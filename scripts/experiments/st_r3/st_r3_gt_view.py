#!/usr/bin/env python3
"""Build, verify, or import the fixed sealed ST-R3 EVAL36 GT view."""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from biohub.st_r3_gt_view import (  # noqa: E402
    GTViewError,
    build_gt_view,
    canonical_json_bytes,
    import_gt_view,
    verify_gt_view,
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise GTViewError(f"invalid arguments: {message}")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--run-id", required=True)
    build.add_argument("--preregistration-sha256", required=True)
    build.add_argument("--generation-manifest-sha256", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--receipt-sha256", required=True)
    import_command = commands.add_parser("import")
    import_command.add_argument("--run-id", required=True)
    import_command.add_argument("--generation-manifest-sha256", required=True)
    import_command.add_argument("--source-receipt-sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "build":
            result = build_gt_view(args.run_id, args.preregistration_sha256, args.generation_manifest_sha256)
        elif args.command == "verify":
            result = verify_gt_view(args.run_id, args.receipt_sha256)
        elif args.command == "import":
            result = import_gt_view(args.run_id, args.generation_manifest_sha256, args.source_receipt_sha256)
        else:  # pragma: no cover
            raise GTViewError("unsupported command")
        sys.stdout.buffer.write(canonical_json_bytes(dataclasses.asdict(result)))
        return 0
    except Exception as exc:
        sys.stderr.buffer.write(canonical_json_bytes({"error": type(exc).__name__, "status": "FAIL"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
