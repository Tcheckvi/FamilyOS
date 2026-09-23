from __future__ import annotations

import socket
import ssl
import struct
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from unittest.mock import Mock

import pytest

import familyos_pilot0.custody_mtls_transport as wire
from familyos_pilot0.custody_anchor_protocol import (
    AnchorAction,
    AnchorOutcome,
    AnchorRejected,
    AnchorRequest,
    AnchorUnavailable,
    AnchorUncertain,
)
from familyos_pilot0.custody_mtls_transport import (
    SyntheticMTLSServer,
    SyntheticMTLSTransport,
    certificate_file_sha256,
    synthetic_client_context,
    synthetic_server_context,
)
from familyos_pilot0.custody_rollback_contracts import RollbackCheckpoint, RollbackContractError
from familyos_pilot0.custody_sqlite_witness import (
    SQLiteWitness,
    enroll_synthetic_witness,
)
from familyos_pilot0.custody_usb_witness_head import (
    USBWitnessHead,
    enroll_synthetic_usb_head,
)
from familyos_pilot0.custody_witness_state import canonical, request_document
from familyos_pilot0.custody_worker_runtime import AuthoritativeClaimStore
from tests.custody_sqlite_witness_fixtures import (
    ADMIN,
    IDENTITY,
    READER,
    SECOND,
    WORKER,
)


@dataclass(frozen=True)
class Certificate:
    certificate: Path
    key: Path

    @property
    def fingerprint(self) -> str:
        return certificate_file_sha256(self.certificate)


@dataclass(frozen=True)
class PKI:
    ca: Certificate
    wrong_ca: Certificate
    server: Certificate
    wrong_server: Certificate
    worker: Certificate
    unexpected: Certificate
    wrong_client: Certificate


