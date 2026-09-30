"""Tests for M10 real-data readiness Wave A. No network or provider calls."""

from __future__ import annotations

from dataclasses import replace

import pytest

from familyos_pilot0.controlled_execution import (
    ControlledExecutionAuditEvidence,
    ControlledExecutionReadinessDecision,
    ControlledExecutionReadinessState,
    FinalMinorDataScreeningEvidence,
)
from familyos_pilot0.execution_authorization import SingleUseTokenValidationState
from familyos_pilot0.real_data_wave_a import (
    ApprovedProviderIdentityBinding,
    FinalScreeningFreshnessPolicy,
    FinalScreeningTemporalEvidence,
    ObservedRuntimeProviderIdentity,
    RuntimeProviderIdentitySource,
    TrustedExecutionClock,
    TrustedHumanAuthorizationReceipt,
    TrustedHumanReceiptVerifier,
    TrustedHumanVerifierPolicy,
    TrustedTimeEvidence,
    VerifiedHumanAuthorization,
    WaveARealDataReadinessDecision,
    WaveARealDataReadinessState,
    credential_fingerprint_from_secret,
    evaluate_wave_a_real_data_readiness,
)

NOW = 2_000_000_000
SCOPE = "a" * 64
CREDENTIAL_FINGERPRINT = "b" * 64


class StubClock:
    def __init__(self, evidence: TrustedTimeEvidence) -> None:
        self._evidence = evidence

    def read_trusted_time(self) -> TrustedTimeEvidence:
        return self._evidence


class RaisingClock:
    def read_trusted_time(self) -> TrustedTimeEvidence:
        raise RuntimeError("trusted time unavailable")


class StubProviderSource:
    def __init__(self, evidence: ObservedRuntimeProviderIdentity) -> None:
        self._evidence = evidence

    def capture_runtime_provider_identity(self) -> ObservedRuntimeProviderIdentity:
        return self._evidence


class RaisingProviderSource:
    def capture_runtime_provider_identity(self) -> ObservedRuntimeProviderIdentity:
        raise RuntimeError("runtime provider identity unavailable")


class StubVerifier:
    def verify(
        self,
        receipt: TrustedHumanAuthorizationReceipt,
        *,
        trusted_time: TrustedTimeEvidence,
    ) -> VerifiedHumanAuthorization:
        return VerifiedHumanAuthorization(
            receipt_identifier=receipt.receipt_identifier,
            verifier_identifier=receipt.verifier_identifier,
            subject_identifier=receipt.subject_identifier,
            scope_fingerprint=receipt.scope_fingerprint,
            verified_at_epoch_seconds=trusted_time.epoch_seconds,
        )


class RaisingVerifier:
    def verify(
        self,
        receipt: TrustedHumanAuthorizationReceipt,
        *,
        trusted_time: TrustedTimeEvidence,
    ) -> VerifiedHumanAuthorization:
        del receipt, trusted_time
        raise RuntimeError("receipt verification failed")


def make_m10_decision(
    state: ControlledExecutionReadinessState = (
        ControlledExecutionReadinessState.READY_FOR_EXPLICIT_HUMAN_PRE_SEND_AUTHORIZATION
    ),
) -> ControlledExecutionReadinessDecision:
    audit = ControlledExecutionAuditEvidence(
        ephemeral_correlation_identifier="corr-wave-a-001",
        pseudonymous_participant_reference="participant-wave-a-001",
        provider_route_identifier="openai-familyos-reviewed-route",
        scope_fingerprint=SCOPE,
        state=state,
        reasons=(),
        m9_token_validation_state=(
            SingleUseTokenValidationState.VALID_FOR_SEPARATE_PRE_SEND_CONFIRMATION
        ),
    )
    return ControlledExecutionReadinessDecision(
        state=state,
        reasons=(),
        scope_fingerprint=SCOPE,
        audit_evidence=audit,
    )


def make_screening() -> FinalMinorDataScreeningEvidence:
    return FinalMinorDataScreeningEvidence(
        evidence_identifier="final-screen-wave-a-001",
        screening_complete=True,
        minor_data_detected=False,
        uncertainty_detected=False,
    )


def make_clock() -> StubClock:
    return StubClock(
        TrustedTimeEvidence(
            epoch_seconds=NOW,
            source_identifier="trusted-clock-test-authority",
            source_attestation_identifier="clock-attestation-001",
        )
    )


def make_policy() -> FinalScreeningFreshnessPolicy:
    return FinalScreeningFreshnessPolicy(
        policy_identifier="final-screen-policy-v1",
        maximum_age_seconds=60,
        allowed_future_skew_seconds=0,
    )


def make_temporal_evidence() -> FinalScreeningTemporalEvidence:
    return FinalScreeningTemporalEvidence(
        evidence_identifier="final-screen-wave-a-001",
        scope_fingerprint=SCOPE,
        screened_at_epoch_seconds=NOW - 5,
        policy_identifier="final-screen-policy-v1",
    )


