from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from familyos_pilot0.custody_anchor_adapter import (
    BoundedAnchorCalls,
    ProtocolRollbackAnchor,
)
from familyos_pilot0.custody_anchor_protocol import (
    AnchorAction,
    AnchorOutcome,
    AnchorRejected,
    AnchorRequest,
    AnchorRight,
    AnchorUnavailable,
    AnchorUncertain,
)
from familyos_pilot0.custody_rollback_contracts import (
    RollbackCheckpoint,
    RollbackRejectedError,
)
from familyos_pilot0.custody_sqlite_witness import (
    SQLiteWitness,
    SyntheticLoopbackTransport,
    enroll_synthetic_witness,
)
from familyos_pilot0.custody_witness_state import (
    MAX_REQUEST_BYTES,
    HeadContinuity,
    WitnessHead,
    WitnessState,
)
from familyos_pilot0.custody_worker_runtime import (
    AuthoritativeClaimStore,
    RecoveryRequired,
)
from tests.custody_sqlite_witness_fixtures import (
    ADMIN,
    IDENTITY,
    READER,
    SECOND,
    WORKER,
    FakeFileHead,
    adapter,
)


@dataclass
class Rig:
    path: Path
    head: FakeFileHead
    initial: RollbackCheckpoint
    service: SQLiteWitness

    def client(self) -> ProtocolRollbackAnchor:
        return adapter(self.service, self.head)

    def reopen(self) -> None:
        self.service.close()
        self.service = SQLiteWitness(self.path, identity=IDENTITY, head=self.head)

    def request(self, action: AnchorAction, key: str = "same") -> AnchorRequest:
        return AnchorRequest(
            action,
            WORKER.name,
            IDENTITY,
            "session",
            "exchange",
            expected_current=None if action is AnchorAction.READ else self.initial,
            candidate=(
                replace(self.initial, store_generation=1, store_root_digest="a" * 64)
                if action is AnchorAction.ADVANCE
                else None
            ),
            idempotency_key=None if action is AnchorAction.READ else key,
            execution_id="permanent-operation" if action is AnchorAction.EXECUTE_ONCE else None,
        )

    def exchange(self, request: AnchorRequest) -> AnchorOutcome:
        return SyntheticLoopbackTransport(self.service, WORKER.name).exchange(request).outcome


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    initial = AuthoritativeClaimStore.expected_empty_rollback_checkpoint(IDENTITY)
    path = tmp_path / "witness.sqlite3"
    head = FakeFileHead(tmp_path / "separate-head.json")
    enrolled = enroll_synthetic_witness(
        path,
        initial=initial,
        principals=(WORKER, SECOND, READER),
        administrator=ADMIN,
    )
    head.enroll(enrolled, ADMIN)
    service = SQLiteWitness(path, identity=IDENTITY, head=head)
    model = Rig(path, head, initial, service)
    try:
        yield model
    finally:
        model.service.close()


def test_exact_read_and_explicit_durability(rig: Rig) -> None:
    before = rig.path.read_bytes(), rig.head.path.read_bytes()
    assert rig.client().read_checkpoint() == rig.initial
    assert before == (rig.path.read_bytes(), rig.head.path.read_bytes())
    from familyos_pilot0.custody_sqlite_witness import _database

    with _database(rig.path) as db:
        assert db.execute("PRAGMA synchronous").fetchone()[0] == 3
        assert db.execute("PRAGMA fullfsync").fetchone()[0] == 1
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_advance_dedup_and_stale_cas_survive_restart(rig: Rig) -> None:
    request = rig.request(AnchorAction.ADVANCE)
    assert request.candidate is not None
    assert rig.exchange(request) is AnchorOutcome.COMMITTED
    saved = rig.head.read()
    rig.reopen()
    assert rig.client().read_checkpoint() == request.candidate
    assert (
        rig.exchange(replace(request, request_id="retry", session_id="new"))
        is AnchorOutcome.DUPLICATE
    )
    assert rig.exchange(replace(request, idempotency_key="stale")) is AnchorOutcome.REJECTED
    assert (
        rig.exchange(
            replace(
                request,
                candidate=replace(
                    request.candidate,
                    store_root_digest="b" * 64,
                ),
            )
        )
        is AnchorOutcome.REJECTED
    )
    assert rig.head.read() == saved


