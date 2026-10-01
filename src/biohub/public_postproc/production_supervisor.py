"""Fail-closed ST-R3 child supervision, validation, and publication.

This module intentionally does not import the production adapter, pipeline,
evaluator, scorer, or any ground-truth reader.  It can seal a local child
interface execution while reporting the sandbox, process-tree, target, data,
and scoring holds which remain outside that evidence.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import math
import os
import re
import resource
import select
import signal
import stat
import struct
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

EVAL36 = (
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

EVENT_SCHEMA = "biohub.st_r3.dataset_event.v1"
CHILD_RESULT_SCHEMA = "biohub.st_r3.child_result.v1"
EFFECTIVE_CONFIG_SCHEMA = "biohub.st_r3.effective_config.v1"
DEEPCENTER_RECEIPT_SCHEMA = "biohub.st_r3.deepcenter_receipt.v1"
TWIN_PLAN_SCHEMA = "biohub.st_r3.twin_plan.v1"
TWIN_PLAN_MANIFEST_SCHEMA = "biohub.st_r3.twin_plan_manifest.v1"
RUN_STATS_SCHEMA = "biohub.st_r3.run_stats.v1"
ARM_RECEIPT_SCHEMA = "biohub.st_r3.arm_receipt.v2"
FAILURE_RECEIPT_SCHEMA = "biohub.st_r3.failure_receipt.v2"

_PARTIAL_PROMOTIONS = {
    "submission.csv.partial": "submission.csv",
    "run_stats.csv.partial": "run_stats.csv",
    "effective_config.json.partial": "effective_config.json",
    "deepcenter_receipt.json.partial": "deepcenter_receipt.json",
    "twin_plan_manifest.json.partial": "twin_plan_manifest.json",
}
_SUPERVISOR_LOGS = ("supervisor_stdout.log.partial", "supervisor_stderr.log.partial")
_LOCAL_HOLDS = (
    "HOLD_GT_VISIBLE",
    "HOLD_PROCESS_TREE_UNPROVEN",
    "HOLD_PUBLICATION_CONCURRENCY_UNPROVEN",
    "HOLD_RSS_UNMEASURABLE",
    "HOLD_TARGET_RUNTIME_UNCALIBRATED",
    "HOLD_TARGET_MEMORY_UNCALIBRATED",
    "HOLD_DATA_NOT_READY",
    "HOLD_SCORING_NOT_RUN",
)
_SUBMISSION_HEADER = (
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
)
_RUN_STATS_COLUMNS = tuple(
    """
    stats_schema_version dataset frames raw_nodes nodes raw_edges edges
    division_like_sources edge_to_node_ratio gap_added_nodes_frac
    dropped_nonconsecutive_edges dropped_long_edges dropped_multi_parent_edges
    dropped_multi_child_edges dropped_division_edges gap_candidates
    gap_pairs_selected gap_reused_existing gap_inserted_synthetic gap_added_nodes
    gap_added_edges gap_skipped_node_cap gap_density_nodes_scored
    gap_density_candidates_expanded gap_density_candidates_restricted
    gap_density_selected_outside_base gap_density_step_delta_milli_sum
    gap_refined_synthetic gap_refine_failed gap_refine_rejected_shift
    centroid_refine_examined centroid_refine_moved centroid_refine_no_signal
    centroid_refine_rejected_shift pruned_isolated_nodes motion_relink_edges
    motion_relink_tight_edges motion_relink_relaxed_edges motion_relink_frames
    motion_relink_replaced_raw_edges motion_relink_fallback_raw
    motion_relink_skipped_large_frame gap2_candidates gap2_pairs_selected
    gap2_added_nodes gap2_added_edges gap2_skipped_cap safe_division_candidates
    safe_division_geometric_candidates safe_divisions_added safe_division_skipped_cap
    safe_division_mutual_nn_rejected safe_division_divergence_rejected
    deepcenter_gap_checked deepcenter_gap_bypassed_strong_motion
    deepcenter_gap_bypassed_observed_node deepcenter_gap_accepted
    deepcenter_gap_rejected deepcenter_gap_missing deepcenter_safe_div_checked
    deepcenter_safe_div_accepted deepcenter_safe_div_rejected
    deepcenter_safe_div_missing short_track_components_removed
    short_track_nodes_removed short_track_edges_removed short_track_filter_skipped_all
    short_track_rescue_triggered short_track_rescue_components
    short_track_rescue_nodes short_track_rescue_budget linefit_smoothed_nodes
    linefit_skipped_nodes steal_twin_examined_frames steal_twin_p_pool
    steal_twin_q_pool steal_twin_enumerated steal_twin_rejected_distance_twin
    steal_twin_rejected_ambiguous_p_nn steal_twin_rejected_ambiguous_q_nn
    steal_twin_rejected_not_mutual_parent_nn
    steal_twin_rejected_distance_existing_child steal_twin_rejected_distance_parent
    steal_twin_rejected_distance_sister_low steal_twin_rejected_distance_sister_high
    steal_twin_rejected_time steal_twin_rejected_missing_successor
    steal_twin_rejected_shared_successor steal_twin_rejected_divergence
    steal_twin_rejected_synthetic steal_twin_rejected_deepcenter_bundle
    steal_twin_rejected_deepcenter_dataset steal_twin_rejected_deepcenter_frame
    steal_twin_rejected_deepcenter_heatmap steal_twin_rejected_deepcenter_nonfinite
    steal_twin_rejected_deepcenter_threshold steal_twin_eligible
    steal_twin_rejected_conflict steal_twin_rejected_frame_cap
    steal_twin_rejected_video_cap steal_twin_accepted
    steal_twin_planned_edges_removed steal_twin_planned_edges_added
    steal_twin_edges_removed steal_twin_edges_added steal_twin_isolated_donors
    steal_twin_validation_failed steal_twin_validation_missing_node_field
    steal_twin_validation_invalid_node_id steal_twin_validation_duplicate_node_id
    steal_twin_validation_invalid_node_time
    steal_twin_validation_nonfinite_node_coordinate
    steal_twin_validation_invalid_edge_endpoint steal_twin_validation_dangling_edge
    steal_twin_validation_duplicate_edge steal_twin_validation_nonconsecutive_edge
    steal_twin_validation_indegree steal_twin_validation_outdegree
    steal_twin_validation_nonfinite_edge_distance steal_twin_debug_records_written
    steal_twin_debug_records_dropped steal_twin_mutations_applied
    steal_twin_pure_nodes steal_twin_pure_edges steal_twin_pure_fork_sources
    steal_twin_pure_edge_symmetric_difference
    steal_twin_geometry_edges_removed_observed steal_twin_prune_nodes_removed_observed
    steal_twin_prune_edges_removed_observed steal_twin_short_nodes_removed_observed
    steal_twin_short_edges_removed_observed steal_twin_final_nodes
    steal_twin_final_edges steal_twin_final_fork_sources
    steal_twin_linefit_coordinate_changed_nodes_observed
    gap_close_effective_max_gap planner_seconds
    """.split()
)

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
_TWIN_COUNTER_KEYS = _RUN_STATS_COLUMNS[
    _RUN_STATS_COLUMNS.index("steal_twin_examined_frames") : _RUN_STATS_COLUMNS.index(
        "steal_twin_debug_records_dropped"
    )
    + 1
]
_TWIN_R2_KEYS = (
    "steal_twin_mutations_applied",
    "steal_twin_pure_nodes",
    "steal_twin_pure_edges",
    "steal_twin_pure_fork_sources",
    "steal_twin_pure_edge_symmetric_difference",
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
_TWIN_NODE_KEYS = ("node_id", "t", "z", "y", "x", "gap_synthetic")
_TWIN_EDGE_KEYS = ("source_id", "target_id", "input_position", "metadata")
_TWIN_DEEPCENTER_KEYS = ("accepted", "raw_score", "reason")
_TWIN_REMOVED_EDGE_KEYS = ("source_id", "target_id", "metadata")
_TWIN_PLANNED_EDGE_KEYS = ("source_id", "target_id", "distance_um", "edge_prob")
_TWIN_CANDIDATE_KEYS = (
    "frame",
    "p",
    "q",
    "a",
    "b",
    "a2",
    "b2",
    "d_pq",
    "d_pa",
    "d_pb",
    "d_ab",
    "d_a2b2",
    "divergence_growth",
    "raw_deepcenter_score",
    "deepcenter_decision",
    "sort_key",
    "removed_edge",
    "planned_edge",
)
_TWIN_DEBUG_KEYS = (
    "dataset",
    "decision",
    "reason",
    "p",
    "q",
    "a",
    "b",
    "a2",
    "b2",
    "sort_key",
    "d_pq",
    "d_pa",
    "d_pb",
    "d_ab",
    "d_a2b2",
    "divergence_growth",
    "raw_deepcenter_score",
    "deepcenter_threshold",
    "deepcenter_decision",
    "removed_edge",
    "planned_edge",
)
_DEEPCENTER_MANIFEST_CONFIG = {
    "base_channels": 24,
    "batch_size": 8,
    "bg_quantile": 0.4,
    "brightness_jitter": 0.0,
    "epochs": 1000,
    "frames_per_movie": 0,
    "gauss_sigma": 1.0,
    "grad_clip_norm": None,
    "learning_rate": 0.001,
    "movie_limit": None,
    "norm_clip_hi": 6.0,
    "norm_clip_lo": -0.5,
    "norm_hi_pct": 99.5,
    "norm_lo_pct": 50.0,
    "num_workers": 4,
    "pool_factor": 4,
    "pos_thresh": 0.05,
    "random_flip": True,
    "seed": 2026,
    "val_fraction": 0.1,
    "w_bg": 1.0,
    "w_ignore": 0.05,
    "w_pos": 12.0,
    "weight_decay": 0.0,
}
_DEEPCENTER_CHECKPOINT_CONFIG = {**_DEEPCENTER_MANIFEST_CONFIG, "epochs": 50}
_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FROZEN_TWIN_LIMITS = {
    "STEAL_TWIN_TWIN_MAX_UM": 5.0,
    "STEAL_TWIN_EXISTING_CHILD_MAX_UM": 10.0,
    "STEAL_TWIN_PARENT_MAX_UM": 8.0,
    "STEAL_TWIN_SISTER_MIN_UM": 5.5,
    "STEAL_TWIN_SISTER_MAX_UM": 11.0,
    "STEAL_TWIN_DIVERGE_UM": 2.25,
}
_FROZEN_DEEPCENTER_THRESHOLD = 0.12
_FROZEN_ELIGIBILITY_CONFIG_LIMITS = {
    **_FROZEN_TWIN_LIMITS,
    "DEEPCENTER_SAFE_DIV_THRESHOLD": _FROZEN_DEEPCENTER_THRESHOLD,
}
_TEXT_FORBIDDEN_ABSOLUTE_PREFIXES = (
    "/Users/",
    "/home/",
    "/root/",
    "/private/",
    "/tmp/",
    "/var/",
    "/Volumes/",
    "/mnt/",
    "/data/",
    "/gt/",
    "/secret/",
    "/secrets/",
)
_TEXT_CREDENTIAL_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?:authorization|proxy-authorization|bearer|cookie|set-cookie|"
    r"password|passwd|secret|token|api[ _-]?key|access[ _-]?key|auth)(?![A-Za-z0-9_])"
)
_TEXT_NONFINITE_RE = re.compile(r"(?i)(?<![A-Za-z0-9_])(?:nan|[+-]?inf(?:inity)?)(?![A-Za-z0-9_])")
_TEXT_DATASET_RE = re.compile(r"(?i)(?<![0-9a-z])([0-9a-f]{4}_[0-9a-f]{8})(?![0-9a-z])")
_TEXT_DATASET_FILE_RE = re.compile(r"(?i)(?<![A-Za-z0-9_.-])([A-Za-z0-9][A-Za-z0-9_.-]*)\.(?:geff|zarr)\b")
_TEXT_DATASET_ASSIGN_RE = re.compile(r"(?i)(?<![A-Za-z0-9_])dataset\s*[:=]\s*[\"']?([A-Za-z0-9][A-Za-z0-9_.-]*)")
_TEXT_ABSOLUTE_PATH_RE = re.compile(r"(?<![A-Za-z0-9_])(?:/[A-Za-z0-9_.~+@%=-][^\s\"'<>]*)")
_TEXT_WINDOWS_PATH_RE = re.compile(r"(?i)(?<![A-Za-z0-9_])(?:[A-Z]:\\|\\\\)[^\s\"'<>]+")
_SAFE_REDACTED_LOG = b"[child text rejected by supervisor policy]\n"
_SAFE_FAILURE_REDACTION = "diagnostic redacted by supervisor policy"
_MAX_SUPERVISOR_LOG_BYTES = 1_048_576
_LOCAL_SUCCESS_SCOPE = "LOCAL_VALIDATION_ONLY_NOT_PRODUCTION_PERMISSION"
_SUCCESS_EVIDENCE_STATE = "ARM_RECEIPT_PUBLISHED_WITH_HOLDS"
_FAILURE_EVIDENCE_WRITTEN = "FAILURE_RECEIPT_WRITTEN"
_FAILURE_EVIDENCE_FALLBACK = "FALLBACK_FAILURE_RECEIPT_WRITTEN"
_FAILURE_EVIDENCE_UNWRITABLE = "FAILURE_RECEIPT_UNWRITABLE"


@dataclass(frozen=True)
class SupervisorSpec:
    arm_name: Literal["baseline", "dry_run", "candidate"]
    geff_dir: Path
    test_dir: Path
    deepcenter_checkpoint: Path
    deepcenter_manifest: Path
    expected_effective_config_sha256: str
    final_dir: Path
    timeout_seconds: float


@dataclass(frozen=True)
class SupervisorResult:
    success: bool
    arm_name: str
    child_pid: int | None
    staging_dir: Path | None
    final_dir: Path
    duration_monotonic_ns: int | None
    exit_code: int | None
    term_signal: int | None
    ru_maxrss_raw: int | float | None
    ru_maxrss_unit: str | None
    ru_maxrss_bytes: int | None
    failure_type: str | None
    failure_message: str | None
    receipt_path: Path | None
    failure_evidence_state: str
    failure_evidence_errors: tuple[str, ...]
    success_scope: str
    holds: tuple[str, ...]


class SupervisorError(RuntimeError):
    """An arm cannot be validated or safely published."""


def _canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _write_new_file(path: Path, data: bytes) -> None:
    if path.is_symlink() or path.exists():
        raise FileExistsError(f"refusing to replace artifact: {path.name}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short artifact write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _regular_bytes(path: Path) -> bytes:
    def identity(item: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
        return (
            item.st_dev,
            item.st_ino,
            item.st_mode,
            item.st_nlink,
            item.st_size,
            item.st_mtime_ns,
            item.st_ctime_ns,
        )

    before_path = path.lstat()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise SupervisorError("artifact cannot be opened as a no-follow regular file") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or identity(before_path) != identity(before):
            raise SupervisorError("artifact is not an isolated single-link regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1_048_576)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
        after = os.fstat(fd)
        after_path = path.lstat()
        if identity(before) != identity(after) or identity(after) != identity(after_path) or len(data) != after.st_size:
            raise SupervisorError("artifact changed while being read")
        return data
    finally:
        os.close(fd)


def _digest_record(path: Path, root: Path) -> dict[str, object]:
    data = _regular_bytes(path)
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _safe_relative_path(value: object) -> str:
    if type(value) is not str or not value or "\\" in value:
        raise SupervisorError("artifact relative_path must be a nonempty POSIX string")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise SupervisorError(f"unsafe artifact relative_path: {value!r}")
    return value


def _parse_canonical_json(path: Path) -> dict[str, object]:
    data = _regular_bytes(path)
    if not data.endswith(b"\n") or data.endswith(b"\n\n"):
        raise SupervisorError(f"JSON artifact lacks one canonical trailing newline: {path.name}")
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SupervisorError(f"invalid JSON artifact: {path.name}") from exc
    if type(value) is not dict or data != _canonical_json_bytes(value):
        raise SupervisorError(f"noncanonical JSON artifact: {path.name}")
    return value


def _strict_nonnegative_int(text: str, *, sentinel: bool = False) -> int:
    if type(text) is not str or not text or text.startswith("+"):
        raise SupervisorError("noncanonical integer cell")
    try:
        value = int(text, 10)
    except ValueError as exc:
        raise SupervisorError("noncanonical integer cell") from exc
    if str(value) != text or (value < -1 if sentinel else value < 0):
        raise SupervisorError("integer cell is outside its allowed range")
    return value


def _is_lower_sha256(value: object) -> bool:
    return type(value) is str and _LOWER_SHA256.fullmatch(value) is not None


def _validate_safe_text_bytes(data: bytes) -> str:
    """Validate the exact text policy used for logs and diagnostic artifacts.

    The policy is deliberately syntactic and fail closed: strict UTF-8,
    printable text plus LF/TAB, no credential vocabulary, no nonfinite token,
    no registered host/secret absolute prefix, and no unregistered dataset
    stem or GEFF/Zarr basename.  Errors never include the rejected bytes.
    """
    if type(data) is not bytes:
        raise SupervisorError("text policy received a non-bytes value")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SupervisorError("text artifact violates the safe-text policy") from exc
    if any(character not in "\n\t" and not character.isprintable() for character in text):
        raise SupervisorError("text artifact violates the safe-text policy")
    if _TEXT_CREDENTIAL_RE.search(text) or _TEXT_NONFINITE_RE.search(text) or _TEXT_WINDOWS_PATH_RE.search(text):
        raise SupervisorError("text artifact violates the safe-text policy")
    for match in _TEXT_ABSOLUTE_PATH_RE.finditer(text):
        candidate = match.group(0)
        if candidate.startswith(_TEXT_FORBIDDEN_ABSOLUTE_PREFIXES):
            raise SupervisorError("text artifact violates the safe-text policy")
    if any(match.group(1) not in EVAL36 for match in _TEXT_DATASET_RE.finditer(text)):
        raise SupervisorError("text artifact violates the safe-text policy")
    if any(match.group(1) not in EVAL36 for match in _TEXT_DATASET_FILE_RE.finditer(text)):
        raise SupervisorError("text artifact violates the safe-text policy")
    if any(match.group(1) not in EVAL36 for match in _TEXT_DATASET_ASSIGN_RE.finditer(text)):
        raise SupervisorError("text artifact violates the safe-text policy")
    return text


def _safe_failure_message(failure: BaseException | None) -> str:
    if failure is None:
        return _SAFE_FAILURE_REDACTION
    candidate = str(failure)
    encoded = candidate.encode("utf-8", errors="replace")
    if len(encoded) > 512:
        return _SAFE_FAILURE_REDACTION
    try:
        _validate_safe_text_bytes(encoded)
    except SupervisorError:
        return _SAFE_FAILURE_REDACTION
    return candidate or _SAFE_FAILURE_REDACTION


def _validate_frozen_twin_config(fields: object) -> None:
    if type(fields) is not dict:
        raise SupervisorError("effective config fields are not an exact mapping")
    for name, expected in _FROZEN_ELIGIBILITY_CONFIG_LIMITS.items():
        encoded = fields.get(name)
        if (
            type(encoded) is not dict
            or set(encoded) != {"__type__", "bits_hex"}
            or encoded["__type__"] != "float64"
            or type(encoded["bits_hex"]) is not str
            or encoded["bits_hex"] != struct.pack(">d", expected).hex()
        ):
            raise SupervisorError(f"effective config frozen twin limit differs: {name}")


def _same_float(left: object, right: object) -> bool:
    return (
        type(left) is float
        and type(right) is float
        and math.isfinite(left)
        and math.isfinite(right)
        and left.hex() == right.hex()
    )


def _plain_twin_token(value: object, depth: int = 0) -> object:
    """Validate and normalize the lossless child-side frozen-value codec."""
    if depth > 64:
        raise SupervisorError("active twin plan metadata exceeds maximum depth")
    if value is None or type(value) in (bool, int, str):
        return (type(value).__name__, value)
    if type(value) is float:
        if not math.isfinite(value):
            raise SupervisorError("active twin plan contains a nonfinite plain float")
        return ("float", value.hex())
    if type(value) is not dict or type(value.get("__twin_type__")) is not str:
        raise SupervisorError("active twin plan has invalid frozen metadata")
    kind = value["__twin_type__"]
    if kind == "float":
        if set(value) != {"__twin_type__", "value", "bits_hex"}:
            raise SupervisorError("active twin plan has invalid encoded float")
        label, bits = value["value"], value["bits_hex"]
        if label not in ("nan", "+inf", "-inf") or type(bits) is not str or re.fullmatch(r"[0-9a-f]{16}", bits) is None:
            raise SupervisorError("active twin plan has invalid encoded float")
        decoded = struct.unpack(">d", bytes.fromhex(bits))[0]
        if (
            math.isfinite(decoded)
            or (label == "nan" and not math.isnan(decoded))
            or (label == "+inf" and decoded != math.inf)
            or (label == "-inf" and decoded != -math.inf)
        ):
            raise SupervisorError("active twin plan encoded float label/bits mismatch")
        return ("float", bits)
    if kind == "complex":
        if set(value) != {"__twin_type__", "real", "imag"}:
            raise SupervisorError("active twin plan has invalid encoded complex")
        return (
            "complex",
            _plain_twin_float_token(value["real"], depth + 1),
            _plain_twin_float_token(value["imag"], depth + 1),
        )
    if kind == "bytes":
        if (
            set(value) != {"__twin_type__", "hex"}
            or type(value["hex"]) is not str
            or re.fullmatch(r"(?:[0-9a-f]{2})*", value["hex"]) is None
        ):
            raise SupervisorError("active twin plan has invalid encoded bytes")
        return ("bytes", value["hex"])
    if kind in ("tuple", "frozenset"):
        if set(value) != {"__twin_type__", "items"} or type(value["items"]) is not list:
            raise SupervisorError("active twin plan has invalid encoded collection")
        items = tuple(_plain_twin_token(item, depth + 1) for item in value["items"])
        if kind == "frozenset":
            if list(value["items"]) != sorted(
                value["items"],
                key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False),
            ):
                raise SupervisorError("active twin plan frozenset is not canonically ordered")
            if len(set(items)) != len(items):
                raise SupervisorError("active twin plan frozenset has duplicate values")
        return (kind, items)
    if kind == "mapping":
        if set(value) != {"__twin_type__", "items"} or type(value["items"]) is not list:
            raise SupervisorError("active twin plan has invalid encoded mapping")
        items = value["items"]
        if any(type(item) is not list or len(item) != 2 for item in items):
            raise SupervisorError("active twin plan has invalid encoded mapping items")
        tokens = tuple((_plain_twin_token(item[0], depth + 1), _plain_twin_token(item[1], depth + 1)) for item in items)
        if len({key for key, _item in tokens}) != len(tokens):
            raise SupervisorError("active twin plan encoded mapping has duplicate keys")
        return ("mapping", tokens)
    if kind == "numpy_dtype":
        expected = {
            "__twin_type__",
            "string",
            "descriptor",
            "metadata",
            "itemsize",
            "alignment",
            "byteorder",
            "names",
            "hasobject",
            "aligned_struct",
        }
        if (
            set(value) != expected
            or type(value["string"]) is not str
            or type(value["itemsize"]) is not int
            or value["itemsize"] < 0
            or type(value["alignment"]) is not int
            or value["alignment"] < 0
            or type(value["byteorder"]) is not str
            or type(value["hasobject"]) is not bool
            or type(value["aligned_struct"]) is not bool
        ):
            raise SupervisorError("active twin plan has invalid encoded dtype")
        names = value["names"]
        if names is not None and (
            type(names) is not list or any(type(name) is not str for name in names) or len(set(names)) != len(names)
        ):
            raise SupervisorError("active twin plan has invalid encoded dtype names")
        metadata = value["metadata"]
        metadata_token = None if metadata is None else _plain_twin_token(metadata, depth + 1)
        if metadata_token is not None and metadata_token[0] != "mapping":
            raise SupervisorError("active twin plan dtype metadata is not a mapping")
        token = (
            kind,
            value["string"],
            _plain_twin_token(value["descriptor"], depth + 1),
            metadata_token,
            value["itemsize"],
            value["alignment"],
            value["byteorder"],
            None if names is None else tuple(names),
            value["hasobject"],
            value["aligned_struct"],
        )
        _validate_plain_dtype_token(token)
        return token
    if kind == "numpy_structured_scalar":
        if (
            set(value) != {"__twin_type__", "fields"}
            or type(value["fields"]) is not list
            or any(type(item) is not list or len(item) != 2 or type(item[0]) is not str for item in value["fields"])
        ):
            raise SupervisorError("active twin plan has invalid encoded structured scalar")
        names = [item[0] for item in value["fields"]]
        if len(set(names)) != len(names):
            raise SupervisorError("active twin plan structured scalar has duplicate fields")
        return (kind, tuple((item[0], _plain_twin_token(item[1], depth + 1)) for item in value["fields"]))
    if kind == "numpy_scalar":
        if (
            set(value) != {"__twin_type__", "dtype", "content"}
            or type(value["content"]) is not str
            or re.fullmatch(r"(?:[0-9a-f]{2})*", value["content"]) is None
        ):
            raise SupervisorError("active twin plan has invalid encoded numpy scalar")
        dtype_token = _plain_twin_token(value["dtype"], depth + 1)
        if dtype_token[0] != "numpy_dtype" or dtype_token[8] or len(value["content"]) // 2 != dtype_token[4]:
            raise SupervisorError("active twin plan numpy scalar dtype/content mismatch")
        return (kind, dtype_token, value["content"])
    if kind == "numpy_array":
        base = {"__twin_type__", "dtype", "shape", "strides", "c_contiguous", "f_contiguous", "object_content"}
        keys = set(value)
        if (
            keys not in (base | {"content_hex"}, base | {"content"})
            or type(value["shape"]) is not list
            or any(type(item) is not int or item < 0 for item in value["shape"])
            or type(value["strides"]) is not list
            or any(type(item) is not int for item in value["strides"])
            or len(value["strides"]) != len(value["shape"])
            or type(value["c_contiguous"]) is not bool
            or type(value["f_contiguous"]) is not bool
            or type(value["object_content"]) is not bool
        ):
            raise SupervisorError("active twin plan has invalid encoded numpy array")
        content_name = "content_hex" if "content_hex" in value else "content"
        content = value[content_name]
        if content_name == "content_hex" and (
            type(content) is not str or re.fullmatch(r"(?:[0-9a-f]{2})*", content) is None or value["object_content"]
        ):
            raise SupervisorError("active twin plan has invalid numpy array content")
        if content_name == "content" and not value["object_content"]:
            raise SupervisorError("active twin plan has invalid numpy array content")
        dtype_token = _plain_twin_token(value["dtype"], depth + 1)
        if dtype_token[0] != "numpy_dtype" or value["object_content"] is not dtype_token[8]:
            raise SupervisorError("active twin plan numpy array dtype/content mismatch")
        count = math.prod(value["shape"])
        if content_name == "content_hex":
            if len(content) // 2 != count * dtype_token[4]:
                raise SupervisorError("active twin plan numpy array byte length mismatch")
            content_token: object = content
        else:
            content_token = _plain_twin_token(content, depth + 1)
            if content_token[0] != "tuple" or len(content_token[1]) != count:
                raise SupervisorError("active twin plan numpy object array length mismatch")
        return (
            kind,
            dtype_token,
            tuple(value["shape"]),
            tuple(value["strides"]),
            value["c_contiguous"],
            value["f_contiguous"],
            value["object_content"],
            content_token,
        )
    if kind == "buffer":
        expected = {"__twin_type__", "kind", "format", "itemsize", "shape", "strides", "readonly", "content_hex"}
        if (
            set(value) != expected
            or value["kind"] not in ("bytearray", "memoryview")
            or type(value["format"]) is not str
            or type(value["itemsize"]) is not int
            or value["itemsize"] <= 0
            or type(value["shape"]) is not list
            or any(type(item) is not int or item < 0 for item in value["shape"])
            or type(value["strides"]) is not list
            or any(type(item) is not int for item in value["strides"])
            or (value["strides"] and len(value["strides"]) != len(value["shape"]))
            or type(value["readonly"]) is not bool
            or type(value["content_hex"]) is not str
            or re.fullmatch(r"(?:[0-9a-f]{2})*", value["content_hex"]) is None
        ):
            raise SupervisorError("active twin plan has invalid encoded buffer")
        if len(value["content_hex"]) // 2 != math.prod(value["shape"]) * value["itemsize"]:
            raise SupervisorError("active twin plan buffer byte length mismatch")
        if value["kind"] == "bytearray" and (
            value["format"] != "B"
            or value["itemsize"] != 1
            or value["shape"] != [len(value["content_hex"]) // 2]
            or value["strides"] != [1]
            or value["readonly"] is not False
        ):
            raise SupervisorError("active twin plan has invalid encoded bytearray")
        return (
            kind,
            value["kind"],
            value["format"],
            value["itemsize"],
            tuple(value["shape"]),
            tuple(value["strides"]),
            value["readonly"],
            value["content_hex"],
        )
    raise SupervisorError("active twin plan has an unknown frozen metadata type")


def _plain_twin_float_token(value: object, depth: int) -> object:
    if type(value) is float:
        if not math.isfinite(value):
            raise SupervisorError("active twin plan contains a nonfinite plain float")
        return ("float", struct.pack(">d", value).hex())
    token = _plain_twin_token(value, depth)
    if type(token) is not tuple or not token or token[0] != "float":
        raise SupervisorError("active twin plan complex component is not a float")
    return token


def _descriptor_token_to_python(token: object) -> object:
    if type(token) is not tuple or not token:
        raise SupervisorError("active twin plan dtype descriptor token is invalid")
    kind = token[0]
    if kind in ("NoneType", "bool", "int", "str"):
        return token[1]
    if kind == "float":
        encoded = token[1]
        if type(encoded) is not str:
            raise SupervisorError("active twin plan dtype descriptor float is invalid")
        return float.fromhex(encoded) if "x" in encoded else struct.unpack(">d", bytes.fromhex(encoded))[0]
    if kind == "complex":
        return complex(_descriptor_token_to_python(token[1]), _descriptor_token_to_python(token[2]))
    if kind == "bytes":
        return bytes.fromhex(token[1])
    if kind == "tuple":
        return tuple(_descriptor_token_to_python(item) for item in token[1])
    if kind == "frozenset":
        return frozenset(_descriptor_token_to_python(item) for item in token[1])
    if kind == "mapping":
        try:
            return {_descriptor_token_to_python(key): _descriptor_token_to_python(item) for key, item in token[1]}
        except (TypeError, ValueError) as exc:
            raise SupervisorError("active twin plan dtype descriptor mapping is invalid") from exc
    raise SupervisorError("active twin plan dtype descriptor uses an invalid object")


def _python_descriptor_token(value: object) -> object:
    if value is None or type(value) in (bool, int, str):
        return (type(value).__name__, value)
    if type(value) is float:
        if not math.isfinite(value):
            return ("float", struct.pack(">d", value).hex())
        return ("float", value.hex())
    if type(value) is complex:
        return ("complex", _python_descriptor_token(value.real), _python_descriptor_token(value.imag))
    if type(value) is bytes:
        return ("bytes", value.hex())
    if type(value) in (list, tuple):
        return ("tuple", tuple(_python_descriptor_token(item) for item in value))
    if type(value) in (set, frozenset):
        return ("frozenset", tuple(sorted((_python_descriptor_token(item) for item in value), key=repr)))
    if isinstance(value, dict):
        return (
            "mapping",
            tuple((_python_descriptor_token(key), _python_descriptor_token(item)) for key, item in value.items()),
        )
    raise SupervisorError("active twin plan reconstructed dtype contains an invalid object")


def _validate_plain_dtype_token(token: tuple[object, ...]) -> None:
    import numpy as np

    string, descriptor_token, itemsize, alignment, byteorder, names, hasobject, aligned_struct = (
        token[1],
        token[2],
        token[4],
        token[5],
        token[6],
        token[7],
        token[8],
        token[9],
    )
    try:
        descriptor = _descriptor_token_to_python(descriptor_token)
        if names is None:
            dtype = np.dtype(string)
        else:
            field_names: list[object] = []
            field_titles: list[object | None] = []
            field_formats: list[object] = []
            field_offsets: list[int] = []
            offset = 0
            for entry in descriptor:
                if type(entry) is not tuple or len(entry) not in (2, 3):
                    raise TypeError("invalid dtype descriptor entry")
                field_format = entry[1]
                if type(field_format) is tuple and field_format and all(type(item) is tuple for item in field_format):
                    # numpy's descriptor renders a nested structured field as a
                    # tuple of field entries, while np.dtype expects the same
                    # descriptor as a list at this boundary.
                    field_format = list(field_format)
                field_dtype = np.dtype(field_format if len(entry) == 2 else (field_format, entry[2]))
                if entry[0] != "":
                    if type(entry[0]) is tuple and len(entry[0]) == 2:
                        field_titles.append(entry[0][0])
                        field_names.append(entry[0][1])
                    else:
                        field_titles.append(None)
                        field_names.append(entry[0])
                    field_formats.append(field_dtype)
                    field_offsets.append(offset)
                offset += field_dtype.itemsize
            dtype = np.dtype(
                {
                    "names": field_names,
                    "formats": field_formats,
                    "offsets": field_offsets,
                    "itemsize": itemsize,
                    "titles": field_titles,
                },
                align=aligned_struct,
            )
    except (TypeError, ValueError) as exc:
        raise SupervisorError("active twin plan dtype cannot be reconstructed") from exc
    opaque_subarray = (
        names is None
        and string == f"|V{itemsize}"
        and descriptor_token == ("tuple", (("tuple", (("str", ""), ("str", string))),))
        and byteorder == "|"
        and hasobject is False
        and aligned_struct is False
        and type(alignment) is int
        and alignment > 0
        and (itemsize == 0 or itemsize % alignment == 0)
    )
    if not opaque_subarray and (
        dtype.str != string
        or _python_descriptor_token(dtype.descr) != descriptor_token
        or dtype.itemsize != itemsize
        or dtype.alignment != alignment
        or dtype.byteorder != byteorder
        or dtype.names != names
        or bool(dtype.hasobject) is not hasobject
        or bool(dtype.isalignedstruct) is not aligned_struct
    ):
        raise SupervisorError("active twin plan dtype fields are internally inconsistent")


def _image_shape(test_dir: Path, dataset: str) -> tuple[int, int, int, int]:
    meta = test_dir / f"{dataset}.zarr" / "0" / "zarr.json"
    value = _parse_canonical_or_plain_json(meta)
    shape = value.get("shape")
    if type(shape) is not list or len(shape) != 4 or any(type(item) is not int or item <= 0 for item in shape):
        raise SupervisorError(f"invalid image array shape for {dataset}")
    return tuple(shape)  # type: ignore[return-value]


def _parse_canonical_or_plain_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(_regular_bytes(path))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SupervisorError(f"invalid JSON input: {path}") from exc
    if type(value) is not dict:
        raise SupervisorError(f"JSON input must be an object: {path}")
    return value


def _physical_csv_rows(path: Path, width: int) -> list[list[str]]:
    data = _regular_bytes(path)
    if not data or not data.endswith(b"\n") or data.endswith(b"\n\n"):
        raise SupervisorError(f"CSV artifact lacks exactly one final LF: {path.name}")
    if b"\r" in data or b'"' in data or b"\x00" in data:
        raise SupervisorError(f"CSV artifact contains a forbidden physical byte: {path.name}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SupervisorError(f"CSV artifact is not UTF-8: {path.name}") from exc
    lines = text[:-1].split("\n")
    if not lines or any(not line for line in lines):
        raise SupervisorError(f"CSV artifact contains a blank physical line: {path.name}")
    rows = [line.split(",") for line in lines]
    if any(len(row) != width for row in rows):
        raise SupervisorError(f"CSV artifact has a non-fixed physical width: {path.name}")
    return rows


def _validate_submission(path: Path, test_dir: Path) -> tuple[int, int, int]:
    shapes = {dataset: _image_shape(test_dir, dataset) for dataset in EVAL36}
    physical_rows = _physical_csv_rows(path, len(_SUBMISSION_HEADER))
    if tuple(physical_rows[0]) != _SUBMISSION_HEADER:
        raise SupervisorError("submission has the wrong fixed header")
    nodes: dict[str, dict[int, int]] = {dataset: {} for dataset in EVAL36}
    edges: dict[str, list[tuple[int, int]]] = {dataset: [] for dataset in EVAL36}
    phase = {dataset: "node" for dataset in EVAL36}
    previous_node = {dataset: -1 for dataset in EVAL36}
    dataset_index = 0
    row_count = 0
    for cells in physical_rows[1:]:
        if any(cell == "" for cell in cells):
            raise SupervisorError("submission has a malformed or blank row")
        row = dict(zip(_SUBMISSION_HEADER, cells, strict=True))
        if _strict_nonnegative_int(row["id"]) != row_count:
            raise SupervisorError("submission IDs are not contiguous physical-row IDs")
        dataset = row["dataset"]
        if dataset not in nodes:
            raise SupervisorError("submission contains an unexpected dataset")
        current = EVAL36[dataset_index]
        if dataset != current:
            if dataset_index + 1 >= len(EVAL36) or dataset != EVAL36[dataset_index + 1]:
                raise SupervisorError("submission dataset blocks are reordered or repeated")
            dataset_index += 1
        if row["row_type"] == "node":
            if phase[dataset] != "node":
                raise SupervisorError("submission node follows an edge")
            node_id = _strict_nonnegative_int(row["node_id"])
            if node_id <= previous_node[dataset] or node_id in nodes[dataset]:
                raise SupervisorError("submission nodes are duplicate or not strictly ordered")
            t, z, y, x = (_strict_nonnegative_int(row[name]) for name in ("t", "z", "y", "x"))
            if tuple(_strict_nonnegative_int(row[name], sentinel=True) for name in ("source_id", "target_id")) != (
                -1,
                -1,
            ):
                raise SupervisorError("node row has invalid edge sentinels")
            if any(value >= bound for value, bound in zip((t, z, y, x), shapes[dataset], strict=True)):
                raise SupervisorError("node row lies outside explicit image bounds")
            nodes[dataset][node_id] = t
            previous_node[dataset] = node_id
        elif row["row_type"] == "edge":
            phase[dataset] = "edge"
            if (
                tuple(_strict_nonnegative_int(row[name], sentinel=True) for name in ("node_id", "t", "z", "y", "x"))
                != (-1,) * 5
            ):
                raise SupervisorError("edge row has invalid node sentinels")
            edges[dataset].append(
                (_strict_nonnegative_int(row["source_id"]), _strict_nonnegative_int(row["target_id"]))
            )
        else:
            raise SupervisorError("submission row_type must be node or edge")
        row_count += 1
    if dataset_index != len(EVAL36) - 1 or any(not value for value in nodes.values()):
        raise SupervisorError("submission does not contain every frozen dataset with nodes")
    for dataset in EVAL36:
        seen: set[tuple[int, int]] = set()
        indegree: dict[int, int] = {}
        outdegree: dict[int, int] = {}
        for source, target in edges[dataset]:
            if (
                source == target
                or source not in nodes[dataset]
                or target not in nodes[dataset]
                or (source, target) in seen
            ):
                raise SupervisorError("submission edge identity/referential integrity failed")
            if nodes[dataset][target] != nodes[dataset][source] + 1:
                raise SupervisorError("submission edge is not consecutive in time")
            seen.add((source, target))
            indegree[target] = indegree.get(target, 0) + 1
            outdegree[source] = outdegree.get(source, 0) + 1
            if indegree[target] > 1 or outdegree[source] > 2:
                raise SupervisorError("submission graph degree limit failed")
    return sum(len(value) for value in nodes.values()), sum(len(value) for value in edges.values()), row_count


def _validate_run_stats(path: Path) -> dict[str, dict[str, object]]:
    physical_rows = _physical_csv_rows(path, len(_RUN_STATS_COLUMNS))
    if tuple(physical_rows[0]) != _RUN_STATS_COLUMNS:
        raise SupervisorError("run stats header does not equal the fixed v1 schema")
    rows = [dict(zip(_RUN_STATS_COLUMNS, cells, strict=True)) for cells in physical_rows[1:]]
    if len(rows) != 36:
        raise SupervisorError("run stats must contain exactly one row per eval36 dataset")
    if [row["dataset"] for row in rows] != list(EVAL36):
        raise SupervisorError("run stats dataset rows are not literal eval36 order")
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        if row["stats_schema_version"] != RUN_STATS_SCHEMA or any(value == "" for value in row.values()):
            raise SupervisorError("run stats contains a schema, width, or blank-cell error")
        typed: dict[str, int | float | str | None] = {
            "stats_schema_version": row["stats_schema_version"],
            "dataset": row["dataset"],
        }
        for name in _RUN_STATS_COLUMNS:
            if name in ("stats_schema_version", "dataset", "gap_close_effective_max_gap", "planner_seconds"):
                continue
            if name in ("edge_to_node_ratio", "gap_added_nodes_frac"):
                value = float(row[name])
                if not math.isfinite(value) or repr(value) != row[name]:
                    raise SupervisorError(f"run stats {name} is noncanonical or nonfinite")
                typed[name] = value
            else:
                typed[name] = _strict_nonnegative_int(row[name])
        if row["gap_close_effective_max_gap"] != "null":
            typed["gap_close_effective_max_gap"] = _strict_nonnegative_int(row["gap_close_effective_max_gap"])
        else:
            typed["gap_close_effective_max_gap"] = None
        if row["planner_seconds"] != "null":
            value = float(row["planner_seconds"])
            if not math.isfinite(value) or value < 0 or repr(value) != row["planner_seconds"]:
                raise SupervisorError("run stats planner_seconds is noncanonical")
            typed["planner_seconds"] = value
        else:
            typed["planner_seconds"] = None
        if typed["frames"] <= 0:
            raise SupervisorError("run stats frames must be a positive exact built-in int")
        if typed["nodes"] <= 0:
            raise SupervisorError("invalid raw stats graph counts")
        if typed["edge_to_node_ratio"] != typed["edges"] / max(typed["nodes"], 1):
            raise SupervisorError("run stats edge_to_node_ratio conservation failed")
        if typed["gap_added_nodes_frac"] != typed["gap_added_nodes"] / max(typed["raw_nodes"], 1):
            raise SupervisorError("run stats gap_added_nodes_frac conservation failed")
        if typed["steal_twin_validation_failed"] != 0:
            raise SupervisorError("run stats reports a twin validation failure")
        if sum(typed[f"steal_twin_validation_{reason}"] for reason in _TWIN_VALIDATION_REASONS) != 0:
            raise SupervisorError("run stats twin validation reason counters are nonzero")
        if typed["steal_twin_enumerated"] != (
            sum(typed[f"steal_twin_rejected_{reason}"] for reason in _TWIN_ELIGIBILITY_REASONS)
            + typed["steal_twin_eligible"]
        ):
            raise SupervisorError("run stats ST-R1 enumeration conservation failed")
        if typed["steal_twin_enumerated"] > typed["steal_twin_p_pool"]:
            raise SupervisorError("run stats enumerated count exceeds the P pool")
        if typed["steal_twin_eligible"] != (
            typed["steal_twin_accepted"]
            + typed["steal_twin_rejected_conflict"]
            + typed["steal_twin_rejected_frame_cap"]
            + typed["steal_twin_rejected_video_cap"]
        ):
            raise SupervisorError("run stats ST-R1 resolution conservation failed")
        if not (
            typed["steal_twin_planned_edges_removed"]
            == typed["steal_twin_planned_edges_added"]
            == typed["steal_twin_accepted"]
        ):
            raise SupervisorError("run stats ST-R1 planned-edge conservation failed")
        if typed["steal_twin_isolated_donors"] != typed["steal_twin_accepted"]:
            raise SupervisorError("run stats ST-R1 isolated-donor conservation failed")
        if not (
            typed["steal_twin_accepted"] <= typed["steal_twin_examined_frames"] and typed["steal_twin_accepted"] <= 2
        ):
            raise SupervisorError("run stats ST-R1 frozen cap conservation failed")
        if not (
            typed["steal_twin_edges_removed"]
            == typed["steal_twin_edges_added"]
            == typed["steal_twin_mutations_applied"]
        ):
            raise SupervisorError("run stats applied mutation conservation failed")
        if typed["steal_twin_pure_edge_symmetric_difference"] != 2 * typed["steal_twin_mutations_applied"]:
            raise SupervisorError("run stats ST-R2 symmetric-difference conservation failed")
        mutations = typed["steal_twin_mutations_applied"]
        if mutations not in (0, typed["steal_twin_accepted"]):
            raise SupervisorError("run stats ST-R2 accepted/mutation conservation failed")
        topology_columns = (
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
        r2_active = typed["steal_twin_pure_nodes"] > 0 or typed["steal_twin_pure_edges"] > 0
        if not r2_active:
            if any(typed[name] != 0 for name in topology_columns):
                raise SupervisorError("run stats inactive ST-R2 topology counters must be zero")
        else:
            if mutations != typed["steal_twin_accepted"]:
                raise SupervisorError("run stats active ST-R2 mutation count must equal accepted count")
            if typed["steal_twin_final_nodes"] != (
                typed["steal_twin_pure_nodes"]
                - typed["steal_twin_prune_nodes_removed_observed"]
                - typed["steal_twin_short_nodes_removed_observed"]
            ):
                raise SupervisorError("run stats ST-R2 node conservation failed")
            if typed["steal_twin_final_edges"] != (
                typed["steal_twin_pure_edges"]
                - typed["steal_twin_geometry_edges_removed_observed"]
                - typed["steal_twin_prune_edges_removed_observed"]
                - typed["steal_twin_short_edges_removed_observed"]
            ):
                raise SupervisorError("run stats ST-R2 edge conservation failed")
            if typed["steal_twin_final_nodes"] != typed["nodes"] or typed["steal_twin_final_edges"] != typed["edges"]:
                raise SupervisorError("run stats ST-R2 final graph count mismatch")
            if (
                typed["steal_twin_pure_fork_sources"] > typed["steal_twin_pure_nodes"]
                or typed["steal_twin_final_fork_sources"] > typed["steal_twin_final_nodes"]
                or typed["steal_twin_linefit_coordinate_changed_nodes_observed"] > typed["steal_twin_final_nodes"]
            ):
                raise SupervisorError("run stats ST-R2 fork/linefit count exceeds nodes")
        debug_accounted = typed["steal_twin_debug_records_written"] + typed["steal_twin_debug_records_dropped"]
        if debug_accounted not in (0, typed["steal_twin_eligible"]):
            raise SupervisorError("run stats ST-R1 debug-record conservation failed")
        canonical_cells = []
        for name in _RUN_STATS_COLUMNS:
            value = typed[name]
            if value is None:
                canonical_cells.append("null")
            elif type(value) is float:
                canonical_cells.append(repr(value))
            else:
                canonical_cells.append(str(value))
        if canonical_cells != [row[name] for name in _RUN_STATS_COLUMNS]:
            raise SupervisorError("run stats row is not the exact canonical child encoding")
        result[row["dataset"]] = dict(typed)
    return result


def _validate_events(data: bytes, arm_name: str, pid: int) -> list[dict[str, object]]:
    if not data.endswith(b"\n") or data.count(b"\n") != 72:
        raise SupervisorError("event pipe must contain exactly 72 complete JSON lines")
    records: list[dict[str, object]] = []
    previous_ns = -1
    expected_keys = {"schema_version", "pid", "sequence", "arm_name", "dataset", "kind", "monotonic_ns"}
    for index, line in enumerate(data.splitlines(keepends=True)):
        if len(line) >= 4096:
            raise SupervisorError("event record is not below the portable PIPE_BUF minimum")
        try:
            record = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SupervisorError("event pipe contains invalid JSON") from exc
        if type(record) is not dict or set(record) != expected_keys or line != _canonical_json_bytes(record):
            raise SupervisorError("event record is not the exact canonical schema")
        sequence, pair_index = divmod(index, 2)
        if (
            record["schema_version"] != EVENT_SCHEMA
            or type(record["pid"]) is not int
            or record["pid"] != pid
            or type(record["sequence"]) is not int
            or record["sequence"] != sequence
            or record["arm_name"] != arm_name
            or record["dataset"] != EVAL36[sequence]
            or record["kind"] != ("START" if pair_index == 0 else "FINISH")
            or type(record["monotonic_ns"]) is not int
            or record["monotonic_ns"] <= previous_ns
        ):
            raise SupervisorError("event PID/order/kind/time validation failed")
        previous_ns = record["monotonic_ns"]
        records.append(record)
    return records


def _same_typed_plain(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return set(left) == set(right) and all(_same_typed_plain(left[key], right[key]) for key in left)
    if type(left) is list:
        return len(left) == len(right) and all(_same_typed_plain(a, b) for a, b in zip(left, right, strict=True))
    if type(left) is float:
        return _same_float(left, right)
    return left == right


def _validate_deepcenter_file_receipt(value: object, expected_sha256: str) -> None:
    if type(value) is not dict or set(value) != {"sha256", "pre", "post_hash", "post_read", "open_count"}:
        raise SupervisorError("DeepCenter file receipt schema validation failed")
    if value["sha256"] != expected_sha256 or value["open_count"] != 1 or type(value["open_count"]) is not int:
        raise SupervisorError("DeepCenter file receipt identity/open-count validation failed")
    expected_stat_keys = {"device", "inode", "mode", "size", "mtime_ns", "ctime_ns"}
    stats = (value["pre"], value["post_hash"], value["post_read"])
    if any(
        type(item) is not dict
        or set(item) != expected_stat_keys
        or any(type(field) is not int or field < 0 for field in item.values())
        or not stat.S_ISREG(item["mode"])
        for item in stats
    ) or not (stats[0] == stats[1] == stats[2]):
        raise SupervisorError("DeepCenter file receipt stat identity validation failed")


def _validate_deepcenter_receipt(
    value: object,
    checkpoint_name: str | None,
    manifest_name: str | None,
) -> None:
    expected_keys = {
        "schema_version",
        "registered",
        "checkpoint",
        "manifest",
        "chosen_artifact",
        "verified_epoch",
        "verified_configs",
        "known_config_discrepancy",
        "inference_relevant_config_equal",
        "device",
        "dtype",
        "open_count",
        "fallback_candidates",
    }
    if type(value) is not dict or set(value) != expected_keys:
        raise SupervisorError("DeepCenter receipt exact schema validation failed")
    registered = value["registered"]
    if type(registered) is not dict or set(registered) != {"checkpoint_name", "manifest_name"}:
        raise SupervisorError("DeepCenter registered identity validation failed")
    registered_checkpoint = registered["checkpoint_name"]
    registered_manifest = registered["manifest_name"]
    if (
        type(registered_checkpoint) is not str
        or type(registered_manifest) is not str
        or not registered_checkpoint
        or not registered_manifest
        or (checkpoint_name is not None and registered_checkpoint != checkpoint_name)
        or (manifest_name is not None and registered_manifest != manifest_name)
        or value["chosen_artifact"] != registered_checkpoint
        or type(value["chosen_artifact"]) is not str
    ):
        raise SupervisorError("DeepCenter registered/chosen artifact identity validation failed")
    _validate_deepcenter_file_receipt(
        value["checkpoint"],
        "8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0",
    )
    _validate_deepcenter_file_receipt(
        value["manifest"],
        "1eedc1af72b10c464c6995013075310510b6f6e634450ff2bc170c67b89ce911",
    )
    expected_configs = {
        "manifest": _DEEPCENTER_MANIFEST_CONFIG,
        "checkpoint": _DEEPCENTER_CHECKPOINT_CONFIG,
    }
    if (
        value["schema_version"] != DEEPCENTER_RECEIPT_SCHEMA
        or type(value["schema_version"]) is not str
        or type(value["verified_epoch"]) is not int
        or value["verified_epoch"] != 2
        or not _same_typed_plain(value["verified_configs"], expected_configs)
        or not _same_typed_plain(
            value["known_config_discrepancy"],
            {"field": "epochs", "manifest": 1000, "checkpoint": 50},
        )
        or value["inference_relevant_config_equal"] is not True
        or type(value["device"]) is not str
        or value["device"] != "cpu"
        or type(value["dtype"]) is not str
        or value["dtype"] != "float32"
        or type(value["open_count"]) is not int
        or value["open_count"] != 2
        or type(value["fallback_candidates"]) is not int
        or value["fallback_candidates"] != 0
    ):
        raise SupervisorError("DeepCenter verified configuration/stat validation failed")


def _twin_counter_mapping(value: object) -> dict[str, int]:
    if (
        type(value) is not dict
        or set(value) != {"__twin_type__", "items"}
        or value["__twin_type__"] != "mapping"
        or type(value["items"]) is not list
        or len(value["items"]) != len(_TWIN_COUNTER_KEYS)
    ):
        raise SupervisorError("active twin plan counter schema validation failed")
    counters: dict[str, int] = {}
    for expected, item in zip(_TWIN_COUNTER_KEYS, value["items"], strict=True):
        if (
            type(item) is not list
            or len(item) != 2
            or type(item[0]) is not str
            or item[0] != expected
            or type(item[1]) is not int
            or item[1] < 0
        ):
            raise SupervisorError("active twin plan counter schema/value validation failed")
        counters[expected] = item[1]
    return counters


def _metadata_endpoint(metadata: object, name: str) -> int:
    _plain_twin_token(metadata)
    items = metadata["items"] if type(metadata) is dict and metadata.get("__twin_type__") == "mapping" else []
    values = [item[1] for item in items if type(item[0]) is str and item[0] == name]
    if len(values) != 1 or type(values[0]) is not int:
        raise SupervisorError("active twin plan edge metadata endpoint validation failed")
    return values[0]


def _validate_twin_deepcenter(value: object, raw_score: float) -> None:
    if (
        type(value) is not dict
        or set(value) != set(_TWIN_DEEPCENTER_KEYS)
        or value["accepted"] is not True
        or not _same_float(value["raw_score"], raw_score)
        or raw_score < _FROZEN_DEEPCENTER_THRESHOLD
        or value["reason"] is not None
    ):
        raise SupervisorError("active twin plan DeepCenter decision validation failed")


def _validate_twin_candidate(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != set(_TWIN_CANDIDATE_KEYS):
        raise SupervisorError("active twin plan candidate schema validation failed")
    for name in ("frame", "p", "q", "a", "b", "a2", "b2"):
        if type(value[name]) is not int:
            raise SupervisorError("active twin plan candidate integer validation failed")
    float_names = (
        "d_pq",
        "d_pa",
        "d_pb",
        "d_ab",
        "d_a2b2",
        "divergence_growth",
        "raw_deepcenter_score",
    )
    if any(type(value[name]) is not float or not math.isfinite(value[name]) for name in float_names):
        raise SupervisorError("active twin plan candidate float validation failed")
    _validate_twin_deepcenter(value["deepcenter_decision"], value["raw_deepcenter_score"])
    sort_key = value["sort_key"]
    if (
        type(sort_key) is not list
        or len(sort_key) != 9
        or any(type(item) is not float or not math.isfinite(item) for item in sort_key[:3])
        or any(type(item) is not int for item in sort_key[3:])
    ):
        raise SupervisorError("active twin plan candidate sort-key validation failed")
    removed = value["removed_edge"]
    if (
        type(removed) is not dict
        or set(removed) != set(_TWIN_REMOVED_EDGE_KEYS)
        or type(removed["source_id"]) is not int
        or type(removed["target_id"]) is not int
        or (removed["source_id"], removed["target_id"]) != (value["q"], value["b"])
    ):
        raise SupervisorError("active twin plan removed-edge validation failed")
    _plain_twin_token(removed["metadata"])
    planned = value["planned_edge"]
    if (
        type(planned) is not dict
        or set(planned) != set(_TWIN_PLANNED_EDGE_KEYS)
        or type(planned["source_id"]) is not int
        or type(planned["target_id"]) is not int
        or (planned["source_id"], planned["target_id"]) != (value["p"], value["b"])
        or type(planned["distance_um"]) is not float
        or not math.isfinite(planned["distance_um"])
        or planned["edge_prob"] is not None
    ):
        raise SupervisorError("active twin plan planned-edge validation failed")
    return value


def _twin_distance(left: dict[str, object], right: dict[str, object]) -> float:
    # Imported only after the supervised child has exited.  Matching the
    # producer's float64 ufunc/reduction path is necessary for bit-exact plan
    # distance validation; math.sqrt differs by one ULP for ordinary inputs.
    import numpy as np

    delta = np.asarray(
        [
            (left[name] - right[name]) * scale
            for name, scale in zip(("z", "y", "x"), (1.625, 0.40625, 0.40625), strict=True)
        ],
        dtype=np.float64,
    )
    return float(np.sqrt(np.sum(delta * delta)))


def _validate_active_twin_plan(value: object, dataset: str) -> dict[str, object]:
    try:
        expected_top = {
            "validation_reason",
            "nodes",
            "edges",
            "candidates",
            "accepted_candidates",
            "decisions",
            "counters",
            "debug_records",
        }
        if type(value) is not dict or set(value) != expected_top:
            raise SupervisorError("active twin plan top-level schema validation failed")
        lists = tuple(
            value[name]
            for name in ("nodes", "edges", "candidates", "accepted_candidates", "decisions", "debug_records")
        )
        if any(type(item) is not list for item in lists):
            raise SupervisorError("active twin plan list-field schema validation failed")
        counters = _twin_counter_mapping(value["counters"])
        reason = value["validation_reason"]
        if reason is not None:
            if type(reason) is not str or reason not in _TWIN_VALIDATION_REASONS or any(lists):
                raise SupervisorError("active twin plan validation-failure envelope validation failed")
            expected_one = {"steal_twin_validation_failed", f"steal_twin_validation_{reason}"}
            if any(count != (1 if key in expected_one else 0) for key, count in counters.items()):
                raise SupervisorError("active twin plan validation-failure counters validation failed")
            return {"counters": counters, "nodes": 0, "edges": 0, "validation_reason": reason}

        candidates = [_validate_twin_candidate(item) for item in value["candidates"]]
        accepted = [_validate_twin_candidate(item) for item in value["accepted_candidates"]]
        accepted_count = counters["steal_twin_accepted"]
        if not (
            counters["steal_twin_enumerated"]
            == sum(counters[f"steal_twin_rejected_{name}"] for name in _TWIN_ELIGIBILITY_REASONS)
            + counters["steal_twin_eligible"]
            and counters["steal_twin_eligible"]
            == accepted_count
            + counters["steal_twin_rejected_conflict"]
            + counters["steal_twin_rejected_frame_cap"]
            + counters["steal_twin_rejected_video_cap"]
            and counters["steal_twin_planned_edges_removed"] == accepted_count
            and counters["steal_twin_planned_edges_added"] == accepted_count
            and counters["steal_twin_edges_removed"] == 0
            and counters["steal_twin_edges_added"] == 0
            and counters["steal_twin_isolated_donors"] == accepted_count
            and counters["steal_twin_validation_failed"] == 0
            and all(counters[f"steal_twin_validation_{name}"] == 0 for name in _TWIN_VALIDATION_REASONS)
            and counters["steal_twin_debug_records_written"] == 0
            and counters["steal_twin_debug_records_dropped"] == 0
            and len(candidates) == counters["steal_twin_eligible"]
            and len(accepted) == accepted_count
            and accepted_count <= counters["steal_twin_examined_frames"]
            and accepted_count <= 2
        ):
            raise SupervisorError("active twin plan counter conservation failed")

        nodes: dict[int, dict[str, object]] = {}
        previous_node: int | None = None
        for node in value["nodes"]:
            if (
                type(node) is not dict
                or set(node) != set(_TWIN_NODE_KEYS)
                or type(node["node_id"]) is not int
                or type(node["t"]) is not int
                or any(type(node[name]) is not float or not math.isfinite(node[name]) for name in ("z", "y", "x"))
                or type(node["gap_synthetic"]) is not bool
                or (previous_node is not None and node["node_id"] <= previous_node)
            ):
                raise SupervisorError("active twin plan node schema/invariant validation failed")
            previous_node = node["node_id"]
            nodes[node["node_id"]] = node

        edge_pairs: set[tuple[int, int]] = set()
        edge_metadata: dict[tuple[int, int], object] = {}
        positions: set[int] = set()
        incoming: dict[int, set[int]] = {}
        outgoing: dict[int, set[int]] = {}
        previous_edge: tuple[int, int, int] | None = None
        for edge in value["edges"]:
            if (
                type(edge) is not dict
                or set(edge) != set(_TWIN_EDGE_KEYS)
                or any(type(edge[name]) is not int for name in ("source_id", "target_id", "input_position"))
            ):
                raise SupervisorError("active twin plan edge schema validation failed")
            source, target, position = edge["source_id"], edge["target_id"], edge["input_position"]
            edge_key = (source, target, position)
            pair = (source, target)
            if (
                previous_edge is not None
                and edge_key <= previous_edge
                or pair in edge_pairs
                or position in positions
                or source not in nodes
                or target not in nodes
                or nodes[target]["t"] != nodes[source]["t"] + 1
                or _metadata_endpoint(edge["metadata"], "source_id") != source
                or _metadata_endpoint(edge["metadata"], "target_id") != target
            ):
                raise SupervisorError("active twin plan edge invariant validation failed")
            previous_edge = edge_key
            edge_pairs.add(pair)
            edge_metadata[pair] = edge["metadata"]
            positions.add(position)
            outgoing.setdefault(source, set()).add(target)
            incoming.setdefault(target, set()).add(source)
        if (
            positions != set(range(len(value["edges"])))
            or any(len(items) > 1 for items in incoming.values())
            or any(len(items) > 2 for items in outgoing.values())
        ):
            raise SupervisorError("active twin plan graph invariant validation failed")

        p_by_frame: dict[int, list[int]] = {}
        q_by_frame: dict[int, list[int]] = {}
        for node_id, node in nodes.items():
            indegree = len(incoming.get(node_id, ()))
            outdegree = len(outgoing.get(node_id, ()))
            if indegree == 1 and outdegree == 1:
                p_by_frame.setdefault(node["t"], []).append(node_id)
            if indegree == 0 and outdegree == 1:
                q_by_frame.setdefault(node["t"], []).append(node_id)
        for pool in (p_by_frame, q_by_frame):
            for node_ids in pool.values():
                node_ids.sort()
        examined_frames = set(p_by_frame) | set(q_by_frame)
        enumerated = sum(len(p_by_frame.get(frame, ())) for frame in examined_frames if q_by_frame.get(frame))
        if (
            counters["steal_twin_examined_frames"] != len(examined_frames)
            or counters["steal_twin_p_pool"] != sum(map(len, p_by_frame.values()))
            or counters["steal_twin_q_pool"] != sum(map(len, q_by_frame.values()))
            or counters["steal_twin_enumerated"] != enumerated
            or counters["steal_twin_rejected_time"] != 0
        ):
            raise SupervisorError("active twin plan pool/enumeration conservation failed")

        decisions = value["decisions"]
        if len(decisions) != len(candidates):
            raise SupervisorError("active twin plan decision count validation failed")
        accepted_from_decisions = []
        rejected_counts = {name: 0 for name in ("conflict", "frame_cap", "video_cap")}
        for candidate, decision in zip(candidates, decisions, strict=True):
            if (
                type(decision) is not dict
                or set(decision) != {"candidate", "accepted", "reason"}
                or not _same_typed_plain(decision["candidate"], candidate)
                or type(decision["accepted"]) is not bool
            ):
                raise SupervisorError("active twin plan decision schema/projection validation failed")
            if decision["accepted"] is True and decision["reason"] is None:
                accepted_from_decisions.append(candidate)
            elif (
                decision["accepted"] is False
                and type(decision["reason"]) is str
                and decision["reason"] in rejected_counts
            ):
                rejected_counts[decision["reason"]] += 1
            else:
                raise SupervisorError("active twin plan decision semantics validation failed")
        if (
            len(accepted_from_decisions) != len(accepted)
            or any(
                not _same_typed_plain(left, right)
                for left, right in zip(accepted_from_decisions, accepted, strict=True)
            )
            or any(rejected_counts[name] != counters[f"steal_twin_rejected_{name}"] for name in rejected_counts)
        ):
            raise SupervisorError("active twin plan accepted-membership validation failed")

        previous_sort: tuple[object, ...] | None = None
        accepted_roles: set[int] = set()
        accepted_frames: set[int] = set()
        candidate_parents: set[int] = set()
        for candidate, decision in zip(candidates, decisions, strict=True):
            roles = tuple(candidate[name] for name in ("p", "q", "a", "b", "a2", "b2"))
            if len(set(roles)) != 6 or any(role not in nodes for role in roles):
                raise SupervisorError("active twin plan candidate role validation failed")
            p, q, a, b, a2, b2 = roles
            frame = candidate["frame"]
            if (nodes[p]["t"], nodes[q]["t"], nodes[a]["t"], nodes[b]["t"], nodes[a2]["t"], nodes[b2]["t"]) != (
                frame,
                frame,
                frame + 1,
                frame + 1,
                frame + 2,
                frame + 2,
            ) or any(nodes[role]["gap_synthetic"] for role in roles):
                raise SupervisorError("active twin plan candidate time/synthetic validation failed")
            if p not in p_by_frame.get(frame, ()) or q not in q_by_frame.get(frame, ()) or p in candidate_parents:
                raise SupervisorError("active twin plan candidate pool-role validation failed")
            candidate_parents.add(p)

            def unique_nearest(source: int, choices: list[int]) -> int | None:
                neighbors = sorted(
                    (
                        (_twin_distance(nodes[source], nodes[other]), other)
                        for other in choices
                        if _twin_distance(nodes[source], nodes[other]) <= _FROZEN_TWIN_LIMITS["STEAL_TWIN_TWIN_MAX_UM"]
                    ),
                    key=lambda item: (item[0], item[1]),
                )
                if not neighbors:
                    return None
                minimum = neighbors[0][0]
                if sum(distance - minimum <= 1e-9 for distance, _other in neighbors) != 1:
                    return None
                return neighbors[0][1]

            if unique_nearest(p, q_by_frame[frame]) != q or unique_nearest(q, p_by_frame[frame]) != p:
                raise SupervisorError("active twin plan mutual-nearest validation failed")
            distance_names = ("d_pq", "d_pa", "d_pb", "d_ab", "d_a2b2")
            distances = (
                _twin_distance(nodes[p], nodes[q]),
                _twin_distance(nodes[p], nodes[a]),
                _twin_distance(nodes[p], nodes[b]),
                _twin_distance(nodes[a], nodes[b]),
                _twin_distance(nodes[a2], nodes[b2]),
            )
            if any(
                not _same_float(distance, candidate[name])
                for distance, name in zip(distances, distance_names, strict=True)
            ) or not _same_float(distances[4] - distances[3], candidate["divergence_growth"]):
                raise SupervisorError("active twin plan candidate distance validation failed")
            if not (
                distances[0] <= _FROZEN_TWIN_LIMITS["STEAL_TWIN_TWIN_MAX_UM"]
                and distances[1] <= _FROZEN_TWIN_LIMITS["STEAL_TWIN_EXISTING_CHILD_MAX_UM"]
                and distances[2] <= _FROZEN_TWIN_LIMITS["STEAL_TWIN_PARENT_MAX_UM"]
                and _FROZEN_TWIN_LIMITS["STEAL_TWIN_SISTER_MIN_UM"]
                <= distances[3]
                <= _FROZEN_TWIN_LIMITS["STEAL_TWIN_SISTER_MAX_UM"]
                and candidate["divergence_growth"] >= _FROZEN_TWIN_LIMITS["STEAL_TWIN_DIVERGE_UM"]
            ):
                raise SupervisorError("active twin plan frozen eligibility boundary failed")
            formula = (
                candidate["d_pb"] + 0.15 * candidate["d_ab"],
                -candidate["divergence_growth"],
                candidate["d_pq"],
                *roles,
            )
            if (
                any(not _same_float(formula[index], candidate["sort_key"][index]) for index in range(3))
                or tuple(candidate["sort_key"][3:]) != formula[3:]
                or not _same_float(candidate["planned_edge"]["distance_um"], distances[2])
            ):
                raise SupervisorError("active twin plan sort/planned-distance validation failed")
            removed_pair = (q, b)
            required = ((p, a), removed_pair, (a, a2), (b, b2))
            if (
                removed_pair not in edge_metadata
                or not _same_typed_plain(candidate["removed_edge"]["metadata"], edge_metadata[removed_pair])
                or any(pair not in edge_pairs for pair in required)
                or (p, b) in edge_pairs
                or outgoing.get(p, set()) != {a}
                or outgoing.get(q, set()) != {b}
                or outgoing.get(a, set()) != {a2}
                or outgoing.get(b, set()) != {b2}
                or incoming.get(q, set())
            ):
                raise SupervisorError("active twin plan candidate graph projection validation failed")
            current_sort = tuple(candidate["sort_key"])
            if previous_sort is not None and current_sort < previous_sort:
                raise SupervisorError("active twin plan candidate ordering validation failed")
            previous_sort = current_sort
            expected_reason = (
                "conflict"
                if set(roles) & accepted_roles
                else "frame_cap"
                if frame in accepted_frames
                else "video_cap"
                if len(accepted_frames) >= 2
                else None
            )
            if decision["accepted"] is not (expected_reason is None) or decision["reason"] != expected_reason:
                raise SupervisorError("active twin plan resolution-order validation failed")
            if expected_reason is None:
                accepted_roles.update(roles)
                accepted_frames.add(frame)
        if len(accepted_frames) != accepted_count:
            raise SupervisorError("active twin plan accepted-frame conservation failed")

        debug_records = value["debug_records"]
        if len(debug_records) != len(candidates):
            raise SupervisorError("active twin plan debug-record count validation failed")
        for record, candidate, decision in zip(debug_records, candidates, decisions, strict=True):
            if (
                type(record) is not dict
                or set(record) != set(_TWIN_DEBUG_KEYS)
                or type(record["dataset"]) is not str
                or record["dataset"] != dataset
                or record["decision"] != ("accepted" if decision["accepted"] else "rejected")
                or record["reason"] != decision["reason"]
                or not _same_float(record["deepcenter_threshold"], _FROZEN_DEEPCENTER_THRESHOLD)
            ):
                raise SupervisorError("active twin plan debug-record schema/identity validation failed")
            projected_names = (
                "p",
                "q",
                "a",
                "b",
                "a2",
                "b2",
                "sort_key",
                "d_pq",
                "d_pa",
                "d_pb",
                "d_ab",
                "d_a2b2",
                "divergence_growth",
                "raw_deepcenter_score",
                "deepcenter_decision",
                "removed_edge",
                "planned_edge",
            )
            if any(not _same_typed_plain(record[name], candidate[name]) for name in projected_names):
                raise SupervisorError("active twin plan debug-record projection validation failed")
        return {
            "counters": counters,
            "nodes": len(nodes),
            "edges": len(edge_pairs),
            "validation_reason": None,
        }
    except SupervisorError as exc:
        if str(exc).startswith("active twin plan"):
            raise
        raise SupervisorError(f"active twin plan validation failed: {exc}") from exc
    except Exception as exc:
        raise SupervisorError("active twin plan validation failed") from exc


def _validate_json_artifacts(
    staging: Path,
    arm_name: str,
    artifact_by_path: dict[str, dict[str, object]],
    expected_effective_config_sha256: str,
    deepcenter_checkpoint_name: str | None = None,
    deepcenter_manifest_name: str | None = None,
) -> dict[str, dict[str, object]]:
    config_path = staging / "effective_config.json.partial"
    config_data = _regular_bytes(config_path)
    if hashlib.sha256(config_data).hexdigest() != expected_effective_config_sha256:
        raise SupervisorError("effective config does not match the supervisor spec SHA-256")
    config = _parse_canonical_json(config_path)
    if (
        set(config) != {"schema_version", "fields"}
        or config["schema_version"] != EFFECTIVE_CONFIG_SCHEMA
        or type(config["fields"]) is not dict
        or len(config["fields"]) != 101
    ):
        raise SupervisorError("effective config essential schema validation failed")
    _validate_frozen_twin_config(config["fields"])
    deepcenter = _parse_canonical_json(staging / "deepcenter_receipt.json.partial")
    _validate_deepcenter_receipt(
        deepcenter,
        deepcenter_checkpoint_name,
        deepcenter_manifest_name,
    )
    plans = []
    plan_summaries: dict[str, dict[str, object]] = {}
    for sequence, dataset in enumerate(EVAL36):
        relative = f"twin_plans/{sequence}.{dataset}.json"
        plan_path = staging / relative
        _validate_safe_text_bytes(_regular_bytes(plan_path))
        plan = _parse_canonical_json(plan_path)
        if (
            set(plan) != {"schema_version", "dataset", "sequence", "planner_active", "plan"}
            or plan["schema_version"] != TWIN_PLAN_SCHEMA
            or plan["dataset"] != dataset
            or plan["sequence"] != sequence
            or type(plan["planner_active"]) is not bool
            or plan["planner_active"] is (arm_name == "baseline")
            or (plan["plan"] is None) is plan["planner_active"]
        ):
            raise SupervisorError("twin plan envelope validation failed")
        if plan["planner_active"] and (
            type(plan["plan"]) is not dict
            or set(plan["plan"])
            != {
                "validation_reason",
                "nodes",
                "edges",
                "candidates",
                "accepted_candidates",
                "decisions",
                "counters",
                "debug_records",
            }
        ):
            raise SupervisorError("active twin plan has a missing or extra top-level field")
        if plan["planner_active"]:
            plan_summaries[dataset] = _validate_active_twin_plan(plan["plan"], dataset)
        else:
            plan_summaries[dataset] = {
                "counters": dict.fromkeys(_TWIN_COUNTER_KEYS, 0),
                "nodes": None,
                "edges": None,
                "validation_reason": None,
            }
        digest = artifact_by_path[relative]
        plans.append(
            {
                "dataset": dataset,
                "sequence": sequence,
                "planner_active": plan["planner_active"],
                "relative_path": relative,
                "bytes": digest["bytes"],
                "sha256": digest["sha256"],
            }
        )
    manifest = _parse_canonical_json(staging / "twin_plan_manifest.json.partial")
    if manifest != {"schema_version": TWIN_PLAN_MANIFEST_SCHEMA, "datasets": list(EVAL36), "plans": plans}:
        raise SupervisorError("twin plan manifest does not bind every exact plan")
    return plan_summaries


def _validate_plan_stats_consistency(
    arm_name: str,
    stats_by_dataset: dict[str, dict[str, object]],
    plans_by_dataset: dict[str, dict[str, object]],
) -> None:
    if set(stats_by_dataset) != set(EVAL36) or set(plans_by_dataset) != set(EVAL36):
        raise SupervisorError("plan/stats dataset sets do not equal eval36")
    for dataset in EVAL36:
        stats = stats_by_dataset[dataset]
        plan = plans_by_dataset[dataset]
        counters = plan["counters"]
        if type(counters) is not dict or set(counters) != set(_TWIN_COUNTER_KEYS):
            raise SupervisorError("plan/stats counter schema mismatch")
        if arm_name == "baseline":
            if any(stats[name] != 0 for name in (*_TWIN_COUNTER_KEYS, *_TWIN_R2_KEYS)):
                raise SupervisorError(f"baseline plan/stats counters must be zero: {dataset}")
            continue
        if plan["validation_reason"] is not None:
            raise SupervisorError(f"active arm contains a failed twin plan: {dataset}")
        applied_keys = {"steal_twin_edges_removed", "steal_twin_edges_added"}
        if any(stats[name] != value for name, value in counters.items() if name not in applied_keys):
            raise SupervisorError(f"plan/run-stats pre-mutation counters differ: {dataset}")
        accepted = counters["steal_twin_accepted"]
        if arm_name == "dry_run":
            if any(stats[name] != counters[name] for name in applied_keys) or any(
                stats[name] != 0 for name in _TWIN_R2_KEYS
            ):
                raise SupervisorError(f"dry-run stats report an applied mutation/topology: {dataset}")
            continue
        if not (
            stats["steal_twin_edges_removed"]
            == stats["steal_twin_edges_added"]
            == stats["steal_twin_mutations_applied"]
            == accepted
            and stats["steal_twin_pure_nodes"] == plan["nodes"]
            and stats["steal_twin_pure_edges"] == plan["edges"]
        ):
            raise SupervisorError(f"candidate plan/applied stats topology differs: {dataset}")


def _validate_child_staging(
    staging: Path,
    arm_name: str,
    test_dir: Path,
    expected_effective_config_sha256: str,
    deepcenter_checkpoint_name: str | None = None,
    deepcenter_manifest_name: str | None = None,
) -> dict[str, object]:
    child = _parse_canonical_json(staging / "child_result.json")
    if set(child) != {
        "schema_version",
        "arm_name",
        "datasets",
        "total_nodes",
        "total_edges",
        "total_rows",
        "artifacts",
    }:
        raise SupervisorError("child_result has missing or extra fields")
    if (
        child["schema_version"] != CHILD_RESULT_SCHEMA
        or child["arm_name"] != arm_name
        or child["datasets"] != list(EVAL36)
    ):
        raise SupervisorError("child_result identity/dataset mismatch")
    for name in ("total_nodes", "total_edges", "total_rows"):
        if type(child[name]) is not int or child[name] < 0:
            raise SupervisorError("child_result count is not a nonnegative exact integer")
    artifacts = child["artifacts"]
    if type(artifacts) is not list:
        raise SupervisorError("child_result artifacts must be a list")
    artifact_by_path: dict[str, dict[str, object]] = {}
    for record in artifacts:
        if type(record) is not dict or set(record) != {"relative_path", "bytes", "sha256"}:
            raise SupervisorError("invalid child artifact record schema")
        relative = _safe_relative_path(record["relative_path"])
        if relative in artifact_by_path or type(record["bytes"]) is not int or record["bytes"] < 0:
            raise SupervisorError("duplicate artifact path or invalid byte count")
        if not _is_lower_sha256(record["sha256"]):
            raise SupervisorError("invalid artifact SHA-256")
        actual = _digest_record(staging / relative, staging)
        if actual != record:
            raise SupervisorError(f"child artifact byte/hash mismatch: {relative}")
        artifact_by_path[relative] = record
    expected = {
        *(_PARTIAL_PROMOTIONS),
        *(f"twin_plans/{sequence}.{dataset}.json" for sequence, dataset in enumerate(EVAL36)),
    }
    if set(artifact_by_path) != expected:
        raise SupervisorError("child artifact path set is missing, extra, or renamed")
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for path in staging.rglob("*"):
        info = path.lstat()
        relative = path.relative_to(staging).as_posix()
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise SupervisorError(f"staging contains a symlink or special file: {relative}")
        (actual_files if stat.S_ISREG(info.st_mode) else actual_directories).add(relative)
    if actual_directories != {"twin_plans"} or actual_files != expected | {"child_result.json"}:
        raise SupervisorError("staging contains an unregistered child artifact")
    submission_counts = _validate_submission(staging / "submission.csv.partial", test_dir)
    if submission_counts != (child["total_nodes"], child["total_edges"], child["total_rows"]):
        raise SupervisorError("child_result counts do not equal the validated submission")
    stats_by_dataset = _validate_run_stats(staging / "run_stats.csv.partial")
    plans_by_dataset = _validate_json_artifacts(
        staging,
        arm_name,
        artifact_by_path,
        expected_effective_config_sha256,
        deepcenter_checkpoint_name,
        deepcenter_manifest_name,
    )
    _validate_plan_stats_consistency(arm_name, stats_by_dataset, plans_by_dataset)
    return child


def _promote_partial_files(
    staging: Path,
    expected_artifacts: dict[str, dict[str, object]] | None = None,
) -> dict[str, str]:
    for source_name, destination_name in _PARTIAL_PROMOTIONS.items():
        source, destination = staging / source_name, staging / destination_name
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"promotion target already exists: {destination_name}")
        source_record = _digest_record(source, staging)
        if expected_artifacts is not None and source_record != expected_artifacts[source_name]:
            raise SupervisorError("child artifact changed immediately before promotion")
        os.link(source, destination, follow_symlinks=False)
        source.unlink()
        promoted = destination.lstat()
        if not stat.S_ISREG(promoted.st_mode) or promoted.st_nlink != 1:
            raise SupervisorError("promoted artifact is not an isolated single-link regular file")
    _fsync_directory(staging)
    return dict(_PARTIAL_PROMOTIONS)


class _PublicationPostconditionError(SupervisorError):
    def __init__(self, rollback_name: str | None, final_present: bool, rollback_failed: bool):
        super().__init__(
            "publication postcondition failed; rollback "
            + ("failed and final remains present" if rollback_failed else "completed to retained failure staging")
        )
        self.rollback_name = rollback_name
        self.final_present = final_present
        self.rollback_failed = rollback_failed


def _rename_directory_no_replace(parent_fd: int, source_name: str, destination_name: str) -> str:
    libc = ctypes.CDLL(None, use_errno=True)
    encoded_source, encoded_destination = os.fsencode(source_name), os.fsencode(destination_name)
    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        result = libc.renameat2(parent_fd, encoded_source, parent_fd, encoded_destination, 1)
        primitive = "renameat2(RENAME_NOREPLACE)"
    elif sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        result = libc.renameatx_np(parent_fd, encoded_source, parent_fd, encoded_destination, 0x00000004)
        primitive = "renameatx_np(RENAME_EXCL)"
    else:
        raise SupervisorError("HOLD_PUBLICATION_NOREPLACE_UNSUPPORTED")
    if result != 0:
        error = ctypes.get_errno()
        if error in (errno.EEXIST, errno.ENOTEMPTY):
            raise FileExistsError(f"final arm directory collision: {destination_name}")
        if error in (errno.ENOSYS, errno.ENOTSUP, errno.EINVAL):
            raise SupervisorError("HOLD_PUBLICATION_NOREPLACE_UNSUPPORTED")
        raise OSError(error, os.strerror(error), destination_name)
    os.fsync(parent_fd)
    return primitive


def _publish_directory_no_replace(parent_fd: int, source_name: str, destination_name: str) -> str:
    parent_info = os.fstat(parent_fd)
    pending_key = (parent_info.st_dev, parent_info.st_ino, source_name)
    pending_seal = _PENDING_PUBLICATION_SEALS.get(pending_key)
    if pending_seal is not None:
        _verify_tree_seal(pending_seal)
    primitive = _rename_directory_no_replace(parent_fd, source_name, destination_name)
    if pending_seal is None:
        return primitive
    pending_seal.staging = pending_seal.staging.parent / destination_name
    try:
        _verify_tree_seal(pending_seal)
    except BaseException as postcondition_error:
        rollback_name = f".{destination_name}.failed.{uuid.uuid4().hex}"
        try:
            _rename_directory_no_replace(parent_fd, destination_name, rollback_name)
        except BaseException as rollback_error:
            raise _PublicationPostconditionError(None, True, True) from ExceptionGroup(
                "publication verification and rollback both failed",
                [postcondition_error, rollback_error],
            )
        pending_seal.staging = pending_seal.staging.parent / rollback_name
        raise _PublicationPostconditionError(rollback_name, False, False) from postcondition_error
    return primitive


def _normalized_rss(usage: resource.struct_rusage) -> tuple[int | float, str, int]:
    raw = usage.ru_maxrss
    if type(raw) not in (int, float) or not math.isfinite(raw) or raw <= 0:
        raise SupervisorError("invalid wait4 ru_maxrss")
    if sys.platform == "darwin":
        unit, normalized = "bytes", int(raw)
    elif sys.platform.startswith("linux"):
        unit, normalized = "KiB", int(raw * 1024)
    else:
        raise SupervisorError("unknown wait4 ru_maxrss platform/unit")
    if normalized <= 0:
        raise SupervisorError("normalized wait4 ru_maxrss is not positive")
    return raw, unit, normalized


def _child_environment() -> dict[str, str]:
    return {
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


def _cloexec_pipe() -> tuple[int, int]:
    if hasattr(os, "pipe2"):
        return os.pipe2(os.O_CLOEXEC)
    read_fd, write_fd = os.pipe()
    os.set_inheritable(read_fd, False)
    os.set_inheritable(write_fd, False)
    return read_fd, write_fd


def _kill_child_process_group(child_pid: int) -> None:
    """Kill the isolated child session; a self-detached descendant remains held."""
    try:
        os.killpg(child_pid, signal.SIGKILL)
    except ProcessLookupError:
        try:
            os.kill(child_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _drain_pipe(
    fd: int,
    output_fd: int | None,
    sink: bytearray,
    done: threading.Event,
    errors: list[BaseException],
    byte_limit: int | None = None,
) -> None:
    os.set_blocking(fd, False)
    try:
        quiet_after_done = 0
        captured_bytes = 0
        while True:
            ready, _, _ = select.select([fd], [], [], 0.05)
            if ready:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                quiet_after_done = 0
                if output_fd is not None:
                    captured_bytes += len(chunk)
                    if byte_limit is not None and captured_bytes > byte_limit:
                        raise SupervisorError("supervisor log exceeded its exact byte limit")
                    view = memoryview(chunk)
                    while view:
                        written = os.write(output_fd, view)
                        if written <= 0:
                            raise OSError("short supervisor log write")
                        view = view[written:]
                else:
                    sink.extend(chunk)
                    if len(sink) > 1_048_576:
                        raise SupervisorError("event pipe exceeded bounded receipt size")
            elif done.is_set():
                quiet_after_done += 1
                if quiet_after_done >= 4:
                    break
        if output_fd is not None:
            os.fsync(output_fd)
    except BaseException as exc:
        errors.append(exc)
    finally:
        if output_fd is not None:
            os.close(output_fd)
        os.close(fd)


def _validate_spec(spec: SupervisorSpec) -> None:
    if type(spec) is not SupervisorSpec:
        raise TypeError("spec must be an exact SupervisorSpec")
    if spec.arm_name not in ("baseline", "dry_run", "candidate"):
        raise ValueError("invalid frozen arm name")
    for name in ("geff_dir", "test_dir", "deepcenter_checkpoint", "deepcenter_manifest", "final_dir"):
        if type(getattr(spec, name)) is not type(Path()):
            raise TypeError(f"{name} must be in the pathlib.Path category")
    if type(spec.timeout_seconds) is not float or not math.isfinite(spec.timeout_seconds) or spec.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be a finite positive exact float")
    digest = spec.expected_effective_config_sha256
    if not _is_lower_sha256(digest):
        raise ValueError("effective config digest must be lowercase SHA-256")


def _partial_inventory(
    staging: Path,
    exclude: set[str] | None = None,
    *,
    strict: bool = True,
) -> list[dict[str, object]]:
    excluded = exclude or set()
    records = []
    for path in sorted(staging.rglob("*"), key=lambda item: item.relative_to(staging).as_posix()):
        relative = path.relative_to(staging).as_posix()
        if relative in excluded:
            continue
        receipt_relative = relative
        if not strict:
            try:
                _validate_safe_text_bytes(relative.encode("utf-8"))
            except SupervisorError:
                receipt_relative = f"redacted-entry-{hashlib.sha256(relative.encode()).hexdigest()[:16]}"
        info = path.lstat()
        if stat.S_ISREG(info.st_mode):
            try:
                record = _digest_record(path, staging)
                record["relative_path"] = receipt_relative
                records.append(record)
            except SupervisorError:
                if strict:
                    raise
                records.append({"relative_path": receipt_relative, "kind": "rejected_regular"})
        else:
            records.append(
                {
                    "relative_path": receipt_relative,
                    "kind": "directory" if stat.S_ISDIR(info.st_mode) else "rejected_special",
                }
            )
    return records


def _stat_signature(item: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        item.st_dev,
        item.st_ino,
        item.st_mode,
        item.st_nlink,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )


def _hash_open_fd(fd: int, expected_size: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    offset = 0
    while offset < expected_size:
        chunk = os.pread(fd, min(1_048_576, expected_size - offset), offset)
        if not chunk:
            raise SupervisorError("sealed file ended before its fstat size")
        digest.update(chunk)
        offset += len(chunk)
    if os.pread(fd, 1, offset):
        raise SupervisorError("sealed file exceeds its fstat size")
    return offset, digest.hexdigest()


def _read_open_fd(fd: int, expected_size: int) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < expected_size:
        chunk = os.pread(fd, min(1_048_576, expected_size - offset), offset)
        if not chunk:
            raise SupervisorError("sealed text ended before its fstat size")
        chunks.append(chunk)
        offset += len(chunk)
    if os.pread(fd, 1, offset):
        raise SupervisorError("sealed text exceeds its fstat size")
    return b"".join(chunks)


@dataclass
class _TreeSeal:
    staging: Path
    staging_fd: int
    files: dict[str, tuple[int, tuple[int, int, int, int, int, int, int], int, str]]
    directories: dict[str, tuple[int, int, int]]


def _seal_tree_readonly(staging: Path, staging_fd: int) -> _TreeSeal:
    files: dict[str, tuple[int, tuple[int, int, int, int, int, int, int], int, str]] = {}
    directories: dict[str, tuple[int, int, int]] = {}
    try:
        for path in sorted(staging.rglob("*"), key=lambda item: item.relative_to(staging).as_posix()):
            relative = path.relative_to(staging).as_posix()
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                directories[relative] = (info.st_dev, info.st_ino, info.st_mode)
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise SupervisorError("publication tree contains a non-isolated regular file")
            fd = os.open(
                path,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            before = os.fstat(fd)
            if _stat_signature(before) != _stat_signature(info) or before.st_nlink != 1:
                os.close(fd)
                raise SupervisorError("publication tree file identity changed before sealing")
            size, digest = _hash_open_fd(fd, before.st_size)
            after = os.fstat(fd)
            if _stat_signature(before) != _stat_signature(after):
                os.close(fd)
                raise SupervisorError("publication tree file changed while sealing")
            os.fchmod(fd, 0o400)
            sealed = os.fstat(fd)
            if sealed.st_nlink != 1 or not stat.S_ISREG(sealed.st_mode):
                os.close(fd)
                raise SupervisorError("publication tree file lost single-link isolation")
            files[relative] = (fd, _stat_signature(sealed), size, digest)
        for relative in sorted(directories, key=lambda item: item.count("/"), reverse=True):
            path = staging / relative
            os.chmod(path, 0o500, follow_symlinks=False)
            info = path.lstat()
            directories[relative] = (info.st_dev, info.st_ino, info.st_mode)
        os.fchmod(staging_fd, 0o500)
        return _TreeSeal(staging, staging_fd, files, directories)
    except BaseException:
        for fd, _signature, _size, _digest in files.values():
            os.close(fd)
        raise


def _verify_tree_seal(seal: _TreeSeal) -> None:
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for path in seal.staging.rglob("*"):
        relative = path.relative_to(seal.staging).as_posix()
        info = path.lstat()
        if stat.S_ISREG(info.st_mode):
            actual_files.add(relative)
        elif stat.S_ISDIR(info.st_mode):
            actual_directories.add(relative)
        else:
            raise SupervisorError("publication tree gained a symlink or special file")
    if actual_files != set(seal.files) or actual_directories != set(seal.directories):
        raise SupervisorError("publication tree membership changed after sealing")
    for relative, (fd, signature, size, digest) in seal.files.items():
        current = os.fstat(fd)
        current_path = (seal.staging / relative).lstat()
        if (
            _stat_signature(current) != signature
            or _stat_signature(current_path) != signature
            or current.st_nlink != 1
            or _hash_open_fd(fd, size) != (size, digest)
        ):
            raise SupervisorError("publication tree file changed after sealing")
    for relative, identity in seal.directories.items():
        current = (seal.staging / relative).lstat()
        if (current.st_dev, current.st_ino, current.st_mode) != identity:
            raise SupervisorError("publication tree directory changed after sealing")
    root = os.fstat(seal.staging_fd)
    if not stat.S_ISDIR(root.st_mode) or stat.S_IMODE(root.st_mode) != 0o500:
        raise SupervisorError("publication staging root is not read-only sealed")


def _release_tree_seal(seal: _TreeSeal, *, writable: bool) -> None:
    if writable:
        try:
            os.fchmod(seal.staging_fd, 0o700)
        except OSError:
            pass
        for relative in sorted(seal.directories, key=lambda item: item.count("/")):
            try:
                os.chmod(seal.staging / relative, 0o700, follow_symlinks=False)
            except OSError:
                pass
        for fd, _signature, _size, _digest in seal.files.values():
            try:
                os.fchmod(fd, 0o600)
            except OSError:
                pass
    for fd, _signature, _size, _digest in seal.files.values():
        try:
            os.close(fd)
        except OSError:
            pass


def _tree_seal_digest(seal: _TreeSeal, relative: str) -> tuple[int, str]:
    try:
        _fd, _signature, size, digest = seal.files[relative]
    except KeyError as exc:
        raise SupervisorError("sealed publication tree is missing an expected file") from exc
    return size, digest


def _validate_sealed_text_policy(seal: _TreeSeal) -> None:
    text_paths = {
        *_SUPERVISOR_LOGS,
        *(relative for relative in seal.files if relative.startswith("twin_plans/") and relative.endswith(".json")),
    }
    for relative in text_paths:
        try:
            fd, _signature, size, _digest = seal.files[relative]
        except KeyError as exc:
            raise SupervisorError("sealed tree is missing a required text artifact") from exc
        _validate_safe_text_bytes(_read_open_fd(fd, size))


def _verify_child_artifacts(child: dict[str, object], staging: Path, *, promoted: bool) -> None:
    for record in child["artifacts"]:
        relative = record["relative_path"]
        current_relative = _PARTIAL_PROMOTIONS.get(relative, relative) if promoted else relative
        actual = _digest_record(staging / current_relative, staging)
        if actual["bytes"] != record["bytes"] or actual["sha256"] != record["sha256"]:
            raise SupervisorError("child artifact changed after validation")
    if _regular_bytes(staging / "child_result.json") != _canonical_json_bytes(child):
        raise SupervisorError("child result changed after validation")


_PENDING_PUBLICATION_SEALS: dict[tuple[int, int, str], _TreeSeal] = {}


def _entry_exists(directory_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _regular_bytes_at(directory_fd: int, name: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise SupervisorError("text artifact cannot be opened safely") from exc
    try:
        before = os.fstat(fd)
        before_path = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or (before.st_dev, before.st_ino) != (before_path.st_dev, before_path.st_ino)
        ):
            raise SupervisorError("text artifact is not an isolated single-link regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1_048_576)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
        after = os.fstat(fd)
        after_path = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            _stat_signature(before) != _stat_signature(after)
            or _stat_signature(after) != _stat_signature(after_path)
            or len(data) != after.st_size
        ):
            raise SupervisorError("text artifact changed while being read")
        return data
    finally:
        os.close(fd)


def _validate_temporary_logs(parent_fd: int, temporary_names: tuple[str, str]) -> None:
    for name in temporary_names:
        _validate_safe_text_bytes(_regular_bytes_at(parent_fd, name))


def _validate_attached_logs(staging: Path) -> None:
    for name in _SUPERVISOR_LOGS:
        _validate_safe_text_bytes(_regular_bytes(staging / name))


def _attach_supervisor_logs(
    parent_fd: int,
    staging_fd: int,
    temporary_names: tuple[str, str],
) -> None:
    for temporary_name, artifact_name in zip(temporary_names, _SUPERVISOR_LOGS, strict=True):
        if _entry_exists(staging_fd, artifact_name):
            raise SupervisorError(f"child created reserved supervisor log name: {artifact_name}")
        source = os.stat(temporary_name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(source.st_mode) or source.st_nlink != 1:
            raise SupervisorError("supervisor log is not an isolated single-link regular file")
        os.link(
            temporary_name,
            artifact_name,
            src_dir_fd=parent_fd,
            dst_dir_fd=staging_fd,
            follow_symlinks=False,
        )
        os.unlink(temporary_name, dir_fd=parent_fd)
        attached = os.stat(artifact_name, dir_fd=staging_fd, follow_symlinks=False)
        if not stat.S_ISREG(attached.st_mode) or attached.st_nlink != 1:
            raise SupervisorError("attached supervisor log is not an isolated regular file")
    os.fsync(staging_fd)


def _attach_redacted_supervisor_logs(
    parent_fd: int,
    staging_fd: int,
    staging: Path,
    temporary_names: tuple[str, str],
) -> None:
    for temporary_name, artifact_name in zip(temporary_names, _SUPERVISOR_LOGS, strict=True):
        if _entry_exists(parent_fd, temporary_name):
            os.unlink(temporary_name, dir_fd=parent_fd)
        if _entry_exists(staging_fd, artifact_name):
            os.unlink(artifact_name, dir_fd=staging_fd)
        _write_new_file(staging / artifact_name, _SAFE_REDACTED_LOG)
    os.fsync(staging_fd)


def _sanitize_failed_text_artifacts(staging: Path) -> None:
    candidates = []
    for path in staging.rglob("*"):
        relative = path.relative_to(staging).as_posix()
        lowered = path.name.lower()
        if (
            relative in _SUPERVISOR_LOGS
            or (relative.startswith("twin_plans/") and relative.endswith(".json"))
            or "log" in lowered
            or "debug" in lowered
            or lowered.endswith(".jsonl")
        ):
            candidates.append(path)
    for path in candidates:
        relative = path.relative_to(staging).as_posix()
        try:
            _validate_safe_text_bytes(relative.encode("utf-8"))
        except SupervisorError:
            replacement = path.with_name(f"redacted-text-{hashlib.sha256(relative.encode()).hexdigest()[:16]}.txt")
            try:
                if replacement.exists() or replacement.is_symlink():
                    path.unlink()
                    continue
                path.rename(replacement)
                path = replacement
            except OSError:
                continue
        try:
            _validate_safe_text_bytes(_regular_bytes(path))
        except (OSError, SupervisorError):
            try:
                path.unlink()
                _write_new_file(path, _SAFE_REDACTED_LOG)
            except OSError:
                pass


def _evidence_error(operation: str, error: BaseException) -> str:
    return f"{operation}:{type(error).__name__}"


def _remove_invalid_success_receipt(staging_fd: int) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    recovery: dict[str, object] = {
        "attempted": False,
        "present_before": None,
        "removed": None,
        "present_after": None,
        "directory_fsync_succeeded": None,
        "tainted": True,
    }
    try:
        present_before = _entry_exists(staging_fd, "arm_receipt.json")
        recovery["present_before"] = present_before
        if present_before:
            recovery["attempted"] = True
            os.unlink("arm_receipt.json", dir_fd=staging_fd)
            recovery["removed"] = True
            try:
                os.fsync(staging_fd)
                recovery["directory_fsync_succeeded"] = True
            except BaseException as exc:
                recovery["directory_fsync_succeeded"] = False
                errors.append(_evidence_error("success_receipt_removal_fsync", exc))
        else:
            recovery["removed"] = True
            recovery["directory_fsync_succeeded"] = True
        recovery["present_after"] = _entry_exists(staging_fd, "arm_receipt.json")
        recovery["tainted"] = bool(recovery["present_after"]) or recovery["directory_fsync_succeeded"] is not True
    except BaseException as exc:
        errors.append(_evidence_error("success_receipt_removal", exc))
        try:
            recovery["present_after"] = _entry_exists(staging_fd, "arm_receipt.json")
        except BaseException as check_exc:
            errors.append(_evidence_error("success_receipt_postcheck", check_exc))
    return recovery, errors


def _write_failure_receipt_best_effort(
    staging: Path,
    payload: dict[str, object],
) -> tuple[Path | None, str, list[str]]:
    errors: list[str] = []
    receipt_path = staging / "failure_receipt.json"
    try:
        _write_new_file(receipt_path, _canonical_json_bytes(payload))
        _fsync_directory(staging)
        return receipt_path, _FAILURE_EVIDENCE_WRITTEN, errors
    except BaseException as exc:
        errors.append(_evidence_error("failure_receipt_primary", exc))
    fallback_path = staging / f"failure_receipt.fallback.{uuid.uuid4().hex}.json"
    fallback = {
        "schema_version": FAILURE_RECEIPT_SCHEMA,
        "status": "FAILED_NOT_GENERATION_INPUT",
        "arm_name": payload["arm_name"],
        "failure": payload["failure"],
        "final_absent": payload["final_absent"],
        "publication_recovery": payload["publication_recovery"],
        "success_receipt_removal": payload["success_receipt_removal"],
        "failure_evidence_errors": [*payload["failure_evidence_errors"], *errors],
        "failure_evidence_state": _FAILURE_EVIDENCE_FALLBACK,
        "partial_inventory_complete": False,
        "holds": list(_LOCAL_HOLDS),
        "success_scope": _LOCAL_SUCCESS_SCOPE,
    }
    try:
        _write_new_file(fallback_path, _canonical_json_bytes(fallback))
        _fsync_directory(staging)
        return fallback_path, _FAILURE_EVIDENCE_FALLBACK, errors
    except BaseException as exc:
        errors.append(_evidence_error("failure_receipt_fallback", exc))
        return None, _FAILURE_EVIDENCE_UNWRITABLE, errors


def supervise_arm(spec: SupervisorSpec) -> SupervisorResult:
    """Run, validate, seal, and no-replace publish one frozen ST-R3 arm."""
    _validate_spec(spec)
    final_dir = Path(os.path.abspath(spec.final_dir))
    parent = final_dir.parent
    if not parent.is_dir() or parent.resolve(strict=True) != parent:
        raise ValueError("final parent and every ancestor must be existing nonsymlink directories")
    parent_fd = os.open(
        parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    parent_identity = os.fstat(parent_fd)
    staging_name = f".{final_dir.name}.staging.{uuid.uuid4().hex}"
    os.mkdir(staging_name, mode=0o700, dir_fd=parent_fd)
    staging = parent / staging_name
    staging_fd = os.open(
        staging_name,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_fd,
    )
    child_pid: int | None = None
    child_process: subprocess.Popen[bytes] | None = None
    duration_ns: int | None = None
    exit_code: int | None = None
    term_signal: int | None = None
    raw_rss: int | float | None = None
    raw_unit: str | None = None
    rss_bytes: int | None = None
    event_bytes = bytearray()
    wait_usage = None
    failure: BaseException | None = None
    timed_out = False
    child_reaped = False
    owned_fds: set[int] = set()
    threads: list[threading.Thread] = []
    thread_errors: list[BaseException] = []
    done = threading.Event()
    temporary_logs = (
        f".{staging_name}.stdout.{uuid.uuid4().hex}",
        f".{staging_name}.stderr.{uuid.uuid4().hex}",
    )
    logs_attached = False
    logs_policy_safe = False
    logs_policy_rejected = False
    tree_seal: _TreeSeal | None = None
    publication_seal_key: tuple[int, int, str] | None = None
    publication_rollback_attempted = False
    publication_rollback_succeeded: bool | None = None
    status: int | None = None
    try:
        if _entry_exists(parent_fd, final_dir.name):
            raise FileExistsError(f"final arm path must be absent: {final_dir}")
        if os.fstat(staging_fd).st_dev != parent_identity.st_dev:
            raise SupervisorError("staging and final parent are not on the same filesystem")
        repo_root = Path(__file__).resolve().parents[3]
        child_cli = repo_root / "scripts" / "experiments" / "st_r3" / "st_r3_postproc_arm.py"
        python_executable = Path(sys.executable).absolute()
        if not python_executable.exists():
            raise SupervisorError("current Python executable is absent")
        if child_cli.is_symlink() or not child_cli.is_file():
            raise SupervisorError("fixed ST-R3 child CLI is absent or symlinked")
        event_read, event_write = _cloexec_pipe()
        owned_fds.update((event_read, event_write))
        stdout_read, stdout_write = _cloexec_pipe()
        owned_fds.update((stdout_read, stdout_write))
        stderr_read, stderr_write = _cloexec_pipe()
        owned_fds.update((stderr_read, stderr_write))
        log_fds = tuple(
            os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent_fd) for name in temporary_logs
        )
        owned_fds.update(log_fds)
        argv = [
            str(python_executable),
            str(child_cli),
            "--arm-name",
            spec.arm_name,
            "--geff-dir",
            str(spec.geff_dir.absolute()),
            "--test-dir",
            str(spec.test_dir.absolute()),
            "--deepcenter-checkpoint",
            str(spec.deepcenter_checkpoint.absolute()),
            "--deepcenter-manifest",
            str(spec.deepcenter_manifest.absolute()),
            "--expected-effective-config-sha256",
            spec.expected_effective_config_sha256,
            "--staging-dir",
            str(staging),
            "--event-fd",
            str(event_write),
        ]
        for dataset in EVAL36:
            argv.extend(("--dataset", dataset))
        environment = _child_environment()
        started_utc_ns = time.time_ns()
        started_monotonic_ns = time.monotonic_ns()
        devnull_fd = os.open(os.devnull, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        owned_fds.add(devnull_fd)
        child_process = subprocess.Popen(
            argv,
            executable=python_executable,
            stdin=devnull_fd,
            stdout=stdout_write,
            stderr=stderr_write,
            env=environment,
            close_fds=True,
            pass_fds=(event_write,),
            start_new_session=True,
        )
        child_pid = child_process.pid
        os.close(devnull_fd)
        owned_fds.remove(devnull_fd)
        os.close(event_write)
        owned_fds.remove(event_write)
        os.close(stdout_write)
        owned_fds.remove(stdout_write)
        os.close(stderr_write)
        owned_fds.remove(stderr_write)
        threads = [
            threading.Thread(
                target=_drain_pipe,
                args=(event_read, None, event_bytes, done, thread_errors, None),
                daemon=True,
            ),
            threading.Thread(
                target=_drain_pipe,
                args=(stdout_read, log_fds[0], bytearray(), done, thread_errors, _MAX_SUPERVISOR_LOG_BYTES),
                daemon=True,
            ),
            threading.Thread(
                target=_drain_pipe,
                args=(stderr_read, log_fds[1], bytearray(), done, thread_errors, _MAX_SUPERVISOR_LOG_BYTES),
                daemon=True,
            ),
        ]
        for thread, transferred in zip(
            threads,
            ((event_read,), (stdout_read, log_fds[0]), (stderr_read, log_fds[1])),
            strict=True,
        ):
            thread.start()
            owned_fds.difference_update(transferred)
        deadline = started_monotonic_ns + int(spec.timeout_seconds * 1_000_000_000)
        while True:
            waited_pid, status, wait_usage = os.wait4(child_pid, os.WNOHANG)
            if waited_pid == child_pid:
                child_reaped = True
                child_process.returncode = os.waitstatus_to_exitcode(status)
                break
            if thread_errors:
                _kill_child_process_group(child_pid)
                _, status, wait_usage = os.wait4(child_pid, 0)
                child_reaped = True
                child_process.returncode = os.waitstatus_to_exitcode(status)
                break
            if time.monotonic_ns() >= deadline:
                timed_out = True
                _kill_child_process_group(child_pid)
                _, status, wait_usage = os.wait4(child_pid, 0)
                child_reaped = True
                child_process.returncode = os.waitstatus_to_exitcode(status)
                break
            time.sleep(0.01)
        ended_monotonic_ns = time.monotonic_ns()
        ended_utc_ns = time.time_ns()
        duration_ns = ended_monotonic_ns - started_monotonic_ns
        done.set()
        for thread in threads:
            thread.join(timeout=1.0)
        if any(thread.is_alive() for thread in threads):
            raise SupervisorError("pipe drain did not reach EOF; possible detached descendant")
        if status is None:
            raise SupervisorError("wait4 returned no child status")
        if os.WIFEXITED(status):
            exit_code = os.WEXITSTATUS(status)
        elif os.WIFSIGNALED(status):
            term_signal = os.WTERMSIG(status)
        if wait_usage is None:
            raise SupervisorError("wait4 returned no resource usage")
        raw_rss, raw_unit, rss_bytes = _normalized_rss(wait_usage)
        if thread_errors:
            if any(isinstance(error, SupervisorError) and "log exceeded" in str(error) for error in thread_errors):
                logs_policy_rejected = True
            raise SupervisorError("concurrent pipe drain failed")
        try:
            _validate_temporary_logs(parent_fd, temporary_logs)
            logs_policy_safe = True
        except SupervisorError:
            logs_policy_rejected = True
            raise SupervisorError("child text output violates the safe-text policy") from None
        if timed_out:
            raise TimeoutError("authoritative child exceeded supervisor timeout")
        if exit_code != 0 or term_signal is not None:
            raise SupervisorError(f"authoritative child failed: exit={exit_code}, signal={term_signal}")
        _validate_events(bytes(event_bytes), spec.arm_name, child_pid)
        child_result = _validate_child_staging(
            staging,
            spec.arm_name,
            spec.test_dir,
            spec.expected_effective_config_sha256,
            spec.deepcenter_checkpoint.name,
            spec.deepcenter_manifest.name,
        )
        _attach_supervisor_logs(parent_fd, staging_fd, temporary_logs)
        logs_attached = True
        _verify_child_artifacts(child_result, staging, promoted=False)
        expected_artifacts = {record["relative_path"]: record for record in child_result["artifacts"]}
        promotions = _promote_partial_files(staging, expected_artifacts)
        _verify_child_artifacts(child_result, staging, promoted=True)
        _write_new_file(staging / "dataset_events.jsonl", bytes(event_bytes))
        artifact_inventory = _partial_inventory(staging, {"arm_receipt.json"})
        receipt = {
            "schema_version": ARM_RECEIPT_SCHEMA,
            "status": "LOCAL_VALIDATION_OBSERVED_WITH_HOLDS",
            "arm_name": spec.arm_name,
            "datasets": list(EVAL36),
            "child": {
                "pid": child_pid,
                "exec_same_pid": True,
                "spawn_method": "subprocess.Popen(close_fds=True,pass_fds,start_new_session=True)",
                "argv": argv,
                "environment": environment,
                "declared_fds": [0, 1, 2, event_write],
                "child_result": child_result,
            },
            "timing": {
                "clock": "time.monotonic_ns",
                "start_utc_ns": started_utc_ns,
                "end_utc_ns": ended_utc_ns,
                "start_monotonic_ns": started_monotonic_ns,
                "end_monotonic_ns": ended_monotonic_ns,
                "duration_monotonic_ns": duration_ns,
            },
            "wait4": {
                "method": "os.wait4",
                "exit_code": exit_code,
                "term_signal": term_signal,
                "ru_maxrss_raw": raw_rss,
                "ru_maxrss_raw_unit": raw_unit,
                "ru_maxrss_normalized_bytes": rss_bytes,
                "platform": sys.platform,
                "authoritative_for_rss_gate": False,
            },
            "events": {"relative_path": "dataset_events.jsonl", "records": 72, "exact_pipe_bytes": True},
            "promotions": promotions,
            "artifact_inventory": artifact_inventory,
            "publication": {"primitive": None, "no_replace": True},
            "holds": list(_LOCAL_HOLDS),
            "success_scope": _LOCAL_SUCCESS_SCOPE,
            "claims": {
                "local_child_interface_validated_at_publication_check": True,
                "publication_concurrency_exclusion_proven": False,
                "success_boolean_authorizes_production": False,
                "gt_nonvisibility_proven": False,
                "no_descendants_proven": False,
                "target_runtime_calibrated": False,
                "target_memory_calibrated": False,
                "data_ready": False,
                "scoring_performed": False,
            },
        }
        # The primitive is selected before publication but the receipt must be sealed first.
        receipt["publication"]["primitive"] = (
            "renameat2(RENAME_NOREPLACE)"
            if sys.platform.startswith("linux")
            else "renameatx_np(RENAME_EXCL)"
            if sys.platform == "darwin"
            else "HOLD_PUBLICATION_NOREPLACE_UNSUPPORTED"
        )
        receipt_bytes = _canonical_json_bytes(receipt)
        _write_new_file(staging / "arm_receipt.json", receipt_bytes)
        _fsync_directory(staging / "twin_plans")
        _fsync_directory(staging)
        _verify_child_artifacts(child_result, staging, promoted=True)
        tree_seal = _seal_tree_readonly(staging, staging_fd)
        _validate_sealed_text_policy(tree_seal)
        for record in artifact_inventory:
            if "sha256" in record and _tree_seal_digest(tree_seal, record["relative_path"]) != (
                record["bytes"],
                record["sha256"],
            ):
                raise SupervisorError("publication artifact inventory changed before sealing")
        if _tree_seal_digest(tree_seal, "arm_receipt.json") != (
            len(receipt_bytes),
            hashlib.sha256(receipt_bytes).hexdigest(),
        ):
            raise SupervisorError("arm receipt changed before publication sealing")
        for record in child_result["artifacts"]:
            relative = _PARTIAL_PROMOTIONS.get(record["relative_path"], record["relative_path"])
            if _tree_seal_digest(tree_seal, relative) != (record["bytes"], record["sha256"]):
                raise SupervisorError("child artifact changed before publication sealing")
        _verify_tree_seal(tree_seal)
        current_parent = parent.stat(follow_symlinks=False)
        if parent.resolve(strict=True) != parent or (current_parent.st_dev, current_parent.st_ino) != (
            parent_identity.st_dev,
            parent_identity.st_ino,
        ):
            raise SupervisorError("final parent identity changed before publication")
        if _entry_exists(parent_fd, final_dir.name):
            raise FileExistsError(f"final arm path collided before publication: {final_dir}")
        publication_seal_key = (parent_identity.st_dev, parent_identity.st_ino, staging_name)
        _PENDING_PUBLICATION_SEALS[publication_seal_key] = tree_seal
        _publish_directory_no_replace(parent_fd, staging_name, final_dir.name)
        _PENDING_PUBLICATION_SEALS.pop(publication_seal_key, None)
        publication_seal_key = None
        staging_name = final_dir.name
        staging = final_dir
        _release_tree_seal(tree_seal, writable=False)
        tree_seal = None
        os.close(staging_fd)
        os.close(parent_fd)
        return SupervisorResult(
            True,
            spec.arm_name,
            child_pid,
            None,
            final_dir,
            duration_ns,
            exit_code,
            term_signal,
            raw_rss,
            raw_unit,
            rss_bytes,
            None,
            None,
            final_dir / "arm_receipt.json",
            _SUCCESS_EVIDENCE_STATE,
            (),
            _LOCAL_SUCCESS_SCOPE,
            _LOCAL_HOLDS,
        )
    except BaseException as exc:
        if isinstance(exc, _PublicationPostconditionError):
            publication_rollback_attempted = True
            publication_rollback_succeeded = not exc.rollback_failed
            staging_name = exc.rollback_name if exc.rollback_name is not None else final_dir.name
            staging = parent / staging_name
            if tree_seal is not None:
                tree_seal.staging = staging
        failure = exc
    if publication_seal_key is not None:
        _PENDING_PUBLICATION_SEALS.pop(publication_seal_key, None)
        publication_seal_key = None
    if tree_seal is not None:
        _release_tree_seal(tree_seal, writable=True)
        tree_seal = None
    failure_evidence_errors: list[str] = []
    if child_pid is not None and child_pid > 0 and not child_reaped:
        try:
            _kill_child_process_group(child_pid)
        except BaseException as kill_exc:
            failure_evidence_errors.append(_evidence_error("child_group_kill", kill_exc))
        try:
            _, cleanup_status, cleanup_usage = os.wait4(child_pid, 0)
            child_reaped = True
            status = cleanup_status
            wait_usage = cleanup_usage
            if child_process is not None:
                child_process.returncode = os.waitstatus_to_exitcode(status)
            if os.WIFEXITED(status):
                exit_code = os.WEXITSTATUS(status)
            elif os.WIFSIGNALED(status):
                term_signal = os.WTERMSIG(status)
            if raw_rss is None:
                raw_rss, raw_unit, rss_bytes = _normalized_rss(wait_usage)
        except BaseException as reap_exc:
            failure_evidence_errors.append(_evidence_error("child_reap", reap_exc))
    done.set()
    for fd in tuple(owned_fds):
        try:
            os.close(fd)
        except BaseException as close_exc:
            failure_evidence_errors.append(_evidence_error("owned_fd_close", close_exc))
        owned_fds.discard(fd)
    for thread in threads:
        try:
            thread.join(timeout=1.0)
        except BaseException as join_exc:
            failure_evidence_errors.append(_evidence_error("drain_thread_join", join_exc))
    if logs_attached:
        try:
            _validate_attached_logs(staging)
        except BaseException as log_exc:
            logs_policy_rejected = True
            failure_evidence_errors.append(_evidence_error("attached_log_validation", log_exc))
            try:
                _attach_redacted_supervisor_logs(parent_fd, staging_fd, staging, temporary_logs)
            except BaseException as redact_exc:
                failure_evidence_errors.append(_evidence_error("attached_log_redaction", redact_exc))
    try:
        temporary_logs_exist = all(_entry_exists(parent_fd, name) for name in temporary_logs)
    except BaseException as log_check_exc:
        temporary_logs_exist = False
        failure_evidence_errors.append(_evidence_error("temporary_log_presence", log_check_exc))
    if not logs_attached and temporary_logs_exist:
        if not logs_policy_safe and not logs_policy_rejected:
            try:
                _validate_temporary_logs(parent_fd, temporary_logs)
                logs_policy_safe = True
            except BaseException as log_exc:
                logs_policy_rejected = True
                failure_evidence_errors.append(_evidence_error("temporary_log_validation", log_exc))
        if logs_policy_rejected:
            try:
                _attach_redacted_supervisor_logs(parent_fd, staging_fd, staging, temporary_logs)
                logs_attached = True
            except BaseException as log_exc:
                failure_evidence_errors.append(_evidence_error("temporary_log_redaction", log_exc))
        else:
            try:
                _attach_supervisor_logs(parent_fd, staging_fd, temporary_logs)
                logs_attached = True
            except BaseException as log_exc:
                failure_evidence_errors.append(_evidence_error("temporary_log_attachment", log_exc))
                try:
                    _attach_redacted_supervisor_logs(parent_fd, staging_fd, staging, temporary_logs)
                    logs_attached = True
                except BaseException as redact_exc:
                    failure_evidence_errors.append(_evidence_error("temporary_log_fallback_redaction", redact_exc))
    success_receipt_removal, removal_errors = _remove_invalid_success_receipt(staging_fd)
    failure_evidence_errors.extend(removal_errors)
    try:
        _sanitize_failed_text_artifacts(staging)
    except BaseException as sanitize_exc:
        failure_evidence_errors.append(_evidence_error("failed_text_sanitization", sanitize_exc))
    try:
        partial_inventory = _partial_inventory(staging, {"failure_receipt.json"}, strict=False)
        partial_inventory_complete = True
    except BaseException as inventory_exc:
        partial_inventory = []
        partial_inventory_complete = False
        failure_evidence_errors.append(_evidence_error("partial_inventory", inventory_exc))
    try:
        final_present: bool | None = _entry_exists(parent_fd, final_dir.name)
    except BaseException as final_check_exc:
        final_present = None
        failure_evidence_errors.append(_evidence_error("final_presence", final_check_exc))
    failure_type = type(failure).__name__
    failure_message = _safe_failure_message(failure)
    failure_payload = {
        "schema_version": FAILURE_RECEIPT_SCHEMA,
        "status": "FAILED_NOT_GENERATION_INPUT",
        "arm_name": spec.arm_name,
        "failure": {"type": failure_type, "message": failure_message},
        "child_pid": child_pid,
        "duration_monotonic_ns": duration_ns,
        "exit_code": exit_code,
        "term_signal": term_signal,
        "ru_maxrss_raw": raw_rss,
        "ru_maxrss_raw_unit": raw_unit,
        "ru_maxrss_normalized_bytes": rss_bytes,
        "final_absent": None if final_present is None else not final_present,
        "publication_recovery": {
            "rollback_attempted": publication_rollback_attempted,
            "rollback_succeeded": publication_rollback_succeeded,
            "final_present": final_present,
        },
        "success_receipt_removal": success_receipt_removal,
        "failure_evidence_errors": failure_evidence_errors,
        "failure_evidence_state": _FAILURE_EVIDENCE_WRITTEN,
        "partial_inventory": partial_inventory,
        "partial_inventory_complete": partial_inventory_complete,
        "holds": list(_LOCAL_HOLDS),
        "success_scope": _LOCAL_SUCCESS_SCOPE,
    }
    receipt_path, failure_evidence_state, write_errors = _write_failure_receipt_best_effort(staging, failure_payload)
    failure_evidence_errors.extend(write_errors)
    try:
        os.close(staging_fd)
    except OSError as close_exc:
        failure_evidence_errors.append(_evidence_error("staging_fd_close", close_exc))
    try:
        os.close(parent_fd)
    except OSError as close_exc:
        failure_evidence_errors.append(_evidence_error("parent_fd_close", close_exc))
    return SupervisorResult(
        False,
        spec.arm_name,
        child_pid,
        staging,
        final_dir,
        duration_ns,
        exit_code,
        term_signal,
        raw_rss,
        raw_unit,
        rss_bytes,
        failure_type,
        failure_message,
        receipt_path,
        failure_evidence_state,
        tuple(failure_evidence_errors),
        _LOCAL_SUCCESS_SCOPE,
        _LOCAL_HOLDS,
    )


__all__ = ["EVAL36", "SupervisorResult", "SupervisorSpec", "supervise_arm"]
