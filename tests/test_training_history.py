from __future__ import annotations

import base64
import copy
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from biohub.training_history import (
    CHECKPOINT_FORMAT,
    DuplicateKeyError,
    GateValidationError,
    HistoryWriter,
    TrainingHistoryError,
    atomic_publish_file,
    atomic_write_json,
    canonical_json_bytes,
    canonical_sha256,
    compute_degradation,
    execution_config_sha256,
    select_best,
    sha256_bytes,
    sha256_file,
    strict_json_load,
    strict_json_loads,
    strict_jsonl_load,
    validate_resume_metadata,
    validate_training_run,
    validate_warm_start,
    verify_training_run,
)

ZERO_SHA = "0" * 64
STATE_KEYS = [{"name": "layer.weight", "shape": [2, 2], "dtype": "float32"}]
MODEL_STATE = [{"name": "layer.weight", "shape": [2, 2], "dtype": "float32", "values": [0.1, 0.2, 0.3, 0.4]}]


def _checkpoint(kind: str, run_id: str, epoch: int, step: int) -> dict:
    return {
        "format": CHECKPOINT_FORMAT,
        "schema_version": 1,
        "kind": kind,
        "run_id": run_id,
        "epoch": epoch,
        "global_step": step,
        "state_keys": copy.deepcopy(STATE_KEYS),
        "model_state": copy.deepcopy(MODEL_STATE),
    }


def _state_payload(value: object) -> dict:
    return {"state_dict": value, "sha256": canonical_sha256(value)}


def _rng_payload(value: bytes) -> dict:
    return {
        "encoding": "base64",
        "value": base64.b64encode(value).decode("ascii"),
        "sha256": sha256_bytes(value),
    }


def _component(value: float, denominator: int = 10) -> dict:
    return {
        "value": value,
        "numerator": value * denominator,
        "denominator": denominator,
        "reduction": "sum_over_examples",
    }


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.unlink(missing_ok=True)
    atomic_publish_file(path, b"".join(canonical_json_bytes(row) for row in rows))


def _replace_json(path: Path, value: object) -> None:
    path.unlink(missing_ok=True)
    atomic_write_json(path, value)


def _replace_bytes(path: Path, value: bytes) -> None:
    path.unlink(missing_ok=True)
    atomic_publish_file(path, value)


def _refresh_artifacts(root: Path, verdict: str = "PASS") -> None:
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path != root / "ARTIFACT_MANIFEST.json":
            files.append(
                {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            )
    run_id = strict_json_load(root / "run_manifest.json")["run_id"]
    _replace_json(
        root / "ARTIFACT_MANIFEST.json",
        {"schema_version": 1, "run_id": run_id, "verdict": verdict, "files": files},
    )


def _valid_run(root: Path, *, values: list[float] | None = None, run_id: str = "run-001") -> tuple[dict, list[dict]]:
    values = values or [0.8, 0.6, 0.7]
    (root / "checkpoints").mkdir(parents=True)
    (root / "provenance").mkdir()
    atomic_publish_file(root / "provenance/code-tree.json", b'{"tree":"pinned"}\n')
    atomic_publish_file(root / "provenance/input.json", b'{"input":"pinned"}\n')
    atomic_publish_file(
        root / "provenance/per-video.json",
        b'{"values":{"val-a":0.6,"val-b":0.65},"uncertainty":{"upper":0.1}}\n',
    )

    best_epoch = min(range(len(values)), key=values.__getitem__) + 1
    atomic_write_json(root / "checkpoints/best.pt", _checkpoint("best", run_id, best_epoch, best_epoch * 2))
    atomic_write_json(root / "checkpoints/last.pt", _checkpoint("last", run_id, len(values), len(values) * 2))
    best_sha = sha256_file(root / "checkpoints/best.pt")
    last_sha = sha256_file(root / "checkpoints/last.pt")

    split = {
        "train": {
            "stems": ["train-a"],
            "videos": 1,
            "examples": 20,
            "batches": 2,
            "lineages": {"44b6": 10, "6bba": 10},
            "example_ids": [f"train-{index}" for index in range(20)],
        },
        "validation": {
            "stems": ["val-a", "val-b"],
            "videos": 2,
            "examples": 10,
            "batches": 1,
            "lineages": {"44b6": 5, "6bba": 5},
            "example_ids": [f"val-{index}" for index in range(10)],
        },
    }
    configs = {
        "model_config": {"name": "tiny"},
        "model_state_schema": copy.deepcopy(STATE_KEYS),
        "loss_config": {"w_edge": 1.0},
        "optimizer_config": {"name": "sgd"},
        "scheduler_config": {"name": "constant"},
    }
    input_sha = sha256_file(root / "provenance/input.json")
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "purpose": "candidate",
        "run_kind": "single_split",
        "phase": "train",
        "fold_id": None,
        "git_sha": "abc123",
        "code_tree_sha256": sha256_file(root / "provenance/code-tree.json"),
        "config_sha256": ZERO_SHA,
        "cli": "python train.py",
        "allowed_environment": {"CUBLAS_WORKSPACE_CONFIG": ":4096:8"},
        **{key: value for key, value in configs.items() if key != "model_state_schema"},
        "seed": 7,
        "dependencies": {"python": "3.12"},
        "hardware": {"device": "cpu"},
        "input_manifest_sha256": input_sha,
        "split_sha256": canonical_sha256(split),
        "warm_start_checkpoint_sha256": None,
        "selector": {
            "kind": "validation_loss",
            "field": "val.losses.total_loss.value",
            "direction": "min",
            "tie_rule": "earliest",
        },
        "loss_component_profile": {
            "train": {
                "edge_loss": {
                    "required": True,
                    "reduction": "sum_over_examples",
                    "denominator_source": "examples",
                },
                "total_loss": {
                    "required": True,
                    "reduction": "sum_over_examples",
                    "denominator_source": "examples",
                },
                "optional_loss": {
                    "required": False,
                    "reduction": "sum_over_examples",
                    "denominator_source": "examples",
                },
            },
            "val": {
                "edge_loss": {
                    "required": True,
                    "reduction": "sum_over_examples",
                    "denominator_source": "examples",
                },
                "total_loss": {
                    "required": True,
                    "reduction": "sum_over_examples",
                    "denominator_source": "examples",
                },
                "optional_loss": {
                    "required": False,
                    "reduction": "sum_over_examples",
                    "denominator_source": "examples",
                },
            },
        },
        "nullable_loss_components": {
            "train": {"optional_loss": {"reason": "NO_PAIRS", "zero_count": 0}},
            "val": {"optional_loss": {"reason": "NO_PAIRS", "zero_count": 0}},
        },
        "total_loss": {
            "name": "total_loss",
            "components": ["edge_loss"],
            "formula": "edge_loss * w_edge",
            "weights": {"w_edge": 1.0},
            "aggregation": {
                "denominator_source": "examples",
                "numerator_formula": "edge_loss_numerator * w_edge",
                "reduction": "sum_over_examples",
            },
        },
        "validation_snapshot": {
            "example_ids": [f"val-{index}" for index in range(10)],
            "input_manifest_sha256": input_sha,
            "split_sha256": canonical_sha256(split),
            "preprocessing_config": {"normalize": True},
            "seed": 7,
            "allowed_environment": {"CUBLAS_WORKSPACE_CONFIG": ":4096:8"},
            "device": "cpu",
            "dtype": "float32",
            "framework_version": "test-1",
            "shuffle": False,
            "augmentation": False,
        },
        "acceptance_thresholds": {
            "zero_best_absolute_degradation": 0.01,
            "primary": {
                "field": "val.losses.total_loss.value",
                "direction": "min",
                "baseline": 0.7,
                "margin": 0.05,
                "observed_source": "history_best",
            },
            "noninferiority": {
                "dice": {
                    "field": "task_metrics.dice",
                    "direction": "max",
                    "baseline": 0.75,
                    "limit": 0.05,
                    "observed_source": "best_epoch",
                }
            },
            "lineage_noninferiority": {
                "44b6": {
                    "field": "val_by_lineage.44b6.loss",
                    "direction": "min",
                    "baseline": 0.7,
                    "limit": 0.1,
                    "observed_source": "best_epoch",
                },
                "6bba": {
                    "field": "val_by_lineage.6bba.loss",
                    "direction": "min",
                    "baseline": 0.7,
                    "limit": 0.1,
                    "observed_source": "best_epoch",
                },
            },
            "per_video": {
                "path": "provenance/per-video.json",
                "sha256": sha256_file(root / "provenance/per-video.json"),
                "direction": "min",
                "baseline": 0.7,
                "limit": 0.1,
                "observed_source": "artifact_values",
                "uncertainty_field": "uncertainty.upper",
                "uncertainty_limit": 0.2,
                "min_qualifying_videos": 2,
            },
        },
        "split": split,
        "final_selection": {
            "epoch": best_epoch,
            "selector_value": values[best_epoch - 1],
            "checkpoint_sha256": best_sha,
        },
        "degradation": compute_degradation(values, values, direction="min", absolute_warning_threshold=0.01),
        "model_state_schema": STATE_KEYS,
        "hash_sources": {
            "code_tree_sha256": "provenance/code-tree.json",
            "input_manifest_sha256": "provenance/input.json",
        },
        "sampler": {"mode": "serialized"},
        "gradient": {"clip_threshold": 3.0},
        "resume_validation_contract": {
            "loss": "val.losses.total_loss.value",
            "count": "val_examples",
            "ids": "$validation_snapshot_ids",
        },
        "checkpoint_refs": {},
    }
    manifest["degradation"]["flags"] = manifest["degradation"].pop("warnings")
    manifest["config_sha256"] = execution_config_sha256(manifest)
    _replace_json(root / "run_manifest.json", manifest)

    rows = []
    running_best = math.inf
    for epoch, value in enumerate(values, 1):
        improved = value < running_best
        running_best = min(running_best, value)
        checkpoint = best_sha if epoch == best_epoch else last_sha if epoch == len(values) else None
        rows.append(
            {
                "schema_version": 1,
                "run_id": run_id,
                "purpose": "candidate",
                "run_kind": "single_split",
                "phase": "train",
                "fold_id": None,
                "epoch": epoch,
                "global_step": epoch * 2,
                "lr": 0.01,
                "epoch_seconds": 1.0,
                "train_batches": 2,
                "train_examples": 20,
                "val_batches": 1,
                "val_examples": 10,
                "train": {
                    "losses": {
                        "edge_loss": _component(value + 0.1, 20),
                        "total_loss": _component(value + 0.1, 20),
                        "optional_loss": None,
                    }
                },
                "val": {
                    "losses": {"edge_loss": _component(value), "total_loss": _component(value), "optional_loss": None}
                },
                "val_by_lineage": {
                    "44b6": {"loss": value, "examples": 5},
                    "6bba": {"loss": value, "examples": 5},
                },
                "task_metrics": {"dice": 0.8},
                "grad_norm_pre_clip": {
                    "max": 2.0,
                    "mean": 1.5,
                    "last": 1.0,
                    "checked_steps": 2,
                    "clip_threshold": 3.0,
                },
                "nonfinite_count": 0,
                "selector_value": value,
                "best_so_far": improved,
                "checkpoint_sha256": checkpoint,
            }
        )
    _write_rows(root / "history.jsonl", rows)
    snapshot_sha = canonical_sha256(manifest["validation_snapshot"])
    receipt = {
        "schema_version": 1,
        "run_id": run_id,
        "epoch": len(rows),
        "global_step": len(rows) * 2,
        "validation_snapshot_sha256": snapshot_sha,
        "expected": {"loss": values[-1], "count": 10, "ids": manifest["validation_snapshot"]["example_ids"]},
        "actual": {"loss": values[-1], "count": 10, "ids": manifest["validation_snapshot"]["example_ids"]},
        "tolerances": {"loss": {"rtol": 1e-5, "atol": 1e-7}},
    }
    atomic_write_json(root / "provenance/resume-validation.json", receipt)
    resume = _checkpoint("resume", run_id, len(rows), len(rows) * 2)
    resume.update(
        {
            "config_sha256": manifest["config_sha256"],
            "input_manifest_sha256": input_sha,
            "split_sha256": manifest["split_sha256"],
            "code_tree_sha256": manifest["code_tree_sha256"],
            "warm_start_checkpoint_sha256": None,
            "history_prefix_sha256": sha256_file(root / "history.jsonl"),
            "next_epoch": len(rows) + 1,
            "next_global_step": len(rows) * 2 + 1,
            "validation_snapshot_sha256": snapshot_sha,
            "validation_receipt": {
                "path": "provenance/resume-validation.json",
                "sha256": sha256_file(root / "provenance/resume-validation.json"),
            },
            "state": {
                "model": {"type": "model_state_dict", "payload": _state_payload(MODEL_STATE)},
                "optimizer": {
                    "type": "optimizer_state_dict",
                    "payload": _state_payload({"param_groups": [{"lr": 0.01}], "state": {"0": {"momentum": 0.2}}}),
                },
                "scheduler": {
                    "type": "scheduler_state_dict",
                    "payload": _state_payload({"last_epoch": len(rows), "step_count": len(rows)}),
                },
                "scaler": {
                    "type": "amp_scaler_state",
                    "payload": _state_payload({"scale": 1.0, "growth_tracker": 3}),
                },
                "rng": {
                    "python": _rng_payload(b"python-state"),
                    "numpy": _rng_payload(b"numpy-state"),
                    "torch_cpu": _rng_payload(b"torch-cpu-state"),
                    "torch_cuda": _rng_payload(b"torch-cuda-state"),
                },
                "sampler": {
                    "type": "sampler_state",
                    "payload": _state_payload({"epoch": len(rows), "index": 0, "order": list(range(20))}),
                },
                "best_state": {
                    "epoch": best_epoch,
                    "selector_value": values[best_epoch - 1],
                    "checkpoint_sha256": best_sha,
                },
            },
        }
    )
    atomic_write_json(root / "checkpoints/resume.pt", resume)
    manifest["checkpoint_refs"] = {
        relative: sha256_file(root / relative)
        for relative in ("checkpoints/best.pt", "checkpoints/last.pt", "checkpoints/resume.pt")
    }
    _replace_json(root / "run_manifest.json", manifest)
    _refresh_artifacts(root)
    return manifest, rows


