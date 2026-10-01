"""Export a verified candidate for graph evaluation, never submission approval.

Qwen draft corrected for actual artifact paths, schemas and candidate tensors.
The sealed run and the original primary checkpoint are never modified.
"""
import argparse
import io
import json
from pathlib import Path

import torch

from biohub.association_manifest import PRIMARY_EXPECTED_SHA
from biohub.training_history import (
    _contained_regular_file,
    atomic_publish_file,
    atomic_write_json,
    sha256_bytes,
    sha256_file,
    strict_json_load,
    trusted_pytorch_checkpoint_metadata_loader,
    verify_training_run,
)

ROOT = Path(__file__).resolve().parents[1]


def export_candidate(run_root, destination):
    root, dest = Path(run_root).absolute(), Path(destination).absolute()
    base = ROOT / "outputs/local/association_exports"
    if (root != root.resolve(strict=True) or dest != dest.resolve(strict=False)
            or not dest.is_relative_to(base) or dest == base or dest.is_relative_to(root)
            or root.is_relative_to(dest) or dest.exists() or dest.is_symlink()):
        raise ValueError("Unsafe or existing export location")
    artifact = _contained_regular_file(root, "ARTIFACT_MANIFEST.json")
    artifact_sha = sha256_file(artifact)
    result = verify_training_run(root, checkpoint_metadata_loader=trusted_pytorch_checkpoint_metadata_loader)
    if result["verdict"] != "PASS":
        raise ValueError("Training run did not pass")
    manifest = strict_json_load(_contained_regular_file(root, "run_manifest.json"))
    config = manifest["model_config"]
    if (manifest["purpose"] != "candidate" or manifest["run_kind"] != "single_split"
            or config["epochs"] != 10 or config["frozen_submodules"] != ["unet", "detect_head"]
            or config["original_warm_start_sha256"] != PRIMARY_EXPECTED_SHA):
        raise ValueError("Unexpected candidate contract")
    best = _contained_regular_file(root, "checkpoints/best.pt").read_bytes()
    original = _contained_regular_file(root, "provenance/primary-original.pth").read_bytes()
    if (sha256_bytes(best) != manifest["checkpoint_refs"]["checkpoints/best.pt"]
            or sha256_bytes(original) != PRIMARY_EXPECTED_SHA):
        raise ValueError("Checkpoint bytes differ from verified pins")
    candidate = torch.load(io.BytesIO(best), map_location="cpu", weights_only=True)["model_state"]
    baseline = torch.load(io.BytesIO(original), map_location="cpu", weights_only=True)
    if not isinstance(candidate, dict) or not candidate or set(candidate) != set(baseline):
        raise ValueError("State keys differ")
    frozen = {"unet.": 0, "detect_head.": 0}
    changed = []
    for name, tensor in candidate.items():
        before = baseline[name]
        if (not isinstance(tensor, torch.Tensor) or not isinstance(before, torch.Tensor)
                or tensor.shape != before.shape or tensor.dtype != before.dtype
                or not bool(torch.isfinite(tensor).all()) or not bool(torch.isfinite(before).all())):
            raise ValueError("State tensor schema or finiteness mismatch")
        same = torch.equal(tensor, before)
        prefix = next((prefix for prefix in frozen if name.startswith(prefix)), None)
        if prefix:
            frozen[prefix] += 1
            if not same:
                raise ValueError("Frozen detector tensor changed")
        elif not same:
            changed.append(name)
    if not all(frozen.values()) or not changed:
        raise ValueError("Frozen tensors missing or association unchanged")
    final = verify_training_run(root, checkpoint_metadata_loader=trusted_pytorch_checkpoint_metadata_loader)
    if final["verdict"] != "PASS" or sha256_file(artifact) != artifact_sha:
        raise ValueError("Sealed run changed during export")
    stream = io.BytesIO()
    torch.save(candidate, stream)  # Candidate, not the baseline/original state.
    raw = stream.getvalue()
    receipt = {"run_id": manifest["run_id"], "purpose": "graph_evaluation_only",
               "approved_for_submission": False, "original_sha256": PRIMARY_EXPECTED_SHA,
               "best_sha256": sha256_bytes(best), "artifact_manifest_sha256": artifact_sha,
               "export_sha256": sha256_bytes(raw), "changed_association_tensors": sorted(changed)}
    dest.mkdir(parents=True, exist_ok=False)
    atomic_publish_file(dest / "edge_predictor_best.pth", raw)
    if sha256_file(dest / "edge_predictor_best.pth") != receipt["export_sha256"]:
        raise ValueError("Export bytes changed")
    atomic_write_json(dest / "export.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(export_candidate(args.run_root, args.destination)))
        return 0
    except Exception as error:
        print(json.dumps({"state": "failed", "error_class": type(error).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
