from __future__ import annotations

import ast
import json
from concurrent.futures import ThreadPoolExecutor
from copy import copy, deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from threading import Event, Thread
from typing import Any, cast

import pytest

import familyos_pilot0.controlled_execution as controlled_execution_module
from familyos_pilot0.controlled_execution import (
    ControlledExecutionReadinessDecision,
    ControlledExecutionReadinessState,
    ControlledExecutionRequest,
    EphemeralScopeBindingKey,
    ExecutionPayload,
    FinalMinorDataScreeningEvidence,
    HumanPreSendExecutionAuthorization,
    OneShotSubmissionEnvelope,
    ProviderExecutionBoundary,
    SingleUseAuthorizationLedger,
    SyntheticOneShotSubmissionRecorder,
    build_controlled_execution_scope_fingerprint,
    evaluate_controlled_execution_readiness,
    prepare_one_shot_submission_envelope,
)
from familyos_pilot0.errors import ControlledExecutionValidationError
from familyos_pilot0.execution_authorization import (
    ExecutionAuthorizationReadinessRequest,
    ManualSourceAuthorizationDescriptor,
    MinorDataScreeningEvidence,
    OperatorExecutionChecklist,
    ParticipantAuthorizationEvidence,
    PayloadRouteAuthorizationBinding,
    ProviderProjectReadOnlyEvidence,
    SingleUseExecutionAuthorization,
    SyntheticHumanAuthorizationEvidence,
    evaluate_execution_authorization_readiness,
    issue_synthetic_single_use_authorization,
    validate_single_use_authorization,
)
from familyos_pilot0.real_data_readiness import REQUIRED_PAYLOAD_FIELD_NAMES

NOW = 2_000_000_000
RAW_TEXT = "Synthetic adult-only reminder text."


def make_m9_request() -> ExecutionAuthorizationReadinessRequest:
    return ExecutionAuthorizationReadinessRequest(
        source=ManualSourceAuthorizationDescriptor(
            source_type="manual_text",
            selected_item_count=1,
            manual_selection_confirmed=True,
            ephemeral_correlation_identifier="corr-synthetic-001",
        ),
        participant=ParticipantAuthorizationEvidence(
            pseudonymous_participant_reference="adult-synthetic-001",
            consent_evidence_identifier="consent-synthetic-001",
            eligibility_evidence_identifier="eligibility-synthetic-001",
            adult_confirmed=True,
            active_consent=True,
            revoked=False,
        ),
        minor_screening=MinorDataScreeningEvidence(
            screening_evidence_identifier="minor-screen-synthetic-001",
            screening_complete=True,
            minor_data_detected=False,
        ),
        payload_route=PayloadRouteAuthorizationBinding(
            payload_field_names=tuple(sorted(REQUIRED_PAYLOAD_FIELD_NAMES)),
            provider_route_identifier="openai-familyos-reviewed-route",
        ),
        provider=ProviderProjectReadOnlyEvidence(
            dedicated_familyos_project_confirmed=True,
            store_disabled_confirmed=True,
            hosted_tools_disabled_confirmed=True,
            provider_sharing_disabled_confirmed=True,
            read_only_preflight_completed=True,
        ),
        operator=OperatorExecutionChecklist(
            checklist_complete=True,
            abort_conditions_acknowledged=True,
            pre_send_confirmation_required=True,
        ),
    )


def make_token(
    request: ExecutionAuthorizationReadinessRequest,
) -> SingleUseExecutionAuthorization:
    decision = evaluate_execution_authorization_readiness(request)
    human = SyntheticHumanAuthorizationEvidence(
        human_decision_reference="m9-human-synthetic-001",
        explicit_human_confirmation=True,
        approved_scope_fingerprint=decision.scope_fingerprint,
    )
    return issue_synthetic_single_use_authorization(
        decision,
        human,
        authorization_identifier="m9-token-synthetic-001",
        issued_at_epoch_seconds=NOW - 10,
        ttl_seconds=300,
    )


def make_payload(
    *,
    selected_text_body: str = RAW_TEXT,
) -> ExecutionPayload:
    return ExecutionPayload(
        (
            ("ephemeral_correlation_identifier", "corr-synthetic-001"),
            ("pseudonymous_participant_reference", "adult-synthetic-001"),
            ("selected_text_body", selected_text_body),
            ("source_type", "manual_text"),
        )
    )


