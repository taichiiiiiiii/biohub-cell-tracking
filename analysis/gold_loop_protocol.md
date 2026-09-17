# Biohub gold-loop protocol

Updated: 2026-09-08 (Asia/Tokyo; bounded low-overhead subagent routing override only)

This file is the operating brief for the parent agent. Read it before changing
an experiment, implementation, or adoption decision.

## Current user override — 2026-09-14

The user explicitly lifted Flash-only implementation and selected Qwen Cloud
qwen3.8-max through the subscription-only canonical authoring route in AGENTS.md.
The parent has created a new active Goal: repair E31, obtain five distinct new
validated exploratory submissions within Kaggle's daily limit, and record their
terminal scores/errors. Settings changes or local scores alone are not completion.
The daily target does not require duplicate or invalid submissions and does not
prove Private Score improvement. Preserve integrity and provenance gates; keep
exploratory submission separate from adoption. Qwen authoring may proceed under
the direct request/active Goal; scheduled Qwen starts remain prohibited.
The older goal, Flash routing, Max evaluation cap and submission prohibition
below are historical. Current AGENTS.md and the user's daily-submission request
take precedence. The separate evaluation launcher remains read-only, even though
the implementation launcher now also uses Max. Do not substitute native/SOL/PAYG.

## Historical objective and authority — 2026-09-12

The active goal is to select one submission candidate that improves the fixed CV
baseline and passes leakage, tracking, repeatability, CPU execution and format
gates with traceable code/config/artifact identities. Public rank alone does not
establish acceptance. Preserve all frozen scientific gates below; no retrospective
relaxation. Record one hypothesis and acceptance criteria before each experiment,
then record both positive and negative results. Stop on success, serious leakage
suspicion, an environment/data obstacle, or eight consecutive valid experiments
without improvement; report the best candidate and unresolved issues.

Current routing is in AGENTS.md: Flash implements, Max performs one eligible
evaluation, parent decides. The September 8 Max-implementation instruction below
is historical, not a live launch instruction. Automatic goal/heartbeat Qwen
launches remain prohibited. Actual submission now requires explicit approval;
the older once-per-loop submission permission below does not override this goal.
The legacy gold leaderboard target is context, not the new completion criterion.

September 12 delegated update: additionally stop on unstable CV or unclear rule/data
conditions. Report best candidate, OOF/CV evidence, leakage risks and next hypothesis.
Keep the frozen folds/seeds/preprocessing/CPU conditions; do not invent a numerical
fold-variance acceptance gate after observing results. No submission, external data
transfer, deployment, commit or push without individual explicit authorization.
Explicitly requested supervised Qwen authoring is allowed within the bounded task;
this does not authorize sending competition data or unattended provider loops.
Max evaluations are capped at 20% of implementation tasks, one per eligible change;
record counts first and hold adoption if a required review cannot fit the cap.

## Historical execution override — 2026-09-08 (superseded above)

The latest user request re-enables bounded native subagents, superseding today's
earlier single-agent instruction. Follow the compact routing/wait/context rules
in `AGENTS.md`: SOL/medium parent; Qwen Cloud qwen3.8-max for implementation via
the verified canonical-compatible, supervised subscription route; usually 1–2 SOL
diagnosis/review children with medium default. No nested delegation or full-history
transfer by default. Never substitute SOL for unavailable Qwen implementation.
Parent and SOL children use low for simple checks, medium normally, high only for
a named difficult causal/leakage/metric issue, then return to medium. No routine ultra.
All five native role-file defaults are medium. Qwen's adapter remains none pending
provider-specific support verification; this is not a claim about its internal reasoning.
Avoid short polling, duplicate investigations and ceremonial receipt chains.
Keep required scientific evidence, tests, independent review when actually performed,
and serial physical evaluation. Older Qwen worktree routing remains historical;
unattended goal/heartbeat use and PAYG remain prohibited.
This change does not resume a goal, alter scientific gates, or change other projects.
E26's terminal result is public0.922; E23public0.924 remains incumbent. See the
Sep8 terminal entry in `experiment_ledger.md`; older PENDING observations are historical.

Active initial-screening protocol (user-approved switch, 2026-09-05):
[`kaggle_loop_protocol_v2.md`](kaggle_loop_protocol_v2.md).
It explicitly separates retrospective local screening from pre-submission
operational confirmation. It does not waive or satisfy the legacy ST-R3 gates:
that path and its holds remain intact. SCREEN results cannot authorize submission.

