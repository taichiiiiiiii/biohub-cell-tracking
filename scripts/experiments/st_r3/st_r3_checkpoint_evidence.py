#!/usr/bin/env python3
"""Build or verify the fixed ST-R3 checkpoint-evidence receipt."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from biohub.st_r3_checkpoint_evidence import (  # noqa: E402
    CheckpointEvidenceError,
    build_checkpoint_evidence,
    canonical_json_bytes,
    verify_checkpoint_evidence,
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CheckpointEvidenceError(f"invalid arguments: {message}")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "verify"):
        child = commands.add_parser(command)
        child.add_argument("--run-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        result = (
            build_checkpoint_evidence(args.run_dir)
            if args.command == "build"
            else verify_checkpoint_evidence(args.run_dir)
        )
        sys.stdout.buffer.write(canonical_json_bytes(result))
        return 0
    except Exception as error:
        sys.stderr.buffer.write(canonical_json_bytes({"error": type(error).__name__, "status": "FAIL"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
