"""Integration tests for SQLite connection, locking, rollback, and permissions."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import cast

import pytest

from familyos_cli.infrastructure.persistence import (
    SQLiteCorruptionError,
    SQLiteDatabase,
    SQLiteLockError,
    SQLitePermissionError,
    SQLitePersistenceError,
)
from familyos_cli.infrastructure.persistence.sqlite_database import (
    is_uniqueness_violation,
    translate_sqlite_error,
)


def _database(tmp_path: Path) -> SQLiteDatabase:
    os.chmod(tmp_path, 0o700)
    return SQLiteDatabase(tmp_path / "core.sqlite3")


class _SQLiteErrorDouble(Exception):
    def __init__(self, code: int, name: str, message: str) -> None:
        super().__init__(message)
        self.sqlite_errorcode = code
        self.sqlite_errorname = name


def _sqlite_error(
    code: int,
    name: str,
    message: str = "unrelated message",
) -> sqlite3.Error:
    return cast(sqlite3.Error, _SQLiteErrorDouble(code, name, message))


def test_connection_applies_required_pragmas_and_permissions(tmp_path: Path) -> None:
    database = _database(tmp_path)

    with database.connection() as connection:
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        synchronous = connection.execute("PRAGMA synchronous").fetchone()[0]

    assert foreign_keys == 1
    assert busy_timeout == 1_000
    assert synchronous == 2
    assert (database.path.stat().st_mode & 0o777) == 0o600
    assert (tmp_path.stat().st_mode & 0o777) == 0o700


def test_write_transaction_rolls_back_partial_state(tmp_path: Path) -> None:
    database = _database(tmp_path)

    with (
        database.connection() as connection,
        pytest.raises(RuntimeError, match="injected failure"),
        database.write_transaction(connection),
    ):
        connection.execute(
            "INSERT INTO persons (person_id) VALUES (?)",
            ("12345678-1234-4234-8234-123456789abc",),
        )
        raise RuntimeError("injected failure")

    with database.connection() as connection:
        row = connection.execute("SELECT COUNT(*) FROM persons").fetchone()

    assert row == (0,)


def test_locked_database_maps_to_typed_lock_failure(tmp_path: Path) -> None:
    database = _database(tmp_path)

    with database.connection() as first:
        first.execute("BEGIN IMMEDIATE")
        try:
            with (
                database.connection() as second,
                pytest.raises(SQLiteLockError),
                database.write_transaction(second),
            ):
                pass
        finally:
            first.execute("ROLLBACK")


def test_insecure_existing_file_mode_fails_closed(tmp_path: Path) -> None:
    database = _database(tmp_path)

    with database.connection():
        pass

    os.chmod(database.path, 0o400)
    try:
        with (
            pytest.raises(SQLitePermissionError, match="mode 0600"),
            database.connection(),
        ):
            pass
    finally:
        os.chmod(database.path, 0o600)


def test_insecure_parent_directory_mode_fails_closed(tmp_path: Path) -> None:
    os.chmod(tmp_path, 0o755)
    database = SQLiteDatabase(tmp_path / "core.sqlite3")

    with (
        pytest.raises(SQLitePermissionError, match="mode 0700"),
        database.connection(),
    ):
        pass


def test_symlinked_parent_directory_fails_closed(tmp_path: Path) -> None:
    os.chmod(tmp_path, 0o700)
    real_parent = tmp_path / "real"
    real_parent.mkdir(mode=0o700)
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    database = SQLiteDatabase(linked_parent / "core.sqlite3")

    with (
        pytest.raises(SQLitePermissionError, match="symbolic link"),
        database.connection(),
    ):
        pass


def test_connection_is_closed_after_context_exit(tmp_path: Path) -> None:
    database = _database(tmp_path)

    with database.connection() as connection:
        assert connection.execute("SELECT 1").fetchone() == (1,)

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_connection_is_closed_on_error_path(tmp_path: Path) -> None:
    database = _database(tmp_path)

    with (
        pytest.raises(RuntimeError, match="injected failure"),
        database.connection() as connection,
    ):
        raise RuntimeError("injected failure")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_error_mapping_uses_sqlite_error_codes() -> None:
    busy = _sqlite_error(sqlite3.SQLITE_BUSY, "SQLITE_BUSY")
    corrupt = _sqlite_error(sqlite3.SQLITE_CORRUPT, "SQLITE_CORRUPT")
    readonly = _sqlite_error(sqlite3.SQLITE_READONLY, "SQLITE_READONLY")

    assert isinstance(translate_sqlite_error(busy), SQLiteLockError)
    assert isinstance(translate_sqlite_error(corrupt), SQLiteCorruptionError)
    assert isinstance(translate_sqlite_error(readonly), SQLitePermissionError)


@pytest.mark.parametrize(
    ("code", "name", "expected"),
    [
        (sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY, "SQLITE_CONSTRAINT_PRIMARYKEY", True),
        (sqlite3.SQLITE_CONSTRAINT_UNIQUE, "SQLITE_CONSTRAINT_UNIQUE", True),
        (sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY, "SQLITE_CONSTRAINT_FOREIGNKEY", False),
        (sqlite3.SQLITE_CONSTRAINT_CHECK, "SQLITE_CONSTRAINT_CHECK", False),
        (sqlite3.SQLITE_CONSTRAINT_TRIGGER, "SQLITE_CONSTRAINT_TRIGGER", False),
    ],
)
def test_uniqueness_mapping_uses_extended_constraint_codes(
    code: int,
    name: str,
    expected: bool,
) -> None:
    error = _sqlite_error(code, name)
    assert is_uniqueness_violation(cast(sqlite3.IntegrityError, error)) is expected


class _RollbackFailureConnection:
    def __init__(self) -> None:
        self.in_transaction = False

    def execute(self, sql: str) -> None:
        if sql == "BEGIN IMMEDIATE":
            self.in_transaction = True
            return
        if sql == "ROLLBACK":
            raise sqlite3.OperationalError("disk I/O error")
        raise AssertionError(f"Unexpected SQL: {sql}")


def test_rollback_failure_preserves_original_base_exception(tmp_path: Path) -> None:
    database = _database(tmp_path)
    fake = cast(sqlite3.Connection, _RollbackFailureConnection())

    with (
        pytest.raises(KeyboardInterrupt) as captured,
        database.write_transaction(fake),
    ):
        raise KeyboardInterrupt

    assert getattr(captured.value, "__notes__", []) == ["SQLite rollback also failed"]
    assert isinstance(captured.value.__cause__, SQLitePersistenceError)
