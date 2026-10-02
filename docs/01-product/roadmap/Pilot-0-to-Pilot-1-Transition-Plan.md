# FamilyOS — Pilot 0 to Pilot 1 Transition Plan

## Status

- Document type: Transition HOW TO
- Version: 1.0
- State: Prepared outside the repository
- Language: English
- Scope: Pilot 0 exit, Pilot 1 entry, and productization readiness
- Repository mutation: Not performed

## Purpose

This document defines the controlled path from the current Pilot 0 state to a
formal Pilot 1 start.

It is a transition plan, not an authorization. Every repository mutation,
deployment, real-data execution, provider use, external-family onboarding, and
release decision remains subject to its own governed authorization.

## Current Known State — 2026-10-02

The following state is treated as the current transition baseline:

- M10 Wave A blocker closure is complete for RD-01, RD-04, RD-05, and RD-06.
- The Operations & Closure Playbook is finalized.
- M10 repository documentation synchronization is locally committed.
- The Pilot 0 M10 lineage is published on the dedicated remote branch
  `pilot0/m10-wave-a-closure-2026-10-02`.
- `origin/main` remains unchanged.
- `M10_REAL_DATA_EXECUTION_AUTHORIZED=false`.

This state closes a governance and evidence milestone. It does not, by itself,
authorize Pilot 1.

## Transition Principle

Pilot 1 SHALL begin only after Pilot 0 has a documented exit review and an
explicit human transition decision.

The transition follows this sequence:

```text
Pilot 0 evidence complete
        |
        v
Pilot 0 Exit Review
        |
        v
Independent readiness review
        |
        v
Human transition decision
        |
        v
Pilot 0 baseline freeze
        |
        v
Pilot 1 architecture baseline
        |
        v
Pilot 1 implementation plan
        |
        v
Pilot 1 controlled start
        |
        v
Productization
```

## Phase 1 — Reconcile Pilot 0

### Objective

Establish one authoritative view of what Pilot 0 actually proved, what remains
open, and what must not be carried forward accidentally.

### Required outputs

- Pilot 0 evidence index.
- Pilot 0 completed-milestone list.
- Remaining open-risk register.
- Deferred-work register.
- Current authorization-boundary summary.
- Current branch and evidence-lineage map.
- Explicit statement of which Pilot 0 mechanisms are provisional.

### Exit criteria

- No unresolved contradiction between closure evidence and current
  documentation.
- No consumed one-shot authority is treated as reusable.
- No historical evidence is silently rewritten.
- Deferred risks have a named destination: Pilot 1, post-pilot hardening, or
  explicitly accepted residual risk.

## Phase 2 — Pilot 0 Exit Review

Use `docs/03-engineering/Pilot-0-Exit-Review-Checklist.md`.

The exit review SHALL answer:

1. What product hypothesis did Pilot 0 test?
2. What user-facing behavior was demonstrated?
3. What safety/governance controls were exercised?
4. What controls were only synthetic?
5. What real-data or external-family claims are supported?
6. What claims are explicitly not supported?
7. Which architecture is temporary?
8. Which contracts should survive into Pilot 1?
9. What evidence supports moving forward?
10. Which risks block Pilot 1?

### Exit decision states

Only these transition states are recommended:

- `NOT_READY`
- `READY_WITH_OPEN_NON_BLOCKING_ITEMS`
- `READY_FOR_PILOT_1_HUMAN_DECISION`

The exit review itself SHALL NOT start Pilot 1.

## Phase 3 — Independent Readiness Review

An independent review should verify:

- Pilot 0 evidence references resolve.
- Closure states are internally consistent.
- Security/privacy gates are not weakened by transition wording.
- No Pilot 0 provisional implementation is silently promoted to platform
  architecture.
- Pilot 1 scope remains bounded.
- All deferred items are traceable.

A second full review is unnecessary unless the first review finds a substantive
risk or the candidate materially changes.

## Phase 4 — Human Pilot 1 Transition Decision

The human decision should bind:

