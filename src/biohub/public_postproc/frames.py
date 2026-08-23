"""Test-frame access for the gap-refinement synthetic-midpoint step.

The notebook cell re-implemented its own blosc2 chunk reader with a
``zarr``-library fallback; here we reuse ``biohub.io.open_volume(...).frame(t)``
(same one-chunk-per-timepoint blosc2/zstd layout) as instructed. Any read
failure still lands in the caller's ``except Exception`` and degrades to
"keep the unrefined midpoint", matching the notebook's behaviour.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from biohub.io import open_volume
from biohub.public_postproc.config import PostprocConfig
from biohub.public_postproc.geometry import point_distance_um


def read_test_frame(test_dir: Path, dataset: str, t: int, frame_cache: dict[int, np.ndarray]) -> np.ndarray:
    if t in frame_cache:
        return frame_cache[t]
    frame = open_volume(test_dir / f"{dataset}.zarr").frame(t)
    frame_cache[t] = frame
    return frame


def refine_synthetic_midpoint(
    cfg: PostprocConfig,
    dataset: str | None,
    t: int,
    midpoint: tuple[float, float, float],
    frame_cache: dict[int, np.ndarray],
    stats: dict[str, int],
) -> tuple[float, float, float]:
    if not cfg.GAP_REFINE_SYNTHETIC or dataset is None:
        return midpoint
    try:
        frame = read_test_frame(cfg.TEST_DIR, dataset, t, frame_cache)
        z, y, x = (int(round(v)) for v in midpoint)
        z0 = max(0, z - cfg.GAP_REFINE_WIN_Z)
        z1 = min(frame.shape[0], z + cfg.GAP_REFINE_WIN_Z + 1)
        y0 = max(0, y - cfg.GAP_REFINE_WIN_YX)
        y1 = min(frame.shape[1], y + cfg.GAP_REFINE_WIN_YX + 1)
        x0 = max(0, x - cfg.GAP_REFINE_WIN_YX)
        x1 = min(frame.shape[2], x + cfg.GAP_REFINE_WIN_YX + 1)
        patch = frame[z0:z1, y0:y1, x0:x1].astype(np.float64)
        if patch.size == 0:
            stats["gap_refine_failed"] += 1
            return midpoint
        baseline = float(np.percentile(patch, 20.0))
        weights = np.maximum(patch - baseline, 0.0)
        total = float(weights.sum())
        if total <= 0:
            stats["gap_refine_failed"] += 1
            return midpoint
        zz = np.arange(z0, z1, dtype=np.float64)[:, None, None]
        yy = np.arange(y0, y1, dtype=np.float64)[None, :, None]
        xx = np.arange(x0, x1, dtype=np.float64)[None, None, :]
        refined = (
            float((weights * zz).sum() / total),
            float((weights * yy).sum() / total),
            float((weights * xx).sum() / total),
        )
        if point_distance_um(refined, midpoint) > cfg.GAP_REFINE_MAX_SHIFT_UM:
            stats["gap_refine_rejected_shift"] += 1
            return midpoint
        stats["gap_refined_synthetic"] += 1
        return refined
    except Exception:
        stats["gap_refine_failed"] += 1
        return midpoint
