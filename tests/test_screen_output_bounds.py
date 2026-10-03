"""Synthetic boundary tests; no competition data, models, or GT."""
import csv
import io
from copy import deepcopy

import pytest

from biohub.output_bounds import OutputBoundsError
from biohub.public_postproc.csv_out import SubmissionCsvWriter
from biohub.screen_output_bounds import ScreenNodeSerializer, verify_screen_output_bounds


def _node(index=0, t=0, **xyz):
    return {"node_id": index, "t": t, "z": 1., "y": 2., "x": 3., **xyz}


def _write(tmp_path, nodes, shapes=None):
    shapes = shapes or {"arbitrary": (100, 64, 256, 256)}
    serializer = ScreenNodeSerializer(shapes)
    path = tmp_path / "submission.csv"
    with path.open("x", newline="") as handle:
        writer = SubmissionCsvWriter(handle, node_serializer=serializer)
        for dataset in shapes:
            writer.write_nodes(dataset, nodes)
    return path, serializer


@pytest.mark.parametrize("axis,dim", [("z", 64), ("y", 256), ("x", 256)])
@pytest.mark.parametrize("offset", [-.51, -.5, -.49, 0., .5, 5.])
def test_all_upper_axes_round_then_clamp(tmp_path, axis, dim, offset):
    node = _node(**{axis: dim + offset})
    original = deepcopy(node)
    path, serializer = _write(tmp_path, {0: node})
    with path.open(newline="") as handle:
        row = next(csv.DictReader(handle))
    assert int(row[axis]) == min(round(dim + offset), dim - 1)
    assert node == original
    verify_screen_output_bounds(serializer.snapshot(), path, shapes=serializer.shapes)


def test_legacy_lower_clips_are_not_new_csv_changes(tmp_path):
    path, serializer = _write(tmp_path, {0: _node(z=-.6, y=256., x=256.1)})
    report = serializer.snapshot()
    assert report["per_dataset"][0]["axis_counts"] == {"z": 1, "y": 1, "x": 1}
    assert report["corrections"][0]["legacy_csv_delta"] == {"z": 0, "y": -1, "x": -1}
    assert report["per_dataset"][0]["corrected_nodes"] == 1
    verify_screen_output_bounds(report, path, shapes=serializer.shapes)


def test_complete_audit_beyond_twenty_samples_and_literal_datasets(tmp_path):
    nodes = {i: _node(i, y=256.4, x=-.6) for i in range(32)}
    shapes = {"last_lexically": (100, 64, 256, 256), "a_first": (100, 64, 256, 256)}
    path, serializer = _write(tmp_path, nodes, shapes)
    report = serializer.snapshot()
    assert len(report["corrections"]) == 64
    assert [p["dataset"] for p in report["per_dataset"]] == list(shapes)
    assert all(p["samples_truncated"] and len(p["samples"]) == 20 for p in report["per_dataset"])
    verify_screen_output_bounds(report, path, shapes=shapes)
    report["corrections"].clear()
    assert len(serializer.snapshot()["corrections"]) == 64


def test_default_writer_byte_compatibility_and_only_expected_coordinate_differences(tmp_path):
    nodes = {2: _node(2, 1, z=-.6, x=256.), 1: _node(1, z=2.5, y=3.5, x=255.49)}
    original = deepcopy(nodes)
    legacy, adapted = io.StringIO(), io.StringIO()
    serializer = ScreenNodeSerializer({"not_hardcoded": (2, 64, 256, 256)})
    for handle, kwargs in ((legacy, {}), (adapted, {"node_serializer": serializer})):
        writer = SubmissionCsvWriter(handle, **kwargs)
        writer.write_nodes("not_hardcoded", nodes)
        assert writer.write_edges("not_hardcoded", nodes, [{"source_id": 1, "target_id": 2}]) == {1: 1}
        assert writer.row_id == 3
    assert legacy.getvalue() == (
        "id,dataset,row_type,node_id,t,z,y,x,source_id,target_id\r\n"
        "0,not_hardcoded,node,1,0,2,4,255,-1,-1\r\n"
        "1,not_hardcoded,node,2,1,0,2,256,-1,-1\r\n"
        "2,not_hardcoded,edge,-1,-1,-1,-1,-1,1,2\r\n"
    )
    assert adapted.getvalue() == legacy.getvalue().replace(
        "1,not_hardcoded,node,2,1,0,2,256,-1,-1", "1,not_hardcoded,node,2,1,0,2,255,-1,-1")
    assert nodes == original


