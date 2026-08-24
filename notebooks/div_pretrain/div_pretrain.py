"""E7 Arm B: pretrain the division patch CNN on the CC0 synthetic dataset
(josefreitasalvesneto, Discussion #732103; 165k labelled divisions).

Output: pretrain.pt (state dict of the same tiny 3D CNN used by
biohub-div-classifier) + pretrain_info.json with val AUC on held-out
synthetic sequences. Fine-tuning on the real 151 happens downstream.
"""
import glob
import json
import os
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

RZ, RXY = 2, 12
DEV = "cuda" if torch.cuda.is_available() else "cpu"
RNG = np.random.default_rng(0)
POS_PER_SEQ = 30
NEG_PER_POS = 4
MAX_SEQS = int(os.environ.get("PRETRAIN_MAX_SEQS", "600"))
EPOCHS = 4

roots = glob.glob("/kaggle/input/**/sequences", recursive=True)
assert roots, [str(p) for p in Path("/kaggle/input").iterdir()]
SEQ_DIR = sorted(roots)[0]
seq_files = sorted(glob.glob(os.path.join(SEQ_DIR, "*.npz")))
print(f"{len(seq_files)} sequence files under {SEQ_DIR}")
RNG.shuffle(seq_files)
seq_files = seq_files[:MAX_SEQS]
n_val = max(20, len(seq_files) // 10)
val_files, tr_files = seq_files[:n_val], seq_files[n_val:]


def extract(vol_t, vol_t1, z, y, x):
    out = np.zeros((2, 2 * RZ + 1, 2 * RXY + 1, 2 * RXY + 1), dtype=np.float32)
    for i, fr in enumerate((vol_t, vol_t1)):
        Z, Y, X = fr.shape
        z0, y0, x0 = int(round(z)) - RZ, int(round(y)) - RXY, int(round(x)) - RXY
        zs, ys, xs = max(0, z0), max(0, y0), max(0, x0)
        ze = min(Z, z0 + 2 * RZ + 1); ye = min(Y, y0 + 2 * RXY + 1); xe = min(X, x0 + 2 * RXY + 1)
        out[i, zs - z0:ze - z0, ys - y0:ye - y0, xs - x0:xe - x0] = fr[zs:ze, ys:ye, xs:xe]
    return out


def sample_patches(f):
    """yield (patch, label) from one sequence npz"""
    try:
        s = np.load(f)
        vols, nodes, divs = s["volumes"], s["nodes"], s["divisions"]
    except Exception as e:
        print(f"skip {os.path.basename(f)}: {type(e).__name__}")
        return []
    T = vols.shape[0]
    t_col = nodes[:, 0].astype(int)
    out = []
    div_idx = np.asarray(divs).astype(int).ravel()
    div_idx = div_idx[t_col[div_idx] < T - 1]
    if len(div_idx) > POS_PER_SEQ:
        div_idx = RNG.choice(div_idx, POS_PER_SEQ, replace=False)
    div_set = set(div_idx.tolist())
    neg_pool = np.array([i for i in range(len(nodes)) if i not in div_set and t_col[i] < T - 1])
    n_neg = min(len(neg_pool), NEG_PER_POS * max(1, len(div_idx)))
    neg_idx = RNG.choice(neg_pool, n_neg, replace=False) if n_neg else []
    for idx, lab in [(i, 1) for i in div_idx] + [(i, 0) for i in neg_idx]:
        t, z, y, x = nodes[idx, 0], nodes[idx, 1], nodes[idx, 2], nodes[idx, 3]
        t = int(t)
        out.append((extract(vols[t], vols[min(t + 1, T - 1)], z, y, x), lab))
    return out


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


def norm_batch(b):
    med = np.median(b, axis=(1, 2, 3, 4), keepdims=True)
    mad = np.median(np.abs(b - med), axis=(1, 2, 3, 4), keepdims=True) + 1e-3
    return (b - med) / (3 * mad)


def auc(yt, ys):
    o = np.argsort(ys); r = np.empty(len(ys)); r[o] = np.arange(len(ys))
    p = yt == 1
    return (r[p].sum() - p.sum() * (p.sum() - 1) / 2) / max(1, p.sum() * (~p).sum())


# build the validation pool once
val_X, val_y = [], []
for f in val_files:
    for p, lab in sample_patches(f):
        val_X.append(p); val_y.append(lab)
val_X = norm_batch(np.stack(val_X)); val_y = np.array(val_y, dtype=np.float32)
print(f"val pool: {len(val_y)} patches, pos={int(val_y.sum())}")

net = Net().to(DEV)
opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-4)
lossf = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([float(NEG_PER_POS)], device=DEV))
history = []
step = 0
for ep in range(EPOCHS):
    RNG.shuffle(tr_files)
    buf_X, buf_y = [], []
    ep_loss, nb = 0.0, 0
    net.train()
    for f in tr_files:
        for p, lab in sample_patches(f):
            buf_X.append(p); buf_y.append(lab)
        while len(buf_y) >= 256:
            xb = torch.from_numpy(norm_batch(np.stack(buf_X[:256]))).to(DEV)
            yb = torch.from_numpy(np.array(buf_y[:256], dtype=np.float32)).to(DEV)
            del buf_X[:256], buf_y[:256]
            opt.zero_grad()
            loss = lossf(net(xb), yb)
            loss.backward()
            opt.step()
            ep_loss += float(loss.item()); nb += 1; step += 1
    net.eval()
    with torch.no_grad():
        vs = []
        for i in range(0, len(val_y), 512):
            vs.append(torch.sigmoid(net(torch.from_numpy(val_X[i:i+512]).to(DEV))).cpu().numpy())
        va = auc(val_y, np.concatenate(vs))
    history.append({"epoch": ep, "train_loss": ep_loss / max(1, nb), "val_auc": float(va)})
    print(f"ep {ep}: batches={nb} train_loss={ep_loss/max(1,nb):.4f} SYNTH val_auc={va:.4f}", flush=True)

torch.save(net.state_dict(), "/kaggle/working/pretrain.pt")
json.dump({"history": history, "n_train_seqs": len(tr_files), "n_val_patches": int(len(val_y)),
           "rz": RZ, "rxy": RXY}, open("/kaggle/working/pretrain_info.json", "w"))
print("saved pretrain.pt")
