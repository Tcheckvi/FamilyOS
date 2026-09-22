from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

import pytest

from familyos_pilot0.custody_rollback_contracts import (
    RollbackCheckpoint,
    RollbackContractError,
    RollbackRejectedError,
    RollbackVerificationDecision,
    StoreIdentity,
    require_anchor_advancement,
)
from familyos_pilot0.custody_worker_contracts import (
    KeyPurposeClass,
    KeyRef,
    ReplayClaimState,
    SigningResult,
)
from familyos_pilot0.custody_worker_runtime import (
    AuthoritativeClaimStore,
    ClaimConflictError,
    DurableWriteUncertain,
    RuntimeClaimStoreError,
    RuntimeFactConstructor,
    StaleClaimGenerationError,
)


class _R2BSyntheticRollbackAnchor:
    """Synthetic test-only implementation of the external rollback anchor."""

    def __init__(self, checkpoint: RollbackCheckpoint) -> None:
        self._checkpoint = checkpoint
        self.fail_advance = False
        self.readback_mismatch = False

    def read_checkpoint(self) -> RollbackCheckpoint:
        if not self.readback_mismatch:
            return self._checkpoint

        mismatch_digest = "f" * 64 if self._checkpoint.store_root_digest != "f" * 64 else "e" * 64
        return RollbackCheckpoint(
            identity=self._checkpoint.identity,
            store_generation=self._checkpoint.store_generation,
            store_root_digest=mismatch_digest,
        )

    def advance_checkpoint(
        self,
        *,
        expected_current: RollbackCheckpoint,
        candidate: RollbackCheckpoint,
    ) -> None:
        if self.fail_advance:
            raise RollbackContractError("synthetic anchor advancement failed")
        if self._checkpoint != expected_current:
            raise RollbackContractError("synthetic anchor compare-and-swap failed")
        require_anchor_advancement(
            current=self._checkpoint,
            candidate=candidate,
        )
        self._checkpoint = candidate


_R2B_TEST_BINDINGS: dict[
    str,
    tuple[StoreIdentity, _R2BSyntheticRollbackAnchor],
] = {}


def _r2b_test_binding(
    root: object,
) -> tuple[StoreIdentity, _R2BSyntheticRollbackAnchor]:
    key = str(root)
    existing = _R2B_TEST_BINDINGS.get(key)
    if existing is not None:
        return existing

    identity = StoreIdentity(
        store_instance_id="synthetic-runtime-test-store",
        store_epoch=1,
    )
    anchor = _R2BSyntheticRollbackAnchor(
        AuthoritativeClaimStore.expected_empty_rollback_checkpoint(identity)
    )
    binding = (identity, anchor)
    _R2B_TEST_BINDINGS[key] = binding
    return binding


def _r2b_test_identity(root: object) -> StoreIdentity:
    return _r2b_test_binding(root)[0]


def _r2b_test_anchor(root: object) -> _R2BSyntheticRollbackAnchor:
    return _r2b_test_binding(root)[1]


AUTHORIZATION_ID = "auth-runtime-r1"
OPERATION_ID = "operation-runtime-r1"
CONTEXT_DIGEST = "1" * 64
SIGNING_REQUEST_DIGEST = "2" * 64
RESOURCES = ("rfc3161-slot-1",)


def _store(tmp_path: Path) -> AuthoritativeClaimStore:
    return AuthoritativeClaimStore(
        tmp_path / "claim-store",
        store_identity=_r2b_test_identity(tmp_path / "claim-store"),
        rollback_anchor=_r2b_test_anchor(tmp_path / "claim-store"),
    )


def _reserved_store(tmp_path: Path) -> tuple[AuthoritativeClaimStore, int]:
    store = _store(tmp_path)
    claim = store.reserve(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
        context_digest=CONTEXT_DIGEST,
        non_key_resources_consumed=RESOURCES,
    )
    return store, claim.claim_generation


