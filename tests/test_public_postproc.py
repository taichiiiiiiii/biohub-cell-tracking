"""Synthetic-graph tests for the ported public-notebook post-processing stack.

No competition data or geff files required: nodes/edges are built by hand as
the same plain dicts ``filter_output_graph`` consumes, and each pass under
test is isolated by disabling every other ``BIOHUB_OUTPUT_*`` toggle.
"""
from __future__ import annotations

import csv
import io
import json
import os
import pickle
import struct
from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from enum import IntEnum
from pathlib import Path

import numpy as np
import pytest

from biohub.public_postproc import deepcenter as deepcenter_module
from biohub.public_postproc import divisions as divisions_module
from biohub.public_postproc import frames as frames_module
from biohub.public_postproc import graph_ops as graph_ops_module
from biohub.public_postproc import pipeline as pipeline_module
from biohub.public_postproc.config import PostprocConfig, build_config
from biohub.public_postproc.csv_out import CSV_COLUMNS, SubmissionCsvWriter
from biohub.public_postproc.divisions import add_safe_divisions_postlink
from biohub.public_postproc.frames import refine_all_centroids, refine_centroids, refine_synthetic_midpoint
from biohub.public_postproc.geometry import point_distance_um
from biohub.public_postproc.graph_ops import close_single_frame_gaps, linefit_smooth_output_graph
from biohub.public_postproc.pipeline import filter_output_graph, filter_output_graph_pre_linefit, new_stats

# All the passes filter_output_graph can run, forced off so a test can turn
# on exactly the one it exercises.
_ALL_OFF = {
    "BIOHUB_OUTPUT_MOTION_RELINK": "0",
    "BIOHUB_OUTPUT_SINGLE_PARENT_REPAIR": "0",
    "BIOHUB_OUTPUT_SINGLE_CHILD_REPAIR": "0",
    "BIOHUB_OUTPUT_GAP_CLOSE": "0",
    "BIOHUB_OUTPUT_GAP2_RECOVERY": "0",
    "BIOHUB_OUTPUT_SAFE_DIVISIONS": "0",
    "BIOHUB_OUTPUT_DIVISION_GEOMETRY_FILTER": "0",
    "BIOHUB_OUTPUT_PRUNE_ISOLATED": "0",
    "BIOHUB_OUTPUT_FILTER_SHORT_TRACKS": "0",
    "BIOHUB_OUTPUT_LINEFIT_SMOOTH": "0",
    "BIOHUB_ADAPTIVE_SHORT_TRACK_RESCUE": "0",
    "BIOHUB_USE_DEEPCENTER_VETO": "0",
}


def _cfg(tmp_path: Path, **overrides: str) -> PostprocConfig:
    env = {**_ALL_OFF, **overrides}
    return build_config(env, test_dir=tmp_path)


def _node(node_id: int, t: int, z: float = 0.0, y: float = 0.0, x: float = 0.0) -> dict[str, object]:
    return {"node_id": node_id, "t": t, "z": z, "y": y, "x": x}


# --------------------------------------------------------------------------
# consecutive-edge enforcement
# --------------------------------------------------------------------------
def test_nonconsecutive_edge_is_dropped(tmp_path: Path):
    nodes = {1: _node(1, 0), 2: _node(2, 1), 3: _node(3, 2)}
    raw_edges = [
        {"source_id": 1, "target_id": 2, "edge_prob": 0.9},  # t0 -> t1, consecutive
        {"source_id": 1, "target_id": 3, "edge_prob": 0.9},  # t0 -> t2, skips a frame
    ]
    cfg = _cfg(tmp_path, BIOHUB_OUTPUT_ENFORCE_NEXT_FRAME="1")

    kept_nodes, kept_edges, stats = filter_output_graph(cfg, nodes, raw_edges, dataset=None)

    assert [(int(e["source_id"]), int(e["target_id"])) for e in kept_edges] == [(1, 2)]
    assert stats["dropped_nonconsecutive_edges"] == 1
    assert set(kept_nodes) == {1, 2, 3}  # prune-isolated is off: node 3 survives, just unlinked


def test_consecutive_edges_all_kept_when_enforcement_disabled(tmp_path: Path):
    nodes = {1: _node(1, 0), 2: _node(2, 1), 3: _node(3, 2)}
    raw_edges = [
        {"source_id": 1, "target_id": 2, "edge_prob": 0.9},
        {"source_id": 1, "target_id": 3, "edge_prob": 0.9},
    ]
    cfg = _cfg(tmp_path, BIOHUB_OUTPUT_ENFORCE_NEXT_FRAME="0")

    _, kept_edges, stats = filter_output_graph(cfg, nodes, raw_edges, dataset=None)

    assert len(kept_edges) == 2
    assert stats["dropped_nonconsecutive_edges"] == 0


# --------------------------------------------------------------------------
# single-parent repair
# --------------------------------------------------------------------------
def test_single_parent_repair_keeps_the_higher_scoring_edge(tmp_path: Path):
    # Two t0 sources both point at the same t1 target; only the edge with
    # the higher (edge_prob, -distance) key (edge_sort_key) should survive.
    nodes = {1: _node(1, 0), 2: _node(2, 0), 3: _node(3, 1)}
    raw_edges = [
        {"source_id": 1, "target_id": 3, "edge_prob": 0.9},  # winner
        {"source_id": 2, "target_id": 3, "edge_prob": 0.3},  # loser
    ]
    cfg = _cfg(tmp_path, BIOHUB_OUTPUT_ENFORCE_NEXT_FRAME="1", BIOHUB_OUTPUT_SINGLE_PARENT_REPAIR="1")

    _, kept_edges, stats = filter_output_graph(cfg, nodes, raw_edges, dataset=None)

    assert len(kept_edges) == 1
    assert int(kept_edges[0]["source_id"]) == 1
    assert stats["dropped_multi_parent_edges"] == 1


def test_single_parent_repair_off_keeps_both_parents(tmp_path: Path):
    nodes = {1: _node(1, 0), 2: _node(2, 0), 3: _node(3, 1)}
    raw_edges = [
        {"source_id": 1, "target_id": 3, "edge_prob": 0.9},
        {"source_id": 2, "target_id": 3, "edge_prob": 0.3},
    ]
    cfg = _cfg(tmp_path, BIOHUB_OUTPUT_ENFORCE_NEXT_FRAME="1", BIOHUB_OUTPUT_SINGLE_PARENT_REPAIR="0")

    _, kept_edges, stats = filter_output_graph(cfg, nodes, raw_edges, dataset=None)

    assert len(kept_edges) == 2
    assert stats["dropped_multi_parent_edges"] == 0


# --------------------------------------------------------------------------
# linefit smoothing leaves topology unchanged
# --------------------------------------------------------------------------
def test_linefit_smoothing_moves_points_but_not_topology(tmp_path: Path):
    # A slightly bent 5-node chain along x; z, y constant.
    xs = [0.0, 1.0, 3.0, 3.0, 4.0]  # index 2 is off the straight line 0,1,2,3,4
    nodes = {i + 1: _node(i + 1, t=i, x=xs[i]) for i in range(5)}
    edges = [{"source_id": i + 1, "target_id": i + 2, "edge_prob": 1.0, "distance_um": 1.0} for i in range(4)]
    node_ids_before = set(nodes)
    original_x = {nid: node["x"] for nid, node in nodes.items()}

    cfg = _cfg(
        tmp_path, BIOHUB_OUTPUT_LINEFIT_SMOOTH="1", BIOHUB_OUTPUT_LINEFIT_WEIGHT="0.8", BIOHUB_OUTPUT_LINEFIT_WINDOW="2"
    )
    stats: dict[str, int] = {"linefit_smoothed_nodes": 0, "linefit_skipped_nodes": 0}

    smoothed = linefit_smooth_output_graph(cfg, nodes, edges, stats)

    # Topology: same node set, same edge list (the function never touches edges).
    assert set(smoothed) == node_ids_before
    assert edges == [{"source_id": i + 1, "target_id": i + 2, "edge_prob": 1.0, "distance_um": 1.0} for i in range(4)]
    # Every node has >= 3 points in its window=2 neighbourhood on a 5-node chain.
    assert stats["linefit_smoothed_nodes"] == 5
    assert stats["linefit_skipped_nodes"] == 0
    # The deliberately-bent node moved toward the fitted line.
    assert smoothed[3]["x"] != pytest.approx(original_x[3])


def test_linefit_smoothing_noop_when_disabled(tmp_path: Path):
    nodes = {1: _node(1, 0, x=0.0), 2: _node(2, 1, x=5.0)}
    edges = [{"source_id": 1, "target_id": 2, "edge_prob": 1.0, "distance_um": 1.0}]
    cfg = _cfg(tmp_path, BIOHUB_OUTPUT_LINEFIT_SMOOTH="0")
    stats: dict[str, int] = {"linefit_smoothed_nodes": 0, "linefit_skipped_nodes": 0}

    out = linefit_smooth_output_graph(cfg, nodes, edges, stats)

    assert out[1]["x"] == 0.0 and out[2]["x"] == 5.0
    assert stats["linefit_smoothed_nodes"] == 0


# --------------------------------------------------------------------------
# CSV schema
# --------------------------------------------------------------------------
def test_csv_writer_schema_and_row_shape():
    handle = io.StringIO()
    writer = SubmissionCsvWriter(handle)

    nodes = {2: _node(2, 1, z=3, y=4, x=5), 1: _node(1, 0, z=1, y=2, x=3)}
    edges = [{"source_id": 1, "target_id": 2}]

    writer.write_nodes("dsA", nodes)
    division_sources = writer.write_edges("dsA", nodes, edges)

    handle.seek(0)
    rows = list(csv.DictReader(handle))

    assert list(rows[0].keys()) == CSV_COLUMNS == [
        "id", "dataset", "row_type", "node_id", "t", "z", "y", "x", "source_id", "target_id",
    ]
    assert [r["id"] for r in rows] == ["0", "1", "2"]
    # Nodes are written sorted by node_id (1 before 2), edges after.
    assert [r["row_type"] for r in rows] == ["node", "node", "edge"]
    assert [r["node_id"] for r in rows] == ["1", "2", "-1"]

    node_rows = [r for r in rows if r["row_type"] == "node"]
    for r in node_rows:
        assert r["source_id"] == "-1" and r["target_id"] == "-1"

    edge_row = rows[2]
    assert edge_row["node_id"] == "-1" and edge_row["t"] == "-1"
    assert edge_row["z"] == "-1" and edge_row["y"] == "-1" and edge_row["x"] == "-1"
    assert edge_row["source_id"] == "1" and edge_row["target_id"] == "2"
    assert division_sources == {1: 1}


def test_csv_writer_id_counter_is_continuous_across_datasets():
    handle = io.StringIO()
    writer = SubmissionCsvWriter(handle)

    writer.write_nodes("dsA", {1: _node(1, 0)})
    writer.write_edges("dsA", {1: _node(1, 0)}, [])
    writer.write_nodes("dsB", {5: _node(5, 0)})
    writer.write_edges("dsB", {5: _node(5, 0)}, [])

    handle.seek(0)
    rows = list(csv.DictReader(handle))
    assert [r["id"] for r in rows] == ["0", "1"]
    assert [r["dataset"] for r in rows] == ["dsA", "dsB"]
    assert writer.row_id == 2


def test_csv_writer_raises_on_dangling_edge():
    handle = io.StringIO()
    writer = SubmissionCsvWriter(handle)
    nodes = {1: _node(1, 0)}
    with pytest.raises(AssertionError, match="dangling edge"):
        writer.write_edges("dsA", nodes, [{"source_id": 1, "target_id": 999}])


# --------------------------------------------------------------------------
# E23 all-node intensity-centroid refinement (Phase 2)
# --------------------------------------------------------------------------
def _write_synthetic_zarr(test_dir: Path, dataset: str, frames: dict[int, np.ndarray]) -> Path:
    """Write the minimal ``<dataset>.zarr`` layout ``biohub.io.open_volume`` reads."""
    import blosc2

    depth, height, width = next(iter(frames.values())).shape
    array_dir = test_dir / f"{dataset}.zarr" / "0"
    array_dir.mkdir(parents=True)
    (array_dir / "zarr.json").write_text(
        json.dumps({"shape": [max(frames) + 1, depth, height, width], "data_type": "uint16"})
    )
    for t, frame in frames.items():
        chunk_dir = array_dir / "c" / str(t) / "0" / "0"
        chunk_dir.mkdir(parents=True)
        (chunk_dir / "0").write_bytes(blosc2.compress(frame.astype(np.uint16).tobytes(), typesize=2))
    return test_dir / f"{dataset}.zarr"


def _spy_open_volume(monkeypatch) -> list[Path]:
    """Count ``frames.open_volume`` calls while still decoding the real zarr."""
    from biohub.io import open_volume as real_open_volume

    opened: list[Path] = []

    def counting_open_volume(path):
        opened.append(Path(path))
        return real_open_volume(path)

    monkeypatch.setattr(frames_module, "open_volume", counting_open_volume)
    return opened


def _frame_with_spot(shape: tuple[int, int, int], spot: tuple[int, int, int], value: int = 1000) -> np.ndarray:
    frame = np.zeros(shape, dtype=np.uint16)
    frame[spot] = value
    return frame


def test_refine_centroids_exact_weighted_center(tmp_path: Path):
    cfg = _cfg(tmp_path)
    vol = np.zeros((5, 9, 9), dtype=np.uint16)
    # Window around (2, 4, 4) at wz=1 / wyx=3; the 20th-percentile baseline of
    # the mostly-zero patch is 0, so only the two bright voxels carry weight.
    vol[2, 4, 5] = 300
    vol[2, 5, 4] = 100
    stats = new_stats()

    refined = refine_centroids(cfg, vol, [(2.0, 4.0, 4.0)], stats)

    # centroid = (300 * (2, 4, 5) + 100 * (2, 5, 4)) / 400
    assert refined == [(2.0, 4.25, 4.75)]
    assert stats["centroid_refine_examined"] == 1
    assert stats["centroid_refine_moved"] == 1
    assert stats["centroid_refine_no_signal"] == 0
    assert stats["centroid_refine_rejected_shift"] == 0


def test_refine_centroids_zero_signal_keeps_point_and_counts(tmp_path: Path):
    cfg = _cfg(tmp_path)
    vol = np.zeros((5, 9, 9), dtype=np.uint16)
    stats = new_stats()

    # Flat patch (total weight 0) and empty patch (rounded point far outside
    # the volume) both degrade to "no signal": coordinates left unchanged.
    refined = refine_centroids(cfg, vol, [(2.0, 4.0, 4.0), (100.0, 100.0, 100.0)], stats)

    assert refined == [(2.0, 4.0, 4.0), (100.0, 100.0, 100.0)]
    assert stats["centroid_refine_examined"] == 2
    assert stats["centroid_refine_no_signal"] == 2
    assert stats["centroid_refine_moved"] == 0
    assert stats["centroid_refine_rejected_shift"] == 0


def test_refine_centroids_rejects_excessive_physical_shift(tmp_path: Path):
    # Single bright voxel at the window edge: centroid 3 yx voxels away,
    # 3 * 0.40625 = 1.21875 um > the 0.5 um cap.
    cfg = _cfg(tmp_path, BIOHUB_REFINE_CENTROIDS_MAX_SHIFT_UM="0.5")
    vol = np.zeros((5, 9, 9), dtype=np.uint16)
    vol[2, 4, 7] = 500
    stats = new_stats()

    refined = refine_centroids(cfg, vol, [(2.0, 4.0, 4.0)], stats)

    assert refined == [(2.0, 4.0, 4.0)]
    assert stats["centroid_refine_examined"] == 1
    assert stats["centroid_refine_rejected_shift"] == 1
    assert stats["centroid_refine_moved"] == 0


def test_refine_centroids_exact_noop_is_not_counted_as_moved(tmp_path: Path):
    cfg = _cfg(tmp_path)
    vol = np.zeros((5, 9, 9), dtype=np.uint16)
    # Symmetric bright pattern around (2, 4, 4): the weighted centroid is the
    # input point itself, an accepted exact no-op that must not count as moved.
    vol[2, 4, 4] = 100
    vol[1, 4, 4] = vol[3, 4, 4] = 50
    vol[2, 3, 4] = vol[2, 5, 4] = 50
    vol[2, 4, 3] = vol[2, 4, 5] = 50
    stats = new_stats()

    refined = refine_centroids(cfg, vol, [(2.0, 4.0, 4.0)], stats)

    assert refined == [(2.0, 4.0, 4.0)]
    assert stats["centroid_refine_examined"] == 1
    assert stats["centroid_refine_moved"] == 0
    assert stats["centroid_refine_no_signal"] == 0
    assert stats["centroid_refine_rejected_shift"] == 0


def test_refine_all_centroids_reads_each_frame_once_and_keeps_order(tmp_path: Path, monkeypatch):
    shape = (20, 40, 40)
    frames = {0: _frame_with_spot(shape, (10, 20, 21)), 1: _frame_with_spot(shape, (10, 20, 23))}
    _write_synthetic_zarr(tmp_path, "synthetic", frames)
    opened = _spy_open_volume(monkeypatch)
    cfg = _cfg(tmp_path, BIOHUB_REFINE_ALL_CENTROIDS="1")
    nodes = {
        5: _node(5, 0, z=10.0, y=20.0, x=20.0),
        3: _node(3, 1, z=10.0, y=20.0, x=24.0),
        9: _node(9, 0, z=10.0, y=20.0, x=20.0),
    }
    stats = new_stats()
    frame_cache: dict[int, np.ndarray] = {}

    refine_all_centroids(cfg, nodes, "synthetic", frame_cache, stats)

    assert opened == [tmp_path / "synthetic.zarr", tmp_path / "synthetic.zarr"]  # once per t
    assert sorted(frame_cache) == [0, 1]
    assert list(nodes) == [5, 3, 9]  # dict iteration order preserved
    assert (nodes[5]["z"], nodes[5]["y"], nodes[5]["x"]) == (10.0, 20.0, 21.0)
    assert (nodes[9]["z"], nodes[9]["y"], nodes[9]["x"]) == (10.0, 20.0, 21.0)
    assert (nodes[3]["z"], nodes[3]["y"], nodes[3]["x"]) == (10.0, 20.0, 23.0)
    assert stats["centroid_refine_examined"] == 3
    assert stats["centroid_refine_moved"] == 3


def test_refine_all_centroids_requires_dataset(tmp_path: Path):
    cfg = _cfg(tmp_path, BIOHUB_REFINE_ALL_CENTROIDS="1")
    with pytest.raises(ValueError, match="dataset"):
        refine_all_centroids(cfg, {1: _node(1, 0)}, None, {}, new_stats())


def test_pipeline_enabled_without_dataset_is_a_hard_failure(tmp_path: Path):
    cfg = _cfg(tmp_path, BIOHUB_REFINE_ALL_CENTROIDS="1", BIOHUB_OUTPUT_ENFORCE_NEXT_FRAME="1")
    nodes = {1: _node(1, 0), 2: _node(2, 1)}
    raw_edges = [{"source_id": 1, "target_id": 2, "edge_prob": 0.9}]
    with pytest.raises(ValueError, match="dataset"):
        filter_output_graph(cfg, nodes, raw_edges, dataset=None)


def test_refine_all_centroids_missing_image_is_runtime_error(tmp_path: Path):
    cfg = _cfg(tmp_path, BIOHUB_REFINE_ALL_CENTROIDS="1")
    nodes = {1: _node(1, 0, z=2.0, y=4.0, x=4.0)}
    with pytest.raises(RuntimeError, match="dataset=missing") as excinfo:
        refine_all_centroids(cfg, nodes, "missing", {}, new_stats())
    message = str(excinfo.value)
    assert "t=0" in message
    assert str(tmp_path / "missing.zarr") in message
    assert excinfo.value.__cause__ is not None  # original read error chained, never swallowed


def test_disabled_refinement_does_not_read_frames(tmp_path: Path, monkeypatch):
    _write_synthetic_zarr(tmp_path, "synthetic", {0: np.zeros((4, 8, 8), dtype=np.uint16)})
    opened = _spy_open_volume(monkeypatch)
    cfg = _cfg(tmp_path, BIOHUB_REFINE_ALL_CENTROIDS="0", BIOHUB_OUTPUT_ENFORCE_NEXT_FRAME="1")
    nodes = {1: _node(1, 0, z=2.0, y=4.0, x=4.0), 2: _node(2, 1, z=2.0, y=4.0, x=5.0)}
    raw_edges = [{"source_id": 1, "target_id": 2, "edge_prob": 0.9}]

    kept_nodes, kept_edges, stats = filter_output_graph(cfg, nodes, raw_edges, dataset="synthetic")

    assert opened == []  # base1 behaviour: no frame reads while refinement is off
    assert stats["centroid_refine_examined"] == 0
    assert (kept_nodes[1]["z"], kept_nodes[1]["y"], kept_nodes[1]["x"]) == (2.0, 4.0, 4.0)
    assert len(kept_edges) == 1


def test_frame_cache_shared_with_synthetic_midpoint_refinement(tmp_path: Path, monkeypatch):
    frames = {0: _frame_with_spot((20, 40, 40), (10, 20, 21))}
    _write_synthetic_zarr(tmp_path, "synthetic", frames)
    opened = _spy_open_volume(monkeypatch)
    cfg = _cfg(tmp_path, BIOHUB_REFINE_ALL_CENTROIDS="1", BIOHUB_GAP_REFINE_SYNTHETIC="1")
    nodes = {7: _node(7, 0, z=10.0, y=20.0, x=20.0)}
    stats = new_stats()
    frame_cache: dict[int, np.ndarray] = {}

    refine_all_centroids(cfg, nodes, "synthetic", frame_cache, stats)
    assert list(frame_cache) == [0]

    # The gap-refinement fallback reuses the cached frame: no second open.
    refined = refine_synthetic_midpoint(cfg, "synthetic", 0, (10.0, 20.0, 20.0), frame_cache, stats)

    assert len(opened) == 1
    assert refined == (10.0, 20.0, 21.0)
    assert (nodes[7]["z"], nodes[7]["y"], nodes[7]["x"]) == (10.0, 20.0, 21.0)
    assert stats["gap_refined_synthetic"] == 1


def _two_node_graph() -> tuple[dict[int, dict[str, object]], list[dict[str, object]]]:
    nodes = {1: _node(1, 0, z=10.0, y=20.0, x=20.0), 2: _node(2, 1, z=10.0, y=20.0, x=24.0)}
    raw_edges = [{"source_id": 1, "target_id": 2, "edge_prob": 0.9}]
    return nodes, raw_edges


def test_centroid_refinement_runs_before_edge_distance_filter(tmp_path: Path):
    # Raw node distance is 4 yx voxels = 1.625 um, above the 1.0 um edge cap;
    # the intensity spots pull both centroids one voxel inward each, leaving
    # 2 voxels = 0.8125 um. The edge can only survive when refinement runs
    # *before* the edge-distance filter.
    shape = (20, 40, 40)
    frames = {0: _frame_with_spot(shape, (10, 20, 21)), 1: _frame_with_spot(shape, (10, 20, 23))}
    _write_synthetic_zarr(tmp_path, "synthetic", frames)
    edge_cap = {"BIOHUB_OUTPUT_ENFORCE_NEXT_FRAME": "1", "BIOHUB_OUTPUT_EDGE_MAX_UM": "1.0"}

    cfg_off = _cfg(tmp_path, BIOHUB_REFINE_ALL_CENTROIDS="0", **edge_cap)
    nodes_off, edges_off, stats_off = filter_output_graph_pre_linefit(cfg_off, *_two_node_graph(), dataset="synthetic")
    assert edges_off == []
    assert stats_off["dropped_long_edges"] == 1
    assert nodes_off[1]["x"] == 20.0  # untouched without refinement

    cfg_on = _cfg(tmp_path, BIOHUB_REFINE_ALL_CENTROIDS="1", **edge_cap)
    nodes_on, edges_on, stats_on = filter_output_graph_pre_linefit(cfg_on, *_two_node_graph(), dataset="synthetic")
    assert len(edges_on) == 1
    assert stats_on["dropped_long_edges"] == 0
    assert stats_on["centroid_refine_examined"] == 2
    assert stats_on["centroid_refine_moved"] == 2
    assert (nodes_on[1]["z"], nodes_on[1]["y"], nodes_on[1]["x"]) == (10.0, 20.0, 21.0)
    assert (nodes_on[2]["z"], nodes_on[2]["y"], nodes_on[2]["x"]) == (10.0, 20.0, 23.0)


