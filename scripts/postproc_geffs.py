#!/usr/bin/env python
"""Run the ported public-notebook post-processing stack over prediction geffs.

Applies a named config profile: ``base1`` (default; the
``biohub_132_clean_short_track_rescue_lightcv_nohack`` preset that produced
``outputs/kaggle/base1_v1/submission.csv``, score 0.8890) or ``e23`` (the
submitted E23 notebook's effective settings, public LB 0.924). Override
individual ``BIOHUB_*`` knobs with repeated ``--set NAME=VALUE``; overrides
always win over the selected profile.

    uv run python scripts/postproc_geffs.py \\
        --geff-dir outputs/kaggle/base1_v1/tracking_repo/predictions/unknown/unet_transformer/split_0 \\
        --out outputs/port_check/submission.csv

    uv run python scripts/postproc_geffs.py --geff-dir <dir> --out <csv> --profile e23

    uv run python scripts/postproc_geffs.py --geff-dir <dir> --out <csv> \\
        --set BIOHUB_GAP_CLOSE_UM=7.0 --set BIOHUB_OUTPUT_MIN_TRACK_LEN=4

Checkpoint mode -- for sweeping BIOHUB_OUTPUT_LINEFIT_* without redoing the
expensive motion-relink / gap-close / safe-division passes, run once with
``--save-prelinefit`` (topology-only knobs must match the sweep you intend to
run) and then use ``scripts/relinefit.py`` to iterate:

    uv run python scripts/postproc_geffs.py --geff-dir <dir> \\
        --save-prelinefit outputs/port_check/prelinefit
    uv run python scripts/relinefit.py --prelinefit outputs/port_check/prelinefit \\
        --out outputs/port_check/submission.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from biohub.public_postproc.config import PROFILES, build_config, parse_set_overrides  # noqa: E402
from biohub.public_postproc.pipeline import run_postproc, save_prelinefit_checkpoint  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geff-dir", type=Path, required=True, help="directory of prediction *.geff files")
    ap.add_argument(
        "--test-dir", type=Path, default=ROOT / "data" / "test", help="zarr volumes for gap-refinement pixel lookups"
    )
    ap.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default="base1",
        help="named config profile: base1 (legacy default) or e23 (submitted E23 parity)",
    )
    ap.add_argument("--out", type=Path, default=None, dest="out_csv", help="submission CSV to write")
    ap.add_argument("--run-stats", type=Path, default=None, help="default: run_stats.csv next to --out")
    ap.add_argument(
        "--save-prelinefit",
        type=Path,
        default=None,
        metavar="DIR",
        help="checkpoint mode: run the stack up to (excluding) linefit smoothing and pickle "
        "one <dataset>.pkl + a manifest.json per dataset into DIR, instead of writing a CSV",
    )
    ap.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        dest="overrides",
        help="override one BIOHUB_* preset knob (repeatable); NAME may omit the BIOHUB_ prefix",
    )
    return ap


def main() -> None:
    args = build_parser().parse_args()

    if args.save_prelinefit is None and args.out_csv is None:
        raise SystemExit("need --out (normal mode) or --save-prelinefit DIR (checkpoint mode)")

    overrides = parse_set_overrides(args.overrides)
    try:
        cfg = build_config(overrides, test_dir=args.test_dir, profile=args.profile)
    except (KeyError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print(f"profile: {args.profile}")
    print(f"geff-dir: {args.geff_dir}")
    print(f"test-dir: {args.test_dir}")
    if overrides:
        print(f"overrides: {overrides}")

    if args.save_prelinefit is not None:
        if args.out_csv is not None:
            print("--out is ignored in --save-prelinefit checkpoint mode")
        manifest = save_prelinefit_checkpoint(args.geff_dir, args.save_prelinefit, cfg)
        print(f"datasets: {manifest['datasets']}")
        print(f"wrote pre-linefit checkpoint to {args.save_prelinefit} ({len(manifest['datasets'])} datasets)")
        return

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
