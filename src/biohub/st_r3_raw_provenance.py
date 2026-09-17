"""Seal and revalidate the frozen E22 raw-prediction history for ST-R3.

This module deliberately makes a narrow claim.  The retained Kaggle log and
runtime receipts are byte-pinned and internally consistent with the frozen raw
GEFF tree, but checkpoint bytes are outside this receipt's verified authority.
A receipt therefore always remains ``LEGACY_HISTORY_UNVERIFIED`` and never
claims cryptographic checkpoint-to-output provenance or a training-loss result.

Production entry points have no caller-selectable repository, evidence, or raw
paths.  They operate only in the canonical checkout and publish exactly two
canonical JSON receipts in a fresh, direct child of the fixed output parent.
"""

from __future__ import annotations

import contextlib
import ctypes
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
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = "biohub.st_r3.raw_provenance_receipt.v1"
STATUS = "LEGACY_HISTORY_UNVERIFIED"
REMAINING_HOLD = "HOLD_RAW_PROVENANCE_UNVERIFIED"
CANONICAL_REPO_ROOT = Path("/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking")

READ_SIZE = 1024 * 1024
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_RECEIPT_BYTES = 64 * 1024
OFFICIAL_OID = "075fc5f5a52d11077f9dc2b074644618f26939e2"
PRODUCTION_OFFICIAL_TRACKED_ENTRIES = 49
PRIMARY_WEIGHT_SHA256 = "12f6881ee3620a831697ca098ff8f48e687a24225f4e048b538deec3562fe771"
SECONDARY_WEIGHT_SHA256 = "9bac2fa0dadc4a6fc1899e0caf187f4b553e0a7cd90ba1261a68b35ffe9e305f"
DEEPCENTER_SHA256 = "8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0"
SUPPORT_MANIFEST_SHA256 = "978b626d1fd1e7397435a437dfe68691defe1572fc3c20e61012d7c9b52ed029"

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

_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_OID_RE = re.compile(r"[0-9a-f]{40}\Z")
_RUN_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+@-]{0,127}\Z")
_UTC_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")


class RawProvenanceError(RuntimeError):
    """The legacy provenance evidence cannot safely support a receipt."""


class PublicationAmbiguityError(RawProvenanceError):
    """Publication or owned-staging rollback could not be proven durable."""


@dataclass(frozen=True)
class FilePin:
    relative: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class Authority:
    output_parent_relative: str
    raw_root_relative: str
    raw_manifest_relative: str
    stems: tuple[str, ...]
    raw_files: int
    raw_bytes: int
    raw_records_sha256: str
    raw_legacy_tree_sha256: str
    download_manifest: FilePin
    runtime_integrity: FilePin
    derivation_log: FilePin
    official_oid: str
    primary_weight_sha256: str
    secondary_weight_sha256: str
    deepcenter_sha256: str
    support_manifest_sha256: str
    builder_sources: tuple[str, ...]


PRODUCTION_AUTHORITY = Authority(
    output_parent_relative="outputs/local/st_r3_raw_provenance",
    raw_root_relative=(
        "outputs/kaggle/e22_bidir030_eval36_raw/tracking_repo/predictions/unknown/unet_transformer_val/split_0"
    ),
    raw_manifest_relative=("../e22_bidir030_eval36_raw/tracking_repo/predictions/unknown/unet_transformer_val/split_0"),
    stems=EVAL36_STEMS,
    raw_files=1_188,
    raw_bytes=10_090_215,
    raw_records_sha256="d49541301e7b76afe65a5ba61f5d8f8b01c14c39c256455b7cdd5af9a7564cbb",
    raw_legacy_tree_sha256="fa34dcf5f20054f240d750bd2225dd08fc6cf645e094cd9596ce2faf4bbf0ca2",
    download_manifest=FilePin(
        "outputs/kaggle/e22_bidir030_eval36_reference/DOWNLOAD_MANIFEST.json",
        3_524,
        "1f567e2520cc75536886296c1b88724ea2c2776cd2aa6b52ceaaac6bca8ac12b",
    ),
    runtime_integrity=FilePin(
        "outputs/kaggle/e22_bidir030_eval36_reference/bidirectional_production_runtime_integrity.json",
        2_387,
        "ae41130ee035d3ddcbaf2d0977f721429a52ffda8133fe1b877f51de5926278d",
    ),
    derivation_log=FilePin(
        "outputs/kaggle/e22_bidir030_eval36_raw/biohub-eval-train-raw.log",
        391_952,
        "eaf6749aafacfc87b5c9ec953add016adff61d5a3da8d3112385590029ce5129",
    ),
    official_oid=OFFICIAL_OID,
    primary_weight_sha256=PRIMARY_WEIGHT_SHA256,
    secondary_weight_sha256=SECONDARY_WEIGHT_SHA256,
    deepcenter_sha256=DEEPCENTER_SHA256,
    support_manifest_sha256=SUPPORT_MANIFEST_SHA256,
    builder_sources=("src/biohub/st_r3_raw_provenance.py", "scripts/st_r3_raw_provenance.py"),
)

PRIMARY_RECEIPT = "PRIMARY_RAW_PROVENANCE.json"
SECONDARY_RECEIPT = "SECONDARY_RAW_PROVENANCE.json"
RECEIPT_NAMES = (PRIMARY_RECEIPT, SECONDARY_RECEIPT)


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
class PinnedRead:
    raw: bytes
    identity: tuple[int, int, int, int, int, int, int]


@dataclass(frozen=True)
class RawSnapshot:
    records: tuple[tuple[str, int, str], ...]
    identities: tuple[tuple[str, tuple[int, int, int, int, int, int, int]], ...]
    root_identity: tuple[int, int, int, int, int, int, int]
    records_sha256: str
    legacy_tree_sha256: str
    file_count: int
    total_bytes: int


@dataclass(frozen=True)
class CollectedAuthority:
    git: GitState
    raw: RawSnapshot
    download: PinnedRead
    runtime: PinnedRead
    log: PinnedRead


@dataclass(frozen=True)
class _OwnedStaging:
    name: str
    identity: tuple[int, int]
    files: tuple[tuple[str, tuple[int, int]], ...]


def canonical_json_bytes(value: object) -> bytes:
    """Return the sole accepted receipt/output encoding."""
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _strict_json_bytes(raw: bytes, *, canonical: bool) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise RawProvenanceError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> object:
        raise RawProvenanceError("non-finite JSON value")

    def finite_float(value: str) -> float:
        result = float(value)
        if not math.isfinite(result):
            raise RawProvenanceError("non-finite JSON float")
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
            parse_float=finite_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RawProvenanceError("invalid JSON") from error
    if canonical and canonical_json_bytes(value) != raw:
        raise RawProvenanceError("noncanonical JSON")
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


