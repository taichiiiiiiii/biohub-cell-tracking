#!/usr/bin/env python3
"""Build the sealed single-file private Kaggle eval-36 bundle kernel.

The production CLI has one mutable value: the fresh local staging directory.
All Kaggle execution inputs, paths, metadata, and embedded byte pins are fixed.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import errno
import hashlib
import hmac
import importlib.metadata
import json
import os
import re
import stat
import subprocess
import sys
import zlib
from pathlib import Path
from typing import Any

COMPETITION = "biohub-cell-tracking-during-development"
KERNEL_ID = "taichiiiii/biohub-eval36-bundle-packer"
KERNEL_TITLE = "biohub-eval36-bundle-packer"
KERNEL_CODE_NAME = "eval36_bundle_kernel.py"
METADATA_NAME = "kernel-metadata.json"

PACKER_RELATIVE = Path("scripts/pack_eval36_zarr_bundles.py")
MANIFEST_RELATIVE = Path("data/manifest.csv")
PACKER_BYTES = 28_769
PACKER_SHA256 = "9dbe0126a9d288d01e8848b0e71e95c089d45cd926f980eacb3cfa3e6b802b6e"
PACKER_COMPRESSED_BYTES = 7_246
PACKER_COMPRESSED_SHA256 = "5a255ec3647314325d188002684875b6205c095cf4887e44575a96dbdd9468c9"
MANIFEST_BYTES = 1_187_624
MANIFEST_LINES = 24_887
MANIFEST_SHA256 = "6c1c59644daf7fe59458dc860f2e1783d1217be389a791ea54e1f611f5f848f4"
MANIFEST_COMPRESSED_BYTES = 157_421
MANIFEST_COMPRESSED_SHA256 = "981658c0d42b77005f4e7e0066322c6fe5eb5bdb2097a244871e76b8cb2741ed"
KAGGLE_VERSION = "2.2.4"
KAGGLESDK_VERSION = "0.1.37"

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
ARCHIVE_BYTES = (
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
TOTAL_ARCHIVE_BYTES = 6_104_616_960

_SELF_PATTERN = re.compile(rb'(?m)^SELF_SHA256 = "([0-9a-f]{64})"\n')
_ZERO_SHA256 = b"0" * 64
_MAX_INPUT_BYTES = 4 * 1024 * 1024


class KernelPreparationError(RuntimeError):
    """A fail-closed local package preparation error."""


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _open_directory_path(path: Path) -> int:
    absolute = path.absolute()
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def read_stable_regular(path: Path, *, expected_bytes: int, expected_sha256: str) -> bytes:
    """Read one bounded, single-link regular file through a held parent dirfd."""
    parent_fd = _open_directory_path(path.absolute().parent)
    descriptor: int | None = None
    try:
        before_path = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(before_path.st_mode)
            or before_path.st_nlink != 1
            or before_path.st_size != expected_bytes
            or before_path.st_size > _MAX_INPUT_BYTES
        ):
            raise KernelPreparationError("input type, link count, or byte count mismatch")
        descriptor = os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        before = os.fstat(descriptor)
        if _identity(before) != _identity(before_path):
            raise KernelPreparationError("input identity changed while opening")
        chunks: list[bytes] = []
        remaining = expected_bytes
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise KernelPreparationError("input ended early")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise KernelPreparationError("input grew while reading")
        after_fd = os.fstat(descriptor)
        after_path = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if _identity(after_fd) != _identity(before) or _identity(after_path) != _identity(before):
            raise KernelPreparationError("input changed while reading")
        payload = b"".join(chunks)
        if sha256_bytes(payload) != expected_sha256:
            raise KernelPreparationError("input SHA-256 mismatch")
        return payload
    except OSError as error:
        raise KernelPreparationError("input could not be read safely") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)


def verify_manifest_bytes(payload: bytes) -> None:
    if len(payload) != MANIFEST_BYTES or sha256_bytes(payload) != MANIFEST_SHA256:
        raise KernelPreparationError("manifest byte pin mismatch")
    if (
        not payload.endswith(b"\r\n")
        or payload.count(b"\r\n") != MANIFEST_LINES
        or payload.count(b"\r") != MANIFEST_LINES
        or payload.count(b"\n") != MANIFEST_LINES
        or len(payload.splitlines()) != MANIFEST_LINES
    ):
        raise KernelPreparationError("manifest CRLF contract mismatch")
    try:
        payload.decode("ascii")
    except UnicodeDecodeError as error:
        raise KernelPreparationError("manifest is not ASCII") from error


def _compressed(payload: bytes, *, expected_bytes: int, expected_sha256: str) -> bytes:
    compressed = zlib.compress(payload, level=9)
    if len(compressed) != expected_bytes or sha256_bytes(compressed) != expected_sha256:
        raise KernelPreparationError("zlib output drifted from the reviewed package contract")
    return compressed


def _base64_block(name: str, payload: bytes) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    lines = [f"{name} = ("]
    lines.extend(f'    "{encoded[index : index + 96]}"' for index in range(0, len(encoded), 96))
    lines.append(")")
    return "\n".join(lines)


def _kernel_template() -> str:
    return r'''#!/usr/bin/env python3
"""Sealed private CPU kernel for deterministic eval-36 Zarr bundles."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import types
import zlib
from pathlib import Path

