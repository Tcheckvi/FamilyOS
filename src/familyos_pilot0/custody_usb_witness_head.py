"""Synthetic removable-media continuity head with durable exact CAS.

This module has no default path and no runtime enrollment, reset, repair, or
fallback behavior.  Its filesystem claims are limited to the explicit path and
device identity supplied by trusted synthetic deployment code.
"""

from __future__ import annotations

import errno
import fcntl
import json
import math
import os
import stat
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from familyos_pilot0.custody_anchor_protocol import (
    AnchorPrincipal,
    AnchorRejected,
    AnchorRight,
    AnchorUnavailable,
    AnchorUncertain,
)
from familyos_pilot0.custody_rollback_contracts import StoreIdentity
from familyos_pilot0.custody_witness_state import (
    WitnessHead,
    canonical,
    identity_from,
    mapping,
    natural,
    text_value,
)

MAX_HEAD_BYTES = 4_096


def _head_document(head: WitnessHead) -> dict[str, object]:
    return {
        "domain": "familyos.synthetic-witness-head.v1",
        "identity": {
            "store_epoch": head.identity.store_epoch,
            "store_instance_id": head.identity.store_instance_id,
        },
        "sequence": head.sequence,
        "state_digest": head.state_digest,
    }


def _encode(head: WitnessHead) -> bytes:
    if type(head) is not WitnessHead:
        raise ValueError("exact witness head required")
    raw = canonical(_head_document(head)).encode()
    if len(raw) > MAX_HEAD_BYTES:
        raise ValueError("head exceeds synthetic bound")
    return raw


def _decode(raw: bytes) -> WitnessHead:
    if not raw or len(raw) > MAX_HEAD_BYTES:
        raise ValueError("invalid head size")
    try:
        text = raw.decode("ascii")
        value = json.loads(text, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("malformed witness head") from exc
    obj = mapping(value, {"domain", "identity", "sequence", "state_digest"})
    if obj["domain"] != "familyos.synthetic-witness-head.v1":
        raise ValueError("unsupported witness head domain")
    head = WitnessHead(
        identity_from(obj["identity"]),
        natural(obj["sequence"]),
        text_value(obj["state_digest"]),
    )
    if _encode(head) != raw:
        raise ValueError("noncanonical witness head")
    return head


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _validate_parent(path: Path, expected_device: int | None = None) -> os.stat_result:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise AnchorUnavailable("explicit absolute USB head path required")
    try:
        parent = path.parent.lstat()
    except OSError as exc:
        raise AnchorUnavailable("USB head medium is absent") from exc
    if not stat.S_ISDIR(parent.st_mode) or path.parent.is_symlink():
        raise AnchorUnavailable("USB head parent is not a safe directory")
    if expected_device is not None and parent.st_dev != expected_device:
        raise AnchorUnavailable("USB head medium identity changed or is absent")
    return parent


def _open_directory(path: Path, expected_device: int) -> int:
    _validate_parent(path, expected_device)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path.parent, flags)
    except OSError as exc:
        raise AnchorUnavailable("USB head directory unavailable") from exc
    actual = os.fstat(descriptor)
    if not stat.S_ISDIR(actual.st_mode) or actual.st_dev != expected_device:
        os.close(descriptor)
        raise AnchorUnavailable("USB head directory was substituted")
    return descriptor


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError(errno.EIO, "short USB head write")
        offset += written


def enroll_synthetic_usb_head(
    path: Path,
    *,
    head: WitnessHead,
    administrator: AnchorPrincipal,
) -> int:
    """Explicit synthetic enrollment; returns the containing device identifier."""
    if administrator.identity != head.identity or AnchorRight.ENROLL not in administrator.rights:
        raise AnchorRejected("separate enrollment authority required")
    parent = _validate_parent(path)
    directory = _open_directory(path, parent.st_dev)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path.name, flags, 0o600, dir_fd=directory)
        try:
            _write_all(descriptor, _encode(head))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(directory)
    except FileExistsError as exc:
        raise AnchorRejected("USB head enrollment refuses overwrite") from exc
    except OSError as exc:
        raise AnchorUnavailable("USB head enrollment failed") from exc
    finally:
        os.close(directory)
    return parent.st_dev


