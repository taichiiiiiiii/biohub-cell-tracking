"""Bounds-correcting serializer for Biohub output node rows.

This module repairs missing *upper* coordinate bounds only. Graph/topology,
row order, node/time/row IDs, sentinels and model settings are preserved.
Rounding is Python's built-in ``round`` (ties-to-even). No dataset IDs, node
IDs or image dimensions are hardcoded in runtime logic.
"""

import json
from fractions import Fraction
from numbers import Integral, Real
from pathlib import Path

CSV_NODE_FIELDS = (
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
)

CSV_SAMPLE_FIELDS = (
    "dataset",
    "row_id",
    "node_id",
    "t",
    "axis",
    "original_float",
    "rounded_int",
    "clipped_int",
    "signed_delta",
    "absolute_delta",
)

REPORT_FIELDS = (
    "dataset",
    "shape",
    "node_count",
    "corrected_nodes",
    "axis_counts",
    "max_absolute_correction",
    "samples",
    "sample_limit",
    "samples_truncated",
)

AXIS_ORDER = ("T", "Z", "Y", "X")
COORD_AXES = ("z", "y", "x")
DIM_INDEX = {"z": 1, "y": 2, "x": 3}

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1

SAMPLE_LIMIT = 20


class OutputBoundsError(ValueError):
    """Raised when metadata, a node row or a report fails validation."""


def _is_python_int(value: object) -> bool:
    """True only for a genuine Python ``int`` (bool excluded)."""
    return type(value) is int


def _validate_rank4_shape_input(shape: object) -> tuple[int, int, int, int]:
    """Validate shape input before any coercion.

    Rejects None, scalars, strings, generators and other non-sequence types
    directly with OutputBoundsError. Only list/tuple of length 4 with positive
    Python ints is accepted.
    """
    if isinstance(shape, (str, bytes)):
        raise OutputBoundsError("array shape must be a rank-4 sequence")
    if not isinstance(shape, (list, tuple)):
        raise OutputBoundsError("array shape must be a rank-4 sequence")
    if len(shape) != 4:
        raise OutputBoundsError("array shape must be a rank-4 sequence")
    dims: list[int] = []
    for axis, value in zip(AXIS_ORDER, shape, strict=True):
        if not _is_python_int(value):
            raise OutputBoundsError(f"{axis} dimension is not a Python int")
        if value <= 0:
            raise OutputBoundsError(f"{axis} dimension must be positive")
        dims.append(value)
    return dims[0], dims[1], dims[2], dims[3]


def _positive_rank4_shape(shape: object) -> tuple[int, int, int, int]:
    """Validate a rank-4 sequence of positive Python ints.

    Accepts only list or tuple; used for already-extracted shape values from
    JSON metadata where the container type is known to be safe.
    """
    if not isinstance(shape, (list, tuple)) or len(shape) != 4:
        raise OutputBoundsError("array shape must be a rank-4 sequence")
    dims: list[int] = []
    for axis, value in zip(AXIS_ORDER, shape, strict=True):
        if not _is_python_int(value):
            raise OutputBoundsError(f"{axis} dimension is not a Python int")
        if value <= 0:
            raise OutputBoundsError(f"{axis} dimension must be positive")
        dims.append(value)
    return dims[0], dims[1], dims[2], dims[3]


def _multiscales_entry_paths(entry: object) -> list[str]:
    """Return the raw ``datasets[*]["path"]`` list for a multiscales entry."""
    if not isinstance(entry, dict):
        raise OutputBoundsError("multiscales entries must be JSON objects")
    datasets = entry.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise OutputBoundsError(
            "multiscales entries require a non-empty datasets list"
        )
    paths: list[str] = []
    for item in datasets:
        if not isinstance(item, dict) or "path" not in item:
            raise OutputBoundsError(
                "multiscales dataset entries require a path"
            )
        path = item["path"]
        if not isinstance(path, str) or not path:
            raise OutputBoundsError(
                "multiscales dataset path must be a non-empty string"
            )
        paths.append(path)
    return paths


def _entry_axes_are_tzyx(entry: dict) -> bool:
    """True when the entry declares exactly T, Z, Y, X axes in that order."""
    axes = entry.get("axes")
    if not isinstance(axes, list) or len(axes) != 4:
        return False
    names: list[str] = []
    for axis in axes:
        if not isinstance(axis, dict):
            return False
        name = axis.get("name")
        if not isinstance(name, str) or not name:
            return False
        names.append(name.upper())
    return names == list(AXIS_ORDER)


