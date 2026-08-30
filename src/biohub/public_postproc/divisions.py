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

from dataclasses import dataclass

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
