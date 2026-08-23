"""I/O round-trips on synthetic zarr v3 volumes (no competition data required)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from biohub.io import DEFAULT_SCALE, list_videos, open_volume, read_scale


def _write_volume(root: Path, name: str, arr: np.ndarray, scale: tuple[float, float, float] | None) -> Path:
    import zarr

    zpath = root / f"{name}.zarr"
    group = zarr.open_group(zpath, mode="w", zarr_format=3)
    if scale is not None:
        group.attrs["ome"] = {
            "multiscales": [
                {"datasets": [{"path": "0", "coordinateTransformations": [{"type": "scale", "scale": [1.0, *scale]}]}]}
            ]
        }
    z = group.create_array(
        "0",
        shape=arr.shape,
        chunks=(1, *arr.shape[1:]),
        dtype=arr.dtype,
        compressors=zarr.codecs.BloscCodec(cname="zstd", clevel=1, shuffle="bitshuffle"),
    )
    z[:] = arr
    return zpath


@pytest.fixture
def volume(tmp_path: Path) -> tuple[Path, np.ndarray]:
    rng = np.random.default_rng(0)
    arr = rng.integers(0, 4000, size=(3, 4, 8, 8), dtype=np.uint16)
    return _write_volume(tmp_path, "vid_a", arr, (2.0, 0.5, 0.5)), arr


def test_open_volume_reads_shape_dtype_and_scale(volume):
    zpath, arr = volume
    vol = open_volume(zpath)
    assert vol.shape == arr.shape
    assert vol.dtype == np.uint16
    assert vol.scale == (2.0, 0.5, 0.5)
    assert vol.n_t == 3


def test_frame_matches_written_data_exactly(volume):
    zpath, arr = volume
    vol = open_volume(zpath)
    for t in range(arr.shape[0]):
        np.testing.assert_array_equal(vol.frame(t), arr[t])


def test_frame_is_a_writable_copy(volume):
    zpath, arr = volume
    f = open_volume(zpath).frame(0)
    f[0, 0, 0] = 7  # must not raise (np.frombuffer alone would be read-only)
    np.testing.assert_array_equal(open_volume(zpath).frame(0), arr[0])


def test_frame_out_of_range_raises(volume):
    zpath, _ = volume
    with pytest.raises(IndexError):
        open_volume(zpath).frame(3)


def test_read_scale_falls_back_to_default_without_multiscales(tmp_path: Path):
    arr = np.zeros((1, 2, 2, 2), dtype=np.uint16)
    zpath = _write_volume(tmp_path, "noscale", arr, None)
    assert read_scale(zpath) == DEFAULT_SCALE


def test_open_volume_missing_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        open_volume(tmp_path / "nope.zarr")


def test_list_videos_filters_on_geff(tmp_path: Path):
    arr = np.zeros((1, 2, 2, 2), dtype=np.uint16)
    _write_volume(tmp_path, "b", arr, None)
    _write_volume(tmp_path, "a", arr, None)
    (tmp_path / "a.geff").mkdir()
    assert list_videos(tmp_path) == ["a", "b"]
    assert list_videos(tmp_path, require_geff=True) == ["a"]


def test_zarr_json_layout_matches_competition_convention(volume):
    """The competition stores one chunk per timepoint at 0/c/{t}/0/0/0 — our writer must too."""
    zpath, arr = volume
    meta = json.loads((zpath / "0" / "zarr.json").read_text())
    assert meta["chunk_grid"]["configuration"]["chunk_shape"] == [1, *arr.shape[1:]]
    assert (zpath / "0" / "c" / "0" / "0" / "0" / "0").exists()
