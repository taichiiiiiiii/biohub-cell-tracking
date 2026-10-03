"""Synthetic CPU arrays; no model, competition image, or GT access."""

import json
from dataclasses import replace

import numpy as np
import pytest

from biohub.association_capture import COORDINATES, FEATURES, MATRICES, CaptureLimits, PairCapture


def packet(counts=(2, 3, 2), t=0):
    ns, nt = counts[t:t + 2]
    offsets = np.cumsum([0, *counts])
    arrays = {}
    for side, time in (("source", t), ("target", t + 1)):
        n = counts[time]
        arrays[f"{side}_indices"] = np.arange(offsets[time], offsets[time + 1], dtype=np.int64)
        arrays[f"{side}_coords_grid"] = np.array([[time, 1, 2, i] for i in range(n)],
                                                 dtype=np.int16).reshape(n, 4)
    if ns and nt:
        for i, key in enumerate(MATRICES):
            arrays[key] = (np.arange(ns * nt, dtype=np.float32).reshape(ns, nt) + np.float32(i / 7))
        arrays["mixed_probabilities"] = np.full((ns, nt), 1 / ns, dtype=np.float32)
        for key in FEATURES:
            n = ns if "source" in key else nt
            arrays[key] = np.arange(n * 32, dtype=np.float32).reshape(n, 32) + np.float32(t / 3)
    return arrays


def test_full_lossless_roundtrip_and_no_input_mutation(tmp_path):
    writer = PairCapture(tmp_path / "capture", {"video": [2, 3, 2]})
    for t in (0, 1):
        arrays = packet(t=t)
        original = {k: a.tobytes() for k, a in arrays.items()}
        for a in arrays.values():
            a.flags.writeable = False
        record = writer.write_pair("video", t, arrays)
        with np.load(writer.root / record["path"], allow_pickle=False) as saved:
            for k, a in arrays.items():
                assert saved[k].dtype == a.dtype and saved[k].tobytes() == original[k] == a.tobytes()
    result = writer.finish()
    assert result["status"] == "PAIR_CAPTURE_COMPLETE" and result["dense_pairs"] == 12
    assert not result["submission_authorized"] and not result["inference_parity_verified"]
    assert not result["graph_ID_mapping_complete"]
    assert (writer.root / "MANIFEST.json").exists()


def test_same_node_has_distinct_window_side_features(tmp_path):
    writer = PairCapture(tmp_path / "capture", {"v": [2, 3, 2]})
    for t in range(2):
        writer.write_pair("v", t, packet(t=t))
    writer.finish()
    with np.load(writer.root / "v/pair_0000.npz", allow_pickle=False) as left, \
            np.load(writer.root / "v/pair_0001.npz", allow_pickle=False) as right:
        assert np.array_equal(left["target_indices"], right["source_indices"])
        assert not np.array_equal(left["primary_target_features"], right["primary_source_features"])


def test_empty_pair_has_no_fabricated_features(tmp_path):
    counts = (0, 3, 0)
    writer = PairCapture(tmp_path / "capture", {"v": list(counts)})
    for t in range(2):
        record = writer.write_pair("v", t, packet(counts, t))
        assert record["status"] == "SKIPPED_EMPTY" and record["dense_pairs"] == 0
        assert set(record["arrays"]) == set(COORDINATES)
    assert writer.finish()["dense_pairs"] == 0


@pytest.mark.parametrize("case", [
    "transpose", "half", "nan", "extra_key", "missing_key", "wrong_time", "wrong_id",
    "negative_grid", "wrong_prob_axis", "negative_prob", "large_prob", "object", "wrong_features",
])
def test_malformed_packet_fails_closed(tmp_path, case):
    arrays = packet()
    if case == "transpose":
        arrays["primary_reverse_logits"] = arrays["primary_reverse_logits"].T
    elif case == "half":
        arrays["mixed_logits"] = arrays["mixed_logits"].astype(np.float16)
    elif case == "nan":
        arrays["mixed_logits"][0, 0] = np.nan
    elif case == "extra_key":
        arrays["unknown"] = arrays["mixed_logits"]
    elif case == "missing_key":
        del arrays["secondary_forward_logits"]
    elif case == "wrong_time":
        arrays["source_coords_grid"][:, 0] = 1
    elif case == "wrong_id":
        arrays["source_indices"][0] = 99999
    elif case == "negative_grid":
        arrays["target_coords_grid"][0, 1] = -1
    elif case == "wrong_prob_axis":
        arrays["mixed_probabilities"][:] = np.float32(1 / 3)
    elif case == "negative_prob":
        arrays["mixed_probabilities"][0, 0] = -0.5
    elif case == "large_prob":
        arrays["mixed_probabilities"][0, 0] = 1.5
    elif case == "object":
        arrays["mixed_logits"] = arrays["mixed_logits"].astype(object)
    else:
        arrays["primary_source_features"] = np.ones((2, 31), dtype=np.float32)
    writer = PairCapture(tmp_path / "capture", {"v": [2, 3, 2]})
    with pytest.raises(ValueError):
        writer.write_pair("v", 0, arrays)
    assert writer.failed and (writer.root / "ERROR.json").exists()
    with pytest.raises(ValueError, match="failed or closed"):
        writer.finish()
    assert not (writer.root / "MANIFEST.json").exists()


