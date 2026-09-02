"""Adversarial contract tests for the ST-R3 production-runner boundary.

The focused tests in this module intentionally distinguish direct unit fault
injection from the fresh-process CLI proof.  Production is never replaced by
a fake adapter; monkeypatching is confined to OS failures and expensive model
loading that cannot be represented by the tiny fixture.
"""
from __future__ import annotations

import ast
import csv
import errno
import hashlib
import inspect
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import threading
from dataclasses import fields, replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from biohub.public_postproc import deepcenter as deepcenter_module
from biohub.public_postproc import divisions as divisions_module
from biohub.public_postproc import pipeline as pipeline_module
from biohub.public_postproc.config import PostprocConfig, build_config

EVAL12 = (
    "44b6_12dfb391",
    "44b6_267148e4",
    "44b6_2a2eff9f",
    "44b6_341df25f",
    "44b6_587a1e22",
    "44b6_5f15d135",
    "6bba_062c8d37",
    "6bba_07e24132",
    "6bba_085bf656",
    "6bba_09961292",
    "6bba_0e7c0d07",
    "6bba_12665c0e",
)
EVAL24 = (
    "44b6_706092f0",
    "44b6_74d0c52e",
    "44b6_7a302da0",
    "44b6_996155de",
    "44b6_9be80b04",
    "44b6_a21120c2",
    "44b6_aaf8b0ea",
    "44b6_c50204e0",
    "44b6_c8e2a523",
    "44b6_d2f34f90",
    "44b6_d5e7d891",
    "44b6_d754aa59",
    "6bba_1d0d8384",
    "6bba_207c6aaf",
    "6bba_20852818",
    "6bba_2312ac41",
    "6bba_268e1230",
    "6bba_2819ca14",
    "6bba_32db13fc",
    "6bba_337b1b3a",
    "6bba_3abfe10a",
    "6bba_3c5691b6",
    "6bba_3db54e20",
    "6bba_3fda6b25",
)
EVAL36 = EVAL12 + EVAL24

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "st_r3_postproc_arm.py"
ADAPTER = ROOT / "src" / "biohub" / "public_postproc" / "production_adapter.py"


def _adapter():
    from biohub.public_postproc import production_adapter

    return production_adapter


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        + b"\n"
    )


def test_frozen_dataset_literal_is_not_lexical_order_and_matches_adapter():
    adapter = _adapter()
    assert len(EVAL36) == 36
    assert len(set(EVAL36)) == 36
    assert set(EVAL12).isdisjoint(EVAL24)
    assert sum(stem.startswith("44b6_") for stem in EVAL36) == 18
    assert sum(stem.startswith("6bba_") for stem in EVAL36) == 18
    assert EVAL36 != tuple(sorted(EVAL36))
    assert tuple(adapter.EVAL12) == EVAL12
    assert tuple(adapter.EVAL24) == EVAL24
    assert tuple(adapter.EVAL36) == EVAL36


def test_production_surface_is_frozen_typed_and_has_no_gt_or_free_profile():
    adapter = _adapter()
    arm_fields = tuple(field.name for field in fields(adapter.ArmSpec))
    child_fields = tuple(field.name for field in fields(adapter.ChildResult))
    forbidden = {"gt", "gt_dir", "ground_truth", "profile", "overrides", "set", "event_path"}
    assert arm_fields == (
        "arm_name",
        "geff_dir",
        "test_dir",
        "deepcenter_checkpoint",
        "deepcenter_manifest",
        "datasets",
        "expected_effective_config_sha256",
        "staging_dir",
        "event_fd",
    )
    assert child_fields == (
        "arm_name",
        "datasets",
        "total_nodes",
        "total_edges",
        "total_rows",
        "artifacts",
    )
    assert forbidden.isdisjoint(arm_fields)
    assert forbidden.isdisjoint(child_fields)
    assert adapter.ArmSpec.__dataclass_params__.frozen is True
    assert adapter.ChildResult.__dataclass_params__.frozen is True
    assert str(inspect.signature(adapter.run_production_arm)) == "(spec: 'ArmSpec') -> 'ChildResult'"

    cli_text = CLI.read_text()
    assert "--profile" not in cli_text
    assert "--set" not in cli_text
    assert "event-path" not in cli_text
    assert "ground-truth" not in cli_text.lower()
    assert "gt-dir" not in cli_text.lower()


def test_generation_sources_do_not_import_evaluator_gt_or_relinefit_paths():
    for source_path in (ADAPTER, CLI):
        tree = ast.parse(source_path.read_text(), filename=str(source_path))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        assert not any(name == "biohub.evaluate" or name.startswith("tracking_cellmot") for name in imported)
        lowered = source_path.read_text().lower()
        assert "run_relinefit" not in lowered
        assert "save_prelinefit_checkpoint" not in lowered


def test_config_declared_field_count_remains_exactly_101(tmp_path: Path):
    config = build_config(test_dir=tmp_path, profile="e23")
    assert len(fields(PostprocConfig)) == 101
    assert len(fields(config)) == 101


def _spec(tmp_path: Path, arm_name: str = "baseline", **changes: object):
    adapter = _adapter()
    values: dict[str, object] = {
        "arm_name": arm_name,
        "geff_dir": tmp_path / "raw",
        "test_dir": tmp_path / "images",
        "deepcenter_checkpoint": tmp_path / "registered.pt",
        "deepcenter_manifest": tmp_path / "ARTIFACT_MANIFEST.json",
        "datasets": EVAL36,
        "expected_effective_config_sha256": "0" * 64,
        "staging_dir": tmp_path / "staging",
        "event_fd": 1,
    }
    values.update(changes)
    return adapter.ArmSpec(**values)


