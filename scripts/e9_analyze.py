#!/usr/bin/env python
"""E9 readouts: transformer pair-prob rank of real division pairs (ledger E9).

Dump rows: gi,gj,prob,t_src,z_src,y_src,x_src,t_tgt,z_tgt,y_tgt,x_tgt
(voxel units, original resolution). Real pairs come from e6_measure output
joined to the postproc submission for coordinates.

    uv run python scripts/e9_analyze.py \
        --dump-dir outputs/kaggle/eval_train_raw_v4/pair_probs \
        --measure outputs/e7/val12_measure.csv \
        --pred-csv outputs/e7/val12_post/submission.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import polars as pl

SCALE = np.array([1.625, 0.40625, 0.40625])
MATCH_UM = 2.0
DUMP_COLS = ["gi", "gj", "prob", "t_src", "z_src", "y_src", "x_src",
             "t_tgt", "z_tgt", "y_tgt", "x_tgt"]


def match_node(dump_pts_um: np.ndarray, dump_t: np.ndarray, t: int, p_um: np.ndarray) -> np.ndarray:
    m = dump_t == t
    d = np.linalg.norm(dump_pts_um[m] - p_um, axis=1)
    idx = np.where(m)[0]
    return idx[d <= MATCH_UM]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dump-dir", type=Path, required=True)
    ap.add_argument("--measure", type=Path, required=True)
    ap.add_argument("--pred-csv", type=Path, required=True)
    args = ap.parse_args()

    pairs = pl.read_csv(args.measure)
    nodes = (pl.read_csv(args.pred_csv).filter(pl.col("row_type") == "node")
             .select("dataset", "node_id", "t", "z", "y", "x"))
    edges = (pl.read_csv(args.pred_csv).filter(pl.col("row_type") == "edge")
             .select("dataset", "source_id", "target_id"))

    tops = {1: 0, 3: 0, 10: 0, 50: 0}
    n_matched = n_real = 0
    for (stem,), g in sorted(pairs.group_by("dataset"), key=lambda kv: kv[0][0]):
        f = args.dump_dir / f"{stem}.csv"
        if not f.exists():
            print(f"{stem}: no dump file")
            continue
        d = pl.read_csv(f, has_header=False, new_columns=DUMP_COLS)
        nd = nodes.filter(pl.col("dataset") == stem)
        pos = {int(r["node_id"]): np.array([r["z"], r["y"], r["x"]], dtype=float) * SCALE
               for r in nd.iter_rows(named=True)}
        tof = {int(r["node_id"]): int(r["t"]) for r in nd.iter_rows(named=True)}

        src_um = d.select("z_src", "y_src", "x_src").to_numpy() * SCALE
        tgt_um = d.select("z_tgt", "y_tgt", "x_tgt").to_numpy() * SCALE
        t_src = d["t_src"].to_numpy()
        t_tgt = d["t_tgt"].to_numpy()
        prob = d["prob"].to_numpy()

        # exclusion pool: dump pairs that correspond to solution edges
        ed = edges.filter(pl.col("dataset") == stem)
        sol = np.zeros(len(d), dtype=bool)
        for r in ed.iter_rows(named=True):
            s_id, t_id = int(r["source_id"]), int(r["target_id"])
            if s_id not in pos or t_id not in pos:
                continue
            si = match_node(src_um, t_src, tof[s_id], pos[s_id])
            if len(si) == 0:
                continue
            ti = match_node(tgt_um, t_tgt, tof[t_id], pos[t_id])
            both = np.intersect1d(si, ti)
            sol[both] = True
        pool = ~sol
        order = np.argsort(-prob)
        pool_rank = np.empty(len(d), dtype=np.int64)
        pr = 0
        for i in order:
            if pool[i]:
                pr += 1
                pool_rank[i] = pr
            else:
                pool_rank[i] = -1
        n_pool = int(pool.sum())

        for r in g.filter(pl.col("real")).iter_rows(named=True):
            n_real += 1
            p_id, c2 = int(r["parent_id"]), int(r["orphan_id"])
            si = match_node(src_um, t_src, tof[p_id], pos[p_id])
            ti = match_node(tgt_um, t_tgt, tof[c2], pos[c2])
            both = np.intersect1d(si, ti)
            if len(both) == 0:
                print(f"{stem}: real pair (P={p_id},C2={c2}) NOT IN DUMP "
                      f"(src_hits={len(si)} tgt_hits={len(ti)})")
                continue
            n_matched += 1
            i = both[np.argmax(prob[both])]
            rk = pool_rank[i] if pool[i] else 0
            note = "SOLUTION-EDGE" if not pool[i] else f"rank {rk}/{n_pool}"
            print(f"{stem}: real pair (P={p_id},C2={c2}) kind={r['kind']} "
                  f"prob={prob[i]:.4f} {note}")
            if pool[i]:
                for k in tops:
                    tops[k] += int(rk <= k)
    print(f"\nSUMMARY: real pairs={n_real} matched-in-dump={n_matched} "
          f"top1={tops[1]} top3={tops[3]} top10={tops[10]} top50={tops[50]}")


if __name__ == "__main__":
    main()
