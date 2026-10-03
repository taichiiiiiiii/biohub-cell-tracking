# E26 unit04 — sealed predictions and staged official scoring

2026-09-06 / Parent design SHIP after independent static API diagnosis and review.
Not an implementation dispatch, physical-run allowance or submission approval.
Prerequisites: accepted complete unit02, unit03 implementation and independent
review; then a separate parent physical-run decision with frozen budgets.
Candidate/split/gates remain [E26](e26_motion_relink_off_design.md).

Accepted cross-process handoff: [runner interface](e26_runner_interface.md).
Unit04 owns private `GT_BINDING.json` and the GT-path-free public
`PREREGISTRATION.json` completion marker in the separate canonical registration
namespace. Both expected digests are fixed before generation dispatch. Only
unit04 parses private registration; unit03 may hash its opaque artifact bytes.
Scoring must verify both original bindings, not accept a replacement registered
after predictions. Include this interface in the frozen scientific source closure.

## Scope and process boundary

Design is owned here by the parent. Design/code/results have an independent SOL
reviewer; the user-designated Qwen implements the existing E26 module/CLI/tests.
No edits to official/, post-processing, E25/ST-R3, old artifacts or AGENTS.
No new candidate, learned parameters, threshold tuning or manual gate exceptions.

Extend E26's CLI with a distinct score process. Do not import scoring modules in
generation paths: score-related imports are deferred until verified scoring entry.
Unit04's preflight prepares an opaque inventory of the exact 36 GT trees and
explicit ZYX scale metadata before generation. Store this separately from unit03's
generation-only child controls. The generation/scoring contract binds that inventory
and all relevant scientific/source bytes without giving GT paths to generation.

Opaque preregistration hashes bytes; it does not open GT graphs or interpret
annotations. After generation, only the current scoring stage may read its GT
metadata/graphs semantically. In particular, an eval12 rejection must prevent
eval24 GT graph/estimated-node-count reads and scoring. Pre-registered byte hashes
are not a claim that no later-stage GT bytes were ever read for integrity checking.

## Verified public API and required guards

Use committed `biohub.evaluate.score_submission(csv_path, gt_dir,
max_distance=7.0, verbose=False) -> (summary, rows)`. It calls the pinned official
metric and returns dataset plus all official per-sample metric columns. Keep
`official/` clean at HEAD `075fc5f5a52d11077f9dc2b074644618f26939e2`.
Bind score source closure additionally to `evaluate.py`, official package init,
`metrics.py`, `division_metrics.py`, and installed score runtime dependencies.
Do not use a proxy, private E25/ST-R3 scorer or old gate implementation.

The wrapper silently skips missing GT and sorts dataset names. Therefore:

- Before a stage call, verify every selected GT tree exists and still matches its
  seal. Parse only those videos' GT metadata and require estimated_number_of_nodes
  finite and >0. `io.estimated_number_of_nodes` can return NaN on missing/bad
  metadata; that is ERROR, not permission to omit adjusted score rows.
- Require explicit pinned image scale metadata with finite positive Z/Y/X values;
  compare it exactly to `read_scale` before scoring. Reject fallback/default caused
  by missing metadata. Pass matching distance 7.0 explicitly, never a caller knob.
- The subset CSV contains only the current stage's exact video set. Validate it
  structurally, preserve selected prediction values/graph, and bind its provenance
  to the sealed full CSV. Record any purely mechanical global-row-ID renumbering;
  do not alter node IDs, endpoints, coordinates or predictions.
- Require returned rows to contain each expected video exactly once with no extras;
  reorder to literal stage order only after set/count/uniqueness validation.
  Require all required official row fields and reject failed/NaN count rows.

Store exact official edge TP/FP/FN, division TP/FP/FN, num_pred_nodes, node_recall,
total_node_ratio, edge_jaccard and adj_edge_jaccard per video. Counts are
nonnegative integers, not bool; ratio may legitimately be negative. Cross-check
num_pred_nodes against the sealed CSV per-video count. Required numeric values
must be finite; do not filter bad rows or replace unknown values.

Official `biohub.evaluate.summarise(rows)` aggregates official per-sample rows.
Use it for each stage, each lineage subset and every singleton video; singleton
`score` supplies each video's combined score. Never reconstruct combined by a
different formula, average singleton scores to imitate the official aggregate,
or substitute paired mean for aggregate delta. Validate summary n and n_adj equal
the exact subset size; do not let official NaN-skipping silently shrink a stage.
Preserve complete per-video rows, singleton summaries, stage and lineage summaries.
Since official summaries omit edge-count totals/total predicted nodes, additionally
save exact sums from the preserved rows and verify them during result reparse.

## Division-free official results

