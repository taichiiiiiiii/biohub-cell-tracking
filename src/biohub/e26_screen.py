"""E26 config construction, exact screening gates and generation-output checks.

This module provides helpers to build ``PostprocConfig`` instances for the
three E26 arms (``public4_parity``, ``baseline``, ``candidate``) and to
validate that a baseline/candidate pair differs only in the expected
``OUTPUT_MOTION_RELINK`` flag.

The candidate arm is identified by :data:`CANDIDATE_ID` and disables motion
relinking via ``BIOHUB_OUTPUT_MOTION_RELINK="0"``. All arms use the existing
``build_config`` factory from ``biohub.public_postproc.config`` with explicit
path overrides for the DeepCenter checkpoint/manifest variables.

Statistics and gates are pure; CSV validation opens only its explicit input.
Input registration binds canonical bytes and separates opaque GT registration
from generation-side verification. Serial generation calls the committed core;
staged official scoring opens GT only after generation verification.
"""
from __future__ import annotations

import csv
import dataclasses
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import random
import re
import resource
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from numbers import Real
from pathlib import Path

from biohub.public_postproc.config import PostprocConfig, build_config


class E26Error(RuntimeError):
    """Raised when an E26 screening operation encounters invalid input."""


CANDIDATE_ID: str = "e23_motion_relink_off_v1"

ARM_ORDER: tuple[str, ...] = ("public4_parity", "baseline", "candidate")

GATE_INPUT_SCHEMA = "biohub.e26_screen.gate_input.v1"
GATE_RESULT_SCHEMA = "biohub.e26_screen.gate_result.v1"

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

_STAGE_VIDEOS = {"eval12": EVAL12, "eval24": EVAL24, "eval36": EVAL36}
_GATE_THRESHOLDS = {
    "eval12": (
        ("paired_mean", 0.005),
        ("paired_median", 0.0),
        ("paired_worst", -0.002),
        ("aggregate_adj_edge", -0.002),
        ("lineage_44b6_score", 0.0),
        ("lineage_6bba_score", 0.0),
    ),
    "eval24": (
        ("paired_mean", 0.003),
        ("paired_median", 0.0),
        ("paired_worst", -0.002),
        ("aggregate_adj_edge", -0.002),
        ("lineage_44b6_score", 0.0),
        ("lineage_6bba_score", 0.0),
    ),
    "eval36": (
        ("aggregate_adj_edge", 0.0),
        ("aggregate_score", 0.0),
        ("aggregate_division_jaccard", 0.0),
        ("paired_median", 0.0),
        ("paired_worst", -0.002),
        ("lineage_44b6_score", 0.0),
        ("lineage_6bba_score", 0.0),
    ),
}


def _require_finite_number(value: object, label: str, *, json_number: bool = False) -> None:
    valid_type = type(value) in (int, float) if json_number else isinstance(value, Real)
    if isinstance(value, bool) or not valid_type:
        raise E26Error(f"{label} must be a finite real number excluding bool")
    try:
        finite = math.isfinite(value)
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise E26Error(f"{label} cannot be represented as a finite number") from exc
    if not finite:
        raise E26Error(f"{label} must be finite")


def paired_statistics(values: Sequence[Real]) -> dict[str, Real]:
    """Compute unrounded paired video deltas; never discard invalid observations."""
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise E26Error("values must be a nonempty sequence of finite real numbers")
    if not values:
        raise E26Error("values must be nonempty")
    for index, value in enumerate(values):
        _require_finite_number(value, f"values[{index}]")
    try:
        n = len(values)
        ordered = sorted(values)
        center = n // 2
        median = ordered[center] if n % 2 else math.fsum(ordered[center - 1:center + 1]) / 2
        result = {"n": n, "mean": math.fsum(values) / n, "median": median, "worst": min(values)}
        for name, value in result.items():
            _require_finite_number(value, name)
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise E26Error("paired statistics arithmetic failed") from exc
    return result


def _require_keys(value: object, keys: set[str], label: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise E26Error(f"{label} must be a dict with exactly keys {sorted(keys)}")
    return value


def _gate_record(name: str, value: Real, threshold: float) -> dict:
    """One inclusive, exact comparison; inputs are validated before this is called."""
    return {"name": name, "value": value, "threshold": threshold, "passed": bool(value >= threshold)}


def evaluate_gate(stage: str, payload: dict) -> dict:
    """Screen already-scored rows. This pure API does not certify their provenance.

    Malformed data is an error, distinct from scientific rejection. All input,
    including non-gated diagnostics, is validated before any gate is evaluated.
    A pass never authorizes submission or adoption.
    """
    if type(stage) is not str or stage not in _STAGE_VIDEOS:
        raise E26Error("stage must be eval12, eval24 or eval36")
    payload = _require_keys(payload, {"schema_version", "stage", "per_video", "aggregate_deltas"}, "payload")
    if (
        type(payload["schema_version"]) is not str
        or type(payload["stage"]) is not str
        or payload["schema_version"] != GATE_INPUT_SCHEMA
        or payload["stage"] != stage
    ):
        raise E26Error("payload schema_version or stage does not match")
    videos = _STAGE_VIDEOS[stage]
    rows = payload["per_video"]
    if type(rows) is not list or len(rows) != len(videos):
        raise E26Error(f"per_video must be an ordered list of exactly {len(videos)} rows")
    deltas = []
    for index, (row, video) in enumerate(zip(rows, videos, strict=True)):
        row = _require_keys(row, {"dataset", "combined_score_delta"}, f"per_video[{index}]")
        if type(row["dataset"]) is not str or row["dataset"] != video:
            raise E26Error(f"per_video[{index}] dataset must be {video}")
        _require_finite_number(row["combined_score_delta"], f"per_video[{index}] delta", json_number=True)
        deltas.append(row["combined_score_delta"])

    aggregates = _require_keys(payload["aggregate_deltas"], {stage, "44b6", "6bba"}, "aggregate_deltas")
    for group in (stage, "44b6", "6bba"):
        metrics = _require_keys(
            aggregates[group], {"score", "adj_edge_jaccard", "division_jaccard"}, f"aggregate_deltas.{group}"
        )
        for metric in ("score", "adj_edge_jaccard", "division_jaccard"):
            value = metrics[metric]
            if metric == "division_jaccard" and value is None and not (stage == "eval36" and group == stage):
                continue
            _require_finite_number(value, f"aggregate_deltas.{group}.{metric}", json_number=True)

    stats = paired_statistics(deltas)
    values = {
        "paired_mean": stats["mean"],
        "paired_median": stats["median"],
        "paired_worst": stats["worst"],
        "aggregate_adj_edge": aggregates[stage]["adj_edge_jaccard"],
        "aggregate_score": aggregates[stage]["score"],
        "aggregate_division_jaccard": aggregates[stage]["division_jaccard"],
        "lineage_44b6_score": aggregates["44b6"]["score"],
        "lineage_6bba_score": aggregates["6bba"]["score"],
    }
    gates = [_gate_record(name, values[name], threshold) for name, threshold in _GATE_THRESHOLDS[stage]]
    first_failure = next((gate["name"] for gate in gates if not gate["passed"]), None)
    if first_failure is not None:
        status = f"SCREEN_REJECT_{stage.upper()}"
    elif stage == "eval36":
        status = "SCREEN_PASS_REQUIRES_CONFIRMATION"
    else:
        status = f"SCREEN_{stage.upper()}_PASS"
    return {
        "schema_version": GATE_RESULT_SCHEMA,
        "candidate_id": CANDIDATE_ID,
        "stage": stage,
        "paired_statistics": stats,
        "gates": gates,
        "first_failure": first_failure,
        "status": status,
        "submission_authorized": False,
    }

# The four explicit string path overrides applied identically across all arms.
_DEEPCENTER_OVERRIDES_KEYS: tuple[str, ...] = (
    "BIOHUB_DEEPCENTER_CHECKPOINT",
    "BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT",
    "BIOHUB_DEEPCENTER_MANIFEST",
    "BIOHUB_DEEPCENTER_MANIFEST_DEFAULT",
)


def build_arm_config(arm: str, image_root: Path, checkpoint: Path, manifest: Path) -> PostprocConfig:
    """Build a ``PostprocConfig`` for the given E26 arm.

    Parameters
    ----------
    arm:
        One of :data:`ARM_ORDER`.  All three arms use the ``e23`` profile;
        ``public4_parity`` may use a different image root but shares the same
        preset configuration as baseline and candidate.
    image_root:
        Root directory for images (passed as ``test_dir`` to ``build_config``).
    checkpoint:
        Path used for ``BIOHUB_DEEPCENTER_CHECKPOINT`` and
        ``BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT``.
    manifest:
        Path used for ``BIOHUB_DEEPCENTER_MANIFEST`` and
        ``BIOHUB_DEEPCENTER_MANIFEST_DEFAULT``.

    Returns
    -------
    PostprocConfig
        The constructed configuration.

    Raises
    ------
    E26Error
        If *arm* is not a recognised value or any argument has the wrong type.
    """
    if not isinstance(arm, str):
        raise E26Error(f"arm must be a str, got {type(arm).__name__}")
    if arm not in ARM_ORDER:
        raise E26Error(f"unknown arm {arm!r}; expected one of {ARM_ORDER}")
    if not isinstance(image_root, Path):
        raise E26Error(f"image_root must be a Path, got {type(image_root).__name__}")
    if not isinstance(checkpoint, Path):
        raise E26Error(f"checkpoint must be a Path, got {type(checkpoint).__name__}")
    if not isinstance(manifest, Path):
        raise E26Error(f"manifest must be a Path, got {type(manifest).__name__}")

    checkpoint_str = str(checkpoint)
    manifest_str = str(manifest)

    base_overrides: dict[str, str] = {
        "BIOHUB_DEEPCENTER_CHECKPOINT": checkpoint_str,
        "BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT": checkpoint_str,
        "BIOHUB_DEEPCENTER_MANIFEST": manifest_str,
        "BIOHUB_DEEPCENTER_MANIFEST_DEFAULT": manifest_str,
    }

    if arm == "candidate":
        overrides = dict(base_overrides)
        overrides["BIOHUB_OUTPUT_MOTION_RELINK"] = "0"
    else:
        # public4_parity and baseline both use e23 profile
        overrides = dict(base_overrides)

    return build_config(overrides=overrides, test_dir=image_root, profile="e23")


def validate_config_pair(
    baseline: PostprocConfig,
    candidate: PostprocConfig,
    *,
    image_root: Path,
    checkpoint: Path,
    manifest: Path,
) -> None:
    """Validate that *baseline* and *candidate* form a correct E26 pair.

    The function rebuilds the expected baseline and candidate configs from the
    supplied path arguments using the exact same logic as
    :func:`build_arm_config`, then compares every field of the actual
    ``PostprocConfig`` objects against the expected ones.

    The only permitted difference between baseline and candidate is that
    ``OUTPUT_MOTION_RELINK`` must be ``True`` in the baseline and ``False`` in
    the candidate.  Additionally, ``OUTPUT_STEAL_TWIN_REWIRE`` must be literal
    ``False`` in both configs.

    Parameters
    ----------
    baseline:
        The actual baseline ``PostprocConfig``.
    candidate:
        The actual candidate ``PostprocConfig``.
    image_root:
        Image root used to build the expected configs.
    checkpoint:
        Checkpoint path used to build the expected configs.
    manifest:
        Manifest path used to build the expected configs.

    Raises
    ------
    E26Error
        If the pair does not match the expected contract.
    """
    if not isinstance(baseline, PostprocConfig):
        raise E26Error(f"baseline must be a PostprocConfig, got {type(baseline).__name__}")
    if not isinstance(candidate, PostprocConfig):
        raise E26Error(f"candidate must be a PostprocConfig, got {type(candidate).__name__}")
    if not isinstance(image_root, Path):
        raise E26Error(f"image_root must be a Path, got {type(image_root).__name__}")
    if not isinstance(checkpoint, Path):
        raise E26Error(f"checkpoint must be a Path, got {type(checkpoint).__name__}")
    if not isinstance(manifest, Path):
        raise E26Error(f"manifest must be a Path, got {type(manifest).__name__}")

    expected_baseline = build_arm_config("baseline", image_root, checkpoint, manifest)
    expected_candidate = build_arm_config("candidate", image_root, checkpoint, manifest)

    # Check motion relink values first before full-field comparison
    if baseline.OUTPUT_MOTION_RELINK is not True:
        raise E26Error(
            f"baseline OUTPUT_MOTION_RELINK must be True, got {baseline.OUTPUT_MOTION_RELINK!r}"
        )
    if candidate.OUTPUT_MOTION_RELINK is not False:
        raise E26Error(
            f"candidate OUTPUT_MOTION_RELINK must be False, got {candidate.OUTPUT_MOTION_RELINK!r}"
        )

    # Both must have OUTPUT_STEAL_TWIN_REWIRE == False
    if baseline.OUTPUT_STEAL_TWIN_REWIRE is not False:
        raise E26Error(
            f"baseline OUTPUT_STEAL_TWIN_REWIRE must be False, got {baseline.OUTPUT_STEAL_TWIN_REWIRE!r}"
        )
    if candidate.OUTPUT_STEAL_TWIN_REWIRE is not False:
        raise E26Error(
            f"candidate OUTPUT_STEAL_TWIN_REWIRE must be False, got {candidate.OUTPUT_STEAL_TWIN_REWIRE!r}"
        )

    _assert_configs_equal(baseline, expected_baseline, label="baseline")
    _assert_configs_equal(candidate, expected_candidate, label="candidate")


def _assert_configs_equal(actual: PostprocConfig, expected: PostprocConfig, label: str) -> None:
    """Assert that two ``PostprocConfig`` instances are identical field-by-field.

    This performs strict type-aware comparison: ``bool`` values must match
    exactly (``True`` is not equal to ``1`` for our purposes), and all other
    fields must also match in both value and type.

    Raises
    ------
    E26Error
        If any field differs.
    """
    for field in dataclasses.fields(PostprocConfig):
        name = field.name
        actual_val = getattr(actual, name)
        expected_val = getattr(expected, name)

        # Strict type check: bool vs int must not pass.
        if type(actual_val) is not type(expected_val):
            raise E26Error(
                f"{label} field {name}: type mismatch — "
                f"expected {type(expected_val).__name__}, got {type(actual_val).__name__}"
            )

        if actual_val != expected_val:
            raise E26Error(
                f"{label} field {name}: value mismatch — "
                f"expected {expected_val!r}, got {actual_val!r}"
            )


# Unit03 output validation. Generation supervision and sealing are separate.
_E26_CSV_COLUMNS = ("id", "dataset", "row_type", "node_id", "t", "z", "y", "x", "source_id", "target_id")
_E26_CSV_INTEGERS = ("id", "node_id", "t", "z", "y", "x", "source_id", "target_id")


def validate_generated_csv(
    csv_path: Path, *, datasets: tuple[str, ...], shapes: dict[str, tuple[int, int, int, int]]
) -> dict:
    """Reparse exact E26 CSV structure, then use the existing graph validator.

    Only the supplied dataset shapes are used; no image/GT discovery or repair.
    Numerical imports are deferred for the future generation child's environment
    setup. This content check alone is not a generation seal or provenance proof.
    """
    if not isinstance(csv_path, Path):
        raise E26Error("csv_path must be a Path")
    if (
        type(datasets) is not tuple or not datasets
        or any(type(name) is not str or not name for name in datasets)
        or len(set(datasets)) != len(datasets)
    ):
        raise E26Error("datasets must be a nonempty ordered tuple of unique names")
    _require_keys(shapes, set(datasets), "shapes")
    for name, shape in shapes.items():
        if type(shape) is not tuple or len(shape) != 4 or any(type(v) is not int or v <= 0 for v in shape):
            raise E26Error(f"{name}: shape must contain four positive integer TZYX sizes")

    import polars as pl

    from biohub.validate import SubmissionError, validate_submission

    try:
        if csv_path.is_symlink() or not csv_path.is_file():
            raise E26Error("CSV must be a regular non-symlink file")
        before = csv_path.stat()
        row_count = 0
        block_index = -1
        current = None
        in_edges = False
        seen_edges = set()
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            if next(reader, None) != list(_E26_CSV_COLUMNS):
                raise E26Error("CSV must have the exact ordered 10-column header")
            for cells in reader:
                if len(cells) != len(_E26_CSV_COLUMNS) or any(cell == "" for cell in cells):
                    raise E26Error(f"CSV row {row_count}: wrong width or missing cell")
                row = dict(zip(_E26_CSV_COLUMNS, cells, strict=True))
                integers = {}
                for field in _E26_CSV_INTEGERS:
                    if re.fullmatch(r"-?[0-9]+", row[field]) is None:
                        raise E26Error(f"CSV row {row_count}: {field} must be an integer")
                    value = int(row[field])
                    if not -(2**63) <= value < 2**63:
                        raise E26Error(f"CSV row {row_count}: {field} outside Int64 range")
                    integers[field] = value
                if integers["id"] != row_count:
                    raise E26Error("CSV global row IDs must be contiguous from zero")
                dataset = row["dataset"]
                if dataset != current:
                    block_index += 1
                    if block_index >= len(datasets) or dataset != datasets[block_index]:
                        raise E26Error("CSV dataset blocks must follow the exact selected order")
                    current, in_edges = dataset, False
                    seen_edges.clear()
                if row["row_type"] == "node":
                    if in_edges:
                        raise E26Error(f"{dataset}: nodes must precede edges")
                    if integers["node_id"] < 0 or integers["source_id"] != -1 or integers["target_id"] != -1:
                        raise E26Error(f"{dataset}: invalid node ID or node endpoint sentinels")
                elif row["row_type"] == "edge":
                    in_edges = True
                    if any(integers[field] != -1 for field in ("node_id", "t", "z", "y", "x")):
                        raise E26Error(f"{dataset}: invalid edge node/coordinate sentinels")
                    edge = (integers["source_id"], integers["target_id"])
                    if min(edge) < 0 or edge in seen_edges:
                        raise E26Error(f"{dataset}: negative endpoint or duplicate edge pair")
                    seen_edges.add(edge)
                else:
                    raise E26Error(f"{dataset}: row_type must be node or edge")
                row_count += 1
        if block_index != len(datasets) - 1:
            raise E26Error("CSV does not contain every selected dataset")
        frame = pl.read_csv(
            csv_path,
            schema_overrides={
                field: pl.Int64 if field in _E26_CSV_INTEGERS else pl.String for field in _E26_CSV_COLUMNS
            },
        )
        report = validate_submission(frame, shapes)
        after = csv_path.stat()
        stat_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, key) != getattr(after, key) for key in stat_fields):
            raise E26Error("CSV changed during validation")
        if frame.height != row_count:
            raise E26Error("CSV row counts differ between reparsers")
        return {
            "datasets": list(datasets),
            "total_rows": row_count,
            "total_nodes": sum(counts["nodes"] for counts in report.values()),
            "total_edges": sum(counts["edges"] for counts in report.values()),
            "per_dataset": [{"dataset": name, **report[name]} for name in datasets],
        }
    except (OSError, UnicodeError, csv.Error, ValueError, pl.exceptions.PolarsError) as exc:
        # SubmissionError is ValueError, but explicitly distinguish its provenance.
        operation = "structural validation" if isinstance(exc, SubmissionError) else "CSV parsing"
        raise E26Error(f"{operation} failed: {exc}") from exc

