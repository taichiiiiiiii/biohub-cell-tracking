"""Train the E6 division patch classifier (tiny 3D CNN) on div_patches output.

Overfitting controls (per user directive 2026-08-24):
  * grouped CV: folds split by VIDEO, balanced by lineage and positive count
    (no per-video leakage; each fold sees both 44b6/6bba and ~equal positives)
  * per-epoch learning curves (train loss + val AUC) printed and saved to
    history.json so divergence between train and val is visible in the log
  * best-epoch tracking per fold; the final all-data model trains for the
    median best epoch instead of a fixed large count
  * thresholds are chosen from OOF scores only (honest precision@recall)
"""
import csv
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

INPUT = Path("/kaggle/input")
_hits = sorted(INPUT.rglob("div_patches.npz"))
if not _hits:
    print("mount tree:", [str(p) for p in INPUT.rglob("*") if p.is_dir()][:40])
    raise FileNotFoundError("div_patches.npz not found under /kaggle/input")
SRC = _hits[0].parent
print("SRC =", SRC)
d = np.load(SRC / "div_patches.npz")
X, y = d["X"], d["y"].astype(np.float32)
with open(SRC / "meta.csv") as f:
    meta = list(csv.DictReader(f))
stems = np.array([m["stem"] for m in meta])
print(f"X={X.shape} pos={int(y.sum())} neg={int((1 - y).sum())} videos={len(set(stems))}")

DEV = "cuda" if torch.cuda.is_available() else "cpu"
RNG = np.random.default_rng(0)
N_FOLDS = 4
MAX_EPOCHS = 30


def norm(batch):
    """robust per-patch normalization (no dataset-level stats -> no leakage)"""
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


def auc(y_true, y_score):
    order = np.argsort(y_score)
    ranks = np.empty(len(y_score))
    ranks[order] = np.arange(len(y_score))
    pos = y_true == 1
    return (ranks[pos].sum() - pos.sum() * (pos.sum() - 1) / 2) / max(1, pos.sum() * (~pos).sum())


def predict(net, idx, bs=256):
    net.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(idx), bs):
            j = idx[i:i + bs]
            out.append(torch.sigmoid(net(torch.from_numpy(norm(X[j])).to(DEV))).cpu().numpy())
    return np.concatenate(out)


def train_fold(tr_idx, va_idx, epochs, tag, history):
    net = Net().to(DEV)
    pos_w = torch.tensor([(len(tr_idx) - y[tr_idx].sum()) / max(1.0, y[tr_idx].sum())], device=DEV)
    lossf = nn.BCEWithLogitsLoss(pos_weight=pos_w)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    bs = 64
    best = {"auc": -1.0, "ep": -1, "scores": None}
    for ep in range(epochs):
        net.train()
        idx = RNG.permutation(tr_idx)
        tot, nb = 0.0, 0
        for i in range(0, len(idx), bs):
            j = idx[i:i + bs]
            xb = torch.from_numpy(norm(augment(X[j]))).to(DEV)
            yb = torch.from_numpy(y[j]).to(DEV)
            opt.zero_grad()
            loss = lossf(net(xb), yb)
            loss.backward()
            opt.step()
            tot += float(loss.item())
            nb += 1
        sched.step()
        rec = {"tag": tag, "epoch": ep, "train_loss": tot / max(1, nb)}
        if va_idx is not None:
            s = predict(net, va_idx)
            rec["val_auc"] = float(auc(y[va_idx], s))
            if rec["val_auc"] > best["auc"]:
                best = {"auc": rec["val_auc"], "ep": ep, "scores": s}
            print(f"[{tag}] ep {ep:02d}  train_loss={rec['train_loss']:.4f}  val_auc={rec['val_auc']:.4f}"
                  + ("  *best*" if best["ep"] == ep else ""), flush=True)
        else:
            print(f"[{tag}] ep {ep:02d}  train_loss={rec['train_loss']:.4f}", flush=True)
        history.append(rec)
    return net, best


# ---- balanced grouped folds: per lineage, snake-draft videos by positive count
vid_pos = {}
for v in sorted(set(stems)):
    vid_pos[v] = int(y[stems == v].sum())
