"""Tests for the post-link observer."""

import dataclasses
import json
import sys

import pytest

from scripts.e27_postlink_observer import observe_postlink

CFG = object()
STATS = object()


def make_graph():
    nodes = {
        1: {"t": 0, "z": 0.0, "y": 0.0, "x": 0.0},
        2: {"t": 1, "z": 0.0, "y": 0.0, "x": 0.0},
        3: {"t": 2, "z": 0.0, "y": 0.0, "x": 0.0},
        4: {"t": 3, "z": 0.0, "y": 0.0, "x": 0.0},
        5: {"t": 0, "z": 0.0, "y": 0.0, "x": 100.0},
        6: {"t": 1, "z": 0.0, "y": 0.0, "x": 100.0},
    }
    edges = [
        {"source_id": 1, "target_id": 2},
        {"source_id": 2, "target_id": 3},
        {"source_id": 3, "target_id": 4},
        {"source_id": 5, "target_id": 6},
    ]
    return nodes, edges


def motion(cfg, nodes_by_id, stats, learned_edge_probs=None):
    return [{"source_id": 1, "target_id": 3}]


def short(cfg, nodes_by_id, edges, stats):
    return ({1: nodes_by_id[1], 2: nodes_by_id[2], 3: nodes_by_id[3], 4: nodes_by_id[4]},
            [{"source_id": 1, "target_id": 3}])


def unrelated_motion(cfg, nodes_by_id, stats, learned_edge_probs=None):
    return []



def test_basic_order_and_identity():
    nodes, edges = make_graph()
    sentinel = object()

    def run():
        motion(CFG, nodes, STATS)
        short(CFG, nodes, edges, STATS)
        return sentinel

    result, snaps = observe_postlink(run, motion, short)
    assert result is sentinel
    assert len(snaps) == 3


def test_temporal_isolation():
    nodes, edges = make_graph()

    def run():
        motion(CFG, nodes, STATS)
        nodes[1]["x"] = 999.0
        edges.append({"source_id": 4, "target_id": 5})
        short(CFG, nodes, edges, STATS)
        return None

    _, snaps = observe_postlink(run, motion, short)
    assert snaps["motion_after"]["nodes"][0][4] == 0.0
    assert snaps["short_before"]["nodes"][0][4] == 999.0
    assert len(snaps["short_before"]["edges"]) == 5


def test_missing_motion_raises():
    def run():
        return None

    with pytest.raises(RuntimeError):
        observe_postlink(run, motion, short)


def test_duplicate_motion_raises():
    nodes, edges = make_graph()

    def run():
        motion(CFG, nodes, STATS)
        motion(CFG, nodes, STATS)
        short(CFG, nodes, edges, STATS)
        return None

    with pytest.raises(RuntimeError):
        observe_postlink(run, motion, short)


def test_reordered_raises():
    nodes, edges = make_graph()

    def run():
        short(CFG, nodes, edges, STATS)
        motion(CFG, nodes, STATS)
        return None

    with pytest.raises(RuntimeError):
        observe_postlink(run, motion, short)


def test_malformed_nonfinite_runs_full_sequence():
    nodes, _ = make_graph()
    nodes[1]["z"] = float("nan")

    def run():
        motion(CFG, nodes, STATS)
        short(CFG, nodes, [], STATS)
        return None

    with pytest.raises(RuntimeError):
        observe_postlink(run, motion, short)


def test_same_name_decoy_not_matched():

    def run():
        motion(CFG, {}, STATS)
        short(CFG, {}, [], STATS)
        return None

    unrelated_motion.__name__ = "motion"
    nodes, edges = make_graph()

    def run2():
        motion(CFG, nodes, STATS)
        unrelated_motion(CFG, nodes, STATS)
        short(CFG, nodes, edges, STATS)
        return None

    _, snaps = observe_postlink(run2, motion, short)
    assert len(snaps) == 3


def test_run_exception_preserved_and_profile_restored():
    boom = RuntimeError("boom")

    def run():
        raise boom

    with pytest.raises(RuntimeError) as excinfo:
        observe_postlink(run, motion, short)
    assert excinfo.value is boom
    assert sys.getprofile() is None


def test_preexisting_profiler_rejected():
    calls = []

    def probe(frame, event, arg):
        calls.append(event)

    sys.setprofile(probe)
    try:
        assert sys.getprofile() is probe
        with pytest.raises(RuntimeError):
            observe_postlink(lambda: None, motion, short)
        assert sys.getprofile() is probe
    finally:
        sys.setprofile(None)


