#!/usr/bin/env python
"""Unverified-spec probe: score sensitivity to random GT track-subset draws.

Hidden test GT is 'a random sparse subset' (Discussion #734237). This probe
subsamples fraction F of GT lineages (connected components) per video with a
seed, rescoring the same predictions. The spread across seeds estimates the
GT-draw noise; N_true (estimated_number_of_nodes) is kept fixed because it
estimates the true cell count, not the annotated count.

    uv run python scripts/gt_subsample_probe.py --seed 0 --frac 0.5 \
        --pred-csv outputs/e7/val12_post/submission.csv --out outputs/e7/gtprobe/seed0.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from biohub.evaluate import (  # noqa: E402
    MAX_MATCH_DISTANCE_UM,
    estimated_number_of_nodes,
    graph_from_rows,
    node_recall,
    official_evaluate,
    per_sample_metrics,
    read_submission,
    summarise,
)
from biohub.io import load_geff_graph, read_scale  # noqa: E402


def subsample_gt(geff: Path, frac: float, seed: int):
    g = load_geff_graph(geff)
    na, ea = g.node_attrs(), g.edge_attrs()
    nid = na["node_id"].to_numpy()
    src = ea["source_id"].to_numpy()
    tgt = ea["target_id"].to_numpy()
    parent = {int(n): int(n) for n in nid}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for s, t in zip(src, tgt):
        ra, rb = find(int(s)), find(int(t))
        if ra != rb:
            parent[ra] = rb
    comps: dict[int, list[int]] = {}
    for n in nid:
        comps.setdefault(find(int(n)), []).append(int(n))
    keys = sorted(comps)
    rng = np.random.default_rng(seed)
    keep_keys = set(rng.choice(keys, size=max(1, int(round(frac * len(keys)))), replace=False).tolist())
    keep_nodes = {n for k in keep_keys for n in comps[k]}
    nsub = na.filter(pl.col("node_id").is_in(list(keep_nodes)))
    esub = ea.filter(pl.col("source_id").is_in(list(keep_nodes))
                     & pl.col("target_id").is_in(list(keep_nodes)))
    return graph_from_rows(nsub, esub), len(keys), len(keep_keys)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pred-csv", type=Path, required=True)
    ap.add_argument("--gt-dir", type=Path, default=ROOT / "data" / "train")
    ap.add_argument("--frac", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    df = read_submission(args.pred_csv)
    rows = []
    for (name,), g in sorted(df.group_by("dataset"), key=lambda kv: kv[0][0]):
        geff = args.gt_dir / f"{name}.geff"
        if not geff.exists():
            continue
        gt_sub, n_comp, n_keep = subsample_gt(geff, args.frac, args.seed)
        pred = graph_from_rows(g.filter(pl.col("row_type") == "node"),
                               g.filter(pl.col("row_type") == "edge"))
        scale = read_scale(args.gt_dir / f"{name}.zarr")
        er = official_evaluate(pred, gt_sub, scale=scale, max_distance=MAX_MATCH_DISTANCE_UM)
        recall = node_recall(pred, gt_sub) if pred.num_edges() and pred.num_nodes() else 0.0
        row = {"dataset": name, "components": n_comp, "kept": n_keep,
               **per_sample_metrics(er, estimated_number_of_nodes(geff), recall)}
        rows.append(row)
        print(f"{name}: comps {n_keep}/{n_comp} adj_J={row['adj_edge_jaccard']:.4f}", flush=True)
    summary = summarise([{k: v for k, v in r.items() if k not in ("dataset", "components", "kept")} for r in rows])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"frac": args.frac, "seed": args.seed, "summary": summary, "per_dataset": rows},
              open(args.out, "w"), indent=1)
    print(f"frac={args.frac} seed={args.seed}: score={summary['score']:.4f} "
          f"adj={summary['adj_edge_jaccard']:.4f} divJ={summary['division_jaccard']:.4f}")


if __name__ == "__main__":
    main()
