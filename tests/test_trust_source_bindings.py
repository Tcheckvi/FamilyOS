"""Tests for the approved M10 Wave A offline trust-source profile."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from familyos_pilot0.controlled_execution import FinalMinorDataScreeningEvidence
from familyos_pilot0.real_data_wave_a import (
    FinalScreeningFreshnessPolicy,
    TrustedHumanAuthorizationReceipt,
)
from familyos_pilot0.trust_source_bindings import (
    HUMAN_RECEIPT_NAMESPACE,
    M10_FINAL_SCREENING_ALLOWED_FUTURE_SKEW_SECONDS,
    M10_FINAL_SCREENING_MAXIMUM_AGE_SECONDS,
    M10_FINAL_SCREENING_POLICY_IDENTIFIER,
    TIME_ATTESTATION_NAMESPACE,
    LocalRuntimeProviderConfiguration,
    OfflineSignatureVerificationError,
    OfflineSignedHumanReceiptVerifier,
    OfflineSshSignatureMaterial,
    SignedExternalTimeAttestationClock,
    SignedTimeAttestation,
    TrustSourceBindingValidationError,
    VerifiedLocalRuntimeProviderIdentitySource,
    approved_m10_final_screening_freshness_policy,
    bind_final_screening_temporal_evidence,
    canonical_human_authorization_receipt_payload,
    canonical_time_attestation_payload,
)

SCOPE = "a" * 64
CREDENTIAL_FINGERPRINT = "b" * 64
NOW = 2_000_000_000


def _ssh_keygen() -> str:
    executable = shutil.which("ssh-keygen")
    if executable is None:
        pytest.fail("approved offline profile requires ssh-keygen")
    return str(Path(executable).resolve())


def _signed_material(
    tmp_path: Path,
    *,
    principal: str,
    namespace: str,
    payload: bytes,
    stem: str,
) -> OfflineSshSignatureMaterial:
    ssh_keygen = _ssh_keygen()
    key_path = tmp_path / f"{stem}-key"
    payload_path = tmp_path / f"{stem}-payload"

    payload_path.write_bytes(payload)
    subprocess.run(
        [
            ssh_keygen,
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-f",
            str(key_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            ssh_keygen,
            "-Y",
            "sign",
            "-f",
            str(key_path),
            "-n",
            namespace,
            str(payload_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    public_key = Path(f"{key_path}.pub").read_text(encoding="utf-8").strip()
    signature = Path(f"{payload_path}.sig").read_text(encoding="utf-8")

    return OfflineSshSignatureMaterial(
        principal_identifier=principal,
        signature_text=signature,
        allowed_signers_text=f"{principal} {public_key}\n",
        ssh_keygen_path=ssh_keygen,
    )


def _time_attestation() -> SignedTimeAttestation:
    return SignedTimeAttestation(
        attestation_identifier="time-attestation-0001",
        authority_identifier="familyos-time-authority",
        scope_fingerprint=SCOPE,
        epoch_seconds=NOW,
    )


def _trusted_clock(tmp_path: Path) -> SignedExternalTimeAttestationClock:
    attestation = _time_attestation()
    material = _signed_material(
        tmp_path,
        principal=attestation.authority_identifier,
        namespace=TIME_ATTESTATION_NAMESPACE,
        payload=canonical_time_attestation_payload(attestation),
        stem="time",
    )
    return SignedExternalTimeAttestationClock(
        attestation=attestation,
        signature_material=material,
        expected_scope_fingerprint=SCOPE,
    )


def _receipt() -> TrustedHumanAuthorizationReceipt:
    return TrustedHumanAuthorizationReceipt(
        receipt_identifier="human-receipt-0001",
        verifier_identifier="familyos-human-authority",
        subject_identifier="operator-thierry",
        scope_fingerprint=SCOPE,
        issued_at_epoch_seconds=NOW - 10,
        expires_at_epoch_seconds=NOW + 120,
        decision_reference="m10-wave-a-human-decision-0001",
        integrity_proof_identifier="ssh-signature-0001",
    )


def test_signed_time_attestation_clock_verifies_offline_signature(
    tmp_path: Path,
) -> None:
    clock = _trusted_clock(tmp_path)

    evidence = clock.read_trusted_time()

    assert evidence.epoch_seconds == NOW
    assert evidence.source_identifier == "familyos-time-authority"
    assert evidence.source_attestation_identifier == "time-attestation-0001"


def test_signed_time_attestation_clock_rejects_tampered_attestation(
    tmp_path: Path,
) -> None:
    original = _time_attestation()
    material = _signed_material(
        tmp_path,
        principal=original.authority_identifier,
        namespace=TIME_ATTESTATION_NAMESPACE,
        payload=canonical_time_attestation_payload(original),
        stem="time-tampered",
    )
    tampered = replace(original, epoch_seconds=NOW + 1)
    clock = SignedExternalTimeAttestationClock(
        attestation=tampered,
        signature_material=material,
        expected_scope_fingerprint=SCOPE,
    )

    with pytest.raises(OfflineSignatureVerificationError):
        clock.read_trusted_time()


def test_signed_time_attestation_clock_rejects_scope_mismatch(
    tmp_path: Path,
) -> None:
    attestation = _time_attestation()
    material = _signed_material(
        tmp_path,
        principal=attestation.authority_identifier,
        namespace=TIME_ATTESTATION_NAMESPACE,
        payload=canonical_time_attestation_payload(attestation),
        stem="time-scope",
    )

    with pytest.raises(TrustSourceBindingValidationError):
        SignedExternalTimeAttestationClock(
            attestation=attestation,
            signature_material=material,
            expected_scope_fingerprint="c" * 64,
        )


def test_approved_rd05_policy_is_exactly_60_seconds_zero_future_skew() -> None:
    policy = approved_m10_final_screening_freshness_policy()

    assert policy.policy_identifier == M10_FINAL_SCREENING_POLICY_IDENTIFIER
    assert policy.maximum_age_seconds == M10_FINAL_SCREENING_MAXIMUM_AGE_SECONDS == 60
    assert (
        policy.allowed_future_skew_seconds == M10_FINAL_SCREENING_ALLOWED_FUTURE_SKEW_SECONDS == 0
    )


def test_final_screening_binding_uses_trusted_time() -> None:
    final_screening = FinalMinorDataScreeningEvidence(
        evidence_identifier="final-screening-0001",
        screening_complete=True,
        minor_data_detected=False,
        uncertainty_detected=False,
    )
    trusted_time = _time_attestation()
    policy = approved_m10_final_screening_freshness_policy()

    evidence = bind_final_screening_temporal_evidence(
        final_screening,
        scope_fingerprint=SCOPE,
        trusted_time=__import__(
            "familyos_pilot0.real_data_wave_a",
            fromlist=["TrustedTimeEvidence"],
        ).TrustedTimeEvidence(
            epoch_seconds=trusted_time.epoch_seconds,
            source_identifier=trusted_time.authority_identifier,
            source_attestation_identifier=trusted_time.attestation_identifier,
        ),
        policy=policy,
    )

    assert evidence.evidence_identifier == final_screening.evidence_identifier
    assert evidence.scope_fingerprint == SCOPE
    assert evidence.screened_at_epoch_seconds == NOW
    assert evidence.policy_identifier == M10_FINAL_SCREENING_POLICY_IDENTIFIER


def test_final_screening_binding_rejects_nonapproved_policy() -> None:
    final_screening = FinalMinorDataScreeningEvidence(
        evidence_identifier="final-screening-0002",
        screening_complete=True,
        minor_data_detected=False,
        uncertainty_detected=False,
    )
    trusted_time = __import__(
        "familyos_pilot0.real_data_wave_a",
        fromlist=["TrustedTimeEvidence"],
    ).TrustedTimeEvidence(
        epoch_seconds=NOW,
        source_identifier="familyos-time-authority",
        source_attestation_identifier="time-attestation-0002",
    )
    policy = FinalScreeningFreshnessPolicy(
        policy_identifier="different-policy",
        maximum_age_seconds=60,
        allowed_future_skew_seconds=0,
    )

    with pytest.raises(TrustSourceBindingValidationError):
        bind_final_screening_temporal_evidence(
            final_screening,
            scope_fingerprint=SCOPE,
            trusted_time=trusted_time,
            policy=policy,
        )


def test_local_runtime_provider_configuration_digest_and_capture(
    tmp_path: Path,
) -> None:
    clock = _trusted_clock(tmp_path)
    configuration = LocalRuntimeProviderConfiguration.create(
        source_identifier="pilot0-local-runtime-config",
        provider_identifier="openai",
        project_identifier="familyos-pilot0-project",
        model_identifier="approved-model-revision",
        credential_fingerprint=CREDENTIAL_FINGERPRINT,
        scope_fingerprint=SCOPE,
    )
    source = VerifiedLocalRuntimeProviderIdentitySource(
        configuration=configuration,
        trusted_clock=clock,
    )

    observed = source.capture_runtime_provider_identity()

    assert observed.provider_identifier == "openai"
    assert observed.project_identifier == "familyos-pilot0-project"
    assert observed.model_identifier == "approved-model-revision"
    assert observed.credential_fingerprint == CREDENTIAL_FINGERPRINT
    assert observed.scope_fingerprint == SCOPE
    assert observed.captured_at_epoch_seconds == NOW
    assert configuration.configuration_digest in observed.source_identifier


def test_local_runtime_provider_configuration_rejects_digest_tamper() -> None:
    configuration = LocalRuntimeProviderConfiguration.create(
        source_identifier="pilot0-local-runtime-config",
        provider_identifier="openai",
        project_identifier="familyos-pilot0-project",
        model_identifier="approved-model-revision",
        credential_fingerprint=CREDENTIAL_FINGERPRINT,
        scope_fingerprint=SCOPE,
    )

    with pytest.raises(TrustSourceBindingValidationError):
        replace(configuration, model_identifier="tampered-model")


def test_offline_signed_human_receipt_verifier_accepts_valid_receipt(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    material = _signed_material(
        tmp_path,
        principal=receipt.verifier_identifier,
        namespace=HUMAN_RECEIPT_NAMESPACE,
        payload=canonical_human_authorization_receipt_payload(receipt),
        stem="human",
    )
    verifier = OfflineSignedHumanReceiptVerifier(
        receipt_identifier=receipt.receipt_identifier,
        signature_material=material,
    )
    trusted_time = _trusted_clock(tmp_path).read_trusted_time()

    verified = verifier.verify(receipt, trusted_time=trusted_time)

    assert verified.receipt_identifier == receipt.receipt_identifier
    assert verified.verifier_identifier == receipt.verifier_identifier
    assert verified.subject_identifier == receipt.subject_identifier
    assert verified.scope_fingerprint == SCOPE
    assert verified.verified_at_epoch_seconds == NOW


def test_offline_signed_human_receipt_verifier_rejects_tampering(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    material = _signed_material(
        tmp_path,
        principal=receipt.verifier_identifier,
        namespace=HUMAN_RECEIPT_NAMESPACE,
        payload=canonical_human_authorization_receipt_payload(receipt),
        stem="human-tampered",
    )
    verifier = OfflineSignedHumanReceiptVerifier(
        receipt_identifier=receipt.receipt_identifier,
        signature_material=material,
    )
    trusted_time = _trusted_clock(tmp_path).read_trusted_time()
    tampered = replace(receipt, subject_identifier="operator-other")

    with pytest.raises(OfflineSignatureVerificationError):
        verifier.verify(tampered, trusted_time=trusted_time)


def test_offline_signed_human_receipt_verifier_rejects_expired_receipt(
    tmp_path: Path,
) -> None:
    receipt = replace(_receipt(), expires_at_epoch_seconds=NOW)
    material = _signed_material(
        tmp_path,
        principal=receipt.verifier_identifier,
        namespace=HUMAN_RECEIPT_NAMESPACE,
        payload=canonical_human_authorization_receipt_payload(receipt),
        stem="human-expired",
    )
    verifier = OfflineSignedHumanReceiptVerifier(
        receipt_identifier=receipt.receipt_identifier,
        signature_material=material,
    )
    trusted_time = _trusted_clock(tmp_path).read_trusted_time()

    with pytest.raises(OfflineSignatureVerificationError):
        verifier.verify(receipt, trusted_time=trusted_time)


def test_signature_material_repr_excludes_signature_and_allowed_signers(
    tmp_path: Path,
) -> None:
    attestation = _time_attestation()
    material = _signed_material(
        tmp_path,
        principal=attestation.authority_identifier,
        namespace=TIME_ATTESTATION_NAMESPACE,
        payload=canonical_time_attestation_payload(attestation),
        stem="repr",
    )

    rendered = repr(material)

    assert "BEGIN SSH SIGNATURE" not in rendered
    assert "ssh-ed25519" not in rendered
    assert "signature_text" not in rendered
    assert "allowed_signers_text" not in rendered


# RD-01 trust guards remain outside the receipt-owned serializer.


def _rd01_trust_guard_fixture(index: int) -> TrustedHumanAuthorizationReceipt:
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


def test_rd01_legacy_helper_delegates_to_receipt_canonical_method() -> None:
    from familyos_pilot0.trust_source_bindings import (
        canonical_human_authorization_receipt_payload,
    )

    for index in range(1, 4):
        receipt = _rd01_trust_guard_fixture(index)
        assert (
            canonical_human_authorization_receipt_payload(receipt)
            == receipt.canonical_payload_bytes()
        )


def test_rd01_legacy_helper_preserves_exact_type_guard() -> None:
    from familyos_pilot0.real_data_wave_a import TrustedHumanAuthorizationReceipt
    from familyos_pilot0.trust_source_bindings import (
        TrustSourceBindingValidationError,
        canonical_human_authorization_receipt_payload,
    )

    class ReceiptSubclass(TrustedHumanAuthorizationReceipt):
        pass

    base = _rd01_trust_guard_fixture(1)
    receipt = ReceiptSubclass(
        receipt_identifier=base.receipt_identifier,
        verifier_identifier=base.verifier_identifier,
        subject_identifier=base.subject_identifier,
        scope_fingerprint=base.scope_fingerprint,
        issued_at_epoch_seconds=base.issued_at_epoch_seconds,
        expires_at_epoch_seconds=base.expires_at_epoch_seconds,
        decision_reference=base.decision_reference,
        integrity_proof_identifier=base.integrity_proof_identifier,
    )
    try:
        canonical_human_authorization_receipt_payload(receipt)
    except TrustSourceBindingValidationError:
        pass
    else:
        raise AssertionError("exact-type guard was not preserved")


def test_rd01_legacy_helper_preserves_defensive_size_guard() -> None:
    from familyos_pilot0.trust_source_bindings import (
        TrustSourceBindingValidationError,
        canonical_human_authorization_receipt_payload,
    )

    receipt = _rd01_trust_guard_fixture(1)
    object.__setattr__(receipt, "decision_reference", "X" * 20000)
    try:
        canonical_human_authorization_receipt_payload(receipt)
    except TrustSourceBindingValidationError:
        pass
    else:
        raise AssertionError("defensive payload-size guard was not preserved")
