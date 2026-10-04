# Derived from the public Kaggle notebook "Clean Approach + Lightweight Local CV | No Hack"
# by Yusuke Togashi (https://www.kaggle.com/code/yusuketogashi/clean-approach-lightweight-local-cv-no-hack),
# licensed under the Apache License 2.0 (LICENSES/Apache-2.0.txt).
# Modified: ported from notebook cells into a torch-free package; see THIRD_PARTY_NOTICES.md.
"""Division-related post-processing passes, ported verbatim from the notebook cell.

Two candidate-generation modes share the exact same proposal acceptance loop
(sorting, frame/global caps, used-target conflicts, output edge fields):

* ``legacy`` -- the pre-E23 port: pure distance gates, no structural
  constraints. Output is byte-for-byte identical to the Phase-1 behavior.
* ``e23`` -- the submitted E23 notebook's ``add_safe_divisions_postlink``
  (pub923_repro): all-orphan cKDTree, mid-track parent (C1), mutual nearest
  orphan (C2), DeepCenter veto before t+2 divergence growth (C3), accepting
  exactly the notebook's candidate set.

Both modes share the exact notebook proposal-acceptance loop: sort by
``parent_dist + 0.15 * sister_dist``, frame cap, global cap, and the
used-target conflict check, appending accepted edges after the originals.
"""
from __future__ import annotations

import math
import struct
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Literal

import numpy as np
from scipy.spatial import cKDTree

from biohub.public_postproc.config import PostprocConfig
from biohub.public_postproc.deepcenter import (
    deepcenter_accept_repair_point,
    deepcenter_heatmap_for_frame,
)
from biohub.public_postproc.frames import read_test_frame
from biohub.public_postproc.geometry import VOXEL_SCALE_UM, edge_distance_um


@dataclass(frozen=True)
class TwinDeepCenterDecision:
    accepted: bool
    raw_score: float | None
    reason: str | None


@dataclass(frozen=True)
class TwinFrozenMapping(Mapping[object, object]):
    """Small immutable, insertion-order-preserving mapping snapshot."""

    items_snapshot: tuple[tuple[object, object], ...]

    def __getitem__(self, key: object) -> object:
        for item_key, value in self.items_snapshot:
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[object]:
        return (key for key, _ in self.items_snapshot)

    def __len__(self) -> int:
        return len(self.items_snapshot)


@dataclass(frozen=True)
class TwinFrozenDType:
    """Immutable dtype description, including structured fields and metadata."""

    string: str
    descriptor: object
    metadata: TwinFrozenMapping | None
    itemsize: int
    alignment: int
    byteorder: str
    names: tuple[str, ...] | None
    hasobject: bool
    aligned_struct: bool


@dataclass(frozen=True)
class TwinFrozenStructuredScalar:
    fields: tuple[tuple[str, object], ...]


@dataclass(frozen=True)
class TwinFrozenNumpyScalar:
    dtype: TwinFrozenDType
    content: bytes


@dataclass(frozen=True)
class TwinFrozenArray:
    """Immutable, lossless semantic snapshot of an ndarray."""

    dtype: TwinFrozenDType
    shape: tuple[int, ...]
    strides: tuple[int, ...]
    c_contiguous: bool
    f_contiguous: bool
    content: bytes | tuple[object, ...]
    object_content: bool


@dataclass(frozen=True)
class TwinFrozenBuffer:
    """Immutable snapshot of a bytearray or memoryview."""

    kind: str
    format: str
    itemsize: int
    shape: tuple[int, ...]
    strides: tuple[int, ...]
    readonly: bool
    content: bytes


@dataclass(frozen=True)
class TwinSnapshotNode:
    node_id: int
    t: int
    z: float
    y: float
    x: float
    gap_synthetic: bool


@dataclass(frozen=True)
class TwinSnapshotEdge:
    source_id: int
    target_id: int
    input_position: int
    metadata: TwinFrozenMapping


@dataclass(frozen=True)
class TwinEdgeRecord:
    """Public edge snapshot; the internal caller-row ordinal is intentionally absent."""

    source_id: int
    target_id: int
    metadata: TwinFrozenMapping


@dataclass(frozen=True)
class TwinPlannedEdge:
    source_id: int
    target_id: int
    distance_um: float
    edge_prob: None = None


type TwinScoreCallback = Callable[[TwinSnapshotNode], TwinDeepCenterDecision]


@dataclass(frozen=True)
class TwinCandidate:
    frame: int
    p: int
    q: int
    a: int
    b: int
    a2: int
    b2: int
    d_pq: float
    d_pa: float
    d_pb: float
    d_ab: float
    d_a2b2: float
    divergence_growth: float
    raw_deepcenter_score: float
    deepcenter_decision: TwinDeepCenterDecision
    sort_key: tuple[float, float, float, int, int, int, int, int, int]
    removed_edge: TwinEdgeRecord
    planned_edge: TwinPlannedEdge


@dataclass(frozen=True)
class TwinResolutionDecision:
    candidate: TwinCandidate
    accepted: bool
    reason: str | None


@dataclass(frozen=True)
class TwinDebugRecord:
    dataset: str | None
    decision: str
    reason: str | None
    p: int
    q: int
    a: int
    b: int
    a2: int
    b2: int
    sort_key: tuple[float, float, float, int, int, int, int, int, int]
    d_pq: float
    d_pa: float
    d_pb: float
    d_ab: float
    d_a2b2: float
    divergence_growth: float
    raw_deepcenter_score: float
    deepcenter_threshold: float
    deepcenter_decision: TwinDeepCenterDecision
    removed_edge: TwinEdgeRecord
    planned_edge: TwinPlannedEdge


@dataclass(frozen=True)
class TwinPlan:
    validation_reason: str | None
    nodes: tuple[TwinSnapshotNode, ...]
    edges: tuple[TwinSnapshotEdge, ...]
    candidates: tuple[TwinCandidate, ...]
    accepted_candidates: tuple[TwinCandidate, ...]
    decisions: tuple[TwinResolutionDecision, ...]
    counters: TwinFrozenMapping
    debug_records: tuple[TwinDebugRecord, ...]


@dataclass(frozen=True)
class TwinMutationSummary:
    status: Literal["applied", "already_applied", "no_changes"]
    accepted_count: int
    nodes_before: int
    nodes_after: int
    edges_before: int
    edges_after: int
    edges_removed: int
    edges_added: int
    edge_symmetric_difference: int
    isolated_donors: int


class TwinMutationError(RuntimeError):
    reason: str

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


_TWIN_COUNTER_KEYS = (
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
)

_TWIN_DEEPCENTER_REASONS = (
    "deepcenter_bundle",
    "deepcenter_dataset",
    "deepcenter_frame",
    "deepcenter_heatmap",
    "deepcenter_nonfinite",
    "deepcenter_threshold",
)

_TWIN_METADATA_MAX_DEPTH = 64

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


def _freeze_twin_dtype(
    dtype: np.dtype,
    *,
    _depth: int = 0,
    _active: set[int] | None = None,
) -> TwinFrozenDType:
    if _depth > _TWIN_METADATA_MAX_DEPTH:
        raise TypeError("twin metadata exceeds maximum depth")
    active = set() if _active is None else _active
    metadata = (
        _freeze_twin_value(dtype.metadata, _depth=_depth + 1, _active=active)
        if dtype.metadata is not None
        else None
    )
    if metadata is not None and not isinstance(metadata, TwinFrozenMapping):
        raise TypeError("numpy dtype metadata must be a mapping")
    return TwinFrozenDType(
        dtype.str,
        _freeze_twin_value(dtype.descr, _depth=_depth + 1, _active=active),
        metadata,
        int(dtype.itemsize),
        int(dtype.alignment),
        dtype.byteorder,
        tuple(dtype.names) if dtype.names is not None else None,
        bool(dtype.hasobject),
        bool(dtype.isalignedstruct),
    )


def _freeze_twin_structured_scalar(
    value: np.void,
    dtype: np.dtype,
    *,
    _depth: int = 0,
    _active: set[int] | None = None,
) -> TwinFrozenStructuredScalar:
    if _depth > _TWIN_METADATA_MAX_DEPTH:
        raise TypeError("twin metadata exceeds maximum depth")
    if dtype.names is None:
        raise TypeError("unstructured numpy void metadata is unsupported")
    active = set() if _active is None else _active
    return TwinFrozenStructuredScalar(
        tuple(
            (name, _freeze_twin_value(value[name], _depth=_depth + 1, _active=active))
            for name in dtype.names
        )
    )


def _freeze_twin_value(
    value: object,
    *,
    _depth: int = 0,
    _active: set[int] | None = None,
) -> object:
    """Freeze supported edge metadata or reject it before a plan is returned.

    Supported values are standard immutable scalars, recursively frozen
    mappings/sequences/sets, NumPy dtypes/scalars/arrays, bytearrays, and
    memoryviews. Arbitrary objects are rejected rather than retained behind a
    frozen dataclass or ambiguously deep-copied.
    """
    if _depth > _TWIN_METADATA_MAX_DEPTH:
        raise TypeError("twin metadata exceeds maximum depth")
    active = set() if _active is None else _active
    recursive = isinstance(
        value,
        (np.dtype, np.ndarray, np.void, Mapping, list, tuple, set, frozenset),
    )
    value_id = id(value)
    if recursive:
        if value_id in active:
            raise TypeError("cyclic twin metadata")
        active.add(value_id)
    try:
        return _freeze_twin_value_inner(value, _depth, active)
    finally:
        if recursive:
            active.remove(value_id)


