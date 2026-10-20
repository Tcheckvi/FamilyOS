"""Integration tests for durable SQLite Family persistence."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier
from typing import cast
from uuid import UUID

import pytest

from familyos_cli.application.ports.family import (
    FamilyConflictError,
    FamilyRepository,
)
from familyos_cli.domain.family import Family, FamilyId
from familyos_cli.infrastructure.family.sqlite_family_repository import (
    SQLiteFamilyRepository,
)
from familyos_cli.infrastructure.persistence import (
    SQLiteDatabase,
    SQLitePersistenceError,
    SQLiteReconstructionError,
)


def _database(tmp_path: Path) -> SQLiteDatabase:
    os.chmod(tmp_path, 0o700)
    return SQLiteDatabase(tmp_path / "core.sqlite3")


def _repository(tmp_path: Path) -> SQLiteFamilyRepository:
    return SQLiteFamilyRepository(_database(tmp_path))


def _family() -> Family:
    return Family(
        family_id=FamilyId(UUID("01234567-89ab-4cde-8f01-23456789abcd"))
    )


def test_repository_implements_canonical_port(tmp_path: Path) -> None:
    assert isinstance(_repository(tmp_path), FamilyRepository)


def test_save_get_and_reopen_round_trip_exact_identity(tmp_path: Path) -> None:
    family = _family()
    database = _database(tmp_path)

    first = SQLiteFamilyRepository(database)
    first.save(family)

    retrieved = first.get(family.family_id)
    assert retrieved == family
    assert str(retrieved.family_id) == str(family.family_id)

    reopened = SQLiteFamilyRepository(SQLiteDatabase(database.path))
    assert reopened.get(family.family_id) == family


def test_duplicate_family_is_conflict_without_replacement(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    first = _family()
    replacement = Family(family_id=first.family_id)

    repository.save(first)

    with pytest.raises(FamilyConflictError, match="Family already exists"):
        repository.save(replacement)

    assert repository.get(first.family_id) == first


def test_absent_family_returns_none(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    absent = FamilyId(UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))

    assert repository.get(absent) is None


class _TamperedLookup:
    def __init__(self, raw: str) -> None:
        self._raw = raw

    def __str__(self) -> str:
        return self._raw


@pytest.mark.parametrize(
    "raw",
    [
        "not-a-uuid",
        "0123456789ab4cde8f0123456789abcd",
        "01234567-89AB-4CDE-8F01-23456789ABCD",
        "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
    ],
)
def test_tampered_stored_identity_fails_through_repository_get(
    tmp_path: Path,
    raw: str,
) -> None:
    database = _database(tmp_path)
    repository = SQLiteFamilyRepository(database)

    with (
        database.connection() as connection,
        database.write_transaction(connection),
    ):
        connection.execute(
            "INSERT INTO families (family_id) VALUES (?)",
            (raw,),
        )

    lookup = cast(FamilyId, _TamperedLookup(raw))
    with pytest.raises(SQLiteReconstructionError):
        repository.get(lookup)


class _SQLiteConstraintDouble(sqlite3.IntegrityError):
    sqlite_errorcode = sqlite3.SQLITE_CONSTRAINT_CHECK
    sqlite_errorname = "SQLITE_CONSTRAINT_CHECK"


class _FailingConnection:
    def execute(self, sql: str, parameters: tuple[str, ...] = ()) -> None:
        del sql, parameters
        raise _SQLiteConstraintDouble("CHECK constraint failed")


class _FailingDatabase:
    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        yield cast(sqlite3.Connection, _FailingConnection())

    @contextmanager
    def write_transaction(self, connection: sqlite3.Connection) -> Iterator[None]:
        del connection
        yield


def test_non_uniqueness_integrity_failure_remains_infrastructure_error() -> None:
    repository = SQLiteFamilyRepository(cast(SQLiteDatabase, _FailingDatabase()))

    with pytest.raises(SQLitePersistenceError):
        repository.save(_family())


def test_concurrent_initial_save_establishes_identity_exactly_once(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    family_id = FamilyId(UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"))
    families = tuple(Family(family_id=family_id) for _ in range(4))
    barrier = Barrier(len(families))

    def attempt_save(family: Family) -> bool:
        repository = SQLiteFamilyRepository(database)
        barrier.wait()
        try:
            repository.save(family)
        except FamilyConflictError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=len(families)) as executor:
        outcomes = tuple(executor.map(attempt_save, families))

    assert outcomes.count(True) == 1
    assert outcomes.count(False) == len(families) - 1

    repository = SQLiteFamilyRepository(database)
    assert repository.get(family_id) == families[outcomes.index(True)]
