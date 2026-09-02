"""Adversarial tests for the fail-closed ST-R3 production supervisor.

The only fresh-process fixture seam replaces the unavailable registered Torch
checkpoint loader.  The child CLI, adapter, graph/image readers, dataset loop,
artifact writers, event pipe, and all three frozen arm mappings remain real.
Supervisor process-failure tests replace only its fixed child script while
retaining the real native-spawn/exec/wait4/pipe-drain path.
"""

from __future__ import annotations

import ast
import csv
import errno
import hashlib
import json
import math
import os
import shutil
import signal
import stat
import struct
import subprocess
import sys
import threading
import warnings
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from biohub.public_postproc import deepcenter as deepcenter_module
from biohub.public_postproc import divisions as divisions_module
from biohub.public_postproc import pipeline as pipeline_module
from biohub.public_postproc import production_adapter as adapter
from biohub.public_postproc import production_supervisor as supervisor

ROOT = Path(__file__).resolve().parents[1]
CHILD_CLI = ROOT / "scripts" / "st_r3_postproc_arm.py"
SUPERVISOR_CLI = ROOT / "scripts" / "st_r3_supervise_arm.py"
SUPERVISOR_SOURCE = ROOT / "src" / "biohub" / "public_postproc" / "production_supervisor.py"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(_canonical(value))