# --------------------------------------------------------------------------
# named profiles: base1 (legacy default) and e23 (submitted E23 parity)
# --------------------------------------------------------------------------
def test_base1_profile_is_byte_for_byte_the_legacy_default():
    # Default call and explicit base1 must produce identical configs, and the
    # result must keep every value of the pre-profile (base1) behavior.
    assert build_config(profile="base1") == build_config()
    cfg = build_config()
    assert cfg.MOTION_RELINK_LEARNED_BONUS == 1.0
    assert cfg.MOTION_RELINK_RELAXED_UM == 9.5
    assert cfg.GAP_CLOSE_MAX_GAP == 2
    assert cfg.GAP_CLOSE_UM == 5.8
    assert cfg.GAP_DENSITY_ADAPTIVE is True
    assert cfg.SAFE_DIV_MAX_UM == 4.66
    assert cfg.SAFE_DIV_SISTER_MAX_UM == 8.5
    assert cfg.SAFE_DIV_EXISTING_CHILD_MAX_UM == 7.65
    assert cfg.SAFE_DIV_FRAME_FRAC_CAP == 0.0076
    assert cfg.SAFE_DIV_GLOBAL_FRAC_CAP == 0.00375
    assert cfg.ADAPTIVE_SHORT_TRACK_RESCUE is True
    assert cfg.SHORT_TRACK_RESCUE_MIN_LEN == 5
    assert cfg.USE_DEEPCENTER_VETO is False
    assert cfg.REQUIRE_DEEPCENTER_VETO is False
    assert cfg.DEEPCENTER_GAP_VETO is False
    assert cfg.DEEPCENTER_SAFE_DIV_VETO is False
    assert cfg.DEEPCENTER_EXPECTED_EPOCH == 0
    assert cfg.DEEPCENTER_GAP_CONFIRM_MIN_SPAN_UM == 8.0
    assert cfg.DEEPCENTER_GAP_THRESHOLD == 0.20
    assert cfg.EXPERIMENT_TAG == "biohub_132_clean_short_track_rescue_lightcv_nohack"
    # Phase-1 additions stay inert under base1.
    assert cfg.REFINE_ALL_CENTROIDS is False
    assert cfg.SAFE_DIV_MODE == "legacy"
    assert cfg.SAFE_DIV_REQUIRE_MID_TRACK_PARENT is False
    assert cfg.SAFE_DIV_REQUIRE_MUTUAL_NN is False
    assert cfg.SAFE_DIV_REQUIRE_DIVERGENCE is False


def test_e23_profile_exact_values():
    cfg = build_config(profile="e23")
    best_pt = "/kaggle/input/biohub-deepcenter-unet3d-center-prior-v1/weights/full_frame_center/best.pt"

    assert cfg.MOTION_RELINK_LEARNED_BONUS == 1.0
    assert cfg.GAP_CLOSE_MAX_GAP == 2
    assert cfg.GAP_CLOSE_UM == 5.8
    assert cfg.GAP_DENSITY_ADAPTIVE is True
    assert cfg.GAP_DENSITY_REFERENCE_UM == 6.5
    assert cfg.GAP_DENSITY_GAIN == 0.040
    assert cfg.GAP_DENSITY_MAX_STEP_DELTA_UM == 0.125
    assert cfg.GAP_DENSITY_NEIGHBORS == 3
    assert cfg.OUTPUT_FILTER_SHORT_TRACKS is True
    assert cfg.OUTPUT_MIN_TRACK_LEN == 6
    assert cfg.OUTPUT_KEEP_DIVISION_COMPONENTS is True
    assert cfg.OUTPUT_GAP2_RECOVERY is False
    assert cfg.ADAPTIVE_SHORT_TRACK_RESCUE is False
    assert cfg.SAFE_DIV_MAX_UM == 8.0
    assert cfg.SAFE_DIV_SISTER_MAX_UM == 11.0
    assert cfg.SAFE_DIV_EXISTING_CHILD_MAX_UM == 10.0
    assert cfg.SAFE_DIV_FRAME_FRAC_CAP == 0.0076
    assert cfg.SAFE_DIV_GLOBAL_FRAC_CAP == 0.00375
    assert cfg.SAFE_DIV_MODE == "e23"
    assert cfg.SAFE_DIV_REQUIRE_MID_TRACK_PARENT is True
    assert cfg.SAFE_DIV_REQUIRE_MUTUAL_NN is True
    assert cfg.SAFE_DIV_REQUIRE_DIVERGENCE is True
    assert cfg.SAFE_DIV_DIVERGE_UM == 2.25
    assert cfg.REFINE_ALL_CENTROIDS is True
    assert cfg.REFINE_CENTROIDS_WIN_Z == 1
    assert cfg.REFINE_CENTROIDS_WIN_YX == 3
    assert cfg.REFINE_CENTROIDS_BASELINE_PERCENTILE == 20.0
    assert cfg.REFINE_CENTROIDS_MAX_SHIFT_UM == 2.8
    assert cfg.USE_DEEPCENTER_VETO is True
    assert cfg.REQUIRE_DEEPCENTER_VETO is True
    assert cfg.DEEPCENTER_EXPECTED_EPOCH == 2
    assert cfg.DEEPCENTER_GAP_CONFIRM_MIN_SPAN_UM == 8.5
    assert cfg.DEEPCENTER_CHECKPOINT == best_pt
    assert cfg.DEEPCENTER_RELATIVE == "weights/full_frame_center/best.pt"
    assert cfg.DEEPCENTER_CHECKPOINT_DEFAULT == best_pt
    assert cfg.DEEPCENTER_GAP_VETO is True
    assert cfg.DEEPCENTER_GAP_THRESHOLD == 0.25
    assert cfg.DEEPCENTER_SAFE_DIV_VETO is True
    assert cfg.DEEPCENTER_SAFE_DIV_THRESHOLD == 0.12
    assert cfg.EXPERIMENT_TAG == "e23_pub923_parity"
    # Unspecified values fall back to CODE_DEFAULTS, never to base1's preset.
    assert cfg.MOTION_RELINK_TIGHT_UM == 6.0
    assert cfg.MOTION_RELINK_RELAXED_UM == 10.0  # base1 preset says 9.5
    assert cfg.SHORT_TRACK_RESCUE_MIN_LEN == 4  # base1 preset says 5
    assert cfg.OUTPUT_LINEFIT_WEIGHT == 0.8


def test_overrides_win_over_the_selected_profile():
    cfg = build_config({"BIOHUB_GAP_CLOSE_UM": "7.0", "BIOHUB_SAFE_DIV_MODE": "legacy"}, profile="e23")
    assert cfg.GAP_CLOSE_UM == 7.0
    assert cfg.SAFE_DIV_MODE == "legacy"
    assert cfg.EXPERIMENT_TAG == "e23_pub923_parity"


def test_unknown_profile_raises_value_error():
    with pytest.raises(ValueError, match="unknown profile"):
        build_config(profile="e24")


def test_unknown_override_key_still_fails():
    with pytest.raises(KeyError, match="unknown BIOHUB_"):
        build_config({"BIOHUB_NOT_A_KNOB": "1"}, profile="e23")


def test_safe_div_mode_is_validated():
    with pytest.raises(ValueError, match="SAFE_DIV_MODE"):
        build_config({"BIOHUB_SAFE_DIV_MODE": "aggressive"}, profile="e23")


