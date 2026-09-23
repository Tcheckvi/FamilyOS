# F05 R2C — Synthetic LAN mTLS transport and USB continuity head

Date: 2026-09-23. Canonical baseline:
`e52b9746f4b8334aa49fe79374ba80e13d931c2d`.

Status: bounded implementation candidate for independent review. It is not a
production external-anchor selection, deployment authorization, or security
qualification.

## Scope and topology

The human-selected threat boundary remains Scope B, whole-Mac rollback. The
reference profile remains a second-device LAN witness on the qualified MacBook
Pro, with the Mac mini as runtime and the 990 PRO as active FamilyOS storage.
This tranche adds two synthetic boundaries behind the committed R2C contracts:

1. a TLS 1.3 mutual-authentication client/server transport for the existing
   `AnchorTransport.exchange` and `SQLiteWitness.exchange_for_peer` path; and
2. a removable-media `IndependentWitnessHead` candidate with durable exact CAS.

The head path has no default. Trusted synthetic deployment code must supply an
absolute path on the intended USB volume and the observed containing-device
identifier. Missing paths and device changes deny. There is no fallback to a
MacBook-internal path. GitHub, Time Machine, iCloud, Dropbox, OneDrive and source
backup are not continuity authorities. The removable head is separate from the
MacBook restore domain and from family-data backup.

No certificate, key, IP address, USB identifier or real data is embedded in the
source. Automated tests generate disposable certificates and state under pytest
temporary directories. No real MacBook service, launchd unit, firewall rule,
power setting, USB enrollment, custody key or signer is touched.

## Authentication boundary

`custody_mtls_transport.py` uses Python standard-library sockets and TLS. Server
and client contexts require TLS 1.3 as their minimum. The server requires a client
certificate and validates it against an explicitly supplied CA. The client validates
the server CA and hostname and additionally requires the exact SHA-256 fingerprint
of the expected server leaf certificate.

After the TLS layer validates the client certificate, the server hashes its DER
leaf certificate and looks up that exact fingerprint in an explicit map to an
already-enrolled runtime principal. Certificate CN text and request content do not
select the authenticated identity. The server supplies the mapped identity to
`SQLiteWitness.exchange_for_peer`; a different request principal is rejected.
An otherwise CA-valid but unpinned leaf is rejected. There is no first-connection
learning and no trust-on-first-use path.

Each connection carries one length-prefixed request and one response. The maximum
frame is 32 KiB. Socket accept, TLS handshake, read and write operations use explicit
deadlines. Requests and responses are versioned canonical ASCII JSON with exact
field sets. Missing, extra, duplicate, noncanonical, malformed, invalid-enum and
oversized representations deny. Python pickle or executable deserialization is
not used.

The wire request binds protocol version, action, principal, store identity/epoch,
session ID, request ID, expected checkpoint, candidate checkpoint, idempotency key
and execution ID. A response includes the complete request, outcome, checkpoint and
continuity evidence. The client rejects a response not bound to its exact request.
Only READ, ADVANCE and EXECUTE_ONCE exist in the runtime protocol. The server exposes
no enrollment, recovery, reset, policy, key-management or signing endpoint.

If TLS or connectivity fails before a request can be exposed, the transport is
unavailable. Once a mutating request may have been exposed, loss or malformation of
its response becomes `AnchorUncertain`; it is never represented as definite
non-commit. Typed server errors preserve `AnchorRejected`, `AnchorUnavailable` and
`AnchorUncertain`. The existing adapter remains responsible for conservatively
mapping a mutation-side unavailable response into uncertainty for its caller.

## USB head durability and CAS

`custody_usb_witness_head.py` preserves the committed `IndependentWitnessHead`
contract. Synthetic enrollment is a separate administrative function requiring an
ENROLL principal in the same lineage. It uses exclusive creation and refuses any
overwrite. Runtime construction requires pre-existing valid canonical state and the
exact expected `StoreIdentity`; it never bootstraps or learns a first value.