def _validate_multiscales_axes(multiscales: list, dataset: str) -> None:
    """Every multiscales entry must carry a non-empty axes list of dicts."""
    for index, entry in enumerate(multiscales):
        if not isinstance(entry, dict):
            raise OutputBoundsError(
                f"multiscales[{index}] must be a JSON object for {dataset}"
            )
        axes = entry.get("axes")
        if not isinstance(axes, list) or not axes:
            raise OutputBoundsError(
                f"multiscales[{index}] requires a non-empty axes list "
                f"for {dataset}"
            )
        for axis_index, axis in enumerate(axes):
            if not isinstance(axis, dict):
                raise OutputBoundsError(
                    f"multiscales[{index}].axes[{axis_index}] must be a "
                    f"JSON object for {dataset}"
                )
            name = axis.get("name")
            if not isinstance(name, str) or not name:
                raise OutputBoundsError(
                    f"multiscales[{index}].axes[{axis_index}] requires a "
                    f"non-empty name for {dataset}"
                )


def read_output_shape(
    test_dir: str | Path, dataset: str
) -> tuple[int, int, int, int]:
    """Return ``(T, Z, Y, X)`` for ``dataset`` from Zarr format-3 metadata.

    Reads ``<dataset>.zarr/zarr.json`` and ``<dataset>.zarr/0/zarr.json``. No
    shape fallback and no image-array reads are performed. Exactly one
    reference to the literal path ``"0"`` is required across *all* multiscales
    entries, counted before any axis filtering. Every multiscales entry must
    declare a non-empty axes list; only the selected path-0 entry is required
    to match the normalized T,Z,Y,X ordering.
    """
    if not isinstance(dataset, str) or not dataset.strip():
        raise OutputBoundsError("dataset must be a non-empty string")
    root = Path(test_dir) / f"{dataset}.zarr"

    try:
        group_meta = json.loads((root / "zarr.json").read_text(encoding="utf-8"))
        array_meta = json.loads(
            (root / "0" / "zarr.json").read_text(encoding="utf-8")
        )
    except OSError as exc:
        raise OutputBoundsError(
            f"missing zarr metadata for {dataset}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise OutputBoundsError(
            f"malformed zarr metadata for {dataset}: {exc}"
        ) from exc
    except UnicodeDecodeError as exc:
        raise OutputBoundsError(
            f"malformed zarr metadata encoding for {dataset}: {exc}"
        ) from exc

    if not isinstance(group_meta, dict) or not isinstance(array_meta, dict):
        raise OutputBoundsError("zarr metadata must be JSON objects")

    group_version = group_meta.get("zarr_format")
    array_version = array_meta.get("zarr_format")
    if not _is_python_int(group_version) or group_version != 3:
        raise OutputBoundsError("only zarr format 3 metadata is supported")
    if not _is_python_int(array_version) or array_version != 3:
        raise OutputBoundsError("only zarr format 3 metadata is supported")
    if group_meta.get("node_type") != "group":
        raise OutputBoundsError("root metadata node_type must be 'group'")
    if array_meta.get("node_type") != "array":
        raise OutputBoundsError("child metadata node_type must be 'array'")

    attributes = group_meta.get("attributes")
    if not isinstance(attributes, dict):
        raise OutputBoundsError("root metadata is missing attributes")
    multiscales = attributes.get("multiscales")
    if not isinstance(multiscales, list):
        raise OutputBoundsError(
            "root metadata is missing multiscales attributes"
        )

    _validate_multiscales_axes(multiscales, dataset)

    path_zero_total = 0
    for entry in multiscales:
        paths = _multiscales_entry_paths(entry)
        path_zero_total += sum(1 for path in paths if path == "0")
    if path_zero_total == 0:
        raise OutputBoundsError(
            f"no multiscales entry references dataset path '0' for {dataset}"
        )
    if path_zero_total > 1:
        raise OutputBoundsError(
            f"ambiguous duplicate path '0' references for {dataset}"
        )

    matching = [
        entry
        for entry in multiscales
        if any(path == "0" for path in _multiscales_entry_paths(entry))
    ]
    if len(matching) != 1:
        raise OutputBoundsError(
            "expected exactly one multiscales entry referencing path '0' "
            f"for {dataset}"
        )

    entry = matching[0]
    if not _entry_axes_are_tzyx(entry):
        raise OutputBoundsError(
            "multiscales entry for path '0' must declare T,Z,Y,X axes "
            f"for {dataset}"
        )

    return _positive_rank4_shape(array_meta.get("shape"))


