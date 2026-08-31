from __future__ import annotations

import fcntl
import sys
import threading
import time
from pathlib import Path

import pytest

from scripts import download_data


@pytest.fixture
def isolated_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(download_data, "DATA", data)
    return data


def _successful_command(payload: bytes):
    def run(cmd: list[str], **kwargs: object) -> tuple[int, str, bool]:
        staging = Path(cmd[cmd.index("-p") + 1])
        name = str(kwargs["name"])
        (staging / Path(name).name).write_bytes(payload)
        return 0, "", False

    return run


def test_fetch_success_atomically_replaces_old_target_and_cleans_staging(
    isolated_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "train/video.zarr/0/c/0"
    target = isolated_data / name
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    monkeypatch.setattr(download_data, "_run_command", _successful_command(b"replacement"))

    assert download_data.fetch(name, len(b"replacement")) == (name, "ok")
    assert target.read_bytes() == b"replacement"
    assert not list(target.parent.glob("*.kaggle-staging"))


def test_exact_size_target_symlink_is_not_skipped_and_self_heals(
    isolated_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "train/video.zarr/0/c/symlink"
    target = isolated_data / name
    target.parent.mkdir(parents=True)
    backing = isolated_data / "backing"
    backing.write_bytes(b"old data")
    target.symlink_to(backing)
    monkeypatch.setattr(download_data, "_run_command", _successful_command(b"new data"))

    assert download_data.fetch(name, len(b"new data")) == (name, "ok")
    assert not target.is_symlink()
    assert target.read_bytes() == b"new data"
    assert backing.read_bytes() == b"old data"


def test_failed_fetch_preserves_target_symlink(isolated_data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    name = "train/video.zarr/0/c/symlink"
    target = isolated_data / name
    target.parent.mkdir(parents=True)
    backing = isolated_data / "backing"
    backing.write_bytes(b"old data")
    target.symlink_to(backing)
    monkeypatch.setattr(download_data, "_run_command", lambda *args, **kwargs: (1, "HTTP 403 Forbidden", False))

    _, status = download_data.fetch(name, len(b"old data"))

    assert "class=forbidden" in status
    assert target.is_symlink()
    assert target.resolve() == backing
    assert backing.read_bytes() == b"old data"


def test_ancestor_symlink_fails_before_popen(isolated_data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outside = isolated_data.parent / "outside"
    outside.mkdir()
    (isolated_data / "train").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(download_data, "_run_command", lambda *args, **kwargs: pytest.fail("Popen reached"))

    _, status = download_data.fetch("train/unsafe", 1)

    assert "FAIL class=integrity" in status
    assert f"symlink ancestor path={isolated_data / 'train'}" in status
    assert not (outside / "unsafe").exists()


def test_external_exact_files_are_rejected_before_prefilter_skip_or_popen(
    isolated_data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    absolute_external = isolated_data.parent / "absolute-external"
    traversal_external = isolated_data.parent / "traversal-external"
    absolute_external.write_bytes(b"same")
    traversal_external.write_bytes(b"same")
    names = [str(absolute_external), "../traversal-external", "nested/..", ""]
    monkeypatch.setattr(download_data, "_run_command", lambda *args, **kwargs: pytest.fail("Popen reached"))

    failures = download_data.run_downloads(names, {name: 4 for name in names}, jobs=1, fail_fast=False)

    assert len(failures) == 4
    assert all("FAIL class=integrity: destination escapes data root" in failure for failure in failures)
    assert "RESUME exact-size-skip=0 pending=4" in capsys.readouterr().out
    assert absolute_external.read_bytes() == b"same"
    assert traversal_external.read_bytes() == b"same"


def test_fetch_failure_preserves_old_target_and_cleans_staging(
    isolated_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "train/video.zarr/0/c/0"
    target = isolated_data / name
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old bytes")
    monkeypatch.setattr(download_data, "_run_command", lambda *args, **kwargs: (1, "HTTP 403 Forbidden", False))

    _, status = download_data.fetch(name, 99)

    assert "class=forbidden" in status
    assert target.read_bytes() == b"old bytes"
    assert not list(target.parent.glob("*.kaggle-staging"))


def test_cleanup_failure_is_explicit_and_preserves_old_target(
    isolated_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "train/video.zarr/0/c/cleanup"
    target = isolated_data / name
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    monkeypatch.setattr(download_data, "_run_command", _successful_command(b"replacement"))

    def cleanup_denied(path: Path) -> None:
        raise PermissionError("cleanup denied")

    monkeypatch.setattr(download_data.shutil, "rmtree", cleanup_denied)

    _, status = download_data.fetch(name, len(b"replacement"))

    assert "FAIL class=cleanup" in status
    assert "staging path=" in status
    assert "PermissionError: cleanup denied" in status
    assert target.read_bytes() == b"old"
    assert not list(target.parent.glob("*.kaggle-ready"))
    assert len(list(target.parent.glob("*.kaggle-staging"))) == 1


def test_fetch_interrupt_preserves_old_target_and_cleans_staging(
    isolated_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "train/video.zarr/0/c/interrupted"
    target = isolated_data / name
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old bytes")

    def interrupt(*args: object, **kwargs: object) -> tuple[int, str, bool]:
        raise KeyboardInterrupt

    monkeypatch.setattr(download_data, "_run_command", interrupt)

    with pytest.raises(KeyboardInterrupt):
        download_data.fetch(name, 99)

    assert target.read_bytes() == b"old bytes"
    assert not list(target.parent.glob("*.kaggle-staging"))


def test_interrupt_and_cleanup_failure_are_both_observable(
    isolated_data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    name = "train/video.zarr/0/c/interrupted-cleanup"
    target = isolated_data / name
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old bytes")

    def interrupt(*args: object, **kwargs: object) -> tuple[int, str, bool]:
        raise KeyboardInterrupt

    def cleanup_denied(path: Path) -> None:
        raise PermissionError("cleanup denied")

    monkeypatch.setattr(download_data, "_run_command", interrupt)
    monkeypatch.setattr(download_data.shutil, "rmtree", cleanup_denied)

    with pytest.raises(KeyboardInterrupt) as caught:
        download_data.fetch(name, 99)

    stderr = capsys.readouterr().err
    assert "CLEANUP FAIL while handling KeyboardInterrupt" in stderr
    assert "staging path=" in stderr
    assert "cleanup denied" in stderr
    assert caught.value.__notes__ and "CLEANUP FAIL" in caught.value.__notes__[0]
    assert target.read_bytes() == b"old bytes"


def test_rate_limit_is_not_retried_and_stops_later_sequential_work(
    isolated_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_fetch(name: str, size: int, stop_event: threading.Event) -> tuple[str, str]:
        calls.append(name)
        return name, "FAIL class=rate-limit rc=1: HTTP 429 Too Many Requests"

    monkeypatch.setattr(download_data, "fetch", fake_fetch)
    manifest = {"a": 1, "b": 1, "c": 1}

    failures = download_data.run_downloads(list(manifest), manifest, jobs=1, fail_fast=False)

    assert calls == ["a"]
    assert failures == ["a: FAIL class=rate-limit rc=1: HTTP 429 Too Many Requests"]


def test_fetch_classifies_429_without_retry(isolated_data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def rate_limited(*args: object, **kwargs: object) -> tuple[int, str, bool]:
        nonlocal calls
        calls += 1
        return 1, "HTTP 429 Too Many Requests", False

    monkeypatch.setattr(download_data, "_run_command", rate_limited)

    _, status = download_data.fetch("train/rate-limited", 1)

    assert "class=rate-limit" in status
    assert calls == 1


def test_jobs_one_uses_no_executor_and_counts_exact_skips_first(
    isolated_data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    existing = isolated_data / "already"
    existing.write_bytes(b"yes")
    calls: list[str] = []

    def no_executor(*args: object, **kwargs: object) -> None:
        raise AssertionError("jobs=1 must not construct an executor")

    def fake_fetch(name: str, size: int, stop_event: threading.Event) -> tuple[str, str]:
        calls.append(name)
        return name, "ok"

    monkeypatch.setattr(download_data, "ThreadPoolExecutor", no_executor)
    monkeypatch.setattr(download_data, "fetch", fake_fetch)

    assert (
        download_data.run_downloads(["already", "pending"], {"already": 3, "pending": 4}, jobs=1, fail_fast=True)
        == []
    )
    assert calls == ["pending"]
    assert "RESUME exact-size-skip=1 pending=1" in capsys.readouterr().out


def test_main_prefilter_does_not_count_exact_size_symlink_as_skip(
    isolated_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backing = isolated_data / "backing"
    backing.write_bytes(b"same")
    target = isolated_data / "selected"
    target.symlink_to(backing)
    calls: list[str] = []

    def fake_fetch(name: str, size: int, stop_event: threading.Event) -> tuple[str, str]:
        calls.append(name)
        return name, "FAIL class=integrity: test stop"

    monkeypatch.setattr(download_data, "fetch", fake_fetch)

    failures = download_data.run_downloads(["selected"], {"selected": 4}, jobs=1, fail_fast=True)

    assert calls == ["selected"]
    assert failures == ["selected: FAIL class=integrity: test stop"]


def test_dry_run_keeps_selection_summary_and_does_not_take_lock(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = {"sample_submission.csv": 123}
    monkeypatch.setattr(download_data, "load_manifest", lambda: manifest)
    monkeypatch.setattr(sys, "argv", ["download_data.py", "--jobs", "1", "--fail-fast", "--dry-run"])

    @download_data.contextmanager
    def forbidden_lock():
        pytest.fail("dry-run must not take the mutation lock")
        yield

    monkeypatch.setattr(download_data, "single_run_lock", forbidden_lock)

    download_data.main()

    assert capsys.readouterr().out == "1 files, 0.00 GB selected\n   sample_submission.csv\n"


def test_parallel_scheduler_never_exceeds_jobs_in_flight(
    isolated_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = 0
    maximum = 0
    lock = threading.Lock()

    def fake_fetch(name: str, size: int, stop_event: threading.Event) -> tuple[str, str]:
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return name, "ok"

    monkeypatch.setattr(download_data, "fetch", fake_fetch)
    manifest = {f"file-{index}": 1 for index in range(9)}

    assert download_data.run_downloads(list(manifest), manifest, jobs=2, fail_fast=False) == []
    assert maximum == 2


def test_future_exception_reports_the_manifest_path(
    isolated_data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_fetch(name: str, size: int, stop_event: threading.Event) -> tuple[str, str]:
        if name == "broken/path":
            raise RuntimeError("worker exploded")
        return name, "ok"

    monkeypatch.setattr(download_data, "fetch", fake_fetch)

    failures = download_data.run_downloads(
        ["broken/path", "other/path"], {"broken/path": 1, "other/path": 1}, jobs=2, fail_fast=False
    )

    assert failures == ["broken/path: FAIL class=exception: RuntimeError: worker exploded"]
    assert "broken/path: FAIL class=exception" in capsys.readouterr().out


def test_timeout_retries_are_finite_and_leave_target_unchanged(
    isolated_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "train/video.geff/chunk"
    target = isolated_data / name
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    calls = 0

    def timeout(*args: object, **kwargs: object) -> tuple[int, str, bool]:
        nonlocal calls
        calls += 1
        return -15, "", True

    monkeypatch.setattr(download_data, "_run_command", timeout)
    monkeypatch.setattr(download_data, "TIMEOUT_RETRY_DELAY_SECONDS", 0.0)

    _, status = download_data.fetch(name, 100)

    assert status == "FAIL class=timeout after 2 attempts"
    assert calls == download_data.MAX_TIMEOUT_ATTEMPTS == 2
    assert target.read_bytes() == b"old"


def test_hard_timeout_emits_heartbeat_and_kills_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    child_pid_file = tmp_path / "child.pid"
    term_marker = tmp_path / "term.marker"
    child_code = (
        "import pathlib,signal,sys,time; "
        "signal.signal(signal.SIGTERM, lambda *_: "
        "(pathlib.Path(sys.argv[1]).write_text('TERM'), sys.exit(0))); time.sleep(30)"
    )
    code = (
        "import pathlib,subprocess,sys,time; "
        f"child=subprocess.Popen([sys.executable,'-c',{child_code!r},sys.argv[2]]); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(30)"
    )
    monkeypatch.setattr(download_data, "DOWNLOAD_TIMEOUT_SECONDS", 0.25)
    monkeypatch.setattr(download_data, "HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(download_data, "PROCESS_POLL_SECONDS", 0.01)
    monkeypatch.setattr(download_data, "TERMINATE_GRACE_SECONDS", 0.05)

    returncode, _, hard_timeout = download_data._run_command(
        [sys.executable, "-c", code, str(child_pid_file), str(term_marker)],
        name="train/a",
        attempt=1,
        stop_event=threading.Event(),
    )

    assert hard_timeout
    assert returncode is not None
    output = capsys.readouterr().out
    assert "START path=train/a attempt=1/2 deadline=" in output
    assert "HEARTBEAT path=train/a" in output
    assert "TIMEOUT path=train/a" in output
    assert child_pid_file.read_text().isdigit()
    assert term_marker.read_text() == "TERM"


def test_process_group_termination_escalates_to_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    signals: list[int] = []

    class StubbornProcess:
        pid = 321
        dead = False

        def poll(self) -> int | None:
            return -9 if self.dead else None

        def wait(self, timeout: float) -> int:
            return -9

    process = StubbornProcess()

    def killpg(pid: int, sig: int) -> None:
        assert pid == process.pid
        signals.append(sig)
        if sig == download_data.signal.SIGKILL:
            process.dead = True

    monkeypatch.setattr(download_data.os, "killpg", killpg)
    monkeypatch.setattr(download_data, "TERMINATE_GRACE_SECONDS", 0.0)

    download_data._terminate_process_group(process)  # type: ignore[arg-type]

    assert signals == [download_data.signal.SIGTERM, download_data.signal.SIGKILL]


def test_popen_starts_a_new_session(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class FinishedProcess:
        pid = 123
        returncode = 0

        def __init__(self, cmd: list[str], **kwargs: object) -> None:
            seen.update(kwargs)

        def poll(self) -> int:
            return 0

    monkeypatch.setattr(download_data.subprocess, "Popen", FinishedProcess)
    download_data._run_command(["ignored"], name="path", attempt=1, stop_event=threading.Event())
    assert seen["start_new_session"] is True


def test_interrupt_inside_command_stops_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    signals: list[int] = []

    class InterruptedProcess:
        pid = 456
        polls = 0
        dead = False

        def __init__(self, cmd: list[str], **kwargs: object) -> None:
            pass

        def poll(self) -> int | None:
            self.polls += 1
            if self.polls == 1:
                raise KeyboardInterrupt
            return -15 if self.dead else None

        def wait(self, timeout: float) -> int:
            return -15

    process: InterruptedProcess | None = None

    def popen(cmd: list[str], **kwargs: object) -> InterruptedProcess:
        nonlocal process
        process = InterruptedProcess(cmd, **kwargs)
        return process

    def killpg(pid: int, sig: int) -> None:
        assert process is not None and pid == process.pid
        signals.append(sig)
        process.dead = True

    monkeypatch.setattr(download_data.subprocess, "Popen", popen)
    monkeypatch.setattr(download_data.os, "killpg", killpg)

    with pytest.raises(KeyboardInterrupt):
        download_data._run_command(["ignored"], name="current/path", attempt=1, stop_event=threading.Event())

    assert signals == [download_data.signal.SIGTERM]


def test_single_run_lock_rejects_a_second_owner(isolated_data: Path) -> None:
    lock_path = isolated_data / ".download_data.lock"
    with lock_path.open("a+") as holder:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(download_data.DownloadLockHeldError, match="another download is running"):
            with download_data.single_run_lock():
                pass


def test_keyboard_interrupt_reports_current_path_and_propagates(
    isolated_data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def interrupt(name: str, size: int, stop_event: threading.Event) -> tuple[str, str]:
        raise KeyboardInterrupt

    monkeypatch.setattr(download_data, "fetch", interrupt)

    with pytest.raises(KeyboardInterrupt):
        download_data.run_downloads(
            ["current/path", "queued/path"],
            {"current/path": 1, "queued/path": 1},
            jobs=1,
            fail_fast=True,
        )

    output = capsys.readouterr().out
    assert "INTERRUPT current=current/path" in output
    assert "cancelling queued work" in output


def test_cancelled_fetch_does_not_start_a_process(isolated_data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stop = threading.Event()
    stop.set()
    monkeypatch.setattr(download_data, "_run_command", lambda *args, **kwargs: pytest.fail("process started"))

    assert download_data.fetch("queued/path", 1, stop) == ("queued/path", "CANCELLED run stopping")


@pytest.mark.parametrize(
    ("message", "classification"),
    [
        ("NameResolutionError", "dns"),
        ("HTTP 401 Unauthorized", "auth"),
        ("HTTP 403 Forbidden", "forbidden"),
        ("OSError: [Errno 28] No space left on device", "disk-full"),
        ("unexpected failure", "unknown"),
    ],
)
def test_non_timeout_failures_are_classified_without_retry(
    isolated_data: Path,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    classification: str,
) -> None:
    calls = 0

    def fail(*args: object, **kwargs: object) -> tuple[int, str, bool]:
        nonlocal calls
        calls += 1
        return 1, message, False

    monkeypatch.setattr(download_data, "_run_command", fail)

    _, status = download_data.fetch("some/path", 1)

    assert f"class={classification}" in status
    assert calls == 1
