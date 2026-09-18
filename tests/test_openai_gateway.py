"""Provider contract tests for ``OpenAIModelGateway``. No network access.

Every test uses a fake/stub OpenAI client -- no real API key is required and
no request ever leaves this process. Live-call behavior is exercised
separately, and only opt-in, by the disabled-by-default script in
``tests/live_smoke/``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx2
import openai
import pytest

from familyos_pilot0.errors import (
    ModelGatewayProviderError,
    ModelGatewayRefusalError,
    ModelGatewayResponseParseError,
    ModelGatewayTimeoutError,
)
from familyos_pilot0.model_gateway import GatewayExtractionResult
from familyos_pilot0.openai_gateway import (
    DEFAULT_MODEL,
    OpenAIModelGateway,
    _ResponsesResource,
)


@dataclass
class _FakeContentItem:
    type: str


@dataclass
class _FakeOutputItem:
    type: str
    content: list[_FakeContentItem] = field(default_factory=list)


@dataclass
class _FakeResponse:
    output_text: str | None = None
    output: list[_FakeOutputItem] = field(default_factory=list)


_Behavior = Callable[..., _FakeResponse]


class _FakeResponsesResource:
    """Stands in for ``client.responses``. ``behavior`` is a callable that
    either returns a ``_FakeResponse`` or raises."""

    def __init__(self, behavior: _Behavior) -> None:
        self._behavior = behavior
        self.last_call_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> Any:
        self.last_call_kwargs = kwargs
        return self._behavior(**kwargs)


class _FakeOpenAIClient:
    def __init__(self, resource: _FakeResponsesResource) -> None:
        # Explicitly annotated as the protocol type, not the concrete fake
        # type -- mypy checks Protocol attributes invariantly (they are
        # read/write), so a narrower inferred type would not satisfy
        # `_ResponsesClient` even though it structurally implements it.
        # Callers keep their own concretely-typed reference to `resource`
        # for introspection (e.g. `last_call_kwargs`), since that attribute
        # is a test-only detail, not part of the protocol.
        self.responses: _ResponsesResource = resource


def _valid_payload() -> str:
    return json.dumps(
        {
            "person": "Alex Synthetic",
            "event_summary": "Dentist appointment",
            "date": "2026-10-03",
            "time": "14:30",
            "confidence": "high",
        }
    )


def _gateway_with(
    behavior: _Behavior,
) -> tuple[OpenAIModelGateway, _FakeResponsesResource]:
    resource = _FakeResponsesResource(behavior)
    gateway = OpenAIModelGateway(client=_FakeOpenAIClient(resource))
    return gateway, resource


def _dummy_request() -> httpx2.Request:
    return httpx2.Request("POST", "https://api.openai.com/v1/responses")


# -- Strict schema mapping success -------------------------------------------


def test_successful_extraction_maps_structured_output_exactly() -> None:
    gateway, resource = _gateway_with(
        lambda **_: _FakeResponse(output_text=_valid_payload())
    )

    result = gateway.extract(message_text="Reminder: Dentist appointment...")

    assert result == GatewayExtractionResult(
        person="Alex Synthetic",
        event_summary="Dentist appointment",
        date="2026-10-03",
        time="14:30",
        confidence="high",
    )


def test_request_uses_store_false_and_strict_schema() -> None:
    gateway, resource = _gateway_with(
        lambda **_: _FakeResponse(output_text=_valid_payload())
    )

    gateway.extract(message_text="Reminder: Dentist appointment...")

    kwargs = resource.last_call_kwargs
    assert kwargs is not None
    assert kwargs["store"] is False
    assert kwargs["text"]["format"]["strict"] is True
    assert kwargs["text"]["format"]["type"] == "json_schema"
    assert kwargs["model"] == DEFAULT_MODEL


def test_no_hosted_tools_are_requested() -> None:
    gateway, resource = _gateway_with(
        lambda **_: _FakeResponse(output_text=_valid_payload())
    )

    gateway.extract(message_text="Reminder: Dentist appointment...")

    kwargs = resource.last_call_kwargs
    assert kwargs is not None
    assert "tools" not in kwargs


# -- Refusal handling ---------------------------------------------------------


def test_refusal_at_output_item_level_raises() -> None:
    gateway, _ = _gateway_with(
        lambda **_: _FakeResponse(output=[_FakeOutputItem(type="refusal")])
    )

    with pytest.raises(ModelGatewayRefusalError):
        gateway.extract(message_text="anything")


def test_refusal_at_content_item_level_raises() -> None:
    gateway, _ = _gateway_with(
        lambda **_: _FakeResponse(
            output=[
                _FakeOutputItem(
                    type="message", content=[_FakeContentItem(type="refusal")]
                )
            ]
        )
    )

    with pytest.raises(ModelGatewayRefusalError):
        gateway.extract(message_text="anything")


# -- Malformed / missing structured output ------------------------------------


def test_empty_output_text_raises_parse_error() -> None:
    gateway, _ = _gateway_with(lambda **_: _FakeResponse(output_text=None))

    with pytest.raises(ModelGatewayResponseParseError):
        gateway.extract(message_text="anything")


def test_invalid_json_output_text_raises_parse_error() -> None:
    gateway, _ = _gateway_with(
        lambda **_: _FakeResponse(output_text="{not valid json")
    )

    with pytest.raises(ModelGatewayResponseParseError):
        gateway.extract(message_text="anything")


def test_missing_required_field_raises_parse_error() -> None:
    incomplete = json.dumps({"person": "Alex Synthetic", "event_summary": "x"})
    gateway, _ = _gateway_with(lambda **_: _FakeResponse(output_text=incomplete))

    with pytest.raises(ModelGatewayResponseParseError):
        gateway.extract(message_text="anything")


def test_non_object_json_raises_parse_error() -> None:
    gateway, _ = _gateway_with(lambda **_: _FakeResponse(output_text="[1, 2, 3]"))

    with pytest.raises(ModelGatewayResponseParseError):
        gateway.extract(message_text="anything")


# -- Local schema/type/enum validation (defense-in-depth beyond the
#    provider's own strict Structured Outputs schema) -----------------------


def _payload_with(**overrides: Any) -> str:
    base: dict[str, Any] = {
        "person": "Alex Synthetic",
        "event_summary": "Dentist appointment",
        "date": "2026-10-03",
        "time": "14:30",
        "confidence": "high",
    }
    base.update(overrides)
    return json.dumps(base)


def test_wrong_type_for_event_summary_raises_parse_error() -> None:
    gateway, _ = _gateway_with(
        lambda **_: _FakeResponse(output_text=_payload_with(event_summary=42))
    )

    with pytest.raises(ModelGatewayResponseParseError):
        gateway.extract(message_text="anything")


def test_wrong_type_for_person_raises_parse_error() -> None:
    gateway, _ = _gateway_with(
        lambda **_: _FakeResponse(output_text=_payload_with(person=[]))
    )

    with pytest.raises(ModelGatewayResponseParseError):
        gateway.extract(message_text="anything")


def test_wrong_type_for_date_raises_parse_error() -> None:
    gateway, _ = _gateway_with(
        lambda **_: _FakeResponse(output_text=_payload_with(date={}))
    )

    with pytest.raises(ModelGatewayResponseParseError):
        gateway.extract(message_text="anything")


def test_wrong_type_for_time_raises_parse_error() -> None:
    gateway, _ = _gateway_with(
        lambda **_: _FakeResponse(output_text=_payload_with(time=3.14))
    )

    with pytest.raises(ModelGatewayResponseParseError):
        gateway.extract(message_text="anything")


def test_invalid_confidence_enum_raises_parse_error() -> None:
    gateway, _ = _gateway_with(
        lambda **_: _FakeResponse(output_text=_payload_with(confidence="medium"))
    )

    with pytest.raises(ModelGatewayResponseParseError):
        gateway.extract(message_text="anything")


def test_extra_unexpected_field_raises_parse_error() -> None:
    gateway, _ = _gateway_with(
        lambda **_: _FakeResponse(
            output_text=_payload_with(unexpected_field="surprise")
        )
    )

    with pytest.raises(ModelGatewayResponseParseError):
        gateway.extract(message_text="anything")


def test_empty_event_summary_raises_parse_error() -> None:
    gateway, _ = _gateway_with(
        lambda **_: _FakeResponse(output_text=_payload_with(event_summary=""))
    )

    with pytest.raises(ModelGatewayResponseParseError):
        gateway.extract(message_text="anything")


def test_whitespace_only_event_summary_raises_parse_error() -> None:
    gateway, _ = _gateway_with(
        lambda **_: _FakeResponse(output_text=_payload_with(event_summary="   "))
    )

    with pytest.raises(ModelGatewayResponseParseError):
        gateway.extract(message_text="anything")


def test_null_person_and_null_date_time_are_accepted() -> None:
    """None is explicitly valid for person/date/time -- only non-null,
    non-str values must be rejected."""
    gateway, _ = _gateway_with(
        lambda **_: _FakeResponse(
            output_text=_payload_with(
                person=None, date=None, time=None, confidence="low"
            )
        )
    )

    result = gateway.extract(message_text="anything")

    assert result.person is None
    assert result.date is None
    assert result.time is None
    assert result.confidence == "low"


# -- Timeout -------------------------------------------------------------------


def test_timeout_raises_model_gateway_timeout_error() -> None:
    def _raise_timeout(**_: Any) -> _FakeResponse:
        raise openai.APITimeoutError(request=_dummy_request())

    gateway, _ = _gateway_with(_raise_timeout)

    with pytest.raises(ModelGatewayTimeoutError):
        gateway.extract(message_text="anything")


# -- Retryable vs non-retryable failure ----------------------------------------


def test_other_api_error_raises_model_gateway_provider_error() -> None:
    def _raise_connection_error(**_: Any) -> _FakeResponse:
        raise openai.APIConnectionError(message="boom", request=_dummy_request())

    gateway, _ = _gateway_with(_raise_connection_error)

    with pytest.raises(ModelGatewayProviderError):
        gateway.extract(message_text="anything")


def test_default_client_configures_bounded_retries_and_timeout() -> None:
    """Verifies retry/timeout configuration without making any network
    call -- constructing the SDK client does not itself contact the API."""
    import os

    os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-a-real-key")
    gateway = OpenAIModelGateway(timeout=12.5, max_retries=3)

    client = gateway._client
    assert isinstance(client, openai.OpenAI)
    assert client.max_retries == 3
    assert client.timeout == 12.5


# -- No provider SDK types escape the ModelGatewayPort boundary --------------


def test_extract_return_type_is_gateway_extraction_result_only() -> None:
    gateway, _ = _gateway_with(
        lambda **_: _FakeResponse(output_text=_valid_payload())
    )

    result = gateway.extract(message_text="anything")

    assert type(result) is GatewayExtractionResult
    for field_name in ("person", "event_summary", "date", "time", "confidence"):
        value = getattr(result, field_name)
        assert value is None or isinstance(value, str)
