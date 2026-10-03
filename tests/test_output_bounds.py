import copy
import inspect
import json
import math
from fractions import Fraction

import numpy as np
import pytest

from biohub.output_bounds import (
    OutputBoundsError,
    bounded_output_node,
    new_output_bounds_report,
    read_output_shape,
)

SHAPE = (100, 64, 256, 256)
TZYX = [{"name": "T"}, {"name": "Z"}, {"name": "Y"}, {"name": "X"}]


def write_metadata(
    tmp_path,
    dataset,
    shape=(100, 64, 256, 256),
    *,
    axes=None,
    extra_entries=(),
    child_node="array",
    zarr_format_root=3,
    zarr_format_child=3,
):
    root = tmp_path / f"{dataset}.zarr"
    (root / "0").mkdir(parents=True)
    if axes is None:
        axes = TZYX
    entry = {"axes": axes, "datasets": [{"path": "0"}]}
    group = {
        "zarr_format": zarr_format_root,
        "node_type": "group",
        "attributes": {"multiscales": [entry, *extra_entries]},
    }
    child = {
        "zarr_format": zarr_format_child,
        "node_type": child_node,
        "shape": list(shape),
    }
    (root / "zarr.json").write_text(json.dumps(group), encoding="utf-8")
    (root / "0" / "zarr.json").write_text(json.dumps(child), encoding="utf-8")
    return root


def make_node(node_id=7, t=3, z=10.5, y=20.25, x=30.0):
    return {"node_id": node_id, "t": t, "z": z, "y": y, "x": x}


def report_for(dataset="demo", shape=SHAPE):
    return new_output_bounds_report(dataset, shape)


def node_row(**overrides):
    row = {"node_id": 1, "t": 1, "z": 5.2, "y": 5.2, "x": 5.2}
    row.update(overrides)
    return row


def entry(paths, axes=None):
    return {
        "axes": axes if axes is not None else TZYX,
        "datasets": [{"path": p} for p in paths],
    }


# ---------------------------------------------------------------- shape reading


def test_read_output_shape_ok(tmp_path):
    write_metadata(tmp_path, "demo")
    assert read_output_shape(tmp_path, "demo") == (100, 64, 256, 256)


def test_read_output_shape_missing(tmp_path):
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "absent")


