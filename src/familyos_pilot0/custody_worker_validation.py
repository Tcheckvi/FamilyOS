"""Pure Phase-1 custody worker validation for FamilyOS Pilot 0 (F05 I2).

This module evaluates governed custody inputs against the immutable I1-R1
contracts. The RD-01 bindings are pinned by the I1-R1 SPEC-0017 v1.1.0
contract constants. This module performs no I/O and never authorizes key use.

A successful validation only means that the supplied context is internally
consistent and may advance to a later, separately governed custody step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from familyos_pilot0.custody_worker_contracts import (
    RD01_RECEIPT_CANONICALIZATION,
    RD01_RECEIPT_CANONICALIZATION_ID,
    RD01_RECEIPT_SCHEMA_VERSION,
    RD01_SIGNATURE_NAMESPACE,
    ApproverEvidence,
    AuthorizationEnvelope,
    KeyPurposeClass,
    RevocationStatus,
    TrustAnchorRecord,
)

_SHA256_HEX_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_CHALLENGE_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{32,128}$")


class CustodyValidationReason(StrEnum):
    """Deterministic fail-closed reasons emitted by Phase-1 validation."""

    INVALID_GOVERNED_TIME = "INVALID_GOVERNED_TIME"
    INVALID_EXPECTED_PAYLOAD_DIGEST = "INVALID_EXPECTED_PAYLOAD_DIGEST"
    INVALID_EXPECTED_WORKER_CHALLENGE = "INVALID_EXPECTED_WORKER_CHALLENGE"

    AUTHORIZATION_ID_MISMATCH = "AUTHORIZATION_ID_MISMATCH"
    OPERATION_ID_MISMATCH = "OPERATION_ID_MISMATCH"
    ISSUER_MISMATCH = "ISSUER_MISMATCH"
    VERIFIER_MISMATCH = "VERIFIER_MISMATCH"
    ISSUANCE_RECORD_DIGEST_MISMATCH = "ISSUANCE_RECORD_DIGEST_MISMATCH"
    ENVELOPE_DIGEST_MISMATCH = "ENVELOPE_DIGEST_MISMATCH"

    TRUST_ANCHOR_REVOKED = "TRUST_ANCHOR_REVOKED"
    TRUST_ANCHOR_NOT_YET_VALID = "TRUST_ANCHOR_NOT_YET_VALID"
    TRUST_ANCHOR_EXPIRED = "TRUST_ANCHOR_EXPIRED"
    AUTHORIZATION_NOT_YET_VALID = "AUTHORIZATION_NOT_YET_VALID"
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"

    KEY_PURPOSE_MISMATCH = "KEY_PURPOSE_MISMATCH"
    KEY_PURPOSE_NOT_ALLOWED = "KEY_PURPOSE_NOT_ALLOWED"
    APPROVER_NOT_ELIGIBLE = "APPROVER_NOT_ELIGIBLE"
    APPROVER_NOT_ANCHORED = "APPROVER_NOT_ANCHORED"
    CUSTODY_ACCOUNT_MISMATCH = "CUSTODY_ACCOUNT_MISMATCH"
    APPROVER_KEY_MISMATCH = "APPROVER_KEY_MISMATCH"

    REQUESTER_MISMATCH = "REQUESTER_MISMATCH"
    REPRESENTED_ACTOR_MISMATCH = "REPRESENTED_ACTOR_MISMATCH"
    HUMAN_PRESENCE_MISMATCH = "HUMAN_PRESENCE_MISMATCH"
    PAYLOAD_DIGEST_MISMATCH = "PAYLOAD_DIGEST_MISMATCH"
    WORKER_CHALLENGE_MISMATCH = "WORKER_CHALLENGE_MISMATCH"

    SIGNATURE_NAMESPACE_MISMATCH = "SIGNATURE_NAMESPACE_MISMATCH"
    CANONICALIZATION_ID_MISMATCH = "CANONICALIZATION_ID_MISMATCH"
    SCHEMA_VERSION_MISMATCH = "SCHEMA_VERSION_MISMATCH"
    PAYLOAD_TEMPLATE_RULES_MISMATCH = "PAYLOAD_TEMPLATE_RULES_MISMATCH"


@dataclass(frozen=True)
class CustodyValidationDecision:
    """Pure validation outcome.

    ``key_use_authorized`` is deliberately a computed constant. No caller can
    construct a Phase-1 decision that authorizes a key.
    """

    reasons: tuple[CustodyValidationReason, ...]

    @property
    def validation_passed(self) -> bool:
        """Whether every invariant checked by this tranche passed."""

        return not self.reasons

    @property
    def key_use_authorized(self) -> bool:
        """Phase 1 never authorizes key use."""

        return False


def _is_exact_nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _is_sha256_hex(value: object) -> bool:
    return type(value) is str and _SHA256_HEX_RE.fullmatch(value) is not None


def _is_worker_challenge(value: object) -> bool:
    return type(value) is str and _CHALLENGE_RE.fullmatch(value) is not None


def _payload_template_rules_match(envelope: AuthorizationEnvelope) -> bool:
    actual = tuple(
        (field.name, field.kind, field.derivation) for field in envelope.payload_template.fields
    )
    return actual == RD01_RECEIPT_CANONICALIZATION.field_rules


def validate_custody_worker_context(
    *,
    envelope: AuthorizationEnvelope,
    trust_anchor: TrustAnchorRecord,
    approver_evidence: ApproverEvidence,
    governed_epoch_seconds: int,
    expected_final_payload_digest: str,
    expected_worker_challenge: str,
) -> CustodyValidationDecision:
    """Validate one Phase-1 custody context without authorizing key use.

    The function is deterministic and side-effect free. It checks cross-contract
    identity, trust, time, approver, payload and SPEC-0017 RD-01 bindings. It
    never touches a key or a signer.
    """

    reasons: list[CustodyValidationReason] = []

    if not _is_exact_nonnegative_int(governed_epoch_seconds):
        reasons.append(CustodyValidationReason.INVALID_GOVERNED_TIME)
    if not _is_sha256_hex(expected_final_payload_digest):
        reasons.append(CustodyValidationReason.INVALID_EXPECTED_PAYLOAD_DIGEST)
    if not _is_worker_challenge(expected_worker_challenge):
        reasons.append(CustodyValidationReason.INVALID_EXPECTED_WORKER_CHALLENGE)

    if trust_anchor.authorization_id != envelope.authorization_id:
        reasons.append(CustodyValidationReason.AUTHORIZATION_ID_MISMATCH)
    if approver_evidence.authorization_id != envelope.authorization_id:
        reasons.append(CustodyValidationReason.AUTHORIZATION_ID_MISMATCH)
    if approver_evidence.operation_id != envelope.operation_id:
        reasons.append(CustodyValidationReason.OPERATION_ID_MISMATCH)

    if trust_anchor.issuer_ref != envelope.issuer_ref:
        reasons.append(CustodyValidationReason.ISSUER_MISMATCH)
    if trust_anchor.verifier_ref != envelope.verifier_ref:
        reasons.append(CustodyValidationReason.VERIFIER_MISMATCH)
    if trust_anchor.pinned_issuance_record_digest != envelope.issuance_record_digest:
        reasons.append(CustodyValidationReason.ISSUANCE_RECORD_DIGEST_MISMATCH)
    if trust_anchor.pinned_envelope_digest != envelope.digest():
        reasons.append(CustodyValidationReason.ENVELOPE_DIGEST_MISMATCH)

    if trust_anchor.revocation_status is not RevocationStatus.ACTIVE:
        reasons.append(CustodyValidationReason.TRUST_ANCHOR_REVOKED)

    if _is_exact_nonnegative_int(governed_epoch_seconds):
        if governed_epoch_seconds < trust_anchor.valid_from_epoch_seconds:
            reasons.append(CustodyValidationReason.TRUST_ANCHOR_NOT_YET_VALID)
        if (
            trust_anchor.valid_until_epoch_seconds is not None
            and governed_epoch_seconds > trust_anchor.valid_until_epoch_seconds
        ):
            reasons.append(CustodyValidationReason.TRUST_ANCHOR_EXPIRED)
        if governed_epoch_seconds < envelope.not_before_epoch_seconds:
            reasons.append(CustodyValidationReason.AUTHORIZATION_NOT_YET_VALID)
        if governed_epoch_seconds > envelope.expires_at_epoch_seconds:
            reasons.append(CustodyValidationReason.AUTHORIZATION_EXPIRED)

    if envelope.key_ref.key_purpose_class is not KeyPurposeClass.HUMAN_DECISION:
        reasons.append(CustodyValidationReason.KEY_PURPOSE_MISMATCH)
    if envelope.key_ref.key_purpose_class not in trust_anchor.allowed_authorization_classes:
        reasons.append(CustodyValidationReason.KEY_PURPOSE_NOT_ALLOWED)

    if approver_evidence.approver_ref not in envelope.eligible_approver_refs:
        reasons.append(CustodyValidationReason.APPROVER_NOT_ELIGIBLE)

    approver_binding = trust_anchor.binding_for(approver_evidence.approver_ref)
    if approver_binding is None:
        reasons.append(CustodyValidationReason.APPROVER_NOT_ANCHORED)
    else:
        if approver_binding.custody_account_id != approver_evidence.custody_account_id:
            reasons.append(CustodyValidationReason.CUSTODY_ACCOUNT_MISMATCH)
        if approver_binding.key_ref != envelope.key_ref:
            reasons.append(CustodyValidationReason.APPROVER_KEY_MISMATCH)

    if approver_evidence.requester_ref != envelope.actor_ref:
        reasons.append(CustodyValidationReason.REQUESTER_MISMATCH)
    if approver_evidence.represented_actor_ref != envelope.represented_actor_ref:
        reasons.append(CustodyValidationReason.REPRESENTED_ACTOR_MISMATCH)
    if approver_evidence.human_presence_profile is not envelope.human_presence_requirement:
        reasons.append(CustodyValidationReason.HUMAN_PRESENCE_MISMATCH)

    if approver_evidence.final_payload_digest != expected_final_payload_digest:
        reasons.append(CustodyValidationReason.PAYLOAD_DIGEST_MISMATCH)
    if approver_evidence.worker_challenge != expected_worker_challenge:
        reasons.append(CustodyValidationReason.WORKER_CHALLENGE_MISMATCH)

    if envelope.signature_namespace != RD01_SIGNATURE_NAMESPACE:
        reasons.append(CustodyValidationReason.SIGNATURE_NAMESPACE_MISMATCH)
    if envelope.payload_template.canonicalization_id != RD01_RECEIPT_CANONICALIZATION_ID:
        reasons.append(CustodyValidationReason.CANONICALIZATION_ID_MISMATCH)
    if envelope.payload_template.schema_version != RD01_RECEIPT_SCHEMA_VERSION:
        reasons.append(CustodyValidationReason.SCHEMA_VERSION_MISMATCH)
    if not _payload_template_rules_match(envelope):
        reasons.append(CustodyValidationReason.PAYLOAD_TEMPLATE_RULES_MISMATCH)

    return CustodyValidationDecision(reasons=tuple(dict.fromkeys(reasons)))
