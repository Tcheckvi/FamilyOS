"""CLI command context."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path

from familyos_cli.application.build import RunPackageBuildUseCase
from familyos_cli.application.family.activate_membership import ActivateMembership
from familyos_cli.application.family.create_family import CreateFamily
from familyos_cli.application.family.end_membership import EndMembership
from familyos_cli.application.family.end_relationship import EndRelationship
from familyos_cli.application.family.establish_membership import EstablishMembership
from familyos_cli.application.family.establish_relationship import EstablishRelationship
from familyos_cli.application.family.get_family import GetFamily
from familyos_cli.application.family.get_membership import GetMembership
from familyos_cli.application.family.get_relationship import GetRelationship
from familyos_cli.application.family.suspend_membership import SuspendMembership
from familyos_cli.application.generation.domain_generation_catalog_service import (
    DomainGenerationCatalogService,
)
from familyos_cli.application.generation.generation_catalog_service import (
    GenerationCatalogService,
)
from familyos_cli.application.generation.recipe_catalog_service import (
    RecipeCatalogService,
)
from familyos_cli.application.person.create_person import CreatePerson
from familyos_cli.application.person.get_person import GetPerson
from familyos_cli.application.quality.quality_assessment_execution_service import (
    QualityAssessmentExecutionService,
)
from familyos_cli.application.quality.quality_execution_service import (
    QualityExecutionService,
)
from familyos_cli.application.specifications.domain_specification_loader_service import (
    DomainSpecificationLoaderService,
)
from familyos_cli.application.testing import (
    EvaluateTestingEvidenceFreshnessUseCase,
)
from familyos_cli.application.use_cases.check_plugin_compliance import (
    CheckPluginComplianceUseCase,
)
from familyos_cli.application.use_cases.create_artifact import (
    CreateArtifactUseCase,
)
from familyos_cli.application.use_cases.create_domain import (
    CreateDomainUseCase,
)
from familyos_cli.application.use_cases.create_project import (
    CreateProjectUseCase,
)
from familyos_cli.application.use_cases.resolve_plugins import (
    ResolvePluginsUseCase,
)
from familyos_cli.application.validation import RunCiValidationUseCase
from familyos_cli.bootstrap import (
    ApplicationContainer,
    ApplicationFactory,
)


class CommandContext:
    """Shared context for CLI commands."""

    def __init__(
        self,
        container: ApplicationContainer | None = None,
        project_root: Path | None = None,
        core_database_path: Path | None = None,
    ) -> None:
        """Initialize CLI context."""

        if container is not None:
            if core_database_path is not None:
                raise ValueError(
                    "core_database_path cannot be combined with an explicit container",
                )
            self._container = container
        elif project_root is not None:
            if core_database_path is None:
                self._container = ApplicationContainer(
                    project_root=project_root,
                )
            else:
                self._container = ApplicationContainer(
                    project_root=project_root,
                    core_database_path=core_database_path,
                )
        elif core_database_path is not None:
            self._container = ApplicationFactory.create(
                core_database_path=core_database_path,
            )
        else:
            self._container = ApplicationFactory.create()

    @property
    def project_root(self) -> Path:
        """Return the repository root selected by CLI composition."""

        return self._container.project_root

    @cached_property
    def create_project(
        self,
    ) -> CreateProjectUseCase:
        """Provide project creation use case."""

        return self._container.create_project_use_case()

    @cached_property
    def create_artifact(
        self,
    ) -> CreateArtifactUseCase:
        """Provide artifact creation use case."""

        return self._container.create_artifact_use_case()

    @cached_property
    def domain_specification_loader(
        self,
    ) -> DomainSpecificationLoaderService:
        """Provide domain specification loader service."""

        return self._container.domain_specification_loader_service()

    @cached_property
    def create_domain(
        self,
    ) -> CreateDomainUseCase:
        """Provide domain creation use case."""

        return self._container.create_domain_use_case()

    @cached_property
    def create_person(self) -> CreatePerson:
        """Provide the durable Core Product Person creation use case."""

        return self._container.create_person_use_case()

    @cached_property
    def get_person(self) -> GetPerson:
        """Provide the durable Core Product Person query use case."""

        return self._container.get_person_use_case()

    @cached_property
    def create_family(self) -> CreateFamily:
        """Provide the durable Core Product Family creation use case."""

        return self._container.create_family_use_case()

    @cached_property
    def get_family(self) -> GetFamily:
        """Provide the durable Core Product Family query use case."""

        return self._container.get_family_use_case()

    @cached_property
    def establish_membership(self) -> EstablishMembership:
        """Provide durable canonical Membership establishment."""

        return self._container.establish_membership_use_case()

    @cached_property
    def get_membership(self) -> GetMembership:
        """Provide durable canonical Membership retrieval."""

        return self._container.get_membership_use_case()

    @cached_property
    def activate_membership(self) -> ActivateMembership:
        """Provide durable canonical Membership activation."""

        return self._container.activate_membership_use_case()

    @cached_property
    def suspend_membership(self) -> SuspendMembership:
        """Provide durable canonical Membership suspension."""

        return self._container.suspend_membership_use_case()

    @cached_property
    def end_membership(self) -> EndMembership:
        """Provide durable canonical Membership ending."""

        return self._container.end_membership_use_case()

    @cached_property
    def establish_relationship(self) -> EstablishRelationship:
        """Provide durable canonical Relationship establishment."""

        return self._container.establish_relationship_use_case()

    @cached_property
    def get_relationship(self) -> GetRelationship:
        """Provide durable canonical Relationship retrieval."""

        return self._container.get_relationship_use_case()

    @cached_property
    def end_relationship(self) -> EndRelationship:
        """Provide durable canonical Relationship ending."""

        return self._container.end_relationship_use_case()

    @cached_property
    def generation_catalog(
        self,
    ) -> GenerationCatalogService:
        """Provide generation catalog service."""

        return self._container.generation_catalog_service()

    @cached_property
    def domain_generation_catalog(
        self,
    ) -> DomainGenerationCatalogService:
        """Provide domain generation catalog service."""

        return self._container.domain_generation_catalog_service()

    @cached_property
    def recipe_catalog(
        self,
    ) -> RecipeCatalogService:
        """Provide generation recipe catalog service."""

        return self._container.recipe_catalog_service()

    @cached_property
    def resolve_plugins(
        self,
    ) -> ResolvePluginsUseCase:
        """Provide plugin resolution use case."""

        return self._container.resolve_plugins_use_case()

    @cached_property
    def check_plugin_compliance(
        self,
    ) -> CheckPluginComplianceUseCase:
        """Provide plugin compliance checking use case."""

        return self._container.check_plugin_compliance_use_case()

    @cached_property
    def quality_execution(self) -> QualityExecutionService:
        "Provide the governed Phase 12 Quality execution service."
        return self._container.quality_execution_service()

    @cached_property
    def quality_assessment(self) -> QualityAssessmentExecutionService:
        return self._container.quality_assessment_execution_service()

    @cached_property
    def testing_evidence_freshness(
        self,
    ) -> EvaluateTestingEvidenceFreshnessUseCase:
        """Provide the canonical Testing Evidence freshness authority."""

        return self._container.testing_evidence_freshness_use_case()

    @cached_property
    def run_ci_validation(self) -> RunCiValidationUseCase:
        """Provide the canonical CI validation use case."""

        return self._container.run_ci_validation_use_case()

    @cached_property
    def run_package_build(self) -> RunPackageBuildUseCase:
        """Provide the canonical package-build use case."""

        return self._container.run_package_build_use_case()
