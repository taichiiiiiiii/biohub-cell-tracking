# E17 frozen association ranker on E23: constrained tie-break v1 design

Updated: 2026-09-05 (Asia/Tokyo; status reconciliation only, frozen candidate unchanged)

Status: **HOLD — no candidate implementation/readout; current-commit prerequisites,
verified consumer artifact, feature/support-source contract, and pre-ILP inputs remain incomplete**

2026-09-05 reconciliation: E23 public-four Phase 3/4 parity completed on
2026-08-30 at `022222b79a10df4908ee46b7ccba6ea088aa255c`, as recorded in the
[ledger](experiment_ledger.md). A hash-matching ranker cache is quarantined,
not absent; it is not an approved consumer root. Follow the
[acquisition runbook](e17_ranker_artifact_acquisition_runbook.md) for the
remaining version/license/source/feature gates. The current facts below
supersede the original 2026-08-30 missing-artifact/parity status.
Exact-implementation-commit parity is still required.
The current execution order is in
[the evidence-based strategy](experiment_strategy_20260905.md).

This document specifies one candidate only: `e23_e17_ranker_tiebreak_v1`.
It is subordinate to the [gold-loop protocol](gold_loop_protocol.md) and the
[gold candidate landscape](gold_candidate_landscape.md). It does not authorize
a Kaggle push, run, or submission, and it does not change `official/`, data, or
existing output artifacts.

## Verdict first

The candidate is a frozen 22-feature model used only to reorder the two leading
E23 incoming-edge candidates in an already ambiguous, target-local conflict
set. It must not add or delete candidates, change the E23 edge threshold,
globally rescore the candidate graph, or veto an edge. The local conflict's
original two E23 score slots are merely assigned to the two candidates in the
ranker's local order; the per-target candidate membership and score multiset
remain unchanged. The unchanged ILP remains the only graph selector.

The experiment cannot start yet. The implementation-commit prerequisite
receipts and approved ranker consumer bundle are not complete. In addition,
the existing eval-36 GEFFs contain only
the solved graph and not the full pre-ILP candidate table or the 22 features.
These are fail-closed prerequisites, not reasons to silently approximate the
ranker downstream.

## Evidence boundary

### Verified repository and artifact facts

- E17 was preregistered as the public 22-feature association ranker on the
  dual-seed association path in the
  [experiment ledger](experiment_ledger.md). There is no E17 implementation,
  named profile, or ranker-specific test in the current tracked `src/`,
  `scripts/`, or `tests/` trees.
- The public artifact identity recorded by the
  [candidate landscape](gold_candidate_landscape.md) is Kaggle dataset
  `pilkwang/biohub-local-association-ranker-unet300-v1`, dataset ID `11102521`,
  immutable dataset-version source ID `17840600`. The expected files and
  SHA256 values are:

  | Relative file | Required SHA256 |
  |---|---|
  | `ASSOCIATION_RANKER_MANIFEST.json` | `b1f80944ea02ad103bb938eedc7126c050e9ce345327dc33df677440be14f407` |
  | `model/local_association_ranker.pt` | `b49a9ab4228daba63d31056ae5beef9fd3e8bcd3ba26d9f57a45ef828d4fb4b8` |
  | `model/model_info.json` | `ba8d338f4eb0b8cfa9bcffc71f3619353ed3dc297b091eebaff23e5d266a96a7` |

- Hash-matching bytes for the three consumer files exist in
  `outputs/local/e17_quarantine/cache_20260830T185150JST/payload/`, alongside
  two provenance-only dataset files. The quarantine is not a consumer root.
  Version binding, license acceptance, support-source/extractor semantics,
  feature units/transforms/missing-value rules, complete model architecture,
  and output calibration remain unverified. Serialized feature names and
  tensor shapes do not establish those contracts. A remembered or
  reverse-engineered substitute is not acceptable.
- The landscape records the artifact as a constrained local tie-breaker and
  the old public ranker lineage as only `0.915`. It is evidence for an
  orthogonal component to falsify, not a claim that it beats E23.