Evidence-based candidate-order brief:
[`experiment_strategy_20260905.md`](experiment_strategy_20260905.md).
It records the completed E25 twin-only rejection, D1 diagnosis, and current
E26 motion-relink-off design; the frozen E17 ranker remains source-gated.
Read it with the exact candidate contracts;
it does not change their numerical gates or turn legacy eval36 into a holdout.

## Objective and current state

- Competition: `biohub-cell-tracking-during-development`
- Current reproducible public baseline: E23, public LB `0.924`
- Account rank at the fresh browser check (2026-09-08 14:43 UTC): `995 / 3,253`.
- Official public leaderboard UI: 16th score `0.952` with gold medal icon;
  17th also displays `0.952` but has a silver icon. Rounded score equality does
  not establish medal eligibility. Public test is approximately 29%, private 71%.
  Source: https://www.kaggle.com/competitions/biohub-cell-tracking-during-development/leaderboard
- Working target: public LB `>= 0.954`, retaining the prior 0.002 buffer above
  the refreshed proxy. This updates the moving planning target only; no frozen
  E26 candidate, scientific gate or numerical adoption rule changes.
- Public-LB noise estimate from hidden-199 extrapolation: SD about `0.0045`;
  differences below `0.005` are not treated as decisive by themselves.
- Score direction: higher is better.

Leaderboard values are time-sensitive. Refresh them read-only before making a
final submission decision.

## Authority boundary

- Read-only Kaggle/API inspection and artifact downloads are allowed.
- Local code, tests, documentation, and ignored experiment outputs may be
  created or changed within the project.
- Latest direct-user override (2026-09-06): prioritize improvement experiments
  and submissions, investigate causes in detail, and submit once per scientific
  hypothesis loop. Implementation repair steps are not separate scientific loops.
  A local efficacy-gate miss may still receive that loop's exploratory submission;
  keep its local REJECT label and staged-GT stop unchanged. Submission and adoption
  are separate decisions. This forward-only policy does not revive retired E25.
- Before the private target run and submission, freeze the hypothesis, exact
  candidate/config/source and asset identities. Require implementation review,
  baseline parity, valid finite graph/CSV, permitted assets/licenses, current
  competition rules/quota and a completed target run with validated output.
  Integrity, reproducibility, safety or execution errors remain no-submit.
  Record measured runtime/RAM scope and hidden-run uncertainty honestly; the
  9.6-hour/80% buffers are conservative project policy, not competition rules
  or an already-proven hidden-runtime guarantee.
- The parent makes at most one accepted submission of the frozen candidate per
  scientific loop, binds notebook version/output hash/submission ID, and follows
  it to a terminal result. An uncertain API response is not permission to submit
  again: first prove no submission was accepted before any identical-artifact
  retry. No post-LB tuning or relabeling within that loop. Keep E23 as incumbent
  when evidence is negative/inconclusive; numerical adoption gates remain fixed.
  Local runners keep submission_authorized=false; this external-action authority
  is separately recorded by the parent, not fabricated by a SCREEN verdict.
- Git commits and pushes are allowed only for complete, verified logical units
  on a non-`main`/`master` feature branch. Inspect status/diff and exclude
  secrets before either action. Never push incomplete or failing work.
- Keep `official/` read-only. It is the reference metric implementation.
- Use `src/biohub/evaluate.py`, which directly calls the official metric, for
  every adoption decision. Notebook proxy scorers are diagnostic only.

## Historical model and effort routing — superseded by the current execution override

- Latest direct-user override (2026-09-07): use exact `qwen3.8-max` and advance
  the project. The preceding September 6 conditional override selected Max if Flash
  implementation does not meet acceptance. The parent verified the Flash HOLD
  and selected Qwen Cloud Max for the current bounds repair through the existing
  `qwen_token_plan` subscription provider. This is an explicit escalation decision,
  not a provider-failure fallback or a change to other projects' model defaults.
  The repository launcher requires explicit
  `--cloud-only --cloud-model qwen3.8-max WORKTREE` for this repair; a missing
  opt-in must stop, not select local Flash. The shared queue validates its fixed
  base Codex argv and rewrites it to the explicitly selected Cloud runtime before
  execution. Separate reviewed Flash/Max selectors and catalogs leave other
  callers' Plus default and existing Flash configuration unchanged. No further shared/authentication changes
  are implied by an application implementation task.
- Subscription-only: logged-in QwenCloud usage refreshed19:22:41 JST on Sep6
  shows Pro Active, remaining95.1%, total40000, no credit packs. Official Token
  Plan docs list Flash/Max and the existing dedicated subscription endpoint. That
  balance is a historical observation, not a current remaining-credit guarantee.
  Direct supervised Flash responses were observed at16:45 and16:52 UTC; actual
  credits consumed and refreshed balance were not obtained. Stop on quota/auth/routing errors; no PAYG,
  purchases, upgrades, resets, automatic retry or model/provider substitution.
