# RFC-0017: AI Reasoning, Planning and Agent Coordination

> **Identifier:** RFC-0017
> **Status:** Accepted
> **Filed:** 2026-09-18

## Status

Accepted. `RFC-0017` was filed under `docs/rfcs/` after independent review, and is formally accepted through explicit human acceptance decision, following the acceptance of `ADR-0014`; every boundary decision in that ADR remains a fixed constraint, not an open question. Acceptance does not authorize implementation; runtime implementation remains a separate, explicitly governed step.

## Summary

This RFC proposes the internal mechanism by which the FamilyOS AI Platform Capability understands user intent, reasons about it, plans a response, and coordinates domain-scoped agents — entirely inside the AI Platform Capability boundary fixed by the companion ADR. It does not propose how AI-produced proposals become authorized actions; that is the subject of the companion RFC, "AI Proposed Actions and Workflow Human-Interaction Integration."

## Context

`docs/00-foundation/AI-Architecture.md` already defines AI Services at a capability-type level (Knowledge Retrieval, Reasoning, Recommendations, Automation, Assistance) and an AI Lifecycle Model (Capability Definition → Data Authorization → Context Preparation → AI Processing → Result Evaluation → User Interaction → Feedback Collection → Improvement), but does not define a concrete reasoning/planning/agent-coordination mechanism. This RFC fills that gap for the "Domain Intelligence" roadmap phase, without pre-building infrastructure ahead of concrete need (Engineering Constitution Article III).

## Goals

- Define how user/family intent is detected and handed to a reasoning/planning process.
- Define domain-scoped agents (e.g. Finance, Education, Documents) as an internal decomposition of the AI Platform Capability, not as replacements for or peers of the corresponding Domain components.
- Define an Authorized Context concept consistent with the vocabulary already established in `Security-Architecture.md` ("identity; permissions; roles; relationships; security policies") and `Identity-Architecture.md` ("Authorization context represents the conditions under which an identity can access FamilyOS capabilities"), so AI never decides for itself what data it may see.
- Define a Model Gateway / provider-abstraction boundary so the AI Platform Capability is not coupled to a specific LLM provider.
- Define minimum evaluation/observability requirements consistent with `AI-Architecture.md`'s "maintain AI interaction traceability" responsibility.

## Non-Goals

- This RFC does not define the `ProposedAction` contract shape in detail (see the companion RFC and the draft SPEC skeleton).
- This RFC does not define or authorize any runtime execution, side effect, or plugin invocation.
- This RFC does not introduce an "AI Orchestrator" role or any orchestration mechanism outside Application, per the companion ADR.
- This RFC does not specify a Python class hierarchy, a specific LLM provider, or prompt text. Those are implementation concerns for a later, separately-reviewed change.
- This RFC does not invent an AI-specific authorization or permission system. See "Explicit Non-Goals and Boundary Protections" below.

## Architectural Boundary

Consistent with the companion ADR, the AI Platform Capability's authorized-data dependency remains `AI → Authorized Data` (per `Architecture-Map.md`'s "Allowed examples"). Its canonical invocation and result-flow boundary is `Application → AI Platform Capability → Application`: Application invokes AI with Authorized Context, and AI returns reasoning results or a `ProposedAction` to Application. This interaction does not authorize AI to depend directly on Domain, Workflow, Plugin, or Runtime components. Everything described in this RFC — intent handling, reasoning, planning, agent coordination, and the Model Gateway — remains internal to the AI Platform Capability.

```text
Application (canonical application/use-case orchestrator)
        │
        │ invokes with Authorized Context
        ▼
AI Platform Capability
        │
        ├── Intent Detection
        ├── Reasoning / Planning
        ├── Agent Coordination
        │        │
        │        ├── Finance AI Agent
        │        ├── Education AI Agent
        │        ├── Documents AI Agent
        │        └── ... (domain-scoped, internal only)
        │
        └── Model Gateway ── provider-neutral ── OpenAI / Claude / other
        │
        ▼
ProposedAction (returned to Application; see companion RFC)
```

## Proposed Design

### Intent Handling

Application, as the canonical application/use-case orchestrator, invokes the AI Platform Capability with a user/family intent and an Authorized Context (see below). The AI Platform Capability does not itself listen to raw user input, events, or unauthorized data sources; it is invoked, not self-triggering.

### Reasoning / Planning Responsibilities

The AI Platform Capability may: understand the request; retrieve relevant information from the Authorized Context; reason about applicable domain concepts; explain its reasoning when required (`AI-Architecture.md`, "Explainable AI"); recommend a course of action; construct a candidate `ProposedAction`. It must not: define or alter business rules; decide autonomously on behalf of the family; access data outside the Authorized Context; assume execution authority over its own output.

### Agent Contracts and Agent Coordination

