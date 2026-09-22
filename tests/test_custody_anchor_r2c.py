from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from familyos_pilot0.custody_anchor_adapter import BoundedAnchorCalls, ProtocolRollbackAnchor
from familyos_pilot0.custody_anchor_protocol import (
    AnchorAction,
    AnchorOutcome,
    AnchorPrincipal,
    AnchorProfile,
    AnchorRejected,
    AnchorRequest,
    AnchorResponse,
    AnchorRight,
    AnchorUnavailable,
    AnchorUncertain,
    ProfileBoundary,
    RecoveryState,
    ThreatScope,
    classify_recovery,
)
from familyos_pilot0.custody_rollback_contracts import (
    RollbackCheckpoint,
    RollbackContractError,
    RollbackRejectedError,
    RollbackVerificationDecision,
    StoreIdentity,
    require_store_checkpoint_match,
)
from familyos_pilot0.custody_worker_contracts import ReplayClaim, ReplayClaimState
from familyos_pilot0.custody_worker_runtime import (
    AuthoritativeClaimStore,
    RecoveryRequired,
    RuntimeClaimStoreError,
    StoreLockTimeout,
)
from tests.custody_anchor_fixtures import SyntheticAnchorService

IDENTITY = StoreIdentity("r2c-synthetic", 1)
PRINCIPAL = AnchorPrincipal(
    "worker",
    IDENTITY,
    frozenset(
        {
            AnchorRight.READ,
            AnchorRight.ADVANCE,
            AnchorRight.EXECUTE_ONCE,
        }
    ),
)
BOUNDARY = ProfileBoundary(
    AnchorProfile.INDEPENDENT_SECOND_DEVICE_WITNESS_PROFILE,
    ThreatScope.WITNESS_AND_CORRELATED_RESTORE,
    "witness-db",
    "retained-independent-head",
)
CONTEXT = "a" * 64
DIGEST = "b" * 64


def adapter(service: SyntheticAnchorService) -> ProtocolRollbackAnchor:
    return ProtocolRollbackAnchor(
        transport=service,
        principal=PRINCIPAL,
        boundary=BOUNDARY,
        continuity=service.continuity,
    )


def setup_store(root: Path) -> tuple[AuthoritativeClaimStore, SyntheticAnchorService]:
    initial = AuthoritativeClaimStore.expected_empty_rollback_checkpoint(IDENTITY)
    service = SyntheticAnchorService(initial, PRINCIPAL)
    return AuthoritativeClaimStore(
        root, store_identity=IDENTITY, rollback_anchor=adapter(service)
    ), service


def reserve(store: AuthoritativeClaimStore, operation: str = "op") -> ReplayClaim:
    return store.reserve(authorization_id="auth", operation_id=operation, context_digest=CONTEXT)


def intent(store: AuthoritativeClaimStore) -> ReplayClaim:
    return store.claim_key_use_intent(
        authorization_id="auth",
        operation_id="op",
        context_digest=CONTEXT,
        signing_request_digest=DIGEST,
        expected_generation=0,
    )


def fence(store: AuthoritativeClaimStore) -> ReplayClaim:
    return store.claim_for_signer(
        authorization_id="auth",
        operation_id="op",
        context_digest=CONTEXT,
        signing_request_digest=DIGEST,
    )


def test_concurrent_full_tuple_cas_has_one_winner(tmp_path: Path) -> None:
    _, service = setup_store(tmp_path)
    initial = service.checkpoint
    candidates = [replace(initial, store_generation=1, store_root_digest=c * 64) for c in "cd"]
    barrier = threading.Barrier(2)

    def compete(index: int) -> bool:
        client = adapter(service)
        barrier.wait(timeout=2)
        try:
            client.advance_checkpoint(expected_current=initial, candidate=candidates[index])
            return True
        except AnchorRejected:
            return False

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(compete, range(2))) == [False, True]
    assert service.mutations == 1
    assert service.checkpoint in candidates


def test_idempotency_is_bound_and_never_mutates_twice(tmp_path: Path) -> None:
    _, service = setup_store(tmp_path)
    client = adapter(service)
    old = client.read_checkpoint()
    new = replace(old, store_generation=1, store_root_digest="d" * 64)
    assert (
        client.advance_idempotent(expected_current=old, candidate=new, idempotency_key="same")
        is AnchorOutcome.COMMITTED
    )
    assert (
        client.advance_idempotent(expected_current=old, candidate=new, idempotency_key="same")
        is AnchorOutcome.DUPLICATE
    )
    with pytest.raises(AnchorRejected):
        client.advance_idempotent(
            expected_current=old,
            candidate=replace(new, store_root_digest="e" * 64),
            idempotency_key="same",
        )
    assert service.mutations == 1
    with pytest.raises(RollbackContractError):
        client.advance_checkpoint(
            expected_current=new, candidate=replace(new, store_root_digest="e" * 64)
        )