def _claimed_store(
    tmp_path: Path,
) -> tuple[AuthoritativeClaimStore, int]:
    store, generation = _reserved_store(tmp_path)
    claim = store.claim_key_use_intent(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
        context_digest=CONTEXT_DIGEST,
        signing_request_digest=SIGNING_REQUEST_DIGEST,
        expected_generation=generation,
    )
    return store, claim.claim_generation


def test_reservation_is_durable_and_binds_context_and_resources(
    tmp_path: Path,
) -> None:
    store, generation = _reserved_store(tmp_path)

    reopened = AuthoritativeClaimStore(
        tmp_path / "claim-store",
        store_identity=_r2b_test_identity(tmp_path / "claim-store"),
        rollback_anchor=_r2b_test_anchor(tmp_path / "claim-store"),
    )
    claim = reopened.load_authoritative(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
    )

    assert claim is not None
    assert claim.context_digest == CONTEXT_DIGEST
    assert claim.non_key_resources_consumed == RESOURCES
    assert claim.state is ReplayClaimState.RESOURCES_RESERVED
    assert claim.claim_generation == generation == 0
    assert claim.key_use_intent_durable is False
    assert claim.signing_request_digest is None


def test_duplicate_reservation_is_rejected(tmp_path: Path) -> None:
    store, _ = _reserved_store(tmp_path)

    with pytest.raises(ClaimConflictError):
        store.reserve(
            authorization_id=AUTHORIZATION_ID,
            operation_id=OPERATION_ID,
            context_digest=CONTEXT_DIGEST,
            non_key_resources_consumed=RESOURCES,
        )


def test_key_use_intent_binds_exact_signing_request_digest(tmp_path: Path) -> None:
    store, generation = _reserved_store(tmp_path)

    claim = store.claim_key_use_intent(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
        context_digest=CONTEXT_DIGEST,
        signing_request_digest=SIGNING_REQUEST_DIGEST,
        expected_generation=generation,
    )

    assert claim.state is ReplayClaimState.KEY_USE_CLAIMED
    assert claim.key_use_intent_durable is True
    assert claim.signing_request_digest == SIGNING_REQUEST_DIGEST
    assert claim.non_key_resources_consumed == RESOURCES
    assert claim.claim_generation == 1

    reopened = AuthoritativeClaimStore(
        tmp_path / "claim-store",
        store_identity=_r2b_test_identity(tmp_path / "claim-store"),
        rollback_anchor=_r2b_test_anchor(tmp_path / "claim-store"),
    )
    authoritative = reopened.claim_for_signer(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
        context_digest=CONTEXT_DIGEST,
        signing_request_digest=SIGNING_REQUEST_DIGEST,
    )
    assert authoritative == claim


def test_wrong_context_cannot_claim_key_use(tmp_path: Path) -> None:
    store, generation = _reserved_store(tmp_path)

    with pytest.raises(ClaimConflictError):
        store.claim_key_use_intent(
            authorization_id=AUTHORIZATION_ID,
            operation_id=OPERATION_ID,
            context_digest="3" * 64,
            signing_request_digest=SIGNING_REQUEST_DIGEST,
            expected_generation=generation,
        )


def test_stale_generation_cannot_advance_claim(tmp_path: Path) -> None:
    store, generation = _reserved_store(tmp_path)

    with pytest.raises(StaleClaimGenerationError):
        store.claim_key_use_intent(
            authorization_id=AUTHORIZATION_ID,
            operation_id=OPERATION_ID,
            context_digest=CONTEXT_DIGEST,
            signing_request_digest=SIGNING_REQUEST_DIGEST,
            expected_generation=generation + 1,
        )


def test_release_requires_authoritative_spent_clean(tmp_path: Path) -> None:
    store, generation = _claimed_store(tmp_path)

    with pytest.raises(ClaimConflictError):
        store.claim_for_release(
            authorization_id=AUTHORIZATION_ID,
            operation_id=OPERATION_ID,
            context_digest=CONTEXT_DIGEST,
            signing_request_digest=SIGNING_REQUEST_DIGEST,
        )

    terminal = store.record_terminal(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
        context_digest=CONTEXT_DIGEST,
        terminal_state=ReplayClaimState.SPENT_CLEAN,
        expected_generation=generation,
    )

    released_claim = store.claim_for_release(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
        context_digest=CONTEXT_DIGEST,
        signing_request_digest=SIGNING_REQUEST_DIGEST,
    )
    assert released_claim == terminal
    assert released_claim.state is ReplayClaimState.SPENT_CLEAN


