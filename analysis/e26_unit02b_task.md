# E26 unit02b — paired statistics and exact screening gates

Parent design, 2026-09-06; independent review including numerical boundary
clarification: SHIP. NOT DISPATCHED. Unit02a must first finish and
pass parent tests plus independent review. This is the remainder of the original
unit02 scientific contract, not a relaxation of its gates. No retry or physical
evaluation is authorized by this draft.

## Context and scope

The final stdin task will be the complete E26 specification for this unit. Do not
search analysis/docs or list the repository looking for E26 documents; they are
not present in the clean worktree. Read AGENTS/fixed worker policy and the accepted
`src/biohub/e26_screen.py` plus `tests/test_e26_screen.py` only. No full config dump.
Use apply_patch to extend only those two files. Keep unit02a's API/behavior/tests
and accepted unit01 tests intact. No other edits, Git mutations, network,
credentials, agents, file I/O in the new API, subprocess, model loading, scoring
imports, actual GT/data, dependency installs or E25/ST-R3 runtime references.

## New API and schemas

Reuse accepted E26Error, CANDIDATE_ID and ARM_ORDER; no dry-run arm.
Add literal EVAL12/EVAL24 tuples from the lists below, and EVAL36=their literal
concatenation (not a sort or a set). Use these schema constants:

- GATE_INPUT_SCHEMA: `biohub.e26_screen.gate_input.v1`
- GATE_RESULT_SCHEMA: `biohub.e26_screen.gate_result.v1`
- `paired_statistics(values) -> dict` with exactly `n,mean,median,worst`.
- `evaluate_gate(stage: str, payload: dict) -> dict`.

Paired statistics require a nonempty sequence of finite real numeric values,
excluding bool, strings, complex and missing values. Use math.fsum(values)/n,
sorted center for odd median, math.fsum(two center values)/2 for even median,
and min for worst. Never filter, round, apply tolerance or fill missing values.
Catch invalid arithmetic/overflow and validate resulting statistics are finite;
raise E26Error, including for non-sequences or invalid numeric types.

Gate payload is a JSON-compatible dict with exactly:
`schema_version`, `stage`, `per_video`, `aggregate_deltas`.
The schema and stage must match the constant and stage argument. Per-video is
an ordered list of exactly the stage's literal videos, each with exactly
`dataset` and `combined_score_delta`. Reject wrong/missing/duplicate/reordered
videos and wrong row counts. Compute statistics from these rows, not supplied
summaries. Never accept a caller-provided mean as evidence.

`aggregate_deltas` has exactly three keys: the stage name, `44b6`, `6bba`.
Each group has exactly `score`, `adj_edge_jaccard`, `division_jaccard`.
JSON numeric values must be finite int/float excluding bool. Stage/group score
and adjusted-edge values are mandatory even where diagnostic rather than gated.
Division J may be null only where it is not a required gate. Stage eval36
division J must be finite; null is ERROR. Group division J and stage eval12/24
division J may be null. Reject NaN/inf even in non-gate diagnostics.
Reject all malformed input before numerical gate comparison; wrong/old schemas,
keys/types/values are E26Error, never a scientific REJECT/PASS.

Complete valid eval12 payload example:

```json
{
  "schema_version": "biohub.e26_screen.gate_input.v1",
  "stage": "eval12",
  "per_video": [
    {"dataset": "44b6_12dfb391", "combined_score_delta": 0.01},
    {"dataset": "44b6_267148e4", "combined_score_delta": 0.01},
    {"dataset": "44b6_2a2eff9f", "combined_score_delta": 0.01},
    {"dataset": "44b6_341df25f", "combined_score_delta": 0.01},
    {"dataset": "44b6_587a1e22", "combined_score_delta": 0.01},
    {"dataset": "44b6_5f15d135", "combined_score_delta": 0.01},
    {"dataset": "6bba_062c8d37", "combined_score_delta": 0.01},
    {"dataset": "6bba_07e24132", "combined_score_delta": 0.01},
    {"dataset": "6bba_085bf656", "combined_score_delta": 0.01},
    {"dataset": "6bba_09961292", "combined_score_delta": 0.01},
    {"dataset": "6bba_0e7c0d07", "combined_score_delta": 0.01},
    {"dataset": "6bba_12665c0e", "combined_score_delta": 0.01}
  ],
  "aggregate_deltas": {
    "eval12": {"score": 0.01, "adj_edge_jaccard": 0.01, "division_jaccard": null},
    "44b6": {"score": 0.01, "adj_edge_jaccard": 0.01, "division_jaccard": null},
    "6bba": {"score": 0.01, "adj_edge_jaccard": 0.01, "division_jaccard": null}
  }
}
```

