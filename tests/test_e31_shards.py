import csv
import hashlib
import json
from pathlib import Path

import pytest

from biohub.e31_shards import _validated_child, merge_shards
from biohub.public_postproc.csv_out import SubmissionCsvWriter
from biohub.screen_output_bounds import ScreenNodeSerializer


def make_child(base: Path, stems: list[str]) -> dict:
    base.mkdir(parents=True, exist_ok=True)
    shapes = {s: (2, 2, 4, 4) for s in stems}
    serializer = ScreenNodeSerializer(shapes)
    nodes = {
        10: {"node_id": 10, "t": 0, "z": 0.0, "y": 0.0, "x": 0.0},
        20: {"node_id": 20, "t": 1, "z": 0.0, "y": 0.0, "x": 9.0},
    }
    edges = [{"source_id": 10, "target_id": 20}]
    with open(base / "submission.csv", "w", newline="") as handle:
        writer = SubmissionCsvWriter(handle, node_serializer=serializer)
        for stem in sorted(stems):
            writer.write_nodes(stem, nodes)
            writer.write_edges(stem, nodes, edges)
    bounds = serializer.snapshot()
    (base / "e31_output_bounds.json").write_text(json.dumps(bounds))
    csv_sha = hashlib.sha256((base / "submission.csv").read_bytes()).hexdigest()
    receipt = {
        "csv_sha256": csv_sha,
        "stems": sorted(stems),
        "shapes": shapes,
        "E31_HASHES": {"payload": "test"},
        "insertion_receipt": {"source": "test"},
        "deepcenter_receipt": {"source": "test"},
        "elapsed": 1.0,
        "hypothesis": "primary-only reciprocal consensus",
    }
    (base / "e31_submission_receipt.json").write_text(json.dumps(receipt))
    with open(base / "run_stats.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dataset", "value"])
        for stem in sorted(stems):
            w.writerow([stem, "0"])
    return receipt


def test_merge_shards_success(tmp_path: Path):
    working = tmp_path / "working"
    child0 = working / "e31_shard_0"
    child1 = working / "e31_shard_1"
    make_child(child0, ["a", "c"])
    make_child(child1, ["b", "d"])
    before0 = (child0 / "submission.csv").read_bytes()
    before1 = (child1 / "submission.csv").read_bytes()
    expected_dir = tmp_path / "expected"
    make_child(expected_dir, ["a", "b", "c", "d"])
    expected_csv = (expected_dir / "submission.csv").read_bytes()
    expected_bounds = json.loads((expected_dir / "e31_output_bounds.json").read_text())
    parent = working
    merge_shards(parent, [["a", "c"], ["b", "d"]], {"payload": "test"})
    assert (parent / "submission.csv").read_bytes() == expected_csv
    assert json.loads((parent / "e31_output_bounds.json").read_text()) == expected_bounds
    receipt = json.loads((parent / "e31_submission_receipt.json").read_text())
    assert receipt["stems"] == ["a", "b", "c", "d"]
    assert set(receipt["shapes"].keys()) == {"a", "b", "c", "d"}
    assert receipt["csv_sha256"] == hashlib.sha256(expected_csv).hexdigest()
    assert (child0 / "submission.csv").read_bytes() == before0
    assert (child1 / "submission.csv").read_bytes() == before1
    with pytest.raises(FileExistsError):
        merge_shards(parent, [["a", "c"], ["b", "d"]], {"payload": "test"})


@pytest.mark.parametrize(
    "field,value",
    [
        ("csv_sha256", "bad"),
        ("E31_HASHES", {}),
        ("stems", ["WRONG"]),
        ("shapes", {}),
        ("elapsed", float("nan")),
        ("hypothesis", "wrong"),
        ("insertion_receipt", {"source": "wrong"}),
    ],
)
def test_merge_shards_corrupt_receipt(tmp_path: Path, field, value):
    working = tmp_path / "working"
    child0 = working / "e31_shard_0"
    child1 = working / "e31_shard_1"
    make_child(child0, ["a"])
    make_child(child1, ["b"])
    receipt_path = child0 / "e31_submission_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt[field] = value
    receipt_path.write_text(json.dumps(receipt))
    parent = working
    with pytest.raises(ValueError):
        merge_shards(parent, [["a"], ["b"]], {"payload": "test"})
    assert not (parent / "e31_submission_receipt.json").exists()
    assert not (parent / "submission.csv").exists()


def test_validated_child_returns_tuple(tmp_path: Path):
    child = tmp_path / "shard"
    make_child(child, ["a"])
    result = _validated_child(child, ["a"], {"payload": "test"})
    receipt, bounds = result
    assert receipt["stems"] == ["a"]
    assert "schema_version" in bounds
