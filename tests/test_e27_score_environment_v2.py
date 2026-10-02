"""Tests for scripts.experiments.e27.e27_score_environment_v2.verify_import_environment.

Includes a required fresh-subprocess regression against the canonical macOS
Python 3.12 venv interpreter. No Kaggle, no ground truth, no scoring, no plan
imports, no Torch, no blanket environment dumps.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from biohub import e26_screen as e
from scripts.experiments.e27.e27_score_environment_v2 import verify_import_environment

ROOT = Path(__file__).resolve().parents[1]

LIBTCC = str(ROOT / ".venv/lib/python3.12/site-packages/blosc2/lib/libtcc.dylib")

ADDITIONS = {
    "KMP_DUPLICATE_LIB_OK": "True",
    "_RJEM_MALLOC_CONF": "dirty_decay_ms:500,muzzy_decay_ms:1000",
    "ME_DSL_JIT_LIBTCC_PATH": LIBTCC,
}

LAUNCH = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/home/user",
    "VIRTUAL_ENV": ".venv",
    "CUDA_VISIBLE_DEVICES": "",
}


def _observed(**extra: str) -> dict[str, str]:
    merged = {**LAUNCH, **ADDITIONS, **extra}
    return merged


# --- success / purity -------------------------------------------------------


def test_success_returns_additions_only():
    result = verify_import_environment(LAUNCH, _observed(), LIBTCC)
    assert result == ADDITIONS


def test_inputs_not_mutated_and_return_independent():
    launch = dict(LAUNCH)
    observed = _observed()
    launch_copy = dict(launch)
    observed_copy = dict(observed)

    result = verify_import_environment(launch, observed, LIBTCC)

    assert launch == launch_copy
    assert observed == observed_copy
    assert result is not observed
    assert result is not launch
    result["KMP_DUPLICATE_LIB_OK"] = "tampered"
    assert observed["KMP_DUPLICATE_LIB_OK"] == "True"


def test_does_not_touch_os_environ():
    before = dict(__import__("os").environ)
    verify_import_environment(LAUNCH, _observed(), LIBTCC)
    assert dict(__import__("os").environ) == before


# --- missing / wrong additions ---------------------------------------------


@pytest.mark.parametrize("missing_key", sorted(ADDITIONS))
def test_missing_each_addition(missing_key: str):
    observed = {k: v for k, v in _observed().items() if k != missing_key}
    with pytest.raises(RuntimeError) as excinfo:
        verify_import_environment(dict(LAUNCH), observed, LIBTCC)
    assert str(excinfo.value) == "import environment verification failed"


@pytest.mark.parametrize("bad_value", ["", "False", "true", "TRUE", "1"])
def test_wrong_threadpoolctl_value(bad_value: str):
    observed = _observed(KMP_DUPLICATE_LIB_OK=bad_value)
    with pytest.raises(RuntimeError):
        verify_import_environment(dict(LAUNCH), observed, LIBTCC)


@pytest.mark.parametrize(
    "bad_value",
    [
        "dirty_decay_ms:500,muzzy_decay_ms:100",
        "dirty_decay_ms:500",
        "muzzy_decay_ms:1000",
        "dirty_decay_ms: 500,muzzy_decay_ms:1000",
        "",
    ],
)
def test_wrong_polars_value(bad_value: str):
    observed = _observed(_RJEM_MALLOC_CONF=bad_value)
    with pytest.raises(RuntimeError):
        verify_import_environment(dict(LAUNCH), observed, LIBTCC)


@pytest.mark.parametrize(
    "bad_path",
    [
        "/other/.venv/lib/python3.12/site-packages/blosc2/lib/libtcc.dylib",
        LIBTCC.replace("python3.12", "python3.11"),
        LIBTCC + "x",
        LIBTCC.upper(),
    ],
)
def test_wrong_blosc2_value(bad_path: str):
    observed = _observed(ME_DSL_JIT_LIBTCC_PATH=bad_path)
    with pytest.raises(RuntimeError):
        verify_import_environment(dict(LAUNCH), observed, LIBTCC)


# --- unknown / changed originals -------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [{"EXTRA_UNREGISTERED": "1"}, {"OMP_NUM_THREADS": "4"}, {"PYTHONPATH": "src"}],
)
def test_extra_unknown_key_rejected(extra: dict[str, str]):
    observed = _observed(**extra)
    with pytest.raises(RuntimeError):
        verify_import_environment(dict(LAUNCH), observed, LIBTCC)


@pytest.mark.parametrize("changed_key", sorted(LAUNCH))
def test_changed_original_launch_value_rejected(changed_key: str):
    observed = _observed(**{changed_key: LAUNCH[changed_key] + "-mutated"})
    with pytest.raises(RuntimeError):
        verify_import_environment(dict(LAUNCH), observed, LIBTCC)


@pytest.mark.parametrize("dropped_key", sorted(LAUNCH))
def test_missing_original_launch_key_rejected(dropped_key: str):
    observed = {k: v for k, v in _observed().items() if k != dropped_key}
    with pytest.raises(RuntimeError):
        verify_import_environment(dict(LAUNCH), observed, LIBTCC)


# --- launch/additions overlap ----------------------------------------------


@pytest.mark.parametrize("overlap_key", sorted(ADDITIONS))
def test_overlap_launch_and_additions_rejected(overlap_key: str):
    launch = {**LAUNCH, overlap_key: "preseeded"}
    observed = _observed()
    with pytest.raises(RuntimeError):
        verify_import_environment(launch, observed, LIBTCC)


@pytest.mark.parametrize("overlap_key", sorted(ADDITIONS))
def test_overlap_rejected_even_when_values_match(overlap_key: str):
    launch = {**LAUNCH, overlap_key: ADDITIONS[overlap_key]}
    observed = {**launch, **ADDITIONS}
    with pytest.raises(RuntimeError):
        verify_import_environment(launch, observed, LIBTCC)


# --- bad types --------------------------------------------------------------


@pytest.mark.parametrize("bad_launch", [None, "launch", 3, [("PATH", "/usr/bin")], frozenset()])
def test_bad_launch_mapping_type(bad_launch: object):
    with pytest.raises(RuntimeError):
        verify_import_environment(bad_launch, _observed(), LIBTCC)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_observed", [None, "observed", 3, (), []])
def test_bad_observed_mapping_type(bad_observed: object):
    with pytest.raises(RuntimeError):
        verify_import_environment(dict(LAUNCH), bad_observed, LIBTCC)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_key", ["", " PATH"])
def test_bad_key_empty_is_rejected(bad_key: str):
    observed = _observed(**{bad_key: "x"}) if bad_key else _observed()
    launch = {**LAUNCH, bad_key: "y"} if bad_key else dict(LAUNCH)
    if not bad_key:
        launch = {"": "y", **LAUNCH}
        observed = {"": "y", **_observed()}
    with pytest.raises(RuntimeError):
        verify_import_environment(launch, observed, LIBTCC)


@pytest.mark.parametrize("non_str", [None, 1, 1.5, True, ("a",)])
def test_non_str_keys_and_values_rejected(non_str: object):
    launch_bad_key = {**LAUNCH, non_str: "/usr/sbin"}
    with pytest.raises(RuntimeError):
        verify_import_environment(launch_bad_key, _observed(), LIBTCC)  # type: ignore[dict-item]

    launch_bad_value = {**LAUNCH, "SOME_KEY": non_str}
    with pytest.raises(RuntimeError):
        verify_import_environment(launch_bad_value, _observed(SOME_KEY="ok"), LIBTCC)  # type: ignore[dict-item]

    observed_bad_value = _observed(SOME_KEY=non_str)
    with pytest.raises(RuntimeError):
        verify_import_environment({**LAUNCH, "SOME_KEY": "ok"}, observed_bad_value, LIBTCC)


@pytest.mark.parametrize("bad_path", [None, 1, Path(LIBTCC), [LIBTCC]])
def test_bad_libtcc_path_type(bad_path: object):
    with pytest.raises(RuntimeError):
        verify_import_environment(dict(LAUNCH), _observed(), bad_path)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad_path",
    [
        "",
        ".venv/lib/python3.12/site-packages/blosc2/lib/libtcc.dylib",
        "../biohub-cell-tracking/.venv/lib/python3.12/site-packages/blosc2/lib/libtcc.dylib",
        "/opt/homebrew/lib/python3.12/site-packages/blosc2/lib/libtcc.dylib.wrong",
        "/somewhere/blosc2/lib/tcc.dylib",
        "/somewhere/blosc2/lib/",
    ],
)
def test_bad_libtcc_path_shape(bad_path: str):
    with pytest.raises(RuntimeError):
        verify_import_environment(dict(LAUNCH), _observed(), bad_path)


def test_error_text_never_contains_values():
    observed = _observed(KMP_DUPLICATE_LIB_OK="nope")
    with pytest.raises(RuntimeError) as excinfo:
        verify_import_environment(dict(LAUNCH), observed, LIBTCC)
    message = str(excinfo.value)
    assert message == "import environment verification failed"
    for secret in (LAUNCH["PATH"], ADDITIONS["_RJEM_MALLOC_CONF"], LIBTCC, "nope"):
        assert secret not in message


# --- required fresh subprocess regression ----------------------------------


_CHILD_CODE = """
import os
from pathlib import Path

