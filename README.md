# FamilyOS Pilot 0

Pilot 0 is a small, hand-authored, evidence-gathering product surface for
FamilyOS. It is governed by `ADR-0015 — Pilot 0 Evidence-Gathering Surface
Location` in the `Tcheckvi/FamilyOS` repository and exists outside
`familyos-cli` on purpose: `familyos-cli` remains engineering, generation,
and validation tooling; it is not a running product surface.

Pilot 0's existence does not define FamilyOS's final runtime architecture.
See ADR-0015 for the full boundary of what this decision does and does not
establish.

## Milestones

### M1 — minimal skeleton (synthetic data only) — done

M1 proved the extraction boundary in isolation, against synthetic inputs
only. It never writes a timeline, never confirms anything, and never
performs any external action.

- `src/familyos_pilot0/model_gateway.py` — a provider-neutral
  `ModelGatewayPort` protocol (per RFC-0017's Model Gateway direction) and a
  deterministic `FakeModelGateway` used for tests. No real LLM provider is
  connected.
- `src/familyos_pilot0/extraction.py` — a minimal, pilot-local
  `TimelineEventProposal` result type and an `ExtractionService` that calls
  the gateway and returns a candidate proposal. It never writes, confirms, or
  executes anything.

### M2 — first synthetic end-to-end vertical slice (current)

M2 adds the confirmation/timeline/audit boundary on top of M1's extraction
boundary: `propose()` still never writes; only an explicit, single-use
confirmed decision (`confirm` or `edit`-then-confirm) writes a timeline
entry. `discard` writes nothing.

- `src/familyos_pilot0/identity.py` — minimal `IdentityContext`
  (`family_id`/`member_id`/`subject_person_ref`/`required_approver_refs`).
  Not the eventual Security/Identity architecture; `required_approver_refs`
  is captured on the identity object for a single call only — not
  persisted, not audited, and not enforced, in M2.
- `src/familyos_pilot0/confirmation.py` — `ConfirmationOutcome`
  (`confirm`/`edit`/`discard`), a scoped, single-use, in-memory
  `ConfirmationToken`/`ConfirmationTokenStore`. Not the eventual production
  signed-link design — the minimal local analogue needed to prove the same
  single-use/replay-protected property.
- `src/familyos_pilot0/timeline.py` — `TimelineEntry` and a SQLite-backed
  `TimelineStore` with exactly one write method; `correlation_id` is the
  primary key, so duplicate writes raise rather than overwrite.
- `src/familyos_pilot0/audit.py` — an append-only `AuditTrail` (no
  update/delete method exists). Content-free by design: records event/
  outcome metadata, never proposal content.
- `src/familyos_pilot0/storage.py` — shared `sqlite3` (standard library,
  no ORM/framework) connection/schema setup.
- `src/familyos_pilot0/vertical_slice.py` — `Pilot0VerticalSliceService`,
  the thin orchestrator tying extraction, confirmation, timeline, and audit
  together.
- `tests/test_vertical_slice.py` — confirm, edit-then-confirm, discard,
  replay rejection, duplicate/idempotency, and audit-trail correlation
  tests, all synthetic.

## What this package does not contain

No general workflow engine, no capability registry, no general
authorization subsystem, no provider marketplace, no web app, no real
database framework (SQLite via the standard library only), no deployment
stack, no remote/CI setup, and no import of any `familyos_cli` module. No
multi-approver enforcement (M2 captures `required_approver_refs` on the
identity object only — it is not persisted or audited, and nothing gates
on it). No M3 work (real provider connection, real family onboarding,
production confirmation-link transport).

## Privacy

M1 and M2 use synthetic data only. No external model provider is connected
anywhere in this package, so Privacy Gate A (provider retention/training/
data-location review) remains untriggered. Privacy Gate A must pass before
any later work connects a real provider to anything beyond synthetic/test
data. Privacy Gate B must pass before any real family is onboarded. Neither
gate applies to this package's current scope.
