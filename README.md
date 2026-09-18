# FamilyOS Pilot 0

Pilot 0 is a small, hand-authored, evidence-gathering product surface for
FamilyOS. It is governed by `ADR-0015 — Pilot 0 Evidence-Gathering Surface
Location` in the `Tcheckvi/FamilyOS` repository and exists outside
`familyos-cli` on purpose: `familyos-cli` remains engineering, generation,
and validation tooling; it is not a running product surface.

Pilot 0's existence does not define FamilyOS's final runtime architecture.
See ADR-0015 for the full boundary of what this decision does and does not
establish.

## Current milestone: M1 — minimal skeleton (synthetic data only)

M1 proves the extraction boundary in isolation, against synthetic inputs
only. It does not write a timeline, does not confirm anything, and does not
perform any external action.

The full first vertical slice (forwarded email -> extraction -> human
confirmation -> timeline entry) is M2, not M1.

## What M1 contains

- `src/familyos_pilot0/model_gateway.py` — a provider-neutral
  `ModelGatewayPort` protocol (per RFC-0017's Model Gateway direction) and a
  deterministic `FakeModelGateway` used for tests. No real LLM provider is
  connected in M1.
- `src/familyos_pilot0/extraction.py` — a minimal, pilot-local
  `TimelineEventProposal` result type and an `ExtractionService` that calls
  the gateway and returns a candidate proposal. It never writes, confirms, or
  executes anything.
- `tests/fixtures.py` — synthetic message fixtures only. No real names,
  emails, addresses, or real family data.
- `tests/test_extraction.py`, `tests/test_boundaries.py` — tests for
  extraction behavior and for the no-side-effect / no-`familyos-cli`-import
  boundaries.

## What M1 does not contain

No workflow engine, no capability registry, no authorization subsystem, no
provider marketplace, no web app, no database, no deployment stack, and no
import of any `familyos_cli` module.

## Privacy

M1 uses synthetic data only. No external model provider is connected, so
Privacy Gate A (provider retention/training/data-location review) remains
untriggered for M1. Privacy Gate A must pass before any later work connects
a real provider to anything beyond synthetic/test data. Privacy Gate B must
pass before any real family is onboarded. Neither gate is relevant to M1's
own scope.
