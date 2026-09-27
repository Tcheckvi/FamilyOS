"""Human-present Phase-1 custody launcher contract.

Native macOS evidence remains injected and separately qualified. This module
implements fail-closed ceremony freshness, trusted UID pinning, and single-use
grant consumption for synthetic repository tests.
"""

from __future__ import annotations

import hashlib
import math
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

PRODUCTION_EXECUTION_AUTHORIZED = False
REAL_CUSTODY_ACCESS_AUTHORIZED = False
REAL_SIGNING_AUTHORIZED = False

MAX_APPROVAL_TTL_SECONDS = 120.0


class CustodyLaunchDenied(RuntimeError):
    """The local custody ceremony does not satisfy the qualified profile."""


@dataclass(frozen=True)
class SessionEvidence:
    real_uid: int
    effective_uid: int
    saved_uid: int
    session_id: str
    local_session: bool
    gui_active: bool
    gui_unlocked: bool
    controlling_tty: bool
    is_admin: bool
    supplementary_admin: bool
    ssh_detected: bool
    su_detected: bool
    remote_control_detected: bool
    automation_detected: bool
    evidence_complete: bool


@dataclass(frozen=True)
class ApprovalRequest:
    operation_id: str
    payload_sha256: str
    nonce: str
    session_id: str
    issued_at: float
    expires_at: float


@dataclass(frozen=True)
class HumanApproval:
    approved: bool
    operation_id: str
    payload_sha256: str
    nonce: str
    session_id: str
    approved_at: float


@dataclass(frozen=True, slots=True)
class CustodyCeremonyGrant:
    """Opaque process-local handle; approved authority stays with the issuer."""

    handle: str


@dataclass(frozen=True)
class _IssuedGrant:
    request: ApprovalRequest
    validated_at: float


class SessionEvidenceProvider(Protocol):
    def current(self) -> SessionEvidence:
        """Return native session evidence for the current invocation."""


class HumanApprovalProvider(Protocol):
    def approve(self, request: ApprovalRequest) -> HumanApproval:
        """Collect fresh approval on the trusted custody surface."""


