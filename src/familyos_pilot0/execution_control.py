"""Fail-closed controlled-execution readiness primitives for Pilot 0 M7."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .errors import ControlledExecutionValidationError


def _require_nonblank(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ControlledExecutionValidationError(f"{name} must not be blank")
    return normalized


class ExecutionDecisionState(StrEnum):
    """Canonical controlled-execution decision states."""

    ALLOW = "ALLOW"
    DENY = "DENY"


@dataclass(frozen=True)
class SourceSelection:
    """Bounded metadata for exactly one manually selected source item."""

    source_type: str
    ephemeral_correlation_identifier: str
    pseudonymous_participant_reference: str

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
        object.__setattr__(
            self,
            "pseudonymous_participant_reference",
            _require_nonblank(
                "pseudonymous_participant_reference",
                self.pseudonymous_participant_reference,
            ),
        )


@dataclass(frozen=True)
class ControlledExecutionRequest:
    """Capability request evaluated by the fail-closed execution gate."""

    source: SourceSelection
    requires_real_family_data: bool = False
    requires_real_email: bool = False
    requires_provider_network_execution: bool = False
    requires_unattended_external_action: bool = False


@dataclass(frozen=True)
class ControlledExecutionAuthorization:
    """Explicit human-bound capabilities for one controlled execution."""

    authorization_id: str
    human_authorized: bool = False
    allow_real_family_data: bool = False
    allow_real_email: bool = False
    allow_provider_network_execution: bool = False
    allow_unattended_external_action: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "authorization_id",
            _require_nonblank("authorization_id", self.authorization_id),
        )


class ConsentVerifier(Protocol):
    """Interface for active-consent verification."""

    def has_active_consent(
        self,
        pseudonymous_participant_reference: str,
    ) -> bool:
        """Return whether the participant currently has active consent."""


class RevocationChecker(Protocol):
    """Interface for fail-closed revocation enforcement."""

    def is_revoked(
        self,
        pseudonymous_participant_reference: str,
    ) -> bool:
        """Return whether the participant is currently revoked."""


@dataclass(frozen=True)
class ExecutionAuditEvidence:
    """Raw-text-free evidence for one execution-gate decision."""

    authorization_id: str
    source_type: str
    ephemeral_correlation_identifier: str
    pseudonymous_participant_reference: str
    decision: ExecutionDecisionState
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ControlledExecutionDecision:
    """Result of controlled-execution gate evaluation."""

    state: ExecutionDecisionState
    reasons: tuple[str, ...]
    audit_evidence: ExecutionAuditEvidence

    @property
    def allowed(self) -> bool:
        """Return whether the request passed every required gate."""
        return self.state is ExecutionDecisionState.ALLOW


def evaluate_controlled_execution(
    request: ControlledExecutionRequest,
    authorization: ControlledExecutionAuthorization,
    consent_verifier: ConsentVerifier,
    revocation_checker: RevocationChecker,
) -> ControlledExecutionDecision:
    """Evaluate one controlled execution and deny whenever a gate is unmet."""

    participant_ref = request.source.pseudonymous_participant_reference
    reasons: list[str] = []

    if not authorization.human_authorized:
        reasons.append("explicit_human_authorization_missing")

    if not consent_verifier.has_active_consent(participant_ref):
        reasons.append("active_consent_missing")

    if revocation_checker.is_revoked(participant_ref):
        reasons.append("participant_revoked")

    capability_checks = (
        (
            request.requires_real_family_data,
            authorization.allow_real_family_data,
            "real_family_data_not_authorized",
        ),
        (
            request.requires_real_email,
            authorization.allow_real_email,
            "real_email_not_authorized",
        ),
        (
            request.requires_provider_network_execution,
            authorization.allow_provider_network_execution,
            "provider_network_execution_not_authorized",
        ),
        (
            request.requires_unattended_external_action,
            authorization.allow_unattended_external_action,
            "unattended_external_action_not_authorized",
        ),
    )

    for requested, permitted, reason in capability_checks:
        if requested and not permitted:
            reasons.append(reason)

    state = (
        ExecutionDecisionState.DENY
        if reasons
        else ExecutionDecisionState.ALLOW
    )
    reasons_tuple = tuple(reasons)

    evidence = ExecutionAuditEvidence(
        authorization_id=authorization.authorization_id,
        source_type=request.source.source_type,
        ephemeral_correlation_identifier=(
            request.source.ephemeral_correlation_identifier
        ),
        pseudonymous_participant_reference=participant_ref,
        decision=state,
        reasons=reasons_tuple,
    )

    return ControlledExecutionDecision(
        state=state,
        reasons=reasons_tuple,
        audit_evidence=evidence,
    )