- Cloud implementation is limited to a directly requested supervised single
  task. The official Token Plan terms explicitly prohibit automated scripts and
  non-interactive batch use. Applying that restriction to automatic goal and
  heartbeat runs is the parent's reviewed interpretation, not a provider statement
  naming those features. The worker policy explicitly forbids those launches.
  They must hold instead of silently returning to Flash or SOL. AGENTS remains
  unchanged. See the 2026-09-06 14:18 UTC ledger audit for fresh source links.
- The old local patch1 was cancelled for this user-requested model switch,
  exit130 at10:18:55.483628 UTC, elapsed852.59s, no generated source/tests and
  clean worktree. Client termination and upstream drain are separate. Current
  Cloud handoff and operational evidence: `e26_unit02a_cloud_task.md` and
  `e26_worker_scope_recovery.md`; do not dispatch frozen local task documents.
- Current implementation state: `MAX_BOUNDS_INTEGRATION_ACCEPTED / V3_PHYSICAL_SHIP /
  E26_SUBMISSION_ACCEPTED_PENDING_SCORE` at2026-09-07 05:50 UTC.
  Parent/both independent physical audits passed. One acceptedsubmission56069885,
  notebookversion3/scriptVersionId347872590 at05:48:26 UTC, score/error empty on
  readback, not yet scored. Existing2h heartbeat id2 now has a narrow read-only
  follow-up exception for thisID; frequency/name/task/notification policy unchanged,
  no new runs/submissions/downloads/unattendedCloud. See currentv3 contract.
  v2 completed with exact one-field CSV repair and valid
  graph/provenance, but its report included six legacy lower-clamps in addition
  to the new upper-clamp. The parent's exact-one-total-report assumption failed.
  v2 remains NO SUBMIT. Both independent reviewers required a new preregistered
  reproducibility run, not retrospective rescue. Max authored only a new v3 token;
  source/helper/science unchanged,703 tests/Ruff and independent10 tests SHIP.
  Actualversion3 was accepted05:10:28 UTC, allsource/config checkedRUNNING.
  See `e26_bounds_v3_contract.md`; seven telemetry events/one CSV delta are fixed.
  No new LB score or adoption. A fresh direct request selected Max and project progress.
  R2 and its one feedback closed HOLD after156PASS masked a real identity-count
  validation gap. The parent redesigned a new one-function/one-test unit in this
  same active supervised turn;300seconds/single response/no feedback/retry/fallback.
  It completed in19.52seconds, exact Max/Token Plan/none/tool0. Parent focused156
  PASS, canonical related693 PASS, Ruff PASS, independent review SHIP, and pinned
  E23/E26 read-only mapping zero/exact-one-coordinate PASS. Helper/tests adopted.
  This is not resuming the blocked goal, a heartbeat or an automatic worker loop.
  Qwen notebook integration and narrow test-oracle closures then passed703 related
  tests/Ruff and independent166 tests/SHIP. Parent pushed frozen source once;
  actualversion2/kernel133333893 wasRUNNING with full33cell source/config/asset
  identity checked at04:34 UTC. Its subsequent failure is described above.
  See `e26_bounds_target_run.md` for its preserved identities and failed report gate.
- Prior Cloud outcome: `MAX_HELPER_ACCEPTANCE_HOLD`. Max responded normally
  at17:13:29.870505 UTC after164.016seconds, none/retry0/fallback0/tool0.
  Literal delivery and AST PASS; parent isolated112PASS/1FAIL and2 lint findings.
  The failed assertion is a no-op corruption oracle, but independent probes also
  prove substantive sample/projection/time/ID/aggregate/truncation validation gaps.
  No canonical adoption. The original600-second supervised unit closes without
  another launch or deadline extension; Max remains explicitly selected.
  Route and task reviews SHIP,42 operational and553 related tests PASS; those
  results verify routing, not application acceptance. Task `e26_max_bounds_task.md`.
  The earlier bounded Flash helper/test unit ended
  `FLASH_HELPER_ACCEPTANCE_HOLD`. Delivery/tool discipline succeeded; the one
  feedback correction still has97PASS/2FAIL and2 lint findings plus independent
  report-validation defects. No canonical repair/new kernel/submission exists.
  Original E26 version1 is COMPLETE but invalid, not a waiting job. E23 LB0.924
  remains incumbent. See `e26_bounds_repair_design.md` and the experiment ledger.
  Do not restart the closed Flash unit or silently substitute Plus/Flash/SOL.
