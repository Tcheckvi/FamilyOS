from __future__ import annotations

from dataclasses import fields

import pytest

from familyos_pilot0.errors import ExecutionAuthorizationValidationError
from familyos_pilot0.execution_authorization import (
    ExecutionAuthorizationAuditEvidence,
    ExecutionAuthorizationReadinessDecision,
    ExecutionAuthorizationReadinessRequest,
    ExecutionAuthorizationReadinessState,
    ManualSourceAuthorizationDescriptor,
    MinorDataScreeningEvidence,
    OperatorExecutionChecklist,
    ParticipantAuthorizationEvidence,
    PayloadRouteAuthorizationBinding,
    ProviderProjectReadOnlyEvidence,
    SingleUseExecutionAuthorization,
    SingleUseTokenValidationState,
    SyntheticHumanAuthorizationEvidence,
    build_execution_authorization_scope_fingerprint,
    evaluate_execution_authorization_readiness,
    issue_synthetic_single_use_authorization,
    mark_single_use_authorization_used,
    revoke_single_use_authorization_before_use,
    validate_single_use_authorization,
)


def make_request(
    *,
    selected_item_count: int = 1,
    manual_selection_confirmed: bool = True,
    adult_confirmed: bool = True,
    active_consent: bool = True,
    revoked: bool = False,
    screening_complete: bool = True,
    minor_data_detected: bool = False,
    payload_field_names: tuple[str, ...] | None = None,
    provider_route_identifier: str = "openai-familyos-dedicated-project",
    read_only_preflight_completed: bool = True,
    provider_configuration_mutation_requested: bool = False,
    checklist_complete: bool = True,
    abort_conditions_acknowledged: bool = True,
    pre_send_confirmation_required: bool = True,
    unattended_execution_requested: bool = False,
) -> ExecutionAuthorizationReadinessRequest:
    fields_for_payload = payload_field_names or (
        "source_type",
        "selected_text_body",
        "pseudonymous_participant_reference",
        "ephemeral_correlation_identifier",
    )

    return ExecutionAuthorizationReadinessRequest(
        source=ManualSourceAuthorizationDescriptor(
            source_type="manual_text_item",
            selected_item_count=selected_item_count,
            manual_selection_confirmed=manual_selection_confirmed,
            ephemeral_correlation_identifier="corr-m9-001",
        ),
        participant=ParticipantAuthorizationEvidence(
            pseudonymous_participant_reference="adult-001",
            consent_evidence_identifier="consent-001",
            eligibility_evidence_identifier="eligibility-001",
            adult_confirmed=adult_confirmed,
            active_consent=active_consent,
            revoked=revoked,
        ),
        minor_screening=MinorDataScreeningEvidence(
            screening_evidence_identifier="minor-screen-001",
            screening_complete=screening_complete,
            minor_data_detected=minor_data_detected,
        ),
        payload_route=PayloadRouteAuthorizationBinding(
            payload_field_names=fields_for_payload,
            provider_route_identifier=provider_route_identifier,
        ),
        provider=ProviderProjectReadOnlyEvidence(
            dedicated_familyos_project_confirmed=True,
            store_disabled_confirmed=True,
            hosted_tools_disabled_confirmed=True,
            provider_sharing_disabled_confirmed=True,
            read_only_preflight_completed=read_only_preflight_completed,
            provider_configuration_mutation_requested=(provider_configuration_mutation_requested),
        ),
        operator=OperatorExecutionChecklist(
            checklist_complete=checklist_complete,
            abort_conditions_acknowledged=abort_conditions_acknowledged,
            pre_send_confirmation_required=pre_send_confirmation_required,
            unattended_execution_requested=unattended_execution_requested,
        ),
    )


def make_ready_decision() -> ExecutionAuthorizationReadinessDecision:
    return evaluate_execution_authorization_readiness(make_request())


def make_human_evidence(
    scope_fingerprint: str,
    *,
    confirmed: bool = True,
) -> SyntheticHumanAuthorizationEvidence:
    return SyntheticHumanAuthorizationEvidence(
        human_decision_reference="human-auth-001",
        explicit_human_confirmation=confirmed,
        approved_scope_fingerprint=scope_fingerprint,
    )