- the exact Pilot 0 exit-review artifact;
- the exact Pilot 0 baseline commit or evidence package;
- the Pilot 1 scope;
- the initial implementation branch;
- explicit non-authorizations;
- any conditions that must remain fail-closed.

No implementation work that crosses an authorization boundary should be
interpreted as implicitly approved by this plan.

## Phase 5 — Freeze the Pilot 0 Baseline

The freeze should preserve:

- final Pilot 0 HEAD / branch reference;
- evidence manifests;
- closure packages;
- exit review;
- transition decision;
- known limitations;
- deferred work.

A freeze is an evidence baseline. It does not require deleting or rewriting the
Pilot 0 repository.

## Phase 6 — Establish the Pilot 1 Architecture Baseline

Use `docs/02-architecture/Pilot-1-Architecture-Readiness.md`.

Pilot 1 should explicitly decide the minimum necessary architecture for:

- identity and authority;
- execution boundaries;
- family/context isolation;
- model/provider interaction;
- observability and audit;
- trusted computing boundary;
- persistence and recovery;
- privacy and consent;
- operational ownership.

These are proposed workstreams, not pre-assigned canonical identifiers. Any
new ADR/RFC/SPEC identifier must be allocated through the authoritative FamilyOS
catalogue before publication.

## Phase 7 — Pilot 1 Scope

Pilot 1 should remain a bounded product-learning phase.

Recommended product principle:

> Preserve the smallest architecture that can safely produce useful,
> repeatable family-facing value.

Do not use Pilot 1 as a reason to implement launch-scale infrastructure unless
Pilot 0 evidence directly justifies it.

## Phase 8 — Pilot 1 Implementation Plan

The implementation plan should define:

- one prioritized product slice;
- entry/exit criteria;
- test strategy;
- rollback/recovery behavior;
- observability;
- consent/privacy boundaries;
- data lifecycle;
- external-provider boundaries;
- operator procedures;
- evidence outputs.

The implementation plan SHALL distinguish:

- product requirement;
- architecture requirement;
- engineering control;
- operational control;
- legal/privacy dependency;
- human authorization gate.

## Phase 9 — Controlled Pilot 1 Start

Before first Pilot 1 execution:

- required CI must be green;
- required privacy/legal prerequisites must be resolved;
- operator procedure must exist;
- secrets must be external to repository;
- family isolation must be testable;
- audit/provenance must be active;
- rollback and deletion/export procedures must be available;
- the exact Pilot 1 execution authorization must be recorded.

## Phase 10 — Productization

Use `docs/01-product/roadmap/Pilot-1-Productization-Plan.md`.

Productization should be evidence-driven and should prioritize:

1. daily utility;
2. reliability;
3. understandable privacy;
4. family-context isolation;
5. repeatable onboarding;
6. maintainable operations;
7. measurable adoption;
8. only then broader intelligence and ecosystem expansion.

## Stop Conditions

Stop and reconcile before proceeding if:

- repository identity differs from the bound baseline;
- a required evidence artifact is missing;
- a branch/history mismatch is discovered;
- a remote has advanced unexpectedly;
- a required legal/privacy decision is absent;
- a one-shot authority is already consumed;
- a new implementation requires an authorization not explicitly granted;
- documentation contradicts current evidence.

## Deliverables Before Pilot 1

The minimum transition package should contain:

- this transition plan;
- Pilot 0 Exit Review Checklist;
- Pilot 1 Architecture Readiness;
- Pilot 1 Launch Gates;
- Pilot 1 Productization Plan;
- Pilot 0 exit-review result;
- independent review result;
- human transition decision;
- frozen evidence manifest.

## Completion Definition

The transition is complete when:

```text
PILOT0_EXIT_REVIEW=PASS
PILOT0_BASELINE_FROZEN=true
PILOT1_ARCHITECTURE_BASELINE=APPROVED
PILOT1_SCOPE_BOUND=true
PILOT1_IMPLEMENTATION_PLAN=APPROVED
PILOT1_START_AUTHORIZED=true
```

Until then:

```text
PILOT1_START_AUTHORIZED=false
```
