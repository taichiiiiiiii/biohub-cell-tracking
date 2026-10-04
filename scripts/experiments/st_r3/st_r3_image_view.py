#!/usr/bin/env python3
"""Build or independently verify the fixed ST-R3 EVAL36 image-only view."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from biohub.st_r3_image_view import (  # noqa: E402
    ImageViewError,
    build_image_view,
    canonical_json_bytes,
    verify_image_view,
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ImageViewError(f"invalid arguments: {message}")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="build and atomically publish a fresh image-only view")
    build.add_argument("--run-dir", required=True, type=Path)
    verify = subparsers.add_parser("verify", help="independently rehash a published image-only view")
    verify.add_argument("--run-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        if arguments.command == "build":
            result = build_image_view(arguments.run_dir)
        elif arguments.command == "verify":
            result = verify_image_view(arguments.run_dir)
        else:  # pragma: no cover - argparse enforces the closed command set
            raise ImageViewError("unsupported command")
        sys.stdout.buffer.write(canonical_json_bytes(result))
        return 0
    except Exception as error:
        failure = {"error": type(error).__name__, "status": "FAIL"}
        sys.stderr.buffer.write(canonical_json_bytes(failure))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
