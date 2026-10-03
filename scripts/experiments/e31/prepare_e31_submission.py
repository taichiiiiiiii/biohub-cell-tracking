import ast
import hashlib
import json
from pathlib import Path


def _code_cell(source: str) -> dict:
    ast.parse(source)
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def build(repo: Path) -> dict:
    baseline = repo / "notebooks/pub923_repro/pub923_repro.ipynb"
    raw = baseline.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ("08507f9123d9f40e185d0db8eda3dd21cb405e50febb720827c2e655f68d5ec1")
    nb = json.loads(raw)
    cells = nb["cells"]

    src_cells = [_code_cell("".join(cells[i]["source"])) for i in (3, 5, 7, 9)]

    cell11_src = "".join(cells[11]["source"])
    marker = "def list_test_stems() -> list[str]:"
    assert cell11_src.count(marker) == 1
    prefix = cell11_src[: cell11_src.index(marker)]
    src_cells.append(_code_cell(prefix))

    payload_paths = [
        "src/biohub/__init__.py",
        "src/biohub/io.py",
        "src/biohub/appearance_cost.py",
        "src/biohub/consensus_edges.py",
        "src/biohub/primary_consensus_observer.py",
        "src/biohub/association_instrumentation.py",
        "src/biohub/output_bounds.py",
        "src/biohub/screen_output_bounds.py",
        "src/biohub/e31_shards.py",
        "scripts/experiments/e31/e31_submission_runtime.py",
    ] + [
        f"src/biohub/public_postproc/{n}.py"
        for n in [
            "__init__",
            "config",
            "csv_out",
            "deepcenter",
            "divisions",
            "frames",
            "geometry",
            "graph_ops",
            "pipeline",
        ]
    ]
    payload, hashes = {}, {}
    for p in payload_paths:
        text = (repo / p).read_text()
        ast.parse(text)
        payload[p] = text
        hashes[p] = hashlib.sha256(text.encode()).hexdigest()

    setup_src = (
        "E31_FILES = " + repr(payload) + "\n"
        "E31_HASHES = " + repr(hashes) + "\n"
        "import sys, hashlib, os\n"
        "payloadroot = WORKING_DIR / 'e31_payload'\n"
        "payloadroot.mkdir(exist_ok=False)\n"
        "for path, content in E31_FILES.items():\n"
        "    dest = payloadroot / path\n"
        "    dest.parent.mkdir(parents=True, exist_ok=True)\n"
        "    with open(dest, 'x') as fh:\n"
        "        fh.write(content)\n"
        "os.chdir(REPO_DIR)\n"
        "sys.path.insert(0, str(REPO_DIR))\n"
        "sys.path.insert(0, str(REPO_DIR / 'src'))\n"
        "sys.path.insert(0, str(REPO_DIR / 'scripts'))\n"
        "if any(name == 'biohub' or name.startswith('biohub.') for name in sys.modules):\n"
        "    raise RuntimeError('biohub imported before hashed payload setup')\n"
        "sys.path.insert(0, str(payloadroot / 'src'))\n"
    )
    src_cells.append(_code_cell(setup_src))

    runtime_src = (repo / "scripts/experiments/e31/e31_dual_gpu_runtime.py").read_text()
    src_cells.append(_code_cell(runtime_src))
    runtime_hash = hashlib.sha256(runtime_src.encode()).hexdigest()

    md_first = (
        "# Biohub E31 Primary Consensus Exploratory\n\n"
        "Acknowledges pilkwang CC0 model/support packs. "
        "E31 primary-only consensus exploratory; not Private Score improvement proof.\n"
    )
    final_cells = [{"cell_type": "markdown", "metadata": {}, "source": md_first.splitlines(keepends=True)}]
    final_cells.extend(src_cells)
    out_nb = {**nb, "cells": final_cells}

    meta_path = repo / "notebooks/pub923_repro/kernel-metadata.json"
    meta = json.loads(meta_path.read_text())
    meta.update(
        {
            "id": "taichiiiii/biohub-e31-primary-consensus-exploratory",
            "title": "Biohub E31 Primary Consensus Exploratory",
            "code_file": "e31_submission.ipynb",
            "is_private": "true",
            "enable_gpu": "true",
            "enable_internet": "false",
        }
    )

    receipt = {
        "status": "PREPARED_NOT_EXECUTED",
        "baselinehash": hashlib.sha256(raw).hexdigest(),
        "payloadhashes": hashes,
        "runtimehash": runtime_hash,
    }
    return {"notebook": out_nb, "metadata": meta, "receipt": receipt}


if __name__ == "__main__":
    print(json.dumps(build(Path(__file__).resolve().parents[3])))
