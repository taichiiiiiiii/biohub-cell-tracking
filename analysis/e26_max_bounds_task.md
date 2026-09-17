# E26 bounds repair: user-authorized Qwen3.8 Max unit

> 履歴・非運用・現行起動に使用禁止。この旧タスクは保存用です。
> 現行方針は [AGENTS.md](../AGENTS.md)、MAX評価入口は
> [評価手順](../.codex/runners/biohub_max_implementer.instructions.md) を参照。
> 以下のモデル指定・命令・実行例は当時の履歴であり、現在のworkerへ渡してはいけません。

The user explicitly said to use qwen3.8-max if Flash did not improve. The parent
verified Flash's final review HOLD and selected exactly qwen3.8-max through
qwen_token_plan (subscription only). No fallback, purchases or API retries.
This is one directly user-initiated, parent-supervised coding unit, not automation.
No tools, file reads/writes, network, agents or execution. Answer from this text.
The parent, not you, applies source and runs tests. Do not claim tests ran.
Parent supervision is bounded to600seconds from actual admission.

DELIVERY: exactly two labels and literal Python blocks, nothing else:
HELPER
```python
<complete standalone module>
```
TESTS
```python
<complete pytest module>
```
Real newlines. No JSON encoding, patches, markdown commentary or omitted code.
Destinations after independent acceptance: src/biohub/output_bounds.py and
tests/test_output_bounds.py. The code below is isolated and NOT adopted.

Scope: fix the generic FINAL node CSV serializer and its evidence, not tracking.
Keep Python ties-to-even round, then clip coordinates to actual dimension limits.
Never change model weights/settings, graph edges, IDs, time, row order, smoothing,
raw conversions or historical artifacts. No hardcoded dataset/node/shape values.
The only current scientific lever stays motion relink OFF, validator OFF.
The strict later public4 gate expects a single saved y256->255 correction and
otherwise identical output, but those identities must NEVER enter helper logic.
No notebook integration requested in this unit.

API contract (Python3.12; helper stdlib only; no future import):
- read_output_shape(test_dir,dataset)->(T,Z,Y,X), reads ONLY
  <test_dir>/<dataset>.zarr/zarr.json and <dataset>.zarr/0/zarr.json via json/pathlib.
  Root dict/group and child dict/array; zarr_format must type int and equal3.
  Shape list or tuple of exactly4 positive builtin int dimensions; reject bool,
  float, numpy int, string, zero/negative. Do not read image arrays/fallback.
  Root attributes.multiscales is a list of dict entries. Each entry must have
  valid axes list (axis dicts with nonempty name strings) and nonempty datasets
  list (dicts with nonempty string path). Other valid non-path0 entries may have
  different axes; only the unique path0 entry must have axes normalized upper
  exactly T,Z,Y,X. Count all exact "0" path references before selecting; require
  exactly1 globally, including within-entry duplicates. Missing/malformed/ambiguous
  entries reject, including bad non-string path values. Path0 may be in the second
  multiscale entry and need not be first/only in its datasets list.
- new_output_bounds_report(dataset,shape)->dict, fresh JSON-safe report with
  exactly these fields: dataset,shape(list),node_count,corrected_nodes,axis_counts
  (z/y/x),max_absolute_correction,samples(list),sample_limit20,samples_truncated(bool).
  All counters initially0; samples empty; truncated false.
- bounded_output_node(node,dataset,row_id,shape,report)->dict with EXACT field order:
  id,dataset,row_type,node_id,t,z,y,x,source_id,target_id.
  row_type="node", source_id=target_id=-1 ALWAYS (ignore input extra sentinels).
  Never mutate node or shape. Validate everything and prepare the complete update
  before changing report; any invalid node/report must leave report unchanged.
  row_id/node_id/t accept numbers.Integral (not bool) and finite exactly-integral
  numbers.Real, returning exact Python ints in0..2**63-1, with t<T.
  No lossy float conversion for IDs. Fraction(2**53+1,1) and Fraction(2**63-1,1)
  remain exact; Fraction(2**54+1,2) rejects. np.int64/np.float64 integral work.
  Reject negative/bool/string/fractional/nonfinite/overflow/missing IDs.
  Coordinate inputs must be numeric Real, not bool/string; convert to finite
  float, Python round -> rounded_int, then clip -> clipped_int in0..dim-1.
  Preserve distinct original_float/rounded_int/clipped_int. Correction ONLY if
  rounded_int!=clipped_int; normal fractional rounding is not correction.
  Use OutputBoundsError(ValueError) consistently for invalid metadata/node/report;
  normalize invalid numeric conversion failures without emitting partial output.
  These validate FINAL serializer inputs, not upstream raw int casts.

