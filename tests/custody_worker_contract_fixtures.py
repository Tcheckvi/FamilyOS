"""Synthetic fixtures for the Phase-1 custody worker contract tests.

All content is synthetic. No real names, keys, fingerprints, paths, custody objects or family data
appear in this file.
"""

from __future__ import annotations

from typing import Any

from familyos_pilot0 import custody_worker_contracts as contracts
from familyos_pilot0.custody_worker_contracts import (
    ENVELOPE_SCHEMA_VERSION,
    RD01_RECEIPT_CANONICALIZATION,
    RD01_RECEIPT_CANONICALIZATION_ID,
    RD01_RECEIPT_VERSION_VALUE,
    RD01_SIGNATURE_NAMESPACE,
    ActorKind,
    ApprovalFactor,
    ApproverBinding,
    ApproverEvidence,
    AuthorizationEnvelope,
    HumanPresenceRequirement,
    KeyPurposeClass,
    KeyRef,
    PayloadFieldKind,
    PayloadFieldSpec,
    PayloadTemplateCommitment,
    ReplayClaim,
    ReplayClaimState,
    ReplayPolicy,
    RevocationStatus,
    TrustAnchorRecord,
)

NOW = 2_000_000_000
SCOPE = "a" * 64
FINGERPRINT = "SHA256:" + "A" * 43


def make_key_ref(**overrides: Any) -> KeyRef:
    values: dict[str, Any] = {
        "key_id": "rd01-human-key",
        "key_version": 1,
        "key_fingerprint": FINGERPRINT,
        "key_purpose_class": KeyPurposeClass.HUMAN_DECISION,
        "algorithm_profile": "ssh-ed25519",
        "backend_id": "agentless-openssh-signer-v1",
    }
    values.update(overrides)
    return KeyRef(**values)


def make_fields(**static_overrides: str) -> tuple[PayloadFieldSpec, ...]:
    static = {
        "version": RD01_RECEIPT_VERSION_VALUE,
        "purpose": RD01_SIGNATURE_NAMESPACE,
        "verifier_identifier": "verifier-rd01-synthetic",
        "subject_identifier": "approver-alex-synthetic",
        "scope_fingerprint": SCOPE,
        "decision_reference": "human-decision-phase1-option1",
        "integrity_proof_identifier": "integrity-proof-rd01-synthetic",
    }
    static.update(static_overrides)
    rules = contracts.PayloadDerivationRule
    dynamic = {
        "receipt_identifier": rules.RECEIPT_IDENTIFIER_FROM_AUTHORIZATION_AND_OPERATION,
        "issued_at_epoch_seconds": rules.ISSUED_AT_FROM_GOVERNED_TIME,
        "expires_at_epoch_seconds": rules.EXPIRES_AT_FROM_ISSUED_AT_PLUS_TTL,
    }
    fields: list[PayloadFieldSpec] = []
    for name in RD01_RECEIPT_CANONICALIZATION.field_order:
        if name in dynamic:
            fields.append(
                PayloadFieldSpec(
                    name=name,
                    kind=PayloadFieldKind.DYNAMIC_DERIVED,
                    derivation=dynamic[name],
                )
            )
        else:
            fields.append(
                PayloadFieldSpec(
                    name=name,
                    kind=PayloadFieldKind.STATIC_BOUND,
                    static_value=static[name],
                )
            )
    return tuple(fields)


def make_template(
    *, ttl: int = 300, fields: tuple[PayloadFieldSpec, ...] | None = None
) -> PayloadTemplateCommitment:
    return PayloadTemplateCommitment.build(
        canonicalization_id=RD01_RECEIPT_CANONICALIZATION_ID,
        schema_version=RD01_RECEIPT_CANONICALIZATION.schema_version,
        fields=make_fields() if fields is None else fields,
        authorization_fixed_ttl_seconds=ttl,
    )


