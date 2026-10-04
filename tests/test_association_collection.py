"""Collection guards and serial failure behavior; no real model/network/GPU runs."""

import copy
import importlib.machinery
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import biohub.association_collection as collection
import biohub.association_collection_supervise as supervision
from biohub.association_capture import _sha
from biohub.association_parity import CFG, E23_ENV


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    for key, value in E23_ENV.items():
        monkeypatch.setenv(key, value)
    source = tmp_path / "source.py"
    source.write_text("raise RuntimeError('test source must never execute')\n")
    weights = tmp_path / "weights.bin"
    weights.write_bytes(b"synthetic")
    groups = [{"group_id": f"group{g:02d}", "datasets": [f"v{g * 4 + i:02d}" for i in range(4)],
               "dense_pairs": 4} for g in range(9)]
    reference = {"schema_version": "biohub.association.collection36.preparation.v1", "groups": groups,
                 "datasets": {n: {"frame_counts": [1, 1] + [0] * 98} for g in groups for n in g["datasets"]},
                 "source_sha256": {"on": _sha(source)}, "expected_pair_packets": 3564,
                 "expected_dense_pairs": 36,
                 "limits": {"start_free_disk_bytes": 16 * 1024**3, "group_wall_seconds": 3600,
                            "whole_job_wall_seconds": 14400, "whole_output_bytes": 12 * 1024**3,
                            "rss_bytes": 24 * 1024**3, "whole_writer_seconds": 1200,
                            "whole_observer_seconds": 1200, "dense_pairs_per_run": 450_000_000}}
    ref_path = tmp_path / "reference.json"
    ref_path.write_text(json.dumps(reference))
    monkeypatch.setattr(collection, "REFERENCE_SHA", _sha(ref_path))
    plans, bounds = [], []
    for g in groups:
        image_root = tmp_path / (g["group_id"] + "_images")
        image_root.mkdir()
        for n in g["datasets"]:
            (image_root / (n + ".zarr")).mkdir()
        split = tmp_path / (g["group_id"] + "_splits.json")
        split.write_text(json.dumps([{"split": 0, "train": [], "test": g["datasets"]}]))
        plan = {"schema_version": collection.GROUP_SCHEMA, "group_id": g["group_id"],
                "reference_path": str(ref_path), "data_dir": str(image_root), "splits_file": str(split),
                "datasets": {n: reference["datasets"][n] for n in g["datasets"]},
                "source_sha256": _sha(source), "source_path": str(source), "primary_weights": str(weights),
                "runtime_file_sha256": {str(weights): _sha(weights), str(split): _sha(split)},
                "source_inventory": [{"path": str(source), "sha256": _sha(source)}],
                "submission_authorized": False}
        path = tmp_path / (g["group_id"] + ".json")
        path.write_text(json.dumps(plan))
        bounds.append({"group_id": g["group_id"], "path": str(path), "sha256": _sha(path)})
        plans.append(plan)
    master = {"schema_version": "biohub.association.collection36.master.v1", "reference_path": str(ref_path),
              "repo_dir": str(tmp_path), "group_plans": bounds, "expected_dependencies": {"test": "1"},
              "submission_authorized": False}
    master_path = tmp_path / "master.json"
    master_path.write_text(json.dumps(master))
    return SimpleNamespace(root=tmp_path, reference=reference, plans=plans, bounds=bounds,
                           groups=groups, master=master, master_path=master_path)


def result_for(fixture, index):
    g, plan, bound = fixture.groups[index], fixture.plans[index], fixture.bounds[index]
    return {"status": "COLLECTION_GROUP_COMPLETE", "group_id": g["group_id"], "plan_sha256": bound["sha256"],
            "source_sha256": plan["source_sha256"], "dataset_order": g["datasets"], "observation_complete": True,
            "records": [{"dataset": n, "stage": s} for n in g["datasets"] for s in ("returned", "pre", "post")],
            "pair_count": 396, "dense_pairs": 4, "environment": E23_ENV, "model_config": CFG,
            "submission_authorized": False, "generalization_evidence": False,
            "wall_seconds": 10., "writer_seconds": 1., "observer_seconds": 2.,
            "peak_self_rss_bytes": 1024, "packet_bytes": 100, "dependencies": {"test": "1"}}


