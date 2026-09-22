"""Tests for pure F05 Phase-1 custody worker validation."""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

from familyos_pilot0.custody_worker_contracts import (
    RD01_RECEIPT_CANONICALIZATION_ID,
    ApproverEvidence,
    AuthorizationEnvelope,
    ReplayClaim,
    ReplayClaimState,
    ReplayPolicy,
    RevocationStatus,
    SigningRequest,
    SigningResult,
    TrustAnchorRecord,
)
from familyos_pilot0.custody_worker_validation import (
    CustodyValidationDecision,
    CustodyValidationReason,
    validate_custody_worker_context,
    validate_post_signing_release,
    validate_replay_preflight,
    verify_signing_request,
)
from tests.custody_worker_contract_fixtures import (
    make_anchor,
    make_claim,
    make_envelope,
    make_evidence,
)

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "familyos_pilot0"


def _aligned_context() -> tuple[AuthorizationEnvelope, TrustAnchorRecord, ApproverEvidence]:
    envelope = make_envelope()
    anchor = make_anchor(envelope)
    approver_ref = envelope.eligible_approver_refs[0]
    binding = anchor.binding_for(approver_ref)
    assert binding is not None

    evidence = make_evidence(
        requester_ref=envelope.actor_ref,
        represented_actor_ref=envelope.represented_actor_ref,
        approver_ref=approver_ref,
        authorization_id=envelope.authorization_id,
        operation_id=envelope.operation_id,
        human_presence_profile=envelope.human_presence_requirement,
        custody_account_id=binding.custody_account_id,
    )
    return envelope, anchor, evidence


def _validate(
    envelope: AuthorizationEnvelope,
    anchor: TrustAnchorRecord,
    evidence: ApproverEvidence,
) -> CustodyValidationDecision:
    return validate_custody_worker_context(
        envelope=envelope,
        trust_anchor=anchor,
        approver_evidence=evidence,
        governed_epoch_seconds=max(
            envelope.not_before_epoch_seconds,
            anchor.valid_from_epoch_seconds,
        ),
        expected_final_payload_digest=evidence.final_payload_digest,
        expected_worker_challenge=evidence.worker_challenge,
    )


def _make_signing_request(
    envelope: AuthorizationEnvelope,
    evidence: ApproverEvidence,
    *,
    context_digest: str = "7" * 64,
    chain_fingerprint: str = "8" * 64,
    issued_at_epoch_seconds: int | None = None,
    not_after_epoch_seconds: int | None = None,
) -> SigningRequest:
    issued_at = (
        envelope.not_before_epoch_seconds
        if issued_at_epoch_seconds is None
        else issued_at_epoch_seconds
    )
    not_after = (
        min(envelope.expires_at_epoch_seconds, issued_at + 51)
        if not_after_epoch_seconds is None
        else not_after_epoch_seconds
    )
    return SigningRequest(
        authorization_id=envelope.authorization_id,
        operation_id=envelope.operation_id,
        key_ref=envelope.key_ref,
        signature_namespace=envelope.signature_namespace,
        canonicalization_id=RD01_RECEIPT_CANONICALIZATION_ID,
        final_payload_digest=evidence.final_payload_digest,
        payload_length=300,
        result_audience=envelope.result_audience,
        context_digest=context_digest,
        chain_fingerprint=chain_fingerprint,
        issued_at_epoch_seconds=issued_at,
        not_after_epoch_seconds=not_after,
    )


def _make_signing_result(
    request: SigningRequest,
    *,
    signature_verified: bool = True,
    completion_seconds: int | None = None,
    signer_reaped: bool = True,
    custody_postconditions_verified: bool = True,
    evidence_sealed: bool = True,
) -> SigningResult:
    return SigningResult(
        authorization_id=request.authorization_id,
        operation_id=request.operation_id,
        key_ref=request.key_ref,
        signature_namespace=request.signature_namespace,
        final_payload_digest=request.final_payload_digest,
        signature_sha256="9" * 64,
        signature_verified=signature_verified,
        elapsed_at_signature_completion_seconds=(
            request.not_after_epoch_seconds - 1
            if completion_seconds is None
            else completion_seconds
        ),
        signer_reaped=signer_reaped,
        custody_postconditions_verified=custody_postconditions_verified,
        evidence_sealed=evidence_sealed,
    )


