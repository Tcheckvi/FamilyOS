# SPEC-0016 — ProposedAction Contract

**Identifier:** SPEC-0016
**Title:** ProposedAction Contract
**Version:** 1.0.0
**Status:** Approved
**Owner:** FamilyOS Project
**Layer:** Specifications

## Status

`SPEC-0016` defines the approved normative core contract for `ProposedAction`, consistent with accepted `ADR-0014`, `RFC-0017`, and `RFC-0018`.

Approval of this specification records the contract and governance decision only. It does not by itself authorize implementation, runtime changes, merge, release, or any `AI-GOV-FOLLOWUP-001` work. Any implementation remains subject to separate repository and Security/Identity authorization.

Workflow internal process/state representation remains deliberately outside this specification. The normative contract defines the information crossing the Application boundary and the ownership of the relevant decisions; it does not prescribe Workflow's internal state machine or persistence model.

## Abstract

A `ProposedAction` is the single canonical envelope used by an AI Platform Capability to communicate a candidate effect to Application. It carries a target capability, capability-specific arguments, explanation and traceability context, but it conveys no authority.

The contract is intentionally provider-neutral and implementation-neutral. It standardizes the governance-relevant semantic envelope while leaving serialization, storage, API transport, Model Gateway/provider details, and Workflow internals to their owning layers.

## Purpose

This specification makes the accepted architectural decisions in `ADR-0014`, `RFC-0017`, and `RFC-0018` concrete enough for consistent review and later implementation without creating an AI-specific authorization mechanism.

It defines:

- the canonical `ProposedAction` envelope;
- required, optional, and conditionally required fields;
- ownership boundaries for validation, approval, authorization, and execution;
- minimum invariants;
- structured failure/rejection semantics;
- versioning expectations.

## Scope

In scope:

- semantic field names and responsibilities;
- requiredness rules;
- capability-resolution and argument-validation boundaries;
- identity/context references needed for authorization evaluation;
- provenance, correlation, evidence, and approval-routing hints;
- error/rejection categories;
- compatibility and evolution rules for the contract.

Out of scope:

- canonical wire serialization;
- persistence/storage schema;
- concrete API surface;
- Model Gateway or provider-specific payloads;
- concrete Workflow internal state/process representation;
- concrete Security/Identity authorization mechanism internals;
- runtime implementation.

## Normative Language

Normative keywords in this specification, including **MUST**, **MUST NOT**, **SHALL**, **SHALL NOT**, **SHOULD**, **SHOULD NOT**, and **MAY**, are interpreted as defined by the FamilyOS Specification Writing Guide (`docs/06-specifications/Writing-Guide.md`).

## Foundational Rule

**SPEC-0016-R1 — No authority from a proposal.**
A `ProposedAction` conveys no authorization. Its presence, contents, provenance, model output, approval hints, or acceptance by any non-authoritative component MUST NOT, by themselves, permit an effect.

**SPEC-0016-R2 — Authorization ownership.**
Security/Identity remains authoritative for authorization and for the validity of authorization context. Application and Workflow MAY coordinate review and approval, but neither an AI Platform Capability nor the `ProposedAction` contract may assert or manufacture authority.

## Canonical Contract Shape

**SPEC-0016-R3 — Single envelope.**
FamilyOS SHALL use one canonical `ProposedAction` envelope. Capability-specific variation SHALL be represented inside the `arguments` payload and the target capability's own schema rather than by creating parallel top-level AI-specific action contract families.

| Field | Requiredness | Semantic contract |
|---|---|---|
| `capability` | Required | Canonical target capability identifier. |
| `arguments` | Required | Capability-specific structured arguments interpreted under the target capability's schema. |
| `rationale` | Required | Human-reviewable explanation of why the action is proposed. |
| `evidence` | Optional | References to supporting information used by the reasoning/planning process, subject to privacy and disclosure constraints. |
| `provenance` | Required core | Minimum traceability identifying the originating agent/process and audit-relevant model/request lineage. Provider-specific detail MAY remain in internal logs. |
| `actor_ref` | Required | Reference to the actor on whose behalf the proposal was constructed. |
| `authorized_context_ref` | Required | Reference to the authorization context to be evaluated by Security/Identity. It is context only, never an assertion of authority. |
| `risk_hint` | Optional | Non-binding advisory routing signal. |
| `approval_hint` | Optional | Non-binding advisory routing signal. Application/Workflow determines the actual approval path. |
| `correlation_id` | Required | Stable correlation reference for review, execution observation, and audit traceability. |
| `idempotency_key` | Conditionally required | Required when the target effect/capability requires duplicate-execution protection; otherwise optional. |

**SPEC-0016-R4 — No hidden authority fields.**
No field in `ProposedAction` may be interpreted as an authorization token, grant, entitlement, or substitute for Security/Identity evaluation.

## Capability and Argument Semantics

**SPEC-0016-R5 — Existing capability registry.**
`capability` MUST resolve through the existing FamilyOS `PluginCapability` / `PluginCapabilityId` registry model. FamilyOS MUST NOT introduce a parallel AI-specific capability registry for `ProposedAction`.

**SPEC-0016-R6 — Resolution timing.**
Application MUST orchestrate capability resolution during proposal evaluation before an action can advance toward governed approval/authorization and execution. The AI Platform Capability is not authoritative merely because it named a valid capability.

**SPEC-0016-R7 — Argument schema ownership.**
The target capability owns the semantic/schema rules for its `arguments`. AI-side components MUST NOT redefine the target capability's contract.

## Validation and Decision Boundaries

