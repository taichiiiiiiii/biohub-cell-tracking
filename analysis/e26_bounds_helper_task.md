# Text-only Python design artifact: shape-aware CSV node helper

> 履歴・非運用・現行起動に使用禁止。この旧タスクは保存用です。
> 現行方針は [AGENTS.md](../AGENTS.md)、MAX評価入口は
> [評価手順](../.codex/runners/biohub_max_implementer.instructions.md) を参照。
> 以下のモデル指定・命令・実行例は当時の履歴であり、現在のworkerへ渡してはいけません。

Answer this question by returning Python source text in your final response.
Do not implement, inspect or edit anything in the worktree. The worktree is
irrelevant to answering this fully self-contained question. Do NOT use
apply_patch, view_image, request_user_input or any other tool. No file paths
are authorized for editing. No test execution. No tools at all.

Return exactly one JSON object {"helper_source":"...complete Python source..."}.
No Markdown fence, prose or extra keys. This is text authorship, not a request
to create files. Finish the outer JSON object. The parent separately handles
any later application and verification; do not perform those actions.

This is a new narrower authoring unit after a multi-deliverable task failed
because the model attempted a prohibited malformed patch. That task is closed.
This unit has one separately reviewed300s direct-user supervised budget,
no extensions, no retries, no provider/model/route fallback. Exact Qwen Cloud
qwen3.7-plus through qwen_token_plan subscription-only remains fixed.

Please write a complete minimal helper satisfying all APIs below. It rounds
finite microscopy node coordinates with Python's existing ties-to-even round
and applies bounds read from actual image metadata. It must never change graph
topology, IDs, row order, time or scientific model settings. There are no
hardcoded dataset/node IDs or fixed spatial dimensions.

Required APIs, pure standard library, without a future import:
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


Original full node output schema:
{"id":row_id,"dataset":dataset,"row_type":"node","node_id":node_id,"t":t,
 "z":z,"y":y,"x":x,"source_id":-1,"target_id":-1}
Shape metadata schemas:
root={"zarr_format":3,"node_type":"group","attributes":{"multiscales":[
 {"axes":[{"name":"T"},{"name":"Z"},{"name":"Y"},{"name":"X"}],
  "datasets":[{"path":"0"}]}]}}
array={"zarr_format":3,"node_type":"array","shape":[100,64,256,256]}
These are examples, never fixed dimensions. Unsupported/malformed metadata
must fail closed. Code style: Python3.12, Ruff E/W/F/I/UP/B, line120.
The complete code will be independently reviewed and tested later; do not
assert that tests passed or that an actual submission is valid.