def make_token(*, ttl_seconds: int = 60) -> SingleUseExecutionAuthorization:
    decision = make_ready_decision()
    return issue_synthetic_single_use_authorization(
        decision,
        make_human_evidence(decision.scope_fingerprint),
        authorization_identifier="auth-token-001",
        issued_at_epoch_seconds=1_000,
        ttl_seconds=ttl_seconds,
    )


def test_structural_validation_rejects_blank_source_type() -> None:
    with pytest.raises(ExecutionAuthorizationValidationError):
        ManualSourceAuthorizationDescriptor(
            source_type=" ",
            selected_item_count=1,
            manual_selection_confirmed=True,
            ephemeral_correlation_identifier="corr-m9-001",
        )


def test_structural_validation_rejects_negative_item_count() -> None:
    with pytest.raises(ExecutionAuthorizationValidationError):
        ManualSourceAuthorizationDescriptor(
            source_type="manual_text_item",
            selected_item_count=-1,
            manual_selection_confirmed=True,
            ephemeral_correlation_identifier="corr-m9-001",
        )


def test_payload_binding_rejects_duplicate_fields() -> None:
    with pytest.raises(ExecutionAuthorizationValidationError):
        PayloadRouteAuthorizationBinding(
            payload_field_names=("source_type", "source_type"),
            provider_route_identifier="route-001",
        )


def test_exactly_one_source_item_is_required() -> None:
    decision = evaluate_execution_authorization_readiness(make_request(selected_item_count=2))

    assert decision.state is ExecutionAuthorizationReadinessState.DENY
    assert "exactly_one_source_item_required" in decision.reasons


def test_manual_selection_is_required() -> None:
    decision = evaluate_execution_authorization_readiness(
        make_request(manual_selection_confirmed=False)
    )

    assert "manual_source_selection_not_confirmed" in decision.reasons


def test_adult_consent_and_revocation_gates_are_fail_closed() -> None:
    not_adult = evaluate_execution_authorization_readiness(make_request(adult_confirmed=False))
    no_consent = evaluate_execution_authorization_readiness(make_request(active_consent=False))
    revoked = evaluate_execution_authorization_readiness(make_request(revoked=True))

    assert "adult_participant_not_confirmed" in not_adult.reasons
    assert "active_consent_missing" in no_consent.reasons
    assert "participant_revoked" in revoked.reasons


def test_minor_data_screening_must_be_complete() -> None:
    decision = evaluate_execution_authorization_readiness(make_request(screening_complete=False))

    assert decision.state is ExecutionAuthorizationReadinessState.DENY
    assert "minor_data_screening_incomplete" in decision.reasons


def test_minor_data_detection_aborts_authorization() -> None:
    decision = evaluate_execution_authorization_readiness(make_request(minor_data_detected=True))

    assert decision.state is ExecutionAuthorizationReadinessState.ABORT
    assert decision.reasons == ("minor_data_detected_authorization_abort",)
    assert decision.execution_authorized is False


def test_payload_requires_minimal_canonical_fields() -> None:
    decision = evaluate_execution_authorization_readiness(
        make_request(payload_field_names=("source_type",))
    )

    assert "required_minimal_payload_field_missing" in decision.reasons


