from __future__ import annotations

import os
import stat
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from familyos_pilot0.custody_anchor_protocol import (
    AnchorRejected,
    AnchorUnavailable,
    AnchorUncertain,
)
from familyos_pilot0.custody_rollback_contracts import StoreIdentity
from familyos_pilot0.custody_usb_witness_head import (
    USBWitnessHead,
    enroll_synthetic_usb_head,
)
from familyos_pilot0.custody_witness_state import WitnessHead
from tests.custody_sqlite_witness_fixtures import ADMIN, IDENTITY


def head(sequence: int = 0, digest: str = "a") -> WitnessHead:
    return WitnessHead(IDENTITY, sequence, digest * 64)


def enrolled(tmp_path: Path) -> tuple[Path, USBWitnessHead]:
    path = (tmp_path / "synthetic-usb" / "head.json").absolute()
    path.parent.mkdir()
    device = enroll_synthetic_usb_head(path, head=head(), administrator=ADMIN)
    return path, USBWitnessHead(
        path,
        identity=IDENTITY,
        expected_directory_device=device,
        wait_seconds=0.2,
    )


def test_explicit_enrollment_creates_once_with_restrictive_permissions(
    tmp_path: Path,
) -> None:
    path = (tmp_path / "usb" / "head.json").absolute()
    path.parent.mkdir()
    device = enroll_synthetic_usb_head(path, head=head(), administrator=ADMIN)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert (
        USBWitnessHead(
            path,
            identity=IDENTITY,
            expected_directory_device=device,
        ).read()
        == head()
    )
    with pytest.raises(AnchorRejected, match="overwrite"):
        enroll_synthetic_usb_head(path, head=head(), administrator=ADMIN)


def test_exact_read_cas_stale_replacement_and_restart(tmp_path: Path) -> None:
    path, backend = enrolled(tmp_path)
    old = path.read_bytes()
    candidate = head(1, "b")
    backend.compare_and_set(head(), candidate)
    assert backend.read() == candidate
    with pytest.raises(AnchorRejected, match="CAS"):
        backend.compare_and_set(head(), candidate)
    path.write_bytes(old)
    with pytest.raises(AnchorRejected, match="CAS"):
        backend.compare_and_set(candidate, head(2, "c"))
    assert (
        USBWitnessHead(
            path,
            identity=IDENTITY,
            expected_directory_device=path.parent.stat().st_dev,
        ).read()
        == head()
    )


def test_wrong_lineage_and_invalid_candidate_are_rejected(tmp_path: Path) -> None:
    path, backend = enrolled(tmp_path)
    wrong = WitnessHead(StoreIdentity("other", 1), 1, "b" * 64)
    with pytest.raises(AnchorRejected, match="lineage"):
        backend.compare_and_set(head(), wrong)
    with pytest.raises(AnchorRejected, match="once"):
        backend.compare_and_set(head(), head(2, "c"))
    with pytest.raises(AnchorUnavailable, match="lineage"):
        USBWitnessHead(
            path,
            identity=StoreIdentity("other", 1),
            expected_directory_device=path.parent.stat().st_dev,
        )


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not-json",
        b'{"domain":"familyos.synthetic-witness-head.v1","identity":{},"sequence":0,'
        b'"state_digest":"x","extra":true}',
        b'{"domain":"familyos.synthetic-witness-head.v1","domain":"duplicate",'
        b'"identity":{},"sequence":0,"state_digest":"x"}',
    ],
)
def test_malformed_empty_extra_and_duplicate_state_fail_closed(
    tmp_path: Path, content: bytes
) -> None:
    path, backend = enrolled(tmp_path)
    path.write_bytes(content)
    with pytest.raises(AnchorUnavailable, match="malformed"):
        backend.read()


def test_symlink_absent_parent_and_device_substitution_are_rejected(tmp_path: Path) -> None:
    path, backend = enrolled(tmp_path)
    target = tmp_path / "target"
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(AnchorUnavailable, match="absent or unsafe"):
        backend.read()
    with pytest.raises(AnchorUnavailable, match="absent"):
        USBWitnessHead(
            (tmp_path / "missing" / "head.json").absolute(),
            identity=IDENTITY,
            expected_directory_device=path.parent.stat().st_dev,
        )
    with pytest.raises(AnchorUnavailable, match="identity changed"):
        USBWitnessHead(
            target.absolute(),
            identity=IDENTITY,
            expected_directory_device=target.parent.stat().st_dev + 1,
        )


def test_overbroad_head_permissions_are_rejected(tmp_path: Path) -> None:
    path, backend = enrolled(tmp_path)
    path.chmod(0o644)
    with pytest.raises(AnchorUnavailable, match="substituted"):
        backend.read()


def test_overbroad_lock_permissions_are_rejected(tmp_path: Path) -> None:
    path, backend = enrolled(tmp_path)
    lock = path.parent / ("." + path.name + ".lock")
    previous_head = path.read_bytes()
    lock.chmod(0o644)
    with pytest.raises(AnchorUnavailable, match="lock path is unsafe"):
        backend.compare_and_set(head(), head(1, "b"))
    assert path.read_bytes() == previous_head


