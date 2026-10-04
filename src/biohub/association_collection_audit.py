"""Audit downloaded collection evidence, without executing models or reading GT."""

import json
import re
import time
import zipfile
from pathlib import Path, PurePosixPath

import numpy as np

from biohub.association_artifact_audit import audit_video, pair_manifest_summary
from biohub.association_capture import _require, _sha
from biohub.association_collection import validate_group_result
from biohub.association_collection_supervise import check_cumulative
from biohub.association_parity import array_signatures

WORKING = PurePosixPath("/kaggle/working")


class Reader:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.bindings = {}
        self.started = time.monotonic()

    def path(self, relative):
        name = PurePosixPath(relative)
        _require(not name.is_absolute() and ".." not in name.parts, "unsafe artifact path")
        path = self.root / str(name)
        _require(self.root in path.resolve().parents, "artifact outside download root")
        return path

    def remote(self, name):
        path = PurePosixPath(name)
        _require(".." not in path.parts and path.is_relative_to(WORKING), "unexpected runtime path")
        return str(path.relative_to(WORKING))

    def bind(self, name, expected=None):
        _require(time.monotonic() - self.started <= 300, "collection audit time budget exceeded")
        path = self.path(name)
        _require(path.stat().st_size <= 64 * 1024**2, "audit file budget exceeded")
        digest = _sha(path)
        _require(expected is None or digest == expected, f"artifact hash mismatch: {name}")
        record = {"bytes": path.stat().st_size, "sha256": digest}
        _require(name not in self.bindings or self.bindings[name] == record, "artifact changed during audit")
        self.bindings[name] = record
        return path

    def json(self, name, expected=None):
        return json.loads(self.bind(name, expected).read_text())

    def arrays(self, name, expected=None):
        path = self.bind(name, expected)
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            _require(
                len(entries) == len({r.filename for r in entries})
                and sum(r.file_size for r in entries) <= 128 * 1024**2,
                "graph NPZ expansion/duplicate guard",
            )
        with np.load(path, allow_pickle=False) as data:
            return {k: data[k] for k in data.files}

    def recheck(self):
        for name, record in list(self.bindings.items()):
            self.bind(name, record["sha256"])


def finite_budget(value, maximum, label):
    _require(type(value) in (int, float) and np.isfinite(value) and 0 <= value <= maximum, label)


def file_listing_summary(listing, expected_packets, max_run_bytes):
    files = {}
    for item in listing:
        name, size = item["path"], item["bytes"]
        path = PurePosixPath(name)
        _require(
            not path.is_absolute()
            and ".." not in path.parts
            and str(path) == name
            and name not in files
            and type(size) is int
            and size >= 0,
            "invalid output file inventory",
        )
        _require(path.name not in ("submission.csv", "ERROR.json"), "unexpected submission/error output")
        files[name] = size
    for path, size in expected_packets.items():
        _require(files.get(path) == size, "missing/resized remote packet")
    actual_packets = {p for p in files if "/observation/pairs/" in p and p.endswith(".npz")}
    _require(actual_packets == set(expected_packets), "unexpected remote packet files")
    run_bytes = sum(v for k, v in files.items() if k.startswith("association_collection_run/"))
    _require(run_bytes <= max_run_bytes, "whole collection root output budget exceeded")
    return {
        "file_count": len(files),
        "all_working_output_bytes": sum(files.values()),
        "collection_root_bytes": run_bytes,
        "matrix_packet_file_count": len(actual_packets),
    }


