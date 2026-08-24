#!/usr/bin/env python
"""E12: 3-frame motion consistency as an orthogonal wrong-link signal (ledger E12).

Joins E11 label CSVs with parent-side incoming edges from the submission to
compute acceleration = ||(v-u) - (u-w)|| um for each pred edge (w->u->v).

    uv run python scripts/e12_motion_probe.py \
        --pred-csv outputs/e7/val12_post/submission.csv --labels-dir outputs/e11
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl

SCALE = np.array([1.625, 0.40625, 0.40625])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pred-csv", type=Path, default=Path("outputs/e7/val12_post/submission.csv"))
    ap.add_argument("--labels-dir", type=Path, default=Path("outputs/e11"))
    args = ap.parse_args()

    sub = pl.read_csv(args.pred_csv)
    frames = []
    for f in sorted(args.labels_dir.glob("labels_*.csv")):
        stem = f.stem.replace("labels_", "")
        lab = pl.read_csv(f)
        g = sub.filter(pl.col("dataset") == stem)
        nodes = g.filter(pl.col("row_type") == "node")
        edges = g.filter(pl.col("row_type") == "edge")
        # E11 labels use tracksdata ids = insertion order of node rows
        nid = nodes["node_id"].to_numpy()
        td_of_sub = {int(v): i for i, v in enumerate(nid)}
        pos = nodes.select("z", "y", "x").to_numpy() * SCALE
        # parent map in tracksdata-id space
        parent = {}
        for s_, t_ in zip(edges["source_id"].to_numpy(), edges["target_id"].to_numpy()):
            parent[td_of_sub[int(t_)]] = td_of_sub[int(s_)]
        acc, dv1, dv2 = [], [], []
        for r in lab.iter_rows(named=True):
            u, v = int(r["src"]), int(r["tgt"])
            w = parent.get(u)
            if w is None:
                acc.append(float("nan")); dv1.append(float("nan")); dv2.append(float("nan"))
                continue
            v1 = pos[u] - pos[w]
            v2 = pos[v] - pos[u]
            acc.append(float(np.linalg.norm(v2 - v1)))
            dv1.append(float(np.linalg.norm(v1)))
            dv2.append(float(np.linalg.norm(v2)))
        frames.append(lab.with_columns(pl.Series("acc", acc), pl.Series("speed_in", dv1),
                                       pl.Series("speed_out", dv2)))
    df = pl.concat(frames)
    counts = [json.load(open(f)) for f in sorted(args.labels_dir.glob("counts_*.json"))]
    TP0 = sum(c["tp"] for c in counts); FP0 = sum(c["fp"] for c in counts); FN0 = sum(c["fn"] for c in counts)
    j0 = TP0 / (TP0 + FP0 + FN0)
    print(f"baseline: TP={TP0} FP={FP0} FN={FN0} J={j0:.4f}")

    has = df.filter(pl.col("acc").is_not_nan())
    print(f"\nedges with motion history: {has.height}/{df.height}")
    for lab in ("TP", "FP_valid", "invisible"):
        g = has.filter(pl.col("label") == lab)["acc"]
        if len(g):
            q = [float(g.quantile(x)) for x in (0.25, 0.5, 0.75, 0.95)]
            print(f"  acc[{lab}]: n={len(g)} p25={q[0]:.2f} med={q[1]:.2f} p75={q[2]:.2f} p95={q[3]:.2f} um")

    print("\ntau sweep: prune edges with acc > tau (motion-history edges only):")
    print(f"  {'tau':>6} {'TP_rm':>6} {'FP_rm':>6} {'inv_rm':>7} {'dJ':>9}")
    for tau in (3, 4, 5, 6, 8, 10, 12, 15):
        cut = has.filter(pl.col("acc") > tau)
        a = cut.filter(pl.col("label") == "TP").height
        b = cut.filter(pl.col("label") == "FP_valid").height
        iv = cut.filter(pl.col("label") == "invisible").height
        j1 = (TP0 - a) / (TP0 + FP0 + FN0 - b)
        print(f"  {tau:>6} {a:>6} {b:>6} {iv:>7} {j1 - j0:>+9.4f}")

    print("\ncombo sweep: prune if acc > tau_a AND prob < tau_p (covered & history):")
    both = has.filter(pl.col("covered") & pl.col("prob").is_not_nan())
    print(f"  {'tau_a':>6} {'tau_p':>6} {'TP_rm':>6} {'FP_rm':>6} {'dJ':>9}")
    for ta in (4, 6, 8, 10):
        for tp_ in (0.3, 0.5, 0.7, 0.9):
            cut = both.filter((pl.col("acc") > ta) & (pl.col("prob") < tp_))
            a = cut.filter(pl.col("label") == "TP").height
            b = cut.filter(pl.col("label") == "FP_valid").height
            j1 = (TP0 - a) / (TP0 + FP0 + FN0 - b)
            print(f"  {ta:>6} {tp_:>6} {a:>6} {b:>6} {j1 - j0:>+9.4f}")


if __name__ == "__main__":
    main()
