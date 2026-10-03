"""Diagnostic validation instrumentation around the unchanged official evaluator."""

import io
import json
import math
import random
from pathlib import Path
from types import MethodType

import numpy as np
import torch

from biohub.training_history import (
    HistoryWriter,
    atomic_publish_file,
    atomic_write_json,
    select_best,
    sha256_bytes,
    sha256_file,
    strict_json_loads,
)


def diagnostic_input_manifest(data_dir, split, max_frames):
    """Pin the supported local full-frame Zarr chunks; reject missing frames."""
    root = Path(data_dir)
    files = set()
    for name in split["train"] + split["test"]:
        stem = name.removesuffix(".zarr")
        if not stem or Path(stem).name != stem or stem in (".", "..") or "\\" in stem:
            raise ValueError("Invalid input video stem")
        image = root / f"{stem}.zarr"
        metadata_path = image / "0/zarr.json"
        metadata = json.loads(metadata_path.read_text())
        shape = metadata["shape"]
        chunks = metadata["chunk_grid"]["configuration"]["chunk_shape"]
        if (len(shape) != 4 or chunks != [1, *shape[1:]] or not 2 <= max_frames <= shape[0]
                or metadata["chunk_key_encoding"] != {"name": "default", "configuration": {"separator": "/"}}):
            raise ValueError("Unsupported diagnostic Zarr layout or frame range")
        files.update([image / "zarr.json", metadata_path])
        files.update(image / f"0/c/{frame}/0/0/0" for frame in range(max_frames))
        geff = root / f"{stem}.geff"
        if not (geff / "zarr.json").is_file():
            raise ValueError(f"Missing annotation metadata: {stem}")
        files.update(path for path in geff.rglob("*") if path.is_file())
    inventory = []
    for path in sorted(files):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing or symlink input file: {path}")
        inventory.append({"path": str(path.relative_to(root)), "bytes": path.stat().st_size,
                          "sha256": sha256_file(path)})
    return inventory


def freeze_detector(model):
    """Freeze detector parameters and buffers even after parent model.train()."""
    modules = {"unet": model.unet, "detect_head": model.detect_head}
    for module in modules.values():
        module.requires_grad_(False)
        module.eval()
    before = {prefix: {name: value.detach().cpu().clone() for name, value in module.state_dict().items()}
              for prefix, module in modules.items()}
    original_train = model.train

    def train(this, mode=True):
        original_train(mode)
        for module in modules.values():
            module.eval()
        return this

    model.train = MethodType(train, model)

    def verify():
        for prefix, module in modules.items():
            if any(child.training for child in module.modules()):
                raise ValueError(f"Frozen detector entered training mode: {prefix}")
            if any(p.requires_grad or p.grad is not None for p in module.parameters()):
                raise ValueError(f"Frozen detector received gradients: {prefix}")
            current = module.state_dict()
            if set(current) != set(before[prefix]):
                raise ValueError(f"Frozen detector state keys changed: {prefix}")
            for name, value in current.items():
                if not torch.equal(before[prefix][name], value.detach().cpu()):
                    raise ValueError(f"Frozen detector state changed: {prefix}.{name}")

    return verify


def strict_warm_start(model, path, expected_sha256):
    """Load pinned full-model weights, never optimizer state or partial matches."""
    if (not isinstance(expected_sha256, str) or len(expected_sha256) != 64
            or any(c not in "0123456789abcdef" for c in expected_sha256)):
        raise ValueError("An explicit lowercase SHA256 is required")
    payload = Path(path).read_bytes()
    if sha256_bytes(payload) != expected_sha256:
        raise ValueError("Warm-start checkpoint SHA256 mismatch")
    state = torch.load(io.BytesIO(payload), map_location="cpu", weights_only=True)
    expected = model.state_dict()
    if not isinstance(state, dict) or set(state) != set(expected):
        raise ValueError("Warm-start full-model keys mismatch")
    for name, tensor in state.items():
        reference = expected[name]
        if (not isinstance(tensor, torch.Tensor) or tensor.shape != reference.shape
                or tensor.dtype != reference.dtype or not bool(torch.isfinite(tensor).all())):
            raise ValueError(f"Warm-start tensor mismatch or nonfinite value: {name}")
    model.load_state_dict(state, strict=True)
    return {"mode": "full_strict", "sha256": expected_sha256, "keys": len(state)}