def test_float32_tiny_probability_signed_zero_and_noncontiguous_arrays(tmp_path):
    arrays = packet(counts=(2, 3))
    arrays["mixed_probabilities"][0] = np.float32(1e-12)
    arrays["mixed_probabilities"][1] = np.float32(1.)
    arrays["mixed_logits"][0, 0] = np.float32(-0.)
    arrays["primary_forward_logits"] = np.asfortranarray(arrays["primary_forward_logits"])
    writer = PairCapture(tmp_path / "capture", {"v": [2, 3]})
    record = writer.write_pair("v", 0, arrays)
    with np.load(writer.root / record["path"], allow_pickle=False) as saved:
        assert saved["mixed_probabilities"][0, 0] == np.float32(1e-12)
        assert np.signbit(saved["mixed_logits"][0, 0])
        assert saved["primary_forward_logits"].tobytes() == arrays["primary_forward_logits"].tobytes()
    writer.finish()


def test_duplicate_pair_preserves_first_packet(tmp_path):
    writer = PairCapture(tmp_path / "capture", {"v": [2, 3]})
    first = writer.write_pair("v", 0, packet(counts=(2, 3)))
    path = writer.root / first["path"]
    original = path.read_bytes()
    with pytest.raises(ValueError, match="duplicate"):
        writer.write_pair("v", 0, packet(counts=(2, 3)))
    assert path.read_bytes() == original


def test_existing_run_and_incomplete_finish_rejected(tmp_path):
    root = tmp_path / "capture"
    writer = PairCapture(root, {"v": [2, 3, 2]})
    with pytest.raises(FileExistsError):
        PairCapture(root, {"v": [2, 3, 2]})
    writer.write_pair("v", 0, packet())
    with pytest.raises(ValueError, match="incomplete"):
        writer.finish()


@pytest.mark.parametrize("kind", ["node", "packet", "run"])
def test_count_limits_before_any_output(tmp_path, kind):
    limits = CaptureLimits()
    if kind == "node":
        limits = replace(limits, nodes_per_side=2)
    elif kind == "packet":
        limits = replace(limits, pairs_per_packet=5)
    else:
        limits = replace(limits, pairs_per_run=11)
    root = tmp_path / "capture"
    with pytest.raises(ValueError):
        PairCapture(root, {"v": [2, 3, 2]}, limits=limits)
    assert not root.exists()


def test_byte_limit_preserves_failed_partial_output(tmp_path):
    writer = PairCapture(tmp_path / "capture", {"v": [2, 3]}, limits=replace(CaptureLimits(), output_bytes=1))
    with pytest.raises(ValueError, match="byte budget"):
        writer.write_pair("v", 0, packet(counts=(2, 3)))
    assert (writer.root / "v/pair_0000.npz").exists()
    assert json.loads((writer.root / "ERROR.json").read_text())["status"] == "ERROR"


def test_time_limit(tmp_path, monkeypatch):
    writer = PairCapture(tmp_path / "capture", {"v": [2, 3]})
    times = iter([0., 1201.])
    monkeypatch.setattr("biohub.association_capture.time.perf_counter", lambda: next(times))
    with pytest.raises(ValueError, match="time budget"):
        writer.write_pair("v", 0, packet(counts=(2, 3)))


def test_saved_packet_mutation_rejected(tmp_path):
    writer = PairCapture(tmp_path / "capture", {"v": [2, 3]})
    record = writer.write_pair("v", 0, packet(counts=(2, 3)))
    with (writer.root / record["path"]).open("ab") as stream:
        stream.write(b"corruption")
    with pytest.raises(ValueError, match="packet changed"):
        writer.finish()


def test_returned_metadata_cannot_change_internal_manifest(tmp_path):
    writer = PairCapture(tmp_path / "capture", {"v": [2, 3]})
    record = writer.write_pair("v", 0, packet(counts=(2, 3)))
    record["dense_pairs"] = 1
    record["arrays"].clear()
    result = writer.finish()
    assert result["dense_pairs"] == 6 and len(result["records"][0]["arrays"]) == 13


def test_manifest_size_is_part_of_byte_limit(tmp_path):
    probe = PairCapture(tmp_path / "probe", {"v": [2, 3]})
    probe.write_pair("v", 0, packet(counts=(2, 3)))
    limit = probe.output_bytes + 1
    probe.finish()
    writer = PairCapture(tmp_path / "capture", {"v": [2, 3]},
                         limits=replace(CaptureLimits(), output_bytes=limit))
    writer.write_pair("v", 0, packet(counts=(2, 3)))
    with pytest.raises(ValueError, match="manifest byte budget"):
        writer.finish()
    assert not (writer.root / "MANIFEST.json").exists()


@pytest.mark.parametrize("name,counts", [("../escape", [1, 2]), ("v", [True, 2]), ("v", [2])])
def test_invalid_plan(tmp_path, name, counts):
    with pytest.raises(ValueError):
        PairCapture(tmp_path / "capture", {name: counts})
