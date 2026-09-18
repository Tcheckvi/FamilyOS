"""Pilot 0 extraction contract and service (M1 scope only).

``TimelineEventProposal`` is a minimal, pilot-local proposal-shaped result.
It is deliberately NOT a literal reuse of SPEC-0016's normative
``ProposedAction`` contract or its full field set — M1 uses only the fields
it actually needs, and none of SPEC-0016's authorization/validation
machinery applies here (there is no Application, Workflow, or Security/
Identity boundary in M1 to evaluate it against).

Field provenance, made explicit per the M1 request:

- ``capability``, ``rationale``, ``correlation_id`` are normative design
  references: their names and intent are taken directly from SPEC-0016's
  ``ProposedAction`` field table, because Pilot 0 is meant to generate real
  evidence toward that eventual contract.
- ``person``, ``event_summary``, ``date``, ``time``, ``confidence`` are
  pilot-local fields with no SPEC-0016 equivalent — they exist only because
  M1's specific extraction task needs them.
- SPEC-0016 fields NOT present here (``arguments`` as a generic payload,
  ``actor_ref``, ``authorized_context_ref``, ``evidence``, ``risk_hint``/
  ``approval_hint``, a separate ``idempotency_key``) are intentionally
  absent: M1 never reaches a confirmation, authorization, or execution step,
  so there is nothing yet to authorize, approve, or deduplicate against
  persisted state. ``correlation_id`` alone is sufficient for M1's identity-
  preservation test because M1 has no persistence layer to deduplicate
  against.

The Foundational Rule this pilot preserves, unconditionally: a
``TimelineEventProposal`` conveys no authorization and MUST NOT, by itself,
cause any effect. ``ExtractionService`` enforces this by construction — it
has no method that writes, confirms, or executes anything.
"""

from __future__ import annotations

from dataclasses import dataclass

from familyos_pilot0.model_gateway import ModelGatewayPort


@dataclass(frozen=True)
class TimelineEventProposal:
    """A candidate timeline event. Proposal only — never authorization."""

    capability: str
    person: str | None
    event_summary: str
    date: str | None
    time: str | None
    confidence: str  # "high" or "low"
    rationale: str
    correlation_id: str


class ExtractionService:
    """Turns raw message text into a ``TimelineEventProposal``.

    This service has exactly one responsibility: call the configured
    ``ModelGatewayPort`` and shape its result into a proposal. It has no
    method that writes a timeline, confirms a proposal, or performs any
    external action — those belong to later milestones, not M1.
    """

    _CAPABILITY = "pilot.timeline.extract_event"

    def __init__(self, gateway: ModelGatewayPort) -> None:
        self._gateway = gateway

    def extract_event(
        self, *, message_text: str, correlation_id: str
    ) -> TimelineEventProposal:
        """Produce a proposal-only extraction result. No side effects."""
        result = self._gateway.extract(message_text=message_text)

        if result.confidence == "high":
            rationale = (
                "Extracted a clear date/time and person reference from the "
                "message text."
            )
        else:
            rationale = (
                "Message text did not contain an unambiguous date/time; "
                "returning a low-confidence candidate for human review."
            )

        return TimelineEventProposal(
            capability=self._CAPABILITY,
            person=result.person,
            event_summary=result.event_summary,
            date=result.date,
            time=result.time,
            confidence=result.confidence,
            rationale=rationale,
            correlation_id=correlation_id,
        )
