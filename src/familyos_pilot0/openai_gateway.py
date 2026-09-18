"""Real OpenAI ModelGateway adapter for Pilot 0 M3.

Implements ``ModelGatewayPort`` (see ``model_gateway.py``) against the
official OpenAI Python SDK's Responses API. This is the first, and so far
only, real (non-fake) gateway -- ``FakeModelGateway`` remains untouched and
this module never references or falls back to it: a failed real call raises
a typed ``ModelGatewayError`` subclass, it never silently substitutes a fake
response.

Privacy/scope boundary (Privacy Gate A, synthetic-only for M3):

- ``store=False`` is passed explicitly on every request.
- No hosted tools (function calling, web search, file search) are enabled.
- No prompt or model output content is ever logged, printed, or embedded in
  an error message -- only metadata (exception type, field names, status
  categories).
- The API key is read only from the ``OPENAI_API_KEY`` environment variable
  by the underlying SDK's default client construction; this module never
  accepts, stores, or logs a key value itself.
- This adapter performs no retry logic of its own. The OpenAI SDK's client
  already retries a specific, bounded set of transport/rate-limit/server
  failure classes (connection errors, 408, 409, 429, and 5xx) up to
  ``max_retries`` times; everything else (including refusals, malformed
  output, and non-retryable 4xx errors) surfaces immediately as a typed
  error. Configuring ``max_retries`` on the client is preferred over
  hand-rolled retry logic -- it reuses SDK-tested behavior instead of
  duplicating it.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

import openai
from openai import OpenAI

from familyos_pilot0.errors import (
    ModelGatewayProviderError,
    ModelGatewayRefusalError,
    ModelGatewayResponseParseError,
    ModelGatewayTimeoutError,
)
from familyos_pilot0.model_gateway import GatewayExtractionResult


class _ResponsesResource(Protocol):
    """The one method this adapter actually calls on ``client.responses``."""

    def create(self, **kwargs: Any) -> Any: ...


class _ResponsesClient(Protocol):
    """The minimal client shape this adapter depends on.

    A structural protocol, not the concrete ``openai.OpenAI`` class, so a
    test double only needs to match this shape (no subclassing, no
    ``# type: ignore``) -- the same pattern ``ModelGatewayPort`` already
    uses for ``FakeModelGateway`` vs. a real provider.
    """

    responses: _ResponsesResource

DEFAULT_MODEL = "gpt-5.6-luna"
"""Cost-effective, non-frontier model. M3 is narrow structured extraction;
there is no evidence a frontier model is needed for this task."""

_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_MAX_RETRIES = 2

_SCHEMA_NAME = "gateway_extraction_result"
_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "person": {"type": ["string", "null"]},
        "event_summary": {"type": "string"},
        "date": {"type": ["string", "null"]},
        "time": {"type": ["string", "null"]},
        "confidence": {"type": "string", "enum": ["high", "low"]},
    },
    "required": ["person", "event_summary", "date", "time", "confidence"],
    "additionalProperties": False,
}
"""Manual JSON schema, not a pydantic model. ``openai`` already depends on
pydantic transitively (verified: `pip show openai` lists it under
``Requires``), but this module deliberately does not import or depend on it
directly -- a hand-written schema keeps this adapter's own public surface
and dependency contract smaller than accepting a pydantic model class would,
per the M3 request's own stated preference."""

_ALLOWED_KEYS = frozenset({"person", "event_summary", "date", "time", "confidence"})
_VALID_CONFIDENCE_VALUES = frozenset({"high", "low"})

_INSTRUCTIONS = (
    "You extract a single candidate calendar event from a short family "
    "message. Respond only with the structured fields requested. If the "
    "message contains no identifiable event, still return your best-effort "
    "summary with a null date/time and confidence \"low\". Never invent a "
    "date or time that is not reasonably inferable from the message."
)


class OpenAIModelGateway:
    """``ModelGatewayPort`` implementation calling the real OpenAI Responses
    API. See module docstring for the full privacy/retry/error boundary.
    """

    def __init__(
        self,
        *,
        client: _ResponsesClient | None = None,
        model: str = DEFAULT_MODEL,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = _DEFAULT_MAX_RETRIES,
    ) -> None:
        """``client`` is injectable for tests (any object matching
        ``_ResponsesClient``'s shape, e.g. a fake); production callers
        should leave it as ``None`` so the SDK's default client
        construction reads ``OPENAI_API_KEY`` from the environment.
        """
        self._client = client or OpenAI(timeout=timeout, max_retries=max_retries)
        self._model = model

    def extract(self, *, message_text: str) -> GatewayExtractionResult:
        try:
            response = self._client.responses.create(
                model=self._model,
                instructions=_INSTRUCTIONS,
                input=message_text,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": _SCHEMA_NAME,
                        "schema": _SCHEMA,
                        "strict": True,
                    }
                },
                store=False,
            )
        except openai.APITimeoutError as exc:
            raise ModelGatewayTimeoutError(
                "OpenAI Responses API call timed out."
            ) from exc
        except openai.APIError as exc:
            raise ModelGatewayProviderError(
                f"OpenAI Responses API call failed ({type(exc).__name__})."
            ) from exc

        return self._parse_response(response)

    def _parse_response(self, response: Any) -> GatewayExtractionResult:
        for item in getattr(response, "output", None) or []:
            if getattr(item, "type", None) == "refusal":
                raise ModelGatewayRefusalError(
                    "The model refused to produce a structured extraction."
                )
            for content in getattr(item, "content", None) or []:
                if getattr(content, "type", None) == "refusal":
                    raise ModelGatewayRefusalError(
                        "The model refused to produce a structured "
                        "extraction."
                    )

        output_text = getattr(response, "output_text", None)
        if not output_text:
            raise ModelGatewayResponseParseError(
                "OpenAI response contained no structured output text."
            )

        try:
            payload = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise ModelGatewayResponseParseError(
                "OpenAI structured output was not valid JSON."
            ) from exc

        if not isinstance(payload, dict):
            raise ModelGatewayResponseParseError(
                "OpenAI structured output was not a JSON object."
            )

        return _validate_extraction_payload(payload)