def test_payload_refuses_noncanonical_fields() -> None:
    decision = evaluate_execution_authorization_readiness(
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


def test_provider_read_only_preflight_is_required() -> None:
    decision = evaluate_execution_authorization_readiness(
        make_request(read_only_preflight_completed=False)
    )

    assert "provider_read_only_preflight_incomplete" in decision.reasons


def test_provider_configuration_mutation_request_is_refused() -> None:
    decision = evaluate_execution_authorization_readiness(
        make_request(provider_configuration_mutation_requested=True)
    )

    assert "provider_configuration_mutation_forbidden" in decision.reasons


def test_operator_pre_send_confirmation_boundary_is_required() -> None:
    decision = evaluate_execution_authorization_readiness(
        make_request(pre_send_confirmation_required=False)
    )

    assert "separate_pre_send_confirmation_not_required" in decision.reasons


def test_unattended_execution_is_refused() -> None:
    decision = evaluate_execution_authorization_readiness(
        make_request(unattended_execution_requested=True)
    )

    assert "unattended_execution_forbidden" in decision.reasons


def test_ready_state_never_authorizes_execution() -> None:
    decision = make_ready_decision()

    assert (
        decision.state
        is ExecutionAuthorizationReadinessState.READY_TO_ISSUE_SINGLE_USE_AUTHORIZATION
    )
    assert decision.ready_to_issue_single_use_authorization is True
    assert decision.execution_authorized is False
    assert decision.reasons == ()


def test_scope_fingerprint_binds_exact_provider_route() -> None:
    first = build_execution_authorization_scope_fingerprint(
        make_request(provider_route_identifier="route-a")
    )
    second = build_execution_authorization_scope_fingerprint(
        make_request(provider_route_identifier="route-b")
    )

    assert first != second


def test_audit_evidence_contains_no_raw_source_content_field() -> None:
    field_names = {field.name for field in fields(ExecutionAuthorizationAuditEvidence)}

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


def test_synthetic_issue_requires_explicit_human_confirmation() -> None:
    decision = make_ready_decision()

    with pytest.raises(ExecutionAuthorizationValidationError):
        issue_synthetic_single_use_authorization(
            decision,
            make_human_evidence(
                decision.scope_fingerprint,
                confirmed=False,
            ),
            authorization_identifier="auth-token-001",
            issued_at_epoch_seconds=1_000,
            ttl_seconds=60,
        )


def test_synthetic_issue_requires_exact_human_scope_binding() -> None:
    decision = make_ready_decision()

    with pytest.raises(ExecutionAuthorizationValidationError):
        issue_synthetic_single_use_authorization(
            decision,
            make_human_evidence("wrong-scope"),
            authorization_identifier="auth-token-001",
            issued_at_epoch_seconds=1_000,
            ttl_seconds=60,
        )


def test_valid_token_requires_separate_pre_send_confirmation() -> None:
    token = make_token()

    validation = validate_single_use_authorization(
        token,
        expected_scope_fingerprint=token.scope_fingerprint,
        now_epoch_seconds=1_001,
    )

    assert (
        validation.state is SingleUseTokenValidationState.VALID_FOR_SEPARATE_PRE_SEND_CONFIRMATION
    )
    assert validation.valid_for_separate_pre_send_confirmation is True
    assert validation.execution_authorized is False


def test_expired_token_is_refused() -> None:
    token = make_token(ttl_seconds=60)

    validation = validate_single_use_authorization(
        token,
        expected_scope_fingerprint=token.scope_fingerprint,
        now_epoch_seconds=1_060,
    )

    assert validation.state is SingleUseTokenValidationState.REFUSE_EXPIRED


def test_scope_mismatch_is_refused() -> None:
    token = make_token()

    validation = validate_single_use_authorization(
        token,
        expected_scope_fingerprint="different-scope",
        now_epoch_seconds=1_001,
    )

    assert validation.state is SingleUseTokenValidationState.REFUSE_SCOPE_MISMATCH


def test_revocation_before_use_is_refused() -> None:
    revoked = revoke_single_use_authorization_before_use(make_token())

    validation = validate_single_use_authorization(
        revoked,
        expected_scope_fingerprint=revoked.scope_fingerprint,
        now_epoch_seconds=1_001,
    )

    assert validation.state is SingleUseTokenValidationState.REFUSE_REVOKED


def test_used_token_is_refused_as_replay() -> None:
    token = make_token()
    used = mark_single_use_authorization_used(
        token,
        now_epoch_seconds=1_001,
    )

    validation = validate_single_use_authorization(
        used,
        expected_scope_fingerprint=used.scope_fingerprint,
        now_epoch_seconds=1_002,
    )

    assert validation.state is SingleUseTokenValidationState.REFUSE_REPLAY


def test_used_token_cannot_be_revoked_before_use() -> None:
    used = mark_single_use_authorization_used(
        make_token(),
        now_epoch_seconds=1_001,
    )

    with pytest.raises(ExecutionAuthorizationValidationError):
        revoke_single_use_authorization_before_use(used)
