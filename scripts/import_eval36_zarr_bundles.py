#!/usr/bin/env python3
"""Strictly verify and locally import deterministic eval-36 USTAR bundles.

No archive metadata is applied. The production CLI has fixed manifest pins;
tests may inject explicit pins through :func:`import_bundles` only.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import stat
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

try:  # Supports both ``python scripts/...`` and importing as ``scripts...``.
    from scripts.pack_eval36_zarr_bundles import (
        BUNDLE_MANIFEST_NAME,
        PRODUCTION_ARCHIVE_BYTES,
        PRODUCTION_EMBEDDED_MANIFEST_BYTES,
        PRODUCTION_PINS,
        SCHEMA_VERSION,
        BundleError,
        ManifestPins,
        _header,
        _open_directory_path,
        _remove_owned_or_quarantine,
        canonical_json,
        load_expected_files,
        rename_noreplace,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the production CLI form
    from pack_eval36_zarr_bundles import (  # type: ignore[no-redef]
        BUNDLE_MANIFEST_NAME,
        PRODUCTION_ARCHIVE_BYTES,
        PRODUCTION_EMBEDDED_MANIFEST_BYTES,
        PRODUCTION_PINS,
        SCHEMA_VERSION,
        BundleError,
        ManifestPins,
        _header,
        _open_directory_path,
        _remove_owned_or_quarantine,
        canonical_json,
        load_expected_files,
        rename_noreplace,
    )

_CHUNK = 1024 * 1024
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPOSITORY_ROOT / "data"
MANIFEST_PATH = DATA_ROOT / "manifest.csv"


class ImportHold(BundleError):
    """Safe local state requires operator action rather than replacement."""


class PublishedFileError(ImportHold):
    """A verified final file was published but its directory fsync failed."""

    def __init__(self, logical_path: str, error: OSError) -> None:
        super().__init__(f"post-publication fsync failed for {logical_path}: {error}")
        self.logical_path = logical_path


@dataclass(frozen=True)
class Member:
    name: str
    size: int
    offset: int


@dataclass
class CheckedArchive:
    path: Path
    fd: int
    parent_fd: int
    name: str
    identity: tuple[int, int, int, int, int, int, int]
    root: str
    sha256: str
    members: dict[str, Member]
    files: tuple[dict[str, object], ...]


def _strict_json(raw: bytes) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise BundleError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def bad_constant(value: str) -> object:
        raise BundleError(f"non-finite JSON value: {value}")

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=bad_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BundleError(f"invalid strict JSON: {error}") from error


def _archive_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _safe_path(name: str) -> bool:
    if not name or "\x00" in name or "\\" in name or name.startswith("/"):
        return False
    value = PurePosixPath(name)
    return str(value) == name and all(part not in {"", ".", ".."} for part in value.parts)


def _real_ancestors(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:-1]:
        current /= part
        try:
            info = current.lstat()
        except OSError as error:
            raise BundleError(f"archive ancestor unavailable: {current}: {error}") from error
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise BundleError(f"archive ancestor is not a real directory: {current}")


def _decode_field(field: bytes, label: str) -> str:
    head, separator, tail = field.partition(b"\0")
    if separator and tail.strip(b"\0"):
        raise BundleError(f"non-canonical USTAR {label} padding")
    try:
        return head.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BundleError(f"non-UTF-8 USTAR {label}") from error


def _parse_octal(field: bytes, label: str) -> int:
    value = field.rstrip(b"\0 ").lstrip(b" ")
    if not value or any(byte not in b"01234567" for byte in value):
        raise BundleError(f"invalid USTAR {label}")
    return int(value, 8)


def _pread_exact(fd: int, count: int, offset: int) -> bytes:
    chunks: list[bytes] = []
    remaining = count
    while remaining:
        chunk = os.pread(fd, remaining, offset)
        if not chunk:
            raise BundleError("truncated archive")
        chunks.append(chunk)
        remaining -= len(chunk)
        offset += len(chunk)
    return b"".join(chunks)


def _parse_ustar(fd: int, archive_size: int, *, max_members: int = 4096) -> dict[str, Member]:
    if archive_size < 10_240 or archive_size % 10_240:
        raise BundleError("archive length is not complete canonical USTAR records")
    members: dict[str, Member] = {}
    offset = 0
    zero_blocks = 0
    while offset + 512 <= archive_size:
        header = _pread_exact(fd, 512, offset)
        if header == b"\0" * 512:
            zero_blocks += 1
            offset += 512
            if zero_blocks == 2:
                canonical_size = ((offset + 10_239) // 10_240) * 10_240
                if archive_size != canonical_size:
                    raise BundleError("archive has non-canonical USTAR record padding")
                remaining = archive_size - offset
                while remaining:
                    chunk = os.pread(fd, min(_CHUNK, remaining), offset)
                    if not chunk or chunk.strip(b"\0"):
                        raise BundleError("nonzero or truncated USTAR record padding")
                    remaining -= len(chunk)
                    offset += len(chunk)
                return members
            continue
        if zero_blocks:
            raise BundleError("single zero block inside archive")
        if header[257:263] != b"ustar\0" or header[263:265] != b"00":
            raise BundleError("only canonical USTAR is accepted")
        if header[156:157] != b"0":
            raise BundleError("non-regular/PAX/GNU/sparse archive member")
        checksum_field = header[148:156]
        stored = _parse_octal(checksum_field, "checksum")
        checksum_header = bytearray(header)
        checksum_header[148:156] = b"        "
        if sum(checksum_header) != stored:
            raise BundleError("USTAR header checksum mismatch")
        name = _decode_field(header[0:100], "name")
        prefix = _decode_field(header[345:500], "prefix")
        logical = f"{prefix}/{name}" if prefix else name
        if not _safe_path(logical) or logical in members:
            raise BundleError(f"unsafe or duplicate archive member: {logical!r}")
        if len(members) >= max_members:
            raise BundleError("archive member count exceeds limit")
        size = _parse_octal(header[124:136], "size")
        if header != _header(logical, size):
            raise BundleError("non-canonical USTAR header")
        if _parse_octal(header[100:108], "mode") != 0o444:
            raise BundleError("non-canonical member mode")
        for field, label in ((header[108:116], "uid"), (header[116:124], "gid"), (header[136:148], "mtime")):
            if _parse_octal(field, label) != 0:
                raise BundleError(f"non-canonical member {label}")
        if _decode_field(header[265:297], "owner") or _decode_field(header[297:329], "group"):
            raise BundleError("non-canonical owner/group")
        data_offset = offset + 512
        next_offset = data_offset + size + (-size % 512)
        if next_offset > archive_size:
            raise BundleError("truncated archive member")
        padding_size = -size % 512
        if padding_size and _pread_exact(fd, padding_size, data_offset + size) != b"\0" * padding_size:
            raise BundleError("nonzero USTAR member padding")
        members[logical] = Member(logical, size, data_offset)
        offset = next_offset
    raise BundleError("archive has no two-block USTAR terminator")


def _hash_region(fd: int, offset: int, size: int, target: BinaryIO | None = None) -> str:
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        chunk = os.pread(fd, min(_CHUNK, remaining), offset)
        if not chunk:
            raise BundleError("short archive payload read")
        if target is not None:
            target.write(chunk)
        digest.update(chunk)
        remaining -= len(chunk)
        offset += len(chunk)
    return digest.hexdigest()


def _check_manifest_shape(
    value: object, root: str, pins: ManifestPins, expected: list[tuple[str, int]]
) -> tuple[dict[str, object], ...]:
    if not isinstance(value, dict) or set(value) != {
        "competition",
        "files",
        "manifest_csv_sha256",
        "root",
        "schema_version",
    }:
        raise BundleError("embedded manifest schema mismatch")
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
        raise BundleError("embedded schema version mismatch")
    if value["competition"] != pins.competition or value["manifest_csv_sha256"] != pins.sha256 or value["root"] != root:
        raise BundleError("embedded manifest identity mismatch")
    files = value["files"]
    if not isinstance(files, list) or len(files) != len(expected):
        raise BundleError("embedded file count mismatch")
    checked: list[dict[str, object]] = []
    expected_pairs: list[tuple[str, int]] = []
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "size"}:
            raise BundleError("embedded file entry schema mismatch")
        path, size, digest = item["path"], item["size"], item["sha256"]
        if not isinstance(path, str) or not _safe_path(path):
            raise BundleError("invalid embedded path")
        if type(size) is not int or size < 0:
            raise BundleError("invalid embedded size")
        if not isinstance(digest, str) or not re_full_sha256(digest):
            raise BundleError("invalid embedded SHA-256")
        expected_pairs.append((path, size))
        checked.append(item)
    if expected_pairs != expected:
        raise BundleError("embedded paths/sizes differ from pinned CSV")
    return tuple(checked)


def re_full_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _path_matches_fd(path: Path, identity: tuple[int, int, int, int, int, int, int]) -> bool:
    try:
        return _archive_identity(path.lstat()) == identity
    except OSError:
        return False


def _archive_path_matches(archive: CheckedArchive) -> bool:
    try:
        by_parent = os.stat(archive.name, dir_fd=archive.parent_fd, follow_symlinks=False)
    except OSError:
        return False
    return _archive_identity(by_parent) == archive.identity and _path_matches_fd(archive.path, archive.identity)


def _open_checked_archive(
    path: Path, expected_maps: dict[str, list[tuple[str, int]]], pins: ManifestPins
) -> CheckedArchive:
    parent_fd = _open_directory_path(path.parent)
    name = path.name
    if not name or name in {".", ".."}:
        os.close(parent_fd)
        raise BundleError("invalid archive filename")
    try:
        path_info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as error:
        os.close(parent_fd)
        raise BundleError(f"cannot stat archive {path}: {error}") from error
    if not stat.S_ISREG(path_info.st_mode) or stat.S_ISLNK(path_info.st_mode) or path_info.st_nlink != 1:
        os.close(parent_fd)
        raise BundleError(f"archive is not a single-link regular file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        os.close(parent_fd)
        raise BundleError(f"cannot safely open archive {path}: {error}") from error
    try:
        info = os.fstat(fd)
        identity = _archive_identity(info)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or _archive_identity(path_info) != identity
            or not _path_matches_fd(path, identity)
        ):
            raise BundleError(f"archive is not a stable single-link regular file: {path}")
        if pins == PRODUCTION_PINS and info.st_size not in set(PRODUCTION_ARCHIVE_BYTES.values()):
            raise BundleError("production archive byte-count is not an allowed root size")
        if info.st_size > max(PRODUCTION_ARCHIVE_BYTES.values()):
            raise BundleError("archive exceeds byte limit")
        members = _parse_ustar(fd, info.st_size, max_members=pins.files_per_root + 1)
        manifest_member = members.get(BUNDLE_MANIFEST_NAME)
        if manifest_member is None:
            raise BundleError("missing unique embedded manifest")
        if manifest_member.size > 4 * 1024 * 1024:
            raise BundleError("embedded manifest is unreasonably large")
        if pins == PRODUCTION_PINS and manifest_member.size != PRODUCTION_EMBEDDED_MANIFEST_BYTES:
            raise BundleError("production embedded manifest size mismatch")
        raw_manifest = _pread_exact(fd, manifest_member.size, manifest_member.offset)
        parsed = _strict_json(raw_manifest)
        if canonical_json(parsed) != raw_manifest:
            raise BundleError("embedded manifest JSON is not canonical")
        if not isinstance(parsed, dict) or not isinstance(parsed.get("root"), str):
            raise BundleError("embedded root is missing or invalid")
        root = parsed["root"]
        if root not in expected_maps or path.name != f"{root}.tar":
            raise BundleError("archive filename/root selection mismatch")
        if pins == PRODUCTION_PINS and info.st_size != PRODUCTION_ARCHIVE_BYTES[root]:
            raise BundleError("production archive byte-count mismatch")
        files = _check_manifest_shape(parsed, root, pins, expected_maps[root])
        expected_names = {entry["path"] for entry in files} | {BUNDLE_MANIFEST_NAME}
        if set(members) != expected_names:
            raise BundleError("archive member set mismatch")
        expected_order = [str(entry["path"]) for entry in files] + [BUNDLE_MANIFEST_NAME]
        if list(members) != expected_order:
            raise BundleError("archive member order mismatch")
        archive_digest = hashlib.sha256()
        archive_offset = 0
        while archive_offset < info.st_size:
            chunk = os.pread(fd, min(_CHUNK, info.st_size - archive_offset), archive_offset)
            if not chunk:
                raise BundleError("short archive read")
            archive_digest.update(chunk)
            archive_offset += len(chunk)
        for entry in files:
            member = members[str(entry["path"])]
            if member.size != entry["size"] or _hash_region(fd, member.offset, member.size) != entry["sha256"]:
                raise BundleError(f"payload size/hash mismatch: {member.name}")
        provisional = CheckedArchive(
            path, fd, parent_fd, name, identity, root, archive_digest.hexdigest(), members, files
        )
        if _archive_identity(os.fstat(fd)) != identity or not _archive_path_matches(provisional):
            raise BundleError("archive changed during validation")
        return provisional
    except BaseException:
        os.close(fd)
        os.close(parent_fd)
        raise


def _check_data_root(data_root: Path) -> int:
    try:
        fd = _open_directory_path(data_root)
    except OSError as error:
        raise ImportHold(f"data root is unavailable or unsafe: {error}") from error
    return fd


def _inspect_destination(data_fd: int, data_root: Path, entry: dict[str, object]) -> str:
    relative = PurePosixPath(str(entry["path"]))
    path = data_root.joinpath(*relative.parts)
    current_fd = os.dup(data_fd)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        for part in relative.parts[:-1]:
            try:
                next_fd = os.open(part, flags, dir_fd=current_fd)
            except FileNotFoundError:
                return "missing"
            except OSError as error:
                raise ImportHold(f"unsafe destination ancestor for {path}: {error}") from error
            os.close(current_fd)
            current_fd = next_fd
        try:
            info = os.stat(relative.parts[-1], dir_fd=current_fd, follow_symlinks=False)
        except FileNotFoundError:
            return "missing"
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_nlink != 1:
            raise ImportHold(f"destination is not a single-link regular file: {path}")
        if (
            info.st_size != entry["size"]
            or _hash_file_stable(current_fd, relative.parts[-1], path, info) != entry["sha256"]
        ):
            raise ImportHold(f"existing destination differs; refusing replacement: {path}")
        os.fsync(current_fd)
        return "skipped"
    except ImportHold:
        raise
    except OSError as error:
        raise ImportHold(f"destination inspection or durability check failed for {path}: {error}") from error
    finally:
        os.close(current_fd)


def _hash_file_stable(parent_fd: int, name: str, path: Path, before: os.stat_result) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(name, flags, dir_fd=parent_fd)
    try:
        opened = os.fstat(fd)
        if _archive_identity(opened) != _archive_identity(before):
            raise ImportHold(f"destination identity changed: {path}")
        digest = hashlib.sha256()
        while chunk := os.read(fd, _CHUNK):
            digest.update(chunk)
        path_info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if _archive_identity(os.fstat(fd)) != _archive_identity(before) or _archive_identity(
            path_info
        ) != _archive_identity(before):
            raise ImportHold(f"destination changed while hashing: {path}")
        return digest.hexdigest()
    finally:
        os.close(fd)


def _data_root_matches_fd(data_root: Path, data_fd: int) -> bool:
    try:
        path_info = data_root.lstat()
        fd_info = os.fstat(data_fd)
    except OSError:
        return False
    return (path_info.st_dev, path_info.st_ino, path_info.st_mode) == (
        fd_info.st_dev,
        fd_info.st_ino,
        fd_info.st_mode,
    )


@contextlib.contextmanager
def _mutation_lock(data_fd: int, data_root: Path) -> Iterator[None]:
    lock = data_root / ".download_data.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    if not _data_root_matches_fd(data_root, data_fd):
        raise ImportHold("data root identity changed before lock")
    try:
        fd = os.open(".download_data.lock", flags, 0o600, dir_fd=data_fd)
    except OSError as error:
        raise ImportHold(f"cannot safely open downloader lock file: {lock}") from error
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or _archive_identity(os.stat(".download_data.lock", dir_fd=data_fd, follow_symlinks=False))
            != _archive_identity(info)
        ):
            raise ImportHold("unsafe downloader lock file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ImportHold(f"another download/import owns lock: {lock}") from error
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _open_parent(data_fd: int, parts: tuple[str, ...]) -> int:
    current = os.dup(data_fd)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        for part in parts:
            try:
                next_fd = os.open(part, flags, dir_fd=current)
            except FileNotFoundError:
                os.mkdir(part, 0o755, dir_fd=current)
                next_fd = os.open(part, flags, dir_fd=current)
            os.close(current)
            current = next_fd
        return current
    except OSError as error:
        os.close(current)
        raise ImportHold("destination ancestor is unsafe or changed during creation") from error
    except BaseException:
        os.close(current)
        raise


def _parent_matches(data_fd: int, parts: tuple[str, ...], expected_fd: int) -> bool:
    current = os.dup(data_fd)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        for part in parts:
            next_fd = os.open(part, flags, dir_fd=current)
            os.close(current)
            current = next_fd
        actual = os.fstat(current)
        expected = os.fstat(expected_fd)
        return (actual.st_dev, actual.st_ino, actual.st_mode) == (expected.st_dev, expected.st_ino, expected.st_mode)
    except OSError:
        return False
    finally:
        os.close(current)


def _copy_payload(archive: CheckedArchive, member: Member, target: BinaryIO) -> str:
    return _hash_region(archive.fd, member.offset, member.size, target)


def _verify_temporary(parent_fd: int, name: str, expected_size: int, expected_sha256: str) -> None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(name, flags, dir_fd=parent_fd)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != expected_size:
            raise BundleError(f"temporary payload type/size mismatch: {name}")
        digest = hashlib.sha256()
        while chunk := os.read(fd, _CHUNK):
            digest.update(chunk)
        path_info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if _archive_identity(before) != _archive_identity(os.fstat(fd)) or _archive_identity(
            before
        ) != _archive_identity(path_info):
            raise BundleError(f"temporary payload identity changed: {name}")
        if digest.hexdigest() != expected_sha256:
            raise BundleError(f"temporary payload readback hash mismatch: {name}")
    finally:
        os.close(fd)


def _verify_published_payload(
    parent_fd: int, name: str, entry: dict[str, object], expected_inode: tuple[int, int]
) -> None:
    info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or (info.st_dev, info.st_ino) != expected_inode
        or info.st_size != entry["size"]
        or _hash_file_stable(parent_fd, name, Path(str(entry["path"])), info) != entry["sha256"]
    ):
        raise ImportHold(f"published payload content/identity mismatch: {entry['path']}")


def _install_entry(data_fd: int, archive: CheckedArchive, entry: dict[str, object]) -> str:
    relative = PurePosixPath(str(entry["path"]))
    parent_fd = _open_parent(data_fd, relative.parts[:-1])
    leaf = relative.parts[-1]
    temp_name: str | None = None
    published_inode: tuple[int, int] | None = None
    try:
        try:
            existing = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            return "race-existing"
        for attempt in range(100):
            candidate = f".{leaf}.eval36-{os.getpid()}-{attempt}.tmp"
            try:
                temp_fd = os.open(
                    candidate,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=parent_fd,
                )
                temp_name = candidate
                break
            except FileExistsError:
                continue
        else:
            raise ImportHold(f"cannot reserve destination temporary for {relative}")
        with os.fdopen(temp_fd, "wb", closefd=True) as target:
            digest = _copy_payload(archive, archive.members[str(entry["path"])], target)
            target.flush()
            os.fsync(target.fileno())
        temp_info = os.stat(temp_name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(temp_info.st_mode)
            or temp_info.st_nlink != 1
            or temp_info.st_size != entry["size"]
            or digest != entry["sha256"]
        ):
            raise BundleError(f"temporary payload verification failed: {relative}")
        _verify_temporary(parent_fd, temp_name, int(entry["size"]), str(entry["sha256"]))
        if not _parent_matches(data_fd, relative.parts[:-1], parent_fd):
            raise ImportHold(f"destination parent changed before publication: {relative}")
        try:
            rename_noreplace(temp_name, leaf, source_dir_fd=parent_fd, destination_dir_fd=parent_fd)
        except FileExistsError:
            return "race-existing"
        temp_name = None
        published = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        published_inode = (published.st_dev, published.st_ino)
        _verify_published_payload(parent_fd, leaf, entry, published_inode)
        try:
            os.fsync(parent_fd)
        except OSError as error:
            raise PublishedFileError(str(relative), error) from error
        if not _parent_matches(data_fd, relative.parts[:-1], parent_fd):
            raise ImportHold(f"destination parent changed during publication: {relative}")
        _verify_published_payload(parent_fd, leaf, entry, published_inode)
        return "installed"
    except PublishedFileError:
        raise
    except BaseException:
        if published_inode is not None:
            try:
                _remove_owned_or_quarantine(parent_fd, leaf, published_inode)
            except Exception as rollback_error:
                raise ImportHold("destination publication failed and rollback was incomplete") from rollback_error
        raise
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        os.close(parent_fd)


def _write_receipt(receipt_dir: Path, value: dict[str, object]) -> Path:
    _validate_receipt_dir(receipt_dir)
    raw = canonical_json(value)
    digest = hashlib.sha256(raw).hexdigest()
    final_name = f"eval36-import-{digest}.json"
    final = receipt_dir / final_name
    directory_fd = _open_directory_path(receipt_dir)
    temp_name: str | None = None
    published_inode: tuple[int, int] | None = None
    try:
        directory_info = os.fstat(directory_fd)
        if not stat.S_ISDIR(directory_info.st_mode) or _archive_identity(receipt_dir.lstat()) != _archive_identity(
            directory_info
        ):
            raise ImportHold("receipt directory identity changed")
        try:
            existing = os.stat(final_name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1:
                raise ImportHold(f"unsafe existing receipt: {final}")
            existing_fd = os.open(final_name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
            try:
                existing_raw = b""
                while chunk := os.read(existing_fd, _CHUNK):
                    existing_raw += chunk
                    if len(existing_raw) > len(raw):
                        break
                if _archive_identity(os.fstat(existing_fd)) != _archive_identity(existing):
                    raise ImportHold(f"existing receipt changed: {final}")
                path_info = os.stat(final_name, dir_fd=directory_fd, follow_symlinks=False)
                if _archive_identity(path_info) != _archive_identity(existing):
                    raise ImportHold(f"existing receipt path changed: {final}")
            finally:
                os.close(existing_fd)
            if existing_raw == raw:
                if not _directory_path_matches(receipt_dir, directory_info):
                    raise ImportHold("receipt directory changed during reuse")
                try:
                    os.fsync(directory_fd)
                except OSError as error:
                    raise ImportHold("existing receipt durability is ambiguous") from error
                return final
            raise ImportHold(f"receipt collision: {final}")
        for attempt in range(100):
            candidate = f".eval36-receipt-{os.getpid()}-{attempt}.tmp"
            try:
                fd = os.open(
                    candidate,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=directory_fd,
                )
                temp_name = candidate
                break
            except FileExistsError:
                continue
        else:
            raise ImportHold("cannot reserve receipt temporary")
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_info = os.stat(temp_name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(temporary_info.st_mode)
            or temporary_info.st_nlink != 1
            or temporary_info.st_size != len(raw)
        ):
            raise ImportHold("receipt temporary is not a stable single-link regular file")
        if not _directory_path_matches(receipt_dir, directory_info):
            raise ImportHold("receipt directory changed before publication")
        try:
            rename_noreplace(temp_name, final_name, source_dir_fd=directory_fd, destination_dir_fd=directory_fd)
        except FileExistsError as error:
            raise ImportHold(f"receipt publication race: {final}") from error
        final_info = os.stat(final_name, dir_fd=directory_fd, follow_symlinks=False)
        published_inode = (final_info.st_dev, final_info.st_ino)
        temp_name = None
        _verify_receipt_final(directory_fd, final_name, raw, published_inode)
        try:
            os.fsync(directory_fd)
        except OSError as error:
            raise ImportHold("receipt publication durability is ambiguous") from error
        _verify_receipt_final(directory_fd, final_name, raw, published_inode)
        if not _directory_path_matches(receipt_dir, directory_info):
            raise ImportHold("receipt directory changed during publication")
        return final
    except BaseException:
        if published_inode is not None:
            try:
                _remove_owned_or_quarantine(directory_fd, final_name, published_inode)
            except Exception as rollback_error:
                raise ImportHold("receipt publication failed and rollback was incomplete") from rollback_error
        raise
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def _verify_receipt_final(directory_fd: int, name: str, expected: bytes, expected_inode: tuple[int, int]) -> None:
    fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or (before.st_dev, before.st_ino) != expected_inode
            or before.st_size != len(expected)
        ):
            raise ImportHold("published receipt identity mismatch")
        actual = b""
        while len(actual) <= len(expected):
            chunk = os.read(fd, min(_CHUNK, len(expected) + 1 - len(actual)))
            if not chunk:
                break
            actual += chunk
        path_info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            actual != expected
            or _archive_identity(os.fstat(fd)) != _archive_identity(before)
            or _archive_identity(path_info) != _archive_identity(before)
        ):
            raise ImportHold("published receipt content/identity mismatch")
    finally:
        os.close(fd)


def _directory_path_matches(path: Path, expected: os.stat_result) -> bool:
    try:
        actual = path.lstat()
    except OSError:
        return False
    return (actual.st_dev, actual.st_ino, actual.st_mode) == (expected.st_dev, expected.st_ino, expected.st_mode)


def _validate_receipt_dir(receipt_dir: Path) -> None:
    try:
        fd = _open_directory_path(receipt_dir)
    except OSError as error:
        raise ImportHold(f"receipt path is unsafe: {error}") from error
    os.close(fd)


def _archive_records(checked: list[CheckedArchive]) -> list[dict[str, object]]:
    return [
        {"bytes": item.identity[4], "name": item.path.name, "root": item.root, "sha256": item.sha256}
        for item in checked
    ]


def _receipt_document(
    checked: list[CheckedArchive], actions: dict[str, str], pins: ManifestPins, status: str, data_fd: int | None
) -> dict[str, object]:
    entries = {str(entry["path"]): entry for archive in checked for entry in archive.files}
    data_identity: dict[str, int] | None = None
    if data_fd is not None:
        info = os.fstat(data_fd)
        data_identity = {"device": info.st_dev, "inode": info.st_ino}
    return {
        "archives": _archive_records(checked),
        "data_root_identity": data_identity,
        "files": [
            {
                "action": actions[path],
                "path": path,
                "sha256": entries[path]["sha256"],
                "size": entries[path]["size"],
            }
            for path in sorted(actions, key=lambda value: value.encode())
        ],
        "manifest_csv_sha256": pins.sha256,
        "installed": sum(value == "installed" for value in actions.values()),
        "schema_version": SCHEMA_VERSION,
        "skipped": sum(value == "skipped" for value in actions.values()),
        "status": status,
        "validated": sum(len(archive.files) for archive in checked),
    }


def _import_bundles_impl(
    archive_paths: tuple[Path, ...],
    manifest_path: Path,
    data_root: Path,
    *,
    receipt_dir: Path | None = None,
    dry_run: bool = False,
    pins: ManifestPins = PRODUCTION_PINS,
) -> dict[str, object]:
    """Verify all archives first, then install missing files without replacement."""
    if not archive_paths:
        raise BundleError("no archives selected")
    data_fd = _check_data_root(data_root)
    if not _data_root_matches_fd(data_root, data_fd):
        os.close(data_fd)
        raise ImportHold("data root identity changed while opening")
    try:
        expected = load_expected_files(manifest_path, pins)
    except BaseException:
        os.close(data_fd)
        raise
    checked: list[CheckedArchive] = []
    try:
        roots: set[str] = set()
        for path in archive_paths:
            archive = _open_checked_archive(path, expected, pins)
            checked.append(archive)
            if archive.root in roots:
                raise BundleError(f"duplicate archive root: {archive.root}")
            roots.add(archive.root)
        initial: dict[str, str] = {}
        for archive in checked:
            for entry in archive.files:
                initial[str(entry["path"])] = _inspect_destination(data_fd, data_root, entry)
        if dry_run:
            return {
                "archives": _archive_records(checked),
                "installed": 0,
                "receipt": None,
                "skipped": sum(action == "skipped" for action in initial.values()),
                "status": "PASS",
                "validated": sum(action == "missing" for action in initial.values()),
            }
        if receipt_dir is None:
            raise BundleError("receipt_dir is required for installation")
        if receipt_dir.absolute() == data_root.absolute() or receipt_dir.absolute().is_relative_to(
            data_root.absolute()
        ):
            raise ImportHold("receipt directory must be outside data root")
        _validate_receipt_dir(receipt_dir)
        actions: dict[str, str] = {}
        with _mutation_lock(data_fd, data_root):
            try:
                for archive in checked:
                    if _archive_identity(os.fstat(archive.fd)) != archive.identity or not _archive_path_matches(
                        archive
                    ):
                        raise BundleError(f"archive changed before installation: {archive.path}")
                for archive in checked:
                    for entry in archive.files:
                        state = _inspect_destination(data_fd, data_root, entry)
                        if state == "skipped":
                            actions[str(entry["path"])] = "skipped"
                            continue
                        outcome = _install_entry(data_fd, archive, entry)
                        if outcome == "race-existing":
                            if _inspect_destination(data_fd, data_root, entry) != "skipped":
                                raise ImportHold(f"publication race produced a differing destination: {entry['path']}")
                            actions[str(entry["path"])] = "skipped"
                        else:
                            actions[str(entry["path"])] = "installed"
                for archive in checked:
                    if _archive_identity(os.fstat(archive.fd)) != archive.identity or not _archive_path_matches(
                        archive
                    ):
                        raise BundleError(f"archive changed during installation: {archive.path}")
                    for entry in archive.files:
                        if _inspect_destination(data_fd, data_root, entry) != "skipped":
                            raise BundleError(f"final destination verification failed: {entry['path']}")
                    if _archive_identity(os.fstat(archive.fd)) != archive.identity or not _archive_path_matches(
                        archive
                    ):
                        raise BundleError(f"archive changed during final destination verification: {archive.path}")
                if not _data_root_matches_fd(data_root, data_fd):
                    raise ImportHold("data root identity changed before receipt publication")
                receipt_value = _receipt_document(checked, actions, pins, "PASS", data_fd)
                receipt = _write_receipt(receipt_dir, receipt_value)
            except Exception as error:
                if isinstance(error, PublishedFileError):
                    actions[error.logical_path] = "installed"
                failure_status = "HOLD" if isinstance(error, ImportHold) else "FAIL"
                try:
                    failure_receipt = _write_receipt(
                        receipt_dir, _receipt_document(checked, actions, pins, failure_status, data_fd)
                    )
                    error.receipt = str(failure_receipt)
                except Exception:
                    pass
                raise
        return {
            "archives": receipt_value["archives"],
            "installed": sum(value == "installed" for value in actions.values()),
            "receipt": receipt.name,
            "skipped": sum(value == "skipped" for value in actions.values()),
            "status": "PASS",
            "validated": len(actions),
        }
    except Exception as error:
        if not dry_run and receipt_dir is not None and not hasattr(error, "receipt"):
            status = "HOLD" if isinstance(error, ImportHold) else "FAIL"
            try:
                if not (
                    receipt_dir.absolute() == data_root.absolute()
                    or receipt_dir.absolute().is_relative_to(data_root.absolute())
                ):
                    failure_receipt = _write_receipt(receipt_dir, _receipt_document(checked, {}, pins, status, data_fd))
                    error.receipt = str(failure_receipt)
            except Exception:
                pass
        raise
    finally:
        for archive in checked:
            os.close(archive.fd)
            os.close(archive.parent_fd)
        os.close(data_fd)


def import_bundles(
    archive_paths: tuple[Path, ...],
    manifest_path: Path,
    data_root: Path,
    *,
    receipt_dir: Path | None = None,
    dry_run: bool = False,
    pins: ManifestPins = PRODUCTION_PINS,
) -> dict[str, object]:
    """Verify all archives first, then install missing files without replacement."""
    try:
        return _import_bundles_impl(
            archive_paths, manifest_path, data_root, receipt_dir=receipt_dir, dry_run=dry_run, pins=pins
        )
    except Exception as error:
        if not dry_run and receipt_dir is not None and not hasattr(error, "receipt"):
            status = "HOLD" if isinstance(error, ImportHold) else "FAIL"
            terminal = {
                "archives": [],
                "data_root_identity": None,
                "files": [],
                "installed": 0,
                "manifest_csv_sha256": pins.sha256,
                "schema_version": SCHEMA_VERSION,
                "skipped": 0,
                "status": status,
                "validated": 0,
            }
            try:
                if not (
                    receipt_dir.absolute() == data_root.absolute()
                    or receipt_dir.absolute().is_relative_to(data_root.absolute())
                ):
                    failure_receipt = _write_receipt(receipt_dir, terminal)
                    error.receipt = str(failure_receipt)
            except Exception:
                pass
        raise


class _FailClosedParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise BundleError(f"invalid arguments: {message}")


def _parser() -> argparse.ArgumentParser:
    parser = _FailClosedParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    parser.add_argument("--receipt-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        result = import_bundles(
            tuple(args.archives), MANIFEST_PATH, DATA_ROOT, receipt_dir=args.receipt_dir, dry_run=args.dry_run
        )
        print(canonical_json(result).decode(), end="")
        return 0
    except Exception as error:
        status = "HOLD" if isinstance(error, ImportHold) else "FAIL"
        result = {"error": type(error).__name__, "status": status}
        receipt = getattr(error, "receipt", None)
        if isinstance(receipt, str):
            result["receipt"] = Path(receipt).name
        print(canonical_json(result).decode(), end="", file=sys.stderr)
        return 2 if status == "HOLD" else 1


if __name__ == "__main__":
    raise SystemExit(main())
