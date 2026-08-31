# ST-R2 binding contract: transactional twin-only mutation adapter

Status: **HOLD_R1C_IMPLEMENTATION_DEPENDENCY**

This is a design-only implementation handoff.  It freezes the ST-R2 pure
mutation boundary and its pipeline semantics, but it does **not** authorize an
implementation yet.  ST-R1c has a final reviewed task document at commit
`541a659a67e1b136e930f24a2e63f4e2a73a06bf`; its production implementation is
not present at this base.  The exact R1c implementation commit, source hashes,
symbols, signatures, and call order must be pinned in section 13 before any R2
source change starts.  Until that audit is complete, the disposition is HOLD.

The purpose of R2 is deliberately narrow: consume a validated immutable
`TwinPlan`, remove each accepted `Q->B` edge, append its `P->B` replacement,
prove the pure-boundary invariants, and connect that transaction at the already
chosen pipeline hook.  R2 does not change candidate discovery, scoring,
resolution, caps, debug selection, or evaluation.

## 1. Frozen design base

This contract was authored against the clean main-repository commit
`541a659a67e1b136e930f24a2e63f4e2a73a06bf`.  The reviewed files and SHA-256
digests are:

```text
AGENTS.md
f62b268b3be7607d3571a5e543687bc23da8efb94fda40d6940fa767987a7e5f

analysis/steal_twin_design.md
9e6e7aa320020da0076fe71da3f5fb610b94fa1e27fb13d048e51a0e771c024c

analysis/steal_twin_st_r1_contract.md
54caa99ba0f5637b69366dccf6260e49728bb8380b506a9beafbf1374b08a274

analysis/steal_twin_st_r1c_sol_task.md
5829460647068995a884f02b653e2c0bff8ab2eaa831029241e3ca8d31191093

analysis/steal_twin_st_r3_eval_contract.md
18cfa78464b70cc419ed4f6614c39192d0727d85ab3531beb1092b32bb10a169

src/biohub/public_postproc/divisions.py
3009d182b71dd786f1249e17734b2e6dea70e2260b752f6227e810643efb59f4

src/biohub/public_postproc/pipeline.py
3f0dad3fa502af98cf421c0c81834020da41c8aa223bbd9193712365cf32f43b

tests/test_public_postproc.py
13f435a03f8aa8f134f27b7bbf583337e3333bdf20fd44a3f499e655dd5d8e68
```

The adopted R1b planner is on `develop` at `cb206e8`.  Its current
`divisions.py` digest is the one above.  In particular, R2 binds to the public
immutable types `TwinSnapshotNode`, `TwinSnapshotEdge`, `TwinEdgeRecord`,
`TwinPlannedEdge`, `TwinCandidate`, `TwinResolutionDecision`, and `TwinPlan`,
and to:

```python
plan_twin_only_v1(
    cfg: PostprocConfig,
    dataset: str | None,
    node_rows: Sequence[Mapping[str, object]],
    edge_rows: Sequence[Mapping[str, object]],
    score_callback: TwinScoreCallback,
) -> TwinPlan
```

Do not rename or broaden an R1b type in R2.  If any pinned file or interface
differs when implementation begins, stop and perform a new contract review.

## 2. Scope

R2 may implement only:

1. a pure, transactional `TwinPlan` mutator in `divisions.py`;
2. strict plan/current-graph matching and pre/post classification;
3. the pure-boundary conservation and graph-invariant checks;
4. the candidate non-dry pipeline branch at the existing R1c hook;
5. exact mutation and downstream-observation counters defined here; and
6. focused unit/integration tests for those behaviors.

R2 must not implement or change:

- R1b eligibility, nearest-neighbor logic, score callback, threshold, sort key,
  conflict resolution, frame/video caps, frozen metadata codec, or counters;
- R1c collector allocation, JSON-safe codec, global capacity, atomic publish,
  path alias guards, cache ownership, duplicate-loader policy, or debug schema;
- config names, defaults, locks, profile values, DeepCenter loading/model code,
  checkpoint/manifest format (apart from the expected mutated graph and new
  stats values), or the `twin_only_v1` mode spelling;
- safe-division, gap, motion, centroid, geometry, prune, short-track, linefit,
  CSV writer, or official metric algorithms;
- ST-R3 runner, arm manifest, timing/RSS, image hashing, GT sandbox, metric,
  promotion, network, Kaggle, or score-dependent behavior;
- a `disposable_steal` mode, fallback heuristic, partial mutation recovery, or
  best-effort graph repair.

No ground truth, metric result, prior arm result, promotion result, or callback
capable of reading them may enter the R2 mutator or adapter.

## 3. Exact production API

Add the following public values to `divisions.py` with these names, field
orders, and annotations:

```python
@dataclass(frozen=True)
class TwinMutationSummary:
    status: Literal["applied", "already_applied", "no_changes"]
    accepted_count: int
    nodes_before: int
    nodes_after: int
    edges_before: int
    edges_after: int
    edges_removed: int
    edges_added: int
    edge_symmetric_difference: int
    isolated_donors: int


class TwinMutationError(RuntimeError):
    reason: str

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def apply_twin_only_v1_plan(
    nodes_by_id: dict[int, dict[str, object]],
    current_edges: list[dict[str, object]],
    plan: TwinPlan,
) -> tuple[list[dict[str, object]], TwinMutationSummary]:
    ...
```

