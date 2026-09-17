# E26 unit02a — finish contract-test coverage, direct-user Cloud delivery

> 履歴・非運用・現行起動に使用禁止。この旧タスクは保存用です。
> 現行方針は [AGENTS.md](../AGENTS.md)、MAX評価入口は
> [評価手順](../.codex/runners/biohub_max_implementer.instructions.md) を参照。
> 以下のモデル指定・命令・実行例は当時の履歴であり、現在のworkerへ渡してはいけません。

2026-09-06. This is one new bounded defect-correction task within the user's
direct interactive request to prioritize improvement experiments and submit
once per scientific loop. Exact qwen3.7-plus via qwen_token_plan only.
Parent-supervised600s cap, retries0, fallback0, no unattended launch.

Revision2 completed normally but was NOT applied. Its production module below
passes independent static review and Ruff; the tests still lacked explicit
coverage and had23 lint violations. Preserve the entire original worker log.
The worktree remains clean at a17eb0203ee791161f18774a1987e4f3dfd6c7fa with both
target files absent. This task repairs tests, not the candidate or numerical gates.

## Delivery

NO tools, filesystem exploration, model calls, network, agents or claims of tests
run. Return EXACTLY these two headings and two complete Python blocks, and NO
preface/epilogue or other code fences:
### src/biohub/e26_screen.py
(code fence python containing the EXACT complete fixed module below)
### tests/test_e26_screen.py
(code fence python containing the complete new tests you author)

Use real triple-backtick python fences in that output. Copy the fixed source
module byte-for-byte, including its final newline. The parent must not repair
scientific code or fill in tests. All tests must be real, synthetic and explicit.
The parent inspects complete log, requires tool/error0 and normal completion,
checks same clean HEAD and absent targets, reads both full files and applies
only byte-preserved Qwen-authored files. Incomplete output is retained, not applied.
No placeholders, skip/xfail/noqa/lint-config edits or assertion weakening.

## Required tests (all, not a sample)

Use compact parametrized tests and helpers to avoid repeated long call lines.
Ruff selects E,W,F,I,UP,B; line-length120. Keep ALL lines under120, including
comments/type-ignore comments. Imports must be sorted; import only used names.
Use dataclasses.fields/replace, pathlib.Path, pytest, and existing config factory.
Type-ignore comments may be used only for deliberately invalid argument types.

1. Exact constants CANDIDATE_ID=e23_motion_relink_off_v1 and
   ARM_ORDER=(public4_parity,baseline,candidate).
2. All three arms return PostprocConfig. For EACH arm compare EVERY dataclass
   field, BOTH exact type and value, against a separately constructed existing
   build_config(overrides=...,test_dir=image_root,profile="e23") reference.
   Reference overrides have all four explicit checkpoint/manifest string paths.
   Only candidate has BIOHUB_OUTPUT_MOTION_RELINK="0"; no reference may call
   build_arm_config. Explicitly verify all four path fields for each arm.
3. Public4 and baseline built with identical roots have all-field/type equality.
   Public4 with its separate root versus baseline may differ ONLY in TEST_DIR,
   and every remaining field must match in exact type and value.
4. Pair baseline/candidate has exactly one differing field OUTPUT_MOTION_RELINK,
   literal True/False, same types for every field, twins literal False in both.
   validate_config_pair returns None for the valid pair.
5. Invalid arms: unknown string and nonstring values (include None,int,bool,list).
   Build path arguments: EACH image_root/checkpoint/manifest rejects string,
   None and int. Valid nonexistent Path values need no real files.
6. Validation wrong config objects in EACH arm reject with E26Error. EACH explicit
   expected image_root/checkpoint/manifest argument rejects malformed types.
7. Shared AND baseline-only AND candidate-only mutations must reject for EACH:
   GAP_CLOSE_UM, EXPERIMENT_TAG, TEST_DIR, DEEPCENTER_CHECKPOINT,
   DEEPCENTER_CHECKPOINT_DEFAULT, DEEPCENTER_MANIFEST,
   DEEPCENTER_MANIFEST_DEFAULT. Mutate to a genuinely different value of the
   same expected type, keep supplied expected paths fixed. Cartesian
   parametrization is encouraged, not just one path or one side.
8. Start from a valid pair, then change EACH expected Path argument to a different
   valid Path while leaving the actual pair unchanged; EACH must reject.
9. Preserve the FOUR literal motion/twin rejection cases and exact regex text:
   baseline OUTPUT_MOTION_RELINK must be True
   candidate OUTPUT_MOTION_RELINK must be False
   baseline OUTPUT_STEAL_TWIN_REWIRE must be False
   candidate OUTPUT_STEAL_TWIN_REWIRE must be False
   Use wrong opposite bool in each. Also test baseline motion=1 and candidate
   motion=0, baseline/candidate twin=0; equality of bool and int must NOT pass.
