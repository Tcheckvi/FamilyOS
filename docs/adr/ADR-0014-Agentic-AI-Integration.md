# ADR-0014 — Agentic AI Integration within the Canonical FamilyOS Architecture

## Metadata

| Field | Value |
|---|---|
| Identifier | ADR-0014 |
| Title | Agentic AI Integration within the Canonical FamilyOS Architecture |
| Category | Architecture Decision Record |
| Version | 1.0.0 |
| Status | Accepted |
| Date | 2026-09-18 |
| Authors | FamilyOS Architecture Team |

## Status

Accepted. `ADR-0014` was filed in `docs/adr/` after independent review, and is formally accepted through explicit human acceptance decision. Acceptance fixes the architectural boundaries in the Decision section as durable constraints for RFC-0017, RFC-0018, and future companion RFCs/SPECs. Acceptance does not authorize implementation; runtime implementation remains a separate, explicitly governed step.

## Context

FamilyOS foundation documentation (`docs/00-foundation/AI-Architecture.md`, v1.0, Stable) already establishes AI as a supporting capability of the platform, governed by principles (Human Centered AI, Privacy By Design, Explainable AI, Context Aware Intelligence, Responsible Automation) and explicit exclusions ("AI component shall never: define business rules; replace domain knowledge; make autonomous family decisions; bypass identity or security controls; access unauthorized information; become the source of business truth"). It does not, however, commit to any concrete agentic mechanism (agents, reasoning/planning, model providers, structured proposals).

