"""Disposable file-backed head model; not a qualified independent storage device."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from familyos_pilot0.custody_anchor_adapter import ProtocolRollbackAnchor
from familyos_pilot0.custody_anchor_protocol import (
    AnchorPrincipal,
    AnchorProfile,
    AnchorRejected,
    AnchorRight,
    AnchorUnavailable,
    ProfileBoundary,
    ThreatScope,
)
from familyos_pilot0.custody_rollback_contracts import StoreIdentity
from familyos_pilot0.custody_sqlite_witness import (
    SQLiteWitness,
    SyntheticLoopbackTransport,
)
from familyos_pilot0.custody_witness_state import HeadContinuity, WitnessHead

IDENTITY = StoreIdentity("sqlite-witness-test-only", 1)
WORKER = AnchorPrincipal(
    "worker",
    IDENTITY,
    frozenset({AnchorRight.READ, AnchorRight.ADVANCE, AnchorRight.EXECUTE_ONCE}),
)
SECOND = AnchorPrincipal("second", IDENTITY, WORKER.rights)
READER = AnchorPrincipal("reader", IDENTITY, frozenset({AnchorRight.READ}))
ADMIN = AnchorPrincipal(
    "admin", IDENTITY, frozenset({AnchorRight.ENROLL, AnchorRight.RECOVER_ADMIN})
)
BOUNDARY = ProfileBoundary(
    AnchorProfile.INDEPENDENT_SECOND_DEVICE_WITNESS_PROFILE,
    ThreatScope.WHOLE_MAC,
    "synthetic-witness",
    "independent-test-head",
)


class FakeFileHead:
    """Separate controllable fixture file; retains data across service/process restarts.

    Its locking is only process-local; tests never claim cross-process head CAS
    qualification. Deliberate file restoration in tests can violate independence.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.available = True

    def enroll(self, head: WitnessHead, administrator: AnchorPrincipal) -> None:
        if (
            administrator.identity != head.identity
            or AnchorRight.ENROLL not in administrator.rights
        ):
            raise AnchorRejected("test enrollment administrator required")
        with self.path.open("x") as handle:
            handle.write(head.evidence())
            handle.flush()
            os.fsync(handle.fileno())

    def read(self) -> WitnessHead:
        if not self.available or not self.path.is_file():
            raise AnchorUnavailable("test head absent/unavailable")
        obj = json.loads(self.path.read_text())
        return WitnessHead(StoreIdentity(**obj["identity"]), obj["sequence"], obj["state_digest"])

    def compare_and_set(self, expected: WitnessHead, candidate: WitnessHead) -> None:
        with self.lock:
            if self.read() != expected:
                raise AnchorRejected("test head CAS lost")
            if (
                candidate.identity != expected.identity
                or candidate.sequence != expected.sequence + 1
            ):
                raise AnchorRejected("test head must advance exactly once in same lineage")
            temporary = self.path.with_suffix(".temporary")
            with temporary.open("w") as handle:
                handle.write(candidate.evidence())
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)


def adapter(
    service: SQLiteWitness, head: FakeFileHead, principal: AnchorPrincipal = WORKER
) -> ProtocolRollbackAnchor:
    return ProtocolRollbackAnchor(
        transport=SyntheticLoopbackTransport(service, principal.name),
        principal=principal,
        boundary=BOUNDARY,
        continuity=HeadContinuity(head, IDENTITY),
    )