def _claimed_replay(
    request: SigningRequest,
    *,
    signing_request_digest: str | None = None,
) -> ReplayClaim:
    return make_claim(
        ReplayClaimState.KEY_USE_CLAIMED,
        authorization_id=request.authorization_id,
        operation_id=request.operation_id,
        context_digest=request.context_digest,
        signing_request_digest=(
            request.digest() if signing_request_digest is None else signing_request_digest
        ),
    )


def test_valid_context_passes_but_never_authorizes_key_use() -> None:
    envelope, anchor, evidence = _aligned_context()

    decision = _validate(envelope, anchor, evidence)

    assert decision.validation_passed is True
    assert decision.reasons == ()
    assert decision.key_use_authorized is False


def test_decision_type_has_no_mutable_key_authorization_field() -> None:
    decision = CustodyValidationDecision(())

    assert tuple(decision.__dataclass_fields__) == ("reasons",)
    assert decision.key_use_authorized is False


def test_anchor_binding_and_revocation_fail_closed() -> None:
    envelope, anchor, evidence = _aligned_context()

    wrong_digest = replace(anchor, pinned_envelope_digest="f" * 64)
    digest_decision = _validate(envelope, wrong_digest, evidence)
    assert CustodyValidationReason.ENVELOPE_DIGEST_MISMATCH in digest_decision.reasons
    assert digest_decision.key_use_authorized is False

    revoked = replace(anchor, revocation_status=RevocationStatus.REVOKED)
    revoked_decision = _validate(envelope, revoked, evidence)
    assert CustodyValidationReason.TRUST_ANCHOR_REVOKED in revoked_decision.reasons
    assert revoked_decision.key_use_authorized is False


def test_authorization_time_window_fails_closed() -> None:
    envelope, anchor, evidence = _aligned_context()

    decision = validate_custody_worker_context(
        envelope=envelope,
        trust_anchor=anchor,
        approver_evidence=evidence,
        governed_epoch_seconds=envelope.expires_at_epoch_seconds + 1,
        expected_final_payload_digest=evidence.final_payload_digest,
        expected_worker_challenge=evidence.worker_challenge,
    )

    assert CustodyValidationReason.AUTHORIZATION_EXPIRED in decision.reasons
    assert decision.validation_passed is False
    assert decision.key_use_authorized is False


def test_payload_digest_and_worker_challenge_are_bound() -> None:
    envelope, anchor, evidence = _aligned_context()

    decision = validate_custody_worker_context(
        envelope=envelope,
        trust_anchor=anchor,
        approver_evidence=evidence,
        governed_epoch_seconds=max(
            envelope.not_before_epoch_seconds,
            anchor.valid_from_epoch_seconds,
        ),
        expected_final_payload_digest="0" * 64,
        expected_worker_challenge="1" * 32,
    )

    assert CustodyValidationReason.PAYLOAD_DIGEST_MISMATCH in decision.reasons
    assert CustodyValidationReason.WORKER_CHALLENGE_MISMATCH in decision.reasons
    assert decision.key_use_authorized is False


def test_malformed_governed_inputs_fail_closed_without_io() -> None:
    envelope, anchor, evidence = _aligned_context()

    decision = validate_custody_worker_context(
        envelope=envelope,
        trust_anchor=anchor,
        approver_evidence=evidence,
        governed_epoch_seconds=True,
        expected_final_payload_digest="not-a-digest",
        expected_worker_challenge="short",
    )

    assert decision.reasons[:3] == (
        CustodyValidationReason.INVALID_GOVERNED_TIME,
        CustodyValidationReason.INVALID_EXPECTED_PAYLOAD_DIGEST,
        CustodyValidationReason.INVALID_EXPECTED_WORKER_CHALLENGE,
    )
    assert decision.key_use_authorized is False


def test_requester_and_approver_bindings_fail_closed() -> None:
    envelope, anchor, evidence = _aligned_context()

    altered = replace(
        evidence,
        requester_ref="requester-other",
        approver_ref="approver-other",
    )
    decision = _validate(envelope, anchor, altered)

    assert CustodyValidationReason.REQUESTER_MISMATCH in decision.reasons
    assert CustodyValidationReason.APPROVER_NOT_ELIGIBLE in decision.reasons
    assert CustodyValidationReason.APPROVER_NOT_ANCHORED in decision.reasons
    assert decision.key_use_authorized is False


