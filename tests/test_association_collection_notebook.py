"""Static collection notebook preparation; no GPU cell execution."""

import ast
from pathlib import Path

import pytest

from scripts.prepare_e23_association_collection_notebook import build
from scripts.prepare_e23_association_parity import build as build_parity

ROOT = Path(__file__).resolve().parents[1]


def test_notebook_preserves_model_source_and_uses_literal_serial_groups():
    if not (ROOT / "outputs/local/e23_association_collection_20260908/REFERENCE_PLAN.json").exists():
        pytest.skip("local frozen collection reference unavailable")
    prepared = build(ROOT)
    parity = build_parity(ROOT)
    for index in (2, 3, 4, 6, 7):
        assert prepared["notebook"]["cells"][index] == parity["notebook"]["cells"][index]
    texts = []
    for cell in prepared["notebook"]["cells"]:
        if cell["cell_type"] == "code":
            text = "".join(cell["source"])
            ast.parse(text)
            assert not cell["outputs"]
            texts.append(text)
    assert len(texts) == 9
    assert sum("D3_COLLECTION = supervise_collection(" in s for s in texts) == 1
    assert not any("D3_RESULT = supervise(" in s or "competitions submit" in s for s in texts)
    assert 'D3_TRAIN_IMAGES = COMP_DIR / "train"' in texts[4]
    assert "D3_INVENTORY == D3_EXPECTED_SOURCE" in texts[-2]
    assert len(prepared["receipt"]["runtime_source_pins"]) == 25
    meta = prepared["metadata"]
    assert meta["is_private"] == "true" and meta["enable_internet"] == "false"
    assert meta["enable_gpu"] == "true" and meta["machine_shape"] == "NvidiaTeslaT4"
    assert meta["competition_sources"] == ["biohub-cell-tracking-during-development"]
    assert len(meta["dataset_sources"]) == 3
    assert not prepared["receipt"]["submission_authorized"]
