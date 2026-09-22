"""R2C provider-neutral anchor protocol; no credentials or production implementation.

The transport is an authenticated, current authority, not an arbitrary HTTP client.
An execution fence is a permanent consumption record, never an expiring lease.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from familyos_pilot0.custody_rollback_contracts import (
    RollbackCheckpoint,
    RollbackContractError,
    RollbackVerificationDecision,
    StoreIdentity,
    verify_store_checkpoint,
)

PROTOCOL_VERSION = "familyos.anchor.r2c.v1"


class AnchorUnavailable(RollbackContractError):
    """No authoritative result is available; do not use cached authority."""


class AnchorRejected(RollbackContractError):
    """The requested mutation was definitely rejected."""


class AnchorUncertain(RollbackContractError):
    """A mutation may have committed; neither retry-to-sign nor repair is allowed."""


class AnchorProfile(StrEnum):
    PROTECTED_INTERNAL_ANCHOR_PROFILE = "PROTECTED_INTERNAL_ANCHOR_PROFILE"
    INDEPENDENT_SECOND_DEVICE_WITNESS_PROFILE = "INDEPENDENT_SECOND_DEVICE_WITNESS_PROFILE"
    REMOTE_CLOUD_WITNESS_PROFILE = "REMOTE_CLOUD_WITNESS_PROFILE"


class ThreatScope(StrEnum):
    EXTERNAL_DISK = "EXTERNAL_DISK"
    WHOLE_MAC = "WHOLE_MAC"
    WITNESS_AND_CORRELATED_RESTORE = "WITNESS_AND_CORRELATED_RESTORE"


@dataclass(frozen=True)
class ProfileBoundary:
    """A declared qualification target, never evidence or production selection."""

    profile: AnchorProfile
    threat: ThreatScope
    trusted_domain: str
    recovery_domain: str

    def __post_init__(self) -> None:
        if type(self.profile) is not AnchorProfile or type(self.threat) is not ThreatScope:
            raise ValueError("profile and threat must be exact enums")
        if not self.trusted_domain or not self.recovery_domain:
            raise ValueError("explicit trusted and recovery domains are required")
        if (
            self.profile is AnchorProfile.PROTECTED_INTERNAL_ANCHOR_PROFILE
            and self.threat is not ThreatScope.EXTERNAL_DISK
        ):
            raise ValueError("internal profile requires trusted Mac / external-only threat")
        if (
            self.threat is ThreatScope.WITNESS_AND_CORRELATED_RESTORE
            and self.trusted_domain == self.recovery_domain
        ):
            raise ValueError("correlated restore requires a separate surviving authority")


class AnchorAction(StrEnum):
    READ = "READ"
    ADVANCE = "ADVANCE"
    EXECUTE_ONCE = "EXECUTE_ONCE"


class AnchorOutcome(StrEnum):
    CURRENT = "CURRENT"
    COMMITTED = "COMMITTED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"
    UNCERTAIN = "UNCERTAIN"


class AnchorRight(StrEnum):
    READ = "READ"
    ADVANCE = "ADVANCE"
    EXECUTE_ONCE = "EXECUTE_ONCE"
    ENROLL = "ENROLL"
    RECOVER_ADMIN = "RECOVER_ADMIN"


@dataclass(frozen=True)
class AnchorPrincipal:
    """Transport-authenticated identity; runtime credentials grant no admin rights."""

    name: str
    identity: StoreIdentity
    rights: frozenset[AnchorRight]

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name or len(self.name) > 128:
            raise ValueError("principal name must be bounded and nonempty")
        if type(self.identity) is not StoreIdentity or type(self.rights) is not frozenset:
            raise ValueError("invalid principal binding")
        if any(type(right) is not AnchorRight for right in self.rights):
            raise ValueError("invalid principal rights")

    def require(self, action: AnchorAction) -> None:
        if AnchorRight(action.value) not in self.rights:
            raise AnchorRejected("principal lacks requested runtime authority")


@dataclass(frozen=True)
class AnchorRequest:
    """Exact request/session binding; authenticated transport supplies the principal."""

    action: AnchorAction
    principal: str
    identity: StoreIdentity
    session_id: str
    request_id: str
    expected_current: RollbackCheckpoint | None = None
    candidate: RollbackCheckpoint | None = None
    idempotency_key: str | None = None
    execution_id: str | None = None
    protocol_version: str = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if type(self.action) is not AnchorAction or type(self.identity) is not StoreIdentity:
            raise ValueError("invalid request action or identity")
        if self.protocol_version != PROTOCOL_VERSION:
            raise ValueError("unsupported anchor protocol")
        for value in (self.principal, self.session_id, self.request_id):
            if type(value) is not str or not value or len(value) > 128:
                raise ValueError("invalid request binding")
        for optional in (self.idempotency_key, self.execution_id):
            if optional is not None and (
                type(optional) is not str or not optional or len(optional) > 128
            ):
                raise ValueError("invalid mutation identifier")
        for checkpoint in (self.expected_current, self.candidate):
            if checkpoint is not None and (
                type(checkpoint) is not RollbackCheckpoint or checkpoint.identity != self.identity
            ):
                raise ValueError("checkpoint does not belong to bound store")
        if self.action is AnchorAction.READ:
            if any(
                x is not None
                for x in (
                    self.expected_current,
                    self.candidate,
                    self.idempotency_key,
                    self.execution_id,
                )
            ):
                raise ValueError("read cannot carry mutation fields")
        elif self.expected_current is None or self.idempotency_key is None:
            raise ValueError("mutation requires expected checkpoint and idempotency key")
        elif self.action is AnchorAction.ADVANCE:
            if self.candidate is None or self.execution_id is not None:
                raise ValueError("advance requires only a candidate")
        elif self.execution_id is None or self.candidate is not None:
            raise ValueError("execution requires only a permanent execution identifier")

    def mutation_content(self) -> tuple[object, ...]:
        """Exclude exchange/session IDs; bind deduplication to all mutation semantics."""
        return (
            self.protocol_version,
            self.principal,
            self.identity,
            self.action,
            self.expected_current,
            self.candidate,
            self.execution_id,
        )


@dataclass(frozen=True)
class AnchorResponse:
    """A response is current only through a qualified transport and continuity check."""

    request: AnchorRequest
    outcome: AnchorOutcome
    checkpoint: RollbackCheckpoint
    continuity_evidence: str


class AnchorTransport(Protocol):
    """Authenticate both ends; execute linearizable reads and atomic durable mutations.

    Commit checkpoint/fence, deduplication outcome and continuity evidence together.
    A restored service must not serve authority before continuity is established.
    No enrollment/reset/recovery endpoint is exposed by this runtime interface.
    """

    def exchange(self, request: AnchorRequest) -> AnchorResponse: ...


class WitnessContinuity(Protocol):
    """Verify latest witness state using authority outside its restore domain.

    Evidence covers checkpoint AND execution tombstones/idempotency state. A nonce,
    signature, timestamp or co-restored revision alone does not implement this.
    No automatic enrollment or learn-first-value behavior is permitted.
    """

    def require_current(self, response: AnchorResponse) -> None: ...


@runtime_checkable
class ExecutionFenceAnchor(Protocol):
    """Permanently consume execution identity under exact current-checkpoint CAS.

    Return only for the first confirmed consumption. All duplicates, uncertainty
    and restarts deny. Records have no expiry/release/reset in the runtime API.
    """

    def acquire_execution(
        self, *, expected_current: RollbackCheckpoint, execution_id: str
    ) -> None: ...


class RecoveryState(StrEnum):
    EXACT_NO_EXECUTION_AUTHORITY = "EXACT_NO_EXECUTION_AUTHORITY"
    EXACT_AFTER_UNCERTAINTY_BLOCKED = "EXACT_AFTER_UNCERTAINTY_BLOCKED"
    LOCAL_AHEAD_BLOCKED = "LOCAL_AHEAD_BLOCKED"
    LOCAL_ROLLBACK_BLOCKED = "LOCAL_ROLLBACK_BLOCKED"
    DIVERGENCE_BLOCKED = "DIVERGENCE_BLOCKED"
    WRONG_LINEAGE_BLOCKED = "WRONG_LINEAGE_BLOCKED"
    UNAVAILABLE_BLOCKED = "UNAVAILABLE_BLOCKED"
    HISTORY_LOST_PERMANENTLY_BLOCKED = "HISTORY_LOST_PERMANENTLY_BLOCKED"


def classify_recovery(
    *,
    local: RollbackCheckpoint,
    trusted: RollbackCheckpoint | None,
    uncertain: bool = False,
    history_lost: bool = False,
) -> RecoveryState:
    """Deny-only diagnosis; no result authorizes a signer or mutates either side."""
    if type(uncertain) is not bool or type(history_lost) is not bool:
        raise ValueError("recovery evidence flags must be exact booleans")
    if history_lost:
        return RecoveryState.HISTORY_LOST_PERMANENTLY_BLOCKED
    if trusted is None:
        return RecoveryState.UNAVAILABLE_BLOCKED
    decision = verify_store_checkpoint(observed=local, trusted=trusted)
    if decision is RollbackVerificationDecision.MATCH:
        return (
            RecoveryState.EXACT_AFTER_UNCERTAINTY_BLOCKED
            if uncertain
            else RecoveryState.EXACT_NO_EXECUTION_AUTHORITY
        )
    return {
        RollbackVerificationDecision.ROLLBACK_DETECTED: RecoveryState.LOCAL_ROLLBACK_BLOCKED,
        RollbackVerificationDecision.ANCHOR_LAG_OR_UNCERTAIN: RecoveryState.LOCAL_AHEAD_BLOCKED,
        RollbackVerificationDecision.DIVERGENCE: RecoveryState.DIVERGENCE_BLOCKED,
        RollbackVerificationDecision.WRONG_STORE: RecoveryState.WRONG_LINEAGE_BLOCKED,
    }[decision]
