"""Isolated import-environment verification helper for a later versioned scorer.

This module is standard-library only. It does not import the old frozen scorer,
read experiment or ground-truth files, rescore old candidates, or touch os.environ.

Scope note: this helper checks that the observed process environment equals the
launch environment plus exactly three preregistered dependency-added variables.
It does NOT independently prove dependency provenance; a later PLAN must pin the
dependency files, the libtcc path literal, and this helper's hash.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["verify_import_environment"]

THREADPOOLCTL_KEY = "KMP_DUPLICATE_LIB_OK"
THREADPOOLCTL_VALUE = "True"

POLARS_KEY = "_RJEM_MALLOC_CONF"
POLARS_VALUE = "dirty_decay_ms:500,muzzy_decay_ms:1000"

BLOSC2_SUFFIX = "/blosc2/lib/libtcc.dylib"
BLOSC2_KEY = "ME_DSL_JIT_LIBTCC_PATH"

_EXPECTED_KEYS = (THREADPOOLCTL_KEY, POLARS_KEY, BLOSC2_KEY)

_ERROR = "import environment verification failed"


def _fail() -> None:
    raise RuntimeError(_ERROR)


def _is_concrete_str(value: object) -> bool:
    return type(value) is str and value != ""


def _validate_mapping(mapping: object) -> dict[str, str]:
    if type(mapping) is not dict:
        _fail()
    for key, value in mapping.items():
        if not _is_concrete_str(key) or type(value) is not str:
            _fail()
    return mapping


def verify_import_environment(
    launch: dict[str, str],
    observed: dict[str, str],
    libtcc_path: str,
) -> dict[str, str]:
    """Validate that `observed` is exactly `launch` plus the three known additions.

    Returns a fresh dict containing only the validated additions. Never mutates
    inputs, os.environ, or any file. Raises RuntimeError with fixed generic text
    on any mismatch; error messages never include values.
    """
    launch_map = _validate_mapping(launch)
    observed_map = _validate_mapping(observed)

    if type(libtcc_path) is not str or libtcc_path == "":
        _fail()
    candidate = Path(libtcc_path)
    if not candidate.is_absolute():
        _fail()
    if not libtcc_path.endswith(BLOSC2_SUFFIX):
        _fail()

    additions = {
        THREADPOOLCTL_KEY: THREADPOOLCTL_VALUE,
        POLARS_KEY: POLARS_VALUE,
        BLOSC2_KEY: libtcc_path,
    }

    for key in _EXPECTED_KEYS:
        if key in launch_map:
            _fail()

    expected = {**launch_map, **additions}

    if set(observed_map) != set(expected):
        _fail()
    for key, value in expected.items():
        if observed_map[key] != value:
            _fail()

    return {key: value for key, value in additions.items()}