def _digest(path: Path, root: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _image_root(root: Path, shape: tuple[int, int, int, int] = (2, 2, 3, 4)) -> Path:
    root.mkdir()
    for dataset in supervisor.EVAL36:
        metadata = root / f"{dataset}.zarr" / "0" / "zarr.json"
        metadata.parent.mkdir(parents=True)
        _write_json(metadata, {"shape": list(shape)})
    return root


def _submission_rows() -> list[dict[str, str]]:
    rows = []
    for row_id, dataset in enumerate(supervisor.EVAL36):
        rows.append(
            {
                "id": str(row_id),
                "dataset": dataset,
                "row_type": "node",
                "node_id": "0",
                "t": "0",
                "z": "0",
                "y": "0",
                "x": "0",
                "source_id": "-1",
                "target_id": "-1",
            }
        )
    return rows


def _renumber(rows: list[dict[str, str]]) -> None:
    for index, row in enumerate(rows):
        row["id"] = str(index)


def _write_submission(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=supervisor._SUBMISSION_HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _stats_row(dataset: str, arm_name: str = "baseline") -> dict[str, str]:
    row = {name: "0" for name in supervisor._RUN_STATS_COLUMNS}
    row.update(
        {
            "stats_schema_version": supervisor.RUN_STATS_SCHEMA,
            "dataset": dataset,
            "frames": "2",
            "raw_nodes": "1",
            "nodes": "1",
            "edge_to_node_ratio": "0.0",
            "gap_added_nodes_frac": "0.0",
            "gap_close_effective_max_gap": "null",
            "planner_seconds": "null",
        }
    )
    if arm_name == "candidate":
        row["steal_twin_pure_nodes"] = "1"
        row["steal_twin_final_nodes"] = "1"
    return row


def _write_stats(
    path: Path,
    rows: list[dict[str, str]] | None = None,
    arm_name: str = "baseline",
) -> None:
    rows = rows or [_stats_row(dataset, arm_name) for dataset in supervisor.EVAL36]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=supervisor._RUN_STATS_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _deepcenter_receipt() -> dict[str, object]:
    manifest_config = dict(deepcenter_module.STRICT_DEEPCENTER_MANIFEST_MODEL_CONFIG)
    checkpoint_config = dict(deepcenter_module.STRICT_DEEPCENTER_CHECKPOINT_MODEL_CONFIG)
    file_stat = {
        "device": 1,
        "inode": 2,
        "mode": stat.S_IFREG | 0o600,
        "size": 3,
        "mtime_ns": 4,
        "ctime_ns": 5,
    }

    def file_receipt(sha256: str) -> dict[str, object]:
        return {
            "sha256": sha256,
            "pre": file_stat,
            "post_hash": file_stat,
            "post_read": file_stat,
            "open_count": 1,
        }

    return {
        "schema_version": supervisor.DEEPCENTER_RECEIPT_SCHEMA,
        "registered": {
            "checkpoint_name": "registered.pt",
            "manifest_name": "ARTIFACT_MANIFEST.json",
        },
        "checkpoint": file_receipt(deepcenter_module.STRICT_DEEPCENTER_CHECKPOINT_SHA256),
        "manifest": file_receipt(deepcenter_module.STRICT_DEEPCENTER_MANIFEST_SHA256),
        "chosen_artifact": "registered.pt",
        "verified_epoch": 2,
        "verified_configs": {"manifest": manifest_config, "checkpoint": checkpoint_config},
        "known_config_discrepancy": {"field": "epochs", "manifest": 1000, "checkpoint": 50},
        "inference_relevant_config_equal": True,
        "device": "cpu",
        "dtype": "float32",
        "open_count": 2,
        "fallback_candidates": 0,
    }


def _active_plan() -> dict[str, object]:
    plan = divisions_module.TwinPlan(
        validation_reason=None,
        nodes=(divisions_module.TwinSnapshotNode(0, 0, 0.0, 0.0, 0.0, False),),
        edges=(),
        candidates=(),
        accepted_candidates=(),
        decisions=(),
        counters=divisions_module._frozen_twin_counters(divisions_module._twin_counters()),
        debug_records=(),
    )
    return adapter.twin_plan_plain(plan)


def _nonempty_active_plan(dataset: str) -> dict[str, object]:
    scale_y = 0.40625

    def node(node_id: int, frame: int, y_um: float) -> dict[str, object]:
        return {"node_id": node_id, "t": frame, "z": 0.0, "y": y_um / scale_y, "x": 0.0}

    nodes = [
        node(0, -1, 0.0),
        node(1, 0, 0.0),
        node(2, 0, 4.0),
        node(3, 1, 0.0),
        node(4, 1, 6.0),
        node(5, 2, 0.0),
        node(6, 2, 9.0),
    ]
    edges = [
        {"source_id": 0, "target_id": 1, "edge_prob": 0.9},
        {"source_id": 1, "target_id": 3, "edge_prob": 0.8},
        {"source_id": 2, "target_id": 4, "edge_prob": 0.7},
        {"source_id": 3, "target_id": 5, "edge_prob": 0.6},
        {"source_id": 4, "target_id": 6, "edge_prob": 0.5},
    ]
    cfg = adapter.build_config(
        {"BIOHUB_STEAL_TWIN_DRY_RUN": "1"},
        test_dir=Path("."),
        profile="e23_twin_only_v1",
    )
    plan = divisions_module.plan_twin_only_v1(
        cfg,
        dataset,
        nodes,
        edges,
        lambda _node: divisions_module.TwinDeepCenterDecision(True, 0.2, None),
    )
    assert len(plan.accepted_candidates) == 1
    return adapter.twin_plan_plain(plan)


def _build_valid_staging(tmp_path: Path, arm_name: str = "baseline") -> tuple[Path, Path, str]:
    staging = tmp_path / "staging"
    staging.mkdir()
    images = _image_root(tmp_path / "images")
    config_fields: dict[str, object] = {f"field_{index:03d}": index for index in range(94)}
    config_fields.update(
        {
            name: {"__type__": "float64", "bits_hex": struct.pack(">d", value).hex()}
            for name, value in supervisor._FROZEN_ELIGIBILITY_CONFIG_LIMITS.items()
        }
    )
    config = {
        "schema_version": supervisor.EFFECTIVE_CONFIG_SCHEMA,
        "fields": config_fields,
    }
    config_data = _canonical(config)
    (staging / "effective_config.json.partial").write_bytes(config_data)
    _write_json(staging / "deepcenter_receipt.json.partial", _deepcenter_receipt())
    _write_submission(staging / "submission.csv.partial", _submission_rows())
    _write_stats(staging / "run_stats.csv.partial", arm_name=arm_name)
    plans_dir = staging / "twin_plans"
    plans_dir.mkdir()
    manifest_plans = []
    for sequence, dataset in enumerate(supervisor.EVAL36):
        plan_path = plans_dir / f"{sequence}.{dataset}.json"
        active = arm_name != "baseline"
        _write_json(
            plan_path,
            {
                "schema_version": supervisor.TWIN_PLAN_SCHEMA,
                "dataset": dataset,
                "sequence": sequence,
                "planner_active": active,
                "plan": _active_plan() if active else None,
            },
        )
        digest = _digest(plan_path, staging)
        manifest_plans.append(
            {
                "dataset": dataset,
                "sequence": sequence,
                "planner_active": active,
                **digest,
            }
        )
    _write_json(
        staging / "twin_plan_manifest.json.partial",
        {
            "schema_version": supervisor.TWIN_PLAN_MANIFEST_SCHEMA,
            "datasets": list(supervisor.EVAL36),
            "plans": manifest_plans,
        },
    )
    artifact_paths = [
        *supervisor._PARTIAL_PROMOTIONS,
        *(f"twin_plans/{sequence}.{dataset}.json" for sequence, dataset in enumerate(supervisor.EVAL36)),
    ]
    artifacts = [_digest(staging / relative, staging) for relative in artifact_paths]
    _write_json(
        staging / "child_result.json",
        {
            "schema_version": supervisor.CHILD_RESULT_SCHEMA,
            "arm_name": arm_name,
            "datasets": list(supervisor.EVAL36),
            "total_nodes": 36,
            "total_edges": 0,
            "total_rows": 36,
            "artifacts": artifacts,
        },
    )
    return staging, images, hashlib.sha256(config_data).hexdigest()


def _sync_first_stats_to_plan(staging: Path, plan: dict[str, object]) -> None:
    child = json.loads((staging / "child_result.json").read_bytes())
    arm_name = child["arm_name"]
    stats_path = staging / "run_stats.csv.partial"
    with stats_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    row = rows[0]
    counters = dict(plan["counters"]["items"])
    for name, value in counters.items():
        row[name] = str(value)
    for name in supervisor._TWIN_R2_KEYS:
        row[name] = "0"
    if arm_name == "candidate":
        accepted = counters["steal_twin_accepted"]
        row["steal_twin_edges_removed"] = str(accepted)
        row["steal_twin_edges_added"] = str(accepted)
        row["steal_twin_mutations_applied"] = str(accepted)
        row["steal_twin_pure_nodes"] = str(len(plan["nodes"]))
        row["steal_twin_pure_edges"] = str(len(plan["edges"]))
        row["steal_twin_pure_edge_symmetric_difference"] = str(2 * accepted)
        post_pairs = {(edge["source_id"], edge["target_id"]) for edge in plan["edges"]}
        for candidate in plan["accepted_candidates"]:
            post_pairs.remove((candidate["q"], candidate["b"]))
            post_pairs.add((candidate["p"], candidate["b"]))
        sources: dict[int, int] = {}
        for source, _target in post_pairs:
            sources[source] = sources.get(source, 0) + 1
        row["steal_twin_pure_fork_sources"] = str(sum(count == 2 for count in sources.values()))
        row["steal_twin_final_nodes"] = row["steal_twin_pure_nodes"]
        row["steal_twin_final_edges"] = row["steal_twin_pure_edges"]
        row["steal_twin_final_fork_sources"] = row["steal_twin_pure_fork_sources"]
        row["nodes"] = row["steal_twin_final_nodes"]
        row["edges"] = row["steal_twin_final_edges"]
        row["edge_to_node_ratio"] = repr(int(row["edges"]) / max(int(row["nodes"]), 1))
    _write_stats(stats_path, rows)
    child_record = next(item for item in child["artifacts"] if item["relative_path"] == stats_path.name)
    child_record.update(_digest(stats_path, staging))
    _write_json(staging / "child_result.json", child)


def _replace_first_plan_and_rebind(
    staging: Path,
    plan: dict[str, object],
    *,
    sync_stats: bool = False,
) -> None:
    plan_path = staging / f"twin_plans/0.{supervisor.EVAL36[0]}.json"
    envelope = json.loads(plan_path.read_bytes())
    envelope["plan"] = plan
    _write_json(plan_path, envelope)
    plan_digest = _digest(plan_path, staging)
    manifest_path = staging / "twin_plan_manifest.json.partial"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["plans"][0].update(plan_digest)
    _write_json(manifest_path, manifest)
    child_path = staging / "child_result.json"
    child = json.loads(child_path.read_bytes())
    records = {record["relative_path"]: record for record in child["artifacts"]}
    records[plan_digest["relative_path"]].update(plan_digest)
    records[manifest_path.name].update(_digest(manifest_path, staging))
    _write_json(child_path, child)
    if sync_stats:
        _sync_first_stats_to_plan(staging, plan)


def _events(arm_name: str = "baseline", pid: int = 1234) -> bytes:
    lines = []
    monotonic_ns = 100
    for sequence, dataset in enumerate(supervisor.EVAL36):
        for kind in ("START", "FINISH"):
            lines.append(
                _canonical(
                    {
                        "schema_version": supervisor.EVENT_SCHEMA,
                        "pid": pid,
                        "sequence": sequence,
                        "arm_name": arm_name,
                        "dataset": dataset,
                        "kind": kind,
                        "monotonic_ns": monotonic_ns,
                    }
                )
            )
            monotonic_ns += 1
    return b"".join(lines)


def _supervisor_spec(tmp_path: Path, final_dir: Path, digest: str, **changes: object) -> supervisor.SupervisorSpec:
    values: dict[str, object] = {
        "arm_name": "baseline",
        "geff_dir": tmp_path / "raw",
        "test_dir": tmp_path / "images",
        "deepcenter_checkpoint": tmp_path / "registered.pt",
        "deepcenter_manifest": tmp_path / "ARTIFACT_MANIFEST.json",
        "expected_effective_config_sha256": digest,
        "final_dir": final_dir,
        "timeout_seconds": 5.0,
    }
    values.update(changes)
    return supervisor.SupervisorSpec(**values)


def _install_fake_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    fake_root = tmp_path / "fake-repo"
    script = fake_root / "scripts" / "st_r3_postproc_arm.py"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    fake_module = fake_root / "src" / "biohub" / "public_postproc" / "production_supervisor.py"
    monkeypatch.setattr(supervisor, "__file__", str(fake_module))


def _copying_child_source(template: Path) -> str:
    return f"""
import argparse,json,os,shutil,time
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--arm-name');p.add_argument('--geff-dir');p.add_argument('--test-dir')
p.add_argument('--deepcenter-checkpoint');p.add_argument('--deepcenter-manifest')
p.add_argument('--expected-effective-config-sha256');p.add_argument('--staging-dir')
p.add_argument('--event-fd',type=int);p.add_argument('--dataset',action='append')
a=p.parse_args()
template=Path({str(template)!r}); staging=Path(a.staging_dir)
for item in template.iterdir():
    shutil.copytree(item,staging/item.name) if item.is_dir() else shutil.copy2(item,staging/item.name)
previous=0
for sequence,dataset in enumerate(a.dataset):
    for kind in ('START','FINISH'):
        previous=max(previous+1,time.monotonic_ns())
        record={{'schema_version':'{supervisor.EVENT_SCHEMA}','pid':os.getpid(),'sequence':sequence,
                'arm_name':a.arm_name,'dataset':dataset,'kind':kind,'monotonic_ns':previous}}
        os.write(a.event_fd,(json.dumps(record,sort_keys=True,separators=(',',':'))+'\\n').encode())
os.write(1,b'child stdout\\n');os.write(2,b'child stderr\\n')
"""


def _fresh_child_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    import blosc2
    import polars as pl
    import tracksdata as td

    raw = tmp_path / "raw"
    images = tmp_path / "images"
    raw.mkdir()
    images.mkdir()
    graph_template = tmp_path / "template.geff"
    graph = td.graph.InMemoryGraph()
    for key in ("z", "y", "x"):
        graph.add_node_attr_key(key, pl.Float64, -999999.0)
    assert graph.bulk_add_nodes([{"t": 0, "z": 0.0, "y": 0.0, "x": 0.0}]) == [0]
    graph.to_geff(graph_template)
    image_template = tmp_path / "template.zarr"
    array = image_template / "0"
    array.mkdir(parents=True)
    (array / "zarr.json").write_text(json.dumps({"shape": [1, 1, 1, 1], "data_type": "uint16"}))
    chunk = array / "c" / "0" / "0" / "0"
    chunk.mkdir(parents=True)
    (chunk / "0").write_bytes(blosc2.compress(b"\0\0", typesize=2))
    for dataset in supervisor.EVAL36:
        shutil.copytree(graph_template, raw / f"{dataset}.geff")
        shutil.copytree(image_template, images / f"{dataset}.zarr")
    checkpoint = tmp_path / "fixture.pt"
    manifest = tmp_path / "fixture.json"
    checkpoint.write_bytes(b"loader replaced at the unavailable registered Torch boundary")
    manifest.write_bytes(b"{}\n")
    return raw, images, checkpoint, manifest


@pytest.mark.parametrize("arm_name", ["baseline", "dry_run", "candidate"])
def test_all_arms_execute_real_tiny_child_cli_in_fresh_sanitized_process(tmp_path: Path, arm_name: str):
    raw, images, checkpoint, manifest = _fresh_child_fixture(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    read_fd, write_fd = os.pipe()
    spec = adapter.ArmSpec(
        arm_name,
        raw,
        images,
        checkpoint,
        manifest,
        adapter.EVAL36,
        "0" * 64,
        staging,
        write_fd,
    )
    config_sha = hashlib.sha256(adapter._canonical_effective_config(adapter._build_arm_config(spec))).hexdigest()
    code = (
        "import runpy,sys;from pathlib import Path;script=Path(sys.argv.pop(1));"
        "sys.path.insert(0,str(script.resolve().parent.parent/'src'));"
        "import biohub.public_postproc.production_adapter as p;"
        "p.load_deepcenter_veto_detector_strict=lambda *a,**k:"
        "({}, {'schema_version':p.DEEPCENTER_RECEIPT_SCHEMA});"
        "runpy.run_path(str(script),run_name='__main__')"
    )
    argv = [
        sys.executable,
        "-c",
        code,
        str(CHILD_CLI),
        "--arm-name",
        arm_name,
        "--geff-dir",
        str(raw),
        "--test-dir",
        str(images),
        "--deepcenter-checkpoint",
        str(checkpoint),
        "--deepcenter-manifest",
        str(manifest),
        "--expected-effective-config-sha256",
        config_sha,
        "--staging-dir",
        str(staging),
        "--event-fd",
        str(write_fd),
    ]
    for dataset in supervisor.EVAL36:
        argv.extend(("--dataset", dataset))
    process = subprocess.Popen(
        argv,
        cwd=tmp_path,
        env={"PYTHONHASHSEED": "0", "LC_ALL": "C", "LANG": "C", "TZ": "UTC"},
        pass_fds=(write_fd,),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    os.close(write_fd)
    chunks: list[bytes] = []

    def drain_fragmented() -> None:
        while chunk := os.read(read_fd, 7):
            chunks.append(chunk)
        os.close(read_fd)

    thread = threading.Thread(target=drain_fragmented)
    thread.start()
    stdout, stderr = process.communicate(timeout=120)
    thread.join(timeout=5)
    assert process.returncode == 0, (stdout, stderr)
    assert not thread.is_alive()
    data = b"".join(chunks)
    records = supervisor._validate_events(data, arm_name, process.pid)
    assert len(records) == 72
    assert json.loads((staging / "child_result.json").read_bytes())["arm_name"] == arm_name


def test_event_drain_reassembles_fragmented_pipe_reads_and_validates_exact_72():
    data = _events()
    read_fd, write_fd = os.pipe()
    sink = bytearray()
    errors: list[BaseException] = []
    done = threading.Event()
    thread = threading.Thread(target=supervisor._drain_pipe, args=(read_fd, None, sink, done, errors))
    thread.start()
    for offset in range(0, len(data), 3):
        os.write(write_fd, data[offset : offset + 3])
    os.close(write_fd)
    done.set()
    thread.join(timeout=5)
    assert errors == []
    assert bytes(sink) == data
    assert len(supervisor._validate_events(bytes(sink), "baseline", 1234)) == 72


@pytest.mark.parametrize(
    "corruption",
    ["missing", "partial", "extra", "pid", "sequence", "order", "kind", "time", "schema", "noncanonical"],
)
def test_event_contract_rejects_every_identity_cardinality_and_order_corruption(corruption: str):
    lines = _events().splitlines(keepends=True)
    if corruption == "missing":
        lines.pop()
    elif corruption == "partial":
        lines[-1] = lines[-1][:-1]
    elif corruption == "extra":
        lines.append(lines[-1])
    else:
        record = json.loads(lines[1])
        if corruption == "pid":
            record["pid"] = 99
        elif corruption == "sequence":
            record["sequence"] = 1
        elif corruption == "order":
            record["dataset"] = supervisor.EVAL36[1]
        elif corruption == "kind":
            record["kind"] = "START"
        elif corruption == "time":
            record["monotonic_ns"] = 100
        elif corruption == "schema":
            record["extra"] = True
        else:
            lines[1] = json.dumps(record, indent=2).encode() + b"\n"
            with pytest.raises(supervisor.SupervisorError):
                supervisor._validate_events(b"".join(lines), "baseline", 1234)
            return
        lines[1] = _canonical(record)
    with pytest.raises(supervisor.SupervisorError):
        supervisor._validate_events(b"".join(lines), "baseline", 1234)


@pytest.mark.parametrize("arm_name", ["baseline", "dry_run", "candidate"])
def test_valid_complete_staging_contract(tmp_path: Path, arm_name: str):
    staging, images, digest = _build_valid_staging(tmp_path, arm_name)
    child = supervisor._validate_child_staging(staging, arm_name, images, digest)
    assert (child["total_nodes"], child["total_edges"], child["total_rows"]) == (36, 0, 36)


def test_candidate_rejects_nonempty_plan_with_zero_run_stats(tmp_path: Path):
    staging, images, digest = _build_valid_staging(tmp_path, "candidate")
    plan = _nonempty_active_plan(supervisor.EVAL36[0])
    _replace_first_plan_and_rebind(staging, plan)
    with pytest.raises(supervisor.SupervisorError, match="plan/run-stats pre-mutation"):
        supervisor._validate_child_staging(staging, "candidate", images, digest)


@pytest.mark.parametrize("arm_name", ["baseline", "dry_run", "candidate"])
def test_plan_stats_arm_consistency_checks_every_dataset(arm_name: str):
    zero_counters = dict.fromkeys(supervisor._TWIN_COUNTER_KEYS, 0)
    plans = {
        dataset: {
            "counters": dict(zero_counters),
            "nodes": 1 if arm_name != "baseline" else None,
            "edges": 0 if arm_name != "baseline" else None,
            "validation_reason": None,
        }
        for dataset in supervisor.EVAL36
    }
    stats = {
        dataset: {
            **dict.fromkeys((*supervisor._TWIN_COUNTER_KEYS, *supervisor._TWIN_R2_KEYS), 0),
            "steal_twin_pure_nodes": 1 if arm_name == "candidate" else 0,
            "steal_twin_final_nodes": 1 if arm_name == "candidate" else 0,
        }
        for dataset in supervisor.EVAL36
    }
    supervisor._validate_plan_stats_consistency(arm_name, stats, plans)
    for dataset in supervisor.EVAL36:
        if arm_name == "baseline":
            key = "steal_twin_p_pool"
        elif arm_name == "dry_run":
            key = "steal_twin_mutations_applied"
        else:
            key = "steal_twin_pure_nodes"
        stats[dataset][key] += 1
        with pytest.raises(supervisor.SupervisorError, match=dataset):
            supervisor._validate_plan_stats_consistency(arm_name, stats, plans)
        stats[dataset][key] -= 1


@pytest.mark.parametrize(
    "corruption",
    ["hash", "bytes", "missing_record", "extra_record", "unsafe_path", "extra_file", "symlink", "fifo", "child_schema"],
)
def test_child_artifact_schema_path_hash_and_file_type_are_fail_closed(tmp_path: Path, corruption: str):
    staging, images, digest = _build_valid_staging(tmp_path)
    child_path = staging / "child_result.json"
    child = json.loads(child_path.read_bytes())
    if corruption == "hash":
        child["artifacts"][0]["sha256"] = "0" * 64
    elif corruption == "bytes":
        child["artifacts"][0]["bytes"] += 1
    elif corruption == "missing_record":
        child["artifacts"].pop()
    elif corruption == "extra_record":
        child["artifacts"].append(dict(child["artifacts"][0], relative_path="other"))
    elif corruption == "unsafe_path":
        child["artifacts"][0]["relative_path"] = "../escape"
    elif corruption == "extra_file":
        (staging / "unregistered").write_bytes(b"x")
    elif corruption == "symlink":
        victim = staging / child["artifacts"][0]["relative_path"]
        victim.unlink()
        victim.symlink_to(staging / "child_result.json")
    elif corruption == "fifo":
        os.mkfifo(staging / "unregistered-fifo")
    else:
        child["extra"] = True
    if corruption not in {"extra_file", "symlink", "fifo"}:
        _write_json(child_path, child)
    with pytest.raises((supervisor.SupervisorError, FileNotFoundError)):
        supervisor._validate_child_staging(staging, "baseline", images, digest)


def test_regular_file_hashing_detects_identity_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"stable bytes")
    real_lstat = Path.lstat
    calls = 0

    def changed_lstat(path: Path):
        nonlocal calls
        result = real_lstat(path)
        if path == artifact:
            calls += 1
            if calls == 2:
                values = list(result)
                values[8] += 1
                return os.stat_result(values)
        return result

    monkeypatch.setattr(Path, "lstat", changed_lstat)
    with pytest.raises(supervisor.SupervisorError, match="changed while being read"):
        supervisor._regular_bytes(artifact)


def test_regular_file_reader_accepts_single_link_and_rejects_external_hardlink(tmp_path: Path):
    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"isolated")
    assert supervisor._regular_bytes(artifact) == b"isolated"
    alias = tmp_path / "external-alias"
    os.link(artifact, alias)
    assert artifact.stat().st_nlink == 2
    with pytest.raises(supervisor.SupervisorError, match="single-link"):
        supervisor._regular_bytes(artifact)


def test_complete_staging_rejects_external_inode_alias(tmp_path: Path):
    staging, images, digest = _build_valid_staging(tmp_path)
    victim = staging / "submission.csv.partial"
    os.link(victim, tmp_path / "external-submission-alias")
    with pytest.raises(supervisor.SupervisorError, match="single-link"):
        supervisor._validate_child_staging(staging, "baseline", images, digest)


def _write_submission_case(tmp_path: Path, case: str) -> tuple[Path, Path]:
    images = _image_root(tmp_path / "images")
    rows = _submission_rows()
    if case == "bounds":
        rows[0]["x"] = "4"
    elif case == "dataset_order":
        rows[0], rows[1] = rows[1], rows[0]
    elif case == "ids":
        rows[2]["id"] = "9"
    elif case == "referential":
        rows.insert(
            1,
            {
                "id": "0",
                "dataset": supervisor.EVAL36[0],
                "row_type": "edge",
                "node_id": "-1",
                "t": "-1",
                "z": "-1",
                "y": "-1",
                "x": "-1",
                "source_id": "0",
                "target_id": "99",
            },
        )
        _renumber(rows)
    elif case == "node_after_edge":
        edge = dict(rows[0])
        edge.update(row_type="edge", node_id="-1", t="-1", z="-1", y="-1", x="-1", source_id="0", target_id="1")
        rows.insert(1, edge)
        node = dict(rows[0])
        node.update(node_id="1", t="1")
        rows.insert(2, node)
        _renumber(rows)
    elif case in {"outdegree", "indegree"}:
        first = supervisor.EVAL36[0]
        extra_nodes = []
        for node_id in (1, 2, 3):
            node = dict(rows[0])
            node.update(node_id=str(node_id), t="1" if case == "outdegree" else "0")
            extra_nodes.append(node)
        if case == "indegree":
            extra_nodes[-1]["t"] = "1"
        edges = []
        pairs = ((0, 1), (0, 2), (0, 3)) if case == "outdegree" else ((0, 3), (1, 3))
        for source, target in pairs:
            edge = dict(rows[0])
            edge.update(
                row_type="edge",
                node_id="-1",
                t="-1",
                z="-1",
                y="-1",
                x="-1",
                source_id=str(source),
                target_id=str(target),
            )
            edges.append(edge)
        rows = [rows[0], *extra_nodes, *edges, *rows[1:]]
        assert all(row["dataset"] == first for row in rows[: 4 + len(edges)])
        _renumber(rows)
    path = tmp_path / "submission.csv"
    _write_submission(path, rows)
    return path, images


@pytest.mark.parametrize(
    "case",
    ["bounds", "dataset_order", "ids", "referential", "node_after_edge", "outdegree", "indegree"],
)
def test_submission_bounds_order_ids_referential_and_degree(case: str, tmp_path: Path):
    path, images = _write_submission_case(tmp_path, case)
    with pytest.raises(supervisor.SupervisorError):
        supervisor._validate_submission(path, images)


@pytest.mark.parametrize("case", ["quoted", "crlf", "missing_lf", "blank_line"])
def test_submission_rejects_noncanonical_physical_csv(case: str, tmp_path: Path):
    images = _image_root(tmp_path / "images")
    path = tmp_path / "submission.csv"
    _write_submission(path, _submission_rows())
    data = path.read_bytes()
    if case == "quoted":
        lines = data.splitlines(keepends=True)
        lines[1] = b'"0",' + lines[1].split(b",", 1)[1]
        data = b"".join(lines)
    elif case == "crlf":
        data = data.replace(b"\n", b"\r\n")
    elif case == "missing_lf":
        data = data[:-1]
    else:
        data += b"\n"
    path.write_bytes(data)
    with pytest.raises(supervisor.SupervisorError, match="CSV artifact"):
        supervisor._validate_submission(path, images)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("steal_twin_validation_failed", "1"),
        ("steal_twin_enumerated", "2"),
        ("steal_twin_edges_removed", "1"),
        ("edge_to_node_ratio", "1.0"),
        ("steal_twin_final_nodes", "2"),
    ],
)
def test_run_stats_schema_and_essential_conservation(tmp_path: Path, column: str, value: str):
    rows = [_stats_row(dataset) for dataset in supervisor.EVAL36]
    rows[0][column] = value
    if column == "steal_twin_final_nodes":
        rows[0]["steal_twin_pure_nodes"] = "1"
    path = tmp_path / "stats.csv"
    _write_stats(path, rows)
    with pytest.raises(supervisor.SupervisorError):
        supervisor._validate_run_stats(path)


