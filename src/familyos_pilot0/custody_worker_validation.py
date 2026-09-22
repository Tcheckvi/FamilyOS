"""Pure Phase-1 custody worker validation for FamilyOS Pilot 0 (F05 I2).

This module evaluates governed custody inputs against the immutable I1-R1
contracts. The RD-01 bindings are pinned by the I1-R1 SPEC-0017 v1.1.0
contract constants. This module performs no I/O and never authorizes key use.

I2-R1 validates the governed custody context. I2-R2 adds pure signing-request
verification and single-use replay preflight. Passing either layer only means
that the supplied state is internally consistent enough to advance to a later,
separately governed custody boundary.
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
    ReplayClaim,
    ReplayClaimState,
    ReplayPolicy,
    RevocationStatus,
    SigningRequest,
    SigningResult,
    TrustAnchorRecord,
)

_SHA256_HEX_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_CHALLENGE_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{32,128}$")


class CustodyValidationReason(StrEnum):
    """Deterministic fail-closed reasons emitted by Phase-1 validation."""

    INVALID_GOVERNED_TIME = "INVALID_GOVERNED_TIME"
    INVALID_EXPECTED_PAYLOAD_DIGEST = "INVALID_EXPECTED_PAYLOAD_DIGEST"
    INVALID_EXPECTED_WORKER_CHALLENGE = "INVALID_EXPECTED_WORKER_CHALLENGE"
    INVALID_EXPECTED_CONTEXT_DIGEST = "INVALID_EXPECTED_CONTEXT_DIGEST"
    INVALID_EXPECTED_CHAIN_FINGERPRINT = "INVALID_EXPECTED_CHAIN_FINGERPRINT"

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

    REPLAY_POLICY_MISMATCH = "REPLAY_POLICY_MISMATCH"
    CLAIM_AUTHORIZATION_ID_MISMATCH = "CLAIM_AUTHORIZATION_ID_MISMATCH"
    CLAIM_OPERATION_ID_MISMATCH = "CLAIM_OPERATION_ID_MISMATCH"
    CLAIM_CONTEXT_DIGEST_MISMATCH = "CLAIM_CONTEXT_DIGEST_MISMATCH"
    CLAIM_NOT_RESERVED = "CLAIM_NOT_RESERVED"
    CLAIM_NOT_KEY_USE_CLAIMED = "CLAIM_NOT_KEY_USE_CLAIMED"
    CLAIM_KEY_USE_INTENT_NOT_DURABLE = "CLAIM_KEY_USE_INTENT_NOT_DURABLE"
    CLAIM_SIGNING_REQUEST_DIGEST_MISSING = "CLAIM_SIGNING_REQUEST_DIGEST_MISSING"
    CLAIM_SIGNING_REQUEST_DIGEST_MISMATCH = "CLAIM_SIGNING_REQUEST_DIGEST_MISMATCH"

    SIGNING_REQUEST_AUTHORIZATION_ID_MISMATCH = "SIGNING_REQUEST_AUTHORIZATION_ID_MISMATCH"
    SIGNING_REQUEST_OPERATION_ID_MISMATCH = "SIGNING_REQUEST_OPERATION_ID_MISMATCH"
    SIGNING_REQUEST_KEY_REF_MISMATCH = "SIGNING_REQUEST_KEY_REF_MISMATCH"
    SIGNING_REQUEST_SIGNATURE_NAMESPACE_MISMATCH = "SIGNING_REQUEST_SIGNATURE_NAMESPACE_MISMATCH"
    SIGNING_REQUEST_CANONICALIZATION_ID_MISMATCH = "SIGNING_REQUEST_CANONICALIZATION_ID_MISMATCH"
    SIGNING_REQUEST_PAYLOAD_DIGEST_MISMATCH = "SIGNING_REQUEST_PAYLOAD_DIGEST_MISMATCH"
    SIGNING_REQUEST_RESULT_AUDIENCE_MISMATCH = "SIGNING_REQUEST_RESULT_AUDIENCE_MISMATCH"
    SIGNING_REQUEST_CONTEXT_DIGEST_MISMATCH = "SIGNING_REQUEST_CONTEXT_DIGEST_MISMATCH"
    SIGNING_REQUEST_CHAIN_FINGERPRINT_MISMATCH = "SIGNING_REQUEST_CHAIN_FINGERPRINT_MISMATCH"
    SIGNING_REQUEST_ISSUED_BEFORE_AUTHORIZATION = "SIGNING_REQUEST_ISSUED_BEFORE_AUTHORIZATION"
    SIGNING_REQUEST_EXCEEDS_AUTHORIZATION = "SIGNING_REQUEST_EXCEEDS_AUTHORIZATION"
    SIGNING_REQUEST_NOT_YET_VALID = "SIGNING_REQUEST_NOT_YET_VALID"
    SIGNING_REQUEST_EXPIRED = "SIGNING_REQUEST_EXPIRED"

    SIGNING_RESULT_AUTHORIZATION_ID_MISMATCH = "SIGNING_RESULT_AUTHORIZATION_ID_MISMATCH"
    SIGNING_RESULT_OPERATION_ID_MISMATCH = "SIGNING_RESULT_OPERATION_ID_MISMATCH"
    SIGNING_RESULT_KEY_REF_MISMATCH = "SIGNING_RESULT_KEY_REF_MISMATCH"
    SIGNING_RESULT_SIGNATURE_NAMESPACE_MISMATCH = "SIGNING_RESULT_SIGNATURE_NAMESPACE_MISMATCH"
    SIGNING_RESULT_PAYLOAD_DIGEST_MISMATCH = "SIGNING_RESULT_PAYLOAD_DIGEST_MISMATCH"
    SIGNATURE_NOT_VERIFIED = "SIGNATURE_NOT_VERIFIED"
    SIGNATURE_COMPLETED_TOO_LATE = "SIGNATURE_COMPLETED_TOO_LATE"
    SIGNER_NOT_REAPED = "SIGNER_NOT_REAPED"
    CUSTODY_POSTCONDITIONS_NOT_VERIFIED = "CUSTODY_POSTCONDITIONS_NOT_VERIFIED"
    EVIDENCE_NOT_SEALED = "EVIDENCE_NOT_SEALED"
    CLAIM_NOT_TERMINAL = "CLAIM_NOT_TERMINAL"
    CLAIM_NOT_SPENT_CLEAN = "CLAIM_NOT_SPENT_CLEAN"


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


def _decision(reasons: list[CustodyValidationReason]) -> CustodyValidationDecision:
    return CustodyValidationDecision(reasons=tuple(dict.fromkeys(reasons)))


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

    return _decision(reasons)


def validate_replay_preflight(
    *,
    envelope: AuthorizationEnvelope,
    claim: ReplayClaim,
    expected_context_digest: str,
) -> CustodyValidationDecision:
    """Validate the reversible single-use reservation before key-use intent.

    A passing result only confirms that the reservation is the expected,
    unspent SINGLE_USE claim for this envelope and context. It never authorizes
    a key and performs no claim transition.
    """

    reasons: list[CustodyValidationReason] = []

    if not _is_sha256_hex(expected_context_digest):
        reasons.append(CustodyValidationReason.INVALID_EXPECTED_CONTEXT_DIGEST)

    if envelope.replay_policy is not ReplayPolicy.SINGLE_USE:
        reasons.append(CustodyValidationReason.REPLAY_POLICY_MISMATCH)
    if claim.authorization_id != envelope.authorization_id:
        reasons.append(CustodyValidationReason.CLAIM_AUTHORIZATION_ID_MISMATCH)
    if claim.operation_id != envelope.operation_id:
        reasons.append(CustodyValidationReason.CLAIM_OPERATION_ID_MISMATCH)
    if claim.context_digest != expected_context_digest:
        reasons.append(CustodyValidationReason.CLAIM_CONTEXT_DIGEST_MISMATCH)
    if claim.state is not ReplayClaimState.RESOURCES_RESERVED:
        reasons.append(CustodyValidationReason.CLAIM_NOT_RESERVED)

    return _decision(reasons)


def verify_signing_request(
    *,
    envelope: AuthorizationEnvelope,
    signing_request: SigningRequest,
    claim: ReplayClaim,
    governed_epoch_seconds: int,
    expected_final_payload_digest: str,
    expected_context_digest: str,
    expected_chain_fingerprint: str,
) -> CustodyValidationDecision:
    """Verify a signing request against its authorization and durable claim.

    The request itself is not authority. A passing result requires a durable
    ``KEY_USE_CLAIMED`` replay claim bound to the exact request digest. Even
    then, this pure verifier does not authorize or perform key use.
    """

    reasons: list[CustodyValidationReason] = []

    if not _is_exact_nonnegative_int(governed_epoch_seconds):
        reasons.append(CustodyValidationReason.INVALID_GOVERNED_TIME)
    if not _is_sha256_hex(expected_final_payload_digest):
        reasons.append(CustodyValidationReason.INVALID_EXPECTED_PAYLOAD_DIGEST)
    if not _is_sha256_hex(expected_context_digest):
        reasons.append(CustodyValidationReason.INVALID_EXPECTED_CONTEXT_DIGEST)
    if not _is_sha256_hex(expected_chain_fingerprint):
        reasons.append(CustodyValidationReason.INVALID_EXPECTED_CHAIN_FINGERPRINT)

    if envelope.replay_policy is not ReplayPolicy.SINGLE_USE:
        reasons.append(CustodyValidationReason.REPLAY_POLICY_MISMATCH)

    if signing_request.authorization_id != envelope.authorization_id:
        reasons.append(CustodyValidationReason.SIGNING_REQUEST_AUTHORIZATION_ID_MISMATCH)
    if signing_request.operation_id != envelope.operation_id:
        reasons.append(CustodyValidationReason.SIGNING_REQUEST_OPERATION_ID_MISMATCH)
    if signing_request.key_ref != envelope.key_ref:
        reasons.append(CustodyValidationReason.SIGNING_REQUEST_KEY_REF_MISMATCH)
    if signing_request.signature_namespace != envelope.signature_namespace:
        reasons.append(CustodyValidationReason.SIGNING_REQUEST_SIGNATURE_NAMESPACE_MISMATCH)
    if signing_request.canonicalization_id != envelope.payload_template.canonicalization_id:
        reasons.append(CustodyValidationReason.SIGNING_REQUEST_CANONICALIZATION_ID_MISMATCH)
    if signing_request.final_payload_digest != expected_final_payload_digest:
        reasons.append(CustodyValidationReason.SIGNING_REQUEST_PAYLOAD_DIGEST_MISMATCH)
    if signing_request.result_audience != envelope.result_audience:
        reasons.append(CustodyValidationReason.SIGNING_REQUEST_RESULT_AUDIENCE_MISMATCH)
    if signing_request.context_digest != expected_context_digest:
        reasons.append(CustodyValidationReason.SIGNING_REQUEST_CONTEXT_DIGEST_MISMATCH)
    if signing_request.chain_fingerprint != expected_chain_fingerprint:
        reasons.append(CustodyValidationReason.SIGNING_REQUEST_CHAIN_FINGERPRINT_MISMATCH)

    if signing_request.issued_at_epoch_seconds < envelope.not_before_epoch_seconds:
        reasons.append(CustodyValidationReason.SIGNING_REQUEST_ISSUED_BEFORE_AUTHORIZATION)
    if signing_request.not_after_epoch_seconds > envelope.expires_at_epoch_seconds:
        reasons.append(CustodyValidationReason.SIGNING_REQUEST_EXCEEDS_AUTHORIZATION)

    if _is_exact_nonnegative_int(governed_epoch_seconds):
        if governed_epoch_seconds < signing_request.issued_at_epoch_seconds:
            reasons.append(CustodyValidationReason.SIGNING_REQUEST_NOT_YET_VALID)
        if governed_epoch_seconds > signing_request.not_after_epoch_seconds:
            reasons.append(CustodyValidationReason.SIGNING_REQUEST_EXPIRED)

    if claim.authorization_id != signing_request.authorization_id:
        reasons.append(CustodyValidationReason.CLAIM_AUTHORIZATION_ID_MISMATCH)
    if claim.operation_id != signing_request.operation_id:
        reasons.append(CustodyValidationReason.CLAIM_OPERATION_ID_MISMATCH)
    if claim.context_digest != signing_request.context_digest:
        reasons.append(CustodyValidationReason.CLAIM_CONTEXT_DIGEST_MISMATCH)
    if claim.state is not ReplayClaimState.KEY_USE_CLAIMED:
        reasons.append(CustodyValidationReason.CLAIM_NOT_KEY_USE_CLAIMED)
    if not claim.key_use_intent_durable:
        reasons.append(CustodyValidationReason.CLAIM_KEY_USE_INTENT_NOT_DURABLE)
    if claim.signing_request_digest is None:
        reasons.append(CustodyValidationReason.CLAIM_SIGNING_REQUEST_DIGEST_MISSING)
    elif claim.signing_request_digest != signing_request.digest():
        reasons.append(CustodyValidationReason.CLAIM_SIGNING_REQUEST_DIGEST_MISMATCH)

    return _decision(reasons)


def validate_post_signing_release(
    *,
    signing_request: SigningRequest,
    signing_result: SigningResult,
    claim: ReplayClaim,
) -> CustodyValidationDecision:
    """Validate post-signing release facts without releasing or mutating state.

    ``SigningResult`` supplies facts observed by the trusted runtime. The
    authoritative replay record must already be terminal ``SPENT_CLEAN`` and
    must retain the exact digest of ``signing_request``. This function performs
    no signing, no key access, no replay transition and no I/O.
    """

    reasons: list[CustodyValidationReason] = []

    if signing_result.authorization_id != signing_request.authorization_id:
        reasons.append(CustodyValidationReason.SIGNING_RESULT_AUTHORIZATION_ID_MISMATCH)
    if signing_result.operation_id != signing_request.operation_id:
        reasons.append(CustodyValidationReason.SIGNING_RESULT_OPERATION_ID_MISMATCH)
    if signing_result.key_ref != signing_request.key_ref:
        reasons.append(CustodyValidationReason.SIGNING_RESULT_KEY_REF_MISMATCH)
    if signing_result.signature_namespace != signing_request.signature_namespace:
        reasons.append(CustodyValidationReason.SIGNING_RESULT_SIGNATURE_NAMESPACE_MISMATCH)
    if signing_result.final_payload_digest != signing_request.final_payload_digest:
        reasons.append(CustodyValidationReason.SIGNING_RESULT_PAYLOAD_DIGEST_MISMATCH)

    if not signing_result.signature_verified:
        reasons.append(CustodyValidationReason.SIGNATURE_NOT_VERIFIED)
    if (
        signing_result.elapsed_at_signature_completion_seconds
        >= signing_request.not_after_epoch_seconds
    ):
        reasons.append(CustodyValidationReason.SIGNATURE_COMPLETED_TOO_LATE)
    if not signing_result.signer_reaped:
        reasons.append(CustodyValidationReason.SIGNER_NOT_REAPED)
    if not signing_result.custody_postconditions_verified:
        reasons.append(CustodyValidationReason.CUSTODY_POSTCONDITIONS_NOT_VERIFIED)
    if not signing_result.evidence_sealed:
        reasons.append(CustodyValidationReason.EVIDENCE_NOT_SEALED)

    if claim.authorization_id != signing_request.authorization_id:
        reasons.append(CustodyValidationReason.CLAIM_AUTHORIZATION_ID_MISMATCH)
    if claim.operation_id != signing_request.operation_id:
        reasons.append(CustodyValidationReason.CLAIM_OPERATION_ID_MISMATCH)
    if claim.context_digest != signing_request.context_digest:
        reasons.append(CustodyValidationReason.CLAIM_CONTEXT_DIGEST_MISMATCH)
    if not claim.is_terminal:
        reasons.append(CustodyValidationReason.CLAIM_NOT_TERMINAL)
    if claim.state is not ReplayClaimState.SPENT_CLEAN:
        reasons.append(CustodyValidationReason.CLAIM_NOT_SPENT_CLEAN)
    if not claim.key_use_intent_durable:
        reasons.append(CustodyValidationReason.CLAIM_KEY_USE_INTENT_NOT_DURABLE)
    if claim.signing_request_digest is None:
        reasons.append(CustodyValidationReason.CLAIM_SIGNING_REQUEST_DIGEST_MISSING)
    elif claim.signing_request_digest != signing_request.digest():
        reasons.append(CustodyValidationReason.CLAIM_SIGNING_REQUEST_DIGEST_MISMATCH)

    return _decision(reasons)
