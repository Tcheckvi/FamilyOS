"""Integration tests for durable SQLite Relationship temporal persistence."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from typing import cast
from uuid import UUID

import pytest

from familyos_cli.application.ports.family import (
    RelationshipConflictError,
    RelationshipRepository,
)
from familyos_cli.domain.family import (
    FamilyId,
    FamilyRelationshipEnded,
    FamilyRelationshipEstablished,
    Relationship,
    RelationshipState,
    RelationshipType,
)
from familyos_cli.domain.person import PersonId
from familyos_cli.infrastructure.family.sqlite_relationship_repository import (
    SQLiteRelationshipRepository,
)
from familyos_cli.infrastructure.persistence import (
    SQLiteDatabase,
    SQLitePersistenceError,
    SQLiteReconstructionError,
)

FAMILY_UUID = UUID("12345678-1234-4234-8234-123456789abc")
OTHER_FAMILY_UUID = UUID("87654321-4321-4321-8321-cba987654321")
LOW_UUID = UUID("00000000-0000-4000-8000-000000000001")
HIGH_UUID = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
THIRD_UUID = UUID("11111111-1111-4111-8111-111111111111")
NOW = datetime(2026, 10, 6, 18, 0, tzinfo=UTC)


def _family_id() -> FamilyId:
    return FamilyId(FAMILY_UUID)


def _other_family_id() -> FamilyId:
    return FamilyId(OTHER_FAMILY_UUID)


def _low() -> PersonId:
    return PersonId(LOW_UUID)


def _high() -> PersonId:
    return PersonId(HIGH_UUID)


def _third() -> PersonId:
    return PersonId(THIRD_UUID)


def _database(tmp_path: Path) -> SQLiteDatabase:
    return SQLiteDatabase(tmp_path / "familyos.sqlite3")


def _repository(tmp_path: Path) -> SQLiteRelationshipRepository:
    return SQLiteRelationshipRepository(_database(tmp_path))


def _key(
    relationship: Relationship,
) -> tuple[FamilyId, PersonId, PersonId, RelationshipType]:
    return (
        relationship.family_id,
        relationship.source_person_id,
        relationship.target_person_id,
        relationship.relationship_type,
    )


def _established(
    relationship: Relationship,
    *,
    occurred_at: datetime = NOW,
) -> FamilyRelationshipEstablished:
    return FamilyRelationshipEstablished(
        family_id=relationship.family_id,
        source_person_id=relationship.source_person_id,
        target_person_id=relationship.target_person_id,
        relationship_type=relationship.relationship_type,
        occurred_at=occurred_at,
    )


def _ended(
    relationship: Relationship,
    *,
    occurred_at: datetime = NOW + timedelta(minutes=1),
) -> FamilyRelationshipEnded:
    return FamilyRelationshipEnded(
        family_id=relationship.family_id,
        source_person_id=relationship.source_person_id,
        target_person_id=relationship.target_person_id,
        relationship_type=relationship.relationship_type,
        occurred_at=occurred_at,
    )


def _parent_relationship(
    *,
    family_id: FamilyId | None = None,
) -> Relationship:
    return Relationship.establish(
        family_id or _family_id(),
        _low(),
        _high(),
        RelationshipType.PARENT_OF,
    )


def _seed_identity(
    database: SQLiteDatabase,
    family_id: FamilyId,
    *person_ids: PersonId,
) -> None:
    with (
        database.connection() as connection,
        database.write_transaction(connection),
    ):
        connection.execute(
            "INSERT OR IGNORE INTO families (family_id) VALUES (?)",
            (str(family_id),),
        )
        for person_id in person_ids:
            connection.execute(
                "INSERT OR IGNORE INTO persons (person_id) VALUES (?)",
                (str(person_id),),
            )


def _seed_default_identity(database: SQLiteDatabase) -> None:
    _seed_identity(database, _family_id(), _low(), _high(), _third())


def _raw_connection(database: SQLiteDatabase) -> sqlite3.Connection:
    with database.connection():
        pass
    connection = sqlite3.connect(database.path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("PRAGMA ignore_check_constraints = ON")
    return connection


def _insert_raw_relationship(
    database: SQLiteDatabase,
    *,
    family_id: str = str(FAMILY_UUID),
    source_person_id: str = str(LOW_UUID),
    target_person_id: str = str(HIGH_UUID),
    relationship_type: str = "parent_of",
    state: str = "established",
) -> None:
    connection = _raw_connection(database)
    try:
        connection.execute(
            """
            INSERT INTO relationships (
                family_id,
                source_person_id,
                target_person_id,
                relationship_type,
                state
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                family_id,
                source_person_id,
                target_person_id,
                relationship_type,
                state,
            ),
        )
    finally:
        connection.close()