@pytest.mark.parametrize(
    ("arm_name", "expected_master", "expected_dry", "expected_tag"),
    [
        ("baseline", False, False, "e23_pub923_parity"),
        ("dry_run", True, True, "e23_twin_only_v1"),
        ("candidate", True, False, "e23_twin_only_v1"),
    ],
)
def test_exact_arm_mapping_has_no_free_profile_or_override(
    tmp_path: Path,
    arm_name: str,
    expected_master: bool,
    expected_dry: bool,
    expected_tag: str,
):
    adapter = _adapter()
    spec = _spec(tmp_path, arm_name)
    cfg = adapter._build_arm_config(spec)
    assert cfg.OUTPUT_STEAL_TWIN_REWIRE is expected_master
    assert cfg.STEAL_TWIN_DRY_RUN is expected_dry
    assert cfg.EXPERIMENT_TAG == expected_tag
    assert cfg.DEEPCENTER_CHECKPOINT == str(spec.deepcenter_checkpoint)
    assert cfg.DEEPCENTER_CHECKPOINT_DEFAULT == str(spec.deepcenter_checkpoint)
    assert cfg.DEEPCENTER_MANIFEST == str(spec.deepcenter_manifest)
    assert cfg.DEEPCENTER_MANIFEST_DEFAULT == str(spec.deepcenter_manifest)
    with pytest.raises(ValueError, match="arm_name"):
        adapter._build_arm_config(replace(spec, arm_name="e23"))


def test_effective_config_all_fields_round_trip_with_tagged_path_and_signed_zero(tmp_path: Path):
    adapter = _adapter()
    cfg = replace(
        adapter._build_arm_config(_spec(tmp_path, "baseline")),
        OUTPUT_EDGE_MAX_UM=-0.0,
    )
    encoded = adapter._canonical_effective_config(cfg)
    decoded = adapter._parse_canonical_effective_config(encoded)
    plain = json.loads(encoded)
    assert encoded.endswith(b"\n") and not encoded.endswith(b"\n\n")
    assert plain["schema_version"] == "biohub.st_r3.effective_config.v1"
    assert plain["fields"]["TEST_DIR"] == {"__type__": "path", "value": str(cfg.TEST_DIR)}
    assert plain["fields"]["OUTPUT_EDGE_MAX_UM"] == {
        "__type__": "float64",
        "bits_hex": struct.pack(">d", -0.0).hex(),
    }
    assert type(decoded["TEST_DIR"]) is type(Path())
    assert struct.pack(">d", decoded["OUTPUT_EDGE_MAX_UM"]) == struct.pack(">d", -0.0)
    assert len(decoded) == 101
    digest = hashlib.sha256(encoded).hexdigest()
    assert adapter._validate_effective_config(cfg, digest) == encoded
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        adapter._validate_effective_config(cfg, "0" * 64)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_effective_config_rejects_every_nonfinite_float(tmp_path: Path, bad: float):
    adapter = _adapter()
    cfg = replace(adapter._build_arm_config(_spec(tmp_path)), OUTPUT_EDGE_MAX_UM=bad)
    with pytest.raises(ValueError, match="must be finite"):
        adapter._canonical_effective_config(cfg)


@pytest.mark.parametrize(
    ("field_name", "bad_value", "message"),
    [
        ("OUTPUT_ENFORCE_NEXT_FRAME", 1, "exact built-in bool"),
        ("MOTION_RELINK_MAX_FRAME_NODES", True, "exact built-in int"),
        ("OUTPUT_EDGE_MAX_UM", 7, "exact built-in float"),
        ("STEAL_TWIN_MODE", 1, "exact built-in str"),
    ],
)
def test_effective_config_rejects_cross_typed_values(
    tmp_path: Path,
    field_name: str,
    bad_value: object,
    message: str,
):
    adapter = _adapter()
    cfg = adapter._build_arm_config(_spec(tmp_path))
    with pytest.raises(TypeError, match=message):
        adapter._canonical_effective_config(replace(cfg, **{field_name: bad_value}))


def test_effective_config_rejects_scalar_and_path_subclasses(tmp_path: Path):
    adapter = _adapter()

    class FloatSubclass(float):
        pass

    class StringSubclass(str):
        pass

    class PathSubclass(type(Path())):
        pass

    cfg = adapter._build_arm_config(_spec(tmp_path))
    for field_name, bad_value in (
        ("OUTPUT_EDGE_MAX_UM", FloatSubclass(7.0)),
        ("STEAL_TWIN_MODE", StringSubclass("off")),
        ("TEST_DIR", PathSubclass(tmp_path)),
    ):
        with pytest.raises(TypeError):
            adapter._canonical_effective_config(replace(cfg, **{field_name: bad_value}))


def test_dataset_event_is_one_canonical_atomic_pipe_write(monkeypatch):
    adapter = _adapter()
    read_fd, write_fd = os.pipe()
    calls: list[bytes] = []
    real_write = os.write

    def one_write(fd: int, data: bytes) -> int:
        calls.append(data)
        return real_write(fd, data)

    monkeypatch.setattr(adapter.os, "write", one_write)
    try:
        encoded = adapter._write_dataset_event(write_fd, "candidate", EVAL36[0], 0, "START")
        received = os.read(read_fd, 4096)
        pipe_buf = os.fpathconf(write_fd, "PC_PIPE_BUF")
    finally:
        os.close(read_fd)
        os.close(write_fd)
    assert calls == [encoded]
    assert received == encoded
    assert len(encoded) < pipe_buf
    assert encoded == _canonical_json(json.loads(encoded))
    event = json.loads(encoded)
    assert event == {
        "schema_version": "biohub.st_r3.dataset_event.v1",
        "pid": os.getpid(),
        "sequence": 0,
        "arm_name": "candidate",
        "dataset": EVAL36[0],
        "kind": "START",
        "monotonic_ns": event["monotonic_ns"],
    }
    assert type(event["monotonic_ns"]) is int