def _ownership(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _directory_handle_identity(info: os.stat_result) -> tuple[int, int, int]:
    return info.st_dev, info.st_ino, info.st_mode


def _safe_relative(value: object) -> str:
    if type(value) is not str or not value or "\x00" in value or "\\" in value:
        raise RawProvenanceError("unsafe relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(part in {"", ".", ".."} for part in path.parts):
        raise RawProvenanceError("unsafe relative path")
    return value


def _safe_name(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\x00" in value:
        raise RawProvenanceError("unsafe path component")
    return value


def _exact_child_name(parent_fd: int, name: str, *, allow_missing: bool) -> bool:
    _safe_name(name)
    matches = [entry for entry in os.listdir(parent_fd) if entry.casefold() == name.casefold()]
    if not matches:
        if allow_missing:
            return False
        raise RawProvenanceError("required path component is absent")
    if matches != [name]:
        raise RawProvenanceError("case-colliding or non-exact path component")
    return True


def _open_absolute_directory(path: Path) -> int:
    absolute = Path(os.path.abspath(path))
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            _exact_child_name(current, part, allow_missing=False)
            parent_before = _identity(os.fstat(current))
            next_fd = os.open(part, flags, dir_fd=current)
            keep_next = False
            try:
                path_info = os.stat(part, dir_fd=current, follow_symlinks=False)
                if not stat.S_ISDIR(path_info.st_mode) or _identity(path_info) != _identity(os.fstat(next_fd)):
                    raise RawProvenanceError("directory identity mismatch")
                if parent_before != _identity(os.fstat(current)):
                    raise RawProvenanceError("parent directory changed")
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
    parts = PurePosixPath(_safe_relative(relative)).parts if isinstance(relative, str) else relative
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current = os.dup(root_fd)
    try:
        for part in parts:
            _safe_name(part)
            _exact_child_name(current, part, allow_missing=False)
            parent_before = _identity(os.fstat(current))
            next_fd = os.open(part, flags, dir_fd=current)
            keep_next = False
            try:
                path_info = os.stat(part, dir_fd=current, follow_symlinks=False)
                if not stat.S_ISDIR(path_info.st_mode) or _identity(path_info) != _identity(os.fstat(next_fd)):
                    raise RawProvenanceError("directory identity mismatch")
                if parent_before != _identity(os.fstat(current)):
                    raise RawProvenanceError("parent directory changed")
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


def _read_fd(fd: int, *, max_bytes: int | None) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, READ_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if max_bytes is not None and total > max_bytes:
            raise RawProvenanceError("file exceeds maximum accepted size")
        chunks.append(chunk)
    return b"".join(chunks)


def _read_named_regular(parent_fd: int, name: str, *, max_bytes: int | None = None) -> PinnedRead:
    _safe_name(name)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    parent_before = _identity(os.fstat(parent_fd))
    try:
        path_before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(path_before.st_mode) or path_before.st_nlink != 1:
            raise RawProvenanceError("file is not an isolated regular file")
        fd = os.open(name, flags, dir_fd=parent_fd)
    except RawProvenanceError:
        raise
    except OSError as error:
        raise RawProvenanceError("cannot safely open regular file") from error
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or _identity(before) != _identity(path_before):
            raise RawProvenanceError("file is not an isolated regular file")
        raw = _read_fd(fd, max_bytes=max_bytes)
        after = os.fstat(fd)
        path_after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            len(raw) != before.st_size
            or _identity(before) != _identity(after)
            or _identity(after) != _identity(path_after)
            or parent_before != _identity(os.fstat(parent_fd))
        ):
            raise RawProvenanceError("file changed while reading")
        return PinnedRead(raw=raw, identity=_identity(after))
    finally:
        os.close(fd)


def _read_repo_regular(root_fd: int, relative: str, *, max_bytes: int | None = None) -> PinnedRead:
    parts = PurePosixPath(_safe_relative(relative)).parts
    parent_fd = _open_relative_directory(root_fd, tuple(parts[:-1]))
    try:
        return _read_named_regular(parent_fd, parts[-1], max_bytes=max_bytes)
    finally:
        os.close(parent_fd)


def _walk_directory(
    directory_fd: int,
    prefix: str,
    records: list[tuple[str, int, str]],
    identities: list[tuple[str, tuple[int, int, int, int, int, int, int]]],
    *,
    max_file_bytes: int | None = None,
) -> None:
    before = _identity(os.fstat(directory_fd))
    names = os.listdir(directory_fd)
    folded: dict[str, str] = {}
    for name in names:
        _safe_name(name)
        previous = folded.setdefault(name.casefold(), name)
        if previous != name:
            raise RawProvenanceError("raw tree contains a case collision")
    for name in sorted(names):
        relative = f"{prefix}/{name}" if prefix else name
        path_info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(path_info.st_mode):
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            child_fd = os.open(name, flags, dir_fd=directory_fd)
            try:
                child_before = _identity(os.fstat(child_fd))
                if child_before != _identity(path_info):
                    raise RawProvenanceError("raw directory identity mismatch")
                identities.append((relative, child_before))
                _walk_directory(
                    child_fd,
                    relative,
                    records,
                    identities,
                    max_file_bytes=max_file_bytes,
                )
                child_after = _identity(os.fstat(child_fd))
                path_after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if child_before != child_after or child_after != _identity(path_after):
                    raise RawProvenanceError("raw directory changed while scanning")
            finally:
                os.close(child_fd)
        elif stat.S_ISREG(path_info.st_mode):
            item = _read_named_regular(directory_fd, name, max_bytes=max_file_bytes)
            records.append((relative, len(item.raw), _sha256(item.raw)))
            identities.append((relative, item.identity))
        else:
            raise RawProvenanceError("raw tree contains a symlink or special entry")
    if before != _identity(os.fstat(directory_fd)):
        raise RawProvenanceError("raw directory changed while scanning")


def _scan_raw_tree(root_fd: int, authority: Authority) -> RawSnapshot:
    raw_fd = _open_relative_directory(root_fd, authority.raw_root_relative)
    try:
        root_before = _identity(os.fstat(raw_fd))
        direct = os.listdir(raw_fd)
        expected = {f"{stem}.geff" for stem in authority.stems}
        if len(direct) != len(expected) or set(direct) != expected:
            raise RawProvenanceError("raw direct-root membership drift")
        for name in direct:
            info = os.stat(name, dir_fd=raw_fd, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode):
                raise RawProvenanceError("every raw direct child must be a GEFF directory")
        records: list[tuple[str, int, str]] = []
        identities: list[tuple[str, tuple[int, int, int, int, int, int, int]]] = []
        _walk_directory(raw_fd, "", records, identities, max_file_bytes=authority.raw_bytes)
        root_after = _identity(os.fstat(raw_fd))
        if root_before != root_after:
            raise RawProvenanceError("raw root changed while scanning")
    finally:
        os.close(raw_fd)
    records.sort(key=lambda item: item[0])
    identities.sort(key=lambda item: item[0])
    record_values = [{"path": path, "bytes": size, "sha256": digest} for path, size, digest in records]
    records_sha256 = _sha256(canonical_json_bytes(record_values))
    legacy = b"".join(f"{digest}  ./{path}\n".encode() for path, _size, digest in records)
    snapshot = RawSnapshot(
        records=tuple(records),
        identities=tuple(identities),
        root_identity=root_after,
        records_sha256=records_sha256,
        legacy_tree_sha256=_sha256(legacy),
        file_count=len(records),
        total_bytes=sum(size for _path, size, _digest in records),
    )
    if (
        snapshot.file_count != authority.raw_files
        or snapshot.total_bytes != authority.raw_bytes
        or snapshot.records_sha256 != authority.raw_records_sha256
        or snapshot.legacy_tree_sha256 != authority.raw_legacy_tree_sha256
    ):
        raise RawProvenanceError("raw inventory does not match the frozen authority")
    return snapshot


def _read_pin(root_fd: int, pin: FilePin) -> PinnedRead:
    if pin.bytes < 0 or pin.bytes > MAX_JSON_BYTES or _SHA_RE.fullmatch(pin.sha256) is None:
        raise RawProvenanceError("invalid evidence pin")
    item = _read_repo_regular(root_fd, pin.relative, max_bytes=pin.bytes)
    if len(item.raw) != pin.bytes or _sha256(item.raw) != pin.sha256:
        raise RawProvenanceError("pinned evidence file drift")
    return item


def _require_dict(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise RawProvenanceError(f"{label} schema drift")
    return value


def _validate_evidence_semantics(
    download_raw: bytes,
    runtime_raw: bytes,
    log_raw: bytes,
    authority: Authority,
) -> None:
    download = _strict_json_bytes(download_raw, canonical=False)
    runtime = _strict_json_bytes(runtime_raw, canonical=False)
    if type(download) is not dict or type(runtime) is not dict:
        raise RawProvenanceError("provenance JSON root is not an object")

    source = download.get("source")
    raw_geff = download.get("raw_geff")
    references = download.get("reference_files")
    if type(source) is not dict or any(
        (
            source.get("kernel") != "taichiiiii/biohub-eval-train-raw",
            type(source.get("version")) is not int or source.get("version") != 11,
            type(source.get("kernel_id")) is not int or source.get("kernel_id") != 131_740_073,
            source.get("latest_status") != "KernelWorkerStatus.COMPLETE",
        )
    ):
        raise RawProvenanceError("download-manifest kernel identity drift")
    if type(raw_geff) is not dict or any(
        (
            raw_geff.get("path") != authority.raw_manifest_relative,
            type(raw_geff.get("roots")) is not int or raw_geff.get("roots") != len(authority.stems),
            type(raw_geff.get("files")) is not int or raw_geff.get("files") != authority.raw_files,
            type(raw_geff.get("bytes")) is not int or raw_geff.get("bytes") != authority.raw_bytes,
            raw_geff.get("canonical_sha256sum_tree_sha256") != authority.raw_legacy_tree_sha256,
            raw_geff.get("zarr_semantic_validation") != "passed",
            type(raw_geff.get("resume_verification_runs")) is not int or raw_geff.get("resume_verification_runs") != 1,
        )
    ):
        raise RawProvenanceError("download-manifest raw-tree semantics drift")
    expected_references = {
        Path(authority.runtime_integrity.relative).name: {
            "bytes": authority.runtime_integrity.bytes,
            "sha256": authority.runtime_integrity.sha256,
        },
        Path(authority.derivation_log.relative).name: {
            "bytes": authority.derivation_log.bytes,
            "sha256": authority.derivation_log.sha256,
        },
    }
    if type(references) is not dict or any(
        references.get(name) != value for name, value in expected_references.items()
    ):
        raise RawProvenanceError("download-manifest reference hashes drift")

    expected_checkpoints = {
        "deepcenter": authority.deepcenter_sha256,
        "primary": authority.primary_weight_sha256,
        "secondary": authority.secondary_weight_sha256,
    }
    checkpoints = runtime.get("checkpoint_sha256")
    if (
        checkpoints != expected_checkpoints
        or len(set(expected_checkpoints.values())) != 3
        or runtime.get("ground_truth_accessed") is not False
        or runtime.get("status") != "complete_label_free_runtime_integrity"
        or type(runtime.get("support_repo_python_file_count")) is not int
        or runtime.get("support_repo_python_file_count") != 13
        or runtime.get("support_repo_python_manifest_sha256") != authority.support_manifest_sha256
    ):
        raise RawProvenanceError("runtime-integrity semantics drift")

    try:
        log_text = log_raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RawProvenanceError("derivation log is not UTF-8") from error
    statements = (
        f"Weight sha256: {authority.primary_weight_sha256}",
        f"Primary materialized SHA256: {authority.primary_weight_sha256}",
        f"Secondary SHA256: {authority.secondary_weight_sha256}",
        (
            "VALIDATOR: merged 36 prediction graphs into "
            "/kaggle/working/tracking_repo/predictions/unknown/unet_transformer_val/split_0"
        ),
        "VALIDATOR: prediction completed in 75.25 minutes",
    )
    if any(log_text.count(statement) != 1 for statement in statements):
        raise RawProvenanceError("derivation log lacks unique frozen hash/completion statements")


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
        raise RawProvenanceError("git state capture failed") from error
    if process.returncode != 0 or process.stderr:
        raise RawProvenanceError("git state capture failed")
    return process.stdout


def _git_blob_oid(raw: bytes) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {len(raw)}\0".encode("ascii"))
    digest.update(raw)
    return digest.hexdigest()


def _nul_records(raw: bytes, label: str) -> tuple[bytes, ...]:
    if not raw or not raw.endswith(b"\0"):
        raise RawProvenanceError(f"invalid {label} output")
    records = tuple(raw[:-1].split(b"\0"))
    if any(not record for record in records):
        raise RawProvenanceError(f"invalid {label} output")
    return records


def _decode_git_path(raw: bytes) -> str:
    try:
        path = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise RawProvenanceError("tracked path is not strict UTF-8") from error
    return _safe_relative(path)


def _assert_no_case_collisions(paths: tuple[str, ...], label: str) -> None:
    folded: dict[str, str] = {}
    for path in paths:
        previous = folded.setdefault(path.casefold(), path)
        if previous != path:
            raise RawProvenanceError(f"{label} has case-colliding paths")


def _parse_head_entries(raw: bytes, label: str) -> tuple[tuple[str, str, str, str], ...]:
    entries: list[tuple[str, str, str, str]] = []
    for record in _nul_records(raw, label):
        try:
            metadata, path_raw = record.split(b"\t", 1)
            mode_raw, kind_raw, oid_raw = metadata.split(b" ")
            mode = mode_raw.decode("ascii")
            kind = kind_raw.decode("ascii")
            oid = oid_raw.decode("ascii")
        except (UnicodeDecodeError, ValueError) as error:
            raise RawProvenanceError(f"invalid {label} entry") from error
        expected_kind = {
            "100644": "blob",
            "100755": "blob",
            "120000": "blob",
            "160000": "commit",
        }.get(mode)
        if expected_kind is None or kind != expected_kind or _OID_RE.fullmatch(oid) is None:
            raise RawProvenanceError(f"unsupported {label} entry")
        entries.append((mode, kind, oid, _decode_git_path(path_raw)))
    paths = tuple(entry[3] for entry in entries)
    if len(set(paths)) != len(paths):
        raise RawProvenanceError(f"duplicate {label} path")
    _assert_no_case_collisions(paths, label)
    return tuple(entries)


def _parse_index_entries(raw: bytes, label: str) -> tuple[tuple[str, str, str, str], ...]:
    entries: list[tuple[str, str, str, str]] = []
    for record in _nul_records(raw, label):
        if not record.startswith(b"H "):
            raise RawProvenanceError(f"{label} has unsafe index flags")
        try:
            metadata, path_raw = record[2:].split(b"\t", 1)
            mode_raw, oid_raw, stage_raw = metadata.split(b" ")
            mode = mode_raw.decode("ascii")
            oid = oid_raw.decode("ascii")
            stage = stage_raw.decode("ascii")
        except (UnicodeDecodeError, ValueError) as error:
            raise RawProvenanceError(f"invalid {label} entry") from error
        if mode not in {"100644", "100755", "120000", "160000"} or _OID_RE.fullmatch(oid) is None or stage != "0":
            raise RawProvenanceError(f"invalid {label} mode, OID, or stage")
        entries.append((mode, "commit" if mode == "160000" else "blob", oid, _decode_git_path(path_raw)))
    paths = tuple(entry[3] for entry in entries)
    if len(set(paths)) != len(paths):
        raise RawProvenanceError(f"duplicate {label} path")
    _assert_no_case_collisions(paths, label)
    return tuple(entries)


def _read_relative_symlink(root_fd: int, relative: str) -> PinnedRead:
    parts = PurePosixPath(_safe_relative(relative)).parts
    parent_fd = _open_relative_directory(root_fd, tuple(parts[:-1]))
    try:
        before = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISLNK(before.st_mode) or before.st_nlink != 1:
            raise RawProvenanceError("tracked symlink type or link-count drift")
        target = os.readlink(os.fsencode(parts[-1]), dir_fd=parent_fd)
        if not isinstance(target, bytes):
            raise RawProvenanceError("tracked symlink target type drift")
        after = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        if _identity(before) != _identity(after) or before.st_size != len(target):
            raise RawProvenanceError("tracked symlink changed while reading")
        return PinnedRead(raw=target, identity=_identity(after))
    finally:
        os.close(parent_fd)


def _validate_tracked_checkout(root: Path, checkout_fd: int, *, production_official: bool) -> int:
    label = "official"
    head = _parse_head_entries(
        _run_git(root, "ls-tree", "-rz", "--full-tree", "HEAD"),
        f"{label} HEAD tree",
    )
    index = _parse_index_entries(
        _run_git(root, "ls-files", "-z", "--stage", "-v"),
        f"{label} index",
    )
    if head != index:
        raise RawProvenanceError(f"{label} HEAD and index entries differ")
    if production_official and len(head) != PRODUCTION_OFFICIAL_TRACKED_ENTRIES:
        raise RawProvenanceError("official tracked-entry count drift")
    for mode, kind, oid, relative in head:
        if kind == "commit":
            raise RawProvenanceError(f"nested {label} gitlinks are forbidden")
        expected_raw = _run_git(root, "cat-file", "blob", oid)
        if _git_blob_oid(expected_raw) != oid:
            raise RawProvenanceError(f"{label} HEAD blob identity drift")
        if mode == "120000":
            observed = _read_relative_symlink(checkout_fd, relative)
        else:
            observed = _read_repo_regular(checkout_fd, relative)
            expected_permissions = 0o755 if mode == "100755" else 0o644
            if stat.S_IMODE(observed.identity[2]) != expected_permissions:
                raise RawProvenanceError(f"{label} regular-file mode drift")
        if observed.raw != expected_raw:
            raise RawProvenanceError(f"{label} working-tree bytes differ from HEAD")
    return len(head)


def _validate_superproject_checkout(
    root: Path,
    guard: CheckoutGuard,
    authority: Authority,
) -> int:
    head = _parse_head_entries(
        _run_git(root, "ls-tree", "-rz", "--full-tree", "HEAD"),
        "superproject HEAD tree",
    )
    index = _parse_index_entries(
        _run_git(root, "ls-files", "-z", "--stage", "-v"),
        "superproject index",
    )
    if head != index:
        raise RawProvenanceError("superproject HEAD and index entries differ")
    paths = {entry[3] for entry in head}
    required = {*authority.builder_sources, "official"}
    if not required.issubset(paths):
        raise RawProvenanceError("required superproject tracked entries are absent")

    gitlinks = 0
    for mode, kind, oid, relative in head:
        if kind == "commit":
            gitlinks += 1
            if mode != "160000" or relative != "official" or oid != authority.official_oid:
                raise RawProvenanceError("unexpected superproject gitlink")
            path_info = os.stat(relative, dir_fd=guard.root_fd, follow_symlinks=False)
            if (
                not stat.S_ISDIR(path_info.st_mode)
                or _directory_handle_identity(path_info) != guard.official_identity
                or _directory_handle_identity(os.fstat(guard.official_fd)) != guard.official_identity
            ):
                raise RawProvenanceError("superproject official gitlink working-tree drift")
            continue

        expected_raw = _run_git(root, "cat-file", "blob", oid)
        if _git_blob_oid(expected_raw) != oid:
            raise RawProvenanceError("superproject HEAD blob identity drift")
        if mode == "120000":
            observed = _read_relative_symlink(guard.root_fd, relative)
        else:
            observed = _read_repo_regular(guard.root_fd, relative)
            expected_permissions = 0o755 if mode == "100755" else 0o644
            if stat.S_IMODE(observed.identity[2]) != expected_permissions:
                raise RawProvenanceError("superproject regular-file mode drift")
        if observed.raw != expected_raw:
            raise RawProvenanceError("superproject working-tree bytes differ from HEAD")
    if gitlinks != 1:
        raise RawProvenanceError("superproject official gitlink cardinality drift")
    return len(head)


def _validate_builder_source(root: Path, root_fd: int, relative: str) -> None:
    safe = _safe_relative(relative)
    head = _parse_head_entries(
        _run_git(root, "ls-tree", "-rz", "--full-tree", "HEAD", "--", safe),
        "builder HEAD tree",
    )
    index = _parse_index_entries(
        _run_git(root, "ls-files", "-z", "--stage", "-v", "--", safe),
        "builder index",
    )
    if len(head) != 1 or head != index or head[0][3] != safe:
        raise RawProvenanceError("builder source HEAD/index binding drift")
    mode, kind, oid, _path = head[0]
    if kind != "blob" or mode not in {"100644", "100755"}:
        raise RawProvenanceError("builder source is not a regular HEAD blob")
    expected_raw = _run_git(root, "cat-file", "blob", oid)
    if _git_blob_oid(expected_raw) != oid:
        raise RawProvenanceError("builder source HEAD blob identity drift")
    observed = _read_repo_regular(root_fd, safe, max_bytes=4 * 1024 * 1024)
    expected_permissions = 0o755 if mode == "100755" else 0o644
    if stat.S_IMODE(observed.identity[2]) != expected_permissions:
        raise RawProvenanceError("builder source mode drift")
    if observed.raw != expected_raw:
        raise RawProvenanceError("builder source bytes differ from HEAD")


def _assert_checkout_rebound(root: Path, guard: CheckoutGuard) -> None:
    if root != Path(os.path.abspath(CANONICAL_REPO_ROOT)) or Path.cwd() != root:
        raise RawProvenanceError("canonical checkout pathname drift")
    if _directory_handle_identity(os.fstat(guard.root_fd)) != guard.root_identity:
        raise RawProvenanceError("canonical checkout descriptor drift")
    if _directory_handle_identity(os.fstat(guard.git_fd)) != guard.git_identity:
        raise RawProvenanceError("canonical .git descriptor drift")
    if _directory_handle_identity(os.fstat(guard.official_fd)) != guard.official_identity:
        raise RawProvenanceError("canonical official descriptor drift")
    fresh_root_fd = _open_absolute_directory(root)
    try:
        if _directory_handle_identity(os.fstat(fresh_root_fd)) != guard.root_identity:
            raise RawProvenanceError("canonical checkout path identity drift")
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
                raise RawProvenanceError(f"canonical {name} path identity drift")
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
        status_raw = _run_git(
            root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=none",
        )
        if status_raw:
            raise RawProvenanceError("checkout is not completely clean")
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
            raise RawProvenanceError("official checkout is not clean")
        if not _OID_RE.fullmatch(commit) or not _OID_RE.fullmatch(tree):
            raise RawProvenanceError("invalid source object identity")
        if gitlink != authority.official_oid or official != authority.official_oid:
            raise RawProvenanceError("official gitlink/head drift")
        _validate_superproject_checkout(root, guard, authority)
        _validate_tracked_checkout(
            root / "official",
            guard.official_fd,
            production_official=official == OFFICIAL_OID,
        )
        _assert_checkout_rebound(root, guard)
        return GitState(commit=commit, tree=tree, official_oid=official)
    finally:
        if owned_guard:
            guard.close()


def _collect_authority(
    root_fd: int,
    root: Path,
    authority: Authority,
    guard: CheckoutGuard | None = None,
) -> CollectedAuthority:
    git_before = _capture_git_state(root, authority, guard)
    download_before = _read_pin(root_fd, authority.download_manifest)
    runtime_before = _read_pin(root_fd, authority.runtime_integrity)
    log_before = _read_pin(root_fd, authority.derivation_log)
    raw_before = _scan_raw_tree(root_fd, authority)
    raw_after = _scan_raw_tree(root_fd, authority)
    download_after = _read_pin(root_fd, authority.download_manifest)
    runtime_after = _read_pin(root_fd, authority.runtime_integrity)
    log_after = _read_pin(root_fd, authority.derivation_log)
    git_after = _capture_git_state(root, authority, guard)
    if (
        git_before != git_after
        or raw_before != raw_after
        or download_before != download_after
        or runtime_before != runtime_after
        or log_before != log_after
    ):
        raise RawProvenanceError("authority changed during collection")
    _validate_evidence_semantics(download_before.raw, runtime_before.raw, log_before.raw, authority)
    return CollectedAuthority(
        git=git_before,
        raw=raw_before,
        download=download_before,
        runtime=runtime_before,
        log=log_before,
    )


def _validate_checkout(root: Path) -> CheckoutGuard:
    expected = Path(os.path.abspath(CANONICAL_REPO_ROOT))
    if root != expected or Path.cwd() != expected:
        raise RawProvenanceError("operation requires the canonical checkout as cwd")
    root_fd = _open_absolute_directory(root)
    git_fd: int | None = None
    official_fd: int | None = None
    try:
        root_info = os.fstat(root_fd)
        if _identity(root_info) != _identity(root.lstat()):
            raise RawProvenanceError("canonical checkout identity mismatch")
        git_info = os.stat(".git", dir_fd=root_fd, follow_symlinks=False)
        if not stat.S_ISDIR(git_info.st_mode):
            raise RawProvenanceError("linked worktrees are forbidden")
        git_fd = os.open(
            ".git",
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
        if _directory_handle_identity(os.fstat(git_fd)) != _directory_handle_identity(git_info):
            raise RawProvenanceError("canonical .git identity mismatch")
        official_info = os.stat("official", dir_fd=root_fd, follow_symlinks=False)
        if not stat.S_ISDIR(official_info.st_mode):
            raise RawProvenanceError("official checkout is not a directory")
        official_fd = os.open(
            "official",
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
        if _directory_handle_identity(os.fstat(official_fd)) != _directory_handle_identity(official_info):
            raise RawProvenanceError("canonical official identity mismatch")
        return CheckoutGuard(
            root_fd=root_fd,
            git_fd=git_fd,
            official_fd=official_fd,
            root_identity=_directory_handle_identity(root_info),
            git_identity=_directory_handle_identity(git_info),
            official_identity=_directory_handle_identity(official_info),
        )
    except BaseException:
        for fd in (official_fd, git_fd, root_fd):
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)
        raise


def _constrain_run_dir(root: Path, run_dir: Path, authority: Authority) -> tuple[Path, str]:
    if any(part == ".." for part in run_dir.parts):
        raise RawProvenanceError("run directory must not contain traversal")
    absolute = Path(os.path.abspath(run_dir))
    expected_parent = root / authority.output_parent_relative
    if absolute.parent != expected_parent or _RUN_NAME_RE.fullmatch(absolute.name) is None:
        raise RawProvenanceError("run directory must be a fresh direct child of the fixed output parent")
    return absolute, absolute.name


def _ensure_output_parent(root_fd: int, relative: str) -> int:
    parts = PurePosixPath(_safe_relative(relative)).parts
    current = os.dup(root_fd)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        for part in parts:
            parent_before = _identity(os.fstat(current))
            exists = _exact_child_name(current, part, allow_missing=True)
            if not exists:
                try:
                    os.mkdir(part, 0o700, dir_fd=current)
                    os.fsync(current)
                except FileExistsError:
                    _exact_child_name(current, part, allow_missing=False)
            next_fd = os.open(part, flags, dir_fd=current)
            keep_next = False
            try:
                path_info = os.stat(part, dir_fd=current, follow_symlinks=False)
                if not stat.S_ISDIR(path_info.st_mode) or _identity(path_info) != _identity(os.fstat(next_fd)):
                    raise RawProvenanceError("unsafe output-parent component")
                if exists and parent_before != _identity(os.fstat(current)):
                    raise RawProvenanceError("output parent changed")
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


def _name_info(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _write_new_regular(parent_fd: int, name: str, raw: bytes) -> tuple[int, int]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(name, flags, 0o444, dir_fd=parent_fd)
    try:
        created = _ownership(os.fstat(fd))
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short receipt write")
            view = view[written:]
        os.fchmod(fd, 0o444)
        os.fsync(fd)
        info = os.fstat(fd)
        path_info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_size != len(raw)
            or stat.S_IMODE(info.st_mode) != 0o444
            or _identity(info) != _identity(path_info)
        ):
            raise RawProvenanceError("new receipt identity mismatch")
        return created
    except BaseException as original:
        try:
            descriptor = os.fstat(fd)
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(descriptor.st_mode)
                or descriptor.st_nlink != 1
                or _identity(descriptor) != _identity(current)
            ):
                raise PublicationAmbiguityError("failed receipt write changed identity")
            os.unlink(name, dir_fd=parent_fd)
            os.fsync(parent_fd)
            if _name_info(parent_fd, name) is not None:
                raise PublicationAmbiguityError("failed receipt write remains after rollback")
        except BaseException as cleanup:
            raise PublicationAmbiguityError("failed receipt write could not be rolled back") from BaseExceptionGroup(
                "receipt write and rollback failed", [original, cleanup]
            )
        raise
    finally:
        pending = sys.exception()
        try:
            os.close(fd)
        except OSError:
            pass
        except BaseException as close_error:
            if pending is not None:
                raise PublicationAmbiguityError(
                    "receipt fault and descriptor close are ambiguous"
                ) from BaseExceptionGroup(
                    "receipt operation and descriptor-close failure",
                    [pending, close_error],
                )
            raise


def _rename_noreplace(parent_fd: int, source: str, destination: str) -> str:
    source_raw = os.fsencode(source)
    destination_raw = os.fsencode(destination)
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(library, "renameatx_np"):
        function = library.renameatx_np
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(parent_fd, source_raw, parent_fd, destination_raw, 0x00000004)
        primitive = "renameatx_np(RENAME_EXCL)"
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        function = library.renameat2
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(parent_fd, source_raw, parent_fd, destination_raw, 0x00000001)
        primitive = "renameat2(RENAME_NOREPLACE)"
    else:
        raise RawProvenanceError("atomic no-replace directory rename is unavailable")
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(destination)
        raise OSError(error_number, os.strerror(error_number))
    return primitive


def _owned_name(parent_fd: int, name: str, ownership: tuple[int, int]) -> bool:
    info = _name_info(parent_fd, name)
    return info is not None and stat.S_ISDIR(info.st_mode) and _ownership(info) == ownership


def _cleanup_owned(parent_fd: int, name: str, owned: _OwnedStaging) -> None:
    if not _owned_name(parent_fd, name, owned.identity):
        raise PublicationAmbiguityError("owned staging identity changed")
    directory_fd = _open_relative_directory(parent_fd, (name,))
    try:
        os.fchmod(directory_fd, 0o700)
        expected = dict(owned.files)
        if set(os.listdir(directory_fd)) != set(expected):
            raise PublicationAmbiguityError("owned staging membership changed")
        for filename, identity in owned.files:
            info = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or _ownership(info) != identity:
                raise PublicationAmbiguityError("owned staging file identity changed")
        for filename, _identity_value in owned.files:
            os.unlink(filename, dir_fd=directory_fd)
        os.fsync(directory_fd)
    except PublicationAmbiguityError:
        raise
    except OSError as error:
        raise PublicationAmbiguityError("owned staging cleanup failed") from error
    finally:
        os.close(directory_fd)
    try:
        os.rmdir(name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except OSError as error:
        raise PublicationAmbiguityError("owned staging directory cleanup failed") from error


def _bind_empty_staging(parent_fd: int, name: str) -> tuple[int, _OwnedStaging]:
    directory_fd = _open_relative_directory(parent_fd, (name,))
    keep = False
    try:
        before = os.fstat(directory_fd)
        path_before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        names = os.listdir(directory_fd)
        after = os.fstat(directory_fd)
        path_after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISDIR(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o700
            or names
            or _identity(before) != _identity(path_before)
            or _identity(before) != _identity(after)
            or _identity(after) != _identity(path_after)
        ):
            raise PublicationAmbiguityError("new staging directory identity is ambiguous")
        owned = _OwnedStaging(name=name, identity=_ownership(after), files=())
        keep = True
        return directory_fd, owned
    finally:
        if not keep:
            with contextlib.suppress(OSError):
                os.close(directory_fd)


def _recover_initial_staging_fault(parent_fd: int, name: str, cause: BaseException) -> None:
    try:
        recovery_fd, owned = _bind_empty_staging(parent_fd, name)
    except BaseException as identity_error:
        raise PublicationAmbiguityError("new staging identity could not be recovered") from BaseExceptionGroup(
            "initial staging identity fault and recovery failure",
            [cause, identity_error],
        )
    try:
        os.close(recovery_fd)
    except OSError:
        pass
    except BaseException as close_error:
        raise PublicationAmbiguityError("new staging recovery descriptor close is ambiguous") from BaseExceptionGroup(
            "initial staging identity fault and descriptor-close failure",
            [cause, close_error],
        )
    try:
        _cleanup_owned(parent_fd, name, owned)
    except BaseException as cleanup_error:
        raise PublicationAmbiguityError("new staging recovery is not durable") from BaseExceptionGroup(
            "initial staging identity fault and cleanup failure",
            [cause, cleanup_error],
        )


def _create_owned_staging(parent_fd: int, name: str) -> tuple[int, _OwnedStaging]:
    os.mkdir(name, 0o700, dir_fd=parent_fd)
    try:
        directory_fd, owned = _bind_empty_staging(parent_fd, name)
    except BaseException as error:
        _recover_initial_staging_fault(parent_fd, name, error)
        raise
    try:
        os.fsync(parent_fd)
        descriptor = os.fstat(directory_fd)
        path_info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISDIR(descriptor.st_mode)
            or stat.S_IMODE(descriptor.st_mode) != 0o700
            or _identity(descriptor) != _identity(path_info)
            or _ownership(descriptor) != owned.identity
        ):
            raise PublicationAmbiguityError("new staging identity changed after parent fsync")
        return directory_fd, owned
    except BaseException as error:
        try:
            os.close(directory_fd)
        except OSError:
            pass
        except BaseException as close_error:
            raise PublicationAmbiguityError("new staging descriptor close is ambiguous") from BaseExceptionGroup(
                "staging creation and descriptor-close failure",
                [error, close_error],
            )
        try:
            _cleanup_owned(parent_fd, name, owned)
        except BaseException as cleanup_error:
            raise PublicationAmbiguityError("new staging creation rollback failed") from BaseExceptionGroup(
                "staging creation and rollback failed",
                [error, cleanup_error],
            )
        raise


def _rollback_publication(parent_fd: int, final_name: str, staging_name: str, owned: _OwnedStaging) -> None:
    try:
        if not _owned_name(parent_fd, final_name, owned.identity) or _name_info(parent_fd, staging_name) is not None:
            raise PublicationAmbiguityError("published directory ownership is ambiguous")
        _rename_noreplace(parent_fd, final_name, staging_name)
        os.fsync(parent_fd)
        _cleanup_owned(parent_fd, staging_name, owned)
    except PublicationAmbiguityError:
        raise
    except BaseException as error:
        raise PublicationAmbiguityError("published directory rollback failed") from error


def _publish_staging(parent_fd: int, final_name: str, owned: _OwnedStaging) -> str:
    renamed = False
    try:
        primitive = _rename_noreplace(parent_fd, owned.name, final_name)
        renamed = True
        os.fsync(parent_fd)
        return primitive
    except BaseException as original:
        try:
            staging_owned = _owned_name(parent_fd, owned.name, owned.identity)
            final_owned = _owned_name(parent_fd, final_name, owned.identity)
            if final_owned and not staging_owned:
                _rollback_publication(parent_fd, final_name, owned.name, owned)
            elif staging_owned and not final_owned:
                _cleanup_owned(parent_fd, owned.name, owned)
            else:
                raise PublicationAmbiguityError("publication outcome is ambiguous")
        except BaseException as recovery:
            raise PublicationAmbiguityError("publication and recovery both failed") from BaseExceptionGroup(
                "publication and recovery failed", [original, recovery]
            )
        if renamed:
            raise RawProvenanceError("publication durability failed and was rolled back") from original
        raise


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _valid_utc(value: object) -> bool:
    if type(value) is not str or _UTC_RE.fullmatch(value) is None:
        return False
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
    except ValueError:
        return False
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z") == value


def _artifact_ref(pin: FilePin) -> dict[str, object]:
    return {"path": pin.relative, "bytes": pin.bytes, "sha256": pin.sha256}


def _receipt_value(
    role: str, created_utc: str, collected: CollectedAuthority, authority: Authority
) -> dict[str, object]:
    if role not in {"primary", "secondary"}:
        raise RawProvenanceError("unsupported provenance role")
    known_weight = authority.primary_weight_sha256 if role == "primary" else authority.secondary_weight_sha256
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "role": role,
        "created_utc": created_utc,
        "source": {
            "commit": collected.git.commit,
            "git_tree_oid": collected.git.tree,
            "official_gitlink": authority.official_oid,
        },
        "raw_root": authority.raw_root_relative,
        "raw_records_sha256": authority.raw_records_sha256,
        "known_weight_sha256": known_weight,
        "download_manifest": _artifact_ref(authority.download_manifest),
        "runtime_integrity": _artifact_ref(authority.runtime_integrity),
        "derivation_log": _artifact_ref(authority.derivation_log),
        "claims": {
            "checkpoint_bytes_verified_by_this_receipt": False,
            "checkpoint_to_raw_cryptographic_proof": False,
            "legacy_log_and_runtime_receipts_verified": True,
        },
    }


def _validate_receipt(
    raw: bytes,
    role: str,
    collected: CollectedAuthority,
    authority: Authority,
) -> dict[str, Any]:
    value = _strict_json_bytes(raw, canonical=True)
    expected_keys = {
        "schema_version",
        "status",
        "role",
        "created_utc",
        "source",
        "raw_root",
        "raw_records_sha256",
        "known_weight_sha256",
        "download_manifest",
        "runtime_integrity",
        "derivation_log",
        "claims",
    }
    receipt = _require_dict(value, expected_keys, f"{role} receipt")
    if (
        receipt["schema_version"] != SCHEMA_VERSION
        or receipt["status"] != STATUS
        or receipt["role"] != role
        or not _valid_utc(receipt["created_utc"])
        or receipt["source"]
        != {
            "commit": collected.git.commit,
            "git_tree_oid": collected.git.tree,
            "official_gitlink": authority.official_oid,
        }
        or receipt["raw_root"] != authority.raw_root_relative
        or receipt["raw_records_sha256"] != authority.raw_records_sha256
        or receipt["download_manifest"] != _artifact_ref(authority.download_manifest)
        or receipt["runtime_integrity"] != _artifact_ref(authority.runtime_integrity)
        or receipt["derivation_log"] != _artifact_ref(authority.derivation_log)
    ):
        raise RawProvenanceError(f"{role} receipt authority drift")
    expected_weight = authority.primary_weight_sha256 if role == "primary" else authority.secondary_weight_sha256
    if receipt["known_weight_sha256"] != expected_weight or _SHA_RE.fullmatch(expected_weight) is None:
        raise RawProvenanceError(f"{role} known weight digest drift")
    if receipt["claims"] != {
        "checkpoint_bytes_verified_by_this_receipt": False,
        "checkpoint_to_raw_cryptographic_proof": False,
        "legacy_log_and_runtime_receipts_verified": True,
    }:
        raise RawProvenanceError("legacy claims overstate or omit the frozen evidence boundary")
    return receipt


def _load_bundle(parent_fd: int, run_name: str) -> tuple[bytes, bytes, tuple[int, int, int, int, int, int, int]]:
    run_fd = _open_relative_directory(parent_fd, (run_name,))
    try:
        before = _identity(os.fstat(run_fd))
        if not stat.S_ISDIR(before[2]) or stat.S_IMODE(before[2]) != 0o555:
            raise RawProvenanceError("receipt bundle directory mode drift")
        names = os.listdir(run_fd)
        if len(names) != 2 or set(names) != set(RECEIPT_NAMES):
            raise RawProvenanceError("receipt-bundle membership drift")
        primary_item = _read_named_regular(run_fd, PRIMARY_RECEIPT, max_bytes=MAX_RECEIPT_BYTES)
        secondary_item = _read_named_regular(run_fd, SECONDARY_RECEIPT, max_bytes=MAX_RECEIPT_BYTES)
        if stat.S_IMODE(primary_item.identity[2]) != 0o444 or stat.S_IMODE(secondary_item.identity[2]) != 0o444:
            raise RawProvenanceError("receipt file mode drift")
        after = _identity(os.fstat(run_fd))
        if before != after:
            raise RawProvenanceError("receipt bundle changed while reading")
        return primary_item.raw, secondary_item.raw, after
    finally:
        os.close(run_fd)


def _assert_output_parent_rebound(
    root_fd: int,
    relative: str,
    parent_fd: int,
    expected_identity: tuple[int, int, int],
) -> None:
    if _directory_handle_identity(os.fstat(parent_fd)) != expected_identity:
        raise RawProvenanceError("held output parent identity drift")
    fresh_fd = _open_relative_directory(root_fd, relative)
    try:
        fresh_identity = _directory_handle_identity(os.fstat(fresh_fd))
        if fresh_identity != expected_identity or fresh_identity != _directory_handle_identity(os.fstat(parent_fd)):
            raise RawProvenanceError("canonical output parent pathname displacement")
    finally:
        os.close(fresh_fd)


def _validate_owned_bundle(
    parent_fd: int,
    name: str,
    owned: _OwnedStaging,
    expected_primary: bytes,
    expected_secondary: bytes,
) -> tuple[int, int, int, int, int, int, int]:
    if not _owned_name(parent_fd, name, owned.identity):
        raise RawProvenanceError("owned raw-provenance bundle pathname identity drift")
    run_fd = _open_relative_directory(parent_fd, (name,))
    try:
        before = _identity(os.fstat(run_fd))
        path_before = _identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False))
        names = os.listdir(run_fd)
        expected_files = dict(owned.files)
        expected_bytes = {PRIMARY_RECEIPT: expected_primary, SECONDARY_RECEIPT: expected_secondary}
        if (
            _ownership(os.fstat(run_fd)) != owned.identity
            or before != path_before
            or stat.S_IMODE(before[2]) != 0o555
            or len(names) != 2
            or set(names) != set(RECEIPT_NAMES)
            or set(expected_files) != set(RECEIPT_NAMES)
        ):
            raise RawProvenanceError("owned raw-provenance bundle identity or membership drift")
        observed: dict[str, bytes] = {}
        for filename in RECEIPT_NAMES:
            path_info = os.stat(filename, dir_fd=run_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(path_info.st_mode)
                or path_info.st_nlink != 1
                or _ownership(path_info) != expected_files[filename]
            ):
                raise RawProvenanceError("owned raw-provenance receipt inode drift")
            item = _read_named_regular(run_fd, filename, max_bytes=MAX_RECEIPT_BYTES)
            if stat.S_IMODE(item.identity[2]) != 0o444:
                raise RawProvenanceError("owned raw-provenance receipt mode drift")
            if item.raw != expected_bytes[filename] or _sha256(item.raw) != _sha256(expected_bytes[filename]):
                raise RawProvenanceError("owned raw-provenance receipt bytes or hash drift")
            observed[filename] = item.raw
        after = _identity(os.fstat(run_fd))
        path_after = _identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False))
        if observed != expected_bytes or before != after or after != path_after:
            raise RawProvenanceError("owned raw-provenance bundle bytes or identity drift")
        return after
    finally:
        os.close(run_fd)


