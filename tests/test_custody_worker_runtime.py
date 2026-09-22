from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

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

AUTHORIZATION_ID = "auth-runtime-r1"
OPERATION_ID = "operation-runtime-r1"
CONTEXT_DIGEST = "1" * 64
SIGNING_REQUEST_DIGEST = "2" * 64
RESOURCES = ("rfc3161-slot-1",)


def _store(tmp_path: Path) -> AuthoritativeClaimStore:
    return AuthoritativeClaimStore(tmp_path / "claim-store")


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

    reopened = AuthoritativeClaimStore(tmp_path / "claim-store")
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

    reopened = AuthoritativeClaimStore(tmp_path / "claim-store")
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
    baseline = AuthoritativeClaimStore(root)
    reserved = baseline.reserve(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
        context_digest=CONTEXT_DIGEST,
        non_key_resources_consumed=RESOURCES,
    )

    def fail_before_fsync(phase: str) -> None:
        if phase == "before_file_fsync":
            raise OSError("synthetic write failure")

    failing = AuthoritativeClaimStore(root, fault_injector=fail_before_fsync)

    with pytest.raises(DurableWriteUncertain) as error:
        failing.claim_key_use_intent(
            authorization_id=AUTHORIZATION_ID,
            operation_id=OPERATION_ID,
            context_digest=CONTEXT_DIGEST,
            signing_request_digest=SIGNING_REQUEST_DIGEST,
            expected_generation=reserved.claim_generation,
        )

    assert error.value.fail_closed_state is ReplayClaimState.SPENT_UNKNOWN

    reopened = AuthoritativeClaimStore(root)
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


def test_failed_key_use_write_after_replace_recovers_spent_unknown(
    tmp_path: Path,
) -> None:
    root = tmp_path / "claim-store"
    baseline = AuthoritativeClaimStore(root)
    reserved = baseline.reserve(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
        context_digest=CONTEXT_DIGEST,
        non_key_resources_consumed=RESOURCES,
    )

    def fail_after_replace(phase: str) -> None:
        if phase == "after_replace":
            raise OSError("synthetic directory durability failure")

    failing = AuthoritativeClaimStore(root, fault_injector=fail_after_replace)

    with pytest.raises(DurableWriteUncertain) as error:
        failing.claim_key_use_intent(
            authorization_id=AUTHORIZATION_ID,
            operation_id=OPERATION_ID,
            context_digest=CONTEXT_DIGEST,
            signing_request_digest=SIGNING_REQUEST_DIGEST,
            expected_generation=reserved.claim_generation,
        )

    assert error.value.fail_closed_state is ReplayClaimState.SPENT_UNKNOWN

    reopened = AuthoritativeClaimStore(root)
    current = reopened.load_authoritative(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
    )
    assert current is not None
    assert current.state is ReplayClaimState.KEY_USE_CLAIMED

    recovered = reopened.recover_after_restart(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
    )
    assert recovered is not None
    assert recovered.state is ReplayClaimState.SPENT_UNKNOWN
    assert recovered.signing_request_digest == SIGNING_REQUEST_DIGEST


def test_corrupt_store_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "claim-store"
    root.mkdir()
    (root / "claims.json").write_text("{not-json", encoding="utf-8")

    store = AuthoritativeClaimStore(root)
    with pytest.raises(RuntimeClaimStoreError):
        store.load_authoritative(
            authorization_id=AUTHORIZATION_ID,
            operation_id=OPERATION_ID,
        )


def test_store_rejects_schema_tampering(tmp_path: Path) -> None:
    root = tmp_path / "claim-store"
    store = AuthoritativeClaimStore(root)
    store.reserve(
        authorization_id=AUTHORIZATION_ID,
        operation_id=OPERATION_ID,
        context_digest=CONTEXT_DIGEST,
        non_key_resources_consumed=RESOURCES,
    )

    path = root / "claims.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    key = next(iter(data["claims"]))
    data["claims"][key]["unexpected"] = True
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(RuntimeClaimStoreError):
        store.load_authoritative(
            authorization_id=AUTHORIZATION_ID,
            operation_id=OPERATION_ID,
        )


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