def checked_loss(loss):
    """Reject invalid scalar losses before backward or any optimizer update."""
    if loss.numel() != 1 or not bool(torch.isfinite(loss).all()) or float(loss.detach().item()) < 0:
        raise ValueError("Training loss must be a finite nonnegative scalar")
    return loss


def validate_window_coverage(windows, *, source):
    """Do not silently drop a named diagnostic video after prefix filtering."""
    if not windows:
        raise ValueError(f"No usable annotated windows for {source}")
    positives = sum(int(torch.count_nonzero(target).item()) for window in windows for target in window.targets)
    if positives == 0:
        raise ValueError(f"No annotated positive tracking edges for {source}")
    return {"source": str(source), "windows": len(windows), "positive_edge_occurrences": positives}


def finalize_diagnostic_selection(history_path, checkpoint_dir, output_path):
    """Read back complete diagnostic epochs and pin the earliest loss minimum.

    This does not promote a diagnostic snapshot or validate candidate training.
    A receipt ties every checkpoint to the exact recorded history prefix.
    """
    history_path, checkpoint_dir = Path(history_path), Path(checkpoint_dir)
    if history_path.is_symlink() or not history_path.is_file() or checkpoint_dir.is_symlink():
        raise ValueError("History and checkpoint directory must not be symlinks")
    raw = history_path.read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise ValueError("History is empty or missing its final newline")
    rows, prefix = [], b""
    for epoch, line in enumerate(raw.split(b"\n")[:-1], start=1):
        row = strict_json_loads(line, source=f"{history_path}:line{epoch}")
        if not isinstance(row, dict) or type(row.get("epoch")) is not int or row["epoch"] != epoch:
            raise ValueError("History epochs must be contiguous integers starting at 1")
        step = row.get("global_step")
        if type(step) is not int or step <= (rows[-1]["global_step"] if rows else 0):
            raise ValueError("History global steps must strictly increase")
        if (row.get("status") != "DIAGNOSTIC_ONLY" or row.get("candidate_gate") != "INCOMPLETE"
                or row.get("resume_supported") is not False):
            raise ValueError("Diagnostic history contract mismatch")
        try:
            loss = row["validation"]["losses"]["total_loss"]["value"]
        except (KeyError, TypeError) as error:
            raise ValueError("Validation total loss is missing") from error
        if type(loss) not in (int, float) or not math.isfinite(loss) or loss < 0:
            raise ValueError("Validation total loss must be finite and nonnegative")
        checkpoint = row.get("checkpoint")
        if not isinstance(checkpoint, dict) or checkpoint.get("name") != f"epoch_{epoch:04d}.pt":
            raise ValueError("Checkpoint name does not match its epoch")
        path = checkpoint_dir / checkpoint["name"]
        if path.is_symlink() or not path.is_file() or sha256_file(path) != checkpoint.get("sha256"):
            raise ValueError("Checkpoint file/hash mismatch")
        receipt_path = path.with_suffix(".receipt.json")
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise ValueError("Checkpoint receipt missing or symlinked")
        receipt = strict_json_loads(receipt_path.read_bytes(), source=str(receipt_path))
        if (not isinstance(receipt, dict) or receipt.get("checkpoint") != checkpoint
                or type(receipt.get("epoch")) is not int or receipt["epoch"] != epoch
                or type(receipt.get("global_step")) is not int or receipt["global_step"] != step
                or receipt.get("resume_supported") is not False):
            raise ValueError("Checkpoint receipt contract mismatch")
        prefix += line + b"\n"
        if receipt.get("history_prefix_sha256") != sha256_bytes(prefix):
            raise ValueError("Checkpoint receipt history prefix mismatch")
        rows.append({"epoch": epoch, "global_step": step, "selector_value": loss, "checkpoint": checkpoint})
    best = select_best(rows, selector="selector_value", direction="min")
    result = {
        "status": "DIAGNOSTIC_ONLY", "candidate_gate": "INCOMPLETE", "resume_supported": False,
        "epoch": best["epoch"], "selector_value": best["selector_value"], "checkpoint": best["checkpoint"],
        "history_sha256": sha256_bytes(raw),
        "selector": {"path": "validation.losses.total_loss.value", "direction": "min", "tie_rule": "earliest_exact"},
    }
    atomic_write_json(output_path, result)
    return result


