"""Minimal Pilot 0 identity context (M2 scope only).

This is deliberately NOT the eventual FamilyOS Security/Identity or
`AuthorizedContext` architecture. It is the smallest model that lets M2
express "this item concerns X, and additionally names Y as a required
approver" without committing to any specific family/household topology --
following the corrected M1-preparation-phase design (family_id/member_id/
subject_person_ref/required_approver_refs[] rather than a household_id-per-
parent model).

``required_approver_refs`` is captured in ``IdentityContext`` for the
duration of a single ``propose``/``decide`` call only. It is NOT persisted
to ``TimelineEntry`` and NOT written to any ``AuditRecord`` -- neither
schema has a field for it (see ``timeline.py``/``audit.py``), and M2's
audit trail is deliberately content-minimized. It is also NOT enforced: the
``member_id`` who makes the confirm/edit/discard decision is the sole
decision-maker for M2's scope, regardless of what ``required_approver_refs``
names. Persisting, auditing, or enforcing required-approver gating are all
explicitly later-milestone concerns, not part of this vertical slice --
doing any of them now would mean building exactly the kind of general
authorization/workflow subsystem this milestone's authorization excludes.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IdentityContext:
    """The minimal identity binding for a single M2 proposal/decision."""

    family_id: str
    member_id: str
    subject_person_ref: str | None = None
    required_approver_refs: tuple[str, ...] = field(default_factory=tuple)
