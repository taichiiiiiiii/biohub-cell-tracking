#!/usr/bin/env python
"""Download a *subset* of the competition data into data/.

The full dataset is ~87.6 GB (199 train videos); this machine has ~16 GB of
disk and 3.8 GB of RAM, so we never mirror it. Heavy work runs on Kaggle where
the data is mounted. Locally we keep:

  * sample_submission.csv
  * test/*.zarr            (4 videos, ~1.9 GB)  -- identical to 4 train videos
  * train/<name>.geff      (ground truth for every locally present video)
  * train/<name>.zarr      for the names passed with --train (optional)

Reads data/manifest.csv (see scripts/build_manifest.py). Skips files whose
size already matches the manifest, so re-running is cheap.

Usage:
    uv run python scripts/download_data.py                 # test + their GT
    uv run python scripts/download_data.py --train 6bba_c328f2fd 44b6_24264f12
    uv run python scripts/download_data.py --all-geffs          # + GT of all 199 train videos (~4k small files)
    uv run python scripts/download_data.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

COMPETITION = "biohub-cell-tracking-during-development"
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MANIFEST = DATA / "manifest.csv"

# GEFF needed by official/tests/test_metrics.py (official/data -> ../data symlink).
ALWAYS_GEFF = ("6bba_c328f2fd",)


def load_manifest() -> dict[str, int]:
    if not MANIFEST.exists():
        sys.exit(f"{MANIFEST} missing - run scripts/build_manifest.py first")
    with MANIFEST.open() as f:
        return {r["name"]: int(r["size"]) for r in csv.DictReader(f)}


def select(manifest: dict[str, int], train_names: list[str], all_geffs: bool = False) -> list[str]:
    test_names = sorted({n.split("/")[1][:-5] for n in manifest if n.startswith("test/") and ".zarr/" in n})
    geff_names = set(test_names) | set(train_names) | set(ALWAYS_GEFF)
    wanted: list[str] = ["sample_submission.csv"]
    for n in manifest:
        if n.startswith("test/"):
            wanted.append(n)
        elif n.startswith("train/"):
            stem, kind = n.split("/")[1].rsplit(".", 1)
            if kind == "geff" and (all_geffs or stem in geff_names):
                wanted.append(n)
            elif kind == "zarr" and stem in train_names:
                wanted.append(n)
    return wanted


def fetch(name: str, size: int) -> tuple[str, str]:
    dest = DATA / name
    if dest.exists() and dest.stat().st_size == size:
        return name, "skip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["kaggle", "competitions", "download", "-c", COMPETITION, "-f", name, "-p", str(dest.parent), "--force"]
    for attempt in range(6):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            break
        if "429" in (r.stderr + r.stdout):  # Kaggle rate limit: back off and retry
            time.sleep(15 * (attempt + 1))
            continue
        return name, f"FAIL rc={r.returncode}: {r.stderr.strip()[-200:]}"
    else:
        return name, "FAIL rate-limited (429) after 6 attempts"
    if not dest.exists() or dest.stat().st_size != size:
        return name, f"FAIL size mismatch (have {dest.stat().st_size if dest.exists() else 'none'}, want {size})"
    return name, "ok"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train", nargs="*", default=[], help="train video stems to fetch (zarr + geff)")
    ap.add_argument("--all-geffs", action="store_true", help="also fetch the GT .geff of every train video (tiny)")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    manifest = load_manifest()
    wanted = select(manifest, args.train, all_geffs=args.all_geffs)
    total = sum(manifest[n] for n in wanted)
    print(f"{len(wanted)} files, {total / 1e9:.2f} GB selected")
    if args.dry_run:
        for n in wanted[:20]:
            print("  ", n)
        if len(wanted) > 20:
            print(f"   ... (+{len(wanted) - 20})")
        return

    counts = {"ok": 0, "skip": 0, "fail": 0}
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = [ex.submit(fetch, n, manifest[n]) for n in wanted]
        for i, fut in enumerate(as_completed(futs), 1):
            name, status = fut.result()
            if status.startswith("FAIL"):
                counts["fail"] += 1
                failures.append(f"{name}: {status}")
            else:
                counts[status] += 1
            if i % 50 == 0 or i == len(futs):
                print(f"[{i}/{len(futs)}] ok={counts['ok']} skip={counts['skip']} fail={counts['fail']}", flush=True)
    for f in failures:
        print("  ", f)
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
