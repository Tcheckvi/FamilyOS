"""Schema-v1 bootstrap and validation for bounded Core Product SQLite persistence."""

from __future__ import annotations

import sqlite3

from familyos_cli.infrastructure.persistence.sqlite_errors import SQLiteSchemaError

APPLICATION_ID = 1_179_603_761  # 0x464F5331 == "FOS1"
SCHEMA_VERSION = 1

CREATE_TABLES = {
    "persons": """
    CREATE TABLE persons (
        person_id TEXT NOT NULL PRIMARY KEY
    ) STRICT, WITHOUT ROWID
    """,
    "families": """
    CREATE TABLE families (
        family_id TEXT NOT NULL PRIMARY KEY
    ) STRICT, WITHOUT ROWID
    """,
    "memberships": """
    CREATE TABLE memberships (
        family_id TEXT NOT NULL,
        person_id TEXT NOT NULL,
        state TEXT NOT NULL
            CHECK (state IN ('pending', 'active', 'suspended', 'ended')),
        PRIMARY KEY (family_id, person_id),
        FOREIGN KEY (family_id)
            REFERENCES families(family_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        FOREIGN KEY (person_id)
            REFERENCES persons(person_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    ) STRICT, WITHOUT ROWID
    """,
    "membership_facts": """
    CREATE TABLE membership_facts (
        family_id TEXT NOT NULL,
        person_id TEXT NOT NULL,
        sequence INTEGER NOT NULL
            CHECK (sequence >= 1),
        fact_type TEXT NOT NULL
            CHECK (
                fact_type IN (
                    'created',
                    'activated',
                    'suspended',
                    'reactivated',
                    'ended'
                )
            ),
        occurred_at TEXT NOT NULL,
        PRIMARY KEY (family_id, person_id, sequence),
        FOREIGN KEY (family_id, person_id)
            REFERENCES memberships(family_id, person_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    ) STRICT, WITHOUT ROWID
    """,
    "relationships": """
    CREATE TABLE relationships (
        family_id TEXT NOT NULL,
        source_person_id TEXT NOT NULL,
        target_person_id TEXT NOT NULL,
        relationship_type TEXT NOT NULL
            CHECK (
                relationship_type IN (
                    'parent_of',
                    'spouse_of',
                    'sibling_of'
                )
            ),
        state TEXT NOT NULL
            CHECK (state IN ('established', 'ended')),
        CHECK (source_person_id <> target_person_id),
        PRIMARY KEY (
            family_id,
            source_person_id,
            target_person_id,
            relationship_type
        ),
        FOREIGN KEY (family_id)
            REFERENCES families(family_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        FOREIGN KEY (source_person_id)
            REFERENCES persons(person_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        FOREIGN KEY (target_person_id)
            REFERENCES persons(person_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    ) STRICT, WITHOUT ROWID
    """,
    "relationship_facts": """
    CREATE TABLE relationship_facts (
        family_id TEXT NOT NULL,
        source_person_id TEXT NOT NULL,
        target_person_id TEXT NOT NULL,
        relationship_type TEXT NOT NULL
            CHECK (
                relationship_type IN (
                    'parent_of',
                    'spouse_of',
                    'sibling_of'
                )
            ),
        sequence INTEGER NOT NULL
            CHECK (sequence >= 1),
        fact_type TEXT NOT NULL
            CHECK (fact_type IN ('established', 'ended')),
        occurred_at TEXT NOT NULL,
        PRIMARY KEY (
            family_id,
            source_person_id,
            target_person_id,
            relationship_type,
            sequence
        ),
        FOREIGN KEY (
            family_id,
            source_person_id,
            target_person_id,
            relationship_type
        )
            REFERENCES relationships(
                family_id,
                source_person_id,
                target_person_id,
                relationship_type
            )
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    ) STRICT, WITHOUT ROWID
    """,
}

CREATE_TABLE_STATEMENTS = tuple(CREATE_TABLES.values())
EXPECTED_TABLES = frozenset(CREATE_TABLES)


def _normalize_sql(sql: str) -> str:
    return " ".join(sql.strip().rstrip(";").split())


EXPECTED_SCHEMA_OBJECTS = frozenset(
    ("table", name, _normalize_sql(statement))
    for name, statement in CREATE_TABLES.items()
)


def _pragma_int(connection: sqlite3.Connection, name: str) -> int:
    row = connection.execute(f"PRAGMA {name}").fetchone()
    if row is None or not isinstance(row[0], int):
        raise SQLiteSchemaError("SQLite schema metadata is unavailable")
    return row[0]


def _user_schema_objects(
    connection: sqlite3.Connection,
) -> frozenset[tuple[str, str, str]]:
    rows = connection.execute(
        """
        SELECT type, name, sql
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite\\_%' ESCAPE '\\'
          AND type IN ('table', 'index', 'view', 'trigger')
        ORDER BY type, name
        """
    ).fetchall()

    objects: set[tuple[str, str, str]] = set()
    for row in rows:
        if (
            len(row) != 3
            or not isinstance(row[0], str)
            or not isinstance(row[1], str)
            or not isinstance(row[2], str)
        ):
            raise SQLiteSchemaError("SQLite schema object metadata is invalid")
        objects.add((row[0], row[1], _normalize_sql(row[2])))

    return frozenset(objects)


def _is_pristine(connection: sqlite3.Connection) -> bool:
    return (
        _pragma_int(connection, "application_id") == 0
        and _pragma_int(connection, "user_version") == 0
        and not _user_schema_objects(connection)
    )


def validate_schema(connection: sqlite3.Connection) -> None:
    """Validate exact application identity, version, and complete schema-v1 DDL."""
    application_id = _pragma_int(connection, "application_id")
    version = _pragma_int(connection, "user_version")

    if application_id != APPLICATION_ID:
        raise SQLiteSchemaError("Database application identity is not FamilyOS Wave A")
    if version != SCHEMA_VERSION:
        raise SQLiteSchemaError("Database schema version is unsupported")

    objects = _user_schema_objects(connection)
    if objects != EXPECTED_SCHEMA_OBJECTS:
        raise SQLiteSchemaError("Database schema objects do not match exact schema-v1")


def bootstrap_schema(connection: sqlite3.Connection) -> None:
    """Bootstrap schema-v1 once, rechecking the pristine state under a write lock."""
    if connection.in_transaction:
        raise SQLiteSchemaError("Schema bootstrap requires an idle connection")

    connection.execute("BEGIN IMMEDIATE")
    try:
        if not _is_pristine(connection):
            validate_schema(connection)
            connection.execute("COMMIT")
            return

        connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        for statement in CREATE_TABLE_STATEMENTS:
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        validate_schema(connection)
        connection.execute("COMMIT")
    except BaseException as original_error:
        if connection.in_transaction:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error as rollback_error:
                original_error.add_note("SQLite schema rollback also failed")
                raise original_error from rollback_error
        raise


def ensure_schema(connection: sqlite3.Connection) -> None:
    """Validate schema-v1 or bootstrap only a truly pristine database."""
    try:
        validate_schema(connection)
        return
    except SQLiteSchemaError:
        pass

    if _is_pristine(connection):
        bootstrap_schema(connection)
        return

    validate_schema(connection)
