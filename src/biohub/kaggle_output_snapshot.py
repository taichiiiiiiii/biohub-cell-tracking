"""Bounded output retrieval; no submission, kernel dispatch, GT read or model worker."""

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import requests


class SnapshotError(ValueError):
    pass


def require(value, message):
    if not value:
        raise SnapshotError(message)


@dataclass(frozen=True)
class Limits:
    files: int = 12000
    pages: int = 100
    seconds: float = 900.0
    download_bytes: int = 512 * 1024**2
    file_bytes: int = 64 * 1024**2
    remote_bytes: int = 64 * 1024**3
    io_threads: int = 4


def safe_path(name):
    require(isinstance(name, str) and bool(name), "empty output path")
    p = PurePosixPath(name)
    require(
        bool(p.parts)
        and not p.is_absolute()
        and ".." not in p.parts
        and str(p) == name
        and "\\" not in name
        and "\x00" not in name,
        "unsafe output path",
    )
    return p


def range_size(url, get=requests.get, *, deadline=None, clock=time.monotonic):
    """Return the exact byte length of a remote resource using one ranged GET."""
    try:
        if not isinstance(url, str):
            raise SnapshotError("url must be a string")
        parts = urlsplit(url)
        if (
            parts.scheme.lower() != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
        ):
            raise SnapshotError("url must be an https URL with a host and no userinfo")
        if deadline is not None:
            deadline = _finite_number(deadline, "deadline must be a finite number")
        left = _remaining(deadline, clock)

        response = get(
            url,
            stream=True,
            allow_redirects=False,
            timeout=_timeout(left),
            headers={"Range": "bytes=0-0", "Accept-Encoding": "identity"},
        )
        try:
            left = _remaining(deadline, clock)
            with response as entered:
                left = _remaining(deadline, clock)
                size = _parse_size(entered, deadline, clock)
            left = _remaining(deadline, clock)
        finally:
            response.close()
        _remaining(deadline, clock)
    except Exception:
        raise SnapshotError("HTTP size request failed") from None
    return size

def _remaining(deadline, clock):
    now = _finite_number(clock(), "clock must return a finite number")
    if deadline is None:
        return None
    deadline = _finite_number(deadline, "deadline must be a finite number")
    left = _finite_number(deadline - now, "deadline must be a finite number")
    if left <= 0:
        raise SnapshotError("deadline exceeded")
    return left


def _timeout(left):
    if left is None:
        return (10, 30)
    from urllib3.util import Timeout

    return Timeout(total=left, connect=min(10, left), read=min(30, left))


def _parse_size(response, deadline, clock):
    status = response.status_code
    encoding = response.headers.get("Content-Encoding")
    if encoding is not None and encoding != "identity":
        raise SnapshotError("unsupported Content-Encoding")

    if status == 206:
        content_range = response.headers.get("Content-Range")
        total = _range_total(content_range)
        length = response.headers.get("Content-Length")
        if length is not None and length != "1":
            raise SnapshotError("invalid Content-Length for partial response")
        _remaining(deadline, clock)
        raw = response.raw.read(1)
        _remaining(deadline, clock)
        if not isinstance(raw, bytes) or len(raw) != 1:
            raise SnapshotError("partial response body is not exactly one byte")
        return total

    if status == 416:
        content_range = response.headers.get("Content-Range")
        if content_range is None or content_range != "bytes */0":
            raise SnapshotError("invalid Content-Range for 416 response")
        return 0

    raise SnapshotError(f"unexpected HTTP status {status:d}")


def _range_total(content_range):
    if content_range is None:
        raise SnapshotError("missing Content-Range")
    match = re.fullmatch(r"bytes 0-0/([1-9][0-9]*)", content_range)
    if not match:
        raise SnapshotError("invalid Content-Range")
    return int(match.group(1))



