# F05 R2C — Synthetic durable MacBook witness candidate

Date: 2026-09-22. Baseline: `00aedffdf7020f2e04598dda7e636c48fa4bbf3f`.
Status: bounded working-tree candidate for independent review, not production approval.

## Authority and topology

The synthetic implementation request and human design binding dated 2026-09-22
authorize this additive implementation. The binding SHA-256 is
`b2d88e985e89f786599b751ecd9f2f1bcfcf8cdf73976f86221b65d4ea20c2c1`.
They select Scope B and a MacBook Pro second-device/LAN witness as the reference
design to develop, not a qualified production authority.

- Mac mini: current runtime/development host.
- 990 PRO: active FamilyOS storage, not its own backup.
- MacBook Pro: reference witness candidate, not a signing service or family-data backup.
- Independent head: current commitment retained outside the covered witness restore domain.
- GitHub: source/history backup only; recoverable family claim/data history needs separate backups.

The supplied binding identifies a 14-inch 2021 M1 Pro MacBook with 16 GB memory
and macOS 27.0. No real MacBook was contacted, configured, enrolled or tested.
All executable tests use temporary synthetic paths, identifiers and data.

Engineering Constitution principles (stable interfaces, evidence, explicit dependencies),
ENG-005, ENG-006, ENG-009 and ENG-012 inform this slice. It preserves existing R2C
protocol/adapter/runtime bytes, the C-1 corrective and M-2 exact-readback behavior.
No additional package dependency is introduced; SQLite is accessed through Python's
standard library. Python 3.13 and SQLite supporting STRICT tables (3.37+) are needed.

## Modules and boundaries

`custody_witness_state.py` supplies strict canonical state validation, immutable
`WitnessHead`, `IndependentWitnessHead` and `HeadContinuity`. A head binds exact
lineage/epoch, witness sequence and a domain-separated digest of the entire state.
It is not a change to the existing claim checkpoint or its digest/generation rules.

`custody_sqlite_witness.py` supplies explicit synthetic enrollment, `SQLiteWitness`
and `SyntheticLoopbackTransport`, implementing the existing exchange interface.
One service owns the database using a lifetime advisory file lock. A finite thread
lock wait serializes exchanges; SQLite's busy wait is zero. Connections use `mode=rw`
so missing databases never bootstrap. Database schema, user version and canonical
state are checked before each exchange, not just at construction.

The equivalent loopback transport is typed and entirely in-process. Trusted fixture
code binds an authenticated peer independently from the request's principal. The
service checks persisted principal rights and exact lineage. This is a test model
of an authenticated boundary, not secure authentication of arbitrary Python callers.
There is no HTTP server, port binding, socket, TLS stack or key material. mTLS fixtures
are deliberately deferred because they are optional for this slice and add no proof
of the central storage/continuity contract. Real LAN mTLS remains a later gate.

## Explicit enrollment and rights

The separate `enroll_synthetic_witness` administrative function requires an explicitly
provided ENROLL test principal bound to the same lineage. It exclusively creates a
new database and returns the exact initial head for separate fake-backend enrollment.
Existing or partially initialized files are never overwritten. Opening a witness
requires the expected StoreIdentity and an already provisioned matching head.

Runtime principals may have only READ, ADVANCE and EXECUTE_ONCE. Enrollment policy
is committed as a canonical set of named principals/rights and fixed policy revision 1.
There is no dynamic policy update, credential rotation, ENROLL or RECOVER_ADMIN API
on the runtime service/transport. RECOVER_ADMIN is modeled separately by the test
administrator but supplies no recovery implementation. Every exposed mutation creates
a committed receipt and advances the sequence/head exactly once. Any future policy
mutation must use the same continuity commitment discipline and a new reviewed contract;
editing persisted rights or revision offline is not supported and fails validation/continuity.

## State and durability

One SQLite STRICT table holds one canonical committed state and an optional staged
candidate. State includes schema version, exact checkpoint, sequence, policy revision,
runtime rights, permanent execution IDs and complete bound COMMITTED receipts.
Receipt session/exchange IDs are normalized to fixed receipt markers; semantic request
content and the idempotency key remain bound. Duplicate advance acknowledges the prior
commit without changing state; changed-content key reuse rejects. An identical execution
receipt returns DUPLICATE, which the existing adapter denies as a new execution grant.
Fresh keys/principals cannot bypass the lineage-wide permanent execution set.

The sequence advances for fence-only changes even when the checkpoint does not.
The schema rejects boolean integers, unknown versions/revisions, extra fields,
duplicate JSON members, noncanonical representations, inconsistent consumption/receipt
sets and duplicate receipt keys. The complete state is bounded to 8 MiB, and normalized
requests to 16 KiB; contract strings also retain their existing bounds. Capacity exhaustion
denies without history pruning, fence expiry or a new lineage. This whole-state representation
and linear receipt lookup suit a bounded synthetic model, not indefinite production throughput.

SQLite uses rollback journal DELETE, synchronous EXTRA and fullfsync enabled. New enrollment
also fsyncs the containing directory; database file creation is exclusive with mode 0600.
Journal and data directories must be trusted local storage under the caller's control.
No portable filesystem test establishes that a path is not cloud/network synchronized:
tests use only disposable local paths, while production mount, ownership, sync exclusion
and storage-flush qualification remain mandatory. Advisory locks assume cooperating code
and protected paths; they do not stop a privileged writer or establish device independence.

