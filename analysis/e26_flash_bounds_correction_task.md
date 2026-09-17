# Qwen Cloud Flash: evidence-driven correction of the delivered bounds unit

Continue the same directly user-initiated supervised implementation workflow.
Exact qwen3.8-flash, Token Plan only, reasoning none. No tools, file access,
network, agents, fallback or API retries. Parent has NOT adopted your prior code.
Its response delivery succeeded, but real pytest found 8 failures/53 passes.
This is one explicit code-correction stage with concrete counterexamples, not
an unchanged request retry. The parent keeps the original total supervision
deadline 2026-09-06 16:54:10 UTC and will stop this stage by that deadline.
Return COMPLETE corrected helper and COMPLETE corrected tests, using exactly
the same two literal labeled Python fences below. No patch, no JSON, no prose.
Do not claim to have run tests.

Only correct the following demonstrated defects and add focused regression
tests. Preserve the original scientific scope and every valid CSV field.

1. Your coordinate loop overwrites the rounded value with the clipped value
   before comparing them, making the correction branch unreachable. Preserve
   distinct original_float, rounded_int and clipped_int, derive each correction
   from rounded_int != clipped_int, and update all telemetry correctly.
   Compute/validate the whole node and all report updates before mutating report.
   Do not fix tests merely to agree with broken telemetry.
2. Metadata: count ALL references to exact path "0" BEFORE validating the selected
   entry's axes. Exactly one reference across all entries is required.
   Duplicate path0 within one entry must reject; duplicate path0 in a wrong-axis
   or malformed entry must not be hidden by filtering entries first.
   Reject malformed metadata structures; allow other valid non-path0 entries.
   A valid multiscale dataset list with unique paths ["0","1"] is allowed, and
   path0 need not be its first dataset entry. Do not invent that ordering rule.
   Validate selected axes T,Z,Y,X; root/child dictionaries and exact Zarr3.
   Shapes must have rank4 positive Python int dimensions (type int, not bool,
   float, numpy int or string). Metadata JSON ints naturally are Python ints.
3. Exact IDs: numbers.Integral may be int-cast directly. For other numbers.Real
   never round through float to decide integrality or return ID. Compare value
   exactly to its integer candidate and preserve integers through 2**63-1.
   Parent reproduced:
   Fraction(9007199254740993,1) incorrectly returns9007199254740992;
   Fraction(18014398509481985,2) incorrectly accepts a fractional ID.
   Add those and signed64 boundary/overflow tests for node_id,row_id,t.
   Keep bool/string/nonfinite/negative rejection and 0<=t<T.
4. Report validation must reject malformed sample dictionaries such as {} or
   missing fields, wrong field types, NaN/non-JSON values, mismatched dataset
   and internally wrong correction fields. Validate the bounded <=20 samples,
   required counter structure and basic consistent aggregate state before any
   mutation. New reports are JSON serializable and every accepted update stays
   JSON serializable. No O(total_nodes) storage or unbounded scanning.
5. Correct demonstrably wrong test expectations:
   - With dim5, input4.5001 rounds5 then clips4: output4 and correction1 peraxis,
     corrected_nodes1 for a three-axis node. 4.49 and4.5 round4, no corrections.
   - shape(4,1,30,500), z=-9.75,y=-1,x=499.9 -> rounded(-10,-1,500),
     clipped(0,0,499), counts all1, corrected_nodes1, maxabsolute10.
   - Twelve calls with only x corrected produce12 samples, no truncation,
     row IDs0..11 once, max delta56 for x=300..311/dim256.
     Add a genuine >20-correction test, e.g.25 calls gives20samples,
     node_count/corrected_nodes/x_count25, truncated true, max delta69.
     Verify deterministic first20 order across calls; retain z,y,x ordering test.
6. OLS fixture should fit the ACTUAL last time among THREE in-bounds samples,
   not extrapolate to a fourth future time. Example shape spatialdim5 with
   points (0,0),(1,4),(2,4): least-squares fit at t2 is14/3 (>4), rounds5 then
   clips4. All input coordinates are valid; smoothing itself stays unchanged.
   Compute ordinary OLS clearly; no dead conditional expression.
7. Ruff line120: fix three long test lines and import ordering. Repository Ruff
   currently treats biohub as third-party (no src detection setting), so use
   numpy,pytest,biohub in one third-party import group in lexical order.