def _rewrite(root: Path, manifest: dict, rows: list[dict], *, verdict: str = "PASS") -> None:
    manifest["config_sha256"] = execution_config_sha256(manifest)
    _replace_json(root / "run_manifest.json", manifest)
    _write_rows(root / "history.jsonl", rows)
    resume_path = root / "checkpoints/resume.pt"
    resume = strict_json_load(resume_path)
    resume["history_prefix_sha256"] = sha256_file(root / "history.jsonl")
    for field in (
        "config_sha256",
        "input_manifest_sha256",
        "split_sha256",
        "code_tree_sha256",
        "warm_start_checkpoint_sha256",
    ):
        resume[field] = manifest[field]
    resume["validation_snapshot_sha256"] = (
        None if manifest.get("validation_snapshot") is None else canonical_sha256(manifest["validation_snapshot"])
    )
    receipt_path = root / resume["validation_receipt"]["path"]
    receipt = strict_json_load(receipt_path)
    receipt.update(
        run_id=manifest["run_id"],
        epoch=resume["epoch"],
        global_step=resume["global_step"],
        validation_snapshot_sha256=resume["validation_snapshot_sha256"],
    )
    expected_receipt = {}
    for name, source in manifest["resume_validation_contract"].items():
        if source == "$validation_snapshot_ids":
            expected_receipt[name] = manifest["validation_snapshot"]["example_ids"]
        elif source == "$train_example_ids":
            expected_receipt[name] = manifest["split"]["train"]["example_ids"]
        else:
            value = rows[-1]
            try:
                for part in source.split("."):
                    value = value[part]
            except (KeyError, TypeError):
                value = receipt["expected"].get(name)
            expected_receipt[name] = value
    receipt["expected"] = expected_receipt
    receipt["actual"] = copy.deepcopy(expected_receipt)
    _replace_json(receipt_path, receipt)
    resume["validation_receipt"]["sha256"] = sha256_file(receipt_path)
    final = manifest.get("final_selection", {})
    resume["state"]["best_state"] = {
        "epoch": final.get("fixed_epoch", final.get("epoch")),
        "selector_value": final.get("selector_value"),
        "checkpoint_sha256": final.get("checkpoint_sha256"),
    }
    _replace_json(resume_path, resume)
    checkpoint_names = ["last.pt", "resume.pt"]
    if manifest.get("run_kind") == "final_refit":
        checkpoint_names.append("fixed_epoch.pt")
    else:
        checkpoint_names.append("best.pt")
        if (root / "checkpoints/min_val_loss.pt").is_file():
            checkpoint_names.append("min_val_loss.pt")
    manifest["checkpoint_refs"] = {
        f"checkpoints/{name}": sha256_file(root / "checkpoints" / name) for name in checkpoint_names
    }
    _replace_json(root / "run_manifest.json", manifest)
    _refresh_artifacts(root, verdict)


def test_valid_training_run_and_safe_checkpoint_envelopes(tmp_path: Path) -> None:
    _valid_run(tmp_path)
    report = verify_training_run(tmp_path)
    assert report["verdict"] == "PASS", report
    assert report["details"]["best_epoch"] == 2


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_strict_json_rejects_nonfinite(token: str) -> None:
    with pytest.raises(TrainingHistoryError, match="non-finite"):
        strict_json_loads(f'{{"value":{token}}}')


def test_strict_json_and_jsonl_reject_duplicate_keys_and_blank_lines(tmp_path: Path) -> None:
    with pytest.raises(DuplicateKeyError):
        strict_json_loads('{"x":1,"x":2}')
    path = tmp_path / "bad.jsonl"
    path.write_text('{"x":1}\n\n')
    with pytest.raises(TrainingHistoryError, match="blank"):
        strict_jsonl_load(path)


def test_history_writer_is_append_only_contiguous_and_resumable(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    writer = HistoryWriter(path)
    first_hash = writer.append({"epoch": 1, "global_step": 2})
    assert first_hash == sha256_file(path)
    with pytest.raises(TrainingHistoryError, match="overwrite"):
        HistoryWriter(path)
    resumed = HistoryWriter(path, resume=True, expected_prefix_sha256=sha256_file(path))
    resumed.append({"epoch": 2, "global_step": 4})
    with pytest.raises(TrainingHistoryError, match="continue"):
        resumed.append({"epoch": 4, "global_step": 6})


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda m, r: r[0].update(val_batches=0, val_examples=0), "empty validation"),
        (lambda m, r: m["split"]["validation"]["stems"].append("train-a"), "stem overlap"),
        (lambda m, r: m["split"]["validation"]["lineages"].update({"6bba": 0}), "both lineages"),
        (lambda m, r: r[0]["val"]["losses"]["edge_loss"].update(denominator=0), "denominator"),
        (lambda m, r: r[0]["val"]["losses"].pop("edge_loss"), "component set"),
        (lambda m, r: r[0]["val"]["losses"]["total_loss"].update(value=9.0), "value != numerator"),
        (lambda m, r: r[0].update(nonfinite_count=1), "nonfinite_count"),
        (lambda m, r: r[1]["grad_norm_pre_clip"].update(checked_steps=1), "checked_steps"),
        (lambda m, r: r[1].update(epoch=1), "epoch sequence"),
        (lambda m, r: r[1].update(global_step=2), "global_step"),
    ],
)
def test_mandatory_history_failures(tmp_path: Path, mutation, message: str) -> None:
    manifest, rows = _valid_run(tmp_path)
    mutation(manifest, rows)
    if "split" in message or "lineages" in message:
        manifest["split_sha256"] = canonical_sha256(manifest["split"])
        manifest["validation_snapshot"]["split_sha256"] = manifest["split_sha256"]
        resume = strict_json_load(tmp_path / "checkpoints/resume.pt")
        resume["split_sha256"] = manifest["split_sha256"]
        _replace_json(tmp_path / "checkpoints/resume.pt", resume)
    _rewrite(tmp_path, manifest, rows)
    report = verify_training_run(tmp_path)
    assert report["verdict"] == "FAIL"
    assert message in " ".join(report["errors"])


