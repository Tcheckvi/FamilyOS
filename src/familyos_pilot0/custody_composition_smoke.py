"""Credential-free synthetic adapters; never selectable by operational mode."""

from __future__ import annotations

import hashlib
import secrets
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from familyos_pilot0.custody_anchor_adapter import BoundedAnchorCalls
from familyos_pilot0.custody_credential_helper import (
    BoundedWitnessReceipt,
    BoundedWitnessRequest,
    CredentialTransactionBackend,
    OneShotCredentialHelper,
    WitnessReceiptOutcome,
)
from familyos_pilot0.custody_deployment_contract import validate_launch_policy
from familyos_pilot0.custody_github_witness import (
    GitHubWitnessAnchor,
    GitHubWitnessConflict,
    GitHubWitnessMutationResult,
    GitHubWitnessSnapshot,
    GitHubWitnessTransport,
    WitnessMutationOutcome,
    checkpoint_digest,
)
from familyos_pilot0.custody_github_witness import (
    transition_digest as compute_transition_digest,
)
from familyos_pilot0.custody_rollback_contracts import (
    RollbackCheckpoint,
    StoreIdentity,
    require_anchor_advancement,
)
from familyos_pilot0.custody_worker_composition import (
    SYNTHETIC_PAYLOAD,
    CheckedApprovalProvider,
    CheckedSessionProvider,
    CompositionConfig,
    CompositionDenied,
    NativeDependencyUnavailable,
)
from familyos_pilot0.custody_worker_contracts import ReplayClaimState
from familyos_pilot0.custody_worker_launcher import (
    ApprovalRequest,
    HumanApproval,
    HumanApprovalProvider,
    HumanPresentCustodyLauncher,
    SessionEvidence,
    SessionEvidenceProvider,
)
from familyos_pilot0.custody_worker_runtime import AuthoritativeClaimStore

SYNTHETIC_UID = 503
SYNTHETIC_REPOSITORY_ID = 1
SYNTHETIC_REF = "refs/heads/synthetic-smoke"
SYNTHETIC_IDENTITY = StoreIdentity("synthetic-composition-store", 1)


class SyntheticSession:
    def current(self) -> SessionEvidence:
        return SessionEvidence(
            real_uid=SYNTHETIC_UID,
            effective_uid=SYNTHETIC_UID,
            saved_uid=SYNTHETIC_UID,
            session_id="synthetic-session",
            local_session=True,
            gui_active=True,
            gui_unlocked=True,
            controlling_tty=True,
            is_admin=False,
            supplementary_admin=False,
            ssh_detected=False,
            su_detected=False,
            remote_control_detected=False,
            automation_detected=False,
            evidence_complete=True,
        )


class SyntheticApproval:
    def approve(self, request: ApprovalRequest) -> HumanApproval:
        return HumanApproval(
            True,
            request.operation_id,
            request.payload_sha256,
            request.nonce,
            request.session_id,
            time.monotonic(),
        )


class SyntheticHelper:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def perform(self, request: BoundedWitnessRequest) -> BoundedWitnessReceipt:
        if "execution_fence" not in self.events:
            raise CompositionDenied("synthetic helper requires execution fencing")
        self.events.append("synthetic_helper_transaction")
        return BoundedWitnessReceipt(
            request.repository_id,
            request.ref,
            request.operation_id,
            request.body_sha256,
            "1" * 40,
            WitnessReceiptOutcome.COMMITTED,
        )


