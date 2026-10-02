# FamilyOS — Documentation Validation Checklist

## Status

- Version: 1.0
- State: Prepared outside the repository
- Purpose: Documentation validation checklist

## Repository

- [ ] Correct repository selected.
- [ ] Expected branch/HEAD recorded before changes.
- [ ] Working-tree state recorded.
- [ ] No unrelated file is overwritten.

## Language and Naming

- [ ] English.
- [ ] UTF-8.
- [ ] FamilyOS capitalization consistent.
- [ ] Filename follows canonical naming rules.
- [ ] No secret, account identifier, or personal data in filename.
- [ ] No new canonical identifier invented without catalogue allocation.

## Structure

- [ ] Document has one primary responsibility.
- [ ] Correct documentation category.
- [ ] No duplicate authoritative definition.
- [ ] Related documents are referenced using repository-relative paths.

## Markdown

- [ ] Code fences balanced.
- [ ] No trailing whitespace.
- [ ] Headings are coherent.
- [ ] Examples are minimal and safe.
- [ ] `git diff --check` passes.

## Governance

- [ ] Historical evidence not rewritten silently.
- [ ] Decision documents remain separate from implementation.
- [ ] Authorization statements are precise.
- [ ] Proposed content is not presented as approved.
- [ ] Deprecated material points to its successor.

## Navigation

- [ ] Relevant README/index updated or change explicitly deferred.
- [ ] New document discoverable.
- [ ] Cross-reference target exists.

## Final

- [ ] Documentation-specific validator passes where available.
- [ ] Repository-required quality checks pass.
- [ ] Final diff reviewed.
- [ ] Commit/push remains separately authorized if governance requires it.
