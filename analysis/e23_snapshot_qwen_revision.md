# D3 transport revision — rejected draft follow-up

> 履歴・非運用・現行起動に使用禁止。以下のMax実装命令・旧タスクは当時の記録です。
> 診断根拠は保持しますが、そのままworker入力にしないでください。
> 現行方針は [AGENTS.md](../AGENTS.md)、[MAX評価手順](../.codex/runners/biohub_max_implementer.instructions.md)。

The first authoring unit is CLOSED/REJECTED: 13 passed, 8 failed; Ruff 4 errors.
Independent SOL review also rejects it. Canonical src is unchanged. This is a new
supervised, review-guided correction unit, not a provider retry or fallback.
Keep the original contract in e23_snapshot_qwen_task.md. One response, 600 seconds.
No tools, network, filesystem, agents, or claims of having executed tests.
Return TWO complete Python fenced blocks: module and tests. No commentary.

Correct these verified defects and their test masking:

- Never check derived log against itself. Validate remote paths plus internal
  reserved paths plus selected .partial paths as a complete file namespace, with
  exact and ancestor conflicts. Do this before HTTP. Include a and a/b, selected
  a and remote a.partial, log ancestors, and reserved ancestors in tests.
- Factor full bounded pagination and use it both before and after transfer. Test
  genuine two-page BEFORE and two-page AFTER sequences with identical first-page
  membership, changed second-page membership, and rotated URLs. Assert page calls.
- Remaining budget must RAISE when <= 0, never clamp to zero then test >= 0.
  Socket timeout must not exceed remaining budget. Check external calls and chunks.
  Prefer bounded batches with at most io_threads futures, deadline-aware waits,
  cancellation on failure, and no submission of later batches after failure.
  Do not claim hard thread cancellation. Running calls remain socket bounded.
- Sanitize exceptions at EACH external boundary (status/page/get/enter/exit/
  iter_content/progress) even when exception type is SnapshotError. Keep internal
  validation messages fixed, and suppress raw external exception chaining.
  Ensure tests reach the intended external failure (assert fake call count), not
  pass merely because early unrelated validation failed. Cover status, page,
  get, stream, context manager, progress and SnapshotError variants with fake URLs.
- Fix fake URL matching: a.bin file must map to URL ending a.bin consistently.
- Remove unused imports, line length <=120, preserve receipt shape and API.

Keep all unrelated science/runtime files untouched. Parent validates returned code
in isolation first; independent reviewer must accept before integration.

## Closed result and next bounded unit (2026-09-08)

Revision REJECTED: 15 passed / 14 failed, Ruff 1 error. No canonical adoption.
The next directly supervised authoring request must NOT resend the whole module.
Implement a pure namespace validator and its tests only, then integrate in a later
unit. Do not start this Qwen unit from an automatic goal/heartbeat continuation.

Proposed signature: validate_namespace(remote_paths, selected_paths, log_name).
It receives complete pre-download remote membership, NOT just selected paths.
Selected paths must be nonempty, unique, safe, and a subset of remote paths.
Remote paths must be unique and safe. Validate log_name separately as one safe file.
Internal reserved files are INVENTORY.json and SNAPSHOT_ERROR.json plus log_name.
Temporary files are selected_path + '.partial' ONLY for selected paths.
Check disjoint exact membership BEFORE taking set unions, then check file/ancestor
conflicts across all these categories. Do not insert log_name into remote_paths:
that caused both rejected drafts to reject every valid snapshot.
Errors must be fixed text without echoing untrusted paths. No IO, HTTP, timing,
source.status, executor, global state, or receipt code belongs in this unit.

Acceptance matrix fixed before implementation:

