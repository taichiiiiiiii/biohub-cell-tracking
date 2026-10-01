"""Bounded adversarial tests for label-blind ST-R3 generation."""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from biohub import st_r3_generation as generation


def _write_json(path: Path, value: object) -> bytes:
    data = generation.canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def _inventory(root: Path, kind: str) -> dict[str, object]:
    return generation._inventory_value(kind, root, generation._tree_records(root))


def _tiny_ready_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    stems = generation.E24_IMPORT_ROOTS
    monkeypatch.setattr(generation, "EVAL36", stems)
    monkeypatch.setattr(generation, "EXPECTED_IMAGE_FILES", 1_530)
    monkeypatch.setattr(generation, "EXPECTED_IMAGE_BYTES", 1_530)
    view = tmp_path / "images"
    files = sorted(
        relative
        for stem in stems
        for relative in [f"{stem}.zarr/zarr.json", f"{stem}.zarr/0/zarr.json"]
        + [f"{stem}.zarr/0/c/{index}/0/0/0" for index in range(100)]
    )
    for relative in files:
        path = view / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"a")
    records = [
        {
            "path": relative,
            "bytes": 1,
            "sha256": hashlib.sha256(b"a").hexdigest(),
            "stem": relative.split(".zarr/", 1)[0],
        }
        for relative in files
    ]
    summary = {"chunks": 3_600, "files": 1_530, "roots": 36, "stored_bytes": 1_530}
    evidence = tmp_path / "outputs/local/eval36_image_ready/fixed/"
    evidence.mkdir(parents=True)
    inventory_data = _write_json(
        evidence / "IMAGE_CONTENT_INVENTORY.json",
        {
            "files": records,
            "roots": list(stems),
            "schema_version": "biohub.eval36_image_content_inventory.v1",
            "summary": summary,
        },
    )
    import_receipt_value = {
        "archives": [
            {"bytes": size, "name": f"{root}.tar", "root": root, "sha256": digest}
            for root, size, digest in zip(
                generation.E24_IMPORT_ROOTS,
                generation.E24_IMPORT_BYTES,
                generation.E24_IMPORT_SHA256,
                strict=True,
            )
        ],
        "data_root_identity": {"device": 1, "inode": 2},
        "files": [
            {
                "action": "installed" if index < 1_487 else "skipped",
                "path": f"train/{files[index]}",
                "sha256": hashlib.sha256(b"a").hexdigest(),
                "size": 1,
            }
            for index in range(1_530)
        ],
        "installed": 1_487,
        "manifest_csv_sha256": generation.IMAGE_MANIFEST_SHA256,
        "schema_version": 1,
        "skipped": 43,
        "status": "PASS",
        "validated": 1_530,
    }
    import_data = generation.canonical_json_bytes(import_receipt_value)
    import_digest = hashlib.sha256(import_data).hexdigest()
    import_relative = f"outputs/local/import/eval36-import-{import_digest}.json"
    import_receipt = tmp_path / import_relative
    import_receipt.parent.mkdir(parents=True)
    import_receipt.write_bytes(import_data)
    monkeypatch.setattr(generation, "CANONICAL_IMPORT_PATH", import_relative)
    monkeypatch.setattr(generation, "CANONICAL_IMPORT_SHA256", import_digest)
    verifier = tmp_path / "scripts" / "verify_eval36_images.py"
    verifier.parent.mkdir()
    verifier.write_bytes(b"verifier\n")
    core = {
        "data_root_identity": {"device": -1, "inode": -1},
        "decoded": {
            "aggregate_sha256": "635a326ff78526a3d43952b94950e6d97d07db14cd53bc056517ea70d5b49646",
            "bytes": 30_198_988_800,
            "chunks": 3_600,
            "order": generation.READY_DECODE_ORDER,
        },
        "digest_scope": generation.READY_DIGEST_SCOPE,
        "import_receipt": {
            "bytes": len(import_data),
            "reference": import_receipt.name,
            "sha256": hashlib.sha256(import_data).hexdigest(),
            "status": "PASS",
            "installed": 1_487,
            "skipped": 43,
            "validated": 1_530,
        },
        "inventory": {
            "bytes": len(inventory_data),
            "path": "IMAGE_CONTENT_INVENTORY.json",
            "sha256": hashlib.sha256(inventory_data).hexdigest(),
            "summary": summary,
        },
        "manifest": {
            "bytes": 1_187_624,
            "lines": 24_887,
            "path": "manifest.csv",
            "sha256": generation.IMAGE_MANIFEST_SHA256,
        },
        "schema_version": "biohub.eval36_images_ready.v1",
        "status": "READY",
        "verifier": {
            "bytes": len(b"verifier\n"),
            "reference": verifier.name,
            "sha256": hashlib.sha256(b"verifier\n").hexdigest(),
        },
    }
    ready = {
        **core,
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "ready_content_sha256": hashlib.sha256(generation.canonical_json_bytes(core)).hexdigest(),
    }
    ready_path = evidence / "READY.json"
    ready_data = _write_json(ready_path, ready)
    monkeypatch.setattr(generation, "CANONICAL_READY_PATH", ready_path.relative_to(tmp_path).as_posix())
    monkeypatch.setattr(generation, "CANONICAL_READY_SHA256", hashlib.sha256(ready_data).hexdigest())
    monkeypatch.setattr(generation, "CANONICAL_READY_CONTENT_SHA256", ready["ready_content_sha256"])
    monkeypatch.setattr(generation, "CANONICAL_IMAGE_INVENTORY_SHA256", hashlib.sha256(inventory_data).hexdigest())
    return ready_path, import_receipt, view