def test_lost_advance_reply_fresh_read_does_not_unblock_runtime(tmp_path: Path) -> None:
    store, service = setup_store(tmp_path)
    reserve(store)
    service.lose_reply = True
    with pytest.raises(AnchorUncertain):
        intent(store)
    local = store._current_rollback_checkpoint_locked()
    assert adapter(service).read_checkpoint() == local
    assert classify_recovery(local=local, trusted=local, uncertain=True) is (
        RecoveryState.EXACT_AFTER_UNCERTAINTY_BLOCKED
    )
    reopened = AuthoritativeClaimStore(
        tmp_path, store_identity=IDENTITY, rollback_anchor=adapter(service)
    )
    for runtime in (store, reopened):
        with pytest.raises(RecoveryRequired):
            fence(runtime)
        with pytest.raises(RecoveryRequired):
            runtime.recover_after_restart(authorization_id="auth", operation_id="op")
    assert not service.executions


def test_two_cloned_runtimes_compete_at_signer_boundary(tmp_path: Path) -> None:
    original, service = setup_store(tmp_path / "original")
    reserve(original)
    claimed = intent(original)
    shutil.copytree(tmp_path / "original", tmp_path / "clone")
    clone = AuthoritativeClaimStore(
        tmp_path / "clone", store_identity=IDENTITY, rollback_anchor=adapter(service)
    )
    barrier = threading.Barrier(2)

    def compete(runtime: AuthoritativeClaimStore) -> bool:
        barrier.wait(timeout=2)
        try:
            assert fence(runtime) == claimed
            return True
        except AnchorRejected:
            return False

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(compete, [original, clone])) == [False, True]
    assert len(service.executions) == 1
    for root in (tmp_path / "original", tmp_path / "clone"):
        reopened = AuthoritativeClaimStore(
            root, store_identity=IDENTITY, rollback_anchor=adapter(service)
        )
        with pytest.raises(AnchorRejected):
            fence(reopened)
        assert not reopened.export_diagnostics()["pending_anchor_mutation"]


def test_uncertain_execution_is_permanently_consumed_across_snapshot_clone(tmp_path: Path) -> None:
    store, service = setup_store(tmp_path / "original")
    reserve(store)
    intent(store)
    shutil.copytree(tmp_path / "original", tmp_path / "before-fence")
    service.lose_reply = True
    with pytest.raises(AnchorUncertain):
        fence(store)
    assert len(service.executions) == 1
    restored = AuthoritativeClaimStore(
        tmp_path / "before-fence", store_identity=IDENTITY, rollback_anchor=adapter(service)
    )
    assert adapter(service).read_checkpoint() == store._current_rollback_checkpoint_locked()
    with pytest.raises(AnchorRejected):
        fence(restored)


def test_confirmed_fence_restart_recovers_spent_without_regrant(tmp_path: Path) -> None:
    store, service = setup_store(tmp_path)
    reserve(store)
    intent(store)
    fence(store)
    reopened = AuthoritativeClaimStore(
        tmp_path, store_identity=IDENTITY, rollback_anchor=adapter(service)
    )
    recovered = reopened.recover_after_restart(authorization_id="auth", operation_id="op")
    assert recovered is not None and recovered.state is ReplayClaimState.SPENT_UNKNOWN
    with pytest.raises(RuntimeClaimStoreError):
        fence(reopened)
    assert len(service.executions) == 1


def test_witness_restore_including_fences_is_detected(tmp_path: Path) -> None:
    store, service = setup_store(tmp_path)
    reserve(store)
    intent(store)
    before = service.snapshot()
    fence(store)
    service.restore_for_test(before)
    # Checkpoint is unchanged: independent evidence must also cover execution tombstones.
    assert service.checkpoint == before.checkpoint
    with pytest.raises(AnchorUnavailable):
        adapter(service).read_checkpoint()


