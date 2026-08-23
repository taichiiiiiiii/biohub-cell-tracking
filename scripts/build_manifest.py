#!/usr/bin/env python
"""Enumerate every competition file (name, size) into data/manifest.csv.

The Kaggle CLI paginates; this walks every page. Takes ~2-3 minutes for the
~25k chunk files of this competition. Re-run only if the dataset changes.
"""
from __future__ import annotations

import csv
import re
import subprocess
import sys
from pathlib import Path

COMPETITION = "biohub-cell-tracking-during-development"
OUT = Path(__file__).resolve().parent.parent / "data" / "manifest.csv"


def main() -> None:
    token: str | None = None
    rows: list[tuple[str, int]] = []
    page = 0
    while True:
        cmd = ["kaggle", "competitions", "files", COMPETITION, "--page-size", "1000", "-v"]
        if token:
            cmd += ["--page-token", token]
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
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
