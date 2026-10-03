"""Join fixed pre-stage GT correspondences to bound packets; no labels or scores."""

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from biohub.association_capture import _json_bytes, _require, _sha
from biohub.association_packet_readout import detector_lookup, query_pair, read_packet
from biohub.association_parity import array_signatures


def fingerprint(stage, pre, coords):
    return {
        "stage_sha256": hashlib.sha256(_json_bytes(stage)).hexdigest(),
        "pre_arrays": array_signatures(pre),
        "detector_arrays": array_signatures({"coords": coords}),
    }


def plan_queries(stage, pre, coords, manifest_path, manifest_sha):
    """Return exact packet downloads without reading any model probability matrix."""
    before = fingerprint(stage, pre, coords)
    manifest_path = Path(manifest_path)
    _require(_sha(manifest_path) == manifest_sha, "pair manifest changed")
    manifest = json.loads(manifest_path.read_text())
    _require(
        manifest["schema_version"] == "biohub.e23.association_capture.v1"
        and manifest["status"] == "PAIR_CAPTURE_COMPLETE"
        and manifest["submission_authorized"] is False,
        "invalid complete capture manifest",
    )
    _require(
        stage["schema_version"] == "biohub.association.graph_stage_diagnostic.v1"
        and stage["status"] == "GRAPH_STAGE_DIAGNOSTIC_COMPLETE"
        and stage["matching_mode"] == "distance7um_without_edge_short_circuit"
        and stage["official_score_computed"] is False
        and stage["matrix_read"] is False
        and stage["submission_authorized"] is False,
        "invalid graph stage diagnostic",
    )
    name = stage["dataset"]
    _require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]+", name) is not None, "unsafe dataset name")
    counts = manifest["frame_counts"][name]
    _require(
        len(counts) == 100 and counts == [int(np.count_nonzero(coords[:, 0] == t)) for t in range(100)],
        "capture/stage detector counts mismatch",
    )
    lookup = detector_lookup(pre, coords)
    mapped_gt, submitted = {}, set()
    for row in stage["node_maps"]["pre"]:
        node = row["submitted_node_id"]
        _require(type(node) is int and node in lookup and node not in submitted, "stage node mapping mismatch")
        submitted.add(node)
        _require(
            tuple(row[k] for k in ("t", "z", "y", "x")) == tuple(coords[lookup[node]]),
            "stage/pre node coordinate mismatch",
        )
        gt_id = row["gt_node_id"]
        if gt_id is not None:
            _require(type(gt_id) is int and gt_id not in mapped_gt, "duplicate/invalid GT node mapping")
            mapped_gt[gt_id] = node
    _require(submitted == set(lookup), "incomplete stage node map")
    candidate_probs = {}
    for s, t, p in zip(pre["edge_source_id"], pre["edge_target_id"], pre["edge_edge_prob"], strict=True):
        _require(np.issubdtype(type(s), np.integer) and np.issubdtype(type(t), np.integer), "noninteger candidate ID")
        pair = int(s), int(t)
        _require(
            pair not in candidate_probs
            and s in lookup
            and t in lookup
            and coords[lookup[t], 0] == coords[lookup[s], 0] + 1,
            "duplicate/dangling/nonadjacent candidate",
        )
        _require(np.isfinite(p) and 0.48 < p <= 1, "invalid candidate probability")
        candidate_probs[pair] = float(p)
    records = [r for r in manifest["records"] if r["dataset"] == name]
    packet_by_time = {r["t_source"]: r for r in records}
    _require(
        len(records) == len(packet_by_time) == 99 and set(packet_by_time) == set(range(99)),
        "incomplete/duplicate video packet coverage",
    )
    for t, r in packet_by_time.items():
        _require(
            r["path"] == f"{name}/pair_{t:04d}.npz"
            and r["t_target"] == t + 1
            and (r["n_source"], r["n_target"], r["dense_pairs"])
            == (counts[t], counts[t + 1], counts[t] * counts[t + 1]),
            "packet plan/frame mismatch",
        )
    queries, unmatched, gt_ids, gt_pairs = [], [], set(), set()
    _require(stage["summary"]["gt_edges"] == len(stage["records"]), "incomplete stage edge count")
    for index, row in enumerate(stage["records"]):
        edge_id, gs, gt = row["gt_edge_id"], row["gt_source_id"], row["gt_target_id"]
        _require(
            all(type(i) is int for i in (edge_id, gs, gt))
            and edge_id not in gt_ids
            and (gs, gt) not in gt_pairs
            and row["dataset"] == name,
            "duplicate/invalid GT edge",
        )
        gt_ids.add(edge_id)
        gt_pairs.add((gs, gt))
        view = row["stage_views"]["pre"]
        source, target = mapped_gt.get(gs), mapped_gt.get(gt)
        _require((view["source_id"], view["target_id"]) == (source, target), "stage/GT assignment mismatch")
        both = source is not None and target is not None
        _require(
            view["both_matched"] is both and view["edge_present"] is ((source, target) in candidate_probs),
            "stage/candidate edge presence mismatch",
        )
        for side, node in (("source", source), ("target", target)):
            position = view[f"{side}_position"]
            _require(
                (position is None) if node is None else tuple(position) == tuple(coords[lookup[node]]),
                "stage view coordinate mismatch",
            )
        if not both:
            unmatched.append(index)
            continue
        frame = int(coords[lookup[source], 0])
        _require(frame in packet_by_time and coords[lookup[target], 0] == frame + 1, "query crosses wrong frames")
        queries.append(
            {
                "record_index": index,
                "t_source": frame,
                "source_id": source,
                "target_id": target,
                "pre_probability": candidate_probs.get((source, target)),
            }
        )
    times = sorted({q["t_source"] for q in queries})
    _require(
        _sha(manifest_path) == manifest_sha and fingerprint(stage, pre, coords) == before,
        "inputs changed during planning",
    )
    return {
        "dataset": name,
        "queries": queries,
        "unmatched_record_indices": unmatched,
        "packets": [packet_by_time[t] for t in times],
        "matrix_read": False,
        "manifest_sha256": manifest_sha,
        "input_fingerprint": before,
        "training_label_assigned": False,
        "submission_authorized": False,
    }