def test_replay_preflight_accepts_only_reserved_single_use_claim() -> None:
    envelope, _, _ = _aligned_context()
    context_digest = "7" * 64
    claim = make_claim(
        ReplayClaimState.RESOURCES_RESERVED,
        authorization_id=envelope.authorization_id,
        operation_id=envelope.operation_id,
        context_digest=context_digest,
    )

    decision = validate_replay_preflight(
        envelope=envelope,
        claim=claim,
        expected_context_digest=context_digest,
    )

    assert decision.validation_passed is True
    assert decision.reasons == ()
    assert decision.key_use_authorized is False


def test_replay_preflight_rejects_consumed_or_wrong_context_claim() -> None:
    envelope, _, _ = _aligned_context()
    claim = make_claim(
        ReplayClaimState.NO_KEY_USE,
        authorization_id=envelope.authorization_id,
        operation_id=envelope.operation_id,
        context_digest="6" * 64,
    )

    decision = validate_replay_preflight(
        envelope=envelope,
        claim=claim,
        expected_context_digest="7" * 64,
    )

    assert CustodyValidationReason.CLAIM_CONTEXT_DIGEST_MISMATCH in decision.reasons
    assert CustodyValidationReason.CLAIM_NOT_RESERVED in decision.reasons
    assert decision.key_use_authorized is False


def test_replay_preflight_requires_single_use_policy() -> None:
    envelope, _, _ = _aligned_context()
    envelope = replace(envelope, replay_policy=ReplayPolicy.BOUNDED)
    claim = make_claim(
        ReplayClaimState.RESOURCES_RESERVED,
        authorization_id=envelope.authorization_id,
        operation_id=envelope.operation_id,
        context_digest="7" * 64,
    )

    decision = validate_replay_preflight(
        envelope=envelope,
        claim=claim,
        expected_context_digest="7" * 64,
    )

    assert CustodyValidationReason.REPLAY_POLICY_MISMATCH in decision.reasons
    assert decision.key_use_authorized is False


def test_verify_signing_request_requires_exact_durable_claim_binding() -> None:
    envelope, _, evidence = _aligned_context()
    request = _make_signing_request(envelope, evidence)
    claim = _claimed_replay(request)

    decision = verify_signing_request(
        envelope=envelope,
        signing_request=request,
        claim=claim,
        governed_epoch_seconds=request.issued_at_epoch_seconds,
        expected_final_payload_digest=evidence.final_payload_digest,
        expected_context_digest=request.context_digest,
        expected_chain_fingerprint=request.chain_fingerprint,
    )

    assert decision.validation_passed is True
    assert decision.reasons == ()
    assert decision.key_use_authorized is False


def test_verify_signing_request_rejects_request_field_mismatches() -> None:
    envelope, _, evidence = _aligned_context()
    request = _make_signing_request(envelope, evidence)
    altered = replace(
        request,
        result_audience="other-audience",
        chain_fingerprint="5" * 64,
    )
    claim = _claimed_replay(altered)

    decision = verify_signing_request(
        envelope=envelope,
        signing_request=altered,
        claim=claim,
        governed_epoch_seconds=altered.issued_at_epoch_seconds,
        expected_final_payload_digest=evidence.final_payload_digest,
        expected_context_digest=altered.context_digest,
        expected_chain_fingerprint="8" * 64,
    )

    assert CustodyValidationReason.SIGNING_REQUEST_RESULT_AUDIENCE_MISMATCH in decision.reasons
    assert CustodyValidationReason.SIGNING_REQUEST_CHAIN_FINGERPRINT_MISMATCH in decision.reasons
    assert decision.key_use_authorized is False


def test_verify_signing_request_rejects_wrong_recorded_request_digest() -> None:
    envelope, _, evidence = _aligned_context()
    request = _make_signing_request(envelope, evidence)
    claim = _claimed_replay(request, signing_request_digest="6" * 64)

    decision = verify_signing_request(
        envelope=envelope,
        signing_request=request,
        claim=claim,
        governed_epoch_seconds=request.issued_at_epoch_seconds,
        expected_final_payload_digest=evidence.final_payload_digest,
        expected_context_digest=request.context_digest,
        expected_chain_fingerprint=request.chain_fingerprint,
    )

    assert CustodyValidationReason.CLAIM_SIGNING_REQUEST_DIGEST_MISMATCH in decision.reasons
    assert decision.key_use_authorized is False


