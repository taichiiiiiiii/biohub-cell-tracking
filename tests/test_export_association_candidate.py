import copy
import json

import pytest
import torch

from scripts import export_association_candidate as module


def fixture(tmp_path, monkeypatch, damage=None):
    monkeypatch.setattr(module, "ROOT", tmp_path)
    root = tmp_path / "run"
    (root / "provenance").mkdir(parents=True)
    (root / "checkpoints").mkdir()
    baseline = {"unet.weight": torch.ones(2), "detect_head.weight": torch.ones(1),
                "transformer.weight": torch.ones(3)}
    candidate = copy.deepcopy(baseline)
    candidate["transformer.weight"] += 1
    if damage == "frozen":
        candidate["unet.weight"] += 1
    elif damage == "unchanged":
        candidate = copy.deepcopy(baseline)
    elif damage == "nan":
        candidate["transformer.weight"][0] = float("nan")
    elif damage == "missing":
        del baseline["detect_head.weight"], candidate["detect_head.weight"]
    elif damage == "shape":
        candidate["transformer.weight"] = torch.ones(4)
    torch.save(baseline, root / "provenance/primary-original.pth")
    torch.save({"model_state": candidate}, root / "checkpoints/best.pt")
    monkeypatch.setattr(module, "PRIMARY_EXPECTED_SHA", module.sha256_file(root / "provenance/primary-original.pth"))
    manifest = {"run_id": "fixture", "purpose": "candidate", "run_kind": "single_split",
                "model_config": {"epochs": 10, "frozen_submodules": ["unet", "detect_head"],
                                 "original_warm_start_sha256": module.PRIMARY_EXPECTED_SHA},
                "checkpoint_refs": {"checkpoints/best.pt": module.sha256_file(root / "checkpoints/best.pt")}}
    module.atomic_write_json(root / "run_manifest.json", manifest)
    module.atomic_write_json(root / "ARTIFACT_MANIFEST.json", {"fixture": True})
    monkeypatch.setattr(module, "verify_training_run", lambda *args, **kwargs: {"verdict": "PASS"})
    return root, tmp_path / "outputs/local/association_exports/candidate", candidate


def test_exports_changed_candidate_not_original_without_modifying_run(tmp_path, monkeypatch):
    root, dest, candidate = fixture(tmp_path, monkeypatch)
    before = {str(p): module.sha256_file(p) for p in root.rglob("*") if p.is_file()}
    receipt = module.export_candidate(root, dest)
    actual = torch.load(dest / "edge_predictor_best.pth", weights_only=True)
    assert all(torch.equal(actual[name], tensor) for name, tensor in candidate.items())
    assert receipt["changed_association_tensors"] == ["transformer.weight"]
    assert receipt["approved_for_submission"] is False
    assert receipt == json.loads((dest / "export.json").read_text())
    assert before == {str(p): module.sha256_file(p) for p in root.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        module.export_candidate(root, dest)


@pytest.mark.parametrize("damage", ["frozen", "unchanged", "nan", "missing", "shape", "gate", "hash", "outside"])
def test_invalid_candidate_never_creates_export(damage, tmp_path, monkeypatch):
    root, dest, _ = fixture(tmp_path, monkeypatch, damage)
    if damage == "gate":
        monkeypatch.setattr(module, "verify_training_run", lambda *args, **kwargs: {"verdict": "FAIL"})
    elif damage == "hash":
        torch.save({"different": True}, root / "checkpoints/best.pt")
    elif damage == "outside":
        dest = tmp_path / "outputs/local/association_exports-sibling/candidate"
    with pytest.raises(ValueError):
        module.export_candidate(root, dest)
    assert not dest.exists()


def test_second_gate_failure_prevents_export(tmp_path, monkeypatch):
    root, dest, _ = fixture(tmp_path, monkeypatch)
    verdicts = iter(["PASS", "FAIL"])
    monkeypatch.setattr(module, "verify_training_run", lambda *args, **kwargs: {"verdict": next(verdicts)})
    with pytest.raises(ValueError, match="Sealed run changed"):
        module.export_candidate(root, dest)
    assert not dest.exists()
