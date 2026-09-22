# SPEC-0017 — Phase-1 Custody Worker Contract

**Identifier:** SPEC-0017
**Title:** Phase-1 Custody Worker Contract
**Version:** 1.0.0
**Status:** Approved
**Owner:** FamilyOS Project
**Layer:** Specifications

## 1. Purpose

This specification defines the normative Phase-1 custody-worker contract for RD-01 human-decision signing.

It specifies:

- worker inputs and trusted inputs;
- authorization-envelope and trust-anchor requirements;
- payload-template partition and canonical derivation;
- human selection and final confirmation;
- authoritative replay/claim-ledger behavior;
- signer-entry and signature-release boundaries;
- temporal semantics;
- cleanup and terminal-state rules;
- evidence obligations;
- fail-closed behavior.

It does not authorize implementation or execution.

## 2. Scope

Phase 1 supports a single-human `HUMAN_DECISION` flow.

The following are out of scope for Phase 1:

- dual-human approval;
- delegation chains;
- persistent signing services;
- persistent brokers;
- generic remote signing endpoints;
- arbitrary key selection;
- arbitrary executable selection;
- automatic authorization by AI or workflow software.

## 3. Normative References

- `ADR-0016` — Phase-1 Human-Present Custody Worker Architecture
- `SPEC-0002` — Identifier
- `SPEC-0003` — Metadata
- `SPEC-0004` — Versioning
- `SPEC-0005` — Document Format
- `SPEC-0007` — File Format
- FamilyOS Specification Writing Guide

## 4. Terms and Definitions

The following terms are used as defined by the normative requirements in Section 6.

### AuthorizationEnvelope

The structured authorization input whose source issuance record is governed outside the worker and whose identity, scope, validity, replay profile, and key-use constraints are independently bound.

### TrustAnchorRecord

The independently trusted record that pins issuer/verifier identity, issuance and envelope digests, validity, revocation/supersession state, key identity, approver/custody bindings, payload-template identity, and replay requirements.

### Authoritative Claim Ledger

The single durable granting source for reservation, key-use intent, and terminal claim state. Mirrors are deny-only and cannot grant authority.

### SigningRequest

A reference artifact that binds the authorization, operation, trusted context, final payload digest, key identity, audience, and temporal bounds. It is not authority by itself.

### SigningResult

A held signer output that is subject to independent verification, authoritative terminal-state checks, cleanup/postcondition checks, evidence sealing, and final freshness checks before release.

## 5. Normative Language

The key words MUST, MUST NOT, SHALL, SHALL NOT, SHOULD, SHOULD NOT, and MAY are normative requirements for this specification.

## 6. Requirements

### 6.1 Trust Model

#### 6.1.1 Trusted components

The implementation SHALL define and pin the trusted components responsible for:

- authorization issuance verification;
- verifier identity;
- trust-anchor retrieval;
- policy/profile retrieval;
- governed time evidence;
- authoritative replay/claim state;
- custody-session identity;
- signer process ownership;
- signature verification;
- cleanup supervision;
- evidence sealing.

#### 6.1.2 Untrusted or hostile inputs

The worker SHALL treat as untrusted until independently validated:

- caller-created Python objects;
- caller-created claims;
- envelope self-assertions;
- profile values supplied by a request;
- anchor values supplied by a request;
- wall-clock assertions;
- signer results;
- mirror claims;
- process identifiers without stronger ownership binding.

#### 6.1.3 Carried-forward prerequisites

The prerequisites listed in the ADR, Section 2.11 (privilege and account boundary, trusted human input, pin placement and bootstrap, reconciliation of the existing RD-01 authorization, mechanism-only closure with a separate real-key readiness gate, and requalification on material change) are normative for this specification. They SHALL be satisfied or explicitly dispositioned before an implementation authorization decision under Section 6.20.

### 6.2 Phase-1 Authorization Issuer

The selected issuer direction is:

```text
PHASE1_ISSUER_HUMAN_DECISION=OPTION_1
PHASE1_ISSUER_DIRECTION=SUPERSEDING_GOVERNED_HUMAN_ISSUANCE_RECORD
```

The worker SHALL consume a structured `AuthorizationEnvelope` whose source issuance record is governed outside the worker.

