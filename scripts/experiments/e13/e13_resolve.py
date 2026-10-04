#!/usr/bin/env python
"""E13: local ILP re-solve with candidate expansion + weight sweep (ledger E13).

Phase solve (per stem, resumable):
    uv run python scripts/e13_resolve.py --tag base --stem 44b6_341df25f
    uv run python scripts/e13_resolve.py --tag thr03 --add-thr 0.3 --stem ...
Phase emit (postproc all solved stems -> submission.csv):
    uv run python scripts/e13_resolve.py --tag base --emit
Then score with:
    uv run python scripts/local_eval.py outputs/e13/<tag>/submission.csv --json ...
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import polars as pl
import zarr

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

DUMP_DS = np.array([1.0, 4.0, 4.0])
DUMP_COLS = ["gi", "gj", "prob", "t_src", "z_src", "y_src", "x_src",
             "t_tgt", "z_tgt", "y_tgt", "x_tgt"]
SCALE = np.array([1.625, 0.40625, 0.40625])


def read_raw(geff: Path):
    g = zarr.open(str(geff), mode="r")
    return {
        "ids": np.asarray(g["nodes/ids"]),
        "t": np.asarray(g["nodes/props/t/values"]),
        "z": np.asarray(g["nodes/props/z/values"]),
        "y": np.asarray(g["nodes/props/y/values"]),
        "x": np.asarray(g["nodes/props/x/values"]),
        "e_ids": np.asarray(g["edges/ids"]),
        "prob": np.asarray(g["edges/props/edge_prob/values"]),
        "dist": np.asarray(g["edges/props/edge_dist/values"]),
    }


def solve_stem(stem: str, args) -> None:
    import tracksdata as td
    out_dir = args.out_root / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)
    out_pq = out_dir / f"solved_{stem}.parquet"
    if out_pq.exists():
        print(f"{stem}: already solved, skip")
        return
    r = read_raw(args.raw_dir / f"{stem}.geff")
    n = len(r["ids"])
    arcs = {(int(s), int(t)): (float(p), float(d))
            for (s, t), p, d in zip(r["e_ids"], r["prob"], r["dist"], strict=True)}
    n_base = len(arcs)

    if args.add_thr < 0.5:
        coord2id = {(int(t), int(round(z)), int(round(y)), int(round(x))): int(i)
                    for i, t, z, y, x in zip(r["ids"], r["t"], r["z"], r["y"], r["x"], strict=True)}
        d = pl.read_csv(args.dump_dir / f"{stem}.csv", has_header=False, new_columns=DUMP_COLS)
        d = d.filter(pl.col("prob") >= args.add_thr)
        added = unmapped = 0
        for row in d.iter_rows(named=True):
            ks = (int(row["t_src"]), int(round(row["z_src"] * DUMP_DS[0])),
                  int(round(row["y_src"] * DUMP_DS[1])), int(round(row["x_src"] * DUMP_DS[2])))
            kt = (int(row["t_tgt"]), int(round(row["z_tgt"] * DUMP_DS[0])),
                  int(round(row["y_tgt"] * DUMP_DS[1])), int(round(row["x_tgt"] * DUMP_DS[2])))
            si, ti = coord2id.get(ks), coord2id.get(kt)
            if si is None or ti is None:
                unmapped += 1
                continue
            if (si, ti) in arcs:
                continue
            dz = (np.array(ks[1:]) - np.array(kt[1:])) * SCALE
            arcs[(si, ti)] = (float(row["prob"]), float(np.linalg.norm(dz)))
            added += 1
        print(f"{stem}: arcs base={n_base} added={added} unmapped_rows={unmapped}")

    graph = td.graph.InMemoryGraph()
    for key in ["z", "y", "x"]:
        graph.add_node_attr_key(key, pl.Float64, -999999.0)
    node_ids = graph.bulk_add_nodes([
        {"t": int(t), "z": float(z), "y": float(y), "x": float(x)}
        for t, z, y, x in zip(r["t"], r["z"], r["y"], r["x"], strict=True)])
    old2new = dict(zip(r["ids"].tolist(), node_ids, strict=True))
    new2old = {v: k for k, v in old2new.items()}
    graph.add_edge_attr_key("edge_prob", pl.Float64, 0.0)
    graph.add_edge_attr_key("edge_dist", pl.Float64, 0.0)
    graph.add_edge_attr_key("edge_cost", pl.Float64, 0.0)  # -(prob - edge_off)
    graph.bulk_add_edges([
        {"source_id": old2new[s], "target_id": old2new[t], "edge_prob": p, "edge_dist": dd,
         "edge_cost": -(p - args.edge_off)}
        for (s, t), (p, dd) in arcs.items()])
    t0 = time.time()
    solver = td.solvers.ILPSolver(
        edge_weight=(1.0 * td.EdgeAttr("edge_cost")) if args.edge_off != 0.0
        else (args.ilp_edge * td.EdgeAttr("edge_prob")),
        appearance_weight=args.app, disappearance_weight=args.disapp,
        division_weight=args.div)
    solver.solve(graph)
    ea = graph.edge_attrs(attr_keys=["solution", "edge_prob"])
    K = td.DEFAULT_ATTR_KEYS
    sol = ea.filter(pl.col("solution"))
    rows = [{"source_id": new2old[int(s)], "target_id": new2old[int(t)], "edge_prob": float(p)}
            for s, t, p in zip(sol[K.EDGE_SOURCE], sol[K.EDGE_TARGET], sol["edge_prob"], strict=True)]
    pl.DataFrame(rows).write_parquet(out_pq)
    print(f"{stem}: n={n} arcs={len(arcs)} solution={len(rows)} solve={time.time() - t0:.1f}s")


def emit(args) -> None:
    from biohub.public_postproc.config import build_config, parse_set_overrides
    from biohub.public_postproc.deepcenter import load_deepcenter_veto_detector
    from biohub.public_postproc.pipeline import (
        SubmissionCsvWriter,
        _load_geff_as_dicts,
        filter_output_graph,
    )
    out_dir = args.out_root / args.tag
    cfg = build_config(parse_set_overrides(args.set or []))
    deep = load_deepcenter_veto_detector(cfg)
    stems = sorted(p.stem.replace("solved_", "").replace(".parquet", "")
                   for p in out_dir.glob("solved_*.parquet"))
    csv_path = out_dir / (args.emit_name or "submission.csv")
    with csv_path.open("w", newline="") as handle:
        writer = SubmissionCsvWriter(handle)
        for stem in stems:
            nodes_by_id, _ = _load_geff_as_dicts(args.raw_dir / f"{stem}.geff")
            raw_edges = [dict(r) for r in pl.read_parquet(out_dir / f"solved_{stem}.parquet").iter_rows(named=True)]
            nb, edges, stats = filter_output_graph(cfg, nodes_by_id, raw_edges, dataset=stem,
                                                   deepcenter_bundle=deep)
            writer.write_nodes(stem, nb)
            writer.write_edges(stem, nb, edges)
            print(f"{stem}: nodes {len(nodes_by_id)}->{len(nb)} sol_edges {len(raw_edges)}->{len(edges)}")
    json.dump(vars(args), open(out_dir / "config.json", "w"), default=str)
    print(f"wrote {csv_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--stem")
    ap.add_argument("--emit", action="store_true")
    ap.add_argument("--emit-name", help="alternate output csv name for postproc sweeps")
    ap.add_argument("--set", action="append", metavar="NAME=VALUE",
                    help="postproc BIOHUB_* overrides for emit (repeatable)")
    ap.add_argument("--add-thr", type=float, default=0.5)
    ap.add_argument("--app", type=float, default=0.1)
    ap.add_argument("--disapp", type=float, default=0.1)
    ap.add_argument("--div", type=float, default=1.0)
    ap.add_argument("--ilp-edge", type=float, default=-1.0)
    ap.add_argument("--edge-off", type=float, default=0.0)
    ap.add_argument("--raw-dir", type=Path, default=Path("outputs/e7/val12_raw"))
    ap.add_argument("--dump-dir", type=Path, default=Path("outputs/kaggle/eval_train_raw_v4/pair_probs"))
    ap.add_argument("--out-root", type=Path, default=Path("outputs/e13"))
    args = ap.parse_args()
    if args.emit:
        emit(args)
    else:
        assert args.stem, "--stem required for solve phase"
        solve_stem(args.stem, args)


if __name__ == "__main__":
    main()
