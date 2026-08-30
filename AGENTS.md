# Biohub Cell Tracking During Development

## Mission

Improve the 3D+t microscopy cell-detection and lineage-tracking pipeline for `taichiiiiiiii/biohub-cell-tracking`. Work in Japanese unless the user asks otherwise. The target repository's active development branch is `develop`.

## Sources of truth

Use evidence in this order: (1) `official/` metric implementation and tests, (2) the repository code and focused tests, (3) `CLAUDE.md`, `CHECKLIST.md`, `analysis/experiment_ledger.md`, and `docs/LESSONS.md`, (4) Kaggle scores and reproducible public notebooks, and (5) external papers. State dataset, annotation, metric, and license differences when transferring external methods.

## Non-negotiable constraints

- The score is adjusted edge Jaccard plus 0.1 times division Jaccard. Report both components and per-dataset results.
- Ground truth is sparse; unmatched detections are not equivalent to fully supervised false positives. Never infer full annotation coverage.
- Public test contains four dummy datasets and is in-sample. Never call its score generalization performance.
- Keep `official/` read-only. Adapt through `src/biohub/`.
- Edges must connect t to t+1. Gap handling must create intermediate nodes.
- Local RAM and disk are constrained. Training and full inference run on Kaggle; local work is limited to small data, tests, and analysis.
- Never push a Kaggle kernel, submit, join a team, spend GPU quota, publish, merge, release, or tag without explicit user approval.

## Workflow

Start from an Issue and a falsifiable hypothesis. Inspect the real evaluation path before coding. Establish the measurement unit and noise floor before claiming improvement. Use video-level splits stratified by `44b6` and `6bba`; keep related frames from one video in one fold. Implement one isolated lever, add focused tests, run repository checks, and record negative as well as positive results in the experiment ledger. Estimate hidden-test runtime for roughly 200 videos and retain a feasible fallback path.

## Delegation

Use the minimum useful specialists. Read-heavy specification, literature, and review tasks may run independently. Avoid parallel edits to metric conversion, graph construction, or the same notebook. The main agent owns hypotheses, integration, adoption decisions, and all external actions.

- Run the parent agent with `gpt-5.6-sol` at `ultra` reasoning effort. Choose
  native subagent effort by task: `medium` for bounded specification and
  submission checks, and `high` for experiment design, tracking research, and
  scientific review. The default fallback is `medium`.
- Delegate code and test implementation through the external worker:
  `printf '%s\n' "$TASK" | .codex/bin/qwen-implement /absolute/linked/worktree`.
  Do not use native `spawn_agent` for Qwen implementation. Codex 0.151.0 does
  not propagate a custom `model_provider` into native child roles.
- The external worker uses `qwen3.7-max` with machine-local
  `qwen_token_plan`. Use `medium` reasoning for bounded implementation phases;
  raise effort only when the task's ambiguity or review risk justifies it.
  Never copy provider credentials into this repository.
- Give each worker a clean linked worktree on a non-protected branch. At most two
  Qwen workers may run concurrently, and their files must not overlap.
- Parallelize independent read-only work, but do not let multiple agents edit the same files or run heavy experiments concurrently.
- Before adopting Qwen-authored changes, the SOL parent agent must reread the complete diff and rerun the relevant pytest and ruff checks itself.