@pytest.mark.parametrize("failure", ["eintr", "epipe", "partial", "oversize"])
def test_dataset_event_write_failures_are_fatal_without_retry(monkeypatch, failure: str):
    adapter = _adapter()
    calls = 0

    def failed_write(_fd: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        if failure == "eintr":
            raise InterruptedError(errno.EINTR, "injected")
        if failure == "epipe":
            raise BrokenPipeError(errno.EPIPE, "injected")
        return len(data) - 1

    monkeypatch.setattr(adapter.os, "write", failed_write)
    if failure == "oversize":
        monkeypatch.setattr(adapter.os, "fpathconf", lambda _fd, _name: 1)
        with pytest.raises(ValueError, match="PIPE_BUF"):
            adapter._write_dataset_event(7, "candidate", EVAL36[0], 0, "START")
        assert calls == 0
    elif failure == "eintr":
        with pytest.raises(RuntimeError, match="interrupted"):
            adapter._write_dataset_event(7, "candidate", EVAL36[0], 0, "START")
        assert calls == 1
    elif failure == "epipe":
        with pytest.raises(BrokenPipeError):
            adapter._write_dataset_event(7, "candidate", EVAL36[0], 0, "START")
        assert calls == 1
    else:
        with pytest.raises(RuntimeError, match="partial"):
            adapter._write_dataset_event(7, "candidate", EVAL36[0], 0, "START")
        assert calls == 1


def _debug_record(dataset: str):
    decision = divisions_module.TwinDeepCenterDecision(True, 0.2, None)
    removed = divisions_module.TwinEdgeRecord(2, 4, divisions_module.TwinFrozenMapping(()))
    planned = divisions_module.TwinPlannedEdge(1, 4, 6.0, None)
    return divisions_module.TwinDebugRecord(
        dataset=dataset,
        decision="accepted",
        reason=None,
        p=1,
        q=2,
        a=3,
        b=4,
        a2=5,
        b2=6,
        sort_key=(6.9, -3.0, 4.0, 1, 2, 3, 4, 5, 6),
        d_pq=4.0,
        d_pa=0.0,
        d_pb=6.0,
        d_ab=6.0,
        d_a2b2=8.0,
        divergence_growth=2.5,
        raw_deepcenter_score=0.2,
        deepcenter_threshold=0.12,
        deepcenter_decision=decision,
        removed_edge=removed,
        planned_edge=planned,
    )


def test_complete_plan_is_uncapped_beyond_200_while_debug_remains_bounded():
    adapter = _adapter()
    debug_records = tuple(_debug_record(EVAL36[0]) for _ in range(205))
    counters = divisions_module._twin_counters()
    counters["steal_twin_eligible"] = len(debug_records)
    plan = divisions_module.TwinPlan(
        validation_reason=None,
        nodes=(),
        edges=(),
        candidates=(),
        accepted_candidates=(),
        decisions=(),
        counters=divisions_module._frozen_twin_counters(counters),
        debug_records=debug_records,
    )
    dry_bytes = adapter._canonical_twin_plan(EVAL36[0], 0, plan)
    candidate_bytes = adapter._canonical_twin_plan(EVAL36[0], 0, plan)
    envelope = json.loads(dry_bytes)
    assert dry_bytes == candidate_bytes
    assert envelope["schema_version"] == "biohub.st_r3.twin_plan.v1"
    assert envelope["planner_active"] is True
    assert tuple(envelope["plan"]) == (
        "accepted_candidates",
        "candidates",
        "counters",
        "debug_records",
        "decisions",
        "edges",
        "nodes",
        "validation_reason",
    )
    assert len(envelope["plan"]["debug_records"]) == 205

    collector = pipeline_module._TwinDebugCollector(200)
    assert collector.allocate(debug_records) == (200, 5)
    assert collector.records_written == 200
    assert collector.records_dropped == 5


def test_baseline_plan_envelope_is_explicitly_inactive():
    adapter = _adapter()
    envelope = json.loads(adapter._canonical_twin_plan(EVAL36[0], 0, None))
    assert envelope == {
        "schema_version": "biohub.st_r3.twin_plan.v1",
        "dataset": EVAL36[0],
        "sequence": 0,
        "planner_active": False,
        "plan": None,
    }


def _raw_stats_row(dataset: str = EVAL36[0]) -> dict[str, object]:
    nodes = {1: {"node_id": 1, "t": 0, "z": 0.0, "y": 0.0, "x": 0.0}}
    return pipeline_module._dataset_stats_row(dataset, nodes, [], pipeline_module.new_stats(), 1, {})


def test_fixed_stats_schema_types_order_and_conservation():
    adapter = _adapter()
    row = _raw_stats_row()
    values = adapter._validate_raw_stats_row(row, EVAL36[0], frames_count=1)
    assert len(values) == len(adapter.RUN_STATS_COLUMNS)
    normalized = dict(zip(adapter.RUN_STATS_COLUMNS, values, strict=True))
    assert tuple(normalized) == adapter.RUN_STATS_COLUMNS
    assert normalized["stats_schema_version"] == "biohub.st_r3.run_stats.v1"
    assert normalized["dataset"] == EVAL36[0]
    assert type(normalized["frames"]) is int
    assert normalized["planner_seconds"] is None
    assert normalized["gap_close_effective_max_gap"] is None
    for name, value in normalized.items():
        if name in {"stats_schema_version", "dataset", "planner_seconds", "gap_close_effective_max_gap"}:
            continue
        if name in {"edge_to_node_ratio", "gap_added_nodes_frac"}:
            assert type(value) is float and math.isfinite(value)
        else:
            assert type(value) is int and value >= 0


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "extra",
        "reordered",
        "type",
        "nan",
        "conservation",
        "enumerated_gt_pool",
        "resolution",
        "isolated_donor",
        "active_r2",
    ],
)
def test_raw_stats_rejects_schema_type_nonfinite_and_conservation_corruption(corruption: str):
    adapter = _adapter()
    row = _raw_stats_row()
    if corruption == "missing":
        row.pop("linefit_skipped_nodes")
    elif corruption == "extra":
        row["invented"] = 0
    elif corruption == "reordered":
        row = {"raw_nodes": row["raw_nodes"], **{key: value for key, value in row.items() if key != "raw_nodes"}}
    elif corruption == "type":
        row["nodes"] = True
    elif corruption == "nan":
        row["edge_to_node_ratio"] = math.nan
    elif corruption == "conservation":
        row["steal_twin_mutations_applied"] = 1
    elif corruption == "enumerated_gt_pool":
        row["steal_twin_enumerated"] = 1
        row["steal_twin_p_pool"] = 0
        row["steal_twin_rejected_distance_twin"] = 1
    elif corruption == "resolution":
        row["steal_twin_enumerated"] = row["steal_twin_p_pool"] = row["steal_twin_eligible"] = 1
    elif corruption == "isolated_donor":
        row["steal_twin_enumerated"] = row["steal_twin_p_pool"] = row["steal_twin_eligible"] = 1
        row["steal_twin_accepted"] = row["steal_twin_examined_frames"] = 1
        row["steal_twin_planned_edges_removed"] = row["steal_twin_planned_edges_added"] = 1
    else:
        row["steal_twin_pure_nodes"] = 1
    with pytest.raises((TypeError, ValueError, RuntimeError)):
        adapter._validate_raw_stats_row(row, EVAL36[0], frames_count=1)


