"""Synthetic GitHub witness integration boundary for F05 B1/B2.

The module implements the existing rollback and permanent execution-fence
contracts while keeping live GitHub access and credential retrieval outside
this repository-only tranche.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum, StrEnum
from typing import Protocol

from familyos_pilot0.custody_anchor_protocol import (
    AnchorRejected,
    AnchorUncertain,
)
from familyos_pilot0.custody_rollback_contracts import (
    RollbackCheckpoint,
    require_anchor_advancement,
)

PRODUCTION_EXECUTION_AUTHORIZED = False
REAL_WITNESS_MUTATION_AUTHORIZED = False

_GIT_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_EXECUTION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_REF = re.compile(r"refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,199}\Z")


type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class GitHubWitnessProtocolViolation(RuntimeError):
    """Provider data does not satisfy the frozen FamilyOS witness protocol."""


class GitHubWitnessConflict(AnchorRejected):
    """The authoritative witness rejected the exact expected-current transition."""


class WitnessMutationOutcome(StrEnum):
    COMMITTED = "committed"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


@dataclass(frozen=True)
class GitHubWitnessSnapshot:
    """One complete authoritative provider state."""

    checkpoint: RollbackCheckpoint
    revision: str
    checkpoint_digest: str
    executions: frozenset[str]


@dataclass(frozen=True)
class GitHubWitnessMutationResult:
    """Typed outcome for one attempted authoritative ref transition."""

    outcome: WitnessMutationOutcome
    snapshot: GitHubWitnessSnapshot


class GitHubWitnessTransport(Protocol):
    """Exact-parent provider boundary.

    A concrete transport must pin repository/ref identity and publish a candidate
    whose sole parent is ``expected_revision`` with force disabled.
    """

    def read_snapshot(
        self,
        repository_id: int,
        ref: str,
    ) -> GitHubWitnessSnapshot:
        """Read the exact authoritative witness state."""

    def advance_snapshot(
        self,
        repository_id: int,
        ref: str,
        expected_revision: str,
        expected_checkpoint: RollbackCheckpoint,
        candidate: RollbackCheckpoint,
        expected_executions: frozenset[str],
        transition_digest: str,
    ) -> GitHubWitnessMutationResult:
        """Attempt one monotonic checkpoint transition."""

    def acquire_execution_snapshot(
        self,
        repository_id: int,
        ref: str,
        expected_revision: str,
        expected_checkpoint: RollbackCheckpoint,
        expected_executions: frozenset[str],
        execution_id: str,
        transition_digest: str,
    ) -> GitHubWitnessMutationResult:
        """Attempt one permanent execution-consumption transition."""


def _normalize(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"__bytes_hex__": value.hex()}
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, tuple | list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("checkpoint mapping keys must be strings")
            normalized[key] = _normalize(item)
        return normalized
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _normalize(getattr(value, field.name))
            for field in fields(value)
        }
    raise TypeError(f"unsupported checkpoint value: {type(value)!r}")


def canonical_checkpoint_bytes(checkpoint: RollbackCheckpoint) -> bytes:
    """Return deterministic bytes for protocol binding."""

    return json.dumps(
        _normalize(checkpoint),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def checkpoint_digest(checkpoint: RollbackCheckpoint) -> str:
    """SHA-256 of the canonical logical checkpoint."""

    return hashlib.sha256(canonical_checkpoint_bytes(checkpoint)).hexdigest()


def executions_digest(executions: frozenset[str]) -> str:
    """SHA-256 of the sorted permanent execution set."""

    raw = json.dumps(
        sorted(executions),
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def transition_digest(
    *,
    repository_id: int,
    ref: str,
    action: str,
    expected_revision: str,
    expected_current: RollbackCheckpoint,
    candidate: RollbackCheckpoint,
    expected_executions: frozenset[str],
    candidate_executions: frozenset[str],
    execution_id: str | None = None,
) -> str:
    """Bind provider identity, revision, checkpoint and execution state."""

    envelope: dict[str, JsonValue] = {
        "schema": "familyos.github-witness.transition.v2",
        "repository_id": repository_id,
        "ref": ref,
        "action": action,
        "expected_revision": expected_revision,
        "expected_checkpoint_sha256": checkpoint_digest(expected_current),
        "candidate_checkpoint_sha256": checkpoint_digest(candidate),
        "expected_executions_sha256": executions_digest(expected_executions),
        "candidate_executions_sha256": executions_digest(candidate_executions),
        "execution_id": execution_id,
    }
    raw = json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _valid_ref(ref: str) -> bool:
    return bool(
        _REF.fullmatch(ref)
        and ".." not in ref
        and "//" not in ref
        and "@{" not in ref
        and not ref.endswith((".", "/"))
    )


class GitHubWitnessAnchor:
    """Rollback anchor plus permanent execution fence over an injected transport."""

    def __init__(
        self,
        *,
        transport: GitHubWitnessTransport,
        repository_id: int,
        ref: str,
    ) -> None:
        if type(repository_id) is not int or repository_id <= 0:
            raise ValueError("repository_id must be a positive integer")
        if not _valid_ref(ref):
            raise ValueError("ref must be one exact valid refs/heads/... reference")
        self._transport = transport
        self._repository_id = repository_id
        self._ref = ref

    @staticmethod
    def _validate_snapshot(snapshot: GitHubWitnessSnapshot) -> None:
        if not _GIT_OID.fullmatch(snapshot.revision):
            raise GitHubWitnessProtocolViolation("invalid provider revision")
        if snapshot.checkpoint_digest != checkpoint_digest(snapshot.checkpoint):
            raise GitHubWitnessProtocolViolation("provider checkpoint digest mismatch")
        if not isinstance(snapshot.executions, frozenset):
            raise GitHubWitnessProtocolViolation("execution state must be immutable")
        if any(not _EXECUTION_ID.fullmatch(item) for item in snapshot.executions):
            raise GitHubWitnessProtocolViolation("invalid execution identifier")

    def _read(self) -> GitHubWitnessSnapshot:
        snapshot = self._transport.read_snapshot(self._repository_id, self._ref)
        self._validate_snapshot(snapshot)
        return snapshot

    @staticmethod
    def _post_send_snapshot(snapshot: GitHubWitnessSnapshot) -> GitHubWitnessSnapshot:
        try:
            GitHubWitnessAnchor._validate_snapshot(snapshot)
        except (GitHubWitnessProtocolViolation, TypeError, ValueError):
            raise AnchorUncertain(
                "witness publication returned unverifiable authoritative state"
            ) from None
        return snapshot

    def _readback_after_send(self) -> GitHubWitnessSnapshot:
        try:
            return self._post_send_snapshot(
                self._transport.read_snapshot(self._repository_id, self._ref)
            )
        except AnchorUncertain:
            raise
        except Exception:
            raise AnchorUncertain(
                "authoritative witness readback failed after publication"
            ) from None

    @staticmethod
    def _require_committed(
        result: GitHubWitnessMutationResult,
        *,
        duplicate_message: str,
    ) -> GitHubWitnessSnapshot:
        if result.outcome is WitnessMutationOutcome.DUPLICATE:
            raise AnchorRejected(duplicate_message)
        if result.outcome is WitnessMutationOutcome.REJECTED:
            raise GitHubWitnessConflict("authoritative witness rejected transition")
        if result.outcome is not WitnessMutationOutcome.COMMITTED:
            raise AnchorUncertain("witness returned an unknown mutation outcome")
        return GitHubWitnessAnchor._post_send_snapshot(result.snapshot)

    def read_checkpoint(self) -> RollbackCheckpoint:
        return self._read().checkpoint

    def advance_checkpoint(
        self,
        *,
        expected_current: RollbackCheckpoint,
        candidate: RollbackCheckpoint,
    ) -> None:
        require_anchor_advancement(current=expected_current, candidate=candidate)
        before = self._read()
        if before.checkpoint != expected_current:
            raise GitHubWitnessConflict(
                "authoritative checkpoint no longer equals expected_current"
            )

        digest = transition_digest(
            repository_id=self._repository_id,
            ref=self._ref,
            action="advance",
            expected_revision=before.revision,
            expected_current=expected_current,
            candidate=candidate,
            expected_executions=before.executions,
            candidate_executions=before.executions,
        )

        try:
            result = self._transport.advance_snapshot(
                self._repository_id,
                self._ref,
                before.revision,
                expected_current,
                candidate,
                before.executions,
                digest,
            )
        except AnchorRejected:
            raise
        except Exception:
            raise AnchorUncertain(
                "witness checkpoint publication outcome is uncertain"
            ) from None

        committed = self._require_committed(
            result,
            duplicate_message="checkpoint transition was already observed",
        )
        if committed.revision == before.revision:
            raise AnchorUncertain("provider revision did not advance")
        if committed.checkpoint != candidate:
            raise AnchorUncertain("provider committed an unexpected checkpoint")
        if committed.executions != before.executions:
            raise AnchorUncertain("checkpoint transition changed execution fences")

        readback = self._readback_after_send()
        if readback != committed:
            raise AnchorUncertain(
                "authoritative witness moved or changed after checkpoint publication"
            )

    def acquire_execution(
        self,
        *,
        expected_current: RollbackCheckpoint,
        execution_id: str,
    ) -> None:
        if not _EXECUTION_ID.fullmatch(execution_id):
            raise AnchorRejected("invalid execution identifier")

        before = self._read()
        if before.checkpoint != expected_current:
            raise GitHubWitnessConflict(
                "authoritative checkpoint no longer equals expected_current"
            )
        if execution_id in before.executions:
            raise AnchorRejected("execution already permanently consumed")

        candidate_executions = before.executions | {execution_id}
        digest = transition_digest(
            repository_id=self._repository_id,
            ref=self._ref,
            action="execute_once",
            expected_revision=before.revision,
            expected_current=expected_current,
            candidate=expected_current,
            expected_executions=before.executions,
            candidate_executions=candidate_executions,
            execution_id=execution_id,
        )

        try:
            result = self._transport.acquire_execution_snapshot(
                self._repository_id,
                self._ref,
                before.revision,
                expected_current,
                before.executions,
                execution_id,
                digest,
            )
        except AnchorRejected:
            raise
        except Exception:
            raise AnchorUncertain(
                "witness execution-consumption outcome is uncertain"
            ) from None

        committed = self._require_committed(
            result,
            duplicate_message="execution already permanently consumed",
        )
        if committed.revision == before.revision:
            raise AnchorUncertain("execution fence did not advance provider revision")
        if committed.checkpoint != expected_current:
            raise AnchorUncertain("execution fence changed logical checkpoint")
        if committed.executions != candidate_executions:
            raise AnchorUncertain("execution fence committed unexpected consumption state")

        readback = self._readback_after_send()
        if readback != committed:
            raise AnchorUncertain(
                "authoritative witness moved or changed after execution consumption"
            )
