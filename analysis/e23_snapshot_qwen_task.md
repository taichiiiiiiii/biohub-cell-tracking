# D3 output transport — bounded Qwen implementation

> 履歴・非運用・現行起動に使用禁止。この旧タスクは保存用です。
> 現行方針は [AGENTS.md](../AGENTS.md)、MAX評価入口は
> [評価手順](../.codex/runners/biohub_max_implementer.instructions.md) を参照。
> 以下のモデル指定・命令・実行例は当時の履歴であり、現在のworkerへ渡してはいけません。

Directly requested, parent-supervised qwen3.8-max subscription-only authoring task.
No tools, filesystem access, shell, network, agents, retries or provider fallback.
Use only the source supplied below. Do not claim tests were executed. Parent applies
and verifies the returned code. One response, 600-second supervision limit.

Return exactly two fenced Python blocks, preceded by their respective file paths:
src/biohub/kaggle_output_snapshot.py and tests/test_kaggle_output_snapshot.py.
The first is the complete corrected module, the second focused pytest tests.
No other files or new framework. Python 3.12, requests, pytest; Ruff E/W/F/I/UP/B,
line length120. Tests use fakes only, no network, GPU, GT, real credentials or sleeps.

Preserve the API and output inventory contract, limits and diagnostic-only scope.
Implement only these changes, based on independent review:

1. Replace limits=Limits() default with None and initialize internally. Validate
   positive finite time and positive integer count/byte/thread limits (reject bool).
2. Bounded full pagination both before and after downloads. Compare exact full path
   sets and log, allowing signed URLs to rotate. Validate duplicate paths, token cycles,
   file/page bounds on both passes. Recheck COMPLETE after final listing.
3. Validate owner/slug shape. Before writing log or downloading, reject remote paths
   colliding with INVENTORY.json, SNAPSHOT_ERROR.json, derived kernel log, or selected
   temporary .partial paths, including file/ancestor collisions. Fresh output root only.
4. Cooperative absolute deadline: check before/after HTTP and between streamed chunks;
   cap socket connect/read timeout to remaining budget. Keep at most4 HTTP threads.
   Do not claim Python threads can be forcibly killed or this is a hard wall-time cap.
   Cancel pending work on failure and leave partial files as incomplete evidence.
5. External source/get/context-manager/progress exceptions must be sanitized even
   when their class is SnapshotError. Never expose a URL/token in raised messages or
   error receipts. Internal meaningful validation errors may remain fixed strings.

Required finite tests: unchanged two-page snapshot succeeds with rotated URLs;
second-page addition/removal fails; duplicate/token cycle fails; namespace collisions
fail before HTTP; Range206/empty416/invalid/truncated replies; truncated or oversized
download never finalizes; fake clock crosses deadline during stream; external exceptions
containing a fake signed URL (including SnapshotError) are sanitized; invalid limits;
incomplete kernel refuses work; selected byte budget; receipt hashes/counts/scope.

Do not add Kaggle SDK integration yet. Do not alter the running collection, reference,
graph audit, model, inference, tests or scientific gates outside these two files.
