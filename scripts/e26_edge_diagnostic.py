"""One bounded diagnostic of saved E26 eval12 CSVs; no inference/network/submission."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import resource
import signal
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

STEMS = (
    "44b6_12dfb391", "44b6_267148e4", "44b6_2a2eff9f", "44b6_341df25f", "44b6_587a1e22", "44b6_5f15d135",
    "6bba_062c8d37", "6bba_07e24132", "6bba_085bf656", "6bba_09961292", "6bba_0e7c0d07", "6bba_12665c0e",
)
RUN = "e26_motion_off_screen_v2_20260908073709Z"
SCORE = ROOT / "outputs/local/e26_screen" / RUN / "scoring/eval12.json"
GT_BINDING = ROOT / "outputs/local/e26_screen_preregistrations" / RUN / "GT_BINDING.json"
SCORE_SHA = "0e53e36ae3efb5636a1b8ee46fc2b5cdd1aa3d8090c1c5853daef9ea2eaf45f4"
GT_SHA = "f2842591cfa6750a443aae0d6d2ffd44616b1c0d7ad3bb93cb0f6a83a662b3b1"
BUDGET = {"wall_seconds": 600, "peak_self_rss_bytes": 4 * 1024**3, "output_bytes": 250 * 1024**2}


def check(value, message):
    if not value:
        raise ValueError(message)


def binding(path):
    path = Path(path).resolve()
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            h.update(block)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": h.hexdigest()}


def verify_files(items):
    for item in items:
        check(binding(item["path"]) == item, f"binding changed: {item['path']}")


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
        stream.write("\n")


def versions():
    return {"python": sys.version, "packages": sorted(
        (d.metadata["Name"], d.version) for d in importlib.metadata.distributions()
    )}


def official_identity():
    def git(*args):
        return subprocess.check_output(["git", "-C", str(ROOT / "official"), *args], text=True).strip()
    check(git("rev-parse", "HEAD") == "075fc5f5a52d11077f9dc2b074644618f26939e2", "official HEAD changed")
    check(not git("status", "--porcelain"), "official dirty")


def fixed_inputs():
    check(binding(SCORE)["sha256"] == SCORE_SHA and binding(GT_BINDING)["sha256"] == GT_SHA,
          "original stage/GT binding changed")
    stage, gt = json.loads(SCORE.read_bytes()), json.loads(GT_BINDING.read_bytes())
    check(tuple(gt["eval36_order"][:12]) == STEMS, "GT order differs")
    files = [binding(SCORE), binding(GT_BINDING)]
    for arm in ("baseline", "candidate"):
        check(tuple(stage["subsets"][arm]["datasets"]) == STEMS, "CSV subset differs")
        files.append(stage["subsets"][arm]["csv"])
    gt_trees = {}
    for video in gt["videos"]:
        stem = video["dataset"]
        if stem not in STEMS:
            continue  # No remaining-24 file inventory traversal or semantic access.
        tree = ROOT / "data/train" / f"{stem}.geff"
        selected = []
        for f in video["gt_inventory"]["files"]:
            path = Path(f["selected_path"])
            check(path == tree / f["relative_path"], "unexpected GT path")
            files.append({"path": str(path), "bytes": f["stat"]["size"], "sha256": f["sha256"]})
            selected.append(str(path))
        gt_trees[str(tree)] = sorted(selected)
        files.append(video["image_metadata"]["root_metadata"])
    check(len(gt_trees) == 12, "incomplete GT selection")
    verify_files(files)
    verify_trees(gt_trees)
    return stage, files, gt_trees


def verify_trees(trees):
    for root, expected in trees.items():
        actual = sorted(str(p) for p in Path(root).rglob("*") if p.is_file())
        check(actual == expected, f"GT file membership changed: {root}")


def sources():
    import tracksdata

    paths = [Path(__file__), ROOT / "src/biohub/e26_edge_diagnostic.py", ROOT / "src/biohub/evaluate.py",
             ROOT / "src/biohub/io.py", ROOT / "tests/test_e26_edge_diagnostic.py",
             ROOT / "tests/test_e26_edge_diagnostic_runner.py",
             ROOT / "pyproject.toml", ROOT / "uv.lock", ROOT / "analysis/e26_d2_diagnostic.md"]
    paths += sorted((ROOT / "official/src/tracking_cellmot").glob("*.py"))
    paths += sorted(Path(tracksdata.__file__).parent.rglob("*.py"))
    return [binding(p) for p in paths]


def check_budget(start, output):
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":
        rss *= 1024
    size = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
    elapsed = time.monotonic() - start
    check(elapsed <= BUDGET["wall_seconds"], "wall budget exceeded")
    check(rss <= BUDGET["peak_self_rss_bytes"], "self RSS budget exceeded")
    check(size <= BUDGET["output_bytes"], "output budget exceeded")
    return {"wall_seconds": elapsed, "peak_self_rss_bytes": rss, "output_bytes": size}


def run(control_path, expected_sha, output):
    check(binding(control_path)["sha256"] == expected_sha, "control identity mismatch")
    control = json.loads(control_path.read_bytes())
    check(control["budget"] == BUDGET and tuple(control["datasets"]) == STEMS, "control scope changed")
    check(control["submission_authorized"] is False, "diagnostic cannot authorize submission")
    check(control["versions"] == json.loads(json.dumps(versions())), "dependency versions changed")
    official_identity()
    verify_files(control["inputs"] + control["sources"])
    check(control["sources"] == sources(), "source membership changed")
    verify_trees(control["gt_trees"])
    for key in ("PYTHONHASHSEED", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "POLARS_MAX_THREADS"):
        check(os.environ.get(key) == ("0" if key == "PYTHONHASHSEED" else "1"), f"invalid {key}")
    check(os.environ.get("CUDA_VISIBLE_DEVICES") == "", "CUDA must be disabled")
    check(not any(k.startswith("BIOHUB_") for k in os.environ), "ambient BIOHUB override")
    output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    def timeout(_signum, _frame):
        raise TimeoutError("D2B fixed wall budget exceeded")
    signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, BUDGET["wall_seconds"])
    try:
        import polars as pl
        import tracksdata as td

        from biohub.e26_edge_diagnostic import compare_arms, diagnose_arm
        from biohub.evaluate import read_submission
        from biohub.io import estimated_number_of_nodes, load_geff_graph, read_scale

        stage = json.loads(SCORE.read_bytes())
        inputs = {a: read_submission(stage["subsets"][a]["csv"]["path"]) for a in ("baseline", "candidate")}
        for df in inputs.values():
            check(set(df["dataset"].unique()) == set(STEMS), "unexpected CSV dataset")
        summaries, artifacts = [], []
        def parquet(path, df):
            check(not path.exists(), "output exists")
            df.write_parquet(path)
            check(pl.read_parquet(path).equals(df), "Parquet roundtrip mismatch")
            artifacts.append(binding(path))
            check_budget(start, output)
        for stem in STEMS:
            gt_path = ROOT / "data/train" / f"{stem}.geff"
            gt = load_geff_graph(gt_path)
            scale = read_scale(ROOT / "data/train" / f"{stem}.zarr")
            estimate = estimated_number_of_nodes(gt_path)
            check(all(math.isfinite(x) and x > 0 for x in (*scale, estimate)), "invalid GT metadata")
            preflight = next(v for v in stage["gt_preflight"]["baseline"]["videos"] if v["dataset"] == stem)
            check(tuple(preflight["scale_zyx"]) == tuple(scale) and
                  estimate == preflight["estimated_number_of_nodes"], "GT metadata changed")
            parquet(output / f"{stem}_gt_nodes.parquet", gt.node_attrs(
                attr_keys=[td.DEFAULT_ATTR_KEYS.NODE_ID, td.DEFAULT_ATTR_KEYS.T, "z", "y", "x"]))
            parquet(output / f"{stem}_gt_edges.parquet", gt.edge_attrs(attr_keys=[]))
            arms = {}
            for arm in ("baseline", "candidate"):
                group = inputs[arm].filter(pl.col("dataset") == stem)
                expected = next(r for r in stage["arms"][arm]["rows"] if r["dataset"] == stem)
                arms[arm] = diagnose_arm(stem, group.filter(pl.col("row_type") == "node"),
                                         group.filter(pl.col("row_type") == "edge"), gt, scale, estimate, expected)
                parquet(output / f"{stem}_{arm}_nodes.parquet", arms[arm].nodes)
                parquet(output / f"{stem}_{arm}_edges.parquet", arms[arm].edges)
            records, summary = compare_arms(arms["baseline"], arms["candidate"])
            trace = output / f"{stem}_gt_edge_transitions.json"
            write_json(trace, records)
            check(json.loads(trace.read_bytes()) == records, "JSON trace roundtrip mismatch")
            artifacts.append(binding(trace))
            summaries.append(summary)
            print(json.dumps({"dataset": stem, "transitions": summary["transitions"],
                              "timing": check_budget(start, output)}), flush=True)
        verify_files(control["inputs"] + control["sources"] + artifacts)
        verify_trees(control["gt_trees"])
        official_identity()
        check(binding(control_path)["sha256"] == expected_sha, "control changed during diagnostic")
        check(control["versions"] == json.loads(json.dumps(versions())), "dependencies changed during diagnostic")
        check("torch" not in sys.modules, "unexpected torch import")
        totals = Counter()
        for summary in summaries:
            totals.update(summary["transitions"])
        result = {"schema_version": "biohub.e26.d2b.edge_diagnostic.v1", "status": "DIAGNOSTIC_COMPLETE_NOT_ADOPTION",
                  "submission_authorized": False, "control": binding(control_path), "datasets": list(STEMS),
                  "summaries": summaries, "transition_totals": dict(totals), "artifacts": artifacts,
                  "timing": check_budget(start, output)}
        write_json(output / "RESULT.json", result)
        check_budget(start, output)
        print(json.dumps({"status": result["status"], "totals": dict(totals),
                          "result": binding(output / "RESULT.json")}), flush=True)
    except BaseException as exc:
        write_json(output / "ERROR.json", {"type": type(exc).__name__, "error": str(exc),
                                          "submission_authorized": False})
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("bind", "run"))
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--control-sha")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    parent = ROOT / "outputs/local/e26_diagnostic"
    control = args.control.resolve()
    check(parent in control.parents, "control must be inside project diagnostic outputs")
    if args.mode == "bind":
        official_identity()
        _, files, trees = fixed_inputs()
        control.parent.mkdir(parents=True, exist_ok=True)
        write_json(control, {"schema_version": "biohub.e26.d2b.control.v1", "datasets": list(STEMS),
                             "budget": BUDGET, "inputs": files, "gt_trees": trees, "sources": sources(),
                             "versions": versions(), "submission_authorized": False})
        print(json.dumps(binding(control)))
    else:
        check(args.control_sha and args.output, "run requires control SHA and fresh output path")
        output = args.output.resolve()
        check(parent in output.parents and output != control.parent, "invalid output path")
        run(control, args.control_sha, output)


if __name__ == "__main__":
    main()
