"""Orchestrates the post-processing stack, ported verbatim from the notebook's
``filter_output_graph`` function and the CSV-writing loop that calls it once
per prediction ``.geff``.

Also provides a checkpoint split at the linefit-smoothing boundary
(:func:`filter_output_graph_pre_linefit` / :func:`save_prelinefit_checkpoint`
/ :func:`run_relinefit`): the stack up to and including
``filter_short_track_components`` fixes final graph *topology* (node/edge
sets); ``linefit_smooth_output_graph`` only nudges node coordinates. Sweeping
``BIOHUB_OUTPUT_LINEFIT_*`` therefore never needs to redo the expensive
motion-relink / gap-close / safe-division passes.
"""
from __future__ import annotations

import json
import math
import os
import pickle
import struct
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pandas as pd

from biohub.io import load_geff_graph
from biohub.public_postproc.config import PostprocConfig
from biohub.public_postproc.csv_out import NodeSerializer, SubmissionCsvWriter, write_run_stats
from biohub.public_postproc.deepcenter import load_deepcenter_veto_detector
from biohub.public_postproc.divisions import (
    _TWIN_COUNTER_KEYS,
    _TWIN_METADATA_MAX_DEPTH,
    _TWIN_VALIDATION_REASONS,
    TwinDebugRecord,
    TwinDeepCenterDecision,
    TwinEdgeRecord,
    TwinFrozenArray,
    TwinFrozenBuffer,
    TwinFrozenDType,
    TwinFrozenMapping,
    TwinFrozenNumpyScalar,
    TwinFrozenStructuredScalar,
    TwinPlan,
    TwinPlannedEdge,
    TwinSnapshotNode,
    add_safe_divisions_postlink,
    apply_twin_only_v1_plan,
    plan_twin_only_v1,
    score_twin_deepcenter,
)
from biohub.public_postproc.frames import refine_all_centroids
from biohub.public_postproc.geometry import edge_distance_um, edge_sort_key
from biohub.public_postproc.graph_ops import (
    close_single_frame_gaps,
    filter_short_track_components,
    linefit_smooth_output_graph,
    motion_relink_edges,
    prepare_consensus_reservations,
    recover_strict_gap2,
)

CHECKPOINT_MANIFEST_NAME = "manifest.json"

TwinPlanHook = Callable[[str, TwinPlan | None], None]
RawStatsHook = Callable[[Mapping[str, object]], None]
DatasetHook = Callable[[int, str], None]
DeepCenterLoader = Callable[[PostprocConfig], dict[str, object] | None]

