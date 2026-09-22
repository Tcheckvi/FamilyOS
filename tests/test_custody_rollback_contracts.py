from __future__ import annotations

from dataclasses import replace

import pytest

from familyos_pilot0.custody_rollback_contracts import (
    AnchorAdvanceDecision,
    ExternalRollbackAnchor,
    InvalidCheckpointError,
    RollbackCheckpoint,
    RollbackContractError,
    RollbackRejectedError,
    RollbackVerificationDecision,
    StoreIdentity,
    require_anchor_advancement,
    require_store_checkpoint_match,
    validate_anchor_advancement,
    verify_store_checkpoint,
)


def _digest(char: str) -> str:
    return char * 64


def _identity(
    *,
    store_instance_id: str = "store-01",
    store_epoch: int = 1,
) -> StoreIdentity:
    return StoreIdentity(
        store_instance_id=store_instance_id,
        store_epoch=store_epoch,
    )


def _checkpoint(
    *,
    store_instance_id: str = "store-01",
    store_epoch: int = 1,
    store_generation: int = 7,
    digest_char: str = "a",
) -> RollbackCheckpoint:
    return RollbackCheckpoint(
        identity=_identity(
            store_instance_id=store_instance_id,
            store_epoch=store_epoch,
        ),
        store_generation=store_generation,
        store_root_digest=_digest(digest_char),
    )


class SyntheticRollbackAnchor:
    """Test-only in-memory implementation of ExternalRollbackAnchor."""

    def __init__(self, initial: RollbackCheckpoint) -> None:
        self._checkpoint = initial

    def read_checkpoint(self) -> RollbackCheckpoint:
        return self._checkpoint

    def advance_checkpoint(
        self,
        *,
        expected_current: RollbackCheckpoint,
        candidate: RollbackCheckpoint,
    ) -> None:
        if expected_current != self._checkpoint:
            raise RollbackContractError("synthetic anchor compare-and-swap failed")
        require_anchor_advancement(
            current=self._checkpoint,
            candidate=candidate,
        )
        self._checkpoint = candidate


def test_exact_match_is_admissible() -> None:
    trusted = _checkpoint()

    assert (
        verify_store_checkpoint(observed=trusted, trusted=trusted)
        is RollbackVerificationDecision.MATCH
    )
    require_store_checkpoint_match(observed=trusted, trusted=trusted)


def test_store_generation_rollback_is_rejected() -> None:
    trusted = _checkpoint(store_generation=8)
    observed = _checkpoint(store_generation=7)

    assert (
        verify_store_checkpoint(observed=observed, trusted=trusted)
        is RollbackVerificationDecision.ROLLBACK_DETECTED
    )
    with pytest.raises(RollbackRejectedError) as exc_info:
        require_store_checkpoint_match(observed=observed, trusted=trusted)

    assert (
        exc_info.value.decision
        is RollbackVerificationDecision.ROLLBACK_DETECTED
    )


def test_same_generation_digest_divergence_is_rejected() -> None:
    trusted = _checkpoint(store_generation=8, digest_char="a")
    observed = _checkpoint(store_generation=8, digest_char="b")

    assert (
        verify_store_checkpoint(observed=observed, trusted=trusted)
        is RollbackVerificationDecision.DIVERGENCE
    )


def test_wrong_store_is_rejected() -> None:
    trusted = _checkpoint(store_instance_id="store-01")
    observed = _checkpoint(store_instance_id="store-02")

    assert (
        verify_store_checkpoint(observed=observed, trusted=trusted)
        is RollbackVerificationDecision.WRONG_STORE
    )


def test_old_epoch_is_rejected_as_rollback() -> None:
    trusted = _checkpoint(store_epoch=4, store_generation=0)
    observed = _checkpoint(store_epoch=3, store_generation=999)

    assert (
        verify_store_checkpoint(observed=observed, trusted=trusted)
        is RollbackVerificationDecision.ROLLBACK_DETECTED
    )


def test_store_generation_ahead_of_anchor_is_uncertain_and_denied() -> None:
    trusted = _checkpoint(store_generation=8)
    observed = _checkpoint(store_generation=9)

    assert (
        verify_store_checkpoint(observed=observed, trusted=trusted)
        is RollbackVerificationDecision.ANCHOR_LAG_OR_UNCERTAIN
    )
    with pytest.raises(RollbackRejectedError):
        require_store_checkpoint_match(observed=observed, trusted=trusted)