def _publish_verified(
    root: Path,
    guard: CheckoutGuard,
    parent_fd: int,
    parent_identity: tuple[int, int, int],
    final_name: str,
    owned: _OwnedStaging,
    primary_raw: bytes,
    secondary_raw: bytes,
    authority: Authority,
) -> str:
    renamed = False
    try:
        _assert_checkout_rebound(root, guard)
        _assert_output_parent_rebound(guard.root_fd, authority.output_parent_relative, parent_fd, parent_identity)
        _validate_owned_bundle(parent_fd, owned.name, owned, primary_raw, secondary_raw)
        primitive = _rename_noreplace(parent_fd, owned.name, final_name)
        renamed = True
        os.fsync(parent_fd)
        _assert_checkout_rebound(root, guard)
        _assert_output_parent_rebound(guard.root_fd, authority.output_parent_relative, parent_fd, parent_identity)
        if _name_info(parent_fd, owned.name) is not None:
            raise RawProvenanceError("raw-provenance staging name remained after publication")
        _validate_owned_bundle(parent_fd, final_name, owned, primary_raw, secondary_raw)
        _assert_checkout_rebound(root, guard)
        _assert_output_parent_rebound(guard.root_fd, authority.output_parent_relative, parent_fd, parent_identity)
        return primitive
    except BaseException as original:
        try:
            staging_owned = _owned_name(parent_fd, owned.name, owned.identity)
            final_owned = _owned_name(parent_fd, final_name, owned.identity)
            if final_owned and not staging_owned:
                _rollback_publication(parent_fd, final_name, owned.name, owned)
            elif staging_owned and not final_owned:
                _cleanup_owned(parent_fd, owned.name, owned)
            else:
                raise PublicationAmbiguityError("raw-provenance publication ownership is ambiguous")
        except BaseException as recovery:
            raise PublicationAmbiguityError("raw-provenance publication recovery is ambiguous") from BaseExceptionGroup(
                "raw-provenance publication and recovery failed", [original, recovery]
            )
        if renamed:
            raise RawProvenanceError("raw-provenance publication failed and was durably rolled back") from original
        raise


