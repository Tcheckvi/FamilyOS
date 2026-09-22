# F05 Runtime R2C — Provider-neutral successor candidate

Date: 2026-09-22
Status: local implementation candidate for independent review; not production approval
Baseline: `eee73f17613c45ab70e134db5c3927d1d066b7d1`

## 1. Scope and authority

The comprehensive writable successor request dated 2026-09-22 authorizes this local candidate. Earlier Claude/Astra reviews supply evidence, not write or production authority. Existing R2A checkpoint types, exact comparison, monotonic advancement and store-first ordering remain. No real witness, provider, credential, key, signing operation or production replay store is configured or contacted.

The Engineering Constitution's evidence-before-abstraction and stable-interface principles, ENG-009 security boundaries, ENG-006 explicit failure and ENG-012 compatibility discipline inform this candidate. This additive document neither rewrites historical approvals nor declares F05 closed.

## 2. Threat and deployment decision matrix

`ProfileBoundary` records an explicit proposed profile, threat scope, trusted domain and recovery domain. It is a declaration to qualify, not proof that the domains are independent. There is no production default profile or selected provider.

| Threat | Eligible first profile | Required trust / unresolved human decision |
|---|---|---|
| External `990 PRO` store rollback; Mac internal state trusted | `PROTECTED_INTERNAL_ANCHOR_PROFILE` | Internal anchor, configuration, exclusive writer and internal restore history remain trusted. The runtime rejects pairing this profile with a whole-Mac guarantee. |
| Whole-Mac rollback/replacement | `INDEPENDENT_SECOND_DEVICE_WITNESS_PROFILE` or `REMOTE_CLOUD_WITNESS_PROFILE` | Latest witness state survives; Mac compromise/recovery credentials cannot rewind or enroll a replacement witness lineage. No second device or cloud vendor is chosen. |
| Witness restore/admin reset, including correlated rollback | Independent profile plus a qualified continuity authority outside the affected restore domain | A surviving authority retains the latest state, including execution consumptions. If all authority is restored together, detection cannot be promised. |

A second family-owned device still needs independent administration and restoration. Cloud remains eligible against the same guarantees. Merely naming two different domains does not establish separation.

## 3. Runtime and anchor interfaces

`custody_anchor_protocol.py` adds immutable request/response bindings, explicit outcomes, profile/authority declarations, a deny-only recovery classifier and `ExecutionFenceAnchor`. `custody_anchor_adapter.py` translates the protocol to the existing `ExternalRollbackAnchor` methods. No field is added to `RollbackCheckpoint`: store identity, epoch, generation and root retain their existing meaning.

`AnchorTransport.exchange` is a qualification seam. Its implementation must authenticate both endpoint and caller, pin the enrolled store and provide linearizable current reads and exact full-tuple CAS. It is not permission to treat arbitrary transport bytes or a client-supplied principal name as authentication. The synthetic service checks requests against its configured authenticated principal; production must enforce the equivalent boundary.

An advance compares the entire expected checkpoint, including identity, epoch and root. Generation-only comparison, stale writers, same-generation/different-root changes and automatic epoch transitions remain rejected. Readback supplements CAS; it never replaces it.

Responses echo the complete request, including protocol version, principal, store identity/epoch, session and fresh exchange ID. The adapter checks the exact binding, outcome type and checkpoint identity. Replayed historical responses fail the binding check. Fresh binding alone cannot make stale server data current: qualified linearizable reads and continuity remain required.

## 4. One-shot execution fencing

`claim_for_signer` still verifies authoritative `KEY_USE_CLAIMED`, durable key intent and the exact signing-request/context digest. It now additionally calls `acquire_execution` under the local lock, passing the exact current checkpoint and a stable execution ID derived from authorization ID and operation ID.

The anchor atomically checks that checkpoint and permanently consumes that execution identity. The consumption is scoped to the enrolled store lineage and shared across clients/principals authorized for that lineage. It does not depend on a caller-selected attempt ID, current claim generation or elapsed time. The first confirmed consumption may return; stale calls, duplicates and uncertain results deny. The runtime also requires exact checkpoint readback before returning.

This is a permanent execution claim, not an expiring lease. There is no release, retry, expiry or reset endpoint. Independent clones with byte-identical local claim files therefore compete against the same authoritative consumption record; only one obtains a return from the signer boundary. Copying a post-intent snapshot does not erase that record. A legacy anchor without the execution extension is denied at the signer boundary; there is no unfenced fallback.

The trusted runtime caller must perform at most one physical execution for a successful boundary return. A returned `ReplayClaim` is not a portable/reusable authorization token, and this candidate does not wire a native signer. Preventing malicious trusted code from bypassing the boundary or reusing its returned object is a deployment/account-isolation obligation. The tests count boundary winners and never invoke any signer.

