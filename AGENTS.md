# Biohub Cell Tracking

Work in Japanese in the canonical checkout on its current feature branch, never develop/main/master.

## Boundaries

- Preserve user WIP, frozen evaluation inputs and runtime. No new checkouts/worktrees, destructive cleanup, stash/reset, global edits, or plugin/hook removal. Heavy physical evaluation is serial.
- Keep official/ read-only; adapt via src/biohub/. Never expose credentials, tokens or signed URLs, retrieve Keychain secrets, or delete data.
- During the macOS screen lock or a Codex implementation lock, the parent may use the existing authenticated Kaggle CLI/API for read-only competition files, submissions/status, scores, leaderboard, quota/deadline and kernel-status inspection without browser UI. This does not authorize downloads, comments, joins, settings changes or credential refresh. On authentication failure, stop without retrying and request user re-authentication while the screen is unlocked; never read, print or transmit credential-file contents.
- Kaggle execution and submission, including the GPU spending they incur, no longer require explicit user approval. Team joining, publication, merge, release and tags still need explicit user approval. Subagents must not submit, push, create PRs or send external data. Git commit/push obey the user's completion, verification and branch gates; never infer permission from a schedule.
- Local work is small-data analysis and tests; training/full inference belongs on Kaggle only when authorized. Do not edit frozen source or commit/push while a physical run is generating or remains unscored. **User decision 2026-09-23, in force until the 2026-09-29 deadline: this unscored-run restriction is relaxed for the E-series experiment flow.** Up to two submissions may be in flight at once, and the notebook may be edited, committed and pushed while earlier runs remain unscored, because each Kaggle kernel version pins the exact configuration that was submitted, so reproducibility is carried by the version rather than by serialisation. Every submission must still name its kernel version and its experiment id. Outside the E-series flow the original restriction stands.

## Commit and push

Only the parent agent may commit or push; Codex and other subagents never do so. **Standing authorization, user decision 2026-09-23, in force until the 2026-09-29 deadline: notebook-only commits and pushes belonging to the E-series experiment flow are pre-authorized and need no per-action confirmation, provided the verification for that change has passed and only the named notebook path is staged.** Every other commit or push still requires explicit user authorization for that action. A commit must be one complete logical unit whose acceptance criteria are met, with relevant checks passing (or an explicit recorded reason they could not run), the final diff reviewed, and no credentials, generated competition data, or unrelated changes staged. Stage only the named paths and use an accurate conventional commit message. Push only at a genuine milestone from a non-protected task branch after a successful fetch proves the remote branch is not ahead or diverged. Never push directly to `main`, `master`, or `develop`, never force-push, and never push while an authorized physical run remains unscored (except under the E-series relaxation recorded in Boundaries). If any condition is uncertain, preserve the work locally and report the blocker.

Keep commits small and independently reviewable or revertible. Split unrelated behavior, tests, configuration, experiment records, and separate hypotheses when each is a valid standalone unit; do not bundle separate completed tasks into one commit. Do not split an implementation from the directly required test or frozen contract update when that would leave an invalid intermediate commit.

Use an issue-first workflow for every repository-scoped file change, experiment, durable research result, or external operation. Before work, the parent creates a GitHub Issue containing the goal, exact scope, acceptance checks, and competition/safety boundaries; Codex and other subagents only report to the parent and never create, comment on, or close Issues. Use a non-protected branch named `codex/issue-<number>-<slug>` and reference the Issue in commits. **Recorded exception, user decision 2026-09-23: the E-series work (E48 onward) is tracked in Issue #20 but continues on `codex/issue-18-goal-silver-medal`, because a concurrent work stream holds a large uncommitted WIP on that branch and cutting a new branch now would entangle it. Each E-series commit names its Issue in the message instead.** After verification, the parent must push the branch, then add an Issue result comment with outcome, changed paths, checks, commit and branch, plus remaining risks. Close the Issue only after that push succeeds and acceptance criteria are met. If work, scoring, verification, commit, or push is incomplete, record the blocker and keep the Issue open. Emergency data-protection actions and simple conversational or read-only status answers are exempt; any follow-up repository work is not.

## Read only what the task needs

Evidence priority: official metric/tests, current code/tests, relevant project records, reproducible Kaggle evidence, then external papers. No blanket document preload.
- Status: latest relevant section of analysis/experiment_ledger.md, not its entire history.
- Scientific design/evaluation: relevant frozen experiment contract and analysis/gold_loop_protocol.md; inspect official metric path when the claim depends on it.
- Metric/format diagnosis: official/metrics.md and src/biohub/evaluate.py plus affected tests.
- Implementation: assigned task, affected source/tests; docs/LESSONS.md or CHECKLIST.md only for a relevant known failure.
- Provider routing: investigation, implementation and review run through the Codex plugin (`codex:rescue`), invoked directly from Claude Code. CLAUDE.md's dated setup/role history is not current status or authorization.
- AGENTS.md is the current authority. Historical/non-operational prompts (including old analysis task briefs, `.claude` roles, and the retired Qwen/Luna-Terra-Sol routing under `.codex/`) must never be piped into a current launcher. Prepare a fresh bounded brief under current policy.

## Scientific work

Start scientific changes from an Issue and falsifiable hypothesis, with measurement unit, noise floor, control and acceptance gate fixed before results. Follow hypothesis → diagnosis → independent review → isolated change → focused tests → serial physical evaluation → failure/result record → next design.
- Score = adjusted edge Jaccard + 0.1 × division Jaccard; report both and per-dataset results. Sparse unmatched detections are not blanket false positives.
- Public4 is dummy in-sample data, never generalization evidence. Split whole videos, stratify 44b6/6bba, preserve unexposed GT boundaries.
- Edges are t→t+1; gaps require intermediate nodes. Estimate hidden-scale runtime (~200 videos) and retain an already-required feasible fallback. State data, annotation, metric and license differences for transferred methods.
- Record positive and negative results once in the ledger, with required reproducibility hashes. Configuration changes, test success and worker exit0 are not scientific improvement or goal resumption.

## Delegation and implementation

- Claude owns design and adoption decisions. Investigation, implementation and review run on the Codex side via the Codex plugin (`codex:rescue`), invoked directly from Claude Code — not as native Claude subagents and not through Qwen. Do not use xhigh, max or ultra effort routinely.
- Give Codex only what the task needs: goal, acceptance criteria, exact file/task scope, and the minimal relevant diff, code or test/experiment results — not a whole repository, long history or large logs.
- Codex reports findings, an implementation, or a review verdict back to Claude. Claude reviews the delivery and alone decides adoption, experiment continuation and submission; Codex never commits, pushes or submits.
- Delegate one bounded, independent task at a time with a clear brief (goal, exact file ownership, constraints, acceptance criteria, output limit); no nested delegation or ceremonial review chains, and no duplicate investigations.
- While Codex runs, do useful separate work. Otherwise wait a reasonable multiple of the estimated remaining time, or 120 seconds if unknown, before checking back; no short polling or blind restarts on timeout.
- Do not add duplicate tests or reviews to small reversible changes, or extra experiments/abstractions when the evidence already in hand is sufficient.

## Smallest complete change

Reuse existing structures, dependencies and abstractions. No speculative frameworks, generic layers, new documents, compatibility shims or fallback routes without a concrete current requirement. Fix only the requested scope; use relevant existing tests, not repeated full-suite runs or reviews. Once explicit acceptance is met, stop. Re-read evidence only after changes or a concrete contradiction.