def test_bound_plan_passes_without_importing_source(fixture):
    ref, group = collection.validate_plan(fixture.plans[0])
    assert ref == fixture.reference and group == fixture.groups[0]


@pytest.mark.parametrize("case", ["schema", "source", "dataset", "split", "gt_entry", "weights", "env", "reference"])
def test_plan_drift_fails_before_model_import(fixture, monkeypatch, case):
    p = copy.deepcopy(fixture.plans[0])
    if case == "schema":
        p["schema_version"] = "biohub.association.public4.v1"
    elif case == "source":
        Path(p["source_path"]).write_text("changed")
    elif case == "dataset":
        p["datasets"].pop(next(iter(p["datasets"])))
    elif case == "split":
        Path(p["splits_file"]).write_text("[]")
    elif case == "gt_entry":
        (Path(p["data_dir"]) / "v00.geff").mkdir()
    elif case == "weights":
        Path(p["primary_weights"]).write_bytes(b"changed")
    elif case == "env":
        monkeypatch.setenv("BIOHUB_DUAL_SEED_EDGE_THRESHOLD", "0.10")
    else:
        Path(p["reference_path"]).write_text("{}")
    with pytest.raises(ValueError):
        collection.validate_plan(p)


@pytest.mark.parametrize("change", [
    {"status": "COLLECTION_PARTIAL"}, {"group_id": "group01"}, {"records": []},
    {"dataset_order": []}, {"pair_count": 395}, {"dense_pairs": 5}, {"observation_complete": False},
    {"source_sha256": "wrong"}, {"plan_sha256": "wrong"}, {"environment": {}},
    {"wall_seconds": float("nan")}, {"writer_seconds": -1}, {"peak_self_rss_bytes": 25 * 1024**3},
])
def test_incomplete_or_drifted_group_never_accepted(fixture, change):
    with pytest.raises(ValueError):
        collection.validate_group_result({**result_for(fixture, 0), **change}, fixture.plans[0], fixture.groups[0],
                                         fixture.bounds[0]["sha256"])