def test_correlated_restore_demonstrates_structural_limit(tmp_path: Path) -> None:
    store, service = setup_store(tmp_path / "original")
    reserve(store)
    intent(store)
    shutil.copytree(tmp_path / "original", tmp_path / "old-store")
    old = service.snapshot()
    fence(store)
    service.restore_for_test(old, correlated=True)
    restored = AuthoritativeClaimStore(
        tmp_path / "old-store", store_identity=IDENTITY, rollback_anchor=adapter(service)
    )
    # Deliberately roll back ALL retained authority: no surviving bit can reveal history.
    assert fence(restored).state is ReplayClaimState.KEY_USE_CLAIMED
    assert service.mutations == 4


@pytest.mark.parametrize("case", ["local-ahead", "anchor-ahead", "divergent", "outage"])
def test_checkpoint_mismatch_or_outage_denies_mutation(tmp_path: Path, case: str) -> None:
    store, service = setup_store(tmp_path)
    reserve(store)
    if case == "local-ahead":
        service.checkpoint = replace(service.checkpoint, store_generation=0)
    elif case == "anchor-ahead":
        service.checkpoint = replace(service.checkpoint, store_generation=99)
    elif case == "divergent":
        service.checkpoint = replace(service.checkpoint, store_root_digest="f" * 64)
    else:
        service.available = False
    service.continuity.head = service._stamp()
    before = (tmp_path / "claims.json").read_bytes()
    with pytest.raises(RollbackContractError):
        reserve(store, "other")
    assert (tmp_path / "claims.json").read_bytes() == before
    assert store.export_diagnostics()["authoritative"] is False


def test_recovery_matrix_never_grants_execution(tmp_path: Path) -> None:
    _, service = setup_store(tmp_path)
    c = service.checkpoint
    assert classify_recovery(local=c, trusted=None) is RecoveryState.UNAVAILABLE_BLOCKED
    assert classify_recovery(local=c, trusted=c, history_lost=True) is (
        RecoveryState.HISTORY_LOST_PERMANENTLY_BLOCKED
    )
    assert classify_recovery(local=replace(c, store_generation=1), trusted=c) is (
        RecoveryState.LOCAL_AHEAD_BLOCKED
    )
    assert classify_recovery(local=c, trusted=replace(c, store_generation=1)) is (
        RecoveryState.LOCAL_ROLLBACK_BLOCKED
    )
    assert classify_recovery(local=c, trusted=replace(c, store_root_digest="f" * 64)) is (
        RecoveryState.DIVERGENCE_BLOCKED
    )
    assert classify_recovery(local=c, trusted=c) is RecoveryState.EXACT_NO_EXECUTION_AUTHORITY


def test_replayed_or_unbound_read_response_denied(tmp_path: Path) -> None:
    _, service = setup_store(tmp_path)

    class ReplayTransport:
        saved: AnchorResponse | None = None

        def exchange(self, request: AnchorRequest) -> AnchorResponse:
            if self.saved is None:
                self.saved = service.exchange(request)
            return self.saved

    client = ProtocolRollbackAnchor(
        transport=ReplayTransport(),
        principal=PRINCIPAL,
        boundary=BOUNDARY,
        continuity=service.continuity,
    )
    client.read_checkpoint()
    with pytest.raises(AnchorUnavailable, match="current"):
        client.read_checkpoint()


def test_fresh_binding_with_stale_state_is_rejected_by_independent_authority(
    tmp_path: Path,
) -> None:
    _, service = setup_store(tmp_path)
    request = AnchorRequest(AnchorAction.READ, "worker", IDENTITY, "session", "first")
    old = service.exchange(request)
    client = adapter(service)
    client.advance_checkpoint(
        expected_current=old.checkpoint,
        candidate=replace(old.checkpoint, store_generation=1, store_root_digest="c" * 64),
    )

    class StaleReplica:
        def exchange(self, request: AnchorRequest) -> AnchorResponse:
            return replace(old, request=request)

    stale = ProtocolRollbackAnchor(
        transport=StaleReplica(),
        principal=PRINCIPAL,
        boundary=BOUNDARY,
        continuity=service.continuity,
    )
    with pytest.raises(AnchorUnavailable):
        stale.read_checkpoint()


