Issue17 Max authoring only. Return minimal unified diff for scripts/e31_submission_runtime.py and scripts/prepare_e31_submission.py. Current runtime below. Fix all concrete defects, don't change other semantics:
1 import actual PrimaryConsensusObserver from biohub.primary_consensus_observer and instrument_source from biohub.association_instrumentation.
2 stems=sorted(p.stem for p in TEST_DIR.glob("*.zarr")), assert no list(TEST_DIR.glob("*.geff")); remove misleading suffixcheck and setcomp/is_dir filters.
3 env secondaryedge key strict [] not .get fallback. fusion env key BIOHUB_BIDIRECTIONAL_FUSION_MODE strict[].
4 all output writes mode x not w (predict_path,splits_path,bounds_path,receipt).
5 config keys CHECKPOINT_DEFAULT -> BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT; MANIFEST_DEFAULT -> BIOHUB_DEEPCENTER_MANIFEST_DEFAULT.
6 Parent brief had wrong strict API. Actual load_deepcenter_veto_detector_strict(cfg,checkpoint_path:Path,manifest_path:Path) -> tuple[dict bundle,dict receipt]. Immediately before serializer instantiate bundle,deepcenter_receipt by calling actualfunc(cfg,_deepcenter_materialized_path,manifest). run_postproc_core deepcenter_loader use lambda config: bundle (returns BUNDLE ONLY). Include deepcenter_receipt in finalreceipt. No repeatload/fallback.
7 node firstpass before assignment assert nid not in node_times.get(ds,{}), assert source_id and target_id both -1. Preserve edge negative sentinels.
8 builder setup string adds sys.path.insert(0,str(REPO_DIR / 'src')) immediately after sys.path.insert(0,str(REPO_DIR)). Current exact builder text:
        "sys.path.insert(0, str(REPO_DIR))\n"
        "sys.path.insert(0, str(REPO_DIR / 'scripts'))\n"
This is critical biohub_tracking package import.
CURRENT RUNTIME:
# e31_submission_runtime.py — notebook cell fragment (not importable module)
import json, os, sys, time, hashlib, importlib.util, csv
from pathlib import Path

stems = sorted({p.stem for p in TEST_DIR.glob("*.zarr") if p.is_dir()})
assert stems, "no test zarr stems"
assert len(stems) == len(set(stems))
assert not any(s.endswith(".geff") for s in stems)

assert float(os.environ["BIOHUB_BIDIRECTIONAL_EDGE_WEIGHT"]) == 0.30
assert Path(os.environ["BIOHUB_SECONDARY_WEIGHTS"]) == SECONDARY_WEIGHTS_PATH
assert SECONDARY_WEIGHTS_PATH.is_file()
secondary_edge_weight = float(os.environ.get("BIOHUB_SECONDARY_EDGE_WEIGHT", "0.15"))
assert secondary_edge_weight == 0.15
fusion_mode = os.environ.get("BIOHUB_FUSION_MODE", "harmonic_probability")
assert fusion_mode == "harmonic_probability"

patched, insertion_receipt = instrument_source(_ps.read_text())
predict_path = REPO_DIR / "scripts" / "e31_predict.py"
with open(predict_path, "w", encoding="utf-8") as f:
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
with open(splits_path, "w", encoding="utf-8") as f:
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
from biohub.public_postproc.pipeline import run_postproc_core
from biohub.screen_output_bounds import ScreenNodeSerializer, verify_screen_output_bounds
from biohub.public_postproc.deepcenter import load_deepcenter_veto_detector_strict

manifest = _deepcenter_materialized_path.parents[2] / "ARTIFACT_MANIFEST.json"
assert manifest.is_file()
cfg = build_config(
    overrides={
        "BIOHUB_DEEPCENTER_CHECKPOINT": str(_deepcenter_materialized_path),
        "CHECKPOINT_DEFAULT": str(_deepcenter_materialized_path),
        "BIOHUB_DEEPCENTER_MANIFEST": str(manifest),
        "MANIFEST_DEFAULT": str(manifest),
    },
    test_dir=TEST_DIR,
    profile="e23",
)
assert cfg.OUTPUT_MOTION_RELINK and cfg.USE_DEEPCENTER_VETO and cfg.REQUIRE_DEEPCENTER_VETO

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
    deepcenter_loader=load_deepcenter_veto_detector_strict,
)

bounds = serializer.snapshot()
verify_screen_output_bounds(bounds, csv_path, shapes=shapes)
bounds_path = WORKING_DIR / "e31_output_bounds.json"
with open(bounds_path, "w", encoding="utf-8") as f:
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
            nid = int(row["node_id"]); assert nid >= 0
            ti = int(row["t"]); zi = int(row["z"]); yi = int(row["y"]); xi = int(row["x"])
            sh = shapes[ds]
            assert 0 <= ti < sh[0] and 0 <= zi < sh[1] and 0 <= yi < sh[2] and 0 <= xi < sh[3]
            node_times.setdefault(ds, {})[nid] = ti
        elif rt == "edge":
            assert int(row["node_id"]) == -1 and int(row["t"]) == -1
            assert int(row["z"]) == -1 and int(row["y"]) == -1 and int(row["x"]) == -1
        else:
            raise ValueError(f"unknown row_type {rt}")

edges_seen = set()
in_deg = {}; out_deg = {}
with open(csv_path, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row["row_type"] != "edge":
            continue
        ds = row["dataset"]; src = int(row["source_id"]); tgt = int(row["target_id"])
        assert src >= 0 and tgt >= 0
        nt = node_times.get(ds, {})
        assert src in nt and tgt in nt
        assert nt[tgt] == nt[src] + 1
        key = (ds, src, tgt)
        assert key not in edges_seen; edges_seen.add(key)
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
    "E31_HASHES": E31_HASHES,
    "elapsed": elapsed,
    "hypothesis": "primary-only reciprocal consensus",
}
with open(WORKING_DIR / "e31_submission_receipt.json", "w", encoding="utf-8") as f:
    json.dump(receipt, f)
print("VALIDATED_E31_SUBMISSION")

