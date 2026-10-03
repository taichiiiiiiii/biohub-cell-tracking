"""Tests for PrimaryConsensusObserver."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from biohub.primary_consensus_observer import PrimaryConsensusObserver

# ---------------------------------------------------------------------------
# Fake tensor that preserves input dtype through detach/cpu/numpy chain
# ---------------------------------------------------------------------------


class _FakeTensor:
    """Mimics a torch tensor; .detach().cpu().numpy() returns the original array."""

    def __init__(self, array: np.ndarray):
        self._array = array

    def detach(self) -> _FakeTensor:
        return self

    def cpu(self) -> _FakeTensor:
        return self

    def numpy(self) -> np.ndarray:
        return self._array


def _make_logits(ns: int, nt: int, *, dtype=np.float32) -> _FakeTensor:
    rng = np.random.default_rng(42)
    data = rng.random((1, ns, nt), dtype=dtype).astype(dtype, copy=False)
    return _FakeTensor(data)


def _make_unique_logits(ns: int, nt: int) -> tuple[_FakeTensor, _FakeTensor]:
    """Create forward/reverse with exactly one known reciprocal pair (0, 0)."""
    fwd = np.zeros((1, ns, nt), dtype=np.float32)
    rev = np.zeros((1, ns, nt), dtype=np.float32)
    # Make (0,0) the unique max in column 0 of fwd and row 0 of rev.
    fwd[0, 0, 0] = 1.0
    rev[0, 0, 0] = 1.0
    # Fill remaining with smaller distinct values so no ties.
    val = 0.1
    for i in range(ns):
        for j in range(nt):
            if i == 0 and j == 0:
                continue
            fwd[0, i, j] = val
            val += 0.001
    val = 0.1
    for i in range(ns):
        for j in range(nt):
            if i == 0 and j == 0:
                continue
            rev[0, i, j] = val
            val += 0.001
    return _FakeTensor(fwd), _FakeTensor(rev)


# ---------------------------------------------------------------------------
# Fake graph supporting filtered attrs and arbitrary row order
# ---------------------------------------------------------------------------


class _FakeGraphAttrs:
    def __init__(self, rows: list[dict[str, Any]], attr_keys: list[str]):
        self._rows = rows
        self._keys = attr_keys

    def iter_rows(self, *, named: bool = True):
        for row in self._rows:
            if named:
                yield {k: row[k] for k in self._keys}
            else:
                yield tuple(row[k] for k in self._keys)


class FakeGraph:
    """Minimal graph stub supporting node_attrs(attr_keys=...).iter_rows(named=True)."""

    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = list(rows)

    def node_attrs(self, *, attr_keys: list[str]) -> _FakeGraphAttrs:
        return _FakeGraphAttrs(self._rows, list(attr_keys))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def observer():
    return PrimaryConsensusObserver()


def _simple_frames2_coords():
    """2 frames, 2 source + 2 target = 4 coords. Times [0,0,1,1]."""
    return np.array(
        [[0, 0, 0, 0], [0, 0, 1, 1], [1, 0, 2, 2], [1, 0, 3, 3]],
        dtype=np.int64,
    )


def _nonsquare_coords():
    """3 source + 5 target = 8 coords. Target offset 3. Times [0,0,0,1,1,1,1,1]."""
    src = np.array([[0, 0, i, i] for i in range(3)], dtype=np.int64)
    tgt = np.array([[1, 0, i + 3, i + 3] for i in range(5)], dtype=np.int64)
    return np.vstack([src, tgt])


def _empty_middle_frames3_coords():
    """3 frames. Frame 0: 2 nodes, frame 1: 0 nodes, frame 2: 2 nodes.
    Transitions: (0,2,2,2) then (2,2,2,4). Total 4 coords.
    """
    return np.array(
        [
            [0, 0, 0, 0],
            [0, 0, 1, 1],
            [2, 0, 2, 2],
            [2, 0, 3, 3],
        ],
        dtype=np.int64,
    )


def _ids_simple():
    return [101, 7, 55, 900]


def _ids_nonsquare():
    return [10, 20, 30, 40, 50, 60, 70, 80]


def _ids_empty_middle():
    return [100, 200, 300, 400]


def _build_graph(coords, node_ids, row_order=None):
    """Build a FakeGraph from coords and positional node_ids.
    row_order allows arbitrary table ordering.
    """
    rows = []
    for idx, nid in enumerate(node_ids):
        rows.append(
            {
                "node_id": nid,
                "t": int(coords[idx, 0]),
                "z": int(coords[idx, 1]),
                "y": int(coords[idx, 2]),
                "x": int(coords[idx, 3]),
            }
        )
    if row_order is not None:
        rows = [rows[i] for i in row_order]
    return FakeGraph(rows)


def _run_full_simple(observer: PrimaryConsensusObserver, name="vid"):
    """Run a complete simple 2-frame video and return the observer."""
    coords = _simple_frames2_coords()
    ids = _ids_simple()
    assert observer.start_video(name, 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax") == "pair"
    assert observer.start_pair(0, 0, 2, 2, 4, coords) == "primary"
    fwd, rev = _make_unique_logits(2, 2)
    assert observer.primary(fwd, None, None) == "reverse"
    assert observer.reverse(rev) == "secondary"
    assert observer.secondary(None, None, None) == "mixed"
    assert observer.mixed(None, None) == "pair"
    assert observer.end_video(coords, None) == name
    graph = _build_graph(coords, ids)
    assert observer.pre_graph(coords, None, ids, graph) == name
    sel_graph = _build_graph(coords, ids)
    assert observer.selected_graph(sel_graph) == name
    return observer


def _raw_nodes_from_coords(coords, node_ids, indices):
    """Generate raw_nodes dict from final coords for given node indices."""
    out = {}
    for idx in indices:
        nid = node_ids[idx]
        out[nid] = {
            "node_id": nid,
            "t": int(coords[idx, 0]),
            "z": int(coords[idx, 1]),
            "y": int(coords[idx, 2]),
            "x": int(coords[idx, 3]),
        }
    return out


# ---------------------------------------------------------------------------
# Helper equivalence
# ---------------------------------------------------------------------------


def test_helper_equivalence_primary_only():
    """Observer uses primary_reciprocal_consensus_pairs, not reimplemented logic."""
    from biohub.consensus_edges import map_consensus_to_raw, primary_reciprocal_consensus_pairs

    fwd_np = np.array([[1.0, 0.2], [0.3, 0.8]], dtype=np.float32)
    rev_np = np.array([[0.9, 0.1], [0.2, 0.7]], dtype=np.float32)
    expected = primary_reciprocal_consensus_pairs(fwd_np, rev_np)
    obs = PrimaryConsensusObserver()
    coords = _simple_frames2_coords()
    obs.start_video("h", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs.start_pair(0, 0, 2, 2, 4, coords)
    obs.primary(_FakeTensor(fwd_np.reshape(1, 2, 2)), None, None)
    obs.reverse(_FakeTensor(rev_np.reshape(1, 2, 2)))
    obs.secondary(None, None, None)
    obs.mixed(None, None)
    obs.end_video(coords, None)
    ids = _ids_simple()
    graph = _build_graph(coords, ids)
    obs.pre_graph(coords, None, ids, graph)
    obs.selected_graph(_build_graph(coords, ids))
    raw = _raw_nodes_from_coords(coords, ids, [0, 1, 2, 3])
    result = obs.frames_for("h", raw)
    assert 0 in result
    assert result[0] == map_consensus_to_raw(expected, [0, 1], [2, 3], dict(zip(ids, range(4), strict=True)), list(raw))


def test_start_pair_incorrect_times_rejected():
    """start_pair rejects when source/target block times don't match t/t+1."""
    obs = PrimaryConsensusObserver()
    coords = _simple_frames2_coords().copy()
    # Corrupt source block time for the pair at t=0
    coords[0, 0] = 99
    obs.start_video("bad_t", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    with pytest.raises(ValueError, match="source block times must equal t"):
        obs.start_pair(0, 0, 2, 2, 4, coords)
    assert obs._failed is True


def test_single_frame_coords_times_must_equal_zero():
    obs = PrimaryConsensusObserver()
    obs.start_video("single", 1, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    with pytest.raises(ValueError, match="single-frame coords times must equal zero"):
        obs.end_video(np.array([[1, 0, 0, 0]], dtype=np.int64), None)
    assert obs._failed

    empty = PrimaryConsensusObserver()
    empty.start_video("empty", 1, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    assert empty.end_video(np.empty((0, 4), dtype=np.int64), None) == "empty"


@pytest.mark.parametrize("field", ["node_id", "t"])
@pytest.mark.parametrize("badvalue", [1.5, True])
def test_frames_for_rejects_non_int_node_id_or_t(field, badvalue):
    obs = _run_full_simple(PrimaryConsensusObserver())
    coords = _simple_frames2_coords()
    ids = _ids_simple()
    assert ids == [101, 7, 55, 900]
    raw = _raw_nodes_from_coords(coords, ids, [0, 1, 2, 3])
    raw[101][field] = badvalue
    with pytest.raises(ValueError, match="raw node_id and t must be ints"):
        obs.frames_for("vid", raw)
    assert obs._failed


# ---------------------------------------------------------------------------
# Basic flow
# ---------------------------------------------------------------------------


def test_simple_flow(observer):
    _run_full_simple(observer)
    coords = _simple_frames2_coords()
    ids = _ids_simple()
    raw = _raw_nodes_from_coords(coords, ids, [0, 1, 2, 3])
    result = observer.frames_for("vid", raw)
    assert isinstance(result, dict)
    assert 0 in result


def test_empty_ranges_skip_hooks(observer):
    """Empty middle frame: no tensor hooks called at all."""
    coords = _empty_middle_frames3_coords()
    ids = _ids_empty_middle()
    observer.start_video("e", 3, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    # Transition 0: source [0,2), target [2,2) -> empty target
    assert observer.start_pair(0, 0, 2, 2, 2, coords) == "pair"
    # Transition 1: source [2,2), target [2,4) -> empty source
    assert observer.start_pair(1, 2, 2, 2, 4, coords) == "pair"
    observer.end_video(coords, None)
    graph = _build_graph(coords, ids)
    observer.pre_graph(coords, None, ids, graph)
    observer.selected_graph(_build_graph(coords, ids))
    raw = _raw_nodes_from_coords(coords, ids, [0, 1, 2, 3])
    result = observer.frames_for("e", raw)
    # Both transitions empty -> no active adjacent raw times produce pairs
    assert result == {}


def test_nonsquare_reverse_already_transposed(observer):
    """3 source x 5 target; reverse shape is (1,3,5) already transposed."""
    coords = _nonsquare_coords()
    ids = _ids_nonsquare()
    observer.start_video("ns", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    assert observer.start_pair(0, 0, 3, 3, 8, coords) == "primary"
    fwd = _make_logits(3, 5)
    rev = _make_logits(3, 5)  # Already transposed to source x target
    observer.primary(fwd, None, None)
    observer.reverse(rev)
    observer.secondary(None, None, None)
    observer.mixed(None, None)
    observer.end_video(coords, None)
    graph = _build_graph(coords, ids)
    observer.pre_graph(coords, None, ids, graph)
    observer.selected_graph(_build_graph(coords, ids))
    raw = _raw_nodes_from_coords(coords, ids, list(range(8)))
    result = observer.frames_for("ns", raw)
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Subset mapping
# ---------------------------------------------------------------------------


def test_subset_mapping(observer):
    """Selected graph is a subset; frames_for only returns selected nodes."""
    obs3 = PrimaryConsensusObserver()
    coords3 = _simple_frames2_coords()
    ids3 = _ids_simple()
    obs3.start_video("s3", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs3.start_pair(0, 0, 2, 2, 4, coords3)
    fwd, rev = _make_unique_logits(2, 2)
    obs3.primary(fwd, None, None)
    obs3.reverse(rev)
    obs3.secondary(None, None, None)
    obs3.mixed(None, None)
    obs3.end_video(coords3, None)
    obs3.pre_graph(coords3, None, ids3, _build_graph(coords3, ids3))
    obs3.selected_graph(_build_graph(coords3[[0, 2]], [ids3[0], ids3[2]]))
    raw = _raw_nodes_from_coords(coords3, ids3, [0, 2])
    result = obs3.frames_for("s3", raw)
    assert result == {0: [(ids3[0], ids3[2])]}


def test_empty_selected_graph(observer):
    """Empty selected graph is allowed; frames_for returns empty results."""
    coords = _simple_frames2_coords()
    ids = _ids_simple()
    observer.start_video("es", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    observer.start_pair(0, 0, 2, 2, 4, coords)
    fwd, rev = _make_unique_logits(2, 2)
    observer.primary(fwd, None, None)
    observer.reverse(rev)
    observer.secondary(None, None, None)
    observer.mixed(None, None)
    observer.end_video(coords, None)
    observer.pre_graph(coords, None, ids, _build_graph(coords, ids))
    observer.selected_graph(FakeGraph([]))
    raw = _raw_nodes_from_coords(coords, ids, [])
    result = observer.frames_for("es", raw)
    assert result == {}


# ---------------------------------------------------------------------------
# Ties excluded
# ---------------------------------------------------------------------------


def test_ties_excluded(observer):
    """Tied maxima produce no pairs."""
    coords = _simple_frames2_coords()
    ids = _ids_simple()
    observer.start_video("tie", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    observer.start_pair(0, 0, 2, 2, 4, coords)
    # All equal -> ties everywhere
    tie_fwd = _FakeTensor(np.ones((1, 2, 2), dtype=np.float32))
    tie_rev = _FakeTensor(np.ones((1, 2, 2), dtype=np.float32))
    observer.primary(tie_fwd, None, None)
    observer.reverse(tie_rev)
    observer.secondary(None, None, None)
    observer.mixed(None, None)
    observer.end_video(coords, None)
    observer.pre_graph(coords, None, ids, _build_graph(coords, ids))
    observer.selected_graph(_build_graph(coords, ids))
    raw = _raw_nodes_from_coords(coords, ids, [0, 1, 2, 3])
    result = observer.frames_for("tie", raw)
    assert result.get(0, []) == []


# ---------------------------------------------------------------------------
# Validation failures (fresh observer each)
# ---------------------------------------------------------------------------


def test_float64_logits_rejected():
    obs = PrimaryConsensusObserver()
    coords = _simple_frames2_coords()
    obs.start_video("f64", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs.start_pair(0, 0, 2, 2, 4, coords)
    bad = _FakeTensor(np.ones((1, 2, 2), dtype=np.float64))
    with pytest.raises(ValueError, match="float32"):
        obs.primary(bad, None, None)


def test_nonfinite_logits_rejected():
    obs = PrimaryConsensusObserver()
    coords = _simple_frames2_coords()
    obs.start_video("nf", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs.start_pair(0, 0, 2, 2, 4, coords)
    bad = _FakeTensor(np.full((1, 2, 2), np.inf, dtype=np.float32))
    with pytest.raises(ValueError, match="finite"):
        obs.primary(bad, None, None)


def test_bad_shape_logits_rejected():
    obs = PrimaryConsensusObserver()
    coords = _simple_frames2_coords()
    obs.start_video("bs", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs.start_pair(0, 0, 2, 2, 4, coords)
    bad = _FakeTensor(np.ones((1, 3, 2), dtype=np.float32))
    with pytest.raises(ValueError, match="shape"):
        obs.primary(bad, None, None)


def test_failed_state_permanent():
    obs = PrimaryConsensusObserver()
    coords = _simple_frames2_coords()
    obs.start_video("fail", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs.start_pair(0, 0, 2, 2, 4, coords)
    bad = _FakeTensor(np.ones((1, 2, 2), dtype=np.float64))
    with pytest.raises(ValueError):
        obs.primary(bad, None, None)
    # Subsequent calls must also fail
    with pytest.raises(ValueError, match="permanently failed"):
        obs.reverse(_make_logits(2, 2))


def test_duplicate_video_rejected(observer):
    _run_full_simple(observer, "dup")
    with pytest.raises(ValueError, match="duplicate"):
        observer.start_video("dup", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")


def test_new_video_before_graph_complete_rejected():
    obs = PrimaryConsensusObserver()
    coords = _simple_frames2_coords()
    obs.start_video("v1", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs.start_pair(0, 0, 2, 2, 4, coords)
    fwd, rev = _make_unique_logits(2, 2)
    obs.primary(fwd, None, None)
    obs.reverse(rev)
    obs.secondary(None, None, None)
    obs.mixed(None, None)
    obs.end_video(coords, None)
    # Don't call pre_graph/selected_graph; try starting new video
    with pytest.raises(ValueError, match="selected_graph"):
        obs.start_video("v2", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")


def test_coords_mutation_detected():
    obs = PrimaryConsensusObserver()
    coords = _simple_frames2_coords()
    ids = _ids_simple()
    obs.start_video("mut", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs.start_pair(0, 0, 2, 2, 4, coords)
    fwd, rev = _make_unique_logits(2, 2)
    obs.primary(fwd, None, None)
    obs.reverse(rev)
    obs.secondary(None, None, None)
    obs.mixed(None, None)
    obs.end_video(coords, None)
    mutated = coords.copy()
    mutated[0, 1] = 999
    with pytest.raises(ValueError, match="equal"):
        obs.pre_graph(mutated, None, ids, _build_graph(mutated, ids))


def test_unknown_dataset_rejected():
    obs = PrimaryConsensusObserver()
    with pytest.raises(ValueError, match="unknown dataset"):
        obs.frames_for("nonexistent", {})


def test_incomplete_selected_graph_rejected():
    obs = PrimaryConsensusObserver()
    coords = _simple_frames2_coords()
    ids = _ids_simple()
    obs.start_video("inc", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs.start_pair(0, 0, 2, 2, 4, coords)
    fwd, rev = _make_unique_logits(2, 2)
    obs.primary(fwd, None, None)
    obs.reverse(rev)
    obs.secondary(None, None, None)
    obs.mixed(None, None)
    obs.end_video(coords, None)
    obs.pre_graph(coords, None, ids, _build_graph(coords, ids))
    # Don't call selected_graph
    raw = _raw_nodes_from_coords(coords, ids, [0, 1, 2, 3])
    with pytest.raises(ValueError, match="selected_graph"):
        obs.frames_for("inc", raw)


def test_required_extra_attrs_accepted():
    """Extra attributes beyond _NODE_KEYS are allowed in raw_nodes."""
    obs = PrimaryConsensusObserver()
    coords = _simple_frames2_coords()
    ids = _ids_simple()
    obs.start_video("extra", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs.start_pair(0, 0, 2, 2, 4, coords)
    fwd, rev = _make_unique_logits(2, 2)
    obs.primary(fwd, None, None)
    obs.reverse(rev)
    obs.secondary(None, None, None)
    obs.mixed(None, None)
    obs.end_video(coords, None)
    obs.pre_graph(coords, None, ids, _build_graph(coords, ids))
    obs.selected_graph(_build_graph(coords, ids))
    raw = _raw_nodes_from_coords(coords, ids, [0, 1, 2, 3])
    # Add extra attribute
    for v in raw.values():
        v["score"] = 0.9
    result = obs.frames_for("extra", raw)
    assert isinstance(result, dict)


def test_duplicate_selected_graph_rejected():
    obs = PrimaryConsensusObserver()
    coords = _simple_frames2_coords()
    ids = _ids_simple()
    obs.start_video("dsel", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs.start_pair(0, 0, 2, 2, 4, coords)
    fwd, rev = _make_unique_logits(2, 2)
    obs.primary(fwd, None, None)
    obs.reverse(rev)
    obs.secondary(None, None, None)
    obs.mixed(None, None)
    obs.end_video(coords, None)
    obs.pre_graph(coords, None, ids, _build_graph(coords, ids))
    obs.selected_graph(_build_graph(coords, ids))
    with pytest.raises(ValueError, match="already completed"):
        obs.selected_graph(_build_graph(coords, ids))


def test_multivideo_different_ids():
    """Two videos with different ID sets don't interfere."""
    obs = PrimaryConsensusObserver()
    coords1 = _simple_frames2_coords()
    ids1 = [101, 7, 55, 900]
    obs.start_video("v1", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs.start_pair(0, 0, 2, 2, 4, coords1)
    fwd, rev = _make_unique_logits(2, 2)
    obs.primary(fwd, None, None)
    obs.reverse(rev)
    obs.secondary(None, None, None)
    obs.mixed(None, None)
    obs.end_video(coords1, None)
    obs.pre_graph(coords1, None, ids1, _build_graph(coords1, ids1))
    obs.selected_graph(_build_graph(coords1, ids1))

    coords2 = _simple_frames2_coords()
    ids2 = [1001, 2002, 3003, 4004]
    obs.start_video("v2", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs.start_pair(0, 0, 2, 2, 4, coords2)
    fwd2, rev2 = _make_unique_logits(2, 2)
    obs.primary(fwd2, None, None)
    obs.reverse(rev2)
    obs.secondary(None, None, None)
    obs.mixed(None, None)
    obs.end_video(coords2, None)
    obs.pre_graph(coords2, None, ids2, _build_graph(coords2, ids2))
    obs.selected_graph(_build_graph(coords2, ids2))

    raw1 = _raw_nodes_from_coords(coords1, ids1, [0, 1, 2, 3])
    raw2 = _raw_nodes_from_coords(coords2, ids2, [0, 1, 2, 3])
    r1 = obs.frames_for("v1", raw1)
    r2 = obs.frames_for("v2", raw2)
    assert isinstance(r1, dict)
    assert isinstance(r2, dict)


def test_no_pair_if_raw_only_sources():
    """If raw_nodes only contains source-time nodes, no adjacent pair exists."""
    obs = PrimaryConsensusObserver()
    coords = _simple_frames2_coords()
    ids = _ids_simple()
    obs.start_video("srconly", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs.start_pair(0, 0, 2, 2, 4, coords)
    fwd, rev = _make_unique_logits(2, 2)
    obs.primary(fwd, None, None)
    obs.reverse(rev)
    obs.secondary(None, None, None)
    obs.mixed(None, None)
    obs.end_video(coords, None)
    obs.pre_graph(coords, None, ids, _build_graph(coords, ids))
    obs.selected_graph(_build_graph(coords, ids))
    # Only source-time nodes (t=0)
    raw = _raw_nodes_from_coords(coords, ids, [0, 1])
    result = obs.frames_for("srconly", raw)
    assert result == {}


def test_graph_arbitrary_row_order():
    """Graph table rows in arbitrary order still validate correctly."""
    obs = PrimaryConsensusObserver()
    coords = _simple_frames2_coords()
    ids = _ids_simple()
    obs.start_video("order", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs.start_pair(0, 0, 2, 2, 4, coords)
    fwd, rev = _make_unique_logits(2, 2)
    obs.primary(fwd, None, None)
    obs.reverse(rev)
    obs.secondary(None, None, None)
    obs.mixed(None, None)
    obs.end_video(coords, None)
    # Provide graph rows in reversed order
    graph = _build_graph(coords, ids, row_order=[3, 2, 1, 0])
    obs.pre_graph(coords, None, ids, graph)
    obs.selected_graph(_build_graph(coords, ids))
    raw = _raw_nodes_from_coords(coords, ids, [0, 1, 2, 3])
    result = obs.frames_for("order", raw)
    assert isinstance(result, dict)


def test_stages_enforced():
    """Calling hooks out of order raises ValueError."""
    obs = PrimaryConsensusObserver()
    coords = _simple_frames2_coords()
    obs.start_video("stage", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs.start_pair(0, 0, 2, 2, 4, coords)
    # Skip primary, try reverse
    with pytest.raises(ValueError, match="state"):
        obs.reverse(_make_logits(2, 2))
