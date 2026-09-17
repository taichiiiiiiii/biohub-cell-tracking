#!/usr/bin/env python3
"""E26 preregistration, serial generation and separate staged official scoring."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from biohub.e26_screen import (  # noqa: E402
    E26Error,
    capture_generation_inputs,
    generate_screen,
    preregister_screen,
    read_json_bound,
    run_generation_child,
    run_score_child,
    score_screen,
    verify_generation_inputs,
    verify_generation_seal,
    verify_registration_pair,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify-inputs", help="read-only canonical raw/image/weight acquisition verification")
    register = sub.add_parser("preregister", help="opaque registration only; not execution authorization")
    register.add_argument("--run-id", required=True)
    register.add_argument("--budget", required=True, type=Path)
    register.add_argument("--budget-sha256", required=True)
    for command in ("verify-registration", "generate"):
        verify = sub.add_parser(command, help="GT-free verification" if command.startswith("verify")
                               else "fresh sequential generation; requires accepted implementation and frozen budget")
        verify.add_argument("--public", required=True, type=Path)
        verify.add_argument("--public-sha256", required=True)
        verify.add_argument("--private-sha256", required=True)
    for command in ("verify-generation", "score"):
        seal = sub.add_parser(command, help="verify generation" if command.startswith("verify")
                              else "fresh staged official scoring; not submission authorization")
        seal.add_argument("--seal", required=True, type=Path)
        seal.add_argument("--seal-sha256", required=True)
        seal.add_argument("--public-sha256", required=True)
        seal.add_argument("--private-sha256", required=True)
    for command in ("_arm", "_score"):
        child = sub.add_parser(command, help="internal fresh-process entry; no fixture or bypass options")
        child.add_argument("--control", required=True, type=Path)
        child.add_argument("--control-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.command == "preregister":
            result = preregister_screen(args.run_id, read_json_bound(args.budget, args.budget_sha256))
        elif args.command == "_arm":
            result = run_generation_child(args.control, args.control_sha256)
        elif args.command == "_score":
            result = run_score_child(args.control, args.control_sha256)
        elif args.command == "score":
            result = score_screen(args.seal, expected_seal_sha256=args.seal_sha256,
                                  expected_public_sha256=args.public_sha256,
                                  expected_private_sha256=args.private_sha256)
        elif args.command == "generate":
            result = generate_screen(args.public, expected_public_sha256=args.public_sha256,
                                     expected_private_sha256=args.private_sha256)
        elif args.command == "verify-generation":
            value = verify_generation_seal(args.seal, expected_seal_sha256=args.seal_sha256,
                                           expected_public_sha256=args.public_sha256,
                                           expected_private_sha256=args.private_sha256)
            result = {"run_id": value["seal"]["run_id"], "status": "GENERATION_VERIFIED_NOT_SCORED",
                      "submission_authorized": False}
        elif args.command == "verify-registration":
            value = verify_registration_pair(
                args.public, expected_public_sha256=args.public_sha256,
                expected_private_sha256=args.private_sha256,
            )
            result = {"run_id": value["run_id"], "status": "REGISTRATION_VERIFIED", "submission_authorized": False}
        else:
            binding = capture_generation_inputs()
            verify_generation_inputs(binding)
            result = {"status": "INPUT_BYTES_VERIFIED", "submission_authorized": False,
                      "generation_complete": False, "scored": False}
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except E26Error as exc:
        print(f"E26 ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
