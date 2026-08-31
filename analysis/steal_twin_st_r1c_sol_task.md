# SOL implementation task: twin-only ST-R1c pipeline dry-run integration

Implement **only ST-R1c** in the clean linked worktree supplied by the
launcher.  This is the final integration slice of ST-R1.  It wires the already
reviewed R1a strict scorer and the already reviewed R1b immutable planner into
the post-processing pipeline, but it never applies a planned rewire.

This handoff is binding and self-contained for the implementation run.  Read
`AGENTS.md` completely before editing.  Do not use network, Kaggle, official
metrics, notebooks, or data-heavy jobs.  Do not commit, branch, push, or edit
analysis documents during implementation.

## 1. Required base and stop conditions

The expected implementation base is `develop@cb206e8`, where the reviewed R1b
worktree was adopted.  It must contain the current R1a interface and the current
reviewed R1b interface.  Before editing,
verify all of the following exact symbols in
`src/biohub/public_postproc/divisions.py`:

```python
@dataclass(frozen=True)
class TwinDeepCenterDecision:
    accepted: bool
    raw_score: float | None
    reason: str | None

@dataclass(frozen=True)
class TwinSnapshotNode:
    node_id: int
    t: int
    z: float
    y: float
    x: float
    gap_synthetic: bool

type TwinScoreCallback = Callable[[TwinSnapshotNode], TwinDeepCenterDecision]

def plan_twin_only_v1(
    cfg: PostprocConfig,
    dataset: str | None,
    node_rows: Sequence[Mapping[str, object]],
    edge_rows: Sequence[Mapping[str, object]],
    score_callback: TwinScoreCallback,
) -> TwinPlan:
    ...

def score_twin_deepcenter(
    cfg: PostprocConfig,
    dataset: str | None,
    t: int,
    point: tuple[float, float, float],
    detector_bundle: dict[str, object] | None,
    frame_cache: dict[int, np.ndarray],
    heatmap_cache: dict[tuple[str, int], np.ndarray],
) -> TwinDeepCenterDecision:
    ...
```

The R1b file must also expose the existing immutable result classes
`TwinFrozenMapping`, `TwinFrozenDType`, `TwinFrozenStructuredScalar`,
`TwinFrozenNumpyScalar`, `TwinFrozenArray`, `TwinFrozenBuffer`,
`TwinEdgeRecord`, `TwinPlannedEdge`, `TwinDebugRecord`, and `TwinPlan`, plus the
48-key tuple `_TWIN_COUNTER_KEYS` in the order frozen below.  The expected
reviewed R1b production-file SHA256 is:

```text
3009d182b71dd786f1249e17734b2e6dea70e2260b752f6227e810643efb59f4
```

That hash is also the adopted production file at `develop@cb206e8`.  If the
symbols, fields, signatures, hash, or counter order differ, **stop and report
the dependency mismatch**.
Do not repair, rename, broaden, or reimplement R1a/R1b in this task.  In
particular, do not invent another planner, callback signature, plan field,
counter, debug-record field, or serialization helper in `divisions.py`.

## 2. Allowed files and explicit exclusions

Modify only:

- `src/biohub/public_postproc/pipeline.py`
- `tests/test_public_postproc.py`

Do not modify `config.py`, `deepcenter.py`, `divisions.py`, `graph_ops.py`,
`csv_out.py`, CLI code, `official/`, notebooks, data, outputs, or any other
file.  R1a already owns config/provenance/scoring.  R1b already owns validation,
candidate construction, deterministic resolution, counters, and immutable
debug-ready records.

The following are explicitly out of scope:

- ST-R2 graph mutation, including removing `Q->B`, adding `P->B`, changing edge
  metadata, applying a plan, or adding mutation/delta/`2k` tests;
- ST-R3 metric/evaluation logic, manifests, receipts, promotion gates, runtime
  or RSS measurement, GT access, official imports, or any evaluation command;
- network, Kaggle API/CLI, submissions, downloads, uploads, or remote state;
- changes to the existing fail-open DeepCenter repair helper;
- any `disposable_steal` mode, fallback, or telemetry.

## 3. Frozen counter schema and merge ownership

Append all of these keys, in this exact order, to the mapping returned by
`new_stats()`, initialized to built-in integer zero:

```text
steal_twin_examined_frames
steal_twin_p_pool
steal_twin_q_pool
steal_twin_enumerated
steal_twin_rejected_distance_twin
steal_twin_rejected_ambiguous_p_nn
steal_twin_rejected_ambiguous_q_nn
steal_twin_rejected_not_mutual_parent_nn
steal_twin_rejected_distance_existing_child
steal_twin_rejected_distance_parent
steal_twin_rejected_distance_sister_low
steal_twin_rejected_distance_sister_high
steal_twin_rejected_time
steal_twin_rejected_missing_successor
steal_twin_rejected_shared_successor
steal_twin_rejected_divergence
steal_twin_rejected_synthetic
steal_twin_rejected_deepcenter_bundle
steal_twin_rejected_deepcenter_dataset
steal_twin_rejected_deepcenter_frame
steal_twin_rejected_deepcenter_heatmap
steal_twin_rejected_deepcenter_nonfinite
steal_twin_rejected_deepcenter_threshold
steal_twin_eligible
steal_twin_rejected_conflict
steal_twin_rejected_frame_cap
steal_twin_rejected_video_cap
steal_twin_accepted
steal_twin_planned_edges_removed
steal_twin_planned_edges_added
steal_twin_edges_removed
steal_twin_edges_added
steal_twin_isolated_donors
steal_twin_validation_failed
steal_twin_validation_missing_node_field
steal_twin_validation_invalid_node_id
steal_twin_validation_duplicate_node_id
steal_twin_validation_invalid_node_time
steal_twin_validation_nonfinite_node_coordinate
steal_twin_validation_invalid_edge_endpoint
steal_twin_validation_dangling_edge
steal_twin_validation_duplicate_edge
steal_twin_validation_nonconsecutive_edge
steal_twin_validation_indegree
steal_twin_validation_outdegree
steal_twin_validation_nonfinite_edge_distance
steal_twin_debug_records_written
steal_twin_debug_records_dropped
```

Import the reviewed package-private tuple `_TWIN_COUNTER_KEYS`; do not copy a
second production tuple with independent spelling or order.  This task accepts
that package-internal dependency deliberately.  `new_stats()` must append
`dict.fromkeys(_TWIN_COUNTER_KEYS, 0)` after the existing keys so existing
counter order stays unchanged and the twin keys follow it exactly.

The pipeline adapter must validate the R1b result before merging:

1. `tuple(plan.counters) == _TWIN_COUNTER_KEYS` exactly;
2. every value has `type(value) is int` and is nonnegative;
3. both planner-owned debug counters are zero before allocation;
4. every target twin key exists in `stats` and is still zero.

Any violation is a `RuntimeError` and aborts the run.  Merge by assignment,
not `+=`: each planner invocation owns the complete per-dataset twin counter
mapping.  After the merge, replace only
`steal_twin_debug_records_written/dropped` with the collector's allocation for
that dataset.  If no debug path is configured, those two values remain zero.
Do not modify any non-twin counter.

## 4. Exact dry-run guard and public-call compatibility

Add an internal helper equivalent to:

```python
def _require_steal_twin_r1_dry_run(cfg: PostprocConfig) -> None:
    if cfg.OUTPUT_STEAL_TWIN_REWIRE and not cfg.STEAL_TWIN_DRY_RUN:
        raise RuntimeError(
            "twin_only_v1 graph mutation is unavailable in ST-R1; "
            "set BIOHUB_STEAL_TWIN_DRY_RUN=1 or implement ST-R2"
        )
```

The message may add context but must contain `ST-R1`, `ST-R2`, and
`BIOHUB_STEAL_TWIN_DRY_RUN=1`.  The guard must run:

- at the very start of `filter_output_graph_pre_linefit`, before `new_stats`,
  centroid refinement, cache creation, or any graph pass;
- in `run_postproc` after the read-only sorted GEFF discovery/nonempty check but
  before detector loading, directory creation, or output opening;
- in `save_prelinefit_checkpoint` after the read-only sorted GEFF
  discovery/nonempty check but before detector loading or checkpoint-directory
  creation.

When the master switch is false, this helper does nothing.  The off path must
not inspect or validate the twin debug path, call a planner/scorer/collector,
or perform twin I/O.

Preserve all existing positional call compatibility.  Extend the two filter
functions only with a final keyword-only internal argument:

```python
def filter_output_graph_pre_linefit(
    cfg: PostprocConfig,
    nodes_by_id: dict[int, dict[str, object]],
    raw_edges: list[dict[str, object]],
    dataset: str | None = None,
    deepcenter_bundle: dict[str, object] | None = None,
    *,
    twin_debug_collector: _TwinDebugCollector | None = None,
) -> tuple[dict[int, dict[str, object]], list[dict[str, object]], dict[str, int]]:
    ...

def filter_output_graph(
    cfg: PostprocConfig,
    nodes_by_id: dict[int, dict[str, object]],
    raw_edges: list[dict[str, object]],
    dataset: str | None = None,
    deepcenter_bundle: dict[str, object] | None = None,
    *,
    twin_debug_collector: _TwinDebugCollector | None = None,
) -> tuple[dict[int, dict[str, object]], list[dict[str, object]], dict[str, int]]:
    ...
```

`filter_output_graph` passes that exact collector object through to the
pre-linefit function.  Do not add it to `run_relinefit`: a pre-linefit
checkpoint already contains final R1 telemetry and must not replan, reallocate,
or republish debug data.

If all three conditions below hold, a direct filter call must raise a clear
`RuntimeError` before any graph pass or planner call:

```text
OUTPUT_STEAL_TWIN_REWIRE is true
STEAL_TWIN_DEBUG_JSONL is nonempty
twin_debug_collector is None
```

Do not reject or call a supplied collector when the master is off.  Do not call
a supplied collector when the debug path is empty.