@pytest.mark.parametrize("case", ["missing_row", "extra_row", "dataset_order", "schema", "header", "blank"])
def test_run_stats_exact_schema_width_and_dataset_order(tmp_path: Path, case: str):
    rows = [_stats_row(dataset) for dataset in supervisor.EVAL36]
    fieldnames = list(supervisor._RUN_STATS_COLUMNS)
    if case == "missing_row":
        rows.pop()
    elif case == "extra_row":
        rows.append(dict(rows[-1]))
    elif case == "dataset_order":
        rows[0], rows[1] = rows[1], rows[0]
    elif case == "schema":
        rows[0]["stats_schema_version"] = "wrong"
    elif case == "header":
        fieldnames[0], fieldnames[1] = fieldnames[1], fieldnames[0]
    else:
        rows[0]["frames"] = ""
    path = tmp_path / "stats.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(supervisor.SupervisorError):
        supervisor._validate_run_stats(path)


@pytest.mark.parametrize("case", ["quoted", "crlf", "missing_lf", "blank_line"])
def test_run_stats_rejects_noncanonical_physical_csv(case: str, tmp_path: Path):
    path = tmp_path / "stats.csv"
    _write_stats(path)
    data = path.read_bytes()
    if case == "quoted":
        lines = data.splitlines(keepends=True)
        cells = lines[1].split(b",")
        cells[2] = b'"2"'
        lines[1] = b",".join(cells)
        data = b"".join(lines)
    elif case == "crlf":
        data = data.replace(b"\n", b"\r\n")
    elif case == "missing_lf":
        data = data[:-1]
    else:
        data += b"\n"
    path.write_bytes(data)
    with pytest.raises(supervisor.SupervisorError, match="CSV artifact"):
        supervisor._validate_run_stats(path)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"frames": "0"}, "frames must be a positive"),
        ({"nodes": "0"}, "invalid raw stats graph counts"),
        ({"steal_twin_validation_missing_node_field": "1"}, "validation reason counters"),
        ({"steal_twin_enumerated": "1", "steal_twin_p_pool": "1"}, "enumeration conservation"),
        (
            {"steal_twin_enumerated": "1", "steal_twin_p_pool": "1", "steal_twin_eligible": "1"},
            "resolution conservation",
        ),
        (
            {
                "steal_twin_enumerated": "1",
                "steal_twin_p_pool": "1",
                "steal_twin_eligible": "1",
                "steal_twin_accepted": "1",
                "steal_twin_isolated_donors": "1",
                "steal_twin_examined_frames": "1",
            },
            "planned-edge conservation",
        ),
        ({"steal_twin_isolated_donors": "1"}, "isolated-donor conservation"),
        (
            {
                "steal_twin_enumerated": "3",
                "steal_twin_p_pool": "3",
                "steal_twin_eligible": "3",
                "steal_twin_accepted": "3",
                "steal_twin_planned_edges_removed": "3",
                "steal_twin_planned_edges_added": "3",
                "steal_twin_isolated_donors": "3",
                "steal_twin_examined_frames": "3",
            },
            "frozen cap conservation",
        ),
        ({"steal_twin_pure_edge_symmetric_difference": "1"}, "symmetric-difference conservation"),
        (
            {
                "steal_twin_enumerated": "2",
                "steal_twin_p_pool": "2",
                "steal_twin_eligible": "2",
                "steal_twin_accepted": "2",
                "steal_twin_examined_frames": "2",
                "steal_twin_planned_edges_removed": "2",
                "steal_twin_planned_edges_added": "2",
                "steal_twin_isolated_donors": "2",
                "steal_twin_edges_removed": "1",
                "steal_twin_edges_added": "1",
                "steal_twin_mutations_applied": "1",
                "steal_twin_pure_edge_symmetric_difference": "2",
            },
            "accepted/mutation conservation",
        ),
        ({"steal_twin_final_nodes": "1"}, "inactive ST-R2 topology"),
        (
            {"steal_twin_pure_nodes": "2", "steal_twin_final_nodes": "1"},
            "node conservation",
        ),
        (
            {
                "steal_twin_pure_nodes": "1",
                "steal_twin_final_nodes": "1",
                "steal_twin_pure_edges": "2",
                "steal_twin_final_edges": "1",
                "edges": "1",
                "edge_to_node_ratio": "1.0",
            },
            "edge conservation",
        ),
        (
            {
                "steal_twin_pure_nodes": "2",
                "steal_twin_final_nodes": "2",
            },
            "final graph count mismatch",
        ),
        (
            {
                "steal_twin_pure_nodes": "1",
                "steal_twin_final_nodes": "1",
                "steal_twin_pure_fork_sources": "2",
            },
            "fork/linefit count",
        ),
        ({"steal_twin_debug_records_written": "1"}, "debug-record conservation"),
    ],
)
def test_run_stats_rejects_full_child_conservation_contract(tmp_path: Path, updates: dict[str, str], message: str):
    rows = [_stats_row(dataset) for dataset in supervisor.EVAL36]
    rows[0].update(updates)
    raw_row: dict[str, object] = {}
    for name in adapter._RAW_STATS_COLUMNS:
        value = rows[0][name]
        raw_row[name] = (
            value
            if name == "dataset"
            else float(value)
            if name
            in {
                "edge_to_node_ratio",
                "gap_added_nodes_frac",
            }
            else int(value)
        )
    with pytest.raises((TypeError, ValueError, RuntimeError), match=message):
        adapter._validate_raw_stats_row(raw_row, supervisor.EVAL36[0], frames_count=int(rows[0]["frames"]))
    path = tmp_path / "stats.csv"
    _write_stats(path, rows)
    with pytest.raises(supervisor.SupervisorError, match=message):
        supervisor._validate_run_stats(path)


@pytest.mark.parametrize(
    "field",
    [
        "registered",
        "chosen_artifact",
        "verified_configs",
        "device",
        "checkpoint_open_count",
        "manifest_stat_drift",
        "checkpoint_extra",
    ],
)
def test_deepcenter_receipt_binds_registered_identity_and_verified_configuration(tmp_path: Path, field: str):
    staging, images, digest = _build_valid_staging(tmp_path)
    del images
    path = staging / "deepcenter_receipt.json.partial"
    receipt = json.loads(path.read_bytes())
    if field == "checkpoint_open_count":
        receipt["checkpoint"]["open_count"] = 2
    elif field == "manifest_stat_drift":
        receipt["manifest"]["post_read"]["mtime_ns"] += 1
    elif field == "checkpoint_extra":
        receipt["checkpoint"]["extra"] = True
    else:
        receipt[field] = "spoofed"
    _write_json(path, receipt)
    child_path = staging / "child_result.json"
    child = json.loads(child_path.read_bytes())
    record = next(item for item in child["artifacts"] if item["relative_path"] == path.name)
    record.update(_digest(path, staging))
    _write_json(child_path, child)
    artifacts = {item["relative_path"]: item for item in child["artifacts"]}
    with pytest.raises(supervisor.SupervisorError, match="DeepCenter"):
        supervisor._validate_json_artifacts(staging, "baseline", artifacts, digest)


def test_supervisor_binds_deepcenter_registered_names_to_spec_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    template_root = tmp_path / "template-root"
    template_root.mkdir()
    template, _images, digest = _build_valid_staging(template_root)
    _install_fake_child(tmp_path, monkeypatch, _copying_child_source(template))
    run_root = tmp_path / "run"
    run_root.mkdir()
    images = _image_root(run_root / "images")
    final = run_root / "final"
    spec = _supervisor_spec(
        run_root,
        final,
        digest,
        test_dir=images,
        deepcenter_checkpoint=run_root / "different-checkpoint-name.pt",
        deepcenter_manifest=run_root / "different-manifest-name.json",
    )
    result = supervisor.supervise_arm(spec)
    assert result.success is False
    assert not final.exists()
    assert result.receipt_path is not None
    assert "DeepCenter" in json.loads(result.receipt_path.read_bytes())["failure"]["message"]


