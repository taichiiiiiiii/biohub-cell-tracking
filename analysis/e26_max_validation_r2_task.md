# E26 Max validation repair r2 — supervised user-requested implementation

> 履歴・非運用・現行起動に使用禁止。この旧タスクは保存用です。
> 現行方針は [AGENTS.md](../AGENTS.md)、MAX評価入口は
> [評価手順](../.codex/runners/biohub_max_implementer.instructions.md) を参照。
> 以下のモデル指定・命令・実行例は当時の履歴であり、現在のworkerへ渡してはいけません。

The user now directly requested qwen3.8-max and project progress.
Use the existing subscription-only Qwen Cloud route, effort none, no tools.
This is a new parent-supervised bounded task, not a heartbeat or restart of the
closed prior task. Answer from this text; do not read files, run tools, or claim tests ran.
Scope: validation only within the existing generic final CSV serializer.
Tracking/weights/settings/graph/IDs/order/rounding/clip/update semantics must stay fixed.
No notebook integration in this unit. No hard-coded dataset/node IDs or image dimensions.

The prior Max module below has a working generated clipping/telemetry path but
fails acceptance. Parent measured112PASS/1FAIL, Ruff2. Fix only the diagnosed
validation defects, remove unused helper inspect, and fix the genuinely wrong
existing test oracle. Do NOT rewrite/reduce unrelated existing tests.

DELIVER exactly these THREE labeled literal Python blocks, no other text:
HELPER
```python
<COMPLETE corrected standalone helper module; not a patch>
```
ORACLE
```python
<only complete def test_reports_with_samples_are_validated; no imports>
```
REGRESSIONS
```python
<complete standalone pytest module with new focused regression tests>
```
No JSON-encoded source, omitted code or tool calls.
Parent mechanically keeps every other old test, replaces only the named oracle
function with ORACLE, and adds REGRESSIONS as tests/test_output_bounds_regressions.py.
Parent may run import-only Ruff formatting; all logic and test oracles come from you.
Helper destination after acceptance: src/biohub/output_bounds.py.
Existing tests destination after acceptance: tests/test_output_bounds.py.

REQUIRED VALIDATION, all invalid cases must raise OutputBoundsError and leave
report/node/shape unchanged. Public API signatures and CSV schema remain:
read_output_shape(test_dir,dataset)->(T,Z,Y,X);
new_output_bounds_report(dataset,shape)->dict;
bounded_output_node(node,dataset,row_id,shape,report)->dict.
Python3.12, helper stdlib only, NO future import. Types/keys/constants already below.
Avoid new generic infrastructure and preserve working code wherever possible.

1. SAMPLE validity needs shape passed by _validate_report.
Exact keys as CSV_SAMPLE_FIELDS; dataset is builtin str matching report;
axis builtin str z/y/x; original_float builtin finite float; all integer fields
builtin int (not bool/numpy/Fraction). row_id/node_id/t in0..2**63-1, t<T.
rounded_int == round(original_float).
clipped_int == min(max(rounded_int,0),shape[DIM_INDEX[axis]]-1).
signed_delta == clipped_int-rounded_int; absolute_delta == abs(signed_delta)>0.
Rounded coordinates and deltas derive from finite floats and need NOT fit int64.
Concrete missed case: x300 -> rounded300, clipped254, signed-46,abs46,max46:
internally consistent deltas but WRONG projection for dim256; must reject.
Also reject sample t100 for T100, row_id or node_id2**63.

2. REPORT invariants must all hold simultaneously:
N=node_count counts accepted calls; C=corrected_nodes counts corrected CALLS.
IDs can repeat across calls. Do not require unique IDs or C == unique identities.
N,C,max,axis counts,sample_limit builtin nonnegative ints; sample_limit exactly20.
report exact REPORT_FIELDS; shape JSON list of exactly4 positive builtin ints;
shape matches the validated input shape; dataset builtin str matching input;
axis_counts exactly z/y/x; samples list <=20, truncated builtin bool.
0<=C<=N; EACH ai<=C; S=sum(ai), C<=S<=3*C.
len(samples)==min(S,20) ALWAYS; samples_truncated is EXACT bool(S>20).
S=0 => C0/max0/no samples/truncfalse. S>0 => max>=1.
S<=20 => per-axis visible sample counts EXACTLY equal ai; max EXACT sample max.
S>20 => per-axis VISIBLE sample counts <= ai; max >= VISIBLE sample max.
Never overwrite/infer complete totals/max from truncated examples.
Number of distinct observed(row_id,node_id,t) keys <=C (only a lower bound).
Do not retain O(total_nodes) history or invent unavailable-history constraints.
Mandatory missed cases:
- 21 SAME x300 corrections,20 samples,total21, then set truncfalse: reject,
  even though complete max equals visible max45.
