# Qwen implementation task: twin-only ST-R1b immutable planner

Implement only ST-R1b in the clean linked worktree supplied by the launcher.
The expected base is the reviewed ST-R1a checkpoint supplied by the parent.
Before editing, confirm that `TwinDeepCenterDecision` and
`score_twin_deepcenter` exist with the exact ST-R1a interface reproduced
below. If that dependency is absent or differs, stop and report it; do not
repair ST-R1a in this handoff.

Do not commit, branch, push, use network/Kaggle, or edit analysis documents.
This handoff is self-contained and supersedes the monolithic
`steal_twin_st_r1_qwen_task.md` for this run. Read `AGENTS.md` completely, then
inspect `divisions.py` and only relevant test sections with `rg`/`sed`; do not
dump the whole large test file or re-read the older gold/design documents.

## Allowed files and deferred work

Modify only:

- `src/biohub/public_postproc/divisions.py`
- `tests/test_public_postproc.py`

Do not modify `config.py`, `deepcenter.py`, `pipeline.py`, `graph_ops.py`, or
any other file. Do not add the `new_stats` schema or stats merge, build a
DeepCenter bundle/cache callback, add debug JSONL I/O or capacity allocation,
add the pipeline hook or non-dry guard, change the GEFF loader, mutate an edge,
or add metric/evaluation behavior. Those belong to ST-R1c or later.

R1b implements only an immutable validated snapshot, deterministic
`twin_only_v1` candidate engine, resolution, planner-owned counter values, and
debug-ready records. It must preserve all current safe-division behavior.

## Fixed ST-R1a dependency and planner boundary

R1a provides this exact decision type and strict adapter:

