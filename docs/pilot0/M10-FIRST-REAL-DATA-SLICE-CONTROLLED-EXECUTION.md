# Pilot 0 — M10 First Real-Data Slice Controlled Execution

## Status

This document defines the synthetic M10 controlled-execution contract of the current external hardening candidate.

Repository hardening mutation, commit, push, real family data, real email,
provider/API transmission, provider configuration mutation, production
credentials, minor-data processing, onboarding and unattended external
execution remain separately gated.

## Exact Execution-Instance Binding

M10 uses HMAC-SHA256 over a deterministic ASCII JSON document.

The canonical document binds:

- M10 contract version;
- M9 scope fingerprint;
- exact M9 consent evidence identifier;
- exact M9 eligibility evidence identifier;
- exact M9 minor-screening evidence identifier;
- M9 authorization identifier;
- M9 human-decision reference;
- M9 token scope;
- M9 token issuance/expiry and used/revoked state;
- exact payload field names and values;
- final screening evidence identifier and flags;
- exact provider route;
- provider preflight state;
- provider configuration-mutation state.

A fresh `EphemeralScopeBindingKey` is generated from the system CSPRNG. A key
object is single-scope: repeated signing of the identical execution document is
allowed for readiness re-evaluation, while use against another execution
document is refused.

Payload strings containing Unicode surrogate code points are rejected before
storage. This prevents a Python surrogate-pair string from canonicalizing to
the same ASCII JSON bytes as the corresponding single Unicode scalar value.

Only the preparation owner destroys the key on exit; losing claimants leave it intact. Python
cannot prove physical memory erasure. Tracebacks, process memory, debuggers or
hostile in-process code can still expose values. Therefore the correct
guarantee is limited to designated synthetic surfaces, not general
non-persistence.

## Runtime Validation

M10 rejects malformed aggregate and nested M9 objects before dereferencing
their fields.

Security-relevant booleans, integers, identifiers, token timestamps and payload
entries require exact canonical runtime types. Governed integers are limited to
the non-negative signed-64-bit range to avoid unbounded JSON-integer failures.

`ExecutionPayload` requires an exact immutable outer tuple and immutable
two-item tuple entries. After construction, ordinary assignment, deletion and
repeated initialization are refused.

This prevents retained-container mutation, payload reinitialization after
approval, truthy strings such as `"false"`, NaN timestamps and oversized
integer serialization from bypassing the governed boundary.

## Payload / Accidental Serialization Boundary

`ExecutionPayload` is intentionally not a dataclass. `dataclasses.asdict()` on
the request/envelope therefore does not recursively turn raw payload into a
plain JSON-ready dictionary.

Raw payload remains explicitly retrievable through `ExecutionPayload.as_dict()`
because a later separately authorized provider boundary would need it. This is
an intentional capability and must not be logged or persisted.

## Minor-Data Boundary

Detected minor data returns `ABORT`.

Screening uncertainty returns `ABORT`.

Incomplete final screening returns `DENY`.

M10 never authorizes minor personal-data processing.

## Provider Boundary

The exact provider route must match the M9 scope.

Read-only provider preflight must be complete.

Provider-configuration mutation is denied.

Exact provider project/model/credential binding is still a future real-data
gate requirement because the present M9 model does not carry all of those
runtime identities.

## Single-Use Boundary

The synthetic ledger is thread-safe per ledger instance. The synthetic
submission recorder validates its input before changing recorder state and is
also thread-safe for valid envelopes.

A scope-binding key is a single-preparation-owner capability. Preparation
claims ownership atomically before entering its cleanup block. Competing
preparation calls using the same key are governed refusals and cannot destroy
the winning caller's key. The owner destroys the key on every preparation
exit. This provides deterministic fail-closed ownership semantics; it does not
create an at-least-once delivery guarantee.

This is not durable authorization state. A different ledger instance/process
can replay the same immutable token.

A future real-data gate must use a durable atomic compare-and-set reservation,
submission and terminal-consumption/void model across process/machine
boundaries.

## Human Authorization Boundary

`HumanPreSendExecutionAuthorization` is caller-provided evidence binding only.

It does not prove trusted human identity.

A Python boolean, object construction or terminal/TTY interaction is not a
trusted identity proof.

Future real-data execution requires an external trusted human-authorization
receipt/verifier.

## Trusted Time and Freshness

M10 rejects future-issued authorization tokens.

A future real-data gate must still provide a trusted execution-time source and
explicit maximum-age/freshness policy for final screening evidence.

## Scanner / Test Isolation

Repository preparation scanners and Python socket shims are defense-in-depth
verification controls. The scanner catches the specific indirect examples
reviewed in this cycle, including direct `__builtins__["__import__"]`,
attribute-mediated `module.__builtins__`, governed `getattr(...,
"__builtins__")` forms, and explicit `sys.modules` access. Neither the scanner
nor the Python socket shim is a security sandbox.

Future real-data execution requires OS/process-level egress isolation and
independently reviewed execution containment.

## Future Real-Execution Requirements

Before any provider transmission can be authorized, a separate governed stage
must provide at minimum:

- trusted human authorization receipt/verifier;
- durable atomic cross-process authorization state;
- explicit reserve/submit/consume-or-void semantics;
- trusted execution-time source;
- final-screening freshness policy;
- exact provider project/model/credential binding;
- OS/process-level network isolation;
- controlled traceback/log policy;
- independently reviewed retention/deletion/revocation evidence;
- independent review of the final real-execution design.

Until that stage is explicitly authorized:

`M10_REAL_DATA_EXECUTION_AUTHORIZED=false`
