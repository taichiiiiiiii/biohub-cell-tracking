"""DeepCenter add-only repair gate, ported verbatim from the notebook cell.

Disabled by the ``biohub_132_clean_short_track_rescue_lightcv_nohack`` preset
(``BIOHUB_USE_DEEPCENTER_VETO=0``) that produced ``outputs/kaggle/base1_v1``,
so none of this needs to fire for the port to reproduce that submission.
Kept so the code path -- and any future preset that re-enables it -- still
works; ``torch`` is optional and only imported when the gate is actually
requested (it is not a project dependency).
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import BinaryIO

import numpy as np

from biohub.public_postproc.config import PostprocConfig
from biohub.public_postproc.frames import read_test_frame
from biohub.public_postproc.geometry import node_point  # noqa: F401  (re-exported for callers)

try:
    import torch
except Exception:  # pragma: no cover - torch is not a project dependency
    torch = None


STRICT_DEEPCENTER_CHECKPOINT_SHA256 = "8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0"
STRICT_DEEPCENTER_MANIFEST_SHA256 = "1eedc1af72b10c464c6995013075310510b6f6e634450ff2bc170c67b89ce911"
STRICT_DEEPCENTER_EPOCH = 2
STRICT_DEEPCENTER_MANIFEST_MODEL_CONFIG = MappingProxyType(
    {
        "base_channels": 24,
        "batch_size": 8,
        "bg_quantile": 0.4,
        "brightness_jitter": 0.0,
        "epochs": 1000,
        "frames_per_movie": 0,
        "gauss_sigma": 1.0,
        "grad_clip_norm": None,
        "learning_rate": 0.001,
        "movie_limit": None,
        "norm_clip_hi": 6.0,
        "norm_clip_lo": -0.5,
        "norm_hi_pct": 99.5,
        "norm_lo_pct": 50.0,
        "num_workers": 4,
        "pool_factor": 4,
        "pos_thresh": 0.05,
        "random_flip": True,
        "seed": 2026,
        "val_fraction": 0.1,
        "w_bg": 1.0,
        "w_ignore": 0.05,
        "w_pos": 12.0,
        "weight_decay": 0.0,
    }
)
STRICT_DEEPCENTER_CHECKPOINT_MODEL_CONFIG = MappingProxyType(
    {
        **STRICT_DEEPCENTER_MANIFEST_MODEL_CONFIG,
        "epochs": 50,
    }
)
STRICT_DEEPCENTER_CONFIG_DISCREPANCY = MappingProxyType(
    {
        "field": "epochs",
        "manifest": 1000,
        "checkpoint": 50,
    }
)


def _strict_stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _strict_stat_plain(value: os.stat_result) -> dict[str, int]:
    return {
        "device": value.st_dev,
        "inode": value.st_ino,
        "mode": value.st_mode,
        "size": value.st_size,
        "mtime_ns": value.st_mtime_ns,
        "ctime_ns": value.st_ctime_ns,
    }


def _strict_config_matches(actual: object, expected: dict[str, object]) -> bool:
    if type(actual) is not dict or set(actual) != set(expected):
        return False
    for key, expected_value in expected.items():
        actual_value = actual[key]
        if type(actual_value) is not type(expected_value):
            return False
        if type(expected_value) is float:
            if not np.isfinite(actual_value) or actual_value.hex() != expected_value.hex():
                return False
        elif actual_value != expected_value:
            return False
    return True


def _strict_read_one_file[T](
    path: Path,
    expected_sha256: str,
    reader: Callable[[BinaryIO], T],
) -> tuple[T, dict[str, object]]:
    """Hash and parse one regular, nonsymlink file through one retained FD."""
    if type(path) is not type(Path()):
        raise TypeError("strict DeepCenter paths must be exact pathlib.Path instances")
    if type(expected_sha256) is not str or len(expected_sha256) != 64:
        raise ValueError("expected SHA-256 must be 64 lowercase hexadecimal characters")
    try:
        bytes.fromhex(expected_sha256)
    except ValueError as exc:
        raise ValueError("expected SHA-256 must be hexadecimal") from exc
    if expected_sha256 != expected_sha256.lower():
        raise ValueError("expected SHA-256 must be lowercase")

    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("strict DeepCenter loading requires O_NOFOLLOW support")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"strict DeepCenter input is not a regular file: {path.name}")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            digest = hashlib.sha256()
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            after_hash = os.fstat(fd)
            if _strict_stat_identity(after_hash) != _strict_stat_identity(before):
                raise RuntimeError(f"strict DeepCenter input changed while hashing: {path.name}")
            actual_sha256 = digest.hexdigest()
            if actual_sha256 != expected_sha256:
                raise ValueError(
                    f"strict DeepCenter SHA-256 mismatch for {path.name}: "
                    f"expected {expected_sha256}, got {actual_sha256}"
                )
            handle.seek(0)
            value = reader(handle)
            after_read = os.fstat(fd)
            if _strict_stat_identity(after_read) != _strict_stat_identity(before):
                raise RuntimeError(f"strict DeepCenter input changed while reading: {path.name}")
        return value, {
            "sha256": actual_sha256,
            "pre": _strict_stat_plain(before),
            "post_hash": _strict_stat_plain(after_hash),
            "post_read": _strict_stat_plain(after_read),
            "open_count": 1,
        }
    finally:
        os.close(fd)


def _load_deepcenter_veto_detector_strict_verified(
    cfg: PostprocConfig,
    checkpoint_path: Path,
    manifest_path: Path,
    *,
    expected_checkpoint_sha256: str,
    expected_manifest_sha256: str,
    expected_epoch: int,
    expected_manifest_model_config: object,
    expected_checkpoint_model_config: object,
) -> tuple[dict[str, object], dict[str, object]]:
    """Private injected-pin seam; production uses the non-overridable wrapper."""
    if not cfg.USE_DEEPCENTER_VETO or not cfg.REQUIRE_DEEPCENTER_VETO:
        raise ValueError("strict DeepCenter requires USE_DEEPCENTER_VETO and REQUIRE_DEEPCENTER_VETO")
    if torch is None:
        raise ImportError("torch is required for strict DeepCenter loading")
    if type(expected_epoch) is not int or expected_epoch != 2:
        raise ValueError("strict DeepCenter expected epoch must be exact built-in int 2")
    if not isinstance(expected_manifest_model_config, (dict, MappingProxyType)):
        raise TypeError("expected DeepCenter manifest model config must be a mapping")
    if not isinstance(expected_checkpoint_model_config, (dict, MappingProxyType)):
        raise TypeError("expected DeepCenter checkpoint model config must be a mapping")
    frozen_manifest_config = dict(expected_manifest_model_config)
    frozen_checkpoint_config = dict(expected_checkpoint_model_config)

    def read_manifest(handle: BinaryIO) -> object:
        return json.load(handle)

    manifest, manifest_file = _strict_read_one_file(
        manifest_path,
        expected_manifest_sha256,
        read_manifest,
    )
    if type(manifest) is not dict:
        raise ValueError("strict DeepCenter manifest must be a JSON object")
    try:
        manifest_model = manifest["model"]
        manifest_checkpoint = manifest_model["best_checkpoint"]
        manifest_summary = manifest_model["best_checkpoint_summary"]
    except (KeyError, TypeError) as exc:
        raise ValueError("strict DeepCenter manifest has no registered best checkpoint") from exc
    if (
        type(manifest_model) is not dict
        or type(manifest_checkpoint) is not dict
        or type(manifest_summary) is not dict
        or manifest_checkpoint.get("sha256") != expected_checkpoint_sha256
        or type(manifest_summary.get("epoch")) is not int
        or manifest_summary.get("epoch") != expected_epoch
        or not _strict_config_matches(manifest_model.get("config"), frozen_manifest_config)
    ):
        raise ValueError("strict DeepCenter manifest identity/config mismatch")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def read_checkpoint(handle: BinaryIO) -> object:
        return torch.load(handle, map_location=device, weights_only=False)

    checkpoint, checkpoint_file = _strict_read_one_file(
        checkpoint_path,
        expected_checkpoint_sha256,
        read_checkpoint,
    )
    if type(checkpoint) is not dict or "model_state" not in checkpoint:
        raise ValueError("strict DeepCenter checkpoint has no model_state")
    if type(checkpoint.get("epoch")) is not int or checkpoint["epoch"] != expected_epoch:
        raise ValueError("strict DeepCenter checkpoint epoch mismatch")
    if not _strict_config_matches(checkpoint.get("config"), frozen_checkpoint_config):
        raise ValueError("strict DeepCenter checkpoint config mismatch")
    model_cfg = SimpleNamespace(**checkpoint["config"])
    model = _DCDeepCenterUNet3D(base_channels=model_cfg.base_channels)
    model.load_state_dict(checkpoint["model_state"])
    model.to(device)
    model.eval()
    bundle = {
        "model": model,
        "cfg": model_cfg,
        "device": device,
        "path": checkpoint_path,
        "torch": torch,
        "checkpoint_epoch": expected_epoch,
    }
    receipt = {
        "schema_version": "biohub.st_r3.deepcenter_receipt.v1",
        "registered": {
            "checkpoint_name": checkpoint_path.name,
            "manifest_name": manifest_path.name,
        },
        "checkpoint": checkpoint_file,
        "manifest": manifest_file,
        "chosen_artifact": checkpoint_path.name,
        "verified_epoch": expected_epoch,
        "verified_configs": {
            "manifest": frozen_manifest_config,
            "checkpoint": frozen_checkpoint_config,
        },
        "known_config_discrepancy": {
            "field": "epochs",
            "manifest": frozen_manifest_config.get("epochs"),
            "checkpoint": frozen_checkpoint_config.get("epochs"),
        },
        "inference_relevant_config_equal": all(
            type(frozen_manifest_config[key]) is type(frozen_checkpoint_config.get(key))
            and frozen_manifest_config[key] == frozen_checkpoint_config[key]
            for key in frozen_manifest_config
            if key != "epochs"
        )
        and set(frozen_manifest_config) == set(frozen_checkpoint_config),
        "device": str(device),
        "dtype": "float32",
        "open_count": 2,
        "fallback_candidates": 0,
    }
    return bundle, receipt


def load_deepcenter_veto_detector_strict(
    cfg: PostprocConfig,
    checkpoint_path: Path,
    manifest_path: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    """Load only the exact preregistered DeepCenter artifact, without fallback."""
    return _load_deepcenter_veto_detector_strict_verified(
        cfg,
        checkpoint_path,
        manifest_path,
        expected_checkpoint_sha256=STRICT_DEEPCENTER_CHECKPOINT_SHA256,
        expected_manifest_sha256=STRICT_DEEPCENTER_MANIFEST_SHA256,
        expected_epoch=STRICT_DEEPCENTER_EPOCH,
        expected_manifest_model_config=STRICT_DEEPCENTER_MANIFEST_MODEL_CONFIG,
        expected_checkpoint_model_config=STRICT_DEEPCENTER_CHECKPOINT_MODEL_CONFIG,
    )


def _dc_pool_frame_xy(volume: np.ndarray, factor: int) -> np.ndarray:
    if factor <= 1:
        return volume.astype(np.float32, copy=False)
    z, y, x = volume.shape
    y2 = (y // factor) * factor
    x2 = (x // factor) * factor
    cropped = volume[:, :y2, :x2].astype(np.float32, copy=False)
    return cropped.reshape(z, y2 // factor, factor, x2 // factor, factor).mean(axis=(2, 4))


def _dc_normalize_dynamic_range(volume: np.ndarray, model_cfg: object) -> np.ndarray:
    vol = np.asarray(volume, dtype=np.float32)
    lo = float(np.percentile(vol, float(getattr(model_cfg, "norm_lo_pct", 50.0))))
    hi = float(np.percentile(vol, float(getattr(model_cfg, "norm_hi_pct", 99.5))))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return np.zeros_like(vol, dtype=np.float32)
    ratio = (vol - lo) / (hi - lo)
    return np.clip(
        ratio,
        float(getattr(model_cfg, "norm_clip_lo", -0.5)),
        float(getattr(model_cfg, "norm_clip_hi", 6.0)),
    ).astype(np.float32)


def _dc_manifest_weight_paths(manifest_path: Path) -> list[Path]:
    if not manifest_path.exists():
        return []
    import json

    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception as exc:
        print("Could not read DeepCenter manifest:", manifest_path, type(exc).__name__, exc)
        return []
    root = manifest_path.parent
    sections: list[dict[str, object]] = []
    for section in [
        manifest.get("model", {}),
        manifest.get("models", {}).get("full_frame_center", {}) if isinstance(manifest.get("models", {}), dict) else {},
        manifest.get("full_frame_center", {}),
    ]:
        if isinstance(section, dict):
            sections.append(section)
    candidates: list[Path] = []
    for section in sections:
        for key in ("weight_path", "path"):
            rel = section.get(key)
            if isinstance(rel, str) and rel:
                candidates.append(root / rel)
        for key in ("last_checkpoint", "best_checkpoint"):
            item = section.get(key)
            if isinstance(item, dict):
                rel = item.get("path")
                if isinstance(rel, str) and rel:
                    candidates.append(root / rel)
    for name in ("checkpoint_last.pt", "best.pt", "last.pt"):
        candidates.append(root / "weights" / "full_frame_center" / name)
        candidates.append(root / name)
    return candidates


def _dc_checkpoint_candidates(cfg: PostprocConfig) -> list[Path]:
    candidates: list[Path] = []
    explicit = (cfg.DEEPCENTER_CHECKPOINT or cfg.DEEPCENTER_CHECKPOINT_DEFAULT).strip()
    if explicit:
        candidates.append(Path(explicit))
    manifest_explicit = (cfg.DEEPCENTER_MANIFEST or cfg.DEEPCENTER_MANIFEST_DEFAULT).strip()
    if manifest_explicit:
        candidates.extend(_dc_manifest_weight_paths(Path(manifest_explicit)))
    candidates.append(Path(cfg.DEEPCENTER_CHECKPOINT_DEFAULT).parent / cfg.DEEPCENTER_RELATIVE)

    seen: set[Path] = set()
    out: list[Path] = []
    for path in candidates:
        path = path.expanduser()
        try:
            key = path.resolve() if path.exists() else path
        except Exception:
            key = path
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


if torch is not None:

    class _DCConvBlock3d(torch.nn.Module):
        def __init__(self, in_channels: int, out_channels: int) -> None:
            super().__init__()
            groups = min(8, out_channels)
            self.block = torch.nn.Sequential(
                torch.nn.Conv3d(in_channels, out_channels, 3, padding=1, bias=False),
                torch.nn.GroupNorm(groups, out_channels),
                torch.nn.SiLU(inplace=True),
                torch.nn.Conv3d(out_channels, out_channels, 3, padding=1, bias=False),
                torch.nn.GroupNorm(groups, out_channels),
                torch.nn.SiLU(inplace=True),
            )

        def forward(self, x):
            return self.block(x)

    class _DCDeepCenterUNet3D(torch.nn.Module):
        def __init__(self, in_channels: int = 1, base_channels: int = 24) -> None:
            super().__init__()
            c = int(base_channels)
            self.enc1 = _DCConvBlock3d(in_channels, c)
            self.down1 = torch.nn.MaxPool3d(2, 2)
            self.enc2 = _DCConvBlock3d(c, c * 2)
            self.down2 = torch.nn.MaxPool3d(2, 2)
            self.enc3 = _DCConvBlock3d(c * 2, c * 4)
            self.down3 = torch.nn.MaxPool3d(2, 2)
            self.bottleneck = _DCConvBlock3d(c * 4, c * 8)
            self.up3 = torch.nn.ConvTranspose3d(c * 8, c * 4, 2, 2)
            self.dec3 = _DCConvBlock3d(c * 8, c * 4)
            self.up2 = torch.nn.ConvTranspose3d(c * 4, c * 2, 2, 2)
            self.dec2 = _DCConvBlock3d(c * 4, c * 2)
            self.up1 = torch.nn.ConvTranspose3d(c * 2, c, 2, 2)
            self.dec1 = _DCConvBlock3d(c * 2, c)
            self.head = torch.nn.Conv3d(c, 1, 1)

        def forward(self, x):
            e1 = self.enc1(x)
            e2 = self.enc2(self.down1(e1))
            e3 = self.enc3(self.down2(e2))
            b = self.bottleneck(self.down3(e3))
            d3 = self.dec3(torch.cat([self.up3(b), e3], dim=1))
            d2 = self.dec2(torch.cat([self.up2(d3), e2], dim=1))
            d1 = self.dec1(torch.cat([self.up1(d2), e1], dim=1))
            return self.head(d1)
else:  # pragma: no cover - exercised only when torch is unavailable
    _DCConvBlock3d = None
    _DCDeepCenterUNet3D = None


def load_deepcenter_veto_detector(cfg: PostprocConfig) -> dict[str, object] | None:
    if not cfg.USE_DEEPCENTER_VETO:
        print("DeepCenter add-only repair gate disabled by configuration.")
        return None
    if torch is None:
        if cfg.REQUIRE_DEEPCENTER_VETO:
            raise ImportError("torch is required for DeepCenter add-only repair gate")
        print("DeepCenter add-only repair gate skipped because torch is unavailable.")
        return None
    from types import SimpleNamespace

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    load_errors: list[str] = []
    for checkpoint_path in _dc_checkpoint_candidates(cfg):
        if not checkpoint_path.exists():
            continue
        try:
            print("Trying DeepCenter add-only gate checkpoint:", checkpoint_path)
            checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
            if not isinstance(checkpoint, dict) or "model_state" not in checkpoint:
                raise ValueError("checkpoint has no model_state")
            checkpoint_epoch = int(checkpoint.get("epoch", -1))
            if cfg.DEEPCENTER_EXPECTED_EPOCH > 0 and checkpoint_epoch != cfg.DEEPCENTER_EXPECTED_EPOCH:
                raise ValueError(f"expected DeepCenter epoch {cfg.DEEPCENTER_EXPECTED_EPOCH}, got {checkpoint_epoch}")
            model_cfg = SimpleNamespace(**checkpoint.get("config", {}))
            model = _DCDeepCenterUNet3D(base_channels=int(getattr(model_cfg, "base_channels", 24)))
            model.load_state_dict(checkpoint["model_state"])
            model.to(device)
            model.eval()
            print("Loaded DeepCenter add-only gate checkpoint:", checkpoint_path)
            print("DeepCenter checkpoint epoch:", checkpoint.get("epoch"), "best_score:", checkpoint.get("best_score"))
            return {
                "model": model,
                "cfg": model_cfg,
                "device": device,
                "path": checkpoint_path,
                "torch": torch,
                "checkpoint_epoch": checkpoint_epoch,
            }
        except Exception as exc:
            load_errors.append(f"{checkpoint_path}: {type(exc).__name__}: {exc}")
            print("Skipping incompatible DeepCenter checkpoint:", checkpoint_path, "|", type(exc).__name__, exc)
    message = "No usable DeepCenter checkpoint found for add-only repair gate."
    if cfg.REQUIRE_DEEPCENTER_VETO:
        checked = "\n".join(str(p) for p in _dc_checkpoint_candidates(cfg)[:80])
        errors = "\n".join(load_errors[-20:])
        raise FileNotFoundError(message + "\nChecked:\n" + checked + ("\nLoad errors:\n" + errors if errors else ""))
    print(message)
    return None


def _dc_cache_trim(cache: dict[tuple[str, int], np.ndarray], cfg: PostprocConfig) -> None:
    limit = max(1, int(cfg.DEEPCENTER_SCORE_CACHE_MAX_FRAMES))
    while len(cache) > limit:
        cache.pop(next(iter(cache)))


def deepcenter_heatmap_for_frame(
    cfg: PostprocConfig,
    dataset: str,
    t: int,
    detector_bundle: dict[str, object] | None,
    frame_cache: dict[int, np.ndarray],
    heatmap_cache: dict[tuple[str, int], np.ndarray],
) -> np.ndarray | None:
    if detector_bundle is None:
        return None
    key = (dataset, int(t))
    cached = heatmap_cache.get(key)
    if cached is not None:
        return cached
    model = detector_bundle["model"]
    model_cfg = detector_bundle["cfg"]
    device = detector_bundle["device"]
    torch_mod = detector_bundle["torch"]
    pool_factor = int(getattr(model_cfg, "pool_factor", 4))
    volume = read_test_frame(cfg.TEST_DIR, dataset, int(t), frame_cache)
    pooled = _dc_pool_frame_xy(volume, pool_factor)
    image = _dc_normalize_dynamic_range(pooled, model_cfg)
    with torch_mod.no_grad():
        tensor = torch_mod.from_numpy(image[None, None, ...]).to(device=device, dtype=torch_mod.float32)
        heatmap = torch_mod.sigmoid(model(tensor))[0, 0].detach().cpu().numpy().astype(np.float32, copy=False)
    heatmap_cache[key] = heatmap
    _dc_cache_trim(heatmap_cache, cfg)
    return heatmap


def deepcenter_score_point(
    cfg: PostprocConfig,
    dataset: str | None,
    t: int,
    point: tuple[float, float, float],
    detector_bundle: dict[str, object] | None,
    frame_cache: dict[int, np.ndarray],
    heatmap_cache: dict[tuple[str, int], np.ndarray],
) -> float | None:
    if not cfg.USE_DEEPCENTER_VETO or detector_bundle is None or dataset is None:
        return None
    heatmap = deepcenter_heatmap_for_frame(cfg, dataset, int(t), detector_bundle, frame_cache, heatmap_cache)
    if heatmap is None or heatmap.size == 0:
        return None
    model_cfg = detector_bundle["cfg"]
    pool_factor = int(getattr(model_cfg, "pool_factor", 4))
    z = int(round(float(point[0])))
    y = int(round(float(point[1]) / max(pool_factor, 1)))
    x = int(round(float(point[2]) / max(pool_factor, 1)))
    z0, z1 = max(0, z - cfg.DEEPCENTER_SCORE_WIN_Z), min(heatmap.shape[0], z + cfg.DEEPCENTER_SCORE_WIN_Z + 1)
    y0, y1 = max(0, y - cfg.DEEPCENTER_SCORE_WIN_YX), min(heatmap.shape[1], y + cfg.DEEPCENTER_SCORE_WIN_YX + 1)
    x0, x1 = max(0, x - cfg.DEEPCENTER_SCORE_WIN_YX), min(heatmap.shape[2], x + cfg.DEEPCENTER_SCORE_WIN_YX + 1)
    patch = heatmap[z0:z1, y0:y1, x0:x1]
    if patch.size == 0:
        return None
    score = float(np.max(patch))
    return score if np.isfinite(score) else None


def deepcenter_accept_repair_point(
    cfg: PostprocConfig,
    dataset: str | None,
    t: int,
    point: tuple[float, float, float],
    detector_bundle: dict[str, object] | None,
    frame_cache: dict[int, np.ndarray],
    heatmap_cache: dict[tuple[str, int], np.ndarray],
    stats: dict[str, int],
    prefix: str,
    threshold: float,
) -> bool:
    if not cfg.USE_DEEPCENTER_VETO:
        return True
    if detector_bundle is None or dataset is None:
        stats[f"deepcenter_{prefix}_missing"] += 1
        return True
    stats[f"deepcenter_{prefix}_checked"] += 1
    score = deepcenter_score_point(cfg, dataset, int(t), point, detector_bundle, frame_cache, heatmap_cache)
    if score is None:
        stats[f"deepcenter_{prefix}_missing"] += 1
        return True
    if score < float(threshold):
        stats[f"deepcenter_{prefix}_rejected"] += 1
        return False
    stats[f"deepcenter_{prefix}_accepted"] += 1
    return True
