"""Build the E6 division patch dataset from all 199 train videos.

Positives: 3D patches around each GT division parent at (t, t+1).
Negatives: (a) random non-dividing GT nodes (tracked cells, definitely not
dividing at t), (b) GT track-start nodes at t>=1 (appearance events that are
NOT division daughters -- the confuser class for orphan adoption).

Output: patches.npz with X (N, 2, PZ, PY, PX) uint16, y, meta CSV.
Patch: Z half 2 (5 slices ~8.1um), XY half 12 (25px ~10.2um).
"""
import csv
import json
from pathlib import Path

import numpy as np
import zarr

INPUT = Path("/kaggle/input")
COMP = next(p for p in INPUT.iterdir() if (p / "train").exists())
TRAIN = COMP / "train"
RZ, RXY = 2, 12
NEG_PER_VIDEO = 12
RNG = np.random.default_rng(20260824)


def read_geff(path: Path):
    g = zarr.open(str(path), mode="r")
    nodes = {k: np.asarray(g[f"nodes/props/{k}/values"]) for k in ("t", "z", "y", "x")}
    ids = np.asarray(g["nodes/ids"])
    edges = np.asarray(g["edges/ids"])  # (E, 2) source,target global ids
    return ids, nodes, edges


def extract(vol, t, z, y, x):
    """(2, 2*RZ+1, 2*RXY+1, 2*RXY+1) patch at t and t+1, zero-padded."""
    T = vol.shape[0]
    out = np.zeros((2, 2 * RZ + 1, 2 * RXY + 1, 2 * RXY + 1), dtype=np.uint16)
    for i, tt in enumerate((t, min(t + 1, T - 1))):
        frame = np.asarray(vol[tt])  # (Z, Y, X)
        z0, y0, x0 = int(round(z)) - RZ, int(round(y)) - RXY, int(round(x)) - RXY
        zs, ys, xs = max(0, z0), max(0, y0), max(0, x0)
        ze, ye, xe = min(frame.shape[0], z0 + 2 * RZ + 1), min(frame.shape[1], y0 + 2 * RXY + 1), min(frame.shape[2], x0 + 2 * RXY + 1)
        out[i, zs - z0:ze - z0, ys - y0:ye - y0, xs - x0:xe - x0] = frame[zs:ze, ys:ye, xs:xe]
    return out

X, y, meta = [], [], []
videos = sorted(TRAIN.glob("*.geff"))
print(f"{len(videos)} geffs")
for gi, geff in enumerate(videos):
    stem = geff.name[:-5]
    zarr_path = TRAIN / f"{stem}.zarr"
    if not zarr_path.exists():
        continue
    ids, nd, edges = read_geff(geff)
    id2idx = {int(v): i for i, v in enumerate(ids)}
    out_deg, in_deg = {}, {}
    for s, tgt in edges:
        out_deg[int(s)] = out_deg.get(int(s), 0) + 1
        in_deg[int(tgt)] = in_deg.get(int(tgt), 0) + 1
    vol = zarr.open(str(zarr_path), mode="r")["0"]

    def node_pos(nid):
        i = id2idx[nid]
        return int(nd["t"][i]), float(nd["z"][i]), float(nd["y"][i]), float(nd["x"][i])

    # positives: dividing parents
    pos_ids = [int(n) for n, d in out_deg.items() if d == 2]
    for nid in pos_ids:
        t, z, yy, xx = node_pos(nid)
        X.append(extract(vol, t, z, yy, xx)); y.append(1)
        meta.append((stem, nid, t, "div_parent"))
    # negatives (a): random tracked non-dividing nodes with a child (mid-track)
    cand_a = [int(n) for n, d in out_deg.items() if d == 1]
    for nid in RNG.choice(cand_a, size=min(NEG_PER_VIDEO, len(cand_a)), replace=False):
        t, z, yy, xx = node_pos(int(nid))
        X.append(extract(vol, t, z, yy, xx)); y.append(0)
        meta.append((stem, int(nid), t, "midtrack"))
    # negatives (b): track starts at t>=1 (appearances, adoption confusers)
    cand_b = [int(n) for n in ids if int(n) not in in_deg and node_pos(int(n))[0] >= 1 and int(n) in out_deg]
    for nid in RNG.choice(cand_b, size=min(6, len(cand_b)), replace=False) if cand_b else []:
        t, z, yy, xx = node_pos(int(nid))
        X.append(extract(vol, max(0, t - 1), z, yy, xx)); y.append(0)  # centered a frame BEFORE appearance
        meta.append((stem, int(nid), t, "trackstart"))
    if gi % 20 == 0:
        print(f"[{gi}/{len(videos)}] {stem}: total={len(y)} pos={sum(y)}")

X = np.stack(X); y = np.array(y, dtype=np.int8)
print(f"dataset: X={X.shape} pos={int(y.sum())} neg={int((1-y).sum())}")
np.savez_compressed("/kaggle/working/div_patches.npz", X=X, y=y)
with open("/kaggle/working/meta.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["stem", "node_id", "t", "kind"]); w.writerows(meta)
json.dump({"RZ": RZ, "RXY": RXY, "n": len(y), "pos": int(y.sum())}, open("/kaggle/working/build_info.json", "w"))
print("done")
