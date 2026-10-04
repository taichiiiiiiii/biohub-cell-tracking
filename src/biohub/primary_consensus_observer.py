"""Primary-consensus association observer for the Biohub tracking reconstruction.

A passive, stateful hook receiver. It records the primary-only reciprocal-
consensus edge decision surface for every time transition without influencing
the run. Only primary logits are consulted; secondary/mixed/features are
accepted for protocol compatibility but never copied or stored.
"""

from __future__ import annotations

import functools
from typing import Any

import numpy as np

from biohub.consensus_edges import (
    map_consensus_to_raw,
    primary_reciprocal_consensus_pairs,
)

CONFIG = {
    "window_size": 2,
    "downsample": (1, 4, 4),
    "scale": (1.625, 0.40625, 0.40625),
    "activation": "softmax",
    "threshold": 0.48,
    "max_parents": None,
    "max_children": None,
}

_PAIR = "pair"
_PRIMARY = "primary"
_REVERSE = "reverse"
_SECONDARY = "secondary"
_MIXED = "mixed"
_NEXT = {
    _PAIR: _PRIMARY,
    _PRIMARY: _REVERSE,
    _REVERSE: _SECONDARY,
    _SECONDARY: _MIXED,
    _MIXED: _PAIR,
}
_NODE_KEYS = ("node_id", "t", "z", "y", "x")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _is_int(value: Any) -> bool:
    return isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_))