SELF_SHA256 = "0000000000000000000000000000000000000000000000000000000000000000"
COMPETITION = "biohub-cell-tracking-during-development"
SOURCE_ROOT = Path("/kaggle/input/competitions/biohub-cell-tracking-during-development")
WORKING_ROOT = Path("/kaggle/working")
RUNTIME_ROOT = Path("/tmp/eval36-runtime")
OUTPUT_ROOT = Path("/kaggle/working/eval36-bundles")
RESULT_NAME = "KERNEL_RESULT.json"
RESULT_TEMP_NAME = ".KERNEL_RESULT.pending"
PACKER_BYTES = 28769
PACKER_SHA256 = "9dbe0126a9d288d01e8848b0e71e95c089d45cd926f980eacb3cfa3e6b802b6e"
PACKER_COMPRESSED_BYTES = 7246
PACKER_COMPRESSED_SHA256 = "5a255ec3647314325d188002684875b6205c095cf4887e44575a96dbdd9468c9"
MANIFEST_BYTES = 1187624
MANIFEST_LINES = 24887
MANIFEST_SHA256 = "6c1c59644daf7fe59458dc860f2e1783d1217be389a791ea54e1f611f5f848f4"
MANIFEST_COMPRESSED_BYTES = 157421
MANIFEST_COMPRESSED_SHA256 = "981658c0d42b77005f4e7e0066322c6fe5eb5bdb2097a244871e76b8cb2741ed"
TOTAL_ARCHIVE_BYTES = 6104616960
MIN_FREE_BYTES = 8252100608
ROOTS = (
    "6bba_09961292", "6bba_0e7c0d07", "6bba_12665c0e", "6bba_1d0d8384",
    "6bba_207c6aaf", "6bba_20852818", "6bba_2312ac41", "6bba_268e1230",
    "6bba_2819ca14", "6bba_32db13fc", "6bba_337b1b3a", "6bba_3abfe10a",
    "6bba_3c5691b6", "6bba_3db54e20", "6bba_3fda6b25",
)
ARCHIVE_BYTES = (
    400179200, 432660480, 358236160, 420177920, 392263680,
    379023360, 389611520, 339527680, 329328640, 477716480,
    459724800, 539504640, 364922880, 443351040, 378388480,
)
_SELF_PATTERN = re.compile(rb'(?m)^SELF_SHA256 = "([0-9a-f]{64})"\n')
_SHA_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_MAX_SELF_BYTES = 1024 * 1024

__PACKER_B64_BLOCK__

__MANIFEST_B64_BLOCK__


class KernelFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _CappedSink:
    def __init__(self, limit: int = 4096) -> None:
        self.limit = limit
        self.count = 0

    def write(self, value: str) -> int:
        if type(value) is not str:
            raise KernelFailure("EMBEDDED_INPUT")
        self.count += len(value.encode("utf-8", "replace"))
        if self.count > self.limit:
            raise KernelFailure("EMBEDDED_INPUT")
        return len(value)

    def flush(self) -> None:
        return None


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _open_directory_path(path: Path) -> int:
    absolute = path.absolute()
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_fd(descriptor: int, limit: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    count = 0
    while chunk := os.read(descriptor, min(1024 * 1024, limit + 1 - count)):
        chunks.append(chunk)
        count += len(chunk)
        if count > limit:
            raise KernelFailure("SELF_INTEGRITY")
    return b"".join(chunks)


def _verify_self_bytes(raw: bytes) -> tuple[str, str]:
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise KernelFailure("SELF_INTEGRITY")
    matches = list(_SELF_PATTERN.finditer(raw))
    if len(matches) != 1:
        raise KernelFailure("SELF_INTEGRITY")
    declared = matches[0].group(1).decode("ascii")
    normalized = raw[: matches[0].start(1)] + (b"0" * 64) + raw[matches[0].end(1) :]
    calculated = hashlib.sha256(normalized).hexdigest()
    if not hmac.compare_digest(declared, calculated):
        raise KernelFailure("SELF_INTEGRITY")
    return declared, hashlib.sha256(raw).hexdigest()


def _open_verified_self() -> dict[str, object]:
    path = Path(__file__).absolute()
    parent_fd = _open_directory_path(path.parent)
    descriptor: int | None = None
    try:
        before_path = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(before_path.st_mode)
            or before_path.st_nlink != 1
            or before_path.st_size > _MAX_SELF_BYTES
        ):
            raise KernelFailure("SELF_INTEGRITY")
        descriptor = os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        before = os.fstat(descriptor)
        if _identity(before) != _identity(before_path):
            raise KernelFailure("SELF_INTEGRITY")
        raw = _read_fd(descriptor, _MAX_SELF_BYTES)
        normalized_sha256, raw_sha256 = _verify_self_bytes(raw)
        if _identity(os.fstat(descriptor)) != _identity(before):
            raise KernelFailure("SELF_INTEGRITY")
        return {
            "descriptor": descriptor,
            "parent_fd": parent_fd,
            "name": path.name,
            "identity": _identity(before),
            "normalized_sha256": normalized_sha256,
            "raw_sha256": raw_sha256,
        }
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)
        raise


