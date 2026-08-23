#!/usr/bin/env python
"""E6: measure division-candidate separability on train videos with GT.

Input: a directory of *postprocessed* prediction CSV (from postproc_geffs)
plus local GT geffs. For every (parent, orphan) adoption candidate under the
revised gates (census n=151), extract features, label it real/fake by
checking against GT divisions (parent within 7 um of a GT divider whose
second daughter is within 7 um of the orphan), and report per-feature
separability + precision/recall of simple gate stacks.

    uv run python scripts/e6_measure.py --pred-csv outputs/e6_eval/pred.csv \
        --gt-dir data/train --out outputs/e6_eval/features.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from biohub.io import DEFAULT_SCALE, load_geff_graph  # noqa: E402

SCALE = np.array(DEFAULT_SCALE)
EXT = np.array([64, 256, 256]) * SCALE
# revised gates (census n=151)
D_PC_MAX = 14.0
SISTER_MIN, SISTER_MAX = 5.5, 21.0
ORPHAN_MIN_LEN = 2
MATCH_UM = 7.0


def gt_divisions(geff: Path) -> list[dict]:
    g = load_geff_graph(geff)
    na, ea = g.node_attrs(), g.edge_attrs()
    pos = {int(r["node_id"]): np.array([r["z"], r["y"], r["x"]]) * SCALE for r in na.iter_rows(named=True)}
    tt = {int(r["node_id"]): int(r["t"]) for r in na.iter_rows(named=True)}
    kids: dict[int, list[int]] = {}
    for r in ea.iter_rows(named=True):
        kids.setdefault(int(r["source_id"]), []).append(int(r["target_id"]))
    return [
        {"parent_pos": pos[p], "t": tt[p], "child_pos": [pos[c] for c in cs]}
        for p, cs in kids.items()
        if len(cs) == 2
    ]


def candidates_for_video(nodes: pl.DataFrame, edges: pl.DataFrame, divs: list[dict]) -> list[dict]:
    pos = {int(r["node_id"]): np.array([r["z"], r["y"], r["x"]]) * SCALE for r in nodes.iter_rows(named=True)}
    tof = {int(r["node_id"]): int(r["t"]) for r in nodes.iter_rows(named=True)}
    in_deg: dict[int, int] = {}
    child_of: dict[int, list[int]] = {}
    for r in edges.iter_rows(named=True):
        s, tt = int(r["source_id"]), int(r["target_id"])
        in_deg[tt] = in_deg.get(tt, 0) + 1
        child_of.setdefault(s, []).append(tt)

    def chain(n: int, k: int = 4) -> list[int]:
        out = [n]
        while len(out) < k:
            nxt = child_of.get(out[-1], [])
            if len(nxt) != 1:
                break
            out.append(nxt[0])
        return out

    orphans_by_t: dict[int, list[int]] = {}
    for n in pos:
        if in_deg.get(n, 0) == 0 and len(chain(n)) >= ORPHAN_MIN_LEN:
            orphans_by_t.setdefault(tof[n], []).append(n)

    out: list[dict] = []
    for p_id, kids_ in child_of.items():
        if len(kids_) != 1:
            continue
        c1 = kids_[0]
        if tof.get(c1) != tof[p_id] + 1:
            continue
        for c2 in orphans_by_t.get(tof[p_id] + 1, []):
            if c2 == c1:
                continue
            d_pc = float(np.linalg.norm(pos[c2] - pos[p_id]))
            if d_pc > D_PC_MAX:
                continue
            sis = float(np.linalg.norm(pos[c2] - pos[c1]))
            if not (SISTER_MIN <= sis <= SISTER_MAX):
                continue
            mid = (pos[c1] + pos[c2]) / 2
            border = min(float(np.min(pos[c2])), float(np.min(EXT - pos[c2])))
            ch = chain(c2)
            speed = float(np.linalg.norm(pos[ch[1]] - pos[ch[0]])) if len(ch) >= 2 else float("nan")
            # label: real iff parent matches a GT divider and orphan matches one of its daughters
            real = False
            for d in divs:
                if d["t"] != tof[p_id]:
                    continue
                if np.linalg.norm(pos[p_id] - d["parent_pos"]) > MATCH_UM:
                    continue
                if any(np.linalg.norm(pos[c2] - cp) <= MATCH_UM for cp in d["child_pos"]):
                    real = True
                    break
            out.append(
                {
                    "parent_id": p_id,
                    "orphan_id": c2,
                    "t": tof[p_id],
                    "d_pc": d_pc,
                    "sister": sis,
                    "mid_over_sister": float(np.linalg.norm(mid - pos[p_id])) / sis,
                    "border": border,
                    "orphan_speed": speed,
                    "orphan_len4": len(ch),
                    "real": real,
                }
            )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pred-csv", type=Path, required=True)
    ap.add_argument("--gt-dir", type=Path, default=ROOT / "data" / "train")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    df = pl.read_csv(args.pred_csv)
    rows: list[dict] = []
    n_divs_total = 0
    for (name,), g in sorted(df.group_by("dataset"), key=lambda kv: kv[0][0]):
        geff = args.gt_dir / f"{name}.geff"
        if not geff.exists():
            print(f"{name}: no GT, skip")
            continue
        divs = gt_divisions(geff)
        n_divs_total += len(divs)
        cands = candidates_for_video(
            g.filter(pl.col("row_type") == "node"), g.filter(pl.col("row_type") == "edge"), divs
        )
        for c in cands:
            c["dataset"] = name
        rows += cands
        print(f"{name}: GT_div={len(divs)} candidates={len(cands)} real={sum(c['real'] for c in cands)}")
    out = pl.DataFrame(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.write_csv(args.out)
    n_real = int(out["real"].sum()) if out.height else 0
    print(f"\nTOTAL: GT divisions={n_divs_total} candidates={out.height} real-in-pool={n_real} "
          f"(orphan-recoverable rate {n_real}/{n_divs_total})")
    if n_real:
        fake = out.filter(~pl.col("real"))
        real = out.filter(pl.col("real"))
        for c in ("d_pc", "sister", "mid_over_sister", "border", "orphan_speed"):
            fv, rv = fake[c].drop_nulls(), real[c].drop_nulls()
            print(f"{c:15} fake med={fv.median():.2f} [{fv.quantile(0.1):.2f},{fv.quantile(0.9):.2f}]  "
                  f"real med={rv.median():.2f} [{rv.min():.2f},{rv.max():.2f}]")


if __name__ == "__main__":
    main()
