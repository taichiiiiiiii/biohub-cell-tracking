"""Hard submission validator: every rule must actually fire on a crafted violation."""
from __future__ import annotations

import polars as pl
import pytest

from biohub.validate import SubmissionError, validate_submission

SHAPES = {"vid": (3, 4, 8, 8)}  # (T, Z, Y, X)


def _df(nodes, edges, dataset="vid"):
    rows = []
    for nid, t, z, y, x in nodes:
        rows.append((dataset, "node", nid, t, z, y, x, -1, -1))
    for s, t in edges:
        rows.append((dataset, "edge", -1, -1, -1, -1, -1, s, t))
    return pl.DataFrame(rows, schema=["dataset", "row_type", "node_id", "t", "z", "y", "x", "source_id", "target_id"],
                        orient="row")


GOOD_NODES = [(1, 0, 1, 2, 3), (2, 1, 1, 2, 3), (3, 2, 1, 2, 3), (4, 2, 2, 5, 5)]
GOOD_EDGES = [(1, 2), (2, 3), (2, 4)]  # one division


def test_valid_submission_passes():
    report = validate_submission(_df(GOOD_NODES, GOOD_EDGES), SHAPES)
    assert report["vid"]["nodes"] == 4 and report["vid"]["edges"] == 3 and report["vid"]["forks"] == 1


@pytest.mark.parametrize(
    "bad_node, msg",
    [
        ((9, -1, 1, 2, 3), "t out of range"),
        ((9, 3, 1, 2, 3), "t out of range"),
        ((9, 0, -1, 2, 3), "coordinate out of range"),
        ((9, 0, 4, 2, 3), "coordinate out of range"),  # z == Z (upper bound!)
        ((9, 0, 1, 8, 3), "coordinate out of range"),
        ((9, 0, 1, 2, 8), "coordinate out of range"),
        ((9, 0, -10000, -10000, -10000), "coordinate out of range"),
    ],
)
def test_node_bounds_fire(bad_node, msg):
    with pytest.raises(SubmissionError, match=msg):
        validate_submission(_df(GOOD_NODES + [bad_node], GOOD_EDGES), SHAPES)


def test_non_consecutive_edge_fires():
    with pytest.raises(SubmissionError, match="t_target != t_source \\+ 1"):
        validate_submission(_df(GOOD_NODES, GOOD_EDGES + [(1, 3)]), SHAPES)


def test_backward_edge_fires():
    with pytest.raises(SubmissionError, match="t_target != t_source \\+ 1"):
        validate_submission(_df(GOOD_NODES, [(2, 1)]), SHAPES)


def test_out_degree_above_two_fires():
    nodes = GOOD_NODES + [(5, 2, 3, 3, 3)]
    with pytest.raises(SubmissionError, match="out-degree > 2"):
        validate_submission(_df(nodes, GOOD_EDGES + [(2, 5)]), SHAPES)


def test_in_degree_above_one_fires():
    nodes = GOOD_NODES + [(5, 1, 3, 3, 3)]
    with pytest.raises(SubmissionError, match="in-degree > 1"):
        validate_submission(_df(nodes, GOOD_EDGES + [(5, 3)]), SHAPES)


def test_dangling_and_duplicate_fire():
    with pytest.raises(SubmissionError, match="unknown node_id"):
        validate_submission(_df(GOOD_NODES, [(1, 99)]), SHAPES)
    with pytest.raises(SubmissionError, match="duplicate node_id"):
        validate_submission(_df(GOOD_NODES + [GOOD_NODES[0]], []), SHAPES)


def test_unknown_dataset_and_missing_dataset_fire():
    with pytest.raises(SubmissionError, match="not in the test set"):
        validate_submission(_df(GOOD_NODES, GOOD_EDGES, dataset="ghost"), SHAPES)
    with pytest.raises(SubmissionError, match="no node rows"):
        validate_submission(_df(GOOD_NODES, GOOD_EDGES), {"vid": (3, 4, 8, 8), "vid2": (3, 4, 8, 8)})


def test_self_test_injection_is_caught():
    """The validator must reject its own canary; a validator that passes the canary is useless."""
    from biohub.validate import self_test

    self_test(SHAPES)  # raises if any rule fails to fire
