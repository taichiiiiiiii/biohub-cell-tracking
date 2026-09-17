"""Small synthetic files only; never opens competition GT or saved real CSVs."""

import json

import pytest

from scripts import e26_edge_diagnostic as runner


def test_binding_rejects_changed_bytes_and_size(tmp_path):
    path = tmp_path / "sample"
    path.write_bytes(b"abc")
    original = runner.binding(path)
    runner.verify_files([original])
    path.write_bytes(b"abd")
    with pytest.raises(ValueError, match="binding changed"):
        runner.verify_files([original])
    path.write_bytes(b"abcd")
    with pytest.raises(ValueError, match="binding changed"):
        runner.verify_files([original])


def test_fresh_json_refuses_overwrite(tmp_path):
    path = tmp_path / "result.json"
    runner.write_json(path, {"kept": 1})
    with pytest.raises(FileExistsError):
        runner.write_json(path, {"replaced": 1})
    assert json.loads(path.read_bytes()) == {"kept": 1}


def test_unknown_tree_member_rejected(tmp_path):
    first = tmp_path / "a"
    first.write_bytes(b"a")
    tree = {str(tmp_path): [str(first)]}
    runner.verify_trees(tree)
    (tmp_path / "b").write_bytes(b"b")
    with pytest.raises(ValueError, match="membership changed"):
        runner.verify_trees(tree)


def test_control_sha_fails_before_output_or_semantic_access(tmp_path):
    control, output = tmp_path / "control.json", tmp_path / "output"
    runner.write_json(control, {})
    with pytest.raises(ValueError, match="control identity mismatch"):
        runner.run(control, "0" * 64, output)
    assert not output.exists()


@pytest.mark.parametrize("corruption", [None, "extra_gt_file", "changed_gt", "csv_changed"])
def test_exact_twelve_selection_does_not_traverse_remaining_gt(tmp_path, monkeypatch, corruption):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    videos = []
    for stem in runner.STEMS:
        root = tmp_path / "data/train" / f"{stem}.geff"
        root.mkdir(parents=True)
        path = root / "fixture_bytes"
        path.write_bytes(b"opaque")
        meta = tmp_path / f"{stem}_meta.json"
        meta.write_bytes(b"opaque scale")
        b = runner.binding(path)
        videos.append({"dataset": stem, "gt_inventory": {"files": [{
            "selected_path": str(path), "relative_path": path.name, "sha256": b["sha256"],
            "stat": {"size": b["bytes"]},
        }]}, "image_metadata": {"root_metadata": runner.binding(meta)}})
    # It intentionally has no inventory; touching a remaining-24 video is a test failure.
    videos.append({"dataset": "remaining_24_must_not_be_opened"})
    gt = tmp_path / "GT_BINDING.json"
    runner.write_json(gt, {"eval36_order": [*runner.STEMS, "remaining_24_must_not_be_opened"], "videos": videos})
    csv = tmp_path / "submission.csv"
    csv.write_bytes(b"opaque csv")
    stage = tmp_path / "stage.json"
    runner.write_json(stage, {"subsets": {arm: {"datasets": list(runner.STEMS), "csv": runner.binding(csv)}
                                           for arm in ("baseline", "candidate")}})
    monkeypatch.setattr(runner, "SCORE", stage)
    monkeypatch.setattr(runner, "GT_BINDING", gt)
    monkeypatch.setattr(runner, "SCORE_SHA", runner.binding(stage)["sha256"])
    monkeypatch.setattr(runner, "GT_SHA", runner.binding(gt)["sha256"])
    if corruption == "extra_gt_file":
        (root / "new_chunk").write_bytes(b"unexpected")
    elif corruption == "changed_gt":
        path.write_bytes(b"wrong!")
    elif corruption == "csv_changed":
        csv.write_bytes(b"modified csv")
    if corruption:
        with pytest.raises(ValueError):
            runner.fixed_inputs()
    else:
        _, files, trees = runner.fixed_inputs()
        assert len(trees) == 12 and len(files) == 28


def test_budget_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "BUDGET", {"wall_seconds": -1, "peak_self_rss_bytes": 2**63, "output_bytes": 100})
    with pytest.raises(ValueError, match="wall budget"):
        runner.check_budget(runner.time.monotonic(), tmp_path)
