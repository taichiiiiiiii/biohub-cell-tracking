"""Sequential E23 observation adapter; no predictor, GT, model load or network."""

from __future__ import annotations

import json
import time
from functools import wraps
from pathlib import Path

import numpy as np

from biohub.association_capture import PairCapture, _json_bytes, _require, _sha


def observed(method):
    """Account synchronous capture work at call boundaries; never swallow errors."""
    @wraps(method)
    def call(self, *args, **kwargs):
        _require(not self.failed and not self.closed, "observer failed or closed")
        started = time.perf_counter()
        try:
            result = method(self, *args, **kwargs)
            self.seconds += time.perf_counter() - started
            _require(self.seconds <= self.pairs.limits.writer_seconds, "observer time budget exceeded")
            _require(self.pairs.output_bytes + self.graph_bytes <= self.pairs.limits.output_bytes,
                     "observer byte budget exceeded")
            return result
        except Exception as exc:
            self.failed = True
            path = self.root / "ERROR.json"
            if not path.exists():
                with path.open("xb") as stream:
                    stream.write(_json_bytes({"status": "ERROR", "error": str(exc),
                                              "submission_authorized": False}))
            raise
    return call


def _copy_tensor(value, *, batched=True):
    # No .float(), autocast, RNG, or model invocation. PairCapture checks actual dtype.
    array = value.detach().cpu().numpy()
    if batched:
        _require(array.ndim == 3 and array.shape[0] == 1, "expected batch size one")
        array = array[0]
    return array.copy()