def _raw_provenance_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str = "primary"
) -> tuple[Path, dict[str, object], dict[str, object]]:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    runtime_value = {
        "status": "complete_label_free_runtime_integrity",
        "ground_truth_accessed": False,
        "checkpoint_sha256": {
            "deepcenter": generation.DEEPCENTER_CHECKPOINT_SHA256,
            "primary": generation.PRIMARY_RAW_WEIGHT_SHA256,
            "secondary": generation.SECONDARY_RAW_WEIGHT_SHA256,
        },
        "support_repo_python_file_count": 13,
        "support_repo_python_manifest_sha256": "978b626d1fd1e7397435a437dfe68691defe1572fc3c20e61012d7c9b52ed029",
    }
    runtime_data = _write_json(evidence / "runtime.json", runtime_value)
    log_data = (
        f"Weight sha256: {generation.PRIMARY_RAW_WEIGHT_SHA256}\n"
        f"Primary materialized SHA256: {generation.PRIMARY_RAW_WEIGHT_SHA256}\n"
        f"Secondary SHA256: {generation.SECONDARY_RAW_WEIGHT_SHA256}\n"
        "VALIDATOR: merged 36 prediction graphs into fixed\n"
        "VALIDATOR: prediction completed in fixed\n"
    ).encode()
    (evidence / "raw.log").write_bytes(log_data)
    runtime_ref = {
        "path": "evidence/runtime.json",
        "bytes": len(runtime_data),
        "sha256": hashlib.sha256(runtime_data).hexdigest(),
    }
    log_ref = {
        "path": "evidence/raw.log",
        "bytes": len(log_data),
        "sha256": hashlib.sha256(log_data).hexdigest(),
    }
    download_value = {
        "source": {
            "kernel": "taichiiiii/biohub-eval-train-raw",
            "version": 11,
            "kernel_id": 131_740_073,
            "latest_status": "KernelWorkerStatus.COMPLETE",
        },
        "raw_geff": {
            "path": "../e22_bidir030_eval36_raw/tracking_repo/predictions/unknown/unet_transformer_val/split_0",
            "roots": 36,
            "files": generation.EXPECTED_RAW_FILES,
            "bytes": generation.EXPECTED_RAW_BYTES,
            "canonical_sha256sum_tree_sha256": "fa34dcf5f20054f240d750bd2225dd08fc6cf645e094cd9596ce2faf4bbf0ca2",
            "zarr_semantic_validation": "passed",
            "resume_verification_runs": 1,
        },
        "reference_files": {
            "bidirectional_production_runtime_integrity.json": {
                "bytes": runtime_ref["bytes"],
                "sha256": runtime_ref["sha256"],
            },
            "biohub-eval-train-raw.log": {"bytes": log_ref["bytes"], "sha256": log_ref["sha256"]},
        },
    }
    download_data = _write_json(evidence / "download.json", download_value)
    download_ref = {
        "path": "evidence/download.json",
        "bytes": len(download_data),
        "sha256": hashlib.sha256(download_data).hexdigest(),
    }
    for name, value in {
        "RAW_DOWNLOAD_MANIFEST_PATH": download_ref["path"],
        "RAW_DOWNLOAD_MANIFEST_BYTES": download_ref["bytes"],
        "RAW_DOWNLOAD_MANIFEST_SHA256": download_ref["sha256"],
        "RAW_RUNTIME_INTEGRITY_PATH": runtime_ref["path"],
        "RAW_RUNTIME_INTEGRITY_BYTES": runtime_ref["bytes"],
        "RAW_RUNTIME_INTEGRITY_SHA256": runtime_ref["sha256"],
        "RAW_DERIVATION_LOG_PATH": log_ref["path"],
        "RAW_DERIVATION_LOG_BYTES": log_ref["bytes"],
        "RAW_DERIVATION_LOG_SHA256": log_ref["sha256"],
    }.items():
        monkeypatch.setattr(generation, name, value)
    source = {"superproject_commit": "a" * 40, "git_tree_oid": "b" * 40}
    known = generation.PRIMARY_RAW_WEIGHT_SHA256 if role == "primary" else generation.SECONDARY_RAW_WEIGHT_SHA256
    receipt_value = {
        "schema_version": generation.RAW_PROVENANCE_SCHEMA,
        "status": "LEGACY_HISTORY_UNVERIFIED",
        "role": role,
        "created_utc": "2026-08-30T00:00:00Z",
        "source": {
            "commit": source["superproject_commit"],
            "git_tree_oid": source["git_tree_oid"],
            "official_gitlink": generation.OFFICIAL_REVIEWED_OID,
        },
        "raw_root": generation.CANONICAL_RAW_ROOT,
        "raw_records_sha256": generation.CANONICAL_RAW_RECORDS_SHA256,
        "known_weight_sha256": known,
        "download_manifest": download_ref,
        "runtime_integrity": runtime_ref,
        "derivation_log": log_ref,
        "claims": {
            "checkpoint_bytes_locally_available": False,
            "checkpoint_to_raw_cryptographic_proof": False,
            "legacy_log_and_runtime_receipts_verified": True,
        },
    }
    receipt = tmp_path / f"{role}.json"
    _write_json(receipt, receipt_value)
    raw_inventory = {
        "file_count": generation.EXPECTED_RAW_FILES,
        "total_bytes": generation.EXPECTED_RAW_BYTES,
        "records_sha256": generation.CANONICAL_RAW_RECORDS_SHA256,
    }
    return receipt, raw_inventory, source


