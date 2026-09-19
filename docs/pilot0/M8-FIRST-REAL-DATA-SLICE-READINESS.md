# M8 — Pilot0 First Real-Data Slice Readiness

## Purpose

M8 establishes readiness for a future separately authorized first real-data
slice.

M8 does **not** authorize or perform real-data execution.

## One-Item Source Boundary

The readiness contract requires exactly one manually selected source item.

The readiness model carries metadata and payload field names only. It does not
carry the selected source content.

## Adult Consent and Eligibility

The synthetic rehearsal requires:

- adult participant confirmation;
- active consent;
- no active revocation.

## Minor-Data Abort

Detection of minor personal data produces an immediate fail-closed `ABORT`
decision.

No minor personal-data processing is authorized by M8.

## Payload Minimization

The future provider payload is constrained to these canonical field names:

- `source_type`;
- `selected_text_body`;
- optional `event_relevant_timestamp`;
- `pseudonymous_participant_reference`;
- `ephemeral_correlation_identifier`.

M8 validates field names only. No real selected text is processed by the M8
readiness implementation.

## Provider / Project Preflight

M8 synthetically verifies evidence that the future route is intended to use:

- the dedicated FamilyOS project;
- provider storage disabled;
- hosted tools disabled;
- provider sharing disabled.

Provider configuration mutation is forbidden during M8 readiness work.

## Separate Execution Authorization

A successful M8 readiness decision has exactly this meaning:

`READY_FOR_SEPARATE_EXECUTION_AUTHORIZATION`

It does not authorize execution.

A later dedicated human execution authorization is required before any real
family data, real email, external connector execution, provider API execution
with real data, or production credentials may be used.

## Operator Dry Run

The operator dry run verifies:

- the one-item selection boundary;
- adult consent and participant eligibility;
- minor-data abort behavior;
- payload field-name minimization;
- provider/project evidence;
- audit / retention / deletion / revocation evidence;
- the requirement for a separate execution-authorization token.

## Audit Evidence

M8 audit evidence contains bounded metadata, readiness state, and reasons.

It excludes raw selected source content.

## Closure Boundary

M8 may close only after its readiness contract, fail-closed gates, synthetic
allow/deny/abort rehearsal, quality checks, repository scope reconciliation,
and human milestone closure decision have all passed.

M8 closure itself still does not authorize a real-data execution.
