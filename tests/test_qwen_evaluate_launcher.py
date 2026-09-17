from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    loader = SourceFileLoader("evaluate_test_module", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def evaluator():
    return load(ROOT / ".codex/bin/qwen-evaluate")


@pytest.fixture
def packet():
    return {"reason": "multi-module", "acceptance": "existing contract unchanged",
            "changed_files": ["src/example.py"], "diff": "--- a/src/example.py\n+++ b/src/example.py\n-x\n+y",
            "test_results": "focused tests passed", "context": ""}


@pytest.mark.parametrize("mutation", [
    {"parent_confirmed": False}, {"secrets_checked": 1}, {"minimal_context": False},
    {"history": "full conversation"}, {"logs": "dump"}, {"reason": "routine"}, {"reason": []},
    {"changed_files": ["../secret"]}, {"changed_files": [".env"]}, {"changed_files": ["auth.json"]},
    {"changed_files": ["x"] * 13}, {"changed_files": ["x", "x"]}, {"changed_files": [None]},
    {"acceptance": ""}, {"diff": "x" * 16385}, {"context": "x" * 4097},
    {"diff": "+++ b/not-declared.py"}, {"test_results": "Authorization: Bearer sentinel"},
    {"context": "https://example.invalid?X-Amz-Signature=sentinel"},
    {"context": "api_key=sentinel-secret-value"}, {"context": "-----BEGIN PRIVATE KEY-----"},
])
def test_bad_inputs_rejected(evaluator, packet, mutation):
    packet.update(mutation)
    with pytest.raises(ValueError, match="rejected"):
        evaluator.validate(json.dumps(packet).encode())


@pytest.mark.parametrize("raw", [b"", b"[]", b"invalid", b"\xff", b"x" * 32769, b'{"x":1,"x":2}'])
def test_malformed(evaluator, raw):
    with pytest.raises(ValueError):
        evaluator.validate(raw)


@pytest.mark.parametrize("key", ["reason", "acceptance", "changed_files", "diff", "test_results", "context"])
def test_missing_or_duplicate_contract_key(evaluator, packet, key):
    missing = dict(packet)
    missing.pop(key)
    with pytest.raises(ValueError):
        evaluator.validate(json.dumps(missing).encode())
    duplicate = json.dumps(packet)[:-1] + "," + json.dumps(key) + ":" + json.dumps(packet[key]) + "}"
    with pytest.raises(ValueError):
        evaluator.validate(duplicate.encode())


def test_help_never_calls_queue(evaluator, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["qwen-evaluate", "--help"])
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("must not launch"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("must not launch"))
    assert evaluator.main() == 0
    assert "--parent-reviewed < evaluation.json" in capsys.readouterr().out


def test_queue_conversion_offline(evaluator, packet, tmp_path):
    assert evaluator.validate(json.dumps(packet).encode()) == packet
    queue = load(Path("/Users/taichi/.local/bin/qwen-implementation-queue"))
    argv, interactive, cloud_only, model = queue.parse_route(evaluator.command()[1:])
    assert not interactive and cloud_only and model == "qwen3.8-max"
    config = tmp_path / "config.toml"
    config.write_text("[model_providers]\nqwen_token_plan=" + queue.toml_literal(queue.CLOUD_EXPECTED))
    catalog = tmp_path / "models.json"
    catalog.write_text(json.dumps({"models": [{"slug": model}]}))
    queue.CLOUD_CONFIG, queue.CLOUD_MAX_CATALOG = config, catalog
    converted = queue.cloud_command(argv, model)
    assert converted[converted.index("--model") + 1] == model
    assert converted[converted.index("--sandbox") + 1] == "read-only"
    assert 'model_provider="qwen_token_plan"' in converted
    assert 'model_reasoning_effort="none"' in converted
    assert "project_doc_max_bytes=0" in converted
    for flag in ("shell_tool", "unified_exec", "apps", "plugins", "remote_plugin"):
        assert f"features.{flag}=false" in converted
    provider = next(x for x in converted if x.startswith("model_providers.qwen_token_plan="))
    assert "request_max_retries=0" in provider and "stream_max_retries=0" in provider
    assert not any("127.0.0.1" in x or "qwen_flash_local" in x for x in converted)


@pytest.mark.parametrize("queue_status", [0, 2])
def test_fake_queue_one_call_only(evaluator, packet, tmp_path, monkeypatch, queue_status):
    # No real queue, Codex, auth helper or provider process is executed.
    captured = tmp_path / "capture"
    fake = tmp_path / "fake_queue.py"
    fake.write_text("import pathlib,sys\n"
                    f"p=pathlib.Path({str(captured)!r})\n"
                    "assert not p.exists()\np.write_bytes(sys.stdin.buffer.read())\n"
                    f"sys.exit({queue_status})\n")
    monkeypatch.setattr(evaluator, "command", lambda: [sys.executable, str(fake)])
    monkeypatch.setattr(sys, "argv", ["qwen-evaluate", "--parent-reviewed"])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(packet).encode())))
    assert evaluator.main() == (0 if queue_status == 0 else 1)
    text = captured.read_text()
    assert "UNTRUSTED REVIEW DATA" in text
    assert "Do not reimplement" in text


@pytest.mark.parametrize("args", [[], ["--cloud-only"], ["--parent-supervised"],
                                 ["--parent-supervised", "--cloud-only"], ["--parent-reviewed", "--cloud-only"],
                                 ["--parent-reviewed", "--model", "qwen3.8-flash"], ["--help", "--parent-reviewed"]])
def test_no_route_override(evaluator, args, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["qwen-evaluate", *args])
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(ValueError):
        evaluator.main()


def test_secret_never_reaches_queue(evaluator, packet, monkeypatch):
    packet["context"] = "password=sentinel"
    monkeypatch.setattr(sys, "argv", ["qwen-evaluate", "--parent-reviewed"])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(packet).encode())))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(ValueError) as error:
        evaluator.main()
    assert "sentinel" not in str(error.value)


def test_protected_branch_never_reaches_queue(evaluator, packet, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["qwen-evaluate", "--parent-reviewed"])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(packet).encode())))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 0, "main\n"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(ValueError):
        evaluator.main()
