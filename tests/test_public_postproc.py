"""Synthetic-graph tests for the ported public-notebook post-processing stack.

No competition data or geff files required: nodes/edges are built by hand as
the same plain dicts ``filter_output_graph`` consumes, and each pass under
test is isolated by disabling every other ``BIOHUB_OUTPUT_*`` toggle.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import numpy as np
import pytest

from biohub.public_postproc import frames as frames_module
from biohub.public_postproc.config import PostprocConfig, build_config
from biohub.public_postproc.csv_out import CSV_COLUMNS, SubmissionCsvWriter
from biohub.public_postproc.frames import refine_all_centroids, refine_centroids, refine_synthetic_midpoint
from biohub.public_postproc.graph_ops import linefit_smooth_output_graph
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
    assert cfg.SAFE_DIV_MUTUAL_NN is False
    assert cfg.SAFE_DIV_DIVERGENCE is False


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
    assert cfg.SAFE_DIV_MUTUAL_NN is True
    assert cfg.SAFE_DIV_DIVERGENCE is True
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
