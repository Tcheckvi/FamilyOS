"""Synthetic-only execution-authorization readiness for Pilot0 M9."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

from .errors import ExecutionAuthorizationValidationError
from .real_data_readiness import (
    ALLOWED_PAYLOAD_FIELD_NAMES,
    REQUIRED_PAYLOAD_FIELD_NAMES,
)


def _require_nonblank(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ExecutionAuthorizationValidationError(f"{name} must not be blank")
    return normalized


def _require_nonnegative(name: str, value: int) -> int:
    if value < 0:
        raise ExecutionAuthorizationValidationError(f"{name} must be non-negative")
    return value


class ExecutionAuthorizationReadinessState(StrEnum):
    """Possible M9 authorization-readiness decisions."""

    READY_TO_ISSUE_SINGLE_USE_AUTHORIZATION = "READY_TO_ISSUE_SINGLE_USE_AUTHORIZATION"
    DENY = "DENY"
    ABORT = "ABORT"


class SingleUseTokenValidationState(StrEnum):
    """Possible validation outcomes for a synthetic single-use token."""

    VALID_FOR_SEPARATE_PRE_SEND_CONFIRMATION = "VALID_FOR_SEPARATE_PRE_SEND_CONFIRMATION"
    REFUSE_EXPIRED = "REFUSE_EXPIRED"
    REFUSE_REPLAY = "REFUSE_REPLAY"
    REFUSE_REVOKED = "REFUSE_REVOKED"
    REFUSE_SCOPE_MISMATCH = "REFUSE_SCOPE_MISMATCH"


@dataclass(frozen=True)
class ManualSourceAuthorizationDescriptor:
    """Metadata-only descriptor for one future manually selected source."""

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
            "selected_item_count",
            _require_nonnegative(
                "selected_item_count",
                self.selected_item_count,
            ),
        )
        object.__setattr__(
            self,
            "ephemeral_correlation_identifier",
            _require_nonblank(
                "ephemeral_correlation_identifier",
                self.ephemeral_correlation_identifier,
            ),
        )


@dataclass(frozen=True)
class ParticipantAuthorizationEvidence:
    """Synthetic adult consent, eligibility, and revocation evidence."""

    pseudonymous_participant_reference: str
    consent_evidence_identifier: str
    eligibility_evidence_identifier: str
    adult_confirmed: bool
    active_consent: bool
    revoked: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "pseudonymous_participant_reference",
            _require_nonblank(
                "pseudonymous_participant_reference",
                self.pseudonymous_participant_reference,
            ),
        )
        object.__setattr__(
            self,
            "consent_evidence_identifier",
            _require_nonblank(
                "consent_evidence_identifier",
                self.consent_evidence_identifier,
            ),
        )
        object.__setattr__(
            self,
            "eligibility_evidence_identifier",
            _require_nonblank(
                "eligibility_evidence_identifier",
                self.eligibility_evidence_identifier,
            ),
        )


@dataclass(frozen=True)
class MinorDataScreeningEvidence:
    """Synthetic evidence for mandatory minor-data screening."""

    screening_evidence_identifier: str
    screening_complete: bool
    minor_data_detected: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "screening_evidence_identifier",
            _require_nonblank(
                "screening_evidence_identifier",
                self.screening_evidence_identifier,
            ),
        )


@dataclass(frozen=True)
class PayloadRouteAuthorizationBinding:
    """Exact field-name and provider-route binding; contains no source text."""

    payload_field_names: tuple[str, ...]
    provider_route_identifier: str

    def __post_init__(self) -> None:
        normalized = tuple(
            _require_nonblank("payload_field_name", name) for name in self.payload_field_names
        )
        if len(set(normalized)) != len(normalized):
            raise ExecutionAuthorizationValidationError(
                "payload_field_names must not contain duplicates"
            )
        object.__setattr__(self, "payload_field_names", normalized)
        object.__setattr__(
            self,
            "provider_route_identifier",
            _require_nonblank(
                "provider_route_identifier",
                self.provider_route_identifier,
            ),
        )


@dataclass(frozen=True)
class ProviderProjectReadOnlyEvidence:
    """Read-only evidence about the future provider/project boundary."""

    dedicated_familyos_project_confirmed: bool
    store_disabled_confirmed: bool
    hosted_tools_disabled_confirmed: bool
    provider_sharing_disabled_confirmed: bool
    read_only_preflight_completed: bool
    provider_configuration_mutation_requested: bool = False


@dataclass(frozen=True)
class OperatorExecutionChecklist:
    """Execution-time boundary requirements carried by the M9 contract."""

    checklist_complete: bool
    abort_conditions_acknowledged: bool
    pre_send_confirmation_required: bool
    unattended_execution_requested: bool = False


@dataclass(frozen=True)
class ExecutionAuthorizationReadinessRequest:
    """Synthetic aggregate for one future execution-authorization request."""

    source: ManualSourceAuthorizationDescriptor
    participant: ParticipantAuthorizationEvidence
    minor_screening: MinorDataScreeningEvidence
    payload_route: PayloadRouteAuthorizationBinding
    provider: ProviderProjectReadOnlyEvidence
    operator: OperatorExecutionChecklist


@dataclass(frozen=True)
class ExecutionAuthorizationAuditEvidence:
    """Raw-content-free evidence for one M9 synthetic authorization rehearsal."""

    ephemeral_correlation_identifier: str
    pseudonymous_participant_reference: str
    provider_route_identifier: str
    scope_fingerprint: str
    state: ExecutionAuthorizationReadinessState
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionAuthorizationReadinessDecision:
    """M9 readiness decision; never performs or authorizes execution."""

    state: ExecutionAuthorizationReadinessState
    reasons: tuple[str, ...]
    scope_fingerprint: str
    audit_evidence: ExecutionAuthorizationAuditEvidence

    @property
    def ready_to_issue_single_use_authorization(self) -> bool:
        """Return whether all M9 readiness gates passed."""
        return (
            self.state
            is ExecutionAuthorizationReadinessState.READY_TO_ISSUE_SINGLE_USE_AUTHORIZATION
        )

    @property
    def execution_authorized(self) -> bool:
        """M9 readiness never authorizes an external real-data execution."""
        return False


@dataclass(frozen=True)
class SyntheticHumanAuthorizationEvidence:
    """Synthetic representation of a future explicit human authorization."""

    human_decision_reference: str
    explicit_human_confirmation: bool
    approved_scope_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "human_decision_reference",
            _require_nonblank(
                "human_decision_reference",
                self.human_decision_reference,
            ),
        )
        object.__setattr__(
            self,
            "approved_scope_fingerprint",
            _require_nonblank(
                "approved_scope_fingerprint",
                self.approved_scope_fingerprint,
            ),
        )


@dataclass(frozen=True)
class SingleUseExecutionAuthorization:
    """Synthetic single-use authorization token model."""

    authorization_identifier: str
    human_decision_reference: str
    scope_fingerprint: str
    issued_at_epoch_seconds: int
    expires_at_epoch_seconds: int
    used: bool = False
    revoked: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "authorization_identifier",
            _require_nonblank(
                "authorization_identifier",
                self.authorization_identifier,
            ),
        )
        object.__setattr__(
            self,
            "human_decision_reference",
            _require_nonblank(
                "human_decision_reference",
                self.human_decision_reference,
            ),
        )
        object.__setattr__(
            self,
            "scope_fingerprint",
            _require_nonblank(
                "scope_fingerprint",
                self.scope_fingerprint,
            ),
        )
        _require_nonnegative(
            "issued_at_epoch_seconds",
            self.issued_at_epoch_seconds,
        )
        _require_nonnegative(
            "expires_at_epoch_seconds",
            self.expires_at_epoch_seconds,
        )
        if self.expires_at_epoch_seconds <= self.issued_at_epoch_seconds:
            raise ExecutionAuthorizationValidationError(
                "expires_at_epoch_seconds must be greater than issued_at_epoch_seconds"
            )


@dataclass(frozen=True)
class SingleUseTokenValidationDecision:
    """Validation result for a synthetic authorization token."""

    state: SingleUseTokenValidationState

    @property
    def valid_for_separate_pre_send_confirmation(self) -> bool:
        """Return whether the token can proceed to a separate confirmation."""
        return self.state is SingleUseTokenValidationState.VALID_FOR_SEPARATE_PRE_SEND_CONFIRMATION

    @property
    def execution_authorized(self) -> bool:
        """Token validation itself never authorizes or performs execution."""
        return False


SCOPE_SCHEMA_VERSION: Final[str] = "familyos-pilot0-m9-execution-auth-v1"


def build_execution_authorization_scope_fingerprint(
    request: ExecutionAuthorizationReadinessRequest,
) -> str:
    """Build a deterministic metadata-only authorization scope fingerprint."""

    document = {
        "schema_version": SCOPE_SCHEMA_VERSION,
        "source_type": request.source.source_type,
        "selected_item_count": request.source.selected_item_count,
        "ephemeral_correlation_identifier": (request.source.ephemeral_correlation_identifier),
        "pseudonymous_participant_reference": (
            request.participant.pseudonymous_participant_reference
        ),
        "payload_field_names": sorted(request.payload_route.payload_field_names),
        "provider_route_identifier": (request.payload_route.provider_route_identifier),
    }
    encoded = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evaluate_execution_authorization_readiness(
    request: ExecutionAuthorizationReadinessRequest,
) -> ExecutionAuthorizationReadinessDecision:
    """Evaluate M9 readiness with fail-closed authorization semantics."""

    reasons: list[str] = []
    fingerprint = build_execution_authorization_scope_fingerprint(request)

    if request.minor_screening.minor_data_detected:
        reasons.append("minor_data_detected_authorization_abort")
        state = ExecutionAuthorizationReadinessState.ABORT
    else:
        if not request.minor_screening.screening_complete:
            reasons.append("minor_data_screening_incomplete")

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

        payload_fields = frozenset(request.payload_route.payload_field_names)
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

        if not request.provider.read_only_preflight_completed:
            reasons.append("provider_read_only_preflight_incomplete")

        if request.provider.provider_configuration_mutation_requested:
            reasons.append("provider_configuration_mutation_forbidden")

        if not request.operator.checklist_complete:
            reasons.append("operator_checklist_incomplete")

        if not request.operator.abort_conditions_acknowledged:
            reasons.append("abort_conditions_not_acknowledged")

        if not request.operator.pre_send_confirmation_required:
            reasons.append("separate_pre_send_confirmation_not_required")

        if request.operator.unattended_execution_requested:
            reasons.append("unattended_execution_forbidden")

        state = (
            ExecutionAuthorizationReadinessState.DENY
            if reasons
            else ExecutionAuthorizationReadinessState.READY_TO_ISSUE_SINGLE_USE_AUTHORIZATION
        )

    reasons_tuple = tuple(reasons)
    audit = ExecutionAuthorizationAuditEvidence(
        ephemeral_correlation_identifier=(request.source.ephemeral_correlation_identifier),
        pseudonymous_participant_reference=(request.participant.pseudonymous_participant_reference),
        provider_route_identifier=(request.payload_route.provider_route_identifier),
        scope_fingerprint=fingerprint,
        state=state,
        reasons=reasons_tuple,
    )

    return ExecutionAuthorizationReadinessDecision(
        state=state,
        reasons=reasons_tuple,
        scope_fingerprint=fingerprint,
        audit_evidence=audit,
    )


def issue_synthetic_single_use_authorization(
    decision: ExecutionAuthorizationReadinessDecision,
    human_evidence: SyntheticHumanAuthorizationEvidence,
    *,
    authorization_identifier: str,
    issued_at_epoch_seconds: int,
    ttl_seconds: int,
) -> SingleUseExecutionAuthorization:
    """Issue a synthetic token only after exact human-scope confirmation."""

    if not decision.ready_to_issue_single_use_authorization:
        raise ExecutionAuthorizationValidationError("authorization readiness decision is not ready")

    if not human_evidence.explicit_human_confirmation:
        raise ExecutionAuthorizationValidationError("explicit human confirmation is required")

    if human_evidence.approved_scope_fingerprint != decision.scope_fingerprint:
        raise ExecutionAuthorizationValidationError(
            "human authorization scope fingerprint mismatch"
        )

    _require_nonnegative(
        "issued_at_epoch_seconds",
        issued_at_epoch_seconds,
    )
    if ttl_seconds <= 0:
        raise ExecutionAuthorizationValidationError("ttl_seconds must be greater than zero")

    return SingleUseExecutionAuthorization(
        authorization_identifier=authorization_identifier,
        human_decision_reference=human_evidence.human_decision_reference,
        scope_fingerprint=decision.scope_fingerprint,
        issued_at_epoch_seconds=issued_at_epoch_seconds,
        expires_at_epoch_seconds=issued_at_epoch_seconds + ttl_seconds,
    )


def validate_single_use_authorization(
    token: SingleUseExecutionAuthorization,
    *,
    expected_scope_fingerprint: str,
    now_epoch_seconds: int,
) -> SingleUseTokenValidationDecision:
    """Validate synthetic token state without performing an execution."""

    _require_nonblank(
        "expected_scope_fingerprint",
        expected_scope_fingerprint,
    )
    _require_nonnegative("now_epoch_seconds", now_epoch_seconds)

    if token.revoked:
        state = SingleUseTokenValidationState.REFUSE_REVOKED
    elif token.used:
        state = SingleUseTokenValidationState.REFUSE_REPLAY
    elif now_epoch_seconds >= token.expires_at_epoch_seconds:
        state = SingleUseTokenValidationState.REFUSE_EXPIRED
    elif expected_scope_fingerprint != token.scope_fingerprint:
        state = SingleUseTokenValidationState.REFUSE_SCOPE_MISMATCH
    else:
        state = SingleUseTokenValidationState.VALID_FOR_SEPARATE_PRE_SEND_CONFIRMATION

    return SingleUseTokenValidationDecision(state=state)


def revoke_single_use_authorization_before_use(
    token: SingleUseExecutionAuthorization,
) -> SingleUseExecutionAuthorization:
    """Revoke a synthetic authorization before it is consumed."""

    if token.used:
        raise ExecutionAuthorizationValidationError(
            "a used authorization cannot be revoked before use"
        )
    return replace(token, revoked=True)


def mark_single_use_authorization_used(
    token: SingleUseExecutionAuthorization,
    *,
    now_epoch_seconds: int,
) -> SingleUseExecutionAuthorization:
    """Mark a synthetic token used after validating its one-time state."""

    validation = validate_single_use_authorization(
        token,
        expected_scope_fingerprint=token.scope_fingerprint,
        now_epoch_seconds=now_epoch_seconds,
    )
    if not validation.valid_for_separate_pre_send_confirmation:
        raise ExecutionAuthorizationValidationError(
            f"authorization cannot be consumed: {validation.state}"
        )
    return replace(token, used=True)
