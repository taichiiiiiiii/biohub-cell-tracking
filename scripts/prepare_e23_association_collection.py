"""Prepare literal E23 collection36 references, without inference or GT reads."""

import hashlib
import json
import re
from pathlib import Path

from biohub.association_capture import _json_bytes, _require, _sha
from scripts.prepare_e23_association_parity import PAYLOAD_FILES, raw_signature

AUDIT = "outputs/local/e23_association_target_20260908/PARENT_ARTIFACT_AUDIT.json"
AUDIT_SHA = "a830c98c85be60b901ca101043340b8494008588d7398891608d2f193f344dab"
D2 = "outputs/local/e26_diagnostic/d2b_eval12_v2_202609081002/result/RESULT.json"
D2_SHA = "2df2b4c2d4cb3aad978358c52b66a893de147b4428816448b2775e090753d767"


def plan_groups(names, diagnostic12):
    """Balance lineages, preserve the literal diagnostic12-first boundary."""
    _require(len(names) == len(set(names)) == 36, "expected 36 unique videos")
    _require(len(diagnostic12) == len(set(diagnostic12)) == 12, "expected 12 unique diagnostic videos")
    _require(set(diagnostic12) <= set(names), "diagnostic video outside collection")
    _require(all(re.fullmatch(r"(?:44b6|6bba)_[a-f0-9]{8}", n) for n in names), "invalid video name")
    groups = []
    for stage, videos, expected in (("diagnostic12", diagnostic12, 6),
                                     ("remaining24", set(names) - set(diagnostic12), 12)):
        left = sorted(n for n in videos if n.startswith("44b6_"))
        right = sorted(n for n in videos if n.startswith("6bba_"))
        _require(len(left) == len(right) == expected, "lineage coverage mismatch")
        for offset in range(0, expected, 2):
            groups.append({"group_id": f"group{len(groups):02d}", "stage": stage,
                           "datasets": sorted(left[offset:offset + 2] + right[offset:offset + 2])})
    return groups


def reference_counts(row):
    _require(row["dtype"] == "<i2" and row["columns"] == ["t", "z", "y", "x"]
             and row["stage"] == "post_detection_pre_graph_pre_ilp", "wrong coordinate reference")
    pairs = row["frame_counts"]
    _require(all(type(t) is int and type(n) is int for t, n in pairs), "noninteger frame count")
    counts = dict(pairs)
    _require(len(counts) == len(pairs) and set(counts) <= set(range(100)), "invalid frame coverage")
    ordered = [counts.get(t, 0) for t in range(100)]
    _require(all(0 <= n <= 2048 for n in ordered) and sum(ordered) == row["rows"], "detector count mismatch")
    _require(all(a * b <= 1_000_000 for a, b in zip(ordered[:-1], ordered[1:], strict=True)), "pair exceeds budget")
    _require(re.fullmatch(r"[0-9a-f]{64}", row["coordinate_sha256"]) is not None, "invalid coordinate SHA")
    return ordered


def build(repo):
    bindings = []

    def read(relative, expected=None):
        path = repo / relative
        digest = _sha(path)
        _require(expected is None or digest == expected, f"frozen input changed: {relative}")
        bindings.append({"path": relative, "bytes": path.stat().st_size, "sha256": digest})
        return path

    audit = json.loads(read(AUDIT, AUDIT_SHA).read_text())
    _require(audit["status"] == "PARENT_PUBLIC4_ARTIFACT_AUDIT_PASS", "public4 gate incomplete")
    for relative, entry in audit["evidence"].items():
        path = repo / relative
        _require(_sha(path) == entry["sha256"] and path.stat().st_size == entry["bytes"], "audit evidence changed")
    diagnostic = json.loads(read(D2, D2_SHA).read_text())["datasets"]
    manifest = read("outputs/kaggle/e22_bidir030_eval36_reference/"
                    "detector_coordinates_harmonic_association_production_single.jsonl",
                    "4355d4fe0c70c4152c09fb55f4988d46db434fcb924b2859c9b22fee7928d1a3")
    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    names = [r["dataset"] for r in rows]
    groups = plan_groups(names, diagnostic)
    raw_root = repo / ("outputs/kaggle/e22_bidir030_eval36_raw/tracking_repo/"
                       "predictions/unknown/unet_transformer_val/split_0")
    _require(set(p.stem for p in raw_root.glob("*.geff")) == set(names), "raw36 coverage mismatch")
    datasets, inventory = {}, []
    for row in sorted(rows, key=lambda r: r["dataset"]):
        name = row["dataset"]
        counts = reference_counts(row)
        datasets[name] = {"frame_counts": counts, "coordinate_sha256": row["coordinate_sha256"],
                          "raw_graph_signature": raw_signature(raw_root / f"{name}.geff")}
        for p in sorted((raw_root / f"{name}.geff").rglob("*")):
            if p.is_file():
                inventory.append({"path": p.relative_to(raw_root).as_posix(),
                                  "bytes": p.stat().st_size, "sha256": _sha(p)})
    dense_total = 0
    for group in groups:
        group["detectors"] = sum(sum(datasets[n]["frame_counts"]) for n in group["datasets"])
        group["dense_pairs"] = sum(sum(a * b for a, b in zip(datasets[n]["frame_counts"][:-1],
                                                           datasets[n]["frame_counts"][1:], strict=True))
                                   for n in group["datasets"])
        dense_total += group["dense_pairs"]
    _require(dense_total == 341106074, "dense total changed")
    _require(sum(g["detectors"] for g in groups) == 910952, "detector total changed")
    parity_plan = json.loads(read("outputs/local/e23_association_target_20260908/terminal/"
                                 "association_public4_plan.json",
                                 "a8b951b2fbf378d31054fcfcb3846509fe0f66d273ea6bfa60891b44f7880b54").read_text())
    for relative in PAYLOAD_FILES:
        p = read(relative)
        _require(p.read_bytes() == (repo / "outputs/local/e23_association_target_20260908/"
                                  "terminal_graphs/association_payload" / relative).read_bytes(),
                 "reviewed payload changed")
    return {"schema_version": "biohub.association.collection36.preparation.v1",
            "status": "REFERENCES_PREPARED_NOT_DISPATCHED", "datasets": datasets, "groups": groups,
            "raw_inventory": {"root": raw_root.relative_to(repo).as_posix(), "files": len(inventory),
                              "bytes": sum(r["bytes"] for r in inventory),
                              "sha256": hashlib.sha256(_json_bytes(inventory)).hexdigest(),
                              "serialization": "sorted relative file records; _json_bytes"},
            "source_sha256": parity_plan["source_sha256"], "bindings": bindings,
            "limits": {"group_wall_seconds": 3600, "whole_job_wall_seconds": 14400,
                       "rss_bytes": 24 * 1024**3, "start_free_disk_bytes": 16 * 1024**3,
                       "whole_output_bytes": 12 * 1024**3, "whole_writer_seconds": 1200,
                       "whole_observer_seconds": 1200, "dense_pairs_per_packet": 1_000_000,
                       "nodes_per_side": 2048, "dense_pairs_per_run": 450_000_000},
            "expected_pair_packets": 3564, "expected_dense_pairs": dense_total,
            "diagnostic12": sorted(diagnostic), "parent_only": True, "seed": 23826,
            "collection_runner_implemented": False, "submission_authorized": False,
            "gt_read": False, "training_started": False, "generalization_evidence": False}


if __name__ == "__main__":
    print(json.dumps(build(Path(__file__).resolve().parents[1]), sort_keys=True, indent=2))
