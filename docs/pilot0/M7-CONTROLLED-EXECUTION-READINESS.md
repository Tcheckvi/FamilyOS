# M7 — Pilot0 Controlled Execution Readiness

## Purpose

This runbook describes the fail-closed controlled-execution gate introduced for
M7.

## Required Preconditions

- explicit human authorization;
- active consent;
- no active revocation;
- explicit authorization for every requested sensitive capability.

## Sensitive Capabilities

No sensitive capability is enabled by default. The model separately controls:

- real family data;
- real email;
- provider/network execution;
- unattended external actions.

## Source Selection Boundary

The request carries metadata for exactly one manually selected source item:

- source type;
- ephemeral correlation identifier;
- pseudonymous participant reference.

The gate carries no raw selected text, mailbox content, attachment, thread
history, account-wide history, or contacts.

## Audit Evidence

Audit evidence is bounded to metadata, decision state, and reasons. Raw selected
text is excluded.

## Runtime Boundary

This candidate does not authorize or perform live execution. Real family data,
real email, OpenAI/API execution, pilot-family onboarding, provider
configuration mutation, production credentials, unattended external actions,
push, and remote mutation remain separately governed.

## Mutation Boundary

Repository mutation requires a separate explicit human authorization after the
external candidate has passed independent review.
