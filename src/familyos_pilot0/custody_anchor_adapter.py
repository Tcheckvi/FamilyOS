"""Bounded R2C adapter over an explicitly supplied synthetic/qualified transport.

No provider, network client, credentials or persistent witness is implemented here.
Timeout stops waiting, not the underlying call; late mutations remain uncertain.
"""

from __future__ import annotations

import math
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, TimeoutError

from familyos_pilot0.custody_anchor_protocol import (
    AnchorAction,
    AnchorOutcome,
    AnchorPrincipal,
    AnchorProfile,
    AnchorRejected,
    AnchorRequest,
    AnchorResponse,
    AnchorTransport,
    AnchorUnavailable,
    AnchorUncertain,
    ProfileBoundary,
    ThreatScope,
    WitnessContinuity,
)
from familyos_pilot0.custody_rollback_contracts import (
    RollbackCheckpoint,
    require_anchor_advancement,
    require_store_checkpoint_match,
)


class BoundedAnchorCalls:
    """At most one outstanding call per owner; no unbounded executor queue.

    A daemon can outlive a timeout. It has immutable request data, no local store
    lock/file handle and no signer callback. The owner remains busy until it exits.
    Native transports must additionally implement their own cancellation/deadline.
    """

    def __init__(self, timeout_seconds: float) -> None:
        if (
            type(timeout_seconds) not in (float, int)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout must be positive and finite")
        self.timeout_seconds = timeout_seconds
        self._busy = threading.Lock()

    def call[T](self, operation: Callable[[], T], *, mutation: bool) -> T:
        if not self._busy.acquire(blocking=False):
            raise AnchorUnavailable("previous anchor call still outstanding")
        result: Future[T] = Future()

        def run() -> None:
            try:
                value = operation()
            except BaseException as exc:
                # Forward errors to the caller; never convert them into success.
                self._busy.release()
                result.set_exception(exc)
            else:
                self._busy.release()
                result.set_result(value)

        thread = threading.Thread(target=run, daemon=True, name="familyos-anchor-call")
        try:
            thread.start()
        except BaseException:
            self._busy.release()
            raise
        try:
            return result.result(timeout=self.timeout_seconds)
        except TimeoutError as exc:
            if mutation:
                raise AnchorUncertain("anchor mutation timed out; commitment is unknown") from exc
            raise AnchorUnavailable("anchor read timed out") from exc


class ProtocolRollbackAnchor:
    """R2A-compatible checkpoint API with R2C bound responses and execution fencing."""

    def __init__(
        self,
        *,
        transport: AnchorTransport,
        principal: AnchorPrincipal,
        boundary: ProfileBoundary,
        continuity: WitnessContinuity | None,
    ) -> None:
        if (
            boundary.threat is ThreatScope.WITNESS_AND_CORRELATED_RESTORE
            or boundary.profile is not AnchorProfile.PROTECTED_INTERNAL_ANCHOR_PROFILE
        ) and continuity is None:
            raise ValueError("independent witness requires explicit continuity authority")
        self._transport = transport
        self._principal = principal
        self._continuity = continuity
        self._session_id = uuid.uuid4().hex

    def _request(
        self,
        action: AnchorAction,
        *,
        expected: RollbackCheckpoint | None = None,
        candidate: RollbackCheckpoint | None = None,
        execution_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> AnchorRequest:
        self._principal.require(action)
        return AnchorRequest(
            action=action,
            principal=self._principal.name,
            identity=self._principal.identity,
            session_id=self._session_id,
            request_id=uuid.uuid4().hex,
            expected_current=expected,
            candidate=candidate,
            execution_id=execution_id,
            idempotency_key=idempotency_key,
        )

    def _exchange(self, request: AnchorRequest) -> AnchorResponse:
        try:
            response = self._transport.exchange(request)
            if (
                type(response) is not AnchorResponse
                or response.request != request
                or type(response.outcome) is not AnchorOutcome
                or type(response.checkpoint) is not RollbackCheckpoint
                or response.checkpoint.identity != request.identity
            ):
                raise AnchorUnavailable("unbound or malformed anchor response")
            if self._continuity is not None:
                self._continuity.require_current(response)
        except AnchorRejected:
            raise
        except (OSError, AnchorUnavailable) as exc:
            if request.action is not AnchorAction.READ:
                raise AnchorUncertain("mutation response cannot establish commitment") from exc
            raise AnchorUnavailable("no current anchor response") from exc
        if response.outcome is AnchorOutcome.REJECTED:
            raise AnchorRejected("anchor rejected request")
        if response.outcome is AnchorOutcome.UNCERTAIN:
            raise AnchorUncertain("anchor reports uncertain outcome")
        return response

    def read_checkpoint(self) -> RollbackCheckpoint:
        response = self._exchange(self._request(AnchorAction.READ))
        if response.outcome is not AnchorOutcome.CURRENT:
            raise AnchorUnavailable("read did not return current authority")
        return response.checkpoint

    def advance_checkpoint(
        self,
        *,
        expected_current: RollbackCheckpoint,
        candidate: RollbackCheckpoint,
    ) -> None:
        self.advance_idempotent(
            expected_current=expected_current,
            candidate=candidate,
            idempotency_key=uuid.uuid4().hex,
        )

    def advance_idempotent(
        self,
        *,
        expected_current: RollbackCheckpoint,
        candidate: RollbackCheckpoint,
        idempotency_key: str,
    ) -> AnchorOutcome:
        """Bound duplicates acknowledge prior commitment, never signer permission."""
        require_anchor_advancement(current=expected_current, candidate=candidate)
        response = self._exchange(
            self._request(
                AnchorAction.ADVANCE,
                expected=expected_current,
                candidate=candidate,
                idempotency_key=idempotency_key,
            )
        )
        if response.outcome not in (AnchorOutcome.COMMITTED, AnchorOutcome.DUPLICATE):
            raise AnchorUncertain("advance did not confirm commitment")
        require_store_checkpoint_match(observed=candidate, trusted=response.checkpoint)
        return response.outcome

    def acquire_execution(
        self,
        *,
        expected_current: RollbackCheckpoint,
        execution_id: str,
    ) -> None:
        response = self._exchange(
            self._request(
                AnchorAction.EXECUTE_ONCE,
                expected=expected_current,
                execution_id=execution_id,
                idempotency_key=uuid.uuid4().hex,
            )
        )
        if response.outcome is AnchorOutcome.DUPLICATE:
            raise AnchorRejected("execution identity is already consumed")
        if response.outcome is not AnchorOutcome.COMMITTED:
            raise AnchorUncertain("execution consumption is not confirmed")
        require_store_checkpoint_match(observed=expected_current, trusted=response.checkpoint)
