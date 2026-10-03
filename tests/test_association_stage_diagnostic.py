"""Synthetic stage attribution, no competition GT, images, or model execution."""

import copy

import numpy as np
import polars as pl
import pytest

from biohub.association_stage_diagnostic import diagnose_stages, frames_from_npz, map_stage, stable_positions
from biohub.e26_edge_diagnostic import diagnose_arm
from biohub.evaluate import graph_from_rows, official_evaluate

NODES = [(10, 0, 0., 0., 0.), (20, 1, 0., 0., 0.)]
EDGES = [(10, 20)]


def frames(nodes=NODES, edges=EDGES):
    return (pl.DataFrame(nodes, schema={"node_id": pl.Int64, "t": pl.Int64, "z": pl.Float64,
                                       "y": pl.Float64, "x": pl.Float64}, orient="row"),
            pl.DataFrame(edges, schema={"source_id": pl.Int64, "target_id": pl.Int64}, orient="row"))


def diagnose(pre=None, post=None, final=None, gt=None):
    return diagnose_stages("synthetic", pre or frames(), post or frames(), final or frames(),
                           gt or graph_from_rows(*frames()), (1., 1., 1.))


def test_missing_edges_do_not_imply_missing_detector_matches():
    empty = frames(edges=[])
    d = diagnose(pre=empty, post=empty, final=empty)
    r = d["records"][0]
    assert all(v["both_matched"] and not v["edge_present"] for v in r["stage_views"].values())
    assert r["fixed_pre_pair_state"] == "absent_from_recorded_candidates"
    assert not d["official_score_computed"] and not r["matrix_read"]
    pred, gt = graph_from_rows(*empty), graph_from_rows(*frames())
    with pytest.warns(UserWarning, match="no edges"):
        er = official_evaluate(pred, gt, scale=(1., 1., 1.))
    assert er.edge_tp == 0 and er.edge_fn == 1
    assert d["matching_mode"] == "distance7um_without_edge_short_circuit"


def test_final_id_renumbering_does_not_look_like_a_deleted_cell():
    final = frames(nodes=[(800, *NODES[0][1:]), (900, *NODES[1][1:])], edges=[(800, 900)])
    r = diagnose(final=final)["records"][0]
    assert r["fixed_pre_pair_state"] == "origin_candidate_retained" and r["pre_post_same_assignment"]
    assert r["post_final_position_relation"] == "same_unique_positions"
    assert r["stage_views"]["final"]["source_id"] == 800 and r["stage_views"]["final"]["edge_present"]


def test_ilp_edge_deletion_with_origin_nodes_retained():
    r = diagnose(post=frames(edges=[]), final=frames(edges=[]))["records"][0]
    assert r["fixed_pre_pair_state"] == "ilp_removed_origin_edge"
    assert r["pre_post_same_assignment"] and r["stage_views"]["post"]["both_matched"]


def test_ilp_node_deletion_and_matching_reassignment_are_separate():
    pre = frames(nodes=[*NODES, (99, 0, 0., 0., 1.)], edges=[(10, 20), (99, 20)])
    post = frames(nodes=[NODES[1], (99, 0, 0., 0., 1.)], edges=[(99, 20)])
    r = diagnose(pre, post, post)["records"][0]
    assert r["fixed_pre_pair_state"] == "ilp_removed_origin_endpoint"
    assert r["stage_views"]["pre"]["source_id"] == 10
    assert r["stage_views"]["post"]["source_id"] == 99
    assert not r["pre_post_same_assignment"] and r["stage_views"]["post"]["edge_present"]


def test_shifted_final_still_matches_gt_but_is_not_same_position():
    final = frames(nodes=[(70, 0, 0., 0., .25), (80, 1, 0., 0., .25)], edges=[(70, 80)])
    r = diagnose(final=final)["records"][0]
    assert r["stage_views"]["final"]["edge_present"]
    assert r["post_final_position_relation"] == "position_changed"


def test_identical_position_duplicate_is_explicitly_ambiguous():
    gt = graph_from_rows(*frames())
    before = map_stage(*frames(), gt, (1., 1., 1.))
    after = map_stage(*frames(nodes=[*NODES, (999, *NODES[0][1:])]), gt, (1., 1., 1.))
    view = {"both_matched": True, "source_position": tuple(NODES[0][1:]),
            "target_position": tuple(NODES[1][1:])}
    assert stable_positions(view, copy.deepcopy(view), before, after) == "ambiguous_duplicate_position"


def test_sparse_unmatched_extras_are_not_labeled_negatives():
    f = frames(nodes=[*NODES, (100, 0, 0., 0., 100.), (200, 1, 0., 0., 100.)],
               edges=[*EDGES, (100, 200)])
    d = diagnose(f, f, f)
    assert len(d["records"]) == 1
    assert len([r for r in d["node_maps"]["pre"] if r["gt_node_id"] is None]) == 2
    assert d["summary"]["edge_presence_by_stage"] == {"pre": 1, "post": 1, "final": 1}


