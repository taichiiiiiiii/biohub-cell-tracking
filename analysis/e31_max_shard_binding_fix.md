Issue17 active Goal, QwenCloud Max subscription authoring, no tools. Return ONLY minimal unified diff for scripts/e31_submission_runtime.py. Earlier delivery rejected, no changes applied. Concrete failures: builtins is NOT the runpy injected module globals; None bypassed validation; isinstance accepted subclasses contrary exact types; sorted comparison failed to reject unsorted input; altered unrelated existing asserts. Correct these causes, do not repeat prior patch.

Use globals() membership for optional E31_ASSIGNED_STEMS. If key exists, obtain from globals(), require type(value) is list, nonempty, each type(entry) is str, original list equals sorted(set(list)), and subset of discovered stems. Explicit None must raise TypeError. On valid assignment replace stems with a copy. Default absent key preserves original list. Use explicit exceptions for new checks only.
Read optional E31_WORKER_TAG using globals().get with empty string default; require exact str and value among empty, 0, 1 strings. Invalid tag raises ValueError before any file writes. Derive predictfilename e31_predict.py for empty, e31_predict_0.py or e31_predict_1.py otherwise. Keep all existing assertions and scientific parameters unchanged. Do not import builtins. Do not emit literal ellipsis as patch context.

Current two exact separate snippets (not adjacent):
stems = sorted(p.stem for p in TEST_DIR.glob("*.zarr"))
assert stems, "no test zarr stems"
assert len(stems) == len(set(stems))
assert not list(TEST_DIR.glob("*.geff"))

patched, insertion_receipt = instrument_source(_ps.read_text())
predict_path = REPO_DIR / "scripts" / "e31_predict.py"
with open(predict_path, "x", encoding="utf-8") as f:
    f.write(patched)