- The submitted E23 inference computes the dual-seed and bidirectional
  association tensor before candidate thresholding and ILP. The local
  post-processing port in
  [`pipeline.py`](../src/biohub/public_postproc/pipeline.py) begins later, from
  a GEFF graph, then may replace its edges in `motion_relink_edges`; it has no
  access to the complete pre-ILP association matrix.
- A read-only check of all 36 pinned eval GEFFs found 730,183 edges and only
  the semantic edge properties `solution`, `edge_prob`, and `edge_dist`; every
  `solution` value was true. No ranker features or rejected candidates are
  present. Thus the pinned GEFF bundle is suitable for E23 post-processing
  parity, but not for this upstream ranker A/B.
- Historical E23 Phase 3/4 public-four parity is complete at
  `022222b79a10df4908ee46b7ccba6ea088aa255c`. Before this ranker candidate's
  scores, require new strict E23/base1 prerequisite receipts bound to the
  exact ranker implementation commit; the historical result alone does not
  certify later code. See the [parity runbook](e23_parity_runbook.md).

### Frozen hypotheses, not verified facts

- Association remains the largest measured error lever, so a signal
  independent of the current transformer may yield about `+0.003..+0.008`.
- Restricting the ranker to the two best candidates of low-margin incoming
  conflicts can remove wrong-parent links without exposing the graph to a
  global learned veto.
- Reusing E23's already-frozen low-margin boundary (`0.35`) and the E17 public
  lineage's recorded `85% ranker / 15% base` blend gives a conservative,
  no-search first arm. Neither constant is evidence of optimality on E23.
- The frozen model may have been trained on all competition training videos.
  The local paired A/B can still falsify the pipeline change, but it cannot
  establish hidden-video generalization.

### Source-semantics eligibility clarification (2026-09-05; no v1 knob change)

The pretrained model's original grouping direction is not established by its
generic "constrained local association tie-breaker" intent. Before implementing
this incoming/pre-ILP consumer, the exact training/extractor/consumer source
must establish group key (source versus target), labels, extraction stage,
feature units/transforms, output domain/calibration, and compatibility with
the E23 candidate rows. The quarantined stats report 126,705 groups but 126,828
positive rows. This is a warning against assuming at most one true incoming
parent per group, not proof of outgoing or posthoc semantics: the aggregation
unit is unverified. If incoming/pre-ILP use cannot be justified, retain HOLD;
do not transpose groups, approximate post-ILP features, or redefine frozen v1.

2026-09-06 read-only audit: the quarantined manifest/info still do not define
the grouping key, labels, extractor, or output calibration. The exact support
predictor (`c44e771ba5980b820f93091e03a303c25dfe8f3232e501f54dc9565731c234b9`)
first thresholds/sorts association candidates (lines 454–468), then applies
configured per-source child/per-target parent caps while constructing edges
(lines 470–488), and only later builds/solves the graph (lines 554–564).
Thus "before ILP" alone does not identify the full candidate population: source
eligibility must also bind extraction/insertion relative to these optional
caps and the actual executed runtime patches. This is a source-contract
clarification, not evidence that the ranker uses either stage or is incompatible.
No ranker-specific extractor/trainer/consumer was found in the 13 pinned support
Python files; the v21 source remains uncollected. HOLD and frozen v1 are unchanged.

## Exact candidate: `e23_e17_ranker_tiebreak_v1`

The following constants are part of the version, not a tuning surface:

| Control | Frozen v1 value |
|---|---:|
| profile/tag | `e23_e17_ranker_tiebreak_v1` |
| base profile | exact parity-certified `e23` |
| ranker mode | `incoming_top2_score_slot_permutation_v1` |
| candidate direction | `t -> t+1` only |
| local group | candidates sharing one `target_id` |
| local pool | the top two by frozen E23 base order |
| active base-margin gate | `p_base(top1) - p_base(top2) <= 0.35` |
| local ordering score | `0.15 * p_base + 0.85 * p_ranker` |
| inference | CPU, float32, `eval()`, inference mode, fixed batches |
| graph mutation | none; only the two original E23 score slots may swap |
| candidate add/delete/global veto | forbidden |