def _interface_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    raw = tmp_path / "raw"
    images = tmp_path / "images"
    staging = tmp_path / "staging"
    raw.mkdir()
    images.mkdir()
    staging.mkdir()
    for stem in EVAL36:
        (raw / f"{stem}.geff").mkdir()
        (images / f"{stem}.zarr").mkdir()
    return raw, images, staging


def test_validated_geff_paths_follow_literal_sequence_not_directory_iteration(tmp_path: Path):
    adapter = _adapter()
    raw, images, staging = _interface_dirs(tmp_path)
    read_fd, write_fd = os.pipe()
    try:
        spec = _spec(
            tmp_path,
            geff_dir=raw,
            test_dir=images,
            staging_dir=staging,
            event_fd=write_fd,
        )
        paths = adapter._validate_arm_spec(spec)
    finally:
        os.close(read_fd)
        os.close(write_fd)
    assert tuple(path.stem for path in paths) == EVAL36
    assert tuple(path.stem for path in paths) != tuple(sorted(EVAL36))


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "extra",
        "raw_extra_zarr",
        "raw_extra_unrelated",
        "image_extra_geff",
        "image_extra_zarr",
        "image_extra_unrelated",
        "duplicate",
        "reordered",
        "geff_symlink",
        "image_symlink",
        "nonfresh_staging",
    ],
)
def test_input_corruption_fails_before_config_detector_or_child_artifact(
    tmp_path: Path,
    monkeypatch,
    corruption: str,
):
    adapter = _adapter()
    raw, images, staging = _interface_dirs(tmp_path)
    datasets = EVAL36
    if corruption == "missing":
        (raw / f"{EVAL36[-1]}.geff").rmdir()
    elif corruption == "extra":
        (raw / "extra.geff").mkdir()
    elif corruption == "raw_extra_zarr":
        (raw / "hidden.zarr").mkdir()
    elif corruption == "raw_extra_unrelated":
        (raw / ".hidden").write_bytes(b"unregistered")
    elif corruption == "image_extra_geff":
        (images / "hidden_gt.geff").mkdir()
    elif corruption == "image_extra_zarr":
        (images / "extra.zarr").mkdir()
    elif corruption == "image_extra_unrelated":
        (images / ".hidden").write_bytes(b"unregistered")
    elif corruption == "duplicate":
        datasets = EVAL36[:-1] + (EVAL36[0],)
    elif corruption == "reordered":
        datasets = (EVAL36[1], EVAL36[0], *EVAL36[2:])
    elif corruption in {"geff_symlink", "image_symlink"}:
        suffix = ".geff" if corruption == "geff_symlink" else ".zarr"
        root = raw if corruption == "geff_symlink" else images
        victim = root / f"{EVAL36[0]}{suffix}"
        victim.rmdir()
        outside = tmp_path / f"outside{suffix}"
        outside.mkdir()
        victim.symlink_to(outside, target_is_directory=True)
    else:
        (staging / "stale.partial").write_bytes(b"stale")

    read_fd, write_fd = os.pipe()
    monkeypatch.setattr(adapter, "_build_arm_config", lambda _spec: pytest.fail("config built after input failure"))
    spec = _spec(
        tmp_path,
        geff_dir=raw,
        test_dir=images,
        staging_dir=staging,
        datasets=datasets,
        event_fd=write_fd,
    )
    before = tuple(sorted(path.relative_to(staging) for path in staging.rglob("*")))
    try:
        with pytest.raises((TypeError, ValueError, FileExistsError)):
            adapter.run_production_arm(spec)
    finally:
        os.close(read_fd)
        os.close(write_fd)
    after = tuple(sorted(path.relative_to(staging) for path in staging.rglob("*")))
    assert after == before


def _write_real_tiny_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    import blosc2
    import polars as pl
    import tracksdata as td

    raw = tmp_path / "real_raw"
    images = tmp_path / "real_images"
    raw.mkdir()
    images.mkdir()

    graph_template = tmp_path / "template.geff"
    graph = td.graph.InMemoryGraph()
    for key in ("z", "y", "x"):
        graph.add_node_attr_key(key, pl.Float64, -999999.0)
    assert graph.bulk_add_nodes([{"t": 0, "z": 0.0, "y": 0.0, "x": 0.0}]) == [0]
    graph.to_geff(graph_template)

    image_template = tmp_path / "template.zarr"
    array_dir = image_template / "0"
    array_dir.mkdir(parents=True)
    (array_dir / "zarr.json").write_text(json.dumps({"shape": [1, 1, 1, 1], "data_type": "uint16"}))
    chunk = array_dir / "c" / "0" / "0" / "0"
    chunk.mkdir(parents=True)
    (chunk / "0").write_bytes(blosc2.compress(b"\0\0", typesize=2))

    for stem in EVAL36:
        shutil.copytree(graph_template, raw / f"{stem}.geff")
        shutil.copytree(image_template, images / f"{stem}.zarr")
    checkpoint = tmp_path / "fixture-checkpoint.pt"
    manifest = tmp_path / "fixture-manifest.json"
    checkpoint.write_bytes(b"strict loader boundary replaced only in fresh-process fixture")
    manifest.write_bytes(b"{}\n")
    return raw, images, checkpoint, manifest


