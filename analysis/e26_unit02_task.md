# E26 unit02 — pure config, paired statistics, and screening gates

Parent design: 2026-09-06. Independent SOL design and dispatch review: SHIP.
The parent authorizes one local-Flash implementation of this unit now, through the
default launcher without --interactive. Supervisor limit: 20 minutes from launch;
automatic retries: zero. Implement the two named files and run the synthetic checks.
This is the next unit after accepted Qwen-authored unit01, not a retry of its stopped worker.
Do not launch another model, use Cloud, or grant another retry from this document.
The complete scientific contract remains [E26 design](e26_motion_relink_off_design.md).
For this unit, the bounded task below contains all required scientific conditions.
Read the worktree AGENTS/fixed worker policy and the relevant existing config API;
do not load the full historical E25/ST-R3/experiment ledger into the implementation
context or repeatedly rewrite a passing file. Stop and report a concrete missing
contract if one is found. Preserve passing work and use small targeted patches.

## Ownership and scope

The designated implementation worker edits only two new files in the one approved
`work/e26-flash` worktree: `src/biohub/e26_screen.py` and `tests/test_e26_screen.py`.
Use apply_patch. Keep existing tests, public_postproc, official/, E25/ST-R3 code,
AGENTS, launcher, data, models, outputs, and Git branches unchanged.
Do not commit, invoke networks, read credentials, spawn agents, or run real data.
SOL owns design, cause analysis, independent review, integration, and validation.

Unit02 has no CLI, filesystem I/O, subprocess, ground-truth/scoring import, model
load, real generation, or submission. Unit03 owns generation/parity/seals/telemetry;
unit04 owns official score conversion, staged GT reads, and persisted verdicts.
Do not add placeholders that claim these later units are implemented.

## Minimal pure API contracts

1. Define an E26-specific error type, candidate ID `e23_motion_relink_off_v1`,
   schema IDs beginning `biohub.e26_screen.`, and arm order
   `public4_parity`, `baseline`, `candidate` (no dry_run).
   Freeze the exact EVAL12/EVAL24 video tuples below; EVAL36 is their literal
   concatenation, not a sorted union. Do not import the uncommitted E25 module
   or ST-R3 gates at runtime. This task supplies the split so the clean worktree
   needs no missing/uncommitted E25 source.
2. Build arm configs via existing `build_config(overrides, test_dir, profile="e23")`.
   Parameters are arm, image-root Path, checkpoint Path, and manifest Path.
   Apply identical explicit checkpoint/default and manifest/default overrides
   to all arms; candidate adds only `BIOHUB_OUTPUT_MOTION_RELINK="0"`.
   Do not expose arbitrary caller overrides or read process environment.
   Unknown arms are errors. Validate baseline/candidate across every dataclass
   field: exact diff set `{OUTPUT_MOTION_RELINK}`, literal True→False, both
   twin flags False, identical tag/test directory and all other config values.
   The pair validator must reject coordinated baseline/candidate drift from
   exact E23 as well as extra pair differences (rebuild the expected configs).
   Public4 uses its own image root; do not compare public4 TEST_DIR to eval36.
3. Pure paired statistics accept a nonempty sequence of finite non-bool numeric
   deltas. Mean is math.fsum(values)/n; median is sorted center or math.fsum
   of the two center values divided by two; worst is min. No decimal rounding,
   tolerance, NaN filtering, or replacement of missing values. Validate results
   too, including arithmetic overflow. Return n/mean/median/worst.
4. A pure E26 gate evaluator accepts stage plus an E26-schema payload of
   ordered per-video `{dataset, combined_score_delta}` rows and already-official
   aggregate deltas. Require exact stage video order/set/count (12/24/36), reject
   duplicates, and compute paired statistics from these rows, not supplied means.
   Aggregate deltas are named by stage, `44b6`, and `6bba`; each supplies `score`
   and `adj_edge_jaccard`; division_jaccard may be null for non-gate diagnostics.
   Reject wrong/old schema, unknown stage, malformed shape, missing required
   values, bool/string/NaN/infinity, and inconsistent video identity as ERROR
   before checking thresholds. Unit04 must establish official-row provenance,
   use official summarise, and justify null diagnostics by zero division counts;
   unit02 must not claim that accepting a payload establishes provenance.

