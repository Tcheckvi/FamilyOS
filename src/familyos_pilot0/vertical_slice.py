"""Pilot 0 M2 vertical slice orchestration.

Ties together M1's extraction boundary with M2's confirmation/timeline/audit
boundary:

    synthetic message
        -> ExtractionService.extract_event (M1, never writes)
        -> propose(): issues a proposal + a single-use ConfirmationToken,
           records "proposal_created" in the audit trail. Still no write to
           the timeline -- a proposal alone conveys no authorization.
        -> decide(): verifies decision.correlation_id matches
           proposal.correlation_id, then redeems the token against the
           expected correlation_id/family_id/member_id/subject_person_ref
           (single-use, scope-checked, replay-protected -- see
           ``ConfirmationTokenStore.redeem``), records "decision_made".
           Only CONFIRM or EDIT (edit-then-confirm) writes a TimelineEntry
           and records "timeline_written". DISCARD writes nothing.

Any failure in the correlation/scope checks above (mismatched
correlation_id, unknown/replayed/expired/scope-mismatched token) raises
before any audit record is written for that attempt -- a failed decide()
call never produces a misleading "decision_made" record for a decision that
was, in fact, rejected.

This module is intentionally thin: it has no branching business logic of
its own beyond "write only on confirm/edit, never on discard, never before a
redeemed, scope-matched token exists". It is not a general workflow engine.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from familyos_pilot0.audit import AuditRecord, AuditTrail
from familyos_pilot0.confirmation import (
    ConfirmationDecision,
    ConfirmationOutcome,
    ConfirmationToken,
    ConfirmationTokenStore,
)
from familyos_pilot0.errors import ConfirmationScopeMismatchError
from familyos_pilot0.extraction import ExtractionService, TimelineEventProposal
from familyos_pilot0.identity import IdentityContext
from familyos_pilot0.timeline import TimelineEntry, TimelineStore


class Pilot0VerticalSliceService:
    """Orchestrates the M2 synthetic end-to-end vertical slice."""

    def __init__(
        self,
        *,
        extraction_service: ExtractionService,
        token_store: ConfirmationTokenStore,
        timeline_store: TimelineStore,
        audit_trail: AuditTrail,
    ) -> None:
        self._extraction_service = extraction_service
        self._token_store = token_store
        self._timeline_store = timeline_store
        self._audit_trail = audit_trail

    def propose(
        self, *, message_text: str, correlation_id: str, identity: IdentityContext
    ) -> tuple[TimelineEventProposal, ConfirmationToken]:
        """Extract a candidate proposal and issue a confirmation token.

        Never writes a timeline entry. A proposal alone conveys no
        authorization.
        """
        proposal = self._extraction_service.extract_event(
            message_text=message_text, correlation_id=correlation_id
        )
        self._audit_trail.append(
            AuditRecord(
                correlation_id=correlation_id,
                event_type="proposal_created",
                outcome=None,
                recorded_at=datetime.now(),
            )
        )
        token = self._token_store.issue(
            correlation_id=correlation_id,
            family_id=identity.family_id,
            member_id=identity.member_id,
            subject_person_ref=identity.subject_person_ref,
        )
        return proposal, token

    def decide(
        self,
        *,
        decision: ConfirmationDecision,
        token_id: str,
        identity: IdentityContext,
        proposal: TimelineEventProposal,
    ) -> TimelineEntry | None:
        """Verify scope, redeem the token, and act on the human decision.

        Returns the written ``TimelineEntry`` for CONFIRM/EDIT, or ``None``
        for DISCARD. Raises ``ConfirmationScopeMismatchError`` if
        ``decision.correlation_id`` does not match
        ``proposal.correlation_id``, or if the token was issued for a
        different correlation_id/family_id/member_id/subject_person_ref than
        this decision and identity -- the subject_person_ref check closes a
        gap where the same valid token could otherwise be redeemed against a
        substituted subject at decide() time. Raises if the token is
        unknown, already redeemed (replay), or expired -- see
        ``familyos_pilot0.errors``. None of these failures consume the token
        or write an audit record for this attempt. Raises
        ``DuplicateTimelineEntryError`` if a timeline entry already exists
        for this correlation_id.
        """
        if proposal.correlation_id != decision.correlation_id:
            raise ConfirmationScopeMismatchError(
                f"proposal.correlation_id={proposal.correlation_id!r} does "
                f"not match decision.correlation_id="
                f"{decision.correlation_id!r}; refusing to act on a "
                f"decision for a different proposal."
            )

        self._token_store.redeem(
            token_id,
            expected_correlation_id=decision.correlation_id,
            expected_family_id=identity.family_id,
            expected_member_id=identity.member_id,
            expected_subject_person_ref=identity.subject_person_ref,
        )

        self._audit_trail.append(
            AuditRecord(
                correlation_id=decision.correlation_id,
                event_type="decision_made",
                outcome=decision.outcome.value,
                recorded_at=datetime.now(),
            )
        )

        if decision.outcome is ConfirmationOutcome.DISCARD:
            return None

        effective_proposal = proposal
        if decision.outcome is ConfirmationOutcome.EDIT:
            effective_proposal = replace(
                proposal,
                event_summary=decision.edited_event_summary
                if decision.edited_event_summary is not None
                else proposal.event_summary,
                date=decision.edited_date
                if decision.edited_date is not None
                else proposal.date,
                time=decision.edited_time
                if decision.edited_time is not None
                else proposal.time,
            )

        entry = TimelineEntry(
            correlation_id=decision.correlation_id,
            family_id=identity.family_id,
            subject_person_ref=identity.subject_person_ref,
            event_summary=effective_proposal.event_summary,
            date=effective_proposal.date,
            time=effective_proposal.time,
            confirmed_by=identity.member_id,
            confirmed_at=datetime.now(),
        )
        self._timeline_store.write(entry)

        self._audit_trail.append(
            AuditRecord(
                correlation_id=decision.correlation_id,
                event_type="timeline_written",
                outcome=decision.outcome.value,
                recorded_at=datetime.now(),
            )
        )
        return entry
