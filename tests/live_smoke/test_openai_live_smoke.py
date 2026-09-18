"""Opt-in live smoke test for ``OpenAIModelGateway``. DISABLED BY DEFAULT.

This test makes one real network call to the OpenAI API. It is not part of
the normal ``pytest tests/`` run in any meaningful sense: it is
automatically SKIPPED unless BOTH of the following are true:

1. The environment variable ``FAMILYOS_PILOT0_ALLOW_LIVE_OPENAI_SYNTHETIC``
   is set to exactly ``"1"``.
2. ``OPENAI_API_KEY`` is present in the environment.

Even when both gates are open, this test sends ONLY the hard-coded
synthetic fixture below -- never arbitrary user or family input, and never
anything read from a file, argument, or other runtime source. This keeps
the live-call surface identical in spirit to every other synthetic-only
test in this package, while still proving the real adapter genuinely works
end to end against the live API when someone deliberately chooses to run
it.

Per Privacy Gate A (see the M3 package review document): this test's own
30-day-default-abuse-retention exposure is accepted for synthetic content
ONLY. This file must never be pointed at real family data, and doing so
would require Privacy Gate B, which remains blocked.

Run explicitly with:

    FAMILYOS_PILOT0_ALLOW_LIVE_OPENAI_SYNTHETIC=1 OPENAI_API_KEY=sk-... \\
        pytest tests/live_smoke/test_openai_live_smoke.py -v
"""

from __future__ import annotations

import os

import pytest

from familyos_pilot0.openai_gateway import OpenAIModelGateway

_ALLOW_FLAG = "FAMILYOS_PILOT0_ALLOW_LIVE_OPENAI_SYNTHETIC"

_SYNTHETIC_LIVE_SMOKE_MESSAGE = (
    "Reminder: Dentist appointment for Alex Synthetic on 2026-10-03 at 14:30."
)
"""The only message this test is ever allowed to send. Hard-coded, not a
parameter, not read from any external source."""

_gates_open = (
    os.environ.get(_ALLOW_FLAG) == "1" and "OPENAI_API_KEY" in os.environ
)


@pytest.mark.skipif(
    not _gates_open,
    reason=(
        f"Live OpenAI smoke test is disabled by default. Set both "
        f"{_ALLOW_FLAG}=1 and OPENAI_API_KEY to opt in explicitly."
    ),
)
def test_live_openai_extraction_on_synthetic_fixture() -> None:
    gateway = OpenAIModelGateway()

    result = gateway.extract(message_text=_SYNTHETIC_LIVE_SMOKE_MESSAGE)

    assert result.confidence in ("high", "low")
    assert isinstance(result.event_summary, str)
    assert result.event_summary != ""
