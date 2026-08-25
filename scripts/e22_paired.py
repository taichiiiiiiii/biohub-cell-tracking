#!/usr/bin/env python
"""E22 readout: paired per-video comparison of bidir 0.30 vs 0.20 baseline (ledger E22).

Baseline = e7/val12_post + e8/val24_post (bidir 0.20, base weights, 36 videos).
New arm  = eval-36 run at bidir 0.30 (same weights, same postproc preset).

Registered bar (fixed before readout): mean paired dScore >= +0.002 AND
median > 0 AND >=22/36 videos non-negative  ->  adopt 0.30 in the base2 lineage.

    uv run python scripts/e22_paired.py --new-score outputs/e22/score.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median

BASELINES = [Path("outputs/e7/val12_post/score.json"), Path("outputs/e8/val24_post/score.json")]


def per_video(entry: dict) -> tuple[float, float]:
    adj = float(entry["adj_edge_jaccard"])
    denom = entry["division_tp"] + entry["division_fp"] + entry["division_fn"]
    div_j = entry["division_tp"] / denom if denom > 0 else 0.0
    return adj, adj + 0.1 * div_j


def load(paths: list[Path]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in paths:
        for e in json.loads(p.read_text())["per_dataset"]:
            assert e["dataset"] not in out, f"duplicate {e['dataset']}"
            out[e["dataset"]] = e
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--new-score", type=Path, required=True)
    args = ap.parse_args()

    base = load(BASELINES)
    new = load([args.new_score])
    common = sorted(set(base) & set(new))
    missing = sorted(set(base) ^ set(new))
    if missing:
        print(f"WARNING: unmatched datasets ({len(missing)}): {missing}")
    print(f"paired videos: {len(common)} (baseline {len(base)}, new {len(new)})\n")

    d_adj, d_score = [], []
    for ds in common:
        ba, bs = per_video(base[ds])
        na, ns = per_video(new[ds])
        d_adj.append(na - ba)
        d_score.append(ns - bs)
        print(f"{ds}: adj {ba:.4f}->{na:.4f} ({na-ba:+.4f})  score {bs:.4f}->{ns:.4f} ({ns-bs:+.4f})")

    n = len(d_score)
    nonneg = sum(1 for d in d_score if d >= 0)
    print(f"\nPAIRED dScore: mean {mean(d_score):+.4f}  median {median(d_score):+.4f}  "
          f"nonneg {nonneg}/{n}  worst {min(d_score):+.4f}  best {max(d_score):+.4f}")
    print(f"PAIRED dAdj  : mean {mean(d_adj):+.4f}  median {median(d_adj):+.4f}")
    ok = mean(d_score) >= 0.002 and median(d_score) > 0 and nonneg >= 22
    print(f"\nREGISTERED BAR (mean>=+0.002 & median>0 & >=22/36 nonneg): {'MET -> adopt 0.30' if ok else 'NOT MET -> keep 0.20'}")

    # summary-level micro comparison (reference only, not the judgment)
    for name, paths in (("baseline(12+24)", BASELINES), ("new", [args.new_score])):
        tp = fp = fn = 0
        for p in paths:
            s = json.loads(p.read_text())["summary"]
            tp += s["division_tp"]; fp += s["division_fp"]; fn += s["division_fn"]
        print(f"{name}: div TP/FP/FN = {tp}/{fp}/{fn}")


if __name__ == "__main__":
    main()
