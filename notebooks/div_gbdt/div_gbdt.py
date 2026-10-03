"""E7 parallel arm: GBDT pair selector on geometry+track features (no CNN).

Trains on the 24 fresh videos' candidate pairs (grouped CV by video),
scores the eval-12 pairs. Datasets: biohub-div-pairs (pairs_train.csv,
pairs_eval.csv from e6_measure).
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
import polars as pl

try:
    import lightgbm as lgb
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "lightgbm"], check=True)
    import lightgbm as lgb

INPUT = Path("/kaggle/input")
tr_csv = next(iter(INPUT.rglob("pairs_train.csv")), None)
ev_csv = next(iter(INPUT.rglob("pairs_eval.csv")), None)
if not (tr_csv and ev_csv):
    raise FileNotFoundError([str(p) for p in INPUT.iterdir()])

FEATS = ["d_pc", "sister", "mid_over_sister", "border", "orphan_speed", "orphan_len4", "d_qc"]


def prep(df):
    df = df.with_columns((pl.col("kind") == "steal").cast(pl.Int8).alias("is_steal"))
    x = df.select(FEATS + ["is_steal"]).to_numpy().astype(np.float32)
    return np.nan_to_num(x, nan=-1.0), df["real"].to_numpy().astype(np.int8), df


tr = pl.read_csv(tr_csv)
ev = pl.read_csv(ev_csv)
Xtr, ytr, tr = prep(tr)
Xev, yev, ev = prep(ev)
videos = tr["dataset"].to_numpy()
print(f"train pairs={len(ytr)} real={ytr.sum()} videos={len(set(videos))}; "
      f"eval pairs={len(yev)} real={yev.sum()}")

PARAMS = dict(objective="binary", learning_rate=0.05, num_leaves=15, min_data_in_leaf=50,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
              is_unbalance=True, verbosity=-1, num_threads=4)

# grouped 4-fold CV by video for an honest AUC
uv = sorted(set(videos))
rng = np.random.default_rng(0)
rng.shuffle(uv)
folds = np.array_split(np.array(uv), 4)


def auc(yt, ys):
    o = np.argsort(ys)
    r = np.empty(len(ys))
    r[o] = np.arange(len(ys))
    p = yt == 1
    return (r[p].sum() - p.sum() * (p.sum() - 1) / 2) / max(1, p.sum() * (~p).sum())


aucs = []
for k, vf in enumerate(folds):
    m = np.isin(videos, vf)
    d_tr = lgb.Dataset(Xtr[~m], label=ytr[~m])
    bst = lgb.train(PARAMS, d_tr, num_boost_round=300)
    s = bst.predict(Xtr[m])
    a = auc(ytr[m], s)
    aucs.append(a)
    print(f"fold {k}: val pairs={int(m.sum())} real={int(ytr[m].sum())} auc={a:.4f}")
print(f"grouped CV AUC: {np.mean(aucs):.4f} +- {np.std(aucs):.4f}")

bst = lgb.train(PARAMS, lgb.Dataset(Xtr, label=ytr), num_boost_round=300)
imp = sorted(zip(FEATS + ["is_steal"], bst.feature_importance("gain"), strict=True), key=lambda t: -t[1])
print("feature gain:", [(f, round(float(g), 1)) for f, g in imp])

ev_scores = bst.predict(Xev)
out = ev.select("dataset", "parent_id", "orphan_id", "kind", "real").with_columns(
    pl.Series("gbdt", ev_scores))
out.write_csv("/kaggle/working/pairs_eval_scored.csv")
bst.save_model("/kaggle/working/div_gbdt.txt")
print("saved")
