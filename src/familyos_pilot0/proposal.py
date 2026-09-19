"""Non-authoritative event proposal and bounded provenance model."""

from dataclasses import dataclass
from enum import StrEnum

from familyos_pilot0.errors import ProposalValidationError


class ProposalState(StrEnum):
    """Human-decision state for a non-authoritative event proposal."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    EDITED = "edited"
    DISCARDED = "discarded"


@dataclass(frozen=True)
class ProposalProvenance:
    """Bounded provenance references without raw source-content retention."""

    source_type: str
    ephemeral_correlation_identifier: str
    pseudonymous_participant_reference: str

    def __post_init__(self) -> None:
        for field_name in (
            "source_type",
            "ephemeral_correlation_identifier",
            "pseudonymous_participant_reference",
        ):
            value = getattr(self, field_name)
            if not value.strip():
                raise ProposalValidationError(
                    f"{field_name} must be a non-blank bounded provenance value"
                )


@dataclass(frozen=True)
class EventProposal:
    """Synthetic-safe, non-authoritative event proposal."""

    proposal_id: str
    event_title: str
    event_start_iso: str
    provenance: ProposalProvenance
    state: ProposalState = ProposalState.PENDING
    human_adjusted: bool = False

    def __post_init__(self) -> None:
        for field_name in ("proposal_id", "event_title", "event_start_iso"):
            value = getattr(self, field_name)
            if not value.strip():
                raise ProposalValidationError(
                    f"{field_name} must be a non-blank proposal value"
                )

    @property
    def durable_write_eligible(self) -> bool:
        """Whether a later, separately authorized durable-write path may proceed."""

        return self.state in {ProposalState.CONFIRMED, ProposalState.EDITED}