def test_verify_signing_request_rejects_unclaimed_replay_state() -> None:
    envelope, _, evidence = _aligned_context()
    request = _make_signing_request(envelope, evidence)
    claim = make_claim(
        ReplayClaimState.RESOURCES_RESERVED,
        authorization_id=request.authorization_id,
        operation_id=request.operation_id,
        context_digest=request.context_digest,
    )

    decision = verify_signing_request(
        envelope=envelope,
        signing_request=request,
        claim=claim,
        governed_epoch_seconds=request.issued_at_epoch_seconds,
        expected_final_payload_digest=evidence.final_payload_digest,
        expected_context_digest=request.context_digest,
        expected_chain_fingerprint=request.chain_fingerprint,
    )

    assert CustodyValidationReason.CLAIM_NOT_KEY_USE_CLAIMED in decision.reasons
    assert CustodyValidationReason.CLAIM_KEY_USE_INTENT_NOT_DURABLE in decision.reasons
    assert CustodyValidationReason.CLAIM_SIGNING_REQUEST_DIGEST_MISSING in decision.reasons
    assert decision.key_use_authorized is False


def test_verify_signing_request_rejects_expired_request() -> None:
    envelope, _, evidence = _aligned_context()
    request = _make_signing_request(
        envelope,
        evidence,
        not_after_epoch_seconds=envelope.not_before_epoch_seconds + 10,
    )
    claim = _claimed_replay(request)

    decision = verify_signing_request(
        envelope=envelope,
        signing_request=request,
        claim=claim,
        governed_epoch_seconds=request.not_after_epoch_seconds + 1,
        expected_final_payload_digest=evidence.final_payload_digest,
        expected_context_digest=request.context_digest,
        expected_chain_fingerprint=request.chain_fingerprint,
    )

    assert CustodyValidationReason.SIGNING_REQUEST_EXPIRED in decision.reasons
    assert decision.key_use_authorized is False


def test_post_signing_release_accepts_exact_clean_terminal_result() -> None:
    envelope, _, evidence = _aligned_context()
    request = _make_signing_request(envelope, evidence)
    result = _make_signing_result(request)
    claim = make_claim(
        ReplayClaimState.SPENT_CLEAN,
        authorization_id=request.authorization_id,
        operation_id=request.operation_id,
        context_digest=request.context_digest,
        signing_request_digest=request.digest(),
    )

    decision = validate_post_signing_release(
        signing_request=request,
        signing_result=result,
        claim=claim,
    )

    assert decision.validation_passed is True
    assert decision.reasons == ()
    assert decision.key_use_authorized is False


def test_post_signing_release_rejects_result_binding_mismatch() -> None:
    envelope, _, evidence = _aligned_context()
    request = _make_signing_request(envelope, evidence)
    result = _make_signing_result(request)
    altered = replace(
        result,
        authorization_id="auth-rd01-other",
        final_payload_digest="5" * 64,
    )
    claim = make_claim(
        ReplayClaimState.SPENT_CLEAN,
        authorization_id=request.authorization_id,
        operation_id=request.operation_id,
        context_digest=request.context_digest,
        signing_request_digest=request.digest(),
    )

    decision = validate_post_signing_release(
        signing_request=request,
        signing_result=altered,
        claim=claim,
    )

    assert CustodyValidationReason.SIGNING_RESULT_AUTHORIZATION_ID_MISMATCH in decision.reasons
    assert CustodyValidationReason.SIGNING_RESULT_PAYLOAD_DIGEST_MISMATCH in decision.reasons
    assert decision.key_use_authorized is False


def test_post_signing_release_requires_all_runtime_postconditions() -> None:
    envelope, _, evidence = _aligned_context()
    request = _make_signing_request(envelope, evidence)
    result = _make_signing_result(
        request,
        signature_verified=False,
        signer_reaped=False,
        custody_postconditions_verified=False,
        evidence_sealed=False,
    )
    claim = make_claim(
        ReplayClaimState.SPENT_CLEAN,
        authorization_id=request.authorization_id,
        operation_id=request.operation_id,
        context_digest=request.context_digest,
        signing_request_digest=request.digest(),
    )

    decision = validate_post_signing_release(
        signing_request=request,
        signing_result=result,
        claim=claim,
    )

    assert CustodyValidationReason.SIGNATURE_NOT_VERIFIED in decision.reasons
    assert CustodyValidationReason.SIGNER_NOT_REAPED in decision.reasons
    assert CustodyValidationReason.CUSTODY_POSTCONDITIONS_NOT_VERIFIED in decision.reasons
    assert CustodyValidationReason.EVIDENCE_NOT_SEALED in decision.reasons
    assert decision.key_use_authorized is False


