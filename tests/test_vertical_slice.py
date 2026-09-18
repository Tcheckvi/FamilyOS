"""End-to-end vertical slice tests for Pilot 0 M2. Synthetic data only.

Covers: confirm, edit-then-confirm, discard, replay rejection, and
duplicate/idempotency behavior, plus audit-trail correlation.
"""

from __future__ import annotations

import pytest

from familyos_pilot0.audit import AuditTrail
from familyos_pilot0.confirmation import (
    ConfirmationDecision,
    ConfirmationOutcome,
    ConfirmationTokenStore,
)
from familyos_pilot0.errors import (
    ConfirmationScopeMismatchError,
    DuplicateTimelineEntryError,
    ReplayedConfirmationTokenError,
)
from familyos_pilot0.extraction import ExtractionService
from familyos_pilot0.model_gateway import FakeModelGateway
from familyos_pilot0.storage import open_pilot0_connection
from familyos_pilot0.timeline import TimelineStore
from familyos_pilot0.vertical_slice import Pilot0VerticalSliceService
from tests.fixtures import (
    CLEAR_APPOINTMENT,
    SYNTHETIC_CHILD_IDENTITY,
    SYNTHETIC_FAMILY_IDENTITY,
    SYNTHETIC_OTHER_FAMILY_IDENTITY,
)


def _service() -> Pilot0VerticalSliceService:
    connection = open_pilot0_connection(":memory:")
    return Pilot0VerticalSliceService(
        extraction_service=ExtractionService(gateway=FakeModelGateway()),
        token_store=ConfirmationTokenStore(),
        timeline_store=TimelineStore(connection),
        audit_trail=AuditTrail(connection),
    )


def test_confirm_writes_timeline_entry() -> None:
    service = _service()
    correlation_id = "corr-confirm-1"

    proposal, token = service.propose(
        message_text=CLEAR_APPOINTMENT,
        correlation_id=correlation_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
    )

    entry = service.decide(
        decision=ConfirmationDecision(
            outcome=ConfirmationOutcome.CONFIRM, correlation_id=correlation_id
        ),
        token_id=token.token_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
        proposal=proposal,
    )

    assert entry is not None
    assert entry.correlation_id == correlation_id
    assert entry.event_summary == proposal.event_summary
    assert entry.confirmed_by == SYNTHETIC_FAMILY_IDENTITY.member_id


def test_edit_then_confirm_writes_edited_timeline_entry() -> None:
    service = _service()
    correlation_id = "corr-edit-1"

    proposal, token = service.propose(
        message_text=CLEAR_APPOINTMENT,
        correlation_id=correlation_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
    )

    entry = service.decide(
        decision=ConfirmationDecision(
            outcome=ConfirmationOutcome.EDIT,
            correlation_id=correlation_id,
            edited_time="15:00",
        ),
        token_id=token.token_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
        proposal=proposal,
    )

    assert entry is not None
    assert entry.time == "15:00"
    assert entry.date == proposal.date  # untouched field carried through
    assert entry.event_summary == proposal.event_summary


def test_discard_writes_no_timeline_entry() -> None:
    service = _service()
    correlation_id = "corr-discard-1"

    proposal, token = service.propose(
        message_text=CLEAR_APPOINTMENT,
        correlation_id=correlation_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
    )

    entry = service.decide(
        decision=ConfirmationDecision(
            outcome=ConfirmationOutcome.DISCARD, correlation_id=correlation_id
        ),
        token_id=token.token_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
        proposal=proposal,
    )

    assert entry is None


def test_proposal_alone_never_writes_a_timeline_entry() -> None:
    service = _service()
    correlation_id = "corr-no-decision-1"

    service.propose(
        message_text=CLEAR_APPOINTMENT,
        correlation_id=correlation_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
    )

    # No decide() call at all -- proposal alone must never write state.
    assert not service._timeline_store.exists(correlation_id)


def test_replayed_confirmation_token_is_rejected() -> None:
    service = _service()
    correlation_id = "corr-replay-1"

    proposal, token = service.propose(
        message_text=CLEAR_APPOINTMENT,
        correlation_id=correlation_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
    )

    service.decide(
        decision=ConfirmationDecision(
            outcome=ConfirmationOutcome.CONFIRM, correlation_id=correlation_id
        ),
        token_id=token.token_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
        proposal=proposal,
    )

    with pytest.raises(ReplayedConfirmationTokenError):
        service.decide(
            decision=ConfirmationDecision(
                outcome=ConfirmationOutcome.CONFIRM,
                correlation_id=correlation_id,
            ),
            token_id=token.token_id,
            identity=SYNTHETIC_FAMILY_IDENTITY,
            proposal=proposal,
        )


