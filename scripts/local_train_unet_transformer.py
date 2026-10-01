"""Diagnostic-only local device adapter; official source remains read-only.

Candidate training is not supported until the training-history contract is wired
into the trainer. No global torch monkeypatches or implicit device fallbacks.
"""

import argparse
import ast
import json
import random
import sys
import types
from pathlib import Path

import numpy as np
import torch

TRAINER = Path(__file__).resolve().parents[1] / "official/scripts/train_unet_transformer.py"
DEVICE_EXPR = 'torch.device("cuda" if torch.cuda.is_available() else "cpu")'


def validate_split(path: Path, fold: int) -> dict:
    """Reject silent split generation, duplicate videos and train/val overlap."""
    folds = json.loads(path.read_text())
    if not isinstance(folds, list) or not 0 <= fold < len(folds):
        raise ValueError("An explicit valid fold is required")
    selected = folds[fold]
    names = {}
    for side in ("train", "test"):
        values = selected.get(side) if isinstance(selected, dict) else None
        if not isinstance(values, list) or not values or len(values) > 4:
            raise ValueError(f"Diagnostic {side} must contain 1..4 explicit videos")
        stems = []
        for value in values:
            if (not isinstance(value, str) or not value or Path(value).name != value
                    or "\\" in value or value in (".", "..")):
                raise ValueError("Video names must be plain stems or .zarr names")
            stem = value.removesuffix(".zarr")
            if not stem.startswith(("44b6_", "6bba_")):
                raise ValueError("Unknown embryo lineage")
            stems.append(stem)
        if len(stems) != len(set(stems)):
            raise ValueError(f"Duplicate videos in {side}")
        names[side] = set(stems)
    if names["train"] & names["test"]:
        raise ValueError("Train/validation video overlap")
    return selected


def select_device(requested: str) -> torch.device:
    available = {"cpu": True, "cuda": torch.cuda.is_available(), "mps": torch.backends.mps.is_available()}
    if requested == "auto":
        requested = next(name for name in ("cuda", "mps", "cpu") if available[name])
    if requested not in available or not available[requested]:
        raise ValueError(f"Requested device is unavailable: {requested}; no fallback performed")
    return torch.device(requested)