8. Keep no future import in helper; no tools/testing claims. Preserve full
   original API/schema, sentinels-1, no model/graph/hardcoded dataset changes.

Required original contract (unchanged except the stricter explicit corrections
above and the shared total supervision deadline):
# Qwen Cloud Flash: one bounds-correctness module and focused tests

The user has now explicitly selected qwen3.8-flash through the Token Plan cloud
route. This is one directly user-initiated, parent-supervised authoring task.
Maximum600seconds, retries0, fallback0. This is not automation or a continuation
of the failed Plus task. No network, tools, file reads/writes, agents or API calls.
Answer from the self-contained contract below. Do not inspect the worktree.

DELIVERY: output exactly two labeled literal Python code blocks, in this order:
HELPER
```python
<complete standalone Python module>
```
TESTS
```python
<complete pytest module>
```
No text before, between or after except the exact labels and normal blank lines.
Use real newlines and ordinary Python syntax. Do not JSON-encode or quote the
whole source, do not emit a patch, do not use any tool. The parent applies the
two literal bodies unchanged after reading all code, then runs tests and Ruff.
Never claim tests were run. No scientific completion/submission claims.

Parent-owned destinations after review:
src/biohub/output_bounds.py and tests/test_output_bounds.py.
These paths are NOT instructions to create or inspect files yourself.
Tests import biohub.output_bounds. Python3.12, Ruff E/W/F/I/UP/B, max line120.
Helper has only standard-library dependencies; pytest tests may use numpy.

PURPOSE: Repair missing upper coordinate bounds only. Keep graph/topology,
row order, node/time/row IDs, sentinels and model settings intact. Existing
rounding is Python ties-to-even. Original scientific settings and CSV remain
unchanged until the new serializer is accepted and a new kernel version runs.
No hardcoded dataset IDs, node IDs or image dimensions in helper runtime code.

1. read_output_shape(test_dir, dataset) -> tuple(T,Z,Y,X)
   Read only dataset.zarr/zarr.json and dataset.zarr/0/zarr.json via pathlib/json.
   Require root group and array metadata dictionaries, Zarr format3, array rank4
   with exactly positive integral JSON ints (bool/float/string not accepted).
   Confirm multiscales axes names normalized upper == ["T","Z","Y","X"] and
   dataset path "0" in the same metadata entry. Reject missing, ambiguous,
   malformed or mismatched metadata. No shape fallback or image-array reads.
2. new_output_bounds_report(dataset, shape) -> mutable JSON-serializable report
   Validate rank4 positive Python ints, keep dataset/shape, node_count0,
   corrected_nodes0, per-axis counts0, max absolute integer correction0,
   samples[], sample_limit20, samples_truncated false (or equivalently complete
   aggregate fields and deterministic bounded sample schema).
3. bounded_output_node(node, dataset, row_id, shape, report) -> complete node CSV
   dict in the original schema below. Must not mutate node or shape.
   Reject bool/nonintegral/nonfinite/negative node_id, t, row_id. Accept Python/
   numpy Integral and exactly integral finite Real values; no lossy integer
   cast, strings, sentinel or overflowing signed64bit. t must be 0<=t<T.
   IDs are exact int, range0..2**63-1. Validate report identity/shape consistency.
   Coordinates: convert numeric Real values to finite float (reject bool,
   string, NaN, infinity), Python round (ties-to-even), then clip to [0,dim-1].
   Keep exactly original fields/sentinels/order. Every valid uncorrected row
   must be identical to old writer. Do not clamp time or change graph.
   Report complete node_count, corrected_nodes (once/node), per-axis counts,
   max absolute integer correction, bounded first20 correction samples in
   invocation/axis z,y,x order. Each sample: dataset,row_id,node_id,t,axis,
   original_float,rounded_int,clipped_int,signed_delta,absolute_delta.
   Sample truncation must be explicit without truncating aggregates.
   Only update report after whole node validates; failure must not partly
   update it. Finite negative coordinates retain existing lower clipping.
   No IDs/datasets/shapes hardcoded in runtime logic.



Important precision to avoid prior defective implementation:
- A correction is ONLY rounded_int != clipped_int. Normal fractional rounding
  such as5.2->5 is not a bounds correction.
- The first20 samples limit is GLOBAL WITHIN ONE REPORT across all calls, not
  a new20 for each node. Aggregate counts include every corrected axis/node.