def _prereg_fixture(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path
    run = repo / "outputs" / "run-1"
    (run / "inputs").mkdir(parents=True)
    raw = repo / "raw"
    images = repo / "images"
    deep = repo / "deep"
    raw.mkdir()
    images.mkdir()
    deep.mkdir()
    (raw / "tiny.bin").write_bytes(b"raw")
    (images / "tiny.bin").write_bytes(b"image")
    (deep / "best.pt").write_bytes(b"checkpoint")
    (deep / "manifest.json").write_bytes(b"manifest")
    raw_inventory = _inventory(raw, "raw_geff")
    image_inventory = _inventory(images, "image_content")
    _write_json(run / "inputs" / "RAW_CONTENT_INVENTORY.json", raw_inventory)
    _write_json(run / "inputs" / "IMAGE_CONTENT_INVENTORY.json", image_inventory)
    config_bytes = {arm: generation.canonical_json_bytes({"arm": arm}) for arm in ("baseline", "dry_run", "candidate")}
    configs = {arm: hashlib.sha256(data).hexdigest() for arm, data in config_bytes.items()}
    executions = []
    for key, arm, relative in generation.FROZEN_EXECUTIONS:
        executions.append(
            {
                "key": key,
                "arm": arm,
                "relative_output": relative,
                "argv": [
                    "/python",
                    str(repo / "scripts" / "experiments" / "st_r3" / "st_r3_supervise_arm.py"),
                    "--arm-name",
                    arm,
                    "--geff-dir",
                    str(raw),
                    "--test-dir",
                    str(images),
                    "--deepcenter-checkpoint",
                    str(deep / "best.pt"),
                    "--deepcenter-manifest",
                    str(deep / "manifest.json"),
                    "--expected-effective-config-sha256",
                    configs[arm],
                    "--final-dir",
                    str(run / relative),
                    "--timeout-seconds",
                    "1.0",
                ],
            }
        )
    prereg = {
        "schema_version": generation.PREREGISTRATION_SCHEMA,
        "state": "PREREGISTERED_WITH_MANDATORY_HOLDS",
        "run_id": run.name,
        "datasets": generation._dataset_binding(),
        "inputs": {
            "raw_geff_root": "raw",
            "raw_inventory": "inputs/RAW_CONTENT_INVENTORY.json",
            "raw_inventory_sha256": hashlib.sha256(generation.canonical_json_bytes(raw_inventory)).hexdigest(),
            "image_view": "images",
            "image_content_inventory": "inputs/IMAGE_CONTENT_INVENTORY.json",
            "image_content_inventory_sha256": hashlib.sha256(
                generation.canonical_json_bytes(image_inventory)
            ).hexdigest(),
            "deepcenter": {
                "checkpoint": {
                    "path": "deep/best.pt",
                    "bytes": len(b"checkpoint"),
                    "sha256": hashlib.sha256(b"checkpoint").hexdigest(),
                },
                "manifest": {
                    "path": "deep/manifest.json",
                    "bytes": len(b"manifest"),
                    "sha256": hashlib.sha256(b"manifest").hexdigest(),
                },
            },
        },
        "effective_config_sha256": configs,
        "execution_protocol": {"executions": executions},
    }
    data = _write_json(run / "PREREGISTRATION.json", prereg)
    (run / ".fixture-configs.json").write_text(
        json.dumps({arm: value.decode() for arm, value in config_bytes.items()}), encoding="utf-8"
    )
    return run, hashlib.sha256(data).hexdigest()


def _fake_arm_runner(run: Path, *, mismatch: str | None = None):
    configs = json.loads((run / ".fixture-configs.json").read_text())
    calls: list[str] = []

    def runner(argv: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        arm = argv[argv.index("--arm-name") + 1]
        final = Path(argv[argv.index("--final-dir") + 1])
        key = generation.FROZEN_EXECUTIONS[len(calls)][0]
        calls.append(key)
        final.mkdir(parents=True)
        plans = final / "twin_plans"
        plans.mkdir()
        header = b"id,dataset,row_type,node_id,t,z,y,x,source_id,target_id\n"
        offset = 0 if arm in {"baseline", "dry_run"} else 100
        rows = [
            f"{sequence},{dataset},node,{sequence + offset},0,0,0,0,-1,-1\n".encode()
            for sequence, dataset in enumerate(generation.EVAL36)
        ]
        submission = header + b"".join(rows)
        if mismatch == key:
            submission += b"drift\n"
        (final / "submission.csv").write_bytes(submission)
        stats = b"baseline-stats\n" if arm == "baseline" else b"candidate-stats\n"
        if arm == "dry_run":
            stats = b"dry-stats\n"
        (final / "run_stats.csv").write_bytes(stats)
        (final / "effective_config.json").write_bytes(configs[arm].encode())
        (final / "deepcenter_receipt.json").write_bytes(b"{}\n")
        (final / "twin_plan_manifest.json").write_bytes(b"plans\n")
        (final / "child_result.json").write_bytes(b"child\n")
        (final / "dataset_events.jsonl").write_bytes(b"events\n")
        (final / "supervisor_stdout.log.partial").write_bytes(b"")
        (final / "supervisor_stderr.log.partial").write_bytes(b"")
        for sequence, dataset in enumerate(generation.EVAL36):
            content = b"baseline-plan\n" if arm == "baseline" else f"{sequence}:{dataset}\n".encode()
            (plans / f"{sequence}.{dataset}.json").write_bytes(content)
        files = generation._tree_records(final)
        inventory = [
            {"relative_path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]} for item in files
        ]
        inventory.append({"relative_path": "twin_plans", "kind": "directory"})
        receipt = {
            "schema_version": generation.ARM_RECEIPT_SCHEMA,
            "status": "LOCAL_VALIDATION_OBSERVED_WITH_HOLDS",
            "arm_name": arm,
            "datasets": list(generation.EVAL36),
            "child": {
                "argv": list(argv),
                "environment": dict(environment),
                "child_result": {"arm_name": arm, "datasets": list(generation.EVAL36)},
            },
            "timing": {"duration_monotonic_ns": 100 + len(calls)},
            "wait4": {"authoritative_for_rss_gate": False, "ru_maxrss_normalized_bytes": 1_000},
            "events": {},
            "promotions": [],
            "artifact_inventory": sorted(inventory, key=lambda item: item["relative_path"]),
            "publication": {},
            "holds": list(generation.UNRESOLVED_PRODUCTION_HOLDS[:6]),
            "success_scope": "LOCAL_VALIDATION_ONLY_NOT_PRODUCTION_PERMISSION",
            "claims": {},
        }
        _write_json(final / "arm_receipt.json", receipt)
        return subprocess.CompletedProcess(argv, 0, "{}\n", "")

    return runner, calls


def test_frozen_dataset_and_execution_order() -> None:
    assert generation.EVAL36 == generation.EVAL12 + generation.EVAL24
    assert len(generation.EVAL36) == len(set(generation.EVAL36)) == 36
    assert not (set(generation.EVAL36) & generation.PUBLIC_FOUR)
    assert [(key, arm) for key, arm, _ in generation.FROZEN_EXECUTIONS] == [
        ("safety_dry_run", "dry_run"),
        ("baseline_ab", "baseline"),
        ("candidate_ab", "candidate"),
        ("candidate_ba", "candidate"),
        ("baseline_ba", "baseline"),
    ]


def test_atomic_publication_refuses_clobber(tmp_path: Path) -> None:
    target = tmp_path / "artifact.json"
    generation._write_new_atomic(target, b"first\n")
    with pytest.raises(generation.GenerationFailure, match="refusing to replace") as caught:
        generation._write_new_atomic(target, b"second\n")
    assert caught.value.code == "OUTPUT_COLLISION"
    assert target.read_bytes() == b"first\n"


def test_inventory_detects_equal_size_drift(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "x").write_bytes(b"one")
    inventory_path = tmp_path / "inventory.json"
    _write_json(inventory_path, _inventory(root, "raw_geff"))
    (root / "x").write_bytes(b"two")
    with pytest.raises(generation.GenerationFailure) as caught:
        generation._verify_inventory(root, inventory_path, "raw_geff")
    assert caught.value.code == "INPUT_DRIFT"


def test_public_four_and_gt_capabilities_are_rejected() -> None:
    with pytest.raises(generation.GenerationFailure) as public:
        generation._reject_forbidden_content({"dataset": "44b6_0113de3b"}, "fixture")
    assert public.value.code == "PUBLIC_FOUR_CONTAMINATION"
    with pytest.raises(generation.GenerationFailure) as gt:
        generation._reject_forbidden_content(["/private/gt/data.geff"], "fixture")
    assert gt.value.code == "GT_PATH_VISIBLE"


def test_sensitive_inherited_fd_is_rejected(tmp_path: Path) -> None:
    fd_root = tmp_path / "fds"
    fd_root.mkdir()
    (fd_root / "0").symlink_to("/dev/null")
    (fd_root / "9").symlink_to("/private/gt/eval.geff")
    with pytest.raises(generation.GenerationFailure) as caught:
        generation._audit_sensitive_fds(fd_root)
    assert caught.value.code == "GT_PATH_VISIBLE"


def test_well_shaped_but_skeletal_public_four_pass_is_rejected(tmp_path: Path) -> None:
    receipt = tmp_path / "parity.json"
    (tmp_path / "source.py").write_bytes(b"source\n")
    source = {
        "superproject_commit": "a" * 40,
        "git_tree_oid": "b" * 40,
        "official": {"gitlink": "c" * 40, "head": "c" * 40},
    }
    _write_json(
        receipt,
        {
            "schema_version": generation.E23_PARITY_RECEIPT_SCHEMA,
            "status": "PASS",
            "created_utc": "2026-09-04T00:00:00Z",
            "source": {
                "commit": "a" * 40,
                "git_tree_oid": "b" * 40,
                "tracked_tree_clean": True,
                "official_gitlink": "c" * 40,
                "official_head": "c" * 40,
                "official_clean": True,
                "files": [],
            },
            "command": {"argv": ["verify"], "cwd": "."},
            "environment": {"PYTHONHASHSEED": "0"},
            "inputs": {"dataset": "44b6_0113de3b"},
            "references": {"hash": "d" * 64},
            "outputs": {"hash": "e" * 64},
            "checks": {"parity": True},
        },
    )
    with pytest.raises(generation.GenerationFailure) as caught:
        generation._receipt_ref(
            receipt,
            tmp_path,
            "parity",
            generation.E23_PARITY_RECEIPT_SCHEMA,
            source,
        )
    assert caught.value.code == "PREREQUISITE_SCHEMA"


def test_arbitrary_pass_receipt_is_rejected(tmp_path: Path) -> None:
    receipt = tmp_path / "fake.json"
    _write_json(receipt, {"status": "PASS"})
    with pytest.raises(generation.GenerationFailure) as caught:
        generation._receipt_ref(
            receipt,
            tmp_path,
            "parity",
            generation.E23_PARITY_RECEIPT_SCHEMA,
            {"superproject_commit": "a" * 40, "git_tree_oid": "b" * 40, "official": {}},
        )
    assert caught.value.code == "PREREQUISITE_NOT_PASS"


def test_target_resource_ref_missing_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    _write_json(
        target,
        {
            "schema_version": generation.TARGET_RESOURCE_SCHEMA,
            "declared_ram_bytes": 1,
            "declared_wall_seconds": 1,
            "source_snapshot": {"path": "missing.json", "bytes": 0, "sha256": "0" * 64},
        },
    )
    with pytest.raises(generation.GenerationFailure):
        generation._target_resources(target, tmp_path)


def test_ready_allows_distinct_clean_image_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ready, import_receipt, view = _tiny_ready_fixture(tmp_path, monkeypatch)
    ref, records = generation._image_ready_ref(ready, tmp_path, view, import_receipt)
    assert len(records) == 1_530
    assert ref["source_data_root_identity"] != ref["image_view_identity"]


def test_ready_has_no_wall_clock_ttl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ready, import_receipt, view = _tiny_ready_fixture(tmp_path, monkeypatch)
    value = json.loads(ready.read_bytes())
    value["created_utc"] = (
        (dt.datetime.now(dt.UTC) - dt.timedelta(days=2)).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    data = generation.canonical_json_bytes(value)
    ready.write_bytes(data)
    monkeypatch.setattr(generation, "CANONICAL_READY_SHA256", hashlib.sha256(data).hexdigest())
    generation._image_ready_ref(ready, tmp_path, view, import_receipt)


def test_ready_rejects_copied_receipt_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ready, import_receipt, view = _tiny_ready_fixture(tmp_path, monkeypatch)
    copied = tmp_path / "outputs/local/eval36_image_ready/copied/READY.json"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(ready.read_bytes())
    (copied.parent / "IMAGE_CONTENT_INVENTORY.json").write_bytes(
        (ready.parent / "IMAGE_CONTENT_INVENTORY.json").read_bytes()
    )
    with pytest.raises(generation.GenerationFailure) as caught:
        generation._image_ready_ref(copied, tmp_path, view, import_receipt)
    assert caught.value.code == "IMAGE_READY_AUTHORITY"


@pytest.mark.parametrize("target_name", ["READY.json", "IMAGE_CONTENT_INVENTORY.json", "import"])
def test_ready_rejects_altered_authority_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_name: str
) -> None:
    ready, import_receipt, view = _tiny_ready_fixture(tmp_path, monkeypatch)
    target = import_receipt if target_name == "import" else ready.parent / target_name
    data = target.read_bytes()
    target.write_bytes(data[:-1] + (b" " if data[-1:] != b" " else b"\n"))
    with pytest.raises(generation.GenerationFailure):
        generation._image_ready_ref(ready, tmp_path, view, import_receipt)


def test_ready_rejects_mixed_image_view(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ready, import_receipt, view = _tiny_ready_fixture(tmp_path, monkeypatch)
    (view / "unexpected.geff").mkdir()
    with pytest.raises(generation.GenerationFailure) as caught:
        generation._image_ready_ref(ready, tmp_path, view, import_receipt)
    assert caught.value.code in {"IMAGE_VIEW_MIXED", "IMAGE_READY_DRIFT"}


def test_ready_rejects_equal_size_content_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ready, import_receipt, view = _tiny_ready_fixture(tmp_path, monkeypatch)
    target = next(path for path in view.rglob("*") if path.is_file())
    target.write_bytes(b"b")
    with pytest.raises(generation.GenerationFailure) as caught:
        generation._image_ready_ref(ready, tmp_path, view, import_receipt)
    assert caught.value.code == "IMAGE_READY_DRIFT"


def test_ready_rejects_same_source_and_snapshot_inode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ready, import_receipt, view = _tiny_ready_fixture(tmp_path, monkeypatch)
    value = json.loads(ready.read_bytes())
    info = view.stat()
    value["data_root_identity"] = {"device": info.st_dev, "inode": info.st_ino}
    core = {key: item for key, item in value.items() if key not in {"created_utc", "ready_content_sha256"}}
    value["ready_content_sha256"] = hashlib.sha256(generation.canonical_json_bytes(core)).hexdigest()
    data = generation.canonical_json_bytes(value)
    ready.write_bytes(data)
    monkeypatch.setattr(generation, "CANONICAL_READY_CONTENT_SHA256", value["ready_content_sha256"])
    monkeypatch.setattr(generation, "CANONICAL_READY_SHA256", hashlib.sha256(data).hexdigest())
    with pytest.raises(generation.GenerationFailure) as caught:
        generation._image_ready_ref(ready, tmp_path, view, import_receipt)
    assert caught.value.code == "IMAGE_VIEW_NOT_ISOLATED"


def test_typed_graph_preserves_noncontiguous_integer_ids(tmp_path: Path) -> None:
    submission = tmp_path / "submission.csv"
    submission.write_text(
        "id,dataset,row_type,node_id,t,z,y,x,source_id,target_id\n"
        "7,d,node,42,0,1,2,3,-1,-1\n"
        "8,d,node,99,1,4,5,6,-1,-1\n"
        "123,d,edge,-1,-1,-1,-1,-1,42,99\n",
        encoding="utf-8",
    )
    graphs, counts = generation._submission_graph_value(submission)
    assert graphs == {"d": {"nodes": [[42, 0, 1, 2, 3], [99, 1, 4, 5, 6]], "edges": [[123, 42, 99]]}}
    assert counts == {"d": (2, 1, 0)}
    assert all(type(value) is int for record in graphs["d"]["nodes"] for value in record)


def test_typed_graph_rejects_decimal_coordinate_and_id_changes_hash(tmp_path: Path) -> None:
    integer = tmp_path / "integer.csv"
    decimal = tmp_path / "decimal.csv"
    changed = tmp_path / "changed.csv"
    body = (
        "id,dataset,row_type,node_id,t,z,y,x,source_id,target_id\n"
        "0,d,node,42,0,{z},2,3,-1,-1\n"
        "1,d,node,{node},1,4,5,6,-1,-1\n"
        "2,d,edge,-1,-1,-1,-1,-1,42,{node}\n"
    )
    integer.write_text(body.format(z="1", node="99"), encoding="utf-8")
    decimal.write_text(body.format(z="1.0", node="99"), encoding="utf-8")
    changed.write_text(body.format(z="1", node="100"), encoding="utf-8")
    with pytest.raises(generation.GenerationFailure) as caught:
        generation._submission_graph_value(decimal)
    assert caught.value.code == "TYPED_GRAPH_NONINTEGER"
    assert generation._submission_graph_evidence(integer)[0] != generation._submission_graph_evidence(changed)[0]


@pytest.mark.parametrize("mutation", ["extra", "reordered", "missing_env", "wrong_executable"])
def test_prerequisite_command_and_environment_are_exact(mutation: str) -> None:
    argv, environment = generation._expected_prerequisite_command(generation.E23_PARITY_RECEIPT_SCHEMA)
    value: dict[str, object] = {"command": {"argv": list(argv), "cwd": "."}, "environment": dict(environment)}
    if mutation == "extra":
        value["command"]["argv"].append("--unexpected")
    elif mutation == "reordered":
        value["command"]["argv"][0:2] = reversed(value["command"]["argv"][0:2])
    elif mutation == "missing_env":
        value["environment"].pop("CUDA_VISIBLE_DEVICES")
    else:
        value["command"]["argv"][0] = "/tmp/uv"
    with pytest.raises(generation.GenerationFailure) as caught:
        generation._validate_prerequisite_command(value, generation.E23_PARITY_RECEIPT_SCHEMA, "E23")
    assert caught.value.code == "PREREQUISITE_SCHEMA"


def test_legacy_raw_provenance_uses_frozen_receipts_without_checkpoint_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt, inventory, source = _raw_provenance_fixture(tmp_path, monkeypatch)
    ref = generation._raw_provenance_ref(receipt, tmp_path, "primary", inventory, source)
    assert ref["verdict"] == "LEGACY_HISTORY_UNVERIFIED"
    assert "checkpoint" not in json.loads(receipt.read_bytes())


@pytest.mark.parametrize("mutation", ["wrong_raw", "dummy_hash", "true_only", "wrong_role"])
def test_legacy_raw_provenance_rejects_forged_linkage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    receipt, inventory, source = _raw_provenance_fixture(tmp_path, monkeypatch)
    value = json.loads(receipt.read_bytes())
    expected_role = "primary"
    if mutation == "wrong_raw":
        value["raw_root"] = "raw"
    elif mutation == "dummy_hash":
        value["known_weight_sha256"] = "0" * 64
    elif mutation == "true_only":
        value = {"schema_version": generation.RAW_PROVENANCE_SCHEMA, "status": "PASS", "checks": {"ok": True}}
    else:
        expected_role = "secondary"
    _write_json(receipt, value)
    with pytest.raises(generation.GenerationFailure):
        generation._raw_provenance_ref(receipt, tmp_path, expected_role, inventory, source)


def test_source_dirty_fails_before_hashing_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def git(_root: Path, *args: str) -> str:
        if args[:2] == ("rev-parse", "HEAD"):
            return "a" * 40
        if args[:2] == ("rev-parse", "HEAD^{tree}"):
            return "b" * 40
        if args[:2] == ("status", "--porcelain=v1"):
            return " M AGENTS.md"
        raise AssertionError(args)

    monkeypatch.setattr(generation, "_run_git", git)
    with pytest.raises(generation.GenerationFailure) as caught:
        generation._source_binding(tmp_path)
    assert caught.value.code == "SOURCE_DIRTY"


def test_fake_runner_seals_five_arm_hold_but_never_feasibility_pass(tmp_path: Path) -> None:
    run, prereg_sha = _prereg_fixture(tmp_path)
    runner, calls = _fake_arm_runner(run)
    result = generation.generate(run, prereg_sha, repo_root=tmp_path, arm_runner=runner)
    assert calls == [item[0] for item in generation.FROZEN_EXECUTIONS]
    assert result.status == "HOLD"
    assert result.code == "GENERATION_COMPLETE_WITH_UNRESOLVED_HOLDS"
    assert "HOLD_TEST_RUNNER" in result.holds
    assert result.generation_manifest_sha256 is not None
    assert not (run / "feasibility" / "FEASIBILITY_PASS.json").exists()
    verdict = json.loads(result.hold_path.read_bytes())
    assert verdict["feasibility_pass_published"] is False
    manifest = json.loads((run / "generation" / "ARTIFACT_MANIFEST.json").read_bytes())
    assert manifest["claims"]["label_blind_generation_complete"] is False
    assert manifest["claims"]["production_generation_sealed"] is False
    assert {item["path"] for item in manifest["artifact_inventory"]} >= {
        "canonical/baseline/typed_graph.json",
        "canonical/candidate/typed_graph.json",
    }
    assert set(manifest["canonical_typed_graphs"]) == {"baseline", "candidate"}


def test_replay_mismatch_is_terminal_hold(tmp_path: Path) -> None:
    run, prereg_sha = _prereg_fixture(tmp_path)
    runner, _ = _fake_arm_runner(run, mismatch="candidate_ba")
    result = generation.generate(run, prereg_sha, repo_root=tmp_path, arm_runner=runner)
    assert result.code == "DETERMINISTIC_REPLAY_MISMATCH"
    assert result.generation_manifest_sha256 is None
    assert not (run / "feasibility" / "FEASIBILITY_PASS.json").exists()


def test_existing_terminal_verdict_blocks_regeneration(tmp_path: Path) -> None:
    run, prereg_sha = _prereg_fixture(tmp_path)
    runner, _ = _fake_arm_runner(run)
    generation.generate(run, prereg_sha, repo_root=tmp_path, arm_runner=runner)
    with pytest.raises(generation.GenerationFailure) as caught:
        generation.generate(run, prereg_sha, repo_root=tmp_path, arm_runner=runner)
    assert caught.value.code == "GENERATION_LOCKED"


def test_hold_publication_failure_cannot_turn_into_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run, prereg_sha = _prereg_fixture(tmp_path)
    runner, _ = _fake_arm_runner(run, mismatch="candidate_ba")
    real_write = generation._write_new_atomic

    def fail_verdict(path: Path, data: bytes) -> None:
        if path.name == "VERDICT.json":
            raise OSError("injected publication failure")
        real_write(path, data)

    monkeypatch.setattr(generation, "_write_new_atomic", fail_verdict)
    with pytest.raises(OSError, match="injected publication failure"):
        generation.generate(run, prereg_sha, repo_root=tmp_path, arm_runner=runner)
    assert not (run / "feasibility" / "FEASIBILITY_PASS.json").exists()


def test_generation_cli_has_no_gt_metric_or_runner_override() -> None:
    path = Path(__file__).parents[1] / "scripts" / "experiments" / "st_r3" / "st_r3_generate.py"
    source = path.read_text(encoding="utf-8")
    assert "--gt" not in source
    assert "--metric" not in source
    assert "--runner" not in source


def test_preregister_cli_requires_artifact_refs_not_free_gt_hash() -> None:
    source = (Path(__file__).parents[1] / "scripts" / "experiments" / "st_r3" / "st_r3_preregister.py").read_text(encoding="utf-8")
    assert "--gt-inventory-sha256" not in source
    assert '"--gt-inventory"' in source
    assert '"--primary-raw-provenance-receipt"' in source
    assert '"--secondary-raw-provenance-receipt"' in source
    assert '"--image-import-receipt"' in source


def test_official_reviewed_oid_is_hard_pinned() -> None:
    assert generation.OFFICIAL_REVIEWED_OID == "075fc5f5a52d11077f9dc2b074644618f26939e2"


def test_ready_and_raw_authorities_are_hard_pinned() -> None:
    assert generation.CANONICAL_READY_PATH.endswith("20260904T220902+0900_2877f28_direct/READY.json")
    assert generation.CANONICAL_READY_SHA256 == "8a0a36d393ecc11a0532bc12011257a4c012cb7361d4346941b4d1211c58c73e"
    assert generation.CANONICAL_READY_CONTENT_SHA256 == (
        "2211abec541bc31df2f31aacf1575c065025f0aa143147c3df07b4ece2b3214a"
    )
    assert generation.CANONICAL_IMAGE_INVENTORY_SHA256 == (
        "efe652bd8e8a791bd51cf3b980ae87fe0fe2205ec52d2f3639717cd2b0550714"
    )
    assert generation.CANONICAL_RAW_ROOT.endswith("unet_transformer_val/split_0")
    assert generation.CANONICAL_RAW_RECORDS_SHA256 == (
        "d49541301e7b76afe65a5ba61f5d8f8b01c14c39c256455b7cdd5af9a7564cbb"
    )
    assert "HOLD_RAW_PROVENANCE_UNVERIFIED" in generation.UNRESOLVED_PRODUCTION_HOLDS


def test_opaque_gt_inventory_rejects_incomplete_root_set(tmp_path: Path) -> None:
    artifact = tmp_path / "inventory.json"
    _write_json(
        artifact,
        {
            "schema_version": generation.GT_INVENTORY_SCHEMA,
            "stems": list(generation.EVAL36),
            "records": [{"path": "x/44b6_12dfb391.geff/zarr.json", "bytes": 1, "sha256": "0" * 64}],
        },
    )
    with pytest.raises(generation.GenerationFailure) as caught:
        generation._gt_inventory_ref(artifact, tmp_path)
    assert caught.value.code == "GT_INVENTORY_SCHEMA"


def test_generation_module_imports_no_evaluator_or_metric() -> None:
    source = (Path(__file__).parents[1] / "src" / "biohub" / "st_r3_generation.py").read_text(encoding="utf-8")
    imported = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not any(name == "biohub.evaluate" or name.startswith("tracking_cellmot") for name in imported)