def _validate_extraction_payload(payload: dict[str, Any]) -> GatewayExtractionResult:
    """Locally re-validate a parsed structured-output payload before it is
    trusted to construct a ``GatewayExtractionResult``.

    This exists IN ADDITION to the provider's own strict Structured Outputs
    schema declaration, not instead of it: the ``strict``/
    ``additionalProperties: false`` schema is a request to the provider, not
    a runtime guarantee this process can verify on its own. A future
    SDK/provider/test-double change could return a payload that violates the
    advertised schema (wrong field types, an out-of-enum ``confidence``
    value, or unexpected extra fields), and without this check such a
    payload would silently flow into ``GatewayExtractionResult`` and onward
    into the rest of the vertical slice. Every failure here raises
    ``ModelGatewayResponseParseError`` with a metadata-only message (field
    name and expected-type category) -- never the actual received value,
    which could itself be attacker- or model-influenced content.
    """
    payload_keys = set(payload)

    missing = _ALLOWED_KEYS - payload_keys
    if missing:
        raise ModelGatewayResponseParseError(
            f"OpenAI structured output was missing required field(s): "
            f"{sorted(missing)!r}."
        )

    extra = payload_keys - _ALLOWED_KEYS
    if extra:
        raise ModelGatewayResponseParseError(
            f"OpenAI structured output contained unexpected field(s): "
            f"{sorted(extra)!r}."
        )

    person = payload["person"]
    if person is not None and not isinstance(person, str):
        raise ModelGatewayResponseParseError(
            "OpenAI structured output field 'person' had an unexpected "
            "type; expected str or null."
        )

    event_summary = payload["event_summary"]
    if not isinstance(event_summary, str) or not event_summary.strip():
        raise ModelGatewayResponseParseError(
            "OpenAI structured output field 'event_summary' must be a "
            "non-empty string."
        )

    date = payload["date"]
    if date is not None and not isinstance(date, str):
        raise ModelGatewayResponseParseError(
            "OpenAI structured output field 'date' had an unexpected type; "
            "expected str or null."
        )

    time = payload["time"]
    if time is not None and not isinstance(time, str):
        raise ModelGatewayResponseParseError(
            "OpenAI structured output field 'time' had an unexpected type; "
            "expected str or null."
        )

    confidence = payload["confidence"]
    if confidence not in _VALID_CONFIDENCE_VALUES:
        raise ModelGatewayResponseParseError(
            "OpenAI structured output field 'confidence' must be exactly "
            "'high' or 'low'."
        )

    return GatewayExtractionResult(
        person=person,
        event_summary=event_summary,
        date=date,
        time=time,
        confidence=confidence,
    )