Removing even one row from the example must fail count validation.
Unit04, not this pure gate, establishes official-row provenance and validates
that null division diagnostics correspond to an actual zero denominator.

## Gate names, order and inclusive thresholds

All comparisons are >= with unrounded numbers. Evaluate every gate, preserving
this exact order and reporting the first failed gate name:

| stage | ordered gate name: threshold |
|---|---|
| eval12 | paired_mean: .005; paired_median: 0; paired_worst: -.002; aggregate_adj_edge: -.002; lineage_44b6_score: 0; lineage_6bba_score: 0 |
| eval24 | paired_mean: .003; paired_median: 0; paired_worst: -.002; aggregate_adj_edge: -.002; lineage_44b6_score: 0; lineage_6bba_score: 0 |
| eval36 | aggregate_adj_edge: 0; aggregate_score: 0; aggregate_division_jaccard: 0; paired_median: 0; paired_worst: -.002; lineage_44b6_score: 0; lineage_6bba_score: 0 |

Eval24 uses the remaining 24 only. Eval36 uses 12+24 saved rows; this API never
scores anything. Eval36 has no paired-mean or division-TP+4 gate. Negative
adjusted-edge at eval36 is rejected even if it would pass the earlier -.002 bar.

Result includes schema_version, candidate_id, stage, paired_statistics,
ordered `gates` entries with exactly name/value/threshold/passed, first_failure
(null on success), status, and submission_authorized=false in every case.
Success statuses are SCREEN_EVAL12_PASS, SCREEN_EVAL24_PASS and
SCREEN_PASS_REQUIRES_CONFIRMATION. Failure statuses are SCREEN_REJECT_EVAL12,
SCREEN_REJECT_EVAL24 and SCREEN_REJECT_EVAL36. No adoption/submission shortcut.

## Synthetic tests and acceptance

Retain unit02a checks; test every literal split/order/count, schema/type/key error,
empty/bool/nonfinite delta, fsum-sensitive mean, odd/even median and arithmetic
overflow. Test each gate at its exact boundary and math.nextafter just below it,
using fixtures that keep other gates passing where possible. For paired gates,
verify the recomputed statistic actually hits the intended boundary (do not
assume modifying one row moves a rounded mean by one ULP).
For eval24 paired mean, exact float .003 is not reachable by math.fsum(values)/24:
adjacent possible totals 0.072 and 0.07200000000000001 divide to respectively
0.0029999999999999996 and 0.0030000000000000005. No representable total lies
between them. Do not force the full-payload statistic to equal .003 by rounding.
Use all 24 deltas=nextafter(.003,-inf) for the exact reachable mean below the bar,
and all 24 deltas=.003 for the exact reachable mean above it; assert those means
and the unchanged .003 threshold. Use a small private gate-record comparator for
every gate, tested separately with exact-bound values and nextafter-below values.
This proves inclusive >= at the comparator and both reachable sides through the
full payload. It does not permit an externally supplied mean, tolerance or a
changed gate. Other reachable boundary cases retain their full-payload tests.

Test simultaneous failures preserve first-failure order and still report all
gates. Test non-gate null division is valid, required eval36 null is ERROR,
negative eval36 adjusted-edge is REJECT, no TP+4 gate exists, and every result
retains submission_authorized=false. Test the example passes and a removed row rejects.

Use existing canonical interpreter and Ruff at
`/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking/.venv/bin/`.
Run PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
on tests/test_e26_screen.py, tests/test_e26_motion_relink_contract.py and
tests/test_public_postproc.py together. Ruff check --no-cache the two edited files.
Report exact results; stop after passing work rather than rewriting it. Parent
must reread the entire diff, rerun checks and obtain separate SOL acceptance.
Unit02 is complete only after all original obligations are covered, not merely
after these API names exist. Unit03/04 and physical evaluation remain separate.

## Literal videos (order binding)

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
