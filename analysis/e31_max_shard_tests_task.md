Issue17 activeGoal QwenCloud Max authoring no tools. Return ONLY appended test functions for tests/test_e31_submission_runtime.py (no repeats of existing file). Runtime has optional injected globals E31_ASSIGNED_STEMS: absent default; present exact list nonempty sorted unique exact strings subset discovered stems, otherwise TypeError/ValueError, even explicit None invalid. E31_WORKER_TAG exact str among empty/0/1 chooses exclusive predictor filename e31_predict.py/e31_predict_0.py/e31_predict_1.py. New guards run before predictor write. Test actual RUNTIME_SOURCE, not copied implementation. Add parameterized invalid assignments and tags (including subclasses), success subset ['b'] after adding b.zarr and c.zarr to existing a fixture; assert splits and receipt only b, generated filename for tag0/1, geffs passed postproc only b. Mock postproc writes _write_csv with [p.stem for p in geffs], not all TEST_DIR. Existing default tests cover no injection. Include malicious tag/path attempts. Return <=100 lines appended functions. CURRENT FILE:
"""tests/test_e31_submission_runtime.py — exec-based runtime validation."""

import csv
import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

RUNTIME_PATH = Path(__file__).resolve().parents[1] / "scripts" / "e31_submission_runtime.py"
RUNTIME_SOURCE = RUNTIME_PATH.read_text(encoding="utf-8")

FAKE_PREDICTOR_SOURCE = """\
import dataspec
import json
from types import SimpleNamespace

PredictConfig = SimpleNamespace

def predict(**kwargs):
    assert not kwargs['evaluate']
    assert kwargs['association_observer'] is not None
    cfg = kwargs['cfg']
    assert cfg.det_threshold == 0.96875
    assert cfg.use_ilp is True
    assert cfg.ilp_edge_weight == -1.0
    assert cfg.ilp_appearance_weight == 0.0
    assert cfg.ilp_disappearance_weight == 1.5
    assert cfg.ilp_division_weight == 1.0
    splits_path = kwargs['splits_file']
    with open(splits_path, 'r', encoding='utf-8') as f:
        splits = json.load(f)
    test_names = splits[0]['test']
    pred_root = dataspec.PREDICTIONS_PATH
    pred_root.mkdir(parents=True, exist_ok=True)
    for name in test_names:
        (pred_root / f"{name}.geff").mkdir(parents=True, exist_ok=True)
"""

CSV_COLUMNS = [
    "id",
    "dataset",
    "row_type",
    "node_id",
    "t",
    "z",
    "y",
    "x",
    "source_id",
    "target_id",
]