Import `Literal` from `typing`; do not replace the status strings with an enum.
The function receives no config, dataset, stats, model, callback, or cache.  It
must be deterministic and have no filesystem, clock, random, logging, or
network effect.

Add one private helper family in the same module to compare frozen snapshots:

```python
def _twin_frozen_token(value: object) -> tuple[object, ...]:
    ...
```

It returns a recursively hashable, type-tagged semantic token.  Exact built-in
types have distinct tags; Python floats use their IEEE-754 binary64 bytes
(therefore preserving NaN payload/sign and signed zero); complex values use
the two component binary64 byte strings; bytes are unchanged; tuples are
ordered token tuples; frozensets become frozensets of tokens; mapping items
remain ordered key/value token pairs; and every `TwinFrozen*` dataclass is
tagged and includes all fields recursively.  Array byte content is exact and
object-array tuple content is recursive.  Reject anything outside the valid
frozen tree from section 5.3.  Do not use `repr`, hash values, locale, JSON
coercion, or ordinary equality.  This private token is not a serializer,
artifact format, inverse decoder, or R1c debug-codec replacement.

`TwinMutationError.reason` is machine-readable.  Its complete allowed set is:

```text
invalid_plan_type
plan_validation_failed
plan_counter_schema
plan_counter_value
plan_conservation
plan_acceptance
plan_candidate
node_mapping
current_graph_invalid
partial_application
current_graph_mismatch
post_invariant
```

Every failure raises `TwinMutationError`; do not leak a `KeyError`,
`AssertionError`, NumPy truth-value error, or incidental exception.  Preserve
the original exception only as `__cause__` where useful.  Do not put dynamic
IDs or exception prose in `reason`.

The function returns only a new-or-existing edge list and the immutable
summary.  It never returns, replaces, or mutates `nodes_by_id`.

## 4. Atomicity and identity contract

The call is a transaction over caller-owned Python objects.

Before validation completes, the mutator may allocate private snapshots and
temporary containers only.  It must not write to:

- the `nodes_by_id` mapping;
- any node-row mapping or any object nested below it;
- the `current_edges` list;
- any current edge-row mapping or any object nested below it;
- `plan` or anything reachable from it; or
- global/module state.

On every failure, every input object and nested object is observably unchanged,
including mapping insertion order and object identity.  There is no partial
result and no rollback path that first mutates caller state.

On first successful application with `k > 0`:

- the returned list is a newly allocated list;
- `nodes_by_id` is the exact same mapping object as before and every node row
  and nested metadata object retains identity and insertion order;
- each unaffected edge row is the exact original row object;
- every object nested under an unaffected edge row retains identity;
- surviving edge rows remain in their original relative order; and
- only the `k` newly appended replacement rows are newly allocated.

The mutator must not deep-copy surviving rows.  These identity guarantees apply
at the pure boundary, before downstream passes.  A downstream prune may create
a new node mapping; that does not weaken this pure-boundary requirement.

For a successful direct idempotent no-op, section 8 requires the returned edge
list to be the exact `current_edges` object.  For a valid zero-acceptance plan,
the returned edge list is also the exact `current_edges` object.

## 5. Plan validation before graph classification

Validation order is binding.  Complete steps 5.1 through 5.5 before deciding
whether the current graph is pre-state, post-state, or invalid.  The first
failing step determines the reason.

### 5.1 Top-level type and planner failure

1. `type(plan) is TwinPlan`; otherwise `invalid_plan_type`.
2. If `plan.validation_reason is not None`, require a nonempty exact `str` and
   then raise `plan_validation_failed`.  A validation-failed planner result is
   never mutable, even when it has zero accepted candidates.
3. If validation reason is `None`, require exact tuple types for `nodes`,
   `edges`, `candidates`, `accepted_candidates`, `decisions`, and
   `debug_records`, and exact `TwinFrozenMapping` for `counters`; otherwise
   `plan_acceptance`.

### 5.2 Counter schema and values

Require `tuple(plan.counters) == _TWIN_COUNTER_KEYS` exactly, with no missing,
extra, or reordered key.  Failure is `plan_counter_schema`.

Every value must have exact type `int` (not `bool`) and be nonnegative.  Failure
is `plan_counter_value`.  R2 neither adds to nor changes `_TWIN_COUNTER_KEYS`.

Require all R1b conservation equations, including:

```text
enumerated == sum(nearest/eligibility first-failure counters) + eligible
eligible == accepted + rejected_conflict + rejected_frame_cap + rejected_video_cap
planned_edges_removed == planned_edges_added == accepted
edges_removed == edges_added == 0
isolated_donors == accepted
len(accepted_candidates) == accepted
accepted <= examined_frames
```

Also require the configured-independent facts encoded by the plan: accepted
frames are unique, so accepted count equals the number of distinct accepted
frames, and accepted count is at most 2.  This v1 fact follows from the frozen
cap of one per frame and two per video; R2 does not read config.  Any
conservation failure is `plan_conservation`.

### 5.3 Immutable snapshot structure

Require exact R1b dataclass types.  All ID/time fields must have exact type
`int`, not `bool`; all required floating fields must have exact type `float`
and be finite; `gap_synthetic` must have exact type `bool`.

For `plan.nodes`:

- node IDs are unique;
- each `(t,z,y,x)` is valid and finite; and
- tuple order is strictly increasing by node ID, matching R1b canonical order.

For `plan.edges`:

- `input_position` values are unique, contiguous `0..len(edges)-1`, and the
  tuple is in R1b canonical `(source_id,target_id,input_position)` order;