def test_duplicate_correlation_id_is_rejected() -> None:
    service = _service()
    correlation_id = "corr-duplicate-1"

    proposal_1, token_1 = service.propose(
        message_text=CLEAR_APPOINTMENT,
        correlation_id=correlation_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
    )
    service.decide(
        decision=ConfirmationDecision(
            outcome=ConfirmationOutcome.CONFIRM, correlation_id=correlation_id
        ),
        token_id=token_1.token_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
        proposal=proposal_1,
    )

    # A second, independent proposal/token cycle for the SAME correlation_id
    # (e.g. the family forwarded the identical email a second time).
    proposal_2, token_2 = service.propose(
        message_text=CLEAR_APPOINTMENT,
        correlation_id=correlation_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
    )

    with pytest.raises(DuplicateTimelineEntryError):
        service.decide(
            decision=ConfirmationDecision(
                outcome=ConfirmationOutcome.CONFIRM,
                correlation_id=correlation_id,
            ),
            token_id=token_2.token_id,
            identity=SYNTHETIC_FAMILY_IDENTITY,
            proposal=proposal_2,
        )


def test_audit_trail_records_every_step_for_confirm() -> None:
    service = _service()
    correlation_id = "corr-audit-confirm-1"

    proposal, token = service.propose(
        message_text=CLEAR_APPOINTMENT,
        correlation_id=correlation_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
    )
    service.decide(
        decision=ConfirmationDecision(
            outcome=ConfirmationOutcome.CONFIRM, correlation_id=correlation_id
        ),
        token_id=token.token_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
        proposal=proposal,
    )

    records = service._audit_trail.for_correlation_id(correlation_id)
    event_types = [record.event_type for record in records]

    assert event_types == ["proposal_created", "decision_made", "timeline_written"]
    assert all(record.correlation_id == correlation_id for record in records)
    # Content-free by design: no proposal text anywhere in the audit trail.
    for record in records:
        assert "Alex Synthetic" not in (record.outcome or "")


def test_audit_trail_records_discard_without_timeline_write() -> None:
    service = _service()
    correlation_id = "corr-audit-discard-1"

    proposal, token = service.propose(
        message_text=CLEAR_APPOINTMENT,
        correlation_id=correlation_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
    )
    service.decide(
        decision=ConfirmationDecision(
            outcome=ConfirmationOutcome.DISCARD, correlation_id=correlation_id
        ),
        token_id=token.token_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
        proposal=proposal,
    )

    records = service._audit_trail.for_correlation_id(correlation_id)
    event_types = [record.event_type for record in records]

    assert event_types == ["proposal_created", "decision_made"]


def test_required_approver_refs_captured_but_not_persisted_or_audited() -> None:
    """Asserts what the implementation truly guarantees, not fixture content.

    ``required_approver_refs`` is captured on ``IdentityContext`` for the
    duration of the call, but must not appear on the resulting
    ``TimelineEntry`` (which has no such field) or in any ``AuditRecord``
    for this correlation_id (whose schema is also content-minimized).
    """
    service = _service()
    correlation_id = "corr-child-1"

    proposal, token = service.propose(
        message_text=CLEAR_APPOINTMENT,
        correlation_id=correlation_id,
        identity=SYNTHETIC_CHILD_IDENTITY,
    )
    entry = service.decide(
        decision=ConfirmationDecision(
            outcome=ConfirmationOutcome.CONFIRM, correlation_id=correlation_id
        ),
        token_id=token.token_id,
        identity=SYNTHETIC_CHILD_IDENTITY,
        proposal=proposal,
    )

    assert entry is not None
    assert entry.subject_person_ref == SYNTHETIC_CHILD_IDENTITY.subject_person_ref
    assert not hasattr(entry, "required_approver_refs")

    records = service._audit_trail.for_correlation_id(correlation_id)
    assert len(records) == 3
    for record in records:
        assert not hasattr(record, "required_approver_refs")
        assert "member-synthetic-parent-b" not in (record.outcome or "")
        assert "member-synthetic-parent-b" not in record.event_type


