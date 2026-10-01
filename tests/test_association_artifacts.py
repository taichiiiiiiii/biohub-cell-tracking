import copy
import io
import json

import pytest
import torch
from test_association_training import API, SmallModel, small_batch
from test_training_history import _convert_run_checkpoints_to_pytorch, _valid_run, _write_rows

from biohub.association_acceptance import acceptance_spec
from biohub.association_artifacts import CONTRACT, SELECTOR, finalize_run, publish_epoch
from biohub.association_resume import capture_state, restore_state
from biohub.association_training import run_epoch
from biohub.training_history import (
    canonical_sha256,
    execution_config_sha256,
    sha256_file,
    strict_jsonl_load,
    trusted_pytorch_checkpoint_metadata_loader,
    validate_resume_metadata,
)


def setup_run(device="cpu"):
    model = SmallModel().to(device)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.0)
    generator = torch.Generator().manual_seed(17)
    train = [("44b6_a", "a:0", small_batch()), ("6bba_b", "b:0", small_batch())]
    val = [("44b6_c", "c:0", small_batch()), ("6bba_d", "d:0", small_batch())]
    split = {name: {"example_ids": [item[1] for item in items], "examples": 2, "batches": 2,
                    "lineages": {"44b6": 1, "6bba": 1}}
             for name, items in (("train", train), ("validation", val))}
    snapshot = {"example_ids": ["c:0", "d:0"], "input_manifest_sha256": "1" * 64,
                "split_sha256": canonical_sha256(split), "preprocessing_config": {"window": 2},
                "seed": 17, "allowed_environment": {}, "device": device, "dtype": "float32",
                "framework_version": str(torch.__version__), "shuffle": False, "augmentation": False}
    manifest = {"schema_version": 1, "run_id": "synthetic-writer-test", "purpose": "candidate",
                "run_kind": "single_split", "phase": "train", "fold_id": None,
                "selector": SELECTOR, "resume_validation_contract": CONTRACT, "hardware": {"device": device},
                "split": split, "validation_snapshot": snapshot, "config_sha256": "0" * 64,
                "input_manifest_sha256": "1" * 64, "split_sha256": snapshot["split_sha256"],
                "code_tree_sha256": "2" * 64, "warm_start_checkpoint_sha256": None}
    return model, optimizer, generator, train, val, manifest


@pytest.mark.parametrize("device", ["cpu", "mps"])
def test_real_epoch_save_readback_and_resume_metadata(tmp_path, device):
    if device == "mps" and not torch.backends.mps.is_available():
        pytest.skip("MPS unavailable")
    model, optimizer, generator, train, val, manifest = setup_run(device)
    rows = []
    for epoch in (1, 2):
        trained = run_epoch(API, model, train, device, optimizer=optimizer)
        evaluated = run_epoch(API, model, val, device)
        captured = capture_state(model, optimizer, generator, device)
        restored = SmallModel().to(device)
        restored_optimizer = torch.optim.SGD(restored.parameters(), lr=0.0)
        restore_state(captured, restored, restored_optimizer, torch.Generator(), device)
        readback = run_epoch(API, restored, val, device)
        row = publish_epoch(tmp_path, manifest, rows, trained, evaluated, readback,
                            captured, lr=0.0, epoch_seconds=1.0)
        rows.append(row)
        assert row["best_so_far"] is (epoch == 1)  # Exact ties retain first epoch.
        assert row["checkpoint_sha256"] == sha256_file(tmp_path / f"checkpoints/epoch-{epoch:04d}.pt")
        resume = trusted_pytorch_checkpoint_metadata_loader(tmp_path / f"checkpoints/resume-{epoch:04d}.pt")
        manifest["model_state_schema"] = resume["state_keys"]
        manifest["final_selection"] = {key: rows[0][key]
                                       for key in ("epoch", "selector_value", "checkpoint_sha256")}
        receipt = json.loads((tmp_path / f"provenance/resume-validation-{epoch:04d}.json").read_text())
        assert resume["history_prefix_sha256"] == sha256_file(tmp_path / "history.jsonl")
        validate_resume_metadata(manifest, rows, resume, validation_receipt=receipt)
    assert strict_jsonl_load(tmp_path / "history.jsonl") == rows


