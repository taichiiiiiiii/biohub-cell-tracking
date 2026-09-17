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