- endpoint pairs are unique;
- endpoints exist in the node snapshot;
- every edge is exactly `t -> t+1`;
- indegree is at most 1 and outdegree at most 2; and
- `metadata` is exact `TwinFrozenMapping` and contains a lossless frozen
  snapshot of the complete input edge row.

R2 must use the already adopted R1b frozen-value machinery.  Do not add a
second equality/codec that assumes ordinary JSON, primitive keys, finite-only
metadata, or a typical GEFF row.

Recursively validate each frozen metadata tree.  Only the exact immutable
outputs supported by R1b are allowed: `None`, exact built-in scalar/bytes
values (including nonfinite float and complex values), tuples, frozensets,
`TwinFrozenMapping`, `TwinFrozenDType`, `TwinFrozenStructuredScalar`,
`TwinFrozenNumpyScalar`, `TwinFrozenArray`, and `TwinFrozenBuffer`, with their
field types and internal length/shape/content relationships valid.  Reject a
mutable container, arbitrary object, subclass used in place of an exact frozen
type, or malformed frozen dataclass as `plan_candidate`.  Metadata mapping item
order is semantic and must be preserved; frozenset order is not.

The required internal checks are bounded and concrete: shape entries are exact
nonnegative ints; stride entries are exact signed ints; array shape/stride
ranks agree; buffer strides are either empty (the R1b `None` normalization) or
have the shape rank; non-object array byte length is
`prod(shape)*itemsize`; object-array content tuple length is `prod(shape)`;
NumPy scalar byte length is its dtype itemsize; buffer content length is
`prod(shape)*itemsize`; dtype scalar flags/integers/strings/names have their
declared exact types; and structured-scalar field names are unique exact
strings.  Do not attempt to reconstruct a live NumPy object or execute
object-array content during this validation.

Any failure in this subsection is `plan_candidate`, except invalid graph-wide
duplicate/dangling/time/degree structure, which is `current_graph_invalid`
only after a well-formed plan has been established and the current graph is
examined.

### 5.4 Decisions and acceptance order

Require:

- every entry of `candidates` has exact type `TwinCandidate`;
- every entry of `decisions` has exact type `TwinResolutionDecision`;
- `len(decisions) == len(candidates)`;
- `decision.candidate is candidates[i]` for each position;
- accepted decisions have exact `accepted is True` and `reason is None`;
- rejected decisions have exact `accepted is False` and reason in the frozen
  R1b resolution set `conflict`, `frame_cap`, or `video_cap`;
- `accepted_candidates` is exactly the identity-preserving subsequence of
  decision candidates whose decisions are accepted; and
- candidates and decisions are in nondecreasing complete `sort_key` order.

Do not sort again in R2.  `accepted_candidates` tuple order is the replacement
edge append order.  Any failure is `plan_acceptance`.

### 5.5 Candidate integrity

For every candidate, require all of the following or raise `plan_candidate`:

- the six role IDs `P,Q,A,B,A2,B2` are pairwise distinct and exist in
  `plan.nodes`;
- role times are exactly `t(P)=t(Q)=frame`, `t(A)=t(B)=frame+1`, and
  `t(A2)=t(B2)=frame+2`;
- all six nodes have `gap_synthetic is False`;
- `deepcenter_decision` has exact type `TwinDeepCenterDecision`, has
  `accepted is True`, has `reason is None`, and has a finite exact-float raw
  score equal to `raw_deepcenter_score`;
- `removed_edge` has exact type `TwinEdgeRecord`, endpoints exactly `Q,B`, and
  exact frozen metadata equal to the matching snapshot edge at `Q,B`;
- `planned_edge` has exact type `TwinPlannedEdge`, endpoints exactly `P,B`, and
  `edge_prob is None` by identity;
- each stored distance/growth/raw score and the first three sort-key components
  is exact `float` and finite;
- all integer sort-key components have exact type `int` and equal the role IDs;
- the complete sort key equals the R1b formula from candidate fields; and
- independently recomputing `d(P,Q)`, `d(P,A)`, `d(P,B)`, `d(A,B)`, and
  `d(A2,B2)` from the immutable plan node coordinates with the existing twin
  distance helper produces finite Python floats exactly equal to the five
  stored distances;
- recomputed `d(A2,B2)-d(A,B)` exactly equals `divergence_growth`; and
- recomputed `d(P,B)` exactly equals `planned_edge.distance_um`.

For every candidate, require its `P->A`, `Q->B`, `A->A2`, and `B->B2` edges to
exist in the plan snapshot and require `P->B` not to exist.  Require P's
complete outgoing set to be exactly `{P->A}`, Q's complete incoming set to be
empty and complete outgoing set exactly `{Q->B}`, A's complete outgoing set
exactly `{A->A2}`, and B's complete outgoing set exactly `{B->B2}`.  Across
accepted candidates, require disjoint six-node role sets, distinct removed
endpoints, and distinct planned endpoints.  Those accepted-only checks prove
that each accepted donor Q becomes isolated and P becomes a valid two-child
fork at the pure boundary.  Failure is `plan_candidate`.

## 6. Current node and edge match

### 6.1 Node mapping

The current node key set must equal the plan node-ID set exactly.  Every key
must have exact type `int`, and every row must be a dict whose `node_id` has
exact type `int` equal to its key.  Reading `t,z,y,x,gap_synthetic` through the
same R1b normalization must produce the corresponding plan node with exact
integer/bool values and bit-exact finite coordinate floats under
`_twin_frozen_token`.  Failure is `node_mapping`.

