"""SQLite adapter for canonical Membership temporal persistence."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from uuid import UUID

from familyos_cli.application.ports.family import (
    MembershipConflictError,
    MembershipRepository,
    MembershipTemporalFact,
)
from familyos_cli.domain.family import (
    FamilyId,
    FamilyMembershipActivated,
    FamilyMembershipCreated,
    FamilyMembershipEnded,
    FamilyMembershipReactivated,
    FamilyMembershipSuspended,
    Membership,
    MembershipState,
)
from familyos_cli.domain.person import PersonId
from familyos_cli.infrastructure.persistence.sqlite_database import (
    SQLiteDatabase,
    is_uniqueness_violation,
    translate_sqlite_error,
)
from familyos_cli.infrastructure.persistence.sqlite_errors import (
    SQLiteReconstructionError,
)


class SQLiteMembershipRepository(MembershipRepository):
    """Durably persist canonical Membership continuity and temporal facts."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def save(
        self,
        membership: Membership,
        temporal_fact: MembershipTemporalFact,
    ) -> None:
        """Atomically persist one canonical Membership transition and temporal fact."""
        family_id = str(membership.family_id)
        person_id = str(membership.person_id)

        with (
            self._database.connection() as connection,
            self._database.write_transaction(connection),
        ):
            try:
                existing_row = connection.execute(
                    """
                    SELECT family_id, person_id, state
                    FROM memberships
                    WHERE family_id = ? AND person_id = ?
                    """,
                    (family_id, person_id),
                ).fetchone()
                history_rows = connection.execute(
                    """
                    SELECT sequence, fact_type, occurred_at
                    FROM membership_facts
                    WHERE family_id = ? AND person_id = ?
                    ORDER BY sequence
                    """,
                    (family_id, person_id),
                ).fetchall()

                existing: Membership | None
                if existing_row is None:
                    if history_rows:
                        raise SQLiteReconstructionError(
                            "Stored Membership facts exist without continuity"
                        )
                    existing = None
                else:
                    existing = self._reconstruct_membership(*existing_row)
                    self._validate_persisted_history(existing, history_rows)

                self._validate_temporal_fact(
                    existing=existing,
                    candidate=membership,
                    temporal_fact=temporal_fact,
                )

                if existing is None:
                    if membership.state is not MembershipState.PENDING:
                        raise MembershipConflictError(
                            "Initial Membership persistence requires PENDING state"
                        )
                    connection.execute(
                        """
                        INSERT INTO memberships (family_id, person_id, state)
                        VALUES (?, ?, ?)
                        """,
                        (family_id, person_id, membership.state.value),
                    )
                    sequence = 1
                else:
                    if not self._is_valid_successor(existing, membership):
                        raise MembershipConflictError(
                            "Membership persistence must preserve one canonical continuity"
                        )

                    cursor = connection.execute(
                        """
                        UPDATE memberships
                        SET state = ?
                        WHERE family_id = ?
                          AND person_id = ?
                          AND state = ?
                        """,
                        (
                            membership.state.value,
                            family_id,
                            person_id,
                            existing.state.value,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise MembershipConflictError(
                            "Membership persistence lost canonical continuity"
                        )
                    sequence = len(history_rows) + 1

                connection.execute(
                    """
                    INSERT INTO membership_facts (
                        family_id,
                        person_id,
                        sequence,
                        fact_type,
                        occurred_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        family_id,
                        person_id,
                        sequence,
                        self._fact_type(temporal_fact),
                        temporal_fact.occurred_at.isoformat(),
                    ),
                )
            except MembershipConflictError:
                raise
            except SQLiteReconstructionError:
                raise
            except sqlite3.IntegrityError as error:
                if is_uniqueness_violation(error):
                    raise MembershipConflictError(
                        "Membership persistence conflict"
                    ) from error
                raise translate_sqlite_error(error) from error
            except sqlite3.Error as error:
                raise translate_sqlite_error(error) from error

    def get(
        self,
        family_id: FamilyId,
        person_id: PersonId,
    ) -> Membership | None:
        """Return canonical Membership, including ENDED, or ordinary absence."""
        raw_family_id = str(family_id)
        raw_person_id = str(person_id)

        with self._database.connection() as connection:
            try:
                row = connection.execute(
                    """
                    SELECT family_id, person_id, state
                    FROM memberships
                    WHERE family_id = ? AND person_id = ?
                    """,
                    (raw_family_id, raw_person_id),
                ).fetchone()
                history_rows = connection.execute(
                    """
                    SELECT sequence, fact_type, occurred_at
                    FROM membership_facts
                    WHERE family_id = ? AND person_id = ?
                    ORDER BY sequence
                    """,
                    (raw_family_id, raw_person_id),
                ).fetchall()
            except sqlite3.Error as error:
                raise translate_sqlite_error(error) from error

        if row is None:
            if history_rows:
                raise SQLiteReconstructionError(
                    "Stored Membership facts exist without continuity"
                )
            return None

        membership = self._reconstruct_membership(*row)
        self._validate_persisted_history(membership, history_rows)
        return membership

    @staticmethod
    def _validate_temporal_fact(
        *,
        existing: Membership | None,
        candidate: Membership,
        temporal_fact: MembershipTemporalFact,
    ) -> None:
        if (
            temporal_fact.family_id != candidate.family_id
            or temporal_fact.person_id != candidate.person_id
        ):
            raise MembershipConflictError(
                "Membership temporal fact must match canonical Membership identity"
            )

        if existing is None:
            if not isinstance(temporal_fact, FamilyMembershipCreated):
                raise MembershipConflictError(
                    "Initial Membership persistence requires creation temporal fact"
                )
            return

        expected_type: type[MembershipTemporalFact]
        if (
            existing.state is MembershipState.PENDING
            and candidate.state is MembershipState.ACTIVE
        ):
            expected_type = FamilyMembershipActivated
        elif (
            existing.state is MembershipState.ACTIVE
            and candidate.state is MembershipState.SUSPENDED
        ):
            expected_type = FamilyMembershipSuspended
        elif (
            existing.state is MembershipState.SUSPENDED
            and candidate.state is MembershipState.ACTIVE
        ):
            expected_type = FamilyMembershipReactivated
        elif candidate.state is MembershipState.ENDED and existing.state in {
            MembershipState.PENDING,
            MembershipState.ACTIVE,
            MembershipState.SUSPENDED,
        }:
            expected_type = FamilyMembershipEnded
        else:
            raise MembershipConflictError(
                "Membership persistence must preserve one canonical continuity"
            )

        if not isinstance(temporal_fact, expected_type):
            raise MembershipConflictError(
                "Membership temporal fact must match canonical lifecycle transition"
            )

    @staticmethod
    def _is_valid_successor(existing: Membership, candidate: Membership) -> bool:
        if (
            existing.family_id != candidate.family_id
            or existing.person_id != candidate.person_id
        ):
            return False

        if existing.state is MembershipState.PENDING:
            return candidate.state in {
                MembershipState.ACTIVE,
                MembershipState.ENDED,
            }
        if existing.state is MembershipState.ACTIVE:
            return candidate.state in {
                MembershipState.SUSPENDED,
                MembershipState.ENDED,
            }
        if existing.state is MembershipState.SUSPENDED:
            return candidate.state in {
                MembershipState.ACTIVE,
                MembershipState.ENDED,
            }
        return False

    @staticmethod
    def _fact_type(temporal_fact: MembershipTemporalFact) -> str:
        if isinstance(temporal_fact, FamilyMembershipCreated):
            return "created"
        if isinstance(temporal_fact, FamilyMembershipActivated):
            return "activated"
        if isinstance(temporal_fact, FamilyMembershipSuspended):
            return "suspended"
        if isinstance(temporal_fact, FamilyMembershipReactivated):
            return "reactivated"
        if isinstance(temporal_fact, FamilyMembershipEnded):
            return "ended"
        raise MembershipConflictError("Membership temporal fact type is unsupported")

    @classmethod
    def _reconstruct_membership(
        cls,
        raw_family_id: object,
        raw_person_id: object,
        raw_state: object,
    ) -> Membership:
        family_id = cls._reconstruct_family_id(raw_family_id)
        person_id = cls._reconstruct_person_id(raw_person_id)

        if not isinstance(raw_state, str):
            raise SQLiteReconstructionError("Stored Membership state is invalid")
        try:
            state = MembershipState(raw_state)
        except ValueError as error:
            raise SQLiteReconstructionError(
                "Stored Membership state is invalid"
            ) from error

        try:
            return Membership(
                family_id=family_id,
                person_id=person_id,
                state=state,
            )
        except (TypeError, ValueError) as error:
            raise SQLiteReconstructionError(
                "Stored Membership cannot reconstruct canonical domain state"
            ) from error

    @staticmethod
    def _reconstruct_family_id(raw_family_id: object) -> FamilyId:
        if not isinstance(raw_family_id, str):
            raise SQLiteReconstructionError("Stored Membership FamilyId is invalid")
        try:
            parsed = UUID(raw_family_id)
        except (ValueError, AttributeError) as error:
            raise SQLiteReconstructionError(
                "Stored Membership FamilyId is invalid"
            ) from error
        if raw_family_id != str(parsed):
            raise SQLiteReconstructionError(
                "Stored Membership FamilyId is not canonical"
            )
        try:
            return FamilyId(parsed)
        except (TypeError, ValueError) as error:
            raise SQLiteReconstructionError(
                "Stored Membership FamilyId is not canonical"
            ) from error

    @staticmethod
    def _reconstruct_person_id(raw_person_id: object) -> PersonId:
        if not isinstance(raw_person_id, str):
            raise SQLiteReconstructionError("Stored Membership PersonId is invalid")
        try:
            parsed = UUID(raw_person_id)
        except (ValueError, AttributeError) as error:
            raise SQLiteReconstructionError(
                "Stored Membership PersonId is invalid"
            ) from error
        if raw_person_id != str(parsed):
            raise SQLiteReconstructionError(
                "Stored Membership PersonId is not canonical"
            )
        try:
            return PersonId(parsed)
        except (TypeError, ValueError) as error:
            raise SQLiteReconstructionError(
                "Stored Membership PersonId is not canonical"
            ) from error

    @classmethod
    def _validate_persisted_history(
        cls,
        membership: Membership,
        rows: list[tuple[object, object, object]],
    ) -> None:
        if not rows:
            raise SQLiteReconstructionError(
                "Stored Membership has no temporal fact history"
            )

        state: MembershipState | None = None
        for expected_sequence, row in enumerate(rows, start=1):
            raw_sequence, raw_fact_type, raw_occurred_at = row

            if raw_sequence != expected_sequence:
                raise SQLiteReconstructionError(
                    "Stored Membership temporal fact sequence is invalid"
                )
            if not isinstance(raw_fact_type, str):
                raise SQLiteReconstructionError(
                    "Stored Membership temporal fact type is invalid"
                )

            cls._validate_stored_occurred_at(raw_occurred_at)
            state = cls._next_history_state(state, raw_fact_type)

        if state is not membership.state:
            raise SQLiteReconstructionError(
                "Stored Membership state does not match temporal fact history"
            )

    @staticmethod
    def _validate_stored_occurred_at(raw_occurred_at: object) -> None:
        if not isinstance(raw_occurred_at, str):
            raise SQLiteReconstructionError(
                "Stored Membership occurrence time is invalid"
            )
        try:
            occurred_at = datetime.fromisoformat(raw_occurred_at)
        except ValueError as error:
            raise SQLiteReconstructionError(
                "Stored Membership occurrence time is invalid"
            ) from error
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise SQLiteReconstructionError(
                "Stored Membership occurrence time is not timezone-aware"
            )
        if raw_occurred_at != occurred_at.isoformat():
            raise SQLiteReconstructionError(
                "Stored Membership occurrence time is not canonical"
            )

    @staticmethod
    def _next_history_state(
        state: MembershipState | None,
        fact_type: str,
    ) -> MembershipState:
        if state is None:
            if fact_type == "created":
                return MembershipState.PENDING
        elif state is MembershipState.PENDING:
            if fact_type == "activated":
                return MembershipState.ACTIVE
            if fact_type == "ended":
                return MembershipState.ENDED
        elif state is MembershipState.ACTIVE:
            if fact_type == "suspended":
                return MembershipState.SUSPENDED
            if fact_type == "ended":
                return MembershipState.ENDED
        elif state is MembershipState.SUSPENDED:
            if fact_type == "reactivated":
                return MembershipState.ACTIVE
            if fact_type == "ended":
                return MembershipState.ENDED

        raise SQLiteReconstructionError(
            "Stored Membership temporal fact history is non-canonical"
        )
