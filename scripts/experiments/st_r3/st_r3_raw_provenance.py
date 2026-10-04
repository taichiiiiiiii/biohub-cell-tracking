#!/usr/bin/env python3
"""Build or independently verify the fixed ST-R3 legacy raw-provenance receipts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from biohub.st_r3_raw_provenance import (  # noqa: E402
    RawProvenanceError,
    build_raw_provenance,
    canonical_json_bytes,
    verify_raw_provenance,
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise RawProvenanceError(f"invalid arguments: {message}")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="atomically publish a fresh fixed receipt bundle")
    build.add_argument("--run-dir", required=True, type=Path)
    verify = subparsers.add_parser("verify", help="independently rehash and validate a receipt bundle")
    verify.add_argument("--run-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        if arguments.command == "build":
            result = build_raw_provenance(arguments.run_dir)
        elif arguments.command == "verify":
            result = verify_raw_provenance(arguments.run_dir)
        else:  # pragma: no cover - argparse enforces the closed command set
            raise RawProvenanceError("unsupported command")
        sys.stdout.buffer.write(canonical_json_bytes(result))
        return 0
    except Exception as error:
        failure = {"error": type(error).__name__, "status": "FAIL"}
        sys.stderr.buffer.write(canonical_json_bytes(failure))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
