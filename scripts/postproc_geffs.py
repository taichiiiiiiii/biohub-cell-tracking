#!/usr/bin/env python
"""Run the ported public-notebook post-processing stack over prediction geffs.

Applies the ``biohub_132_clean_short_track_rescue_lightcv_nohack`` preset
(the config that produced ``outputs/kaggle/base1_v1/submission.csv``,
score 0.8890) as defaults; override individual ``BIOHUB_*`` knobs with
repeated ``--set NAME=VALUE``.

    uv run python scripts/postproc_geffs.py \\
        --geff-dir outputs/kaggle/base1_v1/tracking_repo/predictions/unknown/unet_transformer/split_0 \\
        --out outputs/port_check/submission.csv

    uv run python scripts/postproc_geffs.py --geff-dir <dir> --out <csv> \\
        --set BIOHUB_GAP_CLOSE_UM=7.0 --set BIOHUB_OUTPUT_MIN_TRACK_LEN=4
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from biohub.public_postproc.config import build_config  # noqa: E402
from biohub.public_postproc.pipeline import run_postproc  # noqa: E402


def _parse_set(pairs: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--set expects NAME=VALUE, got: {pair!r}")
        name, value = pair.split("=", 1)
        name = name.strip()
        if not name.startswith("BIOHUB_"):
            name = f"BIOHUB_{name}"
        overrides[name] = value.strip()
    return overrides


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geff-dir", type=Path, required=True, help="directory of prediction *.geff files")
    ap.add_argument("--test-dir", type=Path, default=ROOT / "data" / "test", help="zarr volumes for gap-refinement pixel lookups")
    ap.add_argument("--out", type=Path, required=True, dest="out_csv", help="submission CSV to write")
    ap.add_argument("--run-stats", type=Path, default=None, help="default: run_stats.csv next to --out")
    ap.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        dest="overrides",
        help="override one BIOHUB_* preset knob (repeatable); NAME may omit the BIOHUB_ prefix",
    )
    args = ap.parse_args()

    overrides = _parse_set(args.overrides)
    try:
        cfg = build_config(overrides, test_dir=args.test_dir)
    except KeyError as exc:
        raise SystemExit(str(exc)) from exc

    print(f"geff-dir: {args.geff_dir}")
    print(f"test-dir: {args.test_dir}")
    if overrides:
        print(f"overrides: {overrides}")

    result = run_postproc(
        geff_dir=args.geff_dir,
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
