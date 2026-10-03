"""Synthetic packets only; no competition images, GT, model calls, or training."""

import copy
import json
import zipfile

import numpy as np
import pytest

from biohub.association_capture import FEATURES, MATRICES, PairCapture, _sha
from biohub.association_packet_readout import detector_lookup, query_pair, read_packet
from biohub.association_parity import array_signatures


def make_packet(tmp_path, counts=(3, 2), probabilities=None):
    ns, nt = counts
    arrays = {}
    for side, frame, n, offset in (("source", 0, ns, 0), ("target", 1, nt, ns)):
        arrays[f"{side}_indices"] = np.arange(offset, offset + n, dtype=np.int64)
        arrays[f"{side}_coords_grid"] = np.array([[frame, 1, 2, i] for i in range(n)], dtype=np.int16).reshape(n, 4)
    if ns and nt:
        for number, key in enumerate(MATRICES):
            arrays[key] = np.arange(ns * nt, dtype=np.float32).reshape(ns, nt) + number * 10
        arrays["mixed_probabilities"] = (
            np.array([[0.5, 0.2], [0.5, 0.7], [0, 0.1]], dtype=np.float32)
            if probabilities is None
            else np.asarray(probabilities, dtype=np.float32)
        )
        for key in FEATURES:
            n = ns if "source" in key else nt
            arrays[key] = np.arange(n * 32, dtype=np.float32).reshape(n, 32)
    coords = np.concatenate([arrays[f"{side}_coords_grid"] for side in ("source", "target")]) * np.array(
        [1, 1, 4, 4], dtype=np.int16
    )
    writer = PairCapture(tmp_path / "capture", {"video": list(counts)})
    record = writer.write_pair("video", 0, arrays)
    writer.finish()
    ids = np.arange(len(coords), dtype=np.int64) * 101 + 2**53 + 1
    order = np.arange(len(coords))[::-1]
    pre = {
        "detector_indices": np.arange(len(coords), dtype=np.int64),
        "graph_node_ids": ids,
        "node_node_id": ids[order],
        **{f"node_{key}": coords[order, col] for col, key in enumerate(("t", "z", "y", "x"))},
    }
    return writer.root, record, coords, pre, arrays


def test_lossless_read_real_id_mapping_source_axis_and_ties(tmp_path):
    root, record, coords, pre, arrays = make_packet(tmp_path)
    originals = copy.deepcopy((record, coords, pre))
    packet = read_packet(root, record, coords)
    for key, value in arrays.items():
        assert packet.arrays[key].dtype == value.dtype
        assert packet.arrays[key].tobytes() == value.tobytes()
    lookup = detector_lookup(pre, coords)
    ids = list(map(int, pre["graph_node_ids"]))
    result = query_pair(packet, lookup, ids[0], ids[3], 0.5)
    assert (result["rank_best"], result["rank_worst"]) == (1, 2)
    assert result["margin_vs_best_other"] == 0
    assert (result["source_row"], result["target_column"]) == (0, 0)
    assert result["raw_saved_logits"]["primary_reverse_logits"] == 10
    result = query_pair(packet, lookup, ids[1], ids[4], float(np.float32(0.7)))
    assert result["rank_best"] == result["rank_worst"] == 1
    assert result["best_other_probability"] == float(np.float32(0.2))
    assert not result["training_label_assigned"] and not result["submission_authorized"]
    result = query_pair(packet, lookup, ids[2], ids[3], None)
    assert result["matrix_read"] and result["mixed_probability"] == 0
    assert result["rank_best"] == result["rank_worst"] == 3
    assert record == originals[0] and np.array_equal(coords, originals[1])
    assert all(np.array_equal(pre[k], originals[2][k]) for k in pre)


def test_single_parent_has_no_fabricated_other_probability(tmp_path):
    root, record, coords, pre, _ = make_packet(tmp_path, (1, 2), [[1, 1]])
    ids = list(map(int, pre["graph_node_ids"]))
    result = query_pair(read_packet(root, record, coords), detector_lookup(pre, coords), ids[0], ids[1], 1.0)
    assert result["best_other_probability"] is None and result["margin_vs_best_other"] is None


def test_threshold_is_strict_float32_comparison(tmp_path):
    root, record, coords, pre, _ = make_packet(tmp_path, (2, 1), [[0.48], [0.52]])
    ids = list(map(int, pre["graph_node_ids"]))
    result = query_pair(read_packet(root, record, coords), detector_lookup(pre, coords), ids[0], ids[2], None)
    assert not result["above_candidate_threshold"]