`0.35` is reused from the E23 low-margin consensus configuration; `0.85/0.15`
is the recorded public E17 lineage blend. Changing the margin, blend, pool
size, feature set/order, normalization, distance gate, model, or ILP weights
creates a different experiment and is prohibited after any GT-backed readout.

### Immutable artifact and feature-contract preflight

The future materialized root must be uniquely resolved by the three hashes
above, not by directory name alone. The preferred ignored location is
`outputs/kaggle/e17_artifacts/pilkwang/biohub-local-association-ranker-unet300-v1/`,
but path choice has no authority over identity. Before candidate enumeration,
one preflight must:

1. require exactly the three expected files, regular files with no symlink
   escape, and byte-for-byte SHA256 equality;
2. parse both JSON files strictly, reject duplicate JSON keys, non-finite
   numbers, unknown schema/model versions, missing required fields, or a
   disagreement between manifest and `model_info.json`;
3. copy the manifest-declared feature list verbatim and require exactly 22
   unique ordered names; validate each declared dtype, unit, transform,
   normalization statistic, missing-value rule, coordinate convention, and
   candidate-radius convention before loading weights;
4. load weights with the safe weights-only path, require the manifest-declared
   architecture and exact state-dict keys/shapes, and prove the first layer
   consumes 22 values and the output has the declared scalar semantics;
5. run manifest-provided test vectors if present. If none exist, record that as
   a provenance limitation and require locally constructed structural vectors
   only for shape/order/finiteness—not for semantic calibration;
6. hash the canonical feature-contract JSON, model state schema, loader source,
   and extractor source into the run manifest before any GT access.

There is no fallback model, partial feature vector, imputation invented by the
port, feature reordering, or permissive `strict=False`. Artifact absence or any
schema incompatibility stops the video/run and leaves exact E23 as the only
fallback. Copying values verbatim from the pinned manifest after it is
materialized completes this validation contract; it is not permission to tune
them.

### Exact pipeline insertion boundary

The ranker belongs in the inference repository, not in
`src/biohub/public_postproc/`. Its sole insertion boundary is:

1. unchanged E23 detection and frame-retention guard;
2. unchanged primary/secondary edge logits and bidirectional harmonic fusion;
3. unchanged E23 probability conversion and edge-candidate threshold, yielding
   the complete candidate rows that E23 would send toward graph construction;
4. **extract the manifest-defined 22 features and apply the local score-slot
   permutation below**;
5. unchanged `build_graph` / `tracksdata` construction and unchanged ILP;
6. unchanged GEFF writing and the parity-certified E23 post-processing stack.

This is after the final E23 association score exists but before candidate rows
are consumed by ILP. Running on solved GEFF edges, after ILP, during motion
relink, or after safe division is a schema error and must stop. The off arm's
candidate table hash must equal the unmodified E23 table hash before ILP.

### Candidate pool and deterministic resolution

For every candidate row, preserve immutable fields `e23_base_probability` and
`e23_base_objective`. Reject the whole video on duplicate `(source_id,
target_id)`, missing nodes, non-finite values, or a nonconsecutive edge. Process
datasets, frames, targets, and sources in ascending canonical order.

For each target-local group `G(target)`:

1. Sort by `(-p_base, distance_um, source_id, target_id)`. A singleton is
   inert. With at least two rows, define `a,b` as the first two; every tail row
   is inert.
2. If `p_base(a)-p_base(b) > 0.35`, the group is inert. At the inclusive
   boundary and below it, build the exact manifest-ordered feature vectors for
   `a,b` and obtain finite `p_ranker` values.
3. Order `a,b` by
   `(-(0.15*p_base+0.85*p_ranker), -p_ranker, -p_base, distance_um,
   source_id, target_id)`. This complete key resolves numeric ties without
   depending on dict, tensor, GPU shard, or filesystem order.
4. Preserve the original two E23 objective values as a sorted pair. Assign the
   better original slot to the locally first row and the other slot to the
   second row. Do not alter any other row or any candidate metadata. If the
   local order equals the base order, perform no write.
