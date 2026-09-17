#!/usr/bin/env python
"""Run the fixed five-arm ST-R3 label-blind generation sequence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from biohub.st_r3_generation import GenerationFailure, generate  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--preregistration-sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = generate(args.run_dir, args.preregistration_sha256, repo_root=ROOT)
        value = {
            "status": result.status,
            "code": result.code,
            "run_dir": result.run_dir.relative_to(ROOT).as_posix(),
            "generation_manifest_sha256": result.generation_manifest_sha256,
            "hold_path": result.hold_path.relative_to(ROOT).as_posix(),
            "holds": list(result.holds),
        }
    except GenerationFailure as exc:
        value = {"status": "ERROR", "code": exc.code}
        print(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))
        return 2
    print(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 3 if result.status == "HOLD" else 0


if __name__ == "__main__":
    raise SystemExit(main())
