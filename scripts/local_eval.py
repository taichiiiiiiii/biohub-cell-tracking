#!/usr/bin/env python
"""Score a submission CSV against the ground truth in data/train (official metric, no torch).

    uv run python scripts/local_eval.py outputs/submission.csv
    uv run python scripts/local_eval.py outputs/submission.csv --gt-dir data/train --json outputs/score.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from biohub.evaluate import score_submission  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", type=Path)
    ap.add_argument("--gt-dir", type=Path, default=ROOT / "data" / "train")
    ap.add_argument("--max-distance", type=float, default=7.0)
    ap.add_argument("--json", type=Path, help="write summary + per-dataset rows here")
    args = ap.parse_args()

    summary, rows = score_submission(args.csv, args.gt_dir, max_distance=args.max_distance)
    print("\n=== Summary ===")
    print(
        f"n={summary['n']}  score={summary['score']:.4f}  "
        f"edge_jaccard={summary['edge_jaccard']:.4f}  adj_edge_jaccard={summary['adj_edge_jaccard']:.4f}  "
        f"division_jaccard={summary['division_jaccard']:.4f} "
        f"(TP={summary['division_tp']} FP={summary['division_fp']} FN={summary['division_fn']})  "
        f"node_recall={summary['node_recall']:.4f}"
    )
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"summary": summary, "per_dataset": rows}, indent=2, default=float))
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
