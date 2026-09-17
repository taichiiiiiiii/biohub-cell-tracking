"""Appearance cost between cell embeddings (mean over two seed sources)."""

from __future__ import annotations

import numpy as np

_DIM = 32
_MAX_SIDE = 2048
_MAX_DENSE = 1_000_000
_TOL = 1e-12


def _check_structure(label, arr):
    if not isinstance(arr, np.ndarray):
        raise ValueError(f"{label} must be a numpy ndarray")
    if arr.dtype != np.float32:
        raise ValueError(f"{label} must have dtype float32")
    if arr.ndim != 2:
        raise ValueError(f"{label} must be 2-D (n_rows, {_DIM})")
    if arr.shape[1] != _DIM:
        raise ValueError(f"{label} feature dimension must be {_DIM}")


def _validate_pair(side, prim, sec, other_prim, other_sec):
    for label, arr in ((f"primary_{side}", prim),
                       (f"secondary_{side}", sec),
                       (f"primary_{side}_counterpart", other_prim),
                       (f"secondary_{side}_counterpart", other_sec)):
        _check_structure(label, arr)
    if prim.shape != sec.shape:
        raise ValueError(f"primary/secondary {side} shapes differ: "
                         f"{prim.shape} vs {sec.shape}")
    n_src, n_tgt = prim.shape[0], other_prim.shape[0]
    if max(n_src, n_tgt) > _MAX_SIDE:
        raise ValueError(f"side length exceeds {_MAX_SIDE}")
    if n_src * n_tgt > _MAX_DENSE:
        raise ValueError(f"dense product {n_src * n_tgt} exceeds {_MAX_DENSE}")


def _normalize(label, arr):
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{label} contains non-finite values")
    norms = np.linalg.norm(arr, axis=1)
    if arr.shape[0] and np.any(norms == 0.0):
        raise ValueError(f"{label} contains a zero-norm row")
    return arr / norms[:, None]


def _cosine(source, target, label):
    src = _normalize(f"{label} source", np.array(source, dtype=np.float64))
    tgt = _normalize(f"{label} target", np.array(target, dtype=np.float64))
    cos = src @ tgt.T
    if not np.all(np.isfinite(cos)):
        raise ValueError(f"{label} cosine matrix contains non-finite values")
    if cos.size and (np.min(cos) < -1.0 - _TOL or np.max(cos) > 1.0 + _TOL):
        raise ValueError(f"{label} cosine outside [-1, 1]")
    return np.clip(cos, -1.0, 1.0)


def appearance_penalty(primary_source, primary_target,
                       secondary_source, secondary_target):
    """Return mean of per-seed (1 - cosine) costs as float64 (n_s, n_t)."""
    _validate_pair("source", primary_source, secondary_source,
                   primary_target, secondary_target)
    _validate_pair("target", primary_target, secondary_target,
                   primary_source, secondary_source)
    cos_p = _cosine(primary_source, primary_target, "primary")
    cos_s = _cosine(secondary_source, secondary_target, "secondary")
    return ((1.0 - cos_p) + (1.0 - cos_s)) / 2.0


def frame_appearance_penalty(
    frame: dict,
    t: int,
    source_ids: list[int],
    target_ids: list[int],
) -> np.ndarray:
    """Validate one appearance feature frame and return its penalty matrix.

    The frame must be an exact dict with the eight canonical keys. Source and
    target ID lists passed here must exactly equal the frame's stored lists
    (same order). The returned array is the existing
    ``appearance_penalty`` output for the four feature blocks in primary
    source, primary target, secondary source, secondary target order.
    """
    expected_keys = (
        "t_source",
        "t_target",
        "source_ids",
        "target_ids",
        "primary_source_features",
        "primary_target_features",
        "secondary_source_features",
        "secondary_target_features",
    )

    if type(frame) is not dict or set(frame) != set(expected_keys):
        raise ValueError("frame must be a dict with exactly the eight canonical keys")

    def _check_builtin_int(value: object, name: str) -> int:
        if type(value) is not int:
            raise ValueError(f"{name} must be a builtin int")
        return value

    t_value = _check_builtin_int(t, "t")
    t_source = _check_builtin_int(frame["t_source"], "t_source")
    t_target = _check_builtin_int(frame["t_target"], "t_target")

    if not 0 <= t_value <= 98:
        raise ValueError("t must satisfy 0 <= t <= 98")
    if t_source != t_value or t_target != t_value + 1:
        raise ValueError("frame t_source/t_target must equal t/t+1")

    def _check_id_list(value: object, name: str) -> list[int]:
        if type(value) is not list:
            raise ValueError(f"{name} must be a list of unique builtin ints")
        seen = set()
        for item in value:
            if type(item) is not int:
                raise ValueError(f"{name} must be a list of unique builtin ints")
            if item in seen:
                raise ValueError(f"{name} contains duplicate ids")
            seen.add(item)
        return value

    frame_sources = _check_id_list(frame["source_ids"], "frame source_ids")
    frame_targets = _check_id_list(frame["target_ids"], "frame target_ids")
    call_sources = _check_id_list(source_ids, "source_ids")
    call_targets = _check_id_list(target_ids, "target_ids")

    if frame_sources != call_sources:
        raise ValueError("source_ids must exactly equal frame source_ids including order")
    if frame_targets != call_targets:
        raise ValueError("target_ids must exactly equal frame target_ids including order")

    if set(call_sources) & set(call_targets):
        raise ValueError("source_ids and target_ids must not overlap")

    penalties = appearance_penalty(
        frame["primary_source_features"],
        frame["primary_target_features"],
        frame["secondary_source_features"],
        frame["secondary_target_features"],
    )

    if penalties.shape != (len(call_sources), len(call_targets)):
        raise ValueError("appearance_penalty shape mismatch for frame id lists")

    return penalties