The worker SHALL NOT accept an envelope merely because its internal digest fields are self-consistent. The envelope SHALL be checked against independently trusted anchor data.

### 6.3 AuthorizationEnvelope

The envelope SHALL bind, at minimum:

```text
schema_version
authorization_id
operation_id
issuer_ref
verifier_ref
issuer_trust_version
issuance_record_digest
subject_ref
represented_actor_ref
actor_kind
eligible_approver_refs
upstream_approval_challenge (when present)
capability_or_action
capability_version
resource_or_scope
audience
result_audience
key_ref
key_purpose_class
signature_namespace
payload_template_commitment
issued_at
not_before
expires_at
human_presence_profile
single_use_or_replay_profile
policy_version
revocation_handle
delegation_chain (SHALL be empty in Phase 1; a non-empty chain denies)
```

The envelope binds exactly one `operation_id`. The authoritative ledger SHALL key single use by `authorization_id`: a claim request for an `authorization_id` that already has any claim, under any `operation_id`, SHALL deny.

Unknown fields SHALL deny unless the canonical envelope schema explicitly version-controls and permits them.

Missing required fields, duplicate fields, invalid types, floats where forbidden, non-finite numbers, ambiguous encodings, and non-canonical representations SHALL deny.

### 6.4 TrustAnchorRecord

The trusted anchor SHALL pin, at minimum:

```text
issuer_ref
verifier_ref
issuance_record_digest
structured_envelope_digest
anchor_version
validity interval
revocation state
supersession state
allowed capability/action/scope
key purpose class
expected key reference
expected public-key fingerprint
approver_ref
custody_account_id
payload-template commitment identity
human-presence requirements
replay/single-use requirements
```

The worker SHALL reject:

- revoked anchors;
- superseded anchors when the superseding state is applicable;
- expired anchors at the exact expiry instant;
- context substitution;
- profile substitution;
- envelope substitution.

### 6.5 KeyRef

`KeyRef` SHALL identify the expected logical key without accepting caller-selected paths.

It SHALL bind:

```text
key_id
key_version
public_key_fingerprint
key_purpose_class
algorithm_profile
backend_id
```

`key_purpose_class` for the Phase-1 RD-01 human-decision key SHALL be `HUMAN_DECISION`.

### 6.6 PayloadTemplateCommitment

#### 6.6.1 Exhaustive partition rule

Every field in the canonical RD-01 receipt payload SHALL be classified exactly once as either:

- STATIC: value fixed and bound by the template commitment; or
- DERIVED: value produced by one declared deterministic rule.

A field in both or neither categories SHALL deny.

#### 6.6.2 Canonical RD-01 field set

The current canonical field set is:

```text
version
purpose
receipt_identifier
verifier_identifier
subject_identifier
scope_fingerprint
issued_at_epoch_seconds
expires_at_epoch_seconds
decision_reference
integrity_proof_identifier
```

#### 6.6.3 Phase-1 proposed assignment

Unless superseded by a later reviewed specification revision, Phase 1 SHALL use:

STATIC:

```text
version
purpose
verifier_identifier
subject_identifier
scope_fingerprint
decision_reference
integrity_proof_identifier
```

DERIVED:

```text
receipt_identifier
issued_at_epoch_seconds
expires_at_epoch_seconds
```

`purpose` SHALL equal the governed signature namespace.

`issued_at_epoch_seconds` SHALL derive from verified governed time evidence.

`expires_at_epoch_seconds` SHALL equal the derived issued-at time plus the authorization-fixed TTL.

`receipt_identifier` SHALL use one reviewed deterministic collision-resistant derivation rule bound to `authorization_id` and `operation_id`.

#### 6.6.4 Canonicalization binding

The payload canonicalization identity SHALL bind at minimum:

```text
schema_version
field_set
field_order
separators
line_terminator
encoding
normalization
unknown_field_policy
```

Unknown, extra, duplicate, reordered, ambiguously encoded, or undeclared fields SHALL deny.

#### 6.6.5 Final digest invariant

Before signer entry:

```text
final_digest_before_sign == digest(worker_held_canonical_bytes)
```

After signing and before release:

```text
final_digest_after_sign == final_digest_before_sign
```

The verified signature SHALL cover those exact canonical bytes.

### 6.7 ApproverEvidence

