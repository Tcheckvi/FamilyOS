"""Tests for the Phase-1 custody worker contracts. Pure logic: no key, signer, agent, network."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from familyos_pilot0 import custody_worker_contracts as contracts
from familyos_pilot0.custody_worker_contracts import (
    PAYLOAD_CANONICALIZATIONS,
    RD01_RECEIPT_CANONICALIZATION,
    RD01_RECEIPT_CANONICALIZATION_ID,
    RD01_RECEIPT_VERSION_VALUE,
    RD01_SIGNATURE_NAMESPACE,
    ApprovalFactor,
    ApproverBinding,
    AuthorizationEnvelope,
    CustodyContractValidationError,
    HumanPresenceRequirement,
    KeyPurposeClass,
    PayloadFieldKind,
    PayloadFieldSpec,
    ReplayClaimState,
    SigningRequest,
    SigningResult,
    canonical_json_bytes,
    claim_state_after_durable_write_failure,
    loads_strict_json,
    recover_claim_after_restart,
    stricter_claim_state,
)
from tests.custody_worker_contract_fixtures import (
    FINGERPRINT,
    NOW,
    SCOPE,
    make_anchor,
    make_claim,
    make_envelope,
    make_evidence,
    make_fields,
    make_key_ref,
    make_template,
)

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "familyos_pilot0"
PURE_MODULES = ("custody_worker_contracts.py",)




def test_rd01_contract_constants_are_pinned_by_spec_0017_v1_1_0() -> None:
    assert RD01_RECEIPT_CANONICALIZATION_ID == "familyos-m10-wave-a-receipt-lines-v1"
    assert RD01_RECEIPT_CANONICALIZATION.schema_version == "familyos-m10-wave-a-rd01-receipt-v1"
    assert RD01_RECEIPT_VERSION_VALUE == "1"
    assert RD01_SIGNATURE_NAMESPACE == "familyos-m10-wave-a-human-authorization-v1"
    assert RD01_RECEIPT_CANONICALIZATION.field_order == (
        "version",
        "purpose",
        "receipt_identifier",
        "verifier_identifier",
        "subject_identifier",
        "scope_fingerprint",
        "issued_at_epoch_seconds",
        "expires_at_epoch_seconds",
        "decision_reference",
        "integrity_proof_identifier",
    )

def test_every_rd01_field_is_exactly_static_or_dynamic() -> None:
    kinds = {name: (kind, rule) for name, kind, rule in RD01_RECEIPT_CANONICALIZATION.field_rules}

    assert set(kinds) == set(RD01_RECEIPT_CANONICALIZATION.field_order)
    dynamic = {
        name for name, (kind, _) in kinds.items() if kind is PayloadFieldKind.DYNAMIC_DERIVED
    }
    assert dynamic == {"receipt_identifier", "issued_at_epoch_seconds", "expires_at_epoch_seconds"}
    assert all(
        (kind is PayloadFieldKind.DYNAMIC_DERIVED) == (rule is not None)
        for kind, rule in kinds.values()
    )
    assert (
        PAYLOAD_CANONICALIZATIONS[RD01_RECEIPT_CANONICALIZATION_ID] is RD01_RECEIPT_CANONICALIZATION
    )


def test_purity_modules_import_only_allowlisted_modules_and_call_no_io() -> None:
    allowed = {
        "__future__",
        "hashlib",
        "hmac",
        "json",
        "re",
        "collections.abc",
        "dataclasses",
        "enum",
        "types",
        "typing",
        "custody_worker_contracts",
    }
    forbidden_calls = {"open", "eval", "exec", "compile", "__import__", "input", "print"}
    for module_name in PURE_MODULES:
        tree = ast.parse((SRC_ROOT / module_name).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls, f"{module_name} calls {node.func.id}"
        assert imported <= allowed, f"{module_name} imports {sorted(imported - allowed)}"


def test_key_ref_never_carries_a_path_and_pins_a_fingerprint() -> None:
    for bad_key_id in ("/Users/x/key", "../key", "~/key", "a/b", ""):
        with pytest.raises(CustodyContractValidationError):
            make_key_ref(key_id=bad_key_id)
    for bad_fingerprint in (
        "SHA256:short",
        "MD5:" + "A" * 43,
        "sha256:" + "A" * 43,
        FINGERPRINT + "=",
    ):
        with pytest.raises(CustodyContractValidationError):
            make_key_ref(key_fingerprint=bad_fingerprint)
    with pytest.raises(CustodyContractValidationError):
        make_key_ref(key_version=0)
    with pytest.raises(CustodyContractValidationError):
        make_key_ref(key_version=True)
    with pytest.raises(CustodyContractValidationError):
        make_key_ref(key_purpose_class="HUMAN_DECISION")


def test_payload_field_is_exactly_static_xor_dynamic() -> None:
    with pytest.raises(CustodyContractValidationError):
        PayloadFieldSpec(name="x", kind=PayloadFieldKind.STATIC_BOUND)
    with pytest.raises(CustodyContractValidationError):
        PayloadFieldSpec(
            name="x",
            kind=PayloadFieldKind.STATIC_BOUND,
            static_value="v",
            derivation=contracts.PayloadDerivationRule.ISSUED_AT_FROM_GOVERNED_TIME,
        )
    with pytest.raises(CustodyContractValidationError):
        PayloadFieldSpec(name="x", kind=PayloadFieldKind.DYNAMIC_DERIVED)
    with pytest.raises(CustodyContractValidationError):
        PayloadFieldSpec(
            name="x",
            kind=PayloadFieldKind.DYNAMIC_DERIVED,
            static_value="v",
            derivation=contracts.PayloadDerivationRule.ISSUED_AT_FROM_GOVERNED_TIME,
        )
    with pytest.raises(CustodyContractValidationError):
        PayloadFieldSpec(name="Bad-Name", kind=PayloadFieldKind.STATIC_BOUND, static_value="v")
    with pytest.raises(CustodyContractValidationError):
        PayloadFieldSpec(name="x", kind=PayloadFieldKind.STATIC_BOUND, static_value="a\nb=c")


def test_template_commitment_binds_every_field_and_the_ttl() -> None:
    base = make_template()
    assert make_template().commitment_digest == base.commitment_digest
    assert make_template(ttl=301).commitment_digest != base.commitment_digest
    changed = make_fields(decision_reference="human-decision-other")
    assert make_template(fields=changed).commitment_digest != base.commitment_digest
    with pytest.raises(CustodyContractValidationError):
        replace(base, commitment_digest="0" * 64)
    with pytest.raises(CustodyContractValidationError):
        replace(base, authorization_fixed_ttl_seconds=301)
    duplicated = make_fields() + (make_fields()[0],)
    with pytest.raises(CustodyContractValidationError):
        make_template(fields=duplicated)


def test_envelope_round_trips_and_digest_is_deterministic() -> None:
    envelope = make_envelope()
    rebuilt = AuthorizationEnvelope.from_mapping(json.loads(json.dumps(envelope.to_document())))

    assert rebuilt == envelope
    assert AuthorizationEnvelope.from_json(envelope.canonical_bytes().decode("ascii")) == envelope
    assert rebuilt.digest() == envelope.digest()
    assert envelope.digest() == hashlib.sha256(envelope.canonical_bytes()).hexdigest()
    assert envelope.canonical_bytes() == canonical_json_bytes(envelope.to_document())
    assert make_envelope().digest() == envelope.digest()


@pytest.mark.parametrize(
    "override",
    [
        {"authorization_id": "auth-rd01-0002"},
        {"operation_id": "op-rd01-0002"},
        {"issuer_ref": "issuer-other"},
        {"scope_fingerprint": "b" * 64},
        {"expires_at_epoch_seconds": NOW + 3_601},
        {"eligible_approver_refs": ("approver-alex-synthetic", "approver-blake-synthetic")},
        {"human_presence_requirement": HumanPresenceRequirement.HUMAN_PRESENT_HARDWARE},
        {"key_ref": make_key_ref(key_version=2)},
        {"payload_template": make_template(ttl=301)},
        {"delegation_chain": ("delegation-1",)},
    ],
)
def test_envelope_digest_changes_with_any_bound_field(override: dict[str, Any]) -> None:
    assert make_envelope(**override).digest() != make_envelope().digest()


def test_envelope_parsing_is_strict_about_fields() -> None:
    document = make_envelope().to_document()

    unknown = {**document, "extra_field": "x"}
    with pytest.raises(CustodyContractValidationError):
        AuthorizationEnvelope.from_mapping(unknown)
    for name in list(document):
        missing = {key: value for key, value in document.items() if key != name}
        with pytest.raises(CustodyContractValidationError):
            AuthorizationEnvelope.from_mapping(missing)
    nested_unknown = json.loads(json.dumps(document))
    nested_unknown["key_ref"]["path"] = "/tmp/key"
    with pytest.raises(CustodyContractValidationError):
        AuthorizationEnvelope.from_mapping(nested_unknown)
    nested_field_unknown = json.loads(json.dumps(document))
    nested_field_unknown["payload_template"]["fields"][0]["extra"] = "x"
    with pytest.raises(CustodyContractValidationError):
        AuthorizationEnvelope.from_mapping(nested_field_unknown)


def test_envelope_parsing_rejects_ambiguous_json_and_types() -> None:
    text = make_envelope().canonical_bytes().decode("ascii")
    duplicate = text[:-1] + ',"authorization_id":"auth-other"}'
    with pytest.raises(CustodyContractValidationError):
        AuthorizationEnvelope.from_json(duplicate)
    for bad in ("[]", "null", "12", "{", "", "   "):
        with pytest.raises(CustodyContractValidationError):
            AuthorizationEnvelope.from_json(bad)
    with pytest.raises(CustodyContractValidationError):
        loads_strict_json('{"a": NaN}')
    with pytest.raises(CustodyContractValidationError):
        loads_strict_json('{"a": 1.5}')
    with pytest.raises(CustodyContractValidationError):
        loads_strict_json("{" + '"a":"' + "x" * 70_000 + '"}')
    with pytest.raises(CustodyContractValidationError):
        AuthorizationEnvelope.from_json(None)

    document = make_envelope().to_document()
    for name, bad_value in (
        ("issued_at_epoch_seconds", "1"),
        ("issued_at_epoch_seconds", True),
        ("issued_at_epoch_seconds", 1.0),
        ("actor_kind", "ROBOT"),
        ("human_presence_requirement", "MAYBE"),
        ("replay_policy", "ALWAYS"),
        ("eligible_approver_refs", "approver-alex-synthetic"),
        ("eligible_approver_refs", []),
        ("eligible_approver_refs", ["a", "a"]),
        ("scope_fingerprint", "A" * 64),
        ("upstream_approval_challenge", "XYZ"),
        ("authorization_id", "bad id"),
    ):
        broken = {**document, name: bad_value}
        with pytest.raises(CustodyContractValidationError):
            AuthorizationEnvelope.from_mapping(broken)


def test_envelope_constructor_enforces_time_order_and_types() -> None:
    with pytest.raises(CustodyContractValidationError):
        make_envelope(not_before_epoch_seconds=NOW - 2_000)
    with pytest.raises(CustodyContractValidationError):
        make_envelope(expires_at_epoch_seconds=NOW - 900)
    with pytest.raises(CustodyContractValidationError):
        make_envelope(key_ref=make_key_ref().to_document())
    with pytest.raises(CustodyContractValidationError):
        make_envelope(eligible_approver_refs=["approver-alex-synthetic"])
    with pytest.raises(CustodyContractValidationError):
        make_envelope(human_presence_requirement="HUMAN_PRESENT_LOCAL")


def test_envelope_carries_no_approval_evidence_fields() -> None:
    names = set(make_envelope().to_document())

    assert not {name for name in names if name.startswith("approval_") or "approved" in name}
    assert "upstream_approval_challenge" in names


def test_trust_anchor_pins_envelope_and_binds_only_human_decision_approvers() -> None:
    envelope = make_envelope()
    anchor = make_anchor(envelope)

    assert anchor.pinned_envelope_digest == envelope.digest()
    binding = anchor.binding_for("approver-alex-synthetic")
    assert binding is not None
    assert binding.key_ref == envelope.key_ref
    assert anchor.binding_for("approver-unknown") is None
    with pytest.raises(CustodyContractValidationError):
        ApproverBinding(
            "approver-alex-synthetic",
            "custody-account-rd01",
            make_key_ref(key_purpose_class=KeyPurposeClass.SERVICE_ATTESTATION),
        )
    with pytest.raises(CustodyContractValidationError):
        make_anchor(envelope, valid_until_epoch_seconds=NOW - 1_001)
    with pytest.raises(CustodyContractValidationError):
        make_anchor(envelope, approver_bindings=())
    with pytest.raises(CustodyContractValidationError):
        make_anchor(envelope, allowed_authorization_classes=())
    with pytest.raises(CustodyContractValidationError):
        make_anchor(envelope, pinned_envelope_digest="F" * 64)


def test_approver_evidence_is_strictly_typed_and_offsets_are_monotonic_integers() -> None:
    assert make_evidence().approval_offset_seconds == 20
    for bad in (
        {"approval_offset_seconds": -1},
        {"approval_offset_seconds": 1.5},
        {"approval_offset_seconds": True},
        {"approval_offset_seconds": "20"},
    ):
        with pytest.raises(CustodyContractValidationError):
            make_evidence(**bad)
    with pytest.raises(CustodyContractValidationError):
        make_evidence(factors=(ApprovalFactor.KEY_UNLOCK, ApprovalFactor.KEY_UNLOCK))
    with pytest.raises(CustodyContractValidationError):
        make_evidence(factors=["KEY_UNLOCK"])
    with pytest.raises(CustodyContractValidationError):
        make_evidence(worker_challenge="short")
    with pytest.raises(CustodyContractValidationError):
        make_evidence(final_payload_digest="E" * 64)


def test_signing_request_and_result_are_reference_only_and_typed() -> None:
    request = SigningRequest(
        authorization_id="auth-rd01-0001",
        operation_id="op-rd01-0001",
        key_ref=make_key_ref(),
        signature_namespace=RD01_SIGNATURE_NAMESPACE,
        canonicalization_id=RD01_RECEIPT_CANONICALIZATION_ID,
        final_payload_digest="e" * 64,
        payload_length=300,
        result_audience="familyos-pilot0-verifier",
        context_digest="7" * 64,
        chain_fingerprint="8" * 64,
        issued_at_epoch_seconds=NOW,
        not_after_epoch_seconds=NOW + 51,
    )
    assert not {"payload", "passphrase", "private_key", "key_path"} & set(
        request.__dataclass_fields__
    )
    with pytest.raises(CustodyContractValidationError):
        replace(request, payload_length=0)
    with pytest.raises(CustodyContractValidationError):
        replace(request, not_after_epoch_seconds=NOW)
    with pytest.raises(CustodyContractValidationError):
        replace(request, chain_fingerprint="F" * 64)
    with pytest.raises(CustodyContractValidationError):
        replace(request, context_digest="short")
    with pytest.raises(CustodyContractValidationError):
        SigningResult(
            authorization_id="auth-rd01-0001",
            operation_id="op-rd01-0001",
            key_ref=make_key_ref(),
            signature_namespace=RD01_SIGNATURE_NAMESPACE,
            final_payload_digest="e" * 64,
            signature_sha256="9" * 64,
            signature_verified=1,  # type: ignore[arg-type]
            elapsed_at_signature_completion_seconds=10,
            signer_reaped=True,
            custody_postconditions_verified=True,
            evidence_sealed=True,
        )


def test_replay_claim_generation_is_nonnegative_exact_int() -> None:
    assert make_claim(ReplayClaimState.RESOURCES_RESERVED).claim_generation == 0
    assert make_claim(ReplayClaimState.RESOURCES_RESERVED, claim_generation=7).claim_generation == 7
    for invalid in (-1, True, 1.5, "1"):
        with pytest.raises(CustodyContractValidationError):
            make_claim(ReplayClaimState.RESOURCES_RESERVED, claim_generation=invalid)


def test_replay_claim_states_are_consistent_with_key_use_intent() -> None:
    with pytest.raises(CustodyContractValidationError):
        make_claim(ReplayClaimState.NO_KEY_USE, key_use_intent_durable=True)
    with pytest.raises(CustodyContractValidationError):
        make_claim(ReplayClaimState.RESOURCES_RESERVED, key_use_intent_durable=True)
    with pytest.raises(CustodyContractValidationError):
        make_claim(ReplayClaimState.KEY_USE_CLAIMED, key_use_intent_durable=False)
    with pytest.raises(CustodyContractValidationError):
        make_claim(ReplayClaimState.SPENT_CLEAN, key_use_intent_durable=False)
    with pytest.raises(CustodyContractValidationError):
        make_claim(ReplayClaimState.RESOURCES_RESERVED, context_digest="short")
    with pytest.raises(CustodyContractValidationError):
        make_claim(ReplayClaimState.RESOURCES_RESERVED, context_digest="A" * 64)
    assert {state: make_claim(state).is_terminal for state in ReplayClaimState} == {
        ReplayClaimState.RESOURCES_RESERVED: False,
        ReplayClaimState.KEY_USE_CLAIMED: False,
        ReplayClaimState.NO_KEY_USE: True,
        ReplayClaimState.SPENT_CLEAN: True,
        ReplayClaimState.SPENT_UNKNOWN: True,
        ReplayClaimState.QUARANTINED: True,
    }


def test_stricter_claim_state_is_total_and_quarantine_is_strictest() -> None:
    order = [
        ReplayClaimState.RESOURCES_RESERVED,
        ReplayClaimState.NO_KEY_USE,
        ReplayClaimState.KEY_USE_CLAIMED,
        ReplayClaimState.SPENT_CLEAN,
        ReplayClaimState.SPENT_UNKNOWN,
        ReplayClaimState.QUARANTINED,
    ]
    for index, left in enumerate(order):
        for right in order[index:]:
            assert stricter_claim_state(left, right) is right
            assert stricter_claim_state(right, left) is right


@pytest.mark.parametrize("state", list(ReplayClaimState))
def test_durable_write_failure_is_spent_or_stricter_never_success(state: ReplayClaimState) -> None:
    result = claim_state_after_durable_write_failure(state)

    assert result in (ReplayClaimState.SPENT_UNKNOWN, ReplayClaimState.QUARANTINED)
    assert stricter_claim_state(result, state) is result


def test_durable_write_failure_without_a_claim_is_spent_unknown() -> None:
    assert claim_state_after_durable_write_failure(None) is ReplayClaimState.SPENT_UNKNOWN


def test_restart_recovery_classifies_untrusted_in_flight_claims_as_spent() -> None:
    in_flight = recover_claim_after_restart(
        make_claim(ReplayClaimState.KEY_USE_CLAIMED, context_digest="6" * 64)
    )
    assert in_flight.state is ReplayClaimState.SPENT_UNKNOWN
    assert in_flight.key_use_intent_durable is True
    assert in_flight.context_digest == "6" * 64
    assert in_flight.claim_generation == 1

    reserved = recover_claim_after_restart(
        make_claim(ReplayClaimState.RESOURCES_RESERVED, claim_generation=11)
    )
    assert reserved.state is ReplayClaimState.NO_KEY_USE
    assert reserved.claim_generation == 12
    assert reserved.non_key_resources_consumed == ("rfc3161-slot",)

    for terminal in (
        ReplayClaimState.NO_KEY_USE,
        ReplayClaimState.SPENT_CLEAN,
        ReplayClaimState.SPENT_UNKNOWN,
        ReplayClaimState.QUARANTINED,
    ):
        claim = make_claim(terminal)
        assert recover_claim_after_restart(claim) == claim


def test_anchor_and_evidence_digests_are_deterministic_and_order_independent() -> None:
    envelope = make_envelope()
    binding_a = ApproverBinding("approver-alex-synthetic", "custody-account-rd01", envelope.key_ref)
    binding_b = ApproverBinding(
        "approver-blake-synthetic", "custody-account-blake", envelope.key_ref
    )
    forward = make_anchor(envelope, approver_bindings=(binding_a, binding_b))
    backward = make_anchor(envelope, approver_bindings=(binding_b, binding_a))

    assert forward.digest() == backward.digest()
    assert (
        forward.digest() == make_anchor(envelope, approver_bindings=(binding_a, binding_b)).digest()
    )
    assert make_anchor(envelope).digest() != forward.digest()
    assert (
        make_anchor(envelope, superseded_by="record-v2").digest() != make_anchor(envelope).digest()
    )

    factors = (ApprovalFactor.KEY_UNLOCK, ApprovalFactor.WORKER_CHALLENGE)
    reordered = (ApprovalFactor.WORKER_CHALLENGE, ApprovalFactor.KEY_UNLOCK)
    assert make_evidence(factors=factors).digest() == make_evidence(factors=reordered).digest()
    assert make_evidence(approval_offset_seconds=21).digest() != make_evidence().digest()
    assert make_evidence(worker_challenge="0" * 32).digest() != make_evidence().digest()


def test_replay_claim_records_the_signing_request_digest_exactly_when_key_use_is_claimed() -> None:
    with pytest.raises(CustodyContractValidationError):
        make_claim(ReplayClaimState.KEY_USE_CLAIMED, signing_request_digest=None)
    with pytest.raises(CustodyContractValidationError):
        make_claim(ReplayClaimState.SPENT_CLEAN, signing_request_digest=None)
    with pytest.raises(CustodyContractValidationError):
        make_claim(ReplayClaimState.RESOURCES_RESERVED, signing_request_digest="7" * 64)
    with pytest.raises(CustodyContractValidationError):
        make_claim(ReplayClaimState.NO_KEY_USE, signing_request_digest="7" * 64)
    with pytest.raises(CustodyContractValidationError):
        make_claim(ReplayClaimState.KEY_USE_CLAIMED, signing_request_digest="F" * 64)
    assert make_claim(ReplayClaimState.SPENT_UNKNOWN).signing_request_digest is None
    assert make_claim(ReplayClaimState.QUARANTINED, signing_request_digest="7" * 64).is_terminal
    recovered = recover_claim_after_restart(
        make_claim(ReplayClaimState.KEY_USE_CLAIMED, signing_request_digest="6" * 64)
    )
    assert recovered.state is ReplayClaimState.SPENT_UNKNOWN
    assert recovered.signing_request_digest == "6" * 64


def test_signing_request_digest_is_canonical_and_binds_every_field() -> None:
    request = SigningRequest(
        authorization_id="auth-rd01-0001",
        operation_id="op-rd01-0001",
        key_ref=make_key_ref(),
        signature_namespace=RD01_SIGNATURE_NAMESPACE,
        canonicalization_id=RD01_RECEIPT_CANONICALIZATION_ID,
        final_payload_digest="e" * 64,
        payload_length=300,
        result_audience="familyos-pilot0-verifier",
        context_digest="7" * 64,
        chain_fingerprint="8" * 64,
        issued_at_epoch_seconds=NOW,
        not_after_epoch_seconds=NOW + 51,
    )

    assert request.digest() == replace(request).digest()
    assert (
        request.digest() == hashlib.sha256(canonical_json_bytes(request.to_document())).hexdigest()
    )
    for override in (
        {"authorization_id": "auth-rd01-0002"},
        {"operation_id": "op-rd01-0002"},
        {"key_ref": make_key_ref(key_version=2)},
        {"signature_namespace": "other-namespace"},
        {"canonicalization_id": "other-canonicalization"},
        {"final_payload_digest": "d" * 64},
        {"payload_length": 301},
        {"result_audience": "other-audience"},
        {"context_digest": "6" * 64},
        {"chain_fingerprint": "5" * 64},
        {"issued_at_epoch_seconds": NOW + 1, "not_after_epoch_seconds": NOW + 52},
        {"not_after_epoch_seconds": NOW + 52},
    ):
        assert replace(request, **override).digest() != request.digest()
