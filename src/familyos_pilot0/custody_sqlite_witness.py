"""Synthetic durable R2C witness, with no production defaults or network listener.

One owning process, serialized exchanges, SQLite staging, external head CAS, then
SQLite finalization. Every unfinished stage blocks after restart; no auto-repair.
"""

from __future__ import annotations

import fcntl
import os
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from familyos_pilot0.custody_anchor_adapter import BoundedAnchorCalls
from familyos_pilot0.custody_anchor_protocol import (
    AnchorAction,
    AnchorOutcome,
    AnchorPrincipal,
    AnchorRejected,
    AnchorRequest,
    AnchorResponse,
    AnchorRight,
    AnchorUnavailable,
    AnchorUncertain,
)
from familyos_pilot0.custody_rollback_contracts import (
    RollbackCheckpoint,
    RollbackContractError,
    StoreIdentity,
    require_anchor_advancement,
)
from familyos_pilot0.custody_witness_state import (
    MAX_STATE_BYTES,
    IndependentWitnessHead,
    WitnessHead,
    WitnessState,
    checked_request,
    receipt_request,
)

_SCHEMA = (
    "CREATE TABLE witness (slot INTEGER PRIMARY KEY CHECK(slot = 1), "
    "committed TEXT NOT NULL, staged TEXT) STRICT"
)


@contextmanager
def _database(path: Path) -> Iterator[sqlite3.Connection]:
    # mode=rw never creates a missing database; no implicit initialization.
    connection = sqlite3.connect(path.absolute().as_uri() + "?mode=rw", uri=True, timeout=0)
    try:
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_STATE_BYTES * 2 + 1024)
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA synchronous=EXTRA")
        connection.execute("PRAGMA fullfsync=ON")
        if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
            raise AnchorUnavailable("unexpected journal mode; no automatic migration")
        yield connection
    finally:
        connection.close()


