# Biohub gold candidate landscape

Updated: 2026-08-30 18:45 JST
Scope: read-only public evidence and the existing experiment ledger. This is a
research/prioritisation note, not approval to push or submit a Kaggle notebook.

## Executive verdict

- The live leaderboard has two teams at `0.962`. The working gold proxy remains
  rank 15 at `0.945`; the `0.945` tie spans ranks 15--17. A score of `0.947`
  occupies ranks 10--12, so `>=0.947` remains the correctly buffered target.
- E23 is the account's reproducible baseline at `0.924`, leaving `+0.023` to
  target. The verified external anchor is `0.933`, leaving `+0.014`.
- No public notebook above `0.933` was found whose score can be joined to an
  immutable submission and run. The most visible score-named candidates are
  false leads: `.937` is actually `0.930` or `0.931`, and `.940 EMA` is actually
  `0.926`.
- The remaining gap is too large for another scalar threshold or retention
  calibration. The ledger's largest measured oracle is association (`~+0.065`),
  followed by missed detections (`~+0.016`). Division has a large mathematical
  ceiling (`~+0.096` on eval-36) but every rule-only or old-model selector has
  failed the precision/generalisation gates.
- **No candidate may be scored for adoption until the E23 notebook-to-local
  parity contract is complete.** In particular, E23 all-node centroid
  refinement gave a public-four mechanism delta of `+0.012884`, but that is an
  in-sample diagnostic, is already part of E23, and does not validate the
  currently incomplete local port.
- The first bounded candidate remains the separately designed structural
  twin-only rewire experiment. This note deliberately does not duplicate its
  detailed algorithm. The next independent lever is the frozen public association
  ranker, followed by detection consensus and, if needed, an explicit
  two-child/division head.

## Live boundary snapshot

Read-only commands used:

```text
kaggle competitions leaderboard biohub-cell-tracking-during-development \
  --show --page-size 200 --format json
kaggle competitions list -s biohub-cell-tracking-during-development --format json
kaggle competitions submissions biohub-cell-tracking-during-development \
  --page-size 100 --format json
```

Snapshot at 2026-08-30 18:45 JST:

| Item | Live value | Interpretation |
|---|---:|---|
| Teams / account rank | `2,870 / 491` | protocol's earlier `2,869 / 488-489` is stale |
| Account best | E23 submission `55760016`, `0.924` | immutable account anchor; run `344747469` |
| First place | `0.962` (two teams) | E23 gap `+0.038` |
| Rank-15 gold proxy | `0.945` | tie spans ranks 15--17 |
| Buffered target | `0.947` | ranks 10--12; E23 gap `+0.023` |
| Verified external anchor | `0.933` | ranks 75--85 at this snapshot; target gap `+0.014` |