def make_request() -> ControlledExecutionRequest:
    m9_request = make_m9_request()
    return ControlledExecutionRequest(
        m9_readiness_request=m9_request,
        m9_single_use_authorization=make_token(m9_request),
        final_minor_screening=FinalMinorDataScreeningEvidence(
            evidence_identifier="final-minor-screen-synthetic-001",
            screening_complete=True,
            minor_data_detected=False,
            uncertainty_detected=False,
        ),
        payload=make_payload(),
        provider=ProviderExecutionBoundary(
            provider_route_identifier="openai-familyos-reviewed-route",
            read_only_preflight_complete=True,
        ),
    )


def ready(
    request: ControlledExecutionRequest,
    key: EphemeralScopeBindingKey,
    *,
    now: int = NOW,
) -> ControlledExecutionReadinessDecision:
    return evaluate_controlled_execution_readiness(
        request,
        scope_binding_key=key,
        now_epoch_seconds=now,
    )


def make_human(scope: str) -> HumanPreSendExecutionAuthorization:
    return HumanPreSendExecutionAuthorization(
        human_decision_reference="m10-human-synthetic-001",
        explicit_human_confirmation=True,
        approved_scope_fingerprint=scope,
    )


def prepare(
    request: ControlledExecutionRequest,
    key: EphemeralScopeBindingKey,
    ledger: SingleUseAuthorizationLedger,
) -> OneShotSubmissionEnvelope:
    decision = ready(request, key)
    return prepare_one_shot_submission_envelope(
        request,
        decision,
        make_human(decision.scope_fingerprint),
        ledger=ledger,
        scope_binding_key=key,
        now_epoch_seconds=NOW,
    )


def test_ready_path_requires_separate_human_authorization() -> None:
    request = make_request()
    key = EphemeralScopeBindingKey.generate()
    decision = ready(request, key)

    assert (
        decision.state
        is ControlledExecutionReadinessState.READY_FOR_EXPLICIT_HUMAN_PRE_SEND_AUTHORIZATION
    )
    assert decision.execution_authorized is False
    assert decision.reasons == ()


def test_incomplete_final_screening_denies() -> None:
    request = replace(
        make_request(),
        final_minor_screening=FinalMinorDataScreeningEvidence(
            evidence_identifier="final-minor-screen-synthetic-001",
            screening_complete=False,
            minor_data_detected=False,
            uncertainty_detected=False,
        ),
    )
    decision = ready(request, EphemeralScopeBindingKey.generate())
    assert decision.state is ControlledExecutionReadinessState.DENY
    assert "final_minor_data_screening_incomplete" in decision.reasons


def test_final_minor_detection_aborts() -> None:
    request = replace(
        make_request(),
        final_minor_screening=FinalMinorDataScreeningEvidence(
            evidence_identifier="final-minor-screen-synthetic-001",
            screening_complete=True,
            minor_data_detected=True,
            uncertainty_detected=False,
        ),
    )
    decision = ready(request, EphemeralScopeBindingKey.generate())
    assert decision.state is ControlledExecutionReadinessState.ABORT
    assert "final_minor_data_detected" in decision.reasons


def test_final_minor_uncertainty_aborts() -> None:
    request = replace(
        make_request(),
        final_minor_screening=FinalMinorDataScreeningEvidence(
            evidence_identifier="final-minor-screen-synthetic-001",
            screening_complete=True,
            minor_data_detected=False,
            uncertainty_detected=True,
        ),
    )
    decision = ready(request, EphemeralScopeBindingKey.generate())
    assert decision.state is ControlledExecutionReadinessState.ABORT
    assert "final_minor_data_uncertainty_detected" in decision.reasons


def test_provider_configuration_mutation_denies() -> None:
    request = replace(
        make_request(),
        provider=ProviderExecutionBoundary(
            provider_route_identifier="openai-familyos-reviewed-route",
            read_only_preflight_complete=True,
            provider_configuration_mutation_requested=True,
        ),
    )
    decision = ready(request, EphemeralScopeBindingKey.generate())
    assert decision.state is ControlledExecutionReadinessState.DENY
    assert "provider_configuration_mutation_forbidden" in decision.reasons


def test_provider_route_mismatch_denies() -> None:
    request = replace(
        make_request(),
        provider=ProviderExecutionBoundary(
            provider_route_identifier="different-route",
            read_only_preflight_complete=True,
        ),
    )
    decision = ready(request, EphemeralScopeBindingKey.generate())
    assert decision.state is ControlledExecutionReadinessState.DENY
    assert "provider_route_scope_mismatch" in decision.reasons


