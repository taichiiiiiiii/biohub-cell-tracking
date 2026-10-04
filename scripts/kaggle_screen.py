#!/usr/bin/env python3
"""Run the fixed local-only Kaggle screen; this command never submits."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from biohub.kaggle_screen import (  # noqa: E402
    ScreenError,
    execute_arm,
    generate_screen,
    score_screen,
)


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ScreenError(f"invalid arguments: {message}")


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="run public4 parity and the three label-blind EVAL36 arms")
    generate.add_argument("--run-id", required=True)
    score = commands.add_parser("score", help="score one sealed screen in a separate process")
    score.add_argument("--run-id", required=True)
    score.add_argument("--generation-seal-sha256", required=True)
    arm = commands.add_parser("_arm", help=argparse.SUPPRESS)
    arm.add_argument("--run-id", required=True)
    arm.add_argument("--arm-name", required=True, choices=("public4_parity", "dry_run", "baseline", "candidate"))
    arm.add_argument("--control-sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "generate":
            result = generate_screen(args.run_id)
            payload = {
                "status": result.status,
                "run_dir": str(result.run_dir),
                "generation_seal_sha256": result.seal_sha256,
                "submission_permitted": False,
            }
        elif args.command == "score":
            result = score_screen(args.run_id, args.generation_seal_sha256)
            payload = {
                "status": result.status,
                "run_dir": str(result.run_dir),
                "first_failure": result.first_failure,
                "submission_permitted": False,
            }
        elif args.command == "_arm":
            payload = execute_arm(args.run_id, args.arm_name, args.control_sha256)
        else:  # pragma: no cover
            raise ScreenError("unsupported command")
        print(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {"status": "SCREEN_ERROR", "error_type": type(exc).__name__, "submission_permitted": False},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
