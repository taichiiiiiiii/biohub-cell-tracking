"""Qwen-authored state capture/restore, reviewed for the candidate run adapter.

The caller must verify checkpoint hashes, provenance and history before restore,
then perform validation readback. These functions alone do not pass that gate.
Only tensors and plain Python values are serialized, for weights-only loading.
"""

import base64
import copy
import hashlib
import io
import math
import random

import numpy as np
import torch

from biohub.association_training import _validate_optimizer
from biohub.training_history import canonical_sha256, normalize_pytorch_state_tree

FORMAT = "BIOHUB_ASSOCIATION_STATE_V1"


def _device(device, generator):
    dev = torch.device(device)
    if dev.type not in ("cpu", "cuda", "mps"):
        raise ValueError("Unsupported resume device")
    if dev.type == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA is unavailable; no fallback")
    if dev.type == "mps" and not torch.backends.mps.is_available():
        raise ValueError("MPS is unavailable; no fallback")
    if not isinstance(generator, torch.Generator) or generator.device.type != "cpu":
        raise ValueError("Sampler must use a CPU torch.Generator")
    return dev


def _finite_tree(value):
    if isinstance(value, torch.Tensor):
        if not bool(torch.isfinite(value).all()):
            raise ValueError("Nonfinite checkpoint tensor")
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Nonfinite checkpoint scalar")
    elif isinstance(value, dict):
        for item in value.values():
            _finite_tree(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _finite_tree(item)


def _optimizer_identity(model, optimizer):
    _validate_optimizer(optimizer, model)
    names = {id(parameter): name for name, parameter in model.named_parameters()}
    return {
        "type": f"{type(optimizer).__module__}.{type(optimizer).__qualname__}",
        "parameter_names": [[names[id(p)] for p in group["params"]] for group in optimizer.param_groups],
    }


def _rng_tensor(value, device="cpu"):
    if (not isinstance(value, torch.Tensor) or value.dtype != torch.uint8 or value.ndim != 1
            or value.numel() == 0 or value.device.type != "cpu"):
        raise ValueError("RNG state must be a nonempty CPU uint8 vector")
    try:
        torch.Generator(device=device).set_state(value)
    except (TypeError, RuntimeError) as error:
        raise ValueError("Invalid RNG state") from error


def _numpy_state(payload):
    if not isinstance(payload, list) or len(payload) != 5:
        raise ValueError("Invalid NumPy state")
    algorithm, values, position, has_gauss, cached = payload
    if (algorithm != "MT19937" or not isinstance(values, list) or len(values) != 624
            or any(type(v) is not int or not 0 <= v < 2**32 for v in values)
            or type(position) is not int or not 0 <= position <= 624
            or type(has_gauss) is not int or has_gauss not in (0, 1)
            or type(cached) not in (int, float) or not math.isfinite(cached)):
        raise ValueError("Invalid NumPy state values")
    result = (algorithm, np.array(values, dtype=np.uint32), position, has_gauss, cached)
    np.random.RandomState().set_state(result)
    return result


def capture_state(model, optimizer, generator, device):
    """Clone model/optimizer and all RNG streams used by this run."""
    dev = _device(device, generator)
    model_state = copy.deepcopy(model.state_dict())
    if not model_state or not all(isinstance(value, torch.Tensor) for value in model_state.values()):
        raise ValueError("Expected a nonempty tensor model state")
    identity = _optimizer_identity(model, optimizer)
    optimizer_state = copy.deepcopy(optimizer.state_dict())
    _finite_tree(model_state)
    _finite_tree(optimizer_state)
    numpy_state = np.random.get_state()
    rng = {
        "python": random.getstate(),
        "numpy": [numpy_state[0], numpy_state[1].tolist(), int(numpy_state[2]),
                  int(numpy_state[3]), float(numpy_state[4])],
        "torch_cpu": torch.random.get_rng_state().clone(),
        "torch_cuda": [s.clone() for s in torch.cuda.get_rng_state_all()] if dev.type == "cuda" else [],
    }
    if dev.type == "mps":
        rng["torch_mps"] = torch.mps.get_rng_state().clone()
    return {"format": FORMAT, "device": str(dev), "model": model_state,
            "optimizer": optimizer_state, "optimizer_identity": identity,
            "rng": rng, "sampler": generator.get_state().clone()}


def restore_state(state, model, optimizer, generator, device):
    """Validate the saved state, then load parameters before restoring RNGs.

    Does not claim transactional rollback for failures inside backend load calls.
    The candidate runner must stop if any restore/readback operation fails.
    """
    dev = _device(device, generator)
    keys = {"format", "device", "model", "optimizer", "optimizer_identity", "rng", "sampler"}
    if not isinstance(state, dict) or set(state) != keys or state["format"] != FORMAT:
        raise ValueError("Resume state schema mismatch")
    if state["device"] != str(dev):
        raise ValueError("Resume device mismatch")
    expected = model.state_dict()
    saved = state["model"]
    if not isinstance(saved, dict) or set(saved) != set(expected):
        raise ValueError("Resume model keys mismatch")
    for key, value in saved.items():
        if (not isinstance(value, torch.Tensor) or value.shape != expected[key].shape
                or value.dtype != expected[key].dtype):
            raise ValueError(f"Resume model shape/dtype mismatch: {key}")
    if state["optimizer_identity"] != _optimizer_identity(model, optimizer):
        raise ValueError("Optimizer type or ordered parameter names mismatch")
    opt = state["optimizer"]
    if not isinstance(opt, dict) or set(opt) != {"state", "param_groups"}:
        raise ValueError("Optimizer state schema mismatch")
    groups = opt["param_groups"]
    if not isinstance(groups, list) or len(groups) != len(optimizer.param_groups):
        raise ValueError("Optimizer group count mismatch")
    saved_ids = []
    for live, stored in zip(optimizer.param_groups, groups, strict=True):
        if not isinstance(stored, dict) or not isinstance(stored.get("params"), list):
            raise ValueError("Invalid optimizer parameter group")
        if len(live["params"]) != len(stored["params"]):
            raise ValueError("Optimizer parameter count mismatch")
        saved_ids.extend(stored["params"])
    if (any(type(index) is not int for index in saved_ids) or len(set(saved_ids)) != len(saved_ids)
            or not isinstance(opt["state"], dict) or not set(opt["state"]).issubset(saved_ids)):
        raise ValueError("Invalid optimizer state parameter IDs")
    _finite_tree(saved)
    _finite_tree(opt)
    rng = state["rng"]
    rng_keys = {"python", "numpy", "torch_cpu", "torch_cuda"}
    if dev.type == "mps":
        rng_keys.add("torch_mps")
    if not isinstance(rng, dict) or set(rng) != rng_keys:
        raise ValueError("RNG schema mismatch")
    random.Random().setstate(rng["python"])
    numpy_state = _numpy_state(rng["numpy"])
    _rng_tensor(rng["torch_cpu"])
    _rng_tensor(state["sampler"])
    cuda = rng["torch_cuda"]
    if not isinstance(cuda, list) or len(cuda) != (torch.cuda.device_count() if dev.type == "cuda" else 0):
        raise ValueError("CUDA RNG count mismatch")
    for index, value in enumerate(cuda):
        _rng_tensor(value, f"cuda:{index}")
    if dev.type == "mps":
        _rng_tensor(rng["torch_mps"], dev)

    model.load_state_dict(saved, strict=True)
    optimizer.load_state_dict(copy.deepcopy(opt))
    random.setstate(rng["python"])
    np.random.set_state(numpy_state)
    torch.random.set_rng_state(rng["torch_cpu"])
    if dev.type == "cuda":
        torch.cuda.set_rng_state_all(cuda)
    elif dev.type == "mps":
        torch.mps.set_rng_state(rng["torch_mps"])
    generator.set_state(state["sampler"])


def _cpu_clone(value):
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().clone()
    if isinstance(value, dict):
        return {key: _cpu_clone(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_cpu_clone(item) for item in value)
    return copy.deepcopy(value)


def _model_records(model):
    if (not isinstance(model, dict) or not model
            or any(type(key) is not str or not key or type(value) is not torch.Tensor
                   for key, value in model.items())):
        raise ValueError("Artifact model must be a nonempty named tensor mapping")
    records = []
    for name in sorted(model):
        tensor = normalize_pytorch_state_tree(model[name])
        records.append({"name": name, **{key: tensor[key] for key in ("shape", "dtype", "values")}})
    return records


_STATE_TYPES = {"model": "model_state_dict", "optimizer": "optimizer_state_dict",
                "scheduler": "scheduler_state_dict", "scaler": "amp_scaler_state", "sampler": "sampler_state"}


def _state_hash(name, raw):
    return canonical_sha256(_model_records(raw) if name == "model" else normalize_pytorch_state_tree(raw))


def build_artifact_state(captured, best_state):
    """Build the verifier's raw PyTorch state field, not a complete run envelope.

    Source/history/checkpoint provenance and validation readback remain caller
    responsibilities. This function cannot certify a candidate or authorize it.
    """
    raw = _cpu_clone(captured)
    if set(raw) != {"format", "device", "model", "optimizer", "optimizer_identity", "rng", "sampler"}:
        raise ValueError("Captured state schema mismatch")
    payloads = {"model": raw["model"], "optimizer": raw["optimizer"],
                "scheduler": {"enabled": False}, "scaler": {"enabled": False},
                "sampler": {"generator_state": raw["sampler"], "device": raw["device"],
                            "format": raw["format"], "optimizer_identity": raw["optimizer_identity"]}}
    result = {name: {"type": _STATE_TYPES[name], "payload": {
        "state_dict": value, "sha256": _state_hash(name, value)}} for name, value in payloads.items()}
    result["rng"] = {}
    for name, value in raw["rng"].items():
        stream = io.BytesIO()
        torch.save(value, stream)
        data = stream.getvalue()
        result["rng"][name] = {"encoding": "base64", "value": base64.b64encode(data).decode("ascii"),
                               "sha256": hashlib.sha256(data).hexdigest()}
    result["best_state"] = copy.deepcopy(best_state)
    return result


def state_from_artifact(artifact):
    """Check raw state-field hashes and decode weights-only; never mutate a model.

    Pass the raw torch.load result, not normalized metadata. restore_state then
    validates actual model/optimizer/device compatibility before loading it.
    """
    if not isinstance(artifact, dict) or set(artifact) != set(_STATE_TYPES) | {"rng", "best_state"}:
        raise ValueError("Artifact state schema mismatch")
    raw = {}
    for name, expected_type in _STATE_TYPES.items():
        entry = artifact[name]
        if not isinstance(entry, dict) or set(entry) != {"type", "payload"} or entry["type"] != expected_type:
            raise ValueError(f"Artifact {name} type/schema mismatch")
        payload = entry["payload"]
        if not isinstance(payload, dict) or set(payload) != {"state_dict", "sha256"}:
            raise ValueError(f"Artifact {name} payload schema mismatch")
        if payload["sha256"] != _state_hash(name, payload["state_dict"]):
            raise ValueError(f"Artifact {name} hash mismatch")
        raw[name] = payload["state_dict"]
    for name in ("scheduler", "scaler"):
        if canonical_sha256(raw[name]) != canonical_sha256({"enabled": False}):
            raise ValueError("Only explicitly disabled scheduler/scaler are supported")
    sampler = raw["sampler"]
    if (not isinstance(sampler, dict)
            or set(sampler) != {"generator_state", "device", "format", "optimizer_identity"}
            or sampler["format"] != FORMAT):
        raise ValueError("Artifact sampler schema mismatch")
    device = torch.device(sampler["device"])
    if device.type not in {"cpu", "mps", "cuda"}:
        raise ValueError("Unsupported artifact device")
    rng_keys = {"python", "numpy", "torch_cpu", "torch_cuda"} | ({"torch_mps"} if device.type == "mps" else set())
    if not isinstance(artifact["rng"], dict) or set(artifact["rng"]) != rng_keys:
        raise ValueError("Artifact RNG schema mismatch")
    encoded = {}
    for name, entry in artifact["rng"].items():
        if (not isinstance(entry, dict) or set(entry) != {"encoding", "value", "sha256"}
                or entry["encoding"] != "base64" or not isinstance(entry["value"], str)):
            raise ValueError("Artifact RNG payload schema mismatch")
        data = base64.b64decode(entry["value"], validate=True)
        if not data or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("Artifact RNG hash mismatch")
        encoded[name] = data
    # Verify every hash before decoding any payload. Never fall back to pickle.
    rng = {name: torch.load(io.BytesIO(data), map_location="cpu", weights_only=True)
           for name, data in encoded.items()}
    return {"format": FORMAT, "device": sampler["device"], "model": _cpu_clone(raw["model"]),
            "optimizer": _cpu_clone(raw["optimizer"]),
            "optimizer_identity": copy.deepcopy(sampler["optimizer_identity"]),
            "sampler": _cpu_clone(sampler["generator_state"]), "rng": rng}
