# ST-R1 binding contract: twin-only planner and dry-run telemetry

Updated: 2026-08-30 (Asia/Tokyo)

This file resolves the implementation ambiguities left open by
[`steal_twin_design.md`](steal_twin_design.md). It is binding for ST-R1 and is
read together with that design and [`gold_loop_protocol.md`](gold_loop_protocol.md).
The causal candidate, radii, ordering, staged metric gates, and stop conditions
remain unchanged. No GT metric may be read during ST-R1.

## Scope and phase boundary

ST-R0 is complete at `develop@032da44`: E23 public-four submission, normalized
graph, telemetry, and official-score parity all passed. ST-R1 implements only an
immutable planner, strict node-existence scoring adapter, deterministic
resolution, telemetry, bounded debug collection, and a pipeline dry-run hook.
It must not remove or add graph edges.

The intended production touch set is:

- `src/biohub/public_postproc/config.py`
- `src/biohub/public_postproc/deepcenter.py` (provenance exposure only)
- `src/biohub/public_postproc/divisions.py`
- `src/biohub/public_postproc/pipeline.py`
- `tests/test_public_postproc.py`

Do not change `graph_ops.py`, `official/`, notebooks, evaluation code, data, or
experiment outputs. The pipeline call is immediately after
`add_safe_divisions_postlink` and before division geometry, isolated pruning,
short-track filtering, and linefit. Reuse the existing `repair_frame_cache` and
`deepcenter_heatmap_cache` objects.

If `OUTPUT_STEAL_TWIN_REWIRE` is true while `STEAL_TWIN_DRY_RUN` is false in
ST-R1, raise a clear `RuntimeError` before planning. The real
`e23_twin_only_v1` profile intentionally has `DRY_RUN=0` and therefore cannot
be executed until ST-R2 lands the mutation adapter. Tests exercise ST-R1 with
an explicit dry-run override.

## Pure planner boundary

The planner consumes immutable scalar snapshots and returns a plan. It must not
receive or mutate the caller's `stats`, node dicts, edge dicts, node mapping, or
edge list. The pipeline adapter alone merges planner counters into `new_stats`,
builds the strict DeepCenter callback from the shared caches, and sends debug
records to the run-level collector.

Frozen dataclasses/tuples are preferred. Exact class names are not binding, but
the returned plan must expose:

- one validation reason or `None`;
- all eligibility-passing candidates in complete sort-key order;
- accepted candidates in acceptance order;
- one decision for every eligibility-passing candidate;
- a complete integer counter mapping;
- accepted and resolution-rejected debug records only.

Snapshot nodes are sorted by `node_id`. Snapshot edges preserve an
`input_position` and are sorted by `(source_id, target_id, input_position)` for
index construction; the planner never rewrites the caller's edge order.
Candidate scalar fields are copied, not referenced. Spatial queries use
physical `(z,y,x)=(1.625,0.40625,0.40625)` micrometres and never enumerate all
P/Q pairs. Query results are normalized by sorting `(distance_um, node_id)`.

`_load_geff_as_dicts` must reject a repeated node ID before overwriting it.
Direct snapshot tests may pass repeated node rows and must receive the
`duplicate_node_id` validation result. A production loader duplicate is a hard
fail before graph mutation because no unambiguous `nodes_by_id` exists.

## Exact config contract

Add every `BIOHUB_STEAL_TWIN_*` field from the design. Inert code defaults use
the exact v1 numeric/boolean values but keep the master switch off, the debug
path empty, and mode `twin_only_v1`. Add
`TWIN_ONLY_V1_PRESET={**E23_PRESET, ...}` and profile
`e23_twin_only_v1`, explicitly spelling every twin field and setting the
experiment tag to `e23_twin_only_v1`.

Only `twin_only_v1` is a valid `STEAL_TWIN_MODE`; do not invent an `off` mode
or any disposable-steal control. The master switch provides inactivity.

When `OUTPUT_STEAL_TWIN_REWIRE` is false, the feature is completely inert: do
not validate twin-only fields, call the planner or DeepCenter adapter, allocate
a debug collector, or perform debug I/O. When the master switch is true, the
mode and every causal field are a version lock and must equal the frozen v1
values below:

