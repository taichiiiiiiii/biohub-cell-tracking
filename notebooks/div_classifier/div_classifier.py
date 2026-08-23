"""Train the E6 division patch classifier (tiny 3D CNN) on div_patches output.

Group split by video (no leakage). Reports grouped CV AUC and
precision@recall targets; saves final model trained on all data.
"""
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

SRC = Path("/kaggle/input/biohub-div-patches")
d = np.load(SRC / "div_patches.npz")
X, y = d["X"], d["y"].astype(np.float32)
import csv
with open(SRC / "meta.csv") as f:
    meta = list(csv.DictReader(f))
stems = np.array([m["stem"] for m in meta])
print(f"X={X.shape} pos={int(y.sum())} neg={int((1-y).sum())} videos={len(set(stems))}")

DEV = "cuda" if torch.cuda.is_available() else "cpu"
RNG = np.random.default_rng(0)


def norm(batch):
    """robust per-patch normalization"""
    b = batch.astype(np.float32)
    med = np.median(b, axis=(1, 2, 3, 4), keepdims=True)
    mad = np.median(np.abs(b - med), axis=(1, 2, 3, 4), keepdims=True) + 1e-3
    return (b - med) / (3 * mad)


def augment(b):
    if RNG.random() < 0.5:
        b = b[:, :, :, ::-1, :]
    if RNG.random() < 0.5:
        b = b[:, :, :, :, ::-1]
    if RNG.random() < 0.5:
        b = np.swapaxes(b, 3, 4)
    if RNG.random() < 0.3:
        b = b[:, :, ::-1, :, :]
    return np.ascontiguousarray(b)


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


def train_fold(tr_idx, va_idx, epochs=30):
    net = Net().to(DEV)
    pos_w = torch.tensor([(len(tr_idx) - y[tr_idx].sum()) / max(1.0, y[tr_idx].sum())], device=DEV)
    lossf = nn.BCEWithLogitsLoss(pos_weight=pos_w)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    bs = 64
    for ep in range(epochs):
        net.train()
        idx = RNG.permutation(tr_idx)
        for i in range(0, len(idx), bs):
            j = idx[i:i + bs]
            xb = torch.from_numpy(norm(augment(X[j]))).to(DEV)
            yb = torch.from_numpy(y[j]).to(DEV)
            opt.zero_grad()
            loss = lossf(net(xb), yb)
            loss.backward()
            opt.step()
        sched.step()
    net.eval()
    scores = []
    with torch.no_grad():
        for i in range(0, len(va_idx), 256):
            j = va_idx[i:i + 256]
            scores.append(torch.sigmoid(net(torch.from_numpy(norm(X[j])).to(DEV))).cpu().numpy())
    return net, np.concatenate(scores)


def auc(y_true, y_score):
    order = np.argsort(y_score)
    ranks = np.empty(len(y_score)); ranks[order] = np.arange(len(y_score))
    pos = y_true == 1
    return (ranks[pos].sum() - pos.sum() * (pos.sum() - 1) / 2) / max(1, pos.sum() * (~pos).sum())

videos = np.array(sorted(set(stems)))
RNG.shuffle(videos)
folds = np.array_split(videos, 4)
oof = np.zeros(len(y))
for k, va_videos in enumerate(folds):
    va_mask = np.isin(stems, va_videos)
    net, s = train_fold(np.where(~va_mask)[0], np.where(va_mask)[0])
    oof[va_mask] = s
    print(f"fold {k}: va_pos={int(y[va_mask].sum())} auc={auc(y[va_mask], s):.3f}")
print(f"OOF AUC={auc(y, oof):.4f}")
for rec in (0.9, 0.8, 0.7, 0.5):
    thr = np.quantile(oof[y == 1], 1 - rec)
    prec = y[oof >= thr].mean()
    print(f"recall~{rec}: thr={thr:.3f} precision={prec:.3f} flagged={int((oof>=thr).sum())}")
np.save("/kaggle/working/oof_scores.npy", oof)

# final model on all data
net_all = Net().to(DEV)
pos_w = torch.tensor([(len(y) - y.sum()) / y.sum()], device=DEV)
lossf = nn.BCEWithLogitsLoss(pos_weight=pos_w)
opt = torch.optim.AdamW(net_all.parameters(), lr=1e-3, weight_decay=1e-4)
sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, 40)
for ep in range(40):
    net_all.train()
    idx = RNG.permutation(len(y))
    for i in range(0, len(idx), 64):
        j = idx[i:i + 64]
        xb = torch.from_numpy(norm(augment(X[j]))).to(DEV)
        yb = torch.from_numpy(y[j]).to(DEV)
        opt.zero_grad(); lossf(net_all(xb), yb).backward(); opt.step()
    sched.step()
torch.save(net_all.state_dict(), "/kaggle/working/div_classifier.pt")
json.dump({"arch": "tiny3dcnn-v1", "input": "(2,5,25,25) med/mad-normalized"},
          open("/kaggle/working/model_info.json", "w"))
print("saved final model")
