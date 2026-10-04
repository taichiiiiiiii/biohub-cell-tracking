"""Exact same-input detector probe; Qwen draft corrected to inspect detections.

One fixed input is a regression check, not evidence of generalization. The
separate frozen-state guard remains required for every optimizer step.
"""
import hashlib

import torch


def capture_probe(api, model, batch, device):
    """Capture actual detector outputs, never substitute annotation coordinates."""
    modes = [(module, module.training) for module in model.modules()]
    try:
        model.eval()
        with torch.no_grad():
            imgs = batch["imgs"].to(device, dtype=torch.float32)
            if imgs.ndim != 5 or tuple(imgs.shape[:2]) != (1, 2):
                raise ValueError("Probe requires batch=1 and window=2")
            if not bool(torch.isfinite(imgs).all()):
                raise ValueError("Nonfinite probe input")
            _, logits = model.encode(imgs)
            if len(logits) != 2:
                raise ValueError("Probe requires two detector frames")
            coords, masks = (batch[key].to(device) for key in ("coords", "masks"))
            result = {}
            for i in range(2):
                if not bool(torch.isfinite(logits[i]).all()):
                    raise ValueError("Nonfinite probe logits")
                detected, _, detected_mask, _ = api.detect_and_match(
                    logits[i], coords[:, i], masks[:, i],
                    image_shape=tuple(batch["image_shape"][0].tolist()),
                    voxel_size=tuple(batch["voxel_size"][0].tolist()),
                    pool_kernel_um=5.0, frame_index=i, window_size=2,
                )
                for name, value in (("logits", logits[i]), ("coords", detected), ("masks", detected_mask)):
                    if not bool(torch.isfinite(value).all()):
                        raise ValueError("Nonfinite detector probe output")
                    result[f"{name}/{i}"] = value.detach().cpu().clone()
            return result
    finally:
        # Preserve mixed train/eval modes, especially a frozen detector.
        for module, mode in modes:
            module.training = mode


def assert_same_probe(a, b):
    if set(a) != set(b) or set(a) != {f"{name}/{i}" for name in ("logits", "coords", "masks") for i in range(2)}:
        raise ValueError("Detector probe keys differ")
    for name in a:
        if (a[name].dtype != b[name].dtype or a[name].shape != b[name].shape
                or not torch.equal(a[name], b[name])):
            raise ValueError(f"Detector probe changed: {name}")


def describe_probe(probe):
    assert_same_probe(probe, probe)
    return {name: {"shape": list(value.shape), "dtype": str(value.dtype),
                   "sha256": hashlib.sha256(value.contiguous().numpy().tobytes()).hexdigest()}
            for name, value in probe.items()}
