"""Confirmed timeline entries for Pilot 0 M2.

A ``TimelineEntry`` only ever comes into existence after an explicit human
confirm or edit-then-confirm decision (see ``vertical_slice.py``). Nothing
in this module can create, update, or delete a timeline entry from a bare
proposal -- ``TimelineStore`` exposes exactly one write method, ``write``,
and it is the caller's (the vertical slice orchestrator's) responsibility to
call it only after a genuine human decision.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from familyos_pilot0.errors import DuplicateTimelineEntryError


@dataclass(frozen=True)
class TimelineEntry:
    """A confirmed (or edited-then-confirmed) family timeline entry."""

    correlation_id: str
    family_id: str
    subject_person_ref: str | None
    event_summary: str
    date: str | None
    time: str | None
    confirmed_by: str
    confirmed_at: datetime


class TimelineStore:
    """SQLite-backed store for confirmed timeline entries.

    Exposes exactly one write operation. There is no update or delete
    method -- ``correlation_id`` is the primary key, so a second write
    attempt for the same correlation_id raises
    ``DuplicateTimelineEntryError`` instead of overwriting the original
    entry.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def write(self, entry: TimelineEntry) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO timeline_entries (
                    correlation_id, family_id, subject_person_ref,
                    event_summary, date, time, confirmed_by, confirmed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.correlation_id,
                    entry.family_id,
                    entry.subject_person_ref,
                    entry.event_summary,
                    entry.date,
                    entry.time,
                    entry.confirmed_by,
                    entry.confirmed_at.isoformat(),
                ),
            )
            self._connection.commit()
        except sqlite3.IntegrityError as exc:
            raise DuplicateTimelineEntryError(
                f"A timeline entry already exists for correlation_id "
                f"{entry.correlation_id!r}."
            ) from exc

    def exists(self, correlation_id: str) -> bool:
        cursor = self._connection.execute(
            "SELECT 1 FROM timeline_entries WHERE correlation_id = ?",
            (correlation_id,),
        )
        return cursor.fetchone() is not None
