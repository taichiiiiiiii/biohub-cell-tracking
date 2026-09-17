"""Guard tests for runner._load_runtime (pre-import + post-import binding checks)."""

import importlib
import types

import pytest

from scripts import e23_association_stage_diagnostic as runner

MODULE_NAMES = (
    "biohub.association_collection_audit",
    "biohub.association_stage_diagnostic",
    "biohub.evaluate",
    "biohub.io",
)

PREFIXES = ("biohub", "tracking_cellmot")


def _drop_project_modules(monkeypatch):
    for name in list(sys.modules):
        if name in PREFIXES or name.startswith(tuple(p + "." for p in PREFIXES)):
            monkeypatch.delitem(sys.modules, name, raising=False)


sys = __import__("sys")


def test_preloaded_project_runtime_refused_before_import(monkeypatch):
    calls = []

    def spy(name):
        calls.append(name)
        raise AssertionError("importlib.import_module must not be called")

    monkeypatch.setattr(importlib, "import_module", spy)
    monkeypatch.setitem(sys.modules, "biohub", types.SimpleNamespace())

    with pytest.raises(ValueError, match="preloaded project runtime"):
        runner._load_runtime([])

    assert calls == []


@pytest.mark.parametrize("changed", [False, True])
def test_binding_verified_before_and_after_imports(monkeypatch, tmp_path, changed):
    _drop_project_modules(monkeypatch)

    source = tmp_path / "source.py"
    source.write_bytes(b"before")
    binding = runner.d2.binding(source)

    calls = []

    def fake_import(name):
        calls.append(name)
        if changed and len(calls) == 1:
            source.write_bytes(b"after")
        return types.SimpleNamespace()

    monkeypatch.setattr(importlib, "import_module", fake_import)

    if changed:
        with pytest.raises(ValueError, match="changed"):
            runner._load_runtime([binding])
    else:
        modules = runner._load_runtime([binding])
        assert tuple(modules) == MODULE_NAMES

    assert calls == list(MODULE_NAMES)


def test_existing_output_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)

    out_dir = tmp_path / "outputs" / "local" / "existing"
    out_dir.mkdir(parents=True)
    sentinel = out_dir / "sentinel.txt"
    sentinel.write_text("keep")

    def _fail_collect(*args, **kwargs):
        raise AssertionError("must not bind")

    monkeypatch.setattr(runner, "collect_inputs", _fail_collect)

    with pytest.raises(ValueError, match="output exists"):
        runner.run(out_dir)

    assert sentinel.read_text() == "keep"
