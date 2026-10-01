"""Single-pass recovery of the fixed 12-video acquisition; no automatic retries.

Qwen draft, corrected against the existing downloader by the parent. Run with
python -m scripts.acquire_frozen_association --receipt-dir <new absolute path>.
"""
import argparse
import contextlib
import hashlib
import io
import json
import re
import stat
from datetime import UTC, datetime
from pathlib import Path

from biohub.training_history import atomic_write_json, sha256_file
from scripts import download_data as dd

PLAN_REL = "analysis/frozen_association_acquisition.json"
PLAN_SHA = "6ae8a69d0856390d1590108b6350d1059b6d7875c6efc5923265f4de36dfcb14"
PRIOR_REL = "outputs/local/frozen_association_acquisition_20260922/failed.json"
CLASSES = {"auth", "forbidden", "timeout", "rate-limit", "disk-full", "dns",
           "integrity", "cleanup", "exception", "unknown"}


def classify(status):
    match = re.match(r"^FAIL class=([a-z-]+)(?:\s|$)", status)
    value = match.group(1) if match else "unknown"
    return value if value in CLASSES else "unknown"


def now():
    return datetime.now(UTC).isoformat()


def inventory():
    plan_path = dd.ROOT / PLAN_REL
    if sha256_file(plan_path) != PLAN_SHA:
        raise ValueError("Plan drift")
    plan = json.loads(plan_path.read_text())
    stems = plan["train"] + plan["selection"]
    if len(stems) != 12 or len(set(stems)) != 12:
        raise ValueError("Invalid split")
    roots = {f"{stem}.{ext}" for stem in stems for ext in ("zarr", "geff")}
    selected = {}
    for name, size in dd.load_manifest().items():
        parts = Path(name).parts
        if len(parts) >= 3 and parts[0] == "train" and parts[1] in roots:
            if ".." in parts or type(size) is not int or size < 0:
                raise ValueError("Invalid manifest entry")
            selected[name] = size
    digest = hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if (len(selected) != plan["expected_files"] or sum(selected.values()) != plan["expected_bytes"]
            or digest != plan["path_size_inventory_sha256"]):
        raise ValueError("Inventory mismatch")
    return dict(sorted(selected.items()))


def exact_file(name, size):
    target = dd.DATA / name
    if target.absolute() != target.resolve(strict=False):
        raise ValueError("Symlink or path alias in selected data")
    try:
        info = target.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Nonregular selected data")
    return info.st_size == size


def recover(receipt_dir):
    selected = inventory()  # Before receipt creation and before any request.
    prior = dd.ROOT / PRIOR_REL
    prior_sha = sha256_file(prior)
    receipt = Path(receipt_dir).absolute()
    base = (dd.ROOT / "outputs/local").absolute()
    if not receipt.is_relative_to(base) or receipt == base or receipt != receipt.resolve(strict=False):
        raise ValueError("Invalid receipt location")
    receipt.mkdir(parents=True, exist_ok=False)
    atomic_write_json(receipt / "started.json", {
        "started_at": now(), "plan_sha256": PLAN_SHA, "prior_failure_path": PRIOR_REL,
        "prior_failure_sha256": prior_sha, "attempts_per_file": 1,
        "reason": "Explicit recovery of interrupted acquisition; original failure cause unrecorded",
    })
    verified = 0
    name = None
    failure = "unknown"
    original_attempts = dd.MAX_TIMEOUT_ATTEMPTS
    dd.MAX_TIMEOUT_ATTEMPTS = 1
    try:
        with dd.single_run_lock():
            # Check all selected paths before the first network request.
            pending = [key for key, size in selected.items() if not exact_file(key, size)]
            verified = len(selected) - len(pending)
            print(json.dumps({"verified": verified, "pending": len(pending)}), flush=True)
            for name in pending:
                if sha256_file(dd.ROOT / PLAN_REL) != PLAN_SHA:
                    raise ValueError("Plan drift")
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    returned, status = dd.fetch(name, selected[name])
                if returned != name or status not in {"ok", "skip"}:
                    failure = classify(status)
                    raise RuntimeError("Download failed")
                if not exact_file(name, selected[name]):
                    failure = "integrity"
                    raise ValueError("Size mismatch")
                verified += 1
                if verified % 10 == 0:
                    print(json.dumps({"verified": verified, "total": len(selected)}), flush=True)
            files = []
            for name, size in selected.items():
                if not exact_file(name, size):
                    failure = "integrity"
                    raise ValueError("Final size mismatch")
                files.append({"path": name, "bytes": size, "sha256": sha256_file(dd.DATA / name)})
            if sha256_file(dd.ROOT / PLAN_REL) != PLAN_SHA:
                raise ValueError("Final plan drift")
            atomic_write_json(receipt / "files.json", files)
            atomic_write_json(receipt / "completed.json", {
                "finished_at": now(), "plan_sha256": PLAN_SHA, "files": len(files),
                "bytes": sum(selected.values()), "files_manifest_sha256": sha256_file(receipt / "files.json"),
                "status": "ACQUIRED_SIZE_CHECKED_LOCALLY_HASHED", "provider_content_hash_verified": False,
                "semantic_gt_inspected": False,
            })
        print(json.dumps({"state": "completed", "files": len(files)}), flush=True)
        return 0
    except Exception:
        atomic_write_json(receipt / "failed.json", {
            "finished_at": now(), "plan_sha256": PLAN_SHA, "verified": verified,
            "path": name if name in selected else None, "failure_class": failure, "retry": False,
        })
        print(json.dumps({"state": "failed", "failure_class": failure, "verified": verified}), flush=True)
        return 1
    finally:
        dd.MAX_TIMEOUT_ATTEMPTS = original_attempts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt-dir", required=True)
    args = parser.parse_args()
    try:
        return recover(args.receipt_dir)
    except Exception:
        print('{"state":"preflight_failed","retry":false}', flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