@pytest.mark.parametrize("target", ["config_hash", "config_schema", "plan", "manifest"])
def test_config_plan_and_manifest_validation(tmp_path: Path, target: str):
    staging, images, digest = _build_valid_staging(tmp_path)
    if target == "config_hash":
        digest = "0" * 64
    elif target == "config_schema":
        path = staging / "effective_config.json.partial"
        _write_json(path, {"schema_version": supervisor.EFFECTIVE_CONFIG_SCHEMA, "fields": {}})
    elif target == "plan":
        path = staging / f"twin_plans/0.{supervisor.EVAL36[0]}.json"
        plan = json.loads(path.read_bytes())
        plan["sequence"] = 1
        _write_json(path, plan)
    else:
        path = staging / "twin_plan_manifest.json.partial"
        manifest = json.loads(path.read_bytes())
        manifest["plans"].reverse()
        _write_json(path, manifest)
    if target != "config_hash":
        child_path = staging / "child_result.json"
        child = json.loads(child_path.read_bytes())
        relative = path.relative_to(staging).as_posix()
        record = next(item for item in child["artifacts"] if item["relative_path"] == relative)
        record.update(_digest(path, staging))
        _write_json(child_path, child)
    with pytest.raises(supervisor.SupervisorError):
        supervisor._validate_child_staging(staging, "baseline", images, digest)


@pytest.mark.parametrize("name", tuple(supervisor._FROZEN_ELIGIBILITY_CONFIG_LIMITS))
def test_effective_config_rejects_drift_of_every_supervisor_eligibility_literal(tmp_path: Path, name: str):
    staging, images, _digest_value = _build_valid_staging(tmp_path)
    config_path = staging / "effective_config.json.partial"
    config = json.loads(config_path.read_bytes())
    expected = supervisor._FROZEN_ELIGIBILITY_CONFIG_LIMITS[name]
    config["fields"][name]["bits_hex"] = struct.pack(">d", math.nextafter(expected, math.inf)).hex()
    _write_json(config_path, config)
    child_path = staging / "child_result.json"
    child = json.loads(child_path.read_bytes())
    record = next(item for item in child["artifacts"] if item["relative_path"] == config_path.name)
    record.update(_digest(config_path, staging))
    _write_json(child_path, child)
    drifted_digest = hashlib.sha256(config_path.read_bytes()).hexdigest()
    with pytest.raises(supervisor.SupervisorError, match=name):
        supervisor._validate_child_staging(staging, "baseline", images, drifted_digest)


@pytest.mark.parametrize(("field", "value"), [("nodes", {}), ("counters", []), ("validation_reason", 7)])
def test_active_twin_plan_nested_schema_is_independently_validated(tmp_path: Path, field: str, value: object):
    staging, images, digest = _build_valid_staging(tmp_path, "candidate")
    plan = _active_plan()
    plan[field] = value
    _replace_first_plan_and_rebind(staging, plan)
    with pytest.raises(supervisor.SupervisorError, match="active twin plan"):
        supervisor._validate_child_staging(staging, "candidate", images, digest)


def _corrupt_nonempty_plan(plan: dict[str, object], case: str) -> None:
    candidate = plan["candidates"][0]
    counter_items = plan["counters"]["items"]

    def set_counter(name: str, value: object) -> None:
        entry = next(item for item in counter_items if item[0] == name)
        entry[1] = value

    if case == "node_keys":
        plan["nodes"][0]["extra"] = True
    elif case == "node_exact_type":
        plan["nodes"][0]["gap_synthetic"] = 0
    elif case == "edge_keys":
        del plan["edges"][0]["input_position"]
    elif case == "candidate_keys":
        candidate["extra"] = True
    elif case == "candidate_exact_type":
        candidate["p"] = True
    elif case == "deepcenter_keys":
        del candidate["deepcenter_decision"]["reason"]
    elif case == "removed_endpoint":
        candidate["removed_edge"]["target_id"] = 99
    elif case == "planned_distance_type":
        candidate["planned_edge"]["distance_um"] = "6.0"
    elif case == "sort_key_roles":
        candidate["sort_key"][-1] = 99
    elif case == "accepted_membership":
        plan["accepted_candidates"][0]["p"] = 99
    elif case == "decision_semantics":
        plan["decisions"][0].update(accepted=True, reason="conflict")
    elif case == "counter_keys":
        counter_items.pop(1)
    elif case == "counter_exact_type":
        set_counter("steal_twin_p_pool", True)
    elif case == "counter_nonnegative":
        set_counter("steal_twin_p_pool", -1)
    elif case == "counter_conservation":
        set_counter("steal_twin_enumerated", 2)
    elif case == "debug_dataset":
        plan["debug_records"][0]["dataset"] = "wrong"
    elif case == "debug_threshold":
        plan["debug_records"][0]["deepcenter_threshold"] = 0.13
    elif case == "debug_removed_endpoint":
        plan["debug_records"][0]["removed_edge"]["target_id"] = 99
    elif case == "validation_failure_envelope":
        plan["validation_reason"] = "invalid_node_id"
    else:  # pragma: no cover - the parameter table below is closed
        raise AssertionError(case)


def _recompute_candidate_geometry(plan: dict[str, object]) -> None:
    nodes = {node["node_id"]: node for node in plan["nodes"]}
    candidate = plan["candidates"][0]
    p, q, a, b, a2, b2 = (candidate[name] for name in ("p", "q", "a", "b", "a2", "b2"))
    distances = (
        supervisor._twin_distance(nodes[p], nodes[q]),
        supervisor._twin_distance(nodes[p], nodes[a]),
        supervisor._twin_distance(nodes[p], nodes[b]),
        supervisor._twin_distance(nodes[a], nodes[b]),
        supervisor._twin_distance(nodes[a2], nodes[b2]),
    )
    growth = distances[4] - distances[3]
    projected = (
        plan["candidates"][0],
        plan["accepted_candidates"][0],
        plan["decisions"][0]["candidate"],
    )
    for item in projected:
        for name, value in zip(("d_pq", "d_pa", "d_pb", "d_ab", "d_a2b2"), distances, strict=True):
            item[name] = value
        item["divergence_growth"] = growth
        item["sort_key"][:3] = [distances[2] + 0.15 * distances[3], -growth, distances[0]]
        item["planned_edge"]["distance_um"] = distances[2]
    record = plan["debug_records"][0]
    for name in (
        "d_pq",
        "d_pa",
        "d_pb",
        "d_ab",
        "d_a2b2",
        "divergence_growth",
        "sort_key",
        "planned_edge",
    ):
        record[name] = projected[0][name]


def test_supervisor_distance_is_bit_exact_to_planner_float64_path():
    left = {"z": 9708.698282224668, "y": -5125.86512437454, "x": -2213.0966909122753}
    right = {"z": 6634.519841080237, "y": 2497.989395186005, "x": -9071.277124432057}
    expected = divisions_module._twin_distance(SimpleNamespace(**left), SimpleNamespace(**right))
    actual = supervisor._twin_distance(left, right)
    assert actual.hex() == expected.hex() == "0x1.968a83660a75cp+12"


@pytest.mark.parametrize(
    "case",
    ["twin", "existing_child", "parent", "sister_low", "sister_high", "divergence", "deepcenter"],
)
def test_active_plan_rejects_every_frozen_eligibility_boundary(case: str):
    plan = _nonempty_active_plan(supervisor.EVAL36[0])
    candidate = plan["candidates"][0]
    nodes = {node["node_id"]: node for node in plan["nodes"]}
    scale_y = 0.40625
    if case == "twin":
        nodes[candidate["q"]]["y"] = math.nextafter(5.0, math.inf) / scale_y
    elif case == "existing_child":
        nodes[candidate["a"]]["y"] = math.nextafter(10.0, math.inf) / scale_y
    elif case == "parent":
        nodes[candidate["b"]]["y"] = 9.0 / scale_y
        nodes[candidate["b2"]]["y"] = 12.0 / scale_y
    elif case == "sister_low":
        nodes[candidate["b"]]["y"] = math.nextafter(5.5, -math.inf) / scale_y
    elif case == "sister_high":
        nodes[candidate["b"]]["y"] = math.nextafter(11.0, math.inf) / scale_y
    elif case == "divergence":
        target_um = 6.0 + 2.249
        nodes[candidate["b2"]]["y"] = target_um / scale_y
    else:
        for item in (
            plan["candidates"][0],
            plan["accepted_candidates"][0],
            plan["decisions"][0]["candidate"],
        ):
            item["raw_deepcenter_score"] = 0.01
            item["deepcenter_decision"]["raw_score"] = 0.01
        plan["debug_records"][0]["raw_deepcenter_score"] = 0.01
        plan["debug_records"][0]["deepcenter_decision"]["raw_score"] = 0.01
    if case != "deepcenter":
        _recompute_candidate_geometry(plan)
    with pytest.raises(supervisor.SupervisorError, match="active twin plan"):
        supervisor._validate_active_twin_plan(plan, supervisor.EVAL36[0])


@pytest.mark.parametrize("distance", [8.0, math.nextafter(8.0, math.inf), 9.0])
def test_parent_to_b_limit_uses_exact_frozen_eight_micron_boundary(distance: float):
    plan = _nonempty_active_plan(supervisor.EVAL36[0])
    candidate = plan["candidates"][0]
    nodes = {node["node_id"]: node for node in plan["nodes"]}
    nodes[candidate["b"]]["y"] = distance / 0.40625
    nodes[candidate["b2"]]["y"] = (distance + 3.0) / 0.40625
    _recompute_candidate_geometry(plan)
    assert plan["candidates"][0]["d_pb"].hex() == distance.hex()
    if distance == 8.0:
        supervisor._validate_active_twin_plan(plan, supervisor.EVAL36[0])
    else:
        with pytest.raises(supervisor.SupervisorError, match="frozen eligibility boundary"):
            supervisor._validate_active_twin_plan(plan, supervisor.EVAL36[0])


def test_active_plan_rejects_nonmutual_ambiguous_parent_pool():
    plan = _nonempty_active_plan(supervisor.EVAL36[0])
    candidate = plan["candidates"][0]
    p_node = next(node for node in plan["nodes"] if node["node_id"] == candidate["p"])
    plan["nodes"].extend(
        [
            {
                "node_id": 7,
                "t": candidate["frame"],
                "z": p_node["z"],
                "y": -candidate["d_pq"] / 0.40625,
                "x": p_node["x"],
                "gap_synthetic": False,
            },
            {"node_id": 8, "t": candidate["frame"] + 1, "z": 0.0, "y": -10.0, "x": 0.0, "gap_synthetic": False},
        ]
    )
    metadata = {
        "__twin_type__": "mapping",
        "items": [["source_id", 7], ["target_id", 8], ["edge_prob", 0.4]],
    }
    plan["edges"].append({"source_id": 7, "target_id": 8, "input_position": 5, "metadata": metadata})
    q_pool = next(item for item in plan["counters"]["items"] if item[0] == "steal_twin_q_pool")
    q_pool[1] += 1
    with pytest.raises(supervisor.SupervisorError, match="mutual-nearest"):
        supervisor._validate_active_twin_plan(plan, supervisor.EVAL36[0])


def _plain_dtype(*, itemsize: int = 8, hasobject: bool = False) -> dict[str, object]:
    return {
        "__twin_type__": "numpy_dtype",
        "string": "|O" if hasobject else "<f8",
        "descriptor": {"__twin_type__": "tuple", "items": []},
        "metadata": None,
        "itemsize": itemsize,
        "alignment": itemsize,
        "byteorder": "|" if hasobject else "=",
        "names": None,
        "hasobject": hasobject,
        "aligned_struct": False,
    }


def test_twin_plain_codec_accepts_every_supported_producer_representation():
    structured = np.array((3, 1.25), dtype=[("count", "<i2"), ("score", "<f8")])[()]
    value = {
        "finite": -0.0,
        "special": float("nan"),
        "complex": complex(float("inf"), -2.0),
        "bytes": b"\x00\xff",
        "tuple": (1, "x"),
        "frozenset": frozenset({"a", "b"}),
        "dtype": np.dtype("<f8", metadata={"unit": "test"}),
        "aligned_dtype": np.dtype([("a", "u1"), ("b", "<f8")], align=True),
        "titled_dtype": np.dtype([(("label", "field"), "<i4")]),
        "nested_dtype": np.dtype([("outer", [("inner", "<i2")])]),
        "subarray_dtype": np.dtype(("<f4", (2, 3))),
        "structured": structured,
        "scalar": np.float32(1.5),
        "array": np.arange(6, dtype=np.int16).reshape(2, 3),
        "object_array": np.asarray([{"a": 1}, ("b", 2)], dtype=object),
        "bytearray": bytearray(b"ab"),
        "memoryview": memoryview(b"cd"),
    }
    frozen = divisions_module._freeze_twin_value(value)
    plain = pipeline_module._twin_frozen_value_plain(frozen)
    token = supervisor._plain_twin_token(plain)
    assert token[0] == "mapping"


