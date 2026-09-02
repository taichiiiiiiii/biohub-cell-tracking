#!/usr/bin/env python3
"""Deterministically pack the pinned incomplete eval-36 Zarr roots.

The production CLI intentionally has no flags for weakening the manifest pins.
Tests may call :func:`pack_bundles` with an explicit :class:`ManifestPins`.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import errno
import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

COMPETITION = "biohub-cell-tracking-during-development"
MANIFEST_SHA256 = "6c1c59644daf7fe59458dc860f2e1783d1217be389a791ea54e1f611f5f848f4"
MANIFEST_LINE_COUNT = 24_887
FILES_PER_ROOT = 102
SCHEMA_VERSION = 1
BUNDLE_MANIFEST_NAME = "__eval36_bundle_manifest__.json"
ROOTS = (
    "6bba_09961292",
    "6bba_0e7c0d07",
    "6bba_12665c0e",
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
PRODUCTION_EMBEDDED_MANIFEST_BYTES = 14_458
PRODUCTION_ARCHIVE_BYTES = dict(
    zip(
        ROOTS,
        (
            400_179_200,
            432_660_480,
            358_236_160,
            420_177_920,
            392_263_680,
            379_023_360,
            389_611_520,
            339_527_680,
            329_328_640,
            477_716_480,
            459_724_800,
            539_504_640,
            364_922_880,
            443_351_040,
            378_388_480,
        ),
        strict=True,
    )
)
_SAFE_ROOT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_CHUNK = 1024 * 1024


class BundleError(RuntimeError):
    """A fail-closed bundle validation or publication error."""


@dataclass(frozen=True)
class ManifestPins:
    sha256: str
    line_count: int
    roots: tuple[str, ...]
    files_per_root: int
    competition: str = COMPETITION


PRODUCTION_PINS = ManifestPins(MANIFEST_SHA256, MANIFEST_LINE_COUNT, ROOTS, FILES_PER_ROOT)


def canonical_json(value: object) -> bytes:
    """Return the one accepted canonical JSON representation."""
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rename_noreplace(
    source: str, destination: str, *, source_dir_fd: int | None = None, destination_dir_fd: int | None = None
) -> None:
    """Atomically rename without replacement on the supported macOS/Linux hosts."""
    at_fdcwd = -2
    source_fd = at_fdcwd if source_dir_fd is None else source_dir_fd
    destination_fd = at_fdcwd if destination_dir_fd is None else destination_dir_fd
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if sys.platform == "darwin":
        function = libc.renameatx_np
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = function(source_fd, source_bytes, destination_fd, destination_bytes, 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        try:
            function = libc.renameat2
        except AttributeError as error:
            raise BundleError("renameat2(RENAME_NOREPLACE) is unavailable") from error
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = function(source_fd, source_bytes, destination_fd, destination_bytes, 1)  # RENAME_NOREPLACE
    else:
        raise BundleError(f"atomic no-replace rename is unsupported on {sys.platform}")
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise FileExistsError(error_number, os.strerror(error_number), destination)
        raise OSError(error_number, os.strerror(error_number), destination)


def _stable_published_result(
    directory_fd: int, name: str, display_path: Path, expected_inode: tuple[int, int]
) -> tuple[int, str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(name, flags, dir_fd=directory_fd)
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or (before.st_dev, before.st_ino) != expected_inode
            or _identity(os.stat(name, dir_fd=directory_fd, follow_symlinks=False)) != _identity(before)
        ):
            raise BundleError(f"published archive identity mismatch: {display_path}")
        digest = hashlib.sha256()
        while chunk := os.read(fd, _CHUNK):
            digest.update(chunk)
        if _identity(os.fstat(fd)) != _identity(before) or _identity(
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        ) != _identity(before):
            raise BundleError(f"published archive changed while hashing: {display_path}")
        return before.st_size, digest.hexdigest()
    finally:
        os.close(fd)


def _safe_logical_path(name: str) -> bool:
    if not name or "\x00" in name or "\\" in name or name.startswith("/"):
        return False
    path = PurePosixPath(name)
    return all(part not in {"", ".", ".."} for part in path.parts) and str(path) == name


def _require_real_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as error:
        raise BundleError(f"directory unavailable: {path}: {error}") from error
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise BundleError(f"not a real directory: {path}")


def _require_real_directory_chain(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        _require_real_directory(current)


def _require_ancestors(root: Path, relative: PurePosixPath) -> None:
    _require_real_directory(root)
    current = root
    for part in relative.parts[:-1]:
        current /= part
        _require_real_directory(current)


def load_expected_files(manifest_path: Path, pins: ManifestPins = PRODUCTION_PINS) -> dict[str, list[tuple[str, int]]]:
    """Strictly validate the CSV pin and return ordered files for every pinned root."""
    try:
        raw = manifest_path.read_bytes()
    except OSError as error:
        raise BundleError(f"cannot read manifest: {error}") from error
    if hashlib.sha256(raw).hexdigest() != pins.sha256:
        raise BundleError("manifest SHA-256 mismatch")
    if len(raw.splitlines()) != pins.line_count:
        raise BundleError("manifest line-count mismatch")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BundleError("manifest is not UTF-8") from error
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames != ["name", "size"]:
        raise BundleError("manifest columns must be exactly name,size")
    expected = {root: [] for root in pins.roots}
    seen: set[str] = set()
    try:
        for row in reader:
            if set(row) != {"name", "size"} or None in row or row["name"] is None or row["size"] is None:
                raise BundleError("malformed manifest row")
            name, size_text = row["name"], row["size"]
            if not _safe_logical_path(name) or name in seen:
                raise BundleError(f"unsafe or duplicate manifest path: {name!r}")
            seen.add(name)
            if not re.fullmatch(r"0|[1-9][0-9]*", size_text):
                raise BundleError(f"invalid manifest size for {name}")
            for root in pins.roots:
                if name.startswith(f"train/{root}.zarr/"):
                    expected[root].append((name, int(size_text)))
                    break
    except (csv.Error, UnicodeError) as error:
        raise BundleError(f"malformed manifest CSV: {error}") from error
    for root, files in expected.items():
        files.sort(key=lambda item: item[0].encode("utf-8"))
        if len(files) != pins.files_per_root:
            raise BundleError(f"manifest file-set drift for {root}: expected {pins.files_per_root}, got {len(files)}")
    return expected


def _octal(value: int, width: int) -> bytes:
    encoded = f"{value:0{width - 1}o}\0".encode("ascii")
    if len(encoded) != width:
        raise BundleError("USTAR numeric field overflow")
    return encoded


def _ustar_name(path: str) -> tuple[bytes, bytes]:
    encoded = path.encode("utf-8")
    if len(encoded) <= 100:
        return encoded, b""
    choices = [i for i, byte in enumerate(encoded) if byte == ord("/") and i <= 155 and len(encoded) - i - 1 <= 100]
    if not choices:
        raise BundleError(f"path cannot be represented in USTAR: {path}")
    split = choices[-1]
    return encoded[split + 1 :], encoded[:split]


def _header(path: str, size: int) -> bytes:
    name, prefix = _ustar_name(path)
    block = bytearray(512)
    block[0 : len(name)] = name
    block[100:108] = _octal(0o444, 8)
    block[108:116] = _octal(0, 8)
    block[116:124] = _octal(0, 8)
    block[124:136] = _octal(size, 12)
    block[136:148] = _octal(0, 12)
    block[148:156] = b"        "
    block[156:157] = b"0"
    block[257:263] = b"ustar\0"
    block[263:265] = b"00"
    block[345 : 345 + len(prefix)] = prefix
    block[148:156] = f"{sum(block):06o}\0 ".encode("ascii")
    return bytes(block)


class _HashingReader:
    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream
        self.digest = hashlib.sha256()
        self.count = 0

    def copy_to(self, target: BinaryIO, size: int) -> None:
        remaining = size
        while remaining:
            chunk = self.stream.read(min(_CHUNK, remaining))
            if not chunk:
                raise BundleError("short source read")
            target.write(chunk)
            self.digest.update(chunk)
            self.count += len(chunk)
            remaining -= len(chunk)
        if self.stream.read(1):
            raise BundleError("source grew during read")


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _write_member(target: BinaryIO, name: str, payload: bytes) -> None:
    target.write(_header(name, len(payload)))
    target.write(payload)
    target.write(b"\0" * (-len(payload) % 512))


def _pack_one(
    root: str, files: list[tuple[str, int]], source_root: Path, output_dir: Path, pins: ManifestPins
) -> dict[str, object]:
    final_name = f"{root}.tar"
    final = output_dir / final_name
    output_fd = os.open(output_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    output_info = os.fstat(output_fd)
    if _identity(output_dir.lstat()) != _identity(output_info):
        os.close(output_fd)
        raise BundleError("output directory identity changed")
    try:
        os.stat(final_name, dir_fd=output_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        os.close(output_fd)
        raise BundleError(f"refusing to overwrite archive: {final}")
    temp_name: str | None = None
    for attempt in range(100):
        candidate = f".{root}.{os.getpid()}-{attempt}.tmp"
        try:
            fd = os.open(
                candidate,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=output_fd,
            )
            temp_name = candidate
            break
        except FileExistsError:
            continue
    else:
        os.close(output_fd)
        raise BundleError(f"cannot reserve archive temporary: {root}")
    entries: list[dict[str, object]] = []
    published_inode: tuple[int, int] | None = None
    try:
        with os.fdopen(fd, "wb", closefd=True) as target:
            for logical, expected_size in files:
                relative = PurePosixPath(logical)
                _require_ancestors(source_root, relative)
                source = source_root.joinpath(*relative.parts)
                try:
                    leaf_info = source.lstat()
                except OSError as error:
                    raise BundleError(f"cannot stat source {logical}: {error}") from error
                if not stat.S_ISREG(leaf_info.st_mode) or stat.S_ISLNK(leaf_info.st_mode):
                    raise BundleError(f"source is not a non-symlink regular file: {logical}")
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                try:
                    source_fd = os.open(source, flags)
                except OSError as error:
                    raise BundleError(f"cannot safely open source {logical}: {error}") from error
                with os.fdopen(source_fd, "rb", closefd=True) as stream:
                    before = os.fstat(stream.fileno())
                    path_before = source.lstat()
                    if not stat.S_ISREG(before.st_mode) or before.st_size != expected_size:
                        raise BundleError(f"source type/link/size mismatch: {logical}")
                    if _identity(before) != _identity(path_before):
                        raise BundleError(f"source identity mismatch: {logical}")
                    target.write(_header(logical, expected_size))
                    hashing = _HashingReader(stream)
                    hashing.copy_to(target, expected_size)
                    target.write(b"\0" * (-expected_size % 512))
                    after = os.fstat(stream.fileno())
                    path_after = source.lstat()
                    if _identity(before) != _identity(after) or _identity(before) != _identity(path_after):
                        raise BundleError(f"source changed during packing: {logical}")
                    stream.seek(0)
                    second = hashlib.sha256()
                    second_count = 0
                    for chunk in iter(lambda: stream.read(_CHUNK), b""):
                        second.update(chunk)
                        second_count += len(chunk)
                    final_info = os.fstat(stream.fileno())
                    final_path_info = source.lstat()
                    if (
                        second_count != expected_size
                        or second.digest() != hashing.digest.digest()
                        or _identity(before) != _identity(final_info)
                        or _identity(before) != _identity(final_path_info)
                    ):
                        raise BundleError(f"source second-view mismatch: {logical}")
                    entries.append({"path": logical, "sha256": hashing.digest.hexdigest(), "size": expected_size})
            embedded = {
                "competition": pins.competition,
                "files": entries,
                "manifest_csv_sha256": pins.sha256,
                "root": root,
                "schema_version": SCHEMA_VERSION,
            }
            embedded_bytes = canonical_json(embedded)
            if pins == PRODUCTION_PINS and len(embedded_bytes) != PRODUCTION_EMBEDDED_MANIFEST_BYTES:
                raise BundleError(f"production embedded manifest size drift for {root}")
            _write_member(target, BUNDLE_MANIFEST_NAME, embedded_bytes)
            target.write(b"\0" * 1024)
            padding = (-target.tell()) % 10240
            target.write(b"\0" * padding)
            target.flush()
            os.fsync(target.fileno())
        ready_info = os.stat(temp_name, dir_fd=output_fd, follow_symlinks=False)
        try:
            rename_noreplace(temp_name, final_name, source_dir_fd=output_fd, destination_dir_fd=output_fd)
        except FileExistsError as error:
            raise BundleError(f"archive publication race: {final}") from error
        published_inode = (ready_info.st_dev, ready_info.st_ino)
        temp_name = None
        os.fsync(output_fd)
        current_output = output_dir.lstat()
        if (current_output.st_dev, current_output.st_ino, current_output.st_mode) != (
            output_info.st_dev,
            output_info.st_ino,
            output_info.st_mode,
        ):
            raise BundleError("output directory changed during publication")
        archive_size, archive_sha256 = _stable_published_result(
            output_fd, final_name, final, (ready_info.st_dev, ready_info.st_ino)
        )
        if pins == PRODUCTION_PINS and archive_size != PRODUCTION_ARCHIVE_BYTES[root]:
            raise BundleError(f"production archive size drift for {root}")
        return {"archive": str(final), "bytes": archive_size, "root": root, "sha256": archive_sha256}
    except BaseException:
        if temp_name is not None:
            try:
                os.unlink(temp_name, dir_fd=output_fd)
            except FileNotFoundError:
                pass
        if published_inode is not None:
            try:
                final_info = os.stat(final_name, dir_fd=output_fd, follow_symlinks=False)
                if (final_info.st_dev, final_info.st_ino) == published_inode:
                    os.unlink(final_name, dir_fd=output_fd)
            except FileNotFoundError:
                pass
        raise
    finally:
        os.close(output_fd)


def pack_bundles(
    manifest_path: Path,
    source_root: Path,
    output_dir: Path,
    roots: tuple[str, ...] = ROOTS,
    *,
    pins: ManifestPins = PRODUCTION_PINS,
) -> list[dict[str, object]]:
    """Validate inputs and publish deterministic, immutable-by-policy archives."""
    if len(roots) != len(set(roots)):
        raise BundleError("duplicate root selection")
    if not roots:
        raise BundleError("empty root selection")
    allowed = set(pins.roots)
    for root in roots:
        if not isinstance(root, str) or not _SAFE_ROOT.fullmatch(root) or root not in allowed:
            raise BundleError(f"unknown or unsafe root: {root!r}")
    _require_real_directory_chain(source_root)
    _require_real_directory_chain(output_dir)
    expected = load_expected_files(manifest_path, pins)
    collisions = [output_dir / f"{root}.tar" for root in roots if (output_dir / f"{root}.tar").exists()]
    if collisions:
        raise BundleError(f"output already exists: {collisions[0]}")
    return [_pack_one(root, expected[root], source_root, output_dir, pins) for root in roots]


class _FailClosedParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise BundleError(f"invalid arguments: {message}")


def _parser() -> argparse.ArgumentParser:
    parser = _FailClosedParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-data", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--root", action="append", dest="roots")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        results = pack_bundles(args.manifest, args.source_data, args.output_dir, tuple(args.roots or ROOTS))
        print(canonical_json({"archives": results, "status": "PASS"}).decode(), end="")
        return 0
    except Exception as error:
        print(canonical_json({"error": str(error), "status": "FAIL"}).decode(), end="", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
