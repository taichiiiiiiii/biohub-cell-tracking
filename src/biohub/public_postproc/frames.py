# Derived from the public Kaggle notebook "Clean Approach + Lightweight Local CV | No Hack"
# by Yusuke Togashi (https://www.kaggle.com/code/yusuketogashi/clean-approach-lightweight-local-cv-no-hack),
# licensed under the Apache License 2.0 (LICENSES/Apache-2.0.txt).
# The ``e23`` mode is also derived from the public Kaggle notebook "biohub-0-923-lb" by evgendvorkin
# (https://www.kaggle.com/code/evgendvorkin/biohub-0-923-lb), Apache License 2.0, via notebooks/pub923_repro/.
# Modified: ported from notebook cells into a torch-free package; see THIRD_PARTY_NOTICES.md.
"""Test-frame access for the image-intensity refinement steps.

The notebook cell re-implemented its own blosc2 chunk reader with a
``zarr``-library fallback; here we reuse ``biohub.io.open_volume(...).frame(t)``
(same one-chunk-per-timepoint blosc2/zstd layout) as instructed. Any read
failure still lands in the caller's ``except Exception`` and degrades to
"keep the unrefined midpoint", matching the notebook's behaviour.

The E23 stack additionally refines *every* node coordinate against the local
intensity centroid before any edge-distance filtering
(:func:`refine_centroids` / :func:`refine_all_centroids`); unlike the
gap-refinement fallback, frame read errors there are raised, never swallowed.
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


def refine_centroids(
    cfg: PostprocConfig,
    vol: np.ndarray,
    coords: list[tuple[float, float, float]],
    stats: dict[str, int],
) -> list[tuple[float, float, float]]:
    """Intensity-centroid refinement of node coordinates within one frame (E23).

    For every ``(z, y, x)``: round to the nearest voxel with Python
    ``int(round())``, take the clipped ``REFINE_CENTROIDS_WIN_Z`` /
    ``REFINE_CENTROIDS_WIN_YX`` window, subtract the
    ``REFINE_CENTROIDS_BASELINE_PERCENTILE`` baseline, and move the point to
    the weighted centroid in absolute voxel coordinates unless the physical
    shift exceeds ``REFINE_CENTROIDS_MAX_SHIFT_UM``. Empty or flat windows
    leave the point unchanged (``centroid_refine_no_signal``).
    ``centroid_refine_moved`` counts only accepted points whose output
    coordinates actually differ from the input, matching the notebook's
    ``total_refined`` semantics (an accepted exact no-op is not "moved", so
    the outcome counters need not partition ``centroid_refine_examined``).
    """
    wz = cfg.REFINE_CENTROIDS_WIN_Z
    wyx = cfg.REFINE_CENTROIDS_WIN_YX
    depth, height, width = vol.shape
    refined_coords: list[tuple[float, float, float]] = []
    for z, y, x in coords:
        stats["centroid_refine_examined"] += 1
        zi, yi, xi = int(round(z)), int(round(y)), int(round(x))
        z0 = max(0, zi - wz)
        z1 = min(depth, zi + wz + 1)
        y0 = max(0, yi - wyx)
        y1 = min(height, yi + wyx + 1)
        x0 = max(0, xi - wyx)
        x1 = min(width, xi + wyx + 1)
        patch = vol[z0:z1, y0:y1, x0:x1].astype(np.float64)
        if patch.size == 0:
            stats["centroid_refine_no_signal"] += 1
            refined_coords.append((z, y, x))
            continue
        baseline = float(np.percentile(patch, cfg.REFINE_CENTROIDS_BASELINE_PERCENTILE))
        weights = np.maximum(patch - baseline, 0.0)
        total = float(weights.sum())
        if total <= 0:
            stats["centroid_refine_no_signal"] += 1
            refined_coords.append((z, y, x))
            continue
        zz = np.arange(z0, z1, dtype=np.float64)[:, None, None]
        yy = np.arange(y0, y1, dtype=np.float64)[None, :, None]
        xx = np.arange(x0, x1, dtype=np.float64)[None, None, :]
        refined = (
            float((weights * zz).sum() / total),
            float((weights * yy).sum() / total),
            float((weights * xx).sum() / total),
        )
        if point_distance_um(refined, (z, y, x)) > cfg.REFINE_CENTROIDS_MAX_SHIFT_UM:
            stats["centroid_refine_rejected_shift"] += 1
            refined_coords.append((z, y, x))
            continue
        if refined != (z, y, x):
            stats["centroid_refine_moved"] += 1
        refined_coords.append(refined)
    return refined_coords


def refine_all_centroids(
    cfg: PostprocConfig,
    nodes_by_id: dict[int, dict[str, object]],
    dataset: str | None,
    frame_cache: dict[int, np.ndarray],
    stats: dict[str, int],
) -> dict[int, dict[str, object]]:
    """Run :func:`refine_centroids` over every node, reading each frame ``t`` once.

    Nodes are grouped by ``t`` in dict iteration order (which is preserved;
    only coordinates are mutated in place). Frames go through
    :func:`read_test_frame` into the shared ``frame_cache`` so later
    gap-close / safe-division / DeepCenter passes reuse them. A frame read
    failure raises ``RuntimeError`` naming the dataset, ``t`` and zarr path,
    chained from the original exception -- refinement never swallows it.
    """
    if dataset is None:
        raise ValueError("refine_all_centroids needs a dataset name to read test frames")

    nodes_by_t: dict[int, list[dict[str, object]]] = {}
    for node in nodes_by_id.values():
        nodes_by_t.setdefault(int(node["t"]), []).append(node)

    zarr_path = cfg.TEST_DIR / f"{dataset}.zarr"
    for t, nodes in nodes_by_t.items():
        try:
            frame = read_test_frame(cfg.TEST_DIR, dataset, t, frame_cache)
        except Exception as exc:
            raise RuntimeError(f"centroid refinement cannot read frame: dataset={dataset} t={t} path={zarr_path}") from exc
        coords = [(float(node["z"]), float(node["y"]), float(node["x"])) for node in nodes]
        for node, point in zip(nodes, refine_centroids(cfg, frame, coords, stats), strict=True):
            node["z"], node["y"], node["x"] = point
    return nodes_by_id