Report semantics and oracle (IMPORTANT):
- N=node_count counts accepted calls; C=corrected_nodes counts corrected CALLS
  once per call, NOT distinct biological IDs. Input IDs/row_id may repeat across
  helper calls; do not invent monotonicity/uniqueness restrictions or extra history.
- ai=axis_counts[axis] counts corrected axis events. S=sum(ai).
  Counters/max/sample_limit must builtin ints (not bool/numpy/Fraction); N>=0,
  0<=C<=N, 0<=ai<=C, C<=S<=3*C.
  S=0 iff C=0; then max0/samples[]/truncated false. S>0 implies max>=1.
- Each sample has EXACT keys dataset,row_id,node_id,t,axis,original_float,
  rounded_int,clipped_int,signed_delta,absolute_delta.
  Builtin JSON-safe scalars ONLY: original_float type float and finite; integer
  fields type int not bool. dataset must match report; IDs range/time valid;
  axis z/y/x; rounded_int==round(original_float); clipped_int is exactly the
  shape-derived projection; rounded!=clipped; signed=clipped-rounded;
  absolute=abs(signed)>0. Rounded coordinates/deltas need NOT fit signed64, as
  they derive from any finite float; final IDs do fit signed64.
- len(samples)==min(S,20); samples_truncated is EXACT bool(S>20).
  S<=20: per-axis sample counts must equal ai, max must equal sample max.
  S>20: per-axis VISIBLE sample counts <= ai; report max >= visible max.
  Never reconstruct or overwrite full totals/max from20 truncated samples.
  Observed distinct (row_id,node_id,t) sample keys give a lower bound on C only,
  not equality, even when untruncated: repeated-ID calls are allowed.
  Do not claim complete report validity proves actual history; enforce only
  invariants that are derivable from the defined representation.
- Save deterministic first20 corrected AXIS events globally PER REPORT in
  call order then z,y,x order. Counts and maxima include all events after20.
  Validate existing report before mutating; updated report stays strict JSON-safe.
  Bounded work over<=20 samples is fine; no O(total_nodes) state/image copies.
  Do not permit non-JSON values hidden in extra report keys.

Prior diagnosis (real parent pytest97PASS/2FAIL + independent review HOLD):
1. Existing sample validation accepts Fraction original_float then JSON fails.
   It also accepts original_float1.0 with rounded300 and wrong shape projection.
2. Existing aggregate checks accept node1/x_count99 or complete samples=[] after
   one correction. Missing samples/max/truncation consistency must reject.
3. Metadata allows path value0 instead of a string, and zarr_format3.0.
4. Two tests falsely treat no-op as corruption: fresh samples=[]->[] and existing
   absolute_delta45->45. Fix test ORACLES; do not make valid state fail.
5. Ruff I001 in top imports and test function. Put inspect at module top with
   stdlib. Use a single third-party group (numpy/pytest/biohub); this repo does
   not configure biohub as known first-party. All lines<=120, Ruff E/W/F/I/UP/B.
6. Original Flash clipping/telemetry and exact Fraction-ID defects are already
   corrected in source below; preserve those fixes.

Focused tests required (self-contained; pytest/numpy/Fraction/tmp_path allowed):
- Each axis lower/upper/exact limits, noncubic,size1, negative, ties-to-even.
  dim5 inputs4.49/4.5 yield4 no correction;4.5001 yields4 with correction1 peraxis.
  shape(4,1,30,500),z=-9.75/y=-1/x499.9 ->(0,0,499),counts all1,C1,max10.