def test_read_output_shape_invalid_json(tmp_path):
    root = write_metadata(tmp_path, "demo")
    (root / "0" / "zarr.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_read_output_shape_wrong_root_node_type(tmp_path):
    root = write_metadata(tmp_path, "demo")
    group = json.loads((root / "zarr.json").read_text(encoding="utf-8"))
    group["node_type"] = "array"
    (root / "zarr.json").write_text(json.dumps(group), encoding="utf-8")
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_read_output_shape_wrong_child_node_type(tmp_path):
    write_metadata(tmp_path, "demo", child_node="group")
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


@pytest.mark.parametrize("version", [2, "3", None, 3.0])
def test_read_output_shape_rejects_non_zarr3(tmp_path, version):
    root = write_metadata(tmp_path, "demo")
    group = json.loads((root / "zarr.json").read_text(encoding="utf-8"))
    child = json.loads((root / "0" / "zarr.json").read_text(encoding="utf-8"))
    if version is None:
        del group["zarr_format"]
    else:
        group["zarr_format"] = version
    (root / "zarr.json").write_text(json.dumps(group), encoding="utf-8")
    (root / "0" / "zarr.json").write_text(json.dumps(child), encoding="utf-8")
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_read_output_shape_child_version_three_point_zero(tmp_path):
    write_metadata(tmp_path, "demo", zarr_format_child=3.0)
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_read_output_shape_wrong_axis_order(tmp_path):
    swapped = [{"name": "T"}, {"name": "Y"}, {"name": "Z"}, {"name": "X"}]
    write_metadata(tmp_path, "demo", axes=swapped)
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_read_output_shape_axis_rank_mismatch(tmp_path):
    write_metadata(
        tmp_path, "demo", axes=[{"name": "T"}, {"name": "Z"}, {"name": "Y"}]
    )
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_read_output_shape_lowercase_axes_accepted(tmp_path):
    lower = [{"name": "t"}, {"name": "z"}, {"name": "y"}, {"name": "x"}]
    write_metadata(tmp_path, "demo", axes=lower)
    assert read_output_shape(tmp_path, "demo") == (100, 64, 256, 256)


def test_read_output_shape_rank_mismatch(tmp_path):
    write_metadata(tmp_path, "demo", shape=(64, 256, 256))
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


@pytest.mark.parametrize("bad", [0, -5, 4.5, True, False, "64"])
def test_read_output_shape_bad_dims(tmp_path, bad):
    write_metadata(tmp_path, "demo", shape=(100, bad, 256, 256))
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_read_output_shape_duplicate_path_zero_within_one_entry(tmp_path):
    dup_entry = entry(["0", "0"])
    write_metadata(tmp_path, "demo", extra_entries=[dup_entry])
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_read_output_shape_duplicate_path_zero_across_entries(tmp_path):
    write_metadata(tmp_path, "demo", extra_entries=[entry(["0"])])
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_duplicate_path_zero_in_wrong_axis_entry_is_not_hidden(tmp_path):
    wrong_axes = [
        {"name": "X"},
        {"name": "Y"},
        {"name": "Z"},
        {"name": "T"},
    ]
    write_metadata(tmp_path, "demo", extra_entries=[entry(["0"], axes=wrong_axes)])
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_duplicate_path_zero_in_malformed_entry_is_not_hidden(tmp_path):
    root = write_metadata(tmp_path, "demo")
    group = json.loads((root / "zarr.json").read_text(encoding="utf-8"))
    group["attributes"]["multiscales"].append({"axes": TZYX, "datasets": ["0"]})
    (root / "zarr.json").write_text(json.dumps(group), encoding="utf-8")
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_malformed_multiscales_entry_rejected(tmp_path):
    root = write_metadata(tmp_path, "demo")
    group = json.loads((root / "zarr.json").read_text(encoding="utf-8"))
    group["attributes"]["multiscales"].append("nonsense")
    (root / "zarr.json").write_text(json.dumps(group), encoding="utf-8")
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_multiscales_not_a_list_rejected(tmp_path):
    root = write_metadata(tmp_path, "demo")
    group = json.loads((root / "zarr.json").read_text(encoding="utf-8"))
    group["attributes"]["multiscales"] = {"axes": TZYX}
    (root / "zarr.json").write_text(json.dumps(group), encoding="utf-8")
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_unique_paths_zero_and_one_allowed_with_other_entries(tmp_path):
    write_metadata(tmp_path, "demo", extra_entries=[entry(["1", "2"])])
    assert read_output_shape(tmp_path, "demo") == (100, 64, 256, 256)


def test_path_zero_need_not_be_first_dataset(tmp_path):
    root = write_metadata(tmp_path, "demo")
    group = json.loads((root / "zarr.json").read_text(encoding="utf-8"))
    group["attributes"]["multiscales"] = [entry(["1", "0"])]
    (root / "zarr.json").write_text(json.dumps(group), encoding="utf-8")
    assert read_output_shape(tmp_path, "demo") == (100, 64, 256, 256)


def test_path_zero_need_not_be_first_entry(tmp_path):
    root = write_metadata(tmp_path, "demo")
    group = json.loads((root / "zarr.json").read_text(encoding="utf-8"))
    group["attributes"]["multiscales"] = [entry(["1"]), entry(["0"])]
    (root / "zarr.json").write_text(json.dumps(group), encoding="utf-8")
    assert read_output_shape(tmp_path, "demo") == (100, 64, 256, 256)


def test_read_output_shape_missing_path_zero(tmp_path):
    root = write_metadata(tmp_path, "demo")
    group = json.loads((root / "zarr.json").read_text(encoding="utf-8"))
    group["attributes"]["multiscales"] = [entry(["2"])]
    (root / "zarr.json").write_text(json.dumps(group), encoding="utf-8")
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_read_output_shape_empty_datasets_list(tmp_path):
    root = write_metadata(tmp_path, "demo")
    group = json.loads((root / "zarr.json").read_text(encoding="utf-8"))
    group["attributes"]["multiscales"] = [{"axes": TZYX, "datasets": []}]
    (root / "zarr.json").write_text(json.dumps(group), encoding="utf-8")
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_read_output_shape_numeric_path_value_rejected(tmp_path):
    root = write_metadata(tmp_path, "demo")
    group = json.loads((root / "zarr.json").read_text(encoding="utf-8"))
    group["attributes"]["multiscales"] = [
        {"axes": TZYX, "datasets": [{"path": 0}]}
    ]
    (root / "zarr.json").write_text(json.dumps(group), encoding="utf-8")
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_read_output_shape_empty_string_path_rejected(tmp_path):
    root = write_metadata(tmp_path, "demo")
    group = json.loads((root / "zarr.json").read_text(encoding="utf-8"))
    group["attributes"]["multiscales"] = [
        {"axes": TZYX, "datasets": [{"path": ""}]}
    ]
    (root / "zarr.json").write_text(json.dumps(group), encoding="utf-8")
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


# ------------------------------------------------------------- coordinate bounds


@pytest.mark.parametrize(
    ("axis", "value", "expected"),
    [
        ("z", -3.4, 0),
        ("z", 63.6, 63),
        ("y", -0.5, 0),
        ("y", 255.4, 255),
        ("x", 256.0, 255),
        ("x", 255.0, 255),
    ],
)
def test_axis_limits_are_separate(axis, value, expected):
    report = report_for()
    row = bounded_output_node(node_row(**{axis: value}), "demo", 0, SHAPE, report)
    assert row[axis] == expected
    assert report["axis_counts"][axis] == (1 if expected != round(value) else 0)


@pytest.mark.parametrize(
    ("value", "expected", "corrected"),
    [(4.49, 4, 0), (4.5, 4, 0), (4.5001, 4, 1)],
)
def test_upper_rounding_ties_to_even_dim_five(value, expected, corrected):
    shape = (10, 5, 5, 5)
    report = new_output_bounds_report("tiny", shape)
    row = bounded_output_node(
        node_row(z=value, y=value, x=value), "tiny", 0, shape, report
    )
    assert row["z"] == row["y"] == row["x"] == expected
    assert report["corrected_nodes"] == corrected
    assert report["axis_counts"] == {"z": corrected, "y": corrected, "x": corrected}
    assert report["node_count"] == 1
    assert len(report["samples"]) == 3 * corrected
    if corrected:
        assert report["max_absolute_correction"] == 1
        assert [s["rounded_int"] for s in report["samples"]] == [5, 5, 5]
        assert [s["clipped_int"] for s in report["samples"]] == [4, 4, 4]
        assert [s["signed_delta"] for s in report["samples"]] == [-1, -1, -1]
    else:
        assert report["samples"] == []
        assert report["max_absolute_correction"] == 0


def test_negative_finite_noncubic_and_dim_one():
    shape = (4, 1, 30, 500)
    report = new_output_bounds_report("nc", shape)
    row = bounded_output_node(
        node_row(t=2, z=-9.75, y=-1.0, x=499.9), "nc", 5, shape, report
    )
    assert (row["z"], row["y"], row["x"]) == (0, 0, 499)
    assert report["axis_counts"] == {"z": 1, "y": 1, "x": 1}
    assert report["corrected_nodes"] == 1
    assert report["max_absolute_correction"] == 10
    assert [s["rounded_int"] for s in report["samples"]] == [-10, -1, 500]
    assert [s["clipped_int"] for s in report["samples"]] == [0, 0, 499]
    assert [s["signed_delta"] for s in report["samples"]] == [10, 1, -1]


def test_valid_fractional_input_is_not_a_correction():
    report = report_for()
    before = copy.deepcopy(report)
    node = node_row(z=5.2, y=200.7, x=12.5)
    row = bounded_output_node(node, "demo", 3, SHAPE, report)
    assert row == {
        "id": 3,
        "dataset": "demo",
        "row_type": "node",
        "node_id": 1,
        "t": 1,
        "z": 5,
        "y": 201,
        "x": 12,
        "source_id": -1,
        "target_id": -1,
    }
    assert list(row) == [
        "id",
        "dataset",
        "row_type",
        "node_id",
        "t",
        "z",
        "y",
        "x",
        "source_id",
        "target_id",
    ]
    assert report["corrected_nodes"] == 0
    assert report["axis_counts"] == {"z": 0, "y": 0, "x": 0}
    assert report["max_absolute_correction"] == 0
    assert report["samples"] == []
    assert report["node_count"] == before["node_count"] + 1


def test_inputs_not_mutated_and_sentinels_forced():
    node = node_row(z=300.0, source_id=99, target_id=42)
    snapshot = copy.deepcopy(node)
    shape_snapshot = list(SHAPE)
    report = report_for()
    bounded_output_node(node, "demo", 0, SHAPE, report)
    assert node == snapshot
    assert list(shape_snapshot) == list(SHAPE)


def test_missing_edge_keys_still_sentinel():
    node = {"node_id": 2, "t": 0, "z": 1.0, "y": 1.0, "x": 1.0}
    row = bounded_output_node(node, "demo", 0, SHAPE, report_for())
    assert row["source_id"] == -1 and row["target_id"] == -1


@pytest.mark.parametrize(
    "bad", [float("nan"), math.inf, -math.inf, True, False, "5.0", None]
)
def test_reject_bad_coordinates(bad):
    report = report_for()
    before = copy.deepcopy(report)
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(y=bad), "demo", 0, SHAPE, report)
    assert report == before