def test_cli_parser_profile_selection():
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "postproc_geffs.py"
    spec = importlib.util.spec_from_file_location("postproc_geffs_cli", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    parser = module.build_parser()
    args = parser.parse_args(["--geff-dir", "g", "--out", "o.csv"])
    assert args.profile == "base1"
    args = parser.parse_args(["--geff-dir", "g", "--out", "o.csv", "--profile", "e23"])
    assert args.profile == "e23"
    with pytest.raises(SystemExit):
        parser.parse_args(["--geff-dir", "g", "--out", "o.csv", "--profile", "nope"])
# --------------------------------------------------------------------------
# E23 structural safe divisions (Phase 3): pub923_repro semantics
# --------------------------------------------------------------------------
def _e23_cfg(tmp_path: Path, **overrides: str) -> PostprocConfig:
    # Caps default to 1.0 here so gate tests are not masked by the caps;
    # the cap tests override them explicitly.
    env = {
        "BIOHUB_OUTPUT_SAFE_DIVISIONS": "1",
        "BIOHUB_SAFE_DIV_MODE": "e23",
        "BIOHUB_SAFE_DIV_REQUIRE_MID_TRACK_PARENT": "1",
        "BIOHUB_SAFE_DIV_REQUIRE_MUTUAL_NN": "1",
        "BIOHUB_SAFE_DIV_REQUIRE_DIVERGENCE": "1",
        "BIOHUB_SAFE_DIV_MAX_UM": "8.0",
        "BIOHUB_SAFE_DIV_SISTER_MAX_UM": "11.0",
        "BIOHUB_SAFE_DIV_EXISTING_CHILD_MAX_UM": "10.0",
        "BIOHUB_SAFE_DIV_DIVERGE_UM": "2.25",
        "BIOHUB_SAFE_DIV_FRAME_FRAC_CAP": "1.0",
        "BIOHUB_SAFE_DIV_GLOBAL_FRAC_CAP": "1.0",
    }
    env.update(overrides)
    return _cfg(tmp_path, **env)


def _division_frame() -> tuple[dict[int, dict[str, object]], list[dict[str, object]]]:
    """Structural safe-division scenario around the t=1 division frame.

    P0 -> P -> C (existing child), orphan B within the parent ball, and the
    t+2 successors D (of C) and E (of B), whose separation grew by 3.25 um
    (>= 2.25). All distances run along y at 0.40625 um/voxel.
    """
    nodes = {
        1: _node(1, 0, y=0.0),   # P0: predecessor, makes P mid-track
        2: _node(2, 1, y=0.0),   # P: division parent
        3: _node(3, 2, y=8.0),   # C: existing child, 3.25 um from P
        4: _node(4, 2, y=12.0),  # B: orphan candidate, 4.875 um from P
        5: _node(5, 3, y=16.0),  # D: successor of C
        6: _node(6, 3, y=28.0),  # E: successor of B
    }
    edges = [
        {"source_id": 1, "target_id": 2},
        {"source_id": 2, "target_id": 3},
        {"source_id": 3, "target_id": 5},
        {"source_id": 4, "target_id": 6},
    ]
    return nodes, edges


def test_e23_valid_division_added_with_truthful_counters(tmp_path: Path):
    nodes, edges = _division_frame()
    stats = new_stats()

    out = add_safe_divisions_postlink(_e23_cfg(tmp_path), nodes, edges, stats)

    assert len(out) == len(edges) + 1
    assert out[: len(edges)] == edges  # originals keep their list order
    assert out[-1] == {
        "source_id": 2,
        "target_id": 4,
        "edge_prob": None,
        "distance_um": 4.875,
        "safe_division": 1,
    }
    assert stats["safe_division_geometric_candidates"] == 1
    assert stats["safe_division_candidates"] == 1
    assert stats["safe_divisions_added"] == 1
    assert stats["safe_division_mutual_nn_rejected"] == 0
    assert stats["safe_division_divergence_rejected"] == 0
    assert stats["safe_division_skipped_cap"] == 0


def test_e23_rejects_track_start_parent(tmp_path: Path):
    nodes, edges = _division_frame()
    del nodes[1]  # P loses its predecessor -> C1 mid-track gate fails
    edges = [edge for edge in edges if edge["source_id"] != 1]
    stats = new_stats()

    out = add_safe_divisions_postlink(_e23_cfg(tmp_path), nodes, edges, stats)

    assert out == edges
    assert stats["safe_division_geometric_candidates"] == 0
    assert stats["safe_division_candidates"] == 0
    assert stats["safe_divisions_added"] == 0


def test_e23_mutual_gate_uses_global_nearest_outside_parent_ball(tmp_path: Path):
    # F is the child's globally nearest orphan but sits outside the 8 um
    # parent ball; B sits inside the ball but is not the mutual nearest.
    nodes = {
        1: _node(1, 0, y=0.0),
        2: _node(2, 1, y=0.0),
        3: _node(3, 2, y=8.0),
        4: _node(4, 2, y=-4.0),   # B: in-ball, 4.875 um from C
        5: _node(5, 2, y=19.75),  # F: nearest to C (4.773 um), 8.023 um from P
    }
    edges = [{"source_id": 1, "target_id": 2}, {"source_id": 2, "target_id": 3}]
    stats = new_stats()

    out = add_safe_divisions_postlink(_e23_cfg(tmp_path), nodes, edges, stats)

    assert out == edges
    assert stats["safe_division_geometric_candidates"] == 1  # B passed the distance gates
    assert stats["safe_division_mutual_nn_rejected"] == 1
    assert stats["safe_division_divergence_rejected"] == 0
    assert stats["safe_divisions_added"] == 0


def test_e23_ckdtree_exact_tie_contract(tmp_path: Path):
    # B1 and B2 are exactly equidistant from C, so the mutual-NN lookup hits
    # a genuine cKDTree distance tie. SciPy does not specify which tied point
    # query returns (nonzero-index winners occur even in the pinned SciPy),
    # so the port keeps the notebook's plain tree.query(child_point) call and
    # this test asserts only the tie contract, not a cross-version winner:
    # exactly one tied candidate is accepted, the other is mutual-NN
    # rejected, the winner is one of the tied candidates, and repeated calls
    # in the same pinned runtime/input are identical.
    nodes = {
        1: _node(1, 0, y=0.0),
        2: _node(2, 1, y=0.0),
        3: _node(3, 2, y=8.0),
        4: _node(4, 2, y=6.0),   # B1: 0.8125 um from C
        5: _node(5, 2, y=10.0),  # B2: 0.8125 um from C, exact tie
        6: _node(6, 3, y=16.0),
        7: _node(7, 3, y=28.0),
        8: _node(8, 3, y=30.0),
    }
    edges = [
        {"source_id": 1, "target_id": 2},
        {"source_id": 2, "target_id": 3},
        {"source_id": 3, "target_id": 6},
        {"source_id": 4, "target_id": 7},
        {"source_id": 5, "target_id": 8},
    ]
    cfg = _e23_cfg(tmp_path)
    tied_candidate_ids = {4, 5}

    def run_once() -> tuple[list[tuple[int, int]], dict[str, int]]:
        stats = new_stats()
        out = add_safe_divisions_postlink(cfg, nodes, edges, stats)
        added = [(edge["source_id"], edge["target_id"]) for edge in out if edge.get("safe_division") == 1]
        return added, stats

    first_added, first_stats = run_once()
    for _ in range(3):
        repeated_added, repeated_stats = run_once()
        assert repeated_added == first_added  # deterministic in this runtime
        assert repeated_stats == first_stats

    assert len(first_added) == 1
    source_id, winner_id = first_added[0]
    assert source_id == 2
    assert winner_id in tied_candidate_ids
    assert first_stats["safe_division_geometric_candidates"] == 2
    assert first_stats["safe_division_mutual_nn_rejected"] == 1  # the other tied candidate
    assert first_stats["safe_division_divergence_rejected"] == 0
    assert first_stats["safe_division_candidates"] == 1
    assert first_stats["safe_divisions_added"] == 1


def test_e23_parent_radius_excludes_candidate(tmp_path: Path):
    nodes, edges = _division_frame()
    nodes[4] = _node(4, 2, y=28.0)   # 11.375 um from P: outside the 8 um ball
    nodes[6] = _node(6, 3, y=40.0)
    stats = new_stats()

    out = add_safe_divisions_postlink(_e23_cfg(tmp_path), nodes, edges, stats)

    assert out == edges
    assert stats["safe_division_geometric_candidates"] == 0
    assert stats["safe_division_candidates"] == 0
    assert stats["safe_divisions_added"] == 0


def test_e23_sister_radius_gate(tmp_path: Path):
    # Mutual-NN off so the sister gate is reachable: B sits 4.596 um from P
    # and 3.25 um from C.
    nodes = {
        1: _node(1, 0, y=0.0),
        2: _node(2, 1, y=0.0),
        3: _node(3, 2, y=8.0),
        4: _node(4, 2, y=8.0, x=8.0),
        5: _node(5, 3, y=16.0),
        6: _node(6, 3, y=36.0),
    }
    edges = [
        {"source_id": 1, "target_id": 2},
        {"source_id": 2, "target_id": 3},
        {"source_id": 3, "target_id": 5},
        {"source_id": 4, "target_id": 6},
    ]
    base = {"BIOHUB_SAFE_DIV_REQUIRE_MUTUAL_NN": "0", "BIOHUB_SAFE_DIV_MAX_UM": "5.0"}

    stats = new_stats()
    cfg = _e23_cfg(tmp_path, BIOHUB_SAFE_DIV_SISTER_MAX_UM="3.0", **base)
    out = add_safe_divisions_postlink(cfg, nodes, edges, stats)
    assert out == edges
    assert stats["safe_division_geometric_candidates"] == 0  # sister gate fires before the counter
    assert stats["safe_divisions_added"] == 0

    stats = new_stats()
    cfg = _e23_cfg(tmp_path, BIOHUB_SAFE_DIV_SISTER_MAX_UM="4.0", **base)
    out = add_safe_divisions_postlink(cfg, nodes, edges, stats)
    added = [edge for edge in out if edge.get("safe_division") == 1]
    assert [(edge["source_id"], edge["target_id"]) for edge in added] == [(2, 4)]
    assert stats["safe_division_geometric_candidates"] == 1


def test_e23_existing_child_too_far_skips_source(tmp_path: Path):
    nodes = {
        1: _node(1, 0, y=0.0),
        2: _node(2, 1, y=0.0),
        3: _node(3, 2, z=7.0),  # 11.375 um from P, above the 10 um child cap
        4: _node(4, 2, y=12.0),
    }
    edges = [{"source_id": 1, "target_id": 2}, {"source_id": 2, "target_id": 3}]
    stats = new_stats()

    out = add_safe_divisions_postlink(_e23_cfg(tmp_path), nodes, edges, stats)

    assert out == edges
    assert stats["safe_division_geometric_candidates"] == 0
    assert stats["safe_divisions_added"] == 0


def test_e23_orphan_only_and_source_only_frames_add_nothing(tmp_path: Path):
    # Orphans present but no single-outgoing source at t (P forks twice).
    nodes = {
        1: _node(1, 0, y=0.0),
        2: _node(2, 1, y=8.0),
        3: _node(3, 1, y=-8.0),
        4: _node(4, 1, y=12.0),
    }
    edges = [{"source_id": 1, "target_id": 2}, {"source_id": 1, "target_id": 3}]
    stats = new_stats()
    out = add_safe_divisions_postlink(_e23_cfg(tmp_path), nodes, edges, stats)
    assert out is edges
    assert stats["safe_division_candidates"] == 0
    assert stats["safe_divisions_added"] == 0

    # Source present but no orphan candidate at t+1.
    nodes = {1: _node(1, 0, y=0.0), 2: _node(2, 1, y=0.0), 3: _node(3, 2, y=8.0)}
    edges = [{"source_id": 1, "target_id": 2}, {"source_id": 2, "target_id": 3}]
    stats = new_stats()
    out = add_safe_divisions_postlink(_e23_cfg(tmp_path), nodes, edges, stats)
    assert out is edges
    assert stats["safe_division_candidates"] == 0


def test_e23_divergence_gate_successor_variants(tmp_path: Path):
    base_nodes, base_edges = _division_frame()
    variants = {
        # C loses its only t+2 successor.
        "missing": (
            [edge for edge in base_edges if (edge["source_id"], edge["target_id"]) != (3, 5)],
            {},
        ),
        # C's successor exists but is not at t+2.
        "non_next_frame": (base_edges, {5: _node(5, 7, y=16.0)}),
        # C has two successors, so neither daughter has a single one.
        "multiple": (
            [*base_edges, {"source_id": 3, "target_id": 7}],
            {7: _node(7, 3, y=20.0)},
        ),
        # Both daughters continue into the very same t+2 node.
        "same": (
            [edge for edge in base_edges if (edge["source_id"], edge["target_id"]) != (4, 6)]
            + [{"source_id": 4, "target_id": 5}],
            {},
        ),
    }
    for name, (edges, node_overrides) in variants.items():
        nodes = dict(base_nodes)
        nodes.update(node_overrides)
        stats = new_stats()
        out = add_safe_divisions_postlink(_e23_cfg(tmp_path), nodes, edges, stats)
        added = [edge for edge in out if edge.get("safe_division") == 1]
        assert added == [], name
        assert stats["safe_division_geometric_candidates"] == 1, name
        assert stats["safe_division_mutual_nn_rejected"] == 0, name
        assert stats["safe_division_divergence_rejected"] == 1, name
        assert stats["safe_division_candidates"] == 0, name


def test_e23_divergence_exact_threshold_accepted_below_rejected(tmp_path: Path):
    sister_um = 4.0 * 0.40625  # C y=8, B y=12
    boundary_voxels = (sister_um + 2.25) / 0.40625  # E offset from D for exactly 2.25 um growth

    nodes, edges = _division_frame()
    nodes[6] = _node(6, 3, y=16.0 + boundary_voxels)
    stats = new_stats()
    add_safe_divisions_postlink(_e23_cfg(tmp_path), nodes, edges, stats)
    assert stats["safe_divisions_added"] == 1
    assert stats["safe_division_divergence_rejected"] == 0

    nodes, edges = _division_frame()
    nodes[6] = _node(6, 3, y=16.0 + boundary_voxels - 0.02)  # growth 2.241875 um
    stats = new_stats()
    add_safe_divisions_postlink(_e23_cfg(tmp_path), nodes, edges, stats)
    assert stats["safe_divisions_added"] == 0
    assert stats["safe_division_divergence_rejected"] == 1


def test_e23_deepcenter_veto_runs_before_divergence(tmp_path: Path, monkeypatch):
    # The candidate also fails C3 (no successors); a divergence-first order
    # would count divergence_rejected and never reach DeepCenter.
    nodes, edges = _division_frame()
    for node_id in (5, 6):
        del nodes[node_id]
    edges = [edge for edge in edges if edge["target_id"] not in (5, 6)]
    cfg = _e23_cfg(tmp_path, BIOHUB_DEEPCENTER_SAFE_DIV_VETO="1")

    calls: list[tuple[int, tuple[float, float, float]]] = []

    def reject_veto(cfg_, dataset_, t_, point_, bundle_, frame_cache_, dc_cache_, stats_, prefix_, threshold_):
        calls.append((t_, point_))
        stats_[f"deepcenter_{prefix_}_rejected"] += 1  # the real helper counts the rejection
        return False

    monkeypatch.setattr(divisions_module, "deepcenter_accept_repair_point", reject_veto)
    stats = new_stats()
    out = add_safe_divisions_postlink(cfg, nodes, edges, stats)
    assert calls == [(2, (0.0, 12.0, 0.0))]
    assert out == edges
    assert stats["safe_division_geometric_candidates"] == 1
    assert stats["safe_division_divergence_rejected"] == 0
    assert stats["safe_division_candidates"] == 0
    assert stats["deepcenter_safe_div_rejected"] == 1

    calls.clear()
    monkeypatch.setattr(divisions_module, "deepcenter_accept_repair_point", lambda *args: True)
    stats = new_stats()
    add_safe_divisions_postlink(cfg, nodes, edges, stats)
    assert stats["safe_division_divergence_rejected"] == 1  # veto passed, C3 still rejects
    assert stats["deepcenter_safe_div_rejected"] == 0
    assert stats["safe_divisions_added"] == 0


def test_e23_counter_conservation_across_all_gate_paths(tmp_path: Path, monkeypatch):
    # One frame exercises all four geometric-candidate outcomes: accepted
    # (cluster 3), mutual-NN rejected (cluster 1's near orphan X),
    # DeepCenter rejected (cluster 1's mutual orphan B1), and divergence
    # rejected (cluster 2). Every candidate that passes the existing-edge
    # and distance gates must land in exactly one bucket:
    #
    #   safe_division_geometric_candidates
    #     == safe_division_mutual_nn_rejected
    #      + deepcenter_safe_div_rejected
    #      + safe_division_divergence_rejected
    #      + safe_division_candidates
    nodes = {
        1: _node(1, 0, y=0.0),
        2: _node(2, 1, y=0.0),      # P1
        3: _node(3, 2, y=8.0),      # C1
        4: _node(4, 2, y=12.0),     # B1: C1 mutual NN, vetoed by DeepCenter
        5: _node(5, 2, y=13.0),     # X: in P1 ball, not C1's mutual NN
        7: _node(7, 0, y=60.0),
        8: _node(8, 1, y=60.0),     # P2
        9: _node(9, 2, y=68.0),     # C2: no t+2 successor
        10: _node(10, 2, y=72.0),   # B2: C2 mutual NN, divergence fails
        13: _node(13, 0, y=120.0),
        14: _node(14, 1, y=120.0),  # P3
        15: _node(15, 2, y=128.0),  # C3
        16: _node(16, 2, y=132.0),  # B3: C3 mutual NN, passes every gate
        17: _node(17, 3, y=136.0),
        18: _node(18, 3, y=148.0),
    }
    edges = [
        {"source_id": 1, "target_id": 2},
        {"source_id": 2, "target_id": 3},
        {"source_id": 7, "target_id": 8},
        {"source_id": 8, "target_id": 9},
        {"source_id": 13, "target_id": 14},
        {"source_id": 14, "target_id": 15},
        {"source_id": 15, "target_id": 17},
        {"source_id": 16, "target_id": 18},
    ]
    cfg = _e23_cfg(tmp_path, BIOHUB_DEEPCENTER_SAFE_DIV_VETO="1")

    def veto_cluster_one(cfg_, dataset_, t_, point_, bundle_, frame_cache_, dc_cache_, stats_, prefix_, threshold_):
        # Like the real helper, a rejecting call increments the DeepCenter
        # rejection counter before returning False.
        if point_[1] == 12.0:  # B1
            stats_[f"deepcenter_{prefix_}_rejected"] += 1
            return False
        return True

    monkeypatch.setattr(divisions_module, "deepcenter_accept_repair_point", veto_cluster_one)
    stats = new_stats()
    out = add_safe_divisions_postlink(cfg, nodes, edges, stats)

    added = [(edge["source_id"], edge["target_id"]) for edge in out if edge.get("safe_division") == 1]
    assert added == [(14, 16)]
    assert stats["safe_division_geometric_candidates"] == 4
    assert stats["safe_division_mutual_nn_rejected"] == 1   # X
    assert stats["deepcenter_safe_div_rejected"] == 1       # B1
    assert stats["safe_division_divergence_rejected"] == 1  # B2
    assert stats["safe_division_candidates"] == 1           # B3
    assert stats["safe_divisions_added"] == 1
    assert stats["safe_division_geometric_candidates"] == (
        stats["safe_division_mutual_nn_rejected"]
        + stats["deepcenter_safe_div_rejected"]
        + stats["safe_division_divergence_rejected"]
        + stats["safe_division_candidates"]
    )


def _two_parent_two_orphan_graph() -> tuple[dict[int, dict[str, object]], list[dict[str, object]]]:
    # Two fully valid structural proposals in one frame: (P1 -> B1) scores
    # 5.11875, (P2 -> B2) scores 6.053125.
    nodes = {
        1: _node(1, 0, y=0.0),
        2: _node(2, 1, y=0.0),
        3: _node(3, 2, y=8.0),
        4: _node(4, 2, y=12.0),
        5: _node(5, 3, y=16.0),
        6: _node(6, 3, y=28.0),
        7: _node(7, 0, y=30.0),
        8: _node(8, 1, y=30.0),
        9: _node(9, 2, y=38.0),
        10: _node(10, 2, y=44.0),
        11: _node(11, 3, y=46.0),
        12: _node(12, 3, y=58.0),
    }
    edges = [
        {"source_id": 1, "target_id": 2},
        {"source_id": 2, "target_id": 3},
        {"source_id": 3, "target_id": 5},
        {"source_id": 4, "target_id": 6},
        {"source_id": 7, "target_id": 8},
        {"source_id": 8, "target_id": 9},
        {"source_id": 9, "target_id": 11},
        {"source_id": 10, "target_id": 12},
    ]
    return nodes, edges


def test_e23_frame_cap_adds_only_the_best_proposal(tmp_path: Path):
    nodes, edges = _two_parent_two_orphan_graph()
    cfg = _e23_cfg(tmp_path, BIOHUB_SAFE_DIV_FRAME_FRAC_CAP="0.4", BIOHUB_SAFE_DIV_GLOBAL_FRAC_CAP="1.0")
    stats = new_stats()

    out = add_safe_divisions_postlink(cfg, nodes, edges, stats)

    added = [edge for edge in out if edge.get("safe_division") == 1]
    assert [(edge["source_id"], edge["target_id"]) for edge in added] == [(2, 4)]
    assert stats["safe_division_candidates"] == 2
    assert stats["safe_divisions_added"] == 1
    assert stats["safe_division_skipped_cap"] == 0


def test_e23_global_cap_counts_skipped_proposals(tmp_path: Path):
    nodes, edges = _two_parent_two_orphan_graph()
    cfg = _e23_cfg(tmp_path, BIOHUB_SAFE_DIV_FRAME_FRAC_CAP="1.0", BIOHUB_SAFE_DIV_GLOBAL_FRAC_CAP="0.1")
    stats = new_stats()

    out = add_safe_divisions_postlink(cfg, nodes, edges, stats)

    added = [edge for edge in out if edge.get("safe_division") == 1]
    assert [(edge["source_id"], edge["target_id"]) for edge in added] == [(2, 4)]
    assert stats["safe_divisions_added"] == 1
    assert stats["safe_division_skipped_cap"] == 1


def test_e23_used_target_conflict_adds_the_orphan_once(tmp_path: Path):
    # One shared orphan B; both parents pass every gate. The better-scoring
    # proposal wins B; the loser is skipped by the used-target conflict
    # check, not by a cap.
    nodes = {
        1: _node(1, 0, y=0.0),
        2: _node(2, 1, y=0.0),
        3: _node(3, 2, y=8.0),
        4: _node(4, 0, y=4.0),
        5: _node(5, 1, y=4.0),
        6: _node(6, 2, y=10.0),
        7: _node(7, 2, y=12.0),
        8: _node(8, 3, y=16.0),
        9: _node(9, 3, y=18.0),
        10: _node(10, 3, y=28.0),
    }
    edges = [
        {"source_id": 1, "target_id": 2},
        {"source_id": 2, "target_id": 3},
        {"source_id": 4, "target_id": 5},
        {"source_id": 5, "target_id": 6},
        {"source_id": 3, "target_id": 8},
        {"source_id": 6, "target_id": 9},
        {"source_id": 7, "target_id": 10},
    ]
    stats = new_stats()

    out = add_safe_divisions_postlink(_e23_cfg(tmp_path), nodes, edges, stats)

    added = [edge for edge in out if edge.get("safe_division") == 1]
    assert [(edge["source_id"], edge["target_id"]) for edge in added] == [(5, 7)]
    assert stats["safe_division_candidates"] == 2
    assert stats["safe_divisions_added"] == 1
    assert stats["safe_division_skipped_cap"] == 0


def test_legacy_safe_division_output_order_stats_and_inert_flags(tmp_path: Path):
    # Track-start parent, non-mutual orphan, no t+2 successors: every E23
    # structural gate would reject this fork, but legacy mode keeps pure
    # distance semantics and the structural flags must stay inert.
    nodes = {1: _node(1, 0, y=0.0), 2: _node(2, 1, y=8.0), 3: _node(3, 1, y=12.0)}
    edges = [{"source_id": 1, "target_id": 2}]
    radii = {
        "BIOHUB_SAFE_DIV_MAX_UM": "8.0",
        "BIOHUB_SAFE_DIV_SISTER_MAX_UM": "11.0",
        "BIOHUB_SAFE_DIV_EXISTING_CHILD_MAX_UM": "10.0",
    }

    cfg_off = _cfg(tmp_path, BIOHUB_OUTPUT_SAFE_DIVISIONS="1", **radii)
    assert cfg_off.SAFE_DIV_MODE == "legacy"
    stats_off = new_stats()
    out_off = add_safe_divisions_postlink(cfg_off, nodes, edges, stats_off)

    assert out_off == edges + [
        {"source_id": 1, "target_id": 3, "edge_prob": None, "distance_um": 4.875, "safe_division": 1}
    ]
    assert stats_off["safe_division_candidates"] == 1
    assert stats_off["safe_divisions_added"] == 1
    assert stats_off["safe_division_skipped_cap"] == 0
    assert stats_off["safe_division_geometric_candidates"] == 0
    assert stats_off["safe_division_mutual_nn_rejected"] == 0
    assert stats_off["safe_division_divergence_rejected"] == 0

    flags = {
        "BIOHUB_SAFE_DIV_REQUIRE_MID_TRACK_PARENT": "1",
        "BIOHUB_SAFE_DIV_REQUIRE_MUTUAL_NN": "1",
        "BIOHUB_SAFE_DIV_REQUIRE_DIVERGENCE": "1",
    }
    cfg_on = _cfg(tmp_path, BIOHUB_OUTPUT_SAFE_DIVISIONS="1", **radii, **flags)
    stats_on = new_stats()
    out_on = add_safe_divisions_postlink(cfg_on, nodes, edges, stats_on)
    assert out_on == out_off
    assert stats_on == stats_off


def test_structural_safe_div_config_names_exact_and_old_keys_rejected():
    from biohub.public_postproc.config import CODE_DEFAULTS, config_field_names

    for key in (
        "BIOHUB_SAFE_DIV_MODE",
        "BIOHUB_SAFE_DIV_REQUIRE_MID_TRACK_PARENT",
        "BIOHUB_SAFE_DIV_REQUIRE_MUTUAL_NN",
        "BIOHUB_SAFE_DIV_REQUIRE_DIVERGENCE",
        "BIOHUB_SAFE_DIV_DIVERGE_UM",
    ):
        assert key in CODE_DEFAULTS
    for name in (
        "SAFE_DIV_MODE",
        "SAFE_DIV_REQUIRE_MID_TRACK_PARENT",
        "SAFE_DIV_REQUIRE_MUTUAL_NN",
        "SAFE_DIV_REQUIRE_DIVERGENCE",
        "SAFE_DIV_DIVERGE_UM",
    ):
        assert name in config_field_names()

    base1 = build_config()
    assert base1.SAFE_DIV_MODE == "legacy"
    assert base1.SAFE_DIV_REQUIRE_MID_TRACK_PARENT is False
    assert base1.SAFE_DIV_REQUIRE_MUTUAL_NN is False
    assert base1.SAFE_DIV_REQUIRE_DIVERGENCE is False
    assert base1.SAFE_DIV_DIVERGE_UM == 2.25
    assert not hasattr(base1, "SAFE_DIV_MUTUAL_NN")
    assert not hasattr(base1, "SAFE_DIV_DIVERGENCE")

    e23 = build_config(profile="e23")
    assert e23.SAFE_DIV_MODE == "e23"
    assert e23.SAFE_DIV_REQUIRE_MID_TRACK_PARENT is True
    assert e23.SAFE_DIV_REQUIRE_MUTUAL_NN is True
    assert e23.SAFE_DIV_REQUIRE_DIVERGENCE is True
    assert e23.SAFE_DIV_DIVERGE_UM == 2.25

    for old_key in ("BIOHUB_SAFE_DIV_MUTUAL_NN", "BIOHUB_SAFE_DIV_DIVERGENCE"):
        with pytest.raises(KeyError, match="unknown BIOHUB_"):
            build_config({old_key: "1"})


# --------------------------------------------------------------------------
# E23 Phase 4: exact DeepCenter gap-veto parity (pub923_repro routing table)
# --------------------------------------------------------------------------
# Physical scale is (z, y, x) = (1.625, 0.40625, 0.40625) um/voxel
# (biohub.io.DEFAULT_SCALE); every span below runs along x with z == y == 0,
# so span_um == delta_x_vox * 0.40625. The gap=1 candidate gate is
# GAP_CLOSE_UM * 2 = 12.0 um, so the 8.0/8.5/10.0 um spans are all feasible.
_UM_PER_VOXEL_X = 0.40625
_GAP_NONMARGINAL_SPAN_VOX = 8.0 / _UM_PER_VOXEL_X  # 8.0 um < 8.5 um min span
_GAP_MARGINAL_SPAN_VOX = 10.0 / _UM_PER_VOXEL_X  # 10.0 um >= 8.5 um min span
_GAP_BOUNDARY_SPAN_VOX = 8.5 / _UM_PER_VOXEL_X  # exactly 8.5 um (marginal)


def _gap_cfg(tmp_path: Path, **overrides: str) -> PostprocConfig:
    """Gap close isolated with the E23 gate values: veto on, 0.25, 8.5 um."""
    env = {
        "BIOHUB_OUTPUT_GAP_CLOSE": "1",
        "BIOHUB_USE_DEEPCENTER_VETO": "1",
        "BIOHUB_DEEPCENTER_GAP_VETO": "1",
        "BIOHUB_DEEPCENTER_GAP_THRESHOLD": "0.25",
        "BIOHUB_DEEPCENTER_GAP_CONFIRM_MIN_SPAN_UM": "8.5",
    }
    env.update(overrides)
    return _cfg(tmp_path, **env)


def _gap_graph(
    span_voxels: float,
    *,
    observed_middle: bool = False,
) -> tuple[dict[int, dict[str, object]], list[dict[str, object]]]:
    """One t0->t2 gap pair along x plus a far dummy edge (the gate requires
    at least one edge). With ``observed_middle`` an isolated t1 node sits
    exactly on the midpoint, so GAP_CLOSE_REUSE_EXISTING reuses it; otherwise
    the middle must be synthesized. The first synthetic ID is 9."""
    nodes = {
        1: _node(1, 0, x=0.0),
        2: _node(2, 2, x=span_voxels),
        7: _node(7, 10, x=2000.0),
        8: _node(8, 11, x=2000.0),
    }
    if observed_middle:
        nodes[3] = _node(3, 1, x=span_voxels / 2.0)
    edges = [{"source_id": 7, "target_id": 8, "edge_prob": 1.0}]
    return nodes, edges


def _install_gap_dc_spy(monkeypatch, accept: Callable[[int], bool]) -> list[dict[str, object]]:
    """Replace the gate helper where graph_ops looks it up. The spy keeps the
    real helper's telemetry contract: a scored call increments
    ``deepcenter_gap_checked`` and exactly one of accepted/rejected."""
    calls: list[dict[str, object]] = []

    def spy(cfg_, dataset_, t_, point_, bundle_, frame_cache_, dc_cache_, stats_, prefix_, threshold_):
        calls.append({"t": int(t_), "point": point_, "prefix": prefix_, "threshold": threshold_})
        stats_[f"deepcenter_{prefix_}_checked"] += 1
        if accept(int(t_)):
            stats_[f"deepcenter_{prefix_}_accepted"] += 1
            return True
        stats_[f"deepcenter_{prefix_}_rejected"] += 1
        return False

    monkeypatch.setattr(graph_ops_module, "deepcenter_accept_repair_point", spy)
    return calls


def _install_gap_refine_spy(monkeypatch) -> list[tuple[int, tuple[float, float, float]]]:
    """Replace refine_synthetic_midpoint where graph_ops looks it up; like the
    real successful path it counts one refinement per insertion attempt."""
    calls: list[tuple[int, tuple[float, float, float]]] = []

    def spy(cfg_, dataset_, t_, midpoint_, frame_cache_, stats_):
        calls.append((int(t_), midpoint_))
        stats_["gap_refined_synthetic"] += 1
        return midpoint_

    monkeypatch.setattr(graph_ops_module, "refine_synthetic_midpoint", spy)
    return calls


def test_e23_gap_quadrant_observed_nonmarginal_bypasses_strong_motion(tmp_path: Path, monkeypatch):
    # Reused (observed) middle, span < 8.5 um: count strong motion, no model.
    cfg = _gap_cfg(tmp_path)
    nodes, edges = _gap_graph(_GAP_NONMARGINAL_SPAN_VOX, observed_middle=True)
    calls = _install_gap_dc_spy(monkeypatch, accept=lambda t: True)
    stats = new_stats()
    out_nodes, out_edges = close_single_frame_gaps(cfg, nodes, edges, stats)

    assert calls == []
    assert stats["deepcenter_gap_bypassed_strong_motion"] == 1
    assert stats["deepcenter_gap_bypassed_observed_node"] == 0
    assert stats["deepcenter_gap_checked"] == 0
    assert stats["gap_reused_existing"] == 1
    assert stats["gap_pairs_selected"] == 1
    assert stats["gap_inserted_synthetic"] == 0
    assert int(out_nodes[3].get("gap_synthetic", 0)) != 1  # stays observed
    pairs = {(int(e["source_id"]), int(e["target_id"])) for e in out_edges}
    assert {(1, 3), (3, 2)} <= pairs and len(out_edges) == 3


def test_e23_gap_quadrant_observed_marginal_bypasses_observed_node(tmp_path: Path, monkeypatch):
    # Reused (observed) middle, span >= 8.5 um: count observed_node, no model.
    cfg = _gap_cfg(tmp_path)
    nodes, edges = _gap_graph(_GAP_MARGINAL_SPAN_VOX, observed_middle=True)
    calls = _install_gap_dc_spy(monkeypatch, accept=lambda t: True)
    stats = new_stats()
    out_nodes, out_edges = close_single_frame_gaps(cfg, nodes, edges, stats)

    assert calls == []
    assert stats["deepcenter_gap_bypassed_observed_node"] == 1
    assert stats["deepcenter_gap_bypassed_strong_motion"] == 0
    assert stats["deepcenter_gap_checked"] == 0
    assert stats["gap_reused_existing"] == 1
    assert stats["gap_pairs_selected"] == 1
    assert stats["gap_inserted_synthetic"] == 0
    assert int(out_nodes[3].get("gap_synthetic", 0)) != 1  # stays observed
    pairs = {(int(e["source_id"]), int(e["target_id"])) for e in out_edges}
    assert {(1, 3), (3, 2)} <= pairs and len(out_edges) == 3


def test_e23_gap_quadrant_synthetic_nonmarginal_bypasses_strong_motion(tmp_path: Path, monkeypatch):
    # Synthetic middle, span < 8.5 um: count strong motion, no model.
    cfg = _gap_cfg(tmp_path)
    nodes, edges = _gap_graph(_GAP_NONMARGINAL_SPAN_VOX)
    calls = _install_gap_dc_spy(monkeypatch, accept=lambda t: True)
    stats = new_stats()
    out_nodes, out_edges = close_single_frame_gaps(cfg, nodes, edges, stats)

    assert calls == []
    assert stats["deepcenter_gap_bypassed_strong_motion"] == 1
    assert stats["deepcenter_gap_bypassed_observed_node"] == 0
    assert stats["deepcenter_gap_checked"] == 0
    assert stats["gap_reused_existing"] == 0
    assert stats["gap_inserted_synthetic"] == 1
    assert stats["gap_added_nodes"] == 1
    assert int(out_nodes[9]["gap_synthetic"]) == 1
    pairs = {(int(e["source_id"]), int(e["target_id"])) for e in out_edges}
    assert {(1, 9), (9, 2)} <= pairs and len(out_edges) == 3


def test_e23_gap_quadrant_synthetic_marginal_queries_deepcenter(tmp_path: Path, monkeypatch):
    # Synthetic middle, span >= 8.5 um: exactly one model call at the E23
    # threshold; both bypass counters stay zero.
    cfg = _gap_cfg(tmp_path)
    nodes, edges = _gap_graph(_GAP_MARGINAL_SPAN_VOX)
    calls = _install_gap_dc_spy(monkeypatch, accept=lambda t: True)
    stats = new_stats()
    out_nodes, out_edges = close_single_frame_gaps(cfg, nodes, edges, stats)

    assert len(calls) == 1
    assert calls[0]["t"] == 1
    assert calls[0]["prefix"] == "gap"
    assert calls[0]["threshold"] == 0.25 == cfg.DEEPCENTER_GAP_THRESHOLD
    assert stats["deepcenter_gap_bypassed_strong_motion"] == 0
    assert stats["deepcenter_gap_bypassed_observed_node"] == 0
    assert stats["deepcenter_gap_checked"] == 1
    assert stats["deepcenter_gap_accepted"] == 1
    assert stats["deepcenter_gap_rejected"] == 0
    assert stats["gap_reused_existing"] == 0
    assert stats["gap_inserted_synthetic"] == 1
    assert int(out_nodes[9]["gap_synthetic"]) == 1
    pairs = {(int(e["source_id"]), int(e["target_id"])) for e in out_edges}
    assert {(1, 9), (9, 2)} <= pairs and len(out_edges) == 3


def test_e23_gap_veto_disabled_changes_nothing_but_repairs(tmp_path: Path, monkeypatch):
    # Gate off: no model call and none of the three routing/bypass counters
    # moves, across both node kinds and both span classes in one call, while
    # both valid repairs still land.
    cfg = _gap_cfg(tmp_path, BIOHUB_DEEPCENTER_GAP_VETO="0")
    nodes = {
        1: _node(1, 0, x=0.0),
        2: _node(2, 2, x=_GAP_NONMARGINAL_SPAN_VOX),  # pair A: synthetic, nonmarginal
        3: _node(3, 4, x=400.0),
        4: _node(4, 6, x=400.0 + _GAP_MARGINAL_SPAN_VOX),  # pair B: marginal
        5: _node(5, 5, x=400.0 + _GAP_MARGINAL_SPAN_VOX / 2.0),  # observed middle for B
        7: _node(7, 10, x=2000.0),
        8: _node(8, 11, x=2000.0),
    }
    edges = [{"source_id": 7, "target_id": 8, "edge_prob": 1.0}]
    calls = _install_gap_dc_spy(monkeypatch, accept=lambda t: True)
    stats = new_stats()
    out_nodes, out_edges = close_single_frame_gaps(cfg, nodes, edges, stats)

    assert calls == []
    assert stats["deepcenter_gap_checked"] == 0
    assert stats["deepcenter_gap_accepted"] == 0
    assert stats["deepcenter_gap_rejected"] == 0
    assert stats["deepcenter_gap_missing"] == 0
    assert stats["deepcenter_gap_bypassed_strong_motion"] == 0
    assert stats["deepcenter_gap_bypassed_observed_node"] == 0
    assert stats["gap_pairs_selected"] == 2
    assert stats["gap_added_edges"] == 4
    assert stats["gap_inserted_synthetic"] == 1  # pair A
    assert stats["gap_added_nodes"] == 1
    assert stats["gap_reused_existing"] == 1  # pair B
    assert int(out_nodes[9]["gap_synthetic"]) == 1
    assert int(out_nodes[5].get("gap_synthetic", 0)) != 1
    pairs = {(int(e["source_id"]), int(e["target_id"])) for e in out_edges}
    assert {(1, 9), (9, 2), (3, 5), (5, 4)} <= pairs and len(out_edges) == 5


def test_e23_gap_span_exact_boundary_is_marginal(tmp_path: Path, monkeypatch):
    # 8.5 / 0.40625 voxels of x is exactly the 8.5 um min-span boundary and
    # must take the marginal route for both node kinds.
    assert point_distance_um((0.0, 0.0, 0.0), (0.0, 0.0, _GAP_BOUNDARY_SPAN_VOX)) == 8.5
    cfg = _gap_cfg(tmp_path)

    # Synthetic middle at exactly 8.5 um: routed to DeepCenter.
    calls = _install_gap_dc_spy(monkeypatch, accept=lambda t: True)
    nodes, edges = _gap_graph(_GAP_BOUNDARY_SPAN_VOX)
    stats = new_stats()
    out_nodes, out_edges = close_single_frame_gaps(cfg, nodes, edges, stats)
    assert len(calls) == 1
    assert calls[0]["t"] == 1 and calls[0]["threshold"] == 0.25
    assert stats["deepcenter_gap_bypassed_strong_motion"] == 0
    assert stats["deepcenter_gap_bypassed_observed_node"] == 0
    assert stats["gap_pairs_selected"] == 1
    assert int(out_nodes[9]["gap_synthetic"]) == 1

    # Observed middle at exactly 8.5 um: marginal observed bypass, no model.
    calls = _install_gap_dc_spy(monkeypatch, accept=lambda t: True)
    nodes, edges = _gap_graph(_GAP_BOUNDARY_SPAN_VOX, observed_middle=True)
    stats = new_stats()
    out_nodes, out_edges = close_single_frame_gaps(cfg, nodes, edges, stats)
    assert calls == []
    assert stats["deepcenter_gap_bypassed_observed_node"] == 1
    assert stats["deepcenter_gap_bypassed_strong_motion"] == 0
    assert stats["gap_pairs_selected"] == 1
    assert int(out_nodes[3].get("gap_synthetic", 0)) != 1


def test_e23_deepcenter_gap_threshold_exact_boundary(tmp_path: Path, monkeypatch):
    # The production comparator is the strict ``score < threshold`` inside the
    # real ``deepcenter_accept_repair_point`` (only the model call is
    # stubbed): prove it at 0.25 and at both adjacent floats.
    _install_gap_refine_spy(monkeypatch)
    for score, want_accept in (
        (np.nextafter(0.25, -np.inf), False),
        (0.25, True),
        (np.nextafter(0.25, np.inf), True),
    ):
        monkeypatch.setattr(
            deepcenter_module, "deepcenter_score_point", lambda *_args, _score=score: _score
        )
        cfg = _gap_cfg(tmp_path)
        nodes, edges = _gap_graph(_GAP_MARGINAL_SPAN_VOX)
        stats = new_stats()
        out_nodes, out_edges = close_single_frame_gaps(
            cfg, nodes, edges, stats, dataset="ds0", deepcenter_bundle={"stub": True}
        )
        assert stats["deepcenter_gap_checked"] == 1
        assert stats["deepcenter_gap_missing"] == 0
        if want_accept:
            assert stats["deepcenter_gap_accepted"] == 1
            assert stats["deepcenter_gap_rejected"] == 0
            assert stats["gap_pairs_selected"] == 1
            assert 9 in out_nodes and int(out_nodes[9]["gap_synthetic"]) == 1
            assert len(out_edges) == 3
        else:
            assert stats["deepcenter_gap_accepted"] == 0
            assert stats["deepcenter_gap_rejected"] == 1
            assert stats["gap_pairs_selected"] == 0
            assert 9 not in out_nodes  # rejected node rolled back
            assert len(out_edges) == 1  # only the dummy edge survives


def test_e23_gap_veto_rejection_restores_cap_and_consumes_id(tmp_path: Path, monkeypatch):
    # Deterministic cap-one transaction with a source overlap: pair (1, 2) is
    # vetoed at its t=1 midpoint, then the rejected pair's target 2 is reused
    # as the source of pair (2, 3), whose t=3 midpoint is accepted. The
    # absolute cap (1) is binding, so the accepted insertion only happens if
    # the rejection restores synthetic_added, and the accepted ID must skip
    # the consumed rejected ID. Both distinct spans (9.0 vs 10.0 um) sit
    # inside the 12.0 um gate and above the 8.5 um marginal boundary.
    s = 0.40625
    assert point_distance_um((0.0, 0.0, 0.0), (0.0, 0.0, 9.0 / s)) == 9.0
    assert point_distance_um((0.0, 0.0, 9.0 / s), (0.0, 0.0, 19.0 / s)) == 10.0
    cfg = _gap_cfg(
        tmp_path,
        BIOHUB_GAP_CLOSE_MAX_ADDED_ABS="1",
        BIOHUB_GAP_CLOSE_MAX_ADDED_FRAC="1.0",
    )
    nodes = {
        1: _node(1, 0, x=0.0),
        2: _node(2, 2, x=9.0 / s),
        3: _node(3, 4, x=19.0 / s),
        6: _node(6, 9, x=2000.0),
        7: _node(7, 10, x=2000.0),
        8: _node(8, 11, x=2000.0),
    }
    original_edges = [
        {"source_id": 7, "target_id": 8, "edge_prob": 0.71},
        {"source_id": 6, "target_id": 7, "edge_prob": 0.62},
    ]
    refine_calls = _install_gap_refine_spy(monkeypatch)
    dc_calls = _install_gap_dc_spy(monkeypatch, accept=lambda t: t != 1)  # veto mid t=1
    stats = new_stats()
    out_nodes, out_edges = close_single_frame_gaps(cfg, nodes, original_edges, stats)

    # Both attempts refined and checked, rejected midpoint t=1 first.
    assert [t for t, _ in refine_calls] == [1, 3]
    assert [call["t"] for call in dc_calls] == [1, 3]
    assert stats["gap_refined_synthetic"] == 2  # rejected attempt keeps its event
    assert stats["deepcenter_gap_checked"] == 2
    assert stats["deepcenter_gap_rejected"] == 1
    assert stats["deepcenter_gap_accepted"] == 1
    assert stats["deepcenter_gap_missing"] == 0
    assert stats["deepcenter_gap_bypassed_strong_motion"] == 0
    assert stats["deepcenter_gap_bypassed_observed_node"] == 0

    # Rejected node and its two proposed edges are gone: source 1 and its
    # target 2 keep no rejected repair edge, while 2 is reused as the accepted
    # repair's source. The accepted repair skips the consumed ID (10 == 9+1).
    assert 9 not in out_nodes
    assert 10 in out_nodes and int(out_nodes[10]["gap_synthetic"]) == 1
    assert 10 == 9 + 1
    pairs = {(int(e["source_id"]), int(e["target_id"])) for e in out_edges}
    assert (1, 9) not in pairs and (9, 2) not in pairs
    assert (2, 10) in pairs and (10, 3) in pairs

    # Telemetry and caps reflect only the accepted repair.
    assert stats["gap_inserted_synthetic"] == 1
    assert stats["gap_added_nodes"] == 1
    assert stats["gap_added_edges"] == 2
    assert stats["gap_pairs_selected"] == 1
    assert stats["gap_reused_existing"] == 0
    assert stats["gap_skipped_node_cap"] == 0  # restored cap served candidate 2

    # Exact append order: the two original edges verbatim in their original
    # order, then (2, 10) and (10, 3), each accepted edge with its complete
    # dictionary and exactly half the 10.0 um span.
    assert out_edges == [
        {"source_id": 7, "target_id": 8, "edge_prob": 0.71},
        {"source_id": 6, "target_id": 7, "edge_prob": 0.62},
        {
            "source_id": 2,
            "target_id": 10,
            "edge_prob": None,
            "distance_um": 5.0,
            "gap_closed": 1,
        },
        {
            "source_id": 10,
            "target_id": 3,
            "edge_prob": None,
            "distance_um": 5.0,
            "gap_closed": 1,
        },
    ]
    assert out_edges[2]["distance_um"] == 5.0
    assert out_edges[3]["distance_um"] == 5.0


def test_e23_gap_veto_missing_bundle_fails_open(tmp_path: Path, monkeypatch):
    # USE_DEEPCENTER_VETO fail-open is separate from the gap gate: with veto
    # enabled and no detector bundle, the marginal synthetic repair still
    # lands, counted as missing with no checked/accepted/rejected/bypass.
    cfg = _gap_cfg(tmp_path)
    refine_calls = _install_gap_refine_spy(monkeypatch)
    nodes, edges = _gap_graph(_GAP_MARGINAL_SPAN_VOX)
    stats = new_stats()
    out_nodes, out_edges = close_single_frame_gaps(
        cfg, nodes, edges, stats, dataset="ds0", deepcenter_bundle=None
    )

    assert [t for t, _ in refine_calls] == [1]
    assert stats["deepcenter_gap_missing"] == 1
    assert stats["deepcenter_gap_checked"] == 0
    assert stats["deepcenter_gap_accepted"] == 0
    assert stats["deepcenter_gap_rejected"] == 0
    assert stats["deepcenter_gap_bypassed_strong_motion"] == 0
    assert stats["deepcenter_gap_bypassed_observed_node"] == 0
    assert stats["gap_pairs_selected"] == 1
    assert stats["gap_inserted_synthetic"] == 1
    assert 9 in out_nodes and int(out_nodes[9]["gap_synthetic"]) == 1
    pairs = {(int(e["source_id"]), int(e["target_id"])) for e in out_edges}
    assert {(1, 9), (9, 2)} <= pairs and len(out_edges) == 3


def test_stats_schema_uses_observed_node_bypass_name():
    stats = new_stats()
    assert "deepcenter_gap_bypassed_observed_node" in stats
    assert stats["deepcenter_gap_bypassed_observed_node"] == 0
    # No schema key may keep the stale pre-Phase-4 synthetic-node suffix.
    assert not any(key.endswith("synthetic_node") for key in stats)


# --------------------------------------------------------------------------
# ST-R1a: frozen twin-only config and strict DeepCenter adapter
# --------------------------------------------------------------------------
_STEAL_TWIN_R1A_DEFAULTS = {
    "OUTPUT_STEAL_TWIN_REWIRE": False,
    "STEAL_TWIN_MODE": "twin_only_v1",
    "STEAL_TWIN_DRY_RUN": False,
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
    "STEAL_TWIN_DEBUG_JSONL": "",
    "STEAL_TWIN_DEBUG_MAX_RECORDS": 200,
}


def test_steal_twin_r1a_exact_defaults_profile_and_diff_whitelist():
    from dataclasses import fields

    base1 = build_config(profile="base1")
    e23 = build_config(profile="e23")
    candidate = build_config(profile="e23_twin_only_v1")
    for name, expected in _STEAL_TWIN_R1A_DEFAULTS.items():
        assert getattr(base1, name) == expected
        assert getattr(e23, name) == expected

    candidate_expected = {
        **_STEAL_TWIN_R1A_DEFAULTS,
        "OUTPUT_STEAL_TWIN_REWIRE": True,
    }
    for name, expected in candidate_expected.items():
        assert getattr(candidate, name) == expected
    assert candidate.EXPERIMENT_TAG == "e23_twin_only_v1"

    actual_diff = {
        field.name
        for field in fields(PostprocConfig)
        if getattr(candidate, field.name) != getattr(e23, field.name)
    }
    allowed = {*_STEAL_TWIN_R1A_DEFAULTS, "EXPERIMENT_TAG"}
    assert actual_diff <= allowed
    assert {"OUTPUT_STEAL_TWIN_REWIRE", "EXPERIMENT_TAG"} <= actual_diff
    assert base1.EXPERIMENT_TAG == "biohub_132_clean_short_track_rescue_lightcv_nohack"
    assert e23.EXPERIMENT_TAG == "e23_pub923_parity"


def test_steal_twin_r1a_master_off_validation_is_inert():
    cfg = build_config(
        {
            "BIOHUB_STEAL_TWIN_MODE": "future_unknown_mode",
            "BIOHUB_STEAL_TWIN_PARENT_MAX_UM": "99.0",
            "BIOHUB_STEAL_TWIN_EXISTING_CHILD_MAX_UM": "98.0",
            "BIOHUB_STEAL_TWIN_SISTER_MIN_UM": "97.0",
            "BIOHUB_STEAL_TWIN_SISTER_MAX_UM": "96.0",
            "BIOHUB_STEAL_TWIN_DIVERGE_UM": "95.0",
            "BIOHUB_STEAL_TWIN_TWIN_MAX_UM": "94.0",
            "BIOHUB_STEAL_TWIN_REQUIRE_TWO_SUCCESSORS": "0",
            "BIOHUB_STEAL_TWIN_REJECT_SYNTHETIC": "0",
            "BIOHUB_STEAL_TWIN_DEEPCENTER_VETO": "0",
            "BIOHUB_STEAL_TWIN_FRAME_CAP_ABS": "93",
            "BIOHUB_STEAL_TWIN_VIDEO_CAP_ABS": "92",
            "BIOHUB_STEAL_TWIN_DEBUG_MAX_RECORDS": "91",
        },
        profile="e23",
    )
    assert cfg.OUTPUT_STEAL_TWIN_REWIRE is False
    assert cfg.STEAL_TWIN_MODE == "future_unknown_mode"
    assert cfg.STEAL_TWIN_FRAME_CAP_ABS == 93


@pytest.mark.parametrize(
    ("name", "bad_value"),
    [
        ("BIOHUB_STEAL_TWIN_MODE", "off"),
        ("BIOHUB_STEAL_TWIN_PARENT_MAX_UM", "8.0001"),
        ("BIOHUB_STEAL_TWIN_EXISTING_CHILD_MAX_UM", "10.0001"),
        ("BIOHUB_STEAL_TWIN_SISTER_MIN_UM", "5.5001"),
        ("BIOHUB_STEAL_TWIN_SISTER_MAX_UM", "11.0001"),
        ("BIOHUB_STEAL_TWIN_DIVERGE_UM", "2.2501"),
        ("BIOHUB_STEAL_TWIN_TWIN_MAX_UM", "5.0001"),
        ("BIOHUB_STEAL_TWIN_REQUIRE_TWO_SUCCESSORS", "0"),
        ("BIOHUB_STEAL_TWIN_REJECT_SYNTHETIC", "0"),
        ("BIOHUB_STEAL_TWIN_DEEPCENTER_VETO", "0"),
        ("BIOHUB_STEAL_TWIN_FRAME_CAP_ABS", "0"),
        ("BIOHUB_STEAL_TWIN_VIDEO_CAP_ABS", "3"),
        ("BIOHUB_STEAL_TWIN_DEBUG_MAX_RECORDS", "201"),
    ],
)
def test_steal_twin_r1a_master_on_rejects_every_frozen_value_violation(name: str, bad_value: str):
    with pytest.raises(ValueError, match=name.removeprefix("BIOHUB_")):
        build_config({name: bad_value}, profile="e23_twin_only_v1")


def test_steal_twin_r1a_allows_only_dry_run_and_debug_path_operational_overrides(tmp_path: Path):
    debug_path = tmp_path / "twin.jsonl"
    cfg = build_config(
        {
            "BIOHUB_STEAL_TWIN_DRY_RUN": "1",
            "BIOHUB_STEAL_TWIN_DEBUG_JSONL": str(debug_path),
        },
        profile="e23_twin_only_v1",
    )
    assert cfg.STEAL_TWIN_DRY_RUN is True
    assert cfg.STEAL_TWIN_DEBUG_JSONL == str(debug_path)


def test_steal_twin_r1a_loader_bundle_exposes_verified_epoch(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace

    checkpoint_path = tmp_path / "checkpoint.pt"
    checkpoint_path.write_bytes(b"synthetic")

    class FakeModel:
        def load_state_dict(self, state):
            assert state == {"weight": "synthetic"}

        def to(self, device):
            assert device == "cpu"

        def eval(self):
            return None

    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False),
        device=lambda value: value,
        load=lambda *args, **kwargs: {
            "model_state": {"weight": "synthetic"},
            "epoch": 2,
            "config": {"pool_factor": 4},
        },
    )
    monkeypatch.setattr(deepcenter_module, "torch", fake_torch)
    monkeypatch.setattr(deepcenter_module, "_DCDeepCenterUNet3D", lambda **kwargs: FakeModel())
    monkeypatch.setattr(deepcenter_module, "_dc_checkpoint_candidates", lambda cfg: [checkpoint_path])

    bundle = deepcenter_module.load_deepcenter_veto_detector(build_config(profile="e23"))
    assert bundle is not None
    assert set(bundle) == {"model", "cfg", "device", "path", "torch", "checkpoint_epoch"}
    assert bundle["checkpoint_epoch"] == 2
    assert type(bundle["checkpoint_epoch"]) is int
    assert bundle["path"] == checkpoint_path


