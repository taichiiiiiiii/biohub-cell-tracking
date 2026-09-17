Issue17 Qwen Max authoring-only no tools. Return complete tests/test_e31_submission_runtime.py <=200lines. Test actual notebook runtime via exec(compile(runtime.read_text(),str(runtime),"exec"),globalsdict). pytest tmp_path monkeypatch, noGPU/GT/network. No change appcode. Fixture use real build_config, real ScreenNodeSerializer but stub verify_screen_output_bounds (separate191tests alreadycover) and stub deepcenterloader 3args returns ({},{}). Monkeypatch biohub.association_instrumentation.instrument_source returns tiny Python fake predictor source, receipt. Fake predictor source: import dataspec,json; from types import SimpleNamespace; PredictConfig=SimpleNamespace; def predict(**kwargs): assert not kwargs['evaluate']; check association_observer exists and kwargscfg exact; read testnames splitsjson; create dataspec.PREDICTIONS_PATH/<name>.geff dirs. No actual observers hooks necessary as mock bypasses source. monkeypatch sys.modules['dataspec']=ModuleType with dummyPREDICTIONS_PATH; monkeypatch.setitem sys.modules 'e31_predict' placeholder so restored on teardown. metadata shapes stub output_bounds.read_output_shape -> (2,2,4,4).
tmp paths repo/scripts, working,test/a.zarr,weightsprimary,secondary,dc/weights/full_frame_center/best.pt and dc/ARTIFACT_MANIFEST.json; create only tmp files. globals WORKING_DIR,REPO_DIR,TEST_DIR,_ps fakepath,_primary_materialized_path,_deepcenter_materialized_path,SECONDARY_WEIGHTS_PATH,E31_HASHES={}. env4exactkeys seenruntime.
Stub pipeline.run_postproc_core(geffs,out_csv,cfg,**kwargs) assert cfg flags, strict bundlecallback returns dict, exclusive_output true, consensus_loader callable; write CSV via csv.DictWriter real CSV_COLUMNS. Basic rows 2nodes ids10/20 t0/1 and edge10->20 allcoords0; 3rows sequential ids; nodes endpoints-1 edges nodecoords-1. Introduce mode invalid_duplicate (duplicate nid10 for secondnode), invalid_edge (target99), invalid_bounds (x4); valid mode leaves unchanged. Use request.param for modes or factory fixture function configure(mode).
Tests param success and3invalid cases use pytest.raises AssertionError forinvalid, on success assert submissionreceipt csvhash and stems and real files. Additional tests input .geff rejected before predictor and rerun raisesFileExistsError. No tests claim physicalparity. Avoid deleting anythingoutside tmp_path, fixture writing permitted normaltest implementation. Return only python no fake execution results.
Actual runtime:
# e31_submission_runtime.py — notebook cell fragment (not importable module)
import csv
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

from biohub.association_instrumentation import instrument_source
from biohub.primary_consensus_observer import PrimaryConsensusObserver

stems = sorted(p.stem for p in TEST_DIR.glob("*.zarr"))
assert stems, "no test zarr stems"
assert len(stems) == len(set(stems))
assert not list(TEST_DIR.glob("*.geff"))

assert float(os.environ["BIOHUB_BIDIRECTIONAL_EDGE_WEIGHT"]) == 0.30
assert Path(os.environ["BIOHUB_SECONDARY_WEIGHTS"]) == SECONDARY_WEIGHTS_PATH
assert SECONDARY_WEIGHTS_PATH.is_file()
secondary_edge_weight = float(os.environ["BIOHUB_SECONDARY_EDGE_WEIGHT"])
assert secondary_edge_weight == 0.15
fusion_mode = os.environ["BIOHUB_BIDIRECTIONAL_FUSION_MODE"]
assert fusion_mode == "harmonic_probability"

patched, insertion_receipt = instrument_source(_ps.read_text())
predict_path = REPO_DIR / "scripts" / "e31_predict.py"
with open(predict_path, "x", encoding="utf-8") as f:
    f.write(patched)

import dataspec

dataspec.PREDICTIONS_PATH = WORKING_DIR / "e31_predictions"
assert not dataspec.PREDICTIONS_PATH.exists()

spec = importlib.util.spec_from_file_location("e31_predict", predict_path)
module = importlib.util.module_from_spec(spec)
sys.modules["e31_predict"] = module
spec.loader.exec_module(module)

observer = PrimaryConsensusObserver()

splits_path = WORKING_DIR / "e31_splits.json"
with open(splits_path, "x", encoding="utf-8") as f:
    json.dump([{"split": 0, "train": [], "test": stems}], f)

from biohub.output_bounds import read_output_shape

shapes = {ds: read_output_shape(TEST_DIR, ds) for ds in stems}

t0 = time.monotonic()
module.predict(
    data_dir=TEST_DIR,
    fold=0,
    splits_file=splits_path,
    weights_path=_primary_materialized_path,
    cfg=module.PredictConfig(
        det_threshold=0.96875,
        use_ilp=True,
        ilp_edge_weight=-1.0,
        ilp_appearance_weight=0.0,
        ilp_disappearance_weight=1.5,
        ilp_division_weight=1.0,
    ),
    method="unet_transformer",
    unet_batch_size=4,
    evaluate=False,
    association_observer=observer,
)
elapsed = time.monotonic() - t0