@pytest.mark.parametrize("bad", [1.5, True, "7", -1, 2**63, -(2**63)])
def test_reject_bad_ids(bad):
    report = report_for()
    before = copy.deepcopy(report)
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(node_id=bad), "demo", 0, SHAPE, report)
    assert report == before


@pytest.mark.parametrize("bad", [1.5, True, "7", -1, 2**63])
def test_reject_bad_row_ids(bad):
    report = report_for()
    before = copy.deepcopy(report)
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(), "demo", bad, SHAPE, report)
    assert report == before


@pytest.mark.parametrize("bad", [1.5, True, "7", -1, 2**63])
def test_reject_bad_time_ids(bad):
    report = report_for()
    before = copy.deepcopy(report)
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(t=bad), "demo", 0, SHAPE, report)
    assert report == before


def test_signed64_boundaries_accepted_and_overflow_rejected():
    limit = 2**63 - 1
    report = report_for()
    row = bounded_output_node(node_row(node_id=limit), "demo", limit, SHAPE, report)
    assert row["node_id"] == limit and row["id"] == limit
    assert type(row["node_id"]) is int and type(row["id"]) is int
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(node_id=limit + 1), "demo", 0, SHAPE, report)
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(), "demo", limit + 1, SHAPE, report)


def test_high_precision_reals_are_not_lossy():
    report = report_for()
    exact_odd = Fraction(9007199254740993, 1)
    row = bounded_output_node(node_row(node_id=exact_odd), "demo", 0, SHAPE, report)
    assert row["node_id"] == 9007199254740993
    assert type(row["node_id"]) is int

    half = Fraction(18014398509481985, 2)
    before = copy.deepcopy(report)
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(node_id=half), "demo", 0, SHAPE, report)
    assert report == before

    with pytest.raises(OutputBoundsError):
        bounded_output_node(
            node_row(node_id=Fraction(2**63, 1)), "demo", 0, SHAPE, report
        )
    assert report == before


