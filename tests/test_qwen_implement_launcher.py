from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LAUNCHER = REPO / ".codex/bin/qwen-implement"
POLICY = REPO / ".codex/runners/biohub_implementer.instructions.md"
FLASH_POLICY = REPO / ".codex/runners/biohub_flash_implementer.instructions.md"
MAX_POLICY = REPO / ".codex/runners/biohub_max_implementer.instructions.md"
SHIM = REPO / ".codex/libexec/qwen-implement/codex"
SHARED_QUEUE = Path("/Users/taichi/.local/bin/qwen-implementation-queue")


def run(*argv: str | Path, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(value) for value in argv],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )


@dataclass
class Harness:
    root: Path
    worktree: Path
    launcher: Path
    env: dict[str, str]
    capture: Path
    queue_pid: Path

    @property
    def lock(self) -> Path:
        git_dir = Path(run("git", "-C", self.worktree, "rev-parse", "--absolute-git-dir").stdout.strip())
        return git_dir / "biohub-implement.lock"

    def invoke(self, *extra: str, target: Path | None = None) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [str(self.launcher), *extra, str(target or self.worktree)],
            input=b"bounded task\n",
            env=self.env,
            capture_output=True,
        )


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    root = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    fake_bin = tmp_path / "fake-bin"
    capture = tmp_path / "capture"
    root.mkdir()
    fake_bin.mkdir()
    capture.mkdir()

    run("git", "init", "-b", "develop", root)
    run("git", "-C", root, "config", "user.name", "Test User")
    run("git", "-C", root, "config", "user.email", "test@example.invalid")

    launcher = root / ".codex/bin/qwen-implement"
    policy = root / ".codex/runners/biohub_implementer.instructions.md"
    shim = root / ".codex/libexec/qwen-implement/codex"
    launcher.parent.mkdir(parents=True)
    policy.parent.mkdir(parents=True)
    shim.parent.mkdir(parents=True)
    queue = tmp_path / "fake-queue"

    launcher_text = LAUNCHER.read_text().replace(
        'IMPLEMENTATION_QUEUE="/Users/taichi/.local/bin/qwen-implementation-queue"',
        f'IMPLEMENTATION_QUEUE="{queue}"',
    )
    launcher_text = launcher_text.replace(
        'CANONICAL="/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking"', f'CANONICAL="{root}"'
    )
    launcher.write_text(launcher_text)
    policy.write_bytes(POLICY.read_bytes())
    (policy.parent / FLASH_POLICY.name).write_bytes(FLASH_POLICY.read_bytes())
    (policy.parent / MAX_POLICY.name).write_bytes(MAX_POLICY.read_bytes())
    shim.write_bytes(SHIM.read_bytes())
    tracked = root / "tracked.txt"
    tracked.write_text("clean\n")
    for executable in (launcher, shim):
        executable.chmod(0o755)

    queue.write_text(
        """#!/usr/bin/env python3
import json, os, signal, subprocess, sys, time
from pathlib import Path

def stopped(signum, _frame):
    (Path(os.environ["QWEN_TEST_CAPTURE"]) / "signal.txt").write_text(str(signum))
    if os.environ.get("QWEN_TEST_KILL_ON_SIGNAL"):
        os.kill(os.getpid(), signal.SIGKILL)
    raise SystemExit(128 + signum)

for handled in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
    signal.signal(handled, stopped)

capture = Path(os.environ["QWEN_TEST_CAPTURE"])
capture.mkdir(exist_ok=True)
(Path(os.environ["QWEN_TEST_QUEUE_PID"])).write_text(str(os.getpid()))
argv = sys.argv[1:]
(capture / "queue.json").write_text(json.dumps(argv))
cloud_only = bool(argv and argv[0] == "--cloud-only")
if cloud_only:
    argv = argv[1:]
if len(argv) >= 2 and argv[0] == "--cloud-model" and argv[1] in ("qwen3.8-flash", "qwen3.8-max"):
    argv = argv[2:]
mutation = os.environ.get("QWEN_TEST_MUTATE")
target = Path(os.environ["BIOHUB_QWEN_TARGET"])
if mutation == "dirty":
    (target / "queued-dirty.txt").write_text("dirty")
elif mutation == "branch":
    subprocess.run(["git", "-C", str(target), "switch", "-c", "queued-change"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
ready = os.environ.get("QWEN_TEST_READY")
release = os.environ.get("QWEN_TEST_RELEASE")
if ready:
    Path(ready).write_text("ready")
while release and not Path(release).exists():
    time.sleep(0.02)
payload = sys.stdin.buffer.read()
result = subprocess.run(argv, input=payload, env=os.environ)
raise SystemExit(result.returncode)
"""
    )
    queue.chmod(0o755)

    fake_codex = fake_bin / "codex"
    fake_codex.write_text(
        """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
capture = Path(os.environ["QWEN_TEST_CAPTURE"])
(capture / "codex.json").write_text(json.dumps(sys.argv[1:]))
(capture / "prompt.bin").write_bytes(sys.stdin.buffer.read())
raise SystemExit(int(os.environ.get("QWEN_TEST_CODEX_EXIT", "0")))
"""
    )
    fake_codex.chmod(0o755)

    run("git", "-C", root, "add", ".")
    run("git", "-C", root, "commit", "-m", "fixture")
    run("git", "-C", root, "worktree", "add", "-b", "feature/test", worktree)

    env = os.environ.copy()
    env.update(
        PATH=f"{fake_bin}:{env['PATH']}",
        QWEN_TEST_CAPTURE=str(capture),
        QWEN_TEST_QUEUE_PID=str(tmp_path / "queue.pid"),
    )
    return Harness(root, worktree, launcher, env, capture, tmp_path / "queue.pid")


