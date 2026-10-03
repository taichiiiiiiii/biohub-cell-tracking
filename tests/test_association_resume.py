import base64
import copy
import hashlib
import io
import pickle
import random

import numpy as np
import pytest
import torch

from biohub.association_resume import (
    build_artifact_state,
    capture_state,
    restore_state,
    state_from_artifact,
)
from biohub.training_history import (
    _validate_hashed_state_payload,
    _validate_rng_payload,
    canonical_sha256,
    trusted_pytorch_checkpoint_metadata_loader,
)


def model_and_optimizer(device="cpu"):
    model = torch.nn.Sequential(torch.nn.Linear(4, 8), torch.nn.Dropout(0.3), torch.nn.Linear(8, 2)).to(device)
    return model, torch.optim.AdamW(model.parameters(), lr=1e-3)


def step(model, optimizer, generator, device):
    order = torch.randperm(8, generator=generator)
    scale = random.random() + float(np.random.random()) + float(torch.rand(()))
    x = torch.randn(8, 4, device=device) * scale
    loss = model(x).square().mean()
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    return order, scale, loss.item()


@pytest.mark.parametrize("device", ["cpu", "mps"])
@pytest.mark.parametrize("artifact", [False, True])
def test_safe_checkpoint_roundtrip_continues_actual_dropout_and_adam(device, artifact):
    if device == "mps" and not torch.backends.mps.is_available():
        pytest.skip("MPS unavailable")
    before = (random.getstate(), np.random.get_state(), torch.get_rng_state(),
              torch.mps.get_rng_state() if device == "mps" else None)
    try:
        model, optimizer = model_and_optimizer(device)
        generator = torch.Generator().manual_seed(20260922)
        step(model, optimizer, generator, device)
        state = capture_state(model, optimizer, generator, device)
        frozen_model = copy.deepcopy(state["model"])
        frozen_optimizer = copy.deepcopy(state["optimizer"])
        expected = step(model, optimizer, generator, device)
        for key in frozen_model:
            assert torch.equal(state["model"][key], frozen_model[key])
        torch.testing.assert_close(state["optimizer"], frozen_optimizer, rtol=0, atol=0)
        stream = io.BytesIO()
        torch.save(build_artifact_state(state, {}) if artifact else state, stream)
        stream.seek(0)
        loaded = torch.load(stream, map_location="cpu", weights_only=True)
        if artifact:
            loaded = state_from_artifact(loaded)
        resumed, resumed_optimizer = model_and_optimizer(device)
        resumed_generator = torch.Generator().manual_seed(123)
        restore_state(loaded, resumed, resumed_optimizer, resumed_generator, device)
        observed = step(resumed, resumed_optimizer, resumed_generator, device)
        assert torch.equal(observed[0], expected[0])
        assert observed[1] == expected[1]
        assert observed[2] == pytest.approx(expected[2], rel=1e-5, abs=1e-7)
        torch.testing.assert_close(resumed.state_dict(), model.state_dict(), rtol=1e-5, atol=1e-7)
        torch.testing.assert_close(resumed_optimizer.state_dict(), optimizer.state_dict(), rtol=1e-5, atol=1e-7)
        assert ("torch_mps" in loaded["rng"]) == (device == "mps")
    finally:
        random.setstate(before[0])
        np.random.set_state(before[1])
        torch.set_rng_state(before[2])
        if device == "mps":
            torch.mps.set_rng_state(before[3])


def test_cpu_capture_and_restore_do_not_touch_accelerator_rng(monkeypatch):
    for module, names in ((torch.cuda, ("get_rng_state_all", "set_rng_state_all")),
                          (torch.mps, ("get_rng_state", "set_rng_state"))):
        for name in names:
            monkeypatch.setattr(module, name, lambda *args: pytest.fail("Unselected accelerator RNG accessed"))
    model, optimizer = model_and_optimizer()
    generator = torch.Generator()
    state = capture_state(model, optimizer, generator, "cpu")
    restore_state(state, model, optimizer, generator, "cpu")


