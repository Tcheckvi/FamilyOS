"""Synthetic custody-path candidate checks. Never access actual custody.

Standalone: imports only the staged boundary and standard library, not the
repository/native entrypoints. The guarded OS restricts boundary path operations
to one disposable /private/tmp tree and its directory ancestors. No bytes are
read from candidate key files. These files contain public ASCII canaries.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

HERE = Path(__file__).absolute().parent
SOURCE = HERE.parent / "src/familyos_pilot0/custody_path_boundary.py"
SPEC = importlib.util.spec_from_file_location("candidate_boundary_under_test", SOURCE)
assert SPEC is not None and SPEC.loader is not None
boundary = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = boundary
SPEC.loader.exec_module(boundary)


class GuardedOS:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.fds: dict[int, Path] = {}
        self.before_open: Any = None

    def __getattr__(self, name: str) -> Any:
        if name in {"read", "pread", "write", "fdopen", "system", "popen"}:
            raise AssertionError("content or process operation forbidden")
        return getattr(os, name)

    def path(self, name: str, parent: int | None) -> Path:
        result = Path(name) if parent is None else self.fds[parent] / name
        if not (result == self.root or result in self.root.parents
                or result.is_relative_to(self.root)):
            raise AssertionError("path escaped synthetic boundary")
        return result

    def stat(self, name: str, *, dir_fd: int | None, follow_symlinks: bool) -> os.stat_result:
        self.path(name, dir_fd)
        if follow_symlinks is not False:
            raise AssertionError("followed a symbolic link")
        return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)

    def open(self, name: str, flags: int, *, dir_fd: int | None) -> int:
        path = self.path(name, dir_fd)
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            raise AssertionError("boundary attempted a write")
        if not flags & os.O_NOFOLLOW:
            raise AssertionError("missing nofollow")
        if self.before_open is not None:
            self.before_open(path)
        fd = os.open(name, flags, dir_fd=dir_fd)
        self.fds[fd] = path
        return fd

    def fstat(self, fd: int) -> os.stat_result:
        if fd not in self.fds:
            raise AssertionError("foreign descriptor")
        return os.fstat(fd)

    def close(self, fd: int) -> None:
        self.fds.pop(fd)
        os.close(fd)


def forbidden(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("network or process execution forbidden")


class CustodyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="rd01-public-canary-", dir="/private/tmp")
        self.base = Path(self.temp.name)
        self.root = self.base / "authority"
        self.root.mkdir(mode=0o700)
        (self.root / "private").mkdir(mode=0o700)
        (self.root / "public").mkdir(mode=0o755)
        (self.root / "public").chmod(0o755)
        self.private = self.root / "private/canary-private"
        self.public = self.root / "public/canary-public"
        self.private.write_bytes(b"PUBLIC SYNTHETIC CANARY - NOT A KEY\n")
        self.public.write_bytes(b"PUBLIC SYNTHETIC CANARY - NOT A KEY\n")
        self.private.chmod(0o600)
        self.public.chmod(0o644)
        self.guard = GuardedOS(self.base)
        self.os_patch = patch.object(boundary, "os", self.guard)
        self.os_patch.start()
        self.patches = [patch.object(socket, "socket", forbidden),
                        patch.object(socket, "create_connection", forbidden),
                        patch.object(subprocess, "Popen", forbidden)]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        try:
            self.assertEqual(self.guard.fds, {}, "descriptor leak")
        finally:
            self.os_patch.stop()
            for item in reversed(self.patches):
                item.stop()
            self.temp.cleanup()

    def layout(self, **changes: Any) -> Any:
        values = dict(custody_root=str(self.root), private_key_path=str(self.private),
                      public_key_path=str(self.public), owner_uid=os.getuid(),
                      owner_gid=self.root.stat().st_gid)
        values.update(changes)
        return boundary.CustodyPaths(**values)

    def inspect(self) -> Any:
        return boundary.inspect_custody_paths(self.layout())

    def test_nested_layout_metadata_only_and_frozen(self) -> None:
        result = self.inspect()
        self.assertEqual(result.paths.private_parent, str(self.private.parent))
        self.assertEqual(result.paths.public_parent, str(self.public.parent))
        self.assertEqual(result.private_file.inode, self.private.stat().st_ino)
        self.assertFalse(result.key_use_authorized)
        with self.assertRaises(FrozenInstanceError):
            result.private_file = None
        self.assertNotIn("fd", result.__dataclass_fields__)
        self.assertEqual(self.guard.fds, {})

    def test_canonical_paths_and_role_separation_before_io(self) -> None:
        for field, value in [
            ("custody_root", "relative"), ("custody_root", str(self.root) + "/"),
            ("custody_root", "//private/tmp/x"), ("custody_root", "/"),
            ("private_key_path", str(self.root) + "/private/../private/x"),
            ("private_key_path", str(self.root) + "/private/./x"),
            ("private_key_path", str(self.public)),
            ("public_key_path", str(self.private)),
            ("private_key_path", str(self.base / "outside")),
            ("public_key_path", "bad\x00path"), ("owner_uid", True),
            ("owner_uid", 0), ("owner_gid", True), ("owner_gid", -1),
        ]:
            with self.subTest(field=field, value=value):
                with self.assertRaises(boundary.CustodyPathDenied):
                    self.layout(**{field: value})
                self.assertEqual(self.guard.fds, {})

    def test_uid_and_gid_mismatch(self) -> None:
        for field in ("owner_uid", "owner_gid"):
            with self.subTest(field=field):
                with self.assertRaises(boundary.CustodyPathDenied):
                    boundary.inspect_custody_paths(self.layout(**{
                        field: (os.getuid() if field == "owner_uid" else os.getgid()) + 1
                    }))

    def test_wrong_owner_modes(self) -> None:
        for path, bad in [(self.root, 0o755), (self.private.parent, 0o755),
                          (self.public.parent, 0o777), (self.private, 0o644),
                          (self.public, 0o666)]:
            with self.subTest(path=path, bad=bad):
                prior = path.stat().st_mode & 0o7777
                try:
                    path.chmod(bad)
                    with self.assertRaises(boundary.CustodyPathDenied):
                        self.inspect()
                finally:
                    path.chmod(prior)

    def test_permitted_restricted_modes(self) -> None:
        self.private.chmod(0o400)
        self.public.chmod(0o400)
        self.public.parent.chmod(0o700)
        self.assertFalse(self.inspect().key_use_authorized)

    def test_special_mode_bits_rejected_in_observed_metadata(self) -> None:
        # This filesystem clears setuid on a non-executable canary at chmod.
        # Exercise the observed-metadata invariant independently of that behavior.
        real_stat = self.guard.stat

        def special(name: str, *, dir_fd: int | None, follow_symlinks: bool) -> Any:
            info = real_stat(name, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
            if self.guard.path(name, dir_fd) == self.private:
                fields = {key: getattr(info, key) for key in dir(info) if key.startswith("st_")}
                fields["st_mode"] = info.st_mode | 0o4000
                return SimpleNamespace(**fields)
            return info

        with patch.object(self.guard, "stat", special):
            with self.assertRaises(boundary.CustodyPathDenied):
                self.inspect()

    def test_hard_links_rejected_for_both_roles(self) -> None:
        for path in (self.private, self.public):
            extra = self.base / "hardlink"
            os.link(path, extra)
            try:
                with self.assertRaises(boundary.CustodyPathDenied):
                    self.inspect()
            finally:
                extra.unlink()

    def test_symlinks_at_each_custody_edge(self) -> None:
        for path in (self.private, self.public, self.private.parent,
                     self.public.parent, self.root):
            moved = path.with_name(path.name + "-held")
            path.rename(moved)
            path.symlink_to(moved)
            try:
                with self.assertRaises(boundary.CustodyPathDenied):
                    self.inspect()
            finally:
                path.unlink()
                moved.rename(path)

    def test_symlink_in_ancestor(self) -> None:
        alias = self.base / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        layout = self.layout(custody_root=str(alias / "child"),
                             private_key_path=str(alias / "child/private/x"),
                             public_key_path=str(alias / "child/public/y"))
        with self.assertRaises(boundary.CustodyPathDenied):
            boundary.inspect_custody_paths(layout)

    def test_fifo_directory_empty_oversize_missing_are_denied(self) -> None:
        self.private.unlink()
        for kind in ("fifo", "directory", "empty", "oversize", "missing"):
            with self.subTest(kind=kind):
                if kind == "fifo":
                    os.mkfifo(self.private, 0o600)
                elif kind == "directory":
                    self.private.mkdir(mode=0o700)
                elif kind in {"empty", "oversize"}:
                    self.private.write_bytes(b"" if kind == "empty" else b"x" * 65537)
                    self.private.chmod(0o600)
                with self.assertRaises(boundary.CustodyPathDenied):
                    self.inspect()
                if kind == "directory":
                    self.private.rmdir()
                elif kind != "missing":
                    self.private.unlink()

    def test_replacement_between_stat_and_open(self) -> None:
        replacement = self.base / "replacement"
        replacement.write_bytes(b"PUBLIC SYNTHETIC REPLACEMENT\n")
        replacement.chmod(0o600)

        def replace(path: Path) -> None:
            if path == self.private:
                self.guard.before_open = None
                os.replace(replacement, self.private)

        self.guard.before_open = replace
        with self.assertRaises(boundary.CustodyPathDenied):
            self.inspect()

    def test_replacement_after_private_open(self) -> None:
        replacement = self.base / "replacement"
        replacement.write_bytes(b"PUBLIC SYNTHETIC REPLACEMENT\n")
        replacement.chmod(0o600)

        def replace(path: Path) -> None:
            if path == self.public:
                self.guard.before_open = None
                os.replace(replacement, self.private)

        self.guard.before_open = replace
        with self.assertRaises(boundary.CustodyPathDenied):
            self.inspect()

    def test_hardlink_added_after_private_open(self) -> None:
        def link(path: Path) -> None:
            if path == self.public:
                self.guard.before_open = None
                os.link(self.private, self.base / "extra-link")

        self.guard.before_open = link
        with self.assertRaises(boundary.CustodyPathDenied):
            self.inspect()

    def test_directory_rebound_while_descriptor_held(self) -> None:
        def replace(path: Path) -> None:
            if path == self.public:
                self.guard.before_open = None
                self.private.parent.rename(self.root / "private-old")
                (self.root / "private").mkdir(mode=0o700)

        self.guard.before_open = replace
        with self.assertRaises(boundary.CustodyPathDenied):
            self.inspect()

    def test_mode_changed_after_private_open(self) -> None:
        def change(path: Path) -> None:
            if path == self.public:
                self.guard.before_open = None
                self.private.chmod(0o644)

        self.guard.before_open = change
        with self.assertRaises(boundary.CustodyPathDenied):
            self.inspect()

    def test_missing_safety_flag_denied_before_io(self) -> None:
        with patch.object(self.guard, "O_NOFOLLOW", 0):
            with self.assertRaises(boundary.CustodyPathDenied):
                self.inspect()
        self.assertEqual(self.guard.fds, {})

    def test_open_failure_closes_all_ancestors(self) -> None:
        def fail(path: Path) -> None:
            if path == self.private:
                raise PermissionError("synthetic permission failure")

        self.guard.before_open = fail
        with self.assertRaises(boundary.CustodyPathDenied):
            self.inspect()

    def test_no_key_read_write_process_or_network_calls_in_boundary(self) -> None:
        tree = ast.parse(SOURCE.read_bytes())
        banned = {"read", "pread", "read_bytes", "read_text", "fdopen", "write",
                  "sign", "Popen", "run", "socket", "exec", "eval", "compile"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else (
                    node.func.id if isinstance(node.func, ast.Name) else ""
                )
                self.assertNotIn(name, banned)
        imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse(any(n and n.startswith("familyos") for n in imports))


if __name__ == "__main__":
    unittest.main(verbosity=2)
