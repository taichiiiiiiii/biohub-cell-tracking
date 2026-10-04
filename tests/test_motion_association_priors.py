"""Tests for optional learned association priors on raw ILP-unselected edges.

Nothing here runs training or full inference; the pipeline entry points are
driven with every pass disabled except motion relink, and motion_relink_edges
is spied on so no actual relinking happens.  These tests do not claim real CV
or parity results.
"""

import copy
import math

import pytest

from biohub.public_postproc import pipeline as p
from biohub.public_postproc.config import build_config

OFF_ENV = {
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
    "BIOHUB_REFINE_ALL_CENTROIDS": "0",
}

MOTION_ENV = dict(OFF_ENV, BIOHUB_OUTPUT_MOTION_RELINK="1")


def _node(node_id, t, x=0.0, y=0.0):
    return {"node_id": node_id, "t": t, "x": x, "y": y, "z": 0.0, "r": 5.0}


def _edge(source_id, target_id, prob=0.9):
    return {"source_id": source_id, "target_id": target_id, "edge_prob": prob}


def _graph():
    nodes_by_id = {
        1: _node(1, 0),
        2: _node(2, 1),
        3: _node(3, 2),
        4: _node(4, 3),
        5: _node(5, 2),
    }
    raw_edges = [_edge(1, 2, 0.7), _edge(2, 3, 0.6)]
    return nodes_by_id, raw_edges


# --------------------------------------------------------------------------- #
# helper unit tests
# --------------------------------------------------------------------------- #
def test_helper_none_returns_empty():
    nodes_by_id, raw_edges = _graph()
    assert p._unselected_association_priors(None, raw_edges, nodes_by_id) == {}


def test_helper_empty_dict_returns_empty():
    nodes_by_id, raw_edges = _graph()
    assert p._unselected_association_priors({}, raw_edges, nodes_by_id) == {}


def test_helper_requires_dict_type():
    nodes_by_id, raw_edges = _graph()
    with pytest.raises(ValueError):
        p._unselected_association_priors([((3, 4), 0.5)], raw_edges, nodes_by_id)


def test_helper_selected_ignored_novel_added_missing_skipped():
    nodes_by_id, raw_edges = _graph()
    priors = {
        (1, 2): 0.99,  # already an ORIGINAL raw edge -> ignored
        (3, 4): 0.42,  # novel, both endpoints exist, adjacent -> kept
        (42, 43): 0.5,  # endpoints missing from nodes_by_id -> skipped
    }
    snapshot = copy.deepcopy(priors)
    out = p._unselected_association_priors(priors, raw_edges, nodes_by_id)
    assert out == {(3, 4): pytest.approx(0.42)}
    assert priors == snapshot
    assert out is not priors


def test_helper_selected_pair_still_validated_for_adjacency():
    # (2, 3) is selected and its endpoints are adjacent, so it is dropped.
    nodes_by_id, raw_edges = _graph()
    out = p._unselected_association_priors({(2, 3): 0.5}, raw_edges, nodes_by_id)
    assert out == {}

    bad_nodes = {1: _node(1, 0), 2: _node(2, 5)}
    with pytest.raises(ValueError):
        p._unselected_association_priors({(1, 2): 0.5}, raw_edges, bad_nodes)


def test_helper_does_not_mutate_inputs():
    nodes_by_id, raw_edges = _graph()
    nodes_snapshot = copy.deepcopy(nodes_by_id)
    edges_snapshot = copy.deepcopy(raw_edges)
    priors = {(3, 4): 1, (5, 4): 0.25}
    priors_snapshot = copy.deepcopy(priors)
    out = p._unselected_association_priors(priors, raw_edges, nodes_by_id)
    assert nodes_by_id == nodes_snapshot
    assert raw_edges == edges_snapshot
    assert priors == priors_snapshot
    assert out == {(3, 4): 1.0, (5, 4): 0.25}
    assert all(type(v) is float for v in out.values())


@pytest.mark.parametrize(
    "bad_key",
    [
        pytest.param(1, id="int-key"),
        pytest.param("12", id="str-key"),
        pytest.param((1,), id="len-1-tuple"),
        pytest.param((1, 2, 3), id="len-3-tuple"),
        pytest.param((1.0, 2), id="float-endpoint"),
        pytest.param((True, 2), id="bool-endpoint"),
        pytest.param((1, False), id="bool-endpoint-b"),
        pytest.param(("1", 2), id="str-endpoint"),
    ],
)
def test_helper_invalid_keys_raise(bad_key):
    nodes_by_id, raw_edges = _graph()
    with pytest.raises(ValueError):
        p._unselected_association_priors({bad_key: 0.5}, raw_edges, nodes_by_id)


