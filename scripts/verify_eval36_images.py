#!/usr/bin/env python3
"""Fail-closed verification and sealing of fixed eval-36 Zarr image content.

The CLI is intentionally explicit: the data root, E24 import receipt, and a
pre-existing empty output directory must all be named by the caller.  It never
downloads data and never modifies the data tree.  The source ``data/train`` may
also contain GEFF ground-truth directories; they are neither read nor included
in the image inventory.  READY's ``data_root_identity`` is evidence identifying
that source image-containing ``train`` directory, not an inode-equivalence
requirement for a later, separately rehashed image-only ST-R3 sandbox copy.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import ctypes
import datetime as dt
import errno
import fcntl
import hashlib
import io
import json
import math
import os
import re
import secrets
import stat
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import blosc2

MANIFEST_NAME = "manifest.csv"
MANIFEST_BYTES = 1_187_624
MANIFEST_LINES = 24_887
MANIFEST_SHA256 = "6c1c59644daf7fe59458dc860f2e1783d1217be389a791ea54e1f611f5f848f4"
FILES_PER_ROOT = 102
STORED_BYTES = 15_932_872_938
CHUNKS_PER_ROOT = 100
CHUNK_SHAPE = (1, 64, 256, 256)
DECODED_SHAPE = (64, 256, 256)
DECODED_CHUNK_BYTES = 8_388_608
DECODED_BYTES = 30_198_988_800
DECODED_SHA256 = "635a326ff78526a3d43952b94950e6d97d07db14cd53bc056517ea70d5b49646"
INVENTORY_SCHEMA = "biohub.eval36_image_content_inventory.v1"
READY_SCHEMA = "biohub.eval36_images_ready.v1"
_READ_SIZE = 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

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

E24_ROOTS = (
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

E24_ARCHIVE_BYTES = (
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
)

E24_ARCHIVE_SHA256 = (
    "e3d225f5eb47fbdc3706b2f73cb47dcc16a6142b92439d9c7ac41e1510f331f3",
    "ff7b69d0fd5f190ed3f33a97e81949edd167eda31251865a81fb2176b0c3dd87",
    "4c2d7981cd956d4d81b823fc297d715996344cead56ffa9694a4e7ddc20c1776",
    "6cd4433039685569fc79591a1e3a949bbc006e1579f3b6dffd8fdf499ebf8344",
    "4f955d9059bdc915d1824fc99bd06142b5217495dd393f3e6ca06af1c8d2764b",
    "bc2e435040d05f7cf712c21fc713fddc668eef637b89b4d976bed661cf04279b",
    "66f68cef2083a1821ff0667025287d412dd7b51e1863de20e52aaaa816522702",
    "78221a5392d9cc4609f8012bfe6cd558e2fec4ec4edd868b785df41085e7235a",
    "c4655f71afb7f9c07a2c5e21cea4b65eb846db2f58c4b5a6fb10ab5d06318bca",
    "eb8d6f83895b03460df3006d48c12f663d050c9785f44ccb0bbc71f528dd7a75",
    "3d92e57fee13fffdc30ab03fc442d2f56289619c2912e3558783f9bb9fab15ad",
    "b6cc6a246b6c8c90e2ad4979cf69092a38697b1840d7c07022aa62df5466bf94",
    "d0714fb7d5fa0b8ef1e9948de1d220a0cadd92d04861cb0cc60087d097f05301",
    "940e7f74852748db49d882ef6e00ed6bf06dea47e0fc430d4602703ea2118fd4",
    "1297e35a5fd5a7fa37df8576546f70510a8e1835a405303b72d276ad3cff2ad4",
)


class VerificationError(RuntimeError):
    """The image tree cannot safely be declared ready."""


class PublicationAmbiguityError(VerificationError):
    """Publication cleanup could not prove a durable READY-absent state."""


@dataclass(frozen=True)
class Profile:
    stems: tuple[str, ...]
    import_roots: tuple[str, ...]
    archive_bytes: tuple[int, ...]
    archive_sha256: tuple[str, ...]
    manifest_bytes: int
    manifest_lines: int
    manifest_sha256: str
    files_per_root: int
    stored_bytes: int
    chunks_per_root: int
    chunk_shape: tuple[int, int, int, int]
    decoded_shape: tuple[int, int, int]
    decoded_chunk_bytes: int
    decoded_bytes: int
    decoded_sha256: str
    import_installed: int
    import_skipped: int
    import_validated: int


PRODUCTION_PROFILE = Profile(
    stems=EVAL36_STEMS,
    import_roots=E24_ROOTS,
    archive_bytes=E24_ARCHIVE_BYTES,
    archive_sha256=E24_ARCHIVE_SHA256,
    manifest_bytes=MANIFEST_BYTES,
    manifest_lines=MANIFEST_LINES,
    manifest_sha256=MANIFEST_SHA256,
    files_per_root=FILES_PER_ROOT,
    stored_bytes=STORED_BYTES,
    chunks_per_root=CHUNKS_PER_ROOT,
    chunk_shape=CHUNK_SHAPE,
    decoded_shape=DECODED_SHAPE,
    decoded_chunk_bytes=DECODED_CHUNK_BYTES,
    decoded_bytes=DECODED_BYTES,
    decoded_sha256=DECODED_SHA256,
    import_installed=1_487,
    import_skipped=43,
    import_validated=1_530,
)


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def strict_json(raw: bytes) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise VerificationError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise VerificationError(f"non-finite JSON value: {value}")

    def finite_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise VerificationError(f"non-finite JSON float: {value}")
        return parsed

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
            parse_float=finite_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationError(f"invalid strict JSON: {error}") from error


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _ownership_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    """Identity fields that a same-filesystem rename does not change."""
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size)


def _same_path(path: Path, fd: int) -> bool:
    try:
        return _identity(path.lstat()) == _identity(os.fstat(fd))
    except OSError:
        return False


def _open_directory_path(path: Path) -> int:
    absolute = path.absolute()
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=current)
            os.close(current)
            current = next_fd
        info = os.fstat(current)
        if not stat.S_ISDIR(info.st_mode) or not _same_path(absolute, current):
            raise VerificationError(f"unsafe directory path: {path}")
        return current
    except BaseException:
        os.close(current)
        raise


def _safe_relative(value: str) -> bool:
    if not value or "\x00" in value or "\\" in value or value.startswith("/"):
        return False
    path = PurePosixPath(value)
    return str(path) == value and all(part not in {"", ".", ".."} for part in path.parts)


def _dataset_to_image_view_path(value: str) -> str:
    if not _safe_relative(value):
        raise VerificationError(f"unsafe dataset-root path: {value!r}")
    parts = PurePosixPath(value).parts
    if len(parts) < 3 or parts[0] != "train" or not parts[1].endswith(".zarr"):
        raise VerificationError(f"dataset path is outside the train image view: {value}")
    return PurePosixPath(*parts[1:]).as_posix()


def _read_all(fd: int) -> bytes:
    chunks: list[bytes] = []
    while chunk := os.read(fd, _READ_SIZE):
        chunks.append(chunk)
    return b"".join(chunks)


def _read_named_file(parent_fd: int, name: str, logical: str) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        raise VerificationError(f"cannot safely open {logical}: {error}") from error
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise VerificationError(f"non-regular or multiply-linked file: {logical}")
        raw = _read_all(fd)
        after = os.fstat(fd)
        path_info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            len(raw) != before.st_size
            or _identity(before) != _identity(after)
            or _identity(before) != _identity(path_info)
        ):
            raise VerificationError(f"file changed while reading: {logical}")
        return raw, before
    finally:
        os.close(fd)


def _read_absolute_file(path: Path) -> tuple[bytes, os.stat_result]:
    parent_fd = _open_directory_path(path.absolute().parent)
    try:
        return _read_named_file(parent_fd, path.name, str(path.absolute()))
    finally:
        os.close(parent_fd)


def _open_relative_directory(root_fd: int, parts: tuple[str, ...], logical: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current = os.dup(root_fd)
    try:
        for part in parts:
            parent_info = os.fstat(current)
            next_fd = os.open(part, flags, dir_fd=current)
            path_info = os.stat(part, dir_fd=current, follow_symlinks=False)
            if _identity(os.fstat(next_fd)) != _identity(path_info) or not stat.S_ISDIR(path_info.st_mode):
                os.close(next_fd)
                raise VerificationError(f"directory identity mismatch: {logical}")
            if _identity(os.fstat(current)) != _identity(parent_info):
                os.close(next_fd)
                raise VerificationError(f"parent directory changed: {logical}")
            os.close(current)
            current = next_fd
        return current
    except BaseException:
        os.close(current)
        raise


def _read_data_file(data_fd: int, relative: str) -> tuple[bytes, os.stat_result]:
    if not _safe_relative(relative):
        raise VerificationError(f"unsafe relative path: {relative!r}")
    parts = PurePosixPath(relative).parts
    parent_fd = _open_relative_directory(data_fd, tuple(parts[:-1]), relative)
    try:
        return _read_named_file(parent_fd, parts[-1], relative)
    finally:
        os.close(parent_fd)


def _walk_files(directory_fd: int, prefix: str) -> set[str]:
    result: set[str] = set()
    before = os.fstat(directory_fd)
    for name in os.listdir(directory_fd):
        if not name or "/" in name or name in {".", ".."}:
            raise VerificationError(f"unsafe directory entry below {prefix}")
        logical = f"{prefix}/{name}"
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            child = _open_relative_directory(directory_fd, (name,), logical)
            try:
                result.update(_walk_files(child, logical))
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            result.add(logical)
        else:
            raise VerificationError(f"symlink, special, or multiply-linked entry: {logical}")
    if _identity(before) != _identity(os.fstat(directory_fd)):
        raise VerificationError(f"directory changed while scanning: {prefix}")
    return result


def _assert_exact_tree(
    data_fd: int, expected: dict[str, int], profile: Profile
) -> tuple[int, int, int, int, int, int, int]:
    """Use one strict scanner for both the start and end tree snapshots."""
    train_fd = _open_relative_directory(data_fd, ("train",), "train")
    try:
        image_view_identity = _identity(os.fstat(train_fd))
        roots: set[str] = set()
        for name in os.listdir(train_fd):
            if not name.endswith(".zarr"):
                continue
            logical = f"train/{name}"
            info = os.stat(name, dir_fd=train_fd, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode):
                raise VerificationError(f"symlink or special Zarr root: {logical}")
            roots.add(name.removesuffix(".zarr"))
        if roots != set(profile.stems):
            raise VerificationError("eval-36 Zarr root set drift")
        if _identity(os.fstat(train_fd)) != image_view_identity:
            raise VerificationError("image-view directory changed while scanning roots")
    finally:
        os.close(train_fd)
    for stem in profile.stems:
        root_relative = f"train/{stem}.zarr"
        root_fd = _open_relative_directory(data_fd, tuple(PurePosixPath(root_relative).parts), root_relative)
        try:
            actual = _walk_files(root_fd, root_relative)
        finally:
            os.close(root_fd)
        wanted = {path for path in expected if path.startswith(f"{root_relative}/")}
        if actual != wanted:
            raise VerificationError(f"exact member set drift for {stem}")
    return image_view_identity


def _stat_data_file(data_fd: int, relative: str) -> os.stat_result:
    if not _safe_relative(relative):
        raise VerificationError(f"unsafe relative path: {relative!r}")
    parts = PurePosixPath(relative).parts
    parent_fd = _open_relative_directory(data_fd, tuple(parts[:-1]), relative)
    try:
        info = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise VerificationError(f"non-regular or multiply-linked file: {relative}")
        return info
    finally:
        os.close(parent_fd)


def _manifest_entries(raw: bytes, profile: Profile) -> dict[str, int]:
    if len(raw) != profile.manifest_bytes:
        raise VerificationError("manifest byte count drift")
    if raw.count(b"\n") != profile.manifest_lines or raw.count(b"\r\n") != profile.manifest_lines:
        raise VerificationError("manifest physical line/CRLF count drift")
    if hashlib.sha256(raw).hexdigest() != profile.manifest_sha256:
        raise VerificationError("manifest SHA-256 drift")
    try:
        text = raw.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if reader.fieldnames != ["name", "size"]:
            raise VerificationError("manifest header drift")
        entries: dict[str, int] = {}
        for row in reader:
            if set(row) != {"name", "size"} or None in row:
                raise VerificationError("manifest row shape drift")
            name = row["name"]
            size_text = row["size"]
            if not _safe_relative(name) or not size_text.isascii() or not size_text.isdigit():
                raise VerificationError(f"invalid manifest row: {name!r}")
            size = int(size_text)
            if str(size) != size_text or name in entries:
                raise VerificationError(f"non-canonical or duplicate manifest row: {name!r}")
            entries[name] = size
        return entries
    except (UnicodeDecodeError, csv.Error) as error:
        raise VerificationError(f"invalid manifest CSV: {error}") from error


def _expected_image_entries(entries: dict[str, int], profile: Profile) -> dict[str, int]:
    selected: dict[str, int] = {}
    for stem in profile.stems:
        prefix = f"train/{stem}.zarr/"
        root_entries = {name: size for name, size in entries.items() if name.startswith(prefix)}
        if len(root_entries) != profile.files_per_root:
            raise VerificationError(f"manifest member count drift for {stem}")
        selected.update(root_entries)
    if len(selected) != len(profile.stems) * profile.files_per_root:
        raise VerificationError("manifest selected-file count drift")
    if sum(selected.values()) != profile.stored_bytes:
        raise VerificationError("manifest selected-byte count drift")
    return selected


def _validate_group_metadata(value: object, logical: str) -> None:
    if not isinstance(value, dict) or set(value) != {
        "attributes",
        "consolidated_metadata",
        "node_type",
        "zarr_format",
    }:
        raise VerificationError(f"Zarr group schema drift: {logical}")
    attributes = value["attributes"]
    if (
        not isinstance(attributes, dict)
        or value["consolidated_metadata"] is not None
        or value["node_type"] != "group"
        or type(value["zarr_format"]) is not int
        or value["zarr_format"] != 3
    ):
        raise VerificationError(f"Zarr v3 group metadata drift: {logical}")
    if set(attributes) != {"image_statistics", "multiscales"}:
        raise VerificationError(f"OME group attributes drift: {logical}")
    expected_multiscales = [
        {
            "axes": [
                {"name": "T", "type": "time", "unit": "second"},
                {"name": "Z", "type": "space", "unit": "micrometer"},
                {"name": "Y", "type": "space", "unit": "micrometer"},
                {"name": "X", "type": "space", "unit": "micrometer"},
            ],
            "datasets": [
                {
                    "coordinateTransformations": [{"scale": [1.0, 1.625, 0.40625, 0.40625], "type": "scale"}],
                    "path": "0",
                }
            ],
            "name": "0",
            "version": "0.5",
        }
    ]
    if attributes["multiscales"] != expected_multiscales:
        raise VerificationError(f"OME TZYX axes/scale drift: {logical}")
    scales = attributes["multiscales"][0]["datasets"][0]["coordinateTransformations"][0]["scale"]
    if any(type(number) is not float for number in scales):
        raise VerificationError(f"OME scale numeric type drift: {logical}")
    statistics = attributes["image_statistics"]
    if not isinstance(statistics, dict) or set(statistics) != {"quantiles"}:
        raise VerificationError(f"image statistics schema drift: {logical}")
    quantiles = statistics["quantiles"]
    expected_quantiles = {"0.0", "0.001", "0.01", "0.1", "0.9", "0.99", "0.999", "1.0"}
    if not isinstance(quantiles, dict) or set(quantiles) != expected_quantiles:
        raise VerificationError(f"image quantiles schema drift: {logical}")
    if any(type(number) not in {int, float} for number in quantiles.values()):
        raise VerificationError(f"image quantiles type drift: {logical}")


def _expected_array_metadata(profile: Profile) -> dict[str, object]:
    return {
        "attributes": {},
        "chunk_grid": {"configuration": {"chunk_shape": list(profile.chunk_shape)}, "name": "regular"},
        "chunk_key_encoding": {"configuration": {"separator": "/"}, "name": "default"},
        "codecs": [
            {"configuration": {"endian": "little"}, "name": "bytes"},
            {
                "configuration": {
                    "blocksize": 0,
                    "clevel": 1,
                    "cname": "zstd",
                    "shuffle": "bitshuffle",
                    "typesize": 2,
                },
                "name": "blosc",
            },
        ],
        "data_type": "uint16",
        "fill_value": 0,
        "node_type": "array",
        "shape": [profile.chunks_per_root, *profile.decoded_shape],
        "storage_transformers": [],
        "zarr_format": 3,
    }


def _validate_import_receipt(
    value: object,
    raw: bytes,
    reference: Path,
    data_identity: dict[str, int],
    expected: dict[str, int],
    inventory_by_path: dict[str, dict[str, object]],
    profile: Profile,
) -> dict[str, object]:
    if canonical_json(value) != raw:
        raise VerificationError("import receipt is not canonical JSON")
    keys = {
        "archives",
        "data_root_identity",
        "files",
        "installed",
        "manifest_csv_sha256",
        "schema_version",
        "skipped",
        "status",
        "validated",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise VerificationError("import receipt schema drift")
    scalars = {
        "schema_version": 1,
        "status": "PASS",
        "manifest_csv_sha256": profile.manifest_sha256,
        "installed": profile.import_installed,
        "skipped": profile.import_skipped,
        "validated": profile.import_validated,
    }
    for key, expected_value in scalars.items():
        actual = value[key]
        if type(expected_value) is int and type(actual) is not int:
            raise VerificationError(f"import receipt {key} type drift")
        if actual != expected_value:
            raise VerificationError(f"import receipt {key} drift")
    receipt_data_identity = value["data_root_identity"]
    if (
        not isinstance(receipt_data_identity, dict)
        or set(receipt_data_identity) != {"device", "inode"}
        or any(type(receipt_data_identity[key]) is not int for key in ("device", "inode"))
        or receipt_data_identity != data_identity
    ):
        raise VerificationError("import receipt data-root identity drift")
    archives = value["archives"]
    if not isinstance(archives, list) or len(archives) != len(profile.import_roots):
        raise VerificationError("import receipt archive count drift")
    if len(profile.archive_sha256) != len(profile.import_roots):
        raise VerificationError("fixed archive digest profile drift")
    for item, root, size, digest in zip(
        archives, profile.import_roots, profile.archive_bytes, profile.archive_sha256, strict=True
    ):
        if not isinstance(item, dict) or set(item) != {"bytes", "name", "root", "sha256"}:
            raise VerificationError("import receipt archive schema drift")
        if (
            item["root"] != root
            or item["name"] != f"{root}.tar"
            or type(item["bytes"]) is not int
            or item["bytes"] != size
            or item["sha256"] != digest
        ):
            raise VerificationError(f"import receipt archive drift: {root}")
    wanted = {
        path: size
        for path, size in expected.items()
        if PurePosixPath(path).parts[1].removesuffix(".zarr") in profile.import_roots
    }
    files = value["files"]
    if not isinstance(files, list) or len(files) != profile.import_validated:
        raise VerificationError("import receipt file count drift")
    paths: list[str] = []
    installed = 0
    skipped = 0
    for item in files:
        if not isinstance(item, dict) or set(item) != {"action", "path", "sha256", "size"}:
            raise VerificationError("import receipt file schema drift")
        path = item["path"]
        if not isinstance(path, str) or not _safe_relative(path) or path not in wanted:
            raise VerificationError("import receipt file path drift")
        action = item["action"]
        if action == "installed":
            installed += 1
        elif action == "skipped":
            skipped += 1
        else:
            raise VerificationError(f"import receipt action drift: {path}")
        image_view_path = _dataset_to_image_view_path(path)
        record = inventory_by_path[image_view_path]
        if (
            type(item["size"]) is not int
            or item["size"] != wanted[path]
            or item["size"] != record["bytes"]
            or not isinstance(item["sha256"], str)
            or _SHA256.fullmatch(item["sha256"]) is None
            or item["sha256"] != record["sha256"]
        ):
            raise VerificationError(f"import receipt current-file drift: {path}")
        paths.append(path)
    if paths != sorted(wanted, key=lambda item: item.encode()) or len(set(paths)) != len(paths):
        raise VerificationError("import receipt file set/order drift")
    if installed != profile.import_installed or skipped != profile.import_skipped:
        raise VerificationError("import receipt action counts drift")
    receipt_sha256 = hashlib.sha256(raw).hexdigest()
    if reference.name != f"eval36-import-{receipt_sha256}.json":
        raise VerificationError("import receipt filename/content digest mismatch")
    return {
        "bytes": len(raw),
        "reference": reference.name,
        "sha256": receipt_sha256,
        "status": "PASS",
        "installed": installed,
        "skipped": skipped,
        "validated": len(files),
    }


@contextlib.contextmanager
def _shared_download_lock(data_fd: int) -> Iterator[None]:
    try:
        fd = os.open(".download_data.lock", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=data_fd)
    except OSError as error:
        raise VerificationError(f"cannot safely open downloader lock: {error}") from error
    try:
        info = os.fstat(fd)
        path_info = os.stat(".download_data.lock", dir_fd=data_fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or _identity(info) != _identity(path_info):
            raise VerificationError("unsafe downloader lock file")
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise VerificationError("downloader/import lock is held") from error
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)


def rename_noreplace(source: str, destination: str, *, directory_fd: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function = libc.renameatx_np
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = function(directory_fd, os.fsencode(source), directory_fd, os.fsencode(destination), 0x4)
    elif sys.platform.startswith("linux"):
        try:
            function = libc.renameat2
        except AttributeError as error:
            raise VerificationError("renameat2(RENAME_NOREPLACE) is unavailable") from error
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = function(directory_fd, os.fsencode(source), directory_fd, os.fsencode(destination), 0x1)
    else:  # pragma: no cover - supported production platforms are macOS/Linux
        raise VerificationError(f"atomic no-replace rename unsupported on {sys.platform}")
    if result != 0:
        number = ctypes.get_errno()
        if number == errno.EEXIST:
            raise VerificationError(f"publication collision: {destination}")
        raise OSError(number, os.strerror(number), destination)


def _write_temp(directory_fd: int, final_name: str, payload: bytes) -> tuple[str, tuple[int, int, int, int, int]]:
    name: str | None = None
    fd: int | None = None
    ownership: tuple[int, int, int, int, int] | None = None
    for _ in range(16):
        candidate = f".{final_name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        try:
            fd = os.open(
                candidate,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o444,
                dir_fd=directory_fd,
            )
            name = candidate
            ownership = _ownership_identity(os.fstat(fd))
            break
        except FileExistsError:
            continue
    else:
        raise VerificationError(f"cannot allocate temporary output for {final_name}")
    try:
        assert fd is not None and name is not None and ownership is not None
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise VerificationError(f"short write for {final_name}")
            view = view[written:]
        os.fsync(fd)
        info = os.fstat(fd)
        path_info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or _identity(info) != _identity(path_info):
            raise VerificationError(f"temporary output identity drift: {final_name}")
        ownership = _ownership_identity(info)
        os.close(fd)
        fd = None
        return name, ownership
    except BaseException as error:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
        if name is not None and ownership is not None:
            _rollback_owned(directory_fd, {name: ownership}, error)
        raise


def _rollback_owned(
    directory_fd: int,
    owned: dict[str, tuple[int, int, int, int, int]],
    cause: BaseException,
) -> None:
    """Remove only transaction-owned names and durably prove their absence."""
    problems: list[str] = []
    for name, expected in owned.items():
        try:
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        except OSError as error:
            problems.append(f"stat {name}: {error}")
            continue
        if _ownership_identity(info)[:2] != expected[:2]:
            problems.append(f"ownership changed for {name}")
            continue
        try:
            os.unlink(name, dir_fd=directory_fd)
        except OSError as error:
            problems.append(f"unlink {name}: {error}")
    for name in owned:
        try:
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        except OSError as error:
            problems.append(f"absence check {name}: {error}")
        else:
            problems.append(f"name remains after rollback: {name}")
    try:
        os.fsync(directory_fd)
    except OSError as error:
        problems.append(f"rollback directory fsync: {error}")
    if problems:
        detail = "; ".join(problems)
        raise PublicationAmbiguityError(
            f"publication rollback is ambiguous after {type(cause).__name__}: {detail}"
        ) from cause


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def verify_images(
    data_root: Path,
    import_receipt: Path,
    output_dir: Path,
    *,
    profile: Profile = PRODUCTION_PROFILE,
    verifier_path: Path | None = None,
    decoder: Callable[[bytes], bytes | bytearray | memoryview] = blosc2.decompress,
    now: Callable[[], str] = _utc_now,
) -> dict[str, object]:
    """Verify all pinned bytes and publish a sealed inventory followed by READY."""
    verifier_path = Path(__file__) if verifier_path is None else verifier_path
    data_absolute = data_root.absolute()
    output_absolute = output_dir.absolute()
    if output_absolute == data_absolute or output_absolute.is_relative_to(data_absolute):
        raise VerificationError("output directory must be outside data root")
    data_fd = _open_directory_path(data_absolute)
    try:
        output_fd = _open_directory_path(output_absolute)
    except BaseException:
        os.close(data_fd)
        raise
    try:
        if os.listdir(output_fd):
            raise VerificationError("output directory must be empty and fresh")
        data_info = os.fstat(data_fd)
        output_info = os.fstat(output_fd)
        data_identity = {"device": data_info.st_dev, "inode": data_info.st_ino}
        source_raw, _ = _read_absolute_file(verifier_path)
        receipt_raw, _ = _read_absolute_file(import_receipt)
        receipt_value = strict_json(receipt_raw)
        with _shared_download_lock(data_fd):
            manifest_raw, _ = _read_data_file(data_fd, MANIFEST_NAME)
            manifest_entries = _manifest_entries(manifest_raw, profile)
            expected = _expected_image_entries(manifest_entries, profile)
            image_view_full_identity = _assert_exact_tree(data_fd, expected, profile)
            image_view_identity = {
                "device": image_view_full_identity[0],
                "inode": image_view_full_identity[1],
            }

            inventory_records: list[dict[str, object]] = []
            file_identities: dict[str, tuple[int, int, int, int, int, int, int]] = {}
            decoded_digest = hashlib.sha256()
            decoded_count = 0
            decoded_bytes = 0
            for stem in profile.stems:
                root_relative = f"train/{stem}.zarr"
                wanted = {path for path in expected if path.startswith(f"{root_relative}/")}
                group_path = f"{root_relative}/zarr.json"
                array_path = f"{root_relative}/0/zarr.json"
                group_value: object | None = None
                array_value: object | None = None
                chunk_paths = {f"{root_relative}/0/c/{index}/0/0/0": index for index in range(profile.chunks_per_root)}
                read_order = (group_path, array_path, *chunk_paths)
                if set(read_order) != wanted or len(read_order) != len(wanted):
                    raise VerificationError(f"Zarr canonical path layout drift: {stem}")
                for path in read_order:
                    raw, info = _read_data_file(data_fd, path)
                    if info.st_size != expected[path] or len(raw) != expected[path]:
                        raise VerificationError(f"manifest byte-size drift: {path}")
                    file_identities[path] = _identity(info)
                    inventory_records.append(
                        {
                            "bytes": len(raw),
                            "path": _dataset_to_image_view_path(path),
                            "sha256": hashlib.sha256(raw).hexdigest(),
                            "stem": stem,
                        }
                    )
                    if path == group_path:
                        group_value = strict_json(raw)
                    elif path == array_path:
                        array_value = strict_json(raw)
                    elif path in chunk_paths:
                        index = chunk_paths[path]
                        try:
                            decoded = bytes(decoder(raw))
                        except Exception as error:
                            raise VerificationError(f"chunk decode failed: {path}: {error}") from error
                        if len(decoded) != profile.decoded_chunk_bytes:
                            raise VerificationError(f"decoded chunk size/shape drift: {path}")
                        try:
                            memoryview(decoded).cast("H", shape=profile.decoded_shape)
                        except (TypeError, ValueError) as error:
                            raise VerificationError(f"decoded chunk shape drift: {path}") from error
                        try:
                            decoded_digest.update(stem.encode("ascii"))
                        except UnicodeEncodeError as error:
                            raise VerificationError(f"non-ASCII fixed stem: {stem}") from error
                        decoded_digest.update(index.to_bytes(2, "big"))
                        decoded_digest.update(decoded)
                        decoded_count += 1
                        decoded_bytes += len(decoded)
                if group_value is None or array_value is None:
                    raise VerificationError(f"Zarr metadata missing for {stem}")
                _validate_group_metadata(group_value, group_path)
                if canonical_json(array_value) != canonical_json(_expected_array_metadata(profile)):
                    raise VerificationError(f"Zarr array metadata/codec drift: {array_path}")

            if decoded_count != len(profile.stems) * profile.chunks_per_root:
                raise VerificationError("decoded chunk count drift")
            if decoded_bytes != profile.decoded_bytes:
                raise VerificationError("decoded aggregate byte count drift")
            if decoded_digest.hexdigest() != profile.decoded_sha256:
                raise VerificationError("decoded aggregate SHA-256 drift")
            inventory_records.sort(key=lambda item: str(item["path"]).encode())
            if (
                len(inventory_records) != len(expected)
                or sum(int(item["bytes"]) for item in inventory_records) != profile.stored_bytes
            ):
                raise VerificationError("inventory aggregate drift")
            inventory_by_path = {str(item["path"]): item for item in inventory_records}
            expected_image_view_paths = {_dataset_to_image_view_path(path) for path in expected}
            if set(inventory_by_path) != expected_image_view_paths:
                raise VerificationError("inventory path set drift")
            import_summary = _validate_import_receipt(
                receipt_value,
                receipt_raw,
                import_receipt,
                data_identity,
                expected,
                inventory_by_path,
                profile,
            )
            if set(file_identities) != set(expected):
                raise VerificationError("saved file identity set drift")
            for path, saved_identity in file_identities.items():
                if _identity(_stat_data_file(data_fd, path)) != saved_identity:
                    raise VerificationError(f"file identity changed after content verification: {path}")
            if _assert_exact_tree(data_fd, expected, profile) != image_view_full_identity:
                raise VerificationError("image-view identity changed during verification")
            inventory = {
                "files": inventory_records,
                "roots": list(profile.stems),
                "schema_version": INVENTORY_SCHEMA,
                "summary": {
                    "chunks": decoded_count,
                    "files": len(inventory_records),
                    "roots": len(profile.stems),
                    "stored_bytes": profile.stored_bytes,
                },
            }
            inventory_raw = canonical_json(inventory)
            ready_core = {
                # Source image-view evidence only.  A downstream image-only copy
                # must be accepted by content rehash, never by inode equality.
                "data_root_identity": image_view_identity,
                "decoded": {
                    "aggregate_sha256": decoded_digest.hexdigest(),
                    "bytes": decoded_bytes,
                    "chunks": decoded_count,
                    "order": (
                        "for each EVAL36_STEMS item and numeric chunk index: "
                        "stem ASCII, chunk index unsigned big-endian 2 bytes, decoded little-endian uint16 bytes"
                    ),
                },
                "digest_scope": (
                    "ready_content_sha256 hashes canonical JSON of all READY fields except "
                    "created_utc and ready_content_sha256"
                ),
                "import_receipt": import_summary,
                "inventory": {
                    "bytes": len(inventory_raw),
                    "path": "IMAGE_CONTENT_INVENTORY.json",
                    "sha256": hashlib.sha256(inventory_raw).hexdigest(),
                    "summary": inventory["summary"],
                },
                "manifest": {
                    "bytes": profile.manifest_bytes,
                    "lines": profile.manifest_lines,
                    "path": MANIFEST_NAME,
                    "sha256": profile.manifest_sha256,
                },
                "schema_version": READY_SCHEMA,
                "status": "READY",
                "verifier": {
                    "bytes": len(source_raw),
                    "reference": verifier_path.name,
                    "sha256": hashlib.sha256(source_raw).hexdigest(),
                },
            }
            ready_value = {
                **ready_core,
                "created_utc": now(),
                "ready_content_sha256": hashlib.sha256(canonical_json(ready_core)).hexdigest(),
            }
            ready_raw = canonical_json(ready_value)
            success_result = {
                "inventory": "IMAGE_CONTENT_INVENTORY.json",
                "ready": "READY.json",
                "ready_content_sha256": ready_value["ready_content_sha256"],
                "status": "PASS",
            }

            if not _same_path(data_absolute, data_fd) or _identity(data_info) != _identity(os.fstat(data_fd)):
                raise VerificationError("data-root identity changed before publication")
            if not _same_path(output_absolute, output_fd) or _identity(output_info) != _identity(os.fstat(output_fd)):
                raise VerificationError("output directory identity changed before publication")
            if os.listdir(output_fd):
                raise VerificationError("output directory changed before publication")

            owned: dict[str, tuple[int, int, int, int, int]] = {}
            try:
                inventory_temp, inventory_identity = _write_temp(
                    output_fd, "IMAGE_CONTENT_INVENTORY.json", inventory_raw
                )
                owned[inventory_temp] = inventory_identity
                ready_temp, ready_identity = _write_temp(output_fd, "READY.json", ready_raw)
                owned[ready_temp] = ready_identity

                if set(os.listdir(output_fd)) != set(owned):
                    raise VerificationError("temporary output membership drift")
                for name, expected_raw, expected_identity in (
                    (inventory_temp, inventory_raw, inventory_identity),
                    (ready_temp, ready_raw, ready_identity),
                ):
                    actual_raw, actual_info = _read_named_file(output_fd, name, name)
                    if (
                        _ownership_identity(actual_info) != expected_identity
                        or actual_raw != expected_raw
                        or hashlib.sha256(actual_raw).digest() != hashlib.sha256(expected_raw).digest()
                    ):
                        raise VerificationError(f"temporary output verification failed: {name}")
                if not _same_path(output_absolute, output_fd):
                    raise VerificationError("output directory path changed before publication")

                owned["IMAGE_CONTENT_INVENTORY.json"] = inventory_identity
                rename_noreplace(inventory_temp, "IMAGE_CONTENT_INVENTORY.json", directory_fd=output_fd)
                del owned[inventory_temp]
                os.fsync(output_fd)

                if set(os.listdir(output_fd)) != {"IMAGE_CONTENT_INVENTORY.json", ready_temp}:
                    raise VerificationError("pre-commit output membership drift")
                for name, expected_raw, expected_identity in (
                    ("IMAGE_CONTENT_INVENTORY.json", inventory_raw, inventory_identity),
                    (ready_temp, ready_raw, ready_identity),
                ):
                    actual_raw, actual_info = _read_named_file(output_fd, name, name)
                    if (
                        _ownership_identity(actual_info) != expected_identity
                        or actual_raw != expected_raw
                        or hashlib.sha256(actual_raw).digest() != hashlib.sha256(expected_raw).digest()
                    ):
                        raise VerificationError(f"pre-commit output verification failed: {name}")
                if not _same_path(output_absolute, output_fd):
                    raise VerificationError("output directory path changed at commit point")

                owned["READY.json"] = ready_identity
                rename_noreplace(ready_temp, "READY.json", directory_fd=output_fd)
                del owned[ready_temp]
                # This successful directory fsync is the final commit point.  No
                # fallible operation is permitted between it and the return.
                os.fsync(output_fd)
            except BaseException as error:
                _rollback_owned(output_fd, owned, error)
                raise
        return success_result
    finally:
        with contextlib.suppress(OSError):
            os.close(output_fd)
        with contextlib.suppress(OSError):
            os.close(data_fd)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise VerificationError(f"invalid arguments: {message}")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--import-receipt", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        result = verify_images(args.data_root, args.import_receipt, args.output_dir)
        print(canonical_json(result).decode(), end="")
        return 0
    except Exception as error:
        print(canonical_json({"error": type(error).__name__, "status": "FAIL"}).decode(), end="", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
