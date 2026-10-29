# Codex Lab P1 v4c2 — Offline Qualification, Owner Adoption and Custody Pointer

- **Class:** Informative offline qualification and evidence-custody pointer; not technical closure, ADR, RFC, SPEC or release authorization.
- **Qualification:** `QUALIFIED_OFFLINE_WITH_LIMITS` for exact v4c2 bytes.
- **Owner decision:** `ADOPTED_WITH_LIMITS` (offline only; 2026-10-28).
- **Record ownership:** FamilyOS project owner (classification and index ownership approved on 2026-10-29; this descriptive record does not grant Git mutation authority).
- **Signing / trusted timestamp / immutability:** Not attested.
- **Runtime / P1 / P2 / UTM:** `LIVE_AUTHORIZED=false`.
- **Document preparation date:** 2026-10-29; historical evidence date: 2026-10-28.

## Qualification boundary

- Candidate ZIP C01 SHA-256: `8f6ac4160bfa604f905d23b5c69e613711fea89910e229b55ad8b0e97f6ff3d5`.
- V2 contract controller, contract, consumer, and suite identities must remain as recorded in the exact-byte C01–C03 evidence.
- Claude's independent v4c2 qualification is bounded by offline cases; Astra's earlier F1 review pertains to historical v4, not a new v4c2 live review.
- N1–N3: wording and documentation clarity. N4: consumer strictness; summary forged publication flag not explicitly rejected, no grant demonstrated. N5: E08 mutant survived inherited suite, fresh reviewer tests killed it. N6: historical 222-mutant campaign belonged to Claude, not Astra; preserve append-only provenance correction.
- D1 is offline-limited; D2 root-arranged adversary remains HOLD; D5 point-in-time only; H1 independent witness/atomicity open; SEC-101..104 open; P0 consumed, no reuse.

## External custody and post-publication readback

- Reported on-host destination: `/Volumes/990 PRO/FamilyOS-Files/03-Evidence/Codex-Lab/P1v4c2-Offline-Qualification-2026-10-28/`.
- V9 `PASS_NO_COPY_NO_WRITE`; V11 authorized publication `CONSERVATION=PASS_16_OF_16`, with atomic no-replace and source-preservation reporting.
- V12 distinct readback: `INDEPENDENT_POST_PUBLICATION_READBACK=PASS_16_OF_16_POINT_IN_TIME`; published files have distinct inodes, source originals verified, total published payload 769742 bytes.
- These claims are based on operator-provided Terminal output, not a signed stdout capture or independent hardware attestation. V11 wrote no additional evidence record. No evidence of ongoing retention or WORM immutability is claimed.

## Exact external evidence inventory

The files below are the 16 exact-byte C01–C16 sources independently checked at the point of V12. The full original files remain external to the Git repository.

