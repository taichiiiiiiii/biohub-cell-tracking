Issue17 activeGoal QwenCloud Max authoringonly no tools. Goal restore2GPU independentvideo execution WITHOUT scientificchange. Current runtime tested full4GPUcomplete. Return minimal diff ONLY scripts/e31_submission_runtime.py:
Recovery clarification: the earlier invocation has no live process and no recoverable delivery in parent context; nothing has been applied. New acceptance requirement: distinguish absent E31_ASSIGNED_STEMS from explicitly supplied None; None must fail closed. Validate worker tag before creating the predictor file. Use explicit exceptions rather than assertions for the new injected-input checks. Return only one minimal unified diff, no test claims.
After stems discovery/assert no .geff, optional injected globals E31_ASSIGNED_STEMS. If absent leave behavior. If present require exact list nonempty all exactstr, sortedunique, subset of discoveredstems; then stems=list(assigned). Each child uses ownWORKING_DIR andCUDA_VISIBLE_DEVICES, sameREPO_DIR andreadonlyweights.
To avoid shared predictorfile collisions add optional E31_WORKER_TAG default "" via globals.get. Require exact str in ("","0","1") only; predictfilename default e31_predict.py unchanged, tag=0/1 => e31_predict_0.py/e31_predict_1.py. Existing dynamic module name e31_predict remains perprocess okay.
No other edits. No envspecialcase/testdatasetnames/losschanges/modelchanges. Return exactdiff only.
CURRENT:
stems = sorted(p.stem for p in TEST_DIR.glob("*.zarr"))
assert stems, "no test zarr stems"
assert len(stems) == len(set(stems))
assert not list(TEST_DIR.glob("*.geff"))
...
patched, insertion_receipt = instrument_source(_ps.read_text())
predict_path = REPO_DIR / "scripts" / "e31_predict.py"
with open(predict_path, "x", encoding="utf-8") as f:
    f.write(patched)
