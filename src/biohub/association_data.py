"""Fixed whole-video candidate inputs, verified before annotation access.

Qwen draft corrected for the actual inventory/window schemas. Does not perform
training or certify a candidate. Official normalization and padding are reused.
"""
import csv
import hashlib
import json
import math
import re
from pathlib import Path

import torch
from torch.utils.data import default_collate

from biohub.training_history import _contained_regular_file, sha256_file, strict_json_load

PLAN_SHA = "6ae8a69d0856390d1590108b6350d1059b6d7875c6efc5923265f4de36dfcb14"


def verify_acquisition(data_root, receipt_dir, plan_path):
    data_root, receipt_dir, plan_path = Path(data_root), Path(receipt_dir), Path(plan_path)
    if sha256_file(plan_path) != PLAN_SHA:
        raise ValueError("Acquisition plan hash mismatch")
    plan = strict_json_load(plan_path)
    stems = plan["train"] + plan["selection"]
    if (len(plan["train"]) != 8 or len(plan["selection"]) != 4 or len(set(stems)) != 12
            or any(not isinstance(stem, str) or re.fullmatch(r"(?:44b6|6bba)_[a-zA-Z0-9]+", stem) is None
                   for stem in stems)):
        raise ValueError("Invalid fixed split")
    completed = strict_json_load(_contained_regular_file(receipt_dir, "completed.json"))
    if (completed.get("status") != "ACQUIRED_SIZE_CHECKED_LOCALLY_HASHED"
            or completed.get("plan_sha256") != PLAN_SHA
            or completed.get("files") != plan["expected_files"] or completed.get("bytes") != plan["expected_bytes"]):
        raise ValueError("Acquisition not complete for fixed plan")
    files_path = _contained_regular_file(receipt_dir, "files.json")
    if sha256_file(files_path) != completed["files_manifest_sha256"]:
        raise ValueError("Acquisition files receipt hash mismatch")
    entries = strict_json_load(files_path)
    if not isinstance(entries, list) or len(entries) != plan["expected_files"]:
        raise ValueError("Acquisition files receipt count mismatch")
    expected = {}
    roots = {f"{stem}.{suffix}" for stem in stems for suffix in ("zarr", "geff")}
    with _contained_regular_file(data_root, "manifest.csv").open(newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["name", "size"]:
            raise ValueError("Unexpected Kaggle inventory schema")
        for row in reader:
            name = row["name"]
            parts = Path(name).parts
            if len(parts) >= 3 and parts[0] == "train" and parts[1] in roots:
                if name in expected or ".." in parts:
                    raise ValueError("Duplicate or unsafe inventory path")
                expected[name] = int(row["size"])
                if expected[name] < 0:
                    raise ValueError("Negative inventory size")
    digest = hashlib.sha256(json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if (digest != plan["path_size_inventory_sha256"] or len(expected) != plan["expected_files"]
            or sum(expected.values()) != plan["expected_bytes"]):
        raise ValueError("Fixed path/size inventory mismatch")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"}:
            raise ValueError("Invalid acquisition file record")
        name = entry["path"]
        if name not in expected or name in seen or type(entry["bytes"]) is not int or entry["bytes"] != expected[name]:
            raise ValueError("Acquisition file set/size mismatch")
        path = _contained_regular_file(data_root, name)
        if path.stat().st_size != expected[name] or sha256_file(path) != entry["sha256"]:
            raise ValueError("Acquired file bytes changed")
        seen.add(name)
    if seen != set(expected) or sha256_file(plan_path) != PLAN_SHA or sha256_file(files_path) != completed[
        "files_manifest_sha256"
    ]:
        raise ValueError("Acquisition inventory drift")
    return plan


def _window_coverage(vm, windows, stem, path):
    if (len(vm.image_shape) != 4 or vm.image_shape[0] != 100 or any(size <= 0 for size in vm.image_shape)
            or tuple(vm.downsample) != (1, 4, 4) or Path(vm.zarr_path).resolve() != path.resolve()
            or not all(math.isfinite(value) for value in (vm.q_low, vm.q_high)) or vm.q_high <= vm.q_low):
        raise ValueError("Unexpected video shape/preprocessing metadata")
    times = [window.t_start for window in windows]
    if (not times or any(type(t) is not int or not 0 <= t < 99 for t in times)
            or times != sorted(set(times))):
        raise ValueError("Empty or invalid whole-video window sequence")
    positive, occurrences, zero_ids, ids = 0, 0, [], []
    for window in windows:
        if (window.n_frames != 2 or len(window.node_counts) != 2
                or any(type(count) is not int or count <= 0 for count in window.node_counts)
                or len(window.targets) != 1):
            raise ValueError("Invalid retained window metadata")
        target = window.targets[0]
        if (not isinstance(target, torch.Tensor) or target.device.type != "cpu"
                or tuple(target.shape) != tuple(window.node_counts)
                or not bool(torch.isfinite(target).all()) or not bool(((target == 0) | (target == 1)).all())):
            raise ValueError("Invalid target matrix")
        identity = f"{stem}:{window.t_start:03d}-{window.t_start + 1:03d}"
        ids.append(identity)
        count = int(torch.count_nonzero(target))
        occurrences += count
        positive += count > 0
        if count == 0:
            zero_ids.append(identity)
    if positive == 0:
        raise ValueError(f"No positive tracking windows in fixed video: {stem}")
    return ids, {"total_windows": 99, "usable_windows": len(windows), "positive_windows": positive,
                 "zero_edge_windows": zero_ids, "positive_edge_occurrences": occurrences,
                 "excluded_windows": [{"t_start": time,
                                       "reason": "official_no_gt_nodes_in_at_least_one_frame"}
                                      for time in range(99) if time not in set(times)]}


def prepare_windows(api, data_root, receipt_dir, plan_path):
    plan = verify_acquisition(data_root, receipt_dir, plan_path)  # Before any annotation/API call.
    sides = {"train": plan["train"], "validation": plan["selection"]}
    video_data, identities, coverage = {}, {}, {}
    max_nodes = 0
    for side, stems in sides.items():
        video_data[side], identities[side] = [], []
        for stem in stems:
            path = Path(data_root) / "train" / f"{stem}.zarr"
            vm, windows = api.load_dataset_windows(path, window_size=2, invert_time=False,
                                                   max_frames=None, downsample=(1, 4, 4))
            ids, coverage[stem] = _window_coverage(vm, windows, stem, path)
            video_data[side].append((vm, windows))
            identities[side].extend((stem, identity) for identity in ids)
            max_nodes = max(max_nodes, max(max(window.node_counts) for window in windows))
    datasets, split = {}, {}
    for side, stems in sides.items():
        dataset = api.FrameWindowDataset(video_data[side], max_nodes=max_nodes, augmentations=[])
        if len(dataset) != len(identities[side]):
            raise ValueError("Official dataset length differs from window inventory")
        datasets[side] = dataset
        split[side] = {"stems": list(stems), "videos": len(stems), "examples": len(dataset), "batches": len(dataset),
                       "lineages": {lineage: sum(stem.startswith(lineage + "_") for stem, _ in identities[side])
                                    for lineage in ("44b6", "6bba")},
                       "example_ids": [identity for _, identity in identities[side]]}
        if any(count == 0 for count in split[side]["lineages"].values()):
            raise ValueError("Fixed split lacks lineage coverage")
    return {"datasets": datasets, "identities": identities, "split": split, "coverage": coverage,
            "max_nodes": max_nodes}


def iter_batches(prepared, side, generator=None):
    if side not in ("train", "validation"):
        raise ValueError("Unknown split side")
    dataset, identities = prepared["datasets"][side], prepared["identities"][side]
    if len(dataset) != len(identities):
        raise ValueError("Dataset identity count changed")
    if side == "train":
        if not isinstance(generator, torch.Generator) or generator.device.type != "cpu":
            raise ValueError("Training requires a dedicated CPU sampler generator")
        order = torch.randperm(len(dataset), generator=generator).tolist()
    else:
        if generator is not None:
            raise ValueError("Validation must not shuffle or advance sampler RNG")
        order = range(len(dataset))
    for index in order:
        stem, identity = identities[index]
        yield stem, identity, default_collate([dataset[index]])
