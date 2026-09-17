"""End-to-end synthetic matching -> graph diagnosis -> bound packet evidence."""

import copy
import json

import numpy as np
import polars as pl
import pytest

from biohub.association_capture import FEATURES, MATRICES, PairCapture, _sha
from biohub.association_stage_diagnostic import diagnose_stages, frames_from_npz
from biohub.association_stage_readout import attach_packet_evidence, plan_queries
from biohub.evaluate import graph_from_rows


def fixture(tmp_path, unmatched=False):
    counts = [3, 2] + [0] * 98
    writer = PairCapture(tmp_path / "capture", {"synthetic": counts})
    for t in range(99):
        ns, nt = counts[t : t + 2]
        arrays = {}
        for side, frame, n in (("source", t, ns), ("target", t + 1, nt)):
            arrays[f"{side}_indices"] = np.arange(sum(counts[:frame]), sum(counts[:frame]) + n, dtype=np.int64)
            arrays[f"{side}_coords_grid"] = np.array([[frame, 1, 2, i * 4] for i in range(n)], dtype=np.int16).reshape(
                n, 4
            )
        if ns and nt:
            for number, key in enumerate(MATRICES):
                arrays[key] = np.arange(ns * nt, dtype=np.float32).reshape(ns, nt) + number * 10
            arrays["mixed_probabilities"] = np.array([[0.5, 0.2], [0.5, 0.7], [0, 0.1]], dtype=np.float32)
            for key in FEATURES:
                n = ns if "source" in key else nt
                arrays[key] = np.zeros((n, 32), dtype=np.float32)
            first = copy.deepcopy(arrays)
        writer.write_pair("synthetic", t, arrays)
    writer.finish()
    coords = np.concatenate([first[f"{side}_coords_grid"] for side in ("source", "target")])
    coords *= np.array([1, 1, 4, 4], dtype=np.int16)
    ids = np.arange(5, dtype=np.int64) * 101 + 2**53 + 1
    rows, cols = np.where(first["mixed_probabilities"] > 0.48)
    pre = {
        "detector_indices": np.arange(5, dtype=np.int64),
        "graph_node_ids": ids,
        "node_node_id": ids,
        **{f"node_{key}": coords[:, col] for col, key in enumerate(("t", "z", "y", "x"))},
        "edge_edge_id": np.arange(len(rows), dtype=np.int64),
        "edge_source_id": ids[rows],
        "edge_target_id": ids[cols + 3],
        "edge_edge_prob": first["mixed_probabilities"][rows, cols],
    }
    pre_frames = frames_from_npz(pre)
    post = pre_frames[0], pre_frames[1].head(1)
    gt_nodes = pre_frames[0].filter(pl.col("node_id").is_in(ids[[0, 3, 4]].tolist()))
    if unmatched:
        gt_nodes = gt_nodes.with_columns((pl.col("x") + 1000).alias("x"))
    gt_edges = pl.DataFrame(
        {"source_id": [int(ids[0]), int(ids[0])], "target_id": [int(ids[3]), int(ids[4])]},
        schema={"source_id": pl.Int64, "target_id": pl.Int64},
    )
    gt = graph_from_rows(gt_nodes, gt_edges)
    stage = diagnose_stages("synthetic", pre_frames, post, post, gt, (1.625, 0.40625, 0.40625))
    manifest_path = writer.root / "MANIFEST.json"
    return stage, pre, coords, manifest_path, _sha(manifest_path)


def test_division_both_daughters_and_below_threshold_probability_are_preserved(tmp_path):
    inputs = fixture(tmp_path)
    before = copy.deepcopy(inputs[:3])
    plan = plan_queries(*inputs)
    assert len(plan["packets"]) == 1 and plan["packets"][0]["t_source"] == 0
    assert len(plan["queries"]) == 2 and not plan["matrix_read"]
    result = attach_packet_evidence(*inputs)
    assert result["summary"] == {"gt_edges": 2, "packets_read": 1, "packet_states": {"OBSERVED": 2}}
    rows = result["records"]
    assert [r["association"]["mixed_probability"] for r in rows] == [0.5, float(np.float32(0.2))]
    assert [r["association"]["rank_best"] for r in rows] == [1, 2]
    assert [r["fixed_pre_pair_state"] for r in rows] == ["origin_candidate_retained", "absent_from_recorded_candidates"]
    assert not result["all_dense_packets_read"] and not result["official_score_computed"]
    assert not result["training_label_assigned"] and not result["submission_authorized"]
    assert inputs[0] == before[0]
    assert all(np.array_equal(inputs[1][k], before[1][k]) for k in inputs[1])
    assert np.array_equal(inputs[2], before[2])


