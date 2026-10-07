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