def test_principal_scope_and_profiles_fail_closed(tmp_path: Path) -> None:
    _, service = setup_store(tmp_path)
    read_only = replace(PRINCIPAL, rights=frozenset({AnchorRight.READ}))
    client = ProtocolRollbackAnchor(
        transport=service,
        principal=read_only,
        boundary=BOUNDARY,
        continuity=service.continuity,
    )
    with pytest.raises(AnchorRejected):
        client.acquire_execution(expected_current=service.checkpoint, execution_id="operation")
    with pytest.raises(ValueError):
        ProtocolRollbackAnchor(
            transport=service, principal=PRINCIPAL, boundary=BOUNDARY, continuity=None
        )
    with pytest.raises(ValueError):
        ProfileBoundary(
            AnchorProfile.PROTECTED_INTERNAL_ANCHOR_PROFILE, ThreatScope.WHOLE_MAC, "mac", "mac"
        )
    with pytest.raises(ValueError):
        ProfileBoundary(
            AnchorProfile.REMOTE_CLOUD_WITNESS_PROFILE,
            ThreatScope.WITNESS_AND_CORRELATED_RESTORE,
            "same",
            "same",
        )
    assert not ({AnchorRight.ENROLL, AnchorRight.RECOVER_ADMIN} & PRINCIPAL.rights)
    assert not any(
        hasattr(client, method) for method in ("reset", "repair", "enroll", "release_execution")
    )


def test_bounded_wait_does_not_spawn_more_work_after_timeout() -> None:
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = BoundedAnchorCalls(0.05)

    def slow() -> None:
        started.set()
        release.wait(timeout=3)
        finished.set()

    try:
        before = time.monotonic()
        with pytest.raises(AnchorUncertain):
            calls.call(slow, mutation=True)
        assert started.is_set() and not finished.is_set()
        assert time.monotonic() - before < 1
        with pytest.raises(AnchorUnavailable):
            calls.call(lambda: None, mutation=False)
    finally:
        release.set()
        assert finished.wait(timeout=2)


def test_slow_anchor_releases_runtime_lock_and_diagnostics_remain_available(tmp_path: Path) -> None:
    _, service = setup_store(tmp_path)
    release, entered = threading.Event(), threading.Event()

    class SlowRead:
        def exchange(self, request: AnchorRequest) -> AnchorResponse:
            entered.set()
            release.wait(timeout=3)
            return service.exchange(request)

    client = ProtocolRollbackAnchor(
        transport=SlowRead(),
        principal=PRINCIPAL,
        boundary=BOUNDARY,
        continuity=service.continuity,
    )
    slow = AuthoritativeClaimStore(
        tmp_path,
        store_identity=IDENTITY,
        rollback_anchor=client,
        anchor_timeout_seconds=0.05,
    )
    other = AuthoritativeClaimStore(
        tmp_path,
        store_identity=IDENTITY,
        rollback_anchor=adapter(service),
        lock_timeout_seconds=0.05,
    )
    try:
        with pytest.raises(AnchorUnavailable):
            reserve(slow)
        assert entered.is_set()
        assert slow.export_diagnostics()["authoritative"] is False
        assert reserve(other).claim_generation == 0
    finally:
        release.set()


def test_lock_wait_is_bounded(tmp_path: Path) -> None:
    first, service = setup_store(tmp_path)
    second = AuthoritativeClaimStore(
        tmp_path,
        store_identity=IDENTITY,
        rollback_anchor=adapter(service),
        lock_timeout_seconds=0.02,
    )
    with first._locked():
        with pytest.raises(StoreLockTimeout):
            reserve(second)
        assert second.export_diagnostics()["authoritative"] is False


def valid_document() -> dict[str, object]:
    claim = ReplayClaim("auth", "op", 0, ReplayClaimState.RESOURCES_RESERVED, (), False, CONTEXT)
    return {
        "version": 1,
        "claims": {
            AuthoritativeClaimStore._claim_key(
                "auth", "op"
            ): AuthoritativeClaimStore._serialize_claim(claim)
        },
    }


@pytest.mark.parametrize(
    "bad",
    [
        {"version": 1, "claims": {}, "metadata": {"claim_generation": 99}},
        {"version": True, "claims": {}},
        {"claims": {}},
        {"version": 1, "claims": {"unrelated": {"claim_generation": 100}}},
        {"version": 1, "claims": {}, "metadata": "innocent"},
    ],
)
def test_invalid_envelope_nested_counts_and_metadata_deny(bad: object) -> None:
    with pytest.raises(RuntimeClaimStoreError):
        AuthoritativeClaimStore._rollback_checkpoint_for_document_static(IDENTITY, bad)


def test_malformed_unrelated_claim_denies_entire_store() -> None:
    doc = valid_document()
    claims = doc["claims"]
    assert isinstance(claims, dict)
    claims["other"] = {"claim_generation": 0}
    with pytest.raises(RuntimeClaimStoreError):
        AuthoritativeClaimStore._rollback_checkpoint_for_document_static(IDENTITY, doc)