@pytest.mark.parametrize(
    "terminal_state",
    [ReplayClaimState.SPENT_UNKNOWN, ReplayClaimState.QUARANTINED],
)
def test_unclean_terminal_state_never_releases(
    tmp_path: Path,
    terminal_state: ReplayClaimState,
) -> None:
    store, generation = _claimed_store(tmp_path)
    store.record_terminal(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
        context_digest=CONTEXT_DIGEST,
        terminal_state=terminal_state,
        expected_generation=generation,
    )

    with pytest.raises(ClaimConflictError):
        store.claim_for_release(
            authorization_id=AUTHORIZATION_ID,
            operation_id=OPERATION_ID,
            context_digest=CONTEXT_DIGEST,
            signing_request_digest=SIGNING_REQUEST_DIGEST,
        )


def test_restart_recovery_reserved_becomes_no_key_use(tmp_path: Path) -> None:
    store, _ = _reserved_store(tmp_path)

    recovered = store.recover_after_restart(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
    )

    assert recovered is not None
    assert recovered.state is ReplayClaimState.NO_KEY_USE
    assert recovered.claim_generation == 1
    assert recovered.non_key_resources_consumed == RESOURCES
    assert recovered.key_use_intent_durable is False
    assert recovered.signing_request_digest is None


def test_restart_recovery_claimed_becomes_spent_unknown(tmp_path: Path) -> None:
    store, _ = _claimed_store(tmp_path)

    recovered = store.recover_after_restart(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
    )

    assert recovered is not None
    assert recovered.state is ReplayClaimState.SPENT_UNKNOWN
    assert recovered.claim_generation == 2
    assert recovered.non_key_resources_consumed == RESOURCES
    assert recovered.key_use_intent_durable is True
    assert recovered.signing_request_digest == SIGNING_REQUEST_DIGEST


def test_restart_recovery_terminal_is_unchanged(tmp_path: Path) -> None:
    store, generation = _claimed_store(tmp_path)
    terminal = store.record_terminal(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
        context_digest=CONTEXT_DIGEST,
        terminal_state=ReplayClaimState.SPENT_CLEAN,
        expected_generation=generation,
    )

    recovered = store.recover_after_restart(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
    )

    assert recovered == terminal
    assert recovered is not None
    assert recovered.claim_generation == terminal.claim_generation


def test_failed_key_use_write_before_replace_never_reports_success(
    tmp_path: Path,
) -> None:
    root = tmp_path / "claim-store"
    baseline = AuthoritativeClaimStore(
        root, store_identity=_r2b_test_identity(root), rollback_anchor=_r2b_test_anchor(root)
    )
    reserved = baseline.reserve(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
        context_digest=CONTEXT_DIGEST,
        non_key_resources_consumed=RESOURCES,
    )

    def fail_before_fsync(phase: str) -> None:
        if phase == "before_file_fsync":
            raise OSError("synthetic write failure")

    failing = AuthoritativeClaimStore(
        root,
        fault_injector=fail_before_fsync,
        store_identity=_r2b_test_identity(root),
        rollback_anchor=_r2b_test_anchor(root),
    )

    with pytest.raises(DurableWriteUncertain) as error:
        failing.claim_key_use_intent(
            authorization_id=AUTHORIZATION_ID,
            operation_id=OPERATION_ID,
            context_digest=CONTEXT_DIGEST,
            signing_request_digest=SIGNING_REQUEST_DIGEST,
            expected_generation=reserved.claim_generation,
        )

    assert error.value.fail_closed_state is ReplayClaimState.SPENT_UNKNOWN

    reopened = AuthoritativeClaimStore(
        root, store_identity=_r2b_test_identity(root), rollback_anchor=_r2b_test_anchor(root)
    )
    current = reopened.load_authoritative(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
    )
    assert current is not None
    assert current.state is ReplayClaimState.RESOURCES_RESERVED

    recovered = reopened.recover_after_restart(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
    )
    assert recovered is not None
    assert recovered.state is ReplayClaimState.NO_KEY_USE