def test_execution_receipt_is_permanent_across_principals_and_restart(rig: Rig) -> None:
    request = rig.request(AnchorAction.EXECUTE_ONCE)
    head = rig.head.read()
    assert rig.exchange(request) is AnchorOutcome.COMMITTED
    assert rig.client().read_checkpoint() == rig.initial
    assert rig.head.read().sequence == head.sequence + 1
    assert rig.head.read().state_digest != head.state_digest
    rig.reopen()
    assert rig.exchange(request) is AnchorOutcome.DUPLICATE
    for principal in (WORKER, SECOND):
        with pytest.raises(AnchorRejected):
            adapter(rig.service, rig.head, principal).acquire_execution(
                expected_current=rig.initial,
                execution_id="permanent-operation",
            )
    assert rig.head.read().sequence == 1


@pytest.mark.parametrize("action", [AnchorAction.ADVANCE, AnchorAction.EXECUTE_ONCE])
def test_concurrent_exactly_one_winner(rig: Rig, action: AnchorAction) -> None:
    barrier = threading.Barrier(2)

    def compete(index: int) -> AnchorOutcome:
        barrier.wait(timeout=2)
        return rig.exchange(rig.request(action, str(index)))

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(compete, range(2)))
    assert results.count(AnchorOutcome.COMMITTED) == 1
    assert results.count(AnchorOutcome.REJECTED) == 1
    assert rig.head.read().sequence == 1


@pytest.mark.parametrize("restore", ["database", "head", "both"])
def test_independent_restore_and_correlated_limit(rig: Rig, restore: str) -> None:
    old_db, old_head = rig.path.read_bytes(), rig.head.path.read_bytes()
    assert rig.exchange(rig.request(AnchorAction.EXECUTE_ONCE)) is AnchorOutcome.COMMITTED
    current_db = rig.path.read_bytes()
    rig.service.close()
    if restore in {"database", "both"}:
        rig.path.write_bytes(old_db)
    if restore in {"head", "both"}:
        rig.head.path.write_bytes(old_head)
    if restore != "both":
        with pytest.raises(AnchorUnavailable, match="continuity"):
            rig.reopen()
    else:
        rig.reopen()
        # Deliberately erase ALL current authority. This demonstrates the structural limit.
        assert rig.exchange(rig.request(AnchorAction.EXECUTE_ONCE)) is AnchorOutcome.COMMITTED
        assert rig.path.read_bytes() == current_db


