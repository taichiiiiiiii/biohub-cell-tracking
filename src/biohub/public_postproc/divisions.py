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

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from numbers import Integral, Real

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


def _freeze_twin_dtype(dtype: np.dtype) -> TwinFrozenDType:
    metadata = _freeze_twin_value(dtype.metadata) if dtype.metadata is not None else None
    if metadata is not None and not isinstance(metadata, TwinFrozenMapping):
        raise TypeError("numpy dtype metadata must be a mapping")
    return TwinFrozenDType(
        dtype.str,
        _freeze_twin_value(dtype.descr),
        metadata,
        int(dtype.itemsize),
        int(dtype.alignment),
        dtype.byteorder,
        tuple(dtype.names) if dtype.names is not None else None,
        bool(dtype.hasobject),
        bool(dtype.isalignedstruct),
    )


def _freeze_twin_structured_scalar(value: np.void, dtype: np.dtype) -> TwinFrozenStructuredScalar:
    if dtype.names is None:
        raise TypeError("unstructured numpy void metadata is unsupported")
    return TwinFrozenStructuredScalar(
        tuple((name, _freeze_twin_value(value[name])) for name in dtype.names)
    )


def _freeze_twin_value(value: object) -> object:
    """Freeze supported edge metadata or reject it before a plan is returned.

    Supported values are standard immutable scalars, recursively frozen
    mappings/sequences/sets, NumPy dtypes/scalars/arrays, bytearrays, and
    memoryviews. Arbitrary objects are rejected rather than retained behind a
    frozen dataclass or ambiguously deep-copied.
    """
    if isinstance(value, np.dtype):
        return _freeze_twin_dtype(value)
    if isinstance(value, np.ndarray):
        original_shape = tuple(value.shape)
        original_strides = tuple(value.strides)
        copied_array = np.array(value, copy=True, subok=False, order="K")
        if value.dtype.hasobject:
            if value.dtype.names is not None:
                content: bytes | tuple[object, ...] = tuple(
                    _freeze_twin_structured_scalar(copied_array[index], value.dtype)
                    for index in np.ndindex(original_shape)
                )
            else:
                content = tuple(
                    _freeze_twin_value(copied_array[index]) for index in np.ndindex(original_shape)
                )
        else:
            content = copied_array.tobytes(order="C")
        return TwinFrozenArray(
            _freeze_twin_dtype(value.dtype),
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
            tuple((_freeze_twin_value(key), _freeze_twin_value(item)) for key, item in value.items())
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_twin_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_twin_value(item) for item in value)
    if isinstance(value, np.void):
        return _freeze_twin_structured_scalar(value, value.dtype)
    if isinstance(value, np.generic):
        if value.dtype.hasobject:
            raise TypeError(f"unsupported numpy object scalar metadata: {value.dtype!r}")
        return TwinFrozenNumpyScalar(_freeze_twin_dtype(value.dtype), value.tobytes())
    if value is None or type(value) in (bool, int, float, complex, str, bytes):
        return value
    raise TypeError(f"unsupported mutable edge metadata type: {type(value).__qualname__}")


def _freeze_twin_edge_row(
    row: Mapping[str, object], source_id: int, target_id: int
) -> TwinFrozenMapping:
    """Freeze an edge row, canonicalizing its validated integer endpoints.

    Endpoint validation deliberately accepts every non-boolean
    :class:`numbers.Integral`, while the planner's endpoint contract is the
    canonical integer value used for graph identity.  Converting only the two
    endpoint fields to built-in ``int`` therefore preserves that contract and
    detaches mutable ``int`` subclasses without broadening the supported
    types for arbitrary edge metadata.
    """
    frozen_items: list[tuple[object, object]] = []
    for key, value in row.items():
        if isinstance(key, str) and key == "source_id":
            frozen_items.append((str(key), source_id))
        elif isinstance(key, str) and key == "target_id":
            frozen_items.append((str(key), target_id))
        else:
            frozen_items.append((_freeze_twin_value(key), _freeze_twin_value(value)))
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
