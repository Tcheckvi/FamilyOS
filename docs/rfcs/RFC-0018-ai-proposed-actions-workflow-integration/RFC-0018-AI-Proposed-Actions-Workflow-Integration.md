# RFC-0018: AI Proposed Actions and Workflow Human-Interaction Integration

> **Identifier:** RFC-0018
> **Status:** Draft
> **Filed:** 2026-09-18

## Status

Canonical RFC draft. `RFC-0018` is filed under `docs/rfcs/` after independent review and explicit human filing authorization. It remains Draft and is not accepted or implementation-authorizing. It depends on `ADR-0014` being accepted before this RFC may advance beyond Draft, and it is designed to compose with `RFC-0017`.

## Summary

This RFC proposes how a `ProposedAction` returned by the AI Platform Capability travels through Application to an eventual, authorized, executed effect — without the AI Platform Capability ever holding execution authority, and without inventing a new, AI-specific approval mechanism where one (Workflow's Human Interaction Support) already exists.

## Context

The companion ADR fixes that "AI outputs are proposals, never authority" and that "Workflow's existing Human Interaction Support mechanism... is extended for AI-proposed actions, never duplicated." `docs/00-foundation/Workflow-Architecture.md` already documents this mechanism: "Some FamilyOS processes require human decisions. Workflows should support human participation through controlled interaction points. Examples include: approval steps; validation requests; confirmations; reviews. Human decisions should remain traceable." This RFC defines how AI-proposed actions plug into that existing mechanism.

Direct code inspection (`src/familyos_cli/plugins/`) confirms there is currently no cross-cutting authorization/permission/`ExecutionContext` system to integrate with. This RFC is therefore explicit that its "Security/Identity integration contract" describes the *shape* of a future integration, not a reuse of something that exists today.

## Goals

- Define `ProposedAction` as an untrusted structured proposal: it describes what an AI Platform Capability recommends, never what it is authorized to do.
- Define Application's mediating role between the AI Platform Capability and Workflow/Domain/Plugin.
- Define how a `ProposedAction` enters Workflow's existing approval/confirmation/validation/review mechanism.
- Cleanly separate "approval" (a human or policy decision that a proposal may proceed) from "authorization" (Security/Identity's determination of what an identity is allowed to do), consistent with `Security-Architecture.md`'s definitions.
- Define the execution/observation/verification flow after a `ProposedAction` is approved and authorized.
- Define recurring-policy ownership so that automated, policy-driven execution is never mistaken for an AI decision.

## Non-Goals

- This RFC does not invent a separate AI-specific approval subsystem; it extends Workflow's existing Human Interaction Support mechanism.
- This RFC does not invent a cross-cutting runtime authorization/permission/`ExecutionContext` system; none exists today, and this RFC assumes integration with Security/Identity mechanisms *as they become concretely implemented*.
- This RFC does not authorize any implementation, runtime change, or plugin `execute()`/`invoke()` capability. No such capability exists in the repository today.
- This RFC does not specify a wire format, API endpoint, or persistence schema for `ProposedAction`; see the companion draft SPEC skeleton for a deliberately non-normative sketch of candidate fields.

## Proposed Design

### `ProposedAction` as an Untrusted Structured Proposal

A `ProposedAction` is the sole channel by which action-bearing reasoning from the AI Platform Capability reaches the rest of FamilyOS for authorization or execution consideration. It carries a target capability reference, arguments, a rationale, and supporting evidence (see the companion SPEC draft), but it carries **no** authority: receiving a `ProposedAction` changes nothing by itself. It is data, evaluated by Application, never a command.

### Application Mediation

Never:

```text
AI Agent
   │
   ▼
Finance Plugin
   │
   ▼
PAY
```

Always:

```text
User Intent
    │
    ▼
Application
    │
    ▼
AI Platform Capability (Reasoning / Planning; see companion RFC)
    │
    ▼
ProposedAction
    │
    ▼
Application
    │
    ▼
Workflow (human approval if required)
    │
    ▼
Security / Identity authorization boundary
    │
    ▼
Domain / Plugin capability
    │
    ▼
Runtime / Infrastructure execution
    │
    ▼
Observed result / evidence
```

Application receives every `ProposedAction` and, per its application/use-case orchestration role, decides whether and how the proposal may enter the canonical execution path, including routing into Workflow when process-level orchestration or human interaction is required. Application is the only component that may accept an AI proposal for execution and initiate that canonical path; Workflow may thereafter coordinate the governed multi-step process.

### Workflow Integration for Approvals, Confirmations, Validations, Reviews

A `ProposedAction` that requires human interaction is routed into Workflow's existing "controlled interaction points" (`Workflow-Architecture.md`): approval steps, validation requests, confirmations, or reviews, as appropriate to the proposal's nature. Workflow already owns "Long Running Process Support" (waiting periods, external responses, human approvals, asynchronous activities) — a `ProposedAction` awaiting human decision is modeled as exactly this kind of long-running, traceable process, not as a new state machine invented for AI specifically.

### Separation of Approval from Authorization

Approval (a human, or a previously human-ratified policy, deciding a proposal may proceed) and authorization (Security/Identity's determination of what the relevant identity is actually allowed to do) are distinct decisions and must not be conflated. A `ProposedAction` may be approved by a human and still be refused at the authorization boundary if the identity in question lacks the necessary permission, consistent with `Identity-Architecture.md`'s "Access decisions should consider: identity; permissions; roles; relationships; security policies."

### Security/Identity Integration Contract, Without Inventing Nonexistent Runtime Primitives

This RFC describes the *contract shape* Application should satisfy before invoking Domain/Plugin on behalf of an approved `ProposedAction`: an authorization check against the relevant identity, permissions, and security policies, consistent with `Security-Architecture.md`'s Security Model. It explicitly does not claim that a concrete runtime mechanism implementing this check exists today; direct inspection found none (no `ExecutionContext`, no permission-gate primitive, no privileged-execution mechanism in `src/familyos_cli/plugins/`). Building that mechanism is future work for the Security/Identity architecture track, not this RFC.

### Execution / Observation / Verification Flow

After approval and authorization, Application invokes the relevant Domain/Plugin capability; Runtime/Infrastructure performs the technical execution; the result is observed and retained as evidence (reusing, where applicable, the existing `RuntimeObservationRecorder` pattern already present in `src/familyos_cli/plugins/runtime/runtime_context.py`), closing the loop back to the user/family as an Application result. This mirrors `AI-Architecture.md`'s AI Lifecycle Model's later stages (Result Evaluation, User Interaction, Feedback Collection).

### Recurring-Policy Ownership

An apparently-automated recurring action (e.g. "pay this fixed subscription every month") must never be modeled as an AI decision. The correct model is: the AI Platform Capability may *propose* a candidate policy; a human ratifies it once through the normal approval path above; **Domain owns the business meaning, validity, invariants, and state of the ratified policy**; **Workflow may manage the recurring process, scheduling, waiting, human-interaction points, and execution progression associated with that Domain-owned policy**. Subsequent executions are deterministic executions of that previously authorized policy, not new AI decisions. The AI Platform Capability may still observe and flag anomalies against the ratified policy, but it does not re-decide the policy on each execution.

## Explicit Non-Goals and Boundary Protections

- No separate AI approval subsystem is created; Workflow's existing mechanism is extended.
- No authorization decision is ever made by the AI Platform Capability itself, nor implied by the mere existence of a `ProposedAction`.
- No `ProposedAction` results in a real effect without passing through Application, Workflow (where human interaction is required), and the Security/Identity authorization boundary, in that order.
- No recurring or "automated" execution is attributed to AI decision-making; it is always deterministic execution of a previously human-ratified, Domain-owned policy, with Workflow managing the recurring process where process orchestration is required.

## Alternatives Considered

- **A direct `AI → Plugin` invocation channel for "trusted" or "low-risk" proposals**, bypassing Application/Workflow for convenience. Rejected: violates the companion ADR's boundary rules unconditionally, regardless of perceived risk level; risk-based routing decisions belong to Application/Workflow policy, not to a bypass of the architecture.
- **An AI-specific approval UI/mechanism, separate from Workflow.** Rejected: duplicates Workflow's existing, ratified Human Interaction Support capability and would create two independently-evolving human-approval systems, a risk explicitly named in the discovery round that produced the companion ADR.
- **Treating recurring automated payments as an autonomous AI decision, with post-hoc human review.** Rejected: conflicts with `AI-Architecture.md`'s "AI shall never make autonomous family decisions"; the recurring-policy-ownership model above is the alternative adopted instead.

## Acceptance Criteria

This canonical filing remains Draft. Filing and review do not by themselves make the RFC actionable; acceptance through the repository's RFC workflow remains required. An accepted version would become actionable only once reviewed against the ratified companion ADR and once Security/Identity's concrete authorization mechanism (referenced but not assumed here) has a documented shape to integrate with.

## Future Work

- Concrete Security/Identity authorization mechanism design (outside this RFC's scope; tracked as future Security/Identity architecture work).
- The companion draft SPEC skeleton for `ProposedAction`'s field shape.
- Workflow-side design for how a `ProposedAction`-triggered approval step is represented, once Workflow's own concrete implementation exists to extend.

## Related Documents

- `docs/adr/ADR-0014-Agentic-AI-Integration.md` (this RFC's governing ADR draft)
- `docs/rfcs/RFC-0017-ai-reasoning-planning-agent-coordination/RFC-0017-AI-Reasoning-Planning-Agent-Coordination.md`
- `docs/06-specifications/SPEC-0016-ProposedAction-Contract.md`
- `docs/00-foundation/Workflow-Architecture.md`
- `docs/00-foundation/Security-Architecture.md`
- `docs/00-foundation/Identity-Architecture.md`
- `docs/00-foundation/Application-Architecture.md`
- `src/familyos_cli/plugins/runtime/runtime_context.py`