@pytest.mark.parametrize(
    "value",
    [
        {"__twin_type__": "float", "value": "nan", "bits_hex": "7ff0000000000000"},
        {"__twin_type__": "complex", "real": 1, "imag": 0.0},
        {"__twin_type__": "frozenset", "items": [1, 1]},
        _plain_dtype(),
        {**_plain_dtype(), "metadata": "not-a-mapping"},
        {**_plain_dtype(), "names": ["x", "x"]},
        {"__twin_type__": "numpy_scalar", "dtype": _plain_dtype(), "content": "00"},
        {
            "__twin_type__": "numpy_array",
            "dtype": _plain_dtype(),
            "shape": [2],
            "strides": [8],
            "c_contiguous": True,
            "f_contiguous": True,
            "object_content": False,
            "content_hex": "00" * 8,
        },
        {
            "__twin_type__": "numpy_array",
            "dtype": _plain_dtype(hasobject=True),
            "shape": [2],
            "strides": [8],
            "c_contiguous": True,
            "f_contiguous": True,
            "object_content": True,
            "content": {"__twin_type__": "tuple", "items": [1]},
        },
        {
            "__twin_type__": "buffer",
            "kind": "memoryview",
            "format": "B",
            "itemsize": 1,
            "shape": [2],
            "strides": [1],
            "readonly": True,
            "content_hex": "00",
        },
    ],
)
def test_twin_plain_codec_rejects_impossible_or_inconsistent_objects(value: object):
    with pytest.raises(supervisor.SupervisorError, match="active twin plan"):
        supervisor._plain_twin_token(value)


def test_full_plan_rejects_special_float_label_bits_mismatch():
    plan = _nonempty_active_plan(supervisor.EVAL36[0])
    candidate = plan["candidates"][0]
    edge = next(
        item for item in plan["edges"] if (item["source_id"], item["target_id"]) == (candidate["q"], candidate["b"])
    )
    malformed = {"__twin_type__": "float", "value": "nan", "bits_hex": "7ff0000000000000"}
    metadata_values = (
        edge["metadata"],
        plan["candidates"][0]["removed_edge"]["metadata"],
        plan["accepted_candidates"][0]["removed_edge"]["metadata"],
        plan["decisions"][0]["candidate"]["removed_edge"]["metadata"],
        plan["debug_records"][0]["removed_edge"]["metadata"],
    )
    for metadata in metadata_values:
        metadata["items"].append(["malformed", malformed])
    with pytest.raises(supervisor.SupervisorError, match="label/bits"):
        supervisor._validate_active_twin_plan(plan, supervisor.EVAL36[0])


@pytest.mark.parametrize(
    "case",
    [
        "node_keys",
        "node_exact_type",
        "edge_keys",
        "candidate_keys",
        "candidate_exact_type",
        "deepcenter_keys",
        "removed_endpoint",
        "planned_distance_type",
        "sort_key_roles",
        "accepted_membership",
        "decision_semantics",
        "counter_keys",
        "counter_exact_type",
        "counter_nonnegative",
        "counter_conservation",
        "debug_dataset",
        "debug_threshold",
        "debug_removed_endpoint",
        "validation_failure_envelope",
    ],
)
def test_active_twin_plan_exact_nested_schema_and_invariants(tmp_path: Path, case: str):
    staging, images, digest = _build_valid_staging(tmp_path, "candidate")
    plan = _nonempty_active_plan(supervisor.EVAL36[0])
    _replace_first_plan_and_rebind(staging, plan, sync_stats=True)
    _corrupt_nonempty_plan(plan, case)
    _replace_first_plan_and_rebind(staging, plan)
    with pytest.raises(supervisor.SupervisorError, match="active twin plan"):
        supervisor._validate_child_staging(staging, "candidate", images, digest)


@pytest.mark.parametrize("arm_name", ["dry_run", "candidate"])
def test_dry_run_and_candidate_accept_the_same_valid_active_plan_schema(tmp_path: Path, arm_name: str):
    staging, images, digest = _build_valid_staging(tmp_path, arm_name)
    _replace_first_plan_and_rebind(
        staging,
        _nonempty_active_plan(supervisor.EVAL36[0]),
        sync_stats=True,
    )
    child = supervisor._validate_child_staging(staging, arm_name, images, digest)
    assert child["arm_name"] == arm_name


def test_partial_promotion_is_no_clobber_and_preserves_existing_target(tmp_path: Path):
    staging = tmp_path / "staging"
    staging.mkdir()
    for source in supervisor._PARTIAL_PROMOTIONS:
        (staging / source).write_bytes(source.encode())
    collision = staging / "run_stats.csv"
    collision.write_bytes(b"preexisting")
    with pytest.raises(FileExistsError):
        supervisor._promote_partial_files(staging)
    assert collision.read_bytes() == b"preexisting"
    assert (staging / "run_stats.csv.partial").read_bytes() == b"run_stats.csv.partial"


@pytest.mark.parametrize("collision_name", list(supervisor._PARTIAL_PROMOTIONS.values()))
@pytest.mark.parametrize("collision_kind", ["file", "symlink"])
def test_each_partial_promotion_target_refuses_regular_or_symlink_clobber(
    tmp_path: Path, collision_name: str, collision_kind: str
):
    staging = tmp_path / "staging"
    staging.mkdir()
    for source in supervisor._PARTIAL_PROMOTIONS:
        (staging / source).write_bytes(source.encode())
    collision = staging / collision_name
    owner = tmp_path / "owned"
    owner.write_bytes(b"owned by someone else")
    if collision_kind == "file":
        collision.write_bytes(owner.read_bytes())
    else:
        collision.symlink_to(owner)
    with pytest.raises(FileExistsError):
        supervisor._promote_partial_files(staging)
    assert collision.read_bytes() == b"owned by someone else"
    assert collision.is_symlink() is (collision_kind == "symlink")


def test_successful_partial_promotions_are_same_inode_links_then_remove_partial_names(tmp_path: Path):
    staging = tmp_path / "staging"
    staging.mkdir()
    source_inodes = {}
    for source in supervisor._PARTIAL_PROMOTIONS:
        path = staging / source
        path.write_bytes(source.encode())
        source_inodes[source] = path.stat().st_ino
    assert supervisor._promote_partial_files(staging) == supervisor._PARTIAL_PROMOTIONS
    for source, destination in supervisor._PARTIAL_PROMOTIONS.items():
        assert not (staging / source).exists()
        assert (staging / destination).stat().st_ino == source_inodes[source]