def _insert_raw_fact(
    database: SQLiteDatabase,
    *,
    family_id: str = str(FAMILY_UUID),
    source_person_id: str = str(LOW_UUID),
    target_person_id: str = str(HIGH_UUID),
    relationship_type: str = "parent_of",
    sequence: int = 1,
    fact_type: str = "established",
    occurred_at: str = NOW.isoformat(),
) -> None:
    connection = _raw_connection(database)
    try:
        connection.execute(
            """
            INSERT INTO relationship_facts (
                family_id,
                source_person_id,
                target_person_id,
                relationship_type,
                sequence,
                fact_type,
                occurred_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                family_id,
                source_person_id,
                target_person_id,
                relationship_type,
                sequence,
                fact_type,
                occurred_at,
            ),
        )
    finally:
        connection.close()


def test_repository_implements_canonical_port(tmp_path: Path) -> None:
    assert isinstance(_repository(tmp_path), RelationshipRepository)


def test_initial_save_get_reopen_and_exact_fact_persistence(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_default_identity(database)
    relationship = _parent_relationship()
    event = _established(
        relationship,
        occurred_at=datetime(
            2026,
            10,
            6,
            20,
            15,
            tzinfo=timezone(timedelta(hours=2)),
        ),
    )

    SQLiteRelationshipRepository(database).save(relationship, event)

    reopened = SQLiteRelationshipRepository(database)
    assert reopened.get(*_key(relationship)) == relationship

    with database.connection() as connection:
        relationship_row = connection.execute(
            """
            SELECT family_id, source_person_id, target_person_id,
                   relationship_type, state
            FROM relationships
            """
        ).fetchone()
        fact_row = connection.execute(
            """
            SELECT sequence, fact_type, occurred_at
            FROM relationship_facts
            """
        ).fetchone()

    assert relationship_row == (
        str(relationship.family_id),
        str(relationship.source_person_id),
        str(relationship.target_person_id),
        "parent_of",
        "established",
    )
    assert fact_row == (1, "established", event.occurred_at.isoformat())


def test_get_returns_none_for_absent_canonical_key(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_default_identity(database)
    repository = SQLiteRelationshipRepository(database)

    assert repository.get(
        _family_id(),
        _low(),
        _high(),
        RelationshipType.PARENT_OF,
    ) is None


@pytest.mark.parametrize(
    "relationship_type",
    [RelationshipType.SPOUSE_OF, RelationshipType.SIBLING_OF],
)
def test_symmetric_relationships_persist_canonical_uuid_order(
    tmp_path: Path,
    relationship_type: RelationshipType,
) -> None:
    database = _database(tmp_path)
    _seed_default_identity(database)
    relationship = Relationship.establish(
        _family_id(),
        _high(),
        _low(),
        relationship_type,
    )
    repository = SQLiteRelationshipRepository(database)

    repository.save(relationship, _established(relationship))

    assert relationship.source_person_id == _low()
    assert relationship.target_person_id == _high()
    assert repository.get(
        _family_id(),
        _low(),
        _high(),
        relationship_type,
    ) == relationship


def test_initial_save_rejects_ended_state_atomically(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_default_identity(database)
    ended = _parent_relationship().end()
    repository = SQLiteRelationshipRepository(database)

    with pytest.raises(RelationshipConflictError):
        repository.save(ended, _established(ended))

    assert repository.get(*_key(ended)) is None
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM relationship_facts").fetchone() == (0,)


def test_initial_save_rejects_wrong_fact_atomically(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_default_identity(database)
    relationship = _parent_relationship()
    repository = SQLiteRelationshipRepository(database)

    with pytest.raises(RelationshipConflictError):
        repository.save(relationship, _ended(relationship))

    assert repository.get(*_key(relationship)) is None


def test_temporal_fact_identity_mismatch_is_atomic_conflict(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_default_identity(database)
    relationship = _parent_relationship()
    wrong = FamilyRelationshipEstablished(
        family_id=relationship.family_id,
        source_person_id=relationship.target_person_id,
        target_person_id=relationship.source_person_id,
        relationship_type=relationship.relationship_type,
        occurred_at=NOW,
    )
    repository = SQLiteRelationshipRepository(database)

    with pytest.raises(RelationshipConflictError, match="must match canonical"):
        repository.save(relationship, wrong)

    assert repository.get(*_key(relationship)) is None


def test_duplicate_canonical_key_is_conflict_and_preserves_first_fact(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_default_identity(database)
    first = _parent_relationship()
    duplicate = _parent_relationship()
    repository = SQLiteRelationshipRepository(database)

    repository.save(first, _established(first))
    with pytest.raises(RelationshipConflictError):
        repository.save(
            duplicate,
            _established(duplicate, occurred_at=NOW + timedelta(minutes=1)),
        )

    assert repository.get(*_key(first)) == first
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM relationship_facts").fetchone() == (1,)


def test_child_of_and_parent_of_collide_after_domain_normalization(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_default_identity(database)
    parent_view = Relationship.establish(
        _family_id(),
        _low(),
        _high(),
        RelationshipType.PARENT_OF,
    )
    child_view = Relationship.establish(
        _family_id(),
        _high(),
        _low(),
        RelationshipType.CHILD_OF,
    )
    repository = SQLiteRelationshipRepository(database)

    assert child_view == parent_view
    repository.save(parent_view, _established(parent_view))

    with pytest.raises(RelationshipConflictError):
        repository.save(
            child_view,
            _established(child_view, occurred_at=NOW + timedelta(minutes=1)),
        )


@pytest.mark.parametrize(
    "relationship_type",
    [RelationshipType.SPOUSE_OF, RelationshipType.SIBLING_OF],
)
def test_reversed_symmetric_views_collide_after_domain_normalization(
    tmp_path: Path,
    relationship_type: RelationshipType,
) -> None:
    database = _database(tmp_path)
    _seed_default_identity(database)
    forward = Relationship.establish(
        _family_id(),
        _low(),
        _high(),
        relationship_type,
    )
    reversed_view = Relationship.establish(
        _family_id(),
        _high(),
        _low(),
        relationship_type,
    )
    repository = SQLiteRelationshipRepository(database)

    assert forward == reversed_view
    repository.save(forward, _established(forward))

    with pytest.raises(RelationshipConflictError):
        repository.save(
            reversed_view,
            _established(reversed_view, occurred_at=NOW + timedelta(minutes=1)),
        )


def test_same_relationship_identity_in_other_family_is_distinct(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_identity(database, _family_id(), _low(), _high())
    _seed_identity(database, _other_family_id(), _low(), _high())
    first = _parent_relationship()
    second = _parent_relationship(family_id=_other_family_id())
    repository = SQLiteRelationshipRepository(database)

    repository.save(first, _established(first))
    repository.save(second, _established(second, occurred_at=NOW + timedelta(minutes=1)))

    assert repository.get(*_key(first)) == first
    assert repository.get(*_key(second)) == second


def test_established_to_ended_persists_two_fact_history(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_default_identity(database)
    established = Relationship.establish(
        _family_id(),
        _high(),
        _low(),
        RelationshipType.SPOUSE_OF,
    )
    ended = established.end()
    repository = SQLiteRelationshipRepository(database)

    established_event = _established(established)
    ended_event = _ended(ended)
    repository.save(established, established_event)
    repository.save(ended, ended_event)

    assert repository.get(*_key(established)) == ended
    with database.connection() as connection:
        facts = connection.execute(
            """
            SELECT sequence, fact_type, occurred_at
            FROM relationship_facts
            ORDER BY sequence
            """
        ).fetchall()
    assert facts == [
        (1, "established", established_event.occurred_at.isoformat()),
        (2, "ended", ended_event.occurred_at.isoformat()),
    ]


def test_wrong_transition_fact_rolls_back_state_update(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_default_identity(database)
    established = _parent_relationship()
    ended = established.end()
    repository = SQLiteRelationshipRepository(database)

    repository.save(established, _established(established))
    with pytest.raises(RelationshipConflictError):
        repository.save(
            ended,
            _established(ended, occurred_at=NOW + timedelta(minutes=1)),
        )

    assert repository.get(*_key(established)) == established
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM relationship_facts").fetchone() == (1,)


@pytest.mark.parametrize(
    "candidate_state",
    [RelationshipState.ESTABLISHED, RelationshipState.ENDED],
)
def test_noncanonical_replacement_after_end_is_rejected(
    tmp_path: Path,
    candidate_state: RelationshipState,
) -> None:
    database = _database(tmp_path)
    _seed_default_identity(database)
    established = _parent_relationship()
    ended = established.end()
    repository = SQLiteRelationshipRepository(database)

    repository.save(established, _established(established))
    repository.save(ended, _ended(ended))

    candidate = Relationship(
        family_id=ended.family_id,
        source_person_id=ended.source_person_id,
        target_person_id=ended.target_person_id,
        relationship_type=ended.relationship_type,
        state=candidate_state,
    )
    fact = (
        _established(candidate, occurred_at=NOW + timedelta(minutes=2))
        if candidate_state is RelationshipState.ESTABLISHED
        else _ended(candidate, occurred_at=NOW + timedelta(minutes=2))
    )

    with pytest.raises(RelationshipConflictError):
        repository.save(candidate, fact)

    assert repository.get(*_key(ended)) == ended


def test_ended_key_remains_reserved_across_reopen(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_default_identity(database)
    established = _parent_relationship()
    ended = established.end()

    first = SQLiteRelationshipRepository(database)
    first.save(established, _established(established))
    first.save(ended, _ended(ended))

    reopened = SQLiteRelationshipRepository(database)
    replacement = _parent_relationship()
    with pytest.raises(RelationshipConflictError):
        reopened.save(
            replacement,
            _established(replacement, occurred_at=NOW + timedelta(minutes=2)),
        )

    assert reopened.get(*_key(ended)) == ended


def test_get_does_not_normalize_child_of_view(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_default_identity(database)
    relationship = _parent_relationship()
    repository = SQLiteRelationshipRepository(database)
    repository.save(relationship, _established(relationship))

    assert repository.get(
        _family_id(),
        _high(),
        _low(),
        RelationshipType.CHILD_OF,
    ) is None
    assert repository.get(*_key(relationship)) == relationship


@pytest.mark.parametrize(
    "relationship_type",
    [RelationshipType.SPOUSE_OF, RelationshipType.SIBLING_OF],
)
def test_get_does_not_normalize_reversed_symmetric_view(
    tmp_path: Path,
    relationship_type: RelationshipType,
) -> None:
    database = _database(tmp_path)
    _seed_default_identity(database)
    relationship = Relationship.establish(
        _family_id(),
        _low(),
        _high(),
        relationship_type,
    )
    repository = SQLiteRelationshipRepository(database)
    repository.save(relationship, _established(relationship))

    assert repository.get(
        _family_id(),
        _high(),
        _low(),
        relationship_type,
    ) is None
    assert repository.get(*_key(relationship)) == relationship


@pytest.mark.parametrize(
    "missing_parent",
    ["family", "source", "target"],
)
def test_missing_parent_foreign_key_remains_infrastructure_failure(
    tmp_path: Path,
    missing_parent: str,
) -> None:
    database = _database(tmp_path)
    with (
        database.connection() as connection,
        database.write_transaction(connection),
    ):
        if missing_parent != "family":
            connection.execute(
                "INSERT INTO families (family_id) VALUES (?)",
                (str(_family_id()),),
            )
        if missing_parent != "source":
            connection.execute(
                "INSERT INTO persons (person_id) VALUES (?)",
                (str(_low()),),
            )
        if missing_parent != "target":
            connection.execute(
                "INSERT INTO persons (person_id) VALUES (?)",
                (str(_high()),),
            )

    relationship = _parent_relationship()
    repository = SQLiteRelationshipRepository(database)

    with pytest.raises(SQLitePersistenceError):
        repository.save(relationship, _established(relationship))

    assert repository.get(*_key(relationship)) is None


@pytest.mark.parametrize(
    ("raw_family_id", "message"),
    [
        ("not-a-uuid", "FamilyId is invalid"),
        ("12345678-1234-1234-8234-123456789abc", "FamilyId is not canonical"),
        (str(FAMILY_UUID).upper(), "FamilyId is not canonical"),
    ],
)
def test_family_id_reconstruction_is_fail_closed(
    raw_family_id: str,
    message: str,
) -> None:
    with pytest.raises(SQLiteReconstructionError, match=message):
        SQLiteRelationshipRepository._reconstruct_relationship(
            raw_family_id,
            str(LOW_UUID),
            str(HIGH_UUID),
            "parent_of",
            "established",
        )


@pytest.mark.parametrize(
    ("role", "raw_person_id"),
    [
        ("source", "not-a-uuid"),
        ("source", "ABCDEFAB-CDEF-4ABC-8DEF-ABCDEFABCDEF"),
        ("target", "not-a-uuid"),
        ("target", str(HIGH_UUID).upper()),
    ],
)
def test_person_id_reconstruction_is_fail_closed(
    role: str,
    raw_person_id: str,
) -> None:
    source = raw_person_id if role == "source" else str(LOW_UUID)
    target = raw_person_id if role == "target" else str(HIGH_UUID)

    with pytest.raises(SQLiteReconstructionError):
        SQLiteRelationshipRepository._reconstruct_relationship(
            str(FAMILY_UUID),
            source,
            target,
            "parent_of",
            "established",
        )


def test_invalid_relationship_type_reconstruction_is_fail_closed() -> None:
    with pytest.raises(SQLiteReconstructionError, match="type is invalid"):
        SQLiteRelationshipRepository._reconstruct_relationship(
            str(FAMILY_UUID),
            str(LOW_UUID),
            str(HIGH_UUID),
            "guardian_of",
            "established",
        )


def test_persisted_child_of_reconstruction_is_fail_closed() -> None:
    with pytest.raises(SQLiteReconstructionError, match="canonical domain state"):
        SQLiteRelationshipRepository._reconstruct_relationship(
            str(FAMILY_UUID),
            str(HIGH_UUID),
            str(LOW_UUID),
            "child_of",
            "established",
        )


def test_invalid_relationship_state_reconstruction_is_fail_closed() -> None:
    with pytest.raises(SQLiteReconstructionError, match="state is invalid"):
        SQLiteRelationshipRepository._reconstruct_relationship(
            str(FAMILY_UUID),
            str(LOW_UUID),
            str(HIGH_UUID),
            "parent_of",
            "pending",
        )


def test_noncanonical_symmetric_order_reconstruction_is_fail_closed() -> None:
    with pytest.raises(SQLiteReconstructionError, match="canonical domain state"):
        SQLiteRelationshipRepository._reconstruct_relationship(
            str(FAMILY_UUID),
            str(HIGH_UUID),
            str(LOW_UUID),
            "spouse_of",
            "established",
        )


def test_missing_history_is_reconstruction_error(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert_raw_relationship(database)
    repository = SQLiteRelationshipRepository(database)

    with pytest.raises(SQLiteReconstructionError, match="no temporal fact history"):
        repository.get(
            _family_id(),
            _low(),
            _high(),
            RelationshipType.PARENT_OF,
        )


def test_orphan_history_is_reconstruction_error(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert_raw_fact(database)
    repository = SQLiteRelationshipRepository(database)

    with pytest.raises(SQLiteReconstructionError, match="facts exist without continuity"):
        repository.get(
            _family_id(),
            _low(),
            _high(),
            RelationshipType.PARENT_OF,
        )


def test_sequence_gap_is_reconstruction_error(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert_raw_relationship(database)
    _insert_raw_fact(database, sequence=2)
    repository = SQLiteRelationshipRepository(database)

    with pytest.raises(SQLiteReconstructionError, match="sequence is invalid"):
        repository.get(
            _family_id(),
            _low(),
            _high(),
            RelationshipType.PARENT_OF,
        )


def test_noncanonical_fact_history_is_reconstruction_error(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert_raw_relationship(database)
    _insert_raw_fact(database, sequence=1, fact_type="established")
    _insert_raw_fact(
        database,
        sequence=2,
        fact_type="established",
        occurred_at=(NOW + timedelta(minutes=1)).isoformat(),
    )
    repository = SQLiteRelationshipRepository(database)

    with pytest.raises(SQLiteReconstructionError, match="history is non-canonical"):
        repository.get(
            _family_id(),
            _low(),
            _high(),
            RelationshipType.PARENT_OF,
        )


def test_state_history_mismatch_is_reconstruction_error(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert_raw_relationship(database, state="ended")
    _insert_raw_fact(database, fact_type="established")
    repository = SQLiteRelationshipRepository(database)

    with pytest.raises(SQLiteReconstructionError, match="does not match"):
        repository.get(
            _family_id(),
            _low(),
            _high(),
            RelationshipType.PARENT_OF,
        )


@pytest.mark.parametrize(
    "raw_occurred_at",
    [
        "not-a-datetime",
        "2026-10-06T18:00:00",
        "2026-10-06T18:00:00Z",
    ],
)
def test_invalid_or_noncanonical_timestamp_is_reconstruction_error(
    tmp_path: Path,
    raw_occurred_at: str,
) -> None:
    database = _database(tmp_path)
    _insert_raw_relationship(database)
    _insert_raw_fact(database, occurred_at=raw_occurred_at)
    repository = SQLiteRelationshipRepository(database)

    with pytest.raises(SQLiteReconstructionError):
        repository.get(
            _family_id(),
            _low(),
            _high(),
            RelationshipType.PARENT_OF,
        )


def test_persisted_reversed_symmetric_row_is_reconstruction_error(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert_raw_relationship(
        database,
        source_person_id=str(HIGH_UUID),
        target_person_id=str(LOW_UUID),
        relationship_type="sibling_of",
    )
    _insert_raw_fact(
        database,
        source_person_id=str(HIGH_UUID),
        target_person_id=str(LOW_UUID),
        relationship_type="sibling_of",
    )
    repository = SQLiteRelationshipRepository(database)

    with pytest.raises(SQLiteReconstructionError, match="canonical domain state"):
        repository.get(
            _family_id(),
            _high(),
            _low(),
            RelationshipType.SIBLING_OF,
        )


def test_persisted_child_of_row_is_reconstruction_error(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert_raw_relationship(
        database,
        source_person_id=str(HIGH_UUID),
        target_person_id=str(LOW_UUID),
        relationship_type="child_of",
    )
    _insert_raw_fact(
        database,
        source_person_id=str(HIGH_UUID),
        target_person_id=str(LOW_UUID),
        relationship_type="child_of",
    )
    repository = SQLiteRelationshipRepository(database)

    with pytest.raises(SQLiteReconstructionError, match="canonical domain state"):
        repository.get(
            _family_id(),
            _high(),
            _low(),
            RelationshipType.CHILD_OF,
        )


def test_invalid_state_row_is_reconstruction_error(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert_raw_relationship(database, state="pending")
    _insert_raw_fact(database)
    repository = SQLiteRelationshipRepository(database)

    with pytest.raises(SQLiteReconstructionError, match="state is invalid"):
        repository.get(
            _family_id(),
            _low(),
            _high(),
            RelationshipType.PARENT_OF,
        )


def test_corrupt_history_is_rejected_before_transition_write(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert_raw_relationship(database, state="established")
    _insert_raw_fact(database, sequence=2)
    candidate = _parent_relationship().end()
    repository = SQLiteRelationshipRepository(database)

    with pytest.raises(SQLiteReconstructionError, match="sequence is invalid"):
        repository.save(candidate, _ended(candidate))

    connection = _raw_connection(database)
    try:
        state = connection.execute("SELECT state FROM relationships").fetchone()
        fact_count = connection.execute(
            "SELECT COUNT(*) FROM relationship_facts"
        ).fetchone()
    finally:
        connection.close()
    assert state == ("established",)
    assert fact_count == (1,)


def test_concurrent_initial_save_establishes_exactly_one_continuity_and_fact(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    _seed_default_identity(database)
    relationships = tuple(
        Relationship.establish(
            _family_id(),
            _low(),
            _high(),
            RelationshipType.SIBLING_OF,
        )
        for _ in range(8)
    )
    events = tuple(
        _established(
            relationship,
            occurred_at=NOW + timedelta(minutes=index),
        )
        for index, relationship in enumerate(relationships)
    )
    barrier = Barrier(len(relationships))

    def attempt_save(
        item: tuple[Relationship, FamilyRelationshipEstablished],
    ) -> bool:
        relationship, event = item
        barrier.wait()
        try:
            SQLiteRelationshipRepository(database).save(relationship, event)
        except RelationshipConflictError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=len(relationships)) as executor:
        outcomes = tuple(
            executor.map(
                attempt_save,
                zip(relationships, events, strict=True),
            )
        )

    assert outcomes.count(True) == 1
    assert outcomes.count(False) == len(relationships) - 1

    repository = SQLiteRelationshipRepository(database)
    assert repository.get(*_key(relationships[0])) == relationships[0]
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM relationships").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM relationship_facts").fetchone() == (1,)


def test_fact_identity_type_check_is_strict(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_default_identity(database)
    relationship = _parent_relationship()
    invalid_fact = cast(
        FamilyRelationshipEstablished,
        FamilyRelationshipEnded(
            family_id=relationship.family_id,
            source_person_id=relationship.source_person_id,
            target_person_id=relationship.target_person_id,
            relationship_type=relationship.relationship_type,
            occurred_at=NOW,
        ),
    )

    with pytest.raises(RelationshipConflictError):
        SQLiteRelationshipRepository(database).save(relationship, invalid_fact)