def new_output_bounds_report(
    dataset: str, shape: tuple[int, int, int, int]
) -> dict:
    """Build a fresh, JSON-serializable, mutable bounds-correction report."""
    if not isinstance(dataset, str) or not dataset.strip():
        raise OutputBoundsError("dataset must be a non-empty string")
    if type(dataset) is not str:
        raise OutputBoundsError("dataset must be a builtin str")
    t_dim, z_dim, y_dim, x_dim = _validate_rank4_shape_input(shape)
    return {
        "dataset": dataset,
        "shape": [t_dim, z_dim, y_dim, x_dim],
        "node_count": 0,
        "corrected_nodes": 0,
        "axis_counts": {"z": 0, "y": 0, "x": 0},
        "max_absolute_correction": 0,
        "samples": [],
        "sample_limit": SAMPLE_LIMIT,
        "samples_truncated": False,
    }


def _validate_sample(
    sample: object,
    index: int,
    dataset: str,
    shape: tuple[int, int, int, int],
) -> None:
    """Validate a single sample entry against the schema and dataset."""
    if not isinstance(sample, dict):
        raise OutputBoundsError(f"report samples[{index}] must be a dict")
    if set(sample) != set(CSV_SAMPLE_FIELDS):
        raise OutputBoundsError(
            f"report samples[{index}] fields do not match the sample schema"
        )
    if type(sample["dataset"]) is not str or sample["dataset"] != dataset:
        raise OutputBoundsError(f"report samples[{index}] dataset mismatch")
    if type(sample["axis"]) is not str or sample["axis"] not in COORD_AXES:
        raise OutputBoundsError(f"report samples[{index}] axis is invalid")
    for key in (
        "row_id",
        "node_id",
        "t",
        "rounded_int",
        "clipped_int",
        "signed_delta",
        "absolute_delta",
    ):
        if not _is_python_int(sample[key]):
            raise OutputBoundsError(
                f"report samples[{index}] {key} must be a Python int"
            )
    if sample["row_id"] < 0 or sample["row_id"] > INT64_MAX:
        raise OutputBoundsError(
            f"report samples[{index}] row_id exceeds int64 range"
        )
    if sample["node_id"] < 0 or sample["node_id"] > INT64_MAX:
        raise OutputBoundsError(
            f"report samples[{index}] node_id exceeds int64 range"
        )
    if sample["t"] < 0 or sample["t"] > INT64_MAX:
        raise OutputBoundsError(
            f"report samples[{index}] t exceeds int64 range"
        )
    if sample["t"] >= shape[0]:
        raise OutputBoundsError(
            f"report samples[{index}] t exceeds T dimension"
        )
    original = sample["original_float"]
    if isinstance(original, bool) or type(original) is not float:
        raise OutputBoundsError(
            f"report samples[{index}] original_float must be a Python float"
        )
    if original != original or original in (float("inf"), float("-inf")):
        raise OutputBoundsError(
            f"report samples[{index}] original_float must be finite"
        )
    rounded = sample["rounded_int"]
    clipped = sample["clipped_int"]
    signed = sample["signed_delta"]
    absolute = sample["absolute_delta"]
    if round(original) != rounded:
        raise OutputBoundsError(
            f"report samples[{index}] rounded_int inconsistent with original"
        )
    dim_size = shape[DIM_INDEX[sample["axis"]]]
    expected_clipped = min(max(rounded, 0), dim_size - 1)
    if clipped != expected_clipped:
        raise OutputBoundsError(
            f"report samples[{index}] clipped_int inconsistent with shape"
        )
    if signed != clipped - rounded:
        raise OutputBoundsError(
            f"report samples[{index}] signed_delta is inconsistent"
        )
    if absolute != abs(signed):
        raise OutputBoundsError(
            f"report samples[{index}] absolute_delta is inconsistent"
        )
    if absolute == 0:
        raise OutputBoundsError(
            f"report samples[{index}] records a non-correction"
        )
    if rounded == clipped:
        raise OutputBoundsError(
            f"report samples[{index}] rounded equals clipped"
        )


