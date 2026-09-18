"""Boundary tests for Pilot 0 M1: no side effects, no familyos-cli imports.

These tests exist because the M1 boundary is a safety property, not just a
functional one: ``ExtractionService`` must never gain a write/confirm/
execute capability by accident, and this package must never depend on
``familyos-cli`` internals, which would violate ADR-0015.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from familyos_pilot0.extraction import ExtractionService

_FORBIDDEN_METHOD_NAME_FRAGMENTS = (
    "write",
    "confirm",
    "commit",
    "save",
    "persist",
    "execute",
    "authorize",
    "approve",
    "deploy",
)

_SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "familyos_pilot0"
_FORBIDDEN_IMPORT_PATTERN = re.compile(
    r"^\s*(from\s+familyos_cli|import\s+familyos_cli)\b", re.MULTILINE
)


def test_extraction_service_has_no_side_effect_methods() -> None:
    public_methods = [
        name
        for name, _ in inspect.getmembers(
            ExtractionService, predicate=inspect.isfunction
        )
        if not name.startswith("_")
    ]

    assert public_methods == ["extract_event"], (
        "ExtractionService must expose exactly one public method in M1; "
        f"found: {public_methods}"
    )

    for fragment in _FORBIDDEN_METHOD_NAME_FRAGMENTS:
        assert fragment not in "extract_event", (
            "extract_event's own name must not encode a side-effecting verb"
        )


def test_no_familyos_cli_import_anywhere_in_package() -> None:
    offending_files = []

    for path in _SRC_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if _FORBIDDEN_IMPORT_PATTERN.search(text):
            offending_files.append(str(path))

    assert offending_files == [], (
        "familyos_pilot0 must not import familyos_cli (ADR-0015 boundary); "
        f"offending files: {offending_files}"
    )