@pytest.mark.parametrize(
    "phase",
    [
        "before_stage",
        "after_stage",
        "after_head",
        "before_finalize_commit",
        "after_finalize",
    ],
)
@pytest.mark.parametrize("action", [AnchorAction.ADVANCE, AnchorAction.EXECUTE_ONCE])
def test_abrupt_process_exit_at_every_stage(rig: Rig, phase: str, action: AnchorAction) -> None:
    rig.service.close()
    script = """
import os, sys
from pathlib import Path
from dataclasses import replace
from familyos_pilot0.custody_anchor_protocol import AnchorAction, AnchorRequest
from familyos_pilot0.custody_sqlite_witness import SQLiteWitness, SyntheticLoopbackTransport
from familyos_pilot0.custody_worker_runtime import AuthoritativeClaimStore
from tests.custody_sqlite_witness_fixtures import IDENTITY, FakeFileHead
db, head, phase, action = sys.argv[1:]
def crash(at):
    if at == phase: os._exit(79)
s = SQLiteWitness(Path(db), identity=IDENTITY, head=FakeFileHead(Path(head)), fault_injector=crash)
initial = AuthoritativeClaimStore.expected_empty_rollback_checkpoint(IDENTITY)
action = AnchorAction(action)
request = AnchorRequest(action, "worker", IDENTITY, "s", "r", expected_current=initial,
    candidate=(replace(initial, store_generation=1, store_root_digest="a"*64)
               if action is AnchorAction.ADVANCE else None),
    idempotency_key="crash",
    execution_id="permanent-operation" if action is AnchorAction.EXECUTE_ONCE else None)
SyntheticLoopbackTransport(s, "worker").exchange(request)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(rig.path),
            str(rig.head.path),
            phase,
            action.value,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 79, result.stderr
    if phase in {"after_stage", "after_head", "before_finalize_commit"}:
        for _ in range(2):
            with pytest.raises(AnchorUnavailable, match="staged"):
                rig.reopen()
    else:
        rig.reopen()
        if phase == "before_stage":
            assert rig.client().read_checkpoint() == rig.initial
            assert rig.head.read().sequence == 0
        else:
            assert rig.head.read().sequence == 1
            assert rig.exchange(rig.request(action, "crash")) is AnchorOutcome.DUPLICATE


def test_lost_reply_is_idempotent_after_restart(rig: Rig) -> None:
    def lose(phase: str) -> None:
        if phase == "after_finalize":
            raise OSError("reply lost after durable commit")

    rig.service._fault_injector = lose
    with pytest.raises(AnchorUncertain):
        rig.exchange(rig.request(AnchorAction.ADVANCE))
    with pytest.raises(AnchorUnavailable):
        rig.client().read_checkpoint()
    rig.reopen()
    assert rig.exchange(rig.request(AnchorAction.ADVANCE)) is AnchorOutcome.DUPLICATE
    assert rig.head.read().sequence == 1


def test_backend_rejection_after_staging_is_uncertain(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject(*args: object) -> None:
        raise AnchorRejected("head CAS rejected after database staging")

    monkeypatch.setattr(rig.head, "compare_and_set", reject)
    with pytest.raises(AnchorUncertain):
        rig.exchange(rig.request(AnchorAction.ADVANCE))
    with pytest.raises(AnchorUnavailable, match="staged"):
        rig.reopen()


def test_timeout_late_commit_bounded_busy_and_restart(rig: Rig) -> None:
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def pause(phase: str) -> None:
        if phase == "after_stage":
            entered.set()
            assert release.wait(timeout=5)

    rig.service._fault_injector = pause
    calls = BoundedAnchorCalls(0.05)
    outcomes: list[AnchorOutcome] = []

    def late() -> None:
        try:
            outcomes.append(rig.exchange(rig.request(AnchorAction.EXECUTE_ONCE)))
        finally:
            finished.set()

    try:
        with pytest.raises(AnchorUncertain):
            calls.call(late, mutation=True)
        assert entered.is_set()
        with pytest.raises(AnchorUnavailable, match="outstanding"):
            calls.call(lambda: None, mutation=False)
    finally:
        release.set()
        assert finished.wait(timeout=3)
    assert outcomes == [AnchorOutcome.COMMITTED]  # Abandoned caller received no grant.
    rig.reopen()
    with pytest.raises(AnchorRejected):
        rig.client().acquire_execution(
            expected_current=rig.initial, execution_id="permanent-operation"
        )


def test_single_owner_and_bounded_service_admission(rig: Rig) -> None:
    with pytest.raises(AnchorUnavailable, match="already owned") as caught:
        SQLiteWitness(rig.path, identity=IDENTITY, head=rig.head)
    assert isinstance(caught.value.__cause__, BlockingIOError)
    rig.service._wait = 0.01
    with rig.service._locked(), pytest.raises(AnchorUnavailable, match="busy"):
        rig.exchange(rig.request(AnchorAction.READ))
    assert rig.client().read_checkpoint() == rig.initial


@pytest.mark.parametrize("kind", ["principal", "store", "epoch", "unknown-peer", "read-only"])
def test_authentication_and_lineage_deny(rig: Rig, kind: str) -> None:
    request = rig.request(AnchorAction.EXECUTE_ONCE)
    peer = WORKER.name
    if kind == "principal":
        request = replace(request, principal=SECOND.name)
    elif kind in {"store", "epoch"}:
        identity = replace(
            IDENTITY,
            **({"store_instance_id": "wrong"} if kind == "store" else {"store_epoch": 2}),
        )
        request = replace(
            request,
            identity=identity,
            expected_current=replace(rig.initial, identity=identity),
        )
    elif kind == "unknown-peer":
        peer = "unknown"
        request = replace(request, principal=peer)
    else:
        peer = READER.name
        request = replace(request, principal=peer)
    with pytest.raises(AnchorRejected):
        SyntheticLoopbackTransport(rig.service, peer).exchange(request)
    assert rig.head.read().sequence == 0


def test_no_implicit_enrollment_or_runtime_admin(rig: Rig, tmp_path: Path) -> None:
    missing = tmp_path / "absent.sqlite3"
    with pytest.raises(AnchorUnavailable):
        SQLiteWitness(missing, identity=IDENTITY, head=rig.head)
    assert not missing.exists()
    with pytest.raises(AnchorRejected):
        enroll_synthetic_witness(
            missing, initial=rig.initial, principals=(WORKER,), administrator=WORKER
        )
    assert not missing.exists()
    with pytest.raises(FileExistsError):
        enroll_synthetic_witness(
            rig.path, initial=rig.initial, principals=(WORKER,), administrator=ADMIN
        )
    with pytest.raises(ValueError, match="administrative"):
        enroll_synthetic_witness(
            missing, initial=rig.initial, principals=(ADMIN,), administrator=ADMIN
        )
    assert not missing.exists()
    assert AnchorRight.RECOVER_ADMIN not in WORKER.rights
    transport = SyntheticLoopbackTransport(rig.service, WORKER.name)
    assert not any(hasattr(transport, n) for n in ("enroll", "reset", "recover", "release"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("protocol_version", "unknown"),
        ("principal", "x" * (MAX_REQUEST_BYTES + 1)),
        ("action", "RECOVER_ADMIN"),
        ("candidate", {}),
        ("request_id", ""),
    ],
)
def test_forged_or_oversized_typed_request_denied(rig: Rig, field: str, value: object) -> None:
    request = rig.request(AnchorAction.READ)
    object.__setattr__(request, field, value)
    with pytest.raises(AnchorRejected):
        rig.exchange(request)
    assert rig.head.read().sequence == 0


@pytest.mark.parametrize(
    "mutation", ["version", "policy", "receipt", "execution", "extra", "duplicate"]
)
def test_strict_persisted_state_and_policy_commitment(rig: Rig, mutation: str) -> None:
    rig.exchange(rig.request(AnchorAction.EXECUTE_ONCE))
    rig.service.close()
    with sqlite3.connect(rig.path) as db:
        raw = db.execute("SELECT committed FROM witness").fetchone()[0]
        obj = json.loads(raw)
        if mutation == "version":
            obj["version"] = True
        elif mutation == "policy":
            obj["policy_revision"] = 2
        elif mutation == "receipt":
            obj["receipts"][0]["outcome"] = "DUPLICATE"
        elif mutation == "execution":
            obj["executions"] = []
        elif mutation == "extra":
            obj["metadata"] = {}
        elif mutation == "duplicate":
            raw = raw.replace('"version":1', '"version":1,"version":1')
        if mutation != "duplicate":
            raw = json.dumps(obj, sort_keys=True, separators=(",", ":"))
        db.execute("UPDATE witness SET committed=?", (raw,))
    with pytest.raises(AnchorUnavailable, match="invalid witness state"):
        rig.reopen()


def test_changed_rights_cannot_keep_old_head(rig: Rig) -> None:
    rig.service.close()
    with sqlite3.connect(rig.path) as db:
        state = WitnessState.decode(db.execute("SELECT committed FROM witness").fetchone()[0])
        changed = replace(state, principals=(replace(WORKER, rights=READER.rights),))
        db.execute("UPDATE witness SET committed=?", (changed.encode(),))
    with pytest.raises(AnchorUnavailable, match="continuity"):
        rig.reopen()


def test_absent_head_or_empty_db_does_not_bootstrap(rig: Rig) -> None:
    rig.head.available = False
    with pytest.raises(AnchorUnavailable):
        rig.client().read_checkpoint()
    rig.head.available = True
    rig.service.close()
    with sqlite3.connect(rig.path) as db:
        db.execute("DELETE FROM witness")
    with pytest.raises(AnchorUnavailable, match="missing"):
        rig.reopen()


def runtime(rig: Rig, root: Path) -> AuthoritativeClaimStore:
    return AuthoritativeClaimStore(root, store_identity=IDENTITY, rollback_anchor=rig.client())


def prepare(store: AuthoritativeClaimStore) -> None:
    store.reserve(authorization_id="auth", operation_id="op", context_digest="a" * 64)
    store.claim_key_use_intent(
        authorization_id="auth",
        operation_id="op",
        context_digest="a" * 64,
        signing_request_digest="b" * 64,
        expected_generation=0,
    )


def fence(store: AuthoritativeClaimStore) -> None:
    store.claim_for_signer(
        authorization_id="auth",
        operation_id="op",
        context_digest="a" * 64,
        signing_request_digest="b" * 64,
    )


def test_runtime_clone_fence_and_c1_preserved(rig: Rig, tmp_path: Path) -> None:
    original = runtime(rig, tmp_path / "original")
    prepare(original)
    shutil.copytree(tmp_path / "original", tmp_path / "clone")
    fence(original)
    clone = runtime(rig, tmp_path / "clone")
    with pytest.raises(AnchorRejected):
        fence(clone)
    assert not clone.export_diagnostics()["pending_anchor_mutation"]
    clone.reserve(authorization_id="other", operation_id="op", context_digest="a" * 64)
    rig.reopen()
    assert rig.head.read().sequence == 4


def test_runtime_uncertainty_cannot_be_cleared_by_equal_read(rig: Rig, tmp_path: Path) -> None:
    store = runtime(rig, tmp_path / "claims")
    prepare(store)

    def lose(phase: str) -> None:
        if phase == "after_finalize":
            raise OSError("reply lost")

    rig.service._fault_injector = lose
    with pytest.raises(AnchorUncertain):
        fence(store)
    rig.reopen()
    reopened = runtime(rig, tmp_path / "claims")
    assert rig.client().read_checkpoint() == reopened._current_rollback_checkpoint_locked()
    with pytest.raises(RecoveryRequired):
        fence(reopened)
    with pytest.raises(RecoveryRequired):
        reopened.recover_after_restart(authorization_id="auth", operation_id="op")


def test_runtime_m2_exact_readback_preserved(
    rig: Rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = runtime(rig, tmp_path / "first")
    prepare(first)
    shutil.copytree(tmp_path / "first", tmp_path / "other")
    other = runtime(rig, tmp_path / "other")
    client = rig.client()
    consume = client.acquire_execution

    def intervene(*, expected_current: RollbackCheckpoint, execution_id: str) -> None:
        consume(expected_current=expected_current, execution_id=execution_id)
        other.reserve(authorization_id="other", operation_id="op", context_digest="a" * 64)

    monkeypatch.setattr(client, "acquire_execution", intervene)
    first = AuthoritativeClaimStore(
        tmp_path / "first", store_identity=IDENTITY, rollback_anchor=client
    )
    with pytest.raises(RollbackRejectedError):
        fence(first)
    assert first.export_diagnostics()["pending_anchor_mutation"]
    assert rig.head.read().sequence == 4


def test_stale_bound_response_fails_independent_continuity(rig: Rig) -> None:
    old = SyntheticLoopbackTransport(rig.service, WORKER.name).exchange(
        rig.request(AnchorAction.READ)
    )
    rig.exchange(rig.request(AnchorAction.EXECUTE_ONCE))
    with pytest.raises(AnchorUnavailable):
        HeadContinuity(rig.head, IDENTITY).require_current(old)


@pytest.mark.parametrize("difference", ["root", "generation"])
def test_full_tuple_cas_rejects_different_expected(rig: Rig, difference: str) -> None:
    expected = replace(
        rig.initial,
        **({"store_root_digest": "f" * 64} if difference == "root" else {"store_generation": 1}),
    )
    request = replace(rig.request(AnchorAction.ADVANCE), expected_current=expected)
    assert rig.exchange(request) is AnchorOutcome.REJECTED
    assert rig.head.read().sequence == 0


@pytest.mark.parametrize("phase", ["after_stage", "after_head", "before_finalize_commit"])
def test_read_and_fence_stay_denied_after_exception(rig: Rig, phase: str) -> None:
    def fail(at: str) -> None:
        if at == phase:
            raise OSError("synthetic persistence fault")

    rig.service._fault_injector = fail
    with pytest.raises(AnchorUncertain):
        rig.exchange(rig.request(AnchorAction.EXECUTE_ONCE))
    for action in (AnchorAction.READ, AnchorAction.ADVANCE, AnchorAction.EXECUTE_ONCE):
        with pytest.raises(AnchorUnavailable):
            rig.exchange(rig.request(action))
    with pytest.raises(AnchorUnavailable, match="staged"):
        rig.reopen()


def test_head_commit_with_lost_head_reply_remains_staged(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = rig.head.compare_and_set

    def lose(expected: WitnessHead, candidate: WitnessHead) -> None:
        original(expected, candidate)
        raise OSError("head reply lost")

    monkeypatch.setattr(rig.head, "compare_and_set", lose)
    with pytest.raises(AnchorUncertain):
        rig.exchange(rig.request(AnchorAction.EXECUTE_ONCE))
    assert rig.head.read().sequence == 1
    with pytest.raises(AnchorUnavailable, match="staged"):
        rig.reopen()


def test_live_database_restore_is_checked_on_every_exchange(rig: Rig) -> None:
    before = rig.path.read_bytes()
    rig.exchange(rig.request(AnchorAction.EXECUTE_ONCE))
    rig.path.write_bytes(before)  # No open SQLite connection; simulate an out-of-band restore.
    with pytest.raises(AnchorUnavailable, match="continuity"):
        rig.exchange(rig.request(AnchorAction.READ))


@pytest.mark.parametrize("change", ["version", "table", "trigger"])
def test_sqlite_schema_changes_deny(rig: Rig, change: str) -> None:
    rig.service.close()
    with sqlite3.connect(rig.path) as db:
        if change == "version":
            db.execute("PRAGMA user_version=2")
        elif change == "table":
            db.execute("CREATE TABLE extra (id INTEGER)")
        else:
            db.execute("CREATE TRIGGER extra AFTER UPDATE ON witness BEGIN SELECT 1; END")
    with pytest.raises(AnchorUnavailable):
        rig.reopen()


def test_capacity_denies_without_pruning_history(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    from familyos_pilot0 import custody_witness_state

    with sqlite3.connect(rig.path) as db:
        size = len(db.execute("SELECT committed FROM witness").fetchone()[0].encode())
    before = rig.path.read_bytes(), rig.head.read()
    monkeypatch.setattr(custody_witness_state, "MAX_STATE_BYTES", size)
    with pytest.raises(AnchorRejected, match="capacity"):
        rig.exchange(rig.request(AnchorAction.EXECUTE_ONCE))
    assert before == (rig.path.read_bytes(), rig.head.read())


def test_wrong_pinned_epoch_cannot_open_existing_database(rig: Rig) -> None:
    rig.service.close()
    with pytest.raises(AnchorUnavailable, match="lineage"):
        SQLiteWitness(rig.path, identity=replace(IDENTITY, store_epoch=2), head=rig.head)