def test_failed_key_use_write_after_replace_leaves_store_ahead_and_denied(
    tmp_path: Path,
) -> None:
    root = tmp_path / "claim-store"
    baseline = AuthoritativeClaimStore(
        root,
        store_identity=_r2b_test_identity(root),
        rollback_anchor=_r2b_test_anchor(root),
    )
    reserved = baseline.reserve(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
        context_digest=CONTEXT_DIGEST,
        non_key_resources_consumed=RESOURCES,
    )

    def fail_after_replace(phase: str) -> None:
        if phase == "after_replace":
            raise OSError("synthetic directory durability failure")

    failing = AuthoritativeClaimStore(
        root,
        fault_injector=fail_after_replace,
        store_identity=_r2b_test_identity(root),
        rollback_anchor=_r2b_test_anchor(root),
    )

    with pytest.raises(DurableWriteUncertain) as error:
        failing.claim_key_use_intent(
            authorization_id=AUTHORIZATION_ID,
            operation_id=OPERATION_ID,
            context_digest=CONTEXT_DIGEST,
            signing_request_digest=SIGNING_REQUEST_DIGEST,
            expected_generation=reserved.claim_generation,
        )

    assert error.value.fail_closed_state is ReplayClaimState.SPENT_UNKNOWN

    reopened = AuthoritativeClaimStore(
        root,
        store_identity=_r2b_test_identity(root),
        rollback_anchor=_r2b_test_anchor(root),
    )
    with pytest.raises(RollbackRejectedError) as rollback_error:
        reopened.load_authoritative(
            authorization_id=AUTHORIZATION_ID,
            operation_id=OPERATION_ID,
        )

    assert rollback_error.value.decision is RollbackVerificationDecision.ANCHOR_LAG_OR_UNCERTAIN


def test_corrupt_store_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "claim-store"
    root.mkdir()
    (root / "claims.json").write_text("{not-json", encoding="utf-8")

    store = AuthoritativeClaimStore(
        root, store_identity=_r2b_test_identity(root), rollback_anchor=_r2b_test_anchor(root)
    )
    with pytest.raises(RuntimeClaimStoreError):
        store.load_authoritative(
            authorization_id=AUTHORIZATION_ID,
            operation_id=OPERATION_ID,
        )


def test_store_rejects_schema_tampering(tmp_path: Path) -> None:
    root = tmp_path / "claim-store"
    store = AuthoritativeClaimStore(
        root,
        store_identity=_r2b_test_identity(root),
        rollback_anchor=_r2b_test_anchor(root),
    )
    store.reserve(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
        context_digest=CONTEXT_DIGEST,
        non_key_resources_consumed=RESOURCES,
    )

    claims_path = root / "claims.json"
    data = json.loads(claims_path.read_text(encoding="utf-8"))
    key = next(iter(data["claims"]))
    data["claims"][key]["unexpected"] = True
    claims_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(RollbackRejectedError) as rollback_error:
        store.load_authoritative(
            authorization_id=AUTHORIZATION_ID,
            operation_id=OPERATION_ID,
        )

    assert rollback_error.value.decision is RollbackVerificationDecision.DIVERGENCE


def test_lock_and_claim_files_are_not_group_or_world_accessible(
    tmp_path: Path,
) -> None:
    store, _ = _reserved_store(tmp_path)
    store.load_authoritative(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
    )

    root = tmp_path / "claim-store"
    for path in (root / "claims.json", root / "claims.lock"):
        mode = os.stat(path).st_mode & 0o777
        assert mode & 0o077 == 0


