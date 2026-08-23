#!/usr/bin/env python
"""E6 division stage-2: adopt orphan track-starts as second children.

GT division signature (census n=12, complete geffs): the second daughter
lands 7-13 um from the parent -- beyond typical link gates -- so the linker
leaves it as a NEW track starting at t+1. This script finds
(parent P at t with exactly one child C1) x (orphan track-start C2 at t+1)
pairs within GT-derived geometry gates and adds the edge P->C2.

Usage:
    uv run python scripts/divstage2.py --in-csv outputs/kaggle/base1_v1/submission.csv \
        --out-csv outputs/e6/divstage2.csv [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from biohub.io import DEFAULT_SCALE  # noqa: E402

# GT-derived gates (E6 pre-registration; census n=12: d_child_max p90=12.08 max=13.38,
# sister med=11.04 p90=14.89 max=17.13 um)
PARENT_CHILD_MAX_UM = 14.0
SISTER_MAX_UM = 18.0
SISTER_MIN_UM = 4.0          # sisters p10=8.54; guard against duplicate detections
ORPHAN_MIN_TRACK_LEN = 3     # the adopted track must persist (noise guard)
PARENT_MIN_TRACK_LEN = 2     # the parent must have history
MAX_PER_VIDEO_FRAC = 0.02    # cap: adopted divisions <= 2% of GT-estimated node count / 100
CAP_OVERRIDE = 0
BORDER_MIN_UM = 15.0         # daughters are interior; ~half of fake orphans hug the border
VOLUME_EXTENT_VOX = (64, 256, 256)  # (Z,Y,X): constant across all competition videos


def track_lengths(nodes: pl.DataFrame, edges: pl.DataFrame) -> dict[int, int]:
    """Length (node count) of the weakly-connected chain each node belongs to,
    following single-parent/single-child edges only (cheap union-find)."""
    parent = {}

    def find(x: int) -> int:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for s, t in zip(edges["source_id"].to_list(), edges["target_id"].to_list(), strict=True):
        union(s, t)
    sizes: dict[int, int] = {}
    for n in nodes["node_id"].to_list():
        r = find(n)
        sizes[r] = sizes.get(r, 0) + 1
    return {n: sizes[find(n)] for n in nodes["node_id"].to_list()}


def process_video(nodes: pl.DataFrame, edges: pl.DataFrame, scale: np.ndarray) -> list[tuple[int, int, dict]]:
    """Return [(parent_id, orphan_id, info)] adoption candidates for one video."""
    out_deg: dict[int, int] = {}
    in_deg: dict[int, int] = {}
    child_of: dict[int, list[int]] = {}
    for s, t in zip(edges["source_id"].to_list(), edges["target_id"].to_list(), strict=True):
        out_deg[s] = out_deg.get(s, 0) + 1
        in_deg[t] = in_deg.get(t, 0) + 1
        child_of.setdefault(s, []).append(t)

    tlen = track_lengths(nodes, edges)
    pos = {int(r["node_id"]): np.array([r["z"], r["y"], r["x"]]) * scale for r in nodes.iter_rows(named=True)}
    tof = {int(r["node_id"]): int(r["t"]) for r in nodes.iter_rows(named=True)}

    # orphan track-starts by frame (in-deg 0, has at least one child = track persists)
    ext = np.array(VOLUME_EXTENT_VOX) * scale
    orphans_by_t: dict[int, list[int]] = {}
    for n in pos:
        if in_deg.get(n, 0) != 0 or tlen.get(n, 1) < ORPHAN_MIN_TRACK_LEN:
            continue
        border = min(float(np.min(pos[n])), float(np.min(ext - pos[n])))
        if border < BORDER_MIN_UM:  # likely a cell entering the field of view
            continue
        orphans_by_t.setdefault(tof[n], []).append(n)

    cands: list[tuple[float, int, int, dict]] = []
    for p_id, kids in child_of.items():
        if len(kids) != 1:            # exactly one child -> can adopt one more (out-deg<=2)
            continue
        if tlen.get(p_id, 1) < PARENT_MIN_TRACK_LEN:
            continue
        c1 = kids[0]
        t_next = tof[p_id] + 1
        if tof.get(c1) != t_next:
            continue
        for c2 in orphans_by_t.get(t_next, []):
            if c2 == c1:
                continue
            d_pc = float(np.linalg.norm(pos[c2] - pos[p_id]))
            if d_pc > PARENT_CHILD_MAX_UM:
                continue
            sis = float(np.linalg.norm(pos[c2] - pos[c1]))
            if not (SISTER_MIN_UM <= sis <= SISTER_MAX_UM):
                continue
            # rank by fit to the GT division prior (census n=12: sister med 11.04,
            # d_child med ~4.7-7.1 um). Near-duplicate detections (small sister,
            # small d_pc) score badly instead of greedily starving the cap.
            prior = abs(sis - 11.0) / 4.0 + abs(d_pc - 7.0) / 3.0
            cands.append((prior, p_id, c2, {"d_pc": round(d_pc, 2), "sister": round(sis, 2), "t": tof[p_id]}))

    # best prior fit first; each orphan adopted once, each parent forks once
    cands.sort(key=lambda x: x[0])
    used_p: set[int] = set()
    used_c: set[int] = set()
    picked: list[tuple[int, int, dict]] = []
    cap = CAP_OVERRIDE if CAP_OVERRIDE > 0 else max(3, int(len(pos) * MAX_PER_VIDEO_FRAC / 100))
    for _, p_id, c2, info in cands:
        if p_id in used_p or c2 in used_c:
            continue
        picked.append((p_id, c2, info))
        used_p.add(p_id)
        used_c.add(c2)
        if len(picked) >= cap:
            break
    return picked


def main() -> None:
    global PARENT_CHILD_MAX_UM, SISTER_MAX_UM, SISTER_MIN_UM, ORPHAN_MIN_TRACK_LEN, BORDER_MIN_UM
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in-csv", type=Path, required=True)
    ap.add_argument("--out-csv", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    for name, default in (
        ("--parent-child-max-um", PARENT_CHILD_MAX_UM),
        ("--sister-max-um", SISTER_MAX_UM),
        ("--sister-min-um", SISTER_MIN_UM),
    ):
        ap.add_argument(name, type=float, default=default)
    ap.add_argument("--orphan-min-len", type=int, default=ORPHAN_MIN_TRACK_LEN)
    ap.add_argument("--cap", type=int, default=0, help="fixed per-video adoption cap (0 = frac-based default)")
    ap.add_argument("--border-min-um", type=float, default=BORDER_MIN_UM)
    args = ap.parse_args()

    PARENT_CHILD_MAX_UM = args.parent_child_max_um
    SISTER_MAX_UM = args.sister_max_um
    SISTER_MIN_UM = args.sister_min_um
    ORPHAN_MIN_TRACK_LEN = args.orphan_min_len
    BORDER_MIN_UM = args.border_min_um
    global CAP_OVERRIDE
    CAP_OVERRIDE = args.cap

    scale = np.array(DEFAULT_SCALE)
    df = pl.read_csv(args.in_csv)
    new_edges: list[dict] = []
    for (name,), g in sorted(df.group_by("dataset"), key=lambda kv: kv[0][0]):
        nodes = g.filter(pl.col("row_type") == "node")
        edges = g.filter(pl.col("row_type") == "edge")
        picked = process_video(nodes, edges, scale)
        print(f"{name}: {len(picked)} adoptions " + " ".join(str(i) for *_, i in picked))
        for p_id, c2, _ in picked:
            new_edges.append({"dataset": name, "row_type": "edge", "source_id": p_id, "target_id": c2})
    if args.dry_run:
        return
    if new_edges:
        add = pl.DataFrame(new_edges)
        add = add.with_columns([pl.lit(None, dtype=df[c].dtype).alias(c) for c in df.columns if c not in add.columns])
        df = pl.concat([df, add.select(df.columns)])
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.write_csv(args.out_csv)
    print(f"wrote {args.out_csv} (+{len(new_edges)} edges)")


if __name__ == "__main__":
    main()