```text
STEAL_TWIN_MODE                   == "twin_only_v1"
STEAL_TWIN_PARENT_MAX_UM          == 8.0
STEAL_TWIN_EXISTING_CHILD_MAX_UM == 10.0
STEAL_TWIN_SISTER_MIN_UM          == 5.5
STEAL_TWIN_SISTER_MAX_UM          == 11.0
STEAL_TWIN_DIVERGE_UM             == 2.25
STEAL_TWIN_TWIN_MAX_UM            == 5.0
STEAL_TWIN_REQUIRE_TWO_SUCCESSORS is True
STEAL_TWIN_REJECT_SYNTHETIC       is True
STEAL_TWIN_DEEPCENTER_VETO        is True
STEAL_TWIN_FRAME_CAP_ABS          == 1
STEAL_TWIN_VIDEO_CAP_ABS          == 2
STEAL_TWIN_DEBUG_MAX_RECORDS      == 200
```

The only operational overrides allowed while ST-R1 is enabled are
`STEAL_TWIN_DRY_RUN=True` and an explicit `STEAL_TWIN_DEBUG_JSONL` path. The
frozen candidate preset retains `DRY_RUN=False`; ST-R1 tests opt into the
temporary dry-run override, while a non-dry run raises the guard above.
`DEBUG_MAX_RECORDS` is not a config override: production/runtime validation
requires exactly 200. A direct collector unit test may construct the internal
collector with a smaller capacity to exercise overflow without changing the
config. Boundary tests vary synthetic coordinates or returned DeepCenter
scores; they must not perturb the frozen radii, threshold, booleans, or caps.

Because `STEAL_TWIN_DEBUG_JSONL` is empty in both E23 and the candidate, an
effective dataclass diff cannot literally contain every allowed field. The
binding profile test is:

1. all candidate twin fields have the exact values in the design;
2. `set(actual_diff) <= {all STEAL_TWIN field names, EXPERIMENT_TAG}`;
3. the actual diff contains `OUTPUT_STEAL_TWIN_REWIRE` and `EXPERIMENT_TAG`;
4. all non-whitelisted E23 fields are exactly equal;
5. base1 and e23 retain their pre-ST-R1 effective values and outputs.

## Exact telemetry names

Preseed every key below in `new_stats()`. First-failure and resolution reasons
always use `steal_twin_rejected_<reason>`; no alternative spelling is allowed.

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

Validation chooses exactly one category in the order printed above and occurs
before pool construction or DeepCenter calls. Multiple errors still increment
only `validation_failed` and the first category. A validation failure has all
enumeration/resolution counters zero.

The graph-wide invariant `indegree<=1` and `t->t+1` is stronger than two listed
eligibility guards. Therefore a shared `A2==B2` graph fails validation as
`indegree`, and a wrong-time successor edge fails as `nonconsecutive_edge`.
The `rejected_shared_successor` and `rejected_time` schema keys remain preseeded
but are unreachable for a validated graph. Tests must assert this precedence;
do not weaken graph validation to make those counters fire.

For every validated dataset:

```text
enumerated == sum(all nearest/eligibility rejected counters) + eligible
eligible == accepted + rejected_conflict + rejected_frame_cap + rejected_video_cap
planned_edges_removed == planned_edges_added == accepted
edges_removed == edges_added == 0                 # ST-R1 dry-run
isolated_donors == accepted                       # planned structural property
accepted <= examined_frames
accepted <= configured video cap
```

The planner counts `eligible` before resolution. Resolution order is conflict,
then frame cap, then video cap. It checks candidates in the complete frozen
sort-key order. `examined_frames` is the number of distinct times containing a
nonempty P or Q pool. `enumerated` is one per P only when its frame has at least
one Q. A general one-edge donor with a predecessor is excluded from Q_pool and
is not a disposable-steal candidate.

Pure-boundary actual mutation and final-output delta fields are deferred to
ST-R2. Qwen must not invent their names in ST-R1.

## Strict DeepCenter adapter and reason mapping

The existing loader is the provenance trust boundary. It already loads the
configured checkpoint, checks `DEEPCENTER_EXPECTED_EPOCH`, constructs the exact
model, and fails when the required artifact is unusable. ST-R1 must add the
loader-verified integer `checkpoint_epoch` to the returned detector bundle.
The exact required bundle fields for strict twin scoring are `model`, `cfg`,
`device`, `torch`, `path`, and `checkpoint_epoch`; a missing field rejects as
`deepcenter_bundle`. The bundle `cfg.pool_factor` must be an integer (not a
boolean) with value at least 1. Do not add model weights, hashes, or credentials
to telemetry/debug. The adapter rejects a forged/incomplete bundle, invalid
`pool_factor`, or epoch mismatch as `deepcenter_bundle`.

The callback scores B only, last in eligibility, at the fixed threshold `0.12`.
It reuses the shared frame and heatmap caches. It returns accepted, finite raw
score (or `None`), and exactly one reason using this mapping:

