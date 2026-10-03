"""Synthetic graph and manifest audit; no GT/model/network work."""

import copy
import hashlib
import json

import numpy as np
import pytest

from biohub.association_artifact_audit import audit_video, pair_manifest_summary
from biohub.association_capture import FEATURES, MATRICES, PairCapture
from biohub.association_parity import semantic_graph_signature


def video():
    ids = np.array([101, 205, 308, 990], dtype=np.int64)
    coords = np.array([[0, 1, 4, 8], [0, 1, 4, 16], [1, 1, 4, 8], [1, 1, 4, 16]], dtype=np.int16)
    pre = {
        "node_node_id": ids.copy(),
        **{f"node_{k}": coords[:, i].copy() for i, k in enumerate(("t", "z", "y", "x"))},
        "edge_edge_id": np.array([5, 2], dtype=np.int64),
        "edge_source_id": ids[:2].copy(),
        "edge_target_id": ids[2:].copy(),
        "edge_edge_prob": np.array([0.6, 0.7], dtype=np.float32),
        "edge_edge_dist": np.array([0.0, 0.0], dtype=np.float64),
    }
    post = {k: a[[0, 2]] if k.startswith("node_") else a[:1].copy() for k, a in pre.items()}
    observed = {**copy.deepcopy(pre), "graph_node_ids": ids.copy(), "detector_indices": np.arange(4, dtype=np.int64)}
    post_observed = copy.deepcopy(post)
    returned = {
        "coords": coords,
        "edges": np.array([[0, 2, float(np.float32(0.6)), 0], [1, 3, float(np.float32(0.7)), 0]], dtype=np.float64),
    }
    expected = {
        "frame_counts": [2, 2] + [0] * 98,
        "coordinate_sha256": hashlib.sha256(coords.tobytes()).hexdigest(),
        "raw_graph_signature": semantic_graph_signature(post),
    }
    return expected, returned, pre, post, observed, post_observed


def test_actual_arrays_match_reference_without_modification():
    inputs = video()
    before = copy.deepcopy(inputs)
    assert audit_video(*inputs) == {
        "detectors": 4,
        "candidate_edges": 2,
        "selected_nodes": 2,
        "selected_edges": 1,
        "actual_graphs_verified": True,
        "matrix_packets_read_locally": 0,
    }
    assert inputs[0] == before[0]
    for actual, original in zip(inputs[1:], before[1:], strict=True):
        assert all(np.array_equal(actual[k], original[k]) for k in actual)


def test_observer_row_order_may_differ_but_ids_and_values_must_match():
    inputs = list(video())
    inputs[4] = {k: a[::-1].copy() if k.startswith(("node_", "edge_")) else a for k, a in inputs[4].items()}
    assert audit_video(*inputs)["actual_graphs_verified"]


@pytest.mark.parametrize(
    "case",
    [
        "coordinate_ref",
        "count_ref",
        "common",
        "duplicate_node",
        "duplicate_edge_id",
        "fractional_id",
        "nan",
        "wrong_returned_index",
        "duplicate_candidate",
        "returned_probability",
        "post_ref",
        "post_position",
        "post_edge",
        "post_dangling",
    ],
)
def test_graph_drift_rejected(case):
    inputs = list(video())
    expected, returned, pre, post, observed, post_observed = inputs
    if case == "coordinate_ref":
        expected["coordinate_sha256"] = "0" * 64
    elif case == "count_ref":
        expected["frame_counts"][0] = 3
    elif case == "common":
        pre["edge_edge_prob"][0] = 0.8
    elif case == "duplicate_node":
        pre["node_node_id"][1] = pre["node_node_id"][0]
    elif case == "duplicate_edge_id":
        pre["edge_edge_id"][1] = pre["edge_edge_id"][0]
    elif case == "fractional_id":
        pre["edge_source_id"] = pre["edge_source_id"].astype(float)
    elif case == "nan":
        pre["edge_edge_dist"][0] = np.nan
    elif case == "wrong_returned_index":
        returned["edges"][0, 0] = -0.5
    elif case == "duplicate_candidate":
        for graph in (pre, observed):
            graph["edge_source_id"][1] = graph["edge_source_id"][0]
            graph["edge_target_id"][1] = graph["edge_target_id"][0]
    elif case == "returned_probability":
        returned["edges"][0, 2] += 0.1
    elif case == "post_ref":
        expected["raw_graph_signature"] = {}
    else:
        key, value = {
            "post_position": ("node_x", 100),
            "post_edge": ("edge_edge_prob", 0.8),
            "post_dangling": ("edge_target_id", 990),
        }[case]
        for graph in (post, post_observed):
            graph[key][0] = value
        expected["raw_graph_signature"] = semantic_graph_signature(post)
    with pytest.raises(ValueError):
        audit_video(*inputs)