```python
@dataclass(frozen=True)
class TwinDeepCenterDecision:
    accepted: bool
    raw_score: float | None
    reason: str | None

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

The R1b planner does not receive a detector bundle or caches. It receives a
typed callback equivalent to:

```python
TwinScoreCallback = Callable[[TwinSnapshotNode], TwinDeepCenterDecision]
```

ST-R1c will create that closure and delegate to `score_twin_deepcenter` using
the candidate's `B` node. R1b calls the callback on `B` only, after every
geometric/structural/synthetic gate passes. A score never participates in the
candidate sort key or conflict/cap resolution.

Provide one clearly typed planner entry point, preferably
`plan_twin_only_v1`, accepting the frozen v1 `PostprocConfig`, dataset name,
node-row sequence, edge-row sequence, and score callback. Exact internal class
names are not binding. Read the frozen radii, divergence threshold, and caps
from their R1a config fields; do not add alternate controls or accept runtime
threshold/cap arguments. The returned immutable plan must expose:

- exactly one validation reason or `None`;
- every eligibility-passing candidate in complete sort-key order;
- accepted candidates in acceptance order;
- one resolution decision for every eligibility-passing candidate;
- a complete integer planner-counter mapping;
- debug-ready records for accepted and resolution-rejected candidates only.

The planner must not receive or mutate caller stats. It must not mutate or
retain references to caller node dicts, edge dicts, node/edge sequences, or
embedded metadata. Copy scalar data into frozen dataclasses/tuples or an
equivalently immutable representation. A later mutation of a caller row must
not change the returned plan or edge snapshot.

## Immutable snapshot and exact validation order

The node input is a row sequence, not an already-deduplicated mapping, so a
direct planner call can detect repeated node IDs. Required node fields are
`node_id,t,z,y,x`; `gap_synthetic` is optional and absent means false. Snapshot
nodes are sorted by `node_id`.

Each edge must provide `source_id,target_id`. Preserve its original
row ordinal internally, recursively deep-copy and immutably freeze its complete
metadata without caller references, and sort snapshot edges by
`(source_id,target_id,input_position)` for index construction. Never rewrite
the caller's edge order. Recompute geometric edge distance from snapshot node
coordinates for validation; do not require or trust an existing
`distance_um` metadata value.

The internal `input_position` is a separate snapshot field, never injected
into caller metadata or a debug edge record. If the caller edge itself already
has a metadata key named `input_position`, preserve that key/value exactly as
caller metadata; only the separate internal ordinal is omitted. Recursively
freeze nested mappings, lists, tuples, and sets after copying so later caller
mutation cannot change a plan or debug-ready record.

Validate the whole video before pool construction, spatial queries, or score
callback calls. Choose only the first category in this exact global priority
order, independent of node/edge row order:

```text
missing_node_field
invalid_node_id
duplicate_node_id
invalid_node_time
nonfinite_node_coordinate
invalid_edge_endpoint
dangling_edge
duplicate_edge
nonconsecutive_edge
indegree
outdegree
nonfinite_edge_distance
```

IDs and times must be integers but not booleans. Coordinates must be numeric
and finite. Invalid edge endpoints include a missing endpoint field or an
endpoint that is not a non-boolean integer. A duplicate edge is a repeated
`(source_id,target_id)`. Every edge must be `t -> t+1`, with `indegree<=1` and
`outdegree<=2`. Physical distance uses
`(z,y,x)=(1.625,0.40625,0.40625)` micrometres and must be finite.

On failure, return a plan with that validation reason; increment only
`steal_twin_validation_failed` and its matching validation counter. All pool,
enumeration, eligibility, resolution, planned/actual-edge, isolated-donor, and
debug counters remain zero. Do not call the score callback.

A validated graph makes two eligibility counters unreachable:
`steal_twin_rejected_time` because every edge is consecutive, and
`steal_twin_rejected_shared_successor` because a shared `A2==B2` violates
`indegree<=1`. Keep both keys at zero. A wrong-time successor must fail video
validation as `nonconsecutive_edge`; a shared successor must fail as
`indegree`. Do not weaken validation to make the eligibility counters fire.

## Pools, spatial search, and mutual unique nearest

For every frame `t`, create sorted snapshot pools:

- `P_pool[t]`: `indegree(P)=1`, `outdegree(P)=1`, `succ(P)=A`;
- `Q_pool[t]`: `indegree(Q)=0`, `outdegree(Q)=1`, `succ(Q)=B`.

Sort pools and successor lists by node ID. A donor with one outgoing edge but
also a predecessor is not in Q_pool. `steal_twin_examined_frames` is the number
of distinct times having a nonempty P or Q pool. Pool counters are total node
counts across frames.

For each frame having both pools nonempty, build exactly one physical-coordinate
`scipy.spatial.cKDTree` over the node-ID-sorted union `P_pool[t] ∪ Q_pool[t]`.
Use that same tree for both P-to-Q and Q-to-P radius queries, filtering results
to the opposite role. A frame with either pool empty needs no tree or query.
Never build a second role-specific tree, rebuild per candidate, or enumerate
all P/Q pairs. Normalize every filtered spatial result by sorting
`(distance_um,node_id)`; never depend on tree return order.

Process each P once. It contributes one `steal_twin_enumerated` only when its
frame has at least one Q. Find P's nearest Q and that Q's nearest P within the
inclusive frozen `5.0 um` radius. A nearest neighbor is unique only when
exactly one node lies within `1e-9 um` inclusive of the minimum distance in
that direction. Do not use ID to choose a tied winner.

Apply nearest failures in this exact order:

1. no Q within `5.0 um` -> `distance_twin`;
2. P-to-Q nearest is tied -> `ambiguous_p_nn`;
3. chosen Q-to-P nearest is tied -> `ambiguous_q_nn`;
4. both are unique but Q chooses another P -> `not_mutual_parent_nn`.

An exact `5.0 um` neighbor is in range. Differences equal to `1e-9 um` are
ties; only a difference strictly greater than `1e-9 um` is unique.

## Exact motif and first-failure eligibility

Roles have times
`t(P)=t(Q)=t`, `t(A)=t(B)=t+1`, and `t(A2)=t(B2)=t+2`.
For each mutual-unique P/Q pair, use this first-failure order:

1. Existing child: `A=succ(P)` and `d(P,A)<=10.0`; otherwise
   `distance_existing_child`.
2. Parent candidate: `B=succ(Q)`, `A!=B`, no existing `P->B`, and
   `d(P,B)<=8.0`; otherwise `distance_parent` for the distance failure.
   Pool construction plus video validation already guarantees the listed
   degree/predecessor facts; do not invent another rejection reason.
3. Sister lower bound: require `d(A,B)>=5.5`; otherwise
   `distance_sister_low`.
4. Sister upper bound: require `d(A,B)<=11.0`; otherwise
   `distance_sister_high`.
5. Successors: require `outdegree(A)=outdegree(B)=1` and define
   `A2=succ(A)`, `B2=succ(B)`, with `A2!=B2`. If either A or B has outdegree
   zero **or two**, reject as `missing_successor`. Time and shared successor
   failures are unreachable after whole-video validation as noted above, so a
   validated plan never reaches an `A2==B2` candidate.
6. Divergence: require `d(A2,B2)-d(A,B)>=2.25`; otherwise `divergence`.
7. Synthetic: none of `P,Q,A,B,A2,B2` may have
   `gap_synthetic == 1`; otherwise `synthetic`.
8. DeepCenter last: call the score callback on B at most once. A valid result
   is a `TwinDeepCenterDecision` whose `accepted` field is exactly `bool` and
   whose raw score is either `None` or a finite non-boolean real number.
   Accepted requires a finite raw score and `reason is None`. Rejected requires
   exactly one of `deepcenter_bundle`, `deepcenter_dataset`,
   `deepcenter_frame`, `deepcenter_heatmap`, `deepcenter_nonfinite`, or
   `deepcenter_threshold`. A `deepcenter_threshold` rejection requires a finite
   non-boolean raw score strictly below `0.12`; every other rejection reason
   requires `raw_score is None`. Map a valid rejection to its exact counter.
   If the callback raises, returns another type, uses a non-bool `accepted`, has an
   inconsistent/missing/nonfinite score or reason, or returns an unknown
   reason, fail closed as `deepcenter_bundle` with raw score `None`.

All radius and distance bounds are inclusive. Check every derived distance and
growth for finiteness before it can enter an eligible candidate or sort key;
never let an overflow, NaN, or Inf raise or reach sorting. Reject at the first
corresponding gate: nonfinite `d(P,Q)` or spatial-query numeric failure ->
`distance_twin`; `d(P,A)` -> `distance_existing_child`; `d(P,B)` ->
`distance_parent`; `d(A,B)` -> `distance_sister_high`; and `d(A2,B2)` or the
derived growth -> `divergence`. An eligibility-passing candidate increments
`steal_twin_eligible` before resolution and has only finite geometry/sort-key
values. Preserve its finite raw DeepCenter score and decision for debug; do not
use the score for sorting.

## Complete sort and resolution

Sort all eligible candidates by this complete tuple:

```text
(
  d(P,B) + 0.15 * d(A,B),
  -(d(A2,B2) - d(A,B)),
  d(P,Q),
  P, Q, A, B, A2, B2,
)
```

Use the unrounded float values. IDs are the final deterministic tie breakers.
Walk this sorted list once. For each candidate classify exactly one decision
in this priority order:

1. if any of `{P,Q,A,B,A2,B2}` is already used by an accepted candidate,
   reject as `conflict`;
2. if that frame already has one accepted candidate, reject as `frame_cap`;
3. if the video already has two accepted candidates, reject as `video_cap`;
4. otherwise accept it and atomically add all six IDs to the used set and
   increment the frame/video accepted counts.

The caps are the frozen config values `1` and `2`; tests vary geometry, never
config caps. Conflict remains the reason even when a cap is also full, and
frame cap remains the reason when both caps are full.

R1b plans but never performs these operations for each acceptance:

```text
remove the complete immutable Q->B edge snapshot
add {source_id: P, target_id: B,
     distance_um: recomputed d(P,B), edge_prob: None}
