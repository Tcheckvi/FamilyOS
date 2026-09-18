"""Synthetic message fixtures for Pilot 0 M1 tests.

All content below is synthetic. No real names, emails, addresses, or real
family data appear anywhere in this file.
"""

from __future__ import annotations

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