def test_optional_zero_population_must_be_null_with_reason(tmp_path: Path) -> None:
    manifest, rows = _valid_run(tmp_path)
    rows[0]["val"]["losses"]["optional_loss"] = _component(0.0, denominator=0)
    _rewrite(tmp_path, manifest, rows)
    assert verify_training_run(tmp_path)["verdict"] == "FAIL"
    manifest, rows = _valid_run(tmp_path / "ok")
    assert rows[0]["val"]["losses"]["optional_loss"] is None
    assert verify_training_run(tmp_path / "ok")["verdict"] == "PASS"


def test_total_loss_weight_and_reduction_drift_fail(tmp_path: Path) -> None:
    manifest, rows = _valid_run(tmp_path)
    manifest["total_loss"]["weights"]["w_edge"] = 2.0
    rows[0]["val"]["losses"]["edge_loss"]["reduction"] = "batch_mean"
    _rewrite(tmp_path, manifest, rows)
    errors = " ".join(verify_training_run(tmp_path)["errors"])
    assert "total-loss formula/weight mismatch" in errors
    assert "reduction differs" in errors


def test_explicit_pair_population_denominator_contract_is_supported(tmp_path: Path) -> None:
    manifest, rows = _valid_run(tmp_path)
    for side, count in (("train", 30), ("validation", 15)):
        manifest["split"][side]["denominator_counts"] = {"pairs": count}
    for side in ("train", "val"):
        for component in ("edge_loss", "total_loss"):
            manifest["loss_component_profile"][side][component]["denominator_source"] = "pairs"
    manifest["total_loss"]["aggregation"]["denominator_source"] = "pairs"
    for row in rows:
        for side, count in (("train", 30), ("val", 15)):
            for component in ("edge_loss", "total_loss"):
                loss = row[side]["losses"][component]
                loss["denominator"] = count
                loss["numerator"] = loss["value"] * count
    manifest["split_sha256"] = canonical_sha256(manifest["split"])
    manifest["validation_snapshot"]["split_sha256"] = manifest["split_sha256"]
    _rewrite(tmp_path, manifest, rows)
    assert verify_training_run(tmp_path)["verdict"] == "PASS"


def test_hash_drift_is_detected(tmp_path: Path) -> None:
    _valid_run(tmp_path)
    with (tmp_path / "history.jsonl").open("ab") as stream:
        stream.write(b" ")
    report = verify_training_run(tmp_path)
    assert report["verdict"] == "FAIL"
    assert "SHA256 mismatch" in " ".join(report["errors"])


def test_late_overfit_warns_but_uses_best_checkpoint(tmp_path: Path) -> None:
    _valid_run(tmp_path, values=[0.8, 0.5, 0.7])
    report = verify_training_run(tmp_path)
    assert report["verdict"] == "PASS"
    assert "STRONG_OVERFIT" in report["warnings"]
    assert report["details"]["best_epoch"] == 2


def test_selector_tie_keeps_earliest_and_multiple_best_flags(tmp_path: Path) -> None:
    manifest, rows = _valid_run(tmp_path, values=[0.8, 0.6, 0.6])
    assert select_best(rows, direction="min")["epoch"] == 2
    assert [row["best_so_far"] for row in rows] == [True, True, False]
    assert manifest["final_selection"]["epoch"] == 2
    assert verify_training_run(tmp_path)["verdict"] == "PASS"


def test_nonselected_checkpoint_sha_may_be_null(tmp_path: Path) -> None:
    _, rows = _valid_run(tmp_path)
    assert rows[0]["checkpoint_sha256"] is None
    assert verify_training_run(tmp_path)["verdict"] == "PASS"


def test_diagnostic_cannot_be_promoted_and_is_exempt_from_progression(tmp_path: Path) -> None:
    manifest, rows = _valid_run(tmp_path)
    manifest["purpose"] = "diagnostic"
    for row in rows:
        row["purpose"] = "diagnostic"
    _rewrite(tmp_path, manifest, rows, verdict="DIAGNOSTIC_ONLY")
    report = verify_training_run(tmp_path)
    assert report["verdict"] == "DIAGNOSTIC_ONLY"
    assert report["verdict"] != "PASS"


@pytest.mark.parametrize(
    ("losses", "ratio", "zero"),
    [([0.0, 0.0], 0.0, True), ([0.0, 0.2], None, True), ([0.5, 0.6], pytest.approx(0.2), False)],
)
def test_zero_best_loss_three_branches(losses, ratio, zero) -> None:
    result = compute_degradation(losses, losses, direction="min", absolute_warning_threshold=0.1)
    assert result["loss_degradation_ratio"] == ratio
    assert result["ZERO_BEST_LOSS"] is zero


def test_resume_history_snapshot_metric_tolerance_and_sampler(tmp_path: Path) -> None:
    manifest, rows = _valid_run(tmp_path)
    resume = strict_json_load(tmp_path / "checkpoints/resume.pt")
    rows[-1]["task_metrics"]["val_auc"] = 0.8
    manifest["resume_validation_contract"]["val_auc"] = "task_metrics.val_auc"
    resume["validation_metrics"] = {
        "loss": 0.7,
        "val_auc": 0.8,
        "count": 10,
        "ids": manifest["validation_snapshot"]["example_ids"],
    }
    validate_resume_metadata(
        manifest,
        rows,
        resume,
        validation_readback={
            "loss": 0.700004,
            "val_auc": 0.800000005,
            "count": 10,
            "ids": manifest["validation_snapshot"]["example_ids"],
        },
    )
    bad = copy.deepcopy(resume)
    bad["history_prefix_sha256"] = "f" * 64
    bad["state"].pop("sampler")
    manifest["history_prefix_sha256"] = resume["history_prefix_sha256"]
    with pytest.raises(GateValidationError) as error:
        validate_resume_metadata(manifest, rows, bad, validation_readback={"loss": 0.6})
    text = str(error.value)
    assert "history prefix" in text and "sampler" in text and "actual metrics" in text


def _warm_manifest() -> tuple[dict, dict]:
    keys = ["encoder.bias", "encoder.weight"]
    specs = {key: {"shape": [2], "dtype": "float32"} for key in keys}
    manifest = {
        "run_id": "new",
        "warm_start_checkpoint_sha256": "a" * 64,
        "warm_start": {
            "mode": "submodule_strict",
            "source_run_id": "source-run",
            "source_kind": "best",
            "optimizer_reset": True,
            "scheduler_reset": True,
            "scaler_reset": True,
            "allowed_prefixes": ["encoder."],
            "expected_keys": keys,
            "expected_keys_sha256": canonical_sha256(keys),
            "key_specs": specs,
            "new_keys": ["head.weight"],
            "new_keys_sha256": canonical_sha256(["head.weight"]),
        },
        "model_state_schema": [
            {"name": "encoder.bias", "shape": [2], "dtype": "float32"},
            {"name": "encoder.weight", "shape": [2], "dtype": "float32"},
            {"name": "head.weight", "shape": [2], "dtype": "float32"},
        ],
    }
    metadata = {
        "format": CHECKPOINT_FORMAT,
        "schema_version": 1,
        "run_id": "source-run",
        "kind": "best",
        "checkpoint_sha256": "a" * 64,
        "state_keys": [{"name": key, "shape": specs[key]["shape"], "dtype": specs[key]["dtype"]} for key in keys],
        "model_state": [
            {"name": key, "shape": specs[key]["shape"], "dtype": specs[key]["dtype"], "values": [0.1, 0.2]}
            for key in keys
        ],
    }
    return manifest, metadata


def test_submodule_and_full_strict_warm_start_contracts() -> None:
    manifest, metadata = _warm_manifest()
    validate_warm_start(manifest, metadata)
    for mutate, message in [
        (lambda m, d: d["state_keys"][0].update(shape=[3]), "shape/dtype"),
        (lambda m, d: m["warm_start"].update(allowed_prefixes=["head."]), "outside allowed prefix"),
        (lambda m, d: d["state_keys"].append({"name": "x", "shape": [], "dtype": "float32"}), "key mismatch"),
    ]:
        bad_manifest, bad_metadata = copy.deepcopy(manifest), copy.deepcopy(metadata)
        mutate(bad_manifest, bad_metadata)
        with pytest.raises(GateValidationError, match=message):
            validate_warm_start(bad_manifest, bad_metadata)
    full_manifest, full_metadata = _warm_manifest()
    full_manifest["warm_start"].update(mode="full_strict", new_keys=[])
    full_manifest["warm_start"].pop("allowed_prefixes")
    full_manifest["warm_start"].pop("new_keys_sha256")
    full_manifest["model_state_schema"] = full_metadata["state_keys"]
    validate_warm_start(full_manifest, full_metadata)


def test_validation_snapshot_and_resume_prefix_fail_closed(tmp_path: Path) -> None:
    manifest, rows = _valid_run(tmp_path)
    manifest["validation_snapshot"]["shuffle"] = True
    _rewrite(tmp_path, manifest, rows)
    report = verify_training_run(tmp_path)
    assert report["verdict"] == "FAIL"
    assert "shuffle" in " ".join(report["errors"])
    resume = strict_json_load(tmp_path / "checkpoints/resume.pt")
    resume["history_prefix_sha256"] = ZERO_SHA
    _replace_json(tmp_path / "checkpoints/resume.pt", resume)
    _refresh_artifacts(tmp_path)
    assert "history prefix" in " ".join(verify_training_run(tmp_path)["errors"])


