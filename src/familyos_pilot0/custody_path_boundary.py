"""Candidate custody path observation; no content access or execution authority.

Only a trusted deployment caller may construct CustodyPaths. It is not KeyRef or
an accepted worker configuration field. Returned metadata is an observation, not
a reusable key-use grant: all descriptors are closed before return. A future
qualified native consumer must bind and revalidate its own use of key objects.
"""
from __future__ import annotations

import os
import stat
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

MAX_KEY_BYTES = 65536


class CustodyPathDenied(RuntimeError):
    """A path/object cannot satisfy the candidate metadata boundary."""


def _path(value: str) -> PurePosixPath:
    if (
        type(value) is not str
        or not value.startswith("/")
        or "\x00" in value
        or len(value) > 4096
        or any(part in {"", ".", ".."} for part in value.split("/")[1:])
        or len(value.split("/")) > 64
    ):
        raise CustodyPathDenied("absolute canonical custody path required")
    return PurePosixPath(value)


@dataclass(frozen=True)
class CustodyPaths:
    """Explicit role paths and owner metadata; never a credential or permission."""

    custody_root: str
    private_key_path: str
    public_key_path: str
    owner_uid: int
    owner_gid: int

    def __post_init__(self) -> None:
        root = _path(self.custody_root)
        private = _path(self.private_key_path)
        public = _path(self.public_key_path)
        if (
            private.parent != root / "private"
            or public.parent != root / "public"
            or type(self.owner_uid) is not int
            or self.owner_uid <= 0
            or type(self.owner_gid) is not int
            or self.owner_gid < 0
        ):
            raise CustodyPathDenied("custody role paths or owner identity invalid")

    @property
    def private_parent(self) -> str:
        return str(_path(self.private_key_path).parent)

    @property
    def public_parent(self) -> str:
        return str(_path(self.public_key_path).parent)


@dataclass(frozen=True)
class ObjectIdentity:
    device: int
    inode: int
    size: int
    mode: int
    uid: int
    gid: int
    links: int
    mtime_ns: int
    ctime_ns: int
    flags: int


def _identity(info: os.stat_result) -> ObjectIdentity:
    return ObjectIdentity(
        info.st_dev, info.st_ino, info.st_size, info.st_mode,
        info.st_uid, info.st_gid, info.st_nlink, info.st_mtime_ns,
        info.st_ctime_ns, getattr(info, "st_flags", 0),
    )


@dataclass(frozen=True)
class CustodyPathMetadata:
    paths: CustodyPaths
    root: ObjectIdentity
    private_parent: ObjectIdentity
    public_parent: ObjectIdentity
    private_file: ObjectIdentity
    public_file: ObjectIdentity

    @property
    def key_use_authorized(self) -> Literal[False]:
        return False


@dataclass(frozen=True)
class _Pinned:
    parent_fd: int | None
    name: str
    fd: int
    identity: ObjectIdentity


def _mode_owner(
    info: os.stat_result, paths: CustodyPaths, modes: tuple[int, ...]
) -> None:
    if (
        info.st_uid != paths.owner_uid
        or info.st_gid != paths.owner_gid
        or stat.S_IMODE(info.st_mode) not in modes
        or getattr(info, "st_flags", 0) != 0
    ):
        raise CustodyPathDenied("custody owner, mode or flags mismatch")


def inspect_custody_paths(paths: CustodyPaths) -> CustodyPathMetadata:
    """Observe metadata only via held descriptors; never return a usable key FD.

    All named edges are revalidated before return, including ancestor bindings.
    Concurrent changes fail closed. This is not a lock, ACL qualification, native
    signer, or promise of path continuity after these descriptors are closed.
    """
    if type(paths) is not CustodyPaths:
        raise CustodyPathDenied("exact custody layout required")
    paths.__post_init__()  # Validate before any filesystem operation.
    required = ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC")
    if any(not getattr(os, flag, 0) for flag in required):
        raise CustodyPathDenied("required no-follow descriptor controls unavailable")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        with ExitStack() as cleanup:
            pinned: list[_Pinned] = []

            def open_checked(
                parent_fd: int | None, name: str, *, directory: bool,
                modes: tuple[int, ...] | None = None,
            ) -> _Pinned:
                before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)

                def validate(info: os.stat_result) -> None:
                    if directory:
                        if not stat.S_ISDIR(info.st_mode):
                            raise CustodyPathDenied("custody directory required")
                    elif (
                        not stat.S_ISREG(info.st_mode)
                        or info.st_nlink != 1
                        or not 0 < info.st_size <= MAX_KEY_BYTES
                    ):
                        raise CustodyPathDenied("single-link bounded regular key file required")
                    if modes is not None:
                        _mode_owner(info, paths, modes)

                validate(before)
                fd = os.open(
                    name, directory_flags if directory else file_flags, dir_fd=parent_fd
                )
                cleanup.callback(os.close, fd)
                opened = os.fstat(fd)
                validate(opened)
                if _identity(before) != _identity(opened):
                    raise CustodyPathDenied("custody object replaced during open")
                pin = _Pinned(parent_fd, name, fd, _identity(opened))
                pinned.append(pin)
                return pin

            parent = open_checked(None, "/", directory=True)
            parts = _path(paths.custody_root).parts[1:]
            for index, part in enumerate(parts):
                parent = open_checked(
                    parent.fd, part, directory=True,
                    modes=(0o700,) if index == len(parts) - 1 else None,
                )
            root = parent
            private_dir = open_checked(root.fd, "private", directory=True, modes=(0o700,))
            public_dir = open_checked(root.fd, "public", directory=True, modes=(0o700, 0o755))
            private = open_checked(
                private_dir.fd, _path(paths.private_key_path).name,
                directory=False, modes=(0o400, 0o600),
            )
            public = open_checked(
                public_dir.fd, _path(paths.public_key_path).name,
                directory=False, modes=(0o400, 0o600, 0o644),
            )
            if (private.identity.device, private.identity.inode) == (
                public.identity.device, public.identity.inode
            ):
                raise CustodyPathDenied("private and public objects must be distinct")

            # No content read and no callback/use of key material occurs here.
            for pin in reversed(pinned):
                current = _identity(os.fstat(pin.fd))
                named = _identity(
                    os.stat(pin.name, dir_fd=pin.parent_fd, follow_symlinks=False)
                )
                if current != pin.identity or named != pin.identity:
                    raise CustodyPathDenied("custody descriptor or named binding changed")
            return CustodyPathMetadata(
                paths, root.identity, private_dir.identity, public_dir.identity,
                private.identity, public.identity,
            )
    except (OSError, NotImplementedError):
        raise CustodyPathDenied("custody metadata observation unavailable") from None