def _steal_twin_r1a_cfg(tmp_path: Path, **overrides: str) -> PostprocConfig:
    values = {"BIOHUB_STEAL_TWIN_DRY_RUN": "1", **overrides}
    return build_config(values, test_dir=tmp_path, profile="e23_twin_only_v1")


def _steal_twin_r1a_bundle(**overrides: object) -> dict[str, object]:
    from types import SimpleNamespace

    bundle: dict[str, object] = {
        "model": object(),
        "cfg": SimpleNamespace(pool_factor=1),
        "device": object(),
        "torch": object(),
        "path": Path("synthetic.pt"),
        "checkpoint_epoch": 2,
    }
    bundle.update(overrides)
    return bundle


def _steal_twin_r1a_score(
    tmp_path: Path,
    monkeypatch,
    *,
    bundle: dict[str, object] | None = None,
    dataset: str | None = "ds0",
    frame: object = None,
    heatmap: object = None,
):
    if frame is None:
        frame = np.ones((3, 5, 5), dtype=np.float32)
    if heatmap is None:
        heatmap = np.full((3, 5, 5), 0.12, dtype=np.float32)
    monkeypatch.setattr(divisions_module, "read_test_frame", lambda *args: frame)
    monkeypatch.setattr(divisions_module, "deepcenter_heatmap_for_frame", lambda *args: heatmap)
    return divisions_module.score_twin_deepcenter(
        _steal_twin_r1a_cfg(tmp_path),
        dataset,
        4,
        (1.0, 2.0, 2.0),
        _steal_twin_r1a_bundle() if bundle is None else bundle,
        {},
        {},
    )


@pytest.mark.parametrize("missing_key", ["model", "cfg", "device", "torch", "path", "checkpoint_epoch"])
def test_steal_twin_r1a_rejects_each_missing_bundle_key(tmp_path: Path, monkeypatch, missing_key: str):
    bundle = _steal_twin_r1a_bundle()
    del bundle[missing_key]
    decision = _steal_twin_r1a_score(tmp_path, monkeypatch, bundle=bundle)
    assert decision == divisions_module.TwinDeepCenterDecision(False, None, "deepcenter_bundle")


@pytest.mark.parametrize("epoch", [True, 2.0, "2", 1, 3, None])
def test_steal_twin_r1a_rejects_invalid_epoch(tmp_path: Path, monkeypatch, epoch: object):
    decision = _steal_twin_r1a_score(
        tmp_path,
        monkeypatch,
        bundle=_steal_twin_r1a_bundle(checkpoint_epoch=epoch),
    )
    assert decision.reason == "deepcenter_bundle"
    assert decision.raw_score is None


@pytest.mark.parametrize("pool_factor", [None, "1", 1.0, True, 0, -1])
def test_steal_twin_r1a_rejects_invalid_pool_factor(tmp_path: Path, monkeypatch, pool_factor: object):
    from types import SimpleNamespace

    decision = _steal_twin_r1a_score(
        tmp_path,
        monkeypatch,
        bundle=_steal_twin_r1a_bundle(cfg=SimpleNamespace(pool_factor=pool_factor)),
    )
    assert decision.reason == "deepcenter_bundle"


def test_steal_twin_r1a_rejects_missing_pool_factor(tmp_path: Path, monkeypatch):
    decision = _steal_twin_r1a_score(tmp_path, monkeypatch, bundle=_steal_twin_r1a_bundle(cfg=object()))
    assert decision.reason == "deepcenter_bundle"


def test_steal_twin_r1a_rejects_when_global_or_twin_veto_is_off(tmp_path: Path):
    bundle = _steal_twin_r1a_bundle()
    global_off = build_config({"BIOHUB_USE_DEEPCENTER_VETO": "0"}, test_dir=tmp_path, profile="e23")
    twin_off = build_config({"BIOHUB_STEAL_TWIN_DEEPCENTER_VETO": "0"}, test_dir=tmp_path, profile="e23")
    for cfg in (global_off, twin_off):
        decision = divisions_module.score_twin_deepcenter(cfg, "ds0", 0, (0, 0, 0), bundle, {}, {})
        assert decision.reason == "deepcenter_bundle"


def test_steal_twin_r1a_bundle_and_dataset_reason_precedence(tmp_path: Path, monkeypatch):
    cfg = _steal_twin_r1a_cfg(tmp_path)
    assert divisions_module.score_twin_deepcenter(cfg, None, 0, (0, 0, 0), None, {}, {}).reason == "deepcenter_bundle"
    for dataset in (None, "", "   "):
        decision = divisions_module.score_twin_deepcenter(
            cfg,
            dataset,
            0,
            (0, 0, 0),
            _steal_twin_r1a_bundle(),
            {},
            {},
        )
        assert decision.reason == "deepcenter_dataset"


@pytest.mark.parametrize(
    ("frame", "reason"),
    [
        (np.array([], dtype=np.float32), "deepcenter_frame"),
        (np.ones((3, 5), dtype=np.float32), "deepcenter_frame"),
        (np.array([[np.nan]], dtype=np.float32), "deepcenter_nonfinite"),
        (np.array([[np.inf]], dtype=np.float32), "deepcenter_nonfinite"),
    ],
)
def test_steal_twin_r1a_frame_reason_map_and_nonfinite_precedence(tmp_path: Path, monkeypatch, frame, reason: str):
    decision = _steal_twin_r1a_score(tmp_path, monkeypatch, frame=frame)
    assert decision.reason == reason


def test_steal_twin_r1a_frame_read_exception_maps_to_frame(tmp_path: Path, monkeypatch):
    def fail(*args):
        raise OSError("synthetic read failure")

    monkeypatch.setattr(divisions_module, "read_test_frame", fail)
    decision = divisions_module.score_twin_deepcenter(
        _steal_twin_r1a_cfg(tmp_path), "ds0", 0, (0, 0, 0), _steal_twin_r1a_bundle(), {}, {}
    )
    assert decision.reason == "deepcenter_frame"