10. Other all-field type checks: for BOTH arms reject int1 replacing bool
    OUTPUT_ENFORCE_NEXT_FRAME, boolTrue replacing integer
    MOTION_RELINK_MAX_FRAME_NODES, integer14 replacing float OUTPUT_EDGE_MAX_UM.
11. Environment independence: monkeypatch representative BIOHUB_* env vars
    (motion, twin, tag and weight path) to conflicting strings; full config
    construction/reference comparison and validate pair still unchanged.
12. Inputs are pure and filesystem independent: synthetic Paths are sufficient;
    do not open real files, GT, model or environment secrets. No scoring status,
    adoption, submission, schema/gate or CLI work belongs in this unit.

## Existing APIs and complete fixed source

Import PostprocConfig/build_config from biohub.public_postproc.config.
build_config(overrides:dict[str,str]|None=None,test_dir:Path|str=Path("data/test"),
profile:str="base1")->PostprocConfig uses only its in-memory map, not os.environ.
Expected reference profile MUST explicitly be e23. Its dataclass is frozen.
The existing config module SHA is
415a586ad4d8a81b96314025fa0cf05ce6c797df7ef8eb75e53f48efe192d882.

Preserve this complete Qwen-authored production module unchanged:
```python
"""E26 screening utilities for config construction and pair validation.

This module provides helpers to build ``PostprocConfig`` instances for the
three E26 arms (``public4_parity``, ``baseline``, ``candidate``) and to
validate that a baseline/candidate pair differs only in the expected
``OUTPUT_MOTION_RELINK`` flag.

The candidate arm is identified by :data:`CANDIDATE_ID` and disables motion
relinking via ``BIOHUB_OUTPUT_MOTION_RELINK="0"``. All arms use the existing
``build_config`` factory from ``biohub.public_postproc.config`` with explicit
path overrides for the DeepCenter checkpoint/manifest variables.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

from biohub.public_postproc.config import PostprocConfig, build_config


class E26Error(RuntimeError):
    """Raised when an E26 screening operation encounters invalid input."""


CANDIDATE_ID: str = "e23_motion_relink_off_v1"

ARM_ORDER: tuple[str, ...] = ("public4_parity", "baseline", "candidate")

# The four explicit string path overrides applied identically across all arms.
_DEEPCENTER_OVERRIDES_KEYS: tuple[str, ...] = (
    "BIOHUB_DEEPCENTER_CHECKPOINT",
    "BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT",
    "BIOHUB_DEEPCENTER_MANIFEST",
    "BIOHUB_DEEPCENTER_MANIFEST_DEFAULT",
)


def build_arm_config(arm: str, image_root: Path, checkpoint: Path, manifest: Path) -> PostprocConfig:
    """Build a ``PostprocConfig`` for the given E26 arm.

    Parameters
    ----------
    arm:
        One of :data:`ARM_ORDER`.  All three arms use the ``e23`` profile;
        ``public4_parity`` may use a different image root but shares the same
        preset configuration as baseline and candidate.
    image_root:
        Root directory for images (passed as ``test_dir`` to ``build_config``).
    checkpoint:
        Path used for ``BIOHUB_DEEPCENTER_CHECKPOINT`` and
        ``BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT``.
    manifest:
        Path used for ``BIOHUB_DEEPCENTER_MANIFEST`` and
        ``BIOHUB_DEEPCENTER_MANIFEST_DEFAULT``.

    Returns
    -------
    PostprocConfig
        The constructed configuration.

    Raises
    ------
    E26Error
        If *arm* is not a recognised value or any argument has the wrong type.
    """
    if not isinstance(arm, str):
        raise E26Error(f"arm must be a str, got {type(arm).__name__}")
    if arm not in ARM_ORDER:
        raise E26Error(f"unknown arm {arm!r}; expected one of {ARM_ORDER}")
    if not isinstance(image_root, Path):
        raise E26Error(f"image_root must be a Path, got {type(image_root).__name__}")
    if not isinstance(checkpoint, Path):
        raise E26Error(f"checkpoint must be a Path, got {type(checkpoint).__name__}")
    if not isinstance(manifest, Path):
        raise E26Error(f"manifest must be a Path, got {type(manifest).__name__}")

    checkpoint_str = str(checkpoint)
    manifest_str = str(manifest)

    base_overrides: dict[str, str] = {
        "BIOHUB_DEEPCENTER_CHECKPOINT": checkpoint_str,
        "BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT": checkpoint_str,
        "BIOHUB_DEEPCENTER_MANIFEST": manifest_str,
        "BIOHUB_DEEPCENTER_MANIFEST_DEFAULT": manifest_str,
    }

    if arm == "candidate":
        overrides = dict(base_overrides)
        overrides["BIOHUB_OUTPUT_MOTION_RELINK"] = "0"
    else:
        # public4_parity and baseline both use e23 profile
        overrides = dict(base_overrides)

    return build_config(overrides=overrides, test_dir=image_root, profile="e23")


def validate_config_pair(
    baseline: PostprocConfig,
    candidate: PostprocConfig,
    *,
    image_root: Path,
    checkpoint: Path,
    manifest: Path,
) -> None:
    """Validate that *baseline* and *candidate* form a correct E26 pair.

    The function rebuilds the expected baseline and candidate configs from the
    supplied path arguments using the exact same logic as
    :func:`build_arm_config`, then compares every field of the actual
    ``PostprocConfig`` objects against the expected ones.

    The only permitted difference between baseline and candidate is that
    ``OUTPUT_MOTION_RELINK`` must be ``True`` in the baseline and ``False`` in
    the candidate.  Additionally, ``OUTPUT_STEAL_TWIN_REWIRE`` must be literal
    ``False`` in both configs.

    Parameters
    ----------
    baseline:
        The actual baseline ``PostprocConfig``.
    candidate:
        The actual candidate ``PostprocConfig``.
    image_root:
        Image root used to build the expected configs.
    checkpoint:
        Checkpoint path used to build the expected configs.
    manifest:
        Manifest path used to build the expected configs.

    Raises
    ------
    E26Error
        If the pair does not match the expected contract.
    """
    if not isinstance(baseline, PostprocConfig):
        raise E26Error(f"baseline must be a PostprocConfig, got {type(baseline).__name__}")
    if not isinstance(candidate, PostprocConfig):
        raise E26Error(f"candidate must be a PostprocConfig, got {type(candidate).__name__}")
    if not isinstance(image_root, Path):
        raise E26Error(f"image_root must be a Path, got {type(image_root).__name__}")
    if not isinstance(checkpoint, Path):
        raise E26Error(f"checkpoint must be a Path, got {type(checkpoint).__name__}")
    if not isinstance(manifest, Path):
        raise E26Error(f"manifest must be a Path, got {type(manifest).__name__}")

    expected_baseline = build_arm_config("baseline", image_root, checkpoint, manifest)
    expected_candidate = build_arm_config("candidate", image_root, checkpoint, manifest)

    # Check motion relink values first before full-field comparison
    if baseline.OUTPUT_MOTION_RELINK is not True:
        raise E26Error(
            f"baseline OUTPUT_MOTION_RELINK must be True, got {baseline.OUTPUT_MOTION_RELINK!r}"
        )
    if candidate.OUTPUT_MOTION_RELINK is not False:
        raise E26Error(
            f"candidate OUTPUT_MOTION_RELINK must be False, got {candidate.OUTPUT_MOTION_RELINK!r}"
        )

    # Both must have OUTPUT_STEAL_TWIN_REWIRE == False
    if baseline.OUTPUT_STEAL_TWIN_REWIRE is not False:
        raise E26Error(
            f"baseline OUTPUT_STEAL_TWIN_REWIRE must be False, got {baseline.OUTPUT_STEAL_TWIN_REWIRE!r}"
        )
    if candidate.OUTPUT_STEAL_TWIN_REWIRE is not False:
        raise E26Error(
            f"candidate OUTPUT_STEAL_TWIN_REWIRE must be False, got {candidate.OUTPUT_STEAL_TWIN_REWIRE!r}"
        )

    _assert_configs_equal(baseline, expected_baseline, label="baseline")
    _assert_configs_equal(candidate, expected_candidate, label="candidate")


def _assert_configs_equal(actual: PostprocConfig, expected: PostprocConfig, label: str) -> None:
    """Assert that two ``PostprocConfig`` instances are identical field-by-field.

    This performs strict type-aware comparison: ``bool`` values must match
    exactly (``True`` is not equal to ``1`` for our purposes), and all other
    fields must also match in both value and type.

    Raises
    ------
    E26Error
        If any field differs.
    """
    for field in dataclasses.fields(PostprocConfig):
        name = field.name
        actual_val = getattr(actual, name)
        expected_val = getattr(expected, name)

        # Strict type check: bool vs int must not pass.
        if type(actual_val) is not type(expected_val):
            raise E26Error(
                f"{label} field {name}: type mismatch — "
                f"expected {type(expected_val).__name__}, got {type(actual_val).__name__}"
            )

        if actual_val != expected_val:
            raise E26Error(
                f"{label} field {name}: value mismatch — "
                f"expected {expected_val!r}, got {actual_val!r}"
            )
```

## Parent verification and remaining work

After full source/test read and byte-preserving application in approved worktree:
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 canonical/.venv/bin/python -m pytest -q
-p no:cacheprovider tests/test_e26_screen.py
tests/test_e26_motion_relink_contract.py tests/test_public_postproc.py
canonical/.venv/bin/ruff check --no-cache src/biohub/e26_screen.py tests/test_e26_screen.py
Here canonical is /Users/taichi/コンペティション/Kaggle/biohub-cell-tracking.
Qwen must NOT run these commands or claim results. Parent and independent SOL
must actually run/review them. Unit02b still requires the original fixed splits,
paired stats, numerical stage gates and errors; unit03/04 still require generation,
preregistration, staged official scoring and all original tests. This config/test
unit is NOT a finished runner or a scientific loop, and has no submission authority.
