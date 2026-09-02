# Two-hour repository maintenance

Work exclusively in this existing checkout:

`/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking`

Do not create, add, move, or use a Git worktree or another project copy. Do not
modify `AGENTS.md`, `CLAUDE.md`, other agent-instruction files, or anything under
`official/`. Do not call Kaggle, download competition data, start training or
inference, submit, merge, tag, or release. This run is repository maintenance,
not an experiment.

Perform the following maintenance loop:

1. Inspect `git status --short --branch`, the complete unstaged and staged
   diffs, recent commits, and the current branch/upstream relationship.
2. Compare the actual implementation and current work state with the existing
   documentation.
3. Update only the Markdown files that genuinely need progress, TODO, plan,
   decision, specification, or change-history corrections.
4. Remove or reconcile stale, duplicated, or implementation-contradicting
   documentation. Preserve useful historical evidence and negative results.
5. Record newly discovered issues and unfinished work in the most appropriate
   existing document. Create a new Markdown file only when no existing document
   has the right scope.
6. Record material design decisions and specification changes with evidence.
7. Update `README.md` only when user-facing usage or an external interface has
   changed.
8. Leave agent-instruction files unchanged.

Preserve all pre-existing user changes. Never overwrite, discard, reset, clean,
stash, or silently absorb unrelated work. If dirty files cannot be safely
attributed to one complete logical unit, inspect and report them but do not
commit or push them.

After any edit, reread the full diff. Run the smallest relevant tests, lint,
format check, type check, documentation check, or other repository validation
needed to prove the logical unit is complete. Do not weaken checks or modify
tests merely to make a failure green. Treat unrelated pre-existing failures as
evidence to report, not as permission to commit incomplete work.

Commit only when all of these are true:

- the change is one meaningful, complete logical unit;
- all relevant validation has succeeded;
- staged and unstaged diffs and `git status` were reviewed;
- no credential, token, secret, generated bulk data, cache, or unnecessary file
  is included;
- the commit message accurately describes the completed unit.

Never commit temporary debugging, partial work, or a validation failure.

Push only at a genuine work milestone, never merely because this timer fired.
Before pushing, require every condition below:

- at least one meaningful commit exists to push;
- the current logical unit is complete and validated;
- `git status` and all diffs are reviewed and clean after the commit;
- no secrets or unnecessary files are present;
- the current branch is neither `main` nor `master`;
- the branch has an explicit upstream on `origin`;
- a fresh fetch succeeds and proves the remote is not ahead or divergent;
- the push is a normal non-force push to the same current branch.

If any condition is missing, do not push. Never push directly to `main` or
`master`, never force-push, and never change remote configuration.

Finish with a concise maintenance receipt containing: inspected state,
documentation changes, validation commands/results, commit SHA if any, push
result if any, and unresolved holds. A clean no-change run is valid and must not
manufacture edits.
