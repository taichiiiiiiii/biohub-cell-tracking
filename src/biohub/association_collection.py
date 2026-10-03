"""Kaggle-only collection groups, reusing the frozen E23 trace without changing it."""

import importlib.metadata
import importlib.util
import json
import os
import random
import resource
import sys
import time
from pathlib import Path

import numpy as np

from biohub.association_capture import _json_bytes, _require, _sha
from biohub.association_parity import CFG, E23_ENV, _rng_digest, capture_module, input_inventory

REFERENCE_SHA = "08395ca8615b6eeaaaeec521cd937c62d2212b7a20cf18be1a27478afd4af7ac"
GROUP_SCHEMA = "biohub.association.collection36.group.v1"


def load_reference(path):
    _require(_sha(path) == REFERENCE_SHA, "collection reference SHA mismatch")
    reference = json.loads(path.read_text())
    _require(reference["schema_version"] == "biohub.association.collection36.preparation.v1"
             and len(reference["groups"]) == 9 and len(reference["datasets"]) == 36,
             "invalid collection reference")
    return reference


def validate_plan(plan):
    _require(plan["schema_version"] == GROUP_SCHEMA and plan["submission_authorized"] is False,
             "invalid collection group schema")
    reference = load_reference(Path(plan["reference_path"]))
    groups = {g["group_id"]: g for g in reference["groups"]}
    _require(plan["group_id"] in groups, "unplanned collection group")
    group = groups[plan["group_id"]]
    expected = {n: reference["datasets"][n] for n in group["datasets"]}
    _require(plan["datasets"] == expected and len(expected) == 4, "collection dataset/reference mismatch")
    _require(plan["source_sha256"] == reference["source_sha256"]["on"], "ON source contract mismatch")
    _require({key: os.environ.get(key) for key in E23_ENV} == E23_ENV, "effective E23 environment mismatch")
    image_root = Path(plan["data_dir"])
    _require(set(p.name for p in image_root.iterdir()) == {f"{n}.zarr" for n in expected},
             "image-only view contains unplanned entries")
    _require(all((image_root / f"{n}.zarr").is_dir() for n in expected), "missing image directory")
    split = json.loads(Path(plan["splits_file"]).read_text())
    _require(split == [{"split": 0, "train": [], "test": sorted(expected)}], "collection split mismatch")
    _require(bool(plan["runtime_file_sha256"]) and bool(plan["source_inventory"]), "unbound runtime")
    _require(plan["primary_weights"] in plan["runtime_file_sha256"]
             and plan["splits_file"] in plan["runtime_file_sha256"], "missing required runtime binding")
    for path, digest in plan["runtime_file_sha256"].items():
        _require(_sha(Path(path)) == digest, f"runtime changed: {path}")
    for entry in plan["source_inventory"]:
        _require(_sha(Path(entry["path"])) == entry["sha256"], "source inventory changed")
    _require(_sha(Path(plan["source_path"])) == plan["source_sha256"], "prediction source changed")
    return reference, group


def validate_group_result(result, plan, group, plan_sha):
    names = group["datasets"]
    _require(result["status"] == "COLLECTION_GROUP_COMPLETE" and result["group_id"] == group["group_id"],
             "incomplete/wrong group")
    _require(result["plan_sha256"] == plan_sha and result["source_sha256"] == plan["source_sha256"],
             "group provenance mismatch")
    _require(result["dataset_order"] == names and result["observation_complete"], "group coverage incomplete")
    _require(len(result["records"]) == 12 and {(r["dataset"], r["stage"]) for r in result["records"]}
             == {(n, s) for n in names for s in ("returned", "pre", "post")}, "trace coverage incomplete")
    _require(result["pair_count"] == 396 and result["dense_pairs"] == group["dense_pairs"], "pair coverage incomplete")
    _require(result["environment"] == E23_ENV and result["model_config"] == CFG, "group configuration drift")
    _require(result["submission_authorized"] is False and result["generalization_evidence"] is False,
             "wrong collection claims")
    for key in ("wall_seconds", "writer_seconds", "observer_seconds", "peak_self_rss_bytes"):
        _require(type(result[key]) in (int, float) and np.isfinite(result[key]) and result[key] >= 0,
                 f"invalid resource value: {key}")
    _require(result["wall_seconds"] <= 3600 and result["peak_self_rss_bytes"] <= 24 * 1024**3,
             "group runtime/RSS budget exceeded")


