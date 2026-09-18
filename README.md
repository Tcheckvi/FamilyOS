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

### M2 — first synthetic end-to-end vertical slice — done

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

### M3 — first real Model Gateway provider, synthetic-only (current)

M3 adds the first real (non-fake) `ModelGatewayPort` implementation, behind
Privacy Gate A, with synthetic data only. It does not touch M2's
confirmation/timeline/audit boundary at all -- only the extraction step
gains a second, real gateway option alongside `FakeModelGateway`.

- `src/familyos_pilot0/openai_gateway.py` — `OpenAIModelGateway`, calling
  the official OpenAI Python SDK's Responses API with Structured Outputs
  (strict JSON schema, manually written -- not a pydantic model, to keep
  this module's own public surface small even though `openai` already
  depends on pydantic transitively). Uses `store=False` explicitly, no
  hosted tools (no function calling, web search, or file search), an
  explicit timeout, and the SDK's own bounded retry behavior for
  transport/rate-limit/server failures (no hand-rolled retry loop).
  Provider/parse/refusal/timeout failures convert to typed
  `ModelGatewayError` subclasses (`errors.py`); this module never falls
  back to `FakeModelGateway` and never logs prompt or model output content.
- `src/familyos_pilot0/errors.py` — extended with `ModelGatewayError` and
  four subclasses (`ModelGatewayTimeoutError`, `ModelGatewayRefusalError`,
  `ModelGatewayResponseParseError`, `ModelGatewayProviderError`).
- `tests/test_openai_gateway.py` — provider contract tests against a
  fake/stub OpenAI client (no network): successful mapping, `store=false`
  and strict-schema request shape, no hosted tools, refusal handling,
  malformed/missing output, timeout, and other provider errors.
- `tests/live_smoke/test_openai_live_smoke.py` — a single, **opt-in,
  disabled-by-default** live-call test. Skipped automatically unless both
  `FAMILYOS_PILOT0_ALLOW_LIVE_OPENAI_SYNTHETIC=1` and `OPENAI_API_KEY` are
  present, and even then sends only a hard-coded synthetic fixture, never
  arbitrary input.

## What this package does not contain

No general workflow engine, no capability registry, no general
authorization subsystem, no provider marketplace, no web app, no real
database framework (SQLite via the standard library only), no deployment
stack, no remote/CI setup, and no import of any `familyos_cli` module. No
multi-approver enforcement (M2 captures `required_approver_refs` on the
identity object only — it is not persisted or audited, and nothing gates
on it). No hosted OpenAI tools, no prompt/output logging, no real family
data, no real family onboarding, no production confirmation-link transport,
no M4 work.

## Privacy

M1 and M2 use synthetic data only and connect no external provider. M3
introduces the first real provider connection (OpenAI), still
synthetic-data-only under Privacy Gate A: `store=False` is always passed,
no hosted tools are enabled, and no prompt/output content is logged.
Privacy Gate A's current assessment is `PASS_FOR_SYNTHETIC_ONLY_PENDING_
ACCOUNT_CONFIGURATION_CHECK` -- see the M3 package review document for the
independently-verified facts behind that assessment. Privacy Gate B (real
family data, real onboarding) remains blocked and is not addressed by any
file in this package.
