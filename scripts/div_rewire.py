#!/usr/bin/env python
"""E7 division stage-2: CNN-gated adoption / steal / twin-merge rewiring.

Measurement-mode driver: takes the postprocessed submission CSV, the
unique-parent CNN scores from the div_score_cands kernel, and the pair pool
from e6_measure, applies rewiring, and writes a new submission CSV for
official scoring on eval-12.

    uv run python scripts/div_rewire.py \
        --in-csv outputs/e7/val12_post/submission.csv \
        --cands outputs/e7/cands_dataset/candidates.csv \
        --scores outputs/kaggle/div_score_cands/cand_scores.csv \
        --pairs outputs/e7/val12_measure.csv \
        --out-csv outputs/e7/rewire/submission.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import polars as pl

# thresholds are OOF-derived (ledger E7-10); NOT tuned on eval-12
CNN_RANK_MIN = 0.95      # parent must be in top 5% of its video by CNN score
STACK_CAP_PER_VIDEO = 2  # adopt/steal ops per video
TWIN_MAX_UM = 5.0        # twin-merge pair distance
SCALE = np.array([1.625, 0.40625, 0.40625])


def rank_norm(col: str) -> pl.Expr:
    return (pl.col(col).rank(method="average") - 1) / (pl.len() - 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in-csv", type=Path, required=True)
    ap.add_argument("--cands", type=Path, required=True)
    ap.add_argument("--scores", type=Path, required=True)
    ap.add_argument("--pairs", type=Path, required=True)
    ap.add_argument("--out-csv", type=Path, required=True)
    ap.add_argument("--cnn-rank-min", type=float, default=CNN_RANK_MIN)
    ap.add_argument("--cap", type=int, default=STACK_CAP_PER_VIDEO)
    ap.add_argument("--twin-max-um", type=float, default=TWIN_MAX_UM)
    ap.add_argument("--no-twin", action="store_true")
    ap.add_argument("--no-steal", action="store_true")
    ap.add_argument("--no-adopt", action="store_true")
    args = ap.parse_args()

    sub = pl.read_csv(args.in_csv)
    cands = pl.read_csv(args.cands).join(
        pl.read_csv(args.scores).select("cand_id", "score"), on="cand_id", how="inner")
    cands = cands.with_columns(rank_norm("score").over("stem").alias("cnn_rank"))
    cnn = {(r["stem"], r["parent_id"]): (r["score"], r["cnn_rank"])
           for r in cands.iter_rows(named=True)}

    pairs = pl.read_csv(args.pairs).join(
        cands.select(pl.col("stem").alias("dataset"), "parent_id", "score", "cnn_rank"),
        on=["dataset", "parent_id"], how="inner")
    pairs = pairs.with_columns(
        (-((pl.col("sister") - 10.6).abs() / 4.0 + (pl.col("d_pc") - 7.1).abs() / 3.0
           + pl.col("mid_over_sister"))).alias("geom"))
    pairs = pairs.with_columns(
        (rank_norm("cnn_rank").over("dataset") * rank_norm("geom").over("dataset")).alias("stack"))

    out_frames = []
    stats = []
    for (stem,), g in sorted(sub.group_by("dataset"), key=lambda kv: kv[0][0]):
        nd = g.filter(pl.col("row_type") == "node")
        ed = g.filter(pl.col("row_type") == "edge")
        pos = {int(r["node_id"]): np.array([r["z"], r["y"], r["x"]], dtype=float) * SCALE
               for r in nd.iter_rows(named=True)}
        tof = {int(r["node_id"]): int(r["t"]) for r in nd.iter_rows(named=True)}
        edges = {(int(r["source_id"]), int(r["target_id"])) for r in ed.iter_rows(named=True)}
        parent_of: dict[int, int] = {}
        children: dict[int, list[int]] = {}
        for s, t in edges:
            parent_of[t] = s
            children.setdefault(s, []).append(t)

        n_twin = n_steal = n_adopt = 0

        # ---- pass 1: twin merge (structural; CNN picks the fork owner)
        if not args.no_twin:
            by_t: dict[int, list[int]] = {}
            for nid, tt in tof.items():
                if len(children.get(nid, [])) == 1:
                    by_t.setdefault(tt, []).append(nid)
            for tt, ids in sorted(by_t.items()):
                ids = sorted(ids)
                used = set()
                for i, p in enumerate(ids):
                    if p in used:
                        continue
                    for q in ids[i + 1:]:
                        if q in used:
                            continue
                        if np.linalg.norm(pos[p] - pos[q]) > args.twin_max_um:
                            continue
                        cp = cnn.get((stem, p), (None, -1.0))[1]
                        cq = cnn.get((stem, q), (None, -1.0))[1]
                        if max(cp, cq) < args.cnn_rank_min:
                            continue
                        win, lose = (p, q) if cp >= cq else (q, p)
                        c_lose = children[lose][0]
                        if c_lose in children.get(win, []):
                            continue
                        edges.discard((lose, c_lose))
                        edges.add((win, c_lose))
                        children[win].append(c_lose)
                        children[lose] = []
                        parent_of[c_lose] = win
                        used.update((p, q))
                        n_twin += 1
                        break

        # ---- pass 2: adopt / steal, stacked-score ranked, capped
        gp = (pairs.filter(pl.col("dataset") == stem)
                   .sort("stack", descending=True))
        ops = 0
        for r in gp.iter_rows(named=True):
            if ops >= args.cap:
                break
            if r["cnn_rank"] < args.cnn_rank_min:
                continue
            p_id, c2 = int(r["parent_id"]), int(r["orphan_id"])
            if len(children.get(p_id, [])) != 1:
                continue          # already forked (maybe by twin pass) or childless
            if c2 in children.get(p_id, []):
                continue
            kind = r["kind"]
            if kind == "adopt":
                if args.no_adopt or c2 in parent_of:
                    continue
                edges.add((p_id, c2))
                children[p_id].append(c2)
                parent_of[c2] = p_id
                n_adopt += 1
                ops += 1
            elif kind == "steal":
                if args.no_steal:
                    continue
                q = parent_of.get(c2)
                if q is None or q == p_id:
                    continue
                edges.discard((q, c2))
                children[q] = [c for c in children.get(q, []) if c != c2]
                edges.add((p_id, c2))
                children[p_id].append(c2)
                parent_of[c2] = p_id
                n_steal += 1
                ops += 1

        stats.append((stem, n_twin, n_adopt, n_steal))
        print(f"{stem}: twin={n_twin} adopt={n_adopt} steal={n_steal}")

        es = sorted(edges)
        edge_rows = pl.DataFrame({
            "id": list(range(len(es))),
            "dataset": [stem] * len(es),
            "row_type": ["edge"] * len(es),
            "node_id": [-1] * len(es),
            "t": [-1] * len(es),
            "z": [-1] * len(es),
            "y": [-1] * len(es),
            "x": [-1] * len(es),
            "source_id": [a for a, _ in es],
            "target_id": [b for _, b in es],
        })
        both = pl.concat([nd, edge_rows.select(nd.columns).cast(nd.schema)], how="vertical")
        out_frames.append(both)

    out = pl.concat(out_frames).drop("id").with_row_index("id")
    out = out.select("id", "dataset", "row_type", "node_id", "t", "z", "y", "x", "source_id", "target_id")
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.write_csv(args.out_csv)
    tw, ad, st = (sum(s[i] for s in stats) for i in (1, 2, 3))
    print(f"TOTAL: twin={tw} adopt={ad} steal={st} -> {args.out_csv}")


if __name__ == "__main__":
    main()