def test_noncanonical_head_representation_is_rejected(tmp_path: Path) -> None:
    path, backend = enrolled(tmp_path)
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(AnchorUnavailable, match="malformed"):
        backend.read()


def test_before_replace_failure_preserves_old_head_and_removes_temporary(
    tmp_path: Path,
) -> None:
    path, _ = enrolled(tmp_path)

    def fail(phase: str) -> None:
        if phase == "before_replace":
            raise RuntimeError("synthetic stop")

    backend = USBWitnessHead(
        path,
        identity=IDENTITY,
        expected_directory_device=path.parent.stat().st_dev,
        fault_injector=fail,
    )
    with pytest.raises(AnchorUnavailable, match="before replace"):
        backend.compare_and_set(head(), head(1, "b"))
    assert backend.read() == head()
    assert not list(path.parent.glob(".*.tmp"))


def test_post_replace_failure_is_uncertain_and_candidate_survives(tmp_path: Path) -> None:
    path, _ = enrolled(tmp_path)

    def fail(phase: str) -> None:
        if phase == "after_replace":
            raise RuntimeError("synthetic lost acknowledgement")

    backend = USBWitnessHead(
        path,
        identity=IDENTITY,
        expected_directory_device=path.parent.stat().st_dev,
        fault_injector=fail,
    )
    with pytest.raises(AnchorUncertain, match="may be durable"):
        backend.compare_and_set(head(), head(1, "b"))
    assert backend.read() == head(1, "b")


def test_temporary_replace_file_and_directory_fsync_are_observable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, backend = enrolled(tmp_path)
    fsync_modes: list[int] = []
    replacements: list[tuple[str, str]] = []
    real_fsync, real_replace = os.fsync, os.replace

    def observed_fsync(descriptor: int) -> None:
        fsync_modes.append(stat.S_IFMT(os.fstat(descriptor).st_mode))
        real_fsync(descriptor)

    def observed_replace(source: str, target: str, **kwargs: int) -> None:
        replacements.append((source, target))
        real_replace(source, target, **kwargs)

    monkeypatch.setattr("familyos_pilot0.custody_usb_witness_head.os.fsync", observed_fsync)
    monkeypatch.setattr("familyos_pilot0.custody_usb_witness_head.os.replace", observed_replace)
    backend.compare_and_set(head(), head(1, "b"))
    assert stat.S_IFREG in fsync_modes
    assert stat.S_IFDIR in fsync_modes
    assert len(replacements) == 1
    assert replacements[0][0].endswith(".tmp")
    assert replacements[0][1] == path.name


