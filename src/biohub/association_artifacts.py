"""Immutable candidate epoch publication; this is not a full-run gate verdict.

Qwen draft corrected against the real report and verifier contracts. The caller
must perform validation on the restored checkpoint to obtain readback_report.
"""
import copy
import hashlib
import io
import math
import stat
from pathlib import Path

import torch

from biohub.association_acceptance import paired_readout_from_history, video_metrics
from biohub.association_resume import _model_records, build_artifact_state
from biohub.training_history import (
    CHECKPOINT_FORMAT,
    HistoryWriter,
    _contained_regular_file,
    _validate_checkpoint_envelope_schema,
    _validate_grad,
    _verify_training_run,
    atomic_publish_file,
    atomic_write_json,
    canonical_json_bytes,
    canonical_sha256,
    compute_degradation,
    execution_config_sha256,
    sha256_file,
    strict_json_load,
    strict_jsonl_load,
    trusted_pytorch_checkpoint_metadata_loader,
    validate_resume_metadata,
    verify_training_run,
)

CONTRACT = {"loss": "val.losses.total_loss.value", "count": "val_examples", "ids": "$validation_snapshot_ids"}
SELECTOR = {"kind": "validation_loss", "field": "val.losses.total_loss.value",
            "direction": "min", "tie_rule": "earliest"}
IDENTITY = ("schema_version", "run_id", "purpose", "run_kind", "phase", "fold_id")
METRICS = ("precision", "recall", "accuracy")


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def compare_readback(expected, actual):
    """Counts/IDs exact; fixed same-device loss tolerance, never relaxed."""
    if type(expected) is not type(actual):
        raise ValueError("Readback type mismatch")
    if isinstance(expected, dict):
        if set(expected) != set(actual):
            raise ValueError("Readback keys mismatch")
        for key in expected:
            compare_readback(expected[key], actual[key])
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            raise ValueError("Readback length mismatch")
        for left, right in zip(expected, actual, strict=True):
            compare_readback(left, right)
    elif isinstance(expected, float):
        if (not _finite(expected) or not _finite(actual)
                or not math.isclose(expected, actual, rel_tol=1e-5, abs_tol=1e-7)):
            raise ValueError("Readback numeric mismatch")
    elif type(expected) not in (int, str, bool, type(None)) or expected != actual:
        raise ValueError("Readback exact mismatch")


def _group(group):
    count = group["examples"]
    if type(count) is not int or count <= 0 or group["batches"] != count:
        raise ValueError("Invalid batch1/window counts")
    losses = group["losses"]
    if set(losses) != {"edge_loss", "det_loss", "total_loss"}:
        raise ValueError("Unexpected loss components")
    for loss in losses.values():
        if (set(loss) != {"value", "numerator", "denominator", "reduction"}
                or type(loss["denominator"]) is not int or loss["denominator"] != count
                or loss["reduction"] != "sum_over_windows"
                or any(not _finite(loss[key]) or loss[key] < 0 for key in ("value", "numerator"))
                or loss["value"] != loss["numerator"] / count):
            raise ValueError("Loss aggregation mismatch")
    if not math.isclose(losses["total_loss"]["value"],
                        losses["edge_loss"]["value"] + losses["det_loss"]["value"], rel_tol=1e-5, abs_tol=1e-7):
        raise ValueError("Loss formula mismatch")


def _report(report, split, training):
    _group(report)
    ids = report["example_ids"]
    expected = split["example_ids"]
    if (len(set(ids)) != len(ids) or len(ids) != report["examples"] or set(ids) != set(expected)
            or report["examples"] != split["examples"] or report["batches"] != split["batches"]):
        raise ValueError("Split coverage mismatch")
    if report["optimizer_steps"] != (report["examples"] if training else 0):
        raise ValueError("Optimizer step count mismatch")
    if set(report["by_lineage"]) != {"44b6", "6bba"}:
        raise ValueError("Lineage coverage mismatch")
    for name, group in report["by_lineage"].items():
        _group(group)
        if group["examples"] != split["lineages"][name]:
            raise ValueError("Lineage count mismatch")