def _freeze_twin_value_inner(value: object, depth: int, active: set[int]) -> object:
    if isinstance(value, np.dtype):
        return _freeze_twin_dtype(value, _depth=depth, _active=active)
    if isinstance(value, np.ndarray):
        original_shape = tuple(value.shape)
        original_strides = tuple(value.strides)
        copied_array = np.array(value, copy=True, subok=False, order="K")
        if value.dtype.hasobject:
            if value.dtype.names is not None:
                content: bytes | tuple[object, ...] = tuple(
                    _freeze_twin_structured_scalar(
                        copied_array[index], value.dtype, _depth=depth + 1, _active=active
                    )
                    for index in np.ndindex(original_shape)
                )
            else:
                content = tuple(
                    _freeze_twin_value(
                        copied_array[index], _depth=depth + 1, _active=active
                    )
                    for index in np.ndindex(original_shape)
                )
        else:
            content = copied_array.tobytes(order="C")
        return TwinFrozenArray(
            _freeze_twin_dtype(value.dtype, _depth=depth + 1, _active=active),
            original_shape,
            original_strides,
            bool(value.flags.c_contiguous),
            bool(value.flags.f_contiguous),
            content,
            bool(value.dtype.hasobject),
        )
    if isinstance(value, bytearray):
        return TwinFrozenBuffer("bytearray", "B", 1, (len(value),), (1,), False, bytes(value))
    if isinstance(value, memoryview):
        shape = tuple(value.shape) if value.shape is not None else (value.nbytes // value.itemsize,)
        strides = tuple(value.strides) if value.strides is not None else ()
        return TwinFrozenBuffer(
            "memoryview",
            value.format,
            value.itemsize,
            shape,
            strides,
            value.readonly,
            value.tobytes(),
        )
    if isinstance(value, Mapping):
        return TwinFrozenMapping(
            tuple(
                (
                    _freeze_twin_value(key, _depth=depth + 1, _active=active),
                    _freeze_twin_value(item, _depth=depth + 1, _active=active),
                )
                for key, item in value.items()
            )
        )
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_twin_value(item, _depth=depth + 1, _active=active) for item in value
        )
    if isinstance(value, (set, frozenset)):
        return frozenset(
            _freeze_twin_value(item, _depth=depth + 1, _active=active) for item in value
        )
    if isinstance(value, np.void):
        return _freeze_twin_structured_scalar(value, value.dtype, _depth=depth, _active=active)
    if isinstance(value, np.generic):
        if value.dtype.hasobject:
            raise TypeError(f"unsupported numpy object scalar metadata: {value.dtype!r}")
        return TwinFrozenNumpyScalar(
            _freeze_twin_dtype(value.dtype, _depth=depth + 1, _active=active),
            value.tobytes(),
        )
    if value is None or type(value) in (bool, int, float, complex, str, bytes):
        return value
    raise TypeError(f"unsupported mutable edge metadata type: {type(value).__qualname__}")


def _freeze_twin_edge_row(
    row: Mapping[str, object],
    source_id: int,
    target_id: int,
    *,
    _source_key: object | None = None,
    _target_key: object | None = None,
) -> TwinFrozenMapping:
    """Freeze an edge row, canonicalizing its validated integer endpoints.

    Endpoint validation deliberately accepts every non-boolean
    :class:`numbers.Integral`, while the planner's endpoint contract is the
    canonical integer value used for graph identity.  Converting only the two
    endpoint fields to built-in ``int`` therefore preserves that contract and
    detaches mutable ``int`` subclasses without broadening the supported
    types for arbitrary edge metadata.
    """
    active = {id(row)}
    frozen_items: list[tuple[object, object]] = []
    try:
        for key, value in row.items():
            if _source_key is not None and key is _source_key:
                frozen_items.append((str(key), source_id))
            elif _target_key is not None and key is _target_key:
                frozen_items.append((str(key), target_id))
            elif _source_key is None and isinstance(key, str) and key == "source_id":
                frozen_items.append((str(key), source_id))
            elif _target_key is None and isinstance(key, str) and key == "target_id":
                frozen_items.append((str(key), target_id))
            else:
                frozen_items.append(
                    (
                        _freeze_twin_value(key, _depth=1, _active=active),
                        _freeze_twin_value(value, _depth=1, _active=active),
                    )
                )
    finally:
        active.remove(id(row))
    return TwinFrozenMapping(tuple(frozen_items))


def _twin_counters() -> dict[str, int]:
    return dict.fromkeys(_TWIN_COUNTER_KEYS, 0)


def _frozen_twin_counters(counters: Mapping[str, int]) -> TwinFrozenMapping:
    return TwinFrozenMapping(tuple((key, int(counters[key])) for key in _TWIN_COUNTER_KEYS))


def _invalid_twin_plan(reason: str) -> TwinPlan:
    counters = _twin_counters()
    counters["steal_twin_validation_failed"] = 1
    counters[f"steal_twin_validation_{reason}"] = 1
    return TwinPlan(reason, (), (), (), (), (), _frozen_twin_counters(counters), ())


def _is_twin_integer(value: object) -> bool:
    return not isinstance(value, (bool, np.bool_)) and isinstance(value, Integral)


