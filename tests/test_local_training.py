import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from biohub.local_training import (
    DiagnosticRecorder,
    checked_loss,
    diagnostic_input_manifest,
    evaluate_components,
    finalize_diagnostic_selection,
    freeze_detector,
    strict_warm_start,
    validate_window_coverage,
)
from biohub.training_history import sha256_bytes, sha256_file
from scripts.local_train_unet_transformer import adapted_code


def diagnostic_selection_fixture(tmp_path, losses=(3.0, 1.0, 1.0, 2.0)):
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()
    history = tmp_path / "history.jsonl"
    rows, raw = [], b""
    for epoch, loss in enumerate(losses, 1):
        path = checkpoint_dir / f"epoch_{epoch:04d}.pt"
        path.write_bytes(f"test-checkpoint-{epoch}".encode())
        checkpoint = {"name": path.name, "sha256": sha256_file(path)}
        row = {"epoch": epoch, "global_step": epoch, "status": "DIAGNOSTIC_ONLY",
               "candidate_gate": "INCOMPLETE", "resume_supported": False,
               "validation": {"losses": {"total_loss": {"value": loss}}}, "checkpoint": checkpoint}
        rows.append(row)
        raw += json.dumps(row).encode() + b"\n"
        path.with_suffix(".receipt.json").write_text(json.dumps({
            "checkpoint": checkpoint, "epoch": epoch, "global_step": epoch,
            "resume_supported": False, "history_prefix_sha256": sha256_bytes(raw),
        }))
    history.write_bytes(raw)
    return history, checkpoint_dir, rows


def test_diagnostic_selection_minimum_earliest_tie_and_no_overwrite(tmp_path):
    history, checkpoints, _ = diagnostic_selection_fixture(tmp_path)
    output = tmp_path / "selection.json"
    before = history.read_bytes()
    result = finalize_diagnostic_selection(history, checkpoints, output)
    assert result["epoch"] == 2
    assert result["selector_value"] == 1
    assert result["checkpoint"]["name"] == "epoch_0002.pt"
    assert result["status"] == "DIAGNOSTIC_ONLY"
    assert result["candidate_gate"] == "INCOMPLETE"
    assert result["resume_supported"] is False
    assert result["history_sha256"] == sha256_bytes(before)
    assert history.read_bytes() == before
    saved = output.read_bytes()
    with pytest.raises((ValueError, OSError)):
        finalize_diagnostic_selection(history, checkpoints, output)
    assert output.read_bytes() == saved


@pytest.mark.parametrize("damage", [
    "equal_step", "bool_epoch", "negative_loss", "bool_loss", "nan_loss", "missing_loss",
    "traversal", "checkpoint", "receipt_prefix", "receipt_bool_epoch", "receipt_missing",
    "checkpoint_symlink", "receipt_symlink", "blank_line", "no_newline", "empty", "history_tamper",
])
def test_diagnostic_selection_rejects_incomplete_or_tampered_artifacts(tmp_path, damage):
    history, checkpoints, rows = diagnostic_selection_fixture(tmp_path)
    output = tmp_path / "selection.json"
    checkpoint = checkpoints / "epoch_0001.pt"
    receipt_path = checkpoint.with_suffix(".receipt.json")
    if damage in {"equal_step", "bool_epoch", "negative_loss", "bool_loss", "nan_loss", "missing_loss",
                  "traversal", "history_tamper"}:
        if damage == "equal_step":
            rows[1]["global_step"] = rows[0]["global_step"]
        elif damage == "bool_epoch":
            rows[0]["epoch"] = True
        elif damage == "missing_loss":
            rows[0]["validation"] = {}
        elif damage in {"negative_loss", "bool_loss", "nan_loss"}:
            rows[0]["validation"]["losses"]["total_loss"]["value"] = {
                "negative_loss": -1, "bool_loss": True, "nan_loss": float("nan"),
            }[damage]
        elif damage == "traversal":
            rows[0]["checkpoint"]["name"] = "../epoch_0001.pt"
        else:
            rows[0]["additional"] = "changed"
        history.write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in rows))
    elif damage == "checkpoint":
        checkpoint.write_bytes(b"different weights")
    elif damage in {"receipt_prefix", "receipt_bool_epoch"}:
        receipt = json.loads(receipt_path.read_text())
        receipt["history_prefix_sha256" if damage == "receipt_prefix" else "epoch"] = (
            "0" * 64 if damage == "receipt_prefix" else True)
        receipt_path.write_text(json.dumps(receipt))
    elif damage == "receipt_missing":
        receipt_path.unlink()
    elif damage in {"checkpoint_symlink", "receipt_symlink"}:
        path = checkpoint if damage == "checkpoint_symlink" else receipt_path
        target = tmp_path / "linked-target"
        path.rename(target)
        path.symlink_to(target)
    elif damage == "blank_line":
        history.write_bytes(history.read_bytes() + b"\n")
    elif damage == "no_newline":
        history.write_bytes(history.read_bytes()[:-1])
    else:
        history.write_bytes(b"")
    with pytest.raises((ValueError, OSError)):
        finalize_diagnostic_selection(history, checkpoints, output)
    assert not output.exists()


