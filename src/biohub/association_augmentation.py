"""Qwen-authored XY augmentation, integrated with the official coordinate grid.

No image interpolation, node reordering, temporal reversal, or mutable RNG.
Continuous border coordinates are reflected without clipping, like official
flip_augment; sparse GT may extend beyond the last downsampled voxel center.
"""
import hashlib
import json

import torch


def flip_bits(seed, epoch, example_id):
    if type(seed) is not int or seed < 0 or type(epoch) is not int or epoch < 1:
        raise ValueError("Invalid augmentation seed/epoch")
    if not isinstance(example_id, str) or not example_id:
        raise ValueError("Invalid example identity")
    payload = json.dumps(["biohub-xyflip-v1", seed, epoch, example_id],
                         separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    byte = hashlib.sha256(payload).digest()[0]
    return bool(byte & 1), bool(byte & 2)


def flip_xy(batch, *, flip_y, flip_x):
    if type(flip_y) is not bool or type(flip_x) is not bool:
        raise ValueError("Flip flags must be bool")
    imgs, coords, masks, targets = (batch[key] for key in ("imgs", "coords", "masks", "targets"))
    if not all(isinstance(value, torch.Tensor) for value in (imgs, coords, masks, targets)):
        raise ValueError("Expected tensor batch")
    if imgs.ndim != 5 or imgs.shape[:2] != (1, 2) or any(s <= 0 for s in imgs.shape[2:]):
        raise ValueError("Expected batch1/window2 image")
    if coords.ndim != 4 or coords.shape[:2] != (1, 2) or coords.shape[-1] != 3:
        raise ValueError("Invalid coordinates")
    n = coords.shape[2]
    if masks.dtype != torch.bool or masks.shape != (1, 2, n) or targets.shape != (1, 1, n, n):
        raise ValueError("Invalid masks/targets")
    if not coords.is_floating_point() or not bool(torch.isfinite(coords).all()):
        raise ValueError("Coordinates must be finite floating point")
    result = dict(batch)
    dims = ([3] if flip_y else []) + ([4] if flip_x else [])
    result["imgs"] = imgs.flip(dims) if dims else imgs
    result["coords"] = coords.clone()
    for axis, enabled in ((1, flip_y), (2, flip_x)):
        if enabled:
            result["coords"][..., axis] = torch.where(
                masks, imgs.shape[axis + 2] - 1 - coords[..., axis], coords[..., axis])
    return result


def augmentation_config():
    return {"name": "xy_flip", "axes": ["y", "x"], "axis_probability": 0.5,
            "rule": "SHA256(compact_ascii_JSON([biohub-xyflip-v1,seed,epoch,example_id])) byte0 bits0,1",
            "window_shared": True, "interpolation": False, "validation": False,
            "coordinates": "shape_minus_1_minus_coordinate_no_clipping"}


def augment_batches(items, *, seed, epoch):
    for stem, example_id, batch in items:
        flip_y, flip_x = flip_bits(seed, epoch, example_id)
        yield stem, example_id, flip_xy(batch, flip_y=flip_y, flip_x=flip_x)