@pytest.mark.parametrize("counts", [(0, 2), (2, 0), (0, 0)])
def test_empty_packet_has_no_probability(tmp_path, counts):
    root, record, coords, pre, _ = make_packet(tmp_path, counts)
    packet = read_packet(root, record, coords)
    with pytest.raises(ValueError, match="empty pair"):
        query_pair(packet, detector_lookup(pre, coords), 1, 2, None)


@pytest.mark.parametrize("case", ["missing", "tamper", "symlink"])
def test_unavailable_or_changed_file_fails_closed(tmp_path, case):
    root, record, coords, _, _ = make_packet(tmp_path)
    path = root / record["path"]
    if case == "tamper":
        path.write_bytes(path.read_bytes() + b"changed")
    else:
        outside = tmp_path / "outside.npz"
        path.rename(outside)
        if case == "symlink":
            path.symlink_to(outside)
    with pytest.raises((ValueError, FileNotFoundError)):
        read_packet(root, record, coords)


def rewrite(root, record, arrays, metadata=None):
    if metadata is None:
        metadata = {k: v for k, v in record.items() if k not in ("path", "bytes", "sha256")}
    path = root / record["path"]
    np.savez_compressed(path, metadata=np.array(json.dumps(metadata)), **arrays)
    record.update(bytes=path.stat().st_size, sha256=_sha(path))


@pytest.mark.parametrize(
    "case", ["transpose", "half", "nonfinite", "hash", "metadata", "extra", "normalization", "grid", "indices"]
)
def test_semantic_validation_even_with_updated_file_hash(tmp_path, case):
    root, record, coords, _, arrays = make_packet(tmp_path)
    if case == "transpose":
        arrays["primary_reverse_logits"] = arrays["primary_reverse_logits"].T
    elif case == "half":
        arrays["mixed_logits"] = arrays["mixed_logits"].astype(np.float16)
    elif case == "nonfinite":
        arrays["mixed_logits"][0, 0] = np.nan
    elif case in ("hash", "metadata"):
        arrays["mixed_logits"][0, 0] += 1
    elif case == "extra":
        arrays["unknown"] = np.array(1)
    elif case == "normalization":
        arrays["mixed_probabilities"][:] = 0.2
    elif case == "grid":
        arrays["source_coords_grid"][0, 2] += 1
    else:
        arrays["source_indices"][0] = 42
    metadata = None
    if case == "metadata":
        metadata = {k: v for k, v in record.items() if k not in ("path", "bytes", "sha256")}
        metadata["window_size"] = 3
    elif case != "hash":
        record["arrays"] = array_signatures(arrays)
    rewrite(root, record, arrays, metadata)
    with pytest.raises(ValueError):
        read_packet(root, record, coords)


@pytest.mark.parametrize("case", ["duplicate", "fractional", "coords", "indices", "node_duplicate"])
def test_graph_mapping_rejects_wrong_identity(tmp_path, case):
    _, _, coords, pre, _ = make_packet(tmp_path)
    if case == "duplicate":
        pre["graph_node_ids"][1] = pre["graph_node_ids"][0]
    elif case == "fractional":
        pre["node_node_id"] = pre["node_node_id"].astype(float)
    elif case == "coords":
        pre["node_x"][0] += 1
    elif case == "indices":
        pre["detector_indices"] = pre["detector_indices"][::-1]
    else:
        pre["node_node_id"][0] = pre["node_node_id"][1]
    with pytest.raises(ValueError):
        detector_lookup(pre, coords)


@pytest.mark.parametrize("case", ["absent", "wrong_side", "candidate_missing", "candidate_extra", "probability"])
def test_query_mismatch_never_becomes_a_label(tmp_path, case):
    root, record, coords, pre, _ = make_packet(tmp_path)
    ids = list(map(int, pre["graph_node_ids"]))
    source, target, probability = ids[0], ids[3], 0.5
    if case == "absent":
        source = 0
    elif case == "wrong_side":
        source = ids[3]
    elif case == "candidate_missing":
        probability = None
    elif case == "candidate_extra":
        source = ids[2]
    else:
        probability = 0.51
    with pytest.raises(ValueError):
        query_pair(read_packet(root, record, coords), detector_lookup(pre, coords), source, target, probability)


def test_zip_expansion_guard(tmp_path):
    root, record, coords, _, _ = make_packet(tmp_path)
    path = root / record["path"]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("large.npy", bytes(32 * 1024**2 + 1))
    record.update(bytes=path.stat().st_size, sha256=_sha(path))
    with pytest.raises(ValueError, match="expansion budget"):
        read_packet(root, record, coords)
