import copy
import json
from types import SimpleNamespace

import pytest
import torch
from test_association_training import SmallModel, small_batch

from biohub.association_probe import assert_same_probe, capture_probe, describe_probe


def detected(logits, coords, masks, **kwargs):
    assert not torch.is_grad_enabled()
    assert kwargs["window_size"] == 2
    return coords + 7, None, ~masks, None


def test_probe_captures_detections_not_ground_truth_and_preserves_modes():
    model = SmallModel()
    model.child = torch.nn.Dropout()
    model.child.eval()
    batch = small_batch()
    rng = torch.get_rng_state().clone()
    a = capture_probe(SimpleNamespace(detect_and_match=detected), model, batch, "cpu")
    b = capture_probe(SimpleNamespace(detect_and_match=detected), model, batch, "cpu")
    assert_same_probe(a, b)
    assert torch.equal(a["coords/0"], batch["coords"][:, 0] + 7)
    assert torch.equal(a["masks/0"], ~batch["masks"][:, 0])
    assert all(not value.requires_grad and value.device.type == "cpu" for value in a.values())
    assert model.training and not model.child.training
    assert torch.equal(rng, torch.get_rng_state())
    json.dumps(describe_probe(a), allow_nan=False)
    batch["imgs"].zero_()
    assert a["logits/0"].sum() > 0  # Detached copy, not an alias.


@pytest.mark.parametrize("mutation", ["value", "shape", "dtype", "key"])
def test_probe_rejects_changes(mutation):
    a = capture_probe(SimpleNamespace(detect_and_match=detected), SmallModel(), small_batch(), "cpu")
    b = copy.deepcopy(a)
    if mutation == "value":
        b["coords/1"] += 1
    elif mutation == "shape":
        b["coords/1"] = b["coords/1"].flatten()
    elif mutation == "dtype":
        b["coords/1"] = b["coords/1"].double()
    else:
        del b["coords/1"]
    with pytest.raises(ValueError):
        assert_same_probe(a, b)


@pytest.mark.parametrize("failure", ["input", "window", "detector"])
def test_probe_restores_modes_on_failure(failure):
    model = SmallModel()
    model.child = torch.nn.Dropout()
    model.child.eval()
    batch = small_batch()
    if failure == "input":
        batch["imgs"].fill_(float("nan"))
    elif failure == "window":
        batch["imgs"] = batch["imgs"][:, :1]

    def fail(*args, **kwargs):
        raise ValueError("Detector failed")

    with pytest.raises(ValueError):
        capture_probe(SimpleNamespace(detect_and_match=fail), model, batch, "cpu")
    assert model.training and not model.child.training
