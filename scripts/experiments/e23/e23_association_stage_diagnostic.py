"""E23 association-stage diagnostic: input binding, run loop, and CLI.

Read-only graph diagnostic. No training, no inference, no network, and no
submission; binds frozen known12 only.
"""

import json
from pathlib import Path

from scripts.experiments.e26 import e26_edge_diagnostic as d2

ROOT = d2.ROOT

COLLECTION = ROOT / "outputs/local/e23_collection_verified_20260912"
AUDIT = ROOT / "outputs/local/e23_association_collection_audit_20260908/REAL_COLLECTION_AUDIT_20260912.json"
AUDIT_SHA = "e56db2ab1d9a79a94d8ed97d1b02d9d6391713caf842a2672a0777419391e70a"
REFERENCE = ROOT / "outputs/local/e23_association_collection_20260908/REFERENCE_PLAN.json"
REFERENCE_SHA = "08395ca8615b6eeaaaeec521cd937c62d2212b7a20cf18be1a27478afd4af7ac"
D2_RESULT = ROOT / "outputs/local/e26_diagnostic/d2b_eval12_v2_202609081002/result/RESULT.json"
D2_SHA = "2df2b4c2d4cb3aad978358c52b66a893de147b4428816448b2775e090753d767"
TOTALS = {"retained_tp": 7199, "lost_tp": 54, "gained_tp": 111, "shared_fn": 227}


def collect_inputs():
    audit_b = d2.binding(AUDIT)
    ref_b = d2.binding(REFERENCE)
    d2res_b = d2.binding(D2_RESULT)
    d2.verify_files([
        {"path": str(AUDIT), "bytes": audit_b["bytes"], "sha256": AUDIT_SHA},
        {"path": str(REFERENCE), "bytes": ref_b["bytes"], "sha256": REFERENCE_SHA},
        {"path": str(D2_RESULT), "bytes": d2res_b["sha256"] and d2res_b["bytes"],
         "sha256": D2_SHA},
    ])

    with AUDIT.open() as f:
        audit = json.load(f)
    with REFERENCE.open() as f:
        reference = json.load(f)
    with D2_RESULT.open() as f:
        d2_result = json.load(f)

    d2.check(audit["status"] == "COLLECTION36_ARTIFACT_AUDIT_PASS", "audit status")
    d2.check(audit["submission_authorized"] is False, "audit submission flag")
    d2.check(audit["reference_sha256"] == REFERENCE_SHA, "audit reference sha")
    d2.check(d2_result["status"] == "DIAGNOSTIC_COMPLETE_NOT_ADOPTION", "d2 status")
    d2.check(d2_result["submission_authorized"] is False, "d2 submission flag")
    d2.check(d2_result["datasets"] == list(d2.STEMS), "d2 dataset order")
    d2.check(d2_result["transition_totals"] == TOTALS, "d2 transition totals")

    groups = reference["groups"]
    d2.check(len(groups) == 9, "group count")
    diag_groups = [g for g in groups if g["stage"] == "diagnostic12"]
    d2.check([g["group_id"] for g in diag_groups] == ["group00", "group01", "group02"],
             "diagnostic group ids")
    dataset_to_group = {}
    for g in diag_groups:
        ds = g["datasets"]
        d2.check(len(ds) == 4, f"group width {g['group_id']}")
        for stem in ds:
            d2.check(stem not in dataset_to_group, f"dup dataset {stem}")
            dataset_to_group[stem] = g["group_id"]
    d2.check(set(dataset_to_group) == set(d2.STEMS), "diagnostic12 union mismatch")

    control = d2_result["control"]
    ctrl_b = {"path": control["path"], "bytes": control["bytes"],
              "sha256": control["sha256"]}
    d2.check(Path(ctrl_b["path"]) == D2_RESULT.parent.parent / "control.json",
             "control path")

    artifacts = d2_result["artifacts"]
    d2.check(isinstance(artifacts, list), "artifacts list")
    d2.check(len(artifacts) == 84, "root artifact count")
    trans_bindings = {}
    for stem in d2.STEMS:
        name = f"{stem}_gt_edge_transitions.json"
        matches = [a for a in artifacts if Path(a["path"]).name == name]
        d2.check(len(matches) == 1, f"transition count {stem}")
        b = matches[0]
        d2.check(Path(b["path"]) == D2_RESULT.parent / name, f"transition path {stem}")
        trans_bindings[stem] = {"path": b["path"], "bytes": b["bytes"],
                                "sha256": b["sha256"]}

    scoring, files, trees = d2.fixed_inputs()

    collection_root = COLLECTION.resolve()
    prepost = []
    for stem in d2.STEMS:
        gid = dataset_to_group[stem]
        for kind in ("pre_ilp", "post_ilp"):
            rel = f"association_collection_run/{gid}/observation/{stem}_{kind}.npz"
            exp = audit["bindings"][rel]
            abs_path = str(COLLECTION / rel)
            resolved = Path(abs_path).resolve()
            d2.check(str(resolved) == str((collection_root / rel).resolve()),
                     f"symlink escape {rel}")
            d2.check(str(resolved).startswith(str(collection_root) + "/"),
                     f"outside collection {rel}")
            prepost.append({"path": abs_path, "bytes": exp["bytes"],
                            "sha256": exp["sha256"]})

    all_inputs = [audit_b, ref_b, d2res_b, ctrl_b] + \
        [trans_bindings[s] for s in d2.STEMS] + prepost
    d2.verify_files(all_inputs)

    jobs = []
    for i, stem in enumerate(d2.STEMS):
        jobs.append({"dataset": stem, "group_id": dataset_to_group[stem],
                     "pre": prepost[2 * i], "post": prepost[2 * i + 1],
                     "d2": trans_bindings[stem]})
    d2.check(len(jobs) == 12, "job count")
    d2.verify_files(files + all_inputs)

    summaries = d2_result["summaries"]
    d2.check({s["dataset"] for s in summaries} == set(d2.STEMS), "summary datasets")
    d2.check(len(summaries) == len({s["dataset"] for s in summaries}),
             "summary uniqueness")
    d2.check(sum(s["gt_edges"] for s in summaries) == 7591, "gt edges total")

    return {"scoring": scoring, "inputs": files + all_inputs, "gt_trees": trees,
            "jobs": jobs, "d2_result": d2_result}