@pytest.mark.parametrize("document", [{}, {"version": 1, "claims": {}}, valid_document()])
def test_valid_v1_checkpoint_bytes_remain_compatible(document: dict[str, object]) -> None:
    payload = {
        "domain": "familyos.custody.rollback-checkpoint.v1",
        "store_instance_id": IDENTITY.store_instance_id,
        "store_epoch": IDENTITY.store_epoch,
        "document": document,
    }
    expected = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    actual = AuthoritativeClaimStore._rollback_checkpoint_for_document_static(IDENTITY, document)
    assert actual.store_root_digest == expected
    assert actual.store_generation == (1 if document.get("claims") else 0)


def test_equal_scalar_generation_does_not_substitute_different_history() -> None:
    doc = valid_document()
    first = AuthoritativeClaimStore._rollback_checkpoint_for_document_static(IDENTITY, doc)
    other_claim = ReplayClaim(
        "auth", "different", 0, ReplayClaimState.RESOURCES_RESERVED, (), False, CONTEXT
    )
    other = {
        "version": 1,
        "claims": {
            AuthoritativeClaimStore._claim_key(
                "auth", "different"
            ): AuthoritativeClaimStore._serialize_claim(other_claim)
        },
    }
    second = AuthoritativeClaimStore._rollback_checkpoint_for_document_static(IDENTITY, other)
    assert first.store_generation == second.store_generation
    assert first.store_root_digest != second.store_root_digest
    with pytest.raises(RollbackContractError):
        require_store_checkpoint_match(observed=first, trusted=second)


def test_late_commit_after_timeout_cannot_enable_retry_or_other_local_mutations(
    tmp_path: Path,
) -> None:
    store, service = setup_store(tmp_path)
    reserve(store)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    class SlowAdvance:
        def exchange(self, request: AnchorRequest) -> AnchorResponse:
            if request.action is AnchorAction.ADVANCE:
                entered.set()
                release.wait(timeout=3)
                try:
                    return service.exchange(request)
                finally:
                    finished.set()
            return service.exchange(request)

    client = ProtocolRollbackAnchor(
        transport=SlowAdvance(),
        principal=PRINCIPAL,
        boundary=BOUNDARY,
        continuity=service.continuity,
    )
    slow = AuthoritativeClaimStore(
        tmp_path,
        store_identity=IDENTITY,
        rollback_anchor=client,
        anchor_timeout_seconds=0.05,
    )
    try:
        with pytest.raises(AnchorUncertain):
            intent(slow)
        assert entered.is_set() and not finished.is_set()
        assert slow.export_diagnostics()["pending_anchor_mutation"] is True
        with pytest.raises(RollbackContractError):
            reserve(store, "unrelated")
    finally:
        release.set()
        assert finished.wait(timeout=2)
    assert adapter(service).read_checkpoint() == store._current_rollback_checkpoint_locked()
    with pytest.raises(RecoveryRequired):
        fence(store)
    assert not service.executions


def test_completion_sync_failure_preserves_deny_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, service = setup_store(tmp_path)
    reserve(store)
    intent(store)
    original = store._sync_root
    calls = 0

    def fail_completion_once() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic completion sync failure")
        original()

    monkeypatch.setattr(store, "_sync_root", fail_completion_once)
    with pytest.raises(RecoveryRequired):
        fence(store)
    assert store.export_diagnostics()["pending_anchor_mutation"] is True
    reopened = AuthoritativeClaimStore(
        tmp_path,
        store_identity=IDENTITY,
        rollback_anchor=adapter(service),
    )
    with pytest.raises(RecoveryRequired):
        fence(reopened)
    assert len(service.executions) == 1


@pytest.mark.parametrize(
    "raw",
    [
        '{"version":1,"version":1,"claims":{}}',
        '{"version":1,"claims":{},"metadata":NaN}',
        '{"version":1,"claims":{"x":{"claim_generation":0,"claim_generation":1}}}',
    ],
)
def test_duplicate_json_members_and_nonfinite_constants_deny(tmp_path: Path, raw: str) -> None:
    store, _ = setup_store(tmp_path)
    (tmp_path / "claims.json").write_text(raw)
    with pytest.raises(RuntimeClaimStoreError):
        reserve(store)


