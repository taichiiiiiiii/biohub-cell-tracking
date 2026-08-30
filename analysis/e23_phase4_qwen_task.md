# E23 Phase 4 Qwen handoff: exact gap-veto parity

Implement this only after Phase 3 safe-division work has been integrated. This
is a bounded notebook-parity fix, not a refactor. Work offline in the supplied
worktree, do not commit, and do not alter or regenerate official/Kaggle data.

## Sources and current defect

Read before editing:

- `AGENTS.md`
- `analysis/e23_parity_runbook.md`, especially “Phase 3/4 blocker”
- `notebooks/pub923_repro/pub923_repro.ipynb`, the code in
  `close_single_frame_gaps` and `deepcenter_accept_repair_point`
- `src/biohub/public_postproc/{graph_ops.py,pipeline.py,deepcenter.py,config.py,divisions.py}`
- `tests/test_public_postproc.py`

The oracle notebook computes:

```python
marginal_gap = gap_span_um >= DEEPCENTER_GAP_CONFIRM_MIN_SPAN_UM
synthetic_middle = int(middle.get("gap_synthetic", 0)) == 1
requires_center_confirmation = (
    DEEPCENTER_GAP_VETO and marginal_gap and synthetic_middle
)
```

The current port incorrectly ends that predicate with `middle_reused`, so it
queries DeepCenter for a marginal observed/reused node and bypasses a marginal
synthetic node. It also exposes the stale pipeline counter
`deepcenter_gap_bypassed_synthetic_node`; the notebook schema instead uses
`deepcenter_gap_bypassed_observed_node`.

The DeepCenter oracle rejects only when `score < threshold`; equality is
accepted. Therefore a score exactly `0.25` must pass when the E23 gap threshold
is `0.25`.

## Required behavior and branch priority

Preserve the notebook's branch order exactly. When `DEEPCENTER_GAP_VETO` is
enabled:

| middle node | nonmarginal: span `< 8.5` | marginal: span `>= 8.5` |
|---|---|---|
| observed/reused (`gap_synthetic != 1`) | increment `deepcenter_gap_bypassed_strong_motion`; do not call the model | increment `deepcenter_gap_bypassed_observed_node`; do not call the model |
| synthetic (`gap_synthetic == 1`) | increment `deepcenter_gap_bypassed_strong_motion`; do not call the model | call DeepCenter with `cfg.DEEPCENTER_GAP_THRESHOLD` (`0.25` in E23) |

Thus the model predicate is exactly `cfg.DEEPCENTER_GAP_VETO and
marginal_gap and synthetic_middle`; it must never be based on
`middle_reused`. The nonmarginal check has priority, so both observed and
synthetic nonmarginal repairs count only `bypassed_strong_motion`.

When `DEEPCENTER_GAP_VETO` is disabled, none of the three gap routing/bypass
counters changes and no DeepCenter call is made by this gate. Do not change the
separate fail-open behavior governed by `USE_DEEPCENTER_VETO` inside
`deepcenter_accept_repair_point`.

For a rejected marginal synthetic repair:

- remove the just-inserted middle node;
- decrement/restore the local `synthetic_added` cap accounting and
  `stats["gap_inserted_synthetic"]`;
- preserve the existing construction order: perform the veto before creating
  either proposed edge, so rejection leaves `new_edges` unchanged; do not move
  edge construction before the veto and do not mark the source, target, or
  isolated sets as used;
- do **not** decrement `next_id`: the rejected node consumes its ID, so the
  next accepted synthetic node has a visible ID gap;
- retain telemetry already recorded before rejection, including synthetic
  midpoint refinement counters and DeepCenter checked/rejected/missing or
  accepted counters as applicable.

At function exit, `gap_added_nodes` must still mirror the final
`gap_inserted_synthetic`, and node-cap capacity freed by a rejection must be
available to a later candidate in the same call.

Rename the stats schema entry in `pipeline.new_stats()` from
`deepcenter_gap_bypassed_synthetic_node` to
`deepcenter_gap_bypassed_observed_node`. The stale name must not remain in
active source or tests.

## Scope

Only these files may be modified:

- `src/biohub/public_postproc/graph_ops.py`
- `src/biohub/public_postproc/pipeline.py`
- `tests/test_public_postproc.py`

Do not modify `config.py`, `deepcenter.py`, `divisions.py`, scripts, notebooks,
runbooks, lockfiles, `official/`, or any output/data artifact. In particular,
Phase 4 must not change the integrated Phase 3 division implementation,
division telemetry, or Phase 3 tests. Preserve iteration order, assignment
order, edge construction, and all unrelated counters.

## Deterministic focused tests

Add focused synthetic-graph tests to `tests/test_public_postproc.py`. Isolate
gap closing with the existing `_cfg`/`_ALL_OFF` pattern and monkeypatch the
symbol actually called by `graph_ops.py` so there is no model, image, network,
or checkpoint dependency. A monkeypatched
`graph_ops.deepcenter_accept_repair_point` spy must preserve the real helper's
telemetry contract: on a scored call it increments
`deepcenter_gap_checked` and exactly one of `deepcenter_gap_accepted` or
`deepcenter_gap_rejected` before returning. Alternatively, leave that helper
real and monkeypatch `deepcenter.deepcenter_score_point` to return the desired
deterministic score. For refinement-dependent assertions, monkeypatch
`graph_ops.refine_synthetic_midpoint`; its spy must increment
`gap_refined_synthetic` once per insertion before returning a deterministic
point, just as the successful real refinement path does. Assert spy call
counts, threshold arguments, and relevant stats, not merely final topology.

