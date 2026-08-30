# E23 Phase 3 Qwen follow-up: tie claim and counter conservation

Work only in the supplied clean Phase 3 worktree. This is a narrow follow-up
to SOL review of commit `910656a`; do not redesign or refactor Phase 3.

## Required changes

1. Preserve the E23 notebook's ordinary `cKDTree.query(child_point)` behavior
   and its accepted candidate set. Do **not** add a new deterministic tie-break
   without public-four parity evidence.
2. Remove or reword every claim that SciPy `cKDTree` guarantees a first-input-
   index winner for exact distance ties. SciPy does not specify that contract;
   larger equal-distance trees can return a nonzero index even in the current
   SciPy 1.18.1 environment.
3. Replace the two-point test that hard-codes candidate ID 4 as the tie winner.
   Keep meaningful tie coverage: for an exact tie assert that exactly one tied
   candidate is selected, the other is counted as mutual-NN rejected, the
   winner is one of the tied candidates, and repeated calls in the same pinned
   runtime/input are identical. Do not claim cross-version winner identity.
4. Add a direct structural-counter conservation assertion/test:

   ```text
   safe_division_geometric_candidates
     == safe_division_mutual_nn_rejected
      + deepcenter_safe_div_rejected
      + safe_division_divergence_rejected
      + safe_division_candidates
   ```

   Cover accepted, mutual-rejected, DeepCenter-rejected, and divergence-
   rejected paths. The DeepCenter-order stub that returns false must increment
   `deepcenter_safe_div_rejected`, as the real helper does, before returning.
   Do not mislabel `geometric - candidates` as DeepCenter rejection.

## Scope and verification

Modify only:

- `src/biohub/public_postproc/divisions.py` (comments/docstrings only unless a
  concrete correctness issue is discovered and reported first)
- `tests/test_public_postproc.py`

Do not touch config, pipeline, graph_ops, official, data, outputs, notebooks,
or lockfiles. Do not commit, push, use network, or create agents.

Use the primary environment offline:

```bash
PY=/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking/.venv/bin/python
OFF=/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking/official/src
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 "$PY" -m pytest tests/test_public_postproc.py -q -p no:cacheprovider
PYTHONPATH="src:$OFF" PYTHONDONTWRITEBYTECODE=1 "$PY" -m pytest tests -q -p no:cacheprovider
"$PY" -m ruff check src/biohub/public_postproc/config.py src/biohub/public_postproc/divisions.py src/biohub/public_postproc/pipeline.py tests/test_public_postproc.py
git diff --check
```

Report exact files changed, test counts, Ruff/diff-check results, the revised
tie contract, the conservation coverage, and any residual risk.
