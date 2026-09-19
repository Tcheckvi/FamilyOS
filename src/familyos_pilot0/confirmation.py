"""Confirmation decision boundary for Pilot 0 M2.

A ``TimelineEventProposal`` conveys no authorization (M1's Foundational
Rule). This module is where that boundary is crossed -- deliberately, only
here, and only through an explicit, single-use confirmation token.

``ConfirmationToken`` is a lightweight, LOCAL, SYNTHETIC-slice-only
confirmation credential. It is explicitly NOT the eventual production
signed/expiring/single-use confirmation-link design described in the Pilot 0
preparation package (HMAC-signed opaque token, delivered by email, with a
real transport and real expiry policy) -- it is the minimal in-process
analogue needed to prove the same safety property (single-use,
replay-rejected, scoped) inside this synthetic vertical slice, without
inventing transport, signing, or delivery machinery M2 does not need.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from familyos_pilot0.errors import (
    ConfirmationScopeMismatchError,
    ExpiredConfirmationTokenError,
    ReplayedConfirmationTokenError,
    UnknownConfirmationTokenError,
)

_DEFAULT_VALIDITY = timedelta(hours=1)


class ConfirmationOutcome(StrEnum):
    """The three, and only three, human decision outcomes for M2."""

    CONFIRM = "confirm"
    EDIT = "edit"
    DISCARD = "discard"


@dataclass(frozen=True)
class ConfirmationToken:
    """A scoped, single-use, local confirmation credential."""

    token_id: str
    correlation_id: str
    family_id: str
    member_id: str
    subject_person_ref: str | None
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class ConfirmationDecision:
    """A human decision about a proposal, optionally with edited fields.

    For ``EDIT``, the edited fields override the corresponding proposal
    fields for the resulting timeline entry -- "edit-then-confirm" is a
    single combined decision in M2, not two separate steps.
    """

    outcome: ConfirmationOutcome
    correlation_id: str
    edited_event_summary: str | None = None
    edited_date: str | None = None
    edited_time: str | None = None


@dataclass
class _TokenRecord:
    token: ConfirmationToken
    redeemed: bool = False


class ConfirmationTokenStore:
    """In-memory, single-use confirmation token issuance and redemption.

    Kept in-memory rather than persisted: tokens are short-lived, single-use
    credentials for this synthetic, single-process vertical slice, not part
    of the durable record. The DECISION made using a token, and its outcome,
    are what get durably recorded (see ``AuditTrail``/``TimelineStore``) --
    the token itself is not.
    """

    def __init__(self, *, validity: timedelta = _DEFAULT_VALIDITY) -> None:
        self._validity = validity
        self._records: dict[str, _TokenRecord] = {}

    def issue(
        self,
        *,
        correlation_id: str,
        family_id: str,
        member_id: str,
        subject_person_ref: str | None,
    ) -> ConfirmationToken:
        now = datetime.now()
        token = ConfirmationToken(
            token_id=uuid.uuid4().hex,
            correlation_id=correlation_id,
            family_id=family_id,
            member_id=member_id,
            subject_person_ref=subject_person_ref,
            issued_at=now,
            expires_at=now + self._validity,
        )
        self._records[token.token_id] = _TokenRecord(token=token)
        return token

    def redeem(
        self,
        token_id: str,
        *,
        expected_correlation_id: str,
        expected_family_id: str,
        expected_member_id: str,
        expected_subject_person_ref: str | None,
    ) -> ConfirmationToken:
        """Validate, then consume, a token. Never consumes on failure.

        Checks are performed in this order: unknown -> already-redeemed
        (replay) -> expired -> scope mismatch (correlation_id, family_id,
        member_id, subject_person_ref, all checked together). Only when
        every check passes is the token marked redeemed. A scope-mismatched
        attempt against an otherwise valid token leaves it unredeemed, so
        its legitimate holder can still use it correctly afterward.

        ``subject_person_ref`` is included in scope specifically to close a
        gap where a caller could otherwise reuse a valid
        correlation_id/family_id/member_id-matching token with a
        *different* subject_person_ref at decide() time than the one
        supplied at propose() time, writing a confirmed timeline entry
        against the wrong subject.
        """
        record = self._records.get(token_id)
        if record is None:
            raise UnknownConfirmationTokenError(
                f"No confirmation token found for token_id {token_id!r}."
            )
        if record.redeemed:
            raise ReplayedConfirmationTokenError(
                f"Confirmation token {token_id!r} has already been used."
            )
        if datetime.now() > record.token.expires_at:
            raise ExpiredConfirmationTokenError(
                f"Confirmation token {token_id!r} expired at "
                f"{record.token.expires_at.isoformat()}."
            )
        if (
            record.token.correlation_id != expected_correlation_id
            or record.token.family_id != expected_family_id
            or record.token.member_id != expected_member_id
            or record.token.subject_person_ref != expected_subject_person_ref
        ):
            raise ConfirmationScopeMismatchError(
                f"Confirmation token {token_id!r} is scoped to "
                f"correlation_id={record.token.correlation_id!r}, "
                f"family_id={record.token.family_id!r}, "
                f"member_id={record.token.member_id!r}, "
                f"subject_person_ref={record.token.subject_person_ref!r}; "
                f"it cannot be used for correlation_id="
                f"{expected_correlation_id!r}, family_id="
                f"{expected_family_id!r}, member_id={expected_member_id!r}, "
                f"subject_person_ref={expected_subject_person_ref!r}."
            )
        record.redeemed = True
        return record.token


def confirm_event_proposal(proposal: object) -> object:
    """Confirm a pending proposal without performing a durable write."""

    from dataclasses import replace

    from familyos_pilot0.errors import (
        ProposalTerminalStateError,
        ProposalValidationError,
    )
    from familyos_pilot0.proposal import EventProposal, ProposalState

    if not isinstance(proposal, EventProposal):
        raise ProposalValidationError("event proposal is required")
    if proposal.state is not ProposalState.PENDING:
        raise ProposalTerminalStateError(
            f"cannot confirm proposal in terminal state {proposal.state.value}"
        )
    return replace(proposal, state=ProposalState.CONFIRMED)


def edit_event_proposal(
    proposal: object,
    *,
    event_title: str | None = None,
    event_start_iso: str | None = None,
) -> object:
    """Apply an explicit human edit to a pending proposal."""

    from dataclasses import replace

    from familyos_pilot0.errors import (
        ProposalDecisionError,
        ProposalTerminalStateError,
        ProposalValidationError,
    )
    from familyos_pilot0.proposal import EventProposal, ProposalState

    if not isinstance(proposal, EventProposal):
        raise ProposalValidationError("event proposal is required")
    if proposal.state is not ProposalState.PENDING:
        raise ProposalTerminalStateError(
            f"cannot edit proposal in terminal state {proposal.state.value}"
        )

    new_title = proposal.event_title if event_title is None else event_title.strip()
    new_start = (
        proposal.event_start_iso if event_start_iso is None else event_start_iso.strip()
    )

    if not new_title:
        raise ProposalValidationError("event_title must remain non-blank")
    if not new_start:
        raise ProposalValidationError("event_start_iso must remain non-blank")
    if (
        new_title == proposal.event_title
        and new_start == proposal.event_start_iso
    ):
        raise ProposalDecisionError("an edit must change at least one proposal field")

    return replace(
        proposal,
        event_title=new_title,
        event_start_iso=new_start,
        state=ProposalState.EDITED,
        human_adjusted=True,
    )


def discard_event_proposal(proposal: object) -> object:
    """Discard a pending proposal without creating durable family state."""

    from dataclasses import replace

    from familyos_pilot0.errors import (
        ProposalTerminalStateError,
        ProposalValidationError,
    )
    from familyos_pilot0.proposal import EventProposal, ProposalState

    if not isinstance(proposal, EventProposal):
        raise ProposalValidationError("event proposal is required")
    if proposal.state is not ProposalState.PENDING:
        raise ProposalTerminalStateError(
            f"cannot discard proposal in terminal state {proposal.state.value}"
        )
    return replace(proposal, state=ProposalState.DISCARDED)