def test_provider_preflight_false_denies() -> None:
    request = replace(
        make_request(),
        provider=ProviderExecutionBoundary(
            provider_route_identifier="openai-familyos-reviewed-route",
            read_only_preflight_complete=False,
        ),
    )
    decision = ready(request, EphemeralScopeBindingKey.generate())
    assert decision.state is ControlledExecutionReadinessState.DENY
    assert "provider_read_only_preflight_incomplete" in decision.reasons


def test_payload_metadata_mismatch_denies() -> None:
    request = replace(
        make_request(),
        payload=ExecutionPayload(
            (
                ("ephemeral_correlation_identifier", "corr-synthetic-001"),
                ("pseudonymous_participant_reference", "different-adult"),
                ("selected_text_body", RAW_TEXT),
                ("source_type", "manual_text"),
            )
        ),
    )
    decision = ready(request, EphemeralScopeBindingKey.generate())
    assert decision.state is ControlledExecutionReadinessState.DENY
    assert "payload_participant_scope_mismatch" in decision.reasons


def test_blank_required_payload_value_denies() -> None:
    request = replace(
        make_request(),
        payload=make_payload(selected_text_body=" "),
    )
    decision = ready(request, EphemeralScopeBindingKey.generate())
    assert decision.state is ControlledExecutionReadinessState.DENY
    assert "required_payload_value_invalid:selected_text_body" in decision.reasons


def test_extra_payload_field_denies() -> None:
    request = replace(
        make_request(),
        payload=ExecutionPayload(make_payload().values + (("email_header", "synthetic"),)),
    )
    decision = ready(request, EphemeralScopeBindingKey.generate())
    assert decision.state is ControlledExecutionReadinessState.DENY
    assert "payload_contains_noncanonical_field" in decision.reasons


def test_expired_revoked_and_used_m9_tokens_deny() -> None:
    request = make_request()

    assert (
        ready(
            request,
            EphemeralScopeBindingKey.generate(),
            now=NOW + 1_000,
        ).state
        is ControlledExecutionReadinessState.DENY
    )

    revoked = replace(
        request,
        m9_single_use_authorization=replace(
            request.m9_single_use_authorization,
            revoked=True,
        ),
    )
    assert (
        ready(
            revoked,
            EphemeralScopeBindingKey.generate(),
        ).state
        is ControlledExecutionReadinessState.DENY
    )

    used = replace(
        request,
        m9_single_use_authorization=replace(
            request.m9_single_use_authorization,
            used=True,
        ),
    )
    assert (
        ready(
            used,
            EphemeralScopeBindingKey.generate(),
        ).state
        is ControlledExecutionReadinessState.DENY
    )


def test_future_issued_m9_token_denies() -> None:
    request = make_request()
    future_token = replace(
        request.m9_single_use_authorization,
        issued_at_epoch_seconds=NOW + 10,
        expires_at_epoch_seconds=NOW + 100,
    )
    changed = replace(request, m9_single_use_authorization=future_token)
    decision = ready(changed, EphemeralScopeBindingKey.generate())
    assert decision.state is ControlledExecutionReadinessState.DENY
    assert "m9_single_use_token_not_yet_valid" in decision.reasons


def test_nan_token_expiry_is_governed_error() -> None:
    request = make_request()
    token = object.__new__(SingleUseExecutionAuthorization)
    for name, value in vars(request.m9_single_use_authorization).items():
        object.__setattr__(token, name, value)
    object.__setattr__(token, "expires_at_epoch_seconds", float("nan"))
    changed = replace(request, m9_single_use_authorization=token)

    with pytest.raises(
        ControlledExecutionValidationError,
        match="expires_at_epoch_seconds must be an exact int",
    ):
        ready(changed, EphemeralScopeBindingKey.generate())


def test_execution_payload_rejects_outer_list_and_remains_immutable() -> None:
    with pytest.raises(
        ControlledExecutionValidationError,
        match="exact tuple",
    ):
        ExecutionPayload(cast(Any, [("source_type", "manual_text")]))

    source = (
        ("source_type", "manual_text"),
        ("selected_text_body", RAW_TEXT),
    )
    payload = ExecutionPayload(source)
    assert payload.values == source
    assert isinstance(payload.values, tuple)


def test_execution_payload_rejects_non_string_and_string_subclass() -> None:
    with pytest.raises(
        ControlledExecutionValidationError,
        match="exact string or None",
    ):
        ExecutionPayload((("source_type", cast(Any, 123)),))

    class TrickyString(str):
        pass

    with pytest.raises(
        ControlledExecutionValidationError,
        match="exact string or None",
    ):
        ExecutionPayload((("source_type", cast(Any, TrickyString("manual_text"))),))


