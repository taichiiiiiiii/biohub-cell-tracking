# ST-R2 binding contract: transactional twin-only mutation adapter

Status: **READY_FOR_IMPLEMENTATION**

This is a design-only implementation handoff.  It freezes the ST-R2 pure
mutation boundary and its pipeline semantics.  ST-R1c has a final amended task
document at commit `7f08e00b2dbb5c2a5cb212b60ea7fbcd3557da9b` and a landed,
independently reviewed production implementation at commit
`f6f4ad75b0a584dc348b75ca038b2e50bc7d2f7b`.  Section 13 pins the exact source
hashes, symbols, signatures, call order, and the only R2 adapter change allowed
at that boundary.  Implementation is authorized only within sections 2, 13,
and 15; any pinned drift returns this contract to HOLD.

The purpose of R2 is deliberately narrow: consume a validated immutable
`TwinPlan`, remove each accepted `Q->B` edge, append its `P->B` replacement,
prove the pure-boundary invariants, and connect that transaction at the already
chosen pipeline hook.  R2 does not change candidate discovery, scoring,
resolution, caps, debug selection, or evaluation.

## 1. Frozen design base

The internal R2 design was hardened against the clean main-repository commit
`b1997fd777faece2c8db226ea323dfe49093ce57`.  The R1c implementation itself is
the separately pinned `f6f4ad7` commit in section 13.  The reviewed files and
SHA-256 digests are:

