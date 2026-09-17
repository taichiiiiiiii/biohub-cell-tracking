# E26 test constant types — minimal authoring unit

> 履歴・非運用・現行起動に使用禁止。この旧タスクは保存用です。
> 現行方針は [AGENTS.md](../AGENTS.md)、MAX評価入口は
> [評価手順](../.codex/runners/biohub_max_implementer.instructions.md) を参照。
> 以下のモデル指定・命令・実行例は当時の履歴であり、現在のworkerへ渡してはいけません。

User asked exact Qwen Cloud qwen3.8-max; existing Token Plan/none/no tools.
Single response capped180sec, no feedback, no model/route fallback.
Application/notebook bytes are frozen and reviewed. DO NOT change implementation.
Parent test run:9PASS/1FAIL. The only remaining test error is literaltypes:
test_end_to_end_writer_tail_with_bounds expects strings "node_id1"/"node_id2"/
"node_id5" from a compressed prose handoff, but real fixture node IDs are
builtin integers: first alpha node_id=1, second alpha node_id=2, beta node_id=5.
The correction sample's node_id is builtin integer1. CSV/template require integerIDs.
This is oracle correction, NOT coercing application to strings.

Return EXACTLY ONE literalPython block and NO prose:
```python
REPLACEMENTS = [
    (<exact old text>, <corrected text>),
    ... exactly4tuple pairs ...
]
```
Only one assignment to literal list;4tuplesofstr; noothercode.
Each old text below occurs once in tests/test_e26_bounds_notebook.py:
"node_id": "node_id1"
"node_id": "node_id2"
"node_id": "node_id5"
assert sample["node_id"] == "node_id1"

Replace only the WRONG STRING VALUES with respective integer literals
1,2,5,1. Preserve keys, assertion, indentation and surrounding code.
Do not rewrite tests, imports, fixtures, row IDs, shapes or notebook.
Parent applies exact unique replacements, checks no otherdiff, runsalltests/Ruff.