def test_execution_payload_rejects_non_tuple_entry() -> None:
    with pytest.raises(
        ControlledExecutionValidationError,
        match="exact two-item tuple",
    ):
        ExecutionPayload(cast(Any, (["source_type", "manual_text"],)))


def test_boolean_strings_are_rejected() -> None:
    with pytest.raises(
        ControlledExecutionValidationError,
        match="exact bool",
    ):
        FinalMinorDataScreeningEvidence(
            evidence_identifier="screen-1",
            screening_complete=cast(Any, "false"),
            minor_data_detected=False,
            uncertainty_detected=False,
        )

    with pytest.raises(
        ControlledExecutionValidationError,
        match="exact bool",
    ):
        ProviderExecutionBoundary(
            provider_route_identifier="route-1",
            read_only_preflight_complete=cast(Any, "false"),
        )

    with pytest.raises(
        ControlledExecutionValidationError,
        match="exact bool",
    ):
        HumanPreSendExecutionAuthorization(
            human_decision_reference="human-1",
            explicit_human_confirmation=cast(Any, "false"),
            approved_scope_fingerprint="0" * 64,
        )


def test_non_ascii_human_fingerprint_is_governed_error() -> None:
    with pytest.raises(
        ControlledExecutionValidationError,
        match="SHA-256",
    ):
        HumanPreSendExecutionAuthorization(
            human_decision_reference="human-1",
            explicit_human_confirmation=True,
            approved_scope_fingerprint="é" * 64,
        )


def test_unicode_surrogates_are_rejected_but_scalar_emoji_is_allowed() -> None:
    with pytest.raises(
        ControlledExecutionValidationError,
        match="Unicode surrogates",
    ):
        make_payload(selected_text_body="\ud800")

    with pytest.raises(
        ControlledExecutionValidationError,
        match="Unicode surrogates",
    ):
        make_payload(selected_text_body="\ud83d\ude00")

    request = replace(
        make_request(),
        payload=make_payload(selected_text_body="😀"),
    )
    decision = ready(request, EphemeralScopeBindingKey.generate())
    assert (
        decision.state
        is ControlledExecutionReadinessState.READY_FOR_EXPLICIT_HUMAN_PRE_SEND_AUTHORIZATION
    )


def test_payload_ordinary_mutation_and_reinitialization_are_refused() -> None:
    payload = make_payload()
    original = payload.values

    with pytest.raises(ControlledExecutionValidationError, match="immutable"):
        payload._values = (("source_type", "changed"),)

    with pytest.raises(ControlledExecutionValidationError, match="immutable"):
        delattr(payload, "_values")

    with pytest.raises(
        ControlledExecutionValidationError,
        match="reinitialization",
    ):
        ExecutionPayload.__init__(
            payload,
            (("source_type", "changed"),),
        )

    assert payload.values == original
    assert copy(payload) is payload
    assert deepcopy(payload) is payload


def test_prepared_envelope_payload_cannot_change_via_supported_operations() -> None:
    request = make_request()
    payload = request.payload
    envelope = prepare(
        request,
        EphemeralScopeBindingKey.generate(),
        SingleUseAuthorizationLedger(),
    )

    with pytest.raises(
        ControlledExecutionValidationError,
        match="reinitialization",
    ):
        ExecutionPayload.__init__(
            payload,
            make_payload(
                selected_text_body="Changed after approval.",
            ).values,
        )

    assert envelope.payload is payload
    assert envelope.payload.as_dict()["selected_text_body"] == RAW_TEXT


def assert_same_key_scope_change_is_refused(
    original: ControlledExecutionRequest,
    changed: ControlledExecutionRequest,
) -> None:
    key = EphemeralScopeBindingKey.generate()
    build_controlled_execution_scope_fingerprint(
        original,
        scope_binding_key=key,
        now_epoch_seconds=NOW,
    )

    with pytest.raises(
        ControlledExecutionValidationError,
        match="reuse across execution instances refused",
    ):
        build_controlled_execution_scope_fingerprint(
            changed,
            scope_binding_key=key,
            now_epoch_seconds=NOW,
        )


def test_scope_fingerprint_same_key_binds_payload_values() -> None:
    request = make_request()
    changed = replace(
        request,
        payload=make_payload(selected_text_body="Different synthetic text."),
    )
    assert_same_key_scope_change_is_refused(request, changed)


def test_scope_fingerprint_same_key_binds_payload_field_names() -> None:
    request = make_request()
    changed_values = tuple(
        (
            "source_type_variant" if name == "source_type" else name,
            value,
        )
        for name, value in request.payload.values
    )
    changed = replace(
        request,
        payload=ExecutionPayload(changed_values),
    )
    assert_same_key_scope_change_is_refused(request, changed)