```text
AGENTS.md
f62b268b3be7607d3571a5e543687bc23da8efb94fda40d6940fa767987a7e5f

analysis/steal_twin_design.md
9e6e7aa320020da0076fe71da3f5fb610b94fa1e27fb13d048e51a0e771c024c

analysis/steal_twin_st_r1_contract.md
54caa99ba0f5637b69366dccf6260e49728bb8380b506a9beafbf1374b08a274

analysis/steal_twin_st_r1c_sol_task.md
cce2b1445e6c3be22bb8862831cc3d9e9884e20a74db4f3727c7df14c2ce3c62

analysis/steal_twin_st_r3_eval_contract.md
18cfa78464b70cc419ed4f6614c39192d0727d85ab3531beb1092b32bb10a169

src/biohub/public_postproc/divisions.py
3009d182b71dd786f1249e17734b2e6dea70e2260b752f6227e810643efb59f4

src/biohub/public_postproc/pipeline.py
96b218494b665b3e41f1a32ae33f7f16a80b71bf9b9c18d93e6168f9ca96786a

tests/test_public_postproc.py
e49fb62138fb97bc758ac1363d95219799c8112941aa597997fd76d9306c7e4c
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
  conflict resolution, frame/video caps, frozen metadata schema/type semantics,
  or counters, apart from the exact common depth boundary in section 2;
- R1c collector allocation, JSON-safe encoding/output, global capacity, atomic
  publish, path alias guards, cache ownership, duplicate-loader policy, or debug
  schema, apart from the exact pre-encoding depth guard in section 2;
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

There is one narrow validation-only exception to the R1b/R1c codec exclusions.
Add `_TWIN_METADATA_MAX_DEPTH = 64` in `divisions.py` and use that exact
constant in the adopted R1b freezer, R2 frozen validator/tokenizer, and the R1c
retained-record plain-value codec.  Each complete raw or frozen metadata value
starts at logical depth zero.  The complete edge row is one such mapping root;
its represented keys and values therefore start at depth one.

Depth is semantic rather than an implementation-container count:

- descending from a raw/frozen tuple or frozenset into an element increments
  depth by one;
- descending from a raw mapping or `TwinFrozenMapping` into each represented
  key or value increments depth by one;
- for a raw `np.dtype` or `TwinFrozenDType`, `descriptor` and non-`None`
  `metadata` are recursive children at depth plus one;
- for a raw structured scalar or `TwinFrozenStructuredScalar`, each represented
  field value is a recursive child at depth plus one;
- for a raw NumPy scalar or `TwinFrozenNumpyScalar`, `dtype` is a recursive
  child at depth plus one;
- for a raw ndarray or `TwinFrozenArray`, `dtype` and each object-content
  element are recursive children at depth plus one; and
- bytearray/memoryview and `TwinFrozenBuffer` have no recursive semantic child.

Representation scaffolding does not add depth.  This includes
`items_snapshot`, mapping item-pair tuples, structured-scalar `fields` and its
name/value pair tuples, object-array `content` storage tuples, and the fixed
`shape`, `strides`, and `names` tuples and their primitive elements.  All other
scalar/bytes fields of a `TwinFrozen*` value are leaves.  The represented
children enumerated above still add exactly one level even though such
scaffolding stores them.

A visit at depth greater than 64 is rejected before that value is traversed.
The R1b freezer and R1c retained-record plain codec raise `TypeError`; R2 maps
the same boundary to `plan_candidate` for a frozen plan or
`current_graph_invalid` for a raw current row.  An active-path cycle is rejected
at the same owning boundary.  Shared acyclic subtrees remain legal and are
visited once per semantic occurrence.

Threading this depth/active-path state through the existing private helper
families must preserve exact accepted types, protocol-call count, mapping/set
semantics, frozen dataclass types/fields, bytes, ordering, and output values for
every input at or below the cap.  It may not add a metadata type, coercion,
schema, serializer, or fallback.  R1c JSONL bytes for every accepted retained
record remain identical; the cap is checked before recursive descent so the
plain codec and `json.dumps` retain ample stack headroom.  Dropped R1c records
continue to skip nested metadata traversal under the R1c contract.  Existing
R1/R1c tests plus exact depth-64/depth-65/cycle tests must prove this narrow
parity.  This is a common resource/safety bound on the single adopted codec,
not a second codec.  Schema and type semantics are unchanged, but R2 explicitly
approves narrowing legacy R1b/R1c behavior for logical inputs deeper than 64 so
every retained value has one deterministic resource boundary.

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

It returns a recursively hashable, type-tagged semantic token within the exact
common depth bound above.  Exact built-in types have distinct tags; Python
floats use their IEEE-754 binary64 bytes (therefore preserving NaN payload/sign
and signed zero); complex values use the two component binary64 byte strings;
bytes are unchanged; tuples are ordered token tuples; mapping items remain
ordered key/value token pairs; and every `TwinFrozen*` dataclass is tagged and
includes all fields recursively.  Array byte content is exact and object-array
tuple content is recursive.

A frozenset token is an order-independent frozenset of exact
`(element_token, multiplicity)` pairs, not merely a frozenset of element
tokens.  Python can retain multiple distinct NaN objects with identical
binary64 bits in one set; collapsing equal element tokens would therefore make
one same-bit NaN indistinguishable from two, or confuse different duplicate-
token distributions.  The multiplicity is an exact positive built-in integer
and preserves this frozen semantic cardinality without introducing iteration
order.

Reject anything outside the valid frozen tree from section 5.3.  Do not use
`repr`, process-random hash values, locale, JSON coercion, or ordinary
equality.  This private token is not a serializer, artifact format, inverse
decoder, or R1c debug-codec replacement.

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

The call is a transaction over caller-owned Python objects with respect to
writes performed by R2 itself.

Before validation completes, the mutator may allocate private snapshots and
temporary containers only.  It must not write to:

- the `nodes_by_id` mapping;
- any node-row mapping or any object nested below it;
- the `current_edges` list;
- any current edge-row mapping or any object nested below it;
- `plan` or anything reachable from it; or
- global/module state.

On every failure, R2 itself leaves every input object and nested object
observably unchanged, including mapping insertion order and object identity.
There is no partial result and no rollback path that first mutates caller
state.

The adopted R1b normalization boundary deliberately accepts some protocol
types rather than exact built-ins: for example a non-boolean `Integral` is
canonicalized with `int()`, and supported mapping/container/buffer values are
read through their normal Python protocols.  Those operations can execute
caller-defined methods.  Side effects performed by such caller code are
outside this transaction guarantee; R2 cannot promise that an adversarial
`__int__`, iterator, mapping method, or buffer provider leaves its own object
or global state unchanged.  R2 must not invoke any protocol beyond what the
adopted R1b freezer/normalizer requires, catch-and-retry a protocol operation,
or itself assign to caller/global state.  No-failure-mutation tests that claim
complete input/global identity use exact built-ins or supported
side-effect-free protocol values; adversarial protocol tests instead prove
single-pass exception containment and absence of R2-owned writes.

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

Validation order is binding.  Complete steps 5.1 through 5.6 before deciding
whether the current graph is pre-state, post-state, or invalid.  The first
failing step determines the reason.

### 5.1 Top-level type and planner failure

1. `type(plan) is TwinPlan`; otherwise `invalid_plan_type`.
2. If `plan.validation_reason is not None`, require a nonempty exact `str` and
   then raise `plan_validation_failed`.  A validation-failed planner result is
   never mutable, even when it has zero accepted candidates.  A malformed
   non-`None` reason type or empty string also maps directly to
   `plan_validation_failed`; do not inspect another plan field first.
3. If validation reason is `None`, require exact tuple types for `nodes`,
   `edges`, `candidates`, `accepted_candidates`, `decisions`, and
   `debug_records`, and exact `TwinFrozenMapping` for `counters`; otherwise
   `plan_acceptance`.

### 5.2 Counter schema and values

Inspect `plan.counters.items_snapshot` directly before invoking its `Mapping`
methods: it must be an exact tuple of exact length-two tuple entries whose keys
are exact built-in strings, and the key sequence must equal
`_TWIN_COUNTER_KEYS` with no missing, extra, duplicate, or reordered key.
Malformed entry shape/key structure and any failure that would otherwise occur
while iterating or indexing the forged mapping are `plan_counter_schema`; do
not leak an unpacking, comparison, or lookup exception.

Every value must have exact type `int` (not `bool`) and be nonnegative.  Failure
is `plan_counter_value`.  R2 neither adds to nor changes `_TWIN_COUNTER_KEYS`.

Require all R1b conservation equations, including:

```text
enumerated == sum(nearest/eligibility first-failure counters) + eligible
eligible == accepted + rejected_conflict + rejected_frame_cap + rejected_video_cap
planned_edges_removed == planned_edges_added == accepted
edges_removed == edges_added == 0
isolated_donors == accepted
len(candidates) == eligible
len(accepted_candidates) == accepted
accepted <= examined_frames
```

Also require the following exact pre-collector coupling:

```text
debug_records_written == debug_records_dropped == 0
```

The planner has not yet passed through the R1c collector at this boundary, so
nonzero debug allocation counters are a forged plan even if every other
conservation equation balances.

Also require accepted count to be at most 2.  The candidate-dependent
configured-independent fact that accepted frames are unique is checked only
after candidate field types are safe to read in section 5.5.  This v1 fact
follows from the frozen cap of one per frame and two per video; R2 does not read
config.  Any conservation failure is `plan_conservation`.

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

Before traversing a `TwinFrozenMapping`, require `items_snapshot` to be an
exact tuple of exact length-two tuples.  Apply the same exact-container-first
rule to every tuple-valued frozen dataclass field.  The validator/tokenizer
tracks active-path object IDs and the exact semantic depth from section 2.  A
forged cycle or a visit at depth 65 is `plan_candidate`; shared acyclic subtrees
remain legal and every valid tree through depth 64 is accepted.  Any internal
traversal/packing/length exception is caught and mapped to `plan_candidate`.
The bound must be checked before descent, so no incidental `RecursionError` may
escape or substitute for the deterministic depth classification.  Validation
must never call
`TwinFrozenMapping.__getitem__`, ordinary dataclass equality, or a method on an
unsupported embedded object before rejecting its exact type.

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

Use `prod(()) == 1`.  Dtype itemsize/alignment are exact nonnegative ints;
buffer itemsize is an exact positive int.  Array flags, buffer readonly, and
dtype flags are exact bools.  `object_content is False` requires exact bytes
content, while `object_content is True` requires exact tuple content.  Dtype
names, when present, are an exact tuple of unique exact strings; metadata is
exact `TwinFrozenMapping` or `None`; every string/bytes field has its exact
built-in type.  Buffer `kind` is exactly `"bytearray"` or `"memoryview"`; the
bytearray form also has the adopted fixed `format="B"`, `itemsize=1`,
one-dimensional shape/stride `(len(content),)/(1,)`, and `readonly is False`.
These checks validate the adopted frozen representation only; they do not
reconstruct or reinterpret a live NumPy dtype, scalar, array, or buffer.

Any failure in this subsection, including duplicate/dangling/nonconsecutive or
degree-invalid structure in the immutable `plan.edges` snapshot, is
`plan_candidate`.  `current_graph_invalid` is reserved for a malformed
`current_edges` graph encountered only after a well-formed plan has been
established and the current graph is examined.

### 5.4 Decisions and acceptance order

Require:

- every entry of `candidates` has exact type `TwinCandidate`;
- every entry of `decisions` has exact type `TwinResolutionDecision`;
- `len(decisions) == len(candidates)`;
- `decision.candidate is candidates[i]` for each position;
- accepted decisions have exact `accepted is True` and `reason is None`;
- rejected decisions have exact `accepted is False` and reason in the frozen
  R1b resolution set `conflict`, `frame_cap`, or `video_cap`;
- the accepted-decision count equals `steal_twin_accepted`, and the exact
  counts of rejected decision reasons `conflict`, `frame_cap`, and `video_cap`
  equal their three corresponding counters;
- `accepted_candidates` is exactly the identity-preserving subsequence of
  decision candidates whose decisions are accepted.

This subsection performs only exact type, identity, exact-bool, and fixed
exact-string/`None` checks.  It must not compare or sort a candidate field
before section 5.5 establishes that field's exact safe type.  Thus a forged
candidate containing an arbitrary `sort_key`, metadata, numeric object, or
other malformed field cannot execute its comparison protocol or leak an
incidental exception here.  `accepted_candidates` tuple order is the
replacement-edge append order.  Any failure is `plan_acceptance`.

### 5.5 Candidate integrity

For every candidate, first complete a structural/type pass before performing
any equality, ordering, arithmetic, tokenization, mapping lookup, or graph
relationship check.  Require the candidate and every nested R1b dataclass to
have its exact type; require every scalar/tuple/`None` field to have its exact
declared safe type; and validate `removed_edge.metadata` with the frozen-tree
rules in section 5.3.  Any exception during the subsequent relationship or
distance checks is caught and mapped to `plan_candidate`; no candidate-owned
comparison/arithmetic protocol may execute.  Then require all of the following
or raise `plan_candidate`:

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

After every candidate is structurally valid, require candidates/decisions to
be in nondecreasing complete `sort_key` order; do not sort again in R2.  Also
require `steal_twin_accepted` to equal the number of distinct accepted
candidate frames.  A sort-order failure is `plan_acceptance`; the accepted-
frame conservation failure is `plan_conservation`.

### 5.6 Debug-record projection

Require `type(plan.debug_records[i]) is TwinDebugRecord` and
`len(debug_records) == len(decisions) == len(candidates)`.  Each debug record
must be the exact field-for-field projection of the decision and its candidate
at the same index.  All records have one homogeneous dataset value whose type
is exact built-in `str` or `None`; the empty record tuple imposes no dataset
value.  `decision` is the exact built-in string `"accepted"` or `"rejected"`
as appropriate, and `reason` is the corresponding exact built-in resolution
string or `None`.

R1b constructs every remaining projected field by passing the candidate field
object directly.  Therefore require identity (`is`), not ordinary equality,
for all six role values, `sort_key`, every distance/growth/raw-score value,
`deepcenter_decision`, `removed_edge`, and `planned_edge`.  This is valid even
for scalar objects because it checks the actual adopted constructor behavior,
and it avoids executing any malformed equality protocol.  Candidate integrity
has already made every projected object safe.  `deepcenter_threshold` must be
an exact built-in float whose binary64 bytes equal the binary64 bytes of the
literal `0.12`.  A record may not describe an equal-but-separately-built
candidate or a different candidate while preserving aggregate counters.

Any malformed debug dataclass/field/dataset/identity/threshold is
`plan_acceptance`.  Perform exact type checks before string or binary64 checks,
catch packing/access exceptions as `plan_acceptance`, and do not use ordinary
dataclass/dict/NumPy equality or the debug JSON codec.

## 6. Current node and edge match

### 6.1 Node mapping

Require `type(nodes_by_id) is dict`; otherwise `node_mapping`.  Before any
key-set comparison or value lookup, iterate that exact dict once and require
every outer key to have exact type `int`, every row to have exact built-in
`dict` type, and each row to contain the five required fields `node_id,t,z,y,x`
under exact built-in string keys.  Locate those required keys and the optional
exact-string `gap_synthetic` key by iterating the exact row and checking only
exact-string keys; do not probe arbitrary extra keys with equality or hash
protocols.  Arbitrary extra keys are not read or compared.  Only after this
complete structural pass may the now-safe exact-int key set be compared with
the plan node-ID set.

Each required `node_id` must have exact type `int` equal to its outer key.
Reading `t,z,y,x` and normalizing an optional `gap_synthetic` through the same
R1b rule must produce the corresponding plan node with exact integer/bool
values and bit-exact finite coordinate floats under `_twin_frozen_token`.
Specifically, an absent `gap_synthetic` normalizes to exact `False`; when the
exact key is present, normalize it exactly as
`bool(row_value == 1)`, once, with any protocol exception mapped to
`node_mapping`.  Never insert the absent key or otherwise change row identity,
contents, or order.  Failure is `node_mapping`.  Catch missing required fields
and every normalization/conversion/finite/token exception as `node_mapping`,
and never retry a caller protocol; the section 4 side-effect boundary still
applies.

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

Require `type(current_edges) is list`; otherwise `current_graph_invalid`.
Normalize every current edge with the adopted R1b lossless freezer, assigning
its current list index as `input_position`.  Reject with
`current_graph_invalid` if any row is not an exact built-in dict, cannot be
losslessly frozen, has a boolean/non-`Integral` endpoint, is dangling, is not
`t -> t+1`, or duplicates an endpoint pair.  As R1b does, canonicalize valid
non-boolean `Integral` endpoints to built-in `int`; do not demand built-in ints
in an edge row that R1b accepted.

Check row/dict/required-field structure before endpoint conversion or metadata
freezing.  The single adopted freezer and tokenizer enforce the exact section-2
logical depth: valid values through depth 64 are accepted; an active-path cycle
or visit at depth 65 is `current_graph_invalid`.  Catch endpoint conversion,
buffer, and other malformed normalization exceptions under the same reason; do
not leak `TypeError`, `KeyError`, unpacking errors, a NumPy truth-value exception,
or an incidental `RecursionError`, and never retry a caller protocol.  Check the
cap before descent rather than relying on the interpreter recursion limit.

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

1. If `k == 0` and the graph is the exact pre-state, return the exact input
   list and the `no_changes` summary in section 9.  Otherwise apply the deferred
   degree-cap check from section 6.2: a violation is `current_graph_invalid`,
   and any remaining well-formed drift is `current_graph_mismatch`.
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

Let `M` be the total number of frozen/raw metadata elements plus their
byte-content length traversed while validating and tokenizing the plan and
current edge rows.  Complexity must be bounded by the actual input:
`O(|nodes| + |edges| + k + M)` expected time and
`O(|nodes| + |edges| + k + M)` auxiliary memory.  Frozenset token multiplicity
uses expected constant-time token counting and the order-independent
`frozenset` token from section 3; it does not sort members.  The already
materialized plan object itself is excluded, but private traversal, active-path,
validation, and token structures are not.  No quadratic scan per accepted
candidate or repeated full metadata freeze/token pass per candidate is
allowed.

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

For `k == 0`, there is only one accepted state.  Exact pre-state returns
`status="no_changes"`; a non-pre graph with indegree greater than 1 or
outdegree greater than 2 raises `current_graph_invalid`, and every other
well-formed drift raises `current_graph_mismatch`.

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

- node mapping object, ordered node-key identities, node-row identities, each
  row's ordered key identities, and every top-level key-to-value binding are
  unchanged;
- edge count is exactly E;
- exactly k original complete frozen rows were removed;
- exactly k exact replacement rows were added;
- endpoint sets before and after each have size E;
- endpoint-set symmetric difference has size exactly `2*k`;
- surviving original rows retain their identity, original relative order, and
  complete already-normalized metadata;
- replacement rows are the final k rows in acceptance order and have only the
  four exact keys/values in section 6.4;
- no duplicate or dangling endpoint pair exists;
- every edge is exactly `t -> t+1`;
- every node has indegree at most 1 and outdegree at most 2;
- each accepted Q has degree zero; and
- no nonaccepted endpoint pair changed.

For arbitrary extra node metadata, unchanged nested state is a write-free
implementation guarantee, not a recursive runtime observation.  The pure
mutator may record shallow mapping/row/key/value identities but must not
traverse, compare, serialize, or execute an unsupported caller object merely to
prove this fact.  Caller-protocol side effects remain outside section 4.  Core
fields and all supported edge metadata still receive the explicit bit-exact
checks above.

The symmetric difference is over endpoint pairs, because complete row objects
are metadata-bearing and unhashable.  It is a pure-boundary assertion only.
Do not assert `2*k` after division geometry, isolated pruning, short-track
filtering, linefit, CSV serialization, or arm comparison.

## 11. Pipeline routing and ordering

### 11.1 Pinned R1c semantic labels

The following angle-bracketed names are semantic labels for the exact landed
symbol or inline locations pinned in section 13; they are notation in this
contract, not production identifiers:

```text
<R1C_NON_DRY_GUARD>
<R1C_PLAN_HOOK>
<R1C_COUNTER_MERGE_HOOK>
<R1C_DEBUG_ALLOCATION_HOOK>
<R1C_DEBUG_COLLECTOR_TYPE>
<R1C_RUN_COLLECTOR_FACTORY>
```

R2 must not implement functions with those label names.  Use only each exact
landed symbol or inline location resolved in section 13, with its pinned
signature and order.

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
R2 exact plan/failure-envelope guard
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

The mutation receives the same current node mapping and edge list from which
the planner snapshots were materialized.  The planner itself receives
`tuple(nodes_by_id.values())` and `tuple(edges)`, not those container objects;
no intervening pass may alter the source mapping, list, rows, or contents.  The
existing centroid-refined node coordinates are already part of the immutable
plan.

### 11.3 Off, dry, candidate, and validation failure

The exact routing table is:

| Master/mode state | Planner | R1 counters/debug | Mutation | R2 counters |
|---|---:|---:|---:|---:|
| master off, regardless of mode value | no | no | no | all zero |
| master on, mode/profile lock not exact `twin_only_v1` | hard fail at entry boundary | no | no | no serialization |
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

With section 13 pinned, remove only `<R1C_NON_DRY_GUARD>` that currently
raises because ST-R2 is unavailable.  Preserve every other entry guard,
config/profile lock, loader check, debug path alias check, collector atomicity
rule, and failure order.

The replacement validation must occur at the same run/direct-call boundaries:

- direct `filter_output_graph_pre_linefit` and `filter_output_graph`;
- `run_postproc` before detector/model loading and output creation; and
- `save_prelinefit_checkpoint` before detector/model loading and checkpoint
  creation.

“At the `filter_output_graph` boundary” may be satisfied only by the exact
landed call-through to the guarded pre-linefit function if section 13 confirms
that guard runs before any full-filter work.  Do not add a second guard or
change failure ordering merely to duplicate the check at both symbols.

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

All R2 keys remain zero for master off (regardless of the otherwise inert mode
value), dry-run, or planner validation failure.  Thus graph/CSV/non-twin-stat
identity is required in those paths; run-stats gains only the documented zero
R2 columns.  Master on with another mode is not an inert zero-counter path: it
hard-fails at the entry boundary before planner/model/output activity under
section 11.4.

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
- the direct full-filter or relinefit wrapper first requires every pre-linefit
  `(z,y,x)` binding to be an exact built-in finite `float`, then snapshots it as
  three binary64 byte tokens immediately before linefit and assigns the number
  of node IDs for which at least one token differs immediately after linefit.
  A bad pre-coordinate hard-fails before linefit is called.  Ordinary tuple
  equality is forbidden because it collapses `-0.0` and `+0.0`.  Every
  post-linefit coordinate must also be an exact built-in finite `float` before
  its token is formed.

These `*_observed` values are whole-pass observations in the candidate graph,
not causal attribution to a particular accepted twin and not candidate-minus-
baseline deltas.  Geometry/prune/short must each be topology-nonincreasing.
The linefit wrapper uses only shallow, non-recursive identity snapshots.  Across
the call require: the node mapping identity; its ordered outer-key identities;
the corresponding node-row identities; each row's ordered key identities; and
every non-coordinate top-level key-to-value binding identity.  Require the edge
list identity, ordered edge-row identities, each edge row's ordered key
identities, and every top-level edge key-to-value binding identity.  Only the
three coordinate binding values may change, and their post-values must satisfy
the exact finite-float rule above.  Identify coordinate bindings only through
exact built-in string keys and compare all preserved keys/values pairwise with
`is`; do not use container equality.

Do not recursively traverse, freeze, serialize, compare, or call a protocol on
an arbitrary extra-node value or nested edge value for this linefit guard.
Nested custom in-place state is not runtime-observable at this boundary.  The
existing linefit implementation and the R2 wrapper themselves remain write-free
for such objects; caller-protocol side effects remain excluded by section 4.
Validate the shallow snapshots before assigning the linefit counter or writing
output.  A negative removal delta, invalid pre/post coordinate, or observable
shallow linefit identity/topology/binding change raises rather than being
clamped or serialized.

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

## 13. Pinned R1c implementation appendix

An independent SOL audit returned SHIP for the following immutable dependency:

```text
R1c implementation commit:
f6f4ad75b0a584dc348b75ca038b2e50bc7d2f7b

