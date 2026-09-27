"""Non-exporting one-shot credential transaction boundary.

This is a synthetic repository contract only. It never reads Keychain,
never stores a token and never contacts GitHub.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

PRODUCTION_EXECUTION_AUTHORIZED = False
RUNTIME_CREDENTIAL_ACCESS_AUTHORIZED = False
REAL_WITNESS_MUTATION_AUTHORIZED = False

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_OPERATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_REF = re.compile(r"refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,199}\Z")


class CredentialHelperDenied(RuntimeError):
    """A requested credential-backed operation is outside the fixed profile."""


class CredentialTransactionUncertain(CredentialHelperDenied):
    """A backend attempt occurred and must never be treated as safely retryable."""


class WitnessReceiptOutcome(StrEnum):
    COMMITTED = "committed"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class BoundedWitnessRequest:
    repository_id: int
    ref: str
    operation_id: str
    body_sha256: str


@dataclass(frozen=True)
class BoundedWitnessReceipt:
    repository_id: int
    ref: str
    operation_id: str
    body_sha256: str
    provider_revision: str
    outcome: WitnessReceiptOutcome


class CredentialTransactionBackend(Protocol):
    def perform(self, request: BoundedWitnessRequest) -> BoundedWitnessReceipt:
        """Execute one fixed provider transaction without exporting a secret."""


def _valid_ref(ref: str) -> bool:
    return bool(
        _REF.fullmatch(ref)
        and ".." not in ref
        and "//" not in ref
        and "@{" not in ref
        and not ref.endswith((".", "/"))
    )


def _validate_request(request: BoundedWitnessRequest) -> None:
    if type(request.repository_id) is not int or request.repository_id <= 0:
        raise CredentialHelperDenied("repository_id must be a positive integer")
    if not _valid_ref(request.ref):
        raise CredentialHelperDenied("witness ref is invalid")
    if not _OPERATION_ID.fullmatch(request.operation_id):
        raise CredentialHelperDenied("operation_id is invalid")
    if not _SHA256.fullmatch(request.body_sha256):
        raise CredentialHelperDenied("body_sha256 must be lowercase SHA-256 hex")


def _validate_receipt(
    request: BoundedWitnessRequest,
    receipt: BoundedWitnessReceipt,
) -> None:
    if type(receipt.repository_id) is not int:
        raise CredentialTransactionUncertain("credential transaction receipt invalid")
    if receipt.repository_id != request.repository_id:
        raise CredentialTransactionUncertain("credential transaction receipt invalid")
    if receipt.ref != request.ref or not _valid_ref(receipt.ref):
        raise CredentialTransactionUncertain("credential transaction receipt invalid")
    if receipt.operation_id != request.operation_id:
        raise CredentialTransactionUncertain("credential transaction receipt invalid")
    if receipt.body_sha256 != request.body_sha256:
        raise CredentialTransactionUncertain("credential transaction receipt invalid")
    if not _GIT_OID.fullmatch(receipt.provider_revision):
        raise CredentialTransactionUncertain("credential transaction receipt invalid")
    if not isinstance(receipt.outcome, WitnessReceiptOutcome):
        raise CredentialTransactionUncertain("credential transaction receipt invalid")


class OneShotCredentialHelper:
    """Constrain a credential-backed provider transaction to one bounded call."""

    def __init__(
        self,
        *,
        backend: CredentialTransactionBackend,
        repository_id: int,
        ref: str,
    ) -> None:
        if type(repository_id) is not int or repository_id <= 0:
            raise ValueError("repository_id must be a positive integer")
        if not _valid_ref(ref):
            raise ValueError("ref must be one exact valid refs/heads/... reference")
        self._backend = backend
        self._repository_id = repository_id
        self._ref = ref
        self._used = False

    def perform(self, request: BoundedWitnessRequest) -> BoundedWitnessReceipt:
        if self._used:
            raise CredentialHelperDenied("one-shot helper already consumed")

        _validate_request(request)
        if request.repository_id != self._repository_id:
            raise CredentialHelperDenied("repository identity mismatch")
        if request.ref != self._ref:
            raise CredentialHelperDenied("witness ref mismatch")

        self._used = True

        try:
            receipt = self._backend.perform(request)
        except Exception:
            raise CredentialTransactionUncertain(
                "credential transaction failed with redacted diagnostics"
            ) from None

        try:
            _validate_receipt(request, receipt)
        except CredentialTransactionUncertain:
            raise
        except Exception:
            raise CredentialTransactionUncertain(
                "credential transaction receipt invalid"
            ) from None

        return receipt
