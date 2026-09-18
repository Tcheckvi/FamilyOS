"""Extraction behavior tests for Pilot 0 M1. Synthetic data only."""

from __future__ import annotations

from familyos_pilot0.extraction import ExtractionService
from familyos_pilot0.model_gateway import FakeModelGateway
from tests.fixtures import (
    AMBIGUOUS_TIME,
    CLEAR_APPOINTMENT,
    DUPLICATE_FORWARD_OF_CLEAR_APPOINTMENT,
    SCHOOL_EVENT,
)


def _service() -> ExtractionService:
    return ExtractionService(gateway=FakeModelGateway())


def test_clear_appointment_extracts_high_confidence() -> None:
    proposal = _service().extract_event(
        message_text=CLEAR_APPOINTMENT, correlation_id="corr-clear-1"
    )

    assert proposal.confidence == "high"
    assert proposal.person == "Alex Synthetic"
    assert proposal.date == "2026-10-03"
    assert proposal.time == "14:30"
    assert proposal.capability == "pilot.timeline.extract_event"
    assert proposal.correlation_id == "corr-clear-1"


def test_ambiguous_time_extracts_low_confidence() -> None:
    proposal = _service().extract_event(
        message_text=AMBIGUOUS_TIME, correlation_id="corr-ambiguous-1"
    )

    assert proposal.confidence == "low"
    assert proposal.date is None
    assert proposal.time is None


def test_school_event_extracts_high_confidence() -> None:
    proposal = _service().extract_event(
        message_text=SCHOOL_EVENT, correlation_id="corr-school-1"
    )

    assert proposal.confidence == "high"
    assert proposal.person == "Jordan Synthetic"
    assert proposal.date == "2026-10-10"
    assert proposal.time == "16:00"


def test_correlation_id_is_preserved_across_duplicate_forward() -> None:
    service = _service()

    first = service.extract_event(
        message_text=CLEAR_APPOINTMENT, correlation_id="corr-duplicate-1"
    )
    second = service.extract_event(
        message_text=DUPLICATE_FORWARD_OF_CLEAR_APPOINTMENT,
        correlation_id="corr-duplicate-1",
    )

    assert first.correlation_id == second.correlation_id == "corr-duplicate-1"
    assert first == second