class SyntheticWitnessTransport:
    """In-memory exact-CAS fake; does not make any provider/network request."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.checkpoint = AuthoritativeClaimStore.expected_empty_rollback_checkpoint(
            SYNTHETIC_IDENTITY
        )
        self.executions: frozenset[str] = frozenset()
        self.sequence = 1
        self.lock = Lock()

    def _snapshot(self) -> GitHubWitnessSnapshot:
        return GitHubWitnessSnapshot(
            self.checkpoint,
            f"{self.sequence:040x}",
            checkpoint_digest(self.checkpoint),
            self.executions,
        )

    def _identity(self, repository_id: int, ref: str) -> None:
        if repository_id != SYNTHETIC_REPOSITORY_ID or ref != SYNTHETIC_REF:
            raise GitHubWitnessConflict("synthetic witness identity mismatch")

    def _check(
        self, revision: str, checkpoint: RollbackCheckpoint, executions: frozenset[str]
    ) -> None:
        if (
            revision != f"{self.sequence:040x}"
            or checkpoint != self.checkpoint
            or executions != self.executions
        ):
            raise GitHubWitnessConflict("synthetic witness compare-and-swap conflict")

    def read_snapshot(self, repository_id: int, ref: str) -> GitHubWitnessSnapshot:
        with self.lock:
            self._identity(repository_id, ref)
            return self._snapshot()

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
        with self.lock:
            self._identity(repository_id, ref)
            self._check(expected_revision, expected_checkpoint, expected_executions)
            require_anchor_advancement(current=expected_checkpoint, candidate=candidate)
            wanted = compute_transition_digest(
                repository_id=repository_id,
                ref=ref,
                action="advance",
                expected_revision=expected_revision,
                expected_current=expected_checkpoint,
                candidate=candidate,
                expected_executions=expected_executions,
                candidate_executions=expected_executions,
            )
            if transition_digest != wanted:
                raise GitHubWitnessConflict("synthetic transition digest mismatch")
            self.checkpoint = candidate
            self.sequence += 1
            self.events.append("synthetic_witness_advance")
            return GitHubWitnessMutationResult(WitnessMutationOutcome.COMMITTED, self._snapshot())

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
        with self.lock:
            self._identity(repository_id, ref)
            self._check(expected_revision, expected_checkpoint, expected_executions)
            if execution_id in self.executions:
                raise GitHubWitnessConflict("synthetic execution already fenced")
            wanted = compute_transition_digest(
                repository_id=repository_id,
                ref=ref,
                action="execute_once",
                expected_revision=expected_revision,
                expected_current=expected_checkpoint,
                candidate=expected_checkpoint,
                expected_executions=expected_executions,
                candidate_executions=expected_executions | {execution_id},
                execution_id=execution_id,
            )
            if transition_digest != wanted:
                raise GitHubWitnessConflict("synthetic transition digest mismatch")
            self.executions = self.executions | {execution_id}
            self.sequence += 1
            self.events.append("execution_fence")
            return GitHubWitnessMutationResult(WitnessMutationOutcome.COMMITTED, self._snapshot())


@dataclass(frozen=True)
class SmokeBindings:
    session: SessionEvidenceProvider | None
    approval: HumanApprovalProvider | None
    helper: CredentialTransactionBackend | None
    transport: GitHubWitnessTransport | None
    events: list[str]


def synthetic_bindings() -> SmokeBindings:
    events: list[str] = []
    return SmokeBindings(
        SyntheticSession(),
        SyntheticApproval(),
        SyntheticHelper(events),
        SyntheticWitnessTransport(events),
        events,
    )


def run_smoke(
    config: CompositionConfig, *, bindings: SmokeBindings | None = None
) -> dict[str, object]:
    """Exercise ceremony, durable claims, fencing and one helper call in temporary state."""
    validate_launch_policy(config.launch_policy)
    if config.mode != "smoke":
        raise CompositionDenied("synthetic adapters forbidden in operational mode")
    chosen = synthetic_bindings() if bindings is None else bindings
    if chosen.helper is None or chosen.transport is None:
        raise NativeDependencyUnavailable("synthetic test dependency unavailable")
    launcher = HumanPresentCustodyLauncher(
        expected_custody_uid=SYNTHETIC_UID,
        session_provider=CheckedSessionProvider(chosen.session),
        approval_provider=CheckedApprovalProvider(chosen.approval),
        clock=time.monotonic,
        nonce_factory=lambda: secrets.token_hex(32),
    )
    payload = SYNTHETIC_PAYLOAD.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    grant = launcher.authorize(operation_id=config.operation_id, canonical_payload=payload)
    anchor = GitHubWitnessAnchor(
        transport=chosen.transport, repository_id=SYNTHETIC_REPOSITORY_ID, ref=SYNTHETIC_REF
    )
    helper = OneShotCredentialHelper(
        backend=chosen.helper, repository_id=SYNTHETIC_REPOSITORY_ID, ref=SYNTHETIC_REF
    )
    # No caller-supplied state path: protected/real state cannot be selected here.
    with tempfile.TemporaryDirectory(prefix="familyos-synthetic-composition-") as temporary:
        store = AuthoritativeClaimStore(
            Path(temporary) / "claims",
            store_identity=SYNTHETIC_IDENTITY,
            rollback_anchor=anchor,
            anchor_timeout_seconds=1.0,
            lock_timeout_seconds=1.0,
        )
        args = dict(
            authorization_id="synthetic-authorization",
            operation_id=config.operation_id,
            context_digest=digest,
        )
        reserved = store.reserve(
            authorization_id=args["authorization_id"],
            operation_id=args["operation_id"],
            context_digest=args["context_digest"],
        )
        claimed = store.claim_key_use_intent(
            **args, signing_request_digest=digest, expected_generation=reserved.claim_generation
        )
        launcher.consume_grant(
            grant=grant, operation_id=config.operation_id, canonical_payload=payload
        )
        store.claim_for_signer(**args, signing_request_digest=digest)
        receipt = BoundedAnchorCalls(1.0).call(
            lambda: helper.perform(
                BoundedWitnessRequest(
                    SYNTHETIC_REPOSITORY_ID, SYNTHETIC_REF, config.operation_id, digest
                )
            ),
            mutation=True,
        )
        if receipt.outcome is not WitnessReceiptOutcome.COMMITTED:
            raise CompositionDenied("synthetic helper did not commit")
        terminal = store.record_terminal(
            **args,
            terminal_state=ReplayClaimState.QUARANTINED,
            expected_generation=claimed.claim_generation,
        )
    return {
        "result": "SYNTHETIC_SMOKE_PASS",
        "synthetic_only": True,
        "native_session_qualified": False,
        "native_dependencies_available": False,
        "claim_state": terminal.state.value,
        "events": list(chosen.events),
        "real_key_access": False,
        "signatures_created": 0,
        "provider_mutations": 0,
        "production_binding": False,
        "protected_installation_readiness": "NOT_READY",
    }
