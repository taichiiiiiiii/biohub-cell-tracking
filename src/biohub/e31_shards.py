from __future__ import annotations

import csv
import hashlib
import heapq
import json
import math
import os
import signal
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path

from biohub.screen_output_bounds import ScreenNodeSerializer, verify_screen_output_bounds

CSV_COLS = ["id", "dataset", "row_type", "node_id", "t", "z", "y", "x", "source_id", "target_id"]


def _stream_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _load_child_receipt(child_dir: Path) -> dict:
    p = child_dir / "e31_submission_receipt.json"
    if not p.exists():
        raise FileNotFoundError(f"Missing receipt: {p}")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_child_bounds(child_dir: Path) -> dict:
    p = child_dir / "e31_output_bounds.json"
    if not p.exists():
        raise FileNotFoundError(f"Missing bounds: {p}")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _validated_child(child_dir: Path, assigned: list[str], expected_hashes: dict) -> tuple[dict, dict]:
    receipt = _load_child_receipt(child_dir)
    if receipt["stems"] != assigned:
        raise ValueError("receipt stems mismatch")
    if set(receipt["shapes"]) != set(assigned):
        raise ValueError("receipt shapes mismatch")
    if receipt["E31_HASHES"] != expected_hashes:
        raise ValueError("E31 hashes mismatch")
    csv_path = child_dir / "submission.csv"
    if receipt["csv_sha256"] != _stream_sha256(csv_path):
        raise ValueError("csv sha256 mismatch")
    if receipt.get("hypothesis") != "primary-only reciprocal consensus":
        raise ValueError("hypothesis mismatch")
    elapsed = receipt.get("elapsed")
    if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)):
        raise ValueError("elapsed type invalid")
    if not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError("elapsed non-finite or negative")
    bounds = _load_child_bounds(child_dir)
    verify_screen_output_bounds(bounds, csv_path, shapes=receipt["shapes"])
    seen: set[str] = set()
    prev_ds: str | None = None
    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != CSV_COLS:
            raise ValueError("CSV header mismatch")
        for index, row in enumerate(reader):
            if len(row) != len(CSV_COLS):
                raise ValueError(f"row {index} column count mismatch")
            if any(k is None or v is None for k, v in row.items()):
                raise ValueError(f"row {index} has None key/value")
            if row["id"] != str(index):
                raise ValueError(f"row {index} id mismatch")
            ds = row["dataset"]
            if ds not in assigned:
                raise ValueError(f"row {index} dataset not in assigned")
            if prev_ds is not None and ds < prev_ds:
                raise ValueError(f"row {index} dataset not nondecreasing")
            prev_ds = ds
            seen.add(ds)
    if seen != set(assigned):
        raise ValueError("seen datasets != assigned")
    return receipt, bounds