R1b intentionally snapshots only those six core node fields.  Arbitrary extra
node-row keys are therefore outside plan/current comparison: R2 must neither
read nor normalize them.  They are still protected by the identity and
non-mutation rules in section 4.  This is the only supportable boundary; R2
must not pretend the R1b plan contains extra node metadata.

Consequently, direct pre/post classification authenticates the complete core
node snapshot plus the complete ordered edge graph, but cannot authenticate
extra node metadata across two separate calls.  An extra node value changed by
the caller between applications neither blocks nor proves `already_applied`.
The mutator still leaves whatever extra values it receives untouched.  A
caller needing cross-call provenance for extra node metadata must retain an
external snapshot; adding one to `TwinPlan` is an R1b API change and outside
R2.

### 6.2 Current edge normalization

Normalize every current edge with the adopted R1b lossless freezer, assigning
its current list index as `input_position`.  Reject with
`current_graph_invalid` if any row is not a dict, cannot be losslessly frozen,
has a boolean/non-`Integral` endpoint, is dangling, is not `t -> t+1`, or
duplicates an endpoint pair.  As R1b does, canonicalize valid non-boolean
`Integral` endpoints to built-in `int`; do not demand built-in ints in an edge
row that R1b accepted.

Defer only the indegree/outdegree cap check until after the exact partial-state
classification in section 8.  An addition-only interrupted candidate can
temporarily give B indegree 2; it must receive the more specific
`partial_application` reason.  A remaining unrecognized graph with indegree
greater than 1 or outdegree greater than 2 receives `current_graph_invalid`.

The complete frozen metadata includes endpoint fields and every arbitrary
nested value.  Equality is equality of `_twin_frozen_token` results; never use
ordinary dataclass/dict equality on arrays, NaNs, signed zeros, or complex
special values, and never coerce keys or values.

### 6.3 Exact pre-state

First derive `plan_edges_by_input_position` by sorting the already validated
`plan.edges` on `input_position`.  R1b stores `plan.edges` in canonical endpoint
order, not caller-row order.  This reconstruction is mandatory and must not be
confused with candidate acceptance order.

The exact pre-state is:

```text
len(current_edges) == len(plan.edges)
and for every i:
    frozen(current_edges[i], input_position=i) == plan_edges_by_input_position[i]
```

This is a whole ordered graph match, not merely an endpoint-set match.  Any
unrelated edge reorder, metadata drift, insertion/deletion, or endpoint change
means the current graph is not the pre-state.

### 6.4 Mechanically expected post-state

Construct the expected post-state privately from
`plan_edges_by_input_position` and `accepted_candidates`:

1. remove each exact accepted `Q->B` snapshot row;
2. preserve every other snapshot row in its original order;
3. append one exact replacement row per accepted candidate in acceptance order;
4. each replacement mapping has exact insertion order and values:

```python
{
    "source_id": candidate.p,
    "target_id": candidate.b,
    "distance_um": recomputed_distance,
    "edge_prob": None,
}
```

No donor metadata is copied.  The recomputed distance is from the immutable
plan coordinates, using the same physical scale/helper as R1b.  It must first
pass the exact-equality checks in section 5.5.

For post-state comparison, compare the ordered sequence of exact
`(source_id,target_id,metadata)` records.  Do not compare historical
`input_position`: surviving rows shift when an earlier donor row is removed,
and appended rows have new current indices.  The exact post-state requires the
current sequence to equal the complete expected semantic sequence.  A row with
the correct endpoints but copied probability, extra key, missing key,
different key order, altered distance, or different float representation is
not the expected post-state.

## 7. First application algorithm

After plan validation and current normalization:

1. If `k == 0`, require exact pre-state.  Return the exact input list and the
   `no_changes` summary in section 9.  Any drift is
   `current_graph_mismatch`.
2. If `k > 0` and current is exact pre-state, allocate a new result list.
3. Traverse `current_edges` once in its existing order.  Omit exactly the
   accepted `Q->B` rows whose complete frozen snapshots match
   `candidate.removed_edge`; append every other original row object unchanged.
4. Recompute and append each exact four-key replacement dict in acceptance
   order.
5. Validate the complete temporary result against section 10.
6. Return the temporary list only after all validation succeeds.

Endpoint equality alone is never enough to select the removed row.  The
complete immutable metadata must agree with the plan.  There is no mutation of
the old list followed by append, and no partially returned list.

Complexity must be bounded by the input: `O(|nodes| + |edges| + k)` expected
time and `O(|nodes| + |edges| + k)` auxiliary memory, excluding the already
materialized plan.  No quadratic scan per accepted candidate is allowed.

## 8. Direct second application and partial states

Direct API idempotence is explicit and narrow.

For `k > 0`, classify in this exact order after basic row normalization:

- exact pre-state: apply once and return `status="applied"`;
- exact mechanically expected post-state: perform no writes, return the exact
  `current_edges` list object and `status="already_applied"`;
- exact partial state: raise `TwinMutationError("partial_application")`;
- otherwise, an indegree/outdegree violation is `current_graph_invalid`;
- every other graph is `current_graph_mismatch`.