After a confirmed fence, restart recovery may mark the claim `SPENT_UNKNOWN` through the existing store transition. It never releases the anchor consumption. After an uncertain fence, the local pending marker blocks automatic recovery as well as signing; a pre-fence clone without the marker is still denied by the surviving anchor consumption if the fence committed. If it did not commit, the timed-out caller received no permission, and a different caller can only win through the atomic fence. A late response never grants execution to the abandoned call.

## 5. Uncertainty, idempotency and pending evidence

The protocol distinguishes `COMMITTED`, `REJECTED`, `UNCERTAIN`, `DUPLICATE` and read-only `CURRENT`. Runtime exceptions distinguish `AnchorRejected`, `AnchorUncertain` and `AnchorUnavailable`. Unexpected errors propagate; none is converted to successful authorization.

The public R2A `advance_checkpoint(...) -> None` remains compatible: a normal return means confirmed commitment, and errors deny. The R2C adapter exposes `advance_idempotent` for protocol-level reconciliation/testing. Deduplication binds the authenticated principal, store identity, protocol, action, full expected/candidate checkpoint and execution identity to the supplied key. Fresh exchange/session IDs are excluded from the mutation-content binding so a retransmission can identify the same request. A reused key with changed content rejects. A duplicate identical advance acknowledges the prior committed outcome without another mutation; it conveys no signer permission. Exact current readback still applies, including when another operation has advanced the store since the first request.

For execution consumption, even a duplicate receipt is denied as a new grant. Only a first `COMMITTED` result can return from `acquire_execution`.

The store persists `anchor-pending.json` before sending an anchor mutation. It removes it after confirmed success plus exact readback, or after a definite `AnchorRejected` from the mutation call itself and successful durable cleanup. For ordinary transitions the order is:

1. Verify exact current local/anchor equality under the local lock.
2. Durably write the new local claim store using the existing write pattern.
3. Durably record pending anchor work.
4. Advance the anchor by exact CAS, then read back the exact candidate.
5. Remove the pending marker and sync its directory before returning success.

For signer admission, pending evidence precedes the permanent anchor consumption. The local claim document does not change merely to acquire a fence.

An uncertain/unexpected exception or crash after pending creation leaves deny evidence. A definite mutation rejection clears pending evidence safely and re-raises the original rejection; it grants no execution permission. A readback failure after commitment never uses that cleanup path. A fresh read that later equals the candidate establishes equality only; it does not remove the marker, repeat signing or authorize automatic recovery. A process-local deny latch also remains set after an incomplete mutation. If final marker-removal directory sync fails, the runtime attempts to restore the marker and denies; total storage failure can prevent persistence and remains a deployment durability/recovery limitation.

The marker is deny-only local evidence, not a replacement anti-rollback authority. Rewinding both marker and claim file does not rewind a qualified anchor or its consumption records. The marker format does not change checkpoint bytes; it has no public clear/repair API. Low-level private helpers are internal implementation, not operator recovery interfaces.

## 6. Lock scope, bounded waiting and cancellation

The candidate deliberately retains the local critical section around admission, store write, anchor advance and readback. Moving these calls out without a durable reservation protocol would create a conflicting-writer window.

Local lock acquisition uses nonblocking `flock` with a finite monotonic wait budget. Every runtime anchor call goes through `BoundedAnchorCalls`, which limits waiting and permits only one outstanding call per runtime instance. It starts no further queued work while an earlier call remains outstanding.

The defaults are five seconds for each anchor call and five seconds to acquire the local lock; tests use short explicit budgets. A normal mutating store operation makes at most four sequential anchor calls; signer admission makes three. These are bounds on waiting for anchor results, not a hard real-time bound on all filesystem, scheduler or native code execution. Local disk hangs and OS scheduling require deployment qualification.

A daemon thread may outlive a timeout: Python does not safely cancel arbitrary running code. It holds immutable anchor request data, no local claim-store lock/file handle and no signer callback. The caller releases its local lock on timeout; the pending marker and exact CAS handle any later mutation conservatively. A late result is never delivered as signer permission. A real transport must additionally implement and qualify its own deadline/cancellation/resource cleanup. Repeatedly creating arbitrary runtime instances is not a qualified worker lifecycle; the per-instance guard is not a host-wide admission service.

Unrelated operations can acquire the local lock after the bounded wait. If an anchor mutation is pending, they are denied rather than waiting indefinitely or mutating an uncertain lineage. Definite rejection clears this pending block; independent store/anchor mismatch checks still apply. `export_diagnostics` does not acquire the custody lock or contact the anchor. It returns only a file digest, pending indicator and `authoritative=false`; its per-file observations are not a transactional snapshot or freshness proof.