def _portable_bundle_path(root: Path, run: Path, name: str) -> str:
    relative = (run / name).relative_to(root).as_posix()
    return _safe_relative(relative)


def _result(root: Path, run: Path, source: GitState, primary: bytes, secondary: bytes) -> dict[str, object]:
    primary_ref = {
        "path": _portable_bundle_path(root, run, PRIMARY_RECEIPT),
        "bytes": len(primary),
        "sha256": _sha256(primary),
        "verdict": STATUS,
    }
    secondary_ref = {
        "path": _portable_bundle_path(root, run, SECONDARY_RECEIPT),
        "bytes": len(secondary),
        "sha256": _sha256(secondary),
        "verdict": STATUS,
    }
    if primary_ref["path"] == secondary_ref["path"] or primary_ref["sha256"] == secondary_ref["sha256"]:
        raise RawProvenanceError("primary and secondary opaque receipt references are not distinct")
    return {
        "status": STATUS,
        "remaining_hold": REMAINING_HOLD,
        "source": {"commit": source.commit, "git_tree_oid": source.tree, "official_gitlink": source.official_oid},
        "receipts": {"primary": primary_ref, "secondary": secondary_ref},
    }


def _verify(root: Path, run_dir: Path, authority: Authority) -> dict[str, object]:
    checkout = _validate_checkout(root)
    root_fd = checkout.root_fd
    parent_fd: int | None = None
    try:
        run, run_name = _constrain_run_dir(root, run_dir, authority)
        parent_fd = _open_relative_directory(root_fd, authority.output_parent_relative)
        parent_identity = _directory_handle_identity(os.fstat(parent_fd))
        _assert_output_parent_rebound(root_fd, authority.output_parent_relative, parent_fd, parent_identity)
        primary_before, secondary_before, bundle_before = _load_bundle(parent_fd, run_name)
        collected = _collect_authority(root_fd, root, authority, checkout)
        primary_value = _validate_receipt(primary_before, "primary", collected, authority)
        secondary_value = _validate_receipt(secondary_before, "secondary", collected, authority)
        if primary_value["created_utc"] != secondary_value["created_utc"]:
            raise RawProvenanceError("receipt creation timestamps differ")
        collected_after = _collect_authority(root_fd, root, authority, checkout)
        if not _same_authority(collected, collected_after):
            raise RawProvenanceError("authority changed during verification")
        primary_after, secondary_after, bundle_after = _load_bundle(parent_fd, run_name)
        if primary_before != primary_after or secondary_before != secondary_after or bundle_before != bundle_after:
            raise RawProvenanceError("receipt bundle changed during verification")
        result = _result(root, run, collected.git, primary_before, secondary_before)
        _assert_checkout_rebound(root, checkout)
        _assert_output_parent_rebound(root_fd, authority.output_parent_relative, parent_fd, parent_identity)
        return result
    finally:
        if parent_fd is not None:
            with contextlib.suppress(OSError):
                os.close(parent_fd)
        checkout.close()


