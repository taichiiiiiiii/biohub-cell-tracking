"""Score adoption-candidate parent patches with the fold CNNs (E7 deployment test).

Inputs:
  * dataset taichiiiii/biohub-div-cands: candidates.csv with columns
    stem,cand_id,t,z,y,x,fold   (parent node coordinates, voxel units;
    fold = the CV fold that held this video out during training)
  * kernel output taichiiiii/biohub-div-classifier: fold{0..3}.pt
  * competition train zarrs (patch source)

Output: cand_scores.csv (stem,cand_id,score). Leak-free: each video is scored
only by the model that never saw its patches.
"""
import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

try:
    import zarr
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "zarr"], check=True)
    import zarr

INPUT = Path("/kaggle/input")
cands_csvs = sorted(INPUT.rglob("candidates*.csv"))
cands_csv = cands_csvs[0] if cands_csvs else None
model_dir = next(iter(p.parent for p in INPUT.rglob("fold0.pt")), None)
train_dirs = sorted(d for d in INPUT.rglob("train") if d.is_dir())
if not (cands_csv and model_dir and train_dirs):
    print("mounts:", [str(p) for p in INPUT.iterdir()])
    raise FileNotFoundError(f"cands={cands_csvs} models={model_dir} train={train_dirs[:2]}")
TRAIN = train_dirs[0]
print(f"cands files={[c.name for c in cands_csvs]}\nmodels={model_dir}\ntrain={TRAIN}")

_info = json.load(open(model_dir / "model_info.json"))
RZ, RXY = int(_info.get("rz", 2)), int(_info.get("rxy", 12))
print(f"patch geometry from model_info: RZ={RZ} RXY={RXY}")


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.f = nn.Sequential(
            nn.Conv3d(2, 16, 3, padding=1), nn.BatchNorm3d(16), nn.ReLU(),
            nn.MaxPool3d((1, 2, 2)),
            nn.Conv3d(16, 32, 3, padding=1), nn.BatchNorm3d(32), nn.ReLU(),
            nn.MaxPool3d((1, 2, 2)),
            nn.Conv3d(32, 64, 3, padding=1), nn.BatchNorm3d(64), nn.ReLU(),
            nn.AdaptiveAvgPool3d(1), nn.Flatten(), nn.Dropout(0.3), nn.Linear(64, 1),
        )

    def forward(self, x):
        return self.f(x).squeeze(-1)


DEV = "cuda" if torch.cuda.is_available() else "cpu"
nets = {}
for k in range(4):
    n = Net().to(DEV)
    n.load_state_dict(torch.load(model_dir / f"fold{k}.pt", map_location=DEV))
    n.eval()
    nets[k] = n


def norm(batch):
    b = batch.astype(np.float32)
    med = np.median(b, axis=(1, 2, 3, 4), keepdims=True)
    mad = np.median(np.abs(b - med), axis=(1, 2, 3, 4), keepdims=True) + 1e-3
    return (b - med) / (3 * mad)


def extract(vol_t, vol_t1, z, y, x):
    """(2, 2*RZ+1, 2*RXY+1, 2*RXY+1) patch clamped at borders (zero pad)."""
    out = np.zeros((2, 2 * RZ + 1, 2 * RXY + 1, 2 * RXY + 1), dtype=np.uint16)
    Z, Y, X = vol_t.shape
    z0, z1 = z - RZ, z + RZ + 1
    y0, y1 = y - RXY, y + RXY + 1
    x0, x1 = x - RXY, x + RXY + 1
    sz0, sy0, sx0 = max(0, z0), max(0, y0), max(0, x0)
    sz1, sy1, sx1 = min(Z, z1), min(Y, y1), min(X, x1)
    dst = (slice(sz0 - z0, sz0 - z0 + (sz1 - sz0)),
           slice(sy0 - y0, sy0 - y0 + (sy1 - sy0)),
           slice(sx0 - x0, sx0 - x0 + (sx1 - sx0)))
    out[0][dst] = vol_t[sz0:sz1, sy0:sy1, sx0:sx1]
    out[1][dst] = vol_t1[sz0:sz1, sy0:sy1, sx0:sx1]
    return out


def score_file(cands_csv):
    rows = list(csv.DictReader(open(cands_csv)))
    print(f"{cands_csv.name}: {len(rows)} candidates across {len(set(r['stem'] for r in rows))} videos")
    by_stem = {}
    for r in rows:
        by_stem.setdefault(r["stem"], []).append(r)
    out_rows = []
    for stem, rr in sorted(by_stem.items()):
        arr = zarr.open(str(TRAIN / f"{stem}.zarr"), mode="r")["0"]
        net = nets[int(rr[0]["fold"])]
        by_t = {}
        for r in rr:
            by_t.setdefault(int(r["t"]), []).append(r)
        for t, group in sorted(by_t.items()):
            vol_t = np.asarray(arr[t])
            vol_t1 = np.asarray(arr[min(t + 1, arr.shape[0] - 1)])
            batch = np.stack([
                extract(vol_t, vol_t1, int(round(float(g["z"]))), int(round(float(g["y"]))), int(round(float(g["x"]))))
                for g in group
            ])
            with torch.no_grad():
                sc = torch.sigmoid(net(torch.from_numpy(norm(batch)).to(DEV))).cpu().numpy()
            for g, v in zip(group, sc, strict=True):
                out_rows.append({"stem": stem, "cand_id": g["cand_id"], "score": float(v)})
        print(f"  {stem}: scored={len(rr)}", flush=True)
    out_name = "cand_scores.csv" if cands_csv.name == "candidates.csv" else f"scores_{cands_csv.stem}.csv"
    with open(f"/kaggle/working/{out_name}", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["stem", "cand_id", "score"])
        w.writeheader()
        w.writerows(out_rows)
    print(f"wrote {len(out_rows)} -> {out_name}")


for cands_csv in cands_csvs:
    score_file(cands_csv)
