"""Build (but do not execute/push) a private, GT-free public-four parity notebook."""

import ast
import json
from pathlib import Path

import numpy as np
import zarr

from biohub.association_capture import _require, _sha
from biohub.association_instrumentation import instrument_source
from biohub.association_parity import semantic_graph_signature

NOTEBOOK_SHA = "08507f9123d9f40e185d0db8eda3dd21cb405e50febb720827c2e655f68d5ec1"
CONFIG_SHA = "e9b4e396c58081bca08adf8275bd0bd1c2d3fd6eb091a1912a5116cb6de7b50a"
PAYLOAD_FILES = ["src/biohub/association_capture.py", "src/biohub/association_observer.py",
                 "src/biohub/association_instrumentation.py", "src/biohub/association_parity.py",
                 "src/biohub/association_supervise.py", "scripts/e23_association_bridge.py"]


def raw_signature(path):
    group = zarr.open_group(path, mode="r")
    node_ids = group["nodes/ids"][:]
    order = np.argsort(node_ids)
    edges = group["edges/ids"][:]
    edge_order = np.lexsort((edges[:, 1], edges[:, 0]))
    arrays = {"node_node_id": node_ids[order], "edge_source_id": edges[edge_order, 0],
              "edge_target_id": edges[edge_order, 1]}
    for key in ("t", "z", "y", "x"):
        arrays[f"node_{key}"] = group[f"nodes/props/{key}/values"][:][order]
    for key in ("edge_prob", "edge_dist"):
        arrays[f"edge_{key}"] = group[f"edges/props/{key}/values"][:][edge_order]
    for kind in ("nodes", "edges"):
        _require(np.all(group[f"{kind}/props/solution/values"][:]), "reference raw is not selected-only")
    return semantic_graph_signature(arrays)


def code_cell(source):
    ast.parse(source)
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
            "source": source.splitlines(keepends=True)}


