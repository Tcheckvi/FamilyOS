# FamilyOS — Documentation Completion Plan

## Status

- Version: 1.0
- State: Prepared outside the repository
- Purpose: Move the documentation track from near-complete to review-ready

## Context

FamilyOS documentation is already a first-class architectural capability.

The remaining work should focus on integration quality rather than producing
documents merely to increase document count.

The completion objective is:

> one authoritative location per responsibility, consistent naming,
> navigable cross-references, validated Markdown, clear ownership, and no stale
> conflicting source of truth.

## Completion Workstreams

### D1 — Canonical Placement

- Every persistent document has one primary category.
- Duplicate responsibilities are removed or redirected.
- New transition documents are placed according to documentation responsibility.

### D2 — Index Integrity

- Foundation index updated.
- Product roadmap index updated.
- Architecture index updated.
- Engineering index updated.
- Operations/reference indexes updated where applicable.
- New documents discoverable from at least one authoritative index.

### D3 — Cross-Reference Integrity

- Repository-relative references.
- No stale renamed paths.
- No references to the deprecated singular RFC documentation path when the canonical location is `docs/rfcs/`.
- No duplicate definitions where a narrower authoritative document exists.

### D4 — Markdown Quality

- UTF-8.
- Balanced code fences.
- No trailing whitespace.
- `git diff --check` clean.
- Standard Markdown only unless officially adopted otherwise.

### D5 — Metadata and Naming

- English.
- Official FamilyOS capitalization.
- File names comply with naming conventions.
- Canonical identifiers are not invented locally.
- Sensitive information is never encoded in filenames.

### D6 — Lifecycle

Every authoritative document should have a clear lifecycle state where relevant:

- Draft;
- Proposed;
- Approved;
- Stable;
- Deprecated;
- Superseded.

### D7 — Ownership

Each document has one primary responsibility.

When responsibility overlaps:

1. choose the narrowest authoritative document;
2. keep the definition there;
3. replace duplication with a reference.

### D8 — Validation

Run:

- repository documentation validator, if present;
- link/reference checks, if present;
- Markdown/fence checks;
- Ruff/MyPy/Pytest for repository-wide changes when required by governance;
- `git diff --check`.

## Completion Gate

The documentation track may be considered review-ready when:

```text
CANONICAL_PLACEMENT=PASS
INDEX_INTEGRITY=PASS
CROSS_REFERENCE_INTEGRITY=PASS
MARKDOWN_QUALITY=PASS
NAMING_METADATA=PASS
LIFECYCLE_STATE=PASS
OWNERSHIP_BOUNDARIES=PASS
DOCUMENTATION_VALIDATION=PASS
```

This plan does not itself set the product-roadmap percentage to 100%. The final
percentage should be updated only after the authoritative scoring method is
re-run against the installed and reviewed repository state.