@pytest.mark.parametrize(
    "bad_value",
    [
        pytest.param(True, id="bool-true"),
        pytest.param(False, id="bool-false"),
        pytest.param("0.5", id="str"),
        pytest.param(None, id="none"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="inf"),
        pytest.param(float("-inf"), id="neg-inf"),
        pytest.param(-0.1, id="negative"),
        pytest.param(1.0001, id="gt-one"),
        pytest.param(2, id="int-gt-one"),
        pytest.param(complex(0.5, 0.0), id="complex"),
        pytest.param(10**400, id="huge-int-over-one"),
        pytest.param(-(10**400), id="huge-negative-int"),
    ],
)
def test_helper_invalid_values_raise(bad_value):
    nodes_by_id, raw_edges = _graph()
    with pytest.raises(ValueError):
        p._unselected_association_priors({(3, 4): bad_value}, raw_edges, nodes_by_id)


def test_helper_non_adjacent_raises():
    nodes_by_id, raw_edges = _graph()
    with pytest.raises(ValueError):
        p._unselected_association_priors({(1, 3): 0.5}, raw_edges, nodes_by_id)


def test_helper_boundary_values_ok():
    nodes_by_id, raw_edges = _graph()
    out = p._unselected_association_priors(
        {(3, 4): 0, (5, 4): 1.0}, raw_edges, nodes_by_id
    )
    assert out == {(3, 4): 0.0, (5, 4): 1.0}
    assert all(math.isfinite(v) for v in out.values())


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda n: n[1].pop("t"), id="missing-source-t"),
        pytest.param(lambda n: n[2].pop("t"), id="missing-target-t"),
        pytest.param(lambda n: n[1].__setitem__("t", "0"), id="string-source-t"),
        pytest.param(lambda n: n[2].__setitem__("t", 1.0), id="float-target-t"),
        pytest.param(lambda n: n[2].__setitem__("t", True), id="bool-target-t"),
    ],
)
def test_helper_invalid_endpoint_time_raises(mutate):
    nodes_by_id, raw_edges = _graph()
    mutate(nodes_by_id)
    with pytest.raises(ValueError):
        p._unselected_association_priors({(1, 2): 0.5}, raw_edges, nodes_by_id)


def test_helper_huge_invalid_int_with_known_endpoints_raises():
    nodes_by_id, raw_edges = _graph()
    with pytest.raises(ValueError):
        p._unselected_association_priors(
            {(3, 4): 10**400}, raw_edges, nodes_by_id
        )


# --------------------------------------------------------------------------- #
# integration spy tests
# --------------------------------------------------------------------------- #
class _Spy:
    def __init__(self):
        self.calls = []

    def __call__(self, cfg, nodes_by_id, stats, learned_edge_probs, **kwargs):
        # The association-priors contract is the 4th positional argument; the
        # later keyword-only controls (appearance/consensus/bidirectional) are
        # owned by other experiments and irrelevant here, so tolerate and drop.
        self.calls.append(dict(learned_edge_probs))
        return []


@pytest.fixture
def motion_spy(monkeypatch):
    spy = _Spy()
    monkeypatch.setattr(p, "motion_relink_edges", spy)
    return spy


def test_pre_lineforwards_priors_and_keeps_selected_probability(
    tmp_path, motion_spy
):
    cfg = build_config(dict(MOTION_ENV), test_dir=tmp_path)
    assert cfg.OUTPUT_MOTION_RELINK is True
    nodes_by_id, raw_edges = _graph()
    priors = {(1, 2): 0.99, (3, 4): 0.42}

    nodes_arg = copy.deepcopy(nodes_by_id)
    edges_arg = copy.deepcopy(raw_edges)
    out_nodes, out_edges, stats = p.filter_output_graph_pre_linefit(
        cfg, nodes_arg, edges_arg, association_priors=priors
    )

    assert len(motion_spy.calls) == 1
    forwarded = motion_spy.calls[0]
    # existing learned-edge loop is untouched: selected pair keeps edge_prob 0.7
    assert forwarded[(1, 2)] == pytest.approx(0.7)
    # novel candidate is forwarded verbatim
    assert forwarded[(3, 4)] == pytest.approx(0.42)
    assert stats["motion_relink_replaced_raw_edges"] == 0
    assert out_edges == edges_arg
    assert priors == {(1, 2): 0.99, (3, 4): 0.42}


def test_wrapper_forwards_priors(tmp_path, motion_spy):
    cfg = build_config(dict(MOTION_ENV), test_dir=tmp_path)
    nodes_by_id, raw_edges = _graph()

    nodes_arg = copy.deepcopy(nodes_by_id)
    edges_arg = copy.deepcopy(raw_edges)
    out_nodes, out_edges, stats = p.filter_output_graph(
        cfg, nodes_arg, edges_arg, association_priors={(3, 4): 0.31}
    )

    assert len(motion_spy.calls) == 1
    forwarded = motion_spy.calls[0]
    assert forwarded[(3, 4)] == pytest.approx(0.31)
    assert forwarded[(1, 2)] == pytest.approx(0.7)
    assert forwarded[(2, 3)] == pytest.approx(0.6)
    assert out_edges == edges_arg


