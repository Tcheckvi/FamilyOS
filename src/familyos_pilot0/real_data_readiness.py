"""Synthetic-only readiness model for a future first real-data slice."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from .errors import FirstRealDataSliceValidationError

ALLOWED_PAYLOAD_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "source_type",
        "selected_text_body",
        "event_relevant_timestamp",
        "pseudonymous_participant_reference",
        "ephemeral_correlation_identifier",
    }
)

REQUIRED_PAYLOAD_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "source_type",
        "selected_text_body",
        "pseudonymous_participant_reference",
        "ephemeral_correlation_identifier",
    }
)


def _require_nonblank(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise FirstRealDataSliceValidationError(
            f"{name} must not be blank"
        )
    return normalized


class FirstSliceReadinessState(StrEnum):
    """Possible M8 readiness decisions."""

    READY_FOR_SEPARATE_EXECUTION_AUTHORIZATION = (
        "READY_FOR_SEPARATE_EXECUTION_AUTHORIZATION"
    )
    DENY = "DENY"
    ABORT = "ABORT"


@dataclass(frozen=True)
class SourceSelectionPreflight:
    """Metadata-only boundary for one future manually selected source item."""

    source_type: str
    selected_item_count: int
    manual_selection_confirmed: bool
    ephemeral_correlation_identifier: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_type",
            _require_nonblank("source_type", self.source_type),
        )
        object.__setattr__(
            self,
            "ephemeral_correlation_identifier",
            _require_nonblank(
                "ephemeral_correlation_identifier",
                self.ephemeral_correlation_identifier,
            ),
        )
        if self.selected_item_count < 0:
            raise FirstRealDataSliceValidationError(
                "selected_item_count must be non-negative"
            )


@dataclass(frozen=True)
class ParticipantEligibilityPreflight:
    """Synthetic participant-eligibility facts used by the M8 rehearsal."""

    pseudonymous_participant_reference: str
    adult_confirmed: bool
    active_consent: bool
    revoked: bool
    minor_data_detected: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "pseudonymous_participant_reference",
            _require_nonblank(
                "pseudonymous_participant_reference",
                self.pseudonymous_participant_reference,
            ),
        )


@dataclass(frozen=True)
class PayloadMinimizationPreflight:
    """Field-name-only payload contract; carries no selected source content."""

    payload_field_names: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized = tuple(
            _require_nonblank("payload_field_name", name)
            for name in self.payload_field_names
        )
        if len(set(normalized)) != len(normalized):
            raise FirstRealDataSliceValidationError(
                "payload_field_names must not contain duplicates"
            )
        object.__setattr__(
            self,
            "payload_field_names",
            normalized,
        )


@dataclass(frozen=True)
class ProviderProjectPreflight:
    """Offline evidence about the future provider/project boundary."""

    dedicated_familyos_project_confirmed: bool
    store_disabled_confirmed: bool
    hosted_tools_disabled_confirmed: bool
    provider_sharing_disabled_confirmed: bool
    provider_configuration_mutation_requested: bool = False


@dataclass(frozen=True)
class OperatorExecutionContract:
    """Dry-run contract requiring a later, separate execution authorization."""

    operator_checklist_complete: bool
    separate_execution_authorization_required: bool
    execution_authorization_token_present: bool = False


@dataclass(frozen=True)
class EvidenceRequirementsPreflight:
    """Readiness evidence required before a future first slice."""

    audit_evidence_model_complete: bool
    retention_requirement_defined: bool
    deletion_requirement_defined: bool
    revocation_requirement_defined: bool


@dataclass(frozen=True)
class FirstRealDataSliceReadinessRequest:
    """Synthetic aggregate used only to assess future execution readiness."""

    source: SourceSelectionPreflight
    participant: ParticipantEligibilityPreflight
    payload: PayloadMinimizationPreflight
    provider: ProviderProjectPreflight
    operator: OperatorExecutionContract
    evidence: EvidenceRequirementsPreflight


@dataclass(frozen=True)
class FirstSliceReadinessAuditEvidence:
    """Raw-content-free evidence for one synthetic readiness rehearsal."""

    source_type: str
    ephemeral_correlation_identifier: str
    pseudonymous_participant_reference: str
    state: FirstSliceReadinessState
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class FirstRealDataSliceReadinessDecision:
    """M8 readiness result; never grants real-data execution authority."""

    state: FirstSliceReadinessState
    reasons: tuple[str, ...]
    audit_evidence: FirstSliceReadinessAuditEvidence

    @property
    def ready_for_separate_execution_authorization(self) -> bool:
        """Return whether all M8 readiness gates passed."""
        return (
            self.state
            is FirstSliceReadinessState.READY_FOR_SEPARATE_EXECUTION_AUTHORIZATION
        )

    @property
    def execution_authorized(self) -> bool:
        """M8 readiness never authorizes real-data execution."""
        return False


def evaluate_first_real_data_slice_readiness(
    request: FirstRealDataSliceReadinessRequest,
) -> FirstRealDataSliceReadinessDecision:
    """Evaluate synthetic first-slice readiness with fail-closed semantics."""

    reasons: list[str] = []

    if request.participant.minor_data_detected:
        reasons.append("minor_data_detected_abort_required")
        state = FirstSliceReadinessState.ABORT
    else:
        if request.source.selected_item_count != 1:
            reasons.append("exactly_one_source_item_required")

        if not request.source.manual_selection_confirmed:
            reasons.append("manual_source_selection_not_confirmed")

        if not request.participant.adult_confirmed:
            reasons.append("adult_participant_not_confirmed")

        if not request.participant.active_consent:
            reasons.append("active_consent_missing")

        if request.participant.revoked:
            reasons.append("participant_revoked")

        payload_fields = frozenset(request.payload.payload_field_names)
        if not REQUIRED_PAYLOAD_FIELD_NAMES.issubset(payload_fields):
            reasons.append("required_minimal_payload_field_missing")

        if not payload_fields.issubset(ALLOWED_PAYLOAD_FIELD_NAMES):
            reasons.append("payload_contains_noncanonical_field")

        if not request.provider.dedicated_familyos_project_confirmed:
            reasons.append("dedicated_familyos_project_not_confirmed")

        if not request.provider.store_disabled_confirmed:
            reasons.append("provider_store_disabled_not_confirmed")

        if not request.provider.hosted_tools_disabled_confirmed:
            reasons.append("hosted_tools_disabled_not_confirmed")

        if not request.provider.provider_sharing_disabled_confirmed:
            reasons.append("provider_sharing_disabled_not_confirmed")

        if request.provider.provider_configuration_mutation_requested:
            reasons.append("provider_configuration_mutation_forbidden")

        if not request.operator.operator_checklist_complete:
            reasons.append("operator_checklist_incomplete")

        if not request.operator.separate_execution_authorization_required:
            reasons.append("separate_execution_authorization_not_required")

        if request.operator.execution_authorization_token_present:
            reasons.append("execution_token_must_not_be_bound_during_m8_readiness")

        evidence_checks = (
            (
                request.evidence.audit_evidence_model_complete,
                "audit_evidence_model_incomplete",
            ),
            (
                request.evidence.retention_requirement_defined,
                "retention_requirement_missing",
            ),
            (
                request.evidence.deletion_requirement_defined,
                "deletion_requirement_missing",
            ),
            (
                request.evidence.revocation_requirement_defined,
                "revocation_requirement_missing",
            ),
        )
        for satisfied, reason in evidence_checks:
            if not satisfied:
                reasons.append(reason)

        state = (
            FirstSliceReadinessState.DENY
            if reasons
            else FirstSliceReadinessState.READY_FOR_SEPARATE_EXECUTION_AUTHORIZATION
        )

    reasons_tuple = tuple(reasons)
    audit = FirstSliceReadinessAuditEvidence(
        source_type=request.source.source_type,
        ephemeral_correlation_identifier=(
            request.source.ephemeral_correlation_identifier
        ),
        pseudonymous_participant_reference=(
            request.participant.pseudonymous_participant_reference
        ),
        state=state,
        reasons=reasons_tuple,
    )

    return FirstRealDataSliceReadinessDecision(
        state=state,
        reasons=reasons_tuple,
        audit_evidence=audit,
    )
