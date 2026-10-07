"""Application factory."""

from __future__ import annotations

from pathlib import Path

from familyos_cli.bootstrap.container import (
    ApplicationContainer,
)


class ApplicationFactory:
    """Create application containers."""

    @staticmethod
    def create(
        *,
        core_database_path: Path | None = None,
    ) -> ApplicationContainer:
        """Create an application container."""

        return ApplicationContainer(core_database_path=core_database_path)