## 5. Exact hook order and strict R1a closure

Add one internal adapter, preferably named `_run_steal_twin_r1_dry_run`, with no
graph return value.  It receives the current config, dataset, current
`nodes_by_id`, current `edges`, `stats`, detector bundle, the existing shared
frame cache, the existing shared heatmap cache, and optional collector.  It may
merge stats and allocate debug records; it must not edit, replace, reorder, or
retain the caller's node/edge containers or rows.

Invoke it at exactly this point in `filter_output_graph_pre_linefit`:

```text
refine_all_centroids (when enabled)
raw edge filtering / motion relink / parent repair / child repair
close_single_frame_gaps
recover_strict_gap2
add_safe_divisions_postlink
ST-R1c dry-run adapter                 <-- exactly here
division geometry filter
isolated-node pruning
short-track filtering
return pre-linefit checkpoint
linefit smoothing (filter_output_graph only)
```

The closure passed to the existing `plan_twin_only_v1` must be exactly
equivalent to:

```python
def score_callback(node: TwinSnapshotNode) -> TwinDeepCenterDecision:
    return score_twin_deepcenter(
        cfg,
        dataset,
        node.t,
        (node.z, node.y, node.x),
        deepcenter_bundle,
        repair_frame_cache,
        deepcenter_heatmap_cache,
    )
```

Do not catch or remap exceptions in this closure; R1b owns callback
normalization/fail-closed mapping.  Do not call the scorer before the planner,
score any role other than the `TwinSnapshotNode` supplied by R1b, or create a
new cache.  The two cache arguments must be the identical objects already
created before `close_single_frame_gaps` and passed to
`add_safe_divisions_postlink`.

Call the planner exactly once with:

```python
plan_twin_only_v1(
    cfg,
    dataset,
    tuple(nodes_by_id.values()),
    tuple(edges),
    score_callback,
)
```

R1b performs its own detached immutable snapshot.  Do not pre-sort, deep-copy,
normalize, or convert rows and do not pass the node mapping or stats object.
The adapter must never inspect `accepted_candidates` to apply a mutation.

## 6. GEFF loader duplicate hard failure

In `_load_geff_as_dicts`, before assigning a node row, check whether its
canonical `int(row["node_id"])` already exists in `nodes_by_id`.  A duplicate
must raise:

```python
ValueError(f"{geff_path}: duplicate node_id {node_id}")
```

The path text and duplicate integer must both be present.  Check before the
second assignment, so the first row is never silently overwritten.  This is a
loader hard failure and no partial node mapping is returned.  Do not weaken the
R1b direct-row `duplicate_node_id` validation; the loader and planner cover
different entry points.

## 7. Canonical JSON record schema

R1b returns `TwinDebugRecord` values, not dictionaries.  Convert every retained
record to this exact top-level JSON object without reading the live graph:

```text
{
  "dataset": record.dataset,
  "decision": record.decision,
  "reason": record.reason,
  "p": record.p,
  "q": record.q,
  "a": record.a,
  "b": record.b,
  "a2": record.a2,
  "b2": record.b2,
  "sort_key": list(record.sort_key),
  "d_pq": record.d_pq,
  "d_pa": record.d_pa,
  "d_pb": record.d_pb,
  "d_ab": record.d_ab,
  "d_a2b2": record.d_a2b2,
  "divergence_growth": record.divergence_growth,
  "raw_deepcenter_score": record.raw_deepcenter_score,
  "deepcenter_threshold": record.deepcenter_threshold,
  "deepcenter_decision": {
    "accepted": record.deepcenter_decision.accepted,
    "raw_score": record.deepcenter_decision.raw_score,
    "reason": record.deepcenter_decision.reason
  },
  "removed_edge": {
    "source_id": record.removed_edge.source_id,
    "target_id": record.removed_edge.target_id,
    "metadata": <canonical frozen-value encoding below>
  },
  "planned_edge": {
    "source_id": record.planned_edge.source_id,
    "target_id": record.planned_edge.target_id,
    "distance_um": record.planned_edge.distance_um,
    "edge_prob": null
  }
}
```

Use lowercase role keys exactly as above.  Do not add model path, checkpoint
path, epoch, weights, credentials, wall time, host data, input ordinals, or
graph mutations.  The common validation in section 8 applies to **every**
supplied record before capacity allocation, including records that will be
dropped.  Only retained records enter the recursive metadata codec and line
encoding below.  An incompatible record raises `TypeError` or `ValueError`
before any collector state changes or JSONL target is touched.

### 7.1 Lossless encoding of R1b frozen metadata

The complete `removed_edge.metadata` may contain every frozen type that R1b
supports.  It is not valid to call `dict(...)`, `dataclasses.asdict`, `repr`,
`str`, `tolist`, or a JSON `default=` fallback: those approaches lose non-string
keys, tuple/set/type distinctions, dtype metadata, array bytes, or
determinism.  Implement one private recursive converter with the following
exact tagged representation.  Reject any unlisted type.

