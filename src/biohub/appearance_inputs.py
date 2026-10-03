import re
from pathlib import Path

import numpy as np

from biohub.association_capture import FEATURES, _require
from biohub.association_collection_audit import Reader
from biohub.association_packet_readout import detector_lookup, read_packet
from biohub.association_parity import array_signatures
from biohub.consensus_edges import (
    map_consensus_to_raw,
    positive_reciprocal_consensus_pairs,
    primary_reciprocal_consensus_pairs,
    reciprocal_consensus_pairs,
)


def load_appearance_frames(root, group, dataset, bindings, raw_nodes):
    return _load_frames(root, group, dataset, bindings, raw_nodes, consensus_mode=False)


def load_consensus_frames(root, group, dataset, bindings, raw_nodes):
    return _load_frames(root, group, dataset, bindings, raw_nodes, consensus_mode=True)


def load_positive_consensus_frames(root, group, dataset, bindings, raw_nodes):
    return _load_frames(root, group, dataset, bindings, raw_nodes, consensus_mode="positive")


def load_primary_consensus_frames(root, group, dataset, bindings, raw_nodes):
    return _load_frames(root, group, dataset, bindings, raw_nodes, consensus_mode="primary")


def load_short_track_consensus_frames(root, group, dataset, bindings, raw_nodes):
    return _load_frames(root, group, dataset, bindings, raw_nodes, consensus_mode="short_track")


