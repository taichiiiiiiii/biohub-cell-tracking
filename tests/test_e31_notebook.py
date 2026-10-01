"""Tests for scripts/prepare_e31_submission.py builder and e31_dual_gpu_runtime entry."""

import hashlib
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import torch


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def globals_dict(tmp_path):
    d = tmp_path / "dummy"
    d.mkdir()
    paths = {
        "WORKING_DIR": str(d / "work"),
        "REPO_DIR": str(d / "repo"),
        "TEST_DIR": str(d / "test"),
        "_ps": str(d / "ps"),
        "_primary_materialized_path": str(d / "primary"),
        "_deepcenter_materialized_path": str(d / "deepcenter"),
        "SECONDARY_WEIGHTS_PATH": str(d / "secondary_weights"),
    }
    g = {k: v for k, v in paths.items()}
    g["E31_HASHES"] = {}
    g["payloadroot"] = d / "payload"
    return g


def _load_entry_text():
    p = Path("scripts/experiments/e31/e31_dual_gpu_runtime.py")
    return p.read_text(encoding="utf-8")


def _run_entry(globals_dict, monkeypatch, device_count, cuda_visible=None):
    captured = {}

    def fake_run_workers(job, payloadroot, cuda_tokens):
        captured["job"] = job
        captured["payloadroot"] = payloadroot
        captured["cuda_tokens"] = list(cuda_tokens)

    monkeypatch.setattr("torch.cuda.device_count", lambda: device_count)
    if cuda_visible is not None:
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", cuda_visible)
    else:
        monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)

    import biohub.e31_shards as shards_mod

    monkeypatch.setattr(shards_mod, "run_workers", fake_run_workers)

    src = _load_entry_text()
    exec(compile(src, "e31_dual_gpu_runtime.py", "exec"), globals_dict)
    return captured


def test_success_empty_cuda_visible_devices(globals_dict, monkeypatch):
    cap = _run_entry(globals_dict, monkeypatch, device_count=2, cuda_visible="")
    assert cap["cuda_tokens"] == ["0", "1"]
    job = cap["job"]
    assert job["E31_HASHES"] == {}
    assert str(job["_ps"]) != str(job["_primary_materialized_path"])
    assert cap["payloadroot"] == globals_dict["payloadroot"]
    expected_keys = {
        "WORKING_DIR",
        "REPO_DIR",
        "TEST_DIR",
        "_ps",
        "_primary_materialized_path",
        "_deepcenter_materialized_path",
        "SECONDARY_WEIGHTS_PATH",
        "E31_HASHES",
    }
    assert set(job.keys()) == expected_keys

    path_keys = [
        "WORKING_DIR",
        "REPO_DIR",
        "TEST_DIR",
        "_primary_materialized_path",
        "_deepcenter_materialized_path",
        "SECONDARY_WEIGHTS_PATH",
        "_ps",
    ]
    for key in path_keys:
        assert job[key] == Path(globals_dict[key])


def test_success_explicit_two_devices(globals_dict, monkeypatch):
    cap = _run_entry(globals_dict, monkeypatch, device_count=2, cuda_visible="2,5")
    assert cap["cuda_tokens"] == ["2", "5"]
    job = cap["job"]
    assert str(job["SECONDARY_WEIGHTS_PATH"]) == globals_dict["SECONDARY_WEIGHTS_PATH"]
    assert job["_primary_materialized_path"] == Path(globals_dict["_primary_materialized_path"])


@pytest.mark.parametrize(
    "count,bad",
    [
        (1, ""),
        (2, "-1,1"),
        (2, "0,0"),
        (2, "0,"),
        (2, "0"),
    ],
)
def test_gpu_failure_raises(count, bad, monkeypatch, globals_dict):
    mock_run_workers = MagicMock()
    monkeypatch.setattr(torch.cuda, "device_count", lambda: count)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", bad)
    monkeypatch.setattr("biohub.e31_shards.run_workers", mock_run_workers)

    with pytest.raises(RuntimeError):
        exec(compile(_load_entry_text(), "<entry>", "exec"), globals_dict)

    mock_run_workers.assert_not_called()


def test_builder_outputs_and_receipt_hashes():
    repo = Path(".")
    spec = importlib.util.spec_from_file_location(
        "prepare_e31_submission", repo / "scripts" / "experiments" / "e31" / "prepare_e31_submission.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    result = mod.build(repo)

    assert set(result.keys()) >= {"notebook", "metadata", "receipt"}
    receipt = result["receipt"]
    assert "payloadhashes" in receipt
    assert "E31_HASHES" not in receipt

    ph = receipt["payloadhashes"]
    assert "src/biohub/e31_shards.py" in ph
    assert "scripts/experiments/e31/e31_submission_runtime.py" in ph
    for rel, expected in ph.items():
        actual = _sha((repo / rel).read_text(encoding="utf-8"))
        assert actual == expected, f"hash mismatch for {rel}"

    nb_src = result["notebook"]
    last_code = None
    for cell in nb_src.get("cells", []):
        if cell.get("cell_type") == "code":
            last_code = "".join(cell.get("source", []))
    runtime_text = (repo / "scripts" / "experiments" / "e31" / "e31_dual_gpu_runtime.py").read_text(encoding="utf-8")
    assert last_code is not None and last_code.strip() == runtime_text.strip()
    assert _sha(runtime_text) == receipt.get("runtimehash")

    meta = result["metadata"]
    assert meta.get("enable_internet") == "false"
    assert str(meta.get("is_private")) == "true"
