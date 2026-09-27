"""Static Phase-1 deployment contract checks; never install or authorize execution.

Host ownership/ACL inspection and native worker composition are separate gates.
A valid inventory must not be reported as a deployable worker.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Mapping, Sequence

FIELDS = frozenset(
    [
        "absolute_path",
        "action",
        "object_type",
        "content_sha256",
        "link_target",
        "desired_owner",
        "desired_group",
        "mode_policy",
        "acl_policy",
        "xattr_policy",
        "flags_policy",
        "replacement_policy",
        "role",
    ]
)
TARGET = "/usr/local/libexec/familyos/custody/runtime/python-3.13.15"
APP = "/usr/local/libexec/familyos/custody/app"
SHARED = frozenset(
    [
        "/",
        "/usr",
        "/usr/local",
        "/usr/local/libexec",
        "/Library",
        "/Library/Application Support",
        "/var",
        "/var/db",
        "/private",
        "/private/var",
        "/private/var/db",
    ]
)
STATE = frozenset(["/var/db/familyos/custody", "/var/db/familyos/custody/tmp"])
DIRECTORY_ROLES = frozenset(
    [
        "runtime-directory",
        "managed-config-parent",
        "custody-config-root",
        "custody-app-root",
        "application-package-directory",
        "managed-state-parent",
        "custody-state-root",
        "custody-private-tmp",
        "shared-parent-create-if-absent",
    ]
)
FILE_ROLES = frozenset(
    [
        "runtime-data",
        "approved-application-source-closure",
        "approved-worker-runtime-interpreter",
        "non-entrypoint-runtime-executable-or-native-object",
        "non-entrypoint-auxiliary-tool",
        "approved-qualification-diagnostic-only",
    ]
)
PHASE1_MODULES = frozenset(
    [
        "__init__",
        "custody_anchor_adapter",
        "custody_anchor_protocol",
        "custody_credential_helper",
        "custody_github_witness",
        "custody_rollback_contracts",
        "custody_worker_contracts",
        "custody_worker_launcher",
        "custody_worker_runtime",
    ]
)


class DeploymentContractInvalid(ValueError):
    """A static contract is incomplete or conflicts with the selected Phase-1 profile."""


# Exact R11 policy values, now enforced recursively with strict JSON types.
# This is a closed Phase-1 contract, not a caller-provided schema.
_APPROVED_PHASE1_LAUNCH: dict[str, object] = {
    "argv": [],
    "entrypoint_policy": "deny_by_default",
    "environment_allowlist": {
        "HOME": "/var/db/familyos/custody",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "TMPDIR": "/var/db/familyos/custody/tmp",
        "TZ": "UTC",
    },
    "environment_mode": "allowlist_only",
    "forbidden_environment_exact": [
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
    ],
    "forbidden_environment_prefixes": ["PYTHON", "DYLD_"],
    "import_policy": {
        "application_module": "familyos_pilot0.custody_worker_launcher",
        "application_root": "/usr/local/libexec/familyos/custody/app",
        "cwd_import_forbidden": True,
        "isolated_mode_required": True,
        "pythonpath_forbidden": True,
        "runtime_compilation_forbidden": True,
        "runtime_package_installation_forbidden": True,
        "site_import_disabled": True,
        "user_site_forbidden": True,
    },
    "interpreter": "/usr/local/libexec/familyos/custody/runtime/python-3.13.15/bin/python3.13",
    "protected_installation_readiness": "NOT_READY",
    "schema": "FamilyOS-B1-B2-Phase1-Launch-Contract-v2",
    "service_identity": {
        "admin_required": False,
        "human_present_phase1": True,
        "launch_daemon": False,
        "persistent_signer": False,
        "user": "familyos-custody",
    },
    "trust_policy": {
        "ambient_ca_directory_fallback": False,
        "ambient_system_ca_fallback": False,
        "cafile": "/usr/local/libexec/familyos/custody/runtime/python-3.13.15/openssl/ssl/cert.pem",
        "openssl_config_override": False,
        "openssl_module_override": False,
        "ssl_key_logging": False,
    },
    "worker_entrypoint_status": "UNAVAILABLE_NATIVE_COMPOSITION_NOT_QUALIFIED",
    "working_directory": "/var/db/familyos/custody",
}


def _validate_launch_value(actual: object, expected: object, path: str) -> None:
    # Equality alone accepts 0 == False and 1 == True; security booleans must
    # remain actual booleans. This also rejects tuples and malformed objects.
    if type(actual) is not type(expected):
        raise DeploymentContractInvalid(f"invalid launch policy type: {path}")
    if isinstance(expected, dict) and isinstance(actual, dict):
        if actual.keys() != expected.keys():
            raise DeploymentContractInvalid(f"invalid launch policy keys: {path}")
        for key, value in expected.items():
            _validate_launch_value(actual[key], value, f"{path}.{key}")
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(actual) != len(expected):
            raise DeploymentContractInvalid(f"invalid launch policy list: {path}")
        for index, value in enumerate(expected):
            _validate_launch_value(actual[index], value, f"{path}[{index}]")
    elif actual != expected:
        raise DeploymentContractInvalid(f"invalid launch policy value: {path}")


def validate_contract(
    rows: Sequence[Mapping[str, str]],
    launch: Mapping[str, object],
    expected_application: Mapping[str, str],
) -> None:
    """Validate exact static policy; this does not inspect or change the host."""
    by: dict[str, Mapping[str, str]] = {}
    for row in rows:
        if set(row) != FIELDS or any(not isinstance(v, str) for v in row.values()):
            raise DeploymentContractInvalid("invalid contract schema")
        path = row["absolute_path"]
        if (
            not path.startswith("/")
            or path.startswith("//")
            or posixpath.normpath(path) != path
            or any(part.startswith("._") for part in path.split("/"))
            or path in by
        ):
            raise DeploymentContractInvalid(f"invalid or duplicate path: {path}")
        by[path] = row
    required = (
        SHARED | {APP, APP + "/familyos_pilot0", TARGET + "/bin/python3.13"} | STATE
    )
    if not required.issubset(by):
        raise DeploymentContractInvalid("missing required path")
    for path, row in by.items():
        if posixpath.dirname(path) not in by:
            raise DeploymentContractInvalid(f"missing parent: {path}")
        if not (
            path in SHARED
            or path in STATE
            or path
            in {
                "/usr/local/libexec/familyos",
                "/usr/local/libexec/familyos/custody",
                "/usr/local/libexec/familyos/custody/runtime",
                APP,
                APP + "/familyos_pilot0",
                "/Library/Application Support/FamilyOS",
                "/Library/Application Support/FamilyOS/custody",
                "/var/db/familyos",
            }
            or path == TARGET
            or path.startswith(TARGET + "/")
            or path in expected_application
        ):
            raise DeploymentContractInvalid(f"unexpected deployment path: {path}")
        action, kind, role = row["action"], row["object_type"], row["role"]
        if path in SHARED and path != "/usr/local/libexec":
            expected_kind = "symlink" if path == "/var" else "dir"
            if (
                action != "inspect_existing_ancestor"
                or kind != expected_kind
                or role != "shared-ancestor"
                or row["desired_owner"] != "root"
                or row["desired_group"] != ""
                or row["replacement_policy"] != "never_replace_shared_ancestor"
                or row["mode_policy"]
                != "preserve_existing_require_root_owner_no_group_or_other_write"
                or row["acl_policy"]
                != "preserve_existing_require_no_unreviewed_write_grant"
                or row["xattr_policy"] != "preserve_existing"
                or row["flags_policy"] != "preserve_existing"
                or row["link_target"] != ("private/var" if path == "/var" else "")
                or row["content_sha256"]
            ):
                raise DeploymentContractInvalid(f"invalid shared ancestor: {path}")
            continue
        if path == "/usr/local/libexec":
            if (
                action != "inspect_or_create_shared_parent"
                or kind != "dir"
                or role != "shared-parent-create-if-absent"
                or row["replacement_policy"]
                != "inspect_if_present_create_if_absent_only_when_authorized"
            ):
                raise DeploymentContractInvalid("libexec absent-parent policy missing")
        elif action != {
            "file": "install_file",
            "dir": "create_owned_directory",
            "symlink": "install_symlink",
        }.get(kind):
            raise DeploymentContractInvalid(f"invalid action/type: {path}")
        owner = "familyos-custody" if path in STATE else "root"
        group = "staff" if path in STATE else "wheel"
        mode = "exact:0700" if path in STATE else "exact:0555"
        if kind == "file" and role in {
            "runtime-data",
            "approved-application-source-closure",
        }:
            mode = "exact:0444"
        if kind == "symlink":
            mode = "symlink"
        if (
            row["desired_owner"] != owner
            or row["desired_group"] != group
            or row["mode_policy"] != mode
            or row["acl_policy"] != "no_extended_acl_entries"
            or row["xattr_policy"] != "allowlist:none"
            or row["flags_policy"] != "allowlist:none"
        ):
            raise DeploymentContractInvalid(f"invalid metadata policy: {path}")
        if path != "/usr/local/libexec" and row["replacement_policy"] not in {
            "atomic_install_then_hash_and_metadata_verify",
            "if_existing_require_exact_metadata_else_fail",
        }:
            raise DeploymentContractInvalid(f"invalid replacement policy: {path}")
        if kind == "dir":
            if (
                role not in DIRECTORY_ROLES
                or row["content_sha256"]
                or row["link_target"]
            ):
                raise DeploymentContractInvalid(f"invalid directory: {path}")
        elif kind == "file":
            if role not in FILE_ROLES or not re.fullmatch(
                r"[0-9a-f]{64}", row["content_sha256"]
            ):
                raise DeploymentContractInvalid(f"invalid file binding: {path}")
            if row["link_target"]:
                raise DeploymentContractInvalid(f"file has link target: {path}")
        elif kind == "symlink":
            target = posixpath.normpath(
                posixpath.join(posixpath.dirname(path), row["link_target"])
            )
            if (
                role != "runtime-symlink"
                or row["content_sha256"]
                or not row["link_target"]
                or row["link_target"].startswith("/")
                or target not in by
                or not target.startswith(TARGET + "/")
                or by[target]["object_type"] != "file"
            ):
                raise DeploymentContractInvalid(f"invalid symlink: {path}")
    approved = [
        p for p, r in by.items() if r["role"] == "approved-worker-runtime-interpreter"
    ]
    if approved != [TARGET + "/bin/python3.13"]:
        raise DeploymentContractInvalid("invalid interpreter allowlist")
    app = {
        p: r["content_sha256"]
        for p, r in by.items()
        if r["role"] == "approved-application-source-closure"
    }
    required_app = {f"{APP}/familyos_pilot0/{name}.py" for name in PHASE1_MODULES}
    if set(app) != required_app or dict(expected_application) != app:
        raise DeploymentContractInvalid("application profile or hashes mismatch")
    validate_launch_policy(launch)


def validate_launch_policy(launch: Mapping[str, object]) -> None:
    """Validate the unchanged R12 policy independently of a deployment inventory."""
    if not isinstance(launch, Mapping):
        raise DeploymentContractInvalid("invalid launch policy object")
    _validate_launch_value(dict(launch), _APPROVED_PHASE1_LAUNCH, "launch")
