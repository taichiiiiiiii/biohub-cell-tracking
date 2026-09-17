# Supervised Flash namespace repair — 2026-09-12

Authoring-only, exact qwen3.8-flash. The parent directly requested this task.
No tools, filesystem, network, agents, or claims of executed tests. Return a JSON
object with exactly two string fields: `source` and `tests`, containing complete
Python file text. No fences or commentary. Parent applies only after review.

Ownership: new `src/biohub/output_namespace.py` and
`tests/test_output_namespace.py`. No other files. This is an isolated pure helper;
do not integrate into transport or change scientific/runtime code yet.

Implement `validate_namespace(remote_paths, selected_paths, log_name) -> None`.
Raise ValueError with a fixed generic message on invalid input, without echoing
input or exception chains. No IO/global mutation. Use standard library only.

- remote_paths and selected_paths must each be a finite list or tuple of strings.
  Reject scalars, generators, sets, nonstrings and duplicate entries. Selected
  must be nonempty and a subset of remote; preserve inputs unchanged.
- A file path must be nonempty, relative, lexically canonical POSIX: no absolute,
  backslash, NUL, empty component, `.` or `..` component, or trailing slash.
  Do not invent case-folding or Unicode normalization.
- Files occupy three disjoint categories: remote final paths; reserved local files
  `INVENTORY.json`, `SNAPSHOT_ERROR.json`, log_name; and temporary files formed by
  appending `.partial` to EACH selected path. Selected finals already belong to
  remote; never treat them as a fourth disjoint category. Log is a separate local
  file, NOT inserted into remote. Validate log path and internal duplicates too.
- Reject exact or proper-ancestor collisions across the complete file namespace
  before any caller HTTP begins, including remote files not selected. Shared
  directories are allowed. Enumerate actual slash-delimited proper prefixes and
  check membership; never confuse component depth with character offsets or use
  adjacent lexicographic comparisons. Avoid quadratic all-pairs checks.

Acceptance (pytest imports biohub.output_namespace):
- accept remote a,b selected a log slug.log; nested d/a,d/b both selected;
  remote a,a.partial selected a.partial (its temp is a.partial.partial).
- reject a,a/b; a,a-b,a/b even when a is unselected; selected a with remote
  a.partial or a.partial/b; remote logs with log logs/run.log; remote descendant
  of log; each reserved name and descendant; log equal to reserved name.
- reject duplicate/missing selections, all invalid types and noncanonical paths.
- test explicit pytest.raises for negative inputs and generic no-echo message
  using invalid input that actually fails. Never a vacuous try/except assertion.
- fixture with 12,000 safe remote files must pass; no wall-clock assertion.
- assert input immutability. Keep source and tests focused, Ruff line limit120.

Passing this unit does not accept transport: deadlines, sanitized external errors,
complete BEFORE/AFTER pagination and integration remain separate required work.
No competition GT, learning, Kaggle operations or submission is authorized here.

## Closed result and next implementation boundary

The above authoring unit is CLOSED/ACCEPTED (62 tests and Ruff passed; independent
SOL static review found no blocking correctness defect). Do not dispatch it again.
Source is now `biohub.output_namespace`; reuse it, never reimplement its logic.
Its strict linear-time prose is not a measured guarantee for arbitrarily deep
paths; the reviewer noted a redundant prefix rescan. No performance rewrite is
required for the stated contract.

The next directly supervised Flash unit owns only
`src/biohub/kaggle_output_snapshot.py` and its focused fake-transport tests.
Before dispatch, parent supplies the current module and accepted helper signature
as bounded context, not old rejected tasks or worker logs. Preserve existing API
and receipt fields; no API/GT/download operation during implementation acceptance.

Acceptance must cover the entire transport change, not just importing the helper:

1. Collect all BEFORE pages with page/file/deadline limits, duplicate/token-cycle
   rejection and stable log; validate complete namespace before any HTTP or log
   write. Derive log separately. Reject before remote access on invalid namespace.
2. Sanitize every external boundary, including status/page/progress and response
   enter/exit/read/iteration, even if an external callback raises SnapshotError.
   Fixed error messages, no raw exception chains, signed URLs or input echoes.
3. Propagate one monotonic deadline through HTTP and chunk reads. Expired budget
   raises, never clamps into success; socket waits remain bounded by remaining
   budget. Stop scheduling new batches on failure and cancel unstarted futures.
   Never claim hard cancellation of a running thread or an arbitrary callback.
4. Exhaust all AFTER pages, compare full path membership and log with BEFORE,
   permit rotated signed URLs, and reject changed later-page membership even when
   the first page matches. Keep explicit_version_fetch=false.
5. Recheck downloaded file bytes/SHA and saved log before issuing COMPLETE;
   failures leave only an honest INCOMPLETE receipt, never successful inventory.
6. Fake tests must assert the intended boundary was reached: two real pages in
   BOTH passes, actual negative exception assertions, callback call counts,
   deadline exhaustion, secret sentinels and partial download. No real network.

This unit is eligible for one Max evaluation as a reproducibility-sensitive
transport change after focused tests pass. Parent decides adoption. Its success
would only permit the existing full collection audit, not establish CV improvement.
Automatic goal continuation does not authorize launching either Qwen role.
