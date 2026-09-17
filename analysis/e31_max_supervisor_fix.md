Issue17 QwenCloud Max authoring no tools. Previous supervisor not applied. Return ONLY corrected replacement snippets A–F, no full function. Concrete defects below.
A validate cuda_tokens first two EXACT str nonempty distinct; reject -1. Existing code only truthiness. Current:
    if len(cuda_tokens) < 2 or not cuda_tokens[0] or not cuda_tokens[1] or cuda_tokens[0] == cuda_tokens[1]:
        raise ValueError("cuda_tokens must have >=2 distinct nonempty strings")
B current bogus .geff exclusion inside *.zarr glob never checks GT. Replace:
    stems = sorted(p.stem for p in test_dir.glob("*.zarr") if not p.name.endswith(".geff"))
with stems sorted *.zarr AND explicit if list(test_dir.glob('*.geff')): raise ValueError('GT geff forbidden'). Do not delete or skip GT silently.
C hashes keys RELATIVE, so replace:
    if str(runtime) not in hashes:
        raise ValueError("runtime path missing from E31_HASHES")
with exact key 'scripts/e31_submission_runtime.py' check.
D replace jpath.write_text(json.dumps(cjob)) and child.log open w: give TWO separate snippets using open x, encoding UTF8, job json.dump contextmanager. child.log with stack.enter_context open x encodingUTF8; preserve lf variable.
E replace this polling block (currently waits all children before detecting failure, wrong):
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError("workers exceeded timeout")
                done = all(p.poll() is not None for p in procs)
                if done:
                    break
                time.sleep(1.0)
Poll EACH child on every iteration; immediately raise RuntimeError including i/returncode/logfiles[i] for nonzero, letting existing finally terminate sibling. done flag only true if all zero; preserve timeout and sleep1. No all() short circuit skipped poll. Later for returncode check may remain redundant but harmless.
F replace tpath.write_text(json.dumps(timing)) with exclusive x UTF8 with-open json.dump(timing). No overwrite.