def test_scope_fingerprint_same_key_binds_top_level_m9_scope() -> None:
    request = make_request()
    changed_m9 = replace(
        request.m9_readiness_request,
        source=replace(
            request.m9_readiness_request.source,
            ephemeral_correlation_identifier="corr-synthetic-variant",
        ),
    )
    assert_same_key_scope_change_is_refused(
        request,
        replace(request, m9_readiness_request=changed_m9),
    )


def test_scope_fingerprint_same_key_binds_participant_evidence_identifiers() -> None:
    request = make_request()
    participant = request.m9_readiness_request.participant

    for changed_participant in (
        replace(
            participant,
            consent_evidence_identifier="different-consent-evidence",
        ),
        replace(
            participant,
            eligibility_evidence_identifier="different-eligibility-evidence",
        ),
    ):
        changed_m9 = replace(
            request.m9_readiness_request,
            participant=changed_participant,
        )
        assert_same_key_scope_change_is_refused(
            request,
            replace(request, m9_readiness_request=changed_m9),
        )


def test_scope_fingerprint_same_key_binds_m9_screening_identifier() -> None:
    request = make_request()
    changed_m9 = replace(
        request.m9_readiness_request,
        minor_screening=replace(
            request.m9_readiness_request.minor_screening,
            screening_evidence_identifier="different-screen-evidence",
        ),
    )
    assert_same_key_scope_change_is_refused(
        request,
        replace(request, m9_readiness_request=changed_m9),
    )


def test_scope_fingerprint_same_key_binds_all_m9_token_fields() -> None:
    request = make_request()
    token = request.m9_single_use_authorization

    changed_tokens = (
        replace(token, authorization_identifier="different-token"),
        replace(token, human_decision_reference="different-human"),
        replace(token, scope_fingerprint="1" * 64),
        replace(token, issued_at_epoch_seconds=NOW - 11),
        replace(token, expires_at_epoch_seconds=NOW + 400),
        replace(token, used=True),
        replace(token, revoked=True),
    )

    for changed_token in changed_tokens:
        assert_same_key_scope_change_is_refused(
            request,
            replace(request, m9_single_use_authorization=changed_token),
        )


def test_scope_fingerprint_same_key_binds_final_screening_fields() -> None:
    request = make_request()
    screening = request.final_minor_screening

    changed_screenings = (
        replace(screening, evidence_identifier="different-final-screen"),
        replace(screening, screening_complete=False),
        replace(screening, minor_data_detected=True),
        replace(screening, uncertainty_detected=True),
    )

    for changed_screening in changed_screenings:
        assert_same_key_scope_change_is_refused(
            request,
            replace(request, final_minor_screening=changed_screening),
        )


def test_scope_fingerprint_same_key_binds_provider_boundary_fields() -> None:
    request = make_request()
    provider = request.provider

    changed_providers = (
        replace(provider, provider_route_identifier="different-route"),
        replace(provider, read_only_preflight_complete=False),
        replace(provider, provider_configuration_mutation_requested=True),
    )

    for changed_provider in changed_providers:
        assert_same_key_scope_change_is_refused(
            request,
            replace(request, provider=changed_provider),
        )


def test_scope_fingerprint_same_key_binds_contract_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = make_request()
    key = EphemeralScopeBindingKey.generate()
    build_controlled_execution_scope_fingerprint(
        request,
        scope_binding_key=key,
        now_epoch_seconds=NOW,
    )

    monkeypatch.setattr(
        controlled_execution_module,
        "M10_EXECUTION_CONTRACT_VERSION",
        "familyos-pilot0-m10-controlled-execution-v4-test",
    )

    with pytest.raises(
        ControlledExecutionValidationError,
        match="reuse across execution instances refused",
    ):
        build_controlled_execution_scope_fingerprint(
            request,
            scope_binding_key=key,
            now_epoch_seconds=NOW,
        )