def test_real_pipeline_parity(tmp_path):
    from biohub.public_postproc import graph_ops, pipeline
    from biohub.public_postproc.config import build_config

    cfg = build_config({}, test_dir=tmp_path)
    cfg = dataclasses.replace(
        cfg,
        OUTPUT_FILTER_SHORT_TRACKS=True,
        OUTPUT_MIN_TRACK_LEN=3,
        OUTPUT_KEEP_DIVISION_COMPONENTS=False,
        ADAPTIVE_SHORT_TRACK_RESCUE=False,
    )

    def plain():
        nodes, edges = make_graph()
        new_edges = graph_ops.motion_relink_edges(cfg, nodes, pipeline.new_stats())
        out_nodes, out_edges = graph_ops.filter_short_track_components(
            cfg, nodes, new_edges, pipeline.new_stats()
        )
        return (out_nodes, out_edges)

    expected = plain()

    def observed_run():
        nodes, edges = make_graph()
        new_edges = graph_ops.motion_relink_edges(cfg, nodes, pipeline.new_stats())
        captured["motion_edges"] = new_edges
        out = graph_ops.filter_short_track_components(
            cfg, nodes, new_edges, pipeline.new_stats()
        )
        return out

    captured = {}
    result, snaps = observe_postlink(
        observed_run,
        graph_ops.motion_relink_edges,
        graph_ops.filter_short_track_components,
    )
    assert result[0] == expected[0]
    assert result[1] == expected[1]
    assert len(snaps["short_before"]["nodes"]) == 6
    assert len(snaps["short_after"]["nodes"]) == 4
    assert snaps["motion_after"]["edges"] == \
        sorted([[e["source_id"], e["target_id"]] for e in captured["motion_edges"]])


def test_missing_short_after_motion_raises():
    nodes, _ = make_graph()

    def run():
        motion(CFG, nodes, STATS)
        return None

    with pytest.raises(RuntimeError):
        observe_postlink(run, motion, short)


def test_duplicate_short_after_motion_raises():
    nodes, edges = make_graph()

    def run():
        motion(CFG, nodes, STATS)
        short(CFG, nodes, edges, STATS)
        short(CFG, nodes, edges, STATS)
        return None

    with pytest.raises(RuntimeError):
        observe_postlink(run, motion, short)


@pytest.mark.parametrize("exc", [RuntimeError("target"), ValueError("target")])
def test_exception_raised_inside_observed_target_propagates(exc):
    nodes, edges = make_graph()

    def motion_boom(cfg, nodes_by_id, stats, learned_edge_probs=None):
        raise exc

    def short_ok(cfg, nodes_by_id, edges, stats):
        return (dict(nodes_by_id), list(edges))

    def run():
        motion_boom(CFG, nodes, STATS)
        short_ok(CFG, nodes, edges, STATS)
        return None

    with pytest.raises(type(exc)) as excinfo:
        observe_postlink(run, motion_boom, short_ok)
    assert excinfo.value is exc
    assert sys.getprofile() is None


@pytest.mark.parametrize("exc", [RuntimeError("target"), ValueError("target")])
def test_exception_raised_inside_short_target_propagates(exc):
    nodes, edges = make_graph()

    def short_boom(cfg, nodes_by_id, edges, stats):
        raise exc

    def run():
        motion(CFG, nodes, STATS)
        short_boom(CFG, nodes, edges, STATS)
        return None

    with pytest.raises(type(exc)) as excinfo:
        observe_postlink(run, motion, short_boom)
    assert excinfo.value is exc
    assert sys.getprofile() is None


def test_numpy_scalar_ids_time_and_coords_are_accepted():
    import numpy as np

    nodes = {
        np.int64(1): {"t": np.int64(0), "z": np.float32(0.0),
                      "y": np.float32(0.0), "x": np.float32(0.0), "gap_synthetic": np.int64(0)},
        np.int64(2): {"t": np.int64(1), "z": np.float32(0.0),
                      "y": np.float32(0.0), "x": np.float32(100.0), "gap_synthetic": np.int64(0)},
    }
    edges = [{"source_id": np.int64(1), "target_id": np.int64(2)}]

    def motion_np(cfg, nodes_by_id, stats, learned_edge_probs=None):
        return list(edges)

    def short_np(cfg, nodes_by_id, edges, stats):
        return ({np.int64(1): nodes_by_id[1],
                 np.int64(2): nodes_by_id[2]},
                [{"source_id": np.int64(1), "target_id": np.int64(2)}])

    def run():
        motion_np(CFG, nodes, STATS)
        short_np(CFG, nodes, edges, STATS)
        return None

    _, snaps = observe_postlink(run, motion_np, short_np)
    for key in ("motion_after", "short_before", "short_after"):
        snap = snaps[key]
        assert type(snap) is dict
        assert type(snap["nodes"]) is list
        assert type(snap["edges"]) is list
        for row in snap["nodes"]:
            assert type(row) is list
            assert all(type(value) is int for value in row[:2])
            assert all(type(value) is float for value in row[2:5])
            assert type(row[5]) is int
        for edge in snap["edges"]:
            assert type(edge) is list
            assert all(type(value) is int for value in edge)
    assert json.dumps(snaps, allow_nan=False)


def test_snapshots_are_detached_deep_copies():
    import copy

    nodes, edges = make_graph()
    captured = {}

    def run():
        captured["motion_edges"] = motion(CFG, nodes, STATS)
        out_nodes, out_edges = short(CFG, nodes, edges, STATS)
        captured["result"] = (out_nodes, out_edges)
        return captured["result"]

    result, snaps = observe_postlink(run, motion, short)
    assert result is captured["result"]

    before = copy.deepcopy(snaps)
    out_nodes, out_edges = result
    out_nodes[1]["x"] = 999.0
    out_nodes[2]["z"] = float("inf")
    out_edges.append({"source_id": 4, "target_id": 5})
    out_edges[0]["source_id"] = 42

    assert snaps == before
    assert snaps["short_after"]["nodes"][0][4] == 0.0
    assert len(snaps["short_after"]["edges"]) == 1
    assert result[0] is out_nodes
    assert result[1] is out_edges
