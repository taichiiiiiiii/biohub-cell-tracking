#!/usr/bin/env python
"""GT statistics for detector/linker design (Issue #5).

Reads every ``.geff`` in ``data/train`` (the 4 videos with local zarr plus the
GT-only ``6bba_c328f2fd``) via ``biohub.io.load_geff_graph`` / tracksdata, and
reports per-video and pooled-per-lineage numbers: node/edge/division counts,
track length distribution, per-edge displacement in micrometres (using the
voxel scale), same-frame nearest-neighbour spacing, non-consecutive-time edge
anomalies, and how close GT nodes sit to the volume border.

    uv run python scripts/issue5_gt_stats.py
    uv run python scripts/issue5_gt_stats.py --out outputs/issue5/gt_stats.md
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from biohub.io import DEFAULT_SCALE, load_geff_graph, open_volume, read_scale  # noqa: E402

# (Z, Y, X) voxels. Confirmed identical for all 4 zarr-backed videos (see report);
# assumed for the GT-only 6bba_c328f2fd, which has no local zarr to read.
VOLUME_SHAPE = (64, 256, 256)
MATCH_RADIUS_UM = 7.0
INTENSITY_FRAMES = (0, 20, 40, 60, 80)  # 5 frames/video, evenly spaced (Part 2)


def lineage_of(stem: str) -> str:
    return stem.split("_", 1)[0]


def edge_displacements(nodes: pl.DataFrame, edges: pl.DataFrame, scale: tuple[float, float, float]) -> pl.DataFrame:
    """Join edges to source/target node coords and compute per-axis + total displacement in µm."""
    sz, sy, sx = scale
    src = nodes.select(["node_id", "t", "z", "y", "x"]).rename(
        {"t": "t_src", "z": "z_src", "y": "y_src", "x": "x_src", "node_id": "source_id"}
    )
    tgt = nodes.select(["node_id", "t", "z", "y", "x"]).rename(
        {"t": "t_tgt", "z": "z_tgt", "y": "y_tgt", "x": "x_tgt", "node_id": "target_id"}
    )
    e = edges.join(src, on="source_id", how="left").join(tgt, on="target_id", how="left")
    e = e.with_columns(
        (pl.col("t_tgt") - pl.col("t_src")).alias("dt"),
        ((pl.col("z_tgt") - pl.col("z_src")) * sz).alias("dz_um"),
        ((pl.col("y_tgt") - pl.col("y_src")) * sy).alias("dy_um"),
        ((pl.col("x_tgt") - pl.col("x_src")) * sx).alias("dx_um"),
    )
    return e.with_columns((pl.col("dz_um") ** 2 + pl.col("dy_um") ** 2 + pl.col("dx_um") ** 2).sqrt().alias("disp_um"))


def nn_distances(nodes: pl.DataFrame, scale: tuple[float, float, float]) -> np.ndarray:
    """Nearest-neighbour distance (µm) between GT nodes within the same frame, pooled over all frames."""
    from scipy.spatial import cKDTree

    sz, sy, sx = scale
    out = []
    for t in nodes["t"].unique().sort().to_list():
        sub = nodes.filter(pl.col("t") == t)
        if sub.height < 2:
            continue
        pts = np.column_stack([sub["z"].to_numpy() * sz, sub["y"].to_numpy() * sy, sub["x"].to_numpy() * sx])
        tree = cKDTree(pts)
        d, _ = tree.query(pts, k=2)
        out.append(d[:, 1])
    return np.concatenate(out) if out else np.array([])


def border_distances(nodes: pl.DataFrame, scale: tuple[float, float, float], shape=VOLUME_SHAPE) -> np.ndarray:
    """Distance (µm) from each node to the nearest volume face, taking the anisotropic scale into account."""
    sz, sy, sx = scale
    zz, yy, xx = shape
    z, y, x = nodes["z"].to_numpy(), nodes["y"].to_numpy(), nodes["x"].to_numpy()
    bz = np.minimum(z, zz - 1 - z) * sz
    by = np.minimum(y, yy - 1 - y) * sy
    bx = np.minimum(x, xx - 1 - x) * sx
    return np.minimum(np.minimum(bz, by), bx)


def pct(arr: np.ndarray, p: float) -> float:
    return float(np.percentile(arr, p)) if len(arr) else float("nan")


def med(arr: np.ndarray) -> float:
    return float(np.median(arr)) if len(arr) else float("nan")


def stats_for_video(stem: str, geff_path: Path, scale: tuple[float, float, float]) -> dict:
    g = load_geff_graph(geff_path)
    n_nodes, n_edges = g.num_nodes(), g.num_edges()
    n_divisions = len(g.dividing_nodes())
    g.assign_tracklet_ids(reset=True)
    nodes = g.node_attrs()
    edges = g.edge_attrs()
    track_len = nodes.group_by("tracklet_id").len()["len"].to_numpy()

    e = edge_displacements(nodes, edges, scale)
    dt_bad = e.filter(pl.col("dt") != 1)
    e1 = e.filter(pl.col("dt") == 1)

    return {
        "stem": stem,
        "lineage": lineage_of(stem),
        "n_nodes": n_nodes,
        "n_edges": n_edges,
        "n_divisions": n_divisions,
        "n_tracks": len(track_len),
        "track_len": track_len,
        "disp": e1["disp_um"].to_numpy(),
        "dz": np.abs(e1["dz_um"].to_numpy()),
        "dy": np.abs(e1["dy_um"].to_numpy()),
        "dx": np.abs(e1["dx_um"].to_numpy()),
        "n_dt_anomaly": dt_bad.height,
        "dt_anomaly_examples": dt_bad.select(["source_id", "target_id", "t_src", "t_tgt"]).head(5).to_dicts(),
        "nn": nn_distances(nodes, scale),
        "border": border_distances(nodes, scale),
        "z_range": (int(nodes["z"].min()), int(nodes["z"].max())),
        "y_range": (int(nodes["y"].min()), int(nodes["y"].max())),
        "x_range": (int(nodes["x"].min()), int(nodes["x"].max())),
        "max_nodes_per_frame": int(nodes.group_by("t").len()["len"].max()),
    }


def fmt_row(label: str, s: dict) -> str:
    tl, nn, disp = s["track_len"], s["nn"], s["disp"]
    border = s["border"]
    border_pct = (border < MATCH_RADIUS_UM).mean() * 100 if len(border) else float("nan")
    return (
        f"| {label} | {s['n_nodes']} | {s['n_edges']} | {s['n_divisions']} | {s['n_tracks']} | "
        f"{med(tl):.0f} | {pct(tl, 90):.0f} | {tl.max() if len(tl) else float('nan'):.0f} | "
        f"{med(disp):.2f} | {pct(disp, 90):.2f} | {pct(disp, 99):.2f} | "
        f"{disp.max() if len(disp) else float('nan'):.2f} | "
        f"{med(s['dz']):.2f}/{med(s['dy']):.2f}/{med(s['dx']):.2f} | "
        f"{med(nn):.2f} | {pct(nn, 10):.2f} | {nn.min() if len(nn) else float('nan'):.2f} | "
        f"{s['n_dt_anomaly']} | {border.min() if len(border) else float('nan'):.2f} | {border_pct:.1f}% |"
    )


HEADER = (
    "| video | nodes | edges | divisions | tracks | trklen med | trklen p90 | trklen max "
    "| disp med (µm) | disp p90 | disp p99 | disp max | dz/dy/dx med (µm) "
    "| NN med (µm) | NN p10 | NN min | dt!=1 edges | border min (µm) | %nodes <7µm border |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"
)


def pool(rows: list[dict]) -> dict:
    return {
        "n_nodes": sum(r["n_nodes"] for r in rows),
        "n_edges": sum(r["n_edges"] for r in rows),
        "n_divisions": sum(r["n_divisions"] for r in rows),
        "n_tracks": sum(r["n_tracks"] for r in rows),
        "track_len": np.concatenate([r["track_len"] for r in rows]),
        "disp": np.concatenate([r["disp"] for r in rows]),
        "dz": np.concatenate([r["dz"] for r in rows]),
        "dy": np.concatenate([r["dy"] for r in rows]),
        "dx": np.concatenate([r["dx"] for r in rows]),
        "nn": np.concatenate([r["nn"] for r in rows]),
        "border": np.concatenate([r["border"] for r in rows]),
        "n_dt_anomaly": sum(r["n_dt_anomaly"] for r in rows),
    }


def percentile_rank(frame: np.ndarray, values: np.ndarray) -> np.ndarray:
    """% of frame voxels <= each value (100 = brightest voxel in the frame)."""
    sorted_vals = np.sort(frame.ravel())
    return np.searchsorted(sorted_vals, values, side="right") / sorted_vals.size * 100.0


def local_max(frame: np.ndarray, z: np.ndarray, y: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Max intensity in the 3x3x3 (1-voxel) neighbourhood around each (z,y,x), clipped to bounds."""
    zz, yy, xx = frame.shape
    out = np.empty(len(z), dtype=frame.dtype)
    for i in range(len(z)):
        z0, z1 = max(0, z[i] - 1), min(zz, z[i] + 2)
        y0, y1 = max(0, y[i] - 1), min(yy, y[i] + 2)
        x0, x1 = max(0, x[i] - 1), min(xx, x[i] + 2)
        out[i] = frame[z0:z1, y0:y1, x0:x1].max()
    return out


