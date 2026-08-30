"""Synthetic-graph tests for the ported public-notebook post-processing stack.

No competition data or geff files required: nodes/edges are built by hand as
the same plain dicts ``filter_output_graph`` consumes, and each pass under
test is isolated by disabling every other ``BIOHUB_OUTPUT_*`` toggle.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from biohub.public_postproc.config import PostprocConfig, build_config
from biohub.public_postproc.csv_out import CSV_COLUMNS, SubmissionCsvWriter
from biohub.public_postproc.graph_ops import linefit_smooth_output_graph
from biohub.public_postproc.pipeline import filter_output_graph

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