def test_store_epoch_ahead_of_anchor_is_uncertain_and_denied() -> None:
    trusted = _checkpoint(store_epoch=4, store_generation=20)
    observed = _checkpoint(store_epoch=5, store_generation=0)

    assert (
        verify_store_checkpoint(observed=observed, trusted=trusted)
        is RollbackVerificationDecision.ANCHOR_LAG_OR_UNCERTAIN
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("store_instance_id", ""),
        ("store_instance_id", " space"),
        ("store_instance_id", "x" * 129),
        ("store_epoch", -1),
        ("store_epoch", True),
    ],
)
def test_malformed_store_identity_is_rejected(field: str, value: object) -> None:
    kwargs: dict[str, object] = {
        "store_instance_id": "store-01",
        "store_epoch": 1,
    }
    kwargs[field] = value

    with pytest.raises(InvalidCheckpointError):
        StoreIdentity(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("store_generation", -1),
        ("store_generation", True),
        ("store_root_digest", "A" * 64),
        ("store_root_digest", "a" * 63),
        ("store_root_digest", "g" * 64),
    ],
)
def test_malformed_checkpoint_is_rejected(field: str, value: object) -> None:
    kwargs: dict[str, object] = {
        "identity": _identity(),
        "store_generation": 1,
        "store_root_digest": _digest("a"),
    }
    kwargs[field] = value

    with pytest.raises(InvalidCheckpointError):
        RollbackCheckpoint(**kwargs)  # type: ignore[arg-type]


def test_anchor_advancement_is_monotonic() -> None:
    current = _checkpoint(store_generation=7, digest_char="a")
    candidate = _checkpoint(store_generation=8, digest_char="b")

    assert (
        validate_anchor_advancement(current=current, candidate=candidate)
        is AnchorAdvanceDecision.ADVANCE_ALLOWED
    )
    require_anchor_advancement(current=current, candidate=candidate)


def test_stale_anchor_candidate_is_rejected() -> None:
    current = _checkpoint(store_generation=8)
    stale = _checkpoint(store_generation=7)

    assert (
        validate_anchor_advancement(current=current, candidate=stale)
        is AnchorAdvanceDecision.STALE_CANDIDATE
    )
    with pytest.raises(RollbackContractError):
        require_anchor_advancement(current=current, candidate=stale)


def test_anchor_same_generation_digest_divergence_is_rejected() -> None:
    current = _checkpoint(store_generation=8, digest_char="a")
    candidate = _checkpoint(store_generation=8, digest_char="b")

    assert (
        validate_anchor_advancement(current=current, candidate=candidate)
        is AnchorAdvanceDecision.DIVERGENCE
    )


def test_anchor_wrong_store_candidate_is_rejected() -> None:
    current = _checkpoint(store_instance_id="store-01")
    candidate = _checkpoint(store_instance_id="store-02")

    assert (
        validate_anchor_advancement(current=current, candidate=candidate)
        is AnchorAdvanceDecision.WRONG_STORE
    )


def test_anchor_epoch_transition_requires_reprovisioning() -> None:
    current = _checkpoint(store_epoch=1, store_generation=100)
    candidate = _checkpoint(store_epoch=2, store_generation=0)

    assert (
        validate_anchor_advancement(current=current, candidate=candidate)
        is AnchorAdvanceDecision.EPOCH_TRANSITION_REQUIRES_REPROVISIONING
    )


def test_identical_anchor_checkpoint_is_not_an_advancement() -> None:
    current = _checkpoint()

    assert (
        validate_anchor_advancement(current=current, candidate=current)
        is AnchorAdvanceDecision.ALREADY_CURRENT
    )


def test_synthetic_anchor_implements_protocol_and_advances() -> None:
    initial = _checkpoint(store_generation=3, digest_char="a")
    candidate = _checkpoint(store_generation=4, digest_char="b")
    anchor = SyntheticRollbackAnchor(initial)

    assert isinstance(anchor, ExternalRollbackAnchor)
    anchor.advance_checkpoint(expected_current=initial, candidate=candidate)

    assert anchor.read_checkpoint() == candidate


def test_synthetic_anchor_rejects_stale_compare_and_swap() -> None:
    initial = _checkpoint(store_generation=3, digest_char="a")
    candidate = _checkpoint(store_generation=4, digest_char="b")
    anchor = SyntheticRollbackAnchor(initial)
    anchor.advance_checkpoint(expected_current=initial, candidate=candidate)

    later = _checkpoint(store_generation=5, digest_char="c")
    with pytest.raises(RollbackContractError, match="compare-and-swap"):
        anchor.advance_checkpoint(expected_current=initial, candidate=later)

    assert anchor.read_checkpoint() == candidate


def test_exact_type_guards_reject_checkpoint_subclasses() -> None:
    class CheckpointSubclass(RollbackCheckpoint):
        pass

    trusted = _checkpoint()
    observed = CheckpointSubclass(
        identity=trusted.identity,
        store_generation=trusted.store_generation,
        store_root_digest=trusted.store_root_digest,
    )

    with pytest.raises(InvalidCheckpointError):
        verify_store_checkpoint(observed=observed, trusted=trusted)


def test_replacing_digest_only_preserves_identity_for_divergence_case() -> None:
    trusted = _checkpoint(store_generation=11, digest_char="a")
    observed = replace(trusted, store_root_digest=_digest("b"))

    assert observed.identity == trusted.identity
    assert (
        verify_store_checkpoint(observed=observed, trusted=trusted)
        is RollbackVerificationDecision.DIVERGENCE
    )