def run_group(plan_path, root):
    _require(Path("/kaggle/working").is_dir(), "model execution is Kaggle-only")
    root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    try:
        plan_sha = _sha(plan_path)
        plan = json.loads(plan_path.read_text())
        _, group = validate_plan(plan)
        names = group["datasets"]
        inputs = input_inventory(Path(plan["data_dir"]), names)
        _require(bool(inputs), "empty image inventory")
        import torch

        _require(torch.cuda.is_available() and torch.cuda.device_count() == 1, "expected one visible CUDA device")
        random.seed(23826)
        np.random.seed(23826)
        torch.manual_seed(23826)
        torch.cuda.manual_seed_all(23826)
        dependencies = {n: importlib.metadata.version(n) for n in
                        ("numpy", "torch", "polars", "tracksdata", "pyscipopt", "zarr", "geff", "scipy")}
        spec = importlib.util.spec_from_file_location("biohub_e23_collection_predict", plan["source_path"])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        import dataspec

        dataspec.PREDICTIONS_PATH = root / "raw_predictions"
        torch.cuda.synchronize()
        result = capture_module(module, plan, root, "on")
        torch.cuda.synchronize()
        _require(_sha(plan_path) == plan_sha, "group plan changed")
        validate_plan(plan)
        _require(inputs == input_inventory(Path(plan["data_dir"]), names), "image bytes changed")
        observer_path = root / "observation/MANIFEST.json"
        pairs_path = root / "observation/pairs/MANIFEST.json"
        observer, pairs = (json.loads(p.read_text()) for p in (observer_path, pairs_path))
        _require(observer["pair_manifest_sha256"] == _sha(pairs_path), "pair manifest changed")
        _require(observer["graph_ID_mapping_complete"] and observer["datasets"] == names
                 and observer["status"] == "ASSOCIATION_OBSERVATION_COMPLETE_NOT_PARITY"
                 and pairs["status"] == "PAIR_CAPTURE_COMPLETE", "observation incomplete")
        result.update(status="COLLECTION_GROUP_COMPLETE", group_id=group["group_id"], plan_sha256=plan_sha,
                      source_sha256=plan["source_sha256"], input_inventory=inputs, dependencies=dependencies,
                      environment=E23_ENV, model_config=CFG, rng_after=_rng_digest(torch),
                      reference_sha256=REFERENCE_SHA, reference_raw_matched=True, submission_authorized=False,
                      generalization_evidence=False, paired_off_on_this_group=False,
                      pair_count=len(pairs["records"]), dense_pairs=pairs["dense_pairs"],
                      packet_bytes=pairs["packet_bytes"], writer_seconds=pairs["writer_seconds"],
                      observer_seconds=observer["observer_seconds_excluding_final_manifest"],
                      observer_manifest_sha256=_sha(observer_path), pair_manifest_sha256=_sha(pairs_path),
                      wall_seconds=time.perf_counter() - started,
                      peak_self_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
                      peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved())
        validate_group_result(result, plan, group, plan_sha)
        encoded = _json_bytes(result)
        _require(sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) + len(encoded) <= 12 * 1024**3,
                 "group output budget exceeded")
        with (root / "RESULT.json").open("xb") as stream:
            stream.write(encoded)
        print(json.dumps({"status": result["status"], "group_id": group["group_id"],
                          "wall_seconds": result["wall_seconds"]}), flush=True)
        return result
    except Exception as exc:
        with (root / "ERROR.json").open("xb") as stream:
            stream.write(_json_bytes({"status": "ERROR", "error": str(exc), "submission_authorized": False}))
        raise