class AssociationObserver:
    def __init__(self, root: Path, frame_counts, *, limits=None, downsample=(1, 4, 4),
                 scale=(1.625, .40625, .40625)):
        self.root = Path(root)
        # PairCapture validates the plan before creating any directory.
        _require(not self.root.exists(), "observer output already exists")
        self.pairs = PairCapture(self.root / "pairs", frame_counts, limits=limits,
                                 downsample=downsample, scale=scale)
        self.failed = self.closed = False
        self.seconds = self.graph_bytes = 0
        self.dataset = None
        self.pending = None
        self.stage = "idle"
        self.completed = set()
        self.artifacts = []
        self.coords = self.edges = self.before = None

    @observed
    def start_video(self, name, frames, window_size, downsample, scale, activation, *,
                    threshold=.48, max_parents=None, max_children=None):
        _require(self.dataset is None and name not in self.completed, "video overlap or duplicate")
        _require(name in self.pairs.frame_counts and frames == len(self.pairs.frame_counts[name]),
                 "video plan mismatch")
        _require(window_size == 2 and tuple(downsample) == self.pairs.downsample
                 and tuple(scale) == self.pairs.scale and activation == "softmax", "inference geometry mismatch")
        _require(threshold == .48 and max_parents is None and max_children is None,
                 "E23 candidate filtering mismatch")
        self.threshold = threshold
        self.dataset, self.stage = name, "pair"

    @observed
    def start_pair(self, t, s_src, e_src, s_tgt, e_tgt, coords):
        _require(self.stage == "pair" and self.pending is None, "pair stage order mismatch")
        _require((self.dataset, t) in self.pairs.expected, "unexpected pair")
        offsets = self.pairs.offsets[self.dataset]
        _require((s_src, e_src, s_tgt, e_tgt) == (offsets[t], offsets[t + 1], offsets[t + 1], offsets[t + 2]),
                 "detector offsets mismatch")
        self.t = t
        self.pending = {
            "source_indices": np.arange(s_src, e_src, dtype=np.int64),
            "target_indices": np.arange(s_tgt, e_tgt, dtype=np.int64),
            "source_coords_grid": coords[s_src:e_src].copy(),
            "target_coords_grid": coords[s_tgt:e_tgt].copy(),
        }
        if s_src == e_src or s_tgt == e_tgt:
            self.pairs.write_pair(self.dataset, t, self.pending)
            self.pending = None
        else:
            self.stage = "primary"

    @observed
    def primary(self, logits, source, target):
        _require(self.stage == "primary", "primary stage order mismatch")
        self.pending.update(primary_forward_logits=_copy_tensor(logits),
                            primary_source_features=_copy_tensor(source),
                            primary_target_features=_copy_tensor(target))
        self.stage = "reverse"

    @observed
    def reverse(self, transposed_logits):
        _require(self.stage == "reverse", "reverse stage order mismatch")
        self.pending["primary_reverse_logits"] = _copy_tensor(transposed_logits)
        self.stage = "secondary"

    @observed
    def secondary(self, logits, source, target):
        _require(self.stage == "secondary", "secondary stage order mismatch")
        self.pending.update(secondary_forward_logits=_copy_tensor(logits),
                            secondary_source_features=_copy_tensor(source),
                            secondary_target_features=_copy_tensor(target))
        self.stage = "mixed"

    @observed
    def mixed(self, raw, probabilities):
        _require(self.stage == "mixed", "mixed stage order mismatch")
        self.pending.update(mixed_logits=_copy_tensor(raw, batched=False),
                            mixed_probabilities=probabilities.copy())
        self.pairs.write_pair(self.dataset, self.t, self.pending)
        self.pending, self.stage = None, "pair"

    @observed
    def end_video(self, coords, edges):
        _require(self.stage == "pair" and self.pending is None, "incomplete pair")
        name = self.dataset
        _require({(name, t) for t in range(len(self.pairs.frame_counts[name]) - 1)}
                 <= set(self.pairs.records), "incomplete video")
        _require(coords.dtype == np.int16 and coords.shape == (sum(self.pairs.frame_counts[name]), 4),
                 "returned coordinates shape/dtype mismatch")
        by_time = {t: {} for t in range(len(self.pairs.frame_counts[name]) - 1)}
        for s, target, probability, distance in edges:
            _require(type(s) is int and type(target) is int and 0 <= s < len(coords)
                     and 0 <= target < len(coords), "invalid returned edge index")
            t = int(coords[s, 0])
            _require(t in by_time and coords[target, 0] == t + 1, "invalid returned edge time")
            _require((s, target) not in by_time[t], "duplicate returned edge")
            by_time[t][s, target] = (probability, distance)
        for t in range(len(self.pairs.frame_counts[name]) - 1):
            record = self.pairs.records[name, t]
            with np.load(self.pairs.root / record["path"], allow_pickle=False) as packet:
                for side in ("source", "target"):
                    grid = packet[f"{side}_coords_grid"].astype(np.int64)
                    grid[:, 1:] *= self.pairs.downsample
                    _require(np.array_equal(coords[packet[f"{side}_indices"]], grid),
                             "returned coordinates differ from observed detections")
                expected = {}
                if record["status"] != "SKIPPED_EMPTY":
                    probabilities = packet["mixed_probabilities"]
                    source_ids, target_ids = packet["source_indices"], packet["target_indices"]
                    source_grid, target_grid = packet["source_coords_grid"], packet["target_coords_grid"]
                    for i, j in zip(*np.where(probabilities > self.threshold), strict=True):
                        delta = source_grid[i, 1:].astype(np.float32) - target_grid[j, 1:].astype(np.float32)
                        expected[int(source_ids[i]), int(target_ids[j])] = (
                            float(probabilities[i, j]), float(np.linalg.norm(delta)))
                _require(expected == by_time[t], "returned candidates differ from observed probability/geometry")
        self.coords = coords.copy()
        self.edges = tuple(tuple(edge) for edge in edges)
        self.stage = "pre_graph"

    def _save_arrays(self, label, arrays):
        _require(all(isinstance(a, np.ndarray) and not a.dtype.hasobject for a in arrays.values()),
                 "graph array type mismatch")
        path = self.root / f"{self.dataset}_{label}.npz"
        with path.open("xb") as stream:
            np.savez_compressed(stream, **arrays)
        with np.load(path, allow_pickle=False) as saved:
            _require(set(saved.files) == set(arrays), "graph roundtrip keys mismatch")
            for key, original in arrays.items():
                actual = saved[key]
                _require(actual.dtype == original.dtype and actual.shape == original.shape
                         and actual.tobytes() == original.tobytes(), "graph roundtrip mismatch")
        self.graph_bytes += path.stat().st_size
        self.artifacts.append({"path": path.name, "bytes": path.stat().st_size, "sha256": _sha(path),
                               "dataset": self.dataset, "stage": label})

    @staticmethod
    def _graph_tables(graph):
        nodes = graph.node_attrs(attr_keys=["node_id", "t", "z", "y", "x"])
        edge_keys = ["edge_id", "source_id", "target_id"]
        edges = graph.edge_attrs(attr_keys=edge_keys + (["edge_prob", "edge_dist"] if graph.num_edges() else []))
        return nodes, edges

    @observed
    def pre_graph(self, coords, edges, node_ids, graph):
        _require(self.stage == "pre_graph", "pre-graph stage order mismatch")
        _require(np.array_equal(coords, self.coords) and tuple(tuple(e) for e in edges) == self.edges,
                 "build_graph inputs changed")
        _require(len(node_ids) == len(coords) and len(set(node_ids)) == len(coords)
                 and all(isinstance(i, (int, np.integer)) and not isinstance(i, bool) for i in node_ids),
                 "nonbijective graph ID mapping")
        nodes, edge_table = self._graph_tables(graph)
        node_map = {r["node_id"]: r for r in nodes.iter_rows(named=True)}
        _require(len(node_map) == len(node_ids), "pre-graph node count mismatch")
        for row, node_id in enumerate(node_ids):
            _require(node_id in node_map and
                     tuple(node_map[node_id][k] for k in ("t", "z", "y", "x")) == tuple(coords[row]),
                     "graph ID/coordinate mismatch")
        expected = {}
        for s, t, prob, dist in edges:
            _require(type(s) is int and type(t) is int and 0 <= s < len(coords) and 0 <= t < len(coords),
                     "invalid candidate index")
            _require(coords[t, 0] == coords[s, 0] + 1 and np.isfinite(prob) and np.isfinite(dist)
                     and 0 <= prob <= 1 and dist >= 0, "invalid candidate edge")
            key = (node_ids[s], node_ids[t])
            _require(key not in expected, "duplicate candidate edge")
            expected[key] = (prob, dist)
        actual = {(r["source_id"], r["target_id"]): (r["edge_prob"], r["edge_dist"])
                  for r in edge_table.iter_rows(named=True)}
        _require(edge_table.height == len(actual) and actual == expected, "pre-graph candidate mismatch")
        arrays = {"detector_indices": np.arange(len(coords), dtype=np.int64),
                  "graph_node_ids": np.asarray(node_ids, dtype=np.int64)}
        for prefix, table in (("node", nodes), ("edge", edge_table)):
            arrays.update({f"{prefix}_{column}": table[column].to_numpy() for column in table.columns})
        self._save_arrays("pre_ilp", arrays)
        self.before = (node_map, actual)
        self.stage = "selected_graph"

    @observed
    def selected_graph(self, graph):
        _require(self.stage == "selected_graph", "selected-graph stage order mismatch")
        nodes, edges = self._graph_tables(graph)
        before_nodes, before_edges = self.before
        node_ids = nodes["node_id"].to_list()
        _require(len(node_ids) == len(set(node_ids)), "duplicate selected node")
        for row in nodes.iter_rows(named=True):
            _require(before_nodes.get(row["node_id"]) == row, "selected node changed")
        selected_edges = set()
        selected_ids = set(node_ids)
        for row in edges.iter_rows(named=True):
            key = (row["source_id"], row["target_id"])
            _require(key not in selected_edges and all(i in selected_ids for i in key)
                     and before_edges.get(key) == (row["edge_prob"], row["edge_dist"]),
                     "selected edge changed or dangling")
            selected_edges.add(key)
        self._save_arrays("post_ilp", {f"{prefix}_{column}": table[column].to_numpy()
                                       for prefix, table in (("node", nodes), ("edge", edges))
                                       for column in table.columns})
        self.completed.add(self.dataset)
        self.dataset, self.stage = None, "idle"
        self.coords = self.edges = self.before = None

    @observed
    def verify_complete(self):
        _require(self.dataset is None and self.completed == set(self.pairs.frame_counts), "incomplete graph capture")
        self.pairs.finish()
        for item in self.artifacts:
            path = self.root / item["path"]
            _require(path.stat().st_size == item["bytes"] and _sha(path) == item["sha256"], "graph artifact changed")
        self.graph_bytes += (self.pairs.root / "MANIFEST.json").stat().st_size

    def finish(self):
        self.verify_complete()
        result = {"status": "ASSOCIATION_OBSERVATION_COMPLETE_NOT_PARITY", "capture_only": True,
                  "graph_ID_mapping_complete": True, "inference_parity_verified": False,
                  "submission_authorized": False, "datasets": sorted(self.completed),
                  "candidate_threshold": .48, "candidate_limits": {"parents": None, "children": None},
                  "observer_seconds_excluding_final_manifest": self.seconds,
                  "time_limit_enforcement": "synchronous_call_boundaries",
                  "pair_manifest_sha256": _sha(self.pairs.root / "MANIFEST.json"),
                  "graphs": self.artifacts}
        encoded = _json_bytes(result)
        try:
            _require(self.pairs.output_bytes + self.graph_bytes + len(encoded) <= self.pairs.limits.output_bytes,
                     "observer final manifest byte budget exceeded")
            with (self.root / "MANIFEST.json").open("xb") as stream:
                stream.write(encoded)
        except Exception as exc:
            self.failed = True
            with (self.root / "ERROR.json").open("xb") as stream:
                stream.write(_json_bytes({"status": "ERROR", "error": str(exc), "submission_authorized": False}))
            raise
        self.closed = True
        return json.loads(encoded)