For single-human Phase 1:

```text
presenter_ref == approver_ref
```

The minimum approver-evidence set SHALL require the combination of:

1. authenticated custody-session login under the qualified custody account;
2. successful unlock of the purpose-scoped encrypted key using the human-held passphrase or separately qualified stronger human-presence factor;
3. local human confirmation of exact operation and final payload digest;
4. a worker-generated fresh challenge bound to the operation.

No one factor alone establishes the approver.

The worker SHALL bind protected approval evidence to:

```text
approver_ref
authorization_id
operation_id
final_payload_digest
worker_generated_challenge
approval_time
human_presence_profile
custody_account_id
expected_key_ref
expected_public_key_fingerprint
```

The worker-generated challenge SHALL NOT be replaced by upstream challenge material.

`approval_time` SHALL use a monotonic offset or bounded event time relative to verified governed time evidence, not an untrusted wall-clock assertion.

The approval evidence itself is not claimed to be signed by the existing RD-01 receipt signature. It records the final payload digest, which ties it to the signed payload by reference only; its integrity rests on the sealed worker evidence.

### 6.8 Admission and Context Binding

Admission SHALL recompute the trusted context from the exact:

- authorization envelope;
- trust anchor;
- worker policy/profile.

The admitted context SHALL be represented by a deterministic `context_digest`.

Later stages SHALL NOT rely on a prior Python decision object as proof of admission.

At each irreversible boundary, the implementation SHALL recompute or revalidate the required bindings against trusted inputs.

#### 6.8.1 Reference Lifecycle and Human Selection Order

For `HUMAN_DECISION` the reference lifecycle is:

```text
VALIDATED
ADMITTED_BY_HUMAN_SELECTION
RESOURCE_RESERVATIONS_ESTABLISHED
TIME_EVIDENCE_VERIFIED
PAYLOAD_DERIVED
HUMAN_CONFIRMED
KEY_USE_INTENT_DURABLE
SIGNER_RUNNING
SIGNER_REAPED
RESULT_HELD
SIGNATURE_VERIFIED
FINAL_FRESHNESS_ACCEPTED
FINALIZED
RELEASED
```

The human SHALL select the specific validated operation at the trusted custody boundary, including review of the decoded static operation fields, before any scarce preparation resource for that operation is reserved or submitted. A valid envelope, queue insertion, operation identifier, broker admission, or starting the worker SHALL NOT replace this selection. Selection permits progression only; it does not authorize key use.

`HUMAN_CONFIRMED` SHALL be a distinct confirmation, after trusted time is acquired and the dynamic fields are derived, of the final decoded operation, the final canonical payload digest, the worker-generated challenge, and the approver identity binding. Only after it may `KEY_USE_INTENT_DURABLE` occur (Section 6.9.4).

### 6.9 Authoritative Replay / Claim Ledger

#### 6.9.1 Authority

Exactly one durable claim store SHALL be the authoritative granting source.

Mirrors SHALL be deny-only.

A caller-created `ReplayObservation` or `ReplayClaim` object SHALL NOT constitute authority. Runtime adapters SHALL construct the authoritative view only from the designated store.

#### 6.9.2 Required claim states

The claim model SHALL include at minimum:

```text
UNSEEN
RESOURCES_RESERVED
KEY_USE_CLAIMED
NO_KEY_USE
SPENT_CLEAN
SPENT_UNKNOWN
QUARANTINED
```

`UNSEEN` denotes the absence of a claim record and is not a stored state. A state SHALL NOT be renamed, merged or replaced by an "equivalent" without a reviewed revision of this specification.

Consumption of a scarce non-key resource SHALL be recorded separately from the key-use dimension: a failure after such consumption and before key use records the resource as consumed and the key-use dimension as `NO_KEY_USE`.

#### 6.9.3 Reservation binding

When resources are reserved, the authoritative record SHALL durably and atomically bind:

```text
authorization_id
operation_id
context_digest
reservation identity / consumed resource identity
claim state
```

#### 6.9.4 Key-use intent binding

Immediately before signer execution, and only after final human confirmation, the authoritative record SHALL durably and atomically bind:

```text
signing_request_digest
key_use_intent=true
claim state = KEY_USE_CLAIMED
```

