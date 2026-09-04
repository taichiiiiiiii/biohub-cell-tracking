"""Fail-closed preparation and sealing of ST-R3 code-safety prerequisites.

Production profiles and artifact paths are frozen here. The production CLI
accepts only a prerequisite kind and a fresh run directory. Its explicit
``execute`` action runs the source-bound RUN_SPEC directly without a shell;
``seal`` only validates existing execution evidence and never launches work.
Public-four details remain inside the final parity receipt, while
:func:`validate_prerequisite_receipt` returns only an opaque hash/verdict
reference.
"""

from __future__ import annotations

import contextlib
import csv
import ctypes
import datetime as dt
import errno
import hashlib
import io
import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

RUN_SPEC_SCHEMA = "biohub.st_r3.prerequisite_run_spec.v1"
EXECUTION_SCHEMA = "biohub.st_r3.execution_receipt.v1"
EXECUTION_NAME = "EXECUTION_RECEIPT.json"
E23_SCHEMA = "biohub.st_r3.e23_parity_receipt.v1"
BASE1_SCHEMA = "biohub.st_r3.base1_non_regression_receipt.v1"
OFFICIAL_OID = "075fc5f5a52d11077f9dc2b074644618f26939e2"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_GIT_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_RUN_NAME = re.compile(r"\d{8}T\d{6}Z_[0-9a-f]{7,12}\Z")
_READ_CHUNK = 1024 * 1024
_MAX_JSON = 8 * 1024 * 1024
_MAX_LOG = 4 * 1024 * 1024
_TERM_GRACE_SECONDS = 1.0
_KILL_GRACE_SECONDS = 2.0

PUBLIC_FOUR = ("44b6_0113de3b", "44b6_0b24845f", "6bba_05b6850b", "6bba_05db0fb1")
BASE1_FOUR = ("44b6_12dfb391", "44b6_267148e4", "44b6_2a2eff9f", "44b6_341df25f")

_SOURCE_PATHS = (
    "pyproject.toml",
    "uv.lock",
    "scripts/local_eval.py",
    "scripts/postproc_geffs.py",
    "scripts/st_r3_prerequisite.py",
    "src/biohub/evaluate.py",
    "src/biohub/st_r3_prerequisites.py",
    "src/biohub/public_postproc/__init__.py",
    "src/biohub/public_postproc/config.py",
    "src/biohub/public_postproc/csv_out.py",
    "src/biohub/public_postproc/deepcenter.py",
    "src/biohub/public_postproc/divisions.py",
    "src/biohub/public_postproc/frames.py",
    "src/biohub/public_postproc/geometry.py",
    "src/biohub/public_postproc/graph_ops.py",
    "src/biohub/public_postproc/pipeline.py",
    "src/biohub/public_postproc/production_adapter.py",
    "src/biohub/public_postproc/production_supervisor.py",
    "tests/test_st_r3_prerequisites.py",
)
_OFFICIAL_PATHS = (
    "official/src/tracking_cellmot/__init__.py",
    "official/src/tracking_cellmot/division_metrics.py",
    "official/src/tracking_cellmot/io.py",
    "official/src/tracking_cellmot/metrics.py",
)

_STEAL_FIELDS = tuple(
    """steal_twin_examined_frames steal_twin_p_pool steal_twin_q_pool
    steal_twin_enumerated steal_twin_rejected_distance_twin
    steal_twin_rejected_ambiguous_p_nn steal_twin_rejected_ambiguous_q_nn
    steal_twin_rejected_not_mutual_parent_nn steal_twin_rejected_distance_existing_child
    steal_twin_rejected_distance_parent steal_twin_rejected_distance_sister_low
    steal_twin_rejected_distance_sister_high steal_twin_rejected_time
    steal_twin_rejected_missing_successor steal_twin_rejected_shared_successor
    steal_twin_rejected_divergence steal_twin_rejected_synthetic
    steal_twin_rejected_deepcenter_bundle steal_twin_rejected_deepcenter_dataset
    steal_twin_rejected_deepcenter_frame steal_twin_rejected_deepcenter_heatmap
    steal_twin_rejected_deepcenter_nonfinite steal_twin_rejected_deepcenter_threshold
    steal_twin_eligible steal_twin_rejected_conflict steal_twin_rejected_frame_cap
    steal_twin_rejected_video_cap steal_twin_accepted steal_twin_planned_edges_removed
    steal_twin_planned_edges_added steal_twin_edges_removed steal_twin_edges_added
    steal_twin_isolated_donors steal_twin_validation_failed
    steal_twin_validation_missing_node_field steal_twin_validation_invalid_node_id
    steal_twin_validation_duplicate_node_id steal_twin_validation_invalid_node_time
    steal_twin_validation_nonfinite_node_coordinate steal_twin_validation_invalid_edge_endpoint
    steal_twin_validation_dangling_edge steal_twin_validation_duplicate_edge
    steal_twin_validation_nonconsecutive_edge steal_twin_validation_indegree
    steal_twin_validation_outdegree steal_twin_validation_nonfinite_edge_distance
    steal_twin_debug_records_written steal_twin_debug_records_dropped
    steal_twin_mutations_applied steal_twin_pure_nodes steal_twin_pure_edges
    steal_twin_pure_fork_sources steal_twin_pure_edge_symmetric_difference
    steal_twin_geometry_edges_removed_observed steal_twin_prune_nodes_removed_observed
    steal_twin_prune_edges_removed_observed steal_twin_short_nodes_removed_observed
    steal_twin_short_edges_removed_observed steal_twin_final_nodes steal_twin_final_edges
    steal_twin_final_fork_sources steal_twin_linefit_coordinate_changed_nodes_observed""".split()
)


class PrerequisiteError(RuntimeError):
    """Prerequisite evidence is incomplete, unsafe, or inconsistent."""


class PublicationAmbiguityError(PrerequisiteError):
    """A failed publication could not prove durable absence."""


class _ChildInterrupted(BaseException):
    """Carries truthful child evidence after bounded process-group shutdown."""

    def __init__(self, record: dict[str, object]) -> None:
        super().__init__(str(record["interruption"]))
        self.record = record


@dataclass(frozen=True)
class FilePin:
    path: str
    sha256: str
    bytes: int | None = None


@dataclass(frozen=True)
class TreePin:
    path: str
    roots: tuple[str, ...]
    files: int
    bytes: int
    sha256: str
    root_sha256: tuple[str, ...] = ()
    symlink_target_parent: str | None = None


@dataclass(frozen=True)
class Profile:
    kind: str
    receipt_schema: str
    receipt_name: str
    run_parent: str
    datasets: tuple[str, ...]
    raw: TreePin
    images: TreePin | None
    gt_roots: tuple[TreePin, ...]
    references: tuple[FilePin, ...]
    reference_submission: FilePin
    reference_stats: FilePin
    reference_score: FilePin | None
    submission_sha256: str
    submission_rows: int
    graph_sha256: str | None
    exact_graph_sha256: str | None
    graph_counts: tuple[tuple[str, int, int, int, int], ...]
    deepcenter_manifest: FilePin | None = None
    deepcenter_checkpoint: FilePin | None = None
    source_paths: tuple[str, ...] = _SOURCE_PATHS
    official_paths: tuple[str, ...] = _OFFICIAL_PATHS
    official_oid: str = OFFICIAL_OID
    steal_fields: tuple[str, ...] = _STEAL_FIELDS
    launcher_env_path: str = "/usr/bin/env"
    uv_path: str = "/opt/homebrew/bin/uv"
    test_only: bool = False


_RAW_PUBLIC = "outputs/kaggle/e22_bidir030_public4_raw/tracking_repo/predictions/unknown/unet_transformer/split_0"
_DC = "outputs/kaggle/e23_artifacts/pilkwang/biohub-deepcenter-unet3d-center-prior-v1"

E23_PROFILE = Profile(
    kind="e23",
    receipt_schema=E23_SCHEMA,
    receipt_name="E23_PARITY_RECEIPT.json",
    run_parent="outputs/local/st_r3_prerequisites/e23",
    datasets=PUBLIC_FOUR,
    raw=TreePin(
        _RAW_PUBLIC,
        tuple(f"{item}.geff" for item in PUBLIC_FOUR),
        132,
        1_583_021,
        "5fc5fb5e51d127612421970ed66f0ba4229f020940ed458dfdf0fa316f2e8bc1",
        (
            "a4151aad5042a93e3fce9a7f42a2c5b994e83137d2686049c60540e8f9d56fdb",
            "dfb6885f043250ec106658dcba2bd3d1da14fd02cc75a0bbbbcdc229cd817528",
            "881a827867dc142236db6b5558a331fdc2f26d07ca15c2e978e5ef8c01c6412f",
            "ceb3bd1512cc1482b3349c3d52c4db1a79333209f8f978028daa38183ccfc515",
        ),
    ),
    images=TreePin(
        "data/test",
        tuple(f"{item}.zarr" for item in PUBLIC_FOUR),
        408,
        1_906_332_008,
        "0b9e6e060437104fb261b388f45eae494abcca59155b4bc9fc4fac24bedd9bbd",
        (
            "987acb0038ef744c0265f028fc003e04182fccac0e520afb8704c426926425ac",
            "0c50cb7ef2bb45d1e7414fce46c6c2e37c3829ce805295c3fcad0701440a7140",
            "8f3388f202ab0a483552becd6ffbac6cd13f29ee35ff760bd8c940f5198b5346",
            "fd1913480fcb34db07b72bcaeeb44d1e3488676c3fed982555cd4b06c123416a",
        ),
    ),
    gt_roots=tuple(
        TreePin(f"data/train/{stem}.geff", (), 0, 0, digest)
        for stem, digest in zip(
            PUBLIC_FOUR,
            (
                "db3939aa55ca05306e1d563b80fc458e17f7e61bea60734bf265c695fb3f0fef",
                "d2156aa79ee2b2a72d331fdaa4de67970c97540d2462fb97f94240dc54f45879",
                "aec2da8c1abab059e07a2893a2ee92ebe7efe8101d72e10a0c6e445d4e5f4bcb",
                "11ab0471fdc59dc15c51c9e94eac8c54482aaf2e7b5a2c7ead77a009eade6142",
            ),
            strict=True,
        )
    ),
    references=(
        FilePin(
            "outputs/kaggle/e22_bidir030_public4_raw/DOWNLOAD_MANIFEST.json",
            "9cc95d3e00b75eaeeb05a1798cc1a1fd0cfb18be1d3239c9b64608527933806b",
        ),
        FilePin(f"{_DC}/ARTIFACT_MANIFEST.json", "1eedc1af72b10c464c6995013075310510b6f6e634450ff2bc170c67b89ce911"),
        FilePin(
            f"{_DC}/weights/full_frame_center/SNAPSHOT_MANIFEST.json",
            "a05f5ef2aba1ae3b3ddfcbd4e655c0af98c63e522403c1b371e588f5d928c646",
        ),
        FilePin(
            f"{_DC}/weights/full_frame_center/config.json",
            "9b0d1d8a0bbcd6661795efe1c1221288ee152f29a6d63ded26278986b74e97b3",
        ),
        FilePin(
            f"{_DC}/weights/full_frame_center/best.pt",
            "8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0",
            37_876_911,
        ),
    ),
    reference_submission=FilePin(
        "outputs/kaggle/e23_reference/submission.csv",
        "33c179b0449b9cdd186f06a653cddc8cf12359f008982f6713cdf30784a52e6a",
    ),
    reference_stats=FilePin(
        "outputs/kaggle/e23_reference/run_stats.csv",
        "19f9a0b5b6bb3c903b3dd3d8f6cb25cc9f90a201fae009b3505b140b432fd956",
    ),
    reference_score=FilePin(
        "outputs/kaggle/e23_reference/official_public4_score.json",
        "3afc4a1a5f4319daa27c92eb1486aed010d0e7e8231ad408bd7d2682b36ba71e",
    ),
    submission_sha256="33c179b0449b9cdd186f06a653cddc8cf12359f008982f6713cdf30784a52e6a",
    submission_rows=240_126,
    graph_sha256="7c71134d70413986f3e557c91b59db019260d27a93e438ba3770fd5c464338fd",
    exact_graph_sha256="b6ea4e3a4967f42f4120b3abdc9a04eaf67c3f1a3a0a06739e8d009ee0355add",
    graph_counts=(
        ("44b6_0113de3b", 50_253, 25_485, 24_768, 57),
        ("44b6_0b24845f", 38_558, 19_905, 18_653, 77),
        ("6bba_05b6850b", 12_085, 6_142, 5_943, 11),
        ("6bba_05db0fb1", 139_230, 70_675, 68_555, 118),
    ),
    deepcenter_manifest=FilePin(
        f"{_DC}/ARTIFACT_MANIFEST.json",
        "1eedc1af72b10c464c6995013075310510b6f6e634450ff2bc170c67b89ce911",
    ),
    deepcenter_checkpoint=FilePin(
        f"{_DC}/weights/full_frame_center/best.pt",
        "8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0",
        37_876_911,
    ),
)