def test_steal_twin_r1a_missing_frame_maps_to_frame(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(divisions_module, "read_test_frame", lambda *args: None)
    decision = divisions_module.score_twin_deepcenter(
        _steal_twin_r1a_cfg(tmp_path), "ds0", 0, (0, 0, 0), _steal_twin_r1a_bundle(), {}, {}
    )
    assert decision.reason == "deepcenter_frame"


@pytest.mark.parametrize(
    ("heatmap", "reason"),
    [
        (np.array([], dtype=np.float32), "deepcenter_heatmap"),
        (np.ones((3, 5), dtype=np.float32), "deepcenter_heatmap"),
        (np.array([[np.nan]], dtype=np.float32), "deepcenter_nonfinite"),
        (np.array([[np.inf]], dtype=np.float32), "deepcenter_nonfinite"),
    ],
)
def test_steal_twin_r1a_heatmap_reason_map_and_nonfinite_precedence(
    tmp_path: Path, monkeypatch, heatmap, reason: str
):
    decision = _steal_twin_r1a_score(tmp_path, monkeypatch, heatmap=heatmap)
    assert decision.reason == reason


def test_steal_twin_r1a_inference_exception_and_out_of_bounds_map_to_heatmap(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(divisions_module, "read_test_frame", lambda *args: np.ones((3, 5, 5)))

    def fail(*args):
        raise RuntimeError("synthetic inference failure")

    monkeypatch.setattr(divisions_module, "deepcenter_heatmap_for_frame", fail)
    cfg = _steal_twin_r1a_cfg(tmp_path)
    bundle = _steal_twin_r1a_bundle()
    inference_failure = divisions_module.score_twin_deepcenter(cfg, "ds0", 0, (1, 2, 2), bundle, {}, {})
    assert inference_failure.reason == "deepcenter_heatmap"
    monkeypatch.setattr(divisions_module, "deepcenter_heatmap_for_frame", lambda *args: np.ones((3, 5, 5)))
    out_of_bounds = divisions_module.score_twin_deepcenter(cfg, "ds0", 0, (9, 2, 2), bundle, {}, {})
    assert out_of_bounds.reason == "deepcenter_heatmap"


def test_steal_twin_r1a_missing_heatmap_and_nonfinite_point_map_to_heatmap(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(divisions_module, "read_test_frame", lambda *args: np.ones((3, 5, 5)))
    cfg = _steal_twin_r1a_cfg(tmp_path)
    bundle = _steal_twin_r1a_bundle()
    monkeypatch.setattr(divisions_module, "deepcenter_heatmap_for_frame", lambda *args: None)
    missing = divisions_module.score_twin_deepcenter(cfg, "ds0", 0, (1, 2, 2), bundle, {}, {})
    assert missing.reason == "deepcenter_heatmap"
    monkeypatch.setattr(divisions_module, "deepcenter_heatmap_for_frame", lambda *args: np.ones((3, 5, 5)))
    nonfinite_point = divisions_module.score_twin_deepcenter(cfg, "ds0", 0, (np.nan, 2, 2), bundle, {}, {})
    assert nonfinite_point.reason == "deepcenter_heatmap"


@pytest.mark.parametrize(
    ("score", "accepted", "reason"),
    [
        (np.nextafter(0.12, -np.inf), False, "deepcenter_threshold"),
        (0.12, True, None),
        (np.nextafter(0.12, np.inf), True, None),
    ],
)
def test_steal_twin_r1a_fixed_threshold_adjacent_floats(
    tmp_path: Path, monkeypatch, score: float, accepted: bool, reason: str | None
):
    decision = _steal_twin_r1a_score(
        tmp_path,
        monkeypatch,
        heatmap=np.full((3, 5, 5), score, dtype=np.float64),
    )
    assert decision.accepted is accepted
    assert decision.raw_score == score
    assert decision.reason == reason


def test_steal_twin_r1a_frame_read_precedes_inference_and_shared_caches_reuse(tmp_path: Path, monkeypatch):
    calls: list[str] = []
    physical_reads = 0
    inferences = 0

    def read_frame(_test_dir, _dataset, t, frame_cache):
        nonlocal physical_reads
        calls.append("frame")
        if t not in frame_cache:
            physical_reads += 1
            frame_cache[t] = np.ones((3, 5, 5), dtype=np.float32)
        return frame_cache[t]

    def infer(_cfg, dataset, t, _bundle, frame_cache, heatmap_cache):
        nonlocal inferences
        calls.append("inference")
        key = (dataset, t)
        if key not in heatmap_cache:
            assert t in frame_cache
            inferences += 1
            heatmap_cache[key] = np.full((3, 5, 5), 0.2, dtype=np.float32)
        return heatmap_cache[key]

    monkeypatch.setattr(divisions_module, "read_test_frame", read_frame)
    monkeypatch.setattr(divisions_module, "deepcenter_heatmap_for_frame", infer)
    frame_cache: dict[int, np.ndarray] = {}
    heatmap_cache: dict[tuple[str, int], np.ndarray] = {}
    cfg = _steal_twin_r1a_cfg(tmp_path)
    bundle = _steal_twin_r1a_bundle()
    first = divisions_module.score_twin_deepcenter(cfg, "ds0", 4, (1, 2, 2), bundle, frame_cache, heatmap_cache)
    second = divisions_module.score_twin_deepcenter(cfg, "ds0", 4, (1, 2, 2), bundle, frame_cache, heatmap_cache)
    assert first.accepted and second.accepted
    assert calls == ["frame", "inference", "frame", "inference"]
    assert physical_reads == 1
    assert inferences == 1


def test_steal_twin_r1a_existing_fail_open_helper_is_unchanged(tmp_path: Path):
    cfg = _steal_twin_r1a_cfg(tmp_path)
    stats = {"deepcenter_gap_missing": 0}
    accepted = deepcenter_module.deepcenter_accept_repair_point(
        cfg,
        "ds0",
        0,
        (0, 0, 0),
        None,
        {},
        {},
        stats,
        "gap",
        0.99,
    )
    assert accepted is True
    assert stats == {"deepcenter_gap_missing": 1}


# --------------------------------------------------------------------------
# ST-R1b: immutable twin-only planner
# --------------------------------------------------------------------------
_TWIN_SCALE_Y = 0.40625


def _twin_node(node_id: int, t: int, y_um: float, **metadata: object) -> dict[str, object]:
    return {
        "node_id": node_id,
        "t": t,
        "z": 0.0,
        "y": y_um / _TWIN_SCALE_Y,
        "x": 0.0,
        **metadata,
    }


def _twin_motif(
    *,
    p_um: float = 0.0,
    q_um: float = 4.0,
    a_um: float = 0.0,
    b_um: float = 6.0,
    a2_um: float = 0.0,
    b2_um: float = 9.0,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    nodes = [
        _twin_node(0, -1, p_um),
        _twin_node(1, 0, p_um),
        _twin_node(2, 0, q_um),
        _twin_node(3, 1, a_um),
        _twin_node(4, 1, b_um),
        _twin_node(5, 2, a2_um),
        _twin_node(6, 2, b2_um),
    ]
    edges = [
        {"source_id": 0, "target_id": 1, "edge_prob": 0.9},
        {"source_id": 1, "target_id": 3, "edge_prob": 0.8},
        {
            "source_id": 2,
            "target_id": 4,
            "edge_prob": 0.7,
            "input_position": "caller-value",
            "nested": {"values": [1, {"two": 2}]},
        },
        {"source_id": 3, "target_id": 5, "edge_prob": 0.6},
        {"source_id": 4, "target_id": 6, "edge_prob": 0.5},
    ]
    return nodes, edges


def _offset_twin_motif(
    *,
    id_offset: int,
    frame: int,
    space_um: float,
    b_delta_um: float = 6.0,
    b2_delta_um: float = 9.0,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    nodes, edges = _twin_motif(
        p_um=space_um,
        q_um=space_um + 4.0,
        a_um=space_um,
        b_um=space_um + b_delta_um,
        a2_um=space_um,
        b2_um=space_um + b2_delta_um,
    )
    for node in nodes:
        node["node_id"] += id_offset
        node["t"] += frame
    for edge in edges:
        edge["source_id"] += id_offset
        edge["target_id"] += id_offset
    return nodes, edges


def _twin_accept(_node) -> divisions_module.TwinDeepCenterDecision:
    return divisions_module.TwinDeepCenterDecision(True, 0.2, None)


def _twin_plan(tmp_path: Path, nodes, edges, callback=_twin_accept):
    return divisions_module.plan_twin_only_v1(
        _steal_twin_r1a_cfg(tmp_path), "ds0", nodes, edges, callback
    )


def _make_twin_outdegree_invalid(nodes, edges) -> None:
    nodes.append(_twin_node(7, 0, 20.0))
    edges.extend([{"source_id": 0, "target_id": 2}, {"source_id": 0, "target_id": 7}])


def _assert_twin_conservation(plan) -> None:
    counters = plan.counters
    eligibility_reasons = (
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
    assert counters["steal_twin_enumerated"] == (
        sum(counters[f"steal_twin_rejected_{reason}"] for reason in eligibility_reasons)
        + counters["steal_twin_eligible"]
    )
    assert counters["steal_twin_eligible"] == (
        counters["steal_twin_accepted"]
        + counters["steal_twin_rejected_conflict"]
        + counters["steal_twin_rejected_frame_cap"]
        + counters["steal_twin_rejected_video_cap"]
    )
    accepted = counters["steal_twin_accepted"]
    assert counters["steal_twin_planned_edges_removed"] == accepted
    assert counters["steal_twin_planned_edges_added"] == accepted
    assert counters["steal_twin_edges_removed"] == counters["steal_twin_edges_added"] == 0
    assert counters["steal_twin_isolated_donors"] == accepted
    assert accepted <= counters["steal_twin_examined_frames"]
    assert accepted <= 2
    assert counters["steal_twin_debug_records_written"] == 0
    assert counters["steal_twin_debug_records_dropped"] == 0


def test_steal_twin_r1b_minimal_exact_candidate_counters_and_debug_record(tmp_path: Path):
    nodes, edges = _twin_motif()
    called: list[int] = []

    def score(node):
        called.append(node.node_id)
        return divisions_module.TwinDeepCenterDecision(True, 0.2, None)

    plan = _twin_plan(tmp_path, nodes, edges, score)
    assert plan.validation_reason is None
    assert called == [4]
    assert len(plan.candidates) == len(plan.accepted_candidates) == len(plan.decisions) == 1
    candidate = plan.candidates[0]
    assert (candidate.p, candidate.q, candidate.a, candidate.b, candidate.a2, candidate.b2) == (1, 2, 3, 4, 5, 6)
    assert candidate.sort_key == (6.9, -3.0, 4.0, 1, 2, 3, 4, 5, 6)
    assert candidate.planned_edge == divisions_module.TwinPlannedEdge(1, 4, 6.0)
    assert candidate.removed_edge.metadata["input_position"] == "caller-value"
    snapshot = next(edge for edge in plan.edges if (edge.source_id, edge.target_id) == (2, 4))
    assert snapshot.input_position == 2
    assert plan.decisions[0].accepted and plan.decisions[0].reason is None
    record = plan.debug_records[0]
    assert record.dataset == "ds0"
    assert record.decision == "accepted" and record.reason is None
    assert (record.p, record.q, record.a, record.b, record.a2, record.b2) == (1, 2, 3, 4, 5, 6)
    assert record.sort_key == (6.9, -3.0, 4.0, 1, 2, 3, 4, 5, 6)
    assert (record.d_pq, record.d_pa, record.d_pb, record.d_ab, record.d_a2b2) == (
        4.0,
        0.0,
        6.0,
        6.0,
        9.0,
    )
    assert record.divergence_growth == 3.0
    assert record.raw_deepcenter_score == 0.2
    assert record.deepcenter_threshold == 0.12
    assert record.deepcenter_decision == divisions_module.TwinDeepCenterDecision(True, 0.2, None)
    assert record.removed_edge == candidate.removed_edge
    assert record.removed_edge.source_id == 2 and record.removed_edge.target_id == 4
    assert dict(record.removed_edge.metadata) == {
        "source_id": 2,
        "target_id": 4,
        "edge_prob": 0.7,
        "input_position": "caller-value",
        "nested": divisions_module.TwinFrozenMapping(
            (("values", (1, divisions_module.TwinFrozenMapping((("two", 2),)))),)
        ),
    }
    assert record.planned_edge == candidate.planned_edge
    assert record.planned_edge == divisions_module.TwinPlannedEdge(1, 4, 6.0, None)
    assert plan.counters["steal_twin_accepted"] == 1
    assert plan.counters["steal_twin_examined_frames"] == 3
    _assert_twin_conservation(plan)


def test_steal_twin_r1b_donor_with_predecessor_is_excluded_from_q_pool(tmp_path: Path):
    nodes, edges = _twin_motif()
    nodes.append(_twin_node(7, -1, 4.0))
    edges.append({"source_id": 7, "target_id": 2})
    plan = _twin_plan(tmp_path, nodes, edges)
    assert plan.validation_reason is None
    assert plan.counters["steal_twin_q_pool"] == 2  # nodes 0 and 7, but not donor 2
    assert plan.counters["steal_twin_enumerated"] == 0
    assert not plan.candidates
    _assert_twin_conservation(plan)


@pytest.mark.parametrize(
    ("reason", "mutate"),
    [
        ("missing_node_field", lambda n, e: n[0].pop("z")),
        ("invalid_node_id", lambda n, e: n[0].update(node_id=True)),
        ("duplicate_node_id", lambda n, e: n.append(dict(n[0]))),
        ("invalid_node_time", lambda n, e: n[0].update(t=0.0)),
        ("nonfinite_node_coordinate", lambda n, e: n[0].update(z=np.nan)),
        ("invalid_edge_endpoint", lambda n, e: e[0].update(source_id=True)),
        ("dangling_edge", lambda n, e: e[0].update(source_id=999)),
        ("duplicate_edge", lambda n, e: e.append(dict(e[0]))),
        ("nonconsecutive_edge", lambda n, e: e[0].update(target_id=3)),
        ("indegree", lambda n, e: e.append({"source_id": 2, "target_id": 3})),
        ("outdegree", _make_twin_outdegree_invalid),
        (
            "nonfinite_edge_distance",
            lambda n, e: (n[0].update(z=1e308), n[1].update(z=-1e308)),
        ),
    ],
)
def test_steal_twin_r1b_every_validation_reason_is_order_invariant_and_callback_free(
    tmp_path: Path, reason: str, mutate
):
    nodes, edges = _twin_motif()
    mutate(nodes, edges)
    calls = 0

    def score(_node):
        nonlocal calls
        calls += 1
        return divisions_module.TwinDeepCenterDecision(True, 0.2, None)

    first = _twin_plan(tmp_path, nodes, edges, score)
    second = _twin_plan(tmp_path, list(reversed(nodes)), list(reversed(edges)), score)
    for plan in (first, second):
        assert plan.validation_reason == reason
        assert plan.counters["steal_twin_validation_failed"] == 1
        assert plan.counters[f"steal_twin_validation_{reason}"] == 1
        assert sum(plan.counters.values()) == 2
        assert not plan.nodes and not plan.edges and not plan.debug_records
    assert calls == 0


def test_steal_twin_r1b_validation_exact_multifault_priority(tmp_path: Path):
    nodes, edges = _twin_motif()
    nodes[0].pop("z")
    nodes[1]["node_id"] = True
    edges[0]["source_id"] = "bad"
    assert _twin_plan(tmp_path, nodes, edges).validation_reason == "missing_node_field"


@pytest.mark.parametrize(
    "expected",
    [
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
    ],
)
def test_steal_twin_r1b_multifault_priority_covers_every_validation_category(
    tmp_path: Path, expected: str
):
    nodes, edges = _twin_motif()
    if expected == "missing_node_field":
        nodes[0].pop("z")
        nodes[1]["node_id"] = True
    elif expected == "invalid_node_id":
        nodes[0]["node_id"] = True
        nodes.append(dict(nodes[1]))
    elif expected == "duplicate_node_id":
        nodes.append(dict(nodes[0]))
        nodes[1]["t"] = 0.5
    elif expected == "invalid_node_time":
        nodes[0]["t"] = 0.5
        nodes[1]["z"] = np.nan
    elif expected == "nonfinite_node_coordinate":
        nodes[0]["z"] = np.nan
        edges[0]["source_id"] = True
    elif expected == "invalid_edge_endpoint":
        edges[0]["source_id"] = True
        edges[1]["source_id"] = 999
    elif expected == "dangling_edge":
        edges[0]["source_id"] = 999
        edges.append(dict(edges[1]))
    elif expected == "duplicate_edge":
        edges.append(dict(edges[0]))
        edges[1]["target_id"] = 5
    elif expected == "nonconsecutive_edge":
        edges.append({"source_id": 0, "target_id": 3})
    elif expected == "indegree":
        edges.append({"source_id": 2, "target_id": 3})
        _make_twin_outdegree_invalid(nodes, edges)
    elif expected == "outdegree":
        _make_twin_outdegree_invalid(nodes, edges)
        nodes[0]["z"] = 1e308
        nodes[1]["z"] = -1e308
    else:
        nodes[0]["z"] = 1e308
        nodes[1]["z"] = -1e308
        nodes[3]["z"] = 1e308
        nodes[5]["z"] = -1e308
    for ordered_nodes, ordered_edges in (
        (nodes, edges),
        (list(reversed(nodes)), list(reversed(edges))),
    ):
        plan = _twin_plan(tmp_path, ordered_nodes, ordered_edges)
        assert plan.validation_reason == expected
        assert plan.counters[f"steal_twin_validation_{expected}"] == 1


def test_steal_twin_r1b_wrong_time_and_shared_successor_validate_first(tmp_path: Path):
    nodes, edges = _twin_motif()
    edges[3]["target_id"] = 4
    wrong_time = _twin_plan(tmp_path, nodes, edges)
    assert wrong_time.validation_reason == "nonconsecutive_edge"
    assert wrong_time.counters["steal_twin_rejected_time"] == 0

    nodes, edges = _twin_motif()
    edges[4]["target_id"] = 5
    shared = _twin_plan(tmp_path, nodes, edges)
    assert shared.validation_reason == "indegree"
    assert shared.counters["steal_twin_rejected_shared_successor"] == 0


@pytest.mark.parametrize(
    ("overrides", "counter"),
    [
        ({"q_um": np.nextafter(5.0, np.inf)}, "distance_twin"),
        (
            {"a_um": np.nextafter(-10.0, -np.inf), "b_um": -4.0, "a2_um": -10.0, "b2_um": -1.0},
            "distance_existing_child",
        ),
        ({"b_um": np.nextafter(8.0, np.inf), "b2_um": 11.0}, "distance_parent"),
        ({"b_um": np.nextafter(5.5, -np.inf), "b2_um": 8.0}, "distance_sister_low"),
        ({"p_um": 3.0, "q_um": 4.0, "b_um": np.nextafter(11.0, np.inf), "b2_um": 14.0}, "distance_sister_high"),
        ({"b2_um": np.nextafter(8.25, -np.inf)}, "divergence"),
    ],
)
def test_steal_twin_r1b_adjacent_float_outside_bounds_rejects(tmp_path: Path, overrides, counter: str):
    nodes, edges = _twin_motif(**overrides)
    plan = _twin_plan(tmp_path, nodes, edges)
    assert plan.counters[f"steal_twin_rejected_{counter}"] == 1
    assert not plan.candidates
    _assert_twin_conservation(plan)


@pytest.mark.parametrize(
    "overrides",
    [
        {"q_um": 5.0},
        {"q_um": np.nextafter(5.0, -np.inf)},
        {"a_um": -10.0, "b_um": -4.0, "a2_um": -10.0, "b2_um": -1.0},
        {
            "a_um": np.nextafter(-10.0, np.inf),
            "b_um": -4.0,
            "a2_um": -10.0,
            "b2_um": -1.0,
        },
        {"b_um": 8.0, "b2_um": 11.0},
        {"b_um": np.nextafter(8.0, -np.inf), "b2_um": 11.0},
        {"b_um": 5.5, "b2_um": 7.75},
        {"b_um": np.nextafter(5.5, np.inf), "b2_um": np.nextafter(7.75, np.inf)},
        {"p_um": 3.0, "q_um": 4.0, "b_um": 11.0, "b2_um": 13.25},
        {
            "p_um": 3.0,
            "q_um": 4.0,
            "b_um": np.nextafter(11.0, -np.inf),
            "b2_um": 13.25,
        },
        {"b2_um": 8.25},
        {"b2_um": np.nextafter(8.25, np.inf)},
    ],
)
def test_steal_twin_r1b_inclusive_geometry_boundaries_accept(tmp_path: Path, overrides):
    nodes, edges = _twin_motif(**overrides)
    plan = _twin_plan(tmp_path, nodes, edges)
    assert plan.validation_reason is None
    assert plan.counters["steal_twin_accepted"] == 1
    _assert_twin_conservation(plan)


@pytest.mark.parametrize("role_id", [1, 2, 3, 4, 5, 6])
def test_steal_twin_r1b_each_synthetic_role_rejects_before_callback(tmp_path: Path, role_id: int):
    nodes, edges = _twin_motif()
    next(node for node in nodes if node["node_id"] == role_id)["gap_synthetic"] = 1
    calls: list[int] = []
    plan = _twin_plan(tmp_path, nodes, edges, lambda node: calls.append(node.node_id))
    assert plan.counters["steal_twin_rejected_synthetic"] == 1
    assert calls == []


@pytest.mark.parametrize("missing_source", [3, 4])
def test_steal_twin_r1b_missing_or_branching_successor_rejects(tmp_path: Path, missing_source: int):
    nodes, edges = _twin_motif()
    edges[:] = [edge for edge in edges if edge["source_id"] != missing_source]
    plan = _twin_plan(tmp_path, nodes, edges)
    assert plan.counters["steal_twin_rejected_missing_successor"] == 1


@pytest.mark.parametrize("branch_source", [3, 4])
def test_steal_twin_r1b_two_successors_rejects_as_missing_successor(tmp_path: Path, branch_source: int):
    nodes, edges = _twin_motif()
    new_id = 7
    nodes.append(_twin_node(new_id, 2, 20.0))
    edges.append({"source_id": branch_source, "target_id": new_id})
    plan = _twin_plan(tmp_path, nodes, edges)
    assert plan.validation_reason is None
    assert plan.counters["steal_twin_rejected_missing_successor"] == 1


@pytest.mark.parametrize("reason", [
    "deepcenter_bundle",
    "deepcenter_dataset",
    "deepcenter_frame",
    "deepcenter_heatmap",
    "deepcenter_nonfinite",
])
def test_steal_twin_r1b_maps_each_deepcenter_reason(tmp_path: Path, reason: str):
    nodes, edges = _twin_motif()

    def callback(_node):
        return divisions_module.TwinDeepCenterDecision(False, None, reason)

    plan = _twin_plan(tmp_path, nodes, edges, callback)
    assert plan.counters[f"steal_twin_rejected_{reason}"] == 1


def test_steal_twin_r1b_maps_valid_threshold_rejection(tmp_path: Path):
    nodes, edges = _twin_motif()

    def callback(_node):
        return divisions_module.TwinDeepCenterDecision(
            False, np.nextafter(0.12, -np.inf), "deepcenter_threshold"
        )

    plan = _twin_plan(tmp_path, nodes, edges, callback)
    assert plan.counters["steal_twin_rejected_deepcenter_threshold"] == 1


@pytest.mark.parametrize(
    "result",
    [
        object(),
        divisions_module.TwinDeepCenterDecision(1, 0.2, None),
        divisions_module.TwinDeepCenterDecision(True, None, None),
        divisions_module.TwinDeepCenterDecision(True, np.nan, None),
        divisions_module.TwinDeepCenterDecision(True, 0.2, "deepcenter_threshold"),
        divisions_module.TwinDeepCenterDecision(False, None, "unknown"),
        divisions_module.TwinDeepCenterDecision(False, None, "deepcenter_threshold"),
        divisions_module.TwinDeepCenterDecision(False, 0.12, "deepcenter_threshold"),
        divisions_module.TwinDeepCenterDecision(False, 0.2, "deepcenter_frame"),
    ],
)
def test_steal_twin_r1b_malformed_callback_result_fails_closed(tmp_path: Path, result: object):
    nodes, edges = _twin_motif()
    plan = _twin_plan(tmp_path, nodes, edges, lambda _node: result)
    assert plan.counters["steal_twin_rejected_deepcenter_bundle"] == 1


def test_steal_twin_r1b_callback_exception_fails_closed(tmp_path: Path):
    nodes, edges = _twin_motif()

    def fail(_node):
        raise RuntimeError("synthetic")

    plan = _twin_plan(tmp_path, nodes, edges, fail)
    assert plan.counters["steal_twin_rejected_deepcenter_bundle"] == 1


@pytest.mark.parametrize(
    "reason",
    [
        "distance_twin",
        "ambiguous_p_nn",
        "ambiguous_q_nn",
        "not_mutual_parent_nn",
        "distance_existing_child",
        "distance_parent",
        "distance_sister_low",
        "distance_sister_high",
        "missing_successor",
        "divergence",
        "synthetic",
    ],
)
def test_steal_twin_r1b_callback_runs_only_after_every_earlier_gate_family(
    tmp_path: Path, reason: str
):
    if reason == "distance_existing_child":
        nodes, edges = _twin_motif(a_um=-10.1, b_um=-4.0, a2_um=-10.1, b2_um=-1.0)
    elif reason == "distance_parent":
        nodes, edges = _twin_motif(b_um=8.1, b2_um=11.0)
    elif reason == "distance_sister_low":
        nodes, edges = _twin_motif(b_um=5.0, b2_um=8.0)
    elif reason == "distance_sister_high":
        nodes, edges = _twin_motif(
            p_um=4.0, q_um=4.0, a_um=0.0, b_um=12.0, a2_um=0.0, b2_um=15.0
        )
    else:
        nodes, edges = _twin_motif()
    if reason == "distance_twin":
        next(node for node in nodes if node["node_id"] == 2)["y"] = 6.0 / _TWIN_SCALE_Y
    elif reason == "ambiguous_p_nn":
        nodes.extend([_twin_node(7, 0, -4.0), _twin_node(8, 1, -6.0)])
        edges.append({"source_id": 7, "target_id": 8})
    elif reason in ("ambiguous_q_nn", "not_mutual_parent_nn"):
        extra_um = 8.0 if reason == "ambiguous_q_nn" else 3.0
        nodes.extend(
            [
                _twin_node(7, -1, extra_um),
                _twin_node(8, 0, extra_um),
                _twin_node(9, 1, extra_um),
            ]
        )
        edges.extend([{"source_id": 7, "target_id": 8}, {"source_id": 8, "target_id": 9}])
    elif reason == "missing_successor":
        edges[:] = [edge for edge in edges if edge["source_id"] != 3]
    elif reason == "divergence":
        next(node for node in nodes if node["node_id"] == 6)["y"] = 8.0 / _TWIN_SCALE_Y
    elif reason == "synthetic":
        next(node for node in nodes if node["node_id"] == 5)["gap_synthetic"] = 1
    calls: list[int] = []
    plan = _twin_plan(
        tmp_path,
        nodes,
        edges,
        lambda node: calls.append(node.node_id) or divisions_module.TwinDeepCenterDecision(True, 0.2, None),
    )
    assert plan.counters[f"steal_twin_rejected_{reason}"] >= 1
    assert calls == []


def test_steal_twin_r1b_snapshot_and_records_are_detached_idempotent_and_no_io(tmp_path: Path):
    nodes, edges = _twin_motif()
    caller_array = np.asarray([[1, 2], [3, 4]], dtype=np.int16)
    caller_strided_array = np.arange(8, dtype=np.int16)[::2]
    caller_metadata_array = np.asarray(
        [7, 8], dtype=np.dtype(np.int16, metadata={"unit": "um", "nested": [1, 2]})
    )
    caller_object_array = np.asarray([{"nested": [5]}], dtype=object)
    caller_structured_array = np.asarray(
        [("cell", {"values": [6]})],
        dtype=np.dtype([("name", "U4"), ("payload", object)]),
    )
    caller_buffer = bytearray(b"mutable")
    caller_view_bytes = bytearray(b"view")
    edges[2]["nested"]["array"] = caller_array
    edges[2]["nested"]["strided_array"] = caller_strided_array
    edges[2]["nested"]["metadata_array"] = caller_metadata_array
    edges[2]["nested"]["object_array"] = caller_object_array
    edges[2]["nested"]["structured_array"] = caller_structured_array
    edges[2]["nested"]["buffer"] = caller_buffer
    edges[2]["nested"]["view"] = memoryview(caller_view_bytes)
    original_node_order = [id(row) for row in nodes]
    original_edge_order = [id(row) for row in edges]
    first = _twin_plan(tmp_path, nodes, edges)
    second = _twin_plan(tmp_path, nodes, edges)
    assert first == second
    assert [id(row) for row in nodes] == original_node_order
    assert [id(row) for row in edges] == original_edge_order
    frozen = first.debug_records[0].removed_edge
    nodes[4]["y"] = 999.0
    edges[2]["edge_prob"] = -1.0
    edges[2]["nested"]["values"][1]["two"] = 999
    caller_array[0, 0] = 999
    caller_strided_array[0] = 999
    caller_metadata_array.dtype.metadata["nested"][0] = 999
    caller_object_array[0]["nested"][0] = 999
    caller_structured_array[0]["payload"]["values"][0] = 999
    caller_buffer[0] = ord("X")
    caller_view_bytes[0] = ord("X")
    edges.reverse()
    assert frozen.metadata["edge_prob"] == 0.7
    assert frozen.metadata["nested"]["values"][1]["two"] == 2
    assert frozen.metadata["input_position"] == "caller-value"
    frozen_array = frozen.metadata["nested"]["array"]
    assert isinstance(frozen_array, divisions_module.TwinFrozenArray)
    assert frozen_array.dtype.string == "<i2"
    assert frozen_array.dtype.descriptor == (("", "<i2"),)
    assert frozen_array.shape == (2, 2)
    assert np.frombuffer(frozen_array.content, dtype=np.int16).reshape(frozen_array.shape).tolist() == [
        [1, 2],
        [3, 4],
    ]
    with pytest.raises(TypeError):
        frozen_array.content[0] = 0
    frozen_strided = frozen.metadata["nested"]["strided_array"]
    assert frozen_strided.shape == (4,)
    assert frozen_strided.strides == (4,)
    assert frozen_strided.c_contiguous is False
    assert np.frombuffer(frozen_strided.content, dtype=np.int16).tolist() == [0, 2, 4, 6]
    frozen_metadata_array = frozen.metadata["nested"]["metadata_array"]
    assert frozen_metadata_array.dtype.metadata["unit"] == "um"
    assert frozen_metadata_array.dtype.metadata["nested"] == (1, 2)
    frozen_object_array = frozen.metadata["nested"]["object_array"]
    assert isinstance(frozen_object_array, divisions_module.TwinFrozenArray)
    assert frozen_object_array.object_content is True
    assert frozen_object_array.content[0]["nested"] == (5,)
    frozen_structured = frozen.metadata["nested"]["structured_array"]
    assert frozen_structured.dtype.names == ("name", "payload")
    assert frozen_structured.dtype.hasobject is True
    structured_value = frozen_structured.content[0]
    assert isinstance(structured_value, divisions_module.TwinFrozenStructuredScalar)
    assert dict(structured_value.fields)["payload"]["values"] == (6,)
    frozen_buffer = frozen.metadata["nested"]["buffer"]
    frozen_view = frozen.metadata["nested"]["view"]
    assert frozen_buffer == divisions_module.TwinFrozenBuffer(
        "bytearray", "B", 1, (7,), (1,), False, b"mutable"
    )
    assert frozen_view.kind == "memoryview"
    assert frozen_view.readonly is False
    assert frozen_view.content == b"view"
    with pytest.raises(TypeError):
        frozen_buffer.content[0] = 0
    assert first.debug_records[0].planned_edge.distance_um == 6.0
    assert list(tmp_path.iterdir()) == []


def test_steal_twin_r1b_rejects_unsupported_custom_mutable_metadata_before_plan(tmp_path: Path):
    class MutableMetadata:
        def __init__(self):
            self.values = [1]

    nodes, edges = _twin_motif()
    mutable = MutableMetadata()
    edges[2]["custom"] = mutable
    calls: list[int] = []
    with pytest.raises(TypeError, match="unsupported mutable edge metadata type"):
        _twin_plan(tmp_path, nodes, edges, lambda node: calls.append(node.node_id))
    assert mutable.values == [1]
    assert calls == []


def test_steal_twin_r1b_integral_subclass_endpoints_are_canonical_detached_metadata(
    tmp_path: Path,
):
    class Endpoint(IntEnum):
        DONOR = 2

    class MutableIntegral(int):
        def __new__(cls, value: int):
            instance = super().__new__(cls, value)
            instance.payload = ["caller-owned"]
            return instance

    nodes, edges = _twin_motif()
    caller_target = MutableIntegral(4)
    edges[2]["source_id"] = Endpoint.DONOR
    edges[2]["target_id"] = caller_target
    callback_nodes = []

    def score(node):
        callback_nodes.append(node)
        return divisions_module.TwinDeepCenterDecision(True, 0.2, None)

    plan = _twin_plan(tmp_path, nodes, edges, score)

    assert plan.validation_reason is None
    assert plan.counters["steal_twin_accepted"] == 1
    assert [node.node_id for node in callback_nodes] == [4]
    assert type(callback_nodes[0].node_id) is int
    with pytest.raises(FrozenInstanceError):
        callback_nodes[0].node_id = 999
    removed = plan.debug_records[0].removed_edge
    assert removed.metadata["source_id"] == 2
    assert removed.metadata["target_id"] == 4
    assert type(removed.metadata["source_id"]) is int
    assert type(removed.metadata["target_id"]) is int
    assert edges[2]["source_id"] is Endpoint.DONOR
    assert edges[2]["target_id"] is caller_target
    assert caller_target.payload == ["caller-owned"]

    caller_target.payload[0] = "mutated"
    edges[2]["source_id"] = 999
    edges[2]["target_id"] = 999
    assert removed.metadata["source_id"] == 2
    assert removed.metadata["target_id"] == 4
    with pytest.raises(TypeError):
        removed.metadata["target_id"] = 999


def test_steal_twin_r1b_empty_pool_has_complete_zero_schema_and_conserves(tmp_path: Path):
    plan = _twin_plan(tmp_path, [_twin_node(1, 0, 0.0)], [])
    assert plan.validation_reason is None
    assert len(plan.counters) == len(divisions_module._TWIN_COUNTER_KEYS)
    assert not plan.candidates and not plan.debug_records
    _assert_twin_conservation(plan)


def test_steal_twin_r1b_row_permutations_are_deterministic(tmp_path: Path):
    nodes, edges = _twin_motif()
    baseline = _twin_plan(tmp_path, nodes, edges)
    rng = np.random.default_rng(23)
    for _ in range(20):
        permuted_nodes = [nodes[index] for index in rng.permutation(len(nodes))]
        permuted_edges = [edges[index] for index in rng.permutation(len(edges))]
        plan = _twin_plan(tmp_path, permuted_nodes, permuted_edges)
        assert plan.candidates == baseline.candidates
        assert plan.decisions == baseline.decisions
        assert plan.counters == baseline.counters
        # Internal input ordinals intentionally follow the caller edge rows.
        assert plan.debug_records[0].removed_edge.metadata == baseline.debug_records[0].removed_edge.metadata


def test_steal_twin_r1b_one_union_tree_per_frame_with_both_pools(tmp_path: Path, monkeypatch):
    nodes0, edges0 = _twin_motif()
    nodes1 = [dict(node, node_id=node["node_id"] + 10, t=node["t"] + 10) for node in nodes0]
    edges1 = [
        {**edge, "source_id": edge["source_id"] + 10, "target_id": edge["target_id"] + 10}
        for edge in edges0
    ]
    real_tree = divisions_module.cKDTree
    calls: list[np.ndarray] = []

    def spy(points):
        calls.append(np.asarray(points).copy())
        return real_tree(points)

    monkeypatch.setattr(divisions_module, "cKDTree", spy)
    plan = _twin_plan(tmp_path, [*nodes0, *nodes1], [*edges0, *edges1])
    assert plan.counters["steal_twin_eligible"] == 2
    assert len(calls) == 2
    assert all(len(points) == 2 for points in calls)


def test_steal_twin_r1b_tree_queries_use_precomputed_id_index():
    import inspect

    source = inspect.getsource(divisions_module.plan_twin_only_v1)
    assert "union_index = {" in source
    assert ".index(node_id)" not in source


def test_steal_twin_r1b_one_union_tree_for_multiple_p_and_q_in_same_frame(
    tmp_path: Path, monkeypatch
):
    nodes0, edges0 = _offset_twin_motif(id_offset=0, frame=0, space_um=0.0)
    nodes1, edges1 = _offset_twin_motif(id_offset=20, frame=0, space_um=30.0)
    real_tree = divisions_module.cKDTree
    calls: list[np.ndarray] = []

    def spy(points):
        calls.append(np.asarray(points).copy())
        return real_tree(points)

    monkeypatch.setattr(divisions_module, "cKDTree", spy)
    plan = _twin_plan(tmp_path, [*nodes0, *nodes1], [*edges0, *edges1])
    assert plan.counters["steal_twin_eligible"] == 2
    assert len(calls) == 1
    assert calls[0].shape == (4, 3)


def test_steal_twin_r1b_translated_tree_filters_true_distance_above_radius(tmp_path: Path):
    nodes, edges = _twin_motif(
        p_um=416.0,
        q_um=421.0,
        a_um=416.0,
        b_um=422.0,
        a2_um=416.0,
        b2_um=425.0,
    )
    p = next(node for node in nodes if node["node_id"] == 1)
    q = next(node for node in nodes if node["node_id"] == 2)
    true_distance = abs(float(q["y"]) - float(p["y"])) * _TWIN_SCALE_Y
    assert true_distance == 5.000000000000028
    outside = _twin_plan(tmp_path, nodes, edges)
    assert outside.counters["steal_twin_rejected_distance_twin"] == 1
    assert outside.counters["steal_twin_accepted"] == 0

    q["y"] = np.nextafter(float(p["y"]) + 5.0 / _TWIN_SCALE_Y, -np.inf)
    inside_distance = abs(float(q["y"]) - float(p["y"])) * _TWIN_SCALE_Y
    assert inside_distance <= 5.0
    inside = _twin_plan(tmp_path, nodes, edges)
    assert inside.counters["steal_twin_accepted"] == 1


def test_steal_twin_r1b_tree_query_roundoff_superset_prevents_exact_radius_false_negative(
    tmp_path: Path,
):
    p_y = 1.7577288453082915
    q_y = 14.0654211530006
    nodes, edges = _twin_motif()
    by_id = {node["node_id"]: node for node in nodes}
    for node_id in (0, 1, 3, 5):
        by_id[node_id]["y"] = p_y
    by_id[2]["y"] = q_y
    by_id[4]["y"] = p_y + 6.0 / _TWIN_SCALE_Y
    by_id[6]["y"] = p_y + 9.0 / _TWIN_SCALE_Y
    # A third, lower-ID P establishes the frame origin. It is outside Q's
    # frozen radius and therefore cannot change the mutual pair.
    nodes.extend(
        [
            {"node_id": -3, "t": -1, "z": 0.0, "y": 0.0, "x": 0.0},
            {"node_id": -2, "t": 0, "z": 0.0, "y": 0.0, "x": 0.0},
            {"node_id": -1, "t": 1, "z": 0.0, "y": 0.0, "x": 0.0},
        ]
    )
    edges.extend([{"source_id": -3, "target_id": -2}, {"source_id": -2, "target_id": -1}])
    snapshot_p = divisions_module.TwinSnapshotNode(1, 0, 0.0, p_y, 0.0, False)
    snapshot_q = divisions_module.TwinSnapshotNode(2, 0, 0.0, q_y, 0.0, False)
    assert divisions_module._twin_distance(snapshot_p, snapshot_q) == 5.0
    assert q_y * _TWIN_SCALE_Y - p_y * _TWIN_SCALE_Y == 5.000000000000001
    exact = _twin_plan(tmp_path, nodes, edges)
    assert exact.counters["steal_twin_accepted"] == 1

    by_id[2]["y"] = p_y + np.nextafter(5.0, np.inf) / _TWIN_SCALE_Y
    outside = _twin_plan(tmp_path, nodes, edges)
    assert outside.counters["steal_twin_accepted"] == 0
    assert outside.counters["steal_twin_rejected_distance_twin"] >= 1


def test_steal_twin_r1b_nonfinite_translated_tree_coordinates_fail_closed_without_all_pairs(
    tmp_path: Path, monkeypatch
):
    nodes, edges = _twin_motif()
    for node in nodes:
        node["z"] = 1e308
    nodes.extend(
        [
            {"node_id": -3, "t": -1, "z": -1e308, "y": 0.0, "x": 0.0},
            {"node_id": -2, "t": 0, "z": -1e308, "y": 0.0, "x": 0.0},
            {"node_id": -1, "t": 1, "z": -1e308, "y": 0.0, "x": 0.0},
        ]
    )
    edges.extend([{"source_id": -3, "target_id": -2}, {"source_id": -2, "target_id": -1}])
    constructors = 0

    def unexpected_tree(_points):
        nonlocal constructors
        constructors += 1
        raise AssertionError("nonfinite positions must not enter cKDTree")

    monkeypatch.setattr(divisions_module, "cKDTree", unexpected_tree)
    plan = _twin_plan(tmp_path, nodes, edges)
    assert plan.validation_reason is None
    assert constructors == 0
    assert plan.counters["steal_twin_enumerated"] == 2
    assert plan.counters["steal_twin_rejected_distance_twin"] == 2


def test_steal_twin_r1b_p_nearest_tie_is_inclusive_and_just_over_is_unique(tmp_path: Path):
    nodes, edges = _twin_motif()
    tie_distance = np.nextafter(4.0 + 1e-9, -np.inf)
    nodes.extend([_twin_node(7, 0, -tie_distance), _twin_node(8, 1, -6.0)])
    edges.append({"source_id": 7, "target_id": 8})
    tied = _twin_plan(tmp_path, nodes, edges)
    assert tied.counters["steal_twin_rejected_ambiguous_p_nn"] == 1

    nodes[7]["y"] = -np.nextafter(4.0 + 1e-9, np.inf) / _TWIN_SCALE_Y
    unique = _twin_plan(tmp_path, nodes, edges)
    assert unique.counters["steal_twin_accepted"] == 1
    assert unique.candidates[0].q == 2


def test_steal_twin_r1b_q_nearest_tie_and_unique_nonmutual_are_distinct(tmp_path: Path):
    nodes, edges = _twin_motif()
    nodes.extend(
        [
            _twin_node(7, -1, 8.0),
            _twin_node(8, 0, 8.0 + 1e-9),
            _twin_node(9, 1, 8.0),
        ]
    )
    edges.extend([{"source_id": 7, "target_id": 8}, {"source_id": 8, "target_id": 9}])
    tied = _twin_plan(tmp_path, nodes, edges)
    assert tied.counters["steal_twin_rejected_ambiguous_q_nn"] == 2

    just_over = np.nextafter(8.0 + 1e-9, np.inf)
    for node in nodes:
        if node["node_id"] in (7, 8, 9):
            node["y"] = just_over / _TWIN_SCALE_Y
    unique = _twin_plan(tmp_path, nodes, edges)
    assert unique.counters["steal_twin_rejected_ambiguous_q_nn"] == 0
    assert unique.counters["steal_twin_accepted"] == 1

    for node in nodes:
        if node["node_id"] in (7, 8, 9):
            node["y"] = 3.0 / _TWIN_SCALE_Y
    nonmutual = _twin_plan(tmp_path, nodes, edges)
    assert nonmutual.counters["steal_twin_rejected_not_mutual_parent_nn"] == 1


def test_steal_twin_r1b_spatial_query_order_does_not_change_plan(tmp_path: Path, monkeypatch):
    nodes, edges = _twin_motif()
    baseline = _twin_plan(tmp_path, nodes, edges)
    real_tree = divisions_module.cKDTree

    class ReversedTree:
        def __init__(self, points):
            self._tree = real_tree(points)

        def query_ball_point(self, *args, **kwargs):
            return list(reversed(self._tree.query_ball_point(*args, **kwargs)))

    monkeypatch.setattr(divisions_module, "cKDTree", ReversedTree)
    permuted = _twin_plan(tmp_path, nodes, edges)
    assert permuted == baseline


def test_steal_twin_r1b_sort_uses_cost_then_negative_growth_then_pq_not_score(tmp_path: Path):
    n0, e0 = _offset_twin_motif(id_offset=0, frame=0, space_um=0.0, b_delta_um=6.0, b2_delta_um=9.0)
    n1, e1 = _offset_twin_motif(id_offset=10, frame=10, space_um=0.0, b_delta_um=6.5, b2_delta_um=10.0)
    n2, e2 = _offset_twin_motif(id_offset=20, frame=20, space_um=0.0, b_delta_um=6.0, b2_delta_um=9.0)
    # Same cost as motif 0, greater growth: motif 2 sorts first despite its lower raw score.
    next(node for node in n2 if node["node_id"] == 26)["y"] = 9.5 / _TWIN_SCALE_Y
    scores = {4: 0.9, 14: 0.8, 24: 0.12}
    plan = _twin_plan(
        tmp_path,
        [*n0, *n1, *n2],
        [*e0, *e1, *e2],
        lambda node: divisions_module.TwinDeepCenterDecision(True, scores[node.node_id], None),
    )
    assert [candidate.p for candidate in plan.candidates] == [21, 1, 11]
    assert [candidate.raw_deepcenter_score for candidate in plan.candidates] == [0.12, 0.9, 0.8]
    assert plan.candidates[0].sort_key[:3] < plan.candidates[1].sort_key[:3]


def test_steal_twin_r1b_sort_uses_pq_before_ids_and_raw_score(tmp_path: Path):
    n0, e0 = _offset_twin_motif(id_offset=0, frame=0, space_um=0.0)
    n1, e1 = _offset_twin_motif(id_offset=10, frame=10, space_um=0.0)
    next(node for node in n1 if node["node_id"] == 12)["y"] = 3.0 / _TWIN_SCALE_Y
    scores = {4: 0.9, 14: 0.12}
    plan = _twin_plan(
        tmp_path,
        [*n0, *n1],
        [*e0, *e1],
        lambda node: divisions_module.TwinDeepCenterDecision(True, scores[node.node_id], None),
    )
    assert [candidate.p for candidate in plan.candidates] == [11, 1]
    assert [candidate.d_pq for candidate in plan.candidates] == [3.0, 4.0]
    assert [candidate.raw_deepcenter_score for candidate in plan.candidates] == [0.12, 0.9]


def test_steal_twin_r1b_sort_key_contains_every_id_as_successive_tie_breaker(tmp_path: Path):
    nodes, edges = _twin_motif()
    candidate = _twin_plan(tmp_path, nodes, edges).candidates[0]
    assert candidate.sort_key[3:] == (
        candidate.p,
        candidate.q,
        candidate.a,
        candidate.b,
        candidate.a2,
        candidate.b2,
    )
    prefix = candidate.sort_key[:3]
    for field_index in range(6):
        left_ids = [10] * 6
        right_ids = [10] * 6
        left_ids[field_index] = 1
        right_ids[field_index] = 2
        for later_index in range(field_index + 1, 6):
            left_ids[later_index] = 99
            right_ids[later_index] = 0
        assert (*prefix, *left_ids) < (*prefix, *right_ids)


def test_steal_twin_r1b_frame_cap_precedes_video_cap_and_records_resolution_rejects(tmp_path: Path):
    n0, e0 = _offset_twin_motif(id_offset=0, frame=0, space_um=0.0, b_delta_um=5.5, b2_delta_um=8.0)
    n1, e1 = _offset_twin_motif(id_offset=10, frame=10, space_um=30.0, b_delta_um=5.5, b2_delta_um=8.0)
    n2, e2 = _offset_twin_motif(id_offset=20, frame=10, space_um=60.0, b_delta_um=7.0, b2_delta_um=10.0)
    plan = _twin_plan(tmp_path, [*n0, *n1, *n2], [*e0, *e1, *e2])
    assert [decision.reason for decision in plan.decisions] == [None, None, "frame_cap"]
    assert plan.counters["steal_twin_rejected_frame_cap"] == 1
    assert plan.counters["steal_twin_rejected_video_cap"] == 0
    assert [record.reason for record in plan.debug_records] == [None, None, "frame_cap"]
    _assert_twin_conservation(plan)


def test_steal_twin_r1b_video_cap_rejects_third_independent_frame(tmp_path: Path):
    motifs = [
        _offset_twin_motif(id_offset=10 * index, frame=10 * index, space_um=30.0 * index)
        for index in range(3)
    ]
    nodes = [node for motif_nodes, _ in motifs for node in motif_nodes]
    edges = [edge for _, motif_edges in motifs for edge in motif_edges]
    plan = _twin_plan(tmp_path, nodes, edges)
    assert [decision.reason for decision in plan.decisions] == [None, None, "video_cap"]
    assert plan.counters["steal_twin_rejected_video_cap"] == 1
    _assert_twin_conservation(plan)


def test_steal_twin_r1b_conflict_precedes_simultaneous_frame_and_video_caps(tmp_path: Path):
    # Candidate 1 at frame 0: 1/2/3/4/5/6.  Candidate 2 at frame 1
    # reuses 3 and 5, so it conflicts with candidate 1.
    nodes, edges = _twin_motif(b_um=5.5, b2_um=8.0)
    nodes.extend(
        [
            _twin_node(7, 1, -4.0),
            _twin_node(8, 2, -6.0),
            _twin_node(9, 3, 0.0),
            _twin_node(10, 3, -9.0),
        ]
    )
    edges.extend(
        [
            {"source_id": 7, "target_id": 8},
            {"source_id": 5, "target_id": 9},
            {"source_id": 8, "target_id": 10},
        ]
    )
    # An independent frame-1 candidate sorts between the two above and fills
    # that frame's cap as well as the video's second slot.
    cap_nodes, cap_edges = _offset_twin_motif(
        id_offset=20,
        frame=1,
        space_um=30.0,
        b_delta_um=6.0,
        b2_delta_um=9.0,
    )
    plan = _twin_plan(tmp_path, [*nodes, *cap_nodes], [*edges, *cap_edges])
    role_decisions = {
        (decision.candidate.p, decision.candidate.q): decision.reason
        for decision in plan.decisions
    }
    assert role_decisions[(1, 2)] is None
    assert role_decisions[(21, 22)] is None
    assert role_decisions[(3, 7)] == "conflict"
    assert plan.counters["steal_twin_rejected_conflict"] == 1
    assert plan.counters["steal_twin_rejected_frame_cap"] == 0
    assert plan.counters["steal_twin_rejected_video_cap"] == 0
    _assert_twin_conservation(plan)


@pytest.mark.parametrize(
    ("pair", "failure_call", "reason"),
    [
        (frozenset((1, 2)), 1, "distance_twin"),
        (frozenset((1, 3)), 2, "distance_existing_child"),
        (frozenset((1, 4)), 1, "distance_parent"),
        (frozenset((3, 4)), 1, "distance_sister_high"),
        (frozenset((5, 6)), 1, "divergence"),
    ],
)
def test_steal_twin_r1b_nonfinite_derived_geometry_maps_to_exact_gate(
    tmp_path: Path,
    monkeypatch,
    pair: frozenset[int],
    failure_call: int,
    reason: str,
):
    nodes, edges = _twin_motif()
    real_distance = divisions_module._twin_distance
    calls = 0

    def overflow_at_gate(first, second):
        nonlocal calls
        if frozenset((first.node_id, second.node_id)) == pair:
            calls += 1
            if calls == failure_call:
                return float("inf")
        return real_distance(first, second)

    monkeypatch.setattr(divisions_module, "_twin_distance", overflow_at_gate)
    plan = _twin_plan(tmp_path, nodes, edges)
    assert plan.validation_reason is None
    assert plan.counters[f"steal_twin_rejected_{reason}"] == 1
    assert not plan.candidates
    _assert_twin_conservation(plan)


# --------------------------------------------------------------------------
# ST-R1c: pipeline dry-run integration and bounded debug publication
# --------------------------------------------------------------------------


def _r1c_cfg(tmp_path: Path, debug_path: Path | None = None, **overrides: str) -> PostprocConfig:
    values = {
        "BIOHUB_REFINE_ALL_CENTROIDS": "0",
        "BIOHUB_OUTPUT_MOTION_RELINK": "0",
        "BIOHUB_OUTPUT_GAP_CLOSE": "0",
        "BIOHUB_OUTPUT_GAP2_RECOVERY": "0",
        "BIOHUB_OUTPUT_SAFE_DIVISIONS": "0",
        "BIOHUB_OUTPUT_DIVISION_GEOMETRY_FILTER": "0",
        "BIOHUB_OUTPUT_PRUNE_ISOLATED": "0",
        "BIOHUB_OUTPUT_FILTER_SHORT_TRACKS": "0",
        "BIOHUB_OUTPUT_LINEFIT_SMOOTH": "0",
        "BIOHUB_STEAL_TWIN_DRY_RUN": "1",
        **overrides,
    }
    if debug_path is not None:
        values["BIOHUB_STEAL_TWIN_DEBUG_JSONL"] = str(debug_path)
    return build_config(values, test_dir=tmp_path, profile="e23_twin_only_v1")


def _r1c_record(
    dataset: str | None = "ds0",
    reason: str | None = None,
    metadata: divisions_module.TwinFrozenMapping | None = None,
):
    return divisions_module.TwinDebugRecord(
        dataset,
        "accepted" if reason is None else "rejected",
        reason,
        1,
        2,
        3,
        4,
        5,
        6,
        (6.9, -3.0, 4.0, 1, 2, 3, 4, 5, 6),
        4.0,
        0.0,
        6.0,
        6.0,
        9.0,
        3.0,
        0.2,
        0.12,
        divisions_module.TwinDeepCenterDecision(True, 0.2, None),
        divisions_module.TwinEdgeRecord(
            2,
            4,
            metadata
            if metadata is not None
            else divisions_module.TwinFrozenMapping(
                (("source_id", 2), ("target_id", 4), ("edge_prob", 0.7))
            ),
        ),
        divisions_module.TwinPlannedEdge(1, 4, 6.0),
    )


def _r1c_empty_plan(counters: object | None = None):
    if counters is None:
        counters = divisions_module.TwinFrozenMapping(
            tuple((key, 0) for key in divisions_module._TWIN_COUNTER_KEYS)
        )
    return divisions_module.TwinPlan(None, (), (), (), (), (), counters, ())


def test_steal_twin_r1c_new_stats_appends_exact_frozen_counter_schema():
    stats = new_stats()
    keys = tuple(stats)
    twin_keys = divisions_module._TWIN_COUNTER_KEYS
    assert keys[-len(twin_keys) :] == twin_keys
    assert not any(key.startswith("steal_twin_") for key in keys[: -len(twin_keys)])
    assert all(type(stats[key]) is int and stats[key] == 0 for key in twin_keys)


def test_steal_twin_r1c_non_dry_guard_precedes_direct_graph_work(tmp_path: Path, monkeypatch):
    cfg = build_config(test_dir=tmp_path, profile="e23_twin_only_v1")
    monkeypatch.setattr(pipeline_module, "new_stats", lambda: pytest.fail("new_stats called"))
    for function in (filter_output_graph_pre_linefit, filter_output_graph):
        with pytest.raises(RuntimeError) as error:
            function(cfg, {}, [])
        message = str(error.value)
        assert "ST-R1" in message and "ST-R2" in message
        assert "BIOHUB_STEAL_TWIN_DRY_RUN=1" in message


def test_steal_twin_r1c_direct_debug_collector_requirement_and_empty_path_inert(
    tmp_path: Path, monkeypatch
):
    cfg = _r1c_cfg(tmp_path, tmp_path / "debug.jsonl")
    monkeypatch.setattr(pipeline_module, "new_stats", lambda: pytest.fail("graph work started"))
    with pytest.raises(RuntimeError, match="run-level collector"):
        filter_output_graph_pre_linefit(cfg, {}, [])

    cfg = _r1c_cfg(tmp_path)

    class ForbiddenCollector:
        def allocate(self, _records):
            pytest.fail("collector called with empty debug path")

    monkeypatch.undo()
    nodes = {1: _twin_node(1, 0, 0.0)}
    out_nodes, edges, stats = filter_output_graph_pre_linefit(
        cfg, nodes, [], twin_debug_collector=ForbiddenCollector()
    )
    assert out_nodes is nodes and edges == []
    assert stats["steal_twin_validation_failed"] == 0


def test_steal_twin_r1c_master_off_never_reads_debug_or_calls_twin_components(
    tmp_path: Path, monkeypatch
):
    cfg = _cfg(tmp_path, BIOHUB_STEAL_TWIN_DEBUG_JSONL=str(tmp_path / "forbidden.jsonl"))
    monkeypatch.setattr(pipeline_module, "plan_twin_only_v1", lambda *args: pytest.fail("planner called"))
    monkeypatch.setattr(pipeline_module, "score_twin_deepcenter", lambda *args: pytest.fail("scorer called"))
    nodes = {1: _node(1, 0)}
    original = nodes[1]
    out_nodes, edges, stats = filter_output_graph_pre_linefit(cfg, nodes, [])
    assert out_nodes is nodes and out_nodes[1] is original and edges == []
    assert all(stats[key] == 0 for key in divisions_module._TWIN_COUNTER_KEYS)
    assert not (tmp_path / "forbidden.jsonl").exists()


def test_steal_twin_r1c_hook_order_planner_rows_callback_and_shared_caches(
    tmp_path: Path, monkeypatch
):
    cfg = _r1c_cfg(tmp_path)
    nodes = {1: _twin_node(1, 0, 0.0), 2: _twin_node(2, 1, 1.0)}
    edge = {"source_id": 1, "target_id": 2, "edge_prob": 0.5}
    events: list[str] = []
    cache_ids: dict[str, tuple[int, int]] = {}

    def gap(_cfg, current_nodes, current_edges, _stats, **kwargs):
        events.append("gap")
        cache_ids["gap"] = (id(kwargs["frame_cache"]), id(kwargs["deepcenter_cache"]))
        return current_nodes, current_edges

    def gap2(_cfg, current_nodes, current_edges, _stats, **_kwargs):
        events.append("gap2")
        return current_nodes, current_edges

    def safe(_cfg, _nodes, current_edges, _stats, **kwargs):
        events.append("safe")
        cache_ids["safe"] = (id(kwargs["frame_cache"]), id(kwargs["deepcenter_cache"]))
        return current_edges

    def planner(_cfg, _dataset, node_rows, edge_rows, callback):
        events.append("planner")
        assert type(node_rows) is tuple and type(edge_rows) is tuple
        assert list(node_rows) == list(nodes.values())
        assert edge_rows == (edge,)
        decision = callback(divisions_module.TwinSnapshotNode(4, 9, 1.0, 2.0, 3.0, False))
        assert decision.accepted
        return _r1c_empty_plan()

    bundle = {"bundle": True}

    def scorer(_cfg, dataset, t, point, seen_bundle, frame_cache, heatmap_cache):
        events.append("scorer")
        assert (dataset, t, point, seen_bundle) == ("ds0", 9, (1.0, 2.0, 3.0), bundle)
        cache_ids["scorer"] = (id(frame_cache), id(heatmap_cache))
        return divisions_module.TwinDeepCenterDecision(True, 0.2, None)

    def short(_cfg, current_nodes, current_edges, _stats):
        events.append("short")
        return current_nodes, current_edges

    def linefit(_cfg, current_nodes, _edges, _stats):
        events.append("linefit")
        return current_nodes

    monkeypatch.setattr(pipeline_module, "close_single_frame_gaps", gap)
    monkeypatch.setattr(pipeline_module, "recover_strict_gap2", gap2)
    monkeypatch.setattr(pipeline_module, "add_safe_divisions_postlink", safe)
    monkeypatch.setattr(pipeline_module, "plan_twin_only_v1", planner)
    monkeypatch.setattr(pipeline_module, "score_twin_deepcenter", scorer)
    monkeypatch.setattr(pipeline_module, "filter_short_track_components", short)
    monkeypatch.setattr(pipeline_module, "linefit_smooth_output_graph", linefit)
    filter_output_graph(cfg, nodes, [edge], dataset="ds0", deepcenter_bundle=bundle)
    assert events == ["gap", "gap2", "safe", "planner", "scorer", "short", "linefit"]
    assert cache_ids["gap"] == cache_ids["safe"] == cache_ids["scorer"]


def test_steal_twin_r1c_counter_merge_and_debug_allocation_are_exact(tmp_path: Path, monkeypatch):
    cfg = _r1c_cfg(tmp_path, tmp_path / "debug.jsonl")
    planner_values = {key: index for index, key in enumerate(divisions_module._TWIN_COUNTER_KEYS)}
    planner_values["steal_twin_debug_records_written"] = 0
    planner_values["steal_twin_debug_records_dropped"] = 0
    plan = replace(
        _r1c_empty_plan(),
        counters=divisions_module.TwinFrozenMapping(tuple(planner_values.items())),
        debug_records=(_r1c_record(),),
    )
    monkeypatch.setattr(pipeline_module, "plan_twin_only_v1", lambda *args: plan)
    collector = pipeline_module._TwinDebugCollector(0)
    stats = new_stats()
    pipeline_module._run_steal_twin_r1_dry_run(cfg, "ds0", {}, [], stats, None, {}, {}, collector)
    for key, value in planner_values.items():
        expected = 1 if key == "steal_twin_debug_records_dropped" else value
        assert stats[key] == expected
    assert collector.records_written == 0 and collector.records_dropped == 1


@pytest.mark.parametrize(
    "failure",
    ["missing", "extra", "reordered", "bool", "nonint", "negative", "debug", "destination"],
)
def test_steal_twin_r1c_counter_corruption_fails_before_allocation(
    tmp_path: Path, monkeypatch, failure: str
):
    cfg = _r1c_cfg(tmp_path, tmp_path / "debug.jsonl")
    items = [(key, 0) for key in divisions_module._TWIN_COUNTER_KEYS]
    stats = new_stats()
    if failure == "missing":
        items.pop()
    elif failure == "extra":
        items.append(("steal_twin_unreviewed", 0))
    elif failure == "reordered":
        items = list(reversed(items))
    elif failure == "bool":
        items[0] = (items[0][0], False)
    elif failure == "nonint":
        items[0] = (items[0][0], 0.0)
    elif failure == "negative":
        items[0] = (items[0][0], -1)
    elif failure == "debug":
        index = divisions_module._TWIN_COUNTER_KEYS.index("steal_twin_debug_records_written")
        items[index] = (items[index][0], 1)
    else:
        stats[divisions_module._TWIN_COUNTER_KEYS[0]] = 1
    monkeypatch.setattr(
        pipeline_module,
        "plan_twin_only_v1",
        lambda *args: _r1c_empty_plan(divisions_module.TwinFrozenMapping(tuple(items))),
    )

    class ForbiddenCollector:
        def allocate(self, _records):
            pytest.fail("collector called")

    baseline = dict(stats)
    with pytest.raises(RuntimeError):
        pipeline_module._run_steal_twin_r1_dry_run(
            cfg, "ds0", {}, [], stats, None, {}, {}, ForbiddenCollector()
        )
    assert stats == baseline


def test_steal_twin_r1c_validation_failed_plan_merges_and_downstream_continues(
    tmp_path: Path, monkeypatch
):
    cfg = _r1c_cfg(tmp_path)
    counters = [(key, 0) for key in divisions_module._TWIN_COUNTER_KEYS]
    by_key = dict(counters)
    by_key["steal_twin_validation_failed"] = 1
    by_key["steal_twin_validation_missing_node_field"] = 1
    failed_plan = replace(
        _r1c_empty_plan(divisions_module.TwinFrozenMapping(tuple(by_key.items()))),
        validation_reason="missing_node_field",
    )
    downstream: list[str] = []
    monkeypatch.setattr(pipeline_module, "plan_twin_only_v1", lambda *args: failed_plan)
    monkeypatch.setattr(
        pipeline_module,
        "filter_short_track_components",
        lambda _cfg, nodes, edges, _stats: (downstream.append("short") or nodes, edges),
    )
    nodes = {1: _twin_node(1, 0, 0.0)}
    _, _, stats = filter_output_graph_pre_linefit(cfg, nodes, [], dataset="ds0")
    assert downstream == ["short"]
    assert stats["steal_twin_validation_failed"] == 1
    assert stats["steal_twin_validation_missing_node_field"] == 1
    assert all(
        stats[key] == 0
        for key in divisions_module._TWIN_COUNTER_KEYS
        if key
        not in ("steal_twin_validation_failed", "steal_twin_validation_missing_node_field")
    )


def test_steal_twin_r1c_loader_rejects_duplicate_canonical_node_before_overwrite(
    tmp_path: Path, monkeypatch
):
    class Rows:
        def __init__(self, rows):
            self.rows = rows

        def iter_rows(self, named):
            assert named is True
            return iter(self.rows)

    class Graph:
        def node_attrs(self):
            return Rows(
                [
                    {"node_id": np.int64(1), "t": 0, "z": 0, "y": 0, "x": 0},
                    {"node_id": 1, "t": 1, "z": 1, "y": 1, "x": 1},
                ]
            )

        def edge_attrs(self):
            pytest.fail("edges read after duplicate")

    geff = tmp_path / "duplicate.geff"
    monkeypatch.setattr(pipeline_module, "load_geff_graph", lambda path: Graph())
    with pytest.raises(ValueError, match=r"duplicate\.geff: duplicate node_id 1"):
        pipeline_module._load_geff_as_dicts(geff)

    class UniqueGraph(Graph):
        def node_attrs(self):
            return Rows([{"node_id": np.int64(1), "t": 0, "z": 1, "y": 2, "x": 3}])

        def edge_attrs(self):
            return Rows([])

    monkeypatch.setattr(pipeline_module, "load_geff_graph", lambda path: UniqueGraph())
    assert pipeline_module._load_geff_as_dicts(geff) == (
        {1: {"node_id": 1, "t": 0, "z": 1.0, "y": 2.0, "x": 3.0}},
        [],
    )


@pytest.mark.parametrize("reason", [None, "conflict", "frame_cap", "video_cap"])
def test_steal_twin_r1c_exact_debug_top_level_json(reason: str | None, tmp_path: Path):
    record = _r1c_record(reason=reason)
    collector = pipeline_module._TwinDebugCollector(1)
    assert collector.allocate((record,)) == (1, 0)
    target = tmp_path / "record.jsonl"
    collector.finalize(target)
    line = target.read_text()
    assert line.endswith("\n") and line.count("\n") == 1
    plain = json.loads(line)
    assert list(plain) == sorted(plain)
    assert plain == {
        "dataset": "ds0",
        "decision": "accepted" if reason is None else "rejected",
        "reason": reason,
        "p": 1,
        "q": 2,
        "a": 3,
        "b": 4,
        "a2": 5,
        "b2": 6,
        "sort_key": [6.9, -3.0, 4.0, 1, 2, 3, 4, 5, 6],
        "d_pq": 4.0,
        "d_pa": 0.0,
        "d_pb": 6.0,
        "d_ab": 6.0,
        "d_a2b2": 9.0,
        "divergence_growth": 3.0,
        "raw_deepcenter_score": 0.2,
        "deepcenter_threshold": 0.12,
        "deepcenter_decision": {"accepted": True, "raw_score": 0.2, "reason": None},
        "removed_edge": {
            "source_id": 2,
            "target_id": 4,
            "metadata": {
                "__twin_type__": "mapping",
                "items": [["source_id", 2], ["target_id", 4], ["edge_prob", 0.7]],
            },
        },
        "planned_edge": {"source_id": 1, "target_id": 4, "distance_um": 6.0, "edge_prob": None},
    }


def test_steal_twin_r1c_codec_covers_every_frozen_type_bits_order_and_unicode(tmp_path: Path):
    nan_a = struct.unpack(">d", bytes.fromhex("7ff8000000000001"))[0]
    nan_b = struct.unpack(">d", bytes.fromhex("fff8000000000002"))[0]
    dtype = divisions_module.TwinFrozenDType(
        "<i2",
        (("", "<i2"),),
        divisions_module.TwinFrozenMapping((("unit", "µm"),)),
        2,
        2,
        "=",
        None,
        False,
        False,
    )
    structured = divisions_module.TwinFrozenStructuredScalar((("field", (1, 2)),))
    scalar = divisions_module.TwinFrozenNumpyScalar(dtype, b"\x01\x02")
    array_bytes = divisions_module.TwinFrozenArray(dtype, (1,), (2,), True, True, b"\x03\x04", False)
    array_objects = divisions_module.TwinFrozenArray(dtype, (1,), (8,), True, True, (structured,), True)
    buffer = divisions_module.TwinFrozenBuffer("memoryview", "B", 1, (2,), (1,), True, b"ab")
    mapping = divisions_module.TwinFrozenMapping(
        (
            (7, (b"raw", complex(1.0, -2.0))),
            ("set", frozenset(("z", "a"))),
            ("nan_a", nan_a),
            ("nan_b", nan_b),
            ("inf", float("inf")),
            ("dtype", dtype),
            ("structured", structured),
            ("scalar", scalar),
            ("array_bytes", array_bytes),
            ("array_objects", array_objects),
            ("buffer", buffer),
            ("input_position", "caller-owned"),
        )
    )
    record = _r1c_record(metadata=mapping)
    mapping_clone = pickle.loads(pickle.dumps(mapping))
    assert mapping_clone is not mapping
    assert tuple(key for key, _value in mapping_clone.items_snapshot) == tuple(
        key for key, _value in mapping.items_snapshot
    )
    assert struct.pack(">d", mapping_clone.items_snapshot[2][1]).hex() == "7ff8000000000001"
    assert struct.pack(">d", mapping_clone.items_snapshot[3][1]).hex() == "fff8000000000002"
    first = pipeline_module._TwinDebugCollector(1)
    second = pipeline_module._TwinDebugCollector(1)
    first.allocate((record,))
    second.allocate((_r1c_record(metadata=mapping_clone),))
    path_a, path_b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    first.finalize(path_a)
    second.finalize(path_b)
    assert path_a.read_bytes() == path_b.read_bytes()
    assert b"\\u00b5m" in path_a.read_bytes()
    metadata_plain = json.loads(path_a.read_text())["removed_edge"]["metadata"]
    dtype_plain = {
        "__twin_type__": "numpy_dtype",
        "string": "<i2",
        "descriptor": {
            "__twin_type__": "tuple",
            "items": [
                {"__twin_type__": "tuple", "items": ["", "<i2"]},
            ],
        },
        "metadata": {
            "__twin_type__": "mapping",
            "items": [["unit", "µm"]],
        },
        "itemsize": 2,
        "alignment": 2,
        "byteorder": "=",
        "names": None,
        "hasobject": False,
        "aligned_struct": False,
    }
    structured_plain = {
        "__twin_type__": "numpy_structured_scalar",
        "fields": [["field", {"__twin_type__": "tuple", "items": [1, 2]}]],
    }
    assert metadata_plain == {
        "__twin_type__": "mapping",
        "items": [
            [
                7,
                {
                    "__twin_type__": "tuple",
                    "items": [
                        {"__twin_type__": "bytes", "hex": "726177"},
                        {"__twin_type__": "complex", "real": 1.0, "imag": -2.0},
                    ],
                },
            ],
            ["set", {"__twin_type__": "frozenset", "items": ["a", "z"]}],
            ["nan_a", {"__twin_type__": "float", "value": "nan", "bits_hex": "7ff8000000000001"}],
            ["nan_b", {"__twin_type__": "float", "value": "nan", "bits_hex": "fff8000000000002"}],
            ["inf", {"__twin_type__": "float", "value": "+inf", "bits_hex": "7ff0000000000000"}],
            ["dtype", dtype_plain],
            ["structured", structured_plain],
            ["scalar", {"__twin_type__": "numpy_scalar", "dtype": dtype_plain, "content": "0102"}],
            [
                "array_bytes",
                {
                    "__twin_type__": "numpy_array",
                    "dtype": dtype_plain,
                    "shape": [1],
                    "strides": [2],
                    "c_contiguous": True,
                    "f_contiguous": True,
                    "object_content": False,
                    "content_hex": "0304",
                },
            ],
            [
                "array_objects",
                {
                    "__twin_type__": "numpy_array",
                    "dtype": dtype_plain,
                    "shape": [1],
                    "strides": [8],
                    "c_contiguous": True,
                    "f_contiguous": True,
                    "object_content": True,
                    "content": {"__twin_type__": "tuple", "items": [structured_plain]},
                },
            ],
            [
                "buffer",
                {
                    "__twin_type__": "buffer",
                    "kind": "memoryview",
                    "format": "B",
                    "itemsize": 1,
                    "shape": [2],
                    "strides": [1],
                    "readonly": True,
                    "content_hex": "6162",
                },
            ],
            ["input_position", "caller-owned"],
        ],
    }
    items = dict((json.dumps(key, sort_keys=True), value) for key, value in metadata_plain["items"])
    assert items['"nan_a"']["bits_hex"] == "7ff8000000000001"
    assert items['"nan_b"']["bits_hex"] == "fff8000000000002"
    assert items['"inf"']["value"] == "+inf"
    assert items['"dtype"']["__twin_type__"] == "numpy_dtype"
    assert items['"structured"']["__twin_type__"] == "numpy_structured_scalar"
    assert items['"scalar"']["__twin_type__"] == "numpy_scalar"
    assert items['"array_bytes"']["content_hex"] == "0304"
    assert items['"array_objects"']["content"]["__twin_type__"] == "tuple"
    assert items['"buffer"']["content_hex"] == "6162"
    assert items['"input_position"'] == "caller-owned"
    assert "input_position" not in json.loads(path_a.read_text())["removed_edge"]


def test_steal_twin_r1c_mapping_order_is_lossless_and_frozenset_is_canonical():
    mapping_a = divisions_module.TwinFrozenMapping((("a", 1), ("b", 2)))
    mapping_b = divisions_module.TwinFrozenMapping((("b", 2), ("a", 1)))
    plain_a = pipeline_module._twin_frozen_value_plain(mapping_a)
    plain_b = pipeline_module._twin_frozen_value_plain(mapping_b)
    assert plain_a["items"] == [["a", 1], ["b", 2]]
    assert plain_b["items"] == [["b", 2], ["a", 1]]
    assert json.dumps(plain_a, sort_keys=True) != json.dumps(plain_b, sort_keys=True)
    set_a = frozenset(["a", "b", "c"])
    set_b = frozenset(reversed(["a", "b", "c"]))
    assert pipeline_module._twin_frozen_value_plain(set_a) == pipeline_module._twin_frozen_value_plain(set_b)


def _r1c_malformed_record(case: str):
    record = _r1c_record()
    if case == "record":
        return object()
    if case == "dataset":
        return replace(record, dataset=1)
    if case == "decision":
        return replace(record, decision="unknown")
    if case == "reason":
        return replace(record, decision="rejected", reason="unknown")
    if case == "role":
        return replace(record, p=True)
    if case == "sort_type":
        return replace(record, sort_key=list(record.sort_key))
    if case == "sort_length":
        return replace(record, sort_key=record.sort_key[:-1])
    if case == "sort_float":
        return replace(record, sort_key=(float("nan"), *record.sort_key[1:]))
    if case == "sort_roles":
        return replace(record, sort_key=(*record.sort_key[:3], 9, 2, 3, 4, 5, 6))
    if case == "distance_type":
        return replace(record, d_pq=4)
    if case == "distance_nonfinite":
        return replace(record, d_pq=float("inf"))
    if case == "threshold":
        return replace(record, deepcenter_threshold=0.13)
    if case == "deepcenter":
        return replace(record, deepcenter_decision=divisions_module.TwinDeepCenterDecision(False, 0.2, None))
    if case == "deepcenter_accepted_int":
        return replace(record, deepcenter_decision=divisions_module.TwinDeepCenterDecision(1, 0.2, None))
    if case == "deepcenter_accepted_numpy_bool":
        return replace(
            record,
            deepcenter_decision=divisions_module.TwinDeepCenterDecision(np.bool_(True), 0.2, None),
        )
    if case == "removed":
        return replace(record, removed_edge=divisions_module.TwinEdgeRecord(9, 4, record.removed_edge.metadata))
    if case == "planned_type":
        return replace(record, planned_edge=object())
    return replace(record, planned_edge=divisions_module.TwinPlannedEdge(1, 4, 6.1))


@pytest.mark.parametrize("capacity", [0, 1])
@pytest.mark.parametrize(
    ("case", "error_type"),
    [
        ("record", TypeError),
        ("dataset", TypeError),
        ("decision", ValueError),
        ("reason", ValueError),
        ("role", TypeError),
        ("sort_type", TypeError),
        ("sort_length", ValueError),
        ("sort_float", ValueError),
        ("sort_roles", ValueError),
        ("distance_type", TypeError),
        ("distance_nonfinite", ValueError),
        ("threshold", ValueError),
        ("deepcenter", ValueError),
        ("deepcenter_accepted_int", TypeError),
        ("deepcenter_accepted_numpy_bool", TypeError),
        ("removed", ValueError),
        ("planned_type", TypeError),
        ("planned_value", ValueError),
    ],
)
def test_steal_twin_r1c_all_common_record_failures_are_capacity_independent(
    capacity: int, case: str, error_type: type[Exception]
):
    collector = pipeline_module._TwinDebugCollector(capacity)
    with pytest.raises(error_type, match=r"record 0"):
        collector.allocate((_r1c_malformed_record(case),))
    assert collector.records_written == collector.records_dropped == 0


def test_steal_twin_r1c_mixed_dataset_and_nonsequence_fail_atomically():
    collector = pipeline_module._TwinDebugCollector(2)
    with pytest.raises(TypeError, match="Sequence"):
        collector.allocate(iter((_r1c_record(),)))
    with pytest.raises(ValueError, match=r"record 1.*dataset"):
        collector.allocate((_r1c_record("a"), _r1c_record("b")))
    assert collector.records_written == collector.records_dropped == 0


def test_steal_twin_r1c_dropped_metadata_is_not_encoded_but_retained_metadata_is():
    forged = divisions_module.TwinFrozenMapping((("unsupported", object()),))
    record = _r1c_record(metadata=forged)
    retained = pipeline_module._TwinDebugCollector(1)
    with pytest.raises(TypeError, match="unsupported frozen twin value"):
        retained.allocate((record,))
    assert retained.records_written == retained.records_dropped == 0
    dropped = pipeline_module._TwinDebugCollector(0)
    assert dropped.allocate((record,)) == (0, 1)
    assert dropped.records_written == 0 and dropped.records_dropped == 1


def test_steal_twin_r1c_global_capacity_and_finalized_state(tmp_path: Path):
    for invalid in (-1, True, 1.0):
        with pytest.raises(ValueError, match="nonnegative built-in int"):
            pipeline_module._TwinDebugCollector(invalid)

    empty = pipeline_module._TwinDebugCollector(0)
    zero_target = tmp_path / "zero.jsonl"
    assert empty.allocate(()) == (0, 0)
    empty.finalize(zero_target)
    assert zero_target.read_bytes() == b""

    collector = pipeline_module._TwinDebugCollector(2)
    assert collector.allocate((_r1c_record("a"),)) == (1, 0)
    assert collector.allocate((_r1c_record("b"),)) == (1, 0)
    assert collector.allocate((_r1c_record("c"),)) == (0, 1)
    assert collector.allocate(()) == (0, 0)
    target = tmp_path / "bounded.jsonl"
    collector.finalize(target)
    assert [json.loads(line)["dataset"] for line in target.read_text().splitlines()] == ["a", "b"]
    assert collector.records_written == 2 and collector.records_dropped == 1
    with pytest.raises(RuntimeError):
        collector.allocate(())
    with pytest.raises(RuntimeError):
        collector.finalize(target)


class _R1cFaultingFile:
    def __init__(self, wrapped, phase: str, *, cleanup_close_fails: bool = False):
        self._wrapped = wrapped
        self._phase = phase
        self._failed = False
        self._cleanup_close_fails = cleanup_close_fails
        self.name = wrapped.name

    def _fail_once(self, phase: str):
        if self._phase == phase and not self._failed:
            self._failed = True
            raise OSError(f"synthetic {phase}")

    def write(self, value):
        self._fail_once("write")
        return self._wrapped.write(value)

    def flush(self):
        self._fail_once("flush")
        return self._wrapped.flush()

    def fileno(self):
        return self._wrapped.fileno()

    def close(self):
        if self._cleanup_close_fails and self._failed:
            raise OSError("synthetic cleanup close")
        self._fail_once("close")
        return self._wrapped.close()


@pytest.mark.parametrize("phase", ["parent", "temp", "write", "flush", "fsync", "close", "replace"])
def test_steal_twin_r1c_every_finalize_failure_is_atomic_and_retryable(
    tmp_path: Path, monkeypatch, phase: str
):
    collector = pipeline_module._TwinDebugCollector(1)
    collector.allocate((_r1c_record(),))
    expected_lines = tuple(collector._lines)
    expected_bytes = "".join(expected_lines).encode("utf-8")
    target = tmp_path / "atomic" / "debug.jsonl"
    target.parent.mkdir()
    target.write_bytes(b"stale\n")
    real_factory = pipeline_module.tempfile.NamedTemporaryFile

    with monkeypatch.context() as patch:
        if phase == "parent":
            patch.setattr(Path, "mkdir", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("synthetic parent")))
        elif phase == "temp":
            patch.setattr(
                pipeline_module.tempfile,
                "NamedTemporaryFile",
                lambda **kwargs: (_ for _ in ()).throw(OSError("synthetic temp")),
            )
        elif phase in ("write", "flush", "close"):
            patch.setattr(
                pipeline_module.tempfile,
                "NamedTemporaryFile",
                lambda **kwargs: _R1cFaultingFile(real_factory(**kwargs), phase),
            )
        elif phase == "fsync":
            patch.setattr(pipeline_module.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("synthetic fsync")))
        else:
            patch.setattr(
                pipeline_module.os,
                "replace",
                lambda *_args: (_ for _ in ()).throw(OSError("synthetic replace")),
            )
        with pytest.raises(OSError, match=f"synthetic {phase}"):
            collector.finalize(target)

    assert target.read_bytes() == b"stale\n"
    assert tuple(collector._lines) == expected_lines
    assert collector._finalized is False
    assert collector.records_written == 1 and collector.records_dropped == 0
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []
    collector.finalize(target)
    assert target.read_bytes() == expected_bytes


@pytest.mark.parametrize("cleanup_failure", ["close", "unlink", "both"])
def test_steal_twin_r1c_cleanup_failure_never_masks_operational_error(
    tmp_path: Path, monkeypatch, cleanup_failure: str
):
    collector = pipeline_module._TwinDebugCollector(1)
    collector.allocate((_r1c_record(),))
    expected_lines = tuple(collector._lines)
    expected_bytes = "".join(expected_lines).encode("utf-8")
    target = tmp_path / "debug.jsonl"
    target.write_bytes(b"stale")
    real_factory = pipeline_module.tempfile.NamedTemporaryFile
    real_unlink = Path.unlink
    with monkeypatch.context() as patch:
        patch.setattr(
            pipeline_module.tempfile,
            "NamedTemporaryFile",
            lambda **kwargs: _R1cFaultingFile(
                real_factory(**kwargs),
                "write",
                cleanup_close_fails=cleanup_failure in ("close", "both"),
            ),
        )
        if cleanup_failure in ("unlink", "both"):
            patch.setattr(
                Path,
                "unlink",
                lambda *args, **kwargs: (_ for _ in ()).throw(OSError("cleanup unlink")),
            )
        with pytest.raises(OSError, match="synthetic write"):
            collector.finalize(target)
    residual = list(tmp_path.glob(f".{target.name}.*.tmp"))
    assert len(residual) == (1 if cleanup_failure in ("unlink", "both") else 0)
    assert target.read_bytes() == b"stale"
    assert tuple(collector._lines) == expected_lines
    assert collector._finalized is False
    assert collector.records_written == 1 and collector.records_dropped == 0
    if residual:
        real_unlink(residual[0])
    collector.finalize(target)
    assert target.read_bytes() == expected_bytes


def _r1c_assert_alias_rejected_by_both_runs(
    tmp_path: Path,
    monkeypatch,
    geff_dir: Path,
    debug_path: Path,
) -> None:
    cfg = _r1c_cfg(tmp_path, debug_path)
    monkeypatch.setattr(
        pipeline_module,
        "load_deepcenter_veto_detector",
        lambda _cfg: pytest.fail("detector loaded before alias rejection"),
    )
    with pytest.raises(ValueError) as run_error:
        pipeline_module.run_postproc(geff_dir, tmp_path / "submission.csv", cfg)
    assert str(debug_path) in str(run_error.value)
    with pytest.raises(ValueError) as checkpoint_error:
        pipeline_module.save_prelinefit_checkpoint(geff_dir, tmp_path / "checkpoint", cfg)
    assert str(debug_path) in str(checkpoint_error.value)
    assert not (tmp_path / "submission.csv").exists()
    assert not (tmp_path / "checkpoint").exists()


@pytest.mark.parametrize("location", ["root", "child", "deep"])
@pytest.mark.parametrize("symlink_bundle", [False, True])
def test_steal_twin_r1c_rejects_complete_bundle_tree_before_activity(
    tmp_path: Path, monkeypatch, location: str, symlink_bundle: bool
):
    real_bundle = tmp_path / "real_bundle"
    real_bundle.mkdir()
    (real_bundle / "a.geff").mkdir()
    if symlink_bundle:
        geff_dir = tmp_path / "bundle_link"
        geff_dir.symlink_to(real_bundle, target_is_directory=True)
    else:
        geff_dir = real_bundle
    debug_path = {
        "root": real_bundle,
        "child": real_bundle / "debug.jsonl",
        "deep": real_bundle / "nested" / "debug.jsonl",
    }[location]
    _r1c_assert_alias_rejected_by_both_runs(tmp_path, monkeypatch, geff_dir, debug_path)


@pytest.mark.parametrize("debug_kind", ["inside", "below_symlink", "leaf_symlink"])
def test_steal_twin_r1c_rejects_resolved_symlinked_geff_tree(
    tmp_path: Path, monkeypatch, debug_kind: str
):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    external_geff = tmp_path / "external" / "a-real.geff"
    external_geff.mkdir(parents=True)
    (bundle / "a.geff").symlink_to(external_geff, target_is_directory=True)
    if debug_kind == "inside":
        debug = external_geff / "debug.jsonl"
    elif debug_kind == "below_symlink":
        debug = bundle / "a.geff" / "nested" / "debug.jsonl"
    else:
        outside = tmp_path / "outside.jsonl"
        outside.write_text("outside")
        debug = external_geff / "debug-link.jsonl"
        debug.symlink_to(outside)
    _r1c_assert_alias_rejected_by_both_runs(tmp_path, monkeypatch, bundle, debug)


@pytest.mark.parametrize("kind", ["equal", "hardlink", "bundle_sibling"])
def test_steal_twin_r1c_regular_file_geff_alias_rules(
    tmp_path: Path, monkeypatch, kind: str
):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    geff = bundle / "a.geff"
    geff.write_bytes(b"geff")
    if kind == "equal":
        debug = geff
    elif kind == "hardlink":
        debug = tmp_path / "hardlink.jsonl"
        os.link(geff, debug)
    else:
        debug = bundle / "debug.jsonl"
    _r1c_assert_alias_rejected_by_both_runs(tmp_path, monkeypatch, bundle, debug)


def test_steal_twin_r1c_regular_geff_external_sibling_and_unrelated_target_are_allowed(
    tmp_path: Path,
):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    geff_target = external / "a-real.geff"
    geff_target.write_bytes(b"geff")
    geff = bundle / "a.geff"
    geff.symlink_to(geff_target)
    for debug in (external / "sibling.jsonl", tmp_path / "unrelated.jsonl"):
        pipeline_module._reject_twin_debug_aliases(bundle, (geff,), debug, ())


def test_steal_twin_r1c_rejects_run_and_checkpoint_artifact_aliases(
    tmp_path: Path, monkeypatch
):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "a.geff").mkdir()
    out_csv = tmp_path / "submission.csv"
    stats_path = tmp_path / "stats.csv"
    checkpoint = tmp_path / "checkpoint"
    monkeypatch.setattr(
        pipeline_module,
        "load_deepcenter_veto_detector",
        lambda _cfg: pytest.fail("detector loaded before artifact alias rejection"),
    )
    for debug in (out_csv, stats_path):
        cfg = _r1c_cfg(tmp_path, debug)
        with pytest.raises(ValueError):
            pipeline_module.run_postproc(bundle, out_csv, cfg, run_stats_path=stats_path)
    for debug in (
        checkpoint,
        checkpoint / pipeline_module.CHECKPOINT_MANIFEST_NAME,
        checkpoint / "a.pkl",
    ):
        cfg = _r1c_cfg(tmp_path, debug)
        with pytest.raises(ValueError):
            pipeline_module.save_prelinefit_checkpoint(bundle, checkpoint, cfg)
    assert not out_csv.exists() and not checkpoint.exists()


@pytest.mark.parametrize("artifact_kind", ["out_csv", "run_stats"])
@pytest.mark.parametrize("debug_kind", ["directory", "symlink"])
def test_steal_twin_r1c_rejects_run_artifact_below_debug_target_before_activity(
    tmp_path: Path,
    monkeypatch,
    artifact_kind: str,
    debug_kind: str,
):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "a.geff").mkdir()
    protected_root = tmp_path / "protected-root"
    protected_root.mkdir()
    sentinel = protected_root / "sentinel.txt"
    sentinel.write_bytes(b"sentinel")
    if debug_kind == "symlink":
        debug = tmp_path / "protected-link"
        debug.symlink_to(protected_root, target_is_directory=True)
    else:
        debug = protected_root
    out_csv = debug / "submission.csv" if artifact_kind == "out_csv" else tmp_path / "submission.csv"
    stats_path = debug / "run_stats.csv" if artifact_kind == "run_stats" else tmp_path / "run_stats.csv"
    cfg = _r1c_cfg(tmp_path, debug)
    monkeypatch.setattr(
        pipeline_module,
        "load_deepcenter_veto_detector",
        lambda _cfg: pytest.fail("detector loaded before ancestor alias rejection"),
    )
    with pytest.raises(ValueError) as error:
        pipeline_module.run_postproc(bundle, out_csv, cfg, run_stats_path=stats_path)
    assert str(debug) in str(error.value)
    assert sentinel.read_bytes() == b"sentinel"
    assert not out_csv.exists() and not stats_path.exists()
    if debug_kind == "symlink":
        assert debug.is_symlink() and debug.resolve() == protected_root.resolve()
    else:
        assert debug.is_dir()


@pytest.mark.parametrize("debug_kind", ["directory", "symlink"])
def test_steal_twin_r1c_rejects_checkpoint_below_debug_target_before_activity(
    tmp_path: Path, monkeypatch, debug_kind: str
):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "a.geff").mkdir()
    protected_root = tmp_path / "protected-root"
    protected_root.mkdir()
    sentinel = protected_root / "sentinel.txt"
    sentinel.write_bytes(b"sentinel")
    if debug_kind == "symlink":
        debug = tmp_path / "protected-link"
        debug.symlink_to(protected_root, target_is_directory=True)
    else:
        debug = protected_root
    checkpoint = debug / "checkpoint"
    cfg = _r1c_cfg(tmp_path, debug)
    monkeypatch.setattr(
        pipeline_module,
        "load_deepcenter_veto_detector",
        lambda _cfg: pytest.fail("detector loaded before ancestor alias rejection"),
    )
    with pytest.raises(ValueError) as error:
        pipeline_module.save_prelinefit_checkpoint(bundle, checkpoint, cfg)
    assert str(debug) in str(error.value)
    assert sentinel.read_bytes() == b"sentinel" and not checkpoint.exists()
    if debug_kind == "symlink":
        assert debug.is_symlink() and debug.resolve() == protected_root.resolve()
    else:
        assert debug.is_dir()


@pytest.mark.parametrize(
    "artifact_kind",
    ["out_csv", "run_stats", "checkpoint_manifest", "checkpoint_pickle"],
)
@pytest.mark.parametrize("preexisting", [False, True])
def test_steal_twin_r1c_rejects_debug_below_ordinary_artifact_before_activity(
    tmp_path: Path,
    monkeypatch,
    artifact_kind: str,
    preexisting: bool,
):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "a.geff").mkdir()
    out_csv = tmp_path / "submission.csv"
    stats_path = tmp_path / "run_stats.csv"
    checkpoint = tmp_path / "checkpoint"
    protected = {
        "out_csv": out_csv,
        "run_stats": stats_path,
        "checkpoint_manifest": checkpoint / pipeline_module.CHECKPOINT_MANIFEST_NAME,
        "checkpoint_pickle": checkpoint / "a.pkl",
    }[artifact_kind]
    if preexisting:
        protected.parent.mkdir(parents=True, exist_ok=True)
        protected.write_bytes(b"protected-sentinel")
    debug = protected / "debug.jsonl"
    cfg = _r1c_cfg(tmp_path, debug)
    monkeypatch.setattr(
        pipeline_module,
        "load_deepcenter_veto_detector",
        lambda _cfg: pytest.fail("detector loaded before descendant alias rejection"),
    )

    with pytest.raises(ValueError) as error:
        if artifact_kind.startswith("checkpoint_"):
            pipeline_module.save_prelinefit_checkpoint(bundle, checkpoint, cfg)
        else:
            pipeline_module.run_postproc(bundle, out_csv, cfg, run_stats_path=stats_path)

    assert str(debug) in str(error.value)
    assert not debug.exists()
    if preexisting:
        assert protected.read_bytes() == b"protected-sentinel"
    else:
        assert not protected.exists()
    if artifact_kind == "out_csv":
        assert not stats_path.exists()
    elif artifact_kind == "run_stats":
        assert not out_csv.exists()