class Model:
    def __init__(self):
        self.calls = 0

    def encode(self, imgs):
        self.calls += 1
        return imgs, [imgs[:, i] for i in range(imgs.shape[1])]


def batch(n, value, frames=2):
    return {"imgs": torch.full((n, frames, 1), float(value)),
            "coords": torch.zeros(n, frames, 1, 3), "masks": torch.ones(n, frames, 1)}


def evaluate(model, loader, device, **kwargs):
    for item in loader:
        model.encode(item["imgs"])
    return 2.0, 0.75, 0.8


API = SimpleNamespace(evaluate=evaluate, compute_detection_loss=lambda logits, coords, masks, weight: logits.mean())


def test_reports_weighted_components_without_second_inference():
    model = Model()
    legacy, report = evaluate_components(API, model, [batch(2, 1), batch(1, 4)], "cpu",
                                         det_loss_weight=3, det_neg_weight=0.01)
    assert legacy == (2.0, 0.75, 0.8)
    assert model.calls == 2
    assert report["losses"]["det_loss"]["numerator"] == 6
    assert report["losses"]["det_loss"]["value"] == 2
    assert report["losses"]["total_loss"]["value"] == 8
    assert report["examples"] == 3


@pytest.mark.parametrize("items", [[], [batch(1, float("nan"))], [batch(1, 1), batch(1, 1, 3)]])
def test_invalid_validation_fails(items):
    with pytest.raises(ValueError):
        evaluate_components(API, Model(), items, "cpu", det_loss_weight=1, det_neg_weight=0.01)


def test_invalid_weight_fails_before_forward():
    model = Model()
    with pytest.raises(ValueError):
        evaluate_components(API, model, [batch(1, 1)], "cpu", det_loss_weight=float("nan"), det_neg_weight=0.01)
    assert model.calls == 0


def test_zero_recall_is_not_reported_as_tracking_success():
    def zero_evaluate(model, loader, device, **kwargs):
        for item in loader:
            model.encode(item["imgs"])
        return 0.0, 0.0, 0.0

    api = SimpleNamespace(evaluate=zero_evaluate, compute_detection_loss=API.compute_detection_loss)
    legacy, report = evaluate_components(api, Model(), [batch(1, 1)], "cpu",
                                         det_loss_weight=1, det_neg_weight=0.01)
    assert legacy == (0, 0, 0)
    assert report["warnings"] == ["NO_GT_MATCHES_TRACKING_LOSS_NOT_INFORMATIVE"]