def queue_argv(harness: Harness) -> list[str]:
    return json.loads((harness.capture / "queue.json").read_text())


@pytest.mark.parametrize("model", ["qwen3.8-flash", "qwen3.8-max"])
def test_canonical_authoring_preserves_dirty_input(harness: Harness, model: str) -> None:
    run("git", "-C", harness.root, "switch", "-c", "feature/author")
    original = harness.root / "tracked.txt"
    original.write_text("user WIP\n")
    result = harness.invoke("--parent-reviewed", "--cloud-only", "--cloud-model", model,
                            target=harness.root)
    assert result.returncode == 0, result.stderr.decode()
    argv = queue_argv(harness)
    assert argv[:3] == ["--cloud-only", "--cloud-model", model]
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "project_doc_max_bytes=0" in argv
    assert 'features.shell_tool=false' in argv
    assert 'features.unified_exec=false' in argv
    assert original.read_text() == "user WIP\n"
    assert not (harness.root / ".git/biohub-implement.lock").exists()
    if model == "qwen3.8-max":
        prompt_text = (harness.capture / "prompt.bin").read_text()
        assert "User override 2026-09-14" in prompt_text
        assert "Authoring-only tasks" in prompt_text


@pytest.mark.parametrize("case", ["protected", "linked", "max", "missing_model"])
def test_canonical_authoring_rejects_before_queue(harness: Harness, case: str) -> None:
    args = ["--parent-reviewed", "--cloud-only", "--cloud-model", "qwen3.8-flash"]
    target = harness.root
    if case == "linked":
        target = harness.worktree
    if case == "max":
        args[-1] = "qwen3.8-max"
    if case == "missing_model":
        args = args[:2]
    result = harness.invoke(*args, target=target)
    assert result.returncode != 0
    assert not (harness.capture / "queue.json").exists()


def test_explicit_cloud_only_preserves_fixed_queue_input(harness: Harness) -> None:
    result = harness.invoke("--cloud-only")
    assert result.returncode == 0, result.stderr.decode()
    argv = queue_argv(harness)
    assert argv[:5] == ["--cloud-only", "--cloud-model", "qwen3.8-flash", "codex", "exec"]
    queue_input = argv[3:]
    assert "--interactive" not in argv
    assert queue_input[queue_input.index("--model") + 1] == "qwen38-flash-next"
    assert "--strict-config" in queue_input
    assert "--ignore-user-config" in queue_input
    overrides = [queue_input[index + 1] for index, arg in enumerate(queue_input[:-1]) if arg == "-c"]
    required = {
        'model_provider="qwen_flash_local"',
        'model_catalog_json="/Users/taichi/.codex-local-flash/models.json"',
        'model_reasoning_effort="none"',
        "model_context_window=32768",
        "model_auto_compact_token_limit=24000",
        "sandbox_workspace_write.network_access=false",
        "agents.enabled=false",
        "analytics.enabled=false",
        "features.shell_tool=false",
        "features.unified_exec=false",
        'web_search="disabled"',
    }
    assert required <= set(overrides)
    assert any(value.startswith("model_providers.qwen_flash_local={") for value in overrides)
    codex_argv = json.loads((harness.capture / "codex.json").read_text())
    assert codex_argv[0] == "exec"
    assert "--cloud-only" not in codex_argv
    prompt = (harness.capture / "prompt.bin").read_text()
    assert "exact qwen3.8-flash" in prompt
    assert "qwen_token_plan subscription-only" in prompt
    assert "fallback and transport retries zero" in prompt
    assert "Quota exhaustion, authentication failure, provider error" in prompt
    assert "Request retries, stream retries" in prompt
    assert "never start from a heartbeat or schedule" in prompt
    assert "bounded task" in prompt