def test_numpy_integral_and_real_inputs_work():
    report = report_for()
    node = {
        "node_id": np.int64(9),
        "t": np.int64(2),
        "z": np.float64(4.0),
        "y": np.float64(260.0),
        "x": np.float64(3.5),
    }
    row = bounded_output_node(node, "demo", np.int64(11), SHAPE, report)
    assert row["node_id"] == 9 and row["id"] == 11 and row["t"] == 2
    assert row["y"] == 255 and row["x"] == 4
    assert all(type(row[key]) is int for key in ("id", "node_id", "t", "z", "y", "x"))
    assert report["axis_counts"] == {"z": 0, "y": 1, "x": 0}


@pytest.mark.parametrize("t", [-1, 100, 101])
def test_time_outside_range_rejected(t):
    report = report_for()
    before = copy.deepcopy(report)
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(t=t), "demo", 0, SHAPE, report)
    assert report == before


# ------------------------------------------------------------------- reporting


def test_multi_axis_node_counted_once_with_signed_deltas():
    report = report_for()
    row = bounded_output_node(
        node_row(z=-2.0, y=300.0, x=999.0), "demo", 4, SHAPE, report
    )
    assert row == {
        "id": 4,
        "dataset": "demo",
        "row_type": "node",
        "node_id": 1,
        "t": 1,
        "z": 0,
        "y": 255,
        "x": 255,
        "source_id": -1,
        "target_id": -1,
    }
    assert report["corrected_nodes"] == 1
    assert report["axis_counts"] == {"z": 1, "y": 1, "x": 1}
    assert report["max_absolute_correction"] == 744
    assert [sample["axis"] for sample in report["samples"]] == ["z", "y", "x"]
    assert [s["signed_delta"] for s in report["samples"]] == [2, -45, -744]
    assert [s["absolute_delta"] for s in report["samples"]] == [2, 45, 744]
    assert report["samples"][0]["original_float"] == -2.0
    assert report["samples"][0]["rounded_int"] == -2
    assert report["samples"][0]["clipped_int"] == 0
    assert json.dumps(report)