def _validate_report(
    report: object, dataset: str, shape: tuple[int, int, int, int]
) -> None:
    """Fail closed on any malformed report without mutating it."""
    if not isinstance(report, dict):
        raise OutputBoundsError("report must be a dict")
    if set(report) != set(REPORT_FIELDS):
        raise OutputBoundsError(
            "report fields do not match the report schema"
        )
    if type(report["dataset"]) is not str or report["dataset"] != dataset:
        raise OutputBoundsError("report dataset identity mismatch")
    report_shape = report["shape"]
    if not isinstance(report_shape, list):
        raise OutputBoundsError("report shape must be a JSON list")
    if _positive_rank4_shape(report_shape) != tuple(shape):
        raise OutputBoundsError("report shape mismatch")
    for key in ("node_count", "corrected_nodes", "max_absolute_correction"):
        value = report[key]
        if not _is_python_int(value) or value < 0:
            raise OutputBoundsError(f"report {key} is invalid")
    counts = report["axis_counts"]
    if not isinstance(counts, dict) or set(counts) != set(COORD_AXES):
        raise OutputBoundsError(
            "report axis_counts must cover z, y and x"
        )
    for axis in COORD_AXES:
        if not _is_python_int(counts[axis]) or counts[axis] < 0:
            raise OutputBoundsError(
                f"report axis_counts[{axis!r}] is invalid"
            )
    if (
        not _is_python_int(report["sample_limit"])
        or report["sample_limit"] != SAMPLE_LIMIT
    ):
        raise OutputBoundsError("report sample_limit is invalid")
    if not isinstance(report["samples_truncated"], bool):
        raise OutputBoundsError(
            "report samples_truncated must be a bool"
        )
    samples = report["samples"]
    if not isinstance(samples, list) or len(samples) > SAMPLE_LIMIT:
        raise OutputBoundsError(
            "report samples must be a list bounded by the sample limit"
        )
    for index, sample in enumerate(samples):
        _validate_sample(sample, index, dataset, shape)
    corrected = report["corrected_nodes"]
    node_count = report["node_count"]
    axis_total = sum(counts[axis] for axis in COORD_AXES)
    if corrected > node_count:
        raise OutputBoundsError(
            "report corrected_nodes exceeds node_count"
        )
    for axis in COORD_AXES:
        if counts[axis] > corrected:
            raise OutputBoundsError(
                f"report axis_counts[{axis!r}] exceeds corrected_nodes"
            )
    if axis_total < corrected:
        raise OutputBoundsError(
            "report axis_counts are inconsistent with corrected_nodes"
        )
    if axis_total > 3 * corrected:
        raise OutputBoundsError(
            "report axis_counts exceed per-call maximum"
        )
    if corrected == 0:
        if axis_total != 0:
            raise OutputBoundsError(
                "report axis_counts must be zero when no corrections"
            )
        if report["max_absolute_correction"] != 0:
            raise OutputBoundsError(
                "report max must be zero when no corrections"
            )
        if samples:
            raise OutputBoundsError(
                "report samples must be empty when no corrections"
            )
        if report["samples_truncated"]:
            raise OutputBoundsError(
                "report cannot be truncated without corrections"
            )
    visible_axis_counts = {"z": 0, "y": 0, "x": 0}
    visible_max = 0
    visible_identities: set[tuple[int, int, int]] = set()
    for sample in samples:
        visible_axis_counts[sample["axis"]] += 1
        visible_max = max(visible_max, sample["absolute_delta"])
        visible_identities.add(
            (sample["row_id"], sample["node_id"], sample["t"])
        )
    expected_len = min(axis_total, SAMPLE_LIMIT)
    if len(samples) != expected_len:
        raise OutputBoundsError(
            "report samples length inconsistent with axis totals"
        )
    expected_truncated = axis_total > SAMPLE_LIMIT
    if report["samples_truncated"] != expected_truncated:
        raise OutputBoundsError(
            "report samples_truncated flag is inconsistent"
        )
    for axis in COORD_AXES:
        if visible_axis_counts[axis] > counts[axis]:
            raise OutputBoundsError(
                f"report visible {axis} samples exceed axis_counts"
            )
    if report["max_absolute_correction"] < visible_max:
        raise OutputBoundsError(
            "report max_absolute_correction is below its samples"
        )
    if not report["samples_truncated"]:
        if report["max_absolute_correction"] != visible_max:
            raise OutputBoundsError(
                "untruncated report max must equal visible sample max"
            )
    if len(visible_identities) > corrected:
        raise OutputBoundsError(
            "report distinct sample identities exceed corrected_nodes"
        )


def _as_exact_int(value: object, label: str) -> int:
    """Return an exact Python int without ever routing Reals through float."""
    if isinstance(value, bool):
        raise OutputBoundsError(f"{label} must not be a bool")
    if isinstance(value, Fraction):
        if value.denominator != 1:
            raise OutputBoundsError(f"{label} must be exactly integral")
        number = int(value.numerator)
    elif isinstance(value, Integral):
        number = int(value)
    elif isinstance(value, Real):
        try:
            candidate = round(value)
        except (OverflowError, ValueError) as exc:
            raise OutputBoundsError(
                f"{label} is not a finite real number"
            ) from exc
        if value != candidate:
            raise OutputBoundsError(f"{label} must be exactly integral")
        number = int(candidate)
    else:
        raise OutputBoundsError(
            f"{label} must be a real number, not {type(value).__name__}"
        )
    if number < INT64_MIN or number > INT64_MAX:
        raise OutputBoundsError(f"{label} exceeds signed 64-bit limits")
    return number


