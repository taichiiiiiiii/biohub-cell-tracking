"""Official-metric wrapper: perfect / degraded / invalid submissions on a synthetic GT."""
from __future__ import annotations

import csv
from pathlib import Path

import polars as pl
import pytest

from biohub.evaluate import graph_from_rows, read_submission, score_submission

SCALE = (1.0, 1.0, 1.0)

# One lineage: n1(t0) -> n2(t1) -> divides into n3, n4 (t2); each continues to t3.
GT_NODES = [
    (1, 0, 0.0, 10.0, 10.0),
    (2, 1, 0.0, 11.0, 10.0),
    (3, 2, 0.0, 14.0, 6.0),
    (4, 2, 0.0, 14.0, 14.0),
    (5, 3, 0.0, 16.0, 4.0),
    (6, 3, 0.0, 16.0, 16.0),
]
GT_EDGES = [(1, 2), (2, 3), (2, 4), (3, 5), (4, 6)]


def _write_gt(data_dir: Path, name: str) -> None:
    import zarr
    from geff import GeffMetadata

    rows = pl.DataFrame(GT_NODES, schema=["node_id", "t", "z", "y", "x"], orient="row")
    edges = pl.DataFrame(GT_EDGES, schema=["source_id", "target_id"], orient="row")
    graph = graph_from_rows(rows, edges)
    geff_path = data_dir / f"{name}.geff"
    graph.to_geff(geff_path)
    metadata = GeffMetadata.read(geff_path)
    metadata.extra["estimated_number_of_nodes"] = len(GT_NODES)
    metadata.write(geff_path)
    # Minimal zarr root so read_scale() finds an isotropic scale.
    g = zarr.open_group(data_dir / f"{name}.zarr", mode="w", zarr_format=3)
    transform = {"type": "scale", "scale": [1, *SCALE]}
    g.attrs["ome"] = {"multiscales": [{"datasets": [{"path": "0", "coordinateTransformations": [transform]}]}]}


def _write_csv(path: Path, name: str, nodes, edges) -> Path:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "dataset", "row_type", "node_id", "t", "z", "y", "x", "source_id", "target_id"])
        i = 0
        for nid, t, z, y, x in nodes:
            w.writerow([i, name, "node", nid, t, z, y, x, -1, -1])
            i += 1
        for s, t in edges:
            w.writerow([i, name, "edge", -1, -1, -1, -1, -1, s, t])
            i += 1
    return path


@pytest.fixture
def gt_dir(tmp_path: Path) -> Path:
    d = tmp_path / "train"
    d.mkdir()
    _write_gt(d, "vid")
    return d


def _score_counterfactual(
    gt_dir: Path,
    tmp_path: Path,
    filename: str,
    nodes=GT_NODES,
    edges=GT_EDGES,
) -> tuple[dict, dict]:
    csv_path = _write_csv(tmp_path / filename, "vid", nodes, edges)
    summary, rows = score_submission(csv_path, gt_dir, verbose=False)
    assert len(rows) == 1
    return summary, rows[0]


def _assert_official_counts(
    row: dict,
    *,
    edge: tuple[int, int, int],
    division: tuple[int, int, int],
    num_pred_nodes: int,
) -> None:
    assert (row["edge_tp"], row["edge_fp"], row["edge_fn"]) == edge
    assert (row["division_tp"], row["division_fp"], row["division_fn"]) == division
    assert row["num_pred_nodes"] == num_pred_nodes


def test_perfect_submission_scores_edge_jaccard_one(gt_dir: Path, tmp_path: Path):
    csv_path = _write_csv(tmp_path / "sub.csv", "vid", GT_NODES, GT_EDGES)
    summary, rows = score_submission(csv_path, gt_dir, verbose=False)
    assert rows[0]["edge_tp"] == len(GT_EDGES) and rows[0]["edge_fn"] == 0 and rows[0]["edge_fp"] == 0
    assert summary["edge_jaccard"] == pytest.approx(1.0)
    assert rows[0]["division_tp"] == 1 and rows[0]["division_fn"] == 0


def test_correct_second_daughter_recovers_edge_and_division(gt_dir: Path, tmp_path: Path):
    missing_edges = [edge for edge in GT_EDGES if edge != (2, 4)]
    missing_summary, missing = _score_counterfactual(
        gt_dir, tmp_path, "missing_second_daughter.csv", edges=missing_edges
    )
    recovered_summary, recovered = _score_counterfactual(
        gt_dir, tmp_path, "correct_second_daughter.csv"
    )

    _assert_official_counts(missing, edge=(4, 0, 1), division=(0, 0, 1), num_pred_nodes=6)
    _assert_official_counts(recovered, edge=(5, 0, 0), division=(1, 0, 0), num_pred_nodes=6)
    assert missing["adj_edge_jaccard"] == pytest.approx(0.8)
    assert recovered["adj_edge_jaccard"] == pytest.approx(1.0)
    assert missing_summary["score"] == pytest.approx(0.8)
    assert recovered_summary["score"] == pytest.approx(1.1)


def test_false_fork_adds_edge_and_division_false_positives(gt_dir: Path, tmp_path: Path):
    baseline_summary, baseline = _score_counterfactual(gt_dir, tmp_path, "before_false_fork.csv")
    fork_summary, fork = _score_counterfactual(
        gt_dir, tmp_path, "after_false_fork.csv", edges=[*GT_EDGES, (3, 6)]
    )

    _assert_official_counts(baseline, edge=(5, 0, 0), division=(1, 0, 0), num_pred_nodes=6)
    _assert_official_counts(fork, edge=(5, 1, 0), division=(1, 1, 0), num_pred_nodes=6)
    assert baseline["adj_edge_jaccard"] == pytest.approx(1.0)
    assert fork["adj_edge_jaccard"] == pytest.approx(5 / 6)
    assert baseline_summary["score"] == pytest.approx(1.1)
    assert fork_summary["score"] == pytest.approx(5 / 6 + 0.1 * 0.5)