fold_of = {}
for lineage in ("44b6", "6bba"):
    vids = [v for v in vid_pos if v.startswith(lineage)]
    vids.sort(key=lambda v: (-vid_pos[v], v))
    for i, v in enumerate(vids):
        k = i % (2 * N_FOLDS)
        fold_of[v] = k if k < N_FOLDS else 2 * N_FOLDS - 1 - k
fold_arr = np.array([fold_of[s] for s in stems])
for k in range(N_FOLDS):
    m = fold_arr == k
    print(f"fold {k}: videos={len(set(stems[m]))} n={int(m.sum())} pos={int(y[m].sum())} "
          f"(44b6 pos={int(y[m & np.char.startswith(stems, '44b6')].sum())})")

history: list[dict] = []
oof = np.zeros(len(y))
last_ep_auc = []
best_eps = []
for k in range(N_FOLDS):
    va_mask = fold_arr == k
    net, best = train_fold(np.where(~va_mask)[0], np.where(va_mask)[0], MAX_EPOCHS, f"fold{k}", history)
    torch.save(net.state_dict(), f"/kaggle/working/fold{k}.pt")   # leak-free scorer for fold-k videos
    oof[va_mask] = best["scores"]          # scores from the best epoch, not the last
    final_s = predict(net, np.where(va_mask)[0])
    last_ep_auc.append(float(auc(y[va_mask], final_s)))
    best_eps.append(best["ep"])
    print(f"fold {k}: best ep={best['ep']} auc={best['auc']:.4f} | last ep auc={last_ep_auc[-1]:.4f} "
          f"(gap {best['auc'] - last_ep_auc[-1]:+.4f} = late-epoch overfit if positive)")

rank = np.zeros(len(oof))
for k in range(N_FOLDS):
    m = fold_arr == k
    rank[m] = np.argsort(np.argsort(oof[m])) / max(1, m.sum() - 1)
fold_aucs = [float(auc(y[fold_arr == k], oof[fold_arr == k])) for k in range(N_FOLDS)]
print(f"\nper-fold AUC={['%.4f' % a for a in fold_aucs]}  "
      f"pooled(rank-norm) AUC={auc(y, rank):.4f}  best_eps={best_eps}")
print("NOTE: raw pooled OOF AUC mixes per-fold calibrations -- use rank-normalized")
thr_table = []
for rec_t in (0.9, 0.8, 0.7, 0.5):
    thr = float(np.quantile(rank[y == 1], 1 - rec_t))
    sel = rank >= thr
    prec = float(y[sel].mean()) if sel.any() else 0.0
    thr_table.append({"recall": rec_t, "thr": thr, "precision": prec, "flagged": int(sel.sum())})
    print(f"recall~{rec_t}: thr={thr:.3f} precision={prec:.3f} flagged={int(sel.sum())}")
np.save("/kaggle/working/oof_scores.npy", oof)

# ---- final model on all data, trained for the CV-selected epoch count
final_epochs = max(8, int(np.median(best_eps)) + 1)   # val curves are flat from ep0; floor=8 for stable BN stats
print(f"\nfinal model: {final_epochs} epochs (median fold best +1, floor 8)")
net_all, _ = train_fold(np.arange(len(y)), None, final_epochs, "final", history)
torch.save(net_all.state_dict(), "/kaggle/working/div_classifier.pt")
json.dump(
    {
        "arch": "tiny3dcnn-v1",
        "input": f"{tuple(X.shape[1:])} med/mad-normalized",
        "rz": int((X.shape[2] - 1) // 2),
        "rxy": int((X.shape[3] - 1) // 2),
        "folds": {v: int(k) for v, k in fold_of.items()},
        "fold_aucs": fold_aucs,
        "pooled_rank_auc": float(auc(y, rank)),
        "fold_best_epochs": best_eps,
        "fold_last_auc": last_ep_auc,
        "final_epochs": final_epochs,
        "thresholds": thr_table,
    },
    open("/kaggle/working/model_info.json", "w"), indent=1,
)
json.dump(history, open("/kaggle/working/history.json", "w"))
print("saved final model + history")