def download(url, path, size, get=requests.get, *, deadline=None, clock=time.monotonic):
    def check_remaining():
        return _remaining(deadline, clock)

    try:
        if not isinstance(url, str):
            raise SnapshotError("url must be a string")
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname:
            raise SnapshotError("url must be https with a hostname")
        if parts.username is not None or parts.password is not None:
            raise SnapshotError("url must not contain credentials")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise SnapshotError("size must be a non-negative int")
        if deadline is not None:
            _finite_number(deadline, "deadline must be a finite number")

        path = Path(path)
        partial = path.with_name(path.name + ".partial")
        for p in (path, partial):
            if p.is_symlink() or p.exists():
                raise SnapshotError("output path already exists")
        path.parent.mkdir(parents=True, exist_ok=True)

        left = check_remaining()
        response = get(
            url,
            stream=True,
            allow_redirects=False,
            headers={"Accept-Encoding": "identity"},
            timeout=_timeout(left),
        )
        try:
            check_remaining()
            with response as r:
                check_remaining()
                if r.status_code != 200:
                    raise SnapshotError("unexpected HTTP status")
                encoding = r.headers.get("Content-Encoding")
                if encoding not in (None, "identity"):
                    raise SnapshotError("unexpected Content-Encoding")
                declared = r.headers.get("Content-Length")
                if declared is not None and declared != str(size):
                    raise SnapshotError("Content-Length mismatch")
                hasher = hashlib.sha256()
                received = 0
                iterator = r.iter_content(chunk_size=1024 ** 2)
                with open(partial, "xb") as sink:
                    while True:
                        check_remaining()
                        try:
                            chunk = next(iterator)
                        except StopIteration:
                            check_remaining()
                            break
                        check_remaining()
                        if not isinstance(chunk, bytes):
                            raise SnapshotError("chunk is not bytes")
                        if not chunk:
                            continue
                        if received + len(chunk) > size:
                            raise SnapshotError("response exceeds expected size")
                        check_remaining()
                        if sink.write(chunk) != len(chunk):
                            raise SnapshotError("short write")
                        hasher.update(chunk)
                        received += len(chunk)
                    if received != size:
                        raise SnapshotError("incomplete download")
                check_remaining()
            check_remaining()
        finally:
            response.close()

        if path.is_symlink() or path.exists():
            raise SnapshotError("output path appeared before rename")
        check_remaining()
        partial.rename(path)
        check_remaining()
        return hasher.hexdigest()
    except Exception:
        raise SnapshotError("HTTP download failed") from None