- 20 events/samples but set trunctrue: reject.
- x sample but totals z1,y0,x0: reject (sum matches; per-axis does not).
- N1,C1, x-count2 with two internally valid x samples: reject because ai>C.
- truncated data whose visible x count exceeds aggregate x count: reject.
Positive control: 25 x300..324 corrections =>N25,C25,x25,20 samples,
trunctrue,max69 > visible64; next valid call must still ACCEPT.
Repeated identical(row_id,node_id,t) over3 corrected calls must ACCEPT as C3.

3. METADATA validates axes on EVERY multiscales entry, not just selected path0:
axes nonempty list of dicts with nonempty string name. Other valid non-path0
entries may have different axes. Only selected path0 entry requires exact
normalized T,Z,Y,X. Preserve global exact-string path0 uniqueness, strict
zarr_format builtin int3, group/array kinds, positive rank4 builtin dimensions.
Valid path0 entry plus a non-path0 entry without axes must REJECT.
Do not read images, use fallback shapes, or change path0-selection semantics.

4. Numeric/shape failures:
new_output_bounds_report and bounded_output_node must validate shape BEFORE
coercing to list; reject None/scalar/string/generator and preserve input.
Keep exact Fraction(2**53+1,1)/Fraction(2**63-1,1) IDs without float roundtrip;
fractional Fraction rejects. np.int64/np.float64 integral accept.
NaN/Inf ID conversion and huge Real coordinate float overflow must normalize
to OutputBoundsError, not leak ValueError/OverflowError/TypeError.
Keep coordinate conversion finite numeric Real/no bool/str, ties-to-even round,
clip lower/upper, complete per-call count and maximum across all events.
Malformed JSON/UTF-8 metadata must be OutputBoundsError too.
Do not broaden scope to upstream raw int casts.

5. ORACLE fix: original x300 sample already has absolute_delta45. Assigning45
does not corrupt it. Use a DIFFERENT value and assert the mutation changes the
fixture before expecting rejection. Preserve other checks in this function.

REGRESSIONS must execute the public API (not merely inspect function names):
cover each concrete counterexample above, atomic rejection, positive truncation,
repeated-ID calls, NaN/Inf across node_id/t/row_id, huge Fraction coordinate,
invalid shape for both public writer functions, malformed non-path0 axes plus
positive different non-path0 axes. Cover int64 sample bounds separately from
huge finite coordinate deltas. Use synthetic data/tmp metadata only.
Available: pytest,numpy,Fraction; module imports from biohub.output_bounds.
No networks/model loads/GT. Keep lines<=120 and Ruff E/W/F/I/UP/B.
The repo groups biohub imports with third-party (no blank line after pytest).

