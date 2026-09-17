# Direct supervised Qwen Cloud Max token-only configuration task

> 履歴・非運用・現行起動に使用禁止。この旧タスクは保存用です。
> 現行方針は [AGENTS.md](../AGENTS.md)、MAX評価入口は
> [評価手順](../.codex/runners/biohub_max_implementer.instructions.md) を参照。
> 以下のモデル指定・命令・実行例は当時の履歴であり、現在のworkerへ渡してはいけません。

Use exactly qwen3.8-max, existing qwen_token_plan subscription route, effort none.
One response, no tools or file access, no feedback/retries/fallback. Parent cap180
seconds includes admission. Do not edit implementation, tests, settings or data.

The application is accepted, but its run must be reidentified for a preregistered
v3 report-accounting reproducibility check. The only required configuration edit
is a literal run-token suffix in two existing files. The parent owns integration
and all validation/external actions. No scientific or control-flow change.

Return exactly one JSON object, without Markdown or prose, containing:
old_suffix: the literal string "39549fb-20260907"
new_suffix: the literal string "39549fb-20260907-v3"
expected_replacements: an object with exactly these two keys and integer values:
"notebooks/e26_target_motion_off_bounds/e26_target_motion_off.ipynb": 1
"tests/test_e26_bounds_notebook.py": 2

These suffixes are public run identifiers, not credentials. The full old token
is e26-bounds-a8d2b43e-d39549fb-20260907. One test copy is split across adjacent
string literals but the suffix itself remains contiguous. Preserve everything
else exactly, including notebook metadata, cells, helper, tests and line endings.
