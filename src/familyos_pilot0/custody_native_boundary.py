"""Closed native invocation protocol. This candidate is not deployment-qualified."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol

from familyos_pilot0.custody_worker_contracts import loads_strict_json

PREFIX = "/usr/local/libexec/familyos/custody"
CA_FILE = PREFIX + "/runtime/python-3.13.15/openssl/ssl/cert.pem"
OWNER = "tcheckvi-Thierry"
REPOSITORY = "FamilyOS-External-Witness"
REF = "refs/heads/witness"
ENDPOINT = "https://api.github.com/graphql"
MAX_BYTES = 65_536


class NativeDenied(RuntimeError):
    """Native authority unavailable; diagnostics intentionally contain no input data."""


class NativeUncertain(NativeDenied):
    """Transaction may have occurred. Quarantine and reconcile; never automatically retry."""


class Role(StrEnum):
    SESSION = "session"
    APPROVAL = "approval"
    HELPER = "helper"
    PRESENCE = "presence"


EXECUTABLES = {role: PREFIX + "/native/familyos-custody-" + role.value for role in Role}


class NativeChannel(Protocol):
    def exchange(self, role: Role, request: bytes, *, timeout: float) -> bytes:
        """One bounded exchange; executable identity is not caller-configurable."""


class ProtectedNativeChannel:
    """Closed production boundary, not a generic subprocess runner.

    Source/build hashes alone do not establish protected ownership, signature, ancestry,
    peer identity or trusted UI. No config flag or caller-provided executable can grant
    these prerequisites. This source version cannot execute native children at all.
    Tests inject a channel into individual boundary objects, never operational config.
    """

    def exchange(self, role: Role, request: bytes, *, timeout: float) -> bytes:
        if (
            type(role) is not Role
            or type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or not 0 < timeout <= 60
            or type(request) is not bytes
            or len(request) > MAX_BYTES
        ):
            raise NativeDenied("invalid native invocation")
        raise NativeDenied("protected native executable and peer qualification unavailable")


def encode(value: Mapping[str, object]) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError):
        raise NativeDenied("invalid native request") from None
    if len(raw) > MAX_BYTES:
        raise NativeDenied("native request too large")
    return raw


def decode(raw: bytes, fields: set[str]) -> dict[str, object]:
    try:
        if type(raw) is not bytes or len(raw) > MAX_BYTES:
            raise ValueError
        obj = loads_strict_json(raw.decode("utf-8"))
        if set(obj) != fields:
            raise ValueError
        return dict(obj)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise NativeDenied("malformed native response") from None


def token(value: object, *, maximum: int = 128) -> str:
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", value):
        raise NativeDenied("invalid native binding")
    if len(value) > maximum:
        raise NativeDenied("invalid native binding")
    return value


def digest(value: object) -> str:
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise NativeDenied("invalid digest binding")
    return value


def natural(value: object) -> int:
    if type(value) is not int or value < 0:
        raise NativeDenied("invalid native integer")
    return value


def request_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