def intensity_for_video(stem: str, zarr_path: Path, nodes: pl.DataFrame, frame_ts) -> list[dict]:
    """Part 2: GT-node raw intensity vs. frame background, for a handful of frames (one decoded at a time)."""
    vol = open_volume(zarr_path)
    out = []
    for t in frame_ts:
        sub = nodes.filter(pl.col("t") == t)
        if sub.height == 0:
            continue
        frame = vol.frame(t)
        z, y, x = sub["z"].to_numpy(), sub["y"].to_numpy(), sub["x"].to_numpy()
        vals = frame[z, y, x]
        nmax = local_max(frame, z, y, x)
        out.append(
            {
                "stem": stem,
                "t": t,
                "n": sub.height,
                "node_val": vals,
                "node_rank": percentile_rank(frame, vals),
                "nmax_val": nmax,
                "nmax_rank": percentile_rank(frame, nmax),
                "bg_pcts": {p: float(np.percentile(frame, p)) for p in (50, 90, 95, 99)},
            }
        )
    return out


def intensity_report(rows: list[dict]) -> list[str]:
    lines = [
        "\n## Part 2: GT-node intensity vs. frame background\n",
        f"{INTENSITY_FRAMES} frames sampled per video; raw uint16 intensity at each GT node voxel, "
        "the max in its 1-voxel (3x3x3) neighbourhood, and each value's percentile rank within that "
        "frame's full intensity histogram.\n",
        "| video | n samples | node val med | node rank med % | 1-vox-max val med | 1-vox-max rank med % "
        "| frame p50 | p90 | p95 | p99 (median over sampled frames) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for stem in sorted({r["stem"] for r in rows}):
        vrows = [r for r in rows if r["stem"] == stem]
        node_val = np.concatenate([r["node_val"] for r in vrows])
        node_rank = np.concatenate([r["node_rank"] for r in vrows])
        nmax_val = np.concatenate([r["nmax_val"] for r in vrows])
        nmax_rank = np.concatenate([r["nmax_rank"] for r in vrows])
        bg = {p: med(np.array([r["bg_pcts"][p] for r in vrows])) for p in (50, 90, 95, 99)}
        lines.append(
            f"| {stem} | {len(node_val)} | {med(node_val):.0f} | {med(node_rank):.1f} | "
            f"{med(nmax_val):.0f} | {med(nmax_rank):.1f} | {bg[50]:.0f} | {bg[90]:.0f} | {bg[95]:.0f} | {bg[99]:.0f} |"
        )
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train-dir", type=Path, default=ROOT / "data" / "train")
    ap.add_argument("--zarr-dir", type=Path, default=ROOT / "data" / "test")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs" / "issue5" / "gt_stats.md")
    args = ap.parse_args()

    stems = sorted(p.name[: -len(".geff")] for p in args.train_dir.glob("*.geff"))
    rows = []
    intensity_rows: list[dict] = []
    for stem in stems:
        zarr_path = args.zarr_dir / f"{stem}.zarr"
        has_zarr = zarr_path.exists()
        scale = read_scale(zarr_path) if has_zarr else DEFAULT_SCALE
        r = stats_for_video(stem, args.train_dir / f"{stem}.geff", scale)
        rows.append(r)
        print(f"{stem}: scale={scale} nodes={r['n_nodes']} edges={r['n_edges']}")
        if has_zarr:
            g = load_geff_graph(args.train_dir / f"{stem}.geff")
            intensity_rows += intensity_for_video(stem, zarr_path, g.node_attrs(), INTENSITY_FRAMES)

    lines = [
        "# GT statistics (Issue #5)\n",
        f"5 GT graphs from `{args.train_dir}` (4 have a matching zarr in `{args.zarr_dir}`; "
        "`6bba_c328f2fd` is GT-only and its scale/volume shape are assumed identical to the other "
        "4 videos, confirmed equal amongst themselves). Scale (Z,Y,X) = "
        f"{DEFAULT_SCALE} µm/voxel. Matching radius = {MATCH_RADIUS_UM} µm.\n",
        "## Per video\n",
        HEADER,
    ]
    for r in rows:
        lines.append(fmt_row(r["stem"], r))

    lines += ["\n## Pooled per lineage\n", HEADER]
    for lineage in ("44b6", "6bba"):
        sub = [r for r in rows if r["lineage"] == lineage]
        p = pool(sub)
        lines.append(fmt_row(f"{lineage} (n={len(sub)} videos)", p))
    lines.append(fmt_row("ALL (pooled)", pool(rows)))

    lines.append("\n## Coordinate ranges (voxel, observed in GT) and dt!=1 anomaly examples\n")
    lines.append(
        "| video | z range | y range | x range | max GT nodes/frame | dt!=1 examples "
        "(source_id,target_id,t_src,t_tgt) |"
    )
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        pairs = (f"({d['source_id']},{d['target_id']},{d['t_src']},{d['t_tgt']})" for d in r["dt_anomaly_examples"])
        ex = "; ".join(pairs)
        lines.append(
            f"| {r['stem']} | {r['z_range']} | {r['y_range']} | {r['x_range']} | "
            f"{r['max_nodes_per_frame']} | {ex or 'none'} |"
        )
    lines.append(
        "\nNote: `44b6_0113de3b` has **at most 1 GT node per frame** (single-cell trace GT), so its "
        "within-frame nearest-neighbour columns are `nan` (no pair exists within any frame) — this is "
        "real GT sparsity, not a bug. `border min (µm) = 0.00` for both `44b6` videos means at least one "
        "GT node sits on the outermost z-slice (z=63, `Z-1-z=0`)."
    )
    lines += intensity_report(intensity_rows)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