- Historical Plus outcome (before the later target-run and Flash decisions):
  configuration committed7368ceb (worktreea17eb02),
  parent529 tests pass. Exact Plus Cloud source delivery succeeded, but unit02a
  review found wrong public4 profile,4 pytest failures and17 lint issues; it is
  not accepted. Qwen's two original files are preserved as ignored evidence.
  `e26_unit02a_cloud_revision_task.md` is independently reviewed and ready;
  admission at10:51:17 UTC failed before inference because the shared Cloud slot
  was busy. Nonblocking flock also found it busy at that observation; current
  slot availability was not rechecked at that historical observation. Do not steal
  locks or infer a quota problem, fall back to another model, or auto-relaunch.
- The previous automatic goal run was marked blocked after three consecutive
  confirmations of the same provider-use boundary. A fresh goal read on
  2026-09-06 at14:16 UTC returned active; the parent did not resume it.
  That began a new blocked audit, not a directly interactive Cloud request.
  At14:20 UTC, after three consecutive resumed goal turns confirmed the same
  condition, the parent marked the goal blocked again. No worker was dispatched.
  Implementation remains on HOLD and the goal is not achieved. Read-only setup
  checks are complete at their stated scope (38 synthetic regressions, three
  pinned files,40 raw/image roots and metadata); repeating them is not progress.
  Resume implementation only through provider-compliant interactive Qwen use
  or a user-selected compliant execution route. A free Cloud slot alone does
  not authorize unattended use. Preserve the reviewed correction task and all
  numerical gates; never bypass incomplete E26 implementation to claim accuracy.
- The parent owns design, priorities, result interpretation, and final adoption.
  Subagents own cause analysis, implementation/tests, and independent code review;
  the implementer never supplies the sole review of their own change.
- Unit02 history (2026-09-06 07:05 UTC): one default local-Flash worker
  ran under session `11043`, without interactive/Cloud routing. The parent
  stopped it at the 20-minute deadline and confirmed exit130; worktree clean,
  no implementation files, no retry. Saved log is under independent cause
  analysis. This is a supervisor timeout, not evidence of a provider failure.
  [Unit03 generation design](e26_generation_contract.md) passed independent
  review while waiting; unit02 acceptance still precedes its implementation.
- Historical local implementation attempt: config-only unit02a FAILED with
  `stream disconnected before completion: idle timeout waiting for SSE`.
  Session `83288`, thread `01a07590-9c7b-7753-9852-21b759c0718c`, terminated
  around 07:39:54 UTC; parent confirmed exit1 at 07:40:56 UTC. The worktree
  is clean, with no implementation files and no implementation lock.
  This is not the original unit02 supervisor stop or a quota diagnosis.
  Before the original 07:33:26 deadline, independent operational review accepted
  a one-time same-live-handle extension to 45 minutes total; the parent adopted
  it at 07:30 UTC. This changes only the parent's supervision cap, not task bytes,
  model, scientific scope or attempt count. No further extension or restart.
  The revised deadline is now historical, not an active timer. No Cloud or
  retry. Independent diagnosis found an existing 5-second comment heartbeat,
  but not proof it reached the client or reset the idle timer in this failure.
  Shared-owner isolated transport diagnosis reproduced the comment/client idle
  mismatch on Codex 0.153.4, without identifying all production failure causes.
  See the [bounded recovery design](e26_transport_recovery.md): the isolated
  repair passed 60 tests and independent review, and the shared owner deployed
  those exact source bytes with a bridge-only restart. Parent verified hashes,
  live PIDs and ready health at 08:43 UTC; owner post-deployment fake regression
  passed 33 tests. Recovery task and separate deployment audits are SHIP.
  Parent launched one local recovery at08:47 UTC; session54736 then TERMINATED
  at09:32 UTC under the2700s supervisor cap, exit130, extensions0/Cloud0.
  Final independent log audit found read/search/version checks only, no patch
  or test execution; approved worktree is clean and its lock/client PIDs are gone.
  Upstream drain was unconfirmed at09:35 UTC; at09:42:37 parent verified active0
  and disappearance of both known connections, confirming slot release.
  Do not poll session54736 as live or relaunch it. No additional retry or
  execution-policy change is authorized. See the terminal recovery record.
  The separate shell-disabled code/test-authoring design and its new inline-context
  handoff passed independent SHIP review. The isolated fake-backend tool-gating
  probe passed with independent artifact/source SHIP: apply_patch retained and
  unadvertised exec_command rejected, no real model/auth/Cloud calls. Parent's
  exact two-flag launcher delta plus two regression assertions passed all527
  launcher/unit01/public_postproc tests in14.58s, Ruff and shell syntax checks.
  A separate exact-delta/identity audit resolved inconsistent hashes in the first
  review report and returned SHIP. Parent committed only the two configuration
  files as28cd508, synced to approved worktree345dc38; no push. Worktree validation
  passed527 tests in16.45s. The parent dispatched one1200s local-only attempt at
  10:04:42.892400 UTC, session80539, deadline10:24:42.892400 UTC including queue
  time, with no extension or automatic retry. Worker thread
  01a0762d-6c53-7831-8233-5a998699a3b5 was admitted immediately on Flash. See
  [execution-scope recovery](e26_worker_scope_recovery.md). All original unit02a
  tests still require actual parent execution after complete generated-code review.
  Do not mutate
  shared services. Original statistics/gates/schema/tests remain required
  in 02b; no scientific scope reduction or submission authorization.
