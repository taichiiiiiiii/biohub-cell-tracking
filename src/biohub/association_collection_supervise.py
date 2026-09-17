"""Nine serial collection groups, cumulative budgets, no retries or submission."""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from biohub.association_capture import _json_bytes, _require, _sha
from biohub.association_collection import load_reference, validate_group_result
from biohub.association_supervise import process_tree_rss


def output_bytes(root):
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def record(path, value):
    with path.open("xb") as stream:
        stream.write(_json_bytes(value))


def check_cumulative(results, limits):
    totals = {key: sum(r[key] for r in results) for key in
              ("pair_count", "dense_pairs", "packet_bytes", "writer_seconds", "observer_seconds")}
    _require(totals["writer_seconds"] <= limits["whole_writer_seconds"], "cumulative writer time exceeded")
    _require(totals["observer_seconds"] <= limits["whole_observer_seconds"], "cumulative observer time exceeded")
    _require(totals["dense_pairs"] <= limits["dense_pairs_per_run"], "cumulative dense pair budget exceeded")
    return totals


def supervise_collection(master_path, root, payload, notebook_started):
    _require(Path("/kaggle/working").is_dir(), "collection supervisor is Kaggle-only")
    root.mkdir(parents=True, exist_ok=False)
    completed, results = [], []
    try:
        master_sha = _sha(master_path)
        master = json.loads(master_path.read_text())
        _require(master["schema_version"] == "biohub.association.collection36.master.v1"
                 and master["submission_authorized"] is False, "invalid collection master")
        reference = load_reference(Path(master["reference_path"]))
        limits = reference["limits"]
        groups = reference["groups"]
        _require([r["group_id"] for r in master["group_plans"]] == [g["group_id"] for g in groups],
                 "master group order/coverage mismatch")
        _require(len({r["path"] for r in master["group_plans"]}) == 9, "duplicate group plan")
        _require(shutil.disk_usage(root).free >= limits["start_free_disk_bytes"], "less than 16 GiB free")
        deadline = notebook_started + limits["whole_job_wall_seconds"]
        tokens = [t.strip() for t in os.environ.get("CUDA_VISIBLE_DEVICES", "0").split(",") if t.strip()]
        _require(tokens and tokens[0] != "-1", "no CUDA token")
        for group, bound in zip(groups, master["group_plans"], strict=True):
            gid = group["group_id"]
            plan_path = Path(bound["path"])
            _require(_sha(master_path) == master_sha and _sha(plan_path) == bound["sha256"], "plan changed")
            plan = json.loads(plan_path.read_text())
            _require(plan["group_id"] == gid and plan["reference_path"] == master["reference_path"],
                     "wrong group plan")
            _require(plan["datasets"] == {n: reference["datasets"][n] for n in group["datasets"]},
                     "group references changed")
            _require(time.monotonic() < deadline, "whole deadline before group")
            _require(output_bytes(root) <= limits["whole_output_bytes"], "whole output budget exceeded")
            command = [sys.executable, str(payload / "scripts/e23_association_collect.py"),
                       "--plan", str(plan_path), "--root", str(root / gid)]
            env = {**os.environ,
                   "PYTHONPATH": str(payload / "src") + os.pathsep + str(Path(master["repo_dir"]) / "src"),
                   "CUDA_VISIBLE_DEVICES": tokens[0], "BIOHUB_GPU_SHARD": "single", "PYTHONHASHSEED": "0"}
            started, peak_rss, error = time.monotonic(), 0, None
            with (root / f"{gid}.log").open("xb") as log:
                process = subprocess.Popen(command, cwd=master["repo_dir"], env=env, stdout=log,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                print(f"D3 COLLECTION_STARTED {gid} PID {process.pid}", flush=True)
                try:
                    while process.poll() is None:
                        _require(time.monotonic() < min(started + limits["group_wall_seconds"], deadline),
                                 "group/whole wall budget exceeded")
                        peak_rss = max(peak_rss, process_tree_rss(process.pid))
                        _require(peak_rss <= limits["rss_bytes"], "process-tree RSS budget exceeded")
                        _require(output_bytes(root) <= limits["whole_output_bytes"], "whole output budget exceeded")
                        time.sleep(1.)
                except Exception as exc:
                    error = str(exc)
                    if process.poll() is None:
                        try:
                            os.killpg(process.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                        try:
                            process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
                code = process.wait()
            process_record = {"returncode": code, "error": error, "wall_seconds": time.monotonic() - started,
                              "peak_sampled_tree_rss_bytes": peak_rss}
            record(root / f"{gid}_PROCESS.json", process_record)
            print(f"D3 COLLECTION_FINISHED {gid} exit={code}", flush=True)
            _require(code == 0 and error is None, "collection group failed; retained PROCESS/log/ERROR")
            _require(process_record["wall_seconds"] <= limits["group_wall_seconds"]
                     and time.monotonic() <= deadline, "completed group exceeded wall budget")
            _require(_sha(master_path) == master_sha and _sha(plan_path) == bound["sha256"], "plan changed after group")
            result_path = root / gid / "RESULT.json"
            result = json.loads(result_path.read_text())
            validate_group_result(result, plan, group, bound["sha256"])
            _require(result["dependencies"] == master["expected_dependencies"], "dependencies differ from public4")
            for filename, key in (("observation/MANIFEST.json", "observer_manifest_sha256"),
                                  ("observation/pairs/MANIFEST.json", "pair_manifest_sha256")):
                _require(_sha(root / gid / filename) == result[key], "observation manifest changed")
            results.append(result)
            totals = check_cumulative(results, limits)
            completed.append({"group_id": gid, "datasets": group["datasets"],
                              "result_sha256": _sha(result_path), "process": process_record})
            record(root / f"{gid}_PROGRESS.json", {"status": "COLLECTION_PARTIAL", "completed_groups": completed,
                                                  "totals": totals, "submission_authorized": False})
        names = [n for group in completed for n in group["datasets"]]
        _require(len(names) == len(set(names)) == 36 and set(names) == set(reference["datasets"]),
                 "incomplete final video coverage")
        _require(totals["pair_count"] == reference["expected_pair_packets"]
                 and totals["dense_pairs"] == reference["expected_dense_pairs"], "incomplete final pair coverage")
        result = {"status": "COLLECTION36_COMPLETE_REFERENCE_MATCHED", "completed_groups": completed,
                  "totals": totals, "master_sha256": master_sha,
                  "reference_sha256": _sha(Path(master["reference_path"])),
                  "wall_seconds_including_setup": time.monotonic() - notebook_started,
                  "submission_authorized": False, "generalization_evidence": False,
                  "paired_off_on_all36": False, "gt_scored": False, "training_started": False}
        _require(time.monotonic() <= deadline and output_bytes(root) + len(_json_bytes(result))
                 <= limits["whole_output_bytes"], "final time/output budget exceeded")
        record(root / "RESULT.json", result)
        print(json.dumps(result, sort_keys=True), flush=True)
        return result
    except Exception as exc:
        record(root / "ERROR.json", {"status": "ERROR", "error": str(exc),
                                     "completed_groups": completed, "submission_authorized": False})
        raise
