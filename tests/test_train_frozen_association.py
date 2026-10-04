import contextlib
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from scripts import train_frozen_association as cli


def setup_root(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "PLAN", tmp_path / "plan.json")
    monkeypatch.setattr(cli.dd, "single_run_lock", contextlib.nullcontext)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    monkeypatch.delenv("PYTORCH_ENABLE_MPS_FALLBACK", raising=False)


def test_incomplete_acquisition_creates_no_run_and_never_reads_gt(tmp_path, monkeypatch):
    setup_root(tmp_path, monkeypatch)

    def incomplete(*args):
        raise ValueError("No completion proof")

    monkeypatch.setattr(cli, "verify_acquisition", incomplete)
    monkeypatch.setattr(cli, "execute", lambda *args: pytest.fail("Must not execute"))
    with pytest.raises(ValueError, match="completion"):
        cli.run(tmp_path, "preflight")
    assert not (tmp_path / "outputs").exists()


@pytest.mark.parametrize("case", ["unsafe", "fallback", "existing", "symlink"])
def test_preflight_rejects_unsafe_configuration_before_data(case, tmp_path, monkeypatch):
    setup_root(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "verify_acquisition", lambda *args: pytest.fail("Must not read data"))
    run_id = "safe"
    if case == "unsafe":
        run_id = "../other"
    elif case == "fallback":
        monkeypatch.setenv("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    else:
        parent = tmp_path / "outputs/local/association_candidates"
        parent.mkdir(parents=True)
        if case == "existing":
            (parent / run_id).mkdir()
        else:
            (parent / run_id).symlink_to(tmp_path / "missing")
    with pytest.raises((ValueError, FileExistsError)):
        cli.run(tmp_path, run_id)


def test_source_snapshot_and_drift_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    source = tmp_path / "fixture.py"
    source.write_text("original")
    monkeypatch.setattr(cli, "source_files", lambda: ["fixture.py"])
    output = tmp_path / "run"
    check = cli.snapshot_sources(output)
    check()
    assert (output / "provenance/source/fixture.py").read_text() == "original"
    source.write_text("changed")
    with pytest.raises(ValueError, match="Source changed"):
        check()


def test_failure_report_is_outside_run_and_preserves_partial_work(tmp_path, monkeypatch):
    setup_root(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "verify_acquisition", lambda *args: None)

    def fail(root, *args):
        (root / "partial.txt").write_text("keep")
        raise RuntimeError("Do not expose this detail")

    monkeypatch.setattr(cli, "execute", fail)
    with pytest.raises(RuntimeError):
        cli.run(tmp_path, "failed")
    parent = tmp_path / "outputs/local/association_candidates"
    report = json.loads((parent / "failed.failure.json").read_text())
    assert report["error_class"] == "RuntimeError"
    assert "detail" not in json.dumps(report)
    assert (parent / "failed/partial.txt").read_text() == "keep"


@pytest.mark.parametrize("augmentation", ["none", "xy_flip"])
def test_ten_epoch_orchestration_uses_fresh_iterators_and_preserves_failed_verdict(tmp_path, monkeypatch, augmentation):
    """Wiring test, not numerical/accelerator parity or a performance claim."""
    setup_root(tmp_path, monkeypatch)
    receipt = tmp_path / "receipt"
    receipt.mkdir()
    (receipt / "files.json").write_text("[]")
    cli.PLAN.write_text("{}")
    root, gate = tmp_path / "run", tmp_path / "run.gate.json"
    root.mkdir()
    checks, batches, restored, models, published, augmented_epochs = [], [], [], [], [], []
    result = {"losses": {"total_loss": {"value": 1.}}, "grad_norm_pre_clip": None, "example_ids": ["window"]}
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps(result))

    def snapshot(path):
        for relative in ("provenance/code-tree.json", "provenance/source/scripts/train_frozen_association.py",
                         "provenance/source/src/biohub/association_training.py"):
            cli.atomic_publish_file(path / relative, b"fixture")
        return lambda: checks.append("source")

    class Model:
        def to(self, device):
            return self

    def make_model(api):
        model = Model()
        models.append(model)
        return model

    def iterate(prepared, side, generator=None):
        batches.append((side, generator is not None))
        yield ("video", "window", {"fixture": True})

    def epoch(api, model, items, device, **kwargs):
        items = list(items)
        assert len(items) == 1
        assert bool(items[0][2].get("augmented")) == (augmentation == "xy_flip" and bool(kwargs.get("optimizer")))
        if kwargs.get("optimizer"):
            assert (root / "provenance/pretraining-manifest.json").is_file()
        return copy.deepcopy(result)

    def augment(items, *, seed, epoch):
        assert seed == 20260922
        augmented_epochs.append(epoch)
        for stem, identity, item in items:
            yield stem, identity, {**item, "augmented": True}

    def publish(path, manifest, rows, trained, val, readback, captured, **kwargs):
        assert captured == {"actual_state": True}
        published.append(len(rows))
        return {"global_step": len(rows) + 1}

    monkeypatch.setattr(cli, "snapshot_sources", snapshot)
    monkeypatch.setattr(cli, "verify_acquisition", lambda *args: checks.append("input"))
    monkeypatch.setattr(cli, "load_api", lambda: object())
    monkeypatch.setattr(cli, "prepare_windows", lambda *args: {
        "coverage": {}, "identities": {"train": [("video", "window")]}})
    monkeypatch.setattr(cli, "augment_batches", augment)
    monkeypatch.setattr(cli, "seed_rng", lambda *args: None)
    monkeypatch.setattr(cli, "make_model", make_model)
    monkeypatch.setattr(cli, "make_optimizer", lambda model: object())
    monkeypatch.setattr(cli, "import_warm_start", lambda *args: {})
    monkeypatch.setattr(cli, "freeze_detector", lambda model: lambda: None)
    monkeypatch.setattr(cli, "iter_batches", iterate)
    monkeypatch.setattr(cli, "run_epoch", epoch)
    monkeypatch.setattr(cli, "capture_probe", lambda *args: {"probe": True})
    monkeypatch.setattr(cli, "assert_same_probe", lambda a, b: None)
    monkeypatch.setattr(cli, "describe_probe", copy.deepcopy)
    monkeypatch.setattr(cli, "capture_state", lambda *args: {"actual_state": True})
    monkeypatch.setattr(cli, "restore_state", lambda *args: restored.append(args[1]))
    monkeypatch.setattr(cli, "build_manifest", lambda *args: {"fixed": True})
    monkeypatch.setattr(cli, "publish_epoch", publish)
    monkeypatch.setattr(cli, "paired_readout", lambda *args: {"actual_readout": True})
    monkeypatch.setattr(cli, "finalize_run", lambda *args: {"verdict": "FAIL", "errors": ["threshold"]})
    monkeypatch.setattr(cli, "subprocess", SimpleNamespace(check_output=lambda *args, **kwargs: "fixture-git"))
    assert cli.execute(root, gate, receipt, "fixture", augmentation,
                       reference if augmentation == "xy_flip" else None) == 2
    assert augmented_epochs == (list(range(1, 11)) if augmentation == "xy_flip" else [])
    if augmentation == "xy_flip":
        assert len(json.loads((root / "provenance/augmentation-schedule.json").read_text())) == 10
        for number in range(1, 11):
            record = json.loads((root / f"provenance/augmentation-epoch-{number:04d}.json").read_text())
            assert sum(record["combination_counts"].values()) == 1
    assert json.loads(gate.read_text())["verdict"] == "FAIL"
    assert len(models) == 11 and len(restored) == 20
    assert published == list(range(10))
    assert sum(side == "train" and shuffled for side, shuffled in batches) == 10
    assert sum(side == "validation" for side, _ in batches) == 23
    assert all(restored[index] is models[0] for index in range(1, 20, 2))
    assert len(checks) == 44  # After baseline, before/after each epoch, before seal.
    for number in range(1, 11):
        path = root / f"provenance/readback-state-{number:04d}.pt"
        assert torch.load(path, weights_only=True) == {"actual_state": True}
        assert json.loads(path.with_suffix(".json").read_text())["sha256"] == cli.sha256_file(path)


def test_actual_official_api_loading_restores_search_path():
    previous = cli.sys.path[:]
    api = cli.load_api()
    assert cli.sys.path == previous
    assert Path(api.__file__).resolve() == cli.ROOT / "official/scripts/train_unet_transformer.py"
    assert hasattr(api, "UNetNodeTransformer")


def test_actual_source_inventory_is_complete_and_can_be_snapshotted(tmp_path):
    files = cli.source_files()
    assert "official/scripts/dataspec.py" in files
    assert "src/biohub/association_probe.py" in files
    assert "scripts/train_frozen_association.py" in files
    check = cli.snapshot_sources(tmp_path)
    check()
    records = json.loads((tmp_path / "provenance/code-tree.json").read_text())
    assert [record["path"] for record in records] == files