@pytest.mark.parametrize("field,value", [
    ("t", 100), ("t", -1), ("t", True), ("t", .5), ("node_id", -1),
    ("x", float("nan")), ("x", float("inf")), ("x", True), ("x", "256"),
])
def test_invalid_nodes_do_not_mutate_adapter(field, value):
    serializer = ScreenNodeSerializer({"ds": (100, 64, 256, 256)})
    before = serializer.snapshot()
    with pytest.raises(OutputBoundsError):
        serializer(_node(**{field: value}), "ds", 0)
    assert serializer.snapshot() == before


@pytest.mark.parametrize("fault", ["count", "sample", "node", "float_type", "delta", "missing", "duplicate",
                                   "reordered", "fake_correction", "policy", "extra", "dataset_order"])
def test_bounds_audit_tampering_is_rejected(tmp_path, fault):
    path, serializer = _write(tmp_path, {0: _node(x=256.), 1: _node(1, y=-.6)},
                              {"b": (100, 64, 256, 256), "a": (100, 64, 256, 256)})
    payload = serializer.snapshot()
    if fault == "count":
        payload["per_dataset"][0]["node_count"] += 1
    elif fault == "sample":
        payload["per_dataset"][0]["samples"][0]["original_float"] += .1
    elif fault == "node":
        payload["corrections"][0]["node"]["node_id"] = 99
    elif fault == "float_type":
        payload["corrections"][0]["node"]["x"] = 256
    elif fault == "delta":
        payload["corrections"][0]["legacy_csv_delta"]["x"] = 0
    elif fault == "missing":
        payload["corrections"].pop()
    elif fault == "duplicate":
        payload["corrections"].append(payload["corrections"][-1])
    elif fault == "reordered":
        payload["corrections"].reverse()
    elif fault == "fake_correction":
        payload["corrections"][0]["node"]["x"] = 0.
    elif fault == "policy":
        payload["policy"] = "legacy"
    elif fault == "extra":
        payload["unexpected"] = True
    else:
        payload["per_dataset"].reverse()
    with pytest.raises(OutputBoundsError):
        verify_screen_output_bounds(payload, path, shapes=serializer.shapes)


def test_actual_csv_correction_mismatch_and_missing_row_rejected(tmp_path):
    path, serializer = _write(tmp_path, {0: _node(x=256.)})
    text = path.read_text()
    path.write_text(text.replace(",255,-1,-1", ",254,-1,-1"))
    with pytest.raises(OutputBoundsError, match="actual CSV"):
        verify_screen_output_bounds(serializer.snapshot(), path, shapes=serializer.shapes)
    path.write_text(text.splitlines()[0] + "\n")
    with pytest.raises(OutputBoundsError, match="missing"):
        verify_screen_output_bounds(serializer.snapshot(), path, shapes=serializer.shapes)


def test_default_and_bounded_writer_identical_when_no_upper_change():
    nodes = {i: _node(i, z=-.6, y=2.5, x=3.5) for i in range(3)}
    out = []
    for serializer in (None, ScreenNodeSerializer({"ds": (4, 8, 16, 32)})):
        handle = io.StringIO()
        writer = SubmissionCsvWriter(handle, node_serializer=serializer)
        writer.write_nodes("ds", nodes)
        writer.write_edges("ds", nodes, [])
        out.append(handle.getvalue())
    assert out[0] == out[1]