@pytest.mark.parametrize("damage", ["snapshot", "steps", "readback_count", "readback_loss", "null_metric",
                                    "denominator", "selector", "device", "contract"])
def test_invalid_epoch_never_appends_or_publishes(tmp_path, damage):
    model, optimizer, generator, train, val, manifest = setup_run()
    trained = run_epoch(API, model, train, "cpu", optimizer=optimizer)
    evaluated = run_epoch(API, model, val, "cpu")
    readback = copy.deepcopy(evaluated)
    captured = capture_state(model, optimizer, generator, "cpu")
    if damage == "snapshot":
        manifest["validation_snapshot"]["example_ids"].reverse()
    elif damage == "steps":
        trained["optimizer_steps"] += 1
    elif damage == "readback_count":
        readback["counts"]["tp"] += 1
    elif damage == "readback_loss":
        readback["losses"]["edge_loss"]["value"] += 0.1
    elif damage == "null_metric":
        evaluated["by_lineage"]["44b6"]["task_metrics"]["precision"] = None
        readback = copy.deepcopy(evaluated)
    elif damage == "denominator":
        trained["losses"]["edge_loss"]["denominator"] = 10
    elif damage == "selector":
        manifest["selector"] = {**SELECTOR, "direction": "max"}
    elif damage == "device":
        captured["device"] = "mps"
    else:
        manifest["resume_validation_contract"] = {}
    with pytest.raises(ValueError):
        publish_epoch(tmp_path, manifest, [], trained, evaluated, readback, captured, lr=0.0, epoch_seconds=1.0)
    assert not list(tmp_path.iterdir())


def prepared_finalization_fixture(root, values):
    """Artifact schema fixture only, not Biohub scientific improvement evidence."""
    manifest, rows = _valid_run(root, values=values)
    _convert_run_checkpoints_to_pytorch(root, manifest, rows, genuine_resume_state=True)
    raw = torch.load(root / "checkpoints/last.pt", map_location="cpu", weights_only=True)
    for row in rows:
        epoch = {**raw, "kind": "best" if row["best_so_far"] else "last",
                 "epoch": row["epoch"], "global_step": row["global_step"]}
        stream = io.BytesIO()
        torch.save(epoch, stream)
        path = root / f"checkpoints/epoch-{row['epoch']:04d}.pt"
        path.write_bytes(stream.getvalue())
        row["checkpoint_sha256"] = sha256_file(path)
    _write_rows(root / "history.jsonl", rows)
    winner = min(rows, key=lambda row: row["selector_value"])
    selected = {key: winner[key] for key in ("epoch", "selector_value", "checkpoint_sha256")}
    resume = torch.load(root / "checkpoints/resume.pt", map_location="cpu", weights_only=True)
    resume["history_prefix_sha256"] = sha256_file(root / "history.jsonl")
    resume["state"]["best_state"] = selected
    torch.save(resume, root / f"checkpoints/resume-{len(rows):04d}.pt")
    for relative in ("run_manifest.json", "ARTIFACT_MANIFEST.json", "checkpoints/best.pt",
                     "checkpoints/last.pt", "checkpoints/resume.pt"):
        (root / relative).unlink()  # Only files produced by this isolated test fixture.
    assert manifest["config_sha256"] == execution_config_sha256(manifest)
    return manifest