def test_both_daughters_preserved_without_single_parent_classification_error():
    f = frames(nodes=[NODES[0], (20, 1, 0., 0., -2.), (40, 1, 0., 0., 2.)], edges=[(10, 20), (10, 40)])
    d = diagnose(f, f, f, graph_from_rows(*f))
    assert len(d["records"]) == 2 and all(r["stage_views"]["final"]["edge_present"] for r in d["records"])
    assert d["summary"]["fixed_pre_pair_states"] == {"origin_candidate_retained": 2}


@pytest.mark.parametrize("case", ["new_node", "changed_position", "new_edge", "duplicate_edge", "nonadjacent"])
def test_invalid_graph_relationships_rejected(case):
    pre, post = frames(), frames()
    if case == "new_node":
        post = frames(nodes=[*NODES, (30, 2, 0., 0., 1.)])
    elif case == "changed_position":
        post = frames(nodes=[(10, 0, 0., 0., 1.), NODES[1]])
    elif case == "new_edge":
        pre = frames(edges=[])
    elif case == "duplicate_edge":
        pre = frames(edges=EDGES * 2)
    else:
        pre = frames(edges=[(20, 10)])
    with pytest.raises(ValueError):
        diagnose(pre, post)


def test_inputs_unchanged_and_large_submitted_ids_preserved():
    a, b = 2**53 + 17, 2**53 + 19
    f = frames(nodes=[(a, *NODES[0][1:]), (b, *NODES[1][1:])], edges=[(a, b)])
    before = [frame.clone() for frame in f]
    result = diagnose(f, f, f)
    assert result["records"][0]["stage_views"]["pre"]["source_id"] == a
    assert all(x.equals(y) for x, y in zip(f, before, strict=True))


def test_common_trace_conversion_keeps_edge_id_order_and_integer_precision():
    arrays = {"node_node_id": np.array([10, 20, 40], dtype=np.int64),
              "node_t": np.array([0, 1, 1], dtype=np.int32),
              **{f"node_{k}": np.zeros(3, dtype=np.float64) for k in ("z", "y", "x")},
              "edge_edge_id": np.array([8, 3], dtype=np.int32),
              "edge_source_id": np.array([10, 10], dtype=np.int64),
              "edge_target_id": np.array([20, 40], dtype=np.int64)}
    nodes, edges = frames_from_npz(arrays)
    assert nodes["node_id"].to_list() == [10, 20, 40]
    assert edges["target_id"].to_list() == [40, 20]
    arrays["node_node_id"] = np.array([2**63 + 1, 20, 40], dtype=np.uint64)
    with pytest.raises(ValueError, match="lossy"):
        frames_from_npz(arrays)


def test_empty_detections_remain_unmatched_without_inventing_nodes():
    empty = frames(nodes=[], edges=[])
    d = diagnose(empty, empty, empty)
    assert d["node_maps"] == {"pre": [], "post": [], "final": []}
    assert d["records"][0]["fixed_pre_pair_state"] == "pre_unmatched_endpoint"
    assert not any(v["both_matched"] for v in d["records"][0]["stage_views"].values())


def test_anisotropic_scale_is_applied_in_physical_units():
    gt = graph_from_rows(*frames())
    z_shift = frames(nodes=[(10, 0, 5., 0., 0.), (20, 1, 5., 0., 0.)])
    y_shift = frames(nodes=[(10, 0, 0., 5., 0.), (20, 1, 0., 5., 0.)])
    assert len(map_stage(*z_shift, gt, (1.625, .40625, .40625)).gt_to_submitted) == 0
    assert len(map_stage(*y_shift, gt, (1.625, .40625, .40625)).gt_to_submitted) == 2


def test_nonempty_matching_agrees_with_official_diagnostic_and_gt_is_unchanged():
    f = frames(nodes=[*NODES, (99, 0, 0., 0., 1.), (200, 1, 0., 0., 100.)],
               edges=[(10, 20), (99, 20)])
    gt = graph_from_rows(*frames())
    gt_nodes_before = gt.node_attrs().clone()
    gt_edges_before = gt.edge_attrs().clone()
    matched = map_stage(*f, gt, (1., 1., 1.))
    official = diagnose_arm("synthetic", *f, gt, (1., 1., 1.), 2.)
    expected = {r["gt_node_id"]: r["submitted_node_id"] for r in official.nodes.iter_rows(named=True)
                if r["gt_node_id"] is not None}
    assert matched.gt_to_submitted == expected
    assert gt.node_attrs().equals(gt_nodes_before) and gt.edge_attrs().equals(gt_edges_before)
