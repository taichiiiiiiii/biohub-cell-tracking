Issue17 and Issue16; active parent Goal; user2026-09-14 explicitly switches implementation to qwen3.8-max subscription. You are IMPLEMENTER not evaluator. No tools, filesystem, edits, network, agents or test execution. Return final code only, no alternate drafts: complete src/biohub/primary_consensus_observer.py, complete tests/test_primary_consensus_observer.py, and a unified diff parametrizing existing canonical-authoring routing test (inline below) over qwen3.8-flash and qwen3.8-max with expected argv. For max assert prompt contains 'User override 2026-09-14' and 'Authoring-only tasks'. Keep noncanonical Max rejection tests. Parent applies/tests.
Current launcher explicitly accepts canonical --parent-reviewed --cloud-only --cloud-model qwen3.8-max, uses biohub_implementer.instructions.md, read-only authoring/zero retries/no fallback. No launcher patch needed.

Repair the REJECTED UNAPPLIED DRAFT below, compact implementation, no invented helper APIs.
Goal passive streaming observer at frozen E23 predictor hooks; compute E31 primary-only consensus on complete pre-solver detector matrices. Import AND CALL existing biohub.consensus_edges.primary_reciprocal_consensus_pairs and map_consensus_to_raw. Do not reimplement helpers or relax their float32/finite/shape/cap checks. Only primary logits consulted; mixed/secondary/features ignored and not copied. No GT/train reference/preknown video names, no IO/dense packet storage.

Contracts:
- same hook signatures as draft. Frozen window_size2,downsample(1,4,4),scale(1.625,.40625,.40625),activation softmax,threshold.48,max_parents/max_children None.
- frames positive int; each t0..frames-2 once. Empty ranges skip ALL tensor hooks and return pair-ready immediately; nonempty primary->reverse->secondary->mixed, actually UPDATE state at every call. Exception marks observer permanently failed; decorator MUST pass self to wrapped method.
- start_pair finite numeric nonbool coords(n,4) grid; 0<=s_src<=e_src==s_tgt<=e_tgt<=len(coords), first source start0; later source range equals previous TARGET range using tuple indices not attributes. Times match t and t+1, t must below frames-1. Copy forward .detach().cpu().numpy() validated batch1 float32 finite with (ns,nt) exactly matching offsets. reverse is ALREADY transposed to same source×target shape; don't transpose again. Call helper before any solver subset. Store local pair tuples and ranges, free forward after reverse.
- end_video all transitions complete then copy final ORIGINAL voxel coords; counts/times must agree, frames1 allowed no transitions and time0. pre_graph coords compare by values not identity.
- pre_graph node_ids POSITIONAL list [101,7,55,900] means graph_to_detector={101:0,7:1,55:2,900:3}, arbitrary graph table row order, validate uniqueness/sameID set and exact per-ID coordinates. IDs int/np.integer nonnegative notbool. Never infer IDs from coords. Graph API .node_attrs(attr_keys=["node_id","t","z","y","x"]).iter_rows(named=True).
- selected_graph accepts EMPTY or subset of pregraph, checks coords unchanged, keeps full mapping plus selected IDs separately. No new video until current selected_graph complete. Reject duplicate hooks/names. Preserve old video state querying after second.
- frames_for(dataset,raw_nodes) exact dict id->{node_id,t,z,y,x,...extra attrs} validates keys+attrs ints for id/t and exact coords, IDs belong selected subset. Legitimate subsets allowed, don't require all detector nodes survive. For active adjacent RAW times only, map stored FULL-detector helper pairs through existing map_consensus_to_raw(pairs,range source ids list,range target list,graph_to_detector,list(raw_nodes)). Return exact dict active keys including [] and no inactive keys. Unknown/incomplete/malformed inputs fail. No lossy int conversion of fractional coords.
- No input/model/graph mutations; sparse per-video memory only. No features copied, no dense logits retained across pairs.

Known draft bugs to remove: states returned without assignment; tuple .s_tgt access; helper reimplementation; no shape/range checks; graph table order dependence; empty graph rejection; failure decorator not sticky; doesn't prevent new video before graph hooks.
Tests fake tensor .detach/.cpu/.numpy MUST preserve input dtype, not cast float64 (invalid test would mask bug). FakeGraph supports filtered attrs and arbitrary row order. Fixtures: simple frames2, exactly2source+2target coords, IDs positional list, raw values generated from actual final coords (grid * [1,1,4,4]); no handcoded inconsistent values. Nonsquare3source+5target=8coords with targetoffset3 and reverse shape3x5 ALREADY transposed. Empty middle frame frames3 with times[0,0,2,2], transitions ranges(0,2,2,2) then(2,2,2,4), NO tensor hooks. Cover helper equivalence, subset mapping, ties, float64/nonfinite/badshape, failed state, multivideo DIFFERENT IDs, empty selected, coords mutation detection, required extra attrs, duplicate/unknown/incomplete/stages. Fresh observer for each invalid case. Never expect pair if raw only has sources. Do not query completed cache before end_video. Keep module/tests small, avoid frameworks. Return only FINAL version; do not claim tests run.

REJECTED DRAFT:
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


ACTUAL HELPER AND ROUTING TEST:
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
def test_canonical_authoring_preserves_dirty_input(harness: Harness) -> None:
    run("git", "-C", harness.root, "switch", "-c", "feature/author")
    original = harness.root / "tracked.txt"
    original.write_text("user WIP\n")
    result = harness.invoke("--parent-reviewed", "--cloud-only", "--cloud-model", "qwen3.8-flash",
                            target=harness.root)
    assert result.returncode == 0, result.stderr.decode()
    argv = queue_argv(harness)
    assert argv[:3] == ["--cloud-only", "--cloud-model", "qwen3.8-flash"]
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "project_doc_max_bytes=0" in argv
    assert 'features.shell_tool=false' in argv
    assert 'features.unified_exec=false' in argv
    assert original.read_text() == "user WIP\n"
    assert not (harness.root / ".git/biohub-implement.lock").exists()