@pytest.mark.parametrize("profile", list(AnchorProfile))
def test_all_profile_seams_support_synthetic_runtime_without_selection(
    tmp_path: Path,
    profile: AnchorProfile,
) -> None:
    _, service = setup_store(tmp_path)
    internal = profile is AnchorProfile.PROTECTED_INTERNAL_ANCHOR_PROFILE
    boundary = ProfileBoundary(
        profile,
        ThreatScope.EXTERNAL_DISK if internal else ThreatScope.WHOLE_MAC,
        "internal-mac" if internal else "independent-witness",
        "governed-recovery",
    )
    client = ProtocolRollbackAnchor(
        transport=service,
        principal=PRINCIPAL,
        boundary=boundary,
        continuity=None if internal else service.continuity,
    )
    store = AuthoritativeClaimStore(tmp_path, store_identity=IDENTITY, rollback_anchor=client)
    reserve(store)
    intent(store)
    fence(store)
    with pytest.raises(AnchorRejected):
        fence(store)


def test_runtime_cannot_downgrade_to_unfenced_r2b_anchor(tmp_path: Path) -> None:
    store, service = setup_store(tmp_path)
    reserve(store)
    intent(store)
    client = adapter(service)

    class CheckpointOnly:
        def read_checkpoint(self) -> RollbackCheckpoint:
            return client.read_checkpoint()

        def advance_checkpoint(
            self,
            *,
            expected_current: RollbackCheckpoint,
            candidate: RollbackCheckpoint,
        ) -> None:
            client.advance_checkpoint(expected_current=expected_current, candidate=candidate)

    legacy = AuthoritativeClaimStore(
        tmp_path, store_identity=IDENTITY, rollback_anchor=CheckpointOnly()
    )
    with pytest.raises(RuntimeClaimStoreError, match="fencing"):
        fence(legacy)
    assert not service.executions


def test_execution_duplicate_receipt_is_not_new_permission(tmp_path: Path) -> None:
    _, service = setup_store(tmp_path)
    request = AnchorRequest(
        AnchorAction.EXECUTE_ONCE,
        "worker",
        IDENTITY,
        "session",
        "request",
        expected_current=service.checkpoint,
        idempotency_key="same",
        execution_id="auth-op",
    )
    first = service.exchange(request)
    duplicate = service.exchange(replace(request, request_id="second"))
    assert first.outcome is AnchorOutcome.COMMITTED
    assert duplicate.outcome is AnchorOutcome.DUPLICATE
    assert service.mutations == 1

    class DuplicateTransport:
        def exchange(self, request: AnchorRequest) -> AnchorResponse:
            return replace(duplicate, request=request)

    client = ProtocolRollbackAnchor(
        transport=DuplicateTransport(),
        principal=PRINCIPAL,
        boundary=BOUNDARY,
        continuity=service.continuity,
    )
    with pytest.raises(AnchorRejected):
        client.acquire_execution(expected_current=service.checkpoint, execution_id="auth-op")


def test_c1_t1_definite_fence_rejection_preserves_cross_claim_availability(tmp_path: Path) -> None:
    store, service = setup_store(tmp_path)
    reserve(store)
    intent(store)
    fence(store)
    for _ in range(2):
        with pytest.raises(AnchorRejected):
            fence(store)
        assert not store.export_diagnostics()["pending_anchor_mutation"]
        assert not (tmp_path / "anchor-pending.json").exists()
    assert len(service.executions) == 1
    assert reserve(store, "unrelated").claim_generation == 0
    assert len(service.executions) == 1
    reopened = AuthoritativeClaimStore(
        tmp_path, store_identity=IDENTITY, rollback_anchor=adapter(service)
    )
    assert reserve(reopened, "after-restart").claim_generation == 0


