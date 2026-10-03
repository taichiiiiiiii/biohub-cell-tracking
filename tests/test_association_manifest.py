import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import torch
from test_association_training import API, SmallModel, small_batch

from biohub import association_manifest as module
from biohub.association_acceptance import paired_readout
from biohub.association_artifacts import finalize_run, publish_epoch
from biohub.association_resume import capture_state, restore_state
from biohub.association_training import run_epoch
from biohub.training_history import atomic_write_json, canonical_sha256, sha256_file


def test_synthetic_ten_epoch_pipeline_through_full_gate(tmp_path, monkeypatch):
    """Actual tiny-model updates; not Biohub data or a scientific gain claim."""
    model = SmallModel()
    original = tmp_path / "fixture-source.pth"
    torch.save(model.state_dict(), original)
    monkeypatch.setattr(module, "PRIMARY_EXPECTED_SHA", sha256_file(original))
    root = tmp_path / "run"
    warm = module.import_warm_start(model, original, module.PRIMARY_EXPECTED_SHA, root)
    train_stems = [f"{lineage}_t{i}" for lineage in ("44b6", "6bba") for i in range(4)]
    val_stems = [f"{lineage}_v{i}" for lineage in ("44b6", "6bba") for i in range(2)]
    items, split = {}, {}
    for name, stems in (("train", train_stems), ("validation", val_stems)):
        items[name] = [(stem, f"{stem}:000-001", small_batch()) for stem in stems]
        split[name] = {"stems": stems, "videos": len(stems), "examples": len(stems), "batches": len(stems),
                       "lineages": {lineage: len(stems) // 2 for lineage in ("44b6", "6bba")},
                       "example_ids": [item[1] for item in items[name]]}
    baseline = run_epoch(API, model, items["validation"], "cpu")
    for name in ("input", "code-tree", "wrapper", "support"):
        atomic_write_json(root / f"provenance/{name}.json", {"synthetic_fixture": name})
    context = {
        "run_id": "synthetic-ten-epoch", "git_sha": "fixture", "cli": "test_synthetic_ten_epoch_pipeline",
        "dependencies": {"torch": str(torch.__version__)}, "allowed_environment": {}, "hardware": {"device": "cpu"},
        "code_tree_sha256": sha256_file(root / "provenance/code-tree.json"),
        "input_manifest_sha256": sha256_file(root / "provenance/input.json"), "warm_import": warm,
        "hash_sources": {"code_tree_sha256": "provenance/code-tree.json",
                         "input_manifest_sha256": "provenance/input.json",
                         "warm_start_checkpoint_sha256": "provenance/primary-import.pt"},
        "training_sources": {key: {"path": f"provenance/{name}.json",
                                    "sha256": sha256_file(root / f"provenance/{name}.json")}
                             for key, name in (("wrapper", "wrapper"), ("support_trainer", "support"))},
    }
    prepared = {"split": split, "max_nodes": 2}
    manifest = module.build_manifest(context, prepared, baseline)
    augmented = module.build_manifest({**context, "train_augmentation": {"name": "xy_flip"}}, prepared, baseline)
    assert augmented["model_config"]["train_augmentation"] == {"name": "xy_flip"}
    assert augmented["config_sha256"] != manifest["config_sha256"]
    assert augmented["validation_snapshot"] == manifest["validation_snapshot"]
    assert manifest["model_config"]["epochs"] == 10
    assert manifest["split_sha256"] == canonical_sha256(split)
    bad = copy.deepcopy(baseline)
    bad["example_ids"].reverse()
    with pytest.raises(ValueError):
        module.build_manifest(context, prepared, bad)
    assert manifest["config_sha256"] == module.execution_config_sha256(manifest)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-5)
    generator = torch.Generator().manual_seed(20260922)
    rows, reports = [], []
    for epoch in range(10):
        trained = run_epoch(API, model, items["train"], "cpu", optimizer=optimizer)
        evaluated = run_epoch(API, model, items["validation"], "cpu")
        captured = capture_state(model, optimizer, generator, "cpu")
        restored = SmallModel()
        restored_optimizer = torch.optim.AdamW(restored.parameters(), lr=1e-5)
        restore_state(captured, restored, restored_optimizer, torch.Generator(), "cpu")
        readback = run_epoch(API, restored, items["validation"], "cpu")
        rows.append(publish_epoch(root, manifest, rows, trained, evaluated, readback, captured,
                                  lr=1e-5, epoch_seconds=1.))
        reports.append(evaluated)
        if epoch == 2:
            with pytest.raises(ValueError, match="predeclared"):
                finalize_run(root, manifest)
            assert not (root / "checkpoints/best.pt").exists()
    selected = min(range(10), key=lambda i: rows[i]["selector_value"])
    atomic_write_json(root / "provenance/per-video.json", paired_readout(baseline, reports[selected]))
    readout_path = root / "provenance/per-video.json"
    original_readout = readout_path.read_text()
    forged = json.loads(original_readout)
    forged["uncertainty"]["upper"] = -100.
    readout_path.write_text(json.dumps(forged))
    with pytest.raises(ValueError, match="differs from selected history"):
        finalize_run(root, manifest)
    assert not (root / "checkpoints/best.pt").exists()
    readout_path.write_text(original_readout)
    result = finalize_run(root, manifest)
    assert result["verdict"] == "FAIL"  # Tiny updates do not meet 1% pooled improvement.
    assert result["errors"] == ["primary selector failed recomputed threshold",
                                "artifact verdict mismatch: expected PASS, got 'FAIL'"]
    from scripts import export_association_candidate as exporter

    monkeypatch.setattr(exporter, "ROOT", tmp_path)
    export_path = tmp_path / "outputs/local/association_exports/rejected"
    with pytest.raises(ValueError, match="Training run did not pass"):
        exporter.export_candidate(root, export_path)
    assert not export_path.exists()
    assert rows[-1]["global_step"] == 80
    imported = torch.load(root / "provenance/primary-import.pt", weights_only=True)
    assert imported["epoch"] is None and imported["global_step"] is None
    receipt = json.loads((root / "provenance/warm-import.json").read_text())
    assert receipt["legacy_history_verified"] is False
    before = copy.deepcopy(model.state_dict())
    with pytest.raises(FileExistsError):
        module.import_warm_start(model, original, module.PRIMARY_EXPECTED_SHA, root)
    torch.testing.assert_close(model.state_dict(), before, rtol=0, atol=0)


