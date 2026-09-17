Issue16 targeted corrective patch ONLY, not full file, no tests in this response. Model qwen3.8-flash subscription/no tools/no IO/no agents. Prior two broad authoring deliveries rejected. NEW concrete evidence from second clean version below: primary() never advances video.state, so reverse() ALWAYS fails for every nonempty video. start_pair's prev is tuple but uses prev.s_tgt causing every 2nd transition to fail. _reciprocal reimplements frozen helper, violating required caps. This is a narrower one-module patch request; do not repeat full file or alternate drafts. Return ONE unified diff for src/biohub/primary_consensus_observer.py against EXACT source below. Parent reviews/applies; no executed-test claims.

Fix ONLY these enumerated issues without changing any E31 choices:
1 import both map_consensus_to_raw AND primary_reciprocal_consensus_pairs from biohub.consensus_edges. delete _reciprocal entirely and call primary_reciprocal_consensus_pairs(video.forward,matrix) in reverse. It validates np.ndarray float32 finite, caps2048 per axis/1e6 product; do not change behavior.
2 Set video.state=_REVERSE after forward capture; =_SECONDARY after reverse; =_MIXED after secondary. Shapes from _matrix must equal ranges source/target counts before use.
3 start_pair: enforce t<frames-1; e_src==s_tgt; prev[3],prev[4] not attributes; append plain tuple (remove assignment expression); require coords[source,0]==t and coords[target,0]==t+1.
4 add self._failed=False; decorator must check self._failed then except ANY exception set self._failed=True and re-raise ValueError (preserve ValueError or wrap other). Thus no continued use after error. No silent fallback.
5 start_video reject any prior video lacking selected_ids (end_video isn't sufficient completion). end_video for frames1 require all coords time0.
6 pre_graph graph.node_attrs order arbitrary; don't require list order equals node_ids. Build rows keyed by node_id, ensure unique same ID set, iterate positional node_ids and compare lookup row coords to final_coords[position]. Zero-node empty graph allowed.
7 selected_graph accept empty rows, as valid solver output may be empty. stages pre_graph/selected_graph must reject duplicates: _pending takes where and picks only final_coords with graph_to_detector is None for pre_graph; for selected_graph picks graph_to_detector is not None and selected_ids is None.
8 frames_for raw node dict may include extra attrs (real GEFF adds selected/etc): require necessary keys subset, not exact set. Validate t int and node_id int (no bool equality). Keep active-transition-only output and original mapping logic. Do not alter helper cap.
9 _check_coords source coords must finite numeric (int or float), not object/bool; don't assume integers exclusively as validation final compares exact values, but preserve existing nonnegative check.
10 No new diagnostics frameworks/classes. Unified diff only, <=200 changed lines.

EXACT FILE:
"""Primary-consensus association observer for the Biohub tracking reconstruction.

A passive, stateful hook receiver. It records the reciprocal-consensus edge
decision surface for every time transition without influencing the run.
"""

from __future__ import annotations

import functools

import numpy as np

from biohub.consensus_edges import map_consensus_to_raw

CONFIG = {
    "window_size": 2,
    "downsample": (1, 4, 4),
    "scale": (1.625, 0.40625, 0.40625),
    "activation": "softmax",
    "threshold": 0.48,
    "max_parents": None,
    "max_children": None,
}

_PAIR, _PRIMARY, _REVERSE, _SECONDARY, _MIXED = (
    "pair", "primary", "reverse", "secondary", "mixed")
_NEXT = {_PAIR: _PRIMARY, _PRIMARY: _REVERSE, _REVERSE: _SECONDARY,
         _SECONDARY: _MIXED, _MIXED: _PAIR}
_NODE_KEYS = ("node_id", "t", "z", "y", "x")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _is_int(value):
    return isinstance(value, (int, np.integer)) and not isinstance(
        value, (bool, np.bool_))


def _fail_closed(where):
    def decorate(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except ValueError:
                raise
            except Exception as exc:  # fail closed with an explicit error
                raise ValueError(
                    f"{where} failed: {type(exc).__name__}: {exc}") from exc
        return wrapper
    return decorate


class _Video:
    __slots__ = ("name", "frames", "next_t", "ranges", "local_pairs", "state",
                 "forward", "final_coords", "graph_to_detector", "selected_ids")

    def __init__(self, name, frames):
        self.name = name
        self.frames = frames
        self.next_t = 0
        self.ranges = []
        self.local_pairs = {}
        self.state = _PAIR
        self.forward = None
        self.final_coords = None
        self.graph_to_detector = None
        self.selected_ids = None


class PrimaryConsensusObserver:
    """Collect consensus decisions across videos; never mutate the graphs."""

    def __init__(self):
        self._videos: dict[str, _Video] = {}
        self._active: _Video | None = None

    # ------------------------------------------------------------- video setup

    @_fail_closed("start_video")
    def start_video(self, name, frames, window_size, downsample, scale,
                    activation, *, threshold=0.48, max_parents=None,
                    max_children=None):
        _require(isinstance(name, str) and bool(name),
                 "name must be a nonempty str")
        _require(_is_int(frames) and int(frames) > 0,
                 "frames must be a positive integer")
        _require(name not in self._videos, f"duplicate video name {name!r}")
        _require(self._active is None, "previous video is still incomplete")
        _require(window_size == CONFIG["window_size"], "window_size must be 2")
        _require(tuple(downsample) == CONFIG["downsample"],
                 "downsample must be (1, 4, 4)")
        _require(tuple(scale) == CONFIG["scale"],
                 "scale must be (1.625, 0.40625, 0.40625)")
        _require(activation == CONFIG["activation"],
                 "activation must be 'softmax'")
        _require(threshold == CONFIG["threshold"], "threshold must be 0.48")
        _require(max_parents is None, "max_parents must be None")
        _require(max_children is None, "max_children must be None")
        self._active = _Video(name, int(frames))
        return self._active.state

    # ------------------------------------------------------------ transitions

    @_fail_closed("start_pair")
    def start_pair(self, t, s_src, e_src, s_tgt, e_tgt, coords):
        video = self._active_video("start_pair")
        _require(video.state == _PAIR, "start_pair requires pair-ready state")
        _require(_is_int(t) and int(t) == video.next_t,
                 f"transition sequence error: expected {video.next_t}")
        bounds = [s_src, e_src, s_tgt, e_tgt]
        _require(all(_is_int(v) for v in bounds), "range bounds must be ints")
        s_src, e_src, s_tgt, e_tgt = (int(v) for v in bounds)
        _require(0 <= s_src <= e_src, "invalid source range")
        _require(0 <= s_tgt <= e_tgt, "invalid target range")
        n = self._check_coords(coords)
        _require(e_src <= n and e_tgt <= n, "range bounds exceed coords length")
        if video.next_t == 0:
            _require(s_src == 0, "first transition must start at source 0")
        else:
            prev = video.ranges[-1]
            _require((s_src, e_src) == (prev.s_tgt, prev.e_tgt),
                     "source range must equal the previous target range")
        video.ranges.append(_Range := (t, s_src, e_src, s_tgt, e_tgt))
        video.local_pairs[video.next_t] = []
        if s_src == e_src or s_tgt == e_tgt:
            video.next_t += 1  # empty transition: no logits hooks at all
            return video.state
        video.state = _PRIMARY
        return video.state

    @staticmethod
    def _check_coords(coords):
        _require(type(coords) is np.ndarray, "coords must be an exact ndarray")
        _require(coords.ndim == 2 and coords.shape[1] == 4,
                 "coords must have shape (n, 4)")
        _require(np.issubdtype(coords.dtype, np.integer),
                 "grid coords must use an integer dtype")
        _require(bool((coords >= 0).all()), "grid coords must be nonnegative")
        return int(coords.shape[0])

    # ------------------------------------------------------------ logits hooks

    @_fail_closed("primary")
    def primary(self, logits, source, target):
        video = self._hook_state(_PRIMARY, "primary")
        video.forward = self._matrix(logits, "primary")
        return _NEXT[_PRIMARY]

    @_fail_closed("reverse")
    def reverse(self, transposed_logits):
        video = self._hook_state(_REVERSE, "reverse")
        matrix = self._matrix(transposed_logits, "reverse")
        _require(matrix.shape == video.forward.shape,
                 "reverse logits shape must match primary logits shape")
        video.local_pairs[video.next_t] = self._reciprocal(video.forward, matrix)
        video.forward = None
        return _NEXT[_REVERSE]

    @_fail_closed("secondary")
    def secondary(self, logits, source, target):
        self._hook_state(_SECONDARY, "secondary")
        return _NEXT[_SECONDARY]

    @_fail_closed("mixed")
    def mixed(self, raw, probabilities):
        video = self._hook_state(_MIXED, "mixed")
        video.next_t += 1
        video.state = _PAIR
        return video.state

    def _active_video(self, where):
        _require(self._active is not None, f"{where} needs an active video")
        return self._active

    def _hook_state(self, expected, where):
        video = self._active_video(where)
        _require(video.state == expected,
                 f"{where} requires state '{expected}', found '{video.state}'")
        return video

    @staticmethod
    def _matrix(logits, name):
        array = logits.detach().cpu().numpy()
        _require(type(array) is np.ndarray, f"{name} logits must yield ndarray")
        _require(array.dtype == np.float32, f"{name} logits must be float32")
        _require(array.ndim == 3 and array.shape[0] == 1,
                 f"{name} logits must have shape (1, ns, nt)")
        _require(np.isfinite(array).all(), f"{name} logits must be finite")
        return np.array(array[0], copy=True)

    @staticmethod
    def _reciprocal(forward, reverse):
        ns, nt = forward.shape
        if ns == 0 or nt == 0:
            return []
        hits = forward == forward.max(axis=0, keepdims=True)
        src_ok = hits & (hits.sum(axis=0, keepdims=True) == 1)
        hits = reverse == reverse.max(axis=1, keepdims=True)
        tgt_ok = hits & (hits.sum(axis=1, keepdims=True) == 1)
        rows, cols = np.nonzero(src_ok & tgt_ok)
        order = np.lexsort((cols, rows))
        return [(int(i), int(j)) for i, j in zip(rows[order], cols[order],
                                                 strict=True)]

    # ------------------------------------------------------------- graph hooks

    @_fail_closed("end_video")
    def end_video(self, coords, edges):
        video = self._active_video("end_video")
        _require(video.state == _PAIR,
                 "end_video requires no pending logits hooks")
        _require(video.next_t == video.frames - 1,
                 "end_video requires every declared transition")
        n = self._check_coords(coords)
        expected = video.ranges[-1][4] if video.frames > 1 else n
        _require(n == expected,
                 "final coords length must equal the last target range end")
        for t, (_, s_src, e_src, s_tgt, e_tgt) in enumerate(video.ranges):
            _require(bool((coords[s_src:e_src, 0] == t).all()),
                     "source block times must equal the transition index")
            _require(bool((coords[s_tgt:e_tgt, 0] == t + 1).all()),
                     "target block times must equal the following frame")
        video.final_coords = np.array(coords, copy=True)
        self._videos[video.name] = video
        self._active = None
        return video.name

    @_fail_closed("pre_graph")
    def pre_graph(self, coords, edges, node_ids, graph):
        video = self._pending("pre_graph")
        n = self._check_coords(coords)
        _require(n == video.final_coords.shape[0],
                 "pre_graph coords length must match end_video coords")
        _require(np.array_equal(coords, video.final_coords),
                 "pre_graph coords must equal the end_video coordinates")
        ids = self._as_node_ids(node_ids, n)
        rows = list(graph.node_attrs(attr_keys=list(_NODE_KEYS))
                    .iter_rows(named=True))
        _require(len(rows) == n, "graph node count must match coords count")
        _require([row["node_id"] for row in rows] == ids,
                 "graph node ids must match node_ids positionally")
        for index, row in enumerate(rows):
            got = np.asarray([row["t"], row["z"], row["y"], row["x"]])
            _require(got.shape == (4,), "graph coordinate arity mismatch")
            _require(bool((got == video.final_coords[index]).all()),
                     "graph coordinates must equal the voxel coordinates")
        video.graph_to_detector = {gid: index for index, gid in enumerate(ids)}
        return video.name

    @staticmethod
    def _as_node_ids(node_ids, expected_len):
        _require(not isinstance(node_ids, dict),
                 "node_ids is a positional list of graph ids, not a dict")
        try:
            items = list(node_ids)
        except TypeError as exc:
            raise ValueError("node_ids must be iterable") from exc
        _require(len(items) == expected_len,
                 "node_ids length must match the coords count")
        out = []
        for value in items:
            _require(_is_int(value) and int(value) >= 0,
                     "node_ids entries must be nonnegative ints")
            out.append(int(value))
        _require(len(set(out)) == len(out), "node_ids must be unique")
        return out

    @_fail_closed("selected_graph")
    def selected_graph(self, graph):
        video = self._pending("selected_graph")
        _require(video.graph_to_detector is not None,
                 "selected_graph requires pre_graph")
        rows = list(graph.node_attrs(attr_keys=list(_NODE_KEYS))
                    .iter_rows(named=True))
        _require(bool(rows), "selected graph must contain at least one node")
        selected = self._as_node_ids([row["node_id"] for row in rows],
                                     len(rows))
        _require(set(selected).issubset(video.graph_to_detector),
                 "selected nodes must be a subset of the pre-graph nodes")
        for row in rows:
            pos = video.graph_to_detector[row["node_id"]]
            got = np.asarray([row["t"], row["z"], row["y"], row["x"]])
            _require(bool((got == video.final_coords[pos]).all()),
                     "selected node coordinates must be unchanged")
        video.selected_ids = set(selected)
        return video.name

    def _pending(self, where):
        _require(self._active is None,
                 f"{where} requires end_video to close the active video")
        waiting = [v for v in self._videos.values()
                   if v.final_coords is not None
                   and v.graph_to_detector is None]
        if not waiting:
            waiting = [v for v in self._videos.values()
                       if v.final_coords is not None
                       and v.selected_ids is None]
        _require(bool(waiting), f"{where} found no video awaiting a graph")
        return waiting[-1]

    # ----------------------------------------------------------------- lookup

    @_fail_closed("frames_for")
    def frames_for(self, dataset, raw_nodes):
        _require(dataset in self._videos, f"unknown dataset {dataset!r}")
        video = self._videos[dataset]
        _require(video.selected_ids is not None,
                 f"{dataset} has not completed selected_graph")
        _require(type(raw_nodes) is dict, "raw_nodes must be an exact dict")
        mapping = video.graph_to_detector
        times = {}
        for node_id, record in raw_nodes.items():
            _require(_is_int(node_id) and int(node_id) >= 0,
                     "raw node keys must be nonnegative ints")
            node_id = int(node_id)
            _require(isinstance(record, dict), "raw node records must be dicts")
            _require(set(record) == set(_NODE_KEYS),
                     "raw node records need node_id, t, z, y, x")
            _require(record["node_id"] == node_id,
                     "raw node key must match its node_id attribute")
            _require(node_id in mapping,
                     "raw node id is outside the recorded graph mapping")
            _require(node_id in video.selected_ids,
                     "raw node id is not in the selected graph")
            want = video.final_coords[mapping[node_id]]
            got = np.asarray([record["t"], record["z"], record["y"],
                              record["x"]])
            _require(got.shape == (4,), "raw coordinate arity mismatch")
            _require(bool((got == want).all()),
                     "raw coordinates must match the recorded voxel coords")
            times[node_id] = int(record["t"])
        present = set(times.values())
        result = {}
        for t in range(video.frames - 1):
            if t not in present or t + 1 not in present:
                continue
            _, s_src, e_src, s_tgt, e_tgt = video.ranges[t]
            raw_ids = [gid for gid, stamp in times.items()
                       if stamp in (t, t + 1)]
            result[t] = map_consensus_to_raw(
                video.local_pairs[t],
                list(range(s_src, e_src)),
                list(range(s_tgt, e_tgt)),
                mapping,
                raw_ids,
            )
        return result

