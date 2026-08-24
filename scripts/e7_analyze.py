#!/usr/bin/env python
"""E7 pre-registered readouts (ledger E7-10). Run after div_score_cands completes.

    uv run python scripts/e7_analyze.py \
        --scores outputs/kaggle/div_score_cands/cand_scores.csv \
        --cands outputs/e7/cands_dataset/candidates.csv \
        --measure outputs/e7/val12_measure.csv \
        --gt-dir data/train
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e6_measure import SCALE, gt_divisions  # noqa: E402

MATCH_UM = 7.0


def rank_norm(col: str) -> pl.Expr:
    return (pl.col(col).rank(method="average") - 1) / (pl.len() - 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scores", type=Path, required=True)
    ap.add_argument("--cands", type=Path, required=True)
    ap.add_argument("--measure", type=Path, required=True)
    ap.add_argument("--gt-dir", type=Path, default=Path("data/train"))
    args = ap.parse_args()

    scores = pl.read_csv(args.scores)
    cands = pl.read_csv(args.cands)
    df = cands.join(scores.select("cand_id", "score"), on="cand_id", how="left")
    missing = df.filter(pl.col("score").is_null()).height
    if missing:
        print(f"WARNING: {missing} candidates without score")
    df = df.filter(pl.col("score").is_not_null())
    df = df.with_columns(rank_norm("score").over("stem").alias("cnn_rank"))

    # ---- readout 1: within-video rank of real parents (CNN alone)
    print("=" * 70)
    print("READOUT 1: real-parent rank by CNN score (per video)")
    tops = {1: 0, 3: 0, 10: 0}
    pct1 = 0
    n_real = 0
    for (stem,), g in sorted(df.group_by("stem"), key=lambda kv: kv[0][0]):
        g = g.sort("score", descending=True).with_row_index("pos")
        reals = g.filter(pl.col("is_real_parent"))
        n = g.height
        for r in reals.iter_rows(named=True):
            n_real += 1
            pos = r["pos"] + 1
            for k in tops:
                tops[k] += int(pos <= k)
            pct1 += int(pos <= max(1, n // 100))
            print(f"  {stem}: real parent {r['parent_id']} rank {pos}/{n} "
                  f"(score={r['score']:.4f})")
    print(f"SUMMARY: {n_real} real parents -> top1={tops[1]} top3={tops[3]} "
          f"top10={tops[10]} top1%={pct1}")

    # ---- readout 2: fixed-form stack with geometry prior on candidate PAIRS
    print("=" * 70)
    print("READOUT 2: fixed stack rank_norm(CNN) * rank_norm(geom prior) on pairs")
    pairs = pl.read_csv(args.measure)
    pairs = pairs.join(
        df.select(pl.col("stem").alias("dataset"), "parent_id", "score"),
        on=["dataset", "parent_id"], how="left")
    pairs = pairs.filter(pl.col("score").is_not_null())
    # geometry prior: closeness to GT census modes (sister 10.6, d_pc 7.1), fixed form
    pairs = pairs.with_columns(
        (-((pl.col("sister") - 10.6).abs() / 4.0 + (pl.col("d_pc") - 7.1).abs() / 3.0
           + pl.col("mid_over_sister"))).alias("geom"))
    pairs = pairs.with_columns(
        (rank_norm("score").over("dataset") * rank_norm("geom").over("dataset")).alias("stack"))
    tops2 = {1: 0, 3: 0, 10: 0}
    n_real2 = 0
    for (stem,), g in sorted(pairs.group_by("dataset"), key=lambda kv: kv[0][0]):
        g = g.sort("stack", descending=True).with_row_index("pos")
        for r in g.filter(pl.col("real")).iter_rows(named=True):
            n_real2 += 1
            pos = r["pos"] + 1
            for k in tops2:
                tops2[k] += int(pos <= k)
            if pos <= 10:
                print(f"  {stem}: real pair (P={r['parent_id']},C2={r['orphan_id']}) "
                      f"rank {pos}/{g.height} kind={r['kind']}")
    print(f"SUMMARY: {n_real2} real pairs -> top1={tops2[1]} top3={tops2[3]} top10={tops2[10]}")

    # ---- readout 3: existing-fork veto
    print("=" * 70)
    print("READOUT 3: existing-fork CNN veto (threshold from OOF, rank>=0.60=recall0.9)")
    forks = df.filter(pl.col("is_existing_fork"))
    lab = []
    for (stem,), g in sorted(forks.group_by("stem"), key=lambda kv: kv[0][0]):
        divs = gt_divisions(args.gt_dir / f"{stem}.geff")
        for r in g.iter_rows(named=True):
            p_um = np.array([r["z"], r["y"], r["x"]], dtype=float) * SCALE
            near = any(d["t"] == r["t"] and np.linalg.norm(p_um - d["parent_pos"]) <= MATCH_UM
                       for d in divs)
            lab.append({"stem": stem, "near_gt": near, "cnn_rank": r["cnn_rank"],
                        "score": r["score"]})
    labdf = pl.DataFrame(lab)
    for grp, g in (("near_GT(TP-ish)", labdf.filter(pl.col("near_gt"))),
                   ("far(FP-cand)", labdf.filter(~pl.col("near_gt")))):
        if g.height:
            print(f"  {grp}: n={g.height} cnn_rank med={g['cnn_rank'].median():.3f} "
                  f"[p10={g['cnn_rank'].quantile(0.1):.3f}, p90={g['cnn_rank'].quantile(0.9):.3f}]")
    for tau in (0.60, 0.80, 0.90):
        keep = labdf.filter(pl.col("cnn_rank") >= tau)
        drop = labdf.filter(pl.col("cnn_rank") < tau)
        print(f"  veto@rank<{tau}: drops {drop.height} forks "
              f"(near_gt dropped={int(drop['near_gt'].sum())}, kept near_gt={int(keep['near_gt'].sum())})")


if __name__ == "__main__":
    main()