def _command(*args: str) -> None:
    subprocess.run(
        ["openssl", *args],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def _ca(directory: Path, name: str) -> Certificate:
    cert = Certificate(directory / f"{name}.crt", directory / f"{name}.key")
    _command(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(cert.key),
        "-out",
        str(cert.certificate),
        "-subj",
        f"/CN={name}",
        "-days",
        "1",
    )
    return cert


def _issued(
    directory: Path,
    name: str,
    ca: Certificate,
    *,
    hostname: str | None = None,
) -> Certificate:
    cert = Certificate(directory / f"{name}.crt", directory / f"{name}.key")
    request = directory / f"{name}.csr"
    _command(
        "req",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(cert.key),
        "-out",
        str(request),
        "-subj",
        f"/CN={name}",
    )
    args = [
        "x509",
        "-req",
        "-in",
        str(request),
        "-CA",
        str(ca.certificate),
        "-CAkey",
        str(ca.key),
        "-CAcreateserial",
        "-out",
        str(cert.certificate),
        "-days",
        "1",
    ]
    if hostname is not None:
        extension = directory / f"{name}.ext"
        extension.write_text(f"subjectAltName=DNS:{hostname}\nextendedKeyUsage=serverAuth\n")
        args.extend(["-extfile", str(extension)])
    _command(*args)
    return cert


@pytest.fixture(scope="module")
def pki(tmp_path_factory: pytest.TempPathFactory) -> PKI:
    directory = tmp_path_factory.mktemp("synthetic-pki")
    ca = _ca(directory, "ca")
    wrong_ca = _ca(directory, "wrong-ca")
    return PKI(
        ca,
        wrong_ca,
        _issued(directory, "server", ca, hostname="localhost"),
        _issued(directory, "wrong-server", wrong_ca, hostname="localhost"),
        _issued(directory, "worker", ca),
        _issued(directory, "unexpected", ca),
        _issued(directory, "wrong-client", wrong_ca),
    )


@dataclass
class Rig:
    service: SQLiteWitness
    database: Path
    head_path: Path
    head: USBWitnessHead
    initial: RollbackCheckpoint

    def close(self) -> None:
        self.service.close()


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    initial = AuthoritativeClaimStore.expected_empty_rollback_checkpoint(IDENTITY)
    database = tmp_path / "witness.sqlite3"
    head_path = (tmp_path / "usb" / "head.json").absolute()
    head_path.parent.mkdir()
    enrolled = enroll_synthetic_witness(
        database,
        initial=initial,
        principals=(WORKER, SECOND, READER),
        administrator=ADMIN,
    )
    device = enroll_synthetic_usb_head(
        head_path,
        head=enrolled,
        administrator=ADMIN,
    )
    head = USBWitnessHead(
        head_path,
        identity=IDENTITY,
        expected_directory_device=device,
    )
    value = Rig(
        SQLiteWitness(database, identity=IDENTITY, head=head),
        database,
        head_path,
        head,
        initial,
    )
    try:
        yield value
    finally:
        value.close()


def request(
    rig: Rig,
    action: AnchorAction,
    *,
    principal: str = "worker",
    key: str = "key",
) -> AnchorRequest:
    initial = rig.initial
    return AnchorRequest(
        action,
        principal,
        IDENTITY,
        "session",
        "request",
        expected_current=None if action is AnchorAction.READ else initial,
        candidate=(
            replace(initial, store_generation=1, store_root_digest="b" * 64)
            if action is AnchorAction.ADVANCE
            else None
        ),
        idempotency_key=None if action is AnchorAction.READ else key,
        execution_id="execution" if action is AnchorAction.EXECUTE_ONCE else None,
    )


def server(
    rig: Rig,
    pki: PKI,
    *,
    certificate: Certificate | None = None,
    pins: dict[str, str] | None = None,
    timeout: float = 0.5,
) -> SyntheticMTLSServer:
    selected = certificate or pki.server
    return SyntheticMTLSServer(
        service=rig.service,
        context=synthetic_server_context(
            certificate=selected.certificate,
            private_key=selected.key,
            client_ca=pki.ca.certificate,
        ),
        peer_fingerprints=pins or {pki.worker.fingerprint: "worker"},
        timeout_seconds=timeout,
    )


def transport(
    endpoint: SyntheticMTLSServer,
    pki: PKI,
    *,
    certificate: Certificate | None = None,
    ca: Certificate | None = None,
    hostname: str = "localhost",
    fingerprint: str | None = None,
    no_certificate: bool = False,
    timeout: float = 0.5,
) -> SyntheticMTLSTransport:
    selected = certificate or pki.worker
    context = synthetic_client_context(
        certificate=None if no_certificate else selected.certificate,
        private_key=None if no_certificate else selected.key,
        server_ca=(ca or pki.ca).certificate,
    )
    host, port = endpoint.address
    return SyntheticMTLSTransport(
        host=host,
        port=port,
        server_hostname=hostname,
        context=context,
        expected_server_fingerprint=fingerprint or pki.server.fingerprint,
        timeout_seconds=timeout,
    )


@contextmanager
def serving(endpoint: SyntheticMTLSServer, count: int = 1) -> Iterator[None]:
    outcomes: list[bool] = []

    def run() -> None:
        for _ in range(count):
            outcomes.append(endpoint.serve_once())

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield
    finally:
        thread.join(timeout=3)
        endpoint.close()
        assert not thread.is_alive()
        assert outcomes == [True] * count


def test_valid_mutual_tls_read_advance_execute_and_duplicate(rig: Rig, pki: PKI) -> None:
    endpoint = server(rig, pki)
    client = transport(endpoint, pki)
    read, advance, execute = (
        request(rig, AnchorAction.READ),
        request(rig, AnchorAction.ADVANCE, key="advance"),
        request(rig, AnchorAction.EXECUTE_ONCE, key="execute"),
    )
    with serving(endpoint, 4):
        assert client.exchange(read).outcome is AnchorOutcome.CURRENT
        assert client.exchange(execute).outcome is AnchorOutcome.COMMITTED
        assert client.exchange(execute).outcome is AnchorOutcome.DUPLICATE
        assert client.exchange(advance).outcome is AnchorOutcome.COMMITTED


@pytest.mark.parametrize(
    "error_type", [RollbackContractError, AnchorRejected, AnchorUnavailable, AnchorUncertain]
)
def test_serve_once_contains_contract_errors_and_serves_next_connection(
    rig: Rig,
    pki: PKI,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[RollbackContractError],
) -> None:
    endpoint = server(rig, pki)
    client = transport(endpoint, pki)
    original_handle = endpoint._handle
    handled = 0

    def fail_first_connection(stream: ssl.SSLSocket) -> None:
        nonlocal handled
        handled += 1
        if handled == 1:
            wire._receive_frame(stream, wire.MAX_FRAME_BYTES)
            raise error_type("synthetic escaped contract error")
        original_handle(stream)

    monkeypatch.setattr(endpoint, "_handle", fail_first_connection)
    # The serving helper asserts two True returns, no escaping exception, and termination.
    with serving(endpoint, 2):
        with pytest.raises(AnchorUnavailable):
            client.exchange(request(rig, AnchorAction.READ))
        assert client.exchange(request(rig, AnchorAction.READ)).outcome is AnchorOutcome.CURRENT
    assert handled == 2


@pytest.mark.parametrize("action", [AnchorAction.ADVANCE, AnchorAction.EXECUTE_ONCE])
def test_oversized_local_mutation_is_unavailable_without_network_exposure(
    rig: Rig, pki: PKI, monkeypatch: pytest.MonkeyPatch, action: AnchorAction
) -> None:
    mutation = request(rig, action)
    frame_maximum = len(wire._request_payload(mutation)) - 1
    client = SyntheticMTLSTransport(
        host="127.0.0.1",
        port=1,
        server_hostname="localhost",
        context=synthetic_client_context(
            certificate=pki.worker.certificate,
            private_key=pki.worker.key,
            server_ca=pki.ca.certificate,
        ),
        expected_server_fingerprint=pki.server.fingerprint,
        maximum_frame_bytes=frame_maximum,
    )
    connect = Mock(side_effect=AssertionError("local rejection must precede connection"))
    monkeypatch.setattr(socket, "create_connection", connect)
    previous_head = rig.head.read()
    with pytest.raises(AnchorUnavailable, match="frame exceeds bound") as caught:
        client.exchange(mutation)
    assert type(caught.value) is AnchorUnavailable
    connect.assert_not_called()
    assert rig.head.read() == previous_head


@pytest.mark.parametrize("mode", ["none", "wrong-ca"])
def test_missing_or_wrong_ca_client_certificate_is_rejected(rig: Rig, pki: PKI, mode: str) -> None:
    endpoint = server(rig, pki)
    client = transport(
        endpoint,
        pki,
        certificate=pki.wrong_client if mode == "wrong-ca" else None,
        no_certificate=mode == "none",
    )
    with serving(endpoint), pytest.raises(AnchorUnavailable):
        client.exchange(request(rig, AnchorAction.READ))


def test_unpinned_leaf_and_unknown_authenticated_peer_are_rejected(rig: Rig, pki: PKI) -> None:
    unpinned = server(rig, pki)
    with serving(unpinned), pytest.raises(AnchorRejected, match="not pinned"):
        transport(unpinned, pki, certificate=pki.unexpected).exchange(
            request(rig, AnchorAction.READ)
        )
    unknown = server(rig, pki, pins={pki.worker.fingerprint: "unknown"})
    with serving(unknown), pytest.raises(AnchorRejected, match="not enrolled"):
        transport(unknown, pki).exchange(request(rig, AnchorAction.READ, principal="unknown"))


def test_wrong_server_ca_hostname_and_fingerprint_are_rejected(rig: Rig, pki: PKI) -> None:
    wrong_ca_server = server(rig, pki, certificate=pki.wrong_server)
    with serving(wrong_ca_server), pytest.raises(AnchorUnavailable):
        transport(
            wrong_ca_server,
            pki,
            fingerprint=pki.wrong_server.fingerprint,
        ).exchange(request(rig, AnchorAction.READ))
    wrong_host_server = server(rig, pki)
    with serving(wrong_host_server), pytest.raises(AnchorUnavailable):
        transport(wrong_host_server, pki, hostname="wrong.example").exchange(
            request(rig, AnchorAction.READ)
        )
    wrong_pin_server = server(rig, pki)
    with serving(wrong_pin_server), pytest.raises(AnchorUnavailable):
        transport(
            wrong_pin_server,
            pki,
            fingerprint=pki.unexpected.fingerprint,
        ).exchange(request(rig, AnchorAction.READ))


def test_request_principal_must_match_certificate_pin(rig: Rig, pki: PKI) -> None:
    endpoint = server(rig, pki)
    with serving(endpoint), pytest.raises(AnchorRejected, match="authenticated peer"):
        transport(endpoint, pki).exchange(request(rig, AnchorAction.READ, principal="second"))


def _raw_tls(
    endpoint: SyntheticMTLSServer,
    pki: PKI,
    payload: bytes,
    *,
    declared_size: int | None = None,
) -> bytes:
    host, port = endpoint.address
    context = synthetic_client_context(
        certificate=pki.worker.certificate,
        private_key=pki.worker.key,
        server_ca=pki.ca.certificate,
    )
    with socket.create_connection((host, port), timeout=1) as raw:
        with context.wrap_socket(raw, server_hostname="localhost") as stream:
            stream.settimeout(1)
            stream.sendall(struct.pack("!I", declared_size or len(payload)) + payload)
            return wire._receive_frame(stream, wire.MAX_FRAME_BYTES)


@pytest.mark.parametrize(
    "payload,size",
    [
        (b"not-json", None),
        (b'{ "request":{},"wire_version":"x"}', None),
        (b'{"request":{},"request":{},"wire_version":"x"}', None),
        (b"x", wire.MAX_FRAME_BYTES + 1),
    ],
)
def test_malformed_duplicate_and_oversized_frames_are_rejected(
    rig: Rig, pki: PKI, payload: bytes, size: int | None
) -> None:
    endpoint = server(rig, pki)
    with serving(endpoint):
        response = _raw_tls(endpoint, pki, payload, declared_size=size)
    with pytest.raises(AnchorRejected):
        wire._raise_error_payload(response)


def test_partial_frame_and_stalled_peer_fail_within_deadline(rig: Rig, pki: PKI) -> None:
    endpoint = server(rig, pki, timeout=0.1)
    host, port = endpoint.address
    context = synthetic_client_context(
        certificate=pki.worker.certificate,
        private_key=pki.worker.key,
        server_ca=pki.ca.certificate,
    )
    start = time.monotonic()
    with serving(endpoint), socket.create_connection((host, port), timeout=1) as raw:
        with context.wrap_socket(raw, server_hostname="localhost") as stream:
            stream.sendall(struct.pack("!I", 100) + b"{")
            time.sleep(0.2)
    assert time.monotonic() - start < 1.0


def test_no_admin_or_enrollment_action_exists_on_wire(rig: Rig, pki: PKI) -> None:
    document = request_document(request(rig, AnchorAction.READ))
    document["action"] = "ENROLL"
    payload = canonical({"request": document, "wire_version": wire.WIRE_VERSION}).encode()
    endpoint = server(rig, pki)
    with serving(endpoint):
        response = _raw_tls(endpoint, pki, payload)
    with pytest.raises(AnchorRejected, match="malformed"):
        wire._raise_error_payload(response)


def test_mutating_response_loss_is_uncertain(rig: Rig, pki: PKI) -> None:
    context = synthetic_server_context(
        certificate=pki.server.certificate,
        private_key=pki.server.key,
        client_ca=pki.ca.certificate,
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    host, port = listener.getsockname()[:2]

    def drop_response() -> None:
        raw, _ = listener.accept()
        with raw, context.wrap_socket(raw, server_side=True) as stream:
            stream.settimeout(0.5)
            wire._receive_frame(stream, wire.MAX_FRAME_BYTES)
        listener.close()

    thread = threading.Thread(target=drop_response, daemon=True)
    thread.start()
    client = SyntheticMTLSTransport(
        host=host,
        port=port,
        server_hostname="localhost",
        context=synthetic_client_context(
            certificate=pki.worker.certificate,
            private_key=pki.worker.key,
            server_ca=pki.ca.certificate,
        ),
        expected_server_fingerprint=pki.server.fingerprint,
        timeout_seconds=0.5,
    )
    with pytest.raises(AnchorUncertain, match="commitment is unknown"):
        client.exchange(request(rig, AnchorAction.EXECUTE_ONCE))
    thread.join(timeout=2)
    assert not thread.is_alive()


@pytest.mark.parametrize(
    ("action", "error_type"),
    [
        (AnchorAction.READ, AnchorUnavailable),
        (AnchorAction.EXECUTE_ONCE, AnchorUncertain),
    ],
)
def test_post_service_serialization_failure_preserves_uncertainty(
    rig: Rig,
    pki: PKI,
    monkeypatch: pytest.MonkeyPatch,
    action: AnchorAction,
    error_type: type[Exception],
) -> None:
    def fail_response(_response: object) -> bytes:
        raise ValueError("synthetic serialization failure")

    monkeypatch.setattr(wire, "_response_payload", fail_response)
    endpoint = server(rig, pki)
    with serving(endpoint), pytest.raises(error_type):
        transport(endpoint, pki).exchange(request(rig, action))


def test_real_witness_usb_head_and_mtls_survive_restart(rig: Rig, pki: PKI) -> None:
    endpoint = server(rig, pki)
    client = transport(endpoint, pki)
    mutation = request(rig, AnchorAction.EXECUTE_ONCE, key="durable")
    with serving(endpoint):
        assert client.exchange(mutation).outcome is AnchorOutcome.COMMITTED
    rig.service.close()
    rig.head = USBWitnessHead(
        rig.head_path,
        identity=IDENTITY,
        expected_directory_device=rig.head_path.parent.stat().st_dev,
    )
    rig.service = SQLiteWitness(rig.database, identity=IDENTITY, head=rig.head)
    reopened = server(rig, pki)
    with serving(reopened, 2):
        assert (
            transport(reopened, pki).exchange(request(rig, AnchorAction.READ)).outcome
            is AnchorOutcome.CURRENT
        )
        assert transport(reopened, pki).exchange(mutation).outcome is AnchorOutcome.DUPLICATE


def test_advance_and_current_read_survive_full_service_restart(rig: Rig, pki: PKI) -> None:
    mutation = request(rig, AnchorAction.ADVANCE, key="durable-advance")
    assert mutation.candidate is not None
    endpoint = server(rig, pki)
    with serving(endpoint):
        assert transport(endpoint, pki).exchange(mutation).outcome is AnchorOutcome.COMMITTED
    rig.service.close()
    rig.head = USBWitnessHead(
        rig.head_path,
        identity=IDENTITY,
        expected_directory_device=rig.head_path.parent.stat().st_dev,
    )
    rig.service = SQLiteWitness(rig.database, identity=IDENTITY, head=rig.head)
    reopened = server(rig, pki)
    with serving(reopened):
        response = transport(reopened, pki).exchange(request(rig, AnchorAction.READ))
    assert response.outcome is AnchorOutcome.CURRENT
    assert response.checkpoint == mutation.candidate


def test_head_mismatch_blocks_service(rig: Rig, pki: PKI) -> None:
    old = rig.head_path.read_bytes()
    endpoint = server(rig, pki)
    with serving(endpoint):
        assert (
            transport(endpoint, pki).exchange(request(rig, AnchorAction.EXECUTE_ONCE)).outcome
            is AnchorOutcome.COMMITTED
        )
    rig.service.close()
    rig.head_path.write_bytes(old)
    with pytest.raises(AnchorUnavailable, match="continuity"):
        SQLiteWitness(rig.database, identity=IDENTITY, head=rig.head)


def test_staged_uncertain_mtls_mutation_remains_fail_closed(rig: Rig, pki: PKI) -> None:
    rig.service.close()

    def interrupt(phase: str) -> None:
        if phase == "after_stage":
            raise RuntimeError("synthetic interruption")

    rig.service = SQLiteWitness(
        rig.database,
        identity=IDENTITY,
        head=rig.head,
        fault_injector=interrupt,
    )
    endpoint = server(rig, pki)
    with serving(endpoint), pytest.raises(AnchorUncertain):
        transport(endpoint, pki).exchange(request(rig, AnchorAction.EXECUTE_ONCE))
    rig.service.close()
    with pytest.raises(AnchorUnavailable, match="staged"):
        SQLiteWitness(rig.database, identity=IDENTITY, head=rig.head)