def make_envelope(**overrides: Any) -> AuthorizationEnvelope:
    values: dict[str, Any] = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "authorization_id": "auth-rd01-0001",
        "operation_id": "op-rd01-0001",
        "issuer_ref": "issuer-governed-human-record",
        "verifier_ref": "verifier-rd01-human",
        "issuer_trust_version": "v1",
        "issuance_record_digest": "c" * 64,
        "issued_at_epoch_seconds": NOW - 1_000,
        "not_before_epoch_seconds": NOW - 900,
        "expires_at_epoch_seconds": NOW + 3_600,
        "actor_ref": "actor-familyos-app",
        "actor_kind": ActorKind.SYSTEM,
        "represented_actor_ref": None,
        "eligible_approver_refs": ("approver-alex-synthetic",),
        "upstream_approval_challenge": "d" * 32,
        "family_or_security_domain": "family-synthetic",
        "capability_id": "custody.sign.rd01_receipt",
        "capability_version": "v1",
        "action": "sign",
        "resource_ref": "m10/wave-a/rd01",
        "scope_fingerprint": SCOPE,
        "audience_custody_profile": "custody-worker-phase1",
        "result_audience": "familyos-pilot0-verifier",
        "key_ref": make_key_ref(),
        "signature_namespace": RD01_SIGNATURE_NAMESPACE,
        "human_presence_requirement": HumanPresenceRequirement.HUMAN_PRESENT_LOCAL,
        "payload_template": make_template(),
        "replay_policy": ReplayPolicy.SINGLE_USE,
        "policy_version": "policy-v1",
        "revocation_handle": "revocation-handle-0001",
        "delegation_chain": (),
    }
    values.update(overrides)
    return AuthorizationEnvelope(**values)


def make_anchor(envelope: AuthorizationEnvelope, **overrides: Any) -> TrustAnchorRecord:
    values: dict[str, Any] = {
        "authorization_id": envelope.authorization_id,
        "issuer_ref": envelope.issuer_ref,
        "verifier_ref": envelope.verifier_ref,
        "record_version": envelope.issuer_trust_version,
        "pinned_issuance_record_digest": envelope.issuance_record_digest,
        "pinned_envelope_digest": envelope.digest(),
        "valid_from_epoch_seconds": NOW - 1_000,
        "valid_until_epoch_seconds": NOW + 7_200,
        "revocation_status": RevocationStatus.ACTIVE,
        "supersedes": (),
        "superseded_by": None,
        "allowed_authorization_classes": (KeyPurposeClass.HUMAN_DECISION,),
        "approver_bindings": (
            ApproverBinding(
                approver_ref="approver-alex-synthetic",
                custody_account_id="custody-account-rd01",
                key_ref=envelope.key_ref,
            ),
        ),
    }
    values.update(overrides)
    return TrustAnchorRecord(**values)


def make_evidence(**overrides: Any) -> ApproverEvidence:
    values: dict[str, Any] = {
        "requester_ref": "actor-familyos-app",
        "represented_actor_ref": None,
        "approver_ref": "approver-alex-synthetic",
        "presenter_ref": "approver-alex-synthetic",
        "authorization_id": "auth-rd01-0001",
        "operation_id": "op-rd01-0001",
        "final_payload_digest": "e" * 64,
        "worker_challenge": "f" * 32,
        "approval_offset_seconds": 20,
        "human_presence_profile": HumanPresenceRequirement.HUMAN_PRESENT_LOCAL,
        "custody_account_id": "custody-account-rd01",
        "factors": (
            ApprovalFactor.CUSTODY_SESSION_LOGIN,
            ApprovalFactor.KEY_UNLOCK,
            ApprovalFactor.LOCAL_CONFIRMATION,
            ApprovalFactor.WORKER_CHALLENGE,
        ),
    }
    values.update(overrides)
    return ApproverEvidence(**values)


def make_claim(state: ReplayClaimState, **overrides: Any) -> ReplayClaim:
    intent = state in {
        ReplayClaimState.KEY_USE_CLAIMED,
        ReplayClaimState.SPENT_CLEAN,
        ReplayClaimState.SPENT_UNKNOWN,
        ReplayClaimState.QUARANTINED,
    }
    values: dict[str, Any] = {
        "authorization_id": "auth-rd01-0001",
        "operation_id": "op-rd01-0001",
        "claim_generation": 0,
        "state": state,
        "non_key_resources_consumed": ("rfc3161-slot",),
        "key_use_intent_durable": intent,
        "context_digest": "9" * 64,
        "signing_request_digest": (
            "8" * 64
            if state in {ReplayClaimState.KEY_USE_CLAIMED, ReplayClaimState.SPENT_CLEAN}
            else None
        ),
    }
    values.update(overrides)
    return ReplayClaim(**values)