The signer SHALL NOT run unless this write is confirmed durable. If the compare-and-set finds any other state, including a stricter state such as `SPENT_CLEAN`, `SPENT_UNKNOWN` or `QUARANTINED`, the key-use intent is not established and the signer SHALL NOT run.

#### 6.9.5 Terminal state

After signer completion, the same authoritative store SHALL record the terminal state.

Signature release SHALL require the terminal state `SPENT_CLEAN` exactly. Every other state, including `NO_KEY_USE` and the stricter states `SPENT_UNKNOWN` and `QUARANTINED`, SHALL withhold the result.

#### 6.9.6 Durability failures

Any failure to durably record:

- reservation;
- key-use intent;
- terminal state;
- claim consumption;

including file sync, directory sync, transaction commit, compare-and-set, or equivalent persistence failure, SHALL fail closed.

The state SHALL become spent or stricter and SHALL NOT become reusable automatically.

#### 6.9.7 Restart and rollback

Restart/recovery SHALL never map an in-flight or uncertain state back to reusable.

Rollback to an older authoritative claim version SHALL be detected or prevented.

The implementation SHALL define anti-rollback evidence, monotonic versioning, transaction sequence, or equivalent mechanism.

#### 6.9.8 Mirror semantics

For every required mirror:

- missing mirror => deny;
- unreachable mirror => deny;
- mirror with conflicting claim => deny;
- reachable mirror with no claim SHALL be treated as a lagging deny-only mirror and accepted (a mirror can never grant);
- mirror agreement SHALL never create granting authority.

### 6.10 SigningRequest

A `SigningRequest` is a reference artifact, not authority.

It SHALL bind at minimum:

```text
authorization_id
operation_id
context_digest
chain_fingerprint
final_payload_digest
payload_length
key_ref
signature_namespace
canonicalization_id
result_audience
issued_at
not_after
```

It SHALL expose one deterministic canonical digest.

The runtime SHALL record this digest in the authoritative claim at key-use intent.

### 6.11 Signer-Entry Verification

The signer boundary SHALL:

1. reject any request or confirmation-chain input whose exact runtime type is not the expected `SigningRequest` or confirmation-chain type;
2. reject subclasses and proxy types;
3. recompute the current confirmation chain from trusted inputs;
4. compare canonical request digests rather than Python object equality;
5. verify payload, envelope, anchor, confirmation, and request validity windows;
6. verify that the authoritative claim is in state exactly `KEY_USE_CLAIMED` and binds the expected context and signing-request digest (terminal and stricter states are rejected);
7. verify the expected key identity and purpose class.

Python `__eq__`, object identity, dataclass construction history, or class-subclass compatibility SHALL NOT be treated as provenance.

### 6.12 SigningResult

The signer result SHALL be held, not immediately released.

It SHALL bind at minimum:

```text
operation_id
authorization_id
signing_request_digest
final_payload_digest
signature_verified
signer_reaped
custody_postconditions
evidence_sealed
completion_time_or_elapsed
```

The exact result schema SHALL be versioned. The terminal state is not a result field: it is read from the authoritative claim (Section 6.13).

### 6.13 Signature Release

Release SHALL require all of the following:

- exact expected runtime types of the release request, the `SigningRequest` and the `SigningResult`;
- `SigningRequest.digest()` equals the authoritative claim's recorded `signing_request_digest`;
- authoritative claim identity matches authorization and operation;
- authoritative context digest matches;
- required mirrors satisfy Section 6.9.8;
- authoritative terminal state is exactly `SPENT_CLEAN`;
- result binds the request and payload;
- signature verification passed;
- signer is reaped;
- custody postconditions passed;
- terminal record is read from the authoritative claim, not asserted by the result;
- evidence is sealed;
- final freshness is accepted.

A caller-controlled request with a widened `not_after` SHALL remain withheld because its digest cannot replace the recorded authoritative digest.

A caller-controlled claim object containing a matching forged digest SHALL NOT be accepted by the runtime adapter; the claim MUST originate from the designated authoritative store.

### 6.14 Temporal Semantics

The accepted semantics are:

```text
freshness_budget: inclusive maximum
human_confirmation_deadline: inclusive maximum
payload_expiry: exclusive
envelope_expiry: exclusive
anchor_expiry: exclusive
signing_request_not_after: exclusive
```