_TWIN_R2_COUNTER_KEYS = (
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


def new_stats() -> dict[str, int]:
    """Zero-initialised counters filter_output_graph may increment.

    Verbatim from the notebook cell (``gap_close_effective_max_gap`` is
    deliberately absent: it is only set if ``close_single_frame_gaps``
    actually runs, same as the source).

    The notebook declares ``safe_division_geometric_candidates``,
    ``safe_division_mutual_nn_rejected`` and
    ``safe_division_divergence_rejected`` but never increments them (its
    telemetry always prints 0 for all three). The port keeps the keys in
    the notebook's position and fills them truthfully inside
    ``add_safe_divisions_postlink`` -- the documented notebook-only
    broken-counter exception of the E23 parity contract.
    """
    stats = {
        "raw_edges": 0,
        "dropped_nonconsecutive_edges": 0,
        "dropped_long_edges": 0,
        "dropped_multi_parent_edges": 0,
        "dropped_multi_child_edges": 0,
        "dropped_division_edges": 0,
        "gap_candidates": 0,
        "gap_pairs_selected": 0,
        "gap_reused_existing": 0,
        "gap_inserted_synthetic": 0,
        "gap_added_nodes": 0,
        "gap_added_edges": 0,
        "gap_skipped_node_cap": 0,
        "gap_density_nodes_scored": 0,
        "gap_density_candidates_expanded": 0,
        "gap_density_candidates_restricted": 0,
        "gap_density_selected_outside_base": 0,
        "gap_density_step_delta_milli_sum": 0,
        "gap_refined_synthetic": 0,
        "gap_refine_failed": 0,
        "gap_refine_rejected_shift": 0,
        "centroid_refine_examined": 0,
        "centroid_refine_moved": 0,
        "centroid_refine_no_signal": 0,
        "centroid_refine_rejected_shift": 0,
        "pruned_isolated_nodes": 0,
        "motion_relink_edges": 0,
        "motion_relink_tight_edges": 0,
        "motion_relink_relaxed_edges": 0,
        "motion_relink_frames": 0,
        "motion_relink_replaced_raw_edges": 0,
        "motion_relink_fallback_raw": 0,
        "motion_relink_skipped_large_frame": 0,
        "gap2_candidates": 0,
        "gap2_pairs_selected": 0,
        "gap2_added_nodes": 0,
        "gap2_added_edges": 0,
        "gap2_skipped_cap": 0,
        "safe_division_candidates": 0,
        "safe_division_geometric_candidates": 0,
        "safe_divisions_added": 0,
        "safe_division_skipped_cap": 0,
        "safe_division_mutual_nn_rejected": 0,
        "safe_division_divergence_rejected": 0,
        "deepcenter_gap_checked": 0,
        "deepcenter_gap_bypassed_strong_motion": 0,
        "deepcenter_gap_bypassed_observed_node": 0,
        "deepcenter_gap_accepted": 0,
        "deepcenter_gap_rejected": 0,
        "deepcenter_gap_missing": 0,
        "deepcenter_safe_div_checked": 0,
        "deepcenter_safe_div_accepted": 0,
        "deepcenter_safe_div_rejected": 0,
        "deepcenter_safe_div_missing": 0,
        "short_track_components_removed": 0,
        "short_track_nodes_removed": 0,
        "short_track_edges_removed": 0,
        "short_track_filter_skipped_all": 0,
        "short_track_rescue_triggered": 0,
        "short_track_rescue_components": 0,
        "short_track_rescue_nodes": 0,
        "short_track_rescue_budget": 0,
        "linefit_smoothed_nodes": 0,
        "linefit_skipped_nodes": 0,
    }
    stats.update(dict.fromkeys(_TWIN_COUNTER_KEYS, 0))
    stats.update(dict.fromkeys(_TWIN_R2_COUNTER_KEYS, 0))
    return stats


def _require_steal_twin_r1_dry_run(cfg: PostprocConfig) -> None:
    if not cfg.OUTPUT_STEAL_TWIN_REWIRE:
        return
    frozen = {
        "STEAL_TWIN_MODE": "twin_only_v1",
        "STEAL_TWIN_PARENT_MAX_UM": 8.0,
        "STEAL_TWIN_EXISTING_CHILD_MAX_UM": 10.0,
        "STEAL_TWIN_SISTER_MIN_UM": 5.5,
        "STEAL_TWIN_SISTER_MAX_UM": 11.0,
        "STEAL_TWIN_DIVERGE_UM": 2.25,
        "STEAL_TWIN_TWIN_MAX_UM": 5.0,
        "STEAL_TWIN_REQUIRE_TWO_SUCCESSORS": True,
        "STEAL_TWIN_REJECT_SYNTHETIC": True,
        "STEAL_TWIN_DEEPCENTER_VETO": True,
        "STEAL_TWIN_FRAME_CAP_ABS": 1,
        "STEAL_TWIN_VIDEO_CAP_ABS": 2,
        "STEAL_TWIN_DEBUG_MAX_RECORDS": 200,
    }
    if any(
        type(getattr(cfg, name)) is not type(expected) or getattr(cfg, name) != expected
        for name, expected in frozen.items()
    ):
        raise RuntimeError("invalid twin_only_v1 mode/profile lock")


def _twin_float_plain(value: float) -> float | dict[str, str]:
    if math.isfinite(value):
        return value
    if math.isnan(value):
        label = "nan"
    elif value > 0:
        label = "+inf"
    else:
        label = "-inf"
    return {
        "__twin_type__": "float",
        "value": label,
        "bits_hex": struct.pack(">d", value).hex(),
    }


def _twin_frozen_value_plain(value: object) -> object:
    return _twin_frozen_value_plain_inner(value, 0, set())


def _twin_frozen_value_plain_inner(value: object, depth: int, active: set[int]) -> object:
    if depth > _TWIN_METADATA_MAX_DEPTH:
        raise TypeError("twin metadata exceeds maximum depth")
    value_type = type(value)
    if value is None or value_type in (bool, int, str):
        return value
    if value_type is float:
        return _twin_float_plain(value)
    if value_type is complex:
        return {
            "__twin_type__": "complex",
            "real": _twin_float_plain(value.real),
            "imag": _twin_float_plain(value.imag),
        }
    if value_type is bytes:
        return {"__twin_type__": "bytes", "hex": value.hex()}
    recursive_types = (
        tuple,
        frozenset,
        TwinFrozenMapping,
        TwinFrozenDType,
        TwinFrozenStructuredScalar,
        TwinFrozenNumpyScalar,
        TwinFrozenArray,
        TwinFrozenBuffer,
    )
    if value_type not in recursive_types:
        raise TypeError(f"unsupported frozen twin value type: {value_type.__qualname__}")
    value_id = id(value)
    if value_id in active:
        raise TypeError("cyclic frozen twin value")
    active.add(value_id)
    try:
        return _twin_frozen_value_plain_recursive(value, depth, active)
    finally:
        active.remove(value_id)


def _twin_frozen_value_plain_recursive(value: object, depth: int, active: set[int]) -> object:
    value_type = type(value)
    if value_type is tuple:
        return {
            "__twin_type__": "tuple",
            "items": [
                _twin_frozen_value_plain_inner(item, depth + 1, active) for item in value
            ],
        }
    if value_type is frozenset:
        items = [
            _twin_frozen_value_plain_inner(item, depth + 1, active) for item in value
        ]
        items.sort(
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
        return {"__twin_type__": "frozenset", "items": items}
    if value_type is TwinFrozenMapping:
        return {
            "__twin_type__": "mapping",
            "items": [
                [
                    _twin_frozen_value_plain_inner(key, depth + 1, active),
                    _twin_frozen_value_plain_inner(item, depth + 1, active),
                ]
                for key, item in value.items_snapshot
            ],
        }
    if value_type is TwinFrozenDType:
        return {
            "__twin_type__": "numpy_dtype",
            "string": value.string,
            "descriptor": _twin_frozen_value_plain_inner(value.descriptor, depth + 1, active),
            "metadata": (
                None
                if value.metadata is None
                else _twin_frozen_value_plain_inner(value.metadata, depth + 1, active)
            ),
            "itemsize": value.itemsize,
            "alignment": value.alignment,
            "byteorder": value.byteorder,
            "names": None if value.names is None else list(value.names),
            "hasobject": value.hasobject,
            "aligned_struct": value.aligned_struct,
        }
    if value_type is TwinFrozenStructuredScalar:
        return {
            "__twin_type__": "numpy_structured_scalar",
            "fields": [
                [name, _twin_frozen_value_plain_inner(item, depth + 1, active)]
                for name, item in value.fields
            ],
        }
    if value_type is TwinFrozenNumpyScalar:
        return {
            "__twin_type__": "numpy_scalar",
            "dtype": _twin_frozen_value_plain_inner(value.dtype, depth + 1, active),
            "content": value.content.hex(),
        }
    if value_type is TwinFrozenArray:
        plain = {
            "__twin_type__": "numpy_array",
            "dtype": _twin_frozen_value_plain_inner(value.dtype, depth + 1, active),
            "shape": list(value.shape),
            "strides": list(value.strides),
            "c_contiguous": value.c_contiguous,
            "f_contiguous": value.f_contiguous,
            "object_content": value.object_content,
        }
        if type(value.content) is bytes:
            plain["content_hex"] = value.content.hex()
        elif type(value.content) is tuple:
            plain["content"] = {
                "__twin_type__": "tuple",
                "items": [
                    _twin_frozen_value_plain_inner(item, depth + 1, active)
                    for item in value.content
                ],
            }
        else:
            raise TypeError("unsupported TwinFrozenArray content type")
        return plain
    if value_type is TwinFrozenBuffer:
        return {
            "__twin_type__": "buffer",
            "kind": value.kind,
            "format": value.format,
            "itemsize": value.itemsize,
            "shape": list(value.shape),
            "strides": list(value.strides),
            "readonly": value.readonly,
            "content_hex": value.content.hex(),
        }
    raise TypeError(f"unsupported frozen twin value type: {value_type.__qualname__}")


def _twin_debug_record_plain(record: TwinDebugRecord) -> dict[str, object]:
    return {
        "dataset": record.dataset,
        "decision": record.decision,
        "reason": record.reason,
        "p": record.p,
        "q": record.q,
        "a": record.a,
        "b": record.b,
        "a2": record.a2,
        "b2": record.b2,
        "sort_key": list(record.sort_key),
        "d_pq": record.d_pq,
        "d_pa": record.d_pa,
        "d_pb": record.d_pb,
        "d_ab": record.d_ab,
        "d_a2b2": record.d_a2b2,
        "divergence_growth": record.divergence_growth,
        "raw_deepcenter_score": record.raw_deepcenter_score,
        "deepcenter_threshold": record.deepcenter_threshold,
        "deepcenter_decision": {
            "accepted": record.deepcenter_decision.accepted,
            "raw_score": record.deepcenter_decision.raw_score,
            "reason": record.deepcenter_decision.reason,
        },
        "removed_edge": {
            "source_id": record.removed_edge.source_id,
            "target_id": record.removed_edge.target_id,
            "metadata": _twin_frozen_value_plain(record.removed_edge.metadata),
        },
        "planned_edge": {
            "source_id": record.planned_edge.source_id,
            "target_id": record.planned_edge.target_id,
            "distance_um": record.planned_edge.distance_um,
            "edge_prob": None,
        },
    }


def _twin_candidate_plain(candidate: object) -> dict[str, object]:
    return {
        "frame": candidate.frame,
        "p": candidate.p,
        "q": candidate.q,
        "a": candidate.a,
        "b": candidate.b,
        "a2": candidate.a2,
        "b2": candidate.b2,
        "d_pq": candidate.d_pq,
        "d_pa": candidate.d_pa,
        "d_pb": candidate.d_pb,
        "d_ab": candidate.d_ab,
        "d_a2b2": candidate.d_a2b2,
        "divergence_growth": candidate.divergence_growth,
        "raw_deepcenter_score": candidate.raw_deepcenter_score,
        "deepcenter_decision": {
            "accepted": candidate.deepcenter_decision.accepted,
            "raw_score": candidate.deepcenter_decision.raw_score,
            "reason": candidate.deepcenter_decision.reason,
        },
        "sort_key": list(candidate.sort_key),
        "removed_edge": {
            "source_id": candidate.removed_edge.source_id,
            "target_id": candidate.removed_edge.target_id,
            "metadata": _twin_frozen_value_plain(candidate.removed_edge.metadata),
        },
        "planned_edge": {
            "source_id": candidate.planned_edge.source_id,
            "target_id": candidate.planned_edge.target_id,
            "distance_um": candidate.planned_edge.distance_um,
            "edge_prob": candidate.planned_edge.edge_prob,
        },
    }


def twin_plan_plain(plan: TwinPlan) -> dict[str, object]:
    """Losslessly expose every validated plan field for the production hook."""
    plan = _validate_twin_plan_failure_envelope(plan)
    return {
        "validation_reason": plan.validation_reason,
        "nodes": [
            {
                "node_id": node.node_id,
                "t": node.t,
                "z": node.z,
                "y": node.y,
                "x": node.x,
                "gap_synthetic": node.gap_synthetic,
            }
            for node in plan.nodes
        ],
        "edges": [
            {
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "input_position": edge.input_position,
                "metadata": _twin_frozen_value_plain(edge.metadata),
            }
            for edge in plan.edges
        ],
        "candidates": [_twin_candidate_plain(candidate) for candidate in plan.candidates],
        "accepted_candidates": [
            _twin_candidate_plain(candidate) for candidate in plan.accepted_candidates
        ],
        "decisions": [
            {
                "candidate": _twin_candidate_plain(decision.candidate),
                "accepted": decision.accepted,
                "reason": decision.reason,
            }
            for decision in plan.decisions
        ],
        "counters": _twin_frozen_value_plain(plan.counters),
        "debug_records": [_twin_debug_record_plain(record) for record in plan.debug_records],
    }


def _twin_record_type_error(index: int, field: str) -> TypeError:
    return TypeError(f"twin debug record {index}: invalid type for {field}")


def _twin_record_value_error(index: int, field: str) -> ValueError:
    return ValueError(f"twin debug record {index}: invalid value for {field}")


def _validate_twin_debug_record(
    record: object,
    index: int,
    expected_dataset: str | None,
    *,
    first: bool,
) -> str | None:
    if type(record) is not TwinDebugRecord:
        raise _twin_record_type_error(index, "record")
    if record.dataset is not None and type(record.dataset) is not str:
        raise _twin_record_type_error(index, "dataset")
    if not first and record.dataset != expected_dataset:
        raise _twin_record_value_error(index, "dataset")
    if type(record.decision) is not str:
        raise _twin_record_type_error(index, "decision")
    if record.decision == "accepted":
        if record.reason is not None:
            raise _twin_record_value_error(index, "decision/reason")
    elif record.decision == "rejected":
        if type(record.reason) is not str:
            raise _twin_record_type_error(index, "reason")
        if record.reason not in ("conflict", "frame_cap", "video_cap"):
            raise _twin_record_value_error(index, "reason")
    else:
        raise _twin_record_value_error(index, "decision")

    roles = (record.p, record.q, record.a, record.b, record.a2, record.b2)
    if any(type(value) is not int for value in roles):
        raise _twin_record_type_error(index, "roles")
    if type(record.sort_key) is not tuple:
        raise _twin_record_type_error(index, "sort_key")
    if len(record.sort_key) != 9:
        raise _twin_record_value_error(index, "sort_key length")
    if any(type(value) is not float for value in record.sort_key[:3]):
        raise _twin_record_type_error(index, "sort_key numeric prefix")
    if not all(math.isfinite(value) for value in record.sort_key[:3]):
        raise _twin_record_value_error(index, "sort_key numeric prefix")
    if any(type(value) is not int for value in record.sort_key[3:]):
        raise _twin_record_type_error(index, "sort_key role suffix")
    if record.sort_key[3:] != roles:
        raise _twin_record_value_error(index, "sort_key role suffix")

    float_fields = (
        ("d_pq", record.d_pq),
        ("d_pa", record.d_pa),
        ("d_pb", record.d_pb),
        ("d_ab", record.d_ab),
        ("d_a2b2", record.d_a2b2),
        ("divergence_growth", record.divergence_growth),
        ("raw_deepcenter_score", record.raw_deepcenter_score),
        ("deepcenter_threshold", record.deepcenter_threshold),
    )
    for field, value in float_fields:
        if type(value) is not float:
            raise _twin_record_type_error(index, field)
        if not math.isfinite(value):
            raise _twin_record_value_error(index, field)
    if record.deepcenter_threshold != 0.12:
        raise _twin_record_value_error(index, "deepcenter_threshold")

    decision = record.deepcenter_decision
    if type(decision) is not TwinDeepCenterDecision:
        raise _twin_record_type_error(index, "deepcenter_decision")
    if type(decision.accepted) is not bool:
        raise _twin_record_type_error(index, "deepcenter_decision.accepted")
    if decision.accepted is not True or decision.reason is not None:
        raise _twin_record_value_error(index, "deepcenter_decision")
    if type(decision.raw_score) is not float:
        raise _twin_record_type_error(index, "deepcenter_decision.raw_score")
    if not math.isfinite(decision.raw_score):
        raise _twin_record_value_error(index, "deepcenter_decision.raw_score")
    if decision.raw_score != record.raw_deepcenter_score:
        raise _twin_record_value_error(index, "deepcenter_decision.raw_score")

    removed = record.removed_edge
    if type(removed) is not TwinEdgeRecord:
        raise _twin_record_type_error(index, "removed_edge")
    if type(removed.source_id) is not int or type(removed.target_id) is not int:
        raise _twin_record_type_error(index, "removed_edge endpoints")
    if type(removed.metadata) is not TwinFrozenMapping:
        raise _twin_record_type_error(index, "removed_edge.metadata")
    if (removed.source_id, removed.target_id) != (record.q, record.b):
        raise _twin_record_value_error(index, "removed_edge endpoints")

    planned = record.planned_edge
    if type(planned) is not TwinPlannedEdge:
        raise _twin_record_type_error(index, "planned_edge")
    if type(planned.source_id) is not int or type(planned.target_id) is not int:
        raise _twin_record_type_error(index, "planned_edge endpoints")
    if type(planned.distance_um) is not float:
        raise _twin_record_type_error(index, "planned_edge.distance_um")
    if not math.isfinite(planned.distance_um):
        raise _twin_record_value_error(index, "planned_edge.distance_um")
    if planned.edge_prob is not None:
        raise _twin_record_value_error(index, "planned_edge.edge_prob")
    if (planned.source_id, planned.target_id, planned.distance_um) != (
        record.p,
        record.b,
        record.d_pb,
    ):
        raise _twin_record_value_error(index, "planned_edge")
    return record.dataset


class _TwinDebugCollector:
    def __init__(self, max_records: int) -> None:
        if type(max_records) is not int or max_records < 0:
            raise ValueError("max_records must be a nonnegative built-in int")
        self._max_records = max_records
        self._lines: list[str] = []
        self._records_written = 0
        self._records_dropped = 0
        self._finalized = False

    @property
    def records_written(self) -> int:
        return self._records_written

    @property
    def records_dropped(self) -> int:
        return self._records_dropped

    def allocate(self, records: Sequence[TwinDebugRecord]) -> tuple[int, int]:
        if self._finalized:
            raise RuntimeError("twin debug collector is already finalized")
        if not isinstance(records, Sequence):
            raise TypeError("twin debug records must be a Sequence")
        records_snapshot = tuple(records)
        expected_dataset: str | None = None
        for index, record in enumerate(records_snapshot):
            expected_dataset = _validate_twin_debug_record(
                record,
                index,
                expected_dataset,
                first=index == 0,
            )

        written = min(len(records_snapshot), self._max_records - self._records_written)
        dropped = len(records_snapshot) - written
        encoded = [
            json.dumps(
                _twin_debug_record_plain(records_snapshot[index]),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
            for index in range(written)
        ]
        self._lines.extend(encoded)
        self._records_written += written
        self._records_dropped += dropped
        return written, dropped

    def finalize(self, output_path: Path) -> None:
        if self._finalized:
            raise RuntimeError("twin debug collector is already finalized")
        handle = None
        temp_path: Path | None = None
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=output_path.parent,
                prefix=f".{output_path.name}.",
                suffix=".tmp",
                delete=False,
            )
            temp_path = Path(handle.name)
            handle.write("".join(self._lines))
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            handle = None
            os.replace(temp_path, output_path)
            temp_path = None
            self._finalized = True
        except BaseException:
            if handle is not None:
                try:
                    handle.close()
                except BaseException:
                    pass
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except BaseException:
                    pass
            raise


def _validate_twin_plan_failure_envelope(plan: object) -> TwinPlan:
    if type(plan) is not TwinPlan:
        raise RuntimeError("invalid twin planner return type")
    try:
        reason = plan.validation_reason
        snapshots = (
            plan.nodes,
            plan.edges,
            plan.candidates,
            plan.accepted_candidates,
            plan.decisions,
            plan.debug_records,
        )
        counters = plan.counters
    except Exception as exc:
        raise RuntimeError("invalid twin planner top-level fields") from exc
    if any(type(value) is not tuple for value in snapshots):
        raise RuntimeError("invalid twin planner top-level fields")
    if type(counters) is not TwinFrozenMapping:
        raise RuntimeError("invalid twin planner failure counters")
    try:
        items = counters.items_snapshot
    except Exception as exc:
        raise RuntimeError("invalid twin planner failure counters") from exc
    if type(items) is not tuple or len(items) != len(_TWIN_COUNTER_KEYS):
        raise RuntimeError("invalid twin planner failure counters")
    values: list[int] = []
    for index, entry in enumerate(items):
        if (
            type(entry) is not tuple
            or len(entry) != 2
            or type(entry[0]) is not str
            or entry[0] != _TWIN_COUNTER_KEYS[index]
            or type(entry[1]) is not int
        ):
            raise RuntimeError("invalid twin planner failure counters")
        values.append(entry[1])
    if reason is None:
        return plan
    if type(reason) is not str or reason not in _TWIN_VALIDATION_REASONS:
        raise RuntimeError("invalid twin planner validation reason")
    if any(
        type(value) is not tuple or value
        for value in snapshots
    ):
        raise RuntimeError("invalid twin planner failure snapshot")
    expected_one = {
        "steal_twin_validation_failed",
        f"steal_twin_validation_{reason}",
    }
    if any(value != (1 if key in expected_one else 0) for key, value in zip(_TWIN_COUNTER_KEYS, values, strict=True)):
        raise RuntimeError("invalid twin planner failure counters")
    return plan


def _run_steal_twin_r1_dry_run(
    cfg: PostprocConfig,
    dataset: str | None,
    nodes_by_id: dict[int, dict[str, object]],
    edges: list[dict[str, object]],
    stats: dict[str, int],
    deepcenter_bundle: dict[str, object] | None,
    repair_frame_cache: dict[int, np.ndarray],
    deepcenter_heatmap_cache: dict[tuple[str, int], np.ndarray],
    twin_debug_collector: _TwinDebugCollector | None = None,
    *,
    defer_debug_allocation: bool = False,
) -> TwinPlan:
    def score_callback(node: TwinSnapshotNode) -> TwinDeepCenterDecision:
        return score_twin_deepcenter(
            cfg,
            dataset,
            node.t,
            (node.z, node.y, node.x),
            deepcenter_bundle,
            repair_frame_cache,
            deepcenter_heatmap_cache,
        )

    plan = plan_twin_only_v1(
        cfg,
        dataset,
        tuple(nodes_by_id.values()),
        tuple(edges),
        score_callback,
    )
    plan = _validate_twin_plan_failure_envelope(plan)
    try:
        counter_keys = tuple(plan.counters)
        counter_values = tuple(plan.counters[key] for key in counter_keys)
    except Exception as exc:
        raise RuntimeError("invalid twin planner counter mapping") from exc
    if counter_keys != _TWIN_COUNTER_KEYS:
        raise RuntimeError("invalid twin planner counter key schema")
    if any(type(value) is not int or value < 0 for value in counter_values):
        raise RuntimeError("invalid twin planner counter value")
    if any(
        plan.counters[key] != 0
        for key in ("steal_twin_debug_records_written", "steal_twin_debug_records_dropped")
    ):
        raise RuntimeError("twin planner must not allocate debug counters")
    if any(key not in stats or type(stats[key]) is not int or stats[key] != 0 for key in _TWIN_COUNTER_KEYS):
        raise RuntimeError("twin destination counters must be preseeded exact integer zero")

    for key, value in zip(counter_keys, counter_values, strict=True):
        stats[key] = value
    if cfg.STEAL_TWIN_DEBUG_JSONL and not defer_debug_allocation:
        if twin_debug_collector is None:
            raise RuntimeError("twin debug path requires a run-level collector")
        written, dropped = twin_debug_collector.allocate(plan.debug_records)
        stats["steal_twin_debug_records_written"] = written
        stats["steal_twin_debug_records_dropped"] = dropped
    return plan


def _twin_fork_sources(edges: list[dict[str, object]]) -> int:
    counts: dict[int, int] = {}
    for edge in edges:
        source_id = int(edge["source_id"])
        counts[source_id] = counts.get(source_id, 0) + 1
    return sum(value == 2 for value in counts.values())


def _twin_observed_removal(before: int, after: int, stage: str) -> int:
    removed = before - after
    if removed < 0:
        raise RuntimeError(f"{stage} increased twin graph topology")
    return removed


def _linefit_with_twin_r2_guard(
    cfg: PostprocConfig,
    nodes_by_id: dict[int, dict[str, object]],
    edges: list[dict[str, object]],
    stats: dict[str, int],
    *,
    enabled: bool,
) -> dict[int, dict[str, object]]:
    if not enabled:
        return linefit_smooth_output_graph(cfg, nodes_by_id, edges, stats)

    node_mapping_id = id(nodes_by_id)
    node_snapshot: list[
        tuple[
            object,
            dict[str, object],
            tuple[tuple[object, object], ...],
            tuple[bytes, bytes, bytes],
        ]
    ] = []
    for outer_key, row in nodes_by_id.items():
        if type(row) is not dict:
            raise RuntimeError("invalid twin linefit node row")
        items = tuple(row.items())
        coordinate_values: dict[str, float] = {}
        for key, value in items:
            if type(key) is str and key in ("z", "y", "x"):
                coordinate_values[key] = value
        if set(coordinate_values) != {"z", "y", "x"}:
            raise RuntimeError("invalid twin linefit coordinate schema")
        coordinates = tuple(coordinate_values[name] for name in ("z", "y", "x"))
        if any(type(value) is not float or not math.isfinite(value) for value in coordinates):
            raise RuntimeError("invalid twin linefit pre-coordinate")
        node_snapshot.append(
            (
                outer_key,
                row,
                items,
                tuple(struct.pack(">d", value) for value in coordinates),
            )
        )
    edge_list_id = id(edges)
    edge_snapshot = [
        (row, tuple(row.items()))
        for row in edges
        if type(row) is dict
    ]
    if len(edge_snapshot) != len(edges):
        raise RuntimeError("invalid twin linefit edge row")

    returned = linefit_smooth_output_graph(cfg, nodes_by_id, edges, stats)
    if id(returned) != node_mapping_id or id(nodes_by_id) != node_mapping_id or id(edges) != edge_list_id:
        raise RuntimeError("twin linefit replaced a graph container")
    if len(nodes_by_id) != len(node_snapshot) or len(edges) != len(edge_snapshot):
        raise RuntimeError("twin linefit changed graph topology")

    changed = 0
    for (expected_outer_key, expected_row, expected_items, before), (outer_key, row) in zip(
        node_snapshot, nodes_by_id.items(), strict=True
    ):
        if outer_key is not expected_outer_key or row is not expected_row:
            raise RuntimeError("twin linefit replaced or reordered a node")
        current_items = tuple(row.items())
        if len(current_items) != len(expected_items) or any(
            current_key is not expected_key
            for (current_key, _), (expected_key, _) in zip(
                current_items, expected_items, strict=True
            )
        ):
            raise RuntimeError("twin linefit changed node keys")
        after_coordinates: dict[str, bytes] = {}
        for (key, value), (_, expected_value) in zip(
            current_items, expected_items, strict=True
        ):
            if type(key) is str and key in ("z", "y", "x"):
                if type(value) is not float or not math.isfinite(value):
                    raise RuntimeError("invalid twin linefit post-coordinate")
                after_coordinates[key] = struct.pack(">d", value)
            elif value is not expected_value:
                raise RuntimeError("twin linefit changed a preserved node binding")
        if tuple(after_coordinates[name] for name in ("z", "y", "x")) != before:
            changed += 1
    for (expected_row, expected_items), row in zip(edge_snapshot, edges, strict=True):
        if row is not expected_row:
            raise RuntimeError("twin linefit replaced or reordered an edge")
        current_items = tuple(row.items())
        if len(current_items) != len(expected_items):
            raise RuntimeError("twin linefit changed edge keys")
        for (key, value), (expected_key, expected_value) in zip(
            current_items, expected_items, strict=True
        ):
            if key is not expected_key:
                raise RuntimeError("twin linefit changed edge keys")
            if value is not expected_value:
                raise RuntimeError("twin linefit changed an edge binding")
    stats["steal_twin_linefit_coordinate_changed_nodes_observed"] = changed
    return returned


def _twin_debug_path_identities(debug_path: Path) -> tuple[Path, Path]:
    debug_resolved = debug_path.resolve(strict=False)
    debug_parent_resolved = debug_path.parent.resolve(strict=False)
    return debug_resolved, debug_parent_resolved / debug_path.name


def _twin_paths_samefile(first: Path, second: Path) -> bool:
    if not first.exists() or not second.exists():
        return False
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _raise_twin_debug_alias(debug_path: Path, artifact: Path) -> None:
    raise ValueError(f"twin debug target {debug_path} aliases run artifact {artifact}")


def _twin_debug_identity_overlaps_protected_path(
    debug_identities: Sequence[Path], protected_resolved: Path
) -> bool:
    return any(
        identity == protected_resolved
        or identity.is_relative_to(protected_resolved)
        or protected_resolved.is_relative_to(identity)
        for identity in debug_identities
    )


def _reject_twin_debug_aliases(
    geff_dir: Path,
    geffs: Sequence[Path],
    debug_path: Path,
    ordinary_artifacts: Sequence[Path],
) -> None:
    debug_resolved, debug_entry_resolved = _twin_debug_path_identities(debug_path)
    debug_identities = (debug_resolved, debug_entry_resolved)
    bundle_resolved = geff_dir.resolve(strict=True)
    if not bundle_resolved.is_dir():
        raise ValueError(f"GEFF input bundle is not a directory: {geff_dir}")
    if _twin_debug_identity_overlaps_protected_path(debug_identities, bundle_resolved):
        _raise_twin_debug_alias(debug_path, geff_dir)

    for geff_path in geffs:
        geff_resolved = geff_path.resolve(strict=True)
        if geff_resolved.is_dir():
            if _twin_debug_identity_overlaps_protected_path(debug_identities, geff_resolved):
                _raise_twin_debug_alias(debug_path, geff_path)
        elif geff_resolved.is_file():
            if _twin_debug_identity_overlaps_protected_path(
                debug_identities, geff_resolved
            ) or _twin_paths_samefile(debug_path, geff_path):
                _raise_twin_debug_alias(debug_path, geff_path)
        else:
            raise ValueError(f"GEFF input is not a regular file or directory: {geff_path}")

    for artifact in ordinary_artifacts:
        artifact_resolved = artifact.resolve(strict=False)
        if _twin_debug_identity_overlaps_protected_path(
            debug_identities, artifact_resolved
        ) or _twin_paths_samefile(debug_path, artifact):
            _raise_twin_debug_alias(debug_path, artifact)


def _unselected_association_priors(
    priors: dict[tuple[int, int], float] | None,
    raw_edges: list[dict[str, object]],
    nodes_by_id: dict[int, dict[str, object]],
) -> dict[tuple[int, int], float]:
    """Validate learned association priors and keep only ILP-unselected pairs.

    Returns a new dict of float probabilities for pairs that are *not* present
    in the ORIGINAL ``raw_edges`` (selected pairs keep whatever probability the
    edge itself carries; they are never overwritten).  Pairs whose endpoints no
    longer exist in ``nodes_by_id`` are excluded -- pre-linefit has already
    dropped ILP-unselected nodes.  Every other pair must reference two existing
    nodes whose builtin ``int`` times satisfy ``t == source_t + 1``; missing or
    invalid times raise ``ValueError``, including for selected pairs.

    No input is mutated.
    """
    if priors is None:
        return {}
    if type(priors) is not dict:
        raise ValueError("association_priors must be a dict or None")

    selected_pairs = {
        (int(edge["source_id"]), int(edge["target_id"])) for edge in raw_edges
    }

    def _time(node_id: int) -> int:
        t = nodes_by_id.get(node_id, {}).get("t")
        if type(t) is not int:
            raise ValueError(
                f"association_priors endpoint {node_id!r} needs a builtin int t: {t!r}"
            )
        return t

    result: dict[tuple[int, int], float] = {}
    for key, value in priors.items():
        if type(key) is not tuple or len(key) != 2:
            raise ValueError(
                f"association_priors keys must be 2-tuples of builtin ints: {key!r}"
            )
        sid, tid = key
        if type(sid) is not int or type(tid) is not int:
            raise ValueError(
                f"association_priors keys must be 2-tuples of builtin ints: {key!r}"
            )
        if type(value) is bool or type(value) not in (int, float):
            raise ValueError(
                f"association_priors values must be builtin int or float: {value!r}"
            )
        if value < 0 or value > 1:
            raise ValueError(
                f"association_priors values must be within [0, 1]: {value!r}"
            )
        prob = float(value)
        if not math.isfinite(prob):
            raise ValueError(
                f"association_priors values must be finite: {value!r}"
            )
        if sid not in nodes_by_id or tid not in nodes_by_id:
            continue
        if _time(tid) != _time(sid) + 1:
            raise ValueError(
                "association_priors endpoints must be adjacent frames: "
                f"({sid}, {tid}) -> t={_time(sid)}, t={_time(tid)}"
            )
        if (sid, tid) in selected_pairs:
            continue
        result[(sid, tid)] = prob
    return result


def filter_output_graph_pre_linefit(
    cfg: PostprocConfig,
    nodes_by_id: dict[int, dict[str, object]],
    raw_edges: list[dict[str, object]],
    dataset: str | None = None,
    deepcenter_bundle: dict[str, object] | None = None,
    *,
    twin_debug_collector: _TwinDebugCollector | None = None,
    twin_plan_hook: TwinPlanHook | None = None,
    association_priors: dict[tuple[int, int], float] | None = None,
    appearance_frames: dict[int, dict] | None = None,
    consensus_pairs_by_t: dict[int, list[tuple[int, int]]] | None = None,
    consensus_soft_pairs_by_t: dict[int, list[tuple[int, int]]] | None = None,
    short_track_consensus_pairs_by_t: dict[int, list[tuple[int, int]]] | None = None,
    bidirectional_motion_consistency: bool = False,
) -> tuple[dict[int, dict[str, object]], list[dict[str, object]], dict[str, int]]:
    """Everything ``filter_output_graph`` does *except* the final linefit-smoothing call.

    This is the checkpoint boundary: final node/edge topology is fixed here
    (``filter_short_track_components`` already ran); only coordinates can
    still move.
    """
    if appearance_frames is not None:
        # Opt-in appearance features: exact non-empty frame map, motion relink
        # enabled, and never combined with E27 association priors.
        if type(appearance_frames) is not dict or not appearance_frames:
            raise ValueError("appearance_frames must be a non-empty exact dict")
        if not cfg.OUTPUT_MOTION_RELINK:
            raise ValueError("appearance_frames requires OUTPUT_MOTION_RELINK")
        if association_priors is not None:
            raise ValueError("appearance_frames cannot be combined with association_priors")
    if appearance_frames is not None and (
        consensus_pairs_by_t is not None or consensus_soft_pairs_by_t is not None
    ):
        raise ValueError("consensus pairs cannot be combined with appearance_frames")
    if consensus_pairs_by_t is not None and consensus_soft_pairs_by_t is not None:
        raise ValueError("hard and soft consensus pairs cannot be combined")
    unselected_priors = _unselected_association_priors(
        association_priors, raw_edges, nodes_by_id
    )
    _require_steal_twin_r1_dry_run(cfg)
    if cfg.OUTPUT_STEAL_TWIN_REWIRE and cfg.STEAL_TWIN_DEBUG_JSONL and twin_debug_collector is None:
        raise RuntimeError("twin debug path requires a run-level collector")

    stats = new_stats()
    stats["raw_edges"] = len(raw_edges)
    raw_edges_for_consensus = [dict(edge) for edge in raw_edges]

    # One shared frame cache for the whole pre-linefit stack: E23 all-node
    # centroid refinement reads each timepoint once, and gap-close /
    # safe-division / DeepCenter reuse those frames below.
    repair_frame_cache: dict[int, np.ndarray] = {}
    if cfg.REFINE_ALL_CENTROIDS:
        # Runs before any edge distance is computed, matching the notebook:
        # refined coordinates feed the edge-length filter, motion relink,
        # gap repair, safe divisions and DeepCenter queries.
        refine_all_centroids(cfg, nodes_by_id, dataset, repair_frame_cache, stats)

    edges: list[dict[str, object]] = []
    for edge in raw_edges:
        source = nodes_by_id.get(int(edge["source_id"]))
        target = nodes_by_id.get(int(edge["target_id"]))
        if source is None or target is None:
            continue
        if cfg.OUTPUT_ENFORCE_NEXT_FRAME and int(target["t"]) != int(source["t"]) + 1:
            stats["dropped_nonconsecutive_edges"] += 1
            continue
        distance_um = edge_distance_um(source, target)
        edge["distance_um"] = distance_um
        if cfg.OUTPUT_EDGE_MAX_UM > 0 and distance_um > cfg.OUTPUT_EDGE_MAX_UM:
            stats["dropped_long_edges"] += 1
            continue
        edges.append(edge)

    if cfg.OUTPUT_MOTION_RELINK:
        learned_edge_probs: dict[tuple[int, int], float] = {}
        for edge in edges:
            prob = edge.get("edge_prob")
            if prob is None:
                continue
            try:
                prob = float(prob)
            except (TypeError, ValueError):
                continue
            if np.isfinite(prob):
                key = (int(edge["source_id"]), int(edge["target_id"]))
                learned_edge_probs[key] = max(learned_edge_probs.get(key, float("-inf")), prob)
        learned_edge_probs.update(unselected_priors)
        hard_consensus = (
            None
            if consensus_pairs_by_t is None
            else prepare_consensus_reservations(
                consensus_pairs_by_t,
                nodes_by_id,
                raw_edges_for_consensus,
                edges,
                cfg.MOTION_RELINK_TIGHT_UM,
            )
        )
        soft_consensus = (
            None
            if consensus_soft_pairs_by_t is None
            else prepare_consensus_reservations(
                consensus_soft_pairs_by_t,
                nodes_by_id,
                raw_edges_for_consensus,
                edges,
                cfg.MOTION_RELINK_TIGHT_UM,
            )
        )
        motion_edges = motion_relink_edges(
            cfg,
            nodes_by_id,
            stats,
            learned_edge_probs,
            appearance_frames=appearance_frames,
            consensus_pairs_by_t=hard_consensus,
            consensus_soft_pairs_by_t=soft_consensus,
            bidirectional_motion_consistency=bidirectional_motion_consistency,
        )
        if motion_edges:
            stats["motion_relink_replaced_raw_edges"] = len(edges)
            edges = motion_edges
        else:
            stats["motion_relink_fallback_raw"] = 1

    if cfg.OUTPUT_SINGLE_PARENT_REPAIR and edges:
        best_by_target: dict[int, dict[str, object]] = {}
        for edge in edges:
            target_id = int(edge["target_id"])
            prev = best_by_target.get(target_id)
            if prev is None or edge_sort_key(edge) > edge_sort_key(prev):
                best_by_target[target_id] = edge
        kept_ids = {id(edge) for edge in best_by_target.values()}
        stats["dropped_multi_parent_edges"] = sum(1 for edge in edges if id(edge) not in kept_ids)
        edges = [edge for edge in edges if id(edge) in kept_ids]

    if cfg.OUTPUT_SINGLE_CHILD_REPAIR and edges:
        best_by_source: dict[int, dict[str, object]] = {}
        for edge in edges:
            source_id = int(edge["source_id"])
            prev = best_by_source.get(source_id)
            if prev is None or edge_sort_key(edge) > edge_sort_key(prev):
                best_by_source[source_id] = edge
        kept_ids = {id(edge) for edge in best_by_source.values()}
        stats["dropped_multi_child_edges"] = sum(1 for edge in edges if id(edge) not in kept_ids)
        edges = [edge for edge in edges if id(edge) in kept_ids]

    deepcenter_heatmap_cache: dict[tuple[str, int], np.ndarray] = {}
    nodes_by_id, edges = close_single_frame_gaps(
        cfg,
        nodes_by_id,
        edges,
        stats,
        dataset=dataset,
        deepcenter_bundle=deepcenter_bundle,
        frame_cache=repair_frame_cache,
        deepcenter_cache=deepcenter_heatmap_cache,
    )
    nodes_by_id, edges = recover_strict_gap2(cfg, nodes_by_id, edges, stats, dataset=dataset)
    edges = add_safe_divisions_postlink(
        cfg,
        nodes_by_id,
        edges,
        stats,
        dataset=dataset,
        deepcenter_bundle=deepcenter_bundle,
        frame_cache=repair_frame_cache,
        deepcenter_cache=deepcenter_heatmap_cache,
    )

    twin_candidate_active = False
    if cfg.OUTPUT_STEAL_TWIN_REWIRE:
        if twin_plan_hook is None:
            plan = _run_steal_twin_r1_dry_run(
                cfg,
                dataset,
                nodes_by_id,
                edges,
                stats,
                deepcenter_bundle,
                repair_frame_cache,
                deepcenter_heatmap_cache,
                twin_debug_collector,
            )
        else:
            if dataset is None:
                raise RuntimeError("twin plan hook requires a dataset")
            plan = _run_steal_twin_r1_dry_run(
                cfg,
                dataset,
                nodes_by_id,
                edges,
                stats,
                deepcenter_bundle,
                repair_frame_cache,
                deepcenter_heatmap_cache,
                twin_debug_collector,
                defer_debug_allocation=True,
            )
            twin_plan_hook(dataset, plan)
            if cfg.STEAL_TWIN_DEBUG_JSONL:
                if twin_debug_collector is None:
                    raise RuntimeError("twin debug path requires a run-level collector")
                written, dropped = twin_debug_collector.allocate(plan.debug_records)
                stats["steal_twin_debug_records_written"] = written
                stats["steal_twin_debug_records_dropped"] = dropped
        if plan.validation_reason is None and not cfg.STEAL_TWIN_DRY_RUN:
            edges, mutation = apply_twin_only_v1_plan(nodes_by_id, edges, plan)
            if mutation.status == "already_applied":
                raise RuntimeError("pipeline received an already-applied twin plan")
            accepted = len(plan.accepted_candidates)
            if mutation.status not in ("applied", "no_changes"):
                raise RuntimeError("invalid twin mutation status")
            stats["steal_twin_edges_removed"] = mutation.edges_removed
            stats["steal_twin_edges_added"] = mutation.edges_added
            stats["steal_twin_mutations_applied"] = mutation.edges_removed
            stats["steal_twin_pure_nodes"] = len(nodes_by_id)
            stats["steal_twin_pure_edges"] = len(edges)
            stats["steal_twin_pure_fork_sources"] = _twin_fork_sources(edges)
            stats["steal_twin_pure_edge_symmetric_difference"] = mutation.edge_symmetric_difference
            if not (
                stats["steal_twin_planned_edges_removed"]
                == stats["steal_twin_planned_edges_added"]
                == stats["steal_twin_accepted"]
                == accepted
                == stats["steal_twin_edges_removed"]
                == stats["steal_twin_edges_added"]
                == stats["steal_twin_mutations_applied"]
                and stats["steal_twin_pure_edge_symmetric_difference"] == 2 * accepted
            ):
                raise RuntimeError("twin mutation counter conservation failed")
            twin_candidate_active = True
    elif twin_plan_hook is not None:
        if dataset is None:
            raise RuntimeError("twin plan hook requires a dataset")
        twin_plan_hook(dataset, None)

    geometry_edges_before = len(edges)
    if cfg.OUTPUT_DIVISION_GEOMETRY_FILTER and edges:
        by_source: dict[int, list[dict[str, object]]] = {}
        for edge in edges:
            by_source.setdefault(int(edge["source_id"]), []).append(edge)

        filtered: list[dict[str, object]] = []
        for source_id, source_edges in by_source.items():
            if len(source_edges) <= 1:
                filtered.extend(source_edges)
                continue

            ranked = sorted(source_edges, key=edge_sort_key, reverse=True)
            source = nodes_by_id[source_id]
            top1 = ranked[0]
            top2 = ranked[1]
            d1 = float(top1["distance_um"])
            d2 = float(top2["distance_um"])
            sister = edge_distance_um(nodes_by_id[int(top1["target_id"])], nodes_by_id[int(top2["target_id"])])
            valid_division = (
                max(d1, d2) <= cfg.DIV_PARENT_MAX_UM
                and sister <= cfg.DIV_SISTER_MAX_UM
                and int(nodes_by_id[int(top1["target_id"])]["t"]) == int(source["t"]) + 1
                and int(nodes_by_id[int(top2["target_id"])]["t"]) == int(source["t"]) + 1
            )
            if valid_division:
                filtered.extend([top1, top2])
                stats["dropped_division_edges"] += max(0, len(ranked) - 2)
            elif cfg.DIV_DROP_TO_SINGLE_IF_BAD:
                filtered.append(top1)
                stats["dropped_division_edges"] += len(ranked) - 1
            else:
                filtered.extend(ranked)
        edges = filtered
    if twin_candidate_active:
        stats["steal_twin_geometry_edges_removed_observed"] = _twin_observed_removal(
            geometry_edges_before, len(edges), "division geometry"
        )

    prune_nodes_before = len(nodes_by_id)
    prune_edges_before = len(edges)
    if cfg.OUTPUT_PRUNE_ISOLATED:
        incident = {int(edge["source_id"]) for edge in edges} | {int(edge["target_id"]) for edge in edges}
        if incident:
            kept_nodes = {node_id: node for node_id, node in nodes_by_id.items() if node_id in incident}
            stats["pruned_isolated_nodes"] = len(nodes_by_id) - len(kept_nodes)
            nodes_by_id = kept_nodes
            edges = [edge for edge in edges if int(edge["source_id"]) in nodes_by_id and int(edge["target_id"]) in nodes_by_id]
    if twin_candidate_active:
        stats["steal_twin_prune_nodes_removed_observed"] = _twin_observed_removal(
            prune_nodes_before, len(nodes_by_id), "isolated prune"
        )
        stats["steal_twin_prune_edges_removed_observed"] = _twin_observed_removal(
            prune_edges_before, len(edges), "isolated prune"
        )

    short_nodes_before = len(nodes_by_id)
    short_edges_before = len(edges)
    if short_track_consensus_pairs_by_t is None:
        nodes_by_id, edges = filter_short_track_components(cfg, nodes_by_id, edges, stats)
    else:
        nodes_by_id, edges = filter_short_track_components(
            cfg, nodes_by_id, edges, stats,
            consensus_proof_pairs_by_t=short_track_consensus_pairs_by_t,
        )
    if twin_candidate_active:
        stats["steal_twin_short_nodes_removed_observed"] = _twin_observed_removal(
            short_nodes_before, len(nodes_by_id), "short-track filter"
        )
        stats["steal_twin_short_edges_removed_observed"] = _twin_observed_removal(
            short_edges_before, len(edges), "short-track filter"
        )
        stats["steal_twin_final_nodes"] = len(nodes_by_id)
        stats["steal_twin_final_edges"] = len(edges)
        stats["steal_twin_final_fork_sources"] = _twin_fork_sources(edges)

    if bidirectional_motion_consistency and edges:
        # E34 safety gate: a malformed downstream merge must never publish an
        # invalid graph. Keep the strongest edge per target and per source.
        best_target: dict[int, dict[str, object]] = {}
        for edge in edges:
            tid = int(edge["target_id"])
            if tid not in best_target or edge_sort_key(edge) > edge_sort_key(best_target[tid]):
                best_target[tid] = edge
        best_source: dict[int, dict[str, object]] = {}
        for edge in best_target.values():
            sid = int(edge["source_id"])
            if sid not in best_source or edge_sort_key(edge) > edge_sort_key(best_source[sid]):
                best_source[sid] = edge
        edges = list(best_source.values())

    return nodes_by_id, edges, stats


def filter_output_graph(
    cfg: PostprocConfig,
    nodes_by_id: dict[int, dict[str, object]],
    raw_edges: list[dict[str, object]],
    dataset: str | None = None,
    deepcenter_bundle: dict[str, object] | None = None,
    *,
    twin_debug_collector: _TwinDebugCollector | None = None,
    twin_plan_hook: TwinPlanHook | None = None,
    association_priors: dict[tuple[int, int], float] | None = None,
    appearance_frames: dict[int, dict] | None = None,
    consensus_pairs_by_t: dict[int, list[tuple[int, int]]] | None = None,
    consensus_soft_pairs_by_t: dict[int, list[tuple[int, int]]] | None = None,
    short_track_consensus_pairs_by_t: dict[int, list[tuple[int, int]]] | None = None,
    bidirectional_motion_consistency: bool = False,
) -> tuple[dict[int, dict[str, object]], list[dict[str, object]], dict[str, int]]:
    nodes_by_id, edges, stats = filter_output_graph_pre_linefit(
        cfg,
        nodes_by_id,
        raw_edges,
        dataset=dataset,
        deepcenter_bundle=deepcenter_bundle,
        twin_debug_collector=twin_debug_collector,
        twin_plan_hook=twin_plan_hook,
        association_priors=association_priors,
        consensus_pairs_by_t=consensus_pairs_by_t,
        consensus_soft_pairs_by_t=consensus_soft_pairs_by_t,
        short_track_consensus_pairs_by_t=short_track_consensus_pairs_by_t,
        bidirectional_motion_consistency=bidirectional_motion_consistency,
        **({} if appearance_frames is None else {"appearance_frames": appearance_frames}),
    )
    twin_candidate_active = (
        stats["steal_twin_pure_nodes"] > 0 or stats["steal_twin_pure_edges"] > 0
    )
    nodes_by_id = _linefit_with_twin_r2_guard(
        cfg,
        nodes_by_id,
        edges,
        stats,
        enabled=twin_candidate_active,
    )
    return nodes_by_id, edges, stats


def _load_geff_as_dicts(geff_path: Path) -> tuple[dict[int, dict[str, object]], list[dict[str, object]]]:
    graph = load_geff_graph(geff_path)

    nodes_by_id: dict[int, dict[str, object]] = {}
    for row in graph.node_attrs().iter_rows(named=True):
        node_id = int(row["node_id"])
        if node_id in nodes_by_id:
            raise ValueError(f"{geff_path}: duplicate node_id {node_id}")
        nodes_by_id[node_id] = {
            "node_id": node_id,
            "t": int(row["t"]),
            "z": float(row["z"]),
            "y": float(row["y"]),
            "x": float(row["x"]),
        }

    raw_edges: list[dict[str, object]] = []
    for row in graph.edge_attrs().iter_rows(named=True):
        edge_prob = row.get("edge_prob") if hasattr(row, "get") else None
        raw_edges.append({
            "source_id": int(row["source_id"]),
            "target_id": int(row["target_id"]),
            "edge_prob": None if edge_prob is None else float(edge_prob),
        })
    return nodes_by_id, raw_edges


def _dataset_stats_row(
    dataset: str,
    nodes_by_id: dict[int, dict[str, object]],
    edges: list[dict[str, object]],
    stats: dict[str, int],
    raw_node_count: int,
    division_sources: dict[int, int],
) -> dict[str, object]:
    node_count = len(nodes_by_id)
    edge_count = len(edges)
    return {
        "dataset": dataset,
        "raw_nodes": raw_node_count,
        "nodes": node_count,
        "raw_edges": stats["raw_edges"],
        "edges": edge_count,
        "division_like_sources": sum(1 for count in division_sources.values() if count >= 2),
        "edge_to_node_ratio": edge_count / max(node_count, 1),
        "gap_added_nodes_frac": stats.get("gap_added_nodes", 0) / max(raw_node_count, 1),
        **stats,
    }


def _finish_run(
    writer: SubmissionCsvWriter,
    stats_rows: list[dict[str, object]],
    total_nodes: int,
    total_edges: int,
    cfg: PostprocConfig,
    run_stats_path: Path,
    predict_seconds: float,
) -> pd.DataFrame:
    assert writer.row_id == total_nodes + total_edges, "Internal row counter mismatch"
    assert total_nodes > 0, "No node rows produced"

    stats_rows_with_meta = [
        {**row, "predict_minutes_total": predict_seconds / 60.0, "experiment_tag": cfg.EXPERIMENT_TAG}
        for row in stats_rows
    ]
    return write_run_stats(stats_rows_with_meta, run_stats_path)


def run_postproc_core(
    geff_paths: Sequence[Path],
    out_csv: Path,
    cfg: PostprocConfig,
    run_stats_path: Path | None = None,
    predict_seconds: float = 0.0,
    *,
    deepcenter_loader: DeepCenterLoader | None = None,
    dataset_start_hook: DatasetHook | None = None,
    dataset_finish_hook: DatasetHook | None = None,
    twin_plan_hook: TwinPlanHook | None = None,
    raw_stats_hook: RawStatsHook | None = None,
    write_run_stats_output: bool = True,
    exclusive_output: bool = False,
    node_serializer: NodeSerializer | None = None,
    association_priors_by_dataset: dict[str, dict[tuple[int, int], float]] | None = None,
    appearance_loader: Callable[[str, dict[int, dict[str, object]]], dict[int, dict]]
    | None = None,
    consensus_loader: Callable[[str, dict[int, dict[str, object]]], dict[int, list[tuple[int, int]]]]
    | None = None,
    consensus_soft_loader: Callable[[str, dict[int, dict[str, object]]], dict[int, list[tuple[int, int]]]]
    | None = None,
    short_track_consensus_loader: Callable[[str, dict[int, dict[str, object]]], dict[int, list[tuple[int, int]]]]
    | None = None,
    bidirectional_motion_consistency: bool = False,
) -> dict[str, object]:
    """Run the full stack over an explicit GEFF sequence without reordering it.

    This is the sole full-run dataset loop.  The legacy entry point supplies a
    sorted discovery result; the ST-R3 adapter supplies its frozen literal
    order and production hooks. An optional serializer changes only the node
    CSV boundary; the default retains the legacy byte representation.

    ``association_priors_by_dataset`` is opt-in.  ``None`` (default) keeps the
    legacy behaviour exactly.  When supplied it must be an outer ``dict`` whose
    keys are exactly the unique GEFF stems; every inner mapping is validated up
    front with ``_unselected_association_priors`` and snapshotted so that later
    hook activity cannot alter what a downstream dataset consumes.
    """
    geffs = tuple(geff_paths)
    if not geffs:
        raise RuntimeError("no GEFF paths supplied")
    if any(type(path) is not type(Path()) for path in geffs):
        raise TypeError("GEFF paths must be exact pathlib.Path instances")

    if appearance_loader is not None:
        # Opt-in per-dataset appearance features; validated up front so no
        # video is ever half-featured.  No global default config is implied.
        if not callable(appearance_loader):
            raise ValueError("appearance_loader must be callable")
        if not cfg.OUTPUT_MOTION_RELINK:
            raise ValueError("appearance_loader requires OUTPUT_MOTION_RELINK")
        if association_priors_by_dataset is not None:
            raise ValueError("appearance_loader cannot be combined with association_priors_by_dataset")
        stems = tuple(path.stem for path in geffs)
        if len(set(stems)) != len(stems):
            raise ValueError("GEFF dataset stems must be unique when an appearance loader is supplied")
    for loader_name, consensus_callback in (
        ("consensus_loader", consensus_loader),
        ("consensus_soft_loader", consensus_soft_loader),
    ):
        if consensus_callback is None:
            continue
        if not callable(consensus_callback):
            raise ValueError(f"{loader_name} must be callable")
        if appearance_loader is not None or association_priors_by_dataset is not None:
            raise ValueError(f"{loader_name} cannot be combined with appearance/prior loaders")
        stems = tuple(path.stem for path in geffs)
        if len(set(stems)) != len(stems):
            raise ValueError("GEFF dataset stems must be unique when a consensus loader is supplied")
    if consensus_loader is not None and consensus_soft_loader is not None:
        raise ValueError("hard and soft consensus loaders cannot be combined")
    if short_track_consensus_loader is not None:
        if not callable(short_track_consensus_loader):
            raise ValueError("short_track_consensus_loader must be callable")
        if appearance_loader is not None or consensus_loader is not None or consensus_soft_loader is not None:
            raise ValueError("short-track consensus loader cannot be combined with other feature loaders")

    prior_map: dict[str, dict[tuple[int, int], float]] | None = None
    if association_priors_by_dataset is not None:
        if type(association_priors_by_dataset) is not dict:
            raise ValueError("association_priors_by_dataset must be an exact dict")
        for key in association_priors_by_dataset:
            if type(key) is not str:
                raise ValueError("association_priors_by_dataset keys must be exact str")
        stems = tuple(path.stem for path in geffs)
        if len(set(stems)) != len(stems):
            raise ValueError("GEFF dataset stems must be unique when priors are supplied")
        if set(association_priors_by_dataset) != set(stems):
            raise ValueError(
                "association_priors_by_dataset keys must exactly match the GEFF dataset stems"
            )
        prior_map = {}
        for stem in stems:
            inner = association_priors_by_dataset[stem]
            if inner is None or type(inner) is not dict:
                raise ValueError(
                    f"association priors for {stem!r} must be an exact dict"
                )
            _unselected_association_priors(inner, [], {})
            prior_map[stem] = inner.copy()

    _require_steal_twin_r1_dry_run(cfg)
    effective_run_stats_path = run_stats_path or out_csv.parent / "run_stats.csv"
    twin_debug_collector: _TwinDebugCollector | None = None
    twin_debug_path: Path | None = None
    if cfg.OUTPUT_STEAL_TWIN_REWIRE and cfg.STEAL_TWIN_DEBUG_JSONL:
        twin_debug_path = Path(cfg.STEAL_TWIN_DEBUG_JSONL)
        _reject_twin_debug_aliases(
            geffs[0].parent,
            geffs,
            twin_debug_path,
            (out_csv, effective_run_stats_path),
        )
        twin_debug_collector = _TwinDebugCollector(cfg.STEAL_TWIN_DEBUG_MAX_RECORDS)

    effective_deepcenter_loader = deepcenter_loader or load_deepcenter_veto_detector
    deepcenter_detector = effective_deepcenter_loader(cfg)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    stats_rows: list[dict[str, object]] = []
    total_nodes = 0
    total_edges = 0

    with out_csv.open("x" if exclusive_output else "w", newline="") as handle:
        writer = SubmissionCsvWriter(handle, node_serializer=node_serializer)

        for sequence, geff_path in enumerate(geffs):
            dataset = geff_path.stem
            if dataset_start_hook is not None:
                dataset_start_hook(sequence, dataset)
            nodes_by_id, raw_edges = _load_geff_as_dicts(geff_path)

            raw_node_count = len(nodes_by_id)
            appearance_kwargs: dict[str, object] = {}
            if appearance_loader is not None:
                frames = appearance_loader(
                    dataset, {node_id: dict(node) for node_id, node in nodes_by_id.items()}
                )
                if type(frames) is not dict or not frames:
                    raise ValueError(f"appearance_loader returned no features for {dataset!r}")
                appearance_kwargs["appearance_frames"] = frames
                del frames
            if consensus_loader is not None:
                consensus = consensus_loader(
                    dataset, {node_id: dict(node) for node_id, node in nodes_by_id.items()}
                )
                if type(consensus) is not dict:
                    raise ValueError(f"consensus_loader returned non-dict for {dataset!r}")
                appearance_kwargs["consensus_pairs_by_t"] = consensus
                del consensus
            if consensus_soft_loader is not None:
                consensus = consensus_soft_loader(
                    dataset, {node_id: dict(node) for node_id, node in nodes_by_id.items()}
                )
                if type(consensus) is not dict:
                    raise ValueError(
                        f"consensus_soft_loader returned non-dict for {dataset!r}"
                    )
                appearance_kwargs["consensus_soft_pairs_by_t"] = consensus
                del consensus
            if short_track_consensus_loader is not None:
                consensus = short_track_consensus_loader(
                    dataset, {node_id: dict(node) for node_id, node in nodes_by_id.items()}
                )
                if type(consensus) is not dict:
                    raise ValueError(
                        f"short_track_consensus_loader returned non-dict for {dataset!r}"
                    )
                appearance_kwargs["short_track_consensus_pairs_by_t"] = consensus
                del consensus
            nodes_by_id, edges, filter_stats = filter_output_graph(
                cfg,
                nodes_by_id,
                raw_edges,
                dataset=dataset,
                deepcenter_bundle=deepcenter_detector,
                twin_debug_collector=twin_debug_collector,
                twin_plan_hook=twin_plan_hook,
                association_priors=None if prior_map is None else prior_map[dataset],
                **appearance_kwargs,
                bidirectional_motion_consistency=bidirectional_motion_consistency,
            )
            del appearance_kwargs
            if not nodes_by_id:
                raise AssertionError(f"{dataset}: post-processing removed every node")

            writer.write_nodes(dataset, nodes_by_id)
            division_sources = writer.write_edges(dataset, nodes_by_id, edges)

            total_nodes += len(nodes_by_id)
            total_edges += len(edges)
            stats_row = _dataset_stats_row(
                dataset,
                nodes_by_id,
                edges,
                filter_stats,
                raw_node_count,
                division_sources,
            )
            stats_rows.append(stats_row)
            if raw_stats_hook is not None:
                raw_stats_hook(MappingProxyType(stats_row.copy()))
            handle.flush()
            if dataset_finish_hook is not None:
                os.fsync(handle.fileno())
                dataset_finish_hook(sequence, dataset)

        handle.flush()
        os.fsync(handle.fileno())

    if write_run_stats_output:
        stats_frame: pd.DataFrame | None = _finish_run(
            writer,
            stats_rows,
            total_nodes,
            total_edges,
            cfg,
            effective_run_stats_path,
            predict_seconds,
        )
    else:
        assert writer.row_id == total_nodes + total_edges, "Internal row counter mismatch"
        assert total_nodes > 0, "No node rows produced"
        stats_frame = None
    if twin_debug_collector is not None and twin_debug_path is not None:
        twin_debug_collector.finalize(twin_debug_path)

    return {
        "datasets": [p.stem for p in geffs],
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "total_rows": writer.row_id,
        "run_stats": stats_frame,
    }


def run_postproc(
    geff_dir: Path,
    out_csv: Path,
    cfg: PostprocConfig,
    run_stats_path: Path | None = None,
    predict_seconds: float = 0.0,
) -> dict[str, object]:
    """Legacy sorted-discovery wrapper over :func:`run_postproc_core`."""
    geffs = sorted(geff_dir.glob("*.geff"))
    if not geffs:
        raise RuntimeError(f"no *.geff files found in {geff_dir}")
    return run_postproc_core(
        geffs,
        out_csv,
        cfg,
        run_stats_path=run_stats_path,
        predict_seconds=predict_seconds,
    )


# ---------------------------------------------------------------------------
# Pre-linefit checkpoint: run the expensive part once, then iterate on
# BIOHUB_OUTPUT_LINEFIT_* (or anything else that only needs final topology +
# coordinates) without redoing motion-relink / gap-close / safe-divisions.
# ---------------------------------------------------------------------------
def save_prelinefit_checkpoint(geff_dir: Path, checkpoint_dir: Path, cfg: PostprocConfig) -> dict[str, object]:
    """Run the stack up to (excluding) linefit smoothing; pickle one file per dataset.

    Each ``<dataset>.pkl`` holds ``{"dataset", "raw_node_count", "nodes_by_id",
    "edges", "stats"}`` -- the exact ``nodes_by_id``/``edges``/``stats`` that
    :func:`filter_output_graph_pre_linefit` returned, coordinates as the
    float64 Python floats they already are (pickle round-trips them exactly).
    A ``manifest.json`` records the dataset order (matches ``sorted(*.geff)``).
    """
    geffs = sorted(geff_dir.glob("*.geff"))
    if not geffs:
        raise RuntimeError(f"no *.geff files found in {geff_dir}")

    _require_steal_twin_r1_dry_run(cfg)
    twin_debug_collector: _TwinDebugCollector | None = None
    twin_debug_path: Path | None = None
    if cfg.OUTPUT_STEAL_TWIN_REWIRE and cfg.STEAL_TWIN_DEBUG_JSONL:
        twin_debug_path = Path(cfg.STEAL_TWIN_DEBUG_JSONL)
        _reject_twin_debug_aliases(
            geff_dir,
            geffs,
            twin_debug_path,
            (
                checkpoint_dir,
                checkpoint_dir / CHECKPOINT_MANIFEST_NAME,
                *(checkpoint_dir / f"{geff_path.stem}.pkl" for geff_path in geffs),
            ),
        )
        twin_debug_collector = _TwinDebugCollector(cfg.STEAL_TWIN_DEBUG_MAX_RECORDS)

    deepcenter_detector = load_deepcenter_veto_detector(cfg)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    datasets: list[str] = []
    for geff_path in geffs:
        dataset = geff_path.stem
        nodes_by_id, raw_edges = _load_geff_as_dicts(geff_path)
        raw_node_count = len(nodes_by_id)
        nodes_by_id, edges, stats = filter_output_graph_pre_linefit(
            cfg,
            nodes_by_id,
            raw_edges,
            dataset=dataset,
            deepcenter_bundle=deepcenter_detector,
            twin_debug_collector=twin_debug_collector,
        )
        if not nodes_by_id:
            raise AssertionError(f"{dataset}: post-processing removed every node")
        payload = {
            "dataset": dataset,
            "raw_node_count": raw_node_count,
            "nodes_by_id": nodes_by_id,
            "edges": edges,
            "stats": stats,
        }
        with (checkpoint_dir / f"{dataset}.pkl").open("wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        datasets.append(dataset)

    manifest = {"geff_dir": str(geff_dir), "datasets": datasets}
    (checkpoint_dir / CHECKPOINT_MANIFEST_NAME).write_text(json.dumps(manifest, indent=2))
    if twin_debug_collector is not None and twin_debug_path is not None:
        twin_debug_collector.finalize(twin_debug_path)
    return manifest


def run_relinefit(
    checkpoint_dir: Path,
    out_csv: Path,
    cfg: PostprocConfig,
    run_stats_path: Path | None = None,
    predict_seconds: float = 0.0,
) -> dict[str, object]:
    """Load a :func:`save_prelinefit_checkpoint` checkpoint, apply linefit smoothing, write the CSV.

    ``cfg`` only needs to change ``BIOHUB_OUTPUT_LINEFIT_*`` between calls;
    every other post-processing pass has already been baked into the
    checkpoint and is not re-run.
    """
    manifest_path = checkpoint_dir / CHECKPOINT_MANIFEST_NAME
    if not manifest_path.exists():
        raise FileNotFoundError(f"no {CHECKPOINT_MANIFEST_NAME} in {checkpoint_dir} (run --save-prelinefit first)")
    manifest = json.loads(manifest_path.read_text())
    datasets: list[str] = manifest["datasets"]
    if not datasets:
        raise RuntimeError(f"{manifest_path}: empty dataset list")

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    stats_rows: list[dict[str, object]] = []
    total_nodes = 0
    total_edges = 0

    with out_csv.open("w", newline="") as handle:
        writer = SubmissionCsvWriter(handle)

        for dataset in datasets:
            checkpoint_path = checkpoint_dir / f"{dataset}.pkl"
            with checkpoint_path.open("rb") as f:
                payload = pickle.load(f)  # noqa: S301 - our own checkpoint, not untrusted input

            nodes_by_id = payload["nodes_by_id"]
            edges = payload["edges"]
            stats = dict(payload["stats"])  # copy: don't mutate the on-disk checkpoint's stats in memory

            twin_candidate_active = (
                stats.get("steal_twin_pure_nodes", 0) > 0
                or stats.get("steal_twin_pure_edges", 0) > 0
            )
            nodes_by_id = _linefit_with_twin_r2_guard(
                cfg,
                nodes_by_id,
                edges,
                stats,
                enabled=twin_candidate_active,
            )

            writer.write_nodes(dataset, nodes_by_id)
            division_sources = writer.write_edges(dataset, nodes_by_id, edges)

            total_nodes += len(nodes_by_id)
            total_edges += len(edges)
            stats_rows.append(
                _dataset_stats_row(dataset, nodes_by_id, edges, stats, payload["raw_node_count"], division_sources)
            )

    stats_frame = _finish_run(
        writer, stats_rows, total_nodes, total_edges, cfg, run_stats_path or out_csv.parent / "run_stats.csv", predict_seconds
    )

    return {
        "datasets": datasets,
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "total_rows": writer.row_id,
        "run_stats": stats_frame,
    }
