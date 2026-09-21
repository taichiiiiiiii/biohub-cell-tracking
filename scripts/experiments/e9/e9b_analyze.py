#!/usr/bin/env python
"""E9-b readouts: transformer pair prob as a feature on the candidate-pair table.

Universe = val12_measure.csv (1.23M orphan/parent pairs, real=23).  For each
pair (P at t -> C2 at t+1) resolve both submission nodes to dump detection
indices (exact voxel coords first, then <=2um nearest at same t), then look up
the dump prob for (g_P, g_C2).  Pairs absent from the per-target top-5 dump get
trans_prob = 0.

    uv run python scripts/e9b_analyze.py \
        --dump-dir outputs/kaggle/eval_train_raw_v4/pair_probs \
        --measure outputs/e7/val12_measure.csv \
        --pred-csv outputs/e7/val12_post/submission.csv \
        --scores outputs/kaggle/div_score_cands_v3/cand_scores.csv \
        --cands outputs/e7/cands_dataset/candidates.csv
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import numpy as np
import polars as pl

SCALE = np.array([1.625, 0.40625, 0.40625])
DUMP_DS = np.array([1.0, 4.0, 4.0])  # detector grid -> voxel (downsample [1,4,4])
MATCH_UM = 2.0
DUMP_COLS = ["gi", "gj", "prob", "t_src", "z_src", "y_src", "x_src",
             "t_tgt", "z_tgt", "y_tgt", "x_tgt"]


def rank_norm(col: str) -> pl.Expr:
    return (pl.col(col).rank(method="average") - 1) / (pl.len() - 1)


def build_trans_feature(dump_file: Path, nd: pl.DataFrame) -> dict[int, dict]:
    """Return node_id -> g-index map and (gi,gj) -> prob map for one video."""
    d = pl.read_csv(dump_file, has_header=False, new_columns=DUMP_COLS)
    # g-index -> (t, voxel coords) from both src and tgt occurrences
    g_coord: dict[int, tuple] = {}
    for side, tcol in (("src", "t_src"), ("tgt", "t_tgt")):
        sub = d.select(pl.col(f"g{'i' if side == 'src' else 'j'}").alias("g"),
                       pl.col(tcol).alias("t"),
                       pl.col(f"z_{side}").alias("z"),
                       pl.col(f"y_{side}").alias("y"),
                       pl.col(f"x_{side}").alias("x")).unique(subset=["g"])
        for r in sub.iter_rows():
            g_coord.setdefault(int(r[0]), (int(r[1]), float(r[2]) * DUMP_DS[0],
                                           float(r[3]) * DUMP_DS[1], float(r[4]) * DUMP_DS[2]))
    # per-t buckets in um for fallback NN
    by_t: dict[int, list] = defaultdict(list)
    exact: dict[tuple, int] = {}
    for g, (t, z, y, x) in g_coord.items():
        exact[(t, round(z), round(y), round(x))] = g
        by_t[t].append((g, np.array([z, y, x]) * SCALE))
    bt = {t: (np.array([v[1] for v in lst]), [v[0] for v in lst]) for t, lst in by_t.items()}

    nodemap: dict[int, int] = {}
    n_exact = n_nn = 0
    for r in nd.iter_rows(named=True):
        nid, t = int(r["node_id"]), int(r["t"])
        key = (t, round(r["z"]), round(r["y"]), round(r["x"]))
        if key in exact:
            nodemap[nid] = exact[key]
            n_exact += 1
            continue
        if t in bt:
            pts, gs = bt[t]
            dd = np.linalg.norm(pts - np.array([r["z"], r["y"], r["x"]]) * SCALE, axis=1)
            i = int(np.argmin(dd))
            if dd[i] <= MATCH_UM:
                nodemap[nid] = gs[i]
                n_nn += 1
    pair_prob: dict[tuple, float] = {}
    for gi, gj, prob in d.select("gi", "gj", "prob").iter_rows():
        k = (int(gi), int(gj))
        if prob > pair_prob.get(k, 0.0):
            pair_prob[k] = float(prob)
    print(f"  nodes matched: exact={n_exact} nn={n_nn} / {nd.height} "
          f"(dump g-nodes={len(g_coord)}, pair rows={d.height})")
    return {"nodemap": nodemap, "pair_prob": pair_prob}


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
        f = args.dump_dir / f"{stem}.csv"
        nd = nodes.filter(pl.col("dataset") == stem)
        print(f"{stem}: pairs={g.height}")
        maps = build_trans_feature(f, nd)
        nm, pp = maps["nodemap"], maps["pair_prob"]
        tp = np.zeros(g.height)
        p_ids = g["parent_id"].to_numpy()
        o_ids = g["orphan_id"].to_numpy()
        for i in range(g.height):
            gp, gc = nm.get(int(p_ids[i])), nm.get(int(o_ids[i]))
            if gp is not None and gc is not None:
                tp[i] = pp.get((gp, gc), 0.0)
        out_frames.append(g.with_columns(pl.Series("trans_prob", tp)))
    df = pl.concat(out_frames)
    df = df.join(cnn, on=["dataset", "parent_id"], how="left")
    df = df.filter(pl.col("score").is_not_null())
    # geometry prior: same fixed form as E7 readout 2
    df = df.with_columns(
        (-((pl.col("sister") - 10.6).abs() / 4.0 + (pl.col("d_pc") - 7.1).abs() / 3.0
           + pl.col("mid_over_sister"))).alias("geom"))
    df = df.with_columns(
        rank_norm("score").over("dataset").alias("r_cnn"),
        rank_norm("geom").over("dataset").alias("r_geom"),
        rank_norm("trans_prob").over("dataset").alias("r_trans"),
    ).with_columns(
        (pl.col("r_cnn") * pl.col("r_geom")).alias("stack2"),
        (pl.col("r_cnn") * pl.col("r_geom") * pl.col("r_trans")).alias("stack3"),
    )

    # readout (i): coverage
    reals = df.filter(pl.col("real"))
    cov = int((reals["trans_prob"] > 0).sum())
    print("=" * 70)
    print(f"READOUT i: real pairs with trans_prob>0: {cov}/{reals.height}")
    nz = float((df["trans_prob"] > 0).mean())
    print(f"  (all pairs nonzero fraction: {nz:.4f})")

    for name, col in (("trans alone", "trans_prob"), ("stack2 CNN*geom (E7 baseline)", "stack2"),
                      ("stack3 CNN*geom*trans", "stack3")):
        print("=" * 70)
        print(f"READOUT: within-video rank of real pairs by {name}")
        tops = {1: 0, 3: 0, 10: 0, 50: 0}
        for (stem,), g in sorted(df.group_by("dataset"), key=lambda kv: kv[0][0]):
            g = g.sort(col, descending=True).with_row_index("pos")
            for r in g.filter(pl.col("real")).iter_rows(named=True):
                pos = r["pos"] + 1
                for k in tops:
                    tops[k] += int(pos <= k)
                if pos <= 50:
                    print(f"  {stem}: (P={r['parent_id']},C2={r['orphan_id']}) rank {pos}/{g.height} "
                          f"kind={r['kind']} trans={r['trans_prob']:.4f}")
        print(f"SUMMARY[{name}]: top1={tops[1]} top3={tops[3]} top10={tops[10]} top50={tops[50]}")


if __name__ == "__main__":
    main()