def test_readonly_tree_seal_detects_post_validation_content_and_mode_mutation(tmp_path: Path):
    staging = tmp_path / "staging"
    staging.mkdir()
    artifact = staging / "artifact.txt"
    artifact.write_bytes(b"validated")
    staging_fd = os.open(staging, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    seal = supervisor._seal_tree_readonly(staging, staging_fd)
    try:
        assert stat.S_IMODE(artifact.stat().st_mode) == 0o400
        os.chmod(artifact, 0o600)
        artifact.write_bytes(b"mutated-after-validation")
        with pytest.raises(supervisor.SupervisorError, match="changed after sealing"):
            supervisor._verify_tree_seal(seal)
    finally:
        supervisor._release_tree_seal(seal, writable=True)
        os.close(staging_fd)


def test_true_directory_rename_no_replace_and_collision(tmp_path: Path):
    parent_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        source = tmp_path / "source"
        source.mkdir()
        (source / "sentinel").write_bytes(b"sealed")
        primitive = supervisor._publish_directory_no_replace(parent_fd, "source", "final")
        assert "RENAME" in primitive
        assert not source.exists()
        assert (tmp_path / "final" / "sentinel").read_bytes() == b"sealed"
        collision_source = tmp_path / "source2"
        collision_source.mkdir()
        with pytest.raises(FileExistsError):
            supervisor._publish_directory_no_replace(parent_fd, "source2", "final")
        assert collision_source.is_dir()
        assert (tmp_path / "final" / "sentinel").read_bytes() == b"sealed"
    finally:
        os.close(parent_fd)


def test_post_rename_hardlink_race_is_rolled_back_to_unpredictable_failure_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "payload").write_bytes(b"sealed")
    staging_fd = os.open(staging, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    parent_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    seal = supervisor._seal_tree_readonly(staging, staging_fd)
    parent_info = os.fstat(parent_fd)
    key = (parent_info.st_dev, parent_info.st_ino, "staging")
    supervisor._PENDING_PUBLICATION_SEALS[key] = seal
    external_alias = tmp_path / "external-alias"
    real_verify = supervisor._verify_tree_seal
    verify_calls = 0

    def verify_then_inject_alias(tree_seal: supervisor._TreeSeal) -> None:
        nonlocal verify_calls
        real_verify(tree_seal)
        verify_calls += 1
        if verify_calls == 1:
            os.link(staging / "payload", external_alias)

    monkeypatch.setattr(supervisor, "_verify_tree_seal", verify_then_inject_alias)
    try:
        with pytest.raises(supervisor._PublicationPostconditionError) as caught:
            supervisor._publish_directory_no_replace(parent_fd, "staging", "final")
        error = caught.value
        assert not error.final_present and not error.rollback_failed and error.rollback_name is not None
        assert error.rollback_name.startswith(".final.failed.")
        assert not (tmp_path / "final").exists()
        assert (tmp_path / error.rollback_name / "payload").read_bytes() == b"sealed"
        assert external_alias.stat().st_nlink == 2
    finally:
        supervisor._PENDING_PUBLICATION_SEALS.pop(key, None)
        supervisor._release_tree_seal(seal, writable=True)
        os.close(staging_fd)
        os.close(parent_fd)
        external_alias.unlink(missing_ok=True)


def test_final_postcondition_check_return_window_is_explicitly_held(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "payload").write_bytes(b"sealed")
    staging_fd = os.open(staging, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    parent_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    seal = supervisor._seal_tree_readonly(staging, staging_fd)
    parent_info = os.fstat(parent_fd)
    key = (parent_info.st_dev, parent_info.st_ino, "staging")
    supervisor._PENDING_PUBLICATION_SEALS[key] = seal
    external_alias = tmp_path / "external-alias"
    real_verify = supervisor._verify_tree_seal
    verify_calls = 0

    def verify_then_inject_after_final_check(tree_seal: supervisor._TreeSeal) -> None:
        nonlocal verify_calls
        real_verify(tree_seal)
        verify_calls += 1
        if verify_calls == 2:
            os.link(tree_seal.staging / "payload", external_alias)

    monkeypatch.setattr(supervisor, "_verify_tree_seal", verify_then_inject_after_final_check)
    try:
        assert "RENAME" in supervisor._publish_directory_no_replace(parent_fd, "staging", "final")
        assert (tmp_path / "final" / "payload").stat().st_nlink == 2
        assert "HOLD_PUBLICATION_CONCURRENCY_UNPROVEN" in supervisor._LOCAL_HOLDS
    finally:
        supervisor._PENDING_PUBLICATION_SEALS.pop(key, None)
        supervisor._release_tree_seal(seal, writable=True)
        os.close(staging_fd)
        os.close(parent_fd)
        external_alias.unlink(missing_ok=True)


def test_postcondition_rollback_failure_is_never_reported_as_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "payload").write_bytes(b"sealed")
    staging_fd = os.open(staging, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    parent_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    seal = supervisor._seal_tree_readonly(staging, staging_fd)
    parent_info = os.fstat(parent_fd)
    key = (parent_info.st_dev, parent_info.st_ino, "staging")
    supervisor._PENDING_PUBLICATION_SEALS[key] = seal
    external_alias = tmp_path / "external-alias"
    real_verify = supervisor._verify_tree_seal
    real_rename = supervisor._rename_directory_no_replace
    verify_calls = 0

    def verify_then_inject_alias(tree_seal: supervisor._TreeSeal) -> None:
        nonlocal verify_calls
        real_verify(tree_seal)
        verify_calls += 1
        if verify_calls == 1:
            os.link(staging / "payload", external_alias)

    def refuse_rollback(parent: int, source: str, destination: str) -> str:
        if source == "final":
            raise OSError(errno.EIO, "rollback denied")
        return real_rename(parent, source, destination)

    monkeypatch.setattr(supervisor, "_verify_tree_seal", verify_then_inject_alias)
    monkeypatch.setattr(supervisor, "_rename_directory_no_replace", refuse_rollback)
    try:
        with pytest.raises(supervisor._PublicationPostconditionError) as caught:
            supervisor._publish_directory_no_replace(parent_fd, "staging", "final")
        assert caught.value.final_present and caught.value.rollback_failed
        assert (tmp_path / "final" / "payload").exists()
    finally:
        supervisor._PENDING_PUBLICATION_SEALS.pop(key, None)
        supervisor._release_tree_seal(seal, writable=True)
        os.close(staging_fd)
        os.close(parent_fd)
        external_alias.unlink(missing_ok=True)


def test_publish_time_collision_retains_staging_and_never_clobbers_racer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    template_root = tmp_path / "template-root"
    template_root.mkdir()
    template, _images, digest = _build_valid_staging(template_root)
    _install_fake_child(tmp_path, monkeypatch, _copying_child_source(template))
    run_root = tmp_path / "run"
    run_root.mkdir()
    images = _image_root(run_root / "images")
    final = run_root / "final"
    real_publish = supervisor._publish_directory_no_replace

    def collide(parent_fd: int, source_name: str, destination_name: str) -> str:
        final.mkdir()
        (final / "racer-sentinel").write_bytes(b"keep")
        return real_publish(parent_fd, source_name, destination_name)

    monkeypatch.setattr(supervisor, "_publish_directory_no_replace", collide)
    result = supervisor.supervise_arm(_supervisor_spec(run_root, final, digest, test_dir=images))
    assert result.success is False and result.staging_dir is not None
    assert (final / "racer-sentinel").read_bytes() == b"keep"
    assert result.receipt_path is not None and result.receipt_path.is_file()
    receipt = json.loads(result.receipt_path.read_bytes())
    assert receipt["failure"]["type"] == "FileExistsError"
    assert receipt["final_absent"] is False


def test_mutation_after_child_validation_is_rejected_inside_promotion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    template_root = tmp_path / "template-root"
    template_root.mkdir()
    template, _images, digest = _build_valid_staging(template_root)
    _install_fake_child(tmp_path, monkeypatch, _copying_child_source(template))
    run_root = tmp_path / "run"
    run_root.mkdir()
    images = _image_root(run_root / "images")
    final = run_root / "final"
    real_promote = supervisor._promote_partial_files

    def mutate_then_promote(
        staging: Path,
        expected_artifacts: dict[str, dict[str, object]] | None = None,
    ) -> dict[str, str]:
        with (staging / "submission.csv.partial").open("ab") as handle:
            handle.write(b"post-validation-mutation\n")
        return real_promote(staging, expected_artifacts)

    monkeypatch.setattr(supervisor, "_promote_partial_files", mutate_then_promote)
    result = supervisor.supervise_arm(_supervisor_spec(run_root, final, digest, test_dir=images))
    assert not result.success and not final.exists() and result.receipt_path is not None
    assert "immediately before promotion" in json.loads(result.receipt_path.read_bytes())["failure"]["message"]


def test_mutation_at_publication_boundary_is_rejected_by_held_fd_tree_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    template_root = tmp_path / "template-root"
    template_root.mkdir()
    template, _images, digest = _build_valid_staging(template_root)
    _install_fake_child(tmp_path, monkeypatch, _copying_child_source(template))
    run_root = tmp_path / "run"
    run_root.mkdir()
    images = _image_root(run_root / "images")
    final = run_root / "final"
    real_publish = supervisor._publish_directory_no_replace

    def mutate_then_publish(parent_fd: int, source_name: str, destination_name: str) -> str:
        victim = run_root / source_name / "submission.csv"
        os.chmod(victim, 0o600)
        with victim.open("ab") as handle:
            handle.write(b"publication-race\n")
        return real_publish(parent_fd, source_name, destination_name)

    monkeypatch.setattr(supervisor, "_publish_directory_no_replace", mutate_then_publish)
    result = supervisor.supervise_arm(_supervisor_spec(run_root, final, digest, test_dir=images))
    assert not result.success and not final.exists() and result.receipt_path is not None
    assert "changed after sealing" in json.loads(result.receipt_path.read_bytes())["failure"]["message"]


def test_supervisor_post_rename_race_rolls_back_and_records_honest_failure_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    template_root = tmp_path / "template-root"
    template_root.mkdir()
    template, _images, digest = _build_valid_staging(template_root)
    _install_fake_child(tmp_path, monkeypatch, _copying_child_source(template))
    run_root = tmp_path / "run"
    run_root.mkdir()
    images = _image_root(run_root / "images")
    final = run_root / "final"
    external_alias = run_root / "external-alias"
    real_verify = supervisor._verify_tree_seal
    verify_calls = 0

    def verify_then_race(tree_seal: supervisor._TreeSeal) -> None:
        nonlocal verify_calls
        real_verify(tree_seal)
        verify_calls += 1
        # Caller precheck is first; the pending-seal precheck immediately
        # inside publication is second.  Insert the alias in that exact gap.
        if verify_calls == 2:
            os.link(tree_seal.staging / "submission.csv", external_alias)

    monkeypatch.setattr(supervisor, "_verify_tree_seal", verify_then_race)
    result = supervisor.supervise_arm(_supervisor_spec(run_root, final, digest, test_dir=images))
    assert not result.success and not final.exists() and result.staging_dir is not None
    assert result.staging_dir.name.startswith(".final.failed.")
    assert result.receipt_path is not None and result.receipt_path.parent == result.staging_dir
    assert not (result.staging_dir / "arm_receipt.json").exists()
    receipt = json.loads(result.receipt_path.read_bytes())
    assert receipt["final_absent"] is True
    assert receipt["publication_recovery"] == {
        "rollback_attempted": True,
        "rollback_succeeded": True,
        "final_present": False,
    }
    external_alias.unlink()


def test_supervisor_records_rollback_failure_and_never_returns_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    template_root = tmp_path / "template-root"
    template_root.mkdir()
    template, _images, digest = _build_valid_staging(template_root)
    _install_fake_child(tmp_path, monkeypatch, _copying_child_source(template))
    run_root = tmp_path / "run"
    run_root.mkdir()
    images = _image_root(run_root / "images")
    final = run_root / "final"
    external_alias = run_root / "external-alias"
    real_verify = supervisor._verify_tree_seal
    real_rename = supervisor._rename_directory_no_replace
    verify_calls = 0

    def verify_then_race(tree_seal: supervisor._TreeSeal) -> None:
        nonlocal verify_calls
        real_verify(tree_seal)
        verify_calls += 1
        if verify_calls == 2:
            os.link(tree_seal.staging / "submission.csv", external_alias)

    def refuse_rollback(parent_fd: int, source_name: str, destination_name: str) -> str:
        if source_name == "final":
            raise OSError(errno.EIO, "rollback denied")
        return real_rename(parent_fd, source_name, destination_name)

    monkeypatch.setattr(supervisor, "_verify_tree_seal", verify_then_race)
    monkeypatch.setattr(supervisor, "_rename_directory_no_replace", refuse_rollback)
    result = supervisor.supervise_arm(_supervisor_spec(run_root, final, digest, test_dir=images))
    assert not result.success and final.exists() and result.staging_dir == final
    assert result.receipt_path == final / "failure_receipt.json"
    assert not (final / "arm_receipt.json").exists()
    receipt = json.loads(result.receipt_path.read_bytes())
    assert receipt["final_absent"] is False
    assert receipt["publication_recovery"] == {
        "rollback_attempted": True,
        "rollback_succeeded": False,
        "final_present": True,
    }
    external_alias.unlink()


def test_rollback_and_success_receipt_removal_failure_records_final_taint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    template_root = tmp_path / "template-root"
    template_root.mkdir()
    template, _images, digest = _build_valid_staging(template_root)
    _install_fake_child(tmp_path, monkeypatch, _copying_child_source(template))
    run_root = tmp_path / "run"
    run_root.mkdir()
    images = _image_root(run_root / "images")
    final = run_root / "final"
    external_alias = run_root / "external-alias"
    real_verify = supervisor._verify_tree_seal
    real_rename = supervisor._rename_directory_no_replace
    real_unlink = supervisor.os.unlink
    verify_calls = 0

    def verify_then_race(tree_seal: supervisor._TreeSeal) -> None:
        nonlocal verify_calls
        real_verify(tree_seal)
        verify_calls += 1
        if verify_calls == 2:
            os.link(tree_seal.staging / "submission.csv", external_alias)

    def refuse_rollback(parent_fd: int, source_name: str, destination_name: str) -> str:
        if source_name == "final":
            raise OSError(errno.EIO, "rollback denied")
        return real_rename(parent_fd, source_name, destination_name)

    def refuse_arm_receipt_unlink(path: str | bytes, *args: object, **kwargs: object) -> None:
        if path == "arm_receipt.json":
            raise OSError(errno.EIO, "success receipt removal denied")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(supervisor, "_verify_tree_seal", verify_then_race)
    monkeypatch.setattr(supervisor, "_rename_directory_no_replace", refuse_rollback)
    monkeypatch.setattr(supervisor.os, "unlink", refuse_arm_receipt_unlink)
    result = supervisor.supervise_arm(_supervisor_spec(run_root, final, digest, test_dir=images))
    assert not result.success and final.exists()
    assert (final / "arm_receipt.json").exists()
    invalid_success_receipt = json.loads((final / "arm_receipt.json").read_bytes())
    assert invalid_success_receipt["holds"] == list(supervisor._LOCAL_HOLDS)
    assert invalid_success_receipt["success_scope"] == supervisor._LOCAL_SUCCESS_SCOPE
    assert invalid_success_receipt["claims"]["success_boolean_authorizes_production"] is False
    receipt = json.loads((final / "failure_receipt.json").read_bytes())
    assert receipt["success_receipt_removal"] == {
        "attempted": True,
        "present_before": True,
        "removed": None,
        "present_after": True,
        "directory_fsync_succeeded": None,
        "tainted": True,
    }
    assert receipt["publication_recovery"]["final_present"] is True
    assert "success_receipt_removal:OSError" in receipt["failure_evidence_errors"]
    assert receipt["success_scope"] == supervisor._LOCAL_SUCCESS_SCOPE
    external_alias.unlink()


def test_publish_and_rss_refuse_unsupported_platform(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(supervisor.sys, "platform", "plan9")
    with pytest.raises(supervisor.SupervisorError, match="unknown wait4"):
        supervisor._normalized_rss(SimpleNamespace(ru_maxrss=1))
    parent_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    (tmp_path / "source").mkdir()
    try:
        with pytest.raises(supervisor.SupervisorError, match="NOREPLACE_UNSUPPORTED"):
            supervisor._publish_directory_no_replace(parent_fd, "source", "final")
    finally:
        os.close(parent_fd)


@pytest.mark.parametrize(
    ("platform", "raw", "unit", "normalized"),
    [("darwin", 4096, "bytes", 4096), ("linux", 4096, "KiB", 4096 * 1024)],
)
def test_wait4_ru_maxrss_platform_units(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    raw: int,
    unit: str,
    normalized: int,
):
    monkeypatch.setattr(supervisor.sys, "platform", platform)
    assert supervisor._normalized_rss(SimpleNamespace(ru_maxrss=raw)) == (raw, unit, normalized)


def test_pipe_and_child_fd_cleanup_contract_in_isolated_process(tmp_path: Path):
    read_fd, write_fd = supervisor._cloexec_pipe()
    try:
        assert not os.get_inheritable(read_fd)
        assert not os.get_inheritable(write_fd)
    finally:
        os.close(read_fd)
        os.close(write_fd)
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import os,resource,sys\n"
        "keep=int(sys.argv[1]);drop=int(sys.argv[2])\n"
        "limit=resource.getrlimit(resource.RLIMIT_NOFILE)[0]\n"
        "maximum=int(os.sysconf('SC_OPEN_MAX')) if limit==resource.RLIM_INFINITY else int(limit)\n"
        "os.closerange(3,keep);os.closerange(keep+1,maximum)\n"
        "os.fstat(keep)\n"
        "try: os.fstat(drop)\n"
        "except OSError: raise SystemExit(0)\n"
        "raise SystemExit(9)\n"
    )
    first_r, first_w = os.pipe()
    second_r, second_w = os.pipe()
    try:
        completed = subprocess.run(
            [sys.executable, str(probe), str(first_w), str(second_w)],
            env={"LC_ALL": "C", "LANG": "C"},
            pass_fds=(first_w, second_w),
            check=False,
        )
    finally:
        for fd in (first_r, first_w, second_r, second_w):
            os.close(fd)
    assert completed.returncode == 0


def test_safe_spawn_child_cannot_observe_unrelated_inheritable_parent_fd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    leaked_read, leaked_write = os.pipe()
    os.set_inheritable(leaked_write, True)
    body = f"""
import os
try:
    os.fstat({leaked_write})
except OSError:
    raise SystemExit(3)
raise SystemExit(9)
"""
    _install_fake_child(tmp_path, monkeypatch, body)
    final = tmp_path / "parent" / "final"
    final.parent.mkdir()
    try:
        result = supervisor.supervise_arm(_supervisor_spec(tmp_path, final, "0" * 64))
    finally:
        os.close(leaked_read)
        os.close(leaked_write)
    assert result.success is False
    # Exit 3 proves the inherited descriptor number was closed before exec;
    # exit 9 would mean the unrelated parent descriptor leaked into the child.
    assert result.exit_code == 3


@pytest.mark.parametrize("operation", ["write", "fsync"])
def test_drain_reports_output_write_and_fsync_errors(monkeypatch: pytest.MonkeyPatch, operation: str):
    read_fd, write_fd = os.pipe()
    output_fd = os.open(os.devnull, os.O_WRONLY)
    os.write(write_fd, b"payload")
    os.close(write_fd)
    errors: list[BaseException] = []
    real_write = supervisor.os.write

    real_fsync = supervisor.os.fsync

    def failed_write(fd: int, data: bytes | memoryview) -> int:
        if operation == "write" and fd == output_fd:
            raise OSError(errno.ENOSPC, "full")
        return real_write(fd, data)

    def failed_fsync(fd: int) -> None:
        if operation == "fsync" and fd == output_fd:
            raise OSError(errno.EIO, "fsync")
        real_fsync(fd)

    monkeypatch.setattr(supervisor.os, "write", failed_write)
    monkeypatch.setattr(supervisor.os, "fsync", failed_fsync)
    supervisor._drain_pipe(read_fd, output_fd, bytearray(), threading.Event(), errors)
    assert len(errors) == 1 and isinstance(errors[0], OSError)


@pytest.mark.parametrize(("payload_size", "fails"), [(1024, False), (1025, True)])
def test_log_drain_enforces_exact_byte_limit(tmp_path: Path, payload_size: int, fails: bool):
    read_fd, write_fd = os.pipe()
    output = tmp_path / "captured.log"
    output_fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    errors: list[BaseException] = []

    def write_payload() -> None:
        try:
            os.write(write_fd, b"x" * payload_size)
        finally:
            os.close(write_fd)

    writer = threading.Thread(target=write_payload)
    writer.start()
    supervisor._drain_pipe(
        read_fd,
        output_fd,
        bytearray(),
        threading.Event(),
        errors,
        1024,
    )
    writer.join(timeout=1)
    assert not writer.is_alive()
    assert bool(errors) is fails
    if fails:
        assert isinstance(errors[0], supervisor.SupervisorError)
        assert output.stat().st_size == 0
    else:
        assert output.read_bytes() == b"x" * 1024


def test_log_drain_accepts_literal_one_mib_boundary(tmp_path: Path):
    read_fd, write_fd = os.pipe()
    output = tmp_path / "captured.log"
    output_fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    errors: list[BaseException] = []

    def write_payload() -> None:
        view = memoryview(b"x" * supervisor._MAX_SUPERVISOR_LOG_BYTES)
        try:
            while view:
                written = os.write(write_fd, view)
                view = view[written:]
        finally:
            os.close(write_fd)

    writer = threading.Thread(target=write_payload)
    writer.start()
    supervisor._drain_pipe(
        read_fd,
        output_fd,
        bytearray(),
        threading.Event(),
        errors,
        supervisor._MAX_SUPERVISOR_LOG_BYTES,
    )
    writer.join(timeout=2)
    assert not writer.is_alive() and not errors
    assert output.stat().st_size == supervisor._MAX_SUPERVISOR_LOG_BYTES


def test_event_drain_is_bounded_at_one_mib():
    read_fd, write_fd = os.pipe()
    sink = bytearray()
    errors: list[BaseException] = []

    def write_payload() -> None:
        view = memoryview(b"x" * (supervisor._MAX_SUPERVISOR_LOG_BYTES + 1))
        try:
            while view:
                try:
                    written = os.write(write_fd, view)
                except BrokenPipeError:
                    break
                view = view[written:]
        finally:
            os.close(write_fd)

    writer = threading.Thread(target=write_payload)
    writer.start()
    supervisor._drain_pipe(read_fd, None, sink, threading.Event(), errors)
    writer.join(timeout=2)
    assert not writer.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], supervisor.SupervisorError)
    assert "bounded receipt size" in str(errors[0])
    assert len(sink) <= supervisor._MAX_SUPERVISOR_LOG_BYTES + 65536