def test_post_signing_release_treats_not_after_as_exclusive() -> None:
    envelope, _, evidence = _aligned_context()
    request = _make_signing_request(envelope, evidence)
    result = _make_signing_result(
        request,
        completion_seconds=request.not_after_epoch_seconds,
    )
    claim = make_claim(
        ReplayClaimState.SPENT_CLEAN,
        authorization_id=request.authorization_id,
        operation_id=request.operation_id,
        context_digest=request.context_digest,
        signing_request_digest=request.digest(),
    )

    decision = validate_post_signing_release(
        signing_request=request,
        signing_result=result,
        claim=claim,
    )

    assert CustodyValidationReason.SIGNATURE_COMPLETED_TOO_LATE in decision.reasons
    assert decision.key_use_authorized is False


def test_post_signing_release_requires_authoritative_spent_clean_claim() -> None:
    envelope, _, evidence = _aligned_context()
    request = _make_signing_request(envelope, evidence)
    result = _make_signing_result(request)
    claim = make_claim(
        ReplayClaimState.SPENT_UNKNOWN,
        authorization_id=request.authorization_id,
        operation_id=request.operation_id,
        context_digest=request.context_digest,
    )

    decision = validate_post_signing_release(
        signing_request=request,
        signing_result=result,
        claim=claim,
    )

    assert CustodyValidationReason.CLAIM_NOT_SPENT_CLEAN in decision.reasons
    assert CustodyValidationReason.CLAIM_SIGNING_REQUEST_DIGEST_MISSING in decision.reasons
    assert CustodyValidationReason.CLAIM_NOT_TERMINAL not in decision.reasons
    assert decision.key_use_authorized is False


def test_post_signing_release_rejects_nonterminal_claim() -> None:
    envelope, _, evidence = _aligned_context()
    request = _make_signing_request(envelope, evidence)
    result = _make_signing_result(request)
    claim = make_claim(
        ReplayClaimState.KEY_USE_CLAIMED,
        authorization_id=request.authorization_id,
        operation_id=request.operation_id,
        context_digest=request.context_digest,
        signing_request_digest=request.digest(),
    )

    decision = validate_post_signing_release(
        signing_request=request,
        signing_result=result,
        claim=claim,
    )

    assert CustodyValidationReason.CLAIM_NOT_TERMINAL in decision.reasons
    assert CustodyValidationReason.CLAIM_NOT_SPENT_CLEAN in decision.reasons
    assert decision.key_use_authorized is False


def test_post_signing_release_requires_exact_recorded_request_digest() -> None:
    envelope, _, evidence = _aligned_context()
    request = _make_signing_request(envelope, evidence)
    result = _make_signing_result(request)
    claim = make_claim(
        ReplayClaimState.SPENT_CLEAN,
        authorization_id=request.authorization_id,
        operation_id=request.operation_id,
        context_digest=request.context_digest,
        signing_request_digest="6" * 64,
    )

    decision = validate_post_signing_release(
        signing_request=request,
        signing_result=result,
        claim=claim,
    )

    assert CustodyValidationReason.CLAIM_SIGNING_REQUEST_DIGEST_MISMATCH in decision.reasons
    assert decision.key_use_authorized is False


def test_validation_module_is_pure_and_has_no_transitional_imports() -> None:
    path = SRC_ROOT / "custody_worker_validation.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "real_data_wave_a" not in source
    assert "trust_source_bindings" not in source

    forbidden_import_roots = {
        "asyncio",
        "os",
        "pathlib",
        "socket",
        "subprocess",
        "tempfile",
        "urllib",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".", 1)[0] for alias in node.names}
            assert not (roots & forbidden_import_roots)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            assert node.module.split(".", 1)[0] not in forbidden_import_roots

    forbidden_calls = {"open", "exec", "eval", "compile", "__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in forbidden_calls
