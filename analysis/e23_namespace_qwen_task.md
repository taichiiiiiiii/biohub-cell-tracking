# D3 pure namespace authoring unit

> 履歴・非運用・現行起動に使用禁止。この旧タスクは保存用です。
> 現行方針は [AGENTS.md](../AGENTS.md)、MAX評価入口は
> [評価手順](../.codex/runners/biohub_max_implementer.instructions.md) を参照。
> 以下のモデル指定・命令・実行例は当時の履歴であり、現在のworkerへ渡してはいけません。

Direct user-supervised Qwen Cloud qwen3.8-max subscription-only request.
No tools, filesystem, network, agents, retries or fallback. Return exactly two
Python fenced blocks: standalone module and pytest tests. Parent will test them;
do not claim execution. No integration or real downloads in this unit.

Implement src/biohub/snapshot_namespace.py with NamespaceError(ValueError) and
validate_namespace(remote_paths, selected_paths, log_name) -> None.
Tests import biohub.snapshot_namespace. Python 3.12; Ruff E/W/F/I/UP/B; width120.

Only finite list/tuple containers accepted for remote and selected. Reject scalar
str/bytes, None, sets, generators and non-string entries. Preserve duplicate checks.
Remote entries unique; selected nonempty, unique, subset of remote. All paths and
log must be nonempty strings, relative POSIX lexical canonical files: reject
absolute paths, backslash, NUL, empty/dot/dotdot components, trailing slash.
No Unicode normalization or case folding. All errors fixed text, no input echoes.

Disjoint file categories: all remote files; reserved INVENTORY.json,
SNAPSHOT_ERROR.json and independently checked log_name; temporary selected+'.partial'.
Selected finals are already remote, not another disjoint category. Detect duplicate
reserved names and exact cross-category collisions BEFORE union. Across the full
namespace detect any file also ancestor of another file, using total-path-depth
bounded checks (not quadratic all-pairs or naive adjacent sorting).

Acceptance fixtures must include:
- remote [a,b], selected [a], log slug.log: accept.
- remote [d/a,d/b], selected both: accept.
- each reserved name and descendant remote: reject; log INVENTORY.json: reject.
- remote ancestor of nested log, remote descendant of log: reject.
- remote [a,a/b], selected [a/b]: reject even unselected ancestor.
- remote [a,a-b,a/b]: reject despite intervening sorted sibling.
- remote [a,a.partial], selected [a]: reject.
- remote [a,a.partial/b], selected [a]: reject.
- remote [a,a.partial], selected [a.partial]: ACCEPT (temporary a.partial.partial).
- duplicate remote/selected, missing selected, malformed inputs and paths: reject.
- functional 12000 remote fixture, no timing assertion.
- errors never echo sentinel untrusted path data.

No IO, global state, HTTP, deadlines, executors or transport changes. Use stdlib
and pytest only. Passing this unit does not certify existing snapshot transport.
