"""Fail-closed ST-R3 child-process production adapter.

This module deliberately contains no evaluator, ground-truth, planner, or
relinefit import.  It validates the frozen arm boundary, then delegates the
only dataset loop to :func:`pipeline.run_postproc_core`.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import stat
import struct
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Literal, get_type_hints

from biohub.io import open_volume
from biohub.public_postproc.config import PostprocConfig, build_config
from biohub.public_postproc.deepcenter import load_deepcenter_veto_detector_strict
from biohub.public_postproc.pipeline import new_stats, run_postproc_core, twin_plan_plain

EVAL12 = (
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
)
EVAL24 = (
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
EVAL36 = EVAL12 + EVAL24

EFFECTIVE_CONFIG_SCHEMA = "biohub.st_r3.effective_config.v1"
DEEPCENTER_RECEIPT_SCHEMA = "biohub.st_r3.deepcenter_receipt.v1"
DATASET_EVENT_SCHEMA = "biohub.st_r3.dataset_event.v1"
TWIN_PLAN_SCHEMA = "biohub.st_r3.twin_plan.v1"
TWIN_PLAN_MANIFEST_SCHEMA = "biohub.st_r3.twin_plan_manifest.v1"
RUN_STATS_SCHEMA = "biohub.st_r3.run_stats.v1"
CHILD_RESULT_SCHEMA = "biohub.st_r3.child_result.v1"

SUBMISSION_PARTIAL = "submission.csv.partial"
RUN_STATS_PARTIAL = "run_stats.csv.partial"
EFFECTIVE_CONFIG_PARTIAL = "effective_config.json.partial"
DEEPCENTER_RECEIPT_PARTIAL = "deepcenter_receipt.json.partial"
TWIN_PLAN_DIRECTORY = "twin_plans"
TWIN_PLAN_MANIFEST_PARTIAL = "twin_plan_manifest.json.partial"
TWIN_DEBUG_PARTIAL = "twin_debug.jsonl.partial"
CHILD_RESULT_NAME = "child_result.json"

_BASE_RAW_STATS_COLUMNS = (
    "dataset",
    "raw_nodes",
    "nodes",
    "raw_edges",
    "edges",
    "division_like_sources",
    "edge_to_node_ratio",
    "gap_added_nodes_frac",
)
_NEW_STATS_COLUMNS = tuple(new_stats())
_TWIN_ELIGIBILITY_REASONS = (
    "distance_twin",
    "ambiguous_p_nn",
    "ambiguous_q_nn",
    "not_mutual_parent_nn",
    "distance_existing_child",
    "distance_parent",
    "distance_sister_low",
    "distance_sister_high",
    "time",
    "missing_successor",
    "shared_successor",
    "divergence",
    "synthetic",
    "deepcenter_bundle",
    "deepcenter_dataset",
    "deepcenter_frame",
    "deepcenter_heatmap",
    "deepcenter_nonfinite",
    "deepcenter_threshold",
)
_TWIN_VALIDATION_REASONS = (
    "missing_node_field",
    "invalid_node_id",
    "duplicate_node_id",
    "invalid_node_time",
    "nonfinite_node_coordinate",
    "invalid_edge_endpoint",
    "dangling_edge",
    "duplicate_edge",
    "nonconsecutive_edge",
    "indegree",
    "outdegree",
    "nonfinite_edge_distance",
)
_RAW_STATS_COLUMNS = _BASE_RAW_STATS_COLUMNS + tuple(
    name for name in _NEW_STATS_COLUMNS if name != "raw_edges"
)
RUN_STATS_COLUMNS = (
    "stats_schema_version",
    "dataset",
    "frames",
    *_BASE_RAW_STATS_COLUMNS[1:],
    *(name for name in _NEW_STATS_COLUMNS if name != "raw_edges"),
    "gap_close_effective_max_gap",
    "planner_seconds",
)


@dataclass(frozen=True)
class ArmSpec:
    arm_name: str
    geff_dir: Path
    test_dir: Path
    deepcenter_checkpoint: Path
    deepcenter_manifest: Path
    datasets: tuple[str, ...]
    expected_effective_config_sha256: str
    staging_dir: Path
    event_fd: int


@dataclass(frozen=True)
class ArtifactDigest:
    relative_path: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class ChildResult:
    arm_name: str
    datasets: tuple[str, ...]
    total_nodes: int
    total_edges: int
    total_rows: int
    artifacts: tuple[ArtifactDigest, ...]


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _canonical_effective_config(cfg: PostprocConfig) -> bytes:
    """Validate all 101 fields and encode exact typed values canonically."""
    if type(cfg) is not PostprocConfig:
        raise TypeError("effective config must be an exact PostprocConfig")
    type_hints = get_type_hints(PostprocConfig)
    config_fields = fields(PostprocConfig)
    if len(config_fields) != 101 or set(type_hints) != {field.name for field in config_fields}:
        raise RuntimeError("unexpected PostprocConfig field schema")
    encoded_fields: dict[str, object] = {}
    for field in config_fields:
        value = getattr(cfg, field.name)
        expected_type = type_hints[field.name]
        if field.name == "TEST_DIR":
            if expected_type is not Path or type(value) is not type(Path()):
                raise TypeError("TEST_DIR must be in the declared Path category")
            encoded_fields[field.name] = {"__type__": "path", "value": str(value)}
        elif expected_type is float:
            if type(value) is not float:
                raise TypeError(f"{field.name} must be exact built-in float")
            if not math.isfinite(value):
                raise ValueError(f"{field.name} must be finite")
            encoded_fields[field.name] = {
                "__type__": "float64",
                "bits_hex": struct.pack(">d", value).hex(),
            }
        elif expected_type in (bool, int, str):
            if type(value) is not expected_type:
                raise TypeError(f"{field.name} must be exact built-in {expected_type.__name__}")
            encoded_fields[field.name] = value
        else:  # pragma: no cover - the 101-field schema is frozen above
            raise RuntimeError(f"unsupported PostprocConfig annotation for {field.name}")
    return _canonical_json_bytes(
        {"schema_version": EFFECTIVE_CONFIG_SCHEMA, "fields": encoded_fields}
    )


def _parse_canonical_effective_config(data: bytes) -> dict[str, object]:
    if type(data) is not bytes or not data.endswith(b"\n") or data.endswith(b"\n\n"):
        raise ValueError("canonical effective config must end in exactly one newline")
    value = json.loads(data)
    if type(value) is not dict or value.get("schema_version") != EFFECTIVE_CONFIG_SCHEMA:
        raise ValueError("invalid effective config schema")
    raw_fields = value.get("fields")
    config_fields = fields(PostprocConfig)
    if type(raw_fields) is not dict or tuple(raw_fields) != tuple(sorted(field.name for field in config_fields)):
        raise ValueError("invalid effective config field set/order")
    type_hints = get_type_hints(PostprocConfig)
    decoded: dict[str, object] = {}
    for field in config_fields:
        item = raw_fields[field.name]
        expected_type = type_hints[field.name]
        if field.name == "TEST_DIR":
            if type(item) is not dict or set(item) != {"__type__", "value"} or item.get("__type__") != "path":
                raise ValueError("invalid tagged TEST_DIR")
            if type(item["value"]) is not str:
                raise TypeError("invalid tagged TEST_DIR value")
            decoded[field.name] = Path(item["value"])
        elif expected_type is float:
            if (
                type(item) is not dict
                or set(item) != {"__type__", "bits_hex"}
                or item.get("__type__") != "float64"
                or type(item.get("bits_hex")) is not str
            ):
                raise ValueError(f"invalid tagged float for {field.name}")
            try:
                raw = bytes.fromhex(item["bits_hex"])
                decoded_value = struct.unpack(">d", raw)[0]
            except (ValueError, struct.error) as exc:
                raise ValueError(f"invalid float bits for {field.name}") from exc
            if len(raw) != 8 or not math.isfinite(decoded_value):
                raise ValueError(f"invalid finite float for {field.name}")
            decoded[field.name] = decoded_value
        else:
            if type(item) is not expected_type:
                raise TypeError(f"invalid exact type for {field.name}")
            decoded[field.name] = item
    round_trip = _canonical_effective_config(PostprocConfig(**decoded))
    if round_trip != data:
        raise ValueError("effective config is not canonical")
    return decoded


def _validate_effective_config(cfg: PostprocConfig, expected_sha256: str) -> bytes:
    if (
        type(expected_sha256) is not str
        or len(expected_sha256) != 64
        or expected_sha256 != expected_sha256.lower()
    ):
        raise ValueError("expected effective-config SHA-256 must be lowercase hexadecimal")
    try:
        bytes.fromhex(expected_sha256)
    except ValueError as exc:
        raise ValueError("expected effective-config SHA-256 must be hexadecimal") from exc
    encoded = _canonical_effective_config(cfg)
    _parse_canonical_effective_config(encoded)
    actual = hashlib.sha256(encoded).hexdigest()
    if actual != expected_sha256:
        raise ValueError(
            f"effective-config SHA-256 mismatch: expected {expected_sha256}, got {actual}"
        )
    return encoded


def _build_arm_config(spec: ArmSpec) -> PostprocConfig:
    """Apply the only three allowed arm-to-profile mappings."""
    profiles = {
        "baseline": ("e23", False),
        "dry_run": ("e23_twin_only_v1", True),
        "candidate": ("e23_twin_only_v1", False),
    }
    try:
        profile, dry_run = profiles[spec.arm_name]
    except KeyError:
        raise ValueError("arm_name must be exactly baseline, dry_run, or candidate") from None
    overrides = {
        "BIOHUB_STEAL_TWIN_DRY_RUN": "1" if dry_run else "0",
        "BIOHUB_DEEPCENTER_CHECKPOINT": str(spec.deepcenter_checkpoint),
        "BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT": str(spec.deepcenter_checkpoint),
        "BIOHUB_DEEPCENTER_MANIFEST": str(spec.deepcenter_manifest),
        "BIOHUB_DEEPCENTER_MANIFEST_DEFAULT": str(spec.deepcenter_manifest),
    }
    cfg = build_config(overrides, test_dir=spec.test_dir, profile=profile)
    expected_master = spec.arm_name != "baseline"
    if (
        cfg.OUTPUT_STEAL_TWIN_REWIRE is not expected_master
        or cfg.STEAL_TWIN_DRY_RUN is not dry_run
        or cfg.STEAL_TWIN_DEBUG_JSONL != ""
    ):
        raise RuntimeError("invalid frozen arm-to-config mapping")
    return cfg


def _require_path_category(value: object, name: str) -> Path:
    if type(value) is not type(Path()):
        raise TypeError(f"{name} must be in the pathlib.Path category")
    return value


def _validate_arm_spec(spec: ArmSpec) -> tuple[Path, ...]:
    if type(spec) is not ArmSpec:
        raise TypeError("spec must be an exact ArmSpec")
    if type(spec.arm_name) is not str or spec.arm_name not in ("baseline", "dry_run", "candidate"):
        raise ValueError("arm_name must be exactly baseline, dry_run, or candidate")
    for name in (
        "geff_dir",
        "test_dir",
        "deepcenter_checkpoint",
        "deepcenter_manifest",
        "staging_dir",
    ):
        _require_path_category(getattr(spec, name), name)
    if type(spec.datasets) is not tuple or any(type(item) is not str for item in spec.datasets):
        raise TypeError("datasets must be an exact tuple of built-in strings")
    if spec.datasets != EVAL36:
        raise ValueError("datasets must equal the literal ordered eval12 + eval24 sequence")
    if len(set(spec.datasets)) != 36:
        raise ValueError("datasets contain a duplicate")
    if type(spec.event_fd) is not int or spec.event_fd <= 2:
        raise ValueError("event_fd must be an inherited non-stdio exact built-in int")

    for root_name in ("geff_dir", "test_dir"):
        root = getattr(spec, root_name)
        if root.is_symlink() or not root.is_dir():
            raise ValueError(f"{root_name} must be a nonsymlink directory")
    geff_entries = tuple(spec.geff_dir.iterdir())
    expected_geff_names = {f"{dataset}.geff" for dataset in EVAL36}
    if {entry.name for entry in geff_entries} != expected_geff_names or len(geff_entries) != 36:
        raise ValueError("GEFF root direct entries must equal the frozen eval36 GEFF set exactly")
    stems = [entry.stem for entry in geff_entries]
    if len(stems) != len(set(stems)) or set(stems) != set(EVAL36):
        raise ValueError("direct GEFF membership must equal the frozen eval36 set")
    for entry in geff_entries:
        if entry.is_symlink() or not (entry.is_file() or entry.is_dir()):
            raise ValueError(f"GEFF input must be a nonsymlink regular file/directory: {entry.name}")
        if entry.is_dir() and any(
            child.is_symlink() or not (child.is_file() or child.is_dir())
            for child in entry.rglob("*")
        ):
            raise ValueError(f"GEFF input tree contains a symlink or special file: {entry.name}")
    geff_paths = tuple(spec.geff_dir / f"{dataset}.geff" for dataset in spec.datasets)

    image_entries = tuple(spec.test_dir.iterdir())
    expected_image_names = {f"{dataset}.zarr" for dataset in EVAL36}
    if {entry.name for entry in image_entries} != expected_image_names or len(image_entries) != 36:
        raise ValueError("image root direct entries must equal the frozen eval36 image-only set exactly")
    if any(entry.is_symlink() or not entry.is_dir() for entry in image_entries):
        raise ValueError("image roots must be nonsymlink directories")
    if any(
        child.is_symlink() or not (child.is_file() or child.is_dir())
        for entry in image_entries
        for child in entry.rglob("*")
    ):
        raise ValueError("image input tree contains a symlink or special file")

    if spec.staging_dir.is_symlink() or not spec.staging_dir.is_dir():
        raise ValueError("staging_dir must be a supervisor-created nonsymlink directory")
    if any(spec.staging_dir.iterdir()):
        raise FileExistsError("staging_dir must be fresh and empty")
    staging_resolved = spec.staging_dir.resolve(strict=True)
    for protected in (spec.geff_dir, spec.test_dir):
        protected_resolved = protected.resolve(strict=True)
        if staging_resolved == protected_resolved or staging_resolved.is_relative_to(protected_resolved):
            raise ValueError("staging_dir overlaps an input root")

    fd_stat = os.fstat(spec.event_fd)
    if not stat.S_ISFIFO(fd_stat.st_mode) or not os.get_blocking(spec.event_fd):
        raise ValueError("event_fd must be an inherited blocking pipe")
    pipe_buf = os.fpathconf(spec.event_fd, "PC_PIPE_BUF")
    if type(pipe_buf) is not int or pipe_buf <= 0:
        raise ValueError("event_fd has no valid PIPE_BUF")
    return geff_paths


def _write_dataset_event(
    event_fd: int,
    arm_name: str,
    dataset: str,
    sequence: int,
    kind: Literal["START", "FINISH"],
) -> bytes:
    if type(event_fd) is not int or type(sequence) is not int or sequence < 0:
        raise TypeError("event fd and sequence must be exact built-in integers")
    if type(arm_name) is not str or type(dataset) is not str or kind not in ("START", "FINISH"):
        raise ValueError("invalid dataset event fields")
    import time

    encoded = _canonical_json_bytes(
        {
            "schema_version": DATASET_EVENT_SCHEMA,
            "pid": os.getpid(),
            "sequence": sequence,
            "arm_name": arm_name,
            "dataset": dataset,
            "kind": kind,
            "monotonic_ns": time.monotonic_ns(),
        }
    )
    pipe_buf = os.fpathconf(event_fd, "PC_PIPE_BUF")
    if len(encoded) >= pipe_buf:
        raise ValueError("dataset event is not strictly smaller than PIPE_BUF")
    try:
        written = os.write(event_fd, encoded)
    except InterruptedError as exc:
        raise RuntimeError("dataset event write was interrupted") from exc
    if written != len(encoded):
        raise RuntimeError("dataset event write was partial")
    return encoded


def _atomic_write(path: Path, data: bytes) -> None:
    if type(path) is not type(Path()) or type(data) is not bytes:
        raise TypeError("atomic write requires exact Path and bytes")
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise FileNotFoundError("atomic write parent must already be a nonsymlink directory")
    handle = tempfile.NamedTemporaryFile(
        mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    )
    temp_path = Path(handle.name)
    try:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.link(temp_path, path, follow_symlinks=False)
        temp_path.unlink()
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            handle.close()
        finally:
            temp_path.unlink(missing_ok=True)
        raise


def _artifact_digest(path: Path, root: Path) -> ArtifactDigest:
    file_stat = path.lstat()
    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError(f"staged artifact is not a regular file: {path.name}")
    data = path.read_bytes()
    after = path.lstat()
    if (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
    ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise RuntimeError(f"staged artifact changed while hashing: {path.name}")
    return ArtifactDigest(
        relative_path=path.relative_to(root).as_posix(),
        bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _canonical_twin_plan(dataset: str, sequence: int, plan: object | None) -> bytes:
    if type(dataset) is not str or type(sequence) is not int or sequence < 0:
        raise TypeError("invalid twin plan envelope fields")
    planner_active = plan is not None
    return _canonical_json_bytes(
        {
            "schema_version": TWIN_PLAN_SCHEMA,
            "dataset": dataset,
            "sequence": sequence,
            "planner_active": planner_active,
            "plan": None if plan is None else twin_plan_plain(plan),
        }
    )


def _validate_raw_stats_row(
    row: Mapping[str, object],
    dataset: str,
    frames_count: int,
    planner_seconds: float | None = None,
) -> tuple[object, ...]:
    if not isinstance(row, Mapping) or type(dataset) is not str:
        raise TypeError("raw stats row must be a mapping for one dataset")
    keys = tuple(row)
    allowed = _RAW_STATS_COLUMNS + ("gap_close_effective_max_gap",)
    if keys not in (_RAW_STATS_COLUMNS, allowed):
        raise ValueError("raw stats keys are missing, extra, or reordered")
    if row.get("dataset") != dataset or type(row.get("dataset")) is not str:
        raise ValueError("raw stats dataset mismatch")
    if type(frames_count) is not int or frames_count <= 0:
        raise ValueError("frames must be a positive exact built-in int")
    if planner_seconds is not None and (
        type(planner_seconds) is not float or not math.isfinite(planner_seconds) or planner_seconds < 0
    ):
        raise ValueError("planner_seconds must be null or a finite nonnegative float")

    float_columns = {"edge_to_node_ratio", "gap_added_nodes_frac"}
    for name in _RAW_STATS_COLUMNS:
        value = row[name]
        if name == "dataset":
            continue
        if name in float_columns:
            if type(value) is not float or not math.isfinite(value):
                raise TypeError(f"raw stats {name} must be a finite exact float")
        elif type(value) is not int or value < 0:
            raise TypeError(f"raw stats {name} must be a nonnegative exact int")
    gap_value = row.get("gap_close_effective_max_gap")
    if gap_value is not None and (type(gap_value) is not int or gap_value < 0):
        raise TypeError("gap_close_effective_max_gap must be null or nonnegative exact int")
    if row["raw_edges"] != row["raw_edges"] or row["nodes"] <= 0:
        raise ValueError("invalid raw stats graph counts")
    if row["edge_to_node_ratio"] != row["edges"] / max(row["nodes"], 1):
        raise ValueError("edge_to_node_ratio conservation failed")
    if row["gap_added_nodes_frac"] != row["gap_added_nodes"] / max(row["raw_nodes"], 1):
        raise ValueError("gap_added_nodes_frac conservation failed")

    if row["steal_twin_validation_failed"] != 0:
        raise ValueError("twin validation failed")
    if sum(row[f"steal_twin_validation_{reason}"] for reason in _TWIN_VALIDATION_REASONS) != 0:
        raise ValueError("twin validation reason counters are nonzero")
    if row["steal_twin_enumerated"] != (
        sum(row[f"steal_twin_rejected_{reason}"] for reason in _TWIN_ELIGIBILITY_REASONS)
        + row["steal_twin_eligible"]
    ):
        raise ValueError("ST-R1 enumeration conservation failed")
    if row["steal_twin_enumerated"] > row["steal_twin_p_pool"]:
        raise ValueError("ST-R1 enumerated count exceeds P pool")
    if row["steal_twin_eligible"] != (
        row["steal_twin_accepted"]
        + row["steal_twin_rejected_conflict"]
        + row["steal_twin_rejected_frame_cap"]
        + row["steal_twin_rejected_video_cap"]
    ):
        raise ValueError("ST-R1 resolution conservation failed")
    if not (
        row["steal_twin_planned_edges_removed"]
        == row["steal_twin_planned_edges_added"]
        == row["steal_twin_accepted"]
    ):
        raise ValueError("ST-R1 planned-edge conservation failed")
    if row["steal_twin_isolated_donors"] != row["steal_twin_accepted"]:
        raise ValueError("ST-R1 isolated-donor conservation failed")
    if not (
        row["steal_twin_accepted"] <= row["steal_twin_examined_frames"]
        and row["steal_twin_accepted"] <= 2
    ):
        raise ValueError("ST-R1 frozen cap conservation failed")
    if not (
        row["steal_twin_edges_removed"]
        == row["steal_twin_edges_added"]
        == row["steal_twin_mutations_applied"]
    ):
        raise ValueError("ST-R2 applied-edge conservation failed")
    if row["steal_twin_pure_edge_symmetric_difference"] != 2 * row["steal_twin_mutations_applied"]:
        raise ValueError("ST-R2 symmetric-difference conservation failed")
    mutations = row["steal_twin_mutations_applied"]
    if mutations not in (0, row["steal_twin_accepted"]):
        raise ValueError("ST-R2 accepted/mutation conservation failed")
    r2_topology_columns = (
        "steal_twin_pure_nodes",
        "steal_twin_pure_edges",
        "steal_twin_pure_fork_sources",
        "steal_twin_geometry_edges_removed_observed",
        "steal_twin_prune_nodes_removed_observed",
        "steal_twin_prune_edges_removed_observed",
        "steal_twin_short_nodes_removed_observed",
        "steal_twin_short_edges_removed_observed",
        "steal_twin_final_nodes",
        "steal_twin_final_edges",
        "steal_twin_final_fork_sources",
        "steal_twin_linefit_coordinate_changed_nodes_observed",
    )
    r2_active = row["steal_twin_pure_nodes"] > 0 or row["steal_twin_pure_edges"] > 0
    if not r2_active:
        if any(row[name] != 0 for name in r2_topology_columns):
            raise ValueError("inactive ST-R2 topology counters must be zero")
    else:
        if mutations != row["steal_twin_accepted"]:
            raise ValueError("active ST-R2 mutation count must equal accepted count")
        if row["steal_twin_final_nodes"] != (
            row["steal_twin_pure_nodes"]
            - row["steal_twin_prune_nodes_removed_observed"]
            - row["steal_twin_short_nodes_removed_observed"]
        ):
            raise ValueError("ST-R2 node conservation failed")
        if row["steal_twin_final_edges"] != (
            row["steal_twin_pure_edges"]
            - row["steal_twin_geometry_edges_removed_observed"]
            - row["steal_twin_prune_edges_removed_observed"]
            - row["steal_twin_short_edges_removed_observed"]
        ):
            raise ValueError("ST-R2 edge conservation failed")
        if row["steal_twin_final_nodes"] != row["nodes"] or row["steal_twin_final_edges"] != row["edges"]:
            raise ValueError("ST-R2 final graph count mismatch")
        if (
            row["steal_twin_pure_fork_sources"] > row["steal_twin_pure_nodes"]
            or row["steal_twin_final_fork_sources"] > row["steal_twin_final_nodes"]
            or row["steal_twin_linefit_coordinate_changed_nodes_observed"] > row["steal_twin_final_nodes"]
        ):
            raise ValueError("ST-R2 fork/linefit count exceeds nodes")
    debug_accounted = row["steal_twin_debug_records_written"] + row["steal_twin_debug_records_dropped"]
    if debug_accounted not in (0, row["steal_twin_eligible"]):
        raise ValueError("ST-R1 debug-record conservation failed")

    normalized = {
        "stats_schema_version": RUN_STATS_SCHEMA,
        "dataset": dataset,
        "frames": frames_count,
        **row,
        "gap_close_effective_max_gap": gap_value,
        "planner_seconds": planner_seconds,
    }
    values = tuple(normalized[name] for name in RUN_STATS_COLUMNS)
    encoded = _canonical_json_bytes(dict(zip(RUN_STATS_COLUMNS, values, strict=True)))
    decoded = json.loads(encoded)
    if tuple(decoded) != tuple(sorted(RUN_STATS_COLUMNS)):
        raise RuntimeError("canonical stats schema changed during encoding")
    for name, value in zip(RUN_STATS_COLUMNS, values, strict=True):
        if decoded[name] != value or (type(value) in (bool, int, float, str) and type(decoded[name]) is not type(value)):
            raise RuntimeError(f"canonical stats value changed during encoding: {name}")
    return values


def _stats_csv_cell(value: object) -> str:
    if value is None:
        return "null"
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("nonfinite stats value")
        return repr(value)
    if type(value) in (int, str):
        text = str(value)
        if not text:
            raise ValueError("blank stats value")
        return text
    raise TypeError("unsupported stats CSV value")


def _parse_stats_csv_cells(cells: Sequence[str]) -> tuple[object, ...]:
    if type(cells) not in (list, tuple) or len(cells) != len(RUN_STATS_COLUMNS):
        raise ValueError("stats CSV row has the wrong field count")
    float_columns = {"edge_to_node_ratio", "gap_added_nodes_frac", "planner_seconds"}
    nullable_columns = {"gap_close_effective_max_gap", "planner_seconds"}
    string_columns = {"stats_schema_version", "dataset"}
    parsed: list[object] = []
    for name, cell in zip(RUN_STATS_COLUMNS, cells, strict=True):
        if type(cell) is not str or cell == "":
            raise ValueError(f"stats CSV {name} is blank or not text")
        if cell == "null":
            if name not in nullable_columns:
                raise ValueError(f"stats CSV {name} is unexpectedly null")
            parsed.append(None)
        elif name in string_columns:
            parsed.append(cell)
        elif name in float_columns:
            value = float(cell)
            if not math.isfinite(value):
                raise ValueError(f"stats CSV {name} is nonfinite")
            parsed.append(value)
        else:
            if cell.startswith("+") or (cell.startswith("0") and cell != "0"):
                raise ValueError(f"stats CSV {name} is not canonical base-10")
            value = int(cell, 10)
            if str(value) != cell or value < 0:
                raise ValueError(f"stats CSV {name} is not canonical nonnegative base-10")
            parsed.append(value)
    return tuple(parsed)


def run_production_arm(spec: ArmSpec) -> ChildResult:
    """Execute one frozen ST-R3 arm inside supervisor-owned staging."""
    geff_paths = _validate_arm_spec(spec)
    cfg = _build_arm_config(spec)
    effective_config = _validate_effective_config(cfg, spec.expected_effective_config_sha256)

    deepcenter_bundle, deepcenter_receipt = load_deepcenter_veto_detector_strict(
        cfg,
        spec.deepcenter_checkpoint,
        spec.deepcenter_manifest,
    )
    if deepcenter_receipt.get("schema_version") != DEEPCENTER_RECEIPT_SCHEMA:
        raise RuntimeError("strict DeepCenter receipt schema mismatch")

    staging = spec.staging_dir
    config_path = staging / EFFECTIVE_CONFIG_PARTIAL
    deepcenter_path = staging / DEEPCENTER_RECEIPT_PARTIAL
    submission_path = staging / SUBMISSION_PARTIAL
    stats_path = staging / RUN_STATS_PARTIAL
    plans_dir = staging / TWIN_PLAN_DIRECTORY
    plan_manifest_path = staging / TWIN_PLAN_MANIFEST_PARTIAL
    _atomic_write(config_path, effective_config)
    _atomic_write(deepcenter_path, _canonical_json_bytes(deepcenter_receipt))
    plans_dir.mkdir()

    plan_records: list[dict[str, object]] = []
    next_plan_sequence = 0
    next_stats_sequence = 0

    stats_handle = stats_path.open("x", encoding="utf-8", newline="")
    stats_writer = csv.writer(stats_handle, lineterminator="\n")
    stats_writer.writerow(RUN_STATS_COLUMNS)
    stats_handle.flush()
    os.fsync(stats_handle.fileno())

    def start_hook(sequence: int, dataset: str) -> None:
        _write_dataset_event(spec.event_fd, spec.arm_name, dataset, sequence, "START")

    def plan_hook(dataset: str, plan: object | None) -> None:
        nonlocal next_plan_sequence
        sequence = next_plan_sequence
        if sequence >= len(EVAL36) or dataset != EVAL36[sequence]:
            raise RuntimeError("twin plan hook order mismatch")
        plan_path = plans_dir / f"{sequence}.{dataset}.json"
        _atomic_write(plan_path, _canonical_twin_plan(dataset, sequence, plan))
        digest = _artifact_digest(plan_path, staging)
        plan_records.append(
            {
                "dataset": dataset,
                "sequence": sequence,
                "planner_active": plan is not None,
                "relative_path": digest.relative_path,
                "bytes": digest.bytes,
                "sha256": digest.sha256,
            }
        )
        next_plan_sequence += 1

    def raw_stats_hook(row: Mapping[str, object]) -> None:
        nonlocal next_stats_sequence
        sequence = next_stats_sequence
        if sequence >= len(EVAL36):
            raise RuntimeError("extra raw stats row")
        dataset = EVAL36[sequence]
        frames_count = open_volume(spec.test_dir / f"{dataset}.zarr").n_t
        values = _validate_raw_stats_row(row, dataset, frames_count)
        cells = [_stats_csv_cell(value) for value in values]
        if _parse_stats_csv_cells(cells) != values:
            raise RuntimeError("stats CSV encoding changed a typed value")
        stats_writer.writerow(cells)
        stats_handle.flush()
        os.fsync(stats_handle.fileno())
        next_stats_sequence += 1

    def finish_hook(sequence: int, dataset: str) -> None:
        if next_plan_sequence != sequence + 1 or next_stats_sequence != sequence + 1:
            raise RuntimeError("dataset FINISH preceded complete plan/stats staging")
        _write_dataset_event(spec.event_fd, spec.arm_name, dataset, sequence, "FINISH")

    def strict_loader(_cfg: PostprocConfig) -> dict[str, object]:
        if _cfg is not cfg:
            raise RuntimeError("pipeline replaced the validated production config")
        return deepcenter_bundle

    try:
        result = run_postproc_core(
            geff_paths,
            submission_path,
            cfg,
            run_stats_path=stats_path,
            deepcenter_loader=strict_loader,
            dataset_start_hook=start_hook,
            dataset_finish_hook=finish_hook,
            twin_plan_hook=plan_hook,
            raw_stats_hook=raw_stats_hook,
            write_run_stats_output=False,
            exclusive_output=True,
        )
        if next_plan_sequence != 36 or next_stats_sequence != 36:
            raise RuntimeError("production pipeline did not complete all frozen datasets")
        stats_handle.flush()
        os.fsync(stats_handle.fileno())
        stats_handle.close()
    except BaseException:
        stats_handle.close()
        raise

    plan_manifest = {
        "schema_version": TWIN_PLAN_MANIFEST_SCHEMA,
        "datasets": list(EVAL36),
        "plans": plan_records,
    }
    _atomic_write(plan_manifest_path, _canonical_json_bytes(plan_manifest))

    artifact_paths = [
        submission_path,
        stats_path,
        config_path,
        deepcenter_path,
        *(plans_dir / f"{sequence}.{dataset}.json" for sequence, dataset in enumerate(EVAL36)),
        plan_manifest_path,
    ]
    artifacts = tuple(_artifact_digest(path, staging) for path in artifact_paths)
    child_result = ChildResult(
        arm_name=spec.arm_name,
        datasets=EVAL36,
        total_nodes=int(result["total_nodes"]),
        total_edges=int(result["total_edges"]),
        total_rows=int(result["total_rows"]),
        artifacts=artifacts,
    )
    child_payload = {
        "schema_version": CHILD_RESULT_SCHEMA,
        "arm_name": child_result.arm_name,
        "datasets": list(child_result.datasets),
        "total_nodes": child_result.total_nodes,
        "total_edges": child_result.total_edges,
        "total_rows": child_result.total_rows,
        "artifacts": [
            {
                "relative_path": artifact.relative_path,
                "bytes": artifact.bytes,
                "sha256": artifact.sha256,
            }
            for artifact in child_result.artifacts
        ],
    }
    _atomic_write(staging / CHILD_RESULT_NAME, _canonical_json_bytes(child_payload))
    return child_result


__all__ = ["ArmSpec", "ChildResult", "run_production_arm"]