Therefore, if a budget is `B` seconds:

```text
elapsed <= B  => within budget
elapsed > B   => outside budget
```

At an expiry instant:

```text
now >= expiry => expired
```

Because the freshness budget is an inclusive maximum and `not_after` is an exclusive instant, the signing request bound SHALL be `not_after = min(payload_expiry, envelope_expiry, anchor_valid_until when set, issued_at + overall_freshness_budget + 1)`.

Concrete production values remain governed policy and SHALL NOT be inferred from synthetic fixture values.

### 6.15 Required Deadlines

The runtime SHALL define finite values for:

```text
human_selection_deadline
human_confirmation_deadline
signer_execution_deadline
cleanup_reap_deadline
overall_transaction_deadline
overall_freshness_budget
```

The implementation SHALL define suspend/resume behavior and which deadlines use governed wall time, monotonic time, or both.

### 6.16 Cleanup and Process Ownership

The signing capability SHALL be owned by exactly one controlled runtime component.

The cleanup mechanism SHALL outlive launcher failure and SHALL:

- know the signer through a stable ownership identity stronger than PID alone;
- issue at most the reviewed termination sequence;
- bound waits;
- reap the signer;
- quarantine uncertainty;
- preserve cleanup evidence.

The cleanup watchdog SHALL hold no passphrase, no unlocked key, no authorization envelope, and no signing-capable control channel.

### 6.17 Evidence Package

For every governed operation, the runtime SHALL seal an evidence package sufficient to reconstruct:

- trusted input identities and digests;
- authorization-envelope identity;
- trust-anchor identity;
- context digest;
- human selection event;
- protected approval evidence;
- payload-template identity;
- final canonical payload digest;
- resource reservation;
- key-use intent write;
- signing-request digest;
- signer process identity and lifecycle;
- signature verification;
- claim-ledger terminal state;
- cleanup result;
- final freshness decision;
- release decision.

Evidence SHALL distinguish observed fact, trusted input, derived value, and human decision.

### 6.18 Required Negative Tests

Before implementation authorization can advance, tests SHALL cover at minimum:

- forged Stage-1 decision;
- forged READY decision;
- wrong derivation binding;
- anchor substitution;
- profile substitution/loosening;
- payload TTL expiry;
- envelope exact expiry;
- anchor exact expiry;
- duplicate mirror identifiers;
- missing/unreachable/conflicting mirror;
- forged signer request;
- malicious equality object;
- subclass/proxy request;
- one-field request mutations;
- late release;
- widened forged `not_after`;
- forged caller claim substitution at runtime adapter;
- durable reservation write failure;
- durable key-use-intent write failure;
- terminal-state write failure;
- restart after every in-flight state;
- rollback attempt;
- launcher death around every irreversible boundary;
- signer cleanup timeout;
- signer identity mismatch;
- sealed-evidence failure;
- signer entry with a claim in any state other than `KEY_USE_CLAIMED`, including terminal and stricter states;
- release with a terminal state other than `SPENT_CLEAN` (`NO_KEY_USE`, `SPENT_UNKNOWN`, `QUARANTINED`);
- release with a required mirror missing, unreachable or conflicting, and with a reachable mirror reporting no claim;
- a second claim for an existing `authorization_id` under a different `operation_id`;
- a `SigningResult` that asserts a terminal record the authoritative claim does not show.

### 6.19 Open Deployment Decisions

The following remain explicitly open:

```text
FRESHNESS_HUMAN_LATENCY_APPROACH=OPEN
RD01_KEY_PROVENANCE=OPEN
TRUSTED_INPUT_FALLBACK=OPEN
EVERYDAY_ACCOUNT_ADMINISTRATOR_STATUS_OR_COMPENSATING_ARCHITECTURE=OPEN
```

No implementation shall silently choose these values.

### 6.20 Implementation Gate

Approval and filing of this specification do not by themselves authorize implementation.

Before any repository implementation step, a separate governed decision SHALL bind:

- the reviewed ADR revision;
- the reviewed Worker Specification revision;
- exact implementation scope;
- exact repository baseline;
- exact files allowed to change;
- unresolved deployment decisions relevant to that slice;
- validation obligations;
- the exact reuse and replacement map citing concrete implementation artifacts (ADR, Section 6);
- the reconciliation of the governing RD-01 authorization (ADR, Section 2.11).