R1c implementation Git tree:
36354ee5c262300e61ff43ab712b5b82243e82af

R1c binding task commit:
7f08e00b2dbb5c2a5cb212b60ea7fbcd3557da9b

R1c binding task SHA-256:
cce2b1445e6c3be22bb8862831cc3d9e9884e20a74db4f3727c7df14c2ce3c62

divisions.py SHA-256:
3009d182b71dd786f1249e17734b2e6dea70e2260b752f6227e810643efb59f4

pipeline.py SHA-256:
96b218494b665b3e41f1a32ae33f7f16a80b71bf9b9c18d93e6168f9ca96786a

tests/test_public_postproc.py SHA-256:
e49fb62138fb97bc758ac1363d95219799c8112941aa597997fd76d9306c7e4c
```

The authoritative `f6f4ad7` commit tree is immutable.  At re-pin,
`develop@b1997fd` was clean and the current `divisions.py`, `pipeline.py`,
`tests/test_public_postproc.py`, and amended R1c task were byte-identical to
their pinned commit versions.  A later difference in any pinned path or hash
invalidates this appendix and returns R2 to HOLD.

### 13.1 Non-dry guard and entry boundaries

`<R1C_NON_DRY_GUARD>` is
`pipeline.py@f6f4ad7:146-151`:

```python
def _require_steal_twin_r1_dry_run(cfg: PostprocConfig) -> None:
    if cfg.OUTPUT_STEAL_TWIN_REWIRE and not cfg.STEAL_TWIN_DRY_RUN:
        raise RuntimeError(...)
