"""Synthetic only: complete mappings, sparse official counts, and paired transitions."""

from copy import deepcopy
from itertools import product

import polars as pl
import pytest

from biohub.e26_edge_diagnostic import (
    STATES,
    compare_arms,
    diagnose_arm,
    edge_state,
    graph_with_ids,
    transition,
)
from biohub.evaluate import graph_from_rows, node_recall, official_evaluate, per_sample_metrics

NODES = [(11, 0, 0., 10., 10.), (27, 1, 0., 11., 10.), (8, 2, 0., 14., 6.),
         (190, 2, 0., 14., 14.), (39, 3, 0., 16., 4.), (412, 3, 0., 16., 16.)]
EDGES = [(11, 27), (27, 8), (27, 190), (8, 39), (190, 412)]


def frames(nodes=NODES, edges=EDGES):
    return (
        pl.DataFrame(nodes, schema=["node_id", "t", "z", "y", "x"], orient="row"),
        pl.DataFrame(edges, schema={"source_id": pl.Int64, "target_id": pl.Int64}, orient="row"),
    )


def diagnostic(nodes=NODES, edges=EDGES):
    n, e = frames(nodes, edges)
    gt = graph_from_rows(*frames())
    stock = graph_from_rows(n, e)
    er = official_evaluate(stock, gt, scale=(1., 1., 1.), max_distance=7.)
    expected = {"dataset": "fixture", **per_sample_metrics(
        er, 6., node_recall(stock, gt) if stock.num_edges() else 0.,
    )}
    return diagnose_arm("fixture", n, e, gt, (1., 1., 1.), 6., expected)


@pytest.mark.parametrize(("source", "target", "edge", "tp", "state"), [
    (True, True, True, True, "tp"),
    (False, True, False, False, "source_unmatched_only"),
    (True, False, False, False, "target_unmatched_only"),
    (False, False, False, False, "both_unmatched"),
    (True, True, False, False, "both_matched_no_csv_edge"),
    (True, True, True, False, "both_matched_edge_not_official_tp"),
])
def test_six_states(source, target, edge, tp, state):
    assert edge_state(source, target, edge, tp) == state


@pytest.mark.parametrize("before,after", list(product(STATES, repeat=2)))
def test_all_state_transitions(before, after):
    expected = {(True, True): "retained_tp", (True, False): "lost_tp",
                (False, True): "gained_tp", (False, False): "shared_fn"}
    assert transition(before, after) == expected[before == "tp", after == "tp"]


def test_impossible_state_rejected():
    with pytest.raises(ValueError, match="endpoints"):
        edge_state(False, True, True, False)
    with pytest.raises(ValueError, match="TP without"):
        edge_state(True, True, False, True)
    with pytest.raises(ValueError, match="unknown"):
        transition("pretend", "tp")


def test_actual_id_maps_and_full_division_matching():
    arm = diagnostic()
    assert arm.row["edge_tp"] == 5 and arm.row["division_tp"] == 1
    assert arm.nodes.height == 6 and arm.edges.height == 5
    assert set(arm.nodes["submitted_node_id"]) == {n[0] for n in NODES}
    assert arm.nodes["internal_node_id"].n_unique() == 6
    assert arm.nodes["gt_node_id"].n_unique() == 6
    assert all(r["state"] == "tp" and r["matched_source"] and r["matched_target"] for r in arm.gt_edges)
    records, summary = compare_arms(arm, arm)
    assert len(records) == 5 and summary["transitions"]["retained_tp"] == 5


def test_missing_edge_loss_and_symmetric_gain():
    baseline, candidate = diagnostic(), diagnostic(edges=[e for e in EDGES if e != (27, 8)])
    records, summary = compare_arms(baseline, candidate)
    assert summary["transitions"] == {"retained_tp": 4, "lost_tp": 1, "gained_tp": 0, "shared_fn": 0}
    assert summary["lost_tp_candidate_state"]["both_matched_no_csv_edge"] == 1
    assert len(records) == 5
    _, reverse = compare_arms(candidate, baseline)
    assert reverse["transitions"]["gained_tp"] == 1
    assert reverse["gained_tp_baseline_state"]["both_matched_no_csv_edge"] == 1


