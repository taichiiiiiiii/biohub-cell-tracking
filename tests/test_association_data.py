import csv
import hashlib
import json
from types import SimpleNamespace

import pytest
import torch

from biohub import association_data as data
from biohub.training_history import atomic_write_json, sha256_file


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    root = tmp_path.resolve() / "data"
    root.mkdir()
    train = [f"{lineage}_t{i}" for lineage in ("44b6", "6bba") for i in range(4)]
    selection = [f"{lineage}_v{i}" for lineage in ("44b6", "6bba") for i in range(2)]
    expected, files = {}, []
    for stem in train + selection:
        for suffix in ("zarr", "geff"):
            name = f"train/{stem}.{suffix}/zarr.json"
            path = root / name
            path.parent.mkdir(parents=True)
            path.write_bytes(b"{}")
            expected[name] = 2
            files.append({"path": name, "bytes": 2, "sha256": sha256_file(path)})
    with (root / "manifest.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["name", "size"])
        writer.writerows(expected.items())
        writer.writerow(["train/unselected.zarr/zarr.json", 123])
    plan = {"train": train, "selection": selection, "expected_files": 24, "expected_bytes": 48,
            "path_size_inventory_sha256": hashlib.sha256(
                json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
    plan_path = tmp_path / "plan.json"
    atomic_write_json(plan_path, plan)
    monkeypatch.setattr(data, "PLAN_SHA", sha256_file(plan_path))
    receipt = tmp_path / "receipt"
    atomic_write_json(receipt / "files.json", files)
    atomic_write_json(receipt / "completed.json", {"status": "ACQUIRED_SIZE_CHECKED_LOCALLY_HASHED",
                      "plan_sha256": data.PLAN_SHA, "files": 24, "bytes": 48,
                      "files_manifest_sha256": sha256_file(receipt / "files.json")})
    return root, receipt, plan_path, plan


class FakeAPI:
    def __init__(self, damage=None):
        self.calls = []
        self.damage = damage

    def load_dataset_windows(self, path, **kwargs):
        self.calls.append(path)
        assert kwargs == {"window_size": 2, "invert_time": False, "max_frames": None, "downsample": (1, 4, 4)}
        vm = SimpleNamespace(zarr_path=path, image_shape=(100, 2, 4, 4), downsample=(1, 4, 4), q_low=0., q_high=1.)
        windows = [SimpleNamespace(t_start=i, n_frames=2, node_counts=[1, 1], targets=[torch.tensor([[float(i == 0)]])])
                   for i in (0, 1)]
        if self.damage == "zero_positive":
            windows[0].targets[0].zero_()
        elif self.damage == "duplicate":
            windows[1].t_start = 0
        elif self.damage == "bad_target":
            windows[0].targets[0].fill_(2)
        elif self.damage == "empty":
            windows = []
        return vm, windows

    class FrameWindowDataset:
        def __init__(self, videos, max_nodes, augmentations):
            assert max_nodes == 1 and augmentations == []
            self.items = [(vm, window) for vm, windows in videos for window in windows]

        def __len__(self):
            return len(self.items)

        def __getitem__(self, index):
            return {"imgs": torch.ones(2, 1, 1, 1).half(), "index": torch.tensor(index)}


def test_verified_inputs_full_coverage_and_resume_sampler_order(inputs):
    root, receipt, plan_path, plan = inputs
    api = FakeAPI()
    prepared = data.prepare_windows(api, root, receipt, plan_path)
    assert len(api.calls) == 12
    assert prepared["split"]["train"]["lineages"] == {"44b6": 8, "6bba": 8}
    assert prepared["split"]["validation"]["examples"] == 8
    for stem in plan["train"] + plan["selection"]:
        coverage = prepared["coverage"][stem]
        assert coverage["positive_windows"] == 1
        assert coverage["positive_edge_occurrences"] == 1
        assert coverage["zero_edge_windows"] == [f"{stem}:001-002"]
        assert len(coverage["excluded_windows"]) == 97
    generator = torch.Generator().manual_seed(123)
    saved = generator.get_state()
    global_before = torch.get_rng_state().clone()
    first = [identity for _, identity, _ in data.iter_batches(prepared, "train", generator)]
    generator.set_state(saved)
    assert first == [identity for _, identity, _ in data.iter_batches(prepared, "train", generator)]
    assert len(first) == 16 and len(set(first)) == 16
    validation = list(data.iter_batches(prepared, "validation"))
    assert [identity for _, identity, _ in validation] == prepared["split"]["validation"]["example_ids"]
    assert validation[0][2]["imgs"].shape == (1, 2, 1, 1, 1)
    assert validation[0][2]["imgs"].dtype == torch.float16  # Preserve official storage precision.
    assert torch.equal(global_before, torch.get_rng_state())
    with pytest.raises(ValueError):
        list(data.iter_batches(prepared, "validation", generator))
    with pytest.raises(ValueError):
        list(data.iter_batches(prepared, "train"))


@pytest.mark.parametrize("damage", ["incomplete", "same_size_change", "missing", "symlink", "receipt_hash", "manifest"])
def test_acquisition_failure_precedes_any_annotation_api_call(inputs, damage):
    root, receipt, plan_path, plan = inputs
    target = root / f"train/{plan['train'][0]}.zarr/zarr.json"
    if damage == "incomplete":
        (receipt / "completed.json").unlink()
    elif damage == "same_size_change":
        target.write_bytes(b"[]")
    elif damage == "missing":
        target.unlink()
    elif damage == "symlink":
        target.unlink()
        target.symlink_to(plan_path)
    elif damage == "receipt_hash":
        (receipt / "files.json").write_text("[]")
    else:
        with (root / "manifest.csv").open("a") as stream:
            stream.write(f"train/{plan['train'][0]}.zarr/unexpected,0\n")
    api = FakeAPI()
    with pytest.raises((ValueError, OSError)):
        data.prepare_windows(api, root, receipt, plan_path)
    assert api.calls == []


@pytest.mark.parametrize("damage", ["zero_positive", "duplicate", "bad_target", "empty"])
def test_bad_video_fails_instead_of_silent_exclusion_or_replacement(inputs, damage):
    root, receipt, plan_path, _ = inputs
    api = FakeAPI(damage)
    with pytest.raises(ValueError):
        data.prepare_windows(api, root, receipt, plan_path)
    assert len(api.calls) == 1
