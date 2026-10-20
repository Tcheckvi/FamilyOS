"""Bounded SQLite persistence infrastructure for Core Product Wave A."""

from familyos_cli.infrastructure.persistence.sqlite_database import SQLiteDatabase
from familyos_cli.infrastructure.persistence.sqlite_errors import (
    SQLiteCorruptionError,
    SQLiteLockError,
    SQLitePermissionError,
    SQLitePersistenceError,
    SQLiteReconstructionError,
    SQLiteSchemaError,
)
from familyos_cli.infrastructure.persistence.sqlite_schema import (
    APPLICATION_ID,
    SCHEMA_VERSION,
)

__all__ = [
    "APPLICATION_ID",
    "SCHEMA_VERSION",
    "SQLiteCorruptionError",
    "SQLiteDatabase",
    "SQLiteLockError",
    "SQLitePermissionError",
    "SQLitePersistenceError",
    "SQLiteReconstructionError",
    "SQLiteSchemaError",
]