An exact partial state is obtained from the exact pre-state by independently
performing any nonempty proper subset of the `2*k` frozen operations (remove
the exact donor row; append the exact replacement row), while keeping all
survivors and appended replacements in their prescribed relative orders.  The
all-unperformed mask is pre-state and the all-performed mask is post-state, so
neither is partial.  Because frozen v1 has `k<=2`, classification is bounded;
an implementation may enumerate the at most 16 operation masks or use an
equivalent linear classifier.  This definition includes removal-only,
addition-only, and mixed candidates, without treating unrelated drift as an
interrupted application.

The classification must use the complete core node snapshot and entire ordered
edge graph/metadata, subject only to the explicit extra-node boundary in
section 6.1.  It is not legal to call a graph already applied merely because
all `P->B` endpoints are present.  Unrelated edge or core-node drift cannot be
hidden by the idempotence branch.

For `k == 0`, there is only one state.  Exact pre-state returns
`status="no_changes"`; drift raises `current_graph_mismatch`.

The production pipeline is a fresh single-application path.  It must never
silently accept `already_applied`.  If the mutator returns that status from the
pipeline hook, the adapter raises `RuntimeError` before downstream processing
or stats assignment.  This guard catches duplicate wiring or a reused mutated
graph.  The direct mutator behavior remains useful for explicit callers and
tests; it is not a pipeline retry mechanism.

## 9. Exact summaries

Let `N=len(nodes_by_id)`, `E=len(current_edges)`, and
`k=len(plan.accepted_candidates)`.

First applied result:

```text
status = "applied"
accepted_count = k
nodes_before = nodes_after = N
edges_before = edges_after = E
edges_removed = edges_added = isolated_donors = k
edge_symmetric_difference = 2*k
```

Exact already-applied no-op:

```text
status = "already_applied"
accepted_count = k
nodes_before = nodes_after = N
edges_before = edges_after = E
edges_removed = edges_added = 0
edge_symmetric_difference = 0
isolated_donors = 0
```

Zero-acceptance no-op:

```text
status = "no_changes"
accepted_count = 0
nodes_before = nodes_after = N
edges_before = edges_after = E
edges_removed = edges_added = 0
edge_symmetric_difference = 0
isolated_donors = 0
```

Summary removal/addition counts are effects of this call, not historical facts
inferred from the current graph.  The plan's R1 counters retain their separate
planned meaning.

## 10. Pure-boundary invariant proof

Before returning an `applied` result, validate the complete temporary graph.
Any failure is `post_invariant`, and the caller inputs remain unchanged.

Require:

- node mapping object, node key set, node-row identities, complete row contents,
  nested identities, and insertion orders are unchanged;
- edge count is exactly E;
- exactly k original complete frozen rows were removed;
- exactly k exact replacement rows were added;
- endpoint sets before and after each have size E;
- endpoint-set symmetric difference has size exactly `2*k`;
- surviving original rows retain their identity, nested identities, original
  relative order, and complete metadata;
- replacement rows are the final k rows in acceptance order and have only the
  four exact keys/values in section 6.4;
- no duplicate or dangling endpoint pair exists;
- every edge is exactly `t -> t+1`;
- every node has indegree at most 1 and outdegree at most 2;
- each accepted Q has degree zero; and
- no nonaccepted endpoint pair changed.

For arbitrary extra node metadata, “contents unchanged” is established by the
write-free implementation and exact mapping/row/nested object identities; do
not traverse, compare, serialize, or execute unsupported caller objects merely
to prove this fact.  Core fields and all supported edge metadata still receive
the explicit bit-exact checks above.

The symmetric difference is over endpoint pairs, because complete row objects
are metadata-bearing and unhashable.  It is a pure-boundary assertion only.
Do not assert `2*k` after division geometry, isolated pruning, short-track
filtering, linefit, CSV serialization, or arm comparison.

## 11. Pipeline routing and ordering

### 11.1 R1c dependency placeholders

At this base, the following semantic R1c operations exist only in the reviewed
task document.  They are intentionally named placeholders here, not invented
production symbols:

```text
<R1C_NON_DRY_GUARD>
<R1C_PLAN_HOOK>
<R1C_COUNTER_MERGE_HOOK>
<R1C_DEBUG_ALLOCATION_HOOK>
<R1C_DEBUG_COLLECTOR_TYPE>
<R1C_RUN_COLLECTOR_FACTORY>
```

R2 must not implement guessed functions with those names.  Section 13 must
replace each placeholder with the one exact landed symbol or inline code
location and freeze its signature/order before source work begins.

### 11.2 Exact pre-linefit order

The full enabled order remains:

```text
all-node centroid refinement
raw dangling/time/distance filtering
motion relink
single-parent repair
single-child repair
single-frame gap close
strict gap2
safe divisions
<R1C_PLAN_HOOK> using shared frame/heatmap caches
<R1C_COUNTER_MERGE_HOOK>
<R1C_DEBUG_ALLOCATION_HOOK>
if planner validation failed: no mutation
elif STEAL_TWIN_DRY_RUN: no mutation
else: apply_twin_only_v1_plan transaction
division geometry filter
isolated-node prune
short-track filter
return pre-linefit checkpoint boundary
linefit smoothing in filter_output_graph only
```

Planning, counter merge, and debug allocation precede mutation so dry and
candidate arms have identical pre-mutation plan/decision/sort/planner-counter
artifacts.  R2 does not move or duplicate those R1c actions.  A collector
encoding/allocation failure occurs before mutation and therefore cannot leave a
mutated graph with missing debug state.