- Full CSV schema/order/sentinels, valid fractional no correction, input immutability.
- All node/time/row IDs valid exact boundaries and invalid types/nonfinite/overflow;
  Fraction large exact/invalid fractional, np inputs. Coordinates bad types/nonfinite.
- Global sample budget:12 x corrections300..311/dim256 ->12samples/no trunc/max56.
  25 x corrections300..324 ->20samples/truncated/25counts/max69. Verify first20
  ordered events and multiaxis order; repeated row/node IDs still count per call.
- Create real corrupted reports from a valid generated report. Assert that each
  mutation actually changes the fixture, then reject atomically. Test malformed
  sample keys/types/Fraction/NaN, original-round inconsistency, clip/delta, wrong
  dataset/ID/time, missing complete samples, counts>N or ai>C, incorrect complete
  max/truncation and missing/extra fields. For NaN use appropriate non-equality
  snapshot checks. Invalid last-axis coordinate must leave report unchanged.
- Truncated positive fixture MUST accept aggregate max greater than visible20
  max (unretained later events may contain true max). Never demand equality there.
- Metadata root/child type/version/rank/order/dim failures, malformed path value/
  missing axes/datasets, exact duplicate0 within one entry and across entries,
  bad-axis duplicate not hidden, path0 secondentry/secondpath allowed.
- Three in-bounds coordinates at times0,1,2 with values0,4,4, shape spatialdim5:
  OLS evaluated at last observed t2 is14/3, rounds5 then clips4. Not future-time
  extrapolation. Demonstrates generic bounds need, NOT actual saved-node causality.
- No network/real data/model/GT evaluation in tests. Tests may create tmp metadata
  and inspect the delivered module when the parent RUNS them, but you use no tools.

Known unaccepted helper to correct:
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


def _is_python_int(value: object) -> bool:
    """True only for a genuine Python ``int`` (bool excluded)."""
    return type(value) is int


def _positive_rank4_shape(shape: object) -> tuple[int, int, int, int]:
    """Validate a rank-4 sequence of positive Python ints."""
    if not isinstance(shape, (list, tuple)) or len(shape) != 4:
        raise OutputBoundsError("array shape must be a rank-4 sequence")
    dims = []
    for axis, value in zip(AXIS_ORDER, shape, strict=True):
        if not _is_python_int(value):
            raise OutputBoundsError(f"{axis} dimension is not a Python int")
        if value <= 0:
            raise OutputBoundsError(f"{axis} dimension must be positive")
        dims.append(value)
    return dims[0], dims[1], dims[2], dims[3]


def _multiscales_entry_paths(entry: object) -> list | None:
    """Return the raw ``datasets[*]["path"]`` list for a multiscales entry."""
    if not isinstance(entry, dict):
        raise OutputBoundsError("multiscales entries must be JSON objects")
    datasets = entry.get("datasets")
    if not isinstance(datasets, list):
        raise OutputBoundsError("multiscales entries require a datasets list")
    paths = []
    for item in datasets:
        if not isinstance(item, dict) or "path" not in item:
            raise OutputBoundsError("multiscales dataset entries require a path")
        paths.append(item["path"])
    return paths


def _entry_axes_are_tzyx(entry: dict) -> bool:
    """True when the entry declares exactly T, Z, Y, X axes in that order."""
    axes = entry.get("axes")
    if not isinstance(axes, list) or len(axes) != 4:
        return False
    names = []
    for axis in axes:
        if not isinstance(axis, dict):
            return False
        name = axis.get("name")
        if not isinstance(name, str):
            return False
        names.append(name.upper())
    return names == list(AXIS_ORDER)