def _coord_to_float(value: object, axis: str) -> float:
    """Convert a coordinate to a finite float, rejecting bool/str/non-finite."""
    if isinstance(value, bool):
        raise OutputBoundsError(f"coordinate {axis} must not be a bool")
    if isinstance(value, str):
        raise OutputBoundsError(f"coordinate {axis} must not be a string")
    if isinstance(value, Fraction):
        try:
            number = float(value)
        except (OverflowError, ValueError) as exc:
            raise OutputBoundsError(
                f"coordinate {axis} is not a finite real number"
            ) from exc
    elif isinstance(value, Real):
        try:
            number = float(value)
        except (OverflowError, ValueError) as exc:
            raise OutputBoundsError(
                f"coordinate {axis} is not a finite real number"
            ) from exc
    else:
        raise OutputBoundsError(
            f"coordinate {axis} must be a real number"
        )
    if number != number or number in (float("inf"), float("-inf")):
        raise OutputBoundsError(f"coordinate {axis} must be finite")
    return number


def bounded_output_node(
    node: dict,
    dataset: str,
    row_id: int,
    shape: tuple[int, int, int, int],
    report: dict,
) -> dict:
    """Return one complete, bounds-corrected node CSV row dict.

    Neither ``node`` nor ``shape`` is mutated. The report is updated only after
    the whole node validates successfully. A correction is recorded only when
    the rounded integer differs from the clipped integer.
    """
    if not isinstance(node, dict):
        raise OutputBoundsError("node must be a dict")
    if not isinstance(dataset, str) or not dataset.strip():
        raise OutputBoundsError("dataset must be a non-empty string")
    if type(dataset) is not str:
        raise OutputBoundsError("dataset must be a builtin str")
    t_dim, z_dim, y_dim, x_dim = _validate_rank4_shape_input(shape)
    _validate_report(report, dataset, (t_dim, z_dim, y_dim, x_dim))

    row = _as_exact_int(row_id, "row_id")
    if row < 0:
        raise OutputBoundsError("row_id must be non-negative")
    node_id = _as_exact_int(node.get("node_id"), "node_id")
    if node_id < 0:
        raise OutputBoundsError("node_id must be non-negative")
    t_val = _as_exact_int(node.get("t"), "t")
    if t_val < 0 or t_val > INT64_MAX:
        raise OutputBoundsError("t exceeds signed 64-bit limits")
    if t_val >= t_dim:
        raise OutputBoundsError(
            f"t={t_val} outside [0, T-1] for T={t_dim}"
        )

    dims = {"z": z_dim, "y": y_dim, "x": x_dim}
    originals: dict[str, float] = {}
    rounded: dict[str, int] = {}
    clipped: dict[str, int] = {}
    corrections: list[str] = []
    for axis in COORD_AXES:
        original = _coord_to_float(node.get(axis), axis)
        near = int(round(original))
        bound = min(max(near, 0), dims[axis] - 1)
        originals[axis] = original
        rounded[axis] = near
        clipped[axis] = bound
        if near != bound:
            corrections.append(axis)

    out = {
        "id": row,
        "dataset": dataset,
        "row_type": "node",
        "node_id": node_id,
        "t": t_val,
        "z": clipped["z"],
        "y": clipped["y"],
        "x": clipped["x"],
        "source_id": -1,
        "target_id": -1,
    }

    pending_samples: list[dict] = []
    max_delta = 0
    for axis in COORD_AXES:
        if axis not in corrections:
            continue
        signed = clipped[axis] - rounded[axis]
        absolute = abs(signed)
        max_delta = max(max_delta, absolute)
        pending_samples.append(
            {
                "dataset": dataset,
                "row_id": row,
                "node_id": node_id,
                "t": t_val,
                "axis": axis,
                "original_float": originals[axis],
                "rounded_int": rounded[axis],
                "clipped_int": clipped[axis],
                "signed_delta": signed,
                "absolute_delta": absolute,
            }
        )

    samples = report["samples"]
    room = SAMPLE_LIMIT - len(samples)
    if len(pending_samples) > room:
        report["samples_truncated"] = True
    if room > 0:
        samples.extend(pending_samples[:room])
    report["node_count"] += 1
    if corrections:
        report["corrected_nodes"] += 1
        for axis in corrections:
            report["axis_counts"][axis] += 1
        if max_delta > report["max_absolute_correction"]:
            report["max_absolute_correction"] = max_delta
    return out
