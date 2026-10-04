"""Focused regression tests for output bounds validation repairs."""

import copy
import json
from fractions import Fraction

import numpy as np
import pytest

from biohub.output_bounds import (
    INT64_MAX,
    OutputBoundsError,
    bounded_output_node,
    new_output_bounds_report,
    read_output_shape,
)

SHAPE = (100, 64, 256, 256)


def _report(dataset="demo", shape=SHAPE):
    return new_output_bounds_report(dataset, shape)


def _node(**overrides):
    row = {"node_id": 1, "t": 1, "z": 5.2, "y": 5.2, "x": 5.2}
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    "bad_shape",
    [None, 42, "shape", (x for x in (1, 2, 3, 4))],
    ids=["none", "scalar", "string", "generator"],
)
def test_new_report_rejects_invalid_shape_inputs(bad_shape):
    with pytest.raises(OutputBoundsError):
        new_output_bounds_report("demo", bad_shape)


@pytest.mark.parametrize(
    "bad_shape",
    [None, 42, "shape", (x for x in (1, 2, 3, 4))],
    ids=["none", "scalar", "string", "generator"],
)
def test_bounded_node_rejects_invalid_shape_inputs(bad_shape):
    report = _report()
    with pytest.raises(OutputBoundsError):
        bounded_output_node(_node(), "demo", 0, bad_shape, report)


def test_sample_rejects_out_of_bound_projection_with_consistent_max():
    report = _report()
    bounded_output_node(_node(x=300.0), "demo", 0, SHAPE, report)
    broken = copy.deepcopy(report)
    broken["samples"][0]["clipped_int"] = 254
    broken["samples"][0]["signed_delta"] = -46
    broken["samples"][0]["absolute_delta"] = 46
    broken["max_absolute_correction"] = 46
    with pytest.raises(OutputBoundsError):
        bounded_output_node(_node(), "demo", 9, SHAPE, broken)


def test_sample_rejects_t_equal_to_time_dimension():
    report = _report()
    bounded_output_node(_node(t=99, x=300.0), "demo", 0, SHAPE, report)
    broken = copy.deepcopy(report)
    broken["samples"][0]["t"] = SHAPE[0]
    with pytest.raises(OutputBoundsError):
        bounded_output_node(_node(), "demo", 9, SHAPE, broken)


def test_sample_rejects_row_id_above_int64_max():
    report = _report()
    bounded_output_node(_node(x=300.0), "demo", 0, SHAPE, report)
    broken = copy.deepcopy(report)
    broken["samples"][0]["row_id"] = 2**63
    with pytest.raises(OutputBoundsError):
        bounded_output_node(_node(), "demo", 9, SHAPE, broken)


def test_sample_rejects_node_id_above_int64_max():
    report = _report()
    bounded_output_node(_node(x=300.0), "demo", 0, SHAPE, report)
    broken = copy.deepcopy(report)
    broken["samples"][0]["node_id"] = 2**63
    with pytest.raises(OutputBoundsError):
        bounded_output_node(_node(), "demo", 9, SHAPE, broken)


def test_sample_rejects_t_above_int64_max():
    report = _report()
    bounded_output_node(_node(x=300.0), "demo", 0, SHAPE, report)
    broken = copy.deepcopy(report)
    broken["samples"][0]["t"] = 2**63
    with pytest.raises(OutputBoundsError):
        bounded_output_node(_node(), "demo", 9, SHAPE, broken)


def test_report_rejects_truncation_flag_mismatch_when_over_limit():
    report = _report()
    for idx in range(21):
        bounded_output_node(
            _node(node_id=idx, x=300.0), "demo", idx, SHAPE, report
        )
    assert report["samples_truncated"]
    broken = copy.deepcopy(report)
    broken["samples_truncated"] = False
    with pytest.raises(OutputBoundsError):
        bounded_output_node(_node(), "demo", 99, SHAPE, broken)


