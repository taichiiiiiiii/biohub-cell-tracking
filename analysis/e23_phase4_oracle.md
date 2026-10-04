# E23 Phase 4 independent verification oracle

Use this note to review the exact gap-veto parity change without a model,
images, network access, or competition data. The current branch is shippable
only after all checks below pass.

## Notebook evidence

The binding source is code cell index 13 (the 14th notebook cell) in
`notebooks/pub923_repro/pub923_repro.ipynb`. Line numbers below are source-line
numbers after extracting that cell as text, not physical JSON file lines.

- Lines 470-495: `deepcenter_accept_repair_point` is fail-open and rejects only
  when `score < threshold`; equality is accepted.
- Lines 819-831: a new ID is consumed before refinement/insertion, the new node
  gets `gap_synthetic == 1`, and local/stat cap accounting is incremented.
- Lines 833-859: marginal means `gap_span_um >= 8.5`; node kind is
  `int(middle.get("gap_synthetic", 0)) == 1`; the model predicate is gap veto
  enabled AND marginal AND synthetic. Rejection removes the inserted node and
  restores `synthetic_added` and `gap_inserted_synthetic`, but not `next_id`.
- Lines 840-843: the nonmarginal branch precedes the observed-node branch.
- Lines 864-885: proposed edges, used sets, `gap_pairs_selected`, and
  `gap_added_edges` are changed only after veto success.
- Line 889: `gap_added_nodes` mirrors final `gap_inserted_synthetic`.
- Lines 1453-1458: the schema contains
  `deepcenter_gap_bypassed_observed_node`.
- Preset cell index 3, lines 35, 37, and 38: the E23 span boundary is `8.5`,
  the gap veto is enabled, and the threshold is `0.25`.

A reproducible extraction pattern is:

```bash
jq -r 'if (.cells[13].source|type)=="array" then .cells[13].source|join("") else .cells[13].source end' \
  notebooks/pub923_repro/pub923_repro.ipynb | nl -ba
```

## Binding route matrix

Node kind is defined by the `gap_synthetic` value, not by whether the node was
reused.

| Gap veto | Middle node | Span `< 8.5` | Span `>= 8.5` |
|---|---|---|---|
| off | any | no helper call; no route counter | no helper call; no route counter |
| on | `gap_synthetic != 1` | increment `deepcenter_gap_bypassed_strong_motion`; no helper call | increment `deepcenter_gap_bypassed_observed_node`; no helper call |
| on | `gap_synthetic == 1` | increment `deepcenter_gap_bypassed_strong_motion`; no helper call | call the helper once with threshold `0.25` |

The four node-kind by span quadrants must assert the exact single counter or
single helper call, the threshold argument, and the resulting node metadata.
Use physical spans clearly below and above the boundary. For equality, use an
x displacement of `8.5 / 0.40625` voxels and first assert that the repository
distance helper returns exactly `8.5`.

## Strict-threshold oracle

The `0.25` boundary test must call the real
`biohub.public_postproc.deepcenter.deepcenter_accept_repair_point`. Monkeypatch
only `deepcenter.deepcenter_score_point`, provide a non-`None` dataset and
detector bundle, and enable `USE_DEEPCENTER_VETO`. A stub of
`graph_ops.deepcenter_accept_repair_point` cannot prove the production
comparison operator.

Exercise scores `nextafter(0.25, -inf)`, `0.25`, and
`nextafter(0.25, +inf)`. Expected results are reject, accept, and accept. Each
case increments `deepcenter_gap_checked` once and exactly one of accepted or
rejected. Separately, a missing detector bundle is fail-open with
`deepcenter_gap_missing == 1` and checked/accepted/rejected all zero.

## Cap-one rejection transaction

Construct two spatially separated candidates in one call, with distinct costs
and deterministic insertion order. Set `GAP_CLOSE_MAX_ADDED_ABS=1` and make the
fractional cap nonbinding. Route the first marginal synthetic candidate to
rejection and the later one to acceptance. If the initial maximum ID is `M`,
the oracle is:

- node `M+1` is absent but its ID remains consumed; the accepted node is
  exactly `M+2` and has `gap_synthetic == 1`;
- neither rejected proposed edge exists; the original edges retain their order
  and only the two accepted edges are appended;
- `gap_inserted_synthetic == gap_added_nodes == 1`,
  `gap_pairs_selected == 1`, `gap_added_edges == 2`, and
  `gap_skipped_node_cap == 0`;
- `gap_refined_synthetic == 2`; DeepCenter reports two checked, one rejected,
  and one accepted;
- the rejected source/target are not marked used, while the freed node-cap slot
  is available to the accepted candidate.

This single-call scenario detects node/counter rollback errors, cap leakage,
premature edge or used-set mutation, and incorrect `next_id` rollback.

## Caveat and stale-symbol fence

The exact notebook classifies an existing reused node carrying
`gap_synthetic == 1` as synthetic and would remove it on rejection. Such input
is unreachable in the standard E23 path because imported graph nodes are
rebuilt with only `node_id`, `t`, `z`, `y`, and `x`. Do not expand Phase 4 to
define new behavior for that out-of-contract state.

The active source and tests must contain the observed-node counter and no stale
synthetic-node bypass counter. Finish verification with:

```bash
! rg -n 'deepcenter_gap_bypassed_synthetic_node' src tests
rg -n 'deepcenter_gap_bypassed_observed_node' src tests
git diff --check
```
