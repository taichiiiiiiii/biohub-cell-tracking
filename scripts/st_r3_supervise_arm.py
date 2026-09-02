#!/usr/bin/env python
"""Supervise and seal one frozen ST-R3 production arm."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from biohub.public_postproc.production_supervisor import (  # noqa: E402
    SupervisorSpec,
    supervise_arm,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm-name", required=True, choices=("baseline", "dry_run", "candidate"))
    parser.add_argument("--geff-dir", required=True, type=Path)
    parser.add_argument("--test-dir", required=True, type=Path)
    parser.add_argument("--deepcenter-checkpoint", required=True, type=Path)
    parser.add_argument("--deepcenter-manifest", required=True, type=Path)
    parser.add_argument("--expected-effective-config-sha256", required=True)
    parser.add_argument("--final-dir", required=True, type=Path)
    parser.add_argument("--timeout-seconds", required=True, type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = supervise_arm(
        SupervisorSpec(
            arm_name=args.arm_name,
            geff_dir=args.geff_dir,
            test_dir=args.test_dir,
            deepcenter_checkpoint=args.deepcenter_checkpoint,
            deepcenter_manifest=args.deepcenter_manifest,
            expected_effective_config_sha256=args.expected_effective_config_sha256,
            final_dir=args.final_dir,
            timeout_seconds=args.timeout_seconds,
        )
    )
    print(
        json.dumps(
            {
                "success": result.success,
                "arm_name": result.arm_name,
                "child_pid": result.child_pid,
                "staging_dir": None if result.staging_dir is None else str(result.staging_dir),
                "final_dir": str(result.final_dir),
                "receipt_path": None if result.receipt_path is None else str(result.receipt_path),
                "holds": list(result.holds),
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