## 7. Witness continuity, credentials and administration

`WitnessContinuity.require_current(response)` is the narrow non-regression seam. It must consult/protect latest state outside the restore domain at issue. The evidence covers checkpoint, permanent execution records and committed idempotency state. Detecting only checkpoint regression would miss a restored execution tombstone when the checkpoint itself did not change.

No generic witness revision is added to the store contract. A concrete service may use a revision, hardware state, independently retained head or another qualified mechanism. It must define protected ownership, restoration, reset and atomicity semantics. A revision or signed head restored together with its database is not independent evidence.

Independent-device/cloud adapters require an explicit continuity implementation; the narrower trusted-internal profile permits none because its internal authority is an explicit trust assumption. Supplying a Python object or a profile name is not a production proof. This candidate has no production continuity implementation.

The synthetic service models one atomic lock-protected transaction across checkpoint, permanent fences, receipts and a separately retained head. Backups intentionally omit that head. The test suite both detects isolated witness restore and demonstrates the structural failure if the head, witness and store are all restored together. That positive regrant in the deliberately invalid correlated model is a limitation demonstration, not a passing security guarantee. Real atomicity across independently retained authority must be separately designed and qualified.

`AnchorRight` distinguishes read, advance, execute-once, enrollment and recovery/admin authority. Runtime requests expose only the first three; neither the adapter nor runtime offers provisioning/reset/recovery mutation endpoints. A production transport must bind authenticated callers to enrolled stores and keep credential rotation/admin recovery outside ordinary advance authority. No RD-01 key is used as an authenticator and no concrete credential is provisioned.

## 8. Operator recovery matrix

`classify_recovery` is pure and deny-only. Every state name makes its non-authorizing role explicit. Its input flags are evidence supplied by a separately governed operator investigation, not a human assertion accepted by custody runtime.

| Evidence | Classification / operator posture |
|---|---|
| Exact equality, no unresolved exchange | `EXACT_NO_EXECUTION_AUTHORITY`: equality alone grants nothing; normal validated runtime transitions and one-shot fence remain mandatory. |
| Response lost; fresh exact candidate later observed | `EXACT_AFTER_UNCERTAINTY_BLOCKED`: retain evidence and pending marker; do not retry the signer or clear the marker. |
| Local store ahead, witness old | `LOCAL_AHEAD_BLOCKED`: stop; do not advance the witness to match or rewind the store. |
| Witness ahead, local store old | `LOCAL_ROLLBACK_BLOCKED`: stop; a digest cannot reconstruct missing claim history. |
| Equal generation, different root | `DIVERGENCE_BLOCKED`: preserve both observations and investigate. |
| Wrong store identity | `WRONG_LINEAGE_BLOCKED`: investigate enrollment/configuration; no automatic replacement lineage. |
| Anchor unavailable | `UNAVAILABLE_BLOCKED`: permit only non-authoritative diagnostics/evidence export. |
| Latest history irretrievably lost | `HISTORY_LOST_PERMANENTLY_BLOCKED`: keep the affected lineage blocked; retirement/revocation/replacement requires a separate design preventing reuse of old authorizations. |

Operator sequence: stop custody activity; preserve diagnostic/file evidence; identify the enrolled lineage and trusted surviving authority; classify the observed mismatch/uncertainty; seek separately authorized recovery review. Do not edit JSON, delete pending markers, restore both sides until they match, switch endpoints, increment an epoch or re-enroll an empty store as a shortcut. A manual reconciliation implementation is deliberately absent until the required trustworthy recovery evidence and human policy are selected.

If all latest history is lost, human approval cannot reconstruct it. This candidate encodes permanent blocking rather than inventing a recovery claim. Existing automatic `recover_after_restart` can only consume in-flight claims when authoritative equality exists and no pending mutation remains; it is not anchor reconciliation.

## 9. Generation, schema and persisted compatibility

The v1 root still hashes the same domain, store identity/epoch and exact canonical JSON document using sorted keys, compact separators and ASCII escaping. The historical absent-store `{}` checkpoint remains unchanged. Valid v1 records keep the same scalar `sum(claim_generation + 1)` and root bytes; no automatic epoch or digest-domain migration occurs.

R2C validates the complete envelope and every claim, including unrelated records and claim-key/identity binding, before counting only the top-level claims. Duplicate JSON members, non-finite constants, boolean versions, extra envelope metadata, malformed unrelated claims and nested generation tricks deny. No field is silently stripped or normalized to recover equality. Equal scalar generations can represent different histories; exact root comparison remains mandatory, and the witness cannot infer legal claim transitions from the scalar or digest alone.

