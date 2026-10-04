#!/usr/bin/env python
"""Hard-validate a submission.csv against the test zarr shapes, after a validator self-test.

    uv run python scripts/validate_submission.py outputs/x/submission.csv --test-dir data/test
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from biohub.validate import SubmissionError, self_test, test_shapes, validate_csv  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", type=Path)
    ap.add_argument("--test-dir", type=Path, default=ROOT / "data" / "test")
    args = ap.parse_args()
    shapes = test_shapes(args.test_dir)
    self_test(shapes)
    print(f"validator self-test: all canaries fired ({len(shapes)} test datasets)")
    try:
        report = validate_csv(args.csv, args.test_dir)
    except SubmissionError as exc:
        print(f"INVALID: {exc}")
        sys.exit(1)
    for name, r in report.items():
        print(f"  {name}: nodes={r['nodes']} edges={r['edges']} forks={r['forks']}")
    print("VALID")


if __name__ == "__main__":
    main()