The mutation receives the same current node mapping and edge list that were
passed to the planner.  No intervening pass may alter them.  The existing
centroid-refined node coordinates are already part of the immutable plan.

### 11.3 Off, dry, candidate, and validation failure

The exact routing table is:

| Master/mode state | Planner | R1 counters/debug | Mutation | R2 counters |
|---|---:|---:|---:|---:|
| master off or mode not `twin_only_v1` | no | no | no | all zero |
| mode on, dry-run true, valid plan | yes | yes | no | all zero |
| mode on, dry-run true, failed plan | yes | failure only | no | all zero |
| mode on, dry-run false, failed plan | yes | failure only | no | all zero |
| mode on, dry-run false, valid `k=0` | yes | yes | no-op call | stage counts as section 12 |
| mode on, dry-run false, valid `k>0` | yes | yes | one transaction | stage counts as section 12 |

Planner validation failure remains fail-closed with no graph mutation; it is
not an exception if R1b/R1c define it as a returned failure plan.  Mutator,
collector, or adapter contract violations are exceptions and abort the dataset
before downstream output.

### 11.4 Removing the R1c non-dry guard

After section 13 is pinned, remove only `<R1C_NON_DRY_GUARD>` that currently
raises because ST-R2 is unavailable.  Preserve every other entry guard,
config/profile lock, loader check, debug path alias check, collector atomicity
rule, and failure order.

The replacement validation must occur at the same run/direct-call boundaries:

- direct `filter_output_graph_pre_linefit` and `filter_output_graph`;
- `run_postproc` before detector/model loading and output creation; and
- `save_prelinefit_checkpoint` before detector/model loading and checkpoint
  creation.

The new candidate non-dry path is allowed only for the exact locked
`twin_only_v1` mode.  Do not weaken the profile or accept another mode.

### 11.5 Checkpoint and relinefit

`save_prelinefit_checkpoint` plans and, in candidate non-dry mode, mutates once
before geometry/prune/short.  Its pickle contains that final pre-linefit graph
and final per-dataset stats.

`run_relinefit` must never plan, score, collect debug records, or mutate graph
topology.  It consumes the already mutated checkpoint and may update only the
linefit-owned R2 coordinate counter described below.  Re-running relinefit does
not call the direct idempotence branch.

## 12. Frozen telemetry and ownership

### 12.1 R1 counters retained

Keep `_TWIN_COUNTER_KEYS` byte-for-byte and in the same order.  R1b owns all
planner values.  R1c owns preseed and whole-mapping merge.  R2 may overwrite,
using assignment rather than increment, only these existing actual-effect keys
after a successful `status="applied"` result:

```text
steal_twin_edges_removed = k
steal_twin_edges_added = k
```

They remain zero for off, dry-run, planner failure, `k=0`, and before a
successful commit.  `steal_twin_isolated_donors` remains planner-owned and
equals planned accepted count; do not overwrite it with the per-call summary.

### 12.2 New R2 counter schema

In `pipeline.py`, add `_TWIN_R2_COUNTER_KEYS` in exactly this order:

```text
steal_twin_mutations_applied
steal_twin_pure_nodes
steal_twin_pure_edges
steal_twin_pure_fork_sources
steal_twin_pure_edge_symmetric_difference
steal_twin_geometry_edges_removed_observed
steal_twin_prune_nodes_removed_observed
steal_twin_prune_edges_removed_observed
steal_twin_short_nodes_removed_observed
steal_twin_short_edges_removed_observed
steal_twin_final_nodes
steal_twin_final_edges
steal_twin_final_fork_sources
steal_twin_linefit_coordinate_changed_nodes_observed
```

`new_stats()` appends these keys after all exact R1c twin keys.  Every value is
an exact nonnegative Python `int`, preseeded to zero.  No key is conditional or
created late.  The existing non-twin counter order remains unchanged.

All R2 keys remain zero for master off, another mode, dry-run, or planner
validation failure.  Thus graph/CSV/non-twin-stat identity is required in those
paths; run-stats gains only the documented zero R2 columns.

For candidate non-dry with a valid plan, ownership is:

- mutation adapter sets `steal_twin_mutations_applied` to k for `applied`, else
  zero for `no_changes`; `already_applied` is rejected by the pipeline;
- mutation adapter sets pure nodes/edges to sizes of its returned graph,
  pure fork sources to the number of sources with exactly two outgoing edges,
  and pure symmetric difference from the summary;
- a small wrapper around the existing division-geometry block assigns the
  nonnegative before-edge minus after-edge count to the geometry field;
- the isolated-prune wrapper assigns before-minus-after node and edge counts to
  its two fields;
- the short-track wrapper assigns before-minus-after node and edge counts to
  its two fields;
- after short-track, the pre-linefit adapter assigns final nodes, edges, and
  fork sources; and
- the direct full-filter or relinefit wrapper snapshots `(z,y,x)` immediately
  before linefit and assigns the number of node IDs whose exact coordinate
  tuple differs immediately after linefit.

These `*_observed` values are whole-pass observations in the candidate graph,
not causal attribution to a particular accepted twin and not candidate-minus-
baseline deltas.  Geometry/prune/short must each be topology-nonincreasing;
linefit must preserve node IDs and edge rows.  A negative removal delta or a
linefit topology change raises before output rather than being clamped.

For a valid non-dry `k=0` call, actual/pure-symmetric/mutation counts are zero,
but pure/final graph size and fork fields and downstream observations are
populated because the candidate adapter ran.  This distinguishes a real empty
plan from master off without adding a separate invocation counter.