@pytest.mark.parametrize("input_kind", ["bundle_ancestor", "external_geff_ancestor"])
@pytest.mark.parametrize("debug_kind", ["directory", "symlink"])
def test_steal_twin_r1c_rejects_input_below_debug_target_before_both_runs(
    tmp_path: Path,
    monkeypatch,
    input_kind: str,
    debug_kind: str,
):
    real_root = tmp_path / "real-input"
    real_root.mkdir()
    sentinel = real_root / "sentinel.txt"
    sentinel.write_bytes(b"sentinel")
    if debug_kind == "symlink":
        debug = tmp_path / "input-link"
        debug.symlink_to(real_root, target_is_directory=True)
    else:
        debug = real_root

    if input_kind == "bundle_ancestor":
        geff_dir = debug / "bundle"
        geff_dir.mkdir()
        (geff_dir / "a.geff").mkdir()
        protected_geff = geff_dir / "a.geff"
    else:
        geff_dir = tmp_path / "bundle"
        geff_dir.mkdir()
        real_geff = debug / "a-real.geff"
        real_geff.mkdir()
        protected_geff = geff_dir / "a.geff"
        protected_geff.symlink_to(real_geff, target_is_directory=True)

    _r1c_assert_alias_rejected_by_both_runs(tmp_path, monkeypatch, geff_dir, debug)
    assert sentinel.read_bytes() == b"sentinel"
    assert protected_geff.resolve(strict=True).is_dir()
    if debug_kind == "symlink":
        assert debug.is_symlink() and debug.resolve() == real_root.resolve()
    else:
        assert debug.is_dir()


