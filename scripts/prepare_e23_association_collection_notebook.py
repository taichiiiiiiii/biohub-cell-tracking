"""Build a private collection36 notebook; never import/run its model source locally."""

import json
from pathlib import Path

from biohub.association_capture import _require, _sha
from biohub.association_collection import REFERENCE_SHA
from scripts.prepare_e23_association_collection import build as build_references
from scripts.prepare_e23_association_parity import CONFIG_SHA, PAYLOAD_FILES, code_cell
from scripts.prepare_e23_association_parity import build as build_parity

EXTRA_FILES = ["src/biohub/association_collection.py", "src/biohub/association_collection_supervise.py",
               "scripts/e23_association_collect.py"]


def build(repo):
    reference_path = repo / "outputs/local/e23_association_collection_20260908/REFERENCE_PLAN.json"
    _require(_sha(reference_path) == REFERENCE_SHA, "fixed collection reference changed")
    references = json.loads(reference_path.read_text())
    _require(references == build_references(repo), "collection references no longer reproduce")
    prepared = build_parity(repo)
    cells = prepared["notebook"]["cells"][:8]
    cells[0] = {"cell_type": "markdown", "metadata": {}, "source": [
        "# E23 association collection: 36 previously exposed train videos\n",
        "Private diagnostic, fixed E23, nine serial groups, no GT reads/training/submission.csv.\n",
        "Source/model packs by pilkwang (CC0 as recorded in project evidence).\n",
        "Public-four OFF/ON parity passed; this run is ON-only with per-video frozen reference checks.\n",
        "Train GT remains on the competition mount: image-only views are not OS isolation.\n"]}
    cells[1] = code_cell("import time\nD3_STARTED = time.monotonic()\n")
    cells[5] = code_cell(f'''D3_EXPECTED_DATASETS = {sorted(references['datasets'])!r}
D3_TRAIN_IMAGES = COMP_DIR / "train"
assert D3_TRAIN_IMAGES.is_dir()
assert all((D3_TRAIN_IMAGES / (name + ".zarr")).is_dir() for name in D3_EXPECTED_DATASETS)
print("D3 COLLECTION image paths present", len(D3_EXPECTED_DATASETS), flush=True)
''')
    files = {p: (repo / p).read_text() for p in PAYLOAD_FILES + EXTRA_FILES}
    files["src/biohub/__init__.py"] = "# Diagnostic-only payload namespace.\n"
    old_plan = json.loads((repo / "outputs/local/e23_association_target_20260908/terminal/"
                          "association_public4_plan.json").read_text())
    pins = {r["path"].replace("/association_payload/", "/collection_payload/"): r["sha256"]
            for r in old_plan["source_inventory"]}
    pins.update({"/kaggle/working/collection_payload/" + p: _sha(repo / p) for p in EXTRA_FILES})
    old_result = json.loads((repo / "outputs/local/e23_association_target_20260908/terminal/"
                            "association_parity_run/on/RESULT.json").read_text())
    setup = f'''D3_PAYLOAD = WORKING_DIR / "collection_payload"
assert not D3_PAYLOAD.exists(), "fresh payload required"
D3_FILES = {files!r}
for relative, text in D3_FILES.items():
    target = D3_PAYLOAD / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x") as stream:
        stream.write(text)
sys.path.insert(0, str(D3_PAYLOAD / "src"))
from biohub.association_capture import _sha
from biohub.association_instrumentation import instrument_source
from biohub.association_collection import load_reference
patched, receipt = instrument_source(_ps.read_text())
assert receipt["original_sha256"] == {references['source_sha256']['off']!r}
assert receipt["instrumented_sha256"] == {references['source_sha256']['on']!r}
D3_SOURCES = {{arm: REPO_DIR / "scripts" / f"e23_observer_{{arm}}.py" for arm in ("off", "on")}}
for arm, text in (("off", _ps.read_text()), ("on", patched)):
    with D3_SOURCES[arm].open("x") as stream:
        stream.write(text)
D3_REFERENCE_PATH = WORKING_DIR / "association_collection_reference.json"
with D3_REFERENCE_PATH.open("xb") as stream:
    stream.write({reference_path.read_bytes()!r})
D3_REFERENCE = load_reference(D3_REFERENCE_PATH)
D3_EXPECTED_SOURCE = {pins!r}
D3_INVENTORY = {{str(p): _sha(p) for p in sorted([*REPO_DIR.rglob("*.py"), *D3_PAYLOAD.rglob("*.py")])}}
assert D3_INVENTORY == D3_EXPECTED_SOURCE, "collection source differs from verified runtime"
D3_SHARED_RUNTIME = {{str(_primary_materialized_path): _primary_expected_sha256,
                     str(SECONDARY_WEIGHTS_PATH): _secondary_expected_sha256,
                     str(_deepcenter_materialized_path): _deepcenter_expected_sha256,
                     str(_primary_materialized_path.parent / "config.json"): {CONFIG_SHA!r},
                     str(SECONDARY_CONFIG_PATH): {CONFIG_SHA!r},
                     str(D3_REFERENCE_PATH): _sha(D3_REFERENCE_PATH)}}
for path, digest in D3_SHARED_RUNTIME.items():
    assert _sha(Path(path)) == digest, path
D3_PLANS = WORKING_DIR / "association_collection_plans"
D3_VIEWS = WORKING_DIR / "association_collection_images"
D3_PLANS.mkdir(exist_ok=False)
D3_VIEWS.mkdir(exist_ok=False)
D3_GROUP_PLANS = []
for group in D3_REFERENCE["groups"]:
    gid, names = group["group_id"], group["datasets"]
    image_view = D3_VIEWS / gid
    image_view.mkdir(exist_ok=False)
    for name in names:
        (image_view / (name + ".zarr")).symlink_to(D3_TRAIN_IMAGES / (name + ".zarr"), target_is_directory=True)
    assert set(p.name for p in image_view.iterdir()) == {{n + ".zarr" for n in names}}
    split_path = D3_PLANS / (gid + "_splits.json")
    with split_path.open("x") as stream:
        json.dump([{{"split": 0, "train": [], "test": names}}], stream)
    plan = {{"schema_version": "biohub.association.collection36.group.v1", "group_id": gid,
            "reference_path": str(D3_REFERENCE_PATH), "data_dir": str(image_view),
            "datasets": {{n: D3_REFERENCE["datasets"][n] for n in names}},
            "splits_file": str(split_path), "primary_weights": str(_primary_materialized_path),
            "source_path": str(D3_SOURCES["on"]), "source_sha256": receipt["instrumented_sha256"],
            "source_inventory": [{{"path": p, "sha256": digest}} for p, digest in D3_INVENTORY.items()],
            "runtime_file_sha256": {{**D3_SHARED_RUNTIME, str(split_path): _sha(split_path)}},
            "submission_authorized": False}}
    plan_path = D3_PLANS / (gid + ".json")
    with plan_path.open("x") as stream:
        json.dump(plan, stream, sort_keys=True, indent=2)
    D3_GROUP_PLANS.append({{"group_id": gid, "path": str(plan_path), "sha256": _sha(plan_path)}})
D3_MASTER = {{"schema_version": "biohub.association.collection36.master.v1",
             "reference_path": str(D3_REFERENCE_PATH), "repo_dir": str(REPO_DIR),
             "expected_dependencies": {old_result['dependencies']!r},
             "group_plans": D3_GROUP_PLANS, "submission_authorized": False}}
D3_MASTER_PATH = WORKING_DIR / "association_collection_master.json"
with D3_MASTER_PATH.open("x") as stream:
    json.dump(D3_MASTER, stream, sort_keys=True, indent=2)
print("D3 COLLECTION MASTER SEALED", _sha(D3_MASTER_PATH), flush=True)
'''
    cells.append(code_cell(setup))
    cells.append(code_cell('''from biohub.association_collection_supervise import supervise_collection
D3_COLLECTION = supervise_collection(D3_MASTER_PATH, WORKING_DIR / "association_collection_run", D3_PAYLOAD, D3_STARTED)
assert D3_COLLECTION["status"] == "COLLECTION36_COMPLETE_REFERENCE_MATCHED"
assert not (WORKING_DIR / "submission.csv").exists()
'''))
    metadata = prepared["metadata"]
    metadata.update(id="taichiiiii/biohub-e23-association-collection36",
                    title="Biohub E23 Association Collection36", code_file="association_collection.ipynb")
    return {"notebook": {**prepared["notebook"], "cells": cells}, "metadata": metadata,
            "receipt": {"status": "COLLECTION_NOTEBOOK_PREPARED_NOT_DISPATCHED", "reference_sha256": REFERENCE_SHA,
                        "source_files": [{"path": p, "sha256": _sha(repo / p)} for p in PAYLOAD_FILES + EXTRA_FILES],
                        "runtime_source_pins": pins, "source_executed_locally": False,
                        "submission_authorized": False, "parent_only": True}}


if __name__ == "__main__":
    print(json.dumps(build(Path(__file__).resolve().parents[1]), separators=(",", ":")))
