from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_external_933_replay.py"
SPEC = importlib.util.spec_from_file_location("prepare_external_933_replay", SCRIPT)
assert SPEC and SPEC.loader
replay = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = replay
SPEC.loader.exec_module(replay)


def _json(path: Path, value: object) -> None:
    path.write_bytes(replay.canonical_json_bytes(value))


def _fixture(root: Path):
    root.mkdir()
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": ["source attribution\n"]},
            {"cell_type": "code", "metadata": {}, "source": ["x = 1\n"], "outputs": [], "execution_count": None},
        ],
    }
    notebook_name = "source.ipynb"
    view_name = "view.json"
    _json(root / notebook_name, notebook)
    sources = [(1, 2, "competitions/c"), (3, None, "datasets/a/b")]
    view = {
        "kernel": {"url": "/code/author/slug"},
        "kernelRun": {
            "id": 10,
            "kernelVersionNumber": 2,
            "status": "COMPLETE",
            "dataSources": [
                {"sourceId": source, "databundleVersionId": version, "mountSlug": mount}
                for source, version, mount in sources
            ],
        },
        "submission": {"id": 20, "sourceScriptVersionId": 10, "scoreFormatted": "0.933"},
    }
    _json(root / view_name, view)
    ast_hash, count = replay.canonical_ast_sha256(notebook)
    files = []
    for path in (root / notebook_name, root / view_name):
        files.append(
            {
                "filename": path.name,
                "bytes": path.stat().st_size,
                "sha256": replay.sha256_file(path),
                "role": "fixture",
            }
        )
    manifest = {"files": files}
    _json(root / "ARTIFACT_MANIFEST.json", manifest)
    spec = replay.ReplaySpec(
        reference_manifest_sha256=replay.sha256_file(root / "ARTIFACT_MANIFEST.json"),
        notebook_name=notebook_name,
        notebook_sha256=replay.sha256_file(root / notebook_name),
        canonical_ast_sha256=ast_hash,
        ast_python_major_minor=(sys.version_info.major, sys.version_info.minor),
        code_cells=count,
        view_model_name=view_name,
        view_model_sha256=replay.sha256_file(root / view_name),
        source_kernel_ref="author/slug",
        source_kernel_version=2,
        source_session_id=10,
        source_submission_id=20,
        source_score="0.933",
        data_source_tuples=tuple(sources),
    )
    return spec


def test_verify_and_stage_exact_source(tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    spec = _fixture(reference)
    verified = replay.verify_reference(reference, spec, ast_python=Path(sys.executable))
    assert verified["status"] == "VERIFIED_SOURCE_ONLY"
    assert verified["claims"]["account_replay_executed"] is False
    assert verified["claims"]["kernel_metadata_dataset_versions_resolved"] is False

    allowed = tmp_path / "staging"
    output = allowed / "run-1"
    receipt = replay.stage_replay(
        reference,
        output,
        allowed_root=allowed,
        kernel_id="owner/replay",
        spec=spec,
        ast_python=Path(sys.executable),
    )
    assert receipt["status"] == "STAGED_NOT_AUTHORIZED_TO_PUSH"
    assert "each dataset slug resolves to the pinned source version ID" in receipt["required_before_push"]
    assert (output / "READY.json").is_file()
    assert not (output / "INCOMPLETE").exists()
    assert replay.sha256_file(output / "package/external_933_replay.ipynb") == spec.notebook_sha256
    metadata = json.loads((output / "package/kernel-metadata.json").read_text())
    assert metadata["id"] == "owner/replay"
    assert metadata["enable_internet"] == "false"


def test_reference_rejects_ast_or_raw_byte_drift(tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    spec = _fixture(reference)
    notebook = json.loads((reference / spec.notebook_name).read_text())
    notebook["cells"][1]["source"] = ["x = 2\n"]
    _json(reference / spec.notebook_name, notebook)
    with pytest.raises(replay.ReplayPreparationError, match="identity mismatch|bytes drifted"):
        replay.verify_reference(reference, spec, ast_python=Path(sys.executable))


def test_reference_rejects_extra_and_symlink(tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    spec = _fixture(reference)
    (reference / "extra.txt").write_text("extra")
    with pytest.raises(replay.ReplayPreparationError, match="file set mismatch"):
        replay.verify_reference(reference, spec, ast_python=Path(sys.executable))
    (reference / "extra.txt").unlink()
    notebook = reference / spec.notebook_name
    outside = tmp_path / "outside"
    outside.write_bytes(notebook.read_bytes())
    notebook.unlink()
    os.symlink(outside, notebook)
    with pytest.raises(replay.ReplayPreparationError, match="non-symlink"):
        replay.verify_reference(reference, spec, ast_python=Path(sys.executable))


def test_view_binding_and_sources_are_exact(tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    spec = _fixture(reference)
    view = json.loads((reference / spec.view_model_name).read_text())
    view["submission"]["scoreFormatted"] = "0.934"
    _json(reference / spec.view_model_name, view)
    with pytest.raises(replay.ReplayPreparationError, match="identity mismatch|bytes drifted"):
        replay.verify_reference(reference, spec)


def test_stage_is_no_clobber_and_scoped(tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    spec = _fixture(reference)
    allowed = tmp_path / "allowed"
    output = allowed / "run"
    replay.stage_replay(
        reference,
        output,
        allowed_root=allowed,
        kernel_id="owner/replay",
        spec=spec,
        ast_python=Path(sys.executable),
    )
    with pytest.raises(replay.ReplayPreparationError, match="refusing to reuse"):
        replay.stage_replay(
            reference,
            output,
            allowed_root=allowed,
            kernel_id="owner/replay",
            spec=spec,
            ast_python=Path(sys.executable),
        )
    with pytest.raises(replay.ReplayPreparationError, match="child of"):
        replay.stage_replay(
            reference,
            tmp_path / "outside",
            allowed_root=allowed,
            kernel_id="owner/replay",
            spec=spec,
            ast_python=Path(sys.executable),
        )


def test_canonical_ast_ignores_comments_but_not_behavior() -> None:
    first = {"cells": [{"cell_type": "code", "source": "x = 1\n"}]}
    comment = {"cells": [{"cell_type": "code", "source": "# note\nx = 1\n"}]}
    changed = {"cells": [{"cell_type": "code", "source": "x = 2\n"}]}
    assert replay.canonical_ast_sha256(first) == replay.canonical_ast_sha256(comment)
    assert replay.canonical_ast_sha256(first) != replay.canonical_ast_sha256(changed)
    assert ast.dump(ast.parse("x = 1"), include_attributes=False)
