#!/usr/bin/env python
"""E10: edge-term failure census on eval-12 (ledger E10).

For one video, runs the OFFICIAL evaluate() (which writes matching attrs onto
the pred graph) and classifies every GT edge FN by cause, plus FP edges.

    uv run python scripts/e10_edge_census.py --stem 44b6_12dfb391 \
        --pred-csv outputs/e7/val12_post/submission.csv \
        --gt-dir data/train --out-dir outputs/e10
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from biohub.evaluate import graph_from_rows, read_submission  # noqa: E402
from biohub.io import load_geff_graph  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "official" / "src"))
from tracking_cellmot.metrics import evaluate as official_evaluate  # noqa: E402

SCALE = (1.625, 0.40625, 0.40625)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stem", required=True)
    ap.add_argument("--pred-csv", type=Path, required=True)
    ap.add_argument("--gt-dir", type=Path, default=Path("data/train"))
    ap.add_argument("--out-dir", type=Path, default=Path("outputs/e10"))
    args = ap.parse_args()
    import tracksdata as td
    K = td.DEFAULT_ATTR_KEYS

    df = read_submission(args.pred_csv).filter(pl.col("dataset") == args.stem)
    nodes = df.filter(pl.col("row_type") == "node")
    edges = df.filter(pl.col("row_type") == "edge")
    pred = graph_from_rows(nodes, edges)
    gt = load_geff_graph(args.gt_dir / f"{args.stem}.geff")
    res = official_evaluate(pred, gt, scale=SCALE, max_distance=7.0)
    print(f"{args.stem}: official edge tp={res.edge_tp} fp={res.edge_fp} fn={res.edge_fn}")

    pn = pred.node_attrs(attr_keys=[K.NODE_ID, K.MATCHED_NODE_ID, "t", "z", "y", "x"])
    pe = pred.edge_attrs(attr_keys=[K.MATCHED_EDGE_MASK])
    gn = gt.node_attrs(attr_keys=[K.NODE_ID, "t", "z", "y", "x"])
    ge = gt.edge_attrs(attr_keys=[])
    gt_ids = gt.node_ids()
    gt_out = dict(zip(gt_ids, gt.out_degree(gt_ids)))
    gt_in = dict(zip(gt_ids, gt.in_degree(gt_ids)))

    m = {int(r[K.MATCHED_NODE_ID]): int(r[K.NODE_ID])
         for r in pn.iter_rows(named=True) if r[K.MATCHED_NODE_ID] != -1}
    sc = np.array(SCALE)
    p_by_t: dict[int, np.ndarray] = defaultdict(lambda: np.empty((0, 3)))
    for t, g in pn.group_by("t"):
        p_by_t[int(t[0])] = g.select("z", "y", "x").to_numpy() * sc
    g_pos = {int(r[K.NODE_ID]): np.array([r["z"], r["y"], r["x"]]) * sc
             for r in gn.iter_rows(named=True)}
    g_t = {int(r[K.NODE_ID]): int(r["t"]) for r in gn.iter_rows(named=True)}

    pred_children: dict[int, list] = defaultdict(list)
    pred_parents: dict[int, list] = defaultdict(list)
    tp_pairs = set()
    pred_edge_set = set()
    pmatch = {int(r[K.NODE_ID]): int(r[K.MATCHED_NODE_ID]) for r in pn.iter_rows(named=True)}
    for r in pe.iter_rows(named=True):
        s, t_ = int(r[K.EDGE_SOURCE]), int(r[K.EDGE_TARGET])
        pred_children[s].append(t_)
        pred_parents[t_].append(s)
        pred_edge_set.add((s, t_))
        if r[K.MATCHED_EDGE_MASK]:
            tp_pairs.add((pmatch[s], pmatch[t_]))

    def near_pred(gid: int) -> float:
        pts = p_by_t.get(g_t[gid])
        if pts is None or not len(pts):
            return np.inf
        return float(np.min(np.linalg.norm(pts - g_pos[gid], axis=1)))

    rows = []
    for r in ge.iter_rows(named=True):
        u, v = int(r[K.EDGE_SOURCE]), int(r[K.EDGE_TARGET])
        if (u, v) in tp_pairs:
            cat = "TP"
        elif u not in m:
            cat = "parent_det_stolen" if near_pred(u) <= 7.0 else "parent_no_detection"
        elif v not in m:
            cat = "child_det_stolen" if near_pred(v) <= 7.0 else "child_no_detection"
        else:
            pu, pv = m[u], m[v]
            if (pu, pv) in pred_edge_set:
                cat = "edge_dropped_by_dedup"
            else:
                has_out, has_in = bool(pred_children[pu]), bool(pred_parents[pv])
                cat = ("link_gap" if not has_out and not has_in else
                       "parent_track_end" if not has_out else
                       "child_track_start" if not has_in else
                       "both_linked_elsewhere")
        rows.append({"stem": args.stem, "gt_src": u, "gt_tgt": v, "t": g_t[u],
                     "z": g_pos[u][0] / sc[0], "y": g_pos[u][1] / sc[1], "x": g_pos[u][2] / sc[2],
                     "is_div": gt_out.get(u, 0) == 2, "category": cat})

    # FP edges: not matched but pred_valid per official definition
    n_fp = Counter()
    for r in pe.iter_rows(named=True):
        if r[K.MATCHED_EDGE_MASK]:
            continue
        s, t_ = int(r[K.EDGE_SOURCE]), int(r[K.EDGE_TARGET])
        ms, mt = pmatch.get(s, -1), pmatch.get(t_, -1)
        out_valid = ms != -1 and gt_out.get(ms, 0) > 0
        in_valid = mt != -1 and gt_in.get(mt, 0) > 0
        if not (out_valid or in_valid):
            continue  # invisible to metric (sparse GT)
        n_fp[("fp_src_gt_parents_elsewhere" if out_valid else "") +
             ("+" if out_valid and in_valid else "") +
             ("fp_tgt_gt_has_other_parent" if in_valid else "")] += 1

    out = pl.DataFrame(rows)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out.write_csv(args.out_dir / f"census_{args.stem}.csv")
    cc = Counter(out["category"].to_list())
    tp_n = cc.pop("TP", 0)
    fn_n = sum(cc.values())
    print(f"  census: TP={tp_n} FN={fn_n} (official fn={res.edge_fn}) FP_valid={sum(n_fp.values())} (official fp={res.edge_fp})")
    for k, v in sorted(cc.items(), key=lambda kv: -kv[1]):
        nd = int(out.filter((pl.col("category") == k) & pl.col("is_div")).height)
        print(f"    FN {k}: {v} (div-edge {nd})")
    for k, v in sorted(n_fp.items(), key=lambda kv: -kv[1]):
        print(f"    FP {k}: {v}")


if __name__ == "__main__":
    main()