def read_output_shape(test_dir: str | Path, dataset: str) -> tuple[int, int, int, int]:
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

    entries = attributes["multiscales"]

    path_zero_total = 0
    for entry in entries:
        paths = _multiscales_entry_paths(entry)
        path_zero_total += sum(1 for path in paths if path == "0")
    if path_zero_total == 0:
        raise OutputBoundsError(f"no multiscales entry references dataset path '0' for {dataset}")
    if path_zero_total > 1:
        raise OutputBoundsError(f"ambiguous duplicate path '0' references for {dataset}")

    matching = [entry for entry in entries if any(path == "0" for path in _multiscales_entry_paths(entry))]
    if len(matching) != 1:
        raise OutputBoundsError(f"expected exactly one multiscales entry referencing path '0' for {dataset}")

    entry = matching[0]
    if not _entry_axes_are_tzyx(entry):
        raise OutputBoundsError(f"multiscales entry for path '0' must declare T,Z,Y,X axes for {dataset}")

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


def _validate_sample(sample: object, index: int) -> None:
    if not isinstance(sample, dict):
        raise OutputBoundsError(f"report samples[{index}] must be a dict")
    if set(sample) != set(CSV_SAMPLE_FIELDS):
        raise OutputBoundsError(f"report samples[{index}] fields do not match the sample schema")
    if not isinstance(sample["dataset"], str) or not sample["dataset"].strip():
        raise OutputBoundsError(f"report samples[{index}] dataset is invalid")
    for key in ("row_id", "node_id", "t", "rounded_int", "clipped_int", "signed_delta", "absolute_delta"):
        if not _is_python_int(sample[key]):
            raise OutputBoundsError(f"report samples[{index}] {key} must be a Python int")
    if sample["row_id"] < 0 or sample["node_id"] < 0 or sample["t"] < 0:
        raise OutputBoundsError(f"report samples[{index}] identifiers must be non-negative")
    if sample["axis"] not in COORD_AXES:
        raise OutputBoundsError(f"report samples[{index}] axis is invalid")
    original = sample["original_float"]
    if isinstance(original, bool) or not isinstance(original, Real):
        raise OutputBoundsError(f"report samples[{index}] original_float must be a real number")
    original_f = float(original)
    if original_f != original_f or original_f in (float("inf"), float("-inf")):
        raise OutputBoundsError(f"report samples[{index}] original_float must be finite")
    rounded, clipped = sample["rounded_int"], sample["clipped_int"]
    signed, absolute = sample["signed_delta"], sample["absolute_delta"]
    if signed != clipped - rounded:
        raise OutputBoundsError(f"report samples[{index}] signed_delta is inconsistent")
    if absolute != abs(signed):
        raise OutputBoundsError(f"report samples[{index}] absolute_delta is inconsistent")
    if absolute == 0:
        raise OutputBoundsError(f"report samples[{index}] records a non-correction")
    if rounded < 0 and clipped != 0:
        raise OutputBoundsError(f"report samples[{index}] lower clip is inconsistent")


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


def _validate_report(report: object, dataset: str, shape: tuple[int, int, int, int]) -> None:
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
    if report["sample_limit"] != SAMPLE_LIMIT:
        raise OutputBoundsError("report sample_limit is invalid")
    if not isinstance(report["samples_truncated"], bool):
        raise OutputBoundsError("report samples_truncated must be a bool")
    samples = report["samples"]
    if not isinstance(samples, list) or len(samples) > SAMPLE_LIMIT:
        raise OutputBoundsError("report samples must be a list bounded by the sample limit")
    for index, sample in enumerate(samples):
        _validate_sample(sample, index)
    corrected = report["corrected_nodes"]
    axis_total = sum(counts[axis] for axis in COORD_AXES)
    if corrected > report["node_count"]:
        raise OutputBoundsError("report corrected_nodes exceeds node_count")
    if axis_total < corrected:
        raise OutputBoundsError("report axis_counts are inconsistent with corrected_nodes")
    if len(samples) == SAMPLE_LIMIT and not report["samples_truncated"]:
        pass
    if report["samples_truncated"] and len(samples) != SAMPLE_LIMIT:
        raise OutputBoundsError("report samples_truncated is inconsistent with samples")
    max_seen = 0
    for sample in samples:
        if sample["dataset"] != dataset:
            raise OutputBoundsError("report sample dataset mismatch")
        if sample["absolute_delta"] > report["max_absolute_correction"]:
            raise OutputBoundsError("report max_absolute_correction is below its samples")
        max_seen = max(max_seen, sample["absolute_delta"])
    if report["max_absolute_correction"] < max_seen:
        raise OutputBoundsError("report max_absolute_correction is inconsistent")


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
        raise OutputBoundsError(f"{label} must be a real number, not {type(value).__name__}")
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
    t = _as_exact_int(node.get("t"), "t")
    if not 0 <= t < t_dim:
        raise OutputBoundsError(f"t={t} outside [0, T-1] for T={t_dim}")

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
        "t": t,
        "z": clipped["z"],
        "y": clipped["y"],
        "x": clipped["x"],
        "source_id": -1,
        "target_id": -1,
    }

    pending_samples = []
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
                "t": t,
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
    samples.extend(pending_samples[:max(room, 0)])
    report["node_count"] += 1
    if corrections:
        report["corrected_nodes"] += 1
        for axis in corrections:
            report["axis_counts"][axis] += 1
        if max_delta > report["max_absolute_correction"]:
            report["max_absolute_correction"] = max_delta
    return out