def validate_seed(seed):
    """Validate a uint32 seed before changing any RNG state."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an int")
    if not 0 <= seed <= 2**32 - 1:
        raise ValueError("seed must be in [0, 2**32-1]")


def seed_rng(seed, device=None):
    """Seed CPU and selected accelerator RNGs, without claiming determinism.

    No global deterministic-algorithm flags are changed. Equal seeds do not
    establish cross-device reproducibility or complete resume support.
    """
    validate_seed(seed)
    if device is None:
        dev = torch.device("cpu")
    elif isinstance(device, (str, torch.device)):
        dev = torch.device(device)
    else:
        raise TypeError("device must be str or torch.device")
    if dev.type not in ("cpu", "cuda", "mps"):
        raise ValueError(f"Unsupported device type: {dev.type}")
    random.seed(seed)
    np.random.seed(seed)
    torch.random.default_generator.manual_seed(seed)
    accelerator = None
    if dev.type == "cuda":
        torch.cuda.manual_seed_all(seed)
        accelerator = "cuda"
    elif dev.type == "mps":
        torch.mps.manual_seed(seed)
        accelerator = "mps"
    return {"seed": seed, "python": True, "numpy": True, "torch_cpu": True,
            "accelerator": accelerator, "full_determinism": False}


def adapted_code(source: str, filename: str):
    """Adapt reviewed device/timing sites and observe the existing gradient clip."""
    tree = ast.parse(source, filename=filename)
    expected = ast.dump(ast.parse(DEVICE_EXPR, mode="eval").body)
    assignments = []
    barriers = []
    clips = []
    backwards = []
    expected_clip = ast.dump(ast.parse("torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)", mode="eval").body)
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if (function.name == "train" and isinstance(node, ast.Assign)
                    and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "device" and ast.dump(node.value) == expected):
                assignments.append(node)
            if (function.name == "train_epoch" and isinstance(node, ast.Call)
                    and ast.unparse(node.func) == "torch.cuda.synchronize" and not node.args
                    and not node.keywords):
                barriers.append(node)
            if function.name == "train_epoch" and isinstance(node, ast.Call) and ast.dump(node) == expected_clip:
                clips.append(node)
            if (function.name == "train_epoch" and isinstance(node, ast.Call)
                    and ast.unparse(node) == "loss.backward()"):
                backwards.append(node)
    if len(assignments) != 1 or len(barriers) != 3 or len(clips) != 1 or len(backwards) != 1:
        raise ValueError("Official trainer device/timing contract changed; refusing adaptation")
    assignments[0].value = ast.copy_location(ast.Name(id="_local_device", ctx=ast.Load()), assignments[0].value)
    for node in barriers:
        node.func = ast.copy_location(ast.Name(id="_local_synchronize", ctx=ast.Load()), node.func)
    clips[0].func = ast.copy_location(ast.Name(id="_local_clip_grad_norm", ctx=ast.Load()), clips[0].func)
    backwards[0].func.value = ast.Call(func=ast.Name(id="_local_checked_loss", ctx=ast.Load()),
                                      args=[ast.Name(id="loss", ctx=ast.Load())], keywords=[])
    return compile(ast.fix_missing_locations(tree), filename, "exec")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--device", choices=("auto", "cpu", "mps", "cuda"), default="auto")
    parser.add_argument("--check-device", action="store_true", help="Check availability without loading data")
    parser.add_argument("--diagnostic", action="store_true", help="Explicitly opt into non-candidate training")
    parser.add_argument("--seed", type=int, default=0, help="RNG seed (0..2**32-1)")
    parser.add_argument("--max-frames", type=int, default=4, help="Diagnostic frame cap per video (2..8)")
    parser.add_argument("--warm-start", type=Path)
    parser.add_argument("--warm-start-sha256")
    parser.add_argument("--freeze-detector", action="store_true")
    args, remaining = parser.parse_known_args()
    device = select_device(args.device)
    print(f"Local device: {device}; training status: DIAGNOSTIC_ONLY", flush=True)
    if args.check_device:
        return
    try:
        validate_seed(args.seed)
    except (TypeError, ValueError) as error:
        parser.error(str(error))
    if not args.diagnostic:
        parser.error("Candidate training is not instrumented; use --diagnostic for a bounded non-candidate run")
    if bool(args.warm_start) != bool(args.warm_start_sha256):
        parser.error("Warm-start path and pinned SHA256 must be supplied together")
    if args.freeze_detector and args.warm_start is None:
        parser.error("Freezing requires a pinned pretrained detector")
    # Require a separate output name and an explicit workload bound. Never use
    # the official default weights directory for a diagnostic.
    run_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    run_parser.add_argument("--method", required=True)
    run_parser.add_argument("--epochs", required=True, type=int)
    run_parser.add_argument("--max-iters", required=True, type=int)
    run_parser.add_argument("--splits", required=True, type=Path)
    run_parser.add_argument("--split", type=int, default=0)
    run_parser.add_argument("--debug-video")
    run_parser.add_argument("--det-loss-weight", type=float, default=1.0)
    run_parser.add_argument("--det-neg-weight", type=float, default=0.01)
    run_parser.add_argument("--unet-weights")
    run_args, _ = run_parser.parse_known_args(remaining)
    if run_args.unet_weights:
        parser.error("Partial strict=False initialization is disabled; use full --warm-start with SHA256")
    if (not run_args.method.startswith("local_diagnostic_") or "/" in run_args.method
            or "\\" in run_args.method or not 1 <= run_args.epochs <= 3 or not 1 <= run_args.max_iters <= 10):
        parser.error("Use local_diagnostic_<name>, epochs 1..3, and max-iters 1..10")
    if run_args.debug_video or not 2 <= args.max_frames <= 8:
        parser.error("Debug-video overlap is forbidden; max-frames must be 2..8")
    validate_split(run_args.splits, run_args.split)
    synchronize = {"cpu": lambda: None, "mps": torch.mps.synchronize, "cuda": torch.cuda.synchronize}[device.type]
    output_root = TRAINER.parents[2] / "outputs/local/training_diagnostics"
    if (output_root / run_args.method).exists():
        parser.error("Diagnostic output already exists; choose a new method name")
    seed_policy = seed_rng(args.seed, device)
    module_name = "_biohub_local_diagnostic_trainer"
    module = types.ModuleType(module_name)
    module.__dict__.update({"__file__": str(TRAINER),
                            "_local_device": device, "_local_synchronize": synchronize})
    previous_argv = sys.argv
    previous_path = sys.path[:]
    previous_module = sys.modules.get(module_name)
    try:
        sys.modules[module_name] = module
        sys.path[:0] = [str(TRAINER.parent), str(TRAINER.parents[1] / "src"), str(TRAINER.parents[2] / "src")]
        sys.argv = [str(TRAINER), *remaining]
        exec(adapted_code(TRAINER.read_text(), str(TRAINER)), module.__dict__)
        module.WEIGHTS_PATH = output_root
        original_train = module.train
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

        module._local_checked_loss = checked_loss
        detector_guard = None
        if args.warm_start is not None:
            original_model = module.UNetNodeTransformer

            def initialized_model(*model_args, **model_kwargs):
                nonlocal detector_guard
                model = original_model(*model_args, **model_kwargs)
                receipt = strict_warm_start(model, args.warm_start, args.warm_start_sha256)
                print("WARM_START " + json.dumps(receipt), flush=True)
                if args.freeze_detector:
                    detector_guard = freeze_detector(model)
                return model

            module.UNetNodeTransformer = initialized_model
        original_loader = module.load_dataset_windows

        def checked_loader(path, *args, **kwargs):
            metadata, windows = original_loader(path, *args, **kwargs)
            coverage = validate_window_coverage(windows, source=path)
            print("WINDOW_COVERAGE " + json.dumps(coverage), flush=True)
            return metadata, windows

        module.load_dataset_windows = checked_loader

        original_evaluate = module.evaluate
        original_train_epoch = module.train_epoch
        recorder = None
        evaluation_api = types.SimpleNamespace(evaluate=original_evaluate,
                                               compute_detection_loss=module.compute_detection_loss)

        def observed_evaluate(model, loader, device, pool_kernel_um=5.0):
            legacy, report = evaluate_components(
                evaluation_api, model, loader, device, det_loss_weight=run_args.det_loss_weight,
                det_neg_weight=run_args.det_neg_weight, pool_kernel_um=pool_kernel_um,
            )
            recorder.validation(report)
            print("VALIDATION_COMPONENTS " + json.dumps(report, allow_nan=False), flush=True)
            return legacy

        def bounded_train(*train_args, **kwargs):
            nonlocal recorder
            kwargs.update(max_frames=args.max_frames, seed=args.seed)
            from biohub.training_history import atomic_write_json, sha256_file

            split = validate_split(run_args.splits, run_args.split)
            inventory = diagnostic_input_manifest(kwargs["data_dir"], split, args.max_frames)
            run_manifest = {
                "status": "DIAGNOSTIC_ONLY", "resume_supported": False,
                "argv": previous_argv[1:], "device": str(device), "torch_version": str(torch.__version__),
                "split": split, "split_sha256": sha256_file(run_args.splits),
                "warm_start_sha256": args.warm_start_sha256, "freeze_detector": args.freeze_detector,
                "input_files": inventory, "loader_seed": args.seed, "full_determinism": False,
                "seed": args.seed, "seed_policy": seed_policy,
                "source_sha256": {str(path): sha256_file(path) for path in (
                    TRAINER, Path(__file__), TRAINER.parents[2] / "src/biohub/local_training.py")},
            }
            atomic_write_json(output_root / run_args.method / "diagnostic_manifest.json", run_manifest)
            recorder = DiagnosticRecorder(output_root / run_args.method / "diagnostic_history.jsonl",
                                          det_loss_weight=run_args.det_loss_weight,
                                          checkpoint_dir=output_root / run_args.method / "checkpoints")
            module._local_clip_grad_norm = recorder.clip_grad_norm
            try:
                result = original_train(*train_args, **kwargs)
            finally:
                recorder.close()
            if recorder.epoch != run_args.epochs:
                raise ValueError("Not all requested diagnostic epochs completed")
            selection = finalize_diagnostic_selection(
                output_root / run_args.method / "diagnostic_history.jsonl",
                output_root / run_args.method / "checkpoints",
                output_root / run_args.method / "diagnostic_selection.json",
            )
            print("DIAGNOSTIC_SELECTION " + json.dumps(selection), flush=True)
            return result

        def observed_train_epoch(*args, **kwargs):
            result = recorder.train_epoch(original_train_epoch, *args, **kwargs)
            if detector_guard is not None:
                detector_guard()
                print("FROZEN_DETECTOR state_unchanged=True", flush=True)
            return result

        module.train = bounded_train
        module.train_epoch = observed_train_epoch
        module.evaluate = observed_evaluate
        module.main()
    finally:
        sys.argv = previous_argv
        sys.path[:] = previous_path
        if previous_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module


if __name__ == "__main__":
    main()