`save_prelinefit_checkpoint` stores
`steal_twin_linefit_coordinate_changed_nodes_observed=0`.  `run_relinefit`
loads a copy of checkpoint stats and assigns the linefit value only when the
checkpoint stats prove that the non-dry candidate adapter ran: at least one of
the pure graph size fields is nonzero.  It does not change the checkpoint on
disk.  A graph with zero nodes is already forbidden by the pipeline.

The ordinary full `filter_output_graph` assigns the linefit field after its
single linefit call under the same candidate-non-dry condition.  Dry/off fields
remain zero even if ordinary linefit changes coordinates.

Final baseline/candidate deltas, timing, RSS, and promotion summaries require
two-arm orchestration and belong to ST-R3.  R2 must not add them here.

### 12.3 Counter atomicity

Do not assign any actual or stage R2 counter until the mutator returns
successfully.  Use local before/after measurements for each downstream pass and
assign only after that pass succeeds.  If the dataset aborts, do not create its
stats row or checkpoint payload after the failure.  R2 adds no rollback or
atomicity claim for submission CSVs, earlier dataset checkpoint files, or
other existing run artifacts; R1c's run-level atomic guarantee applies to its
debug collector target only.

The pipeline must assert after mutation:

```text
planned_edges_removed == planned_edges_added == accepted == k
edges_removed == edges_added == mutations_applied == k
pure_edge_symmetric_difference == 2*k
```

For `k=0`, all terms are zero.  Do not infer actual effects from planner
counters without the successful mutator summary.

## 13. Required R1c re-pin appendix

This appendix is intentionally unresolved and is the only known external
design HOLD.

Before implementation, a reviewer must record:

```text
R1c implementation commit: <HOLD>
R1c implementation tree status: <HOLD: must be clean>
divisions.py SHA-256: <HOLD>
pipeline.py SHA-256: <HOLD>
tests/test_public_postproc.py SHA-256: <HOLD>
<R1C_NON_DRY_GUARD>: <HOLD exact file/line/condition>
<R1C_PLAN_HOOK>: <HOLD exact symbol/signature>
<R1C_COUNTER_MERGE_HOOK>: <HOLD exact symbol/signature>
<R1C_DEBUG_ALLOCATION_HOOK>: <HOLD exact symbol/signature>
<R1C_DEBUG_COLLECTOR_TYPE>: <HOLD exact symbol/signature>
<R1C_RUN_COLLECTOR_FACTORY>: <HOLD exact symbol/signature>
shared frame-cache object and owner: <HOLD>
shared heatmap-cache object and owner: <HOLD>
exact plan/merge/allocate call order: <HOLD>
run_postproc finalization order: <HOLD>
save_prelinefit_checkpoint finalization order: <HOLD>
```

The audit must verify R1c against task commit `541a659`, including strict
callback closure, shared cache identity, counter merge, duplicate GEFF node
hard fail, direct-call path/collector combinations, non-dry entry guards,
run-level capacity, deterministic lossless encoding, alias guards, and atomic
collector publication.  If it differs, revise this contract before R2 code.

It is forbidden to resolve a placeholder through reflection, `hasattr`
fallbacks, signature guessing, multiple alternative call paths, or a test-only
production shim.

## 14. Required tests

Add focused tests named `test_steal_twin_r2_*` to the existing test module.
They use tiny in-memory graphs and fakes; no GEFF corpus, model checkpoint,
metric, image set, network, or Kaggle access is allowed.

### 14.1 Pure success and exact row construction

- One accepted candidate removes exact `Q->B`, appends exact `P->B`, preserves
  E, produces `2k=2`, and returns the exact applied summary.
- Two accepted disjoint candidates remove two rows and append replacements in
  accepted-candidate order, independent of removed rows' input positions.
- Replacement key insertion order is exactly source, target, distance,
  edge-probability; probability is `None`; distance is independently
  recomputed and not copied from donor metadata.
- Surviving row, nested mapping/list/array/buffer/object, and node mapping/row/
  nested identities are unchanged.  Original relative edge order is exact.
- Donor rows containing every supported R1b frozen metadata family can be
  matched and removed without ordinary dict/array equality errors.  Include
  float/complex specials, distinct NaN payloads, signed zero, arbitrary mapping
  key types/order, bytes/buffers, frozensets, dtype metadata, structured
  scalars, and object arrays; mapping-order differences remain distinct while
  equivalent frozenset construction order compares equal.

### 14.2 Validation and fail-closed behavior

Parameterize every exact `TwinMutationError.reason`.  Cover wrong top-level
type; failure plan; counter missing/extra/reordered/bool/negative; conservation
forgery; candidate/decision identity or order forgery; role/time/distance/sort
forgery; removed metadata mismatch; and planned probability not `None`.

For every failure, snapshot all input list/mapping bytes or lossless frozen
values and all relevant object identities before the call.  Assert no mutation,
no partial result, no global state change, and no counter assignment.

Cover malformed current rows, duplicate edges, dangling endpoints,
nonconsecutive time, indegree >1, outdegree >2, nonlossless metadata, node key/
row-ID mismatch, core node drift, unrelated edge metadata drift, and edge
reorder.  Exact extra node metadata is ignored for matching but its identity is
preserved.  A second direct call with edge-post-state and caller-modified extra
node metadata follows the documented support boundary and is still
`already_applied`; bit-level core coordinate drift fails `node_mapping`.