class USBWitnessHead:
    """Synthetic removable-media head with cross-process serialized exact CAS."""

    def __init__(
        self,
        path: Path,
        *,
        identity: StoreIdentity,
        expected_directory_device: int,
        wait_seconds: float = 1.0,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        if type(identity) is not StoreIdentity:
            raise ValueError("exact enrolled identity required")
        if type(expected_directory_device) is not int or expected_directory_device < 0:
            raise ValueError("explicit directory device identity required")
        if (
            type(wait_seconds) not in (int, float)
            or not math.isfinite(wait_seconds)
            or wait_seconds <= 0
        ):
            raise ValueError("wait must be positive and finite")
        self._path = path
        self._identity = identity
        self._device = expected_directory_device
        self._wait = float(wait_seconds)
        self._fault_injector = fault_injector
        self._thread_lock = threading.Lock()
        self.read()

    def _fault(self, phase: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(phase)

    @contextmanager
    def _locked_directory(self) -> Iterator[int]:
        if not self._thread_lock.acquire(timeout=self._wait):
            raise AnchorUnavailable("USB head busy; thread wait exceeded bound")
        directory = -1
        lock_name = "." + self._path.name + ".lock"
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        lock_descriptor = -1
        try:
            directory = _open_directory(self._path, self._device)
            try:
                lock_descriptor = os.open(lock_name, flags, 0o600, dir_fd=directory)
            except OSError as exc:
                raise AnchorUnavailable("USB head lock path unavailable") from exc
            lock_info = os.fstat(lock_descriptor)
            if not stat.S_ISREG(lock_info.st_mode) or stat.S_IMODE(lock_info.st_mode) & 0o077:
                raise AnchorUnavailable("USB head lock path is unsafe")
            deadline = time.monotonic() + self._wait
            while True:
                try:
                    fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise AnchorUnavailable("USB head lock wait exceeded bound") from exc
                    time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
            yield directory
        finally:
            if lock_descriptor >= 0:
                os.close(lock_descriptor)
            if directory >= 0:
                os.close(directory)
            self._thread_lock.release()

    def _read_at(self, directory: int) -> WitnessHead:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self._path.name, flags, dir_fd=directory)
        except OSError as exc:
            raise AnchorUnavailable("USB head state is absent or unsafe") from exc
        try:
            info = os.fstat(descriptor)
            named = os.stat(self._path.name, dir_fd=directory, follow_symlinks=False)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_dev != self._device
                or stat.S_IMODE(info.st_mode) & 0o077
                or (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino)
            ):
                raise AnchorUnavailable("USB head state was substituted")
            parts: list[bytes] = []
            remaining = MAX_HEAD_BYTES + 1
            while remaining:
                part = os.read(descriptor, remaining)
                if not part:
                    break
                parts.append(part)
                remaining -= len(part)
            raw = b"".join(parts)
        finally:
            os.close(descriptor)
        try:
            head = _decode(raw)
        except (ValueError, TypeError, RecursionError) as exc:
            raise AnchorUnavailable("USB head state is malformed") from exc
        if head.identity != self._identity:
            raise AnchorUnavailable("USB head lineage mismatch")
        return head

    def read(self) -> WitnessHead:
        with self._locked_directory() as directory:
            return self._read_at(directory)

    def compare_and_set(self, expected: WitnessHead, candidate: WitnessHead) -> None:
        if type(expected) is not WitnessHead or type(candidate) is not WitnessHead:
            raise AnchorRejected("exact witness heads required")
        if (
            expected.identity != self._identity
            or candidate.identity != self._identity
            or candidate.sequence != expected.sequence + 1
        ):
            raise AnchorRejected("USB head candidate must advance exact lineage once")
        with self._locked_directory() as directory:
            if self._read_at(directory) != expected:
                raise AnchorRejected("USB head exact CAS lost")
            temporary = f".{self._path.name}.{uuid.uuid4().hex}.tmp"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = -1
            commitment_possible = False
            try:
                descriptor = os.open(temporary, flags, 0o600, dir_fd=directory)
                _write_all(descriptor, _encode(candidate))
                os.fsync(descriptor)
                os.close(descriptor)
                descriptor = -1
                self._fault("after_temporary_fsync")
                self._fault("before_replace")
                commitment_possible = True
                os.replace(
                    temporary,
                    self._path.name,
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                )
                self._fault("after_replace")
                os.fsync(directory)
                self._fault("after_directory_fsync")
                if self._read_at(directory) != candidate:
                    raise OSError(errno.EIO, "USB head changed after durable replace")
            except AnchorRejected:
                raise
            except Exception as exc:
                if descriptor >= 0:
                    os.close(descriptor)
                if not commitment_possible:
                    try:
                        os.unlink(temporary, dir_fd=directory)
                    except FileNotFoundError:
                        pass
                if commitment_possible:
                    raise AnchorUncertain(
                        "USB head replace may be durable; commitment is uncertain"
                    ) from exc
                raise AnchorUnavailable("USB head CAS failed before replace") from exc
