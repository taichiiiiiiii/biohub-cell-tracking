"""E19: training feasibility probe (ledger E19).

Measures sec/iter and iters/epoch for train_unet_transformer.py on the full
train split, bounded by --max-iters, plus a warm-start continuity check
(loading the 400ep edge_predictor_best.pth before training).

Outputs /kaggle/working/probe_report.json.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

INPUT = Path("/kaggle/input")
WORK = Path("/kaggle/working")

# --- locate support pack (repo + wheels + weights) ---
packs = sorted(INPUT.rglob("ARTIFACT_MANIFEST.json"))
pack = None
for m in packs:
    if (m.parent / "repo" / "scripts" / "train_unet_transformer.py").exists():
        pack = m.parent
        break
assert pack, f"no support pack found: {[str(p) for p in packs]}"
print("pack =", pack)

# --- offline wheel install ---
wheels = pack / "wheels"
req = next(pack.glob("requirements-unet-ilp*.txt"), None)
if wheels.exists():
    cmd = [sys.executable, "-m", "pip", "install", "-q", "--no-index",
           "--find-links", str(wheels)]
    cmd += ["-r", str(req)] if req else ["zarr", "geff", "tracksdata", "polars", "blosc2"]
    subprocess.run(cmd, check=True)
print("deps installed")

# --- copy repo ---
import shutil
repo = WORK / "tracking_repo"
if not repo.exists():
    shutil.copytree(pack / "repo", repo)
    shutil.copytree(pack / "weights", repo / "weights", dirs_exist_ok=True)

# --- build a full-train splits file ---
comp = next(p for p in [INPUT / "competitions" / "biohub-cell-tracking-during-development",
                        INPUT / "biohub-cell-tracking-during-development"] if p.exists())
train_dir = comp / "train"
stems = sorted(p.name for p in train_dir.glob("*.zarr"))
print(f"train videos: {len(stems)}")
test_stems = stems[:2]  # tiny test list: epoch-end eval kept cheap
splits = [{"split": 0, "train": stems, "test": test_stems}]
sp = repo / "probe_splits.json"
sp.write_text(json.dumps(splits))

# --- patch train script: optional full warm start from env ---
ts = repo / "scripts" / "train_unet_transformer.py"
s = ts.read_text()
anchor = """        pos_feat_dim=pos_feat_dim,
    ).to(device)"""
assert s.count(anchor) == 1
warm = anchor + '''

    import os as _os
    _warm = _os.environ.get("BIOHUB_WARM_START", "")
    if _warm:
        _state = torch.load(_warm, map_location="cpu", weights_only=True)
        _missing, _unexpected = model.load_state_dict(_state, strict=False)
        print(f"WARM START from {_warm}: missing={len(_missing)} unexpected={len(_unexpected)}", flush=True)
        assert not _missing, f"warm start failed to cover keys: {_missing[:5]}"
'''
s = s.replace(anchor, warm, 1)
compile(s, str(ts), "exec")
ts.write_text(s)
print("warm-start patch applied")

# --- probe run: 1 epoch capped at N iters ---
N_ITERS = 150
import os
env = {**os.environ, "PYTHONPATH": "src",
       "BIOHUB_WARM_START": str(repo / "weights" / "unet_transformer" / "split_0" / "edge_predictor_best.pth")}
t0 = time.time()
r = subprocess.run(
    [sys.executable, "scripts/train_unet_transformer.py",
     "--data-dir", str(train_dir), "--splits", "probe_splits.json", "--split", "0",
     "--epochs", "1", "--max-iters", str(N_ITERS), "--num-workers", "4",
     "--batch-size", "8"],  # v1: batch 16 OOMed on T4 (per-GPU 8 needs >14.5GB)
    cwd=repo, env=env, capture_output=True, text=True)
wall = time.time() - t0
print("STDOUT tail:\n", r.stdout[-4000:])
print("STDERR tail:\n", r.stderr[-2000:])
r.check_returncode()

report = {
    "n_iters": N_ITERS,
    "wall_seconds_total": wall,
    "note": "wall includes data-pipeline warmup + epoch-end eval on 2 videos; see stdout for per-iter pace and initial loss (warm-start continuity)",
}
json.dump(report, open(WORK / "probe_report.json", "w"), indent=1)
print("probe done:", report)
