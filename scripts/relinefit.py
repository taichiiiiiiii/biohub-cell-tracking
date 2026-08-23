#!/usr/bin/env python
"""Apply linefit smoothing to a pre-linefit checkpoint and write the submission CSV.

Companion to ``scripts/postproc_geffs.py --save-prelinefit``: everything
before linefit smoothing (motion relink, gap close, safe divisions,
short-track filter/rescue -- i.e. final graph topology) is already baked
into the checkpoint, so only ``BIOHUB_OUTPUT_LINEFIT_*`` (or anything else
that only touches coordinates, not topology) needs to change between runs.

    uv run python scripts/postproc_geffs.py --geff-dir <geff-dir> \\
        --save-prelinefit outputs/port_check/prelinefit
    uv run python scripts/relinefit.py --prelinefit outputs/port_check/prelinefit \\
        --out outputs/port_check/submission.csv
    uv run python scripts/relinefit.py --prelinefit outputs/port_check/prelinefit --out outputs/sweep/w06.csv \\
        --set BIOHUB_OUTPUT_LINEFIT_WEIGHT=0.6 --set BIOHUB_OUTPUT_LINEFIT_WINDOW=3

With no --set overrides this reproduces the preset defaults
(BIOHUB_OUTPUT_LINEFIT_WEIGHT=0.8, BIOHUB_OUTPUT_LINEFIT_WINDOW=2), i.e. the
same submission.csv scripts/postproc_geffs.py would have written.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from biohub.public_postproc.config import build_config, parse_set_overrides  # noqa: E402
from biohub.public_postproc.pipeline import run_relinefit  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prelinefit", type=Path, required=True, dest="checkpoint_dir", help="dir from --save-prelinefit")
    ap.add_argument(
        "--test-dir", type=Path, default=ROOT / "data" / "test", help="unused by linefit itself; kept for config parity"
    )
    ap.add_argument("--out", type=Path, required=True, dest="out_csv", help="submission CSV to write")
    ap.add_argument("--run-stats", type=Path, default=None, help="default: run_stats.csv next to --out")
    ap.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        dest="overrides",
        help="override one BIOHUB_* preset knob (repeatable); NAME may omit the BIOHUB_ prefix. "
        "Only BIOHUB_OUTPUT_LINEFIT_* affects the result -- everything else was already applied "
        "when the checkpoint was saved.",
    )
    args = ap.parse_args()

    overrides = parse_set_overrides(args.overrides)
    try:
        cfg = build_config(overrides, test_dir=args.test_dir)
    except KeyError as exc:
        raise SystemExit(str(exc)) from exc

    print(f"prelinefit checkpoint: {args.checkpoint_dir}")
    if overrides:
        print(f"overrides: {overrides}")

    result = run_relinefit(
        checkpoint_dir=args.checkpoint_dir,
        out_csv=args.out_csv,
        cfg=cfg,
        run_stats_path=args.run_stats,
    )

    print(f"datasets: {result['datasets']}")
    print(f"wrote {args.out_csv} with {result['total_rows']:,} rows")
    print(f"node rows: {result['total_nodes']:,} | edge rows: {result['total_edges']:,}")
    run_stats_path = args.run_stats or args.out_csv.parent / "run_stats.csv"
    print(f"wrote {run_stats_path}")


if __name__ == "__main__":
    main()
