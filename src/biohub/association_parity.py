"""Common OFF/ON inference bridge and exact observation-parity comparison."""

from __future__ import annotations

import hashlib
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
from biohub.association_observer import AssociationObserver

E23_ENV = {
    "BIOHUB_SECONDARY_EDGE_WEIGHT": "0.15", "BIOHUB_SECONDARY_DETECTION_WEIGHT": "0.475",
    "BIOHUB_SECONDARY_LINK_MODE": "low_margin_consensus", "BIOHUB_SECONDARY_MIX_TEMPERATURE": "1",
    "BIOHUB_SECONDARY_LOW_MARGIN_MAX": "0.35", "BIOHUB_DUAL_SEED_EDGE_THRESHOLD": "0.48",
    "BIOHUB_BIDIRECTIONAL_EDGE_WEIGHT": "0.30", "BIOHUB_BIDIRECTIONAL_FUSION_MODE": "harmonic_probability",
    "BIOHUB_DUAL_SEED_MIN_CANDIDATE_RETENTION": "0.90",
}
CFG = {"det_threshold": .96875, "use_ilp": True, "ilp_edge_weight": -1.,
       "ilp_appearance_weight": 0., "ilp_disappearance_weight": 1.5, "ilp_division_weight": 1.}


def array_signatures(arrays):
    return {k: {"dtype": a.dtype.str, "shape": list(a.shape),
                "sha256": hashlib.sha256(a.tobytes(order="C")).hexdigest()} for k, a in sorted(arrays.items())}


def graph_arrays(graph):
    nodes = graph.node_attrs(attr_keys=["node_id", "t", "z", "y", "x"]).sort("node_id")
    edge_keys = ["edge_id", "source_id", "target_id"]
    if graph.num_edges():
        edge_keys += ["edge_prob", "edge_dist"]
    edges = graph.edge_attrs(attr_keys=edge_keys).sort("source_id", "target_id", "edge_id")
    return {f"{prefix}_{column}": table[column].to_numpy()
            for prefix, table in (("node", nodes), ("edge", edges)) for column in table.columns}


def semantic_graph_signature(arrays):
    """GEFF has endpoint pairs rather than edge IDs; compare lossless numeric values."""
    keys = ("node_node_id", "node_t", "node_z", "node_y", "node_x",
            "edge_source_id", "edge_target_id", "edge_edge_prob", "edge_edge_dist")
    canonical = {}
    for k in keys:
        raw = arrays.get(k, np.empty(0, dtype=np.float64))
        dtype = np.int64 if k.endswith("_id") or k == "node_t" else np.float64
        canonical[k] = raw.astype(dtype)
        _require(np.array_equal(canonical[k], raw), f"lossy graph canonicalization: {k}")
    return array_signatures(canonical)


def compare_results(off, on):
    for result, arm in ((off, "off"), (on, "on")):
        _require(result["status"] == "ARM_COMPLETE" and result["arm"] == arm, "incomplete/wrong arm")
        names = result["dataset_order"]
        _require(len(names) == 4 and len(set(names)) == 4 and names == sorted(names), "incomplete dataset coverage")
        records = result["records"]
        _require(len(records) == 12 and {(r["dataset"], r["stage"]) for r in records}
                 == {(name, stage) for name in names for stage in ("returned", "pre", "post")},
                 "incomplete trace coverage")
    common = ("dataset_order", "input_inventory", "dependencies", "environment", "model_config", "rng_after")
    for key in common:
        _require(off[key] == on[key], f"OFF/ON {key} mismatch")
    _require(off["plan_sha256"] == on["plan_sha256"], "OFF/ON plan mismatch")
    _require(off["records"] == on["records"], "OFF/ON prediction/graph arrays mismatch")
    _require(on["observation_complete"], "ON observer incomplete")
    return {"status": "PUBLIC4_ASSOCIATION_OBSERVER_PARITY_PASS", "datasets": off["dataset_order"],
            "reference_raw_matched": True, "submission_authorized": False,
            "full36_capture_complete": False, "generalization_evidence": False}


