"""Offline trust-source bindings for FamilyOS Pilot 0 M10 Wave A.

Approved profile:

- RD-04: signed external time attestation verified locally;
- RD-05: final-screening freshness policy fixed to 60 seconds / 0 future skew;
- RD-06: immutable verified local runtime provider configuration;
- RD-01: offline signed human authorization receipt verified locally.

This module performs no network or provider call, introduces no third-party
dependency, stores no private signing key, and never authorizes real-data
execution.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .controlled_execution import FinalMinorDataScreeningEvidence
from .real_data_wave_a import (
    FinalScreeningFreshnessPolicy,
    FinalScreeningTemporalEvidence,
    ObservedRuntimeProviderIdentity,
    TrustedHumanAuthorizationReceipt,
    TrustedTimeEvidence,
    VerifiedHumanAuthorization,
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_GOVERNED_INT = (1 << 63) - 1
_MAX_SIGNATURE_TEXT_BYTES = 32_768
_MAX_ALLOWED_SIGNERS_BYTES = 16_384
_MAX_CANONICAL_PAYLOAD_BYTES = 16_384

DEFAULT_SSH_KEYGEN_PATH = "/usr/bin/ssh-keygen"

TIME_ATTESTATION_NAMESPACE = "familyos-m10-wave-a-time-attestation-v1"
HUMAN_RECEIPT_NAMESPACE = "familyos-m10-wave-a-human-authorization-v1"

M10_FINAL_SCREENING_POLICY_IDENTIFIER = "familyos-m10-final-screening-freshness-v1"
M10_FINAL_SCREENING_MAXIMUM_AGE_SECONDS = 60
M10_FINAL_SCREENING_ALLOWED_FUTURE_SKEW_SECONDS = 0


class TrustSourceBindingError(RuntimeError):
    """Base error for an unavailable or invalid approved trust-source binding."""


class TrustSourceBindingValidationError(ValueError):
    """Raised when a trust-source binding receives malformed governed input."""


class OfflineSignatureVerificationError(TrustSourceBindingError):
    """Raised when local offline SSH signature verification does not succeed."""


def _require_exact_string(name: str, value: object) -> str:
    if type(value) is not str:
        raise TrustSourceBindingValidationError(f"{name} must be an exact string")
    if not value.strip():
        raise TrustSourceBindingValidationError(f"{name} must not be blank")
    return value


def _require_identifier(name: str, value: object) -> str:
    normalized = _require_exact_string(name, value)
    if _IDENTIFIER_RE.fullmatch(normalized) is None:
        raise TrustSourceBindingValidationError(f"{name} must be a bounded identifier")
    return normalized


def _require_sha256_hex(name: str, value: object) -> str:
    normalized = _require_exact_string(name, value)
    if normalized != normalized.lower() or _SHA256_HEX_RE.fullmatch(normalized) is None:
        raise TrustSourceBindingValidationError(
            f"{name} must be a lowercase SHA-256 hexadecimal value"
        )
    return normalized


def _require_exact_nonnegative_int(name: str, value: object) -> int:
    if type(value) is not int:
        raise TrustSourceBindingValidationError(f"{name} must be an exact int")
    if value < 0:
        raise TrustSourceBindingValidationError(f"{name} must be non-negative")
    if value > _MAX_GOVERNED_INT:
        raise TrustSourceBindingValidationError(f"{name} exceeds the governed integer range")
    return value


def _require_bounded_text(name: str, value: object, *, maximum_bytes: int) -> str:
    normalized = _require_exact_string(name, value)
    if "\x00" in normalized:
        raise TrustSourceBindingValidationError(f"{name} must not contain NUL")
    if len(normalized.encode("utf-8")) > maximum_bytes:
        raise TrustSourceBindingValidationError(f"{name} exceeds its size limit")
    return normalized


def _require_scope(value: object) -> str:
    return _require_sha256_hex("scope_fingerprint", value)


def _canonical_payload(lines: tuple[tuple[str, str], ...]) -> bytes:
    payload = "".join(f"{key}={value}\n" for key, value in lines).encode("utf-8")
    if len(payload) > _MAX_CANONICAL_PAYLOAD_BYTES:
        raise TrustSourceBindingValidationError("canonical payload exceeds size limit")
    return payload


def _validated_ssh_keygen_path(value: object) -> str:
    raw = _require_exact_string("ssh_keygen_path", value)
    path = Path(raw)
    if not path.is_absolute():
        raise TrustSourceBindingValidationError("ssh_keygen_path must be an absolute path")
    if path.name != "ssh-keygen":
        raise TrustSourceBindingValidationError(
            "ssh_keygen_path must name the ssh-keygen executable"
        )
    try:
        if path.is_symlink() or not path.is_file():
            raise TrustSourceBindingValidationError(
                "ssh_keygen_path must be a regular non-symlink file"
            )
    except OSError as exc:
        raise TrustSourceBindingValidationError("ssh_keygen_path could not be inspected") from exc
    return str(path)


@dataclass(frozen=True)
class OfflineSshSignatureMaterial:
    """Public verification material for one offline SSH signature."""

    principal_identifier: str
    signature_text: str = field(repr=False)
    allowed_signers_text: str = field(repr=False)
    ssh_keygen_path: str = DEFAULT_SSH_KEYGEN_PATH

    def __post_init__(self) -> None:
        principal = _require_identifier(
            "principal_identifier",
            self.principal_identifier,
        )
        signature = _require_bounded_text(
            "signature_text",
            self.signature_text,
            maximum_bytes=_MAX_SIGNATURE_TEXT_BYTES,
        )
        allowed = _require_bounded_text(
            "allowed_signers_text",
            self.allowed_signers_text,
            maximum_bytes=_MAX_ALLOWED_SIGNERS_BYTES,
        )
        path = _validated_ssh_keygen_path(self.ssh_keygen_path)

        if not signature.startswith("-----BEGIN SSH SIGNATURE-----\n"):
            raise TrustSourceBindingValidationError(
                "signature_text must be an armored SSH signature"
            )
        if not signature.rstrip().endswith("-----END SSH SIGNATURE-----"):
            raise TrustSourceBindingValidationError(
                "signature_text must end with an SSH signature footer"
            )

        lines = [line for line in allowed.splitlines() if line.strip()]
        if len(lines) != 1:
            raise TrustSourceBindingValidationError(
                "allowed_signers_text must contain exactly one signer line"
            )
        fields = lines[0].split()
        if len(fields) < 2 or fields[0] != principal:
            raise TrustSourceBindingValidationError(
                "allowed signer principal must match principal_identifier"
            )
        if not fields[1].startswith("ssh-"):
            raise TrustSourceBindingValidationError(
                "allowed signer must use an SSH public-key format"
            )

        object.__setattr__(self, "principal_identifier", principal)
        object.__setattr__(self, "signature_text", signature)
        object.__setattr__(self, "allowed_signers_text", allowed)
        object.__setattr__(self, "ssh_keygen_path", path)


def _verify_offline_ssh_signature(
    *,
    payload: bytes,
    namespace: str,
    material: OfflineSshSignatureMaterial,
) -> None:
    _require_identifier("signature_namespace", namespace)
    if type(material) is not OfflineSshSignatureMaterial:
        raise TrustSourceBindingValidationError(
            "material must have the exact OfflineSshSignatureMaterial type"
        )
    if len(payload) > _MAX_CANONICAL_PAYLOAD_BYTES:
        raise TrustSourceBindingValidationError("payload exceeds size limit")

    try:
        with tempfile.TemporaryDirectory(prefix="familyos-m10-verify-") as tmp:
            root = Path(tmp)
            allowed_path = root / "allowed_signers"
            signature_path = root / "signature"

            allowed_path.write_text(material.allowed_signers_text, encoding="utf-8")
            signature_path.write_text(material.signature_text, encoding="utf-8")
            allowed_path.chmod(0o600)
            signature_path.chmod(0o600)

            completed = subprocess.run(
                [
                    material.ssh_keygen_path,
                    "-Y",
                    "verify",
                    "-f",
                    str(allowed_path),
                    "-I",
                    material.principal_identifier,
                    "-n",
                    namespace,
                    "-s",
                    str(signature_path),
                ],
                input=payload,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OfflineSignatureVerificationError(
            "offline signature verification unavailable"
        ) from exc

    if completed.returncode != 0:
        raise OfflineSignatureVerificationError("offline signature verification failed")


@dataclass(frozen=True)
class SignedTimeAttestation:
    """Scope-bound time statement issued by a separately governed authority."""

    attestation_identifier: str
    authority_identifier: str
    scope_fingerprint: str
    epoch_seconds: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "attestation_identifier",
            _require_identifier(
                "attestation_identifier",
                self.attestation_identifier,
            ),
        )
        object.__setattr__(
            self,
            "authority_identifier",
            _require_identifier(
                "authority_identifier",
                self.authority_identifier,
            ),
        )
        object.__setattr__(
            self,
            "scope_fingerprint",
            _require_scope(self.scope_fingerprint),
        )
        _require_exact_nonnegative_int("epoch_seconds", self.epoch_seconds)


def canonical_time_attestation_payload(attestation: SignedTimeAttestation) -> bytes:
    """Return the exact bytes that the approved time authority must sign."""

    if type(attestation) is not SignedTimeAttestation:
        raise TrustSourceBindingValidationError(
            "attestation must have the exact SignedTimeAttestation type"
        )
    return _canonical_payload(
        (
            ("version", "1"),
            ("purpose", TIME_ATTESTATION_NAMESPACE),
            ("attestation_identifier", attestation.attestation_identifier),
            ("authority_identifier", attestation.authority_identifier),
            ("scope_fingerprint", attestation.scope_fingerprint),
            ("epoch_seconds", str(attestation.epoch_seconds)),
        )
    )


@dataclass(frozen=True)
class SignedExternalTimeAttestationClock:
    """RD-04 trusted clock backed by a locally verified signed attestation."""

    attestation: SignedTimeAttestation
    signature_material: OfflineSshSignatureMaterial
    expected_scope_fingerprint: str

    def __post_init__(self) -> None:
        if type(self.attestation) is not SignedTimeAttestation:
            raise TrustSourceBindingValidationError(
                "attestation must have the exact SignedTimeAttestation type"
            )
        if type(self.signature_material) is not OfflineSshSignatureMaterial:
            raise TrustSourceBindingValidationError(
                "signature_material must have the exact OfflineSshSignatureMaterial type"
            )
        scope = _require_scope(self.expected_scope_fingerprint)
        if self.attestation.scope_fingerprint != scope:
            raise TrustSourceBindingValidationError(
                "time attestation scope does not match the expected scope"
            )
        if self.signature_material.principal_identifier != self.attestation.authority_identifier:
            raise TrustSourceBindingValidationError(
                "time authority and signature principal must match"
            )
        object.__setattr__(self, "expected_scope_fingerprint", scope)

    def read_trusted_time(self) -> TrustedTimeEvidence:
        """Verify the attestation every time it is consumed."""

        _verify_offline_ssh_signature(
            payload=canonical_time_attestation_payload(self.attestation),
            namespace=TIME_ATTESTATION_NAMESPACE,
            material=self.signature_material,
        )
        return TrustedTimeEvidence(
            epoch_seconds=self.attestation.epoch_seconds,
            source_identifier=self.attestation.authority_identifier,
            source_attestation_identifier=self.attestation.attestation_identifier,
        )


def approved_m10_final_screening_freshness_policy() -> FinalScreeningFreshnessPolicy:
    """Return the exact human-approved RD-05 policy."""

    return FinalScreeningFreshnessPolicy(
        policy_identifier=M10_FINAL_SCREENING_POLICY_IDENTIFIER,
        maximum_age_seconds=M10_FINAL_SCREENING_MAXIMUM_AGE_SECONDS,
        allowed_future_skew_seconds=M10_FINAL_SCREENING_ALLOWED_FUTURE_SKEW_SECONDS,
    )


def bind_final_screening_temporal_evidence(
    final_screening: FinalMinorDataScreeningEvidence,
    *,
    scope_fingerprint: str,
    trusted_time: TrustedTimeEvidence,
    policy: FinalScreeningFreshnessPolicy,
) -> FinalScreeningTemporalEvidence:
    """Bind final-screening evidence to the approved policy and trusted time."""

    if type(final_screening) is not FinalMinorDataScreeningEvidence:
        raise TrustSourceBindingValidationError(
            "final_screening must have the exact FinalMinorDataScreeningEvidence type"
        )
    if type(trusted_time) is not TrustedTimeEvidence:
        raise TrustSourceBindingValidationError(
            "trusted_time must have the exact TrustedTimeEvidence type"
        )
    if type(policy) is not FinalScreeningFreshnessPolicy:
        raise TrustSourceBindingValidationError(
            "policy must have the exact FinalScreeningFreshnessPolicy type"
        )

    approved = approved_m10_final_screening_freshness_policy()
    if policy != approved:
        raise TrustSourceBindingValidationError(
            "policy must exactly match the approved M10 freshness policy"
        )

    return FinalScreeningTemporalEvidence(
        evidence_identifier=final_screening.evidence_identifier,
        scope_fingerprint=_require_scope(scope_fingerprint),
        screened_at_epoch_seconds=trusted_time.epoch_seconds,
        policy_identifier=approved.policy_identifier,
    )


@dataclass(frozen=True)
class LocalRuntimeProviderConfiguration:
    """Immutable non-secret RD-06 runtime configuration snapshot."""

    source_identifier: str
    provider_identifier: str
    project_identifier: str
    model_identifier: str
    credential_fingerprint: str
    scope_fingerprint: str
    configuration_digest: str

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
            _require_scope(self.scope_fingerprint),
        )
        object.__setattr__(
            self,
            "configuration_digest",
            _require_sha256_hex(
                "configuration_digest",
                self.configuration_digest,
            ),
        )

        expected = hashlib.sha256(
            canonical_local_runtime_provider_configuration_payload(
                source_identifier=self.source_identifier,
                provider_identifier=self.provider_identifier,
                project_identifier=self.project_identifier,
                model_identifier=self.model_identifier,
                credential_fingerprint=self.credential_fingerprint,
                scope_fingerprint=self.scope_fingerprint,
            )
        ).hexdigest()
        if not hmac.compare_digest(self.configuration_digest, expected):
            raise TrustSourceBindingValidationError(
                "configuration_digest does not match the immutable configuration"
            )

        audit_source = f"{self.source_identifier}:{self.configuration_digest}"
        if _IDENTIFIER_RE.fullmatch(audit_source) is None:
            raise TrustSourceBindingValidationError(
                "source_identifier plus configuration digest exceeds identifier limits"
            )

    @classmethod
    def create(
        cls,
        *,
        source_identifier: str,
        provider_identifier: str,
        project_identifier: str,
        model_identifier: str,
        credential_fingerprint: str,
        scope_fingerprint: str,
    ) -> LocalRuntimeProviderConfiguration:
        """Construct a snapshot with a digest over all governed fields."""

        payload = canonical_local_runtime_provider_configuration_payload(
            source_identifier=source_identifier,
            provider_identifier=provider_identifier,
            project_identifier=project_identifier,
            model_identifier=model_identifier,
            credential_fingerprint=credential_fingerprint,
            scope_fingerprint=scope_fingerprint,
        )
        return cls(
            source_identifier=source_identifier,
            provider_identifier=provider_identifier,
            project_identifier=project_identifier,
            model_identifier=model_identifier,
            credential_fingerprint=credential_fingerprint,
            scope_fingerprint=scope_fingerprint,
            configuration_digest=hashlib.sha256(payload).hexdigest(),
        )


def canonical_local_runtime_provider_configuration_payload(
    *,
    source_identifier: str,
    provider_identifier: str,
    project_identifier: str,
    model_identifier: str,
    credential_fingerprint: str,
    scope_fingerprint: str,
) -> bytes:
    """Return canonical non-secret bytes for the local runtime config digest."""

    return _canonical_payload(
        (
            ("version", "1"),
            ("purpose", "familyos-m10-wave-a-runtime-provider-config-v1"),
            (
                "source_identifier",
                _require_identifier(
                    "source_identifier",
                    source_identifier,
                ),
            ),
            (
                "provider_identifier",
                _require_identifier(
                    "provider_identifier",
                    provider_identifier,
                ),
            ),
            (
                "project_identifier",
                _require_identifier(
                    "project_identifier",
                    project_identifier,
                ),
            ),
            (
                "model_identifier",
                _require_identifier(
                    "model_identifier",
                    model_identifier,
                ),
            ),
            (
                "credential_fingerprint",
                _require_sha256_hex(
                    "credential_fingerprint",
                    credential_fingerprint,
                ),
            ),
            ("scope_fingerprint", _require_scope(scope_fingerprint)),
        )
    )


@dataclass(frozen=True)
class VerifiedLocalRuntimeProviderIdentitySource:
    """RD-06 source that exposes one immutable locally verified configuration."""

    configuration: LocalRuntimeProviderConfiguration
    trusted_clock: SignedExternalTimeAttestationClock

    def __post_init__(self) -> None:
        if type(self.configuration) is not LocalRuntimeProviderConfiguration:
            raise TrustSourceBindingValidationError(
                "configuration must have the exact LocalRuntimeProviderConfiguration type"
            )
        if type(self.trusted_clock) is not SignedExternalTimeAttestationClock:
            raise TrustSourceBindingValidationError(
                "trusted_clock must have the exact SignedExternalTimeAttestationClock type"
            )
        if self.configuration.scope_fingerprint != self.trusted_clock.expected_scope_fingerprint:
            raise TrustSourceBindingValidationError(
                "runtime configuration and trusted clock scopes must match"
            )

    def capture_runtime_provider_identity(self) -> ObservedRuntimeProviderIdentity:
        """Capture the immutable local identity without contacting the provider."""

        trusted_time = self.trusted_clock.read_trusted_time()
        return ObservedRuntimeProviderIdentity(
            source_identifier=(
                f"{self.configuration.source_identifier}:{self.configuration.configuration_digest}"
            ),
            provider_identifier=self.configuration.provider_identifier,
            project_identifier=self.configuration.project_identifier,
            model_identifier=self.configuration.model_identifier,
            credential_fingerprint=self.configuration.credential_fingerprint,
            scope_fingerprint=self.configuration.scope_fingerprint,
            captured_at_epoch_seconds=trusted_time.epoch_seconds,
        )


def canonical_human_authorization_receipt_payload(
    receipt: TrustedHumanAuthorizationReceipt,
) -> bytes:
    if type(receipt) is not TrustedHumanAuthorizationReceipt:
        raise TrustSourceBindingValidationError(
            "receipt must have the exact TrustedHumanAuthorizationReceipt type"
        )
    payload = receipt.canonical_payload_bytes()
    if len(payload) > _MAX_CANONICAL_PAYLOAD_BYTES:
        raise TrustSourceBindingValidationError("canonical payload exceeds size limit")
    return payload


@dataclass(frozen=True)
class OfflineSignedHumanReceiptVerifier:
    """RD-01 verifier for one exact offline signed authorization receipt."""

    receipt_identifier: str
    signature_material: OfflineSshSignatureMaterial

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "receipt_identifier",
            _require_identifier("receipt_identifier", self.receipt_identifier),
        )
        if type(self.signature_material) is not OfflineSshSignatureMaterial:
            raise TrustSourceBindingValidationError(
                "signature_material must have the exact OfflineSshSignatureMaterial type"
            )

    def verify(
        self,
        receipt: TrustedHumanAuthorizationReceipt,
        *,
        trusted_time: TrustedTimeEvidence,
    ) -> VerifiedHumanAuthorization:
        """Verify authenticity and temporal validity without any network call."""

        if type(receipt) is not TrustedHumanAuthorizationReceipt:
            raise TrustSourceBindingValidationError(
                "receipt must have the exact TrustedHumanAuthorizationReceipt type"
            )
        if type(trusted_time) is not TrustedTimeEvidence:
            raise TrustSourceBindingValidationError(
                "trusted_time must have the exact TrustedTimeEvidence type"
            )
        if receipt.receipt_identifier != self.receipt_identifier:
            raise OfflineSignatureVerificationError(
                "receipt identifier does not match verification material"
            )
        if receipt.verifier_identifier != self.signature_material.principal_identifier:
            raise OfflineSignatureVerificationError(
                "receipt verifier does not match the approved signature principal"
            )
        if receipt.issued_at_epoch_seconds > trusted_time.epoch_seconds:
            raise OfflineSignatureVerificationError(
                "receipt was issued after the trusted verification time"
            )
        if trusted_time.epoch_seconds >= receipt.expires_at_epoch_seconds:
            raise OfflineSignatureVerificationError(
                "receipt is expired at the trusted verification time"
            )

        _rd01_canonical_payload = receipt.canonical_payload_bytes()
        if len(_rd01_canonical_payload) > _MAX_CANONICAL_PAYLOAD_BYTES:
            raise TrustSourceBindingValidationError("canonical payload exceeds size limit")
        _verify_offline_ssh_signature(
            payload=_rd01_canonical_payload,
            namespace=HUMAN_RECEIPT_NAMESPACE,
            material=self.signature_material,
        )
        return VerifiedHumanAuthorization(
            receipt_identifier=receipt.receipt_identifier,
            verifier_identifier=receipt.verifier_identifier,
            subject_identifier=receipt.subject_identifier,
            scope_fingerprint=receipt.scope_fingerprint,
            verified_at_epoch_seconds=trusted_time.epoch_seconds,
        )