def _merge_csv(working_dir: Path, child_dirs: list[Path], receipts: list[dict], bounds: list[dict]) -> dict:
    global_shapes = {}
    for r in receipts:
        for ds, shape in r["shapes"].items():
            global_shapes.setdefault(ds, shape)
    global_shapes = {k: global_shapes[k] for k in sorted(global_shapes)}
    serializer = ScreenNodeSerializer(global_shapes)
    correction_map: dict[tuple[int, str], dict] = {}
    for idx, b in enumerate(bounds):
        for c in b.get("corrections", []):
            key = (idx, str(c["row_id"]))
            if key in correction_map:
                raise ValueError(f"Duplicate correction key {key}")
            correction_map[key] = c
    node_counts: dict[str, int] = {ds: 0 for ds in global_shapes}
    consumed: set[tuple[int, str]] = set()
    with ExitStack() as stack:
        readers = []
        for idx, cd in enumerate(child_dirs):
            fh = stack.enter_context(open(cd / "submission.csv", newline="", encoding="utf-8"))
            readers.append((csv.DictReader(fh), idx))
        dst = stack.enter_context(open(working_dir / "submission.csv", "x", newline="", encoding="utf-8"))
        writer = csv.DictWriter(dst, fieldnames=CSV_COLS)
        writer.writeheader()

        def tagged(reader, idx):
            for row in reader:
                yield (idx, row)

        merged = heapq.merge(
            *(tagged(r, i) for r, i in readers),
            key=lambda item: item[1]["dataset"],
        )
        for new_id, (idx, row) in enumerate(merged):
            row_out = dict(row)
            row_out["id"] = str(new_id)
            ckey = (idx, str(row["id"]))
            if ckey in correction_map:
                corr = correction_map[ckey]
                serialized = serializer(corr["node"], row["dataset"], new_id)
                expected = {k: str(v) for k, v in serialized.items()}
                if expected != {k: str(v) for k, v in row_out.items()}:
                    raise ValueError(f"Correction mismatch at child={idx} row_id={row['id']}")
                consumed.add(ckey)
            if row_out.get("row_type") == "node":
                node_counts[row["dataset"]] += 1
            writer.writerow(row_out)
    unconsumed = set(correction_map.keys()) - consumed
    if unconsumed:
        raise ValueError(f"Unconsumed corrections: {unconsumed}")
    for ds in global_shapes:
        serializer.reports[ds]["node_count"] = node_counts[ds]
    snapshot = serializer.snapshot()
    verify_screen_output_bounds(snapshot, working_dir / "submission.csv", shapes=global_shapes)
    return snapshot


