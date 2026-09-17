# Direct supervised Flash correction — bounded listing 2026-09-12

Author exact qwen3.8-flash, no tools/IO/network/agents/test execution. Return only
JSON with two strings: `addition` (Python functions to append to the existing
module) and `tests` (complete pytest file). Keep short. Do not repeat full module.
Own additions to src/biohub/kaggle_output_snapshot.py and new
tests/test_kaggle_output_listing.py. Do not modify snapshot/range_size/download yet;
they remain unaccepted until later integration. This prerequisite is not the
whole transport fix. Existing namespace helper is already accepted, do not copy it.

Existing module imports time, re, json, PurePosixPath, dataclass and urlsplit.
Existing SnapshotError(ValueError), require(value,message) raises SnapshotError,
safe_path(name) validates nonempty lexical canonical relative POSIX file path,
rejects backslash/NUL/.., returns PurePosixPath. Existing frozen Limits has integer
files=12000,pages=100,file_bytes=67108864,seconds=900 etc. Do not edit these.

Add only these helpers (private internal utilities permitted if necessary):

`call_external(callback, *args, **kwargs)` invokes once, returns result. On ANY
Exception, including SnapshotError containing arbitrary text, raise NEW
SnapshotError('external source call failed') from None. Never preserve external
exception messages/types as output. Do not catch BaseException (KeyboardInterrupt
and SystemExit must propagate). Do not print/log original errors. Treat callback
return validation separately with fixed internal messages. This will be reused
for source.status/page/progress boundaries during later integration.

`list_all_pages(source, limits, deadline, *, clock=time.monotonic)` returns
(files, log, pages). files maps remote paths to https URL strings for in-memory
transport only. No files, HTTP, status calls or progress callbacks here.
- Deadline is an absolute finite numeric clock value (not bool). Require remaining
  >0 before and after EACH source.page call, before return. No timeout floor or
  fake claim that arbitrary source callbacks can be interrupted. Use clock seam
  for deterministic tests; validate finite now values. No sleep.
- pages/files/file_bytes must be positive integers, not bool. Validate inputs
  before calling source. Enforce page and aggregate file limits, max log bytes.
- Call source.page(None), then each next token until None/empty token. Tokens
  must be str or None; reject cycles. Never stop after just the first page.
- Validate exact builtin dict page with files(list), log(str or None),
  next_page_token(str or None). All three keys required (extras permitted).
  Each file item dict contains path/url strings (extras permitted). Reject duplicate
  paths within/across pages. safe_path rejects lexical hazards; explicitly reject
  '.' too. URL must be HTTPS with nonempty host; reject userinfo. Do not echo it.
- None/empty page log means absent (preserve legacy behavior); nonempty logs must
  agree; require a nonempty log by completion. Bound UTF8 bytes. Fixed messages
  for invalid returns including invalid URL parsing, never raw ValueError text.
- Do not mutate returned page objects, input limits or source page data.

Tests must include two BEFORE and two AFTER pages via the SAME helper, then
compare sets/logs in the test caller. Changing only AFTER's second-page path must
show unequal sets; changing only URL strings must keep path sets/log equal. Assert
all four exact page call tokens [None,'n',None,'n'], not a misleading test that
changes BEFORE or fails on missing required selection before AFTER.
Test duplicate within/across pages, token cycles, page/file/log limits, missing
keys/bad types, unsafe paths, malformed URL, inconsistent/missing log, empty log
on intermediate pages. Use explicit pytest.raises(SnapshotError), no broad
Exception assertions. Negative fixtures must reach intended validation and assert
call counts. Failure text/traceback must not include a synthetic secret marker
when an external SnapshotError/RuntimeError is raised. Check callback once and
KeyboardInterrupt propagation. Test expired/NaN/inf/bool deadline, expiry inside
callback using fake clock, no subsequent call; positive and empty final page,
input immutability. Standard library+pytest only; Ruff max line120.

No new model/framework, no code outside this prerequisite. Parent checks output,
then later integrates one complete transport path with original slug.log and all
namespace/deadline/download/receipt gates retained.

## Result — CLOSED / REJECT

Flash thread01a09559-1025-77d2-92c2-552fe2051995 completed normally. The 24 supplied
tests pass (0.05s), but parent probes prove page limit1 allows 2 source.page calls,
and deadline10 / clock [0,0,11] permits the second call before detecting expiry.
The loop checks budgets only after calls, violating this preregistered contract.
No canonical additions applied. Isolated candidate retains original module plus
exact Flash addition in outputs/local/e23_listing_flash_20260912/candidate.py.
Ruff's single B008 finding belongs to the unchanged baseline, not this addition.

One Max evaluation (thread01a0955b-bd72-72d0-99b0-637771d3576e) also rejects the
ordering defects. Parent rejects its incorrect advice to preserve external
SnapshotError: this violates mandatory sanitization. Its claims of absent
duplicate/empty-token tests are unsupported: those tests exist in the full delivery
but were not included in the bounded packet. The log must remain identical when
present; do not loosen the frozen terminal-log contract.
The URL guard exists in the delivered source. An explicit summary replaced its
single line in the evaluation packet because the scanner misread the password
attribute followed by ':' as a credential assignment. This was a local input
rejection before queue/model invocation, not a failed provider request. Max's
inability to independently verify that omitted line is a review scope limitation.

Next bounded correction: put remaining-time and `pages >= pages_limit` checks
before each page call, keep the after-call and final checks, and require exact
call counts in the page-limit and between-page expiry tests. Preserve generic
external SnapshotError sanitization, full two-pass listing behavior and stable
logs. Also replace the noncallable branch's convoluted `require(...)` expression
with a fixed error and reject numeric conversion overflow with SnapshotError.
Do not resend this closed task or edit application code with SOL. HTTP/deadline/
namespace/receipt integration remains a separate unaccepted downstream unit.