def test_artifact_state_matches_existing_safe_loader_contract(tmp_path):
    model, optimizer = model_and_optimizer()
    generator = torch.Generator()
    step(model, optimizer, generator, "cpu")
    captured = capture_state(model, optimizer, generator, "cpu")
    artifact = build_artifact_state(captured, {"epoch": 1})
    artifact["model"]["payload"]["state_dict"]["0.weight"].add_(1)
    assert not torch.equal(captured["model"]["0.weight"], artifact["model"]["payload"]["state_dict"]["0.weight"])
    artifact = build_artifact_state(captured, {"epoch": 1})
    path = tmp_path / "state.pt"
    torch.save({"model_state": captured["model"], "state": artifact}, path)
    metadata = trusted_pytorch_checkpoint_metadata_loader(path)
    errors = []
    for name in ("model", "optimizer", "scheduler", "scaler", "sampler"):
        _validate_hashed_state_payload(metadata["state"][name], artifact[name]["type"], name, errors)
    for name, payload in metadata["state"]["rng"].items():
        _validate_rng_payload(payload, name, errors)
    assert not errors
    assert metadata["model_state"] == metadata["state"]["model"]["payload"]["state_dict"]


@pytest.mark.parametrize("damage", [
    "model", "optimizer", "sampler", "scheduler", "scaler", "rng_hash", "rng_extra", "pickle",
])
def test_artifact_rejects_hash_schema_and_unsafe_load(damage, monkeypatch):
    model, optimizer = model_and_optimizer()
    artifact = build_artifact_state(capture_state(model, optimizer, torch.Generator(), "cpu"), {})
    if damage in ("model", "optimizer", "sampler"):
        artifact[damage]["payload"]["sha256"] = "0" * 64
    elif damage in ("scheduler", "scaler"):
        payload = artifact[damage]["payload"]
        payload["state_dict"] = {"enabled": True}
        payload["sha256"] = canonical_sha256(payload["state_dict"])
    elif damage == "rng_hash":
        artifact["rng"]["python"]["sha256"] = "0" * 64
    elif damage == "rng_extra":
        artifact["rng"]["extra"] = artifact["rng"]["python"]
    else:
        # Valid bytes/hash, but disallowed object: no unsafe torch.load fallback.
        stream = io.BytesIO()
        torch.save(random.Random(1), stream)
        data = stream.getvalue()
        artifact["rng"]["python"] = {"encoding": "base64", "value": base64.b64encode(data).decode(),
                                      "sha256": hashlib.sha256(data).hexdigest()}
    real_load = torch.load
    calls = []

    def checked_load(*args, **kwargs):
        calls.append(kwargs)
        assert kwargs == {"map_location": "cpu", "weights_only": True}
        return real_load(*args, **kwargs)

    monkeypatch.setattr(torch, "load", checked_load)
    with pytest.raises(pickle.UnpicklingError if damage == "pickle" else ValueError):
        state_from_artifact(artifact)
    if damage != "pickle":
        assert not calls


@pytest.mark.parametrize("damage", ["shape", "dtype", "keys", "model_nan", "optimizer_nan", "optimizer_names",
                                    "optimizer_type", "sampler", "cpu_rng", "numpy", "rng_extra", "device"])
def test_bad_state_rejected_before_model_or_rng_mutation(damage):
    source, source_optimizer = model_and_optimizer()
    generator = torch.Generator()
    step(source, source_optimizer, generator, "cpu")
    state = capture_state(source, source_optimizer, generator, "cpu")
    target, optimizer = model_and_optimizer()
    before_model = copy.deepcopy(target.state_dict())
    before_rng = torch.get_rng_state().clone()
    if damage == "shape":
        state["model"]["0.weight"] = torch.zeros(1)
    elif damage == "dtype":
        state["model"]["0.weight"] = state["model"]["0.weight"].double()
    elif damage == "keys":
        state["model"].pop("0.weight")
    elif damage == "model_nan":
        state["model"]["0.weight"].fill_(float("nan"))
    elif damage == "optimizer_nan":
        state["optimizer"]["param_groups"][0]["lr"] = float("nan")
    elif damage == "optimizer_names":
        state["optimizer_identity"]["parameter_names"][0].reverse()
    elif damage == "optimizer_type":
        state["optimizer_identity"]["type"] = "torch.optim.sgd.SGD"
    elif damage == "sampler":
        state["sampler"] = torch.zeros(1, dtype=torch.uint8)
    elif damage == "cpu_rng":
        state["rng"]["torch_cpu"] = torch.zeros(1, dtype=torch.uint8)
    elif damage == "numpy":
        state["rng"]["numpy"][2] = -1
    elif damage == "rng_extra":
        state["rng"]["torch_mps"] = torch.zeros(44, dtype=torch.uint8)
    else:
        state["device"] = "mps"
    with pytest.raises((ValueError, RuntimeError, TypeError)):
        restore_state(state, target, optimizer, generator, "cpu")
    for key, value in target.state_dict().items():
        assert torch.equal(value, before_model[key])
    assert torch.equal(torch.get_rng_state(), before_rng)