def test_interprocess_lock_has_bounded_wait_and_no_fallback(tmp_path: Path) -> None:
    path, backend = enrolled(tmp_path)
    lock = path.parent / ("." + path.name + ".lock")
    script = """
import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX)
print('locked', flush=True)
time.sleep(1)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(lock)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "locked"
        start = time.monotonic()
        with pytest.raises(AnchorUnavailable, match="wait exceeded"):
            backend.compare_and_set(head(), head(1, "b"))
        assert time.monotonic() - start < 0.8
        process.terminate()
        process.wait(timeout=2)
        assert backend.read() == head()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=2)


def test_admin_right_and_absolute_path_are_mandatory(tmp_path: Path) -> None:
    path = tmp_path / "head.json"
    with pytest.raises(AnchorRejected, match="enrollment"):
        enroll_synthetic_usb_head(
            path.absolute(),
            head=head(),
            administrator=replace(ADMIN, rights=frozenset()),
        )
    with pytest.raises(AnchorUnavailable, match="absolute"):
        enroll_synthetic_usb_head(Path("relative.json"), head=head(), administrator=ADMIN)


def test_stable_storage_sync_uses_fullfsync_on_darwin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import familyos_pilot0.custody_usb_witness_head as custody_usb

    path = tmp_path / "sync.bin"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    calls: list[tuple[int, int]] = []

    class Darwin:
        platform = "darwin"

    def observed_fcntl(fd: int, command: int) -> int:
        calls.append((fd, command))
        return 0

    monkeypatch.setattr(custody_usb, "sys", Darwin())
    monkeypatch.setattr(custody_usb.fcntl, "F_FULLFSYNC", 51, raising=False)
    monkeypatch.setattr(custody_usb.fcntl, "fcntl", observed_fcntl)
    try:
        custody_usb._stable_storage_sync(descriptor)
    finally:
        os.close(descriptor)

    assert calls == [(descriptor, 51)]


def test_stable_storage_sync_missing_fullfsync_fails_closed_on_darwin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    import familyos_pilot0.custody_usb_witness_head as custody_usb

    path = tmp_path / "sync.bin"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)

    class Darwin:
        platform = "darwin"

    monkeypatch.setattr(custody_usb, "sys", Darwin())
    monkeypatch.delattr(custody_usb.fcntl, "F_FULLFSYNC", raising=False)
    try:
        with pytest.raises(OSError) as exc_info:
            custody_usb._stable_storage_sync(descriptor)
    finally:
        os.close(descriptor)

    assert exc_info.value.errno == errno.ENOTSUP


def test_stable_storage_sync_non_darwin_uses_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import familyos_pilot0.custody_usb_witness_head as custody_usb

    path = tmp_path / "sync.bin"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    real_fsync = os.fsync
    calls: list[int] = []

    class NonDarwin:
        platform = "linux"

    def observed_fsync(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(custody_usb, "sys", NonDarwin())
    monkeypatch.setattr(custody_usb.os, "fsync", observed_fsync)
    try:
        custody_usb._stable_storage_sync(descriptor)
    finally:
        os.close(descriptor)

    assert calls == [descriptor]


def test_cas_strong_sync_follows_directory_fsync_and_descriptor_survives_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import familyos_pilot0.custody_usb_witness_head as custody_usb

    path, backend = enrolled(tmp_path)
    real_fsync = os.fsync
    events: list[tuple[str, int]] = []

    def observed_fsync(descriptor: int) -> None:
        events.append(("fsync", stat.S_IFMT(os.fstat(descriptor).st_mode)))
        real_fsync(descriptor)

    def observed_strong_sync(descriptor: int) -> None:
        events.append(("strong", stat.S_IFMT(os.fstat(descriptor).st_mode)))
        assert os.fstat(descriptor).st_ino == path.stat().st_ino

    monkeypatch.setattr(custody_usb.os, "fsync", observed_fsync)
    monkeypatch.setattr(custody_usb, "_stable_storage_sync", observed_strong_sync)

    backend.compare_and_set(head(), head(1, "b"))

    file_fsync = events.index(("fsync", stat.S_IFREG))
    directory_fsync = events.index(("fsync", stat.S_IFDIR))
    strong_sync = events.index(("strong", stat.S_IFREG))
    assert file_fsync < directory_fsync < strong_sync
    assert backend.read() == head(1, "b")


def test_strong_sync_failure_after_replace_is_uncertain_and_candidate_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import familyos_pilot0.custody_usb_witness_head as custody_usb

    path, backend = enrolled(tmp_path)

    def fail_strong_sync(descriptor: int) -> None:
        assert os.fstat(descriptor).st_ino == path.stat().st_ino
        raise OSError("synthetic strong storage sync failure")

    monkeypatch.setattr(custody_usb, "_stable_storage_sync", fail_strong_sync)

    with pytest.raises(AnchorUncertain, match="may be durable"):
        backend.compare_and_set(head(), head(1, "b"))

    assert backend.read() == head(1, "b")


def test_after_full_storage_sync_fault_is_uncertain_and_candidate_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import familyos_pilot0.custody_usb_witness_head as custody_usb

    path, _ = enrolled(tmp_path)

    def no_op_strong_sync(descriptor: int) -> None:
        assert os.fstat(descriptor).st_ino == path.stat().st_ino

    def fail(phase: str) -> None:
        if phase == "after_full_storage_sync":
            raise RuntimeError("synthetic lost acknowledgement after full storage sync")

    monkeypatch.setattr(custody_usb, "_stable_storage_sync", no_op_strong_sync)
    backend = USBWitnessHead(
        path,
        identity=IDENTITY,
        expected_directory_device=path.parent.stat().st_dev,
        fault_injector=fail,
    )

    with pytest.raises(AnchorUncertain, match="may be durable"):
        backend.compare_and_set(head(), head(1, "b"))

    assert backend.read() == head(1, "b")


def test_successful_cas_closes_candidate_descriptor_after_strong_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import familyos_pilot0.custody_usb_witness_head as custody_usb

    path, backend = enrolled(tmp_path)
    captured: list[int] = []

    def observed_strong_sync(descriptor: int) -> None:
        assert os.fstat(descriptor).st_ino == path.stat().st_ino
        captured.append(descriptor)

    monkeypatch.setattr(custody_usb, "_stable_storage_sync", observed_strong_sync)

    backend.compare_and_set(head(), head(1, "b"))

    assert len(captured) == 1
    with pytest.raises(OSError):
        os.fstat(captured[0])
    assert backend.read() == head(1, "b")


def test_cleanup_close_failure_does_not_mask_anchor_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import familyos_pilot0.custody_usb_witness_head as custody_usb

    path, backend = enrolled(tmp_path)
    real_close = os.close
    captured: list[int] = []

    def fail_strong_sync(descriptor: int) -> None:
        captured.append(descriptor)
        raise OSError("synthetic strong storage sync failure")

    def fail_candidate_close(descriptor: int) -> None:
        if captured and descriptor == captured[0]:
            raise OSError("synthetic cleanup close failure")
        real_close(descriptor)

    monkeypatch.setattr(custody_usb, "_stable_storage_sync", fail_strong_sync)
    monkeypatch.setattr(custody_usb.os, "close", fail_candidate_close)

    try:
        with pytest.raises(AnchorUncertain, match="may be durable"):
            backend.compare_and_set(head(), head(1, "b"))
        assert backend.read() == head(1, "b")
    finally:
        if captured:
            real_close(captured[0])
