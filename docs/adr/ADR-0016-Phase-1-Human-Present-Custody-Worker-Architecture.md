# ADR-0016 — Phase-1 Human-Present Custody Worker Architecture

| Field | Value |
|---|---|
| Identifier | ADR-0016 |
| Title | Phase-1 Human-Present Custody Worker Architecture |
| Version | 1.0.0 |
| Status | Accepted |
| Date | 2026-09-22 |
| Scope | F05 Phase-1 human-present custody worker architecture |

## 1. Context

FamilyOS needs a Phase-1 custody boundary for RD-01 human-decision signing that preserves a real human authorization decision while preventing the normal FamilyOS/development environment from exercising the signing capability as software.

Earlier disposable qualification established that the alternate signing interface can function in a bounded synthetic domain, but the production custody path exposed a stronger architecture requirement: a signing capability must not become available merely because software running under the everyday account can reach an agent, endpoint, broker, or long-lived signing service.

The accepted Phase-1 direction is therefore a human-present, agent-less custody worker behind a separately controlled operating-system identity and fixed worker interfaces. A persistent broker is deferred. A future broker, if ever introduced, requires a separate architecture decision and must preserve the same authority boundaries.

The Phase-1 authorization issuer has already been selected by a separate human decision:

```text
OPTION_1 = superseding governed human issuance record
           + exact issuance-record digest pinning
           + verifier identity pinning
           + structured AuthorizationEnvelope semantics
```

No new offline authorization-signing key is introduced for Phase 1.

## 2. Decision

FamilyOS SHALL use a bounded Phase-1 custody worker architecture with the following properties.

### 2.1 Human authorization remains distinct from software execution

The worker SHALL distinguish:

```text
requested
selected_by_human
prepared
confirmed_by_human
key_use_intent_durable
executed
observed
verified
released
```

These distinctions are realized by the reference lifecycle states of Section 3: requested = VALIDATED; selected_by_human = ADMITTED_BY_HUMAN_SELECTION; prepared = RESOURCE_RESERVATIONS_ESTABLISHED through PAYLOAD_DERIVED; confirmed_by_human = HUMAN_CONFIRMED; key_use_intent_durable = KEY_USE_INTENT_DURABLE; executed = SIGNER_RUNNING; observed = SIGNER_REAPED and RESULT_HELD; verified = SIGNATURE_VERIFIED, FINAL_FRESHNESS_ACCEPTED and FINALIZED; released = RELEASED.

No AI output, application request, queue insertion, broker admission, envelope validity, worker start, payload derivation, or successful policy evaluation constitutes human authorization or key-use authorization by itself.

### 2.2 Human selection precedes scarce preparation

For `HUMAN_DECISION`, the human SHALL select the exact validated operation at the trusted custody boundary before any scarce preparation resource for that operation is reserved or submitted.

Selection permits progression only. It does not authorize key use.

### 2.3 Final human confirmation occurs after payload derivation

After trusted time has been acquired and all dynamic payload fields have been derived, the worker SHALL require a distinct final human confirmation of:

- final decoded operation;
- final canonical payload digest;
- worker-generated fresh challenge;
- approver identity binding.

Only after that confirmation may the worker durably record key-use intent.

### 2.4 Phase-1 issuer and trust anchor

The Phase-1 worker SHALL consume a structured `AuthorizationEnvelope` derived from the superseding governed human issuance record.

The worker trust anchor SHALL pin at minimum:

- authorization issuer identity;
- verifier identity;
- exact issuance-record digest;
- exact structured-envelope digest (both the issuance-record digest and the structured-envelope digest are pinned; no substitute binding is accepted without a new reviewed revision of this ADR);
- authorization/policy version;
- validity and supersession state;
- allowed action/capability/scope;
- key reference and key purpose class;
- approver-to-custody-account-to-key mapping;
- payload-template commitment;
- human-presence requirements;
- replay/single-use semantics.

An envelope is data, not authority by self-assertion. The worker SHALL verify it against independently trusted anchors.

### 2.5 Key purpose separation

The Phase-1 RD-01 signing key purpose class is:

```text
HUMAN_DECISION
```

Human-decision keys and future service-attestation keys SHALL be distinct purpose classes and SHALL NOT be silently reused across those purposes.

### 2.6 No long-lived signing endpoint

Phase 1 SHALL NOT introduce:

- an ssh-agent-backed production custody path;
- a long-lived agent socket;
- a generic persistent signing daemon;
- a broker capable of initiating signatures;
- a software endpoint that lets the everyday account exercise the human-decision key.

The signing capability SHALL exist only inside the bounded human-present ceremony and SHALL be removed, reaped, or quarantined at the end of the operation.

### 2.7 Privilege boundary

The qualified production profile SHALL require both the everyday FamilyOS/development account and the custody account to be non-administrator.