def test_twelve_single_axis_corrections_are_not_truncated():
    report = report_for()
    for index in range(12):
        bounded_output_node(
            node_row(node_id=index, x=300.0 + index), "demo", index, SHAPE, report
        )
    assert report["node_count"] == 12
    assert report["corrected_nodes"] == 12
    assert report["axis_counts"] == {"z": 0, "y": 0, "x": 12}
    assert len(report["samples"]) == 12
    assert report["samples_truncated"] is False
    assert report["max_absolute_correction"] == 56
    assert [s["row_id"] for s in report["samples"]] == list(range(12))
    assert [s["node_id"] for s in report["samples"]] == list(range(12))
    assert [s["original_float"] for s in report["samples"]] == [
        300.0 + i for i in range(12)
    ]
    assert [s["signed_delta"] for s in report["samples"]] == [
        -(45 + i) for i in range(12)
    ]
    assert json.dumps(report)


def test_more_than_twenty_corrections_truncate_samples_only():
    report = report_for()
    for index in range(25):
        bounded_output_node(
            node_row(node_id=index, x=300.0 + index), "demo", index, SHAPE, report
        )
    assert report["node_count"] == 25
    assert report["corrected_nodes"] == 25
    assert report["axis_counts"]["x"] == 25
    assert report["samples_truncated"] is True
    assert len(report["samples"]) == 20
    assert report["max_absolute_correction"] == 69
    assert [s["row_id"] for s in report["samples"]] == list(range(20))


def test_truncation_keeps_deterministic_first_twenty_order():
    def build():
        rep = report_for()
        for index in range(25):
            bounded_output_node(
                node_row(node_id=index, x=300.0 + index), "demo", index, SHAPE, rep
            )
        return rep

    assert [s["row_id"] for s in build()["samples"]] == list(range(20))
    assert [s["axis"] for s in build()["samples"]] == ["x"] * 20


def test_sample_order_is_invocation_then_z_y_x():
    report = report_for()
    bounded_output_node(
        node_row(node_id=1, z=-1.0, y=300.0, x=5.0), "demo", 0, SHAPE, report
    )
    bounded_output_node(
        node_row(node_id=2, z=5.0, y=-1.0, x=300.0), "demo", 1, SHAPE, report
    )
    assert [(s["row_id"], s["axis"]) for s in report["samples"]] == [
        (0, "z"),
        (0, "y"),
        (1, "y"),
        (1, "x"),
    ]


def test_last_axis_failure_leaves_report_untouched():
    report = report_for()
    report["node_count"] = 5
    before = copy.deepcopy(report)
    bad = {"node_id": 1, "t": 1, "z": 300.0, "y": 300.0, "x": "bad"}
    with pytest.raises(OutputBoundsError):
        bounded_output_node(bad, "demo", 0, SHAPE, report)
    assert report == before


def test_id_failure_after_coordinate_correction_leaves_report_untouched():
    report = report_for()
    before = copy.deepcopy(report)
    bad = {"node_id": 1, "t": 1, "z": 300.0, "y": 5.0, "x": 5.0}
    with pytest.raises(OutputBoundsError):
        bounded_output_node(bad, "demo", 2**63, SHAPE, report)
    assert report == before


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.__setitem__("dataset", "other"),
        lambda r: r.__setitem__("shape", [100, 64, 256, 128]),
        lambda r: r.__setitem__("node_count", -1),
        lambda r: r.__setitem__("node_count", 1.5),
        lambda r: r.__setitem__("corrected_nodes", -1),
        lambda r: r.__setitem__("axis_counts", {"z": 0, "y": 0}),
        lambda r: r.__setitem__(
            "axis_counts", {"z": 0, "y": 0, "x": 0, "t": 0}
        ),
        lambda r: r.__setitem__("max_absolute_correction", 1.5),
        lambda r: r.__setitem__("samples", "corrupt"),
        lambda r: r.__setitem__("samples_truncated", "yes"),
        lambda r: r.__setitem__("sample_limit", 40),
        lambda r: r.pop("samples_truncated"),
        lambda r: r.__setitem__("extra", 1),
    ],
)
def test_corrupted_reports_rejected_without_mutation(mutate):
    report = report_for()
    mutate(report)
    before = copy.deepcopy(report)
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(x=300.0), "demo", 0, SHAPE, report)
    assert report == before