@pytest.mark.parametrize("model", ["qwen3.8-flash"])
def test_cloud_selector_is_explicit_and_uses_noncontradictory_policy(harness: Harness, model: str) -> None:
    result = harness.invoke("--cloud-only", "--cloud-model", model)
    assert result.returncode == 0, result.stderr.decode()
    argv = queue_argv(harness)
    assert argv[:5] == ["--cloud-only", "--cloud-model", model, "codex", "exec"]
    prompt = (harness.capture / "prompt.bin").read_text()
    assert f"exact {model} through qwen_token_plan subscription-only" in prompt
    assert "supersedes historical Max/Plus/local-model names" in prompt
    assert "authoring-only tasks" in prompt
    assert "exactly `qwen3.7-plus`" not in prompt
    assert "fallback and transport retries zero" in prompt
    assert "never start from a heartbeat or schedule" in prompt
    assert not harness.lock.exists()


@pytest.mark.parametrize(
    "args",
    [
        ("--cloud-model", "qwen3.8-flash"),
        ("--interactive", "--cloud-model", "qwen3.8-flash"),
        ("--cloud-only", "--cloud-model"),
        ("--cloud-only", "--cloud-model=qwen3.8-flash"),
        ("--cloud-only", "--cloud-model", "qwen3.8-max-preview"),
        ("--cloud-only", "--cloud-model", "qwen3.8-max"),
        ("--cloud-only", "--cloud-model", "qwen38-flash-next"),
        ("--cloud-only", "--cloud-model=qwen3.8-max"),
        ("--interactive", "--cloud-model", "qwen3.8-max"),
        ("--cloud-only", "--cloud-model", "qwen3.7-plus"),
        ("--cloud-only", "--cloud-model", "qwen3.8-flash", "--cloud-model", "qwen3.8-flash"),
        ("--cloud-only", "--cloud-model", "qwen3.8-max", "--cloud-model", "qwen3.8-flash"),
    ],
)
def test_invalid_flash_selectors_do_not_reach_queue(harness: Harness, args: tuple[str, ...]) -> None:
    result = harness.invoke(*args)
    assert result.returncode == 2
    assert not (harness.capture / "queue.json").exists()
    assert not harness.lock.exists()


@pytest.mark.parametrize(
    "args",
    [(), ("--interactive",), ("--unknown",), ("--cloud-only", "--cloud-only")],
)
def test_missing_unknown_interactive_and_duplicate_flags_are_rejected(
    harness: Harness, args: tuple[str, ...]
) -> None:
    result = harness.invoke(*args)
    assert result.returncode == 2
    assert not (harness.capture / "queue.json").exists()


def test_cloud_only_after_worktree_is_rejected(harness: Harness) -> None:
    result = subprocess.run(
        [str(harness.launcher), str(harness.worktree), "--cloud-only"],
        input=b"bounded task\n",
        env=harness.env,
        capture_output=True,
    )
    assert result.returncode == 2
    assert not (harness.capture / "queue.json").exists()

    unknown = subprocess.run(
        [str(harness.launcher), "--cloud-only", "--unknown"],
        input=b"bounded task\n",
        env=harness.env,
        capture_output=True,
    )
    assert unknown.returncode == 2
    assert not (harness.capture / "queue.json").exists()