def input_inventory(root, datasets):
    result = []
    for name in datasets:
        folder = root / f"{name}.zarr"
        _require(folder.is_dir(), "missing planned image dataset")
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                result.append({"path": path.relative_to(root).as_posix(),
                               "bytes": path.stat().st_size, "sha256": _sha(path)})
    return result


def _rng_digest(torch):
    numpy_state = np.random.get_state()
    return {"python": hashlib.sha256(_json_bytes(random.getstate())).hexdigest(),
            "numpy": hashlib.sha256(numpy_state[1].tobytes() + _json_bytes(
                [numpy_state[0], *numpy_state[2:]])).hexdigest(),
            "torch_cpu": hashlib.sha256(torch.get_rng_state().numpy().tobytes()).hexdigest(),
            "torch_cuda": [hashlib.sha256(s.cpu().numpy().tobytes()).hexdigest()
                           for s in torch.cuda.get_rng_state_all()]}


def capture_module(module, plan, root, arm):
    """Run one prepared module. Synthetic tests supply a module-shaped fixture."""
    _require(arm in ("off", "on"), "unknown arm")
    names = sorted(plan["datasets"])
    observer = AssociationObserver(root / "observation", {
        name: plan["datasets"][name]["frame_counts"] for name in names}) if arm == "on" else None
    original_video, original_build, original_save = module.predict_video, module.build_graph, module.save_graph
    records = {}
    current = None
    stage = "video"
    order = []

    def save_record(name, label, arrays):
        _require((name, label) not in records, "duplicate trace record")
        _require(all(isinstance(a, np.ndarray) and not a.dtype.hasobject and np.isfinite(a).all()
                     for a in arrays.values()), "invalid trace array")
        path = root / f"{name}_{label}.npz"
        with path.open("xb") as stream:
            np.savez_compressed(stream, **arrays)
        with np.load(path, allow_pickle=False) as saved:
            _require(array_signatures({k: saved[k] for k in saved.files}) == array_signatures(arrays),
                     "trace roundtrip mismatch")
        records[name, label] = {"dataset": name, "stage": label, "arrays": array_signatures(arrays)}

    def video(*args, **kwargs):
        nonlocal current, stage
        _require(stage == "video", "overlapping prediction video")
        name = Path(args[1]).stem
        _require(name in names and name not in order, "unplanned or duplicate prediction video")
        current = name
        coords, edges = original_video(*args, **kwargs)
        expected = plan["datasets"][name]
        _require(coords.dtype == np.dtype("int16") and coords.shape == (sum(expected["frame_counts"]), 4),
                 "reference detection shape/dtype mismatch")
        _require(hashlib.sha256(coords.astype("<i2", copy=False).tobytes()).hexdigest()
                 == expected["coordinate_sha256"], "reference detection coordinate mismatch")
        _require([int(np.count_nonzero(coords[:, 0] == t)) for t in range(100)] == expected["frame_counts"],
                 "reference detector counts mismatch")
        save_record(name, "returned", {"coords": coords, "edges": np.array(edges, dtype=np.float64).reshape(-1, 4)})
        order.append(name)
        stage = "pre"
        return coords, edges

    def build(*args, **kwargs):
        nonlocal stage
        _require(stage == "pre", "unexpected graph build")
        graph = original_build(*args, **kwargs)
        save_record(current, "pre", graph_arrays(graph))
        stage = "post"
        return graph

    def save(graph, path, *args, **kwargs):
        nonlocal stage
        _require(stage == "post" and Path(path).stem == current, "unexpected graph save")
        arrays = graph_arrays(graph)
        _require(semantic_graph_signature(arrays) == plan["datasets"][current]["raw_graph_signature"],
                 "reference selected raw graph mismatch")
        save_record(current, "post", arrays)
        result = original_save(graph, path, *args, **kwargs)
        stage = "video"
        return result

    module.predict_video, module.build_graph, module.save_graph = video, build, save
    try:
        kwargs = {"data_dir": Path(plan["data_dir"]), "fold": 0, "splits_file": Path(plan["splits_file"]),
                  "weights_path": Path(plan["primary_weights"]), "cfg": module.PredictConfig(**CFG),
                  "method": "unet_transformer", "unet_batch_size": 4, "evaluate": False}
        if observer is not None:
            kwargs["association_observer"] = observer
        module.predict(**kwargs)
        _require(stage == "video" and order == names and len(records) == len(names) * 3, "incomplete trace")
        if observer is not None:
            observer.finish()
        return {"dataset_order": order, "records": [records[key] for key in sorted(records)],
                "observation_complete": observer is not None}
    finally:
        module.predict_video, module.build_graph, module.save_graph = original_video, original_build, original_save