def _reverify_self(handle: dict[str, object]) -> None:
    descriptor = handle["descriptor"]
    parent_fd = handle["parent_fd"]
    if type(descriptor) is not int or type(parent_fd) is not int:
        raise KernelFailure("SELF_INTEGRITY")
    raw = _read_fd(descriptor, _MAX_SELF_BYTES)
    normalized_sha256, raw_sha256 = _verify_self_bytes(raw)
    current_fd = _identity(os.fstat(descriptor))
    current_path = _identity(os.stat(str(handle["name"]), dir_fd=parent_fd, follow_symlinks=False))
    if (
        current_fd != handle["identity"]
        or current_path != handle["identity"]
        or normalized_sha256 != handle["normalized_sha256"]
        or raw_sha256 != handle["raw_sha256"]
    ):
        raise KernelFailure("SELF_INTEGRITY")


def _decode_payload(
    encoded: str, compressed_bytes: int, compressed_sha256: str, raw_bytes: int, raw_sha256: str
) -> bytes:
    try:
        compressed = base64.b64decode(encoded, validate=True)
    except Exception as error:
        raise KernelFailure("EMBEDDED_INPUT") from error
    if len(compressed) != compressed_bytes or hashlib.sha256(compressed).hexdigest() != compressed_sha256:
        raise KernelFailure("EMBEDDED_INPUT")
    try:
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(compressed, raw_bytes + 1)
        raw += decompressor.flush()
    except zlib.error as error:
        raise KernelFailure("EMBEDDED_INPUT") from error
    if (
        len(raw) != raw_bytes
        or decompressor.unused_data
        or decompressor.unconsumed_tail
        or not decompressor.eof
        or hashlib.sha256(raw).hexdigest() != raw_sha256
    ):
        raise KernelFailure("EMBEDDED_INPUT")
    return raw


def _load_inputs() -> tuple[types.ModuleType, bytes]:
    packer_raw = _decode_payload(
        PACKER_B64, PACKER_COMPRESSED_BYTES, PACKER_COMPRESSED_SHA256, PACKER_BYTES, PACKER_SHA256
    )
    manifest_raw = _decode_payload(
        MANIFEST_B64, MANIFEST_COMPRESSED_BYTES, MANIFEST_COMPRESSED_SHA256, MANIFEST_BYTES, MANIFEST_SHA256
    )
    if (
        not manifest_raw.endswith(b"\r\n")
        or manifest_raw.count(b"\r\n") != MANIFEST_LINES
        or manifest_raw.count(b"\r") != MANIFEST_LINES
        or manifest_raw.count(b"\n") != MANIFEST_LINES
        or len(manifest_raw.splitlines()) != MANIFEST_LINES
    ):
        raise KernelFailure("EMBEDDED_INPUT")
    module_name = "embedded_eval36_packer"
    if module_name in sys.modules:
        raise KernelFailure("EMBEDDED_INPUT")
    module = types.ModuleType(module_name)
    module.__file__ = "<embedded_eval36_packer>"
    sys.modules[module_name] = module
    stdout = _CappedSink()
    stderr = _CappedSink()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exec(compile(packer_raw, module.__file__, "exec"), module.__dict__)
    except BaseException as error:
        sys.modules.pop(module_name, None)
        raise KernelFailure("EMBEDDED_INPUT") from error
    if stdout.count or stderr.count:
        sys.modules.pop(module_name, None)
        raise KernelFailure("EMBEDDED_INPUT")
    return module, manifest_raw