def test_unmatched_is_not_zero_and_does_not_download_packets(tmp_path):
    inputs = fixture(tmp_path, unmatched=True)
    plan = plan_queries(*inputs)
    assert plan["packets"] == [] and plan["queries"] == []
    result = attach_packet_evidence(*inputs)
    assert result["summary"]["packet_states"] == {"UNMATCHED_ENDPOINT": 2}
    assert all(r["association"] is None for r in result["records"])


def test_plan_does_not_read_packets_but_execution_requires_them(tmp_path):
    inputs = fixture(tmp_path)
    path = inputs[3].parent / "synthetic/pair_0000.npz"
    path.unlink()
    assert len(plan_queries(*inputs)["packets"]) == 1
    with pytest.raises(FileNotFoundError):
        attach_packet_evidence(*inputs)


@pytest.mark.parametrize(
    "case",
    [
        "assignment",
        "position",
        "presence",
        "duplicate_edge",
        "missing_node",
        "node_position",
        "node_gt_duplicate",
        "duplicate_candidate",
        "invalid_candidate",
        "count",
    ],
)
def test_wrong_stage_or_graph_cannot_be_joined(tmp_path, case):
    inputs = fixture(tmp_path)
    stage, pre = inputs[:2]
    if case == "assignment":
        stage["records"][0]["stage_views"]["pre"]["source_id"] += 1
    elif case == "position":
        stage["records"][0]["stage_views"]["pre"]["source_position"] = (0, 0, 0, 0)
    elif case == "presence":
        stage["records"][0]["stage_views"]["pre"]["edge_present"] = False
    elif case == "duplicate_edge":
        stage["records"][1] = stage["records"][0]
    elif case == "missing_node":
        stage["node_maps"]["pre"].pop()
    elif case == "node_position":
        stage["node_maps"]["pre"][0]["x"] += 1
    elif case == "node_gt_duplicate":
        stage["node_maps"]["pre"][1]["gt_node_id"] = stage["node_maps"]["pre"][0]["gt_node_id"]
    elif case == "duplicate_candidate":
        pre["edge_source_id"][1] = pre["edge_source_id"][0]
        pre["edge_target_id"][1] = pre["edge_target_id"][0]
    elif case == "invalid_candidate":
        pre["edge_edge_prob"][0] = 0.1
    else:
        stage["summary"]["gt_edges"] += 1
    with pytest.raises(ValueError):
        attach_packet_evidence(*inputs)


@pytest.mark.parametrize("case", ["sha", "missing", "duplicate", "counts", "path"])
def test_manifest_guards(tmp_path, case):
    inputs = list(fixture(tmp_path))
    path = inputs[3]
    manifest = json.loads(path.read_text())
    if case == "missing":
        manifest["records"].pop()
    elif case == "duplicate":
        manifest["records"][-1] = manifest["records"][0]
    elif case == "counts":
        manifest["frame_counts"]["synthetic"][0] += 1
    elif case == "path":
        manifest["records"][0]["path"] = "../outside.npz"
    path.write_text(json.dumps(manifest))
    if case != "sha":
        inputs[4] = _sha(path)
    with pytest.raises(ValueError):
        attach_packet_evidence(*inputs)


def test_shared_frame_packet_read_once(tmp_path, monkeypatch):
    from biohub import association_stage_readout as module

    inputs = fixture(tmp_path)
    original = module.read_packet
    calls = []

    def counted(*args):
        calls.append(args[1]["path"])
        return original(*args)

    monkeypatch.setattr(module, "read_packet", counted)
    result = attach_packet_evidence(*inputs)
    assert len(result["records"]) == 2 and calls == ["synthetic/pair_0000.npz"]


def test_mid_read_stage_mutation_rejected(tmp_path, monkeypatch):
    from biohub import association_stage_readout as module

    inputs = fixture(tmp_path)
    original = module.read_packet

    def changed(*args):
        packet = original(*args)
        inputs[0]["records"][0]["fixed_pre_pair_state"] = "changed"
        return packet

    monkeypatch.setattr(module, "read_packet", changed)
    with pytest.raises(ValueError, match="inputs changed"):
        attach_packet_evidence(*inputs)


def test_json_roundtrip_still_joins_same_gt_ids(tmp_path):
    inputs = list(fixture(tmp_path))
    before = attach_packet_evidence(*inputs)
    inputs[0] = json.loads(json.dumps(inputs[0]))
    after = attach_packet_evidence(*inputs)
    assert json.loads(json.dumps(before)) == json.loads(json.dumps(after))


def test_packet_changed_after_query_is_rejected(tmp_path, monkeypatch):
    from biohub import association_stage_readout as module

    inputs = fixture(tmp_path)
    original = module.query_pair
    path = inputs[3].parent / "synthetic/pair_0000.npz"

    def changed(*args):
        result = original(*args)
        path.write_bytes(path.read_bytes() + b"changed")
        return result

    monkeypatch.setattr(module, "query_pair", changed)
    with pytest.raises(ValueError, match="packet changed after query"):
        attach_packet_evidence(*inputs)
