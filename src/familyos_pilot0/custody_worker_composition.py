"""Explicit custody composition entrypoint; native operational adapters unavailable.

No executable paths, credentials, provider URLs or native qualification claims are
accepted from configuration. The only executable path is an isolated synthetic
smoke with temporary state. R12 launch policy is validated without modification.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path

from familyos_pilot0.custody_deployment_contract import validate_launch_policy
from familyos_pilot0.custody_path_boundary import CustodyPathDenied, CustodyPaths
from familyos_pilot0.custody_worker_contracts import loads_strict_json
from familyos_pilot0.custody_worker_launcher import (
    ApprovalRequest,
    HumanApproval,
    HumanApprovalProvider,
    SessionEvidence,
    SessionEvidenceProvider,
)

SYNTHETIC_PAYLOAD = "FamilyOS credential-free synthetic composition smoke"
NATIVE_DEPENDENCIES_UNAVAILABLE = (
    "qualified_native_session_provider",
    "qualified_human_approval_surface",
    "qualified_credential_helper_executable",
    "qualified_witness_transport",
    "protected_runtime_and_configuration",
)


class CompositionDenied(RuntimeError):
    """Configuration or a dependency cannot establish execution authority."""


class NativeDependencyUnavailable(CompositionDenied):
    """Native integration must be independently supplied and qualified."""


def prepare_candidate_custody_paths(
    *, custody_root: str, private_key_path: str, public_key_path: str,
    owner_uid: int, owner_gid: int,
) -> CustodyPaths:
    """Represent trusted deployment metadata only; no I/O or configuration extension.

    KeyRef remains path-free. Neither dispatch nor the smoke calls this function.
    A valid layout is not a qualified native dependency or authorization.
    """
    try:
        return CustodyPaths(
            custody_root, private_key_path, public_key_path, owner_uid, owner_gid
        )
    except CustodyPathDenied:
        raise CompositionDenied("invalid candidate custody layout") from None


@dataclass(frozen=True)
class CompositionConfig:
    mode: str
    operation_id: str
    launch_policy: Mapping[str, object]


def parse_config(text: str, *, requested_mode: str) -> CompositionConfig:
    """Reject ambiguity and validate all policy before selecting any adapter."""
    try:
        if len(text) > 65536:
            raise CompositionDenied("configuration exceeds limit")
        obj = loads_strict_json(text)
        if set(obj) != {"schema", "mode", "operation_id", "payload", "launch_policy"}:
            raise CompositionDenied("invalid composition configuration fields")
        if obj["schema"] != "FamilyOS-Custody-Composition-v1":
            raise CompositionDenied("invalid composition schema")
        mode = obj["mode"]
        if type(mode) is not str or mode not in {"smoke", "operational"}:
            raise CompositionDenied("invalid composition mode")
        if mode != requested_mode:
            raise CompositionDenied("CLI/configuration mode mismatch")
        operation = obj["operation_id"]
        if type(operation) is not str or not re.fullmatch(
            r"synthetic-[A-Za-z0-9-]{1,64}", operation
        ):
            raise CompositionDenied("only synthetic operation identifiers are accepted")
        if obj["payload"] != SYNTHETIC_PAYLOAD:
            raise CompositionDenied("only the fixed synthetic payload is accepted")
        policy = obj["launch_policy"]
        if type(policy) is not dict:
            raise CompositionDenied("invalid launch policy object")
        validate_launch_policy(policy)
        return CompositionConfig(mode, operation, policy)
    except CompositionDenied:
        raise
    except (ValueError, TypeError, KeyError, RecursionError):
        raise CompositionDenied("invalid composition configuration or policy") from None


def validate_environment(environment: Mapping[str, str]) -> None:
    """Deny inherited bypass inputs, including SSH-agent/remote-session inputs."""
    exact = {
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "SSLKEYLOGFILE",
        "OPENSSL_CONF",
        "OPENSSL_MODULES",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "SSH_AUTH_SOCK",
        "SSH_AGENT_PID",
        "SSH_CONNECTION",
        "SSH_TTY",
    }
    if any(k in exact or k.startswith(("PYTHON", "DYLD_", "SSL_CERT_")) for k in environment):
        raise CompositionDenied("forbidden inherited environment")


class CheckedSessionProvider:
    """Typed native boundary; malformed evidence never becomes local authority."""

    def __init__(self, source: SessionEvidenceProvider | None) -> None:
        self._source = source

    def current(self) -> SessionEvidence:
        if self._source is None:
            raise NativeDependencyUnavailable("native session provider unavailable")
        try:
            result = self._source.current()
        except Exception:
            raise CompositionDenied("session evidence unavailable") from None
        if type(result) is not SessionEvidence:
            raise CompositionDenied("malformed session evidence")
        for field in fields(result):
            value = getattr(result, field.name)
            if field.name in {"real_uid", "effective_uid", "saved_uid"}:
                valid = type(value) is int and value > 0
            elif field.name == "session_id":
                valid = type(value) is str and bool(value) and len(value) <= 256
            else:
                valid = type(value) is bool
            if not valid:
                raise CompositionDenied("malformed session evidence field")
        return result


class CheckedApprovalProvider:
    """Freshness and operation binding are enforced by the existing launcher."""

    def __init__(self, source: HumanApprovalProvider | None) -> None:
        self._source = source

    def approve(self, request: ApprovalRequest) -> HumanApproval:
        if self._source is None:
            raise NativeDependencyUnavailable("native approval provider unavailable")
        try:
            result = self._source.approve(request)
        except Exception:
            raise CompositionDenied("human approval unavailable") from None
        if type(result) is not HumanApproval or type(result.approved) is not bool:
            raise CompositionDenied("malformed human approval")
        for name in ("operation_id", "payload_sha256", "nonce", "session_id"):
            if type(getattr(result, name)) is not str:
                raise CompositionDenied("malformed human approval field")
        return result


def dispatch(config_text: str, *, mode: str, environment: Mapping[str, str]) -> dict[str, object]:
    """Validate first; configuration cannot register or promote native adapters."""
    config = parse_config(config_text, requested_mode=mode)
    validate_environment(environment)
    if config.mode == "operational":
        # No injectable qualification boolean/path can bypass this registry state.
        raise NativeDependencyUnavailable(
            "operational composition unavailable: " + ", ".join(NATIVE_DEPENDENCIES_UNAVAILABLE)
        )
    from familyos_pilot0.custody_composition_smoke import run_smoke
    from familyos_pilot0.custody_credential_helper import CredentialHelperDenied
    from familyos_pilot0.custody_github_witness import GitHubWitnessProtocolViolation
    from familyos_pilot0.custody_rollback_contracts import RollbackContractError
    from familyos_pilot0.custody_worker_launcher import CustodyLaunchDenied
    from familyos_pilot0.custody_worker_runtime import RuntimeClaimStoreError

    try:
        return run_smoke(config)
    except (
        CredentialHelperDenied,
        GitHubWitnessProtocolViolation,
        RollbackContractError,
        CustodyLaunchDenied,
        RuntimeClaimStoreError,
    ):
        raise CompositionDenied("synthetic composition dependency rejected execution") from None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Custody composition qualification entrypoint")
    parser.add_argument("--mode", required=True, choices=["smoke", "operational"])
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        # Bound parsing input before allocating/parsing an unbounded document.
        with args.config.open("rb") as file:
            raw = file.read(65537)
        if len(raw) > 65536:
            raise CompositionDenied("configuration exceeds limit")
        result = dispatch(raw.decode("utf-8"), mode=args.mode, environment=dict(os.environ))
    except (CompositionDenied, OSError, UnicodeError):
        print(
            json.dumps(
                {
                    "result": "DENIED",
                    "production_binding": False,
                    "native_dependencies_available": False,
                }
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
