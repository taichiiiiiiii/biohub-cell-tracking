"""Pre-training provenance/manifest for the fixed association candidate.

Qwen draft corrected against the verifier's actual schemas. A legacy weights
import does not establish the source epoch, best score, or training history.
"""
import copy
import hashlib
import io
from pathlib import Path

import torch

from biohub.association_acceptance import acceptance_spec
from biohub.association_artifacts import CONTRACT, SELECTOR
from biohub.association_resume import _model_records
from biohub.local_training import strict_warm_start
from biohub.training_history import (
    CHECKPOINT_FORMAT,
    _validate_manifest,
    atomic_publish_file,
    atomic_write_json,
    canonical_sha256,
    execution_config_sha256,
    sha256_file,
    trusted_pytorch_checkpoint_metadata_loader,
    validate_warm_start,
)

PRIMARY_EXPECTED_SHA = "12f6881ee3620a831697ca098ff8f48e687a24225f4e048b538deec3562fe771"


def import_warm_start(model, source_path, expected_sha, run_root):
    root = Path(run_root).absolute()
    if root != root.resolve(strict=False) or expected_sha != PRIMARY_EXPECTED_SHA:
        raise ValueError("Unexpected run location or primary checkpoint pin")
    targets = [root / "provenance" / name for name in ("primary-original.pth", "primary-import.pt", "warm-import.json")]
    if any(path.exists() or path.is_symlink() for path in targets):
        raise FileExistsError("Refusing to overwrite warm-start provenance")
    strict_warm_start(model, source_path, expected_sha)
    raw_bytes = Path(source_path).read_bytes()
    if hashlib.sha256(raw_bytes).hexdigest() != expected_sha:
        raise ValueError("Warm-start source changed")
    state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
    original = torch.load(io.BytesIO(raw_bytes), map_location="cpu", weights_only=True)
    if set(original) != set(state) or any(not torch.equal(original[name], state[name]) for name in state):
        raise ValueError("Imported tensors differ from primary source")
    records = _model_records(state)
    schema = [{key: record[key] for key in ("name", "shape", "dtype")} for record in records]
    envelope = {"format": CHECKPOINT_FORMAT, "schema_version": 1, "kind": "imported_weights",
                "run_id": f"legacy-primary-import-{expected_sha[:12]}", "epoch": None, "global_step": None,
                "model_state": state, "state_keys": schema}
    stream = io.BytesIO()
    torch.save(envelope, stream)
    atomic_publish_file(targets[0], raw_bytes)
    atomic_publish_file(targets[1], stream.getvalue())
    imported_sha = sha256_file(targets[1])
    atomic_write_json(targets[2], {"original_sha256": expected_sha, "import_sha256": imported_sha,
                                  "model_tensor_canonical_sha256": canonical_sha256(records),
                                  "legacy_history_verified": False})
    names = sorted(state)
    info = {"warm_start_checkpoint_sha256": imported_sha, "model_state_schema": schema,
            "original_sha256": expected_sha,
            "warm_start": {"mode": "full_strict", "source_run_id": envelope["run_id"],
                           "source_kind": "imported_weights", "optimizer_reset": True,
                           "scheduler_reset": True, "scaler_reset": True, "expected_keys": names,
                           "expected_keys_sha256": canonical_sha256(names),
                           "key_specs": {record["name"]: {key: record[key] for key in ("shape", "dtype")}
                                         for record in schema}}}
    validate_warm_start(info, trusted_pytorch_checkpoint_metadata_loader(targets[1]))
    return info