5. Pass the unchanged candidate set to the unchanged ILP. Do not greedily emit
   an edge. Targets make disjoint local groups; shared sources and possible
   divisions remain global conflicts resolved only by the existing ILP.

The invariant at this boundary is, for every target and globally:

```text
candidate row identities before == candidate row identities after
multiset(E23 objective slots) before == multiset(objective slots) after
added == deleted == globally_vetoed == 0
changed rows == 2 * swapped target groups
```

This construction lets the ranker choose only between the two candidates E23
already considered most competitive. It cannot promote a tail candidate,
remove a low ranker score, create an edge below threshold, or alter the total
objective mass of a target group.

## Off, dry-run, and no-retuning contracts

- `off`: do not resolve/load the ranker artifact, extract features, or touch
  candidate values. Pre-ILP candidate bytes, solved GEFFs, final submission,
  and all common telemetry must match exact E23. Ranker counters are zero or
  absent according to one frozen schema.
- `dry-run`: require and validate the artifact, extract and score active local
  pools, and write separate audit telemetry, but never assign score slots.
  Candidate bytes, solved GEFFs, final graph/submission, and common E23
  telemetry must be byte-identical to `off`.
- `on`: differs from dry-run only by the deterministic two-slot assignment.
  Detection coordinates, candidate membership, base scores, all non-ranker
  config, ILP weights, and E23 post-processing remain identical.
- After the first GT-backed eval12 score is read, no code, artifact, feature
  contract, constant, batching rule, tie key, or gate may change. A failed arm
  is recorded and rejected; it is not repaired on eval24/eval36.

The candidate profile must be an exact extension of the parity-certified E23
inference/post-processing configuration. A config-diff assertion permits only
the master mode (`off|dry_run|on`), the pinned artifact paths/hashes, fixed v1
constants above, bounded audit paths, and the experiment tag.

## Telemetry and conservation

Persist per-dataset integer counters plus a full hash-pinned pre-ILP candidate
table in an ignored run directory. The full table contains identifiers,
`p_base`, original/final objective slot, 22 named features, `p_ranker`, local
score, decision, and complete sort key. It is required evidence, not an input
to metric calculation. A human-readable JSONL sample is opt-in, sorted, and
capped at 200 records; overflow is counted.

Required counters include:

- `ranker_candidates_total`, `ranker_targets_total`,
  `ranker_singleton_targets`, `ranker_multi_targets`,
  `ranker_multi_tail_edges`;
- `ranker_inactive_margin_targets`, `ranker_active_targets`,
  `ranker_scored_edges`, `ranker_base_order_kept_targets`,
  `ranker_swapped_targets`, `ranker_changed_rows`;
- artifact/contract validation status, feature-vector rows, per-feature
  non-finite counts, model batches, output non-finite counts, debug rows and
  dropped debug rows;
- pre/post candidate row count, candidate identity SHA, per-target objective
  multiset SHA, detector-coordinate SHA, off/on GEFF SHA, final graph SHA,
  wall time, and peak RSS.

Assert, per dataset:

```text
targets_total == singleton_targets + multi_targets
candidates_total == singleton_targets + 2*multi_targets + multi_tail_edges
multi_targets == inactive_margin_targets + active_targets
scored_edges == 2*active_targets
active_targets == base_order_kept_targets + swapped_targets
changed_rows == 2*swapped_targets
pre_candidates == post_candidates
added == deleted == globally_vetoed == 0
feature_nonfinite == output_nonfinite == 0
```

Counters use first and only disposition; an active target cannot be counted as
inactive. A validation failure occurs before this conservation ledger and
fails the video/run rather than being converted to a rejection count.

## Adversarial tests required before scores

### Unit and property tests

- Artifact absent, wrong hash/size, duplicate JSON key, unknown schema,
  manifest/model-info disagreement, unsafe path, wrong state keys/shapes,
  21/23/duplicate/reordered feature names, wrong dtype/unit/normalization, and
  absent output semantics all fail closed.
