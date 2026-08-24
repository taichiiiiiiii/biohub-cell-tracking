#!/usr/bin/env python
"""Build candidates.csv for the div_score_cands kernel (E7 deployment test).

Joins e6_measure candidate rows (parent_id per video) with the submission CSV
node coordinates, attaches the CV fold that held each video out, and writes
stem,cand_id,t,z,y,x,fold plus the feature columns for later stacking.

    uv run python scripts/e7_build_cands.py \
        --measure outputs/e7/val12_measure.csv \
        --pred-csv outputs/e7/val12_post/submission.csv \
        --model-info outputs/kaggle/div_classifier_v2/model_info.json \
        --out outputs/e7/candidates.csv
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--measure", type=Path, required=True)
    ap.add_argument("--pred-csv", type=Path, required=True)
    ap.add_argument("--model-info", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    cands = pl.read_csv(args.measure)
    nodes = (
        pl.read_csv(args.pred_csv)
        .filter(pl.col("row_type") == "node")
        .select("dataset", "node_id", "t", "z", "y", "x")
    )
    folds = json.load(open(args.model_info))["folds"]

    joined = cands.join(
        nodes.rename({"node_id": "parent_id", "t": "t_node"}),
        on=["dataset", "parent_id"],
        how="left",
    )
    n_missing = joined.filter(pl.col("z").is_null()).height
    if n_missing:
        raise SystemExit(f"{n_missing} candidates failed the coordinate join")
    bad_t = joined.filter(pl.col("t") != pl.col("t_node")).height
    if bad_t:
        raise SystemExit(f"{bad_t} candidates with t mismatch between measure and pred CSV")

    out = joined.with_columns(
        pl.col("dataset").alias("stem"),
        pl.arange(0, joined.height).alias("cand_id"),
        pl.col("dataset").map_elements(lambda s: folds[s], return_dtype=pl.Int64).alias("fold"),
    ).select(
        "stem", "cand_id", "t", "z", "y", "x", "fold",
        "kind", "parent_id", "orphan_id", "d_pc", "sister", "mid_over_sister",
        "border", "orphan_speed", "orphan_len4", "d_qc", "real",
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.write_csv(args.out)
    print(f"wrote {out.height} candidates, real={int(out['real'].sum())}, "
          f"videos={out['stem'].n_unique()}")
    for stem, g in sorted(out.group_by("stem"), key=lambda kv: kv[0][0]):
        print(f"  {stem}: cands={g.height} real={int(g['real'].sum())} fold={g['fold'][0]}")


if __name__ == "__main__":
    main()