def make_approved_provider() -> ApprovedProviderIdentityBinding:
    return ApprovedProviderIdentityBinding(
        binding_identifier="provider-binding-001",
        provider_identifier="openai",
        project_identifier="familyos-project-001",
        model_identifier="familyos-reviewed-model-001",
        credential_fingerprint=CREDENTIAL_FINGERPRINT,
        scope_fingerprint=SCOPE,
    )


def make_observed_provider() -> ObservedRuntimeProviderIdentity:
    return ObservedRuntimeProviderIdentity(
        source_identifier="runtime-provider-config-001",
        provider_identifier="openai",
        project_identifier="familyos-project-001",
        model_identifier="familyos-reviewed-model-001",
        credential_fingerprint=CREDENTIAL_FINGERPRINT,
        scope_fingerprint=SCOPE,
        captured_at_epoch_seconds=NOW,
    )


def make_receipt() -> TrustedHumanAuthorizationReceipt:
    return TrustedHumanAuthorizationReceipt(
        receipt_identifier="human-receipt-001",
        verifier_identifier="trusted-human-verifier-001",
        subject_identifier="operator-001",
        scope_fingerprint=SCOPE,
        issued_at_epoch_seconds=NOW - 30,
        expires_at_epoch_seconds=NOW + 30,
        decision_reference="human-decision-001",
        integrity_proof_identifier="receipt-proof-001",
    )


def make_verifier_policy() -> TrustedHumanVerifierPolicy:
    return TrustedHumanVerifierPolicy(trusted_verifier_identifiers=("trusted-human-verifier-001",))


def evaluate(
    *,
    m10_decision: ControlledExecutionReadinessDecision | None = None,
    screening: FinalMinorDataScreeningEvidence | None = None,
    clock: TrustedExecutionClock | None = None,
    policy: FinalScreeningFreshnessPolicy | None = None,
    temporal: FinalScreeningTemporalEvidence | None = None,
    approved_provider: ApprovedProviderIdentityBinding | None = None,
    provider_source: RuntimeProviderIdentitySource | None = None,
    receipt: TrustedHumanAuthorizationReceipt | None = None,
    verifier_policy: TrustedHumanVerifierPolicy | None = None,
    verifier: TrustedHumanReceiptVerifier | None = None,
) -> WaveARealDataReadinessDecision:
    return evaluate_wave_a_real_data_readiness(
        m10_decision or make_m10_decision(),
        screening or make_screening(),
        trusted_clock=clock or make_clock(),
        freshness_policy=policy or make_policy(),
        temporal_evidence=temporal or make_temporal_evidence(),
        approved_provider=approved_provider or make_approved_provider(),
        runtime_provider_source=(provider_source or StubProviderSource(make_observed_provider())),
        human_receipt=receipt or make_receipt(),
        verifier_policy=verifier_policy or make_verifier_policy(),
        human_receipt_verifier=verifier or StubVerifier(),
    )


def test_wave_a_ready_path_never_authorizes_execution() -> None:
    decision = evaluate()

    assert (
        decision.state
        is WaveARealDataReadinessState.READY_FOR_SEPARATE_REAL_EXECUTION_AUTHORIZATION
    )
    assert decision.reasons == ()
    assert decision.ready_for_separate_real_execution_authorization is True
    assert decision.execution_authorized is False
    assert decision.audit_evidence.credential_fingerprint == CREDENTIAL_FINGERPRINT


def test_wave_a_requires_existing_m10_readiness() -> None:
    decision = evaluate(m10_decision=make_m10_decision(ControlledExecutionReadinessState.DENY))

    assert decision.state is WaveARealDataReadinessState.DENY
    assert "m10_controlled_execution_not_ready" in decision.reasons


def test_rd04_trusted_clock_unavailability_fails_closed() -> None:
    decision = evaluate(clock=RaisingClock())

    assert decision.state is WaveARealDataReadinessState.DENY
    assert decision.reasons == ("trusted_execution_clock_unavailable",)


@pytest.mark.parametrize(
    ("temporal", "expected_reason"),
    [
        (
            replace(
                make_temporal_evidence(),
                screened_at_epoch_seconds=NOW - 61,
            ),
            "final_screening_evidence_stale",
        ),
        (
            replace(
                make_temporal_evidence(),
                screened_at_epoch_seconds=NOW + 1,
            ),
            "final_screening_timestamp_from_future",
        ),
        (
            replace(
                make_temporal_evidence(),
                scope_fingerprint="c" * 64,
            ),
            "final_screening_scope_mismatch",
        ),
        (
            replace(
                make_temporal_evidence(),
                policy_identifier="other-policy",
            ),
            "final_screening_policy_mismatch",
        ),
    ],
)
def test_rd05_final_screening_freshness_fails_closed(
    temporal: FinalScreeningTemporalEvidence,
    expected_reason: str,
) -> None:
    decision = evaluate(temporal=temporal)

    assert decision.state is WaveARealDataReadinessState.DENY
    assert expected_reason in decision.reasons


def test_rd05_final_screening_identifier_is_bound() -> None:
    decision = evaluate(
        temporal=replace(
            make_temporal_evidence(),
            evidence_identifier="other-final-screen",
        )
    )

    assert "final_screening_evidence_identifier_mismatch" in decision.reasons


