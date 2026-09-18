"""Boundary tests for Pilot 0 M1/M2: controlled side effects, no
familyos-cli imports.

These tests exist because the boundary is a safety property, not just a
functional one: ``ExtractionService`` must never gain a write/confirm/
execute capability by accident, ``TimelineStore`` and ``AuditTrail`` must
never gain an update/delete capability by accident (append/write-once only),
and this package must never depend on ``familyos-cli`` internals, which
would violate ADR-0015.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from familyos_pilot0.audit import AuditTrail
from familyos_pilot0.extraction import ExtractionService
from familyos_pilot0.timeline import TimelineStore

_FORBIDDEN_METHOD_NAME_FRAGMENTS = (
    "update",
    "delete",
    "remove",
    "overwrite",
    "commit",
    "execute",
    "authorize",
    "approve",
    "deploy",
)

_SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "familyos_pilot0"
_FORBIDDEN_IMPORT_PATTERN = re.compile(
    r"^\s*(from\s+familyos_cli|import\s+familyos_cli)\b", re.MULTILINE
)


def _public_methods(cls: type) -> list[str]:
    return [
        name
        for name, _ in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith("_")
    ]


def test_extraction_service_has_no_side_effect_methods() -> None:
    public_methods = _public_methods(ExtractionService)

    assert public_methods == ["extract_event"], (
        "ExtractionService must expose exactly one public method; "
        f"found: {public_methods}"
    )


def test_timeline_store_exposes_only_write_and_exists() -> None:
    public_methods = _public_methods(TimelineStore)

    assert sorted(public_methods) == ["exists", "write"], (
        "TimelineStore must expose exactly write/exists, no update/delete; "
        f"found: {public_methods}"
    )


def test_audit_trail_exposes_only_append_and_read() -> None:
    public_methods = _public_methods(AuditTrail)

    assert sorted(public_methods) == ["append", "for_correlation_id"], (
        "AuditTrail must expose exactly append/for_correlation_id, no "
        f"update/delete; found: {public_methods}"
    )


def test_no_forbidden_method_names_anywhere_in_package() -> None:
    offending: list[str] = []

    for cls in (ExtractionService, TimelineStore, AuditTrail):
        for name in _public_methods(cls):
            for fragment in _FORBIDDEN_METHOD_NAME_FRAGMENTS:
                if fragment in name:
                    offending.append(f"{cls.__name__}.{name}")

    assert offending == [], f"Forbidden side-effecting method names found: {offending}"


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