def enroll_synthetic_witness(
    path: Path,
    *,
    initial: RollbackCheckpoint,
    principals: tuple[AnchorPrincipal, ...],
    administrator: AnchorPrincipal,
) -> WitnessHead:
    """Explicit test-only administrative provisioning, separate from runtime transport.

    Returns the exact head to provision separately in a fresh fake head backend.
    Existing/partial files are never overwritten. Python values are test authority,
    not proof of real human enrollment or secure credential possession.
    """
    if administrator.identity != initial.identity or AnchorRight.ENROLL not in administrator.rights:
        raise AnchorRejected("separate enrollment authority required")
    if any(p.identity != initial.identity for p in principals):
        raise ValueError("principal belongs to another lineage")
    state = WitnessState.decode(WitnessState(initial, 0, principals).encode())
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with _database(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(_SCHEMA)
        connection.execute("PRAGMA user_version=1")
        connection.execute("INSERT INTO witness VALUES (1, ?, NULL)", (state.encode(),))
        connection.commit()
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return state.head()


class SQLiteWitness:
    """No runtime provisioning/admin API; all state is explicitly synthetic.

    Trusted host code supplies authenticated peer identity out of band. Filesystem
    ownership, actual device durability and a real head backend remain unqualified.
    """

    def __init__(
        self,
        path: Path,
        *,
        identity: StoreIdentity,
        head: IndependentWitnessHead,
        fault_injector: Callable[[str], None] | None = None,
        wait_seconds: float = 1.0,
    ) -> None:
        if type(identity) is not StoreIdentity:
            raise ValueError("explicit exact enrolled identity required")
        self._wait = BoundedAnchorCalls(wait_seconds).timeout_seconds
        if not path.is_file() or path.is_symlink():
            raise AnchorUnavailable("enrolled database missing or symlinked")
        self._path = path
        self._identity = identity
        self._head = head
        self._fault_injector = fault_injector
        self._lock = threading.Lock()
        self._blocked = False
        self._closed = False
        self._owner_fd = os.open(str(path) + ".owner", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(self._owner_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise AnchorUnavailable(
                    "witness database already owned by another process"
                ) from exc
            with _database(path) as connection:
                self._load_current(connection)
        except BaseException:
            os.close(self._owner_fd)
            self._closed = True
            raise

    def close(self) -> None:
        with self._locked():
            if not self._closed:
                os.close(self._owner_fd)
                self._closed = True

    @contextmanager
    def _locked(self) -> Iterator[None]:
        if not self._lock.acquire(timeout=self._wait):
            raise AnchorUnavailable("witness busy; admission wait exceeded bound")
        try:
            yield
        finally:
            self._lock.release()

    def _fault(self, phase: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(phase)

    def _load_current(self, connection: sqlite3.Connection) -> WitnessState:
        schema = connection.execute("SELECT type, name, sql FROM sqlite_schema").fetchall()
        if schema != [("table", "witness", _SCHEMA)]:
            raise AnchorUnavailable("unexpected witness database schema")
        if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise AnchorUnavailable("unsupported witness database version")
        rows = connection.execute("SELECT slot, committed, staged FROM witness").fetchall()
        if len(rows) != 1 or rows[0][0] != 1:
            raise AnchorUnavailable("missing or ambiguous enrolled state")
        if rows[0][2] is not None:
            raise AnchorUnavailable("staged witness transition requires separate recovery")
        try:
            state = WitnessState.decode(rows[0][1])
        except (ValueError, TypeError, RecursionError) as exc:
            raise AnchorUnavailable("invalid witness state") from exc
        if state.checkpoint.identity != self._identity or self._head.read() != state.head():
            raise AnchorUnavailable("witness lineage/continuity mismatch")
        return state

    def exchange_for_peer(
        self, request: AnchorRequest, *, authenticated_peer: str
    ) -> AnchorResponse:
        """Typed loopback boundary; the request never supplies its own authenticated peer."""
        try:
            request = checked_request(request)
        except (ValueError, TypeError, AttributeError, RecursionError) as exc:
            raise AnchorRejected("malformed synthetic request") from exc
        if request.principal != authenticated_peer or request.identity != self._identity:
            raise AnchorRejected("authenticated peer or enrolled lineage mismatch")
        with self._locked():
            if self._closed or self._blocked:
                raise AnchorUnavailable("witness is closed or requires recovery")
            try:
                with _database(self._path) as connection:
                    state = self._load_current(connection)
                    principal = next(
                        (p for p in state.principals if p.name == authenticated_peer),
                        None,
                    )
                    if principal is None:
                        raise AnchorRejected("peer is not enrolled")
                    principal.require(request.action)
                    if request.action is AnchorAction.READ:
                        return self._response(request, AnchorOutcome.CURRENT, state)
                    return self._mutate(connection, request, state)
            except sqlite3.Error as exc:
                raise AnchorUnavailable("witness database unavailable") from exc

    @staticmethod
    def _response(
        request: AnchorRequest,
        outcome: AnchorOutcome,
        state: WitnessState,
    ) -> AnchorResponse:
        return AnchorResponse(request, outcome, state.checkpoint, state.head().evidence())

    def _mutate(
        self,
        connection: sqlite3.Connection,
        request: AnchorRequest,
        state: WitnessState,
    ) -> AnchorResponse:
        receipt = receipt_request(request)
        for old in state.receipts:
            if (old.principal, old.idempotency_key) == (
                request.principal,
                request.idempotency_key,
            ):
                outcome = AnchorOutcome.DUPLICATE if old == receipt else AnchorOutcome.REJECTED
                return self._response(request, outcome, state)
        if request.expected_current != state.checkpoint:
            return self._response(request, AnchorOutcome.REJECTED, state)
        candidate = state.checkpoint
        executions = state.executions
        if request.action is AnchorAction.ADVANCE:
            assert request.candidate is not None
            try:
                require_anchor_advancement(current=state.checkpoint, candidate=request.candidate)
            except RollbackContractError:
                return self._response(request, AnchorOutcome.REJECTED, state)
            candidate = request.candidate
        else:
            assert request.execution_id is not None
            if request.execution_id in executions:
                return self._response(request, AnchorOutcome.REJECTED, state)
            executions = executions | {request.execution_id}
        next_state = replace(
            state,
            checkpoint=candidate,
            sequence=state.sequence + 1,
            executions=frozenset(executions),
            receipts=state.receipts + (receipt,),
        )
        try:
            payload = next_state.encode()
        except ValueError as exc:
            raise AnchorRejected("synthetic witness capacity exhausted") from exc
        old_head, new_head = state.head(), next_state.head()
        # Once staging starts no failure can be exposed as definite non-commit.
        self._blocked = True
        try:
            self._fault("before_stage")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE witness SET staged=? WHERE slot=1", (payload,))
            connection.commit()
            self._fault("after_stage")
            self._head.compare_and_set(old_head, new_head)
            self._fault("after_head")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE witness SET committed=staged, staged=NULL WHERE slot=1")
            self._fault("before_finalize_commit")
            connection.commit()
            self._fault("after_finalize")
            if self._load_current(connection) != next_state:
                raise AnchorUnavailable("final committed state changed")
            self._blocked = False
        except Exception as exc:
            # Even a backend AnchorRejected after staging must not clear client pending evidence.
            raise AnchorUncertain(
                "witness transition interrupted; no execution permission"
            ) from exc
        return self._response(request, AnchorOutcome.COMMITTED, next_state)


@dataclass(frozen=True)
class SyntheticLoopbackTransport:
    """Test-only in-process authentication binding, never a production credential.

    No sockets, certificates, provider calls or HTTP body framing. Trusted fixture
    code supplies the peer name independently from each request. Production must
    replace this boundary with authenticated transport, not accept a caller name.
    """

    service: SQLiteWitness
    authenticated_peer: str

    def exchange(self, request: AnchorRequest) -> AnchorResponse:
        return self.service.exchange_for_peer(request, authenticated_peer=self.authenticated_peer)