def _create_fresh_child(parent: Path, name: str) -> tuple[Path, int]:
    parent_fd = _open_directory_path(parent)
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        child_fd = os.open(name, flags, dir_fd=parent_fd)
        child_info = os.fstat(child_fd)
        path_info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(child_info.st_mode) or _identity(child_info) != _identity(path_info):
            os.close(child_fd)
            raise KernelFailure("ENVIRONMENT")
        return parent / name, child_fd
    except FileExistsError as error:
        raise KernelFailure("ENVIRONMENT") from error
    except OSError as error:
        raise KernelFailure("ENVIRONMENT") from error
    finally:
        os.close(parent_fd)


def _write_exclusive_at(directory_fd: int, name: str, payload: bytes) -> tuple[int, int, int, int, int, int, int]:
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
    except OSError as error:
        raise KernelFailure("PUBLICATION") from error
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise KernelFailure("PUBLICATION")
            view = view[written:]
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != len(payload):
            raise KernelFailure("PUBLICATION")
        return _identity(info)
    finally:
        os.close(descriptor)


def _stable_hash_at(directory_fd: int, name: str) -> tuple[int, str, tuple[int, int, int, int, int, int, int]]:
    try:
        before_path = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(before_path.st_mode) or before_path.st_nlink != 1:
            raise KernelFailure("OUTPUT_INTEGRITY")
        descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
    except OSError as error:
        raise KernelFailure("OUTPUT_INTEGRITY") from error
    try:
        before = os.fstat(descriptor)
        if _identity(before) != _identity(before_path):
            raise KernelFailure("OUTPUT_INTEGRITY")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after_fd = os.fstat(descriptor)
        after_path = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if _identity(after_fd) != _identity(before) or _identity(after_path) != _identity(before):
            raise KernelFailure("OUTPUT_INTEGRITY")
        return before.st_size, digest.hexdigest(), _identity(before)
    finally:
        os.close(descriptor)


def _directory_identity(info: os.stat_result) -> tuple[int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode)


def _close_quiet(descriptor: object) -> None:
    if type(descriptor) is int:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _validate_results(results: object, output_fd: int, output_identity: tuple[int, int, int]):
    if type(results) is not list or len(results) != len(ROOTS):
        raise KernelFailure("OUTPUT_INTEGRITY")
    expected_names = {f"{root}.tar" for root in ROOTS}
    if set(os.listdir(output_fd)) != expected_names:
        raise KernelFailure("OUTPUT_INTEGRITY")
    sealed: list[dict[str, object]] = []
    total = 0
    for index, (root, expected_bytes) in enumerate(zip(ROOTS, ARCHIVE_BYTES, strict=True)):
        item = results[index]
        name = f"{root}.tar"
        if (
            type(item) is not dict
            or set(item) != {"archive", "bytes", "root", "sha256"}
            or type(item["archive"]) is not str
            or type(item["bytes"]) is not int
            or type(item["root"]) is not str
            or type(item["sha256"]) is not str
            or item["archive"] != name
            or item["bytes"] != expected_bytes
            or item["root"] != root
            or _SHA_PATTERN.fullmatch(item["sha256"]) is None
        ):
            raise KernelFailure("OUTPUT_INTEGRITY")
        size, digest, _ = _stable_hash_at(output_fd, name)
        if size != expected_bytes or not hmac.compare_digest(digest, item["sha256"]):
            raise KernelFailure("OUTPUT_INTEGRITY")
        sealed.append({"archive": name, "bytes": size, "root": root, "sha256": digest})
        total += size
    if total != TOTAL_ARCHIVE_BYTES or _directory_identity(os.fstat(output_fd)) != output_identity:
        raise KernelFailure("OUTPUT_INTEGRITY")
    return sealed


