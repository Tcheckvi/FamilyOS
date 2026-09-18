"""Append-only audit trail for Pilot 0 M2.

Terminology note: this is an APPEND-ONLY audit trail, not an "immutable"
one. ``AuditTrail`` exposes no update or delete method, so nothing in this
codebase can alter or remove a written record -- but nothing here provides
a cryptographic or write-once-storage guarantee against, say, direct
database file edits outside this process. "Append-only" is the accurate
claim; "immutable" would be an overclaim this package deliberately avoids
making, per the correction already applied to the Pilot 0 preparation
package.

Privacy note: records store event/outcome metadata only, never the
proposal's actual content (event_summary/date/time/person). This follows
the same content-versus-behavior principle used throughout this session's
Pilot 0 design work: observe what happened, not the private content
involved.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AuditRecord:
    """One append-only audit event. Content-free by design."""

    correlation_id: str
    event_type: str  # "proposal_created" | "decision_made" | "timeline_written"
    outcome: str | None
    recorded_at: datetime


class AuditTrail:
    """SQLite-backed, append-only audit trail.

    Exposes exactly one write method, ``append``. Reading back records
    (``for_correlation_id``) is provided for test/inspection purposes; it is
    not a mutation.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def append(self, record: AuditRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO audit_records (
                correlation_id, event_type, outcome, recorded_at
            ) VALUES (?, ?, ?, ?)
            """,
            (
                record.correlation_id,
                record.event_type,
                record.outcome,
                record.recorded_at.isoformat(),
            ),
        )
        self._connection.commit()

    def for_correlation_id(self, correlation_id: str) -> list[AuditRecord]:
        cursor = self._connection.execute(
            """
            SELECT correlation_id, event_type, outcome, recorded_at
            FROM audit_records
            WHERE correlation_id = ?
            ORDER BY id ASC
            """,
            (correlation_id,),
        )
        return [
            AuditRecord(
                correlation_id=row[0],
                event_type=row[1],
                outcome=row[2],
                recorded_at=datetime.fromisoformat(row[3]),
            )
            for row in cursor.fetchall()
        ]