ORIGINAL HELPER:
```python
"""Bounds-correcting serializer for Biohub output node rows.

This module repairs missing *upper* coordinate bounds only. Graph/topology,
row order, node/time/row IDs, sentinels and model settings are preserved.
Rounding is Python's built-in ``round`` (ties-to-even). No dataset IDs, node
IDs or image dimensions are hardcoded in runtime logic.
"""

import inspect
import json
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


def _positive_rank4_shape(shape: object) -> tuple[int, int, int, int]:
    """Validate a rank-4 sequence of positive Python ints."""
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
        raise OutputBoundsError("multiscales entries require a non-empty datasets list")
    paths: list[str] = []
    for item in datasets:
        if not isinstance(item, dict) or "path" not in item:
            raise OutputBoundsError("multiscales dataset entries require a path")
        path = item["path"]
        if not isinstance(path, str) or not path:
            raise OutputBoundsError("multiscales dataset path must be a non-empty string")
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


def read_output_shape(
    test_dir: str | Path, dataset: str
) -> tuple[int, int, int, int]:
    """Return ``(T, Z, Y, X)`` for ``dataset`` from Zarr format-3 metadata only.

    Reads ``<dataset>.zarr/zarr.json`` and ``<dataset>.zarr/0/zarr.json``. No
    shape fallback and no image-array reads are performed. Exactly one
    reference to the literal path ``"0"`` is required across *all* multiscales
    entries, counted before any axis filtering.
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
        raise OutputBoundsError("root metadata is missing multiscales attributes")

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
    t_dim, z_dim, y_dim, x_dim = _positive_rank4_shape(list(shape))
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


def _validate_sample(sample: object, index: int, dataset: str) -> None:
    """Validate a single sample entry against the schema and dataset."""
    if not isinstance(sample, dict):
        raise OutputBoundsError(f"report samples[{index}] must be a dict")
    if set(sample) != set(CSV_SAMPLE_FIELDS):
        raise OutputBoundsError(
            f"report samples[{index}] fields do not match the sample schema"
        )
    if sample["dataset"] != dataset:
        raise OutputBoundsError(f"report samples[{index}] dataset mismatch")
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
    if sample["row_id"] < 0 or sample["node_id"] < 0 or sample["t"] < 0:
        raise OutputBoundsError(
            f"report samples[{index}] identifiers must be non-negative"
        )
    if sample["axis"] not in COORD_AXES:
        raise OutputBoundsError(f"report samples[{index}] axis is invalid")
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
    if rounded != clipped:
        pass
    else:
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
        raise OutputBoundsError("report fields do not match the report schema")
    if report["dataset"] != dataset:
        raise OutputBoundsError("report dataset identity mismatch")
    if _positive_rank4_shape(report["shape"]) != tuple(shape):
        raise OutputBoundsError("report shape mismatch")
    for key in ("node_count", "corrected_nodes", "max_absolute_correction"):
        value = report[key]
        if not _is_python_int(value) or value < 0:
            raise OutputBoundsError(f"report {key} is invalid")
    counts = report["axis_counts"]
    if not isinstance(counts, dict) or set(counts) != set(COORD_AXES):
        raise OutputBoundsError("report axis_counts must cover z, y and x")
    for axis in COORD_AXES:
        if not _is_python_int(counts[axis]) or counts[axis] < 0:
            raise OutputBoundsError(f"report axis_counts[{axis!r}] is invalid")
    if not _is_python_int(report["sample_limit"]) or report["sample_limit"] != SAMPLE_LIMIT:
        raise OutputBoundsError("report sample_limit is invalid")
    if not isinstance(report["samples_truncated"], bool):
        raise OutputBoundsError("report samples_truncated must be a bool")
    samples = report["samples"]
    if not isinstance(samples, list) or len(samples) > SAMPLE_LIMIT:
        raise OutputBoundsError(
            "report samples must be a list bounded by the sample limit"
        )
    for index, sample in enumerate(samples):
        _validate_sample(sample, index, dataset)
    corrected = report["corrected_nodes"]
    node_count = report["node_count"]
    axis_total = sum(counts[axis] for axis in COORD_AXES)
    if corrected > node_count:
        raise OutputBoundsError("report corrected_nodes exceeds node_count")
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
    if report["samples_truncated"] and len(samples) != SAMPLE_LIMIT:
        raise OutputBoundsError(
            "report samples_truncated is inconsistent with samples"
        )
    if not report["samples_truncated"] and len(samples) < SAMPLE_LIMIT:
        if axis_total != len(samples):
            raise OutputBoundsError(
                "untruncated report sample count must equal axis_total"
            )
    visible_max = 0
    for sample in samples:
        visible_max = max(visible_max, sample["absolute_delta"])
    if report["max_absolute_correction"] < visible_max:
        raise OutputBoundsError(
            "report max_absolute_correction is below its samples"
        )
    if not report["samples_truncated"]:
        if report["max_absolute_correction"] != visible_max:
            raise OutputBoundsError(
                "untruncated report max must equal visible sample max"
            )


def _as_exact_int(value: object, label: str) -> int:
    """Return an exact Python int without ever routing Reals through float."""
    if isinstance(value, bool):
        raise OutputBoundsError(f"{label} must not be a bool")
    if isinstance(value, Integral):
        number = int(value)
    elif isinstance(value, Real):
        candidate = round(value)
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
    the whole node validates successfully. A correction is recorded only when
    the rounded integer differs from the clipped integer.
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
    t_val = _as_exact_int(node.get("t"), "t")
    if not 0 <= t_val < t_dim:
        raise OutputBoundsError(f"t={t_val} outside [0, T-1] for T={t_dim}")

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
```

EXISTING TEST FIXTURES (in original test module; ORACLE can use these):
```python
import copy
import inspect
import json
import math
from fractions import Fraction
import numpy as np
import pytest
from biohub.output_bounds import OutputBoundsError, bounded_output_node, new_output_bounds_report, read_output_shape
SHAPE = (100, 64, 256, 256)
def report_for(dataset="demo", shape=SHAPE):
    return new_output_bounds_report(dataset, shape)
def node_row(**overrides):
    row = {"node_id": 1, "t": 1, "z": 5.2, "y": 5.2, "x": 5.2}
    row.update(overrides)
    return row
```

ORIGINAL SINGLE TEST TO REPLACE:
```python
def test_reports_with_samples_are_validated():
    report = report_for()
    bounded_output_node(node_row(x=300.0), "demo", 0, SHAPE, report)
    good = copy.deepcopy(report)
    assert bounded_output_node(node_row(x=301.0), "demo", 1, SHAPE, report)["x"] == 255
    assert report["node_count"] == 2

    for field, value in [
        ("rounded_int", 299),
        ("clipped_int", 254),
        ("absolute_delta", 45),
    ]:
        broken = copy.deepcopy(good)
        broken["samples"][0][field] = value
        with pytest.raises(OutputBoundsError):
            bounded_output_node(node_row(), "demo", 9, SHAPE, broken)

    truncated = copy.deepcopy(good)
    truncated["samples_truncated"] = True
    with pytest.raises(OutputBoundsError):
        bounded_output_node(node_row(), "demo", 9, SHAPE, truncated)

    over_max = copy.deepcopy(good)
    over_max["max_absolute_correction"] = 0
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
```
