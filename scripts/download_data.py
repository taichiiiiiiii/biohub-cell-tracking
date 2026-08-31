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
import errno
import fcntl
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

COMPETITION = "biohub-cell-tracking-during-development"
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MANIFEST = DATA / "manifest.csv"

DOWNLOAD_TIMEOUT_SECONDS = 300.0
HEARTBEAT_SECONDS = 30.0
PROCESS_POLL_SECONDS = 0.25
TERMINATE_GRACE_SECONDS = 5.0
MAX_TIMEOUT_ATTEMPTS = 2
TIMEOUT_RETRY_DELAY_SECONDS = 2.0

# GEFF needed by official/tests/test_metrics.py (official/data -> ../data symlink).
ALWAYS_GEFF = ("6bba_c328f2fd",)


class DownloadLockHeldError(RuntimeError):
    """Another downloader owns the data-directory advisory lock."""


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


@contextmanager
def single_run_lock() -> Iterator[None]:
    """Hold a non-blocking, process-scoped lock for mutations under data/."""
    DATA.mkdir(parents=True, exist_ok=True)
    lock_path = DATA / ".download_data.lock"
    with lock_path.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DownloadLockHeldError(f"another download is running (lock: {lock_path})") from error
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _classify_failure(output: str) -> str:
    lowered = output.lower()
    if "429" in lowered or "too many requests" in lowered or "rate limit" in lowered:
        return "rate-limit"
    if "enospc" in lowered or "no space left on device" in lowered:
        return "disk-full"
    if any(
        marker in lowered
        for marker in (
            "nameresolutionerror",
            "temporary failure in name resolution",
            "could not resolve host",
            "name or service not known",
            "nodename nor servname provided",
        )
    ):
        return "dns"
    if "403" in lowered or "forbidden" in lowered or "rules acceptance" in lowered:
        return "forbidden"
    if any(marker in lowered for marker in ("401", "unauthorized", "credential", "authentication", "api token")):
        return "auth"
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    return "unknown"


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    """Terminate a child and its descendants, escalating after a short grace."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + TERMINATE_GRACE_SECONDS
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(min(PROCESS_POLL_SECONDS, max(0.0, deadline - time.monotonic())))
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def _run_command(
    cmd: list[str],
    *,
    name: str,
    attempt: int,
    stop_event: threading.Event,
) -> tuple[int | None, str, bool]:
    """Run one Kaggle CLI process, returning (returncode, output, hard_timeout)."""
    started = time.monotonic()
    deadline = started + DOWNLOAD_TIMEOUT_SECONDS
    deadline_wall = datetime.now(UTC) + timedelta(seconds=DOWNLOAD_TIMEOUT_SECONDS)
    print(
        f"START path={name} attempt={attempt}/{MAX_TIMEOUT_ATTEMPTS} "
        f"deadline={deadline_wall.isoformat(timespec='seconds')}",
        flush=True,
    )
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stdout_file, tempfile.TemporaryFile(
        mode="w+", encoding="utf-8"
    ) as stderr_file:
        process = subprocess.Popen(
            cmd,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            start_new_session=True,
        )
        next_heartbeat = started + HEARTBEAT_SECONDS
        hard_timeout = False
        try:
            while process.poll() is None:
                now = time.monotonic()
                if stop_event.is_set():
                    _terminate_process_group(process)
                    break
                if now >= deadline:
                    hard_timeout = True
                    print(
                        f"TIMEOUT path={name} attempt={attempt}/{MAX_TIMEOUT_ATTEMPTS}; stopping process group",
                        flush=True,
                    )
                    _terminate_process_group(process)
                    break
                if now >= next_heartbeat:
                    print(
                        f"HEARTBEAT path={name} attempt={attempt}/{MAX_TIMEOUT_ATTEMPTS} "
                        f"elapsed={int(now - started)}s deadline_in={max(0, int(deadline - now))}s",
                        flush=True,
                    )
                    next_heartbeat = now + HEARTBEAT_SECONDS
                time.sleep(min(PROCESS_POLL_SECONDS, max(0.0, deadline - now)))
        except BaseException:
            if process.poll() is None:
                _terminate_process_group(process)
            raise
        stdout_file.seek(0)
        stderr_file.seek(0)
        output = stdout_file.read() + stderr_file.read()
        return process.poll(), output, hard_timeout


def _is_exact_regular_file(path: Path, size: int) -> bool:
    """Return true only for a non-symlink regular file of the expected size."""
    try:
        file_stat = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(file_stat.st_mode) and file_stat.st_size == size


def _ancestor_integrity_error(dest: Path) -> str | None:
    """Reject unsafe manifest paths and existing symlinks above the target."""
    try:
        relative_dest = dest.relative_to(DATA)
    except ValueError:
        return f"destination escapes data root: {dest}"
    if not relative_dest.parts or ".." in relative_dest.parts:
        return f"destination escapes data root: {dest}"

    relative_parent = relative_dest.parent
    current = DATA
    candidates = [current]
    for part in relative_parent.parts:
        current /= part
        candidates.append(current)
    for candidate in candidates:
        try:
            mode = candidate.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            return f"symlink ancestor path={candidate}"
    return None


def _cleanup_artifacts(staging: Path | None, ready: Path | None) -> list[str]:
    """Best-effort cleanup that reports every non-absence failure with its path."""
    errors: list[str] = []
    if ready is not None:
        try:
            ready.unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            errors.append(f"ready path={ready}: {type(error).__name__}: {error}")
    if staging is not None:
        try:
            shutil.rmtree(staging)
        except FileNotFoundError:
            pass
        except OSError as error:
            errors.append(f"staging path={staging}: {type(error).__name__}: {error}")
    return errors


def _status_with_cleanup(status: str, cleanup_errors: list[str]) -> str:
    if not cleanup_errors:
        return status
    return f"FAIL class=cleanup {'; '.join(cleanup_errors)}; prior={status}"


def _os_error_status(error: OSError) -> str:
    classification = "disk-full" if error.errno == errno.ENOSPC else "unknown"
    return f"FAIL class={classification}: {type(error).__name__}: {error}"


def fetch(name: str, size: int, stop_event: threading.Event | None = None) -> tuple[str, str]:
    """Fetch one manifest path atomically, preserving an existing target on failure."""
    stop_event = stop_event or threading.Event()
    dest = DATA / name
    if integrity_error := _ancestor_integrity_error(dest):
        return name, f"FAIL class=integrity: {integrity_error}"
    if _is_exact_regular_file(dest, size):
        return name, "skip"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{dest.name}.", suffix=".kaggle-staging", dir=dest.parent))
    except OSError as error:
        return name, _os_error_status(error)

    ready: Path | None = None
    try:
        cmd = [
            "kaggle",
            "competitions",
            "download",
            "-c",
            COMPETITION,
            "-f",
            name,
            "-p",
            str(staging),
            "--force",
        ]
        status = "FAIL class=unknown: download did not run"
        downloaded = staging / dest.name
        for attempt in range(1, MAX_TIMEOUT_ATTEMPTS + 1):
            if stop_event.is_set():
                status = "CANCELLED run stopping"
                break
            try:
                returncode, output, hard_timeout = _run_command(
                    cmd, name=name, attempt=attempt, stop_event=stop_event
                )
            except OSError as error:
                status = _os_error_status(error)
                break
            if stop_event.is_set():
                status = "CANCELLED run stopping"
                break
            if hard_timeout:
                classification = "timeout"
            elif returncode == 0:
                try:
                    downloaded_stat = downloaded.lstat()
                except FileNotFoundError:
                    status = f"FAIL class=integrity size mismatch (have none, want {size})"
                    break
                if not stat.S_ISREG(downloaded_stat.st_mode):
                    status = "FAIL class=integrity downloaded payload is not a regular file"
                    break
                if downloaded_stat.st_size != size:
                    status = f"FAIL class=integrity size mismatch (have {downloaded_stat.st_size}, want {size})"
                    break
                status = "ready"
                break
            else:
                classification = _classify_failure(output)
                detail = " ".join(output.strip().split())[-300:]
                if classification != "timeout":
                    status = f"FAIL class={classification} rc={returncode}: {detail}"
                    break

            if attempt == MAX_TIMEOUT_ATTEMPTS:
                status = f"FAIL class={classification} after {attempt} attempts"
                break
            print(
                f"RETRY path={name} class={classification} next_attempt={attempt + 1}/{MAX_TIMEOUT_ATTEMPTS}",
                flush=True,
            )
            stop_event.wait(TIMEOUT_RETRY_DELAY_SECONDS)

        if status != "ready":
            cleanup_errors = _cleanup_artifacts(staging, ready)
            return name, _status_with_cleanup(status, cleanup_errors)

        ready_fd, ready_name = tempfile.mkstemp(
            prefix=f".{dest.name}.", suffix=".kaggle-ready", dir=dest.parent
        )
        ready = Path(ready_name)
        os.close(ready_fd)
        os.replace(downloaded, ready)

        cleanup_errors = _cleanup_artifacts(staging, None)
        if cleanup_errors:
            ready_cleanup_errors = _cleanup_artifacts(None, ready)
            ready = None if not ready_cleanup_errors else ready
            all_cleanup_errors = cleanup_errors + ready_cleanup_errors
            return name, _status_with_cleanup("FAIL class=cleanup staging removal failed", all_cleanup_errors)
        staging = None

        os.replace(ready, dest)
        ready = None
        return name, "ok"
    except OSError as error:
        cleanup_errors = _cleanup_artifacts(staging, ready)
        return name, _status_with_cleanup(_os_error_status(error), cleanup_errors)
    except BaseException as error:
        cleanup_errors = _cleanup_artifacts(staging, ready)
        if cleanup_errors:
            cleanup_message = f"CLEANUP FAIL while handling {type(error).__name__}: {'; '.join(cleanup_errors)}"
            print(cleanup_message, file=sys.stderr, flush=True)
            if hasattr(error, "add_note"):
                error.add_note(cleanup_message)
        raise


def _record_result(
    name: str,
    status: str,
    counts: dict[str, int],
    failures: list[str],
) -> bool:
    """Record a result and return whether this classification must stop the run."""
    if status.startswith("FAIL"):
        counts["fail"] += 1
        failures.append(f"{name}: {status}")
        return "class=rate-limit" in status
    if status.startswith("CANCELLED"):
        counts["cancel"] += 1
        return False
    counts[status] += 1
    return False


def _progress(completed: int, total: int, counts: dict[str, int]) -> None:
    print(
        f"[{completed}/{total}] ok={counts['ok']} skip={counts['skip']} "
        f"fail={counts['fail']} cancel={counts['cancel']}",
        flush=True,
    )


def run_downloads(wanted: list[str], manifest: dict[str, int], *, jobs: int, fail_fast: bool) -> list[str]:
    """Download selected paths with bounded scheduling; return formatted failures."""
    counts = {"ok": 0, "skip": 0, "fail": 0, "cancel": 0}
    pending: list[str] = []
    for name in wanted:
        dest = DATA / name
        integrity_error = _ancestor_integrity_error(dest)
        if integrity_error is None and _is_exact_regular_file(dest, manifest[name]):
            counts["skip"] += 1
        else:
            pending.append(name)
    total = len(wanted)
    completed = counts["skip"]
    print(f"RESUME exact-size-skip={counts['skip']} pending={len(pending)}", flush=True)
    if not pending:
        _progress(completed, total, counts)
        return []

    failures: list[str] = []
    stop_event = threading.Event()
    current: set[str] = set()
    stopped = False
    try:
        if jobs == 1:
            for name in pending:
                current = {name}
                try:
                    result_name, status = fetch(name, manifest[name], stop_event)
                except Exception as error:  # defensive: every failure must retain its path
                    result_name, status = name, f"FAIL class=exception: {type(error).__name__}: {error}"
                current.clear()
                completed += 1
                mandatory_stop = _record_result(result_name, status, counts, failures)
                if completed % 50 == 0 or status.startswith(("FAIL", "CANCELLED")) or completed == total:
                    _progress(completed, total, counts)
                if mandatory_stop or (fail_fast and status.startswith("FAIL")):
                    stopped = True
                    break
        else:
            names = iter(pending)
            futures: dict[Future[tuple[str, str]], str] = {}
            executor = ThreadPoolExecutor(max_workers=jobs)
            try:
                for _ in range(min(jobs, len(pending))):
                    name = next(names)
                    futures[executor.submit(fetch, name, manifest[name], stop_event)] = name
                    current.add(name)
                while futures:
                    done, _ = wait(futures, return_when=FIRST_COMPLETED)
                    for future in done:
                        name = futures.pop(future)
                        current.discard(name)
                        if future.cancelled():
                            result_name, status = name, "CANCELLED before start"
                        else:
                            try:
                                result_name, status = future.result()
                            except Exception as error:  # retain path even for unexpected worker failure
                                result_name, status = name, f"FAIL class=exception: {type(error).__name__}: {error}"
                        completed += 1
                        mandatory_stop = _record_result(result_name, status, counts, failures)
                        if completed % 50 == 0 or status.startswith(("FAIL", "CANCELLED")) or completed == total:
                            _progress(completed, total, counts)
                        if mandatory_stop or (fail_fast and status.startswith("FAIL")):
                            stopped = True
                    if stopped:
                        stop_event.set()
                        for future, name in futures.items():
                            if future.cancel():
                                current.discard(name)
                        continue
                    while len(futures) < jobs:
                        try:
                            name = next(names)
                        except StopIteration:
                            break
                        futures[executor.submit(fetch, name, manifest[name], stop_event)] = name
                        current.add(name)
            except KeyboardInterrupt:
                stop_event.set()
                for future in futures:
                    future.cancel()
                executor.shutdown(wait=True, cancel_futures=True)
                raise
            else:
                executor.shutdown(wait=True)
    except KeyboardInterrupt:
        stop_event.set()
        active = ", ".join(sorted(current)) or "none"
        print(f"INTERRUPT current={active}; cancelling queued work and stopping process groups", flush=True)
        raise

    if stopped:
        not_started = total - completed - len(current)
        print(
            f"RUN STOP requested; current={','.join(sorted(current)) or 'none'} "
            f"not-started={max(0, not_started)}",
            flush=True,
        )
    for failure in failures:
        print("  ", failure)
    return failures


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train", nargs="*", default=[], help="train video stems to fetch (zarr + geff)")
    ap.add_argument("--all-geffs", action="store_true", help="also fetch the GT .geff of every train video (tiny)")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--fail-fast", action="store_true", help="stop scheduling after the first failed file")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.jobs < 1:
        ap.error("--jobs must be at least 1")

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

    try:
        with single_run_lock():
            failures = run_downloads(wanted, manifest, jobs=args.jobs, fail_fast=args.fail_fast)
    except DownloadLockHeldError as error:
        print(f"FAIL class=lock: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1) from error
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
