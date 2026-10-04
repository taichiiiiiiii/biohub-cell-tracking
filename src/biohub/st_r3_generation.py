"""Fail-closed ST-R3 preregistration and label-blind generation orchestration.

This module intentionally imports no evaluator, official metric, or ground-truth
reader.  It can preserve evidence from the five frozen local supervisor runs,
but the current local supervisor cannot prove the production sandbox, process
tree, target runtime, target memory, or publication exclusion requirements.
Consequently this implementation emits a terminal HOLD and never manufactures
``FEASIBILITY_PASS.json``.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from biohub.public_postproc import production_adapter, production_supervisor
from biohub.public_postproc.production_supervisor import (
    ARM_RECEIPT_SCHEMA,
    EVAL36,
)

EVAL12 = EVAL36[:12]
EVAL24 = EVAL36[12:]
PUBLIC_FOUR = frozenset(("44b6_0113de3b", "44b6_0b24845f", "6bba_05b6850b", "6bba_05db0fb1"))

PREREGISTRATION_SCHEMA = "biohub.st_r3.preregistration.v1"
TREE_INVENTORY_SCHEMA = "biohub.st_r3.tree_inventory.v1"
REVERIFY_SCHEMA = "biohub.st_r3.input_reverify.v1"
GENERATION_SCHEMA = "biohub.st_r3.generation_manifest.v1"
TERMINAL_HOLD_SCHEMA = "biohub.st_r3.generation_hold.v1"
TARGET_RESOURCE_SCHEMA = "biohub.st_r3.target_resources.v1"
E23_PARITY_RECEIPT_SCHEMA = "biohub.st_r3.e23_parity_receipt.v1"
BASE1_RECEIPT_SCHEMA = "biohub.st_r3.base1_non_regression_receipt.v1"
RAW_PROVENANCE_SCHEMA = "biohub.st_r3.raw_provenance_receipt.v1"
GT_INVENTORY_SCHEMA = "biohub.st_r3.gt_inventory.v1"
TYPED_GRAPH_SCHEMA = "biohub.st_r3.typed_submission_graph.v1"

OFFICIAL_REVIEWED_OID = "075fc5f5a52d11077f9dc2b074644618f26939e2"
READY_DIGEST_SCOPE = (
    "ready_content_sha256 hashes canonical JSON of all READY fields except created_utc and ready_content_sha256"
)
READY_DECODE_ORDER = (
    "for each EVAL36_STEMS item and numeric chunk index: "
    "stem ASCII, chunk index unsigned big-endian 2 bytes, decoded little-endian uint16 bytes"
)
CANONICAL_READY_PATH = "outputs/local/eval36_image_ready/20260904T220902+0900_2877f28_direct/READY.json"
CANONICAL_READY_SHA256 = "8a0a36d393ecc11a0532bc12011257a4c012cb7361d4346941b4d1211c58c73e"
CANONICAL_READY_CONTENT_SHA256 = "2211abec541bc31df2f31aacf1575c065025f0aa143147c3df07b4ece2b3214a"
CANONICAL_IMAGE_INVENTORY_SHA256 = "efe652bd8e8a791bd51cf3b980ae87fe0fe2205ec52d2f3639717cd2b0550714"
CANONICAL_IMPORT_PATH = (
    "outputs/local/eval36_bundle_receipts/20260904T0055JST/"
    "eval36-import-0b224bf87b6fb0d0653cd265461a4fb75e17068de3550a73b19379eeb2294570.json"
)
CANONICAL_IMPORT_SHA256 = "0b224bf87b6fb0d0653cd265461a4fb75e17068de3550a73b19379eeb2294570"
CANONICAL_RAW_ROOT = (
    "outputs/kaggle/e22_bidir030_eval36_raw/tracking_repo/predictions/unknown/unet_transformer_val/split_0"
)
CANONICAL_RAW_RECORDS_SHA256 = "d49541301e7b76afe65a5ba61f5d8f8b01c14c39c256455b7cdd5af9a7564cbb"
PRIMARY_RAW_WEIGHT_SHA256 = "12f6881ee3620a831697ca098ff8f48e687a24225f4e048b538deec3562fe771"
SECONDARY_RAW_WEIGHT_SHA256 = "9bac2fa0dadc4a6fc1899e0caf187f4b553e0a7cd90ba1261a68b35ffe9e305f"
RAW_DERIVATION_LOG_PATH = "outputs/kaggle/e22_bidir030_eval36_raw/biohub-eval-train-raw.log"
RAW_DERIVATION_LOG_BYTES = 391_952
RAW_DERIVATION_LOG_SHA256 = "eaf6749aafacfc87b5c9ec953add016adff61d5a3da8d3112385590029ce5129"
RAW_DOWNLOAD_MANIFEST_PATH = "outputs/kaggle/e22_bidir030_eval36_reference/DOWNLOAD_MANIFEST.json"
RAW_DOWNLOAD_MANIFEST_BYTES = 3_524
RAW_DOWNLOAD_MANIFEST_SHA256 = "1f567e2520cc75536886296c1b88724ea2c2776cd2aa6b52ceaaac6bca8ac12b"
RAW_RUNTIME_INTEGRITY_PATH = (
    "outputs/kaggle/e22_bidir030_eval36_reference/bidirectional_production_runtime_integrity.json"
)
RAW_RUNTIME_INTEGRITY_BYTES = 2_387
RAW_RUNTIME_INTEGRITY_SHA256 = "ae41130ee035d3ddcbaf2d0977f721429a52ffda8133fe1b877f51de5926278d"

IMAGE_MANIFEST_SHA256 = "6c1c59644daf7fe59458dc860f2e1783d1217be389a791ea54e1f611f5f848f4"
DEEPCENTER_CHECKPOINT_SHA256 = "8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0"
DEEPCENTER_MANIFEST_SHA256 = "1eedc1af72b10c464c6995013075310510b6f6e634450ff2bc170c67b89ce911"
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_RE = re.compile(r"[0-9a-f]{40,64}\Z")
CSV_INTEGER_RE = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")

EXPECTED_RAW_FILES = 1_188
EXPECTED_RAW_BYTES = 10_090_215
EXPECTED_IMAGE_FILES = 3_672
EXPECTED_IMAGE_BYTES = 15_932_872_938

E24_IMPORT_ROOTS = (
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
E24_IMPORT_BYTES = (
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
E24_IMPORT_SHA256 = (
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

FROZEN_EXECUTIONS = (
    ("safety_dry_run", "dry_run", "generation/safety_dry_run"),
    ("baseline_ab", "baseline", "generation/primary/AB/baseline"),
    ("candidate_ab", "candidate", "generation/primary/AB/candidate"),
    ("candidate_ba", "candidate", "generation/primary/BA/candidate"),
    ("baseline_ba", "baseline", "generation/primary/BA/baseline"),
)

# These are code-owned holds.  No input JSON boolean can remove them.
UNRESOLVED_PRODUCTION_HOLDS = (
    "HOLD_GT_VISIBLE",
    "HOLD_PROCESS_TREE_UNPROVEN",
    "HOLD_PUBLICATION_CONCURRENCY_UNPROVEN",
    "HOLD_RSS_UNMEASURABLE",
    "HOLD_TARGET_RUNTIME_UNCALIBRATED",
    "HOLD_TARGET_MEMORY_UNCALIBRATED",
    "HOLD_SCORING_NOT_RUN",
    "HOLD_INPUT_IMMUTABILITY_UNPROVEN",
    "HOLD_NETWORK_ISOLATION_UNPROVEN",
    "HOLD_SCORING_INTERFACE_INCOMPLETE",
    "HOLD_DEPENDENCY_INVENTORY_INCOMPLETE",
    "HOLD_PLATFORM_INVENTORY_INCOMPLETE",
    "HOLD_CPU_RAM_INVENTORY_INCOMPLETE",
    "HOLD_DEVICE_RUNTIME_INVENTORY_INCOMPLETE",
    "HOLD_LIVE_ARTIFACT_INVENTORY_INCOMPLETE",
    "HOLD_RAW_PROVENANCE_UNVERIFIED",
)

SOURCE_BINDINGS = (
    "src/biohub/st_r3_generation.py",
    "scripts/experiments/st_r3/st_r3_preregister.py",
    "scripts/experiments/st_r3/st_r3_generate.py",
    "tests/test_st_r3_generation.py",
    "src/biohub/evaluate.py",
    "src/biohub/st_r3_scoring.py",
    "src/biohub/public_postproc/production_adapter.py",
    "src/biohub/public_postproc/production_supervisor.py",
    "src/biohub/public_postproc/config.py",
    "src/biohub/public_postproc/divisions.py",
    "src/biohub/public_postproc/pipeline.py",
    "scripts/experiments/st_r3/st_r3_postproc_arm.py",
    "scripts/experiments/st_r3/st_r3_supervise_arm.py",
    "scripts/verify_eval36_images.py",
    "pyproject.toml",
    "uv.lock",
    "analysis/steal_twin_st_r3_eval_contract.md",
    "analysis/steal_twin_st_r3_adapter_appendix.md",
    "analysis/steal_twin_st_r3_supervisor_appendix.md",
    "analysis/st_r3_scoring_appendix.md",
)

FIXED_ENVIRONMENT = {
    "PYTHONHASHSEED": "0",
    "LC_ALL": "C",
    "LANG": "C",
    "TZ": "UTC",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "CUDA_VISIBLE_DEVICES": "",
}


class GenerationFailure(RuntimeError):
    """A stable, fail-closed generation error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PreregistrationSpec:
    run_dir: Path
    raw_geff_dir: Path
    image_view: Path
    image_ready_receipt: Path
    image_import_receipt: Path
    deepcenter_checkpoint: Path
    deepcenter_manifest: Path
    e23_parity_receipt: Path
    base1_receipt: Path
    primary_raw_provenance_receipt: Path
    secondary_raw_provenance_receipt: Path
    target_resources: Path
    gt_inventory: Path
    timeout_seconds: float


@dataclass(frozen=True)
class GenerationResult:
    status: str
    code: str
    run_dir: Path
    generation_manifest_sha256: str | None
    hold_path: Path
    holds: tuple[str, ...]


ArmRunner = Callable[[Sequence[str], Mapping[str, str]], subprocess.CompletedProcess[str]]


