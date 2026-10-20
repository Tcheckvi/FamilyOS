"""Connection and transaction boundary for bounded local SQLite persistence."""

from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from familyos_cli.infrastructure.persistence.sqlite_errors import (
    SQLiteCorruptionError,
    SQLiteLockError,
    SQLitePermissionError,
    SQLitePersistenceError,
)
from familyos_cli.infrastructure.persistence.sqlite_schema import ensure_schema

BUSY_TIMEOUT_MS = 1_000


def _sqlite_primary_code(error: sqlite3.Error) -> int | None:
    code = getattr(error, "sqlite_errorcode", None)
    if not isinstance(code, int):
        return None
    return code & 0xFF


def is_uniqueness_violation(error: sqlite3.IntegrityError) -> bool:
    """Return whether SQLite reported a canonical uniqueness violation."""
    code = getattr(error, "sqlite_errorcode", None)
    return code in {
        sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY,
        sqlite3.SQLITE_CONSTRAINT_UNIQUE,
    }


def translate_sqlite_error(error: sqlite3.Error) -> SQLitePersistenceError:
    """Translate SQLite failures using result codes before message fallback."""
    primary_code = _sqlite_primary_code(error)

    if primary_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
        return SQLiteLockError("SQLite database is locked")
    if primary_code in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
        return SQLiteCorruptionError("SQLite database is invalid or corrupt")
    if primary_code in {
        sqlite3.SQLITE_READONLY,
        sqlite3.SQLITE_CANTOPEN,
        sqlite3.SQLITE_PERM,
    }:
        return SQLitePermissionError("SQLite database path is not writable")

    message = str(error).lower()
    if "locked" in message or "busy" in message:
        return SQLiteLockError("SQLite database is locked")
    if (
        "not a database" in message
        or "malformed" in message
        or "database disk image is malformed" in message
    ):
        return SQLiteCorruptionError("SQLite database is invalid or corrupt")
    if (
        "readonly" in message
        or "read-only" in message
        or "permission denied" in message
        or "unable to open database file" in message
    ):
        return SQLitePermissionError("SQLite database path is not writable")

    return SQLitePersistenceError("SQLite persistence operation failed")


class SQLiteDatabase:
    """Own bounded SQLite connection policy for the local synthetic Wave A adapter."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        """Return the configured local database path."""
        return self._path

    def _prepare_storage_path(self) -> None:
        parent = self._path.parent

        if self._path.is_symlink():
            raise SQLitePermissionError("SQLite database path must not be a symbolic link")
        if parent.is_symlink():
            raise SQLitePermissionError(
                "SQLite database parent directory must not be a symbolic link"
            )

        if not parent.exists():
            # Only the immediate database parent is adapter-owned and mode-enforced.
            # Any pre-existing intermediate ancestors remain caller-owned.
            parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            if parent.is_symlink():
                raise SQLitePermissionError(
                    "SQLite database parent directory must not be a symbolic link"
                )
            os.chmod(parent, 0o700)

        if not parent.is_dir():
            raise SQLitePermissionError(
                "SQLite database parent path must be a directory"
            )

        parent_mode = stat.S_IMODE(parent.stat().st_mode)
        if parent_mode != 0o700:
            raise SQLitePermissionError(
                "SQLite database parent directory must have mode 0700"
            )

        if not self._path.exists():
            try:
                descriptor = os.open(
                    self._path,
                    os.O_CREAT | os.O_EXCL | os.O_RDWR,
                    0o600,
                )
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
                os.chmod(self._path, 0o600)

        if self._path.is_symlink():
            raise SQLitePermissionError("SQLite database path must not be a symbolic link")
        if not self._path.is_file():
            raise SQLitePermissionError("SQLite database path must be a regular file")

        file_mode = stat.S_IMODE(self._path.stat().st_mode)
        if file_mode != 0o600:
            raise SQLitePermissionError("SQLite database file must have mode 0600")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Open, configure, validate, yield, and deterministically close a connection."""
        self._prepare_storage_path()

        try:
            connection = sqlite3.connect(
                self._path,
                timeout=BUSY_TIMEOUT_MS / 1_000,
                isolation_level=None,
                check_same_thread=True,
            )
        except sqlite3.Error as error:
            raise translate_sqlite_error(error) from error

        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            connection.execute("PRAGMA synchronous = FULL")
            ensure_schema(connection)
            yield connection
        except sqlite3.Error as error:
            raise translate_sqlite_error(error) from error
        finally:
            connection.close()

    @contextmanager
    def write_transaction(self, connection: sqlite3.Connection) -> Iterator[None]:
        """Run one explicit single-writer transaction with fail-closed rollback."""
        if connection.in_transaction:
            raise SQLitePersistenceError("Nested SQLite write transaction is unsupported")

        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as error:
            raise translate_sqlite_error(error) from error

        try:
            yield
        except BaseException as original_error:
            if connection.in_transaction:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error as rollback_error:
                    original_error.add_note("SQLite rollback also failed")
                    raise original_error from translate_sqlite_error(rollback_error)
            raise

        try:
            connection.execute("COMMIT")
        except sqlite3.Error as error:
            if connection.in_transaction:
                with suppress(sqlite3.Error):
                    connection.execute("ROLLBACK")
            raise translate_sqlite_error(error) from error