def snapshot(source, output, required_paths, *, limits=None, get=requests.get,
             progress=None, clock=time.monotonic):
    """Freeze a COMPLETE Kaggle kernel output namespace into a verified local snapshot."""
    RESERVED_ERROR = "SNAPSHOT_ERROR.json"
    RESERVED_INVENTORY = "INVENTORY.json"
    COMPLETE_MARKER = "KERNEL_OUTPUT_SNAPSHOT_COMPLETE"

    from biohub.output_namespace import validate_namespace

    def budget():
        return _remaining(deadline, clock)

    def emit(phase, done, total):
        if progress is None:
            return
        budget()
        call_external(progress, {"phase": phase, "done": done, "total": total})
        budget()

    owns_root = False
    error_state = {"phase": "limits", "downloaded_files": 0, "listed_files": 0,
                   "sizes_checked": 0}

    def emit_error(state):
        if not owns_root:
            return
        try:
            with open(out / RESERVED_ERROR, "x", encoding="utf-8") as handle:
                json.dump({
                    "status": "SNAPSHOT_INCOMPLETE",
                    "phase": state["phase"],
                    "downloaded_files": state["downloaded_files"],
                    "listed_files": state["listed_files"],
                    "sizes_checked": state["sizes_checked"],
                    "submission_authorized": False,
                }, handle, indent=2, sort_keys=True)
                handle.write("\n")
        except Exception:
            pass

    def save_inventory(receipt):
        body = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        with open(out / RESERVED_INVENTORY, "xb") as handle:
            handle.write(body.encode("utf-8"))

    try:
        if progress is not None and not callable(progress):
            raise TypeError("progress must be callable")
        lim = Limits() if limits is None else limits
        _pos_int(lim.files, "files limit")
        _pos_int(lim.pages, "pages limit")
        seconds = _finite_number(lim.seconds, "seconds limit")
        download_budget = _pos_int(lim.download_bytes, "download_bytes limit")
        file_max = _pos_int(lim.file_bytes, "file_bytes limit")
        remote_budget = _pos_int(lim.remote_bytes, "remote_bytes limit")
        io_threads = _pos_int(lim.io_threads, "io_threads limit")
        if seconds <= 0:
            raise ValueError("seconds limit must be positive")
        if io_threads > 4:
            raise ValueError("io_threads limit out of range")

        if isinstance(required_paths, str) or not isinstance(required_paths, (list, tuple)):
            raise TypeError("required_paths must be a list or tuple")
        paths = []
        for raw in required_paths:
            if not isinstance(raw, str) or not raw:
                raise ValueError("required path must be a non-empty string")
            paths.append(raw)
        if not paths:
            raise ValueError("required_paths must not be empty")
        if len(set(paths)) != len(paths):
            raise ValueError("required paths must be unique")

        kernel = source.kernel
        if not isinstance(kernel, str) or not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_-]+", kernel):
            raise ValueError("kernel identifier is invalid")
        kernel_tag = kernel.split("/")[1]
        log_name = kernel_tag + ".log"

        for p in paths + [log_name]:
            safe_path(p)

        error_state["phase"] = "status-before"
        start = _finite_number(clock(), "clock reading")
        deadline = _finite_number(start + seconds, "deadline")
        budget()
        status_before = call_external(source.status)
        budget()
        if status_before != "COMPLETE":
            raise SnapshotError("kernel status is not COMPLETE")

        listed_before, log_text, pages_before = list_all_pages(
            source, lim, deadline, clock=clock)
        error_state["listed_files"] = len(listed_before)

        error_state["phase"] = "resolve-required"
        missing = [p for p in paths if p not in listed_before]
        if missing:
            raise SnapshotError("required paths are missing from the output listing")
        selected = sorted(set(paths))
        validate_namespace(sorted(listed_before), selected, log_name)

        error_state["phase"] = "output-dir"
        out = Path(output)
        out.mkdir(parents=True, exist_ok=False)
        owns_root = True

        log_bytes = log_text.encode("utf-8")
        log_sha = hashlib.sha256(log_bytes).hexdigest()
        error_state["phase"] = "log-write"
        log_path = out / safe_path(log_name)
        with open(log_path, "xb") as handle:
            handle.write(log_bytes)
        if log_path.stat().st_size != len(log_bytes):
            raise SnapshotError("saved log size mismatch")

        error_state["phase"] = "range-inventory"
        total_remote = 0
        sizes = {}
        pool = ThreadPoolExecutor(max_workers=io_threads)
        try:
            names = sorted(listed_before)
            for batch_start in range(0, len(names), io_threads):
                budget()
                batch = names[batch_start:batch_start + io_threads]
                futures = []
                for p in batch:
                    budget()
                    futures.append(pool.submit(call_external, range_size, listed_before[p], get,
                                               deadline=deadline, clock=clock))
                for path, fut in zip(batch, futures, strict=True):
                    size = fut.result(timeout=budget())
                    budget()
                    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                        raise SnapshotError("reported byte size is invalid")
                    error_state["sizes_checked"] += 1
                    total_remote += size
                    if total_remote > remote_budget:
                        raise SnapshotError("remote bytes exceed the configured budget")
                    sizes[path] = size
                emit("inventory", min(batch_start + len(batch), len(names)), len(names))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        error_state["phase"] = "size-policy"
        selected_total = sum(sizes[p] for p in selected)
        if selected_total + len(log_bytes) > download_budget:
            raise SnapshotError("selected download bytes exceed the budget")
        oversized = [p for p in selected if sizes[p] > file_max]
        if oversized or len(selected) > lim.files:
            raise SnapshotError("selected files exceed the per-file or count policy")

        error_state["phase"] = "download"
        downloaded = []
        written = 0
        total_selected = len(selected)
        for index, path in enumerate(selected, start=1):
            budget()
            sha = call_external(download, listed_before[path], out / safe_path(path),
                               sizes[path], get, deadline=deadline, clock=clock)
            budget()
            written += sizes[path]
            error_state["downloaded_files"] += 1
            downloaded.append({"path": path, "bytes": sizes[path], "sha256": sha})
            emit("download", index, total_selected)

        error_state["phase"] = "status-after-list"
        budget()
        status_after = call_external(source.status)
        budget()
        if status_after != "COMPLETE":
            raise SnapshotError("kernel status changed during snapshot")
        listed_after, log_after, pages_after = list_all_pages(source, lim, deadline, clock=clock)
        budget()
        status_after = call_external(source.status)
        budget()
        if status_after != "COMPLETE":
            raise SnapshotError("kernel status changed after listing")
        if set(listed_after) != set(listed_before):
            raise SnapshotError("output namespace changed during snapshot")
        if log_text != log_after:
            raise SnapshotError("output log changed during snapshot")
        validate_namespace(sorted(listed_after), selected, log_name)
        error_state["listed_files"] = len(listed_after)

        error_state["phase"] = "verify"
        for entry in downloaded:
            budget()
            target = out / safe_path(entry["path"])
            digest = hashlib.sha256()
            read_bytes = 0
            with open(target, "rb") as handle:
                while True:
                    budget()
                    chunk = handle.read(min(1 << 20, file_max))
                    budget()
                    if not chunk:
                        break
                    read_bytes += len(chunk)
                    digest.update(chunk)
            if read_bytes != entry["bytes"] or digest.hexdigest() != entry["sha256"]:
                raise SnapshotError("saved file verification failed")
        if log_path.read_bytes() != log_bytes:
            raise SnapshotError("saved log verification failed")

        error_state["phase"] = "receipt"
        receipt = {
            "status": COMPLETE_MARKER,
            "kernel": kernel,
            "status_before": status_before,
            "status_after": "COMPLETE",
            "pages": pages_before,
            "pages_after": pages_after,
            "all_pages_exhausted": True,
            "explicit_version_fetch": False,
            "size_method": "HTTP_GET_RANGE_CONTENT_RANGE",
            "files": [{"path": p, "bytes": sizes[p]} for p in sorted(sizes)],
            "downloaded": downloaded,
            "log_path": log_name,
            "log_sha256": log_sha,
            "total_remote_bytes": total_remote,
            "downloaded_bytes": written + len(log_bytes),
            "wall_seconds": clock() - start,
            "range_body_bytes_max": len(sizes),
            "submission_authorized": False,
        }
        budget()
        save_inventory(receipt)
        budget()
        return receipt
    except Exception:
        emit_error(error_state)
        raise SnapshotError("snapshot failed") from None