def test_runtime_fact_constructor_builds_exact_signing_result() -> None:
    key_ref = KeyRef(
        key_id="rd01-human",
        key_version=1,
        key_fingerprint="SHA256:" + "A" * 43,
        key_purpose_class=KeyPurposeClass.HUMAN_DECISION,
        algorithm_profile="ed25519",
        backend_id="synthetic",
    )
    result = RuntimeFactConstructor.signing_result(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
        key_ref=key_ref,
        signature_namespace="familyos-test",
        final_payload_digest="3" * 64,
        signature_sha256="4" * 64,
        signature_verified=True,
        elapsed_at_signature_completion_seconds=7,
        signer_reaped=True,
        custody_postconditions_verified=True,
        evidence_sealed=True,
    )

    assert type(result) is SigningResult
    assert result.key_ref == key_ref
    assert result.signature_verified is True
    assert result.signer_reaped is True
    assert result.custody_postconditions_verified is True
    assert result.evidence_sealed is True


def test_r2b_constructor_requires_explicit_identity_and_anchor() -> None:
    signature = inspect.signature(AuthoritativeClaimStore)
    assert signature.parameters["store_identity"].default is inspect.Parameter.empty
    assert signature.parameters["rollback_anchor"].default is inspect.Parameter.empty


def test_r2b_empty_checkpoint_and_generation_formula(tmp_path: Path) -> None:
    root = tmp_path / "r2b-generation"
    identity = StoreIdentity(
        store_instance_id="r2b-generation-store",
        store_epoch=7,
    )
    anchor = _R2BSyntheticRollbackAnchor(
        AuthoritativeClaimStore.expected_empty_rollback_checkpoint(identity)
    )
    store = AuthoritativeClaimStore(
        root,
        store_identity=identity,
        rollback_anchor=anchor,
    )

    empty = store._rollback_checkpoint_for_document({})
    assert empty.store_generation == 0

    one_claim = {
        "claims": {
            "a": {
                "claim_generation": 0,
            }
        }
    }
    one = store._rollback_checkpoint_for_document(one_claim)
    assert one.store_generation == 1

    transitioned = {
        "claims": {
            "a": {
                "claim_generation": 1,
            }
        }
    }
    two = store._rollback_checkpoint_for_document(transitioned)
    assert two.store_generation == 2

    two_claims = {
        "claims": {
            "a": {
                "claim_generation": 1,
            },
            "b": {
                "claim_generation": 0,
            },
        }
    }
    three = store._rollback_checkpoint_for_document(two_claims)
    assert three.store_generation == 3
    assert (
        len(
            {
                empty.store_root_digest,
                one.store_root_digest,
                two.store_root_digest,
                three.store_root_digest,
            }
        )
        == 4
    )


def test_r2b_wrong_store_identity_is_denied(tmp_path: Path) -> None:
    root = tmp_path / "r2b-wrong-store"
    identity = StoreIdentity(
        store_instance_id="r2b-store-a",
        store_epoch=1,
    )
    wrong_identity = StoreIdentity(
        store_instance_id="r2b-store-b",
        store_epoch=1,
    )
    anchor = _R2BSyntheticRollbackAnchor(
        AuthoritativeClaimStore.expected_empty_rollback_checkpoint(wrong_identity)
    )
    store = AuthoritativeClaimStore(
        root,
        store_identity=identity,
        rollback_anchor=anchor,
    )

    with pytest.raises(RollbackContractError):
        store._require_rollback_match_locked()


def test_r2b_store_ahead_of_anchor_is_denied(tmp_path: Path) -> None:
    root = tmp_path / "r2b-store-ahead"
    identity = StoreIdentity(
        store_instance_id="r2b-store-ahead",
        store_epoch=1,
    )
    anchor = _R2BSyntheticRollbackAnchor(
        AuthoritativeClaimStore.expected_empty_rollback_checkpoint(identity)
    )
    store = AuthoritativeClaimStore(
        root,
        store_identity=identity,
        rollback_anchor=anchor,
    )

    store._claims_path.write_text(
        '{"claims":{"a":{"claim_generation":0}}}',
        encoding="utf-8",
    )

    with pytest.raises(RollbackContractError):
        store._require_rollback_match_locked()