def _run() -> bytes:
    self_handle: dict[str, object] | None = None
    working_fd: int | None = None
    runtime_fd: int | None = None
    output_fd: int | None = None
    try:
        self_handle = _open_verified_self()
        if len(sys.argv) != 1:
            raise KernelFailure("ARGUMENTS")
        try:
            source_fd = _open_directory_path(SOURCE_ROOT)
            os.close(source_fd)
            working_fd = _open_directory_path(WORKING_ROOT)
        except OSError as error:
            raise KernelFailure("ENVIRONMENT") from error
        filesystem = os.fstatvfs(working_fd)
        free_bytes = filesystem.f_bavail * filesystem.f_frsize
        if free_bytes < MIN_FREE_BYTES:
            raise KernelFailure("RESOURCE")
        packer, manifest_raw = _load_inputs()
        runtime_path, runtime_fd = _create_fresh_child(Path("/tmp"), RUNTIME_ROOT.name)
        manifest_name = "manifest.csv"
        _write_exclusive_at(runtime_fd, manifest_name, manifest_raw)
        os.fsync(runtime_fd)
        output_path, output_fd = _create_fresh_child(WORKING_ROOT, OUTPUT_ROOT.name)
        output_identity = _directory_identity(os.fstat(output_fd))
        if _directory_identity(os.stat(OUTPUT_ROOT.name, dir_fd=working_fd, follow_symlinks=False)) != output_identity:
            raise KernelFailure("ENVIRONMENT")
        stdout = _CappedSink()
        stderr = _CappedSink()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                results = packer.pack_bundles(runtime_path / manifest_name, SOURCE_ROOT, output_path)
        except BaseException as error:
            raise KernelFailure("PACKER") from error
        if stdout.count or stderr.count:
            raise KernelFailure("PACKER")
        sealed = _validate_results(results, output_fd, output_identity)
        receipt = {
            "archives": sealed,
            "competition": COMPETITION,
            "kernel_raw_sha256": self_handle["raw_sha256"],
            "kernel_self_sha256": self_handle["normalized_sha256"],
            "manifest": {"bytes": MANIFEST_BYTES, "lines": MANIFEST_LINES, "sha256": MANIFEST_SHA256},
            "packer": {"bytes": PACKER_BYTES, "sha256": PACKER_SHA256},
            "schema_version": "biohub.eval36_kernel_pack.v1",
            "status": "PASS",
            "total_archive_bytes": TOTAL_ARCHIVE_BYTES,
        }
        receipt_bytes = _canonical_json(receipt)
        _write_exclusive_at(output_fd, RESULT_TEMP_NAME, receipt_bytes)
        os.fsync(output_fd)
        if set(os.listdir(output_fd)) != {*(f"{root}.tar" for root in ROOTS), RESULT_TEMP_NAME}:
            raise KernelFailure("PUBLICATION")
        result_size, result_sha256, _ = _stable_hash_at(output_fd, RESULT_TEMP_NAME)
        if result_size != len(receipt_bytes) or result_sha256 != hashlib.sha256(receipt_bytes).hexdigest():
            raise KernelFailure("PUBLICATION")
        _reverify_self(self_handle)
        if (
            _directory_identity(os.fstat(output_fd)) != output_identity
            or _directory_identity(os.stat(OUTPUT_ROOT.name, dir_fd=working_fd, follow_symlinks=False))
            != output_identity
        ):
            raise KernelFailure("PUBLICATION")
        try:
            packer.rename_noreplace(
                RESULT_TEMP_NAME,
                RESULT_NAME,
                source_dir_fd=output_fd,
                destination_dir_fd=output_fd,
            )
        except BaseException as error:
            raise KernelFailure("PUBLICATION") from error
        return receipt_bytes
    finally:
        _close_quiet(output_fd)
        _close_quiet(runtime_fd)
        _close_quiet(working_fd)
        if self_handle is not None:
            _close_quiet(self_handle.get("descriptor"))
            _close_quiet(self_handle.get("parent_fd"))


def _main() -> int:
    try:
        payload = _run()
    except BaseException as error:
        if isinstance(error, KernelFailure):
            failure_class = error.code
        elif isinstance(error, (KeyboardInterrupt, SystemExit)):
            failure_class = "INTERRUPTED"
        else:
            failure_class = "INTERNAL"
        if failure_class not in {
            "ARGUMENTS", "EMBEDDED_INPUT", "ENVIRONMENT", "INTERNAL", "INTERRUPTED",
            "OUTPUT_INTEGRITY", "PACKER", "PUBLICATION", "RESOURCE", "SELF_INTEGRITY",
        }:
            failure_class = "INTERNAL"
        sys.stderr.buffer.write(_canonical_json({"failure_class": failure_class, "status": "FAIL"}))
        return 1
    sys.stdout.buffer.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
