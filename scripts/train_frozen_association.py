"""Fixed 10-epoch candidate entry point; no download, submission or fallback.

Qwen orchestration draft reviewed and corrected to use the verified epoch,
resume and acceptance implementations, not replacement losses or PASS flags.
Run with PYTHONPATH=src python -m scripts.train_frozen_association.
"""
import argparse
import importlib.metadata
import importlib.util
import io
import json
import os
import platform
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

import torch

from biohub.association_acceptance import paired_readout
from biohub.association_artifacts import compare_readback, finalize_run, publish_epoch
from biohub.association_augmentation import augment_batches, augmentation_config, flip_bits
from biohub.association_data import iter_batches, prepare_windows, verify_acquisition
from biohub.association_manifest import PRIMARY_EXPECTED_SHA, build_manifest, import_warm_start
from biohub.association_probe import assert_same_probe, capture_probe, describe_probe
from biohub.association_resume import capture_state, restore_state
from biohub.association_training import run_epoch
from biohub.local_training import freeze_detector
from biohub.training_history import atomic_publish_file, atomic_write_json, sha256_bytes, sha256_file
from scripts import download_data as dd
from scripts.local_train_unet_transformer import seed_rng

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "analysis/frozen_association_acquisition.json"
SEED = 20260922


def source_files():
    fixed = ["scripts/train_frozen_association.py", "scripts/local_train_unet_transformer.py",
             "scripts/download_data.py", "official/scripts/train_unet_transformer.py",
             "official/scripts/augmentations.py", "official/scripts/dataspec.py", "src/biohub/__init__.py",
             "src/biohub/local_training.py",
             "src/biohub/training_history.py", "pyproject.toml", "uv.lock"]
    fixed += [f"src/biohub/association_{name}.py" for name in (
        "acceptance", "artifacts", "augmentation", "data", "manifest", "probe", "resume", "training")]
    return sorted(set(fixed) | {str(p.relative_to(ROOT)) for pattern in (
        "official/src/tracking_cellmot/**/*.py",) for p in ROOT.glob(pattern)})


def snapshot_sources(root):
    records = []
    for rel in source_files():
        path = ROOT / rel
        if not path.is_file() or path.resolve() != path.absolute():
            raise ValueError("Missing or symlink source")
        raw = path.read_bytes()
        destination = root / "provenance/source" / rel
        atomic_publish_file(destination, raw)
        digest = sha256_file(destination)
        if sha256_file(path) != digest:
            raise ValueError("Source changed during snapshot")
        records.append({"path": rel, "bytes": len(raw), "sha256": digest})
    atomic_write_json(root / "provenance/code-tree.json", records)

    def check():
        if source_files() != [record["path"] for record in records]:
            raise ValueError("Source file set changed")
        for record in records:
            path = ROOT / record["path"]
            if path.resolve() != path.absolute() or sha256_file(path) != record["sha256"]:
                raise ValueError("Source changed")

    return check


def load_api():
    previous = sys.path[:]
    try:
        sys.path[:0] = [str(ROOT / "official/scripts"), str(ROOT / "official/src")]
        spec = importlib.util.spec_from_file_location(
            "_frozen_association_official", ROOT / "official/scripts/train_unet_transformer.py")
        api = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = api
        spec.loader.exec_module(api)
        return api
    finally:
        sys.path[:] = previous


def make_model(api):
    return api.UNetNodeTransformer(
        api.TemporalUNet3D(in_channels=1, out_channels=32, layers=[32, 64, 128]),
        unet_out_channels=32, pos_feat_dim=32, hidden_dim=128, n_heads=4, n_blocks=4, dropout=0.3)


def make_optimizer(model):
    return torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],
                            lr=1e-5, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.01)


def save_readback_state(root, epoch, captured):
    path = root / f"provenance/readback-state-{epoch:04d}.pt"
    stream = io.BytesIO()
    torch.save(captured, stream)
    raw = stream.getvalue()
    digest = sha256_bytes(raw)
    atomic_publish_file(path, raw)
    if sha256_file(path) != digest:
        raise ValueError("Saved state differs from captured bytes")
    loaded = torch.load(path, map_location="cpu", weights_only=True)
    if sha256_file(path) != digest:
        raise ValueError("Saved readback state changed")
    atomic_write_json(path.with_suffix(".json"), {"sha256": digest, "epoch": epoch})
    return loaded


