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