def test_report_rejects_truncation_flag_when_under_limit():
    report = _report()
    for idx in range(20):
        bounded_output_node(
            _node(node_id=idx, x=300.0 + idx), "demo", idx, SHAPE, report
        )
    assert not report["samples_truncated"]
    broken = copy.deepcopy(report)
    broken["samples_truncated"] = True
    with pytest.raises(OutputBoundsError):
        bounded_output_node(_node(), "demo", 99, SHAPE, broken)


def test_report_rejects_per_axis_count_exceeding_corrected_with_two_samples():
    report = _report()
    bounded_output_node(_node(x=300.0), "demo", 0, SHAPE, report)
    bounded_output_node(_node(x=301.0), "demo", 1, SHAPE, report)
    assert report["axis_counts"]["x"] == 2
    assert report["corrected_nodes"] == 2
    broken = copy.deepcopy(report)
    broken["corrected_nodes"] = 1
    broken["node_count"] = 2
    broken["max_absolute_correction"] = report["max_absolute_correction"]
    with pytest.raises(OutputBoundsError):
        bounded_output_node(_node(), "demo", 9, SHAPE, broken)


def test_report_rejects_distinct_identity_count_exceeding_corrected():
    report = _report()
    bounded_output_node(_node(y=300.0, x=300.0), "demo", 0, SHAPE, report)
    assert report["node_count"] == 1
    assert report["corrected_nodes"] == 1
    assert report["axis_counts"] == {"z": 0, "y": 1, "x": 1}
    assert len(report["samples"]) == 2
    assert report["max_absolute_correction"] == 45
    assert report["samples_truncated"] is False
    for field in ("row_id", "node_id", "t"):
        broken = copy.deepcopy(report)
        second = broken["samples"][1]
        if field == "row_id":
            second["row_id"] = second["row_id"] + 1
        elif field == "node_id":
            second["node_id"] = second["node_id"] + 1
        else:
            second["t"] = second["t"] + 1
        snapshot = copy.deepcopy(broken)
        with pytest.raises(OutputBoundsError):
            bounded_output_node(_node(), "demo", 9, SHAPE, broken)
        assert broken == snapshot
    positive = copy.deepcopy(report)
    bounded_output_node(_node(y=300.0, x=300.0), "demo", 0, SHAPE, positive)
    shared = copy.deepcopy(report)
    bounded_output_node(_node(y=300.0, x=300.0), "demo", 0, SHAPE, shared)
    bounded_output_node(_node(y=300.0, x=300.0), "demo", 0, SHAPE, shared)
    bounded_output_node(_node(y=300.0, x=300.0), "demo", 0, SHAPE, shared)


def test_repeated_identical_calls_accepted_as_corrected_count():
    report = _report()
    for _ in range(3):
        bounded_output_node(_node(x=300.0), "demo", 0, SHAPE, report)
    assert report["corrected_nodes"] == 3
    assert report["axis_counts"]["x"] == 3
    assert report["node_count"] == 3


def test_report_rejects_tuple_shape():
    report = _report()
    broken = copy.deepcopy(report)
    broken["shape"] = tuple(broken["shape"])
    with pytest.raises(OutputBoundsError):
        bounded_output_node(_node(), "demo", 9, SHAPE, broken)


def test_report_rejects_numpy_str_dataset():
    with pytest.raises(OutputBoundsError):
        new_output_bounds_report(np.str_("demo"), SHAPE)


def test_sample_rejects_numpy_str_axis():
    report = _report()
    bounded_output_node(_node(x=300.0), "demo", 0, SHAPE, report)
    broken = copy.deepcopy(report)
    broken["samples"][0]["axis"] = np.str_("x")
    with pytest.raises(OutputBoundsError):
        bounded_output_node(_node(), "demo", 9, SHAPE, broken)


def test_sample_rejects_numpy_str_dataset_field():
    report = _report()
    bounded_output_node(_node(x=300.0), "demo", 0, SHAPE, report)
    broken = copy.deepcopy(report)
    broken["samples"][0]["dataset"] = np.str_("demo")
    with pytest.raises(OutputBoundsError):
        bounded_output_node(_node(), "demo", 9, SHAPE, broken)