The canonical head contains the domain, exact store identity/epoch, sequence and
full witness-state digest. Reads reject empty, malformed, duplicate-member,
extra-field, noncanonical, wrong-lineage, symlinked, nonregular, over-permissive or
wrong-device state. The directory and opened file are checked through descriptors;
the file descriptor and directory entry must identify the same inode. These checks
assume a protected host path and do not defeat a privileged writer.

CAS takes a bounded process-local lock and a bounded nonblocking advisory lock file,
then rereads the authoritative head. It accepts only a full exact expected-head
match and a candidate in the same lineage with sequence exactly one greater. It
writes canonical bytes to a fresh same-directory file with mode 0600, fsyncs that
file, atomically replaces the authoritative name, fsyncs the containing directory,
and rereads the candidate before returning.

A failure injected before the replace leaves the old head authoritative and returns
unavailable. The implementation marks commitment as possible immediately before
calling replace. Any exception from that point through directory fsync and final
reread returns `AnchorUncertain`, because durable replacement may already have
occurred. The enclosing SQLite witness already stages its full candidate before head
CAS and converts all subsequent failure into mutation uncertainty. On restart, a
remaining SQLite stage marker denies all authority; no automatic completion,
discard, reset, repair or epoch transition exists.

The USB head is itself the retained authority. A valid old USB-head file restored
without any higher independent authority cannot announce that it is old. Exact CAS
detects replacement relative to the caller's expected current head, and the witness
detects mismatch between its database and head. Correlated restoration of both
continues to be the documented structural limit. Production claims require a
separate recovery-domain analysis and operational controls.

## Tests and qualification boundary

The additive tests cover CA validation, client-certificate requirement, exact client
and server leaf pins, hostname validation, principal binding independent from the
request, unknown peers, canonical framing, malformed/oversized/truncated/stalled
connections, response loss for mutations, absence of admin actions, and positive
READ/ADVANCE/EXECUTE_ONCE behavior. Integration uses the real committed
`SQLiteWitness`, the new USB head and the mTLS boundary, including restart,
permanent execution consumption, head mismatch and staged uncertainty.

USB tests cover explicit one-time enrollment, permissions, exact read/CAS, stale and
wrong-lineage rejection, corruption, symlinks, absent paths, device mismatch,
interprocess lock contention, observable temporary-file replacement, file fsync,
directory fsync, failures before and after replace, and restart persistence.

Loopback TLS tests establish protocol behavior only. They do not qualify LAN routing,
firewall state, sleep/lid behavior, certificate storage or revocation, service account
isolation, launchd packaging, hardware power-loss durability, USB volume identity
across reboot, mount ownership, production encryption or recovery ceremonies. The
current USB medium is unencrypted for this synthetic phase. Those gates remain closed.

```text
F05_R2C_PRODUCTION_THREAT_SCOPE=SCOPE_B_WHOLE_MAC
REFERENCE_WITNESS_PROFILE=SECOND_DEVICE_LAN_WITNESS
REFERENCE_WITNESS_CANDIDATE=MACBOOK_PRO
CURRENT_RUNTIME_MACHINE=MAC_MINI
FAMILYOS_STORAGE=990_PRO_EXTERNAL
SYNTHETIC_IMPLEMENTATION_ONLY=true
PRODUCTION_EXTERNAL_ANCHOR_SELECTED=false
REAL_MACBOOK_INSTALLATION_AUTHORIZED=false
REAL_CONTINUITY_HEAD_ENROLLMENT_AUTHORIZED=false
REAL_CUSTODY_AUTHORIZED=false
REAL_KEY_ACCESS_AUTHORIZED=false
REAL_SIGNING_AUTHORIZED=false
NATIVE_SIGNING_AUTHORIZED=false
PRODUCTION_REPLAY_STATE_MUTATION_AUTHORIZED=false
COMMIT_AUTHORIZED=false
PUSH_AUTHORIZED=false
```