Compatibility is deliberately tightened for documents older readers tolerated but the v1 writer never emitted: incomplete envelopes, arbitrary metadata and malformed unrelated claims are now denied. This is an explicit admission change, not a new interpretation of their old checkpoint. Preserve such data for separate recovery/migration review; do not edit it in place or recompute its anchor silently. A future metadata schema must define its own governed compatible/versioned transition. Existing synthetic tests using partial fake records were replaced with valid v1 fixtures; tampering still denies, now at schema validation before digest comparison.

## 10. Durability and availability limits

Local file/directory `fsync`, atomic replacement and pending-marker synchronization provide the implemented software ordering. Synthetic injected failures demonstrate control flow, not every APFS/external-device power-loss guarantee. Native storage cache flushing, device firmware behavior and account/path isolation need separate qualification. The trusted filesystem/root must prevent hostile mutation of claims, lock file and marker; advisory locks do not defend against arbitrary privileged writers.

The synthetic witness defines committed as its completed lock-protected in-memory transaction. Its restore snapshots and retained head are test models, not disk durability. No production service may advertise that model as crash-qualified persistence.

During outage, only non-authoritative diagnostics are available. Cached checkpoints, timestamps, operator assertions, old signed receipts, silent single-anchor fallback and emergency signing bypasses remain forbidden. Losing availability after an uncertain mutation is deliberate.

## 11. Independent review and remaining decisions

Review the exact diff and tests, especially the permanent fence, uncertainty marker lifecycle, timeout late-commit behavior and valid-v1 compatibility. Deployment threat scope, real continuity mechanism, transport authentication and deadlines, credential custody, restore/reprovisioning policy and physical durability remain unresolved production gates. No real anchor is implemented or selected. No native signing integration or real-key validation is claimed.

```text
IMPLEMENTATION_AUTHORIZED_FOR_THIS_LOCAL_CANDIDATE=true
PRODUCTION_EXTERNAL_ANCHOR_SELECTED=false
PROVIDER_SELECTED=false
REAL_CUSTODY_AUTHORIZED=false
REAL_KEY_ACCESS_AUTHORIZED=false
REAL_SIGNING_AUTHORIZED=false
NATIVE_SIGNING_AUTHORIZED=false
PRODUCTION_REPLAY_STATE_MUTATION_AUTHORIZED=false
PUSH_AUTHORIZED=false
```

## 12. Targeted C-1 correction and M-2 concurrency cost

The 2026-09-22 corrective candidate distinguishes definite mutation rejection from
unknown outcome in one shared runtime helper used by execution-fence acquisition
and ordinary checkpoint advancement. It catches only `AnchorRejected` around the
mutation call, durably clears the pending marker/latch, and re-raises that same
exception. Successful calls retain the existing exact readback and completion path.
Readback is deliberately outside the rejection handler. An `AnchorRejected` raised
by the final read is not evidence that the preceding mutation did not commit.
`AnchorUncertain`, timeout, mismatch and unexpected errors leave pending state intact.
If cleanup itself fails, `RecoveryRequired` and deny evidence remain; clean rejection
is not falsely reported as safely completed cleanup.

A duplicate fence rejection leaves the checkpoint unchanged. An unrelated claim can
therefore proceed after cleanup, while the original execution identity stays consumed.
For ordinary advancement, the durable local write precedes the anchor request. A
rejected advance leaves the local store ahead of the unchanged anchor. Clearing the
pending marker does not undo that write or make the checkpoints equal: subsequent
mutations still deny with the existing rollback/lag error, not an artificial pending
latch. T2 exercises reserve, key-use intent and terminal recording and preserves this
necessary distinction. A complementary T2 test lets another competing synthetic runtime
commit the identical candidate first: the stale caller receives its unchanged rejection,
cleans pending state, and can then reserve an unrelated claim because exact equality
already exists. Only the other caller committed; no rejected call is reclassified as
success and no state is repaired. Unconditionally allowing another claim while local
state remains ahead would require forbidden repair/rewind or a new protocol, which
this correction does not add.

M-2 is an intentional fail-closed concurrency cost. After the execution fence succeeds,
a different clone may legitimately advance the shared anchor for an unrelated claim
before the first caller's final readback. That caller still compares against its exact
pre-fence local checkpoint and denies; it does not accept a later generation. Its
execution identity remains consumed and its pending state remains active. The other
clone's legitimate operation can succeed. A deterministic test interleaves these steps
and proves both outcomes. A safe alternative would need separate protocol design and
is outside this corrective request.
