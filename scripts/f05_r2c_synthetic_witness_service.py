#!/usr/bin/env python3
"""FamilyOS synthetic witness service candidate.

This runner is synthetic-only and must not be used as production authority.
It performs fail-closed startup validation before opening the mTLS listener.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import logging
import os
import signal
import sqlite3
import stat
import subprocess
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, NoReturn, cast


def fatal(message: str) -> NoReturn:
    raise RuntimeError(message)


def require_regular_file(path: Path, *, mode: int | None = None) -> None:
    if path.is_symlink() or not path.is_file():
        fatal(f"required regular file is absent or unsafe: {path}")
    if mode is not None and stat.S_IMODE(path.stat().st_mode) != mode:
        fatal(f"unexpected file mode for {path}")


def require_python_runtime(path: Path, expected_realpath: Path) -> None:
    if not path.exists():
        fatal(f"required Python runtime is absent: {path}")

    try:
        resolved = path.resolve(strict=True)
        expected = expected_realpath.resolve(strict=True)
    except OSError as exc:
        fatal(f"Python runtime resolution failed: {exc}")

    if resolved != expected:
        fatal(f"Python runtime realpath mismatch: observed={resolved} expected={expected}")

    if not resolved.is_file() or resolved.is_symlink():
        fatal(f"resolved Python runtime is not a regular file: {resolved}")

    if not os.access(resolved, os.X_OK):
        fatal(f"resolved Python runtime is not executable: {resolved}")


def require_directory(path: Path, *, mode: int | None = None) -> None:
    if path.is_symlink() or not path.is_dir():
        fatal(f"required directory is absent or unsafe: {path}")
    if mode is not None and stat.S_IMODE(path.stat().st_mode) != mode:
        fatal(f"unexpected directory mode for {path}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def diskutil_volume_uuid(mount: Path) -> str:
    proc = subprocess.run(
        ["/usr/sbin/diskutil", "info", str(mount)],
        check=True,
        text=True,
        capture_output=True,
    )
    for line in proc.stdout.splitlines():
        if line.strip().startswith("Volume UUID:"):
            return line.split(":", 1)[1].strip()
    fatal("diskutil did not report a volume UUID")


def current_interface_ipv4(interface: str) -> str:
    proc = subprocess.run(
        ["/usr/sbin/ipconfig", "getifaddr", interface],
        check=False,
        text=True,
        capture_output=True,
    )
    observed = proc.stdout.strip()
    if proc.returncode != 0 or not observed:
        fatal(f"expected network interface has no IPv4 address: {interface}")
    try:
        address = ipaddress.ip_address(observed)
    except ValueError as exc:
        fatal(f"expected network interface reported an invalid IP address: {exc}")
    if not isinstance(address, ipaddress.IPv4Address):
        fatal("expected network interface did not report an IPv4 address")
    if address.is_loopback or address.is_unspecified or address.is_multicast:
        fatal("expected network interface reported an unsafe IPv4 address")
    return str(address)


def validate_network_policy(config: dict[str, Any]) -> None:
    if config.get("bind_strategy") != "current_interface_ipv4":
        fatal("unsupported network bind strategy")
    if "bind_ip" in config:
        fatal("static bind_ip is forbidden for current-interface binding")

    interface = config.get("network_interface")
    if type(interface) is not str or not interface or len(interface) > 32:
        fatal("invalid network interface")

    port = config.get("bind_port")
    if type(port) is not int or not 1 <= port <= 65535:
        fatal("invalid network bind port")

    hostname = config.get("server_hostname")
    if type(hostname) is not str or not hostname or len(hostname) > 253:
        fatal("invalid server hostname")


def verify_sqlite_readonly(database: Path) -> None:
    uri = f"file:{database}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        value = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if value != "ok":
        fatal(f"SQLite integrity check failed: {value}")


def verify_release(release_root: Path, expected_manifest_sha: str) -> None:
    manifest = release_root / "INSTALL-MANIFEST.sha256"
    require_regular_file(manifest)
    if sha256_file(manifest) != expected_manifest_sha:
        fatal("installed release manifest SHA-256 mismatch")
    subprocess.run(
        ["/usr/bin/shasum", "-a", "256", "-c", str(manifest)],
        cwd=release_root,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def load_config(path: Path) -> dict[str, Any]:
    require_regular_file(path, mode=0o600)
    data = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    if data.get("schema_version") != 2:
        fatal("unsupported service configuration schema")
    return data


def configure_logging(config: dict[str, Any]) -> logging.Logger:
    log_path = Path(config["log_file"])
    require_directory(log_path.parent, mode=0o700)
    logger = logging.getLogger("familyos.synthetic_witness")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        log_path,
        maxBytes=int(config["log_max_bytes"]),
        backupCount=int(config["log_backup_count"]),
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.handlers.clear()
    logger.addHandler(handler)
    return logger


def validate_static_preconditions(config: dict[str, Any]) -> None:
    release_root = Path(config["release_root"])
    python_runtime = Path(config["python_runtime"])
    database = Path(config["persistent_database"])
    usb_mount = Path(config["usb_mount"])
    usb_head = Path(config["usb_head"])
    credential_root = Path(config["credential_root"])
    server_key = Path(config["server_key"])
    server_cert = Path(config["server_cert"])
    ca_cert = Path(config["ca_cert"])

    require_directory(release_root)
    verify_release(release_root, config["install_manifest_sha256"])

    require_python_runtime(
        python_runtime,
        Path(config["python_runtime_realpath"]),
    )
    require_directory(database.parent, mode=0o700)
    require_regular_file(database, mode=0o600)
    verify_sqlite_readonly(database)

    require_directory(usb_mount)
    if diskutil_volume_uuid(usb_mount) != config["usb_volume_uuid"]:
        fatal("USB volume UUID mismatch")
    require_directory(usb_head.parent, mode=0o700)
    require_regular_file(usb_head, mode=0o600)

    require_directory(credential_root, mode=0o700)
    require_regular_file(server_key, mode=0o600)
    require_regular_file(server_cert, mode=0o644)
    require_regular_file(ca_cert, mode=0o644)

    if sha256_file(server_cert) != config["server_cert_sha256"]:
        fatal("server certificate SHA-256 mismatch")
    if sha256_file(ca_cert) != config["ca_cert_sha256"]:
        fatal("CA certificate SHA-256 mismatch")
    if sha256_file(server_key) != config["server_key_sha256"]:
        fatal("server private key SHA-256 mismatch")

    validate_network_policy(config)

    allowed = config.get("allowed_client_fingerprints", [])
    if not isinstance(allowed, list) or not allowed:
        fatal("client certificate fingerprint allowlist is empty")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    logger = configure_logging(config)

    try:
        validate_static_preconditions(config)

        release_root = Path(config["release_root"])
        sys.path.insert(0, str(release_root / "src"))

        from familyos_pilot0.custody_mtls_transport import (
            SyntheticMTLSServer,
            synthetic_server_context,
        )
        from familyos_pilot0.custody_rollback_contracts import StoreIdentity
        from familyos_pilot0.custody_sqlite_witness import SQLiteWitness
        from familyos_pilot0.custody_usb_witness_head import USBWitnessHead

        identity = StoreIdentity(
            config["store_instance_id"],
            int(config["store_epoch"]),
        )
        head_path = Path(config["usb_head"])
        database = Path(config["persistent_database"])

        head = USBWitnessHead(
            head_path,
            identity=identity,
            expected_directory_device=head_path.parent.stat().st_dev,
            wait_seconds=float(config["wait_seconds"]),
        )

        # A fresh backend read must succeed before SQLiteWitness is constructed.
        observed = head.read()
        if observed.identity != identity:
            fatal("USB head identity mismatch")

        service = SQLiteWitness(
            database,
            identity=identity,
            head=head,
            wait_seconds=float(config["wait_seconds"]),
        )

        context = synthetic_server_context(
            certificate=Path(config["server_cert"]),
            private_key=Path(config["server_key"]),
            client_ca=Path(config["ca_cert"]),
        )

        peers = {
            fingerprint.lower(): "worker" for fingerprint in config["allowed_client_fingerprints"]
        }

        bind_ip = current_interface_ipv4(config["network_interface"])
        bind_port = int(config["bind_port"])

        server = SyntheticMTLSServer(
            service=service,
            context=context,
            peer_fingerprints=peers,
            host=bind_ip,
            port=bind_port,
            timeout_seconds=float(config["server_timeout_seconds"]),
        )

        if server.address != (bind_ip, bind_port):
            server.close()
            service.close()
            fatal("mTLS listener did not bind to the qualified interface address")
        if current_interface_ipv4(config["network_interface"]) != bind_ip:
            server.close()
            service.close()
            fatal("LAN binding changed during listener startup")

        stop = threading.Event()

        def request_stop(signum: int, frame: object) -> None:
            del signum, frame
            stop.set()

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)

        logger.info(
            "synthetic witness service started checkpoint=%s bind=%s:%s",
            config["canonical_checkpoint"],
            bind_ip,
            bind_port,
        )

        try:
            while not stop.is_set():
                # Fail closed if the qualified USB or LAN binding disappears.
                if diskutil_volume_uuid(Path(config["usb_mount"])) != config["usb_volume_uuid"]:
                    fatal("USB volume identity changed while service was running")
                if current_interface_ipv4(config["network_interface"]) != bind_ip:
                    fatal("LAN binding changed while service was running")
                server.serve_once()
        finally:
            server.close()
            service.close()

        logger.info("synthetic witness service stopped cleanly")
        return 0
    except BaseException as exc:
        logger.exception("synthetic witness service fail-closed: %s", exc)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
