"""Light-weight readers for the competition data (no torch, no dask).

Image volume : ``<name>.zarr`` (zarr v3), array ``0`` of shape (T, Z, Y, X),
               uint16, one blosc2/zstd chunk per timepoint at ``0/c/{t}/0/0/0``.
Ground truth : ``<name>.geff`` (tracksdata graph). Nodes carry t, z, y, x in
               *voxel* units; edges are (source_id, target_id) with t+1 targets.
Submission   : CSV with columns id, dataset, row_type, node_id, t, z, y, x,
               source_id, target_id (node rows use -1 for source/target,
               edge rows use -1 for node_id/t/z/y/x).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import blosc2
import numpy as np

# (Z, Y, X) micrometres per voxel; same as the official DEFAULT_SCALE.
DEFAULT_SCALE: tuple[float, float, float] = (1.625, 0.40625, 0.40625)

SUBMISSION_COLUMNS = ("dataset", "row_type", "node_id", "t", "z", "y", "x", "source_id", "target_id")


@dataclass(frozen=True)
class ZarrVolume:
    """Metadata handle for one video. Frames are decoded on demand."""

    path: Path
    shape: tuple[int, int, int, int]  # (T, Z, Y, X)
    dtype: np.dtype
    scale: tuple[float, float, float]

    @property
    def n_t(self) -> int:
        return self.shape[0]

    def frame(self, t: int) -> np.ndarray:
        """Decode timepoint ``t`` -> (Z, Y, X) array (new, writable copy)."""
        if not 0 <= t < self.n_t:
            raise IndexError(f"t={t} out of range [0, {self.n_t})")
        chunk = self.path / "0" / "c" / str(t) / "0" / "0" / "0"
        raw = blosc2.decompress(chunk.read_bytes())
        arr = np.frombuffer(raw, dtype=self.dtype)
        expected = int(np.prod(self.shape[1:]))
        if arr.size != expected:
            raise ValueError(f"{chunk}: decoded {arr.size} values, expected {expected}")
        return arr.reshape(self.shape[1:]).copy()


def read_scale(zarr_path: Path) -> tuple[float, float, float]:
    """(Z, Y, X) voxel scale from the OME-NGFF multiscales attrs, else DEFAULT_SCALE."""
    root_meta = zarr_path / "zarr.json"
    if not root_meta.exists():
        return DEFAULT_SCALE
    attrs = json.loads(root_meta.read_text()).get("attributes", {})
    # OME-NGFF 0.5 nests under "ome"; older layouts put multiscales at the top.
    attrs = attrs.get("ome", attrs)
    if "multiscales" not in attrs:
        return DEFAULT_SCALE
    transform = attrs["multiscales"][0]["datasets"][0]["coordinateTransformations"][0]
    if transform.get("type") != "scale":
        raise ValueError(f"{root_meta}: first transform is not 'scale': {transform}")
    z, y, x = (float(v) for v in transform["scale"][-3:])
    return (z, y, x)


def open_volume(zarr_path: Path | str) -> ZarrVolume:
    """Open ``<name>.zarr`` (metadata only; no image bytes are read)."""
    zarr_path = Path(zarr_path)
    meta_path = zarr_path / "0" / "zarr.json"
    if not meta_path.exists():
        raise FileNotFoundError(meta_path)
    meta = json.loads(meta_path.read_text())
    shape = tuple(int(s) for s in meta["shape"])
    if len(shape) != 4:
        raise ValueError(f"{meta_path}: expected 4-D (T,Z,Y,X) shape, got {shape}")
    return ZarrVolume(
        path=zarr_path,
        shape=shape,  # type: ignore[arg-type]
        dtype=np.dtype(meta["data_type"]),
        scale=read_scale(zarr_path),
    )


def list_videos(split_dir: Path | str, require_geff: bool = False) -> list[str]:
    """Video stems under ``split_dir`` (sorted). With ``require_geff`` keep only GT-paired ones."""
    split_dir = Path(split_dir)
    stems = sorted(p.name[:-5] for p in split_dir.glob("*.zarr"))
    if require_geff:
        stems = [s for s in stems if (split_dir / f"{s}.geff").exists()]
    return stems


def load_geff_graph(geff_path: Path | str):
    """Load a ``.geff`` as a tracksdata graph (import deferred: tracksdata is slow to import)."""
    import tracksdata as td

    result = td.graph.IndexedRXGraph.from_geff(Path(geff_path))
    return result[0] if isinstance(result, tuple) else result


def estimated_number_of_nodes(geff_path: Path | str) -> float:
    """``estimated_number_of_nodes`` from the GEFF metadata extras (NaN if absent)."""
    from geff import GeffMetadata

    try:
        meta = GeffMetadata.read(Path(geff_path))
    except Exception:
        return float("nan")
    val = (meta.extra or {}).get("estimated_number_of_nodes")
    return float(val) if val is not None else float("nan")
