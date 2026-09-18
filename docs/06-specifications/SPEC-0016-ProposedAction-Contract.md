# SPEC-0016 — ProposedAction Contract

**Identifier:** SPEC-0016
**Title:** ProposedAction Contract
**Version:** 0.1.0
**Status:** Draft
**Owner:** FamilyOS Project
**Layer:** Specifications

## Status

Canonical draft specification skeleton. `SPEC-0016` is filed in `docs/06-specifications/` after independent review and explicit human filing authorization. It remains deliberately incomplete and non-normative as a whole; filing does not constitute approval and it must not be treated as ready for implementation.

This skeleton follows the general section shape of existing FamilyOS specifications (e.g. `SPEC-0010-Plugin-Capability-Contract.md`) for structural compatibility, without adopting formal numbered normative requirements (`SPEC-XXXX-Rn`), because the underlying design decisions (the two companion RFCs) are not yet approved.

## Abstract

This skeleton sketches candidate fields for a `ProposedAction` contract: the structure an AI Platform Capability uses to communicate a candidate action to Application, per `docs/rfcs/RFC-0018-ai-proposed-actions-workflow-integration/RFC-0018-AI-Proposed-Actions-Workflow-Integration.md`. It is explicitly non-normative. No field listed here is fixed; all are subject to change or removal once the governing RFCs are approved.

## Purpose

To give the two companion RFC drafts (`docs/rfcs/RFC-0017-ai-reasoning-planning-agent-coordination/RFC-0017-AI-Reasoning-Planning-Agent-Coordination.md`, `docs/rfcs/RFC-0018-ai-proposed-actions-workflow-integration/RFC-0018-AI-Proposed-Actions-Workflow-Integration.md`) a concrete illustration of what a `ProposedAction` might contain, so reviewers can evaluate the RFCs against something more tangible than prose — without prematurely fixing a wire format or persistence schema.

## Scope

In scope (illustrative only): candidate field names, candidate types, and a one-line rationale per field. Out of scope: serialization format, storage schema, API surface, versioning scheme, and anything that would require the governing RFCs, or the Security/Identity authorization mechanism they reference, to already be decided.

## Foundational Statement

**A `ProposedAction` conveys no authorization.** Its presence, its fields, and its acceptance by any component do not, by themselves, permit any effect. This statement is normative in intent even though this document as a whole is not; it restates `docs/adr/ADR-0014-Agentic-AI-Integration.md`'s point 5 ("AI outputs are proposals, never authority") and must be preserved in any future non-draft version of this specification.

## Candidate Fields (Non-Normative)

| Candidate field | Candidate type | Rationale (draft, unsettled) |
|---|---|---|
| `capability` | string (capability identifier, e.g. `calendar.event.create`) | Names the target capability the proposal would invoke, consistent with the existing `PluginCapabilityId`-style identifiers already used in `src/familyos_cli/plugins/capabilities/`. Unsettled: whether this must resolve to a registered `PluginCapability` at proposal time or only at approval time. |
| `arguments` | structured/typed, capability-specific | The candidate parameters for the target capability (e.g. date, title for a calendar event). Unsettled: validation timing and schema ownership (AI Platform Capability vs. target capability). |
| `rationale` | free text or structured explanation | Supports `AI-Architecture.md`'s "Explainable AI" principle — why the AI Platform Capability proposed this action. Unsettled: whether structure (e.g. cited evidence references) is required or optional. |
| `evidence` | list of references | Supporting information the reasoning/planning process used, for human review and traceability. Unsettled: whether this references Authorized Context items directly or a redacted/summarized form. |
| `provenance` | structured (originating agent, model, Model Gateway request id) | Traceability back to which internal agent and model produced the proposal, per the companion RFC's observability goals. Unsettled: retention policy and whether provider-identifying detail belongs here or only in internal logs. |
| `actor_ref` / `authorized_context_ref` | reference(s) | References the actor and Authorized Context under which the proposal was constructed, so Application/Workflow/Security can evaluate it against the correct identity. These references are provenance/context inputs only and are never a channel for the AI Platform Capability to assert authority. |
| `risk_hint` / `approval_hint` | enumerated or free text, advisory only | A non-binding signal the AI Platform Capability may attach (e.g. "financial", "recurring", "irreversible") to help Application/Workflow route the proposal to the right approval path. Explicitly advisory: Application/Workflow, not the AI Platform Capability, decides the actual approval requirement. |
| `correlation_id` / `idempotency_key` | string | Supports the execution/observation/verification flow in the companion RFC and prevents duplicate execution of the same proposal. Unsettled: generation responsibility (AI Platform Capability vs. Application) and collision-handling policy. |

## Explicitly Unsettled

- Whether `ProposedAction` is a single unified contract or a family of capability-specific contracts sharing a common envelope.
- The relationship, if any, between `ProposedAction` and the existing `PluginCapability` registry/provider pattern (`src/familyos_cli/plugins/capabilities/`) — reuse versus a parallel, AI-specific registry.
- Versioning and compatibility rules, pending the two companion RFCs' approval and pending acceptance and later normative stabilization of `SPEC-0016`.
- Any relationship to Workflow's internal process/state representation, since Workflow's own concrete mechanism has not yet been designed in enough depth to define an integration point precisely.

## Non-Goals

- This skeleton does not define validation rules, required-vs-optional fields, or a canonical serialization.
- This skeleton does not authorize any implementation.
- This filed draft does not authorize implementation or normative use; acceptance and normative stabilization remain deferred until the governing RFCs are approved.

## Related Documents

- `docs/adr/ADR-0014-Agentic-AI-Integration.md`
- `docs/rfcs/RFC-0017-ai-reasoning-planning-agent-coordination/RFC-0017-AI-Reasoning-Planning-Agent-Coordination.md`
- `docs/rfcs/RFC-0018-ai-proposed-actions-workflow-integration/RFC-0018-AI-Proposed-Actions-Workflow-Integration.md`
- `docs/06-specifications/SPEC-0010-Plugin-Capability-Contract.md` (structural reference)
- `src/familyos_cli/plugins/capabilities/plugin_capability.py`