Primitive values:

- `None`, exact `bool`, exact `int`, and exact `str`: encode directly.
- finite exact `float`: encode directly;
- nonfinite exact `float`: encode as
  `{"__twin_type__":"float","value":"nan","bits_hex":<16 hex chars>}`,
  with value `"+inf"` or `"-inf"` for infinities.  `bits_hex` is the lowercase
  hexadecimal result of `struct.pack(">d", value).hex()`, so signed NaNs and
  NaN payloads are not collapsed;
- exact `complex`: encode as
  `{"__twin_type__":"complex","real":<float encoding>,"imag":<float encoding>}`;
- exact `bytes`: encode as
  `{"__twin_type__":"bytes","hex":value.hex()}`.

Containers:

- `tuple`: `{"__twin_type__":"tuple","items":[...recursive values...]}`;
- `frozenset`: `{"__twin_type__":"frozenset","items":[...]}` where the
  already-converted elements are sorted by their own canonical JSON encoding
  using the same `sort_keys`, separators, and `allow_nan=False` settings;
- `TwinFrozenMapping`:
  `{"__twin_type__":"mapping","items":[[key,value],...]}` with each key and
  value recursively converted, preserving `items_snapshot` order.  Never turn
  it into a JSON object because keys need not be strings.

`TwinFrozenMapping.items_snapshot` order is part of the lossless frozen value;
do not sort it.  In this contract, two independently constructed records are
"equivalent" for byte-identity only when their complete frozen snapshots are
equal, including the item order of every nested `TwinFrozenMapping`, tuple
order, dtype descriptor/metadata order, array content, and buffer content.
Mappings containing the same key/value pairs in a different `items_snapshot`
order are intentionally different frozen snapshots and must produce different
tagged `items` arrays and different JSONL bytes.  `frozenset` is the sole
container here whose iteration/construction order is discarded by canonical
element sorting; two equal frozensets built in different orders must encode to
the same bytes.

Frozen NumPy/buffer values:

- `TwinFrozenDType`: tag `"numpy_dtype"` and include fields `string`,
  `descriptor`, `metadata`, `itemsize`, `alignment`, `byteorder`, `names`,
  `hasobject`, and `aligned_struct`; recursively encode `descriptor` and
  `metadata`, and encode `names` as JSON `null` or a list of strings;
- `TwinFrozenStructuredScalar`: tag `"numpy_structured_scalar"` and encode
  `fields` as an ordered list of `[name, recursive_value]` pairs;
- `TwinFrozenNumpyScalar`: tag `"numpy_scalar"`, recursively encode `dtype`,
  and encode `content` as lowercase hex;
- `TwinFrozenArray`: tag `"numpy_array"`; include recursively encoded `dtype`,
  `shape` and `strides` as integer lists, `c_contiguous`, `f_contiguous`, and
  `object_content`; when `content` is bytes use `content_hex`, otherwise use
  `content` as a recursively encoded tuple, with exactly one of those two keys;
- `TwinFrozenBuffer`: tag `"buffer"`; include `kind`, `format`, `itemsize`,
  `shape`, `strides`, `readonly`, and lowercase `content_hex`.

This codec is lossless relative to the reviewed immutable R1b snapshot.  It
also ensures metadata NaN/Inf cannot bypass the required `allow_nan=False`.
Do not broaden the codec to arbitrary dataclasses or Python/NumPy objects.  Do
not add an inverse decoder or reconstruction API to production: ST-R1c only
needs the deterministic forward conversion to a tagged plain JSON value.

The final line encoding is exactly:

```python
json.dumps(
    plain_record,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
) + "\n"
```

Use default `ensure_ascii=True`; do not pass indentation or append spaces.

## 8. Exact bounded run-level collector API

Add one internal class with this exact externally testable shape:

```python
class _TwinDebugCollector:
    def __init__(self, max_records: int) -> None: ...
    def allocate(self, records: Sequence[TwinDebugRecord]) -> tuple[int, int]: ...
    def finalize(self, output_path: Path) -> None: ...

    @property
    def records_written(self) -> int: ...

    @property
    def records_dropped(self) -> int: ...
```

`max_records` must have `type(max_records) is int` and be nonnegative; otherwise
raise `ValueError`.  Production always constructs it with the already frozen
`cfg.STEAL_TWIN_DEBUG_MAX_RECORDS == 200`.  Unit tests may construct a smaller
capacity.

`allocate` is single-threaded and online.  It performs these steps in exact
order:

1. reject calls after successful finalization;
2. require `records` to be a `Sequence`; an empty sequence is valid;
3. walk **all** records in supplied index order and apply the common structural
   validation below, without consulting remaining capacity;
4. only after every record passes, retain the first
   `min(len(records), remaining_capacity)` in supplied order and classify the
   rest as dropped;
5. canonicalize and encode each retained record into a local list of line
   strings; do not recursively traverse or encode dropped metadata;
6. only after every retained line encodes successfully, extend the in-memory
   collector buffer, update cumulative counts, and return this call's
   `(written, dropped)`.