Required coverage:

1. The four observed/synthetic x nonmarginal/marginal quadrants in the table.
   Each must prove the correct single bypass counter or the single model call;
   observed nodes must remain observed and synthetic nodes must carry
   `gap_synthetic == 1`.
2. Veto disabled: both node kinds/at least both span classes collectively show
   no model call and zero bypass/check counters while valid repairs still land.
3. Exact boundaries: span exactly `8.5` is marginal. Construct that boundary
   in physical units using the repository scale, for example an x-coordinate
   difference of `8.5 / 0.40625` voxels with equal z/y, and assert that the
   resulting candidate takes the marginal route. Exercise the established
   DeepCenter strict threshold boundary as well: score `0.25` is accepted and
   a score below `0.25` is rejected (either through the real helper with a
   deterministic score stub or an equivalently focused test).
4. Rejection transaction in one deterministic scenario containing a later
   accepted synthetic candidate: rejected node and its two proposed edges are
   absent; accepted repair is present; `gap_inserted_synthetic`,
   `gap_added_nodes`, `gap_added_edges`, `gap_pairs_selected`, and node-cap
   behavior reflect only the accepted repair; the accepted node ID skips the
   rejected ID. Prove refinement telemetry from the rejected insertion and
   DeepCenter checked/rejected telemetry remain. Do not weaken this into two
   separate function calls, because `next_id` and cap reuse are call-local.
   Set `GAP_CLOSE_MAX_ADDED_ABS=1` and make
   `GAP_CLOSE_MAX_ADDED_FRAC` large enough that the absolute cap is the binding
   cap. Route the first candidate to rejection and the later candidate to
   acceptance without a candidate tie. Assert `gap_skipped_node_cap == 0`, the
   accepted node ID is exactly the rejected consumed ID plus one, and
   `gap_refined_synthetic == 2` (one retained refinement event for each
   attempted insertion). This must fail if rejection does not restore
   `synthetic_added` capacity.
5. Marginal synthetic fail-open: explicitly enable both
   `USE_DEEPCENTER_VETO` and `DEEPCENTER_GAP_VETO`, route the gap gate to the
   real `deepcenter_accept_repair_point`, and pass a dataset with a missing
   detector bundle. The valid repair still lands,
   `deepcenter_gap_missing == 1`, checked/accepted/rejected remain zero, and no
   bypass counter changes. This protects the separate `USE_DEEPCENTER_VETO`
   fail-open contract without loading a model.
6. Stats-schema test: `new_stats()` contains
   `deepcenter_gap_bypassed_observed_node` and does not contain the stale
   `deepcenter_gap_bypassed_synthetic_node`.
7. Non-regression: retain and run the existing legacy/default-base1 identity
   test and exact E23 profile-semantics test. Phase 4 changes no profile values.
   The full focused module must also retain all integrated Phase 3 tests.

Use explicit coordinates whose physical `gap_span_um` lies clearly on the
desired side of `8.5`, except for the dedicated equality case. Avoid reliance
on unordered candidate ties. Tests must be repeatable with no competition data.

## Verification commands

Use the repository's primary `.venv` directly and explicit `PYTHONPATH`; do
not run `uv sync`, install anything, or access the network.

```bash
set -euo pipefail
export PYTHONPATH="$PWD/src:$PWD/official/src"
.venv/bin/python -m pytest -q tests/test_public_postproc.py
.venv/bin/ruff check src/biohub/public_postproc tests/test_public_postproc.py
git diff --check
```

Also inspect scope and stale symbols:

```bash
set -euo pipefail
git status --short
git diff -- src/biohub/public_postproc/graph_ops.py src/biohub/public_postproc/pipeline.py tests/test_public_postproc.py
! rg -n 'deepcenter_gap_bypassed_synthetic_node' src tests
rg -n 'deepcenter_gap_bypassed_observed_node' src tests
git diff --exit-code -- src/biohub/public_postproc/divisions.py
```

Do not commit, push, fetch, browse, submit, publish, or run the public-four/full
pipeline. Do not edit `official/`.

## Completion report checklist

Return a concise report containing all of the following:

- [ ] exact files changed (and confirmation that no other file was changed by you);
- [ ] the corrected predicate, branch priority, and counter rename;
- [ ] rollback/cap/telemetry/next-ID behavior implemented;
- [ ] tests added, mapped to every required case above;
- [ ] exact verification commands and pass/fail results, including test count;
- [ ] `git diff --check` result and stale-symbol search result;
- [ ] confirmation that `divisions.py`, Phase 3 behavior/tests, profile values,
      `official/`, data/outputs, and lockfiles were untouched;
- [ ] confirmation of no commit and no network/external action;
- [ ] any residual concern or `none`.
