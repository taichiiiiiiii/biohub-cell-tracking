"""Read a bound lossless packet and query actual graph-ID pairs, never score or train."""

import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from biohub.association_capture import COORDINATES, FEATURES, MATRICES, _require, _sha
from biohub.association_parity import array_signatures


@dataclass
class Packet:
    record: dict
    arrays: dict


def _validate_coords(coords):
    _require(
        isinstance(coords, np.ndarray)
        and coords.dtype == np.dtype("int16")
        and coords.ndim == 2
        and coords.shape[1] == 4,
        "invalid returned detector coords",
    )
    _require(
        np.all(coords >= 0) and np.all(coords[:, 0] <= 99) and np.all(np.diff(coords[:, 0].astype(np.int64)) >= 0),
        "invalid detector coordinate order/range",
    )


def read_packet(root, record, detector_coords):
    root = Path(root)
    _validate_coords(detector_coords)
    name, t = record["dataset"], record["t_source"]
    _require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]+", name) is not None, "unsafe dataset name")
    _require(type(t) is int and 0 <= t < 99 and record["t_target"] == t + 1, "invalid frame pair")
    _require(record["path"] == f"{name}/pair_{t:04d}.npz", "unexpected packet path")
    ns, nt = record["n_source"], record["n_target"]
    _require(
        type(ns) is int
        and type(nt) is int
        and 0 <= ns <= 2048
        and 0 <= nt <= 2048
        and ns * nt <= 1_000_000
        and record["dense_pairs"] == ns * nt,
        "packet size contract",
    )
    _require(
        record["schema_version"] == "biohub.e23.association_pair.v1"
        and record["window_size"] == 2
        and record["matrix_axes"] == ["source", "target"]
        and record["probability_normalisation_axis"] == "source"
        and record["downsample_zyx"] == [1, 4, 4]
        and record["scale_zyx_um"] == [1.625, 0.40625, 0.40625]
        and record["submission_authorized"] is False,
        "packet axes/units/schema mismatch",
    )
    empty = ns == 0 or nt == 0
    _require(record["status"] == ("SKIPPED_EMPTY" if empty else "OBSERVED"), "invalid empty status")
    path = root / record["path"]
    _require(root.resolve() in path.resolve().parents, "packet path escapes root")
    _require(path.stat().st_size == record["bytes"] and _sha(path) == record["sha256"], "packet file changed")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        _require(len(entries) == len({e.filename for e in entries}), "duplicate ZIP member")
        _require(sum(e.file_size for e in entries) <= 32 * 1024**2, "packet expansion budget exceeded")
    keys = set(COORDINATES) if empty else set(COORDINATES + FEATURES + MATRICES)
    with np.load(path, allow_pickle=False) as saved:
        _require(set(saved.files) == keys | {"metadata"}, "packet keys mismatch")
        metadata = json.loads(str(saved["metadata"]))
        _require(
            metadata == {k: v for k, v in record.items() if k not in ("path", "bytes", "sha256")},
            "packet metadata mismatch",
        )
        arrays = {k: saved[k] for k in keys}
    for k, a in arrays.items():
        n = ns if "source" in k else nt
        shape = (
            (ns, nt) if k in MATRICES else (n,) if k.endswith("indices") else (n, 4) if k.endswith("grid") else (n, 32)
        )
        dtype = (
            np.dtype("int64")
            if k.endswith("indices")
            else np.dtype("int16")
            if k.endswith("grid")
            else np.dtype("float32")
        )
        _require(a.shape == shape and a.dtype == dtype and np.isfinite(a).all(), f"packet array contract: {k}")
    _require(array_signatures(arrays) == record["arrays"], "packet array hash mismatch")
    for side, frame in (("source", t), ("target", t + 1)):
        expected = np.flatnonzero(detector_coords[:, 0] == frame)
        _require(np.array_equal(arrays[f"{side}_indices"], expected), "global detector indices mismatch")
        restored = arrays[f"{side}_coords_grid"].astype(np.int64) * (1, 1, 4, 4)
        _require(np.array_equal(restored, detector_coords[expected]), "grid/returned coordinate mismatch")
    if not empty:
        p = arrays["mixed_probabilities"]
        _require(
            np.all((p >= 0) & (p <= 1)) and np.allclose(p.sum(axis=0, dtype=np.float64), 1.0, atol=2e-5, rtol=0),
            "invalid source-normalized probability",
        )
    _require(_sha(path) == record["sha256"], "packet changed while reading")
    return Packet(record, arrays)


