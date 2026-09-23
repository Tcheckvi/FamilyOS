"""Synthetic TLS 1.3 transport for the R2C witness exchange contract.

The peer certificate fingerprint, not request content or certificate CN text,
selects the already-enrolled runtime principal.  This module exposes exactly one
bounded request/response exchange per connection and no administrative endpoint.
"""

from __future__ import annotations

import hashlib
import json
import math
import socket
import ssl
import struct
import time
from collections.abc import Mapping
from pathlib import Path
from typing import NoReturn, cast

from familyos_pilot0.custody_anchor_protocol import (
    AnchorAction,
    AnchorOutcome,
    AnchorRejected,
    AnchorRequest,
    AnchorResponse,
    AnchorUnavailable,
    AnchorUncertain,
)
from familyos_pilot0.custody_rollback_contracts import RollbackContractError
from familyos_pilot0.custody_sqlite_witness import SQLiteWitness
from familyos_pilot0.custody_witness_state import (
    canonical,
    checkpoint_document,
    checkpoint_from,
    mapping,
    request_document,
    request_from,
    text_value,
)

WIRE_VERSION = "familyos.synthetic-mtls.v1"
MAX_FRAME_BYTES = 32_768
_HEADER_BYTES = 4


def certificate_sha256(der_certificate: bytes) -> str:
    if type(der_certificate) is not bytes or not der_certificate:
        raise ValueError("nonempty DER certificate required")
    return hashlib.sha256(der_certificate).hexdigest()


