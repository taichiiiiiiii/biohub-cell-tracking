#!/usr/bin/env python
"""Download a public kernel's output submission.csv and score it with the official metric.

The 4 public test clips are dummies with GT in data/train, so this is an
in-sample check of what a notebook actually produces — useful to verify a
pipeline is clean and to compare notebooks on equal footing. It is NOT a
hidden-test estimate.

    uv run python scripts/score_kernel_output.py yusuketogashi/clean-approach-lightweight-local-cv-no-hack
    uv run python scripts/score_kernel_output.py <ref> [<ref> ...] --out outputs/public_nb
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from biohub.evaluate import score_submission  # noqa: E402


def fetch(ref: str, out_dir: Path) -> Path | None:
    dest = out_dir / ref.replace("/", "__")
    dest.mkdir(parents=True, exist_ok=True)
    csv = dest / "submission.csv"
    if not csv.exists():
        r = subprocess.run(["kaggle", "kernels", "output", ref, "-p", str(dest)], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  {ref}: kaggle output failed: {r.stderr.strip()[-200:]}")
            return None
    if not csv.exists():
        found = sorted(dest.rglob("submission*.csv"))
        if not found:
            print(f"  {ref}: no submission csv in output ({[p.name for p in dest.iterdir()]})")
            return None
        csv = found[0]
    return csv


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("refs", nargs="+")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs" / "public_nb")
    ap.add_argument("--gt-dir", type=Path, default=ROOT / "data" / "train")
    args = ap.parse_args()

    rows = []
    for ref in args.refs:
        print(f"== {ref}")
        csv = fetch(ref, args.out)
        if csv is None:
            continue
        try:
            summary, per = score_submission(csv, args.gt_dir, verbose=True)
        except Exception as exc:  # malformed CSV etc. -> report, keep going
            print(f"  {ref}: scoring failed: {type(exc).__name__}: {exc}")
            rows.append({"ref": ref, "error": str(exc)[:120]})
            continue
        n_nodes = sum(r["num_pred_nodes"] for r in per)
        rows.append({"ref": ref, "score": summary["score"], "adj_edge_J": summary["adj_edge_jaccard"],
                     "edge_J": summary["edge_jaccard"], "div_J": summary["division_jaccard"],
                     "node_recall": summary["node_recall"], "n_pred_nodes": n_nodes, "n_datasets": summary["n"]})
        (args.out / (ref.replace("/", "__") + ".json")).write_text(
            json.dumps({"summary": summary, "per_dataset": per}, indent=2, default=float))

    print("\n| ref | score | adj_edge_J | edge_J | div_J | node_recall | n_pred_nodes |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        if "error" in r:
            print(f"| {r['ref']} | ERROR: {r['error']} | | | | | |")
        else:
            print(f"| {r['ref']} | {r['score']:.4f} | {r['adj_edge_J']:.4f} | {r['edge_J']:.4f} | "
                  f"{r['div_J']:.4f} | {r['node_recall']:.4f} | {r['n_pred_nodes']} |")


if __name__ == "__main__":
    main()
