"""Domain-specific errors for Pilot 0 M2.

Explicit, typed failures rather than raw storage exceptions leaking out of
the vertical slice -- consistent with preferring explicit failure over
silent corruption.
"""

from __future__ import annotations


class Pilot0Error(Exception):
    """Base class for all Pilot 0 domain errors."""


class DuplicateTimelineEntryError(Pilot0Error):
    """A timeline entry already exists for this correlation_id.

    Raised instead of allowing a second confirm/edit-then-confirm decision
    for the same correlation_id to silently overwrite or duplicate a
    timeline entry.
    """


class UnknownConfirmationTokenError(Pilot0Error):
    """No confirmation token exists with the given token id."""


class ReplayedConfirmationTokenError(Pilot0Error):
    """The confirmation token has already been redeemed once.

    Confirmation tokens are single-use. A second redemption attempt for the
    same token id is a replay and MUST be rejected, not silently accepted.
    """


class ExpiredConfirmationTokenError(Pilot0Error):
    """The confirmation token's validity window has passed."""


class ConfirmationScopeMismatchError(Pilot0Error):
    """The pieces of a confirmation decision do not actually belong together.

    Raised when either:

    - the token being redeemed was issued for a different correlation_id,
      family_id, or member_id than the decision/identity it is being used
      for, or
    - the ``ConfirmationDecision.correlation_id`` does not match the
      ``TimelineEventProposal.correlation_id`` it is supposedly deciding on.

    A token whose scope does not match is NOT consumed by a mismatched
    attempt (validate-then-consume) -- only a scope-matched, non-expired,
    not-yet-redeemed token is ever marked redeemed. This keeps a
    scope-mismatched attempt from silently burning a token that its
    legitimate holder could otherwise still use correctly.
    """
