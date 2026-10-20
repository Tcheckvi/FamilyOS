"""SQLite adapter for the canonical Family repository port."""

from __future__ import annotations

import sqlite3
from uuid import UUID

from familyos_cli.application.ports.family import (
    FamilyConflictError,
    FamilyRepository,
)
from familyos_cli.domain.family import Family, FamilyId
from familyos_cli.infrastructure.persistence.sqlite_database import (
    SQLiteDatabase,
    is_uniqueness_violation,
    translate_sqlite_error,
)
from familyos_cli.infrastructure.persistence.sqlite_errors import (
    SQLiteReconstructionError,
)


class SQLiteFamilyRepository(FamilyRepository):
    """Durably persist canonical Families by FamilyId in the bounded Wave A store."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def save(self, family: Family) -> None:
        """Atomically establish a new Family without replacing canonical identity."""
        family_id = str(family.family_id)

        with (
            self._database.connection() as connection,
            self._database.write_transaction(connection),
        ):
            try:
                connection.execute(
                    "INSERT INTO families (family_id) VALUES (?)",
                    (family_id,),
                )
            except sqlite3.IntegrityError as error:
                if is_uniqueness_violation(error):
                    raise FamilyConflictError("Family already exists") from error
                raise translate_sqlite_error(error) from error
            except sqlite3.Error as error:
                raise translate_sqlite_error(error) from error

    def get(self, family_id: FamilyId) -> Family | None:
        """Return one canonical Family, or ordinary absence."""
        with self._database.connection() as connection:
            try:
                row = connection.execute(
                    "SELECT family_id FROM families WHERE family_id = ?",
                    (str(family_id),),
                ).fetchone()
            except sqlite3.Error as error:
                raise translate_sqlite_error(error) from error

        if row is None:
            return None

        return self._reconstruct_family(row[0])

    @staticmethod
    def _reconstruct_family(raw_family_id: object) -> Family:
        if not isinstance(raw_family_id, str):
            raise SQLiteReconstructionError("Stored Family identity is invalid")

        try:
            parsed = UUID(raw_family_id)
        except (ValueError, AttributeError) as error:
            raise SQLiteReconstructionError("Stored Family identity is invalid") from error

        if raw_family_id != str(parsed):
            raise SQLiteReconstructionError("Stored Family identity is not canonical")

        try:
            return Family(family_id=FamilyId(parsed))
        except (TypeError, ValueError) as error:
            raise SQLiteReconstructionError(
                "Stored Family cannot reconstruct canonical domain state"
            ) from error
