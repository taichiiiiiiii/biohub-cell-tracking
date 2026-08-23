"""Score a submission CSV against local ground truth with the *official* metric.

Torch-free re-implementation of official/scripts/{csv_to_geffs,evaluate}.py:
the official modules import torch via ``tracking_cellmot.io``; this file uses
only ``tracking_cellmot.metrics`` (polars + tracksdata).

Validation is strict on purpose: a malformed CSV raises instead of being
silently repaired, because Kaggle would reject or mis-score it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import polars as pl

from biohub.io import SUBMISSION_COLUMNS, estimated_number_of_nodes, load_geff_graph, read_scale

_OFFICIAL_SRC = Path(__file__).resolve().parents[2] / "official" / "src"
if str(_OFFICIAL_SRC) not in sys.path:
    sys.path.insert(0, str(_OFFICIAL_SRC))

from tracking_cellmot.metrics import evaluate as official_evaluate  # noqa: E402
from tracking_cellmot.metrics import node_recall, per_sample_metrics, summarise  # noqa: E402

MAX_MATCH_DISTANCE_UM = 7.0


def read_submission(csv_path: Path | str) -> pl.DataFrame:
    """Read and validate a submission CSV (schema + referential integrity)."""
    df = pl.read_csv(csv_path)
    missing = [c for c in SUBMISSION_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"submission missing columns {missing}")
    bad_type = df.filter(~pl.col("row_type").is_in(["node", "edge"]))
    if bad_type.height:
        raise ValueError(f"{bad_type.height} rows with row_type not in {{node, edge}}")
    for (name,), g in df.group_by("dataset"):
        nodes = g.filter(pl.col("row_type") == "node")
        edges = g.filter(pl.col("row_type") == "edge")
        if nodes["node_id"].n_unique() != nodes.height:
            raise ValueError(f"{name}: duplicate node_id")
        ids = set(nodes["node_id"].to_list())
        pairs = zip(edges["source_id"].to_list(), edges["target_id"].to_list(), strict=True)
        dangling = [(s, t) for s, t in pairs if s not in ids or t not in ids]
        if dangling:
            raise ValueError(f"{name}: {len(dangling)} edges reference unknown node_id, e.g. {dangling[:3]}")
    return df


def graph_from_rows(node_rows: pl.DataFrame, edge_rows: pl.DataFrame):
    """Build a tracksdata InMemoryGraph from one dataset's node/edge rows (mirrors official csv_to_geffs)."""
    import tracksdata as td

    graph = td.graph.InMemoryGraph()
    for key in ("z", "y", "x"):
        graph.add_node_attr_key(key, pl.Float64, -999999.0)
    assigned = graph.bulk_add_nodes(
        node_rows.select(
            pl.col("t").cast(pl.Int64),
            pl.col("z").cast(pl.Float64),
            pl.col("y").cast(pl.Float64),
            pl.col("x").cast(pl.Float64),
        ).to_dicts()
    )
    id_map = dict(zip(node_rows["node_id"].to_list(), assigned, strict=True))
    if edge_rows.height:
        graph.bulk_add_edges(
            [
                {"source_id": id_map[s], "target_id": id_map[t]}
                for s, t in zip(edge_rows["source_id"].to_list(), edge_rows["target_id"].to_list(), strict=True)
            ]
        )
    return graph


def score_submission(
    csv_path: Path | str,
    gt_dir: Path | str,
    max_distance: float = MAX_MATCH_DISTANCE_UM,
    verbose: bool = True,
) -> tuple[dict, list[dict]]:
    """Official run-level score for every dataset present in both the CSV and ``gt_dir``.

    Returns ``(summary, per_dataset_rows)``; rows carry a ``dataset`` key in
    addition to the official per-sample metric columns.
    """
    gt_dir = Path(gt_dir)
    df = read_submission(csv_path)
    rows: list[dict] = []
    for (name,), g in sorted(df.group_by("dataset"), key=lambda kv: kv[0][0]):
        geff = gt_dir / f"{name}.geff"
        if not geff.exists():
            if verbose:
                print(f"  {name}: no GT in {gt_dir}, skipped")
            continue
        pred = graph_from_rows(g.filter(pl.col("row_type") == "node"), g.filter(pl.col("row_type") == "edge"))
        gt = load_geff_graph(geff)
        scale = read_scale(gt_dir / f"{name}.zarr")
        er = official_evaluate(pred, gt, scale=scale, max_distance=max_distance)
        recall = node_recall(pred, gt) if pred.num_edges() > 0 and pred.num_nodes() > 0 else 0.0
        row = {"dataset": name, **per_sample_metrics(er, estimated_number_of_nodes(geff), recall)}
        rows.append(row)
        if verbose:
            print(
                f"  {name}: edge TP/FP/FN={er.edge_tp}/{er.edge_fp}/{er.edge_fn} "
                f"div TP/FP/FN={er.division_tp}/{er.division_fp}/{er.division_fn} "
                f"n_pred={er.num_pred_nodes} adj_J={row['adj_edge_jaccard']:.4f}"
            )
    summary = summarise([{k: v for k, v in r.items() if k != "dataset"} for r in rows])
    return summary, rows
