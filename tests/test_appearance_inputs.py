"""Synthetic NPZ integration tests for load_appearance_frames (no mocking)."""

import copy
import json

import numpy as np
import pytest

from biohub.appearance_inputs import (
    load_appearance_frames,
    load_consensus_frames,
    load_positive_consensus_frames,
)
from biohub.association_capture import FEATURES, MATRICES, PairCapture, _sha
from biohub.association_parity import array_signatures

COORDS = np.array([[0, 1, 8, 0], [0, 1, 8, 4], [0, 1, 8, 8],
                   [1, 1, 8, 0], [1, 1, 8, 4]], dtype=np.int16)
IDS = np.array([2**53 + 9, 2**53 + 3, 2**53 + 7, 2**53 + 5, 2**53 + 1], dtype=np.int64)
DIV = np.array([1, 1, 4, 4], dtype=np.int16)


@pytest.fixture
def fixture(tmp_path, request):
    base = tmp_path / "association_collection_run" / "group00"
    obs = base / "observation"
    writerroot = obs / "pairs"
    frame_of_side = {"source": lambda t: t, "target": lambda t: t + 1}
    original = None
    writer = PairCapture(writerroot, {"video": [3, 2] + [0] * 98})
    for t in range(99):
        arrays = {}
        frames = {side: f(t) for side, f in frame_of_side.items()}
        for side in ("source", "target"):
            inds = np.flatnonzero(COORDS[:, 0] == frames[side]).astype(np.int64)
            arrays[side + "_indices"] = inds
            arrays[side + "_coords_grid"] = (COORDS[inds] // DIV).astype(np.int16)
        ns = arrays["source_indices"].size
        nt = arrays["target_indices"].size
        if ns and nt:
            for m in MATRICES:
                arrays[m] = np.zeros((ns, nt), dtype=np.float32)
            if t == 0 and hasattr(request, 'param'):
                for name in ('primary_forward_logits', 'primary_reverse_logits',
                             'secondary_forward_logits'):
                    arrays[name] = np.asarray(request.param, dtype=np.float32).copy()
            arrays["mixed_probabilities"] = np.full((ns, nt), 1.0 / ns,
                                                    dtype=np.float32)
            for number, key in enumerate(FEATURES):
                n = ns if "source" in key else nt
                arrays[key] = (np.arange(n * 32, dtype=np.float32).reshape(n, 32)
                               + 1.0 + 1000.0 * number)
            if t == 0:
                original = {key: arrays[key].copy() for key in FEATURES}
        writer.write_pair("video", t, arrays)
    writer.finish()

    pre = {"detector_indices": np.arange(5, dtype=np.int64),
           "graph_node_ids": IDS,
           "node_t": COORDS[::-1, 0],
           "node_z": COORDS[::-1, 1],
           "node_y": COORDS[::-1, 2],
           "node_x": COORDS[::-1, 3],
           "node_node_id": IDS[::-1]}
    np.savez_compressed(obs / "video_pre_ilp.npz", **pre)
    returned = base / "video_returned.npz"
    np.savez_compressed(returned, coords=COORDS)
    manifest = writerroot / "MANIFEST.json"
    observer = obs / "MANIFEST.json"
    observer.write_text(json.dumps({"pair_manifest_sha256": _sha(manifest)}))

    bindings = {}
    for p in (returned, obs / "video_pre_ilp.npz", observer, manifest):
        bindings[str(p.relative_to(tmp_path))] = {"bytes": p.stat().st_size,
                                                 "sha256": _sha(p)}

    nodes = {}
    for i in (0, 2, 4):
        nodes[int(IDS[i])] = {"node_id": int(IDS[i]), "t": int(COORDS[i, 0]),
                              "z": int(COORDS[i, 1]), "y": int(COORDS[i, 2]),
                              "x": int(COORDS[i, 3])}
    return tmp_path, bindings, nodes, original, IDS


@pytest.mark.parametrize(
    'fixture', [[[9, 0], [0, 0], [0, 9]], [[0, 8], [0, 9], [9, 0]]], indirect=True)
def test_consensus_real_npz(fixture, request):
    root, bindings, nodes, _features, ids = fixture
    first = request.node.callspec.params['fixture'][0][0] == 9
    expected = [(int(ids[2]), int(ids[4]))] if first else []
    frames, receipt = load_consensus_frames(root, "group00", "video", bindings, nodes)
    assert frames == {0: expected}
    assert receipt['schema'] == 'E29_CONSENSUS_INPUT_RECEIPT_V1'
    assert receipt['packet_count'] == 99
    assert len(receipt['bindings']) == 103
    assert receipt["gt_read"] is False
    assert receipt["weights_loaded"] is False
    assert receipt['frames'][0]['detector_consensus_count'] == 2
    assert receipt['frames'][0]['raw_pairs'] == [list(p) for p in expected]
    manifest = json.loads((root / 'association_collection_run' / 'group00' /
                           'observation' / 'pairs' / 'MANIFEST.json').read_text())
    record = next(r for r in manifest['records'] if r['dataset'] == 'video' and r['t_source'] == 0)
    names = ('primary_forward_logits', 'primary_reverse_logits', 'secondary_forward_logits')
    assert receipt['frames'][0]['original_logit_signatures'] == {name: record['arrays'][name] for name in names}


def test_consensus_frames_allzero_logits(fixture):
    root, bindings, nodes, _features, _ids = fixture
    frames, receipt = load_consensus_frames(root, "group00", "video", bindings, nodes)
    assert frames == {0: []}
    assert receipt['frames'][0]['detector_consensus_count'] == 0


def test_positive_consensus_schema_and_pairs(fixture):
    root, bindings, nodes, _features, _ids = fixture
    frames, receipt = load_positive_consensus_frames(root, "group00", "video", bindings, nodes)
    assert frames == {0: []}
    assert receipt["schema"] == "E30_POSITIVE_CONSENSUS_INPUT_RECEIPT_V1"


@pytest.mark.parametrize('mutation', ['packet', 'coords'])
def test_consensus_corruption(fixture, mutation):
    root, bindings, nodes, _features, _ids = fixture
    nodes = copy.deepcopy(nodes)
    if mutation == 'packet':
        p = (root / "association_collection_run" / "group00" / "observation"
             / "pairs" / "video" / "pair_0000.npz")
        p.write_bytes(p.read_bytes() + b"x")
    else:
        nodes[next(iter(nodes))]['x'] += 0.5
    with pytest.raises(ValueError):
        load_consensus_frames(root, "group00", "video", bindings, nodes)


def test_success_and_selection(fixture):
    root, bindings, nodes, original, ids = fixture
    frames, receipt = load_appearance_frames(root, "group00", "video",
                                             bindings, nodes)
    assert set(frames) == {0}
    frame = frames[0]
    assert list(frame["source_ids"]) == [int(ids[2]), int(ids[0])]
    assert list(frame["target_ids"]) == [int(ids[4])]
    assert len(frame) == 8
    for key in FEATURES:
        if "source" in key:
            expected = original[key][[2, 0]]
        else:
            expected = original[key][[1]]
        assert frame[key].dtype == np.float32
        assert frame[key].shape == expected.shape
        assert frame[key].shape[-1] == 32
        np.testing.assert_array_equal(frame[key], expected)
    assert receipt["packet_count"] == 99
    assert len(receipt["frames"]) == 1
    assert len(receipt["bindings"]) == 103
    assert receipt["gt_read"] is False
    assert receipt["weights_loaded"] is False
    assert (receipt["frames"][0]["mapped_feature_signatures"]
            == array_signatures({key: frame[key] for key in FEATURES}))


@pytest.mark.parametrize("mutate", ["frac", "badtime", "empty", "boolid"])
def test_bad_raw_nodes(fixture, mutate):
    root, bindings, fixture_nodes, _, _ = fixture
    nodes = copy.deepcopy(fixture_nodes)
    if mutate == "empty":
        nodes = {}
    else:
        key = next(iter(nodes))
        if mutate == "frac":
            nodes[key]["x"] += 0.5
        elif mutate == "badtime":
            nodes[key]["t"] = 2
        else:
            nodes[key]["node_id"] = True
            nodes[True] = nodes.pop(key)
    with pytest.raises(ValueError):
        load_appearance_frames(root, "group00", "video", bindings, nodes)


def test_changed_returned_file(fixture):
    root, bindings, nodes, _, _ = fixture
    p = root / "association_collection_run" / "group00" / "video_returned.npz"
    p.write_bytes(p.read_bytes() + b"x")
    with pytest.raises(ValueError):
        load_appearance_frames(root, "group00", "video", bindings, nodes)


def test_changed_packet(fixture):
    root, bindings, nodes, _, _ = fixture
    p = (root / "association_collection_run" / "group00" / "observation"
         / "pairs" / "video" / "pair_0000.npz")
    p.write_bytes(p.read_bytes() + b"x")
    with pytest.raises(ValueError):
        load_appearance_frames(root, "group00", "video", bindings, nodes)


def _receipt_case(fixture, monkeypatch):
    from scripts import e27_association_prior_screen as g

    root, bindings, nodes, original_features, ids = fixture
    ref = {
        "diagnostic12": ["video"],
        "groups": [
            {"group_id": "group00", "stage": "diagnostic12", "datasets": ["video"]},
            {"group_id": "group03", "stage": "expansion", "datasets": ["other"]},
        ],
    }
    audit = {"status": "COLLECTION36_ARTIFACT_AUDIT_PASS", "bindings": bindings}

    def fake_load(name, sha):
        if name == g.REFERENCE:
            return copy.deepcopy(ref)
        if name == g.AUDIT:
            return copy.deepcopy(audit)
        raise AssertionError(name)

    monkeypatch.setattr(g, "STEMS", ("video",))
    monkeypatch.setattr(g, "COLLECTION_ROOT", root)
    monkeypatch.setattr(g, "_load", fake_load)

    plan = g.prepare_appearance_plan()
    _, receipt = load_appearance_frames(root, "group00", "video", bindings, nodes)
    return g, root, plan, receipt


def test_verify_appearance_receipts_success(fixture, monkeypatch):
    g, _root, plan, receipt = _receipt_case(fixture, monkeypatch)
    assert len(plan["bindings_by_dataset"]["video"]) == 103
    originals = plan["original_signatures"]["video"]
    assert len(originals) == 99
    assert originals[1] is None
    assert originals[0][FEATURES[0]] == receipt["frames"][0]["original_feature_signatures"][FEATURES[0]]

    calls = []
    assert g.verify_appearance_receipts(plan, [receipt], lambda: calls.append("budget")) is None
    assert len(calls) >= 2


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_binding",
        "duplicate_frame",
        "original_hash",
        "mapped_shape",
        "gt_flag",
        "missing_receipt",
        "inactive_file_drift",
    ],
)
def test_verify_appearance_receipts_rejects(fixture, monkeypatch, mutation):
    g, root, plan, receipt = _receipt_case(fixture, monkeypatch)
    receipts = [copy.deepcopy(receipt)]
    frame = receipts[0]["frames"][0]

    if mutation == "missing_binding":
        receipts[0]["bindings"].pop(next(iter(receipts[0]["bindings"])))
    elif mutation == "duplicate_frame":
        receipts[0]["frames"].append(copy.deepcopy(frame))
    elif mutation == "original_hash":
        frame["original_feature_signatures"][FEATURES[0]]["sha256"] = "0" * 64
    elif mutation == "mapped_shape":
        frame["mapped_feature_signatures"][FEATURES[0]]["shape"] = [999, 32]
    elif mutation == "gt_flag":
        receipts[0]["gt_read"] = True
    elif mutation == "missing_receipt":
        receipts = []
    elif mutation == "inactive_file_drift":
        packet = (
            root / "association_collection_run" / "group00" / "observation" / "pairs"
            / "video" / "pair_0098.npz"
        )
        with packet.open("ab") as handle:
            handle.write(b"x")

    with pytest.raises(ValueError):
        g.verify_appearance_receipts(plan, receipts, lambda: None)
