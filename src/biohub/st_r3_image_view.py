"""Sealed, image-only EVAL36 view construction for ST-R3.

The production entry points in this module have no caller-selectable data or
authority paths.  They consume one pinned READY bundle, address only the 36
fixed Zarr roots below ``data/train``, and publish a fresh run directory with
an atomic no-replace directory rename.  Source image bytes are never decoded.
"""

from __future__ import annotations

import contextlib
import ctypes
import dataclasses
import datetime as dt
import errno
import hashlib
import json
import math
import os
import re
import secrets
import stat
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

SCHEMA_VERSION = "biohub.st_r3.image_view_receipt.v1"
READY_SCHEMA = "biohub.eval36_images_ready.v1"
INVENTORY_SCHEMA = "biohub.eval36_image_content_inventory.v1"
CANONICAL_REPO_ROOT = Path(__file__).resolve().parents[2]
READ_SIZE = 1024 * 1024
MAX_JSON_BYTES = 16 * 1024 * 1024
PRODUCTION_OFFICIAL_OID = "075fc5f5a52d11077f9dc2b074644618f26939e2"
PRODUCTION_OFFICIAL_TRACKED_ENTRIES = 49
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_OID_RE = re.compile(r"[0-9a-f]{40}\Z")
_RUN_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+@-]{0,127}\Z")
_UTC_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")

EVAL36_STEMS = (
    "44b6_12dfb391",
    "44b6_267148e4",
    "44b6_2a2eff9f",
    "44b6_341df25f",
    "44b6_587a1e22",
    "44b6_5f15d135",
    "6bba_062c8d37",
    "6bba_07e24132",
    "6bba_085bf656",
    "6bba_09961292",
    "6bba_0e7c0d07",
    "6bba_12665c0e",
    "44b6_706092f0",
    "44b6_74d0c52e",
    "44b6_7a302da0",
    "44b6_996155de",
    "44b6_9be80b04",
    "44b6_a21120c2",
    "44b6_aaf8b0ea",
    "44b6_c50204e0",
    "44b6_c8e2a523",
    "44b6_d2f34f90",
    "44b6_d5e7d891",
    "44b6_d754aa59",
    "6bba_1d0d8384",
    "6bba_207c6aaf",
    "6bba_20852818",
    "6bba_2312ac41",
    "6bba_268e1230",
    "6bba_2819ca14",
    "6bba_32db13fc",
    "6bba_337b1b3a",
    "6bba_3abfe10a",
    "6bba_3c5691b6",
    "6bba_3db54e20",
    "6bba_3fda6b25",
)
ZARR_FILE_SUFFIXES = (
    "zarr.json",
    "0/zarr.json",
    *(f"0/c/{index}/0/0/0" for index in range(100)),
)


class ImageViewError(RuntimeError):
    """The requested image-only view cannot be trusted or published."""


class PublicationAmbiguityError(ImageViewError):
    """A publication failure could not be rolled back with durable certainty."""


@dataclass(frozen=True)
class Authority:
    stems: tuple[str, ...]
    file_suffixes: tuple[str, ...]
    files_per_root: int
    stored_bytes: int
    source_relative: str
    output_parent_relative: str
    ready_relative: str
    ready_sha256: str
    ready_content_sha256: str
    inventory_sha256: str
    import_receipt_relative: str
    import_receipt_sha256: str
    official_oid: str
    builder_sources: tuple[str, ...]


PRODUCTION_AUTHORITY = Authority(
    stems=EVAL36_STEMS,
    file_suffixes=ZARR_FILE_SUFFIXES,
    files_per_root=102,
    stored_bytes=15_932_872_938,
    source_relative="data/train",
    output_parent_relative="outputs/local/st_r3_image_views",
    ready_relative=("outputs/local/eval36_image_ready/20260904T220902+0900_2877f28_direct/READY.json"),
    ready_sha256="8a0a36d393ecc11a0532bc12011257a4c012cb7361d4346941b4d1211c58c73e",
    ready_content_sha256="2211abec541bc31df2f31aacf1575c065025f0aa143147c3df07b4ece2b3214a",
    inventory_sha256="efe652bd8e8a791bd51cf3b980ae87fe0fe2205ec52d2f3639717cd2b0550714",
    import_receipt_relative=(
        "outputs/local/eval36_bundle_receipts/20260904T0055JST/"
        "eval36-import-0b224bf87b6fb0d0653cd265461a4fb75e17068de3550a73b19379eeb2294570.json"
    ),
    import_receipt_sha256="0b224bf87b6fb0d0653cd265461a4fb75e17068de3550a73b19379eeb2294570",
    official_oid=PRODUCTION_OFFICIAL_OID,
    builder_sources=("src/biohub/st_r3_image_view.py", "scripts/experiments/st_r3/st_r3_image_view.py"),
)


@dataclass(frozen=True)
class GitState:
    commit: str
    tree: str
    official_oid: str


@dataclass(frozen=True)
class CheckoutGuard:
    root_fd: int
    git_fd: int
    official_fd: int
    root_identity: tuple[int, int, int]
    git_identity: tuple[int, int, int]
    official_identity: tuple[int, int, int]

    def close(self) -> None:
        for fd in (self.official_fd, self.git_fd, self.root_fd):
            with contextlib.suppress(OSError):
                os.close(fd)


@dataclass(frozen=True)
class LoadedAuthority:
    ready: dict[str, object]
    ready_raw: bytes
    inventory: dict[str, object]
    inventory_raw: bytes
    records: tuple[dict[str, object], ...]
    import_raw: bytes
    source_identity: tuple[int, int]


@dataclass
class _StagingOwnership:
    name: str
    identity: tuple[int, int]
    directories: dict[str, tuple[int, int]]
    files: dict[str, tuple[int, int]]


class _DarwinFsid(ctypes.Structure):
    _fields_ = [("values", ctypes.c_int32 * 2)]


class _DarwinStatFs(ctypes.Structure):
    """Darwin 64-bit-inode ``struct statfs`` from ``sys/mount.h``."""

    _fields_ = [
        ("f_bsize", ctypes.c_uint32),
        ("f_iosize", ctypes.c_int32),
        ("f_blocks", ctypes.c_uint64),
        ("f_bfree", ctypes.c_uint64),
        ("f_bavail", ctypes.c_uint64),
        ("f_files", ctypes.c_uint64),
        ("f_ffree", ctypes.c_uint64),
        ("f_fsid", _DarwinFsid),
        ("f_owner", ctypes.c_uint32),
        ("f_type", ctypes.c_uint32),
        ("f_flags", ctypes.c_uint32),
        ("f_fssubtype", ctypes.c_uint32),
        ("f_fstypename", ctypes.c_char * 16),
        ("f_mntonname", ctypes.c_char * 1024),
        ("f_mntfromname", ctypes.c_char * 1024),
        ("f_flags_ext", ctypes.c_uint32),
        ("f_reserved", ctypes.c_uint32 * 7),
    ]


def canonical_json_bytes(value: object) -> bytes:
    """Return the sole accepted JSON encoding."""
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _strict_json_bytes(raw: bytes) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ImageViewError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> object:
        raise ImageViewError("non-finite JSON value")

    def finite_float(value: str) -> float:
        result = float(value)
        if not math.isfinite(result):
            raise ImageViewError("non-finite JSON float")
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
            parse_float=finite_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ImageViewError("invalid JSON") from error
    if canonical_json_bytes(value) != raw:
        raise ImageViewError("noncanonical JSON")
    return value


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _identity_value(info: os.stat_result) -> dict[str, int]:
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": info.st_mode,
        "nlink": info.st_nlink,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }


def _identity_from_value(value: object) -> tuple[int, int, int, int, int, int, int]:
    keys = {"device", "inode", "mode", "nlink", "size", "mtime_ns", "ctime_ns"}
    if type(value) is not dict or set(value) != keys:
        raise ImageViewError("identity record shape drift")
    numbers = tuple(value[key] for key in ("device", "inode", "mode", "nlink", "size", "mtime_ns", "ctime_ns"))
    if any(type(number) is not int or number < 0 for number in numbers):
        raise ImageViewError("invalid identity record")
    return numbers  # type: ignore[return-value]