Official summarise returns division_jaccard=NaN when summed division TP+FP+FN=0,
and uses adjusted-edge alone as the combined score. This is valid, not a scoring
failure. Check the exact zero denominator, preserve counts and the official score,
then encode only that undefined division J as JSON null plus an explicit reason.
Every other unexpected NaN/inf is ERROR; JSON writing uses allow_nan=False.

For each paired aggregate, division-J delta is null if either arm's division J is
undefined; retain which arm and its zero-count reason. Do not replace it with zero.
Non-gate null diagnostics are allowed by unit02b. Eval36's stage division-J delta
is a required gate value: undefined there is ERROR, not an exemption or REJECT.
Always use official singleton score differences for paired combined statistics.

## Staged execution and immutable results

1. Start a fresh score process and reject missing/incomplete/old-schema generation
   seals. Verify run/candidate/config/source/dependency/input bindings, all child
   exit/validation receipts, public4 byte parity, both complete 36 CSVs and artifact
   hashes. Seal presence or a status string is not evidence on its own.
2. Create a fresh scoring directory exclusively inside that canonical run. Refuse
   existing result paths, reruns/overwrites and aliases to predictions/GT/source.
   Preserve failure output with an E26 ERROR receipt; do not modify sealed artifacts.
3. Mechanically extract eval12 from each sealed full CSV, score baseline then
   candidate using the exact public API, validate and persist all official rows
   and summaries, compute candidate-minus-baseline deltas and call accepted
   `evaluate_gate("eval12", payload)` from unit02b. Persist the full gate result.
4. Unless that result is SCREEN_EVAL12_PASS, run the common finalizer below and
   return immediately. Do not publish a scientific verdict before finalization.
   No eval24 semantic GT reads, scoring calls or new predictions on that branch.
5. Only on eval12 pass, do the same for the remaining literal eval24. If rejected,
   run the common finalizer for SCREEN_REJECT_EVAL24; do not run eval36 aggregation
   or new inference.
6. Only if both pass, concatenate their saved official per-video rows in literal
   EVAL12+EVAL24 order and call official summarise for 36 and both lineages.
   No third graph-scoring pass. Call unit02b eval36 gate without changing numbers.
7. Common finalizer, mandatory for every scientific terminal status (eval12 REJECT,
   eval24 REJECT, eval36 REJECT or PASS): reparse saved records, verify exact row
   counts/order and artifact/content hashes,
   and revalidate relevant input/source bindings before publishing final verdict.
   A late integrity failure is ERROR even when numerical gates would pass.
   An eval12-rejection finalizer never reads eval24 GT semantics; only its already
   permitted opaque byte bindings may be rechecked. Do not route rejected stages
   around this finalizer or score unvisited stages to complete a report.

Early ERROR uses a separate failure receipt with submission_authorized=false,
the failed operation and preserved partial artifacts. Record hashes/reparse results
for the artifacts that actually exist and explicitly identify missing/unvalidated
ones; do not invent a complete seal or scientific verdict from partial output.

Keep stage/group/singleton row provenance explicit. Save paired distributions,
changed/positive/negative video counts, worst video, node/topology changes and all
official components. No selective summary-only or truncated-tool-output evidence.
Every verdict includes first_failure, all gate results and submission_authorized=false.
The only final scientific success is SCREEN_PASS_REQUIRES_CONFIRMATION, not gold,
holdout generalization, ST-R3 certification or target-environment feasibility.

## Synthetic acceptance before any physical run

Use tiny official fixtures and fake child boundaries, never actual competition GT
for implementation tuning. Cover sealed-input tampering, wrong source/official HEAD,
wrong arm/run/schema, missing GT, default-scale fallback, invalid estimated count,
returned video omissions/duplicates/reorder, NaN-skipped rows, legitimate division-
free singleton/stage behavior, undefined required eval36 division delta, gate
boundaries via the accepted pure API, and complete artifact reparse.
Instrument stage calls/GT readers to prove eval12 failure cannot access eval24
semantically; prove eval36 reuses saved rows and does not rescore or regenerate.
Test score imports absent from generation path, exclusive result creation, partial
failure retention, no-submit labels and no private/old gate dependency.
Test integrity failure in the common finalizer on each early REJECT path; it must
publish ERROR rather than an unverified scientific REJECT, without later GT reads.
Parent rereads full diff and reruns tests/Ruff; independent acceptance is mandatory.

Independent review's common-finalizer must-fix is resolved above: all early REJECT
paths revalidate preserved evidence before publication. Design review SHIP does
not certify an implementation or authorize a physical run.

Physical allowance, local timeout/RAM sizing and input manifests are fixed before
the first real generation. Passing SCREEN still requires target Kaggle full-pipeline
time/RAM/reproducibility, submission equivalence and current-rule checks before any
submission. The existing 36 videos remain retrospective, not a fresh holdout.