def test_checkpoint_loader_is_safe_and_injectable(tmp_path: Path) -> None:
    _valid_run(tmp_path)
    best = tmp_path / "checkpoints/best.pt"
    best.write_bytes(b"not JSON, and must never be unpickled")
    _refresh_artifacts(tmp_path)
    report = verify_training_run(tmp_path)
    assert report["verdict"] == "FAIL"
    assert "opaque checkpoint requires" in " ".join(report["errors"])


def test_checkpoint_strict_shape_and_epoch_are_checked(tmp_path: Path) -> None:
    _valid_run(tmp_path)
    best = strict_json_load(tmp_path / "checkpoints/best.pt")
    best["epoch"] = 3
    best["state_keys"][0]["shape"] = [4, 4]
    _replace_json(tmp_path / "checkpoints/best.pt", best)
    _refresh_artifacts(tmp_path)
    errors = " ".join(verify_training_run(tmp_path)["errors"])
    assert "strict key/shape/dtype" in errors
    assert "checkpoint epoch mismatch" in errors


def test_binary_validation_and_fixed_progression_gate(tmp_path: Path) -> None:
    manifest, rows = _valid_run(tmp_path)
    manifest["task_type"] = "binary_classification"
    manifest["split"]["validation"].update(positive=0, negative=10)
    manifest["split_sha256"] = canonical_sha256(manifest["split"])
    manifest["validation_snapshot"]["split_sha256"] = manifest["split_sha256"]
    manifest["acceptance_thresholds"]["primary"]["baseline"] = 0.61
    resume = strict_json_load(tmp_path / "checkpoints/resume.pt")
    resume["split_sha256"] = manifest["split_sha256"]
    _replace_json(tmp_path / "checkpoints/resume.pt", resume)
    _rewrite(tmp_path, manifest, rows)
    errors = " ".join(verify_training_run(tmp_path)["errors"])
    assert "positive and negative" in errors
    assert "recomputed threshold" in errors


def test_wrapper_and_support_trainer_hash_drift(tmp_path: Path) -> None:
    manifest, rows = _valid_run(tmp_path)
    atomic_publish_file(tmp_path / "provenance/wrapper.py", b"wrapper\n")
    atomic_publish_file(tmp_path / "provenance/support.py", b"support\n")
    manifest["training_sources"] = {
        "wrapper": {"path": "provenance/wrapper.py", "sha256": sha256_file(tmp_path / "provenance/wrapper.py")},
        "support_trainer": {
            "path": "provenance/support.py",
            "sha256": sha256_file(tmp_path / "provenance/support.py"),
        },
    }
    _rewrite(tmp_path, manifest, rows)
    assert verify_training_run(tmp_path)["verdict"] == "PASS"
    manifest["training_sources"]["support_trainer"]["sha256"] = ZERO_SHA
    _rewrite(tmp_path, manifest, rows)
    assert "training source hash mismatch" in " ".join(verify_training_run(tmp_path)["errors"])


def test_artifact_manifest_path_and_checkpoint_hash_integrity(tmp_path: Path) -> None:
    manifest, rows = _valid_run(tmp_path)
    manifest["final_selection"]["checkpoint_sha256"] = ZERO_SHA
    _rewrite(tmp_path, manifest, rows)
    report = verify_training_run(tmp_path)
    assert "final_selection" in " ".join(report["errors"])
    artifacts = strict_json_load(tmp_path / "ARTIFACT_MANIFEST.json")
    artifacts["files"][0]["path"] = "../escape"
    _replace_json(tmp_path / "ARTIFACT_MANIFEST.json", artifacts)
    assert "unsafe artifact path" in " ".join(verify_training_run(tmp_path)["errors"])


def _final_refit(root: Path) -> tuple[dict, list[dict]]:
    manifest, rows = _valid_run(root)
    atomic_write_json(root / "checkpoints/fixed_epoch.pt", _checkpoint("fixed_epoch", manifest["run_id"], 3, 6))
    fixed_sha = sha256_file(root / "checkpoints/fixed_epoch.pt")
    manifest["run_kind"] = "final_refit"
    manifest["selector"] = None
    manifest["loss_component_profile"] = {"train": manifest["loss_component_profile"]["train"]}
    manifest["nullable_loss_components"] = {"train": manifest["nullable_loss_components"]["train"]}
    manifest["validation_snapshot"] = None
    manifest["resume_validation_contract"] = {
        "loss": "train.losses.total_loss.value",
        "count": "train_examples",
        "ids": "$train_example_ids",
    }
    manifest["split"]["validation"] = None
    manifest["split_sha256"] = canonical_sha256(manifest["split"])
    manifest["final_selection"] = {"fixed_epoch": 3, "checkpoint_sha256": fixed_sha}
    manifest["degradation"] = {
        "loss_degradation_ratio": None,
        "loss_degradation_absolute": None,
        "ZERO_BEST_LOSS": None,
        "selector_degradation": None,
        "reason": "CV_DERIVED_REFIT_NO_VALIDATION",
    }
    manifest["parent_cv"] = {
        "run_id": "cv-parent",
        "fixed_epoch": 3,
        "degradation_sha256": "d" * 64,
        "config_sha256": manifest["config_sha256"],
        "input_manifest_sha256": manifest["input_manifest_sha256"],
        "split_sha256": manifest["split_sha256"],
        "code_tree_sha256": manifest["code_tree_sha256"],
        "warm_start_checkpoint_sha256": None,
    }
    for row in rows:
        row.update(
            run_kind="final_refit",
            val_batches=0,
            val_examples=0,
            val=None,
            val_by_lineage=None,
            selector_value=None,
            best_so_far=False,
            checkpoint_sha256=row["checkpoint_sha256"] if row["epoch"] == len(rows) else None,
        )
    (root / "checkpoints/best.pt").unlink()
    _rewrite(root, manifest, rows, verdict="CV_DERIVED_REFIT_ONLY")
    return manifest, rows


def test_final_refit_is_train_only_all_null_and_not_standalone_promotable(tmp_path: Path) -> None:
    manifest, rows = _final_refit(tmp_path)
    standalone = verify_training_run(tmp_path)
    assert standalone["verdict"] == "CV_DERIVED_REFIT_ONLY", standalone
    with pytest.raises(GateValidationError, match="non-promotable"):
        validate_training_run(tmp_path)
    manifest["degradation"]["ZERO_BEST_LOSS"] = False
    _rewrite(tmp_path, manifest, rows, verdict="CV_DERIVED_REFIT_ONLY")
    assert "degradation fields" in " ".join(verify_training_run(tmp_path)["errors"])


def _as_cv_fold(root: Path, fold_id: str) -> dict:
    manifest, rows = _valid_run(root, run_id=f"run-fold-{fold_id}")
    manifest["fold_id"] = fold_id
    manifest["parent_cv"] = {"run_id": "cv-root", "fold_id": fold_id}
    val = manifest["split"]["validation"]
    val["stems"] = [f"{fold_id}-val-a", f"{fold_id}-val-b"]
    val["example_ids"] = [f"{fold_id}-val-{index}" for index in range(10)]
    manifest["split_sha256"] = canonical_sha256(manifest["split"])
    manifest["validation_snapshot"]["example_ids"] = val["example_ids"]
    manifest["validation_snapshot"]["split_sha256"] = manifest["split_sha256"]
    per_video = {
        "values": {val["stems"][0]: 0.6, val["stems"][1]: 0.65},
        "uncertainty": {"upper": 0.1},
    }
    _replace_json(root / "provenance/per-video.json", per_video)
    manifest["acceptance_thresholds"]["per_video"]["sha256"] = sha256_file(root / "provenance/per-video.json")
    for row in rows:
        row["fold_id"] = fold_id
    _rewrite(root, manifest, rows)
    return verify_training_run(root)