def test_shifted_node_is_unmatched_not_automatically_called_deleted():
    shifted = [(*n[:4], 100.) if n[0] == 27 else n for n in NODES]
    candidate = diagnostic(nodes=shifted)
    _, summary = compare_arms(diagnostic(), candidate)
    assert summary["transitions"]["lost_tp"] == 3
    assert summary["lost_tp_candidate_state"]["source_unmatched_only"] == 2
    assert summary["lost_tp_candidate_state"]["target_unmatched_only"] == 1
    assert candidate.nodes.height == 6  # No physical deletion, only changed matching.


def test_sparse_unmatched_predictions_not_all_false_positives():
    arm = diagnostic(nodes=[*NODES, (600, 0, 0., 200., 200.), (900, 1, 0., 200., 200.)],
                     edges=[*EDGES, (600, 900)])
    assert arm.edges.height == 6 and arm.row["edge_fp"] == 0
    irrelevant = arm.edges.filter(pl.col("submitted_source_id") == 600).row(0, named=True)
    assert irrelevant["evaluated"] and not irrelevant["pred_valid"] and not irrelevant["fp"]
    assert arm.nodes.filter(pl.col("gt_node_id").is_null()).height == 2


def test_true_false_positive_is_saved():
    arm = diagnostic(edges=[*EDGES, (8, 412)])
    assert arm.row["edge_fp"] == 1 and arm.edges["fp"].sum() == 1
    assert arm.row["division_fp"] == 1


def test_no_edges_follows_official_no_match_behavior():
    arm = diagnostic(edges=[])
    assert arm.row["edge_fn"] == 5 and all(r["state"] == "both_unmatched" for r in arm.gt_edges)
    assert arm.nodes.height == 6 and arm.edges.height == 0


def test_late_sparse_matches_keep_nullable_int64_and_parquet(tmp_path):
    # More than Polars' default inference prefix is unmatched in both node/edge records.
    extras = [(1000 + i, i % 2, 0., 1000. + i, 1000.) for i in range(220)]
    extra_edges = [(1000 + i, 1001 + i) for i in range(0, 220, 2)]
    arm = diagnostic(nodes=[*extras, *NODES], edges=[*extra_edges, *EDGES])
    assert arm.nodes["gt_node_id"].dtype == pl.Int64
    assert arm.edges["source_gt_id"].dtype == pl.Int64
    assert arm.row["edge_tp"] == 5 and arm.row["edge_fp"] == 0
    assert arm.nodes["gt_node_id"].null_count() == 220
    assert arm.edges["source_gt_id"].null_count() == 110
    for name, table in (("nodes", arm.nodes), ("edges", arm.edges)):
        path = tmp_path / f"{name}.parquet"
        table.write_parquet(path)
        assert pl.read_parquet(path).equals(table)


def test_large_geff_id_is_not_truncated():
    from biohub.e26_edge_diagnostic import NODE_SCHEMA
    record = {"internal_node_id": 0, "submitted_node_id": 1, "gt_node_id": None,
              "t": 0, "z": 0., "y": 0., "x": 0.}
    rows = [record] * 110 + [{**record, "gt_node_id": 149000000036}]
    table = pl.DataFrame(rows, schema=NODE_SCHEMA)
    assert table["gt_node_id"][-1] == 149000000036


@pytest.mark.parametrize("kind", ["duplicate", "dangling", "nonfinite"])
def test_input_inconsistency(kind):
    n, e = frames()
    if kind == "duplicate":
        n = pl.concat([n, n.head(1)])
    elif kind == "dangling":
        e = pl.DataFrame({"source_id": [12345], "target_id": [11]})
    else:
        n = n.with_columns(pl.lit(float("nan")).alias("x"))
    with pytest.raises(ValueError):
        graph_with_ids(n, e)


def test_saved_official_mismatch_rejected():
    with pytest.raises(ValueError, match="official saved row mismatch"):
        diagnose_arm("fixture", *frames(), graph_from_rows(*frames()), (1., 1., 1.), 6., {"wrong": 1})


@pytest.mark.parametrize("kind", ["duplicate_id", "missing_edge", "endpoint", "count"])
def test_complete_pairing_rejects_corruption(kind):
    base = diagnostic()
    candidate = deepcopy(base)
    if kind == "duplicate_id":
        candidate.gt_edges.append(deepcopy(candidate.gt_edges[0]))
    elif kind == "missing_edge":
        candidate.gt_edges.pop()
    elif kind == "endpoint":
        candidate.gt_edges[0]["gt_target_id"] = 987654
    else:
        candidate.row["edge_tp"] += 1
    with pytest.raises(ValueError):
        compare_arms(base, candidate)
