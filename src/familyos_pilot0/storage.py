"""Local persistence for Pilot 0 M2.

Uses Python's standard-library ``sqlite3`` -- no new dependency, no ORM, no
database framework. A single connection holds two tables: confirmed
timeline entries and the append-only audit trail.

Why SQLite here, not a hand-rolled flat file (see the M2 package review
document's justification in full): SQLite's ``UNIQUE`` constraint gives
replay/duplicate protection on ``correlation_id`` for free, at the storage
layer, rather than requiring hand-rolled locking and uniqueness-checking
code to get the same guarantee safely from a flat file. For a two-table,
correlation-linked design (timeline entries cross-referenced by audit
records), that is less code and fewer failure modes than the flat-file
alternative, not more.
"""

from __future__ import annotations

import sqlite3


def create_pilot0_schema(conn: sqlite3.Connection) -> None:
    """Create the M2 tables if they do not already exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS timeline_entries (
            correlation_id TEXT PRIMARY KEY,
            family_id TEXT NOT NULL,
            subject_person_ref TEXT,
            event_summary TEXT NOT NULL,
            date TEXT,
            time TEXT,
            confirmed_by TEXT NOT NULL,
            confirmed_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            correlation_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            outcome TEXT,
            recorded_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def open_pilot0_connection(database_path: str) -> sqlite3.Connection:
    """Open (and schema-initialize) a Pilot 0 storage connection.

    ``database_path`` may be a real file path or ``":memory:"`` for tests.
    """
    conn = sqlite3.connect(database_path)
    create_pilot0_schema(conn)
    return conn