def _cv_root(root: Path, *, attach_refit: bool = True) -> None:
    _as_cv_fold(root / "fold/0", "0")
    _as_cv_fold(root / "fold/1", "1")
    initial = {fold: strict_json_load(root / f"fold/{fold}/run_manifest.json") for fold in ("0", "1")}
    for fold, other in (("0", "1"), ("1", "0")):
        fold_root = root / f"fold/{fold}"
        manifest = strict_json_load(fold_root / "run_manifest.json")
        rows = strict_jsonl_load(fold_root / "history.jsonl")
        base_train = manifest["split"]["train"]
        other_val = initial[other]["split"]["validation"]
        manifest["split"]["train"] = {
            "stems": base_train["stems"] + other_val["stems"],
            "videos": base_train["videos"] + other_val["videos"],
            "examples": base_train["examples"] + other_val["examples"],
            "batches": base_train["batches"] + other_val["batches"],
            "lineages": {
                lineage: base_train["lineages"][lineage] + other_val["lineages"][lineage]
                for lineage in ("44b6", "6bba")
            },
            "example_ids": base_train["example_ids"] + other_val["example_ids"],
        }
        manifest["split_sha256"] = canonical_sha256(manifest["split"])
        manifest["validation_snapshot"]["split_sha256"] = manifest["split_sha256"]
        for row in rows:
            row["train_examples"] = manifest["split"]["train"]["examples"]
            row["train_batches"] = manifest["split"]["train"]["batches"]
            for component in row["train"]["losses"].values():
                if component is not None:
                    component["denominator"] = row["train_examples"]
                    component["numerator"] = component["value"] * row["train_examples"]
        _rewrite(fold_root, manifest, rows)
    reports = {fold: verify_training_run(root / f"fold/{fold}") for fold in ("0", "1")}
    (root / "oof").mkdir()
    oof_ids = [f"{fold}-val-{index}" for fold in ("0", "1") for index in range(10)]
    oof_assignments = [fold for fold in ("0", "1") for _ in range(10)]
    atomic_write_json(root / "oof/predictions.json", [0.1 + index / 100 for index in range(20)])
    atomic_write_json(root / "oof/example_ids.json", oof_ids)
    atomic_write_json(root / "oof/fold_ids.json", oof_assignments)
    atomic_write_json(
        root / "oof/metrics.json",
        {"loss": 0.6, "dice": 0.8, "lineage": {"44b6": 0.6, "6bba": 0.6}},
    )
    fold_manifest = strict_json_load(root / "fold/0/run_manifest.json")
    for source in ("code-tree.json", "input.json", "per-video.json"):
        atomic_publish_file(root / "provenance" / source, (root / "fold/0/provenance" / source).read_bytes())
    root_manifest = copy.deepcopy(fold_manifest)
    root_manifest.update(run_id="cv-root", run_kind="cv", fold_id=None)
    root_manifest.pop("parent_cv")
    root_manifest["checkpoint_refs"] = {}
    root_manifest["code_tree_sha256"] = sha256_file(root / "provenance/code-tree.json")
    root_manifest["input_manifest_sha256"] = sha256_file(root / "provenance/input.json")
    root_manifest["selector"] = {
        "kind": "oof_metric",
        "field": "loss",
        "direction": "min",
        "tie_rule": "earliest",
    }
    root_manifest["split"]["train"] = copy.deepcopy(initial["0"]["split"]["train"])
    root_manifest["split"]["validation"] = {
        "stems": [f"{fold}-val-{suffix}" for fold in ("0", "1") for suffix in ("a", "b")],
        "videos": 4,
        "examples": 20,
        "batches": 2,
        "lineages": {"44b6": 10, "6bba": 10},
        "example_ids": oof_ids,
    }
    root_manifest["split_sha256"] = canonical_sha256(root_manifest["split"])
    root_manifest["validation_snapshot"]["example_ids"] = oof_ids
    root_manifest["validation_snapshot"]["split_sha256"] = root_manifest["split_sha256"]
    root_per_video = {
        "values": {stem: 0.6 for stem in root_manifest["split"]["validation"]["stems"]},
        "uncertainty": {"upper": 0.1},
    }
    _replace_json(root / "provenance/per-video.json", root_per_video)
    root_manifest["acceptance_thresholds"] = {
        "zero_best_absolute_degradation": 0.01,
        "primary": {
            "field": "loss",
            "direction": "min",
            "baseline": 0.7,
            "margin": 0.05,
            "observed_source": "oof_metrics",
        },
        "noninferiority": {
            "dice": {
                "field": "dice",
                "direction": "max",
                "baseline": 0.75,
                "limit": 0.05,
                "observed_source": "oof_metrics",
            }
        },
        "lineage_noninferiority": {
            lineage: {
                "field": f"lineage.{lineage}",
                "direction": "min",
                "baseline": 0.7,
                "limit": 0.1,
                "observed_source": "oof_metrics",
            }
            for lineage in ("44b6", "6bba")
        },
        "per_video": {
            "path": "provenance/per-video.json",
            "sha256": sha256_file(root / "provenance/per-video.json"),
            "direction": "min",
            "baseline": 0.7,
            "limit": 0.1,
            "observed_source": "artifact_values",
            "uncertainty_field": "uncertainty.upper",
            "uncertainty_limit": 0.2,
            "min_qualifying_videos": 4,
        },
    }
    fold_manifests = {fold: strict_json_load(root / f"fold/{fold}/run_manifest.json") for fold in ("0", "1")}
    fold_selections = [
        {
            "fold_id": fold,
            "epoch": reports[fold]["details"]["best_epoch"],
            "selector_value": reports[fold]["details"]["best_selector_value"],
            "checkpoint_sha256": reports[fold]["details"]["checkpoint_sha256"],
        }
        for fold in ("0", "1")
    ]
    fold_degradation = {
        fold: {
            key: reports[fold]["details"][key]
            for key in (
                "loss_degradation_ratio",
                "loss_degradation_absolute",
                "ZERO_BEST_LOSS",
                "selector_degradation",
            )
        }
        for fold in ("0", "1")
    }
    finite_ratios = [
        item["loss_degradation_ratio"]
        for item in fold_degradation.values()
        if item["loss_degradation_ratio"] is not None
    ]
    degradation = {
        "folds": fold_degradation,
        "aggregate": {
            "finite_loss_degradation_ratio_mean": sum(finite_ratios) / len(finite_ratios),
            "loss_degradation_absolute_mean": sum(
                item["loss_degradation_absolute"] for item in fold_degradation.values()
            )
            / len(fold_degradation),
            "selector_degradation_mean": sum(item["selector_degradation"] for item in fold_degradation.values())
            / len(fold_degradation),
            "zero_best_loss_folds": [],
        },
        "oof_selector_value": 0.6,
    }
    atomic_write_json(root / "oof/degradation.json", degradation)
    root_manifest["cv"] = {
        "fold_ids": ["0", "1"],
        "fold_paths": {fold: f"fold/{fold}" for fold in ("0", "1")},
        "fold_pins": {
            fold: {
                field: fold_manifests[fold][field]
                for field in (
                    "run_id",
                    "config_sha256",
                    "input_manifest_sha256",
                    "code_tree_sha256",
                    "warm_start_checkpoint_sha256",
                    "split_sha256",
                )
            }
            for fold in ("0", "1")
        },
        "oof": {
            "predictions_path": "oof/predictions.json",
            "predictions_sha256": sha256_file(root / "oof/predictions.json"),
            "example_ids_path": "oof/example_ids.json",
            "example_ids_sha256": sha256_file(root / "oof/example_ids.json"),
            "fold_ids_path": "oof/fold_ids.json",
            "fold_ids_sha256": sha256_file(root / "oof/fold_ids.json"),
            "metrics_path": "oof/metrics.json",
            "metrics_sha256": sha256_file(root / "oof/metrics.json"),
            "selector_value": 0.6,
        },
        "require_final_refit": True,
        "degradation_artifact": {
            "path": "oof/degradation.json",
            "sha256": sha256_file(root / "oof/degradation.json"),
        },
    }
    root_manifest["final_selection"] = {
        "oof_selector_value": 0.6,
        "fold_selections": fold_selections,
        "final_refit_ref": None,
    }
    root_manifest["degradation"] = degradation
    root_manifest["config_sha256"] = execution_config_sha256(root_manifest)
    _replace_json(root / "run_manifest.json", root_manifest)
    _refresh_artifacts(root)
    if attach_refit:
        _attach_final_refit(root)


def _attach_final_refit(root: Path) -> tuple[dict, list[dict]]:
    child_manifest, child_rows = _final_refit(root / "final_refit")
    root_manifest = strict_json_load(root / "run_manifest.json")
    root_train = root_manifest["split"]["train"]
    root_val = root_manifest["split"]["validation"]
    child_manifest["split"]["train"] = {
        "stems": root_train["stems"] + root_val["stems"],
        "videos": root_train["videos"] + root_val["videos"],
        "examples": root_train["examples"] + root_val["examples"],
        "batches": root_train["batches"] + root_val["batches"],
        "lineages": {
            lineage: root_train["lineages"][lineage] + root_val["lineages"][lineage] for lineage in ("44b6", "6bba")
        },
        "example_ids": root_train["example_ids"] + root_val["example_ids"],
    }
    child_manifest["split_sha256"] = canonical_sha256(child_manifest["split"])
    for row in child_rows:
        row["train_examples"] = child_manifest["split"]["train"]["examples"]
        row["train_batches"] = child_manifest["split"]["train"]["batches"]
        for component in row["train"]["losses"].values():
            if component is not None:
                component["denominator"] = row["train_examples"]
                component["numerator"] = component["value"] * row["train_examples"]
    child_manifest["parent_cv"].update(
        run_id=root_manifest["run_id"],
        config_sha256=root_manifest["config_sha256"],
        input_manifest_sha256=root_manifest["input_manifest_sha256"],
        split_sha256=child_manifest["split_sha256"],
        code_tree_sha256=root_manifest["code_tree_sha256"],
        warm_start_checkpoint_sha256=root_manifest["warm_start_checkpoint_sha256"],
        degradation_path=root_manifest["cv"]["degradation_artifact"]["path"],
        degradation_sha256=root_manifest["cv"]["degradation_artifact"]["sha256"],
    )
    _rewrite(root / "final_refit", child_manifest, child_rows, verdict="CV_DERIVED_REFIT_ONLY")
    child_report = verify_training_run(root / "final_refit")
    root_manifest["final_selection"]["final_refit_ref"] = {
        "run_id": child_report["run_id"],
        "fixed_epoch": child_report["details"]["best_epoch"],
        "checkpoint_sha256": child_report["details"]["checkpoint_sha256"],
        "run_manifest_sha256": sha256_file(root / "final_refit/run_manifest.json"),
        "artifact_manifest_sha256": sha256_file(root / "final_refit/ARTIFACT_MANIFEST.json"),
        "split_sha256": child_manifest["split_sha256"],
    }
    root_manifest["config_sha256"] = execution_config_sha256(root_manifest)
    _replace_json(root / "run_manifest.json", root_manifest)
    _refresh_artifacts(root)
    return child_manifest, child_rows


def test_cv_fold_and_oof_stream_integrity_and_mixing(tmp_path: Path) -> None:
    _cv_root(tmp_path)
    report = verify_training_run(tmp_path)
    assert report["verdict"] == "PASS", report
    fold_manifest = strict_json_load(tmp_path / "fold/1/run_manifest.json")
    fold_rows = strict_jsonl_load(tmp_path / "fold/1/history.jsonl")
    fold_rows[1]["fold_id"] = "0"
    _rewrite(tmp_path / "fold/1", fold_manifest, fold_rows)
    _refresh_artifacts(tmp_path)
    mixed = verify_training_run(tmp_path)
    assert mixed["verdict"] == "FAIL"
    assert "fold_id does not match" in " ".join(mixed["errors"])


def test_cv_oof_hash_drift_is_detected(tmp_path: Path) -> None:
    _cv_root(tmp_path)
    _replace_bytes(tmp_path / "oof/predictions.json", b"[0.2,0.8]\n")
    _refresh_artifacts(tmp_path)
    report = verify_training_run(tmp_path)
    assert report["verdict"] == "FAIL"
    assert "OOF hash mismatch" in " ".join(report["errors"])