def test_primary_foreign_protected_and_detached_are_rejected(harness: Harness, tmp_path: Path) -> None:
    assert harness.invoke("--cloud-only", target=harness.root).returncode == 2

    foreign = tmp_path / "foreign"
    foreign_worktree = tmp_path / "foreign-worktree"
    run("git", "init", "-b", "develop", foreign)
    run("git", "-C", foreign, "config", "user.name", "Test User")
    run("git", "-C", foreign, "config", "user.email", "test@example.invalid")
    (foreign / "file").write_text("x")
    run("git", "-C", foreign, "add", ".")
    run("git", "-C", foreign, "commit", "-m", "fixture")
    run("git", "-C", foreign, "worktree", "add", "-b", "feature/foreign", foreign_worktree)
    assert harness.invoke("--cloud-only", target=foreign_worktree).returncode == 2

    run("git", "-C", harness.worktree, "switch", "-c", "main")
    assert harness.invoke("--cloud-only").returncode == 2
    run("git", "-C", harness.worktree, "switch", "--detach")
    assert harness.invoke("--cloud-only").returncode == 2


def test_dirty_and_hidden_index_flags_are_rejected(harness: Harness) -> None:
    (harness.worktree / "untracked").write_text("dirty")
    assert harness.invoke("--cloud-only").returncode == 2
    (harness.worktree / "untracked").unlink()

    run("git", "-C", harness.worktree, "update-index", "--assume-unchanged", "tracked.txt")
    assert harness.invoke("--cloud-only").returncode == 2
    run("git", "-C", harness.worktree, "update-index", "--no-assume-unchanged", "tracked.txt")

    run("git", "-C", harness.worktree, "update-index", "--skip-worktree", "tracked.txt")
    assert harness.invoke("--cloud-only").returncode == 2
    run("git", "-C", harness.worktree, "update-index", "--no-skip-worktree", "tracked.txt")


@pytest.mark.parametrize("mutation", ["dirty", "branch"])
def test_shim_rejects_state_changed_after_queue_admission(harness: Harness, mutation: str) -> None:
    env = harness.env.copy()
    env["QWEN_TEST_MUTATE"] = mutation
    result = subprocess.run(
        [str(harness.launcher), "--cloud-only", str(harness.worktree)],
        input=b"task\n",
        env=env,
        capture_output=True,
    )
    assert result.returncode == 2
    assert not (harness.capture / "codex.json").exists()


def test_exit_code_is_preserved_and_reaped_lock_is_released(harness: Harness) -> None:
    env = harness.env.copy()
    env["QWEN_TEST_CODEX_EXIT"] = "37"
    result = subprocess.run(
        [str(harness.launcher), "--cloud-only", str(harness.worktree)], input=b"task\n", env=env
    )
    assert result.returncode == 37
    assert not harness.lock.exists()