### 14.3 Idempotence classification

- Apply once, then call the direct mutator on that exact result and same plan.
  The second call returns the same list object, `already_applied`, and zero
  per-call effects.
- A zero-acceptance plan returns the same list object and `no_changes`.
- For k=1 and k=2, test removal-only, addition-only, every nontrivial operation
  mask, and mixed pre/post candidates as `partial_application`.  Wrong
  replacement metadata/order and unrelated drift must not be accepted as post
  or partial: expect `current_graph_mismatch` when graph invariants hold and
  `current_graph_invalid` when they do not.
- The production adapter rejects `already_applied` before geometry/prune/short.

### 14.4 Pure invariant tests

Prove exact node identity, E-before equals E-after, removed/added k, endpoint
symmetric difference `2k`, donor isolation, no duplicate/dangling, `t->t+1`,
indegree <=1, and outdegree <=2.  Fault-inject a temporary post-result invariant
failure and prove the inputs remain unchanged.

### 14.5 Pipeline routing and order

After the R1c re-pin, spy on the exact landed hooks and require:

- master off and non-twin mode never plan, allocate, mutate, or populate R2;
- dry-run plans/merges/allocates but never mutates and preserves graph/CSV;
- candidate non-dry valid plan calls plan, merge, allocate, mutate exactly once
  at the frozen order and then geometry/prune/short;
- validation-failed plans never mutate in dry or non-dry;
- the old non-dry-unavailable exception is gone only for the exact valid mode;
- collector or allocation failure occurs before mutation;
- mutator failure prevents downstream passes and dataset publication;
- direct prelinefit/full, `run_postproc`, and checkpoint paths agree; and
- `run_relinefit` never plans, collects, or mutates.

Assert the shared R1c frame and heatmap cache object identities remain exactly
the objects used by safe division/planner callbacks.  R2 must not allocate
replacement caches.

### 14.6 Telemetry ownership

- New stats preseed exact ordered zero keys after R1 keys.
- Dry/off/failure keeps every R2 value zero and every existing non-twin value
  unchanged.
- Applied k sets existing actual removed/added, mutation count, pure sizes,
  forks, and exact `2k`; a successful k=0 sets only stage sizes/observations.
- Synthetic geometry, prune, and short fixtures verify each wrapper measures
  only its immediate before/after whole-pass delta.
- Full filter counts exact linefit coordinate tuple changes; checkpoint stores
  zero; relinefit computes on its stats copy without touching disk or topology.
- A topology-increasing downstream pass, negative delta, or linefit topology
  change hard-fails instead of clamping.

### 14.7 Profile and regression identity

- Frozen base1/e23 effective configs are unchanged.
- Master-off and non-twin graph objects, final CSV bytes, and all old non-twin
  stats match the pre-R2 base; only preseeded zero R2 run-stats columns differ.
- Twin dry-run graph objects and final CSV bytes match the same input with
  mutation disabled; R1 plan/decision/sort/counter/debug artifacts remain
  identical between dry and candidate before mutation.
- Run the existing lightweight public-postproc suite and all R1/R1c focused
  tests.  Do not weaken or delete an assertion to land R2.

## 15. Allowed implementation files and commands

After the HOLD is cleared, an implementation task may edit only:

```text
src/biohub/public_postproc/divisions.py
src/biohub/public_postproc/pipeline.py
tests/test_public_postproc.py
```

Any need to change config, DeepCenter, graph operations, CSV code, another test
module, or an analysis contract is a new review and HOLD.  Generated outputs,
fixtures from real data, and vendored dependencies are forbidden.

Allowed verification after implementation is limited to syntax/compile,
focused in-memory R2 tests, existing R1/R1c tests, and the ordinary lightweight
public-postproc unit suite.  Official metrics, full dataset runs, image/model
inference, network, Kaggle, and ST-R3 arm evaluation are forbidden in R2.

## 16. Implementation handoff sequence

1. Land and independently review R1c implementation.
2. Complete section 13 against its clean exact commit and hashes.
3. Re-read this entire contract and the resulting exact diff.
4. Implement the pure API and pure tests first.
5. Implement counter preseed/ownership and pipeline routing using only the
   pinned R1c symbols.
6. Add downstream observation and checkpoint/relinefit tests.
7. Run only the allowed lightweight verification.
8. Independently adversarial-review atomicity, identity, second application,
   R1 artifact parity, and scope.
9. Commit only the allowed files if the starting tree and final diff are clean.

Do not combine the R1c implementation and R2 implementation in one review or
commit.  The dependency boundary must remain auditable.

## 17. Exit criteria

R2 is SHIP only when all of the following are true:

- section 13 contains no placeholder and an independent reviewer confirms the
  landed R1c implementation matches its task;
- the exact pure API, reason set, summaries, first/second-application behavior,
  identity rules, and pure `2k` invariants are implemented and tested;
- every failure is transactional and fail-closed;
- pipeline order is exact and the R1c non-dry guard alone is replaced;
- master off, other modes, and dry-run are graph/CSV identity paths;
- planner versus actual versus downstream counter ownership is exact;
- checkpoint and relinefit have no duplicate planning or mutation;
- all allowed focused/regression tests pass; and
- no source outside the allowed list and no R3/metric/GT/network behavior was
  changed.

At this document base, section 13 is unresolved.  Therefore the binding final
disposition is **HOLD_R1C_IMPLEMENTATION_DEPENDENCY**, with no other known
design blocker.