- source_id and target_id in EVERY returned node CSV row are always -1, even if
  input node omits these keys or has different values.
- node_id/t/row_id checks concern final serializer inputs only; do not alter
  existing upstream raw casts. These are fail-closed format prerequisites, not
  a new tracking algorithm. Accept numbers.Integral/Real as specified without
  converting large integer IDs to float. Enforce signed64 limits for all IDs.
- Select the root multiscales entry referencing exact path"0"; don't blindly
  choose entry0. Reject duplicate references/path0 ambiguity, malformed metadata,
  wrong axis order/rank, invalid positive JSON-integer dimensions. Other valid
  non-path0 entries must not be mistaken for the desired axes.
- Report must be validated and all computations succeed before mutation. Invalid
  report identity/shape or required counter/sample structure fails without
  mutation. Keep this bounded and avoid copying images or O(total_nodes) state.
- No future import in helper: parent later embeds it verbatim in a notebook
  after existing definitions. No typing.Dict/List/Tuple; use modernbuiltins.
- Helper does not import/tune/run models or evaluate GT.

FOCUSED TEST REQUIREMENTS (all self-contained; no real data access):
1. z/y/x separate lower/upper limits, exact bounds, ties-to-even, upper rounding
   at4.49/4.5/4.5001 with dimension5, negative finite, noncubic shapes, dimension1.
2. Valid fractional input has zero correction; valid full row equal original
   schema. Source node and shape remain unchanged; mandatory edge sentinels-1.
3. Reject NaN/±Inf/bool/string coords; invalidfractional/bool/string/negative/
   overflow IDs; time outside0..T-1. np.int64 and np.float64 integral inputs work.
4. Correct multi-axis node countedonce; complete peraxis/max with signed deltas.
   Over20 corrections across calls truncateexamples but notcounts; deterministic
   sampleorder in call then z/y/x order. Zero-correction reports visible.
5. Invalid last-axis input and invalid/corruptedreport produce no partialreport
   changes. Invalid shape and mismatcheddataset/shape reject.
6. tmp_path metadata fixtures match real root/child schemas below; testmissing,
   invalidJSON, wrongnode_type, rank/order, duplicatepath0, zero/negative/float/
   booldims, missingpath0; allow unambiguous path0 in secondvalidentry.
7. A small endpoint OLS-equivalent three-coordinate overshoot demonstrates why
   final bounds are needed; do not change smoothing itself or claim causality
   about the actual saved node.

Example original row schema:
{"id":row_id,"dataset":dataset,"row_type":"node","node_id":node_id,"t":t,
 "z":z,"y":y,"x":x,"source_id":-1,"target_id":-1}
Root metadata example:
{"zarr_format":3,"node_type":"group","attributes":{"multiscales":[
 {"axes":[{"name":"T"},{"name":"Z"},{"name":"Y"},{"name":"X"}],
  "datasets":[{"path":"0"}]}]}}
Child metadata example:
{"zarr_format":3,"node_type":"array","shape":[100,64,256,256]}
Example dimensions are illustrative, not constants in code.

Parent's later acceptance (do not implement an artifact rewrite):
same general mapping must leave pinned E23 CSV unchanged and map savedE26 to
exactly its one y256->255 correction, all other rows/fields/edges invariant.
Freshphysical correctedrun must also have only thatdifference or NO SUBMIT.
No notebookintegration source is requested in this unit.


