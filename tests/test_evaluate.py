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

    rows = pl.DataFrame(GT_NODES, schema=["node_id", "t", "z", "y", "x"], orient="row")
    edges = pl.DataFrame(GT_EDGES, schema=["source_id", "target_id"], orient="row")
    graph = graph_from_rows(rows, edges)
    graph.to_geff(data_dir / f"{name}.geff")
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


def test_perfect_submission_scores_edge_jaccard_one(gt_dir: Path, tmp_path: Path):
    csv_path = _write_csv(tmp_path / "sub.csv", "vid", GT_NODES, GT_EDGES)
    summary, rows = score_submission(csv_path, gt_dir, verbose=False)
    assert rows[0]["edge_tp"] == len(GT_EDGES) and rows[0]["edge_fn"] == 0 and rows[0]["edge_fp"] == 0
    assert summary["edge_jaccard"] == pytest.approx(1.0)
    assert rows[0]["division_tp"] == 1 and rows[0]["division_fn"] == 0


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