def test_steal_twin_r1c_run_entry_guards_precede_detector_and_outputs(tmp_path: Path, monkeypatch):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "a.geff").mkdir()
    cfg = build_config(test_dir=tmp_path, profile="e23_twin_only_v1")
    monkeypatch.setattr(
        pipeline_module,
        "load_deepcenter_veto_detector",
        lambda _cfg: pytest.fail("detector loaded"),
    )
    with pytest.raises(RuntimeError, match="ST-R1"):
        pipeline_module.run_postproc(bundle, tmp_path / "submission.csv", cfg)
    with pytest.raises(RuntimeError, match="ST-R1"):
        pipeline_module.save_prelinefit_checkpoint(bundle, tmp_path / "checkpoint", cfg)
    assert not (tmp_path / "submission.csv").exists()
    assert not (tmp_path / "checkpoint").exists()


def test_steal_twin_r1c_dry_run_preserves_graph_rows_metadata_and_never_applies_plan(
    tmp_path: Path, monkeypatch
):
    cfg_on = _r1c_cfg(tmp_path)
    cfg_off = replace(cfg_on, OUTPUT_STEAL_TWIN_REWIRE=False)
    monkeypatch.setattr(
        pipeline_module,
        "score_twin_deepcenter",
        lambda *args: divisions_module.TwinDeepCenterDecision(True, 0.2, None),
    )
    on_nodes_list, on_edges = _twin_motif()
    off_nodes_list = [dict(node) for node in on_nodes_list]
    off_edges = [dict(edge) for edge in on_edges]
    on_nodes = {int(node["node_id"]): node for node in on_nodes_list}
    off_nodes = {int(node["node_id"]): node for node in off_nodes_list}
    on_node_ids = {key: id(value) for key, value in on_nodes.items()}
    on_edge_ids = [id(edge) for edge in on_edges]
    nested = on_edges[2]["nested"]

    result_on = filter_output_graph_pre_linefit(cfg_on, on_nodes, on_edges, dataset="ds0")
    result_off = filter_output_graph_pre_linefit(cfg_off, off_nodes, off_edges, dataset="ds0")
    on_out_nodes, on_out_edges, on_stats = result_on
    off_out_nodes, off_out_edges, off_stats = result_off
    assert on_out_nodes == off_out_nodes
    assert on_out_edges == off_out_edges
    assert {key: id(value) for key, value in on_out_nodes.items()} == on_node_ids
    assert [id(edge) for edge in on_out_edges] == on_edge_ids
    assert on_out_edges[2]["nested"] is nested
    assert on_stats["steal_twin_accepted"] == 1
    assert on_stats["steal_twin_edges_removed"] == on_stats["steal_twin_edges_added"] == 0
    assert next(edge for edge in on_out_edges if edge["source_id"] == 2 and edge["target_id"] == 4) is on_edges[2]
    assert not any(edge["source_id"] == 1 and edge["target_id"] == 4 for edge in on_out_edges)
    assert all(off_stats[key] == 0 for key in divisions_module._TWIN_COUNTER_KEYS)
    non_twin = [key for key in on_stats if not key.startswith("steal_twin_")]
    assert {key: on_stats[key] for key in non_twin} == {key: off_stats[key] for key in non_twin}

    repeated_nodes, repeated_edges, repeated_stats = filter_output_graph_pre_linefit(
        cfg_on, on_nodes, on_edges, dataset="ds0"
    )
    assert repeated_nodes is on_out_nodes
    assert [id(edge) for edge in repeated_edges] == on_edge_ids
    assert repeated_edges == on_out_edges and repeated_stats == on_stats


