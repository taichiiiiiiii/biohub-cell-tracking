from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "src", ROOT / "official" / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


# --- Frozen-baseline guards -------------------------------------------------
# Some experiment tools verify their inputs against hashes recorded when the experiment
# ran. Those guards are correct and must keep refusing a drifted tree; the tests that
# replay them against local frozen artifacts can only pass while the recorded baseline
# still exists. When it has been superseded, these helpers skip with the reason instead
# of reporting a failure.

# pub923_repro.ipynb as it stood for E23/E31 (pinned in prepare_e23_association_parity.py
# and prepare_e31_submission.py). The notebook was edited afterwards for E56-E71.
PUB923_FROZEN_SHA256 = "08507f9123d9f40e185d0db8eda3dd21cb405e50febb720827c2e655f68d5ec1"


def skip_if_pub923_superseded() -> None:
    import hashlib

    import pytest

    live = hashlib.sha256((ROOT / "notebooks/pub923_repro/pub923_repro.ipynb").read_bytes()).hexdigest()
    if live != PUB923_FROZEN_SHA256:
        pytest.skip("pub923_repro.ipynb superseded after E23/E31 (frozen baseline no longer in the tree)")


def skip_if_source_closure_superseded(recorded: dict) -> None:
    import pytest

    from scripts.experiments.e27 import e27_association_prior_screen as g

    def keyed(binding: dict) -> dict:
        return {g._pre_reorg_alias(rel): meta for rel, meta in binding["files"].items()}

    if keyed(g._snapshot_source_closure()) != keyed(recorded):
        pytest.skip("src/biohub source closure changed after the frozen E27 run (baseline superseded)")


# --- torch-dependent modules ------------------------------------------------
# CI installs the torch-free extra only (see .github/workflows/ci.yml). These modules import
# torch directly or through src/biohub at import time, or launch children that require it at
# run time, so they are not collected there.
try:
    import torch  # noqa: F401
except ImportError:
    collect_ignore = [
        "test_association_acceptance.py",
        "test_association_artifacts.py",
        "test_association_collection.py",
        "test_association_augmentation.py",
        "test_association_data.py",
        "test_association_manifest.py",
        "test_association_observer.py",
        "test_association_parity.py",
        "test_association_probe.py",
        "test_association_resume.py",
        "test_association_step_sampler.py",
        "test_association_training.py",
        "test_e26_screen.py",
        "test_e31_notebook.py",
        "test_export_association_candidate.py",
        "test_kaggle_screen.py",
        "test_local_train_device.py",
        "test_local_training.py",
        "test_prepare_eval36_bundle_kernel.py",
        "test_st_r3_prerequisites.py",
        "test_train_frozen_association.py",
    ]
