# Qwen implementation task: twin-only ST-R1a config and strict veto

Implement only ST-R1a in the clean linked worktree supplied by the launcher.
Do not commit, branch, push, use network/Kaggle, or edit analysis documents.
This handoff is self-contained and supersedes the monolithic
`steal_twin_st_r1_qwen_task.md` for this run. Read `AGENTS.md` completely, then
inspect only the relevant source/test sections with `rg`/`sed`; do not dump the
whole large test file or re-read the older gold/design documents.

## Allowed files

Modify only:

- `src/biohub/public_postproc/config.py`
- `src/biohub/public_postproc/deepcenter.py`
- `src/biohub/public_postproc/divisions.py`
- `tests/test_public_postproc.py`

Do not modify `pipeline.py` yet. Do not implement the planner, telemetry
schema/merge, debug collector, pipeline hook, duplicate-GEFF loader guard,
edge mutation, metric harness, or evaluation.

## A. Frozen configuration

Add these `BIOHUB_*` defaults and typed `PostprocConfig` fields. The inert
defaults use the values shown but keep the master off and debug path empty:

```text
BIOHUB_OUTPUT_STEAL_TWIN_REWIRE=0
BIOHUB_STEAL_TWIN_MODE=twin_only_v1
BIOHUB_STEAL_TWIN_DRY_RUN=0
BIOHUB_STEAL_TWIN_PARENT_MAX_UM=8.0
BIOHUB_STEAL_TWIN_EXISTING_CHILD_MAX_UM=10.0
BIOHUB_STEAL_TWIN_SISTER_MIN_UM=5.5
BIOHUB_STEAL_TWIN_SISTER_MAX_UM=11.0
BIOHUB_STEAL_TWIN_DIVERGE_UM=2.25
BIOHUB_STEAL_TWIN_TWIN_MAX_UM=5.0
BIOHUB_STEAL_TWIN_REQUIRE_TWO_SUCCESSORS=1
BIOHUB_STEAL_TWIN_REJECT_SYNTHETIC=1
BIOHUB_STEAL_TWIN_DEEPCENTER_VETO=1
BIOHUB_STEAL_TWIN_FRAME_CAP_ABS=1
BIOHUB_STEAL_TWIN_VIDEO_CAP_ABS=2
BIOHUB_STEAL_TWIN_DEBUG_JSONL=
BIOHUB_STEAL_TWIN_DEBUG_MAX_RECORDS=200
```

Add `TWIN_ONLY_V1_PRESET = {**E23_PRESET, ...}` and profile
`e23_twin_only_v1`. Spell every field above explicitly in the preset, set the
master to `1`, retain dry-run `0`, and set `BIOHUB_EXPERIMENT_TAG` to
`e23_twin_only_v1`.

When the master is false, twin version-lock validation is inert: changed but
parseable twin values and an unknown twin mode must not raise. When the master
is true, validate exact equality to every frozen causal value above, including
mode, booleans, both caps, and `DEBUG_MAX_RECORDS=200`. The preset's
`DRY_RUN=0` is valid. The only permitted operational changes are
`DRY_RUN=1` and a nonempty/changed `DEBUG_JSONL` path. Do not add an `off` mode
or any disposable-steal field.

The candidate/e23 effective-config diff must be a subset of all twin fields
plus `EXPERIMENT_TAG`, and must contain the master and tag. Existing `base1`
and `e23` effective values must remain unchanged.

## B. Checkpoint provenance

In `load_deepcenter_veto_detector`, add only
`"checkpoint_epoch": checkpoint_epoch` to the successful returned bundle.
Do not change loading, checkpoint selection, the model, weights, cache
semantics, or the existing gap/safe-division fail-open helpers.

## C. Strict twin-only DeepCenter adapter

Implement the adapter in `divisions.py`, not `deepcenter.py`, so the only
DeepCenter-module production change remains the provenance field. Use this
stable public interface (names and fields are binding for ST-R1b/R1c):

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