The common validation for every supplied record is exact and ordered.  For
each index, finish all checks below before moving to the next record:

1. the value has exact reviewed type `TwinDebugRecord`;
2. `dataset` is `None` or exact `str`, and every record in one nonempty call has
   the same dataset value as its first record;
3. `decision` is exact `str` and is either `"accepted"` with `reason is None`,
   or `"rejected"` with exact-string reason `"conflict"`, `"frame_cap"`, or
   `"video_cap"`;
4. each role `p,q,a,b,a2,b2` has exact type `int` (not `bool`);
5. `sort_key` is an exact tuple of length nine; its first three values have
   exact type `float` and are finite, its final six values have exact type
   `int`, and those six integers equal `(p,q,a,b,a2,b2)` in order;
6. `d_pq,d_pa,d_pb,d_ab,d_a2b2,divergence_growth`,
   `raw_deepcenter_score`, and `deepcenter_threshold` each have exact type
   `float` and are finite, and `deepcenter_threshold == 0.12`;
7. `deepcenter_decision` has exact type `TwinDeepCenterDecision`, has
   `accepted is True`, exact finite-float `raw_score` equal to
   `raw_deepcenter_score`, and `reason is None`;
8. `removed_edge` has exact type `TwinEdgeRecord`, exact-int endpoints, and
   exact `TwinFrozenMapping` metadata; its endpoints equal `(q,b)`;
9. `planned_edge` has exact type `TwinPlannedEdge`, exact-int endpoints, exact
   finite-float `distance_um`, and `edge_prob is None`; its source/target and
   distance equal `p`, `b`, and `d_pb`, respectively.

These checks deliberately do not recursively walk `removed_edge.metadata` for
a dropped record.  R1b owns construction of the frozen snapshot; the recursive
codec validates every nested value of each retained record.  Capacity zero
does not bypass common validation: a malformed record still raises even though
no record could be retained.  Here, "malformed" means a common envelope failure
listed above.  An exact `TwinFrozenMapping` envelope containing an unsupported
manually forged nested value is a codec failure only if that record is retained;
when dropped, its nested metadata is intentionally not traversed.

Use `TypeError` for a wrong container/record/field type and `ValueError` for a
wrong length, nonfinite numeric value, invalid enum/reason, cross-field
mismatch, or mixed dataset.  The error message must name the zero-based record
index and failing field/category.  The already-finalized check remains the
preceding `RuntimeError` and performs no record inspection.

Each `allocate` call is atomic with respect to collector state.  If common
validation or retained-record encoding raises, the buffer and both cumulative
counts remain exactly unchanged.  Dropped records receive every common check
above, not merely type/dataset/decision checks, but are never recursively
encoded or retained.

The number of retained line strings is never greater than `max_records`.
There is no per-dataset reset and no final resort.  Dataset order comes from
the existing `sorted(geff_dir.glob("*.geff"))` loops, and record order comes
from R1b's complete sort order.  Do not buffer dropped records.  Do not add a
byte cap, random sampling, timestamp, process ID, hash-random iteration, or
threading.

For each enabled dataset, call `allocate(plan.debug_records)` immediately after
the complete counter merge and before division geometry, pruning, short-track
filtering, `_dataset_stats_row`, CSV stats serialization, or checkpoint pickle
serialization.  Store the returned per-call values in that dataset's two debug
counters.  Because encoding happens in `allocate`, an encoding error aborts
before that dataset's stats/checkpoint is serialized.

`run_postproc` and `save_prelinefit_checkpoint` each create exactly one
collector for the whole run only when both the master switch is true and
`STEAL_TWIN_DEBUG_JSONL` is nonempty.  They pass the identical collector to
every sorted dataset.  With an empty path they create none.  With the master
off they do not even inspect the path.

## 9. Atomic JSONL publication and failure semantics

`finalize(output_path)` may be called exactly once after all datasets and all
ordinary run artifacts have succeeded:

- in `run_postproc`, after the output CSV has closed successfully and
  `_finish_run`/`write_run_stats` has returned successfully;
- in `save_prelinefit_checkpoint`, after every dataset pickle has closed
  successfully and `manifest.json` has been written successfully.

Create the parent directory at finalization time.  Create a uniquely named
temporary regular file in the same directory as the target, write all retained
line strings once in order using UTF-8 and `newline=""`, `flush`, call
`os.fsync` on the open temporary file, close it, and call
`os.replace(temp_path, output_path)`.  Never open the target directly and never
append.  A zero-record successful run atomically publishes a zero-byte file.

The exact commit/failure boundary is:

- before `os.replace` succeeds, the configured target is untouched;
- on any handled parent creation, temp creation, write, flush, fsync, close, or
  replace exception, propagate the original exception and remove the temporary
  file best-effort if one was created; an existing target retains its old bytes;
- successful `os.replace` is the sole JSONL commit point.  Mark the collector
  finalized and return without a later fallible durability operation;
- a second `finalize`, or any later `allocate`, raises `RuntimeError` and does
  not touch the published file.