```

No node or edge is edited, removed, or appended in R1b.

## Exact planner counters and conservation

Return every key below as an integer, including zero-valued and unreachable
keys. R1c will preseed/merge the schema and replace the two debug counts after
run-level allocation; R1b does neither.

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

For every validated graph assert:

```text
enumerated == sum(all nearest and eligibility rejection counters) + eligible
eligible == accepted + rejected_conflict + rejected_frame_cap + rejected_video_cap
planned_edges_removed == planned_edges_added == accepted
edges_removed == edges_added == 0
isolated_donors == accepted
accepted <= examined_frames
accepted <= 2
debug_records_written == debug_records_dropped == 0
```

The first sum includes `distance_twin` through all six DeepCenter rejection
keys, including the two unreachable `time` and `shared_successor` zeros. It
does not include resolution rejects.

## Debug-ready records, without debug I/O

Return records only for accepted, conflict, frame-cap, and video-cap decisions,
in the same order those decisions were made from the complete sorted list.
Never return a record for a validation, nearest, or eligibility rejection.

Each record must carry copied, deterministic data sufficient for R1c to encode:

- dataset and decision/reason;
- P/Q/A/B/A2/B2 IDs and the complete sort-key values;
- `d(P,Q)`, `d(P,A)`, `d(P,B)`, `d(A,B)`, `d(A2,B2)`, and divergence growth;
- raw DeepCenter score, fixed threshold `0.12`, and DeepCenter decision;
- the complete immutable pre-plan Q->B edge snapshot, with all caller metadata
  copied and no internal `input_position` leaked;
- the planned P->B edge with recomputed distance and `edge_prob=None`.

The representation may be frozen dataclasses/tuples rather than JSON dicts,
but it must be losslessly convertible to the exact record without reading the
caller graph again. R1b performs no file I/O and no global capacity allocation.

## Required ST-R1b tests

Append focused tests named `test_steal_twin_r1b_*`; do not reorganize or weaken
earlier tests. Use synthetic in-memory rows and deterministic monkeypatches
only. Cover all of the following:

- a minimal eligible six-role P/Q/A/B/A2/B2 motif plus P's required
  predecessor context, with exact candidate, decision, counters, and record;
- exclusion from Q_pool of a one-edge donor that has a predecessor;
- every validation reason, exact multi-fault priority, and row-order-invariant
  validation; direct repeated node rows must produce `duplicate_node_id`;
- wrong-time successor -> validation `nonconsecutive_edge`, and shared
  successor -> validation `indegree`, with unreachable eligibility keys zero;
- inclusive `5.0`, `10.0`, `8.0`, `5.5`, and `11.0` distance boundaries plus
  `np.nextafter` inside/outside cases by changing coordinates, not config;
- divergence `np.nextafter(2.25, -inf)`, exactly `2.25`, and
  `np.nextafter(2.25, +inf)`;
- P-side and Q-side `1e-9 um` inclusive nearest ties, unique values just over
  the tolerance, and a unique but non-mutual pair;
- missing A/B successor, A outdegree two, B outdegree two, and each of the six
  synthetic-node positions;
- nonfinite/overflow derived geometry mapped without an exception to
  `distance_twin`, `distance_existing_child`, `distance_parent`,
  `distance_sister_high`, or `divergence` as specified, with no nonfinite sort
  key;
- score callback is called only for B and only after all earlier gates; map
  every R1a rejection reason to its exact planner counter; callback exceptions,
  wrong result type, non-bool acceptance, invalid accepted score/reason, and an
  unknown rejection reason all fail closed once as `deepcenter_bundle`;
  explicitly include threshold+`None`, threshold+score `>=0.12`, and a
  non-threshold rejection with a finite score as malformed cases;
- complete sort-key tests that isolate cost, negative divergence, P/Q distance,
  and every ID field as successive tie breakers; raw score must not reorder;
- conflict, frame cap, video cap, plus overlap cases proving
  conflict-before-frame-before-video priority;
- all conservation identities for successful, rejected, capped, empty-pool,
  and validation-failed plans;
- randomized node-row and edge-row permutations and forced spatial-result
  permutations yielding identical candidates, decisions, counters, and
  debug-ready records;
- cKDTree constructor spy on multiple P/Q frames proving exactly one union
  tree per frame with both pools nonempty and no per-candidate rebuild;
- caller node/edge/list/dict/metadata values, identities, and edge order remain
  unchanged; mutate caller rows and nested dict/list edge metadata after
  planning and prove the plan and debug-ready record remain detached; preserve
  a caller-owned `input_position` metadata key while omitting only the separate
  internal ordinal;
- repeated planning on the same caller objects is exactly idempotent;
- debug-ready records contain every required value and occur only for accepted
  or resolution-rejected candidates; debug counters remain zero and no I/O is
  attempted.

Do not add ST-R1a adapter/cache tests, R1c pipeline/stats/debug JSONL/loader
tests, ST-R2 applied-mutation/output-edge-metadata/`2k` tests, or ST-R3
metric/manifest tests. Inspecting the immutable planned edge inside the R1b
plan/debug-ready record remains required above.

## Verification

```bash
PY=/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking/.venv/bin/python
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$PY" -m pytest \
  tests/test_public_postproc.py -q -p no:cacheprovider -k steal_twin_r1b
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$PY" -m pytest \
  tests/test_public_postproc.py -q -p no:cacheprovider
"$PY" -m ruff check src/biohub/public_postproc/divisions.py \
  tests/test_public_postproc.py
git diff --check
```

Before handoff, prove `git status --short` contains only the two allowed files
and no added production/test line contains `disposable_steal`. Report the exact
planner/callback interfaces, immutable result types, changed files, focused and
full test counts/results, conservation results, residual risks, and rollback
command. Do not commit.