'''


def normalize_kernel_source(source: bytes) -> tuple[bytes, str]:
    if source.startswith(b"\xef\xbb\xbf") or b"\r" in source or not source.endswith(b"\n"):
        raise KernelPreparationError("generated source encoding or newline drift")
    matches = list(_SELF_PATTERN.finditer(source))
    if len(matches) != 1:
        raise KernelPreparationError("generated source must contain exactly one self-hash sentinel")
    normalized = source[: matches[0].start(1)] + _ZERO_SHA256 + source[matches[0].end(1) :]
    return normalized, matches[0].group(1).decode("ascii")


def verify_kernel_source(source: bytes) -> dict[str, str]:
    normalized, declared = normalize_kernel_source(source)
    calculated = sha256_bytes(normalized)
    if declared != calculated:
        raise KernelPreparationError("generated source self-hash mismatch")
    return {"raw_sha256": sha256_bytes(source), "self_sha256": calculated}


def build_kernel_source(packer_raw: bytes, manifest_raw: bytes) -> bytes:
    if len(packer_raw) != PACKER_BYTES or sha256_bytes(packer_raw) != PACKER_SHA256:
        raise KernelPreparationError("packer byte pin mismatch")
    verify_manifest_bytes(manifest_raw)
    packer_compressed = _compressed(
        packer_raw,
        expected_bytes=PACKER_COMPRESSED_BYTES,
        expected_sha256=PACKER_COMPRESSED_SHA256,
    )
    manifest_compressed = _compressed(
        manifest_raw,
        expected_bytes=MANIFEST_COMPRESSED_BYTES,
        expected_sha256=MANIFEST_COMPRESSED_SHA256,
    )
    source_text = _kernel_template().replace("__PACKER_B64_BLOCK__", _base64_block("PACKER_B64", packer_compressed))
    source_text = source_text.replace("__MANIFEST_B64_BLOCK__", _base64_block("MANIFEST_B64", manifest_compressed))
    if "__PACKER_B64_BLOCK__" in source_text or "__MANIFEST_B64_BLOCK__" in source_text:
        raise KernelPreparationError("generated source placeholder survived")
    source = source_text.encode("utf-8")
    normalized, declared = normalize_kernel_source(source)
    if declared != "0" * 64:
        raise KernelPreparationError("self-hash template was not zeroed")
    digest = sha256_bytes(normalized)
    match = _SELF_PATTERN.search(source)
    if match is None:
        raise KernelPreparationError("self-hash sentinel disappeared")
    sealed = source[: match.start(1)] + digest.encode("ascii") + source[match.end(1) :]
    verify_kernel_source(sealed)
    compile(sealed, KERNEL_CODE_NAME, "exec")
    return sealed


def kernel_metadata() -> dict[str, object]:
    return {
        "id": KERNEL_ID,
        "title": KERNEL_TITLE,
        "code_file": KERNEL_CODE_NAME,
        "language": "python",
        "kernel_type": "script",
        "is_private": "true",
        "enable_gpu": "false",
        "enable_tpu": "false",
        "enable_internet": "false",
        "dataset_sources": [],
        "competition_sources": [COMPETITION],
        "kernel_sources": [],
        "model_sources": [],
    }


def _directory_identity(info: os.stat_result) -> tuple[int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode)


def _close_quiet(descriptor: object) -> None:
    if type(descriptor) is int:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _open_child_directory(parent_fd: int, name: str) -> tuple[int, tuple[int, int, int]]:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, dir_fd=parent_fd)
    info = os.fstat(descriptor)
    path_info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    identity = _directory_identity(info)
    if not stat.S_ISDIR(info.st_mode) or _directory_identity(path_info) != identity:
        os.close(descriptor)
        raise KernelPreparationError("staging directory identity mismatch")
    return descriptor, identity


def _create_child_directory(parent_fd: int, name: str) -> tuple[int, tuple[int, int, int]]:
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent_fd)
    except FileExistsError as error:
        raise KernelPreparationError("refusing to reuse staging directory") from error
    except OSError as error:
        raise KernelPreparationError("staging directory could not be created") from error
    return _open_child_directory(parent_fd, name)


def _write_exclusive_at(directory_fd: int, name: str, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
    except OSError as error:
        raise KernelPreparationError("staged file could not be created exclusively") from error
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise KernelPreparationError("short staging write")
            view = view[written:]
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != len(payload):
            raise KernelPreparationError("staged file type, link count, or byte count mismatch")
    finally:
        os.close(descriptor)


def _read_stable_at(directory_fd: int, name: str, expected: bytes) -> bytes:
    descriptor: int | None = None
    try:
        before_path = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(before_path.st_mode) or before_path.st_nlink != 1 or before_path.st_size != len(expected):
            raise KernelPreparationError("staged file identity mismatch")
        descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
        before = os.fstat(descriptor)
        if _identity(before) != _identity(before_path):
            raise KernelPreparationError("staged file changed while opening")
        chunks: list[bytes] = []
        remaining = len(expected)
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise KernelPreparationError("staged file ended early")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise KernelPreparationError("staged file grew while reading")
        after_fd = os.fstat(descriptor)
        after_path = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        payload = b"".join(chunks)
        if (
            _identity(after_fd) != _identity(before)
            or _identity(after_path) != _identity(before)
            or not hmac.compare_digest(payload, expected)
        ):
            raise KernelPreparationError("staged file bytes or identity mismatch")
        return payload
    except OSError as error:
        raise KernelPreparationError("staged file could not be read safely") from error
    finally:
        _close_quiet(descriptor)


def _rename_noreplace_at(directory_fd: int, source: str, destination: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if sys.platform == "darwin":
        function = libc.renameatx_np
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = function(directory_fd, source_bytes, directory_fd, destination_bytes, 0x00000004)
    elif sys.platform.startswith("linux"):
        try:
            function = libc.renameat2
        except AttributeError as error:
            raise KernelPreparationError("atomic no-replace rename is unavailable") from error
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = function(directory_fd, source_bytes, directory_fd, destination_bytes, 1)
    else:
        raise KernelPreparationError("atomic no-replace rename is unsupported")
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise KernelPreparationError("staging publication destination already exists")
        raise KernelPreparationError("staging publication rename failed")


def _require_directory_membership(
    parent_fd: int, name: str, descriptor: int, expected_identity: tuple[int, int, int]
) -> None:
    current_fd = _directory_identity(os.fstat(descriptor))
    current_path = _directory_identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False))
    if current_fd != expected_identity or current_path != expected_identity:
        raise KernelPreparationError("staging directory membership changed")


def _require_child(output_dir: Path, allowed_root: Path) -> None:
    absolute = output_dir.absolute()
    root = allowed_root.absolute()
    if absolute.parent != root or not absolute.name or absolute.name in {".", ".."}:
        raise KernelPreparationError("output directory must be a fresh direct child of the pinned staging root")


def _git_state(repo_root: Path) -> tuple[str, str]:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise KernelPreparationError("git state could not be verified") from error
    if not re.fullmatch(r"[0-9a-f]{40}", head) or not branch or status:
        raise KernelPreparationError("staging requires a clean named-branch commit")
    if branch in {"main", "master", "develop"}:
        raise KernelPreparationError("staging is forbidden on protected or integration branches")
    return head, branch


def _versions() -> dict[str, str]:
    try:
        versions = {
            "kaggle": importlib.metadata.version("kaggle"),
            "kagglesdk": importlib.metadata.version("kagglesdk"),
        }
    except importlib.metadata.PackageNotFoundError as error:
        raise KernelPreparationError("pinned Kaggle packages are unavailable") from error
    if versions != {"kaggle": KAGGLE_VERSION, "kagglesdk": KAGGLESDK_VERSION}:
        raise KernelPreparationError("Kaggle package version drift")
    return versions


def stage_package(
    output_dir: Path,
    *,
    repo_root: Path,
    git_head: str | None = None,
    git_branch: str | None = None,
    versions: dict[str, str] | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.absolute()
    allowed_root = repo_root / "outputs/local/eval36_kernel"
    allowed_parent = allowed_root.parent
    output_dir = output_dir.absolute()
    _require_child(output_dir, allowed_root)
    packer_raw = read_stable_regular(
        repo_root / PACKER_RELATIVE,
        expected_bytes=PACKER_BYTES,
        expected_sha256=PACKER_SHA256,
    )
    manifest_raw = read_stable_regular(
        repo_root / MANIFEST_RELATIVE,
        expected_bytes=MANIFEST_BYTES,
        expected_sha256=MANIFEST_SHA256,
    )
    verify_manifest_bytes(manifest_raw)
    source = build_kernel_source(packer_raw, manifest_raw)
    metadata_bytes = canonical_json_bytes(kernel_metadata())
    if git_head is None or git_branch is None:
        git_head, git_branch = _git_state(repo_root)
    if versions is None:
        versions = _versions()
    if not re.fullmatch(r"[0-9a-f]{40}", git_head) or not git_branch or git_branch in {"main", "master", "develop"}:
        raise KernelPreparationError("invalid injected git provenance")
    if versions != {"kaggle": KAGGLE_VERSION, "kagglesdk": KAGGLESDK_VERSION}:
        raise KernelPreparationError("invalid injected Kaggle version provenance")
    source_hashes = verify_kernel_source(source)

    allowed_parent_fd: int | None = None
    allowed_fd: int | None = None
    output_fd: int | None = None
    package_fd: int | None = None
    try:
        allowed_parent_fd = _open_directory_path(allowed_parent)
        try:
            os.mkdir(allowed_root.name, mode=0o700, dir_fd=allowed_parent_fd)
            os.fsync(allowed_parent_fd)
        except FileExistsError:
            pass
        allowed_fd, allowed_identity = _open_child_directory(allowed_parent_fd, allowed_root.name)
        output_fd, output_identity = _create_child_directory(allowed_fd, output_dir.name)
        package_fd, package_identity = _create_child_directory(output_fd, "package")
        _write_exclusive_at(output_fd, "INCOMPLETE", b"staging\n")
        _write_exclusive_at(package_fd, KERNEL_CODE_NAME, source)
        _write_exclusive_at(package_fd, METADATA_NAME, metadata_bytes)
        if set(os.listdir(package_fd)) != {KERNEL_CODE_NAME, METADATA_NAME}:
            raise KernelPreparationError("package file set mismatch")
        staged_source = _read_stable_at(package_fd, KERNEL_CODE_NAME, source)
        staged_metadata = _read_stable_at(package_fd, METADATA_NAME, metadata_bytes)
        if verify_kernel_source(staged_source) != source_hashes or json.loads(staged_metadata) != kernel_metadata():
            raise KernelPreparationError("staged package verification mismatch")
        receipt = {
            "allowed_next_action": "PRIVATE_CPU_PUSH_AFTER_INDEPENDENT_HASH_REVIEW",
            "branch": git_branch,
            "competition": COMPETITION,
            "git_head": git_head,
            "inputs": {
                "manifest": {"bytes": MANIFEST_BYTES, "lines": MANIFEST_LINES, "sha256": MANIFEST_SHA256},
                "packer": {"bytes": PACKER_BYTES, "sha256": PACKER_SHA256},
            },
            "kernel_id": KERNEL_ID,
            "package": {
                KERNEL_CODE_NAME: {
                    "bytes": len(source),
                    "raw_sha256": source_hashes["raw_sha256"],
                    "self_sha256": source_hashes["self_sha256"],
                },
                METADATA_NAME: {"bytes": len(metadata_bytes), "sha256": sha256_bytes(metadata_bytes)},
            },
            "schema_version": "biohub.eval36_kernel_staging.v1",
            "status": "STAGED_READY_FOR_PRIVATE_CPU_REVIEW",
            "tool_versions": versions,
        }
        receipt_bytes = canonical_json_bytes(receipt)
        _write_exclusive_at(output_fd, "STAGING_RECEIPT.json", receipt_bytes)
        if _read_stable_at(output_fd, "STAGING_RECEIPT.json", receipt_bytes) != receipt_bytes:
            raise KernelPreparationError("staging receipt verification mismatch")
        os.fsync(package_fd)
        os.fsync(output_fd)
        os.fsync(allowed_fd)
        _require_directory_membership(output_fd, "package", package_fd, package_identity)
        _require_directory_membership(allowed_fd, output_dir.name, output_fd, output_identity)
        _require_directory_membership(allowed_parent_fd, allowed_root.name, allowed_fd, allowed_identity)

        os.unlink("INCOMPLETE", dir_fd=output_fd)
        ready = {
            "allowed_next_action": receipt["allowed_next_action"],
            "package_code_sha256": source_hashes["raw_sha256"],
            "package_metadata_sha256": sha256_bytes(metadata_bytes),
            "receipt_sha256": sha256_bytes(receipt_bytes),
            "schema_version": "biohub.eval36_kernel_ready.v1",
            "status": "READY",
        }
        ready_bytes = canonical_json_bytes(ready)
        ready_temp_name = ".READY.pending"
        _write_exclusive_at(output_fd, ready_temp_name, ready_bytes)
        if set(os.listdir(output_fd)) != {"package", "STAGING_RECEIPT.json", ready_temp_name}:
            raise KernelPreparationError("staging output file set mismatch")
        if (
            _read_stable_at(package_fd, KERNEL_CODE_NAME, source) != source
            or _read_stable_at(package_fd, METADATA_NAME, metadata_bytes) != metadata_bytes
            or _read_stable_at(output_fd, "STAGING_RECEIPT.json", receipt_bytes) != receipt_bytes
            or _read_stable_at(output_fd, ready_temp_name, ready_bytes) != ready_bytes
        ):
            raise KernelPreparationError("staging dependency changed before READY")
        _require_directory_membership(output_fd, "package", package_fd, package_identity)
        _require_directory_membership(allowed_fd, output_dir.name, output_fd, output_identity)
        _require_directory_membership(allowed_parent_fd, allowed_root.name, allowed_fd, allowed_identity)
        os.fsync(package_fd)
        os.fsync(output_fd)
        os.fsync(allowed_fd)
        _require_directory_membership(output_fd, "package", package_fd, package_identity)
        _require_directory_membership(allowed_fd, output_dir.name, output_fd, output_identity)
        _require_directory_membership(allowed_parent_fd, allowed_root.name, allowed_fd, allowed_identity)
        _rename_noreplace_at(output_fd, ready_temp_name, "READY.json")
        return receipt
    finally:
        _close_quiet(package_fd)
        _close_quiet(output_fd)
        _close_quiet(allowed_fd)
        _close_quiet(allowed_parent_fd)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    try:
        result = stage_package(args.output_dir, repo_root=repo_root)
        sys.stdout.buffer.write(canonical_json_bytes(result))
        return 0
    except (KernelPreparationError, OSError, ValueError, TypeError) as error:
        failure = {
            "error_class": type(error).__name__,
            "schema_version": "biohub.eval36_kernel_staging_failure.v1",
            "status": "FAIL",
        }
        sys.stderr.buffer.write(canonical_json_bytes(failure))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
