# Qwen implementation task: twin-only ST-R1 planner and dry-run

Work only in the clean linked worktree supplied by the launcher. The expected
base is `develop@032da44` plus the committed handoff documents containing this
task. Do not reset, rebase, merge, commit, or push.

Before editing, read these files completely, in this order:

1. `AGENTS.md`
2. `analysis/gold_loop_protocol.md`
3. `analysis/steal_twin_design.md`
4. `analysis/steal_twin_st_r1_contract.md`
5. the current implementation and tests you are allowed to touch

The binding scope is ST-R1 only: immutable twin-only candidate planning,
strict fail-closed DeepCenter scoring, deterministic resolution/telemetry,
bounded run-level debug JSONL, and a dry-run-only pipeline hook. Do not
implement the ST-R2 edge mutation adapter or any metric/evaluation behavior.

## Allowed files

You may modify only:

- `src/biohub/public_postproc/config.py`
- `src/biohub/public_postproc/deepcenter.py`
- `src/biohub/public_postproc/divisions.py`
- `src/biohub/public_postproc/pipeline.py`
- `tests/test_public_postproc.py`

Do not create another production module or test file. Do not touch
`graph_ops.py`, `official/`, scripts, notebooks, data, outputs, lockfiles, or
the analysis documents. Preserve all current E23/Base1 code paths.

## Required implementation

Implement every binding requirement in
`analysis/steal_twin_st_r1_contract.md`; where the older design is ambiguous,
the ST-R1 contract wins. In particular:

1. Add the exact inert config fields, exact `e23_twin_only_v1` preset/profile,
   version-lock validation, and profile whitelist tests. Master-off is wholly
   inert. With master-on, every causal value and `DEBUG_MAX_RECORDS=200` must
   equal frozen v1; only `DRY_RUN=True` and an explicit debug path are ST-R1
   operational overrides. Boundary tests vary geometry/model scores, never
   thresholds or caps. Do not add disposable-steal controls or code.
2. Add an immutable validated snapshot and pure `twin_only_v1` planner in
   `divisions.py`. Use per-frame cKDTree/radius queries, sorted query results,
   the exact mutual-unique/tie contract, fixed first-failure order, exact
   eligibility boundaries, strict DeepCenter last, complete sort key, then
   conflict/frame/video resolution. Never enumerate all P/Q pairs and never
   mutate caller-owned objects or `stats`.
3. Add only the minimum DeepCenter production change needed to expose the
   loader-verified integer as `checkpoint_epoch`. Strict scoring requires the
   exact bundle fields `model`, `cfg`, `device`, `torch`, `path`, and
   `checkpoint_epoch`, plus integer non-boolean `cfg.pool_factor >= 1`. Build
   the strict twin scoring adapter using the existing shared frame/heatmap
   caches and the exact reason mapping from the contract. Do not alter the
   established gap or safe-division fail-open behavior.
4. Preseed every exact ST-R1 telemetry key. The adapter merges the plan's
   integer counters. In dry-run, planned edge counters equal accepted, actual
   edge counters remain zero, and the graph is unchanged.
5. Insert the planner immediately after E23 safe division and before all
   downstream passes. Master-off must not call it. Enabled non-dry-run must
   raise the specified ST-R1 guard before planning.
6. Add one run-level deterministic debug collector shared across sorted
   datasets by `run_postproc` and `save_prelinefit_checkpoint`. Allocate the
   remaining frozen global capacity online so each dataset's written/dropped
   counters are final before its stats row or pickle is serialized; buffer the
   retained records and atomically publish JSONL only after full-run success.
   No configured path means no I/O. Enforce exact JSON encoding, record
   contents, overwrite-not-append behavior, and the explicit-collector
   requirement for direct filter calls. Only direct collector unit tests may
   instantiate a smaller internal capacity; runtime config remains 200.
7. Reject duplicate GEFF node IDs before the loader overwrites them.

Use frozen dataclasses/tuples or an equivalently immutable representation.
Keep helper APIs typed. Do not catch broad exceptions except at the explicitly
fail-closed frame/inference boundary where the contract requires mapping an
exception to one deterministic rejection reason.

## Required tests

Keep all existing tests. Add only the complete ST-R1 pre-metric test surface
split out by the binding contract and the SOL readiness audit. Do not add the
deferred ST-R2 mutation/edge-metadata/`2k`/downstream-delta tests or ST-R3
official-metric/manifest tests. ST-R1 tests include:

- exact config/profile diff and unchanged base1/e23 values;
- off and dry-run graph/value/order/metadata/object identity;
- minimal eligible six-node twin and exact complete sort key;
- exclusion of a non-twin donor with a predecessor;
- every snapshot validation reason and validation priority;
- inclusive distance boundaries and nextafter checks by varying coordinates,
  without changing frozen config thresholds;
- both `1e-9 um` nearest-tie directions and a non-mutual pair;
- missing successor, and validation precedence for shared/wrong-time edges;
- divergence immediately below/equal/above `2.25`;
- all six synthetic-node positions;
- every strict DeepCenter reason plus below/equal/above `0.12`;
- full candidate sort-key tie breaking, conflict, frame cap, and video cap;
- all telemetry conservation identities;
- randomized node/edge/spatial-result permutations with stable plan/counters;
- shared-cache spy proving one frame read/inference per `(dataset,t)`;
- deterministic debug bytes, opt-in only, online global cap, counters finalized
  before run-stats/checkpoint serialization, and dropped accounting;
- pipeline-order spy, repeated dry-run idempotence, loader duplicate rejection,
  and the non-dry-run ST-R1 guard.

Tests must use synthetic in-memory data and temporary files only. Do not read
competition images, GT, Kaggle artifacts, or existing experiment outputs.

## Verification before handoff

Use the main checkout's Python environment and official source only for test
imports; do not initialize or modify the worktree's `official` directory.

```bash
PY=/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking/.venv/bin/python
OFF=/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking/official/src
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$PY" -m pytest tests/test_public_postproc.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="src:$OFF" "$PY" -m pytest tests -q -p no:cacheprovider
"$PY" -m ruff check src/biohub/public_postproc tests/test_public_postproc.py
git diff --check
```

Then verify:

- `git status --short` contains only the five allowed files;
- existing production behavior is untouched outside the opt-in hook;
- no new production/config/test line contains `disposable_steal`;
- no network, GT metric, Kaggle command, commit, or push occurred.

Report the exact files changed, planner/debug interfaces, test counts and
commands, conservation results, residual risks, and a one-command rollback.