def _run_real_cli_fixture(
    tmp_path: Path,
    arm_name: str,
    raw: Path,
    images: Path,
    checkpoint: Path,
    manifest: Path,
) -> tuple[Path, list[dict[str, object]], subprocess.CompletedProcess[str]]:
    adapter = _adapter()
    staging = tmp_path / f"staging-{arm_name}"
    staging.mkdir()
    read_fd, write_fd = os.pipe()
    spec = _spec(
        tmp_path,
        arm_name,
        geff_dir=raw,
        test_dir=images,
        deepcenter_checkpoint=checkpoint,
        deepcenter_manifest=manifest,
        staging_dir=staging,
        event_fd=write_fd,
    )
    cfg = adapter._build_arm_config(spec)
    config_sha = hashlib.sha256(adapter._canonical_effective_config(cfg)).hexdigest()
    argv = [
        sys.executable,
        "-c",
        (
            "import runpy,sys;"
            "import biohub.public_postproc.production_adapter as p;"
            "p.load_deepcenter_veto_detector_strict=lambda *a,**k:"
            "({}, {'schema_version':p.DEEPCENTER_RECEIPT_SCHEMA,'fixture_boundary':'torch'});"
            "script=sys.argv.pop(1);runpy.run_path(script,run_name='__main__')"
        ),
        str(CLI),
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
    for dataset in EVAL36:
        argv.extend(("--dataset", dataset))
    process = subprocess.Popen(
        argv,
        cwd=ROOT,
        pass_fds=(write_fd,),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    os.close(write_fd)
    event_chunks: list[bytes] = []

    def drain_events() -> None:
        while chunk := os.read(read_fd, 4096):
            event_chunks.append(chunk)
        os.close(read_fd)

    thread = threading.Thread(target=drain_events)
    thread.start()
    stdout, stderr = process.communicate(timeout=120)
    thread.join(timeout=10)
    assert not thread.is_alive()
    completed = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    events = [json.loads(line) for line in b"".join(event_chunks).splitlines()]
    return staging, events, completed


def test_real_fresh_process_cli_all_three_arms_and_child_artifact_contract(tmp_path: Path):
    adapter = _adapter()
    raw, images, checkpoint, manifest = _write_real_tiny_fixture(tmp_path)
    submissions: dict[str, bytes] = {}
    plans: dict[str, list[bytes]] = {}
    for arm_name in ("baseline", "dry_run", "candidate"):
        staging, events, completed = _run_real_cli_fixture(
            tmp_path,
            arm_name,
            raw,
            images,
            checkpoint,
            manifest,
        )
        assert completed.returncode == 0, completed.stderr
        assert len(events) == 72
        assert [event["dataset"] for event in events[::2]] == list(EVAL36)
        assert [event["dataset"] for event in events[1::2]] == list(EVAL36)
        assert [event["kind"] for event in events] == [kind for _ in EVAL36 for kind in ("START", "FINISH")]
        assert [event["sequence"] for event in events] == [sequence for sequence in range(36) for _ in range(2)]
        assert {event["pid"] for event in events} == {events[0]["pid"]}
        assert type(events[0]["pid"]) is int and events[0]["pid"] > 0
        assert all(event["arm_name"] == arm_name for event in events)
        assert all(
            first["monotonic_ns"] < second["monotonic_ns"]
            for first, second in zip(events, events[1:], strict=False)
        )

        names = {path.relative_to(staging).as_posix() for path in staging.rglob("*") if path.is_file()}
        assert "dataset_events.jsonl" not in names
        assert "arm_receipt.json" not in names
        assert "twin_debug.jsonl.partial" not in names
        assert adapter.CHILD_RESULT_NAME in names
        assert adapter.SUBMISSION_PARTIAL in names
        assert adapter.RUN_STATS_PARTIAL in names
        assert adapter.EFFECTIVE_CONFIG_PARTIAL in names
        assert adapter.DEEPCENTER_RECEIPT_PARTIAL in names
        assert adapter.TWIN_PLAN_MANIFEST_PARTIAL in names
        assert not any(name.endswith(".tmp") for name in names)

        child_path = staging / adapter.CHILD_RESULT_NAME
        child = json.loads(child_path.read_bytes())
        assert child["schema_version"] == "biohub.st_r3.child_result.v1"
        assert child["arm_name"] == arm_name
        assert child["datasets"] == list(EVAL36)
        assert child["total_nodes"] == child["total_rows"] == 36
        assert child["total_edges"] == 0
        assert all(item["relative_path"] != adapter.CHILD_RESULT_NAME for item in child["artifacts"])
        for item in child["artifacts"]:
            artifact = staging / item["relative_path"]
            data = artifact.read_bytes()
            assert item["bytes"] == len(data)
            assert item["sha256"] == hashlib.sha256(data).hexdigest()
            assert child_path.stat().st_mtime_ns >= artifact.stat().st_mtime_ns

        submissions[arm_name] = (staging / adapter.SUBMISSION_PARTIAL).read_bytes()
        with (staging / adapter.SUBMISSION_PARTIAL).open(newline="") as handle:
            submission_rows = list(csv.DictReader(handle))
        assert [row["dataset"] for row in submission_rows] == list(EVAL36)
        with (staging / adapter.RUN_STATS_PARTIAL).open(newline="") as handle:
            stats_rows = list(csv.DictReader(handle))
        assert tuple(stats_rows[0]) == adapter.RUN_STATS_COLUMNS
        assert [row["dataset"] for row in stats_rows] == list(EVAL36)

        plan_paths = [staging / adapter.TWIN_PLAN_DIRECTORY / f"{i}.{dataset}.json" for i, dataset in enumerate(EVAL36)]
        plans[arm_name] = [path.read_bytes() for path in plan_paths]
        for sequence, data in enumerate(plans[arm_name]):
            envelope = json.loads(data)
            assert envelope["sequence"] == sequence
            assert envelope["dataset"] == EVAL36[sequence]
            assert envelope["planner_active"] is (arm_name != "baseline")

    assert submissions["baseline"] == submissions["dry_run"]
    assert submissions["dry_run"] == submissions["candidate"]
    assert plans["dry_run"] == plans["candidate"]


def test_real_cli_hash_failure_is_nonzero_and_preserves_empty_failed_staging(tmp_path: Path):
    raw, images, staging = _interface_dirs(tmp_path)
    read_fd, write_fd = os.pipe()
    argv = [
        sys.executable,
        str(CLI),
        "--arm-name",
        "baseline",
        "--geff-dir",
        str(raw),
        "--test-dir",
        str(images),
        "--deepcenter-checkpoint",
        str(tmp_path / "registered.pt"),
        "--deepcenter-manifest",
        str(tmp_path / "ARTIFACT_MANIFEST.json"),
        "--expected-effective-config-sha256",
        "0" * 64,
        "--staging-dir",
        str(staging),
        "--event-fd",
        str(write_fd),
    ]
    for dataset in EVAL36:
        argv.extend(("--dataset", dataset))
    try:
        completed = subprocess.run(
            argv,
            cwd=ROOT,
            pass_fds=(write_fd,),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    finally:
        os.close(read_fd)
        os.close(write_fd)
    assert completed.returncode != 0
    assert "effective-config SHA-256 mismatch" in completed.stderr
    assert list(staging.iterdir()) == []
    assert not (staging / "child_result.json").exists()
    assert not (staging / "arm_receipt.json").exists()
    assert not (staging / "dataset_events.jsonl").exists()


def test_epipe_after_initial_staging_preserves_partials_without_success_result(tmp_path: Path, monkeypatch):
    adapter = _adapter()
    raw, images, staging = _interface_dirs(tmp_path)
    read_fd, write_fd = os.pipe()
    spec = _spec(
        tmp_path,
        "candidate",
        geff_dir=raw,
        test_dir=images,
        staging_dir=staging,
        event_fd=write_fd,
    )
    cfg = adapter._build_arm_config(spec)
    spec = replace(
        spec,
        expected_effective_config_sha256=hashlib.sha256(adapter._canonical_effective_config(cfg)).hexdigest(),
    )
    monkeypatch.setattr(
        adapter,
        "load_deepcenter_veto_detector_strict",
        lambda *_args, **_kwargs: ({}, {"schema_version": adapter.DEEPCENTER_RECEIPT_SCHEMA}),
    )

    def fail_on_start(_paths, _submission, _cfg, **kwargs):
        kwargs["dataset_start_hook"](0, EVAL36[0])
        pytest.fail("pipeline continued after EPIPE")

    monkeypatch.setattr(adapter, "run_postproc_core", fail_on_start)
    os.close(read_fd)
    try:
        with pytest.raises(BrokenPipeError):
            adapter.run_production_arm(spec)
    finally:
        os.close(write_fd)
    assert (staging / adapter.EFFECTIVE_CONFIG_PARTIAL).is_file()
    assert (staging / adapter.DEEPCENTER_RECEIPT_PARTIAL).is_file()
    assert (staging / adapter.RUN_STATS_PARTIAL).is_file()
    assert (staging / adapter.TWIN_PLAN_DIRECTORY).is_dir()
    assert not (staging / adapter.CHILD_RESULT_NAME).exists()
    assert not (staging / adapter.TWIN_PLAN_MANIFEST_PARTIAL).exists()
    assert not (staging / "arm_receipt.json").exists()
    assert not (staging / "dataset_events.jsonl").exists()


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_reference_json_encoder_refuses_nonfinite_values(bad: float):
    with pytest.raises(ValueError, match="[Oo]ut of range"):
        _canonical_json({"value": bad})


def test_reference_json_encoder_preserves_negative_zero_bits():
    encoded = _canonical_json({"value": -0.0})
    decoded = json.loads(encoded)["value"]
    assert encoded == b'{"value":-0.0}\n'
    assert struct.pack(">d", decoded) == struct.pack(">d", -0.0)


def test_pipeline_plan_hook_precedes_debug_allocation_and_mutation(tmp_path: Path, monkeypatch):
    cfg = replace(
        build_config(
            {
                "BIOHUB_STEAL_TWIN_DEBUG_JSONL": str(tmp_path / "bounded.jsonl"),
                "BIOHUB_STEAL_TWIN_DRY_RUN": "0",
            },
            test_dir=tmp_path,
            profile="e23_twin_only_v1",
        ),
        USE_DEEPCENTER_VETO=False,
        REQUIRE_DEEPCENTER_VETO=False,
        REFINE_ALL_CENTROIDS=False,
    )
    observed: list[str] = []

    class Collector:
        def allocate(self, records):
            assert type(records) is tuple
            observed.append("debug")
            return len(records), 0

    real_mutator = pipeline_module.apply_twin_only_v1_plan

    def mutator(nodes, edges, plan):
        observed.append("mutation")
        return real_mutator(nodes, edges, plan)

    monkeypatch.setattr(pipeline_module, "apply_twin_only_v1_plan", mutator)
    nodes = {1: {"node_id": 1, "t": 0, "z": 0.0, "y": 0.0, "x": 0.0}}
    pipeline_module.filter_output_graph_pre_linefit(
        cfg,
        nodes,
        [],
        dataset="fixture",
        twin_debug_collector=Collector(),
        twin_plan_hook=lambda dataset, plan: (
            observed.append("plan"),
            pytest.fail("wrong plan dataset") if dataset != "fixture" else None,
            pytest.fail("active arm emitted inactive plan") if plan is None else None,
        ),
    )
    assert observed[:3] == ["plan", "debug", "mutation"]


def test_pipeline_core_preserves_explicit_order_and_freezes_raw_stats(tmp_path: Path, monkeypatch):
    requested = (Path("z.geff"), Path("a.geff"))
    seen: list[tuple[str, object]] = []
    cfg = replace(
        build_config(test_dir=tmp_path),
        OUTPUT_STEAL_TWIN_REWIRE=False,
        USE_DEEPCENTER_VETO=False,
        REQUIRE_DEEPCENTER_VETO=False,
    )

    def load(path: Path):
        seen.append(("load", path.stem))
        return ({1: {"node_id": 1, "t": 0, "z": 0.0, "y": 0.0, "x": 0.0}}, [])

    def filtered(_cfg, nodes, edges, *, dataset, **kwargs):
        del _cfg, kwargs
        seen.append(("filter", dataset))
        return nodes, edges, pipeline_module.new_stats()

    def raw(row):
        seen.append(("stats", row["dataset"]))
        assert isinstance(row, MappingProxyType)
        with pytest.raises(TypeError):
            row["nodes"] = 9

    monkeypatch.setattr(pipeline_module, "_load_geff_as_dicts", load)
    monkeypatch.setattr(pipeline_module, "filter_output_graph", filtered)
    result = pipeline_module.run_postproc_core(
        requested,
        tmp_path / "submission.csv",
        cfg,
        deepcenter_loader=lambda _cfg: None,
        dataset_start_hook=lambda sequence, dataset: seen.append(("start", (sequence, dataset))),
        raw_stats_hook=raw,
        dataset_finish_hook=lambda sequence, dataset: seen.append(("finish", (sequence, dataset))),
        write_run_stats_output=False,
    )
    assert result["datasets"] == ["z", "a"]
    assert seen == [
        ("start", (0, "z")),
        ("load", "z"),
        ("filter", "z"),
        ("stats", "z"),
        ("finish", (0, "z")),
        ("start", (1, "a")),
        ("load", "a"),
        ("filter", "a"),
        ("stats", "a"),
        ("finish", (1, "a")),
    ]


def test_strict_deepcenter_pins_match_the_appendix():
    assert deepcenter_module.STRICT_DEEPCENTER_CHECKPOINT_SHA256 == (
        "8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0"
    )
    assert deepcenter_module.STRICT_DEEPCENTER_MANIFEST_SHA256 == (
        "1eedc1af72b10c464c6995013075310510b6f6e634450ff2bc170c67b89ce911"
    )
    assert deepcenter_module.STRICT_DEEPCENTER_EPOCH == 2
    assert deepcenter_module.STRICT_DEEPCENTER_MANIFEST_MODEL_CONFIG["epochs"] == 1000
    assert deepcenter_module.STRICT_DEEPCENTER_CHECKPOINT_MODEL_CONFIG["epochs"] == 50
    assert dict(deepcenter_module.STRICT_DEEPCENTER_CONFIG_DISCREPANCY) == {
        "field": "epochs",
        "manifest": 1000,
        "checkpoint": 50,
    }
    assert str(inspect.signature(deepcenter_module.load_deepcenter_veto_detector_strict)) == (
        "(cfg: 'PostprocConfig', checkpoint_path: 'Path', manifest_path: 'Path') "
        "-> 'tuple[dict[str, object], dict[str, object]]'"
    )


def test_strict_deepcenter_loads_each_registered_file_once_from_retained_fd(tmp_path: Path, monkeypatch):
    manifest_config = {"base_channels": 1, "epochs": 1000}
    checkpoint_config = {"base_channels": 1, "epochs": 50}
    checkpoint = tmp_path / "registered.pt"
    checkpoint.write_bytes(_canonical_json({"config": checkpoint_config, "epoch": 2, "model_state": {}}))
    checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    manifest = tmp_path / "ARTIFACT_MANIFEST.json"
    manifest.write_bytes(
        _canonical_json(
            {
                "model": {
                    "best_checkpoint": {"sha256": checkpoint_sha},
                    "best_checkpoint_summary": {"epoch": 2},
                    "config": manifest_config,
                }
            }
        )
    )
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    opened: list[Path] = []
    real_open = deepcenter_module.os.open

    def tracking_open(path, flags):
        opened.append(Path(path))
        return real_open(path, flags)

    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return False

    class FakeTorch:
        cuda = FakeCuda()

        @staticmethod
        def device(value):
            return value

        @staticmethod
        def load(handle, **kwargs):
            assert kwargs == {"map_location": "cpu", "weights_only": False}
            assert not handle.closed and handle.tell() == 0
            return json.load(handle)

    class FakeModel:
        def __init__(self, *, base_channels):
            assert base_channels == 1

        def load_state_dict(self, state):
            assert state == {}

        def to(self, device):
            assert device == "cpu"

        def eval(self):
            return None

    monkeypatch.setattr(deepcenter_module.os, "open", tracking_open)
    monkeypatch.setattr(deepcenter_module, "torch", FakeTorch())
    monkeypatch.setattr(deepcenter_module, "_DCDeepCenterUNet3D", FakeModel)
    cfg = build_config(test_dir=tmp_path, profile="e23")
    bundle, receipt = deepcenter_module._load_deepcenter_veto_detector_strict_verified(
        cfg,
        checkpoint,
        manifest,
        expected_checkpoint_sha256=checkpoint_sha,
        expected_manifest_sha256=manifest_sha,
        expected_epoch=2,
        expected_manifest_model_config=manifest_config,
        expected_checkpoint_model_config=checkpoint_config,
    )
    assert opened == [manifest, checkpoint]
    assert bundle["path"] == checkpoint and bundle["checkpoint_epoch"] == 2
    assert receipt["schema_version"] == "biohub.st_r3.deepcenter_receipt.v1"
    assert receipt["open_count"] == 2
    assert receipt["fallback_candidates"] == 0
    assert receipt["manifest"]["open_count"] == 1
    assert receipt["checkpoint"]["open_count"] == 1
    assert receipt["registered"] == {
        "checkpoint_name": checkpoint.name,
        "manifest_name": manifest.name,
    }
    assert receipt["verified_configs"] == {
        "manifest": manifest_config,
        "checkpoint": checkpoint_config,
    }
    assert receipt["known_config_discrepancy"] == {
        "field": "epochs",
        "manifest": 1000,
        "checkpoint": 50,
    }
    assert receipt["inference_relevant_config_equal"] is True


def test_strict_reader_rejects_same_fd_metadata_drift_before_parse(tmp_path: Path, monkeypatch):
    target = tmp_path / "artifact.bin"
    target.write_bytes(b"same-fd bytes")
    expected = hashlib.sha256(target.read_bytes()).hexdigest()
    real_fstat = deepcenter_module.os.fstat
    calls = 0

    def drifting_fstat(fd):
        nonlocal calls
        calls += 1
        actual = real_fstat(fd)
        if calls == 2:
            values = {name: getattr(actual, name) for name in (
                "st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns"
            )}
            values["st_mtime_ns"] += 1
            return SimpleNamespace(**values)
        return actual

    monkeypatch.setattr(deepcenter_module.os, "fstat", drifting_fstat)
    with pytest.raises(RuntimeError, match="changed while hashing"):
        deepcenter_module._strict_read_one_file(
            target,
            expected,
            lambda _handle: pytest.fail("parsed after fstat drift"),
        )


def test_strict_reader_hash_mismatch_never_parses_or_falls_back(tmp_path: Path):
    target = tmp_path / "registered.bin"
    target.write_bytes(b"registered")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        deepcenter_module._strict_read_one_file(
            target,
            hashlib.sha256(b"different").hexdigest(),
            lambda _handle: pytest.fail("parsed after hash mismatch"),
        )


def test_strict_loader_rejects_manifest_identity_before_checkpoint_open(tmp_path: Path, monkeypatch):
    model_config = {"base_channels": 1}
    checkpoint = tmp_path / "registered.pt"
    checkpoint.write_bytes(b"checkpoint must not open")
    checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    manifest = tmp_path / "ARTIFACT_MANIFEST.json"
    manifest.write_bytes(
        _canonical_json(
            {
                "model": {
                    "best_checkpoint": {"sha256": "0" * 64},
                    "best_checkpoint_summary": {"epoch": 2},
                    "config": model_config,
                }
            }
        )
    )
    opened: list[Path] = []
    real_open = deepcenter_module.os.open

    def tracking_open(path, flags):
        opened.append(Path(path))
        return real_open(path, flags)

    monkeypatch.setattr(deepcenter_module.os, "open", tracking_open)
    monkeypatch.setattr(deepcenter_module, "torch", object())
    with pytest.raises(ValueError, match="manifest identity/config mismatch"):
        deepcenter_module._load_deepcenter_veto_detector_strict_verified(
            build_config(test_dir=tmp_path, profile="e23"),
            checkpoint,
            manifest,
            expected_checkpoint_sha256=checkpoint_sha,
            expected_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
            expected_epoch=2,
            expected_manifest_model_config=model_config,
            expected_checkpoint_model_config=model_config,
        )
    assert opened == [manifest]


def test_strict_loader_rejects_checkpoint_epoch_from_same_fd(tmp_path: Path, monkeypatch):
    model_config = {"base_channels": 1}
    checkpoint = tmp_path / "registered.pt"
    checkpoint.write_bytes(_canonical_json({"config": model_config, "epoch": 1, "model_state": {}}))
    checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    manifest = tmp_path / "ARTIFACT_MANIFEST.json"
    manifest.write_bytes(
        _canonical_json(
            {
                "model": {
                    "best_checkpoint": {"sha256": checkpoint_sha},
                    "best_checkpoint_summary": {"epoch": 2},
                    "config": model_config,
                }
            }
        )
    )

    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return False

    class FakeTorch:
        cuda = FakeCuda()

        @staticmethod
        def device(value):
            return value

        @staticmethod
        def load(handle, **_kwargs):
            assert handle.tell() == 0
            return json.load(handle)

    monkeypatch.setattr(deepcenter_module, "torch", FakeTorch())
    with pytest.raises(ValueError, match="checkpoint epoch mismatch"):
        deepcenter_module._load_deepcenter_veto_detector_strict_verified(
            build_config(test_dir=tmp_path, profile="e23"),
            checkpoint,
            manifest,
            expected_checkpoint_sha256=checkpoint_sha,
            expected_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
            expected_epoch=2,
            expected_manifest_model_config=model_config,
            expected_checkpoint_model_config=model_config,
        )


def test_strict_reader_requires_nofollow_support(tmp_path: Path, monkeypatch):
    target = tmp_path / "artifact.bin"
    target.write_bytes(b"registered")
    expected = hashlib.sha256(target.read_bytes()).hexdigest()
    monkeypatch.delattr(deepcenter_module.os, "O_NOFOLLOW")
    with pytest.raises(RuntimeError, match="requires O_NOFOLLOW"):
        deepcenter_module._strict_read_one_file(target, expected, lambda handle: handle.read())


def test_strict_reader_rejects_symlink_without_fallback(tmp_path: Path):
    target = tmp_path / "real.bin"
    target.write_bytes(b"registered")
    alias = tmp_path / "alias.bin"
    alias.symlink_to(target)
    expected = hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(OSError):
        deepcenter_module._strict_read_one_file(alias, expected, lambda handle: handle.read())


def test_strict_path_category_accepts_platform_path_but_rejects_subclass(tmp_path: Path):
    target = tmp_path / "artifact.bin"
    target.write_bytes(b"registered")
    expected = hashlib.sha256(target.read_bytes()).hexdigest()
    assert deepcenter_module._strict_read_one_file(target, expected, lambda handle: handle.read())[0] == b"registered"

    class PathSubclass(type(Path())):
        pass

    with pytest.raises(TypeError, match="exact pathlib.Path"):
        deepcenter_module._strict_read_one_file(PathSubclass(target), expected, lambda handle: handle.read())