def wait_for(path: Path, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {path.name}")


def reset_test_signals() -> None:
    signals = {signal.SIGHUP, signal.SIGINT, signal.SIGTERM}
    signal.pthread_sigmask(signal.SIG_UNBLOCK, signals)
    for sig in signals:
        signal.signal(sig, signal.SIG_DFL)


@pytest.mark.parametrize(
    ("sig", "expected"),
    [(signal.SIGHUP, 129), (signal.SIGINT, 130), (signal.SIGTERM, 143)],
)
def test_same_worktree_is_exclusive_and_signal_releases_reaped_lock(
    harness: Harness, sig: signal.Signals, expected: int
) -> None:
    ready = harness.root.parent / "ready"
    release = harness.root.parent / "release"
    env = harness.env.copy()
    env.update(QWEN_TEST_READY=str(ready), QWEN_TEST_RELEASE=str(release))
    first = subprocess.Popen(
        [str(harness.launcher), "--cloud-only", str(harness.worktree)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
        preexec_fn=reset_test_signals,
    )
    try:
        assert first.stdin is not None
        first.stdin.write(b"task\n")
        first.stdin.close()
        wait_for(ready)
        assert harness.invoke("--cloud-only").returncode == 2
        first.send_signal(sig)
        assert first.wait(timeout=5) == expected
        assert (harness.capture / "signal.txt").read_text() == str(sig)
        assert not harness.lock.exists()
    finally:
        if first.poll() is None:
            first.send_signal(signal.SIGTERM)
            first.wait(timeout=5)


def test_unreaped_launch_retains_lock(harness: Harness) -> None:
    ready = harness.root.parent / "ready-kill"
    release = harness.root.parent / "release-kill"
    env = harness.env.copy()
    env.update(QWEN_TEST_READY=str(ready), QWEN_TEST_RELEASE=str(release))
    process = subprocess.Popen(
        [str(harness.launcher), "--cloud-only", str(harness.worktree)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    queue_pid: int | None = None
    try:
        assert process.stdin is not None
        process.stdin.write(b"task\n")
        process.stdin.close()
        wait_for(ready)
        queue_pid = int(harness.queue_pid.read_text())
        process.kill()
        assert process.wait(timeout=5) == -signal.SIGKILL
        assert harness.lock.is_dir()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if queue_pid is None and harness.queue_pid.exists():
            queue_pid = int(harness.queue_pid.read_text())
        if queue_pid is not None:
            try:
                os.kill(queue_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def test_signal_race_with_killed_queue_retains_lock(harness: Harness) -> None:
    ready = harness.root.parent / "ready-race"
    release = harness.root.parent / "release-race"
    env = harness.env.copy()
    env.update(
        QWEN_TEST_READY=str(ready),
        QWEN_TEST_RELEASE=str(release),
        QWEN_TEST_KILL_ON_SIGNAL="1",
    )
    process = subprocess.Popen(
        [str(harness.launcher), "--cloud-only", str(harness.worktree)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        assert process.stdin is not None
        process.stdin.write(b"task\n")
        process.stdin.close()
        wait_for(ready)
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=5) == 143
        assert harness.lock.is_dir()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_signal_style_queue_exit_retains_lock(harness: Harness) -> None:
    env = harness.env.copy()
    env["QWEN_TEST_CODEX_EXIT"] = "137"
    result = subprocess.run(
        [str(harness.launcher), "--cloud-only", str(harness.worktree)], input=b"task\n", env=env
    )
    assert result.returncode == 137
    assert harness.lock.is_dir()


def load_shared_queue():
    if not SHARED_QUEUE.is_file():
        pytest.skip("shared implementation queue is not installed on this host")
    loader = SourceFileLoader("qwen_implementation_queue", str(SHARED_QUEUE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shared_queue_validate_and_cloud_conversion_use_mock_metadata(
    harness: Harness, tmp_path: Path
) -> None:
    module = load_shared_queue()
    result = harness.invoke("--cloud-only")
    assert result.returncode == 0
    queued = queue_argv(harness)
    assert queued[:5] == ["--cloud-only", "--cloud-model", "qwen3.8-flash", "codex", "exec"]
    argv = queued[3:]
    module.validate(argv)

    config = tmp_path / "config.toml"
    catalog = tmp_path / "catalog.json"
    expected = module.CLOUD_EXPECTED
    config.write_text(
        "[model_providers.qwen_token_plan]\n"
        f"name = {json.dumps(expected['name'])}\n"
        f"base_url = {json.dumps(expected['base_url'])}\n"
        f"wire_api = {json.dumps(expected['wire_api'])}\n"
        "[model_providers.qwen_token_plan.auth]\n"
        f"command = {json.dumps(expected['auth']['command'])}\n"
        f"args = {json.dumps(expected['auth']['args'])}\n"
    )
    catalog.write_text(json.dumps({"models": [{"slug": module.CLOUD_MODEL}]}))
    module.CLOUD_CONFIG = config
    module.CLOUD_CATALOG = catalog
    converted = module.cloud_command(argv)
    assert converted[converted.index("--model") + 1] == "qwen3.7-plus"
    assert "--strict-config" in converted
    assert "--ignore-user-config" in converted
    overrides = [converted[index + 1] for index, arg in enumerate(converted[:-1]) if arg == "-c"]
    assert 'model_provider="qwen_token_plan"' in overrides
    provider = next(value for value in overrides if value.startswith("model_providers.qwen_token_plan={"))
    assert "request_max_retries=0" in provider
    assert "stream_max_retries=0" in provider
    assert 'model_reasoning_effort="none"' in overrides
    assert f'model_catalog_json="{catalog}"' in overrides
    assert all("qwen_flash_local" not in value for value in converted)

    # The existing implicit Plus route and its catalog remain untouched.
    parsed, interactive, cloud_only, model = module.parse_route(["--cloud-only", *argv])
    assert parsed == argv and not interactive and cloud_only and model == "qwen3.7-plus"
    flash_catalog = tmp_path / "flash-catalog.json"
    flash_catalog.write_text(json.dumps({"models": [{"slug": "qwen3.8-flash"}]}))
    module.CLOUD_FLASH_CATALOG = flash_catalog
    selected = queued
    parsed, interactive, cloud_only, model = module.parse_route(selected)
    assert parsed == argv and not interactive and cloud_only and model == "qwen3.8-flash"
    flash = module.cloud_command(parsed, model)
    assert flash[flash.index("--model") + 1] == "qwen3.8-flash"
    flash_overrides = [flash[index + 1] for index, arg in enumerate(flash[:-1]) if arg == "-c"]
    assert 'model_provider="qwen_token_plan"' in flash_overrides
    assert 'model_reasoning_effort="none"' in flash_overrides
    assert f'model_catalog_json="{flash_catalog}"' in flash_overrides
    assert provider in flash_overrides
    assert "model_context_window=32768" in flash_overrides
    assert module.cloud_command(argv) == converted

    max_catalog = tmp_path / "max-catalog.json"
    max_catalog.write_text(json.dumps({"models": [{"slug": "qwen3.8-max"}]}))
    module.CLOUD_MAX_CATALOG = max_catalog
    selected = ["--cloud-only", "--cloud-model", "qwen3.8-max", *argv]
    parsed, interactive, cloud_only, model = module.parse_route(selected)
    assert parsed == argv and not interactive and cloud_only and model == "qwen3.8-max"
    maximum = module.cloud_command(parsed, model)
    assert maximum[maximum.index("--model") + 1] == "qwen3.8-max"
    max_overrides = [maximum[index + 1] for index, arg in enumerate(maximum[:-1]) if arg == "-c"]
    assert f'model_catalog_json="{max_catalog}"' in max_overrides
    assert 'model_provider="qwen_token_plan"' in max_overrides
    assert 'model_reasoning_effort="none"' in max_overrides
    assert "model_context_window=32768" in max_overrides
    assert provider in max_overrides
    assert module.cloud_command(argv) == converted
    assert module.cloud_command(argv, "qwen3.8-flash") == flash
    max_catalog.write_text(json.dumps({"models": [{"slug": "qwen3.8-flash"}]}))
    with pytest.raises(SystemExit):
        module.cloud_command(argv, "qwen3.8-max")

    # A renamed or mixed catalog cannot silently select a different model.
    flash_catalog.write_text(json.dumps({"models": [{"slug": "qwen3.7-plus"}]}))
    with pytest.raises(SystemExit):
        module.cloud_command(argv, "qwen3.8-flash")
    with pytest.raises(SystemExit):
        module.cloud_command(argv, "qwen3.8-max-preview")
    config.write_text(config.read_text().replace(expected["base_url"], "https://example.invalid/payg"))
    with pytest.raises(SystemExit):
        module.cloud_command(argv)


@pytest.mark.parametrize(
    "prefix,suffix",
    [
        (["--cloud-model", "qwen3.8-flash"], []),
        (["--interactive", "--cloud-model", "qwen3.8-flash"], []),
        (["--cloud-only", "--cloud-model"], []),
        (["--cloud-only", "--cloud-model=qwen3.8-flash"], []),
        (["--cloud-only", "--cloud-model", "qwen3.8-max-preview"], []),
        (["--cloud-only", "--cloud-model=qwen3.8-max"], []),
        (["--interactive", "--cloud-model", "qwen3.8-max"], []),
        (["--cloud-only", "--cloud-model", "qwen3.7-plus"], []),
        (["--cloud-only", "--cloud-model", "qwen3.8-flash", "--cloud-model", "qwen3.8-flash"], []),
        (["--cloud-only"], ["--cloud-model", "qwen3.8-flash"]),
        (["--cloud-only"], ["--cloud-model", "qwen3.8-max"]),
        (["--cloud-only", "--cloud-model", "qwen3.8-max", "--cloud-model", "qwen3.8-flash"], []),
    ],
)
def test_shared_queue_rejects_bad_selector_before_model_or_auth(
    prefix: list[str], suffix: list[str]
) -> None:
    module = load_shared_queue()
    with pytest.raises(SystemExit):
        module.parse_route([*prefix, "codex", "exec", *suffix])
