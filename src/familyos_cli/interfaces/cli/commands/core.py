"""Public Core Product CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn
from uuid import UUID

import typer

from familyos_cli.application.family.activate_membership import MembershipNotFoundError
from familyos_cli.application.family.end_relationship import RelationshipNotFoundError
from familyos_cli.application.family.establish_membership import (
    FamilyNotFoundError,
    PersonNotFoundError,
)
from familyos_cli.application.ports.family import (
    MembershipConflictError,
    RelationshipConflictError,
)
from familyos_cli.domain.family import (
    FamilyId,
    InvalidMembershipTransitionError,
    InvalidRelationshipTransitionError,
    RelationshipType,
)
from familyos_cli.domain.person import PersonId
from familyos_cli.interfaces.cli.context import CommandContext
from familyos_cli.interfaces.cli.output import Output

core_app = typer.Typer(
    help="Core Product commands.",
    no_args_is_help=True,
)

person_app = typer.Typer(
    help="Person commands.",
    no_args_is_help=True,
)

family_app = typer.Typer(
    help="Family commands.",
    no_args_is_help=True,
)

membership_app = typer.Typer(
    help="Membership commands.",
    no_args_is_help=True,
)

relationship_app = typer.Typer(
    help="Relationship commands.",
    no_args_is_help=True,
)

core_app.add_typer(
    person_app,
    name="person",
)

core_app.add_typer(
    family_app,
    name="family",
)

core_app.add_typer(
    membership_app,
    name="membership",
)

core_app.add_typer(
    relationship_app,
    name="relationship",
)


def _parse_person_id(raw_value: str) -> PersonId:
    try:
        return PersonId(UUID(raw_value))
    except (TypeError, ValueError, AttributeError) as error:
        raise typer.BadParameter(
            "person_id must be a valid UUID",
            param_hint="PERSON_ID",
        ) from error


def _parse_family_id(raw_value: str) -> FamilyId:
    try:
        return FamilyId(UUID(raw_value))
    except (TypeError, ValueError, AttributeError) as error:
        raise typer.BadParameter(
            "family_id must be a valid UUID version 4",
            param_hint="FAMILY_ID",
        ) from error


def _parse_relationship_type(raw_value: str) -> RelationshipType:
    try:
        return RelationshipType(raw_value)
    except (TypeError, ValueError) as error:
        allowed = ", ".join(member.value for member in RelationshipType)
        raise typer.BadParameter(
            f"relationship_type must be one of: {allowed}",
            param_hint="RELATIONSHIP_TYPE",
        ) from error


def _membership_identity(family_id: FamilyId, person_id: PersonId) -> str:
    return f"{family_id}:{person_id}"


def _relationship_identity(
    family_id: FamilyId,
    source_person_id: PersonId,
    target_person_id: PersonId,
    relationship_type: RelationshipType,
) -> str:
    return (
        f"{family_id}:{source_person_id}:{target_person_id}:"
        f"{relationship_type.value}"
    )


def _command_error(error: Exception) -> NoReturn:
    Output.error(str(error))
    raise typer.Exit(code=1)


@person_app.command(name="create")
def create_person(
    database: Annotated[
        Path,
        typer.Option(
            "--database",
            help="Explicit SQLite database path for Core Product durable state.",
        ),
    ],
) -> None:
    """Create one durable canonical Person."""

    result = CommandContext(
        core_database_path=database,
    ).create_person.execute()

    Output.success(
        f"Person created: {result.person.person_id}",
    )


@person_app.command(name="get")
def get_person(
    person_id: Annotated[
        str,
        typer.Argument(
            ...,
            help="Canonical Person UUID.",
        ),
    ],
    database: Annotated[
        Path,
        typer.Option(
            "--database",
            help="Explicit SQLite database path for Core Product durable state.",
        ),
    ],
) -> None:
    """Get one durable canonical Person."""

    canonical_person_id = _parse_person_id(person_id)
    person = CommandContext(
        core_database_path=database,
    ).get_person.execute(canonical_person_id)

    if person is None:
        Output.error(
            f'Person "{canonical_person_id}" not found.',
        )
        raise typer.Exit(code=1)

    Output.info(
        f"Person found: {person.person_id}",
    )


@family_app.command(name="create")
def create_family(
    database: Annotated[
        Path,
        typer.Option(
            "--database",
            help="Explicit SQLite database path for Core Product durable state.",
        ),
    ],
) -> None:
    """Create one durable canonical Family."""

    result = CommandContext(
        core_database_path=database,
    ).create_family.execute()

    Output.success(
        f"Family created: {result.family.family_id}",
    )


@family_app.command(name="get")
def get_family(
    family_id: Annotated[
        str,
        typer.Argument(
            ...,
            help="Canonical Family UUID version 4.",
        ),
    ],
    database: Annotated[
        Path,
        typer.Option(
            "--database",
            help="Explicit SQLite database path for Core Product durable state.",
        ),
    ],
) -> None:
    """Get one durable canonical Family."""

    canonical_family_id = _parse_family_id(family_id)
    family = CommandContext(
        core_database_path=database,
    ).get_family.execute(canonical_family_id)

    if family is None:
        Output.error(
            f'Family "{canonical_family_id}" not found.',
        )
        raise typer.Exit(code=1)

    Output.info(
        f"Family found: {family.family_id}",
    )


@family_app.command(name="resolve-boundary")
def resolve_family_boundary(
    family_id: Annotated[
        str,
        typer.Argument(
            ...,
            help="Canonical Family UUID version 4.",
        ),
    ],
    database: Annotated[
        Path,
        typer.Option(
            "--database",
            help="Explicit SQLite database path for Core Product durable state.",
        ),
    ],
) -> None:
    """Resolve one durable canonical Family boundary identity."""

    canonical_family_id = _parse_family_id(family_id)
    boundary_id = CommandContext(
        core_database_path=database,
    ).resolve_family_boundary.execute(canonical_family_id)

    if boundary_id is None:
        Output.error(
            f'Family "{canonical_family_id}" not found.',
        )
        raise typer.Exit(code=1)

    Output.success(
        f"Family boundary resolved: {boundary_id}",
    )


@membership_app.command(name="establish")
def establish_membership(
    family_id: Annotated[
        str,
        typer.Argument(..., help="Canonical Family UUID version 4."),
    ],
    person_id: Annotated[
        str,
        typer.Argument(..., help="Canonical Person UUID."),
    ],
    database: Annotated[
        Path,
        typer.Option(
            "--database",
            help="Explicit SQLite database path for Core Product durable state.",
        ),
    ],
) -> None:
    """Establish one durable canonical Membership."""

    canonical_family_id = _parse_family_id(family_id)
    canonical_person_id = _parse_person_id(person_id)

    try:
        result = CommandContext(
            core_database_path=database,
        ).establish_membership.execute(
            canonical_family_id,
            canonical_person_id,
        )
    except (
        FamilyNotFoundError,
        PersonNotFoundError,
        MembershipConflictError,
    ) as error:
        _command_error(error)

    membership = result.membership
    Output.success(
        "Membership established: "
        f"{_membership_identity(membership.family_id, membership.person_id)} "
        f"state={membership.state.value}",
    )


@membership_app.command(name="get")
def get_membership(
    family_id: Annotated[
        str,
        typer.Argument(..., help="Canonical Family UUID version 4."),
    ],
    person_id: Annotated[
        str,
        typer.Argument(..., help="Canonical Person UUID."),
    ],
    database: Annotated[
        Path,
        typer.Option(
            "--database",
            help="Explicit SQLite database path for Core Product durable state.",
        ),
    ],
) -> None:
    """Get one durable canonical Membership."""

    canonical_family_id = _parse_family_id(family_id)
    canonical_person_id = _parse_person_id(person_id)
    membership = CommandContext(
        core_database_path=database,
    ).get_membership.execute(
        canonical_family_id,
        canonical_person_id,
    )

    if membership is None:
        Output.error(
            "Membership "
            f'"{_membership_identity(canonical_family_id, canonical_person_id)}" '
            "not found.",
        )
        raise typer.Exit(code=1)

    Output.info(
        "Membership found: "
        f"{_membership_identity(membership.family_id, membership.person_id)} "
        f"state={membership.state.value}",
    )


@membership_app.command(name="activate")
def activate_membership(
    family_id: Annotated[
        str,
        typer.Argument(..., help="Canonical Family UUID version 4."),
    ],
    person_id: Annotated[
        str,
        typer.Argument(..., help="Canonical Person UUID."),
    ],
    database: Annotated[
        Path,
        typer.Option(
            "--database",
            help="Explicit SQLite database path for Core Product durable state.",
        ),
    ],
) -> None:
    """Activate or reactivate one durable canonical Membership."""

    canonical_family_id = _parse_family_id(family_id)
    canonical_person_id = _parse_person_id(person_id)

    try:
        result = CommandContext(
            core_database_path=database,
        ).activate_membership.execute(
            canonical_family_id,
            canonical_person_id,
        )
    except (
        MembershipNotFoundError,
        InvalidMembershipTransitionError,
        MembershipConflictError,
    ) as error:
        _command_error(error)

    membership = result.membership
    Output.success(
        "Membership activated: "
        f"{_membership_identity(membership.family_id, membership.person_id)} "
        f"state={membership.state.value}",
    )


@membership_app.command(name="suspend")
def suspend_membership(
    family_id: Annotated[
        str,
        typer.Argument(..., help="Canonical Family UUID version 4."),
    ],
    person_id: Annotated[
        str,
        typer.Argument(..., help="Canonical Person UUID."),
    ],
    database: Annotated[
        Path,
        typer.Option(
            "--database",
            help="Explicit SQLite database path for Core Product durable state.",
        ),
    ],
) -> None:
    """Suspend one durable canonical Membership."""

    canonical_family_id = _parse_family_id(family_id)
    canonical_person_id = _parse_person_id(person_id)

    try:
        result = CommandContext(
            core_database_path=database,
        ).suspend_membership.execute(
            canonical_family_id,
            canonical_person_id,
        )
    except (
        MembershipNotFoundError,
        InvalidMembershipTransitionError,
        MembershipConflictError,
    ) as error:
        _command_error(error)

    membership = result.membership
    Output.success(
        "Membership suspended: "
        f"{_membership_identity(membership.family_id, membership.person_id)} "
        f"state={membership.state.value}",
    )


@membership_app.command(name="end")
def end_membership(
    family_id: Annotated[
        str,
        typer.Argument(..., help="Canonical Family UUID version 4."),
    ],
    person_id: Annotated[
        str,
        typer.Argument(..., help="Canonical Person UUID."),
    ],
    database: Annotated[
        Path,
        typer.Option(
            "--database",
            help="Explicit SQLite database path for Core Product durable state.",
        ),
    ],
) -> None:
    """End one durable canonical Membership."""

    canonical_family_id = _parse_family_id(family_id)
    canonical_person_id = _parse_person_id(person_id)

    try:
        result = CommandContext(
            core_database_path=database,
        ).end_membership.execute(
            canonical_family_id,
            canonical_person_id,
        )
    except (
        MembershipNotFoundError,
        InvalidMembershipTransitionError,
        MembershipConflictError,
    ) as error:
        _command_error(error)

    membership = result.membership
    Output.success(
        "Membership ended: "
        f"{_membership_identity(membership.family_id, membership.person_id)} "
        f"state={membership.state.value}",
    )


@relationship_app.command(name="establish")
def establish_relationship(
    family_id: Annotated[
        str,
        typer.Argument(..., help="Canonical Family UUID version 4."),
    ],
    source_person_id: Annotated[
        str,
        typer.Argument(..., help="Source Person UUID."),
    ],
    target_person_id: Annotated[
        str,
        typer.Argument(..., help="Target Person UUID."),
    ],
    relationship_type: Annotated[
        str,
        typer.Argument(
            ...,
            help="Relationship type: parent_of, child_of, spouse_of, sibling_of.",
        ),
    ],
    database: Annotated[
        Path,
        typer.Option(
            "--database",
            help="Explicit SQLite database path for Core Product durable state.",
        ),
    ],
) -> None:
    """Establish one durable canonical Relationship."""

    canonical_family_id = _parse_family_id(family_id)
    canonical_source_person_id = _parse_person_id(source_person_id)
    canonical_target_person_id = _parse_person_id(target_person_id)
    canonical_relationship_type = _parse_relationship_type(relationship_type)

    try:
        result = CommandContext(
            core_database_path=database,
        ).establish_relationship.execute(
            canonical_family_id,
            canonical_source_person_id,
            canonical_target_person_id,
            canonical_relationship_type,
        )
    except (
        FamilyNotFoundError,
        PersonNotFoundError,
        RelationshipConflictError,
        ValueError,
    ) as error:
        _command_error(error)

    relationship = result.relationship
    Output.success(
        "Relationship established: "
        f"{_relationship_identity(
            relationship.family_id,
            relationship.source_person_id,
            relationship.target_person_id,
            relationship.relationship_type,
        )} "
        f"state={relationship.state.value}",
    )


@relationship_app.command(name="get")
def get_relationship(
    family_id: Annotated[
        str,
        typer.Argument(..., help="Canonical Family UUID version 4."),
    ],
    source_person_id: Annotated[
        str,
        typer.Argument(..., help="Source Person UUID."),
    ],
    target_person_id: Annotated[
        str,
        typer.Argument(..., help="Target Person UUID."),
    ],
    relationship_type: Annotated[
        str,
        typer.Argument(
            ...,
            help="Relationship type: parent_of, child_of, spouse_of, sibling_of.",
        ),
    ],
    database: Annotated[
        Path,
        typer.Option(
            "--database",
            help="Explicit SQLite database path for Core Product durable state.",
        ),
    ],
) -> None:
    """Get one durable canonical Relationship."""

    canonical_family_id = _parse_family_id(family_id)
    canonical_source_person_id = _parse_person_id(source_person_id)
    canonical_target_person_id = _parse_person_id(target_person_id)
    canonical_relationship_type = _parse_relationship_type(relationship_type)

    try:
        relationship = CommandContext(
            core_database_path=database,
        ).get_relationship.execute(
            canonical_family_id,
            canonical_source_person_id,
            canonical_target_person_id,
            canonical_relationship_type,
        )
    except ValueError as error:
        _command_error(error)

    if relationship is None:
        Output.error(
            "Relationship "
            f'"{_relationship_identity(
                canonical_family_id,
                canonical_source_person_id,
                canonical_target_person_id,
                canonical_relationship_type,
            )}" not found.',
        )
        raise typer.Exit(code=1)

    Output.info(
        "Relationship found: "
        f"{_relationship_identity(
            relationship.family_id,
            relationship.source_person_id,
            relationship.target_person_id,
            relationship.relationship_type,
        )} "
        f"state={relationship.state.value}",
    )


@relationship_app.command(name="end")
def end_relationship(
    family_id: Annotated[
        str,
        typer.Argument(..., help="Canonical Family UUID version 4."),
    ],
    source_person_id: Annotated[
        str,
        typer.Argument(..., help="Source Person UUID."),
    ],
    target_person_id: Annotated[
        str,
        typer.Argument(..., help="Target Person UUID."),
    ],
    relationship_type: Annotated[
        str,
        typer.Argument(
            ...,
            help="Relationship type: parent_of, child_of, spouse_of, sibling_of.",
        ),
    ],
    database: Annotated[
        Path,
        typer.Option(
            "--database",
            help="Explicit SQLite database path for Core Product durable state.",
        ),
    ],
) -> None:
    """End one durable canonical Relationship."""

    canonical_family_id = _parse_family_id(family_id)
    canonical_source_person_id = _parse_person_id(source_person_id)
    canonical_target_person_id = _parse_person_id(target_person_id)
    canonical_relationship_type = _parse_relationship_type(relationship_type)

    try:
        result = CommandContext(
            core_database_path=database,
        ).end_relationship.execute(
            canonical_family_id,
            canonical_source_person_id,
            canonical_target_person_id,
            canonical_relationship_type,
        )
    except (
        RelationshipNotFoundError,
        InvalidRelationshipTransitionError,
        RelationshipConflictError,
        ValueError,
    ) as error:
        _command_error(error)

    relationship = result.relationship
    Output.success(
        "Relationship ended: "
        f"{_relationship_identity(
            relationship.family_id,
            relationship.source_person_id,
            relationship.target_person_id,
            relationship.relationship_type,
        )} "
        f"state={relationship.state.value}",
    )