@pytest.mark.parametrize("values", [[0.8, 0.6, 0.7], [0.8, 0.7, 0.6], [0.8, 0.6, 0.6]])
def test_finalization_passes_full_saved_artifact_verifier(tmp_path, values):
    manifest = prepared_finalization_fixture(tmp_path, values)
    report = finalize_run(tmp_path, manifest)
    assert report["verdict"] == "PASS", report
    saved = json.loads((tmp_path / "run_manifest.json").read_text())
    assert saved["final_selection"]["epoch"] == values.index(min(values)) + 1
    assert json.loads((tmp_path / "ARTIFACT_MANIFEST.json").read_text())["verdict"] == "PASS"
    with pytest.raises(ValueError):
        finalize_run(tmp_path, manifest)


def test_finalization_keeps_failed_acceptance_as_fail(tmp_path):
    manifest = prepared_finalization_fixture(tmp_path, [0.9, 0.85, 0.8])
    report = finalize_run(tmp_path, manifest)
    assert report["verdict"] == "FAIL"
    assert any("primary" in error for error in report["errors"])
    assert json.loads((tmp_path / "ARTIFACT_MANIFEST.json").read_text())["verdict"] == "FAIL"


def test_finalization_binds_predeclared_result_without_rewriting_execution_hash(tmp_path):
    manifest = prepared_finalization_fixture(tmp_path, [0.8, 0.6, 0.7])
    manifest["execution_hash_policy"] = "predeclared_with_result_bindings_v1"
    manifest["acceptance_thresholds"]["per_video"]["sha256"] = None
    manifest["config_sha256"] = execution_config_sha256(manifest)
    resume_path = tmp_path / "checkpoints/resume-0003.pt"
    resume = torch.load(resume_path, map_location="cpu", weights_only=True)
    resume["config_sha256"] = manifest["config_sha256"]
    torch.save(resume, resume_path)  # Isolated fixture's pretraining policy.
    report = finalize_run(tmp_path, manifest)
    assert report["verdict"] == "PASS", report
    saved = json.loads((tmp_path / "run_manifest.json").read_text())
    assert saved["config_sha256"] == manifest["config_sha256"]
    assert saved["acceptance_thresholds"]["per_video"]["sha256"] == sha256_file(tmp_path / "provenance/per-video.json")


def test_finalization_rejects_tampered_snapshot_before_alias_publication(tmp_path):
    manifest = prepared_finalization_fixture(tmp_path, [0.8, 0.6, 0.7])
    path = tmp_path / "checkpoints/epoch-0001.pt"
    raw = torch.load(path, map_location="cpu", weights_only=True)
    raw["model_state"]["layer.weight"].add_(1)
    torch.save(raw, path)
    with pytest.raises(ValueError, match="SHA"):
        finalize_run(tmp_path, manifest)
    assert not (tmp_path / "checkpoints/best.pt").exists()
    assert not (tmp_path / "ARTIFACT_MANIFEST.json").exists()


def test_publisher_records_actual_four_video_losses_and_strict_improvement_count(tmp_path):
    model, optimizer, generator, train, val, manifest = setup_run()
    val.extend([("44b6_e", "e:0", small_batch()), ("6bba_f", "f:0", small_batch())])
    ids = [item[1] for item in val]
    manifest["split"]["validation"] = {"example_ids": ids, "examples": 4, "batches": 4,
                                        "lineages": {"44b6": 2, "6bba": 2}}
    manifest["validation_snapshot"]["example_ids"] = ids
    baseline = run_epoch(API, model, val, "cpu")
    manifest["acceptance_thresholds"] = acceptance_spec(baseline)
    trained = run_epoch(API, model, train, "cpu", optimizer=optimizer)
    evaluated = run_epoch(API, model, val, "cpu")
    captured = capture_state(model, optimizer, generator, "cpu")
    row = publish_epoch(tmp_path, manifest, [], trained, evaluated, run_epoch(API, model, val, "cpu"),
                        captured, lr=0., epoch_seconds=1.)
    assert row["task_metrics"]["improved_videos"] == 0  # LR zero test; not a qualifying candidate.
    assert row["task_metrics"]["video_losses"] == {
        stem: group["losses"]["total_loss"]["value"] for stem, group in evaluated["by_video"].items()}
