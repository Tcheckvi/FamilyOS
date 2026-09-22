"""Phase-1 custody worker contracts for FamilyOS Pilot 0 (F05).

Pure, side-effect-free data contracts for the human-present, agent-less custody
worker of the phased hybrid custody architecture (Phase 1: no persistent
broker). This module performs no I/O, reads no clock, draws no randomness and
never touches a key, a passphrase, an agent, a socket, the network or the
filesystem.

Nothing here authorizes key use. The decisions built on these contracts live in
``custody_worker_validation`` and their ``key_use_authorized`` property is
always ``False``.

The Phase-1 authorization issuer is a new superseding governed human issuance
record whose digest and verifier identity are pinned in a ``TrustAnchorRecord``.
The RD-01 receipt payload schema reuses the canonical receipt semantics of
``real_data_wave_a.TrustedHumanAuthorizationReceipt``; this module only declares
which of its fields are statically bound and which are derived.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_OPENSSH_FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
_CHALLENGE_RE = re.compile(r"^[0-9a-f]{32,128}$")
_MAX_GOVERNED_INT = (1 << 63) - 1

MAX_ENVELOPE_JSON_BYTES: Final[int] = 65_536

ENVELOPE_SCHEMA_VERSION: Final[str] = "familyos-f05-authorization-envelope-v1"
ENVELOPE_CANONICALIZATION_ID: Final[str] = "familyos-canonical-json-v1"

RD01_RECEIPT_CANONICALIZATION_ID: Final[str] = "familyos-m10-wave-a-receipt-lines-v1"
RD01_RECEIPT_SCHEMA_VERSION: Final[str] = "familyos-m10-wave-a-rd01-receipt-v1"
RD01_SIGNATURE_NAMESPACE: Final[str] = "familyos-m10-wave-a-human-authorization-v1"
RD01_RECEIPT_VERSION_VALUE: Final[str] = "1"


class CustodyContractValidationError(ValueError):
    """Raised when a custody worker contract receives malformed governed input."""


class KeyPurposeClass(StrEnum):
    """Meaning of a signature. A key never crosses purpose classes."""

    HUMAN_DECISION = "HUMAN_DECISION"
    SERVICE_ATTESTATION = "SERVICE_ATTESTATION"


class ActorKind(StrEnum):
    """Identity-Architecture actor kinds (persons, systems, external services)."""

    PERSON = "PERSON"
    SYSTEM = "SYSTEM"
    EXTERNAL_SERVICE = "EXTERNAL_SERVICE"


class HumanPresenceRequirement(StrEnum):
    """How human presence must be established at the custody boundary."""

    NONE = "NONE"
    AUTHENTICATED_SESSION = "AUTHENTICATED_SESSION"
    HUMAN_PRESENT_LOCAL = "HUMAN_PRESENT_LOCAL"
    HUMAN_PRESENT_HARDWARE = "HUMAN_PRESENT_HARDWARE"
    DUAL_HUMAN = "DUAL_HUMAN"


class ReplayPolicy(StrEnum):
    """Replay policy bound by an authorization."""

    SINGLE_USE = "SINGLE_USE"
    BOUNDED = "BOUNDED"
    WINDOWED = "WINDOWED"


class RevocationStatus(StrEnum):
    """Revocation status of a trust anchor record."""

    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class PayloadFieldKind(StrEnum):
    """Every canonical payload field is exactly one of these."""

    STATIC_BOUND = "STATIC_BOUND"
    DYNAMIC_DERIVED = "DYNAMIC_DERIVED"


class PayloadDerivationRule(StrEnum):
    """Deterministic derivation rules for dynamic payload fields."""

    ISSUED_AT_FROM_GOVERNED_TIME = "ISSUED_AT_FROM_GOVERNED_TIME"
    EXPIRES_AT_FROM_ISSUED_AT_PLUS_TTL = "EXPIRES_AT_FROM_ISSUED_AT_PLUS_TTL"
    RECEIPT_IDENTIFIER_FROM_AUTHORIZATION_AND_OPERATION = (
        "RECEIPT_IDENTIFIER_FROM_AUTHORIZATION_AND_OPERATION"
    )


class ApprovalFactor(StrEnum):
    """Factors that together establish the approver at the custody boundary."""

    CUSTODY_SESSION_LOGIN = "CUSTODY_SESSION_LOGIN"
    KEY_UNLOCK = "KEY_UNLOCK"
    HARDWARE_PRESENCE = "HARDWARE_PRESENCE"
    LOCAL_CONFIRMATION = "LOCAL_CONFIRMATION"
    WORKER_CHALLENGE = "WORKER_CHALLENGE"


class ReplayClaimState(StrEnum):
    """States of the authoritative single-use claim."""

    RESOURCES_RESERVED = "RESOURCES_RESERVED"
    KEY_USE_CLAIMED = "KEY_USE_CLAIMED"
    NO_KEY_USE = "NO_KEY_USE"
    SPENT_CLEAN = "SPENT_CLEAN"
    SPENT_UNKNOWN = "SPENT_UNKNOWN"
    QUARANTINED = "QUARANTINED"


_TERMINAL_CLAIM_STATES: Final[frozenset[ReplayClaimState]] = frozenset(
    {
        ReplayClaimState.NO_KEY_USE,
        ReplayClaimState.SPENT_CLEAN,
        ReplayClaimState.SPENT_UNKNOWN,
        ReplayClaimState.QUARANTINED,
    }
)

_CLAIM_STATE_STRICTNESS: Final[Mapping[ReplayClaimState, int]] = MappingProxyType(
    {
        ReplayClaimState.RESOURCES_RESERVED: 0,
        ReplayClaimState.NO_KEY_USE: 1,
        ReplayClaimState.KEY_USE_CLAIMED: 2,
        ReplayClaimState.SPENT_CLEAN: 3,
        ReplayClaimState.SPENT_UNKNOWN: 4,
        ReplayClaimState.QUARANTINED: 5,
    }
)


def _require_exact_string(name: str, value: object) -> str:
    if type(value) is not str:
        raise CustodyContractValidationError(f"{name} must be an exact string")
    if not value.strip():
        raise CustodyContractValidationError(f"{name} must not be blank")
    return value


def _require_identifier(name: str, value: object) -> str:
    normalized = _require_exact_string(name, value)
    if _IDENTIFIER_RE.fullmatch(normalized) is None:
        raise CustodyContractValidationError(f"{name} must be a bounded identifier")
    return normalized


def _require_token(name: str, value: object) -> str:
    normalized = _require_exact_string(name, value)
    if _TOKEN_RE.fullmatch(normalized) is None:
        raise CustodyContractValidationError(f"{name} must be a bounded token without path syntax")
    return normalized


def _require_sha256_hex(name: str, value: object) -> str:
    normalized = _require_exact_string(name, value)
    if normalized != normalized.lower() or _SHA256_HEX_RE.fullmatch(normalized) is None:
        raise CustodyContractValidationError(
            f"{name} must be a lowercase SHA-256 hexadecimal value"
        )
    return normalized


def _require_openssh_fingerprint(name: str, value: object) -> str:
    normalized = _require_exact_string(name, value)
    if _OPENSSH_FINGERPRINT_RE.fullmatch(normalized) is None:
        raise CustodyContractValidationError(f"{name} must be an OpenSSH SHA256 fingerprint")
    return normalized


def _require_challenge(name: str, value: object) -> str:
    normalized = _require_exact_string(name, value)
    if _CHALLENGE_RE.fullmatch(normalized) is None:
        raise CustodyContractValidationError(
            f"{name} must be 32 to 128 lowercase hexadecimal characters"
        )
    return normalized


def _require_field_name(name: str, value: object) -> str:
    normalized = _require_exact_string(name, value)
    if _FIELD_NAME_RE.fullmatch(normalized) is None:
        raise CustodyContractValidationError(f"{name} must be a lowercase snake-case field name")
    return normalized


def _require_payload_text(name: str, value: object) -> str:
    normalized = _require_exact_string(name, value)
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in normalized):
        raise CustodyContractValidationError(f"{name} must not contain control characters")
    return normalized


def _require_exact_nonnegative_int(name: str, value: object) -> int:
    if type(value) is not int:
        raise CustodyContractValidationError(f"{name} must be an exact int")
    if value < 0:
        raise CustodyContractValidationError(f"{name} must be non-negative")
    if value > _MAX_GOVERNED_INT:
        raise CustodyContractValidationError(f"{name} exceeds the governed integer range")
    return value


def _require_positive_int(name: str, value: object) -> int:
    normalized = _require_exact_nonnegative_int(name, value)
    if normalized == 0:
        raise CustodyContractValidationError(f"{name} must be greater than zero")
    return normalized


def _require_exact_bool(name: str, value: object) -> bool:
    if type(value) is not bool:
        raise CustodyContractValidationError(f"{name} must be an exact bool")
    return value


def _require_enum[E: StrEnum](name: str, value: object, enum_type: type[E]) -> E:
    if not isinstance(value, enum_type):
        raise CustodyContractValidationError(f"{name} must be a {enum_type.__name__} member")
    return value


def _parse_enum[E: StrEnum](name: str, value: object, enum_type: type[E]) -> E:
    if type(value) is not str:
        raise CustodyContractValidationError(f"{name} must be an exact string")
    try:
        return enum_type(value)
    except ValueError:
        raise CustodyContractValidationError(f"{name} has an unknown value") from None


def _require_identifier_tuple(
    name: str,
    value: object,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise CustodyContractValidationError(f"{name} must be an exact tuple")
    normalized = tuple(_require_identifier(name, item) for item in value)
    if not normalized and not allow_empty:
        raise CustodyContractValidationError(f"{name} must not be empty")
    if len(set(normalized)) != len(normalized):
        raise CustodyContractValidationError(f"{name} must not contain duplicates")
    return normalized


def _require_optional_identifier(name: str, value: object) -> str | None:
    if value is None:
        return None
    return _require_identifier(name, value)


def canonical_json_bytes(document: Mapping[str, object]) -> bytes:
    """Return deterministic ASCII canonical JSON bytes for a JSON-compatible document."""

    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise CustodyContractValidationError(f"duplicate JSON key: {key}")
        document[key] = value
    return document


def _reject_json_constant(token: str) -> object:
    raise CustodyContractValidationError(f"non-finite JSON constant is not allowed: {token}")


def _reject_json_float(token: str) -> object:
    raise CustodyContractValidationError(f"JSON floats are not allowed: {token}")


def loads_strict_json(text: object) -> Mapping[str, object]:
    """Parse a bounded JSON object, rejecting duplicate keys, floats and non-finite numbers."""

    encoded_text = _require_exact_string("json_text", text)
    if len(encoded_text.encode("utf-8")) > MAX_ENVELOPE_JSON_BYTES:
        raise CustodyContractValidationError("json_text exceeds its size limit")
    try:
        document = json.loads(
            encoded_text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
            parse_float=_reject_json_float,
        )
    except json.JSONDecodeError as error:
        raise CustodyContractValidationError(f"json_text is not valid JSON: {error.msg}") from None
    if type(document) is not dict:
        raise CustodyContractValidationError("json_text must be a JSON object")
    return document


def _exact_mapping(name: str, data: object, expected: frozenset[str]) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise CustodyContractValidationError(f"{name} must be a mapping")
    keys = set(data)
    if any(type(key) is not str for key in keys):
        raise CustodyContractValidationError(f"{name} must only have string keys")
    missing = sorted(expected - keys)
    unknown = sorted(keys - expected)
    if missing:
        raise CustodyContractValidationError(f"{name} is missing fields: {missing}")
    if unknown:
        raise CustodyContractValidationError(f"{name} has unknown fields: {unknown}")
    return data


def _sequence_to_tuple(name: str, value: object) -> tuple[object, ...]:
    if type(value) is list or type(value) is tuple:
        return tuple(value)
    raise CustodyContractValidationError(f"{name} must be an array")


@dataclass(frozen=True)
class PayloadCanonicalizationSpec:
    """Worker-side definition of one supported canonical payload schema.

    The ``canonicalization_id`` names and thereby binds the schema version, the
    field set, the field order, the separator and terminator rules, the
    encoding, the normalization rule and the unknown-field policy declared here.
    """

    canonicalization_id: str
    schema_version: str
    field_rules: tuple[tuple[str, PayloadFieldKind, PayloadDerivationRule | None], ...]
    separator: str
    line_terminator: str
    encoding: str
    normalization: str
    unknown_field_policy: str

    def __post_init__(self) -> None:
        _require_identifier("canonicalization_id", self.canonicalization_id)
        _require_identifier("schema_version", self.schema_version)
        names = tuple(rule[0] for rule in self.field_rules)
        if not names or len(set(names)) != len(names):
            raise CustodyContractValidationError("field_rules must be non-empty and unique")
        for name, kind, rule in self.field_rules:
            _require_field_name("field name", name)
            _require_enum("field kind", kind, PayloadFieldKind)
            if (kind is PayloadFieldKind.DYNAMIC_DERIVED) != (rule is not None):
                raise CustodyContractValidationError(
                    "exactly the dynamic fields must declare a derivation rule"
                )
        if self.unknown_field_policy != "deny":
            raise CustodyContractValidationError("unknown_field_policy must be deny")

    @property
    def field_order(self) -> tuple[str, ...]:
        """Return the canonical field order."""

        return tuple(rule[0] for rule in self.field_rules)


RD01_RECEIPT_CANONICALIZATION: Final[PayloadCanonicalizationSpec] = PayloadCanonicalizationSpec(
    canonicalization_id=RD01_RECEIPT_CANONICALIZATION_ID,
    schema_version=RD01_RECEIPT_SCHEMA_VERSION,
    field_rules=(
        ("version", PayloadFieldKind.STATIC_BOUND, None),
        ("purpose", PayloadFieldKind.STATIC_BOUND, None),
        (
            "receipt_identifier",
            PayloadFieldKind.DYNAMIC_DERIVED,
            PayloadDerivationRule.RECEIPT_IDENTIFIER_FROM_AUTHORIZATION_AND_OPERATION,
        ),
        ("verifier_identifier", PayloadFieldKind.STATIC_BOUND, None),
        ("subject_identifier", PayloadFieldKind.STATIC_BOUND, None),
        ("scope_fingerprint", PayloadFieldKind.STATIC_BOUND, None),
        (
            "issued_at_epoch_seconds",
            PayloadFieldKind.DYNAMIC_DERIVED,
            PayloadDerivationRule.ISSUED_AT_FROM_GOVERNED_TIME,
        ),
        (
            "expires_at_epoch_seconds",
            PayloadFieldKind.DYNAMIC_DERIVED,
            PayloadDerivationRule.EXPIRES_AT_FROM_ISSUED_AT_PLUS_TTL,
        ),
        ("decision_reference", PayloadFieldKind.STATIC_BOUND, None),
        ("integrity_proof_identifier", PayloadFieldKind.STATIC_BOUND, None),
    ),
    separator="=",
    line_terminator="\n",
    encoding="utf-8",
    normalization="none",
    unknown_field_policy="deny",
)

PAYLOAD_CANONICALIZATIONS: Final[Mapping[str, PayloadCanonicalizationSpec]] = MappingProxyType(
    {RD01_RECEIPT_CANONICALIZATION_ID: RD01_RECEIPT_CANONICALIZATION}
)


@dataclass(frozen=True)
class KeyRef:
    """Reference to a custody key by identity; it never carries a path."""

    key_id: str
    key_version: int
    key_fingerprint: str
    key_purpose_class: KeyPurposeClass
    algorithm_profile: str
    backend_id: str

    def __post_init__(self) -> None:
        _require_token("key_id", self.key_id)
        _require_positive_int("key_version", self.key_version)
        _require_openssh_fingerprint("key_fingerprint", self.key_fingerprint)
        _require_enum("key_purpose_class", self.key_purpose_class, KeyPurposeClass)
        _require_token("algorithm_profile", self.algorithm_profile)
        _require_token("backend_id", self.backend_id)

    def to_document(self) -> dict[str, object]:
        """Return the JSON-compatible document form."""

        return {
            "key_id": self.key_id,
            "key_version": self.key_version,
            "key_fingerprint": self.key_fingerprint,
            "key_purpose_class": self.key_purpose_class.value,
            "algorithm_profile": self.algorithm_profile,
            "backend_id": self.backend_id,
        }

    @classmethod
    def from_mapping(cls, data: object) -> KeyRef:
        """Parse a strict mapping; unknown or missing fields deny."""

        document = _exact_mapping(
            "key_ref",
            data,
            frozenset(
                {
                    "key_id",
                    "key_version",
                    "key_fingerprint",
                    "key_purpose_class",
                    "algorithm_profile",
                    "backend_id",
                }
            ),
        )
        return cls(
            key_id=_require_token("key_id", document["key_id"]),
            key_version=_require_positive_int("key_version", document["key_version"]),
            key_fingerprint=_require_openssh_fingerprint(
                "key_fingerprint", document["key_fingerprint"]
            ),
            key_purpose_class=_parse_enum(
                "key_purpose_class", document["key_purpose_class"], KeyPurposeClass
            ),
            algorithm_profile=_require_token("algorithm_profile", document["algorithm_profile"]),
            backend_id=_require_token("backend_id", document["backend_id"]),
        )


@dataclass(frozen=True)
class PayloadFieldSpec:
    """One canonical payload field: statically bound XOR dynamically derived."""

    name: str
    kind: PayloadFieldKind
    static_value: str | None = None
    derivation: PayloadDerivationRule | None = None

    def __post_init__(self) -> None:
        _require_field_name("name", self.name)
        _require_enum("kind", self.kind, PayloadFieldKind)
        if self.kind is PayloadFieldKind.STATIC_BOUND:
            _require_payload_text("static_value", self.static_value)
            if self.derivation is not None:
                raise CustodyContractValidationError("a static field must not declare a derivation")
        else:
            if self.static_value is not None:
                raise CustodyContractValidationError(
                    "a dynamic field must not carry a static value"
                )
            _require_enum("derivation", self.derivation, PayloadDerivationRule)

    def to_document(self) -> dict[str, object]:
        """Return the JSON-compatible document form."""

        return {
            "name": self.name,
            "kind": self.kind.value,
            "static_value": self.static_value,
            "derivation": None if self.derivation is None else self.derivation.value,
        }

    @classmethod
    def from_mapping(cls, data: object) -> PayloadFieldSpec:
        """Parse a strict mapping; unknown or missing fields deny."""

        document = _exact_mapping(
            "payload_field",
            data,
            frozenset({"name", "kind", "static_value", "derivation"}),
        )
        static_value = document["static_value"]
        derivation = document["derivation"]
        return cls(
            name=_require_field_name("name", document["name"]),
            kind=_parse_enum("kind", document["kind"], PayloadFieldKind),
            static_value=None
            if static_value is None
            else _require_payload_text("static_value", static_value),
            derivation=None
            if derivation is None
            else _parse_enum("derivation", derivation, PayloadDerivationRule),
        )


def _template_document(
    canonicalization_id: str,
    schema_version: str,
    fields: tuple[PayloadFieldSpec, ...],
    ttl_seconds: int,
) -> dict[str, object]:
    return {
        "canonicalization_id": canonicalization_id,
        "schema_version": schema_version,
        "fields": [field.to_document() for field in fields],
        "authorization_fixed_ttl_seconds": ttl_seconds,
        "unknown_field_policy": "deny",
    }


@dataclass(frozen=True)
class PayloadTemplateCommitment:
    """A payload template and its commitment, issued before ceremony-time fields exist.

    The commitment binds every static field value, the ordered field set, the
    declared derivation rule of every dynamic field, the fixed time-to-live and
    the canonicalization identifier. It is not a commitment to final bytes,
    because the final bytes contain fields derived from governed time evidence.
    """

    canonicalization_id: str
    schema_version: str
    fields: tuple[PayloadFieldSpec, ...]
    authorization_fixed_ttl_seconds: int
    commitment_digest: str

    def __post_init__(self) -> None:
        _require_identifier("canonicalization_id", self.canonicalization_id)
        _require_identifier("schema_version", self.schema_version)
        if type(self.fields) is not tuple or not self.fields:
            raise CustodyContractValidationError("fields must be a non-empty exact tuple")
        for field in self.fields:
            if type(field) is not PayloadFieldSpec:
                raise CustodyContractValidationError("fields must contain PayloadFieldSpec only")
        names = tuple(field.name for field in self.fields)
        if len(set(names)) != len(names):
            raise CustodyContractValidationError("fields must not contain duplicate names")
        _require_positive_int(
            "authorization_fixed_ttl_seconds", self.authorization_fixed_ttl_seconds
        )
        _require_sha256_hex("commitment_digest", self.commitment_digest)
        expected = _compute_template_digest(
            self.canonicalization_id,
            self.schema_version,
            self.fields,
            self.authorization_fixed_ttl_seconds,
        )
        if not hmac.compare_digest(expected, self.commitment_digest):
            raise CustodyContractValidationError("commitment_digest does not match the template")

    @classmethod
    def build(
        cls,
        *,
        canonicalization_id: str,
        schema_version: str,
        fields: tuple[PayloadFieldSpec, ...],
        authorization_fixed_ttl_seconds: int,
    ) -> PayloadTemplateCommitment:
        """Build a template and compute its commitment digest."""

        digest = _compute_template_digest(
            canonicalization_id, schema_version, fields, authorization_fixed_ttl_seconds
        )
        return cls(
            canonicalization_id=canonicalization_id,
            schema_version=schema_version,
            fields=fields,
            authorization_fixed_ttl_seconds=authorization_fixed_ttl_seconds,
            commitment_digest=digest,
        )

    def to_document(self) -> dict[str, object]:
        """Return the JSON-compatible document form."""

        document = _template_document(
            self.canonicalization_id,
            self.schema_version,
            self.fields,
            self.authorization_fixed_ttl_seconds,
        )
        document["commitment_digest"] = self.commitment_digest
        return document

    @classmethod
    def from_mapping(cls, data: object) -> PayloadTemplateCommitment:
        """Parse a strict mapping; unknown or missing fields deny."""

        document = _exact_mapping(
            "payload_template",
            data,
            frozenset(
                {
                    "canonicalization_id",
                    "schema_version",
                    "fields",
                    "authorization_fixed_ttl_seconds",
                    "unknown_field_policy",
                    "commitment_digest",
                }
            ),
        )
        if document["unknown_field_policy"] != "deny":
            raise CustodyContractValidationError("unknown_field_policy must be deny")
        return cls(
            canonicalization_id=_require_identifier(
                "canonicalization_id", document["canonicalization_id"]
            ),
            schema_version=_require_identifier("schema_version", document["schema_version"]),
            fields=tuple(
                PayloadFieldSpec.from_mapping(item)
                for item in _sequence_to_tuple("fields", document["fields"])
            ),
            authorization_fixed_ttl_seconds=_require_positive_int(
                "authorization_fixed_ttl_seconds", document["authorization_fixed_ttl_seconds"]
            ),
            commitment_digest=_require_sha256_hex(
                "commitment_digest", document["commitment_digest"]
            ),
        )


def _compute_template_digest(
    canonicalization_id: str,
    schema_version: str,
    fields: tuple[PayloadFieldSpec, ...],
    ttl_seconds: int,
) -> str:
    document = _template_document(canonicalization_id, schema_version, fields, ttl_seconds)
    return hashlib.sha256(canonical_json_bytes(document)).hexdigest()


_ENVELOPE_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "authorization_id",
        "operation_id",
        "issuer_ref",
        "verifier_ref",
        "issuer_trust_version",
        "issuance_record_digest",
        "issued_at_epoch_seconds",
        "not_before_epoch_seconds",
        "expires_at_epoch_seconds",
        "actor_ref",
        "actor_kind",
        "represented_actor_ref",
        "eligible_approver_refs",
        "upstream_approval_challenge",
        "family_or_security_domain",
        "capability_id",
        "capability_version",
        "action",
        "resource_ref",
        "scope_fingerprint",
        "audience_custody_profile",
        "result_audience",
        "key_ref",
        "signature_namespace",
        "human_presence_requirement",
        "payload_template",
        "replay_policy",
        "policy_version",
        "revocation_handle",
        "delegation_chain",
    }
)


@dataclass(frozen=True)
class AuthorizationEnvelope:
    """Structured worker-facing authorization derived from a governed issuance record.

    The envelope carries no approval evidence: upstream fields may pre-bind
    eligibility and challenge material but never substitute for the local human
    confirmation at the custody boundary. Its digest is computed over the whole
    canonical structure and is what a trust anchor pins.
    """

    schema_version: str
    authorization_id: str
    operation_id: str
    issuer_ref: str
    verifier_ref: str
    issuer_trust_version: str
    issuance_record_digest: str
    issued_at_epoch_seconds: int
    not_before_epoch_seconds: int
    expires_at_epoch_seconds: int
    actor_ref: str
    actor_kind: ActorKind
    represented_actor_ref: str | None
    eligible_approver_refs: tuple[str, ...]
    upstream_approval_challenge: str | None
    family_or_security_domain: str
    capability_id: str
    capability_version: str
    action: str
    resource_ref: str
    scope_fingerprint: str
    audience_custody_profile: str
    result_audience: str
    key_ref: KeyRef
    signature_namespace: str
    human_presence_requirement: HumanPresenceRequirement
    payload_template: PayloadTemplateCommitment
    replay_policy: ReplayPolicy
    policy_version: str
    revocation_handle: str
    delegation_chain: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_identifier("schema_version", self.schema_version)
        for name in (
            "authorization_id",
            "operation_id",
            "issuer_ref",
            "verifier_ref",
            "actor_ref",
            "family_or_security_domain",
            "capability_id",
            "resource_ref",
            "audience_custody_profile",
            "result_audience",
            "signature_namespace",
            "revocation_handle",
        ):
            _require_identifier(name, getattr(self, name))
        for name in ("issuer_trust_version", "capability_version", "action", "policy_version"):
            _require_token(name, getattr(self, name))
        _require_sha256_hex("issuance_record_digest", self.issuance_record_digest)
        _require_sha256_hex("scope_fingerprint", self.scope_fingerprint)
        issued = _require_exact_nonnegative_int(
            "issued_at_epoch_seconds", self.issued_at_epoch_seconds
        )
        not_before = _require_exact_nonnegative_int(
            "not_before_epoch_seconds", self.not_before_epoch_seconds
        )
        expires = _require_exact_nonnegative_int(
            "expires_at_epoch_seconds", self.expires_at_epoch_seconds
        )
        if not issued <= not_before < expires:
            raise CustodyContractValidationError(
                "time bounds must satisfy issued_at <= not_before < expires_at"
            )
        _require_enum("actor_kind", self.actor_kind, ActorKind)
        _require_optional_identifier("represented_actor_ref", self.represented_actor_ref)
        _require_identifier_tuple(
            "eligible_approver_refs", self.eligible_approver_refs, allow_empty=False
        )
        if self.upstream_approval_challenge is not None:
            _require_challenge("upstream_approval_challenge", self.upstream_approval_challenge)
        if type(self.key_ref) is not KeyRef:
            raise CustodyContractValidationError("key_ref must be a KeyRef")
        _require_enum(
            "human_presence_requirement", self.human_presence_requirement, HumanPresenceRequirement
        )
        if type(self.payload_template) is not PayloadTemplateCommitment:
            raise CustodyContractValidationError(
                "payload_template must be a PayloadTemplateCommitment"
            )
        _require_enum("replay_policy", self.replay_policy, ReplayPolicy)
        _require_identifier_tuple("delegation_chain", self.delegation_chain, allow_empty=True)

    def to_document(self) -> dict[str, object]:
        """Return the JSON-compatible document form."""

        return {
            "schema_version": self.schema_version,
            "authorization_id": self.authorization_id,
            "operation_id": self.operation_id,
            "issuer_ref": self.issuer_ref,
            "verifier_ref": self.verifier_ref,
            "issuer_trust_version": self.issuer_trust_version,
            "issuance_record_digest": self.issuance_record_digest,
            "issued_at_epoch_seconds": self.issued_at_epoch_seconds,
            "not_before_epoch_seconds": self.not_before_epoch_seconds,
            "expires_at_epoch_seconds": self.expires_at_epoch_seconds,
            "actor_ref": self.actor_ref,
            "actor_kind": self.actor_kind.value,
            "represented_actor_ref": self.represented_actor_ref,
            "eligible_approver_refs": list(self.eligible_approver_refs),
            "upstream_approval_challenge": self.upstream_approval_challenge,
            "family_or_security_domain": self.family_or_security_domain,
            "capability_id": self.capability_id,
            "capability_version": self.capability_version,
            "action": self.action,
            "resource_ref": self.resource_ref,
            "scope_fingerprint": self.scope_fingerprint,
            "audience_custody_profile": self.audience_custody_profile,
            "result_audience": self.result_audience,
            "key_ref": self.key_ref.to_document(),
            "signature_namespace": self.signature_namespace,
            "human_presence_requirement": self.human_presence_requirement.value,
            "payload_template": self.payload_template.to_document(),
            "replay_policy": self.replay_policy.value,
            "policy_version": self.policy_version,
            "revocation_handle": self.revocation_handle,
            "delegation_chain": list(self.delegation_chain),
        }

    def canonical_bytes(self) -> bytes:
        """Return the deterministic canonical bytes that a trust anchor pins."""

        return canonical_json_bytes(self.to_document())

    def digest(self) -> str:
        """Return the SHA-256 digest of the canonical envelope bytes."""

        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @classmethod
    def from_mapping(cls, data: object) -> AuthorizationEnvelope:
        """Parse a strict mapping; unknown, missing or ambiguous fields deny."""

        document = _exact_mapping("authorization_envelope", data, _ENVELOPE_FIELD_NAMES)
        represented = document["represented_actor_ref"]
        upstream = document["upstream_approval_challenge"]
        return cls(
            schema_version=_require_identifier("schema_version", document["schema_version"]),
            authorization_id=_require_identifier("authorization_id", document["authorization_id"]),
            operation_id=_require_identifier("operation_id", document["operation_id"]),
            issuer_ref=_require_identifier("issuer_ref", document["issuer_ref"]),
            verifier_ref=_require_identifier("verifier_ref", document["verifier_ref"]),
            issuer_trust_version=_require_token(
                "issuer_trust_version", document["issuer_trust_version"]
            ),
            issuance_record_digest=_require_sha256_hex(
                "issuance_record_digest", document["issuance_record_digest"]
            ),
            issued_at_epoch_seconds=_require_exact_nonnegative_int(
                "issued_at_epoch_seconds", document["issued_at_epoch_seconds"]
            ),
            not_before_epoch_seconds=_require_exact_nonnegative_int(
                "not_before_epoch_seconds", document["not_before_epoch_seconds"]
            ),
            expires_at_epoch_seconds=_require_exact_nonnegative_int(
                "expires_at_epoch_seconds", document["expires_at_epoch_seconds"]
            ),
            actor_ref=_require_identifier("actor_ref", document["actor_ref"]),
            actor_kind=_parse_enum("actor_kind", document["actor_kind"], ActorKind),
            represented_actor_ref=_require_optional_identifier(
                "represented_actor_ref", represented
            ),
            eligible_approver_refs=tuple(
                _require_identifier("eligible_approver_refs", item)
                for item in _sequence_to_tuple(
                    "eligible_approver_refs", document["eligible_approver_refs"]
                )
            ),
            upstream_approval_challenge=None
            if upstream is None
            else _require_challenge("upstream_approval_challenge", upstream),
            family_or_security_domain=_require_identifier(
                "family_or_security_domain", document["family_or_security_domain"]
            ),
            capability_id=_require_identifier("capability_id", document["capability_id"]),
            capability_version=_require_token("capability_version", document["capability_version"]),
            action=_require_token("action", document["action"]),
            resource_ref=_require_identifier("resource_ref", document["resource_ref"]),
            scope_fingerprint=_require_sha256_hex(
                "scope_fingerprint", document["scope_fingerprint"]
            ),
            audience_custody_profile=_require_identifier(
                "audience_custody_profile", document["audience_custody_profile"]
            ),
            result_audience=_require_identifier("result_audience", document["result_audience"]),
            key_ref=KeyRef.from_mapping(document["key_ref"]),
            signature_namespace=_require_identifier(
                "signature_namespace", document["signature_namespace"]
            ),
            human_presence_requirement=_parse_enum(
                "human_presence_requirement",
                document["human_presence_requirement"],
                HumanPresenceRequirement,
            ),
            payload_template=PayloadTemplateCommitment.from_mapping(document["payload_template"]),
            replay_policy=_parse_enum("replay_policy", document["replay_policy"], ReplayPolicy),
            policy_version=_require_token("policy_version", document["policy_version"]),
            revocation_handle=_require_identifier(
                "revocation_handle", document["revocation_handle"]
            ),
            delegation_chain=tuple(
                _require_identifier("delegation_chain", item)
                for item in _sequence_to_tuple("delegation_chain", document["delegation_chain"])
            ),
        )

    @classmethod
    def from_json(cls, text: object) -> AuthorizationEnvelope:
        """Parse strict JSON text (duplicate keys, floats and unknown fields deny)."""

        return cls.from_mapping(loads_strict_json(text))


@dataclass(frozen=True)
class ApproverBinding:
    """Pinned mapping of one approver to a custody account and a purpose-scoped key."""

    approver_ref: str
    custody_account_id: str
    key_ref: KeyRef

    def __post_init__(self) -> None:
        _require_identifier("approver_ref", self.approver_ref)
        _require_identifier("custody_account_id", self.custody_account_id)
        if type(self.key_ref) is not KeyRef:
            raise CustodyContractValidationError("key_ref must be a KeyRef")
        if self.key_ref.key_purpose_class is not KeyPurposeClass.HUMAN_DECISION:
            raise CustodyContractValidationError("an approver key must be HUMAN_DECISION")

    def to_document(self) -> dict[str, object]:
        """Return the JSON-compatible document form."""

        return {
            "approver_ref": self.approver_ref,
            "custody_account_id": self.custody_account_id,
            "key_ref": self.key_ref.to_document(),
        }


@dataclass(frozen=True)
class TrustAnchorRecord:
    """Phase-1 trust anchor pinning one governed human issuance record.

    It pins the exact source issuance-record digest, the exact digest of the
    canonical structured envelope the worker consumes, and the verifier
    identity. Rotation and revocation are explicit and fail closed.
    """

    authorization_id: str
    issuer_ref: str
    verifier_ref: str
    record_version: str
    pinned_issuance_record_digest: str
    pinned_envelope_digest: str
    valid_from_epoch_seconds: int
    valid_until_epoch_seconds: int | None
    revocation_status: RevocationStatus
    supersedes: tuple[str, ...]
    superseded_by: str | None
    allowed_authorization_classes: tuple[KeyPurposeClass, ...]
    approver_bindings: tuple[ApproverBinding, ...]

    def __post_init__(self) -> None:
        for name in ("authorization_id", "issuer_ref", "verifier_ref"):
            _require_identifier(name, getattr(self, name))
        _require_token("record_version", self.record_version)
        _require_sha256_hex("pinned_issuance_record_digest", self.pinned_issuance_record_digest)
        _require_sha256_hex("pinned_envelope_digest", self.pinned_envelope_digest)
        valid_from = _require_exact_nonnegative_int(
            "valid_from_epoch_seconds", self.valid_from_epoch_seconds
        )
        if self.valid_until_epoch_seconds is not None:
            valid_until = _require_exact_nonnegative_int(
                "valid_until_epoch_seconds", self.valid_until_epoch_seconds
            )
            if valid_until <= valid_from:
                raise CustodyContractValidationError("valid_until must be greater than valid_from")
        _require_enum("revocation_status", self.revocation_status, RevocationStatus)
        _require_identifier_tuple("supersedes", self.supersedes, allow_empty=True)
        _require_optional_identifier("superseded_by", self.superseded_by)
        if type(self.allowed_authorization_classes) is not tuple:
            raise CustodyContractValidationError("allowed_authorization_classes must be a tuple")
        if not self.allowed_authorization_classes:
            raise CustodyContractValidationError("allowed_authorization_classes must not be empty")
        for purpose in self.allowed_authorization_classes:
            _require_enum("allowed_authorization_classes", purpose, KeyPurposeClass)
        if type(self.approver_bindings) is not tuple or not self.approver_bindings:
            raise CustodyContractValidationError("approver_bindings must be a non-empty tuple")
        approvers = tuple(binding.approver_ref for binding in self.approver_bindings)
        for binding in self.approver_bindings:
            if type(binding) is not ApproverBinding:
                raise CustodyContractValidationError("approver_bindings must hold ApproverBinding")
        if len(set(approvers)) != len(approvers):
            raise CustodyContractValidationError("approver_bindings must not repeat an approver")

    def binding_for(self, approver_ref: str) -> ApproverBinding | None:
        """Return the pinned binding of an approver, if any."""

        for binding in self.approver_bindings:
            if binding.approver_ref == approver_ref:
                return binding
        return None

    def to_document(self) -> dict[str, object]:
        """Return the JSON-compatible document form; unordered sets are sorted."""

        return {
            "authorization_id": self.authorization_id,
            "issuer_ref": self.issuer_ref,
            "verifier_ref": self.verifier_ref,
            "record_version": self.record_version,
            "pinned_issuance_record_digest": self.pinned_issuance_record_digest,
            "pinned_envelope_digest": self.pinned_envelope_digest,
            "valid_from_epoch_seconds": self.valid_from_epoch_seconds,
            "valid_until_epoch_seconds": self.valid_until_epoch_seconds,
            "revocation_status": self.revocation_status.value,
            "supersedes": list(self.supersedes),
            "superseded_by": self.superseded_by,
            "allowed_authorization_classes": sorted(
                purpose.value for purpose in self.allowed_authorization_classes
            ),
            "approver_bindings": [
                binding.to_document()
                for binding in sorted(self.approver_bindings, key=lambda item: item.approver_ref)
            ],
        }

    def digest(self) -> str:
        """Return the SHA-256 digest of the canonical anchor document."""

        return hashlib.sha256(canonical_json_bytes(self.to_document())).hexdigest()


@dataclass(frozen=True)
class ApproverEvidence:
    """Protected approval evidence produced at the custody boundary by the worker.

    ``approval_offset_seconds`` is a monotonic offset relative to the verified
    governed time evidence; a wall-clock assertion is not representable. This is
    worker-recorded evidence: it is bound to the signed final payload digest and to
    the worker's sealed evidence, but it is not itself covered by the receipt signature.
    """

    requester_ref: str
    represented_actor_ref: str | None
    approver_ref: str
    presenter_ref: str
    authorization_id: str
    operation_id: str
    final_payload_digest: str
    worker_challenge: str
    approval_offset_seconds: int
    human_presence_profile: HumanPresenceRequirement
    custody_account_id: str
    factors: tuple[ApprovalFactor, ...]

    def __post_init__(self) -> None:
        for name in (
            "requester_ref",
            "approver_ref",
            "presenter_ref",
            "authorization_id",
            "operation_id",
            "custody_account_id",
        ):
            _require_identifier(name, getattr(self, name))
        _require_optional_identifier("represented_actor_ref", self.represented_actor_ref)
        _require_sha256_hex("final_payload_digest", self.final_payload_digest)
        _require_challenge("worker_challenge", self.worker_challenge)
        _require_exact_nonnegative_int("approval_offset_seconds", self.approval_offset_seconds)
        _require_enum(
            "human_presence_profile", self.human_presence_profile, HumanPresenceRequirement
        )
        if type(self.factors) is not tuple:
            raise CustodyContractValidationError("factors must be an exact tuple")
        for factor in self.factors:
            _require_enum("factors", factor, ApprovalFactor)
        if len(set(self.factors)) != len(self.factors):
            raise CustodyContractValidationError("factors must not contain duplicates")

    def to_document(self) -> dict[str, object]:
        """Return the JSON-compatible document form; the factor set is sorted."""

        return {
            "requester_ref": self.requester_ref,
            "represented_actor_ref": self.represented_actor_ref,
            "approver_ref": self.approver_ref,
            "presenter_ref": self.presenter_ref,
            "authorization_id": self.authorization_id,
            "operation_id": self.operation_id,
            "final_payload_digest": self.final_payload_digest,
            "worker_challenge": self.worker_challenge,
            "approval_offset_seconds": self.approval_offset_seconds,
            "human_presence_profile": self.human_presence_profile.value,
            "custody_account_id": self.custody_account_id,
            "factors": sorted(factor.value for factor in self.factors),
        }

    def digest(self) -> str:
        """Return the SHA-256 digest of the canonical evidence document."""

        return hashlib.sha256(canonical_json_bytes(self.to_document())).hexdigest()


@dataclass(frozen=True)
class SigningRequest:
    """Reference-only request handed to the signer stage after final confirmation.

    A ``SigningRequest`` is not authority: any caller can construct one. The
    runtime records ``digest()`` in the authoritative claim when it claims the
    key-use intent. The irreversible boundary must call ``verify_signing_request``
    with the trusted inputs, which recomputes the whole chain and requires this
    exact request and its recorded digest; the release gate compares against the
    same recorded digest. ``not_after_epoch_seconds`` is an exclusive upper bound
    on governed time.
    """

    authorization_id: str
    operation_id: str
    key_ref: KeyRef
    signature_namespace: str
    canonicalization_id: str
    final_payload_digest: str
    payload_length: int
    result_audience: str
    context_digest: str
    chain_fingerprint: str
    issued_at_epoch_seconds: int
    not_after_epoch_seconds: int

    def __post_init__(self) -> None:
        _require_identifier("authorization_id", self.authorization_id)
        _require_identifier("operation_id", self.operation_id)
        if type(self.key_ref) is not KeyRef:
            raise CustodyContractValidationError("key_ref must be a KeyRef")
        _require_identifier("signature_namespace", self.signature_namespace)
        _require_identifier("canonicalization_id", self.canonicalization_id)
        _require_sha256_hex("final_payload_digest", self.final_payload_digest)
        _require_positive_int("payload_length", self.payload_length)
        _require_identifier("result_audience", self.result_audience)
        _require_sha256_hex("context_digest", self.context_digest)
        _require_sha256_hex("chain_fingerprint", self.chain_fingerprint)
        issued = _require_exact_nonnegative_int(
            "issued_at_epoch_seconds", self.issued_at_epoch_seconds
        )
        not_after = _require_exact_nonnegative_int(
            "not_after_epoch_seconds", self.not_after_epoch_seconds
        )
        if not_after <= issued:
            raise CustodyContractValidationError("not_after must be greater than issued_at")

    def to_document(self) -> dict[str, object]:
        """Return the JSON-compatible document form."""

        return {
            "authorization_id": self.authorization_id,
            "operation_id": self.operation_id,
            "key_ref": self.key_ref.to_document(),
            "signature_namespace": self.signature_namespace,
            "canonicalization_id": self.canonicalization_id,
            "final_payload_digest": self.final_payload_digest,
            "payload_length": self.payload_length,
            "result_audience": self.result_audience,
            "context_digest": self.context_digest,
            "chain_fingerprint": self.chain_fingerprint,
            "issued_at_epoch_seconds": self.issued_at_epoch_seconds,
            "not_after_epoch_seconds": self.not_after_epoch_seconds,
        }

    def digest(self) -> str:
        """Return the SHA-256 digest of the canonical request document."""

        return hashlib.sha256(canonical_json_bytes(self.to_document())).hexdigest()


@dataclass(frozen=True)
class SigningResult:
    """Result of one signing attempt.

    Freshness is not asserted: the elapsed monotonic time at signature completion is
    recorded and checked against the request's ``not_after``. The terminal record is
    not asserted either: the release gate reads it from the authoritative claim. The
    remaining conditions are facts that only the trusted runtime component that
    observed them may construct.
    """

    authorization_id: str
    operation_id: str
    key_ref: KeyRef
    signature_namespace: str
    final_payload_digest: str
    signature_sha256: str
    signature_verified: bool
    elapsed_at_signature_completion_seconds: int
    signer_reaped: bool
    custody_postconditions_verified: bool
    evidence_sealed: bool

    def __post_init__(self) -> None:
        _require_identifier("authorization_id", self.authorization_id)
        _require_identifier("operation_id", self.operation_id)
        if type(self.key_ref) is not KeyRef:
            raise CustodyContractValidationError("key_ref must be a KeyRef")
        _require_identifier("signature_namespace", self.signature_namespace)
        _require_sha256_hex("final_payload_digest", self.final_payload_digest)
        _require_sha256_hex("signature_sha256", self.signature_sha256)
        _require_exact_nonnegative_int(
            "elapsed_at_signature_completion_seconds", self.elapsed_at_signature_completion_seconds
        )
        for name in (
            "signature_verified",
            "signer_reaped",
            "custody_postconditions_verified",
            "evidence_sealed",
        ):
            _require_exact_bool(name, getattr(self, name))


@dataclass(frozen=True)
class ReplayClaim:
    """One record of the authoritative single-use claim.

    ``claim_generation`` is the monotonic transaction generation used as anti-rollback
    evidence. ``context_digest`` binds the claim to the exact envelope, trust anchor and
    worker profile that were admitted when it was created; later stages must present the
    same context, so a substituted anchor or a looser profile is denied.
    """

    authorization_id: str
    operation_id: str
    claim_generation: int
    state: ReplayClaimState
    non_key_resources_consumed: tuple[str, ...]
    key_use_intent_durable: bool
    context_digest: str
    signing_request_digest: str | None = None

    def __post_init__(self) -> None:
        _require_identifier("authorization_id", self.authorization_id)
        _require_identifier("operation_id", self.operation_id)
        _require_exact_nonnegative_int("claim_generation", self.claim_generation)
        _require_sha256_hex("context_digest", self.context_digest)
        if self.signing_request_digest is not None:
            _require_sha256_hex("signing_request_digest", self.signing_request_digest)
        _require_enum("state", self.state, ReplayClaimState)
        _require_identifier_tuple(
            "non_key_resources_consumed", self.non_key_resources_consumed, allow_empty=True
        )
        _require_exact_bool("key_use_intent_durable", self.key_use_intent_durable)
        if self.state in (ReplayClaimState.RESOURCES_RESERVED, ReplayClaimState.NO_KEY_USE) and (
            self.key_use_intent_durable
        ):
            raise CustodyContractValidationError(f"{self.state.value} cannot record key-use intent")
        if (
            self.state
            in (
                ReplayClaimState.KEY_USE_CLAIMED,
                ReplayClaimState.SPENT_CLEAN,
            )
            and not self.key_use_intent_durable
        ):
            raise CustodyContractValidationError(f"{self.state.value} requires key-use intent")
        if (
            self.state
            in (
                ReplayClaimState.KEY_USE_CLAIMED,
                ReplayClaimState.SPENT_CLEAN,
            )
            and self.signing_request_digest is None
        ):
            raise CustodyContractValidationError(
                f"{self.state.value} requires the recorded signing request digest"
            )
        if (
            self.state in (ReplayClaimState.RESOURCES_RESERVED, ReplayClaimState.NO_KEY_USE)
            and self.signing_request_digest is not None
        ):
            raise CustodyContractValidationError(
                f"{self.state.value} cannot carry a signing request digest"
            )

    @property
    def is_terminal(self) -> bool:
        """Return whether a trusted terminal state has been recorded."""

        return self.state in _TERMINAL_CLAIM_STATES


def stricter_claim_state(left: ReplayClaimState, right: ReplayClaimState) -> ReplayClaimState:
    """Return the stricter of two claim states; ``QUARANTINED`` is the strictest."""

    if _CLAIM_STATE_STRICTNESS[left] >= _CLAIM_STATE_STRICTNESS[right]:
        return left
    return right


def claim_state_after_durable_write_failure(current: ReplayClaimState | None) -> ReplayClaimState:
    """Return the state to record after any durable-write failure: spent or stricter.

    A failed reservation, key-use-intent, terminal-state or claim-consumption
    write is never success and never permits automatic reuse.
    """

    if current is None:
        return ReplayClaimState.SPENT_UNKNOWN
    return stricter_claim_state(current, ReplayClaimState.SPENT_UNKNOWN)


def recover_claim_after_restart(claim: ReplayClaim) -> ReplayClaim:
    """Classify a claim found at startup that lacks a trusted terminal record.

    An in-flight key-use claim becomes ``SPENT_UNKNOWN``. In-flight resource
    reservations become ``NO_KEY_USE`` with the reserved resources treated as
    consumed. Terminal records are returned unchanged.
    """

    if type(claim) is not ReplayClaim:
        raise CustodyContractValidationError("claim must be an exact ReplayClaim")
    if claim.is_terminal:
        return claim
    if claim.state is ReplayClaimState.KEY_USE_CLAIMED:
        return ReplayClaim(
            authorization_id=claim.authorization_id,
            operation_id=claim.operation_id,
            claim_generation=claim.claim_generation + 1,
            state=ReplayClaimState.SPENT_UNKNOWN,
            non_key_resources_consumed=claim.non_key_resources_consumed,
            key_use_intent_durable=True,
            context_digest=claim.context_digest,
            signing_request_digest=claim.signing_request_digest,
        )
    return ReplayClaim(
        authorization_id=claim.authorization_id,
        operation_id=claim.operation_id,
        claim_generation=claim.claim_generation + 1,
        state=ReplayClaimState.NO_KEY_USE,
        non_key_resources_consumed=claim.non_key_resources_consumed,
        key_use_intent_durable=False,
        context_digest=claim.context_digest,
    )
