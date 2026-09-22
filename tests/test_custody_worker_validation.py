"""Tests for pure F05 Phase-1 custody worker validation."""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

from familyos_pilot0.custody_worker_contracts import (
    ApproverEvidence,
    AuthorizationEnvelope,
    RevocationStatus,
    TrustAnchorRecord,
)
from familyos_pilot0.custody_worker_validation import (
    CustodyValidationDecision,
    CustodyValidationReason,
    validate_custody_worker_context,
)
from tests.custody_worker_contract_fixtures import (
    make_anchor,
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
