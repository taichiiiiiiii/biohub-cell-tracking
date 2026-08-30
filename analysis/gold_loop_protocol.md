# Biohub gold-loop protocol

Updated: 2026-08-30 (Asia/Tokyo)

This file is the shared operating brief for SOL reviewers, native subagents,
and the external Qwen implementation worker. Read it before changing an
experiment, implementation, or adoption decision.

## Objective and current state

- Competition: `biohub-cell-tracking-during-development`
- Current reproducible public baseline: E23, public LB `0.924`
- Current account rank at the last read-only check (2026-08-30 18:45 JST):
  `491 / 2,870`
- Observed gold-zone proxy: rank 15 at `0.945`
- Working target: public LB `>= 0.947` (a buffer above the observed boundary)
- Public-LB noise estimate from hidden-199 extrapolation: SD about `0.0045`;
  differences below `0.005` are not treated as decisive by themselves.
- Score direction: higher is better.

Leaderboard values are time-sensitive. Refresh them read-only before making a
final submission decision.

## Authority boundary

- Read-only Kaggle/API inspection and artifact downloads are allowed.
- Local code, tests, documentation, and ignored experiment outputs may be
  created or changed within the project.
- Do not push a Kaggle kernel, create a Kaggle submission, choose final
  submissions, push Git commits to a remote, or open/comment on a PR without
  explicit user approval for that external mutation.
- Keep `official/` read-only. It is the reference metric implementation.
- Use `src/biohub/evaluate.py`, which directly calls the official metric, for
  every adoption decision. Notebook proxy scorers are diagnostic only.

## Model and effort routing

- SOL is the primary designer and final reviewer.
- Implementation work is assigned to the external Qwen runner in a clean,
  registered linked worktree. SOL must reread the complete diff and rerun the
  relevant tests before adoption.
- Native subagent effort is task-dependent:
  - medium: inventory, downloads, deterministic operational checks;
  - high: scientific audit, metric reasoning, candidate design, code review.
- Parallelize independent read-only, implementation, and validation work.

## Loop order

- Binding training gate: every new or warm-start training run must pass
  [`analysis/training_loss_gate.md`](training_loss_gate.md) before official
  metric evaluation; E23 primary/secondary remain `LEGACY_HISTORY_UNVERIFIED`
  and cannot receive retrospective PASS, while current post-processing-only
  work is outside this gate.

1. Establish exact parity with the submitted E23 notebook.
2. Run official local scoring and paired per-video diagnostics.
3. Change one causal factor at a time and preregister its gate.
4. Reject weak or unstable changes; record every result in the ledger.
5. Only after a local candidate passes its gate, prepare one immutable Kaggle
   evaluation run and request approval before pushing it.
6. Compare public LB with the preregistered expectation, update the model of
   the failure, then start the next loop.

Do not interpret an ablation result until its input/output parity gate passes.

## E23 parity contract

The default `base1` profile must keep its existing behavior. Add E23 as an
explicit named profile; never silently replace base1 defaults.

E23 effective post-processing settings:

- motion learned bonus `1.0`;
- gap max `2`, radius `5.8 um`, density-adaptive enabled, reference `6.5`,
  gain `0.040`, max step delta `0.125`, neighbors `3`;
- short-track min length `6`, keep division components, gap2 disabled,
  adaptive short-track rescue disabled;
- safe-division parent/candidate `8.0 um`, sister `11.0 um`, existing child
  `10.0 um`, frame cap `0.0076`, global cap `0.00375`;
- structural safe-division gates enabled: parent is mid-track, candidate is an
  orphan at `t+1`, nearest-orphan support, both daughters have exactly one
  distinct successor at `t+2`, and separation growth is at least `2.25 um`;
- all-node intensity-centroid refinement runs before edge-distance filtering,
  motion relinking, gap repair, safe division, DeepCenter queries, and linefit;
  window `(z=1, y=3, x=3)`, local baseline percentile `20.0`, maximum accepted
  shift `2.8 um`;
- DeepCenter is enabled and required, epoch `2`, exact `best.pt` artifact,
  gap veto enabled at `0.25` with confirm span `8.5 um`, safe-division veto
  enabled at `0.12`;
- for gap closing, only a newly inserted synthetic middle at or above the
  confirm span is sent to DeepCenter; an observed/reused middle bypasses it.
  A rejected synthetic middle must be removed with its node/cap counters rolled
  back before either proposed edge is retained;