def test_actual_primary_import_preserves_all_official_model_tensors(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    original = root / "outputs/kaggle/st_r3_checkpoint_recovery/primary/edge_predictor_best.pth"
    if not original.exists():
        pytest.skip("Pinned primary weights not available in this checkout")
    monkeypatch.syspath_prepend(str(root / "official/src"))
    monkeypatch.syspath_prepend(str(root / "official/scripts"))
    spec = importlib.util.spec_from_file_location(
        "_primary_import_test", root / "official/scripts/train_unet_transformer.py")
    api = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, api)
    spec.loader.exec_module(api)
    model = api.UNetNodeTransformer(api.TemporalUNet3D(in_channels=1, out_channels=32, layers=[32, 64, 128]),
                                   unet_out_channels=32, pos_feat_dim=32)
    info = module.import_warm_start(model, original, module.PRIMARY_EXPECTED_SHA, tmp_path)
    assert info["original_sha256"] == sha256_file(original)
    imported = torch.load(tmp_path / "provenance/primary-import.pt", map_location="cpu", weights_only=True)
    source = torch.load(original, map_location="cpu", weights_only=True)
    assert len(source) == len(info["model_state_schema"]) == 136
    assert set(imported["model_state"]) == set(source)
    assert all(torch.equal(source[name], imported["model_state"][name]) for name in source)
