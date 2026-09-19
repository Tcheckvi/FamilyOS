from __future__ import annotations

from dataclasses import fields

import pytest

from familyos_pilot0.errors import FirstRealDataSliceValidationError
from familyos_pilot0.real_data_readiness import (
    ALLOWED_PAYLOAD_FIELD_NAMES,
    EvidenceRequirementsPreflight,
    FirstRealDataSliceReadinessRequest,
    FirstSliceReadinessAuditEvidence,
    FirstSliceReadinessState,
    OperatorExecutionContract,
    ParticipantEligibilityPreflight,
    PayloadMinimizationPreflight,
    ProviderProjectPreflight,
    SourceSelectionPreflight,
    evaluate_first_real_data_slice_readiness,
)


def make_request(
    *,
    selected_item_count: int = 1,
    manual_selection_confirmed: bool = True,
    adult_confirmed: bool = True,
    active_consent: bool = True,
    revoked: bool = False,
    minor_data_detected: bool = False,
    payload_field_names: tuple[str, ...] | None = None,
    provider_configuration_mutation_requested: bool = False,
    execution_authorization_token_present: bool = False,
) -> FirstRealDataSliceReadinessRequest:
    fields_for_payload = payload_field_names or (
        "source_type",
        "selected_text_body",
        "pseudonymous_participant_reference",
        "ephemeral_correlation_identifier",
    )

    return FirstRealDataSliceReadinessRequest(
        source=SourceSelectionPreflight(
            source_type="manual_text_item",
            selected_item_count=selected_item_count,
            manual_selection_confirmed=manual_selection_confirmed,
            ephemeral_correlation_identifier="corr-m8-001",
        ),
        participant=ParticipantEligibilityPreflight(
            pseudonymous_participant_reference="adult-001",
            adult_confirmed=adult_confirmed,
            active_consent=active_consent,
            revoked=revoked,
            minor_data_detected=minor_data_detected,
        ),
        payload=PayloadMinimizationPreflight(
            payload_field_names=fields_for_payload,
        ),
        provider=ProviderProjectPreflight(
            dedicated_familyos_project_confirmed=True,
            store_disabled_confirmed=True,
            hosted_tools_disabled_confirmed=True,
            provider_sharing_disabled_confirmed=True,
            provider_configuration_mutation_requested=(
                provider_configuration_mutation_requested
            ),
        ),
        operator=OperatorExecutionContract(
            operator_checklist_complete=True,
            separate_execution_authorization_required=True,
            execution_authorization_token_present=(
                execution_authorization_token_present
            ),
        ),
        evidence=EvidenceRequirementsPreflight(
            audit_evidence_model_complete=True,
            retention_requirement_defined=True,
            deletion_requirement_defined=True,
            revocation_requirement_defined=True,
        ),
    )


def test_structural_validation_rejects_blank_source_type() -> None:
    with pytest.raises(FirstRealDataSliceValidationError):
        SourceSelectionPreflight(
            source_type=" ",
            selected_item_count=1,
            manual_selection_confirmed=True,
            ephemeral_correlation_identifier="corr-m8-001",
        )


def test_structural_validation_rejects_negative_item_count() -> None:
    with pytest.raises(FirstRealDataSliceValidationError):
        SourceSelectionPreflight(
            source_type="manual_text_item",
            selected_item_count=-1,
            manual_selection_confirmed=True,
            ephemeral_correlation_identifier="corr-m8-001",
        )


def test_exactly_one_manual_source_item_is_required() -> None:
    decision = evaluate_first_real_data_slice_readiness(
        make_request(selected_item_count=2)
    )

    assert decision.state is FirstSliceReadinessState.DENY
    assert "exactly_one_source_item_required" in decision.reasons


def test_manual_source_selection_must_be_confirmed() -> None:
    decision = evaluate_first_real_data_slice_readiness(
        make_request(manual_selection_confirmed=False)
    )

    assert decision.state is FirstSliceReadinessState.DENY
    assert "manual_source_selection_not_confirmed" in decision.reasons


def test_missing_adult_confirmation_denies() -> None:
    decision = evaluate_first_real_data_slice_readiness(
        make_request(adult_confirmed=False)
    )

    assert "adult_participant_not_confirmed" in decision.reasons


def test_missing_active_consent_denies() -> None:
    decision = evaluate_first_real_data_slice_readiness(
        make_request(active_consent=False)
    )

    assert "active_consent_missing" in decision.reasons


def test_revocation_denies() -> None:
    decision = evaluate_first_real_data_slice_readiness(
        make_request(revoked=True)
    )

    assert "participant_revoked" in decision.reasons


def test_minor_data_detection_aborts_immediately() -> None:
    decision = evaluate_first_real_data_slice_readiness(
        make_request(minor_data_detected=True)
    )

    assert decision.state is FirstSliceReadinessState.ABORT
    assert decision.reasons == ("minor_data_detected_abort_required",)
    assert decision.execution_authorized is False


def test_payload_must_remain_within_canonical_field_names() -> None:
    decision = evaluate_first_real_data_slice_readiness(
        make_request(
            payload_field_names=(
                "source_type",
                "selected_text_body",
                "pseudonymous_participant_reference",
                "ephemeral_correlation_identifier",
                "email_headers",
            )
        )
    )

    assert "payload_contains_noncanonical_field" in decision.reasons


def test_optional_event_timestamp_is_allowed() -> None:
    assert "event_relevant_timestamp" in ALLOWED_PAYLOAD_FIELD_NAMES

    decision = evaluate_first_real_data_slice_readiness(
        make_request(
            payload_field_names=(
                "source_type",
                "selected_text_body",
                "event_relevant_timestamp",
                "pseudonymous_participant_reference",
                "ephemeral_correlation_identifier",
            )
        )
    )

    assert decision.ready_for_separate_execution_authorization is True


def test_provider_configuration_mutation_request_denies() -> None:
    decision = evaluate_first_real_data_slice_readiness(
        make_request(provider_configuration_mutation_requested=True)
    )

    assert "provider_configuration_mutation_forbidden" in decision.reasons


def test_execution_token_must_not_be_bound_during_m8_readiness() -> None:
    decision = evaluate_first_real_data_slice_readiness(
        make_request(execution_authorization_token_present=True)
    )

    assert (
        "execution_token_must_not_be_bound_during_m8_readiness"
        in decision.reasons
    )


def test_all_readiness_gates_can_pass_without_authorizing_execution() -> None:
    decision = evaluate_first_real_data_slice_readiness(make_request())

    assert (
        decision.state
        is FirstSliceReadinessState.READY_FOR_SEPARATE_EXECUTION_AUTHORIZATION
    )
    assert decision.ready_for_separate_execution_authorization is True
    assert decision.execution_authorized is False
    assert decision.reasons == ()


def test_audit_evidence_contains_no_raw_source_content_field() -> None:
    field_names = {field.name for field in fields(FirstSliceReadinessAuditEvidence)}

    forbidden = {
        "text",
        "body",
        "content",
        "raw_text",
        "selected_text",
        "selected_text_body",
        "source_text",
        "email_body",
    }

    assert field_names.isdisjoint(forbidden)


def test_source_selection_contains_no_raw_source_content_field() -> None:
    field_names = {field.name for field in fields(SourceSelectionPreflight)}

    forbidden = {
        "text",
        "body",
        "content",
        "raw_text",
        "selected_text",
        "selected_text_body",
        "source_text",
    }

    assert field_names.isdisjoint(forbidden)
