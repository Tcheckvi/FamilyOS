"""Unit tests for public Core Product CLI commands."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID, uuid1

from typer.testing import CliRunner

from familyos_cli.domain.family import Family, FamilyId
from familyos_cli.domain.person import Person, PersonId
from familyos_cli.interfaces.cli.app import app
from familyos_cli.interfaces.cli.commands.core import core_app

runner = CliRunner()

PERSON_UUID = UUID("11111111-1111-4111-8111-111111111111")
FAMILY_UUID = UUID("22222222-2222-4222-8222-222222222222")


def test_root_should_register_core_command_group() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "core" in result.stdout
    assert "Core Product commands." in result.stdout


def test_person_create_requires_explicit_database() -> None:
    result = runner.invoke(core_app, ["person", "create"])

    assert result.exit_code == 2
    assert "--database" in result.output


@patch("familyos_cli.interfaces.cli.commands.core.CommandContext")
def test_person_create_delegates_to_context(
    context_type: Mock,
    tmp_path: Path,
) -> None:
    database = tmp_path / "core.db"
    person = Person(PersonId(PERSON_UUID))
    context = context_type.return_value
    context.create_person.execute.return_value = SimpleNamespace(person=person)

    result = runner.invoke(
        core_app,
        ["person", "create", "--database", str(database)],
    )

    assert result.exit_code == 0
    assert str(PERSON_UUID) in result.stdout
    context_type.assert_called_once_with(core_database_path=database)
    context.create_person.execute.assert_called_once_with()


@patch("familyos_cli.interfaces.cli.commands.core.CommandContext")
def test_person_get_returns_nonzero_for_absence(
    context_type: Mock,
    tmp_path: Path,
) -> None:
    database = tmp_path / "core.db"
    context = context_type.return_value
    context.get_person.execute.return_value = None

    result = runner.invoke(
        core_app,
        [
            "person",
            "get",
            str(PERSON_UUID),
            "--database",
            str(database),
        ],
    )

    assert result.exit_code == 1
    assert "not found" in result.output
    context.get_person.execute.assert_called_once_with(PersonId(PERSON_UUID))


def test_person_get_rejects_invalid_uuid(tmp_path: Path) -> None:
    result = runner.invoke(
        core_app,
        [
            "person",
            "get",
            "not-a-uuid",
            "--database",
            str(tmp_path / "core.db"),
        ],
    )

    assert result.exit_code == 2
    assert "person_id must be a valid UUID" in result.output


@patch("familyos_cli.interfaces.cli.commands.core.CommandContext")
def test_family_create_delegates_to_context(
    context_type: Mock,
    tmp_path: Path,
) -> None:
    database = tmp_path / "core.db"
    family = Family(FamilyId(FAMILY_UUID))
    context = context_type.return_value
    context.create_family.execute.return_value = SimpleNamespace(family=family)

    result = runner.invoke(
        core_app,
        ["family", "create", "--database", str(database)],
    )

    assert result.exit_code == 0
    assert str(FAMILY_UUID) in result.stdout
    context_type.assert_called_once_with(core_database_path=database)
    context.create_family.execute.assert_called_once_with()


@patch("familyos_cli.interfaces.cli.commands.core.CommandContext")
def test_family_get_returns_existing_family(
    context_type: Mock,
    tmp_path: Path,
) -> None:
    database = tmp_path / "core.db"
    family_id = FamilyId(FAMILY_UUID)
    family = Family(family_id)
    context = context_type.return_value
    context.get_family.execute.return_value = family

    result = runner.invoke(
        core_app,
        [
            "family",
            "get",
            str(FAMILY_UUID),
            "--database",
            str(database),
        ],
    )

    assert result.exit_code == 0
    assert str(FAMILY_UUID) in result.stdout
    context.get_family.execute.assert_called_once_with(family_id)


def test_family_get_rejects_non_v4_uuid(tmp_path: Path) -> None:
    result = runner.invoke(
        core_app,
        [
            "family",
            "get",
            str(uuid1()),
            "--database",
            str(tmp_path / "core.db"),
        ],
    )

    assert result.exit_code == 2
    assert "family_id must be a valid UUID version 4" in result.output
