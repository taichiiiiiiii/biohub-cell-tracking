"""Reciprocal-consensus edge helper for Biohub cell tracking."""

from __future__ import annotations

import numpy as np

_MAX_NS = 2048
_MAX_NT = 2048
_MAX_PACKET = 1_000_000


def _validate(matrix: np.ndarray, name: str) -> tuple[int, int]:
    if type(matrix) is not np.ndarray:
        raise ValueError(f"{name} must be an exact np.ndarray")
    if matrix.dtype != np.float32:
        raise ValueError(f"{name} must have dtype float32")
    if matrix.ndim != 2:
        raise ValueError(f"{name} must be 2-dimensional")
    if not np.isfinite(matrix).all():
        raise ValueError(f"{name} must be finite")
    ns, nt = matrix.shape
    if ns > _MAX_NS or nt > _MAX_NT:
        raise ValueError(f"{name} exceeds axis cap {_MAX_NS}/{_MAX_NT}")
    if ns * nt > _MAX_PACKET:
        raise ValueError(f"{name} exceeds packet size {_MAX_PACKET}")
    return ns, nt


def _unique_max_along_axis(logits: np.ndarray, axis: int) -> np.ndarray:
    """Boolean mask that is True only where logits has a unique maximum."""
    best = logits.max(axis=axis, keepdims=True)
    hits = logits == best
    counts = hits.sum(axis=axis, keepdims=True)
    return hits & (counts == 1)


def reciprocal_consensus_pairs(
    primary_forward: np.ndarray,
    primary_reverse: np.ndarray,
    secondary_forward: np.ndarray,
) -> list[tuple[int, int]]:
    """Return (source, target) pairs agreed by all three detectors.

    A pair (i, j) is kept when i is the unique argmax of both forward matrices
    in column j and j is the unique argmax of the reverse matrix in row i.
    Logits are compared within a model/direction only. Ties are excluded.
    """
    shapes = (
        _validate(primary_forward, "primary_forward"),
        _validate(primary_reverse, "primary_reverse"),
        _validate(secondary_forward, "secondary_forward"),
    )
    ns, nt = shapes[0]
    if any(shape != shapes[0] for shape in shapes[1:]):
        raise ValueError("all matrices must share identical (ns, nt) shapes")
    if ns == 0 or nt == 0:
        return []
    src_ok = _unique_max_along_axis(primary_forward, axis=0) & _unique_max_along_axis(secondary_forward, axis=0)
    tgt_ok = _unique_max_along_axis(primary_reverse, axis=1)
    mask = src_ok & tgt_ok
    rows, cols = np.nonzero(mask)
    order = np.lexsort((cols, rows))
    return [(int(i), int(j)) for i, j in zip(rows[order], cols[order], strict=True)]


def positive_reciprocal_consensus_pairs(
    primary_forward: np.ndarray,
    primary_reverse: np.ndarray,
    secondary_forward: np.ndarray,
) -> list[tuple[int, int]]:
    """Return reciprocal pairs whose three selected logits are strictly positive."""
    pairs = reciprocal_consensus_pairs(
        primary_forward, primary_reverse, secondary_forward
    )
    return [
        (i, j)
        for i, j in pairs
        if primary_forward[i, j] > 0
        and primary_reverse[i, j] > 0
        and secondary_forward[i, j] > 0
    ]


def primary_reciprocal_consensus_pairs(
    primary_forward: np.ndarray,
    primary_reverse: np.ndarray,
) -> list[tuple[int, int]]:
    """Return strict reciprocal unique-argmax pairs from the primary model only."""
    forward_shape = _validate(primary_forward, "primary_forward")
    reverse_shape = _validate(primary_reverse, "primary_reverse")
    if forward_shape != reverse_shape:
        raise ValueError("primary matrices must share identical shapes")
    ns, nt = forward_shape
    if ns == 0 or nt == 0:
        return []
    src_ok = _unique_max_along_axis(primary_forward, axis=0)
    tgt_ok = _unique_max_along_axis(primary_reverse, axis=1)
    rows, cols = np.nonzero(src_ok & tgt_ok)
    order = np.lexsort((cols, rows))
    return [(int(i), int(j)) for i, j in zip(rows[order], cols[order], strict=True)]


def map_consensus_to_raw(pairs, source_detector_indices, target_detector_indices, graph_to_detector, raw_node_ids):
    lists = (pairs, source_detector_indices, target_detector_indices, raw_node_ids)
    if any(type(x) is not list for x in lists):
        raise ValueError("list inputs must be exact lists")
    if type(graph_to_detector) is not dict:
        raise ValueError("graph_to_detector must be an exact dict")

    def is_int(v):
        return type(v) is int and v >= 0

    for g, d in graph_to_detector.items():
        if not (is_int(g) and is_int(d)):
            raise ValueError("mapping keys/values must be nonnegative ints")
    graphs = list(graph_to_detector)
    dets = list(graph_to_detector.values())
    if len(set(graphs)) != len(graphs) or len(set(dets)) != len(dets):
        raise ValueError("mapping must be one-to-one")

    for name, arr in (("source", source_detector_indices), ("target", target_detector_indices), ("raw", raw_node_ids)):
        if any(not is_int(v) for v in arr):
            raise ValueError(f"{name} entries must be nonnegative ints")
        if len(set(arr)) != len(arr):
            raise ValueError(f"{name} entries must be unique")

    if set(source_detector_indices) & set(target_detector_indices):
        raise ValueError("source/target detector sets must be disjoint")
    mapped = set(dets)
    for v in source_detector_indices + target_detector_indices:
        if v not in mapped:
            raise ValueError("detector index missing from mapping values")
    keyset = set(graphs)
    for v in raw_node_ids:
        if v not in keyset:
            raise ValueError("raw id missing from mapping keys")

    ns, nt = len(source_detector_indices), len(target_detector_indices)
    for p in pairs:
        if type(p) is not tuple or len(p) != 2 or not all(is_int(x) for x in p):
            raise ValueError("pairs must be tuples of two nonnegative ints")
    if pairs != sorted(pairs):
        raise ValueError("pairs must be sorted")
    if len(set(pairs)) != len(pairs):
        raise ValueError("pairs must be unique")
    for i, j in pairs:
        if not (0 <= i < ns and 0 <= j < nt):
            raise ValueError("pair indices out of range")
    if len({i for i, _ in pairs}) != len(pairs):
        raise ValueError("repeated source row")
    if len({j for _, j in pairs}) != len(pairs):
        raise ValueError("repeated target column")

    inverse = {d: g for g, d in graph_to_detector.items()}
    rawset = set(raw_node_ids)
    out = []
    for i, j in pairs:
        sg = inverse[source_detector_indices[i]]
        tg = inverse[target_detector_indices[j]]
        if sg in rawset and tg in rawset:
            out.append((sg, tg))
    return sorted(out)