def test_steal_twin_r1c_master_off_and_dry_run_write_identical_csv_rows(
    tmp_path: Path, monkeypatch
):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "ds0.geff").mkdir()
    cfg_on = _r1c_cfg(tmp_path)
    cfg_off = replace(cfg_on, OUTPUT_STEAL_TWIN_REWIRE=False)

    def load(_path):
        nodes, edges = _twin_motif()
        return {int(node["node_id"]): node for node in nodes}, edges

    monkeypatch.setattr(pipeline_module, "_load_geff_as_dicts", load)
    monkeypatch.setattr(pipeline_module, "load_deepcenter_veto_detector", lambda _cfg: None)
    monkeypatch.setattr(
        pipeline_module,
        "score_twin_deepcenter",
        lambda *args: divisions_module.TwinDeepCenterDecision(True, 0.2, None),
    )
    off_csv = tmp_path / "off.csv"
    on_csv = tmp_path / "on.csv"
    pipeline_module.run_postproc(bundle, off_csv, cfg_off, tmp_path / "off-stats.csv")
    pipeline_module.run_postproc(bundle, on_csv, cfg_on, tmp_path / "on-stats.csv")
    assert on_csv.read_bytes() == off_csv.read_bytes()


def test_steal_twin_r1c_run_and_checkpoint_share_one_collector_and_serialize_final_counts(
    tmp_path: Path, monkeypatch
):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    for dataset in ("b", "a"):
        (bundle / f"{dataset}.geff").mkdir()

    def load(_path):
        nodes, edges = _twin_motif()
        return {int(node["node_id"]): node for node in nodes}, edges

    monkeypatch.setattr(pipeline_module, "_load_geff_as_dicts", load)
    monkeypatch.setattr(pipeline_module, "load_deepcenter_veto_detector", lambda _cfg: None)
    monkeypatch.setattr(
        pipeline_module,
        "score_twin_deepcenter",
        lambda *args: divisions_module.TwinDeepCenterDecision(True, 0.2, None),
    )
    real_adapter = pipeline_module._run_steal_twin_r1_dry_run
    collector_ids: list[int] = []
    dataset_stats_seen: list[tuple[str, int, int]] = []
    run_stats_seen: list[list[tuple[str, int, int]]] = []
    pickle_stats_seen: list[tuple[str, int, int]] = []
    finalize_totals: dict[str, tuple[int, int]] = {}

    def adapter(*args):
        collector_ids.append(id(args[-1]))
        return real_adapter(*args)

    monkeypatch.setattr(pipeline_module, "_run_steal_twin_r1_dry_run", adapter)
    real_dataset_stats_row = pipeline_module._dataset_stats_row

    def dataset_stats_row(dataset, nodes, edges, stats, raw_count, sources):
        dataset_stats_seen.append(
            (
                dataset,
                stats["steal_twin_debug_records_written"],
                stats["steal_twin_debug_records_dropped"],
            )
        )
        return real_dataset_stats_row(dataset, nodes, edges, stats, raw_count, sources)

    monkeypatch.setattr(pipeline_module, "_dataset_stats_row", dataset_stats_row)
    real_write_run_stats = pipeline_module.write_run_stats

    def write_run_stats(rows, path):
        run_stats_seen.append(
            [
                (
                    row["dataset"],
                    row["steal_twin_debug_records_written"],
                    row["steal_twin_debug_records_dropped"],
                )
                for row in rows
            ]
        )
        return real_write_run_stats(rows, path)

    monkeypatch.setattr(pipeline_module, "write_run_stats", write_run_stats)
    real_pickle_dump = pipeline_module.pickle.dump

    def pickle_dump(payload, handle, *, protocol):
        pickle_stats_seen.append(
            (
                payload["dataset"],
                payload["stats"]["steal_twin_debug_records_written"],
                payload["stats"]["steal_twin_debug_records_dropped"],
            )
        )
        return real_pickle_dump(payload, handle, protocol=protocol)

    monkeypatch.setattr(pipeline_module.pickle, "dump", pickle_dump)
    real_finalize = pipeline_module._TwinDebugCollector.finalize
    finalized_after: list[str] = []

    def finalize(self, path):
        finalize_totals[path.name] = (self.records_written, self.records_dropped)
        if path.name == "run.jsonl":
            assert (tmp_path / "submission.csv").read_text().startswith("id,dataset")
            assert (tmp_path / "run_stats.csv").exists()
        else:
            checkpoint = tmp_path / "checkpoint"
            assert (checkpoint / "manifest.json").exists()
            assert all((checkpoint / f"{dataset}.pkl").exists() for dataset in ("a", "b"))
        finalized_after.append(path.name)
        return real_finalize(self, path)

    monkeypatch.setattr(pipeline_module._TwinDebugCollector, "finalize", finalize)

    run_debug = tmp_path / "run.jsonl"
    run_cfg = _r1c_cfg(tmp_path, run_debug)
    result = pipeline_module.run_postproc(bundle, tmp_path / "submission.csv", run_cfg)
    assert result["datasets"] == ["a", "b"]
    assert [json.loads(line)["dataset"] for line in run_debug.read_text().splitlines()] == ["a", "b"]
    with (tmp_path / "run_stats.csv").open(newline="") as handle:
        stats_rows = list(csv.DictReader(handle))
    assert [row["dataset"] for row in stats_rows] == ["a", "b"]
    assert sum(int(row["steal_twin_debug_records_written"]) for row in stats_rows) == 2
    assert len(set(collector_ids)) == 1
    assert dataset_stats_seen == [("a", 1, 0), ("b", 1, 0)]
    assert run_stats_seen == [[("a", 1, 0), ("b", 1, 0)]]
    assert finalize_totals["run.jsonl"] == (2, 0)

    collector_ids.clear()
    checkpoint_debug = tmp_path / "checkpoint.jsonl"
    checkpoint_cfg = _r1c_cfg(tmp_path, checkpoint_debug)
    manifest = pipeline_module.save_prelinefit_checkpoint(
        bundle, tmp_path / "checkpoint", checkpoint_cfg
    )
    assert manifest["datasets"] == ["a", "b"]
    assert [json.loads(line)["dataset"] for line in checkpoint_debug.read_text().splitlines()] == ["a", "b"]
    checkpoint_written = 0
    for dataset in ("a", "b"):
        with (tmp_path / "checkpoint" / f"{dataset}.pkl").open("rb") as handle:
            payload = pickle.load(handle)
        checkpoint_written += payload["stats"]["steal_twin_debug_records_written"]
    assert checkpoint_written == 2 and len(set(collector_ids)) == 1
    assert pickle_stats_seen == [("a", 1, 0), ("b", 1, 0)]
    assert finalize_totals["checkpoint.jsonl"] == (2, 0)
    assert finalized_after == ["run.jsonl", "checkpoint.jsonl"]


@pytest.mark.parametrize("entrypoint", ["run", "checkpoint"])
@pytest.mark.parametrize("preexisting", [False, True])
def test_steal_twin_r1c_second_dataset_failure_never_publishes_debug(
    tmp_path: Path, monkeypatch, entrypoint: str, preexisting: bool
):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    for dataset in ("a", "b"):
        (bundle / f"{dataset}.geff").mkdir()
    debug = tmp_path / f"{entrypoint}.jsonl"
    if preexisting:
        debug.write_bytes(b"stale-debug")
    cfg = _r1c_cfg(tmp_path, debug)
    calls = 0

    def load(_path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("second dataset")
        return {1: _twin_node(1, 0, 0.0)}, []

    monkeypatch.setattr(pipeline_module, "_load_geff_as_dicts", load)
    monkeypatch.setattr(pipeline_module, "load_deepcenter_veto_detector", lambda _cfg: None)
    with pytest.raises(RuntimeError, match="second dataset"):
        if entrypoint == "run":
            pipeline_module.run_postproc(bundle, tmp_path / "submission.csv", cfg)
        else:
            pipeline_module.save_prelinefit_checkpoint(bundle, tmp_path / "checkpoint", cfg)
    if preexisting:
        assert debug.read_bytes() == b"stale-debug"
    else:
        assert not debug.exists()


@pytest.mark.parametrize(
    ("phase", "entrypoint"),
    [
        ("downstream", "run"),
        ("downstream", "checkpoint"),
        ("csv", "run"),
        ("stats", "run"),
        ("pickle", "checkpoint"),
        ("manifest", "checkpoint"),
    ],
)
@pytest.mark.parametrize("preexisting", [False, True])
def test_steal_twin_r1c_downstream_artifact_failures_never_publish_debug(
    tmp_path: Path,
    monkeypatch,
    phase: str,
    entrypoint: str,
    preexisting: bool,
):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "a.geff").mkdir()
    debug = tmp_path / f"{entrypoint}-{phase}.jsonl"
    if preexisting:
        debug.write_bytes(b"stale-debug")
    cfg = _r1c_cfg(tmp_path, debug)
    monkeypatch.setattr(
        pipeline_module,
        "_load_geff_as_dicts",
        lambda _path: ({1: _twin_node(1, 0, 0.0)}, []),
    )
    monkeypatch.setattr(pipeline_module, "load_deepcenter_veto_detector", lambda _cfg: None)
    if phase == "downstream":
        monkeypatch.setattr(
            pipeline_module,
            "filter_short_track_components",
            lambda *_args: (_ for _ in ()).throw(RuntimeError("synthetic downstream")),
        )
    elif phase == "csv":
        monkeypatch.setattr(
            pipeline_module.SubmissionCsvWriter,
            "write_nodes",
            lambda *_args: (_ for _ in ()).throw(RuntimeError("synthetic csv")),
        )
    elif phase == "stats":
        monkeypatch.setattr(
            pipeline_module,
            "_finish_run",
            lambda *_args: (_ for _ in ()).throw(RuntimeError("synthetic stats")),
        )
    elif phase == "pickle":
        monkeypatch.setattr(
            pipeline_module.pickle,
            "dump",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic pickle")),
        )
    else:
        real_write_text = Path.write_text

        def write_text(path, *args, **kwargs):
            if path.name == pipeline_module.CHECKPOINT_MANIFEST_NAME:
                raise RuntimeError("synthetic manifest")
            return real_write_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", write_text)

    with pytest.raises(RuntimeError, match=f"synthetic {phase}"):
        if entrypoint == "run":
            pipeline_module.run_postproc(bundle, tmp_path / "submission.csv", cfg)
        else:
            pipeline_module.save_prelinefit_checkpoint(bundle, tmp_path / "checkpoint", cfg)
    if preexisting:
        assert debug.read_bytes() == b"stale-debug"
    else:
        assert not debug.exists()


def test_steal_twin_r1c_run_relinefit_never_constructs_or_publishes_collector(
    tmp_path: Path, monkeypatch
):
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "manifest.json").write_text(json.dumps({"datasets": ["ds0"]}))
    stats = new_stats()
    payload = {
        "dataset": "ds0",
        "raw_node_count": 1,
        "nodes_by_id": {1: _twin_node(1, 0, 0.0)},
        "edges": [],
        "stats": stats,
    }
    with (checkpoint / "ds0.pkl").open("wb") as handle:
        pickle.dump(payload, handle)
    monkeypatch.setattr(
        pipeline_module,
        "_TwinDebugCollector",
        lambda *_args: pytest.fail("collector constructed during relinefit"),
    )
    cfg = _r1c_cfg(tmp_path, tmp_path / "must-not-exist.jsonl")
    result = pipeline_module.run_relinefit(checkpoint, tmp_path / "submission.csv", cfg)
    assert result["datasets"] == ["ds0"]
    assert not (tmp_path / "must-not-exist.jsonl").exists()