def publish_epoch(root, manifest, rows, train_report, val_report, readback_report, captured, *, lr, epoch_seconds):
    root = Path(root).absolute()
    if root != root.resolve(strict=False):
        raise ValueError("Run root contains an alias")
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
            or manifest["purpose"] != "candidate" or manifest["run_kind"] != "single_split"
            or manifest["selector"] != SELECTOR or manifest["resume_validation_contract"] != CONTRACT):
        raise ValueError("Unsupported candidate contract")
    if any(not _finite(value) or value < 0 for value in (lr, epoch_seconds)):
        raise ValueError("Invalid LR/time")
    if captured["device"] != manifest["hardware"]["device"]:
        raise ValueError("Captured device mismatch")
    _report(train_report, manifest["split"]["train"], True)
    _report(val_report, manifest["split"]["validation"], False)
    if val_report["example_ids"] != manifest["validation_snapshot"]["example_ids"]:
        raise ValueError("Validation order differs from snapshot")
    compare_readback(val_report, readback_report)
    errors = []
    _validate_grad(train_report["grad_norm_pre_clip"], train_report["optimizer_steps"], len(rows) + 1, errors)
    if errors or train_report["grad_norm_pre_clip"]["clip_threshold"] != 1.0:
        raise ValueError("Invalid gradient record")
    lineage = {}
    for name, group in val_report["by_lineage"].items():
        metrics = {key: group["task_metrics"][key] for key in METRICS}
        if any(not _finite(value) or not 0 <= value <= 1 for value in metrics.values()):
            raise ValueError("Undefined required lineage metrics")
        lineage[name] = {"loss": group["losses"]["total_loss"]["value"], "examples": group["examples"],
                         **metrics, "counts": group["counts"]}
    history = root / "history.jsonl"
    existing = b""
    if rows:
        existing = history.read_bytes()
        if canonical_json_bytes(strict_jsonl_load(history)) != canonical_json_bytes(rows):
            raise ValueError("History prefix differs from supplied rows")
    elif history.exists():
        raise ValueError("Unexpected existing history")
    epoch = len(rows) + 1
    step = (rows[-1]["global_step"] if rows else 0) + train_report["optimizer_steps"]
    value = val_report["losses"]["total_loss"]["value"]
    improved = not rows or value < min(row["selector_value"] for row in rows)
    row = {key: copy.deepcopy(manifest[key]) for key in IDENTITY}
    row.update(epoch=epoch, global_step=step, lr=lr, epoch_seconds=epoch_seconds,
               train_batches=train_report["batches"], train_examples=train_report["examples"],
               val_batches=val_report["batches"], val_examples=val_report["examples"],
               train={"losses": train_report["losses"]}, val={"losses": val_report["losses"]},
               val_by_lineage=lineage, task_metrics={name: {key: item[key] for key in METRICS}
                                                    for name, item in lineage.items()},
               grad_norm_pre_clip=train_report["grad_norm_pre_clip"], nonfinite_count=0,
               selector_value=value, best_so_far=improved)
    thresholds = manifest.get("acceptance_thresholds", {})
    if "improved_videos" in thresholds.get("noninferiority", {}):
        row["task_metrics"].update(video_metrics(val_report, thresholds))
    state = build_artifact_state(captured, {})
    model = state["model"]["payload"]["state_dict"]
    records = _model_records(model)
    envelope = {"format": CHECKPOINT_FORMAT, "schema_version": 1, "kind": "best" if improved else "last",
                "run_id": manifest["run_id"], "epoch": epoch, "global_step": step, "model_state": model,
                "state_keys": [{key: record[key] for key in ("name", "shape", "dtype")} for record in records]}
    stream = io.BytesIO()
    torch.save(envelope, stream)
    weights = stream.getvalue()
    row["checkpoint_sha256"] = hashlib.sha256(weights).hexdigest()
    winner = row if improved else min(rows, key=lambda item: item["selector_value"])
    state["best_state"] = {key: winner[key] for key in ("epoch", "selector_value", "checkpoint_sha256")}
    prefix = hashlib.sha256(existing + canonical_json_bytes(row)).hexdigest()
    snapshot_sha = canonical_sha256(manifest["validation_snapshot"])
    receipt = {"schema_version": 1, "run_id": manifest["run_id"], "epoch": epoch, "global_step": step,
               "validation_snapshot_sha256": snapshot_sha,
               "expected": {"loss": value, "count": val_report["examples"], "ids": val_report["example_ids"]},
               "actual": {"loss": readback_report["losses"]["total_loss"]["value"],
                          "count": readback_report["examples"], "ids": readback_report["example_ids"]},
               "tolerances": {"loss": {"rtol": 1e-5, "atol": 1e-7}}}
    receipt_path = f"provenance/resume-validation-{epoch:04d}.json"
    resume = {**envelope, "kind": "resume", "state": state, "history_prefix_sha256": prefix,
              "next_epoch": epoch + 1, "next_global_step": step + 1, "validation_snapshot_sha256": snapshot_sha,
              "validation_receipt": {"path": receipt_path,
                                     "sha256": hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()}}
    for key in ("config_sha256", "input_manifest_sha256", "split_sha256",
                "code_tree_sha256", "warm_start_checkpoint_sha256"):
        resume[key] = manifest[key]
    stream = io.BytesIO()
    torch.save(resume, stream)
    reports = {"train": train_report, "val": val_report, "readback": readback_report}
    canonical_json_bytes(reports)  # Reject nonfinite/unsupported values before any write.
    paths = [receipt_path, f"reports/epoch-{epoch:04d}.json", f"checkpoints/epoch-{epoch:04d}.pt",
             f"checkpoints/resume-{epoch:04d}.pt"]
    if any((root / path).exists() or (root / path).is_symlink() for path in paths):
        raise ValueError("Refusing to overwrite epoch artifacts")
    atomic_write_json(root / receipt_path, receipt)
    atomic_write_json(root / paths[1], reports)
    atomic_publish_file(root / paths[2], weights)
    atomic_publish_file(root / paths[3], stream.getvalue())
    writer = HistoryWriter(history, resume=bool(rows),
                           expected_prefix_sha256=hashlib.sha256(existing).hexdigest() if rows else None)
    try:
        if writer.append(row) != prefix or sha256_file(history) != prefix:
            raise ValueError("Published history prefix mismatch; stop run")
    finally:
        writer.close()
    return copy.deepcopy(row)


