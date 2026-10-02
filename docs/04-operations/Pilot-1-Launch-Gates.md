# FamilyOS — Pilot 1 Launch Gates

## Status

- Version: 1.0
- State: Proposed operational gate set

## Gate P1-01 — Transition Authority

PASS requires:

- Pilot 0 exit review completed;
- Pilot 0 baseline frozen;
- human Pilot 1 transition decision recorded.

## Gate P1-02 — Repository Identity

PASS requires:

- intended implementation repository identified;
- branch identity verified;
- no ambiguous unrelated-history target;
- clean or explicitly accounted working-tree state.

## Gate P1-03 — Architecture Baseline

PASS requires all architecture-readiness workstreams to have an approved
baseline or an explicit non-blocking disposition.

## Gate P1-04 — Security / Privacy Preconditions

PASS requires:

- family/context isolation control;
- consent prerequisites;
- provider-data minimization;
- secrets outside repository;
- audit/logging policy;
- deletion/export procedure.

## Gate P1-05 — Engineering Quality

PASS requires the applicable repository quality profile to be green:

- Ruff;
- MyPy;
- Pytest;
- repository-specific validation;
- documentation validation;
- diff check.

## Gate P1-06 — Operations

PASS requires:

- operator runbook;
- failure/retry policy;
- backup/restore where persistence exists;
- stop conditions;
- incident path.

## Gate P1-07 — External Dependencies

PASS requires:

- exact external dependencies identified;
- provider/project/model bindings where applicable;
- fallback behavior;
- no hidden production credential dependency.

## Gate P1-08 — Human Start Decision

No Pilot 1 execution should begin until an explicit human decision binds the
exact candidate baseline.

## Global Stop Conditions

Any of the following forces `NOT_READY`:

- repository identity mismatch;
- unresolved family-isolation defect;
- absent required consent/privacy artifact;
- stale or contradictory evidence;
- unauthorized network/provider action;
- missing rollback or deletion path for persisted real data;
- scope expansion not covered by the transition decision.
