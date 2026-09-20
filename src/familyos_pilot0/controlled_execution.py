"""Fail-closed controlled-execution contract for Pilot0 M10.

This module contains no provider SDK or network call. It prepares an exact,
one-shot submission envelope only after M9 token validation and a separate
human pre-send evidence binding. Actual provider execution remains a separately
authorized operator action.

The M10 scope is HMAC-bound with a fresh, process-local key object generated
from Python's CSPRNG. The key is never stored in the request/envelope dataclasses
or governance evidence. The key object is single-scope, redacted, and can be
explicitly destroyed. Python cannot provide a proof of physical memory erasure;
future real-data execution therefore still requires stronger process isolation
and trusted external authorization infrastructure.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Lock
from typing import Final

from .errors import ControlledExecutionValidationError
from .execution_authorization import (
    ExecutionAuthorizationReadinessRequest,
    ManualSourceAuthorizationDescriptor,
    MinorDataScreeningEvidence,
    OperatorExecutionChecklist,
    ParticipantAuthorizationEvidence,
    PayloadRouteAuthorizationBinding,
    ProviderProjectReadOnlyEvidence,
    SingleUseExecutionAuthorization,
    SingleUseTokenValidationState,
    build_execution_authorization_scope_fingerprint,
    evaluate_execution_authorization_readiness,
    mark_single_use_authorization_used,
    validate_single_use_authorization,
)
from .real_data_readiness import (
    ALLOWED_PAYLOAD_FIELD_NAMES,
    REQUIRED_PAYLOAD_FIELD_NAMES,
)

_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256_HEX_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_MAX_GOVERNED_INT: Final[int] = (1 << 63) - 1


def _require_exact_string(name: str, value: object) -> str:
    if type(value) is not str:
        raise ControlledExecutionValidationError(f"{name} must be an exact string")
    if not value.strip():
        raise ControlledExecutionValidationError(f"{name} must not be blank")
    return value


def _require_identifier(name: str, value: object) -> str:
    normalized = _require_exact_string(name, value)
    if _IDENTIFIER_RE.fullmatch(normalized) is None:
        raise ControlledExecutionValidationError(f"{name} must be a bounded identifier")
    return normalized


def _require_sha256_hex(name: str, value: object) -> str:
    normalized = _require_exact_string(name, value)
    if normalized != normalized.lower() or _SHA256_HEX_RE.fullmatch(normalized) is None:
        raise ControlledExecutionValidationError(
            f"{name} must be a lowercase SHA-256 hexadecimal value"
        )
    return normalized


def _require_exact_bool(name: str, value: object) -> bool:
    if type(value) is not bool:
        raise ControlledExecutionValidationError(f"{name} must be an exact bool")
    return value


def _require_exact_nonnegative_int(name: str, value: object) -> int:
    if type(value) is not int:
        raise ControlledExecutionValidationError(f"{name} must be an exact int")
    if value < 0:
        raise ControlledExecutionValidationError(f"{name} must be non-negative")
    if value > _MAX_GOVERNED_INT:
        raise ControlledExecutionValidationError(f"{name} exceeds the governed integer range")
    return value


def _contains_unicode_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


class ControlledExecutionReadinessState(StrEnum):
    """Possible M10 pre-send execution-readiness outcomes."""

    READY_FOR_EXPLICIT_HUMAN_PRE_SEND_AUTHORIZATION = (
        "READY_FOR_EXPLICIT_HUMAN_PRE_SEND_AUTHORIZATION"
    )
    DENY = "DENY"
    ABORT = "ABORT"


class ExecutionPayload:
    """Ordinarily immutable exact minimized payload values.

    This is intentionally not a dataclass. Therefore dataclasses.asdict() on a
    containing request/envelope does not recursively serialize raw payload
    values into a plain dictionary. Direct payload access remains possible by
    explicit API because a later separately authorized provider boundary would
    need the actual payload.

    Ordinary assignment, deletion and repeated initialization are refused.
    Deliberate object-internals manipulation remains outside this synthetic
    boundary and is not a production isolation guarantee.
    """

    __slots__ = ("_initialized", "_values")

    _initialized: bool
    _values: tuple[tuple[str, str | None], ...]

    def __init__(self, values: object) -> None:
        if getattr(self, "_initialized", False):
            raise ControlledExecutionValidationError("payload reinitialization is forbidden")

        if type(values) is not tuple:
            raise ControlledExecutionValidationError("payload values must be an exact tuple")

        validated: list[tuple[str, str | None]] = []
        names: list[str] = []

        for entry in values:
            if type(entry) is not tuple or len(entry) != 2:
                raise ControlledExecutionValidationError(
                    "each payload entry must be an exact two-item tuple"
                )

            raw_name, raw_value = entry
            name = _require_identifier("payload_field_name", raw_name)

            if raw_value is not None and type(raw_value) is not str:
                raise ControlledExecutionValidationError(
                    "payload value must be an exact string or None"
                )
            if type(raw_value) is str:
                if "\x00" in raw_value:
                    raise ControlledExecutionValidationError(
                        "payload string values must not contain NUL"
                    )
                if _contains_unicode_surrogate(raw_value):
                    raise ControlledExecutionValidationError(
                        "payload string values must not contain Unicode surrogates"
                    )

            validated.append((name, raw_value))
            names.append(name)

        if len(set(names)) != len(names):
            raise ControlledExecutionValidationError(
                "payload field names must not contain duplicates"
            )

        object.__setattr__(self, "_values", tuple(validated))
        object.__setattr__(self, "_initialized", True)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise ControlledExecutionValidationError("payload is immutable")

    def __delattr__(self, name: str) -> None:
        del name
        raise ControlledExecutionValidationError("payload is immutable")

    @property
    def values(self) -> tuple[tuple[str, str | None], ...]:
        """Return the immutable exact payload tuple."""
        return self._values

    @property
    def field_names(self) -> tuple[str, ...]:
        """Return the immutable exact field-name tuple."""
        return tuple(name for name, _ in self._values)

    def as_dict(self) -> dict[str, str | None]:
        """Return an explicit copy of the raw payload mapping."""
        return dict(self._values)

    def __repr__(self) -> str:
        return "ExecutionPayload(<redacted>)"

    def __copy__(self) -> ExecutionPayload:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> ExecutionPayload:
        del memo
        return self


class EphemeralScopeBindingKey:
    """Fresh single-scope HMAC key with best-effort explicit destruction."""

    __slots__ = (
        "_bound_message_digest",
        "_destroyed",
        "_lock",
        "_material",
        "_preparation_claimed",
    )

    def __init__(self) -> None:
        material = secrets.token_bytes(32)
        if len(material) != 32:
            raise ControlledExecutionValidationError("scope-binding key generation failed closed")
        self._material = bytearray(material)
        self._destroyed = False
        self._bound_message_digest: bytes | None = None
        self._preparation_claimed = False
        self._lock = Lock()

    @classmethod
    def generate(cls) -> EphemeralScopeBindingKey:
        """Generate a new 256-bit process-local key using the system CSPRNG."""
        return cls()

    @property
    def destroyed(self) -> bool:
        with self._lock:
            return self._destroyed

    @property
    def preparation_claimed(self) -> bool:
        with self._lock:
            return self._preparation_claimed

    def claim_preparation(self) -> None:
        """Atomically grant this key to exactly one preparation attempt.

        A readiness decision may sign the exact canonical message before this
        claim. Once preparation begins, competing callers are refused and are
        not permitted to destroy the key owned by the successful claimant.
        """

        with self._lock:
            if self._destroyed:
                raise ControlledExecutionValidationError("scope-binding key has been destroyed")
            if self._preparation_claimed:
                raise ControlledExecutionValidationError(
                    "scope-binding key preparation already claimed"
                )
            self._preparation_claimed = True

    def sign(self, message: bytes) -> str:
        """HMAC exactly one canonical execution instance.

        Repeated signing of the identical canonical message is allowed because
        readiness is re-evaluated immediately before envelope preparation.
        Reuse for a different execution instance is refused.
        """

        if type(message) is not bytes:
            raise ControlledExecutionValidationError("scope-binding message must be exact bytes")

        message_digest = hashlib.sha256(message).digest()

        with self._lock:
            if self._destroyed:
                raise ControlledExecutionValidationError("scope-binding key has been destroyed")

            if self._bound_message_digest is None:
                self._bound_message_digest = message_digest
            elif not hmac.compare_digest(
                self._bound_message_digest,
                message_digest,
            ):
                raise ControlledExecutionValidationError(
                    "scope-binding key reuse across execution instances refused"
                )

            return hmac.new(
                bytes(self._material),
                message,
                hashlib.sha256,
            ).hexdigest()

    def destroy(self) -> None:
        """Best-effort zeroize the mutable in-process key buffer."""
        with self._lock:
            if self._destroyed:
                return
            for index in range(len(self._material)):
                self._material[index] = 0
            self._bound_message_digest = None
            self._destroyed = True

    def __enter__(self) -> EphemeralScopeBindingKey:
        if self.destroyed:
            raise ControlledExecutionValidationError("scope-binding key has been destroyed")
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        del exc_type, exc, traceback
        self.destroy()

    def __repr__(self) -> str:
        return f"EphemeralScopeBindingKey(<redacted>, destroyed={self.destroyed})"

    def __copy__(self) -> EphemeralScopeBindingKey:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> EphemeralScopeBindingKey:
        del memo
        return self


@dataclass(frozen=True)
class FinalMinorDataScreeningEvidence:
    """Final immediately-pre-send minor-data screening evidence."""

    evidence_identifier: str
    screening_complete: bool
    minor_data_detected: bool
    uncertainty_detected: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_identifier",
            _require_identifier(
                "evidence_identifier",
                self.evidence_identifier,
            ),
        )
        _require_exact_bool("screening_complete", self.screening_complete)
        _require_exact_bool("minor_data_detected", self.minor_data_detected)
        _require_exact_bool("uncertainty_detected", self.uncertainty_detected)


@dataclass(frozen=True)
class ProviderExecutionBoundary:
    """Exact provider-route boundary for one future execution instance."""

    provider_route_identifier: str
    read_only_preflight_complete: bool
    provider_configuration_mutation_requested: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_route_identifier",
            _require_identifier(
                "provider_route_identifier",
                self.provider_route_identifier,
            ),
        )
        _require_exact_bool(
            "read_only_preflight_complete",
            self.read_only_preflight_complete,
        )
        _require_exact_bool(
            "provider_configuration_mutation_requested",
            self.provider_configuration_mutation_requested,
        )


@dataclass(frozen=True)
class ControlledExecutionRequest:
    """Aggregate for one exact M10 execution instance."""

    m9_readiness_request: ExecutionAuthorizationReadinessRequest
    m9_single_use_authorization: SingleUseExecutionAuthorization
    final_minor_screening: FinalMinorDataScreeningEvidence
    payload: ExecutionPayload = field(repr=False)
    provider: ProviderExecutionBoundary

    def __post_init__(self) -> None:
        if type(self.m9_readiness_request) is not ExecutionAuthorizationReadinessRequest:
            raise ControlledExecutionValidationError(
                "m9_readiness_request must have the exact canonical type"
            )
        if type(self.m9_single_use_authorization) is not SingleUseExecutionAuthorization:
            raise ControlledExecutionValidationError(
                "m9_single_use_authorization must have the exact canonical type"
            )
        if type(self.final_minor_screening) is not FinalMinorDataScreeningEvidence:
            raise ControlledExecutionValidationError(
                "final_minor_screening must have the exact canonical type"
            )
        if type(self.payload) is not ExecutionPayload:
            raise ControlledExecutionValidationError(
                "payload must have the exact ExecutionPayload type"
            )
        if type(self.provider) is not ProviderExecutionBoundary:
            raise ControlledExecutionValidationError(
                "provider must have the exact ProviderExecutionBoundary type"
            )


@dataclass(frozen=True)
class ControlledExecutionAuditEvidence:
    """Raw-content-free and key-free M10 pre-send evidence."""

    ephemeral_correlation_identifier: str
    pseudonymous_participant_reference: str
    provider_route_identifier: str
    scope_fingerprint: str
    state: ControlledExecutionReadinessState
    reasons: tuple[str, ...]
    m9_token_validation_state: SingleUseTokenValidationState


@dataclass(frozen=True)
class ControlledExecutionReadinessDecision:
    """M10 pre-send decision; never performs a provider call."""

    state: ControlledExecutionReadinessState
    reasons: tuple[str, ...]
    scope_fingerprint: str
    audit_evidence: ControlledExecutionAuditEvidence

    @property
    def ready_for_explicit_human_pre_send_authorization(self) -> bool:
        return (
            self.state
            is ControlledExecutionReadinessState.READY_FOR_EXPLICIT_HUMAN_PRE_SEND_AUTHORIZATION
        )

    @property
    def execution_authorized(self) -> bool:
        return False


@dataclass(frozen=True)
class HumanPreSendExecutionAuthorization:
    """Caller-provided evidence binding, not trusted human identity proof."""

    human_decision_reference: str
    explicit_human_confirmation: bool
    approved_scope_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "human_decision_reference",
            _require_identifier(
                "human_decision_reference",
                self.human_decision_reference,
            ),
        )
        _require_exact_bool(
            "explicit_human_confirmation",
            self.explicit_human_confirmation,
        )
        object.__setattr__(
            self,
            "approved_scope_fingerprint",
            _require_sha256_hex(
                "approved_scope_fingerprint",
                self.approved_scope_fingerprint,
            ),
        )

    @property
    def trusted_human_identity_verified(self) -> bool:
        return False


@dataclass(frozen=True)
class OneShotSubmissionEnvelope:
    """Prepared one-shot provider envelope; contains no execution method."""

    scope_fingerprint: str
    authorization_identifier: str
    human_decision_reference: str
    provider_route_identifier: str
    idempotency_reference: str
    payload: ExecutionPayload = field(repr=False)
    consumed_authorization: SingleUseExecutionAuthorization

    @property
    def provider_execution_performed(self) -> bool:
        return False

    @property
    def execution_authorized(self) -> bool:
        return False


@dataclass(frozen=True)
class SyntheticSubmissionEvidence:
    """Synthetic one-shot rehearsal evidence without raw payload values."""

    authorization_identifier: str
    provider_route_identifier: str
    scope_fingerprint: str
    submission_count: int


class SyntheticOneShotSubmissionRecorder:
    """Thread-safe synthetic-only at-most-one submission recorder."""

    def __init__(self) -> None:
        self._submitted = False
        self._lock = Lock()

    def record(
        self,
        envelope: OneShotSubmissionEnvelope,
    ) -> SyntheticSubmissionEvidence:
        if type(envelope) is not OneShotSubmissionEnvelope:
            raise ControlledExecutionValidationError(
                "envelope must have the exact OneShotSubmissionEnvelope type"
            )

        try:
            authorization_identifier = _require_identifier(
                "authorization_identifier",
                envelope.authorization_identifier,
            )
            provider_route_identifier = _require_identifier(
                "provider_route_identifier",
                envelope.provider_route_identifier,
            )
            scope_fingerprint = _require_sha256_hex(
                "scope_fingerprint",
                envelope.scope_fingerprint,
            )
            _require_identifier(
                "human_decision_reference",
                envelope.human_decision_reference,
            )
            _require_identifier(
                "idempotency_reference",
                envelope.idempotency_reference,
            )
            if type(envelope.payload) is not ExecutionPayload:
                raise ControlledExecutionValidationError(
                    "envelope payload must have the exact ExecutionPayload type"
                )
            if type(envelope.consumed_authorization) is not SingleUseExecutionAuthorization:
                raise ControlledExecutionValidationError(
                    "consumed authorization must have the exact canonical type"
                )
        except ControlledExecutionValidationError:
            raise
        except (AttributeError, TypeError, ValueError, OverflowError):
            raise ControlledExecutionValidationError(
                "malformed synthetic submission envelope"
            ) from None

        with self._lock:
            if self._submitted:
                raise ControlledExecutionValidationError(
                    "synthetic one-shot submission replay refused"
                )
            self._submitted = True

        return SyntheticSubmissionEvidence(
            authorization_identifier=authorization_identifier,
            provider_route_identifier=provider_route_identifier,
            scope_fingerprint=scope_fingerprint,
            submission_count=1,
        )


class SingleUseAuthorizationLedger:
    """Thread-safe, per-instance synthetic single-use consumption record.

    This remains insufficient for real provider execution. Any future real path
    requires durable atomic compare-and-set storage across process/machine
    boundaries.
    """

    def __init__(self) -> None:
        self._consumed: set[str] = set()
        self._lock = Lock()

    def consume(self, authorization_identifier: str) -> None:
        normalized = _require_identifier(
            "authorization_identifier",
            authorization_identifier,
        )
        with self._lock:
            if normalized in self._consumed:
                raise ControlledExecutionValidationError(
                    "single-use authorization already consumed"
                )
            self._consumed.add(normalized)


M10_EXECUTION_CONTRACT_VERSION: Final[str] = "familyos-pilot0-m10-controlled-execution-v4"


def _validate_m9_runtime_types(
    request: ControlledExecutionRequest,
    *,
    now_epoch_seconds: object,
) -> int:
    if type(request) is not ControlledExecutionRequest:
        raise ControlledExecutionValidationError(
            "request must have the exact ControlledExecutionRequest type"
        )

    now = _require_exact_nonnegative_int("now_epoch_seconds", now_epoch_seconds)

    try:
        m9_request = request.m9_readiness_request
        final_screening = request.final_minor_screening
        payload = request.payload
        execution_provider = request.provider
        token = request.m9_single_use_authorization

        if type(m9_request) is not ExecutionAuthorizationReadinessRequest:
            raise ControlledExecutionValidationError(
                "m9_readiness_request must have the exact canonical type"
            )
        if type(final_screening) is not FinalMinorDataScreeningEvidence:
            raise ControlledExecutionValidationError(
                "final_minor_screening must have the exact canonical type"
            )
        if type(payload) is not ExecutionPayload:
            raise ControlledExecutionValidationError(
                "payload must have the exact ExecutionPayload type"
            )
        if type(execution_provider) is not ProviderExecutionBoundary:
            raise ControlledExecutionValidationError(
                "provider must have the exact ProviderExecutionBoundary type"
            )
        if type(token) is not SingleUseExecutionAuthorization:
            raise ControlledExecutionValidationError(
                "m9_single_use_authorization must have the exact canonical type"
            )

        source = m9_request.source
        participant = m9_request.participant
        screening = m9_request.minor_screening
        payload_route = m9_request.payload_route
        provider = m9_request.provider
        operator = m9_request.operator

        exact_nested_types = (
            ("source", source, ManualSourceAuthorizationDescriptor),
            ("participant", participant, ParticipantAuthorizationEvidence),
            ("minor_screening", screening, MinorDataScreeningEvidence),
            ("payload_route", payload_route, PayloadRouteAuthorizationBinding),
            ("provider_evidence", provider, ProviderProjectReadOnlyEvidence),
            ("operator", operator, OperatorExecutionChecklist),
        )
        for nested_name, nested_value, expected_type in exact_nested_types:
            if type(nested_value) is not expected_type:
                raise ControlledExecutionValidationError(
                    f"{nested_name} must have the exact canonical type"
                )

        _require_identifier("source_type", source.source_type)
        _require_exact_nonnegative_int(
            "selected_item_count",
            source.selected_item_count,
        )
        _require_exact_bool(
            "manual_selection_confirmed",
            source.manual_selection_confirmed,
        )
        _require_identifier(
            "ephemeral_correlation_identifier",
            source.ephemeral_correlation_identifier,
        )

        _require_identifier(
            "pseudonymous_participant_reference",
            participant.pseudonymous_participant_reference,
        )
        _require_identifier(
            "consent_evidence_identifier",
            participant.consent_evidence_identifier,
        )
        _require_identifier(
            "eligibility_evidence_identifier",
            participant.eligibility_evidence_identifier,
        )
        _require_exact_bool("adult_confirmed", participant.adult_confirmed)
        _require_exact_bool("active_consent", participant.active_consent)
        _require_exact_bool("participant_revoked", participant.revoked)

        _require_identifier(
            "m9_screening_evidence_identifier",
            screening.screening_evidence_identifier,
        )
        _require_exact_bool(
            "m9_screening_complete",
            screening.screening_complete,
        )
        _require_exact_bool(
            "m9_minor_data_detected",
            screening.minor_data_detected,
        )

        if type(payload_route.payload_field_names) is not tuple:
            raise ControlledExecutionValidationError(
                "m9 payload_field_names must be an exact tuple"
            )
        for field_name in payload_route.payload_field_names:
            _require_identifier("m9_payload_field_name", field_name)
        _require_identifier(
            "m9_provider_route_identifier",
            payload_route.provider_route_identifier,
        )

        for bool_name, bool_value in (
            (
                "dedicated_familyos_project_confirmed",
                provider.dedicated_familyos_project_confirmed,
            ),
            ("store_disabled_confirmed", provider.store_disabled_confirmed),
            (
                "hosted_tools_disabled_confirmed",
                provider.hosted_tools_disabled_confirmed,
            ),
            (
                "provider_sharing_disabled_confirmed",
                provider.provider_sharing_disabled_confirmed,
            ),
            (
                "read_only_preflight_completed",
                provider.read_only_preflight_completed,
            ),
            (
                "m9_provider_configuration_mutation_requested",
                provider.provider_configuration_mutation_requested,
            ),
            ("operator_checklist_complete", operator.checklist_complete),
            (
                "abort_conditions_acknowledged",
                operator.abort_conditions_acknowledged,
            ),
            (
                "pre_send_confirmation_required",
                operator.pre_send_confirmation_required,
            ),
            (
                "unattended_execution_requested",
                operator.unattended_execution_requested,
            ),
        ):
            _require_exact_bool(bool_name, bool_value)

        _require_identifier(
            "authorization_identifier",
            token.authorization_identifier,
        )
        _require_identifier(
            "m9_human_decision_reference",
            token.human_decision_reference,
        )
        _require_sha256_hex("m9_scope_fingerprint", token.scope_fingerprint)
        issued = _require_exact_nonnegative_int(
            "issued_at_epoch_seconds",
            token.issued_at_epoch_seconds,
        )
        expires = _require_exact_nonnegative_int(
            "expires_at_epoch_seconds",
            token.expires_at_epoch_seconds,
        )
        _require_exact_bool("m9_token_used", token.used)
        _require_exact_bool("m9_token_revoked", token.revoked)

        if expires <= issued:
            raise ControlledExecutionValidationError("token expiry must be greater than issuance")
    except ControlledExecutionValidationError:
        raise
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise ControlledExecutionValidationError("malformed canonical M9 execution input") from None

    return now


def _validate_payload(
    request: ControlledExecutionRequest,
    reasons: list[str],
) -> None:
    payload = request.payload.as_dict()
    payload_fields = frozenset(payload)
    bound_fields = frozenset(request.m9_readiness_request.payload_route.payload_field_names)

    if payload_fields != bound_fields:
        reasons.append("payload_field_set_does_not_match_m9_binding")

    if not REQUIRED_PAYLOAD_FIELD_NAMES.issubset(payload_fields):
        reasons.append("required_minimal_payload_field_missing")

    if not payload_fields.issubset(ALLOWED_PAYLOAD_FIELD_NAMES):
        reasons.append("payload_contains_noncanonical_field")

    if payload.get("source_type") != request.m9_readiness_request.source.source_type:
        reasons.append("payload_source_type_scope_mismatch")

    if (
        payload.get("pseudonymous_participant_reference")
        != request.m9_readiness_request.participant.pseudonymous_participant_reference
    ):
        reasons.append("payload_participant_scope_mismatch")

    if (
        payload.get("ephemeral_correlation_identifier")
        != request.m9_readiness_request.source.ephemeral_correlation_identifier
    ):
        reasons.append("payload_correlation_scope_mismatch")

    for required_name in REQUIRED_PAYLOAD_FIELD_NAMES:
        value = payload.get(required_name)
        if type(value) is not str or not value.strip():
            reasons.append(f"required_payload_value_invalid:{required_name}")

    timestamp = payload.get("event_relevant_timestamp")
    if timestamp is not None and (type(timestamp) is not str or not timestamp.strip()):
        reasons.append("optional_event_relevant_timestamp_invalid")


def _canonical_scope_document(
    request: ControlledExecutionRequest,
) -> bytes:
    token = request.m9_single_use_authorization

    document = {
        "contract_version": M10_EXECUTION_CONTRACT_VERSION,
        "m9_scope": build_execution_authorization_scope_fingerprint(request.m9_readiness_request),
        "m9_consent_evidence_identifier": (
            request.m9_readiness_request.participant.consent_evidence_identifier
        ),
        "m9_eligibility_evidence_identifier": (
            request.m9_readiness_request.participant.eligibility_evidence_identifier
        ),
        "m9_minor_screening_evidence_identifier": (
            request.m9_readiness_request.minor_screening.screening_evidence_identifier
        ),
        "m9_token": {
            "authorization_identifier": token.authorization_identifier,
            "human_decision_reference": token.human_decision_reference,
            "scope_fingerprint": token.scope_fingerprint,
            "issued_at_epoch_seconds": token.issued_at_epoch_seconds,
            "expires_at_epoch_seconds": token.expires_at_epoch_seconds,
            "used": token.used,
            "revoked": token.revoked,
        },
        "payload_values": sorted(
            request.payload.values,
            key=lambda item: item[0],
        ),
        "final_screening_evidence_identifier": (request.final_minor_screening.evidence_identifier),
        "final_screening_complete": (request.final_minor_screening.screening_complete),
        "final_minor_data_detected": (request.final_minor_screening.minor_data_detected),
        "final_uncertainty_detected": (request.final_minor_screening.uncertainty_detected),
        "provider_route_identifier": request.provider.provider_route_identifier,
        "provider_preflight_complete": (request.provider.read_only_preflight_complete),
        "provider_configuration_mutation_requested": (
            request.provider.provider_configuration_mutation_requested
        ),
    }

    # Payload strings containing Unicode surrogate code points are rejected
    # before canonicalization. ensure_ascii=True then provides deterministic
    # ASCII bytes over the admitted Unicode-scalar-value domain.
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def build_controlled_execution_scope_fingerprint(
    request: ControlledExecutionRequest,
    *,
    scope_binding_key: EphemeralScopeBindingKey,
    now_epoch_seconds: int,
) -> str:
    """Build a fresh-key HMAC fingerprint of one exact execution instance."""

    _validate_m9_runtime_types(
        request,
        now_epoch_seconds=now_epoch_seconds,
    )
    if type(scope_binding_key) is not EphemeralScopeBindingKey:
        raise ControlledExecutionValidationError(
            "scope_binding_key must have the exact EphemeralScopeBindingKey type"
        )
    return scope_binding_key.sign(_canonical_scope_document(request))


def evaluate_controlled_execution_readiness(
    request: ControlledExecutionRequest,
    *,
    scope_binding_key: EphemeralScopeBindingKey,
    now_epoch_seconds: int,
) -> ControlledExecutionReadinessDecision:
    """Evaluate final M10 pre-send readiness with fail-closed semantics."""

    now = _validate_m9_runtime_types(
        request,
        now_epoch_seconds=now_epoch_seconds,
    )

    for name, value in (
        (
            "final_screening_complete",
            request.final_minor_screening.screening_complete,
        ),
        (
            "final_minor_data_detected",
            request.final_minor_screening.minor_data_detected,
        ),
        (
            "final_uncertainty_detected",
            request.final_minor_screening.uncertainty_detected,
        ),
        (
            "provider_read_only_preflight_complete",
            request.provider.read_only_preflight_complete,
        ),
        (
            "provider_configuration_mutation_requested",
            request.provider.provider_configuration_mutation_requested,
        ),
    ):
        _require_exact_bool(name, value)

    scope_fingerprint = build_controlled_execution_scope_fingerprint(
        request,
        scope_binding_key=scope_binding_key,
        now_epoch_seconds=now,
    )

    m9_decision = evaluate_execution_authorization_readiness(request.m9_readiness_request)
    m9_scope_fingerprint = build_execution_authorization_scope_fingerprint(
        request.m9_readiness_request
    )

    token_validation = validate_single_use_authorization(
        request.m9_single_use_authorization,
        expected_scope_fingerprint=m9_scope_fingerprint,
        now_epoch_seconds=now,
    )

    reasons: list[str] = []

    if now < request.m9_single_use_authorization.issued_at_epoch_seconds:
        reasons.append("m9_single_use_token_not_yet_valid")

    if (
        request.final_minor_screening.minor_data_detected
        or request.final_minor_screening.uncertainty_detected
    ):
        if request.final_minor_screening.minor_data_detected:
            reasons.append("final_minor_data_detected")
        if request.final_minor_screening.uncertainty_detected:
            reasons.append("final_minor_data_uncertainty_detected")
        state = ControlledExecutionReadinessState.ABORT
    else:
        if not request.final_minor_screening.screening_complete:
            reasons.append("final_minor_data_screening_incomplete")

        if not m9_decision.ready_to_issue_single_use_authorization:
            reasons.append("m9_authorization_readiness_not_ready")

        if not token_validation.valid_for_separate_pre_send_confirmation:
            reasons.append(f"m9_single_use_token_invalid:{token_validation.state}")

        if (
            request.provider.provider_route_identifier
            != request.m9_readiness_request.payload_route.provider_route_identifier
        ):
            reasons.append("provider_route_scope_mismatch")

        if not request.provider.read_only_preflight_complete:
            reasons.append("provider_read_only_preflight_incomplete")

        if request.provider.provider_configuration_mutation_requested:
            reasons.append("provider_configuration_mutation_forbidden")

        _validate_payload(request, reasons)

        state = (
            ControlledExecutionReadinessState.DENY
            if reasons
            else ControlledExecutionReadinessState.READY_FOR_EXPLICIT_HUMAN_PRE_SEND_AUTHORIZATION
        )

    reasons_tuple = tuple(reasons)

    audit = ControlledExecutionAuditEvidence(
        ephemeral_correlation_identifier=(
            request.m9_readiness_request.source.ephemeral_correlation_identifier
        ),
        pseudonymous_participant_reference=(
            request.m9_readiness_request.participant.pseudonymous_participant_reference
        ),
        provider_route_identifier=request.provider.provider_route_identifier,
        scope_fingerprint=scope_fingerprint,
        state=state,
        reasons=reasons_tuple,
        m9_token_validation_state=token_validation.state,
    )

    return ControlledExecutionReadinessDecision(
        state=state,
        reasons=reasons_tuple,
        scope_fingerprint=scope_fingerprint,
        audit_evidence=audit,
    )


def prepare_one_shot_submission_envelope(
    request: ControlledExecutionRequest,
    decision: ControlledExecutionReadinessDecision,
    human_authorization: HumanPreSendExecutionAuthorization,
    *,
    ledger: SingleUseAuthorizationLedger,
    scope_binding_key: EphemeralScopeBindingKey,
    now_epoch_seconds: int,
) -> OneShotSubmissionEnvelope:
    """Prepare an envelope only for the exact request already approved.

    This performs no provider execution. The caller-provided human evidence is
    not trusted identity proof. The caller that wins the atomic preparation claim owns key cleanup.
    The owner destroys the process-local scope key on exit whether preparation
    succeeds or fails; a caller that loses the claim is refused before cleanup
    and leaves the owner's key intact.
    """

    if type(scope_binding_key) is not EphemeralScopeBindingKey:
        raise ControlledExecutionValidationError(
            "scope_binding_key must have the exact EphemeralScopeBindingKey type"
        )

    # Preparation uses exclusive key ownership. A competing caller that loses
    # this atomic claim must not enter the cleanup block and therefore cannot
    # destroy the winning caller's key.
    scope_binding_key.claim_preparation()

    try:
        if type(decision) is not ControlledExecutionReadinessDecision:
            raise ControlledExecutionValidationError(
                "decision must have the exact ControlledExecutionReadinessDecision type"
            )
        if type(human_authorization) is not HumanPreSendExecutionAuthorization:
            raise ControlledExecutionValidationError(
                "human_authorization must have the exact canonical type"
            )
        if type(ledger) is not SingleUseAuthorizationLedger:
            raise ControlledExecutionValidationError(
                "ledger must have the exact SingleUseAuthorizationLedger type"
            )

        _require_sha256_hex(
            "decision_scope_fingerprint",
            decision.scope_fingerprint,
        )

        fresh = evaluate_controlled_execution_readiness(
            request,
            scope_binding_key=scope_binding_key,
            now_epoch_seconds=now_epoch_seconds,
        )

        if not fresh.ready_for_explicit_human_pre_send_authorization:
            raise ControlledExecutionValidationError(
                "controlled execution readiness is not ready for this request"
            )

        if not decision.ready_for_explicit_human_pre_send_authorization:
            raise ControlledExecutionValidationError(
                "controlled execution readiness decision is not ready"
            )

        if not hmac.compare_digest(
            decision.scope_fingerprint,
            fresh.scope_fingerprint,
        ):
            raise ControlledExecutionValidationError(
                "controlled execution decision does not match this request"
            )

        if not human_authorization.explicit_human_confirmation:
            raise ControlledExecutionValidationError(
                "explicit human pre-send execution authorization is required"
            )

        if not hmac.compare_digest(
            human_authorization.approved_scope_fingerprint,
            fresh.scope_fingerprint,
        ):
            raise ControlledExecutionValidationError("human pre-send authorization scope mismatch")

        consumed = mark_single_use_authorization_used(
            request.m9_single_use_authorization,
            now_epoch_seconds=now_epoch_seconds,
        )
        ledger.consume(consumed.authorization_identifier)

        return OneShotSubmissionEnvelope(
            scope_fingerprint=fresh.scope_fingerprint,
            authorization_identifier=consumed.authorization_identifier,
            human_decision_reference=human_authorization.human_decision_reference,
            provider_route_identifier=request.provider.provider_route_identifier,
            idempotency_reference=consumed.authorization_identifier,
            payload=request.payload,
            consumed_authorization=consumed,
        )
    finally:
        scope_binding_key.destroy()
