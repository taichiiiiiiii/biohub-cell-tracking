# E26: motion relink OFF — target-only exploratory loop

Preregistered 2026-09-06 before any E26 target execution or LB readout.

## Frozen hypothesis and interpretation

Motion relinking replaces the filtered raw graph when it returns nonempty edges.
Disabling that replacement may recover useful raw associations and improve
tracking. The intervention includes downstream gap/division/pruning and matching
effects; it does not identify motion relinking as the cause of every lost edge.

D1 found 82 raw-to-final lost pairs among 205 matched-endpoint false negatives
(out of 338 total FN). Of those 82, 62 were in 6bba and 20 in 44b6; two videos
accounted for 45/82. New final pairs with raw endpoints contributed 37 TP and
156 FP in the sparse-GT evaluation. These are diagnostic subset counts, not
precision over all predictions. The pre-motion 14um filter and downstream
stages remain alternative causes. E25 accepted seven twin rewires but left
aggregate edge TP/FP/FN unchanged; its paired mean gain was only 4.05e-7 and
remains REJECT. E25 is not revived.

This loop uses the existing E23 notebook directly. Local E26 SCREEN and its
config/test runner remain INCOMPLETE; this is not SCREEN/PREFLIGHT PASS.
Original E23 source is preserved. Source-level parity means every notebook
field except the two appended configuration assignments is identical; it does
not prove newly measured local candidate parity or historical v1 source identity.
Current incumbent: submission55760016, E23 public LB0.924.

## Frozen artifacts

- Original notebook SHA256: 08507f9123d9f40e185d0db8eda3dd21cb405e50febb720827c2e655f68d5ec1
- Original kernel metadata SHA256: 12a05b6289850652e70affd8cba6ebc03038831c5a0cda44fef61f0d96450d85
- Candidate: notebooks/e26_target_motion_off/e26_target_motion_off.ipynb
- Candidate SHA256: a8d2b43e743eea8a99a128e4a2672f1ede8531dc162ebbb10dd957fc5fa7a052
- Candidate kernel metadata SHA256: a8d02867db2b095d3fb668468222c498fb207e77a0974482237e91e187da146c
- Requested kernel ID: taichiiiii/biohub-e26-motion-off-v1
- Title: Biohub E26 Motion OFF Exploratory. Kaggle may normalize its slug;
  bind the actual returned URL/version, never guess the immutable identity.
- Cell3 suffix only: BIOHUB_OUTPUT_MOTION_RELINK='0', BIOHUB_VALIDATOR_ENABLE='0'.
  The second switch disables train validation after submission.csv is written;
  independent source review verified it is output-neutral.
- All weights, attached datasets, configuration, code, private/GPU/offline
  settings remain unchanged. No twin-rewiring implementation is present.
- Existing runtime byte pins: primary12f6881ee3620a831697ca098ff8f48e687a24225f4e048b538deec3562fe771;
  secondary9bac2fa0dadc4a6fc1899e0caf187f4b553e0a7cd90ba1261a68b35ffe9e305f;
  DeepCenter8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0;
  support Python manifest978b626d1fd1e7397435a437dfe68691defe1572fc3c20e61012d7c9b52ed029.

## Review, implementation and tests

SOL independent direct-target design review: SHIP. Parent completed source-order,
exact suffix, AST, full notebook object equality outside cell3, and metadata
three-field-only checks. Relevant pytest:534 PASS; Ruff on the exact two-line
delta with its os import:PASS. Existing notebook-wide lint is excluded by the
repository configuration; no claim of new whole-notebook lint cleanliness.

Qwen Cloud qwen3.7-plus through qwen_token_plan authored the delta in one
direct-user supervised task, 14:40:11.256244–14:40:40.233569 UTC, exit0,28.98s,
600s cap, retries0/fallback0, tool calls0. Worker log SHA256:
be618b62102f49b53ba4f59a2a83708ff848598174a1d0d732fad7ef421012af.
Strict JSON delivery FAILED: leading code fence and one missing outer brace.
Independent review approved one-off envelope-only salvage: remove that first
fence line, append one brace, parse once. No escape decoding or source edits.
Exact original prefix plus exactly the two requested assignments was verified
independently and by the parent; generic parser/policy was not relaxed.

## Physical execution and submission gates

Fresh official rules/code requirements on Sep6: notebook-only, offline, maximum
12h CPU/GPU, submission.csv; five daily submissions. Fresh authenticated API:
numToday0, numTotal6, numAllowedNow5. All three reused pilkwang dataset metadata
licenses were freshly confirmed CC0-1.0. No new assets are introduced.
Rules: https://www.kaggle.com/competitions/biohub-cell-tracking-during-development/rules
Runtime: https://www.kaggle.com/competitions/biohub-cell-tracking-during-development/overview/code-requirements

Run one private GPU kernel serially with timeout43200. Public-four runtime is
not a guarantee for hidden roughly200 videos; prior rough extrapolation was
near12h and the effect of motion OFF is unmeasured. Do not claim the9.6h/80%
project buffer is satisfied. Record actual GPU, runtime, errors and asset pins.

After COMPLETE require exact version/source binding, expected assets and no
fallback, motion OFF/validator OFF, finite valid CSV and valid consecutive-time
graph for all four public datasets. Only then submit that immutable version once.
On uncertain acceptance, inspect history before any retry. Follow to terminal
LB or execution failure. No post-LB tuning within E26. Keep E23 as incumbent
unless later official local evidence and the unchanged adoption gates justify
replacement; public-LB improvement alone is not generalization or a gold result.

Execution status at preregistration: NOT STARTED. No accepted E26 submission.