def test_supervisor_kills_child_and_redacts_logs_on_log_byte_overflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    body = """
import os,time
payload=b'x'*65536
while True:
    try: os.write(1,payload)
    except BrokenPipeError: time.sleep(10)
"""
    _install_fake_child(tmp_path, monkeypatch, body)
    final = tmp_path / "run" / "final"
    final.parent.mkdir()
    result = supervisor.supervise_arm(_supervisor_spec(tmp_path, final, "0" * 64, timeout_seconds=5.0))
    assert not result.success and not final.exists() and result.staging_dir is not None
    assert result.term_signal == signal.SIGKILL
    assert result.receipt_path is not None
    receipt = json.loads(result.receipt_path.read_bytes())
    assert receipt["failure"]["message"] == "concurrent pipe drain failed"
    for name in supervisor._SUPERVISOR_LOGS:
        assert (result.staging_dir / name).read_bytes() == supervisor._SAFE_REDACTED_LOG


@pytest.mark.parametrize(
    "payload",
    [
        b"token=TOPSECRET\n",
        b"password: hunter2\n",
        b"Secret = value\n",
        b"API-Key: value\n",
        b"Auth=value\n",
        b"Authorization: Bearer abc123\n",
        b"Cookie: session=value\n",
        b"/private/secret/model.pt\n",
        b"/gt/44b6_12dfb391.geff\n",
        b"dead_beefdead.geff\n",
        b"dataset=unexpected\n",
        b"metric=NaN\n",
        b"metric=+Inf\n",
        b"metric=-Infinity\n",
        b"bad=\xff\n",
    ],
)
def test_safe_text_scanner_rejects_credentials_paths_nonfinite_stems_and_non_utf8(payload: bytes):
    with pytest.raises(supervisor.SupervisorError, match="safe-text policy"):
        supervisor._validate_safe_text_bytes(payload)


def test_safe_text_scanner_accepts_only_registered_dataset_diagnostics():
    payload = (f"child completed\n{supervisor.EVAL36[0]}\nartifact={supervisor.EVAL36[-1]}.geff\n").encode()
    assert supervisor._validate_safe_text_bytes(payload) == payload.decode()


@pytest.mark.parametrize(
    ("payload", "marker"),
    [
        (b"token=TOPSECRET\n", b"TOPSECRET"),
        (b"Authorization: Bearer abc123\n", b"abc123"),
        (b"/private/secret/model.pt\n", b"/private/secret"),
        (b"/gt/44b6_12dfb391.geff\n", b"/gt/"),
        (b"dead_beefdead.geff\n", b"dead_beefdead"),
        (b"bad=\xff\n", b"\xff"),
        (b"metric=NaN\n", b"NaN"),
        (b"metric=-Inf\n", b"-Inf"),
    ],
)
def test_unsafe_child_text_is_never_published_or_copied_into_failure_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    marker: bytes,
):
    template_root = tmp_path / "template-root"
    template_root.mkdir()
    template, _images, digest = _build_valid_staging(template_root)
    body = _copying_child_source(template).replace(
        "os.write(1,b'child stdout\\n')",
        f"os.write(1,{payload!r})",
    )
    _install_fake_child(tmp_path, monkeypatch, body)
    run_root = tmp_path / "run"
    run_root.mkdir()
    final = run_root / "final"
    result = supervisor.supervise_arm(
        _supervisor_spec(run_root, final, digest, test_dir=_image_root(run_root / "images"))
    )
    assert not result.success and not final.exists() and result.staging_dir is not None
    assert result.receipt_path is not None
    receipt_bytes = result.receipt_path.read_bytes()
    assert marker not in receipt_bytes
    supervisor._validate_safe_text_bytes(receipt_bytes)
    for name in supervisor._SUPERVISOR_LOGS:
        assert (result.staging_dir / name).read_bytes() == supervisor._SAFE_REDACTED_LOG
        assert marker not in (result.staging_dir / name).read_bytes()


def test_twin_plan_debug_text_is_scanned_before_nested_semantic_acceptance(tmp_path: Path):
    staging, images, digest = _build_valid_staging(tmp_path, "candidate")
    plan = _nonempty_active_plan(supervisor.EVAL36[0])
    plan["debug_records"][0]["reason"] = "token=TOPSECRET"
    _replace_first_plan_and_rebind(staging, plan, sync_stats=True)
    with pytest.raises(supervisor.SupervisorError, match="safe-text policy"):
        supervisor._validate_child_staging(staging, "candidate", images, digest)


def test_reserved_supervisor_log_spoof_is_rejected(tmp_path: Path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / supervisor._SUPERVISOR_LOGS[0]).write_bytes(b"spoof")
    temporary = ("stdout.tmp", "stderr.tmp")
    for name in temporary:
        (tmp_path / name).write_bytes(b"real")
    parent_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    staging_fd = os.open(staging, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        with pytest.raises(supervisor.SupervisorError, match="reserved"):
            supervisor._attach_supervisor_logs(parent_fd, staging_fd, temporary)
    finally:
        os.close(staging_fd)
        os.close(parent_fd)
    assert (staging / supervisor._SUPERVISOR_LOGS[0]).read_bytes() == b"spoof"


def test_successful_safe_spawn_exec_publish_receipt_has_explicit_holds_and_no_overclaim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    template_root = tmp_path / "template-root"
    template_root.mkdir()
    template, _images, digest = _build_valid_staging(template_root)
    _install_fake_child(tmp_path, monkeypatch, _copying_child_source(template))
    run_root = tmp_path / "run"
    run_root.mkdir()
    images = _image_root(run_root / "images")
    final = run_root / "final"
    spec = _supervisor_spec(run_root, final, digest, test_dir=images)
    result = supervisor.supervise_arm(spec)
    assert result.success is True
    assert result.staging_dir is None and result.final_dir == final
    receipt = json.loads((final / "arm_receipt.json").read_bytes())
    assert receipt["status"] == "LOCAL_VALIDATION_OBSERVED_WITH_HOLDS"
    assert receipt["events"] == {"exact_pipe_bytes": True, "records": 72, "relative_path": "dataset_events.jsonl"}
    assert receipt["child"]["pid"] == result.child_pid
    assert (final / "supervisor_stdout.log.partial").read_bytes() == b"child stdout\n"
    assert (final / "supervisor_stderr.log.partial").read_bytes() == b"child stderr\n"
    for path in final.rglob("*"):
        info = path.lstat()
        if stat.S_ISREG(info.st_mode):
            assert info.st_nlink == 1
            assert stat.S_IMODE(info.st_mode) == 0o400
        else:
            assert stat.S_ISDIR(info.st_mode)
            assert stat.S_IMODE(info.st_mode) == 0o500
    assert stat.S_IMODE(final.stat().st_mode) == 0o500
    assert set(receipt["holds"]) == set(supervisor._LOCAL_HOLDS)
    assert "HOLD_PUBLICATION_CONCURRENCY_UNPROVEN" in receipt["holds"]
    assert result.success_scope == supervisor._LOCAL_SUCCESS_SCOPE
    assert result.failure_evidence_state == supervisor._SUCCESS_EVIDENCE_STATE
    assert receipt["success_scope"] == supervisor._LOCAL_SUCCESS_SCOPE
    assert receipt["child"]["spawn_method"].startswith("subprocess.Popen")
    assert receipt["wait4"]["authoritative_for_rss_gate"] is False
    assert receipt["claims"] == {
        "local_child_interface_validated_at_publication_check": True,
        "publication_concurrency_exclusion_proven": False,
        "success_boolean_authorizes_production": False,
        "gt_nonvisibility_proven": False,
        "no_descendants_proven": False,
        "target_runtime_calibrated": False,
        "target_memory_calibrated": False,
        "data_ready": False,
        "scoring_performed": False,
    }


@pytest.mark.parametrize(
    ("body", "timeout", "failure_type", "exit_code", "term_signal"),
    [
        ("import sys;sys.exit(7)\n", 5.0, "SupervisorError", 7, None),
        ("import os,signal;os.kill(os.getpid(),signal.SIGTERM)\n", 5.0, "SupervisorError", None, signal.SIGTERM),
        ("import time;time.sleep(5)\n", 0.05, "TimeoutError", None, signal.SIGKILL),
    ],
)
def test_nonzero_signal_and_timeout_preserve_failure_staging_without_final(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: str,
    timeout: float,
    failure_type: str,
    exit_code: int | None,
    term_signal: int | None,
):
    _install_fake_child(tmp_path, monkeypatch, body)
    final = tmp_path / "run" / "final"
    final.parent.mkdir()
    spec = _supervisor_spec(tmp_path, final, "0" * 64, timeout_seconds=timeout)
    result = supervisor.supervise_arm(spec)
    assert result.success is False and result.staging_dir is not None
    assert not final.exists()
    receipt = json.loads(result.receipt_path.read_bytes())
    assert receipt["failure"]["type"] == failure_type
    assert receipt["exit_code"] == exit_code
    assert receipt["term_signal"] == term_signal
    assert receipt["final_absent"] is True
    assert receipt["holds"] == list(supervisor._LOCAL_HOLDS)


@pytest.mark.parametrize("event_mode", ["missing", "partial", "extra"])
def test_missing_partial_and_extra_event_streams_fail_before_artifact_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, event_mode: str
):
    complete = _events(pid=0)
    if event_mode == "missing":
        payload = b""
    elif event_mode == "partial":
        payload = complete[:20]
    else:
        payload = complete + b"{}\n"
    body = f"""
import argparse,os
p=argparse.ArgumentParser(add_help=False);p.add_argument('--event-fd',type=int)
a,_=p.parse_known_args();payload={payload!r};os.write(a.event_fd,payload)
"""
    _install_fake_child(tmp_path, monkeypatch, body)
    final = tmp_path / "run" / "final"
    final.parent.mkdir()
    result = supervisor.supervise_arm(_supervisor_spec(tmp_path, final, "0" * 64))
    assert result.success is False and not final.exists()
    failure = json.loads(result.receipt_path.read_bytes())
    assert "event pipe" in failure["failure"]["message"]


