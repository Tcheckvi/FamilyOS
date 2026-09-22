"""Authoritative custody-worker claim storage and runtime provenance boundaries.

This module is the first tracked runtime slice after the pure Phase-1 contract
and validation layer. It intentionally does not perform native signing, access
real custody material, or authorize production execution.

The durable claim store is the only granting source. Caller-created ReplayClaim
objects never constitute authority here.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final, cast

from familyos_pilot0.custody_anchor_adapter import BoundedAnchorCalls
from familyos_pilot0.custody_anchor_protocol import AnchorRejected, ExecutionFenceAnchor
from familyos_pilot0.custody_rollback_contracts import (
    ExternalRollbackAnchor,
    RollbackCheckpoint,
    StoreIdentity,
    require_anchor_advancement,
    require_store_checkpoint_match,
)
from familyos_pilot0.custody_worker_contracts import (
    KeyRef,
    ReplayClaim,
    ReplayClaimState,
    SigningResult,
    claim_state_after_durable_write_failure,
    recover_claim_after_restart,
)

_STORE_VERSION: Final[int] = 1
_TERMINAL_AFTER_KEY_USE: Final[frozenset[ReplayClaimState]] = frozenset(
    {
        ReplayClaimState.SPENT_CLEAN,
        ReplayClaimState.SPENT_UNKNOWN,
        ReplayClaimState.QUARANTINED,
    }
)


class RuntimeClaimStoreError(RuntimeError):
    """Base error for authoritative runtime claim-store failures."""


class ClaimConflictError(RuntimeClaimStoreError):
    """Raised when a requested transition conflicts with authoritative state."""


class StaleClaimGenerationError(RuntimeClaimStoreError):
    """Raised when compare-and-set generation does not match authoritative state."""


class DurableWriteUncertain(RuntimeClaimStoreError):
    """A durable write failed and the transition must not be treated as success."""

    def __init__(
        self,
        message: str,
        *,
        fail_closed_state: ReplayClaimState,
    ) -> None:
        super().__init__(message)
        self.fail_closed_state = fail_closed_state


class RecoveryRequired(RuntimeClaimStoreError):
    """Unfinished anchor mutation persists; no automatic reconciliation is permitted."""


class StoreLockTimeout(RuntimeClaimStoreError):
    """The local lock could not be acquired within the configured wait bound."""


class AuthoritativeClaimStore:
    """Small durable single-authority replay/claim store.

    The store uses an advisory cross-process lock plus atomic replacement,
    file fsync, and directory fsync. Every transition reloads current state
    while holding the lock and applies a claim-generation compare-and-set.

    This slice is storage/runtime infrastructure only. Production deployment
    location, account isolation, real-key custody, and native signing remain
    outside its authorization.
    """

    def __init__(
        self,
        root: Path,
        *,
        store_identity: StoreIdentity,
        rollback_anchor: ExternalRollbackAnchor,
        fault_injector: Callable[[str], None] | None = None,
        anchor_timeout_seconds: float = 5.0,
        lock_timeout_seconds: float = 5.0,
    ) -> None:
        if type(store_identity) is not StoreIdentity:
            raise TypeError("store_identity must be an exact StoreIdentity")
        if not isinstance(rollback_anchor, ExternalRollbackAnchor):
            raise TypeError("rollback_anchor must implement ExternalRollbackAnchor")
        self._anchor_calls = BoundedAnchorCalls(anchor_timeout_seconds)
        self._lock_timeout = BoundedAnchorCalls(lock_timeout_seconds).timeout_seconds
        self._store_identity = store_identity
        self._rollback_anchor = rollback_anchor
        if not isinstance(root, Path):
            raise TypeError("root must be a pathlib.Path")
        self._root = root
        self._claims_path = root / "claims.json"
        self._lock_path = root / "claims.lock"
        self._pending_path = root / "anchor-pending.json"
        self._recovery_required = False
        self._fault_injector = fault_injector
        self._root.mkdir(parents=True, exist_ok=True)
        os.chmod(self._root, 0o700)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(fd, 0o600)
            deadline = time.monotonic() + self._lock_timeout
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise StoreLockTimeout("claim-store lock wait exceeded bound") from exc
                    time.sleep(min(0.005, remaining))
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _fault(self, phase: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(phase)

    @staticmethod
    def _claim_key(authorization_id: str, operation_id: str) -> str:
        payload = (
            f"{len(authorization_id)}:{authorization_id}{len(operation_id)}:{operation_id}"
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _decode_document(raw_text: str) -> object:
        def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise RuntimeClaimStoreError("duplicate JSON member in claim store")
                result[key] = value
            return result

        def reject_constant(value: str) -> object:
            raise RuntimeClaimStoreError("non-finite JSON constant in claim store")

        return json.loads(raw_text, object_pairs_hook=unique_object, parse_constant=reject_constant)

    def _read_document_locked(self) -> dict[str, object]:
        if not self._claims_path.exists():
            return {"version": _STORE_VERSION, "claims": {}}

        try:
            raw_text = self._claims_path.read_text(encoding="utf-8")
            raw: object = self._decode_document(raw_text)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeClaimStoreError("authoritative claim store is unreadable") from exc

        if not isinstance(raw, dict):
            raise RuntimeClaimStoreError("authoritative claim store must be a JSON object")

        document = cast(dict[str, object], raw)
        if document.get("version") != _STORE_VERSION:
            raise RuntimeClaimStoreError("unsupported authoritative claim-store version")

        claims = document.get("claims")
        if not isinstance(claims, dict):
            raise RuntimeClaimStoreError("authoritative claim store claims must be an object")

        self._validate_document(document)
        return document

    @staticmethod
    def _claims_mapping(document: dict[str, object]) -> dict[str, object]:
        claims = document.get("claims")
        if not isinstance(claims, dict):
            raise RuntimeClaimStoreError("authoritative claim store claims must be an object")
        return cast(dict[str, object], claims)

    @staticmethod
    def _serialize_claim(claim: ReplayClaim) -> dict[str, object]:
        return {
            "authorization_id": claim.authorization_id,
            "operation_id": claim.operation_id,
            "claim_generation": claim.claim_generation,
            "state": claim.state.value,
            "non_key_resources_consumed": list(claim.non_key_resources_consumed),
            "key_use_intent_durable": claim.key_use_intent_durable,
            "context_digest": claim.context_digest,
            "signing_request_digest": claim.signing_request_digest,
        }

    @staticmethod
    def _deserialize_claim(raw: object) -> ReplayClaim:
        if not isinstance(raw, dict):
            raise RuntimeClaimStoreError("stored claim must be a JSON object")

        mapping = cast(dict[str, object], raw)
        expected = {
            "authorization_id",
            "operation_id",
            "claim_generation",
            "state",
            "non_key_resources_consumed",
            "key_use_intent_durable",
            "context_digest",
            "signing_request_digest",
        }
        if set(mapping) != expected:
            raise RuntimeClaimStoreError("stored claim has an unexpected schema")

        authorization_id = mapping["authorization_id"]
        operation_id = mapping["operation_id"]
        claim_generation = mapping["claim_generation"]
        state = mapping["state"]
        resources = mapping["non_key_resources_consumed"]
        key_use_intent_durable = mapping["key_use_intent_durable"]
        context_digest = mapping["context_digest"]
        signing_request_digest = mapping["signing_request_digest"]

        if not isinstance(authorization_id, str):
            raise RuntimeClaimStoreError("stored authorization_id must be a string")
        if not isinstance(operation_id, str):
            raise RuntimeClaimStoreError("stored operation_id must be a string")
        if type(claim_generation) is not int:
            raise RuntimeClaimStoreError("stored claim_generation must be an exact int")
        if not isinstance(state, str):
            raise RuntimeClaimStoreError("stored state must be a string")
        if not isinstance(resources, list) or not all(isinstance(item, str) for item in resources):
            raise RuntimeClaimStoreError(
                "stored non_key_resources_consumed must be an array of strings"
            )
        if type(key_use_intent_durable) is not bool:
            raise RuntimeClaimStoreError("stored key_use_intent_durable must be an exact bool")
        if not isinstance(context_digest, str):
            raise RuntimeClaimStoreError("stored context_digest must be a string")
        if signing_request_digest is not None and not isinstance(signing_request_digest, str):
            raise RuntimeClaimStoreError("stored signing_request_digest must be a string or null")

        try:
            return ReplayClaim(
                authorization_id=authorization_id,
                operation_id=operation_id,
                claim_generation=claim_generation,
                state=ReplayClaimState(state),
                non_key_resources_consumed=tuple(resources),
                key_use_intent_durable=key_use_intent_durable,
                context_digest=context_digest,
                signing_request_digest=signing_request_digest,
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeClaimStoreError("stored claim violates contract invariants") from exc

    def _load_claim_locked(
        self,
        authorization_id: str,
        operation_id: str,
    ) -> ReplayClaim | None:
        document = self._read_document_locked()
        claims = self._claims_mapping(document)
        raw = claims.get(self._claim_key(authorization_id, operation_id))
        if raw is None:
            return None

        claim = self._deserialize_claim(raw)
        if claim.authorization_id != authorization_id or claim.operation_id != operation_id:
            raise RuntimeClaimStoreError("stored claim key does not match claim identity")
        return claim

    def _durable_write_document(
        self,
        document: dict[str, object],
        *,
        current: ReplayClaim | None,
    ) -> None:
        fail_closed_state = claim_state_after_durable_write_failure(
            None if current is None else current.state
        )
        payload = (
            json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
        ).encode("utf-8")

        fd = -1
        tmp_path: Path | None = None
        try:
            fd, raw_tmp_path = tempfile.mkstemp(
                prefix=".claims-",
                suffix=".tmp",
                dir=self._root,
            )
            tmp_path = Path(raw_tmp_path)
            os.fchmod(fd, 0o600)

            with os.fdopen(fd, "wb", closefd=True) as handle:
                fd = -1
                handle.write(payload)
                handle.flush()
                self._fault("before_file_fsync")
                os.fsync(handle.fileno())
                self._fault("after_file_fsync")

            os.replace(tmp_path, self._claims_path)
            tmp_path = None
            self._fault("after_replace")

            dir_fd = os.open(self._root, os.O_RDONLY)
            try:
                self._fault("before_directory_fsync")
                os.fsync(dir_fd)
                self._fault("after_directory_fsync")
            finally:
                os.close(dir_fd)

        except OSError as exc:
            raise DurableWriteUncertain(
                "durable authoritative claim-store write is uncertain",
                fail_closed_state=fail_closed_state,
            ) from exc
        finally:
            if fd >= 0:
                os.close(fd)
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _store_claim_locked(
        self,
        claim: ReplayClaim,
        *,
        current: ReplayClaim | None,
    ) -> None:
        document = self._read_document_locked()
        claims = self._claims_mapping(document)
        claims[self._claim_key(claim.authorization_id, claim.operation_id)] = self._serialize_claim(
            claim
        )
        expected_rollback_checkpoint = self._require_rollback_match_locked()
        self._durable_write_document(document, current=current)
        self._begin_anchor_mutation("advance")
        self._advance_rollback_anchor_locked(expected_rollback_checkpoint)
        self._finish_anchor_mutation()

    @staticmethod
    def _require_identity(
        claim: ReplayClaim,
        *,
        authorization_id: str,
        operation_id: str,
        context_digest: str,
    ) -> None:
        if claim.authorization_id != authorization_id:
            raise ClaimConflictError("authorization_id does not match authoritative claim")
        if claim.operation_id != operation_id:
            raise ClaimConflictError("operation_id does not match authoritative claim")
        if claim.context_digest != context_digest:
            raise ClaimConflictError("context_digest does not match authoritative claim")

    @staticmethod
    def _require_generation(claim: ReplayClaim, expected_generation: int) -> None:
        if type(expected_generation) is not int or expected_generation < 0:
            raise ValueError("expected_generation must be a non-negative exact int")
        if claim.claim_generation != expected_generation:
            raise StaleClaimGenerationError(
                "expected_generation does not match authoritative claim"
            )

    @staticmethod
    def _next_claim(
        current: ReplayClaim,
        *,
        state: ReplayClaimState,
        key_use_intent_durable: bool,
        signing_request_digest: str | None,
    ) -> ReplayClaim:
        return ReplayClaim(
            authorization_id=current.authorization_id,
            operation_id=current.operation_id,
            claim_generation=current.claim_generation + 1,
            state=state,
            non_key_resources_consumed=current.non_key_resources_consumed,
            key_use_intent_durable=key_use_intent_durable,
            context_digest=current.context_digest,
            signing_request_digest=signing_request_digest,
        )

    def reserve(
        self,
        *,
        authorization_id: str,
        operation_id: str,
        context_digest: str,
        non_key_resources_consumed: tuple[str, ...] = (),
    ) -> ReplayClaim:
        """Durably reserve one operation and bind its admitted context digest."""
        with self._locked():
            self._require_rollback_match_locked()
            current = self._load_claim_locked(authorization_id, operation_id)
            if current is not None:
                raise ClaimConflictError("operation already has authoritative claim state")

            claim = ReplayClaim(
                authorization_id=authorization_id,
                operation_id=operation_id,
                claim_generation=0,
                state=ReplayClaimState.RESOURCES_RESERVED,
                non_key_resources_consumed=non_key_resources_consumed,
                key_use_intent_durable=False,
                context_digest=context_digest,
                signing_request_digest=None,
            )
            self._store_claim_locked(claim, current=None)
            return claim

    def claim_key_use_intent(
        self,
        *,
        authorization_id: str,
        operation_id: str,
        context_digest: str,
        signing_request_digest: str,
        expected_generation: int,
    ) -> ReplayClaim:
        """Durably bind the exact signing-request digest before signer execution."""
        with self._locked():
            self._require_rollback_match_locked()
            current = self._load_claim_locked(authorization_id, operation_id)
            if current is None:
                raise ClaimConflictError("authoritative reservation is missing")

            self._require_identity(
                current,
                authorization_id=authorization_id,
                operation_id=operation_id,
                context_digest=context_digest,
            )
            self._require_generation(current, expected_generation)

            if current.state is not ReplayClaimState.RESOURCES_RESERVED:
                raise ClaimConflictError("key-use intent requires RESOURCES_RESERVED")

            claim = self._next_claim(
                current,
                state=ReplayClaimState.KEY_USE_CLAIMED,
                key_use_intent_durable=True,
                signing_request_digest=signing_request_digest,
            )
            self._store_claim_locked(claim, current=current)
            return claim

    def record_terminal(
        self,
        *,
        authorization_id: str,
        operation_id: str,
        context_digest: str,
        terminal_state: ReplayClaimState,
        expected_generation: int,
    ) -> ReplayClaim:
        """Durably record a terminal claim state using authoritative current state."""
        if type(terminal_state) is not ReplayClaimState:
            raise TypeError("terminal_state must be an exact ReplayClaimState")

        with self._locked():
            self._require_rollback_match_locked()
            current = self._load_claim_locked(authorization_id, operation_id)
            if current is None:
                raise ClaimConflictError("authoritative claim is missing")

            self._require_identity(
                current,
                authorization_id=authorization_id,
                operation_id=operation_id,
                context_digest=context_digest,
            )
            self._require_generation(current, expected_generation)

            if current.state is ReplayClaimState.RESOURCES_RESERVED:
                if terminal_state not in {
                    ReplayClaimState.NO_KEY_USE,
                    ReplayClaimState.QUARANTINED,
                }:
                    raise ClaimConflictError(
                        "reserved claim may terminate only as NO_KEY_USE or QUARANTINED"
                    )
                key_use_intent_durable = False
                signing_request_digest = None
            elif current.state is ReplayClaimState.KEY_USE_CLAIMED:
                if terminal_state not in _TERMINAL_AFTER_KEY_USE:
                    raise ClaimConflictError(
                        "claimed key use requires SPENT_CLEAN, SPENT_UNKNOWN, or QUARANTINED"
                    )
                key_use_intent_durable = True
                signing_request_digest = current.signing_request_digest
            else:
                raise ClaimConflictError("authoritative claim is already terminal")

            claim = self._next_claim(
                current,
                state=terminal_state,
                key_use_intent_durable=key_use_intent_durable,
                signing_request_digest=signing_request_digest,
            )
            self._store_claim_locked(claim, current=current)
            return claim

    def load_authoritative(
        self,
        *,
        authorization_id: str,
        operation_id: str,
    ) -> ReplayClaim | None:
        """Load authoritative state; caller-created claims are not accepted."""
        with self._locked():
            self._require_rollback_match_locked()
            return self._load_claim_locked(authorization_id, operation_id)

    def claim_for_signer(
        self,
        *,
        authorization_id: str,
        operation_id: str,
        context_digest: str,
        signing_request_digest: str,
    ) -> ReplayClaim:
        """Consume a permanent anchor execution fence before returning permission.

        Only the first confirmed consumption returns. Restart, duplicate or uncertain
        consumption never provides a second grant. The trusted caller must execute at
        most once on this return; ReplayClaim objects are not transferable permits.
        """
        with self._locked():
            expected = self._require_rollback_match_locked()
            claim = self._load_claim_locked(authorization_id, operation_id)
            if claim is None:
                raise ClaimConflictError("authoritative claim is missing")
            self._require_identity(
                claim,
                authorization_id=authorization_id,
                operation_id=operation_id,
                context_digest=context_digest,
            )
            if claim.state is not ReplayClaimState.KEY_USE_CLAIMED:
                raise ClaimConflictError("signer boundary requires KEY_USE_CLAIMED")
            if not claim.key_use_intent_durable:
                raise ClaimConflictError("key-use intent is not durable")
            if claim.signing_request_digest != signing_request_digest:
                raise ClaimConflictError(
                    "signing_request_digest does not match authoritative state"
                )
            anchor = self._rollback_anchor
            if not isinstance(anchor, ExecutionFenceAnchor):
                raise ClaimConflictError("anchor lacks R2C execution fencing")
            # Stable across clones and generations: no expiry or alternate attempt ID.
            execution_id = self._claim_key(authorization_id, operation_id)
            self._begin_anchor_mutation("execute_once")
            self._call_pending_anchor_mutation(
                lambda: anchor.acquire_execution(
                    expected_current=expected, execution_id=execution_id
                )
            )
            trusted_after = self._anchor_calls.call(anchor.read_checkpoint, mutation=False)
            require_store_checkpoint_match(observed=expected, trusted=trusted_after)
            self._finish_anchor_mutation()
            return claim

    def claim_for_release(
        self,
        *,
        authorization_id: str,
        operation_id: str,
        context_digest: str,
        signing_request_digest: str,
    ) -> ReplayClaim:
        """Reload authoritative SPENT_CLEAN state for release validation."""
        with self._locked():
            self._require_rollback_match_locked()
            claim = self._load_claim_locked(authorization_id, operation_id)
            if claim is None:
                raise ClaimConflictError("authoritative claim is missing")
            self._require_identity(
                claim,
                authorization_id=authorization_id,
                operation_id=operation_id,
                context_digest=context_digest,
            )
            if claim.state is not ReplayClaimState.SPENT_CLEAN:
                raise ClaimConflictError("release boundary requires SPENT_CLEAN")
            if not claim.key_use_intent_durable:
                raise ClaimConflictError("key-use intent is not durable")
            if claim.signing_request_digest != signing_request_digest:
                raise ClaimConflictError(
                    "signing_request_digest does not match authoritative state"
                )
            return claim

    def recover_after_restart(
        self,
        *,
        authorization_id: str,
        operation_id: str,
    ) -> ReplayClaim | None:
        """Recover in-flight claims fail-closed and persist the stricter state."""
        with self._locked():
            self._require_rollback_match_locked()
            current = self._load_claim_locked(authorization_id, operation_id)
            if current is None:
                return None

            recovered = recover_claim_after_restart(current)
            if recovered.state is current.state:
                return current

            claim = ReplayClaim(
                authorization_id=recovered.authorization_id,
                operation_id=recovered.operation_id,
                claim_generation=current.claim_generation + 1,
                state=recovered.state,
                non_key_resources_consumed=recovered.non_key_resources_consumed,
                key_use_intent_durable=recovered.key_use_intent_durable,
                context_digest=recovered.context_digest,
                signing_request_digest=recovered.signing_request_digest,
            )
            self._store_claim_locked(claim, current=current)
            return claim

    @staticmethod
    def expected_empty_rollback_checkpoint(
        store_identity: StoreIdentity,
    ) -> RollbackCheckpoint:
        """Return the externally provisioned checkpoint for an empty store."""
        if type(store_identity) is not StoreIdentity:
            raise TypeError("store_identity must be an exact StoreIdentity")
        return AuthoritativeClaimStore._rollback_checkpoint_for_document_static(
            store_identity,
            {},
        )

    @staticmethod
    def _validate_document(document: object) -> dict[str, object]:
        """Validate every v1 claim without normalizing away any committed bytes.

        Empty {} is the historical absent-store checkpoint. Previously tolerated
        extra envelope fields are denied, never dropped or silently rehashed.
        """
        if type(document) is not dict:
            raise RuntimeClaimStoreError("store must be an exact JSON object")
        if not document:
            return {}
        if set(document) != {"version", "claims"}:
            raise RuntimeClaimStoreError("unsupported store envelope or metadata")
        if type(document["version"]) is not int or document["version"] != _STORE_VERSION:
            raise RuntimeClaimStoreError("unsupported authoritative claim-store version")
        if type(document["claims"]) is not dict:
            raise RuntimeClaimStoreError("claims must be an exact object")
        claims = cast(dict[str, object], document["claims"])
        for key, raw in claims.items():
            claim = AuthoritativeClaimStore._deserialize_claim(raw)
            if key != AuthoritativeClaimStore._claim_key(
                claim.authorization_id, claim.operation_id
            ):
                raise RuntimeClaimStoreError("stored claim key does not match claim identity")
        return claims

    @staticmethod
    def _rollback_store_generation(document: object) -> int:
        """Count validated top-level claims only; preserve v1 valid-store generation."""
        claims = AuthoritativeClaimStore._validate_document(document)
        return sum(
            AuthoritativeClaimStore._deserialize_claim(raw).claim_generation + 1
            for raw in claims.values()
        )

    @staticmethod
    def _rollback_checkpoint_for_document_static(
        store_identity: StoreIdentity,
        document: object,
    ) -> RollbackCheckpoint:
        """Build the deterministic checkpoint for one durable store document."""
        if type(store_identity) is not StoreIdentity:
            raise TypeError("store_identity must be an exact StoreIdentity")

        generation = AuthoritativeClaimStore._rollback_store_generation(document)
        canonical_payload = {
            "domain": "familyos.custody.rollback-checkpoint.v1",
            "store_instance_id": store_identity.store_instance_id,
            "store_epoch": store_identity.store_epoch,
            "document": document,
        }
        try:
            canonical_bytes = json.dumps(
                canonical_payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise RuntimeClaimStoreError(
                "authoritative store document is not canonically serializable"
            ) from exc

        return RollbackCheckpoint(
            identity=store_identity,
            store_generation=generation,
            store_root_digest=hashlib.sha256(canonical_bytes).hexdigest(),
        )

    def _rollback_checkpoint_for_document(
        self,
        document: object,
    ) -> RollbackCheckpoint:
        return self._rollback_checkpoint_for_document_static(
            self._store_identity,
            document,
        )

    def _read_rollback_document_locked(self) -> object:
        """Read the exact durable JSON document used for rollback admission."""
        if not self._claims_path.exists():
            return {}

        try:
            document = self._decode_document(self._claims_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeClaimStoreError(
                "cannot read authoritative store for rollback verification"
            ) from exc

        if type(document) is not dict:
            raise RuntimeClaimStoreError("authoritative store document must be a JSON object")
        return document

    def _current_rollback_checkpoint_locked(self) -> RollbackCheckpoint:
        return self._rollback_checkpoint_for_document(self._read_rollback_document_locked())

    def _require_rollback_match_locked(self) -> RollbackCheckpoint:
        """Deny store admission unless durable state exactly matches the anchor."""
        observed = self._current_rollback_checkpoint_locked()
        trusted = self._anchor_calls.call(self._rollback_anchor.read_checkpoint, mutation=False)
        require_store_checkpoint_match(
            observed=observed,
            trusted=trusted,
        )
        if self._recovery_required or self._pending_path.exists():
            raise RecoveryRequired("unfinished anchor mutation; human recovery required")
        return observed

    def _call_pending_anchor_mutation(self, operation: Callable[[], None]) -> None:
        """Clear pending evidence only for a definite rejection of this mutation.

        Call under the store lock after _begin_anchor_mutation. Readback is outside
        this handler: its rejection cannot prove the preceding mutation did not apply.
        Cleanup errors remain RecoveryRequired; no local store repair is attempted.
        """
        try:
            self._anchor_calls.call(operation, mutation=True)
        except AnchorRejected:
            self._finish_anchor_mutation()
            raise

    def _begin_anchor_mutation(self, action: str) -> None:
        """Persist pending evidence; only confirmed success or definite rejection clears it."""
        self._recovery_required = True
        payload = json.dumps({"protocol": "r2c-pending.v1", "action": action}).encode()
        try:
            fd = os.open(self._pending_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            self._sync_root()
        except OSError as exc:
            raise RecoveryRequired("could not durably record pending anchor mutation") from exc

    def _sync_root(self) -> None:
        fd = os.open(self._root, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _finish_anchor_mutation(self) -> None:
        # Clear only after confirmed success or definite mutation rejection.
        try:
            self._pending_path.unlink()
            self._sync_root()
        except OSError as exc:
            # Keep this instance denied and restore deny evidence if unlink succeeded.
            # A failed storage device still needs deployment-specific recovery proof.
            try:
                if not self._pending_path.exists():
                    self._begin_anchor_mutation("completion_uncertain")
            except RecoveryRequired as marker_error:
                exc.add_note(str(marker_error))
            raise RecoveryRequired("pending mutation completion durability is uncertain") from exc
        self._recovery_required = False

    def export_diagnostics(self) -> dict[str, object]:
        """Local evidence only, without anchor I/O or authoritative admission.

        Atomic file replacement gives a per-file view, not a transactional snapshot.
        Do not feed this output into custody decisions. No claim contents are exported.
        """
        try:
            data = self._claims_path.read_bytes()
        except FileNotFoundError:
            data = b""
        return {
            "authoritative": False,
            "store_file_sha256": hashlib.sha256(data).hexdigest(),
            "pending_anchor_mutation": self._recovery_required or self._pending_path.exists(),
        }

    def _advance_rollback_anchor_locked(
        self,
        expected_current: RollbackCheckpoint,
    ) -> RollbackCheckpoint:
        """Advance the anchor only after the new store state is durable."""
        candidate = self._current_rollback_checkpoint_locked()
        require_anchor_advancement(
            current=expected_current,
            candidate=candidate,
        )
        self._call_pending_anchor_mutation(
            lambda: self._rollback_anchor.advance_checkpoint(
                expected_current=expected_current, candidate=candidate
            )
        )
        trusted_after = self._anchor_calls.call(
            self._rollback_anchor.read_checkpoint, mutation=False
        )
        require_store_checkpoint_match(
            observed=candidate,
            trusted=trusted_after,
        )
        return candidate


class RuntimeFactConstructor:
    """Construct exact contract facts inside the trusted runtime boundary."""

    @staticmethod
    def signing_result(
        *,
        authorization_id: str,
        operation_id: str,
        key_ref: KeyRef,
        signature_namespace: str,
        final_payload_digest: str,
        signature_sha256: str,
        signature_verified: bool,
        elapsed_at_signature_completion_seconds: int,
        signer_reaped: bool,
        custody_postconditions_verified: bool,
        evidence_sealed: bool,
    ) -> SigningResult:
        if type(key_ref) is not KeyRef:
            raise TypeError("key_ref must be an exact KeyRef")
        return SigningResult(
            authorization_id=authorization_id,
            operation_id=operation_id,
            key_ref=key_ref,
            signature_namespace=signature_namespace,
            final_payload_digest=final_payload_digest,
            signature_sha256=signature_sha256,
            signature_verified=signature_verified,
            elapsed_at_signature_completion_seconds=(elapsed_at_signature_completion_seconds),
            signer_reaped=signer_reaped,
            custody_postconditions_verified=custody_postconditions_verified,
            evidence_sealed=evidence_sealed,
        )
