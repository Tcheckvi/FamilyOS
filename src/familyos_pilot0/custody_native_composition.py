"""Fixed native successor entrypoint. Unqualified prerequisites cannot execute work."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping, Sequence

from familyos_pilot0.custody_native_boundary import NativeDenied
from familyos_pilot0.custody_path_boundary import (
    CustodyPathDenied,
    CustodyPathMetadata,
    CustodyPaths,
    inspect_custody_paths,
)

GATES = {
    "N1": "complete mandatory indicator evaluation and protected session peer unqualified",
    "N2": (
        "hardware enrollment, per-intent signature and "
        "protected persistent nonce journal unqualified"
    ),
    "N3": "credential authority unavailable; native executable denies all requests",
    "N4": "helper-owned TLS/provider integration and persistent reconciliation not qualified",
    "N5": "protected runtime, peer identity and installation/launch not qualified",
}
EXACT_ENVIRONMENT = {
    "HOME": "/var/db/familyos/custody",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
    "TMPDIR": "/var/db/familyos/custody/tmp",
    "TZ": "UTC",
}


def inspect_candidate_custody_paths(paths: CustodyPaths) -> CustodyPathMetadata:
    """Metadata-only review API, never called by the blocked native entrypoint.

    No returned observation grants key use. The caller must separately authorize
    any observation of actual custody; tests use only disposable public canaries.
    """
    try:
        return inspect_custody_paths(paths)
    except CustodyPathDenied:
        raise NativeDenied("candidate custody metadata rejected") from None


def require_native_prerequisites(environment: Mapping[str, str], argv: Sequence[str]) -> None:
    if list(argv) or dict(environment) != EXACT_ENVIRONMENT:
        raise NativeDenied("native argv/environment violates closed launch contract")
    if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode:
        raise NativeDenied("native interpreter is not isolated")
    if os.getuid() != 503 or os.geteuid() != 503 or 80 in os.getgroups():
        raise NativeDenied("native service identity unavailable")
    # There is deliberately no ready/config/test override or selectable synthetic path.
    raise NativeDenied("native qualification gates unavailable: " + ",".join(GATES))


def main(argv: Sequence[str] | None = None) -> int:
    try:
        require_native_prerequisites(os.environ, sys.argv[1:] if argv is None else argv)
    except NativeDenied:
        print(
            json.dumps(
                {
                    "result": "DENIED",
                    "native_gates": dict.fromkeys(GATES, "BLOCKED"),
                    "production_binding": False,
                    "protected_install_ready": False,
                }
            )
        )
        return 2
    # No worker/helper/provider construction or state creation exists in this version.
    raise NativeDenied("unreachable native execution boundary")


if __name__ == "__main__":
    raise SystemExit(main())