def _is_twin_finite_real(value: object) -> bool:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        return False
    try:
        return bool(np.isfinite(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _twin_distance(first: TwinSnapshotNode, second: TwinSnapshotNode) -> float:
    try:
        with np.errstate(all="ignore"):
            delta = np.asarray(
                [
                    (first.z - second.z) * VOXEL_SCALE_UM[0],
                    (first.y - second.y) * VOXEL_SCALE_UM[1],
                    (first.x - second.x) * VOXEL_SCALE_UM[2],
                ],
                dtype=np.float64,
            )
            distance = float(np.sqrt(np.sum(delta * delta)))
    except (ArithmeticError, TypeError, ValueError, OverflowError):
        return float("nan")
    return distance


def _validate_twin_snapshot(
    node_rows: Sequence[Mapping[str, object]],
    edge_rows: Sequence[Mapping[str, object]],
) -> tuple[str | None, tuple[TwinSnapshotNode, ...], tuple[TwinSnapshotEdge, ...]]:
    required = ("node_id", "t", "z", "y", "x")
    if any(not isinstance(row, Mapping) or any(name not in row for name in required) for row in node_rows):
        return "missing_node_field", (), ()
    if any(not _is_twin_integer(row["node_id"]) for row in node_rows):
        return "invalid_node_id", (), ()
    node_ids = [int(row["node_id"]) for row in node_rows]
    if len(node_ids) != len(set(node_ids)):
        return "duplicate_node_id", (), ()
    if any(not _is_twin_integer(row["t"]) for row in node_rows):
        return "invalid_node_time", (), ()
    if any(not all(_is_twin_finite_real(row[name]) for name in ("z", "y", "x")) for row in node_rows):
        return "nonfinite_node_coordinate", (), ()

    nodes = tuple(
        sorted(
            (
                TwinSnapshotNode(
                    int(row["node_id"]),
                    int(row["t"]),
                    float(row["z"]),
                    float(row["y"]),
                    float(row["x"]),
                    bool(row.get("gap_synthetic", False) == 1),
                )
                for row in node_rows
            ),
            key=lambda node: node.node_id,
        )
    )
    by_id = {node.node_id: node for node in nodes}

    if any(
        not isinstance(row, Mapping)
        or "source_id" not in row
        or "target_id" not in row
        or not _is_twin_integer(row["source_id"])
        or not _is_twin_integer(row["target_id"])
        for row in edge_rows
    ):
        return "invalid_edge_endpoint", (), ()
    endpoints = [(int(row["source_id"]), int(row["target_id"])) for row in edge_rows]
    if any(source not in by_id or target not in by_id for source, target in endpoints):
        return "dangling_edge", (), ()
    if len(endpoints) != len(set(endpoints)):
        return "duplicate_edge", (), ()
    if any(by_id[target].t != by_id[source].t + 1 for source, target in endpoints):
        return "nonconsecutive_edge", (), ()
    indegree: dict[int, int] = {}
    outdegree: dict[int, int] = {}
    for source, target in endpoints:
        outdegree[source] = outdegree.get(source, 0) + 1
        indegree[target] = indegree.get(target, 0) + 1
    if any(value > 1 for value in indegree.values()):
        return "indegree", (), ()
    if any(value > 2 for value in outdegree.values()):
        return "outdegree", (), ()
    if any(not np.isfinite(_twin_distance(by_id[source], by_id[target])) for source, target in endpoints):
        return "nonfinite_edge_distance", (), ()

    edges = tuple(
        sorted(
            (
                TwinSnapshotEdge(
                    source,
                    target,
                    position,
                    _freeze_twin_edge_row(row, source, target),
                )
                for position, (row, (source, target)) in enumerate(
                    zip(edge_rows, endpoints, strict=True)
                )
            ),
            key=lambda edge: (edge.source_id, edge.target_id, edge.input_position),
        )
    )
    return None, nodes, edges


def _normalize_twin_score(result: object) -> TwinDeepCenterDecision:
    fallback = TwinDeepCenterDecision(False, None, "deepcenter_bundle")
    if not isinstance(result, TwinDeepCenterDecision) or type(result.accepted) is not bool:
        return fallback
    score = result.raw_score
    valid_score = _is_twin_finite_real(score) if score is not None else False
    if result.accepted:
        if not valid_score or result.reason is not None:
            return fallback
        return TwinDeepCenterDecision(True, float(score), None)
    if result.reason not in _TWIN_DEEPCENTER_REASONS:
        return fallback
    if result.reason == "deepcenter_threshold":
        if not valid_score or float(score) >= 0.12:
            return fallback
        return TwinDeepCenterDecision(False, float(score), result.reason)
    if score is not None:
        return fallback
    return TwinDeepCenterDecision(False, None, result.reason)


def plan_twin_only_v1(
    cfg: PostprocConfig,
    dataset: str | None,
    node_rows: Sequence[Mapping[str, object]],
    edge_rows: Sequence[Mapping[str, object]],
    score_callback: TwinScoreCallback,
) -> TwinPlan:
    """Build the immutable, deterministic ST-R1b twin-only rewire plan."""
    validation_reason, nodes, edges = _validate_twin_snapshot(node_rows, edge_rows)
    if validation_reason is not None:
        return _invalid_twin_plan(validation_reason)

    counters = _twin_counters()
    by_id = {node.node_id: node for node in nodes}
    incoming: dict[int, list[TwinSnapshotEdge]] = {}
    outgoing: dict[int, list[TwinSnapshotEdge]] = {}
    for edge in edges:
        outgoing.setdefault(edge.source_id, []).append(edge)
        incoming.setdefault(edge.target_id, []).append(edge)
    for values in outgoing.values():
        values.sort(key=lambda edge: edge.target_id)

    p_pool: dict[int, list[int]] = {}
    q_pool: dict[int, list[int]] = {}
    for node in nodes:
        indegree = len(incoming.get(node.node_id, ()))
        outdegree = len(outgoing.get(node.node_id, ()))
        if indegree == 1 and outdegree == 1:
            p_pool.setdefault(node.t, []).append(node.node_id)
        if indegree == 0 and outdegree == 1:
            q_pool.setdefault(node.t, []).append(node.node_id)
    for pool in (p_pool, q_pool):
        for values in pool.values():
            values.sort()
    frames = sorted(set(p_pool) | set(q_pool))
    counters["steal_twin_examined_frames"] = len(frames)
    counters["steal_twin_p_pool"] = sum(map(len, p_pool.values()))
    counters["steal_twin_q_pool"] = sum(map(len, q_pool.values()))

    eligible: list[TwinCandidate] = []

    def reject(reason: str) -> None:
        counters[f"steal_twin_rejected_{reason}"] += 1

    for frame in frames:
        p_ids = p_pool.get(frame, ())
        q_ids = q_pool.get(frame, ())
        if not p_ids or not q_ids:
            continue
        union_ids = sorted((*p_ids, *q_ids))
        frame_origin = by_id[union_ids[0]]
        positions = np.asarray(
            [
                (
                    (by_id[node_id].z - frame_origin.z) * VOXEL_SCALE_UM[0],
                    (by_id[node_id].y - frame_origin.y) * VOXEL_SCALE_UM[1],
                    (by_id[node_id].x - frame_origin.x) * VOXEL_SCALE_UM[2],
                )
                for node_id in union_ids
            ],
            dtype=np.float64,
        )
        union_index = {node_id: index for index, node_id in enumerate(union_ids)}
        tree_coordinate_scale = max(cfg.STEAL_TWIN_TWIN_MAX_UM, 1.0, *np.abs(positions).flat)
        # The tree sees translated/scaled coordinates and performs more float
        # operations internally. Query a conservative roundoff superset, then
        # enforce the exact frozen radius using _twin_distance below.
        query_roundoff = 32.0 * np.finfo(np.float64).eps * np.sqrt(3.0) * tree_coordinate_scale
        query_radius = float(
            np.nextafter(cfg.STEAL_TWIN_TWIN_MAX_UM + query_roundoff, np.inf)
        )
        if np.all(np.isfinite(positions)) and np.isfinite(query_radius):
            try:
                tree = cKDTree(positions)
            except Exception:
                tree = None
        else:
            tree = None
        role_p = set(p_ids)
        role_q = set(q_ids)

        def neighbors(
            node_id: int,
            opposite: set[int],
            frame_tree=tree,
            frame_positions=positions,
            frame_union_ids=tuple(union_ids),
            frame_union_index=union_index,
            frame_query_radius=query_radius,
        ) -> list[tuple[float, int]] | None:
            if frame_tree is None:
                return None
            point = frame_positions[frame_union_index[node_id]]
            try:
                indices = frame_tree.query_ball_point(point, r=frame_query_radius)
                result = []
                for index in indices:
                    other_id = frame_union_ids[int(index)]
                    if other_id not in opposite:
                        continue
                    distance = _twin_distance(by_id[node_id], by_id[other_id])
                    if not np.isfinite(distance):
                        return None
                    if distance <= cfg.STEAL_TWIN_TWIN_MAX_UM:
                        result.append((distance, other_id))
            except Exception:
                return None
            result.sort(key=lambda item: (item[0], item[1]))
            return result

        for p_id in p_ids:
            counters["steal_twin_enumerated"] += 1
            p_neighbors = neighbors(p_id, role_q)
            if not p_neighbors:
                reject("distance_twin")
                continue
            minimum = p_neighbors[0][0]
            if sum(distance - minimum <= 1e-9 for distance, _ in p_neighbors) != 1:
                reject("ambiguous_p_nn")
                continue
            d_pq, q_id = p_neighbors[0]
            q_neighbors = neighbors(q_id, role_p)
            if not q_neighbors:
                reject("distance_twin")
                continue
            q_minimum = q_neighbors[0][0]
            if sum(distance - q_minimum <= 1e-9 for distance, _ in q_neighbors) != 1:
                reject("ambiguous_q_nn")
                continue
            if q_neighbors[0][1] != p_id:
                reject("not_mutual_parent_nn")
                continue

            a_id = outgoing[p_id][0].target_id
            a = by_id[a_id]
            d_pa = _twin_distance(by_id[p_id], a)
            if not np.isfinite(d_pa) or d_pa > cfg.STEAL_TWIN_EXISTING_CHILD_MAX_UM:
                reject("distance_existing_child")
                continue
            b_edge = outgoing[q_id][0]
            b_id = b_edge.target_id
            b = by_id[b_id]
            d_pb = _twin_distance(by_id[p_id], b)
            if not np.isfinite(d_pb) or d_pb > cfg.STEAL_TWIN_PARENT_MAX_UM:
                reject("distance_parent")
                continue
            d_ab = _twin_distance(a, b)
            if np.isfinite(d_ab) and d_ab < cfg.STEAL_TWIN_SISTER_MIN_UM:
                reject("distance_sister_low")
                continue
            if not np.isfinite(d_ab) or d_ab > cfg.STEAL_TWIN_SISTER_MAX_UM:
                reject("distance_sister_high")
                continue
            if len(outgoing.get(a_id, ())) != 1 or len(outgoing.get(b_id, ())) != 1:
                reject("missing_successor")
                continue
            a2_id = outgoing[a_id][0].target_id
            b2_id = outgoing[b_id][0].target_id
            if a2_id == b2_id:
                reject("shared_successor")
                continue
            d_a2b2 = _twin_distance(by_id[a2_id], by_id[b2_id])
            with np.errstate(all="ignore"):
                growth = d_a2b2 - d_ab
            if not np.isfinite(d_a2b2) or not np.isfinite(growth) or growth < cfg.STEAL_TWIN_DIVERGE_UM:
                reject("divergence")
                continue
            role_ids = (p_id, q_id, a_id, b_id, a2_id, b2_id)
            if any(by_id[node_id].gap_synthetic for node_id in role_ids):
                reject("synthetic")
                continue
            try:
                deepcenter = _normalize_twin_score(score_callback(b))
            except Exception:
                deepcenter = TwinDeepCenterDecision(False, None, "deepcenter_bundle")
            if not deepcenter.accepted:
                reject(deepcenter.reason or "deepcenter_bundle")
                continue
            sort_key = (
                d_pb + 0.15 * d_ab,
                -growth,
                d_pq,
                p_id,
                q_id,
                a_id,
                b_id,
                a2_id,
                b2_id,
            )
            if not all(np.isfinite(value) for value in sort_key[:3]):
                reject("divergence")
                continue
            candidate = TwinCandidate(
                frame,
                p_id,
                q_id,
                a_id,
                b_id,
                a2_id,
                b2_id,
                d_pq,
                d_pa,
                d_pb,
                d_ab,
                d_a2b2,
                float(growth),
                deepcenter.raw_score,
                deepcenter,
                sort_key,
                TwinEdgeRecord(b_edge.source_id, b_edge.target_id, b_edge.metadata),
                TwinPlannedEdge(p_id, b_id, d_pb),
            )
            eligible.append(candidate)
            counters["steal_twin_eligible"] += 1

    eligible.sort(key=lambda candidate: candidate.sort_key)
    decisions: list[TwinResolutionDecision] = []
    accepted: list[TwinCandidate] = []
    debug_records: list[TwinDebugRecord] = []
    used_ids: set[int] = set()
    accepted_by_frame: dict[int, int] = {}
    for candidate in eligible:
        candidate_ids = {candidate.p, candidate.q, candidate.a, candidate.b, candidate.a2, candidate.b2}
        if candidate_ids & used_ids:
            reason = "conflict"
        elif accepted_by_frame.get(candidate.frame, 0) >= cfg.STEAL_TWIN_FRAME_CAP_ABS:
            reason = "frame_cap"
        elif len(accepted) >= cfg.STEAL_TWIN_VIDEO_CAP_ABS:
            reason = "video_cap"
        else:
            reason = None
            accepted.append(candidate)
            used_ids.update(candidate_ids)
            accepted_by_frame[candidate.frame] = accepted_by_frame.get(candidate.frame, 0) + 1
        is_accepted = reason is None
        decisions.append(TwinResolutionDecision(candidate, is_accepted, reason))
        if is_accepted:
            counters["steal_twin_accepted"] += 1
        else:
            counters[f"steal_twin_rejected_{reason}"] += 1
        debug_records.append(
            TwinDebugRecord(
                dataset,
                "accepted" if is_accepted else "rejected",
                reason,
                candidate.p,
                candidate.q,
                candidate.a,
                candidate.b,
                candidate.a2,
                candidate.b2,
                candidate.sort_key,
                candidate.d_pq,
                candidate.d_pa,
                candidate.d_pb,
                candidate.d_ab,
                candidate.d_a2b2,
                candidate.divergence_growth,
                candidate.raw_deepcenter_score,
                0.12,
                candidate.deepcenter_decision,
                candidate.removed_edge,
                candidate.planned_edge,
            )
        )
    accepted_count = len(accepted)
    counters["steal_twin_planned_edges_removed"] = accepted_count
    counters["steal_twin_planned_edges_added"] = accepted_count
    counters["steal_twin_isolated_donors"] = accepted_count
    return TwinPlan(
        None,
        nodes,
        edges,
        tuple(eligible),
        tuple(accepted),
        tuple(decisions),
        _frozen_twin_counters(counters),
        tuple(debug_records),
    )


class _TwinMutationFault(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


def _twin_exact_tuple(value: object, *, length: int | None = None) -> bool:
    return type(value) is tuple and (length is None or len(value) == length)


def _twin_shape_product(shape: tuple[int, ...]) -> int:
    result = 1
    for size in shape:
        result *= size
    return result


def _twin_frozen_token(value: object) -> tuple[object, ...]:
    """Return a bit-exact, recursively hashable token for an R1 frozen value."""
    try:
        return _twin_frozen_token_inner(value, 0, set())
    except TypeError:
        raise
    except Exception as exc:
        raise TypeError("invalid frozen twin value") from exc


def _twin_frozen_token_inner(
    value: object,
    depth: int,
    active: set[int],
) -> tuple[object, ...]:
    if depth > _TWIN_METADATA_MAX_DEPTH:
        raise TypeError("twin metadata exceeds maximum depth")
    value_type = type(value)
    if value is None:
        return ("none",)
    if value_type is bool:
        return ("bool", value)
    if value_type is int:
        return ("int", value)
    if value_type is float:
        return ("float", struct.pack(">d", value))
    if value_type is complex:
        return ("complex", struct.pack(">d", value.real), struct.pack(">d", value.imag))
    if value_type is str:
        return ("str", value)
    if value_type is bytes:
        return ("bytes", value)

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
        raise TypeError("unsupported frozen twin value")
    value_id = id(value)
    if value_id in active:
        raise TypeError("cyclic frozen twin value")
    active.add(value_id)
    try:
        if value_type is tuple:
            return (
                "tuple",
                tuple(_twin_frozen_token_inner(item, depth + 1, active) for item in value),
            )
        if value_type is frozenset:
            counts = Counter(
                _twin_frozen_token_inner(item, depth + 1, active) for item in value
            )
            return ("frozenset", frozenset((token, count) for token, count in counts.items()))
        if value_type is TwinFrozenMapping:
            if not _twin_exact_tuple(value.items_snapshot):
                raise TypeError("invalid frozen mapping items")
            items: list[tuple[tuple[object, ...], tuple[object, ...]]] = []
            for pair in value.items_snapshot:
                if not _twin_exact_tuple(pair, length=2):
                    raise TypeError("invalid frozen mapping item")
                items.append(
                    (
                        _twin_frozen_token_inner(pair[0], depth + 1, active),
                        _twin_frozen_token_inner(pair[1], depth + 1, active),
                    )
                )
            return ("mapping", tuple(items))
        if value_type is TwinFrozenDType:
            if (
                type(value.string) is not str
                or type(value.itemsize) is not int
                or value.itemsize < 0
                or type(value.alignment) is not int
                or value.alignment < 0
                or type(value.byteorder) is not str
                or type(value.hasobject) is not bool
                or type(value.aligned_struct) is not bool
                or (value.metadata is not None and type(value.metadata) is not TwinFrozenMapping)
            ):
                raise TypeError("invalid frozen dtype fields")
            if value.names is not None:
                if (
                    not _twin_exact_tuple(value.names)
                    or any(type(name) is not str for name in value.names)
                    or len(set(value.names)) != len(value.names)
                ):
                    raise TypeError("invalid frozen dtype names")
            return (
                "dtype",
                value.string,
                _twin_frozen_token_inner(value.descriptor, depth + 1, active),
                None
                if value.metadata is None
                else _twin_frozen_token_inner(value.metadata, depth + 1, active),
                value.itemsize,
                value.alignment,
                value.byteorder,
                value.names,
                value.hasobject,
                value.aligned_struct,
            )
        if value_type is TwinFrozenStructuredScalar:
            if not _twin_exact_tuple(value.fields):
                raise TypeError("invalid structured scalar fields")
            names: list[str] = []
            fields: list[tuple[str, tuple[object, ...]]] = []
            for pair in value.fields:
                if not _twin_exact_tuple(pair, length=2) or type(pair[0]) is not str:
                    raise TypeError("invalid structured scalar field")
                names.append(pair[0])
                fields.append(
                    (pair[0], _twin_frozen_token_inner(pair[1], depth + 1, active))
                )
            if len(set(names)) != len(names):
                raise TypeError("duplicate structured scalar field")
            return ("structured_scalar", tuple(fields))
        if value_type is TwinFrozenNumpyScalar:
            if type(value.dtype) is not TwinFrozenDType or type(value.content) is not bytes:
                raise TypeError("invalid frozen numpy scalar")
            dtype_token = _twin_frozen_token_inner(value.dtype, depth + 1, active)
            if value.dtype.hasobject or len(value.content) != value.dtype.itemsize:
                raise TypeError("invalid frozen numpy scalar length")
            return ("numpy_scalar", dtype_token, value.content)
        if value_type is TwinFrozenArray:
            if (
                type(value.dtype) is not TwinFrozenDType
                or not _twin_exact_tuple(value.shape)
                or not _twin_exact_tuple(value.strides)
                or any(type(size) is not int or size < 0 for size in value.shape)
                or any(type(stride) is not int for stride in value.strides)
                or len(value.shape) != len(value.strides)
                or type(value.c_contiguous) is not bool
                or type(value.f_contiguous) is not bool
                or type(value.object_content) is not bool
                or value.object_content is not value.dtype.hasobject
            ):
                raise TypeError("invalid frozen array fields")
            dtype_token = _twin_frozen_token_inner(value.dtype, depth + 1, active)
            count = _twin_shape_product(value.shape)
            if value.object_content:
                if not _twin_exact_tuple(value.content) or len(value.content) != count:
                    raise TypeError("invalid frozen object array content")
                content_token: object = tuple(
                    _twin_frozen_token_inner(item, depth + 1, active)
                    for item in value.content
                )
            else:
                if type(value.content) is not bytes or len(value.content) != count * value.dtype.itemsize:
                    raise TypeError("invalid frozen array byte content")
                content_token = value.content
            return (
                "array",
                dtype_token,
                value.shape,
                value.strides,
                value.c_contiguous,
                value.f_contiguous,
                content_token,
                value.object_content,
            )
        if (
            type(value.kind) is not str
            or value.kind not in ("bytearray", "memoryview")
            or type(value.format) is not str
            or type(value.itemsize) is not int
            or value.itemsize <= 0
            or not _twin_exact_tuple(value.shape)
            or not _twin_exact_tuple(value.strides)
            or any(type(size) is not int or size < 0 for size in value.shape)
            or any(type(stride) is not int for stride in value.strides)
            or (value.strides and len(value.strides) != len(value.shape))
            or type(value.readonly) is not bool
            or type(value.content) is not bytes
            or len(value.content) != _twin_shape_product(value.shape) * value.itemsize
        ):
            raise TypeError("invalid frozen buffer fields")
        if value.kind == "bytearray" and (
            value.format != "B"
            or value.itemsize != 1
            or value.shape != (len(value.content),)
            or value.strides != (1,)
            or value.readonly is not False
        ):
            raise TypeError("invalid frozen bytearray")
        return (
            "buffer",
            value.kind,
            value.format,
            value.itemsize,
            value.shape,
            value.strides,
            value.readonly,
            value.content,
        )
    finally:
        active.remove(value_id)


def _twin_float_token(value: float) -> bytes:
    return struct.pack(">d", value)


def _twin_plan_fault(reason: str) -> None:
    raise _TwinMutationFault(reason)


def _twin_edge_adjacency(
    edge_pairs: set[tuple[int, int]],
) -> tuple[dict[int, set[int]], dict[int, set[int]]]:
    outgoing_targets: dict[int, set[int]] = {}
    incoming_sources: dict[int, set[int]] = {}
    for source_id, target_id in edge_pairs:
        outgoing_targets.setdefault(source_id, set()).add(target_id)
        incoming_sources.setdefault(target_id, set()).add(source_id)
    return outgoing_targets, incoming_sources


def _validate_twin_plan_for_mutation(
    plan: object,
) -> tuple[
    TwinPlan,
    dict[str, int],
    dict[int, TwinSnapshotNode],
    list[tuple[TwinSnapshotEdge, tuple[object, ...]]],
    tuple[tuple[object, ...], ...],
]:
    if type(plan) is not TwinPlan:
        _twin_plan_fault("invalid_plan_type")
    try:
        validation_reason = plan.validation_reason
    except Exception:
        _twin_plan_fault("plan_acceptance")
    if validation_reason is not None:
        _twin_plan_fault("plan_validation_failed")
    try:
        plan_nodes = plan.nodes
        plan_edges = plan.edges
        plan_candidates = plan.candidates
        plan_accepted = plan.accepted_candidates
        plan_decisions = plan.decisions
        plan_debug_records = plan.debug_records
        plan_counters = plan.counters
    except Exception:
        _twin_plan_fault("plan_acceptance")
    tuple_fields = (
        plan_nodes,
        plan_edges,
        plan_candidates,
        plan_accepted,
        plan_decisions,
        plan_debug_records,
    )
    if any(type(value) is not tuple for value in tuple_fields) or type(plan_counters) is not TwinFrozenMapping:
        _twin_plan_fault("plan_acceptance")

    try:
        items = plan_counters.items_snapshot
    except Exception:
        _twin_plan_fault("plan_counter_schema")
    if type(items) is not tuple or len(items) != len(_TWIN_COUNTER_KEYS):
        _twin_plan_fault("plan_counter_schema")
    counter_values: list[int] = []
    for index, entry in enumerate(items):
        if (
            type(entry) is not tuple
            or len(entry) != 2
            or type(entry[0]) is not str
            or entry[0] != _TWIN_COUNTER_KEYS[index]
        ):
            _twin_plan_fault("plan_counter_schema")
        if type(entry[1]) is not int or entry[1] < 0:
            _twin_plan_fault("plan_counter_value")
        counter_values.append(entry[1])
    counters = dict(zip(_TWIN_COUNTER_KEYS, counter_values, strict=True))
    eligibility_keys = (
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
    accepted_count = counters["steal_twin_accepted"]
    conservation = (
        counters["steal_twin_enumerated"]
        == sum(counters[f"steal_twin_rejected_{key}"] for key in eligibility_keys)
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
        and counters["steal_twin_debug_records_written"] == 0
        and counters["steal_twin_debug_records_dropped"] == 0
        and len(plan_candidates) == counters["steal_twin_eligible"]
        and len(plan_accepted) == accepted_count
        and accepted_count <= counters["steal_twin_examined_frames"]
        and accepted_count <= 2
    )
    if not conservation:
        _twin_plan_fault("plan_conservation")

    by_id: dict[int, TwinSnapshotNode] = {}
    previous_id: int | None = None
    for node in plan_nodes:
        if (
            type(node) is not TwinSnapshotNode
            or type(node.node_id) is not int
            or type(node.t) is not int
            or any(type(value) is not float or not math.isfinite(value) for value in (node.z, node.y, node.x))
            or type(node.gap_synthetic) is not bool
            or (previous_id is not None and node.node_id <= previous_id)
        ):
            _twin_plan_fault("plan_candidate")
        previous_id = node.node_id
        by_id[node.node_id] = node

    edge_pairs: set[tuple[int, int]] = set()
    positions: set[int] = set()
    indegree: Counter[int] = Counter()
    outdegree: Counter[int] = Counter()
    edge_metadata_tokens: dict[tuple[int, int], tuple[object, ...]] = {}
    previous_edge_key: tuple[int, int, int] | None = None
    for edge in plan_edges:
        if (
            type(edge) is not TwinSnapshotEdge
            or type(edge.source_id) is not int
            or type(edge.target_id) is not int
            or type(edge.input_position) is not int
            or type(edge.metadata) is not TwinFrozenMapping
        ):
            _twin_plan_fault("plan_candidate")
        try:
            metadata_token = _twin_frozen_token(edge.metadata)
        except Exception:
            _twin_plan_fault("plan_candidate")
        metadata_sources = [
            item
            for key, item in edge.metadata.items_snapshot
            if type(key) is str and key == "source_id"
        ]
        metadata_targets = [
            item
            for key, item in edge.metadata.items_snapshot
            if type(key) is str and key == "target_id"
        ]
        edge_key = (edge.source_id, edge.target_id, edge.input_position)
        pair = edge_key[:2]
        if (
            (previous_edge_key is not None and edge_key <= previous_edge_key)
            or pair in edge_pairs
            or edge.input_position in positions
            or edge.source_id not in by_id
            or edge.target_id not in by_id
            or by_id[edge.target_id].t != by_id[edge.source_id].t + 1
            or len(metadata_sources) != 1
            or type(metadata_sources[0]) is not int
            or metadata_sources[0] != edge.source_id
            or len(metadata_targets) != 1
            or type(metadata_targets[0]) is not int
            or metadata_targets[0] != edge.target_id
        ):
            _twin_plan_fault("plan_candidate")
        previous_edge_key = edge_key
        edge_pairs.add(pair)
        positions.add(edge.input_position)
        edge_metadata_tokens[pair] = metadata_token
        outdegree[edge.source_id] += 1
        indegree[edge.target_id] += 1
    if positions != set(range(len(plan_edges))) or any(v > 1 for v in indegree.values()) or any(v > 2 for v in outdegree.values()):
        _twin_plan_fault("plan_candidate")
    outgoing_targets, incoming_sources = _twin_edge_adjacency(edge_pairs)

    if len(plan_decisions) != len(plan_candidates):
        _twin_plan_fault("plan_acceptance")
    accepted_from_decisions: list[TwinCandidate] = []
    rejected_counts = Counter()
    for candidate, decision in zip(plan_candidates, plan_decisions, strict=True):
        if type(candidate) is not TwinCandidate or type(decision) is not TwinResolutionDecision or decision.candidate is not candidate:
            _twin_plan_fault("plan_acceptance")
        if decision.accepted is True and decision.reason is None:
            accepted_from_decisions.append(candidate)
        elif decision.accepted is False and type(decision.reason) is str and decision.reason in ("conflict", "frame_cap", "video_cap"):
            rejected_counts[decision.reason] += 1
        else:
            _twin_plan_fault("plan_acceptance")
    if (
        len(accepted_from_decisions) != accepted_count
        or len(accepted_from_decisions) != len(plan_accepted)
        or any(
            left is not right
            for left, right in zip(accepted_from_decisions, plan_accepted, strict=True)
        )
        or any(
            rejected_counts[key] != counters[f"steal_twin_rejected_{key}"]
            for key in ("conflict", "frame_cap", "video_cap")
        )
    ):
        _twin_plan_fault("plan_acceptance")

    candidate_metadata_tokens = tuple(
        _validate_twin_candidate_structure(candidate) for candidate in plan_candidates
    )
    accepted_roles: set[int] = set()
    accepted_removed: set[tuple[int, int]] = set()
    accepted_planned: set[tuple[int, int]] = set()
    previous_sort_key: tuple[float, float, float, int, int, int, int, int, int] | None = None
    accepted_frames: set[int] = set()
    accepted_metadata_tokens: list[tuple[object, ...]] = []
    for candidate, candidate_metadata_token, decision in zip(
        plan_candidates, candidate_metadata_tokens, plan_decisions, strict=True
    ):
        try:
            roles = (candidate.p, candidate.q, candidate.a, candidate.b, candidate.a2, candidate.b2)
            if len(set(roles)) != 6 or any(role not in by_id for role in roles):
                _twin_plan_fault("plan_candidate")
            if (
                by_id[candidate.p].t != candidate.frame
                or by_id[candidate.q].t != candidate.frame
                or by_id[candidate.a].t != candidate.frame + 1
                or by_id[candidate.b].t != candidate.frame + 1
                or by_id[candidate.a2].t != candidate.frame + 2
                or by_id[candidate.b2].t != candidate.frame + 2
                or any(by_id[role].gap_synthetic for role in roles)
            ):
                _twin_plan_fault("plan_candidate")
            distances = (
                _twin_distance(by_id[candidate.p], by_id[candidate.q]),
                _twin_distance(by_id[candidate.p], by_id[candidate.a]),
                _twin_distance(by_id[candidate.p], by_id[candidate.b]),
                _twin_distance(by_id[candidate.a], by_id[candidate.b]),
                _twin_distance(by_id[candidate.a2], by_id[candidate.b2]),
            )
            stored = (candidate.d_pq, candidate.d_pa, candidate.d_pb, candidate.d_ab, candidate.d_a2b2)
            if any(not math.isfinite(value) for value in distances) or any(
                _twin_float_token(left) != _twin_float_token(right)
                for left, right in zip(distances, stored, strict=True)
            ):
                _twin_plan_fault("plan_candidate")
            growth = distances[4] - distances[3]
            formula = (
                candidate.d_pb + 0.15 * candidate.d_ab,
                -candidate.divergence_growth,
                candidate.d_pq,
                *roles,
            )
            if (
                _twin_float_token(growth) != _twin_float_token(candidate.divergence_growth)
                or any(
                    _twin_float_token(formula[i]) != _twin_float_token(candidate.sort_key[i])
                    for i in range(3)
                )
                or formula[3:] != candidate.sort_key[3:]
                or _twin_float_token(distances[2]) != _twin_float_token(candidate.planned_edge.distance_um)
            ):
                _twin_plan_fault("plan_candidate")
            removed_token = edge_metadata_tokens.get((candidate.q, candidate.b))
            if removed_token is None or removed_token != candidate_metadata_token:
                _twin_plan_fault("plan_candidate")
            required = ((candidate.p, candidate.a), (candidate.q, candidate.b), (candidate.a, candidate.a2), (candidate.b, candidate.b2))
            if any(pair not in edge_pairs for pair in required) or (candidate.p, candidate.b) in edge_pairs:
                _twin_plan_fault("plan_candidate")
            if (
                outgoing_targets.get(candidate.p, set()) != {candidate.a}
                or outgoing_targets.get(candidate.q, set()) != {candidate.b}
                or outgoing_targets.get(candidate.a, set()) != {candidate.a2}
                or outgoing_targets.get(candidate.b, set()) != {candidate.b2}
                or incoming_sources.get(candidate.q, set())
            ):
                _twin_plan_fault("plan_candidate")
            if previous_sort_key is not None and candidate.sort_key < previous_sort_key:
                _twin_plan_fault("plan_acceptance")
            previous_sort_key = candidate.sort_key
            if decision.accepted is True:
                role_set = set(roles)
                removed_pair = (candidate.q, candidate.b)
                planned_pair = (candidate.p, candidate.b)
                if role_set & accepted_roles or removed_pair in accepted_removed or planned_pair in accepted_planned:
                    _twin_plan_fault("plan_candidate")
                accepted_roles.update(role_set)
                accepted_removed.add(removed_pair)
                accepted_planned.add(planned_pair)
                accepted_frames.add(candidate.frame)
                accepted_metadata_tokens.append(candidate_metadata_token)
        except _TwinMutationFault:
            raise
        except Exception:
            _twin_plan_fault("plan_candidate")
    if len(accepted_frames) != accepted_count:
        _twin_plan_fault("plan_conservation")

    if len(plan_debug_records) != len(plan_candidates):
        _twin_plan_fault("plan_acceptance")
    dataset_value: str | None = None
    for index, (record, decision, candidate) in enumerate(
        zip(plan_debug_records, plan_decisions, plan_candidates, strict=True)
    ):
        try:
            if type(record) is not TwinDebugRecord or (record.dataset is not None and type(record.dataset) is not str):
                _twin_plan_fault("plan_acceptance")
            if index == 0:
                dataset_value = record.dataset
            elif record.dataset != dataset_value:
                _twin_plan_fault("plan_acceptance")
            expected_decision = "accepted" if decision.accepted else "rejected"
            if (
                type(record.decision) is not str
                or record.decision != expected_decision
                or (record.reason is not None and type(record.reason) is not str)
                or record.reason != decision.reason
            ):
                _twin_plan_fault("plan_acceptance")
            projected = (
                (record.p, candidate.p), (record.q, candidate.q), (record.a, candidate.a),
                (record.b, candidate.b), (record.a2, candidate.a2), (record.b2, candidate.b2),
                (record.sort_key, candidate.sort_key), (record.d_pq, candidate.d_pq),
                (record.d_pa, candidate.d_pa), (record.d_pb, candidate.d_pb),
                (record.d_ab, candidate.d_ab), (record.d_a2b2, candidate.d_a2b2),
                (record.divergence_growth, candidate.divergence_growth),
                (record.raw_deepcenter_score, candidate.raw_deepcenter_score),
                (record.deepcenter_decision, candidate.deepcenter_decision),
                (record.removed_edge, candidate.removed_edge), (record.planned_edge, candidate.planned_edge),
            )
            if any(left is not right for left, right in projected):
                _twin_plan_fault("plan_acceptance")
            if type(record.deepcenter_threshold) is not float or _twin_float_token(record.deepcenter_threshold) != _twin_float_token(0.12):
                _twin_plan_fault("plan_acceptance")
        except _TwinMutationFault:
            raise
        except Exception:
            _twin_plan_fault("plan_acceptance")
    ordered_edges = sorted(
        (
            (edge, edge_metadata_tokens[(edge.source_id, edge.target_id)])
            for edge in plan_edges
        ),
        key=lambda item: item[0].input_position,
    )
    return plan, counters, by_id, ordered_edges, tuple(accepted_metadata_tokens)


def _validate_twin_candidate_structure(candidate: TwinCandidate) -> tuple[object, ...]:
    roles = (candidate.frame, candidate.p, candidate.q, candidate.a, candidate.b, candidate.a2, candidate.b2)
    floats = (
        candidate.d_pq, candidate.d_pa, candidate.d_pb, candidate.d_ab,
        candidate.d_a2b2, candidate.divergence_growth, candidate.raw_deepcenter_score,
    )
    if any(type(value) is not int for value in roles) or any(type(value) is not float or not math.isfinite(value) for value in floats):
        _twin_plan_fault("plan_candidate")
    if (
        type(candidate.deepcenter_decision) is not TwinDeepCenterDecision
        or candidate.deepcenter_decision.accepted is not True
        or candidate.deepcenter_decision.reason is not None
        or type(candidate.deepcenter_decision.raw_score) is not float
        or not math.isfinite(candidate.deepcenter_decision.raw_score)
        or _twin_float_token(candidate.deepcenter_decision.raw_score) != _twin_float_token(candidate.raw_deepcenter_score)
        or type(candidate.sort_key) is not tuple
        or len(candidate.sort_key) != 9
        or any(type(value) is not float or not math.isfinite(value) for value in candidate.sort_key[:3])
        or any(type(value) is not int for value in candidate.sort_key[3:])
        or type(candidate.removed_edge) is not TwinEdgeRecord
        or type(candidate.removed_edge.source_id) is not int
        or type(candidate.removed_edge.target_id) is not int
        or type(candidate.removed_edge.metadata) is not TwinFrozenMapping
        or (candidate.removed_edge.source_id, candidate.removed_edge.target_id) != (candidate.q, candidate.b)
        or type(candidate.planned_edge) is not TwinPlannedEdge
        or type(candidate.planned_edge.source_id) is not int
        or type(candidate.planned_edge.target_id) is not int
        or type(candidate.planned_edge.distance_um) is not float
        or not math.isfinite(candidate.planned_edge.distance_um)
        or candidate.planned_edge.edge_prob is not None
        or (candidate.planned_edge.source_id, candidate.planned_edge.target_id) != (candidate.p, candidate.b)
    ):
        _twin_plan_fault("plan_candidate")
    try:
        return _twin_frozen_token(candidate.removed_edge.metadata)
    except Exception:
        _twin_plan_fault("plan_candidate")


@dataclass(frozen=True)
class _TwinCurrentEdge:
    source_id: int
    target_id: int
    metadata: TwinFrozenMapping
    token: tuple[object, ...]


def _normalize_twin_current_nodes(
    nodes_by_id: object,
    plan_nodes: dict[int, TwinSnapshotNode],
) -> dict[int, TwinSnapshotNode]:
    if type(nodes_by_id) is not dict:
        _twin_plan_fault("node_mapping")
    locations: list[tuple[int, dict[str, object], dict[str, str]]] = []
    try:
        for outer_key, row in nodes_by_id.items():
            if type(outer_key) is not int or type(row) is not dict:
                _twin_plan_fault("node_mapping")
            found: dict[str, str] = {}
            for key in row:
                if type(key) is str and key in ("node_id", "t", "z", "y", "x", "gap_synthetic"):
                    found[key] = key
            if any(name not in found for name in ("node_id", "t", "z", "y", "x")):
                _twin_plan_fault("node_mapping")
            locations.append((outer_key, row, found))
        if {item[0] for item in locations} != set(plan_nodes):
            _twin_plan_fault("node_mapping")
        normalized: dict[int, TwinSnapshotNode] = {}
        for outer_key, row, found in locations:
            node_id_value = row[found["node_id"]]
            time_value = row[found["t"]]
            coordinate_values = (row[found["z"]], row[found["y"]], row[found["x"]])
            if (
                type(node_id_value) is not int
                or node_id_value != outer_key
                or not _is_twin_integer(time_value)
                or any(not _is_twin_finite_real(value) for value in coordinate_values)
            ):
                _twin_plan_fault("node_mapping")
            gap = False
            if "gap_synthetic" in found:
                gap = bool(row[found["gap_synthetic"]] == 1)
            current = TwinSnapshotNode(
                outer_key,
                int(time_value),
                float(coordinate_values[0]),
                float(coordinate_values[1]),
                float(coordinate_values[2]),
                gap,
            )
            expected = plan_nodes[outer_key]
            if (
                current.t != expected.t
                or current.gap_synthetic is not expected.gap_synthetic
                or any(
                    _twin_float_token(left) != _twin_float_token(right)
                    for left, right in zip(
                        (current.z, current.y, current.x),
                        (expected.z, expected.y, expected.x),
                        strict=True,
                    )
                )
            ):
                _twin_plan_fault("node_mapping")
            normalized[outer_key] = current
        return normalized
    except _TwinMutationFault:
        raise
    except Exception:
        _twin_plan_fault("node_mapping")


def _normalize_twin_current_edges(
    current_edges: object,
    nodes: dict[int, TwinSnapshotNode],
    *,
    failure_reason: str = "current_graph_invalid",
) -> list[_TwinCurrentEdge]:
    if type(current_edges) is not list:
        _twin_plan_fault(failure_reason)
    result: list[_TwinCurrentEdge] = []
    pairs: set[tuple[int, int]] = set()
    try:
        for row in current_edges:
            if type(row) is not dict:
                _twin_plan_fault(failure_reason)
            source_key: object | None = None
            target_key: object | None = None
            source_value: object = None
            target_value: object = None
            for key, value in row.items():
                if isinstance(key, str):
                    if key == "source_id":
                        source_key = key
                        source_value = value
                    elif key == "target_id":
                        target_key = key
                        target_value = value
            if source_key is None or target_key is None:
                _twin_plan_fault(failure_reason)
            if not _is_twin_integer(source_value) or not _is_twin_integer(target_value):
                _twin_plan_fault(failure_reason)
            source_id = int(source_value)
            target_id = int(target_value)
            pair = (source_id, target_id)
            if (
                pair in pairs
                or source_id not in nodes
                or target_id not in nodes
                or nodes[target_id].t != nodes[source_id].t + 1
            ):
                _twin_plan_fault(failure_reason)
            metadata = _freeze_twin_edge_row(
                row,
                source_id,
                target_id,
                _source_key=source_key,
                _target_key=target_key,
            )
            token = _twin_frozen_token(metadata)
            result.append(_TwinCurrentEdge(source_id, target_id, metadata, token))
            pairs.add(pair)
        return result
    except _TwinMutationFault:
        raise
    except Exception:
        _twin_plan_fault(failure_reason)


def _twin_edge_semantic_token(
    source_id: int,
    target_id: int,
    metadata: TwinFrozenMapping,
) -> tuple[object, ...]:
    return ("edge", source_id, target_id, _twin_frozen_token(metadata))


def _twin_replacement_row(
    candidate: TwinCandidate,
    nodes: dict[int, TwinSnapshotNode],
) -> dict[str, object]:
    distance = _twin_distance(nodes[candidate.p], nodes[candidate.b])
    return {
        "source_id": candidate.p,
        "target_id": candidate.b,
        "distance_um": distance,
        "edge_prob": None,
    }


def _twin_expected_replacement_token(
    candidate: TwinCandidate,
    nodes: dict[int, TwinSnapshotNode],
) -> tuple[object, ...]:
    distance = _twin_distance(nodes[candidate.p], nodes[candidate.b])
    metadata_token = (
        "mapping",
        (
            (("str", "source_id"), ("int", candidate.p)),
            (("str", "target_id"), ("int", candidate.b)),
            (("str", "distance_um"), ("float", _twin_float_token(distance))),
            (("str", "edge_prob"), ("none",)),
        ),
    )
    return ("edge", candidate.p, candidate.b, metadata_token)


def _twin_degrees(edges: Sequence[_TwinCurrentEdge]) -> tuple[Counter[int], Counter[int]]:
    indegree: Counter[int] = Counter()
    outdegree: Counter[int] = Counter()
    for edge in edges:
        outdegree[edge.source_id] += 1
        indegree[edge.target_id] += 1
    return indegree, outdegree


def _twin_summary(
    status: Literal["applied", "already_applied", "no_changes"],
    node_count: int,
    edge_count: int,
    accepted_count: int,
) -> TwinMutationSummary:
    applied = status == "applied"
    return TwinMutationSummary(
        status,
        accepted_count,
        node_count,
        node_count,
        edge_count,
        edge_count,
        accepted_count if applied else 0,
        accepted_count if applied else 0,
        2 * accepted_count if applied else 0,
        accepted_count if applied else 0,
    )


def _snapshot_twin_node_mapping_shallow(
    nodes_by_id: object,
) -> tuple[
    dict[int, dict[str, object]],
    tuple[
        tuple[
            object,
            object,
            tuple[tuple[object, object], ...] | None,
        ],
        ...,
    ],
] | None:
    """Capture only identities needed by the section-10 write-free proof."""
    if type(nodes_by_id) is not dict:
        return None
    entries: list[
        tuple[object, object, tuple[tuple[object, object], ...] | None]
    ] = []
    for key, row in nodes_by_id.items():
        bindings = tuple(row.items()) if type(row) is dict else None
        entries.append((key, row, bindings))
    return nodes_by_id, tuple(entries)


def _twin_node_mapping_matches_shallow_snapshot(
    nodes_by_id: object,
    snapshot: tuple[
        dict[int, dict[str, object]],
        tuple[
            tuple[
                object,
                object,
                tuple[tuple[object, object], ...] | None,
            ],
            ...,
        ],
    ]
    | None,
) -> bool:
    if snapshot is None or type(nodes_by_id) is not dict or nodes_by_id is not snapshot[0]:
        return False
    current_entries = tuple(nodes_by_id.items())
    expected_entries = snapshot[1]
    if len(current_entries) != len(expected_entries):
        return False
    for (expected_key, expected_row, expected_bindings), (key, row) in zip(
        expected_entries, current_entries, strict=True
    ):
        if key is not expected_key or row is not expected_row or type(row) is not dict:
            return False
        if expected_bindings is None:
            return False
        current_bindings = tuple(row.items())
        if len(current_bindings) != len(expected_bindings):
            return False
        if any(
            key is not expected_key or value is not expected_value
            for (expected_key, expected_value), (key, value) in zip(
                expected_bindings, current_bindings, strict=True
            )
        ):
            return False
    return True


def apply_twin_only_v1_plan(
    nodes_by_id: dict[int, dict[str, object]],
    current_edges: list[dict[str, object]],
    plan: TwinPlan,
) -> tuple[list[dict[str, object]], TwinMutationSummary]:
    """Atomically apply a validated R1 twin plan to its exact source graph."""
    fallback_reason = "plan_candidate"
    try:
        node_mapping_snapshot = _snapshot_twin_node_mapping_shallow(nodes_by_id)
        (
            valid_plan,
            _counters,
            plan_nodes,
            ordered_plan_edges,
            accepted_metadata_tokens,
        ) = _validate_twin_plan_for_mutation(plan)
        fallback_reason = "node_mapping"
        _normalize_twin_current_nodes(nodes_by_id, plan_nodes)
        fallback_reason = "current_graph_invalid"
        current = _normalize_twin_current_edges(current_edges, plan_nodes)
        accepted = valid_plan.accepted_candidates
        accepted_count = len(accepted)

        pre_tokens = tuple(
            ("edge", edge.source_id, edge.target_id, metadata_token)
            for edge, metadata_token in ordered_plan_edges
        )
        current_tokens = tuple(
            ("edge", edge.source_id, edge.target_id, edge.token)
            for edge in current
        )
        remove_tokens = tuple(
            ("edge", candidate.q, candidate.b, metadata_token)
            for candidate, metadata_token in zip(
                accepted, accepted_metadata_tokens, strict=True
            )
        )
        replacement_tokens = tuple(
            _twin_expected_replacement_token(candidate, plan_nodes)
            for candidate in accepted
        )

        def state_for_mask(mask: int) -> tuple[tuple[object, ...], ...]:
            removed = {
                remove_tokens[index]
                for index in range(accepted_count)
                if mask & (1 << (2 * index))
            }
            state = [token for token in pre_tokens if token not in removed]
            state.extend(
                replacement_tokens[index]
                for index in range(accepted_count)
                if mask & (1 << (2 * index + 1))
            )
            return tuple(state)

        full_mask = (1 << (2 * accepted_count)) - 1
        post_tokens = state_for_mask(full_mask)
        exact_pre = current_tokens == pre_tokens
        exact_post = accepted_count > 0 and current_tokens == post_tokens
        if accepted_count == 0:
            if exact_pre:
                return current_edges, _twin_summary("no_changes", len(nodes_by_id), len(current_edges), 0)
            indegree, outdegree = _twin_degrees(current)
            if any(value > 1 for value in indegree.values()) or any(value > 2 for value in outdegree.values()):
                _twin_plan_fault("current_graph_invalid")
            _twin_plan_fault("current_graph_mismatch")
        if exact_post:
            return current_edges, _twin_summary(
                "already_applied", len(nodes_by_id), len(current_edges), accepted_count
            )
        if not exact_pre:
            if any(current_tokens == state_for_mask(mask) for mask in range(1, full_mask)):
                _twin_plan_fault("partial_application")
            indegree, outdegree = _twin_degrees(current)
            if any(value > 1 for value in indegree.values()) or any(value > 2 for value in outdegree.values()):
                _twin_plan_fault("current_graph_invalid")
            _twin_plan_fault("current_graph_mismatch")

        fallback_reason = "post_invariant"
        replacement_rows = tuple(
            _twin_replacement_row(candidate, plan_nodes) for candidate in accepted
        )
        for candidate, row in zip(accepted, replacement_rows, strict=True):
            expected_distance = _twin_distance(
                plan_nodes[candidate.p], plan_nodes[candidate.b]
            )
            if (
                type(row) is not dict
                or tuple(row) != (
                    "source_id",
                    "target_id",
                    "distance_um",
                    "edge_prob",
                )
                or any(type(key) is not str for key in row)
                or type(row["source_id"]) is not int
                or row["source_id"] != candidate.p
                or type(row["target_id"]) is not int
                or row["target_id"] != candidate.b
                or type(row["distance_um"]) is not float
                or _twin_float_token(row["distance_um"])
                != _twin_float_token(expected_distance)
                or row["edge_prob"] is not None
            ):
                _twin_plan_fault("post_invariant")
        replacement_current = _normalize_twin_current_edges(
            list(replacement_rows), plan_nodes, failure_reason="post_invariant"
        )

        remove_token_set = set(remove_tokens)
        survivors = [
            (row, edge)
            for row, edge, token in zip(current_edges, current, current_tokens, strict=True)
            if token not in remove_token_set
        ]
        result = [row for row, _edge in survivors]
        result.extend(replacement_rows)

        # Prove the complete temporary graph before exposing it to the caller.
        temporary = [edge for _row, edge in survivors]
        temporary.extend(replacement_current)
        temporary_tokens = tuple(("edge", edge.source_id, edge.target_id, edge.token) for edge in temporary)
        before_pairs = {(edge.source_id, edge.target_id) for edge in current}
        after_pairs = {(edge.source_id, edge.target_id) for edge in temporary}
        indegree, outdegree = _twin_degrees(temporary)
        surviving_count = len(current_edges) - accepted_count
        if (
            temporary_tokens != post_tokens
            or len(result) != len(current_edges)
            or len(before_pairs) != len(current_edges)
            or len(after_pairs) != len(result)
            or len(before_pairs ^ after_pairs) != 2 * accepted_count
            or any(result[index] is not survivors[index][0] for index in range(surviving_count))
            or any(value > 1 for value in indegree.values())
            or any(value > 2 for value in outdegree.values())
            or any(indegree[candidate.q] + outdegree[candidate.q] != 0 for candidate in accepted)
        ):
            _twin_plan_fault("post_invariant")
        for index, row in enumerate(replacement_rows):
            result_row = result[surviving_count + index]
            if result_row is not row or tuple(result_row) != (
                "source_id", "target_id", "distance_um", "edge_prob"
            ):
                _twin_plan_fault("post_invariant")
        if not _twin_node_mapping_matches_shallow_snapshot(
            nodes_by_id, node_mapping_snapshot
        ):
            _twin_plan_fault("post_invariant")
        return result, _twin_summary(
            "applied", len(nodes_by_id), len(current_edges), accepted_count
        )
    except _TwinMutationFault as exc:
        raise TwinMutationError(exc.reason) from exc
    except TwinMutationError:
        raise
    except Exception as exc:
        raise TwinMutationError(fallback_reason) from exc


def score_twin_deepcenter(
    cfg: PostprocConfig,
    dataset: str | None,
    t: int,
    point: tuple[float, float, float],
    detector_bundle: dict[str, object] | None,
    frame_cache: dict[int, np.ndarray],
    heatmap_cache: dict[tuple[str, int], np.ndarray],
) -> TwinDeepCenterDecision:
    """Strict, fail-closed DeepCenter decision for the frozen twin-only planner."""
    required_bundle_keys = {"model", "cfg", "device", "torch", "path", "checkpoint_epoch"}
    if not cfg.USE_DEEPCENTER_VETO or not cfg.STEAL_TWIN_DEEPCENTER_VETO or detector_bundle is None:
        return TwinDeepCenterDecision(False, None, "deepcenter_bundle")
    if not required_bundle_keys.issubset(detector_bundle):
        return TwinDeepCenterDecision(False, None, "deepcenter_bundle")
    checkpoint_epoch = detector_bundle["checkpoint_epoch"]
    if (
        isinstance(checkpoint_epoch, bool)
        or not isinstance(checkpoint_epoch, int)
        or checkpoint_epoch != cfg.DEEPCENTER_EXPECTED_EPOCH
    ):
        return TwinDeepCenterDecision(False, None, "deepcenter_bundle")
    model_cfg = detector_bundle["cfg"]
    pool_factor = getattr(model_cfg, "pool_factor", None)
    if isinstance(pool_factor, bool) or not isinstance(pool_factor, int) or pool_factor < 1:
        return TwinDeepCenterDecision(False, None, "deepcenter_bundle")
    if dataset is None or not dataset.strip():
        return TwinDeepCenterDecision(False, None, "deepcenter_dataset")

    try:
        frame = read_test_frame(cfg.TEST_DIR, dataset, int(t), frame_cache)
    except Exception:
        return TwinDeepCenterDecision(False, None, "deepcenter_frame")
    if frame is None or np.asarray(frame).size == 0:
        return TwinDeepCenterDecision(False, None, "deepcenter_frame")
    frame_array = np.asarray(frame)
    if not np.all(np.isfinite(frame_array)):
        return TwinDeepCenterDecision(False, None, "deepcenter_nonfinite")
    if frame_array.ndim != 3:
        return TwinDeepCenterDecision(False, None, "deepcenter_frame")

    try:
        heatmap = deepcenter_heatmap_for_frame(
            cfg,
            dataset,
            int(t),
            detector_bundle,
            frame_cache,
            heatmap_cache,
        )
    except Exception:
        return TwinDeepCenterDecision(False, None, "deepcenter_heatmap")
    if heatmap is None or np.asarray(heatmap).size == 0:
        return TwinDeepCenterDecision(False, None, "deepcenter_heatmap")
    heatmap_array = np.asarray(heatmap)
    if not np.all(np.isfinite(heatmap_array)):
        return TwinDeepCenterDecision(False, None, "deepcenter_nonfinite")
    if heatmap_array.ndim != 3:
        return TwinDeepCenterDecision(False, None, "deepcenter_heatmap")

    point_array = np.asarray(point, dtype=np.float64)
    if point_array.shape != (3,) or not np.all(np.isfinite(point_array)):
        return TwinDeepCenterDecision(False, None, "deepcenter_heatmap")
    z = int(round(float(point_array[0])))
    y = int(round(float(point_array[1]) / pool_factor))
    x = int(round(float(point_array[2]) / pool_factor))
    if not (0 <= z < heatmap_array.shape[0] and 0 <= y < heatmap_array.shape[1] and 0 <= x < heatmap_array.shape[2]):
        return TwinDeepCenterDecision(False, None, "deepcenter_heatmap")
    z0, z1 = max(0, z - cfg.DEEPCENTER_SCORE_WIN_Z), min(
        heatmap_array.shape[0], z + cfg.DEEPCENTER_SCORE_WIN_Z + 1
    )
    y0, y1 = max(0, y - cfg.DEEPCENTER_SCORE_WIN_YX), min(
        heatmap_array.shape[1], y + cfg.DEEPCENTER_SCORE_WIN_YX + 1
    )
    x0, x1 = max(0, x - cfg.DEEPCENTER_SCORE_WIN_YX), min(
        heatmap_array.shape[2], x + cfg.DEEPCENTER_SCORE_WIN_YX + 1
    )
    patch = heatmap_array[z0:z1, y0:y1, x0:x1]
    if patch.size == 0:
        return TwinDeepCenterDecision(False, None, "deepcenter_heatmap")
    if not np.all(np.isfinite(patch)):
        return TwinDeepCenterDecision(False, None, "deepcenter_nonfinite")
    raw_value = np.max(patch)
    if np.ndim(raw_value) != 0:
        return TwinDeepCenterDecision(False, None, "deepcenter_heatmap")
    raw_score = float(raw_value)
    if not np.isfinite(raw_score):
        return TwinDeepCenterDecision(False, None, "deepcenter_nonfinite")
    if raw_score < 0.12:
        return TwinDeepCenterDecision(False, raw_score, "deepcenter_threshold")
    return TwinDeepCenterDecision(True, raw_score, None)


def add_safe_divisions_postlink(
    cfg: PostprocConfig,
    nodes_by_id: dict[int, dict[str, object]],
    edges: list[dict[str, object]],
    stats: dict[str, int],
    dataset: str | None = None,
    deepcenter_bundle: dict[str, object] | None = None,
    frame_cache: dict[int, np.ndarray] | None = None,
    deepcenter_cache: dict[tuple[str, int], np.ndarray] | None = None,
) -> list[dict[str, object]]:
    if not cfg.OUTPUT_SAFE_DIVISIONS or not edges or not nodes_by_id:
        return edges
    frame_cache = frame_cache if frame_cache is not None else {}
    deepcenter_cache = deepcenter_cache if deepcenter_cache is not None else {}

    out_by_source: dict[int, list[dict[str, object]]] = {}
    incoming: set[int] = set()
    for edge in edges:
        out_by_source.setdefault(int(edge["source_id"]), []).append(edge)
        incoming.add(int(edge["target_id"]))

    ids_by_t: dict[int, list[int]] = {}
    for node_id, node in nodes_by_id.items():
        ids_by_t.setdefault(int(node["t"]), []).append(node_id)

    existing_edges = {(int(edge["source_id"]), int(edge["target_id"])) for edge in edges}
    global_cap = max(1, int(round(max(1, len(edges)) * cfg.SAFE_DIV_GLOBAL_FRAC_CAP)))
    added: list[dict[str, object]] = []
    used_targets: set[int] = set()

    for t in sorted(ids_by_t):
        child_frame_ids = ids_by_t.get(t + 1, [])
        if not child_frame_ids:
            continue
        source_ids = [node_id for node_id in ids_by_t[t] if len(out_by_source.get(node_id, [])) == 1]
        candidate_ids = [node_id for node_id in child_frame_ids if node_id not in incoming and node_id not in used_targets]
        if not source_ids or not candidate_ids:
            continue

        frame_cap = max(1, int(round(len(source_ids) * cfg.SAFE_DIV_FRAME_FRAC_CAP)))
        if cfg.SAFE_DIV_MODE == "e23":
            proposals = _e23_frame_proposals(
                cfg,
                nodes_by_id,
                out_by_source,
                incoming,
                existing_edges,
                source_ids,
                candidate_ids,
                t,
                stats,
                dataset,
                deepcenter_bundle,
                frame_cache,
                deepcenter_cache,
            )
        else:  # "legacy"; build_config rejects every other value
            proposals = _legacy_frame_proposals(
                cfg,
                nodes_by_id,
                out_by_source,
                existing_edges,
                source_ids,
                candidate_ids,
                t,
                stats,
                dataset,
                deepcenter_bundle,
                frame_cache,
                deepcenter_cache,
            )

        stats["safe_division_candidates"] += len(proposals)
        if not proposals:
            continue
        proposals.sort(key=lambda item: item[0])
        added_this_frame = 0
        for _, source_id, candidate_id, parent_dist, _ in proposals:
            if len(added) >= global_cap:
                stats["safe_division_skipped_cap"] += 1
                break
            if added_this_frame >= frame_cap:
                break
            if candidate_id in used_targets or candidate_id in incoming:
                continue
            added.append({
                "source_id": source_id,
                "target_id": candidate_id,
                "edge_prob": None,
                "distance_um": parent_dist,
                "safe_division": 1,
            })
            used_targets.add(candidate_id)
            added_this_frame += 1

    if added:
        stats["safe_divisions_added"] = len(added)
        return [*edges, *added]
    return edges


def _legacy_frame_proposals(
    cfg: PostprocConfig,
    nodes_by_id: dict[int, dict[str, object]],
    out_by_source: dict[int, list[dict[str, object]]],
    existing_edges: set[tuple[int, int]],
    source_ids: list[int],
    candidate_ids: list[int],
    t: int,
    stats: dict[str, int],
    dataset: str | None,
    deepcenter_bundle: dict[str, object] | None,
    frame_cache: dict[int, np.ndarray],
    deepcenter_cache: dict[tuple[str, int], np.ndarray],
) -> list[tuple[float, int, int, float, float]]:
    """Candidate generation exactly as the pre-E23 port: distance gates only.

    No cKDTree and no structural restrictions; the legacy output is
    output-identical to the Phase-1 behavior.
    """
    proposals: list[tuple[float, int, int, float, float]] = []
    for source_id in source_ids:
        source = nodes_by_id[source_id]
        existing_child_edge = out_by_source[source_id][0]
        existing_child_id = int(existing_child_edge["target_id"])
        existing_child = nodes_by_id.get(existing_child_id)
        if existing_child is None or int(existing_child["t"]) != t + 1:
            continue
        child_dist = edge_distance_um(source, existing_child)
        if child_dist > cfg.SAFE_DIV_EXISTING_CHILD_MAX_UM:
            continue
        for candidate_id in candidate_ids:
            if (source_id, candidate_id) in existing_edges:
                continue
            candidate = nodes_by_id[candidate_id]
            parent_dist = edge_distance_um(source, candidate)
            if parent_dist > cfg.SAFE_DIV_MAX_UM:
                continue
            sister_dist = edge_distance_um(existing_child, candidate)
            if sister_dist > cfg.SAFE_DIV_SISTER_MAX_UM:
                continue
            if cfg.DEEPCENTER_SAFE_DIV_VETO and not deepcenter_accept_repair_point(
                cfg,
                dataset,
                int(candidate["t"]),
                (float(candidate["z"]), float(candidate["y"]), float(candidate["x"])),
                deepcenter_bundle,
                frame_cache,
                deepcenter_cache,
                stats,
                "safe_div",
                cfg.DEEPCENTER_SAFE_DIV_THRESHOLD,
            ):
                continue
            score = parent_dist + 0.15 * sister_dist
            proposals.append((score, source_id, candidate_id, parent_dist, sister_dist))
    return proposals


def _e23_frame_proposals(
    cfg: PostprocConfig,
    nodes_by_id: dict[int, dict[str, object]],
    out_by_source: dict[int, list[dict[str, object]]],
    incoming: set[int],
    existing_edges: set[tuple[int, int]],
    source_ids: list[int],
    candidate_ids: list[int],
    t: int,
    stats: dict[str, int],
    dataset: str | None,
    deepcenter_bundle: dict[str, object] | None,
    frame_cache: dict[int, np.ndarray],
    deepcenter_cache: dict[tuple[str, int], np.ndarray],
) -> list[tuple[float, int, int, float, float]]:
    """E23 notebook candidate generation (pub923_repro add_safe_divisions_postlink).

    One cKDTree over ALL orphan candidates of the frame, in physical
    micrometres; the mutual gate queries the GLOBAL nearest orphan of the
    existing child, so the nearest orphan may sit outside the parent ball.
    Per-source gates: existing child at t+1 within
    SAFE_DIV_EXISTING_CHILD_MAX_UM; C1 mid-track parent (the notebook
    hardwires it; the port exposes SAFE_DIV_REQUIRE_MID_TRACK_PARENT).
    Per-candidate gates accept exactly the notebook's set: existing edge,
    parent radius (ball membership), sister radius, C2 mutual nearest
    orphan, DeepCenter safe-division veto (before divergence), C3 t+2
    divergence (distinct single successors whose t+2 separation grew by at
    least SAFE_DIV_DIVERGE_UM).

    Parity note: the submitted notebook declares
    ``safe_division_geometric_candidates``,
    ``safe_division_mutual_nn_rejected`` and
    ``safe_division_divergence_rejected`` but never increments them (they
    always print 0). The port fills all three truthfully: geometric counts
    every candidate that passes the existing-edge and the distance gates,
    before mutual-NN, DeepCenter, or divergence; the other two count the
    respective gate rejections.
    """
    positions = np.asarray(
        [
            [
                float(nodes_by_id[candidate_id]["z"]) * VOXEL_SCALE_UM[0],
                float(nodes_by_id[candidate_id]["y"]) * VOXEL_SCALE_UM[1],
                float(nodes_by_id[candidate_id]["x"]) * VOXEL_SCALE_UM[2],
            ]
            for candidate_id in candidate_ids
        ],
        dtype=float,
    )
    tree = cKDTree(positions) if len(positions) else None

    def _succ1(node_id: int) -> int | None:
        out_edges = out_by_source.get(node_id, [])
        return int(out_edges[0]["target_id"]) if len(out_edges) == 1 else None

    proposals: list[tuple[float, int, int, float, float]] = []
    for source_id in source_ids:
        source = nodes_by_id[source_id]
        existing_child_edge = out_by_source[source_id][0]
        existing_child_id = int(existing_child_edge["target_id"])
        existing_child = nodes_by_id.get(existing_child_id)
        if existing_child is None or int(existing_child["t"]) != t + 1:
            continue
        child_dist = edge_distance_um(source, existing_child)
        if child_dist > cfg.SAFE_DIV_EXISTING_CHILD_MAX_UM:
            continue
        # C1: parent must be mid-track (has a predecessor) - not a track start
        if cfg.SAFE_DIV_REQUIRE_MID_TRACK_PARENT and source_id not in incoming:
            continue
        if tree is None:
            continue
        source_point = np.asarray(
            [
                float(source["z"]) * VOXEL_SCALE_UM[0],
                float(source["y"]) * VOXEL_SCALE_UM[1],
                float(source["x"]) * VOXEL_SCALE_UM[2],
            ],
            dtype=float,
        )
        near = tree.query_ball_point(source_point, r=cfg.SAFE_DIV_MAX_UM)
        child_point = np.asarray(
            [
                float(existing_child["z"]) * VOXEL_SCALE_UM[0],
                float(existing_child["y"]) * VOXEL_SCALE_UM[1],
                float(existing_child["x"]) * VOXEL_SCALE_UM[2],
            ],
            dtype=float,
        )
        # Single nearest query on the ALL-orphan tree at the existing-child
        # point, exactly the notebook's call. SciPy does not specify which of
        # several exactly equidistant points cKDTree.query returns, and
        # nonzero-index tie winners occur in practice, so a tie's winner is an
        # unspecified implementation detail here, not a guaranteed contract.
        nearest_dist, nearest_idx = tree.query(child_point)
        mutual_id = candidate_ids[int(nearest_idx)] if nearest_dist <= cfg.SAFE_DIV_SISTER_MAX_UM else None
        for near_idx in near:
            candidate_id = candidate_ids[int(near_idx)]
            if (source_id, candidate_id) in existing_edges:
                continue
            candidate = nodes_by_id[candidate_id]
            parent_dist = edge_distance_um(source, candidate)
            if parent_dist > cfg.SAFE_DIV_MAX_UM:
                continue
            sister_dist = edge_distance_um(existing_child, candidate)
            if sister_dist > cfg.SAFE_DIV_SISTER_MAX_UM:
                continue
            stats["safe_division_geometric_candidates"] += 1
            # C2: sisters must be MUTUAL nearest orphans
            if cfg.SAFE_DIV_REQUIRE_MUTUAL_NN and candidate_id != mutual_id:
                stats["safe_division_mutual_nn_rejected"] += 1
                continue
            if cfg.DEEPCENTER_SAFE_DIV_VETO and not deepcenter_accept_repair_point(
                cfg,
                dataset,
                int(candidate["t"]),
                (float(candidate["z"]), float(candidate["y"]), float(candidate["x"])),
                deepcenter_bundle,
                frame_cache,
                deepcenter_cache,
                stats,
                "safe_div",
                cfg.DEEPCENTER_SAFE_DIV_THRESHOLD,
            ):
                continue
            # C3: DIVERGENCE - both daughters continue at t+2 and separate.
            if cfg.SAFE_DIV_REQUIRE_DIVERGENCE:
                successor_1 = _succ1(existing_child_id)
                successor_2 = _succ1(candidate_id)
                rejected = successor_1 is None or successor_2 is None or successor_1 == successor_2
                if not rejected:
                    node_1 = nodes_by_id.get(successor_1)
                    node_2 = nodes_by_id.get(successor_2)
                    rejected = (
                        node_1 is None
                        or node_2 is None
                        or int(node_1["t"]) != t + 2
                        or int(node_2["t"]) != t + 2
                        or edge_distance_um(node_1, node_2) - sister_dist < cfg.SAFE_DIV_DIVERGE_UM
                    )
                if rejected:
                    stats["safe_division_divergence_rejected"] += 1
                    continue
            score = parent_dist + 0.15 * sister_dist
            proposals.append((score, source_id, candidate_id, parent_dist, sister_dist))
    return proposals