def _fail_closed(where: str):
    """Decorator that marks the observer permanently failed on any exception."""

    def decorate(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            if getattr(self, "_failed", False):
                raise ValueError("observer is permanently failed")
            try:
                return func(self, *args, **kwargs)
            except ValueError:
                self._failed = True
                raise
            except Exception as exc:
                self._failed = True
                raise ValueError(f"{where} failed: {type(exc).__name__}: {exc}") from exc

        return wrapper

    return decorate


class _Video:
    __slots__ = (
        "name",
        "frames",
        "next_t",
        "ranges",
        "local_pairs",
        "state",
        "forward",
        "final_coords",
        "graph_to_detector",
        "selected_ids",
    )

    def __init__(self, name: str, frames: int):
        self.name = name
        self.frames = frames
        self.next_t = 0
        self.ranges: list[tuple[int, int, int, int, int]] = []
        self.local_pairs: dict[int, list[tuple[int, int]]] = {}
        self.state: str = _PAIR
        self.forward: np.ndarray | None = None
        self.final_coords: np.ndarray | None = None
        self.graph_to_detector: dict[int, int] | None = None
        self.selected_ids: set[int] | None = None


class PrimaryConsensusObserver:
    """Collect primary-only consensus decisions across videos; never mutate graphs."""

    def __init__(self):
        self._videos: dict[str, _Video] = {}
        self._active: _Video | None = None
        self._failed: bool = False

    # ------------------------------------------------------------- video setup

    @_fail_closed("start_video")
    def start_video(
        self,
        name: str,
        frames: int,
        window_size: int,
        downsample: tuple[int, ...],
        scale: tuple[float, ...],
        activation: str,
        *,
        threshold: float = 0.48,
        max_parents: int | None = None,
        max_children: int | None = None,
    ) -> str:
        _require(isinstance(name, str) and bool(name), "name must be a nonempty str")
        _require(_is_int(frames) and int(frames) > 0, "frames must be a positive integer")
        _require(name not in self._videos, f"duplicate video name {name!r}")
        _require(self._active is None, "previous video is still incomplete")
        _require(window_size == CONFIG["window_size"], "window_size must be 2")
        _require(tuple(downsample) == CONFIG["downsample"], "downsample must be (1, 4, 4)")
        _require(tuple(scale) == CONFIG["scale"], "scale must be (1.625, 0.40625, 0.40625)")
        _require(activation == CONFIG["activation"], "activation must be 'softmax'")
        _require(threshold == CONFIG["threshold"], "threshold must be 0.48")
        _require(max_parents is None, "max_parents must be None")
        _require(max_children is None, "max_children must be None")
        for v in self._videos.values():
            _require(
                v.selected_ids is not None,
                "previous video has not completed selected_graph",
            )
        self._active = _Video(name, int(frames))
        return self._active.state

    # ------------------------------------------------------------ transitions

    @_fail_closed("start_pair")
    def start_pair(
        self,
        t: int,
        s_src: int,
        e_src: int,
        s_tgt: int,
        e_tgt: int,
        coords: np.ndarray,
    ) -> str:
        video = self._active_video("start_pair")
        _require(video.state == _PAIR, "start_pair requires pair-ready state")
        _require(
            _is_int(t) and int(t) == video.next_t,
            f"transition sequence error: expected {video.next_t}",
        )
        bounds = [s_src, e_src, s_tgt, e_tgt]
        _require(all(_is_int(v) for v in bounds), "range bounds must be ints")
        s_src, e_src, s_tgt, e_tgt = (int(v) for v in bounds)
        _require(0 <= s_src <= e_src == s_tgt <= e_tgt, "invalid or inconsistent range bounds")
        _require(_is_int(t) and int(t) < video.frames - 1, "t must be less than frames-1")
        n = self._check_coords(coords)
        _require(e_src <= n and e_tgt <= n, "range bounds exceed coords length")
        _require(
            bool((coords[s_src:e_src, 0] == int(t)).all()),
            "source block times must equal t",
        )
        _require(
            bool((coords[s_tgt:e_tgt, 0] == int(t) + 1).all()),
            "target block times must equal t+1",
        )
        if video.next_t == 0:
            _require(s_src == 0, "first transition must start at source 0")
        else:
            prev = video.ranges[-1]
            _require(
                (s_src, e_src) == (prev[3], prev[4]),
                "source range must equal the previous target range",
            )
        video.ranges.append((t, s_src, e_src, s_tgt, e_tgt))
        video.local_pairs[video.next_t] = []
        if s_src == e_src or s_tgt == e_tgt:
            # Empty transition: skip ALL tensor hooks, return pair-ready immediately.
            video.next_t += 1
            video.state = _PAIR
            return video.state
        video.state = _PRIMARY
        return video.state

    @staticmethod
    def _check_coords(coords: np.ndarray) -> int:
        _require(type(coords) is np.ndarray, "coords must be an exact ndarray")
        _require(coords.ndim == 2 and coords.shape[1] == 4, "coords must have shape (n, 4)")
        _require(
            np.issubdtype(coords.dtype, np.floating) or np.issubdtype(coords.dtype, np.integer),
            "grid coords must use a numeric dtype",
        )
        _require(not np.issubdtype(coords.dtype, np.bool_), "grid coords must not be bool")
        _require(not np.issubdtype(coords.dtype, np.complexfloating), "grid coords must not be complex")
        _require(coords.dtype != object, "grid coords must not be object dtype")
        _require(bool(np.isfinite(coords).all()), "grid coords must be finite")
        _require(bool((coords >= 0).all()), "grid coords must be nonnegative")
        return int(coords.shape[0])

    # ------------------------------------------------------------ logits hooks

    @_fail_closed("primary")
    def primary(self, logits: Any, source: Any, target: Any) -> str:
        video = self._hook_state(_PRIMARY, "primary")
        matrix = self._matrix(logits, "primary")
        r = video.ranges[-1]
        _require(matrix.shape == (r[2] - r[1], r[4] - r[3]), "primary logits shape must match current ranges")
        video.forward = matrix
        video.state = _REVERSE
        return video.state

    @_fail_closed("reverse")
    def reverse(self, transposed_logits: Any) -> str:
        video = self._hook_state(_REVERSE, "reverse")
        matrix = self._matrix(transposed_logits, "reverse")
        fwd = video.forward
        _require(fwd is not None, "reverse called without forward")
        _require(
            matrix.shape == fwd.shape,
            "reverse logits shape must match primary logits shape",
        )
        video.local_pairs[video.next_t] = primary_reciprocal_consensus_pairs(fwd, matrix)
        video.forward = None
        video.state = _SECONDARY
        return video.state

    @_fail_closed("secondary")
    def secondary(self, logits: Any, source: Any, target: Any) -> str:
        video = self._hook_state(_SECONDARY, "secondary")
        video.state = _MIXED
        return video.state

    @_fail_closed("mixed")
    def mixed(self, raw: Any, probabilities: Any) -> str:
        video = self._hook_state(_MIXED, "mixed")
        video.next_t += 1
        video.state = _PAIR
        return video.state

    def _active_video(self, where: str) -> _Video:
        _require(self._active is not None, f"{where} needs an active video")
        return self._active

    def _hook_state(self, expected: str, where: str) -> _Video:
        video = self._active_video(where)
        _require(
            video.state == expected,
            f"{where} requires state '{expected}', found '{video.state}'",
        )
        return video

    @staticmethod
    def _matrix(logits: Any, name: str) -> np.ndarray:
        array = logits.detach().cpu().numpy()
        _require(type(array) is np.ndarray, f"{name} logits must yield ndarray")
        _require(array.dtype == np.float32, f"{name} logits must be float32")
        _require(
            array.ndim == 3 and array.shape[0] == 1,
            f"{name} logits must have shape (1, ns, nt)",
        )
        _require(np.isfinite(array).all(), f"{name} logits must be finite")
        return np.array(array[0], copy=True)

    # ------------------------------------------------------------- graph hooks

    @_fail_closed("end_video")
    def end_video(self, coords: np.ndarray, edges: Any) -> str:
        video = self._active_video("end_video")
        _require(video.state == _PAIR, "end_video requires no pending logits hooks")
        _require(
            video.next_t == video.frames - 1,
            "end_video requires every declared transition",
        )
        n = self._check_coords(coords)
        if video.frames > 1:
            expected = video.ranges[-1][4]
        else:
            _require(bool((coords[:, 0] == 0).all()), "single-frame coords times must equal zero")
            expected = n
        _require(n == expected, "final coords length must equal the last target range end")
        for t_val, s_src, e_src, s_tgt, e_tgt in video.ranges:
            _require(
                bool((coords[s_src:e_src, 0] == t_val).all()),
                "source block times must equal the transition index",
            )
            _require(
                bool((coords[s_tgt:e_tgt, 0] == t_val + 1).all()),
                "target block times must equal the following frame",
            )
        video.final_coords = np.array(coords, copy=True)
        self._videos[video.name] = video
        self._active = None
        return video.name

    @_fail_closed("pre_graph")
    def pre_graph(
        self,
        coords: np.ndarray,
        edges: Any,
        node_ids: list[int],
        graph: Any,
    ) -> str:
        video = self._pending("pre_graph")
        n = self._check_coords(coords)
        _require(
            n == video.final_coords.shape[0],
            "pre_graph coords length must match end_video coords",
        )
        _require(
            np.array_equal(coords, video.final_coords),
            "pre_graph coords must equal the end_video coordinates",
        )
        ids = self._as_node_ids(node_ids, n)
        rows = list(graph.node_attrs(attr_keys=list(_NODE_KEYS)).iter_rows(named=True))
        _require(len(rows) == n, "graph node count must match coords count")
        by_id = {row["node_id"]: row for row in rows}
        _require(len(by_id) == n, "duplicate node ids in graph")
        _require(set(by_id) == set(ids), "graph node ids must equal node_ids set")
        for index, gid in enumerate(ids):
            row = by_id[gid]
            got = np.asarray([row["t"], row["z"], row["y"], row["x"]])
            _require(got.shape == (4,), "graph coordinate arity mismatch")
            _require(
                bool((got == video.final_coords[index]).all()),
                "graph coordinates must equal the voxel coordinates",
            )
        video.graph_to_detector = {gid: idx for idx, gid in enumerate(ids)}
        return video.name

    @staticmethod
    def _as_node_ids(node_ids: Any, expected_len: int) -> list[int]:
        _require(
            not isinstance(node_ids, dict),
            "node_ids is a positional list of graph ids, not a dict",
        )
        try:
            items = list(node_ids)
        except TypeError as exc:
            raise ValueError("node_ids must be iterable") from exc
        _require(
            len(items) == expected_len,
            "node_ids length must match the coords count",
        )
        out: list[int] = []
        for value in items:
            _require(
                _is_int(value) and int(value) >= 0,
                "node_ids entries must be nonnegative ints",
            )
            out.append(int(value))
        _require(len(set(out)) == len(out), "node_ids must be unique")
        return out

    @_fail_closed("selected_graph")
    def selected_graph(self, graph: Any) -> str:
        video = self._pending("selected_graph")
        _require(
            video.graph_to_detector is not None,
            "selected_graph requires pre_graph",
        )
        _require(
            video.selected_ids is None,
            "selected_graph already completed for this video",
        )
        rows = list(graph.node_attrs(attr_keys=list(_NODE_KEYS)).iter_rows(named=True))
        # Empty selected graph is allowed.
        selected = self._as_node_ids([row["node_id"] for row in rows], len(rows))
        _require(
            set(selected).issubset(video.graph_to_detector),
            "selected nodes must be a subset of the pre-graph nodes",
        )
        for row in rows:
            pos = video.graph_to_detector[row["node_id"]]
            got = np.asarray([row["t"], row["z"], row["y"], row["x"]])
            _require(
                bool((got == video.final_coords[pos]).all()),
                "selected node coordinates must be unchanged",
            )
        video.selected_ids = set(selected)
        return video.name

    def _pending(self, where: str) -> _Video:
        _require(
            self._active is None,
            f"{where} requires end_video to close the active video",
        )
        if where == "pre_graph":
            waiting = [v for v in self._videos.values() if v.final_coords is not None and v.graph_to_detector is None]
        else:
            waiting = [v for v in self._videos.values() if v.graph_to_detector is not None and v.selected_ids is None]
        _require(not any(w.selected_ids is not None for w in waiting), "already completed or no video awaiting graph")
        _require(bool(waiting), "already completed or no video awaiting graph")
        return waiting[-1]

    # ----------------------------------------------------------------- lookup

    @_fail_closed("frames_for")
    def frames_for(self, dataset: str, raw_nodes: dict[int, dict[str, Any]]) -> dict[int, list[tuple[int, int]]]:
        _require(dataset in self._videos, f"unknown dataset {dataset!r}")
        video = self._videos[dataset]
        _require(
            video.selected_ids is not None,
            f"{dataset} has not completed selected_graph",
        )
        _require(type(raw_nodes) is dict, "raw_nodes must be an exact dict")
        mapping = video.graph_to_detector
        times: dict[int, int] = {}
        for node_id, record in raw_nodes.items():
            _require(
                _is_int(node_id) and int(node_id) >= 0,
                "raw node keys must be nonnegative ints",
            )
            node_id = int(node_id)
            _require(isinstance(record, dict), "raw node records must be dicts")
            _require(
                set(record) >= set(_NODE_KEYS),
                "raw node records need at least node_id, t, z, y, x",
            )
            _require(
                _is_int(record["node_id"]) and _is_int(record["t"]),
                "raw node_id and t must be ints",
            )
            _require(
                record["node_id"] == node_id,
                "raw node key must match its node_id attribute",
            )
            _require(
                node_id in mapping,
                "raw node id is outside the recorded graph mapping",
            )
            _require(
                node_id in video.selected_ids,
                "raw node id is not in the selected graph",
            )
            want = video.final_coords[mapping[node_id]]
            got = np.asarray([record["t"], record["z"], record["y"], record["x"]])
            _require(got.shape == (4,), "raw coordinate arity mismatch")
            _require(
                bool((got == want).all()),
                "raw coordinates must match the recorded voxel coords",
            )
            times[node_id] = int(record["t"])
        present = set(times.values())
        result: dict[int, list[tuple[int, int]]] = {}
        for t_idx in range(video.frames - 1):
            if t_idx not in present or t_idx + 1 not in present:
                continue
            _, s_src, e_src, s_tgt, e_tgt = video.ranges[t_idx]
            raw_ids = [gid for gid, stamp in times.items() if stamp in (t_idx, t_idx + 1)]
            result[t_idx] = map_consensus_to_raw(
                video.local_pairs[t_idx],
                list(range(s_src, e_src)),
                list(range(s_tgt, e_tgt)),
                mapping,
                raw_ids,
            )
        return result
