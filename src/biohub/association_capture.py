"""Lossless observation packets for the fixed E23 association path, not a predictor.

The caller supplies detached CPU NumPy arrays. No torch/model imports, network,
labels, score modification, implicit precision conversion, or top-k selection.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MATRICES = (
    "primary_forward_logits", "primary_reverse_logits", "secondary_forward_logits",
    "mixed_logits", "mixed_probabilities",
)
FEATURES = ("primary_source_features", "primary_target_features",
            "secondary_source_features", "secondary_target_features")
COORDINATES = ("source_indices", "target_indices", "source_coords_grid", "target_coords_grid")


@dataclass(frozen=True)
class CaptureLimits:
    nodes_per_side: int = 2048
    pairs_per_packet: int = 1_000_000
    pairs_per_run: int = 450_000_000
    output_bytes: int = 12 * 1024**3
    writer_seconds: float = 1200.0


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode()


class PairCapture:
    """Fresh-run writer with literal per-video detector counts and full-pair coverage.

`primary_reverse_logits` must already be transposed into (source, target)
orientation by the observer. Original-space coordinates are grid * downsample;
physical coordinates additionally multiply scale. Neither conversion alters input.
"""

    def __init__(self, root: Path, frame_counts: dict[str, list[int]], *,
                 downsample=(1, 4, 4), scale=(1.625, 0.40625, 0.40625), limits=None):
        if limits is None:
            limits = CaptureLimits()
        _require(isinstance(limits, CaptureLimits), "invalid limits")
        _require(all(type(getattr(limits, k)) is int and getattr(limits, k) > 0
                     for k in ("nodes_per_side", "pairs_per_packet", "pairs_per_run", "output_bytes")),
                 "limits must be positive integers")
        _require(type(limits.writer_seconds) in (int, float) and np.isfinite(limits.writer_seconds)
                 and limits.writer_seconds > 0, "invalid writer time limit")
        _require(len(downsample) == 3 and all(type(v) is int and v > 0 for v in downsample),
                 "invalid downsample")
        _require(len(scale) == 3 and all(type(v) in (int, float) and np.isfinite(v) and v > 0 for v in scale),
                 "invalid scale")
        _require(bool(frame_counts), "empty dataset plan")
        self.frame_counts = {}
        self.offsets = {}
        self.expected = set()
        expected_pairs = 0
        for name, counts in frame_counts.items():
            _require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]+", name), "unsafe dataset name")
            _require(len(counts) >= 2 and all(type(n) is int and 0 <= n <= limits.nodes_per_side for n in counts),
                     "invalid detector count")
            _require(len(counts) < 32768, "frame index exceeds int16")
            self.frame_counts[name] = tuple(counts)
            self.offsets[name] = np.cumsum([0, *counts], dtype=np.int64)
            for t in range(len(counts) - 1):
                size = counts[t] * counts[t + 1]
                _require(size <= limits.pairs_per_packet, "packet pair budget exceeded")
                expected_pairs += size
                self.expected.add((name, t))
        _require(expected_pairs <= limits.pairs_per_run, "run pair budget exceeded")
        self.expected_pairs = expected_pairs
        self.downsample, self.scale, self.limits = tuple(downsample), tuple(scale), limits
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=False)
        self.records = {}
        self.output_bytes = 0
        self.writer_seconds = 0.0
        self.failed = False
        self.closed = False

    def _available(self):
        _require(not self.failed and not self.closed, "capture already failed or closed")

    def _failure(self, exc):
        self.failed = True
        path = self.root / "ERROR.json"
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(_json_bytes({"status": "ERROR", "type": type(exc).__name__, "error": str(exc),
                                          "submission_authorized": False}))

    def _validate(self, dataset, t_source, arrays):
        _require(type(t_source) is int and (dataset, t_source) in self.expected, "unexpected frame pair")
        _require((dataset, t_source) not in self.records, "duplicate frame pair")
        ns, nt = self.frame_counts[dataset][t_source:t_source + 2]
        empty = ns == 0 or nt == 0
        keys = set(COORDINATES) if empty else set(COORDINATES + MATRICES + FEATURES)
        _require(set(arrays) == keys, "packet key set mismatch")
        for key, a in arrays.items():
            _require(isinstance(a, np.ndarray) and not a.dtype.hasobject, f"not a numeric ndarray: {key}")
            if key in MATRICES:
                shape, dtype = (ns, nt), np.dtype("float32")
            else:
                n = ns if "source" in key else nt
                shape = (n,) if key.endswith("indices") else (n, 4) if key.endswith("grid") else (n, 32)
                dtype = np.dtype("int64") if key.endswith("indices") else (
                    np.dtype("int16") if key.endswith("grid") else np.dtype("float32"))
            _require(a.shape == shape and a.dtype == dtype, f"shape/dtype mismatch: {key}")
            _require(np.isfinite(a).all(), f"nonfinite: {key}")
        for side, t in (("source", t_source), ("target", t_source + 1)):
            start, end = self.offsets[dataset][t:t + 2]
            _require(np.array_equal(arrays[f"{side}_indices"], np.arange(start, end, dtype=np.int64)),
                     f"global detector ID mapping mismatch: {side}")
            coords = arrays[f"{side}_coords_grid"]
            _require(np.all(coords[:, 0] == t) and np.all(coords[:, 1:] >= 0), f"invalid t/grid coords: {side}")
        if not empty:
            probs = arrays["mixed_probabilities"]
            _require(np.all((probs >= 0) & (probs <= 1)), "probability out of range")
            _require(np.allclose(probs.sum(axis=0, dtype=np.float64), 1., atol=2e-5, rtol=0),
                     "probabilities not normalised over source axis")
        return ns, nt, empty

    def write_pair(self, dataset: str, t_source: int, arrays: dict[str, np.ndarray]):
        self._available()
        started = time.perf_counter()
        try:
            ns, nt, empty = self._validate(dataset, t_source, arrays)
            metadata = {"schema_version": "biohub.e23.association_pair.v1", "dataset": dataset,
                        "t_source": t_source, "t_target": t_source + 1, "window_size": 2,
                        "downsample_zyx": self.downsample, "scale_zyx_um": self.scale,
                        "matrix_axes": ["source", "target"], "probability_normalisation_axis": "source",
                        "status": "SKIPPED_EMPTY" if empty else "OBSERVED",
                        "n_source": ns, "n_target": nt, "dense_pairs": ns * nt,
                        "arrays": {k: {"shape": list(a.shape), "dtype": a.dtype.str,
                                       "sha256": hashlib.sha256(a.tobytes(order="C")).hexdigest()}
                                   for k, a in arrays.items()}, "submission_authorized": False}
            folder = self.root / dataset
            folder.mkdir(exist_ok=True)
            path = folder / f"pair_{t_source:04d}.npz"
            with path.open("xb") as stream:
                np.savez_compressed(stream, metadata=np.array(_json_bytes(metadata).decode()), **arrays)
            with np.load(path, allow_pickle=False) as saved:
                _require(set(saved.files) == set(arrays) | {"metadata"}, "roundtrip key mismatch")
                _require(json.loads(str(saved["metadata"])) == json.loads(json.dumps(metadata)),
                         "roundtrip metadata mismatch")
                for key, original in arrays.items():
                    actual = saved[key]
                    _require(actual.dtype == original.dtype and actual.shape == original.shape and
                             actual.tobytes(order="C") == original.tobytes(order="C"),
                             f"lossy roundtrip: {key}")
            digest = _sha(path)
            self.output_bytes += path.stat().st_size
            self.writer_seconds += time.perf_counter() - started
            _require(self.output_bytes <= self.limits.output_bytes, "output byte budget exceeded")
            _require(self.writer_seconds <= self.limits.writer_seconds, "writer time budget exceeded")
            self.records[dataset, t_source] = {"path": path.relative_to(self.root).as_posix(),
                                             "bytes": path.stat().st_size, "sha256": digest, **metadata}
            return json.loads(json.dumps(self.records[dataset, t_source]))
        except Exception as exc:
            self._failure(exc)
            raise

    def finish(self):
        self._available()
        started = time.perf_counter()
        try:
            _require(set(self.records) == self.expected, "incomplete frame-pair capture")
            _require(sum(r["dense_pairs"] for r in self.records.values()) == self.expected_pairs,
                     "dense pair count mismatch")
            for record in self.records.values():
                path = self.root / record["path"]
                _require(path.stat().st_size == record["bytes"] and _sha(path) == record["sha256"],
                         "saved packet changed")
            self.writer_seconds += time.perf_counter() - started
            _require(self.writer_seconds <= self.limits.writer_seconds, "writer time budget exceeded")
            result = {"schema_version": "biohub.e23.association_capture.v1", "status": "PAIR_CAPTURE_COMPLETE",
                      "capture_only": True, "submission_authorized": False,
                      "graph_ID_mapping_complete": False, "inference_parity_verified": False,
                      "frame_counts": self.frame_counts, "dense_pairs": self.expected_pairs,
                      "writer_seconds": self.writer_seconds, "packet_bytes": self.output_bytes,
                      "records": [self.records[key] for key in sorted(self.records)]}
            encoded = _json_bytes(result)
            _require(self.output_bytes + len(encoded) <= self.limits.output_bytes, "manifest byte budget exceeded")
            with (self.root / "MANIFEST.json").open("xb") as stream:
                stream.write(encoded)
            self.closed = True
            return result
        except Exception as exc:
            self._failure(exc)
            raise