from biohub import e26_screen as e

e._check_score_entry_runtime()

launch = dict(os.environ)

import threadpoolctl
import polars
import blosc2

from scripts.experiments.e27.e27_score_environment_v2 import verify_import_environment

libtcc_path = str(Path.cwd() / '.venv/lib/python3.12/site-packages/blosc2/lib/libtcc.dylib')

observed = dict(os.environ)
additions = verify_import_environment(launch, observed, libtcc_path)
assert additions['ME_DSL_JIT_LIBTCC_PATH'] == libtcc_path

polluted = dict(observed)
polluted['EXTRA_UNREGISTERED'] = '1'
try:
    verify_import_environment(launch, polluted, libtcc_path)
except RuntimeError:
    pass
else:
    raise AssertionError('unregistered extra variable was accepted')

assert dict(os.environ) == observed

print('FRESH_IMPORT_ENV_OK')
"""


@pytest.mark.skipif(sys.platform != "darwin", reason="blosc2 libtcc.dylib path is macOS-specific")
def test_fresh_subprocess_import_environment_regression():
    env = e.generation_environment()
    completed = subprocess.run(
        [sys.executable, "-c", _CHILD_CODE],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=True,
    )
    assert completed.stdout.strip() == "FRESH_IMPORT_ENV_OK"