def _ownership(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _directory_handle_identity(info: os.stat_result) -> tuple[int, int, int]:
    return info.st_dev, info.st_ino, info.st_mode


def _safe_relative(value: object) -> str:
    if type(value) is not str or not value or "\x00" in value or "\\" in value:
        raise ImageViewError("unsafe relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(part in {"", ".", ".."} for part in path.parts):
        raise ImageViewError("unsafe relative path")
    return value


def _open_absolute_directory(path: Path) -> int:
    absolute = path.absolute()
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            parent_before = os.fstat(current)
            next_fd = os.open(part, flags, dir_fd=current)
            keep_next = False
            try:
                path_info = os.stat(part, dir_fd=current, follow_symlinks=False)
                if not stat.S_ISDIR(path_info.st_mode) or _identity(path_info) != _identity(os.fstat(next_fd)):
                    raise ImageViewError("directory identity mismatch")
                if _directory_handle_identity(parent_before) != _directory_handle_identity(os.fstat(current)):
                    raise ImageViewError("parent directory changed")
                keep_next = True
            finally:
                if not keep_next:
                    with contextlib.suppress(OSError):
                        os.close(next_fd)
            old_fd = current
            current = next_fd
            os.close(old_fd)
        return current
    except BaseException:
        os.close(current)
        raise


def _open_relative_directory(root_fd: int, relative: str | tuple[str, ...]) -> int:
    parts = PurePosixPath(relative).parts if isinstance(relative, str) else relative
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current = os.dup(root_fd)
    try:
        for part in parts:
            if not part or part in {".", ".."} or "/" in part or "\x00" in part:
                raise ImageViewError("unsafe directory component")
            parent_before = os.fstat(current)
            next_fd = os.open(part, flags, dir_fd=current)
            keep_next = False
            try:
                path_info = os.stat(part, dir_fd=current, follow_symlinks=False)
                if not stat.S_ISDIR(path_info.st_mode) or _identity(path_info) != _identity(os.fstat(next_fd)):
                    raise ImageViewError("directory identity mismatch")
                if _directory_handle_identity(parent_before) != _directory_handle_identity(os.fstat(current)):
                    raise ImageViewError("parent directory changed")
                keep_next = True
            finally:
                if not keep_next:
                    with contextlib.suppress(OSError):
                        os.close(next_fd)
            old_fd = current
            current = next_fd
            os.close(old_fd)
        return current
    except BaseException:
        os.close(current)
        raise


def _read_fd(fd: int, *, max_bytes: int | None = None) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, READ_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if max_bytes is not None and total > max_bytes:
            raise ImageViewError("file exceeds maximum accepted size")
        chunks.append(chunk)
    return b"".join(chunks)


def _read_named_regular(parent_fd: int, name: str, *, max_bytes: int | None = None) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        raise ImageViewError("cannot safely open regular file") from error
    try:
        before = os.fstat(fd)
        path_before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or _identity(before) != _identity(path_before):
            raise ImageViewError("file is not an isolated regular file")
        raw = _read_fd(fd, max_bytes=max_bytes)
        after = os.fstat(fd)
        path_after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            len(raw) != before.st_size
            or _identity(before) != _identity(after)
            or _identity(after) != _identity(path_after)
        ):
            raise ImageViewError("file changed while reading")
        return raw, after
    finally:
        os.close(fd)


def _read_relative_regular(
    root_fd: int, relative: str, *, max_bytes: int | None = None
) -> tuple[bytes, os.stat_result]:
    safe = _safe_relative(relative)
    parts = PurePosixPath(safe).parts
    parent_fd = _open_relative_directory(root_fd, tuple(parts[:-1]))
    try:
        return _read_named_regular(parent_fd, parts[-1], max_bytes=max_bytes)
    finally:
        os.close(parent_fd)


def _open_relative_regular(root_fd: int, relative: str) -> tuple[int, int]:
    safe = _safe_relative(relative)
    parts = PurePosixPath(safe).parts
    parent_fd = _open_relative_directory(root_fd, tuple(parts[:-1]))
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(parts[-1], flags, dir_fd=parent_fd)
        keep_fd = False
        try:
            info = os.fstat(fd)
            path_info = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or _identity(info) != _identity(path_info):
                raise ImageViewError("source is not an isolated regular file")
            keep_fd = True
            return fd, parent_fd
        finally:
            if not keep_fd:
                with contextlib.suppress(OSError):
                    os.close(fd)
    except BaseException:
        os.close(parent_fd)
        raise


def _hash_open_file(fd: int, expected_size: int) -> str:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != expected_size:
        raise ImageViewError("regular-file size or link-count drift")
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = os.read(fd, READ_SIZE)
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
    after = os.fstat(fd)
    if total != expected_size or _identity(before) != _identity(after):
        raise ImageViewError("file changed while hashing")
    return digest.hexdigest()


def _run_git(root: Path, *arguments: str) -> bytes:
    environment = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "TMPDIR": "/tmp",
        "LC_ALL": "C",
        "LANG": "C",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
    }
    try:
        process = subprocess.run(
            ("/usr/bin/git", *arguments),
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ImageViewError("git state capture failed") from error
    if process.returncode != 0 or process.stderr:
        raise ImageViewError("git state capture failed")
    return process.stdout


def _git_blob_oid(raw: bytes) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {len(raw)}\0".encode("ascii"))
    digest.update(raw)
    return digest.hexdigest()


def _nul_records(raw: bytes, label: str) -> tuple[bytes, ...]:
    if not raw or not raw.endswith(b"\0"):
        raise ImageViewError(f"invalid {label} output")
    records = tuple(raw[:-1].split(b"\0"))
    if any(not record for record in records):
        raise ImageViewError(f"invalid {label} output")
    return records


def _decode_git_path(raw: bytes) -> str:
    try:
        path = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ImageViewError("official path is not strict UTF-8") from error
    return _safe_relative(path)


def _parse_official_head(raw: bytes) -> tuple[tuple[str, str, str, str], ...]:
    entries: list[tuple[str, str, str, str]] = []
    for record in _nul_records(raw, "official HEAD tree"):
        try:
            metadata, path_raw = record.split(b"\t", 1)
            mode_raw, kind_raw, oid_raw = metadata.split(b" ")
            mode = mode_raw.decode("ascii")
            kind = kind_raw.decode("ascii")
            oid = oid_raw.decode("ascii")
        except (UnicodeDecodeError, ValueError) as error:
            raise ImageViewError("invalid official HEAD tree entry") from error
        expected_kind = {
            "100644": "blob",
            "100755": "blob",
            "120000": "blob",
            "160000": "commit",
        }.get(mode)
        if expected_kind is None or kind != expected_kind or _OID_RE.fullmatch(oid) is None:
            raise ImageViewError("unsupported official HEAD entry mode or type")
        entries.append((mode, kind, oid, _decode_git_path(path_raw)))
    paths = tuple(entry[3] for entry in entries)
    if len(set(paths)) != len(paths):
        raise ImageViewError("duplicate official HEAD path")
    _assert_no_case_collisions(paths)
    return tuple(entries)


def _parse_official_index(raw: bytes) -> tuple[tuple[str, str, str, str], ...]:
    entries: list[tuple[str, str, str, str]] = []
    for record in _nul_records(raw, "official index"):
        if not record.startswith(b"H "):
            raise ImageViewError("official index has unsafe flags")
        try:
            metadata, path_raw = record[2:].split(b"\t", 1)
            mode_raw, oid_raw, stage_raw = metadata.split(b" ")
            mode = mode_raw.decode("ascii")
            oid = oid_raw.decode("ascii")
            stage = stage_raw.decode("ascii")
        except (UnicodeDecodeError, ValueError) as error:
            raise ImageViewError("invalid official index entry") from error
        if mode not in {"100644", "100755", "120000", "160000"} or _OID_RE.fullmatch(oid) is None or stage != "0":
            raise ImageViewError("invalid official index mode, OID, or stage")
        entries.append((mode, "commit" if mode == "160000" else "blob", oid, _decode_git_path(path_raw)))
    paths = tuple(entry[3] for entry in entries)
    if len(set(paths)) != len(paths):
        raise ImageViewError("duplicate official index path")
    _assert_no_case_collisions(paths)
    return tuple(entries)


def _read_relative_symlink(root_fd: int, relative: str) -> tuple[bytes, os.stat_result]:
    safe = _safe_relative(relative)
    parts = PurePosixPath(safe).parts
    parent_fd = _open_relative_directory(root_fd, tuple(parts[:-1]))
    try:
        before = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISLNK(before.st_mode) or before.st_nlink != 1:
            raise ImageViewError("official symlink type or link-count drift")
        target = os.readlink(os.fsencode(parts[-1]), dir_fd=parent_fd)
        if not isinstance(target, bytes):
            raise ImageViewError("official symlink target type drift")
        after = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        if _identity(before) != _identity(after) or before.st_size != len(target):
            raise ImageViewError("official symlink changed while reading")
        return target, after
    finally:
        os.close(parent_fd)


def _validate_official_checkout(root: Path, official_fd: int, official_oid: str) -> int:
    official_root = root / "official"
    head = _parse_official_head(_run_git(official_root, "ls-tree", "-rz", "--full-tree", "HEAD"))
    index = _parse_official_index(_run_git(official_root, "ls-files", "-z", "--stage", "-v"))
    if head != index:
        raise ImageViewError("official HEAD and index entries differ")
    if official_oid == PRODUCTION_OFFICIAL_OID and len(head) != PRODUCTION_OFFICIAL_TRACKED_ENTRIES:
        raise ImageViewError("official tracked-entry count drift")

    for mode, kind, oid, relative in head:
        if kind == "commit":
            raise ImageViewError("nested official gitlinks are forbidden")
        expected_raw = _run_git(official_root, "cat-file", "blob", oid)
        if _git_blob_oid(expected_raw) != oid:
            raise ImageViewError("official HEAD blob identity drift")
        if mode == "120000":
            observed_raw, info = _read_relative_symlink(official_fd, relative)
            if not stat.S_ISLNK(info.st_mode):
                raise ImageViewError("official symlink mode drift")
        else:
            observed_raw, info = _read_relative_regular(official_fd, relative)
            expected_permissions = 0o755 if mode == "100755" else 0o644
            if stat.S_IMODE(info.st_mode) != expected_permissions:
                raise ImageViewError("official regular-file mode drift")
        if observed_raw != expected_raw:
            raise ImageViewError("official working-tree bytes differ from HEAD")
    return len(head)


def _assert_checkout_rebound(root: Path, guard: CheckoutGuard) -> None:
    """Rebind all pathname entry points to the held checkout identities."""
    if root != root.absolute() or Path.cwd().absolute() != root:
        raise ImageViewError("canonical checkout pathname drift")
    if _directory_handle_identity(os.fstat(guard.root_fd)) != guard.root_identity:
        raise ImageViewError("canonical checkout descriptor drift")
    if _directory_handle_identity(os.fstat(guard.git_fd)) != guard.git_identity:
        raise ImageViewError("canonical .git descriptor drift")
    if _directory_handle_identity(os.fstat(guard.official_fd)) != guard.official_identity:
        raise ImageViewError("canonical official descriptor drift")

    fresh_root_fd = _open_absolute_directory(root)
    try:
        if _directory_handle_identity(os.fstat(fresh_root_fd)) != guard.root_identity:
            raise ImageViewError("canonical checkout path identity drift")
    finally:
        os.close(fresh_root_fd)

    for name, held_fd, expected in (
        (".git", guard.git_fd, guard.git_identity),
        ("official", guard.official_fd, guard.official_identity),
    ):
        fresh_fd = _open_relative_directory(guard.root_fd, (name,))
        try:
            path_info = os.stat(name, dir_fd=guard.root_fd, follow_symlinks=False)
            if (
                _directory_handle_identity(path_info) != expected
                or _directory_handle_identity(os.fstat(fresh_fd)) != expected
                or _directory_handle_identity(os.fstat(held_fd)) != expected
            ):
                raise ImageViewError(f"canonical {name} path identity drift")
        finally:
            os.close(fresh_fd)


def _capture_git_state(
    root: Path,
    authority: Authority,
    guard: CheckoutGuard | None = None,
) -> GitState:
    owned_guard = guard is None
    if guard is None:
        guard = _validate_checkout(root)
    try:
        _assert_checkout_rebound(root, guard)
        status = _run_git(
            root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=none",
        )
        if status:
            raise ImageViewError("checkout is not clean")
        commit = _run_git(root, "rev-parse", "--verify", "HEAD").decode("ascii").strip()
        tree = _run_git(root, "rev-parse", "--verify", "HEAD^{tree}").decode("ascii").strip()
        gitlink = _run_git(root, "rev-parse", "--verify", "HEAD:official").decode("ascii").strip()
        official = _run_git(root / "official", "rev-parse", "--verify", "HEAD").decode("ascii").strip()
        official_status = _run_git(
            root / "official",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=none",
        )
        if official_status:
            raise ImageViewError("official checkout is not clean")
        if not _OID_RE.fullmatch(commit) or not _OID_RE.fullmatch(tree):
            raise ImageViewError("invalid git object identity")
        if gitlink != authority.official_oid or official != authority.official_oid:
            raise ImageViewError("official OID drift")
        _validate_official_checkout(root, guard.official_fd, official)
        for relative in authority.builder_sources:
            safe = _safe_relative(relative)
            worktree_raw, _worktree_info = _read_relative_regular(guard.root_fd, safe)
            head_raw = _run_git(root, "show", f"HEAD:{safe}")
            if worktree_raw != head_raw:
                raise ImageViewError("builder source bytes differ from HEAD")
            blob_oid = _run_git(root, "rev-parse", "--verify", f"HEAD:{safe}").decode("ascii").strip()
            if not _OID_RE.fullmatch(blob_oid) or blob_oid != _git_blob_oid(head_raw):
                raise ImageViewError("builder source blob identity drift")
            index_state = _run_git(root, "ls-files", "-v", "--", safe)
            if index_state != f"H {safe}\n".encode():
                raise ImageViewError("builder source index flags are unsafe")
        _assert_checkout_rebound(root, guard)
        return GitState(commit=commit, tree=tree, official_oid=official)
    finally:
        if owned_guard:
            guard.close()


def _validate_checkout(root: Path) -> CheckoutGuard:
    if root != root.absolute() or Path.cwd().absolute() != root:
        raise ImageViewError("operation requires the canonical checkout as cwd")
    root_fd = _open_absolute_directory(root)
    git_fd: int | None = None
    official_fd: int | None = None
    try:
        root_info = os.fstat(root_fd)
        if _identity(root_info) != _identity(root.lstat()):
            raise ImageViewError("canonical checkout identity mismatch")
        git_info = os.stat(".git", dir_fd=root_fd, follow_symlinks=False)
        if not stat.S_ISDIR(git_info.st_mode):
            raise ImageViewError("linked worktrees are forbidden")
        git_fd = os.open(
            ".git",
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
        if _directory_handle_identity(os.fstat(git_fd)) != _directory_handle_identity(git_info):
            raise ImageViewError("canonical .git identity mismatch")
        official_info = os.stat("official", dir_fd=root_fd, follow_symlinks=False)
        if not stat.S_ISDIR(official_info.st_mode):
            raise ImageViewError("official checkout is not a directory")
        official_fd = os.open(
            "official",
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
        if _directory_handle_identity(os.fstat(official_fd)) != _directory_handle_identity(official_info):
            raise ImageViewError("canonical official identity mismatch")
        return CheckoutGuard(
            root_fd=root_fd,
            git_fd=git_fd,
            official_fd=official_fd,
            root_identity=_directory_handle_identity(root_info),
            git_identity=_directory_handle_identity(git_info),
            official_identity=_directory_handle_identity(official_info),
        )
    except BaseException:
        if official_fd is not None:
            with contextlib.suppress(OSError):
                os.close(official_fd)
        if git_fd is not None:
            with contextlib.suppress(OSError):
                os.close(git_fd)
        os.close(root_fd)
        raise


def _require_dict(value: object, keys: set[str], label: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise ImageViewError(f"{label} schema drift")
    return value


def _require_nonnegative_int(value: object, label: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        raise ImageViewError(f"invalid {label}")
    return value


def _require_sha(value: object, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise ImageViewError(f"invalid {label}")
    return value


def _assert_no_case_collisions(paths: Iterable[str]) -> None:
    children: dict[tuple[str, ...], dict[str, str]] = {}
    for raw in paths:
        parts = PurePosixPath(_safe_relative(raw)).parts
        for index, part in enumerate(parts):
            parent = parts[:index]
            folded = part.casefold()
            previous = children.setdefault(parent, {}).get(folded)
            if previous is not None and previous != part:
                raise ImageViewError("case-colliding inventory paths")
            children[parent][folded] = part


def _validate_ready(value: object, raw: bytes, authority: Authority) -> tuple[dict[str, object], tuple[int, int]]:
    ready = _require_dict(
        value,
        {
            "created_utc",
            "data_root_identity",
            "decoded",
            "digest_scope",
            "import_receipt",
            "inventory",
            "manifest",
            "ready_content_sha256",
            "schema_version",
            "status",
            "verifier",
        },
        "READY",
    )
    if _sha256(raw) != authority.ready_sha256:
        raise ImageViewError("READY hash drift")
    if ready["schema_version"] != READY_SCHEMA or ready["status"] != "READY":
        raise ImageViewError("READY status drift")
    if ready["ready_content_sha256"] != authority.ready_content_sha256:
        raise ImageViewError("READY content hash drift")
    core = dict(ready)
    del core["created_utc"]
    del core["ready_content_sha256"]
    if _sha256(canonical_json_bytes(core)) != authority.ready_content_sha256:
        raise ImageViewError("READY content digest does not verify")
    identity = _require_dict(ready["data_root_identity"], {"device", "inode"}, "READY data identity")
    device = _require_nonnegative_int(identity["device"], "READY device", positive=True)
    inode = _require_nonnegative_int(identity["inode"], "READY inode", positive=True)
    inventory = _require_dict(ready["inventory"], {"bytes", "path", "sha256", "summary"}, "READY inventory")
    if inventory["path"] != "IMAGE_CONTENT_INVENTORY.json" or inventory["sha256"] != authority.inventory_sha256:
        raise ImageViewError("READY inventory authority drift")
    _require_nonnegative_int(inventory["bytes"], "READY inventory bytes", positive=True)
    summary = _require_dict(inventory["summary"], {"chunks", "files", "roots", "stored_bytes"}, "READY summary")
    if (
        summary["files"] != len(authority.stems) * authority.files_per_root
        or summary["roots"] != len(authority.stems)
        or summary["stored_bytes"] != authority.stored_bytes
    ):
        raise ImageViewError("READY summary drift")
    import_value = _require_dict(
        ready["import_receipt"],
        {"bytes", "installed", "reference", "sha256", "skipped", "status", "validated"},
        "READY import receipt",
    )
    if (
        import_value["reference"] != PurePosixPath(authority.import_receipt_relative).name
        or import_value["sha256"] != authority.import_receipt_sha256
        or import_value["status"] != "PASS"
    ):
        raise ImageViewError("READY import receipt drift")
    _require_nonnegative_int(import_value["bytes"], "import receipt bytes", positive=True)
    return ready, (device, inode)


def _validate_inventory(
    value: object,
    raw: bytes,
    ready: dict[str, object],
    authority: Authority,
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    inventory = _require_dict(value, {"files", "roots", "schema_version", "summary"}, "inventory")
    if _sha256(raw) != authority.inventory_sha256 or inventory["schema_version"] != INVENTORY_SCHEMA:
        raise ImageViewError("inventory authority drift")
    ready_inventory = ready["inventory"]
    assert isinstance(ready_inventory, dict)
    if ready_inventory["bytes"] != len(raw) or ready_inventory["sha256"] != _sha256(raw):
        raise ImageViewError("READY inventory byte binding drift")
    if inventory["roots"] != list(authority.stems):
        raise ImageViewError("fixed EVAL36 order drift")
    summary = _require_dict(inventory["summary"], {"chunks", "files", "roots", "stored_bytes"}, "inventory summary")
    if summary != ready_inventory["summary"]:
        raise ImageViewError("inventory summary disagrees with READY")
    files = inventory["files"]
    if type(files) is not list or len(files) != len(authority.stems) * authority.files_per_root:
        raise ImageViewError("inventory file count drift")
    records: list[dict[str, object]] = []
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    paths_by_stem: dict[str, set[str]] = {stem: set() for stem in authority.stems}
    total = 0
    stem_set = set(authority.stems)
    for value_record in files:
        record = _require_dict(value_record, {"bytes", "path", "sha256", "stem"}, "inventory file")
        path = _safe_relative(record["path"])
        size = _require_nonnegative_int(record["bytes"], "inventory bytes", positive=True)
        digest = _require_sha(record["sha256"], "inventory hash")
        stem = record["stem"]
        if type(stem) is not str or stem not in stem_set:
            raise ImageViewError("inventory stem drift")
        parts = PurePosixPath(path).parts
        if len(parts) < 2 or parts[0] != f"{stem}.zarr":
            raise ImageViewError("inventory path is outside its fixed Zarr root")
        if path in seen:
            raise ImageViewError("duplicate inventory path")
        seen.add(path)
        counts[stem] += 1
        paths_by_stem[stem].add(path)
        total += size
        records.append({"bytes": size, "path": path, "sha256": digest, "stem": stem})
    if [str(record["path"]) for record in records] != sorted(seen, key=lambda item: item.encode("utf-8")):
        raise ImageViewError("inventory order drift")
    if any(counts[stem] != authority.files_per_root for stem in authority.stems):
        raise ImageViewError("per-root inventory count drift")
    if authority.files_per_root != len(authority.file_suffixes):
        raise ImageViewError("fixed Zarr layout configuration drift")
    for stem in authority.stems:
        expected_paths = {f"{stem}.zarr/{suffix}" for suffix in authority.file_suffixes}
        if paths_by_stem[stem] != expected_paths:
            raise ImageViewError("fixed Zarr path layout drift")
    if total != authority.stored_bytes:
        raise ImageViewError("inventory aggregate byte drift")
    _assert_no_case_collisions(seen)
    return inventory, tuple(records)


def _load_authority(root_fd: int, authority: Authority) -> LoadedAuthority:
    ready_raw, _ = _read_relative_regular(root_fd, authority.ready_relative, max_bytes=MAX_JSON_BYTES)
    ready, source_identity = _validate_ready(_strict_json_bytes(ready_raw), ready_raw, authority)
    ready_parent = str(PurePosixPath(authority.ready_relative).parent)
    inventory_relative = f"{ready_parent}/IMAGE_CONTENT_INVENTORY.json"
    inventory_raw, _ = _read_relative_regular(root_fd, inventory_relative, max_bytes=MAX_JSON_BYTES)
    inventory, records = _validate_inventory(_strict_json_bytes(inventory_raw), inventory_raw, ready, authority)
    import_raw, _ = _read_relative_regular(
        root_fd,
        authority.import_receipt_relative,
        max_bytes=MAX_JSON_BYTES,
    )
    if _sha256(import_raw) != authority.import_receipt_sha256:
        raise ImageViewError("import receipt hash drift")
    _strict_json_bytes(import_raw)
    import_binding = ready["import_receipt"]
    assert isinstance(import_binding, dict)
    if import_binding["bytes"] != len(import_raw):
        raise ImageViewError("import receipt byte count drift")
    return LoadedAuthority(
        ready=ready,
        ready_raw=ready_raw,
        inventory=inventory,
        inventory_raw=inventory_raw,
        records=records,
        import_raw=import_raw,
        source_identity=source_identity,
    )


def _source_bindings(root_fd: int, authority: Authority) -> tuple[dict[str, object], ...]:
    bindings: list[dict[str, object]] = []
    for relative in authority.builder_sources:
        raw, _ = _read_relative_regular(root_fd, relative, max_bytes=4 * 1024 * 1024)
        bindings.append({"bytes": len(raw), "path": relative, "sha256": _sha256(raw)})
    return tuple(bindings)


def _filesystem_type(_path: Path, fd: int) -> str:
    """Return the filesystem type from an already verified directory FD."""
    if sys.platform != "darwin":
        raise ImageViewError("APFS image-view construction requires macOS")
    before = os.fstat(fd)
    result = _DarwinStatFs()
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        function = libc.fstatfs
    except AttributeError as error:  # pragma: no cover - every supported macOS has fstatfs
        raise ImageViewError("filesystem type probe is unavailable") from error
    function.argtypes = [ctypes.c_int, ctypes.POINTER(_DarwinStatFs)]
    function.restype = ctypes.c_int
    if function(fd, ctypes.byref(result)) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
    if _identity(before) != _identity(os.fstat(fd)):
        raise ImageViewError("filesystem type probe was unstable")
    try:
        value = bytes(result.f_fstypename).split(b"\0", 1)[0].decode("ascii").lower()
    except UnicodeDecodeError as error:
        raise ImageViewError("filesystem type probe was invalid") from error
    if value != "apfs":
        raise ImageViewError("source and output must be on APFS")
    return value


def _clone_method() -> str:
    if sys.platform != "darwin":
        raise ImageViewError("fclonefileat is unavailable")
    libc = ctypes.CDLL(None, use_errno=True)
    if not hasattr(libc, "fclonefileat"):
        raise ImageViewError("fclonefileat is unavailable")
    return "fclonefileat(APFS_CLONEFILE)"


def _clone_file(source_fd: int, destination_parent_fd: int, destination_name: str) -> None:
    if sys.platform != "darwin":
        raise ImageViewError("fclonefileat is unavailable")
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        function = libc.fclonefileat
    except AttributeError as error:
        raise ImageViewError("fclonefileat is unavailable") from error
    function.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    function.restype = ctypes.c_int
    result = function(source_fd, destination_parent_fd, os.fsencode(destination_name), 0)
    if result != 0:
        number = ctypes.get_errno()
        if number in {errno.EXDEV, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS, errno.EINVAL}:
            raise ImageViewError("APFS clonefile is unsupported for this source/output pair")
        if number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise ImageViewError("clone destination collision")
        raise OSError(number, os.strerror(number), destination_name)


def _publication_primitive() -> str:
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        return "renameatx_np(RENAME_EXCL)"
    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        return "renameat2(RENAME_NOREPLACE)"
    raise ImageViewError("atomic no-replace directory rename is unavailable")


def _rename_noreplace(parent_fd: int, source: str, destination: str) -> str:
    primitive = _publication_primitive()
    libc = ctypes.CDLL(None, use_errno=True)
    if primitive == "renameatx_np(RENAME_EXCL)":
        function = libc.renameatx_np
        flags = 0x00000004
    else:
        function = libc.renameat2
        flags = 0x1
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    result = function(parent_fd, os.fsencode(source), parent_fd, os.fsencode(destination), flags)
    if result != 0:
        number = ctypes.get_errno()
        if number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(destination)
        if number in {errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EINVAL}:
            raise ImageViewError("atomic no-replace directory rename is unavailable")
        raise OSError(number, os.strerror(number), destination)
    return primitive


def _ensure_output_parent(root_fd: int, relative: str) -> int:
    parts = PurePosixPath(_safe_relative(relative)).parts
    current = os.dup(root_fd)
    try:
        for part in parts:
            try:
                os.mkdir(part, 0o700, dir_fd=current)
            except FileExistsError:
                pass
            else:
                os.fsync(current)
            next_fd = _open_relative_directory(current, (part,))
            try:
                os.close(current)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.close(next_fd)
                raise
            current = next_fd
        return current
    except BaseException:
        os.close(current)
        raise


def _constrain_run_dir(root: Path, run_dir: Path, authority: Authority) -> tuple[Path, str]:
    absolute = run_dir.absolute()
    expected_parent = root / authority.output_parent_relative
    if absolute.parent != expected_parent or _RUN_NAME_RE.fullmatch(absolute.name) is None:
        raise ImageViewError("run directory must be one direct safe child of the fixed output parent")
    return absolute, absolute.name


def _name_info(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _create_directory(
    staging_fd: int,
    relative: str,
    ownership: _StagingOwnership,
) -> None:
    parts = PurePosixPath(_safe_relative(relative)).parts
    parent_fd = _open_relative_directory(staging_fd, tuple(parts[:-1]))
    try:
        if _name_info(parent_fd, parts[-1]) is not None:
            raise ImageViewError("staging directory collision")
        os.mkdir(parts[-1], 0o700, dir_fd=parent_fd)
        created_info = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(created_info.st_mode):
            raise ImageViewError("directory creation postcondition failed")
        ownership.directories[relative] = _ownership(created_info)
        child_fd = _open_relative_directory(parent_fd, (parts[-1],))
        try:
            info = os.fstat(child_fd)
            if _ownership(info) != ownership.directories[relative]:
                raise ImageViewError("created directory identity drift")
            os.fsync(child_fd)
        finally:
            os.close(child_fd)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _expected_directories(records: Iterable[dict[str, object]]) -> tuple[str, ...]:
    directories = {"IMAGE_VIEW"}
    for record in records:
        parts = PurePosixPath(str(record["path"])).parts[:-1]
        for depth in range(1, len(parts) + 1):
            directories.add(PurePosixPath("IMAGE_VIEW", *parts[:depth]).as_posix())
    return tuple(sorted(directories, key=lambda item: (len(PurePosixPath(item).parts), item.encode("utf-8"))))


def _expected_view_directories(records: Iterable[dict[str, object]]) -> set[str]:
    return {
        relative.removeprefix("IMAGE_VIEW/") for relative in _expected_directories(records) if relative != "IMAGE_VIEW"
    }


def _walk_tree(
    directory_fd: int, prefix: str = ""
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    before = os.fstat(directory_fd)
    try:
        names = os.listdir(directory_fd)
    except OSError as error:
        raise ImageViewError("tree enumeration failed") from error
    if len({name.casefold() for name in names}) != len(names):
        raise ImageViewError("case-colliding directory entries")
    files: list[dict[str, object]] = []
    directories: list[dict[str, object]] = []
    for name in sorted(names, key=lambda item: item.encode("utf-8")):
        if not name or name in {".", ".."} or "/" in name or "\x00" in name:
            raise ImageViewError("unsafe directory entry")
        relative = f"{prefix}/{name}" if prefix else name
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            child_fd = _open_relative_directory(directory_fd, (name,))
            try:
                child_info = os.fstat(child_fd)
                directories.append({"identity": _identity_value(child_info), "path": relative})
                child_files, child_directories = _walk_tree(child_fd, relative)
                files.extend(child_files)
                directories.extend(child_directories)
            finally:
                os.close(child_fd)
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            files.append({"identity": _identity_value(info), "path": relative})
        else:
            raise ImageViewError("tree contains symlink, special, or multiply-linked entry")
    if _identity(before) != _identity(os.fstat(directory_fd)):
        raise ImageViewError("directory changed while enumerating")
    return tuple(files), tuple(directories)


def _scan_source_layout(train_fd: int, records: tuple[dict[str, object], ...], stems: tuple[str, ...]) -> bytes:
    by_stem: dict[str, set[str]] = {stem: set() for stem in stems}
    for record in records:
        by_stem[str(record["stem"])].add(str(record["path"]))
    complete: list[dict[str, object]] = []
    for stem in stems:
        root_name = f"{stem}.zarr"
        root_fd = _open_relative_directory(train_fd, (root_name,))
        try:
            root_info = os.fstat(root_fd)
            files, directories = _walk_tree(root_fd, root_name)
        finally:
            os.close(root_fd)
        actual = {str(item["path"]) for item in files}
        if actual != by_stem[stem]:
            raise ImageViewError("source Zarr member set drift")
        expected_directories = {root_name}
        for path in by_stem[stem]:
            parts = PurePosixPath(path).parts[:-1]
            for depth in range(1, len(parts) + 1):
                expected_directories.add(PurePosixPath(*parts[:depth]).as_posix())
        actual_directories = {root_name, *(str(item["path"]) for item in directories)}
        if actual_directories != expected_directories:
            raise ImageViewError("source Zarr directory set drift")
        complete.append({"identity": _identity_value(root_info), "path": root_name, "type": "directory"})
        complete.extend({**item, "type": "directory"} for item in directories)
        complete.extend({**item, "type": "file"} for item in files)
    complete.sort(key=lambda item: (str(item["path"]).encode("utf-8"), str(item["type"])))
    return canonical_json_bytes(complete)


def _record_digest(records: list[dict[str, object]], field: str) -> str:
    projected = [
        {
            "bytes": record["bytes"],
            "identity": record[field],
            "path": record["path"],
            "sha256": record["sha256"],
        }
        for record in records
    ]
    return _sha256(canonical_json_bytes(projected))


def _assert_destination_snapshot(
    view_fd: int,
    authority_records: tuple[dict[str, object], ...],
    receipt_records: list[dict[str, object]],
) -> bytes:
    files, directories = _walk_tree(view_fd)
    expected_files = {str(record["path"]) for record in authority_records}
    if {str(item["path"]) for item in files} != expected_files:
        raise ImageViewError("destination file member set drift")
    if {str(item["path"]) for item in directories} != _expected_view_directories(authority_records):
        raise ImageViewError("destination directory member set drift")
    expected_identities = {
        str(record["path"]): _identity_from_value(record["destination"]) for record in receipt_records
    }
    if set(expected_identities) != expected_files:
        raise ImageViewError("destination receipt path set drift")
    for item in files:
        path = str(item["path"])
        identity = _identity_from_value(item["identity"])
        if identity != expected_identities[path]:
            raise ImageViewError("destination file identity drift")
        if identity[3] != 1 or stat.S_IMODE(identity[2]) & 0o222:
            raise ImageViewError("destination file link or mode drift")
    for item in directories:
        identity = _identity_from_value(item["identity"])
        if stat.S_IMODE(identity[2]) & 0o222:
            raise ImageViewError("destination directory mode drift")
    view_info = os.fstat(view_fd)
    if stat.S_IMODE(view_info.st_mode) & 0o222:
        raise ImageViewError("image-view root is writable")
    return canonical_json_bytes({"directories": list(directories), "files": list(files)})


def _write_new_regular(parent_fd: int, name: str, raw: bytes, mode: int = 0o444) -> os.stat_result:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(name, flags, mode, dir_fd=parent_fd)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise ImageViewError("short receipt write")
            view = view[written:]
        os.fchmod(fd, mode)
        os.fsync(fd)
        info = os.fstat(fd)
        path_info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or _identity(info) != _identity(path_info):
            raise ImageViewError("receipt identity drift")
        return info
    finally:
        os.close(fd)


def _set_directories_read_only(staging_fd: int, ownership: _StagingOwnership) -> None:
    ordered = sorted(
        ownership.directories,
        key=lambda item: (-len(PurePosixPath(item).parts), item.encode("utf-8")),
    )
    for relative in ordered:
        fd = _open_relative_directory(staging_fd, relative)
        try:
            if _ownership(os.fstat(fd)) != ownership.directories[relative]:
                raise ImageViewError("owned directory identity drift")
            os.fchmod(fd, 0o555)
            os.fsync(fd)
        finally:
            os.close(fd)


def _cleanup_staging(parent_fd: int, staging_fd: int, ownership: _StagingOwnership) -> None:
    problems: list[str] = []
    try:
        os.fchmod(staging_fd, 0o700)
    except OSError:
        problems.append("staging chmod")
    for relative in sorted(ownership.directories, key=lambda item: len(PurePosixPath(item).parts)):
        try:
            fd = _open_relative_directory(staging_fd, relative)
            try:
                if _ownership(os.fstat(fd)) != ownership.directories[relative]:
                    problems.append("directory ownership")
                else:
                    os.fchmod(fd, 0o700)
            finally:
                os.close(fd)
        except OSError:
            problems.append("directory reopen")
        except ImageViewError:
            problems.append("directory reopen")
    for relative, expected in sorted(
        ownership.files.items(),
        key=lambda item: item[0].encode("utf-8"),
        reverse=True,
    ):
        parts = PurePosixPath(relative).parts
        try:
            parent = _open_relative_directory(staging_fd, tuple(parts[:-1]))
            try:
                info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                if _ownership(info) != expected or stat.S_ISDIR(info.st_mode):
                    problems.append("file ownership")
                else:
                    os.unlink(parts[-1], dir_fd=parent)
                    os.fsync(parent)
            finally:
                os.close(parent)
        except FileNotFoundError:
            continue
        except (OSError, ImageViewError):
            problems.append("file cleanup")
    for relative, expected in sorted(
        ownership.directories.items(),
        key=lambda item: (-len(PurePosixPath(item[0]).parts), item[0].encode("utf-8")),
    ):
        parts = PurePosixPath(relative).parts
        try:
            parent = _open_relative_directory(staging_fd, tuple(parts[:-1]))
            try:
                info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                if _ownership(info) != expected or not stat.S_ISDIR(info.st_mode):
                    problems.append("directory ownership")
                else:
                    os.rmdir(parts[-1], dir_fd=parent)
                    os.fsync(parent)
            finally:
                os.close(parent)
        except FileNotFoundError:
            continue
        except (OSError, ImageViewError):
            problems.append("directory cleanup")
    try:
        if os.listdir(staging_fd):
            problems.append("unexpected staging members")
        os.fsync(staging_fd)
    except OSError:
        problems.append("staging absence fsync")
    if problems:
        raise PublicationAmbiguityError("owned staging cleanup is ambiguous")
    info = _name_info(parent_fd, ownership.name)
    if info is None or _ownership(info) != ownership.identity or not stat.S_ISDIR(info.st_mode):
        raise PublicationAmbiguityError("staging ownership changed before removal")
    try:
        os.rmdir(ownership.name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except OSError as error:
        raise PublicationAmbiguityError("staging removal is not durable") from error
    if _name_info(parent_fd, ownership.name) is not None:
        raise PublicationAmbiguityError("staging remains after removal")


def _recover_publication(
    parent_fd: int,
    staging_fd: int,
    ownership: _StagingOwnership,
    final_name: str,
    cause: BaseException,
) -> None:
    staging_info = _name_info(parent_fd, ownership.name)
    final_info = _name_info(parent_fd, final_name)
    staging_owned = staging_info is not None and _ownership(staging_info) == ownership.identity
    final_owned = final_info is not None and _ownership(final_info) == ownership.identity
    if staging_owned and not final_owned:
        _cleanup_staging(parent_fd, staging_fd, ownership)
        return
    if final_owned and not staging_owned:
        try:
            primitive = _rename_noreplace(parent_fd, final_name, ownership.name)
            if primitive != _publication_primitive():
                raise ImageViewError("rollback primitive drift")
            os.fsync(parent_fd)
        except BaseException as error:
            raise PublicationAmbiguityError("published directory rollback failed") from ExceptionGroup(
                "publication and rollback failed",
                [cause, error],
            )
        _cleanup_staging(parent_fd, staging_fd, ownership)
        return
    raise PublicationAmbiguityError("publication ownership is ambiguous") from cause


def _recover_unopened_staging(
    parent_fd: int,
    ownership: _StagingOwnership,
    cause: BaseException,
) -> None:
    """Durably remove a just-created staging directory that could not be opened."""
    try:
        info = _name_info(parent_fd, ownership.name)
        if info is None or not stat.S_ISDIR(info.st_mode) or _ownership(info) != ownership.identity:
            raise PublicationAmbiguityError("unopened staging ownership is ambiguous")
        os.rmdir(ownership.name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        if _name_info(parent_fd, ownership.name) is not None:
            raise PublicationAmbiguityError("unopened staging remains after removal")
    except PublicationAmbiguityError:
        raise
    except BaseException as error:
        raise PublicationAmbiguityError("unopened staging cleanup is not durable") from ExceptionGroup(
            "staging open and cleanup failed",
            [cause, error],
        )


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _valid_utc(value: str) -> bool:
    if _UTC_RE.fullmatch(value) is None:
        return False
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo == dt.UTC and parsed.microsecond == 0


def _build_receipt(
    *,
    authority: Authority,
    loaded: LoadedAuthority,
    git: GitState,
    bindings: tuple[dict[str, object], ...],
    run_relative: str,
    source_info: os.stat_result,
    image_view_info: os.stat_result,
    records: list[dict[str, object]],
    source_layout_digest: str,
    filesystem: str,
    clone_method: str,
    publication: str,
    created_utc: str,
) -> dict[str, object]:
    if not _valid_utc(created_utc):
        raise ImageViewError("invalid UTC timestamp")
    core: dict[str, object] = {
        "authority": {
            "import_receipt": {
                "bytes": len(loaded.import_raw),
                "path": authority.import_receipt_relative,
                "sha256": authority.import_receipt_sha256,
            },
            "inventory": {
                "bytes": len(loaded.inventory_raw),
                "path": str(PurePosixPath(authority.ready_relative).parent / "IMAGE_CONTENT_INVENTORY.json"),
                "sha256": authority.inventory_sha256,
            },
            "ready": {
                "bytes": len(loaded.ready_raw),
                "content_sha256": authority.ready_content_sha256,
                "path": authority.ready_relative,
                "sha256": authority.ready_sha256,
            },
        },
        "builder": {
            "clone_method": clone_method,
            "filesystem": filesystem,
            "publication_primitive": publication,
            "sources": list(bindings),
        },
        "claims": {
            "all_destination_files_nlink_one": True,
            "all_destination_files_read_only": True,
            "all_file_contents_rehashed": True,
            "all_source_destination_inodes_distinct": True,
            "apfs_clonefile_only": True,
            "ground_truth_payload_read": False,
            "image_payload_decoded": False,
            "source_train_directory_enumerated": False,
            "source_paths_limited_to_ready_inventory": True,
        },
        "evidence": {
            "bytes": sum(int(record["bytes"]) for record in records),
            "destination_records_sha256": _record_digest(records, "destination"),
            "files": len(records),
            "source_after_records_sha256": _record_digest(records, "source_after"),
            "source_before_records_sha256": _record_digest(records, "source_before"),
            "source_layout_sha256": source_layout_digest,
        },
        "git": dataclasses.asdict(git),
        "image_view": {
            "identity": {"device": image_view_info.st_dev, "inode": image_view_info.st_ino},
            "path": "IMAGE_VIEW",
            "roots": list(authority.stems),
        },
        "records": records,
        "run_directory": run_relative,
        "schema_version": SCHEMA_VERSION,
        "source": {
            "identity": {"device": source_info.st_dev, "inode": source_info.st_ino},
            "path": authority.source_relative,
        },
        "status": "READY",
    }
    return {
        **core,
        "created_utc": created_utc,
        "receipt_content_sha256": _sha256(canonical_json_bytes(core)),
    }


def _validate_receipt(
    value: object,
    *,
    authority: Authority,
    loaded: LoadedAuthority,
    git: GitState,
    bindings: tuple[dict[str, object], ...],
    run_relative: str,
) -> dict[str, object]:
    receipt = _require_dict(
        value,
        {
            "authority",
            "builder",
            "claims",
            "created_utc",
            "evidence",
            "git",
            "image_view",
            "receipt_content_sha256",
            "records",
            "run_directory",
            "schema_version",
            "source",
            "status",
        },
        "image-view receipt",
    )
    if receipt["schema_version"] != SCHEMA_VERSION or receipt["status"] != "READY":
        raise ImageViewError("image-view receipt status drift")
    created = receipt["created_utc"]
    if type(created) is not str or not _valid_utc(created):
        raise ImageViewError("invalid receipt timestamp")
    core = dict(receipt)
    del core["created_utc"]
    digest = core.pop("receipt_content_sha256")
    if _require_sha(digest, "receipt content hash") != _sha256(canonical_json_bytes(core)):
        raise ImageViewError("receipt content digest mismatch")
    if receipt["run_directory"] != run_relative:
        raise ImageViewError("receipt run-directory binding drift")
    if receipt["git"] != dataclasses.asdict(git):
        raise ImageViewError("receipt git binding drift")
    authority_value = _require_dict(receipt["authority"], {"import_receipt", "inventory", "ready"}, "receipt authority")
    expected_authority = {
        "import_receipt": {
            "bytes": len(loaded.import_raw),
            "path": authority.import_receipt_relative,
            "sha256": authority.import_receipt_sha256,
        },
        "inventory": {
            "bytes": len(loaded.inventory_raw),
            "path": str(PurePosixPath(authority.ready_relative).parent / "IMAGE_CONTENT_INVENTORY.json"),
            "sha256": authority.inventory_sha256,
        },
        "ready": {
            "bytes": len(loaded.ready_raw),
            "content_sha256": authority.ready_content_sha256,
            "path": authority.ready_relative,
            "sha256": authority.ready_sha256,
        },
    }
    if authority_value != expected_authority:
        raise ImageViewError("receipt authority binding drift")
    builder = _require_dict(
        receipt["builder"],
        {"clone_method", "filesystem", "publication_primitive", "sources"},
        "receipt builder",
    )
    if builder["sources"] != list(bindings):
        raise ImageViewError("builder source binding drift")
    if (
        builder["filesystem"] != "apfs"
        or builder["clone_method"] != "fclonefileat(APFS_CLONEFILE)"
        or builder["clone_method"] != _clone_method()
    ):
        raise ImageViewError("builder method drift")
    if (
        builder["publication_primitive"]
        not in {
            "renameatx_np(RENAME_EXCL)",
            "renameat2(RENAME_NOREPLACE)",
        }
        or builder["publication_primitive"] != _publication_primitive()
    ):
        raise ImageViewError("publication primitive drift")
    claims = _require_dict(
        receipt["claims"],
        {
            "all_destination_files_nlink_one",
            "all_destination_files_read_only",
            "all_file_contents_rehashed",
            "all_source_destination_inodes_distinct",
            "apfs_clonefile_only",
            "ground_truth_payload_read",
            "image_payload_decoded",
            "source_paths_limited_to_ready_inventory",
            "source_train_directory_enumerated",
        },
        "receipt claims",
    )
    expected_claims = {
        "all_destination_files_nlink_one": True,
        "all_destination_files_read_only": True,
        "all_file_contents_rehashed": True,
        "all_source_destination_inodes_distinct": True,
        "apfs_clonefile_only": True,
        "ground_truth_payload_read": False,
        "image_payload_decoded": False,
        "source_paths_limited_to_ready_inventory": True,
        "source_train_directory_enumerated": False,
    }
    if claims != expected_claims:
        raise ImageViewError("receipt claim drift")
    return receipt


def build_image_view(
    run_dir: Path,
    *,
    now: Callable[[], str] = _utc_now,
) -> dict[str, object]:
    """Build and no-replace publish the fixed production image-only view."""
    authority = PRODUCTION_AUTHORITY
    root = CANONICAL_REPO_ROOT
    _run_absolute, final_name = _constrain_run_dir(root, run_dir, authority)
    checkout = _validate_checkout(root)
    root_fd = checkout.root_fd
    parent_fd: int | None = None
    train_fd: int | None = None
    staging_fd: int | None = None
    ownership: _StagingOwnership | None = None
    published = False
    recovery_attempted = False
    try:
        git_before = _capture_git_state(root, authority, checkout)
        loaded = _load_authority(root_fd, authority)
        bindings_before = _source_bindings(root_fd, authority)
        train_fd = _open_relative_directory(root_fd, authority.source_relative)
        train_info = os.fstat(train_fd)
        train_identity_before = _identity(train_info)
        if _ownership(train_info) != loaded.source_identity:
            raise ImageViewError("source train identity disagrees with READY")
        source_fs = _filesystem_type(root / authority.source_relative, train_fd)
        parent_fd = _ensure_output_parent(root_fd, authority.output_parent_relative)
        parent_path = root / authority.output_parent_relative
        output_fs = _filesystem_type(parent_path, parent_fd)
        if source_fs != "apfs" or output_fs != "apfs" or train_info.st_dev != os.fstat(parent_fd).st_dev:
            raise ImageViewError("source and output are not on one APFS filesystem")
        if _name_info(parent_fd, final_name) is not None:
            raise FileExistsError(final_name)
        clone_method = _clone_method()
        publication = _publication_primitive()
        source_layout_before = _scan_source_layout(train_fd, loaded.records, authority.stems)
        source_layout_digest = _sha256(source_layout_before)

        for _ in range(32):
            staging_name = f".{final_name}.staging.{os.getpid()}.{secrets.token_hex(8)}"
            parent_before_mkdir = _directory_handle_identity(os.fstat(parent_fd))
            try:
                os.mkdir(staging_name, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                continue
            created_info = os.stat(staging_name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                not stat.S_ISDIR(created_info.st_mode)
                or stat.S_IMODE(created_info.st_mode) != 0o700
                or _directory_handle_identity(os.fstat(parent_fd)) != parent_before_mkdir
            ):
                raise PublicationAmbiguityError("new staging directory identity is ambiguous")
            ownership = _StagingOwnership(
                name=staging_name,
                identity=_ownership(created_info),
                directories={},
                files={},
            )
            break
        else:
            raise ImageViewError("cannot allocate fresh staging directory")
        try:
            os.fsync(parent_fd)
            staging_fd = _open_relative_directory(parent_fd, (staging_name,))
        except BaseException as error:
            recovery_attempted = True
            _recover_unopened_staging(parent_fd, ownership, error)
            raise
        staging_info = os.fstat(staging_fd)
        if _ownership(staging_info) != ownership.identity:
            raise ImageViewError("new staging directory identity changed while opening")
        for relative in _expected_directories(loaded.records):
            _create_directory(staging_fd, relative, ownership)

        built_records: list[dict[str, object]] = []
        image_view_fd = _open_relative_directory(staging_fd, "IMAGE_VIEW")
        try:
            for expected in loaded.records:
                relative = str(expected["path"])
                expected_size = int(expected["bytes"])
                expected_sha = str(expected["sha256"])
                source_fd, source_parent_fd = _open_relative_regular(train_fd, relative)
                destination_parent_fd: int | None = None
                destination_fd: int | None = None
                try:
                    destination_parts = PurePosixPath(relative).parts
                    destination_parent_relative = PurePosixPath(*destination_parts[:-1]).as_posix()
                    destination_parent_fd = _open_relative_directory(image_view_fd, destination_parent_relative)
                    source_before = os.fstat(source_fd)
                    source_path_before = os.stat(
                        destination_parts[-1],
                        dir_fd=source_parent_fd,
                        follow_symlinks=False,
                    )
                    if _identity(source_before) != _identity(source_path_before):
                        raise ImageViewError("source path identity drift")
                    if _hash_open_file(source_fd, expected_size) != expected_sha:
                        raise ImageViewError("source content disagrees with READY inventory")
                    os.lseek(source_fd, 0, os.SEEK_SET)
                    staging_relative = f"IMAGE_VIEW/{relative}"
                    try:
                        _clone_file(source_fd, destination_parent_fd, destination_parts[-1])
                    except BaseException:
                        partial_info = _name_info(destination_parent_fd, destination_parts[-1])
                        if partial_info is not None and not stat.S_ISDIR(partial_info.st_mode):
                            ownership.files[staging_relative] = _ownership(partial_info)
                        raise
                    created_info = os.stat(
                        destination_parts[-1],
                        dir_fd=destination_parent_fd,
                        follow_symlinks=False,
                    )
                    if stat.S_ISDIR(created_info.st_mode):
                        raise ImageViewError("clone unexpectedly created a directory")
                    ownership.files[staging_relative] = _ownership(created_info)
                    source_after = os.fstat(source_fd)
                    source_path_after = os.stat(
                        destination_parts[-1],
                        dir_fd=source_parent_fd,
                        follow_symlinks=False,
                    )
                    if _hash_open_file(source_fd, expected_size) != expected_sha:
                        raise ImageViewError("source changed after clone")
                    if _identity(source_before) != _identity(source_after) or _identity(source_after) != _identity(
                        source_path_after
                    ):
                        raise ImageViewError("source identity changed across clone")
                    destination_fd = os.open(
                        destination_parts[-1],
                        os.O_RDONLY
                        | getattr(os, "O_CLOEXEC", 0)
                        | getattr(os, "O_NONBLOCK", 0)
                        | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=destination_parent_fd,
                    )
                    destination_initial = os.fstat(destination_fd)
                    destination_path_initial = os.stat(
                        destination_parts[-1],
                        dir_fd=destination_parent_fd,
                        follow_symlinks=False,
                    )
                    if (
                        not stat.S_ISREG(destination_initial.st_mode)
                        or destination_initial.st_nlink != 1
                        or _identity(destination_initial) != _identity(destination_path_initial)
                        or destination_initial.st_dev != source_after.st_dev
                        or _ownership(destination_initial) == _ownership(source_after)
                    ):
                        raise ImageViewError("clone identity or isolation check failed")
                    os.fchmod(destination_fd, 0o444)
                    if _hash_open_file(destination_fd, expected_size) != expected_sha:
                        raise ImageViewError("clone content hash mismatch")
                    os.fsync(destination_fd)
                    destination_final = os.fstat(destination_fd)
                    destination_path_final = os.stat(
                        destination_parts[-1],
                        dir_fd=destination_parent_fd,
                        follow_symlinks=False,
                    )
                    if (
                        destination_final.st_nlink != 1
                        or stat.S_IMODE(destination_final.st_mode) & 0o222
                        or _identity(destination_final) != _identity(destination_path_final)
                        or _ownership(destination_final) == _ownership(source_after)
                    ):
                        raise ImageViewError("sealed clone postcondition failed")
                    ownership.files[staging_relative] = _ownership(destination_final)
                    built_records.append(
                        {
                            "bytes": expected_size,
                            "destination": _identity_value(destination_final),
                            "path": relative,
                            "sha256": expected_sha,
                            "source_after": _identity_value(source_after),
                            "source_before": _identity_value(source_before),
                        }
                    )
                finally:
                    if destination_fd is not None:
                        os.close(destination_fd)
                    if destination_parent_fd is not None:
                        os.close(destination_parent_fd)
                    os.close(source_fd)
                    os.close(source_parent_fd)
        finally:
            os.close(image_view_fd)

        if len(built_records) != len(loaded.records):
            raise ImageViewError("incomplete clone record set")
        source_layout_after = _scan_source_layout(train_fd, loaded.records, authority.stems)
        if source_layout_after != source_layout_before or _identity(os.fstat(train_fd)) != train_identity_before:
            raise ImageViewError("source layout changed during build")
        image_view_fd = _open_relative_directory(staging_fd, "IMAGE_VIEW")
        try:
            actual_files, actual_directories = _walk_tree(image_view_fd)
            if {str(item["path"]) for item in actual_files} != {str(record["path"]) for record in loaded.records}:
                raise ImageViewError("destination member set drift")
            if {str(item["path"]) for item in actual_directories} != _expected_view_directories(loaded.records):
                raise ImageViewError("destination directory set drift")
        finally:
            os.close(image_view_fd)
        _set_directories_read_only(staging_fd, ownership)
        image_view_fd = _open_relative_directory(staging_fd, "IMAGE_VIEW")
        try:
            image_view_info = os.fstat(image_view_fd)
            destination_snapshot = _assert_destination_snapshot(image_view_fd, loaded.records, built_records)
        finally:
            os.close(image_view_fd)
        git_after = _capture_git_state(root, authority, checkout)
        bindings_after = _source_bindings(root_fd, authority)
        if git_after != git_before or bindings_after != bindings_before:
            raise ImageViewError("checkout changed during build")
        run_relative = PurePosixPath(authority.output_parent_relative, final_name).as_posix()
        receipt = _build_receipt(
            authority=authority,
            loaded=loaded,
            git=git_before,
            bindings=bindings_before,
            run_relative=run_relative,
            source_info=train_info,
            image_view_info=image_view_info,
            records=built_records,
            source_layout_digest=source_layout_digest,
            filesystem=source_fs,
            clone_method=clone_method,
            publication=publication,
            created_utc=now(),
        )
        receipt_raw = canonical_json_bytes(receipt)
        try:
            receipt_info = _write_new_regular(staging_fd, "IMAGE_VIEW_RECEIPT.json", receipt_raw)
        except BaseException:
            partial_receipt = _name_info(staging_fd, "IMAGE_VIEW_RECEIPT.json")
            if partial_receipt is not None and not stat.S_ISDIR(partial_receipt.st_mode):
                ownership.files["IMAGE_VIEW_RECEIPT.json"] = _ownership(partial_receipt)
            raise
        ownership.files["IMAGE_VIEW_RECEIPT.json"] = _ownership(receipt_info)
        os.fchmod(staging_fd, 0o555)
        os.fsync(staging_fd)
        if set(os.listdir(staging_fd)) != {"IMAGE_VIEW", "IMAGE_VIEW_RECEIPT.json"}:
            raise ImageViewError("sealed staging membership drift")
        sealed_receipt_raw, sealed_receipt_info = _read_named_regular(
            staging_fd,
            "IMAGE_VIEW_RECEIPT.json",
            max_bytes=MAX_JSON_BYTES,
        )
        if (
            sealed_receipt_raw != receipt_raw
            or _ownership(sealed_receipt_info) != ownership.files["IMAGE_VIEW_RECEIPT.json"]
            or stat.S_IMODE(sealed_receipt_info.st_mode) & 0o222
        ):
            raise ImageViewError("sealed receipt postcondition drift")
        image_view_fd = _open_relative_directory(staging_fd, "IMAGE_VIEW")
        try:
            if _assert_destination_snapshot(image_view_fd, loaded.records, built_records) != destination_snapshot:
                raise ImageViewError("sealed destination snapshot drift")
        finally:
            os.close(image_view_fd)
        if (
            _scan_source_layout(train_fd, loaded.records, authority.stems) != source_layout_before
            or _identity(os.fstat(train_fd)) != train_identity_before
        ):
            raise ImageViewError("source changed before publication")
        loaded_final = _load_authority(root_fd, authority)
        if (
            loaded_final.ready_raw != loaded.ready_raw
            or loaded_final.inventory_raw != loaded.inventory_raw
            or loaded_final.import_raw != loaded.import_raw
            or loaded_final.records != loaded.records
            or loaded_final.source_identity != loaded.source_identity
        ):
            raise ImageViewError("pinned authority changed before publication")
        success_result = {
            "files": len(built_records),
            "image_view": f"{run_relative}/IMAGE_VIEW",
            "receipt": f"{run_relative}/IMAGE_VIEW_RECEIPT.json",
            "receipt_sha256": _sha256(receipt_raw),
            "status": "PASS",
            "stored_bytes": authority.stored_bytes,
        }
        if _name_info(parent_fd, final_name) is not None:
            raise FileExistsError(final_name)
        if _source_bindings(root_fd, authority) != bindings_before:
            raise ImageViewError("checkout changed before publication")
        if _capture_git_state(root, authority, checkout) != git_before:
            raise ImageViewError("checkout changed before publication")
        try:
            used = _rename_noreplace(parent_fd, staging_name, final_name)
            if used != publication:
                raise ImageViewError("publication primitive changed")
            published = True
            final_info = _name_info(parent_fd, final_name)
            if (
                final_info is None
                or _ownership(final_info) != ownership.identity
                or _name_info(parent_fd, staging_name) is not None
                or set(os.listdir(staging_fd)) != {"IMAGE_VIEW", "IMAGE_VIEW_RECEIPT.json"}
            ):
                raise ImageViewError("published directory postcondition drift")
            final_receipt_raw, final_receipt_info = _read_named_regular(
                staging_fd,
                "IMAGE_VIEW_RECEIPT.json",
                max_bytes=MAX_JSON_BYTES,
            )
            if (
                final_receipt_raw != receipt_raw
                or _ownership(final_receipt_info) != ownership.files["IMAGE_VIEW_RECEIPT.json"]
            ):
                raise ImageViewError("published receipt postcondition drift")
            image_view_fd = _open_relative_directory(staging_fd, "IMAGE_VIEW")
            try:
                if _assert_destination_snapshot(image_view_fd, loaded.records, built_records) != destination_snapshot:
                    raise ImageViewError("published destination snapshot drift")
            finally:
                os.close(image_view_fd)
            os.fsync(parent_fd)
            return success_result
        except BaseException as error:
            recovery_attempted = True
            _recover_publication(parent_fd, staging_fd, ownership, final_name, error)
            raise
    except BaseException as error:
        if (
            ownership is not None
            and staging_fd is not None
            and parent_fd is not None
            and not published
            and not recovery_attempted
        ):
            recovery_attempted = True
            try:
                _recover_publication(parent_fd, staging_fd, ownership, final_name, error)
            except PublicationAmbiguityError:
                raise
        raise
    finally:
        for fd in (staging_fd, parent_fd, train_fd):
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)
        checkout.close()


def _validate_receipt_records(
    receipt: dict[str, object],
    loaded: LoadedAuthority,
) -> list[dict[str, object]]:
    values = receipt["records"]
    if type(values) is not list or len(values) != len(loaded.records):
        raise ImageViewError("receipt record count drift")
    result: list[dict[str, object]] = []
    for value, expected in zip(values, loaded.records, strict=True):
        record = _require_dict(
            value,
            {"bytes", "destination", "path", "sha256", "source_after", "source_before"},
            "receipt record",
        )
        if (
            record["path"] != expected["path"]
            or record["bytes"] != expected["bytes"]
            or record["sha256"] != expected["sha256"]
        ):
            raise ImageViewError("receipt record disagrees with READY inventory")
        source_before = _identity_from_value(record["source_before"])
        source_after = _identity_from_value(record["source_after"])
        destination = _identity_from_value(record["destination"])
        if source_before != source_after:
            raise ImageViewError("receipt records an unstable source")
        if source_after[:2] == destination[:2] or source_after[0] != destination[0]:
            raise ImageViewError("receipt records a hardlink or cross-filesystem copy")
        if source_after[3] != 1 or destination[3] != 1 or stat.S_IMODE(destination[2]) & 0o222:
            raise ImageViewError("receipt records unsafe links or modes")
        result.append(record)
    evidence = _require_dict(
        receipt["evidence"],
        {
            "bytes",
            "destination_records_sha256",
            "files",
            "source_after_records_sha256",
            "source_before_records_sha256",
            "source_layout_sha256",
        },
        "receipt evidence",
    )
    if (
        evidence["bytes"] != sum(int(record["bytes"]) for record in result)
        or evidence["files"] != len(result)
        or evidence["source_before_records_sha256"] != _record_digest(result, "source_before")
        or evidence["source_after_records_sha256"] != _record_digest(result, "source_after")
        or evidence["destination_records_sha256"] != _record_digest(result, "destination")
    ):
        raise ImageViewError("receipt evidence digest drift")
    _require_sha(evidence["source_layout_sha256"], "source layout hash")
    return result


def verify_image_view(run_dir: Path) -> dict[str, object]:
    """Independently re-open and fully hash a published production image view."""
    authority = PRODUCTION_AUTHORITY
    root = CANONICAL_REPO_ROOT
    _run_absolute, final_name = _constrain_run_dir(root, run_dir, authority)
    checkout = _validate_checkout(root)
    root_fd = checkout.root_fd
    parent_fd: int | None = None
    train_fd: int | None = None
    run_fd: int | None = None
    view_fd: int | None = None
    try:
        git = _capture_git_state(root, authority, checkout)
        loaded = _load_authority(root_fd, authority)
        bindings = _source_bindings(root_fd, authority)
        parent_fd = _open_relative_directory(root_fd, authority.output_parent_relative)
        run_fd = _open_relative_directory(parent_fd, (final_name,))
        run_identity_before = _identity(os.fstat(run_fd))
        top_names = os.listdir(run_fd)
        if set(top_names) != {"IMAGE_VIEW", "IMAGE_VIEW_RECEIPT.json"} or len(top_names) != 2:
            raise ImageViewError("published run-directory membership drift")
        run_info = os.fstat(run_fd)
        if stat.S_IMODE(run_info.st_mode) & 0o222:
            raise ImageViewError("published run directory is writable")
        receipt_raw, receipt_info = _read_named_regular(run_fd, "IMAGE_VIEW_RECEIPT.json", max_bytes=MAX_JSON_BYTES)
        if stat.S_IMODE(receipt_info.st_mode) & 0o222:
            raise ImageViewError("receipt is writable")
        run_relative = PurePosixPath(authority.output_parent_relative, final_name).as_posix()
        receipt = _validate_receipt(
            _strict_json_bytes(receipt_raw),
            authority=authority,
            loaded=loaded,
            git=git,
            bindings=bindings,
            run_relative=run_relative,
        )
        records = _validate_receipt_records(receipt, loaded)
        train_fd = _open_relative_directory(root_fd, authority.source_relative)
        train_info = os.fstat(train_fd)
        train_identity_before = _identity(train_info)
        if _ownership(train_info) != loaded.source_identity:
            raise ImageViewError("source train identity disagrees with READY")
        source_receipt = _require_dict(receipt["source"], {"identity", "path"}, "receipt source")
        if source_receipt != {
            "identity": {"device": train_info.st_dev, "inode": train_info.st_ino},
            "path": authority.source_relative,
        }:
            raise ImageViewError("receipt source identity drift")
        source_fs = _filesystem_type(root / authority.source_relative, train_fd)
        output_fs = _filesystem_type(root / authority.output_parent_relative, parent_fd)
        if source_fs != "apfs" or output_fs != "apfs" or train_info.st_dev != os.fstat(parent_fd).st_dev:
            raise ImageViewError("source and output are not on one APFS filesystem")
        source_layout = _scan_source_layout(train_fd, loaded.records, authority.stems)
        evidence = receipt["evidence"]
        assert isinstance(evidence, dict)
        if _sha256(source_layout) != evidence["source_layout_sha256"]:
            raise ImageViewError("source layout drift after publication")
        view_fd = _open_relative_directory(run_fd, "IMAGE_VIEW")
        view_info = os.fstat(view_fd)
        view_identity_before = _identity(view_info)
        image_view = _require_dict(receipt["image_view"], {"identity", "path", "roots"}, "receipt image view")
        if image_view != {
            "identity": {"device": view_info.st_dev, "inode": view_info.st_ino},
            "path": "IMAGE_VIEW",
            "roots": list(authority.stems),
        }:
            raise ImageViewError("image-view identity or root order drift")
        destination_layout = _assert_destination_snapshot(view_fd, loaded.records, records)

        observed: list[dict[str, object]] = []
        for receipt_record in records:
            relative = str(receipt_record["path"])
            expected_size = int(receipt_record["bytes"])
            expected_sha = str(receipt_record["sha256"])
            source_fd, source_parent_fd = _open_relative_regular(train_fd, relative)
            destination_fd: int | None = None
            destination_parent_fd: int | None = None
            try:
                destination_fd, destination_parent_fd = _open_relative_regular(view_fd, relative)
                source_info = os.fstat(source_fd)
                destination_info = os.fstat(destination_fd)
                if _hash_open_file(source_fd, expected_size) != expected_sha:
                    raise ImageViewError("source content drift during verification")
                if _hash_open_file(destination_fd, expected_size) != expected_sha:
                    raise ImageViewError("destination content drift during verification")
                source_path_info = os.stat(
                    PurePosixPath(relative).name,
                    dir_fd=source_parent_fd,
                    follow_symlinks=False,
                )
                destination_path_info = os.stat(
                    PurePosixPath(relative).name,
                    dir_fd=destination_parent_fd,
                    follow_symlinks=False,
                )
                if _identity(source_info) != _identity(source_path_info):
                    raise ImageViewError("source identity drift during verification")
                if _identity(destination_info) != _identity(destination_path_info):
                    raise ImageViewError("destination identity drift during verification")
                if _identity(source_info) != _identity_from_value(receipt_record["source_after"]):
                    raise ImageViewError("source identity disagrees with receipt")
                if _identity(destination_info) != _identity_from_value(receipt_record["destination"]):
                    raise ImageViewError("destination identity disagrees with receipt")
                if (
                    _ownership(source_info) == _ownership(destination_info)
                    or source_info.st_dev != destination_info.st_dev
                    or destination_info.st_nlink != 1
                    or stat.S_IMODE(destination_info.st_mode) & 0o222
                ):
                    raise ImageViewError("destination isolation drift")
                observed.append(receipt_record)
            finally:
                if destination_fd is not None:
                    os.close(destination_fd)
                if destination_parent_fd is not None:
                    os.close(destination_parent_fd)
                os.close(source_fd)
                os.close(source_parent_fd)
        if _record_digest(observed, "destination") != evidence["destination_records_sha256"]:
            raise ImageViewError("verified destination record digest drift")
        if (
            _scan_source_layout(train_fd, loaded.records, authority.stems) != source_layout
            or _identity(os.fstat(train_fd)) != train_identity_before
        ):
            raise ImageViewError("source layout changed during verification")
        if (
            _assert_destination_snapshot(view_fd, loaded.records, records) != destination_layout
            or _identity(os.fstat(view_fd)) != view_identity_before
        ):
            raise ImageViewError("destination layout changed during verification")
        if set(os.listdir(run_fd)) != {"IMAGE_VIEW", "IMAGE_VIEW_RECEIPT.json"}:
            raise ImageViewError("run-directory membership changed during verification")
        receipt_after, receipt_after_info = _read_named_regular(
            run_fd,
            "IMAGE_VIEW_RECEIPT.json",
            max_bytes=MAX_JSON_BYTES,
        )
        if receipt_after != receipt_raw or _identity(receipt_after_info) != _identity(receipt_info):
            raise ImageViewError("receipt changed during verification")
        loaded_after = _load_authority(root_fd, authority)
        if (
            loaded_after.ready_raw != loaded.ready_raw
            or loaded_after.inventory_raw != loaded.inventory_raw
            or loaded_after.import_raw != loaded.import_raw
            or loaded_after.records != loaded.records
            or loaded_after.source_identity != loaded.source_identity
        ):
            raise ImageViewError("pinned authority changed during verification")
        if _source_bindings(root_fd, authority) != bindings:
            raise ImageViewError("checkout changed during verification")
        final_info = _name_info(parent_fd, final_name)
        if (
            final_info is None
            or _identity(final_info) != run_identity_before
            or _identity(os.fstat(run_fd)) != run_identity_before
        ):
            raise ImageViewError("run-directory identity changed during verification")
        result = {
            "files": len(records),
            "image_view": f"{run_relative}/IMAGE_VIEW",
            "receipt_sha256": _sha256(receipt_raw),
            "status": "PASS",
            "stored_bytes": authority.stored_bytes,
        }
        if _capture_git_state(root, authority, checkout) != git:
            raise ImageViewError("checkout changed during verification")
        return result
    finally:
        for fd in (view_fd, run_fd, train_fd, parent_fd):
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)
        checkout.close()


__all__ = [
    "Authority",
    "CANONICAL_REPO_ROOT",
    "EVAL36_STEMS",
    "ImageViewError",
    "PRODUCTION_AUTHORITY",
    "PublicationAmbiguityError",
    "build_image_view",
    "canonical_json_bytes",
    "verify_image_view",
]
