# M9 — Pilot0 First Real-Data Slice Execution Authorization Readiness

## Purpose

M9 defines and synthetically validates the exact, auditable, single-use human
authorization contract required before any future first real-data slice
execution.

M9 does **not** transmit real family data, access real email, invoke a provider
API with real data, or perform an external execution.

## One-Item Authorization Request

The future authorization request is bound to exactly one manually selected
source descriptor.

The descriptor contains metadata only and does not carry the selected source
content.

## Adult Consent, Eligibility, and Revocation

The authorization-readiness contract requires bounded evidence identifiers for:

- adult participant confirmation;
- active consent;
- eligibility;
- revocation state.

A revoked participant is denied.

## Minor-Data Screening

Minor-data screening must be complete before authorization readiness can pass.

Detection of minor personal data produces an immediate fail-closed `ABORT`
authorization decision.

M9 does not authorize minor personal-data processing.

## Exact Payload and Provider-Route Binding

The authorization scope binds:

- the canonical minimized payload field names;
- the provider route identifier;
- the pseudonymous participant reference;
- the source type;
- the ephemeral correlation identifier;
- exactly one selected item.

A deterministic SHA-256 scope fingerprint binds those metadata-only values.

No raw selected source content is included in the fingerprint or M9 audit
evidence.

## Read-Only Provider / Project Preflight

M9 requires read-only evidence that the future route is intended to use:

- the dedicated FamilyOS project;
- provider storage disabled;
- hosted tools disabled;
- provider sharing disabled.

Provider configuration mutation is forbidden during M9 readiness work.

## Single-Use Authorization Token

The synthetic token contract binds:

- a human decision reference;
- the exact scope fingerprint;
- issue time;
- expiry time;
- used state;
- revoked state.

The token is fail-closed for:

- expiry;
- replay after use;
- revocation;
- scope mismatch.

A token can be revoked before use.

## Operator Checklist and Pre-Send Boundary

The authorization-readiness contract requires:

- a complete operator checklist;
- acknowledged abort conditions;
- a separate pre-send confirmation boundary;
- refusal of unattended execution.

A successful M9 readiness state has exactly this meaning:

`READY_TO_ISSUE_SINGLE_USE_AUTHORIZATION`

A valid synthetic token has exactly this meaning:

`VALID_FOR_SEPARATE_PRE_SEND_CONFIRMATION`

Neither state authorizes or performs a real-data execution.

## Synthetic Rehearsal

M9 synthetically rehearses:

- authorization readiness;
- denial;
- minor-data abort;
- exact human-scope binding;
- issuance;
- expiry refusal;
- replay refusal;
- revocation-before-use refusal;
- scope-mismatch refusal.

No provider or network call is made.

## Future Execution Gate

Any actual first real-data slice execution requires a separate explicit human
execution authorization after M9 has been independently validated and formally
closed.

M9 closure itself does not authorize that execution.

## Audit Evidence

M9 audit evidence contains bounded metadata, a scope fingerprint, readiness
state, and reasons.

It excludes raw selected source content.

## Closure Boundary

M9 may close only after the authorization request contract, consent/eligibility
binding, minor-data refusal, payload/route binding, provider preflight,
single-use token behavior, operator pre-send boundary, synthetic rehearsals,
quality checks, repository scope reconciliation, and human milestone closure
decision have all passed.