def test_none_priors_retain_previous_results(tmp_path, motion_spy):
    cfg = build_config(dict(MOTION_ENV), test_dir=tmp_path)
    nodes_by_id, raw_edges = _graph()

    baseline_nodes, baseline_edges, baseline_stats = p.filter_output_graph_pre_linefit(
        cfg, copy.deepcopy(nodes_by_id), copy.deepcopy(raw_edges)
    )
    explicit_nodes, explicit_edges, explicit_stats = p.filter_output_graph_pre_linefit(
        cfg,
        copy.deepcopy(nodes_by_id),
        copy.deepcopy(raw_edges),
        association_priors=None,
    )

    assert len(motion_spy.calls) == 2
    assert motion_spy.calls[0] == motion_spy.calls[1]
    assert explicit_nodes == baseline_nodes
    assert explicit_edges == baseline_edges
    assert explicit_stats == baseline_stats


def test_selected_only_priors_match_none_pipeline_result(tmp_path, motion_spy):
    cfg = build_config(dict(MOTION_ENV), test_dir=tmp_path)
    nodes_by_id, raw_edges = _graph()

    none_nodes, none_edges, none_stats = p.filter_output_graph_pre_linefit(
        cfg, copy.deepcopy(nodes_by_id), copy.deepcopy(raw_edges)
    )
    selected_nodes, selected_edges, selected_stats = p.filter_output_graph_pre_linefit(
        cfg,
        copy.deepcopy(nodes_by_id),
        copy.deepcopy(raw_edges),
        association_priors={(1, 2): 0.99, (2, 3): 0.98},
    )

    assert len(motion_spy.calls) == 2
    assert motion_spy.calls[0] == motion_spy.calls[1]
    assert selected_nodes == none_nodes
    assert selected_edges == none_edges
    assert selected_stats == none_stats
    assert motion_spy.calls[1][(1, 2)] == pytest.approx(0.7)


@pytest.mark.parametrize(
    "priors",
    [
        pytest.param({(1, 2): 1.5}, id="out-of-range"),
        pytest.param({(1, 2): 10**400}, id="huge-invalid"),
        pytest.param({(1, 3): 0.5}, id="non-adjacent"),
        pytest.param({(1, "2"): 0.5}, id="bad-key-type"),
    ],
)
def test_invalid_priors_raise_before_graph_mutation(tmp_path, motion_spy, priors):
    cfg = build_config(dict(MOTION_ENV), test_dir=tmp_path)
    nodes_by_id, raw_edges = _graph()
    nodes_arg = copy.deepcopy(nodes_by_id)
    edges_arg = copy.deepcopy(raw_edges)

    with pytest.raises(ValueError):
        p.filter_output_graph_pre_linefit(
            cfg, nodes_arg, edges_arg, association_priors=priors
        )

    assert motion_spy.calls == []
    assert nodes_arg == nodes_by_id
    assert edges_arg == raw_edges


def test_selected_pair_excluded_from_forwarded_priors_even_if_distance_filtered(
    tmp_path, motion_spy
):
    cfg = build_config(
        dict(MOTION_ENV, BIOHUB_OUTPUT_EDGE_MAX_UM="14"),
        test_dir=tmp_path,
    )
    nodes_by_id = {1: _node(1, 0, x=0.0), 2: _node(2, 1, x=100.0)}
    raw_edges = [_edge(1, 2, 0.7)]

    out_nodes, out_edges, stats = p.filter_output_graph_pre_linefit(
        cfg,
        copy.deepcopy(nodes_by_id),
        copy.deepcopy(raw_edges),
        association_priors={(1, 2): 0.99},
    )

    assert len(motion_spy.calls) == 1
    forwarded = motion_spy.calls[0]
    assert (1, 2) not in forwarded
    assert forwarded == {}
    assert out_edges == []


def test_filter_output_graph_association_priors(tmp_path):
    cfg = build_config(
        dict(MOTION_ENV, BIOHUB_MOTION_RELINK_LEARNED_BONUS="1.0"),
        test_dir=tmp_path,
    )
    nodes = {
        1: _node(1, 0, x=0.0),
        2: _node(2, 0, x=1.0),
        3: _node(3, 1, x=0.4),
        4: _node(4, 1, x=0.6),
    }
    raw_edges = [_edge(1, 3, 0.5), _edge(2, 4, 0.5)]
    nodes_snap = copy.deepcopy(nodes)
    raw_snap = copy.deepcopy(raw_edges)

    a = p.filter_output_graph(cfg, copy.deepcopy(nodes), copy.deepcopy(raw_edges))
    b = p.filter_output_graph(
        cfg,
        copy.deepcopy(nodes),
        copy.deepcopy(raw_edges),
        association_priors={(1, 3): 0.99, (2, 4): 0.99},
    )
    c = p.filter_output_graph(
        cfg,
        copy.deepcopy(nodes),
        copy.deepcopy(raw_edges),
        association_priors={(1, 4): 0.99, (2, 3): 0.99},
    )

    assert a == b
    diag = {(e["source_id"], e["target_id"]) for e in a[1]}
    cross = {(e["source_id"], e["target_id"]) for e in c[1]}
    assert diag == {(1, 3), (2, 4)}
    assert cross == {(1, 4), (2, 3)}
    assert c[0] == nodes_snap
    assert nodes == nodes_snap
    assert raw_edges == raw_snap