The leaderboard is mutable; team IDs and submission dates are available from
the official API, but the row positions above are a dated snapshot, not
immutable provenance. Live source: [competition leaderboard](https://www.kaggle.com/competitions/biohub-cell-tracking-during-development/leaderboard).

## Public frontier provenance

### Highest directly verified reproducible public run

The highest public run found with a direct equality between
`submission.sourceScriptVersionId` and `kernelRun.id` remains:

| Field | Immutable value |
|---|---:|
| notebook | `rishabhr0y/933-biohub-bidir30` |
| kernel / version | kernel `132471639`, v2, version ID `207794815` |
| run / session | `345883663`, `COMPLETE`, T4, `2073.385281 s` |
| submission / public score | `55877457` / `0.933` |
| executed source SHA256 | `75714eceb5da6504e2b72af8d5cd69ccbd7fb9beff43f30b90fb40576e397142` |
| canonical AST SHA256 | `0d1809e9e71ec410664ade0204b1a17896dc95954a721ea0bc46773f6fbb221d` |

Immutable session URL:
[scored `.933` v2](https://www.kaggle.com/code/rishabhr0y/933-biohub-bidir30?scriptVersionId=345883663).
Full artifact hashes and the exact `.931 -> .933` semantic diff are already in
`analysis/external_933_provenance.md`.

The score is verified; its causal attribution is not. The exact scored `.931`
parent changes both bidirectional association weight `0.15 -> 0.30` and
secondary detection weight `0.475 -> 0.80`. The joint `+0.002` is below the
`0.005` LB noise floor.

### Score-named notebooks rejected by immutable joins

The discovery sweep covered the latest 100 competition notebooks, the first 100
from Kaggle's `scoreDescending` discovery order, plus searches for `093`, `094`,
and the score-named frontier candidates. The score-sorted discovery list still
contains pre-patch metric-hack notebooks, so it was used only to find slugs.
For each plausible post-patch candidate, `ListKernelVersions` was joined to
`GetKernelViewModel`; a list order, title, or printed proxy was never accepted
as a score.

| Notebook claim | Scored immutable version | Submission | Actual public score | Verdict |
|---|---|---:|---:|---|
| `rishabhr0y/biohub-937-sdw80` | kernel `132288996`, v2/version `207558497`, run `345630447` | `55862755` | `0.930` | title is false as score evidence |
| `notoverkil/biohub-base-0937` | kernel `132468740`, v3/version `207789478`, run `345877408` | `55871825` | `0.931` | title is false as score evidence |
| `grafael/biohub-ct-0940-ema` | kernel `132486215`, v1/version `207816425`, run `345908732` | `55876103` | `0.926` | long-horizon EMA did not establish a frontier |
| `grafael/biohub-ct-0938-harmonic` | kernel `132484278`, v1/version `207812699`, run `345904404` | none | none | completed run, no score join |

The highest additional non-hack notebook immediately below `.933` in the
discovery order was `anhadmahajan06/biohub-track-your-cells-development`: its
best verified run is v27/version `207830283`, run `345923245`, submission
`55875692`, score `0.932`. The next checked candidates were also below the
anchor: `navazshfathi/best-score` v3/version `206169778`, run `344131686`,
submission `55688536`, score `0.919`; `flexonafft/biohub-harmonic-fusion`
v22/version `207396413`, run `345465485`, submission `55827390`, score `0.928`;
and `anvithpothula/biohub-dual-seed-harmonic-bidirectional-fusion` v1/version
`207188763`, run `345253418`, submission `55808334`, score `0.928`.

Session URLs:
[SDW80 v2](https://www.kaggle.com/code/rishabhr0y/biohub-937-sdw80?scriptVersionId=345630447),
[base-0937 v3](https://www.kaggle.com/code/notoverkil/biohub-base-0937?scriptVersionId=345877408),
[EMA v1](https://www.kaggle.com/code/grafael/biohub-ct-0940-ema?scriptVersionId=345908732),
[harmonic v1](https://www.kaggle.com/code/grafael/biohub-ct-0938-harmonic?scriptVersionId=345904404),
[Anhad v27](https://www.kaggle.com/code/anhadmahajan06/biohub-track-your-cells-development?scriptVersionId=345923245),
[Navazsh v3](https://www.kaggle.com/code/navazshfathi/best-score?scriptVersionId=344131686),
[Flexon v22](https://www.kaggle.com/code/flexonafft/biohub-harmonic-fusion?scriptVersionId=345465485),
[Anvith v1](https://www.kaggle.com/code/anvithpothula/biohub-dual-seed-harmonic-bidirectional-fusion?scriptVersionId=345253418).

This is not a proof that no unpublished method exceeds `0.933`; the live board
obviously does. It is evidence that no discovered **public and reproducibly
scored** notebook above the existing anchor is currently available.

### Public ranker asset

The 22-feature local association ranker is a real, downloadable artifact, but
its existing notebook lineage is not itself frontier evidence. The best scored
version found for `yusuketogashi/no-hack-biohub-cell-another-approch-3rd` was
v21 / version `203031633` / run `340377068` / submission `55272257` at `0.915`.
Its value is therefore as an orthogonal component to test on E23, not as a
ready-made higher-scoring solution.

Artifact: Kaggle dataset ID `11102521`, immutable dataset-version source ID
`17840600`,
[`pilkwang/biohub-local-association-ranker-unet300-v1`](https://www.kaggle.com/datasets/pilkwang/biohub-local-association-ranker-unet300-v1).

| File | SHA256 |
|---|---|
| `ASSOCIATION_RANKER_MANIFEST.json` | `b1f80944ea02ad103bb938eedc7126c050e9ce345327dc33df677440be14f407` |
| `model/local_association_ranker.pt` | `b49a9ab4228daba63d31056ae5beef9fd3e8bcd3ba26d9f57a45ef828d4fb4b8` |
| `model/model_info.json` | `ba8d338f4eb0b8cfa9bcffc71f3619353ed3dc297b091eebaff23e5d266a96a7` |

The manifest fixes 22 features and says the ranker is a constrained local
tie-breaker, not a global veto. Existing public run:
[ranker lineage v21](https://www.kaggle.com/code/yusuketogashi/no-hack-biohub-cell-another-approch-3rd?scriptVersionId=340377068).

## What the remaining score can plausibly come from

All ceilings below are diagnostics, not additive promises. They were measured
on the older dual-seed eval graph and must be re-counted after E23 parity.

| Lever | Diagnostic ceiling | Plausible next single-factor delta | Existing negative evidence / constraint |
|---|---:|---:|---|
| Association | about `+0.065` from E10 wrong-link/FP oracle | `+0.003` to `+0.010` | same-model probability prune `+0.0013`, margin `+0.0014`; motion max `+0.0003`; ILP candidate/weight sweep `+0.0003..+0.0009`. A useful signal must be orthogonal to the current transformer. |
| Detection | about `+0.016` from 127 missing-endpoint edges | `+0.003` to `+0.008` | threshold `0.96875 -> 0.9375` added 0.7% nodes but only `+0.0007` recall and score `-0.0015`; E20 local hard-window gain reversed from base2 `0.919` to LB `0.906`. Simple thresholding or unconstrained fine-tuning is closed. |
| Retention / node budget | observed 2.5% node-count movement is worth only about `+0.0023` through the adjustment term alone | `0` to `+0.003` | `.931 -> .933` changed SDW and bidirectional weight together for only `+0.002`; the alleged `.937` SDW80 run is actually `0.930`. Retention cannot supply the `+0.014` anchor-to-target gap by itself. |
| Division | eval-36 perfect-division headroom about `+0.096`; rule-only realistic much smaller | rule-only `0..+0.004`; learned structured head `+0.006..+0.020` | safe-div widening gave `+0.0036` on eval-12 but only `+0.0016` on eval-24, median negative, worst around `-0.02`; CNN/GBDT/forward/reverse probability selectors all missed their rank gates; oversampling left TP unchanged. |
| Centroid localisation | public-four Phase 2 mechanism delta `+0.012884` | **no remaining delta: already in E23** | exact raw public-four score `0.8958347798 -> 0.9087191654`; in-sample only, and the E23 local port is not yet parity-complete. Do not double-count it as a candidate. |

The official metric explains the asymmetry: an association correction can
remove an FP and FN while adding a TP, whereas node shedding is attenuated by
the `0.1` count coefficient. A division gain is valuable only when the local
directed two-branch topology is correct; a weakly connected proxy is invalid.
Metric source pinned at commit
[`075fc5f5`](https://github.com/royerlab/kaggle-cell-tracking-competition/tree/075fc5f5a52d11077f9dc2b074644618f26939e2).

Public discussion is consistent but weak evidence. A current third-place
participant recommends working detection, then linking, then division, while a
`0.933` participant describes the public `0.92--0.933` field as variants of the
same UNet/transformer/ILP stack. These are qualitative reports, not scored
ablations: [layer discussion #737543](https://www.kaggle.com/competitions/biohub-cell-tracking-during-development/discussion/737543).
Trackastra is useful only as a design precedent that learned temporal
association can be linked with division-aware greedy or ILP modes; it is not a
drop-in 3D Biohub score claim. Official implementation pinned at
[`6a8ce94e`](https://github.com/weigertlab/trackastra/tree/6a8ce94ee7c5a1f22c8eb77229ea5a0bc95a7b5b).

## Runtime and code-submission envelope

The official competition requirements are:

- CPU or GPU notebook runtime `<=12 h`;
- internet disabled;
- freely and publicly available external data and pretrained models allowed;
- output must be named `submission.csv`;
- competition API reports five submissions per day and team size at most five.

Source: [competition overview and Code Requirements](https://www.kaggle.com/competitions/biohub-cell-tracking-during-development/overview).

The public `.933` session took `34m33s`, with `9.02 min` reported for prediction
on four public videos. E23-family public runs are roughly 33--38 minutes on two
T4s, but hidden evaluation is about 200 videos and community reports put scoring
at 9--12 hours ([submission-time discussion #734237](https://www.kaggle.com/competitions/biohub-cell-tracking-during-development/discussion/734237)).
Therefore:

- post-processing/ranker/head inference should consume at most about 5--10% of
  E23 wall time;
- another full detector or TTA pass is unsafe unless a timed 36-video run and a
  conservative hidden extrapolation remain below about 10.5 hours;
- training must be separated from the submission notebook and produce a public,
  hash-pinned artifact; the scoring notebook must stay fully offline;
- public-four completion time is not itself proof that the hidden code run fits
  the cap.

## Information-value experiment queue

### Hard prerequisite: E23 parity (not an experiment result)

Before reading any candidate score, require exact agreement between the E23
notebook reference and local port for node IDs, rounded coordinates, directed
edges, forks, official inputs/results, and telemetry. The Phase 2 centroid delta
may be recorded as mechanism evidence but cannot waive this gate. Every arm
below is invalid if parity or on/off identity fails.

### 1. Structural twin-only rewire, bounded on/off

This remains the first candidate because the old census assigns most missed
divisions to already-linked daughters and because the change can be evaluated
entirely on existing raw graphs. Detailed selection, invariants, and edit logic
belong to `analysis/steal_twin_design.md` and are intentionally not repeated.

- Single factor: structural rewire off vs on, fixed E23 graph and all other
  knobs.
- Required artifacts: parity-certified E23 eval-12/24/36 graphs, official GT,
  operation audit table, exact config/source hash.
- Expected delta: `+0.004..+0.010`; it is the only rule-based division candidate
  with a census-backed path to more than one TP.
- Local gate: eval-12 mean `>=+0.005`, eval-24 mean `>=+0.003`, aggregate division
  TP `>=+4`, adjusted-edge loss no worse than `-0.002`, median nonnegative, worst
  video `>=-0.002`, and both embryo lineages nonnegative.
- Failure: any parity/invariant failure, TP gain below four, concentrated
  `-0.01`-class video loss, or lineage sign reversal.

### 2. E17 frozen 22-feature association ranker on E23

- Single factor: blend the hash-pinned ranker as its documented constrained
  tie-breaker vs ranker off. Do not tune the 22 features or use it as a global
  edge veto in the same experiment.
- Required artifacts: E23 parity graphs and pre-ILP candidate table, ranker
  manifest/model hashes above, per-edge base and ranker scores, emitted graph.
- Expected delta: `+0.003..+0.008`; association has the largest oracle, but the
  ranker's old standalone lineage peaked at only `0.915`.
- Local gate: eval-12 `>=+0.005`, median positive, worst `>=-0.002`; then
  independent eval-24 `>=+0.003`, both lineages nonnegative, and runtime overhead
  `<5%`.
- Failure: improvement `<=+0.002`, a gain carried by one video, more than
  `0.002` adjusted-edge loss in either lineage, or any feature/schema mismatch.

### 3. Isolate secondary detection weight on the `.933` semantics

- Single factor: SDW `0.475` vs `0.80` while fixing bidirectional weight at
  `0.30` and fixing the complete `.933` source semantics. This is not a replay
  to reconfirm the already verified `0.933` score.
- Required artifacts: AST-pinned `.933` source, one missing `0.475 @ bidir0.30`
  eval-36 raw arm, the existing `0.80` arm or an exactly paired regeneration,
  per-frame node/candidate counts and official paired scores.
- Expected delta: `-0.002..+0.003`; information value is causal resolution, not
  a likely gold jump.
- Local gate: eval-36 mean `>=+0.003`, median positive, worst `>=-0.002`, both
  lineages nonnegative, node-count adjustment reported separately from edge
  topology.
- Failure: below gate or public-four-only benefit. Do not spend an LB query on a
  sub-noise effect.

### 4. Two-seed + DeepCenter consensus rescue for sub-threshold detections

- Single factor: add low-threshold detections only when both temporal detector
  seeds and the frozen DeepCenter response agree; all association and retention
  settings remain E23. This tests a detector-quality hypothesis, not another
  raw threshold sweep.
- Required artifacts: per-seed pre-threshold center logits/coordinates over
  eval-36, DeepCenter scores, fixed candidate matching, node-budget telemetry,
  parity E23 graphs. These artifacts do not currently exist and require one
  bounded generation run.
- Expected delta: `+0.003..+0.008`, bounded by the old `+0.016` detection oracle.
- Local gate: eval-12 `>=+0.005`, node recall `>=+0.003`, adjusted edge not down,
  median positive, worst `>=-0.002`; confirm eval-24 `>=+0.003` and keep projected
  hidden runtime `<10.5 h`.
- Failure: recall rises by `<0.002`, node penalty consumes the edge gain,
  detections concentrate in one lineage/video, or artifact generation implies
  an unsafe extra full inference pass.

### 5. Frozen-encoder explicit two-child/division head

- Single factor: add a small tuple head that scores `(parent, child1, child2)`
  jointly, with the E23 detector/encoder and ordinary association logits frozen.
  The output is consumed by a division-aware graph decision; do not combine it
  with new detector fine-tuning in the same experiment.
- Required artifacts: hash-pinned E23 checkpoints, video-group OOF split of all
  151 training divisions, fixed hard-negative tuples, training curves, OOF
  logits, parity eval graphs. A frozen head is compatible with the 12-hour
  envelope; scratch retraining of the 400-epoch backbone is not (~900 GPU-h by
  E19).
- Expected delta: `+0.006..+0.020`; the mathematical ceiling is much larger, but
  sparse labels and embryo shift make that ceiling unrealistic.
- Local gate: division TP `>=+4` on eval-12 and again in aggregate eval-36,
  official score `>=+0.005` on eval-12 and `>=+0.003` on eval-24, adjusted-edge
  loss `<=0.002`, median/worst/lineage gates unchanged.
- Failure: OOF precision collapses at deployment base rate, TP remains unchanged
  as in E20, or improvement requires joint backbone fine-tuning that cannot be
  cleanly validated locally.

## Priority decision

After E23 parity, run the bounded structural candidate first, then the ranker.
Those are low-runtime, graph-level tests aimed at the largest measured error
mass. SDW isolation is useful only to decide whether the `.933` detection axis
should be carried forward; it is not expected to reach gold. If association
tests fail, test consensus detection before paying the higher implementation
and validation cost of a learned division head.

Do not queue more motion smoothing, scalar ILP weights, raw detection-threshold
sweeps, checkpoint rollback, or unconstrained short-track retention: the ledger
already contains direct negative evidence, and none has a credible `+0.014`
path from the verified anchor.