| ID | Name | Bytes | SHA-256 |
|---|---|---:|---|
| C01 | `FamilyOS-CodexLab-P1v4C2-ContractV2-Offline-Candidate-EVIDENCE-v1-2026-10-28.zip` | 103069 | `8f6ac4160bfa604f905d23b5c69e613711fea89910e229b55ad8b0e97f6ff3d5` |
| C02 | `FamilyOS-CodexLab-P1v4C2-ContractV2-Offline-Candidate-RESULT-v1-2026-10-28.md` | 7706 | `b56220f81df9b16ee8a9adf6a274b72e6864eae35c4369208fe9fca790330a6c` |
| C03 | `FamilyOS-CodexLab-P1v4C2-ContractV2-Offline-Candidate-SHA256-RECEIPT-v1-2026-10-28.md` | 750 | `55db5ee78508dc2f6dc1c195976db03b17bfc8251eb6041e67ba878d9c141ae5` |
| C04 | `FamilyOS-CodexLab-Claude-P1v4C2-ContractV2-Exact-Bytes-Independent-Review-RESULT-v1-2026-10-28.md` | 23835 | `d6fbe88e332266f4580d755e86e1bc18cfdb582b49ea5eafa7190b8de731908a` |
| C05 | `FamilyOS-CodexLab-Claude-P1v4C2-ContractV2-Exact-Bytes-Independent-Review-EVIDENCE-v1-2026-10-28.zip` | 118419 | `8591256cbef81b5a2b330f6455e45d3c7536a87ad660f23fa6cfc3c716bc5e14` |
| C06 | `FamilyOS-CodexLab-Claude-P1v4C2-ContractV2-Exact-Bytes-Independent-Review-SHA256-RECEIPT-v1-2026-10-28.md` | 1470 | `581ab2f4212624049f97a7cbb2aa181c09aabd4714b9539d5f35acab1e0732e3` |
| C07 | `FamilyOS-CodexLab-Astra-P1v4-F1-Terminal-Cutoff-Independent-Requalification-RESULT-v1-2026-10-28.md` | 21692 | `60a050610892b6d7f5b6a8908fa4b50bcfc736e58c5d6b9be34c243de1c7b71c` |
| C08 | `FamilyOS-CodexLab-Astra-P1v4-F1-Terminal-Cutoff-Independent-Requalification-EVIDENCE-v1-2026-10-28.zip` | 456369 | `9be6c98eda2a8bf13a020b3a3225717ae2e73b3e9ddd3e3568bcfa961e402039` |
| C09 | `FamilyOS-CodexLab-Astra-P1v4-F1-Terminal-Cutoff-Independent-Requalification-SHA256-RECEIPT-v1-2026-10-28.md` | 649 | `7855ac6cc2d03af7239444f13aa111df906faa9a5c60564bc93d74905bc2bbcf` |
| C10 | `FamilyOS-CodexLab-P1v4C2-Offline-Qualification-Reconciliation-RESULT-v1-2026-10-28.md` | 8215 | `f6ee58c211cb12f799f59f4e4a3191a3f0f8e31edc1be1d520a54b7c7b3ca837` |
| C11 | `FamilyOS-CodexLab-P1v4C2-Offline-Qualification-Reconciliation-EVIDENCE-v1-2026-10-28.zip` | 7046 | `c9e14190644829dfeb122816299ce948ab0ca9f06131ea8dd2305efb3f5441fc` |
| C12 | `FamilyOS-CodexLab-P1v4C2-Offline-Qualification-Reconciliation-SHA256-RECEIPT-v1-2026-10-28.md` | 588 | `c210ae53ac52e7d935c69e8b895a22fbc0d8e11df43b376a227c07003a4cd04d` |
| C13 | `FamilyOS-P1v4c2-Owner-Offline-Adoption-v1-2026-10-28-DECISION.md` | 7123 | `00cb078cfbaf44f5ea5f3182373a5239422fc31ba58b3039365c6ee4ef515564` |
| C14 | `FamilyOS-P1v4c2-Owner-Offline-Adoption-v1-2026-10-28-EVIDENCE.zip` | 7987 | `2ba62e26c2ca2cd31c92a9578c22c8e8223af0861367af9c349d5e70b5b57e93` |
| C15 | `FamilyOS-P1v4c2-Owner-Offline-Adoption-v1-2026-10-28-SHA256-RECEIPT.md` | 1185 | `175dadd099515c94b35ecd0fc5788c1100c8703f066734a19bf8564bc0dfb46d` |
| C16 | `FamilyOS-P1v4c2-Owner-Offline-Adoption-v1-2026-10-28-CARRIED-REGISTER.json` | 3639 | `55ee6dac451b9357aca0714a121a9664461836f15e44b6b85e493e632f342357` |

## Authority and preservation

- This record is descriptive, not an execution grant. Any initial Operation B filing requires fresh branch/HEAD/TREE/status and collision checks, the owner's separately explicit repository-mutation authority, and post-filing reconciliation.
- In particular, no `git add`, commit, push, merge, real data, signing, network provider action, UTM/P1/P2 live operation, or consumed-slot reuse is authorized by this document.
- Preserve pre-existing staged, unstaged, and untracked work in both the parent and CLI repositories; never use broad resets/restores/cleans or `git add .`.
- The parent repository is a distinct Git root. Future product/Pilot 1 cross-references require independent approval and change records.
- Core Product remains **5.3/7 (~76%)**, with no weighted-score reconciliation from this pointer.

## Filing provenance and limits of authority

The owner approved the `docs/governance/qualification-records/` class and `README.md` index in conversation on 2026-10-29, **without granting Git mutation at that time**. The initial filing of these two documents is subject to a separately explicit owner mutation authorization, fresh on-host checks, and post-filing reconciliation. The presence of this pointer in a repository does not itself attest custody immutability, signing, release readiness, or operational authority.