def test_diagnostic_history_counts_real_steps_and_survives_incomplete_epoch(tmp_path):
    path = tmp_path / "diagnostic_history.jsonl"
    parameter = torch.nn.Parameter(torch.tensor(1.0))
    optimizer = torch.optim.SGD([parameter], lr=0.1)

    def training(model, loader, opt):
        for _ in range(2):
            opt.zero_grad()
            parameter.square().backward()
            recorder.clip_grad_norm([parameter], 1.0)
            opt.step()
        return 0.2, 0.3

    recorder = DiagnosticRecorder(path, det_loss_weight=0.4)
    try:
        recorder.train_epoch(training, None, None, optimizer)
        recorder.validation({"det_loss_weight": 0.4, "status": "DIAGNOSTIC_ONLY"})
        first_bytes = path.read_bytes()
        row = json.loads(first_bytes)
        assert row["global_step"] == 2
        assert row["train"]["total_loss"] == pytest.approx(0.32)
        assert row["candidate_gate"] == "INCOMPLETE"
        assert row["resume_supported"] is False
        assert row["train"]["grad_norm_pre_clip"]["max"] == pytest.approx(2.0)
        assert row["train"]["grad_norm_pre_clip"]["checked_steps"] == 2
        recorder.train_epoch(training, None, None, optimizer)
        assert path.read_bytes() == first_bytes  # no fake completion before validation
        with pytest.raises(ValueError, match="Previous epoch"):
            recorder.train_epoch(training, None, None, optimizer)
        recorder.validation({"det_loss_weight": 0.4, "status": "DIAGNOSTIC_ONLY"})
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert [row["global_step"] for row in rows] == [2, 4]
        assert [row["epoch"] for row in rows] == [1, 2]
        assert path.read_bytes().startswith(first_bytes)
    finally:
        recorder.close()
    assert not optimizer._optimizer_step_post_hooks
    assert not optimizer._optimizer_step_pre_hooks


@pytest.mark.parametrize("bad_gradient", [float("nan"), float("inf")])
def test_nonfinite_gradient_stops_before_optimizer_update(tmp_path, bad_gradient):
    recorder = DiagnosticRecorder(tmp_path / "history.jsonl", det_loss_weight=1)
    parameter = torch.nn.Parameter(torch.tensor(1.0))
    optimizer = torch.optim.SGD([parameter], lr=0.1)

    def training(model, loader, opt):
        parameter.grad = torch.tensor(bad_gradient)
        recorder.clip_grad_norm([parameter], 1.0)
        opt.step()
        return 0.1, 0.1

    try:
        with pytest.raises(RuntimeError, match="non-finite"):
            recorder.train_epoch(training, None, None, optimizer)
        assert parameter.item() == 1.0
        assert (tmp_path / "history.jsonl").read_bytes() == b""
    finally:
        recorder.close()
    assert not optimizer._optimizer_step_pre_hooks
    assert not optimizer._optimizer_step_post_hooks


def test_missing_gradient_check_stops_optimizer(tmp_path):
    recorder = DiagnosticRecorder(tmp_path / "history.jsonl", det_loss_weight=1)
    parameter = torch.nn.Parameter(torch.tensor(1.0))
    optimizer = torch.optim.SGD([parameter], lr=0.1)

    def training(model, loader, opt):
        parameter.square().backward()
        opt.step()
        return 0.1, 0.1

    try:
        with pytest.raises(ValueError, match="pre-clip"):
            recorder.train_epoch(training, None, None, optimizer)
        assert parameter.item() == 1.0
    finally:
        recorder.close()


