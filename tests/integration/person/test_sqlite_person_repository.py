"""Integration tests for durable SQLite Person persistence."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

from familyos_cli.application.ports.person import (
    PersonConflictError,
    PersonRepository,
)
from familyos_cli.domain.person import Person, PersonId
from familyos_cli.infrastructure.persistence import (
    SQLiteDatabase,
    SQLiteReconstructionError,
)
from familyos_cli.infrastructure.person.sqlite_person_repository import (
    SQLitePersonRepository,
)


def _repository(tmp_path: Path) -> SQLitePersonRepository:
    os.chmod(tmp_path, 0o700)
    return SQLitePersonRepository(SQLiteDatabase(tmp_path / "core.sqlite3"))


def _person() -> Person:
    return Person(
        person_id=PersonId(UUID("12345678-1234-4234-8234-123456789abc"))
    )


def test_repository_implements_canonical_port(tmp_path: Path) -> None:
    assert isinstance(_repository(tmp_path), PersonRepository)


def test_save_get_and_reopen_round_trip_exact_identity(tmp_path: Path) -> None:
    person = _person()
    path = tmp_path / "core.sqlite3"
    os.chmod(tmp_path, 0o700)

    first = SQLitePersonRepository(SQLiteDatabase(path))
    first.save(person)

    retrieved = first.get(person.person_id)
    assert retrieved == person
    assert str(retrieved.person_id) == str(person.person_id)

    reopened = SQLitePersonRepository(SQLiteDatabase(path))
    assert reopened.get(person.person_id) == person


def test_duplicate_person_is_conflict_without_replacement(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    first = _person()
    replacement = Person(person_id=first.person_id)

    repository.save(first)

    with pytest.raises(PersonConflictError, match="Person already exists"):
        repository.save(replacement)

    assert repository.get(first.person_id) == first


def test_absent_person_returns_none(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    absent = PersonId(UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))

    assert repository.get(absent) is None


@pytest.mark.parametrize(
    "raw",
    [
        "not-a-uuid",
        "12345678123442348234123456789abc",
        "12345678-1234-4234-8234-123456789ABC",
    ],
)
def test_tampered_or_noncanonical_stored_identity_fails_reconstruction(
    raw: str,
) -> None:
    with pytest.raises(SQLiteReconstructionError):
        SQLitePersonRepository._reconstruct_person(raw)


class _TamperedLookup:
    def __init__(self, raw: str) -> None:
        self._raw = raw

    def __str__(self) -> str:
        return self._raw


def test_tampered_stored_identity_fails_through_repository_get(
    tmp_path: Path,
) -> None:
    os.chmod(tmp_path, 0o700)
    database = SQLiteDatabase(tmp_path / "core.sqlite3")
    repository = SQLitePersonRepository(database)
    raw = "not-a-uuid"

    with (
        database.connection() as connection,
        database.write_transaction(connection),
    ):
        connection.execute(
            "INSERT INTO persons (person_id) VALUES (?)",
            (raw,),
        )

    lookup = cast(PersonId, _TamperedLookup(raw))
    with pytest.raises(SQLiteReconstructionError):
        repository.get(lookup)