def attach_packet_evidence(stage, pre, coords, manifest_path, manifest_sha):
    """One packet in memory at a time; raise on missing data, never convert missing to zero."""
    before = fingerprint(stage, pre, coords)
    plan = plan_queries(stage, pre, coords, manifest_path, manifest_sha)
    lookup = detector_lookup(pre, coords)
    records = [
        {
            "gt_edge_id": r["gt_edge_id"],
            "gt_source_id": r["gt_source_id"],
            "gt_target_id": r["gt_target_id"],
            "fixed_pre_pair_state": r["fixed_pre_pair_state"],
            "packet_status": "UNMATCHED_ENDPOINT",
            "association": None,
        }
        for r in stage["records"]
    ]
    grouped = defaultdict(list)
    for query in plan["queries"]:
        grouped[query["t_source"]].append(query)
    for record in plan["packets"]:
        packet = read_packet(Path(manifest_path).parent, record, coords)
        for query in grouped[record["t_source"]]:
            evidence = query_pair(packet, lookup, query["source_id"], query["target_id"], query["pre_probability"])
            row = records[query["record_index"]]
            row.update(packet_status="OBSERVED", association=evidence)
        del packet
    _require(
        _sha(Path(manifest_path)) == manifest_sha and fingerprint(stage, pre, coords) == before,
        "diagnostic inputs changed during readout",
    )
    _require(sum(r["association"] is not None for r in records) == len(plan["queries"]), "incomplete query coverage")
    for record in plan["packets"]:
        path = Path(manifest_path).parent / record["path"]
        _require(
            path.stat().st_size == record["bytes"] and _sha(path) == record["sha256"], "packet changed after query"
        )
    return {
        "schema_version": "biohub.association.stage_packet_readout.v1",
        "dataset": stage["dataset"],
        "status": "STAGE_PACKET_READOUT_COMPLETE",
        "records": records,
        "summary": {
            "gt_edges": len(records),
            "packets_read": len(plan["packets"]),
            "packet_states": dict(Counter(r["packet_status"] for r in records)),
        },
        "input_fingerprint": before,
        "manifest_sha256": manifest_sha,
        "packet_bindings": [{k: r[k] for k in ("path", "bytes", "sha256")} for r in plan["packets"]],
        "all_dense_packets_read": len(plan["packets"]) == 99,
        "official_score_computed": False,
        "training_label_assigned": False,
        "submission_authorized": False,
    }