def audit_collection(
    root, reference, reference_sha, master_sha, source_pins, expected_dependencies, shared_runtime, listing, log_sha
):
    """Expected values must come from the sealed local dispatch, not this output tree."""
    reader = Reader(root)
    ref_name, master_name = "association_collection_reference.json", "association_collection_master.json"
    _require(reader.json(ref_name, reference_sha) == reference, "reference differs from frozen local plan")
    master = reader.json(master_name, master_sha)
    _require(
        master["schema_version"] == "biohub.association.collection36.master.v1"
        and master["reference_path"] == str(WORKING / ref_name)
        and master["repo_dir"] == str(WORKING / "tracking_repo")
        and master["expected_dependencies"] == expected_dependencies
        and master["submission_authorized"] is False,
        "master contract mismatch",
    )
    groups = reference["groups"]
    _require(
        len(groups) == 9 and [g["group_id"] for g in groups] == [f"group{i:02d}" for i in range(9)],
        "unexpected collection groups",
    )
    all_names = [n for g in groups for n in g["datasets"]]
    _require(
        len(all_names) == len(set(all_names)) == 36 and set(all_names) == set(reference["datasets"]),
        "invalid 36-video reference",
    )
    _require(
        [p["group_id"] for p in master["group_plans"]] == [g["group_id"] for g in groups], "master group order mismatch"
    )
    run = "association_collection_run"
    terminal = reader.json(f"{run}/RESULT.json")
    _require(
        terminal["status"] == "COLLECTION36_COMPLETE_REFERENCE_MATCHED"
        and terminal["master_sha256"] == master_sha
        and terminal["reference_sha256"] == reference_sha,
        "collection not complete or provenance changed",
    )
    for key in (
        "submission_authorized",
        "generalization_evidence",
        "paired_off_on_all36",
        "gt_scored",
        "training_started",
    ):
        _require(terminal[key] is False, "incorrect collection claim")
    _require(len(source_pins) == 25, "expected 25 runtime sources")
    actual_sources = {
        str(WORKING / p.relative_to(reader.root).as_posix())
        for folder in ("tracking_repo", "collection_payload")
        for p in (reader.root / folder).rglob("*.py")
    }
    _require(actual_sources == set(source_pins), "runtime source membership mismatch")
    for name, digest in source_pins.items():
        reader.bind(reader.remote(name), digest)
    results, completed, videos, packets = [], [], [], {}
    limits = reference["limits"]
    for group, plan_binding in zip(groups, master["group_plans"], strict=True):
        gid, names = group["group_id"], group["datasets"]
        prefix = f"{run}/{gid}"
        plan_name = f"association_collection_plans/{gid}.json"
        _require(plan_binding["path"] == str(WORKING / plan_name), "unexpected group plan path")
        plan = reader.json(plan_name, plan_binding["sha256"])
        _require(
            plan["schema_version"] == "biohub.association.collection36.group.v1"
            and plan["group_id"] == gid
            and plan["reference_path"] == str(WORKING / ref_name)
            and plan["datasets"] == {n: reference["datasets"][n] for n in names}
            and plan["data_dir"] == str(WORKING / "association_collection_images" / gid)
            and plan["source_path"] == str(WORKING / "tracking_repo/scripts/e23_observer_on.py")
            and plan["source_sha256"] == reference["source_sha256"]["on"]
            and plan["submission_authorized"] is False,
            "group plan drift",
        )
        _require(
            len(plan["source_inventory"]) == 25
            and {r["path"]: r["sha256"] for r in plan["source_inventory"]} == source_pins,
            "group source pins drift",
        )
        split_name = f"association_collection_plans/{gid}_splits.json"
        _require(plan["splits_file"] == str(WORKING / split_name), "unexpected split path")
        split_path = reader.bind(split_name)
        _require(json.loads(split_path.read_text()) == [{"split": 0, "train": [], "test": names}], "split mismatch")
        _require(
            plan["runtime_file_sha256"] == {**shared_runtime, str(WORKING / split_name): _sha(split_path)},
            "weights/config/reference declarations drift",
        )
        primary = WORKING / "tracking_repo/weights/unet_transformer/split_0/edge_predictor_best.pth"
        _require(plan["primary_weights"] == str(primary), "unexpected primary model")
        result = reader.json(f"{prefix}/RESULT.json")
        validate_group_result(result, plan, group, plan_binding["sha256"])
        image_paths = set()
        for item in result["input_inventory"]:
            name = PurePosixPath(item["path"])
            _require(
                not name.is_absolute()
                and ".." not in name.parts
                and name.parts[0] in {f"{n}.zarr" for n in names}
                and str(name) not in image_paths
                and type(item["bytes"]) is int
                and item["bytes"] > 0
                and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is not None,
                "invalid image input inventory",
            )
            image_paths.add(str(name))
        _require(
            {f"{n}.zarr/zarr.json" for n in names} <= image_paths
            and all(any(p.startswith(f"{n}.zarr/0/c/") for p in image_paths) for n in names),
            "incomplete image input inventory",
        )
        _require(
            result["reference_sha256"] == reference_sha
            and result["reference_raw_matched"] is True
            and result["dependencies"] == expected_dependencies
            and result["paired_off_on_this_group"] is False,
            "group result provenance drift",
        )
        process = reader.json(f"{run}/{gid}_PROCESS.json")
        _require(process["returncode"] == 0 and process["error"] is None, "group process failed")
        finite_budget(process["wall_seconds"], limits["group_wall_seconds"], "process time exceeded")
        finite_budget(process["peak_sampled_tree_rss_bytes"], limits["rss_bytes"], "process RSS exceeded")
        observer = reader.json(f"{prefix}/observation/MANIFEST.json", result["observer_manifest_sha256"])
        pair = reader.json(f"{prefix}/observation/pairs/MANIFEST.json", result["pair_manifest_sha256"])
        _require(
            observer["status"] == "ASSOCIATION_OBSERVATION_COMPLETE_NOT_PARITY"
            and observer["datasets"] == names
            and observer["graph_ID_mapping_complete"] is True
            and observer["candidate_threshold"] == 0.48
            and observer["candidate_limits"] == {"parents": None, "children": None}
            and observer["pair_manifest_sha256"] == result["pair_manifest_sha256"],
            "observer contract drift",
        )
        summary = pair_manifest_summary(pair, plan["datasets"])
        _require(
            (summary["packet_count"], summary["dense_pairs"], summary["packet_bytes"])
            == (result["pair_count"], result["dense_pairs"], result["packet_bytes"])
            and pair["writer_seconds"] == result["writer_seconds"]
            and observer["observer_seconds_excluding_final_manifest"] == result["observer_seconds"],
            "group count/time receipts disagree",
        )
        _require(
            len(observer["graphs"]) == 8
            and {(r["dataset"], r["stage"]) for r in observer["graphs"]}
            == {(n, s) for n in names for s in ("pre_ilp", "post_ilp")},
            "observer graph coverage",
        )
        for name in names:
            common, observed = [], []
            for stage in ("returned", "pre", "post"):
                arrays = reader.arrays(f"{prefix}/{name}_{stage}.npz")
                record = next(r for r in result["records"] if (r["dataset"], r["stage"]) == (name, stage))
                _require(array_signatures(arrays) == record["arrays"], "trace array receipt mismatch")
                common.append(arrays)
            for stage in ("pre_ilp", "post_ilp"):
                record = next(r for r in observer["graphs"] if (r["dataset"], r["stage"]) == (name, stage))
                _require(record["path"] == f"{name}_{stage}.npz", "unexpected observer path")
                path = f"{prefix}/observation/{record['path']}"
                observed.append(reader.arrays(path, record["sha256"]))
                _require(reader.bindings[path]["bytes"] == record["bytes"], "observer byte count changed")
            videos.append({"dataset": name, "group_id": gid, **audit_video(plan["datasets"][name], *common, *observed)})
        for record in pair["records"]:
            path = f"{prefix}/observation/pairs/{record['path']}"
            _require(path not in packets, "duplicate whole-run packet")
            packets[path] = record["bytes"]
        results.append(result)
        totals = check_cumulative(results, limits)
        completed.append(
            {
                "group_id": gid,
                "datasets": names,
                "result_sha256": reader.bindings[f"{prefix}/RESULT.json"]["sha256"],
                "process": process,
            }
        )
        progress = reader.json(f"{run}/{gid}_PROGRESS.json")
        _require(
            progress
            == {
                "status": "COLLECTION_PARTIAL",
                "completed_groups": completed,
                "totals": totals,
                "submission_authorized": False,
            },
            "progress receipt mismatch",
        )
    _require(terminal["completed_groups"] == completed and terminal["totals"] == totals, "final totals mismatch")
    _require(
        totals["pair_count"] == reference["expected_pair_packets"]
        and totals["dense_pairs"] == reference["expected_dense_pairs"],
        "final pair coverage mismatch",
    )
    finite_budget(terminal["wall_seconds_including_setup"], limits["whole_job_wall_seconds"], "whole wall exceeded")
    _require(
        sum(r["process"]["wall_seconds"] for r in completed) <= terminal["wall_seconds_including_setup"],
        "group time exceeds whole time",
    )
    inventory = file_listing_summary(listing, packets, limits["whole_output_bytes"])
    log_name = "biohub-e23-association-collection36.log"
    log = reader.json(log_name, log_sha)
    text = "".join(r["data"] for r in log)
    events = re.findall(r"D3 COLLECTION_(STARTED|FINISHED) (group\d{2}) (PID \d+|exit=-?\d+)", text)
    _require(
        len(events) == 18
        and [(kind, gid) for kind, gid, _ in events]
        == [(kind, g["group_id"]) for g in groups for kind in ("STARTED", "FINISHED")]
        and all(value == "exit=0" for kind, _, value in events if kind == "FINISHED"),
        "serial event log mismatch",
    )
    _require(
        f"D3 COLLECTION MASTER SEALED {master_sha}" in text and "COLLECTION36_COMPLETE_REFERENCE_MATCHED" in text,
        "missing terminal log evidence",
    )
    listed = {r["path"]: r["bytes"] for r in listing}
    _require(
        all(listed.get(n) == r["bytes"] for n, r in reader.bindings.items() if n != log_name),
        "download/API file list mismatch",
    )
    reader.recheck()
    return {
        "status": "COLLECTION36_ARTIFACT_AUDIT_PASS",
        "videos": videos,
        "totals": totals,
        "output_inventory": inventory,
        "master_sha256": master_sha,
        "reference_sha256": reference_sha,
        "bindings": reader.bindings,
        "wall_seconds": time.monotonic() - reader.started,
        "matrix_packets_reloaded_locally": 0,
        "weights_images_rehashed_locally": False,
        "matrix_scope": (
            "Terminal session file paths and HTTP verified byte lengths; local manifest and graph checks; "
            "matrix roundtrip/hash on Kaggle by byte-matched sources."
        ),
        "generalization_evidence": False,
        "gt_scored": False,
        "training_started": False,
        "submission_authorized": False,
    }
