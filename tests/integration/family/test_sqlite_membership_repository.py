"""Integration tests for durable SQLite Membership temporal persistence."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID

import pytest

from familyos_cli.application.ports.family import (
    MembershipConflictError,
    MembershipRepository,
    MembershipTemporalFact,
)
from familyos_cli.domain.family import (
    Family,
    FamilyId,
    FamilyMembershipActivated,
    FamilyMembershipCreated,
    FamilyMembershipEnded,
    FamilyMembershipReactivated,
    FamilyMembershipSuspended,
    Membership,
    MembershipState,
)
from familyos_cli.domain.person import Person, PersonId
from familyos_cli.infrastructure.family.sqlite_family_repository import (
    SQLiteFamilyRepository,
)
from familyos_cli.infrastructure.family.sqlite_membership_repository import (
    SQLiteMembershipRepository,
)
from familyos_cli.infrastructure.persistence import (
    SQLiteDatabase,
    SQLitePersistenceError,
    SQLiteReconstructionError,
)
from familyos_cli.infrastructure.person.sqlite_person_repository import (
    SQLitePersonRepository,
)


def _database(tmp_path: Path) -> SQLiteDatabase:
    os.chmod(tmp_path, 0o700)
    return SQLiteDatabase(tmp_path / "core.sqlite3")


def _family() -> Family:
    return Family(
        family_id=FamilyId(UUID("01234567-89ab-4cde-8f01-23456789abcd"))
    )


def _person() -> Person:
    return Person(
        person_id=PersonId(UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))
    )


def _seed_prerequisites(database: SQLiteDatabase) -> tuple[Family, Person]:
    family = _family()
    person = _person()
    SQLiteFamilyRepository(database).save(family)
    SQLitePersonRepository(database).save(person)
    return family, person


def _repository(
    tmp_path: Path,
) -> tuple[SQLiteMembershipRepository, SQLiteDatabase, Family, Person]:
    database = _database(tmp_path)
    family, person = _seed_prerequisites(database)
    return SQLiteMembershipRepository(database), database, family, person


def _pending(family: Family, person: Person) -> Membership:
    return Membership.establish(family.family_id, person.person_id)


def _time(minute: int = 0) -> datetime:
    return datetime(2026, 8, 28, 10, minute, tzinfo=UTC)


def _created(
    membership: Membership,
    minute: int = 0,
) -> FamilyMembershipCreated:
    return FamilyMembershipCreated(
        membership.family_id,
        membership.person_id,
        _time(minute),
    )


def _activated(
    membership: Membership,
    minute: int = 1,
) -> FamilyMembershipActivated:
    return FamilyMembershipActivated(
        membership.family_id,
        membership.person_id,
        _time(minute),
    )


def _suspended(
    membership: Membership,
    minute: int = 2,
) -> FamilyMembershipSuspended:
    return FamilyMembershipSuspended(
        membership.family_id,
        membership.person_id,
        _time(minute),
    )


def _reactivated(
    membership: Membership,
    minute: int = 3,
) -> FamilyMembershipReactivated:
    return FamilyMembershipReactivated(
        membership.family_id,
        membership.person_id,
        _time(minute),
    )


def _ended(
    membership: Membership,
    minute: int = 4,
) -> FamilyMembershipEnded:
    return FamilyMembershipEnded(
        membership.family_id,
        membership.person_id,
        _time(minute),
    )


def _fact_rows(
    database: SQLiteDatabase,
    membership: Membership,
) -> list[tuple[int, str, str]]:
    with database.connection() as connection:
        rows = connection.execute(
            """
            SELECT sequence, fact_type, occurred_at
            FROM membership_facts
            WHERE family_id = ? AND person_id = ?
            ORDER BY sequence
            """,
            (str(membership.family_id), str(membership.person_id)),
        ).fetchall()
    return rows


def _persist_to_state(
    repository: SQLiteMembershipRepository,
    family: Family,
    person: Person,
    state: MembershipState,
) -> Membership:
    pending = _pending(family, person)
    repository.save(pending, _created(pending))

    if state is MembershipState.PENDING:
        return pending

    if state is MembershipState.ACTIVE:
        active = pending.activate()
        repository.save(active, _activated(active))
        return active

    if state is MembershipState.SUSPENDED:
        active = pending.activate()
        repository.save(active, _activated(active))
        suspended = active.suspend()
        repository.save(suspended, _suspended(suspended))
        return suspended

    ended = pending.end()
    repository.save(ended, _ended(ended))
    return ended


def test_repository_implements_canonical_port(tmp_path: Path) -> None:
    repository, _, _, _ = _repository(tmp_path)
    assert isinstance(repository, MembershipRepository)


def test_initial_save_get_and_reopen_round_trip_exact_identity_and_fact(
    tmp_path: Path,
) -> None:
    repository, database, family, person = _repository(tmp_path)
    membership = _pending(family, person)
    event = _created(membership)

    repository.save(membership, event)

    assert repository.get(membership.family_id, membership.person_id) == membership
    assert _fact_rows(database, membership) == [
        (1, "created", event.occurred_at.isoformat())
    ]

    reopened = SQLiteMembershipRepository(SQLiteDatabase(database.path))
    assert reopened.get(membership.family_id, membership.person_id) == membership


def test_absent_membership_returns_none(tmp_path: Path) -> None:
    repository, _, family, person = _repository(tmp_path)
    assert repository.get(family.family_id, person.person_id) is None


@pytest.mark.parametrize(
    "state",
    [MembershipState.ACTIVE, MembershipState.SUSPENDED, MembershipState.ENDED],
)
def test_initial_save_rejects_non_pending_state_atomically(
    tmp_path: Path,
    state: MembershipState,
) -> None:
    repository, database, family, person = _repository(tmp_path)
    membership = Membership(family.family_id, person.person_id, state)

    with pytest.raises(
        MembershipConflictError,
        match="Initial Membership persistence requires PENDING state",
    ):
        repository.save(membership, _created(membership))

    assert repository.get(family.family_id, person.person_id) is None
    assert _fact_rows(database, membership) == []


def test_initial_save_rejects_wrong_temporal_fact_type_atomically(
    tmp_path: Path,
) -> None:
    repository, database, family, person = _repository(tmp_path)
    membership = _pending(family, person)

    with pytest.raises(
        MembershipConflictError,
        match="requires creation temporal fact",
    ):
        repository.save(membership, _activated(membership))

    assert repository.get(family.family_id, person.person_id) is None
    assert _fact_rows(database, membership) == []


def test_temporal_fact_identity_mismatch_is_atomic_conflict(tmp_path: Path) -> None:
    repository, database, family, person = _repository(tmp_path)
    membership = _pending(family, person)
    wrong_family = FamilyId(UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"))
    wrong = FamilyMembershipCreated(
        wrong_family,
        membership.person_id,
        _time(),
    )

    with pytest.raises(MembershipConflictError, match="must match canonical"):
        repository.save(membership, wrong)

    assert repository.get(family.family_id, person.person_id) is None
    assert _fact_rows(database, membership) == []


def test_duplicate_pending_save_is_conflict_without_replacement(
    tmp_path: Path,
) -> None:
    repository, database, family, person = _repository(tmp_path)
    first = _pending(family, person)
    replacement = Membership.establish(first.family_id, first.person_id)

    repository.save(first, _created(first))

    with pytest.raises(MembershipConflictError):
        repository.save(replacement, _created(replacement, 1))

    assert repository.get(first.family_id, first.person_id) == first
    assert _fact_rows(database, first) == [
        (1, "created", _created(first).occurred_at.isoformat())
    ]


def test_full_lifecycle_reopen_preserves_state_and_ordered_facts(
    tmp_path: Path,
) -> None:
    repository, database, family, person = _repository(tmp_path)
    pending = _pending(family, person)
    active = pending.activate()
    suspended = active.suspend()
    reactivated = suspended.activate()
    ended = reactivated.end()
    base = datetime(2026, 8, 28, 11, 0, tzinfo=UTC)

    events: tuple[MembershipTemporalFact, ...] = (
        FamilyMembershipCreated(pending.family_id, pending.person_id, base),
        FamilyMembershipActivated(
            pending.family_id,
            pending.person_id,
            base + timedelta(minutes=1),
        ),
        FamilyMembershipSuspended(
            pending.family_id,
            pending.person_id,
            base + timedelta(minutes=2),
        ),
        FamilyMembershipReactivated(
            pending.family_id,
            pending.person_id,
            base + timedelta(minutes=3),
        ),
        FamilyMembershipEnded(
            pending.family_id,
            pending.person_id,
            base + timedelta(minutes=4),
        ),
    )

    for membership, event in zip(
        (pending, active, suspended, reactivated, ended),
        events,
        strict=True,
    ):
        repository.save(membership, event)

    reopened = SQLiteMembershipRepository(SQLiteDatabase(database.path))
    assert reopened.get(pending.family_id, pending.person_id) == ended
    assert _fact_rows(database, pending) == [
        (1, "created", events[0].occurred_at.isoformat()),
        (2, "activated", events[1].occurred_at.isoformat()),
        (3, "suspended", events[2].occurred_at.isoformat()),
        (4, "reactivated", events[3].occurred_at.isoformat()),
        (5, "ended", events[4].occurred_at.isoformat()),
    ]


def test_wrong_transition_fact_rolls_back_state_and_fact(tmp_path: Path) -> None:
    repository, database, family, person = _repository(tmp_path)
    pending = _pending(family, person)
    repository.save(pending, _created(pending))
    active = pending.activate()

    with pytest.raises(
        MembershipConflictError,
        match="temporal fact must match canonical lifecycle transition",
    ):
        repository.save(active, _suspended(active))

    assert repository.get(pending.family_id, pending.person_id) == pending
    assert _fact_rows(database, pending) == [
        (1, "created", _created(pending).occurred_at.isoformat())
    ]


@pytest.mark.parametrize(
    ("existing", "candidate"),
    [
        (MembershipState.PENDING, MembershipState.SUSPENDED),
        (MembershipState.ACTIVE, MembershipState.ACTIVE),
        (MembershipState.SUSPENDED, MembershipState.PENDING),
        (MembershipState.ENDED, MembershipState.ACTIVE),
    ],
)
def test_noncanonical_replacement_is_atomic_conflict(
    tmp_path: Path,
    existing: MembershipState,
    candidate: MembershipState,
) -> None:
    repository, database, family, person = _repository(tmp_path)
    current = _persist_to_state(repository, family, person, existing)
    before_facts = _fact_rows(database, current)
    replacement = Membership(current.family_id, current.person_id, candidate)

    with pytest.raises(MembershipConflictError):
        repository.save(replacement, _created(replacement, 20))

    assert repository.get(current.family_id, current.person_id) == current
    assert _fact_rows(database, current) == before_facts


def test_ended_membership_remains_present_and_key_reserved(tmp_path: Path) -> None:
    repository, database, family, person = _repository(tmp_path)
    pending = _pending(family, person)
    ended = pending.end()
    repository.save(pending, _created(pending))
    repository.save(ended, _ended(ended))
    replacement = Membership.establish(pending.family_id, pending.person_id)
    before_facts = _fact_rows(database, pending)

    with pytest.raises(MembershipConflictError):
        repository.save(replacement, _created(replacement, 5))

    assert repository.get(pending.family_id, pending.person_id) == ended
    assert _fact_rows(database, pending) == before_facts


def test_missing_parent_rows_remain_infrastructure_error(tmp_path: Path) -> None:
    database = _database(tmp_path)
    repository = SQLiteMembershipRepository(database)
    membership = Membership.establish(
        FamilyId(UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")),
        PersonId(UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")),
    )

    with pytest.raises(SQLitePersistenceError):
        repository.save(membership, _created(membership))

    assert repository.get(membership.family_id, membership.person_id) is None
    assert _fact_rows(database, membership) == []


@pytest.mark.parametrize(
    ("family_id", "person_id", "state"),
    [
        ("not-a-uuid", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "pending"),
        (
            "0123456789ab4cde8f0123456789abcd",
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "pending",
        ),
        (
            "01234567-89AB-4CDE-8F01-23456789ABCD",
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "pending",
        ),
        (
            "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "pending",
        ),
        ("01234567-89ab-4cde-8f01-23456789abcd", "not-a-uuid", "pending"),
        (
            "01234567-89ab-4cde-8f01-23456789abcd",
            "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
            "pending",
        ),
        (
            "01234567-89ab-4cde-8f01-23456789abcd",
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "invalid",
        ),
    ],
)
def test_tampered_identity_or_state_fails_reconstruction(
    family_id: object,
    person_id: object,
    state: object,
) -> None:
    with pytest.raises(SQLiteReconstructionError):
        SQLiteMembershipRepository._reconstruct_membership(
            family_id,
            person_id,
            state,
        )


def test_get_rejects_missing_temporal_history(tmp_path: Path) -> None:
    repository, database, family, person = _repository(tmp_path)
    pending = _pending(family, person)
    repository.save(pending, _created(pending))

    with (
        database.connection() as connection,
        database.write_transaction(connection),
    ):
        connection.execute(
            """
            DELETE FROM membership_facts
            WHERE family_id = ? AND person_id = ?
            """,
            (str(pending.family_id), str(pending.person_id)),
        )

    with pytest.raises(SQLiteReconstructionError, match="no temporal fact history"):
        repository.get(pending.family_id, pending.person_id)


def test_get_rejects_noncontiguous_temporal_history(tmp_path: Path) -> None:
    repository, database, family, person = _repository(tmp_path)
    pending = _pending(family, person)
    active = pending.activate()
    repository.save(pending, _created(pending))
    repository.save(active, _activated(active))

    with (
        database.connection() as connection,
        database.write_transaction(connection),
    ):
        connection.execute(
            """
            DELETE FROM membership_facts
            WHERE family_id = ? AND person_id = ? AND sequence = 1
            """,
            (str(pending.family_id), str(pending.person_id)),
        )

    with pytest.raises(SQLiteReconstructionError, match="sequence is invalid"):
        repository.get(pending.family_id, pending.person_id)


def test_get_rejects_state_history_mismatch(tmp_path: Path) -> None:
    repository, database, family, person = _repository(tmp_path)
    pending = _pending(family, person)
    repository.save(pending, _created(pending))

    with (
        database.connection() as connection,
        database.write_transaction(connection),
    ):
        connection.execute(
            """
            UPDATE memberships
            SET state = 'active'
            WHERE family_id = ? AND person_id = ?
            """,
            (str(pending.family_id), str(pending.person_id)),
        )

    with pytest.raises(SQLiteReconstructionError, match="does not match"):
        repository.get(pending.family_id, pending.person_id)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("not-a-datetime", "occurrence time is invalid"),
        ("2026-08-28T10:00:00", "not timezone-aware"),
        ("2026-08-28T10:00:00Z", "not canonical"),
    ],
)
def test_get_rejects_malformed_nonaware_or_noncanonical_occurrence_time(
    tmp_path: Path,
    raw: str,
    message: str,
) -> None:
    repository, database, family, person = _repository(tmp_path)
    pending = _pending(family, person)
    repository.save(pending, _created(pending))

    with (
        database.connection() as connection,
        database.write_transaction(connection),
    ):
        connection.execute(
            """
            UPDATE membership_facts
            SET occurred_at = ?
            WHERE family_id = ? AND person_id = ? AND sequence = 1
            """,
            (raw, str(pending.family_id), str(pending.person_id)),
        )

    with pytest.raises(SQLiteReconstructionError, match=message):
        repository.get(pending.family_id, pending.person_id)


def test_concurrent_initial_save_establishes_identity_and_fact_exactly_once(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    family, person = _seed_prerequisites(database)
    memberships = tuple(_pending(family, person) for _ in range(4))
    events = tuple(_created(item, index) for index, item in enumerate(memberships))
    barrier = Barrier(len(memberships))

    def attempt_save(
        item: tuple[Membership, FamilyMembershipCreated],
    ) -> bool:
        membership, event = item
        repository = SQLiteMembershipRepository(database)
        barrier.wait()
        try:
            repository.save(membership, event)
        except MembershipConflictError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=len(memberships)) as executor:
        outcomes = tuple(
            executor.map(
                attempt_save,
                zip(memberships, events, strict=True),
            )
        )

    assert outcomes.count(True) == 1
    assert outcomes.count(False) == len(memberships) - 1

    winner = outcomes.index(True)
    repository = SQLiteMembershipRepository(database)
    assert repository.get(family.family_id, person.person_id) == memberships[winner]
    assert _fact_rows(database, memberships[winner]) == [
        (1, "created", events[winner].occurred_at.isoformat())
    ]
