"""Pilot 0 privacy boundary for the first bounded M6 preparation slice.

This module is intentionally provider-agnostic. It performs no network access
and contains no mechanism for mailbox crawling, automatic fetch, background
monitoring, or account-wide ingestion.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict

from familyos_pilot0.errors import (
    ConsentRequiredError,
    MinorDataRejectedError,
    PrivacyPayloadError,
)

PILOT0_EVENT_EXTRACTION_PURPOSE = "Pilot 0 event extraction"


class ConsentStatus(StrEnum):
    """Explicit lifecycle states for a participating adult's consent."""

    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class ConsentRecord:
    """Purpose-bound consent state for one participating adult."""

    participant_reference: str
    policy_version: str
    purpose: str
    consented_at_utc: str
    status: ConsentStatus = ConsentStatus.ACTIVE
    revoked_at_utc: str | None = None

    def is_active_for(
        self,
        *,
        participant_reference: str,
        purpose: str = PILOT0_EVENT_EXTRACTION_PURPOSE,
    ) -> bool:
        """Return whether this consent is active for the requested participant/purpose."""
        return (
            self.status is ConsentStatus.ACTIVE
            and self.revoked_at_utc is None
            and self.participant_reference == participant_reference
            and self.purpose == purpose
            and bool(self.policy_version.strip())
            and bool(self.consented_at_utc.strip())
        )


class MinimizedModelPayload(TypedDict):
    """Exactly the fields permitted by the M5-bound first-slice payload."""

    source_type: str
    manually_selected_text_body: str
    optional_event_relevant_source_timestamp: str | None
    pseudonymous_participant_reference: str
    ephemeral_correlation_identifier: str


@dataclass(frozen=True, slots=True)
class PrivacyInput:
    """Synthetic-testable input to the M6-I1/M6-I2 privacy boundary."""

    source_type: str
    manually_selected_text_body: str
    pseudonymous_participant_reference: str
    ephemeral_correlation_identifier: str
    optional_event_relevant_source_timestamp: str | None = None
    contains_minor_personal_data: bool = False


def build_minimized_model_payload(
    *,
    privacy_input: PrivacyInput,
    consent: ConsentRecord | None,
) -> MinimizedModelPayload:
    """Validate M5 privacy boundaries and return the exact provider payload shape.

    This function does not call any model provider. It only validates the
    consent/minor-data boundary and constructs the five-field minimized payload.
    """
    participant_reference = privacy_input.pseudonymous_participant_reference.strip()

    if consent is None or not consent.is_active_for(
        participant_reference=participant_reference
    ):
        raise ConsentRequiredError(
            "Active, purpose-bound participating-adult consent is required."
        )

    if privacy_input.contains_minor_personal_data:
        raise MinorDataRejectedError(
            "Minor personal data is excluded from the first Pilot 0 real-data slice."
        )

    source_type = privacy_input.source_type.strip()
    selected_text = privacy_input.manually_selected_text_body.strip()
    correlation_id = privacy_input.ephemeral_correlation_identifier.strip()

    if not source_type:
        raise PrivacyPayloadError("source_type must not be blank.")
    if not selected_text:
        raise PrivacyPayloadError("manually_selected_text_body must not be blank.")
    if not participant_reference:
        raise PrivacyPayloadError(
            "pseudonymous_participant_reference must not be blank."
        )
    if not correlation_id:
        raise PrivacyPayloadError(
            "ephemeral_correlation_identifier must not be blank."
        )

    timestamp = privacy_input.optional_event_relevant_source_timestamp
    if timestamp is not None:
        timestamp = timestamp.strip() or None

    return MinimizedModelPayload(
        source_type=source_type,
        manually_selected_text_body=selected_text,
        optional_event_relevant_source_timestamp=timestamp,
        pseudonymous_participant_reference=participant_reference,
        ephemeral_correlation_identifier=correlation_id,
    )