def test_sample_t_at_int64_max_rejected_when_within_t_dim():
    big_t = INT64_MAX + 2
    shape = (big_t, 64, 256, 256)
    report = _report(shape=shape)
    bounded_output_node(_node(t=INT64_MAX, x=300.0), "demo", 0, shape, report)
    broken = copy.deepcopy(report)
    broken["samples"][0]["t"] = INT64_MAX + 1
    with pytest.raises(OutputBoundsError):
        bounded_output_node(_node(), "demo", 9, shape, broken)


def test_positive_truncation_continues_accepting_calls():
    report = _report()
    for idx in range(25):
        bounded_output_node(
            _node(node_id=idx, x=300.0 + idx), "demo", idx, SHAPE, report
        )
    assert report["samples_truncated"]
    assert report["corrected_nodes"] == 25
    assert report["axis_counts"]["x"] == 25
    assert len(report["samples"]) == 20
    assert report["max_absolute_correction"] == 69
    visible_max = max(s["absolute_delta"] for s in report["samples"])
    assert visible_max == 64
    bounded_output_node(_node(node_id=25, x=325.0), "demo", 25, SHAPE, report)
    assert report["node_count"] == 26
    assert report["corrected_nodes"] == 26


def test_nan_row_id_raises_output_bounds_error():
    report = _report()
    with pytest.raises(OutputBoundsError):
        bounded_output_node(_node(), "demo", float("nan"), SHAPE, report)


def test_inf_node_id_raises_output_bounds_error():
    report = _report()
    with pytest.raises(OutputBoundsError):
        bounded_output_node(
            _node(node_id=float("inf")), "demo", 0, SHAPE, report
        )


def test_neg_inf_time_raises_output_bounds_error():
    report = _report()
    with pytest.raises(OutputBoundsError):
        bounded_output_node(
            _node(t=float("-inf")), "demo", 0, SHAPE, report
        )


def test_huge_fraction_coordinate_overflow_raises():
    report = _report()
    huge = Fraction(2**2000, 1)
    with pytest.raises(OutputBoundsError):
        bounded_output_node(_node(x=huge), "demo", 0, SHAPE, report)


def test_huge_finite_fraction_coordinate_accepted():
    report = _report()
    huge = Fraction(2**200, 1)
    result = bounded_output_node(_node(x=huge), "demo", 0, SHAPE, report)
    assert result["x"] == 255
    assert report["corrected_nodes"] == 1


def test_fractional_fraction_id_rejected():
    report = _report()
    with pytest.raises(OutputBoundsError):
        bounded_output_node(
            _node(node_id=Fraction(3, 2)), "demo", 0, SHAPE, report
        )


def test_exact_fraction_ids_accepted():
    report = _report()
    id_a = Fraction(2**53 + 1, 1)
    result = bounded_output_node(_node(x=300.0), "demo", int(id_a), SHAPE, report)
    assert result["id"] == int(id_a)
    id_b = Fraction(2**63 - 1, 1)
    result2 = bounded_output_node(
        _node(x=300.0), "demo", int(id_b), SHAPE, report
    )
    assert result2["id"] == int(id_b)


def test_numpy_integral_coordinates_accepted():
    report = _report()
    result = bounded_output_node(
        _node(x=np.int64(300)), "demo", 0, SHAPE, report
    )
    assert result["x"] == 255
    assert report["corrected_nodes"] == 1


def test_numpy_float_integral_id_accepted():
    report = _report()
    result = bounded_output_node(
        _node(x=300.0), "demo", np.int64(42), SHAPE, report
    )
    assert result["id"] == 42


def test_truncation_visible_x_exceeds_aggregate_only():
    report = _report()
    for idx in range(21):
        bounded_output_node(
            _node(node_id=idx, x=300.0), "demo", idx, SHAPE, report
        )
    assert report["samples_truncated"]
    assert report["axis_counts"]["x"] == 21
    broken = copy.deepcopy(report)
    broken["axis_counts"] = {"z": 21, "y": 0, "x": 0}
    with pytest.raises(OutputBoundsError):
        bounded_output_node(_node(), "demo", 99, SHAPE, broken)