- Model output with wrong shape, NaN/Inf, values outside the declared domain,
  or nondeterministic repeated CPU inference fails closed.
- Empty, singleton, two-row, and three-plus-row target groups; duplicate edge,
  dangling node, `t -> t`, `t -> t+2`, non-finite base score/distance, and
  equal-score/equal-distance adversaries.
- Margin cases immediately below, exactly at, and immediately above `0.35`
  using adjacent representable float32 values; blend ties; ranker agreement
  and disagreement; exact score-slot swaps.
- Tail candidates, high-margin groups, unrelated targets, node rows, detector
  coordinates, and every per-target objective multiset are unchanged. There
  is no deletion even for the minimum possible ranker score.
- A source appearing in two target groups is handled independently and left to
  ILP; a possible division is neither forced nor vetoed by the ranker stage.
- Random permutations of rows, dict insertion, tensor batches, and two-GPU
  shard merge order yield identical canonical table bytes, counters, ILP
  inputs, audit JSONL bytes, and graph.
- Reapplying v1 from the immutable `e23_base_*` fields is idempotent. Property
  tests assert membership conservation and `changed_rows == 2*swapped` over
  randomized finite graphs.
- Master off and dry-run produce byte-identical pre-ILP tables, solved GEFFs,
  final submissions, and common stats; on with zero active/swap groups is also
  identical.

### Integration and official-metric tests

- E23 Phase 3/4 parity and base1 non-regression pass before ranker code is
  connected.
- A tiny synthetic candidate table is run through the real unchanged ILP to
  prove a local swap can change parent selection while membership stays fixed;
  counterexamples prove high-margin and tail candidates cannot move.
- Small GT/pred fixtures are scored through `src/biohub/evaluate.py`, including
  one correct-parent gain, one true-edge displacement loss, and a fork-side
  effect. No notebook proxy substitutes for the official path.
- The eval manifest pins code SHA, support-repo source SHA, all model/artifact
  SHA values, input/video set and tree hashes, feature/candidate schema SHA,
  commands, environment/lockfile, candidate-table hashes, outputs, and official
  scorer reference.

## Paired artifact generation and staged falsification

The existing eval GEFFs cannot supply the ranker inputs. After parity closes,
one bounded, label-free inference must emit the complete E23 pre-ILP candidate
table and immutable detector coordinates for each eval video. From that one
table, solve `off` and `on` through the same ILP and exact E23 post-processing.
The off arm must reproduce the parity-certified E23 graph contract before any
candidate metric is read. If it does not, stop; do not compare scores.

The eval12 and eval24 dataset lists are exactly those frozen in
[steal/twin design](steal_twin_design.md); eval24 is the remaining 24 videos
and eval36 is their roll-up. Both subsets have influenced prior work, and
eval36 is not a third independent set. They may progressively falsify this
already frozen candidate, but none is a holdout or proof of generalization.
The four public dummy videos are parity diagnostics only and are excluded from
all adoption gates.

For each video, persist the full-precision official per-sample row and call the
official `summarise` separately for baseline and candidate over eval12,
eval24, eval36, `44b6`, and `6bba`; take differences only afterward. Always
report adjusted edge Jaccard, division Jaccard, combined score, all TP/FP/FN
counts, `num_pred_nodes`, node recall, per-video deltas, mean/median/worst,
nonnegative-video count, and both lineage aggregates. The governing combined
metric is adjusted edge Jaccard plus `0.1 * division Jaccard`; both components
must be reported rather than only the combined number.

### Frozen gates

1. **Prerequisites:** artifact/feature contract and source-semantics eligibility,
   E23 parity, off identity,
   dry-run identity, conservation, tests, and eval36 dry-run feasibility all
   pass. Otherwise HOLD/REJECT without metric readout.
2. **eval12:** paired mean combined-score delta `>= +0.005`, median `> 0`,
   worst `>= -0.002`, official aggregate adjusted-edge delta `>= -0.002`, and
   both lineage aggregate combined-score deltas `>= 0`. Any miss rejects v1.