def canonical_json_bytes(value: object) -> bytes:
    """Encode canonical artifact JSON."""
    try:
        return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GenerationFailure("NONCANONICAL_JSON", "artifact is not finite canonical JSON") from exc


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _same_typed(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(_same_typed(left[key], right[key]) for key in left)
    if isinstance(left, (list, tuple)):
        return len(left) == len(right) and all(_same_typed(a, b) for a, b in zip(left, right, strict=True))
    return left == right


def _require_sha(value: object, label: str) -> str:
    if type(value) is not str or SHA_RE.fullmatch(value) is None:
        raise GenerationFailure("INVALID_SHA256", f"{label} must be lowercase SHA-256")
    return value


def _stat_signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_regular_stable(path: Path, *, max_bytes: int | None = None) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise GenerationFailure("UNSAFE_FILE", f"cannot safely open {path.name}") from exc
    try:
        before = os.fstat(fd)
        path_before = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or _stat_signature(before) != _stat_signature(path_before)
        ):
            raise GenerationFailure("UNSAFE_FILE", f"{path.name} is not an isolated regular file")
        if max_bytes is not None and before.st_size > max_bytes:
            raise GenerationFailure("FILE_TOO_LARGE", f"{path.name} exceeds its size limit")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(1_048_576, remaining))
            if not chunk:
                raise GenerationFailure("FILE_DRIFT", f"{path.name} ended during read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1):
            raise GenerationFailure("FILE_DRIFT", f"{path.name} grew during read")
        after = os.fstat(fd)
        path_after = os.stat(path, follow_symlinks=False)
        if _stat_signature(before) != _stat_signature(after) or _stat_signature(after) != _stat_signature(path_after):
            raise GenerationFailure("FILE_DRIFT", f"{path.name} changed during read")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _digest_regular(path: Path) -> tuple[int, str]:
    data = _read_regular_stable(path)
    return len(data), _sha256_bytes(data)


def _write_new_atomic(path: Path, data: bytes) -> None:
    """Publish one new file without replacing an existing pathname."""
    if path.is_absolute() is False:
        path = path.absolute()
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise GenerationFailure("UNSAFE_OUTPUT_PARENT", "artifact parent must be an existing real directory")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.tmp.", dir=parent)
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, 0o400)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short artifact write")
            view = view[written:]
        os.fsync(fd)
        os.close(fd)
        fd = -1
        try:
            os.link(temp_path, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise GenerationFailure("OUTPUT_COLLISION", f"refusing to replace {path.name}") from exc
        os.unlink(temp_path)
        directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        if temp_path.exists():
            temp_path.unlink()


def _load_canonical_json(
    path: Path,
    *,
    max_bytes: int = 16_777_216,
    reject_forbidden: bool = True,
) -> dict[str, Any]:
    data = _read_regular_stable(path, max_bytes=max_bytes)
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenerationFailure("INVALID_JSON", f"{path.name} is not strict JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != data:
        raise GenerationFailure("NONCANONICAL_JSON", f"{path.name} is not canonical JSON")
    if reject_forbidden:
        _reject_forbidden_content(value, path.name)
    return value


def _reject_forbidden_content(value: object, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_forbidden_content(key, label)
            _reject_forbidden_content(child, label)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_forbidden_content(child, label)
    elif isinstance(value, str):
        lowered = value.lower()
        if any(stem in lowered for stem in PUBLIC_FOUR):
            raise GenerationFailure("PUBLIC_FOUR_CONTAMINATION", f"{label} contains a public-four stem")
        if any(
            token in lowered
            for token in ("ground_truth", "ground-truth", "/gt/", "\\gt\\", "/data/train/", "\\data\\train\\")
        ):
            raise GenerationFailure("GT_PATH_VISIBLE", f"{label} contains a GT capability")


def _audit_sensitive_fds(fd_root: Path | None = None) -> None:
    """Reject an inherited descriptor visibly naming known GT/public-four data."""
    root = fd_root or (Path("/proc/self/fd") if Path("/proc/self/fd").is_dir() else Path("/dev/fd"))
    if not root.is_dir():
        raise GenerationFailure("FD_AUDIT_UNAVAILABLE", "cannot inspect inherited descriptors")
    try:
        entries = tuple(root.iterdir())
    except OSError as exc:
        raise GenerationFailure("FD_AUDIT_UNAVAILABLE", "cannot enumerate inherited descriptors") from exc
    for entry in entries:
        try:
            fd = int(entry.name)
        except ValueError:
            continue
        if fd <= 2:
            continue
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        _reject_forbidden_content(target, "inherited file descriptor")


def _portable_repo_path(path: Path, repo_root: Path, label: str) -> str:
    absolute = Path(os.path.abspath(path))
    try:
        relative = absolute.relative_to(repo_root)
    except ValueError as exc:
        raise GenerationFailure("PATH_OUTSIDE_REPOSITORY", f"{label} must be below the canonical repository") from exc
    pure = PurePosixPath(relative.as_posix())
    if not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
        raise GenerationFailure("INVALID_PATH", f"{label} is not a portable repository path")
    _reject_forbidden_content(relative.as_posix(), label)
    return relative.as_posix()


def _run_git(repo_root: Path, *args: str) -> str:
    process = subprocess.run(
        ("git", *args),
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise GenerationFailure("GIT_BINDING_FAILED", "git source binding failed")
    return process.stdout.strip()


def _source_binding(repo_root: Path, *, allowed_untracked_run: Path | None = None) -> dict[str, object]:
    commit = _run_git(repo_root, "rev-parse", "HEAD")
    git_tree_oid = _run_git(repo_root, "rev-parse", "HEAD^{tree}")
    if COMMIT_RE.fullmatch(commit) is None:
        raise GenerationFailure("GIT_BINDING_FAILED", "unexpected superproject commit")
    if re.fullmatch(r"[0-9a-f]{40}", git_tree_oid) is None:
        raise GenerationFailure("GIT_BINDING_FAILED", "unexpected superproject tree object")
    status_lines = _run_git(repo_root, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
    if allowed_untracked_run is not None:
        allowed_relative = allowed_untracked_run.absolute().relative_to(repo_root).as_posix()
        status_lines = [
            line
            for line in status_lines
            if not (line.startswith("?? ") and line[3:].startswith(f"{allowed_relative}/"))
        ]
    if status_lines:
        raise GenerationFailure("SOURCE_DIRTY", "superproject must be completely clean before preregistration")
    records = []
    for relative in SOURCE_BINDINGS:
        path = repo_root / relative
        size, digest = _digest_regular(path)
        records.append({"path": relative, "bytes": size, "sha256": digest})
    official = repo_root / "official"
    gitlink_line = _run_git(repo_root, "ls-tree", "HEAD", "official")
    fields = gitlink_line.split()
    if len(fields) < 3 or fields[1] != "commit":
        raise GenerationFailure("OFFICIAL_BINDING_FAILED", "official gitlink is missing")
    gitlink = fields[2]
    head = _run_git(official, "rev-parse", "HEAD")
    if (
        gitlink != OFFICIAL_REVIEWED_OID
        or head != OFFICIAL_REVIEWED_OID
        or _run_git(official, "status", "--porcelain=v1", "--untracked-files=all")
    ):
        raise GenerationFailure("OFFICIAL_DIRTY", "official submodule gitlink/head/clean binding failed")
    official_hashes = {}
    for relative in ("tracking_cellmot/metrics.py", "tracking_cellmot/division_metrics.py"):
        size, digest = _digest_regular(official / "src" / relative)
        official_hashes[relative] = {"bytes": size, "sha256": digest}
    return {
        "superproject_commit": commit,
        "git_tree_oid": git_tree_oid,
        "tracked_tree_clean": True,
        "files": records,
        "official": {
            "gitlink": gitlink,
            "head": head,
            "clean": True,
            "source_hashes": official_hashes,
        },
    }


def _tree_records(root: Path) -> list[dict[str, object]]:
    root = Path(os.path.abspath(root))
    if not root.is_dir() or root.is_symlink():
        raise GenerationFailure("UNSAFE_TREE", f"{root.name} must be a real directory")
    records: list[dict[str, object]] = []
    seen_casefold: set[str] = set()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        folded = relative.casefold()
        if folded in seen_casefold:
            raise GenerationFailure("CASE_COLLISION", f"tree contains a case-colliding path: {relative}")
        seen_casefold.add(folded)
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise GenerationFailure("UNSAFE_TREE", f"tree contains symlink/special entry: {relative}")
        if stat.S_ISREG(info.st_mode):
            size, digest = _digest_regular(path)
            records.append({"path": relative, "bytes": size, "sha256": digest})
    return records


def _inventory_value(kind: str, root: Path, records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": TREE_INVENTORY_SCHEMA,
        "kind": kind,
        "root_name": root.name,
        "records": records,
        "file_count": len(records),
        "total_bytes": sum(int(item["bytes"]) for item in records),
        "records_sha256": _sha256_bytes(canonical_json_bytes(records)),
    }


def _validate_raw_inventory(root: Path, records: list[dict[str, object]]) -> None:
    roots = tuple(path.name.removesuffix(".geff") for path in root.iterdir() if path.is_dir())
    if set(roots) != set(EVAL36) or len(roots) != 36:
        raise GenerationFailure("RAW_SET_MISMATCH", "raw GEFF roots do not equal frozen eval36")
    if len(records) != EXPECTED_RAW_FILES or sum(int(item["bytes"]) for item in records) != EXPECTED_RAW_BYTES:
        raise GenerationFailure("RAW_INVENTORY_MISMATCH", "raw GEFF count/bytes do not match the frozen bundle")


def _validate_image_inventory(root: Path, records: list[dict[str, object]]) -> None:
    roots = tuple(path.name.removesuffix(".zarr") for path in root.iterdir() if path.is_dir())
    if set(roots) != set(EVAL36) or len(roots) != 36:
        raise GenerationFailure("IMAGE_SET_MISMATCH", "image roots do not equal frozen eval36")
    if len(records) != EXPECTED_IMAGE_FILES or sum(int(item["bytes"]) for item in records) != EXPECTED_IMAGE_BYTES:
        raise GenerationFailure("IMAGE_INVENTORY_MISMATCH", "image count/bytes do not match the frozen manifest")


def _resolve_repo_evidence_path(repo_root: Path, relative: object, label: str) -> Path:
    """Resolve a receipt-only evidence path without copying sensitive payloads."""
    if type(relative) is not str:
        raise GenerationFailure("PREREQUISITE_SCHEMA", f"{label} path is not text")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
        raise GenerationFailure("PREREQUISITE_SCHEMA", f"{label} path is not portable")
    path = repo_root.joinpath(*pure.parts)
    try:
        path.absolute().relative_to(repo_root)
    except ValueError as exc:
        raise GenerationFailure("PREREQUISITE_SCHEMA", f"{label} escapes the repository") from exc
    return path


def _validate_artifact_evidence(
    repo_root: Path,
    value: object,
    label: str,
    *,
    expected_sha256: str | None = None,
    expected_bytes: int | None = None,
) -> Path:
    if type(value) is not dict or set(value) != {"path", "bytes", "sha256"}:
        raise GenerationFailure("PREREQUISITE_SCHEMA", f"{label} artifact ref is malformed")
    if type(value["bytes"]) is not int or value["bytes"] < 0:
        raise GenerationFailure("PREREQUISITE_SCHEMA", f"{label} byte count is malformed")
    digest = _require_sha(value["sha256"], label)
    if expected_sha256 is not None and digest != expected_sha256:
        raise GenerationFailure("PREREQUISITE_EVIDENCE_MISMATCH", f"{label} digest is not frozen")
    if expected_bytes is not None and value["bytes"] != expected_bytes:
        raise GenerationFailure("PREREQUISITE_EVIDENCE_MISMATCH", f"{label} byte count is not frozen")
    path = _resolve_repo_evidence_path(repo_root, value["path"], label)
    current_bytes, current_sha = _digest_regular(path)
    if current_bytes != value["bytes"] or current_sha != digest:
        raise GenerationFailure("PREREQUISITE_EVIDENCE_DRIFT", f"{label} artifact drifted")
    return path


def _validate_tree_evidence(
    repo_root: Path,
    value: object,
    label: str,
    *,
    files: int,
    total_bytes: int,
    tree_sha256: str,
) -> Path:
    expected = {"path", "files", "bytes", "tree_sha256"}
    if type(value) is not dict or set(value) != expected:
        raise GenerationFailure("PREREQUISITE_SCHEMA", f"{label} tree ref is malformed")
    if value["files"] != files or value["bytes"] != total_bytes or value["tree_sha256"] != tree_sha256:
        raise GenerationFailure("PREREQUISITE_EVIDENCE_MISMATCH", f"{label} frozen tree values differ")
    path = _resolve_repo_evidence_path(repo_root, value["path"], label)
    records: list[dict[str, object]] = []
    seen: set[str] = set()
    for directory, directories, filenames in os.walk(path, followlinks=True):
        directories.sort()
        filenames.sort()
        directory_path = Path(directory)
        for child in directories:
            child_path = directory_path / child
            if child_path.is_symlink():
                try:
                    child_path.resolve(strict=True).relative_to(repo_root)
                except (OSError, ValueError) as exc:
                    raise GenerationFailure("PREREQUISITE_EVIDENCE_DRIFT", f"{label} has an unsafe symlink") from exc
        for filename in filenames:
            child_path = directory_path / filename
            relative = child_path.relative_to(path).as_posix()
            if relative.casefold() in seen or child_path.is_symlink():
                raise GenerationFailure("PREREQUISITE_EVIDENCE_DRIFT", f"{label} has colliding/symlink files")
            seen.add(relative.casefold())
            size, digest = _digest_regular(child_path)
            records.append({"path": relative, "bytes": size, "sha256": digest})
    records.sort(key=lambda item: str(item["path"]))
    legacy_lines = b"".join(f"{item['sha256']}  ./{item['path']}\n".encode() for item in records)
    if (
        len(records) != files
        or sum(int(item["bytes"]) for item in records) != total_bytes
        or _sha256_bytes(legacy_lines) != tree_sha256
    ):
        raise GenerationFailure("PREREQUISITE_EVIDENCE_DRIFT", f"{label} tree drifted")
    return path


def _submission_graph_value(
    path: Path,
) -> tuple[dict[str, dict[str, list[list[int]]]], dict[str, tuple[int, int, int]]]:
    """Preserve original integer IDs and coordinates without scoring imports."""

    def integer(row: Mapping[str, str], key: str) -> int:
        text = row[key]
        if CSV_INTEGER_RE.fullmatch(text) is None:
            raise GenerationFailure("TYPED_GRAPH_NONINTEGER", f"submission {key} is not canonical integer syntax")
        return int(text)

    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != [
                "id",
                "dataset",
                "row_type",
                "node_id",
                "t",
                "z",
                "y",
                "x",
                "source_id",
                "target_id",
            ]:
                raise GenerationFailure("PREREQUISITE_GRAPH", "submission header drifted")
            graphs: dict[str, dict[str, list[list[int]]]] = {}
            node_ids: dict[str, set[int]] = {}
            edge_ids: dict[str, set[int]] = {}
            for row in reader:
                dataset = row["dataset"]
                graph = graphs.setdefault(dataset, {"nodes": [], "edges": []})
                nodes_seen = node_ids.setdefault(dataset, set())
                edges_seen = edge_ids.setdefault(dataset, set())
                if row["row_type"] == "node":
                    node_id = integer(row, "node_id")
                    if node_id in nodes_seen:
                        raise GenerationFailure("PREREQUISITE_GRAPH", "duplicate submission node ID")
                    nodes_seen.add(node_id)
                    graph["nodes"].append([node_id, *(integer(row, key) for key in ("t", "z", "y", "x"))])
                elif row["row_type"] == "edge":
                    edge_id = integer(row, "id")
                    if edge_id in edges_seen:
                        raise GenerationFailure("PREREQUISITE_GRAPH", "duplicate submission edge identity")
                    edges_seen.add(edge_id)
                    graph["edges"].append([edge_id, integer(row, "source_id"), integer(row, "target_id")])
                else:
                    raise GenerationFailure("PREREQUISITE_GRAPH", "submission row type drifted")
    except (OSError, UnicodeError, csv.Error, KeyError, ValueError) as exc:
        raise GenerationFailure("PREREQUISITE_GRAPH", "submission cannot be normalized") from exc
    normalized: dict[str, dict[str, list[list[int]]]] = {}
    counts: dict[str, tuple[int, int, int]] = {}
    for dataset in sorted(graphs):
        nodes = sorted(graphs[dataset]["nodes"], key=lambda item: item[0])
        edges = sorted(graphs[dataset]["edges"], key=lambda item: item[0])
        known_nodes = node_ids[dataset]
        if any(source not in known_nodes or target not in known_nodes for _, source, target in edges):
            raise GenerationFailure("PREREQUISITE_GRAPH", "submission edge references unknown node")
        forks: dict[int, int] = {}
        for _, source, _target in edges:
            forks[source] = forks.get(source, 0) + 1
        normalized[dataset] = {"nodes": nodes, "edges": edges}
        counts[dataset] = (len(nodes), len(edges), sum(value >= 2 for value in forks.values()))
    return normalized, counts


def _submission_graph_evidence(path: Path) -> tuple[str, dict[str, tuple[int, int, int]]]:
    normalized, counts = _submission_graph_value(path)
    raw = json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return _sha256_bytes(raw), counts


def _legacy_official_graph_evidence(path: Path) -> tuple[str, dict[str, tuple[int, int, int]]]:
    """Reproduce only the frozen E23 official-input remapping."""
    graphs, counts = _submission_graph_value(path)
    normalized: dict[str, dict[str, list[list[int | float]]]] = {}
    for dataset, graph in graphs.items():
        id_map = {node[0]: index for index, node in enumerate(graph["nodes"])}
        nodes = [
            [index, node[1], float(node[2]), float(node[3]), float(node[4])]
            for index, node in enumerate(graph["nodes"])
        ]
        edges = [[index, id_map[edge[1]], id_map[edge[2]]] for index, edge in enumerate(graph["edges"])]
        normalized[dataset] = {"nodes": nodes, "edges": edges}
    raw = json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return _sha256_bytes(raw), counts


def _publish_typed_graph(run_dir: Path, executions: Mapping[str, dict[str, Any]], arm: str) -> dict[str, object]:
    keys = ("baseline_ab", "baseline_ba") if arm == "baseline" else ("candidate_ab", "candidate_ba")
    values = [_submission_graph_value(run_dir / executions[key]["path"] / "submission.csv") for key in keys]
    if values[0] != values[1]:
        raise GenerationFailure("TYPED_GRAPH_REPLAY_MISMATCH", f"{arm} canonical typed graph replay differs")
    graphs, counts = values[0]
    artifact = {
        "schema_version": TYPED_GRAPH_SCHEMA,
        "arm": arm,
        "datasets": list(EVAL36),
        "graphs": graphs,
        "counts": {dataset: {"nodes": item[0], "edges": item[1], "forks": item[2]} for dataset, item in counts.items()},
    }
    if list(graphs) != sorted(EVAL36):
        raise GenerationFailure("TYPED_GRAPH_DATASETS", f"{arm} typed graph dataset set/order drifted")
    output = run_dir / "generation" / "canonical" / arm / "typed_graph.json"
    output.parent.mkdir(parents=True, mode=0o700)
    raw = canonical_json_bytes(artifact)
    _write_new_atomic(output, raw)
    return {
        "path": output.relative_to(run_dir).as_posix(),
        "bytes": len(raw),
        "sha256": _sha256_bytes(raw),
        "submission_sha256": executions[keys[0]]["submission_sha256"],
    }


def _csv_common_equal(reference: Path, output: Path, excluded: frozenset[str]) -> bool:
    def load(path: Path) -> tuple[list[str], dict[str, dict[str, str]]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise GenerationFailure("PREREQUISITE_TELEMETRY", "telemetry header is malformed")
            rows = list(reader)
        datasets = [row.get("dataset", "") for row in rows]
        if not datasets or len(datasets) != len(set(datasets)):
            raise GenerationFailure("PREREQUISITE_TELEMETRY", "telemetry dataset rows are malformed")
        return reader.fieldnames, {row["dataset"]: row for row in rows}

    ref_fields, ref_rows = load(reference)
    out_fields, out_rows = load(output)
    common = set(ref_fields) - set(excluded)
    return (
        common <= set(out_fields)
        and set(ref_rows) == set(out_rows)
        and all(all(ref_rows[dataset][field] == out_rows[dataset][field] for field in common) for dataset in ref_rows)
    )


def _validate_prerequisite_semantics(
    value: Mapping[str, object], repo_root: Path, expected_schema: str, label: str
) -> None:
    """Validate all frozen evidence independently; PASS booleans are never authority."""

    def exact_path(ref: object, expected: str, name: str) -> None:
        if type(ref) is not dict or ref.get("path") != expected:
            raise GenerationFailure("PREREQUISITE_EVIDENCE_MISMATCH", f"{name} path is not canonical")

    if expected_schema == E23_PARITY_RECEIPT_SCHEMA:
        if set(value["inputs"]) != {"raw_geff_tree", "test_image_tree", "deepcenter"}:
            raise GenerationFailure("PREREQUISITE_SCHEMA", f"{label} inputs are not closed")
        exact_path(
            value["inputs"]["raw_geff_tree"],
            "outputs/kaggle/e22_bidir030_public4_raw/tracking_repo/predictions/unknown/unet_transformer/split_0",
            "E23 raw GEFF",
        )
        exact_path(value["inputs"]["test_image_tree"], "data/test", "E23 image tree")
        _validate_tree_evidence(
            repo_root,
            value["inputs"]["raw_geff_tree"],
            "E23 raw GEFF",
            files=132,
            total_bytes=1_583_021,
            tree_sha256="5fc5fb5e51d127612421970ed66f0ba4229f020940ed458dfdf0fa316f2e8bc1",
        )
        _validate_tree_evidence(
            repo_root,
            value["inputs"]["test_image_tree"],
            "E23 image tree",
            files=408,
            total_bytes=1_906_332_008,
            tree_sha256="0b9e6e060437104fb261b388f45eae494abcca59155b4bc9fc4fac24bedd9bbd",
        )
        deep = value["inputs"]["deepcenter"]
        if type(deep) is not dict or set(deep) != {"checkpoint", "manifest"}:
            raise GenerationFailure("PREREQUISITE_SCHEMA", "E23 DeepCenter binding is malformed")
        exact_path(
            deep["checkpoint"],
            "outputs/kaggle/e23_artifacts/pilkwang/biohub-deepcenter-unet3d-center-prior-v1/weights/full_frame_center/best.pt",
            "E23 checkpoint",
        )
        exact_path(
            deep["manifest"],
            "outputs/kaggle/e23_artifacts/pilkwang/biohub-deepcenter-unet3d-center-prior-v1/ARTIFACT_MANIFEST.json",
            "E23 manifest",
        )
        _validate_artifact_evidence(
            repo_root, deep["checkpoint"], "E23 checkpoint", expected_sha256=DEEPCENTER_CHECKPOINT_SHA256
        )
        _validate_artifact_evidence(
            repo_root, deep["manifest"], "E23 manifest", expected_sha256=DEEPCENTER_MANIFEST_SHA256
        )
        reference_keys = {"submission", "run_stats", "official_json"}
        if set(value["references"]) != reference_keys or set(value["outputs"]) != reference_keys:
            raise GenerationFailure("PREREQUISITE_SCHEMA", "E23 reference/output evidence is not closed")
        exact_path(
            value["references"]["submission"], "outputs/kaggle/e23_reference/submission.csv", "E23 reference submission"
        )
        exact_path(
            value["references"]["run_stats"], "outputs/kaggle/e23_reference/run_stats.csv", "E23 reference telemetry"
        )
        exact_path(
            value["references"]["official_json"],
            "outputs/kaggle/e23_reference/official_public4_score.json",
            "E23 reference official JSON",
        )
        exact_path(
            value["outputs"]["submission"], "outputs/local/e23_parity_public4/submission.csv", "E23 output submission"
        )
        exact_path(
            value["outputs"]["run_stats"], "outputs/local/e23_parity_public4/run_stats.csv", "E23 output telemetry"
        )
        exact_path(
            value["outputs"]["official_json"],
            "outputs/local/e23_parity_public4/official_score.json",
            "E23 output official JSON",
        )
        ref_sub = _validate_artifact_evidence(
            repo_root,
            value["references"]["submission"],
            "E23 reference submission",
            expected_sha256="33c179b0449b9cdd186f06a653cddc8cf12359f008982f6713cdf30784a52e6a",
            expected_bytes=12_499_233,
        )
        out_sub = _validate_artifact_evidence(
            repo_root,
            value["outputs"]["submission"],
            "E23 output submission",
            expected_sha256="33c179b0449b9cdd186f06a653cddc8cf12359f008982f6713cdf30784a52e6a",
            expected_bytes=12_499_233,
        )
        ref_stats = _validate_artifact_evidence(
            repo_root,
            value["references"]["run_stats"],
            "E23 reference telemetry",
            expected_sha256="19f9a0b5b6bb3c903b3dd3d8f6cb25cc9f90a201fae009b3505b140b432fd956",
            expected_bytes=3_041,
        )
        out_stats = _validate_artifact_evidence(repo_root, value["outputs"]["run_stats"], "E23 output telemetry")
        ref_official = _validate_artifact_evidence(
            repo_root,
            value["references"]["official_json"],
            "E23 reference official JSON",
            expected_sha256="3afc4a1a5f4319daa27c92eb1486aed010d0e7e8231ad408bd7d2682b36ba71e",
            expected_bytes=1_865,
        )
        out_official = _validate_artifact_evidence(
            repo_root,
            value["outputs"]["official_json"],
            "E23 output official JSON",
            expected_sha256="3afc4a1a5f4319daa27c92eb1486aed010d0e7e8231ad408bd7d2682b36ba71e",
            expected_bytes=1_865,
        )
        ref_graph, ref_counts = _legacy_official_graph_evidence(ref_sub)
        out_graph, out_counts = _legacy_official_graph_evidence(out_sub)
        expected_counts = {
            "44b6_0113de3b": (25_485, 24_768, 57),
            "44b6_0b24845f": (19_905, 18_653, 77),
            "6bba_05b6850b": (6_142, 5_943, 11),
            "6bba_05db0fb1": (70_675, 68_555, 118),
        }
        if (
            ref_graph != "7c71134d70413986f3e557c91b59db019260d27a93e438ba3770fd5c464338fd"
            or out_graph != ref_graph
            or ref_counts != expected_counts
            or out_counts != expected_counts
            or _read_regular_stable(ref_official) != _read_regular_stable(out_official)
            or not _csv_common_equal(
                ref_stats,
                out_stats,
                frozenset(
                    {
                        "predict_minutes_total",
                        "experiment_tag",
                        "safe_division_geometric_candidates",
                        "safe_division_mutual_nn_rejected",
                        "safe_division_divergence_rejected",
                    }
                ),
            )
        ):
            raise GenerationFailure("PREREQUISITE_EVIDENCE_MISMATCH", "E23 graph/telemetry/official parity failed")
        expected_checks = {
            "submission_bytes_equal",
            "typed_graph_equal",
            "graph_counts_equal",
            "fork_counts_equal",
            "telemetry_common_fields_equal",
            "official_json_equal",
            "overall_pass",
        }
    elif expected_schema == BASE1_RECEIPT_SCHEMA:
        if set(value["inputs"]) != {"raw_geff_tree"}:
            raise GenerationFailure("PREREQUISITE_SCHEMA", "base1 inputs are not closed")
        exact_path(value["inputs"]["raw_geff_tree"], "outputs/local/eval4_raw_geffs", "base1 raw GEFF")
        _validate_tree_evidence(
            repo_root,
            value["inputs"]["raw_geff_tree"],
            "base1 raw GEFF",
            files=132,
            total_bytes=1_448_288,
            tree_sha256="7148a3adabe187768a8ef8eb27009b6a27f96f6a079b8f274cd00587b9cadb42",
        )
        if set(value["references"]) != {"submission", "run_stats"} or set(value["outputs"]) != {
            "submission",
            "run_stats",
        }:
            raise GenerationFailure("PREREQUISITE_SCHEMA", "base1 reference/output evidence is not closed")
        exact_path(
            value["references"]["submission"], "outputs/local/eval4_base1/submission.csv", "base1 reference submission"
        )
        exact_path(
            value["references"]["run_stats"], "outputs/local/eval4_base1/run_stats.csv", "base1 reference telemetry"
        )
        exact_path(
            value["outputs"]["submission"], "outputs/local/e23_parity_base1/submission.csv", "base1 output submission"
        )
        exact_path(
            value["outputs"]["run_stats"], "outputs/local/e23_parity_base1/run_stats.csv", "base1 output telemetry"
        )
        ref_sub = _validate_artifact_evidence(
            repo_root,
            value["references"]["submission"],
            "base1 reference submission",
            expected_sha256="56b8fab98992bc5c6ed1dcaba32ad7116ebbf6c185a5fcc31ed39cc56fb992ab",
            expected_bytes=11_320_837,
        )
        out_sub = _validate_artifact_evidence(
            repo_root,
            value["outputs"]["submission"],
            "base1 output submission",
            expected_sha256="56b8fab98992bc5c6ed1dcaba32ad7116ebbf6c185a5fcc31ed39cc56fb992ab",
            expected_bytes=11_320_837,
        )
        ref_stats = _validate_artifact_evidence(
            repo_root, value["references"]["run_stats"], "base1 reference telemetry"
        )
        out_stats = _validate_artifact_evidence(repo_root, value["outputs"]["run_stats"], "base1 output telemetry")
        if _submission_graph_evidence(ref_sub) != _submission_graph_evidence(out_sub) or not _csv_common_equal(
            ref_stats,
            out_stats,
            frozenset({"predict_minutes_total", "experiment_tag", "deepcenter_gap_bypassed_synthetic_node"}),
        ):
            raise GenerationFailure("PREREQUISITE_EVIDENCE_MISMATCH", "base1 graph/telemetry equality failed")
        with out_stats.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        zero = {
            "centroid_refine_examined",
            "centroid_refine_moved",
            "centroid_refine_no_signal",
            "centroid_refine_rejected_shift",
            "deepcenter_gap_bypassed_observed_node",
            "safe_division_geometric_candidates",
            "safe_division_mutual_nn_rejected",
            "safe_division_divergence_rejected",
            "steal_twin_planned_edges_removed",
            "steal_twin_planned_edges_added",
            "steal_twin_edges_removed",
            "steal_twin_edges_added",
        }
        if any(not zero <= set(row) or any(row[key] != "0" for key in zero) for row in rows):
            raise GenerationFailure("PREREQUISITE_EVIDENCE_MISMATCH", "base1 added counters are not zero")
        expected_checks = {
            "submission_bytes_equal",
            "typed_graph_equal",
            "common_telemetry_equal",
            "twin_counters_zero",
            "overall_pass",
        }
    else:
        raise GenerationFailure("PREREQUISITE_SCHEMA", "unknown prerequisite receipt schema")
    if set(value["checks"]) != expected_checks or any(value["checks"][name] is not True for name in expected_checks):
        raise GenerationFailure("PREREQUISITE_NOT_PASS", f"{label} exact check set is not PASS")


def _expected_prerequisite_command(schema: str) -> tuple[list[str], dict[str, str]]:
    deep_root = "outputs/kaggle/e23_artifacts/pilkwang/biohub-deepcenter-unet3d-center-prior-v1"
    checkpoint = f"{deep_root}/weights/full_frame_center/best.pt"
    if schema == E23_PARITY_RECEIPT_SCHEMA:
        return (
            [
                "uv",
                "run",
                "--frozen",
                "--extra",
                "deepcenter",
                "python",
                "scripts/postproc_geffs.py",
                "--geff-dir",
                "outputs/kaggle/e22_bidir030_public4_raw/tracking_repo/predictions/unknown/unet_transformer/split_0",
                "--test-dir",
                "data/test",
                "--profile",
                "e23",
                "--set",
                f"BIOHUB_DEEPCENTER_CHECKPOINT={checkpoint}",
                "--set",
                f"BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT={checkpoint}",
                "--set",
                f"BIOHUB_DEEPCENTER_MANIFEST={deep_root}/ARTIFACT_MANIFEST.json",
                "--set",
                f"BIOHUB_DEEPCENTER_MANIFEST_DEFAULT={deep_root}/ARTIFACT_MANIFEST.json",
                "--out",
                "outputs/local/e23_parity_public4/submission.csv",
                "--run-stats",
                "outputs/local/e23_parity_public4/run_stats.csv",
            ],
            {"PYTHONHASHSEED": "0", "CUDA_VISIBLE_DEVICES": ""},
        )
    if schema == BASE1_RECEIPT_SCHEMA:
        return (
            [
                "uv",
                "run",
                "--frozen",
                "python",
                "scripts/postproc_geffs.py",
                "--geff-dir",
                "outputs/local/eval4_raw_geffs",
                "--test-dir",
                "data/train",
                "--profile",
                "base1",
                "--out",
                "outputs/local/e23_parity_base1/submission.csv",
                "--run-stats",
                "outputs/local/e23_parity_base1/run_stats.csv",
            ],
            {"PYTHONHASHSEED": "0"},
        )
    raise GenerationFailure("PREREQUISITE_SCHEMA", "unknown prerequisite command schema")


def _validate_prerequisite_command(value: Mapping[str, object], schema: str, label: str) -> None:
    expected_argv, expected_environment = _expected_prerequisite_command(schema)
    if value.get("command") != {"argv": expected_argv, "cwd": "."}:
        raise GenerationFailure("PREREQUISITE_SCHEMA", f"{label} command is not the exact canonical argv/cwd")
    if value.get("environment") != expected_environment:
        raise GenerationFailure("PREREQUISITE_SCHEMA", f"{label} environment is not the exact canonical mapping")


def _receipt_ref(
    path: Path,
    repo_root: Path,
    label: str,
    expected_schema: str,
    source_binding: Mapping[str, object],
) -> dict[str, object]:
    # These prerequisite receipts may legitimately contain public-four evidence.
    # Only their opaque digest/verdict reference enters the ST-R3 run.
    value = _load_canonical_json(path, reject_forbidden=False)
    expected_keys = {
        "schema_version",
        "status",
        "created_utc",
        "source",
        "command",
        "environment",
        "inputs",
        "references",
        "outputs",
        "checks",
    }
    if set(value) != expected_keys or value.get("schema_version") != expected_schema or value.get("status") != "PASS":
        raise GenerationFailure("PREREQUISITE_NOT_PASS", f"{label} does not have a frozen PASS verdict")
    _strict_utc(value["created_utc"], f"{label} created_utc")
    receipt_source = value["source"]
    source_keys = {
        "commit",
        "git_tree_oid",
        "tracked_tree_clean",
        "official_gitlink",
        "official_head",
        "official_clean",
        "files",
    }
    official = source_binding["official"]
    if (
        type(receipt_source) is not dict
        or set(receipt_source) != source_keys
        or receipt_source["commit"] != source_binding["superproject_commit"]
        or receipt_source["git_tree_oid"] != source_binding["git_tree_oid"]
        or receipt_source["tracked_tree_clean"] is not True
        or receipt_source["official_gitlink"] != official["gitlink"]
        or receipt_source["official_head"] != official["head"]
        or receipt_source["official_clean"] is not True
        or type(receipt_source["files"]) is not list
    ):
        raise GenerationFailure("PREREQUISITE_SOURCE_DRIFT", f"{label} is not bound to this clean source")
    source_files = receipt_source["files"]
    if not source_files:
        raise GenerationFailure("PREREQUISITE_SCHEMA", f"{label} source file inventory is empty")
    source_paths: list[str] = []
    for record in source_files:
        if (
            type(record) is not dict
            or set(record) != {"path", "bytes", "sha256"}
            or type(record["path"]) is not str
            or type(record["bytes"]) is not int
            or record["bytes"] < 0
        ):
            raise GenerationFailure("PREREQUISITE_SCHEMA", f"{label} source file ref is malformed")
        _require_sha(record["sha256"], f"{label} source file")
        source_path = _resolve_repo_path(repo_root, record["path"], f"{label} source file")
        current_bytes, current_sha = _digest_regular(source_path)
        if current_bytes != record["bytes"] or current_sha != record["sha256"]:
            raise GenerationFailure("PREREQUISITE_SOURCE_DRIFT", f"{label} source file drifted")
        source_paths.append(record["path"])
    expected_source_paths = sorted(SOURCE_BINDINGS)
    if source_paths != expected_source_paths or len(source_paths) != len(set(path.casefold() for path in source_paths)):
        raise GenerationFailure("PREREQUISITE_SCHEMA", f"{label} source files are unordered or collide")
    command = value["command"]
    if (
        type(command) is not dict
        or set(command) != {"argv", "cwd"}
        or type(command["argv"]) is not list
        or not command["argv"]
        or any(type(item) is not str or not item for item in command["argv"])
        or type(command["cwd"]) is not str
    ):
        raise GenerationFailure("PREREQUISITE_SCHEMA", f"{label} command binding is malformed")
    _validate_prerequisite_command(value, expected_schema, label)
    if type(value["environment"]) is not dict or any(
        type(key) is not str or type(item) is not str for key, item in value["environment"].items()
    ):
        raise GenerationFailure("PREREQUISITE_SCHEMA", f"{label} environment binding is malformed")
    secret_names = ("TOKEN", "PASSWORD", "SECRET", "COOKIE", "AUTH", "KEY")
    if any(any(token in key.upper() for token in secret_names) for key in value["environment"]):
        raise GenerationFailure("PREREQUISITE_SECRET", f"{label} environment contains a secret-shaped key")
    for child in ("inputs", "references", "outputs"):
        if type(value[child]) is not dict or not value[child]:
            raise GenerationFailure("PREREQUISITE_SCHEMA", f"{label} {child} binding is empty or malformed")
    _validate_prerequisite_semantics(value, repo_root, expected_schema, label)
    size, digest = _digest_regular(path)
    return {
        "path": _portable_repo_path(path, repo_root, label),
        "bytes": size,
        "sha256": digest,
        "verdict": "PASS",
    }


def _target_resources(path: Path, repo_root: Path) -> dict[str, object]:
    value = _load_canonical_json(path)
    expected = {"schema_version", "declared_ram_bytes", "declared_wall_seconds", "source_snapshot"}
    if set(value) != expected or value["schema_version"] != TARGET_RESOURCE_SCHEMA:
        raise GenerationFailure("TARGET_RESOURCE_SCHEMA", "target resource declaration has the wrong schema")
    ram, wall = value["declared_ram_bytes"], value["declared_wall_seconds"]
    if type(ram) is not int or ram <= 0 or type(wall) not in (int, float) or isinstance(wall, bool):
        raise GenerationFailure("TARGET_RESOURCE_SCHEMA", "target resource limits must be positive numbers")
    if not math.isfinite(float(wall)) or float(wall) <= 0:
        raise GenerationFailure("TARGET_RESOURCE_SCHEMA", "target wall limit must be finite and positive")
    source = value["source_snapshot"]
    if type(source) is not dict or set(source) != {"path", "bytes", "sha256"}:
        raise GenerationFailure("TARGET_RESOURCE_SCHEMA", "target source snapshot ref is malformed")
    _require_sha(source["sha256"], "target source snapshot")
    if type(source["bytes"]) is not int or source["bytes"] < 0:
        raise GenerationFailure("TARGET_RESOURCE_SCHEMA", "target source snapshot bytes are invalid")
    source_path = _resolve_repo_path(repo_root, source["path"], "target source snapshot")
    size, digest = _digest_regular(source_path)
    if size != source["bytes"] or digest != source["sha256"]:
        raise GenerationFailure("TARGET_RESOURCE_DRIFT", "target source snapshot ref drifted")
    ref_size, ref_digest = _digest_regular(path)
    return {
        "ref": {
            "path": _portable_repo_path(path, repo_root, "target resources"),
            "bytes": ref_size,
            "sha256": ref_digest,
        },
        "declared_ram_bytes": ram,
        "declared_wall_seconds": float(wall),
        "source_snapshot": source,
    }


def _strict_utc(value: object, label: str) -> tuple[str, dt.datetime]:
    if type(value) is not str or not value.endswith("Z"):
        raise GenerationFailure("TIMESTAMP_SCHEMA", f"{label} must be canonical UTC")
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
    except ValueError as exc:
        raise GenerationFailure("TIMESTAMP_SCHEMA", f"{label} must use second precision UTC") from exc
    return value, parsed


def _image_ready_ref(
    path: Path, repo_root: Path, image_view: Path, import_receipt_path: Path
) -> tuple[dict[str, object], list[dict[str, object]]]:
    if _portable_repo_path(path, repo_root, "image READY receipt") != CANONICAL_READY_PATH:
        raise GenerationFailure("IMAGE_READY_AUTHORITY", "image READY receipt is not the reviewed canonical path")
    if _portable_repo_path(import_receipt_path, repo_root, "image import receipt") != CANONICAL_IMPORT_PATH:
        raise GenerationFailure("IMAGE_READY_AUTHORITY", "image import receipt is not the reviewed canonical path")
    ready_size, ready_sha = _digest_regular(path)
    if ready_sha != CANONICAL_READY_SHA256:
        raise GenerationFailure("IMAGE_READY_AUTHORITY", "image READY receipt digest is not reviewed")
    if sorted(item.name for item in path.parent.iterdir()) != ["IMAGE_CONTENT_INVENTORY.json", "READY.json"]:
        raise GenerationFailure("IMAGE_READY_LATEST", "READY evidence directory is not a fresh two-artifact seal")
    value = _load_canonical_json(path)
    expected_keys = {
        "data_root_identity",
        "decoded",
        "digest_scope",
        "import_receipt",
        "inventory",
        "manifest",
        "schema_version",
        "status",
        "verifier",
        "created_utc",
        "ready_content_sha256",
    }
    if set(value) != expected_keys or value["schema_version"] != "biohub.eval36_images_ready.v1":
        raise GenerationFailure("IMAGE_READY_SCHEMA", "image READY receipt schema mismatch")
    if value["status"] != "READY":
        raise GenerationFailure("IMAGE_READY_SCHEMA", "image READY receipt is not READY")
    created_utc, _ = _strict_utc(value["created_utc"], "image READY created_utc")
    core = {key: item for key, item in value.items() if key not in {"created_utc", "ready_content_sha256"}}
    if (
        _sha256_bytes(canonical_json_bytes(core)) != _require_sha(value["ready_content_sha256"], "image READY content")
        or value["ready_content_sha256"] != CANONICAL_READY_CONTENT_SHA256
    ):
        raise GenerationFailure("IMAGE_READY_DRIFT", "image READY content digest mismatch")
    manifest = value["manifest"]
    if manifest != {
        "bytes": 1_187_624,
        "lines": 24_887,
        "path": "manifest.csv",
        "sha256": IMAGE_MANIFEST_SHA256,
    }:
        raise GenerationFailure("IMAGE_READY_MISMATCH", "image READY manifest binding mismatch")
    if value["digest_scope"] != READY_DIGEST_SCOPE:
        raise GenerationFailure("IMAGE_READY_MISMATCH", "image READY digest scope drifted")
    import_summary = value["import_receipt"]
    if type(import_summary) is not dict or set(import_summary) != {
        "bytes",
        "reference",
        "sha256",
        "status",
        "installed",
        "skipped",
        "validated",
    }:
        raise GenerationFailure("IMAGE_READY_SCHEMA", "image import receipt summary is malformed")
    if (
        import_summary["status"] != "PASS"
        or import_summary["installed"] != 1_487
        or import_summary["skipped"] != 43
        or import_summary["validated"] != 1_530
        or import_summary["reference"] != import_receipt_path.name
        or import_receipt_path.name != f"eval36-import-{import_summary['sha256']}.json"
    ):
        raise GenerationFailure("IMAGE_READY_MISMATCH", "image import receipt summary drifted")
    import_size, import_sha = _digest_regular(import_receipt_path)
    if (
        import_size != import_summary["bytes"]
        or import_sha != _require_sha(import_summary["sha256"], "image import receipt")
        or import_sha != CANONICAL_IMPORT_SHA256
    ):
        raise GenerationFailure("IMAGE_READY_DRIFT", "referenced image import receipt drifted")
    import_value = _load_canonical_json(import_receipt_path, max_bytes=4_000_000, reject_forbidden=False)
    if (
        set(import_value)
        != {
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
        or import_value["schema_version"] != 1
        or import_value["status"] != "PASS"
        or import_value["manifest_csv_sha256"] != IMAGE_MANIFEST_SHA256
        or import_value["installed"] != 1_487
        or import_value["skipped"] != 43
        or import_value["validated"] != 1_530
        or type(import_value["files"]) is not list
        or len(import_value["files"]) != 1_530
    ):
        raise GenerationFailure("IMAGE_IMPORT_SCHEMA", "referenced image import receipt content drifted")
    import_identity = import_value["data_root_identity"]
    if (
        type(import_identity) is not dict
        or set(import_identity) != {"device", "inode"}
        or any(type(import_identity[key]) is not int for key in ("device", "inode"))
        or type(import_value["archives"]) is not list
        or len(import_value["archives"]) != 15
    ):
        raise GenerationFailure("IMAGE_IMPORT_SCHEMA", "image import source identity/archive count drifted")
    for archive, root, archive_bytes, archive_sha in zip(
        import_value["archives"], E24_IMPORT_ROOTS, E24_IMPORT_BYTES, E24_IMPORT_SHA256, strict=True
    ):
        if archive != {
            "bytes": archive_bytes,
            "name": f"{root}.tar",
            "root": root,
            "sha256": archive_sha,
        }:
            raise GenerationFailure("IMAGE_IMPORT_SCHEMA", "image import archive pin drifted")
    import_paths: list[str] = []
    import_file_evidence: dict[str, tuple[int, str]] = {}
    actions = {"installed": 0, "skipped": 0}
    for record in import_value["files"]:
        if (
            type(record) is not dict
            or set(record) != {"action", "path", "sha256", "size"}
            or record["action"] not in actions
            or type(record["path"]) is not str
            or type(record["size"]) is not int
            or record["size"] < 0
        ):
            raise GenerationFailure("IMAGE_IMPORT_SCHEMA", "image import file evidence is malformed")
        _require_sha(record["sha256"], "image import file")
        actions[record["action"]] += 1
        import_paths.append(record["path"])
        pure_import = PurePosixPath(record["path"])
        if len(pure_import.parts) < 3 or pure_import.parts[0] != "train":
            raise GenerationFailure("IMAGE_IMPORT_SCHEMA", "image import file path is outside train")
        image_relative = PurePosixPath(*pure_import.parts[1:]).as_posix()
        if image_relative in import_file_evidence:
            raise GenerationFailure("IMAGE_IMPORT_SCHEMA", "duplicate image import file path")
        import_file_evidence[image_relative] = (record["size"], record["sha256"])
    if (
        actions != {"installed": 1_487, "skipped": 43}
        or import_paths != sorted(import_paths, key=lambda item: item.encode())
        or len(import_paths) != len(set(import_paths))
    ):
        raise GenerationFailure("IMAGE_IMPORT_SCHEMA", "image import file membership/action counts drifted")
    summary = {
        "chunks": 3_600,
        "files": EXPECTED_IMAGE_FILES,
        "roots": 36,
        "stored_bytes": EXPECTED_IMAGE_BYTES,
    }
    inventory = value["inventory"]
    if type(inventory) is not dict or set(inventory) != {"bytes", "path", "sha256", "summary"}:
        raise GenerationFailure("IMAGE_READY_SCHEMA", "image READY inventory ref is malformed")
    if inventory["path"] != "IMAGE_CONTENT_INVENTORY.json" or inventory["summary"] != summary:
        raise GenerationFailure("IMAGE_READY_MISMATCH", "image READY inventory summary mismatch")
    inventory_path = path.parent / inventory["path"]
    inventory_size, inventory_hash = _digest_regular(inventory_path)
    if (
        type(inventory["bytes"]) is not int
        or inventory_size != inventory["bytes"]
        or inventory_hash != _require_sha(inventory["sha256"], "image READY inventory")
        or inventory_hash != CANONICAL_IMAGE_INVENTORY_SHA256
    ):
        raise GenerationFailure("IMAGE_READY_DRIFT", "image READY inventory ref drifted")
    inventory_value = _load_canonical_json(inventory_path, max_bytes=2_000_000)
    if (
        set(inventory_value) != {"files", "roots", "schema_version", "summary"}
        or inventory_value["schema_version"] != "biohub.eval36_image_content_inventory.v1"
        or inventory_value["roots"] != list(EVAL36)
        or inventory_value["summary"] != summary
        or type(inventory_value["files"]) is not list
        or len(inventory_value["files"]) != EXPECTED_IMAGE_FILES
    ):
        raise GenerationFailure("IMAGE_READY_SCHEMA", "image READY content inventory schema mismatch")
    current_records = _tree_records(image_view)
    direct_children = sorted(item.name for item in image_view.iterdir())
    if direct_children != sorted(f"{stem}.zarr" for stem in EVAL36):
        raise GenerationFailure("IMAGE_VIEW_MIXED", "arm image view must contain only the frozen 36 image roots")
    current_by_path = {record["path"]: (record["bytes"], record["sha256"]) for record in current_records}
    ready_by_path: dict[str, tuple[int, str]] = {}
    per_root: dict[str, set[str]] = {stem: set() for stem in EVAL36}
    for record in inventory_value["files"]:
        if (
            type(record) is not dict
            or set(record) != {"bytes", "path", "sha256", "stem"}
            or type(record["path"]) is not str
            or type(record["bytes"]) is not int
            or record["bytes"] < 0
            or record["stem"] not in EVAL36
            or not record["path"].startswith(f"{record['stem']}.zarr/")
        ):
            raise GenerationFailure("IMAGE_READY_SCHEMA", "image READY file record is malformed")
        expected_root_paths = {
            f"{record['stem']}.zarr/zarr.json",
            f"{record['stem']}.zarr/0/zarr.json",
            *(f"{record['stem']}.zarr/0/c/{index}/0/0/0" for index in range(100)),
        }
        if record["path"] not in expected_root_paths:
            raise GenerationFailure("IMAGE_READY_SCHEMA", "image READY path layout drifted")
        per_root[record["stem"]].add(record["path"])
        ready_by_path[record["path"]] = (record["bytes"], _require_sha(record["sha256"], "image file"))
    if (
        len(ready_by_path) != EXPECTED_IMAGE_FILES
        or sum(item[0] for item in ready_by_path.values()) != EXPECTED_IMAGE_BYTES
        or any(len(paths) != 102 for paths in per_root.values())
        or ready_by_path != current_by_path
    ):
        raise GenerationFailure("IMAGE_READY_DRIFT", "image READY file records differ from the image view")
    if any(ready_by_path.get(path) != evidence for path, evidence in import_file_evidence.items()):
        raise GenerationFailure("IMAGE_IMPORT_DRIFT", "image import file evidence differs from READY inventory")
    identity = value["data_root_identity"]
    image_info = image_view.stat(follow_symlinks=False)
    if (
        type(identity) is not dict
        or set(identity) != {"device", "inode"}
        or any(type(identity[key]) is not int for key in ("device", "inode"))
    ):
        raise GenerationFailure("IMAGE_READY_DRIFT", "image READY source data-root identity is malformed")
    if identity == {"device": image_info.st_dev, "inode": image_info.st_ino}:
        raise GenerationFailure("IMAGE_VIEW_NOT_ISOLATED", "arm image view must be a distinct image-only snapshot")
    decoded = value["decoded"]
    if (
        type(decoded) is not dict
        or set(decoded) != {"aggregate_sha256", "bytes", "chunks", "order"}
        or decoded["aggregate_sha256"] != "635a326ff78526a3d43952b94950e6d97d07db14cd53bc056517ea70d5b49646"
        or decoded["bytes"] != 30_198_988_800
        or decoded["chunks"] != 3_600
        or decoded["order"] != READY_DECODE_ORDER
    ):
        raise GenerationFailure("IMAGE_READY_MISMATCH", "image READY decoded-content binding mismatch")
    verifier = value["verifier"]
    verifier_path = repo_root / "scripts" / "verify_eval36_images.py"
    verifier_size, verifier_hash = _digest_regular(verifier_path)
    if (
        type(verifier) is not dict
        or set(verifier) != {"bytes", "reference", "sha256"}
        or verifier["reference"] != verifier_path.name
        or verifier["bytes"] != verifier_size
        or verifier["sha256"] != verifier_hash
    ):
        raise GenerationFailure("IMAGE_READY_VERIFIER_DRIFT", "image READY verifier source drifted")
    return (
        {
            "path": _portable_repo_path(path, repo_root, "image READY receipt"),
            "bytes": ready_size,
            "sha256": ready_sha,
            "verdict": "READY",
            "schema_version": value["schema_version"],
            "created_utc": created_utc,
            "authority_policy": "exact reviewed path and content digests; no wall-clock TTL",
            "source_data_root_identity": identity,
            "image_view_identity": {"device": image_info.st_dev, "inode": image_info.st_ino},
            "import_receipt": {
                "path": _portable_repo_path(import_receipt_path, repo_root, "image import receipt"),
                "bytes": import_size,
                "sha256": import_sha,
                "verdict": "PASS",
            },
            "inventory": {
                "path": _portable_repo_path(inventory_path, repo_root, "image READY inventory"),
                "bytes": inventory_size,
                "sha256": inventory_hash,
            },
        },
        current_records,
    )


def _effective_configs(image_view: Path, checkpoint: Path, manifest: Path) -> dict[str, dict[str, object]]:
    values: dict[str, dict[str, object]] = {}
    for arm in ("baseline", "dry_run", "candidate"):
        spec = production_adapter.ArmSpec(
            arm_name=arm,
            geff_dir=Path("."),
            test_dir=image_view,
            deepcenter_checkpoint=checkpoint,
            deepcenter_manifest=manifest,
            datasets=tuple(EVAL36),
            expected_effective_config_sha256="0" * 64,
            staging_dir=Path("."),
            event_fd=1,
        )
        cfg = production_adapter._build_arm_config(spec)
        encoded = production_adapter._canonical_effective_config(cfg)
        decoded = json.loads(encoded)
        if type(decoded) is not dict or canonical_json_bytes(decoded) != encoded:
            raise GenerationFailure("EFFECTIVE_CONFIG_SCHEMA", "adapter effective config is not canonical")
        values[arm] = {"sha256": _sha256_bytes(encoded), "value": decoded}
    return values


def _raw_provenance_ref(
    path: Path,
    repo_root: Path,
    role: str,
    raw_inventory: Mapping[str, object],
    source: Mapping[str, object],
) -> dict[str, object]:
    value = _load_canonical_json(path, reject_forbidden=False)
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
    if (
        set(value) != expected_keys
        or value["schema_version"] != RAW_PROVENANCE_SCHEMA
        or value["status"] != "LEGACY_HISTORY_UNVERIFIED"
        or value["role"] != role
    ):
        raise GenerationFailure("RAW_PROVENANCE_SCHEMA", f"{role} raw provenance schema drifted")
    _strict_utc(value["created_utc"], f"{role} raw provenance created_utc")
    receipt_source = value["source"]
    if receipt_source != {
        "commit": source["superproject_commit"],
        "git_tree_oid": source["git_tree_oid"],
        "official_gitlink": OFFICIAL_REVIEWED_OID,
    }:
        raise GenerationFailure("RAW_PROVENANCE_SOURCE_DRIFT", f"{role} raw provenance source drifted")
    known_weight = PRIMARY_RAW_WEIGHT_SHA256 if role == "primary" else SECONDARY_RAW_WEIGHT_SHA256
    if (
        value["raw_root"] != CANONICAL_RAW_ROOT
        or value["raw_records_sha256"] != CANONICAL_RAW_RECORDS_SHA256
        or value["known_weight_sha256"] != known_weight
        or raw_inventory["file_count"] != EXPECTED_RAW_FILES
        or raw_inventory["total_bytes"] != EXPECTED_RAW_BYTES
        or raw_inventory["records_sha256"] != CANONICAL_RAW_RECORDS_SHA256
    ):
        raise GenerationFailure("RAW_PROVENANCE_DRIFT", f"{role} raw provenance does not bind the frozen raw tree")
    fixed_refs = (
        ("download_manifest", RAW_DOWNLOAD_MANIFEST_PATH, RAW_DOWNLOAD_MANIFEST_BYTES, RAW_DOWNLOAD_MANIFEST_SHA256),
        ("runtime_integrity", RAW_RUNTIME_INTEGRITY_PATH, RAW_RUNTIME_INTEGRITY_BYTES, RAW_RUNTIME_INTEGRITY_SHA256),
        ("derivation_log", RAW_DERIVATION_LOG_PATH, RAW_DERIVATION_LOG_BYTES, RAW_DERIVATION_LOG_SHA256),
    )
    evidence_paths: dict[str, Path] = {}
    for key, expected_path, expected_bytes, expected_sha in fixed_refs:
        ref = value[key]
        if type(ref) is not dict or ref.get("path") != expected_path:
            raise GenerationFailure("RAW_PROVENANCE_DRIFT", f"{role} {key} path is not frozen")
        evidence_paths[key] = _validate_artifact_evidence(
            repo_root, ref, f"{role} {key}", expected_sha256=expected_sha, expected_bytes=expected_bytes
        )
    try:
        download = json.loads(_read_regular_stable(evidence_paths["download_manifest"]))
        runtime = json.loads(_read_regular_stable(evidence_paths["runtime_integrity"]))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GenerationFailure("RAW_PROVENANCE_DRIFT", "frozen provenance JSON is malformed") from exc
    raw_manifest = download.get("raw_geff") if type(download) is dict else None
    source_manifest = download.get("source") if type(download) is dict else None
    references = download.get("reference_files") if type(download) is dict else None
    if (
        type(source_manifest) is not dict
        or source_manifest.get("kernel") != "taichiiiii/biohub-eval-train-raw"
        or source_manifest.get("version") != 11
        or source_manifest.get("kernel_id") != 131_740_073
        or source_manifest.get("latest_status") != "KernelWorkerStatus.COMPLETE"
        or type(raw_manifest) is not dict
        or raw_manifest.get("path")
        != "../e22_bidir030_eval36_raw/tracking_repo/predictions/unknown/unet_transformer_val/split_0"
        or raw_manifest.get("roots") != 36
        or raw_manifest.get("files") != EXPECTED_RAW_FILES
        or raw_manifest.get("bytes") != EXPECTED_RAW_BYTES
        or raw_manifest.get("canonical_sha256sum_tree_sha256")
        != "fa34dcf5f20054f240d750bd2225dd08fc6cf645e094cd9596ce2faf4bbf0ca2"
        or raw_manifest.get("zarr_semantic_validation") != "passed"
        or raw_manifest.get("resume_verification_runs") != 1
        or type(references) is not dict
        or references.get("bidirectional_production_runtime_integrity.json")
        != {"bytes": RAW_RUNTIME_INTEGRITY_BYTES, "sha256": RAW_RUNTIME_INTEGRITY_SHA256}
        or references.get("biohub-eval-train-raw.log")
        != {"bytes": RAW_DERIVATION_LOG_BYTES, "sha256": RAW_DERIVATION_LOG_SHA256}
    ):
        raise GenerationFailure("RAW_PROVENANCE_DRIFT", "download manifest semantics drifted")
    if (
        type(runtime) is not dict
        or runtime.get("status") != "complete_label_free_runtime_integrity"
        or runtime.get("ground_truth_accessed") is not False
        or runtime.get("checkpoint_sha256")
        != {
            "deepcenter": DEEPCENTER_CHECKPOINT_SHA256,
            "primary": PRIMARY_RAW_WEIGHT_SHA256,
            "secondary": SECONDARY_RAW_WEIGHT_SHA256,
        }
        or runtime.get("support_repo_python_file_count") != 13
        or runtime.get("support_repo_python_manifest_sha256")
        != "978b626d1fd1e7397435a437dfe68691defe1572fc3c20e61012d7c9b52ed029"
    ):
        raise GenerationFailure("RAW_PROVENANCE_DRIFT", "runtime integrity semantics drifted")
    log_text = _read_regular_stable(evidence_paths["derivation_log"]).decode("utf-8")
    required_log_statements = (
        f"Weight sha256: {PRIMARY_RAW_WEIGHT_SHA256}",
        f"Primary materialized SHA256: {PRIMARY_RAW_WEIGHT_SHA256}",
        f"Secondary SHA256: {SECONDARY_RAW_WEIGHT_SHA256}",
        "VALIDATOR: merged 36 prediction graphs into ",
        "VALIDATOR: prediction completed in ",
    )
    if any(log_text.count(statement) != 1 for statement in required_log_statements):
        raise GenerationFailure("RAW_PROVENANCE_DRIFT", "derivation log lacks unique frozen hash/completion statements")
    if value["claims"] != {
        "checkpoint_bytes_locally_available": False,
        "checkpoint_to_raw_cryptographic_proof": False,
        "legacy_log_and_runtime_receipts_verified": True,
    }:
        raise GenerationFailure("RAW_PROVENANCE_SCHEMA", "raw provenance claims overstate legacy evidence")
    size, digest = _digest_regular(path)
    return {
        "path": _portable_repo_path(path, repo_root, f"{role} raw provenance receipt"),
        "bytes": size,
        "sha256": digest,
        "verdict": "LEGACY_HISTORY_UNVERIFIED",
    }


def _gt_inventory_ref(path: Path, repo_root: Path) -> dict[str, object]:
    """Validate only the sealed inventory envelope; never open a GT data path."""
    value = _load_canonical_json(path, reject_forbidden=False)
    if (
        set(value) != {"schema_version", "stems", "records"}
        or value["schema_version"] != GT_INVENTORY_SCHEMA
        or value["stems"] != list(EVAL36)
        or type(value["records"]) is not list
        or not value["records"]
    ):
        raise GenerationFailure("GT_INVENTORY_SCHEMA", "opaque GT inventory schema/stems drifted")
    paths: list[str] = []
    roots: set[str] = set()
    for record in value["records"]:
        if (
            type(record) is not dict
            or set(record) != {"path", "bytes", "sha256"}
            or type(record["path"]) is not str
            or type(record["bytes"]) is not int
            or record["bytes"] < 0
        ):
            raise GenerationFailure("GT_INVENTORY_SCHEMA", "opaque GT inventory record is malformed")
        pure = PurePosixPath(record["path"])
        if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
            raise GenerationFailure("GT_INVENTORY_SCHEMA", "opaque GT inventory path is unsafe")
        matching = [part for part in pure.parts if part.endswith((".geff", ".zarr"))]
        if len(matching) != 1 or matching[0].removesuffix(".geff").removesuffix(".zarr") not in EVAL36:
            raise GenerationFailure("GT_INVENTORY_SCHEMA", "opaque GT inventory root membership drifted")
        roots.add(matching[0])
        _require_sha(record["sha256"], "opaque GT inventory record")
        paths.append(record["path"])
    expected_roots = {f"{stem}.geff" for stem in EVAL36} | {f"{stem}.zarr" for stem in EVAL36}
    if paths != sorted(paths) or len(paths) != len(set(item.casefold() for item in paths)) or roots != expected_roots:
        raise GenerationFailure("GT_INVENTORY_SCHEMA", "opaque GT inventory is unordered, colliding, or incomplete")
    size, digest = _digest_regular(path)
    return {
        "path": _portable_repo_path(path, repo_root, "opaque GT inventory"),
        "bytes": size,
        "sha256": digest,
        "verdict": "SCHEMA_AND_MEMBERSHIP_VERIFIED_WITHOUT_GT_READ",
    }


def _dataset_binding() -> dict[str, object]:
    def digest(items: tuple[str, ...]) -> str:
        return _sha256_bytes(canonical_json_bytes(list(items)))

    if len(set(EVAL36)) != 36 or set(EVAL12) & set(EVAL24) or set(EVAL36) & PUBLIC_FOUR:
        raise RuntimeError("frozen dataset constants are internally inconsistent")
    return {
        "eval12": list(EVAL12),
        "eval24": list(EVAL24),
        "eval36": list(EVAL36),
        "digests": {"eval12": digest(EVAL12), "eval24": digest(EVAL24), "eval36": digest(EVAL36)},
    }


def preregister(spec: PreregistrationSpec, *, repo_root: Path | None = None) -> Path:
    """Create a fresh immutable preregistration before any arm directory exists."""
    if type(spec) is not PreregistrationSpec:
        raise TypeError("spec must be an exact PreregistrationSpec")
    root = (repo_root or Path(__file__).resolve().parents[2]).resolve(strict=True)
    _audit_sensitive_fds()
    if type(spec.timeout_seconds) is not float or not math.isfinite(spec.timeout_seconds) or spec.timeout_seconds <= 0:
        raise GenerationFailure("INVALID_TIMEOUT", "timeout must be a finite positive float")
    unknown_biohub = sorted(name for name in os.environ if name.startswith("BIOHUB_"))
    if unknown_biohub:
        raise GenerationFailure("UNKNOWN_BIOHUB_ENV", "ambient BIOHUB_* variables are forbidden")

    run_dir = Path(os.path.abspath(spec.run_dir))
    _portable_repo_path(run_dir, root, "run directory")
    if run_dir.exists() or run_dir.is_symlink():
        raise GenerationFailure("RUN_DIR_EXISTS", "run directory must be fresh")
    for path, label in (
        (spec.raw_geff_dir, "raw GEFF"),
        (spec.image_view, "image view"),
        (spec.deepcenter_checkpoint, "DeepCenter checkpoint"),
        (spec.deepcenter_manifest, "DeepCenter manifest"),
        (spec.image_import_receipt, "image import receipt"),
        (spec.gt_inventory, "opaque GT inventory"),
    ):
        _portable_repo_path(path, root, label)
    if _portable_repo_path(spec.raw_geff_dir, root, "raw GEFF") != CANONICAL_RAW_ROOT:
        raise GenerationFailure("RAW_PROVENANCE_DRIFT", "raw GEFF root is not the reviewed canonical root")

    source = _source_binding(root)
    checkpoint_size, checkpoint_hash = _digest_regular(spec.deepcenter_checkpoint)
    manifest_size, manifest_hash = _digest_regular(spec.deepcenter_manifest)
    if checkpoint_hash != DEEPCENTER_CHECKPOINT_SHA256 or manifest_hash != DEEPCENTER_MANIFEST_SHA256:
        raise GenerationFailure("DEEPCENTER_DRIFT", "DeepCenter checkpoint or manifest identity drifted")

    raw_records = _tree_records(spec.raw_geff_dir)
    _validate_raw_inventory(spec.raw_geff_dir, raw_records)
    raw_inventory = _inventory_value("raw_geff", spec.raw_geff_dir, raw_records)
    primary_provenance = _raw_provenance_ref(
        spec.primary_raw_provenance_receipt, root, "primary", raw_inventory, source
    )
    secondary_provenance = _raw_provenance_ref(
        spec.secondary_raw_provenance_receipt, root, "secondary", raw_inventory, source
    )
    if (
        primary_provenance["path"] == secondary_provenance["path"]
        or primary_provenance["sha256"] == secondary_provenance["sha256"]
    ):
        raise GenerationFailure("RAW_PROVENANCE_SCHEMA", "primary and secondary provenance receipts must be distinct")
    gt_inventory = _gt_inventory_ref(spec.gt_inventory, root)
    parity = _receipt_ref(
        spec.e23_parity_receipt,
        root,
        "E23 parity receipt",
        E23_PARITY_RECEIPT_SCHEMA,
        source,
    )
    base1 = _receipt_ref(
        spec.base1_receipt,
        root,
        "base1 receipt",
        BASE1_RECEIPT_SCHEMA,
        source,
    )
    image_ready, image_records = _image_ready_ref(
        spec.image_ready_receipt, root, spec.image_view, spec.image_import_receipt
    )

    _validate_image_inventory(spec.image_view, image_records)
    image_inventory = _inventory_value("image_content", spec.image_view, image_records)
    resources = _target_resources(spec.target_resources, root)
    effective_configs = _effective_configs(
        Path(os.path.abspath(spec.image_view)),
        Path(os.path.abspath(spec.deepcenter_checkpoint)),
        Path(os.path.abspath(spec.deepcenter_manifest)),
    )
    config_hashes = {arm: str(item["sha256"]) for arm, item in effective_configs.items()}

    run_dir.mkdir(parents=True, mode=0o700)
    inputs_dir = run_dir / "inputs"
    inputs_dir.mkdir(mode=0o700)
    _write_new_atomic(inputs_dir / "RAW_CONTENT_INVENTORY.json", canonical_json_bytes(raw_inventory))
    _write_new_atomic(inputs_dir / "IMAGE_CONTENT_INVENTORY.json", canonical_json_bytes(image_inventory))

    supervisor = root / "scripts" / "experiments" / "st_r3" / "st_r3_supervise_arm.py"
    executions = []
    for key, arm, relative in FROZEN_EXECUTIONS:
        argv = [
            str(Path(sys.executable).resolve(strict=True)),
            str(supervisor.resolve(strict=True)),
            "--arm-name",
            arm,
            "--geff-dir",
            str(Path(spec.raw_geff_dir).resolve(strict=True)),
            "--test-dir",
            str(Path(spec.image_view).resolve(strict=True)),
            "--deepcenter-checkpoint",
            str(Path(spec.deepcenter_checkpoint).resolve(strict=True)),
            "--deepcenter-manifest",
            str(Path(spec.deepcenter_manifest).resolve(strict=True)),
            "--expected-effective-config-sha256",
            config_hashes[arm],
            "--final-dir",
            str(run_dir / relative),
            "--timeout-seconds",
            repr(spec.timeout_seconds),
        ]
        executions.append({"key": key, "arm": arm, "relative_output": relative, "argv": argv})

    created_ns = time.time_ns()
    prereg = {
        "schema_version": PREREGISTRATION_SCHEMA,
        "state": "PREREGISTERED_WITH_MANDATORY_HOLDS",
        "run_id": run_dir.name,
        "created_utc_ns": created_ns,
        "candidate_id": "twin_only_v1",
        "operator_phase": "ST-R3-G1_LABEL_BLIND_GENERATION",
        "training_gate_status": "NOT_APPLICABLE_POSTPROCESS_ONLY",
        "datasets": _dataset_binding(),
        "source": source,
        "prerequisites": {
            "e23_parity": parity,
            "base1_non_regression": base1,
            "primary_raw_provenance": primary_provenance,
            "secondary_raw_provenance": secondary_provenance,
        },
        "inputs": {
            "raw_geff_root": _portable_repo_path(spec.raw_geff_dir, root, "raw GEFF"),
            "raw_inventory": "inputs/RAW_CONTENT_INVENTORY.json",
            "raw_inventory_sha256": _sha256_bytes(canonical_json_bytes(raw_inventory)),
            "image_view": _portable_repo_path(spec.image_view, root, "image view"),
            "image_ready_receipt": image_ready,
            "image_content_inventory": "inputs/IMAGE_CONTENT_INVENTORY.json",
            "image_content_inventory_sha256": _sha256_bytes(canonical_json_bytes(image_inventory)),
            "deepcenter": {
                "checkpoint": {
                    "path": _portable_repo_path(spec.deepcenter_checkpoint, root, "DeepCenter checkpoint"),
                    "bytes": checkpoint_size,
                    "sha256": checkpoint_hash,
                    "epoch": 2,
                },
                "manifest": {
                    "path": _portable_repo_path(spec.deepcenter_manifest, root, "DeepCenter manifest"),
                    "bytes": manifest_size,
                    "sha256": manifest_hash,
                },
            },
            "opaque_gt_inventory": gt_inventory,
        },
        "effective_config_sha256": config_hashes,
        "effective_configs": effective_configs,
        "candidate_semantics": {
            "mode": "twin_only_v1",
            "twin_max_um": 5.0,
            "existing_child_max_um": 10.0,
            "parent_max_um": 8.0,
            "sister_min_um": 5.5,
            "sister_max_um": 11.0,
            "divergence_growth_min_um": 2.25,
            "deepcenter_threshold": 0.12,
            "frame_cap_abs": 1,
            "video_cap_abs": 2,
            "require_two_successors": True,
            "reject_synthetic": True,
        },
        "execution_protocol": {
            "order": [item[0] for item in FROZEN_EXECUTIONS],
            "blocks": ["SAFETY_DRY_RUN", "AB", "BA"],
            "executions": executions,
            "environment": FIXED_ENVIRONMENT,
            "working_directory": str(root),
            "timeout_seconds": spec.timeout_seconds,
            "supervisor_fresh_os_process": True,
            "dry_run_timed_for_gate": False,
            "candidate_wall_statistic": "max(candidate_ab,candidate_ba)",
            "baseline_wall_statistic": "min(baseline_ab,baseline_ba)",
            "candidate_rss_statistic": "max(candidate_ab,candidate_ba)",
            "baseline_rss_statistic": "min(baseline_ab,baseline_ba)",
        },
        "resources": resources,
        "thresholds": {
            "feasibility": {
                "candidate_wall_le_baseline_multiplier": 1.25,
                "candidate_rss_le_baseline_plus_bytes": 1_073_741_824,
                "target_memory_fraction_le": 0.8,
                "target_wall_fraction_le": 0.8,
                "hidden_dataset_count": 200,
            },
            "eval12": {
                "paired_mean_delta_ge": 0.005,
                "paired_median_delta_ge": 0.0,
                "paired_worst_delta_ge": -0.002,
                "aggregate_adjusted_edge_delta_ge": -0.002,
                "lineage_44b6_score_delta_ge": 0.0,
                "lineage_6bba_score_delta_ge": 0.0,
            },
            "eval24": {
                "paired_mean_delta_ge": 0.003,
                "paired_median_delta_ge": 0.0,
                "paired_worst_delta_ge": -0.002,
                "aggregate_adjusted_edge_delta_ge": -0.002,
                "lineage_44b6_score_delta_ge": 0.0,
                "lineage_6bba_score_delta_ge": 0.0,
            },
            "eval36": {
                "aggregate_division_tp_delta_ge": 4,
                "aggregate_adjusted_edge_delta_ge": -0.002,
                "aggregate_score_delta_ge": 0.0,
                "aggregate_division_jaccard_delta_ge": 0.0,
                "paired_median_delta_ge": 0.0,
                "paired_worst_delta_ge": -0.002,
                "lineage_44b6_score_delta_ge": 0.0,
                "lineage_6bba_score_delta_ge": 0.0,
            },
        },
        "platform": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
        },
        "mandatory_holds": list(UNRESOLVED_PRODUCTION_HOLDS),
        "claims": {
            "training_loss_applicable": False,
            "metric_imported": False,
            "gt_path_accepted": False,
            "feasibility_pass_possible_in_this_revision": False,
        },
    }
    _reject_forbidden_content(prereg, "preregistration")
    _write_new_atomic(run_dir / "PREREGISTRATION.json", canonical_json_bytes(prereg))
    return run_dir / "PREREGISTRATION.json"


def _default_arm_runner(argv: Sequence[str], environment: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        tuple(argv),
        env=dict(environment),
        cwd=Path(argv[1]).resolve(strict=True).parent.parent,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )


def _resolve_repo_path(repo_root: Path, relative: object, label: str) -> Path:
    if type(relative) is not str:
        raise GenerationFailure("INVALID_PATH", f"{label} path is not text")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
        raise GenerationFailure("INVALID_PATH", f"{label} path is not portable")
    path = repo_root.joinpath(*pure.parts)
    try:
        path.absolute().relative_to(repo_root)
    except ValueError as exc:
        raise GenerationFailure("PATH_TRAVERSAL", f"{label} escapes the repository") from exc
    _reject_forbidden_content(relative, label)
    return path


def _resolve_run_path(run_dir: Path, relative: object, label: str) -> Path:
    if type(relative) is not str:
        raise GenerationFailure("INVALID_PATH", f"{label} path is not text")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
        raise GenerationFailure("INVALID_PATH", f"{label} path is not portable")
    return run_dir.joinpath(*pure.parts)


def _verify_inventory(root: Path, inventory_path: Path, kind: str) -> tuple[str, int, int]:
    inventory = _load_canonical_json(inventory_path, max_bytes=2_000_000)
    if inventory.get("schema_version") != TREE_INVENTORY_SCHEMA or inventory.get("kind") != kind:
        raise GenerationFailure("INVENTORY_SCHEMA", f"{kind} inventory schema mismatch")
    records = _tree_records(root)
    current = _inventory_value(kind, root, records)
    if current != inventory:
        raise GenerationFailure("INPUT_DRIFT", f"{kind} tree changed from preregistration")
    return str(current["records_sha256"]), int(current["file_count"]), int(current["total_bytes"])


def _verify_external_ref(repo_root: Path, value: object, label: str) -> None:
    if type(value) is not dict or not {"path", "bytes", "sha256"} <= set(value):
        raise GenerationFailure("REFERENCE_SCHEMA", f"{label} ref is malformed")
    if type(value["bytes"]) is not int or value["bytes"] < 0:
        raise GenerationFailure("REFERENCE_SCHEMA", f"{label} ref byte count is malformed")
    path = _resolve_repo_path(repo_root, value["path"], label)
    size, digest = _digest_regular(path)
    if size != value["bytes"] or digest != _require_sha(value["sha256"], label):
        raise GenerationFailure("REFERENCE_DRIFT", f"{label} ref drifted")


def _reverify_inputs(
    run_dir: Path,
    prereg: dict[str, Any],
    repo_root: Path,
    phase: str,
    *,
    strict_source: bool,
) -> dict[str, object]:
    started = time.monotonic_ns()
    inputs = prereg["inputs"]
    raw = _resolve_repo_path(repo_root, inputs["raw_geff_root"], "raw GEFF")
    images = _resolve_repo_path(repo_root, inputs["image_view"], "image view")
    raw_inventory_path = _resolve_run_path(run_dir, inputs["raw_inventory"], "raw inventory")
    image_inventory_path = _resolve_run_path(run_dir, inputs["image_content_inventory"], "image inventory")
    if _digest_regular(raw_inventory_path)[1] != inputs["raw_inventory_sha256"]:
        raise GenerationFailure("INPUT_DRIFT", "raw inventory artifact drifted")
    if _digest_regular(image_inventory_path)[1] != inputs["image_content_inventory_sha256"]:
        raise GenerationFailure("INPUT_DRIFT", "image inventory artifact drifted")
    raw_digest, raw_files, raw_bytes = _verify_inventory(raw, raw_inventory_path, "raw_geff")
    image_digest, image_files, image_bytes = _verify_inventory(images, image_inventory_path, "image_content")
    for item in inputs["deepcenter"].values():
        path = _resolve_repo_path(repo_root, item["path"], "DeepCenter artifact")
        size, digest = _digest_regular(path)
        if size != item["bytes"] or digest != item["sha256"]:
            raise GenerationFailure("INPUT_DRIFT", "DeepCenter artifact drifted")
    source_sha256 = None
    if strict_source:
        current_source = _source_binding(repo_root, allowed_untracked_run=run_dir)
        if current_source != prereg.get("source"):
            raise GenerationFailure("SOURCE_DRIFT", "source or official binding changed after preregistration")
        source_sha256 = _sha256_bytes(canonical_json_bytes(current_source))
        _verify_external_ref(repo_root, prereg["prerequisites"]["e23_parity"], "E23 parity receipt")
        _verify_external_ref(repo_root, prereg["prerequisites"]["base1_non_regression"], "base1 receipt")
        ready = inputs["image_ready_receipt"]
        _verify_external_ref(repo_root, ready, "image READY receipt")
        _verify_external_ref(repo_root, ready["inventory"], "image READY inventory")
        resources = prereg["resources"]
        _verify_external_ref(repo_root, resources["ref"], "target resources")
        _verify_external_ref(repo_root, resources["source_snapshot"], "target source snapshot")
    ended = time.monotonic_ns()
    return {
        "schema_version": REVERIFY_SCHEMA,
        "phase": phase,
        "raw": {"records_sha256": raw_digest, "files": raw_files, "bytes": raw_bytes},
        "images": {"records_sha256": image_digest, "files": image_files, "bytes": image_bytes},
        "deepcenter_bound": True,
        "source_inventory_sha256": source_sha256,
        "duration_monotonic_ns": ended - started,
        "available_bytes_stable_only": True,
        "actual_consumption_proven": False,
        "upstream_authenticity_proven": False,
    }


def _arm_tree_inventory(arm_dir: Path) -> list[dict[str, object]]:
    records = _tree_records(arm_dir)
    if not any(item["path"] == "arm_receipt.json" for item in records):
        raise GenerationFailure("ARM_RECEIPT_MISSING", "published arm has no receipt")
    return records


def _validate_arm_receipt(
    arm_dir: Path,
    expected_arm: str,
    expected_config_sha: str,
    expected_relative: str,
    image_view: Path,
    checkpoint_name: str,
    manifest_name: str,
    *,
    strict_semantics: bool,
) -> dict[str, Any]:
    receipt = _load_canonical_json(arm_dir / "arm_receipt.json")
    exact_keys = {
        "schema_version",
        "status",
        "arm_name",
        "datasets",
        "child",
        "timing",
        "wait4",
        "events",
        "promotions",
        "artifact_inventory",
        "publication",
        "holds",
        "success_scope",
        "claims",
    }
    if set(receipt) != exact_keys or receipt.get("schema_version") != ARM_RECEIPT_SCHEMA:
        raise GenerationFailure("ARM_RECEIPT_SCHEMA", "arm receipt has an unexpected schema")
    if (
        receipt.get("status") != "LOCAL_VALIDATION_OBSERVED_WITH_HOLDS"
        or receipt.get("arm_name") != expected_arm
        or receipt.get("datasets") != list(EVAL36)
    ):
        raise GenerationFailure("ARM_IDENTITY_MISMATCH", "arm receipt identity/order mismatch")
    holds = receipt.get("holds")
    if type(holds) is not list or set(UNRESOLVED_PRODUCTION_HOLDS[:6]) - set(holds):
        raise GenerationFailure("ARM_HOLDS_DROPPED", "local supervisor receipt omitted binding holds")
    if receipt.get("success_scope") != "LOCAL_VALIDATION_ONLY_NOT_PRODUCTION_PERMISSION":
        raise GenerationFailure("ARM_SCOPE_MISMATCH", "arm receipt overstates its success scope")
    timing = receipt.get("timing")
    wait4 = receipt.get("wait4")
    if type(timing) is not dict or type(timing.get("duration_monotonic_ns")) is not int:
        raise GenerationFailure("ARM_TIMING_INVALID", "arm duration is missing")
    if timing["duration_monotonic_ns"] <= 0:
        raise GenerationFailure("ARM_TIMING_INVALID", "arm duration is nonpositive")
    if type(wait4) is not dict or wait4.get("authoritative_for_rss_gate") is not False:
        raise GenerationFailure("ARM_RSS_SCOPE_INVALID", "local RSS scope is unexpectedly authoritative")
    if type(wait4.get("ru_maxrss_normalized_bytes")) is not int or wait4["ru_maxrss_normalized_bytes"] <= 0:
        raise GenerationFailure("ARM_RSS_INVALID", "arm RSS is missing")
    child = receipt.get("child")
    if type(child) is not dict or type(child.get("argv")) is not list or type(child.get("environment")) is not dict:
        raise GenerationFailure("ARM_CHILD_SCHEMA", "arm child binding is malformed")
    _reject_forbidden_content(child["argv"], "child argv")
    _reject_forbidden_content(child["environment"], "child environment")
    if child["environment"] != FIXED_ENVIRONMENT:
        raise GenerationFailure("ARM_ENVIRONMENT_DRIFT", "arm child environment drifted")
    result = child.get("child_result")
    if type(result) is not dict or result.get("arm_name") != expected_arm or result.get("datasets") != list(EVAL36):
        raise GenerationFailure("ARM_CHILD_SCHEMA", "child result identity/order mismatch")
    config_bytes = _read_regular_stable(arm_dir / "effective_config.json")
    if _sha256_bytes(config_bytes) != expected_config_sha:
        raise GenerationFailure("ARM_CONFIG_DRIFT", "effective config does not match preregistration")
    tree = _arm_tree_inventory(arm_dir)
    actual = {item["path"]: (item["bytes"], item["sha256"]) for item in tree}
    registered = receipt.get("artifact_inventory")
    if type(registered) is not list:
        raise GenerationFailure("ARM_INVENTORY_SCHEMA", "arm inventory is missing")
    for item in registered:
        if type(item) is not dict or set(item) not in ({"relative_path", "bytes", "sha256"}, {"relative_path", "kind"}):
            raise GenerationFailure("ARM_INVENTORY_SCHEMA", "arm inventory record is malformed")
        if "sha256" in item and actual.get(item["relative_path"]) != (item["bytes"], item["sha256"]):
            raise GenerationFailure("ARM_ARTIFACT_DRIFT", "arm inventory digest mismatch")
    # Exact membership is bound independently; registered directories plus all files
    # and the supervisor-owned receipt must account for the whole tree.
    registered_paths = {item["relative_path"] for item in registered if "sha256" in item}
    registered_directories = {item["relative_path"] for item in registered if item.get("kind") == "directory"}
    actual_paths = {item["path"] for item in tree}
    if actual_paths != registered_paths | {"arm_receipt.json"}:
        raise GenerationFailure("ARM_EXTRA_ARTIFACT", "arm tree contains missing or extra artifacts")
    expected_paths = {
        "submission.csv",
        "run_stats.csv",
        "effective_config.json",
        "deepcenter_receipt.json",
        "twin_plan_manifest.json",
        "child_result.json",
        "dataset_events.jsonl",
        "arm_receipt.json",
        "supervisor_stdout.log.partial",
        "supervisor_stderr.log.partial",
        *(f"twin_plans/{sequence}.{dataset}.json" for sequence, dataset in enumerate(EVAL36)),
    }
    if actual_paths != expected_paths:
        raise GenerationFailure("ARM_EXTRA_ARTIFACT", "arm tree does not equal the frozen artifact set")
    if registered_directories != {"twin_plans"}:
        raise GenerationFailure("ARM_EXTRA_ARTIFACT", "arm tree has an unexpected directory inventory")
    if strict_semantics:
        try:
            decoded_config = production_adapter._parse_canonical_effective_config(config_bytes)
            expected_master = expected_arm != "baseline"
            expected_dry_run = expected_arm == "dry_run"
            if (
                decoded_config["OUTPUT_STEAL_TWIN_REWIRE"] is not expected_master
                or decoded_config["STEAL_TWIN_DRY_RUN"] is not expected_dry_run
                or decoded_config["STEAL_TWIN_MODE"] != "twin_only_v1"
            ):
                raise GenerationFailure("ARM_CONFIG_SEMANTICS", "effective arm semantics drifted")
            events = _read_regular_stable(arm_dir / "dataset_events.jsonl")
            production_supervisor._validate_events(events, expected_arm, child["pid"])
            counts = production_supervisor._validate_submission(arm_dir / "submission.csv", image_view)
            if counts != (result["total_nodes"], result["total_edges"], result["total_rows"]):
                raise GenerationFailure("ARM_SUBMISSION_COUNTS", "submission totals differ from child result")
            stats = production_supervisor._validate_run_stats(arm_dir / "run_stats.csv")
            deepcenter = _load_canonical_json(arm_dir / "deepcenter_receipt.json")
            production_supervisor._validate_deepcenter_receipt(deepcenter, checkpoint_name, manifest_name)
            plan_summaries: dict[str, dict[str, object]] = {}
            plan_records = []
            for sequence, dataset in enumerate(EVAL36):
                relative = f"twin_plans/{sequence}.{dataset}.json"
                plan = _load_canonical_json(arm_dir / relative)
                if (
                    set(plan) != {"schema_version", "dataset", "sequence", "planner_active", "plan"}
                    or plan["schema_version"] != production_supervisor.TWIN_PLAN_SCHEMA
                    or plan["dataset"] != dataset
                    or plan["sequence"] != sequence
                    or type(plan["planner_active"]) is not bool
                    or plan["planner_active"] is (expected_arm == "baseline")
                    or (plan["plan"] is None) is plan["planner_active"]
                ):
                    raise GenerationFailure("ARM_PLAN_SCHEMA", "plan envelope identity/order mismatch")
                if plan["planner_active"]:
                    plan_summaries[dataset] = production_supervisor._validate_active_twin_plan(plan["plan"], dataset)
                else:
                    plan_summaries[dataset] = {
                        "counters": dict.fromkeys(production_supervisor._TWIN_COUNTER_KEYS, 0),
                        "nodes": None,
                        "edges": None,
                        "validation_reason": None,
                    }
                size, digest = actual[relative]
                plan_records.append(
                    {
                        "dataset": dataset,
                        "sequence": sequence,
                        "planner_active": plan["planner_active"],
                        "relative_path": relative,
                        "bytes": size,
                        "sha256": digest,
                    }
                )
            plan_manifest = _load_canonical_json(arm_dir / "twin_plan_manifest.json")
            if plan_manifest != {
                "schema_version": production_supervisor.TWIN_PLAN_MANIFEST_SCHEMA,
                "datasets": list(EVAL36),
                "plans": plan_records,
            }:
                raise GenerationFailure("ARM_PLAN_MANIFEST", "plan manifest does not bind exact plan bytes")
            production_supervisor._validate_plan_stats_consistency(expected_arm, stats, plan_summaries)
        except GenerationFailure:
            raise
        except (KeyError, TypeError, ValueError, production_supervisor.SupervisorError) as exc:
            raise GenerationFailure("ARM_SEMANTIC_VALIDATION", "independent arm semantic validation failed") from exc
    return {
        "path": expected_relative,
        "bytes": len(canonical_json_bytes(receipt)),
        "sha256": _sha256_bytes(canonical_json_bytes(receipt)),
        "arm": expected_arm,
        "duration_monotonic_ns": timing["duration_monotonic_ns"],
        "ru_maxrss_normalized_bytes": wait4["ru_maxrss_normalized_bytes"],
        "holds": holds,
        "tree_sha256": _sha256_bytes(canonical_json_bytes(tree)),
        "submission_sha256": _sha256_bytes(_read_regular_stable(arm_dir / "submission.csv")),
        "stats_sha256": _sha256_bytes(_read_regular_stable(arm_dir / "run_stats.csv")),
        "plan_manifest_sha256": _sha256_bytes(_read_regular_stable(arm_dir / "twin_plan_manifest.json")),
    }


def _assert_replay(run_dir: Path, executions: Mapping[str, dict[str, Any]]) -> dict[str, object]:
    def data(key: str, name: str) -> bytes:
        return _read_regular_stable(run_dir / executions[key]["path"] / name)

    comparisons = {
        "baseline_submission_replay": data("baseline_ab", "submission.csv") == data("baseline_ba", "submission.csv"),
        "candidate_submission_replay": data("candidate_ab", "submission.csv") == data("candidate_ba", "submission.csv"),
        "dry_run_equals_baseline": data("safety_dry_run", "submission.csv") == data("baseline_ab", "submission.csv"),
        "baseline_stats_replay": data("baseline_ab", "run_stats.csv") == data("baseline_ba", "run_stats.csv"),
        "candidate_stats_replay": data("candidate_ab", "run_stats.csv") == data("candidate_ba", "run_stats.csv"),
        "baseline_config_replay": data("baseline_ab", "effective_config.json")
        == data("baseline_ba", "effective_config.json"),
        "candidate_config_replay": data("candidate_ab", "effective_config.json")
        == data("candidate_ba", "effective_config.json"),
        "baseline_deepcenter_replay": data("baseline_ab", "deepcenter_receipt.json")
        == data("baseline_ba", "deepcenter_receipt.json"),
        "candidate_deepcenter_replay": data("candidate_ab", "deepcenter_receipt.json")
        == data("candidate_ba", "deepcenter_receipt.json"),
        "baseline_plan_manifest_replay": data("baseline_ab", "twin_plan_manifest.json")
        == data("baseline_ba", "twin_plan_manifest.json"),
        "candidate_plan_manifest_replay": data("candidate_ab", "twin_plan_manifest.json")
        == data("candidate_ba", "twin_plan_manifest.json"),
    }
    for sequence, dataset in enumerate(EVAL36):
        name = f"twin_plans/{sequence}.{dataset}.json"
        expected = data("safety_dry_run", name)
        if expected != data("candidate_ab", name) or expected != data("candidate_ba", name):
            comparisons["pre_mutation_plan_identity"] = False
            break
        if data("baseline_ab", name) != data("baseline_ba", name):
            comparisons["baseline_plan_replay"] = False
            break
    else:
        comparisons["pre_mutation_plan_identity"] = True
        comparisons["baseline_plan_replay"] = True
    if not all(comparisons.values()):
        failed = next(name for name, passed in comparisons.items() if not passed)
        raise GenerationFailure("DETERMINISTIC_REPLAY_MISMATCH", failed)
    return comparisons


def _publish_terminal_hold(
    run_dir: Path,
    prereg_sha: str,
    *,
    code: str,
    holds: Sequence[str],
    generation_manifest_sha: str | None,
    detail: str,
) -> GenerationResult:
    final_dir = run_dir / "final"
    if final_dir.is_symlink() or (final_dir.exists() and not final_dir.is_dir()):
        raise GenerationFailure("UNSAFE_FINAL_DIR", "final evidence directory is unsafe")
    final_dir.mkdir(mode=0o700, exist_ok=True)
    payload = {
        "schema_version": TERMINAL_HOLD_SCHEMA,
        "status": "HOLD",
        "code": code,
        "run_id": run_dir.name,
        "preregistration_sha256": prereg_sha,
        "generation_manifest_sha256": generation_manifest_sha,
        "holds": sorted(set(holds)),
        "detail": detail[:512],
        "allowed_next_action": "new reviewed evidence schema and new run; scoring remains locked",
        "feasibility_pass_published": False,
    }
    _write_new_atomic(final_dir / "VERDICT.json", canonical_json_bytes(payload))
    return GenerationResult(
        "HOLD",
        code,
        run_dir,
        generation_manifest_sha,
        final_dir / "VERDICT.json",
        tuple(payload["holds"]),
    )


def _validate_production_preregistration(value: dict[str, Any], repo_root: Path, run_dir: Path) -> None:
    expected_keys = {
        "schema_version",
        "state",
        "run_id",
        "created_utc_ns",
        "candidate_id",
        "operator_phase",
        "training_gate_status",
        "datasets",
        "source",
        "prerequisites",
        "inputs",
        "effective_config_sha256",
        "effective_configs",
        "candidate_semantics",
        "execution_protocol",
        "resources",
        "thresholds",
        "platform",
        "mandatory_holds",
        "claims",
    }
    if set(value) != expected_keys:
        raise GenerationFailure("PREREGISTRATION_SCHEMA", "preregistration has missing or extra fields")
    if (
        type(value["created_utc_ns"]) is not int
        or value["created_utc_ns"] <= 0
        or value["candidate_id"] != "twin_only_v1"
        or value["operator_phase"] != "ST-R3-G1_LABEL_BLIND_GENERATION"
        or value["training_gate_status"] != "NOT_APPLICABLE_POSTPROCESS_ONLY"
        or value["mandatory_holds"] != list(UNRESOLVED_PRODUCTION_HOLDS)
        or value["claims"]
        != {
            "training_loss_applicable": False,
            "metric_imported": False,
            "gt_path_accepted": False,
            "feasibility_pass_possible_in_this_revision": False,
        }
    ):
        raise GenerationFailure("PREREGISTRATION_SCHEMA", "preregistration frozen identity/claims drifted")
    protocol = value["execution_protocol"]
    if (
        type(protocol) is not dict
        or protocol.get("order") != [item[0] for item in FROZEN_EXECUTIONS]
        or protocol.get("blocks") != ["SAFETY_DRY_RUN", "AB", "BA"]
        or protocol.get("environment") != FIXED_ENVIRONMENT
        or protocol.get("working_directory") != str(repo_root)
        or protocol.get("supervisor_fresh_os_process") is not True
        or protocol.get("dry_run_timed_for_gate") is not False
        or protocol.get("candidate_wall_statistic") != "max(candidate_ab,candidate_ba)"
        or protocol.get("baseline_wall_statistic") != "min(baseline_ab,baseline_ba)"
        or protocol.get("candidate_rss_statistic") != "max(candidate_ab,candidate_ba)"
        or protocol.get("baseline_rss_statistic") != "min(baseline_ab,baseline_ba)"
    ):
        raise GenerationFailure("PREREGISTRATION_SCHEMA", "preregistered execution protocol drifted")
    hashes = value["effective_config_sha256"]
    if type(hashes) is not dict or set(hashes) != {"baseline", "dry_run", "candidate"}:
        raise GenerationFailure("PREREGISTRATION_SCHEMA", "effective config hashes are malformed")
    for arm, digest in hashes.items():
        _require_sha(digest, f"{arm} effective config")
    inputs = value["inputs"]
    if type(inputs) is not dict or set(inputs) != {
        "raw_geff_root",
        "raw_inventory",
        "raw_inventory_sha256",
        "image_view",
        "image_ready_receipt",
        "image_content_inventory",
        "image_content_inventory_sha256",
        "deepcenter",
        "opaque_gt_inventory",
    }:
        raise GenerationFailure("PREREGISTRATION_SCHEMA", "input binding is malformed")
    if type(inputs["deepcenter"]) is not dict or set(inputs["deepcenter"]) != {"checkpoint", "manifest"}:
        raise GenerationFailure("PREREGISTRATION_SCHEMA", "DeepCenter input binding is malformed")
    for name in ("checkpoint", "manifest"):
        ref = inputs["deepcenter"][name]
        required = {"path", "bytes", "sha256"} | ({"epoch"} if name == "checkpoint" else set())
        if type(ref) is not dict or set(ref) != required:
            raise GenerationFailure("PREREGISTRATION_SCHEMA", "DeepCenter artifact ref is malformed")
    _require_sha(inputs["raw_inventory_sha256"], "raw inventory")
    _require_sha(inputs["image_content_inventory_sha256"], "image inventory")
    if type(inputs["opaque_gt_inventory"]) is not dict:
        raise GenerationFailure("PREREGISTRATION_SCHEMA", "opaque GT inventory ref is malformed")
    raw = _resolve_repo_path(repo_root, inputs["raw_geff_root"], "raw GEFF")
    images = _resolve_repo_path(repo_root, inputs["image_view"], "image view")
    checkpoint = _resolve_repo_path(repo_root, inputs["deepcenter"]["checkpoint"]["path"], "DeepCenter checkpoint")
    manifest = _resolve_repo_path(repo_root, inputs["deepcenter"]["manifest"]["path"], "DeepCenter manifest")
    effective_configs = value["effective_configs"]
    if type(effective_configs) is not dict or set(effective_configs) != {"baseline", "dry_run", "candidate"}:
        raise GenerationFailure("PREREGISTRATION_SCHEMA", "effective config maps are malformed")
    recomputed_configs = _effective_configs(images, checkpoint, manifest)
    if effective_configs != recomputed_configs or hashes != {
        arm: item["sha256"] for arm, item in recomputed_configs.items()
    }:
        raise GenerationFailure("PREREGISTRATION_SCHEMA", "effective config maps/hashes drifted")
    if type(protocol.get("timeout_seconds")) is not float or not math.isfinite(protocol["timeout_seconds"]):
        raise GenerationFailure("PREREGISTRATION_SCHEMA", "preregistered timeout is invalid")
    execution_specs = protocol.get("executions")
    if type(execution_specs) is not list or len(execution_specs) != len(FROZEN_EXECUTIONS):
        raise GenerationFailure("PREREGISTRATION_SCHEMA", "preregistered execution list is malformed")
    for item, (key, arm, relative) in zip(execution_specs, FROZEN_EXECUTIONS, strict=True):
        expected_argv = [
            str(Path(sys.executable).resolve(strict=True)),
            str((repo_root / "scripts" / "experiments" / "st_r3" / "st_r3_supervise_arm.py").resolve(strict=True)),
            "--arm-name",
            arm,
            "--geff-dir",
            str(raw),
            "--test-dir",
            str(images),
            "--deepcenter-checkpoint",
            str(checkpoint),
            "--deepcenter-manifest",
            str(manifest),
            "--expected-effective-config-sha256",
            value["effective_config_sha256"][arm],
            "--final-dir",
            str(run_dir / relative),
            "--timeout-seconds",
            repr(protocol["timeout_seconds"]),
        ]
        if item != {"key": key, "arm": arm, "relative_output": relative, "argv": expected_argv}:
            raise GenerationFailure("PREREGISTRATION_SCHEMA", "preregistered execution argv drifted")
    if not _same_typed(
        value["candidate_semantics"],
        {
            "mode": "twin_only_v1",
            "twin_max_um": 5.0,
            "existing_child_max_um": 10.0,
            "parent_max_um": 8.0,
            "sister_min_um": 5.5,
            "sister_max_um": 11.0,
            "divergence_growth_min_um": 2.25,
            "deepcenter_threshold": 0.12,
            "frame_cap_abs": 1,
            "video_cap_abs": 2,
            "require_two_successors": True,
            "reject_synthetic": True,
        },
    ):
        raise GenerationFailure("PREREGISTRATION_SCHEMA", "frozen twin_only_v1 semantics drifted")
    thresholds = value["thresholds"]
    if (
        type(thresholds) is not dict
        or set(thresholds) != {"feasibility", "eval12", "eval24", "eval36"}
        or not _same_typed(
            thresholds["feasibility"],
            {
                "candidate_wall_le_baseline_multiplier": 1.25,
                "candidate_rss_le_baseline_plus_bytes": 1_073_741_824,
                "target_memory_fraction_le": 0.8,
                "target_wall_fraction_le": 0.8,
                "hidden_dataset_count": 200,
            },
        )
        or not _same_typed(
            thresholds["eval12"],
            {
                "paired_mean_delta_ge": 0.005,
                "paired_median_delta_ge": 0.0,
                "paired_worst_delta_ge": -0.002,
                "aggregate_adjusted_edge_delta_ge": -0.002,
                "lineage_44b6_score_delta_ge": 0.0,
                "lineage_6bba_score_delta_ge": 0.0,
            },
        )
        or not _same_typed(
            thresholds["eval24"],
            {
                "paired_mean_delta_ge": 0.003,
                "paired_median_delta_ge": 0.0,
                "paired_worst_delta_ge": -0.002,
                "aggregate_adjusted_edge_delta_ge": -0.002,
                "lineage_44b6_score_delta_ge": 0.0,
                "lineage_6bba_score_delta_ge": 0.0,
            },
        )
        or not _same_typed(
            thresholds["eval36"],
            {
                "aggregate_division_tp_delta_ge": 4,
                "aggregate_adjusted_edge_delta_ge": -0.002,
                "aggregate_score_delta_ge": 0.0,
                "aggregate_division_jaccard_delta_ge": 0.0,
                "paired_median_delta_ge": 0.0,
                "paired_worst_delta_ge": -0.002,
                "lineage_44b6_score_delta_ge": 0.0,
                "lineage_6bba_score_delta_ge": 0.0,
            },
        )
    ):
        raise GenerationFailure("PREREGISTRATION_SCHEMA", "frozen metric/feasibility thresholds drifted")
    if type(value["prerequisites"]) is not dict or set(value["prerequisites"]) != {
        "e23_parity",
        "base1_non_regression",
        "primary_raw_provenance",
        "secondary_raw_provenance",
    }:
        raise GenerationFailure("PREREGISTRATION_SCHEMA", "prerequisite refs are malformed")
    if type(value["resources"]) is not dict or set(value["resources"]) != {
        "ref",
        "declared_ram_bytes",
        "declared_wall_seconds",
        "source_snapshot",
    }:
        raise GenerationFailure("PREREGISTRATION_SCHEMA", "target resource binding is malformed")

    # Reopen and semantically validate every external evidence object.  Merely
    # hand-writing a preregistration with matching-looking SHA strings cannot
    # bypass these checks.
    current_source = _source_binding(repo_root, allowed_untracked_run=run_dir)
    if current_source != value["source"]:
        raise GenerationFailure("SOURCE_DRIFT", "source binding changed after preregistration")
    e23 = _receipt_ref(
        _resolve_repo_path(repo_root, value["prerequisites"]["e23_parity"]["path"], "E23 receipt"),
        repo_root,
        "E23 parity receipt",
        E23_PARITY_RECEIPT_SCHEMA,
        current_source,
    )
    base1 = _receipt_ref(
        _resolve_repo_path(repo_root, value["prerequisites"]["base1_non_regression"]["path"], "base1 receipt"),
        repo_root,
        "base1 receipt",
        BASE1_RECEIPT_SCHEMA,
        current_source,
    )
    if e23 != value["prerequisites"]["e23_parity"] or base1 != value["prerequisites"]["base1_non_regression"]:
        raise GenerationFailure("PREREQUISITE_EVIDENCE_DRIFT", "prerequisite opaque refs drifted")
    raw_inventory_path = _resolve_run_path(run_dir, inputs["raw_inventory"], "raw inventory")
    raw_inventory = _load_canonical_json(raw_inventory_path)
    for role in ("primary", "secondary"):
        key = f"{role}_raw_provenance"
        expected = _raw_provenance_ref(
            _resolve_repo_path(repo_root, value["prerequisites"][key]["path"], key),
            repo_root,
            role,
            raw_inventory,
            current_source,
        )
        if expected != value["prerequisites"][key]:
            raise GenerationFailure("RAW_PROVENANCE_DRIFT", f"{role} provenance opaque ref drifted")
    gt_ref = _gt_inventory_ref(
        _resolve_repo_path(repo_root, inputs["opaque_gt_inventory"]["path"], "opaque GT inventory"), repo_root
    )
    if gt_ref != inputs["opaque_gt_inventory"]:
        raise GenerationFailure("GT_INVENTORY_DRIFT", "opaque GT inventory ref drifted")
    ready_ref = inputs["image_ready_receipt"]
    import_ref = ready_ref["import_receipt"]
    revalidated_ready, _ = _image_ready_ref(
        _resolve_repo_path(repo_root, ready_ref["path"], "image READY receipt"),
        repo_root,
        images,
        _resolve_repo_path(repo_root, import_ref["path"], "image import receipt"),
    )
    if revalidated_ready != ready_ref:
        raise GenerationFailure("IMAGE_READY_DRIFT", "image READY opaque ref drifted")
    revalidated_resources = _target_resources(
        _resolve_repo_path(repo_root, value["resources"]["ref"]["path"], "target resources"), repo_root
    )
    if revalidated_resources != value["resources"]:
        raise GenerationFailure("TARGET_RESOURCE_DRIFT", "target resource evidence drifted")


def generate(
    run_dir: Path,
    preregistration_sha256: str,
    *,
    repo_root: Path | None = None,
    arm_runner: ArmRunner | None = None,
) -> GenerationResult:
    """Run all five frozen arms and seal evidence, always retaining honest holds.

    ``arm_runner`` is an explicit unit-test seam.  Its use adds an irrevocable
    ``HOLD_TEST_RUNNER`` and therefore cannot produce a feasibility PASS.
    """
    root = (repo_root or Path(__file__).resolve().parents[2]).resolve(strict=True)
    _audit_sensitive_fds()
    run_dir = Path(os.path.abspath(run_dir))
    _portable_repo_path(run_dir, root, "run directory")
    expected_prereg = _require_sha(preregistration_sha256, "preregistration")
    prereg_path = run_dir / "PREREGISTRATION.json"
    prereg_data = _read_regular_stable(prereg_path)
    if _sha256_bytes(prereg_data) != expected_prereg:
        raise GenerationFailure("PREREGISTRATION_DRIFT", "preregistration digest mismatch")
    prereg = _load_canonical_json(prereg_path)
    if (
        prereg.get("schema_version") != PREREGISTRATION_SCHEMA
        or prereg.get("state") != "PREREGISTERED_WITH_MANDATORY_HOLDS"
        or prereg.get("run_id") != run_dir.name
        or prereg.get("datasets") != _dataset_binding()
    ):
        raise GenerationFailure("PREREGISTRATION_SCHEMA", "preregistration schema/state mismatch")
    if arm_runner is None:
        _validate_production_preregistration(prereg, root, run_dir)
    if (run_dir / "scores").exists() or (run_dir / "feasibility" / "FEASIBILITY_PASS.json").exists():
        raise GenerationFailure("GENERATION_LOCKED", "scoring or feasibility output already exists")
    if (run_dir / "final" / "VERDICT.json").exists() or (run_dir / "generation" / "ARTIFACT_MANIFEST.json").exists():
        raise GenerationFailure("GENERATION_LOCKED", "run is already terminal or sealed")

    runner = arm_runner or _default_arm_runner
    holds = set(UNRESOLVED_PRODUCTION_HOLDS)
    if arm_runner is not None:
        holds.add("HOLD_TEST_RUNNER")
    execution_specs = prereg["execution_protocol"]["executions"]
    if [item["key"] for item in execution_specs] != [item[0] for item in FROZEN_EXECUTIONS]:
        raise GenerationFailure("EXECUTION_ORDER_DRIFT", "preregistered arm order drifted")

    generation_root = run_dir / "generation"
    if generation_root.exists() or generation_root.is_symlink():
        raise GenerationFailure("GENERATION_LOCKED", "generation directory already exists")
    generation_root.mkdir(mode=0o700)
    reverify_dir = generation_root / "reverify"
    reverify_dir.mkdir(mode=0o700)
    executions: dict[str, dict[str, Any]] = {}
    try:
        for item, frozen in zip(execution_specs, FROZEN_EXECUTIONS, strict=True):
            key, arm, relative = frozen
            if item["arm"] != arm or item["relative_output"] != relative:
                raise GenerationFailure("EXECUTION_ORDER_DRIFT", "preregistered arm mapping drifted")
            pre = _reverify_inputs(
                run_dir,
                prereg,
                root,
                f"{key}:before",
                strict_source=arm_runner is None,
            )
            _write_new_atomic(reverify_dir / f"{key}.before.json", canonical_json_bytes(pre))
            final_dir = run_dir / relative
            if final_dir.exists() or final_dir.is_symlink():
                raise GenerationFailure("ARM_OUTPUT_COLLISION", f"{key} output already exists")
            argv = list(item["argv"])
            _reject_forbidden_content(argv, "generation argv")
            completed = None
            runner_error: BaseException | None = None
            try:
                completed = runner(argv, FIXED_ENVIRONMENT)
            except BaseException as exc:
                runner_error = exc
            post = _reverify_inputs(
                run_dir,
                prereg,
                root,
                f"{key}:after",
                strict_source=arm_runner is None,
            )
            _write_new_atomic(reverify_dir / f"{key}.after.json", canonical_json_bytes(post))
            if runner_error is not None:
                raise GenerationFailure("ARM_RUNNER_EXCEPTION", f"{key} supervisor invocation failed") from runner_error
            if type(completed) is not subprocess.CompletedProcess:
                raise GenerationFailure("RUNNER_PROTOCOL", "arm runner returned an invalid result")
            if completed.returncode != 0:
                raise GenerationFailure("ARM_FAILED", f"{key} supervisor returned nonzero")
            # Supervisor stdout is a diagnostic only.  The sealed arm receipt is authoritative.
            if not final_dir.is_dir() or final_dir.is_symlink():
                raise GenerationFailure("ARM_PUBLICATION_MISSING", f"{key} did not publish its final directory")
            execution = _validate_arm_receipt(
                final_dir,
                arm,
                prereg["effective_config_sha256"][arm],
                relative,
                _resolve_repo_path(root, prereg["inputs"]["image_view"], "image view"),
                Path(prereg["inputs"]["deepcenter"]["checkpoint"]["path"]).name,
                Path(prereg["inputs"]["deepcenter"]["manifest"]["path"]).name,
                strict_semantics=arm_runner is None,
            )
            execution["pre_reverify_sha256"] = _sha256_bytes(canonical_json_bytes(pre))
            execution["post_reverify_sha256"] = _sha256_bytes(canonical_json_bytes(post))
            executions[key] = execution
            # The generation consumer independently verifies the exact READY
            # schema, decoded-content pin, raw/image byte inventories, and each
            # pre/post arm rehash.  That evidence clears only the supervisor's
            # local data-readiness placeholder; immutable locking remains held.
            holds.update(item for item in execution["holds"] if item != "HOLD_DATA_NOT_READY")

        replay = _assert_replay(run_dir, executions)
        canonical_graphs = {arm: _publish_typed_graph(run_dir, executions, arm) for arm in ("baseline", "candidate")}
        candidate_wall = max(
            executions["candidate_ab"]["duration_monotonic_ns"],
            executions["candidate_ba"]["duration_monotonic_ns"],
        )
        baseline_wall = min(
            executions["baseline_ab"]["duration_monotonic_ns"],
            executions["baseline_ba"]["duration_monotonic_ns"],
        )
        candidate_rss = max(
            executions["candidate_ab"]["ru_maxrss_normalized_bytes"],
            executions["candidate_ba"]["ru_maxrss_normalized_bytes"],
        )
        baseline_rss = min(
            executions["baseline_ab"]["ru_maxrss_normalized_bytes"],
            executions["baseline_ba"]["ru_maxrss_normalized_bytes"],
        )
        relative_wall = candidate_wall <= 1.25 * baseline_wall
        relative_rss_diagnostic = candidate_rss <= baseline_rss + 1_073_741_824
        if not relative_wall:
            holds.add("HOLD_LOCAL_RUNTIME_GATE_FAILED")
        # Process-only ru_maxrss is never elevated to a gate result.
        if not relative_rss_diagnostic:
            holds.add("HOLD_LOCAL_RSS_DIAGNOSTIC_FAILED")

        all_inventory = _tree_records(generation_root)
        manifest = {
            "schema_version": GENERATION_SCHEMA,
            "state": "GENERATION_HELD",
            "run_id": run_dir.name,
            "preregistration_sha256": expected_prereg,
            "datasets": _dataset_binding(),
            "execution_order": [item[0] for item in FROZEN_EXECUTIONS],
            "executions": executions,
            "replay": replay,
            "canonical_typed_graphs": canonical_graphs,
            "resource_diagnostics": {
                "candidate_wall_gate_ns": candidate_wall,
                "baseline_wall_gate_ns": baseline_wall,
                "local_relative_wall_pass": relative_wall,
                "candidate_process_rss_bytes": candidate_rss,
                "baseline_process_rss_bytes": baseline_rss,
                "local_process_rss_diagnostic_pass": relative_rss_diagnostic,
                "process_rss_authoritative_for_gate": False,
            },
            "artifact_tree_sha256": _sha256_bytes(canonical_json_bytes(all_inventory)),
            "artifact_inventory": all_inventory,
            "holds": sorted(holds),
            "claims": {
                "label_blind_generation_complete": False,
                "local_five_arm_artifacts_validated": True,
                "production_generation_sealed": False,
                "deterministic_replay_verified": True,
                "available_input_bytes_stable_at_checks": True,
                "immutable_snapshot_or_exclusive_lock_proven": False,
                "gt_nonvisibility_proven": False,
                "whole_process_tree_measured": False,
                "target_runtime_calibrated": False,
                "target_memory_calibrated": False,
                "feasibility_pass": False,
            },
        }
        manifest_path = generation_root / "ARTIFACT_MANIFEST.json"
        manifest_data = canonical_json_bytes(manifest)
        _write_new_atomic(manifest_path, manifest_data)
        manifest_sha = _sha256_bytes(manifest_data)
        return _publish_terminal_hold(
            run_dir,
            expected_prereg,
            code="GENERATION_COMPLETE_WITH_UNRESOLVED_HOLDS",
            holds=sorted(holds),
            generation_manifest_sha=manifest_sha,
            detail="five-arm label-blind evidence sealed; production feasibility and GT scoring remain locked",
        )
    except GenerationFailure as exc:
        holds.add(exc.code)
        return _publish_terminal_hold(
            run_dir,
            expected_prereg,
            code=exc.code,
            holds=sorted(holds),
            generation_manifest_sha=None,
            detail=str(exc),
        )


__all__ = [
    "EVAL12",
    "EVAL24",
    "EVAL36",
    "FROZEN_EXECUTIONS",
    "GenerationFailure",
    "GenerationResult",
    "PreregistrationSpec",
    "canonical_json_bytes",
    "generate",
    "preregister",
]
