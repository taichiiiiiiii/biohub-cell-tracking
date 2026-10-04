#!/usr/bin/env python3
"""Offline, fail-closed verifier for a new-training run directory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from biohub.training_history import trusted_pytorch_checkpoint_metadata_loader, verify_training_run


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="immutable run directory")
    parser.add_argument(
        "--trusted-pytorch-checkpoints",
        action="store_true",
        help="load real .pt files with torch.load(weights_only=True); torch must be installed",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    loader = trusted_pytorch_checkpoint_metadata_loader if args.trusted_pytorch_checkpoints else None
    report = verify_training_run(args.run_dir, checkpoint_metadata_loader=loader)
    print(json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