**SPEC-0016-R8 — Structural validation.**
Application MUST reject a structurally invalid proposal before execution. Structural validation includes, at minimum:

- presence of all required fields;
- a capability identifier that resolves through the canonical capability registry;
- arguments that conform to the target capability's contract;
- a syntactically valid correlation identifier;
- an idempotency key when required by the target capability/effect.

Structural validity does not constitute authorization.

**SPEC-0016-R9 — Authorization-context evaluation.**
Security/Identity MUST remain authoritative for whether `actor_ref`, `authorized_context_ref`, and the corresponding authorization context are valid and sufficient at evaluation time. Application MAY orchestrate the lookup and Workflow MAY participate in governed human/policy approval, but they MUST NOT replace Security/Identity authority.

**SPEC-0016-R10 — Approval is not authorization.**
Human or policy approval routing is distinct from authorization. `risk_hint` and `approval_hint` are advisory only. Application/Workflow may determine an approval route, but approval MUST NOT be treated as sufficient authorization unless the owning Security/Identity policy explicitly defines it as part of the authorization decision.

**SPEC-0016-R11 — Execution gate.**
Runtime/Infrastructure MUST NOT execute the proposed effect until all required structural validation, governed approval steps, and Security/Identity authorization have completed successfully under their owning mechanisms.

## Provenance, Evidence, and Correlation

**SPEC-0016-R12 — Minimum provenance.**
Every `ProposedAction` MUST carry enough provenance to associate the proposal with the originating AI/agent process and an audit-relevant request lineage.

**SPEC-0016-R13 — Evidence minimization.**
`evidence` MAY reference supporting information, but it MUST respect existing privacy, access-control, and data-minimization requirements. A proposal MUST NOT expand access to source material merely by referencing it.

**SPEC-0016-R14 — Correlation.**
`correlation_id` MUST support end-to-end traceability across proposal review, authorization evaluation, execution observation, and outcome recording without itself conveying authority.

**SPEC-0016-R15 — Idempotency.**
When duplicate execution could create an additional effect, the target capability or owning Application contract MUST require an `idempotency_key` and define the applicable duplicate-handling behavior.

## Failure and Rejection Semantics

FamilyOS SHALL distinguish the class of failure instead of collapsing all failures into a generic rejection.

**SPEC-0016-R16 — Malformed or structurally invalid proposal.**
A malformed envelope, missing required field, unresolved capability, or arguments that fail the target capability's contract SHALL be classified as a structural validation failure.

**SPEC-0016-R17 — Authorization-context failure.**
An invalid, stale, insufficient, or denied authorization context SHALL be classified separately from structural invalidity and SHALL be determined by the owning Security/Identity mechanism.

**SPEC-0016-R18 — Approval rejection.**
A proposal rejected by a required human or policy approval step SHALL be recorded as an approval rejection, distinct from an authorization denial.

**SPEC-0016-R19 — Execution failure.**
A proposal that passed validation, approval, and authorization but whose technical execution fails SHALL be recorded as an execution failure.

For each failure/rejection class, the owning layer SHOULD produce a structured reason suitable for audit and for safe feedback to the proposing AI Platform Capability. Sensitive policy or security details MUST NOT be exposed merely for explanatory completeness.

## Workflow Integration Carve-Out

**SPEC-0016-R20 — Stable boundary, deferred internals.**
This specification standardizes the `ProposedAction` data crossing the Application boundary and the ownership boundaries around it. It intentionally does not define Workflow's internal state machine, process representation, persistence model, or concrete runtime integration mechanics.

Resolving those Workflow internals later does not invalidate this core contract. If later Workflow work adds backward-compatible contract surface, the specification version SHALL advance under `SPEC-0004-Versioning.md` using the applicable Minor-version rules. A breaking contract change requires the applicable Major-version treatment.

## Versioning and Compatibility

`SPEC-0016` follows `docs/06-specifications/SPEC-0004-Versioning.md`.

Version `1.0.0` is the first approved normative core of the `ProposedAction` contract. Backward-compatible additions and clarifications SHALL follow the existing specification versioning policy. Breaking changes to required fields, field semantics, authorization boundaries, or compatibility expectations require the corresponding breaking-version treatment defined by `SPEC-0004`.

## Revision History

| Version | Status | Summary |
|---|---|---|
| `0.1.0` | Draft | Initial non-normative `ProposedAction` specification skeleton filed for architecture and governance review. |
| `1.0.0` | Approved | First approved normative core contract, incorporating the converged ADR-0014/RFC-0017/RFC-0018 governance boundaries, contract semantics, validation ownership, error taxonomy, and Workflow-internals carve-out. |

## Non-Goals

- This specification does not define a wire serialization.
- This specification does not define a storage schema.
- This specification does not define a concrete API transport.
- This specification does not define Workflow internals.
- This specification does not define Security/Identity implementation internals.
- This specification does not authorize runtime implementation.
- Approval of this specification does not authorize merge, release, or `AI-GOV-FOLLOWUP-001`.

## Related Documents

- `docs/adr/ADR-0014-Agentic-AI-Integration.md`
- `docs/rfcs/RFC-0017-ai-reasoning-planning-agent-coordination/RFC-0017-AI-Reasoning-Planning-Agent-Coordination.md`
- `docs/rfcs/RFC-0018-ai-proposed-actions-workflow-integration/RFC-0018-AI-Proposed-Actions-Workflow-Integration.md`
- `docs/06-specifications/SPEC-0004-Versioning.md`
- `docs/06-specifications/SPEC-0010-Plugin-Capability-Contract.md`
- `src/familyos_cli/plugins/capabilities/plugin_capability.py`
