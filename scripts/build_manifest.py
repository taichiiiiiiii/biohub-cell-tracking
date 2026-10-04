#!/usr/bin/env python
"""Enumerate every competition file (name, size) into data/manifest.csv.

The Kaggle CLI paginates (200 files/page); this walks every page. Takes ~10
minutes for the ~25k files (125 pages) of this competition. Re-run only if the
dataset changes.
"""
from __future__ import annotations

import csv
import re
import subprocess
import sys
import time
from pathlib import Path

COMPETITION = "biohub-cell-tracking-during-development"
OUT = Path(__file__).resolve().parent.parent / "data" / "manifest.csv"
MAX_ATTEMPTS = 6


def run_page(cmd: list[str], page: int) -> str:
    """Run one Kaggle page request, retrying transient CLI/API failures."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            return proc.stdout
        if attempt == MAX_ATTEMPTS:
            detail = next(
                (line.strip() for line in reversed(proc.stderr.splitlines()) if line.strip()),
                f"Kaggle CLI exited with status {proc.returncode}",
            )
            raise SystemExit(
                f"page {page} failed after {MAX_ATTEMPTS} attempts: {detail}"
            )
        delay = 2 ** (attempt - 1)
        print(
            f"page {page}: Kaggle request failed; retry {attempt}/{MAX_ATTEMPTS} "
            f"in {delay}s",
            file=sys.stderr,
        )
        time.sleep(delay)
    raise AssertionError("unreachable")


def main() -> None:
    token: str | None = None
    rows: list[tuple[str, int]] = []
    page = 0
    while True:
        cmd = ["kaggle", "competitions", "files", COMPETITION, "--page-size", "1000", "-v"]
        if token:
            cmd += ["--page-token", token]
        out = run_page(cmd, page + 1)
        m = re.search(r"Next Page Token = (\S+)", out)
        for line in out.splitlines():
            if not line or line.startswith("Next Page") or line.startswith("name,"):
                continue
            parts = line.rsplit(",", 2)
            if len(parts) == 3:
                rows.append((parts[0], int(parts[1])))
        page += 1
        print(f"page {page}: {len(rows)} files so far", file=sys.stderr)
        if not m:
            break
        token = m.group(1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "size"])
        w.writerows(rows)
    print(f"wrote {len(rows)} rows, {sum(s for _, s in rows) / 1e9:.2f} GB -> {OUT}")


if __name__ == "__main__":
    main()
