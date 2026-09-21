#!/usr/bin/env python
"""Execute one frozen ST-R3 post-processing arm as a fresh child process."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from biohub.public_postproc.production_adapter import ArmSpec, run_production_arm  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm-name", required=True, choices=("baseline", "dry_run", "candidate"))
    parser.add_argument("--geff-dir", required=True, type=Path)
    parser.add_argument("--test-dir", required=True, type=Path)
    parser.add_argument("--deepcenter-checkpoint", required=True, type=Path)
    parser.add_argument("--deepcenter-manifest", required=True, type=Path)
    parser.add_argument("--dataset", required=True, action="append", dest="datasets")
    parser.add_argument("--expected-effective-config-sha256", required=True)
    parser.add_argument("--staging-dir", required=True, type=Path)
    parser.add_argument("--event-fd", required=True, type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    spec = ArmSpec(
        arm_name=args.arm_name,
        geff_dir=args.geff_dir,
        test_dir=args.test_dir,
        deepcenter_checkpoint=args.deepcenter_checkpoint,
        deepcenter_manifest=args.deepcenter_manifest,
        datasets=tuple(args.datasets),
        expected_effective_config_sha256=args.expected_effective_config_sha256,
        staging_dir=args.staging_dir,
        event_fd=args.event_fd,
    )
    run_production_arm(spec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
