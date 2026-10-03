import copy
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from biohub.association_probe import assert_same_probe, capture_probe
from biohub.association_training import _aggregate, _count_metrics, run_epoch
from biohub.local_training import checked_loss, evaluate_components, freeze_detector
from scripts.local_train_unet_transformer import adapted_code


class SmallModel(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.logits = torch.nn.Parameter(torch.tensor([[2.0, 0.0], [0.0, 2.0]]))
        self.calls = 0

    def encode(self, imgs):
        self.calls += 1
        return imgs.unsqueeze(2), [imgs[:, i].unsqueeze(1) for i in range(2)]

    def _index_features(self, features, coords, masks):
        return features.new_zeros((1, coords.shape[1], 1))

    def predict_edges(self, *args):
        return self.logits.unsqueeze(0)


def small_batch(value=1.0):
    return {
        "imgs": torch.full((1, 2, 1, 2, 2), value),
        "coords": torch.zeros(1, 2, 2, 3), "masks": torch.ones(1, 2, 2, dtype=torch.bool),
        "targets": torch.eye(2).reshape(1, 1, 2, 2),
        "image_shape": torch.tensor([[2, 1, 2, 2]]),
        "voxel_size": torch.ones(1, 3), "downsample": torch.ones(1, 3),
    }


def match(logits, coords, masks, image_shape, **kwargs):
    return coords, coords.new_zeros(1, 2, 32), masks, [torch.arange(2, device=coords.device)]


API = SimpleNamespace(
    compute_detection_loss=lambda logits, *args: logits.square().mean(),
    detect_and_match=match,
    build_matched_edge_targets=lambda a, b, target, ns, nt: target,
    compute_batch_loss=lambda logits, target, *args: (logits.softmax(dim=1) - target).square().mean(),
)


def test_real_optimizer_steps_counts_and_no_arg_guard():
    model = SmallModel()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    before = model.logits.detach().clone()
    calls = []
    result = run_epoch(API, model, [("44b6_a", "a:0", small_batch())], "cpu",
                       optimizer=optimizer, detector_guard=lambda: calls.append(True))
    assert result["optimizer_steps"] == 1
    assert result["grad_norm_pre_clip"]["checked_steps"] == 1
    assert result["grad_norm_pre_clip"]["clip_threshold"] == 1
    assert result["grad_norm_pre_clip"]["last"] >= 0
    assert len(calls) == 2
    assert not torch.equal(before, model.logits)
    assert result["counts"]["tp"] == 2
    assert result["counts"]["tn"] == 2
    assert result["task_metrics"]["precision"] == 1


def test_audit_total_reconstructs_components_and_retains_actual_float32_objective():
    edge, det = torch.tensor(0.1), torch.tensor(1.0)
    actual = (edge + det).item()
    report = _aggregate([{"edge_loss": edge.item(), "det_loss": det.item(), "total_loss": actual,
                          "counts": {"tp": 1, "fp": 0, "fn": 0, "tn": 1}, "node_matched": 1, "node_gt": 1}])
    assert report["losses"]["total_loss"]["value"] == edge.item() + det.item()
    assert report["objective_total_loss"]["value"] == actual
    assert report["losses"]["total_loss"]["value"] != actual


def test_lineages_pool_windows_not_video_means_and_eval_has_no_steps():
    model = SmallModel()
    items = [("44b6_a", "a:0", small_batch(0.0)),
             ("44b6_b", "b:0", small_batch(2.0)), ("44b6_b", "b:1", small_batch(2.0)),
             ("6bba_c", "c:0", small_batch(1.0))]
    before = model.logits.detach().clone()
    result = run_epoch(API, model, items, "cpu")
    assert result["optimizer_steps"] == 0
    assert result["grad_norm_pre_clip"] is None
    assert torch.equal(before, model.logits) and model.logits.grad is None
    assert set(result["by_lineage"]) == {"44b6", "6bba"}
    loss = result["by_lineage"]["44b6"]["losses"]["det_loss"]
    assert loss == {"value": 8 / 3, "numerator": 8.0, "denominator": 3, "reduction": "sum_over_windows"}
    assert result["by_video"]["44b6_b"]["examples"] == 2
    assert result["counts"]["tp"] == 8
    assert result["by_lineage"]["44b6"]["counts"]["tp"] == 6
    assert result["example_ids"] == [x[1] for x in items]


def test_metrics_ignore_unannotated_cells_and_keep_undefined_precision():
    logits = torch.tensor([[4.0, -4.0], [-4.0, 4.0]])
    target = torch.tensor([[1.0, 0.0], [0.0, 0.0]])
    assert _count_metrics(logits, target) == {"tp": 1, "fp": 0, "fn": 0, "tn": 2}
    model = SmallModel()
    with torch.no_grad():
        model.logits.zero_()
    result = run_epoch(API, model, [("44b6_a", "a:0", small_batch())], "cpu")
    assert result["task_metrics"]["precision"] is None
    assert result["task_metrics"]["recall"] == 0
    assert result["counts"]["fn"] == 2


def test_nonfinite_logit_outside_annotation_mask_is_rejected():
    logits = torch.tensor([[1.0, 0.0], [0.0, float("nan")]])
    with pytest.raises(ValueError):
        _count_metrics(logits, torch.tensor([[1.0, 0.0], [0.0, 0.0]]))


@pytest.mark.parametrize("damage", ["lineage", "batch_size", "window", "mask_dtype", "target_shape", "empty_id"])
def test_invalid_example_fails_before_forward(damage):
    model, batch, video, example = SmallModel(), small_batch(), "44b6_a", "a:0"
    if damage == "lineage":
        video = "unknown_a"
    elif damage == "batch_size":
        batch["imgs"] = batch["imgs"].repeat(2, 1, 1, 1, 1)
    elif damage == "window":
        batch["imgs"] = batch["imgs"][:, :1]
    elif damage == "mask_dtype":
        batch["masks"] = batch["masks"].float()
    elif damage == "target_shape":
        batch["targets"] = torch.zeros(1, 1, 3, 3)
    else:
        example = ""
    with pytest.raises((ValueError, TypeError)):
        run_epoch(API, model, [(video, example, batch)], "cpu")
    assert model.calls == 0


def test_empty_and_duplicate_epochs_rejected():
    with pytest.raises(ValueError):
        run_epoch(API, SmallModel(), [], "cpu")
    item = ("44b6_a", "a:0", small_batch())
    with pytest.raises(ValueError):
        run_epoch(API, SmallModel(), [item, item], "cpu")


@pytest.mark.parametrize("damage", ["loss", "gradient", "optimizer"])
def test_bad_training_stops_before_step(damage):
    model = SmallModel()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    before = model.logits.detach().clone()
    api = copy.copy(API)
    if damage == "loss":
        api.compute_detection_loss = lambda *args: torch.tensor(float("nan"))
    elif damage == "gradient":
        model.logits.register_hook(lambda grad: torch.full_like(grad, float("nan")))
    else:
        optimizer = torch.optim.SGD([torch.nn.Parameter(torch.ones(1))], lr=0.1)
    with pytest.raises((ValueError, RuntimeError)):
        run_epoch(api, model, [("44b6_a", "a:0", small_batch())], "cpu", optimizer=optimizer)
    assert torch.equal(before, model.logits)


@pytest.mark.parametrize("device_name", ["cpu", "mps"])
def test_official_model_train_and_eval_parity(monkeypatch, device_name):
    if device_name == "mps" and not torch.backends.mps.is_available():
        pytest.skip("MPS unavailable")
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "official/src"))
    monkeypatch.syspath_prepend(str(root / "official/scripts"))
    source = root / "official/scripts/train_unet_transformer.py"
    spec = importlib.util.spec_from_file_location("_association_parity_trainer", source)
    api = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, api)
    device = torch.device(device_name)
    api._local_device = device
    api._local_synchronize = torch.mps.synchronize if device_name == "mps" else lambda: None
    api._local_checked_loss = checked_loss
    api._local_clip_grad_norm = torch.nn.utils.clip_grad_norm_
    exec(adapted_code(source.read_text(), str(source)), api.__dict__)
    model = api.UNetNodeTransformer(
        api.TemporalUNet3D(in_channels=1, out_channels=4, layers=[4, 8]),
        unet_out_channels=4, pos_feat_dim=32, hidden_dim=8, n_heads=2, n_blocks=1, dropout=0,
    ).to(device)
    batch = {"imgs": torch.randn(1, 2, 8, 8, 8),
             "coords": torch.tensor([[[[3., 3., 3.]], [[3., 3., 3.]]]]),
             "masks": torch.ones(1, 2, 1, dtype=torch.bool), "pos_feats": torch.zeros(1, 2, 1, 32),
             "targets": torch.ones(1, 1, 1, 1), "image_shape": torch.tensor([[2, 8, 8, 8]]),
             "voxel_size": torch.ones(1, 3), "downsample": torch.ones(1, 3)}
    legacy, expected = evaluate_components(api, model, [batch], device, det_loss_weight=0.4, det_neg_weight=0.01)
    observed = run_epoch(api, model, [("44b6_a", "a:0", batch)], device, det_loss_weight=0.4)
    for component in ("edge_loss", "det_loss", "total_loss"):
        assert observed["losses"][component]["value"] == pytest.approx(
            expected["losses"][component]["value"], rel=1e-5, abs=1e-7)
    if observed["task_metrics"]["accuracy"] is not None:
        assert observed["task_metrics"]["accuracy"] == pytest.approx(legacy[1])
    assert observed["task_metrics"]["node_recall"] == pytest.approx(legacy[2])
    control = copy.deepcopy(model)
    control_opt = torch.optim.SGD(control.parameters(), lr=0.001)
    candidate_opt = torch.optim.SGD(model.parameters(), lr=0.001)
    edge, det = api.train_epoch(control, [batch], control_opt, device,
                                det_loss_weight=0.4, det_neg_weight=0.01)
    trained = run_epoch(api, model, [("44b6_a", "a:0", batch)], device,
                        optimizer=candidate_opt, det_loss_weight=0.4)
    assert trained["losses"]["edge_loss"]["value"] == pytest.approx(edge, rel=1e-5, abs=1e-7)
    assert trained["losses"]["det_loss"]["value"] == pytest.approx(det, rel=1e-5, abs=1e-7)
    for key, value in model.state_dict().items():
        torch.testing.assert_close(value, control.state_dict()[key], rtol=1e-5, atol=1e-7)
    model.zero_grad(set_to_none=True)
    guard = freeze_detector(model)
    detector_before = capture_probe(api, model, batch, device)
    association_optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=1e-5)
    frozen = run_epoch(api, model, [("44b6_a", "a:0", batch)], device,
                       optimizer=association_optimizer, det_loss_weight=0.4, detector_guard=guard)
    guard()
    assert_same_probe(detector_before, capture_probe(api, model, batch, device))
    assert frozen["optimizer_steps"] == frozen["grad_norm_pre_clip"]["checked_steps"] == 1