- `deepcenter_bundle`: global DeepCenter use is off, bundle missing, required
  bundle entries absent, verified epoch absent/mismatched, or detector config
  needed for scoring is invalid;
- `deepcenter_dataset`: dataset is `None` or blank;
- `deepcenter_frame`: frame read raises or returns missing/empty/wrong-rank data;
- `deepcenter_heatmap`: model/inference raises, heatmap is missing/empty/wrong
  rank, scoring patch is empty/out of bounds, or no scalar score is produced;
- `deepcenter_nonfinite`: frame, heatmap, patch, or raw scalar contains a
  nonfinite value;
- `deepcenter_threshold`: finite raw score is strictly below `0.12`;
- accepted: finite raw score is equal to or above `0.12`.

Populate the frame cache explicitly before heatmap inference so a frame-read
exception is distinguishable; `deepcenter_heatmap_for_frame` must then reuse
that cached frame. Do not call the existing fail-open
`deepcenter_accept_repair_point` for twin-only. A score never participates in
candidate sort or conflict resolution.

## Deterministic run-level debug ownership

The pure planner only returns debug-ready records. `run_postproc` and
`save_prelinefit_checkpoint` each create one collector for the whole sorted
dataset run when `STEAL_TWIN_DEBUG_JSONL` is nonempty, pass it through the
filter adapter, and write once after all datasets succeed. They create no file
when the path is empty. A direct filter call with a nonempty debug path but no
explicit collector raises a clear error rather than silently applying a
per-dataset cap.

Datasets are already processed in sorted order and each planner returns records
in complete sort-key/ID order. The collector allocates the remaining global
capacity online in that order, retains at most the frozen 200 records, and
returns that dataset's written/dropped counts before its stats row or checkpoint
payload is serialized. It buffers retained records in memory; only after the
entire sorted run succeeds does it atomically replace the configured JSONL
(same-directory temporary file followed by replace). A failed run must not
publish a partial new JSONL. Every retained line is encoded exactly as:

```python
json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
```

It includes accepted and resolution-rejected (`conflict`, `frame_cap`,
`video_cap`) records only; never dump eligibility rejects. Per-dataset
`debug_records_written` and `debug_records_dropped` are therefore final before
`_dataset_stats_row` or each `save_prelinefit_checkpoint` pickle is written;
their sums equal the final line count and global dropped count. Repeated use of
an existing output path overwrites it only at successful finalization; it never
appends stale records.

Each record contains dataset, decision/reason, P/Q/A/B/A2/B2, complete sort
key, `d(P,Q)`, `d(P,A)`, `d(P,B)`, `d(A,B)`, `d(A2,B2)`, divergence growth,
raw DeepCenter score/threshold/decision, the complete immutable Q->B edge
snapshot, and the planned P->B edge (`edge_prob=None` and recomputed distance).

## Minimum pre-metric verification

The combined test list in the design is split by implementation phase and must
not be pulled forward across the pure-planner boundary:

- **ST-R1 (this handoff):** exact config/profile locks; master-off and dry-run
  graph/value/order/metadata/object identity; immutable snapshot validation and
  priority; complete planner eligibility including distance boundaries,
  mutual-nearest ties, motif/successor/synthetic gates, and the strict
  DeepCenter reason map with adjacent score floats; deterministic complete-key
  resolution and conflict/frame/video caps; telemetry conservation; input,
  edge, and spatial-result permutations; shared cache reuse; global online
  debug capacity, deterministic bytes, and pre-serialization counters; pipeline
  placement; loader duplicate rejection; non-dry guard; and repeated planner
  dry-run idempotence.
- **ST-R2 (deferred):** actual `Q->B` replacement with `P->B`, exact new-edge
  distance/probability metadata, pure-boundary `2k` invariants, mutation
  idempotence, unrelated-component identity, graph invariants, and downstream
  prune/short-track/linefit delta accounting.
- **ST-R3 (deferred):** official-metric positive/adversarial fixtures and the
  immutable evaluation manifest/readout contract.

Qwen must implement every ST-R1 item above and the resolutions in this file,
but must not add ST-R2 mutation tests or ST-R3 metric/manifest tests now.

Before handoff run:

```bash
PYTHONPATH=src pytest tests/test_public_postproc.py -q
PYTHONPATH="src:<main>/official/src" pytest tests -q
ruff check src/biohub/public_postproc tests/test_public_postproc.py
git diff --check
```

Also prove no edits outside the allowed ST-R1 files and no occurrence of
`disposable_steal` in production/config/test additions. Do not run eval12,
eval24, eval36 official metrics, Kaggle, or any network operation.
