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
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from biohub.io import load_geff_graph
from biohub.public_postproc.config import PostprocConfig
from biohub.public_postproc.csv_out import SubmissionCsvWriter, write_run_stats
from biohub.public_postproc.deepcenter import load_deepcenter_veto_detector
from biohub.public_postproc.divisions import add_safe_divisions_postlink
from biohub.public_postproc.frames import refine_all_centroids
from biohub.public_postproc.geometry import edge_distance_um, edge_sort_key
from biohub.public_postproc.graph_ops import (
    close_single_frame_gaps,
    filter_short_track_components,
    linefit_smooth_output_graph,
    motion_relink_edges,
    recover_strict_gap2,
)

CHECKPOINT_MANIFEST_NAME = "manifest.json"


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
    return {
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


def filter_output_graph_pre_linefit(
    cfg: PostprocConfig,
    nodes_by_id: dict[int, dict[str, object]],
    raw_edges: list[dict[str, object]],
    dataset: str | None = None,
    deepcenter_bundle: dict[str, object] | None = None,
) -> tuple[dict[int, dict[str, object]], list[dict[str, object]], dict[str, int]]:
    """Everything ``filter_output_graph`` does *except* the final linefit-smoothing call.

    This is the checkpoint boundary: final node/edge topology is fixed here
    (``filter_short_track_components`` already ran); only coordinates can
    still move.
    """
    stats = new_stats()
    stats["raw_edges"] = len(raw_edges)

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
        motion_edges = motion_relink_edges(cfg, nodes_by_id, stats, learned_edge_probs)
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

    if cfg.OUTPUT_PRUNE_ISOLATED:
        incident = {int(edge["source_id"]) for edge in edges} | {int(edge["target_id"]) for edge in edges}
        if incident:
            kept_nodes = {node_id: node for node_id, node in nodes_by_id.items() if node_id in incident}
            stats["pruned_isolated_nodes"] = len(nodes_by_id) - len(kept_nodes)
            nodes_by_id = kept_nodes
            edges = [edge for edge in edges if int(edge["source_id"]) in nodes_by_id and int(edge["target_id"]) in nodes_by_id]

    nodes_by_id, edges = filter_short_track_components(cfg, nodes_by_id, edges, stats)

    return nodes_by_id, edges, stats


def filter_output_graph(
    cfg: PostprocConfig,
    nodes_by_id: dict[int, dict[str, object]],
    raw_edges: list[dict[str, object]],
    dataset: str | None = None,
    deepcenter_bundle: dict[str, object] | None = None,
) -> tuple[dict[int, dict[str, object]], list[dict[str, object]], dict[str, int]]:
    nodes_by_id, edges, stats = filter_output_graph_pre_linefit(
        cfg, nodes_by_id, raw_edges, dataset=dataset, deepcenter_bundle=deepcenter_bundle
    )
    nodes_by_id = linefit_smooth_output_graph(cfg, nodes_by_id, edges, stats)
    return nodes_by_id, edges, stats


def _load_geff_as_dicts(geff_path: Path) -> tuple[dict[int, dict[str, object]], list[dict[str, object]]]:
    graph = load_geff_graph(geff_path)

    nodes_by_id: dict[int, dict[str, object]] = {}
    for row in graph.node_attrs().iter_rows(named=True):
        node_id = int(row["node_id"])
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


def run_postproc(
    geff_dir: Path,
    out_csv: Path,
    cfg: PostprocConfig,
    run_stats_path: Path | None = None,
    predict_seconds: float = 0.0,
) -> dict[str, object]:
    """Run the full stack over every ``*.geff`` in ``geff_dir``; write ``out_csv`` + run_stats.

    Mirrors the notebook's main loop: one geff -> one dataset's worth of
    node/edge rows, appended to a single streaming CSV with one running
    ``id`` counter, plus a per-dataset run_stats.csv row.
    """
    geffs = sorted(geff_dir.glob("*.geff"))
    if not geffs:
        raise RuntimeError(f"no *.geff files found in {geff_dir}")

    deepcenter_detector = load_deepcenter_veto_detector(cfg)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    stats_rows: list[dict[str, object]] = []
    total_nodes = 0
    total_edges = 0

    with out_csv.open("w", newline="") as handle:
        writer = SubmissionCsvWriter(handle)

        for geff_path in geffs:
            dataset = geff_path.stem
            nodes_by_id, raw_edges = _load_geff_as_dicts(geff_path)

            raw_node_count = len(nodes_by_id)
            nodes_by_id, edges, filter_stats = filter_output_graph(
                cfg, nodes_by_id, raw_edges, dataset=dataset, deepcenter_bundle=deepcenter_detector
            )
            if not nodes_by_id:
                raise AssertionError(f"{dataset}: post-processing removed every node")

            writer.write_nodes(dataset, nodes_by_id)
            division_sources = writer.write_edges(dataset, nodes_by_id, edges)

            total_nodes += len(nodes_by_id)
            total_edges += len(edges)
            stats_rows.append(_dataset_stats_row(dataset, nodes_by_id, edges, filter_stats, raw_node_count, division_sources))

    stats_frame = _finish_run(
        writer, stats_rows, total_nodes, total_edges, cfg, run_stats_path or out_csv.parent / "run_stats.csv", predict_seconds
    )

    return {
        "datasets": [p.stem for p in geffs],
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "total_rows": writer.row_id,
        "run_stats": stats_frame,
    }


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

    deepcenter_detector = load_deepcenter_veto_detector(cfg)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    datasets: list[str] = []
    for geff_path in geffs:
        dataset = geff_path.stem
        nodes_by_id, raw_edges = _load_geff_as_dicts(geff_path)
        raw_node_count = len(nodes_by_id)
        nodes_by_id, edges, stats = filter_output_graph_pre_linefit(
            cfg, nodes_by_id, raw_edges, dataset=dataset, deepcenter_bundle=deepcenter_detector
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

            nodes_by_id = linefit_smooth_output_graph(cfg, nodes_by_id, edges, stats)

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
