#!/usr/bin/env python
"""Build candidates.csv for the div_score_cands kernel (E7 deployment test).

Joins e6_measure candidate rows (parent_id per video) with the submission CSV
node coordinates, attaches the CV fold that held each video out, and writes
stem,cand_id,t,z,y,x,fold plus the feature columns for later stacking.

    uv run python scripts/e7_build_cands.py \
        --measure outputs/e7/val12_measure.csv \
        --pred-csv outputs/e7/val12_post/submission.csv \
        --model-info outputs/kaggle/div_classifier_v2/model_info.json \
        --out outputs/e7/candidates.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e6_measure import SCALE, gt_divisions  # noqa: E402

MATCH_UM = 7.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--measure", type=Path, required=True)
    ap.add_argument("--pred-csv", type=Path, required=True)
    ap.add_argument("--model-info", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--gt-dir", type=Path, default=Path("data/train"))
    args = ap.parse_args()

    cands = pl.read_csv(args.measure)
    nodes = (
        pl.read_csv(args.pred_csv)
        .filter(pl.col("row_type") == "node")
        .select("dataset", "node_id", "t", "z", "y", "x")
    )
    folds = json.load(open(args.model_info))["folds"]

    joined = cands.join(
        nodes.rename({"node_id": "parent_id", "t": "t_node"}),
        on=["dataset", "parent_id"],
        how="left",
    )
    n_missing = joined.filter(pl.col("z").is_null()).height
    if n_missing:
        raise SystemExit(f"{n_missing} candidates failed the coordinate join")
    bad_t = joined.filter(pl.col("t") != pl.col("t_node")).height
    if bad_t:
        raise SystemExit(f"{bad_t} candidates with t mismatch between measure and pred CSV")

    # existing pred forks (out-degree-2 parents): candidates for CNN-based FP veto
    pred = pl.read_csv(args.pred_csv)
    fork_rows = []
    for (name,), g in sorted(pred.group_by("dataset"), key=lambda kv: kv[0][0]):
        divs = gt_divisions(args.gt_dir / f"{name}.geff")
        nd = g.filter(pl.col("row_type") == "node")
        ed = g.filter(pl.col("row_type") == "edge")
        pos = {int(r["node_id"]): np.array([r["z"], r["y"], r["x"]], dtype=float)
               for r in nd.iter_rows(named=True)}
        tof = {int(r["node_id"]): int(r["t"]) for r in nd.iter_rows(named=True)}
        outdeg: dict[int, int] = {}
        for r in ed.iter_rows(named=True):
            outdeg[int(r["source_id"])] = outdeg.get(int(r["source_id"]), 0) + 1
        for p_id, deg in outdeg.items():
            if deg < 2:
                continue
            p_um = pos[p_id] * SCALE
            real = any(
                d["t"] == tof[p_id] and np.linalg.norm(p_um - d["parent_pos"]) <= MATCH_UM
                for d in divs
            )
            z, y, x = pos[p_id]
            fork_rows.append({"stem": name, "t": tof[p_id], "z": z, "y": y, "x": x,
                              "fold": folds[name], "kind": "existing_fork",
                              "parent_id": p_id, "orphan_id": -1, "real": real})
    print(f"existing forks: {len(fork_rows)} (real={sum(r['real'] for r in fork_rows)})")

    out = joined.with_columns(
        pl.col("dataset").alias("stem"),
        pl.arange(0, joined.height).alias("cand_id"),
        pl.col("dataset").map_elements(lambda s: folds[s], return_dtype=pl.Int64).alias("fold"),
    ).select(
        "stem", "cand_id", "t", "z", "y", "x", "fold",
        "kind", "parent_id", "orphan_id", "d_pc", "sister", "mid_over_sister",
        "border", "orphan_speed", "orphan_len4", "d_qc", "real",
    )
    if fork_rows:
        forks = pl.DataFrame(fork_rows).with_columns(
            (pl.arange(0, len(fork_rows)) + out.height).alias("cand_id"),
        )
        out = pl.concat([out, forks], how="diagonal")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.write_csv(args.out)
    print(f"wrote {out.height} candidates, real={int(out['real'].sum())}, "
          f"videos={out['stem'].n_unique()}")
    for stem, g in sorted(out.group_by("stem"), key=lambda kv: kv[0][0]):
        print(f"  {stem}: cands={g.height} real={int(g['real'].sum())} fold={g['fold'][0]}")


if __name__ == "__main__":
    main()