def test_scope_key_is_fresh_single_scope_redacted_and_destroyable() -> None:
    request = make_request()
    key = EphemeralScopeBindingKey.generate()
    assert "redacted" in repr(key)

    first = build_controlled_execution_scope_fingerprint(
        request,
        scope_binding_key=key,
        now_epoch_seconds=NOW,
    )
    repeated = build_controlled_execution_scope_fingerprint(
        request,
        scope_binding_key=key,
        now_epoch_seconds=NOW,
    )
    assert first == repeated

    changed = replace(
        request,
        payload=make_payload(selected_text_body="different"),
    )
    with pytest.raises(
        ControlledExecutionValidationError,
        match="reuse across execution instances refused",
    ):
        build_controlled_execution_scope_fingerprint(
            changed,
            scope_binding_key=key,
            now_epoch_seconds=NOW,
        )

    key.destroy()
    assert key.destroyed is True
    with pytest.raises(
        ControlledExecutionValidationError,
        match="destroyed",
    ):
        build_controlled_execution_scope_fingerprint(
            request,
            scope_binding_key=key,
            now_epoch_seconds=NOW,
        )


def test_two_generated_scope_keys_produce_distinct_fingerprints() -> None:
    request = make_request()
    with EphemeralScopeBindingKey.generate() as key_a:
        fp_a = build_controlled_execution_scope_fingerprint(
            request,
            scope_binding_key=key_a,
            now_epoch_seconds=NOW,
        )
    with EphemeralScopeBindingKey.generate() as key_b:
        fp_b = build_controlled_execution_scope_fingerprint(
            request,
            scope_binding_key=key_b,
            now_epoch_seconds=NOW,
        )

    assert fp_a != fp_b


def test_asdict_does_not_plain_serialize_raw_payload_or_key() -> None:
    request = make_request()
    data = asdict(request)
    assert isinstance(data["payload"], ExecutionPayload)
    assert RAW_TEXT not in repr(data)
    with pytest.raises(TypeError):
        json.dumps(data)


def test_repr_and_audit_hide_raw_payload() -> None:
    request = make_request()
    key = EphemeralScopeBindingKey.generate()
    decision = ready(request, key)

    assert RAW_TEXT not in repr(request)
    assert RAW_TEXT not in repr(request.payload)
    assert RAW_TEXT not in repr(decision.audit_evidence)


def test_human_scope_mismatch_is_refused() -> None:
    request = make_request()
    key = EphemeralScopeBindingKey.generate()
    decision = ready(request, key)

    with pytest.raises(
        ControlledExecutionValidationError,
        match="scope mismatch",
    ):
        prepare_one_shot_submission_envelope(
            request,
            decision,
            make_human("0" * 64),
            ledger=SingleUseAuthorizationLedger(),
            scope_binding_key=key,
            now_epoch_seconds=NOW,
        )


def test_human_confirmation_is_required() -> None:
    request = make_request()
    key = EphemeralScopeBindingKey.generate()
    decision = ready(request, key)
    human = replace(
        make_human(decision.scope_fingerprint),
        explicit_human_confirmation=False,
    )

    with pytest.raises(
        ControlledExecutionValidationError,
        match="explicit human pre-send",
    ):
        prepare_one_shot_submission_envelope(
            request,
            decision,
            human,
            ledger=SingleUseAuthorizationLedger(),
            scope_binding_key=key,
            now_epoch_seconds=NOW,
        )


def test_prepare_rejects_minor_data_drift_after_prior_ready_decision() -> None:
    request = make_request()
    key = EphemeralScopeBindingKey.generate()
    decision = ready(request, key)

    changed = replace(
        request,
        final_minor_screening=FinalMinorDataScreeningEvidence(
            evidence_identifier="final-minor-screen-synthetic-001",
            screening_complete=True,
            minor_data_detected=True,
            uncertainty_detected=False,
        ),
    )

    with pytest.raises(
        ControlledExecutionValidationError,
        match="reuse across execution instances refused",
    ):
        prepare_one_shot_submission_envelope(
            changed,
            decision,
            make_human(decision.scope_fingerprint),
            ledger=SingleUseAuthorizationLedger(),
            scope_binding_key=key,
            now_epoch_seconds=NOW,
        )


def test_prepare_rejects_provider_boundary_drift_after_ready_decision() -> None:
    request = make_request()
    key = EphemeralScopeBindingKey.generate()
    decision = ready(request, key)

    changed = replace(
        request,
        provider=ProviderExecutionBoundary(
            provider_route_identifier="different-route",
            read_only_preflight_complete=True,
        ),
    )

    with pytest.raises(
        ControlledExecutionValidationError,
        match="reuse across execution instances refused",
    ):
        prepare_one_shot_submission_envelope(
            changed,
            decision,
            make_human(decision.scope_fingerprint),
            ledger=SingleUseAuthorizationLedger(),
            scope_binding_key=key,
            now_epoch_seconds=NOW,
        )