def _checkpoint_snapshot(root, relative):
    path = _contained_regular_file(root, relative)
    metadata = dict(trusted_pytorch_checkpoint_metadata_loader(path))
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != metadata["checkpoint_sha256"]:
        raise ValueError("Checkpoint changed during finalization")
    return data, metadata


def _inventory(root, run_id):
    files = []
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError("Artifact tree contains a symlink or special file")
        relative = path.relative_to(root).as_posix()
        if relative == "ARTIFACT_MANIFEST.json":
            continue
        safe = _contained_regular_file(root, relative)
        files.append({"path": relative, "bytes": safe.stat().st_size, "sha256": sha256_file(safe)})
    return {"schema_version": 1, "run_id": run_id, "verdict": "PASS", "files": files}


def finalize_run(root, manifest):
    """Seal a run once; a failed gate remains FAIL and cannot be promoted.

    Full provenance and per-video acceptance evidence must already exist. This
    does not generate evidence or relax thresholds to make a run pass.
    """
    root = Path(root).absolute()
    if not root.is_dir() or root != root.resolve(strict=True):
        raise ValueError("Invalid run root")
    final_paths = ("checkpoints/best.pt", "checkpoints/last.pt", "checkpoints/resume.pt",
                   "run_manifest.json", "ARTIFACT_MANIFEST.json")
    if any((root / path).exists() or (root / path).is_symlink() for path in final_paths):
        raise ValueError("Run already finalized or partial finalization requires diagnosis")
    if (manifest["purpose"] != "candidate" or manifest["run_kind"] != "single_split"
            or manifest["selector"] != SELECTOR or manifest["config_sha256"] != execution_config_sha256(manifest)):
        raise ValueError("Candidate contract/config mismatch")
    rows = strict_jsonl_load(_contained_regular_file(root, "history.jsonl"))
    if len(rows) < 3:
        raise ValueError("Candidate requires at least three complete epochs")
    planned_epochs = manifest.get("model_config", {}).get("epochs")
    if planned_epochs is not None and (type(planned_epochs) is not int or len(rows) != planned_epochs):
        raise ValueError("Incomplete predeclared training epoch count")
    winner = None
    previous_step = 0
    for index, row in enumerate(rows, 1):
        value = row["selector_value"]
        if (type(row["epoch"]) is not int or row["epoch"] != index
                or type(row["global_step"]) is not int or row["global_step"] <= previous_step
                or any(row[key] != manifest[key] for key in IDENTITY)
                or not _finite(value) or value < 0 or value != row["val"]["losses"]["total_loss"]["value"]):
            raise ValueError("History identity/sequence/selector mismatch")
        previous_step = row["global_step"]
        improved = winner is None or value < winner["selector_value"]
        if row["best_so_far"] is not improved:
            raise ValueError("History violates strict improvement/earliest tie")
        tail_bytes, metadata = _checkpoint_snapshot(root, f"checkpoints/epoch-{index:04d}.pt")
        if metadata["checkpoint_sha256"] != row["checkpoint_sha256"]:
            raise ValueError("Epoch checkpoint SHA mismatch")
        expected_kind = "best" if improved else "last"
        schema = {key: item for key, item in metadata.items() if key != "load_evidence"}
        errors = []
        _validate_checkpoint_envelope_schema(schema, expected_kind, "epoch snapshot", errors)
        if (errors or metadata["kind"] != expected_kind or metadata["format"] != CHECKPOINT_FORMAT
                or metadata["schema_version"] != 1
                or any(metadata[key] != row[key] for key in ("run_id", "epoch", "global_step"))
                or metadata["state_keys"] != manifest["model_state_schema"]):
            raise ValueError("Epoch checkpoint envelope/schema mismatch")
        if improved:
            winner, winner_bytes = row, tail_bytes
    final = copy.deepcopy(manifest)
    if final.get("execution_hash_policy") == "predeclared_with_result_bindings_v1":
        binding = final["acceptance_thresholds"]["per_video"]
        if "improved_videos" in final["acceptance_thresholds"]["noninferiority"]:
            expected_readout = paired_readout_from_history(winner, final["acceptance_thresholds"])
            recorded_readout = strict_json_load(_contained_regular_file(root, binding["path"]))
            if canonical_sha256(expected_readout) != canonical_sha256(recorded_readout):
                raise ValueError("Per-video readout differs from selected history")
        actual = sha256_file(_contained_regular_file(root, binding["path"]))
        if binding["sha256"] not in (None, actual):
            raise ValueError("Per-video result binding changed")
        binding["sha256"] = actual
    final["final_selection"] = {key: winner[key] for key in ("epoch", "selector_value", "checkpoint_sha256")}
    losses = [row["val"]["losses"]["total_loss"]["value"] for row in rows]
    degradation = compute_degradation(losses, [row["selector_value"] for row in rows], direction="min",
                                     absolute_warning_threshold=final["acceptance_thresholds"][
                                         "zero_best_absolute_degradation"])
    degradation["flags"] = degradation.pop("warnings")
    if degradation["loss_degradation_ratio"] is None:
        degradation["reason"] = "ZERO_BEST_LOSS"
    final["degradation"] = degradation
    resume_bytes, resume = _checkpoint_snapshot(root, f"checkpoints/resume-{len(rows):04d}.pt")
    receipt_ref = resume["validation_receipt"]
    receipt_path = _contained_regular_file(root, receipt_ref["path"])
    if sha256_file(receipt_path) != receipt_ref["sha256"]:
        raise ValueError("Resume validation receipt changed")
    if resume["history_prefix_sha256"] != sha256_file(root / "history.jsonl"):
        raise ValueError("Resume does not bind complete history")
    validate_resume_metadata(final, rows, resume, validation_receipt=strict_json_load(receipt_path))
    if final["config_sha256"] != execution_config_sha256(final):
        raise ValueError("Finalization changed execution configuration")
    _inventory(root, final["run_id"])  # Reject special paths before final writes.
    if rows[-1]["best_so_far"]:
        last = torch.load(io.BytesIO(tail_bytes), map_location="cpu", weights_only=True)
        last["kind"] = "last"
        stream = io.BytesIO()
        torch.save(last, stream)
        tail_bytes = stream.getvalue()
    for relative, data in zip(final_paths[:3], (winner_bytes, tail_bytes, resume_bytes), strict=True):
        atomic_publish_file(root / relative, data)
    final["checkpoint_refs"] = {path: sha256_file(root / path) for path in final_paths[:3]}
    atomic_write_json(root / "run_manifest.json", final)
    inventory = _inventory(root, final["run_id"])
    report = _verify_training_run(root, checkpoint_metadata_loader=trusted_pytorch_checkpoint_metadata_loader,
                                  unpublished_artifacts=inventory)
    inventory["verdict"] = report["verdict"]  # Never publish speculative PASS.
    atomic_write_json(root / "ARTIFACT_MANIFEST.json", inventory)
    return verify_training_run(root, checkpoint_metadata_loader=trusted_pytorch_checkpoint_metadata_loader)
