"""Integration proof for Core Product durable recovery across containers."""

from __future__ import annotations

from pathlib import Path

import pytest

from familyos_cli.application.ports.family import (
    MembershipConflictError,
    RelationshipConflictError,
)
from familyos_cli.bootstrap.container import ApplicationContainer
from familyos_cli.domain.family import (
    MembershipState,
    RelationshipState,
    RelationshipType,
)


def test_new_container_recovers_complete_core_product_state(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    database_path = tmp_path / "core.sqlite3"

    first_container = ApplicationContainer(core_database_path=database_path)

    first_person = first_container.create_person_use_case().execute().person
    second_person = first_container.create_person_use_case().execute().person
    family = first_container.create_family_use_case().execute().family

    membership = first_container.establish_membership_use_case().execute(
        family.family_id,
        first_person.person_id,
    ).membership
    relationship = first_container.establish_relationship_use_case().execute(
        family.family_id,
        first_person.person_id,
        second_person.person_id,
        RelationshipType.PARENT_OF,
    ).relationship

    ended_membership = first_container.end_membership_use_case().execute(
        family.family_id,
        first_person.person_id,
    ).membership
    ended_relationship = first_container.end_relationship_use_case().execute(
        family.family_id,
        first_person.person_id,
        second_person.person_id,
        RelationshipType.PARENT_OF,
    ).relationship

    assert membership.state is MembershipState.PENDING
    assert relationship.state is RelationshipState.ESTABLISHED
    assert ended_membership.state is MembershipState.ENDED
    assert ended_relationship.state is RelationshipState.ENDED

    del first_container

    second_container = ApplicationContainer(core_database_path=database_path)

    assert (
        second_container.get_person_use_case().execute(first_person.person_id)
        == first_person
    )
    assert (
        second_container.get_person_use_case().execute(second_person.person_id)
        == second_person
    )
    assert second_container.get_family_use_case().execute(family.family_id) == family
    assert (
        second_container.get_membership_use_case().execute(
            family.family_id,
            first_person.person_id,
        )
        == ended_membership
    )
    assert (
        second_container.get_relationship_use_case().execute(
            family.family_id,
            first_person.person_id,
            second_person.person_id,
            RelationshipType.PARENT_OF,
        )
        == ended_relationship
    )

    with pytest.raises(MembershipConflictError):
        second_container.establish_membership_use_case().execute(
            family.family_id,
            first_person.person_id,
        )

    with pytest.raises(RelationshipConflictError):
        second_container.establish_relationship_use_case().execute(
            family.family_id,
            first_person.person_id,
            second_person.person_id,
            RelationshipType.PARENT_OF,
        )