class DiagnosticRecorder:
    """Persist completed epochs without claiming candidate/resume compliance."""

    def __init__(self, path, *, det_loss_weight, checkpoint_dir=None):
        if not math.isfinite(det_loss_weight) or det_loss_weight < 0:
            raise ValueError("Invalid detection loss weight")
        self.writer = HistoryWriter(path)
        self.weight = det_loss_weight
        self.epoch = 0
        self.steps = 0
        self.pending = None
        self.grad_norms = []
        self.checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir is not None else None
        self.training_state = None

    def clip_grad_norm(self, parameters, max_norm):
        if max_norm != 1.0:
            raise ValueError("Unexpected gradient clipping threshold")
        norm = torch.nn.utils.clip_grad_norm_(parameters, max_norm, error_if_nonfinite=True)
        self.grad_norms.append(float(norm.item()))
        return norm

    def train_epoch(self, train_fn, model, loader, optimizer, *args, **kwargs):
        if self.pending is not None:
            raise ValueError("Previous epoch validation has not been recorded")
        count = 0
        self.grad_norms = []

        def before_step(*unused):
            if len(self.grad_norms) != count + 1:
                raise ValueError("Optimizer step requires exactly one finite pre-clip gradient check")

        def stepped(*unused):
            nonlocal count
            count += 1

        pre_hook = optimizer.register_step_pre_hook(before_step)
        hook = optimizer.register_step_post_hook(stepped)
        try:
            edge, det = train_fn(model, loader, optimizer, *args, **kwargs)
        finally:
            hook.remove()
            pre_hook.remove()
        total = edge + self.weight * det
        if (count == 0 or len(self.grad_norms) != count
                or not all(math.isfinite(value) and value >= 0 for value in (edge, det, total))):
            raise ValueError("Incomplete or nonfinite training epoch")
        self.steps += count
        self.training_state = (model, optimizer, loader)
        self.pending = {"edge_loss": edge, "det_loss": det, "total_loss": total,
                        "optimizer_steps": count, "source": "official_train_epoch_window_means",
                        "grad_norm_pre_clip": {"max": max(self.grad_norms),
                                               "mean": sum(self.grad_norms) / count,
                                               "last": self.grad_norms[-1],
                                               "checked_steps": count, "clip_threshold": 1.0}}
        return edge, det

    def validation(self, report):
        if self.pending is None:
            raise ValueError("Validation has no completed training epoch")
        if report.get("det_loss_weight") != self.weight or report.get("status") != "DIAGNOSTIC_ONLY":
            raise ValueError("Validation contract mismatch")
        row = {"epoch": self.epoch + 1, "global_step": self.steps, "status": "DIAGNOSTIC_ONLY",
               "candidate_gate": "INCOMPLETE", "resume_supported": False,
               "train": self.pending, "validation": report}
        checkpoint = None
        if self.checkpoint_dir is not None:
            model, optimizer, loader = self.training_state
            device = next(model.parameters()).device.type
            numpy_state = np.random.get_state()
            generator = getattr(loader, "generator", None)
            state = {
                "format": "BIOHUB_DIAGNOSTIC_SNAPSHOT_V1", "resume_supported": False,
                "epoch": self.epoch + 1, "global_step": self.steps,
                "model": model.state_dict(), "optimizer": optimizer.state_dict(),
                "scheduler": None, "scaler": None,
                "rng": {"python": random.getstate(), "torch_cpu": torch.get_rng_state(),
                        "numpy": [numpy_state[0], numpy_state[1].tolist(), *numpy_state[2:]],
                        "mps": torch.mps.get_rng_state() if device == "mps" else None,
                        "cuda": torch.cuda.get_rng_state_all() if device == "cuda" else None},
                "loader_generator": generator.get_state() if generator is not None else None,
                "loader_workers": getattr(loader, "num_workers", None),
                "validation": report, "history_prefix_before_epoch": self.writer.prefix_sha256,
                "limitations": ["no_input_manifest", "no_worker_rng_restore", "no_resume_entrypoint"],
            }
            buffer = io.BytesIO()
            torch.save(state, buffer)
            payload = buffer.getvalue()
            checkpoint = self.checkpoint_dir / f"epoch_{self.epoch + 1:04d}.pt"
            atomic_publish_file(checkpoint, payload)
            row["checkpoint"] = {"name": checkpoint.name, "sha256": sha256_bytes(payload)}
        self.writer.append(row)
        if checkpoint is not None:
            atomic_write_json(checkpoint.with_suffix(".receipt.json"), {
                "checkpoint": row["checkpoint"], "history_prefix_sha256": self.writer.prefix_sha256,
                "epoch": self.epoch + 1, "global_step": self.steps, "resume_supported": False,
            })
        self.epoch += 1
        self.pending = None

    def close(self):
        self.writer.close()