## Gate order (all inclusive >=; first failed name is stable)

| stage | conditions in exact evaluation order |
|---|---|
| eval12 | paired mean .005; paired median 0; paired worst −.002; stage adjusted-edge Δ −.002; 44b6 combined Δ 0; 6bba combined Δ 0 |
| eval24 | paired mean .003; paired median 0; paired worst −.002; stage adjusted-edge Δ −.002; 44b6 combined Δ 0; 6bba combined Δ 0 |
| eval36 | stage adjusted-edge Δ 0; stage combined Δ 0; stage division J Δ 0; paired median 0; paired worst −.002; 44b6 combined Δ 0; 6bba combined Δ 0 |

Eval36 has no mean or division TP+4 gate. Its division J delta must be finite;
null is ERROR, not a waived gate. Eval12/24 do not gate on division J.
Return all gate values/thresholds/booleans, first_failure, and E26 schema/stage.
Statuses: `SCREEN_EVAL12_PASS`, `SCREEN_EVAL24_PASS`,
`SCREEN_PASS_REQUIRES_CONFIRMATION` for final success; otherwise
`SCREEN_REJECT_EVAL12`, `SCREEN_REJECT_EVAL24`, `SCREEN_REJECT_EVAL36`.
Every returned result explicitly has `submission_authorized=false`.
Malformed input raises the E26 error; it is never a scientific REJECT or PASS.

## Synthetic acceptance tests and handoff

- All arms and exact full config equality; wrong arm, extra difference, shared
  tag/threshold/twin drift, and literal-bool requirements reject.
- Fixed video tuples/order/count; old schema, duplicate/reordered/wrong videos,
  missing group/metric, wrong type, bool, NaN, infinity, and empty input reject.
- fsum-sensitive mean, odd/even median, worst, and nonfinite-result rejection.
- Every gate passes at its exact bound and fails just below (math.nextafter).
  If multiple fail, first_failure follows the table; all gates remain reported.
- Eval36 rejects negative adjusted-edge even when >=−.002; does not impose
  division TP+4; requires finite nonnegative division J delta. Valid null
  division diagnostics do not invalidate eval12/24.
- No success status grants submission; no E25/ST-R3 gate/schema import.

Run the two E26 test modules and existing test_public_postproc together, with
PYTHONPATH=src and PYTHONDONTWRITEBYTECODE=1, pytest -q -p no:cacheprovider.
Use the existing canonical interpreter
`/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking/.venv/bin/python`
and Ruff at the same `.venv/bin/ruff`; do not install dependencies or create an environment.
Run Ruff --no-cache on both new files. Report exact results and full diff.
Parent rereads the entire diff and reruns checks; a separate SOL reviewer must
accept it before integration. No physical scoring or retry is authorized here.

## Literal split data (order is binding)

EVAL12:

```text
44b6_12dfb391
44b6_267148e4
44b6_2a2eff9f
44b6_341df25f
44b6_587a1e22
44b6_5f15d135
6bba_062c8d37
6bba_07e24132
6bba_085bf656
6bba_09961292
6bba_0e7c0d07
6bba_12665c0e
```

EVAL24:

```text
44b6_706092f0
44b6_74d0c52e
44b6_7a302da0
44b6_996155de
44b6_9be80b04
44b6_a21120c2
44b6_aaf8b0ea
44b6_c50204e0
44b6_c8e2a523
44b6_d2f34f90
44b6_d5e7d891
44b6_d754aa59
6bba_1d0d8384
6bba_207c6aaf
6bba_20852818
6bba_2312ac41
6bba_268e1230
6bba_2819ca14
6bba_32db13fc
6bba_337b1b3a
6bba_3abfe10a
6bba_3c5691b6
6bba_3db54e20
6bba_3fda6b25
```