## Coupled transition and crash states

All mutation validation, deduplication and exact CAS checks precede staging. Then:

1. Mark the current service instance blocked; begin a SQLite transaction, persist the staged
   full candidate, and commit it durably.
2. Compare-and-set the independent head from the exact old head to the candidate head.
3. In another SQLite transaction, replace committed state with staged state and clear staging.
4. Commit, reload strict state, recheck current independent continuity and only then acknowledge.

The two persistence domains are not one physical transaction. Serialization hides the
intermediate state from granting reads; a stage marker makes uncertain recovery fail closed.
Every exception after the start of this sequence is propagated as AnchorUncertain with its
original cause, including a head backend's definite rejection after local staging. It cannot
be misclassified as a clean client-side rejection that clears C-1 pending evidence.

| Stop/crash point | Durable state and restart result |
|---|---|
| Before staging | Old DB/head intact; reopening may serve the old state. An uncertain client's own marker still blocks its runtime. |
| After staged DB commit, before head | Staged candidate plus old head; reopening denies every request. |
| After head advance, before finalization | Staged candidate plus new head; reopening denies every request. |
| During uncommitted finalization | SQLite rollback retains staged evidence; reopening denies. |
| After final commit, before reply | New DB/head agree; reopening admits reads and bound advance duplicates, but never another grant for an already consumed execution. |

No automatic stage completion, discard, marker deletion, epoch change or repair is implemented.
This sacrifices availability rather than claiming unproved reconciliation. Controlled recovery
will need a separately reviewed administrative design. A service blocked by an injected
postcommit failure must reopen to re-establish evidence; client pending state is never cleared
by that reopen or by an equal read. Runtime tests verify this distinction.

## Fake continuity and structural limit

`tests/custody_sqlite_witness_fixtures.py` supplies a separately stored file-backed fake head,
with expected-current CAS and independent restore control. It survives service subprocess
termination for tests. Its lock is process-local; its storage and independence are not
production-qualified. The source head interface offers read/CAS only, no runtime initialization.

Tests restore DB alone and head alone and demonstrate denial, including a fence-only mutation.
They also deliberately restore both to their authentic old state and demonstrate re-admission:
this is the Scope-C structural limit, not a security success. Two temp files on one machine are
not claimed to be independent devices. Head evidence alone cannot reconstruct lost receipts
or execution history. Witness and family-state recovery need complete matching history backups.

## Boundedness and runtime compatibility

The service starts no worker threads or unbounded queue. Concurrent callers serialize or
time out on the finite admission lock. Existing BoundedAnchorCalls still bounds client waiting
and allows at most one outstanding operation per caller instance; timeout does not cancel
work that may later commit. Tests coordinate late commits deterministically with events.
SQLite I/O and an arbitrary head backend cannot be forcibly time-bounded by this model;
production transports/head storage need their own deadline and resource lifecycle proof.

Runtime integration tests preserve C-1 availability after a definite duplicate fence rejection,
unknown-outcome pending blocks, and M-2 denial when another runtime legitimately advances
the checkpoint after fence acquisition but before exact readback. No native signer is invoked.
The existing claim return is not a portable signing capability; actual signer/worker isolation
and process-snapshot safety are unchanged production obligations.

## Validation and future gates

The new tests cover durable read/advance/restart, exact CAS, idempotency, competing writers,
permanent fencing across principals, independent/correlated restore, abrupt subprocess exit
at five phases for both mutation actions, head/lost replies, late commits, schema/rights
tampering, capacity and service bounds, missing enrollment/head, malformed typed input and
existing-runtime integration. Actual counts and commands are recorded in the Bridge result.

These are process-crash and synthetic restore tests, not power-cut, hardware or real-host tests.
The next deployment gates include exact macOS build, FileVault and recovery paths, trusted
service packaging/account isolation, LAN mTLS identity and revocation, backup/sync exclusions,
real independent head placement/atomicity, sleep/lid/reboot behavior, physical durability,
and governed replacement/reconciliation. No MacBook installation or inspection occurs here.

```text
F05_R2C_PRODUCTION_THREAT_SCOPE=SCOPE_B_WHOLE_MAC
REFERENCE_WITNESS_CANDIDATE=MACBOOK_PRO
CURRENT_RUNTIME_MACHINE=MAC_MINI
FAMILYOS_STORAGE=990_PRO_EXTERNAL
SYNTHETIC_IMPLEMENTATION_ONLY=true
PRODUCTION_EXTERNAL_ANCHOR_SELECTED=false
PROVIDER_SELECTED=false
REAL_MACBOOK_CONFIGURATION_AUTHORIZED=false
REAL_CUSTODY_AUTHORIZED=false
REAL_KEY_ACCESS_AUTHORIZED=false
REAL_SIGNING_AUTHORIZED=false
NATIVE_SIGNING_AUTHORIZED=false
PRODUCTION_REPLAY_STATE_MUTATION_AUTHORIZED=false
COMMIT_AUTHORIZED=false
PUSH_AUTHORIZED=false
```
