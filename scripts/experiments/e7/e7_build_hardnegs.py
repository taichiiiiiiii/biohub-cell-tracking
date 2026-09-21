#!/usr/bin/env python
"""Build hardnegs.csv from scored eval-24 candidate parents (ledger E7-15).

Top-K highest-CNN-score FAKE parents per video, excluding anything within
MATCH_UM of a GT divider at the same t (a duplicate detection of a real
divider must not be labelled negative).

    uv run python scripts/e7_build_hardnegs.py \
        --cands outputs/e7/cands_dataset/candidates24.csv \
        --scores outputs/kaggle/div_score_cands_v2/scores_candidates24.csv \
        --out outputs/e8/hardnegs_dataset/hardnegs.csv
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
TOP_K = 40


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cands", type=Path, required=True)
    ap.add_argument("--scores", type=Path, required=True)
    ap.add_argument("--gt-dir", type=Path, default=Path("data/train"))
    ap.add_argument("--top-k", type=int, default=TOP_K)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    df = pl.read_csv(args.cands).join(
        pl.read_csv(args.scores).select("cand_id", "score"), on="cand_id", how="inner")
    rows = []
    for (stem,), g in sorted(df.group_by("stem"), key=lambda kv: kv[0][0]):
        divs = gt_divisions(args.gt_dir / f"{stem}.geff")
        g = g.filter(~pl.col("is_real_parent")).sort("score", descending=True)
        taken = 0
        for r in g.iter_rows(named=True):
            if taken >= args.top_k:
                break
            p_um = np.array([r["z"], r["y"], r["x"]], dtype=float) * SCALE
            if any(d["t"] == r["t"] and np.linalg.norm(p_um - d["parent_pos"]) <= MATCH_UM
                   for d in divs):
                continue  # too close to a real divider -> ambiguous, skip
            rows.append({"stem": stem, "t": r["t"], "z": r["z"], "y": r["y"], "x": r["x"]})
            taken += 1
        print(f"{stem}: {taken} hard negatives")
    out = pl.DataFrame(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.write_csv(args.out)
    print(f"wrote {out.height} hard negatives -> {args.out}")


if __name__ == "__main__":
    main()