def test_empty_graphs_do_not_fabricate_edges():
    inputs = list(video())
    for index in (2, 3, 4, 5):
        inputs[index] = {k: a[:0].copy() if k.startswith("edge_") else a for k, a in inputs[index].items()}
    inputs[1]["edges"] = np.empty((0, 4), dtype=np.float64)
    inputs[0]["raw_graph_signature"] = semantic_graph_signature(inputs[3])
    assert audit_video(*inputs)["candidate_edges"] == 0


@pytest.fixture
def manifest_fixture(tmp_path):
    counts = [2, 2] + [0] * 98
    writer = PairCapture(tmp_path / "capture", {"v": counts})
    for t in range(99):
        ns, nt = counts[t : t + 2]
        arrays = {}
        for side, frame, n in (("source", t, ns), ("target", t + 1, nt)):
            offset = sum(counts[:frame])
            arrays[f"{side}_indices"] = np.arange(offset, offset + n, dtype=np.int64)
            arrays[f"{side}_coords_grid"] = np.array([[frame, 1, 2, i] for i in range(n)], dtype=np.int16).reshape(n, 4)
        if ns and nt:
            for key in MATRICES:
                arrays[key] = np.full((ns, nt), 0.5, dtype=np.float32)
            for key in FEATURES:
                arrays[key] = np.zeros((ns if "source" in key else nt, 32), dtype=np.float32)
        writer.write_pair("v", t, arrays)
    writer.finish()
    return json.loads((writer.root / "MANIFEST.json").read_text()), {"v": {"frame_counts": counts}}


def test_manifest_coverage_and_empty_frames_without_claiming_actual_packet_reads(manifest_fixture):
    result = pair_manifest_summary(*manifest_fixture)
    assert result["packet_count"] == 99 and result["dense_pairs"] == 4 and result["empty_pairs"] == 98
    assert result["packet_bytes"] > 0 and result["matrix_packets_read_locally"] == 0
    assert not result["all_packet_files_verified_locally"]


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "duplicate",
        "bool_frame",
        "transpose",
        "dtype",
        "array_sha",
        "file_sha",
        "axes",
        "empty_status",
        "file_path",
        "bytes",
        "dense",
        "writer",
        "count",
        "extra",
    ],
)
def test_bad_manifest_rejected(manifest_fixture, case):
    manifest, datasets = manifest_fixture
    r = manifest["records"][0]
    if case == "missing":
        manifest["records"].pop()
    elif case == "duplicate":
        manifest["records"][-1] = r
    elif case == "bool_frame":
        r["t_source"] = False
    elif case == "transpose":
        r["arrays"]["mixed_logits"]["shape"] = [3, 2]
    elif case == "dtype":
        r["arrays"]["mixed_logits"]["dtype"] = "<f2"
    elif case == "array_sha":
        r["arrays"]["mixed_logits"]["sha256"] = "bad"
    elif case == "file_sha":
        r["sha256"] = "bad"
    elif case == "axes":
        r["probability_normalisation_axis"] = "target"
    elif case == "empty_status":
        manifest["records"][1]["status"] = "OBSERVED"
    elif case == "file_path":
        r["path"] = "../escape.npz"
    elif case == "bytes":
        manifest["packet_bytes"] += 1
    elif case == "dense":
        manifest["dense_pairs"] += 1
    elif case == "writer":
        manifest["writer_seconds"] = float("nan")
    elif case == "count":
        datasets["v"]["frame_counts"][0] = 2049
    else:
        r["arrays"]["extra"] = r["arrays"]["mixed_logits"]
    with pytest.raises(ValueError):
        pair_manifest_summary(manifest, datasets)