3. **eval24:** apply the same frozen bytes once. Require mean `>= +0.003`,
   median `>= 0`, worst `>= -0.002`, adjusted-edge delta `>= -0.002`, and both
   lineages `>= 0`. Any miss rejects v1; this is staged falsification, not
   independent confirmation.
4. **eval36 adoption:** require official aggregate combined-score delta
   `>= +0.003`, paired mean `>= +0.003`, median `>= 0`, worst `>= -0.002`, at
   least `22/36` videos nonnegative, adjusted-edge delta `>= -0.002`, division
   Jaccard delta `>= 0`, and both lineage aggregate deltas `>= 0`. To reject a
   gain carried by one video, the largest positive per-video delta must be at
   most 40% of the sum of positive deltas. All feasibility gates must also
   pass before the label `adoption candidate` is allowed.

The landscape's explicit failure conditions remain hard failures: eval12 gain
`<= +0.002`, any feature/schema mismatch, gain concentrated in one video, or
adjusted-edge loss worse than `-0.002` in either lineage. Values between a
failure example and a stage's adoption bar still fail that stage; bars are not
interpolated or relaxed.

## Runtime, RSS, and hidden-200 feasibility

Before official metrics, use the same machine, cold process, raw/images,
artifact, batch size, shard layout, and `PYTHONHASHSEED=0` for exact E23 off,
dry-run, and on. Record end-to-end and ranker-only wall time, peak RSS, per-video
max/p95, candidates/features per second, model batches, candidate-table bytes,
and slowest video. Cache warmth must not be hidden.

All bars are required:

- end-to-end `on` eval36 wall time `<= 1.05 * off` and ranker-stage overhead
  `< 5%` of exact E23 wall time;
- peak RSS `<= off + 1 GiB` and `<= 80%` of the target job's declared RAM;
- conservative `T_hidden = T_eval36_on * 200/36` is below both `10.5 h` and
  80% of the declared Kaggle wall-time limit (for 12 h, `9.6 h` is binding);
- runtime scales with candidate rows/model batches, with no all-video or
  all-frame quadratic materialization; full audit tables stream per video.

Failure keeps exact E23 as the production fallback even if the metric wins.
Changing pool size, batch size semantics, feature precision, or margin to fit
runtime is post-readout retuning and is forbidden for v1.

## Bounded future phases and stop conditions

1. **R23-0 — prerequisite audit:** verify exact implementation-commit E23/base1
   parity; publish the pinned consumer artifact through the acquisition
   runbook and complete the feature/schema/source-semantics audit. No ranker
   implementation before these pass. Historical Phase 3/4 parity alone does
   not certify a later implementation commit.
2. **R23-1 — pure loader/extractor/reranker:** implement strict artifact
   validation, manifest-driven features, local resolution, conservation,
   telemetry, and adversarial unit/property tests; connect dry-run only.
3. **R23-2 — pre-ILP adapter:** opt-in score-slot assignment, unchanged ILP,
   off/dry identity, candidate-table replay, E23/base1 non-regression.
4. **R23-3 — paired evaluation harness:** immutable manifests, official
   per-video/aggregate scoring, runtime/RSS collection, and mechanical gates.
5. **R23-4 — no-retuning readout:** eval36 dry-run census/feasibility, then
   eval12; only if it passes, eval24 and the eval36 roll-up. Append all commands,
   hashes, results, failures, and verdicts to the experiment ledger.

Stop immediately on artifact, schema, or source-semantics incompatibility,
unresolved source-semantics eligibility, inability to reproduce exact
E23 off, off/dry-run identity failure, candidate/objective conservation
failure, nondeterminism, a staged metric miss, or a feasibility miss. Do not
move the ranker downstream to work around missing features and do not reinterpret
it as a global edge veto.

The present decision is **HOLD pending current-commit parity prerequisites,
approved artifact publication, feature/support-source contract verification,
and pre-ILP candidate inputs**. This HOLD does not claim the
ranker hypothesis is false; it means no valid implementation or score readout
can yet be made.