def test_read_output_shape_rejects_non_path0_without_axes(tmp_path):
    dataset = "synth"
    root = tmp_path / f"{dataset}.zarr"
    (root / "0").mkdir(parents=True)
    group_meta = {
        "zarr_format": 3,
        "node_type": "group",
        "attributes": {
            "multiscales": [
                {
                    "datasets": [{"path": "0"}],
                    "axes": [
                        {"name": "t"},
                        {"name": "z"},
                        {"name": "y"},
                        {"name": "x"},
                    ],
                },
                {"datasets": [{"path": "1"}]},
            ]
        },
    }
    array_meta = {
        "zarr_format": 3,
        "node_type": "array",
        "shape": [10, 8, 16, 16],
    }
    (root / "zarr.json").write_text(json.dumps(group_meta), encoding="utf-8")
    (root / "0" / "zarr.json").write_text(
        json.dumps(array_meta), encoding="utf-8"
    )
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, dataset)


def test_read_output_shape_accepts_different_non_path0_axes(tmp_path):
    dataset = "synth"
    root = tmp_path / f"{dataset}.zarr"
    (root / "0").mkdir(parents=True)
    group_meta = {
        "zarr_format": 3,
        "node_type": "group",
        "attributes": {
            "multiscales": [
                {
                    "datasets": [{"path": "0"}],
                    "axes": [
                        {"name": "t"},
                        {"name": "z"},
                        {"name": "y"},
                        {"name": "x"},
                    ],
                },
                {
                    "datasets": [{"path": "1"}],
                    "axes": [
                        {"name": "c"},
                        {"name": "y"},
                        {"name": "x"},
                    ],
                },
            ]
        },
    }
    array_meta = {
        "zarr_format": 3,
        "node_type": "array",
        "shape": [10, 8, 16, 16],
    }
    (root / "zarr.json").write_text(json.dumps(group_meta), encoding="utf-8")
    (root / "0" / "zarr.json").write_text(
        json.dumps(array_meta), encoding="utf-8"
    )
    assert read_output_shape(tmp_path, dataset) == (10, 8, 16, 16)


def test_read_output_shape_rejects_malformed_utf8(tmp_path):
    dataset = "synth"
    root = tmp_path / f"{dataset}.zarr"
    (root / "0").mkdir(parents=True)
    (root / "zarr.json").write_bytes(b"\xff\xfe")
    (root / "0" / "zarr.json").write_text("{}", encoding="utf-8")
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, dataset)


def test_read_output_shape_rejects_malformed_json(tmp_path):
    dataset = "synth"
    root = tmp_path / f"{dataset}.zarr"
    (root / "0").mkdir(parents=True)
    (root / "zarr.json").write_text("{not valid json", encoding="utf-8")
    (root / "0" / "zarr.json").write_text("{}", encoding="utf-8")
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, dataset)


@pytest.mark.parametrize(
    "bad_axes",
    [None, [], [None], [{"name": ""}], [{"value": 1}]],
    ids=["none", "empty", "non-dict", "empty-name", "no-name"],
)
def test_read_output_shape_rejects_malformed_non_path0_axes(
    tmp_path, bad_axes
):
    dataset = "synth"
    root = tmp_path / f"{dataset}.zarr"
    (root / "0").mkdir(parents=True)
    entry1 = {
        "datasets": [{"path": "0"}],
        "axes": [
            {"name": "t"},
            {"name": "z"},
            {"name": "y"},
            {"name": "x"},
        ],
    }
    entry2 = {"datasets": [{"path": "1"}]}
    if bad_axes is not None:
        entry2["axes"] = bad_axes
    group_meta = {
        "zarr_format": 3,
        "node_type": "group",
        "attributes": {"multiscales": [entry1, entry2]},
    }
    array_meta = {
        "zarr_format": 3,
        "node_type": "array",
        "shape": [10, 8, 16, 16],
    }
    (root / "zarr.json").write_text(json.dumps(group_meta), encoding="utf-8")
    (root / "0" / "zarr.json").write_text(
        json.dumps(array_meta), encoding="utf-8"
    )
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, dataset)