@torch.no_grad()
def evaluate_components(api, model, loader, device, *, det_loss_weight, det_neg_weight, pool_kernel_um=5.0):
    """Reuse one inference pass; preserve the legacy edge/accuracy/recall result.

    Edge loss is the official mean of per-window transition losses, including
    unsupervised zero terms. For fixed window length this equals the training
    reduction (mean transitions per window, then mean windows). It is not a
    pooled edge-count loss or the official competition score.
    """
    if not all(math.isfinite(x) and x >= 0 for x in (det_loss_weight, det_neg_weight)):
        raise ValueError("Detection weights must be finite and nonnegative")
    state = {"batch": None, "examples": 0, "batches": 0, "frames": None, "det_sum": 0.0}

    def batches():
        for batch in loader:
            batch_size, frames = batch["imgs"].shape[:2]
            if batch_size < 1 or frames < 2:
                raise ValueError("Validation needs nonempty windows of at least two frames")
            if state["frames"] not in (None, frames):
                raise ValueError("Variable window lengths change the loss reduction")
            state["frames"] = frames
            state["batch"] = batch
            state["examples"] += batch_size
            state["batches"] += 1
            yield batch

    class ObservedModel:
        def __getattr__(self, name):
            return getattr(model, name)

        def encode(self, imgs):
            features, logits = model.encode(imgs)
            batch = state["batch"]
            coords = batch["coords"].to(device)
            masks = batch["masks"].to(device)
            frames = imgs.shape[1]
            if len(logits) != frames:
                raise ValueError("Detection output frame count mismatch")
            loss = sum(api.compute_detection_loss(logits[i], coords[:, i], masks[:, i], det_neg_weight)
                       for i in range(frames)) / frames
            value = float(loss.item())
            if not math.isfinite(value) or value < 0:
                raise ValueError("Nonfinite or negative validation detection loss")
            state["det_sum"] += value * imgs.shape[0]
            return features, logits

    legacy = api.evaluate(ObservedModel(), batches(), device, pool_kernel_um=pool_kernel_um)
    if not state["examples"]:
        raise ValueError("Empty validation loader")
    if not all(math.isfinite(float(value)) for value in legacy) or legacy[0] < 0:
        raise ValueError("Invalid legacy validation metrics")
    count = state["examples"]
    edge_sum = float(legacy[0]) * count
    det_sum = state["det_sum"]
    numerators = {"edge_loss": edge_sum, "det_loss": det_sum,
                  "total_loss": edge_sum + det_loss_weight * det_sum}
    if not all(math.isfinite(value) for value in numerators.values()):
        raise ValueError("Validation loss aggregation overflow")
    report = {
        "status": "DIAGNOSTIC_ONLY", "examples": count, "batches": state["batches"],
        "window_size": state["frames"], "det_loss_weight": det_loss_weight,
        "det_neg_weight": det_neg_weight,
        "losses": {name: {"value": value / count, "numerator": value, "denominator": count,
                          "reduction": "sum_over_windows_of_mean_frame_or_transition_loss"}
                   for name, value in numerators.items()},
        "legacy_accuracy": float(legacy[1]), "legacy_node_recall": float(legacy[2]),
        "warnings": ["NO_GT_MATCHES_TRACKING_LOSS_NOT_INFORMATIVE"] if float(legacy[2]) == 0 else [],
    }
    return legacy, report