BASE1_PROFILE = Profile(
    kind="base1",
    receipt_schema=BASE1_SCHEMA,
    receipt_name="BASE1_NON_REGRESSION_RECEIPT.json",
    run_parent="outputs/local/st_r3_prerequisites/base1",
    datasets=BASE1_FOUR,
    raw=TreePin(
        "outputs/local/eval4_raw_geffs",
        tuple(f"{item}.geff" for item in BASE1_FOUR),
        132,
        1_448_288,
        "7148a3adabe187768a8ef8eb27009b6a27f96f6a079b8f274cd00587b9cadb42",
        symlink_target_parent=(
            "outputs/kaggle/e22_bidir030_eval36_raw/tracking_repo/predictions/unknown/unet_transformer_val/split_0"
        ),
    ),
    images=None,
    gt_roots=(),
    references=(),
    reference_submission=FilePin(
        "outputs/local/eval4_base1/submission.csv",
        "56b8fab98992bc5c6ed1dcaba32ad7116ebbf6c185a5fcc31ed39cc56fb992ab",
    ),
    reference_stats=FilePin(
        "outputs/local/eval4_base1/run_stats.csv",
        "17977c29f42259bd2c365f2cbb2e58fc284075c7b63656a8f7efab426e200a91",
    ),
    reference_score=None,
    submission_sha256="56b8fab98992bc5c6ed1dcaba32ad7116ebbf6c185a5fcc31ed39cc56fb992ab",
    submission_rows=217_778,
    graph_sha256="952e137d6aeca3889f86efad55fbe01543394961e0c8d789ebd051dd874e405e",
    exact_graph_sha256="802ea240bd70cfd8fc7192a4f1bcfd1c98982d6eedb7642311a8d8e6460fb9e3",
    graph_counts=(
        ("44b6_12dfb391", 87_239, 44_337, 42_902, 126),
        ("44b6_267148e4", 42_965, 21_915, 21_050, 67),
        ("44b6_2a2eff9f", 71_007, 36_284, 34_723, 135),
        ("44b6_341df25f", 16_567, 8_403, 8_164, 20),
    ),
)