The adapter receives primitive values, never planner types or caller stats.
It never mutates stats and never changes a graph. Accepted returns
`(True, finite_raw_score, None)`. Every rejection returns `accepted=False`,
`raw_score=None` unless a finite below-threshold scalar exists. First validate
bundle, then dataset:

1. `deepcenter_bundle`: global DeepCenter use or twin veto is off; bundle is
   missing; any required key among `model,cfg,device,torch,path,checkpoint_epoch`
   is absent; `checkpoint_epoch` is not a non-bool integer or differs from
   `cfg.DEEPCENTER_EXPECTED_EPOCH`; or `bundle["cfg"].pool_factor` is missing,
   non-integer, boolean, or `<1`.
2. `deepcenter_dataset`: dataset is `None`, empty, or whitespace-only.
After those two gates, classify each stage in this exact order:

1. frame read raises, or frame is missing/empty -> `deepcenter_frame`;
2. a nonempty frame contains NaN/Inf -> `deepcenter_nonfinite`;
3. otherwise a non-3D frame -> `deepcenter_frame`;
4. inference raises, or heatmap is missing/empty -> `deepcenter_heatmap`;
5. a nonempty heatmap contains NaN/Inf -> `deepcenter_nonfinite`;
6. otherwise a non-3D heatmap -> `deepcenter_heatmap`;
7. requested point/patch is out of bounds or empty -> `deepcenter_heatmap`;
8. patch contains NaN/Inf -> `deepcenter_nonfinite`;
9. no scalar is produced -> `deepcenter_heatmap`;
10. raw scalar is nonfinite -> `deepcenter_nonfinite`;
11. finite raw score strictly below fixed `0.12` ->
    `deepcenter_threshold`, preserving that finite value in `raw_score`;
12. otherwise accept.

An equal or greater finite score is accepted. `0.12` is fixed here and is not
a tunable twin config or ranking signal. Explicitly call `read_test_frame`
before heatmap inference so frame errors are distinguishable, then call the
existing `deepcenter_heatmap_for_frame` with the same caches; the second read
must hit the populated frame cache. Do not call or alter
`deepcenter_accept_repair_point`. Catch broad exceptions only around the
explicit frame-read and inference boundaries needed for deterministic reason
mapping.

## Required ST-R1a tests

Append focused tests named `test_steal_twin_r1a_*`; do not reorganize earlier
tests. Cover:

- exact defaults, candidate profile values/diff whitelist, and unchanged
  base1/e23 configs;
- master-off inert validation; every master-on frozen-value violation;
  allowed dry-run/debug-path overrides; invalid mode/cap/debug max;
- loader bundle exposes the verified integer epoch without changing its other
  keys or established behavior;
- every missing required bundle key, epoch missing/type/mismatch, and
  `pool_factor` missing/string/float/bool/zero/negative;
- all six rejection reasons and their precedence, including wrong-rank + NaN
  frame and wrong-rank + NaN heatmap both mapping to
  `deepcenter_nonfinite`;
- `np.nextafter(0.12, -inf)`, exactly `0.12`, and
  `np.nextafter(0.12, +inf)`;
- frame-read-before-inference order and a cache spy proving one physical read
  and one inference for repeated scoring of the same `(dataset,t)`;
- existing fail-open helper behavior is unchanged.

Use synthetic arrays and monkeypatches only. Do not read competition data or
load a real model/checkpoint.

## Verification

```bash
PY=/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking/.venv/bin/python
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$PY" -m pytest \
  tests/test_public_postproc.py -q -p no:cacheprovider -k steal_twin_r1a
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$PY" -m pytest \
  tests/test_public_postproc.py -q -p no:cacheprovider
"$PY" -m ruff check src/biohub/public_postproc tests/test_public_postproc.py
git diff --check
```

Before handoff, prove `git status --short` contains only the four allowed files
and no added production/config/test line contains `disposable_steal`. Report
changed files, the exact adapter behavior/API, test counts/results, residual
risk, and rollback command. Do not commit.