def certificate_file_sha256(path: Path) -> str:
    try:
        der = ssl.PEM_cert_to_DER_cert(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError("valid PEM certificate required") from exc
    return certificate_sha256(der)


def synthetic_server_context(
    *, certificate: Path, private_key: Path, client_ca: Path
) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_cert_chain(certificate, private_key)
    context.load_verify_locations(cafile=client_ca)
    return context


def synthetic_client_context(
    *, certificate: Path | None, private_key: Path | None, server_ca: Path
) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    context.load_verify_locations(cafile=server_ca)
    if (certificate is None) != (private_key is None):
        raise ValueError("client certificate and key must be supplied together")
    if certificate is not None and private_key is not None:
        context.load_cert_chain(certificate, private_key)
    return context


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _canonical_json(raw: bytes) -> object:
    if not raw or len(raw) > MAX_FRAME_BYTES:
        raise ValueError("invalid frame size")
    try:
        text = raw.decode("ascii")
        value = json.loads(text, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("malformed JSON frame") from exc
    if canonical(value) != text:
        raise ValueError("noncanonical JSON frame")
    return value


def _request_payload(request: AnchorRequest) -> bytes:
    return canonical({"request": request_document(request), "wire_version": WIRE_VERSION}).encode()


def _request_from_payload(raw: bytes) -> AnchorRequest:
    obj = mapping(_canonical_json(raw), {"request", "wire_version"})
    if obj["wire_version"] != WIRE_VERSION:
        raise ValueError("unsupported synthetic wire version")
    request = request_from(obj["request"])
    if _request_payload(request) != raw:
        raise ValueError("request is not exact canonical representation")
    return request


def _response_payload(response: AnchorResponse) -> bytes:
    if type(response) is not AnchorResponse:
        raise ValueError("exact anchor response required")
    return canonical(
        {
            "response": {
                "checkpoint": checkpoint_document(response.checkpoint),
                "continuity_evidence": response.continuity_evidence,
                "outcome": response.outcome.value,
                "request": request_document(response.request),
            },
            "wire_version": WIRE_VERSION,
        }
    ).encode()


def _response_from_payload(raw: bytes) -> AnchorResponse:
    envelope = mapping(_canonical_json(raw), {"response", "wire_version"})
    if envelope["wire_version"] != WIRE_VERSION:
        raise ValueError("unsupported synthetic wire version")
    obj = mapping(
        envelope["response"],
        {"checkpoint", "continuity_evidence", "outcome", "request"},
    )
    response = AnchorResponse(
        request=request_from(obj["request"]),
        outcome=AnchorOutcome(text_value(obj["outcome"])),
        checkpoint=checkpoint_from(obj["checkpoint"]),
        continuity_evidence=_evidence_value(obj["continuity_evidence"]),
    )
    if _response_payload(response) != raw:
        raise ValueError("response is not exact canonical representation")
    return response


def _evidence_value(value: object) -> str:
    if type(value) is not str or not value or len(value.encode()) > 4_096:
        raise ValueError("invalid bounded continuity evidence")
    return value


def _error_payload(error: BaseException) -> bytes:
    kind = type(error).__name__
    if kind not in {"AnchorRejected", "AnchorUnavailable", "AnchorUncertain"}:
        kind = "AnchorUnavailable"
    message = str(error)[:128] or "synthetic witness exchange failed"
    return canonical(
        {
            "error": {"kind": kind, "message": message},
            "wire_version": WIRE_VERSION,
        }
    ).encode()


def _raise_error_payload(raw: bytes) -> NoReturn:
    envelope = mapping(_canonical_json(raw), {"error", "wire_version"})
    if envelope["wire_version"] != WIRE_VERSION:
        raise AnchorUnavailable("unsupported synthetic wire version")
    obj = mapping(envelope["error"], {"kind", "message"})
    kind, message = text_value(obj["kind"]), text_value(obj["message"])
    error_type = {
        "AnchorRejected": AnchorRejected,
        "AnchorUnavailable": AnchorUnavailable,
        "AnchorUncertain": AnchorUncertain,
    }.get(kind)
    if error_type is None:
        raise AnchorUnavailable("unknown synthetic server error")
    raise error_type(message)


def _frame_bytes(payload: bytes, maximum: int) -> bytes:
    if not payload or len(payload) > maximum:
        raise AnchorUnavailable("synthetic frame exceeds bound")
    return struct.pack("!I", len(payload)) + payload


def _send_frame(stream: ssl.SSLSocket, payload: bytes, maximum: int) -> None:
    stream.sendall(_frame_bytes(payload, maximum))


def _receive_exact(stream: ssl.SSLSocket, size: int, deadline: float) -> bytes:
    parts: list[bytes] = []
    remaining = size
    while remaining:
        available = deadline - time.monotonic()
        if available <= 0:
            raise AnchorUnavailable("synthetic frame read deadline exceeded")
        stream.settimeout(available)
        part = stream.recv(remaining)
        if not part:
            raise AnchorUnavailable("truncated synthetic frame")
        parts.append(part)
        remaining -= len(part)
    return b"".join(parts)


def _receive_frame(stream: ssl.SSLSocket, maximum: int) -> bytes:
    timeout = stream.gettimeout()
    if timeout is None or timeout <= 0:
        raise AnchorUnavailable("explicit frame read deadline required")
    deadline = time.monotonic() + timeout
    header = _receive_exact(stream, _HEADER_BYTES, deadline)
    size = struct.unpack("!I", header)[0]
    if size == 0 or size > maximum:
        raise AnchorRejected("invalid synthetic frame length")
    return _receive_exact(stream, size, deadline)


class SyntheticMTLSServer:
    """Single-process synthetic server; callers own its bounded serving loop."""

    def __init__(
        self,
        *,
        service: SQLiteWitness,
        context: ssl.SSLContext,
        peer_fingerprints: Mapping[str, str],
        host: str = "127.0.0.1",
        port: int = 0,
        timeout_seconds: float = 1.0,
        maximum_frame_bytes: int = MAX_FRAME_BYTES,
    ) -> None:
        if context.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError("server TLS must require client certificates")
        if context.minimum_version != ssl.TLSVersion.TLSv1_3:
            raise ValueError("server TLS minimum must be TLS 1.3")
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("positive socket deadline required")
        if type(maximum_frame_bytes) is not int or not 1 <= maximum_frame_bytes <= MAX_FRAME_BYTES:
            raise ValueError("invalid synthetic frame bound")
        peers: dict[str, str] = {}
        for fingerprint, principal in peer_fingerprints.items():
            normalized = _fingerprint(fingerprint)
            if type(principal) is not str or not principal or len(principal) > 128:
                raise ValueError("invalid pinned principal")
            if normalized in peers:
                raise ValueError("duplicate pinned certificate")
            peers[normalized] = principal
        if not peers:
            raise ValueError("at least one explicit certificate pin is required")
        self._service = service
        self._context = context
        self._peers = peers
        self._timeout = float(timeout_seconds)
        self._maximum = maximum_frame_bytes
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind((host, port))
        self._listener.listen(8)
        self._listener.settimeout(self._timeout)

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._listener.getsockname()[:2]
        return cast(tuple[str, int], (host, port))

    def close(self) -> None:
        self._listener.close()

    def serve_once(self) -> bool:
        """Serve at most one connection; return false only for accept timeout."""
        try:
            raw, _ = self._listener.accept()
        except TimeoutError:
            return False
        with raw:
            raw.settimeout(self._timeout)
            try:
                with self._context.wrap_socket(raw, server_side=True) as stream:
                    stream.settimeout(self._timeout)
                    self._handle(stream)
            except (OSError, ssl.SSLError, TimeoutError, RollbackContractError):
                pass
        return True

    def _handle(self, stream: ssl.SSLSocket) -> None:
        certificate = stream.getpeercert(binary_form=True)
        if certificate is None:
            raise AnchorRejected("TLS peer did not present a certificate")
        principal = self._peers.get(certificate_sha256(certificate))
        if principal is None:
            _send_frame(
                stream,
                _error_payload(AnchorRejected("client certificate is not pinned")),
                self._maximum,
            )
            return
        try:
            request = _request_from_payload(_receive_frame(stream, self._maximum))
        except (AnchorRejected, ValueError, TypeError, RecursionError):
            payload = _error_payload(AnchorRejected("malformed synthetic request"))
            _send_frame(stream, payload, self._maximum)
            return
        except (AnchorUnavailable, AnchorUncertain) as exc:
            _send_frame(stream, _error_payload(exc), self._maximum)
            return
        try:
            response = self._service.exchange_for_peer(
                request,
                authenticated_peer=principal,
            )
        except (AnchorRejected, AnchorUnavailable, AnchorUncertain) as exc:
            payload = _error_payload(exc)
        else:
            try:
                payload = _response_payload(response)
            except (ValueError, TypeError, RecursionError):
                error: BaseException
                if request.action is AnchorAction.READ:
                    error = AnchorUnavailable("read response serialization failed")
                else:
                    error = AnchorUncertain("mutation response serialization failed")
                payload = _error_payload(error)
        _send_frame(stream, payload, self._maximum)


class SyntheticMTLSTransport:
    """Pinned TLS client implementing one R2C exchange per connection."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        server_hostname: str,
        context: ssl.SSLContext,
        expected_server_fingerprint: str,
        timeout_seconds: float = 1.0,
        maximum_frame_bytes: int = MAX_FRAME_BYTES,
    ) -> None:
        if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError("client TLS must verify CA and hostname")
        if context.minimum_version != ssl.TLSVersion.TLSv1_3:
            raise ValueError("client TLS minimum must be TLS 1.3")
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("positive socket deadline required")
        if type(maximum_frame_bytes) is not int or not 1 <= maximum_frame_bytes <= MAX_FRAME_BYTES:
            raise ValueError("invalid synthetic frame bound")
        self._host = host
        self._port = port
        self._server_hostname = server_hostname
        self._context = context
        self._expected_server = _fingerprint(expected_server_fingerprint)
        self._timeout = float(timeout_seconds)
        self._maximum = maximum_frame_bytes

    def exchange(self, request: AnchorRequest) -> AnchorResponse:
        payload = _request_payload(request)
        frame = _frame_bytes(payload, self._maximum)
        exposed = False
        try:
            with socket.create_connection((self._host, self._port), timeout=self._timeout) as raw:
                raw.settimeout(self._timeout)
                with self._context.wrap_socket(
                    raw,
                    server_hostname=self._server_hostname,
                ) as stream:
                    stream.settimeout(self._timeout)
                    certificate = stream.getpeercert(binary_form=True)
                    if certificate is None:
                        raise AnchorUnavailable("server certificate is unavailable")
                    if certificate_sha256(certificate) != self._expected_server:
                        raise AnchorUnavailable("server certificate fingerprint mismatch")
                    exposed = True
                    stream.sendall(frame)
                    response_raw = _receive_frame(stream, self._maximum)
        except AnchorRejected:
            raise
        except AnchorUncertain:
            raise
        except (OSError, ssl.SSLError, TimeoutError, AnchorUnavailable) as exc:
            if exposed and request.action is not AnchorAction.READ:
                raise AnchorUncertain("mTLS mutation response lost; commitment is unknown") from exc
            raise AnchorUnavailable("mTLS witness exchange unavailable") from exc
        try:
            envelope = _canonical_json(response_raw)
            if type(envelope) is dict and "error" in envelope:
                _raise_error_payload(response_raw)
            response = _response_from_payload(response_raw)
        except (AnchorRejected, AnchorUnavailable, AnchorUncertain):
            raise
        except (ValueError, TypeError, RecursionError) as exc:
            if request.action is not AnchorAction.READ:
                raise AnchorUncertain("malformed mutation response") from exc
            raise AnchorUnavailable("malformed read response") from exc
        if response.request != request:
            if request.action is not AnchorAction.READ:
                raise AnchorUncertain("mutation response is not bound to request")
            raise AnchorUnavailable("read response is not bound to request")
        return response


def _fingerprint(value: str) -> str:
    if type(value) is not str:
        raise ValueError("certificate fingerprint must be text")
    normalized = value.lower()
    if len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized):
        raise ValueError("exact SHA-256 certificate fingerprint required")
    return normalized