```

Known unaccepted tests to correct/extend:
```python
import copy
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


def write_metadata(tmp_path, dataset, shape=(100, 64, 256, 256), *, axes=None, extra_entries=(), child_node="array"):
    root = tmp_path / f"{dataset}.zarr"
    (root / "0").mkdir(parents=True)
    if axes is None:
        axes = TZYX
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


def report_for(dataset="demo", shape=SHAPE):
    return new_output_bounds_report(dataset, shape)


def node_row(**overrides):
    row = {"node_id": 1, "t": 1, "z": 5.2, "y": 5.2, "x": 5.2}
    row.update(overrides)
    return row


def entry(paths, axes=None):
    return {"axes": axes if axes is not None else TZYX, "datasets": [{"path": p} for p in paths]}


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


@pytest.mark.parametrize("version", [2, "3", None])
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


def test_read_output_shape_wrong_axis_order(tmp_path):
    swapped = [{"name": "T"}, {"name": "Y"}, {"name": "Z"}, {"name": "X"}]
    write_metadata(tmp_path, "demo", axes=swapped)
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_read_output_shape_axis_rank_mismatch(tmp_path):
    write_metadata(tmp_path, "demo", axes=[{"name": "T"}, {"name": "Z"}, {"name": "Y"}])
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_read_output_shape_lowercase_axes_accepted(tmp_path):
    write_metadata(tmp_path, "demo", axes=[{"name": "t"}, {"name": "z"}, {"name": "y"}, {"name": "x"}])
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
    write_metadata(tmp_path, "demo", extra_entries=[entry(["0", "0"])])
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_read_output_shape_duplicate_path_zero_across_entries(tmp_path):
    write_metadata(tmp_path, "demo", extra_entries=[entry(["0"])])
    with pytest.raises(OutputBoundsError):
        read_output_shape(tmp_path, "demo")


def test_duplicate_path_zero_in_wrong_axis_entry_is_not_hidden(tmp_path):
    wrong_axes = [{"name": "X"}, {"name": "Y"}, {"name": "Z"}, {"name": "T"}]
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


@pytest.mark.parametrize(("value", "expected", "corrected"), [(4.49, 4, 0), (4.5, 4, 0), (4.5001, 4, 1)])
def test_upper_rounding_ties_to_even_dim_five(value, expected, corrected):
    shape = (10, 5, 5, 5)
    report = new_output_bounds_report("tiny", shape)
    row = bounded_output_node(node_row(z=value, y=value, x=value), "tiny", 0, shape, report)
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
    row = bounded_output_node(node_row(t=2, z=-9.75, y=-1.0, x=499.9), "nc", 5, shape, report)
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
        bounded_output_node(node_row(node_id=Fraction(2**63, 1)), "demo", 0, SHAPE, report)
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
    row = bounded_output_node(node_row(z=-2.0, y=300.0, x=999.0), "demo", 4, SHAPE, report)
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
        bounded_output_node(node_row(node_id=index, x=300.0 + index), "demo", index, SHAPE, report)
    assert report["node_count"] == 12
    assert report["corrected_nodes"] == 12
    assert report["axis_counts"] == {"z": 0, "y": 0, "x": 12}
    assert len(report["samples"]) == 12
    assert report["samples_truncated"] is False
    assert report["max_absolute_correction"] == 56
    assert [s["row_id"] for s in report["samples"]] == list(range(12))
    assert [s["node_id"] for s in report["samples"]] == list(range(12))
    assert [s["original_float"] for s in report["samples"]] == [300.0 + i for i in range(12)]
    assert [s["signed_delta"] for s in report["samples"]] == [-(45 + i) for i in range(12)]
    assert json.dumps(report)


