"""Pure anti-rollback contracts for the FamilyOS custody claim store.

This module defines the contract boundary for detecting external rollback of an
authoritative claim store. It does not select or implement a production trust
anchor and performs no I/O, key access, signing, or replay-state mutation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

_STORE_INSTANCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RollbackContractError(ValueError):
    """Base error for anti-rollback contract violations."""


class InvalidCheckpointError(RollbackContractError):
    """Raised when a rollback checkpoint is malformed."""


class RollbackRejectedError(RollbackContractError):
    """Raised when a store checkpoint is not admissible against its anchor."""

    def __init__(self, decision: RollbackVerificationDecision) -> None:
        self.decision = decision
        super().__init__(
            f"store checkpoint rejected by rollback contract: {decision.value}"
        )


class RollbackVerificationDecision(StrEnum):
    """Result of comparing an observed store checkpoint to a trusted anchor."""

    MATCH = "MATCH"
    ROLLBACK_DETECTED = "ROLLBACK_DETECTED"
    DIVERGENCE = "DIVERGENCE"
    WRONG_STORE = "WRONG_STORE"
    ANCHOR_LAG_OR_UNCERTAIN = "ANCHOR_LAG_OR_UNCERTAIN"


class AnchorAdvanceDecision(StrEnum):
    """Result of validating a proposed monotonic trust-anchor advancement."""

    ADVANCE_ALLOWED = "ADVANCE_ALLOWED"
    ALREADY_CURRENT = "ALREADY_CURRENT"
    STALE_CANDIDATE = "STALE_CANDIDATE"
    DIVERGENCE = "DIVERGENCE"
    WRONG_STORE = "WRONG_STORE"
    EPOCH_TRANSITION_REQUIRES_REPROVISIONING = (
        "EPOCH_TRANSITION_REQUIRES_REPROVISIONING"
    )


@dataclass(frozen=True, slots=True)
class StoreIdentity:
    """Stable identity for one authoritative store lineage."""

    store_instance_id: str
    store_epoch: int

    def __post_init__(self) -> None:
        if type(self.store_instance_id) is not str:
            raise InvalidCheckpointError("store_instance_id must be an exact string")
        if not _STORE_INSTANCE_RE.fullmatch(self.store_instance_id):
            raise InvalidCheckpointError("store_instance_id is not a valid identifier")
        if type(self.store_epoch) is not int or self.store_epoch < 0:
            raise InvalidCheckpointError("store_epoch must be a non-negative exact int")


@dataclass(frozen=True, slots=True)
class RollbackCheckpoint:
    """Checkpoint committed by a store and compared to an external trust anchor."""

    identity: StoreIdentity
    store_generation: int
    store_root_digest: str

    def __post_init__(self) -> None:
        if type(self.identity) is not StoreIdentity:
            raise InvalidCheckpointError("identity must be an exact StoreIdentity")
        if type(self.store_generation) is not int or self.store_generation < 0:
            raise InvalidCheckpointError(
                "store_generation must be a non-negative exact int"
            )
        if type(self.store_root_digest) is not str:
            raise InvalidCheckpointError("store_root_digest must be an exact string")
        if not _SHA256_RE.fullmatch(self.store_root_digest):
            raise InvalidCheckpointError(
                "store_root_digest must be 64 lowercase hexadecimal characters"
            )


@runtime_checkable
class ExternalRollbackAnchor(Protocol):
    """Interface implemented by an independent anti-rollback trust anchor.

    Production selection and implementation of this interface are deliberately
    outside the R2A contract slice.
    """

    def read_checkpoint(self) -> RollbackCheckpoint:
        """Return the currently trusted checkpoint."""
        ...

    def advance_checkpoint(
        self,
        *,
        expected_current: RollbackCheckpoint,
        candidate: RollbackCheckpoint,
    ) -> None:
        """Atomically advance from expected_current to candidate or fail."""
        ...


def verify_store_checkpoint(
    *,
    observed: RollbackCheckpoint,
    trusted: RollbackCheckpoint,
) -> RollbackVerificationDecision:
    """Compare an observed store checkpoint with the independently trusted one."""

    _require_checkpoint(observed, name="observed")
    _require_checkpoint(trusted, name="trusted")

    if observed.identity.store_instance_id != trusted.identity.store_instance_id:
        return RollbackVerificationDecision.WRONG_STORE

    if observed.identity.store_epoch < trusted.identity.store_epoch:
        return RollbackVerificationDecision.ROLLBACK_DETECTED
    if observed.identity.store_epoch > trusted.identity.store_epoch:
        return RollbackVerificationDecision.ANCHOR_LAG_OR_UNCERTAIN

    if observed.store_generation < trusted.store_generation:
        return RollbackVerificationDecision.ROLLBACK_DETECTED
    if observed.store_generation > trusted.store_generation:
        return RollbackVerificationDecision.ANCHOR_LAG_OR_UNCERTAIN

    if observed.store_root_digest != trusted.store_root_digest:
        return RollbackVerificationDecision.DIVERGENCE

    return RollbackVerificationDecision.MATCH


def require_store_checkpoint_match(
    *,
    observed: RollbackCheckpoint,
    trusted: RollbackCheckpoint,
) -> None:
    """Fail closed unless the store exactly matches the trusted checkpoint."""

    decision = verify_store_checkpoint(observed=observed, trusted=trusted)
    if decision is not RollbackVerificationDecision.MATCH:
        raise RollbackRejectedError(decision)


def validate_anchor_advancement(
    *,
    current: RollbackCheckpoint,
    candidate: RollbackCheckpoint,
) -> AnchorAdvanceDecision:
    """Validate a candidate monotonic anchor advancement.

    Epoch transitions are never automatic in this contract. They require a
    separately governed re-provisioning decision.
    """

    _require_checkpoint(current, name="current")
    _require_checkpoint(candidate, name="candidate")

    if candidate.identity.store_instance_id != current.identity.store_instance_id:
        return AnchorAdvanceDecision.WRONG_STORE

    if candidate.identity.store_epoch < current.identity.store_epoch:
        return AnchorAdvanceDecision.STALE_CANDIDATE
    if candidate.identity.store_epoch > current.identity.store_epoch:
        return AnchorAdvanceDecision.EPOCH_TRANSITION_REQUIRES_REPROVISIONING

    if candidate.store_generation < current.store_generation:
        return AnchorAdvanceDecision.STALE_CANDIDATE

    if candidate.store_generation == current.store_generation:
        if candidate.store_root_digest == current.store_root_digest:
            return AnchorAdvanceDecision.ALREADY_CURRENT
        return AnchorAdvanceDecision.DIVERGENCE

    return AnchorAdvanceDecision.ADVANCE_ALLOWED


def require_anchor_advancement(
    *,
    current: RollbackCheckpoint,
    candidate: RollbackCheckpoint,
) -> None:
    """Fail unless candidate is a permitted monotonic anchor advancement."""

    decision = validate_anchor_advancement(current=current, candidate=candidate)
    if decision is not AnchorAdvanceDecision.ADVANCE_ALLOWED:
        raise RollbackContractError(
            f"anchor advancement rejected by rollback contract: {decision.value}"
        )


def _require_checkpoint(value: object, *, name: str) -> RollbackCheckpoint:
    if type(value) is not RollbackCheckpoint:
        raise InvalidCheckpointError(f"{name} must be an exact RollbackCheckpoint")
    return value
