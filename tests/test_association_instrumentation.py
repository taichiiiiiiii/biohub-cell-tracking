"""Text/AST only: no execution/import of external model source."""

import ast
from pathlib import Path

import pytest

from biohub.association_instrumentation import SOURCE_SHA256, instrument_source

RECONSTRUCTION = (Path(__file__).resolve().parents[1] / "outputs/local/"
                  "e23_association_capture_d3_20260908/prospective_e23_predict.py.txt")


def test_pinned_source_insertion_preserves_original_program():
    if not RECONSTRUCTION.is_file():
        pytest.skip("local static source reconstruction unavailable")
    source = RECONSTRUCTION.read_text()
    patched, receipt = instrument_source(source)
    assert receipt["original_sha256"] == SOURCE_SHA256
    assert receipt["restored_bytes_equal"] and receipt["restored_ast_equal"]
    assert not receipt["source_executed"] and not receipt["inference_parity_verified"]
    assert not receipt["submission_authorized"]
    # Calls to all model functions, softmax, sorting and ILP remain identical.
    def model_calls(text):
        return [ast.dump(node) for node in ast.walk(ast.parse(text)) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr in
                {"predict_edges", "encode", "_index_features", "solve", "softmax"}]
    assert model_calls(source) == model_calls(patched)
    tree = ast.parse(patched)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for name in ("predict", "predict_video", "build_graph"):
        assert functions[name].args.args[-1].arg == "association_observer"
        assert isinstance(functions[name].args.defaults[-1], ast.Constant)
        assert functions[name].args.defaults[-1].value is None


def test_unknown_or_double_instrumented_source_rejected():
    with pytest.raises(ValueError, match="SHA mismatch"):
        instrument_source("def predict(): pass\n")
    if RECONSTRUCTION.is_file():
        patched, _ = instrument_source(RECONSTRUCTION.read_text())
        with pytest.raises(ValueError, match="SHA mismatch"):
            instrument_source(patched)