def test_more_than_twenty_corrections_truncate_samples_only():
    report = report_for()
    for index in range(25):
        bounded_output_node(node_row(node_id=index, x=300.0 + index), "demo", index, SHAPE, report)
    assert report["node_count"] == 25
    assert report["corrected_nodes"] == 25
    assert report["axis_counts"]["x"] == 25
    assert report["samples_truncated"] is True
    assert len(report["samples"]) == 20
    assert report["max_absolute_correction"] == 69
    assert [s["row_id"] for s in report["samples"]] == list(range(20))


def test_truncation_keeps_deterministic_first_twenty_order():
    def build():
        report = report_for()
        for index in range(25):
            bounded_output_node(node_row(node_id=index, x=300.0 + index), "demo", index, SHAPE, report)
        return report

    assert [s["row_id"] for s in build()["samples"]] == list(range(20))
    assert [s["axis"] for s in build()["samples"]] == ["x"] * 20


def test_sample_order_is_invocation_then_z_y_x():
    report = report_for()
    bounded_output_node(node_row(node_id=1, z=-1.0, y=300.0, x=5.0), "demo", 0, SHAPE, report)
    bounded_output_node(node_row(node_id=2, z=5.0, y=-1.0, x=300.0), "demo", 1, SHAPE, report)
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


@pytest.mark.parametrize("mutate", [
    lambda r: r.__setitem__("dataset", "other"),
    lambda r: r.__setitem__("shape", [100, 64, 256, 128]),
    lambda r: r.__setitem__("node_count", -1),
    lambda r: r.__setitem__("node_count", 1.5),
    lambda r: r.__setitem__("corrected_nodes", -1),
    lambda r: r.__setitem__("axis_counts", {"z": 0, "y": 0}),
    lambda r: r.__setitem__("axis_counts", {"z": 0, "y": 0, "x": 0, "t": 0}),
    lambda r: r.__setitem__("max_absolute_correction", 1.5),
    lambda r: r.__setitem__("samples", "corrupt"),
    lambda r: r.__setitem__("samples", []),
    lambda r: r.__setitem__("samples_truncated", "yes"),
    lambda r: r.__setitem__("sample_limit", 40),
    lambda r: r.pop("samples_truncated"),
    lambda r: r.__setitem__("extra", 1),
])
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

    for field, value in [("rounded_int", 299), ("clipped_int", 254), ("absolute_delta", 45)]:
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


@pytest.mark.parametrize("bad", [(100, 64, 256), (100, 64.0, 256, 256), (100, True, 256, 256)])
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
    import inspect

    source = inspect.getsource(module)
    assert "__future__" not in source


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
    row = bounded_output_node({"node_id": 1, "t": 2, "z": raw_end, "y": 1.0, "x": 1.0}, "ols", 0, dims, report)
    assert row["z"] == dims[1] - 1
    assert report["corrected_nodes"] == 1
    assert report["axis_counts"] == {"z": 1, "y": 0, "x": 0}
    assert report["max_absolute_correction"] == 1
    assert report["samples"][0]["rounded_int"] == 5
    assert report["samples"][0]["clipped_int"] == 4
    assert report["samples"][0]["signed_delta"] == -1
```

Return only HELPER and TESTS literal Python blocks. Keep implementation compact,
readable and focused on this contract; do not include unchanged notebook code.
