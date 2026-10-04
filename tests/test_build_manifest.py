from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_manifest.py"
_spec = importlib.util.spec_from_file_location("build_manifest_under_test", SCRIPT)
manifest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(manifest)


def test_run_page_retries_transient_failure(monkeypatch):
    results = iter(
        [
            SimpleNamespace(returncode=1, stdout="", stderr="temporary failure"),
            SimpleNamespace(returncode=0, stdout="name,size,creationDate\n", stderr=""),
        ]
    )
    delays = []
    monkeypatch.setattr(manifest.subprocess, "run", lambda *args, **kwargs: next(results))
    monkeypatch.setattr(manifest.time, "sleep", delays.append)

    assert manifest.run_page(["kaggle"], page=7) == "name,size,creationDate\n"
    assert delays == [1]


def test_run_page_stops_after_bounded_attempts(monkeypatch):
    monkeypatch.setattr(manifest, "MAX_ATTEMPTS", 2)
    monkeypatch.setattr(
        manifest.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="\nAPI unavailable\n"
        ),
    )
    monkeypatch.setattr(manifest.time, "sleep", lambda delay: None)

    with pytest.raises(SystemExit, match="page 3 failed after 2 attempts: API unavailable"):
        manifest.run_page(["kaggle"], page=3)