def test_cutting_valid_continuation_preserves_division_tp(gt_dir: Path, tmp_path: Path):
    baseline_summary, baseline = _score_counterfactual(gt_dir, tmp_path, "before_continuation_cut.csv")
    cut_edges = [edge for edge in GT_EDGES if edge != (3, 5)]
    cut_summary, cut = _score_counterfactual(
        gt_dir, tmp_path, "after_continuation_cut.csv", edges=cut_edges
    )

    _assert_official_counts(baseline, edge=(5, 0, 0), division=(1, 0, 0), num_pred_nodes=6)
    _assert_official_counts(cut, edge=(4, 0, 1), division=(1, 0, 0), num_pred_nodes=6)
    assert baseline["adj_edge_jaccard"] == pytest.approx(1.0)
    assert cut["adj_edge_jaccard"] == pytest.approx(0.8)
    assert baseline_summary["score"] == pytest.approx(1.1)
    assert cut_summary["score"] == pytest.approx(0.9)


def test_matched_detection_addition_only_changes_node_adjustment(gt_dir: Path, tmp_path: Path):
    nodes_without_leaf = [node for node in GT_NODES if node[0] != 6]
    edges_without_leaf = [edge for edge in GT_EDGES if edge != (4, 6)]
    before_summary, before = _score_counterfactual(
        gt_dir, tmp_path, "before_matched_detection.csv", nodes=nodes_without_leaf, edges=edges_without_leaf
    )
    after_summary, after = _score_counterfactual(
        gt_dir, tmp_path, "after_matched_detection.csv", edges=edges_without_leaf
    )

    _assert_official_counts(before, edge=(4, 0, 1), division=(1, 0, 0), num_pred_nodes=5)
    _assert_official_counts(after, edge=(4, 0, 1), division=(1, 0, 0), num_pred_nodes=6)
    assert before["node_recall"] == pytest.approx(5 / 6)
    assert after["node_recall"] == pytest.approx(1.0)
    assert before["adj_edge_jaccard"] == pytest.approx(0.8 * (1 + 0.1 / 6))
    assert after["adj_edge_jaccard"] == pytest.approx(0.8)
    assert before_summary["score"] == pytest.approx(before["adj_edge_jaccard"] + 0.1)
    assert after_summary["score"] == pytest.approx(0.9)


def test_unmatched_detection_addition_only_changes_node_adjustment(gt_dir: Path, tmp_path: Path):
    unmatched = (7, 3, 50.0, 50.0, 50.0)
    before_summary, before = _score_counterfactual(gt_dir, tmp_path, "before_unmatched_detection.csv")
    after_summary, after = _score_counterfactual(
        gt_dir, tmp_path, "after_unmatched_detection.csv", nodes=[*GT_NODES, unmatched]
    )

    _assert_official_counts(before, edge=(5, 0, 0), division=(1, 0, 0), num_pred_nodes=6)
    _assert_official_counts(after, edge=(5, 0, 0), division=(1, 0, 0), num_pred_nodes=7)
    assert before["node_recall"] == pytest.approx(1.0)
    assert after["node_recall"] == pytest.approx(1.0)
    assert before["adj_edge_jaccard"] == pytest.approx(1.0)
    assert after["adj_edge_jaccard"] == pytest.approx(1 - 0.1 / 6)
    assert before_summary["score"] == pytest.approx(1.1)
    assert after_summary["score"] == pytest.approx(after["adj_edge_jaccard"] + 0.1)


def test_dropping_edges_lowers_edge_jaccard(gt_dir: Path, tmp_path: Path):
    csv_path = _write_csv(tmp_path / "sub.csv", "vid", GT_NODES, GT_EDGES[:2])
    summary, rows = score_submission(csv_path, gt_dir, verbose=False)
    assert rows[0]["edge_fn"] == 3
    assert summary["edge_jaccard"] == pytest.approx(2 / 5)


def test_nodes_far_from_gt_do_not_match(gt_dir: Path, tmp_path: Path):
    shifted = [(nid, t, z + 50.0, y, x) for nid, t, z, y, x in GT_NODES]
    csv_path = _write_csv(tmp_path / "sub.csv", "vid", shifted, GT_EDGES)
    summary, rows = score_submission(csv_path, gt_dir, max_distance=7.0, verbose=False)
    assert rows[0]["edge_tp"] == 0 and rows[0]["edge_fn"] == len(GT_EDGES)


def test_dataset_without_gt_is_skipped(gt_dir: Path, tmp_path: Path):
    csv_path = _write_csv(tmp_path / "sub.csv", "unknown_vid", GT_NODES, GT_EDGES)
    summary, rows = score_submission(csv_path, gt_dir, verbose=False)
    assert rows == [] and summary["n"] == 0


def test_dangling_edge_is_rejected(tmp_path: Path):
    csv_path = _write_csv(tmp_path / "sub.csv", "vid", GT_NODES, [(1, 999)])
    with pytest.raises(ValueError, match="unknown node_id"):
        read_submission(csv_path)


def test_duplicate_node_id_is_rejected(tmp_path: Path):
    csv_path = _write_csv(tmp_path / "sub.csv", "vid", GT_NODES + [GT_NODES[0]], [])
    with pytest.raises(ValueError, match="duplicate node_id"):
        read_submission(csv_path)


def test_missing_column_is_rejected(tmp_path: Path):
    p = tmp_path / "bad.csv"
    p.write_text("id,dataset,row_type\n0,vid,node\n")
    with pytest.raises(ValueError, match="missing columns"):
        read_submission(p)