def merge_shards(working_dir: Path, assignments: list[list[str]], expected_hashes: dict) -> dict:
    if type(assignments) is not list or len(assignments) not in (1, 2):
        raise ValueError("assignments must be a list of length 1 or 2")
    all_assigned: list[str] = []
    child_dirs: list[Path] = []
    for i, assigned in enumerate(assignments):
        if type(assigned) is not list or not assigned:
            raise ValueError(f"assignment[{i}] must be a non-empty list of str")
        if any(type(a) is not str for a in assigned):
            raise TypeError(f"assignment[{i}] contains non-str elements")
        if assigned != sorted(set(assigned)):
            raise ValueError(f"assignment[{i}] must be sorted and unique")
        all_assigned.extend(assigned)
        child_dirs.append(working_dir / f"e31_shard_{i}")
    if len(set(all_assigned)) != len(all_assigned):
        raise ValueError("duplicate datasets across assignments")

    validated = [_validated_child(cd, asgn, expected_hashes) for cd, asgn in zip(child_dirs, assignments, strict=False)]
    receipts, bounds_list = zip(*validated, strict=False)

    ref_keys = ("insertion_receipt", "deepcenter_receipt", "hypothesis")
    ref = receipts[0]
    for r in receipts[1:]:
        for k in ref_keys:
            if k not in ref or k not in r:
                raise KeyError(f"missing key '{k}' in child receipt")
            if ref[k] != r[k]:
                raise ValueError(f"mismatch on '{k}' between shards")

    final_files = ["submission.csv", "run_stats.csv", "e31_output_bounds.json", "e31_submission_receipt.json"]
    for fn in final_files:
        if (working_dir / fn).exists():
            raise FileExistsError(fn)

    stats_rows: list[dict] = []
    headers: list[str] | None = None
    for cd, asgn in zip(child_dirs, assignments, strict=False):
        p = cd / "run_stats.csv"
        with open(p, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            hdr = reader.fieldnames or []
            if "dataset" not in hdr:
                raise ValueError("run_stats.csv missing 'dataset' column")
            if headers is None:
                headers = list(hdr)
            elif list(hdr) != headers:
                raise ValueError("run_stats.csv header mismatch between shards")
            rows = list(reader)
            if any(None in row.keys() or None in row.values() for row in rows):
                raise ValueError("None key/value in run_stats.csv")
            ds_vals = [row["dataset"] for row in rows]
            if len(ds_vals) != len(asgn) or set(ds_vals) != set(asgn):
                raise ValueError("dataset rows do not match assigned list")
            if len(set(ds_vals)) != len(ds_vals):
                raise ValueError("duplicate dataset in run_stats.csv")
            stats_rows.extend(rows)
    stats_rows.sort(key=lambda r: r["dataset"])

    snapshot = _merge_csv(working_dir, child_dirs, list(receipts), list(bounds_list))

    for cd, receipt in zip(child_dirs, receipts, strict=False):
        actual_sha = _stream_sha256(cd / "submission.csv")
        if actual_sha != receipt["csv_sha256"]:
            raise ValueError("child CSV changed after validation")

    merged_sha = _stream_sha256(working_dir / "submission.csv")
    all_stems = sorted(all_assigned)
    all_shapes = {ds: r["shapes"][ds] for r in receipts for ds in sorted(r["shapes"])}
    all_shapes = dict(sorted(all_shapes.items()))

    with open(working_dir / "e31_output_bounds.json", "x", encoding="utf-8") as f:
        json.dump(snapshot, f)

    with open(working_dir / "run_stats.csv", "x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(stats_rows)

    max_elapsed = max(r["elapsed"] for r in receipts)
    parent_receipt = {
        "csv_sha256": merged_sha,
        "stems": all_stems,
        "shapes": all_shapes,
        "E31_HASHES": expected_hashes,
        "insertion_receipt": ref["insertion_receipt"],
        "deepcenter_receipt": ref["deepcenter_receipt"],
        "hypothesis": ref["hypothesis"],
        "elapsed": max_elapsed,
        "elapsed_kind": "max_shard_predict_seconds",
        "shards": list(receipts),
    }
    with open(working_dir / "e31_submission_receipt.json", "x", encoding="utf-8") as f:
        json.dump(parent_receipt, f)
    return parent_receipt


EXACT7 = (
    "WORKING_DIR",
    "REPO_DIR",
    "TEST_DIR",
    "_ps",
    "_primary_materialized_path",
    "_deepcenter_materialized_path",
    "SECONDARY_WEIGHTS_PATH",
)

CHILD_CODE = """\
import sys, json, runpy
from pathlib import Path
_PK = ["WORKING_DIR","REPO_DIR","TEST_DIR","_ps",
       "_primary_materialized_path","_deepcenter_materialized_path","SECONDARY_WEIGHTS_PATH"]
with open(sys.argv[1]) as _f:
    _job = json.load(_f)
for _k in _PK:
    if _k in _job:
        _job[_k] = Path(_job[_k])
runpy.run_path(sys.argv[2], init_globals=_job)
"""


def run_workers(
    job: dict,
    payloadroot: Path,
    cuda_tokens: list[str],
    timeout_seconds: float = 39600.0,
) -> dict:
    if (
        len(cuda_tokens) < 2
        or not isinstance(cuda_tokens[0], str)
        or not isinstance(cuda_tokens[1], str)
        or cuda_tokens[0] == ""
        or cuda_tokens[1] == ""
        or cuda_tokens[0] == cuda_tokens[1]
    ):
        raise ValueError("cuda_tokens must have >=2 distinct nonempty strings")
    if not (math.isfinite(timeout_seconds) and timeout_seconds > 0):
        raise ValueError("timeout_seconds must be finite positive")

    test_dir: Path = job["TEST_DIR"]
    if list(test_dir.glob("*.geff")):
        raise ValueError("GT geff forbidden in test_dir")
    stems = sorted(p.stem for p in test_dir.glob("*.zarr"))
    if not stems:
        raise ValueError("no zarr stems found")
    worker_count = min(2, len(stems))
    assignments = [stems[i::worker_count] for i in range(worker_count)]

    runtime = payloadroot / "scripts" / "e31_submission_runtime.py"
    hashes: dict = job["E31_HASHES"]
    if "scripts/e31_submission_runtime.py" not in hashes:
        raise ValueError("runtime path missing from E31_HASHES")
    for rel, expected in hashes.items():
        if os.path.isabs(rel) or ".." in rel.split("/"):
            raise ValueError(f"unsafe hash key: {rel}")
        fp = payloadroot / rel
        if not fp.exists():
            raise FileNotFoundError(fp)
        if _stream_sha256(fp) != expected:
            raise ValueError(f"hash mismatch: {rel}")

    parent_work: Path = job["WORKING_DIR"]
    repo_dir: Path = job["REPO_DIR"]
    child_dirs = []
    for i in range(worker_count):
        cd = parent_work / f"e31_shard_{i}"
        cd.mkdir(exist_ok=False)
        child_dirs.append(cd)

    procs: list[subprocess.Popen] = []
    logfiles = []
    t0 = time.monotonic()
    with ExitStack() as stack:
        try:
            for i in range(worker_count):
                cjob = {}
                for k, v in job.items():
                    cjob[k] = str(v) if k in EXACT7 else v
                cjob["WORKING_DIR"] = str(child_dirs[i])
                cjob["E31_ASSIGNED_STEMS"] = assignments[i]
                cjob["E31_WORKER_TAG"] = str(i)
                cjob["E31_HASHES"] = hashes
                jpath = child_dirs[i] / "job.json"
                with open(jpath, "x", encoding="utf-8") as jf:
                    json.dump(cjob, jf)

                lf = stack.enter_context(open(child_dirs[i] / "child.log", "x", encoding="utf-8"))
                logfiles.append(jpath.parent / "child.log")
                env = os.environ.copy()
                env["PYTHONHASHSEED"] = "0"
                env["CUDA_VISIBLE_DEVICES"] = cuda_tokens[i]
                env["BIOHUB_GPU_SHARD"] = str(i)
                env["PYTHONPATH"] = os.pathsep.join(
                    [
                        str(payloadroot / "src"),
                        str(repo_dir / "src"),
                        str(repo_dir / "scripts"),
                        str(repo_dir),
                    ]
                )
                p = subprocess.Popen(
                    [sys.executable, "-c", CHILD_CODE, str(jpath), str(runtime)],
                    cwd=str(repo_dir),
                    start_new_session=True,
                    stdout=lf,
                    stderr=subprocess.STDOUT,
                    env=env,
                )
                procs.append(p)

            deadline = t0 + timeout_seconds
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError("workers exceeded timeout")
                all_done = True
                for i, p in enumerate(procs):
                    rc = p.poll()
                    if rc is None:
                        all_done = False
                    elif rc != 0:
                        raise RuntimeError(f"worker {i} exited with returncode {rc}; log: {logfiles[i]}")
                if all_done:
                    break
                time.sleep(1.0)

            for i, p in enumerate(procs):
                if p.returncode != 0:
                    raise RuntimeError(f"child e31_shard_{i} exited {p.returncode}: {logfiles[i]}")
        finally:
            for p in procs:
                if p.poll() is None:
                    try:
                        os.killpg(p.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            for p in procs:
                try:
                    p.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(p.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    p.wait(timeout=30)

    for rel, expected in hashes.items():
        fp = payloadroot / rel
        if not fp.exists():
            raise FileNotFoundError(fp)
        if _stream_sha256(fp) != expected:
            raise ValueError(f"hash mismatch: {rel}")
    receipt = merge_shards(parent_work, assignments, job["E31_HASHES"])
    timing = {
        "total_wall_seconds": time.monotonic() - t0,
        "worker_count": worker_count,
        "assignments": assignments,
        "cuda_tokens": cuda_tokens[:worker_count],
    }
    tpath = parent_work / "e31_parallel_timing.json"
    with open(tpath, "x", encoding="utf-8") as tf:
        json.dump(timing, tf)
    print("VALIDATED_E31_SUBMISSION")
    return receipt