def test_successful_prepare_consumes_ledger_and_destroys_key() -> None:
    request = make_request()
    key = EphemeralScopeBindingKey.generate()
    ledger = SingleUseAuthorizationLedger()

    envelope = prepare(request, key, ledger)

    assert envelope.provider_execution_performed is False
    assert envelope.execution_authorized is False
    assert envelope.consumed_authorization.used is True
    assert key.destroyed is True


def test_shared_ledger_refuses_second_prepare_with_fresh_key() -> None:
    request = make_request()
    ledger = SingleUseAuthorizationLedger()

    prepare(request, EphemeralScopeBindingKey.generate(), ledger)

    with pytest.raises(
        ControlledExecutionValidationError,
        match="already consumed",
    ):
        prepare(request, EphemeralScopeBindingKey.generate(), ledger)


def test_ledger_concurrency_allows_exactly_one_consumer() -> None:
    ledger = SingleUseAuthorizationLedger()

    def attempt(_: int) -> bool:
        try:
            ledger.consume("concurrent-token")
        except ControlledExecutionValidationError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(attempt, range(64)))

    assert sum(results) == 1


def test_recorder_concurrency_allows_exactly_one_submission() -> None:
    request = make_request()
    envelope = prepare(
        request,
        EphemeralScopeBindingKey.generate(),
        SingleUseAuthorizationLedger(),
    )
    recorder = SyntheticOneShotSubmissionRecorder()

    def attempt(_: int) -> bool:
        try:
            recorder.record(envelope)
        except ControlledExecutionValidationError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(attempt, range(64)))

    assert sum(results) == 1


def test_shared_key_concurrent_prepare_has_exactly_one_owner() -> None:
    request = make_request()
    key = EphemeralScopeBindingKey.generate()
    decision = ready(request, key)
    human = make_human(decision.scope_fingerprint)
    ledger = SingleUseAuthorizationLedger()

    def attempt(_: int) -> bool:
        try:
            prepare_one_shot_submission_envelope(
                request,
                decision,
                human,
                ledger=ledger,
                scope_binding_key=key,
                now_epoch_seconds=NOW,
            )
        except ControlledExecutionValidationError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(attempt, range(64)))

    assert sum(results) == 1
    assert key.preparation_claimed is True
    assert key.destroyed is True


def test_shared_key_losers_cannot_destroy_paused_owner_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = make_request()
    key = EphemeralScopeBindingKey.generate()
    decision = ready(request, key)
    human = make_human(decision.scope_fingerprint)
    ledger = SingleUseAuthorizationLedger()

    owner_claimed = Event()
    release_owner = Event()
    owner_errors: list[BaseException] = []

    original_claim = EphemeralScopeBindingKey.claim_preparation

    def gated_claim(self: EphemeralScopeBindingKey) -> None:
        original_claim(self)
        if self is key and not owner_claimed.is_set():
            owner_claimed.set()
            if not release_owner.wait(timeout=5.0):
                raise AssertionError("timed out waiting to release preparation owner")

    monkeypatch.setattr(EphemeralScopeBindingKey, "claim_preparation", gated_claim)

    def owner_attempt() -> None:
        try:
            prepare_one_shot_submission_envelope(
                request,
                decision,
                human,
                ledger=ledger,
                scope_binding_key=key,
                now_epoch_seconds=NOW,
            )
        except BaseException as exc:
            owner_errors.append(exc)

    owner = Thread(target=owner_attempt, daemon=True)
    owner.start()
    assert owner_claimed.wait(timeout=5.0)
    assert key.preparation_claimed is True
    assert key.destroyed is False

    for _ in range(8):
        with pytest.raises(
            ControlledExecutionValidationError,
            match="already claimed",
        ):
            prepare_one_shot_submission_envelope(
                request,
                decision,
                human,
                ledger=ledger,
                scope_binding_key=key,
                now_epoch_seconds=NOW,
            )
        assert key.destroyed is False

    release_owner.set()
    owner.join(timeout=5.0)

    assert owner.is_alive() is False
    assert owner_errors == []
    assert key.destroyed is True


def test_consumed_token_refuses_validation_replay() -> None:
    request = make_request()
    envelope = prepare(
        request,
        EphemeralScopeBindingKey.generate(),
        SingleUseAuthorizationLedger(),
    )

    validation = validate_single_use_authorization(
        envelope.consumed_authorization,
        expected_scope_fingerprint=(request.m9_single_use_authorization.scope_fingerprint),
        now_epoch_seconds=NOW,
    )
    assert validation.valid_for_separate_pre_send_confirmation is False


def test_human_evidence_does_not_claim_trusted_identity() -> None:
    authorization = make_human("0" * 64)
    assert authorization.trusted_human_identity_verified is False