def verify_raw_provenance(run_dir: Path) -> dict[str, object]:
    """Independently re-open and revalidate a published legacy receipt bundle."""
    return _verify(Path(os.path.abspath(CANONICAL_REPO_ROOT)), run_dir, PRODUCTION_AUTHORITY)


def _same_authority(left: CollectedAuthority, right: CollectedAuthority) -> bool:
    return left == right


def _build(root: Path, run_dir: Path, authority: Authority) -> dict[str, object]:
    checkout: CheckoutGuard | None = _validate_checkout(root)
    root_fd = checkout.root_fd
    parent_fd: int | None = None
    owned: _OwnedStaging | None = None
    published = False
    publication_attempted = False
    try:
        run, run_name = _constrain_run_dir(root, run_dir, authority)
        collected_before = _collect_authority(root_fd, root, authority, checkout)
        parent_fd = _ensure_output_parent(root_fd, authority.output_parent_relative)
        parent_identity = _directory_handle_identity(os.fstat(parent_fd))
        _assert_output_parent_rebound(root_fd, authority.output_parent_relative, parent_fd, parent_identity)
        if any(name.casefold() == run_name.casefold() for name in os.listdir(parent_fd)):
            raise FileExistsError(run_name)
        staging_name = f".staging.{run_name}.{secrets.token_hex(8)}"
        staging_fd, owned = _create_owned_staging(parent_fd, staging_name)
        try:
            if _ownership(os.fstat(staging_fd)) != owned.identity:
                raise RawProvenanceError("staging identity changed while opening")
            created_utc = _utc_now()
            primary_raw = canonical_json_bytes(_receipt_value("primary", created_utc, collected_before, authority))
            secondary_raw = canonical_json_bytes(_receipt_value("secondary", created_utc, collected_before, authority))
            primary_identity = _write_new_regular(staging_fd, PRIMARY_RECEIPT, primary_raw)
            owned = _OwnedStaging(
                name=owned.name,
                identity=owned.identity,
                files=((PRIMARY_RECEIPT, primary_identity),),
            )
            secondary_identity = _write_new_regular(staging_fd, SECONDARY_RECEIPT, secondary_raw)
            owned = _OwnedStaging(
                name=owned.name,
                identity=owned.identity,
                files=((PRIMARY_RECEIPT, primary_identity), (SECONDARY_RECEIPT, secondary_identity)),
            )
            os.fsync(staging_fd)
            os.fchmod(staging_fd, 0o555)
            os.fsync(staging_fd)
            if _ownership(os.fstat(staging_fd)) != owned.identity:
                raise RawProvenanceError("staging identity changed before publication")
        finally:
            os.close(staging_fd)
        staged_primary, staged_secondary, staged_bundle = _load_bundle(parent_fd, staging_name)
        if staged_primary != primary_raw or staged_secondary != secondary_raw:
            raise RawProvenanceError("staged receipt bytes changed before publication")
        primary_value = _validate_receipt(staged_primary, "primary", collected_before, authority)
        secondary_value = _validate_receipt(staged_secondary, "secondary", collected_before, authority)
        if primary_value["created_utc"] != secondary_value["created_utc"]:
            raise RawProvenanceError("staged receipt creation timestamps differ")
        if staged_bundle != _identity(os.stat(staging_name, dir_fd=parent_fd, follow_symlinks=False)):
            raise RawProvenanceError("staged bundle identity drift")
        collected_after = _collect_authority(root_fd, root, authority, checkout)
        if not _same_authority(collected_before, collected_after):
            raise RawProvenanceError("authority changed before publication")
        staged_primary_after, staged_secondary_after, staged_bundle_after = _load_bundle(parent_fd, staging_name)
        if (
            staged_primary_after != staged_primary
            or staged_secondary_after != staged_secondary
            or staged_bundle_after != staged_bundle
        ):
            raise RawProvenanceError("staged bundle changed before publication")
        success_result = _result(root, run, collected_before.git, staged_primary, staged_secondary)
        _assert_checkout_rebound(root, checkout)
        _validate_owned_bundle(parent_fd, staging_name, owned, staged_primary, staged_secondary)
        _assert_output_parent_rebound(root_fd, authority.output_parent_relative, parent_fd, parent_identity)
        publication_attempted = True
        _publish_verified(
            root,
            checkout,
            parent_fd,
            parent_identity,
            run_name,
            owned,
            staged_primary,
            staged_secondary,
            authority,
        )
        published = True
        with contextlib.suppress(OSError):
            os.close(parent_fd)
        parent_fd = None
        return success_result
    except BaseException as original:
        if owned is not None and not published and not publication_attempted and parent_fd is not None:
            try:
                _cleanup_owned(parent_fd, owned.name, owned)
            except BaseException as cleanup:
                raise PublicationAmbiguityError("pre-publication rollback failed") from BaseExceptionGroup(
                    "construction and rollback failed",
                    [original, cleanup],
                )
        raise
    finally:
        if parent_fd is not None:
            with contextlib.suppress(OSError):
                os.close(parent_fd)
        if checkout is not None:
            checkout.close()


def build_raw_provenance(run_dir: Path) -> dict[str, object]:
    """Build and atomically no-replace publish a fresh fixed receipt bundle."""
    return _build(Path(os.path.abspath(CANONICAL_REPO_ROOT)), run_dir, PRODUCTION_AUTHORITY)


__all__ = [
    "CANONICAL_REPO_ROOT",
    "PRIMARY_RECEIPT",
    "PRODUCTION_AUTHORITY",
    "PublicationAmbiguityError",
    "RawProvenanceError",
    "SCHEMA_VERSION",
    "SECONDARY_RECEIPT",
    "STATUS",
    "build_raw_provenance",
    "canonical_json_bytes",
    "verify_raw_provenance",
]