Your prior helper, for source context only; it is known defective:
```python
"""Bounds-correcting serializer for Biohub output node rows.

This module repairs missing *upper* coordinate bounds only. Graph/topology,
row order, node/time/row IDs, sentinels and model settings are preserved.
Rounding is Python's built-in ``round`` (ties-to-even). No dataset IDs, node
IDs or image dimensions are hardcoded in runtime logic.
"""

import json
from numbers import Integral, Real
from pathlib import Path

CSV_NODE_FIELDS = ("id", "dataset", "row_type", "node_id", "t", "z", "y", "x", "source_id", "target_id")

AXIS_ORDER = ("T", "Z", "Y", "X")
COORD_AXES = ("z", "y", "x")
DIM_INDEX = {"z": 1, "y": 2, "x": 3}

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1

SAMPLE_LIMIT = 20


class OutputBoundsError(ValueError):
    """Raised when metadata, a node row or a report fails validation."""


def _is_json_int(value: object) -> bool:
    """True only for genuine integral JSON values (bool excluded)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, Integral):
        return int(value) == value
    return False


def _positive_rank4_shape(shape: object) -> tuple[int, int, int, int]:
    if not isinstance(shape, (list, tuple)) or len(shape) != 4:
        raise OutputBoundsError("array shape must be a rank-4 sequence")
    dims = []
    for axis, value in zip(AXIS_ORDER, shape, strict=True):
        if not _is_json_int(value):
            raise OutputBoundsError(f"{axis} dimension is not an integer JSON number")
        if value <= 0:
            raise OutputBoundsError(f"{axis} dimension must be positive")
        dims.append(int(value))
    return dims[0], dims[1], dims[2], dims[3]


def read_output_shape(test_dir: str | Path, dataset: str) -> tuple[int, int, int, int]:
    """Return ``(T, Z, Y, X)`` for ``dataset`` from Zarr format-3 metadata only.

    Reads ``<dataset>.zarr/zarr.json`` and ``<dataset>.zarr/0/zarr.json``. No
    shape fallback and no image-array reads are performed.
    """
    if not isinstance(dataset, str) or not dataset.strip():
        raise OutputBoundsError("dataset must be a non-empty string")
    root = Path(test_dir) / f"{dataset}.zarr"

    try:
        group_meta = json.loads((root / "zarr.json").read_text(encoding="utf-8"))
        array_meta = json.loads((root / "0" / "zarr.json").read_text(encoding="utf-8"))
    except OSError as exc:
        raise OutputBoundsError(f"missing zarr metadata for {dataset}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OutputBoundsError(f"malformed zarr metadata for {dataset}: {exc}") from exc

    if not isinstance(group_meta, dict) or not isinstance(array_meta, dict):
        raise OutputBoundsError("zarr metadata must be JSON objects")

    if group_meta.get("zarr_format") != 3 or array_meta.get("zarr_format") != 3:
        raise OutputBoundsError("only zarr format 3 metadata is supported")
    if group_meta.get("node_type") != "group":
        raise OutputBoundsError("root metadata node_type must be 'group'")
    if array_meta.get("node_type") != "array":
        raise OutputBoundsError("child metadata node_type must be 'array'")

    attributes = group_meta.get("attributes")
    if not isinstance(attributes, dict) or not isinstance(attributes.get("multiscales"), list):
        raise OutputBoundsError("root metadata is missing multiscales attributes")

    matching = []
    for entry in attributes["multiscales"]:
        if not isinstance(entry, dict):
            continue
        axes = entry.get("axes")
        if not isinstance(axes, list) or len(axes) != 4:
            continue
        names = [axis.get("name") if isinstance(axis, dict) else None for axis in axes]
        if any(not isinstance(name, str) for name in names):
            continue
        if [name.upper() for name in names] != list(AXIS_ORDER):
            continue
        datasets = entry.get("datasets")
        if not isinstance(datasets, list):
            continue
        paths = [item.get("path") for item in datasets if isinstance(item, dict)]
        if paths.count("0") < 1:
            continue
        matching.append(entry)

    if not matching:
        raise OutputBoundsError(f"no multiscales entry references dataset path '0' for {dataset}")
    if len(matching) > 1:
        raise OutputBoundsError(f"ambiguous duplicate multiscales entries referencing path '0' for {dataset}")

    entry = matching[0]
    paths = [item.get("path") for item in entry["datasets"] if isinstance(item, dict)]
    if len(paths) != paths.count("0"):
        raise OutputBoundsError(f"duplicate dataset path '0' reference for {dataset}")
    if paths.index("0") != 0:
        raise OutputBoundsError("dataset path '0' must be the first entry of its multiscales group")

    return _positive_rank4_shape(array_meta.get("shape"))


def new_output_bounds_report(dataset: str, shape: tuple[int, int, int, int]) -> dict:
    """Build a fresh, JSON-serializable, mutable bounds-correction report."""
    if not isinstance(dataset, str) or not dataset.strip():
        raise OutputBoundsError("dataset must be a non-empty string")
    t, z, y, x = _positive_rank4_shape(list(shape))
    return {
        "dataset": dataset,
        "shape": [t, z, y, x],
        "node_count": 0,
        "corrected_nodes": 0,
        "axis_counts": {"z": 0, "y": 0, "x": 0},
        "max_absolute_correction": 0,
        "samples": [],
        "sample_limit": SAMPLE_LIMIT,
        "samples_truncated": False,
    }


def _validate_report(report: object, dataset: str, shape: tuple[int, int, int, int]) -> None:
    if not isinstance(report, dict):
        raise OutputBoundsError("report must be a dict")
    if report.get("dataset") != dataset:
        raise OutputBoundsError("report dataset identity mismatch")
    if _positive_rank4_shape(report.get("shape")) != tuple(int(v) for v in shape):
        raise OutputBoundsError("report shape mismatch")
    if not _is_json_int(report.get("node_count")) or report["node_count"] < 0:
        raise OutputBoundsError("report node_count is invalid")
    if not _is_json_int(report.get("corrected_nodes")) or report["corrected_nodes"] < 0:
        raise OutputBoundsError("report corrected_nodes is invalid")
    counts = report.get("axis_counts")
    if not isinstance(counts, dict) or set(counts) != set(COORD_AXES):
        raise OutputBoundsError("report axis_counts must cover z, y and x")
    for axis in COORD_AXES:
        if not _is_json_int(counts[axis]) or counts[axis] < 0:
            raise OutputBoundsError(f"report axis_counts[{axis!r}] is invalid")
    maximum = report.get("max_absolute_correction")
    if not _is_json_int(maximum) or maximum < 0:
        raise OutputBoundsError("report max_absolute_correction is invalid")
    samples = report.get("samples")
    if not isinstance(samples, list) or len(samples) > SAMPLE_LIMIT:
        raise OutputBoundsError("report samples must be a list bounded by the sample limit")
    if not _is_json_int(report.get("sample_limit")) or report["sample_limit"] != SAMPLE_LIMIT:
        raise OutputBoundsError("report sample_limit is invalid")
    if not isinstance(samples_truncated_flag := report.get("samples_truncated"), bool):
        raise OutputBoundsError("report samples_truncated must be a bool")
    if samples_truncated_flag and len(samples) < SAMPLE_LIMIT:
        raise OutputBoundsError("report samples_truncated is inconsistent with samples")
    expected = sum(1 for item in samples if isinstance(item, dict))
    if expected != len(samples):
        raise OutputBoundsError("report samples must be dicts")


def _as_exact_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise OutputBoundsError(f"{label} must not be a bool")
    if isinstance(value, Integral):
        number = int(value)
    elif isinstance(value, Real):
        if value != value or value in (float("inf"), float("-inf")):
            raise OutputBoundsError(f"{label} must be finite")
        floored = float(value).__floor__()
        if float(value) != float(floored):
            raise OutputBoundsError(f"{label} must be exactly integral")
        number = int(floored)
    else:
        raise OutputBoundsError(f"{label} must be a real number, not {type(value).__name__}")
    if number < INT64_MIN or number > INT64_MAX:
        raise OutputBoundsError(f"{label} exceeds signed 64-bit limits")
    return number


def _coord_to_float(value: object, axis: str) -> float:
    if isinstance(value, bool):
        raise OutputBoundsError(f"coordinate {axis} must not be a bool")
    if isinstance(value, str):
        raise OutputBoundsError(f"coordinate {axis} must not be a string")
    if not isinstance(value, Real):
        raise OutputBoundsError(f"coordinate {axis} must be a real number")
    number = float(value)
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
    the whole node validates successfully.
    """
    if not isinstance(node, dict):
        raise OutputBoundsError("node must be a dict")
    if not isinstance(dataset, str) or not dataset.strip():
        raise OutputBoundsError("dataset must be a non-empty string")
    t_dim, z_dim, y_dim, x_dim = _positive_rank4_shape(list(shape))
    _validate_report(report, dataset, (t_dim, z_dim, y_dim, x_dim))

    row = _as_exact_int(row_id, "row_id")
    if row < 0:
        raise OutputBoundsError("row_id must be non-negative")
    node_id = _as_exact_int(node.get("node_id"), "node_id")
    if node_id < 0:
        raise OutputBoundsError("node_id must be non-negative")
    t = _as_exact_int(node.get("t"), "t")
    if not 0 <= t < t_dim:
        raise OutputBoundsError(f"t={t} outside [0, T-1] for T={t_dim}")

    dims = {"z": z_dim, "y": y_dim, "x": x_dim}
    rounded = {}
    clipped = {}
    corrections = []
    for axis in COORD_AXES:
        original = _coord_to_float(node.get(axis), axis)
        near = round(original)
        limit = dims[axis] - 1
        near = min(max(near, 0), limit)
        rounded[axis] = near
        clipped[axis] = near
        if rounded[axis] != near:
            corrections.append(axis)

    deltas = {}
    for axis in corrections:
        original = _coord_to_float(node.get(axis), axis)
        near = round(original)
        limit = dims[axis] - 1
        bound = min(max(near, 0), limit)
        clipped[axis] = bound
        deltas[axis] = (int(bound) - int(near), abs(int(bound) - int(near)))

    out = {
        "id": row,
        "dataset": dataset,
        "row_type": "node",
        "node_id": node_id,
        "t": t,
        "z": clipped["z"],
        "y": clipped["y"],
        "x": clipped["x"],
        "source_id": -1,
        "target_id": -1,
    }

    if corrections:
        report["corrected_nodes"] += 1
        for axis in COORD_AXES:
            if axis in corrections:
                report["axis_counts"][axis] += 1
        for axis in COORD_AXES:
            if axis not in corrections:
                continue
            signed, absolute = deltas[axis]
            if absolute > report["max_absolute_correction"]:
                report["max_absolute_correction"] = absolute
            if len(report["samples"]) < SAMPLE_LIMIT:
                report["samples"].append(
                    {
                        "dataset": dataset,
                        "row_id": row,
                        "node_id": node_id,
                        "t": t,
                        "axis": axis,
                        "original_float": _coord_to_float(node.get(axis), axis),
                        "rounded_int": int(round(_coord_to_float(node.get(axis), axis))),
                        "clipped_int": int(clipped[axis]),
                        "signed_delta": signed,
                        "absolute_delta": absolute,
                    }
                )
            else:
                report["samples_truncated"] = True

    report["node_count"] += 1
    return out
```