def test_decision_correlation_id_mismatch_with_proposal_is_rejected() -> None:
    service = _service()
    proposal, token = service.propose(
        message_text=CLEAR_APPOINTMENT,
        correlation_id="corr-real-1",
        identity=SYNTHETIC_FAMILY_IDENTITY,
    )

    with pytest.raises(ConfirmationScopeMismatchError):
        service.decide(
            decision=ConfirmationDecision(
                outcome=ConfirmationOutcome.CONFIRM,
                correlation_id="corr-different-1",
            ),
            token_id=token.token_id,
            identity=SYNTHETIC_FAMILY_IDENTITY,
            proposal=proposal,
        )

    # The mismatch must not have consumed the token, written a timeline
    # entry, or written a "decision_made" audit record for the failed
    # attempt -- only the earlier propose() call's "proposal_created" is
    # present.
    assert not service._timeline_store.exists("corr-real-1")
    records = service._audit_trail.for_correlation_id("corr-real-1")
    assert [record.event_type for record in records] == ["proposal_created"]


def test_token_family_member_mismatch_is_rejected() -> None:
    service = _service()
    correlation_id = "corr-cross-identity-1"

    proposal, token = service.propose(
        message_text=CLEAR_APPOINTMENT,
        correlation_id=correlation_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
    )

    with pytest.raises(ConfirmationScopeMismatchError):
        service.decide(
            decision=ConfirmationDecision(
                outcome=ConfirmationOutcome.CONFIRM, correlation_id=correlation_id
            ),
            token_id=token.token_id,
            identity=SYNTHETIC_OTHER_FAMILY_IDENTITY,  # wrong family/member
            proposal=proposal,
        )

    assert not service._timeline_store.exists(correlation_id)


def test_scope_mismatch_does_not_consume_token_legitimate_decide_still_works() -> None:
    """A scope-mismatched attempt must not burn the token for its rightful
    owner -- validate-then-consume, not consume-then-validate."""
    service = _service()
    correlation_id = "corr-scope-recovery-1"

    proposal, token = service.propose(
        message_text=CLEAR_APPOINTMENT,
        correlation_id=correlation_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
    )

    with pytest.raises(ConfirmationScopeMismatchError):
        service.decide(
            decision=ConfirmationDecision(
                outcome=ConfirmationOutcome.CONFIRM, correlation_id=correlation_id
            ),
            token_id=token.token_id,
            identity=SYNTHETIC_OTHER_FAMILY_IDENTITY,
            proposal=proposal,
        )

    # The legitimate holder can still use the same token correctly.
    entry = service.decide(
        decision=ConfirmationDecision(
            outcome=ConfirmationOutcome.CONFIRM, correlation_id=correlation_id
        ),
        token_id=token.token_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
        proposal=proposal,
    )
    assert entry is not None


def test_cross_subject_substitution_at_decide_time_is_rejected() -> None:
    """A token issued for one subject must not be redeemable for a
    different subject, even with the same family_id/member_id/token_id.

    ``SYNTHETIC_FAMILY_IDENTITY`` and ``SYNTHETIC_CHILD_IDENTITY`` share the
    same family_id and member_id but have different subject_person_ref --
    exactly the substitution shape this test guards against: propose() for
    one subject, then attempt decide() for a different one.
    """
    service = _service()
    correlation_id = "corr-subject-substitution-1"

    proposal, token = service.propose(
        message_text=CLEAR_APPOINTMENT,
        correlation_id=correlation_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
    )

    with pytest.raises(ConfirmationScopeMismatchError):
        service.decide(
            decision=ConfirmationDecision(
                outcome=ConfirmationOutcome.CONFIRM, correlation_id=correlation_id
            ),
            token_id=token.token_id,
            identity=SYNTHETIC_CHILD_IDENTITY,  # same family/member, different subject
            proposal=proposal,
        )

    # The substitution attempt must not have consumed the token, written a
    # timeline entry, or written a "decision_made" audit record.
    assert not service._timeline_store.exists(correlation_id)
    records = service._audit_trail.for_correlation_id(correlation_id)
    assert [record.event_type for record in records] == ["proposal_created"]

    # The original, legitimate subject can still use the token correctly.
    entry = service.decide(
        decision=ConfirmationDecision(
            outcome=ConfirmationOutcome.CONFIRM, correlation_id=correlation_id
        ),
        token_id=token.token_id,
        identity=SYNTHETIC_FAMILY_IDENTITY,
        proposal=proposal,
    )
    assert entry is not None
    assert entry.subject_person_ref == SYNTHETIC_FAMILY_IDENTITY.subject_person_ref