PUBLIC4 = ("44b6_0113de3b", "44b6_0b24845f", "6bba_05b6850b", "6bba_05db0fb1")
_RAW_COUNTER_KEYS = frozenset((
    "raw_edges",
    "dropped_nonconsecutive_edges",
    "dropped_long_edges",
    "dropped_multi_parent_edges",
    "dropped_multi_child_edges",
    "dropped_division_edges",
    "gap_candidates",
    "gap_pairs_selected",
    "gap_reused_existing",
    "gap_inserted_synthetic",
    "gap_added_nodes",
    "gap_added_edges",
    "gap_skipped_node_cap",
    "gap_density_nodes_scored",
    "gap_density_candidates_expanded",
    "gap_density_candidates_restricted",
    "gap_density_selected_outside_base",
    "gap_density_step_delta_milli_sum",
    "gap_refined_synthetic",
    "gap_refine_failed",
    "gap_refine_rejected_shift",
    "centroid_refine_examined",
    "centroid_refine_moved",
    "centroid_refine_no_signal",
    "centroid_refine_rejected_shift",
    "pruned_isolated_nodes",
    "motion_relink_edges",
    "motion_relink_tight_edges",
    "motion_relink_relaxed_edges",
    "motion_relink_frames",
    "motion_relink_replaced_raw_edges",
    "motion_relink_fallback_raw",
    "motion_relink_skipped_large_frame",
    "gap2_candidates",
    "gap2_pairs_selected",
    "gap2_added_nodes",
    "gap2_added_edges",
    "gap2_skipped_cap",
    "safe_division_candidates",
    "safe_division_geometric_candidates",
    "safe_divisions_added",
    "safe_division_skipped_cap",
    "safe_division_mutual_nn_rejected",
    "safe_division_divergence_rejected",
    "deepcenter_gap_checked",
    "deepcenter_gap_bypassed_strong_motion",
    "deepcenter_gap_bypassed_observed_node",
    "deepcenter_gap_accepted",
    "deepcenter_gap_rejected",
    "deepcenter_gap_missing",
    "deepcenter_safe_div_checked",
    "deepcenter_safe_div_accepted",
    "deepcenter_safe_div_rejected",
    "deepcenter_safe_div_missing",
    "short_track_components_removed",
    "short_track_nodes_removed",
    "short_track_edges_removed",
    "short_track_filter_skipped_all",
    "short_track_rescue_triggered",
    "short_track_rescue_components",
    "short_track_rescue_nodes",
    "short_track_rescue_budget",
    "linefit_smoothed_nodes",
    "linefit_skipped_nodes",
    "steal_twin_examined_frames",
    "steal_twin_p_pool",
    "steal_twin_q_pool",
    "steal_twin_enumerated",
    "steal_twin_rejected_distance_twin",
    "steal_twin_rejected_ambiguous_p_nn",
    "steal_twin_rejected_ambiguous_q_nn",
    "steal_twin_rejected_not_mutual_parent_nn",
    "steal_twin_rejected_distance_existing_child",
    "steal_twin_rejected_distance_parent",
    "steal_twin_rejected_distance_sister_low",
    "steal_twin_rejected_distance_sister_high",
    "steal_twin_rejected_time",
    "steal_twin_rejected_missing_successor",
    "steal_twin_rejected_shared_successor",
    "steal_twin_rejected_divergence",
    "steal_twin_rejected_synthetic",
    "steal_twin_rejected_deepcenter_bundle",
    "steal_twin_rejected_deepcenter_dataset",
    "steal_twin_rejected_deepcenter_frame",
    "steal_twin_rejected_deepcenter_heatmap",
    "steal_twin_rejected_deepcenter_nonfinite",
    "steal_twin_rejected_deepcenter_threshold",
    "steal_twin_eligible",
    "steal_twin_rejected_conflict",
    "steal_twin_rejected_frame_cap",
    "steal_twin_rejected_video_cap",
    "steal_twin_accepted",
    "steal_twin_planned_edges_removed",
    "steal_twin_planned_edges_added",
    "steal_twin_edges_removed",
    "steal_twin_edges_added",
    "steal_twin_isolated_donors",
    "steal_twin_validation_failed",
    "steal_twin_validation_missing_node_field",
    "steal_twin_validation_invalid_node_id",
    "steal_twin_validation_duplicate_node_id",
    "steal_twin_validation_invalid_node_time",
    "steal_twin_validation_nonfinite_node_coordinate",
    "steal_twin_validation_invalid_edge_endpoint",
    "steal_twin_validation_dangling_edge",
    "steal_twin_validation_duplicate_edge",
    "steal_twin_validation_nonconsecutive_edge",
    "steal_twin_validation_indegree",
    "steal_twin_validation_outdegree",
    "steal_twin_validation_nonfinite_edge_distance",
    "steal_twin_debug_records_written",
    "steal_twin_debug_records_dropped",
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
))
_RAW_RATIO_KEYS = frozenset(("edge_to_node_ratio", "gap_added_nodes_frac"))
_RAW_REQUIRED_KEYS = _RAW_COUNTER_KEYS | _RAW_RATIO_KEYS | {
    "dataset", "raw_nodes", "nodes", "edges", "division_like_sources",
}
_MOTION_COUNTER_KEYS = (
    "motion_relink_edges", "motion_relink_tight_edges", "motion_relink_relaxed_edges",
    "motion_relink_frames", "motion_relink_replaced_raw_edges", "motion_relink_fallback_raw",
    "motion_relink_skipped_large_frame",
)


def _require_count(value: object, label: str, *, signed: bool = False) -> None:
    if type(value) is not int or (not signed and value < 0):
        raise E26Error(f"{label} must be a {'signed' if signed else 'nonnegative'} integer excluding bool")


def validate_raw_statistics(raw_rows: list[dict], *, arm: str, csv_report: dict) -> list[dict]:
    """Validate every raw counter before adding explicit optional-key diagnostics.

    The caller must retain the original raw mappings as well as this normalized
    result. No pandas conversion, GT access or graph-size equality between arms.
    The generation supervisor must separately bind the CSV report to actual bytes.
    """
    if type(arm) is not str or arm not in ARM_ORDER:
        raise E26Error("unknown generation arm")
    datasets = PUBLIC4 if arm == "public4_parity" else EVAL36
    _require_keys(csv_report, {"datasets", "total_rows", "total_nodes", "total_edges", "per_dataset"}, "csv_report")
    if (
        type(csv_report["datasets"]) is not list
        or any(type(name) is not str for name in csv_report["datasets"])
        or csv_report["datasets"] != list(datasets)
    ):
        raise E26Error("CSV report dataset order differs from generation arm")
    counts = csv_report["per_dataset"]
    if type(counts) is not list or len(counts) != len(datasets):
        raise E26Error("CSV report per_dataset count mismatch")
    for index, (row, name) in enumerate(zip(counts, datasets, strict=True)):
        _require_keys(row, {"dataset", "nodes", "edges", "forks"}, f"csv_report[{index}]")
        if type(row["dataset"]) is not str or row["dataset"] != name:
            raise E26Error("CSV report per_dataset order mismatch")
        for key in ("nodes", "edges", "forks"):
            _require_count(row[key], f"{name}.{key}")
        if row["nodes"] == 0:
            raise E26Error(f"{name}: CSV report has no nodes")
    for total, field in (("total_nodes", "nodes"), ("total_edges", "edges")):
        _require_count(csv_report[total], total)
        if csv_report[total] != sum(row[field] for row in counts):
            raise E26Error(f"CSV report {total} is inconsistent")
    _require_count(csv_report["total_rows"], "total_rows")
    if csv_report["total_rows"] != csv_report["total_nodes"] + csv_report["total_edges"]:
        raise E26Error("CSV report total_rows is inconsistent")
    if type(raw_rows) is not list or len(raw_rows) != len(datasets):
        raise E26Error("raw statistics must contain exactly one row per selected dataset")

    normalized = []
    optional = "gap_close_effective_max_gap"
    for index, (row, dataset, count) in enumerate(zip(raw_rows, datasets, counts, strict=True)):
        if type(row) is not dict or set(row) not in (_RAW_REQUIRED_KEYS, _RAW_REQUIRED_KEYS | {optional}):
            raise E26Error(f"raw statistics[{index}]: missing or unexpected keys")
        if type(row["dataset"]) is not str or row["dataset"] != dataset:
            raise E26Error("raw statistics dataset order mismatch")
        for key, value in row.items():
            if key == "dataset":
                continue
            if key in _RAW_RATIO_KEYS:
                _require_finite_number(value, f"{dataset}.{key}", json_number=True)
                if value < 0:
                    raise E26Error(f"{dataset}.{key} must be nonnegative")
            else:
                _require_count(value, f"{dataset}.{key}", signed=key == "gap_density_step_delta_milli_sum")
        for raw_key, csv_key in (("nodes", "nodes"), ("edges", "edges"), ("division_like_sources", "forks")):
            if row[raw_key] != count[csv_key]:
                raise E26Error(f"{dataset}: {raw_key} differs from reparsed CSV")
        if row["motion_relink_tight_edges"] + row["motion_relink_relaxed_edges"] != row["motion_relink_edges"]:
            raise E26Error(f"{dataset}: motion edge component counts differ")
        fallback = row["motion_relink_fallback_raw"]
        skipped = row["motion_relink_skipped_large_frame"]
        motion_edges = row["motion_relink_edges"]
        replaced = row["motion_relink_replaced_raw_edges"]
        if fallback not in (0, 1) or skipped not in (0, 1):
            raise E26Error(f"{dataset}: motion fallback/skip must be binary")
        if arm == "candidate":
            if any(row[key] != 0 for key in _MOTION_COUNTER_KEYS):
                raise E26Error(f"{dataset}: candidate motion counters must all be zero")
        elif fallback != int(motion_edges == 0):
            raise E26Error(f"{dataset}: enabled motion fallback inconsistent with edge count")
        if skipped and (motion_edges != 0 or fallback != 1):
            raise E26Error(f"{dataset}: skipped-large motion must fall back with zero motion edges")
        if fallback and replaced != 0:
            raise E26Error(f"{dataset}: fallback cannot replace raw edges")
        if replaced > row["raw_edges"]:
            raise E26Error(f"{dataset}: motion replacement exceeds raw edges")
        output = dict(row)
        output["gap_close_effective_max_gap_absence_reason"] = None if optional in row else "not_emitted_by_core"
        if optional not in row:
            output[optional] = None
        normalized.append(output)
    return normalized


INVENTORY_SCHEMA = "biohub.e26_screen.inventory.v1"
_STAT_KEYS = ("device", "inode", "mode", "size", "mtime_ns", "ctime_ns")


def _stat_record(value: os.stat_result) -> dict[str, int]:
    return dict(zip(_STAT_KEYS, (
        value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns,
    ), strict=True))


def _absolute_path(path: Path, label: str) -> Path:
    if (
        not isinstance(path, Path) or not path.is_absolute()
        or ".." in path.parts or path == Path(path.anchor)
    ):
        raise E26Error(f"{label} must be an explicit absolute non-root Path without traversal")
    return path


def _require_sha256(value: object, label: str) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise E26Error(f"{label} must be a lowercase SHA256 digest")


def _json_bytes(value: object) -> bytes:
    def check(item: object) -> None:
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                check(child)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                check(child)
            return
        raise E26Error("artifact must contain only finite JSON values and string keys")

    try:
        check(value)
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return (encoded + "\n").encode()
    except (RecursionError, TypeError, ValueError, UnicodeError) as exc:
        raise E26Error("artifact cannot be serialized as strict JSON") from exc


