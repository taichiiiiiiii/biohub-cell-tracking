#!/usr/bin/env python3
"""Prepare, execute, seal, or independently verify one fixed ST-R3 prerequisite."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from biohub.st_r3_prerequisites import (
    PrerequisiteError,
    canonical_json,
    execute,
    prepare,
    seal,
    validate_prerequisite_receipt,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise PrerequisiteError(f"invalid arguments: {message}")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "execute", "seal", "verify"))
    parser.add_argument("--kind", required=True, choices=("e23", "base1"))
    parser.add_argument("--run-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        run_dir = Path(args.run_dir)
        if args.action == "prepare":
            result = prepare(args.kind, run_dir, REPO_ROOT)
        elif args.action == "execute":
            result = execute(args.kind, run_dir, REPO_ROOT)
        elif args.action == "seal":
            result = seal(args.kind, run_dir, REPO_ROOT)
        else:
            receipt_name = "E23_PARITY_RECEIPT.json" if args.kind == "e23" else "BASE1_NON_REGRESSION_RECEIPT.json"
            result = validate_prerequisite_receipt(run_dir / receipt_name, args.kind, REPO_ROOT)
        print(canonical_json(result).decode(), end="")
        return 0 if result.get("status") in {"PREPARED", "PASS"} else 1
    except Exception as error:
        message = str(error).replace("\n", " ")[:240]
        print(
            json.dumps(
                {"error": type(error).__name__, "message": message, "status": "FAIL"},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