- Unit01 history: the 03:53 UTC direct-user supervised task used exact Plus
  through the dedicated Token Plan route, with no retries/fallback. The parent
  stopped repetitive compaction/rewrites and recovered a Qwen-authored version;
  this was not normal worker completion. Official interactive-use conditions
  do not permit extending that task to unattended Cloud goal/heartbeat work.
  See the [E26 implementation record](e26_motion_relink_off_design.md).
  Unit01 is now integrated as canonical commit `18234bd`; the parent reran
  its three contracts together with 508 existing postproc tests (511 PASS) and
  Ruff. The approved implementation worktree is clean. Unit02–04 and physical
  generation/scoring remain incomplete; the test commit is not an accuracy gain.
  SOL retains scientific design and review. The separately delegated launcher
  configuration work does not authorize SOL scientific application implementation.
  Use canonical plus the one approved `work/e26-flash` implementation worktree;
  create no additional copies. The directory name is historical, not a model ID.
  SOL must reread the complete diff and rerun relevant tests before adoption.
  The interrupted E26 attempt has no additional retry budget; a model-setting
  change alone does not restart it or authorize unattended cloud work.
- Native subagent effort is task-dependent:
  - medium: inventory, downloads, deterministic operational checks;
  - high: scientific audit, metric reasoning, candidate design, code review.
- Parallelize independent read-only, implementation, and validation work.
  Keep causal dependencies sequential and run only one heavy physical evaluation
  at a time. Do not turn optional hardening into an endless screening blocker.

## Loop order

- Binding training gate: every new or warm-start training run must pass
  [`analysis/training_loss_gate.md`](training_loss_gate.md) before official
  metric evaluation. Recovered E22/E23 inference-input bytes match the runtime
  paths/hashes and may be used for that identity check only. Primary remains
  `LEGACY_HISTORY_UNVERIFIED`; secondary is
  `LEGACY_IN_SAMPLE_MONITORING_ONLY` because its validation 40 is a 44b6-only
  subset of train 199. Neither receives retrospective training/generalization
  PASS. E20 eval-12 is `LEGACY_UPSTREAM_EXPOSURE_UNKNOWN /
  MODEL_SELECTION_CONTAMINATED_LOCAL_MONITORING`, not held-out evidence.
  Current post-processing-only work is outside this gate.

1. Establish exact parity with the submitted E23 notebook.
2. Run official local scoring and paired per-video diagnostics.
3. Change one causal factor at a time and preregister its gate.
4. Reject weak or unstable changes; record every result in the ledger.
5. Only after a local candidate passes its gate, prepare and verify one
   immutable Kaggle evaluation run. The standing user authority permits the
   private push/run and a necessary competition submission without another
   routine approval request.
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

- Current E22/E23 inference-input bytes are the recovered `edge_predictor_best.pth`
  files: primary 8,363,159 bytes / SHA256 `12f6881e...`, secondary 8,363,159
  bytes / SHA256 `9bac2fa0...`. The E22 runtime integrity receipt pins these
  exact hashes and paths. Only secondary has an exact history-backed best epoch
  (381); do not label either deployed file epoch 400. The recovered
  `checkpoint_last.pth` files are diagnostic/non-deployment assets: primary
  25,069,651 bytes / `8294faaf...` reports epoch 402 amid `400ep` artifact and
  `50ep` source-name conflicts; secondary 25,070,547 bytes / `ee6c1237...` is
  epoch 400. The primary last file is an `UNPINNED_LOCAL_OBSERVATION`.
  **Recovered inference-input bytes ↔ E22 runtime path/hash identity** alone is
  **SHIP**. Strict load, re-run output parity, checkpoint-to-raw causal proof,
  retrospective training/generalization PASS, and use of either
  `checkpoint_last` are **HOLD**.
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