geffs = sorted(dataspec.PREDICTIONS_PATH.rglob("*.geff"))
assert len(geffs) == len(stems)
assert {g.stem for g in geffs} == set(stems)

from biohub.public_postproc.config import build_config
from biohub.public_postproc.deepcenter import load_deepcenter_veto_detector_strict
from biohub.public_postproc.pipeline import run_postproc_core
from biohub.screen_output_bounds import ScreenNodeSerializer, verify_screen_output_bounds

manifest = _deepcenter_materialized_path.parents[2] / "ARTIFACT_MANIFEST.json"
assert manifest.is_file()
cfg = build_config(
    overrides={
        "BIOHUB_DEEPCENTER_CHECKPOINT": str(_deepcenter_materialized_path),
        "BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT": str(_deepcenter_materialized_path),
        "BIOHUB_DEEPCENTER_MANIFEST": str(manifest),
        "BIOHUB_DEEPCENTER_MANIFEST_DEFAULT": str(manifest),
    },
    test_dir=TEST_DIR,
    profile="e23",
)
assert cfg.OUTPUT_MOTION_RELINK and cfg.USE_DEEPCENTER_VETO and cfg.REQUIRE_DEEPCENTER_VETO
bundle, deepcenter_receipt = load_deepcenter_veto_detector_strict(cfg, _deepcenter_materialized_path, manifest)

serializer = ScreenNodeSerializer(shapes)
csv_path = WORKING_DIR / "submission.csv"
run_stats_path = WORKING_DIR / "run_stats.csv"
run_postproc_core(
    geffs,
    csv_path,
    cfg,
    run_stats_path=run_stats_path,
    predict_seconds=elapsed,
    node_serializer=serializer,
    consensus_loader=observer.frames_for,
    exclusive_output=True,
    deepcenter_loader=lambda config: bundle,
)

bounds = serializer.snapshot()
verify_screen_output_bounds(bounds, csv_path, shapes=shapes)
bounds_path = WORKING_DIR / "e31_output_bounds.json"
with open(bounds_path, "x", encoding="utf-8") as f:
    json.dump(bounds, f)

EXPECTED_COLS = ["id", "dataset", "row_type", "node_id", "t", "z", "y", "x", "source_id", "target_id"]
node_times = {}
row_counter = 0
with open(csv_path, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    assert reader.fieldnames == EXPECTED_COLS
    for row in reader:
        assert int(row["id"]) == row_counter
        row_counter += 1
        ds = row["dataset"]
        rt = row["row_type"]
        assert ds in shapes, f"unknown dataset {ds}"
        if rt == "node":
            nid = int(row["node_id"])
            assert nid >= 0
            assert nid not in node_times.get(ds, {})
            assert int(row["source_id"]) == -1
            assert int(row["target_id"]) == -1
            ti = int(row["t"])
            zi = int(row["z"])
            yi = int(row["y"])
            xi = int(row["x"])
            sh = shapes[ds]
            assert 0 <= ti < sh[0] and 0 <= zi < sh[1] and 0 <= yi < sh[2] and 0 <= xi < sh[3]
            node_times.setdefault(ds, {})[nid] = ti
        elif rt == "edge":
            assert int(row["node_id"]) == -1 and int(row["t"]) == -1
            assert int(row["z"]) == -1 and int(row["y"]) == -1 and int(row["x"]) == -1
        else:
            raise ValueError(f"unknown row_type {rt}")

edges_seen = set()
in_deg = {}
out_deg = {}
with open(csv_path, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row["row_type"] != "edge":
            continue
        ds = row["dataset"]
        src = int(row["source_id"])
        tgt = int(row["target_id"])
        assert src >= 0 and tgt >= 0
        nt = node_times.get(ds, {})
        assert src in nt and tgt in nt
        assert nt[tgt] == nt[src] + 1
        key = (ds, src, tgt)
        assert key not in edges_seen
        edges_seen.add(key)
        out_deg[(ds, src)] = out_deg.get((ds, src), 0) + 1
        in_deg[(ds, tgt)] = in_deg.get((ds, tgt), 0) + 1
        assert out_deg[(ds, src)] <= 2 and in_deg[(ds, tgt)] <= 1

for ds in stems:
    assert ds in node_times and node_times[ds]

assert csv_path.stat().st_size > 0
csv_sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
receipt = {
    "csv_sha256": csv_sha,
    "stems": stems,
    "shapes": shapes,
    "insertion_receipt": insertion_receipt,
    "deepcenter_receipt": deepcenter_receipt,
    "E31_HASHES": E31_HASHES,
    "elapsed": elapsed,
    "hypothesis": "primary-only reciprocal consensus",
}
with open(WORKING_DIR / "e31_submission_receipt.json", "x", encoding="utf-8") as f:
    json.dump(receipt, f)
print("VALIDATED_E31_SUBMISSION")