def _write_csv(path, mode, stems):
    rows = []
    rid = 0
    ds = stems[0]
    if mode == "invalid_duplicate":
        rows.append(
            {
                "id": rid,
                "dataset": ds,
                "row_type": "node",
                "node_id": 10,
                "t": 0,
                "z": 0,
                "y": 0,
                "x": 0,
                "source_id": -1,
                "target_id": -1,
            }
        )
        rid += 1
        rows.append(
            {
                "id": rid,
                "dataset": ds,
                "row_type": "node",
                "node_id": 10,
                "t": 1,
                "z": 0,
                "y": 0,
                "x": 0,
                "source_id": -1,
                "target_id": -1,
            }
        )
    elif mode == "invalid_edge":
        rows.append(
            {
                "id": rid,
                "dataset": ds,
                "row_type": "node",
                "node_id": 10,
                "t": 0,
                "z": 0,
                "y": 0,
                "x": 0,
                "source_id": -1,
                "target_id": -1,
            }
        )
        rid += 1
        rows.append(
            {
                "id": rid,
                "dataset": ds,
                "row_type": "edge",
                "node_id": -1,
                "t": -1,
                "z": -1,
                "y": -1,
                "x": -1,
                "source_id": 10,
                "target_id": 99,
            }
        )
    elif mode == "invalid_bounds":
        rows.append(
            {
                "id": rid,
                "dataset": ds,
                "row_type": "node",
                "node_id": 10,
                "t": 0,
                "z": 0,
                "y": 0,
                "x": 4,
                "source_id": -1,
                "target_id": -1,
            }
        )
    else:
        rows.append(
            {
                "id": rid,
                "dataset": ds,
                "row_type": "node",
                "node_id": 10,
                "t": 0,
                "z": 0,
                "y": 0,
                "x": 0,
                "source_id": -1,
                "target_id": -1,
            }
        )
        rid += 1
        rows.append(
            {
                "id": rid,
                "dataset": ds,
                "row_type": "node",
                "node_id": 20,
                "t": 1,
                "z": 0,
                "y": 0,
                "x": 0,
                "source_id": -1,
                "target_id": -1,
            }
        )
        rid += 1
        rows.append(
            {
                "id": rid,
                "dataset": ds,
                "row_type": "edge",
                "node_id": -1,
                "t": -1,
                "z": -1,
                "y": -1,
                "x": -1,
                "source_id": 10,
                "target_id": 20,
            }
        )
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def runtime_env(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    scripts_dir = repo_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    test_dir = tmp_path / "test"
    test_dir.mkdir()
    zarr_a = test_dir / "a.zarr"
    zarr_a.mkdir()

    weights_primary = tmp_path / "weights_primary.pt"
    weights_primary.write_bytes(b"\x00")
    weights_secondary = tmp_path / "weights_secondary.pt"
    weights_secondary.write_bytes(b"\x00")

    dc_weights = tmp_path / "dc" / "weights" / "full_frame_center" / "best.pt"
    dc_weights.parent.mkdir(parents=True)
    dc_weights.write_bytes(b"\x00")
    dc_manifest = tmp_path / "dc" / "ARTIFACT_MANIFEST.json"
    dc_manifest.write_text("{}", encoding="utf-8")

    fake_ps = tmp_path / "predictor_src.py"
    fake_ps.write_text("# placeholder predictor source\n", encoding="utf-8")

    env = {
        "WORKING_DIR": working_dir,
        "REPO_DIR": repo_dir,
        "TEST_DIR": test_dir,
        "_ps": fake_ps,
        "_primary_materialized_path": weights_primary,
        "_deepcenter_materialized_path": dc_weights,
        "SECONDARY_WEIGHTS_PATH": weights_secondary,
        "E31_HASHES": {},
    }

    monkeypatch.setenv("BIOHUB_BIDIRECTIONAL_EDGE_WEIGHT", "0.30")
    monkeypatch.setenv("BIOHUB_SECONDARY_WEIGHTS", str(weights_secondary))
    monkeypatch.setenv("BIOHUB_SECONDARY_EDGE_WEIGHT", "0.15")
    monkeypatch.setenv("BIOHUB_BIDIRECTIONAL_FUSION_MODE", "harmonic_probability")

    dataspec_mod = types.ModuleType("dataspec")
    dataspec_mod.PREDICTIONS_PATH = working_dir / "e31_predictions"
    monkeypatch.setitem(sys.modules, "dataspec", dataspec_mod)
    monkeypatch.setitem(sys.modules, "e31_predict", types.ModuleType("e31_predict"))

    def fake_instrument_source(src):
        return FAKE_PREDICTOR_SOURCE, {"instrumented": True}

    from biohub import association_instrumentation

    monkeypatch.setattr(association_instrumentation, "instrument_source", fake_instrument_source)

    from biohub import output_bounds

    monkeypatch.setattr(output_bounds, "read_output_shape", lambda *a, **k: (2, 2, 4, 4))

    from biohub import screen_output_bounds

    monkeypatch.setattr(screen_output_bounds, "verify_screen_output_bounds", lambda *a, **k: None)

    from biohub.public_postproc import deepcenter as dc_mod

    monkeypatch.setattr(dc_mod, "load_deepcenter_veto_detector_e31_target", lambda cfg, ckpt, mf: ({}, {"stub": True}))

    return env


def configure(mode):
    """Factory returning a fixture-compatible parametrization marker."""
    return mode


@pytest.mark.parametrize("mode", ["success", "invalid_duplicate", "invalid_edge", "invalid_bounds"])
def test_submission_runtime_modes(mode, runtime_env, monkeypatch):
    from biohub.public_postproc import pipeline

    def fake_run_postproc_core(geffs, out_csv, cfg, **kwargs):
        assert cfg.OUTPUT_MOTION_RELINK
        assert cfg.USE_DEEPCENTER_VETO
        assert cfg.REQUIRE_DEEPCENTER_VETO
        assert kwargs.get("exclusive_output") is True
        assert callable(kwargs.get("consensus_loader"))
        bundle = kwargs["deepcenter_loader"](cfg)
        assert isinstance(bundle, dict)
        _write_csv(out_csv, mode, [p.stem for p in runtime_env["TEST_DIR"].glob("*.zarr")])

    monkeypatch.setattr(pipeline, "run_postproc_core", fake_run_postproc_core)

    globals_dict = dict(runtime_env)
    code = compile(RUNTIME_SOURCE, "<e31_submission_runtime>", "exec")

    if mode == "success":
        exec(code, globals_dict)
        receipt_path = runtime_env["WORKING_DIR"] / "e31_submission_receipt.json"
        assert receipt_path.exists()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        csv_path = runtime_env["WORKING_DIR"] / "submission.csv"
        expected_sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        assert receipt["csv_sha256"] == expected_sha
        assert receipt["stems"] == ["a"]
        assert (runtime_env["WORKING_DIR"] / "e31_output_bounds.json").exists()
        assert (runtime_env["REPO_DIR"] / "scripts" / "e31_predict.py").exists()
    else:
        with pytest.raises(AssertionError):
            exec(code, globals_dict)


def test_existing_geff_rejected_before_predictor(runtime_env, monkeypatch):
    (runtime_env["TEST_DIR"] / "a.geff").mkdir()

    from biohub.public_postproc import pipeline

    monkeypatch.setattr(pipeline, "run_postproc_core", lambda *a, **k: None)

    globals_dict = dict(runtime_env)
    code = compile(RUNTIME_SOURCE, "<e31_submission_runtime>", "exec")
    with pytest.raises(AssertionError):
        exec(code, globals_dict)


def test_rerun_raises_file_exists_error(runtime_env, monkeypatch):
    from biohub.public_postproc import pipeline

    call_count = {"n": 0}

    def fake_run_postproc_core(geffs, out_csv, cfg, **kwargs):
        call_count["n"] += 1
        _write_csv(out_csv, "success", [p.stem for p in runtime_env["TEST_DIR"].glob("*.zarr")])

    monkeypatch.setattr(pipeline, "run_postproc_core", fake_run_postproc_core)

    globals_dict = dict(runtime_env)
    code = compile(RUNTIME_SOURCE, "<e31_submission_runtime>", "exec")
    exec(code, globals_dict)
    assert call_count["n"] == 1

    # Second exec must fail because predict script already exists (open "x")
    with pytest.raises(FileExistsError):
        exec(code, globals_dict)