@pytest.mark.parametrize("operation", ["reserve", "intent", "terminal"])
def test_c1_t2_definite_advance_rejection_clears_marker_but_preserves_store_ahead(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    store, service = setup_store(tmp_path)
    if operation != "reserve":
        reserve(store)
    if operation == "terminal":
        intent(store)
    before = service.checkpoint
    mutations = service.mutations
    rejection = AnchorRejected("synthetic definite non-commit")
    client = adapter(service)

    def reject(*, expected_current: RollbackCheckpoint, candidate: RollbackCheckpoint) -> None:
        assert expected_current == before
        assert candidate.store_generation > before.store_generation
        raise rejection

    monkeypatch.setattr(client, "advance_checkpoint", reject)
    store = AuthoritativeClaimStore(tmp_path, store_identity=IDENTITY, rollback_anchor=client)
    with pytest.raises(AnchorRejected) as error:
        if operation == "reserve":
            reserve(store)
        elif operation == "intent":
            intent(store)
        else:
            store.record_terminal(
                authorization_id="auth",
                operation_id="op",
                context_digest=CONTEXT,
                terminal_state=ReplayClaimState.SPENT_UNKNOWN,
                expected_generation=1,
            )
    assert error.value is rejection
    assert service.checkpoint == before and service.mutations == mutations
    assert not store.export_diagnostics()["pending_anchor_mutation"]
    assert not (tmp_path / "anchor-pending.json").exists()
    local = store._current_rollback_checkpoint_locked()
    assert local.store_generation > before.store_generation
    # No automatic rollback/repair: legitimate store-ahead denial still applies.
    assert classify_recovery(local=local, trusted=before) is RecoveryState.LOCAL_AHEAD_BLOCKED
    bytes_after_rejection = (tmp_path / "claims.json").read_bytes()
    with pytest.raises(RollbackRejectedError) as unrelated_error:
        reserve(store, "unrelated")
    assert unrelated_error.value.decision is RollbackVerificationDecision.ANCHOR_LAG_OR_UNCERTAIN
    assert (tmp_path / "claims.json").read_bytes() == bytes_after_rejection
    assert service.checkpoint == before and service.mutations == mutations


@pytest.mark.parametrize("operation", ["advance", "fence"])
def test_c1_t3_uncertain_mutation_preserves_cross_claim_blocking(
    tmp_path: Path,
    operation: str,
) -> None:
    store, service = setup_store(tmp_path)
    reserve(store)
    if operation == "fence":
        intent(store)
    service.lose_reply = True
    with pytest.raises(AnchorUncertain):
        if operation == "advance":
            intent(store)
        else:
            fence(store)
    assert adapter(service).read_checkpoint() == store._current_rollback_checkpoint_locked()
    assert store.export_diagnostics()["pending_anchor_mutation"] is True
    assert (tmp_path / "anchor-pending.json").exists()
    reopened = AuthoritativeClaimStore(
        tmp_path, store_identity=IDENTITY, rollback_anchor=adapter(service)
    )
    for runtime in (store, reopened):
        with pytest.raises(RecoveryRequired):
            reserve(runtime, "unrelated")
        with pytest.raises(RecoveryRequired):
            fence(runtime)
        with pytest.raises(RecoveryRequired):
            runtime.recover_after_restart(authorization_id="auth", operation_id="op")


def test_m2_intervening_legitimate_advance_preserves_exact_fence_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, service = setup_store(tmp_path / "first")
    reserve(store)
    intent(store)
    before = service.checkpoint
    shutil.copytree(tmp_path / "first", tmp_path / "other")
    other = AuthoritativeClaimStore(
        tmp_path / "other", store_identity=IDENTITY, rollback_anchor=adapter(service)
    )
    client = adapter(service)
    acquire = client.acquire_execution

    def intervene(*, expected_current: RollbackCheckpoint, execution_id: str) -> None:
        acquire(expected_current=expected_current, execution_id=execution_id)
        assert reserve(other, "legitimate-unrelated").claim_generation == 0

    monkeypatch.setattr(client, "acquire_execution", intervene)
    store = AuthoritativeClaimStore(
        tmp_path / "first", store_identity=IDENTITY, rollback_anchor=client
    )
    with pytest.raises(RollbackRejectedError) as error:
        fence(store)
    assert error.value.decision is RollbackVerificationDecision.ROLLBACK_DETECTED
    assert service.checkpoint.store_generation == before.store_generation + 1
    assert len(service.executions) == 1
    assert store.export_diagnostics()["pending_anchor_mutation"] is True
    assert (tmp_path / "first/anchor-pending.json").exists()
    assert store._current_rollback_checkpoint_locked() == before
    assert (
        other.load_authoritative(authorization_id="auth", operation_id="legitimate-unrelated")
        is not None
    )


@pytest.mark.parametrize("operation", ["advance", "fence"])
def test_c1_rejection_from_postcommit_readback_is_not_clean_mutation_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    store, service = setup_store(tmp_path)
    reserve(store)
    if operation == "fence":
        intent(store)
    client = adapter(service)
    read = client.read_checkpoint
    calls = 0
    rejection = AnchorRejected("readback access denied after commitment")

    def deny_postcommit_read() -> RollbackCheckpoint:
        nonlocal calls
        calls += 1
        if calls == (3 if operation == "advance" else 2):
            raise rejection
        return read()

    monkeypatch.setattr(client, "read_checkpoint", deny_postcommit_read)
    store = AuthoritativeClaimStore(tmp_path, store_identity=IDENTITY, rollback_anchor=client)
    with pytest.raises(AnchorRejected) as error:
        if operation == "advance":
            intent(store)
        else:
            fence(store)
    assert error.value is rejection
    assert store.export_diagnostics()["pending_anchor_mutation"] is True
    with pytest.raises(RecoveryRequired):
        reserve(store, "unrelated")


def test_c1_cleanup_failure_after_definite_rejection_remains_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, service = setup_store(tmp_path)
    reserve(store)
    intent(store)
    fence(store)
    original = store._sync_root
    calls = 0

    def fail_cleanup_once() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("cleanup durability uncertain")
        original()

    monkeypatch.setattr(store, "_sync_root", fail_cleanup_once)
    with pytest.raises(RecoveryRequired):
        fence(store)
    assert store.export_diagnostics()["pending_anchor_mutation"] is True
    assert (tmp_path / "anchor-pending.json").exists()
    with pytest.raises(RecoveryRequired):
        reserve(store, "unrelated")
    assert len(service.executions) == 1


@pytest.mark.parametrize("operation", ["reserve", "intent", "terminal"])
def test_c1_t2_rejected_stale_advance_allows_unrelated_claim_when_checkpoint_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    store, service = setup_store(tmp_path / "first")
    if operation != "reserve":
        reserve(store)
    if operation == "terminal":
        intent(store)
    shutil.copytree(tmp_path / "first", tmp_path / "other")
    other = AuthoritativeClaimStore(
        tmp_path / "other", store_identity=IDENTITY, rollback_anchor=adapter(service)
    )
    client = adapter(service)
    advance = client.advance_checkpoint
    rejection_seen: list[AnchorRejected] = []

    def transition(runtime: AuthoritativeClaimStore) -> None:
        if operation == "reserve":
            reserve(runtime)
        elif operation == "intent":
            intent(runtime)
        else:
            runtime.record_terminal(
                authorization_id="auth",
                operation_id="op",
                context_digest=CONTEXT,
                terminal_state=ReplayClaimState.SPENT_UNKNOWN,
                expected_generation=1,
            )

    def other_wins(*, expected_current: RollbackCheckpoint, candidate: RollbackCheckpoint) -> None:
        transition(other)
        assert service.checkpoint == candidate
        try:
            advance(expected_current=expected_current, candidate=candidate)
        except AnchorRejected as error:
            rejection_seen.append(error)
            raise

    monkeypatch.setattr(client, "advance_checkpoint", other_wins)
    store = AuthoritativeClaimStore(
        tmp_path / "first", store_identity=IDENTITY, rollback_anchor=client
    )
    count = service.mutations
    with pytest.raises(AnchorRejected) as error:
        transition(store)
    assert rejection_seen == [error.value]
    assert service.mutations == count + 1  # Only the other runtime committed.
    assert not store.export_diagnostics()["pending_anchor_mutation"]
    assert service.checkpoint == store._current_rollback_checkpoint_locked()
    # Remove the scheduling hook, not state: there is no rewind or repair.
    monkeypatch.setattr(client, "advance_checkpoint", advance)
    assert reserve(store, "unrelated").claim_generation == 0
    assert service.mutations == count + 2


@pytest.mark.parametrize("operation", ["advance", "fence"])
def test_c1_unexpected_mutation_failure_keeps_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    store, service = setup_store(tmp_path)
    reserve(store)
    if operation == "fence":
        intent(store)
    client = adapter(service)
    unexpected = RuntimeError("synthetic unexpected failure")

    def fail_advance(
        *, expected_current: RollbackCheckpoint, candidate: RollbackCheckpoint
    ) -> None:
        raise unexpected

    def fail_fence(*, expected_current: RollbackCheckpoint, execution_id: str) -> None:
        raise unexpected

    if operation == "advance":
        monkeypatch.setattr(client, "advance_checkpoint", fail_advance)
    else:
        monkeypatch.setattr(client, "acquire_execution", fail_fence)
    store = AuthoritativeClaimStore(tmp_path, store_identity=IDENTITY, rollback_anchor=client)
    with pytest.raises(RuntimeError) as error:
        if operation == "advance":
            intent(store)
        else:
            fence(store)
    assert error.value is unexpected
    assert store.export_diagnostics()["pending_anchor_mutation"] is True
    assert (tmp_path / "anchor-pending.json").exists()