@pytest.mark.parametrize("case", ["pass", "exit", "rss", "timeout", "disk", "cumulative", "deps", "missing", "plan"])
def test_serial_supervisor_and_stop_on_failure(fixture, monkeypatch, case):
    real_is_dir = Path.is_dir
    monkeypatch.setattr(Path, "is_dir", lambda p: True if str(p) == "/kaggle/working" else real_is_dir(p))
    monkeypatch.setattr(supervision.shutil, "disk_usage", lambda p: SimpleNamespace(free=32 * 1024**3))
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    now, calls, signals = [0.], [], []
    monkeypatch.setattr(supervision.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(supervision.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(supervision, "process_tree_rss", lambda pid: 25 * 1024**3 if case == "rss" else 1024)
    monkeypatch.setattr(supervision.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    if case == "disk":
        monkeypatch.setattr(supervision, "output_bytes", lambda p: 0 if not calls else 13 * 1024**3)

    class Process:
        pid = 987654321

        def __init__(self, command, **kwargs):
            index = len(calls)
            calls.append(index)
            assert kwargs["start_new_session"] and kwargs["env"]["CUDA_VISIBLE_DEVICES"] == "0"
            assert command[1].endswith("e23_association_collect.py")
            self.code = 1 if case == "exit" else None if case in ("rss", "timeout", "disk") else 0
            root = Path(command[command.index("--root") + 1])
            (root / "observation/pairs").mkdir(parents=True)
            result = result_for(fixture, index)
            for name, key in (("observation/MANIFEST.json", "observer_manifest_sha256"),
                              ("observation/pairs/MANIFEST.json", "pair_manifest_sha256")):
                (root / name).write_text("{}")
                result[key] = _sha(root / name)
            if case == "cumulative":
                result["observer_seconds"] = 700.
            if case == "deps":
                result["dependencies"] = {"test": "2"}
            if case != "missing":
                (root / "RESULT.json").write_text(json.dumps(result))
            if case == "plan":
                fixture.master_path.write_text("{}")
            if case == "timeout":
                now[0] = 3601.

        def poll(self):
            return self.code

        def wait(self, timeout=None):
            if self.code is None:
                self.code = -15
            return self.code

    monkeypatch.setattr(supervision.subprocess, "Popen", Process)
    root = fixture.root / "run"
    if case == "pass":
        r = supervision.supervise_collection(fixture.master_path, root, fixture.root, 0.)
        assert calls == list(range(9)) and len(r["completed_groups"]) == 9
        assert r["totals"]["pair_count"] == 3564 and not r["submission_authorized"]
        assert not (root / "ERROR.json").exists()
    else:
        with pytest.raises((ValueError, FileNotFoundError)):
            supervision.supervise_collection(fixture.master_path, root, fixture.root, 0.)
        assert calls == ([0, 1] if case == "cumulative" else [0])
        assert not (root / "RESULT.json").exists() and (root / "ERROR.json").exists()
        assert bool(signals) == (case in ("rss", "timeout", "disk"))


def test_runner_refuses_local_inference(tmp_path):
    with pytest.raises(ValueError, match="Kaggle-only"):
        collection.run_group(tmp_path / "missing.json", tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("case", ["pass", "image_mutation", "capture_failure", "source_mutation"])
def test_group_runner_complete_lifecycle_with_synthetic_capture(fixture, monkeypatch, case):
    import torch

    real_is_dir = Path.is_dir
    monkeypatch.setattr(Path, "is_dir", lambda p: True if str(p) == "/kaggle/working" else real_is_dir(p))
    plan = fixture.plans[0]
    image = Path(plan["data_dir"]) / "v00.zarr/image.bin"
    image.write_bytes(b"synthetic image bytes")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 1)
    monkeypatch.setattr(torch.cuda, "synchronize", lambda: None)
    monkeypatch.setattr(torch.cuda, "get_rng_state_all", lambda: [])
    monkeypatch.setattr(torch.cuda, "max_memory_allocated", lambda: 0)
    monkeypatch.setattr(torch.cuda, "max_memory_reserved", lambda: 0)
    monkeypatch.setattr(collection.importlib.metadata, "version", lambda name: "synthetic")
    monkeypatch.setattr(collection.resource, "getrusage", lambda who: SimpleNamespace(ru_maxrss=1))
    loaded = []

    class Loader:
        def create_module(self, spec):
            return None

        def exec_module(self, module):
            loaded.append(module)

    monkeypatch.setattr(collection.importlib.util, "spec_from_file_location",
                        lambda name, source: importlib.machinery.ModuleSpec(name, Loader()))
    dataspec = ModuleType("dataspec")
    monkeypatch.setitem(sys.modules, "dataspec", dataspec)

    def capture(module, actual_plan, root, arm):
        assert loaded == [module] and actual_plan == plan and arm == "on"
        assert dataspec.PREDICTIONS_PATH == root / "raw_predictions"
        if case == "capture_failure":
            raise ValueError("synthetic capture failed")
        folder = root / "observation/pairs"
        folder.mkdir(parents=True)
        pairs = {"status": "PAIR_CAPTURE_COMPLETE", "records": [{}] * 396,
                 "dense_pairs": 4, "packet_bytes": 100, "writer_seconds": 1.}
        (folder / "MANIFEST.json").write_text(json.dumps(pairs))
        observer = {"status": "ASSOCIATION_OBSERVATION_COMPLETE_NOT_PARITY",
                    "graph_ID_mapping_complete": True, "datasets": fixture.groups[0]["datasets"],
                    "pair_manifest_sha256": _sha(folder / "MANIFEST.json"),
                    "observer_seconds_excluding_final_manifest": 2.}
        (folder.parent / "MANIFEST.json").write_text(json.dumps(observer))
        if case == "image_mutation":
            image.write_bytes(b"changed")
        if case == "source_mutation":
            Path(plan["source_path"]).write_text("changed")
        reference_result = result_for(fixture, 0)
        return {k: reference_result[k] for k in ("dataset_order", "records", "observation_complete")}

    monkeypatch.setattr(collection, "capture_module", capture)
    root = fixture.root / "run_group"
    if case == "pass":
        result = collection.run_group(Path(fixture.bounds[0]["path"]), root)
        assert result["status"] == "COLLECTION_GROUP_COMPLETE" and len(loaded) == 1
        assert not result["paired_off_on_this_group"] and (root / "RESULT.json").exists()
    else:
        with pytest.raises(ValueError):
            collection.run_group(Path(fixture.bounds[0]["path"]), root)
        assert (root / "ERROR.json").exists() and not (root / "RESULT.json").exists()
