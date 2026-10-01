#!/usr/bin/env python
"""E11: can transformer pair-prob prune FP (wrong-link) edges? (ledger E11)

Stage 1 (--stem): label every pred edge via official evaluate() (TP / FP_valid /
invisible), attach transformer prob + margin from the pair-prob dump, cache CSV.
Stage 2 (--aggregate): tau sweep with exact micro delta-J.

    uv run python scripts/e11_prune_probe.py --stem 44b6_341df25f \
        --pred-csv outputs/e7/val12_post/submission.csv \
        --dump-dir outputs/kaggle/eval_train_raw_v4/pair_probs
    uv run python scripts/e11_prune_probe.py --aggregate
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from e9b_analyze import build_trans_feature  # noqa: E402

from biohub.evaluate import graph_from_rows, read_submission  # noqa: E402
from biohub.io import load_geff_graph  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "official" / "src"))
from tracking_cellmot.metrics import evaluate as official_evaluate  # noqa: E402

SCALE = (1.625, 0.40625, 0.40625)
OUT = Path("outputs/e11")


def stage1(stem: str, pred_csv: Path, dump_dir: Path) -> None:
    import tracksdata as td
    K = td.DEFAULT_ATTR_KEYS
    df = read_submission(pred_csv).filter(pl.col("dataset") == stem)
    pred = graph_from_rows(df.filter(pl.col("row_type") == "node"),
                           df.filter(pl.col("row_type") == "edge"))
    gt = load_geff_graph(Path("data/train") / f"{stem}.geff")
    res = official_evaluate(pred, gt, scale=SCALE, max_distance=7.0)
    print(f"{stem}: tp={res.edge_tp} fp={res.edge_fp} fn={res.edge_fn}")

    pn = pred.node_attrs(attr_keys=[K.NODE_ID, K.MATCHED_NODE_ID, "t", "z", "y", "x"])
    pe = pred.edge_attrs(attr_keys=[K.MATCHED_EDGE_MASK])
    gt_ids = gt.node_ids()
    gt_out = dict(zip(gt_ids, gt.out_degree(gt_ids), strict=True))
    gt_in = dict(zip(gt_ids, gt.in_degree(gt_ids), strict=True))
    pmatch = {int(r[K.NODE_ID]): int(r[K.MATCHED_NODE_ID]) for r in pn.iter_rows(named=True)}

    nd = pn.select(pl.col(K.NODE_ID).alias("node_id"), "t", "z", "y", "x")
    maps = build_trans_feature(dump_dir / f"{stem}.csv", nd)
    nm, pp = maps["nodemap"], maps["pair_prob"]
    # best prob per dump target (for margin)
    best_tgt: dict[int, float] = {}
    for (_gi, gj), pr in pp.items():
        if pr > best_tgt.get(gj, 0.0):
            best_tgt[gj] = pr

    rows = []
    for r in pe.iter_rows(named=True):
        s, t_ = int(r[K.EDGE_SOURCE]), int(r[K.EDGE_TARGET])
        if r[K.MATCHED_EDGE_MASK]:
            lab = "TP"
        else:
            ms, mt = pmatch.get(s, -1), pmatch.get(t_, -1)
            out_valid = ms != -1 and gt_out.get(ms, 0) > 0
            in_valid = mt != -1 and gt_in.get(mt, 0) > 0
            lab = "FP_valid" if (out_valid or in_valid) else "invisible"
        gs, gtg = nm.get(s), nm.get(t_)
        covered = gs is not None and gtg is not None
        prob = pp.get((gs, gtg), 0.0) if covered else float("nan")
        margin = prob / best_tgt[gtg] if covered and gtg in best_tgt and best_tgt[gtg] > 0 else float("nan")
        rows.append({"stem": stem, "src": s, "tgt": t_, "label": lab,
                     "covered": covered, "prob": prob, "margin": margin})
    OUT.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(OUT / f"labels_{stem}.csv")
    json.dump({"tp": res.edge_tp, "fp": res.edge_fp, "fn": res.edge_fn},
              open(OUT / f"counts_{stem}.json", "w"))
    cov = sum(r["covered"] for r in rows)
    print(f"  edges={len(rows)} covered={cov} labels: "
          f"TP={sum(r['label'] == 'TP' for r in rows)} "
          f"FP={sum(r['label'] == 'FP_valid' for r in rows)} "
          f"inv={sum(r['label'] == 'invisible' for r in rows)}")


def aggregate() -> None:
    dfs = [pl.read_csv(f) for f in sorted(OUT.glob("labels_*.csv"))]
    df = pl.concat(dfs)
    counts = [json.load(open(f)) for f in sorted(OUT.glob("counts_*.json"))]
    TP0 = sum(c["tp"] for c in counts)
    FP0 = sum(c["fp"] for c in counts)
    FN0 = sum(c["fn"] for c in counts)
    j0 = TP0 / (TP0 + FP0 + FN0)
    print(f"baseline: TP={TP0} FP={FP0} FN={FN0} J={j0:.4f}")
    print("\ncoverage by label:")
    print(df.group_by("label").agg(pl.len().alias("n"), pl.col("covered").sum().alias("cov"),
                                   pl.col("prob").filter(pl.col("covered")).median().alias("prob_med")).sort("label"))
    print("\nprob distribution by label (covered edges only):")
    c = df.filter(pl.col("covered"))
    for lab in ("TP", "FP_valid", "invisible"):
        g = c.filter(pl.col("label") == lab)["prob"]
        if len(g):
            q = [float(g.quantile(x)) for x in (0.05, 0.25, 0.5, 0.75)]
            print(f"  {lab}: n={len(g)} p5={q[0]:.4f} p25={q[1]:.4f} med={q[2]:.4f} p75={q[3]:.4f}")
    for sig in ("prob", "margin"):
        print(f"\ntau sweep on {sig} (prune covered edges with {sig} < tau):")
        print(f"  {'tau':>8} {'TP_rm':>6} {'FP_rm':>6} {'inv_rm':>7} {'dJ':>9}")
        for tau in (0.001, 0.003, 0.01, 0.03, 0.1, 0.2, 0.3, 0.5):
            cut = c.filter(pl.col(sig) < tau)
            a = cut.filter(pl.col("label") == "TP").height
            b = cut.filter(pl.col("label") == "FP_valid").height
            iv = cut.filter(pl.col("label") == "invisible").height
            j1 = (TP0 - a) / (TP0 + FP0 + FN0 - b)
            print(f"  {tau:>8} {a:>6} {b:>6} {iv:>7} {j1 - j0:>+9.4f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stem")
    ap.add_argument("--pred-csv", type=Path, default=Path("outputs/e7/val12_post/submission.csv"))
    ap.add_argument("--dump-dir", type=Path, default=Path("outputs/kaggle/eval_train_raw_v4/pair_probs"))
    ap.add_argument("--aggregate", action="store_true")
    args = ap.parse_args()
    if args.aggregate:
        aggregate()
    else:
        stage1(args.stem, args.pred_csv, args.dump_dir)


if __name__ == "__main__":
    main()