- use an explicit E23 experiment tag.

Parity is accepted only when the notebook reference and local port agree on:

- node IDs and rounded node coordinates;
- directed edge set and fork count;
- per-video output rows and official metric inputs;
- telemetry, except a documented notebook-only broken counter.

## Experiment assets

- E22/E23 bidirectional-weight `0.30` raw predictions are available in the
  primary checkout at
  `outputs/kaggle/e22_bidir030_eval36_raw/tracking_repo/predictions/unknown/unet_transformer_val/split_0`.
  Workspace consolidation reverified 36 GEFF roots, 1,188 files, and
  10,090,215 bytes on 2026-08-30.
- The exact four public-dummy raw predictions used by the submitted E23 run are
  pinned at
  `outputs/kaggle/e22_bidir030_public4_raw/tracking_repo/predictions/unknown/unet_transformer/split_0`:
  4 GEFF roots, 132 files, 1,583,021 bytes, canonical tree SHA256
  `5fc5fb5e51d127612421970ed66f0ba4229f020940ed458dfdf0fa316f2e8bc1`.
  Use `analysis/e23_parity_runbook.md` for the exact oracle comparison; these
  four videos are parity diagnostics only and never an adoption set.
- No usable `0.20` raw predictions exist in kernel versions v1-v10: v1 reached
  the `0.20` guard but stopped before writing raw GEFF; successful versions are
  `0.30`.
- Therefore a strict `0.20 x 0.30` comparison requires one new approved Kaggle
  evaluation run. Top-k pair-probability dumps cannot reconstruct it exactly.
- The external `.933` reproduction anchor is verified as immutable kernel v2 /
  session `345883663` / submission `55877457`. Its exact `.931` parent differs
  in two behavioral controls together: bidirectional edge weight `0.15 -> 0.30`
  and secondary detection weight `0.475 -> 0.80`. The claimed single-change
  attribution is false; see `analysis/external_933_provenance.md` and the
  hash-pinned ignored bundle under `outputs/kaggle/external_933_reference/`.

## Adoption gates

For a new structural-repair candidate, use paired official scores and require:

- eval12: mean delta at least `+0.005` before expansion;
- eval24: mean delta at least `+0.003`;
- division true positives at least `+4` in aggregate;
- adjusted edge loss no worse than `-0.002`;
- median delta nonnegative and worst video no worse than `-0.002`;
- neither embryo lineage has a negative aggregate delta.

For the already-preregistered 36-video safe-div/bidirectional comparison:

- primary contrast: wide-safe-div at `0.30` minus narrow-safe-div at `0.30`;
- paired mean delta `>= +0.003`, median `> 0`, at least `22/36` nonnegative,
  worst `>= -0.002`, aggregate division FP increase `<= 30`, and lineage-
  stratified paired-bootstrap 95% CI lower bound `> 0`;
- re-adopt `0.30` only if its safe-div interaction is `>= +0.002` and the final
  wide/0.30 cell beats narrow/0.20 by mean `>= +0.005`.

Post-parity queue:

0. Keep the resolved external `.933` as a reproduction anchor. Scored v2 is
   directly linked to its `.933` submission, and latest v4 is executable-AST
   equivalent despite its cancelled run. Reproduce the two-control bundle
   without semantic changes; disable its score-irrelevant train validator only
   after proving public-test graph/SHA equivalence. Do not spend an LB query to
   re-prove the score mapping. Any future approved account-level replay tests
   portability/runtime, not provenance or single-factor causality.
1. Conservative structural steal/twin rewire.
2. E17 association ranker on the parity-verified E23 base.
3. A frozen-encoder joint two-child/division head if the first two cannot
   supply the required gain.

Item 0 is a resolved provenance/reproduction anchor, not a claim that either
knob caused the displayed score. The joint `.931 -> .933` delta is below the
noise floor and worsens three of four public dummy datasets under local
official scoring. The implementation queue remains steal/twin then ranker.
Any different candidate must state why its expected gain and information value
outrank those two.

## Required reporting

For every loop, append the immutable code/artifact reference, input hashes,
exact command, runtime, per-video paired result, aggregate official metrics,
gate verdict, and next hypothesis to `analysis/experiment_ledger.md`. A failed
experiment is retained as evidence; do not silently retune its acceptance bar.
