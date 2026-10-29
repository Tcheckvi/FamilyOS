"""Typed infrastructure failures for SQLite Core Product persistence."""

from __future__ import annotations


class SQLitePersistenceError(Exception):
    """Base failure for the bounded SQLite persistence adapter."""


class SQLiteSchemaError(SQLitePersistenceError):
    """Raised when database identity or schema state is unsupported."""


class SQLiteLockError(SQLitePersistenceError):
    """Raised when the bounded single-writer lock cannot be acquired."""


class SQLiteCorruptionError(SQLitePersistenceError):
    """Raised when SQLite reports an invalid or corrupt database."""


class SQLitePermissionError(SQLitePersistenceError):
    """Raised when the database path does not satisfy local access policy."""


class SQLiteReconstructionError(SQLitePersistenceError):
    """Raised when persisted state cannot reconstruct canonical domain state."""