def run_arm(plan_path, source, root, arm):
    """Kaggle-only entry. Fail closed before importing a source with unverified bytes."""
    _require(Path("/kaggle/working").is_dir(), "real model execution is Kaggle-only")
    plan = json.loads(plan_path.read_text())
    _require(plan["schema_version"] == "biohub.association.public4.v1" and len(plan["datasets"]) == 4,
             "invalid public4 plan")
    _require(arm in ("off", "on") and _sha(source) == plan["source_sha256"][arm], "source SHA mismatch")
    _require({key: os.environ.get(key) for key in E23_ENV} == E23_ENV, "effective E23 environment mismatch")
    _require(set(p.stem for p in Path(plan["data_dir"]).glob("*.zarr")) == set(plan["datasets"]),
             "public dataset set mismatch")
    for path, expected in plan["runtime_file_sha256"].items():
        _require(_sha(Path(path)) == expected, f"runtime file changed: {path}")
    for record in plan["source_inventory"]:
        _require(_sha(Path(record["path"])) == record["sha256"], "source inventory changed")
    root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    try:
        inputs = input_inventory(Path(plan["data_dir"]), sorted(plan["datasets"]))
        import torch
        _require(torch.cuda.is_available() and torch.cuda.device_count() == 1, "expected one visible CUDA device")
        # Common diagnostic seed; E23 saved raw parity must still pass, no baseline replacement.
        random.seed(23826)
        np.random.seed(23826)
        torch.manual_seed(23826)
        torch.cuda.manual_seed_all(23826)
        dependencies = {name: importlib.metadata.version(name) for name in
                        ("numpy", "torch", "polars", "tracksdata", "pyscipopt", "zarr", "geff", "scipy")}
        spec = importlib.util.spec_from_file_location("biohub_e23_target_predict", source)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        import dataspec
        # The original predictor deletes an existing output; point it only at this fresh arm.
        dataspec.PREDICTIONS_PATH = root / "raw_predictions"
        torch.cuda.synchronize()
        result = capture_module(module, plan, root, arm)
        torch.cuda.synchronize()
        _require(inputs == input_inventory(Path(plan["data_dir"]), sorted(plan["datasets"])), "image bytes changed")
        for path, expected in plan["runtime_file_sha256"].items():
            _require(_sha(Path(path)) == expected, "runtime file changed after inference")
        for record in plan["source_inventory"]:
            _require(_sha(Path(record["path"])) == record["sha256"], "source changed after inference")
        _require(_sha(source) == plan["source_sha256"][arm], "prediction source changed")
        result.update(status="ARM_COMPLETE", arm=arm, input_inventory=inputs, dependencies=dependencies,
                      environment=E23_ENV, model_config=CFG, rng_after=_rng_digest(torch),
                      plan_sha256=_sha(plan_path), source_sha256=_sha(source), submission_authorized=False,
                      wall_seconds=time.perf_counter() - started,
                      peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
                      peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved(),
                      peak_self_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
        _require(result["wall_seconds"] <= 3600 and result["peak_self_rss_bytes"] <= 24 * 1024**3,
                 "arm runtime/RSS budget exceeded")
        _require(sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) <= 12 * 1024**3,
                 "arm output budget exceeded")
        with (root / "RESULT.json").open("xb") as stream:
            stream.write(_json_bytes(result))
        print(json.dumps({"status": result["status"], "arm": arm, "wall_seconds": result["wall_seconds"]}), flush=True)
        return result
    except Exception as exc:
        with (root / "ERROR.json").open("xb") as stream:
            stream.write(_json_bytes({"status": "ERROR", "error": str(exc), "submission_authorized": False}))
        raise