def run(receipt, run_id, train_augmentation="none", reference_baseline=None):
    if train_augmentation not in {"none", "xy_flip"}:
        raise ValueError("Unknown training augmentation")
    if (train_augmentation == "xy_flip") != (reference_baseline is not None):
        raise ValueError("XY comparison requires its unaugmented reference baseline")
    if re.fullmatch(r"[a-z0-9_-]{1,64}", run_id) is None:
        raise ValueError("Invalid run ID")
    if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "1" or not torch.backends.mps.is_available():
        raise ValueError("Explicit MPS without fallback required")
    root = ROOT / "outputs/local/association_candidates" / run_id
    gate = root.with_name(run_id + ".gate.json")
    failure = root.with_name(run_id + ".failure.json")
    if root != root.resolve(strict=False) or any(p.exists() or p.is_symlink() for p in (root, gate, failure)):
        raise FileExistsError("Run path already exists or is unsafe")
    receipt = Path(receipt).absolute()
    with dd.single_run_lock():
        verify_acquisition(dd.DATA, receipt, PLAN)  # No output creation or GT before complete acquisition.
        root.mkdir(parents=True, exist_ok=False)
        try:
            return execute(root, gate, receipt, run_id, train_augmentation, reference_baseline)
        except Exception as error:
            # Outside the sealed tree; retain partial checkpoints for diagnosis.
            atomic_write_json(failure, {"error_class": type(error).__name__, "time_unix": time.time()})
            raise


