"""Deterministic in-memory R2C service model; never a production anchor.

A model transaction holds one lock across checkpoint, receipts, permanent fences
and the separately retained continuity head. This is an assumed atomic boundary,
not proof that a real two-device transaction can implement it.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass

from familyos_pilot0.custody_anchor_protocol import (
    AnchorAction,
    AnchorOutcome,
    AnchorPrincipal,
    AnchorRejected,
    AnchorRequest,
    AnchorResponse,
    AnchorUnavailable,
)
from familyos_pilot0.custody_rollback_contracts import (
    RollbackCheckpoint,
    RollbackContractError,
    require_anchor_advancement,
)


@dataclass(frozen=True)
class ServiceSnapshot:
    checkpoint: RollbackCheckpoint
    executions: frozenset[str]
    receipts: dict[tuple[str, str], tuple[tuple[object, ...], AnchorOutcome]]


class RetainedContinuity:
    """Synthetic independent head; deliberately not included in service backups."""

    def __init__(self) -> None:
        self.head: str | None = None

    def require_current(self, response: AnchorResponse) -> None:
        if self.head is None or response.continuity_evidence != self.head:
            raise AnchorUnavailable("witness state regressed or continuity is unavailable")


class SyntheticAnchorService:
    """Explicit synthetic enrollment at construction; no runtime enrollment API."""

    def __init__(self, initial: RollbackCheckpoint, principal: AnchorPrincipal) -> None:
        self.checkpoint = initial
        self.principal = principal
        self.executions: set[str] = set()
        self.receipts: dict[tuple[str, str], tuple[tuple[object, ...], AnchorOutcome]] = {}
        self.continuity = RetainedContinuity()
        self.lock = threading.Lock()
        self.available = True
        self.lose_reply = False
        self.mutations = 0
        self.continuity.head = self._stamp()

    def _stamp(self) -> str:
        state = (self.checkpoint, sorted(self.executions), sorted(self.receipts.items()))
        return hashlib.sha256(repr(state).encode()).hexdigest()

    def snapshot(self) -> ServiceSnapshot:
        with self.lock:
            return ServiceSnapshot(self.checkpoint, frozenset(self.executions), dict(self.receipts))

    def restore_for_test(self, snapshot: ServiceSnapshot, *, correlated: bool = False) -> None:
        with self.lock:
            self.checkpoint = snapshot.checkpoint
            self.executions = set(snapshot.executions)
            self.receipts = dict(snapshot.receipts)
            if correlated:
                # This intentionally violates independence to demonstrate its limit.
                self.continuity.head = self._stamp()

    def exchange(self, request: AnchorRequest) -> AnchorResponse:
        with self.lock:
            if not self.available:
                raise AnchorUnavailable("synthetic outage")
            if (
                request.principal != self.principal.name
                or request.identity != self.principal.identity
            ):
                raise AnchorRejected("transport principal/store mismatch")
            self.principal.require(request.action)
            before = self._stamp()
            if before != self.continuity.head:
                raise AnchorUnavailable("restored service cannot serve old authority")
            if request.action is AnchorAction.READ:
                return AnchorResponse(request, AnchorOutcome.CURRENT, self.checkpoint, before)
            assert request.idempotency_key is not None
            key = (request.principal, request.idempotency_key)
            content = request.mutation_content()
            existing = self.receipts.get(key)
            if existing is not None:
                outcome = (
                    AnchorOutcome.DUPLICATE if existing[0] == content else AnchorOutcome.REJECTED
                )
                return AnchorResponse(request, outcome, self.checkpoint, before)
            if request.expected_current != self.checkpoint:
                return AnchorResponse(request, AnchorOutcome.REJECTED, self.checkpoint, before)
            if request.action is AnchorAction.ADVANCE:
                assert request.candidate is not None
                try:
                    require_anchor_advancement(current=self.checkpoint, candidate=request.candidate)
                except RollbackContractError:
                    return AnchorResponse(request, AnchorOutcome.REJECTED, self.checkpoint, before)
                self.checkpoint = request.candidate
            else:
                assert request.execution_id is not None
                if request.execution_id in self.executions:
                    return AnchorResponse(request, AnchorOutcome.REJECTED, self.checkpoint, before)
                self.executions.add(request.execution_id)
            self.receipts[key] = (content, AnchorOutcome.COMMITTED)
            self.mutations += 1
            self.continuity.head = self._stamp()
            if self.lose_reply:
                self.lose_reply = False
                raise OSError("synthetic commit followed by lost reply")
            return AnchorResponse(
                request, AnchorOutcome.COMMITTED, self.checkpoint, self.continuity.head
            )
