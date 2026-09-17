Issue17 activeGoal QwenCloud Max authoring no tools. Return (1) complete new scripts/e31_dual_gpu_runtime.py notebook-cell fragment <=45lines and (2) minimal diff scripts/prepare_e31_submission.py below. No other edits. Same E31 weights/params/runtime preserved.

New fragment imports os,torch,Path and from biohub.e31_shards import run_workers. Notebook globals available WORKING_DIR,REPO_DIR,TEST_DIR,_ps,_primary_materialized_path,_deepcenter_materialized_path,SECONDARY_WEIGHTS_PATH,E31_HASHES,payloadroot. Check torch.cuda.device_count() >=2, otherwise RuntimeError (noCPU/singleGPU fallback). Parse os.environ.get('CUDA_VISIBLE_DEVICES','').strip(): if nonempty split comma striptokens; require at least2 nonempty DISTINCT tokens, reject -1; choose first2. If empty use ['0','1']. Build job dict with exact7Path globals plus E31_HASHES unchanged, call run_workers(job,payloadroot,cuda_tokens). Do not run at import in a library; this is intentionally executed notebookcell. No extra injection/hardware switches/files/thresholdchanges. Child bootstrap does not inherit these globals automatically.

Existing builder snippets exact:
    payload_paths = [
        "src/biohub/__init__.py",
        "src/biohub/io.py",
        "src/biohub/appearance_cost.py",
        "src/biohub/consensus_edges.py",
        "src/biohub/primary_consensus_observer.py",
        "src/biohub/association_instrumentation.py",
        "src/biohub/output_bounds.py",
        "src/biohub/screen_output_bounds.py",
    ] + [
...
    runtime_src = (repo / "scripts/e31_submission_runtime.py").read_text()
    src_cells.append(_code_cell(runtime_src))
    runtime_hash = hashlib.sha256(runtime_src.encode()).hexdigest()

Change only: add 'src/biohub/e31_shards.py' and 'scripts/e31_submission_runtime.py' to payload_paths; runtime_src now reads scripts/e31_dual_gpu_runtime.py. Existing builder hashes all payloads, writes them exclusively to payloadroot, validates every AST. Main single runtime becomes child code embedded as file. Do not invent new build schema, change baseline hash/cells, or copy baseline GT diagnostic cells.
