"""Strict synthetic witness state and independent continuity contracts.

No real head storage, credentials, enrollment discovery or network is provided.
The bounded whole-state encoding deliberately favors auditability over scale.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Protocol, cast

from familyos_pilot0.custody_anchor_protocol import (
    AnchorAction,
    AnchorPrincipal,
    AnchorRequest,
    AnchorResponse,
    AnchorRight,
    AnchorUnavailable,
)
from familyos_pilot0.custody_rollback_contracts import (
    RollbackCheckpoint,
    StoreIdentity,
    require_anchor_advancement,
)

MAX_REQUEST_BYTES = 16_384
MAX_STATE_BYTES = 8 * 1024 * 1024
RUNTIME_RIGHTS = frozenset({AnchorRight.READ, AnchorRight.ADVANCE, AnchorRight.EXECUTE_ONCE})


def canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def mapping(value: object, fields: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise ValueError("unexpected witness schema")
    return cast(dict[str, object], value)


def items(value: object) -> list[object]:
    if type(value) is not list:
        raise ValueError("expected exact array")
    return cast(list[object], value)


def text_value(value: object) -> str:
    if type(value) is not str or not value or len(value) > 128:
        raise ValueError("expected bounded nonempty string")
    return value


def natural(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("expected nonnegative exact integer")
    return value


def identity_document(identity: StoreIdentity) -> dict[str, object]:
    return {
        "store_instance_id": identity.store_instance_id,
        "store_epoch": identity.store_epoch,
    }


def identity_from(value: object) -> StoreIdentity:
    obj = mapping(value, {"store_instance_id", "store_epoch"})
    return StoreIdentity(text_value(obj["store_instance_id"]), natural(obj["store_epoch"]))


def checkpoint_document(checkpoint: RollbackCheckpoint | None) -> object:
    if checkpoint is None:
        return None
    return {
        "identity": identity_document(checkpoint.identity),
        "store_generation": checkpoint.store_generation,
        "store_root_digest": checkpoint.store_root_digest,
    }


def checkpoint_from(value: object) -> RollbackCheckpoint:
    obj = mapping(value, {"identity", "store_generation", "store_root_digest"})
    return RollbackCheckpoint(
        identity_from(obj["identity"]),
        natural(obj["store_generation"]),
        text_value(obj["store_root_digest"]),
    )


def request_document(request: AnchorRequest) -> dict[str, object]:
    return {
        "action": request.action.value,
        "principal": request.principal,
        "identity": identity_document(request.identity),
        "session_id": request.session_id,
        "request_id": request.request_id,
        "expected_current": checkpoint_document(request.expected_current),
        "candidate": checkpoint_document(request.candidate),
        "idempotency_key": request.idempotency_key,
        "execution_id": request.execution_id,
        "protocol_version": request.protocol_version,
    }


def request_from(value: object) -> AnchorRequest:
    obj = mapping(
        value,
        {
            "action",
            "principal",
            "identity",
            "session_id",
            "request_id",
            "expected_current",
            "candidate",
            "idempotency_key",
            "execution_id",
            "protocol_version",
        },
    )
    return AnchorRequest(
        action=AnchorAction(text_value(obj["action"])),
        principal=text_value(obj["principal"]),
        identity=identity_from(obj["identity"]),
        session_id=text_value(obj["session_id"]),
        request_id=text_value(obj["request_id"]),
        expected_current=(
            None if obj["expected_current"] is None else checkpoint_from(obj["expected_current"])
        ),
        candidate=None if obj["candidate"] is None else checkpoint_from(obj["candidate"]),
        idempotency_key=(
            None if obj["idempotency_key"] is None else text_value(obj["idempotency_key"])
        ),
        execution_id=None if obj["execution_id"] is None else text_value(obj["execution_id"]),
        protocol_version=text_value(obj["protocol_version"]),
    )


def checked_request(request: AnchorRequest) -> AnchorRequest:
    if type(request) is not AnchorRequest:
        raise ValueError("expected exact AnchorRequest")
    # Revalidate immutable nested types, including objects forged outside constructors.
    if type(request.action) is not AnchorAction or type(request.identity) is not StoreIdentity:
        raise ValueError("invalid request type")
    for checkpoint in (request.expected_current, request.candidate):
        if checkpoint is not None and type(checkpoint) is not RollbackCheckpoint:
            raise ValueError("invalid checkpoint type")
    replace(request)  # Re-run the committed request contract's validation.
    raw = canonical(request_document(request))
    if len(raw.encode()) > MAX_REQUEST_BYTES:
        raise ValueError("request exceeds synthetic bound")
    return request_from(json.loads(raw))


def receipt_request(request: AnchorRequest) -> AnchorRequest:
    return replace(request, session_id="receipt", request_id="receipt")


@dataclass(frozen=True)
class WitnessHead:
    identity: StoreIdentity
    sequence: int
    state_digest: str

    def __post_init__(self) -> None:
        # Reuse exact lineage/integer/digest validation without redefining checkpoint semantics.
        RollbackCheckpoint(self.identity, self.sequence, self.state_digest)

    def evidence(self) -> str:
        return canonical(
            {
                "domain": "familyos.synthetic-witness-head.v1",
                "identity": identity_document(self.identity),
                "sequence": self.sequence,
                "state_digest": self.state_digest,
            }
        )


class IndependentWitnessHead(Protocol):
    """Current retained authority; CAS must be atomic and durably acknowledged.

    No initialization, reset, repair or learn-first-value runtime method.
    A production backend must survive its declared restore domain independently.
    """

    def read(self) -> WitnessHead: ...

    def compare_and_set(self, expected: WitnessHead, candidate: WitnessHead) -> None: ...


@dataclass(frozen=True)
class HeadContinuity:
    backend: IndependentWitnessHead
    identity: StoreIdentity

    def require_current(self, response: AnchorResponse) -> None:
        current = self.backend.read()
        if (
            type(current) is not WitnessHead
            or current.identity != self.identity
            or response.checkpoint.identity != self.identity
            or response.continuity_evidence != current.evidence()
        ):
            raise AnchorUnavailable("witness response lacks current retained authority")


@dataclass(frozen=True)
class WitnessState:
    checkpoint: RollbackCheckpoint
    sequence: int
    principals: tuple[AnchorPrincipal, ...]
    executions: frozenset[str] = frozenset()
    receipts: tuple[AnchorRequest, ...] = ()
    policy_revision: int = 1

    def encode(self) -> str:
        raw = canonical(
            {
                "version": 1,
                "checkpoint": checkpoint_document(self.checkpoint),
                "sequence": self.sequence,
                "policy_revision": self.policy_revision,
                "principals": [
                    {"name": p.name, "rights": sorted(r.value for r in p.rights)}
                    for p in sorted(self.principals, key=lambda p: p.name)
                ],
                "executions": sorted(self.executions),
                "receipts": [
                    {"request": request_document(r), "outcome": "COMMITTED"} for r in self.receipts
                ],
            }
        )
        if len(raw.encode()) > MAX_STATE_BYTES:
            raise ValueError("synthetic witness capacity reached; no history pruning allowed")
        return raw

    def head(self) -> WitnessHead:
        return WitnessHead(
            self.checkpoint.identity,
            self.sequence,
            hashlib.sha256(
                b"familyos.synthetic-witness-state.v1\0" + self.encode().encode()
            ).hexdigest(),
        )

    @classmethod
    def decode(cls, raw: str) -> WitnessState:
        if type(raw) is not str or len(raw.encode()) > MAX_STATE_BYTES:
            raise ValueError("invalid witness state size/type")
        obj = mapping(
            json.loads(raw),
            {
                "version",
                "checkpoint",
                "sequence",
                "policy_revision",
                "principals",
                "executions",
                "receipts",
            },
        )
        if natural(obj["version"]) != 1 or natural(obj["policy_revision"]) != 1:
            raise ValueError("unsupported witness schema/policy revision")
        checkpoint = checkpoint_from(obj["checkpoint"])
        principals = []
        for value in items(obj["principals"]):
            entry = mapping(value, {"name", "rights"})
            principal = AnchorPrincipal(
                text_value(entry["name"]),
                checkpoint.identity,
                frozenset(AnchorRight(text_value(r)) for r in items(entry["rights"])),
            )
            if not principal.rights or not principal.rights <= RUNTIME_RIGHTS:
                raise ValueError("runtime policy must not contain administrative rights")
            principals.append(principal)
        if not principals or len({p.name for p in principals}) != len(principals):
            raise ValueError("missing/duplicate runtime principals")
        executions = frozenset(text_value(x) for x in items(obj["executions"]))
        receipts = []
        keys: set[tuple[str, str | None]] = set()
        consumed: set[str] = set()
        policy = {p.name: p for p in principals}
        for value in items(obj["receipts"]):
            entry = mapping(value, {"request", "outcome"})
            request = request_from(entry["request"])
            if (
                entry["outcome"] != "COMMITTED"
                or request.action is AnchorAction.READ
                or request != receipt_request(request)
                or request.identity != checkpoint.identity
                or request.principal not in policy
            ):
                raise ValueError("invalid committed receipt")
            policy[request.principal].require(request.action)
            key = (request.principal, request.idempotency_key)
            if key in keys:
                raise ValueError("duplicate idempotency receipt")
            keys.add(key)
            if request.action is AnchorAction.ADVANCE:
                assert request.expected_current is not None and request.candidate is not None
                require_anchor_advancement(
                    current=request.expected_current, candidate=request.candidate
                )
            else:
                assert request.execution_id is not None
                if request.execution_id in consumed:
                    raise ValueError("duplicate execution consumption")
                consumed.add(request.execution_id)
            receipts.append(request)
        sequence = natural(obj["sequence"])
        if executions != consumed or sequence != len(receipts):
            raise ValueError("inconsistent consumption/receipt/sequence state")
        state = cls(checkpoint, sequence, tuple(principals), executions, tuple(receipts))
        # Reject duplicate members, bools, extra fields and noncanonical normalization.
        if state.encode() != raw:
            raise ValueError("witness state is not exact canonical schema")
        return state