def test_identifier_fields_reject_payload_like_text() -> None:
    with pytest.raises(
        ControlledExecutionValidationError,
        match="bounded identifier",
    ):
        HumanPreSendExecutionAuthorization(
            human_decision_reference="this is not an identifier with spaces",
            explicit_human_confirmation=True,
            approved_scope_fingerprint="0" * 64,
        )


def test_top_level_none_request_is_governed_error() -> None:
    with pytest.raises(
        ControlledExecutionValidationError,
        match="request must have the exact",
    ):
        evaluate_controlled_execution_readiness(
            cast(Any, None),
            scope_binding_key=EphemeralScopeBindingKey.generate(),
            now_epoch_seconds=NOW,
        )


def test_malformed_nested_m9_components_are_governed_errors() -> None:
    request = make_request()
    m9 = request.m9_readiness_request

    malformed_requests = (
        replace(m9, source=cast(Any, None)),
        replace(m9, participant=cast(Any, None)),
        replace(m9, minor_screening=cast(Any, None)),
        replace(m9, payload_route=cast(Any, None)),
        replace(m9, provider=cast(Any, None)),
        replace(m9, operator=cast(Any, None)),
    )

    for malformed_m9 in malformed_requests:
        with pytest.raises(
            ControlledExecutionValidationError,
            match="exact canonical type",
        ):
            ready(
                replace(request, m9_readiness_request=malformed_m9),
                EphemeralScopeBindingKey.generate(),
            )


def test_nested_source_object_is_type_checked_before_property_access() -> None:
    class RaisingSource:
        @property
        def source_type(self) -> str:
            raise RuntimeError("must never be accessed")

    request = make_request()
    malformed_m9 = replace(
        request.m9_readiness_request,
        source=cast(Any, RaisingSource()),
    )

    with pytest.raises(
        ControlledExecutionValidationError,
        match="source must have the exact canonical type",
    ):
        ready(
            replace(request, m9_readiness_request=malformed_m9),
            EphemeralScopeBindingKey.generate(),
        )


def test_huge_integer_timestamp_is_governed_before_json_serialization() -> None:
    request = make_request()
    changed_token = replace(
        request.m9_single_use_authorization,
        expires_at_epoch_seconds=10**5000,
    )

    with pytest.raises(
        ControlledExecutionValidationError,
        match="governed integer range",
    ):
        ready(
            replace(request, m9_single_use_authorization=changed_token),
            EphemeralScopeBindingKey.generate(),
        )


def test_recorder_rejects_malformed_input_without_burning_state() -> None:
    envelope = prepare(
        make_request(),
        EphemeralScopeBindingKey.generate(),
        SingleUseAuthorizationLedger(),
    )
    recorder = SyntheticOneShotSubmissionRecorder()

    with pytest.raises(
        ControlledExecutionValidationError,
        match="exact OneShotSubmissionEnvelope type",
    ):
        recorder.record(cast(Any, None))

    evidence = recorder.record(envelope)
    assert evidence.submission_count == 1


def test_uppercase_sha256_fingerprint_is_rejected_not_normalized() -> None:
    with pytest.raises(
        ControlledExecutionValidationError,
        match="lowercase SHA-256",
    ):
        HumanPreSendExecutionAuthorization(
            human_decision_reference="human-1",
            explicit_human_confirmation=True,
            approved_scope_fingerprint="A" * 64,
        )


def test_failed_prepare_destroys_scope_key() -> None:
    request = make_request()
    key = EphemeralScopeBindingKey.generate()
    decision = ready(request, key)

    with pytest.raises(
        ControlledExecutionValidationError,
        match="scope mismatch",
    ):
        prepare_one_shot_submission_envelope(
            request,
            decision,
            make_human("0" * 64),
            ledger=SingleUseAuthorizationLedger(),
            scope_binding_key=key,
            now_epoch_seconds=NOW,
        )

    assert key.destroyed is True


def test_controlled_execution_import_allowlist() -> None:
    module_path = Path(controlled_execution_module.__file__)
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    allowed_absolute = {
        "__future__",
        "copy",
        "hashlib",
        "hmac",
        "json",
        "re",
        "secrets",
        "dataclasses",
        "enum",
        "threading",
        "typing",
    }
    allowed_relative = {
        "errors",
        "execution_authorization",
        "real_data_readiness",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".", 1)[0] in allowed_absolute
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                assert node.module in allowed_relative
            else:
                assert node.module is not None
                assert node.module.split(".", 1)[0] in allowed_absolute
