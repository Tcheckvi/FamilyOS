from dataclasses import fields

import pytest

from familyos_pilot0.confirmation import (
    confirm_event_proposal,
    discard_event_proposal,
    edit_event_proposal,
)
from familyos_pilot0.errors import (
    ProposalDecisionError,
    ProposalTerminalStateError,
    ProposalValidationError,
)
from familyos_pilot0.proposal import (
    EventProposal,
    ProposalProvenance,
    ProposalState,
)


def _proposal() -> EventProposal:
    return EventProposal(
        proposal_id="proposal-001",
        event_title="Synthetic family appointment",
        event_start_iso="2030-01-10T09:00:00+00:00",
        provenance=ProposalProvenance(
            source_type="manual_selected_text",
            ephemeral_correlation_identifier="corr-synthetic-001",
            pseudonymous_participant_reference="adult-synthetic-a",
        ),
    )


def test_provenance_contract_is_bounded() -> None:
    assert [field.name for field in fields(ProposalProvenance)] == [
        "source_type",
        "ephemeral_correlation_identifier",
        "pseudonymous_participant_reference",
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "source_type": " ",
            "ephemeral_correlation_identifier": "corr-1",
            "pseudonymous_participant_reference": "adult-a",
        },
        {
            "source_type": "manual_selected_text",
            "ephemeral_correlation_identifier": "",
            "pseudonymous_participant_reference": "adult-a",
        },
        {
            "source_type": "manual_selected_text",
            "ephemeral_correlation_identifier": "corr-1",
            "pseudonymous_participant_reference": "\t",
        },
    ],
)
def test_blank_provenance_value_fails_closed(kwargs: dict[str, str]) -> None:
    with pytest.raises(ProposalValidationError):
        ProposalProvenance(**kwargs)


def test_proposal_is_non_authoritative_while_pending() -> None:
    proposal = _proposal()

    assert proposal.state is ProposalState.PENDING
    assert proposal.durable_write_eligible is False
    assert proposal.human_adjusted is False


def test_confirm_transition_marks_later_write_eligibility() -> None:
    proposal = confirm_event_proposal(_proposal())

    assert isinstance(proposal, EventProposal)
    assert proposal.state is ProposalState.CONFIRMED
    assert proposal.durable_write_eligible is True
    assert proposal.human_adjusted is False


def test_edit_transition_is_explicit_and_human_adjusted() -> None:
    proposal = edit_event_proposal(
        _proposal(),
        event_title="Human adjusted appointment",
        event_start_iso="2030-01-10T10:00:00+00:00",
    )

    assert isinstance(proposal, EventProposal)
    assert proposal.state is ProposalState.EDITED
    assert proposal.event_title == "Human adjusted appointment"
    assert proposal.event_start_iso == "2030-01-10T10:00:00+00:00"
    assert proposal.human_adjusted is True
    assert proposal.durable_write_eligible is True


def test_discard_transition_never_becomes_write_eligible() -> None:
    proposal = discard_event_proposal(_proposal())

    assert isinstance(proposal, EventProposal)
    assert proposal.state is ProposalState.DISCARDED
    assert proposal.durable_write_eligible is False


def test_noop_edit_fails_closed() -> None:
    with pytest.raises(ProposalDecisionError):
        edit_event_proposal(_proposal())


def test_wrong_object_fails_closed() -> None:
    with pytest.raises(ProposalValidationError):
        confirm_event_proposal(object())


@pytest.mark.parametrize(
    "terminal_proposal",
    [
        lambda: confirm_event_proposal(_proposal()),
        lambda: edit_event_proposal(_proposal(), event_title="Edited"),
        lambda: discard_event_proposal(_proposal()),
    ],
)
def test_terminal_decision_replay_fails_closed(terminal_proposal: object) -> None:
    terminal = terminal_proposal()

    with pytest.raises(ProposalTerminalStateError):
        confirm_event_proposal(terminal)
    with pytest.raises(ProposalTerminalStateError):
        discard_event_proposal(terminal)


def test_proposal_model_contains_no_raw_source_text_field() -> None:
    field_names = {field.name for field in fields(EventProposal)}

    assert "raw_text" not in field_names
    assert "source_text" not in field_names
    assert "selected_text_body" not in field_names
