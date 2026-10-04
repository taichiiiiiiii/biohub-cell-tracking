#!/usr/bin/env python
"""Noise floor of the competition score under video resampling (bootstrap over videos).

Input: one or more score JSONs written by scripts/local_eval.py --json (they carry
per-dataset TP/FP/FN rows). Videos are resampled with replacement to the hidden
set sizes and the official micro-averaged score is recomputed with
tracking_cellmot.metrics.summarise each time.

    uv run python scripts/noise_floor_tracking.py outputs/kaggle/base1_v1/score.json --sizes 58 141 199

Output: per size, the bootstrap SD of the score and the "ignore below" line (2 SD).
With few videos the SD is itself uncertain — treat it as an order of magnitude.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "official" / "src"))

from tracking_cellmot.metrics import summarise  # noqa: E402

_DROP = {"dataset"}


def load_rows(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for p in paths:
        d = json.loads(p.read_text())
        for r in d["per_dataset"]:
            if r["dataset"] in seen:
                continue
            seen.add(r["dataset"])
            rows.append(r)
    return rows


def bootstrap(rows: list[dict], size: int, n_boot: int, rng: np.random.Generator) -> np.ndarray:
    clean = [{k: v for k, v in r.items() if k not in _DROP} for r in rows]
    out = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, len(clean), size=size)
        out[b] = summarise([clean[i] for i in idx])["score"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("score_json", nargs="+", type=Path)
    ap.add_argument("--sizes", nargs="+", type=int, default=[58, 141, 199], help="hidden set sizes to simulate")
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    rows = load_rows(args.score_json)
    full = summarise([{k: v for k, v in r.items() if k != "dataset"} for r in rows])
    print(f"videos: {len(rows)}   score on all: {full['score']:.4f}   "
          f"(adj_edge {full['adj_edge_jaccard']:.4f}, div {full['division_jaccard']:.4f})")
    per = sorted(
        ((r["adj_edge_jaccard"], r["edge_tp"] + r["edge_fp"] + r["edge_fn"], r["dataset"]) for r in rows), reverse=True
    )
    w_tot = sum(w for _, w, _ in per)
    print("per-video adj_edge_J and weight share (w = TP+FP+FN):")
    for j, w, name in per:
        print(f"  {name:16s} adj_J={j:.4f}  w={w:6d} ({100 * w / w_tot:5.1f}%)")
    if len(rows) < 8:
        print(f"WARNING: only {len(rows)} videos - the SD below is an order-of-magnitude estimate, not a measurement")
    rng = np.random.default_rng(args.seed)
    print("\n| hidden size | bootstrap SD | 2 SD (ignore differences below) |")
    print("|---|---|---|")
    for size in args.sizes:
        s = bootstrap(rows, size, args.n_boot, rng)
        print(f"| {size} | {s.std(ddof=1):.4f} | {2 * s.std(ddof=1):.4f} |")


if __name__ == "__main__":
    main()
