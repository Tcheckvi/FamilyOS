# RD01 custody path boundary — correction candidate

Date: 2026-09-27. Status: REVIEW CANDIDATE ONLY. Native F05 and successor custody
remain unqualified. Nothing in this document authorizes installation or execution.

## Smallest implementation boundary

The two composition modules are dispatch/denial boundaries, not key readers.
A shared `custody_path_boundary.py` provides one metadata-only filesystem adapter,
avoiding duplicated path algorithms or adding file paths to the domain `KeyRef`.
SPEC-0017 §6.5 still prohibits caller-selected paths in KeyRef. Existing configuration
schemas, entrypoints, constants, role checks, N1–N5 and denial code are unchanged.

- `prepare_candidate_custody_paths` in worker composition constructs immutable
  explicit deployment metadata without I/O. It accepts a custody authority root,
  independent absolute private/public file paths and exact expected UID/GID.
- `inspect_candidate_custody_paths` in native composition delegates to the
  metadata-only adapter and maps typed failures to the existing NativeDenied type.
- Neither function is called by dispatch, main, a signer, a helper or any operational
  path. No configuration field/CLI option/environment override selects them.

The role layout is exactly `root/private/<file>` and `root/public/<file>`.
The two parent paths remain separately visible. Normalization rejects relative paths,
empty/dot/dot-dot components, NULs, excessive length/depth and role substitutions;
it does not use Path.resolve as a security check.

## Object checks and limitations

Traversal starts at an opened slash directory and opens each single component
relative to its held parent FD. Every component is lstat-equivalent inspected
(`stat(..., follow_symlinks=False)`), opened with O_NOFOLLOW/O_DIRECTORY as
appropriate, and compared with fstat. There is no missing-flag fallback.

Root/private directory: expected UID/GID and exact 0700. Public directory: expected
UID/GID and 0700 or 0755 (separate non-secret role, neither group nor world writable).
Private file modes: 0400/0600. Public file modes: 0400/0600/0644. Special mode bits and
nonzero file flags are denied. These role-specific candidate rules preserve strict
private permissions and represent the recorded nested public-directory 0755
metadata; they do not grant approval of current live objects.

Both key-role files must be nonempty, regular, bounded to 65,536 bytes, and have
exactly one hard link. Distinct roles must identify distinct objects. File opens
are nonblocking, read-only and close-on-exec. No read/pread/fdopen/mmap operation
exists: opened file descriptors are used only for fstat and close.

Full compared identity: device, inode, size, complete mode, UID, GID, link count,
mtime_ns, ctime_ns and file flags. The adapter retains all ancestor and leaf
descriptors and rechecks both fstat and each parent/name binding before returning.
Failures close all held FDs and deny without retry. Returned metadata contains no FD,
key bytes or signer handle. Its `key_use_authorized` property is always false.

This is an observation boundary, not a lock or reusable authorization. A concurrent
same-owner/privileged writer can change an object after the last observation;
metadata does not prove key content, public fingerprint, ACL absence, native
non-exportability, or future path continuity. Metadata changes in unrelated ancestor
directories may conservatively cause denial. No claim of an atomic multi-object
snapshot is made. A future qualified native consumer must independently bind its
actual object use; a later pathname reopen based only on this snapshot is forbidden.

The native service UID checks remain exactly 503/non-admin. A metadata profile
containing the recorded successor owner 501 does not relax those checks or solve
the service/human custody relationship. The metadata API is not exposed through
worker configuration or KeyRef, and is not a trusted-source provenance mechanism.

## Why the forensic summary is not a complete security proof

The forensic hashes are verified, but its vocabulary classifications overstate some
matches: composition `mode` refers to smoke/operational mode; store `identity`
is not an inode comparison; the test's symlink match concerns deployment object-type
policy; documentation `/private/` refers to system ancestry/temporary paths.
Therefore the proposal adds explicit path/object controls and dedicated synthetic
tests. It does not claim the old composition functions accessed key files unsafely.

Some similar lower-level checks exist outside the four named surfaces, e.g.
`custody_live_journal.py`. That component also owns journal/ACL/claim semantics and
calls a native metadata observer, so it is not imported as a generic custody-key
adapter. No journal/claim code is modified or run here.

## Synthetic validation and reproduction

Only the new standalone test is executed. It imports the staged path adapter and
standard library, not native/worker entrypoints or repository modules. All filesystem
fixtures contain a fixed public ASCII canary and live under a new private
`/private/tmp/rd01-public-canary-*` tree. The guarded OS allows only that tree and
directory ancestors, requires no-follow/read-only opens, tracks FD cleanup and
forbids content operations. Socket and subprocess creation are denied. Temporary
cleanup is for synthetic fixtures only, never an operational recovery mechanism.

18 tests cover positive metadata observations, role/lexical validation, wrong owner
and mode, symlinks at every custody edge and ancestry, hard links before/after open,
FIFO/directory/empty/oversize/missing files, replacement before/after open, directory
rebinding, mode changes, missing safety flags, open failure and FD cleanup, immutable
nonauthority output, and a static forbidden-call inspection. Special-mode rejection
uses simulated observed metadata because the host clears setuid on the non-executable
canary. Initial fixture GID assumptions were corrected to its observed group without
relaxing the implementation.

To assemble the reviewed copies outside any repository, map the delivered filenames:
- worker composition candidate -> `candidate/src/familyos_pilot0/custody_worker_composition.py`
- native composition candidate -> `candidate/src/familyos_pilot0/custody_native_composition.py`
- path boundary candidate -> `candidate/src/familyos_pilot0/custody_path_boundary.py`
- test candidate -> `candidate/tests/test_custody_path_boundary_candidate.py`
- this document -> `candidate/docs/pilot0/RD01-CUSTODY-PATH-CANDIDATE.md`

Run the standalone test with an explicitly selected Python 3.13 interpreter:
`python -I -S -B candidate/tests/test_custody_path_boundary_candidate.py`.
This is a synthetic development test command, not an approved live launch command.

No deployment allowlist/package manifest is promoted. The new dependency changes
the candidate source closure, so future protected integration requires a new reviewed
closure rather than silently extending the existing R12/native allowlists.
Next: independent review of exact baseline hashes, patch, adapter threat model,
tests, and the unchanged operational gates. Native qualification remains a separate
unresolved stage; no finalizer/launcher, actual custody inspection, signing, claim,
provisioning, provider call, repository modification or closure is permitted here.