def execute(root, gate, receipt, run_id, train_augmentation="none", reference_baseline=None):
    check_sources = snapshot_sources(root)
    atomic_publish_file(root / "provenance/input.json", (receipt / "files.json").read_bytes())
    atomic_publish_file(root / "provenance/acquisition-plan.json", PLAN.read_bytes())
    api = load_api()
    prepared = prepare_windows(api, dd.DATA, receipt, PLAN)
    atomic_write_json(root / "provenance/coverage.json", prepared["coverage"])
    device = torch.device("mps")
    seed_rng(SEED, device)
    model = make_model(api)
    warm = import_warm_start(model, ROOT / "outputs/kaggle/st_r3_checkpoint_recovery/primary/edge_predictor_best.pth",
                             PRIMARY_EXPECTED_SHA, root)
    model.to(device)
    guard = freeze_detector(model)
    optimizer = make_optimizer(model)
    generator = torch.Generator(device="cpu").manual_seed(SEED)

    def validate(m, g):
        return run_epoch(api, m, iter_batches(prepared, "validation"), device, detector_guard=g)

    def check_inputs():
        check_sources()
        verify_acquisition(dd.DATA, receipt, PLAN)
        if (sha256_file(receipt / "files.json") != sha256_file(root / "provenance/input.json")
                or sha256_file(PLAN) != sha256_file(root / "provenance/acquisition-plan.json")):
            raise ValueError("Input receipt changed")

    print(json.dumps({"state": "baseline_validation_started", "run_id": run_id}), flush=True)
    baseline = validate(model, guard)
    baseline_readback = validate(model, guard)
    compare_readback(baseline, baseline_readback)
    if train_augmentation == "xy_flip":
        reference = Path(reference_baseline)
        if reference.is_symlink() or not reference.is_file():
            raise ValueError("Reference baseline missing or symlink")
        raw_reference = reference.read_bytes()
        compare_readback(json.loads(raw_reference), baseline)
        atomic_publish_file(root / "provenance/control-baseline.json", raw_reference)
    probe_batch = next(iter_batches(prepared, "validation"))[2]
    probe = capture_probe(api, model, probe_batch, device)
    assert_same_probe(probe, capture_probe(api, model, probe_batch, device))
    check_inputs()
    atomic_write_json(root / "provenance/baseline.json", baseline)
    atomic_write_json(root / "provenance/baseline-readback.json", baseline_readback)
    atomic_write_json(root / "provenance/detector-probe.json", describe_probe(probe))
    context = {
        "run_id": run_id, "git_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "cli": shlex.join(sys.argv),
        "dependencies": {"python": platform.python_version(), **{name: importlib.metadata.version(name)
                         for name in ("torch", "numpy", "zarr", "polars", "tracksdata", "scipy",
                                      "dask", "geff", "numcodecs", "tqdm", "scikit-image")}},
        "allowed_environment": {key: os.environ[key] for key in (
            "PYTORCH_ENABLE_MPS_FALLBACK", "PYTORCH_MPS_FAST_MATH", "OMP_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")
            if key in os.environ},
        "hardware": {"device": "mps", "platform": platform.platform(), "machine": platform.machine()},
        "code_tree_sha256": sha256_file(root / "provenance/code-tree.json"),
        "input_manifest_sha256": sha256_file(root / "provenance/input.json"), "warm_import": warm,
        "hash_sources": {"code_tree_sha256": "provenance/code-tree.json",
                         "input_manifest_sha256": "provenance/input.json",
                         "warm_start_checkpoint_sha256": "provenance/primary-import.pt"},
        "training_sources": {key: {"path": "provenance/source/" + rel,
                                    "sha256": sha256_file(root / "provenance/source" / rel)}
                             for key, rel in (("wrapper", "scripts/train_frozen_association.py"),
                                              ("support_trainer", "src/biohub/association_training.py"))},
    }
    if train_augmentation == "xy_flip":
        schedule = [{"epoch": epoch, "example_id": identity,
                     "flip_y": flip_bits(SEED, epoch, identity)[0],
                     "flip_x": flip_bits(SEED, epoch, identity)[1]}
                    for epoch in range(1, 11) for _, identity in prepared["identities"]["train"]]
        atomic_write_json(root / "provenance/augmentation-schedule.json", schedule)
        context["train_augmentation"] = {
            **augmentation_config(), "seed": SEED, "epochs": 10,
            "schedule_sha256": sha256_file(root / "provenance/augmentation-schedule.json"),
            "control_baseline_sha256": sha256_file(root / "provenance/control-baseline.json")}
    manifest = build_manifest(context, prepared, baseline)
    atomic_write_json(root / "provenance/pretraining-manifest.json", manifest)
    print(json.dumps({"state": "baseline_verified", "run_id": run_id,
                      "train_augmentation": train_augmentation}), flush=True)
    rows, best = [], None
    for epoch in range(10):
        check_inputs()
        started = time.monotonic()
        train_items = iter_batches(prepared, "train", generator=generator)
        if train_augmentation == "xy_flip":
            train_items = augment_batches(train_items, seed=SEED, epoch=epoch + 1)

        def observed_items(items, current_epoch=epoch + 1):
            for index, item in enumerate(items):
                if index == 1:
                    # run_epoch advances this iterator only after the prior optimizer step.
                    print(json.dumps({"state": "optimizer_updates_started", "epoch": current_epoch}), flush=True)
                yield item

        trained = run_epoch(api, model, observed_items(train_items), device,
                            optimizer=optimizer, detector_guard=guard)
        if train_augmentation == "xy_flip":
            realized = [{"example_id": identity, "flip_y": flip_bits(SEED, epoch + 1, identity)[0],
                         "flip_x": flip_bits(SEED, epoch + 1, identity)[1]}
                        for identity in trained["example_ids"]]
            counts = {f"{int(y)}{int(x)}": sum(r["flip_y"] == y and r["flip_x"] == x for r in realized)
                      for y in (False, True) for x in (False, True)}
            atomic_write_json(root / f"provenance/augmentation-epoch-{epoch + 1:04d}.json",
                              {"epoch": epoch + 1, "sequence": realized, "combination_counts": counts})
        evaluated = validate(model, guard)
        assert_same_probe(probe, capture_probe(api, model, probe_batch, device))
        captured = save_readback_state(root, epoch + 1, capture_state(model, optimizer, generator, device))
        restored = make_model(api).to(device)
        restored_guard = freeze_detector(restored)
        restored_optimizer = make_optimizer(restored)
        restored_generator = torch.Generator(device="cpu")
        restore_state(captured, restored, restored_optimizer, restored_generator, device)
        # freeze_detector records the random initial tensors; rebind after restoration.
        restored_guard = freeze_detector(restored)
        readback = validate(restored, restored_guard)
        compare_readback(evaluated, readback)
        assert_same_probe(probe, capture_probe(api, restored, probe_batch, device))
        restored_guard()
        restore_state(captured, model, optimizer, generator, device)
        guard()
        del restored, restored_optimizer, restored_generator, restored_guard
        check_inputs()
        rows.append(publish_epoch(root, manifest, rows, trained, evaluated, readback, captured,
                                  lr=1e-5, epoch_seconds=time.monotonic() - started))
        if best is None or evaluated["losses"]["total_loss"]["value"] < best["losses"]["total_loss"]["value"]:
            best = evaluated
        print(json.dumps({"epoch": epoch + 1, "global_step": rows[-1]["global_step"],
                          "train": trained["losses"], "validation": evaluated["losses"],
                          "grad_norm_pre_clip": trained["grad_norm_pre_clip"]}), flush=True)
    atomic_write_json(root / "provenance/per-video.json", paired_readout(baseline, best))
    check_inputs()
    result = finalize_run(root, manifest)
    atomic_write_json(gate, result)
    return 0 if result["verdict"] == "PASS" else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--train-augmentation", choices=("none", "xy_flip"), default="none")
    parser.add_argument("--reference-baseline", type=Path)
    args = parser.parse_args()
    try:
        return run(args.receipt_dir, args.run_id, args.train_augmentation, args.reference_baseline)
    except Exception as error:
        print(json.dumps({"state": "failed", "error_class": type(error).__name__}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