`finalize` is transactional with respect to collector state as well as the
target.  It must not clear or rewrite buffered lines or change
`records_written/records_dropped`.  Set the finalized flag only after
`os.replace` succeeds.  If parent-directory creation, temp-file creation,
write, flush, file fsync, close, or replace fails, the collector remains
unfinalized with the identical buffer and cumulative counters, so restoring the
fault and calling `finalize` again on the **same collector** publishes the
original buffered bytes successfully.

Track whether a temporary path was actually created.  On any failure after
creation, attempt to close any still-open handle and unlink that exact temp
path best-effort.  Preserve and re-raise the first operational exception from
the phase under test; a secondary close/unlink cleanup exception must never
replace or mask it.  When cleanup succeeds, no matching temp file remains.  If
cleanup itself is injected to fail, a temp file may remain as the already
documented best-effort limitation, but the original operational exception,
old target bytes, collector buffer/counters, and unfinalized/retryable state
remain unchanged.  The implementation must not claim temp cleanup succeeded in
that case.

Do not require a parent-directory fsync: a failure after a successful replace
would make it impossible to preserve the promised failure boundary.  Crash
durability beyond atomic same-filesystem replacement is not claimed.  A hard
process kill may leave an unreferenced temp file, but must never expose a
partial target.  Atomicity here applies only to the debug JSONL; this task does
not redesign the existing CSV, run-stats, pickle, or manifest writers.

Before detector loading or output creation, reject a configured debug target
that aliases another artifact in the same run.  Compute both:

```python
debug_resolved = debug_path.resolve(strict=False)
debug_parent_resolved = debug_path.parent.resolve(strict=False)
debug_entry_resolved = debug_parent_resolved / debug_path.name
```

`debug_resolved` follows an existing final-component symlink, while
`debug_entry_resolved` identifies the directory entry that `os.replace` would
replace without following that final symlink.  Both identities matter.  For
ordinary file artifacts, alias comparison means either debug identity equals
the resolved artifact, or `os.path.samefile` when both paths already exist
(handle a samefile `OSError` as non-equality, not as permission to skip the
resolved-path comparisons):

- for `run_postproc`: any input GEFF, `out_csv`, or the effective
  `run_stats_path`;
- for `save_prelinefit_checkpoint`: any input GEFF, `checkpoint_dir` itself,
  `checkpoint_dir/manifest.json`, or any planned
  `checkpoint_dir/<dataset>.pkl`.

Protect the complete input bundle before considering individual GEFF entries.
Resolve `geff_dir` itself with `geff_dir.resolve(strict=True)` and require the
result to be a directory.  Reject when either `debug_resolved` or
`debug_entry_resolved` equals that resolved bundle root or is any descendant of
it.  This rule intentionally rejects a debug target that is merely a sibling of
one `*.geff` but still lies anywhere inside the input bundle: publishing a JSONL
there would mutate the input inventory and could affect later `*.geff`
discovery.  It also covers a `geff_dir` symlink because comparisons use its
resolved directory and the resolved debug entry/target identities.

Input GEFF paths need a stronger tree rule because a GEFF is normally a
directory and may itself be reached through a symlink.  Resolve each discovered
GEFF with `geff_path.resolve(strict=True)` before detector/output activity:

- if the resolved GEFF is a directory, reject when either `debug_resolved` or
  `debug_entry_resolved` is equal to that directory **or is any descendant of
  it**, using `is_relative_to(geff_resolved)`; this protects both the final
  symlink target and the directory entry/temp-file parent in the complete GEFF
  tree, not just its root name;
- if the resolved GEFF is a regular file, treat it as a leaf artifact: reject
  either debug-identity equality or existing-file `os.path.samefile`; a sibling
  path is allowed only when it is outside the resolved input bundle and is
  otherwise unrelated.  A sibling located inside the bundle was already
  rejected by the bundle rule above; there is no per-file descendant rule;
- a symlink to a GEFF directory uses the directory/tree rule after resolution,
  and a symlink to a regular-file GEFF uses the leaf rule.  A debug symlink or
  a debug path below a symlinked GEFF directory is therefore rejected based on
  resolved locations.  A debug leaf symlink physically located inside a GEFF
  tree but pointing outside is also rejected because replacing that leaf and
  creating its same-directory temp file would still modify the GEFF tree.

Do not use lexical `str.startswith`, unresolved `Path.parent`, or only
`debug_path == geff_path`; each misses sibling-prefix or symlink cases.  A
failure to strictly resolve a discovered GEFF propagates before detector/output
activity and is not treated as proof that aliasing is safe.

Raise `ValueError` naming both the debug target and conflicting artifact.  An
unrelated pre-existing debug target is valid and is replaced only after a
successful run.

If any dataset load, planner, downstream pass, CSV/checkpoint write, stats or
manifest write fails, do not call `finalize`; discard the in-memory collector
by unwinding.  The old JSONL remains unchanged and no new configured JSONL is
published.

## 10. Required integration tests

