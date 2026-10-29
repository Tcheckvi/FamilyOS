"""Integration tests for exact fail-closed SQLite schema-v1 handling."""

from __future__ import annotations

import ast
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from familyos_cli.infrastructure.persistence import (
    APPLICATION_ID,
    SCHEMA_VERSION,
    SQLiteCorruptionError,
    SQLiteDatabase,
    SQLitePersistenceError,
    SQLiteSchemaError,
    sqlite_schema,
)


def _secure_parent(path: Path) -> None:
    os.chmod(path, 0o700)


def _secure_file(path: Path) -> None:
    os.chmod(path, 0o600)


def test_empty_database_bootstraps_complete_schema_v1(tmp_path: Path) -> None:
    _secure_parent(tmp_path)
    database = SQLiteDatabase(tmp_path / "core.sqlite3")

    with database.connection() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                """
            )
        }
        application_id = connection.execute("PRAGMA application_id").fetchone()[0]
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        table_sql = {
            row[0]: row[1]
            for row in connection.execute(
                """
                SELECT name, sql
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                """
            )
        }

    assert tables == sqlite_schema.EXPECTED_TABLES
    assert application_id == APPLICATION_ID
    assert user_version == SCHEMA_VERSION
    assert all("STRICT" in sql for sql in table_sql.values())
    assert all("WITHOUT ROWID" in sql for sql in table_sql.values())


def test_foreign_application_id_fails_closed(tmp_path: Path) -> None:
    _secure_parent(tmp_path)
    path = tmp_path / "foreign.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA application_id = 42")
    connection.close()
    _secure_file(path)

    with (
        pytest.raises(SQLiteSchemaError, match="application identity"),
        SQLiteDatabase(path).connection(),
    ):
        pass


def test_unknown_schema_version_fails_closed(tmp_path: Path) -> None:
    _secure_parent(tmp_path)
    path = tmp_path / "future.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
    connection.execute("PRAGMA user_version = 99")
    connection.close()
    _secure_file(path)

    with (
        pytest.raises(SQLiteSchemaError, match="schema version"),
        SQLiteDatabase(path).connection(),
    ):
        pass


def test_versioned_database_without_application_id_fails_closed(
    tmp_path: Path,
) -> None:
    _secure_parent(tmp_path)
    path = tmp_path / "unidentified.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.close()
    _secure_file(path)

    with (
        pytest.raises(SQLiteSchemaError, match="application identity"),
        SQLiteDatabase(path).connection(),
    ):
        pass


def test_nonempty_unversioned_database_fails_closed(tmp_path: Path) -> None:
    _secure_parent(tmp_path)
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE legacy (value TEXT)")
    connection.commit()
    connection.close()
    _secure_file(path)

    with pytest.raises(SQLiteSchemaError), SQLiteDatabase(path).connection():
        pass


def test_nonempty_unversioned_view_fails_closed(tmp_path: Path) -> None:
    _secure_parent(tmp_path)
    path = tmp_path / "legacy-view.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE VIEW legacy_view AS SELECT 1 AS value")
    connection.commit()
    connection.close()
    _secure_file(path)

    with pytest.raises(SQLiteSchemaError), SQLiteDatabase(path).connection():
        pass


def test_corrupt_database_fails_closed(tmp_path: Path) -> None:
    _secure_parent(tmp_path)
    path = tmp_path / "corrupt.sqlite3"
    path.write_bytes(b"not-a-sqlite-database")
    _secure_file(path)

    with pytest.raises(SQLiteCorruptionError), SQLiteDatabase(path).connection():
        pass


def test_same_table_names_with_different_definitions_fail_closed(
    tmp_path: Path,
) -> None:
    _secure_parent(tmp_path)
    path = tmp_path / "wrong-definitions.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    for table_name in sorted(sqlite_schema.EXPECTED_TABLES):
        connection.execute(f"CREATE TABLE {table_name} (value TEXT)")
    connection.commit()
    connection.close()
    _secure_file(path)

    with (
        pytest.raises(SQLiteSchemaError, match="schema objects"),
        SQLiteDatabase(path).connection(),
    ):
        pass


@pytest.mark.parametrize(
    "extra_ddl",
    [
        (
            "CREATE TRIGGER person_delete_after_insert "
            "AFTER INSERT ON persons "
            "BEGIN DELETE FROM persons; END"
        ),
        "CREATE INDEX person_identity_copy ON persons(person_id)",
    ],
)
def test_extra_trigger_or_index_on_valid_schema_fails_closed(
    tmp_path: Path,
    extra_ddl: str,
) -> None:
    _secure_parent(tmp_path)
    path = tmp_path / "extra-object.sqlite3"
    database = SQLiteDatabase(path)

    with database.connection() as connection:
        connection.execute(extra_ddl)

    with (
        pytest.raises(SQLiteSchemaError, match="schema objects"),
        database.connection(),
    ):
        pass


def test_failed_bootstrap_rolls_back_to_a_pristine_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _secure_parent(tmp_path)
    path = tmp_path / "failed-bootstrap.sqlite3"
    statements = sqlite_schema.CREATE_TABLE_STATEMENTS
    monkeypatch.setattr(
        sqlite_schema,
        "CREATE_TABLE_STATEMENTS",
        (statements[0], "CREATE TABLE broken("),
    )

    with pytest.raises(SQLitePersistenceError), SQLiteDatabase(path).connection():
        pass

    connection = sqlite3.connect(path)
    try:
        application_id = connection.execute("PRAGMA application_id").fetchone()[0]
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        objects = connection.execute(
            """
            SELECT type, name
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
              AND type IN ('table', 'index', 'view', 'trigger')
            """
        ).fetchall()
    finally:
        connection.close()

    assert application_id == 0
    assert user_version == 0
    assert objects == []


def test_concurrent_first_open_bootstraps_exactly_once(tmp_path: Path) -> None:
    _secure_parent(tmp_path)
    path = tmp_path / "concurrent.sqlite3"
    barrier = Barrier(4)

    def open_once(_: int) -> tuple[int, int]:
        barrier.wait()
        with SQLiteDatabase(path).connection() as connection:
            return (
                connection.execute("PRAGMA application_id").fetchone()[0],
                connection.execute("PRAGMA user_version").fetchone()[0],
            )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(open_once, range(4)))

    assert results == [(APPLICATION_ID, SCHEMA_VERSION)] * 4


def test_core_domain_and_application_do_not_depend_on_sqlite_infrastructure() -> None:
    repository_root = Path(__file__).parents[3]
    roots = (
        repository_root / "src/familyos_cli/domain/person",
        repository_root / "src/familyos_cli/domain/family",
        repository_root / "src/familyos_cli/application/person",
        repository_root / "src/familyos_cli/application/family",
        repository_root / "src/familyos_cli/application/ports/person",
        repository_root / "src/familyos_cli/application/ports/family",
    )

    for root in roots:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    assert all(alias.name != "sqlite3" for alias in node.names)
                    assert all(
                        not alias.name.startswith(
                            "familyos_cli.infrastructure.persistence"
                        )
                        for alias in node.names
                    )
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    assert module != "sqlite3"
                    assert not module.startswith(
                        "familyos_cli.infrastructure.persistence"
                    )


# --- proposed addition (Claude round 2): LIKE wildcard must not hide user schema objects ----------


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TRIGGER sqliteXdrop AFTER INSERT ON persons BEGIN DELETE FROM persons; END",
        "CREATE VIEW sqlite0x AS SELECT 1",
        "CREATE INDEX sqlitefidx ON memberships (state)",
    ],
)
def test_names_matching_the_like_wildcard_are_still_validated(tmp_path: Path, statement: str) -> None:
    _secure_parent(tmp_path)
    path = tmp_path / "wildcard.sqlite3"
    with SQLiteDatabase(path).connection():
        pass
    connection = sqlite3.connect(path)
    connection.execute(statement)
    connection.commit()
    connection.close()
    with pytest.raises(SQLiteSchemaError), SQLiteDatabase(path).connection():
        pass


def test_pristine_check_sees_wildcard_named_objects(tmp_path: Path) -> None:
    _secure_parent(tmp_path)
    path = tmp_path / "pristine-view.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE VIEW sqlite0x AS SELECT 1")
    connection.commit()
    connection.close()
    _secure_file(path)
    with pytest.raises(SQLiteSchemaError), SQLiteDatabase(path).connection():
        pass