def detector_lookup(pre_graph, detector_coords):
    _validate_coords(detector_coords)
    indices, ids = pre_graph["detector_indices"], pre_graph["graph_node_ids"]
    _require(
        indices.dtype == ids.dtype == np.dtype("int64")
        and ids.shape == indices.shape
        and np.array_equal(indices, np.arange(len(detector_coords), dtype=np.int64)),
        "invalid graph ID mapping",
    )
    _require(len(set(ids.tolist())) == len(ids), "nonbijective graph ID mapping")
    node_ids = pre_graph["node_node_id"]
    _require(
        node_ids.dtype == np.dtype("int64")
        and node_ids.shape == ids.shape
        and len(set(node_ids.tolist())) == len(node_ids),
        "invalid graph node IDs",
    )
    for key in ("t", "z", "y", "x"):
        values = pre_graph[f"node_{key}"]
        _require(values.shape == ids.shape and np.isfinite(values).all(), "invalid graph coordinate column")
    graph_nodes = {
        int(i): tuple(p)
        for i, p in zip(
            pre_graph["node_node_id"],
            np.column_stack([pre_graph[f"node_{k}"] for k in ("t", "z", "y", "x")]),
            strict=True,
        )
    }
    _require(
        len(graph_nodes) == len(ids)
        and all(graph_nodes.get(int(i)) == tuple(detector_coords[j]) for j, i in enumerate(ids)),
        "graph ID/coordinate mismatch",
    )
    return {int(i): int(j) for j, i in enumerate(ids)}


def query_pair(packet, graph_to_detector, source_id, target_id, pre_probability):
    """pre_probability is the saved candidate edge probability, or None if absent."""
    _require(packet.record["status"] == "OBSERVED", "empty pair has no model probability")
    _require(type(source_id) is int and type(target_id) is int, "graph IDs must be integers")
    _require(source_id in graph_to_detector and target_id in graph_to_detector, "unmapped graph ID")
    a = packet.arrays
    locations = []
    for side, node_id in (("source", source_id), ("target", target_id)):
        where = np.flatnonzero(a[f"{side}_indices"] == graph_to_detector[node_id])
        _require(len(where) == 1, "node not in this packet side")
        locations.append(int(where[0]))
    i, j = locations
    column = a["mixed_probabilities"][:, j]
    probability = float(column[i])
    above = bool(column[i] > np.float32(0.48))
    _require((pre_probability is not None) == above, "matrix/candidate presence mismatch")
    if above:
        _require(
            type(pre_probability) in (int, float) and pre_probability == probability,
            "matrix/candidate probability mismatch",
        )
    greater, equal = int(np.count_nonzero(column > column[i])), int(np.count_nonzero(column == column[i]))
    others = np.delete(column, i)
    best_other = float(others.max()) if len(others) else None
    return {
        "dataset": packet.record["dataset"],
        "t_source": packet.record["t_source"],
        "source_graph_id": source_id,
        "target_graph_id": target_id,
        "source_detector_index": graph_to_detector[source_id],
        "target_detector_index": graph_to_detector[target_id],
        "source_row": i,
        "target_column": j,
        "mixed_probability": probability,
        "above_candidate_threshold": above,
        "rank_best": greater + 1,
        "rank_worst": greater + equal,
        "best_other_probability": best_other,
        "margin_vs_best_other": probability - best_other if best_other is not None else None,
        "raw_saved_logits": {k: float(a[k][i, j]) for k in MATRICES if k != "mixed_probabilities"},
        "matrix_read": True,
        "training_label_assigned": False,
        "submission_authorized": False,
    }