def _load_runtime(source_bindings):
    import importlib
    import sys
    refused = [m for m in sys.modules
               if m == "biohub" or m.startswith("biohub.")
               or m == "tracking_cellmot" or m.startswith("tracking_cellmot.")]
    d2.check(not refused, f"preloaded project runtime: {refused}")
    d2.verify_files(source_bindings)
    names = ("biohub.association_collection_audit",
             "biohub.association_stage_diagnostic",
             "biohub.evaluate", "biohub.io")
    modules = {n: importlib.import_module(n) for n in names}
    d2.verify_files(source_bindings)
    return modules


def run(output):
    import os
    import signal
    import sys
    import time
    from collections import Counter

    import polars as pl
    import tracksdata as td

    output = Path(output).resolve()
    local_root = (ROOT / "outputs" / "local").resolve()
    d2.check(str(output).startswith(str(local_root) + "/"), "output outside local root")
    d2.check(not output.exists(), "output exists")
    d2.check(os.environ.get("PYTHONHASHSEED") == "0", "PYTHONHASHSEED")
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                "POLARS_MAX_THREADS"):
        d2.check(os.environ.get(var) == "1", f"thread env {var}")
    d2.check(os.environ.get("CUDA_VISIBLE_DEVICES") == "", "CUDA_VISIBLE_DEVICES")
    d2.check(not [k for k in os.environ if k.startswith("BIOHUB_")], "BIOHUB_* override")

    identity_checks = d2.official_identity()
    bundle = collect_inputs()
    scoring, gt_trees, jobs = bundle["scoring"], bundle["gt_trees"], bundle["jobs"]

    own_src = Path(__file__).resolve()
    closure_modules = ("__init__.py", "association_collection_audit.py",
                       "association_artifact_audit.py", "association_capture.py",
                       "association_collection.py", "association_collection_supervise.py",
                       "association_supervise.py", "association_parity.py",
                       "association_observer.py", "association_packet_readout.py",
                       "association_stage_diagnostic.py", "e26_edge_diagnostic.py",
                       "evaluate.py", "io.py")
    src_paths = ([own_src,
                  ROOT / "tests/test_association_stage_d2_join.py"]
                 + [ROOT / "src/biohub" / m for m in closure_modules])
    seen = set()
    sources = []
    for b in d2.sources() + [d2.binding(p) for p in src_paths]:
        if b["path"] not in seen:
            seen.add(b["path"])
            sources.append(b)
    versions = json.loads(json.dumps(d2.versions(), allow_nan=False))

    runtime = _load_runtime(sources)
    Reader = runtime["biohub.association_collection_audit"].Reader
    frames_from_npz = runtime["biohub.association_stage_diagnostic"].frames_from_npz
    diagnose_stages = runtime["biohub.association_stage_diagnostic"].diagnose_stages
    join_d2_transitions = runtime["biohub.association_stage_diagnostic"].join_d2_transitions
    read_submission = runtime["biohub.evaluate"].read_submission
    load_geff_graph = runtime["biohub.io"].load_geff_graph
    read_scale = runtime["biohub.io"].read_scale

    output.mkdir(parents=True, exist_ok=False)

    start = time.monotonic()
    prev_handler = signal.getsignal(signal.SIGALRM)
    d2.check(signal.getitimer(signal.ITIMER_REAL)[0] == 0, "alarm already active")
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError()))
    signal.setitimer(signal.ITIMER_REAL, d2.BUDGET["wall_seconds"])
    result_path = output / "RESULT.json"
    try:
        control = {"inputs": bundle["inputs"], "gt_trees": gt_trees, "jobs": jobs,
                   "sources": sources, "versions": versions,
                   "datasets": list(d2.STEMS), "budget": d2.BUDGET,
                   "submission_authorized": False}
        control_path = output / "CONTROL.json"
        d2.write_json(control_path, control)
        control_binding = d2.binding(control_path)

        df = read_submission(Path(scoring["subsets"]["baseline"]["csv"]["path"]))
        d2.check(set(df["dataset"].unique().to_list()) == set(d2.STEMS),
                 "submission datasets")
        preflight = {v["dataset"]: v for v in
                     scoring["gt_preflight"]["baseline"]["videos"]}
        expected_by_dataset = {s["dataset"]: s for s in bundle["d2_result"]["summaries"]}
        summaries, artifacts, totals = [], [], Counter()
        for job in jobs:
            stem, gid = job["dataset"], job["group_id"]
            reader = Reader(COLLECTION)
            pre = reader.arrays(Path(job["pre"]["path"]).relative_to(COLLECTION).as_posix(),
                                job["pre"]["sha256"])
            post = reader.arrays(Path(job["post"]["path"]).relative_to(COLLECTION).as_posix(),
                                 job["post"]["sha256"])
            zarr_path = ROOT / "data" / "train" / f"{stem}.zarr"
            gt = load_geff_graph(ROOT / "data" / "train" / f"{stem}.geff")
            scale = read_scale(zarr_path)
            d2.check(tuple(scale) == tuple(preflight[stem]["scale_zyx"]), f"scale {stem}")
            with open(job["d2"]["path"]) as f:
                d2_rows = json.load(f)
            K = td.DEFAULT_ATTR_KEYS
            node_rows = gt.node_attrs(attr_keys=[K.NODE_ID, K.T, "z", "y", "x"])
            gt_nodes = {}
            for r in node_rows.to_dicts():
                gt_nodes[r[K.NODE_ID]] = r
            for rec in d2_rows:
                for arm_name in ("baseline", "candidate"):
                    a = rec[arm_name]
                    d2.check(gt_nodes[a["gt_source_id"]] == a["gt_source"],
                             f"coord identity {stem} {arm_name} source")
                    d2.check(gt_nodes[a["gt_target_id"]] == a["gt_target"],
                             f"coord identity {stem} {arm_name} target")
            csv_nodes = df.filter(pl.col("dataset") == stem).filter(
                pl.col("row_type") == "node")
            csv_edges = df.filter(pl.col("dataset") == stem).filter(
                pl.col("row_type") == "edge")
            stage = diagnose_stages(stem, frames_from_npz(pre), frames_from_npz(post),
                                    (csv_nodes, csv_edges), gt, scale)
            joined = join_d2_transitions(stage, d2_rows)
            expected = expected_by_dataset[stem]
            d2.check(joined["summary"]["gt_edges"] == expected["gt_edges"],
                     f"gt edges {stem}")
            d2.check(joined["summary"]["d2_transitions"] == expected["transitions"],
                     f"d2 transitions {stem}")
            stage_p = output / f"{stem}_stage.json"
            join_p = output / f"{stem}_join.json"
            d2.write_json(stage_p, stage)
            d2.write_json(join_p, joined)
            artifacts += [d2.binding(stage_p), d2.binding(join_p)]
            summary = {"dataset": stem, **joined["summary"]}
            summaries.append(summary)
            totals.update(summary["d2_transitions"])
            d2.check_budget(start, output)
            print(f"{gid} {stem} gt_edges={summary['gt_edges']}", flush=True)
        d2.check(dict(totals) == TOTALS, "transition totals")
        d2.check(sum(s["gt_edges"] for s in summaries) == 7591, "gt edges total")
        d2.check([s["dataset"] for s in summaries] == list(d2.STEMS), "summary order")
        d2.verify_files(bundle["inputs"] + sources + [control_binding] + artifacts)
        d2.verify_trees(gt_trees)
        d2.check(d2.official_identity() == identity_checks, "official identity drift")
        d2.check(json.loads(json.dumps(d2.versions(), allow_nan=False)) == versions,
                 "version drift")
        d2.check("torch" not in sys.modules, "torch imported")
        budget = d2.check_budget(start, output)
        result = {"status": "KNOWN12_GRAPH_STAGE_DIAGNOSTIC_COMPLETE_NOT_ADOPTION",
                  "datasets": list(d2.STEMS), "summaries": summaries,
                  "transition_totals": dict(totals), "artifacts": artifacts,
                  "control": control_binding, "timing": budget,
                  "timing_scope": ("diagnostic interval; values before RESULT write, "
                                   "final boundary separately checked"),
                  "matrix_read": False, "official_score_computed": False,
                  "training_started": False, "submission_authorized": False,
                  "generalization_evidence": False}
        result_path = output / "RESULT.json"
        d2.write_json(result_path, result)
        d2.check_budget(start, output)
        return result
    except BaseException as exc:
        if result_path.exists():
            result_path.rename(output / "RESULT.failed.json")
        d2.write_json(output / "ERROR.json",
                      {"type": type(exc).__name__, "submission_authorized": False})
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, prev_handler)


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.output)


if __name__ == "__main__":
    main()