class HumanPresentCustodyLauncher:
    """Validate one bounded, transaction-specific local custody ceremony."""

    def __init__(
        self,
        *,
        expected_custody_uid: int,
        session_provider: SessionEvidenceProvider,
        approval_provider: HumanApprovalProvider,
        clock: Callable[[], float],
        nonce_factory: Callable[[], str],
        approval_ttl_seconds: float = 60.0,
    ) -> None:
        if type(expected_custody_uid) is not int or expected_custody_uid <= 0:
            raise ValueError("expected_custody_uid must be a positive integer")
        if (
            isinstance(approval_ttl_seconds, bool)
            or not isinstance(approval_ttl_seconds, int | float)
            or not math.isfinite(approval_ttl_seconds)
            or approval_ttl_seconds <= 0
            or approval_ttl_seconds > MAX_APPROVAL_TTL_SECONDS
        ):
            raise ValueError("approval_ttl_seconds is outside the supported range")
        self._expected_custody_uid = expected_custody_uid
        self._session_provider = session_provider
        self._approval_provider = approval_provider
        self._clock = clock
        self._nonce_factory = nonce_factory
        self._approval_ttl_seconds = float(approval_ttl_seconds)
        self._issued_nonces: set[str] = set()
        self._grants: dict[str, _IssuedGrant] = {}
        self._grant_lock = Lock()
        self._issuer_pid = os.getpid()

    def _validate_session(self, evidence: SessionEvidence) -> None:
        expected = self._expected_custody_uid
        if (
            evidence.real_uid != expected
            or evidence.effective_uid != expected
            or evidence.saved_uid != expected
        ):
            raise CustodyLaunchDenied("process identity is not custody-bound")
        if evidence.is_admin or evidence.supplementary_admin:
            raise CustodyLaunchDenied("custody process has administrative authority")
        if not evidence.evidence_complete:
            raise CustodyLaunchDenied("native session evidence is incomplete")
        if not evidence.session_id:
            raise CustodyLaunchDenied("missing login/audit session identity")
        if not evidence.local_session:
            raise CustodyLaunchDenied("session is not qualified as local")
        if not evidence.gui_active or not evidence.gui_unlocked:
            raise CustodyLaunchDenied("custody GUI session is inactive or locked")
        if not evidence.controlling_tty:
            raise CustodyLaunchDenied("supported custody terminal is absent")
        if evidence.ssh_detected:
            raise CustodyLaunchDenied("SSH custody ceremony is forbidden")
        if evidence.su_detected:
            raise CustodyLaunchDenied("su custody ceremony is forbidden")
        if evidence.remote_control_detected:
            raise CustodyLaunchDenied("remote-control custody ceremony is forbidden")
        if evidence.automation_detected:
            raise CustodyLaunchDenied("automated approval surface is forbidden")

    @staticmethod
    def _finite_time(value: float, *, label: str) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise CustodyLaunchDenied(f"{label} is not numeric")
        result = float(value)
        if not math.isfinite(result):
            raise CustodyLaunchDenied(f"{label} is not finite")
        return result

    def authorize(
        self,
        *,
        operation_id: str,
        canonical_payload: bytes,
    ) -> CustodyCeremonyGrant:
        if not operation_id:
            raise CustodyLaunchDenied("operation_id is required")
        if not canonical_payload:
            raise CustodyLaunchDenied("canonical payload is required")

        before = self._session_provider.current()
        self._validate_session(before)

        payload_sha256 = hashlib.sha256(canonical_payload).hexdigest()
        nonce = self._nonce_factory()
        if not nonce:
            raise CustodyLaunchDenied("nonce generation failed")
        with self._grant_lock:
            if nonce in self._issued_nonces:
                raise CustodyLaunchDenied("nonce replay detected")
            self._issued_nonces.add(nonce)

        issued_at = self._finite_time(self._clock(), label="issued_at")
        request = ApprovalRequest(
            operation_id=operation_id,
            payload_sha256=payload_sha256,
            nonce=nonce,
            session_id=before.session_id,
            issued_at=issued_at,
            expires_at=issued_at + self._approval_ttl_seconds,
        )

        approval = self._approval_provider.approve(request)
        after_approval = self._finite_time(self._clock(), label="after_approval")

        if not approval.approved:
            raise CustodyLaunchDenied("human approval denied")
        if approval.operation_id != request.operation_id:
            raise CustodyLaunchDenied("approval operation mismatch")
        if approval.payload_sha256 != request.payload_sha256:
            raise CustodyLaunchDenied("approval payload mismatch")
        if approval.nonce != request.nonce:
            raise CustodyLaunchDenied("approval nonce mismatch")
        if approval.session_id != request.session_id:
            raise CustodyLaunchDenied("approval session mismatch")

        approved_at = self._finite_time(approval.approved_at, label="approved_at")
        if not (request.issued_at <= approved_at <= after_approval <= request.expires_at):
            raise CustodyLaunchDenied("approval time ordering or freshness is invalid")

        after = self._session_provider.current()
        self._validate_session(after)
        if after.session_id != before.session_id:
            raise CustodyLaunchDenied("custody session changed during approval")

        final_now = self._finite_time(self._clock(), label="final_now")
        if final_now < after_approval:
            raise CustodyLaunchDenied("monotonic ceremony clock moved backwards")
        if final_now > request.expires_at:
            raise CustodyLaunchDenied("approval expired during final session validation")

        with self._grant_lock:
            if os.getpid() != self._issuer_pid:
                raise CustodyLaunchDenied("ceremony issuer process changed")
            handle = secrets.token_hex(32)
            if handle in self._grants:
                raise CustodyLaunchDenied("grant handle collision")
            self._grants[handle] = _IssuedGrant(request, final_now)
        return CustodyCeremonyGrant(handle=handle)

    def consume_grant(
        self,
        *,
        grant: CustodyCeremonyGrant,
        operation_id: str,
        canonical_payload: bytes,
    ) -> None:
        """Consume issuer authority once, then validate immediately before progression.

        Copies share one handle. An attempted consumption burns that handle even
        if validation fails. Grants cannot cross issuer instances or processes.
        """

        if os.getpid() != self._issuer_pid:
            raise CustodyLaunchDenied("ceremony issuer process changed")
        if type(grant) is not CustodyCeremonyGrant or type(grant.handle) is not str:
            raise CustodyLaunchDenied("invalid ceremony grant handle")
        with self._grant_lock:
            issued = self._grants.pop(grant.handle, None)
        if issued is None:
            raise CustodyLaunchDenied("unknown or already consumed ceremony grant")

        request = issued.request
        evidence = self._session_provider.current()
        self._validate_session(evidence)
        payload_sha256 = hashlib.sha256(canonical_payload).hexdigest()
        now = self._finite_time(self._clock(), label="grant_consumption_time")
        if now < issued.validated_at:
            raise CustodyLaunchDenied("monotonic ceremony clock moved backwards")
        if now > request.expires_at:
            raise CustodyLaunchDenied("ceremony grant is outside its validity window")
        if operation_id != request.operation_id:
            raise CustodyLaunchDenied("grant operation mismatch")
        if payload_sha256 != request.payload_sha256:
            raise CustodyLaunchDenied("grant payload mismatch")
        if evidence.session_id != request.session_id:
            raise CustodyLaunchDenied("grant session mismatch")


if __name__ == "__main__":
    raise SystemExit(
        "Custody worker unavailable: native session, approval and helper composition "
        "is not qualified. This module is a contract library, not a production entrypoint."
    )