def call_external(callback, *args, **kwargs):
    """Invoke an external boundary once; never leak its exception text or type."""
    if not callable(callback):
        raise SnapshotError("callback must be callable")
    try:
        return callback(*args, **kwargs)
    except Exception:
        raise SnapshotError("external source call failed") from None


def _pos_int(value, message):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SnapshotError(message)
    return value


def _finite_number(value, message):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SnapshotError(message)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise SnapshotError(message) from None
    if number != number or number in (float("inf"), float("-inf")):
        raise SnapshotError(message)
    return number


def _token_or_none(value, message):
    if value is None:
        return None
    if not isinstance(value, str):
        raise SnapshotError(message)
    return value


def list_all_pages(source, limits, deadline, *, clock=time.monotonic):
    """Page through source.page into an in-memory path->https URL map.

    Returns (files, log, pages). Performs no file/HTTP/status/progress work.
    """
    files_limit = _pos_int(getattr(limits, "files", None), "limits.files must be a positive integer")
    pages_limit = _pos_int(getattr(limits, "pages", None), "limits.pages must be a positive integer")
    bytes_limit = _pos_int(getattr(limits, "file_bytes", None), "limits.file_bytes must be a positive integer")
    deadline_value = _finite_number(deadline, "deadline must be a finite number")
    if not callable(clock):
        raise SnapshotError("clock must be callable")

    files = {}
    log = None
    seen_tokens = set()
    token = None
    first = True
    pages = 0

    while True:
        if pages >= pages_limit:
            raise SnapshotError("page limit exceeded")
        now = _finite_number(call_external(clock), "clock returned invalid value")
        if deadline_value - now <= 0:
            raise SnapshotError("deadline expired")
        page = call_external(source.page, None if first else token)
        pages += 1
        now = _finite_number(call_external(clock), "clock returned invalid value")
        if deadline_value - now <= 0:
            raise SnapshotError("deadline expired")
        if type(page) is not dict:
            raise SnapshotError("invalid page return")
        for key in ("files", "log", "next_page_token"):
            if key not in page:
                raise SnapshotError("invalid page return")
        items = page["files"]
        if type(items) is not list:
            raise SnapshotError("invalid page return")
        entry_log = page["log"]
        if entry_log is not None and type(entry_log) is not str:
            raise SnapshotError("invalid page return")
        next_token = _token_or_none(page["next_page_token"], "invalid page return")

        if len(files) + len(items) > files_limit:
            raise SnapshotError("file limit exceeded")
        for item in items:
            if type(item) is not dict:
                raise SnapshotError("invalid file entry")
            path_value = item.get("path")
            url_value = item.get("url")
            if type(path_value) is not str or type(url_value) is not str:
                raise SnapshotError("invalid file entry")
            try:
                safe = safe_path(path_value)
            except SnapshotError:
                raise SnapshotError("invalid file entry") from None
            if str(safe) == ".":
                raise SnapshotError("invalid file entry")
            key = str(safe)
            if key in files:
                raise SnapshotError("duplicate file path")
            try:
                parts = urlsplit(url_value)
                host = parts.hostname
            except ValueError:
                raise SnapshotError("invalid file entry") from None
            if parts.scheme != "https" or not host or parts.username or parts.password:
                raise SnapshotError("invalid file entry")
            files[key] = url_value

        if entry_log:
            try:
                encoded_len = len(entry_log.encode("utf-8"))
            except UnicodeEncodeError:
                raise SnapshotError("log byte limit exceeded") from None
            if encoded_len > bytes_limit:
                raise SnapshotError("log byte limit exceeded")
            if log is None:
                log = entry_log
            elif log != entry_log:
                raise SnapshotError("inconsistent page log")

        first = False
        if next_token is None or next_token == "":
            break
        if next_token in seen_tokens:
            raise SnapshotError("page token cycle")
        seen_tokens.add(next_token)
        token = next_token

    if not log:
        raise SnapshotError("missing page log")
    now = _finite_number(call_external(clock), "clock returned invalid value")
    if deadline_value - now <= 0:
        raise SnapshotError("deadline expired")
    return files, log, pages
