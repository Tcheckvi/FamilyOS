"""Provider-neutral Model Gateway boundary for Pilot 0.

Per RFC-0017's Model Gateway direction: reasoning/extraction logic must not
depend on provider-specific behavior for the correctness of its contract.
Provider selection is a Model Gateway implementation detail, not something
Pilot 0's extraction logic should ever branch on.

M1 ships exactly one concrete implementation, ``FakeModelGateway``, which is
fully deterministic and connects to no external provider. A real provider
adapter is a later milestone, not part of M1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GatewayExtractionResult:
    """The raw, provider-neutral shape a Model Gateway call returns.

    This is intentionally smaller than SPEC-0016's ``ProposedAction``
    contract. It carries only what the Model Gateway itself is responsible
    for producing; ``ExtractionService`` (see ``extraction.py``) is
    responsible for shaping this into the pilot's proposal-shaped result.
    """

    person: str | None
    event_summary: str
    date: str | None
    time: str | None
    confidence: str  # "high" or "low"


class ModelGatewayPort(Protocol):
    """Provider-neutral extraction boundary.

    Any concrete gateway (fake, or a real provider adapter added in a later
    milestone) must implement this method with the same contract: given raw
    message text, return a structured, provider-neutral extraction result.
    Callers must not depend on which concrete implementation is behind this
    protocol.
    """

    def extract(self, *, message_text: str) -> GatewayExtractionResult:
        """Extract a candidate event from raw message text."""
        ...


class FakeModelGateway:
    """Deterministic, synthetic-only implementation of ``ModelGatewayPort``.

    Used by M1's tests to prove the extraction boundary works end-to-end
    without connecting any real external provider. Its "intelligence" is
    intentionally simple pattern matching over the synthetic fixtures — it
    is not, and is not meant to be, a real extraction model.
    """

    _DATE_TIME_PATTERN = re.compile(
        r"on (?P<date>\d{4}-\d{2}-\d{2}) at (?P<time>\d{2}:\d{2})"
    )
    _PERSON_PATTERN = re.compile(r"for ([A-Z][a-zA-Z]+ [A-Z][a-zA-Z]+)")

    def extract(self, *, message_text: str) -> GatewayExtractionResult:
        date_time_match = self._DATE_TIME_PATTERN.search(message_text)
        person_match = self._PERSON_PATTERN.search(message_text)

        if date_time_match is None:
            return GatewayExtractionResult(
                person=person_match.group(1) if person_match else None,
                event_summary=message_text.strip(),
                date=None,
                time=None,
                confidence="low",
            )

        return GatewayExtractionResult(
            person=person_match.group(1) if person_match else None,
            event_summary=message_text.strip(),
            date=date_time_match.group("date"),
            time=date_time_match.group("time"),
            confidence="high",
        )