def build(repo):
    base = repo / "notebooks/pub923_repro/pub923_repro.ipynb"
    _require(_sha(base) == NOTEBOOK_SHA, "baseline notebook SHA mismatch")
    notebook = json.loads(base.read_text())
    reconstruction = repo / "outputs/local/e23_association_capture_d3_20260908/prospective_e23_predict.py.txt"
    _, insertion = instrument_source(reconstruction.read_text())
    inputs = [base, reconstruction]
    datasets = {}
    raw_root = repo / ("outputs/kaggle/e22_bidir030_public4_raw/tracking_repo/"
                       "predictions/unknown/unet_transformer/split_0")
    for suffix in ("0_2", "1_2"):
        manifest = (repo / "outputs/kaggle/e23_reference" /
                    f"detector_coordinates_harmonic_association_production_{suffix}.jsonl")
        inputs.append(manifest)
        for line in manifest.read_text().splitlines():
            row = json.loads(line)
            name = row["dataset"]
            _require(name not in datasets, "duplicate reference video")
            counts = dict(row["frame_counts"])
            datasets[name] = {"coordinate_sha256": row["coordinate_sha256"],
                              "frame_counts": [counts.get(t, 0) for t in range(100)],
                              "raw_graph_signature": raw_signature(raw_root / f"{name}.geff")}
            inputs.extend(p for p in sorted((raw_root / f"{name}.geff").rglob("*")) if p.is_file())
    _require(len(datasets) == 4, "public-four reference incomplete")
    for side in ("primary", "secondary"):
        p = repo / f"outputs/kaggle/st_r3_checkpoint_recovery/{side}/config.json"
        _require(_sha(p) == CONFIG_SHA, "recovered model config changed")
        inputs.append(p)
    files = {path: (repo / path).read_text() for path in PAYLOAD_FILES}
    files["src/biohub/__init__.py"] = "# Diagnostic-only payload namespace.\n"
    cells = [{"cell_type": "markdown", "metadata": {}, "source": [
        "# E23 association observer: public-four OFF → ON parity\n",
        "Private diagnostic only. No training, GT scoring, submission.csv, or competition submission.\n",
        "Same E23 model/source/settings. Public dummy videos are not a holdout.\n",
        "Reuses the user's E23 notebook and pilkwang's CC0 support/model packs.\n"]}]
    cells.append(code_cell("import time\nD3_STARTED = time.monotonic()\n"))
    for index in (3, 5, 7):
        cells.append(code_cell("".join(notebook["cells"][index]["source"])))
    guard = (f"D3_EXPECTED_DATASETS = {sorted(datasets)!r}\n"
             "assert sorted(p.stem for p in TEST_DIR.glob('*.zarr')) == D3_EXPECTED_DATASETS\n"
             "assert not list(TEST_DIR.glob('*.geff')), 'GT must not be in prediction input'\n")
    cells.append(code_cell(guard))
    cells.append(code_cell("".join(notebook["cells"][9]["source"])))
    source_patch = "".join(notebook["cells"][11]["source"])
    delimiter = "def list_test_stems() -> list[str]:"
    _require(source_patch.count(delimiter) == 1, "baseline inference split anchor changed")
    cells.append(code_cell(source_patch.split(delimiter)[0]))
    setup = f'''import hashlib
D3_PAYLOAD = WORKING_DIR / "association_payload"
assert not D3_PAYLOAD.exists(), "fresh payload required"
D3_FILES = {files!r}
for relative, text in D3_FILES.items():
    target = D3_PAYLOAD / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x") as stream:
        stream.write(text)
sys.path.insert(0, str(D3_PAYLOAD / "src"))
from biohub.association_instrumentation import instrument_source
from biohub.association_capture import _sha
patched, receipt = instrument_source(_ps.read_text())
assert receipt["instrumented_sha256"] == {insertion['instrumented_sha256']!r}
D3_SOURCES = {{arm: REPO_DIR / "scripts" / f"e23_observer_{{arm}}.py" for arm in ("off", "on")}}
for arm, text in (("off", _ps.read_text()), ("on", patched)):
    with D3_SOURCES[arm].open("x") as stream:
        stream.write(text)
D3_SPLITS = WORKING_DIR / "association_public4_splits.json"
with D3_SPLITS.open("x") as stream:
    json.dump([{{"split": 0, "train": [], "test": D3_EXPECTED_DATASETS}}], stream)
runtime_files = {{str(_primary_materialized_path): _primary_expected_sha256,
                 str(SECONDARY_WEIGHTS_PATH): _secondary_expected_sha256,
                 str(_deepcenter_materialized_path): _deepcenter_expected_sha256,
                 str(_primary_materialized_path.parent / "config.json"): {CONFIG_SHA!r},
                 str(SECONDARY_CONFIG_PATH): {CONFIG_SHA!r},
                 str(D3_SPLITS): _sha(D3_SPLITS)}}
for path, expected in runtime_files.items():
    assert _sha(Path(path)) == expected, path
D3_PLAN = {{"schema_version": "biohub.association.public4.v1", "datasets": {datasets!r},
           "data_dir": str(TEST_DIR), "splits_file": str(D3_SPLITS), "repo_dir": str(REPO_DIR),
           "primary_weights": str(_primary_materialized_path),
           "runtime_file_sha256": runtime_files,
           "source_paths": {{arm: str(path) for arm, path in D3_SOURCES.items()}},
           "source_sha256": {{"off": receipt["original_sha256"], "on": receipt["instrumented_sha256"]}},
           "source_inventory": [{{"path": str(p), "sha256": _sha(p)}}
                                for p in sorted([*REPO_DIR.rglob("*.py"), *D3_PAYLOAD.rglob("*.py")])],
           "submission_authorized": False}}
D3_PLAN_PATH = WORKING_DIR / "association_public4_plan.json"
with D3_PLAN_PATH.open("x") as stream:
    json.dump(D3_PLAN, stream, sort_keys=True, indent=2)
print("D3 PLAN SEALED", _sha(D3_PLAN_PATH), flush=True)
'''
    cells.append(code_cell(setup))
    cells.append(code_cell('''from biohub.association_supervise import supervise
D3_RESULT = supervise(D3_PLAN_PATH, WORKING_DIR / "association_parity_run", D3_PAYLOAD, D3_STARTED + 8400)
assert D3_RESULT["status"] == "PUBLIC4_ASSOCIATION_OBSERVER_PARITY_PASS"
assert not (WORKING_DIR / "submission.csv").exists()
'''))
    metadata = json.loads((repo / "notebooks/pub923_repro/kernel-metadata.json").read_text())
    metadata.update(id="taichiiiii/biohub-e23-association-observer-parity",
                    title="Biohub E23 Association Observer Parity",
                    code_file="association_parity.ipynb")
    bindings = [{"path": str(p.relative_to(repo)), "bytes": p.stat().st_size, "sha256": _sha(p)}
                for p in inputs + [repo / f for f in PAYLOAD_FILES]]
    built = {"cells": cells, "metadata": notebook["metadata"], "nbformat": 4, "nbformat_minor": 5}
    return {"notebook": built, "metadata": metadata, "receipt": {
        "status": "PREPARED_NOT_EXECUTED", "source_executed_locally": False,
        "reference_count": len(datasets), "bindings": bindings,
        "source_insertion": insertion, "submission_authorized": False}}


if __name__ == "__main__":
    print(json.dumps(build(Path(__file__).resolve().parents[1]), ensure_ascii=False))
