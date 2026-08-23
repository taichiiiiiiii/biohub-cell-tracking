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