Append focused tests named `test_steal_twin_r1c_*`.  Do not reorganize, weaken,
or delete R1a/R1b or existing pipeline tests.  Use synthetic in-memory rows,
temporary paths, and deterministic monkeypatches only.  No real DeepCenter
checkpoint, image dataset, GEFF corpus, official metric, subprocess, or network
is needed.

Cover every item below.

### 10.1 Schema, guard, loader, and exact placement

- `new_stats()` ends with exactly `_TWIN_COUNTER_KEYS`, every value is exact
  integer zero, and earlier keys/order remain unchanged.
- Master off with a nonempty debug path does not call the guard's error branch,
  planner, scorer, collector, or twin I/O.
- Master on plus `DRY_RUN=False` raises at direct pre-linefit/full-filter,
  `run_postproc`, and `save_prelinefit_checkpoint` entry before detector load,
  directory/output creation, graph pass, planner, or collector construction.
- Master on, dry-run true, nonempty debug path, and no collector raises before
  all graph passes.  An empty path does not require a collector, and an
  explicitly supplied collector is not called when that path is empty.
- A monkeypatched call-order trace proves the planner runs once immediately
  after `add_safe_divisions_postlink` and before division geometry, isolated
  pruning, short-track filtering, and linefit.
- The planner spy receives tuple row sequences and no stats/mapping object.  It
  invokes its supplied callback with a known `TwinSnapshotNode`; the scorer spy
  receives B's exact `t/(z,y,x)`, detector bundle, and the same frame/heatmap
  cache object identities seen by gap-close and safe-division.
- A duplicate canonical node ID from a mocked GEFF loader raises the exact
  loader `ValueError` before overwrite.  Unique rows retain current behavior.

### 10.2 Counter merge and pre-serialization timing

- A valid R1b plan copies every counter exactly; allocation replaces only the
  two debug counts with the per-dataset values.
- A validation-failed plan preserves its one validation reason counters and
  leaves all other planner/debug values zero while downstream dry-run continues.
- Missing/extra/reordered counter keys, bool/negative/non-int values, a nonzero
  planner debug count, or a nonzero preseed destination fails atomically with
  `RuntimeError` before collector allocation.
- In both run paths, spies inside `_dataset_stats_row`, pickle serialization,
  and run-stats serialization see final per-dataset written/dropped counters.
  Their sums equal collector cumulative totals and the final JSONL line count.

### 10.3 Canonical codec, global capacity, and deterministic bytes

- An exact expected JSON object/line for one accepted record and each
  resolution reason, including all role, sort, distance, DeepCenter,
  removed-edge, and planned-edge fields.
- For nested `TwinFrozenMapping` with non-string keys, tuple, frozenset under
  construction-order variation, bytes, complex and nonfinite metadata floats
  (including distinct NaN bit patterns), and every frozen
  dtype/scalar/array/structured-scalar/buffer representation supported by R1b,
  assert `json.loads(encoded_line) == exact_expected_tagged_plain_object`.
  Then encode the same immutable record again and assert exact byte replay.
  Do not implement or test a production inverse decoder.  Assert the separate
  snapshot `input_position` ordinal does not leak, while a caller-owned
  metadata key also named `input_position` remains intact.
- Two independently constructed records with the same complete frozen snapshot,
  including identical nested mapping item order, and repeated encodes/runs
  produce byte-identical JSONL.  Unicode uses the frozen default escaped form.
- Separately prove that reversing `TwinFrozenMapping.items_snapshot` order while
  keeping the same key/value pairs preserves that reversed order in the tagged
  plain object and intentionally changes the JSONL bytes.  In a distinct test,
  construct equal frozensets through different insertion/iteration orders and
  prove canonical element sorting produces the same tagged object and bytes.
- A capacity-two collector allocated records in dataset order `a`, `b`, `c`
  retains the first two globally, returns exact per-call written/dropped values,
  and reports exact cumulative totals.  It never serializes or retains dropped
  records.
- Capacity zero, empty records, malformed/incompatible records, second
  finalization, and allocation after finalization have exact fail-closed
  behavior.  Parameterize every common structural/numeric failure against both
  available capacity and capacity zero; malformed would-be-dropped records must
  still raise, leave buffer/written/dropped state unchanged, and create no file.
- Separately forge a valid common envelope whose `TwinFrozenMapping` contains
  an unsupported nested value: it raises during retained codec encoding, while
  capacity zero returns `(0, 1)` and increments only the dropped total without
  traversing metadata.  The retained codec failure leaves all collector state
  unchanged.

### 10.4 Run ownership and atomic failures

- `run_postproc` constructs one collector, reuses its identity across sorted
  GEFF datasets, finalizes only after CSV close and successful run-stats write,
  and replaces rather than appends a stale target.
- `save_prelinefit_checkpoint` does the same across sorted datasets and
  finalizes only after all pickle files and manifest succeed.
- A failure on the second dataset, downstream filter, CSV writer, stats writer,
  pickle dump, or manifest write leaves a pre-existing JSONL byte-for-byte
  unchanged and publishes no new target when none existed.
