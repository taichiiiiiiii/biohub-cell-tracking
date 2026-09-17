# Flash transport integration — direct supervised request 2026-09-12

One bounded authoring task, exact qwen3.8-flash. No tools, IO, network, agents or
claims of executed tests. Return ONLY JSON with `source` and `tests` string fields,
each complete Python file text. Parent validates before adoption. Own only
src/biohub/kaggle_output_snapshot.py and tests/test_kaggle_output_snapshot.py.
No scientific code, GT, Kaggle, training or submission. No new frameworks.

Fix and integrate the supplied current module, preserving existing public API and
receipt fields. Reuse `from biohub.output_namespace import validate_namespace`.
Accepted helper signature validate_namespace(remote_paths, selected_paths, log_name)
returns None or raises generic ValueError; lists/tuples, nonempty selected subset,
safe canonical POSIX files, remote + reserved INVENTORY.json/SNAPSHOT_ERROR.json/log
+ selected .partial paths, exact and ancestor collisions, shared directories OK.
Do not edit/reimplement helper. Parent provides it when executing your tests.

Mandatory acceptance:
1. Full bounded BEFORE pagination, duplicate paths/token cycles/page and file
   limits; stable log. Derive log separately from a validated owner/slug kernel.
   Validate complete namespace before ANY HTTP or writing log. Keep source calls
   separate from HTTP. Before/after both exhaust all pages within limits.
2. All external boundaries status/page/progress/get/context enter/exit/raw.read/
   iter_content are sanitized, including external SnapshotError. No signed URL,
   raw exception message or traceback chain leakage. Fixed public error messages.
   Do not save arbitrary external exception class names or raw exception text.
   Internal validation can use fixed reasons. Log is a required source artifact;
   do not invent lossy log edits. Never print URL. Suppress error-receipt write
   failures without replacing the primary sanitized failure or claiming success.
3. One finite positive monotonic deadline from before first source.status through
   final receipt. Expired remainder RAISES, not clamps into apparent success.
   Add optional keyword-only deadline support to range_size/download preserving
   existing positional get callers. HTTP timeout positive and no more than
   remaining budget (use a total-aware timeout if necessary). Check before/after
   external calls and during streamed chunks. No hard thread/callback cancellation
   guarantee; source callbacks themselves have caller-controlled timeout. Bounded
   <=io_threads batches, deadline-aware future waits, cancel pending on failure,
   no later batches after error, no indefinite executor context shutdown wait.
4. Validate limits: bool/noninteger counts, nonfinite/invalid times/byte limits
   rejected. No overwrite of existing output tree. Fresh root only. Keep current
   strict HTTPS/Range/identity/size/SHA behavior; disallow redirects to avoid
   unvalidated target changes. Valid 416 bytes */0 is empty. Wrong 206 range,
   missing/truncated body, overlong download, nonidentity encoding must fail.
5. AFTER compares entire path set and stable log; rotated URLs allowed. Verify
   returned namespace and required subset. Recheck saved downloaded bytes/SHA and
   log before COMPLETE. explicit_version_fetch remains false. Receipt file list
   uses HTTP actual lengths, NOT manifest estimates. Failed operation must not
   leave a COMPLETE inventory. Preserve incomplete partial evidence.
6. Write focused pytest fake-transport tests covering successful two pages BEFORE
   and two AFTER with rotated URLs (assert exact calls), changed second page with
   identical first page, duplicates/cycles/missing selected/path collisions before
   HTTP (assert zero HTTP calls), status/page/get/context/stream/progress external
   sentinel failures INCLUDING SnapshotError, actual fake call counts so tests
   cannot pass on an unrelated earlier failure. Deadline exhaustion/timeout bounds,
   chunk truncation/overflow and wrong Range, input limits, fresh output, SHA/log
   tamper before receipt. No wallclock sleeps, no real network, no vacuous tests.

Keep implementation concise and Ruff-compatible (line length120). This is a
transport repair, not a prediction experiment; tests are not CV improvement.
Parent will run focused tests then one eligible Max evaluation before adoption.

## 2026-09-12 supervised resume1 — CLOSED / REJECT

The first invocation stopped before inference on the old busy single Cloud slot.
After the shared queue changed to 8 slots, a new explicit one-shot resume admitted
Flash thread01a09551-8d2a-7ab3-8ebe-c900286245e8, cloud-only/retry0. Worker exit0
does not imply acceptance. Exact delivered source/tests are isolated under
outputs/local/e23_transport_flash_20260912_resume1/, never applied to src/tests.

Fake tests: 4 passed / 19 failed; Ruff15 findings. The initial parent harness
needed PYTHONPATH=src before importing the candidate; the above counts are from
the corrected harness, with outbound socket connects disabled. No model retry.

Confirmed defects:
- AFTER still reads only source.page(None), requiring its token empty, so the
  required successful two-page example fails. The named second-page-change test
  mutates BEFORE instead and cannot prove the intended AFTER protection.
- _sanitized/HTTP/progress handlers preserve external SnapshotError messages.
  Parent's synthetic status exception marker was returned intact; confidentiality
  requirement is therefore not met even though normal exceptions are sanitized.
- _http_timeout floors both components to .001s, exceeding a .0001s remaining
  budget. Limits(seconds=inf) is accepted. Both reproduced by pure parent probes.
- Executor context manager still waits on running futures on exit. Range GET
  does not disable redirects. The required bounded-failure semantics are absent.
- log filename changed from slug.log to owner-slug.log, incompatible with existing
  collection audit. Tests endorse the changed name instead of preserving the API.
- Test fixtures have missing time import, wrong class-method monkeypatches,
  early failures masking namespace/budget checks, nonexistent error receipts and
  a contradictory HTTP-message assertion. Do not weaken production gates to fit.

Next supervised correction must be smaller: first complete reusable BEFORE/AFTER
listing and trusted-vs-external error boundaries with exact fake call assertions,
then deadline/transfer integration. Reuse accepted namespace. Do not resend this
closed whole-module prompt or apply a SOL-written application fix. No Max review
was spent on the demonstrably failing draft; this is one Flash acceptance failure,
not two (the earlier busy admission did not invoke a model).
