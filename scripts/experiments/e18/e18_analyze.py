#!/usr/bin/env python
"""E18 readouts: reverse-direction (parent->child) prob for division pairs (ledger E18).

Rev dump rows: gi,gj,prob_rev,coords... where gi = SOURCE (parent P), gj = TARGET
(child), prob_rev = softmax over targets for that source. Readouts:
  (i) for each real (P,C2): prob_rev(P->C2), in-P-top5 rank, and P's top-5 list
  (ii) candidate-pool rank of real pairs by rev alone and CNN*geom*rev stack

    uv run python scripts/e18_analyze.py \
        --dump-dir outputs/kaggle/eval_train_raw_v7/pair_probs \
        --measure outputs/e7/val12_measure.csv \
        --pred-csv outputs/e7/val12_post/submission.csv \
        --scores outputs/kaggle/div_score_cands_v3/cand_scores.csv \
        --cands outputs/e7/cands_dataset/candidates.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import polars as pl

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from e9b_analyze import build_trans_feature, rank_norm  # noqa: E402


class RevArgsShim:
    pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dump-dir", type=Path, required=True)
    ap.add_argument("--measure", type=Path, required=True)
    ap.add_argument("--pred-csv", type=Path, required=True)
    ap.add_argument("--scores", type=Path, required=True)
    ap.add_argument("--cands", type=Path, required=True)
    args = ap.parse_args()

    pairs = pl.read_csv(args.measure)
    nodes = (pl.read_csv(args.pred_csv).filter(pl.col("row_type") == "node")
             .select("dataset", "node_id", "t", "z", "y", "x"))
    scores = pl.read_csv(args.scores)
    cands = pl.read_csv(args.cands)
    cnn = cands.join(scores.select("cand_id", "score"), on="cand_id", how="left") \
               .select(pl.col("stem").alias("dataset"), "parent_id", "score") \
               .unique(subset=["dataset", "parent_id"])

    out_frames = []
    for (stem,), g in sorted(pairs.group_by("dataset"), key=lambda kv: kv[0][0]):
        f = args.dump_dir / f"{stem}_rev.csv"
        if not f.exists():
            print(f"{stem}: NO REV DUMP")
            continue
        nd = nodes.filter(pl.col("dataset") == stem)
        maps = build_trans_feature(f, nd)
        nm, pp = maps["nodemap"], maps["pair_prob"]
        # per-source target lists for readout (i)
        by_src: dict[int, list] = {}
        for (gi, gj), pr in pp.items():
            by_src.setdefault(gi, []).append((pr, gj))
        tp = np.zeros(g.height)
        p_ids = g["parent_id"].to_numpy(); o_ids = g["orphan_id"].to_numpy()
        for i in range(g.height):
            gp, gc = nm.get(int(p_ids[i])), nm.get(int(o_ids[i]))
            if gp is not None and gc is not None:
                tp[i] = pp.get((gp, gc), 0.0)
        gg = g.with_columns(pl.Series("rev_prob", tp))
        out_frames.append(gg)
        for r in gg.filter(pl.col("real")).iter_rows(named=True):
            gp, gc = nm.get(int(r["parent_id"])), nm.get(int(r["orphan_id"]))
            if gp is None or gc is None:
                print(f"{stem}: real (P={r['parent_id']},C2={r['orphan_id']}) kind={r['kind']} NODE-UNRESOLVED")
                continue
            lst = sorted(by_src.get(gp, []), reverse=True)
            in_top = [j for _, j in lst].index(gc) + 1 if gc in [j for _, j in lst] else -1
            print(f"{stem}: real (P={r['parent_id']},C2={r['orphan_id']}) kind={r['kind']} "
                  f"rev_prob={r['rev_prob']:.4f} rank_in_P_top5={in_top} "
                  f"P_top5={[f'{p:.3f}' for p, _ in lst[:5]]}")
    df = pl.concat(out_frames)
    reals = df.filter(pl.col("real"))
    print("=" * 70)
    for kind in ("steal", "adopt"):
        k = reals.filter(pl.col("kind") == kind)["rev_prob"]
        if len(k):
            print(f"real {kind}: n={len(k)} rev_prob med={k.median():.4f} "
                  f"nonzero={(k > 0).sum()}/{len(k)} vals={sorted([round(v,3) for v in k.to_list()], reverse=True)}")
    fake = df.filter(~pl.col("real"))["rev_prob"]
    print(f"fake pairs: nonzero={(fake > 0).mean():.4f} p99={fake.quantile(0.99):.4f}")

    df = df.join(cnn, on=["dataset", "parent_id"], how="left").filter(pl.col("score").is_not_null())
    df = df.with_columns(
        (-((pl.col("sister") - 10.6).abs() / 4.0 + (pl.col("d_pc") - 7.1).abs() / 3.0
           + pl.col("mid_over_sister"))).alias("geom"))
    df = df.with_columns(
        rank_norm("score").over("dataset").alias("r_cnn"),
        rank_norm("geom").over("dataset").alias("r_geom"),
        rank_norm("rev_prob").over("dataset").alias("r_rev"),
    ).with_columns(
        (pl.col("r_cnn") * pl.col("r_geom") * pl.col("r_rev")).alias("stack3r"),
    )
    for name, col in (("rev alone", "rev_prob"), ("stack3r CNN*geom*rev", "stack3r")):
        print("=" * 70)
        print(f"READOUT: within-video rank of real pairs by {name}")
        tops = {1: 0, 3: 0, 10: 0, 50: 0}
        for (stem,), g in sorted(df.group_by("dataset"), key=lambda kv: kv[0][0]):
            g = g.sort(col, descending=True).with_row_index("pos")
            for r in g.filter(pl.col("real")).iter_rows(named=True):
                pos = r["pos"] + 1
                for kk in tops:
                    tops[kk] += int(pos <= kk)
                if pos <= 50:
                    print(f"  {stem}: (P={r['parent_id']},C2={r['orphan_id']}) rank {pos}/{g.height} "
                          f"kind={r['kind']} rev={r['rev_prob']:.4f}")
        print(f"SUMMARY[{name}]: top1={tops[1]} top3={tops[3]} top10={tops[10]} top50={tops[50]}")


if __name__ == "__main__":
    main()