| Inputs | Required result |
| --- | --- |
| remote [a,b], selected [a], log slug.log | accept |
| remote [d/a,d/b], selected [d/a,d/b] | accept (shared directory is not a file collision) |
| remote includes each reserved name or its descendant | reject |
| remote [a,a/b], selected [a/b] | reject even though a is not selected |
| remote [a,a.partial], selected [a] | reject exact temporary collision |
| remote [a,a.partial/b], selected [a] | reject temporary ancestor collision |
| remote [a,a.partial], selected [a.partial] | accept; a is not downloaded |
| duplicate remote or selected entries; selected missing remotely | reject |
| absolute, dot-normalized, traversal, backslash, NUL paths | reject |

Run pure tests before any integration. Subsequent units separately handle external
exception sanitization/deadlines, then pagination/transfer integration. Transport
acceptance still requires all original gates; passing this pure unit alone does
not authorize use on real signed URLs or claim completion of output retrieval.

## Independent design review — 2026-09-09

SOL/medium reviewed the pure-unit contract against the existing download suffix
and snapshot call site. No implementation was accepted or remote retrieval run.
The next Qwen authoring unit must also satisfy these clarifications:

- Accept only finite list/tuple inputs for remote_paths and selected_paths;
  reject scalar str/bytes, None, generators, sets and non-string elements with
  fixed errors. Keep duplicates until validation. The integration caller remains
  responsible for the existing configurable file/page/byte limits.
- Collision categories are remote files, internal reserved files (including the
  independently validated log), and selected temporary files. Selected final
  files are already a subset of remote: do not compare them as a disjoint category.
- Check internal reserved names against each other too. Test log=INVENTORY.json,
  a remote ancestor of a nested log, and a remote descendant of the log.
- Reject lexical noncanonical paths including '.', './a', 'a/.', 'a//b' and a
  trailing slash. Do not invent Unicode normalization or case folding.
- Avoid all-pairs path comparisons. Use exact membership plus ancestor checks
  bounded by total path depth, or an equivalently bounded implementation. Include
  12,000 remote entries in a functional fixture, without a flaky wall-time gate.
  Plain lexicographic adjacent-only checking is insufficient unless it handles
  intervening siblings such as ['a', 'a-b', 'a/b'].
- Preserve acceptance of remote=['a','a.partial'], selected=['a.partial']; its
  temporary file is 'a.partial.partial', not 'a.partial'.

Next unit remains pure validation and fake-input tests only. Deadline, external
exception sanitization and full before/after pagination require later integration
and independent acceptance; this review does not certify the existing transport.

## Supervised pure-unit result — 2026-09-11

Direct user continuation resumed one authoring-only qwen3.8-max request through
the canonical read-only subscription-cloud-only queue (automatic_retry=0).
Worker thread 01a08eb4-6c9c-7e71-b560-04adcbc44ba5 exited 0, but its code is REJECTED.
The new bounded contract is `e23_namespace_qwen_task.md`. No runtime adoption.

The delivered ancestor check confuses component depth with character offset:
`prefix_len = ancestor_depth + 1` and `candidate[:prefix_len]` compare `a/`
against stored `a`. It also uses character positions incorrectly for longer names.
The exact returned function is preserved in ignored local evidence at
`outputs/local/e23_namespace_review_20260911/rejected_ancestor.py`.
Five direct counterexamples all incorrectly accepted: a/a/b, intervening a-b,
logs/logs/run.log, INVENTORY.json/INVENTORY.json/sub, a.partial/a.partial/b.
These are focused function checks, not a full test-suite result for the draft.
The draft's no-echo test also supplies a valid path and catches exceptions only,
so it can pass without exercising error handling.
Independent SOL/medium reviewer `next_loop_review` also returned REJECT after
inspecting the ancestor logic; this was a separate static review, not a second
execution of the parent's five counterexamples.

Next correction must enumerate actual slash-delimited proper prefixes and test
membership in the complete file set. Keep the existing acceptance contract;
require explicit exception assertions for negative tests. Do not silently fix
the rejected implementation with SOL, integrate it, or use it on remote output.
Existing stage/readout regression: 40 passed (3.03s); Ruff for both modules passed.
No Kaggle operation, training, new submission, commit or push in this unit.