Current boundary:

```text
IMPLEMENTATION_AUTHORIZED=false
NATIVE_EXECUTION_AUTHORIZED=false
REAL_CUSTODY_ACCESS_AUTHORIZED=false
REAL_KEY_ACCESS_AUTHORIZED=false
REAL_SIGNING_AUTHORIZED=false
F05_CLOSURE_AUTHORIZED=false
```

### 6.21 Contracts Still To Be Specified

Before an implementation authorization decision, a reviewed revision of this specification SHALL define:

- the canonical serialization and digest of the `AuthorizationEnvelope`, `TrustAnchorRecord`, worker profile, `context_digest` and `chain_fingerprint`;
- the claim-ledger transition table, the compare-and-set interface and the uniqueness key;
- for each runtime fact (governed time, trust anchors, worker profile, claim reads, approver evidence, worker challenge, signer identity and reap state, signature verification, cleanup result, sealed evidence, terminal record), the trusted component that may construct it and the store it is read from;
- the `receipt_identifier` derivation rule and its inputs;
- that the final canonical bytes are produced by the existing RD-01 receipt canonicalization (`TrustedHumanAuthorizationReceipt.canonical_payload_bytes`), whose fixed `version` and `purpose` the template commitment SHALL match;
- the disposition of the implementation dependency on the currently untracked `real_data_wave_a.py` and `trust_source_bindings.py`.

## 7. Constraints

This specification is constrained by the following durable boundaries:

- Phase 1 supports a single-human `HUMAN_DECISION` flow.
- Persistent signing services and persistent brokers are outside Phase-1 scope.
- Caller-created claims, envelopes, profiles, anchors, process identifiers, and signer results are untrusted until independently validated as required by Section 6.
- Open deployment decisions listed in Section 6.19 SHALL remain open until separately governed.
- The unresolved contracts listed in Section 6.21 SHALL be specified in a reviewed revision before implementation authorization.

## 8. Conformance

An implementation conforms to this specification only if:

- every applicable MUST and SHALL requirement in Section 6 is satisfied;
- the authoritative ledger remains the sole granting source;
- signer-entry and release gates use the exact accepted claim states;
- required negative tests in Section 6.18 pass;
- no open deployment decision is silently selected;
- all implementation-gate obligations in Section 6.20 are satisfied before implementation authorization.

Conformance to this specification does not itself authorize deployment, real-key use, or F05 closure.

## 9. Security Considerations

This specification defines a security-sensitive custody boundary and therefore adopts fail-closed behavior throughout.

Implementations SHALL preserve:

- human selection before scarce-resource reservation;
- distinct final human confirmation before durable key-use intent;
- exact request/context digest binding;
- authoritative claim-ledger provenance;
- deny-only mirror behavior;
- exact signer-entry and release claim states;
- bounded temporal semantics;
- independent signer cleanup and evidence sealing.

Documentation, examples, fixtures, and tests SHALL NOT contain real private keys, passphrases, credentials, or confidential family data.

## 10. Compatibility

The permanent identifier of this specification is `SPEC-0017`.

Future revisions SHALL preserve stable requirement meaning and identifier traceability. Any change that weakens authority separation, claim-state gates, digest binding, human-presence ordering, or fail-closed behavior is compatibility-sensitive and requires explicit governed review.

Implementation compatibility remains subject to the separate implementation authorization gate in Section 6.20.

## 11. Examples

The fenced text and state-transition snippets in Section 6 are informative representations unless the surrounding normative text explicitly makes the represented value or relation mandatory.

No example creates authority or relaxes a normative requirement.

## 12. References

- `ADR-0016` — Phase-1 Human-Present Custody Worker Architecture
- `SPEC-0002` — Identifier
- `SPEC-0003` — Metadata
- `SPEC-0004` — Versioning
- `SPEC-0005` — Document Format
- `SPEC-0007` — File Format
- FamilyOS Specification Writing Guide

## 13. Revision History

| Version | Status | Date | Description |
|---|---|---|---|
| 1.0.0 | Approved | 2026-09-22 | Initial canonical publication of the F05 Phase-1 custody worker contract. |
