"""Public Core Product CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer

from familyos_cli.domain.family import FamilyId
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

core_app.add_typer(
    person_app,
    name="person",
)

core_app.add_typer(
    family_app,
    name="family",
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