def test_cv_final_refit_parent_pins_are_binding(tmp_path: Path) -> None:
    _cv_root(tmp_path)
    assert verify_training_run(tmp_path)["verdict"] == "PASS"
    child_manifest = strict_json_load(tmp_path / "final_refit/run_manifest.json")
    child_rows = strict_jsonl_load(tmp_path / "final_refit/history.jsonl")
    child_manifest["parent_cv"]["code_tree_sha256"] = ZERO_SHA
    _rewrite(tmp_path / "final_refit", child_manifest, child_rows, verdict="CV_DERIVED_REFIT_ONLY")
    _refresh_artifacts(tmp_path)
    report = verify_training_run(tmp_path)
    assert report["verdict"] == "FAIL"
    assert "parent CV pin mismatch" in " ".join(report["errors"])


def test_cli_emits_machine_readable_fail_and_nonzero(tmp_path: Path) -> None:
    _valid_run(tmp_path)
    command = [sys.executable, "scripts/validate_training_run.py", str(tmp_path)]
    success = subprocess.run(command, check=False, capture_output=True, text=True)
    assert success.returncode == 0
    assert json.loads(success.stdout)["verdict"] == "PASS"
    (tmp_path / "history.jsonl").unlink()
    failure = subprocess.run(command, check=False, capture_output=True, text=True)
    assert failure.returncode == 1
    assert json.loads(failure.stdout)["verdict"] == "FAIL"


def test_opaque_checkpoint_sidecar_is_never_trusted_and_loader_must_bind_bytes(tmp_path: Path) -> None:
    _valid_run(tmp_path)
    best_path = tmp_path / "checkpoints/best.pt"
    best_metadata = strict_json_load(best_path)
    best_path.write_bytes(b"opaque-pickle-shaped-bytes")
    atomic_write_json(Path(f"{best_path}.metadata.json"), best_metadata | {"checkpoint_sha256": sha256_file(best_path)})
    _refresh_artifacts(tmp_path)
    default = verify_training_run(tmp_path)
    assert default["verdict"] == "FAIL"
    assert "opaque checkpoint requires" in " ".join(default["errors"])

    def dishonest_loader(path: Path) -> dict:
        if path == best_path:
            return best_metadata | {"path": str(path.resolve()), "checkpoint_sha256": ZERO_SHA}
        metadata = strict_json_load(path)
        return metadata | {"path": str(path.resolve()), "checkpoint_sha256": sha256_file(path)}

    bound = verify_training_run(tmp_path, checkpoint_metadata_loader=dishonest_loader)
    assert bound["verdict"] == "FAIL"
    assert "loader path/hash binding mismatch" in " ".join(bound["errors"])


def test_resume_empty_states_missing_receipt_and_negative_tolerance_fail(tmp_path: Path) -> None:
    _valid_run(tmp_path)
    resume_path = tmp_path / "checkpoints/resume.pt"
    resume = strict_json_load(resume_path)
    resume["state"]["optimizer"] = {}
    resume.pop("validation_receipt")
    _replace_json(resume_path, resume)
    _refresh_artifacts(tmp_path)
    errors = " ".join(verify_training_run(tmp_path)["errors"])
    assert "optimizer state must be a typed" in errors
    assert "validation receipt" in errors

    manifest, rows = _valid_run(tmp_path / "negative")
    resume = strict_json_load(tmp_path / "negative/checkpoints/resume.pt")
    receipt = strict_json_load(tmp_path / "negative/provenance/resume-validation.json")
    receipt["tolerances"]["loss"]["rtol"] = -1.0
    with pytest.raises(GateValidationError, match="finite and nonnegative"):
        validate_resume_metadata(manifest, rows, resume, validation_receipt=receipt)


def test_warm_start_is_loaded_from_actual_hash_source_and_shape_drift_fails(tmp_path: Path) -> None:
    manifest, rows = _valid_run(tmp_path)
    warm_path = tmp_path / "provenance/warm.pt"
    warm_envelope = _checkpoint("best", "source-run", 4, 8)
    atomic_write_json(warm_path, warm_envelope)
    warm_hash = sha256_file(warm_path)
    manifest["warm_start_checkpoint_sha256"] = warm_hash
    manifest["hash_sources"]["warm_start_checkpoint_sha256"] = "provenance/warm.pt"
    manifest["warm_start"] = {
        "mode": "full_strict",
        "source_run_id": "source-run",
        "source_kind": "best",
        "optimizer_reset": True,
        "scheduler_reset": True,
        "scaler_reset": True,
        "expected_keys": ["layer.weight"],
        "expected_keys_sha256": canonical_sha256(["layer.weight"]),
        "key_specs": {"layer.weight": {"shape": [2, 2], "dtype": "float32"}},
        "new_keys": [],
    }
    _rewrite(tmp_path, manifest, rows)
    assert verify_training_run(tmp_path)["verdict"] == "PASS"
    warm_envelope["state_keys"][0]["shape"] = [3, 3]
    _replace_json(warm_path, warm_envelope)
    manifest["warm_start_checkpoint_sha256"] = sha256_file(warm_path)
    _rewrite(tmp_path, manifest, rows)
    assert "shape/dtype mismatch" in " ".join(verify_training_run(tmp_path)["errors"])


@pytest.mark.parametrize("attack", ["missing_total", "scaled_counts", "zero_division", "unused_weight"])
def test_total_loss_aggregation_adversaries_fail_closed(tmp_path: Path, attack: str) -> None:
    manifest, rows = _valid_run(tmp_path)
    if attack == "missing_total":
        for row in rows:
            row["val"]["losses"]["total_loss"] = None
    elif attack == "scaled_counts":
        component = rows[0]["val"]["losses"]["edge_loss"]
        component["numerator"] *= 2
        component["denominator"] *= 2
    elif attack == "zero_division":
        manifest["total_loss"]["formula"] = "edge_loss / zero"
        manifest["total_loss"]["weights"] = {"zero": 0.0}
    else:
        manifest["total_loss"]["weights"]["unused"] = 1.0
    _rewrite(tmp_path, manifest, rows)
    report = verify_training_run(tmp_path)
    assert report["verdict"] == "FAIL"
    assert any(word in " ".join(report["errors"]) for word in ("total", "denominator", "formula"))


def test_train_loss_selector_and_forged_acceptance_booleans_fail(tmp_path: Path) -> None:
    manifest, rows = _valid_run(tmp_path)
    manifest["selector"] = {
        "kind": "validation_loss",
        "field": "train.losses.total_loss.value",
        "direction": "min",
        "tie_rule": "earliest",
    }
    manifest["acceptance_thresholds"]["primary"] = {"passed": True}
    _rewrite(tmp_path, manifest, rows)
    errors = " ".join(verify_training_run(tmp_path)["errors"])
    assert "must minimize val.losses.total_loss.value" in errors
    assert "literal primary acceptance" in errors