@pytest.mark.parametrize("device_name", ["cpu", "mps"])
def test_official_model_validation_parity(monkeypatch, device_name, tmp_path):
    if device_name == "mps" and not torch.backends.mps.is_available():
        pytest.skip("MPS unavailable on this host")
    device = torch.device(device_name)
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "official/src"))
    monkeypatch.syspath_prepend(str(root / "official/scripts"))
    spec = importlib.util.spec_from_file_location("_validation_parity_trainer",
                                               root / "official/scripts/train_unet_transformer.py")
    api = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, api)
    api._local_device = device
    api._local_synchronize = torch.mps.synchronize if device_name == "mps" else lambda: None
    api._local_checked_loss = checked_loss
    exec(adapted_code(Path(spec.origin).read_text(), spec.origin), api.__dict__)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(7)
        model = api.UNetNodeTransformer(
            api.TemporalUNet3D(in_channels=1, out_channels=4, layers=[4, 8]),
            unet_out_channels=4, pos_feat_dim=32, hidden_dim=8, n_heads=2, n_blocks=1, dropout=0,
        ).to(device)
        item = {
            "imgs": torch.randn(1, 2, 8, 8, 8),
            "coords": torch.tensor([[[[3., 3., 3.]], [[3., 3., 3.]]]]),
            "masks": torch.ones(1, 2, 1, dtype=torch.bool),
            "pos_feats": torch.zeros(1, 2, 1, 32),
            "targets": torch.ones(1, 1, 1, 1),
            "image_shape": torch.tensor([[2, 8, 8, 8]]),
            "voxel_size": torch.ones(1, 3), "downsample": torch.ones(1, 3),
        }
        expected = api.evaluate(model, [item], device)
        observed, report = evaluate_components(api, model, [item], device,
                                               det_loss_weight=0.4, det_neg_weight=0.01)
        assert observed == pytest.approx(expected, abs=1e-7)
        with torch.no_grad():
            _, logits = model.encode(item["imgs"].to(device))
            det = sum(api.compute_detection_loss(logits[i], item["coords"][:, i].to(device),
                                                item["masks"][:, i].to(device), 0.01) for i in range(2)) / 2
        assert report["losses"]["det_loss"]["value"] == pytest.approx(det.item())
        assert report["losses"]["total_loss"]["value"] == pytest.approx(expected[0] + 0.4 * det.item())
        recorder = DiagnosticRecorder(tmp_path / "history.jsonl", det_loss_weight=0.4,
                                      checkpoint_dir=tmp_path / "checkpoints")
        api._local_clip_grad_norm = recorder.clip_grad_norm
        optimizer = torch.optim.AdamW(model.parameters(), lr=0.001)
        before = model.detect_head.weight.detach().clone()
        try:
            recorder.train_epoch(api.train_epoch, model, [item], optimizer, device,
                                 det_loss_weight=0.4, det_neg_weight=0.01, max_iters=1)
            _, after_report = evaluate_components(api, model, [item], device,
                                                 det_loss_weight=0.4, det_neg_weight=0.01)
            recorder.validation(after_report)
        finally:
            recorder.close()
        row = json.loads((tmp_path / "history.jsonl").read_text())
        assert row["global_step"] == row["train"]["grad_norm_pre_clip"]["checked_steps"] == 1
        assert not torch.equal(before, model.detect_head.weight)
        checkpoint = tmp_path / "checkpoints/epoch_0001.pt"
        saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
        assert saved["global_step"] == 1
        assert saved["resume_supported"] is False
        assert saved["optimizer"]["state"]
        assert torch.equal(saved["model"]["detect_head.weight"], model.detect_head.weight.detach().cpu())
        receipt = json.loads(checkpoint.with_suffix(".receipt.json").read_text())
        import hashlib
        assert receipt["checkpoint"]["sha256"] == hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        assert receipt["history_prefix_sha256"] == hashlib.sha256((tmp_path / "history.jsonl").read_bytes()).hexdigest()
        selection = finalize_diagnostic_selection(
            tmp_path / "history.jsonl", tmp_path / "checkpoints", tmp_path / "diagnostic_selection.json",
        )
        assert selection["epoch"] == 1
        assert selection["selector_value"] == after_report["losses"]["total_loss"]["value"]
        assert selection["checkpoint"]["sha256"] == receipt["checkpoint"]["sha256"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0])
def test_loss_rejected_before_backward(value):
    loss = torch.tensor(value, requires_grad=True)
    with pytest.raises(ValueError, match="finite nonnegative"):
        checked_loss(loss).backward()
    assert loss.grad is None


