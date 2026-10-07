"""End-to-end tests for the public Core Product CLI."""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from familyos_cli.interfaces.cli.app import app

runner = CliRunner()

_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
)


def _extract_uuid(output: str) -> str:
    match = _UUID_PATTERN.search(output)
    assert match is not None
    return match.group(0)


def test_person_create_then_fresh_cli_get_recovers_from_same_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "core.db"

    created = runner.invoke(
        app,
        [
            "core",
            "person",
            "create",
            "--database",
            str(database),
        ],
        catch_exceptions=False,
    )

    assert created.exit_code == 0
    person_id = _extract_uuid(created.stdout)

    recovered = runner.invoke(
        app,
        [
            "core",
            "person",
            "get",
            person_id,
            "--database",
            str(database),
        ],
        catch_exceptions=False,
    )

    assert recovered.exit_code == 0
    assert person_id in recovered.stdout
    assert "Person found" in recovered.stdout


def test_family_create_then_fresh_cli_get_recovers_from_same_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "core.db"

    created = runner.invoke(
        app,
        [
            "core",
            "family",
            "create",
            "--database",
            str(database),
        ],
        catch_exceptions=False,
    )

    assert created.exit_code == 0
    family_id = _extract_uuid(created.stdout)

    recovered = runner.invoke(
        app,
        [
            "core",
            "family",
            "get",
            family_id,
            "--database",
            str(database),
        ],
        catch_exceptions=False,
    )

    assert recovered.exit_code == 0
    assert family_id in recovered.stdout
    assert "Family found" in recovered.stdout


def _create_person(database: Path) -> str:
    result = runner.invoke(
        app,
        [
            "core",
            "person",
            "create",
            "--database",
            str(database),
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    return _extract_uuid(result.stdout)


def _create_family(database: Path) -> str:
    result = runner.invoke(
        app,
        [
            "core",
            "family",
            "create",
            "--database",
            str(database),
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    return _extract_uuid(result.stdout)


def test_membership_establish_get_end_round_trip(
    tmp_path: Path,
) -> None:
    database = tmp_path / "core.db"
    person_id = _create_person(database)
    family_id = _create_family(database)

    established = runner.invoke(
        app,
        [
            "core",
            "membership",
            "establish",
            family_id,
            person_id,
            "--database",
            str(database),
        ],
        catch_exceptions=False,
    )
    assert established.exit_code == 0
    assert "Membership established" in established.stdout
    assert "state=pending" in established.stdout

    recovered = runner.invoke(
        app,
        [
            "core",
            "membership",
            "get",
            family_id,
            person_id,
            "--database",
            str(database),
        ],
        catch_exceptions=False,
    )
    assert recovered.exit_code == 0
    assert "Membership found" in recovered.stdout
    assert "state=pending" in recovered.stdout

    ended = runner.invoke(
        app,
        [
            "core",
            "membership",
            "end",
            family_id,
            person_id,
            "--database",
            str(database),
        ],
        catch_exceptions=False,
    )
    assert ended.exit_code == 0
    assert "Membership ended" in ended.stdout
    assert "state=ended" in ended.stdout

    recovered_ended = runner.invoke(
        app,
        [
            "core",
            "membership",
            "get",
            family_id,
            person_id,
            "--database",
            str(database),
        ],
        catch_exceptions=False,
    )
    assert recovered_ended.exit_code == 0
    assert "state=ended" in recovered_ended.stdout


def test_relationship_establish_get_end_round_trip_with_child_of_normalization(
    tmp_path: Path,
) -> None:
    database = tmp_path / "core.db"
    family_id = _create_family(database)
    low_person_id = _create_person(database)
    high_person_id = _create_person(database)

    established = runner.invoke(
        app,
        [
            "core",
            "relationship",
            "establish",
            family_id,
            high_person_id,
            low_person_id,
            "child_of",
            "--database",
            str(database),
        ],
        catch_exceptions=False,
    )
    assert established.exit_code == 0
    assert "Relationship established" in established.stdout
    assert "parent_of" in established.stdout
    assert "state=established" in established.stdout

    recovered = runner.invoke(
        app,
        [
            "core",
            "relationship",
            "get",
            family_id,
            high_person_id,
            low_person_id,
            "child_of",
            "--database",
            str(database),
        ],
        catch_exceptions=False,
    )
    assert recovered.exit_code == 0
    assert "Relationship found" in recovered.stdout
    assert "parent_of" in recovered.stdout
    assert "state=established" in recovered.stdout

    ended = runner.invoke(
        app,
        [
            "core",
            "relationship",
            "end",
            family_id,
            high_person_id,
            low_person_id,
            "child_of",
            "--database",
            str(database),
        ],
        catch_exceptions=False,
    )
    assert ended.exit_code == 0
    assert "Relationship ended" in ended.stdout
    assert "parent_of" in ended.stdout
    assert "state=ended" in ended.stdout

    recovered_ended = runner.invoke(
        app,
        [
            "core",
            "relationship",
            "get",
            family_id,
            high_person_id,
            low_person_id,
            "child_of",
            "--database",
            str(database),
        ],
        catch_exceptions=False,
    )
    assert recovered_ended.exit_code == 0
    assert "state=ended" in recovered_ended.stdout