If the everyday account is administrator-capable on a supported deployment, that elevation capability SHALL be treated as inside the hostile boundary and a separately reviewed compensating architecture SHALL be required. A second UID alone is not evidence of isolation if the everyday account can administratively cross the boundary.

### 2.8 Runtime claim ledger is part of the trusted computing base

The pure R2 contracts intentionally do not authenticate runtime input provenance. Therefore the authoritative replay/claim ledger SHALL be a trusted runtime component.

It SHALL:

- provide one authoritative granting source;
- use atomic compare-and-set or stronger semantics;
- durably record `context_digest` at resource reservation;
- durably record `signing_request_digest` with key-use intent;
- expose terminal state from the same authoritative store;
- prevent rollback and restart replay;
- fail closed on incomplete durability;
- preserve consumed/spent state across process restart;
- treat mirrors as deny-only observations, never as granting authority.

Caller-supplied claim objects SHALL NOT be accepted as substitutes for reads from the designated authoritative store.

### 2.9 Runtime fact provenance is explicit

The runtime SHALL assign trusted provenance to:

- governed time evidence;
- trust anchors and policy/profile data;
- authoritative claim state;
- approver evidence;
- worker challenge;
- signer process identity and reap state;
- signature verification;
- cleanup result;
- sealed evidence and terminal record.

Pure dataclass construction or Python object identity SHALL never be treated as proof of provenance.

### 2.10 Cleanup must outlive the launcher failure domain

The runtime SHALL include an independently enforced cleanup mechanism, such as a pinned watchdog/supervisor or qualified session teardown mechanism.

The cleanup component:

- SHALL NOT be a signing service;
- SHALL NOT hold a passphrase;
- SHALL NOT hold an unlocked private key;
- SHALL NOT hold an authorization envelope;
- SHALL NOT expose a signing-capable control channel;
- SHALL only terminate, reap, or quarantine the owned signing capability;
- SHALL identify the signer by a process identity stronger than PID alone.

### 2.11 Carried-forward worker prerequisites

The following earlier requirements remain binding and are not superseded by this ADR:

- Privilege and account boundary: the everyday FamilyOS/development account is outside the custody trust boundary; custody runs under a separate protection identity and session; the ordinary account, AI tools, editors, browsers and plugins cannot write worker code, signer pins, trust anchors, allowed-signers material, the claim ledger, custody objects, or protected evidence.
- Trusted human input: human-present input originates in the custody session itself; no relay from an everyday-account terminal qualifies; the fallback ladder is explicit, with hardware presence preferred if the local console path cannot be qualified (the choice is `TRUSTED_INPUT_FALLBACK`, open in Section 9).
- Pin placement and bootstrap: worker code, signer pins, trust anchors, allowed-signers material, claim state and protected evidence are placed outside ordinary-account write authority; the initial pin and trust bootstrap is itself human-verifiable and governed.
- Existing RD-01 authorization: before implementation or real custody, the governing RD-01 authorization is reconciled with this architecture where assumptions differ (custody path and account, automated versus human-present sequence, key provenance, launcher and worker placement, single-use and spent semantics); no historical authorization text is silently reinterpreted.
- Closure: B1 and B2 technical closure is mechanism and profile closure only; a separate real-key readiness gate remains required for the actual encrypted custody object metadata, the actual public fingerprint and provenance, the actual platform and account placement, the actual ceremony runbook, and the actual one-shot real-key use authorization; a closure decision binds one exact artifact and evidence set with an invariants-to-evidence mapping.
- Requalification: any material change to the signer, worker, account isolation, trust anchors, authorization schema, key purpose class, platform profile, claim semantics, input mechanism, or freshness contract requires requalification under the governed change policy.

## 3. Lifecycle

The reference Phase-1 lifecycle is:

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

Terminal key-use outcomes include at minimum:

```text
NO_KEY_USE
SPENT_CLEAN
SPENT_UNKNOWN
QUARANTINED
```

Consumption of a scarce non-key resource SHALL be recorded separately from the key-use dimension.

## 4. Temporal Semantics

The accepted pure-contract semantics are:

- freshness budget: inclusive maximum;
- human confirmation deadline: inclusive maximum;
- payload expiry: exclusive;
- authorization-envelope expiry: exclusive;
- trust-anchor expiry: exclusive;
- signing-request `not_after`: exclusive.

The Worker Specification SHALL define the concrete deadlines and their trusted/monotonic clock semantics.

## 5. Payload and Approval Integrity

The payload-template commitment SHALL exhaustively partition every canonical receipt field into exactly one of:

1. static and bound by the template commitment; or
2. dynamic with one deterministic derivation rule.

Unknown, extra, duplicate, reordered, ambiguously encoded, or undeclared fields SHALL deny.