Domain-scoped agents (Finance, Education, Documents, Health, etc.) are internal decomposition units of the AI Platform Capability. An agent contract should specify, at minimum: the domain scope it reasons about; the subset of the Authorized Context it may read; the capability identifiers (per the existing `PluginCapability`/capability-registry vocabulary in `src/familyos_cli/plugins/capabilities/`) it may reference when constructing a `ProposedAction`; and its non-authority (an agent's output is always a candidate proposal). Agent Coordination is the internal process by which the AI Platform Capability's reasoning/planning layer selects and sequences agents for a given intent — it is explicitly *not* a second orchestration layer; it operates entirely inside the AI Platform Capability. When Agent Coordination produces action-bearing output, that externally visible action-bearing output is a `ProposedAction` returned to Application. Non-action informational reasoning results may return to Application without being represented as a `ProposedAction`, consistent with the two-kind result model in the Architectural Boundary section.

### Authorized Context

AI does not decide what data it may see. Application prepares and hands the AI Platform Capability a pre-authorized context, scoped to the actor, subject, and capability in question, consistent with `Security-Architecture.md`'s "Authorization determines what an identity is allowed to access or perform. Access decisions must follow explicit security policies" and `Identity-Architecture.md`'s "Access decisions should consider: identity; permissions; roles; relationships; security policies." This RFC does not invent a new authorization mechanism to produce this context; it assumes Application obtains it from the Security/Identity components as those integrations are concretely implemented (see companion RFC's "no separate AI approval subsystem" non-goal, and the ADR's point 10).

### Model Gateway / Provider Abstraction

A Model Gateway concept provides provider-neutral access to one or more underlying language models (e.g. OpenAI, Claude). Provider-neutral behavior means: the AI Platform Capability's reasoning/planning/agent-coordination logic must not depend on provider-specific behavior for correctness of its architectural contracts (Authorized Context in, `ProposedAction` out); provider selection, prompt construction, and provider-specific tool-calling formats are gateway-internal implementation details, out of scope for this RFC.

### Evaluation and Observability Requirements

Consistent with `AI-Architecture.md`'s "maintain AI interaction traceability" and "expose AI explanations when appropriate," and with the existing, directly-inspected `RuntimeObservationRecorder` (`src/familyos_cli/plugins/runtime/runtime_context.py`) as an observation pattern that may inform future design, without presuming direct reuse until separately validated: every AI Platform Capability invocation should be traceable through the authorized-context references/evidence it used, the agent/model provenance needed for audit, the explanation or rationale it emitted where appropriate, the result it returned, and any `ProposedAction` it produced. Every `ProposedAction` should carry enough evidence for a human or Application to evaluate it before any authorization decision. Concrete evaluation metrics (accuracy, intent-detection precision, agent-routing correctness) are left to a future, separately-reviewed change once concrete usage exists to measure.

## Explicit Non-Goals and Boundary Protections

- The AI Platform Capability never calls Domain, Workflow, Plugin, or Runtime components directly.
- The AI Platform Capability never bypasses the Authorized Context to fetch its own data.
- Agent Coordination never becomes a second orchestration authority; Application remains the only place a `ProposedAction` can be turned into a real invocation.
- No cross-cutting authorization/permission/`ExecutionContext` primitive is assumed or invented by this RFC; none exists in the current codebase (`src/familyos_cli/plugins/` was inspected directly and confirmed to have no such primitive).
- "AI Orchestrator" remains a rejected role name per the companion ADR; nothing in this RFC's terminology (Intent Detection, Reasoning/Planning, Agent Coordination, Model Gateway) should be read as reintroducing that role under a different name.

## Alternatives Considered

- **A single monolithic AI agent with no domain decomposition.** Rejected as a long-term design: mixing all domain reasoning in one undifferentiated agent makes evaluation, permissioning, and explanation harder as domains grow, and does not map cleanly onto the existing domain-plugin decomposition (Finance, Education, Health, Documents, Communication, Security) already present in the repository.
- **Provider-specific implementation from the start (e.g. a single hard-coded model provider).** Rejected: would violate the Model Gateway's provider-neutral goal and create a hidden coupling the Engineering Constitution's Article IV ("Explicit Dependencies") warns against.
- **Agent Coordination implemented as a peer orchestration layer beside Application.** Rejected per the companion ADR; Agent Coordination is internal to the AI Platform Capability, with a single externally-visible action-bearing `ProposedAction` output when action is proposed.

## Acceptance Criteria

This RFC, if formally accepted (post-C1, following the sequencing decided in the companion ADR), would be considered actionable when it:

- Is accepted through the existing RFC workflow (`docs/rfcs/README.md`).
- Has been reviewed against the final, ratified companion ADR (not this draft).
- Has an accompanying implementation plan that respects Engineering Constitution Article III (no infrastructure built before concrete governed need).

This RFC is Accepted, following the ratified companion `ADR-0014`. Acceptance alone does not make this RFC actionable; an accompanying implementation plan respecting Engineering Constitution Article III remains required, and runtime implementation itself remains a separate, explicitly governed step.

## Future Work

- The companion RFC, "AI Proposed Actions and Workflow Human-Interaction Integration," defines what happens to a `ProposedAction` after the AI Platform Capability returns it to Application.
- A later, separate specification (`docs/06-specifications/SPEC-0016-ProposedAction-Contract.md`) sketches candidate fields for that structure without over-specifying before both RFCs are approved.
- Concrete evaluation/observability tooling is left for a future, evidence-driven change.

## Related Documents

- `docs/adr/ADR-0014-Agentic-AI-Integration.md` (this RFC's governing ADR draft)
- `docs/rfcs/RFC-0018-ai-proposed-actions-workflow-integration/RFC-0018-AI-Proposed-Actions-Workflow-Integration.md`
- `docs/06-specifications/SPEC-0016-ProposedAction-Contract.md`
- `docs/00-foundation/AI-Architecture.md`
- `docs/00-foundation/Security-Architecture.md`
- `docs/00-foundation/Identity-Architecture.md`
- `docs/rfcs/README.md`
- `docs/rfcs/RFC-0002-plugin-sdk-v2/RFC-0002-Plugin-SDK-v2.md` (structural reference)