An independent, evidence-based architecture discovery round (conducted jointly between the project's two AI collaborators — ChatGPT and Claude — and reconciled with the repository owner) has established that the canonical repository already answers most of the boundary questions that would otherwise need to be decided from scratch. This ADR exists to make those already-decided boundaries explicit and durable before any agentic AI mechanism is designed in detail, per `docs/epics/EPIC-ENG-001-engineering-foundation/16-Technical-Governance.md`'s own decision taxonomy: "Architectural Decisions affect system structure. Examples: component boundaries; dependency direction; extension mechanisms. Primary artifact: ADR."

Supporting repository evidence, read directly rather than assumed:

- `docs/00-foundation/Architecture-Map.md`, Dependency Model: `Presentation → Application → Domain`, with `AI` listed as a **Platform Capability**, a peer of `Events, Notifications, Workflows, API, Integrations`. Its "Allowed Dependencies" section (explicitly headed "Allowed examples", i.e. illustrative, not exhaustive) shows exactly one edge for AI: `AI → Authorized Data`.
- `docs/00-foundation/Application-Architecture.md`: "The Application component provides orchestration... Application orchestrates... Future application capabilities should extend this architecture rather than introduce alternative orchestration models."
- `docs/00-foundation/AI-Architecture.md`, Architectural Boundaries diagram: `FamilyOS Knowledge → AI Services → Application Capabilities`.
- `docs/00-foundation/Domain-Architecture.md`: "The Domain is the source of business truth. It does not coordinate application workflows. It does not manage technical execution."
- `docs/00-foundation/Workflow-Architecture.md`, "Human Interaction Support": "Some FamilyOS processes require human decisions... approval steps; validation requests; confirmations; reviews... Human decisions should remain traceable."
- `docs/00-foundation/Security-Architecture.md`: "The Security component communicates with: ... Application for authorization decisions." Authorization is defined as: "Authorization determines what an identity is allowed to access or perform. Access decisions must follow explicit security policies."
- `docs/00-foundation/Identity-Architecture.md`: "Authorization context represents the conditions under which an identity can access FamilyOS capabilities. Access decisions should consider: identity; permissions; roles; relationships; security policies."
- Three ADRs governing the plugin ecosystem independently restate the same orchestration-ownership rule, in a different subsystem: `ADR-0006-plugin-generation-contributions.md` ("The core framework remains responsible for orchestration and execution"); `ADR-0010-Official-Plugin-Domain-Maturity-Review.md` ("The runtime is responsible for orchestration"); `ADR-0013-official-plugin-implementation-strategy.md` (core framework responsibilities include "execute workflows; orchestrate services; manage use cases; coordinate generation operations").

Code-level verification, not merely documentary: `src/familyos_cli/plugins/` was inspected directly. No `execute()`/`invoke()` method exists on any plugin capable of triggering a real business-side effect. No `ExecutionContext` class exists anywhere in `src/`. `PluginCapability` (`capabilities/plugin_capability.py`) is a purely descriptive dataclass (`id`, `display_name`, `description`, `metadata`) used for discovery, not invocation or authorization. `PluginContext` (`plugin_context.py`) carries only generation-time fields (`project_name`, `output_directory`, `plugin_directory`, `variables`). `HookDispatcher` (`runtime/hook_dispatcher.py`) is a minimal, untyped event-to-callback dispatcher with no authorization semantics. `docs/00-foundation/Roadmap.md` places the current platform at "Official Plugins" completed, with "Domain Intelligence" — the phase agentic AI belongs to — explicitly not yet begun ("the platform is now positioned to transition toward Domain Intelligence").

## Problem Statement

Without an explicit architectural decision, future agentic AI implementation work risks:

1. Introducing a second orchestration authority (an "AI Orchestrator") that competes with the Application component's already-canonical orchestration role, reproducing a drift the project has already had to correct once in the plugin ecosystem (ADR-0006, ADR-0010, ADR-0013).
2. Inventing a bespoke AI-specific authorization or approval mechanism, duplicating Workflow's existing Human Interaction Support capability instead of extending it.
3. Assuming a cross-cutting runtime authorization/permission/execution-context system already exists to "reuse," when direct code inspection confirms none does.
4. Leaving the packaging relationship between the AI Platform Capability and the Plugin Architecture ambiguous, causing future agentic AI work to be misclassified as a domain plugin subject to plugin-specific governance (identity, namespace, capability contract rules designed for Finance/Education/Health-style domain extensions) rather than as a platform-level supporting capability.
5. Building agentic infrastructure (agent coordination, model gateway, proposal contracts) before the platform has reached the roadmap phase ("Domain Intelligence") where such infrastructure has a concrete, governed need, in tension with Engineering Constitution Article III, "Evidence Before Abstraction."

## Decision

This ADR fixes the following durable architectural boundaries. It does not authorize any implementation.

1. **AI is, and remains, a Platform Capability** — a peer of Events, Notifications, Workflows, API, and Integrations, per the existing `Architecture-Map.md` categorization. This is confirmed as already decided, not newly introduced by this ADR.
2. **The AI Platform Capability is packaged as a distinct, first-class Platform Capability module — not through the Plugin Architecture.** Rationale: `Architecture-Map.md` already places AI among the Platform Capabilities, structurally separate from the Plugin ecosystem; the Plugin Architecture's governance (`ADR-0007`, `SPEC-0010`, `SPEC-0009`, `SPEC-0012`) is designed for domain-extension plugins (Finance, Education, Health, Documents, Communication, Security, etc.) with their own identity, namespace, and capability-contract rules. Packaging agentic AI as a "plugin" would conflate two structurally different concerns and subject a platform capability to governance rules designed for a different kind of extensibility. This closes the packaging ambiguity named in the discovery round.
3. **Application remains the sole canonical application/use-case orchestration authority. Workflow remains the canonical process-level orchestration mechanism for multi-step, long-running, asynchronous, and human-interaction processes.** No agentic AI mechanism — however sophisticated — introduces an alternative application orchestration model or a competing process-orchestration mechanism. The term **"AI Orchestrator" is explicitly rejected as a FamilyOS architectural role name**, because it would blur the established boundary between Application orchestration and Workflow process orchestration.
4. **Agentic mechanisms (reasoning, planning, agent coordination, model providers) operate entirely inside the AI Platform Capability.** They are internal implementation techniques of AI, not new architectural layers or peers of Application.
5. **AI outputs are proposals, never authority.** Any AI-generated recommendation, plan, or proposed action carries no execution authority by itself. AI output never constitutes authorization.
6. **The AI-to-Application dependency direction is made explicit**, closing the documentary omission identified in the discovery round: `AI-Architecture.md`'s diagram (`AI Services → Application Capabilities`) is confirmed as the intended data/output flow; `Architecture-Map.md`'s "Allowed examples" dependency list should be read as illustrative rather than exhaustive on this point, and a future non-draft revision of `Architecture-Map.md` should add this edge explicitly for completeness. This ADR does not itself edit `Architecture-Map.md`.
7. **Domain remains the sole source of business truth**, including for any standing family policy an AI capability might propose (e.g. a recurring payment rule). AI may propose a candidate policy; only a human, through the appropriate Domain/Workflow mechanism, ratifies it.
8. **Workflow's existing Human Interaction Support mechanism (approval steps, validation requests, confirmations, reviews) is extended for AI-proposed actions, never duplicated by a separate AI-specific approval subsystem.**
9. **AI does not bypass Application, Workflow, Domain, Security, Plugin, or Runtime boundaries under any circumstance**, including for automated or "trusted" workflows; automation is achieved through Workflow-governed deterministic execution of a previously human-ratified policy, never through an AI-held execution privilege.
10. **No cross-cutting runtime authorization, permission, or execution-context system is assumed to exist.** Where this ADR or its follow-on RFCs reference authorization integration, they refer to Security/Identity/Workflow enforcement mechanisms *as they become concretely implemented*, not to a system already present in the codebase today.

## Consequences

- Future RFCs (AI Reasoning/Planning/Agent Coordination; AI Proposed Actions and Workflow Integration) inherit these boundaries as fixed constraints, not open questions.
- No new top-level architectural component is introduced; the AI Platform Capability entry in `Architecture-Map.md` and `AI-Architecture.md` remains the sole home for agentic mechanisms.
- Implementation work that would require a cross-cutting authorization primitive must first surface that need through the normal Security/Identity architecture evolution process, not through an AI-specific shortcut.
- Because `familyos-cli` is currently a code-generation/plugin-scaffolding platform with no general plugin `execute()`/`invoke()` capability, this ADR does not itself unblock or require any runtime implementation; it only fixes the target shape for when the "Domain Intelligence" roadmap phase concretely begins.

## Alternatives Considered

- **"AI Orchestrator" as a new top-level component**, sitting beside or above Application and routing directly to domain agents and plugins. Rejected: conflicts with `Application-Architecture.md`'s exclusive orchestration claim, reproduces a known plugin-ecosystem drift (ADR-0006/0010/0013), and creates two independently evolving centers of "who owns the transaction / authorization / retries / lifecycle / workflow state / canonical event / success" — questions the existing architecture already answers.
- **Packaging AI as an official domain plugin**, subject to `ADR-0007`/`SPEC-0009`/`SPEC-0010`/`SPEC-0012`. Rejected: AI is not a business domain (unlike Finance, Education, Health); it is a supporting platform capability per the existing `Architecture-Map.md` categorization, and plugin-specific governance (capability namespacing, plugin identity/versioning) does not map cleanly onto a cross-domain reasoning capability.
- **Reusing an assumed existing runtime authorization system.** Rejected on the evidence: direct inspection of `src/familyos_cli/plugins/` found no `ExecutionContext`, no cross-cutting permission/authorization primitive, and no privileged-execution mechanism to reuse. Asserting reuse of a non-existent system would misrepresent the current codebase.
- **Building the full agentic stack (agent coordination, model gateway, ProposedAction contract) immediately.** Deferred: no concrete governed need yet exists (the platform has not entered the "Domain Intelligence" roadmap phase), in tension with Engineering Constitution Article III, "Evidence Before Abstraction." Only the governance documents (this ADR, then RFCs) are proposed now.

## References

- `docs/00-foundation/AI-Architecture.md`
- `docs/00-foundation/Application-Architecture.md`
- `docs/00-foundation/Architecture-Map.md`
- `docs/00-foundation/Domain-Architecture.md`
- `docs/00-foundation/Workflow-Architecture.md`
- `docs/00-foundation/Security-Architecture.md`
- `docs/00-foundation/Identity-Architecture.md`
- `docs/00-foundation/Plugin-Architecture.md`
- `docs/00-foundation/Engineering-Constitution.md` (Article III — Evidence Before Abstraction; Article VII — Architectural Governance)
- `docs/00-foundation/Roadmap.md` (current phase; "Domain Intelligence" as next phase)
- `docs/adr/ADR-0006-plugin-generation-contributions.md`
- `docs/adr/ADR-0010-Official-Plugin-Domain-Maturity-Review.md`
- `docs/adr/ADR-0013-official-plugin-implementation-strategy.md`
- `docs/adr/ADR-0007-official-plugin-architecture.md`
- `docs/epics/EPIC-ENG-001-engineering-foundation/16-Technical-Governance.md`
- `src/familyos_cli/plugins/capabilities/plugin_capability.py`
- `src/familyos_cli/plugins/plugin_context.py`
- `src/familyos_cli/plugins/runtime/hook_dispatcher.py`
- Companion drafts: `docs/rfcs/RFC-0017-ai-reasoning-planning-agent-coordination/RFC-0017-AI-Reasoning-Planning-Agent-Coordination.md`, `docs/rfcs/RFC-0018-ai-proposed-actions-workflow-integration/RFC-0018-AI-Proposed-Actions-Workflow-Integration.md`, `docs/06-specifications/SPEC-0016-ProposedAction-Contract.md`

## Tracked Follow-up Action

- **AI-GOV-FOLLOWUP-001 — Architecture Map completeness.** A separate governed change to `Architecture-Map.md` remains required that adds the `AI -> Application` edge explicitly for completeness. This is a sibling follow-up action. It is not inherited by RFC-0017, RFC-0018, or SPEC-0016, and this canonical filing does not authorize that repository change.