Protected approval evidence is worker-recorded evidence. It is not itself claimed to be covered by the existing RD-01 receipt signature. The evidence records the final payload digest, which ties it to the signed payload by reference only; the signature does not cover the evidence, and its integrity rests on the worker's sealed evidence package.

## 6. Reuse and Replacement Direction

Expected reuse candidates, subject to exact implementation review:

- governed time-evidence verification logic;
- canonical receipt construction semantics;
- offline signature verification semantics;
- evidence materialization/manifest concepts;
- fail-closed single-use accounting concepts.

Expected replacement candidates:

- real-key ssh-agent loading;
- `ssh-add` custody transition;
- agent socket endpoint use;
- agent-backed signing request path;
- any automation path that bypasses local human confirmation.

The final implementation plan SHALL cite exact concrete artifacts before any implementation authorization.

## 7. Alternatives Considered

### 7.1 Long-lived ssh-agent or same-UID agent endpoint

Rejected for production Phase 1 because software under the everyday identity could exercise the signing capability independently of the intended human ceremony.

### 7.2 Persistent broker now

Deferred. A broker may be considered later only if product/runtime evidence justifies it. A future broker requires a separate ADR and SHALL satisfy the full accepted broker protection floor below; if any one property cannot be demonstrated, the requirement is not satisfied.

```text
BROKER_RUNS_AS_ROOT=false
BROKER_IS_ADMIN=false
BROKER_IDENTITY != CUSTODY_IDENTITY

BROKER_CAN_READ_PRIVATE_KEY=false
BROKER_CAN_READ_ENCRYPTED_CUSTODY_OBJECT=false
BROKER_CAN_READ_PASSPHRASE=false

BROKER_CAN_MODIFY_WORKER_BINARY=false
BROKER_CAN_MODIFY_WORKER_TRUST_ANCHORS=false

BROKER_CAN_SELECT_ARBITRARY_EXECUTABLE=false
BROKER_CAN_SELECT_ARBITRARY_KEY_PATH=false

BROKER_CAN_RESET_AUTHORITATIVE_SINGLE_USE_STATE=false
BROKER_CAN_OBSERVE_OR_INJECT_CUSTODY_SESSION_INPUT=false

BROKER_CAN_MINT_AUTHORIZATION=false
BROKER_CAN_WIDEN_AUTHORIZATION=false
```

### 7.3 Separate offline authorization-signing authority

Not selected for Phase 1. It would introduce another signing key and another custody lifecycle. The human selected the superseding governed issuance-record direction instead.

## 8. Consequences

Positive consequences:

- human authorization remains logically distinct from normal software execution through a separate operating-system identity and session (physical separation is not claimed);
- release cannot rely on a caller-forged signing request when the runtime ledger is correctly integrated;
- key-use intent becomes durable and replay-resistant;
- the architecture has a bounded trusted computing base rather than a general signing service;
- future broker introduction remains optional rather than foundational.

Costs and constraints:

- availability is intentionally sacrificed for fail-closed behavior;
- durable ledger, trusted time, OS identity, cleanup, and evidence sealing become security-critical runtime components;
- the human flow must be measured against freshness limits;
- platform-specific ceremony and cleanup behavior require native qualification.

## 9. Open Human/Deployment Decisions

The following decisions remain open and are not inferred by this ADR:

```text
FRESHNESS_HUMAN_LATENCY_APPROACH=OPEN
RD01_KEY_PROVENANCE=OPEN
TRUSTED_INPUT_FALLBACK=OPEN
EVERYDAY_ACCOUNT_ADMINISTRATOR_STATUS_OR_COMPENSATING_ARCHITECTURE=OPEN
```

These may block production qualification, but they do not invalidate the accepted architecture direction.

## 10. Governance Boundary

This ADR is accepted as the F05 Phase-1 architecture design reference.

Acceptance and repository filing of this ADR are documentation/governance acts only. They do not by themselves authorize implementation, native execution, real custody access, real-key access, real signing, production gate changes, or F05 closure.

```text
IMPLEMENTATION_AUTHORIZED=false
NATIVE_EXECUTION_AUTHORIZED=false
REAL_CUSTODY_ACCESS_AUTHORIZED=false
REAL_KEY_ACCESS_AUTHORIZED=false
REAL_SIGNING_AUTHORIZED=false
F05_CLOSURE_AUTHORIZED=false
```

Implementation, native validation, real custody/key/signing activity, production gate changes, and F05 closure each require separate governed decisions.

## 11. References

- `SPEC-0017` — Phase-1 Custody Worker Contract
- `SPEC-0002` — Identifier
- `SPEC-0003` — Metadata
- `SPEC-0005` — Document Format
- FamilyOS Specification Writing Guide

## 12. Revision History

| Version | Status | Date | Description |
|---|---|---|---|
| 1.0.0 | Accepted | 2026-09-22 | Initial canonical publication of the F05 Phase-1 human-present custody worker architecture. |
