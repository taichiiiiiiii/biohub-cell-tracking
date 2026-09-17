Issue17 QwenCloud Max authoring no tools. Return complete NEW tests/test_e31_notebook.py <=110lines. Tests actual sources, no copied logic. Test entry script via exec(compile(read_text),globalsdict) with monkeypatch torch.cuda.device_count and biohub.e31_shards.run_workers capture. fixture globals exact7paths temporarydummyPaths + E31_HASHES {} + payloadroot Path. No files needed because run_workers mocked. Success raw CUDA_VISIBLE_DEVICES empty and '2,5': count2, expected tokens ['0','1'] or ['2','5']; assert captured job EXACT keys/values unchanged, primaryweights distinct from _ps and passed correctly. GPUfailure count1 and malformed tokens '-1,1','0,0','0,','0' raise RuntimeError and runner nevercalled. Builder: load actual scripts/prepare_e31_submission.py with importlib.util or runpy.run_path (not __main__); call build(repo). Notebook last code source equals scripts/e31_dual_gpu_runtime.py text, runtimehash sha matches. receipt.payloadhashes includes src/biohub/e31_shards.py and scripts/e31_submission_runtime.py; compute actualsource SHA for ALL entries equals receipt. No execution of notebook setup or any GPU/network. Builder outputs keys notebook,metadata,receipt; receipt key payloadhashes NOT E31_HASHES. Verify metadata offline is string 'false', is_private string 'true'. No imports from scripts package guess. CURRENT ENTRY:
import os
import torch
from pathlib import Path
from biohub.e31_shards import run_workers

if torch.cuda.device_count() < 2:
    raise RuntimeError(
        "e31_dual_gpu_runtime requires >=2 visible CUDA devices; no CPU/single-GPU fallback is provided."
    )

raw = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip()
if raw:
    tokens = [t.strip() for t in raw.split(",")]
    if len(tokens) < 2:
        raise RuntimeError(f"CUDA_VISIBLE_DEVICES must contain at least 2 tokens, got {raw!r}")
    first2 = tokens[:2]
    if not first2[0] or not first2[1]:
        raise RuntimeError(f"First two CUDA_VISIBLE_DEVICES tokens must be non-empty, got {raw!r}")
    if first2[0] == "-1" or first2[1] == "-1":
        raise RuntimeError(f"First two CUDA_VISIBLE_DEVICES tokens must not be -1, got {raw!r}")
    if first2[0] == first2[1]:
        raise RuntimeError(f"First two CUDA_VISIBLE_DEVICES tokens must be distinct, got {raw!r}")
    cuda_tokens = first2
else:
    cuda_tokens = ["0", "1"]

job = {
    "WORKING_DIR": Path(WORKING_DIR),
    "REPO_DIR": Path(REPO_DIR),
    "TEST_DIR": Path(TEST_DIR),
    "_ps": Path(_ps),
    "_primary_materialized_path": Path(_primary_materialized_path),
    "_deepcenter_materialized_path": Path(_deepcenter_materialized_path),
    "SECONDARY_WEIGHTS_PATH": Path(SECONDARY_WEIGHTS_PATH),
    "E31_HASHES": E31_HASHES,
}

run_workers(job, payloadroot, cuda_tokens)

