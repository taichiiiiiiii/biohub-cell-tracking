# E23 Phase 4 Qwen follow-up: boundary and transaction test hardening

Work only in the supplied clean Phase 4 worktree, starting from checkpoint
commit `9e1faac`. This is a test-only follow-up to SOL review. The production
Phase 4 code in `graph_ops.py` and `pipeline.py` already matches the notebook;
do not edit or refactor it.

## Required changes

Modify only `tests/test_public_postproc.py`.

### 1. Prove the strict `0.25` production comparator at adjacent floats

Keep using the real
`biohub.public_postproc.deepcenter.deepcenter_accept_repair_point`; monkeypatch
only `deepcenter.deepcenter_score_point`. Replace the current two-score loop
with exactly these three cases:

```python
(
    (np.nextafter(0.25, -np.inf), False),
    (0.25, True),
    (np.nextafter(0.25, np.inf), True),
)
```

For every case assert one checked call, no missing result, exactly one terminal
accepted/rejected counter, and the expected topology. Do not monkeypatch
`graph_ops.deepcenter_accept_repair_point` in this test.

### 2. Make the cap-one transaction deterministic and append-order exact

Replace the current independent equal-span pairs with the following overlap:
the rejected target becomes the later accepted source. The two costs are
distinct and every physical distance is asserted before the run.

```python
s = 0.40625
nodes = {
    1: _node(1, 0, x=0.0),
    2: _node(2, 2, x=9.0 / s),
    3: _node(3, 4, x=19.0 / s),
    6: _node(6, 9, x=2000.0),
    7: _node(7, 10, x=2000.0),
    8: _node(8, 11, x=2000.0),
}
original_edges = [
    {"source_id": 7, "target_id": 8, "edge_prob": 0.71},
    {"source_id": 6, "target_id": 7, "edge_prob": 0.62},
]
```

Preassert span 1 is exactly `9.0` um and span 2 is exactly `10.0` um through
`point_distance_um`. Keep `GAP_CLOSE_MAX_ADDED_ABS=1` and a nonbinding
fractional cap. Reject midpoint `t=1`; accept midpoint `t=3`.

Required assertions:

- refinement and DeepCenter call order is `[1, 3]`;
- rejected node `9` is absent and accepted synthetic node `10` is present;
- the accepted ID is the rejected consumed ID plus one;
- rejected source `1` and its target `2` have no rejected repair edge, while
  target `2` is successfully reused as the accepted repair's source;
- exact ordered edge list is the two original edges in their original order,
  followed by `(2, 10)` and `(10, 3)`, with complete edge dictionaries and
  `distance_um == 5.0` for both accepted edges;
- final counters remain `gap_inserted_synthetic=1`, `gap_added_nodes=1`,
  `gap_added_edges=2`, `gap_pairs_selected=1`, `gap_skipped_node_cap=0`,
  `gap_refined_synthetic=2`, and DeepCenter checked/rejected/accepted `2/1/1`.

The local used sets are not returned and their success-path mutations are not
fully behaviorally observable because candidate tables are precomputed and
Hungarian rows/columns are unique. Do not refactor production code merely to
expose them. The exact final graph plus the source-overlap above is the binding
behavioral fence; source inspection separately confirms the rejection
`continue` precedes all edge/set/counter mutations.

## Preserve and verify

- Keep all existing Phase 1-4 tests and all three production files unchanged.
- Do not add the stale pre-Phase-4 counter literal to `src` or `tests`.
- Do not commit, push, use network, edit docs/notebooks/official/data/outputs,
  or create agents.

Use the primary environment offline:

```bash
PY=/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking/.venv/bin/python
OFF=/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking/official/src
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 "$PY" -m pytest tests/test_public_postproc.py -q -p no:cacheprovider
PYTHONPATH="src:$OFF" PYTHONDONTWRITEBYTECODE=1 "$PY" -m pytest tests -q -p no:cacheprovider
"$PY" -m ruff check src/biohub/public_postproc tests/test_public_postproc.py
git diff --check
! rg -n 'deepcenter_gap_bypassed_synthetic_node' src tests
git diff --exit-code HEAD -- src/biohub/public_postproc/graph_ops.py src/biohub/public_postproc/pipeline.py src/biohub/public_postproc/divisions.py
```

Report exact files changed, test counts, three-float threshold results, exact
transaction edge order/counters, and any residual risk.
