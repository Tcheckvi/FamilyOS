# FamilyOS — Documentation Placement Manifest

## Status

- Version: 1.0
- State: Proposed placement map

## Purpose

Define the intended repository destinations for the Pilot 0 → Pilot 1
transition package and documentation-completion package.

## Placement

| Document | Intended destination | Responsibility |
| --- | --- | --- |
| Pilot 0 to Pilot 1 Transition Plan | `docs/01-product/roadmap/Pilot-0-to-Pilot-1-Transition-Plan.md` | Product transition sequence |
| Pilot 0 Exit Review Checklist | `docs/03-engineering/Pilot-0-Exit-Review-Checklist.md` | Engineering/evidence exit review |
| Pilot 1 Architecture Readiness | `docs/02-architecture/Pilot-1-Architecture-Readiness.md` | Architecture decisions before Pilot 1 |
| Pilot 1 Launch Gates | `docs/04-operations/Pilot-1-Launch-Gates.md` | Operational launch gates |
| Pilot 1 Productization Plan | `docs/01-product/roadmap/Pilot-1-Productization-Plan.md` | Productization sequence |
| Documentation Completion Plan | `docs/00-foundation/standards/Documentation-Completion-Plan.md` | Documentation completion policy |
| Documentation Validation Checklist | `docs/00-foundation/standards/Documentation-Validation-Checklist.md` | Documentation validation |
| Documentation Placement Manifest | `docs/02-architecture/Documentation-Placement-Manifest.md` | Placement and ownership map |

## Placement Rules

- Installer MUST refuse to overwrite a different existing file.
- Installer MAY accept an already-identical file as idempotent.
- Installer MUST NOT stage, commit, push, fetch, or use network.
- Installer MUST NOT modify index documents automatically.
- Index updates should be reviewed after installation because authoritative
  indexes may already contain concurrent changes.

## Rationale

The placement follows the responsibility model:

- Foundation standards → `docs/00-foundation/standards/`
- Product plans → `docs/01-product/`
- Architecture → `docs/02-architecture/`
- Engineering process → `docs/03-engineering/`
- Operations → `docs/04-operations/`

This keeps responsibility narrow and avoids using one documentation category as
a general dumping ground.