def build_manifest(context, prepared, baseline):
    """Assemble actual pins/coverage/baseline; no synthetic fallback values."""
    context = copy.deepcopy(context)
    split = copy.deepcopy(prepared["split"])
    train, val = split["train"], split["validation"]
    if (len(train["stems"]) != 8 or len(val["stems"]) != 4
            or set(train["stems"]) & set(val["stems"])
            or any(set(side["lineages"]) != {"44b6", "6bba"} for side in (train, val))
            or baseline["example_ids"] != val["example_ids"]
            or baseline["examples"] != val["examples"] or baseline["batches"] != val["batches"]
            or set(baseline["by_video"]) != set(val["stems"])
            or set(baseline["by_lineage"]) != {"44b6", "6bba"}
            or any(baseline["by_lineage"][name]["examples"] != val["lineages"][name] for name in val["lineages"])):
        raise ValueError("Baseline differs from fixed whole-video split/coverage")
    device = context["hardware"]["device"]
    if device not in {"cpu", "mps", "cuda"}:
        raise ValueError("Unsupported explicit device")
    warm = context["warm_import"]
    if (warm["original_sha256"] != PRIMARY_EXPECTED_SHA
            or context["hash_sources"].get("warm_start_checkpoint_sha256") != "provenance/primary-import.pt"):
        raise ValueError("Warm import source pin/path mismatch")
    profile = {name: {"required": True, "reduction": "sum_over_windows", "denominator_source": "examples"}
               for name in ("edge_loss", "det_loss", "total_loss")}
    manifest = {key: context[key] for key in ("run_id", "git_sha", "cli", "dependencies", "allowed_environment",
                                            "hardware", "code_tree_sha256", "input_manifest_sha256",
                                            "hash_sources", "training_sources")}
    manifest.update(
        schema_version=1, purpose="candidate", run_kind="single_split", phase="train", fold_id=None,
        execution_hash_policy="predeclared_with_result_bindings_v1", seed=20260922,
        model_config={"architecture": "UNetNodeTransformer", "unet_out_channels": 32, "unet_layers": [32, 64, 128],
                      "hidden_dim": 128, "n_heads": 4, "n_blocks": 4, "dropout": 0.3,
                      "frozen_submodules": ["unet", "detect_head"], "max_nodes": prepared["max_nodes"],
                      "epochs": 10, "batch_size": 1, "workers": 0, "window_size": 2, "downsample": [1, 4, 4],
                      "original_warm_start_sha256": warm["original_sha256"]},
        loss_config={"w_det": 1.0, "det_neg_weight": 0.01, "pool_kernel_um": 5.0},
        optimizer_config={"name": "AdamW", "lr": 1e-5, "betas": [0.9, 0.999], "eps": 1e-8,
                          "weight_decay": 0.01, "trainable_only": True},
        scheduler_config={"enabled": False, "amp": False},
        split=split, split_sha256=canonical_sha256(split),
        warm_start_checkpoint_sha256=warm["warm_start_checkpoint_sha256"],
        warm_start=warm["warm_start"], model_state_schema=warm["model_state_schema"],
        selector=copy.deepcopy(SELECTOR), loss_component_profile={"train": copy.deepcopy(profile), "val": profile},
        nullable_loss_components={},
        total_loss={"name": "total_loss", "components": ["edge_loss", "det_loss"],
                    "formula": "edge_loss + w_det * det_loss", "weights": {"w_det": 1.0},
                    "aggregation": {"denominator_source": "examples",
                                    "numerator_formula": "edge_loss_numerator + w_det * det_loss_numerator",
                                    "reduction": "sum_over_windows"}},
        acceptance_thresholds=acceptance_spec(baseline), final_selection=None, degradation=None, checkpoint_refs={},
        sampler={"mode": "serialized"}, gradient={"clip_threshold": 1.0},
        resume_validation_contract=copy.deepcopy(CONTRACT),
    )
    manifest["validation_snapshot"] = {
        "example_ids": copy.deepcopy(val["example_ids"]), "input_manifest_sha256": manifest["input_manifest_sha256"],
        "split_sha256": manifest["split_sha256"], "seed": 20260922,
        "allowed_environment": copy.deepcopy(manifest["allowed_environment"]), "device": device, "dtype": "float32",
        "framework_version": context["dependencies"]["torch"], "shuffle": False, "augmentation": False,
        "preprocessing_config": {"window_size": 2, "downsample": [1, 4, 4],
                                 "normalization": "official_quantile_0.001_0.999_clamp_min0",
                                 "image_storage_dtype": "float16", "model_input_dtype": "float32"},
    }
    if "train_augmentation" in context:
        manifest["model_config"]["train_augmentation"] = copy.deepcopy(context["train_augmentation"])
    manifest["config_sha256"] = execution_config_sha256(manifest)
    errors = []
    _validate_manifest(manifest, errors)
    if errors:
        raise ValueError(f"Pre-training manifest validation failed: {errors}")
    return manifest
