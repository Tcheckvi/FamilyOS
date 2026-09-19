"""Synthetic-only tests for the Pilot 0 M6 privacy boundary."""

from __future__ import annotations

import pytest

from familyos_pilot0.errors import (
    ConsentRequiredError,
    MinorDataRejectedError,
    PrivacyPayloadError,
)
from familyos_pilot0.privacy import (
    PILOT0_EVENT_EXTRACTION_PURPOSE,
    ConsentRecord,
    ConsentStatus,
    PrivacyInput,
    build_minimized_model_payload,
)


def _active_consent(*, participant_reference: str = "adult-alpha") -> ConsentRecord:
    return ConsentRecord(
        participant_reference=participant_reference,
        policy_version="m5-v1",
        purpose=PILOT0_EVENT_EXTRACTION_PURPOSE,
        consented_at_utc="2026-09-19T00:00:00Z",
    )


def _privacy_input(**overrides: object) -> PrivacyInput:
    values: dict[str, object] = {
        "source_type": "manual_text",
        "manually_selected_text_body": "Dentist appointment Friday at 10:00.",
        "optional_event_relevant_source_timestamp": "2026-09-18T16:00:00Z",
        "pseudonymous_participant_reference": "adult-alpha",
        "ephemeral_correlation_identifier": "corr-0001",
        "contains_minor_personal_data": False,
    }
    values.update(overrides)
    return PrivacyInput(**values)  # type: ignore[arg-type]


def test_minimized_payload_contains_exactly_the_five_bound_fields() -> None:
    payload = build_minimized_model_payload(
        privacy_input=_privacy_input(),
        consent=_active_consent(),
    )

    assert payload == {
        "source_type": "manual_text",
        "manually_selected_text_body": "Dentist appointment Friday at 10:00.",
        "optional_event_relevant_source_timestamp": "2026-09-18T16:00:00Z",
        "pseudonymous_participant_reference": "adult-alpha",
        "ephemeral_correlation_identifier": "corr-0001",
    }
    assert set(payload) == {
        "source_type",
        "manually_selected_text_body",
        "optional_event_relevant_source_timestamp",
        "pseudonymous_participant_reference",
        "ephemeral_correlation_identifier",
    }


@pytest.mark.parametrize(
    "consent",
    [
        None,
        ConsentRecord(
            participant_reference="adult-alpha",
            policy_version="m5-v1",
            purpose=PILOT0_EVENT_EXTRACTION_PURPOSE,
            consented_at_utc="2026-09-19T00:00:00Z",
            status=ConsentStatus.REVOKED,
            revoked_at_utc="2026-09-19T01:00:00Z",
        ),
        ConsentRecord(
            participant_reference="different-adult",
            policy_version="m5-v1",
            purpose=PILOT0_EVENT_EXTRACTION_PURPOSE,
            consented_at_utc="2026-09-19T00:00:00Z",
        ),
        ConsentRecord(
            participant_reference="adult-alpha",
            policy_version="m5-v1",
            purpose="different purpose",
            consented_at_utc="2026-09-19T00:00:00Z",
        ),
    ],
)
def test_missing_revoked_mismatched_or_wrong_purpose_consent_fails_closed(
    consent: ConsentRecord | None,
) -> None:
    with pytest.raises(ConsentRequiredError):
        build_minimized_model_payload(
            privacy_input=_privacy_input(),
            consent=consent,
        )


def test_known_minor_personal_data_is_rejected_before_payload_creation() -> None:
    with pytest.raises(MinorDataRejectedError):
        build_minimized_model_payload(
            privacy_input=_privacy_input(contains_minor_personal_data=True),
            consent=_active_consent(),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_type", "   "),
        ("manually_selected_text_body", "\t"),
        ("pseudonymous_participant_reference", ""),
        ("ephemeral_correlation_identifier", " "),
    ],
)
def test_required_payload_fields_fail_closed_when_blank(
    field: str,
    value: str,
) -> None:
    participant_reference = (
        "adult-alpha"
        if field != "pseudonymous_participant_reference"
        else value
    )
    with pytest.raises(PrivacyPayloadError):
        build_minimized_model_payload(
            privacy_input=_privacy_input(**{field: value}),
            consent=_active_consent(
                participant_reference=participant_reference,
            ),
        )


def test_optional_timestamp_normalizes_blank_to_none() -> None:
    payload = build_minimized_model_payload(
        privacy_input=_privacy_input(
            optional_event_relevant_source_timestamp="   "
        ),
        consent=_active_consent(),
    )

    assert payload["optional_event_relevant_source_timestamp"] is None
