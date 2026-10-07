"""Unit tests for Core Product CLI context composition."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from familyos_cli.interfaces.cli.context import CommandContext


@patch("familyos_cli.interfaces.cli.context.ApplicationFactory.create")
def test_core_database_path_is_forwarded_to_application_factory(
    create: Mock,
    tmp_path: Path,
) -> None:
    database = tmp_path / "core.db"
    create.return_value = Mock()

    CommandContext(core_database_path=database)

    create.assert_called_once_with(core_database_path=database)


@patch("familyos_cli.interfaces.cli.context.ApplicationFactory.create")
def test_no_arg_context_preserves_existing_factory_behavior(
    create: Mock,
) -> None:
    create.return_value = Mock()

    CommandContext()

    create.assert_called_once_with()


@patch("familyos_cli.interfaces.cli.context.ApplicationContainer")
def test_project_root_and_core_database_path_are_forwarded_together(
    container_type: Mock,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    database = tmp_path / "core.db"

    CommandContext(
        project_root=project_root,
        core_database_path=database,
    )

    container_type.assert_called_once_with(
        project_root=project_root,
        core_database_path=database,
    )


def test_explicit_container_rejects_separate_core_database_path(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="core_database_path cannot be combined",
    ):
        CommandContext(
            container=Mock(),
            core_database_path=tmp_path / "core.db",
        )


def test_core_product_use_cases_are_exposed_and_cached() -> None:
    container = Mock()
    create_person = Mock()
    get_person = Mock()
    create_family = Mock()
    get_family = Mock()
    establish_membership = Mock()
    get_membership = Mock()
    activate_membership = Mock()
    suspend_membership = Mock()
    end_membership = Mock()
    establish_relationship = Mock()
    get_relationship = Mock()
    end_relationship = Mock()

    container.create_person_use_case.return_value = create_person
    container.get_person_use_case.return_value = get_person
    container.create_family_use_case.return_value = create_family
    container.get_family_use_case.return_value = get_family
    container.establish_membership_use_case.return_value = establish_membership
    container.get_membership_use_case.return_value = get_membership
    container.activate_membership_use_case.return_value = activate_membership
    container.suspend_membership_use_case.return_value = suspend_membership
    container.end_membership_use_case.return_value = end_membership
    container.establish_relationship_use_case.return_value = establish_relationship
    container.get_relationship_use_case.return_value = get_relationship
    container.end_relationship_use_case.return_value = end_relationship

    context = CommandContext(container=container)

    assert context.create_person is create_person
    assert context.create_person is create_person
    assert context.get_person is get_person
    assert context.get_person is get_person
    assert context.create_family is create_family
    assert context.create_family is create_family
    assert context.get_family is get_family
    assert context.get_family is get_family
    assert context.establish_membership is establish_membership
    assert context.establish_membership is establish_membership
    assert context.get_membership is get_membership
    assert context.get_membership is get_membership
    assert context.activate_membership is activate_membership
    assert context.activate_membership is activate_membership
    assert context.suspend_membership is suspend_membership
    assert context.suspend_membership is suspend_membership
    assert context.end_membership is end_membership
    assert context.end_membership is end_membership
    assert context.establish_relationship is establish_relationship
    assert context.establish_relationship is establish_relationship
    assert context.get_relationship is get_relationship
    assert context.get_relationship is get_relationship
    assert context.end_relationship is end_relationship
    assert context.end_relationship is end_relationship

    container.create_person_use_case.assert_called_once_with()
    container.get_person_use_case.assert_called_once_with()
    container.create_family_use_case.assert_called_once_with()
    container.get_family_use_case.assert_called_once_with()
    container.establish_membership_use_case.assert_called_once_with()
    container.get_membership_use_case.assert_called_once_with()
    container.activate_membership_use_case.assert_called_once_with()
    container.suspend_membership_use_case.assert_called_once_with()
    container.end_membership_use_case.assert_called_once_with()
    container.establish_relationship_use_case.assert_called_once_with()
    container.get_relationship_use_case.assert_called_once_with()
    container.end_relationship_use_case.assert_called_once_with()