PROFILES = {"e23": E23_PROFILE, "base1": BASE1_PROFILE}


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def strict_json(raw: bytes) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise PrerequisiteError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def finite(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise PrerequisiteError("non-finite JSON number")
        return parsed

    try:
        return json.loads(
            raw.decode(), object_pairs_hook=pairs, parse_float=finite, parse_constant=lambda value: finite(value)
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PrerequisiteError(f"invalid JSON: {error}") from error


def _safe_rel(value: str) -> tuple[str, ...]:
    path = PurePosixPath(value)
    if not value or value.startswith("/") or "\\" in value or str(path) != value:
        raise PrerequisiteError(f"unsafe relative path: {value!r}")
    if any(
        part in {"", ".", ".."} or part != part.strip() or any(ord(character) < 32 for character in part)
        for part in path.parts
    ):
        raise PrerequisiteError(f"unsafe relative path: {value!r}")
    return path.parts


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _reject_casefold_collisions(names: list[str] | tuple[str, ...], logical: str) -> None:
    folded = [name.casefold() for name in names]
    if len(folded) != len(set(folded)):
        raise PrerequisiteError(f"casefold-colliding members: {logical}")


def _open_dir(path: Path) -> int:
    absolute = Path(os.path.abspath(path))
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        path_info = absolute.lstat()
        if not stat.S_ISDIR(path_info.st_mode) or _identity(path_info) != _identity(os.fstat(fd)):
            raise PrerequisiteError(f"unsafe directory: {path}")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_relative_dir(root_fd: int, parts: tuple[str, ...], logical: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.dup(root_fd)
    try:
        for part in parts:
            next_fd: int | None = None
            try:
                next_fd = os.open(part, flags, dir_fd=fd)
                path_info = os.stat(part, dir_fd=fd, follow_symlinks=False)
                if _identity(path_info) != _identity(os.fstat(next_fd)):
                    raise PrerequisiteError(f"directory identity drift: {logical}")
            except BaseException:
                if next_fd is not None:
                    os.close(next_fd)
                raise
            os.close(fd)
            assert next_fd is not None
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_at_stable(
    parent_fd: int, name: str, logical: str, *, limit: int | None = None
) -> tuple[bytes, os.stat_result]:
    fd = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        dir_fd=parent_fd,
    )
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise PrerequisiteError(f"unsafe file: {logical}")
        if limit is not None and before.st_size > limit:
            raise PrerequisiteError(f"oversized file: {logical}")
        chunks: list[bytes] = []
        while chunk := os.read(fd, _READ_CHUNK):
            chunks.append(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        path_info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            len(raw) != before.st_size
            or _identity(before) != _identity(after)
            or _identity(before) != _identity(path_info)
        ):
            raise PrerequisiteError(f"file changed while reading: {logical}")
        return raw, before
    finally:
        os.close(fd)


def _read_at(parent_fd: int, name: str, logical: str, *, limit: int | None = None) -> bytes:
    return _read_at_stable(parent_fd, name, logical, limit=limit)[0]


def _read_repo(repo_root: Path, relative: str, *, limit: int | None = None) -> bytes:
    return _read_repo_stable(repo_root, relative, limit=limit)[0]


def _read_repo_stable(repo_root: Path, relative: str, *, limit: int | None = None) -> tuple[bytes, os.stat_result]:
    parts = _safe_rel(relative)
    root_fd = _open_dir(repo_root)
    try:
        parent = _open_relative_dir(root_fd, parts[:-1], relative)
        try:
            return _read_at_stable(parent, parts[-1], relative, limit=limit)
        finally:
            os.close(parent)
    finally:
        os.close(root_fd)


def _open_repo_dir(repo_root: Path, relative: str) -> int:
    root_fd = _open_dir(repo_root)
    try:
        return _open_relative_dir(root_fd, _safe_rel(relative), relative)
    finally:
        os.close(root_fd)


def _ensure_repo_directory(repo_root: Path, relative: str) -> None:
    parts = _safe_rel(relative)
    fd = _open_dir(repo_root)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        for index, part in enumerate(parts):
            child: int | None = None
            try:
                try:
                    child = os.open(part, flags, dir_fd=fd)
                except FileNotFoundError:
                    os.mkdir(part, 0o755, dir_fd=fd)
                    os.fsync(fd)
                    child = os.open(part, flags, dir_fd=fd)
                info = os.stat(part, dir_fd=fd, follow_symlinks=False)
                if _identity(info) != _identity(os.fstat(child)):
                    logical = "/".join(parts[: index + 1])
                    raise PrerequisiteError(f"directory identity drift: {logical}")
            except FileNotFoundError:
                if child is not None:
                    os.close(child)
                raise
            except BaseException:
                if child is not None:
                    os.close(child)
                raise
            os.close(fd)
            assert child is not None
            fd = child
    finally:
        os.close(fd)


def _file_evidence(repo_root: Path, pin: FilePin, *, require_pin: bool = True) -> dict[str, object]:
    raw = _read_repo(repo_root, pin.path)
    return _raw_file_evidence(pin, raw, require_pin=require_pin)


def _raw_file_evidence(pin: FilePin, raw: bytes, *, require_pin: bool = True) -> dict[str, object]:
    digest = hashlib.sha256(raw).hexdigest()
    if require_pin and pin.sha256 and digest != pin.sha256:
        raise PrerequisiteError(f"file SHA drift: {pin.path}")
    if pin.bytes is not None and len(raw) != pin.bytes:
        raise PrerequisiteError(f"file byte count drift: {pin.path}")
    return {"path": pin.path, "bytes": len(raw), "sha256": digest}


def _executable_evidence(repo_root: Path, argv_path: str) -> dict[str, object]:
    logical = Path(argv_path)
    path = logical if logical.is_absolute() else repo_root / logical
    before = path.lstat()
    if before.st_nlink != 1:
        raise PrerequisiteError(f"unsafe launcher link count: {argv_path}")
    link_target: str | None = None
    target = path
    if stat.S_ISLNK(before.st_mode):
        link_target = os.readlink(path)
        target = Path(os.path.abspath(path.parent / link_target))
    parent = _open_dir(target.parent)
    try:
        raw = _read_at(parent, target.name, argv_path)
        executable = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
    finally:
        os.close(parent)
    after = path.lstat()
    if _identity(before) != _identity(after) or not executable.st_mode & 0o111:
        raise PrerequisiteError(f"launcher executable drift: {argv_path}")
    return {
        "argv_path": argv_path,
        "symlink_target": link_target,
        "mode": format(stat.S_IMODE(executable.st_mode), "04o"),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _walk(fd: int, prefix: str = "") -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    before = os.fstat(fd)
    names = sorted(os.listdir(fd), key=lambda item: item.encode())
    _reject_casefold_collisions(names, prefix or ".")
    for name in names:
        if "\\" in name or any(ord(character) < 32 for character in name):
            raise PrerequisiteError(f"non-portable tree member: {name!r}")
        logical = f"{prefix}/{name}" if prefix else name
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            child = _open_relative_dir(fd, (name,), logical)
            try:
                records.extend(_walk(child, logical))
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            raw = _read_at(fd, name, logical)
            records.append({"path": logical, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        else:
            raise PrerequisiteError(f"symlink/special/hardlink in tree: {logical}")
    if _identity(before) != _identity(os.fstat(fd)):
        raise PrerequisiteError(f"tree directory changed: {prefix or '.'}")
    return records


def _tree_digest(records: list[dict[str, object]]) -> str:
    payload = b"".join(f"{item['sha256']}  ./{item['path']}\n".encode() for item in records)
    return hashlib.sha256(payload).hexdigest()


def _tree_evidence(repo_root: Path, pin: TreePin) -> dict[str, object]:
    root_fd = _open_repo_dir(repo_root, pin.path)
    try:
        before = os.fstat(root_fd)
        names = tuple(sorted(os.listdir(root_fd), key=lambda item: item.encode()))
        _reject_casefold_collisions(names, pin.path)
        if set(names) != set(pin.roots) or len(names) != len(pin.roots):
            raise PrerequisiteError(f"tree root set drift: {pin.path}")
        records: list[dict[str, object]] = []
        root_digests: list[str] = []
        for name in pin.roots:
            info = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            if pin.symlink_target_parent is None:
                if not stat.S_ISDIR(info.st_mode):
                    raise PrerequisiteError(f"unsafe tree root: {pin.path}/{name}")
                child = _open_relative_dir(root_fd, (name,), name)
            else:
                if not stat.S_ISLNK(info.st_mode):
                    raise PrerequisiteError(f"base1 root is not the fixed symlink: {name}")
                link = os.readlink(name, dir_fd=root_fd)
                target = Path(os.path.abspath(repo_root / pin.path / link))
                expected = Path(os.path.abspath(repo_root / pin.symlink_target_parent / name))
                if target != expected:
                    raise PrerequisiteError(f"base1 symlink target drift: {name}")
                child = _open_dir(expected)
            try:
                child_records = _walk(child, name)
                child_identity = _identity(os.fstat(child))
            finally:
                os.close(child)
            if pin.symlink_target_parent is None:
                current = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
                if _identity(current) != child_identity:
                    raise PrerequisiteError(f"tree root identity drift: {pin.path}/{name}")
            else:
                current = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
                if _identity(current) != _identity(info) or os.readlink(name, dir_fd=root_fd) != link:
                    raise PrerequisiteError(f"base1 symlink identity drift: {name}")
                target_check = _open_dir(expected)
                try:
                    if _identity(os.fstat(target_check)) != child_identity:
                        raise PrerequisiteError(f"base1 target identity drift: {name}")
                finally:
                    os.close(target_check)
            records.extend(child_records)
            root_digests.append(
                _tree_digest([{**item, "path": item["path"].split("/", 1)[1]} for item in child_records])
            )
        records.sort(key=lambda item: str(item["path"]).encode())
        if (
            _identity(before) != _identity(os.fstat(root_fd))
            or tuple(sorted(os.listdir(root_fd), key=lambda item: item.encode())) != names
        ):
            raise PrerequisiteError(f"tree changed while scanning: {pin.path}")
    finally:
        os.close(root_fd)
    digest = _tree_digest(records)
    if len(records) != pin.files or sum(int(item["bytes"]) for item in records) != pin.bytes or digest != pin.sha256:
        raise PrerequisiteError(f"tree aggregate drift: {pin.path}")
    if pin.root_sha256 and tuple(root_digests) != pin.root_sha256:
        raise PrerequisiteError(f"tree per-root digest drift: {pin.path}")
    return {
        "path": pin.path,
        "roots": list(pin.roots),
        "files": len(records),
        "bytes": pin.bytes,
        "sha256": digest,
        "root_sha256": root_digests,
        "symlink_target_parent": pin.symlink_target_parent,
        "records": records,
    }


def _single_root_evidence(repo_root: Path, pin: TreePin) -> dict[str, object]:
    fd = _open_repo_dir(repo_root, pin.path)
    try:
        opened = _identity(os.fstat(fd))
        records = _walk(fd)
    finally:
        os.close(fd)
    reopened = _open_repo_dir(repo_root, pin.path)
    try:
        if _identity(os.fstat(reopened)) != opened:
            raise PrerequisiteError(f"GT root identity drift: {pin.path}")
    finally:
        os.close(reopened)
    digest = _tree_digest(records)
    if digest != pin.sha256:
        raise PrerequisiteError(f"GT tree digest drift: {pin.path}")
    return {
        "path": pin.path,
        "files": len(records),
        "bytes": sum(int(item["bytes"]) for item in records),
        "sha256": digest,
        "records": records,
    }


def _git_environment() -> dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
        "TZ": "UTC",
    }


def _git_bytes(repo_root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["/usr/bin/git", *args],
        cwd=repo_root,
        env=_git_environment(),
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise PrerequisiteError(f"git check failed: {' '.join(args)}")
    return result.stdout


def _git_blob_batch(repo_root: Path, object_ids: list[str]) -> dict[str, bytes]:
    if not object_ids:
        return {}
    result = subprocess.run(
        ["/usr/bin/git", "cat-file", "--batch"],
        cwd=repo_root,
        env=_git_environment(),
        input=b"".join(f"{oid}\n".encode() for oid in object_ids),
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise PrerequisiteError("git batch blob read failed")
    output = result.stdout
    offset = 0
    blobs: dict[str, bytes] = {}
    for expected_oid in object_ids:
        newline = output.find(b"\n", offset)
        if newline < 0:
            raise PrerequisiteError("truncated git batch blob header")
        try:
            oid, kind, size_text = output[offset:newline].decode("ascii").split()
            size = int(size_text)
        except (UnicodeDecodeError, ValueError) as error:
            raise PrerequisiteError("invalid git batch blob header") from error
        start = newline + 1
        end = start + size
        if oid != expected_oid or kind != "blob" or end >= len(output) or output[end : end + 1] != b"\n":
            raise PrerequisiteError("git batch blob identity drift")
        blobs[oid] = output[start:end]
        offset = end + 1
    if offset != len(output):
        raise PrerequisiteError("unexpected trailing git batch blob output")
    return blobs


def _git(repo_root: Path, *args: str) -> str:
    try:
        return _git_bytes(repo_root, *args).decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise PrerequisiteError(f"non-UTF-8 git output: {' '.join(args)}") from error


def _read_repo_symlink_stable(repo_root: Path, relative: str) -> tuple[bytes, os.stat_result]:
    parts = _safe_rel(relative)
    root_fd = _open_dir(repo_root)
    try:
        parent = _open_relative_dir(root_fd, parts[:-1], relative)
        try:
            before = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISLNK(before.st_mode) or before.st_nlink != 1:
                raise PrerequisiteError(f"unsafe tracked symlink: {relative}")
            target = os.readlink(parts[-1], dir_fd=parent)
            after = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            if _identity(before) != _identity(after) or os.readlink(parts[-1], dir_fd=parent) != target:
                raise PrerequisiteError(f"tracked symlink changed while reading: {relative}")
            return os.fsencode(target), before
        finally:
            os.close(parent)
    finally:
        os.close(root_fd)


def _all_tracked_snapshot(
    checkout: Path, *, explicit_gitlink: tuple[str, str] | None = None
) -> list[dict[str, object]]:
    """Validate every stage-0 tracked entry against HEAD and the worktree."""

    try:
        raw = _git_bytes(checkout, "ls-files", "-s", "-z")
        chunks = [chunk.decode("utf-8") for chunk in raw.split(b"\0") if chunk]
    except UnicodeDecodeError as error:
        raise PrerequisiteError("non-UTF-8 tracked path") from error
    parsed: list[tuple[str, str, str]] = []
    for chunk in chunks:
        match = re.fullmatch(r"(\d{6}) ([0-9a-f]{40}|[0-9a-f]{64}) 0\t(.+)", chunk)
        if match is None:
            raise PrerequisiteError("non-stage-0 or malformed tracked entry")
        mode, oid, path = match.groups()
        _safe_rel(path)
        parsed.append((path, mode, oid))
    paths = [item[0] for item in parsed]
    if len(paths) != len(set(paths)):
        raise PrerequisiteError("duplicate tracked path")
    _reject_casefold_collisions(paths, "tracked index")
    debug_lines = _git(checkout, "ls-files", "--debug").splitlines()
    flags_by_path: dict[str, str] = {}
    cursor = 0
    for path in paths:
        if cursor >= len(debug_lines) or debug_lines[cursor] != path:
            raise PrerequisiteError(f"tracked index metadata drift: {path}")
        cursor += 1
        metadata: list[str] = []
        while cursor < len(debug_lines) and debug_lines[cursor].startswith("  "):
            metadata.append(debug_lines[cursor])
            cursor += 1
        flags = [line.rsplit("flags:", 1)[1].strip() for line in metadata if "flags:" in line]
        if flags != ["0"]:
            raise PrerequisiteError(f"nonzero index flags: {path}")
        flags_by_path[path] = flags[0]
    if cursor != len(debug_lines):
        raise PrerequisiteError("unexpected tracked index metadata")

    try:
        tree_chunks = [
            chunk.decode("utf-8") for chunk in _git_bytes(checkout, "ls-tree", "-rz", "HEAD").split(b"\0") if chunk
        ]
    except UnicodeDecodeError as error:
        raise PrerequisiteError("non-UTF-8 HEAD tree path") from error
    tree_by_path: dict[str, tuple[str, str, str]] = {}
    for chunk in tree_chunks:
        match = re.fullmatch(r"(\d{6}) (blob|commit) ([0-9a-f]{40}|[0-9a-f]{64})\t(.+)", chunk)
        if match is None:
            raise PrerequisiteError("malformed HEAD tree entry")
        mode, kind, oid, path = match.groups()
        tree_by_path[path] = (mode, kind, oid)
    if set(tree_by_path) != set(paths):
        raise PrerequisiteError("HEAD/index tracked path set drift")
    head_blobs = _git_blob_batch(checkout, [oid for _, mode, oid in parsed if mode != "160000"])

    evidence: list[dict[str, object]] = []
    for path, mode, oid in parsed:
        head_mode, head_kind, head_oid = tree_by_path[path]
        if (head_mode, head_oid) != (mode, oid):
            raise PrerequisiteError(f"HEAD/index identity drift: {path}")
        if mode == "160000":
            if head_kind != "commit" or explicit_gitlink != (path, oid):
                raise PrerequisiteError(f"unexpected tracked gitlink: {path}")
            evidence.append({"path": path, "head_mode": mode, "head_commit_oid": oid, "index_flags": "0"})
        elif mode in {"100644", "100755", "120000"}:
            if head_kind != "blob":
                raise PrerequisiteError(f"tracked entry is not a HEAD blob: {path}")
            if mode == "120000":
                working_raw, working_info = _read_repo_symlink_stable(checkout, path)
            else:
                working_raw, working_info = _read_repo_stable(checkout, path)
            object_hash = hashlib.sha1 if len(oid) == 40 else hashlib.sha256  # noqa: S324 - Git object format
            calculated_oid = object_hash(f"blob {len(working_raw)}\0".encode() + working_raw).hexdigest()
            expected_mode = {"100644": 0o644, "100755": 0o755, "120000": 0o777}[mode]
            if (
                working_raw != head_blobs[oid]
                or calculated_oid != oid
                or (mode != "120000" and stat.S_IMODE(working_info.st_mode) != expected_mode)
            ):
                raise PrerequisiteError(f"working file differs from HEAD: {path}")
            evidence.append(
                {
                    "path": path,
                    "bytes": len(working_raw),
                    "sha256": hashlib.sha256(working_raw).hexdigest(),
                    "head_mode": mode,
                    "head_blob_oid": oid,
                    "index_flags": flags_by_path[path],
                }
            )
        else:
            raise PrerequisiteError(f"unsupported tracked mode: {path}")
    return evidence


def _deepcenter_evidence(repo_root: Path, profile: Profile) -> dict[str, object] | None:
    if profile.deepcenter_manifest is None and profile.deepcenter_checkpoint is None:
        return None
    if profile.deepcenter_manifest is None or profile.deepcenter_checkpoint is None:
        raise PrerequisiteError("incomplete DeepCenter profile")
    manifest_raw = _read_repo(repo_root, profile.deepcenter_manifest.path, limit=_MAX_JSON)
    manifest_evidence = _raw_file_evidence(profile.deepcenter_manifest, manifest_raw)
    manifest = strict_json(manifest_raw)
    try:
        checkpoint_claim = manifest["model"]["best_checkpoint"]  # type: ignore[index]
        claim_path = checkpoint_claim["path"]
        claim_bytes = checkpoint_claim["bytes"]
        claim_sha = checkpoint_claim["sha256"]
    except (KeyError, TypeError) as error:
        raise PrerequisiteError("invalid DeepCenter manifest checkpoint claim") from error
    if type(claim_path) is not str:
        raise PrerequisiteError("invalid DeepCenter manifest checkpoint path")
    _safe_rel(claim_path)
    expected_checkpoint = (
        PurePosixPath(profile.deepcenter_manifest.path).parent / PurePosixPath(claim_path)
    ).as_posix()
    if expected_checkpoint != profile.deepcenter_checkpoint.path:
        raise PrerequisiteError("DeepCenter manifest checkpoint path drift")
    checkpoint_raw = _read_repo(repo_root, profile.deepcenter_checkpoint.path, limit=128 * 1024 * 1024)
    checkpoint_evidence = _raw_file_evidence(profile.deepcenter_checkpoint, checkpoint_raw)
    if (
        type(claim_bytes) is not int
        or claim_bytes != checkpoint_evidence["bytes"]
        or type(claim_sha) is not str
        or claim_sha != checkpoint_evidence["sha256"]
    ):
        raise PrerequisiteError("DeepCenter manifest checkpoint identity drift")
    try:
        import torch

        checkpoint = torch.load(io.BytesIO(checkpoint_raw), map_location="cpu", weights_only=True)
    except Exception as error:
        raise PrerequisiteError("DeepCenter weights-only load failed") from error
    if (
        not isinstance(checkpoint, dict)
        or type(checkpoint.get("epoch")) is not int
        or checkpoint["epoch"] != 2
        or not isinstance(checkpoint.get("model_state"), dict)
        or len(checkpoint["model_state"]) != 50
    ):
        raise PrerequisiteError("DeepCenter checkpoint semantic identity drift")
    module_path = Path(torch.__file__).resolve()
    module_parent = _open_dir(module_path.parent)
    try:
        module_raw = _read_at(module_parent, module_path.name, "torch loader module")
    finally:
        os.close(module_parent)
    return {
        "manifest": manifest_evidence,
        "checkpoint": checkpoint_evidence,
        "semantic": {"epoch": 2, "model_state_entries": 50, "weights_only": True},
        "loader": {
            "module": "torch",
            "version": str(torch.__version__),
            "module_file": {
                "name": module_path.name,
                "bytes": len(module_raw),
                "sha256": hashlib.sha256(module_raw).hexdigest(),
            },
        },
    }


def _source_snapshot(repo_root: Path, profile: Profile) -> dict[str, object]:
    git_dir = repo_root / ".git"
    info = git_dir.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise PrerequisiteError("canonical checkout requires a real .git directory")
    if _git(repo_root, "status", "--porcelain", "--untracked-files=all"):
        raise PrerequisiteError("source tree is not completely clean")
    commit = _git(repo_root, "rev-parse", "HEAD")
    tree = _git(repo_root, "rev-parse", "HEAD^{tree}")
    if _GIT_OID.fullmatch(commit) is None or _GIT_OID.fullmatch(tree) is None:
        raise PrerequisiteError("invalid source git identity")
    stage = _git(repo_root, "ls-files", "-s", "official").split()
    if len(stage) < 2 or stage[0] != "160000" or stage[1] != profile.official_oid:
        raise PrerequisiteError("official gitlink drift")
    official_head = _git(repo_root / "official", "rev-parse", "HEAD")
    if official_head != profile.official_oid:
        raise PrerequisiteError("official checkout OID drift")
    if _git(repo_root / "official", "status", "--porcelain", "--untracked-files=all"):
        raise PrerequisiteError("official checkout is dirty")
    all_source_files = _all_tracked_snapshot(repo_root, explicit_gitlink=("official", profile.official_oid))
    all_official_files = _all_tracked_snapshot(repo_root / "official")
    source_by_path = {str(item["path"]): item for item in all_source_files}
    official_by_path = {str(item["path"]): item for item in all_official_files}
    try:
        source_files = [source_by_path[path] for path in profile.source_paths]
        official_files = [
            {
                **official_by_path[PurePosixPath(path).relative_to("official").as_posix()],
                "path": path,
            }
            for path in profile.official_paths
        ]
    except KeyError as error:
        raise PrerequisiteError(f"profile source path is not tracked: {error.args[0]}") from error
    runtime = [
        _executable_evidence(repo_root, profile.launcher_env_path),
        _executable_evidence(repo_root, profile.uv_path),
    ]
    deepcenter = _deepcenter_evidence(repo_root, profile)
    all_source_files_after = _all_tracked_snapshot(repo_root, explicit_gitlink=("official", profile.official_oid))
    all_official_files_after = _all_tracked_snapshot(repo_root / "official")
    if (
        all_source_files_after != all_source_files
        or all_official_files_after != all_official_files
        or _git(repo_root, "rev-parse", "HEAD") != commit
        or _git(repo_root, "rev-parse", "HEAD^{tree}") != tree
        or _git(repo_root, "status", "--porcelain", "--untracked-files=all")
        or _git(repo_root / "official", "rev-parse", "HEAD") != profile.official_oid
        or _git(repo_root / "official", "status", "--porcelain", "--untracked-files=all")
    ):
        raise PrerequisiteError("source changed while snapshotting")
    return {
        "commit": commit,
        "tree": tree,
        "tracked_state": "CLEAN",
        "files": source_files,
        "official": {
            "gitlink_oid": stage[1],
            "checked_out_head": official_head,
            "state": "CLEAN",
            "files": official_files,
        },
        "runtime": runtime,
        "deepcenter": deepcenter,
    }


def _command(profile: Profile, repo_root: Path, run_dir: Path) -> dict[str, object]:
    run = run_dir.relative_to(repo_root).as_posix()
    environment = {
        "CUDA_VISIBLE_DEVICES": "",
        "LANG": "C",
        "LC_ALL": "C",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "PATH": "/opt/homebrew/bin:/usr/bin:/bin",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "TZ": "UTC",
        "UV_FROZEN": "1",
        "UV_NO_CONFIG": "1",
        "UV_NO_SYNC": "1",
        "UV_OFFLINE": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
    }
    launcher = [
        profile.launcher_env_path,
        "-i",
        *(f"{key}={value}" for key, value in sorted(environment.items())),
        profile.uv_path,
    ]
    if profile.kind == "e23":
        postproc = [
            *launcher,
            "run",
            "--frozen",
            "--offline",
            "--no-sync",
            "--extra",
            "deepcenter",
            "python",
            "scripts/postproc_geffs.py",
            "--geff-dir",
            _RAW_PUBLIC,
            "--test-dir",
            "data/test",
            "--profile",
            "e23",
        ]
        checkpoint = f"{_DC}/weights/full_frame_center/best.pt"
        manifest = f"{_DC}/ARTIFACT_MANIFEST.json"
        for key, value in (
            ("BIOHUB_DEEPCENTER_CHECKPOINT", checkpoint),
            ("BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT", checkpoint),
            ("BIOHUB_DEEPCENTER_MANIFEST", manifest),
            ("BIOHUB_DEEPCENTER_MANIFEST_DEFAULT", manifest),
        ):
            postproc.extend(("--set", f"{key}={value}"))
        postproc.extend(("--out", f"{run}/submission.csv", "--run-stats", f"{run}/run_stats.csv"))
        score = [
            *launcher,
            "run",
            "--frozen",
            "--offline",
            "--no-sync",
            "python",
            "scripts/local_eval.py",
            f"{run}/submission.csv",
            "--gt-dir",
            "data/train",
            "--json",
            f"{run}/official_score.json",
        ]
    else:
        postproc = [
            *launcher,
            "run",
            "--frozen",
            "--offline",
            "--no-sync",
            "python",
            "scripts/postproc_geffs.py",
            "--geff-dir",
            profile.raw.path,
            "--test-dir",
            f"{run}/EMPTY_IMAGE_VIEW",
            "--profile",
            "base1",
            "--out",
            f"{run}/submission.csv",
            "--run-stats",
            f"{run}/run_stats.csv",
        ]
        score = []
    return {
        "cwd": ".",
        "environment": environment,
        "execution": {
            "mode": "direct exec without a shell; env -i clears inherited environment",
            "postproc_combined_output": {"create": "exclusive", "path": "postproc.log"},
            "required_exit_code": 0,
            "score_output": (
                "discard; official_score.json is written by fixed argv" if score else "none; score_argv is empty"
            ),
            "sequence": ["create_start_marker", "postproc_argv", *(["score_argv"] if score else [])],
            "start_marker": {
                "content": "code_sha=<RUN_SPEC.source.commit>\\nstarted_utc=<UTC YYYY-MM-DDTHH:MM:SSZ>\\n",
                "create": "exclusive",
                "path": "START_MARKER.txt",
            },
        },
        "postproc_argv": postproc,
        "score_argv": score,
    }


def _run_spec(
    profile: Profile, repo_root: Path, run_dir: Path, created: str, source: dict[str, object]
) -> dict[str, object]:
    artifacts = ["START_MARKER.txt", "postproc.log", "run_stats.csv", "submission.csv"]
    if profile.kind == "e23":
        artifacts.append("official_score.json")
    else:
        artifacts.append("EMPTY_IMAGE_VIEW/")
    return {
        "schema_version": RUN_SPEC_SCHEMA,
        "status": "PREPARED",
        "kind": profile.kind,
        "created_utc": created,
        "source": source,
        "command": _command(profile, repo_root, run_dir),
        "artifacts": artifacts,
    }


def _parse_csv(raw: bytes, label: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        rows = list(csv.reader(io.StringIO(raw.decode(), newline="")))
    except (UnicodeDecodeError, csv.Error) as error:
        raise PrerequisiteError(f"invalid CSV {label}: {error}") from error
    if not rows or not rows[0] or len(rows[0]) != len(set(rows[0])):
        raise PrerequisiteError(f"invalid CSV header: {label}")
    if any(len(row) != len(rows[0]) for row in rows[1:]):
        raise PrerequisiteError(f"ragged CSV: {label}")
    return rows[0], [dict(zip(rows[0], row, strict=True)) for row in rows[1:]]


def _integer(value: str, label: str, *, minimum: int = 0) -> int:
    if not value.isascii() or not value.isdigit() or str(int(value)) != value or int(value) < minimum:
        raise PrerequisiteError(f"invalid integer {label}")
    return int(value)


def _legacy_parity_graph_digest(normalized: dict[str, object]) -> str:
    """Return the frozen E23 notebook normalizer digest (renumbered IDs)."""
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _graph_evidence(raw: bytes, profile: Profile) -> dict[str, object]:
    header, rows = _parse_csv(raw, "submission")
    expected_header = ["id", "dataset", "row_type", "node_id", "t", "z", "y", "x", "source_id", "target_id"]
    if header != expected_header or len(rows) != profile.submission_rows:
        raise PrerequisiteError("submission schema/row count drift")
    seen_order: list[str] = []
    for index, row in enumerate(rows):
        if _integer(row["id"], "row id") != index:
            raise PrerequisiteError("submission row IDs are not canonical")
        if row["dataset"] not in profile.datasets:
            raise PrerequisiteError("submission dataset drift")
        if row["dataset"] not in seen_order:
            seen_order.append(row["dataset"])
    if tuple(seen_order) != profile.datasets:
        raise PrerequisiteError("submission dataset order drift")
    exact: dict[str, object] = {}
    legacy: dict[str, object] = {}
    counts: list[tuple[str, int, int, int, int]] = []
    for dataset in profile.datasets:
        selected = [row for row in rows if row["dataset"] == dataset]
        node_rows = [row for row in selected if row["row_type"] == "node"]
        edge_rows = [row for row in selected if row["row_type"] == "edge"]
        if len(node_rows) + len(edge_rows) != len(selected):
            raise PrerequisiteError("unknown submission row type")
        node_map: dict[int, int] = {}
        exact_nodes: list[tuple[int, int, float, float, float]] = []
        legacy_nodes: list[tuple[int, int, float, float, float]] = []
        times: dict[int, int] = {}
        for assigned, row in enumerate(node_rows):
            node_id = _integer(row["node_id"], "node_id")
            if node_id in node_map:
                raise PrerequisiteError("duplicate node ID")
            values = tuple(float(row[key]) for key in ("z", "y", "x"))
            if not all(math.isfinite(value) for value in values):
                raise PrerequisiteError("non-finite node coordinate")
            t = _integer(row["t"], "node time")
            node_map[node_id] = assigned
            times[node_id] = t
            exact_nodes.append((node_id, t, *values))
            legacy_nodes.append((assigned, t, *values))
        exact_edges: list[tuple[int, int, int]] = []
        legacy_edges: list[tuple[int, int, int]] = []
        pairs: set[tuple[int, int]] = set()
        sources: Counter[int] = Counter()
        for assigned, row in enumerate(edge_rows):
            row_id = _integer(row["id"], "edge row id")
            source = _integer(row["source_id"], "source_id")
            target = _integer(row["target_id"], "target_id")
            if source not in node_map or target not in node_map or (source, target) in pairs:
                raise PrerequisiteError("dangling or duplicate directed edge")
            if times[target] != times[source] + 1:
                raise PrerequisiteError("nonconsecutive directed edge")
            pairs.add((source, target))
            sources[source] += 1
            exact_edges.append((row_id, source, target))
            legacy_edges.append((assigned, node_map[source], node_map[target]))
        forks = sum(value >= 2 for value in sources.values())
        counts.append((dataset, len(selected), len(exact_nodes), len(exact_edges), forks))
        exact[dataset] = {"nodes": exact_nodes, "edges": exact_edges}
        legacy[dataset] = {"nodes": legacy_nodes, "edges": legacy_edges}
    if profile.graph_counts and tuple(counts) != profile.graph_counts:
        raise PrerequisiteError("typed graph counts/forks drift")
    exact_digest = hashlib.sha256(json.dumps(exact, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    legacy_digest = _legacy_parity_graph_digest(legacy)
    if profile.exact_graph_sha256 is not None and exact_digest != profile.exact_graph_sha256:
        raise PrerequisiteError("exact typed graph digest drift")
    if profile.graph_sha256 is not None and legacy_digest != profile.graph_sha256:
        raise PrerequisiteError("typed graph digest drift")
    return {
        "exact_typed_sha256": exact_digest,
        "legacy_parity_sha256": legacy_digest,
        "counts": [list(item) for item in counts],
    }


def _stats_evidence(candidate: bytes, reference: bytes, profile: Profile) -> dict[str, object]:
    ref_header, ref_rows = _parse_csv(reference, "reference telemetry")
    got_header, got_rows = _parse_csv(candidate, "candidate telemetry")
    if len(ref_rows) != len(got_rows) or len(got_rows) != len(profile.datasets):
        raise PrerequisiteError("telemetry row count drift")
    ref_by = {row.get("dataset"): row for row in ref_rows}
    got_by = {row.get("dataset"): row for row in got_rows}
    if set(ref_by) != set(profile.datasets) or set(got_by) != set(profile.datasets):
        raise PrerequisiteError("telemetry dataset set drift")
    runtime = {"predict_minutes_total", "experiment_tag"}
    if profile.kind == "e23":
        centroid = {
            "centroid_refine_examined",
            "centroid_refine_moved",
            "centroid_refine_no_signal",
            "centroid_refine_rejected_shift",
        }
        structural = {
            "deepcenter_gap_bypassed_observed_node",
            "safe_division_geometric_candidates",
            "safe_division_mutual_nn_rejected",
            "safe_division_divergence_rejected",
        }
        exclusions = runtime | {
            "safe_division_geometric_candidates",
            "safe_division_mutual_nn_rejected",
            "safe_division_divergence_rejected",
        }
        required = set(ref_header) - exclusions
        new_required = centroid | structural
        new_zero: set[str] = set()
    else:
        exclusions = runtime | {"deepcenter_gap_bypassed_synthetic_node"}
        required = set(ref_header) - exclusions
        new_required = set()
        new_zero = {
            "centroid_refine_examined",
            "centroid_refine_moved",
            "centroid_refine_no_signal",
            "centroid_refine_rejected_shift",
            "deepcenter_gap_bypassed_observed_node",
            "safe_division_geometric_candidates",
            "safe_division_mutual_nn_rejected",
            "safe_division_divergence_rejected",
        }
    if (
        not required <= set(got_header)
        or not new_required <= set(got_header)
        or not set(profile.steal_fields) <= set(got_header)
        or not new_zero <= set(got_header)
    ):
        raise PrerequisiteError("telemetry required fields missing")
    allowed = set(ref_header) | set(profile.steal_fields) | new_zero | new_required
    if set(got_header) - allowed:
        raise PrerequisiteError("unknown telemetry fields")
    for dataset in profile.datasets:
        for field in required:
            if got_by[dataset][field] != ref_by[dataset][field]:
                raise PrerequisiteError(f"common telemetry drift: {dataset}/{field}")
        for field in (*profile.steal_fields, *new_zero):
            if _integer(got_by[dataset][field], field) != 0:
                raise PrerequisiteError(f"nonzero disabled telemetry: {dataset}/{field}")
        if profile.kind == "e23":
            for field in (
                "safe_division_candidates",
                "safe_divisions_added",
                "safe_division_skipped_cap",
                "safe_division_geometric_candidates",
                "safe_division_mutual_nn_rejected",
                "safe_division_divergence_rejected",
            ):
                _integer(got_by[dataset][field], field)
            raw = _integer(ref_by[dataset]["raw_nodes"], "raw_nodes")
            if (
                _integer(got_by[dataset]["centroid_refine_examined"], "centroid_refine_examined") != raw
                or _integer(got_by[dataset]["centroid_refine_moved"], "centroid_refine_moved") != raw
                or _integer(got_by[dataset]["centroid_refine_no_signal"], "centroid_refine_no_signal") != 0
                or _integer(got_by[dataset]["centroid_refine_rejected_shift"], "centroid_refine_rejected_shift") != 0
            ):
                raise PrerequisiteError("untruthful centroid telemetry")
    common = {dataset: {field: got_by[dataset][field] for field in sorted(required)} for dataset in profile.datasets}
    return {
        "rows": len(got_rows),
        "common_sha256": hashlib.sha256(canonical_json(common)).hexdigest(),
        "zero_fields": sorted(set(profile.steal_fields) | new_zero),
    }


def _check_log(raw: bytes, kind: str) -> dict[str, object]:
    if not raw or len(raw) > _MAX_LOG:
        raise PrerequisiteError("postprocessor log is empty or oversized")
    try:
        text = raw.decode()
    except UnicodeDecodeError as error:
        raise PrerequisiteError("postprocessor log is not UTF-8") from error
    forbidden = (
        "No usable DeepCenter checkpoint",
        "Could not read DeepCenter manifest",
        "Skipping incompatible DeepCenter checkpoint",
        "DeepCenter add-only repair gate skipped because torch is unavailable",
        "DeepCenter add-only repair gate disabled by configuration",
        "missing DeepCenter checkpoint",
        "Traceback (most recent call last)",
    )
    if any(item.lower() in text.lower() for item in forbidden):
        raise PrerequisiteError(f"forbidden warning/error in {kind} log")
    if re.search(r"(?i)\b(warning|error|critical)\b", text):
        raise PrerequisiteError(f"warning/error line in {kind} log")
    if re.search(
        r"(?i)(api[_-]?key|authorization|password|secret(?:[_-][a-z0-9]+)*|(?:[a-z0-9]+[_-])*token|aws[_-]access[_-]key[_-]id)\s*[:=]",
        text,
    ):
        raise PrerequisiteError("possible secret in postprocessor log")
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "scan": "PASS"}


def _artifact_raw(repo_root: Path, run_dir: Path, name: str, *, limit: int | None = None) -> bytes:
    relative = (run_dir / name).relative_to(repo_root).as_posix()
    return _read_repo(repo_root, relative, limit=limit)


def _artifact_evidence(name: str, raw: bytes) -> dict[str, object]:
    return {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _prepared_membership(repo_root: Path, run_dir: Path, profile: Profile) -> None:
    relative = run_dir.relative_to(repo_root).as_posix()
    fd = _open_repo_dir(repo_root, relative)
    try:
        expected = {"RUN_SPEC.json"}
        if profile.kind == "base1":
            expected.add("EMPTY_IMAGE_VIEW")
        names = set(os.listdir(fd))
        _reject_casefold_collisions(tuple(names), relative)
        if names != expected:
            raise PrerequisiteError("prepared run artifact membership drift")
        for name in names:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if name == "EMPTY_IMAGE_VIEW":
                if not stat.S_ISDIR(info.st_mode):
                    raise PrerequisiteError("unsafe EMPTY_IMAGE_VIEW")
                child = _open_relative_dir(fd, (name,), name)
                try:
                    if os.listdir(child):
                        raise PrerequisiteError("base1 EMPTY_IMAGE_VIEW is nonempty")
                finally:
                    os.close(child)
            elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise PrerequisiteError(f"unsafe prepared artifact: {name}")
    finally:
        os.close(fd)


def _create_exclusive_file(run_dir: Path, name: str, raw: bytes | None) -> int | None:
    directory_fd = _open_dir(run_dir)
    out: int | None = None
    owned = False
    owner: tuple[int, int] | None = None
    try:
        out = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o444,
            dir_fd=directory_fd,
        )
        owned = True
        opened = os.fstat(out)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise PrerequisiteError(f"unsafe exclusive artifact: {name}")
        owner = (opened.st_dev, opened.st_ino)
        if raw is not None:
            view = memoryview(raw)
            while view:
                written = os.write(out, view)
                if written <= 0:
                    raise PrerequisiteError(f"short exclusive artifact write: {name}")
                view = view[written:]
            os.fsync(out)
            os.close(out)
            out = None
            os.fsync(directory_fd)
            return None
        return out
    except BaseException as error:
        problems: list[str] = []
        if out is not None:
            with contextlib.suppress(OSError):
                os.close(out)
        if owned:
            try:
                current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if owner != (current.st_dev, current.st_ino):
                    problems.append("exclusive artifact ownership changed")
                else:
                    os.unlink(name, dir_fd=directory_fd)
            except OSError as cleanup:
                problems.append(f"exclusive artifact unlink: {cleanup}")
            try:
                os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                problems.append("exclusive artifact remains after rollback")
            try:
                os.fsync(directory_fd)
            except OSError as cleanup:
                problems.append(f"exclusive artifact rollback fsync: {cleanup}")
        if problems:
            raise PublicationAmbiguityError("; ".join(problems)) from error
        raise
    finally:
        os.close(directory_fd)


def _fsync_run_artifacts(repo_root: Path, run_dir: Path, names: list[str]) -> None:
    relative = run_dir.relative_to(repo_root).as_posix()
    directory_fd = _open_repo_dir(repo_root, relative)
    try:
        for name in names:
            fd = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
                dir_fd=directory_fd,
            )
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise PrerequisiteError(f"unsafe execution artifact: {name}")
                os.fsync(fd)
            finally:
                os.close(fd)
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _execution_artifacts(repo_root: Path, run_dir: Path, profile: Profile) -> dict[str, object]:
    names = ["START_MARKER.txt", "postproc.log", "submission.csv", "run_stats.csv"]
    if profile.kind == "e23":
        names.append("official_score.json")
    evidence: dict[str, object] = {}
    for name in names:
        limit = _MAX_LOG if name == "postproc.log" else 128 * 1024 * 1024
        raw = _artifact_raw(repo_root, run_dir, name, limit=limit)
        if name == "postproc.log":
            _check_log(raw, profile.kind)
        evidence[name] = _artifact_evidence(name, raw)
    return evidence


def _execution_pass_membership(repo_root: Path, run_dir: Path, profile: Profile) -> None:
    expected = {"RUN_SPEC.json", "START_MARKER.txt", "postproc.log", "submission.csv", "run_stats.csv"}
    if profile.kind == "base1":
        expected.add("EMPTY_IMAGE_VIEW")
    else:
        expected.add("official_score.json")
    directory_fd = _open_repo_dir(repo_root, run_dir.relative_to(repo_root).as_posix())
    try:
        names = set(os.listdir(directory_fd))
        _reject_casefold_collisions(tuple(names), run_dir.name)
        if names != expected:
            raise PrerequisiteError("execution artifact membership drift")
    finally:
        os.close(directory_fd)


def _available_execution_artifacts(repo_root: Path, run_dir: Path, profile: Profile) -> dict[str, object]:
    names = ["START_MARKER.txt", "postproc.log", "submission.csv", "run_stats.csv"]
    if profile.kind == "e23":
        names.append("official_score.json")
    evidence: dict[str, object] = {}
    directory_fd = _open_repo_dir(repo_root, run_dir.relative_to(repo_root).as_posix())
    try:
        present = set(os.listdir(directory_fd))
    finally:
        os.close(directory_fd)
    for name in names:
        if name in present:
            raw = _artifact_raw(repo_root, run_dir, name, limit=128 * 1024 * 1024)
            evidence[name] = _artifact_evidence(name, raw)
    return evidence


def _process_record(
    process: subprocess.Popen[bytes],
    argv: list[str],
    phase: str,
    environment: dict[str, str],
    started: str,
    ended: str,
    *,
    interruption: dict[str, object] | None,
) -> dict[str, object]:
    return_code = process.returncode
    return {
        "phase": phase,
        "argv": argv,
        "cwd": ".",
        "environment": environment,
        "started_utc": started,
        "ended_utc": ended,
        "pid": process.pid,
        "process_group": process.pid,
        "exit_code": return_code if return_code is not None and return_code >= 0 else None,
        "termination_signal": -return_code if return_code is not None and return_code < 0 else None,
        "interruption": interruption,
    }


def _group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Darwin can report EPERM for an unreaped, already-dead group leader.
        return True
    return True


def _bounded_group_shutdown(process: subprocess.Popen[bytes], exception_name: str) -> dict[str, object]:
    """Stop the isolated child process group before returning interruption evidence."""

    process_group = process.pid
    term_sent = False
    kill_sent = False
    cleanup_errors: list[str] = []
    try:
        os.killpg(process_group, signal.SIGTERM)
        term_sent = True
    except ProcessLookupError:
        pass
    except OSError as error:
        cleanup_errors.append(f"SIGTERM:{error.errno}")

    deadline = time.monotonic() + _TERM_GRACE_SECONDS
    while time.monotonic() < deadline:
        process.poll()
        if not _group_exists(process_group):
            break
        time.sleep(0.01)
    if _group_exists(process_group):
        try:
            os.killpg(process_group, signal.SIGKILL)
            kill_sent = True
        except ProcessLookupError:
            pass
        except OSError as error:
            cleanup_errors.append(f"SIGKILL:{error.errno}")

    deadline = time.monotonic() + _KILL_GRACE_SECONDS
    while time.monotonic() < deadline:
        process.poll()
        if not _group_exists(process_group):
            break
        time.sleep(0.01)
    if process.poll() is None:
        cleanup_errors.append("leader-not-reaped-after-SIGKILL")
    group_remaining = _group_exists(process_group)
    if group_remaining:
        cleanup_errors.append("process-group-still-present")
    return {
        "exception": exception_name,
        "sigterm_sent": term_sent,
        "sigkill_sent": kill_sent,
        "group_remaining_after_shutdown": group_remaining,
        "cleanup_errors": cleanup_errors,
    }


def _run_child(
    argv: list[str], repo_root: Path, log_fd: int, phase: str, environment: dict[str, str]
) -> dict[str, object]:
    started = _now()
    process = subprocess.Popen(
        argv,
        cwd=repo_root,
        env={},
        stdin=subprocess.DEVNULL,
        stdout=log_fd,
        stderr=subprocess.STDOUT,
        close_fds=True,
        start_new_session=True,
    )
    try:
        process.wait()
    except BaseException as error:
        interruption = _bounded_group_shutdown(process, type(error).__name__[:80])
        ended = _now()
        record = _process_record(
            process,
            argv,
            phase,
            environment,
            started,
            ended,
            interruption=interruption,
        )
        if interruption["group_remaining_after_shutdown"] or interruption["cleanup_errors"]:
            raise PublicationAmbiguityError("process-group shutdown could not prove absence") from error
        raise _ChildInterrupted(record) from error
    ended = _now()
    return _process_record(process, argv, phase, environment, started, ended, interruption=None)


def _execute(
    kind: str,
    run_dir: Path,
    repo_root: Path,
    *,
    profile: Profile,
    _test_only: bool = False,
) -> dict[str, object]:
    if profile.test_only != _test_only or profile.kind != kind:
        raise PrerequisiteError("private test profile authorization mismatch")
    run = _validate_run_path(repo_root, run_dir, profile)
    spec, spec_raw = _load_spec(repo_root, run)
    source = _source_snapshot(repo_root, profile)
    if spec != _run_spec(profile, repo_root, run, str(spec.get("created_utc")), source):
        raise PrerequisiteError("RUN_SPEC/source drift before execution")
    _prepared_membership(repo_root, run, profile)
    started = _now()
    marker = f"code_sha={source['commit']}\nstarted_utc={started}\n".encode()
    _create_exclusive_file(run, "START_MARKER.txt", marker)
    log_fd = _create_exclusive_file(run, "postproc.log", None)
    assert log_fd is not None
    commands: list[dict[str, object]] = []
    failure: dict[str, object] | None = None
    try:
        postproc = _run_child(
            list(spec["command"]["postproc_argv"]),  # type: ignore[index]
            repo_root,
            log_fd,
            "postproc",
            dict(spec["command"]["environment"]),  # type: ignore[index]
        )
        commands.append(postproc)
        if postproc["exit_code"] != 0:
            failure = {"phase": "postproc", "reason": "NONZERO_EXIT"}
        elif spec["command"]["score_argv"]:  # type: ignore[index]
            score = _run_child(
                list(spec["command"]["score_argv"]),  # type: ignore[index]
                repo_root,
                log_fd,
                "score",
                dict(spec["command"]["environment"]),  # type: ignore[index]
            )
            commands.append(score)
            if score["exit_code"] != 0:
                failure = {"phase": "score", "reason": "NONZERO_EXIT"}
    except PublicationAmbiguityError:
        raise
    except _ChildInterrupted as error:
        commands.append(error.record)
        failure = {
            "phase": str(error.record["phase"]),
            "reason": "INTERRUPTED",
            "exception": str(error.record["interruption"]["exception"]),  # type: ignore[index]
        }
    except BaseException as error:
        failure = {"phase": "launcher", "reason": type(error).__name__[:80]}
    finally:
        try:
            os.fsync(log_fd)
        finally:
            os.close(log_fd)
    artifacts: dict[str, object] = {}
    if failure is None:
        try:
            artifacts = _execution_artifacts(repo_root, run, profile)
            _execution_pass_membership(repo_root, run, profile)
            _fsync_run_artifacts(repo_root, run, list(artifacts))
        except Exception as error:
            failure = {"phase": "evidence", "reason": type(error).__name__[:80]}
    if failure is not None:
        try:
            artifacts = _available_execution_artifacts(repo_root, run, profile)
            _fsync_run_artifacts(repo_root, run, list(artifacts))
        except Exception as error:
            failure = {"phase": "failure_evidence", "reason": type(error).__name__[:80]}
    ended = _now()
    receipt = {
        "schema_version": EXECUTION_SCHEMA,
        "status": "PASS" if failure is None else "FAIL",
        "kind": kind,
        "created_utc": ended,
        "source": source,
        "run_spec": _artifact_evidence("RUN_SPEC.json", spec_raw),
        "command": spec["command"],
        "started_utc": started,
        "ended_utc": ended,
        "commands": commands,
        "artifacts": artifacts,
        "failure": failure,
    }
    raw = canonical_json(receipt)
    result = {
        "status": receipt["status"],
        "execution_receipt": EXECUTION_NAME,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    _publish(run, EXECUTION_NAME, raw)
    return result


def execute(kind: str, run_dir: Path, repo_root: Path) -> dict[str, object]:
    return _execute(kind, run_dir, repo_root, profile=_profile(kind))


def _parse_utc(value: object, label: str) -> dt.datetime:
    if type(value) is not str or _UTC.fullmatch(value) is None:
        raise PrerequisiteError(f"invalid {label} timestamp")
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
    except ValueError as error:
        raise PrerequisiteError(f"invalid {label} timestamp") from error


def _validate_execution_receipt(
    repo_root: Path,
    run_dir: Path,
    profile: Profile,
    spec: dict[str, object],
    source: dict[str, object],
) -> dict[str, object]:
    raw = _artifact_raw(repo_root, run_dir, EXECUTION_NAME, limit=_MAX_JSON)
    value = strict_json(raw)
    if not isinstance(value, dict) or canonical_json(value) != raw:
        raise PrerequisiteError("execution receipt is not canonical JSON")
    keys = {
        "schema_version",
        "status",
        "kind",
        "created_utc",
        "source",
        "run_spec",
        "command",
        "started_utc",
        "ended_utc",
        "commands",
        "artifacts",
        "failure",
    }
    if (
        set(value) != keys
        or value["schema_version"] != EXECUTION_SCHEMA
        or value["status"] != "PASS"
        or value["failure"] is not None
        or value["kind"] != profile.kind
        or value["source"] != source
        or value["command"] != spec["command"]
    ):
        raise PrerequisiteError("execution receipt schema/source/verdict drift")
    spec_raw = _artifact_raw(repo_root, run_dir, "RUN_SPEC.json", limit=_MAX_JSON)
    if value["run_spec"] != _artifact_evidence("RUN_SPEC.json", spec_raw):
        raise PrerequisiteError("execution receipt RUN_SPEC binding drift")
    started = _parse_utc(value["started_utc"], "execution start")
    ended = _parse_utc(value["ended_utc"], "execution end")
    created = _parse_utc(value["created_utc"], "execution receipt")
    if not _parse_utc(spec["created_utc"], "prepare") <= started <= ended or created != ended:
        raise PrerequisiteError("execution receipt chronology drift")
    expected_phases = [("postproc", spec["command"]["postproc_argv"])]  # type: ignore[index]
    if spec["command"]["score_argv"]:  # type: ignore[index]
        expected_phases.append(("score", spec["command"]["score_argv"]))  # type: ignore[index]
    commands = value["commands"]
    if not isinstance(commands, list) or len(commands) != len(expected_phases):
        raise PrerequisiteError("execution command count drift")
    previous = started
    command_keys = {
        "phase",
        "argv",
        "cwd",
        "environment",
        "started_utc",
        "ended_utc",
        "pid",
        "process_group",
        "exit_code",
        "termination_signal",
        "interruption",
    }
    for record, (phase, argv) in zip(commands, expected_phases, strict=True):
        if not isinstance(record, dict) or set(record) != command_keys:
            raise PrerequisiteError("execution command schema drift")
        command_started = _parse_utc(record["started_utc"], f"{phase} start")
        command_ended = _parse_utc(record["ended_utc"], f"{phase} end")
        if (
            record["phase"] != phase
            or record["argv"] != argv
            or record["cwd"] != "."
            or record["environment"] != spec["command"]["environment"]  # type: ignore[index]
            or type(record["pid"]) is not int
            or record["pid"] <= 0
            or record["process_group"] != record["pid"]
            or type(record["exit_code"]) is not int
            or record["exit_code"] != 0
            or record["termination_signal"] is not None
            or record["interruption"] is not None
            or not previous <= command_started <= command_ended <= ended
        ):
            raise PrerequisiteError("execution command evidence drift")
        previous = command_ended
    expected_artifacts = _execution_artifacts(repo_root, run_dir, profile)
    if value["artifacts"] != expected_artifacts:
        raise PrerequisiteError("execution artifact evidence drift")
    marker = _artifact_raw(repo_root, run_dir, "START_MARKER.txt", limit=1024)
    expected_marker = f"code_sha={source['commit']}\nstarted_utc={value['started_utc']}\n".encode()
    if marker != expected_marker:
        raise PrerequisiteError("execution marker binding drift")
    return _artifact_evidence(EXECUTION_NAME, raw)


def _validate_run_membership(repo_root: Path, run_dir: Path, profile: Profile) -> None:
    relative = run_dir.relative_to(repo_root).as_posix()
    fd = _open_repo_dir(repo_root, relative)
    try:
        expected_files = {
            "RUN_SPEC.json",
            EXECUTION_NAME,
            "START_MARKER.txt",
            "postproc.log",
            "run_stats.csv",
            "submission.csv",
        }
        if profile.kind == "e23":
            expected_files.add("official_score.json")
        allowed = expected_files | {profile.receipt_name}
        if profile.kind == "base1":
            allowed.add("EMPTY_IMAGE_VIEW")
        names = set(os.listdir(fd))
        _reject_casefold_collisions(tuple(names), relative)
        if not expected_files <= names or names - allowed:
            raise PrerequisiteError("run artifact membership drift")
        for name in names:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if name == "EMPTY_IMAGE_VIEW":
                if not stat.S_ISDIR(info.st_mode):
                    raise PrerequisiteError("unsafe EMPTY_IMAGE_VIEW")
                child = _open_relative_dir(fd, (name,), name)
                try:
                    if os.listdir(child):
                        raise PrerequisiteError("base1 EMPTY_IMAGE_VIEW is nonempty")
                finally:
                    os.close(child)
            elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise PrerequisiteError(f"unsafe run artifact: {name}")
    finally:
        os.close(fd)


def _evaluate(
    profile: Profile, repo_root: Path, run_dir: Path, spec: dict[str, object], created: str
) -> dict[str, object]:
    source = _source_snapshot(repo_root, profile)
    if source != spec["source"]:
        raise PrerequisiteError("source snapshot drift since prepare")
    expected_spec = _run_spec(profile, repo_root, run_dir, str(spec["created_utc"]), source)
    if spec != expected_spec:
        raise PrerequisiteError("RUN_SPEC drift")
    _validate_run_membership(repo_root, run_dir, profile)
    execution_receipt = _validate_execution_receipt(repo_root, run_dir, profile, spec, source)

    raw_tree = _tree_evidence(repo_root, profile.raw)
    image_tree = (
        _tree_evidence(repo_root, profile.images)
        if profile.images is not None
        else {
            "path": f"{run_dir.relative_to(repo_root).as_posix()}/EMPTY_IMAGE_VIEW",
            "roots": [],
            "files": 0,
            "bytes": 0,
            "sha256": _tree_digest([]),
            "root_sha256": [],
            "symlink_target_parent": None,
            "records": [],
        }
    )
    gt = [_single_root_evidence(repo_root, pin) for pin in profile.gt_roots]
    references = [_file_evidence(repo_root, pin) for pin in profile.references]
    reference_submission_raw = _read_repo(repo_root, profile.reference_submission.path)
    reference_submission = _raw_file_evidence(profile.reference_submission, reference_submission_raw)
    reference_stats_raw = _read_repo(repo_root, profile.reference_stats.path)
    reference_stats = _raw_file_evidence(
        profile.reference_stats, reference_stats_raw, require_pin=bool(profile.reference_stats.sha256)
    )

    marker = _artifact_raw(repo_root, run_dir, "START_MARKER.txt", limit=1024)
    expected_marker_prefix = f"code_sha={source['commit']}\nstarted_utc="
    try:
        marker_text = marker.decode()
    except UnicodeDecodeError as error:
        raise PrerequisiteError("invalid START_MARKER encoding") from error
    if not marker_text.startswith(expected_marker_prefix) or not marker_text.endswith("\n"):
        raise PrerequisiteError("START_MARKER source binding drift")
    started = marker_text[len(expected_marker_prefix) : -1]
    if _UTC.fullmatch(started) is None:
        raise PrerequisiteError("START_MARKER timestamp drift")
    try:
        prepared_at = dt.datetime.strptime(str(spec["created_utc"]), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
        started_at = dt.datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
        sealed_at = dt.datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
    except ValueError as error:
        raise PrerequisiteError("invalid prerequisite chronology") from error
    if not prepared_at <= started_at <= sealed_at:
        raise PrerequisiteError("prerequisite chronology drift")

    submission_raw = _artifact_raw(repo_root, run_dir, "submission.csv", limit=128 * 1024 * 1024)
    if (
        submission_raw != reference_submission_raw
        or hashlib.sha256(submission_raw).hexdigest() != profile.submission_sha256
    ):
        raise PrerequisiteError("submission bytes/hash differ from reference")
    graph = _graph_evidence(submission_raw, profile)
    reference_graph = _graph_evidence(reference_submission_raw, profile)
    if graph != reference_graph:
        raise PrerequisiteError("typed graph differs from reference")

    stats_raw = _artifact_raw(repo_root, run_dir, "run_stats.csv", limit=4 * 1024 * 1024)
    telemetry = _stats_evidence(stats_raw, reference_stats_raw, profile)
    log_raw = _artifact_raw(repo_root, run_dir, "postproc.log", limit=_MAX_LOG)
    log = _check_log(log_raw, profile.kind)
    outputs: dict[str, object] = {
        "start_marker": {
            "path": "START_MARKER.txt",
            "bytes": len(marker),
            "sha256": hashlib.sha256(marker).hexdigest(),
        },
        "submission": {
            "path": "submission.csv",
            "bytes": len(submission_raw),
            "sha256": hashlib.sha256(submission_raw).hexdigest(),
        },
        "run_stats": {
            "path": "run_stats.csv",
            "bytes": len(stats_raw),
            "sha256": hashlib.sha256(stats_raw).hexdigest(),
        },
        "postproc_log": {"path": "postproc.log", **log},
    }
    reference_values: dict[str, object] = {
        "submission": reference_submission,
        "run_stats": reference_stats,
        "fixed_files": references,
        "execution_receipt": execution_receipt,
    }
    if profile.reference_score is not None:
        score_raw = _artifact_raw(repo_root, run_dir, "official_score.json", limit=_MAX_JSON)
        reference_score_raw = _read_repo(repo_root, profile.reference_score.path, limit=_MAX_JSON)
        if score_raw != reference_score_raw:
            raise PrerequisiteError("official score bytes differ from reference")
        strict_json(score_raw)
        score_ref = _raw_file_evidence(profile.reference_score, reference_score_raw)
        outputs["official_score"] = {
            "path": "official_score.json",
            "bytes": len(score_raw),
            "sha256": hashlib.sha256(score_raw).hexdigest(),
        }
        reference_values["official_score"] = score_ref

    run_spec_raw = _artifact_raw(repo_root, run_dir, "RUN_SPEC.json", limit=_MAX_JSON)
    _validate_run_membership(repo_root, run_dir, profile)
    return {
        "schema_version": profile.receipt_schema,
        "status": "PASS",
        "kind": profile.kind,
        "created_utc": created,
        "source": source,
        "run_spec": {
            "path": "RUN_SPEC.json",
            "bytes": len(run_spec_raw),
            "sha256": hashlib.sha256(run_spec_raw).hexdigest(),
        },
        "command": spec["command"],
        "inputs": {"raw": raw_tree, "images": image_tree, "gt": gt},
        "references": reference_values,
        "outputs": outputs,
        "checks": {"graph": graph, "telemetry": telemetry},
    }


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _profile(kind: str) -> Profile:
    try:
        return PROFILES[kind]
    except KeyError as error:
        raise PrerequisiteError(f"unknown prerequisite kind: {kind}") from error


def _validate_run_path(repo_root: Path, run_dir: Path, profile: Profile) -> Path:
    repo = Path(os.path.abspath(repo_root))
    run = Path(os.path.abspath(run_dir))
    parent = repo / profile.run_parent
    valid_name = _RUN_NAME.fullmatch(run.name) is not None
    if valid_name:
        try:
            dt.datetime.strptime(run.name.split("_", 1)[0], "%Y%m%dT%H%M%SZ")
        except ValueError:
            valid_name = False
    if ".." in run_dir.parts or run.parent != parent or not valid_name:
        raise PrerequisiteError(f"run directory must be one direct child of {profile.run_parent}")
    return run


def _rename_noreplace(source: str, destination: str, directory_fd: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function = libc.renameatx_np
        flag = 4
    elif sys.platform.startswith("linux"):
        function = libc.renameat2
        flag = 1
    else:  # pragma: no cover
        raise PrerequisiteError("atomic no-replace rename unsupported")
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    if function(directory_fd, os.fsencode(source), directory_fd, os.fsencode(destination), flag):
        number = ctypes.get_errno()
        raise (
            FileExistsError(number, os.strerror(number), destination)
            if number == errno.EEXIST
            else OSError(number, os.strerror(number), destination)
        )


def _publish(directory: Path, name: str, raw: bytes) -> None:
    fd = _open_dir(directory)
    temp = f".{name}.{os.getpid()}.tmp"
    temp_owned = False
    published = False
    owner: tuple[int, int] | None = None
    try:
        try:
            os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), name)
        out = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o444, dir_fd=fd)
        temp_owned = True
        try:
            opened = os.fstat(out)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise PrerequisiteError("unsafe temporary receipt")
            owner = (opened.st_dev, opened.st_ino)
            view = memoryview(raw)
            while view:
                written = os.write(out, view)
                if written <= 0:
                    raise PrerequisiteError("short receipt write")
                view = view[written:]
            os.fsync(out)
        finally:
            os.close(out)
        check = _read_at(fd, temp, temp)
        if check != raw:
            raise PrerequisiteError("temporary receipt reread mismatch")
        _rename_noreplace(temp, name, fd)
        temp_owned = False
        published = True
        os.fsync(fd)  # final receipt commit point
    except BaseException as error:
        problems: list[str] = []
        if published:
            try:
                current = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if owner != (current.st_dev, current.st_ino):
                    problems.append("published receipt ownership changed")
                else:
                    os.unlink(name, dir_fd=fd)
            except OSError as cleanup:
                problems.append(f"published unlink: {cleanup}")
        elif temp_owned:
            try:
                current = os.stat(temp, dir_fd=fd, follow_symlinks=False)
                if owner != (current.st_dev, current.st_ino):
                    problems.append("temporary receipt ownership changed")
                else:
                    os.unlink(temp, dir_fd=fd)
            except OSError as cleanup:
                problems.append(f"temporary unlink: {cleanup}")
        if published or temp_owned:
            target = name if published else temp
            try:
                os.stat(target, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                problems.append(f"owned path remains after rollback: {target}")
            try:
                os.fsync(fd)
            except OSError as cleanup:
                problems.append(f"rollback fsync: {cleanup}")
        if problems:
            raise PublicationAmbiguityError("; ".join(problems)) from error
        raise
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)


def _prepare(
    kind: str,
    run_dir: Path,
    repo_root: Path,
    *,
    profile: Profile,
    _test_only: bool = False,
) -> dict[str, object]:
    if profile.test_only != _test_only or profile.kind != kind:
        raise PrerequisiteError("private test profile authorization mismatch")
    run = _validate_run_path(repo_root, run_dir, profile)
    _ensure_repo_directory(repo_root, profile.run_parent)
    created = False
    try:
        parent_fd = _open_dir(run.parent)
        try:
            os.mkdir(run.name, 0o755, dir_fd=parent_fd)
            created = True
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        if profile.kind == "base1":
            run_fd = _open_dir(run)
            try:
                os.mkdir("EMPTY_IMAGE_VIEW", 0o755, dir_fd=run_fd)
                empty_fd = _open_relative_dir(run_fd, ("EMPTY_IMAGE_VIEW",), "EMPTY_IMAGE_VIEW")
                try:
                    if os.listdir(empty_fd):
                        raise PrerequisiteError("new EMPTY_IMAGE_VIEW is not empty")
                    os.fsync(empty_fd)
                finally:
                    os.close(empty_fd)
                os.fsync(run_fd)
            finally:
                os.close(run_fd)
        source = _source_snapshot(repo_root, profile)
        spec = _run_spec(profile, repo_root, run, _now(), source)
        raw = canonical_json(spec)
        result = {
            "status": "PREPARED",
            "run_spec": "RUN_SPEC.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        _publish(run, "RUN_SPEC.json", raw)
        return result
    except BaseException as error:
        if not created:
            raise
        problems: list[str] = []
        try:
            parent_fd = _open_dir(run.parent)
        except Exception as cleanup:
            problems.append(f"fresh run parent reopen: {cleanup}")
        else:
            try:
                if profile.kind == "base1":
                    try:
                        run_fd = _open_relative_dir(parent_fd, (run.name,), run.name)
                        try:
                            empty_fd = _open_relative_dir(run_fd, ("EMPTY_IMAGE_VIEW",), "EMPTY_IMAGE_VIEW")
                            try:
                                if os.listdir(empty_fd):
                                    raise PrerequisiteError("owned EMPTY_IMAGE_VIEW became nonempty")
                            finally:
                                os.close(empty_fd)
                            os.rmdir("EMPTY_IMAGE_VIEW", dir_fd=run_fd)
                            os.fsync(run_fd)
                        finally:
                            os.close(run_fd)
                    except Exception as cleanup:
                        problems.append(f"EMPTY_IMAGE_VIEW rollback: {cleanup}")
                try:
                    os.rmdir(run.name, dir_fd=parent_fd)
                except OSError as cleanup:
                    problems.append(f"fresh run removal: {cleanup}")
                try:
                    os.fsync(parent_fd)
                except OSError as cleanup:
                    problems.append(f"fresh run rollback fsync: {cleanup}")
            finally:
                os.close(parent_fd)
        if problems:
            raise PublicationAmbiguityError("; ".join(problems)) from error
        raise
    raise AssertionError("unreachable prepare state")


def prepare(kind: str, run_dir: Path, repo_root: Path) -> dict[str, object]:
    return _prepare(kind, run_dir, repo_root, profile=_profile(kind))


def _load_spec(repo_root: Path, run: Path) -> tuple[dict[str, object], bytes]:
    raw = _artifact_raw(repo_root, run, "RUN_SPEC.json", limit=_MAX_JSON)
    value = strict_json(raw)
    if not isinstance(value, dict) or canonical_json(value) != raw:
        raise PrerequisiteError("RUN_SPEC is not canonical JSON")
    return value, raw


def _seal(
    kind: str,
    run_dir: Path,
    repo_root: Path,
    *,
    profile: Profile,
    _test_only: bool = False,
) -> dict[str, object]:
    if profile.test_only != _test_only or profile.kind != kind:
        raise PrerequisiteError("private test profile authorization mismatch")
    run = _validate_run_path(repo_root, run_dir, profile)
    spec, _ = _load_spec(repo_root, run)
    receipt = _evaluate(profile, repo_root, run, spec, _now())
    raw = canonical_json(receipt)
    result = {"status": "PASS", "receipt": profile.receipt_name, "sha256": hashlib.sha256(raw).hexdigest()}
    _publish(run, profile.receipt_name, raw)
    return result


def seal(kind: str, run_dir: Path, repo_root: Path) -> dict[str, object]:
    return _seal(kind, run_dir, repo_root, profile=_profile(kind))


def _validate(
    path: Path,
    expected_kind: str,
    repo_root: Path,
    expected_source: dict[str, object] | None,
    *,
    profile: Profile,
) -> dict[str, object]:
    if profile.kind != expected_kind or path.name != profile.receipt_name:
        raise PrerequisiteError("prerequisite kind/filename mismatch")
    run = _validate_run_path(repo_root, path.parent, profile)
    canonical_path = run / profile.receipt_name
    if ".." in path.parts or Path(os.path.abspath(path)) != canonical_path:
        raise PrerequisiteError("receipt path is not canonical")
    raw = _artifact_raw(repo_root, run, profile.receipt_name, limit=_MAX_JSON)
    value = strict_json(raw)
    if not isinstance(value, dict) or canonical_json(value) != raw:
        raise PrerequisiteError("receipt is not canonical JSON")
    expected_keys = {
        "schema_version",
        "status",
        "kind",
        "created_utc",
        "source",
        "run_spec",
        "command",
        "inputs",
        "references",
        "outputs",
        "checks",
    }
    if set(value) != expected_keys or value["schema_version"] != profile.receipt_schema or value["status"] != "PASS":
        raise PrerequisiteError("closed receipt schema/verdict mismatch")
    if (
        value["kind"] != expected_kind
        or type(value["created_utc"]) is not str
        or _UTC.fullmatch(value["created_utc"]) is None
    ):
        raise PrerequisiteError("receipt identity/timestamp mismatch")
    spec, _ = _load_spec(repo_root, run)
    recomputed = _evaluate(profile, repo_root, run, spec, value["created_utc"])
    if recomputed != value:
        raise PrerequisiteError("receipt evidence does not recompute exactly")
    if expected_source is not None and value["source"] != expected_source:
        raise PrerequisiteError("receipt source differs from expected source")
    return {
        "path": canonical_path.relative_to(repo_root).as_posix(),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "verdict": "PASS",
        "schema_version": profile.receipt_schema,
    }


def validate_prerequisite_receipt(
    path: Path,
    expected_kind: str,
    repo_root: Path,
    expected_source: dict[str, object] | None = None,
) -> dict[str, object]:
    """Recompute every receipt claim and return an opaque integration ref."""
    return _validate(path, expected_kind, repo_root, expected_source, profile=_profile(expected_kind))


def _validate_test_receipt(
    path: Path, expected_kind: str, repo_root: Path, profile: Profile, expected_source: dict[str, object] | None = None
) -> dict[str, object]:
    if not profile.test_only:
        raise PrerequisiteError("test validator requires a private test profile")
    return _validate(path, expected_kind, repo_root, expected_source, profile=profile)