def test_max_classifier_requires_separately_bound_min_val_loss_checkpoint(tmp_path: Path) -> None:
    manifest, rows = _valid_run(tmp_path)
    manifest["task_type"] = "binary_classification"
    for side in ("train", "validation"):
        examples = manifest["split"][side]["examples"]
        manifest["split"][side].update(positive=examples // 2, negative=examples - examples // 2)
    manifest["split_sha256"] = canonical_sha256(manifest["split"])
    manifest["validation_snapshot"]["split_sha256"] = manifest["split_sha256"]
    aucs = [0.7, 0.8, 0.75]
    for row, auc in zip(rows, aucs, strict=True):
        row["task_metrics"]["auc"] = auc
        row["selector_value"] = auc
        row["best_so_far"] = auc == max(aucs[: row["epoch"]])
    manifest["selector"] = {
        "kind": "grouped_validation_metric",
        "field": "task_metrics.auc",
        "direction": "max",
        "tie_rule": "earliest",
    }
    manifest["acceptance_thresholds"]["primary"] = {
        "field": "task_metrics.auc",
        "direction": "max",
        "baseline": 0.7,
        "margin": 0.05,
        "observed_source": "history_best",
    }
    manifest["final_selection"]["selector_value"] = 0.8
    manifest["degradation"] = compute_degradation(
        [0.8, 0.6, 0.7], aucs, direction="max", absolute_warning_threshold=0.01
    )
    manifest["degradation"]["flags"] = manifest["degradation"].pop("warnings")
    _rewrite(tmp_path, manifest, rows)
    missing = verify_training_run(tmp_path)
    assert missing["verdict"] == "FAIL"
    assert "min-val-loss" in " ".join(missing["errors"])

    min_path = tmp_path / "checkpoints/min_val_loss.pt"
    atomic_write_json(min_path, _checkpoint("min_val_loss", manifest["run_id"], 2, 4))
    manifest["min_val_loss_selection"] = {
        "epoch": 2,
        "value": 0.6,
        "checkpoint_sha256": sha256_file(min_path),
        "path": "checkpoints/min_val_loss.pt",
    }
    _rewrite(tmp_path, manifest, rows)
    assert verify_training_run(tmp_path)["verdict"] == "PASS"


@pytest.mark.parametrize(
    "attack",
    ["string_split", "bool_count", "bad_video_count", "duplicate_ids", "lineage_sum", "binary_sum"],
)
def test_split_and_snapshot_adversaries_fail_canonically(tmp_path: Path, attack: str) -> None:
    manifest, rows = _valid_run(tmp_path)
    if attack == "string_split":
        manifest["split"] = "not-an-object"
    elif attack == "bool_count":
        manifest["split"]["validation"]["examples"] = True
    elif attack == "bad_video_count":
        manifest["split"]["validation"]["videos"] = 3
    elif attack == "duplicate_ids":
        manifest["split"]["validation"]["example_ids"][1] = manifest["split"]["validation"]["example_ids"][0]
        manifest["validation_snapshot"]["example_ids"] = manifest["split"]["validation"]["example_ids"]
    elif attack == "lineage_sum":
        manifest["split"]["validation"]["lineages"]["44b6"] = 4
    else:
        manifest["task_type"] = "binary_classification"
        manifest["split"]["train"].update(positive=10, negative=9)
        manifest["split"]["validation"].update(positive=5, negative=4)
    if isinstance(manifest["split"], dict):
        manifest["split_sha256"] = canonical_sha256(manifest["split"])
        manifest["validation_snapshot"]["split_sha256"] = manifest["split_sha256"]
    _rewrite(tmp_path, manifest, rows)
    report = verify_training_run(tmp_path)
    assert report["verdict"] == "FAIL"
    assert isinstance(report["errors"], list) and report["errors"]


@pytest.mark.parametrize("attack", ["bool_schema", "bool_epoch", "string_task", "bool_lineage"])
def test_global_strict_type_adversaries(tmp_path: Path, attack: str) -> None:
    manifest, rows = _valid_run(tmp_path)
    if attack == "bool_schema":
        manifest["schema_version"] = True
    elif attack == "bool_epoch":
        rows[0]["epoch"] = True
    elif attack == "string_task":
        rows[0]["task_metrics"]["dice"] = "0.8"
    else:
        rows[0]["val_by_lineage"]["44b6"]["loss"] = False
    _rewrite(tmp_path, manifest, rows)
    report = verify_training_run(tmp_path)
    assert report["verdict"] == "FAIL"
    assert report["errors"]


def test_cv_without_folds_fold_pin_drift_duplicate_ids_and_bogus_selector(tmp_path: Path) -> None:
    manifest, rows = _valid_run(tmp_path / "no-fold")
    manifest["run_kind"] = "cv"
    for row in rows:
        row["run_kind"] = "cv"
    _rewrite(tmp_path / "no-fold", manifest, rows)
    assert verify_training_run(tmp_path / "no-fold")["verdict"] == "FAIL"

    _cv_root(tmp_path / "cv")
    root_manifest = strict_json_load(tmp_path / "cv/run_manifest.json")
    root_manifest["cv"]["fold_pins"]["1"]["config_sha256"] = ZERO_SHA
    root_manifest["cv"]["oof"]["selector_value"] = 9.0
    root_manifest["final_selection"]["oof_selector_value"] = 9.0
    _replace_json(tmp_path / "cv/run_manifest.json", root_manifest)
    _refresh_artifacts(tmp_path / "cv")
    errors = " ".join(verify_training_run(tmp_path / "cv")["errors"])
    assert "parent pin mismatch" in errors
    assert "not recomputed" in errors


def test_cv_duplicate_fold_validation_ids_and_non_numeric_oof_fail(tmp_path: Path) -> None:
    _cv_root(tmp_path)
    fold0 = strict_json_load(tmp_path / "fold/0/run_manifest.json")
    fold1 = strict_json_load(tmp_path / "fold/1/run_manifest.json")
    rows1 = strict_jsonl_load(tmp_path / "fold/1/history.jsonl")
    fold1["split"]["validation"]["example_ids"] = fold0["split"]["validation"]["example_ids"]
    fold1["validation_snapshot"]["example_ids"] = fold1["split"]["validation"]["example_ids"]
    fold1["split_sha256"] = canonical_sha256(fold1["split"])
    fold1["validation_snapshot"]["split_sha256"] = fold1["split_sha256"]
    _rewrite(tmp_path / "fold/1", fold1, rows1)
    root = strict_json_load(tmp_path / "run_manifest.json")
    root["cv"]["fold_pins"]["1"]["split_sha256"] = fold1["split_sha256"]
    metrics = strict_json_load(tmp_path / "oof/metrics.json")
    metrics["dice"] = "0.8"
    _replace_json(tmp_path / "oof/metrics.json", metrics)
    root["cv"]["oof"]["metrics_sha256"] = sha256_file(tmp_path / "oof/metrics.json")
    root["config_sha256"] = execution_config_sha256(root)
    _replace_json(tmp_path / "run_manifest.json", root)
    _refresh_artifacts(tmp_path)
    errors = " ".join(verify_training_run(tmp_path)["errors"])
    assert "overlap" in errors
    assert "finite numeric" in errors


def test_final_refit_forbidden_checkpoint_and_fake_parent_never_promote(tmp_path: Path) -> None:
    manifest, rows = _final_refit(tmp_path)
    atomic_write_json(tmp_path / "checkpoints/best.pt", _checkpoint("best", manifest["run_id"], 2, 4))
    manifest["parent_cv"]["degradation_sha256"] = ZERO_SHA
    _rewrite(tmp_path, manifest, rows, verdict="CV_DERIVED_REFIT_ONLY")
    report = verify_training_run(tmp_path)
    assert report["verdict"] == "FAIL"
    assert "forbidden/extra" in " ".join(report["errors"])


def test_atomic_no_clobber_symlink_hardlink_concurrency_and_orphan_checkpoint(tmp_path: Path) -> None:
    target = tmp_path / "immutable.json"
    atomic_write_json(target, {"a": 1})
    with pytest.raises(FileExistsError):
        atomic_write_json(target, {"a": 2})
    assert strict_json_load(target) == {"a": 1}

    history = tmp_path / "concurrent.jsonl"
    first = HistoryWriter(history)
    second = HistoryWriter(history, resume=True, expected_prefix_sha256=sha256_bytes(b""))
    first.append({"epoch": 1, "global_step": 1})
    with pytest.raises(TrainingHistoryError, match="concurrent"):
        second.append({"epoch": 1, "global_step": 1})
    symlink_history = tmp_path / "history-link"
    symlink_history.symlink_to(history)
    with pytest.raises(TrainingHistoryError, match="symlink"):
        HistoryWriter(symlink_history, resume=True, expected_prefix_sha256=sha256_file(history))

    manifest, rows = _valid_run(tmp_path / "run")
    rows[0]["checkpoint_sha256"] = "e" * 64
    _rewrite(tmp_path / "run", manifest, rows)
    assert "orphaned" in " ".join(verify_training_run(tmp_path / "run")["errors"])


def test_external_symlink_and_hardlinked_artifacts_fail(tmp_path: Path) -> None:
    _valid_run(tmp_path / "symlink")
    external = tmp_path / "external.bin"
    external.write_bytes(b"external")
    link = tmp_path / "symlink/provenance/external-link"
    link.symlink_to(external)
    _refresh_artifacts(tmp_path / "symlink")
    assert "symlink artifact" in " ".join(verify_training_run(tmp_path / "symlink")["errors"])

    _valid_run(tmp_path / "hardlink")
    source = tmp_path / "hardlink/provenance/input.json"
    alias = tmp_path / "hardlink/provenance/input-alias.json"
    alias.hardlink_to(source)
    _refresh_artifacts(tmp_path / "hardlink")
    assert "hard-linked artifact" in " ".join(verify_training_run(tmp_path / "hardlink")["errors"])


@pytest.mark.parametrize("attack", ["extra", "run_id", "bool_schema"])
def test_artifact_manifest_exact_schema_identity_and_version(tmp_path: Path, attack: str) -> None:
    _valid_run(tmp_path)
    path = tmp_path / "ARTIFACT_MANIFEST.json"
    artifact = strict_json_load(path)
    if attack == "extra":
        artifact["trusted"] = True
    elif attack == "run_id":
        artifact["run_id"] = "different-run"
    else:
        artifact["schema_version"] = True
    _replace_json(path, artifact)
    assert verify_training_run(tmp_path)["verdict"] == "FAIL"


def test_atomic_publication_failure_leaves_no_target_or_partial(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "never-published.json"

    def fail_rename(*args, **kwargs):
        raise OSError("simulated interrupted publication")

    monkeypatch.setattr("biohub.training_history._rename_noreplace", fail_rename)
    with pytest.raises(OSError, match="interrupted"):
        atomic_write_json(target, {"complete": True})
    assert not target.exists()
    assert not list(tmp_path.glob(".never-published.json.*.tmp"))


def test_metadata_only_checkpoint_and_placeholder_resume_state_fail(tmp_path: Path) -> None:
    _valid_run(tmp_path)
    best_path = tmp_path / "checkpoints/best.pt"
    best = strict_json_load(best_path)
    best.pop("model_state")
    _replace_json(best_path, best)
    resume_path = tmp_path / "checkpoints/resume.pt"
    resume = strict_json_load(resume_path)
    resume["state"]["optimizer"]["payload"] = {"param_groups": 1}
    _replace_json(resume_path, resume)
    _refresh_artifacts(tmp_path)
    errors = " ".join(verify_training_run(tmp_path)["errors"])
    assert "model tensor state missing" in errors
    assert "optimizer payload schema invalid" in errors


@pytest.mark.parametrize("attack", ["wrong_length", "dtype_drift", "duplicate_tensor", "extra_field"])
def test_safe_json_checkpoint_tensor_state_is_strict(tmp_path: Path, attack: str) -> None:
    _valid_run(tmp_path)
    path = tmp_path / "checkpoints/best.pt"
    checkpoint = strict_json_load(path)
    if attack == "wrong_length":
        checkpoint["model_state"][0]["values"] = [0.1]
    elif attack == "dtype_drift":
        checkpoint["model_state"][0]["dtype"] = "float64"
    elif attack == "duplicate_tensor":
        checkpoint["model_state"].append(copy.deepcopy(checkpoint["model_state"][0]))
    else:
        checkpoint["trusted"] = True
    _replace_json(path, checkpoint)
    _refresh_artifacts(tmp_path)
    assert "checkpoint" in " ".join(verify_training_run(tmp_path)["errors"])


def test_opaque_checkpoint_requires_exact_trusted_loader_success_evidence(tmp_path: Path) -> None:
    manifest, rows = _valid_run(tmp_path)
    best_path = tmp_path / "checkpoints/best.pt"
    best_metadata = strict_json_load(best_path)
    _replace_bytes(best_path, b"opaque-model-checkpoint")
    best_sha = sha256_file(best_path)
    manifest["final_selection"]["checkpoint_sha256"] = best_sha
    rows[manifest["final_selection"]["epoch"] - 1]["checkpoint_sha256"] = best_sha
    _rewrite(tmp_path, manifest, rows)

    def loader(path: Path) -> dict:
        metadata = copy.deepcopy(best_metadata) if path == best_path else strict_json_load(path)
        digest = sha256_file(path)
        resolved = str(path.resolve())
        metadata.update(path=resolved, checkpoint_sha256=digest)
        metadata["load_evidence"] = {
            "trusted_safe_loader": True,
            "strict": True,
            "missing_keys": [],
            "unexpected_keys": [],
            "path": resolved,
            "checkpoint_sha256": digest,
            "model_state_sha256": canonical_sha256(metadata["model_state"]),
        }
        return metadata

    assert verify_training_run(tmp_path, checkpoint_metadata_loader=loader)["verdict"] == "PASS"

    def no_success_evidence(path: Path) -> dict:
        metadata = loader(path)
        metadata.pop("load_evidence")
        return metadata

    errors = " ".join(verify_training_run(tmp_path, checkpoint_metadata_loader=no_success_evidence)["errors"])
    assert "success evidence invalid" in errors


def test_complete_execution_digest_and_resume_reject_seed_gradient_drift(tmp_path: Path) -> None:
    manifest, rows = _valid_run(tmp_path)
    old_config_sha = manifest["config_sha256"]
    manifest["seed"] = 8
    manifest["validation_snapshot"]["seed"] = 8
    manifest["gradient"]["clip_threshold"] = 4.0
    for row in rows:
        row["grad_norm_pre_clip"]["clip_threshold"] = 4.0
    manifest["config_sha256"] = execution_config_sha256(manifest)
    assert manifest["config_sha256"] != old_config_sha
    _replace_json(tmp_path / "run_manifest.json", manifest)
    _write_rows(tmp_path / "history.jsonl", rows)
    resume_path = tmp_path / "checkpoints/resume.pt"
    resume = strict_json_load(resume_path)
    resume["history_prefix_sha256"] = sha256_file(tmp_path / "history.jsonl")
    _replace_json(resume_path, resume)
    manifest["checkpoint_refs"]["checkpoints/resume.pt"] = sha256_file(resume_path)
    _replace_json(tmp_path / "run_manifest.json", manifest)
    _refresh_artifacts(tmp_path)
    errors = " ".join(verify_training_run(tmp_path)["errors"])
    assert "resume config_sha256 mismatch" in errors


@pytest.mark.parametrize(
    "mutation",
    [
        lambda manifest: manifest["sampler"].update(mode="epoch_derived", seed_formula="H(run,epoch)"),
        lambda manifest: manifest["selector"].update(tie_rule="latest"),
        lambda manifest: manifest["loss_component_profile"]["val"]["edge_loss"].update(reduction="sum_over_pairs"),
        lambda manifest: manifest["total_loss"]["aggregation"].update(reduction="sum_over_pairs"),
        lambda manifest: manifest["acceptance_thresholds"]["primary"].update(margin=0.2),
    ],
)
def test_execution_digest_covers_all_training_and_gate_semantics(tmp_path: Path, mutation) -> None:
    manifest, _ = _valid_run(tmp_path)
    before = execution_config_sha256(manifest)
    mutation(manifest)
    assert execution_config_sha256(manifest) != before


def test_unknown_manifest_execution_field_is_rejected(tmp_path: Path) -> None:
    _valid_run(tmp_path)
    manifest = strict_json_load(tmp_path / "run_manifest.json")
    manifest["gradient_accumulation"] = 8
    _replace_json(tmp_path / "run_manifest.json", manifest)
    _refresh_artifacts(tmp_path)
    assert "unknown fields" in " ".join(verify_training_run(tmp_path)["errors"])


def test_all_row_checkpoints_receive_strict_state_validation(tmp_path: Path) -> None:
    manifest, rows = _valid_run(tmp_path)
    bogus = _checkpoint("epoch", manifest["run_id"], 1, 2)
    bogus["state_keys"] = [{"name": "wrong", "shape": [999], "dtype": "int8"}]
    bogus["model_state"] = [{"name": "wrong", "shape": [1], "dtype": "int8", "values": [1]}]
    path = tmp_path / "checkpoints/epoch-0001.pt"
    atomic_write_json(path, bogus)
    rows[0]["checkpoint_sha256"] = sha256_file(path)
    _rewrite(tmp_path, manifest, rows)
    errors = " ".join(verify_training_run(tmp_path)["errors"])
    assert "epoch 1 checkpoint metadata mismatch" in errors


def test_cv_exact_membership_unique_selections_and_final_refit_are_mandatory(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate"
    _cv_root(duplicate)
    manifest = strict_json_load(duplicate / "run_manifest.json")
    manifest["final_selection"]["fold_selections"].append(
        copy.deepcopy(manifest["final_selection"]["fold_selections"][0])
    )
    _replace_json(duplicate / "run_manifest.json", manifest)
    _refresh_artifacts(duplicate)
    assert "fold selections" in " ".join(verify_training_run(duplicate)["errors"])

    alien = tmp_path / "alien"
    _cv_root(alien)
    manifest = strict_json_load(alien / "run_manifest.json")
    validation = manifest["split"]["validation"]
    validation["stems"] = [f"alien-{index}" for index in range(4)]
    validation["example_ids"] = [f"alien-{index}" for index in range(20)]
    manifest["split_sha256"] = canonical_sha256(manifest["split"])
    manifest["validation_snapshot"]["example_ids"] = validation["example_ids"]
    manifest["validation_snapshot"]["split_sha256"] = manifest["split_sha256"]
    per_video = {"values": {stem: 0.6 for stem in validation["stems"]}, "uncertainty": {"upper": 0.1}}
    _replace_json(alien / "provenance/per-video.json", per_video)
    manifest["acceptance_thresholds"]["per_video"]["sha256"] = sha256_file(alien / "provenance/per-video.json")
    manifest["config_sha256"] = execution_config_sha256(manifest)
    _replace_json(alien / "run_manifest.json", manifest)
    _refresh_artifacts(alien)
    assert "exact fold-validation union" in " ".join(verify_training_run(alien)["errors"])

    no_refit = tmp_path / "no-refit"
    _cv_root(no_refit, attach_refit=False)
    assert "requires final_refit_ref" in " ".join(verify_training_run(no_refit)["errors"])
    with pytest.raises(GateValidationError):
        validate_training_run(no_refit)


def test_cv_degradation_must_be_exactly_recomputed(tmp_path: Path) -> None:
    _cv_root(tmp_path)
    manifest = strict_json_load(tmp_path / "run_manifest.json")
    _replace_json(tmp_path / "oof/degradation.json", {"made_up": 0})
    manifest["cv"]["degradation_artifact"]["sha256"] = sha256_file(tmp_path / "oof/degradation.json")
    manifest["degradation"] = {"made_up": 0}
    manifest["config_sha256"] = execution_config_sha256(manifest)
    _replace_json(tmp_path / "run_manifest.json", manifest)
    _refresh_artifacts(tmp_path)
    assert "not exactly recomputed" in " ".join(verify_training_run(tmp_path)["errors"])


def test_cv_fold_training_semantics_must_not_drift(tmp_path: Path) -> None:
    _cv_root(tmp_path)
    fold_root = tmp_path / "fold/1"
    fold_manifest = strict_json_load(fold_root / "run_manifest.json")
    fold_rows = strict_jsonl_load(fold_root / "history.jsonl")
    fold_manifest["hardware"]["device"] = "different-device"
    _rewrite(fold_root, fold_manifest, fold_rows)
    root_manifest = strict_json_load(tmp_path / "run_manifest.json")
    root_manifest["cv"]["fold_pins"]["1"]["config_sha256"] = fold_manifest["config_sha256"]
    root_manifest["config_sha256"] = execution_config_sha256(root_manifest)
    _replace_json(tmp_path / "run_manifest.json", root_manifest)
    _refresh_artifacts(tmp_path)
    assert "training semantics drift" in " ".join(verify_training_run(tmp_path)["errors"])


def test_history_writer_rejects_same_size_inode_swap(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_bytes(b'{"epoch":1,"global_step":2}\n')
    writer = HistoryWriter(path, resume=True, expected_prefix_sha256=sha256_file(path))
    path.unlink()
    path.write_bytes(b'{"epoch":1,"global_step":9}\n')
    with pytest.raises(TrainingHistoryError, match="changed"):
        writer.append({"epoch": 2, "global_step": 10})
    writer.close()


def test_post_rename_fsync_failure_rolls_back_target(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "rolled-back.json"
    calls = 0

    def fail_first_fsync(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("directory fsync failed")

    monkeypatch.setattr("biohub.training_history._fsync_directory", fail_first_fsync)
    with pytest.raises(OSError, match="directory fsync failed"):
        atomic_write_json(target, {"complete": True})
    assert not target.exists()


def test_post_rename_rollback_failure_quarantines_final_name(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "quarantined.json"
    original_unlink = Path.unlink
    calls = 0

    def fail_first_fsync(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("directory fsync failed")

    def fail_target_unlink(path: Path, *args, **kwargs) -> None:
        if path == target:
            raise OSError("rollback unlink failed")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr("biohub.training_history._fsync_directory", fail_first_fsync)
    monkeypatch.setattr(Path, "unlink", fail_target_unlink)
    with pytest.raises(TrainingHistoryError, match="was quarantined"):
        atomic_write_json(target, {"complete": True})
    assert not target.exists()
    assert len(list(tmp_path.glob(".quarantined.json.failed-*"))) == 1


def test_loss_config_formula_and_nullable_population_are_consistent(tmp_path: Path) -> None:
    mismatch = tmp_path / "weight"
    manifest, rows = _valid_run(mismatch)
    manifest["loss_config"]["w_edge"] = 2.0
    _rewrite(mismatch, manifest, rows)
    assert "weights do not exactly match" in " ".join(verify_training_run(mismatch)["errors"])

    stale = tmp_path / "nullable"
    manifest, rows = _valid_run(stale)
    for row in rows:
        row["val"]["losses"]["optional_loss"] = _component(0.1, 10)
    _rewrite(stale, manifest, rows)
    assert "despite zero-population" in " ".join(verify_training_run(stale)["errors"])
