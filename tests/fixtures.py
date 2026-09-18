"""Synthetic message and identity fixtures for Pilot 0 M1/M2 tests.

All content below is synthetic. No real names, emails, addresses, or real
family data appear anywhere in this file.
"""

from __future__ import annotations

from familyos_pilot0.identity import IdentityContext

CLEAR_APPOINTMENT = (
    "Reminder: Dentist appointment for Alex Synthetic on 2026-10-03 at 14:30."
)
"""A clear appointment with an unambiguous date, time, and person."""

AMBIGUOUS_TIME = (
    "Let's meet sometime next week, maybe Tuesday or Wednesday afternoon?"
)
"""An ambiguous date/time that should yield a low-confidence extraction."""

SCHOOL_EVENT = (
    "School reminder: Parent-teacher conference for Jordan Synthetic "
    "on 2026-10-10 at 16:00 in Room 12."
)
"""A school/child-related event with a clear date, time, and person."""

DUPLICATE_FORWARD_OF_CLEAR_APPOINTMENT = CLEAR_APPOINTMENT
"""The same message as ``CLEAR_APPOINTMENT``, representing the family
forwarding the identical email a second time. Used to prove that the same
``correlation_id`` supplied for both calls is preserved identically in both
resulting proposals -- the identity-preservation property a later milestone's
persistence layer would use for duplicate detection. M1 has no persistence
layer, so this fixture only proves correlation_id pass-through, not
deduplication itself.
"""

SYNTHETIC_FAMILY_IDENTITY = IdentityContext(
    family_id="family-synthetic-001",
    member_id="member-synthetic-parent-a",
    subject_person_ref="member-synthetic-parent-a",
)
"""A synthetic identity for the family-mental-load-reduction wedge (A):
the proposal concerns the same member who is confirming it."""

SYNTHETIC_CHILD_IDENTITY = IdentityContext(
    family_id="family-synthetic-001",
    member_id="member-synthetic-parent-a",
    subject_person_ref="member-synthetic-child-jordan",
    required_approver_refs=("member-synthetic-parent-b",),
)
"""A synthetic identity for the co-parenting wedge (B): the proposal
concerns a child, and names a second parent as a required approver.
``required_approver_refs`` is captured on this identity object only -- M2
does not persist, audit, or enforce it (see ``identity.py``)."""

SYNTHETIC_OTHER_FAMILY_IDENTITY = IdentityContext(
    family_id="family-synthetic-002",
    member_id="member-synthetic-parent-c",
    subject_person_ref="member-synthetic-parent-c",
)
"""A synthetic identity belonging to a different family/member than
``SYNTHETIC_FAMILY_IDENTITY``. Used only to prove confirmation-token scope
enforcement rejects cross-family/cross-member use of a token."""