def _load_frames(root, group, dataset, bindings, raw_nodes, *, consensus_mode):
    root = Path(root).resolve()
    reader = Reader(root)

    _require(group in ("group00", "group01", "group02"), "bad group")
    _require(isinstance(dataset, str), "dataset must be str")
    _require(re.fullmatch("[A-Za-z0-9_-]+", dataset), "bad dataset")

    base = "association_collection_run/" + group
    returned_rel = base + f"/{dataset}_returned.npz"
    pre_rel = base + f"/observation/{dataset}_pre_ilp.npz"
    observer_rel = base + "/observation/MANIFEST.json"
    pairs_rel = base + "/observation/pairs/MANIFEST.json"

    for rel in (returned_rel, pre_rel, observer_rel, pairs_rel):
        entry = bindings.get(rel)
        _require(isinstance(entry, dict) and "bytes" in entry and "sha256" in entry,
                 "missing binding: " + rel)
        path = reader.bind(rel, entry["sha256"])
        _require(path.stat().st_size == entry["bytes"], "binding bytes mismatch: " + rel)

    coords = np.asarray(reader.arrays(returned_rel, bindings[returned_rel]["sha256"])["coords"])
    _require(coords.dtype == np.int16 and coords.ndim == 2 and coords.shape[1] == 4,
             "returned coords must be int16 Nx4")

    pre = reader.arrays(pre_rel, bindings[pre_rel]["sha256"])
    lookup = detector_lookup(pre, coords)

    observer = reader.json(observer_rel, bindings[observer_rel]["sha256"])
    _require(observer["pair_manifest_sha256"] == bindings[pairs_rel]["sha256"],
             "pairs manifest sha mismatch")

    pairs = reader.json(pairs_rel, bindings[pairs_rel]["sha256"])
    _require(pairs["schema_version"] == "biohub.e23.association_capture.v1", "bad schema_version")
    _require(pairs["status"] == "PAIR_CAPTURE_COMPLETE", "bad status")
    _require(pairs["submission_authorized"] is False, "submission_authorized must be False")

    records = [r for r in pairs["records"] if r.get("dataset") == dataset]
    _require(len(records) == 99, "expected 99 records")
    for rec in records:
        t_source = rec["t_source"]
        t_target = rec["t_target"]
        _require(type(t_source) is int, "t_source must be int")
        _require(type(t_target) is int, "t_target must be int")
        _require(t_target == t_source + 1, "t_target must be t_source+1")
    ts = sorted(rec["t_source"] for rec in records)
    _require(len(set(ts)) == 99, "expected 99 unique records")
    _require(ts == list(range(99)), "t_source must be 0..98")

    counts = pairs["frame_counts"][dataset]
    _require(type(counts) is list and len(counts) == 100, "frame_counts must be a list of 100")
    expected_counts = [int(np.count_nonzero(coords[:, 0] == t)) for t in range(100)]
    _require(counts == expected_counts, "frame_counts mismatch")

    by_t = {}
    for rec in records:
        t0 = rec["t_source"]
        n_src = expected_counts[t0]
        n_tgt = expected_counts[t0 + 1]
        _require(type(rec["n_source"]) is int, "n_source must be int")
        _require(type(rec["n_target"]) is int, "n_target must be int")
        _require(type(rec["dense_pairs"]) is int, "dense_pairs must be int")
        _require(rec["n_source"] == n_src, "n_source mismatch")
        _require(rec["n_target"] == n_tgt, "n_target mismatch")
        _require(rec["dense_pairs"] == n_src * n_tgt, "dense_pairs mismatch")
        by_t[t0] = rec

    _require(type(raw_nodes) is dict and bool(raw_nodes), "raw_nodes must be nonempty dict")
    ids_by_t = {}
    for key, node in raw_nodes.items():
        _require(type(key) is int, "raw node key must be int")
        _require(type(node) is dict, "raw node must be dict")
        node_id = node["node_id"]
        _require(type(node_id) is int, "node_id must be int")
        _require(node_id == key, "node_id must equal key")
        t = node["t"]
        _require(type(t) is int, "raw node t must be int")
        _require(0 <= t <= 99, "raw node t out of range")
        for axis in ("z", "y", "x"):
            v = node[axis]
            _require(type(v) in (int, float) and np.isfinite(float(v)),
                     "raw node coord not finite numeric")
        _require(node_id in lookup, "raw node id not in detector lookup")
        row = lookup[node_id]
        _require(tuple((t, node["z"], node["y"], node["x"])) == tuple(coords[row]),
                 "raw node coordinate mismatch")
        ids_by_t.setdefault(t, []).append(node_id)
    for t in list(ids_by_t):
        ids_by_t[t] = sorted(ids_by_t[t])

    active = set(
        t for t in range(99) if ids_by_t.get(t) and ids_by_t.get(t + 1)
    )
    _require(bool(active), "raw nodes have no active adjacent frames")

    frames = {}
    frame_receipts = []
    for t0 in range(99):
        rec = by_t[t0]
        packet_rel = base + "/observation/pairs/" + rec["path"]
        _require(type(rec["sha256"]) is str and type(rec["bytes"]) is int,
                 "packet record hash/bytes invalid")
        path = reader.bind(packet_rel, rec["sha256"])
        _require(path.stat().st_size == rec["bytes"], "packet bytes mismatch: " + packet_rel)
        packet = read_packet(reader.path(pairs_rel).parent, rec, coords)
        try:
            if t0 not in active:
                continue
            if consensus_mode:
                pair_args = (
                    packet.arrays['primary_forward_logits'],
                    packet.arrays['primary_reverse_logits'],
                    packet.arrays['secondary_forward_logits'],
                )
                if consensus_mode == "positive":
                    pairs = positive_reciprocal_consensus_pairs(*pair_args)
                elif consensus_mode == "primary":
                    pairs = primary_reciprocal_consensus_pairs(pair_args[0], pair_args[1])
                elif consensus_mode == "short_track":
                    pairs = reciprocal_consensus_pairs(*pair_args)
                else:
                    pairs = reciprocal_consensus_pairs(*pair_args)
                mapped = map_consensus_to_raw(
                    pairs,
                    packet.arrays['source_indices'].tolist(),
                    packet.arrays['target_indices'].tolist(),
                    lookup,
                    list(raw_nodes),
                )
                frames[t0] = [(int(a), int(b)) for a, b in mapped]
                frame_receipts.append(
                    dict(
                        t_source=t0,
                        detector_consensus_count=len(pairs),
                        raw_pairs=[list(pair) for pair in mapped],
                        original_logit_signatures={
                            name: rec['arrays'][name]
                            for name in (
                                'primary_forward_logits',
                                'primary_reverse_logits',
                                'secondary_forward_logits',
                            )
                        },
                    )
                )
                continue
            source_ids = ids_by_t[t0]
            target_ids = ids_by_t[t0 + 1]

            src_pos = {int(g): i for i, g in enumerate(packet.arrays["source_indices"])}
            tgt_pos = {int(g): i for i, g in enumerate(packet.arrays["target_indices"])}

            for gid in source_ids:
                _require(gid in lookup, "source id missing from detector lookup")
                _require(lookup[gid] in src_pos, "source row missing from packet")
            for gid in target_ids:
                _require(gid in lookup, "target id missing from detector lookup")
                _require(lookup[gid] in tgt_pos, "target row missing from packet")

            s_rows = [src_pos[int(lookup[gid])] for gid in source_ids]
            t_rows = [tgt_pos[int(lookup[gid])] for gid in target_ids]

            frame = {
                "t_source": t0,
                "t_target": t0 + 1,
                "source_ids": [int(g) for g in source_ids],
                "target_ids": [int(g) for g in target_ids],
                "primary_source_features": packet.arrays["primary_source_features"][s_rows],
                "primary_target_features": packet.arrays["primary_target_features"][t_rows],
                "secondary_source_features": packet.arrays["secondary_source_features"][s_rows],
                "secondary_target_features": packet.arrays["secondary_target_features"][t_rows],
            }
            _require(len(frame) == 8, "frame key count")
            frames[t0] = frame
            frame_receipts.append({
                "t_source": t0,
                "source_ids": frame["source_ids"],
                "target_ids": frame["target_ids"],
                "original_feature_signatures": {k: rec["arrays"][k] for k in FEATURES},
                "mapped_feature_signatures": array_signatures(
                    {k: frame[k] for k in FEATURES}),
            })
        finally:
            del packet

    reader.recheck()
    receipt = {
        "dataset": dataset,
        "group": group,
        "packet_count": 99,
        "frames": frame_receipts,
        "bindings": reader.bindings,
        "gt_read": False,
        "weights_loaded": False,
    }
    if consensus_mode:
        receipt['schema'] = (
            'E30_POSITIVE_CONSENSUS_INPUT_RECEIPT_V1'
            if consensus_mode == "positive"
            else 'E31_PRIMARY_CONSENSUS_INPUT_RECEIPT_V1'
            if consensus_mode == "primary"
            else 'E33_SHORT_TRACK_CONSENSUS_INPUT_RECEIPT_V1'
            if consensus_mode == "short_track"
            else 'E29_CONSENSUS_INPUT_RECEIPT_V1'
        )
    return frames, receipt
