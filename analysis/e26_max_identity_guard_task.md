# E26 Max identity guard — single-function authoring unit

> 履歴・非運用・現行起動に使用禁止。この旧タスクは保存用です。
> 現行方針は [AGENTS.md](../AGENTS.md)、MAX評価入口は
> [評価手順](../.codex/runners/biohub_max_implementer.instructions.md) を参照。
> 以下のモデル指定・命令・実行例は当時の履歴であり、現在のworkerへ渡してはいけません。

The user directly requested qwen3.8-max and project progress in the CURRENT active
supervised coding turn. Parent closed validation-r2 HOLD after its one permitted
feedback; do not reopen/extend that unit. This new narrowly scoped unit implements
the independently diagnosed remaining guard, not a full module rewrite.
Existing subscription-only Token Plan, exact qwen3.8-max, effort none.
One authoring response; cap300 seconds; no tools/retry/fallback.
No notebook, graph, coordinates, assets, settings, routes, or other functions.

Parent and independent review confirmed156pytest PASS and RuffPASS after allowed
import-only formatting, BUT this is a real missing acceptance rule masked by test.
Source helper SHA256: 105ab91a8ebbdfd847817043b0364ec52dbca09404cfc09ca6e9540e6137e58c
Regression module SHA256: 25fc324570a181c8158b60ea728923a96e02595c13fa682cc5ba79b7ba9f8752

DELIVER exactly TWO labeled literal Python blocks; no extra text:
VALIDATION
```python
<complete def _validate_report ONLY; no imports/constants/other defs>
```
REGRESSION
```python
<complete def test_report_rejects_distinct_identity_count_exceeding_corrected ONLY>
```

Parent mechanically replaces exactly these two AST-defined functions, preserves
every other byte from frozen input modules, reads whole resulting diff, runs all
156 previous tests plus independent diagnostic, Ruff, independent acceptance.
No claims of tests run or performance improved.

REQUIRED CHANGE:
Inside _validate_report, after samples have validated via _validate_sample and
corrected_nodes is validated, require number of distinct visible
(row_id,node_id,t) combinations <= corrected_nodes.
Only a LOWER bound from retained samples; do NOT require equality, do NOT keep
unbounded history. IDs may repeat across multiple valid accepted calls.
No change to any other existing validation condition or public API.
Existing fields/constants/functions used below remain available.

The test currently removes the second sample and leaves max inconsistent.
It therefore passes for the wrong reason. Replace its body with non-vacuous
regression using existing _report(),_node(),SHAPE,copy,pytest,OutputBoundsError,
bounded_output_node available in module:
- Generate one valid call with node y=300.0 and x=300.0, using row0,node_id1,t1.
- Verify N=C=1; counts z0,y1,x1; two samples; max45; truncfalse.
- On a fresh deep copy for each desired distinct-ID variation, change only
  the SECOND sample's row_id or node_id or t to another valid value.
  Keep TWO samples and ALL counts,max,shape,deltas unchanged.
- Assert distinct identity count is2, while C1.
- Deepcopy malformed report immediately before calling bounded_output_node with
  a valid in-bounds node,row9.
- Require OutputBoundsError and report identical to snapshot after rejection.
  Preserve node and shape too.
- Positive control MUST accept the unmodified one-call/two-axis report on the
  next valid call, AND three corrected calls sharing identical row/node/t keys.
  This prevents accidental uniqueness/equality restrictions.
No no-op corruption, no removing samples, no changing aggregate totals/max.
Optional iterations over row_id/node_id/t occur inside this ONE test function.
No local helper definitions; do not add imports. Keep lines<=120, RuffE/W/F/I/UP/B.

CURRENT VALIDATION:
```python
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
    for sample in samples:
        visible_axis_counts[sample["axis"]] += 1
        visible_max = max(visible_max, sample["absolute_delta"])
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
```

CURRENT REGRESSION:
```python
def test_report_rejects_distinct_identity_count_exceeding_corrected():
    report = _report()
    bounded_output_node(_node(x=300.0), "demo", 0, SHAPE, report)
    bounded_output_node(_node(x=301.0), "demo", 1, SHAPE, report)
    assert report["corrected_nodes"] == 2
    broken = copy.deepcopy(report)
    broken["corrected_nodes"] = 1
    broken["node_count"] = 2
    broken["axis_counts"] = {"z": 0, "y": 0, "x": 1}
    broken["max_absolute_correction"] = report["max_absolute_correction"]
    broken["samples"] = broken["samples"][:1]
    with pytest.raises(OutputBoundsError):
        bounded_output_node(_node(), "demo", 9, SHAPE, broken)
```