def test_reports_with_samples_are_validated():
    report = report_for()
    bounded_output_node(node_row(x=300.0), "demo", 0, SHAPE, report)
    good = copy.deepcopy(report)
    assert bounded_output_node(node_row(x=301.0), "demo", 1, SHAPE, report)["x"] == 255
    assert report["node_count"] == 2

    # Mutate absolute_delta to a value that actually differs from the fixture.
    # The original sample has absolute_delta=45; setting 45 would be a no-op.
    broken_abs = copy.deepcopy(good)
    original_abs = broken_abs["samples"][0]["absolute_delta"]
    broken_abs["samples"][0]["absolute_delta"] = 44
    assert broken_abs["samples"][0]["absolute_delta"] != original_abs
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(), "demo", 9, SHAPE, broken_abs)

    for field, value in [
        ("rounded_int", 299),
        ("clipped_int", 254),
    ]:
        broken = copy.deepcopy(good)
        original_val = broken["samples"][0][field]
        broken["samples"][0][field] = value
        assert broken["samples"][0][field] != original_val
        with pytest.raises(OutputBoundsError):
            bounded_output_node(node_row(), "demo", 9, SHAPE, broken)

    truncated = copy.deepcopy(good)
    assert not truncated["samples_truncated"]
    truncated["samples_truncated"] = True
    assert truncated["samples_truncated"] != good["samples_truncated"]
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(), "demo", 9, SHAPE, truncated)

    over_max = copy.deepcopy(good)
    original_max = over_max["max_absolute_correction"]
    over_max["max_absolute_correction"] = 0
    assert over_max["max_absolute_correction"] != original_max
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(), "demo", 9, SHAPE, over_max)

    bad_sample = copy.deepcopy(good)
    bad_sample["samples"] = [{}]
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(), "demo", 9, SHAPE, bad_sample)

    nan_sample = copy.deepcopy(good)
    nan_sample["samples"][0]["original_float"] = float("nan")
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(), "demo", 9, SHAPE, nan_sample)

    other_dataset = copy.deepcopy(good)
    other_dataset["samples"][0]["dataset"] = "elsewhere"
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(), "demo", 9, SHAPE, other_dataset)


def test_invalid_shape_and_dataset_mismatch_rejected():
    report = report_for()
    before = copy.deepcopy(report)
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(), "demo", 0, (0, 64, 256, 256), report)
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(), "other", 0, SHAPE, report)
    assert report == before
    with pytest.raises(OutputBoundsError):
        new_output_bounds_report("demo", (100, 64, 256, -1))


@pytest.mark.parametrize(
    "bad",
    [(100, 64, 256), (100, 64.0, 256, 256), (100, True, 256, 256)],
)
def test_new_report_requires_positive_python_int_dims(bad):
    with pytest.raises(OutputBoundsError):
        new_output_bounds_report("demo", bad)


def test_zero_correction_report_is_visible_and_serializable():
    report = report_for()
    bounded_output_node(node_row(), "demo", 0, SHAPE, report)
    assert report["node_count"] == 1
    assert report["corrected_nodes"] == 0
    assert json.dumps(report)


def test_no_future_import_in_helper():
    import biohub.output_bounds as module

    source = inspect.getsource(module)
    assert "__future__" not in source


def test_fresh_report_with_no_samples_passes_validation():
    report = report_for()
    bounded_output_node(node_row(), "demo", 0, SHAPE, report)
    again = copy.deepcopy(report)
    bounded_output_node(node_row(), "demo", 1, SHAPE, again)
    assert again["node_count"] == 2
    assert again["samples"] == []


def test_existing_sample_absolute_delta_preserved():
    report = report_for()
    bounded_output_node(node_row(x=300.0), "demo", 0, SHAPE, report)
    snapshot = copy.deepcopy(report)
    bounded_output_node(node_row(x=301.0), "demo", 1, SHAPE, report)
    assert report["samples"][0]["absolute_delta"] == snapshot["samples"][0]["absolute_delta"]


