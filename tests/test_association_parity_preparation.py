"""Static notebook assembly only; its GPU cells are never executed locally."""

import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def loader():
    spec = importlib.util.spec_from_file_location(
        "prepare_association", ROOT / "scripts/experiments/e23/prepare_e23_association_parity.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_private_offline_notebook_preserves_config_and_source_patch():
    if not (ROOT / "outputs/kaggle/e23_reference").exists():
        pytest.skip("local frozen public-four reference unavailable")
    prepared = loader().build(ROOT)
    metadata = prepared["metadata"]
    assert metadata["is_private"] == "true" and metadata["enable_internet"] == "false"
    assert metadata["machine_shape"] == "NvidiaTeslaT4"
    assert metadata["competition_sources"] == ["biohub-cell-tracking-during-development"]
    assert len(metadata["dataset_sources"]) == 3
    assert prepared["receipt"]["reference_count"] == 4
    assert prepared["receipt"]["source_executed_locally"] is False
    texts = []
    for cell in prepared["notebook"]["cells"]:
        if cell["cell_type"] == "code":
            text = "".join(cell["source"])
            ast.parse(text)
            assert not cell["outputs"] and cell["execution_count"] is None
            texts.append(text)
    assert sum("D3_RESULT = supervise(" in text for text in texts) == 1
    assert all("competitions submit" not in text for text in texts)
    assert not any('start_time = time.time()\navailable_gpu_count' in text for text in texts)
    assert any('BIOHUB_DUAL_SEED_EDGE_THRESHOLD"] = "0.48"' in text for text in texts)


def test_unpinned_notebook_rejected_before_output(tmp_path):
    folder = tmp_path / "notebooks/pub923_repro"
    folder.mkdir(parents=True)
    (folder / "pub923_repro.ipynb").write_text("{}")
    with pytest.raises(ValueError, match="notebook SHA mismatch"):
        loader().build(tmp_path)