Your prior tests, for source context only; some expectations are known defective:
```python
import copy
import json
import math

import numpy as np
import pytest

from biohub.output_bounds import (
    OutputBoundsError,
    bounded_output_node,
    new_output_bounds_report,
    read_output_shape,
)


def write_metadata(tmp_path, dataset, shape=(100, 64, 256, 256), *, axes=None, extra_entries=(), child_node="array"):
    root = tmp_path / f"{dataset}.zarr"
    (root / "0").mkdir(parents=True)
    if axes is None:
        axes = [{"name": "T"}, {"name": "Z"}, {"name": "Y"}, {"name": "X"}]
    entry = {"axes": axes, "datasets": [{"path": "0"}]}
    group = {
        "zarr_format": 3,
        "node_type": "group",
        "attributes": {"multiscales": [entry, *extra_entries]},
    }
    child = {"zarr_format": 3, "node_type": child_node, "shape": list(shape)}
    (root / "zarr.json").write_text(json.dumps(group), encoding="utf-8")
    (root / "0" / "zarr.json").write_text(json.dumps(child), encoding="utf-8")
    return root


def make_node(node_id=7, t=3, z=10.5, y=20.25, x=30.0):
    return {"node_id": node_id, "t": t, "z": z, "y": y, "x": x}


SHAPE = (100, 64, 256, 256)


def report_for(dataset="demo", shape=SHAPE):
    return new_output_bounds_report(dataset, shape)


def node_row(**overrides):
    row = {"node_id": 1, "t": 1, "z": 5.2, "y": 5.2, "x": 5.2}
    row.update(overrides)
    return row


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


def test_read_output_shape_wrong_node_type(tmp_path):
    write_metadata(tmp_path, "demo", child_node="group")
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_read_output_shape_wrong_axis_order(tmp_path):
    write_metadata(tmp_path, "demo", axes=[{"name": "T"}, {"name": "Y"}, {"name": "Z"}, {"name": "X"}])
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_read_output_shape_rank_mismatch(tmp_path):
    write_metadata(tmp_path, "demo", shape=(64, 256, 256))
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


@pytest.mark.parametrize("bad", [0, -5, 4.5, True, False, "64"])
def test_read_output_shape_bad_dims(tmp_path, bad):
    write_metadata(tmp_path, "demo", shape=(100, bad, 256, 256))
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_read_output_shape_duplicate_path_zero(tmp_path):
    dup = {"axes": [{"name": "T"}, {"name": "Z"}, {"name": "Y"}, {"name": "X"}], "datasets": [{"path": "0"}, {"path": "0"}]}
    write_metadata(tmp_path, "demo", extra_entries=[dup])
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_read_output_path_zero_in_second_entry(tmp_path):
    other = {"axes": [{"name": "T"}, {"name": "Z"}, {"name": "Y"}, {"name": "X"}], "datasets": [{"path": "1"}]}
    write_metadata(tmp_path, "demo", extra_entries=[other])
    root = tmp_path / "demo.zarr"
    group = json.loads((root / "zarr.json").read_text(encoding="utf-8"))
    group["attributes"]["multiscales"] = [other, group["attributes"]["multiscales"][0]]
    (root / "zarr.json").write_text(json.dumps(group), encoding="utf-8")
    assert read_output_shape(tmp_path, "demo") == (100, 64, 256, 256)


def test_read_output_shape_missing_path_zero(tmp_path):
    root = write_metadata(tmp_path, "demo")
    group = json.loads((root / "zarr.json").read_text(encoding="utf-8"))
    group["attributes"]["multiscales"][0]["datasets"] = [{"path": "2"}]
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


@pytest.mark.parametrize(("value", "expected"), [(4.49, 4), (4.5, 4), (4.5001, 5)])
def test_upper_rounding_ties_to_even_dim_five(value, expected):
    shape = (10, 5, 5, 5)
    report = new_output_bounds_report("tiny", shape)
    row = bounded_output_node(node_row(z=value, y=value, x=value), "tiny", 0, shape, report)
    assert row["z"] == row["y"] == row["x"] == expected
    assert report["corrected_nodes"] == 0
    assert report["samples"] == []


def test_negative_finite_and_noncubic_and_dim_one():
    shape = (4, 1, 30, 500)
    report = new_output_bounds_report("nc", shape)
    row = bounded_output_node(node_row(t=2, z=-9.75, y=-1.0, x=499.9), "nc", 5, shape, report)
    assert row["z"] == 0 and row["y"] == 0 and row["x"] == 499
    assert row["z"] == 0
    assert report["axis_counts"] == {"z": 1, "y": 0, "x": 1}
    assert report["max_absolute_correction"] == 1


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
    assert list(row) == ["id", "dataset", "row_type", "node_id", "t", "z", "y", "x", "source_id", "target_id"]
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
    row = bounded_output_node(node, "demo", 0, SHAPE, report)
    assert node == snapshot
    assert list(shape_snapshot) == list(SHAPE)
    assert row["source_id"] == -1 and row["target_id"] == -1


def test_missing_edge_keys_still_sentinel():
    node = {"node_id": 2, "t": 0, "z": 1.0, "y": 1.0, "x": 1.0}
    row = bounded_output_node(node, "demo", 0, SHAPE, report_for())
    assert row["source_id"] == -1 and row["target_id"] == -1


@pytest.mark.parametrize("bad", [float("nan"), math.inf, -math.inf, True, False, "5.0", None])
def test_reject_bad_coordinates(bad):
    report = report_for()
    before = copy.deepcopy(report)
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(y=bad), "demo", 0, SHAPE, report)
    assert report == before


@pytest.mark.parametrize("bad", [1.5, True, "7", -1, 2**63])
def test_reject_bad_ids(bad):
    report = report_for()
    before = copy.deepcopy(report)
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(node_id=bad), "demo", 0, SHAPE, report)
    assert report == before


@pytest.mark.parametrize("bad", [1.5, True, "7", -1])
def test_reject_bad_row_ids(bad):
    report = report_for()
    before = copy.deepcopy(report)
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(), "demo", bad, SHAPE, report)
    assert report == before


def test_numpy_integral_and_real_inputs_work():
    report = report_for()
    node = {"node_id": np.int64(9), "t": np.int64(2), "z": np.float64(4.0), "y": np.float64(260.0), "x": np.float64(3.5)}
    row = bounded_output_node(node, "demo", np.int64(11), SHAPE, report)
    assert row["node_id"] == 9 and row["id"] == 11 and row["t"] == 2
    assert row["y"] == 255 and row["x"] == 4
    assert all(type(row[key]) is int for key in ("id", "node_id", "t", "z", "y", "x"))


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
    row = bounded_output_node(node_row(z=-2.0, y=300.0, x=999.0), "demo", 4, SHAPE, report)
    assert row == {"id": 4, "dataset": "demo", "row_type": "node", "node_id": 1, "t": 1,
                   "z": 0, "y": 255, "x": 255, "source_id": -1, "target_id": -1}
    assert report["corrected_nodes"] == 1
    assert report["axis_counts"] == {"z": 1, "y": 1, "x": 1}
    assert report["max_absolute_correction"] == 744
    axes = [sample["axis"] for sample in report["samples"]]
    assert axes == ["z", "y", "x"]
    assert [s["signed_delta"] for s in report["samples"]] == [2, -45, -744]
    assert [s["absolute_delta"] for s in report["samples"]] == [2, 45, 744]
    assert report["samples"][0]["original_float"] == -2.0
    assert report["samples"][0]["rounded_int"] == -2
    assert report["samples"][0]["clipped_int"] == 0


def test_sample_limit_is_global_across_calls():
    report = report_for()
    for index in range(12):
        bounded_output_node(node_row(node_id=index, x=300.0 + index), "demo", index, SHAPE, report)
    assert report["node_count"] == 12
    assert report["corrected_nodes"] == 12
    assert report["axis_counts"]["x"] == 12
    assert len(report["samples"]) == 20
    assert report["samples_truncated"] is True
    assert report["max_absolute_correction"] == 44
    assert [s["row_id"] for s in report["samples"]] == list(range(12)) + list(range(8))
    assert [s["node_id"] for s in report["samples"]] == list(range(12)) + list(range(8))


def test_last_axis_failure_leaves_report_untouched():
    report = report_for()
    report["node_count"] = 5
    before = copy.deepcopy(report)
    with pytest.raises(OutputBoundsError):
        bounded_output_node({"node_id": 1, "t": 1, "z": 300.0, "y": 300.0, "x": "bad"}, "demo", 0, SHAPE, report)
    assert report == before


@pytest.mark.parametrize("mutate", [
    lambda r: r.__setitem__("dataset", "other"),
    lambda r: r.__setitem__("shape", [100, 64, 256, 128]),
    lambda r: r.__setitem__("node_count", -1),
    lambda r: r.__setitem__("axis_counts", {"z": 0, "y": 0}),
    lambda r: r.__setitem__("max_absolute_correction", 1.5),
    lambda r: r.__setitem__("samples", "corrupt"),
    lambda r: r.__setitem__("samples_truncated", "yes"),
])
def test_corrupted_reports_rejected_without_mutation(mutate):
    report = report_for()
    mutate(report)
    before = copy.deepcopy(report)
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(x=300.0), "demo", 0, SHAPE, report)
    assert report == before


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


def test_zero_correction_report_is_visible():
    report = report_for()
    bounded_output_node(node_row(), "demo", 0, SHAPE, report)
    assert report["node_count"] == 1
    assert report["corrected_nodes"] == 0
    assert json.dumps(report)


# ------------------------------------------------------- endpoint overshoot demo


def test_endpoint_overshoot_needs_final_bounds():
    """OLS-equivalent endpoint fit on three coords overshoots; bounds repair it."""
    dims = (20, 10, 10, 10)
    pts = [(0.0, 0.0), (1.0, 4.0), (2.0, 9.0)]
    n = len(pts)
    sx = sum(p[0] for p in pts)
    sy = sum(p[1] for p in pts)
    sxx = sum(p[0] ** 2 for p in pts)
    slope = (n * sxx - sx * sx) / (n * sxx - sx * sx) if False else (n * sum(p[0] * p[1] for p in pts) - sx * sy) / (n * sxx - sx * sx)
    intercept = (sy - slope * sx) / n
    raw_end = slope * 3.0 + intercept
    assert raw_end > dims[1] - 1
    report = new_output_bounds_report("ols", dims)
    row = bounded_output_node({"node_id": 1, "t": 3, "z": raw_end, "y": 1.0, "x": 1.0}, "ols", 0, dims, report)
    assert row["z"] == dims[1] - 1
    assert report["corrected_nodes"] == 1
    assert report["axis_counts"]["z"] == 1
```

FINAL DELIVERY ONLY:
HELPER
```python
<complete corrected helper>
```
TESTS
```python
<complete corrected tests>
```