- Inject failures independently at **every** finalization phase: parent
  directory creation, temp-file creation, write, flush, file fsync, close, and
  `os.replace`.  For each phase, assert the old target is unchanged, the
  phase's original exception propagates, the collector remains unfinalized,
  its buffered bytes and written/dropped counters are identical, and no temp
  remains when cleanup succeeds.  Restore the injected fault and prove a retry
  on that same collector atomically succeeds with the original buffered bytes.
- Independently inject cleanup close/unlink failure after an operational
  failure.  Assert cleanup is best-effort: it never masks the original
  exception, never changes old target or collector state, and leaves the
  collector retryable; permit and explicitly detect the residual temp only in
  this cleanup-failure case, then remove it in test teardown.
- In both `run_postproc` and `save_prelinefit_checkpoint`, a debug target equal
  to the resolved input-bundle root, directly below that root, or anywhere in a
  deeper bundle descendant is rejected before detector/output activity.  Cover
  the same root/descendant cases when `geff_dir` itself is a symlink.  Use a
  sentinel child to prove no target/temporary file is touched.
- In both run paths, also reject a debug target equal to a GEFF directory,
  directly below its tree, or below it through either a GEFF symlink or
  debug-path symlink.  Keep this per-GEFF-tree test outside the bundle via a
  symlinked `*.geff` entry, proving the individual resolved-root rule remains in
  force even when that GEFF resolves elsewhere.  Also cover a debug leaf
  symlink located inside a GEFF tree but pointing outside; the protected
  directory entry and same-directory temp location still require rejection.
- In both run paths, a regular-file GEFF rejects an equal/samefile debug target
  and rejects every sibling debug target that remains inside the input bundle.
  A regular-file GEFF sibling is allowed only outside the bundle and otherwise
  unrelated.  CSV/stats, manifest, and dataset-pickle aliases, plus equality
  with `checkpoint_dir` itself, are also rejected; an unrelated existing target
  outside the bundle is allowed.
- `run_relinefit` never constructs, allocates, or publishes a collector.

### 10.5 Off/dry-run identity and no R2 mutation

- With the master off, compare the pre-R1 expected pipeline result: node/edge
  values, order, row identities, nested metadata identities, and all existing
  non-twin stats remain unchanged; all newly preseeded twin stats are zero.
- With master on and dry-run true, compare against the same graph with the twin
  master off while all non-twin passes are held identical.  The node mapping,
  node rows, edge list contents/order, edge-row identities, nested metadata
  identities, and final CSV node/edge rows are identical.  Only twin telemetry
  and optional debug JSONL may differ.
- Repeat dry-run planning on the same caller objects and prove identical graph
  objects/metadata and deterministic counters/debug bytes.
- Even when a plan contains accepted candidates, assert
  `steal_twin_edges_removed == steal_twin_edges_added == 0`, the original
  `Q->B` edge object remains present in the same position, and no `P->B` edge is
  added.  Do not add ST-R2 mutation tests disguised as R1c tests.

## 11. Verification commands and handoff report

Use the main repository Python and disable cache/bytecode writes:

```bash
PY=/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking/.venv/bin/python
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$PY" -m pytest \
  tests/test_public_postproc.py -q -p no:cacheprovider -k steal_twin_r1c
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$PY" -m pytest \
  tests/test_public_postproc.py -q -p no:cacheprovider
"$PY" -m ruff check src/biohub/public_postproc/pipeline.py \
  tests/test_public_postproc.py
git diff --check
git status --short
```

Do not run official tests that import GT, eval12/eval24/eval36, Kaggle, GPU
inference, or any data-heavy command.  Before handing back, prove:

- only the two allowed files changed;
- no production/test addition contains `disposable_steal`;
- no code imports `official`, evaluation modules, network libraries, or ST-R3
  artifacts;
- no R1b type/interface was edited;
- the hook remains after safe divisions and before every downstream topology
  pass;
- the candidate profile with `DRY_RUN=False` still cannot execute in ST-R1.

Report exact changed files, focused/full test counts and results, lint/diff
results, the implemented filter/collector APIs, deterministic JSONL byte and
global-cap evidence, atomic-failure evidence, off/dry-run identity evidence,
residual risks, and a non-destructive rollback command.  Do not commit.

## 12. Residual risks that this task does not claim to close

- R1c is pinned to the adopted R1b interface at `develop@cb206e8` and production
  file SHA256 above.  A later R1b drift requires a new review; the implementer
  must not adapt this task silently to a guessed interface.
- JSONL atomic replacement does not make the existing CSV, run-stats, pickle,
  and manifest outputs transactionally atomic as one group.
- The collector is bounded by record count, as frozen by the parent contract;
  individual immutable metadata snapshots do not have a separate byte limit.
- No ST-R2 mutation correctness or idempotence claim follows from dry-run
  planning, even when R1 reports accepted candidates.
- No ST-R3 metric, GT, feasibility, promotion, runtime, or RSS conclusion may be
  drawn from this implementation or its unit tests.