@pytest.mark.parametrize(
    ("observed", "expected_reason"),
    [
        (
            replace(make_observed_provider(), provider_identifier="other-provider"),
            "runtime_provider_identifier_mismatch",
        ),
        (
            replace(make_observed_provider(), project_identifier="other-project"),
            "runtime_project_identifier_mismatch",
        ),
        (
            replace(make_observed_provider(), model_identifier="other-model"),
            "runtime_model_identifier_mismatch",
        ),
        (
            replace(
                make_observed_provider(),
                credential_fingerprint="d" * 64,
            ),
            "runtime_credential_identity_mismatch",
        ),
        (
            replace(make_observed_provider(), scope_fingerprint="e" * 64),
            "runtime_provider_scope_mismatch",
        ),
    ],
)
def test_rd06_exact_runtime_provider_binding_fails_closed(
    observed: ObservedRuntimeProviderIdentity,
    expected_reason: str,
) -> None:
    decision = evaluate(provider_source=StubProviderSource(observed))

    assert decision.state is WaveARealDataReadinessState.DENY
    assert expected_reason in decision.reasons


def test_rd06_provider_identity_unavailability_fails_closed() -> None:
    decision = evaluate(provider_source=RaisingProviderSource())

    assert "runtime_provider_identity_unavailable" in decision.reasons


def test_rd01_untrusted_verifier_is_not_called_or_accepted() -> None:
    receipt = replace(make_receipt(), verifier_identifier="untrusted-verifier")
    decision = evaluate(receipt=receipt)

    assert decision.state is WaveARealDataReadinessState.DENY
    assert "human_receipt_untrusted_verifier" in decision.reasons


def test_rd01_receipt_scope_and_expiry_are_bound_to_trusted_time() -> None:
    scope_mismatch = evaluate(receipt=replace(make_receipt(), scope_fingerprint="f" * 64))
    expired = evaluate(
        receipt=replace(
            make_receipt(),
            issued_at_epoch_seconds=NOW - 60,
            expires_at_epoch_seconds=NOW,
        )
    )

    assert "human_receipt_scope_mismatch" in scope_mismatch.reasons
    assert "human_receipt_expired" in expired.reasons


def test_rd01_external_verifier_failure_fails_closed() -> None:
    decision = evaluate(verifier=RaisingVerifier())

    assert decision.state is WaveARealDataReadinessState.DENY
    assert "human_receipt_verification_failed" in decision.reasons


def test_credential_fingerprint_does_not_persist_raw_secret() -> None:
    raw_secret = "synthetic-secret-not-a-real-credential"
    fingerprint = credential_fingerprint_from_secret(raw_secret)
    binding = replace(
        make_approved_provider(),
        credential_fingerprint=fingerprint,
    )

    assert fingerprint != raw_secret
    assert len(fingerprint) == 64
    assert raw_secret not in repr(binding)


# RD-01 canonical payload regression fingerprints frozen before migration.
_RD01_CANONICAL_PAYLOAD_SHA256 = (
    "b1a143a1c1d8dd2826322288f251cac258ed6873d1aeff30268871d2fb5ea662",
    "e3450cdd579df4101bf93c3048f6fe849a3eedb565667dbf5a7f18d9b7281f51",
    "1fca9bd1ee611781daed06f976c24e779485cf2f3a4481f09cfc215acaa63ed5",
)
_RD01_CANONICAL_PAYLOAD_LENGTHS = (
    437,
    437,
    437,
)


def _rd01_canonical_fixture(index: int) -> TrustedHumanAuthorizationReceipt:
    from familyos_pilot0.real_data_wave_a import TrustedHumanAuthorizationReceipt

    issued = 1800000000 + index * 100
    return TrustedHumanAuthorizationReceipt(
        receipt_identifier=f"canonical-contract-fixture-{index}",
        verifier_identifier="familyos-m10-rd01-human-verifier-v1",
        subject_identifier=f"fixture-subject-{index}",
        scope_fingerprint=f"{index:064x}",
        issued_at_epoch_seconds=issued,
        expires_at_epoch_seconds=issued + 60,
        decision_reference=f"FIXTURE-DECISION-{index}",
        integrity_proof_identifier=f"fixture-proof-{index}",
    )


def test_rd01_canonical_payload_bytes_matches_frozen_legacy_fingerprints() -> None:
    import hashlib

    for index, expected_digest in enumerate(
        _RD01_CANONICAL_PAYLOAD_SHA256,
        start=1,
    ):
        receipt = _rd01_canonical_fixture(index)
        payload = receipt.canonical_payload_bytes()
        assert isinstance(payload, bytes)
        assert len(payload) == _RD01_CANONICAL_PAYLOAD_LENGTHS[index - 1]
        assert hashlib.sha256(payload).hexdigest() == expected_digest


def test_rd01_canonical_payload_bytes_is_deterministic() -> None:
    receipt = _rd01_canonical_fixture(1)
    assert receipt.canonical_payload_bytes() == receipt.canonical_payload_bytes()
