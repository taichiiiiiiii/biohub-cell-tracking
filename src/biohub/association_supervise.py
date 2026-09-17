"""Serial bounded Kaggle OFF/ON supervision; never submits or retries."""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from biohub.association_capture import _json_bytes, _require, _sha
from biohub.association_parity import compare_results


def process_tree_rss(pid, proc_root=Path("/proc")):
    """Linux resident-page sampling, following children of every thread, no extra package."""
    pending, seen, pages = [pid], set(), 0
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        folder = proc_root / str(current)
        try:
            pages += int((folder / "statm").read_text().split()[1])
            for children in (folder / "task").glob("*/children"):
                pending.extend(int(value) for value in children.read_text().split())
        except FileNotFoundError:
            continue  # Process/thread ended between samples; exit status is checked separately.
    return pages * os.sysconf("SC_PAGE_SIZE")


def supervise(plan_path, root, payload, deadline):
    _require(Path("/kaggle/working").is_dir(), "supervisor is Kaggle-only")
    root.mkdir(parents=True, exist_ok=False)
    _require(shutil.disk_usage(root).free >= 16 * 1024**3, "less than 16 GiB free")
    plan = json.loads(plan_path.read_text())
    completed = {}
    process_records = {}
    tokens = [t.strip() for t in os.environ.get("CUDA_VISIBLE_DEVICES", "0").split(",") if t.strip()]
    _require(tokens and tokens[0] != "-1", "no CUDA token")
    plan_sha = _sha(plan_path)
    for arm in ("off", "on"):
        _require(time.monotonic() < deadline, "diagnostic wall budget exceeded before arm")
        command = [sys.executable, str(payload / "scripts/e23_association_bridge.py"),
                   "--plan", str(plan_path), "--source", plan["source_paths"][arm],
                   "--root", str(root / arm), "--arm", arm]
        env = {**os.environ, "PYTHONPATH": str(payload / "src") + os.pathsep + str(Path(plan["repo_dir"]) / "src"),
               "CUDA_VISIBLE_DEVICES": tokens[0], "BIOHUB_GPU_SHARD": "single",
               "PYTHONHASHSEED": "0"}
        started, peak_rss = time.monotonic(), 0
        error = None
        with (root / f"{arm}.log").open("xb") as log:
            process = subprocess.Popen(command, cwd=plan["repo_dir"], env=env, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            print(f"D3 ARM_STARTED {arm} PID {process.pid}", flush=True)
            try:
                while process.poll() is None:
                    if time.monotonic() >= min(started + 3600, deadline):
                        raise RuntimeError("arm/diagnostic wall budget exceeded")
                    peak_rss = max(peak_rss, process_tree_rss(process.pid))
                    _require(peak_rss <= 24 * 1024**3, "process-tree RSS budget exceeded")
                    size = sum(p.stat().st_size for p in (root / arm).rglob("*") if p.is_file())
                    _require(size <= 12 * 1024**3, "arm output budget exceeded")
                    time.sleep(1.)
            except Exception as exc:
                error = str(exc)
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
            code = process.wait()
        process_records[arm] = {"returncode": code, "wall_seconds": time.monotonic() - started,
                                "peak_sampled_tree_rss_bytes": peak_rss, "error": error}
        with (root / f"{arm}_PROCESS.json").open("xb") as stream:
            stream.write(_json_bytes(process_records[arm]))
        print(f"D3 ARM_FINISHED {arm} exit={code}", flush=True)
        _require(code == 0 and error is None, "arm failed; inspect retained log/PROCESS/ERROR")
        _require(_sha(plan_path) == plan_sha, "plan changed during diagnostic")
        completed[arm] = json.loads((root / arm / "RESULT.json").read_text())
    result = compare_results(completed["off"], completed["on"])
    result.update(processes=process_records, plan_sha256=plan_sha,
                  arm_result_sha256={arm: _sha(root / arm / "RESULT.json") for arm in completed})
    _require(time.monotonic() <= deadline, "diagnostic deadline exceeded")
    with (root / "PARITY_RESULT.json").open("xb") as stream:
        stream.write(_json_bytes(result))
    print(json.dumps(result, sort_keys=True), flush=True)
    return result
