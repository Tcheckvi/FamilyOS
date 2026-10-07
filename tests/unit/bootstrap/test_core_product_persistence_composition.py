"""Unit tests for bounded Core Product durable composition."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from familyos_cli.application.family import (
    ActivateMembership,
    CreateFamily,
    EndMembership,
    EndRelationship,
    EstablishMembership,
    EstablishRelationship,
    GetFamily,
    GetMembership,
    GetRelationship,
    SuspendMembership,
)
from familyos_cli.application.person import CreatePerson, GetPerson
from familyos_cli.bootstrap.application_factory import ApplicationFactory
from familyos_cli.bootstrap.container import ApplicationContainer
from familyos_cli.infrastructure.family.sqlite_family_repository import (
    SQLiteFamilyRepository,
)
from familyos_cli.infrastructure.family.sqlite_membership_repository import (
    SQLiteMembershipRepository,
)
from familyos_cli.infrastructure.family.sqlite_relationship_repository import (
    SQLiteRelationshipRepository,
)
from familyos_cli.infrastructure.persistence import SQLiteDatabase
from familyos_cli.infrastructure.person.sqlite_person_repository import (
    SQLitePersonRepository,
)


def _repository_database(
    repository: object,
) -> SQLiteDatabase:
    return cast(SQLiteDatabase, vars(repository)["_database"])


def test_explicit_path_composes_one_shared_sqlite_database(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "core.sqlite3"
    container = ApplicationContainer(core_database_path=database_path)

    database = container.core_database()
    person_repository = container.core_person_repository()
    family_repository = container.core_family_repository()
    membership_repository = container.core_membership_repository()
    relationship_repository = container.core_relationship_repository()

    assert database.path == database_path
    assert isinstance(person_repository, SQLitePersonRepository)
    assert isinstance(family_repository, SQLiteFamilyRepository)
    assert isinstance(membership_repository, SQLiteMembershipRepository)
    assert isinstance(relationship_repository, SQLiteRelationshipRepository)
    assert _repository_database(person_repository) is database
    assert _repository_database(family_repository) is database
    assert _repository_database(membership_repository) is database
    assert _repository_database(relationship_repository) is database


def test_core_product_use_cases_use_durable_repositories(tmp_path: Path) -> None:
    container = ApplicationContainer(core_database_path=tmp_path / "core.sqlite3")

    create_person = container.create_person_use_case()
    get_person = container.get_person_use_case()
    create_family = container.create_family_use_case()
    get_family = container.get_family_use_case()
    establish_membership = container.establish_membership_use_case()
    get_membership = container.get_membership_use_case()
    activate_membership = container.activate_membership_use_case()
    suspend_membership = container.suspend_membership_use_case()
    end_membership = container.end_membership_use_case()
    establish_relationship = container.establish_relationship_use_case()
    get_relationship = container.get_relationship_use_case()
    end_relationship = container.end_relationship_use_case()

    assert isinstance(create_person, CreatePerson)
    assert isinstance(get_person, GetPerson)
    assert isinstance(create_family, CreateFamily)
    assert isinstance(get_family, GetFamily)
    assert isinstance(establish_membership, EstablishMembership)
    assert isinstance(get_membership, GetMembership)
    assert isinstance(activate_membership, ActivateMembership)
    assert isinstance(suspend_membership, SuspendMembership)
    assert isinstance(end_membership, EndMembership)
    assert isinstance(establish_relationship, EstablishRelationship)
    assert isinstance(get_relationship, GetRelationship)
    assert isinstance(end_relationship, EndRelationship)

    person_repository = container.core_person_repository()
    family_repository = container.core_family_repository()
    membership_repository = container.core_membership_repository()
    relationship_repository = container.core_relationship_repository()

    assert vars(create_person)["_repository"] is person_repository
    assert vars(get_person)["_repository"] is person_repository
    assert vars(create_family)["_repository"] is family_repository
    assert vars(get_family)["_repository"] is family_repository
    assert vars(establish_membership)["_family_repository"] is family_repository
    assert vars(establish_membership)["_person_repository"] is person_repository
    assert vars(establish_membership)["_membership_repository"] is membership_repository
    assert vars(get_membership)["_repository"] is membership_repository
    assert vars(activate_membership)["_repository"] is membership_repository
    assert vars(suspend_membership)["_repository"] is membership_repository
    assert vars(end_membership)["_repository"] is membership_repository
    assert vars(establish_relationship)["_family_repository"] is family_repository
    assert vars(establish_relationship)["_person_repository"] is person_repository
    assert (
        vars(establish_relationship)["_relationship_repository"]
        is relationship_repository
    )
    assert vars(get_relationship)["_repository"] is relationship_repository
    assert vars(end_relationship)["_repository"] is relationship_repository


def test_missing_core_database_path_preserves_container_and_fails_closed(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(project_root=tmp_path)

    assert container.project_root == tmp_path.resolve()

    accessors = (
        container.core_database,
        container.core_person_repository,
        container.core_family_repository,
        container.core_membership_repository,
        container.core_relationship_repository,
        container.create_person_use_case,
        container.get_person_use_case,
        container.create_family_use_case,
        container.get_family_use_case,
        container.establish_membership_use_case,
        container.get_membership_use_case,
        container.activate_membership_use_case,
        container.suspend_membership_use_case,
        container.end_membership_use_case,
        container.establish_relationship_use_case,
        container.get_relationship_use_case,
        container.end_relationship_use_case,
    )

    for accessor in accessors:
        with pytest.raises(
            RuntimeError,
            match="requires an explicit core_database_path",
        ):
            accessor()


def test_application_factory_forwards_explicit_core_database_path(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "core.sqlite3"

    container = ApplicationFactory.create(core_database_path=database_path)

    assert container.core_database().path == database_path


def test_application_factory_no_argument_behavior_remains_available() -> None:
    container = ApplicationFactory.create()

    assert isinstance(container, ApplicationContainer)