```

It runs in `filter_output_graph_pre_linefit` at line 641 before `new_stats` or
graph work; `filter_output_graph` lines 808-815 delegates first to that guarded
function and has no duplicate guard.  It also runs in `run_postproc` at line
906 before detector loading/output creation and in
`save_prelinefit_checkpoint` at line 992 before detector loading/checkpoint
creation.  R2 replaces only this unavailable-ST-R2 rejection with the exact
master/mode/profile routing in section 11.4; it does not move or duplicate the
four effective entry checks.

### 13.2 Plan, merge, allocation, and collector pins

`<R1C_PLAN_HOOK>` is `pipeline.py@f6f4ad7:505-515`:

```python
def _run_steal_twin_r1_dry_run(
    cfg: PostprocConfig,
    dataset: str | None,
    nodes_by_id: dict[int, dict[str, object]],
    edges: list[dict[str, object]],
    stats: dict[str, int],
    deepcenter_bundle: dict[str, object] | None,
    repair_frame_cache: dict[int, np.ndarray],
    deepcenter_heatmap_cache: dict[tuple[str, int], np.ndarray],
    twin_debug_collector: _TwinDebugCollector | None,
) -> None:
    ...
```

The exact planner invocation is lines 527-533.  The current adapter has no
explicit return and therefore returns `None`; its local `plan` is not exposed
to its caller.

`<R1C_COUNTER_MERGE_HOOK>` has no separate production symbol.  It is inline in
that adapter: lines 534-549 snapshot and validate the planner counter schema,
values, and preseeded destination; lines 551-552 assign the complete mapping
into `stats` with `zip(..., strict=True)`.

`<R1C_DEBUG_ALLOCATION_HOOK>` also has no separate symbol.  At lines 553-558,
a nonempty debug path requires the run-level collector, calls
`twin_debug_collector.allocate(plan.debug_records)`, and overwrites that
dataset's written/dropped counters with the returned values.

`<R1C_DEBUG_COLLECTOR_TYPE>` is
`pipeline.py@f6f4ad7:416-502`, class `_TwinDebugCollector`, with:

```python
__init__(self, max_records: int) -> None
allocate(self, records: Sequence[TwinDebugRecord]) -> tuple[int, int]
finalize(self, output_path: Path) -> None
records_written: int
records_dropped: int
```

`<R1C_RUN_COLLECTOR_FACTORY>` is also inline, not a shared function.
`run_postproc` lines 908-918 and `save_prelinefit_checkpoint` lines 993-1007
each construct exactly one
`_TwinDebugCollector(cfg.STEAL_TWIN_DEBUG_MAX_RECORDS)` after their complete
alias validation only when the master and debug path are both truthy.  The
collector is created outside the sorted dataset loop and passed unchanged to
every dataset; an empty path creates none.

### 13.3 Cache identity and exact current order

`filter_output_graph_pre_linefit` owns one per-dataset
`repair_frame_cache: dict[int, np.ndarray] = {}` at line 651.  The same object
is passed to centroid refinement, single-frame gap close, safe divisions, the
R1c adapter, and through its strict callback to `score_twin_deepcenter` at
lines 656, 724, 735, 747, and 523.

The same function owns one per-dataset
`deepcenter_heatmap_cache: dict[tuple[str, int], np.ndarray] = {}` at line 716.
The same object is passed to single-frame gap close, safe divisions, the R1c
adapter, and through its strict callback to `score_twin_deepcenter` at lines
725, 736, 748, and 524.

The exact current adapter order is:

1. `plan_twin_only_v1` returns local `plan` at lines 527-533.
2. Its complete counter mapping and destination preseed are snapshotted and
   validated at lines 534-549.
3. The complete mapping is assigned to `stats` at lines 551-552.
4. If configured, `plan.debug_records` is allocated at lines 553-556.
5. Returned per-dataset written/dropped values are stored at lines 557-558.
6. The function returns `None` implicitly; R1c never mutates the graph.

### 13.4 Ordinary artifact finalization order

`run_postproc` completes every sorted dataset, closes the output CSV at the
line-952 context boundary, completes `_finish_run`/`write_run_stats` at lines
953-961, finalizes the collector at lines 962-963, and only then returns at
lines 965-971.

`save_prelinefit_checkpoint` completes and closes every dataset pickle at
lines 1012-1036, writes `manifest.json` at lines 1038-1039, finalizes the
collector at lines 1040-1041, and only then returns at line 1042.

### 13.5 Exact R2 adapter amendment

R2 must not assume the landed adapter already returns a plan or replacement
edge list.  It may make exactly these interface changes, in addition to the
new pure mutator and telemetry already frozen elsewhere in this contract:

1. import the pinned `TwinPlan` type in `pipeline.py`;
2. change only the return annotation of `_run_steal_twin_r1_dry_run` from
   `None` to `TwinPlan` and add `return plan` after the existing merge and
   optional debug allocation/counter assignment;
3. at the existing line-740 call site, bind that exact return as
   `plan = _run_steal_twin_r1_dry_run(...)` without another planner call;
4. immediately after the planner returns, and before destination-counter merge
   or collector allocation, validate the exact planner return and its failure
   envelope as specified below;
5. preserve the exact order plan -> failure-envelope validation -> whole
   counter merge -> optional debug allocation -> returned debug counts; then,
   only when `plan.validation_reason is None` and `STEAL_TWIN_DRY_RUN is False`,
   call `apply_twin_only_v1_plan(nodes_by_id, edges, plan)` exactly once and bind
   its returned edge list and summary;
6. a canonical validation-failed plan or dry-run never calls the mutator; a
   collector failure prevents the adapter return and therefore precedes
   mutation; and
7. assign R1 actual-effect and R2 telemetry only after the mutator returns and
   the pipeline rejects an unexpected `already_applied` status, as required by
   sections 11-12.

Define one private exact tuple beside `_TWIN_COUNTER_KEYS` in `divisions.py` and
import it into `pipeline.py`:

```python
_TWIN_VALIDATION_REASONS = (
    "missing_node_field",
    "invalid_node_id",
    "duplicate_node_id",
    "invalid_node_time",
    "nonfinite_node_coordinate",
    "invalid_edge_endpoint",
    "dangling_edge",
    "duplicate_edge",
    "nonconsecutive_edge",
    "indegree",
    "outdegree",
    "nonfinite_edge_distance",
)
```

The pre-merge guard first requires `type(plan) is TwinPlan`.  A
`validation_reason` of `None` is the valid-plan route.  Any non-`None` value
must have exact type `str` and be one of the twelve strings above; empty,
unknown, subclass, integer, or other values are malformed.  For such a reason,
`nodes`, `edges`, `candidates`, `accepted_candidates`, `decisions`, and
`debug_records` must each be the exact empty tuple.  `counters` must be exact
`TwinFrozenMapping` with an exact tuple of exact length-two tuple entries in
`_TWIN_COUNTER_KEYS` order, exact built-in string keys, and exact built-in int
values.  Exactly `steal_twin_validation_failed` and
`steal_twin_validation_<reason>` are one; every other value is zero.

Any failure of this guard raises `RuntimeError` before the R1 planner-counter
merge, collector allocation, twin/R2 mutation, downstream
geometry/prune/short pass, or publication of the current dataset's CSV rows,
stats row, or checkpoint payload.  The planner hook runs after the ordinary
centroid/edge-distance/gap/division preprocessing pinned in section 11.2, and
run/checkpoint entrypoints may already have created an output artifact, header,
or directory and may have published earlier completed datasets.  The guard does
not roll back those existing upstream mutations or ordinary earlier artifacts.
Only a canonical failure envelope takes the existing route: merge its counters,
optionally allocate its empty debug tuple, return the same plan, and skip the
mutator.  The pure mutator retains section 5.1's direct-call classification;
the stricter adapter guard exists because a non-`None` reason controls routing.

The mutator receives the identical node mapping and edge-list objects from
which the planner's row tuples were materialized; the planner does not receive
the containers themselves.  No pass occurs between snapshot construction and
mutation, so their rows and contents are unchanged.  Do not rename the adapter,
change its parameters, expose the plan through global state, return multiple
alternate shapes, use reflection/`hasattr` fallbacks, guess a signature, or add
a test-only production shim.

The audit also confirmed strict callback closure, duplicate GEFF-node hard
failure, direct-call collector combinations, run-level capacity,
deterministic lossless encoding, exact-bool record validation, bidirectional
alias guards, independent cleanup-fault coverage, and atomic collector
publication against the amended R1c task.  No R1c parity difference remains.

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
- Surviving row and supported nested mapping/list/array/buffer values, including
  recursively supported elements of an object-dtype array, plus the node
  mapping/row/supported nested identities, are unchanged.  This does not admit
  an arbitrary custom edge-metadata object.  Put an arbitrary identity sentinel
  only in extra node metadata that R1b does not read; unsupported custom edge
  metadata belongs in a failure test.  Original relative edge order is exact.
- Donor rows containing every supported R1b frozen metadata family can be
  matched and removed without ordinary dict/array equality errors.  Include
  float/complex specials, distinct NaN payloads, signed zero, arbitrary mapping
  key types/order, bytes/buffers, frozensets, dtype metadata, structured
  scalars, and object arrays; mapping-order differences remain distinct while
  equivalent frozenset construction order compares equal.  Separately include
  two distinct same-bit NaN members: the multiset token distinguishes one from
  two and distinguishes equal-total-cardinality sets with different repeated
  token distributions.
- Spy on current-row freezing/tokenization for k=2 and every partial-state
  mask: each row/metadata tree is normalized once per mutator call, not once
  per candidate or operation mask, preserving the section 7 complexity bound.

### 14.2 Validation and fail-closed behavior

Parameterize every exact `TwinMutationError.reason`.  Cover wrong top-level
type; failure plan; counter missing/extra/reordered/bool/negative; conservation
forgery; eligible/candidate-count mismatch; decision-reason/counter mismatch;
nonzero planner debug-allocation counters; debug-record length, identity, field,
dataset, or threshold forgery; candidate/decision identity or order forgery;
role/time/distance/sort forgery; removed metadata mismatch; and planned
probability not `None`.

Forge cyclic frozen-plan and raw-current metadata and require
`plan_candidate`/`current_graph_invalid`, respectively.  Construct exact
semantic-boundary fixtures for every recursive child family listed in section
2: depth 64 succeeds with identical tokens, while depth 65 is
`plan_candidate` for frozen plan metadata and `current_graph_invalid` for raw
current metadata.  The adopted R1b freezer raises `TypeError` at raw depth 65,
and the R1c retained-record plain codec raises `TypeError` at frozen depth 65;
neither leaks `RecursionError`.  The corresponding depth-64 retained record has
deterministic bytes identical across repeated encoding.  Dropped R1c records
still do not traverse or reject their nested metadata.  Shared acyclic subtrees
are accepted and counted once per semantic occurrence.

Use forged candidate/debug fields carrying equality, ordering, numeric, or
mapping protocols that would raise if invoked.  Exact structural checks must
reject the candidate as `plan_candidate`, or the independently forged debug
projection as `plan_acceptance`, without invoking those protocols and without
leaking their exception.  A malformed counter `items_snapshot` entry/key must
similarly produce `plan_counter_schema` before mapping iteration or lookup.

For every failure, snapshot all input list/mapping bytes or lossless frozen
values and all relevant object identities before the call.  With exact
built-ins and side-effect-free supported protocol values, assert no mutation,
no partial result, no R2-owned global state change, and no counter assignment.
Separately use adversarial protocol objects to prove R2 performs no write or
retry beyond the adopted R1b normalization call; caller-method side effects
remain outside the section 4 guarantee.

Cover malformed current rows, duplicate edges, dangling endpoints,
nonconsecutive time, indegree >1, outdegree >2, nonlossless metadata, node key/
row-ID mismatch, core node drift, unrelated edge metadata drift, and edge
reorder.  Exact extra node metadata is ignored for matching but its identity is
preserved.  A second direct call with edge-post-state and caller-modified extra
node metadata follows the documented support boundary and is still
`already_applied`; bit-level core coordinate drift fails `node_mapping`.
Use ordinary loader-shaped node rows with no `gap_synthetic` key for successful
apply, zero-acceptance no-op, and second-application cases, and assert the key is
not inserted.  Also cover one mapping containing both missing and present
optional keys: absent and explicitly false nodes normalize identically, while
an explicitly true node matches its true plan snapshot without changing any
row identity or key order.
Wrong top-level node-mapping/current-edge container types and dict subclasses
for node/edge rows exercise the exact built-in API boundary and map to
`node_mapping`/`current_graph_invalid` without invoking subclass methods.
Forge each duplicate/dangling/nonconsecutive/degree-invalid condition once in
the immutable plan snapshot and once only in the current graph: the former is
`plan_candidate`, while the latter is `current_graph_invalid` after the exact
partial-state precedence required by sections 6.2 and 8.

### 14.3 Idempotence classification

- Apply once, then call the direct mutator on that exact result and same plan.
  The second call returns the same list object, `already_applied`, and zero
  per-call effects.
- A zero-acceptance plan returns the same list object and `no_changes`.
- For zero acceptance, separately prove exact pre-state `no_changes`,
  degree-invalid non-pre-state `current_graph_invalid`, and every other
  well-formed drift `current_graph_mismatch` in that precedence order.
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

Using the section-13 R1c pins, spy on the exact landed hooks and require:

- master off never plans, allocates, mutates, or populates R2 even when the
  otherwise inert mode value is not `twin_only_v1`;
- master on with a mode/profile-lock mismatch hard-fails at every entry
  boundary before planner, detector, collector, mutation, or output activity;
- dry-run plans/merges/allocates but never mutates and preserves graph/CSV;
- candidate non-dry valid plan calls plan, merge, allocate, mutate exactly once
  at the frozen order and then geometry/prune/short;
- canonical validation-failed plans merge and optionally empty-allocate but
  never mutate in dry or non-dry;
- a wrong planner return type; empty, integer, string-subclass, or unknown
  validation reason; nonempty failure snapshot/debug tuple; malformed failure
  counter structure; or reason/counter forgery raises `RuntimeError` before
  R1 counter merge, collector allocation, twin mutation, downstream
  geometry/prune/short, or publication of the current dataset's CSV rows,
  stats row, or checkpoint payload; assert that already-run upstream graph
  preprocessing and already-created ordinary artifacts are not promised a
  rollback;
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
- Full filter counts binary64-token coordinate changes, including a
  `-0.0`/`+0.0` change; checkpoint stores zero; relinefit computes on its stats
  copy without touching disk.  A non-built-in or nonfinite post-coordinate
  hard-fails.
- A topology-increasing downstream pass or negative delta hard-fails.  Around
  linefit, fault-inject node/edge container replacement, row replacement or
  reorder, key replacement or reorder, and top-level preserved-binding
  replacement; each hard-fails before counter assignment or output.  Arbitrary
  nested in-place mutation is deliberately outside this non-recursive runtime
  guard.  Invalid pre-coordinate fixtures fail before linefit is called, and
  invalid post-coordinates fail before counter assignment or output.

### 14.7 Profile and regression identity

- Frozen base1/e23 effective configs are unchanged.
- Master-off graph objects, final CSV bytes, and all old non-twin stats match
  the pre-R2 base even when the otherwise inert mode value is non-twin; only
  preseeded zero R2 run-stats columns differ.  Master-on non-twin mode is the
  separately tested entry-boundary hard failure, not an identity path.
- Twin dry-run graph objects and final CSV bytes match the same input with
  mutation disabled; R1 plan/decision/sort/counter/debug artifacts remain
  identical between dry and candidate before mutation.
- Run the existing lightweight public-postproc suite and all R1/R1c focused
  tests.  Do not weaken or delete an assertion to land R2.

## 15. Allowed implementation files and commands

The section-13 dependency HOLD is cleared.  An implementation task may edit
only:

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

1. **Completed:** land and independently review R1c implementation.
2. **Completed:** pin section 13 against its clean exact commit and hashes.
3. Before editing source, re-read this entire contract, verify every pinned
   hash, and stop on any drift.
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

- section 13 contains no unresolved semantic label and an independent reviewer
  confirms the landed R1c implementation matches its task;
- the exact pure API, reason set, summaries, first/second-application behavior,
  identity rules, and pure `2k` invariants are implemented and tested;
- every mutator failure is fail-closed and satisfies the R2-owned write
  transaction boundary, with caller-protocol side effects scoped exactly as in
  section 4;
- pipeline order is exact and the R1c non-dry guard alone is replaced;
- master off (including an inert non-twin mode value) and exact-mode dry-run
  are graph/CSV identity paths, while master-on mode/lock mismatch hard-fails;
- planner versus actual versus downstream counter ownership is exact;
- checkpoint and relinefit have no duplicate planning or mutation;
- all allowed focused/regression tests pass; and
- no source outside the allowed list and no R3/metric/GT/network behavior was
  changed.

At this document base, section 13 is resolved and independently audited.  An
independent SOL reviewer cleared the amended binding content at SHA-256
`1d0643d20b53bc37274f5174df8c3377ebc30f2e506680ba68c10e3141a3fa13`.
The design disposition is **READY_FOR_IMPLEMENTATION**, with no known contract
blocker.  This is not a claim that R2 itself is SHIP: the implementation and
every remaining exit criterion above are still outstanding.