def _decode_json(data: bytes) -> object:
    def unique_pairs(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise E26Error(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise E26Error(f"nonfinite JSON constant: {value}")

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique_pairs, parse_constant=invalid_constant)
        _json_bytes(value)  # Also rejects numeric overflow such as 1e999 and invalid surrogate strings.
        return value
    except (RecursionError, TypeError, ValueError, UnicodeError) as exc:
        raise E26Error("invalid JSON artifact") from exc


def _resolve_registered_path(
    selected: Path, aliases: dict[str, str], visiting: frozenset[str] = frozenset()
) -> tuple[Path, list[dict]]:
    """Resolve every ancestor/link explicitly; no automatically trusted aliases."""
    _absolute_path(selected, "selected path")
    current = Path(selected.anchor)
    records = []
    try:
        for part in selected.parts[1:]:
            current = current / part
            before = current.lstat()
            if not stat.S_ISLNK(before.st_mode):
                continue
            name = str(current)
            if name in visiting:
                raise E26Error("input alias cycle")
            raw_target = os.readlink(current)
            target = Path(os.path.abspath(current.parent / raw_target))
            resolved, nested = _resolve_registered_path(target, aliases, visiting | {name})
            if aliases.get(name) != str(resolved):
                raise E26Error(f"unregistered or changed input alias: {name}")
            if _stat_record(before) != _stat_record(current.lstat()) or raw_target != os.readlink(current):
                raise E26Error("input alias changed during resolution")
            records.append({
                "path": name, "target": raw_target, "resolved_path": str(resolved), "stat": _stat_record(before),
            })
            records.extend(nested)
            current = resolved
        return current, records
    except (OSError, RecursionError, ValueError) as exc:
        raise E26Error(f"cannot resolve selected input: {selected}") from exc


def _stable_file(path: Path, *, collect: bool = False) -> tuple[dict, bytes | None]:
    """Hash one resolved regular file via a retained FD and stable pre/post stats."""
    _absolute_path(path, "file path")
    fd = None
    try:
        if not hasattr(os, "O_NOFOLLOW"):
            raise E26Error("stable file reads require O_NOFOLLOW")
        initial = path.lstat()
        if not stat.S_ISREG(initial.st_mode):
            raise E26Error("stable file input must be regular and non-symlink")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0) | os.O_NONBLOCK)
        before = os.fstat(fd)
        if _stat_record(initial) != _stat_record(before):
            raise E26Error("file changed before opening")
        digest = hashlib.sha256()
        chunks = [] if collect else None
        size = 0
        while chunk := os.read(fd, 1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
            if chunks is not None:
                chunks.append(chunk)
        if (
            _stat_record(before) != _stat_record(os.fstat(fd))
            or _stat_record(before) != _stat_record(path.lstat()) or size != before.st_size
        ):
            raise E26Error("file changed during stable read")
        return {"sha256": digest.hexdigest(), "stat": _stat_record(before)}, b"".join(chunks) if collect else None
    except OSError as exc:
        raise E26Error(f"cannot read selected regular file: {path}") from exc
    finally:
        if fd is not None:
            os.close(fd)


def inventory_path(selected: Path, *, allowed_aliases: dict[str, str] | None = None) -> dict:
    """Inventory the complete selected file/tree opaquely, including empty dirs.

    Image/graph semantics are never read here. Tree digests retain the historical
    SHA256SUM format for acquisition-pin comparisons; full records also bind
    aliases, identities and directory membership. No partial-cache shortcut.
    """
    _absolute_path(selected, "inventory input")
    aliases = {} if allowed_aliases is None else allowed_aliases
    if type(aliases) is not dict:
        raise E26Error("allowed_aliases must be a dict of absolute link/target names")
    for name, target in aliases.items():
        if type(name) is not str or type(target) is not str:
            raise E26Error("input alias names and targets must be strings")
        _absolute_path(Path(name), "alias name")
        _absolute_path(Path(target), "alias target")
    files, directories = [], []

    def visit(path: Path, relative: str, ancestors: frozenset[tuple[int, int]]) -> tuple[Path, list[dict]]:
        resolved, links = _resolve_registered_path(path, aliases)
        before = resolved.lstat()
        base = {"relative_path": relative, "selected_path": str(path), "resolved_path": str(resolved), "aliases": links}
        if stat.S_ISREG(before.st_mode):
            identity, _ = _stable_file(resolved)
            files.append({**base, **identity})
        elif stat.S_ISDIR(before.st_mode):
            identity = (before.st_dev, before.st_ino)
            if identity in ancestors:
                raise E26Error("directory alias cycle")
            children = sorted((child.name for child in resolved.iterdir()), key=lambda name: name.encode("utf-8"))
            for name in children:
                if any(char in name for char in ("\n", "\r", "\\")):
                    raise E26Error("input names cannot be encoded unambiguously in the acquisition tree digest")
                visit(path / name, name if relative == "." else f"{relative}/{name}", ancestors | {identity})
            if _stat_record(before) != _stat_record(resolved.lstat()):
                raise E26Error("directory changed during inventory")
            directories.append({**base, "stat": _stat_record(before), "children": children})
        else:
            raise E26Error("input contains an unexpected file kind")
        after_resolved, after_links = _resolve_registered_path(path, aliases)
        if after_resolved != resolved or after_links != links:
            raise E26Error("input aliases changed during inventory")
        return resolved, links

    try:
        root, root_links = visit(selected, ".", frozenset())
    except (OSError, UnicodeError, ValueError) as exc:
        raise E26Error(f"cannot inventory selected input: {selected}") from exc
    files.sort(key=lambda row: row["relative_path"].encode("utf-8"))
    directories.sort(key=lambda row: row["relative_path"].encode("utf-8"))
    tree_lines = "".join(f"{row['sha256']}  ./{row['relative_path']}\n" for row in files)
    payload = {
        "schema_version": INVENTORY_SCHEMA, "selected_path": str(selected), "resolved_path": str(root),
        "kind": "tree" if directories else "file", "aliases": root_links, "files": files, "directories": directories,
        "file_count": len(files), "total_bytes": sum(row["stat"]["size"] for row in files),
        "content_sha256": hashlib.sha256(tree_lines.encode()).hexdigest() if directories else files[0]["sha256"],
    }
    return {**payload, "inventory_sha256": hashlib.sha256(_json_bytes(payload)).hexdigest()}


def _validate_inventory(binding: dict) -> dict[str, str]:
    """Validate the full nested schema before following any registered path."""
    _json_bytes(binding)
    _require_keys(binding, {
        "schema_version", "selected_path", "resolved_path", "kind", "aliases", "files", "directories",
        "file_count", "total_bytes", "content_sha256", "inventory_sha256",
    }, "inventory")
    if binding["schema_version"] != INVENTORY_SCHEMA or binding["kind"] not in ("file", "tree"):
        raise E26Error("unknown inventory schema/kind")
    for key in ("selected_path", "resolved_path"):
        if type(binding[key]) is not str:
            raise E26Error("inventory paths must be strings")
        _absolute_path(Path(binding[key]), key)
    aliases = {}
    alias_records = {}

    def check_stat(value: object) -> None:
        _require_keys(value, set(_STAT_KEYS), "file stat")
        if any(type(number) is not int for number in value.values()) or any(
            value[key] < 0 for key in ("device", "inode", "mode", "size")
        ):
            raise E26Error("invalid inventory file stat")

    def check_aliases(records: object) -> None:
        if type(records) is not list:
            raise E26Error("inventory aliases must be a list")
        for row in records:
            _require_keys(row, {"path", "target", "resolved_path", "stat"}, "alias record")
            if any(type(row[key]) is not str for key in ("path", "target", "resolved_path")):
                raise E26Error("alias record paths must be strings")
            _absolute_path(Path(row["path"]), "alias path")
            _absolute_path(Path(row["resolved_path"]), "alias resolved path")
            check_stat(row["stat"])
            if not stat.S_ISLNK(row["stat"]["mode"]) or not row["target"]:
                raise E26Error("invalid alias kind/target")
            previous = aliases.setdefault(row["path"], row["resolved_path"])
            previous_record = alias_records.setdefault(row["path"], row)
            if previous != row["resolved_path"] or previous_record != row:
                raise E26Error("inconsistent repeated alias binding")

    check_aliases(binding["aliases"])
    for group in ("files", "directories"):
        if type(binding[group]) is not list:
            raise E26Error("inventory records must be lists")
        names = []
        for row in binding[group]:
            keys = {"relative_path", "selected_path", "resolved_path", "aliases", "stat"}
            _require_keys(row, keys | ({"sha256"} if group == "files" else {"children"}), group)
            relative = row["relative_path"]
            if (
                type(relative) is not str or not relative or Path(relative).is_absolute()
                or ".." in Path(relative).parts or str(Path(relative)) != relative
            ):
                raise E26Error("invalid relative inventory path")
            if any(char in relative for char in ("\n", "\r", "\\")):
                raise E26Error("invalid relative inventory name")
            names.append(relative)
            for key in ("selected_path", "resolved_path"):
                if type(row[key]) is not str:
                    raise E26Error("record paths must be strings")
                _absolute_path(Path(row[key]), key)
            if Path(row["selected_path"]) != Path(binding["selected_path"]) / relative:
                raise E26Error("record selected path does not match inventory root")
            check_stat(row["stat"])
            check_aliases(row["aliases"])
            if group == "files":
                _require_sha256(row["sha256"], "file digest")
                if not stat.S_ISREG(row["stat"]["mode"]):
                    raise E26Error("file record is not regular")
            else:
                children = row["children"]
                if not stat.S_ISDIR(row["stat"]["mode"]) or type(children) is not list:
                    raise E26Error("invalid directory record")
                if any(
                    type(name) is not str or not name or name in (".", "..")
                    or any(char in name for char in ("/", "\n", "\r", "\\")) for name in children
                ):
                    raise E26Error("invalid directory child name")
                if children != sorted(set(children), key=lambda name: name.encode()):
                    raise E26Error("directory children must be uniquely ordered")
        if names != sorted(set(names), key=lambda name: name.encode()):
            raise E26Error("inventory records must be uniquely ordered")
    if binding["kind"] == "file":
        if binding["directories"] or len(binding["files"]) != 1 or binding["files"][0]["relative_path"] != ".":
            raise E26Error("invalid single-file inventory")
        content_digest = binding["files"][0]["sha256"]
        root_record = binding["files"][0]
    else:
        if not binding["directories"] or binding["directories"][0]["relative_path"] != ".":
            raise E26Error("tree inventory must include root directory")
        tree_lines = "".join(f"{row['sha256']}  ./{row['relative_path']}\n" for row in binding["files"])
        content_digest = hashlib.sha256(tree_lines.encode()).hexdigest()
        root_record = binding["directories"][0]
        all_rows = binding["files"] + binding["directories"]
        all_names = [row["relative_path"] for row in all_rows]
        if len(all_names) != len(set(all_names)):
            raise E26Error("file/directory inventory paths overlap")
        children_by_parent = {row["relative_path"]: [] for row in binding["directories"]}
        for name in all_names:
            if name == ".":
                continue
            relative_path = Path(name)
            parent = str(relative_path.parent)
            if parent not in children_by_parent:
                raise E26Error("inventory record lacks parent directory")
            children_by_parent[parent].append(relative_path.name)
        for directory in binding["directories"]:
            actual_children = sorted(children_by_parent[directory["relative_path"]])
            if actual_children != sorted(directory["children"]):
                raise E26Error("directory membership differs from complete records")
    if root_record["resolved_path"] != binding["resolved_path"] or root_record["aliases"] != binding["aliases"]:
        raise E26Error("root inventory identity mismatch")
    for key in ("file_count", "total_bytes"):
        _require_count(binding[key], key)
    if binding["file_count"] != len(binding["files"]) or binding["total_bytes"] != sum(
        row["stat"]["size"] for row in binding["files"]
    ):
        raise E26Error("inventory counts differ from complete file records")
    _require_sha256(binding["content_sha256"], "content digest")
    _require_sha256(binding["inventory_sha256"], "inventory digest")
    payload = {key: value for key, value in binding.items() if key != "inventory_sha256"}
    if (
        binding["content_sha256"] != content_digest
        or binding["inventory_sha256"] != hashlib.sha256(_json_bytes(payload)).hexdigest()
    ):
        raise E26Error("inventory digest mismatch")
    return aliases


def verify_inventory(binding: dict) -> None:
    aliases = _validate_inventory(binding)
    if inventory_path(Path(binding["selected_path"]), allowed_aliases=aliases) != binding:
        raise E26Error("registered input inventory drift")


def _plain_artifact_path(path: Path) -> Path:
    _absolute_path(path, "artifact path")
    try:
        resolved_parent = path.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise E26Error("artifact parent must exist without alias cycles") from exc
    if resolved_parent != path.parent or path.is_symlink():
        raise E26Error("artifact paths must not contain aliases")
    return path


def read_json_bound(path: Path, expected_sha256: str) -> object:
    """Read one exact JSON artifact. Generation must never use this on GT_BINDING."""
    _plain_artifact_path(path)
    _require_sha256(expected_sha256, "expected artifact digest")
    identity, data = _stable_file(path, collect=True)
    if identity["sha256"] != expected_sha256:
        raise E26Error("JSON artifact digest mismatch")
    return _decode_json(data)


def write_json_exclusive(path: Path, value: object) -> dict:
    """Exclusive, fsynced JSON with strict reparse; failed partial files are kept."""
    _plain_artifact_path(path)
    data = _json_bytes(value)
    try:
        if not hasattr(os, "O_NOFOLLOW"):
            raise E26Error("exclusive artifacts require O_NOFOLLOW")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        expected = hashlib.sha256(data).hexdigest()
        if _json_bytes(read_json_bound(path, expected)) != data:
            raise E26Error("JSON reparse differs from written artifact")
        return {"path": str(path), "sha256": expected, "bytes": len(data)}
    except OSError as exc:
        raise E26Error(f"cannot create exclusive JSON artifact: {path.name}") from exc


BUDGET_SCHEMA = "biohub.e26_screen.budget.v1"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RAM_POLICY = {
    "scope": "self_process",
    "units": "bytes",
    "measurement": "getrusage(RUSAGE_SELF).ru_maxrss",
    "enforcement": "dataset_boundaries_and_receipts_not_os_hard_limit",
}
_INFERENCE_ENV = {
    "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
    "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "1", "CUDA_VISIBLE_DEVICES": "",
    "LC_ALL": "C", "LANG": "C", "TZ": "UTC",
    "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1",
}


def validate_budget(budget: dict) -> None:
    """No numerical default: every physical allowance must be fixed beforehand."""
    _json_bytes(budget)
    _require_keys(budget, {
        "schema_version", "arm_wall_seconds", "generation_wall_seconds", "score_process_wall_seconds",
        "score_stage_wall_seconds", "ram",
    }, "budget")
    if budget["schema_version"] != BUDGET_SCHEMA:
        raise E26Error("unknown budget schema")
    for key, names in (("arm_wall_seconds", set(ARM_ORDER)), ("score_stage_wall_seconds", set(_STAGE_VIDEOS))):
        _require_keys(budget[key], names, key)
    _require_keys(budget["ram"], set(_RAM_POLICY) | {"limit_bytes"}, "RAM budget")
    for key, value in _RAM_POLICY.items():
        if type(budget["ram"][key]) is not str or budget["ram"][key] != value:
            raise E26Error("RAM policy must state self-process boundary/receipt checks honestly")
    _require_count(budget["ram"]["limit_bytes"], "RAM limit")
    if budget["ram"]["limit_bytes"] == 0:
        raise E26Error("RAM limit must be positive")
    limits = list(budget["arm_wall_seconds"].values()) + list(budget["score_stage_wall_seconds"].values())
    limits += [budget["generation_wall_seconds"], budget["score_process_wall_seconds"]]
    for value in limits:
        _require_finite_number(value, "wall limit in seconds", json_number=True)
        if value <= 0:
            raise E26Error("wall limits must be positive")


def generation_environment() -> dict[str, str]:
    """Explicit child allowlist; never copy credentials, proxy or BIOHUB overrides."""
    environment = {
        **_INFERENCE_ENV,
        "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
        "PYTHONPATH": str(_PROJECT_ROOT / "src"),
    }
    if sys.platform == "darwin":
        # This host otherwise injects its user text-encoding setting at startup.
        # Pin its encoding fields explicitly instead of accepting extra keys.
        environment["__CF_USER_TEXT_ENCODING"] = f"0x{os.getuid():X}:0x0:0x0"
    return environment


def initialize_inference_runtime() -> dict:
    """Called once in a fresh generation child, before any numerical imports."""
    if dict(os.environ) != generation_environment():
        raise E26Error("generation child environment differs from the explicit allowlist")
    if any(name in sys.modules for name in ("numpy", "pandas", "polars", "torch")):
        raise E26Error("numerical modules were loaded before inference controls")
    import numpy as np
    import torch

    random.seed(0)
    np.random.seed(0)
    torch.manual_seed(0)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    if torch.cuda.is_available():
        raise E26Error("generation requires CPU, but CUDA is available")
    result = {
        "schema_version": "biohub.e26_screen.inference_controls.v1",
        "environment": dict(os.environ), "python_seed": 0, "numpy_seed": 0, "torch_seed": 0,
        "torch_initial_seed": torch.initial_seed(), "torch_num_threads": torch.get_num_threads(),
        "torch_num_interop_threads": torch.get_num_interop_threads(), "required_device": "cpu",
    }
    if (
        result["torch_initial_seed"] != 0
        or result["torch_num_threads"] != 1 or result["torch_num_interop_threads"] != 1
    ):
        raise E26Error("actual Torch inference controls differ from required values")
    return result


def self_peak_rss_bytes() -> int:
    """Self-process high-water RSS only: Darwin bytes, Linux KiB converted to bytes."""
    measured = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    _require_finite_number(measured, "self peak RSS", json_number=True)
    if measured < 0 or measured != int(measured):
        raise E26Error("self peak RSS must be a nonnegative integer")
    if sys.platform == "darwin":
        return int(measured)
    if sys.platform.startswith("linux"):
        return int(measured) * 1024
    raise E26Error("unsupported platform for honest self-process RSS conversion")


def check_runtime_budget(started_monotonic: float, *, wall_limit_seconds: float, ram_limit_bytes: int) -> dict:
    """Check explicit self-process limits at a dataset boundary or final receipt.

    Raising stops the caller; this is not a continuously enforced OS memory cap.
    Whole-generation and child termination deadlines also need the supervisor.
    """
    _require_finite_number(started_monotonic, "start clock", json_number=True)
    _require_finite_number(wall_limit_seconds, "wall limit", json_number=True)
    _require_count(ram_limit_bytes, "RAM limit")
    if wall_limit_seconds <= 0 or ram_limit_bytes <= 0:
        raise E26Error("runtime limits must be positive")
    elapsed = time.monotonic() - started_monotonic
    _require_finite_number(elapsed, "elapsed wall seconds", json_number=True)
    if elapsed < 0:
        raise E26Error("elapsed wall duration must be nonnegative")
    peak = self_peak_rss_bytes()
    if elapsed > wall_limit_seconds:
        raise E26Error("self-process wall budget exceeded")
    if peak > ram_limit_bytes:
        raise E26Error("self-process peak RSS budget exceeded")
    return {"wall_seconds": elapsed, "peak_rss_bytes": peak, "ram_scope": "self_process"}


def _run_paths(run_id: str) -> tuple[Path, Path]:
    if type(run_id) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", run_id) is None:
        raise E26Error("run_id must be 1–96 safe ASCII letters/digits/underscore/hyphen, starting alphanumeric")
    return (
        _PROJECT_ROOT / "outputs/local/e26_screen_preregistrations" / run_id,
        _PROJECT_ROOT / "outputs/local/e26_screen" / run_id,
    )


def _ensure_plain_directory(path: Path) -> None:
    """Create only missing namespace ancestors, rejecting aliases and non-dirs."""
    _absolute_path(path, "output directory")
    current = Path(path.anchor)
    try:
        for part in path.parts[1:]:
            current = current / part
            try:
                value = current.lstat()
            except FileNotFoundError:
                current.mkdir()
                value = current.lstat()
            if not stat.S_ISDIR(value.st_mode):
                raise E26Error("output directory ancestors must be non-symlink directories")
    except OSError as exc:
        raise E26Error("cannot create plain output namespace") from exc


def create_preregistration_directory(run_id: str) -> Path:
    """Create only the separate registration directory; never precreate generation."""
    registration, generation = _run_paths(run_id)
    current = Path(generation.anchor)
    for part in generation.parent.parts[1:]:
        current = current / part
        try:
            value = current.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise E26Error("cannot inspect generation namespace") from exc
        if not stat.S_ISDIR(value.st_mode):
            raise E26Error("generation namespace must not contain aliases or non-directories")
    if generation.exists() or generation.is_symlink():
        raise E26Error("cannot preregister an existing generation run")
    _ensure_plain_directory(registration.parent)
    _plain_artifact_path(registration)
    try:
        registration.mkdir(mode=0o700)
    except OSError as exc:
        raise E26Error("preregistration run already exists or cannot be created") from exc
    if generation.exists() or generation.is_symlink():
        raise E26Error("generation run appeared during preregistration; failed directory retained")
    return registration


# These are closed runtime/scientific input lists, not discovery patterns. The
# generation/scoring contracts are the final single-agent implementation briefs.
_SOURCE_PATHS = (
    "src/biohub/__init__.py", "src/biohub/e26_screen.py", "scripts/e26_screen.py",
    "src/biohub/output_bounds.py", "src/biohub/screen_output_bounds.py",
    "src/biohub/io.py", "src/biohub/validate.py", "src/biohub/evaluate.py",
    "src/biohub/public_postproc/__init__.py", "src/biohub/public_postproc/config.py",
    "src/biohub/public_postproc/csv_out.py", "src/biohub/public_postproc/deepcenter.py",
    "src/biohub/public_postproc/divisions.py", "src/biohub/public_postproc/frames.py",
    "src/biohub/public_postproc/geometry.py", "src/biohub/public_postproc/graph_ops.py",
    "src/biohub/public_postproc/pipeline.py", "official/src/tracking_cellmot/__init__.py",
    "official/src/tracking_cellmot/metrics.py", "official/src/tracking_cellmot/division_metrics.py",
    "pyproject.toml", "uv.lock",
)
_SCIENTIFIC_PATHS = (
    "analysis/e26_motion_relink_off_design.md", "analysis/e26_unit02_task.md",
    "analysis/e26_unit02b_task.md", "analysis/e26_generation_contract.md",
    "analysis/e26_scoring_contract.md", "analysis/e26_runner_interface.md",
    "analysis/kaggle_loop_protocol_v2.md", "analysis/e23_parity_runbook.md",
    "analysis/e26_screen_bounds_v2_contract.md",
)
_OFFICIAL_HEAD = "075fc5f5a52d11077f9dc2b074644618f26939e2"
_DIRECT_DISTRIBUTIONS = ("numpy", "pandas", "scipy", "blosc2", "tracksdata", "geff", "torch", "polars")
_RAW4_REL = "outputs/kaggle/e22_bidir030_public4_raw/tracking_repo/predictions/unknown/unet_transformer/split_0"
_RAW36_REL = "outputs/kaggle/e22_bidir030_eval36_raw/tracking_repo/predictions/unknown/unet_transformer_val/split_0"
_WEIGHTS_REL = "outputs/kaggle/e23_artifacts/pilkwang/biohub-deepcenter-unet3d-center-prior-v1"
_IMAGE_READY_REL = "outputs/local/eval36_image_ready/20260904T220902+0900_2877f28_direct"
_ACQUISITION_PINS = {
    "raw4_manifest": (
        "outputs/kaggle/e22_bidir030_public4_raw/DOWNLOAD_MANIFEST.json",
        "9cc95d3e00b75eaeeb05a1798cc1a1fd0cfb18be1d3239c9b64608527933806b",
    ),
    "raw36_manifest": (
        "outputs/kaggle/e22_bidir030_eval36_reference/DOWNLOAD_MANIFEST.json",
        "1f567e2520cc75536886296c1b88724ea2c2776cd2aa6b52ceaaac6bca8ac12b",
    ),
    "image36_ready": (
        f"{_IMAGE_READY_REL}/READY.json", "8a0a36d393ecc11a0532bc12011257a4c012cb7361d4346941b4d1211c58c73e",
    ),
    "image36_inventory": (
        f"{_IMAGE_READY_REL}/IMAGE_CONTENT_INVENTORY.json",
        "efe652bd8e8a791bd51cf3b980ae87fe0fe2205ec52d2f3639717cd2b0550714",
    ),
    "image_manifest": ("data/manifest.csv", "6c1c59644daf7fe59458dc860f2e1783d1217be389a791ea54e1f611f5f848f4"),
}
_WEIGHT_PINS = {
    "checkpoint": (f"{_WEIGHTS_REL}/weights/full_frame_center/best.pt",
                   "8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0"),
    "manifest": (f"{_WEIGHTS_REL}/ARTIFACT_MANIFEST.json",
                 "1eedc1af72b10c464c6995013075310510b6f6e634450ff2bc170c67b89ce911"),
    "reference": ("outputs/kaggle/e23_reference/submission.csv",
                  "33c179b0449b9cdd186f06a653cddc8cf12359f008982f6713cdf30784a52e6a"),
}
_PUBLIC4_IMAGE_PINS = (
    "987acb0038ef744c0265f028fc003e04182fccac0e520afb8704c426926425ac",
    "0c50cb7ef2bb45d1e7414fce46c6c2e37c3829ce805295c3fcad0701440a7140",
    "8f3388f202ab0a483552becd6ffbac6cd13f29ee35ff760bd8c940f5198b5346",
    "fd1913480fcb34db07b72bcaeeb44d1e3488676c3fed982555cd4b06c123416a",
)
PREREGISTRATION_SCHEMA = "biohub.e26_screen.preregistration.v2"
GT_BINDING_SCHEMA = "biohub.e26_screen.gt_binding.v1"
INPUT_BINDING_SCHEMA = "biohub.e26_screen.generation_inputs.v1"


def _git_identity() -> dict:
    def git(*args: str, official: bool = False) -> str:
        try:
            return subprocess.run(
                ["/usr/bin/git", "--no-optional-locks", *args],
                cwd=_PROJECT_ROOT / "official" if official else _PROJECT_ROOT,
                env=generation_environment(), check=True, capture_output=True, text=True, timeout=15,
            ).stdout.rstrip("\n")
        except (OSError, subprocess.SubprocessError) as exc:
            raise E26Error("cannot bind repository identity") from exc

    official_head = git("rev-parse", "HEAD", official=True)
    official_status = git("status", "--porcelain=v1", "--untracked-files=all", official=True)
    gitlink = git("ls-files", "--stage", "--", "official")
    if official_head != _OFFICIAL_HEAD or official_status or gitlink != f"160000 {_OFFICIAL_HEAD} 0\tofficial":
        raise E26Error("official HEAD/gitlink must match the clean fixed metric source")
    return {
        "head": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
        "status_porcelain": git("status", "--porcelain=v1", "--untracked-files=all"),
        "official_head": official_head, "official_status": official_status, "official_gitlink": gitlink,
    }


def capture_code_bindings() -> dict:
    """Full selected file inventories plus honest Git state, without imports."""
    before = _git_identity()
    result = {
        "source_binding": {"files": [inventory_path(_PROJECT_ROOT / p) for p in _SOURCE_PATHS], "git": before},
        "scientific_binding": {"files": [inventory_path(_PROJECT_ROOT / p) for p in _SCIENTIFIC_PATHS]},
    }
    if _git_identity() != before:
        raise E26Error("Git state changed while binding source")
    return result


def verify_code_bindings(source_binding: dict, scientific_binding: dict) -> None:
    for binding, paths, keys in (
        (source_binding, _SOURCE_PATHS, {"files", "git"}),
        (scientific_binding, _SCIENTIFIC_PATHS, {"files"}),
    ):
        _require_keys(binding, keys, "code binding")
        if type(binding["files"]) is not list or len(binding["files"]) != len(paths):
            raise E26Error("incomplete code closure")
        for row, relative in zip(binding["files"], paths, strict=True):
            _validate_inventory(row)
            if row["kind"] != "file" or row["selected_path"] != str(_PROJECT_ROOT / relative):
                raise E26Error("code closure path/order mismatch")
    # All path/schema checks precede filesystem verification.
    for binding in (source_binding, scientific_binding):
        for row in binding["files"]:
            verify_inventory(row)
    if _json_bytes(source_binding["git"]) != _json_bytes(_git_identity()):
        raise E26Error("registered Git state drift")


def capture_dependency_binding() -> dict:
    """Pin all installed distributions (including transitive ones), no imports."""
    distributions = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name")
        if type(name) is not str or not name or not dist.version:
            raise E26Error("installed distribution lacks name/version")
        name = re.sub(r"[-_.]+", "-", name).lower()
        if name in distributions:
            raise E26Error("duplicate installed distribution identity")
        distributions[name] = dist.version
    if not set(_DIRECT_DISTRIBUTIONS) <= set(distributions):
        raise E26Error("required generation/scoring runtime is not installed")
    executable = Path(sys.executable).resolve(strict=True)
    identity, _ = _stable_file(executable)
    return {
        "schema_version": "biohub.e26_screen.dependencies.v1", "python_version": sys.version,
        "implementation": sys.implementation.name, "platform": platform.platform(), "machine": platform.machine(),
        "executable": str(Path(sys.executable)), "resolved_executable": str(executable),
        "executable_identity": identity, "prefix": sys.prefix, "base_prefix": sys.base_prefix,
        "required_distributions": list(_DIRECT_DISTRIBUTIONS),
        "installed_distributions": [{"name": name, "version": distributions[name]} for name in sorted(distributions)],
    }


def verify_dependency_binding(binding: dict) -> None:
    if _json_bytes(binding) != _json_bytes(capture_dependency_binding()):
        raise E26Error("registered Python/dependency identity drift or invalid schema")


def _inventory_json_file(tree: dict, relative: str) -> tuple[object, dict]:
    matches = [row for row in tree["files"] if row["relative_path"] == relative]
    if len(matches) != 1:
        raise E26Error(f"missing explicit image metadata: {relative}")
    row = matches[0]
    # Never follow a merely declared resolved name before proving it comes from
    # the allowlisted selected image path and its actual registered aliases.
    resolved, links = _resolve_registered_path(Path(row["selected_path"]), _validate_inventory(tree))
    if str(resolved) != row["resolved_path"] or links != row["aliases"]:
        raise E26Error("image metadata resolved path/alias differs from registered selected path")
    identity, data = _stable_file(resolved, collect=True)
    if identity != {key: row[key] for key in ("sha256", "stat")}:
        raise E26Error("image metadata changed after inventory")
    return _decode_json(data), {
        "path": row["selected_path"], "sha256": row["sha256"], "bytes": row["stat"]["size"],
    }


def bind_image_metadata(image_inventory: dict) -> dict:
    """Read only explicit Zarr metadata; no graph or image-chunk decoding."""
    _validate_inventory(image_inventory)
    array, array_identity = _inventory_json_file(image_inventory, "0/zarr.json")
    root, root_identity = _inventory_json_file(image_inventory, "zarr.json")
    try:
        shape = array["shape"]
        if (
            type(shape) is not list or len(shape) != 4
            or any(type(x) is not int or x <= 0 for x in shape) or array["data_type"] != "uint16"
        ):
            raise E26Error("image must have explicit positive integer TZYX shape and uint16 dtype")
        attrs = root["attributes"]
        attrs = attrs.get("ome", attrs)
        scale_set = attrs["multiscales"][0]
        axes = [axis["name"].lower() for axis in scale_set["axes"]]
        dataset = scale_set["datasets"][0]
        transform = dataset["coordinateTransformations"][0]
        scale = transform["scale"]
        if (
            axes != ["t", "z", "y", "x"] or dataset["path"] != "0" or transform["type"] != "scale"
            or type(scale) is not list or len(scale) != 4
        ):
            raise E26Error("image scale must be explicit TZYX metadata for array 0; no fallback")
        for value in scale:
            _require_finite_number(value, "explicit voxel scale", json_number=True)
            if value <= 0:
                raise E26Error("image voxel scale must be positive")
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise E26Error("missing/invalid explicit image shape/scale metadata; no fallback") from exc
    return {
        "shape_tzyx": shape, "scale_zyx": [float(x) for x in scale[-3:]], "dtype": "uint16",
        "array_metadata": array_identity, "root_metadata": root_identity,
    }


def _serialized_config(arm: str) -> dict:
    cfg = build_arm_config(
        arm, _PROJECT_ROOT / ("data/test" if arm == "public4_parity" else "data/train"),
        _PROJECT_ROOT / _WEIGHT_PINS["checkpoint"][0], _PROJECT_ROOT / _WEIGHT_PINS["manifest"][0],
    )
    return {field.name: str(v) if isinstance(v := getattr(cfg, field.name), Path) else v
            for field in dataclasses.fields(cfg)}


def _validate_image_metadata_binding(metadata: dict, image: dict) -> None:
    """Validate all metadata fields against inventory records before file reads."""
    _require_keys(metadata, {
        "shape_tzyx", "scale_zyx", "dtype", "array_metadata", "root_metadata",
    }, "image metadata binding")
    shape, scale = metadata["shape_tzyx"], metadata["scale_zyx"]
    if (
        type(shape) is not list or len(shape) != 4 or any(type(x) is not int or x <= 0 for x in shape)
        or type(scale) is not list or len(scale) != 3 or metadata["dtype"] != "uint16"
    ):
        raise E26Error("invalid registered image shape/scale/dtype")
    for value in scale:
        _require_finite_number(value, "registered scale", json_number=True)
        if value <= 0:
            raise E26Error("registered scale must be positive")
    for key, relative in (("array_metadata", "0/zarr.json"), ("root_metadata", "zarr.json")):
        rows = [row for row in image["files"] if row["relative_path"] == relative]
        if len(rows) != 1:
            raise E26Error("missing metadata file in registered inventory")
        row = rows[0]
        expected = {"path": row["selected_path"], "sha256": row["sha256"], "bytes": row["stat"]["size"]}
        if _json_bytes(metadata[key]) != _json_bytes(expected):
            raise E26Error("metadata file binding differs from its full inventory record")


def _validate_pinned_file(binding: dict, relative: str, expected_sha: str) -> None:
    _validate_inventory(binding)
    if (
        binding["kind"] != "file" or binding["selected_path"] != str(_PROJECT_ROOT / relative)
        or binding["content_sha256"] != expected_sha
    ):
        raise E26Error("pinned input path/kind/hash mismatch")


def _acquisition_matches(binding: dict) -> None:
    # These exact historical receipts contain raw/image provenance only. Never
    # parse data/manifest.csv here: it also lists GT names and is byte-bound only.
    evidence = {key: read_json_bound(_PROJECT_ROOT / rel, sha)
                for key, (rel, sha) in _ACQUISITION_PINS.items() if key != "image_manifest"}
    for group, historical in (
        ("public4", evidence["raw4_manifest"]["summary"]),
        ("eval36", evidence["raw36_manifest"]["raw_geff"]),
    ):
        raw = binding[group]["raw_inventory"]
        if (raw["file_count"], raw["total_bytes"], raw["content_sha256"]) != (
            historical["files"], historical["bytes"], historical["canonical_sha256sum_tree_sha256"],
        ):
            raise E26Error(f"{group} raw bytes differ from acquisition manifest")
    for row, sha in zip(binding["public4"]["videos"], _PUBLIC4_IMAGE_PINS, strict=True):
        if row["image_inventory"]["content_sha256"] != sha:
            raise E26Error("public4 image bytes differ from parity pins")
    observed_files = sorted((
        {"stem": video["dataset"], "path": f"{video['dataset']}.zarr/{row['relative_path']}",
         "bytes": row["stat"]["size"], "sha256": row["sha256"]}
        for video in binding["eval36"]["videos"] for row in video["image_inventory"]["files"]
    ), key=lambda row: row["path"])
    image_record = evidence["image36_inventory"]
    if image_record["roots"] != list(EVAL36) or observed_files != image_record["files"]:
        raise E26Error("eval36 images differ from acquired content inventory")
    ready = evidence["image36_ready"]
    if (
        ready["inventory"]["sha256"] != _ACQUISITION_PINS["image36_inventory"][1]
        or ready["manifest"]["sha256"] != _ACQUISITION_PINS["image_manifest"][1]
    ):
        raise E26Error("image acquisition receipt chain mismatch")


def capture_generation_inputs(*, allowed_aliases: dict[str, str] | None = None) -> dict:
    """Bind the complete canonical selected inputs, not old execution receipts."""
    def inventory(path: Path) -> dict:
        return inventory_path(path, allowed_aliases=allowed_aliases)

    result = {
        "schema_version": INPUT_BINDING_SCHEMA,
        "acquisition_evidence": {key: inventory(_PROJECT_ROOT / rel) for key, (rel, _) in _ACQUISITION_PINS.items()},
        **{key: inventory(_PROJECT_ROOT / rel) for key, (rel, _) in _WEIGHT_PINS.items()},
        "configs": {arm: _serialized_config(arm) for arm in ARM_ORDER},
    }
    # Reject changed acquisition/weight files before reading the image trees.
    for key, (relative, sha) in _ACQUISITION_PINS.items():
        _validate_pinned_file(result["acquisition_evidence"][key], relative, sha)
    for key, (relative, sha) in _WEIGHT_PINS.items():
        _validate_pinned_file(result[key], relative, sha)
    for group, stems, raw_relative, image_relative in (
        ("public4", PUBLIC4, _RAW4_REL, "data/test"), ("eval36", EVAL36, _RAW36_REL, "data/train"),
    ):
        videos = []
        for stem in stems:
            image = inventory(_PROJECT_ROOT / image_relative / f"{stem}.zarr")
            videos.append({"dataset": stem, "image_inventory": image, "metadata": bind_image_metadata(image)})
        result[group] = {
            "raw_inventory": inventory(_PROJECT_ROOT / raw_relative),
            "image_root": str(_PROJECT_ROOT / image_relative), "videos": videos,
        }
    validate_generation_input_binding(result)
    return result


def validate_generation_input_binding(binding: dict) -> None:
    """Check the entire allowlisted shape before interpreting any supplied path."""
    _json_bytes(binding)
    _require_keys(binding, {
        "schema_version", "public4", "eval36", "acquisition_evidence", "configs", *_WEIGHT_PINS,
    }, "generation input binding")
    if binding["schema_version"] != INPUT_BINDING_SCHEMA:
        raise E26Error("unknown generation input schema")
    _require_keys(binding["acquisition_evidence"], set(_ACQUISITION_PINS), "acquisition evidence")
    for key, (relative, sha) in _ACQUISITION_PINS.items():
        _validate_pinned_file(binding["acquisition_evidence"][key], relative, sha)
    for key, (relative, sha) in _WEIGHT_PINS.items():
        _validate_pinned_file(binding[key], relative, sha)
    if _json_bytes(binding["configs"]) != _json_bytes({arm: _serialized_config(arm) for arm in ARM_ORDER}):
        raise E26Error("registered configs differ from the exact E23 arm definitions")
    for group, stems, raw_relative, image_relative in (
        ("public4", PUBLIC4, _RAW4_REL, "data/test"), ("eval36", EVAL36, _RAW36_REL, "data/train"),
    ):
        value = binding[group]
        _require_keys(value, {"raw_inventory", "image_root", "videos"}, "generation group")
        raw = value["raw_inventory"]
        _validate_inventory(raw)
        if (
            raw["kind"] != "tree" or raw["selected_path"] != str(_PROJECT_ROOT / raw_relative)
            or raw["directories"][0]["children"] != sorted(f"{s}.geff" for s in stems)
            or value["image_root"] != str(_PROJECT_ROOT / image_relative)
        ):
            raise E26Error("raw dataset membership or input root mismatch")
        if type(value["videos"]) is not list or len(value["videos"]) != len(stems):
            raise E26Error("incomplete ordered generation videos")
        for video, stem in zip(value["videos"], stems, strict=True):
            _require_keys(video, {"dataset", "image_inventory", "metadata"}, "generation video")
            image = video["image_inventory"]
            _validate_inventory(image)
            if (
                type(video["dataset"]) is not str or video["dataset"] != stem or image["kind"] != "tree"
                or image["selected_path"] != str(_PROJECT_ROOT / image_relative / f"{stem}.zarr")
            ):
                raise E26Error("generation video order or selected image mismatch")
            _validate_image_metadata_binding(video["metadata"], image)
    # All paths are now structurally validated; only selected image metadata and
    # fixed acquisition JSON are read below. GT semantics remain inaccessible.
    for group in ("public4", "eval36"):
        for video in binding[group]["videos"]:
            if _json_bytes(video["metadata"]) != _json_bytes(bind_image_metadata(video["image_inventory"])):
                raise E26Error("registered image metadata drift")
    _acquisition_matches(binding)


def verify_generation_inputs(binding: dict) -> None:
    validate_generation_input_binding(binding)
    records = list(binding["acquisition_evidence"].values()) + [binding[key] for key in _WEIGHT_PINS]
    for group in ("public4", "eval36"):
        records.append(binding[group]["raw_inventory"])
        records.extend(video["image_inventory"] for video in binding[group]["videos"])
    for record in records:
        verify_inventory(record)


def _validate_registration_header(binding: dict, schema: str, run_id: str) -> None:
    if (
        binding["schema_version"] != schema or binding["run_id"] != run_id
        or binding["candidate_id"] != CANDIDATE_ID or binding["submission_authorized"] is not False
        or binding["eval36_order"] != list(EVAL36)
    ):
        raise E26Error("invalid registration identity/order/no-submit header")


def validate_private_registration(binding: dict, *, run_id: str, generation_inputs: dict) -> None:
    """Only preregistration and scoring may parse the private GT binding."""
    _run_paths(run_id)
    _json_bytes(binding)
    _require_keys(binding, {
        "schema_version", "run_id", "candidate_id", "submission_authorized", "eval36_order", "videos",
    }, "private registration")
    _validate_registration_header(binding, GT_BINDING_SCHEMA, run_id)
    if type(binding["videos"]) is not list or len(binding["videos"]) != len(EVAL36):
        raise E26Error("private registration requires all 36 opaque GT trees")
    for row, image, stem in zip(binding["videos"], generation_inputs["eval36"]["videos"], EVAL36, strict=True):
        _require_keys(row, {"dataset", "gt_inventory", "image_metadata"}, "private video binding")
        gt = row["gt_inventory"]
        _validate_inventory(gt)
        if (
            row["dataset"] != stem or gt["kind"] != "tree" or gt["file_count"] == 0
            or gt["selected_path"] != str(_PROJECT_ROOT / "data/train" / f"{stem}.geff")
            or _json_bytes(row["image_metadata"]) != _json_bytes(image["metadata"])
        ):
            raise E26Error("private GT/scale order, path or metadata mismatch")


def validate_public_registration(binding: dict, *, run_id: str) -> None:
    _run_paths(run_id)
    _json_bytes(binding)
    _require_keys(binding, {
        "schema_version", "run_id", "candidate_id", "created_utc", "submission_authorized", "arm_order",
        "eval36_order", "scientific_binding", "source_binding", "dependency_binding", "generation_input_binding",
        "gt_binding_commitment", "budget",
    }, "public registration")
    _validate_registration_header(binding, PREREGISTRATION_SCHEMA, run_id)
    if binding["arm_order"] != list(ARM_ORDER):
        raise E26Error("registration arm order mismatch")
    created = binding["created_utc"]
    if type(created) is not str or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", created) is None:
        raise E26Error("registration requires an explicit UTC timestamp")
    try:
        datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise E26Error("invalid registration timestamp") from exc
    commitment = binding["gt_binding_commitment"]
    _require_keys(commitment, {"artifact", "algorithm", "sha256", "bytes", "video_count"}, "GT commitment")
    _require_sha256(commitment["sha256"], "private registration digest")
    _require_count(commitment["bytes"], "private registration size")
    if (
        commitment["artifact"] != "GT_BINDING.json" or commitment["algorithm"] != "sha256"
        or commitment["bytes"] == 0 or type(commitment["video_count"]) is not int or commitment["video_count"] != 36
    ):
        raise E26Error("invalid private registration commitment")
    validate_budget(binding["budget"])
    verify_code_bindings(binding["source_binding"], binding["scientific_binding"])
    verify_dependency_binding(binding["dependency_binding"])
    validate_generation_input_binding(binding["generation_input_binding"])


def preregister_screen(run_id: str, budget: dict, *, allowed_aliases: dict[str, str] | None = None) -> dict:
    """Opaque pre-generation registration. Does not authorize/start a real run."""
    validate_budget(budget)
    directory = create_preregistration_directory(run_id)
    code = capture_code_bindings()
    dependency = capture_dependency_binding()
    inputs = capture_generation_inputs(allowed_aliases=allowed_aliases)
    private = {
        "schema_version": GT_BINDING_SCHEMA, "run_id": run_id, "candidate_id": CANDIDATE_ID,
        "submission_authorized": False, "eval36_order": list(EVAL36),
        "videos": [{
            "dataset": video["dataset"], "image_metadata": video["metadata"],
            "gt_inventory": inventory_path(
                _PROJECT_ROOT / "data/train" / f"{video['dataset']}.geff", allowed_aliases=allowed_aliases,
            ),
        } for video in inputs["eval36"]["videos"]],
    }
    validate_private_registration(private, run_id=run_id, generation_inputs=inputs)
    verify_generation_inputs(inputs)
    for video in private["videos"]:
        verify_inventory(video["gt_inventory"])
    private_artifact = write_json_exclusive(directory / "GT_BINDING.json", private)
    public = {
        "schema_version": PREREGISTRATION_SCHEMA, "run_id": run_id, "candidate_id": CANDIDATE_ID,
        "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "submission_authorized": False,
        "arm_order": list(ARM_ORDER), "eval36_order": list(EVAL36), **code,
        "dependency_binding": dependency, "generation_input_binding": inputs, "budget": budget,
        "gt_binding_commitment": {"artifact": "GT_BINDING.json", "algorithm": "sha256",
                                  "sha256": private_artifact["sha256"], "bytes": private_artifact["bytes"],
                                  "video_count": len(EVAL36)},
    }
    validate_public_registration(public, run_id=run_id)
    if _run_paths(run_id)[1].exists() or _run_paths(run_id)[1].is_symlink():
        raise E26Error("generation appeared before registration completed")
    # This public file is the completion marker and is always written LAST.
    public_artifact = write_json_exclusive(directory / "PREREGISTRATION.json", public)
    return {"run_id": run_id, "public": public_artifact, "private": private_artifact,
            "submission_authorized": False}


def verify_registration_pair(
    public_path: Path, *, expected_public_sha256: str, expected_private_sha256: str,
) -> dict:
    """Generation-side verification: NEVER deserialize the private GT artifact."""
    _require_sha256(expected_public_sha256, "dispatch public digest")
    _require_sha256(expected_private_sha256, "dispatch private digest")
    _absolute_path(public_path, "public registration path")
    registration, _ = _run_paths(public_path.parent.name)
    if public_path != registration / "PREREGISTRATION.json":
        raise E26Error("registration must use its canonical public run namespace")
    public = read_json_bound(public_path, expected_public_sha256)
    if type(public) is not dict or type(public.get("run_id")) is not str:
        raise E26Error("missing public registration identity")
    validate_public_registration(public, run_id=public_path.parent.name)
    private_path = _plain_artifact_path(registration / "GT_BINDING.json")
    private_identity, _ = _stable_file(private_path)  # opaque bytes only; collect=False
    commitment = public["gt_binding_commitment"]
    if (
        private_identity["sha256"] != expected_private_sha256 or commitment["sha256"] != expected_private_sha256
        or private_identity["stat"]["size"] != commitment["bytes"]
    ):
        raise E26Error("private registration differs from original dispatch commitment")
    verify_generation_inputs(public["generation_input_binding"])
    return public


CHILD_CONTROL_SCHEMA = "biohub.e26_screen.generation_child.v2"
ARM_RESULT_SCHEMA = "biohub.e26_screen.arm_result.v2"
GENERATION_SEAL_SCHEMA = "biohub.e26_screen.generation_seal.v2"
_ARM_ARTIFACTS = {
    "started": "ARM_STARTED.json", "config": "effective_config.json",
    "deepcenter": "deepcenter_receipt.json", "inference": "inference_controls.json",
    "events": "events.json", "raw_statistics": "raw_stats.json",
    "normalized_statistics": "normalized_stats.json", "csv_validation": "csv_validation.json",
    "csv": "submission.csv",
    "output_bounds": "output_bounds.json",
}


def _artifact_reference(path: Path) -> dict:
    identity, _ = _stable_file(_plain_artifact_path(path))
    return {"path": str(path), "sha256": identity["sha256"], "bytes": identity["stat"]["size"]}


def _verify_artifact(reference: dict, expected_path: Path) -> None:
    _require_keys(reference, {"path", "sha256", "bytes"}, "artifact reference")
    _require_sha256(reference["sha256"], "artifact reference digest")
    _require_count(reference["bytes"], "artifact reference size")
    if reference["path"] != str(expected_path) or _artifact_reference(expected_path) != reference:
        raise E26Error("artifact path/size/bytes differ from the bound reference")


def _artifact_json(reference: dict, expected_path: Path) -> object:
    _verify_artifact(reference, expected_path)
    return read_json_bound(expected_path, reference["sha256"])


def _arm_directory(run_id: str, arm: str) -> Path:
    if type(arm) is not str or arm not in ARM_ORDER:
        raise E26Error("unknown generation arm")
    return _run_paths(run_id)[1] / "generation" / arm


def derive_generation_child_control(public: dict, arm: str) -> dict:
    """Explicit generation allowlist; never copy registration/GT/score state."""
    directory = _arm_directory(public["run_id"], arm)
    return {
        "schema_version": CHILD_CONTROL_SCHEMA, "run_id": public["run_id"], "candidate_id": CANDIDATE_ID,
        "submission_authorized": False, "arm": arm, "datasets": list(PUBLIC4 if arm == ARM_ORDER[0] else EVAL36),
        "output_directory": str(directory), "source_binding": public["source_binding"],
        "scientific_binding": public["scientific_binding"], "dependency_binding": public["dependency_binding"],
        "generation_input_binding": public["generation_input_binding"], "config": _serialized_config(arm),
        "environment": generation_environment(),
        "limits": {"wall_seconds": public["budget"]["arm_wall_seconds"][arm],
                   "ram_limit_bytes": public["budget"]["ram"]["limit_bytes"]},
    }


def validate_generation_child_control(control: dict) -> None:
    _json_bytes(control)
    _require_keys(control, {
        "schema_version", "run_id", "candidate_id", "submission_authorized", "arm", "datasets",
        "output_directory", "source_binding", "scientific_binding", "dependency_binding",
        "generation_input_binding", "config", "environment", "limits",
    }, "generation child control")
    directory = _arm_directory(control["run_id"], control["arm"])
    expected_datasets = PUBLIC4 if control["arm"] == ARM_ORDER[0] else EVAL36
    if (
        control["schema_version"] != CHILD_CONTROL_SCHEMA or control["candidate_id"] != CANDIDATE_ID
        or control["submission_authorized"] is not False or control["output_directory"] != str(directory)
        or control["datasets"] != list(expected_datasets)
        or _json_bytes(control["config"]) != _json_bytes(_serialized_config(control["arm"]))
        or control["environment"] != generation_environment()
    ):
        raise E26Error("invalid generation child identity/order/config/environment")
    _require_keys(control["limits"], {"wall_seconds", "ram_limit_bytes"}, "child limits")
    _require_finite_number(control["limits"]["wall_seconds"], "child wall limit", json_number=True)
    _require_count(control["limits"]["ram_limit_bytes"], "child RAM limit")
    if control["limits"]["wall_seconds"] <= 0 or control["limits"]["ram_limit_bytes"] <= 0:
        raise E26Error("child limits must be positive")
    verify_code_bindings(control["source_binding"], control["scientific_binding"])
    verify_dependency_binding(control["dependency_binding"])
    validate_generation_input_binding(control["generation_input_binding"])


def _verify_child_bindings(control: dict) -> None:
    validate_generation_child_control(control)
    verify_generation_inputs(control["generation_input_binding"])


def _validate_deepcenter_receipt(receipt: dict, inputs: dict) -> None:
    """Validate the strict-loader evidence without importing Torch in the parent."""
    _require_keys(receipt, {
        "schema_version", "registered", "checkpoint", "manifest", "chosen_artifact", "verified_epoch",
        "verified_configs", "known_config_discrepancy", "inference_relevant_config_equal", "device", "dtype",
        "open_count", "fallback_candidates",
    }, "strict DeepCenter receipt")
    for key, expected in (
        ("schema_version", "biohub.st_r3.deepcenter_receipt.v1"), ("device", "cpu"), ("dtype", "float32"),
        ("verified_epoch", 2), ("open_count", 2), ("fallback_candidates", 0),
        ("inference_relevant_config_equal", True), ("chosen_artifact", Path(_WEIGHT_PINS["checkpoint"][0]).name),
    ):
        if type(receipt[key]) is not type(expected) or receipt[key] != expected:
            raise E26Error(f"strict DeepCenter receipt mismatch: {key}")
    registered = {f"{key}_name": Path(_WEIGHT_PINS[key][0]).name for key in ("checkpoint", "manifest")}
    if receipt["registered"] != registered:
        raise E26Error("strict DeepCenter selected artifact names mismatch")
    for key in ("checkpoint", "manifest"):
        row = inputs[key]["files"][0]
        expected = {"sha256": row["sha256"], "open_count": 1,
                    "pre": row["stat"], "post_hash": row["stat"], "post_read": row["stat"]}
        if _json_bytes(receipt[key]) != _json_bytes(expected):
            raise E26Error("strict DeepCenter receipt file identity differs from registered bytes")
    manifest = read_json_bound(_PROJECT_ROOT / _WEIGHT_PINS["manifest"][0], _WEIGHT_PINS["manifest"][1])
    expected_configs = {"manifest": manifest["model"]["config"],
                        "checkpoint": {**manifest["model"]["config"], "epochs": 50}}
    if (
        _json_bytes(receipt["verified_configs"]) != _json_bytes(expected_configs)
        or _json_bytes(receipt["known_config_discrepancy"])
        != _json_bytes({"field": "epochs", "manifest": 1000, "checkpoint": 50})
    ):
        raise E26Error("strict DeepCenter verified model config mismatch")


def _validate_inference_receipt(receipt: dict) -> None:
    expected = {
        "schema_version": "biohub.e26_screen.inference_controls.v1", "environment": generation_environment(),
        "python_seed": 0, "numpy_seed": 0, "torch_seed": 0, "torch_initial_seed": 0,
        "torch_num_threads": 1, "torch_num_interop_threads": 1, "required_device": "cpu",
    }
    if _json_bytes(receipt) != _json_bytes(expected):
        raise E26Error("inference seed/thread/device/environment receipt mismatch")


def _validate_timing(timing: dict, limits: dict, *, core: bool = False) -> None:
    keys = {"wall_seconds", "peak_rss_bytes", "ram_scope"} | ({"core_wall_seconds"} if core else set())
    _require_keys(timing, keys, "runtime measurement")
    _require_finite_number(timing["wall_seconds"], "wall duration", json_number=True)
    _require_count(timing["peak_rss_bytes"], "measured self RSS")
    if (
        not 0 <= timing["wall_seconds"] <= limits["wall_seconds"]
        or timing["peak_rss_bytes"] > limits["ram_limit_bytes"] or timing["ram_scope"] != "self_process"
    ):
        raise E26Error("runtime measurement violates the frozen self-process budget")
    if core:
        _require_finite_number(timing["core_wall_seconds"], "core duration", json_number=True)
        if not 0 <= timing["core_wall_seconds"] <= timing["wall_seconds"]:
            raise E26Error("core duration cannot exceed the complete child duration")


def _validate_events(events: list, control: dict, final_timing: dict) -> None:
    datasets = control["datasets"]
    if type(events) is not list or len(events) != 3 * len(datasets):
        raise E26Error("incomplete start/statistics/finish event sequence")
    previous_wall, previous_rss = 0., 0
    for index, row in enumerate(events):
        _require_keys(row, {"event", "sequence", "dataset", "timing"}, "dataset event")
        if (
            type(row["sequence"]) is not int or row["sequence"] != index // 3
            or row["event"] != ("start", "raw_stats", "finish")[index % 3]
            or row["dataset"] != datasets[index // 3]
        ):
            raise E26Error("dataset event order mismatch")
        timing = row["timing"]
        _validate_timing(timing, control["limits"])
        if (
            not previous_wall <= timing["wall_seconds"] <= final_timing["wall_seconds"]
            or not previous_rss <= timing["peak_rss_bytes"] <= final_timing["peak_rss_bytes"]
        ):
            raise E26Error("dataset clocks/high-water RSS are inconsistent")
        previous_wall, previous_rss = timing["wall_seconds"], timing["peak_rss_bytes"]


def _child_config(control: dict) -> PostprocConfig:
    arm = control["arm"]
    inputs = control["generation_input_binding"]
    image_root = Path(inputs["public4" if arm == ARM_ORDER[0] else "eval36"]["image_root"])
    checkpoint, manifest = (Path(inputs[key]["selected_path"]) for key in ("checkpoint", "manifest"))
    cfg = build_arm_config(arm, image_root, checkpoint, manifest)
    baseline = build_arm_config("baseline", _PROJECT_ROOT / "data/train", checkpoint, manifest)
    candidate = build_arm_config("candidate", _PROJECT_ROOT / "data/train", checkpoint, manifest)
    validate_config_pair(baseline, candidate, image_root=_PROJECT_ROOT / "data/train",
                         checkpoint=checkpoint, manifest=manifest)
    return cfg


def _load_child_model(cfg: PostprocConfig, inputs: dict) -> tuple[dict, dict]:
    # Called after initialize_inference_runtime, once per fresh Python process.
    import torch

    from biohub.public_postproc.deepcenter import load_deepcenter_veto_detector_strict

    result = load_deepcenter_veto_detector_strict(
        cfg, Path(inputs["checkpoint"]["selected_path"]), Path(inputs["manifest"]["selected_path"]),
    )
    if type(result) is not tuple or len(result) != 2:
        raise E26Error("strict loader must return (bundle, receipt)")
    bundle, receipt = result
    _validate_deepcenter_receipt(receipt, inputs)
    if (
        type(bundle) is not dict or bundle.get("torch") is not torch or str(bundle.get("device")) != "cpu"
        or type(bundle.get("checkpoint_epoch")) is not int or bundle["checkpoint_epoch"] != 2
        or bundle.get("path") != Path(inputs["checkpoint"]["selected_path"])
    ):
        raise E26Error("actual strict-loader bundle identity/device mismatch")
    model = bundle.get("model")
    if not isinstance(model, torch.nn.Module) or model.training:
        raise E26Error("actual model must be a Torch module in eval mode")
    parameters = list(model.parameters())
    if not parameters or any(str(p.device) != "cpu" or p.dtype != torch.float32 for p in parameters):
        raise E26Error("actual model parameters must be CPU float32")
    if any(str(b.device) != "cpu" or (b.is_floating_point() and b.dtype != torch.float32) for b in model.buffers()):
        raise E26Error("actual model buffers must be CPU with floating buffers in float32")
    return bundle, receipt


def _validate_screen_bounds(payload: dict, csv_path: Path, shapes: dict) -> None:
    from biohub.output_bounds import OutputBoundsError
    from biohub.screen_output_bounds import verify_screen_output_bounds

    try:
        verify_screen_output_bounds(payload, csv_path, shapes=shapes)
    except OutputBoundsError as exc:
        raise E26Error(f"screen output bounds validation failed: {exc}") from exc


def run_generation_child(control_path: Path, expected_sha256: str) -> dict:
    """One exact core call in a fresh interpreter; no GT registration parsing."""
    started = time.monotonic()
    _absolute_path(control_path, "child control path")
    if len(control_path.parents) < 3:
        raise E26Error("invalid child control path")
    directory = _arm_directory(control_path.parents[2].name, control_path.parent.name)
    if control_path != directory / "CHILD_CONTROL.json":
        raise E26Error("child must use its canonical generation-only control path")
    control = read_json_bound(control_path, expected_sha256)
    validate_generation_child_control(control)
    if directory != _arm_directory(control["run_id"], control["arm"]):
        raise E26Error("child control path/identity mismatch")
    control_ref = _artifact_reference(control_path)
    if control_ref["sha256"] != expected_sha256:
        raise E26Error("child control changed before launch")
    write_json_exclusive(directory / _ARM_ARTIFACTS["started"], {
        "run_id": control["run_id"], "arm": control["arm"], "pid": os.getpid(), "control": control_ref,
        "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    inference = initialize_inference_runtime()
    _validate_inference_receipt(inference)
    write_json_exclusive(directory / _ARM_ARTIFACTS["inference"], inference)
    _verify_child_bindings(control)
    limits = control["limits"]

    def measure() -> dict:
        return check_runtime_budget(started, wall_limit_seconds=limits["wall_seconds"],
                                    ram_limit_bytes=limits["ram_limit_bytes"])

    measure()
    cfg = _child_config(control)
    write_json_exclusive(directory / _ARM_ARTIFACTS["config"], control["config"])
    inputs = control["generation_input_binding"]
    bundle, weight_receipt = _load_child_model(cfg, inputs)
    write_json_exclusive(directory / _ARM_ARTIFACTS["deepcenter"], weight_receipt)
    measure()
    from biohub.io import open_volume
    from biohub.output_bounds import OutputBoundsError
    from biohub.public_postproc.pipeline import run_postproc_core
    from biohub.screen_output_bounds import ScreenNodeSerializer

    selected = inputs["public4" if control["arm"] == ARM_ORDER[0] else "eval36"]
    shapes = {}
    for video in selected["videos"]:
        volume = open_volume(Path(video["image_inventory"]["selected_path"]))
        metadata = video["metadata"]
        if (list(volume.shape) != metadata["shape_tzyx"] or list(volume.scale) != metadata["scale_zyx"]
                or str(volume.dtype) != metadata["dtype"]):
            raise E26Error("core image reader metadata differs from explicit registration")
        shapes[video["dataset"]] = volume.shape
    serializer = ScreenNodeSerializer(shapes)
    events, raw_rows = [], []
    loader_calls = 0

    def loader(actual_cfg):
        nonlocal loader_calls
        if actual_cfg is not cfg or loader_calls != 0:
            raise E26Error("core loader must be called exactly once with the original config")
        loader_calls += 1
        return bundle  # NOT the (bundle, receipt) tuple.

    def event(kind, sequence, dataset):
        index = len(events)
        if (
            type(sequence) is not int or index >= len(control["datasets"]) * 3 or sequence != index // 3
            or dataset != control["datasets"][index // 3] or kind != ("start", "raw_stats", "finish")[index % 3]
        ):
            raise E26Error("core dataset hooks were missing, duplicated or reordered")
        events.append({"event": kind, "sequence": sequence, "dataset": dataset, "timing": measure()})
        print(f"E26 {control['arm']} {kind} {sequence} {dataset}", flush=True)

    def raw_stats(mapping):
        row = dict(mapping)
        event("raw_stats", len(raw_rows), row.get("dataset"))
        _json_bytes(row)
        raw_rows.append(row)

    core_started = time.monotonic()
    csv_path = directory / _ARM_ARTIFACTS["csv"]
    try:
        core_result = run_postproc_core(
            tuple(Path(selected["raw_inventory"]["selected_path"]) / f"{s}.geff" for s in control["datasets"]),
            csv_path, cfg, deepcenter_loader=loader,
            dataset_start_hook=lambda seq, name: event("start", seq, name),
            dataset_finish_hook=lambda seq, name: event("finish", seq, name), raw_stats_hook=raw_stats,
            write_run_stats_output=False, exclusive_output=True, node_serializer=serializer,
        )
    except OutputBoundsError as exc:
        raise E26Error(f"screen node serialization failed: {exc}") from exc
    finally:
        core_wall = time.monotonic() - core_started
        # Preserve observations even if core/CSV validation fails. These files
        # alone never certify a complete arm; the normal validator still gates it.
        for key, value in (("events", events), ("raw_statistics", raw_rows),
                           ("output_bounds", serializer.snapshot())):
            write_json_exclusive(directory / _ARM_ARTIFACTS[key], value)
    if loader_calls != 1:
        raise E26Error("core did not use the single injected strict model")
    csv_before = _artifact_reference(csv_path)
    report = validate_generated_csv(csv_path, datasets=tuple(control["datasets"]), shapes=shapes)
    _validate_screen_bounds(serializer.snapshot(), csv_path, shapes)
    normalized = validate_raw_statistics(raw_rows, arm=control["arm"], csv_report=report)
    expected_core = {key: report[key] for key in ("datasets", "total_nodes", "total_edges", "total_rows")}
    expected_core["run_stats"] = None
    if _json_bytes(core_result) != _json_bytes(expected_core):
        raise E26Error("core returned counts inconsistent with reparsed CSV")
    for key, value in (("normalized_statistics", normalized), ("csv_validation", report)):
        write_json_exclusive(directory / _ARM_ARTIFACTS[key], value)
    _verify_artifact(csv_before, csv_path)
    _verify_artifact(control_ref, control_path)
    _verify_child_bindings(control)
    artifact_refs = {key: _artifact_reference(directory / name) for key, name in _ARM_ARTIFACTS.items()}
    if artifact_refs["csv"] != csv_before:
        raise E26Error("CSV changed between validation and final artifact binding")
    timing = {**measure(), "core_wall_seconds": core_wall}
    _validate_timing(timing, limits, core=True)
    _validate_events(events, control, timing)
    result = {
        "schema_version": ARM_RESULT_SCHEMA, "run_id": control["run_id"], "candidate_id": CANDIDATE_ID,
        "arm": control["arm"], "submission_authorized": False, "control": control_ref,
        "artifacts": artifact_refs,
        "core_result": core_result, "timing": timing,
    }
    return write_json_exclusive(directory / "ARM_RESULT.json", result)


def verify_arm_result(control: dict, result_reference: dict) -> dict:
    """Reparse every saved artifact and CSV; receipt labels alone do not pass."""
    directory = _arm_directory(control["run_id"], control["arm"])
    result = _artifact_json(result_reference, directory / "ARM_RESULT.json")
    _require_keys(result, {
        "schema_version", "run_id", "candidate_id", "arm", "submission_authorized", "control",
        "artifacts", "core_result", "timing",
    }, "arm result")
    if (
        result["schema_version"] != ARM_RESULT_SCHEMA or result["run_id"] != control["run_id"]
        or result["arm"] != control["arm"] or result["candidate_id"] != CANDIDATE_ID
        or result["submission_authorized"] is not False
    ):
        raise E26Error("arm result identity/schema mismatch")
    saved_control = _artifact_json(result["control"], directory / "CHILD_CONTROL.json")
    if _json_bytes(saved_control) != _json_bytes(control):
        raise E26Error("child control differs from original generation-only dispatch")
    _require_keys(result["artifacts"], set(_ARM_ARTIFACTS), "arm artifact closure")
    artifacts = result["artifacts"]
    values = {key: _artifact_json(artifacts[key], directory / name)
              for key, name in _ARM_ARTIFACTS.items() if key != "csv"}
    _verify_artifact(artifacts["csv"], directory / _ARM_ARTIFACTS["csv"])
    if _json_bytes(values["config"]) != _json_bytes(control["config"]):
        raise E26Error("saved effective config mismatch")
    started = values["started"]
    _require_keys(started, {"run_id", "arm", "pid", "control", "created_utc"}, "arm start marker")
    if (
        started["run_id"] != control["run_id"] or started["arm"] != control["arm"]
        or type(started["pid"]) is not int or started["pid"] <= 0 or started["control"] != result["control"]
        or type(started["created_utc"]) is not str
    ):
        raise E26Error("invalid arm start marker")
    _validate_inference_receipt(values["inference"])
    inputs = control["generation_input_binding"]
    _validate_deepcenter_receipt(values["deepcenter"], inputs)
    selected = inputs["public4" if control["arm"] == ARM_ORDER[0] else "eval36"]
    shapes = {video["dataset"]: tuple(video["metadata"]["shape_tzyx"]) for video in selected["videos"]}
    report = validate_generated_csv(directory / _ARM_ARTIFACTS["csv"],
                                    datasets=tuple(control["datasets"]), shapes=shapes)
    if _json_bytes(report) != _json_bytes(values["csv_validation"]):
        raise E26Error("saved CSV validation does not match actual predictions")
    _validate_screen_bounds(values["output_bounds"], directory / _ARM_ARTIFACTS["csv"], shapes)
    expected_core = {key: report[key] for key in ("datasets", "total_nodes", "total_edges", "total_rows")}
    expected_core["run_stats"] = None
    if _json_bytes(result["core_result"]) != _json_bytes(expected_core):
        raise E26Error("saved core counts disagree with CSV")
    normalized = validate_raw_statistics(values["raw_statistics"], arm=control["arm"], csv_report=report)
    if _json_bytes(normalized) != _json_bytes(values["normalized_statistics"]):
        raise E26Error("saved normalized telemetry differs from original raw telemetry")
    _validate_timing(result["timing"], control["limits"], core=True)
    _validate_events(values["events"], control, result["timing"])
    # Ensure none of the reads above raced a change after its initial hash.
    for key, name in _ARM_ARTIFACTS.items():
        _verify_artifact(artifacts[key], directory / name)
    _verify_artifact(result_reference, directory / "ARM_RESULT.json")
    return result


def _launch_generation_child(control_path: Path, expected_sha256: str, timeout_seconds: float) -> dict:
    return _launch_control_process(control_path, expected_sha256, timeout_seconds, command="_arm")


def _launch_control_process(
    control_path: Path, expected_sha256: str, timeout_seconds: float, *, command: str,
) -> dict:
    """One subprocess, streamed logs, termination/reap on timeout; never retry."""
    if command not in ("_arm", "_score"):
        raise E26Error("unknown internal process command")
    _require_finite_number(timeout_seconds, "supervisor child timeout", json_number=True)
    if timeout_seconds <= 0:
        raise E26Error("no wall budget remains for a child")
    stdout_path = _plain_artifact_path(control_path.parent / "stdout.log")
    stderr_path = _plain_artifact_path(control_path.parent / "stderr.log")
    argv = [sys.executable, str(_PROJECT_ROOT / "scripts/e26_screen.py"), command,
            "--control", str(control_path), "--control-sha256", expected_sha256]
    environment = generation_environment()
    started = time.monotonic()
    process = None
    timed_out = False

    def stop_and_reap():
        if process is None:
            return
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
        else:
            process.wait()

    try:
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            process = subprocess.Popen(argv, cwd=_PROJECT_ROOT, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                returncode = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                stop_and_reap()
                returncode = process.returncode
            except BaseException:
                stop_and_reap()
                raise
            stdout.flush()
            stderr.flush()
            os.fsync(stdout.fileno())
            os.fsync(stderr.fileno())
    except (OSError, subprocess.SubprocessError) as exc:
        stop_and_reap()
        raise E26Error("child launch/termination failed; evidence retained") from exc
    finished = time.monotonic()
    return {
        "schema_version": "biohub.e26_screen.child_process.v1", "pid": process.pid, "returncode": returncode,
        "timed_out": timed_out, "wall_seconds": finished - started, "timeout_seconds": timeout_seconds,
        "started_monotonic": started, "finished_monotonic": finished,
        "argv": argv, "cwd": str(_PROJECT_ROOT), "environment": environment,
        "stdout": _artifact_reference(stdout_path), "stderr": _artifact_reference(stderr_path),
    }


def _verify_child_process(receipt: dict, control_reference: dict, control: dict) -> None:
    _verify_control_process(receipt, control_reference, command="_arm",
                            wall_limit=control["limits"]["wall_seconds"])
    if Path(control_reference["path"]).parent != _arm_directory(control["run_id"], control["arm"]):
        raise E26Error("generation process control directory differs from its arm")


def _verify_control_process(receipt: dict, control_reference: dict, *, command: str, wall_limit: float) -> None:
    _require_keys(receipt, {
        "schema_version", "pid", "returncode", "timed_out", "wall_seconds", "timeout_seconds",
        "started_monotonic", "finished_monotonic", "argv", "cwd", "environment", "stdout", "stderr",
    }, "child process receipt")
    for key in ("pid", "returncode"):
        if type(receipt[key]) is not int:
            raise E26Error("child process pid/exit code must be integers")
    for key in ("wall_seconds", "timeout_seconds", "started_monotonic", "finished_monotonic"):
        _require_finite_number(receipt[key], key, json_number=True)
    expected_argv = [sys.executable, str(_PROJECT_ROOT / "scripts/e26_screen.py"), command,
                     "--control", control_reference["path"], "--control-sha256", control_reference["sha256"]]
    if (
        receipt["schema_version"] != "biohub.e26_screen.child_process.v1" or receipt["pid"] <= 0
        or receipt["returncode"] != 0 or receipt["timed_out"] is not False
        or not 0 <= receipt["wall_seconds"] <= receipt["timeout_seconds"]
        or not 0 < receipt["timeout_seconds"] <= wall_limit
        or not 0 <= receipt["started_monotonic"] <= receipt["finished_monotonic"]
        or receipt["wall_seconds"] != receipt["finished_monotonic"] - receipt["started_monotonic"]
        or receipt["argv"] != expected_argv or receipt["cwd"] != str(_PROJECT_ROOT)
        or receipt["environment"] != generation_environment()
    ):
        raise E26Error("child process failed, exceeded budget, or violated its explicit launch contract")
    directory = Path(control_reference["path"]).parent
    for key in ("stdout", "stderr"):
        _verify_artifact(receipt[key], directory / f"{key}.log")


def _parent_generation_control(public: dict, public_ref: dict, private_ref: dict) -> dict:
    return {
        "schema_version": "biohub.e26_screen.control.v1", "run_id": public["run_id"],
        "candidate_id": CANDIDATE_ID, "submission_authorized": False, "arm_order": list(ARM_ORDER),
        "registrations": {"public": public_ref, "private": private_ref}, "budget": public["budget"],
        "source_binding": public["source_binding"], "scientific_binding": public["scientific_binding"],
        "dependency_binding": public["dependency_binding"],
        "generation_input_binding": public["generation_input_binding"],
    }


def _record_generation_failure(run: Path, control: dict, operation: str, error: BaseException) -> None:
    # Restrict diagnostics to known new-run files; do not follow output aliases.
    present, missing, unreadable = [], [], []
    paths = [run / "CONTROL.json"]
    for arm in ARM_ORDER:
        paths.extend(run / "generation" / arm / name for name in (
            "CHILD_CONTROL.json", "PROCESS_RESULT.json", "ARM_RESULT.json", "stdout.log", "stderr.log",
            *_ARM_ARTIFACTS.values(),
        ))
    for path in paths:
        if not path.exists() and not path.is_symlink():
            missing.append(str(path))
            continue
        try:
            present.append({**_artifact_reference(path), "validated": False})
        except E26Error:
            unreadable.append(str(path))
    write_json_exclusive(run / "GENERATION_FAILURE.json", {
        "schema_version": "biohub.e26_screen.generation_failure.v1", "run_id": control["run_id"],
        "candidate_id": CANDIDATE_ID, "submission_authorized": False, "operation": operation,
        "error_type": type(error).__name__, "error": str(error), "registrations": control["registrations"],
        "present_unvalidated_artifacts": present, "missing_artifacts": missing, "unreadable_artifacts": unreadable,
    })


def generate_screen(public_path: Path, *, expected_public_sha256: str, expected_private_sha256: str) -> dict:
    """Serial public4/baseline/candidate supervision. No scoring or submission."""
    started = time.monotonic()
    public = verify_registration_pair(public_path, expected_public_sha256=expected_public_sha256,
                                      expected_private_sha256=expected_private_sha256)
    registration, run = _run_paths(public["run_id"])
    public_ref, private_ref = (_artifact_reference(registration / name)
                               for name in ("PREREGISTRATION.json", "GT_BINDING.json"))
    if public_ref["sha256"] != expected_public_sha256 or private_ref["sha256"] != expected_private_sha256:
        raise E26Error("registration changed before generation run creation")
    _ensure_plain_directory(run.parent)
    _plain_artifact_path(run)
    try:
        run.mkdir(mode=0o700)
    except OSError as exc:
        raise E26Error("generation run already exists or cannot be exclusively created") from exc
    control = _parent_generation_control(public, public_ref, private_ref)
    operation = "parent_control"
    arms = []
    budget = public["budget"]

    def remaining_wall():
        measurement = check_runtime_budget(
            started, wall_limit_seconds=budget["generation_wall_seconds"], ram_limit_bytes=budget["ram"]["limit_bytes"],
        )
        return budget["generation_wall_seconds"] - measurement["wall_seconds"]

    try:
        control_ref = write_json_exclusive(run / "CONTROL.json", control)
        remaining_wall()
        (run / "generation").mkdir()
        for arm in ARM_ORDER:
            operation = arm
            directory = _arm_directory(public["run_id"], arm)
            _plain_artifact_path(directory)
            directory.mkdir()
            child = derive_generation_child_control(public, arm)
            child_ref = write_json_exclusive(directory / "CHILD_CONTROL.json", child)
            process = _launch_generation_child(
                Path(child_ref["path"]), child_ref["sha256"], min(child["limits"]["wall_seconds"], remaining_wall()),
            )
            process_ref = write_json_exclusive(directory / "PROCESS_RESULT.json", process)
            _verify_child_process(process, child_ref, child)
            result_ref = _artifact_reference(directory / "ARM_RESULT.json")
            arm_row = {"arm": arm, "control": child_ref, "process": process_ref, "result": result_ref}
            _verify_completed_arm(arm_row, public)
            remaining_wall()
            arms.append(arm_row)
        operation = "final_integrity"
        verify_registration_pair(public_path, expected_public_sha256=expected_public_sha256,
                                 expected_private_sha256=expected_private_sha256)
        _verify_artifact(control_ref, run / "CONTROL.json")
        for row in arms:
            _verify_completed_arm(row, public)
        timing = check_runtime_budget(started, wall_limit_seconds=budget["generation_wall_seconds"],
                                      ram_limit_bytes=budget["ram"]["limit_bytes"])
        _verify_serial_intervals(arms, public, timing)
        seal = {
            "schema_version": GENERATION_SEAL_SCHEMA, "run_id": public["run_id"], "candidate_id": CANDIDATE_ID,
            "submission_authorized": False, "status": "GENERATION_COMPLETE_NOT_SCORED", "control": control_ref,
            "registrations": control["registrations"], "arms": arms, "supervisor_timing": timing,
        }
        return write_json_exclusive(run / "GENERATION_SEAL.json", seal)
    except BaseException as exc:
        _record_generation_failure(run, control, operation, exc)
        raise


def _verify_completed_arm(row: dict, public: dict) -> dict:
    _require_keys(row, {"arm", "control", "process", "result"}, "completed arm")
    directory = _arm_directory(public["run_id"], row["arm"])
    child = derive_generation_child_control(public, row["arm"])
    saved = _artifact_json(row["control"], directory / "CHILD_CONTROL.json")
    if _json_bytes(saved) != _json_bytes(child):
        raise E26Error("sealed child control differs from registered generation fields")
    process = _artifact_json(row["process"], directory / "PROCESS_RESULT.json")
    _verify_child_process(process, row["control"], child)
    result = verify_arm_result(child, row["result"])
    marker = _artifact_json(result["artifacts"]["started"], directory / _ARM_ARTIFACTS["started"])
    if marker["pid"] != process["pid"] or result["timing"]["wall_seconds"] > process["wall_seconds"]:
        raise E26Error("sealed process/arm marker pid or complete-process duration mismatch")
    if row["arm"] == ARM_ORDER[0] and result["artifacts"]["csv"]["sha256"] != _WEIGHT_PINS["reference"][1]:
        raise E26Error("sealed public4 predictions fail byte parity")
    return result


def _verify_serial_intervals(arms: list, public: dict, supervisor_timing: dict) -> None:
    previous_finish, process_wall_sum = 0., 0.
    for row in arms:
        process = _artifact_json(row["process"], _arm_directory(public["run_id"], row["arm"]) / "PROCESS_RESULT.json")
        if process["started_monotonic"] < previous_finish:
            raise E26Error("generation process intervals overlap or are out of order")
        previous_finish = process["finished_monotonic"]
        process_wall_sum += process["wall_seconds"]
    if process_wall_sum > supervisor_timing["wall_seconds"]:
        raise E26Error("supervisor duration cannot be shorter than its serial children")


def verify_generation_seal(
    seal_path: Path, *, expected_seal_sha256: str, expected_public_sha256: str, expected_private_sha256: str,
) -> dict:
    """Verify generation evidence before the separate scorer may read any GT."""
    _absolute_path(seal_path, "generation seal path")
    registration, run = _run_paths(seal_path.parent.name)
    failure = run / "GENERATION_FAILURE.json"
    if seal_path != run / "GENERATION_SEAL.json" or failure.exists() or failure.is_symlink():
        raise E26Error("generation seal path invalid or a failure receipt exists")
    seal = read_json_bound(seal_path, expected_seal_sha256)
    _require_keys(seal, {
        "schema_version", "run_id", "candidate_id", "submission_authorized", "status", "control",
        "registrations", "arms", "supervisor_timing",
    }, "generation seal")
    if (
        seal["schema_version"] != GENERATION_SEAL_SCHEMA or seal["run_id"] != run.name
        or seal["candidate_id"] != CANDIDATE_ID or seal["submission_authorized"] is not False
        or seal["status"] != "GENERATION_COMPLETE_NOT_SCORED"
        or type(seal["arms"]) is not list or len(seal["arms"]) != len(ARM_ORDER)
    ):
        raise E26Error("invalid/incomplete generation seal identity")
    public = verify_registration_pair(
        registration / "PREREGISTRATION.json", expected_public_sha256=expected_public_sha256,
        expected_private_sha256=expected_private_sha256,
    )
    _require_keys(seal["registrations"], {"public", "private"}, "sealed registration references")
    for key, name, sha in (("public", "PREREGISTRATION.json", expected_public_sha256),
                           ("private", "GT_BINDING.json", expected_private_sha256)):
        ref = seal["registrations"][key]
        _verify_artifact(ref, registration / name)
        if ref["sha256"] != sha:
            raise E26Error("seal binds a substituted registration rather than original dispatch")
    control = _artifact_json(seal["control"], run / "CONTROL.json")
    expected = _parent_generation_control(public, seal["registrations"]["public"], seal["registrations"]["private"])
    if _json_bytes(control) != _json_bytes(expected):
        raise E26Error("parent control differs from original registration")
    for row, arm in zip(seal["arms"], ARM_ORDER, strict=True):
        if type(row) is not dict or row.get("arm") != arm:
            raise E26Error("generation seal arm order mismatch")
        _verify_completed_arm(row, public)
    _validate_timing(seal["supervisor_timing"], {
        "wall_seconds": public["budget"]["generation_wall_seconds"],
        "ram_limit_bytes": public["budget"]["ram"]["limit_bytes"],
    })
    _verify_serial_intervals(seal["arms"], public, seal["supervisor_timing"])
    _verify_artifact(
        {"path": str(seal_path), "sha256": expected_seal_sha256, "bytes": seal_path.stat().st_size}, seal_path,
    )
    return {"seal": seal, "public_registration": public}


SCORE_CONTROL_SCHEMA = "biohub.e26_screen.score_control.v1"
SCORE_STAGE_SCHEMA = "biohub.e26_screen.score_stage.v1"
SCORE_RESULT_SCHEMA = "biohub.e26_screen.score_result.v1"
_SCORE_COUNTS = ("edge_tp", "edge_fp", "edge_fn", "division_tp", "division_fp", "division_fn", "num_pred_nodes")
_SCORE_VALUES = ("node_recall", "total_node_ratio", "edge_jaccard", "adj_edge_jaccard")
_DIVISION_FREE_REASON = "official division TP+FP+FN is zero; division J is undefined"


def _validated_score_rows(rows: list, datasets: tuple[str, ...], counts: dict) -> list[dict]:
    if type(rows) is not list or len(rows) != len(datasets):
        raise E26Error("official rows must cover the entire stage without omissions")
    by_video = {}
    for row in rows:
        _require_keys(row, {"dataset", *_SCORE_COUNTS, *_SCORE_VALUES}, "official metric row")
        name = row["dataset"]
        if type(name) is not str or name not in datasets or name in by_video:
            raise E26Error("official rows contain duplicate/extra/wrong video identities")
        for key in _SCORE_COUNTS:
            _require_count(row[key], f"official {name}.{key}")
        for key in _SCORE_VALUES:
            _require_finite_number(row[key], f"official {name}.{key}", json_number=True)
        if (
            row["num_pred_nodes"] != counts[name]["nodes"] or not 0 <= row["node_recall"] <= 1
            or row["edge_jaccard"] < 0 or row["adj_edge_jaccard"] < 0
            or sum(row[key] for key in _SCORE_COUNTS[:3]) <= 0
        ):
            raise E26Error("official counts/recall/Jaccard disagree with valid sealed predictions")
        by_video[name] = dict(row)
    return [by_video[name] for name in datasets]


def _normalized_official_summary(summary: dict, rows: list[dict]) -> dict:
    _require_keys(summary, {
        "n", "n_adj", "edge_jaccard", "division_jaccard", "division_tp", "division_fp", "division_fn",
        "node_recall", "adj_edge_jaccard", "score",
    }, "official summary")
    for key in ("n", "n_adj", "division_tp", "division_fp", "division_fn"):
        _require_count(summary[key], f"official summary {key}")
    if summary["n"] != len(rows) or summary["n_adj"] != len(rows) or not rows:
        raise E26Error("official summary silently skipped rows or adjusted scores")
    for key in ("division_tp", "division_fp", "division_fn"):
        if summary[key] != sum(row[key] for row in rows):
            raise E26Error("official division count totals differ from preserved rows")
    for key in ("edge_jaccard", "node_recall", "adj_edge_jaccard", "score"):
        _require_finite_number(summary[key], f"official summary {key}", json_number=True)
    result = dict(summary)
    denominator = sum(summary[key] for key in ("division_tp", "division_fp", "division_fn"))
    if denominator == 0:
        if type(summary["division_jaccard"]) is not float or not math.isnan(summary["division_jaccard"]):
            raise E26Error("division-free official summary must retain its undefined value")
        if summary["score"] != summary["adj_edge_jaccard"]:
            raise E26Error("division-free official combined score differs from adjusted edge score")
        result["division_jaccard"] = None
        result["division_jaccard_undefined_reason"] = _DIVISION_FREE_REASON
    else:
        _require_finite_number(summary["division_jaccard"], "official division J", json_number=True)
        result["division_jaccard_undefined_reason"] = None
    _json_bytes(result)
    return result


def _official_group(rows: list[dict]) -> dict:
    from biohub.evaluate import summarise

    values = [{key: value for key, value in row.items() if key != "dataset"} for row in rows]
    return {
        "datasets": [row["dataset"] for row in rows],
        "summary": _normalized_official_summary(summarise(values), rows),
        "count_totals": {key: sum(row[key] for row in rows) for key in _SCORE_COUNTS},
    }


def _score_arm_record(rows: list[dict], stage: str, counts: dict) -> dict:
    ordered = _validated_score_rows(rows, _STAGE_VIDEOS[stage], counts)
    return {
        "rows": ordered,
        "singletons": [{"dataset": row["dataset"], **_official_group([row])} for row in ordered],
        "groups": {name: _official_group(ordered if name == stage else
                                        [row for row in ordered if row["dataset"].startswith(name + "_")])
                   for name in (stage, "44b6", "6bba")},
    }


def _paired_score_record(stage: str, arms: dict, csv_counts: dict) -> dict:
    baseline, candidate = arms["baseline"], arms["candidate"]
    per_video, diagnostics = [], []
    for index, name in enumerate(_STAGE_VIDEOS[stage]):
        b, c = baseline["rows"][index], candidate["rows"][index]
        delta = candidate["singletons"][index]["summary"]["score"] - baseline["singletons"][index]["summary"]["score"]
        per_video.append({"dataset": name, "combined_score_delta": delta})
        diagnostics.append({
            "dataset": name, "official_deltas": {key: c[key] - b[key] for key in (*_SCORE_COUNTS, *_SCORE_VALUES)},
            "topology_deltas": {key: csv_counts["candidate"][name][key] - csv_counts["baseline"][name][key]
                                for key in ("nodes", "edges", "forks")},
        })
    deltas, reasons = {}, {}
    for group in (stage, "44b6", "6bba"):
        b, c = (arms[arm]["groups"][group]["summary"] for arm in ("baseline", "candidate"))
        undefined = {arm: arms[arm]["groups"][group]["summary"]["division_jaccard_undefined_reason"]
                     for arm in ("baseline", "candidate")
                     if arms[arm]["groups"][group]["summary"]["division_jaccard"] is None}
        deltas[group] = {key: c[key] - b[key] for key in ("score", "adj_edge_jaccard")}
        deltas[group]["division_jaccard"] = None if undefined else c["division_jaccard"] - b["division_jaccard"]
        reasons[group] = undefined
    payload = {"schema_version": GATE_INPUT_SCHEMA, "stage": stage,
               "per_video": per_video, "aggregate_deltas": deltas}
    values = [row["combined_score_delta"] for row in per_video]
    return {
        "payload": payload, "gate": evaluate_gate(stage, payload), "per_video_diagnostics": diagnostics,
        "division_delta_undefined_reasons": reasons,
        "score_changed_videos": sum(value != 0 for value in values),
        "positive_videos": sum(value > 0 for value in values), "negative_videos": sum(value < 0 for value in values),
        "worst_videos": [row["dataset"] for row in per_video if row["combined_score_delta"] == min(values)],
    }


def _stage_csv_rows(full_csv: Path, datasets: tuple[str, ...]):
    """Only global IDs change. Preserve the original string fields and row order."""
    index = 0
    with full_csv.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(_E26_CSV_COLUMNS):
            raise E26Error("sealed full CSV header changed")
        for row in reader:
            if row["dataset"] in datasets:
                original_id = row["id"]
                yield original_id, {**row, "id": str(index)}
                index += 1


def _stage_subset(full_reference: dict, output: Path, datasets: tuple[str, ...], shapes: dict, *, create: bool) -> dict:
    full_path = Path(full_reference["path"])
    _verify_artifact(full_reference, full_path)
    _plain_artifact_path(output)
    mapping, count = hashlib.sha256(), 0
    if create:
        with output.open("x", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_E26_CSV_COLUMNS)
            writer.writeheader()
            for original, row in _stage_csv_rows(full_path, datasets):
                writer.writerow(row)
                mapping.update(f"{row['id']},{original}\n".encode("ascii"))
                count += 1
            handle.flush()
            os.fsync(handle.fileno())
    else:
        with output.open(newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != list(_E26_CSV_COLUMNS):
                raise E26Error("subset CSV header mismatch")
            for original, expected in _stage_csv_rows(full_path, datasets):
                if next(reader, None) != expected:
                    raise E26Error("subset predictions differ from sealed full CSV")
                mapping.update(f"{expected['id']},{original}\n".encode("ascii"))
                count += 1
            if next(reader, None) is not None:
                raise E26Error("subset CSV has extra rows")
    reference = _artifact_reference(output)
    report = validate_generated_csv(output, datasets=datasets, shapes={name: shapes[name] for name in datasets})
    _verify_artifact(reference, output)
    _verify_artifact(full_reference, full_path)
    return {
        "source": full_reference, "csv": reference, "datasets": list(datasets), "validation": report,
        "row_id_mapping": {"rule": "new zero-based global id,original full CSV id; ASCII lines with LF",
                           "sha256": mapping.hexdigest(), "rows": count},
        "predictions_changed": False,
    }


def _verify_scoring_inputs(control: dict) -> dict:
    _require_keys(control, {"schema_version", "run_id", "candidate_id", "submission_authorized", "generation_seal",
                            "expected_public_sha256", "expected_private_sha256"}, "score control")
    _, run = _run_paths(control["run_id"])
    if (control["schema_version"] != SCORE_CONTROL_SCHEMA or control["candidate_id"] != CANDIDATE_ID
            or control["submission_authorized"] is not False):
        raise E26Error("score control schema/identity mismatch")
    seal_ref = control["generation_seal"]
    _verify_artifact(seal_ref, run / "GENERATION_SEAL.json")
    verified = verify_generation_seal(
        run / "GENERATION_SEAL.json", expected_seal_sha256=seal_ref["sha256"],
        expected_public_sha256=control["expected_public_sha256"],
        expected_private_sha256=control["expected_private_sha256"],
    )
    public = verified["public_registration"]
    private_ref = verified["seal"]["registrations"]["private"]
    private = _artifact_json(private_ref, _run_paths(control["run_id"])[0] / "GT_BINDING.json")
    validate_private_registration(private, run_id=control["run_id"],
                                  generation_inputs=public["generation_input_binding"])
    for video in private["videos"]:
        verify_inventory(video["gt_inventory"])  # Opaque integrity only, all 36; no metadata semantics.
    _verify_artifact(private_ref, Path(private_ref["path"]))
    results = {row["arm"]: _artifact_json(row["result"],
                                         _arm_directory(public["run_id"], row["arm"]) / "ARM_RESULT.json")
               for row in verified["seal"]["arms"] if row["arm"] != ARM_ORDER[0]}
    counts = {arm: {row["dataset"]: row for row in _artifact_json(result["artifacts"]["csv_validation"],
                                                              _arm_directory(public["run_id"], arm)
                                                              / "csv_validation.json")["per_dataset"]}
              for arm, result in results.items()}
    return {**verified, "private": private, "arm_results": results, "csv_counts": counts}


def _check_stage_gt(stage: str, inputs: dict) -> dict:
    """The only extra GT semantic reads: exact CURRENT stage, never later videos."""
    from biohub.io import estimated_number_of_nodes, read_scale

    registered = {row["dataset"]: row for row in inputs["private"]["videos"]}
    images = {row["dataset"]: row
              for row in inputs["public_registration"]["generation_input_binding"]["eval36"]["videos"]}
    evidence = []
    for name in _STAGE_VIDEOS[stage]:
        row, image = registered[name], images[name]
        verify_inventory(row["gt_inventory"])
        metadata = bind_image_metadata(image["image_inventory"])
        if _json_bytes(metadata) != _json_bytes(row["image_metadata"]):
            raise E26Error("stage scale/shape binding changed")
        gt = Path(row["gt_inventory"]["selected_path"])
        estimated = estimated_number_of_nodes(gt)
        _require_finite_number(estimated, f"{name} estimated_number_of_nodes", json_number=True)
        if estimated <= 0:
            raise E26Error("estimated_number_of_nodes must be positive")
        scale = read_scale(Path(image["image_inventory"]["selected_path"]))
        if list(scale) != metadata["scale_zyx"]:
            raise E26Error("official scale reader differs from explicit registered scale")
        evidence.append({"dataset": name, "estimated_number_of_nodes": estimated, "scale_zyx": list(scale)})
    return {"stage": stage, "videos": evidence}


def _score_process_control(run_id: str, seal_reference: dict, public_sha: str, private_sha: str) -> dict:
    return {"schema_version": SCORE_CONTROL_SCHEMA, "run_id": run_id, "candidate_id": CANDIDATE_ID,
            "submission_authorized": False, "generation_seal": seal_reference,
            "expected_public_sha256": public_sha, "expected_private_sha256": private_sha}


def _score_shapes(inputs: dict) -> dict:
    return {row["dataset"]: tuple(row["metadata"]["shape_tzyx"])
            for row in inputs["public_registration"]["generation_input_binding"]["eval36"]["videos"]}


def _reparse_score_stages(directory: Path, references: list[dict], inputs: dict) -> list[dict]:
    """Common finalizer for every scientific outcome; never read GT semantics."""
    if type(references) is not list or not 1 <= len(references) <= 3:
        raise E26Error("scoring requires an ordered nonempty stage history")
    saved = []
    for index, ref in enumerate(references):
        stage = ("eval12", "eval24", "eval36")[index]
        path = directory / f"{stage}.json"
        record = _artifact_json(ref, path)
        _require_keys(record, {"schema_version", "stage", "arms", "subsets", "gt_preflight", "paired", "timing",
                              "saved_row_sources", "arm_artifacts"}, "saved score stage")
        if record["schema_version"] != SCORE_STAGE_SCHEMA or record["stage"] != stage:
            raise E26Error("score stage schema/order mismatch")
        if saved and saved[-1]["paired"]["gate"]["status"] != f"SCREEN_{saved[-1]['stage'].upper()}_PASS":
            raise E26Error("a rejected stage cannot have a later stage")
        _require_keys(record["arms"], {"baseline", "candidate"}, "scored arms")
        _require_keys(record["subsets"], set() if stage == "eval36" else {"baseline", "candidate"}, "stage subsets")
        _require_keys(record["gt_preflight"], set() if stage == "eval36" else {"baseline", "candidate"},
                      "stage GT evidence")
        _require_keys(record["arm_artifacts"], set() if stage == "eval36" else {"baseline", "candidate"},
                      "stage arm artifacts")
        if record["saved_row_sources"] != (references[:2] if stage == "eval36" else []):
            raise E26Error("eval36 must bind exactly the two saved stage artifacts")
        for arm in ("baseline", "candidate"):
            _require_keys(record["arms"][arm], {"rows", "singletons", "groups"}, "saved official arm")
            if stage != "eval36":
                saved_arm = _artifact_json(record["arm_artifacts"][arm], directory / f"{stage}_{arm}.json")
                if _json_bytes(saved_arm) != _json_bytes({
                    "stage": stage, "arm": arm, "official": record["arms"][arm],
                    "subset": record["subsets"][arm], "gt_preflight": record["gt_preflight"][arm],
                }):
                    raise E26Error("saved per-arm official evidence differs from completed stage")
                subset = _stage_subset(inputs["arm_results"][arm]["artifacts"]["csv"],
                                       directory / f"{stage}_{arm}.csv", _STAGE_VIDEOS[stage],
                                       _score_shapes(inputs), create=False)
                if _json_bytes(subset) != _json_bytes(record["subsets"][arm]):
                    raise E26Error("saved subset/provenance/validation mismatch")
                preflight = record["gt_preflight"][arm]
                _require_keys(preflight, {"stage", "videos"}, "saved stage GT preflight")
                if preflight["stage"] != stage or type(preflight["videos"]) is not list or (
                        len(preflight["videos"]) != len(_STAGE_VIDEOS[stage])):
                    raise E26Error("saved stage GT preflight count/order mismatch")
                for item, name in zip(preflight["videos"], _STAGE_VIDEOS[stage], strict=True):
                    _require_keys(item, {"dataset", "estimated_number_of_nodes", "scale_zyx"}, "saved GT preflight row")
                    _require_finite_number(item["estimated_number_of_nodes"], "saved estimated nodes", json_number=True)
                    expected_scale = inputs["private"]["videos"][EVAL36.index(name)]["image_metadata"]["scale_zyx"]
                    if (item["dataset"] != name or item["estimated_number_of_nodes"] <= 0
                            or _json_bytes(item["scale_zyx"]) != _json_bytes(expected_scale)):
                        raise E26Error("saved GT preflight values disagree with registration")
                rows = record["arms"][arm].get("rows")
            else:
                rows = [row for earlier in saved for row in earlier["arms"][arm]["rows"]]
            expected = _score_arm_record(rows, stage, inputs["csv_counts"][arm])
            if _json_bytes(expected) != _json_bytes(record["arms"][arm]):
                raise E26Error("saved official rows/singletons/lineages/totals changed")
        paired = _paired_score_record(stage, record["arms"], inputs["csv_counts"])
        if _json_bytes(paired) != _json_bytes(record["paired"]):
            raise E26Error("saved paired diagnostics/gates differ from official rows")
        budget = inputs["public_registration"]["budget"]
        _validate_timing(record["timing"], {"wall_seconds": budget["score_stage_wall_seconds"][stage],
                                            "ram_limit_bytes": budget["ram"]["limit_bytes"]})
        _verify_artifact(ref, path)
        saved.append(record)
    last = saved[-1]["paired"]["gate"]["status"]
    if last in ("SCREEN_EVAL12_PASS", "SCREEN_EVAL24_PASS"):
        raise E26Error("a partial passing stage is not a terminal scientific verdict")
    return saved


def _check_score_entry_runtime() -> None:
    if dict(os.environ) != generation_environment() or "torch" in sys.modules or "biohub.evaluate" in sys.modules:
        raise E26Error("score entry requires a fresh explicitly controlled process without inference/scorer imports")


def run_score_child(control_path: Path, expected_sha256: str) -> dict:
    """Fresh scoring process: verify first, eval12/eval24, saved-row eval36, finalize."""
    started = time.monotonic()
    _absolute_path(control_path, "score control path")
    _, run = _run_paths(control_path.parent.parent.name)
    directory = run / "scoring"
    if control_path != directory / "SCORE_CONTROL.json":
        raise E26Error("score control requires its canonical exclusive directory")
    _check_score_entry_runtime()
    control = read_json_bound(control_path, expected_sha256)
    if control.get("run_id") != run.name:
        raise E26Error("score control run differs from its canonical path")
    control_ref = _artifact_reference(control_path)
    if control_ref["sha256"] != expected_sha256:
        raise E26Error("score control changed before execution")
    write_json_exclusive(directory / "SCORE_STARTED.json", {
        "run_id": run.name, "pid": os.getpid(), "control": control_ref, "environment": dict(os.environ),
    })
    inputs = _verify_scoring_inputs(control)
    # No scoring import precedes the complete generation + private opaque verification above.
    from biohub.evaluate import score_submission

    budget = inputs["public_registration"]["budget"]
    random.seed(0)
    import numpy as np

    np.random.seed(0)

    def measure(origin=started, stage=None):
        total = check_runtime_budget(started, wall_limit_seconds=budget["score_process_wall_seconds"],
                                     ram_limit_bytes=budget["ram"]["limit_bytes"])
        if stage is None:
            return total
        return check_runtime_budget(origin, wall_limit_seconds=budget["score_stage_wall_seconds"][stage],
                                    ram_limit_bytes=budget["ram"]["limit_bytes"])

    references = []
    for stage in ("eval12", "eval24", "eval36"):
        stage_started = time.monotonic()
        measure()
        arms, subsets, preflights, arm_artifacts = {}, {}, {}, {}
        previous = [_artifact_json(ref, directory / f"{name}.json")
                    for ref, name in zip(references, ("eval12", "eval24"), strict=False)] if stage == "eval36" else []
        for arm in ("baseline", "candidate"):
            if stage == "eval36":
                rows = [row for earlier in previous for row in earlier["arms"][arm]["rows"]]
            else:
                subsets[arm] = _stage_subset(inputs["arm_results"][arm]["artifacts"]["csv"],
                                             directory / f"{stage}_{arm}.csv", _STAGE_VIDEOS[stage],
                                             _score_shapes(inputs), create=True)
                preflights[arm] = _check_stage_gt(stage, inputs)
                measure(stage_started, stage)
                print(f"E26 scoring {stage} {arm} started", flush=True)
                summary, rows = score_submission(Path(subsets[arm]["csv"]["path"]), _PROJECT_ROOT / "data/train",
                                                 max_distance=7.0, verbose=False)
                measure(stage_started, stage)
            arms[arm] = _score_arm_record(rows, stage, inputs["csv_counts"][arm])
            if stage != "eval36" and _json_bytes(_normalized_official_summary(summary, arms[arm]["rows"])) != (
                    _json_bytes(arms[arm]["groups"][stage]["summary"])):
                raise E26Error("official wrapper summary differs from official aggregation of preserved rows")
            if stage != "eval36":
                # Preserve a completed baseline even when the candidate later fails.
                arm_artifacts[arm] = write_json_exclusive(directory / f"{stage}_{arm}.json", {
                    "stage": stage, "arm": arm, "official": arms[arm],
                    "subset": subsets[arm], "gt_preflight": preflights[arm],
                })
                print(f"E26 scoring {stage} {arm} saved", flush=True)
        paired = _paired_score_record(stage, arms, inputs["csv_counts"])
        record = {
            "schema_version": SCORE_STAGE_SCHEMA, "stage": stage, "arms": arms, "subsets": subsets,
            "gt_preflight": preflights, "paired": paired, "timing": measure(stage_started, stage),
            "saved_row_sources": list(references) if stage == "eval36" else [], "arm_artifacts": arm_artifacts,
        }
        references.append(write_json_exclusive(directory / f"{stage}.json", record))
        if paired["gate"]["status"] != f"SCREEN_{stage.upper()}_PASS":
            break
    # All REJECT/PASS branches converge here. No later-stage GT semantic calls.
    inputs = _verify_scoring_inputs(control)
    records = _reparse_score_stages(directory, references, inputs)
    _verify_artifact(control_ref, control_path)
    gate = records[-1]["paired"]["gate"]
    return write_json_exclusive(directory / "SCORE_RESULT.json", {
        "schema_version": SCORE_RESULT_SCHEMA, "run_id": run.name, "candidate_id": CANDIDATE_ID,
        "submission_authorized": False, "status": gate["status"], "first_failure": gate["first_failure"],
        "control": control_ref, "started": _artifact_reference(directory / "SCORE_STARTED.json"),
        "stages": references, "gates": [row["paired"]["gate"] for row in records], "timing": measure(),
    })


def _verify_score_child_result(result_ref: dict, control_ref: dict, control: dict, process: dict) -> dict:
    directory = _run_paths(control["run_id"])[1] / "scoring"
    inputs = _verify_scoring_inputs(control)
    saved_control = _artifact_json(control_ref, directory / "SCORE_CONTROL.json")
    if _json_bytes(saved_control) != _json_bytes(control):
        raise E26Error("score control changed since dispatch")
    result = _artifact_json(result_ref, directory / "SCORE_RESULT.json")
    _require_keys(result, {"schema_version", "run_id", "candidate_id", "submission_authorized", "status",
                           "first_failure", "control", "started", "stages", "gates", "timing"}, "score result")
    if (result["schema_version"] != SCORE_RESULT_SCHEMA or result["run_id"] != control["run_id"]
            or result["candidate_id"] != CANDIDATE_ID or result["submission_authorized"] is not False
            or result["control"] != control_ref):
        raise E26Error("score result identity/control/schema mismatch")
    marker = _artifact_json(result["started"], directory / "SCORE_STARTED.json")
    _require_keys(marker, {"run_id", "pid", "control", "environment"}, "score process marker")
    if (marker["run_id"] != control["run_id"] or type(marker["pid"]) is not int
            or marker["pid"] != process["pid"] or marker["control"] != control_ref
            or marker["environment"] != generation_environment()):
        raise E26Error("score child marker/process identity mismatch")
    records = _reparse_score_stages(directory, result["stages"], inputs)
    expected_gates = [record["paired"]["gate"] for record in records]
    final = expected_gates[-1]
    if (_json_bytes(result["gates"]) != _json_bytes(expected_gates)
            or result["status"] != final["status"] or result["first_failure"] != final["first_failure"]):
        raise E26Error("score verdict disagrees with reparsed stage evidence")
    budget = inputs["public_registration"]["budget"]
    _validate_timing(result["timing"], {"wall_seconds": budget["score_process_wall_seconds"],
                                        "ram_limit_bytes": budget["ram"]["limit_bytes"]})
    _verify_control_process(process, control_ref, command="_score", wall_limit=budget["score_process_wall_seconds"])
    if (result["timing"]["wall_seconds"] > process["wall_seconds"]
            or sum(row["timing"]["wall_seconds"] for row in records) > result["timing"]["wall_seconds"]):
        raise E26Error("score stage/child/process durations are inconsistent")
    for row in inputs["seal"]["arms"]:
        generation_process = _artifact_json(row["process"], _arm_directory(control["run_id"], row["arm"])
                                             / "PROCESS_RESULT.json")
        if generation_process["finished_monotonic"] > process["started_monotonic"]:
            raise E26Error("scoring cannot overlap generation")
    _verify_artifact(result_ref, directory / "SCORE_RESULT.json")
    return result


def _record_scoring_failure(directory: Path, control: dict, operation: str, error: BaseException) -> None:
    present, missing, unreadable = [], [], []
    names = ["SCORE_CONTROL.json", "SCORE_STARTED.json", "SCORE_RESULT.json", "PROCESS_RESULT.json",
             "stdout.log", "stderr.log", "SCREEN_RESULT.json", "eval12.json", "eval24.json", "eval36.json"]
    names += [f"{stage}_{arm}.csv" for stage in ("eval12", "eval24") for arm in ("baseline", "candidate")]
    names += [f"{stage}_{arm}.json" for stage in ("eval12", "eval24") for arm in ("baseline", "candidate")]
    for name in names:
        path = directory / name
        if not path.exists() and not path.is_symlink():
            missing.append(str(path))
            continue
        try:
            ref = _artifact_reference(path)
            parsed = False
            if path.suffix == ".json":
                read_json_bound(path, ref["sha256"])
                parsed = True
            present.append({**ref, "json_reparsed": parsed, "scientifically_validated": False})
        except E26Error:
            unreadable.append(str(path))
    write_json_exclusive(directory / "SCORE_FAILURE.json", {
        "schema_version": "biohub.e26_screen.score_failure.v1", "run_id": control["run_id"],
        "candidate_id": CANDIDATE_ID, "submission_authorized": False, "status": "ERROR", "operation": operation,
        "error_type": type(error).__name__, "error": str(error), "original_control": control,
        "present_unvalidated_artifacts": present, "missing_artifacts": missing, "unreadable_artifacts": unreadable,
    })


def score_screen(
    seal_path: Path, *, expected_seal_sha256: str, expected_public_sha256: str, expected_private_sha256: str,
) -> dict:
    """Supervise one distinct scoring process, then verify its terminal evidence."""
    started = time.monotonic()
    verified = verify_generation_seal(seal_path, expected_seal_sha256=expected_seal_sha256,
                                      expected_public_sha256=expected_public_sha256,
                                      expected_private_sha256=expected_private_sha256)
    public = verified["public_registration"]
    _, run = _run_paths(public["run_id"])
    directory = run / "scoring"
    control = _score_process_control(public["run_id"], _artifact_reference(seal_path),
                                     expected_public_sha256, expected_private_sha256)
    if control["generation_seal"]["sha256"] != expected_seal_sha256:
        raise E26Error("generation seal changed before scoring dispatch")
    _plain_artifact_path(directory)
    try:
        directory.mkdir(mode=0o700)
    except OSError as exc:
        raise E26Error("scoring directory already exists or cannot be exclusively created") from exc
    operation = "score_control"
    budget = public["budget"]
    try:
        control_ref = write_json_exclusive(directory / "SCORE_CONTROL.json", control)
        operation = "score_child"
        measurement = check_runtime_budget(started, wall_limit_seconds=budget["score_process_wall_seconds"],
                                            ram_limit_bytes=budget["ram"]["limit_bytes"])
        process = _launch_control_process(Path(control_ref["path"]), control_ref["sha256"],
                                          budget["score_process_wall_seconds"] - measurement["wall_seconds"],
                                          command="_score")
        process_ref = write_json_exclusive(directory / "PROCESS_RESULT.json", process)
        _verify_control_process(process, control_ref, command="_score", wall_limit=budget["score_process_wall_seconds"])
        operation = "score_final_integrity"
        result_ref = _artifact_reference(directory / "SCORE_RESULT.json")
        result = _verify_score_child_result(result_ref, control_ref, control, process)
        _verify_artifact(process_ref, directory / "PROCESS_RESULT.json")
        timing = check_runtime_budget(started, wall_limit_seconds=budget["score_process_wall_seconds"],
                                       ram_limit_bytes=budget["ram"]["limit_bytes"])
        return write_json_exclusive(directory / "SCREEN_RESULT.json", {
            "schema_version": "biohub.e26_screen.verified_screen.v1", "run_id": public["run_id"],
            "candidate_id": CANDIDATE_ID, "status": result["status"], "first_failure": result["first_failure"],
            "submission_authorized": False, "control": control_ref, "process": process_ref,
            "result": result_ref, "gates": result["gates"], "supervisor_timing": timing,
        })
    except BaseException as exc:
        _record_scoring_failure(directory, control, operation, exc)
        raise
