#!/usr/bin/env python
"""Create one fresh, label-blind ST-R3 preregistration."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from biohub.st_r3_generation import (  # noqa: E402
    GenerationFailure,
    PreregistrationSpec,
    canonical_json_bytes,
    preregister,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--raw-geff-dir", required=True, type=Path)
    parser.add_argument("--image-view", required=True, type=Path)
    parser.add_argument("--image-ready-receipt", required=True, type=Path)
    parser.add_argument("--image-import-receipt", required=True, type=Path)
    parser.add_argument("--deepcenter-checkpoint", required=True, type=Path)
    parser.add_argument("--deepcenter-manifest", required=True, type=Path)
    parser.add_argument("--e23-parity-receipt", required=True, type=Path)
    parser.add_argument("--base1-receipt", required=True, type=Path)
    parser.add_argument("--primary-raw-provenance-receipt", required=True, type=Path)
    parser.add_argument("--secondary-raw-provenance-receipt", required=True, type=Path)
    parser.add_argument("--target-resources", required=True, type=Path)
    parser.add_argument("--gt-inventory", required=True, type=Path)
    parser.add_argument("--timeout-seconds", required=True, type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        path = preregister(
            PreregistrationSpec(
                run_dir=args.run_dir,
                raw_geff_dir=args.raw_geff_dir,
                image_view=args.image_view,
                image_ready_receipt=args.image_ready_receipt,
                image_import_receipt=args.image_import_receipt,
                deepcenter_checkpoint=args.deepcenter_checkpoint,
                deepcenter_manifest=args.deepcenter_manifest,
                e23_parity_receipt=args.e23_parity_receipt,
                base1_receipt=args.base1_receipt,
                primary_raw_provenance_receipt=args.primary_raw_provenance_receipt,
                secondary_raw_provenance_receipt=args.secondary_raw_provenance_receipt,
                target_resources=args.target_resources,
                gt_inventory=args.gt_inventory,
                timeout_seconds=args.timeout_seconds,
            ),
            repo_root=ROOT,
        )
    except GenerationFailure as exc:
        print(canonical_json_bytes({"status": "ERROR", "code": exc.code}).decode(), end="")
        return 2
    data = path.read_bytes()
    print(
        json.dumps(
            {
                "status": "PREREGISTERED_WITH_MANDATORY_HOLDS",
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
