#!/usr/bin/env python
"""Detector-recall upper bound for the 4 GT-backed videos (Issue #5, Part 3).

Simple 3D blob detector per frame: anisotropic Gaussian smoothing (sigma from
an assumed cell radius, 3/4/5 um "small/medium/large" variants) then local
maxima via ``scipy.ndimage.maximum_filter`` with a ~2.5 um anisotropic
footprint, thresholded at intensity percentiles 90/95/97/98/99 of the
smoothed frame. For each (video, sigma, threshold) we report detections/frame,
GT recall within the 7 um matching radius, and the median GT->nearest
detection distance -- an upper bound on what any detector+threshold could do,
since it never has to disambiguate track identity.

One frame is decoded at a time (never a whole video). To keep total runtime
inside the local RAM/time budget only every ``--stride``-th frame is used by
default (2 -> 50/100 frames per video); this is the "reduce frames" fallback
from the task brief, applied because a full-precision (truncate=4) 100-frame
x 4-video x 3-sigma sweep measured at ~25 minutes locally.

Run one video (or a few) per invocation and re-run to accumulate more videos
into the same CSV -- existing rows for the requested videos are replaced,
others are kept:

    uv run python scripts/issue5_detector_recall.py --videos 44b6_0113de3b
    uv run python scripts/issue5_detector_recall.py --videos 44b6_0b24845f 6bba_05b6850b
    uv run python scripts/issue5_detector_recall.py --videos 6bba_05db0fb1
    uv run python scripts/issue5_detector_recall.py --summarize-only   # just print/re-derive the summary
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import polars as pl
from scipy import ndimage
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from biohub.io import load_geff_graph, open_volume  # noqa: E402

SIGMA_UM = {"small": 3.0, "medium": 4.0, "large": 5.0}  # assumed cell radius -> smoothing sigma
FOOTPRINT_UM = 2.5  # local-maxima minimum-separation footprint (~2-3 um)
GAUSSIAN_TRUNCATE = 1.5  # truncated kernel (~86% of 1D mass) traded for ~2x speed; see module docstring
THRESHOLDS_PCT = (90, 95, 97, 98, 99)
MATCH_RADIUS_UM = 7.0
CSV_COLUMNS = [
    "video",
    "lineage",
    "sigma_name",
    "sigma_um",
    "threshold_pct",
    "avg_detections_per_frame",
    "recall_at_7um",
    "median_dist_um",
    "n_frames_evaluated",
    "n_gt_evaluated",
    "frame_stride",
]


def lineage_of(stem: str) -> str:
    return stem.split("_", 1)[0]


def voxel_shape(size_um: float, scale: tuple[float, float, float]) -> tuple[int, int, int]:
    shape = tuple(max(1, round(size_um / s)) for s in scale)
    return tuple(v if v % 2 == 1 else v + 1 for v in shape)  # odd side lengths for a centred footprint


def detect_frame(frame_f32: np.ndarray, sigma_vox, footprint) -> tuple[np.ndarray, np.ndarray]:
    """Smoothed frame + boolean local-maxima mask (before intensity thresholding)."""
    smoothed = ndimage.gaussian_filter(frame_f32, sigma=sigma_vox, truncate=GAUSSIAN_TRUNCATE)
    local_max = ndimage.maximum_filter(smoothed, size=footprint)
    return smoothed, smoothed == local_max


def eval_video(
    stem: str, zarr_path: Path, geff_path: Path, frame_ts, sigma_names, thresholds, stride: int
) -> list[dict]:
    vol = open_volume(zarr_path)
    scale = vol.scale
    nodes = load_geff_graph(geff_path).node_attrs()
    footprint = voxel_shape(FOOTPRINT_UM, scale)

    acc = {(sn, th): {"n_det": [], "dist": [], "matched": 0, "total_gt": 0} for sn in sigma_names for th in thresholds}
    for t in frame_ts:
        sub = nodes.filter(pl.col("t") == t)
        n_gt = sub.height
        gtpts = None
        if n_gt:
            gtpts = np.column_stack([sub[c].to_numpy() * s for c, s in zip(("z", "y", "x"), scale, strict=True)])
        frame = vol.frame(t).astype(np.float32)
        for sname in sigma_names:
            sigma_vox = tuple(SIGMA_UM[sname] / s for s in scale)
            smoothed, peak_mask = detect_frame(frame, sigma_vox, footprint)
            for thr_pct in thresholds:
                cutoff = np.percentile(smoothed, thr_pct)
                zz, yy, xx = np.nonzero(peak_mask & (smoothed > cutoff))
                key = (sname, thr_pct)
                acc[key]["n_det"].append(len(zz))
                if n_gt == 0:
                    continue
                acc[key]["total_gt"] += n_gt
                if len(zz) == 0:
                    continue
                detpts = np.column_stack([zz * scale[0], yy * scale[1], xx * scale[2]])
                d, _ = cKDTree(detpts).query(gtpts)
                acc[key]["dist"].extend(d.tolist())
                acc[key]["matched"] += int(np.sum(d <= MATCH_RADIUS_UM))

    rows = []
    for (sname, thr_pct), a in acc.items():
        n_det, dist = np.array(a["n_det"]), np.array(a["dist"])
        recall = a["matched"] / a["total_gt"] if a["total_gt"] else float("nan")
        rows.append(
            {
                "video": stem,
                "lineage": lineage_of(stem),
                "sigma_name": sname,
                "sigma_um": SIGMA_UM[sname],
                "threshold_pct": thr_pct,
                "avg_detections_per_frame": float(n_det.mean()) if len(n_det) else float("nan"),
                "recall_at_7um": recall,
                "median_dist_um": float(np.median(dist)) if len(dist) else float("nan"),
                "n_frames_evaluated": len(frame_ts),
                "n_gt_evaluated": a["total_gt"],
                "frame_stride": stride,
            }
        )
    return rows


def merge_csv(out_path: Path, new_rows: list[dict], videos_updated: set[str]) -> pl.DataFrame:
    new_df = pl.DataFrame(new_rows, schema=CSV_COLUMNS)
    if out_path.exists():
        old = pl.read_csv(out_path).filter(~pl.col("video").is_in(list(videos_updated)))
        new_df = pl.concat([old, new_df], how="vertical")
    new_df = new_df.sort(["video", "sigma_name", "threshold_pct"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    new_df.write_csv(out_path)
    return new_df


def summarize(df: pl.DataFrame) -> str:
    lines = ["\n=== Pooled per lineage (micro-avg recall, weighted by n_gt_evaluated) ==="]
    pooled = (
        df.group_by(["lineage", "sigma_name", "sigma_um", "threshold_pct"])
        .agg(
            (pl.col("recall_at_7um") * pl.col("n_gt_evaluated")).sum() / pl.col("n_gt_evaluated").sum(),
            pl.col("avg_detections_per_frame").mean().alias("avg_detections_per_frame"),
            pl.col("median_dist_um").mean().alias("median_dist_um_mean_of_videos"),
            pl.col("video").n_unique().alias("n_videos"),
        )
        .rename({"recall_at_7um": "recall_at_7um"})
        .sort(["lineage", "sigma_name", "threshold_pct"])
    )
    lines.append(str(pooled))

    lines.append("\n=== Best setting per lineage: recall >= 0.95 at smallest avg detections/frame ===")
    for lineage in pooled["lineage"].unique().sort().to_list():
        cand = pooled.filter((pl.col("lineage") == lineage) & (pl.col("recall_at_7um") >= 0.95))
        lineage_rows = pooled.filter(pl.col("lineage") == lineage)
        if cand.height == 0:
            best_recall = lineage_rows.sort("recall_at_7um", descending=True).head(1)
            n_videos = lineage_rows["n_videos"].max()
            lines.append(
                f"{lineage}: NO setting reaches recall>=0.95 (n_videos={n_videos}). "
                f"Best: {best_recall.to_dicts()}"
            )
        else:
            best = cand.sort("avg_detections_per_frame").head(1)
            lines.append(f"{lineage}: {best.to_dicts()[0]}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zarr-dir", type=Path, default=ROOT / "data" / "test")
    ap.add_argument("--train-dir", type=Path, default=ROOT / "data" / "train")
    ap.add_argument("--videos", nargs="*", default=None, help="subset of video stems (default: all with zarr+geff)")
    ap.add_argument("--stride", type=int, default=2, help="use every Nth frame (default 2 -> 50/100 frames)")
    ap.add_argument("--sigmas", nargs="*", default=list(SIGMA_UM), choices=list(SIGMA_UM))
    ap.add_argument("--thresholds", nargs="*", type=int, default=list(THRESHOLDS_PCT))
    ap.add_argument("--out", type=Path, default=ROOT / "outputs" / "issue5" / "detector_recall.csv")
    ap.add_argument("--summarize-only", action="store_true", help="skip detection, just print summary of --out")
    args = ap.parse_args()

    if args.summarize_only:
        print(summarize(pl.read_csv(args.out)))
        return

    all_stems = sorted(p.name[: -len(".zarr")] for p in args.zarr_dir.glob("*.zarr"))
    stems = args.videos if args.videos else [s for s in all_stems if (args.train_dir / f"{s}.geff").exists()]

    all_rows = []
    for stem in stems:
        geff_path = args.train_dir / f"{stem}.geff"
        if not geff_path.exists():
            print(f"skip {stem}: no GT geff in {args.train_dir}")
            continue
        frame_ts = list(range(0, 100, args.stride))
        zarr_path = args.zarr_dir / f"{stem}.zarr"
        rows = eval_video(stem, zarr_path, geff_path, frame_ts, args.sigmas, args.thresholds, args.stride)
        all_rows += rows
        print(f"{stem}: {len(frame_ts)} frames x {len(args.sigmas)} sigmas x {len(args.thresholds)} thresholds done")

    df = merge_csv(args.out, all_rows, set(stems))
    print(f"\nwrote {args.out} ({df.height} rows, videos present: {sorted(df['video'].unique().to_list())})")
    print("\n=== Per video / sigma / threshold ===")
    print(df)
    print(summarize(df))


if __name__ == "__main__":
    main()