def test_truncated_fixture_accepts_max_greater_than_visible():
    report = report_for()
    for index in range(25):
        bounded_output_node(
            node_row(node_id=index, x=300.0 + index), "demo", index, SHAPE, report
        )
    visible_max = max(s["absolute_delta"] for s in report["samples"])
    assert report["max_absolute_correction"] >= visible_max
    assert report["max_absolute_correction"] == 69
    assert report["samples_truncated"] is True


def test_sample_fraction_original_float_rejected():
    report = report_for()
    bounded_output_node(node_row(x=300.0), "demo", 0, SHAPE, report)
    broken = copy.deepcopy(report)
    broken["samples"][0]["original_float"] = Fraction(300, 1)
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(), "demo", 1, SHAPE, broken)


def test_sample_rounded_inconsistent_with_original_rejected():
    report = report_for()
    bounded_output_node(node_row(x=300.0), "demo", 0, SHAPE, report)
    broken = copy.deepcopy(report)
    broken["samples"][0]["rounded_int"] = 299
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(), "demo", 1, SHAPE, broken)


def test_complete_samples_missing_when_corrected_rejected():
    report = report_for()
    bounded_output_node(node_row(x=300.0), "demo", 0, SHAPE, report)
    broken = copy.deepcopy(report)
    broken["samples"] = []
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(), "demo", 1, SHAPE, broken)


def test_axis_counts_exceeding_per_call_maximum_rejected():
    report = report_for()
    bounded_output_node(node_row(x=300.0), "demo", 0, SHAPE, report)
    broken = copy.deepcopy(report)
    broken["axis_counts"]["x"] = 5
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(), "demo", 1, SHAPE, broken)


def test_corrected_nodes_exceeding_node_count_rejected():
    report = report_for()
    bounded_output_node(node_row(x=300.0), "demo", 0, SHAPE, report)
    broken = copy.deepcopy(report)
    broken["corrected_nodes"] = 5
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(), "demo", 1, SHAPE, broken)


def test_untruncated_max_must_match_visible_max():
    report = report_for()
    bounded_output_node(node_row(x=300.0), "demo", 0, SHAPE, report)
    broken = copy.deepcopy(report)
    broken["max_absolute_correction"] = 999
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(), "demo", 1, SHAPE, broken)


def test_repeated_row_node_ids_still_count_per_call():
    report = report_for()
    for _ in range(3):
        bounded_output_node(node_row(x=300.0), "demo", 0, SHAPE, report)
    assert report["node_count"] == 3
    assert report["corrected_nodes"] == 3
    assert report["axis_counts"]["x"] == 3
    assert len(report["samples"]) == 3


# ------------------------------------------------------- endpoint overshoot demo


def ols_slope_intercept(points):
    n = len(points)
    sx = sum(t for t, _ in points)
    sy = sum(v for _, v in points)
    sxx = sum(t * t for t, _ in points)
    sxy = sum(t * v for t, v in points)
    slope = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    intercept = (sy - slope * sx) / n
    return slope, intercept


def test_endpoint_overshoot_needs_final_bounds():
    """OLS fit evaluated at the LAST in-bounds time still overshoots dim-1."""
    dims = (20, 5, 10, 10)
    pts = [(0.0, 0.0), (1.0, 4.0), (2.0, 4.0)]
    slope, intercept = ols_slope_intercept(pts)
    raw_end = slope * 2.0 + intercept
    assert raw_end == pytest.approx(14.0 / 3.0)
    assert raw_end > dims[1] - 1

    report = new_output_bounds_report("ols", dims)
    row = bounded_output_node(
        {"node_id": 1, "t": 2, "z": raw_end, "y": 1.0, "x": 1.0},
        "ols",
        0,
        dims,
        report,
    )
    assert row["z"] == dims[1] - 1
    assert report["corrected_nodes"] == 1
    assert report["axis_counts"] == {"z": 1, "y": 0, "x": 0}
    assert report["max_absolute_correction"] == 1
    assert report["samples"][0]["rounded_int"] == 5
    assert report["samples"][0]["clipped_int"] == 4
    assert report["samples"][0]["signed_delta"] == -1