def test_empty_video_cannot_silently_disappear():
    with pytest.raises(ValueError, match="No usable annotated windows"):
        validate_window_coverage([], source="44b6_example")
    with pytest.raises(ValueError, match="No annotated positive"):
        validate_window_coverage([SimpleNamespace(targets=[torch.zeros(1, 1)])], source="44b6_example")
    report = validate_window_coverage([SimpleNamespace(targets=[torch.eye(2)])], source="44b6_example")
    assert report["windows"] == 1
    assert report["positive_edge_occurrences"] == 2


def test_warm_start_hash_and_full_structure(tmp_path):
    path = tmp_path / "weights.pt"
    source = torch.nn.Linear(2, 1)
    target = torch.nn.Linear(2, 1)
    torch.save(source.state_dict(), path)
    digest = sha256_file(path)
    before = target.weight.detach().clone()
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        strict_warm_start(target, path, "0" * 64)
    assert torch.equal(before, target.weight)
    with pytest.raises(ValueError, match="tensor mismatch"):
        strict_warm_start(torch.nn.Linear(3, 1), path, digest)
    receipt = strict_warm_start(target, path, digest)
    assert receipt["mode"] == "full_strict"
    assert torch.equal(source.weight, target.weight)


def test_warm_start_rejects_nonfinite_before_mutation(tmp_path):
    model = torch.nn.Linear(2, 1)
    before = model.weight.detach().clone()
    state = {k: v.clone() for k, v in model.state_dict().items()}
    state["bias"].fill_(float("nan"))
    path = tmp_path / "bad.pt"
    torch.save(state, path)
    with pytest.raises(ValueError, match="nonfinite"):
        strict_warm_start(model, path, sha256_file(path))
    assert torch.equal(model.weight, before)


def test_freeze_keeps_detector_output_and_buffers_while_association_trains():
    model = torch.nn.Module()
    model.unet = torch.nn.Sequential(torch.nn.Linear(3, 3), torch.nn.BatchNorm1d(3), torch.nn.Dropout(0.5))
    model.detect_head = torch.nn.Linear(3, 1)
    model.transformer = torch.nn.Linear(1, 1)
    verify = freeze_detector(model)
    x = torch.ones(4, 3)
    before = model.detect_head(model.unet(x)).detach().clone()
    association_before = model.transformer.bias.detach().clone()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    model.train()
    assert model.transformer.training
    model.transformer(model.detect_head(model.unet(x))).sum().backward()
    optimizer.step()
    verify()
    assert torch.equal(before, model.detect_head(model.unet(x)))
    assert not torch.equal(association_before, model.transformer.bias)
    with torch.no_grad():
        model.detect_head.bias.add_(1)
    with pytest.raises(ValueError, match="state changed"):
        verify()


def test_input_manifest_pins_consumed_frames_and_rejects_missing_chunk(tmp_path):
    stem = "44b6_example"
    image = tmp_path / f"{stem}.zarr"
    annotation = tmp_path / f"{stem}.geff"
    (image / "0").mkdir(parents=True)
    annotation.mkdir()
    (image / "zarr.json").write_text("{}")
    (annotation / "zarr.json").write_text("{}")
    (image / "0/zarr.json").write_text(json.dumps({
        "shape": [100, 2, 2, 2], "chunk_grid": {"configuration": {"chunk_shape": [1, 2, 2, 2]}},
        "chunk_key_encoding": {"name": "default", "configuration": {"separator": "/"}},
    }))
    for frame in (0, 1):
        chunk = image / f"0/c/{frame}/0/0/0"
        chunk.parent.mkdir(parents=True)
        chunk.write_bytes(bytes([frame]))
    split = {"train": [stem], "test": []}
    inventory = diagnostic_input_manifest(tmp_path, split, 2)
    assert len(inventory) == 5
    assert all(len(entry["sha256"]) == 64 for entry in inventory)
    with pytest.raises(ValueError, match="Missing"):
        diagnostic_input_manifest(tmp_path, split, 3)
