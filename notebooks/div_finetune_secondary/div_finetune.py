"""E21(prep): same hard-window fine-tune applied to the SECONDARY seed (seed314159 ep400).

Train windows containing a GT division parent are oversampled (K=28 -> ~30%
exposure); lr 1e-5; eval-12 stems excluded from training (quasi-clean probe of
the fine-tune delta). Saves edge_predictor_best.pth (test-score) AND
edge_predictor_last.pth (final epoch).
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

INPUT = Path("/kaggle/input")
WORK = Path("/kaggle/working")

EVAL12 = [
    "44b6_12dfb391", "44b6_267148e4", "44b6_2a2eff9f", "44b6_341df25f",
    "44b6_587a1e22", "44b6_5f15d135", "6bba_062c8d37", "6bba_07e24132",
    "6bba_085bf656", "6bba_09961292", "6bba_0e7c0d07", "6bba_12665c0e",
]

packs = sorted(INPUT.rglob("ARTIFACT_MANIFEST.json"))
pack = next(m.parent for m in packs
            if (m.parent / "repo" / "scripts" / "train_unet_transformer.py").exists())
sec_cands = [p for p in INPUT.rglob("edge_predictor_best.pth") if "seed314159" in str(p)]
assert len(sec_cands) == 1, sec_cands
SECONDARY_WEIGHTS = sec_cands[0]
print("pack =", pack)
wheels = pack / "wheels"
req = next(pack.glob("requirements-unet-ilp*.txt"), None)
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-index",
                "--find-links", str(wheels), "-r", str(req)], check=True)
print("deps installed")

repo = WORK / "tracking_repo"
if not repo.exists():
    shutil.copytree(pack / "repo", repo)
    shutil.copytree(pack / "weights", repo / "weights", dirs_exist_ok=True)

comp = next(p for p in [INPUT / "competitions" / "biohub-cell-tracking-during-development",
                        INPUT / "biohub-cell-tracking-during-development"] if p.exists())
train_dir = comp / "train"
stems = sorted(p.name for p in train_dir.glob("*.zarr"))
train_stems = [s for s in stems if s.replace(".zarr", "") not in EVAL12]
test_stems = [s for s in stems if s.replace(".zarr", "") in EVAL12[:2]]
print(f"train={len(train_stems)} (eval-12 excluded) test={test_stems}")
(repo / "ft_splits.json").write_text(json.dumps(
    [{"split": 0, "train": train_stems, "test": test_stems}]))

ts = repo / "scripts" / "train_unet_transformer.py"
s = ts.read_text()

# patch 1: full warm start after model construction (E19-verified anchor)
a1 = """        pos_feat_dim=pos_feat_dim,
    ).to(device)"""
assert s.count(a1) == 1
s = s.replace(a1, a1 + '''

    import os as _os
    _warm = _os.environ.get("BIOHUB_WARM_START", "")
    if _warm:
        _state = torch.load(_warm, map_location="cpu", weights_only=True)
        _missing, _unexpected = model.load_state_dict(_state, strict=False)
        print(f"WARM START from {_warm}: missing={len(_missing)} unexpected={len(_unexpected)}", flush=True)
        assert not _missing, f"warm start failed to cover keys: {_missing[:5]}"
''', 1)

# patch 2: division-window oversampler
a2 = """    train_loader = DataLoader(
        train_ds, batch_size=batch_size, shuffle=True,"""
assert s.count(a2) == 1
s = s.replace(a2, '''    import os as _os2
    _div_k = float(_os2.environ.get("BIOHUB_DIV_OVERSAMPLE_K", "0"))
    _sampler = None
    if _div_k > 0:
        _w = []
        for _meta, _vm in train_ds._data:
            _w.append(_div_k if bool((_meta["targets"].sum(dim=2) >= 2).any()) else 1.0)
        import torch.utils.data as _tud
        _n_div = sum(1 for x in _w if x > 1)
        _sampler = _tud.WeightedRandomSampler(_w, num_samples=len(_w), replacement=True)
        print(f"DIV OVERSAMPLER: {_n_div} division windows / {len(_w)} "
              f"(K={_div_k}, exposure~{_n_div*_div_k/(_n_div*_div_k+len(_w)-_n_div):.2f})", flush=True)
    train_loader = DataLoader(
        train_ds, batch_size=batch_size, shuffle=_sampler is None, sampler=_sampler,''', 1)

# patch 3: always save last-epoch weights too
a3 = """    print(f"\\nBest score (acc*recall): {best_score:.4f}, saved to {save_path}", flush=True)"""
assert s.count(a3) == 1
s = s.replace(a3, '''    torch.save(
        {k.replace("unet.module.", "unet.", 1): v for k, v in model.state_dict().items()},
        output_dir / "edge_predictor_last.pth",
    )
''' + a3, 1)

compile(s, str(ts), "exec")
ts.write_text(s)
print("patches applied: warm-start, div-oversampler, last-save")

env = {**os.environ, "PYTHONPATH": "src",
       "BIOHUB_WARM_START": str(SECONDARY_WEIGHTS),
       "BIOHUB_DIV_OVERSAMPLE_K": "28"}
t0 = time.time()
r = subprocess.run(
    [sys.executable, "scripts/train_unet_transformer.py",
     "--data-dir", str(train_dir), "--splits", "ft_splits.json", "--split", "0",
     "--epochs", "8", "--max-iters", "500", "--num-workers", "4",
     "--batch-size", "8", "--lr", "1e-5", "--method", "unet_transformer_divft_sec"],
    cwd=repo, env=env)
print(f"train wall: {(time.time() - t0) / 60:.1f} min")
r.check_returncode()

out = WORK / "ft_weights"
shutil.copytree(repo / "weights" / "unet_transformer_divft_sec" / "split_0", out, dirs_exist_ok=True)
print("saved:", sorted(p.name for p in out.iterdir()))
