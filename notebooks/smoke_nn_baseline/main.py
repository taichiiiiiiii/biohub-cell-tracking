"""Smoke-test kernel: percentile-threshold detector + Hungarian nearest-neighbour linking.

Purpose (Issue #2): verify the Kaggle run path end to end — data mount, zarr
decoding, submission schema, local scoring against the 4 public-test GT geffs
(they are duplicated in train/) — and obtain the first leaderboard value for
the same code submitted twice (leaderboard repeat noise). Scoring is done
locally afterwards: download the output and run scripts/local_eval.py.

It is the official "getting started" recipe (inversion) re-written with the
same conventions as src/biohub; it is NOT meant to be competitive. Runs on CPU
in a few minutes.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path

import blosc2
import numpy as np
from scipy.ndimage import label, uniform_filter
from scipy.optimize import linear_sum_assignment

COMP = Path("/kaggle/input/competitions/biohub-cell-tracking-during-development")
if not COMP.exists():  # alternative mount layout seen on Kaggle
    COMP = Path("/kaggle/input/biohub-cell-tracking-during-development")
TEST_DIR = Path(os.environ.get("BIOHUB_TEST_DIR", COMP / "test"))
OUT = Path("/kaggle/working") if Path("/kaggle/working").exists() else Path(".")

SCALE = np.array([1.625, 0.40625, 0.40625])  # (Z, Y, X) µm / voxel
DOWNSAMPLE = 4
PERCENTILE = 90
MAX_LINK_DISTANCE_UM = 15.0
SUBMISSION_COLUMNS = ["id", "dataset", "row_type", "node_id", "t", "z", "y", "x", "source_id", "target_id"]


def read_frame(zarr_path: Path, t: int, shape: tuple[int, ...], dtype: np.dtype) -> np.ndarray:
    raw = (zarr_path / "0" / "c" / str(t) / "0" / "0" / "0").read_bytes()
    arr = np.frombuffer(blosc2.decompress(raw), dtype=dtype)
    if arr.size != int(np.prod(shape[1:])):
        raise ValueError(f"{zarr_path} t={t}: decoded {arr.size} values, expected {np.prod(shape[1:])}")
    return arr.reshape(shape[1:])


def detect(vol: np.ndarray) -> np.ndarray:
    """Return (N, 3) centroids in full-resolution voxel units."""
    ds = vol[::DOWNSAMPLE, ::DOWNSAMPLE, ::DOWNSAMPLE].astype(np.float32)
    smoothed = uniform_filter(ds, size=3)
    binary = smoothed > np.percentile(smoothed, PERCENTILE)
    labeled, n = label(binary)
    if n == 0:
        return np.zeros((0, 3))
    idx = np.argwhere(labeled > 0)
    lab = labeled[labeled > 0]
    sums = np.zeros((n + 1, 3))
    counts = np.bincount(lab, minlength=n + 1).astype(np.float64)
    for d in range(3):
        sums[:, d] = np.bincount(lab, weights=idx[:, d], minlength=n + 1)
    return (sums[1:] / counts[1:, None]) * DOWNSAMPLE


def link(prev: np.ndarray, curr: np.ndarray) -> list[tuple[int, int]]:
    if len(prev) == 0 or len(curr) == 0:
        return []
    dist = np.linalg.norm((prev * SCALE)[:, None, :] - (curr * SCALE)[None, :, :], axis=2)
    ri, ci = linear_sum_assignment(dist)
    return [(int(r), int(c)) for r, c in zip(ri, ci, strict=True) if dist[r, c] <= MAX_LINK_DISTANCE_UM]


def track_video(zarr_path: Path, writer: csv.writer, row_id: int) -> tuple[int, int, int]:
    name = zarr_path.name[:-5]
    meta = json.loads((zarr_path / "0" / "zarr.json").read_text())
    shape = tuple(int(s) for s in meta["shape"])
    dtype = np.dtype(meta["data_type"])
    next_id = 1
    prev_cent: np.ndarray = np.zeros((0, 3))
    prev_ids: list[int] = []
    n_nodes = n_edges = 0
    for t in range(shape[0]):
        cent = detect(read_frame(zarr_path, t, shape, dtype))
        ids = list(range(next_id, next_id + len(cent)))
        next_id += len(cent)
        for nid, (z, y, x) in zip(ids, cent, strict=True):
            writer.writerow([row_id, name, "node", nid, t, int(round(z)), int(round(y)), int(round(x)), -1, -1])
            row_id += 1
            n_nodes += 1
        for r, c in link(prev_cent, cent):
            writer.writerow([row_id, name, "edge", -1, -1, -1, -1, -1, prev_ids[r], ids[c]])
            row_id += 1
            n_edges += 1
        prev_cent, prev_ids = cent, ids
    return row_id, n_nodes, n_edges


def main() -> None:
    t0 = time.time()
    videos = sorted(TEST_DIR.glob("*.zarr"))
    if not videos:
        sys.exit(f"no .zarr under {TEST_DIR}")
    sub_path = OUT / "submission.csv"
    row_id = 0
    with sub_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(SUBMISSION_COLUMNS)
        for zp in videos:
            row_id, n_nodes, n_edges = track_video(zp, w, row_id)
            print(f"{zp.name}: nodes={n_nodes} edges={n_edges} ({time.time() - t0:.0f}s)", flush=True)
    print(f"wrote {sub_path} ({row_id} rows)")


if __name__ == "__main__":
    main()