def test_preexisting_final_and_symlink_parent_fail_closed_without_clobber(tmp_path: Path):
    final = tmp_path / "parent" / "final"
    final.mkdir(parents=True)
    (final / "sentinel").write_bytes(b"keep")
    result = supervisor.supervise_arm(_supervisor_spec(tmp_path, final, "0" * 64))
    assert result.success is False
    assert (final / "sentinel").read_bytes() == b"keep"
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(ValueError, match="nonsymlink"):
        supervisor.supervise_arm(_supervisor_spec(tmp_path, linked_parent / "final", "0" * 64))
    assert not (real_parent / "final").exists()


def test_same_filesystem_identity_mismatch_fails_before_spawn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    final = tmp_path / "parent" / "final"
    final.parent.mkdir()
    real_fstat = supervisor.os.fstat
    directory_calls = 0

    def mismatched_fstat(fd: int):
        nonlocal directory_calls
        result = real_fstat(fd)
        if stat.S_ISDIR(result.st_mode):
            directory_calls += 1
            if directory_calls == 2:
                values = list(result)
                values[2] += 1
                return os.stat_result(values)
        return result

    monkeypatch.setattr(supervisor.os, "fstat", mismatched_fstat)
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("spawn after mismatch"))
    result = supervisor.supervise_arm(_supervisor_spec(tmp_path, final, "0" * 64))
    assert result.success is False and not final.exists()
    assert "same filesystem" in json.loads(result.receipt_path.read_bytes())["failure"]["message"]


def test_final_parent_identity_change_after_sealing_prevents_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    template_root = tmp_path / "template-root"
    template_root.mkdir()
    template, _images, digest = _build_valid_staging(template_root)
    _install_fake_child(tmp_path, monkeypatch, _copying_child_source(template))
    run_root = tmp_path / "run"
    run_root.mkdir()
    images = _image_root(run_root / "images")
    final = run_root / "final"
    real_stat = Path.stat

    def changed_parent_stat(path: Path, *args: object, **kwargs: object):
        result = real_stat(path, *args, **kwargs)
        sealed = path == run_root and any(
            entry.name.startswith(".final.staging.") and os.path.exists(os.fspath(entry / "arm_receipt.json"))
            for entry in run_root.iterdir()
        )
        if sealed:
            values = list(result)
            values[1] += 1
            return os.stat_result(values)
        return result

    monkeypatch.setattr(Path, "stat", changed_parent_stat)
    result = supervisor.supervise_arm(_supervisor_spec(run_root, final, digest, test_dir=images))
    assert result.success is False and not final.exists()
    assert result.receipt_path is not None
    failure = json.loads(result.receipt_path.read_bytes())
    assert "parent identity changed" in failure["failure"]["message"]


def test_supervisor_surface_has_no_gt_evaluator_or_free_child_cli_controls():
    expected_fields = (
        "arm_name",
        "geff_dir",
        "test_dir",
        "deepcenter_checkpoint",
        "deepcenter_manifest",
        "expected_effective_config_sha256",
        "final_dir",
        "timeout_seconds",
    )
    assert tuple(field.name for field in fields(supervisor.SupervisorSpec)) == expected_fields
    source_paths = (SUPERVISOR_SOURCE, SUPERVISOR_CLI)
    for path in source_paths:
        source = path.read_text()
        imported = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        assert not any("evaluate" in name or "tracking_cellmot" in name for name in imported)
        lowered = source.lower()
        assert "--gt" not in lowered and "--evaluator" not in lowered and "--score" not in lowered
    cli = SUPERVISOR_CLI.read_text()
    for forbidden in ("--child", "--dataset", "--profile", "--set", "--event", "--output"):
        assert forbidden not in cli


def test_expected_config_sha_is_exact_lowercase_32_byte_hex(tmp_path: Path):
    final = tmp_path / "parent" / "final"
    final.parent.mkdir()
    malformed = "0" * 62 + "  "  # bytes.fromhex ignores ASCII whitespace unless length is also checked.
    with pytest.raises(ValueError, match="SHA-256"):
        supervisor._validate_spec(_supervisor_spec(tmp_path, final, malformed))


def test_supervisor_cli_help_exposes_only_the_frozen_controls(tmp_path: Path):
    completed = subprocess.run(
        [sys.executable, str(SUPERVISOR_CLI), "--help"],
        cwd=tmp_path,
        env={"PYTHONHASHSEED": "0", "LC_ALL": "C", "LANG": "C", "TZ": "UTC"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    option_lines = {token for token in completed.stdout.split() if token.startswith("--")}
    assert option_lines == {
        "--help",
        "--arm-name",
        "--geff-dir",
        "--test-dir",
        "--deepcenter-checkpoint",
        "--deepcenter-manifest",
        "--expected-effective-config-sha256",
        "--final-dir",
        "--timeout-seconds",
    }


def test_failure_receipt_inventory_is_canonical_and_preserves_partial_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    body = "import os;os.write(1,b'out-before-failure\\n');os.write(2,b'err-before-failure\\n');raise SystemExit(4)\n"
    _install_fake_child(tmp_path, monkeypatch, body)
    final = tmp_path / "parent" / "final"
    final.parent.mkdir()
    result = supervisor.supervise_arm(_supervisor_spec(tmp_path, final, "0" * 64))
    assert not result.success and result.staging_dir is not None and not final.exists()
    assert result.receipt_path is not None
    raw = result.receipt_path.read_bytes()
    receipt = json.loads(raw)
    assert raw == _canonical(receipt)
    assert (result.staging_dir / "supervisor_stdout.log.partial").read_bytes() == b"out-before-failure\n"
    assert (result.staging_dir / "supervisor_stderr.log.partial").read_bytes() == b"err-before-failure\n"
    inventory_paths = {item["relative_path"] for item in receipt["partial_inventory"]}
    assert {"supervisor_stdout.log.partial", "supervisor_stderr.log.partial"} <= inventory_paths
    assert receipt["final_absent"] is True


@pytest.mark.parametrize("operation", ["sanitize", "inventory", "log"])
def test_failure_evidence_cleanup_oserror_never_escapes_or_replaces_original_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
):
    _install_fake_child(tmp_path, monkeypatch, "raise SystemExit(7)\n")
    final = tmp_path / "parent" / "final"
    final.parent.mkdir()
    if operation == "sanitize":
        monkeypatch.setattr(
            supervisor,
            "_sanitize_failed_text_artifacts",
            lambda _path: (_ for _ in ()).throw(OSError(errno.EIO, "cleanup failed")),
        )
    elif operation == "inventory":
        monkeypatch.setattr(
            supervisor,
            "_partial_inventory",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError(errno.EIO, "inventory failed")),
        )
    else:
        monkeypatch.setattr(
            supervisor,
            "_attach_supervisor_logs",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError(errno.EIO, "log attachment failed")),
        )
    result = supervisor.supervise_arm(_supervisor_spec(tmp_path, final, "0" * 64))
    assert not result.success and result.receipt_path is not None
    assert result.failure_type == "SupervisorError"
    assert result.failure_message == "authoritative child failed: exit=7, signal=None"
    receipt = json.loads(result.receipt_path.read_bytes())
    assert receipt["failure"] == {
        "type": "SupervisorError",
        "message": "authoritative child failed: exit=7, signal=None",
    }
    assert any(item.endswith(":OSError") for item in receipt["failure_evidence_errors"])
    if operation == "inventory":
        assert receipt["partial_inventory_complete"] is False


@pytest.mark.parametrize("fail_fallback", [False, True])
def test_failure_receipt_primary_write_failure_has_explicit_fallback_or_unwritable_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_fallback: bool
):
    _install_fake_child(tmp_path, monkeypatch, "raise SystemExit(7)\n")
    final = tmp_path / "parent" / "final"
    final.parent.mkdir()
    real_write = supervisor._write_new_file

    def fail_receipt_write(path: Path, data: bytes) -> None:
        if path.name == "failure_receipt.json" or (fail_fallback and path.name.startswith("failure_receipt.fallback.")):
            raise OSError(errno.EIO, "receipt write failed")
        real_write(path, data)

    monkeypatch.setattr(supervisor, "_write_new_file", fail_receipt_write)
    result = supervisor.supervise_arm(_supervisor_spec(tmp_path, final, "0" * 64))
    assert not result.success
    if fail_fallback:
        assert result.receipt_path is None
        assert result.failure_evidence_state == supervisor._FAILURE_EVIDENCE_UNWRITABLE
        assert result.failure_type == "SupervisorError"
        assert result.failure_message == "authoritative child failed: exit=7, signal=None"
        assert "failure_receipt_fallback:OSError" in result.failure_evidence_errors
    else:
        assert result.receipt_path is not None
        assert result.receipt_path.name.startswith("failure_receipt.fallback.")
        assert result.failure_evidence_state == supervisor._FAILURE_EVIDENCE_FALLBACK
        receipt = json.loads(result.receipt_path.read_bytes())
        assert receipt["failure"] == {
            "type": "SupervisorError",
            "message": "authoritative child failed: exit=7, signal=None",
        }


def test_background_thread_spawn_is_warning_free_and_retains_all_holds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    template_root = tmp_path / "template-root"
    template_root.mkdir()
    template, _images, digest = _build_valid_staging(template_root)
    _install_fake_child(tmp_path, monkeypatch, _copying_child_source(template))
    run_root = tmp_path / "run"
    run_root.mkdir()
    images = _image_root(run_root / "images")
    ready = threading.Event()
    stop = threading.Event()
    background = threading.Thread(target=lambda: (ready.set(), stop.wait()))
    background.start()
    ready.wait()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            result = supervisor.supervise_arm(_supervisor_spec(run_root, run_root / "final", digest, test_dir=images))
    finally:
        stop.set()
        background.join(timeout=1)
    assert result.success
    assert result.holds == supervisor._LOCAL_HOLDS
    assert not background.is_alive()


def test_detached_descendant_can_outlive_local_success_but_cannot_clear_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    template_root = tmp_path / "template-root"
    template_root.mkdir()
    template, _images, digest = _build_valid_staging(template_root)
    descendant_pid_path = tmp_path / "descendant.pid"
    body = (
        _copying_child_source(template)
        + f"""
pid=os.fork()
if pid==0:
    os.setsid()
    time.sleep(30)
    os._exit(0)
Path({str(descendant_pid_path)!r}).write_text(str(pid))
"""
    )
    _install_fake_child(tmp_path, monkeypatch, body)
    run_root = tmp_path / "run"
    run_root.mkdir()
    images = _image_root(run_root / "images")
    descendant_pid: int | None = None
    try:
        result = supervisor.supervise_arm(_supervisor_spec(run_root, run_root / "final", digest, test_dir=images))
        descendant_pid = int(descendant_pid_path.read_text())
        os.kill(descendant_pid, 0)
        receipt = json.loads(result.receipt_path.read_bytes())
        assert result.success
        assert receipt["claims"]["no_descendants_proven"] is False
        assert receipt["wait4"]["authoritative_for_rss_gate"] is False
        assert "HOLD_PROCESS_TREE_UNPROVEN" in receipt["holds"]
        assert "HOLD_RSS_UNMEASURABLE" in receipt["holds"]
    finally:
        if descendant_pid is not None:
            try:
                os.kill(descendant_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