def test_r2b_anchor_advances_after_durable_store_state(tmp_path: Path) -> None:
    root = tmp_path / "r2b-advance"
    identity = StoreIdentity(
        store_instance_id="r2b-advance",
        store_epoch=1,
    )
    anchor = _R2BSyntheticRollbackAnchor(
        AuthoritativeClaimStore.expected_empty_rollback_checkpoint(identity)
    )
    store = AuthoritativeClaimStore(
        root,
        store_identity=identity,
        rollback_anchor=anchor,
    )

    old_checkpoint = store._require_rollback_match_locked()
    store._claims_path.write_text(
        '{"claims":{"a":{"claim_generation":0}}}',
        encoding="utf-8",
    )
    candidate = store._advance_rollback_anchor_locked(old_checkpoint)

    assert candidate.store_generation == 1
    assert anchor.read_checkpoint() == candidate
    assert store._require_rollback_match_locked() == candidate


def test_r2b_anchor_advance_failure_leaves_store_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "r2b-advance-failure"
    identity = StoreIdentity(
        store_instance_id="r2b-advance-failure",
        store_epoch=1,
    )
    anchor = _R2BSyntheticRollbackAnchor(
        AuthoritativeClaimStore.expected_empty_rollback_checkpoint(identity)
    )
    store = AuthoritativeClaimStore(
        root,
        store_identity=identity,
        rollback_anchor=anchor,
    )

    old_checkpoint = store._require_rollback_match_locked()
    store._claims_path.write_text(
        '{"claims":{"a":{"claim_generation":0}}}',
        encoding="utf-8",
    )
    anchor.fail_advance = True

    with pytest.raises(RollbackContractError):
        store._advance_rollback_anchor_locked(old_checkpoint)

    anchor.fail_advance = False
    with pytest.raises(RollbackContractError):
        store._require_rollback_match_locked()


def test_r2b_anchor_readback_mismatch_is_denied(tmp_path: Path) -> None:
    root = tmp_path / "r2b-readback"
    identity = StoreIdentity(
        store_instance_id="r2b-readback",
        store_epoch=1,
    )
    anchor = _R2BSyntheticRollbackAnchor(
        AuthoritativeClaimStore.expected_empty_rollback_checkpoint(identity)
    )
    store = AuthoritativeClaimStore(
        root,
        store_identity=identity,
        rollback_anchor=anchor,
    )

    old_checkpoint = store._require_rollback_match_locked()
    store._claims_path.write_text(
        '{"claims":{"a":{"claim_generation":0}}}',
        encoding="utf-8",
    )
    anchor.readback_mismatch = True

    with pytest.raises(RollbackContractError):
        store._advance_rollback_anchor_locked(old_checkpoint)


def test_r2b_all_public_store_admission_methods_are_guarded() -> None:
    for name in (
        "reserve",
        "claim_key_use_intent",
        "record_terminal",
        "load_authoritative",
        "claim_for_signer",
        "claim_for_release",
        "recover_after_restart",
    ):
        source = inspect.getsource(getattr(AuthoritativeClaimStore, name))
        assert "_require_rollback_match_locked()" in source

    mutation_source = inspect.getsource(AuthoritativeClaimStore._store_claim_locked)
    assert "expected_rollback_checkpoint" in mutation_source
    assert "_advance_rollback_anchor_locked" in mutation_source


def test_r2b_no_runtime_tofu_or_anchor_bootstrap_surface() -> None:
    constructor_source = inspect.getsource(AuthoritativeClaimStore.__init__)
    assert "store_identity" in constructor_source
    assert "rollback_anchor" in constructor_source
    assert "expected_empty_rollback_checkpoint" not in constructor_source

    runtime_source = inspect.getsource(AuthoritativeClaimStore)
    assert "setdefault" not in runtime_source
    assert "auto_provision" not in runtime_source
    assert "trust_on_first_use" not in runtime_source
