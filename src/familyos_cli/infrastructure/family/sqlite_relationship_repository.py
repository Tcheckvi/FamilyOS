"""SQLite adapter for canonical Relationship temporal persistence."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from uuid import UUID

from familyos_cli.application.ports.family import (
    RelationshipConflictError,
    RelationshipRepository,
    RelationshipTemporalFact,
)
from familyos_cli.domain.family import (
    FamilyId,
    FamilyRelationshipEnded,
    FamilyRelationshipEstablished,
    Relationship,
    RelationshipState,
    RelationshipType,
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


class SQLiteRelationshipRepository(RelationshipRepository):
    """Durably persist canonical Relationship continuity and temporal facts."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def save(
        self,
        relationship: Relationship,
        temporal_fact: RelationshipTemporalFact,
    ) -> None:
        """Atomically persist one canonical Relationship transition and fact."""
        family_id = str(relationship.family_id)
        source_person_id = str(relationship.source_person_id)
        target_person_id = str(relationship.target_person_id)
        relationship_type = relationship.relationship_type.value
        key = (
            family_id,
            source_person_id,
            target_person_id,
            relationship_type,
        )

        with (
            self._database.connection() as connection,
            self._database.write_transaction(connection),
        ):
            try:
                existing_row = connection.execute(
                    """
                    SELECT
                        family_id,
                        source_person_id,
                        target_person_id,
                        relationship_type,
                        state
                    FROM relationships
                    WHERE family_id = ?
                      AND source_person_id = ?
                      AND target_person_id = ?
                      AND relationship_type = ?
                    """,
                    key,
                ).fetchone()
                history_rows = connection.execute(
                    """
                    SELECT sequence, fact_type, occurred_at
                    FROM relationship_facts
                    WHERE family_id = ?
                      AND source_person_id = ?
                      AND target_person_id = ?
                      AND relationship_type = ?
                    ORDER BY sequence
                    """,
                    key,
                ).fetchall()

                existing: Relationship | None
                if existing_row is None:
                    if history_rows:
                        raise SQLiteReconstructionError(
                            "Stored Relationship facts exist without continuity"
                        )
                    existing = None
                else:
                    existing = self._reconstruct_relationship(*existing_row)
                    self._validate_persisted_history(existing, history_rows)

                self._validate_temporal_fact(
                    existing=existing,
                    candidate=relationship,
                    temporal_fact=temporal_fact,
                )

                if existing is None:
                    if relationship.state is not RelationshipState.ESTABLISHED:
                        raise RelationshipConflictError(
                            "Initial Relationship persistence requires ESTABLISHED state"
                        )
                    connection.execute(
                        """
                        INSERT INTO relationships (
                            family_id,
                            source_person_id,
                            target_person_id,
                            relationship_type,
                            state
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (*key, relationship.state.value),
                    )
                    sequence = 1
                else:
                    if not self._is_valid_successor(existing, relationship):
                        raise RelationshipConflictError(
                            "Relationship persistence must preserve one canonical continuity"
                        )

                    cursor = connection.execute(
                        """
                        UPDATE relationships
                        SET state = ?
                        WHERE family_id = ?
                          AND source_person_id = ?
                          AND target_person_id = ?
                          AND relationship_type = ?
                          AND state = ?
                        """,
                        (
                            relationship.state.value,
                            *key,
                            existing.state.value,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise RelationshipConflictError(
                            "Relationship persistence lost canonical continuity"
                        )
                    sequence = len(history_rows) + 1

                connection.execute(
                    """
                    INSERT INTO relationship_facts (
                        family_id,
                        source_person_id,
                        target_person_id,
                        relationship_type,
                        sequence,
                        fact_type,
                        occurred_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        *key,
                        sequence,
                        self._fact_type(temporal_fact),
                        temporal_fact.occurred_at.isoformat(),
                    ),
                )
            except RelationshipConflictError:
                raise
            except SQLiteReconstructionError:
                raise
            except sqlite3.IntegrityError as error:
                if is_uniqueness_violation(error):
                    raise RelationshipConflictError(
                        "Relationship persistence conflict"
                    ) from error
                raise translate_sqlite_error(error) from error
            except sqlite3.Error as error:
                raise translate_sqlite_error(error) from error

    def get(
        self,
        family_id: FamilyId,
        source_person_id: PersonId,
        target_person_id: PersonId,
        relationship_type: RelationshipType,
    ) -> Relationship | None:
        """Return Relationship for an already-canonical normalized business key."""
        key = (
            str(family_id),
            str(source_person_id),
            str(target_person_id),
            relationship_type.value,
        )

        with self._database.connection() as connection:
            try:
                row = connection.execute(
                    """
                    SELECT
                        family_id,
                        source_person_id,
                        target_person_id,
                        relationship_type,
                        state
                    FROM relationships
                    WHERE family_id = ?
                      AND source_person_id = ?
                      AND target_person_id = ?
                      AND relationship_type = ?
                    """,
                    key,
                ).fetchone()
                history_rows = connection.execute(
                    """
                    SELECT sequence, fact_type, occurred_at
                    FROM relationship_facts
                    WHERE family_id = ?
                      AND source_person_id = ?
                      AND target_person_id = ?
                      AND relationship_type = ?
                    ORDER BY sequence
                    """,
                    key,
                ).fetchall()
            except sqlite3.Error as error:
                raise translate_sqlite_error(error) from error

        if row is None:
            if history_rows:
                raise SQLiteReconstructionError(
                    "Stored Relationship facts exist without continuity"
                )
            return None

        relationship = self._reconstruct_relationship(*row)
        self._validate_persisted_history(relationship, history_rows)
        return relationship

    @staticmethod
    def _validate_temporal_fact(
        *,
        existing: Relationship | None,
        candidate: Relationship,
        temporal_fact: RelationshipTemporalFact,
    ) -> None:
        if (
            temporal_fact.family_id != candidate.family_id
            or temporal_fact.source_person_id != candidate.source_person_id
            or temporal_fact.target_person_id != candidate.target_person_id
            or temporal_fact.relationship_type is not candidate.relationship_type
        ):
            raise RelationshipConflictError(
                "Relationship temporal fact must match canonical Relationship identity"
            )

        if existing is None:
            if not isinstance(temporal_fact, FamilyRelationshipEstablished):
                raise RelationshipConflictError(
                    "Initial Relationship persistence requires establishment temporal fact"
                )
            return

        if not (
            existing.state is RelationshipState.ESTABLISHED
            and candidate.state is RelationshipState.ENDED
            and isinstance(temporal_fact, FamilyRelationshipEnded)
        ):
            raise RelationshipConflictError(
                "Relationship temporal fact must match canonical lifecycle transition"
            )

    @staticmethod
    def _is_valid_successor(
        existing: Relationship,
        candidate: Relationship,
    ) -> bool:
        return (
            existing.family_id == candidate.family_id
            and existing.source_person_id == candidate.source_person_id
            and existing.target_person_id == candidate.target_person_id
            and existing.relationship_type is candidate.relationship_type
            and existing.state is RelationshipState.ESTABLISHED
            and candidate.state is RelationshipState.ENDED
        )

    @staticmethod
    def _fact_type(temporal_fact: RelationshipTemporalFact) -> str:
        if isinstance(temporal_fact, FamilyRelationshipEstablished):
            return "established"
        if isinstance(temporal_fact, FamilyRelationshipEnded):
            return "ended"
        raise RelationshipConflictError("Relationship temporal fact type is unsupported")

    @classmethod
    def _reconstruct_relationship(
        cls,
        raw_family_id: object,
        raw_source_person_id: object,
        raw_target_person_id: object,
        raw_relationship_type: object,
        raw_state: object,
    ) -> Relationship:
        family_id = cls._reconstruct_family_id(raw_family_id)
        source_person_id = cls._reconstruct_person_id(
            raw_source_person_id,
            role="source",
        )
        target_person_id = cls._reconstruct_person_id(
            raw_target_person_id,
            role="target",
        )

        if not isinstance(raw_relationship_type, str):
            raise SQLiteReconstructionError(
                "Stored Relationship type is invalid"
            )
        try:
            relationship_type = RelationshipType(raw_relationship_type)
        except ValueError as error:
            raise SQLiteReconstructionError(
                "Stored Relationship type is invalid"
            ) from error

        if not isinstance(raw_state, str):
            raise SQLiteReconstructionError("Stored Relationship state is invalid")
        try:
            state = RelationshipState(raw_state)
        except ValueError as error:
            raise SQLiteReconstructionError(
                "Stored Relationship state is invalid"
            ) from error

        try:
            return Relationship(
                family_id=family_id,
                source_person_id=source_person_id,
                target_person_id=target_person_id,
                relationship_type=relationship_type,
                state=state,
            )
        except (TypeError, ValueError) as error:
            raise SQLiteReconstructionError(
                "Stored Relationship cannot reconstruct canonical domain state"
            ) from error

    @staticmethod
    def _reconstruct_family_id(raw_family_id: object) -> FamilyId:
        if not isinstance(raw_family_id, str):
            raise SQLiteReconstructionError(
                "Stored Relationship FamilyId is invalid"
            )
        try:
            parsed = UUID(raw_family_id)
        except (ValueError, AttributeError) as error:
            raise SQLiteReconstructionError(
                "Stored Relationship FamilyId is invalid"
            ) from error
        if raw_family_id != str(parsed):
            raise SQLiteReconstructionError(
                "Stored Relationship FamilyId is not canonical"
            )
        try:
            return FamilyId(parsed)
        except (TypeError, ValueError) as error:
            raise SQLiteReconstructionError(
                "Stored Relationship FamilyId is not canonical"
            ) from error

    @staticmethod
    def _reconstruct_person_id(
        raw_person_id: object,
        *,
        role: str,
    ) -> PersonId:
        if not isinstance(raw_person_id, str):
            raise SQLiteReconstructionError(
                f"Stored Relationship {role} PersonId is invalid"
            )
        try:
            parsed = UUID(raw_person_id)
        except (ValueError, AttributeError) as error:
            raise SQLiteReconstructionError(
                f"Stored Relationship {role} PersonId is invalid"
            ) from error
        if raw_person_id != str(parsed):
            raise SQLiteReconstructionError(
                f"Stored Relationship {role} PersonId is not canonical"
            )
        try:
            return PersonId(parsed)
        except (TypeError, ValueError) as error:
            raise SQLiteReconstructionError(
                f"Stored Relationship {role} PersonId is not canonical"
            ) from error

    @classmethod
    def _validate_persisted_history(
        cls,
        relationship: Relationship,
        rows: list[tuple[object, object, object]],
    ) -> None:
        if not rows:
            raise SQLiteReconstructionError(
                "Stored Relationship has no temporal fact history"
            )

        state: RelationshipState | None = None
        for expected_sequence, row in enumerate(rows, start=1):
            raw_sequence, raw_fact_type, raw_occurred_at = row

            if raw_sequence != expected_sequence:
                raise SQLiteReconstructionError(
                    "Stored Relationship temporal fact sequence is invalid"
                )
            if not isinstance(raw_fact_type, str):
                raise SQLiteReconstructionError(
                    "Stored Relationship temporal fact type is invalid"
                )

            cls._validate_stored_occurred_at(raw_occurred_at)
            state = cls._next_history_state(state, raw_fact_type)

        if state is not relationship.state:
            raise SQLiteReconstructionError(
                "Stored Relationship state does not match temporal fact history"
            )

    @staticmethod
    def _validate_stored_occurred_at(raw_occurred_at: object) -> None:
        if not isinstance(raw_occurred_at, str):
            raise SQLiteReconstructionError(
                "Stored Relationship occurrence time is invalid"
            )
        try:
            occurred_at = datetime.fromisoformat(raw_occurred_at)
        except ValueError as error:
            raise SQLiteReconstructionError(
                "Stored Relationship occurrence time is invalid"
            ) from error
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise SQLiteReconstructionError(
                "Stored Relationship occurrence time is not timezone-aware"
            )
        if raw_occurred_at != occurred_at.isoformat():
            raise SQLiteReconstructionError(
                "Stored Relationship occurrence time is not canonical"
            )

    @staticmethod
    def _next_history_state(
        state: RelationshipState | None,
        fact_type: str,
    ) -> RelationshipState:
        if state is None:
            if fact_type == "established":
                return RelationshipState.ESTABLISHED
        elif (
            state is RelationshipState.ESTABLISHED
            and fact_type == "ended"
        ):
            return RelationshipState.ENDED

        raise SQLiteReconstructionError(
            "Stored Relationship temporal fact history is non-canonical"
        )
