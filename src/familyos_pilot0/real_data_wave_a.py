"""Fail-closed M10 real-data readiness boundary for Wave A.

Wave A implements local contracts for:

- RD-01: trusted human identity / authorization receipt;
- RD-04: trusted execution clock;
- RD-05: final-screening freshness;
- RD-06: exact provider/project/model/credential identity binding.

This module performs no provider call and does not authorize real-data
execution. It consumes the existing M10 controlled-execution readiness
decision and produces a separate Wave A decision whose
``execution_authorized`` property is always ``False``.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .controlled_execution import (
    ControlledExecutionReadinessDecision,
    FinalMinorDataScreeningEvidence,
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_GOVERNED_INT = (1 << 63) - 1


class WaveARealDataValidationError(ValueError):
    """Raised when Wave A receives malformed governed input."""


def _require_exact_string(name: str, value: object) -> str:
    if type(value) is not str:
        raise WaveARealDataValidationError(f"{name} must be an exact string")
    if not value.strip():
        raise WaveARealDataValidationError(f"{name} must not be blank")
    return value


def _require_identifier(name: str, value: object) -> str:
    normalized = _require_exact_string(name, value)
    if _IDENTIFIER_RE.fullmatch(normalized) is None:
        raise WaveARealDataValidationError(f"{name} must be a bounded identifier")
    return normalized


def _require_sha256_hex(name: str, value: object) -> str:
    normalized = _require_exact_string(name, value)
    if normalized != normalized.lower() or _SHA256_HEX_RE.fullmatch(normalized) is None:
        raise WaveARealDataValidationError(f"{name} must be a lowercase SHA-256 hexadecimal value")
    return normalized


def _require_exact_nonnegative_int(name: str, value: object) -> int:
    if type(value) is not int:
        raise WaveARealDataValidationError(f"{name} must be an exact int")
    if value < 0:
        raise WaveARealDataValidationError(f"{name} must be non-negative")
    if value > _MAX_GOVERNED_INT:
        raise WaveARealDataValidationError(f"{name} exceeds the governed integer range")
    return value


def credential_fingerprint_from_secret(secret: str) -> str:
    """Derive a non-secret identity fingerprint without retaining the secret."""

    normalized = _require_exact_string("credential_secret", secret)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TrustedTimeEvidence:
    """One observation from a separately trusted execution-time source."""

    epoch_seconds: int
    source_identifier: str
    source_attestation_identifier: str

    def __post_init__(self) -> None:
        _require_exact_nonnegative_int("epoch_seconds", self.epoch_seconds)
        object.__setattr__(
            self,
            "source_identifier",
            _require_identifier("source_identifier", self.source_identifier),
        )
        object.__setattr__(
            self,
            "source_attestation_identifier",
            _require_identifier(
                "source_attestation_identifier",
                self.source_attestation_identifier,
            ),
        )


class TrustedExecutionClock(Protocol):
    """Boundary implemented by a trusted clock source outside this module."""

    def read_trusted_time(self) -> TrustedTimeEvidence:
        """Return trusted execution time or raise when trust is unavailable."""
        ...


@dataclass(frozen=True)
class FinalScreeningFreshnessPolicy:
    """Maximum-age policy for immediately pre-send screening evidence."""

    policy_identifier: str
    maximum_age_seconds: int
    allowed_future_skew_seconds: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "policy_identifier",
            _require_identifier("policy_identifier", self.policy_identifier),
        )
        maximum_age = _require_exact_nonnegative_int(
            "maximum_age_seconds",
            self.maximum_age_seconds,
        )
        if maximum_age == 0:
            raise WaveARealDataValidationError("maximum_age_seconds must be greater than zero")
        _require_exact_nonnegative_int(
            "allowed_future_skew_seconds",
            self.allowed_future_skew_seconds,
        )


@dataclass(frozen=True)
class FinalScreeningTemporalEvidence:
    """Trusted temporal binding for one final-screening result."""

    evidence_identifier: str
    scope_fingerprint: str
    screened_at_epoch_seconds: int
    policy_identifier: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_identifier",
            _require_identifier("evidence_identifier", self.evidence_identifier),
        )
        object.__setattr__(
            self,
            "scope_fingerprint",
            _require_sha256_hex("scope_fingerprint", self.scope_fingerprint),
        )
        _require_exact_nonnegative_int(
            "screened_at_epoch_seconds",
            self.screened_at_epoch_seconds,
        )
        object.__setattr__(
            self,
            "policy_identifier",
            _require_identifier("policy_identifier", self.policy_identifier),
        )


@dataclass(frozen=True)
class ApprovedProviderIdentityBinding:
    """Approved exact provider identities for one execution scope."""

    binding_identifier: str
    provider_identifier: str
    project_identifier: str
    model_identifier: str
    credential_fingerprint: str
    scope_fingerprint: str

    def __post_init__(self) -> None:
        for name in (
            "binding_identifier",
            "provider_identifier",
            "project_identifier",
            "model_identifier",
        ):
            object.__setattr__(
                self,
                name,
                _require_identifier(name, getattr(self, name)),
            )
        object.__setattr__(
            self,
            "credential_fingerprint",
            _require_sha256_hex(
                "credential_fingerprint",
                self.credential_fingerprint,
            ),
        )
        object.__setattr__(
            self,
            "scope_fingerprint",
            _require_sha256_hex("scope_fingerprint", self.scope_fingerprint),
        )


@dataclass(frozen=True)
class ObservedRuntimeProviderIdentity:
    """Observed effective provider identities captured before transmission."""

    source_identifier: str
    provider_identifier: str
    project_identifier: str
    model_identifier: str
    credential_fingerprint: str
    scope_fingerprint: str
    captured_at_epoch_seconds: int

    def __post_init__(self) -> None:
        for name in (
            "source_identifier",
            "provider_identifier",
            "project_identifier",
            "model_identifier",
        ):
            object.__setattr__(
                self,
                name,
                _require_identifier(name, getattr(self, name)),
            )
        object.__setattr__(
            self,
            "credential_fingerprint",
            _require_sha256_hex(
                "credential_fingerprint",
                self.credential_fingerprint,
            ),
        )
        object.__setattr__(
            self,
            "scope_fingerprint",
            _require_sha256_hex("scope_fingerprint", self.scope_fingerprint),
        )
        _require_exact_nonnegative_int(
            "captured_at_epoch_seconds",
            self.captured_at_epoch_seconds,
        )


class RuntimeProviderIdentitySource(Protocol):
    """Boundary that observes effective runtime identities without transmitting."""

    def capture_runtime_provider_identity(self) -> ObservedRuntimeProviderIdentity:
        """Return effective provider identities or raise when unavailable."""
        ...


@dataclass(frozen=True)
class TrustedHumanAuthorizationReceipt:
    """Receipt issued by an external trusted human-authorization authority."""

    receipt_identifier: str
    verifier_identifier: str
    subject_identifier: str
    scope_fingerprint: str
    issued_at_epoch_seconds: int
    expires_at_epoch_seconds: int
    decision_reference: str
    integrity_proof_identifier: str

    def __post_init__(self) -> None:
        for name in (
            "receipt_identifier",
            "verifier_identifier",
            "subject_identifier",
            "decision_reference",
            "integrity_proof_identifier",
        ):
            object.__setattr__(
                self,
                name,
                _require_identifier(name, getattr(self, name)),
            )
        object.__setattr__(
            self,
            "scope_fingerprint",
            _require_sha256_hex("scope_fingerprint", self.scope_fingerprint),
        )
        issued = _require_exact_nonnegative_int(
            "issued_at_epoch_seconds",
            self.issued_at_epoch_seconds,
        )
        expires = _require_exact_nonnegative_int(
            "expires_at_epoch_seconds",
            self.expires_at_epoch_seconds,
        )
        if expires <= issued:
            raise WaveARealDataValidationError(
                "expires_at_epoch_seconds must be greater than issued_at_epoch_seconds"
            )

    def canonical_payload_bytes(self) -> bytes:

        def _canonical_payload_local(lines: tuple[tuple[str, str], ...]) -> bytes:
            payload = "".join((f"{key}={value}\n" for key, value in lines)).encode("utf-8")
            return payload

        HUMAN_RECEIPT_NAMESPACE = "familyos-m10-wave-a-human-authorization-v1"
        return _canonical_payload_local(
            (
                ("version", "1"),
                ("purpose", HUMAN_RECEIPT_NAMESPACE),
                ("receipt_identifier", self.receipt_identifier),
                ("verifier_identifier", self.verifier_identifier),
                ("subject_identifier", self.subject_identifier),
                ("scope_fingerprint", self.scope_fingerprint),
                ("issued_at_epoch_seconds", str(self.issued_at_epoch_seconds)),
                ("expires_at_epoch_seconds", str(self.expires_at_epoch_seconds)),
                ("decision_reference", self.decision_reference),
                ("integrity_proof_identifier", self.integrity_proof_identifier),
            )
        )


@dataclass(frozen=True)
class VerifiedHumanAuthorization:
    """Verified result returned by an external trusted receipt verifier."""

    receipt_identifier: str
    verifier_identifier: str
    subject_identifier: str
    scope_fingerprint: str
    verified_at_epoch_seconds: int

    def __post_init__(self) -> None:
        for name in (
            "receipt_identifier",
            "verifier_identifier",
            "subject_identifier",
        ):
            object.__setattr__(
                self,
                name,
                _require_identifier(name, getattr(self, name)),
            )
        object.__setattr__(
            self,
            "scope_fingerprint",
            _require_sha256_hex("scope_fingerprint", self.scope_fingerprint),
        )
        _require_exact_nonnegative_int(
            "verified_at_epoch_seconds",
            self.verified_at_epoch_seconds,
        )


@dataclass(frozen=True)
class TrustedHumanVerifierPolicy:
    """Explicit allow-list of trusted external verifier identities."""

    trusted_verifier_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.trusted_verifier_identifiers) is not tuple:
            raise WaveARealDataValidationError(
                "trusted_verifier_identifiers must be an exact tuple"
            )
        normalized = tuple(
            _require_identifier("trusted_verifier_identifier", item)
            for item in self.trusted_verifier_identifiers
        )
        if not normalized:
            raise WaveARealDataValidationError("trusted_verifier_identifiers must not be empty")
        if len(set(normalized)) != len(normalized):
            raise WaveARealDataValidationError(
                "trusted_verifier_identifiers must not contain duplicates"
            )
        object.__setattr__(self, "trusted_verifier_identifiers", normalized)


class TrustedHumanReceiptVerifier(Protocol):
    """External verifier boundary; no local boolean can replace verification."""

    def verify(
        self,
        receipt: TrustedHumanAuthorizationReceipt,
        *,
        trusted_time: TrustedTimeEvidence,
    ) -> VerifiedHumanAuthorization:
        """Verify receipt authenticity or raise when verification fails."""
        ...


class WaveARealDataReadinessState(StrEnum):
    """Wave A pre-transmission readiness state."""

    DENY = "DENY"
    READY_FOR_SEPARATE_REAL_EXECUTION_AUTHORIZATION = (
        "READY_FOR_SEPARATE_REAL_EXECUTION_AUTHORIZATION"
    )


@dataclass(frozen=True)
class WaveARealDataAuditEvidence:
    """Raw-secret-free Wave A audit evidence."""

    scope_fingerprint: str
    trusted_time_source_identifier: str | None
    final_screening_evidence_identifier: str
    provider_identifier: str | None
    project_identifier: str | None
    model_identifier: str | None
    credential_fingerprint: str | None
    provider_identity_source_identifier: str | None
    human_receipt_identifier: str | None
    human_verifier_identifier: str | None
    human_subject_identifier: str | None
    state: WaveARealDataReadinessState
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class WaveARealDataReadinessDecision:
    """Wave A decision; readiness never authorizes or performs execution."""

    state: WaveARealDataReadinessState
    reasons: tuple[str, ...]
    scope_fingerprint: str
    audit_evidence: WaveARealDataAuditEvidence

    @property
    def ready_for_separate_real_execution_authorization(self) -> bool:
        return (
            self.state
            is WaveARealDataReadinessState.READY_FOR_SEPARATE_REAL_EXECUTION_AUTHORIZATION
        )

    @property
    def execution_authorized(self) -> bool:
        return False


def _decision(
    *,
    scope_fingerprint: str,
    final_screening_evidence_identifier: str,
    reasons: list[str],
    trusted_time: TrustedTimeEvidence | None,
    observed_provider: ObservedRuntimeProviderIdentity | None,
    verified_human: VerifiedHumanAuthorization | None,
) -> WaveARealDataReadinessDecision:
    reasons_tuple = tuple(reasons)
    state = (
        WaveARealDataReadinessState.DENY
        if reasons_tuple
        else WaveARealDataReadinessState.READY_FOR_SEPARATE_REAL_EXECUTION_AUTHORIZATION
    )
    audit = WaveARealDataAuditEvidence(
        scope_fingerprint=scope_fingerprint,
        trusted_time_source_identifier=(
            None if trusted_time is None else trusted_time.source_identifier
        ),
        final_screening_evidence_identifier=final_screening_evidence_identifier,
        provider_identifier=(
            None if observed_provider is None else observed_provider.provider_identifier
        ),
        project_identifier=(
            None if observed_provider is None else observed_provider.project_identifier
        ),
        model_identifier=(
            None if observed_provider is None else observed_provider.model_identifier
        ),
        credential_fingerprint=(
            None if observed_provider is None else observed_provider.credential_fingerprint
        ),
        provider_identity_source_identifier=(
            None if observed_provider is None else observed_provider.source_identifier
        ),
        human_receipt_identifier=(
            None if verified_human is None else verified_human.receipt_identifier
        ),
        human_verifier_identifier=(
            None if verified_human is None else verified_human.verifier_identifier
        ),
        human_subject_identifier=(
            None if verified_human is None else verified_human.subject_identifier
        ),
        state=state,
        reasons=reasons_tuple,
    )
    return WaveARealDataReadinessDecision(
        state=state,
        reasons=reasons_tuple,
        scope_fingerprint=scope_fingerprint,
        audit_evidence=audit,
    )


def evaluate_wave_a_real_data_readiness(
    m10_decision: ControlledExecutionReadinessDecision,
    final_screening: FinalMinorDataScreeningEvidence,
    *,
    trusted_clock: TrustedExecutionClock,
    freshness_policy: FinalScreeningFreshnessPolicy,
    temporal_evidence: FinalScreeningTemporalEvidence,
    approved_provider: ApprovedProviderIdentityBinding,
    runtime_provider_source: RuntimeProviderIdentitySource,
    human_receipt: TrustedHumanAuthorizationReceipt,
    verifier_policy: TrustedHumanVerifierPolicy,
    human_receipt_verifier: TrustedHumanReceiptVerifier,
) -> WaveARealDataReadinessDecision:
    """Evaluate Wave A contracts without executing or transmitting anything."""

    if type(m10_decision) is not ControlledExecutionReadinessDecision:
        raise WaveARealDataValidationError(
            "m10_decision must have the exact ControlledExecutionReadinessDecision type"
        )
    if type(final_screening) is not FinalMinorDataScreeningEvidence:
        raise WaveARealDataValidationError(
            "final_screening must have the exact FinalMinorDataScreeningEvidence type"
        )
    if type(freshness_policy) is not FinalScreeningFreshnessPolicy:
        raise WaveARealDataValidationError(
            "freshness_policy must have the exact FinalScreeningFreshnessPolicy type"
        )
    if type(temporal_evidence) is not FinalScreeningTemporalEvidence:
        raise WaveARealDataValidationError(
            "temporal_evidence must have the exact FinalScreeningTemporalEvidence type"
        )
    if type(approved_provider) is not ApprovedProviderIdentityBinding:
        raise WaveARealDataValidationError(
            "approved_provider must have the exact ApprovedProviderIdentityBinding type"
        )
    if type(human_receipt) is not TrustedHumanAuthorizationReceipt:
        raise WaveARealDataValidationError(
            "human_receipt must have the exact TrustedHumanAuthorizationReceipt type"
        )
    if type(verifier_policy) is not TrustedHumanVerifierPolicy:
        raise WaveARealDataValidationError(
            "verifier_policy must have the exact TrustedHumanVerifierPolicy type"
        )

    scope = _require_sha256_hex(
        "m10_scope_fingerprint",
        m10_decision.scope_fingerprint,
    )
    reasons: list[str] = []

    if not m10_decision.ready_for_explicit_human_pre_send_authorization:
        reasons.append("m10_controlled_execution_not_ready")

    if not final_screening.screening_complete:
        reasons.append("final_screening_incomplete")
    if final_screening.minor_data_detected:
        reasons.append("final_screening_minor_data_detected")
    if final_screening.uncertainty_detected:
        reasons.append("final_screening_uncertainty_detected")

    try:
        trusted_time = trusted_clock.read_trusted_time()
    except Exception:  # noqa: BLE001 - external trust boundary must fail closed
        reasons.append("trusted_execution_clock_unavailable")
        return _decision(
            scope_fingerprint=scope,
            final_screening_evidence_identifier=final_screening.evidence_identifier,
            reasons=reasons,
            trusted_time=None,
            observed_provider=None,
            verified_human=None,
        )

    if type(trusted_time) is not TrustedTimeEvidence:
        raise WaveARealDataValidationError(
            "trusted clock must return the exact TrustedTimeEvidence type"
        )
    now = trusted_time.epoch_seconds

    if temporal_evidence.evidence_identifier != final_screening.evidence_identifier:
        reasons.append("final_screening_evidence_identifier_mismatch")
    if temporal_evidence.scope_fingerprint != scope:
        reasons.append("final_screening_scope_mismatch")
    if temporal_evidence.policy_identifier != freshness_policy.policy_identifier:
        reasons.append("final_screening_policy_mismatch")

    latest_allowed_screening_time = now + freshness_policy.allowed_future_skew_seconds
    if temporal_evidence.screened_at_epoch_seconds > latest_allowed_screening_time:
        reasons.append("final_screening_timestamp_from_future")
    elif now - temporal_evidence.screened_at_epoch_seconds > freshness_policy.maximum_age_seconds:
        reasons.append("final_screening_evidence_stale")

    if approved_provider.scope_fingerprint != scope:
        reasons.append("approved_provider_scope_mismatch")

    observed_provider: ObservedRuntimeProviderIdentity | None = None
    try:
        observed_candidate = runtime_provider_source.capture_runtime_provider_identity()
    except Exception:  # noqa: BLE001 - runtime identity boundary must fail closed
        reasons.append("runtime_provider_identity_unavailable")
    else:
        if type(observed_candidate) is not ObservedRuntimeProviderIdentity:
            raise WaveARealDataValidationError(
                "provider source must return the exact ObservedRuntimeProviderIdentity type"
            )
        observed_provider = observed_candidate

    if observed_provider is not None:
        if observed_provider.scope_fingerprint != scope:
            reasons.append("runtime_provider_scope_mismatch")
        if observed_provider.captured_at_epoch_seconds > now:
            reasons.append("runtime_provider_identity_timestamp_from_future")
        if observed_provider.provider_identifier != approved_provider.provider_identifier:
            reasons.append("runtime_provider_identifier_mismatch")
        if observed_provider.project_identifier != approved_provider.project_identifier:
            reasons.append("runtime_project_identifier_mismatch")
        if observed_provider.model_identifier != approved_provider.model_identifier:
            reasons.append("runtime_model_identifier_mismatch")
        if not hmac.compare_digest(
            observed_provider.credential_fingerprint,
            approved_provider.credential_fingerprint,
        ):
            reasons.append("runtime_credential_identity_mismatch")

    if human_receipt.verifier_identifier not in (verifier_policy.trusted_verifier_identifiers):
        reasons.append("human_receipt_untrusted_verifier")
    if human_receipt.scope_fingerprint != scope:
        reasons.append("human_receipt_scope_mismatch")
    if human_receipt.issued_at_epoch_seconds > now:
        reasons.append("human_receipt_issued_in_future")
    if now >= human_receipt.expires_at_epoch_seconds:
        reasons.append("human_receipt_expired")

    verified_human: VerifiedHumanAuthorization | None = None
    human_receipt_structurally_acceptable = not any(
        reason.startswith("human_receipt_") for reason in reasons
    )
    if human_receipt_structurally_acceptable:
        try:
            verified_candidate = human_receipt_verifier.verify(
                human_receipt,
                trusted_time=trusted_time,
            )
        except Exception:  # noqa: BLE001 - external verifier must fail closed
            reasons.append("human_receipt_verification_failed")
        else:
            if type(verified_candidate) is not VerifiedHumanAuthorization:
                raise WaveARealDataValidationError(
                    "human verifier must return the exact VerifiedHumanAuthorization type"
                )
            verified_human = verified_candidate

    if verified_human is not None:
        if verified_human.receipt_identifier != human_receipt.receipt_identifier:
            reasons.append("verified_human_receipt_identifier_mismatch")
        if verified_human.verifier_identifier != human_receipt.verifier_identifier:
            reasons.append("verified_human_verifier_identifier_mismatch")
        if verified_human.subject_identifier != human_receipt.subject_identifier:
            reasons.append("verified_human_subject_identifier_mismatch")
        if verified_human.scope_fingerprint != scope:
            reasons.append("verified_human_scope_mismatch")
        if verified_human.verified_at_epoch_seconds > now:
            reasons.append("verified_human_timestamp_from_future")

    return _decision(
        scope_fingerprint=scope,
        final_screening_evidence_identifier=final_screening.evidence_identifier,
        reasons=reasons,
        trusted_time=trusted_time,
        observed_provider=observed_provider,
        verified_human=verified_human,
    )
