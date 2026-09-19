from __future__ import annotations

from dataclasses import fields

import pytest

from familyos_pilot0.errors import ControlledExecutionValidationError
from familyos_pilot0.execution_control import (
    ControlledExecutionAuthorization,
    ControlledExecutionRequest,
    ExecutionAuditEvidence,
    ExecutionDecisionState,
    SourceSelection,
    evaluate_controlled_execution,
)


class StaticConsentVerifier:
    def __init__(self, active: bool) -> None:
        self.active = active

    def has_active_consent(
        self,
        pseudonymous_participant_reference: str,
    ) -> bool:
        assert pseudonymous_participant_reference
        return self.active


class StaticRevocationChecker:
    def __init__(self, revoked: bool) -> None:
        self.revoked = revoked

    def is_revoked(
        self,
        pseudonymous_participant_reference: str,
    ) -> bool:
        assert pseudonymous_participant_reference
        return self.revoked


def make_source() -> SourceSelection:
    return SourceSelection(
        source_type="manual_text_item",
        ephemeral_correlation_identifier="corr-001",
        pseudonymous_participant_reference="person-001",
    )


def test_source_selection_rejects_blank_values() -> None:
    with pytest.raises(ControlledExecutionValidationError):
        SourceSelection(
            source_type=" ",
            ephemeral_correlation_identifier="corr-001",
            pseudonymous_participant_reference="person-001",
        )


def test_authorization_rejects_blank_identifier() -> None:
    with pytest.raises(ControlledExecutionValidationError):
        ControlledExecutionAuthorization(
            authorization_id=" ",
            human_authorized=True,
        )


def test_gate_denies_without_explicit_human_authorization() -> None:
    decision = evaluate_controlled_execution(
        ControlledExecutionRequest(source=make_source()),
        ControlledExecutionAuthorization(authorization_id="auth-001"),
        StaticConsentVerifier(active=True),
        StaticRevocationChecker(revoked=False),
    )

    assert decision.state is ExecutionDecisionState.DENY
    assert decision.allowed is False
    assert decision.reasons == ("explicit_human_authorization_missing",)


def test_gate_denies_without_active_consent() -> None:
    decision = evaluate_controlled_execution(
        ControlledExecutionRequest(source=make_source()),
        ControlledExecutionAuthorization(
            authorization_id="auth-001",
            human_authorized=True,
        ),
        StaticConsentVerifier(active=False),
        StaticRevocationChecker(revoked=False),
    )

    assert "active_consent_missing" in decision.reasons


def test_gate_denies_revoked_participant() -> None:
    decision = evaluate_controlled_execution(
        ControlledExecutionRequest(source=make_source()),
        ControlledExecutionAuthorization(
            authorization_id="auth-001",
            human_authorized=True,
        ),
        StaticConsentVerifier(active=True),
        StaticRevocationChecker(revoked=True),
    )

    assert "participant_revoked" in decision.reasons


@pytest.mark.parametrize(
    ("request_kwargs", "reason"),
    [
        (
            {"requires_real_family_data": True},
            "real_family_data_not_authorized",
        ),
        (
            {"requires_real_email": True},
            "real_email_not_authorized",
        ),
        (
            {"requires_provider_network_execution": True},
            "provider_network_execution_not_authorized",
        ),
        (
            {"requires_unattended_external_action": True},
            "unattended_external_action_not_authorized",
        ),
    ],
)
def test_sensitive_capabilities_fail_closed(
    request_kwargs: dict[str, bool],
    reason: str,
) -> None:
    decision = evaluate_controlled_execution(
        ControlledExecutionRequest(
            source=make_source(),
            **request_kwargs,
        ),
        ControlledExecutionAuthorization(
            authorization_id="auth-001",
            human_authorized=True,
        ),
        StaticConsentVerifier(active=True),
        StaticRevocationChecker(revoked=False),
    )

    assert decision.allowed is False
    assert reason in decision.reasons


def test_gate_allows_when_every_required_gate_is_satisfied() -> None:
    decision = evaluate_controlled_execution(
        ControlledExecutionRequest(
            source=make_source(),
            requires_real_family_data=True,
            requires_real_email=True,
            requires_provider_network_execution=True,
            requires_unattended_external_action=True,
        ),
        ControlledExecutionAuthorization(
            authorization_id="auth-001",
            human_authorized=True,
            allow_real_family_data=True,
            allow_real_email=True,
            allow_provider_network_execution=True,
            allow_unattended_external_action=True,
        ),
        StaticConsentVerifier(active=True),
        StaticRevocationChecker(revoked=False),
    )

    assert decision.allowed is True
    assert decision.state is ExecutionDecisionState.ALLOW
    assert decision.reasons == ()


def test_audit_evidence_contains_no_raw_source_text_field() -> None:
    field_names = {field.name for field in fields(ExecutionAuditEvidence)}

    forbidden = {
        "text",
        "body",
        "content",
        "raw_text",
        "selected_text",
        "source_text",
    }

    assert field_names.isdisjoint(forbidden)


def test_source_selection_contains_no_bulk_or_raw_content_fields() -> None:
    field_names = {field.name for field in fields(SourceSelection)}

    forbidden = {
        "mailbox",
        "thread",
        "account",
        "attachment",
        "history",
        "contacts",
        "text",
        "body",
        "content",
        "raw_text",
    }

    assert field_names.isdisjoint(forbidden)
