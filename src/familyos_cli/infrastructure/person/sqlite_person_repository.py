"""SQLite adapter for the canonical Person repository port."""

from __future__ import annotations

import sqlite3
from uuid import UUID

from familyos_cli.application.ports.person import (
    PersonConflictError,
    PersonRepository,
)
from familyos_cli.domain.person import Person, PersonId
from familyos_cli.infrastructure.persistence.sqlite_database import (
    SQLiteDatabase,
    is_uniqueness_violation,
    translate_sqlite_error,
)
from familyos_cli.infrastructure.persistence.sqlite_errors import (
    SQLiteReconstructionError,
)


class SQLitePersonRepository(PersonRepository):
    """Durably persist canonical Persons by PersonId in the bounded Wave A store."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def save(self, person: Person) -> None:
        """Atomically establish a new Person without replacing canonical identity."""
        person_id = str(person.person_id)

        with (
            self._database.connection() as connection,
            self._database.write_transaction(connection),
        ):
            try:
                connection.execute(
                    "INSERT INTO persons (person_id) VALUES (?)",
                    (person_id,),
                )
            except sqlite3.IntegrityError as error:
                if is_uniqueness_violation(error):
                    raise PersonConflictError("Person already exists") from error
                raise translate_sqlite_error(error) from error
            except sqlite3.Error as error:
                raise translate_sqlite_error(error) from error

    def get(self, person_id: PersonId) -> Person | None:
        """Return one canonical Person, or ordinary absence."""
        with self._database.connection() as connection:
            try:
                row = connection.execute(
                    "SELECT person_id FROM persons WHERE person_id = ?",
                    (str(person_id),),
                ).fetchone()
            except sqlite3.Error as error:
                raise translate_sqlite_error(error) from error

        if row is None:
            return None

        return self._reconstruct_person(row[0])

    @staticmethod
    def _reconstruct_person(raw_person_id: object) -> Person:
        if not isinstance(raw_person_id, str):
            raise SQLiteReconstructionError("Stored Person identity is invalid")

        try:
            parsed = UUID(raw_person_id)
        except (ValueError, AttributeError) as error:
            raise SQLiteReconstructionError("Stored Person identity is invalid") from error

        if raw_person_id != str(parsed):
            raise SQLiteReconstructionError("Stored Person identity is not canonical")

        try:
            return Person(person_id=PersonId(parsed))
        except (TypeError, ValueError) as error:
            raise SQLiteReconstructionError(
                "Stored Person cannot reconstruct canonical domain state"
            ) from error
