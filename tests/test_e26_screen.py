"""Tests for biohub.e26_screen config construction and pair validation."""
from __future__ import annotations

import csv
import dataclasses
import hashlib
import json
import math
import os
import stat
import subprocess
import sys
import time
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

from biohub import e26_screen
from biohub.e26_screen import (
    ARM_ORDER,
    CANDIDATE_ID,
    EVAL12,
    EVAL24,
    EVAL36,
    GATE_INPUT_SCHEMA,
    GATE_RESULT_SCHEMA,
    PUBLIC4,
    E26Error,
    build_arm_config,
    check_runtime_budget,
    create_preregistration_directory,
    evaluate_gate,
    generation_environment,
    initialize_inference_runtime,
    inventory_path,
    paired_statistics,
    read_json_bound,
    self_peak_rss_bytes,
    validate_budget,
    validate_config_pair,
    validate_generated_csv,
    validate_raw_statistics,
    verify_inventory,
    write_json_exclusive,
)
from biohub.public_postproc.config import PostprocConfig, build_config

# --- Helpers ---------------------------------------------------------------


def _make_paths() -> tuple[Path, Path, Path]:
    """Return synthetic Paths suitable for config building."""
    return (
        Path("/tmp/image_root"),
        Path("/tmp/checkpoint.pt"),
        Path("/tmp/manifest.json"),
    )


def _ref_config(
    image_root: Path, checkpoint: Path, manifest: Path, extra: dict[str, str] | None = None
) -> PostprocConfig:
    """Build a reference PostprocConfig with explicit DeepCenter overrides."""
    overrides: dict[str, str] = {
        "BIOHUB_DEEPCENTER_CHECKPOINT": str(checkpoint),
        "BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT": str(checkpoint),
        "BIOHUB_DEEPCENTER_MANIFEST": str(manifest),
        "BIOHUB_DEEPCENTER_MANIFEST_DEFAULT": str(manifest),
    }
    if extra:
        overrides.update(extra)
    return build_config(overrides=overrides, test_dir=image_root, profile="e23")


def _all_fields_match(cfg: PostprocConfig, ref: PostprocConfig) -> None:
    """Assert every field matches in both type and value."""
    for fld in dataclasses.fields(PostprocConfig):
        name = fld.name
        actual = getattr(cfg, name)
        expected = getattr(ref, name)
        assert type(actual) is type(expected), (
            f"{name}: type mismatch — expected {type(expected).__name__}, "
            f"got {type(actual).__name__}"
        )
        assert actual == expected, f"{name}: value mismatch — expected {expected!r}, got {actual!r}"


# --- Test 1: Exact constants -----------------------------------------------


def test_constants() -> None:
    assert CANDIDATE_ID == "e23_motion_relink_off_v1"
    assert ARM_ORDER == ("public4_parity", "baseline", "candidate")


# --- Test 2: All three arms return PostprocConfig with correct fields ------


@pytest.mark.parametrize("arm", ARM_ORDER)
def test_all_arms_return_valid_config(arm: str) -> None:
    image_root, checkpoint, manifest = _make_paths()
    cfg = build_arm_config(arm, image_root, checkpoint, manifest)
    assert isinstance(cfg, PostprocConfig)

    extra: dict[str, str] = {}
    if arm == "candidate":
        extra["BIOHUB_OUTPUT_MOTION_RELINK"] = "0"
    ref = _ref_config(image_root, checkpoint, manifest, extra=extra)
    _all_fields_match(cfg, ref)
    assert type(cfg.DEEPCENTER_CHECKPOINT) is str
    assert cfg.DEEPCENTER_CHECKPOINT == str(checkpoint)
    assert type(cfg.DEEPCENTER_CHECKPOINT_DEFAULT) is str
    assert cfg.DEEPCENTER_CHECKPOINT_DEFAULT == str(checkpoint)
    assert type(cfg.DEEPCENTER_MANIFEST) is str
    assert cfg.DEEPCENTER_MANIFEST == str(manifest)
    assert type(cfg.DEEPCENTER_MANIFEST_DEFAULT) is str
    assert cfg.DEEPCENTER_MANIFEST_DEFAULT == str(manifest)


# --- Test 3: Public4 parity vs baseline equality ---------------------------


def test_public4_parity_equals_baseline_same_root() -> None:
    image_root, checkpoint, manifest = _make_paths()
    pub4 = build_arm_config("public4_parity", image_root, checkpoint, manifest)
    bl = build_arm_config("baseline", image_root, checkpoint, manifest)
    _all_fields_match(pub4, bl)


def test_public4_parity_differs_only_in_test_dir() -> None:
    ckpt, manifest = Path("/tmp/ckpt.pt"), Path("/tmp/manifest.json")
    pub4 = build_arm_config("public4_parity", Path("/pub4_root"), ckpt, manifest)
    bl = build_arm_config("baseline", Path("/base_root"), ckpt, manifest)
    for fld in dataclasses.fields(PostprocConfig):
        name = fld.name
        pv = getattr(pub4, name)
        bv = getattr(bl, name)
        if name == "TEST_DIR":
            assert pv != bv
        else:
            assert type(pv) is type(bv)
            assert pv == bv


# --- Test 4: Baseline/candidate differ only in MOTION_RELINK ---------------


def test_baseline_candidate_single_field_diff() -> None:
    image_root, checkpoint, manifest = _make_paths()
    bl = build_arm_config("baseline", image_root, checkpoint, manifest)
    cand = build_arm_config("candidate", image_root, checkpoint, manifest)

    differing: list[str] = []
    for fld in dataclasses.fields(PostprocConfig):
        name = fld.name
        bv = getattr(bl, name)
        cv = getattr(cand, name)
        if bv != cv or type(bv) is not type(cv):
            differing.append(name)

    assert differing == ["OUTPUT_MOTION_RELINK"]
    assert bl.OUTPUT_MOTION_RELINK is True
    assert cand.OUTPUT_MOTION_RELINK is False
    assert type(bl.OUTPUT_MOTION_RELINK) is bool
    assert type(cand.OUTPUT_MOTION_RELINK) is bool

    # Twins must both be False
    assert bl.OUTPUT_STEAL_TWIN_REWIRE is False
    assert cand.OUTPUT_STEAL_TWIN_REWIRE is False

    # validate_config_pair should succeed
    assert validate_config_pair(bl, cand, image_root=image_root, checkpoint=checkpoint, manifest=manifest) is None


# --- Test 5: Invalid arms and path types -----------------------------------


@pytest.mark.parametrize("bad_arm", ["unknown", "", 1, None, True, []])
def test_invalid_arm_raises(bad_arm: object) -> None:
    ir, cp, mf = _make_paths()
    with pytest.raises(E26Error):
        build_arm_config(bad_arm, ir, cp, mf)  # type: ignore[arg-type]


@pytest.mark.parametrize("arg_name,arg_value", [
    ("image_root", "/string/path"),
    ("image_root", None),
    ("image_root", 42),
    ("checkpoint", "/string/path"),
    ("checkpoint", None),
    ("checkpoint", 42),
    ("manifest", "/string/path"),
    ("manifest", None),
    ("manifest", 42),
])
def test_path_args_reject_bad_types(arg_name: str, arg_value: object) -> None:
    kwargs: dict[str, object] = {"arm": "baseline"}
    defaults: dict[str, Path] = {
        "image_root": Path("/tmp/ir"),
        "checkpoint": Path("/tmp/cp.pt"),
        "manifest": Path("/tmp/mf.json"),
    }
    for k, v in defaults.items():
        if k not in kwargs:
            kwargs[k] = v
    kwargs[arg_name] = arg_value
    with pytest.raises(E26Error):
        build_arm_config(**kwargs)  # type: ignore[arg-type]


# --- Test 6: Validation rejects wrong config objects -----------------------


@pytest.mark.parametrize("side", ["baseline", "candidate"])
@pytest.mark.parametrize("bad", ["not_a_config", None, {}, 1])
def test_validate_rejects_non_config_objects(side: str, bad: object) -> None:
    ir, cp, mf = _make_paths()
    pair = {arm: build_arm_config(arm, ir, cp, mf) for arm in ("baseline", "candidate")}
    pair[side] = bad  # type: ignore[assignment]
    with pytest.raises(E26Error, match=f"^{side} must be a PostprocConfig, got {type(bad).__name__}$"):
        validate_config_pair(**pair, image_root=ir, checkpoint=cp, manifest=mf)


def test_validate_rejects_bad_path_args() -> None:
    bl = build_arm_config("baseline", *_make_paths())
    cand = build_arm_config("candidate", *_make_paths())
    for bad in ["/str", None, 42]:
        with pytest.raises(E26Error):
            validate_config_pair(
                bl, cand, image_root=bad, checkpoint=_make_paths()[1], manifest=_make_paths()[2]
            )  # type: ignore[arg-type]
        with pytest.raises(E26Error):
            validate_config_pair(
                bl, cand, image_root=_make_paths()[0], checkpoint=bad, manifest=_make_paths()[2]
            )  # type: ignore[arg-type]
        with pytest.raises(E26Error):
            validate_config_pair(
                bl, cand, image_root=_make_paths()[0], checkpoint=_make_paths()[1], manifest=bad
            )  # type: ignore[arg-type]


# --- Test 7: Mutations that must be rejected -------------------------------

_MUTABLE_FIELDS: list[str] = [
    "GAP_CLOSE_UM",
    "EXPERIMENT_TAG",
    "TEST_DIR",
    "DEEPCENTER_CHECKPOINT",
    "DEEPCENTER_CHECKPOINT_DEFAULT",
    "DEEPCENTER_MANIFEST",
    "DEEPCENTER_MANIFEST_DEFAULT",
]


def _mutate_config(cfg: PostprocConfig, field: str) -> PostprocConfig:
    """Return a copy of *cfg* with *field* changed to a genuinely different value."""
    current = getattr(cfg, field)
    if isinstance(current, bool):
        new_val = not current
    elif isinstance(current, int):
        new_val = current + 1
    elif isinstance(current, float):
        new_val = current + 1.0
    elif isinstance(current, str):
        new_val = current + "_mutated"
    elif isinstance(current, Path):
        new_val = current / "mutated"
    else:
        new_val = current
    return dataclasses.replace(cfg, **{field: new_val})


@pytest.mark.parametrize("field", _MUTABLE_FIELDS)
@pytest.mark.parametrize("side", ["baseline", "candidate", "both"])
def test_mutation_rejected(field: str, side: str) -> None:
    ir, cp, mf = _make_paths()
    bl = build_arm_config("baseline", ir, cp, mf)
    cand = build_arm_config("candidate", ir, cp, mf)

    if side in ("baseline", "both"):
        bl = _mutate_config(bl, field)
    if side in ("candidate", "both"):
        cand = _mutate_config(cand, field)

    with pytest.raises(E26Error):
        validate_config_pair(bl, cand, image_root=ir, checkpoint=cp, manifest=mf)


# --- Test 8: Changing expected paths while pair unchanged --------------------


@pytest.mark.parametrize("path_arg", ["image_root", "checkpoint", "manifest"])
def test_wrong_expected_path_rejected(path_arg: str) -> None:
    ir, cp, mf = _make_paths()
    bl = build_arm_config("baseline", ir, cp, mf)
    cand = build_arm_config("candidate", ir, cp, mf)

    kwargs: dict[str, Path] = {"image_root": ir, "checkpoint": cp, "manifest": mf}
    kwargs[path_arg] = Path("/different/" + path_arg)

    with pytest.raises(E26Error):
        validate_config_pair(bl, cand, **kwargs)


# --- Test 9: Motion/twin rejection cases -----------------------------------


@pytest.mark.parametrize(
    "side,field,value,expected_error",
    [
        ("baseline", "OUTPUT_MOTION_RELINK", False, "baseline OUTPUT_MOTION_RELINK must be True, got False"),
        ("baseline", "OUTPUT_MOTION_RELINK", 1, "baseline OUTPUT_MOTION_RELINK must be True, got 1"),
        ("candidate", "OUTPUT_MOTION_RELINK", True, "candidate OUTPUT_MOTION_RELINK must be False, got True"),
        ("candidate", "OUTPUT_MOTION_RELINK", 0, "candidate OUTPUT_MOTION_RELINK must be False, got 0"),
        ("baseline", "OUTPUT_STEAL_TWIN_REWIRE", True, "baseline OUTPUT_STEAL_TWIN_REWIRE must be False, got True"),
        ("baseline", "OUTPUT_STEAL_TWIN_REWIRE", 0, "baseline OUTPUT_STEAL_TWIN_REWIRE must be False, got 0"),
        ("candidate", "OUTPUT_STEAL_TWIN_REWIRE", True, "candidate OUTPUT_STEAL_TWIN_REWIRE must be False, got True"),
        ("candidate", "OUTPUT_STEAL_TWIN_REWIRE", 0, "candidate OUTPUT_STEAL_TWIN_REWIRE must be False, got 0"),
    ],
)
def test_motion_twin_rejection(
    side: str, field: str, value: object, expected_error: str
) -> None:
    ir, cp, mf = _make_paths()
    pair = {arm: build_arm_config(arm, ir, cp, mf) for arm in ("baseline", "candidate")}
    pair[side] = dataclasses.replace(pair[side], **{field: value})
    with pytest.raises(E26Error, match=f"^{expected_error}$"):
        validate_config_pair(**pair, image_root=ir, checkpoint=cp, manifest=mf)


# --- Test 10: Other all-field type checks ----------------------------------


@pytest.mark.parametrize("side", ["baseline", "candidate"])
@pytest.mark.parametrize(
    "field,value,expected_type",
    [("OUTPUT_ENFORCE_NEXT_FRAME", 1, "bool"),
     ("MOTION_RELINK_MAX_FRAME_NODES", True, "int"),
     ("OUTPUT_EDGE_MAX_UM", 14, "float")],
)
def test_other_type_mismatches(side: str, field: str, value: object, expected_type: str) -> None:
    ir, cp, mf = _make_paths()
    pair = {arm: build_arm_config(arm, ir, cp, mf) for arm in ("baseline", "candidate")}
    pair[side] = dataclasses.replace(pair[side], **{field: value})
    expected_error = f"^{side} field {field}: type mismatch — expected {expected_type}, got {type(value).__name__}$"
    with pytest.raises(E26Error, match=expected_error):
        validate_config_pair(**pair, image_root=ir, checkpoint=cp, manifest=mf)


# --- Test 11: Environment independence -------------------------------------


def test_env_vars_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIOHUB_OUTPUT_MOTION_RELINK", "1")
    monkeypatch.setenv("BIOHUB_OUTPUT_STEAL_TWIN_REWIRE", "1")
    monkeypatch.setenv("BIOHUB_EXPERIMENT_TAG", "wrong_tag")
    monkeypatch.setenv("BIOHUB_DEEPCENTER_CHECKPOINT", "/wrong/checkpoint.pt")
    monkeypatch.setenv("BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT", "/wrong/default_checkpoint.pt")
    monkeypatch.setenv("BIOHUB_DEEPCENTER_MANIFEST", "/wrong/manifest.json")
    monkeypatch.setenv("BIOHUB_DEEPCENTER_MANIFEST_DEFAULT", "/wrong/default_manifest.json")

    ir, cp, mf = _make_paths()
    bl = build_arm_config("baseline", ir, cp, mf)
    cand = build_arm_config("candidate", ir, cp, mf)

    for arm in ARM_ORDER:
        cfg = build_arm_config(arm, ir, cp, mf)
        extra = {"BIOHUB_OUTPUT_MOTION_RELINK": "0"} if arm == "candidate" else {}
        _all_fields_match(cfg, _ref_config(ir, cp, mf, extra=extra))

    # validate_config_pair should still succeed despite env pollution
    assert validate_config_pair(bl, cand, image_root=ir, checkpoint=cp, manifest=mf) is None


# --- Test 12: Pure inputs, no filesystem access ----------------------------


def test_no_filesystem_access() -> None:
    """Synthetic Paths are sufficient; no real files are opened."""
    ir, cp, mf = _make_paths()
    bl = build_arm_config("baseline", ir, cp, mf)
    cand = build_arm_config("candidate", ir, cp, mf)
    assert isinstance(bl, PostprocConfig)
    assert isinstance(cand, PostprocConfig)
    validate_config_pair(bl, cand, image_root=ir, checkpoint=cp, manifest=mf)


# --- Unit02b: independent literal splits and gate oracles -------------------

_EXPECTED12 = tuple("""
44b6_12dfb391 44b6_267148e4 44b6_2a2eff9f 44b6_341df25f 44b6_587a1e22 44b6_5f15d135
6bba_062c8d37 6bba_07e24132 6bba_085bf656 6bba_09961292 6bba_0e7c0d07 6bba_12665c0e
""".split())
_EXPECTED24 = tuple("""
44b6_706092f0 44b6_74d0c52e 44b6_7a302da0 44b6_996155de 44b6_9be80b04 44b6_a21120c2
44b6_aaf8b0ea 44b6_c50204e0 44b6_c8e2a523 44b6_d2f34f90 44b6_d5e7d891 44b6_d754aa59
6bba_1d0d8384 6bba_207c6aaf 6bba_20852818 6bba_2312ac41 6bba_268e1230 6bba_2819ca14
6bba_32db13fc 6bba_337b1b3a 6bba_3abfe10a 6bba_3c5691b6 6bba_3db54e20 6bba_3fda6b25
""".split())
_SPLITS = {"eval12": _EXPECTED12, "eval24": _EXPECTED24, "eval36": _EXPECTED12 + _EXPECTED24}
_EXPECTED_GATES = {
    "eval12": [
        ("paired_mean", .005), ("paired_median", 0), ("paired_worst", -.002),
        ("aggregate_adj_edge", -.002), ("lineage_44b6_score", 0), ("lineage_6bba_score", 0),
    ],
    "eval24": [
        ("paired_mean", .003), ("paired_median", 0), ("paired_worst", -.002),
        ("aggregate_adj_edge", -.002), ("lineage_44b6_score", 0), ("lineage_6bba_score", 0),
    ],
    "eval36": [
        ("aggregate_adj_edge", 0), ("aggregate_score", 0), ("aggregate_division_jaccard", 0),
        ("paired_median", 0), ("paired_worst", -.002), ("lineage_44b6_score", 0), ("lineage_6bba_score", 0),
    ],
}
_GATE_CASES = [(stage, name, threshold) for stage, gates in _EXPECTED_GATES.items() for name, threshold in gates]


def _payload(stage: str) -> dict:
    return {
        "schema_version": "biohub.e26_screen.gate_input.v1",
        "stage": stage,
        "per_video": [{"dataset": video, "combined_score_delta": .01} for video in _SPLITS[stage]],
        "aggregate_deltas": {
            group: {
                "score": .01,
                "adj_edge_jaccard": .01,
                "division_jaccard": .01 if stage == "eval36" and group == stage else None,
            }
            for group in (stage, "44b6", "6bba")
        },
    }


def _set_deltas(payload: dict, values: list) -> None:
    for row, value in zip(payload["per_video"], values, strict=True):
        row["combined_score_delta"] = value


def test_gate_schema_and_literal_video_order() -> None:
    assert GATE_INPUT_SCHEMA == "biohub.e26_screen.gate_input.v1"
    assert GATE_RESULT_SCHEMA == "biohub.e26_screen.gate_result.v1"
    assert type(EVAL12) is type(EVAL24) is type(EVAL36) is tuple
    assert EVAL12 == _EXPECTED12
    assert EVAL24 == _EXPECTED24
    assert EVAL36 == _EXPECTED12 + _EXPECTED24
    assert (len(EVAL12), len(EVAL24), len(EVAL36)) == (12, 24, 36)
    assert len(set(EVAL36)) == 36
    assert set(EVAL12).isdisjoint(EVAL24)


@pytest.mark.parametrize(
    "values,expected",
    [
        ([3], {"n": 1, "mean": 3, "median": 3, "worst": 3}),
        ([3, 1, 2], {"n": 3, "mean": 2, "median": 2, "worst": 1}),
        ((4, 1, 3, 2), {"n": 4, "mean": 2.5, "median": 2.5, "worst": 1}),
        ([1e16, 1, -1e16], {"n": 3, "mean": 1 / 3, "median": 1, "worst": -1e16}),
        ([Fraction(1, 4), Fraction(3, 4)], {"n": 2, "mean": .5, "median": .5, "worst": .25}),
        (range(3), {"n": 3, "mean": 1, "median": 1, "worst": 0}),
    ],
)
def test_paired_statistics_exact(values: object, expected: dict) -> None:
    before = list(values)
    result = paired_statistics(values)
    assert result == expected
    assert type(result["n"]) is int
    assert list(values) == before


@pytest.mark.parametrize("values", [None, 1, True, "123", b"123", bytearray(b"123"), {}, {1, 2}, iter([1]), [], ()])
def test_paired_statistics_rejects_nonsequence_or_empty(values: object) -> None:
    with pytest.raises(E26Error):
        paired_statistics(values)


_INVALID_NUMBERS = [True, False, None, "0.01", 1j, [], {}, math.nan, math.inf, -math.inf, 10**400]


@pytest.mark.parametrize("bad", _INVALID_NUMBERS)
def test_paired_statistics_rejects_any_invalid_observation(bad: object) -> None:
    with pytest.raises(E26Error):
        paired_statistics([.01, bad, .01])


@pytest.mark.parametrize("values", [[1e308, 1e308], [1e308, 1e308, -1e308], [-1e308, 1e308, 1e308, 1e308]])
def test_paired_statistics_arithmetic_overflow(values: list) -> None:
    with pytest.raises(E26Error, match="arithmetic failed"):
        paired_statistics(values)


@pytest.mark.parametrize("stage", _SPLITS)
def test_example_success_has_exact_result_schema_and_no_authority(stage: str) -> None:
    payload = _payload(stage)
    before = deepcopy(payload)
    result = evaluate_gate(stage, payload)
    assert payload == before
    assert set(result) == {
        "schema_version", "candidate_id", "stage", "paired_statistics", "gates", "first_failure",
        "status", "submission_authorized",
    }
    assert result["schema_version"] == "biohub.e26_screen.gate_result.v1"
    assert result["candidate_id"] == "e23_motion_relink_off_v1"
    assert result["stage"] == stage
    assert result["paired_statistics"] == {
        "n": len(_SPLITS[stage]), "mean": math.fsum([.01] * len(_SPLITS[stage])) / len(_SPLITS[stage]),
        "median": .01, "worst": .01,
    }
    assert [(g["name"], g["threshold"]) for g in result["gates"]] == _EXPECTED_GATES[stage]
    for gate in result["gates"]:
        assert set(gate) == {"name", "value", "threshold", "passed"}
        assert gate["passed"] is True
    assert result["first_failure"] is None
    expected_status = "SCREEN_PASS_REQUIRES_CONFIRMATION" if stage == "eval36" else f"SCREEN_{stage.upper()}_PASS"
    assert result["status"] == expected_status
    assert result["submission_authorized"] is False


@pytest.mark.parametrize("stage", ["", "EVAL12", "eval13", None, True, 12, [], {}])
def test_invalid_gate_stage(stage: object) -> None:
    with pytest.raises(E26Error):
        evaluate_gate(stage, _payload("eval12"))


@pytest.mark.parametrize("payload", [None, [], "{}", 1, True])
def test_invalid_gate_payload_type(payload: object) -> None:
    with pytest.raises(E26Error):
        evaluate_gate("eval12", payload)


@pytest.mark.parametrize("field", ["schema_version", "stage"])
@pytest.mark.parametrize("bad", [None, True, 12, [], {}, "", "biohub.e25_screen.gate_input.v1", "eval24"])
def test_invalid_payload_identity(field: str, bad: object) -> None:
    payload = _payload("eval12")
    payload[field] = bad
    with pytest.raises(E26Error):
        evaluate_gate("eval12", payload)


_KEY_PATHS = [(), ("per_video", 0), ("aggregate_deltas",)] + [
    ("aggregate_deltas", group) for group in ("eval12", "44b6", "6bba")
]


@pytest.mark.parametrize("path", _KEY_PATHS)
def test_exact_keys_at_every_payload_level(path: tuple) -> None:
    payload = _payload("eval12")
    target = payload
    for key in path:
        target = target[key]
    for key in list(target):
        value = target.pop(key)
        with pytest.raises(E26Error):
            evaluate_gate("eval12", payload)
        target[key] = value
    target["unexpected"] = .99
    with pytest.raises(E26Error):
        evaluate_gate("eval12", payload)


@pytest.mark.parametrize("path", _KEY_PATHS[1:])
@pytest.mark.parametrize("bad", [None, [], "{}", 1, True])
def test_invalid_nested_mapping_types(path: tuple, bad: object) -> None:
    payload = _payload("eval12")
    parent = payload
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = bad
    with pytest.raises(E26Error):
        evaluate_gate("eval12", payload)


@pytest.mark.parametrize("stage", _SPLITS)
@pytest.mark.parametrize(
    "change", ["empty", "removed", "extra", "reorder", "duplicate", "wrong", "wrong-stage", "tuple"]
)
def test_per_video_requires_complete_literal_order(stage: str, change: str) -> None:
    payload = _payload(stage)
    rows = payload["per_video"]
    if change == "empty":
        rows.clear()
    elif change == "removed":
        rows.pop()
    elif change == "extra":
        rows.append(deepcopy(rows[0]))
    elif change == "reorder":
        rows[0], rows[1] = rows[1], rows[0]
    elif change == "duplicate":
        rows[1] = deepcopy(rows[0])
    elif change == "wrong":
        rows[-1]["dataset"] = "44b6_unknown"
    elif change == "wrong-stage":
        other = "eval12" if stage == "eval24" else "eval24"
        payload["per_video"] = _payload(other)["per_video"]
    else:
        payload["per_video"] = tuple(rows)
    with pytest.raises(E26Error):
        evaluate_gate(stage, payload)


@pytest.mark.parametrize("bad", [None, {}, "rows", 1, True])
def test_invalid_per_video_type(bad: object) -> None:
    payload = _payload("eval12")
    payload["per_video"] = bad
    with pytest.raises(E26Error):
        evaluate_gate("eval12", payload)


@pytest.mark.parametrize("bad", [None, [], {}, 1, True, ""])
def test_invalid_dataset_type(bad: object) -> None:
    payload = _payload("eval12")
    payload["per_video"][0]["dataset"] = bad
    with pytest.raises(E26Error):
        evaluate_gate("eval12", payload)


@pytest.mark.parametrize("field", ["schema_version", "stage", "dataset"])
def test_identity_cannot_be_a_non_json_object_with_string_equality(field: str) -> None:
    class EqualToAnything:
        def __eq__(self, other):
            return True

    payload = _payload("eval12")
    target = payload["per_video"][0] if field == "dataset" else payload
    target[field] = EqualToAnything()
    with pytest.raises(E26Error):
        evaluate_gate("eval12", payload)


@pytest.mark.parametrize("bad", _INVALID_NUMBERS + [Fraction(1, 4)])
def test_gate_delta_must_be_finite_json_number(bad: object) -> None:
    payload = _payload("eval12")
    payload["per_video"][-1]["combined_score_delta"] = bad
    with pytest.raises(E26Error):
        evaluate_gate("eval12", payload)


@pytest.mark.parametrize("stage", _SPLITS)
@pytest.mark.parametrize("group", ["stage", "44b6", "6bba"])
@pytest.mark.parametrize("metric", ["score", "adj_edge_jaccard", "division_jaccard"])
@pytest.mark.parametrize("bad", [True, "0.01", math.nan, math.inf, -math.inf, Fraction(1, 4)])
def test_every_aggregate_including_diagnostics_requires_finite_json_number(
    stage: str, group: str, metric: str, bad: object
) -> None:
    payload = _payload(stage)
    payload["aggregate_deltas"][stage if group == "stage" else group][metric] = bad
    with pytest.raises(E26Error):
        evaluate_gate(stage, payload)


@pytest.mark.parametrize("stage", _SPLITS)
@pytest.mark.parametrize("group", ["stage", "44b6", "6bba"])
@pytest.mark.parametrize("metric", ["score", "adj_edge_jaccard", "division_jaccard"])
def test_nullable_division_diagnostics_only(stage: str, group: str, metric: str) -> None:
    payload = _payload(stage)
    payload["aggregate_deltas"][stage if group == "stage" else group][metric] = None
    nullable = metric == "division_jaccard" and not (stage == "eval36" and group == "stage")
    if nullable:
        result = evaluate_gate(stage, payload)
        assert result["first_failure"] is None
        assert result["submission_authorized"] is False
    else:
        with pytest.raises(E26Error):
            evaluate_gate(stage, payload)


@pytest.mark.parametrize("stage,name,threshold", _GATE_CASES)
@pytest.mark.parametrize("below", [False, True])
def test_comparator_inclusive_exact_boundary(stage: str, name: str, threshold: float, below: bool) -> None:
    value = math.nextafter(threshold, -math.inf) if below else threshold
    assert e26_screen._gate_record(name, value, threshold) == {
        "name": name, "value": value, "threshold": threshold, "passed": not below,
    }


@pytest.mark.parametrize("stage,name,threshold", _GATE_CASES)
@pytest.mark.parametrize("below", [False, True])
def test_each_gate_boundary_through_recomputed_payload(
    stage: str, name: str, threshold: float, below: bool
) -> None:
    payload = _payload(stage)
    value = math.nextafter(threshold, -math.inf) if below else threshold
    n = len(payload["per_video"])
    expected_value = value
    if name == "paired_mean":
        _set_deltas(payload, [value] * n)
        if stage == "eval24":
            # No representable fsum total produces exact .003 after division by 24.
            expected_value = .0029999999999999996 if below else .0030000000000000005
    elif name == "paired_median":
        _set_deltas(payload, [value] * (n // 2 + 1) + [.03] * (n // 2 - 1))
    elif name == "paired_worst":
        payload["per_video"][0]["combined_score_delta"] = value
    else:
        target = {
            "aggregate_adj_edge": (stage, "adj_edge_jaccard"),
            "aggregate_score": (stage, "score"),
            "aggregate_division_jaccard": (stage, "division_jaccard"),
            "lineage_44b6_score": ("44b6", "score"),
            "lineage_6bba_score": ("6bba", "score"),
        }[name]
        payload["aggregate_deltas"][target[0]][target[1]] = value
    result = evaluate_gate(stage, payload)
    gate = next(g for g in result["gates"] if g["name"] == name)
    assert gate["value"] == expected_value
    assert gate["threshold"] == threshold
    assert gate["passed"] is (not below)
    if name.startswith("paired_"):
        assert result["paired_statistics"][name.removeprefix("paired_")] == expected_value
    assert all(g["passed"] for g in result["gates"] if g["name"] != name)
    assert result["first_failure"] == (name if below else None)
    assert result["submission_authorized"] is False
    if below:
        assert result["status"] == f"SCREEN_REJECT_{stage.upper()}"


@pytest.mark.parametrize("stage", _SPLITS)
def test_all_failures_reported_with_first_failure_in_fixed_order(stage: str) -> None:
    payload = _payload(stage)
    _set_deltas(payload, [-1] * len(payload["per_video"]))
    for group in payload["aggregate_deltas"].values():
        group.update(score=-1, adj_edge_jaccard=-1, division_jaccard=-1)
    result = evaluate_gate(stage, payload)
    assert [g["name"] for g in result["gates"]] == [name for name, _ in _EXPECTED_GATES[stage]]
    assert all(g["passed"] is False for g in result["gates"])
    assert result["first_failure"] == _EXPECTED_GATES[stage][0][0]
    assert result["status"] == f"SCREEN_REJECT_{stage.upper()}"
    assert result["submission_authorized"] is False


def test_invalid_last_diagnostic_errors_before_any_comparison(monkeypatch: pytest.MonkeyPatch) -> None:
    def must_not_compare(*args, **kwargs):
        pytest.fail("malformed input reached gate comparison")

    monkeypatch.setattr(e26_screen, "_gate_record", must_not_compare)
    payload = _payload("eval12")
    _set_deltas(payload, [-1] * 12)
    payload["aggregate_deltas"]["6bba"]["division_jaccard"] = math.nan
    with pytest.raises(E26Error):
        evaluate_gate("eval12", payload)


def test_gate_statistics_overflow_is_error_not_scientific_reject() -> None:
    payload = _payload("eval12")
    _set_deltas(payload, [1e308] * 12)
    with pytest.raises(E26Error):
        evaluate_gate("eval12", payload)


@pytest.mark.parametrize("field", ["mean", "paired_statistics", "division_tp", "submission_authorized"])
def test_caller_summaries_or_gate_shortcuts_not_accepted(field: str) -> None:
    payload = _payload("eval12")
    payload[field] = 1
    with pytest.raises(E26Error):
        evaluate_gate("eval12", payload)


def test_eval36_no_mean_or_division_tp_gate_but_strict_adjusted_edge() -> None:
    payload = _payload("eval36")
    _set_deltas(payload, [-.002] * 17 + [0] * 19)
    payload["aggregate_deltas"]["eval36"].update(score=0, adj_edge_jaccard=0, division_jaccard=0)
    result = evaluate_gate("eval36", payload)
    assert result["paired_statistics"]["mean"] < 0
    assert [g["name"] for g in result["gates"]] == [name for name, _ in _EXPECTED_GATES["eval36"]]
    assert result["status"] == "SCREEN_PASS_REQUIRES_CONFIRMATION"
    assert result["submission_authorized"] is False
    payload["aggregate_deltas"]["eval36"]["adj_edge_jaccard"] = -.001
    result = evaluate_gate("eval36", payload)
    assert result["first_failure"] == "aggregate_adj_edge"
    assert result["status"] == "SCREEN_REJECT_EVAL36"
    assert result["submission_authorized"] is False


# --- Unit03: strict generated CSV checks before existing graph validation ---

_CSV_COLUMNS = ["id", "dataset", "row_type", "node_id", "t", "z", "y", "x", "source_id", "target_id"]
_CSV_DATASETS = ("44b6_12dfb391", "6bba_062c8d37")
_CSV_SHAPES = {name: (3, 4, 8, 8) for name in _CSV_DATASETS}


def _csv_fixture_rows() -> list[dict]:
    first, second = _CSV_DATASETS
    rows = [
        [first, "node", 0, 0, 1, 1, 1, -1, -1],
        [first, "node", 1, 1, 1, 1, 1, -1, -1],
        [first, "node", 2, 1, 1, 1, 1, -1, -1],
        [first, "node", 3, 2, 1, 1, 1, -1, -1],
        [first, "edge", -1, -1, -1, -1, -1, 0, 1],
        [first, "edge", -1, -1, -1, -1, -1, 0, 2],
        [first, "edge", -1, -1, -1, -1, -1, 1, 3],
        [second, "node", 0, 0, 0, 0, 0, -1, -1],
    ]
    return [dict(zip(_CSV_COLUMNS, [i, *row], strict=True)) for i, row in enumerate(rows)]


def _write_csv_fixture(path: Path, rows: list[dict], *, columns: list[str] = _CSV_COLUMNS) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def test_generated_csv_counts_order_zero_edge_and_existing_validator(tmp_path: Path, monkeypatch) -> None:
    from biohub import validate
    from biohub.public_postproc.csv_out import CSV_COLUMNS

    assert _CSV_COLUMNS == CSV_COLUMNS
    path = tmp_path / "submission.csv"
    _write_csv_fixture(path, _csv_fixture_rows())
    before = path.read_bytes()
    calls = []
    original = validate.validate_submission

    def checked(frame, shapes):
        calls.append((frame.height, shapes))
        return original(frame, shapes)

    def no_discovery(*args, **kwargs):
        pytest.fail("must not discover image or GT files")

    monkeypatch.setattr(validate, "validate_submission", checked)
    monkeypatch.setattr(validate, "test_shapes", no_discovery)
    monkeypatch.setattr(validate, "open_volume", no_discovery)
    result = validate_generated_csv(path, datasets=_CSV_DATASETS, shapes=_CSV_SHAPES)
    assert calls == [(8, _CSV_SHAPES)]
    assert result == {
        "datasets": list(_CSV_DATASETS), "total_rows": 8, "total_nodes": 5, "total_edges": 3,
        "per_dataset": [
            {"dataset": _CSV_DATASETS[0], "nodes": 4, "edges": 3, "forks": 1},
            {"dataset": _CSV_DATASETS[1], "nodes": 1, "edges": 0, "forks": 0},
        ],
    }
    assert path.read_bytes() == before


@pytest.mark.parametrize("field", ["id", "node_id", "t", "z", "y", "x", "source_id", "target_id"])
@pytest.mark.parametrize("bad", ["1.0", "nan", "inf", "True", "", " 1", str(2**63), str(-(2**63) - 1)])
def test_generated_csv_rejects_noninteger_missing_or_overflow(tmp_path: Path, field: str, bad: str) -> None:
    rows = _csv_fixture_rows()
    rows[0][field] = bad
    path = tmp_path / "bad.csv"
    _write_csv_fixture(path, rows)
    with pytest.raises(E26Error):
        validate_generated_csv(path, datasets=_CSV_DATASETS, shapes=_CSV_SHAPES)


@pytest.mark.parametrize(
    "change",
    ["id-offset", "id-duplicate", "duplicate-node", "duplicate-edge", "node-after-edge", "row-type", "dataset-empty",
     "dataset-wrong", "dataset-order", "dataset-interleaved", "dataset-missing", "all-empty", "node-negative",
     "node-source-sentinel", "node-target-sentinel", "edge-node-sentinel", "edge-t-sentinel", "edge-z-sentinel",
     "edge-y-sentinel", "edge-x-sentinel", "edge-negative", "dangling", "cross-video", "nonconsecutive",
     "indegree", "outdegree", "no-nodes"],
)
def test_generated_csv_rejects_contract_corruption(tmp_path: Path, change: str) -> None:
    rows = _csv_fixture_rows()
    if change == "id-offset":
        rows[0]["id"] = 1
    elif change == "id-duplicate":
        rows[1]["id"] = 0
    elif change == "duplicate-node":
        rows[1]["node_id"] = 0
    elif change == "duplicate-edge":
        rows[5]["target_id"] = 1
    elif change == "node-after-edge":
        rows[3], rows[4] = rows[4], rows[3]
    elif change == "row-type":
        rows[0]["row_type"] = "unknown"
    elif change == "dataset-empty":
        rows[0]["dataset"] = ""
    elif change == "dataset-wrong":
        rows[0]["dataset"] = "unselected"
    elif change == "dataset-order":
        rows = rows[-1:] + rows[:-1]
    elif change == "dataset-interleaved":
        rows.insert(1, rows.pop())
    elif change == "dataset-missing":
        rows.pop()
    elif change == "all-empty":
        rows = []
    elif change == "node-negative":
        rows[0]["node_id"] = -1
    elif change in ("node-source-sentinel", "node-target-sentinel"):
        rows[0]["source_id" if "source" in change else "target_id"] = 0
    elif change.startswith("edge-") and change.endswith("-sentinel"):
        field = change.split("-")[1]
        rows[4]["node_id" if field == "node" else field] = 0
    elif change == "edge-negative":
        rows[4]["source_id"] = -1
    elif change == "dangling":
        rows[4]["target_id"] = 99
    elif change == "cross-video":
        rows[-1]["node_id"] = 99
        rows[4]["target_id"] = 99
    elif change == "nonconsecutive":
        rows[4]["target_id"] = 3
    elif change == "indegree":
        rows[2]["t"] = 0
        rows[5].update(source_id=2, target_id=1)
    elif change == "outdegree":
        rows[3]["t"] = 1
        rows[6]["source_id"] = 0
    elif change == "no-nodes":
        rows = rows[4:]
    else:
        pytest.fail(f"unhandled mutation {change}")
    if not change.startswith("id-"):
        for index, row in enumerate(rows):
            row["id"] = index
    path = tmp_path / "bad.csv"
    _write_csv_fixture(path, rows)
    before = path.read_bytes()
    with pytest.raises(E26Error):
        validate_generated_csv(path, datasets=_CSV_DATASETS, shapes=_CSV_SHAPES)
    assert path.read_bytes() == before


@pytest.mark.parametrize("axis,upper", [("t", 3), ("z", 4), ("y", 8), ("x", 8)])
@pytest.mark.parametrize("side", ["lower", "upper"])
def test_generated_csv_coordinate_bounds(tmp_path: Path, axis: str, upper: int, side: str) -> None:
    rows = _csv_fixture_rows()
    rows[0][axis] = -1 if side == "lower" else upper
    path = tmp_path / "bad.csv"
    _write_csv_fixture(path, rows)
    with pytest.raises(E26Error, match="structural validation"):
        validate_generated_csv(path, datasets=_CSV_DATASETS, shapes=_CSV_SHAPES)


@pytest.mark.parametrize(
    "change", ["empty", "header-missing", "header-duplicate", "header-order", "short", "long", "quote"]
)
def test_generated_csv_malformed_encoding_and_shape(tmp_path: Path, change: str) -> None:
    path = tmp_path / "bad.csv"
    rows = _csv_fixture_rows()
    if change == "empty":
        path.write_text("")
    elif change == "header-missing":
        path.write_text(",".join(_CSV_COLUMNS[:-1]) + "\n")
    elif change == "header-duplicate":
        path.write_text(",".join(_CSV_COLUMNS + ["id"]) + "\n")
    elif change == "header-order":
        _write_csv_fixture(path, rows, columns=list(reversed(_CSV_COLUMNS)))
    else:
        first_row = [str(rows[0][field]) for field in _CSV_COLUMNS]
        if change == "short":
            first_row.pop()
        elif change == "long":
            first_row.append("extra")
        else:
            first_row = ['"unterminated']
        path.write_text(",".join(_CSV_COLUMNS) + "\n" + ",".join(first_row) + "\n")
    with pytest.raises(E26Error):
        validate_generated_csv(path, datasets=_CSV_DATASETS, shapes=_CSV_SHAPES)


@pytest.mark.parametrize("bad", [None, [], (), ("one", "one"), (None,), ("",), (1,)])
def test_generated_csv_invalid_dataset_selection(tmp_path: Path, bad: object) -> None:
    with pytest.raises(E26Error):
        validate_generated_csv(tmp_path / "absent.csv", datasets=bad, shapes=_CSV_SHAPES)


@pytest.mark.parametrize("bad", [None, [], {}, {"unselected": (3, 4, 8, 8)}])
def test_generated_csv_shapes_require_exact_selection(tmp_path: Path, bad: object) -> None:
    with pytest.raises(E26Error):
        validate_generated_csv(tmp_path / "absent.csv", datasets=_CSV_DATASETS, shapes=bad)


@pytest.mark.parametrize("bad", [None, [], (3, 4, 8), (3, 4, 8, 8, 1), (True, 4, 8, 8), (3, 0, 8, 8), (3, 4, 8, 8.)])
def test_generated_csv_shapes_are_positive_integer_tzyx(tmp_path: Path, bad: object) -> None:
    shapes = {**_CSV_SHAPES, _CSV_DATASETS[0]: bad}
    with pytest.raises(E26Error):
        validate_generated_csv(tmp_path / "absent.csv", datasets=_CSV_DATASETS, shapes=shapes)


def test_generated_csv_missing_directory_symlink_or_bad_encoding(tmp_path: Path) -> None:
    path = tmp_path / "absent.csv"
    for invalid in (None, str(path), path, tmp_path):
        with pytest.raises(E26Error):
            validate_generated_csv(invalid, datasets=_CSV_DATASETS, shapes=_CSV_SHAPES)
    path.write_bytes(b"\xff\xff\xfe")
    with pytest.raises(E26Error):
        validate_generated_csv(path, datasets=_CSV_DATASETS, shapes=_CSV_SHAPES)
    alias = tmp_path / "alias.csv"
    alias.symlink_to(path)
    with pytest.raises(E26Error, match="non-symlink"):
        validate_generated_csv(alias, datasets=_CSV_DATASETS, shapes=_CSV_SHAPES)


def test_generated_csv_change_during_validation_is_rejected(tmp_path: Path, monkeypatch) -> None:
    from biohub import validate

    path = tmp_path / "submission.csv"
    _write_csv_fixture(path, _csv_fixture_rows())
    original = validate.validate_submission

    def changed(frame, shapes):
        report = original(frame, shapes)
        with path.open("a") as handle:
            handle.write("\n")
        return report

    monkeypatch.setattr(validate, "validate_submission", changed)
    with pytest.raises(E26Error, match="changed during validation"):
        validate_generated_csv(path, datasets=_CSV_DATASETS, shapes=_CSV_SHAPES)


# --- Unit03: raw core telemetry, never pandas-normalized -------------------


def _telemetry_fixture(arm: str) -> tuple[list[dict], dict]:
    from biohub.public_postproc.pipeline import new_stats

    videos = (
        ("44b6_0113de3b", "44b6_0b24845f", "6bba_05b6850b", "6bba_05db0fb1")
        if arm == "public4_parity" else _SPLITS["eval36"]
    )
    rows = []
    for video in videos:
        row = dict(new_stats())
        row.update(
            dataset=video, raw_nodes=5, nodes=4, raw_edges=4, edges=3, division_like_sources=1,
            edge_to_node_ratio=.75, gap_added_nodes_frac=0., motion_relink_fallback_raw=int(arm != "candidate"),
        )
        rows.append(row)
    return rows, {
        "datasets": list(videos), "total_rows": 7 * len(videos), "total_nodes": 4 * len(videos),
        "total_edges": 3 * len(videos),
        "per_dataset": [{"dataset": video, "nodes": 4, "edges": 3, "forks": 1} for video in videos],
    }


def test_raw_counter_schema_matches_exact_current_core() -> None:
    from biohub.public_postproc.pipeline import new_stats

    assert e26_screen._RAW_COUNTER_KEYS == frozenset(new_stats())
    assert len(e26_screen._RAW_COUNTER_KEYS) == 126
    assert len(e26_screen._MOTION_COUNTER_KEYS) == 7
    assert frozenset(key for key in new_stats() if key.startswith("motion_relink_")) == frozenset(
        e26_screen._MOTION_COUNTER_KEYS
    )
    assert PUBLIC4 == ("44b6_0113de3b", "44b6_0b24845f", "6bba_05b6850b", "6bba_05db0fb1")
    assert set(PUBLIC4).isdisjoint(EVAL36)


@pytest.mark.parametrize("arm", ARM_ORDER)
@pytest.mark.parametrize("optional_present", [False, True])
def test_raw_statistics_preserve_signed_sum_and_optional_absence(arm: str, optional_present: bool) -> None:
    rows, report = _telemetry_fixture(arm)
    rows[0]["gap_density_step_delta_milli_sum"] = -37
    if optional_present:
        rows[0]["gap_close_effective_max_gap"] = 1
    before_rows, before_report = deepcopy(rows), deepcopy(report)
    result = validate_raw_statistics(rows, arm=arm, csv_report=report)
    assert rows == before_rows and report == before_report
    assert [row["dataset"] for row in result] == report["datasets"]
    for original, output in zip(rows, result, strict=True):
        assert {key: output[key] for key in original} == original
        assert output is not original
        present = "gap_close_effective_max_gap" in original
        assert output["gap_close_effective_max_gap"] == (1 if present else None)
        assert output["gap_close_effective_max_gap_absence_reason"] == (None if present else "not_emitted_by_core")
    assert result[0]["gap_density_step_delta_milli_sum"] == -37


@pytest.mark.parametrize("arm", ["baseline", "public4_parity"])
@pytest.mark.parametrize("case", ["replacement", "fallback", "large-skip"])
def test_enabled_motion_allows_replacement_fallback_and_large_frame_skip(arm: str, case: str) -> None:
    rows, report = _telemetry_fixture(arm)
    if case == "replacement":
        rows[0].update(motion_relink_edges=2, motion_relink_tight_edges=1, motion_relink_relaxed_edges=1,
                       motion_relink_frames=1, motion_relink_replaced_raw_edges=4, motion_relink_fallback_raw=0)
    elif case == "large-skip":
        rows[0]["motion_relink_skipped_large_frame"] = 1
    result = validate_raw_statistics(rows, arm=arm, csv_report=report)
    assert len(result) == len(rows)


@pytest.mark.parametrize("arm", ARM_ORDER)
def test_raw_statistics_allow_nodes_with_zero_final_edges(arm: str) -> None:
    rows, report = _telemetry_fixture(arm)
    rows[0].update(edges=0, division_like_sources=0, edge_to_node_ratio=0.)
    report["per_dataset"][0].update(edges=0, forks=0)
    report["total_edges"] -= 3
    report["total_rows"] -= 3
    assert validate_raw_statistics(rows, arm=arm, csv_report=report)[0]["edges"] == 0


def test_every_required_raw_key_missing_is_error() -> None:
    rows, report = _telemetry_fixture("candidate")
    for key in list(rows[0]):
        value = rows[0].pop(key)
        with pytest.raises(E26Error, match="keys"):
            validate_raw_statistics(rows, arm="candidate", csv_report=report)
        rows[0][key] = value
    rows[0]["unexpected"] = 0
    with pytest.raises(E26Error, match="keys"):
        validate_raw_statistics(rows, arm="candidate", csv_report=report)


@pytest.mark.parametrize("bad", [True, None, 1., "0", math.nan, math.inf, -1])
def test_all_raw_count_types_and_nonnegative_lower_bounds(bad: object) -> None:
    rows, report = _telemetry_fixture("candidate")
    keys = set(rows[0]) - {"dataset", "edge_to_node_ratio", "gap_added_nodes_frac"}
    for key in keys:
        if key == "gap_density_step_delta_milli_sum" and bad == -1:
            continue
        previous = rows[0][key]
        rows[0][key] = bad
        with pytest.raises(E26Error):
            validate_raw_statistics(rows, arm="candidate", csv_report=report)
        rows[0][key] = previous


@pytest.mark.parametrize("key", ["edge_to_node_ratio", "gap_added_nodes_frac"])
@pytest.mark.parametrize("bad", [True, None, "0", math.nan, math.inf, -math.inf, -.01])
def test_raw_ratios_require_finite_nonnegative_numbers(key: str, bad: object) -> None:
    rows, report = _telemetry_fixture("candidate")
    rows[0][key] = bad
    with pytest.raises(E26Error):
        validate_raw_statistics(rows, arm="candidate", csv_report=report)


@pytest.mark.parametrize("bad", [None, True, 1., "1", -1, math.nan])
def test_present_optional_gap_counter_must_be_valid(bad: object) -> None:
    rows, report = _telemetry_fixture("candidate")
    rows[0]["gap_close_effective_max_gap"] = bad
    with pytest.raises(E26Error):
        validate_raw_statistics(rows, arm="candidate", csv_report=report)


@pytest.mark.parametrize("key", ["nodes", "edges", "division_like_sources"])
def test_raw_counts_must_match_reparsed_csv(key: str) -> None:
    rows, report = _telemetry_fixture("candidate")
    rows[0][key] += 1
    with pytest.raises(E26Error, match="differs from reparsed CSV"):
        validate_raw_statistics(rows, arm="candidate", csv_report=report)


@pytest.mark.parametrize("key", e26_screen._MOTION_COUNTER_KEYS)
def test_candidate_every_motion_counter_must_be_zero(key: str) -> None:
    rows, report = _telemetry_fixture("candidate")
    rows[0][key] = 1
    with pytest.raises(E26Error):
        validate_raw_statistics(rows, arm="candidate", csv_report=report)


@pytest.mark.parametrize(
    "changes",
    [
        {"motion_relink_edges": 1},
        {"motion_relink_fallback_raw": 2},
        {"motion_relink_skipped_large_frame": 2},
        {"motion_relink_fallback_raw": 0},
        {"motion_relink_edges": 1, "motion_relink_tight_edges": 1},
        {"motion_relink_replaced_raw_edges": 1},
        {"motion_relink_edges": 1, "motion_relink_tight_edges": 1, "motion_relink_fallback_raw": 0,
         "motion_relink_skipped_large_frame": 1},
        {"motion_relink_edges": 1, "motion_relink_tight_edges": 1, "motion_relink_fallback_raw": 0,
         "motion_relink_replaced_raw_edges": 5},
    ],
)
def test_motion_telemetry_internal_consistency(changes: dict) -> None:
    rows, report = _telemetry_fixture("baseline")
    rows[0].update(changes)
    with pytest.raises(E26Error):
        validate_raw_statistics(rows, arm="baseline", csv_report=report)


@pytest.mark.parametrize("bad", [None, [], {}, "", "dry_run", "other"])
def test_raw_statistics_unknown_arm(bad: object) -> None:
    rows, report = _telemetry_fixture("baseline")
    with pytest.raises(E26Error):
        validate_raw_statistics(rows, arm=bad, csv_report=report)


@pytest.mark.parametrize("change", ["type", "empty", "missing", "extra", "duplicate", "reordered", "wrong", "row-type"])
def test_raw_statistics_requires_literal_ordered_complete_rows(change: str) -> None:
    rows, report = _telemetry_fixture("baseline")
    if change == "type":
        rows = tuple(rows)
    elif change == "empty":
        rows = []
    elif change == "missing":
        rows.pop()
    elif change == "extra":
        rows.append(deepcopy(rows[0]))
    elif change == "duplicate":
        rows[1] = deepcopy(rows[0])
    elif change == "reordered":
        rows[0], rows[1] = rows[1], rows[0]
    elif change == "wrong":
        rows[0]["dataset"] = "other"
    else:
        rows[0] = None
    with pytest.raises(E26Error):
        validate_raw_statistics(rows, arm="baseline", csv_report=report)


@pytest.mark.parametrize(
    "change",
    ["schema", "datasets", "missing-video", "wrong-video", "count-bool", "zero-nodes", "total-rows",
     "total-nodes", "total-edges", "extra-field", "missing-field"],
)
def test_raw_statistics_does_not_trust_malformed_csv_counts(change: str) -> None:
    rows, report = _telemetry_fixture("baseline")
    if change == "schema":
        report = None
    elif change == "datasets":
        report["datasets"].reverse()
    elif change == "missing-video":
        report["per_dataset"].pop()
    elif change == "wrong-video":
        report["per_dataset"][0]["dataset"] = "other"
    elif change == "count-bool":
        report["per_dataset"][0]["nodes"] = True
    elif change == "zero-nodes":
        report["per_dataset"][0]["nodes"] = 0
    elif change.startswith("total-"):
        report[change.replace("-", "_")] += 1
    elif change == "extra-field":
        report["per_dataset"][0]["unexpected"] = 0
    else:
        del report["per_dataset"][0]["forks"]
    with pytest.raises(E26Error):
        validate_raw_statistics(rows, arm="baseline", csv_report=report)


def test_e26_import_defers_numerical_modules_and_excludes_scoring() -> None:
    code = """
import sys
import biohub.e26_screen
for prefix in ('numpy', 'polars', 'pandas', 'torch', 'biohub.evaluate', 'tracking_cellmot',
               'biohub.kaggle_screen', 'biohub.st_r3'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
assert not any(name.startswith('biohub.st_r3_') for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=generation_environment(),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# --- Opaque inventories and exclusive, hash-bound JSON artifacts -----------


def _tiny_inventory_tree(tmp_path: Path) -> Path:
    root = tmp_path / "inputs"
    root.mkdir()
    (root / "nested").mkdir()
    (root / "empty").mkdir()
    (root / "a.bin").write_bytes(b"opaque\x00graph")
    (root / "nested" / "b.bin").write_bytes(b"image bytes")
    return root


def test_full_opaque_tree_inventory_and_historical_digest(tmp_path: Path, monkeypatch) -> None:
    root = _tiny_inventory_tree(tmp_path)

    def no_semantic_read(*args, **kwargs):
        pytest.fail("opaque inventory must not decode JSON/GT/image semantics")

    monkeypatch.setattr(e26_screen, "_decode_json", no_semantic_read)
    binding = inventory_path(root)
    assert binding["schema_version"] == "biohub.e26_screen.inventory.v1"
    assert binding["selected_path"] == binding["resolved_path"] == str(root)
    assert binding["aliases"] == [] and binding["kind"] == "tree"
    assert binding["file_count"] == 2
    assert binding["total_bytes"] == len(b"opaque\x00graph") + len(b"image bytes")
    expected_lines = "".join(
        f"{hashlib.sha256(data).hexdigest()}  ./{name}\n"
        for name, data in [("a.bin", b"opaque\x00graph"), ("nested/b.bin", b"image bytes")]
    )
    assert binding["content_sha256"] == hashlib.sha256(expected_lines.encode()).hexdigest()
    assert [row["relative_path"] for row in binding["files"]] == ["a.bin", "nested/b.bin"]
    assert [row["relative_path"] for row in binding["directories"]] == [".", "empty", "nested"]
    assert binding["directories"][0]["children"] == ["a.bin", "empty", "nested"]
    assert verify_inventory(binding) is None
    assert inventory_path(root) == binding


def test_single_file_and_empty_directory_inventory(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    binding = inventory_path(empty)
    assert binding["files"] == [] and binding["file_count"] == binding["total_bytes"] == 0
    assert binding["content_sha256"] == hashlib.sha256(b"").hexdigest()
    assert verify_inventory(binding) is None
    path = empty / "data.bin"
    path.write_bytes(b"abc")
    binding = inventory_path(path)
    assert binding["kind"] == "file" and binding["directories"] == []
    assert binding["files"][0]["relative_path"] == "."
    assert binding["content_sha256"] == hashlib.sha256(b"abc").hexdigest()
    assert verify_inventory(binding) is None


@pytest.mark.parametrize("where", ["root", "ancestor", "internal-file", "internal-dir", "chain"])
def test_only_explicit_input_aliases_are_followed_and_bound(tmp_path: Path, where: str) -> None:
    root = _tiny_inventory_tree(tmp_path)
    alias = tmp_path / "alias"
    aliases = {}
    selected = root
    if where in ("root", "ancestor", "chain"):
        alias.symlink_to(root, target_is_directory=True)
        aliases[str(alias)] = str(root)
        selected = alias / "nested" if where == "ancestor" else alias
        if where == "chain":
            chain = tmp_path / "chain"
            chain.symlink_to(alias)
            aliases[str(chain)] = str(root)
            selected = chain
    else:
        alias = root / "link"
        target = root / "a.bin" if where == "internal-file" else root / "nested"
        alias.symlink_to(target.name)
        aliases[str(alias)] = str(target)
    with pytest.raises(E26Error, match="unregistered"):
        inventory_path(selected)
    binding = inventory_path(selected, allowed_aliases=aliases)
    assert verify_inventory(binding) is None
    all_links = binding["aliases"] + [
        link for row in binding["files"] + binding["directories"] for link in row["aliases"]
    ]
    assert set(aliases) == {link["path"] for link in all_links}
    assert all(link["resolved_path"] == aliases[link["path"]] for link in all_links)


def test_inventory_rejects_wrong_alias_target_even_if_bytes_match(tmp_path: Path) -> None:
    one, two = tmp_path / "one.bin", tmp_path / "two.bin"
    one.write_bytes(b"same")
    two.write_bytes(b"same")
    link = tmp_path / "link"
    link.symlink_to(one)
    with pytest.raises(E26Error, match="unregistered"):
        inventory_path(link, allowed_aliases={str(link): str(two)})
    binding = inventory_path(link, allowed_aliases={str(link): str(one)})
    link.unlink()
    link.symlink_to(two)
    with pytest.raises(E26Error, match="unregistered"):
        verify_inventory(binding)


@pytest.mark.parametrize("kind", ["broken", "link-cycle", "directory-cycle", "fifo"])
def test_inventory_rejects_broken_cycle_and_nonregular_inputs(tmp_path: Path, kind: str) -> None:
    selected = tmp_path / "input"
    aliases = {}
    if kind == "broken":
        selected.symlink_to(tmp_path / "absent")
    elif kind == "link-cycle":
        other = tmp_path / "other"
        selected.symlink_to(other)
        other.symlink_to(selected)
    elif kind == "directory-cycle":
        selected.mkdir()
        link = selected / "cycle"
        link.symlink_to(selected)
        aliases[str(link)] = str(selected)
    else:
        os.mkfifo(selected)
    with pytest.raises(E26Error):
        inventory_path(selected, allowed_aliases=aliases)


@pytest.mark.parametrize("change", ["bytes", "add-file", "remove-file", "add-empty-dir", "rename", "mode"])
def test_inventory_detects_input_drift(tmp_path: Path, change: str) -> None:
    root = _tiny_inventory_tree(tmp_path)
    binding = inventory_path(root)
    if change == "bytes":
        (root / "a.bin").write_bytes(b"changed")
    elif change == "add-file":
        (root / "new.bin").write_bytes(b"extra")
    elif change == "remove-file":
        (root / "a.bin").unlink()
    elif change == "add-empty-dir":
        (root / "newdir").mkdir()
    elif change == "rename":
        (root / "a.bin").rename(root / "renamed.bin")
    else:
        (root / "a.bin").chmod(0o600)
    with pytest.raises(E26Error):
        verify_inventory(binding)


def test_stable_file_rejects_midread_content_change(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "data.bin"
    path.write_bytes(b"before")
    original = os.read
    changed = False

    def mutate(fd, size):
        nonlocal changed
        value = original(fd, size)
        if not changed:
            path.write_bytes(b"after!")
            changed = True
        return value

    monkeypatch.setattr(e26_screen.os, "read", mutate)
    with pytest.raises(E26Error, match="changed"):
        inventory_path(path)


def test_full_schema_errors_precede_inventory_io(tmp_path: Path, monkeypatch) -> None:
    binding = inventory_path(_tiny_inventory_tree(tmp_path))

    def must_not_follow(*args, **kwargs):
        pytest.fail("malformed inventory reached filesystem traversal")

    monkeypatch.setattr(e26_screen, "inventory_path", must_not_follow)
    targets = [binding, binding["files"][0], binding["files"][0]["stat"], binding["directories"][0]]
    for target in targets:
        for key in list(target):
            value = target.pop(key)
            with pytest.raises(E26Error):
                verify_inventory(binding)
            target[key] = value
        target["unexpected"] = 1
        with pytest.raises(E26Error):
            verify_inventory(binding)
        del target["unexpected"]


@pytest.mark.parametrize(
    "change", ["old-schema", "count", "bytes", "summary-sha", "content-sha", "file-sha", "file-type", "root",
               "relative-traversal", "relative-alias", "reorder", "duplicate", "missing-record", "missing-directory",
               "directory-membership", "extra-child", "nonfinite", "empty-files"]
)
def test_inventory_schema_counts_membership_and_digests_fail_closed(tmp_path: Path, change: str) -> None:
    binding = inventory_path(_tiny_inventory_tree(tmp_path))
    if change == "old-schema":
        binding["schema_version"] = "biohub.e25.inventory.v1"
    elif change == "count":
        binding["file_count"] = True
    elif change == "bytes":
        binding["total_bytes"] += 1
    elif change == "summary-sha":
        binding["inventory_sha256"] = "0" * 64
    elif change == "content-sha":
        binding["content_sha256"] = "0" * 64
    elif change == "file-sha":
        binding["files"][0]["sha256"] = "BAD"
    elif change == "file-type":
        binding["files"][0]["stat"]["mode"] = stat.S_IFIFO
    elif change == "root":
        binding["resolved_path"] = str(tmp_path / "other")
    elif change == "relative-traversal":
        binding["files"][0]["relative_path"] = "../escaped"
    elif change == "relative-alias":
        binding["files"][0]["relative_path"] = "./a.bin"
    elif change == "reorder":
        binding["files"].reverse()
    elif change == "duplicate":
        binding["files"].append(deepcopy(binding["files"][0]))
    elif change == "missing-record":
        binding["files"].pop()
    elif change == "missing-directory":
        binding["directories"].pop()
    elif change == "directory-membership":
        binding["directories"][0]["children"].pop()
    elif change == "extra-child":
        binding["directories"][0]["children"].append("extra")
    elif change == "nonfinite":
        binding["files"][0]["stat"]["size"] = math.nan
    else:
        binding["files"] = []
    with pytest.raises(E26Error):
        verify_inventory(binding)


@pytest.mark.parametrize("bad", [None, "relative", Path("relative"), Path("/"), Path("//"), Path("/tmp/../escape")])
def test_inventory_rejects_implicit_or_unsafe_root(bad: object) -> None:
    with pytest.raises(E26Error):
        inventory_path(bad)


def test_json_exclusive_roundtrip_hash_mode_and_no_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "artifact.json"
    payload = {"schema_version": "test", "rows": [1, .1, True, None, "動画"]}
    receipt = write_json_exclusive(path, payload)
    data = path.read_bytes()
    assert receipt == {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert read_json_bound(path, receipt["sha256"]) == payload
    with pytest.raises(E26Error):
        write_json_exclusive(path, {"changed": True})
    assert path.read_bytes() == data


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, (1, 2), {1: "value"}, Fraction(1, 4), "\ud800"])
def test_json_invalid_payload_does_not_create_output(tmp_path: Path, bad: object) -> None:
    path = tmp_path / "bad.json"
    with pytest.raises(E26Error):
        write_json_exclusive(path, {"nested": [bad]})
    assert not path.exists()


@pytest.mark.parametrize("data", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":1e999}', b'{', b'\xff'])
def test_json_reparse_rejects_duplicate_nonfinite_or_malformed_bytes(tmp_path: Path, data: bytes) -> None:
    path = tmp_path / "bad.json"
    path.write_bytes(data)
    with pytest.raises(E26Error):
        read_json_bound(path, hashlib.sha256(data).hexdigest())


def test_json_hash_substitution_fails_before_deserialization(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "artifact.json"
    receipt = write_json_exclusive(path, {"original": 1})
    path.write_text('{"substituted":2}')

    def forbidden(*args, **kwargs):
        pytest.fail("substituted artifact was parsed")

    monkeypatch.setattr(e26_screen, "_decode_json", forbidden)
    with pytest.raises(E26Error, match="digest mismatch"):
        read_json_bound(path, receipt["sha256"])


def test_json_rejects_output_aliases(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(target)
    with pytest.raises(E26Error, match="aliases"):
        write_json_exclusive(alias / "out.json", {})
    path = target / "file.json"
    receipt = write_json_exclusive(path, {})
    file_alias = tmp_path / "file-link"
    file_alias.symlink_to(path)
    with pytest.raises(E26Error, match="aliases"):
        read_json_bound(file_alias, receipt["sha256"])
    assert not (target / "out.json").exists()


def test_json_fsync_failure_retains_partial_file(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "partial.json"

    def failure(fd):
        raise OSError("synthetic fsync failure")

    monkeypatch.setattr(e26_screen.os, "fsync", failure)
    with pytest.raises(E26Error):
        write_json_exclusive(path, {"unfinished": True})
    assert path.exists()
    assert json.loads(path.read_text()) == {"unfinished": True}


def _synthetic_budget() -> dict:
    # Test-only numbers: never a physical run allowance or production default.
    return {
        "schema_version": "biohub.e26_screen.budget.v1",
        "arm_wall_seconds": {"public4_parity": 1, "baseline": 2, "candidate": 2},
        "generation_wall_seconds": 6,
        "score_process_wall_seconds": 3,
        "score_stage_wall_seconds": {"eval12": 1, "eval24": 1, "eval36": 1},
        "ram": {
            "scope": "self_process", "units": "bytes", "limit_bytes": 1000,
            "measurement": "getrusage(RUSAGE_SELF).ru_maxrss",
            "enforcement": "dataset_boundaries_and_receipts_not_os_hard_limit",
        },
    }


def test_budget_has_no_default_and_requires_complete_honest_policy() -> None:
    budget = _synthetic_budget()
    before = deepcopy(budget)
    assert validate_budget(budget) is None
    assert budget == before
    for mapping in (budget, budget["arm_wall_seconds"], budget["score_stage_wall_seconds"], budget["ram"]):
        for key in list(mapping):
            value = mapping.pop(key)
            with pytest.raises(E26Error):
                validate_budget(budget)
            mapping[key] = value
        mapping["unexpected"] = 1
        with pytest.raises(E26Error):
            validate_budget(budget)
        del mapping["unexpected"]


@pytest.mark.parametrize("bad", [0, -1, True, None, "1", math.nan, math.inf, -math.inf])
def test_every_wall_budget_requires_finite_positive_number(bad: object) -> None:
    budget = _synthetic_budget()
    for mapping, keys in (
        (budget, ["generation_wall_seconds", "score_process_wall_seconds"]),
        (budget["arm_wall_seconds"], list(ARM_ORDER)),
        (budget["score_stage_wall_seconds"], list(_SPLITS)),
    ):
        for key in keys:
            value = mapping[key]
            mapping[key] = bad
            with pytest.raises(E26Error):
                validate_budget(budget)
            mapping[key] = value


@pytest.mark.parametrize("bad", [0, -1, True, None, 1., "1000", math.inf])
def test_ram_budget_requires_positive_integer_bytes(bad: object) -> None:
    budget = _synthetic_budget()
    budget["ram"]["limit_bytes"] = bad
    with pytest.raises(E26Error):
        validate_budget(budget)


@pytest.mark.parametrize("key,bad", [
    ("scope", "process_tree"), ("units", "MiB"), ("enforcement", "OS_hard_limit"), ("measurement", "estimated"),
])
def test_ram_policy_cannot_overstate_measurement_or_enforcement(key: str, bad: str) -> None:
    budget = _synthetic_budget()
    budget["ram"][key] = bad
    with pytest.raises(E26Error):
        validate_budget(budget)


def test_generation_environment_excludes_ambient_credentials_and_overrides(monkeypatch) -> None:
    before = generation_environment()
    for key in ("KAGGLE_API_TOKEN", "DASHSCOPE_API_KEY", "HTTP_PROXY", "BIOHUB_OUTPUT_MOTION_RELINK", "PYTHONPATH"):
        monkeypatch.setenv(key, "synthetic-should-not-propagate")
    assert generation_environment() == before
    expected_keys = {
        "PYTHONHASHSEED", "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE", "PYTHONCOERCECLOCALE", "PYTHONUTF8",
        "CUDA_VISIBLE_DEVICES", "LC_ALL", "LANG", "TZ", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "PATH", "PYTHONPATH",
    }
    if sys.platform == "darwin":
        expected_keys.add("__CF_USER_TEXT_ENCODING")
        assert before["__CF_USER_TEXT_ENCODING"] == f"0x{os.getuid():X}:0x0:0x0"
    assert set(before) == expected_keys
    assert before["CUDA_VISIBLE_DEVICES"] == ""
    assert before["PYTHONHASHSEED"] == "0"
    assert before["LC_ALL"] == before["LANG"] == "C"
    assert before["TZ"] == "UTC"
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS"):
        assert before[key] == "1"


def test_fresh_inference_controls_are_real_cpu_seed_and_thread_settings() -> None:
    code = """
import json, random
from biohub.e26_screen import initialize_inference_runtime
receipt = initialize_inference_runtime()
import numpy as np
import torch
assert random.random() == 0.8444218515250481
assert np.random.random() == 0.5488135039273248
assert torch.initial_seed() == 0
assert torch.get_num_threads() == torch.get_num_interop_threads() == 1
assert not torch.cuda.is_available()
print(json.dumps(receipt))
"""
    result = subprocess.run(
        [sys.executable, "-c", code], env=generation_environment(),
        capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["environment"] == generation_environment()
    assert receipt["required_device"] == "cpu"
    assert all(receipt[key] == 0 for key in ("python_seed", "numpy_seed", "torch_seed", "torch_initial_seed"))


def test_inference_controls_reject_environment_and_preloaded_modules(monkeypatch) -> None:
    monkeypatch.setenv("BIOHUB_OUTPUT_MOTION_RELINK", "1")
    with pytest.raises(E26Error, match="environment"):
        initialize_inference_runtime()
    monkeypatch.setattr(e26_screen.os, "environ", generation_environment())
    monkeypatch.setitem(sys.modules, "numpy", object())
    with pytest.raises(E26Error, match="loaded before"):
        initialize_inference_runtime()


@pytest.mark.parametrize("platform,multiplier", [("darwin", 1), ("linux", 1024)])
def test_peak_rss_platform_units_are_not_confused(monkeypatch, platform: str, multiplier: int) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(e26_screen.sys, "platform", platform)
    monkeypatch.setattr(e26_screen.resource, "getrusage", lambda who: SimpleNamespace(ru_maxrss=123))
    assert self_peak_rss_bytes() == 123 * multiplier


@pytest.mark.parametrize("bad", [-1, 1.5, True, None, math.nan, math.inf])
def test_peak_rss_rejects_invalid_readings(monkeypatch, bad: object) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(e26_screen.resource, "getrusage", lambda who: SimpleNamespace(ru_maxrss=bad))
    with pytest.raises(E26Error):
        self_peak_rss_bytes()


@pytest.mark.parametrize("run_id", [None, True, "", "..", "../run", "/tmp/run", "a/b", "a b", "a\n", "a" * 97, "動画"])
def test_run_id_rejection_precedes_any_output_creation(tmp_path: Path, monkeypatch, run_id: object) -> None:
    monkeypatch.setattr(e26_screen, "_PROJECT_ROOT", tmp_path)
    with pytest.raises(E26Error):
        create_preregistration_directory(run_id)
    assert list(tmp_path.iterdir()) == []


def test_registration_namespace_is_separate_exclusive_and_retains_existing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(e26_screen, "_PROJECT_ROOT", tmp_path)
    path = create_preregistration_directory("run-01")
    assert path == tmp_path / "outputs/local/e26_screen_preregistrations/run-01"
    assert not (tmp_path / "outputs/local/e26_screen/run-01").exists()
    marker = path / "partial.json"
    marker.write_text("preserved")
    with pytest.raises(E26Error):
        create_preregistration_directory("run-01")
    assert marker.read_text() == "preserved"
    generated = tmp_path / "outputs/local/e26_screen/run-02"
    generated.mkdir(parents=True)
    with pytest.raises(E26Error, match="existing generation"):
        create_preregistration_directory("run-02")
    assert not (path.parent / "run-02").exists()


def test_registration_rejects_namespace_alias(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(e26_screen, "_PROJECT_ROOT", tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    (tmp_path / "outputs").symlink_to(other)
    with pytest.raises(E26Error, match="aliases"):
        create_preregistration_directory("run-01")
    assert list(other.iterdir()) == []


def test_registration_rejects_alias_to_missing_generation_namespace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(e26_screen, "_PROJECT_ROOT", tmp_path)
    parent = tmp_path / "outputs/local"
    parent.mkdir(parents=True)
    (parent / "e26_screen").symlink_to(tmp_path / "absent")
    with pytest.raises(E26Error, match="aliases"):
        create_preregistration_directory("run-01")
    assert not (parent / "e26_screen_preregistrations").exists()


def test_json_parent_alias_cycle_is_e26_error(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.symlink_to(second)
    second.symlink_to(first)
    with pytest.raises(E26Error, match="alias cycles"):
        write_json_exclusive(first / "artifact.json", {})


def test_alias_schema_is_checked_completely_before_io(tmp_path: Path, monkeypatch) -> None:
    root = _tiny_inventory_tree(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(root)
    binding = inventory_path(link, allowed_aliases={str(link): str(root)})

    def forbidden(*args, **kwargs):
        pytest.fail("invalid alias record reached filesystem")

    monkeypatch.setattr(e26_screen, "inventory_path", forbidden)
    alias = binding["aliases"][0]
    for key in list(alias):
        value = alias.pop(key)
        with pytest.raises(E26Error):
            verify_inventory(binding)
        alias[key] = value
    alias["unexpected"] = 1
    with pytest.raises(E26Error):
        verify_inventory(binding)


@pytest.mark.parametrize("elapsed,peak", [(1., 1000), (math.nextafter(1., math.inf), 1000), (1., 1001), (-1., 1000)])
def test_runtime_budget_boundaries_are_inclusive_and_not_rounded(monkeypatch, elapsed: float, peak: int) -> None:
    monkeypatch.setattr(e26_screen.time, "monotonic", lambda: elapsed)
    monkeypatch.setattr(e26_screen, "self_peak_rss_bytes", lambda: peak)
    if elapsed == 1. and peak == 1000:
        assert check_runtime_budget(0., wall_limit_seconds=1., ram_limit_bytes=1000) == {
            "wall_seconds": 1., "peak_rss_bytes": 1000, "ram_scope": "self_process",
        }
    else:
        with pytest.raises(E26Error):
            check_runtime_budget(0., wall_limit_seconds=1., ram_limit_bytes=1000)


@pytest.mark.parametrize("bad", [None, True, math.nan, math.inf, "1"])
def test_runtime_budget_rejects_invalid_start_or_limits(monkeypatch, bad: object) -> None:
    with pytest.raises(E26Error):
        check_runtime_budget(bad, wall_limit_seconds=1., ram_limit_bytes=1000)
    with pytest.raises(E26Error):
        check_runtime_budget(0., wall_limit_seconds=bad, ram_limit_bytes=1000)
    with pytest.raises(E26Error):
        check_runtime_budget(0., wall_limit_seconds=1., ram_limit_bytes=bad)


def _tiny_image(path: Path) -> Path:
    (path / "0/c/0/0/0").mkdir(parents=True)
    (path / "0/c/0/0/0/0").write_bytes(b"opaque synthetic image bytes; never decoded")
    (path / "0/zarr.json").write_text(json.dumps({"shape": [1, 2, 3, 4], "data_type": "uint16"}))
    (path / "zarr.json").write_text(json.dumps({"attributes": {"multiscales": [{
        "axes": [{"name": name} for name in ("T", "Z", "Y", "X")],
        "datasets": [{"path": "0", "coordinateTransformations": [
            {"type": "scale", "scale": [1., 1.625, .40625, .40625]},
        ]}],
    }]}}))
    return path


@pytest.fixture
def registration_inputs(tmp_path: Path, monkeypatch):
    """Complete tiny canonical layout. No real GT/model/competition I/O."""
    monkeypatch.setattr(e26_screen, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(e26_screen, "_git_identity", lambda: {"head": "test-head", "status_porcelain": "test-dirty"})
    monkeypatch.setattr(e26_screen, "capture_dependency_binding", lambda: {"synthetic_dependency": "1"})
    for relative in (*e26_screen._SOURCE_PATHS, *e26_screen._SCIENTIFIC_PATHS):
        file = tmp_path / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(f"synthetic source/contract: {relative}\n")
    for stems, relative, split in (
        (PUBLIC4, e26_screen._RAW4_REL, "test"), (EVAL36, e26_screen._RAW36_REL, "train"),
    ):
        for stem in stems:
            raw = tmp_path / relative / f"{stem}.geff"
            raw.mkdir(parents=True)
            (raw / "opaque.bin").write_bytes(stem.encode())
            _tiny_image(tmp_path / "data" / split / f"{stem}.zarr")
            if split == "train":
                gt = tmp_path / "data/train" / f"{stem}.geff"
                gt.mkdir()
                (gt / "private.bin").write_bytes(b"PRIVATE_GT_SENTINEL: not JSON or a valid graph")
    weight_pins = {}
    for key, (relative, _) in e26_screen._WEIGHT_PINS.items():
        file = tmp_path / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(f"synthetic {key}".encode())
        weight_pins[key] = (relative, hashlib.sha256(file.read_bytes()).hexdigest())
    monkeypatch.setattr(e26_screen, "_WEIGHT_PINS", weight_pins)
    image_pins = tuple(inventory_path(tmp_path / "data/test" / f"{stem}.zarr")["content_sha256"] for stem in PUBLIC4)
    monkeypatch.setattr(e26_screen, "_PUBLIC4_IMAGE_PINS", image_pins)
    evidence = {}
    for key, relative, section in (
        ("raw4_manifest", e26_screen._RAW4_REL, "summary"),
        ("raw36_manifest", e26_screen._RAW36_REL, "raw_geff"),
    ):
        inv = inventory_path(tmp_path / relative)
        evidence[key] = {section: {"files": inv["file_count"], "bytes": inv["total_bytes"],
                                  "canonical_sha256sum_tree_sha256": inv["content_sha256"]}}
    files = []
    for stem in EVAL36:
        inv = inventory_path(tmp_path / "data/train" / f"{stem}.zarr")
        files.extend({"stem": stem, "path": f"{stem}.zarr/{row['relative_path']}",
                      "bytes": row["stat"]["size"], "sha256": row["sha256"]} for row in inv["files"])
    evidence["image36_inventory"] = {"roots": list(EVAL36), "files": sorted(files, key=lambda row: row["path"])}
    pins = {}
    for key in ("raw4_manifest", "raw36_manifest", "image36_inventory", "image_manifest", "image36_ready"):
        relative = e26_screen._ACQUISITION_PINS[key][0]
        file = tmp_path / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        if key == "image_manifest":
            file.write_text("name,size\ntrain/GT_NAMES_MUST_NOT_ENTER_CONTROLS.geff,1\n")
        else:
            if key == "image36_ready":
                evidence[key] = {"inventory": {"sha256": pins["image36_inventory"][1]},
                                 "manifest": {"sha256": pins["image_manifest"][1]}}
            file.write_text(json.dumps(evidence[key]))
        pins[key] = (relative, hashlib.sha256(file.read_bytes()).hexdigest())
    monkeypatch.setattr(e26_screen, "_ACQUISITION_PINS", pins)
    return tmp_path


def test_complete_registration_pair_is_ordered_and_generation_never_opens_gt(registration_inputs, monkeypatch):
    root = registration_inputs
    writes = []
    writer = e26_screen.write_json_exclusive

    def observe_write(path, value):
        writes.append(path.name)
        return writer(path, value)

    monkeypatch.setattr(e26_screen, "write_json_exclusive", observe_write)
    receipt = e26_screen.preregister_screen("synthetic-01", _synthetic_budget())
    assert writes == ["GT_BINDING.json", "PREREGISTRATION.json"]
    assert receipt["submission_authorized"] is False
    assert not (root / "outputs/local/e26_screen/synthetic-01").exists()
    public_path, private_path = Path(receipt["public"]["path"]), Path(receipt["private"]["path"])
    public = json.loads(public_path.read_text())
    private_bytes = private_path.read_bytes()
    private = json.loads(private_bytes)
    assert [row["dataset"] for row in private["videos"]] == list(EVAL36)
    assert all(row["gt_inventory"]["files"] for row in private["videos"])
    assert public["gt_binding_commitment"] == {
        "artifact": "GT_BINDING.json", "algorithm": "sha256", "sha256": receipt["private"]["sha256"],
        "bytes": len(private_bytes), "video_count": 36,
    }
    for stem in EVAL36:
        assert str(root / "data/train" / f"{stem}.geff") not in public_path.read_text()
    assert "PRIVATE_GT_SENTINEL" not in public_path.read_text()
    assert "GT_NAMES_MUST_NOT_ENTER_CONTROLS" not in public_path.read_text()
    decoder, inventory = e26_screen._decode_json, e26_screen.inventory_path

    def forbid_private_parse(data):
        assert data != private_bytes, "generation attempted to deserialize the private registration"
        return decoder(data)

    def forbid_gt_inventory(path, **kwargs):
        assert not (path.parent == root / "data/train" and path.suffix == ".geff")
        return inventory(path, **kwargs)

    monkeypatch.setattr(e26_screen, "_decode_json", forbid_private_parse)
    monkeypatch.setattr(e26_screen, "inventory_path", forbid_gt_inventory)
    assert e26_screen.verify_registration_pair(
        public_path, expected_public_sha256=receipt["public"]["sha256"],
        expected_private_sha256=receipt["private"]["sha256"],
    ) == public


@pytest.mark.parametrize("target", ["public", "private", "source", "scientific", "raw", "image", "weight"])
def test_registration_pair_rejects_post_registration_drift(registration_inputs, target):
    root = registration_inputs
    receipt = e26_screen.preregister_screen("drift", _synthetic_budget())
    paths = {
        "public": Path(receipt["public"]["path"]), "private": Path(receipt["private"]["path"]),
        "source": root / e26_screen._SOURCE_PATHS[0], "scientific": root / e26_screen._SCIENTIFIC_PATHS[0],
        "raw": root / e26_screen._RAW36_REL / f"{EVAL36[0]}.geff/opaque.bin",
        "image": root / "data/train" / f"{EVAL36[0]}.zarr/0/c/0/0/0/0",
        "weight": root / e26_screen._WEIGHT_PINS["checkpoint"][0],
    }
    paths[target].write_bytes(paths[target].read_bytes() + b"changed")
    with pytest.raises(E26Error):
        e26_screen.verify_registration_pair(
            Path(receipt["public"]["path"]), expected_public_sha256=receipt["public"]["sha256"],
            expected_private_sha256=receipt["private"]["sha256"],
        )


def test_half_registration_preserved_but_no_public_marker(registration_inputs, monkeypatch):
    writer = e26_screen.write_json_exclusive

    def fail_public(path, value):
        if path.name == "PREREGISTRATION.json":
            raise E26Error("synthetic publication failure")
        return writer(path, value)

    monkeypatch.setattr(e26_screen, "write_json_exclusive", fail_public)
    with pytest.raises(E26Error, match="publication failure"):
        e26_screen.preregister_screen("partial", _synthetic_budget())
    directory = registration_inputs / "outputs/local/e26_screen_preregistrations/partial"
    assert (directory / "GT_BINDING.json").exists()
    assert not (directory / "PREREGISTRATION.json").exists()
    with pytest.raises(E26Error, match="already exists"):
        e26_screen.preregister_screen("partial", _synthetic_budget())
    with pytest.raises(E26Error):
        e26_screen.verify_registration_pair(directory / "PREREGISTRATION.json",
                                            expected_public_sha256="a" * 64, expected_private_sha256="b" * 64)


def test_registration_requires_both_original_dispatch_digests(registration_inputs):
    receipt = e26_screen.preregister_screen("digests", _synthetic_budget())
    for pub, private in (("a" * 64, receipt["private"]["sha256"]), (receipt["public"]["sha256"], "b" * 64)):
        with pytest.raises(E26Error, match="digest|commitment"):
            e26_screen.verify_registration_pair(Path(receipt["public"]["path"]),
                                                expected_public_sha256=pub, expected_private_sha256=private)


def test_complete_binding_rejects_unknown_missing_nested_fields_before_io(registration_inputs, monkeypatch):
    binding = e26_screen.capture_generation_inputs()

    def forbidden(*args, **kwargs):
        pytest.fail("invalid schema followed an input path")

    monkeypatch.setattr(e26_screen, "_stable_file", forbidden)
    for fields in ((), ("eval36",), ("eval36", "videos", 0),
                   ("eval36", "videos", 0, "metadata"),
                   ("eval36", "videos", 0, "metadata", "array_metadata"),
                   ("eval36", "videos", 0, "metadata", "root_metadata"),
                   ("eval36", "raw_inventory"), ("acquisition_evidence",)):
        for mutation in ("extra", "missing"):
            altered = deepcopy(binding)
            target = altered
            for key in fields:
                target = target[key]
            if mutation == "extra":
                target["extra"] = True
            else:
                target.pop(next(iter(target)))
            with pytest.raises(E26Error):
                e26_screen.validate_generation_input_binding(altered)


@pytest.mark.parametrize("mutation", ["order", "config", "image_path", "acquisition_pin", "metadata", "raw_membership"])
def test_generation_binding_rejects_wrong_contract(registration_inputs, mutation):
    binding = e26_screen.capture_generation_inputs()
    if mutation == "order":
        binding["eval36"]["videos"].reverse()
    elif mutation == "config":
        binding["configs"]["candidate"]["OUTPUT_MOTION_RELINK"] = True
    elif mutation == "image_path":
        binding["eval36"]["image_root"] = str(registration_inputs / "data/test")
    elif mutation == "acquisition_pin":
        binding["acquisition_evidence"]["raw36_manifest"]["content_sha256"] = "a" * 64
    elif mutation == "metadata":
        binding["eval36"]["videos"][0]["metadata"]["scale_zyx"][0] *= 2
    else:
        binding["eval36"]["raw_inventory"]["directories"][0]["children"].pop()
    with pytest.raises(E26Error):
        e26_screen.validate_generation_input_binding(binding)


@pytest.mark.parametrize("bad", [None, True, -1, 0, "1", math.nan, math.inf])
def test_explicit_image_metadata_rejects_bad_scale_and_shape(tmp_path, bad):
    path = _tiny_image(tmp_path / "tiny.zarr")
    root = json.loads((path / "zarr.json").read_text())
    root["attributes"]["multiscales"][0]["datasets"][0]["coordinateTransformations"][0]["scale"][1] = bad
    (path / "zarr.json").write_text(json.dumps(root))
    with pytest.raises(E26Error):
        e26_screen.bind_image_metadata(inventory_path(path))
    (path / "zarr.json").write_text(json.dumps({"attributes": {}}))
    with pytest.raises(E26Error, match="fallback"):
        e26_screen.bind_image_metadata(inventory_path(path))


def test_image_metadata_does_not_decode_chunks_and_accepts_ome_nesting(tmp_path):
    path = _tiny_image(tmp_path / "tiny.zarr")
    root = json.loads((path / "zarr.json").read_text())
    root["attributes"] = {"ome": root["attributes"]}
    (path / "zarr.json").write_text(json.dumps(root))
    result = e26_screen.bind_image_metadata(inventory_path(path))
    assert result["shape_tzyx"] == [1, 2, 3, 4]
    assert result["scale_zyx"] == [1.625, .40625, .40625]
    assert result["dtype"] == "uint16"
    (path / "0/zarr.json").write_text(json.dumps({"shape": [True, 2, 3, 4], "data_type": "uint16"}))
    with pytest.raises(E26Error, match="shape"):
        e26_screen.bind_image_metadata(inventory_path(path))


def test_source_closure_full_records_and_git_dependency_drift(registration_inputs, monkeypatch):
    code = e26_screen.capture_code_bindings()
    assert [row["selected_path"] for row in code["source_binding"]["files"]] == [
        str(registration_inputs / relative) for relative in e26_screen._SOURCE_PATHS]
    e26_screen.verify_code_bindings(**code)
    invalid = deepcopy(code)
    invalid["source_binding"]["files"].pop()
    with pytest.raises(E26Error, match="closure"):
        e26_screen.verify_code_bindings(**invalid)
    monkeypatch.setattr(e26_screen, "_git_identity", lambda: {"head": "changed"})
    with pytest.raises(E26Error, match="Git"):
        e26_screen.verify_code_bindings(**code)
    with pytest.raises(E26Error, match="dependency"):
        e26_screen.verify_dependency_binding({"synthetic_dependency": "other"})


def test_real_dependency_binding_includes_transitive_versions_without_numerical_imports():
    code = """
import sys
from biohub.e26_screen import capture_dependency_binding, verify_dependency_binding
b = capture_dependency_binding()
names = [r['name'] for r in b['installed_distributions']]
assert names == sorted(set(names))
assert set(b['required_distributions']) < set(names)
assert all(r['version'] for r in b['installed_distributions'])
verify_dependency_binding(b)
assert not {'numpy','torch','pandas','polars','biohub.evaluate'} & set(sys.modules)
print('dependency binding PASS')
"""
    result = subprocess.run([sys.executable, "-c", code], env=generation_environment(),
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "dependency binding PASS"


def test_cli_has_no_model_child_fixture_or_implicit_physical_run_entry():
    path = Path(__file__).resolve().parents[1] / "scripts/e26_screen.py"
    result = subprocess.run([sys.executable, str(path), "--help"], env=generation_environment(),
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0
    assert "verify-inputs" in result.stdout and "verify-registration" in result.stdout
    for option in ("--fake-child", "--fixture", "--skip-parity", "--skip-acquisition"):
        assert option not in result.stdout


def test_public_and_private_registrations_reject_incomplete_or_old_schemas(registration_inputs):
    receipt = e26_screen.preregister_screen("schemas", _synthetic_budget())
    public = json.loads(Path(receipt["public"]["path"]).read_text())
    private = json.loads(Path(receipt["private"]["path"]).read_text())
    mutations = (
        ("schema_version", "biohub.kaggle_screen.control.v1"), ("run_id", "other-run"),
        ("candidate_id", "e23_twin_only_v1"), ("submission_authorized", True), ("eval36_order", []),
    )
    for original in (public, private):
        for key, value in mutations:
            altered = deepcopy(original)
            altered[key] = value
            with pytest.raises(E26Error):
                if original is public:
                    e26_screen.validate_public_registration(altered, run_id="schemas")
                else:
                    e26_screen.validate_private_registration(
                        altered, run_id="schemas", generation_inputs=public["generation_input_binding"],
                    )
    for key in ("scientific_binding", "source_binding", "dependency_binding", "budget", "gt_binding_commitment"):
        altered = deepcopy(public)
        altered[key] = {}
        with pytest.raises(E26Error):
            e26_screen.validate_public_registration(altered, run_id="schemas")
    for key, value in (("video_count", True), ("bytes", 0), ("sha256", "bad"), ("gt_path", "/private.gt")):
        altered = deepcopy(public)
        altered["gt_binding_commitment"][key] = value
        with pytest.raises(E26Error):
            e26_screen.validate_public_registration(altered, run_id="schemas")
    for changed in ([], private["videos"][::-1]):
        altered = deepcopy(private)
        altered["videos"] = changed
        with pytest.raises(E26Error):
            e26_screen.validate_private_registration(
                altered, run_id="schemas", generation_inputs=public["generation_input_binding"],
            )


def test_private_gt_drift_is_not_read_by_generation_but_detectable_by_scoring(registration_inputs):
    receipt = e26_screen.preregister_screen("gt-drift", _synthetic_budget())
    private = json.loads(Path(receipt["private"]["path"]).read_text())
    gt = registration_inputs / "data/train" / f"{EVAL36[0]}.geff/private.bin"
    gt.write_bytes(b"changed private GT bytes")
    # Generation checks the original opaque JSON commitment, not its GT trees.
    e26_screen.verify_registration_pair(
        Path(receipt["public"]["path"]), expected_public_sha256=receipt["public"]["sha256"],
        expected_private_sha256=receipt["private"]["sha256"],
    )
    # The forthcoming scoring entry must perform this check before graph reads.
    with pytest.raises(E26Error, match="drift"):
        verify_inventory(private["videos"][0]["gt_inventory"])


def test_changed_acquisition_file_stops_before_any_image_tree_read(registration_inputs, monkeypatch):
    file = registration_inputs / e26_screen._ACQUISITION_PINS["raw36_manifest"][0]
    file.write_text("{}")
    inventory = e26_screen.inventory_path

    def no_images(path, **kwargs):
        assert path.suffix != ".zarr", "bad acquisition evidence reached image processing"
        return inventory(path, **kwargs)

    monkeypatch.setattr(e26_screen, "inventory_path", no_images)
    with pytest.raises(E26Error, match="pinned input"):
        e26_screen.capture_generation_inputs()


def test_private_artifact_cannot_be_passed_as_public_before_json_parsing(registration_inputs, monkeypatch):
    receipt = e26_screen.preregister_screen("private-as-public", _synthetic_budget())

    def forbidden(*args, **kwargs):
        pytest.fail("private JSON was opened via the public argument")

    monkeypatch.setattr(e26_screen, "read_json_bound", forbidden)
    with pytest.raises(E26Error, match="canonical public"):
        e26_screen.verify_registration_pair(
            Path(receipt["private"]["path"]), expected_public_sha256=receipt["private"]["sha256"],
            expected_private_sha256=receipt["private"]["sha256"],
        )


def test_declared_metadata_resolved_path_cannot_redirect_reads_to_private_file(tmp_path, monkeypatch):
    image = inventory_path(_tiny_image(tmp_path / "image.zarr"))
    foreign = tmp_path / "private.bin"
    foreign.write_bytes(b"PRIVATE_GT_MUST_NOT_BE_OPENED")
    row = next(row for row in image["files"] if row["relative_path"] == "0/zarr.json")
    row["resolved_path"] = str(foreign)
    image["inventory_sha256"] = hashlib.sha256(e26_screen._json_bytes(
        {key: value for key, value in image.items() if key != "inventory_sha256"},
    )).hexdigest()
    # A self-consistent declared inventory digest is not authority to follow its
    # resolved-path field. Resolve the selected image path first.
    reader = e26_screen._stable_file

    def forbid_foreign(path, **kwargs):
        assert path != foreign, "metadata followed an unproved resolved path"
        return reader(path, **kwargs)

    monkeypatch.setattr(e26_screen, "_stable_file", forbid_foreign)
    with pytest.raises(E26Error, match="resolved path"):
        e26_screen.bind_image_metadata(image)


def _expected_inference_receipt() -> dict:
    return {
        "schema_version": "biohub.e26_screen.inference_controls.v1", "environment": generation_environment(),
        "python_seed": 0, "numpy_seed": 0, "torch_seed": 0, "torch_initial_seed": 0,
        "torch_num_threads": 1, "torch_num_interop_threads": 1, "required_device": "cpu",
    }


def _synthetic_strict_receipt(inputs: dict) -> dict:
    configs = {"manifest": {"epochs": 1000, "base_channels": 1},
               "checkpoint": {"epochs": 50, "base_channels": 1}}
    return {
        "schema_version": "biohub.st_r3.deepcenter_receipt.v1",
        "registered": {"checkpoint_name": "best.pt", "manifest_name": "ARTIFACT_MANIFEST.json"},
        **{key: {"sha256": inputs[key]["files"][0]["sha256"], "open_count": 1,
                 **{phase: inputs[key]["files"][0]["stat"] for phase in ("pre", "post_hash", "post_read")}}
           for key in ("checkpoint", "manifest")},
        "chosen_artifact": "best.pt", "verified_epoch": 2, "verified_configs": configs,
        "known_config_discrepancy": {"field": "epochs", "manifest": 1000, "checkpoint": 50},
        "inference_relevant_config_equal": True, "device": "cpu", "dtype": "float32",
        "open_count": 2, "fallback_candidates": 0,
    }


@pytest.fixture
def synthetic_generation(registration_inputs, monkeypatch):
    """Real E26 registration/validation with fake core/model/process boundaries."""
    import torch

    from biohub.public_postproc import deepcenter, pipeline

    root = registration_inputs
    pins = dict(e26_screen._WEIGHT_PINS)
    manifest = root / pins["manifest"][0]
    manifest.write_text(json.dumps({"model": {"config": {"epochs": 1000, "base_channels": 1}}}))
    pins["manifest"] = (pins["manifest"][0], hashlib.sha256(manifest.read_bytes()).hexdigest())
    reference = root / pins["reference"][0]
    _write_csv_fixture(reference, [dict(zip(_CSV_COLUMNS, [i, stem, "node", 0, 0, 0, 0, 0, -1, -1], strict=True))
                                   for i, stem in enumerate(PUBLIC4)])
    pins["reference"] = (pins["reference"][0], hashlib.sha256(reference.read_bytes()).hexdigest())
    monkeypatch.setattr(e26_screen, "_WEIGHT_PINS", pins)
    monkeypatch.setattr(e26_screen, "initialize_inference_runtime", _expected_inference_receipt)
    monkeypatch.setattr(e26_screen, "self_peak_rss_bytes", lambda: 42)
    state = {"root": root, "launches": [], "core_calls": [], "strict_loads": [], "fault": None, "active": False}

    def strict_loader(cfg, checkpoint, manifest):
        state["strict_loads"].append(state["arm"])
        assert checkpoint == root / pins["checkpoint"][0] and manifest == root / pins["manifest"][0]
        inputs = state["control"]["generation_input_binding"]
        model = torch.nn.Linear(1, 1).eval()
        bundle = {"model": model, "cfg": SimpleNamespace(epochs=50, base_channels=1), "device": torch.device("cpu"),
                  "path": checkpoint, "torch": torch, "checkpoint_epoch": 2}
        state["bundle"] = bundle
        return bundle, _synthetic_strict_receipt(inputs)

    def core(paths, output, cfg, **kwargs):
        arm = state["arm"]
        state["core_calls"].append(arm)
        stems = PUBLIC4 if arm == ARM_ORDER[0] else EVAL36
        assert tuple(path.stem for path in paths) == stems
        assert kwargs["write_run_stats_output"] is False and kwargs["exclusive_output"] is True
        assert kwargs["deepcenter_loader"](cfg) is state["bundle"]
        with output.open("x", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_CSV_COLUMNS)
            writer.writeheader()
            for sequence, stem in enumerate(stems):
                kwargs["dataset_start_hook"](sequence, stem)
                node = {"node_id": 0, "t": 0, "z": 0., "y": float(state["fault"] == "parity"), "x": 0.}
                if state["fault"] == "corrected_nodes":
                    node["x"] = -.6 if arm == ARM_ORDER[0] else kwargs["node_serializer"].shapes[stem][3] + .1
                if state["fault"] == "invalid_node":
                    node["t"] = -1
                if state["fault"] == "serializer_skipped":
                    row = dict(zip(_CSV_COLUMNS, [sequence, stem, "node", 0, 0, 0, 0, 0, -1, -1], strict=True))
                else:
                    row = kwargs["node_serializer"](node, stem, sequence)
                if state["fault"] == "csv_bounds":
                    row["x"] = 999999
                writer.writerow(row)
                if arm == "baseline" and state["fault"] == "baseline_failure":
                    raise RuntimeError("synthetic mid-baseline failure")
                raw = dict(pipeline.new_stats())
                raw.update(dataset=stem, raw_nodes=1, nodes=1, edges=0, division_like_sources=0,
                           edge_to_node_ratio=0., gap_added_nodes_frac=0.,
                           motion_relink_fallback_raw=int(arm != "candidate"))
                if arm == "candidate" and state["fault"] == "bad_statistics":
                    raw["motion_relink_frames"] = 1
                if state["fault"] == "hook_order":
                    kwargs["dataset_finish_hook"](sequence, stem)
                kwargs["raw_stats_hook"](raw)
                handle.flush()
                os.fsync(handle.fileno())
                kwargs["dataset_finish_hook"](sequence, stem)
        if state["fault"] == "source_drift":
            (root / e26_screen._SOURCE_PATHS[0]).write_text("changed during generation")
        return {"datasets": list(stems), "total_nodes": len(stems), "total_edges": 0,
                "total_rows": len(stems), "run_stats": None}

    def launch(control_path, expected_sha256, timeout_seconds):
        assert not state["active"], "generation children overlap"
        state["active"] = True
        started = time.monotonic()
        control = read_json_bound(control_path, expected_sha256)
        state["control"], state["arm"] = control, control["arm"]
        state["launches"].append(control["arm"])
        stdout, stderr = control_path.parent / "stdout.log", control_path.parent / "stderr.log"
        try:
            e26_screen.run_generation_child(control_path, expected_sha256)
            returncode, error = 0, ""
        except Exception as exc:
            returncode, error = 2, str(exc)
        finally:
            state["active"] = False
        stdout.write_text(f"synthetic {control['arm']} stdout\n")
        stderr.write_text(error)
        finished = time.monotonic()
        return {
            "schema_version": "biohub.e26_screen.child_process.v1", "pid": os.getpid(), "returncode": returncode,
            "timed_out": False, "wall_seconds": finished - started, "timeout_seconds": timeout_seconds,
            "started_monotonic": started, "finished_monotonic": finished,
            "argv": [sys.executable, str(root / "scripts/e26_screen.py"), "_arm", "--control", str(control_path),
                     "--control-sha256", expected_sha256], "cwd": str(root), "environment": generation_environment(),
            "stdout": e26_screen._artifact_reference(stdout), "stderr": e26_screen._artifact_reference(stderr),
        }

    monkeypatch.setattr(deepcenter, "load_deepcenter_veto_detector_strict", strict_loader)
    monkeypatch.setattr(pipeline, "run_postproc_core", core)
    monkeypatch.setattr(e26_screen, "_launch_generation_child", launch)
    budget = _synthetic_budget()
    budget["arm_wall_seconds"] = dict.fromkeys(ARM_ORDER, 60)
    budget["generation_wall_seconds"] = 600
    budget["score_process_wall_seconds"] = 600
    budget["score_stage_wall_seconds"] = dict.fromkeys(("eval12", "eval24", "eval36"), 60)
    state["registration"] = e26_screen.preregister_screen("synthetic-generation", budget)
    return state


def _generate_synthetic(state):
    receipt = state["registration"]
    return e26_screen.generate_screen(Path(receipt["public"]["path"]),
                                     expected_public_sha256=receipt["public"]["sha256"],
                                     expected_private_sha256=receipt["private"]["sha256"])


def _verify_synthetic_seal(state, seal):
    return e26_screen.verify_generation_seal(
        Path(seal["path"]), expected_seal_sha256=seal["sha256"],
        expected_public_sha256=state["registration"]["public"]["sha256"],
        expected_private_sha256=state["registration"]["private"]["sha256"],
    )


def test_generation_end_to_end_serial_single_loader_and_gt_free_controls(synthetic_generation, monkeypatch):
    state = synthetic_generation
    root = state["root"]
    decoder = e26_screen._decode_json
    private_bytes = Path(state["registration"]["private"]["path"]).read_bytes()

    def no_private(data):
        assert data != private_bytes, "generation deserialized private GT registration"
        return decoder(data)

    monkeypatch.setattr(e26_screen, "_decode_json", no_private)
    imported_before = set(sys.modules)
    seal_ref = _generate_synthetic(state)
    verified = _verify_synthetic_seal(state, seal_ref)
    seal = verified["seal"]
    assert state["launches"] == state["core_calls"] == state["strict_loads"] == list(ARM_ORDER)
    assert seal["status"] == "GENERATION_COMPLETE_NOT_SCORED" and seal["submission_authorized"] is False
    assert seal["registrations"] == {key: state["registration"][key] for key in ("public", "private")}
    assert [row["arm"] for row in seal["arms"]] == list(ARM_ORDER)
    for row in seal["arms"]:
        control_text = Path(row["control"]["path"]).read_text()
        for forbidden in (
            "GT_BINDING.json", "gt_binding_commitment", "score_stage_wall_seconds", "PRIVATE_GT_SENTINEL",
        ):
            assert forbidden not in control_text
        for stem in EVAL36:
            assert str(root / "data/train" / f"{stem}.geff") not in control_text
        result = json.loads(Path(row["result"]["path"]).read_text())
        assert result["core_result"]["total_edges"] == 0
        assert len(json.loads(Path(result["artifacts"]["events"]["path"]).read_text())) == (
            12 if row["arm"] == ARM_ORDER[0] else 108)
    new_modules = set(sys.modules) - imported_before
    assert not any(name == "biohub.evaluate" or name.startswith(("biohub.st_r3", "biohub.kaggle_screen"))
                   for name in new_modules)
    run = Path(seal_ref["path"]).parent
    assert not (run / "GENERATION_FAILURE.json").exists()
    assert not (run / "scoring").exists()
    with pytest.raises(E26Error, match="already exists"):
        _generate_synthetic(state)
    assert state["launches"] == list(ARM_ORDER)


@pytest.mark.parametrize("fault,launched", [
    ("parity", ["public4_parity"]), ("baseline_failure", ["public4_parity", "baseline"]),
    ("bad_statistics", list(ARM_ORDER)), ("hook_order", ["public4_parity"]), ("source_drift", ["public4_parity"]),
])
def test_generation_failure_stops_sequence_and_preserves_original_bindings(synthetic_generation, fault, launched):
    state = synthetic_generation
    state["fault"] = fault
    with pytest.raises(E26Error):
        _generate_synthetic(state)
    assert state["launches"] == launched
    run = state["root"] / "outputs/local/e26_screen/synthetic-generation"
    assert not (run / "GENERATION_SEAL.json").exists()
    failure = json.loads((run / "GENERATION_FAILURE.json").read_text())
    assert failure["submission_authorized"] is False and failure["operation"] == launched[-1]
    assert failure["registrations"] == {key: state["registration"][key] for key in ("public", "private")}
    assert failure["present_unvalidated_artifacts"] and failure["missing_artifacts"]
    assert (run / "generation" / launched[-1] / "stdout.log").exists()
    if fault == "baseline_failure":
        assert (run / "generation/baseline/submission.csv").exists()
        assert not (run / "generation/baseline/ARM_RESULT.json").exists()


def test_incomplete_registration_prevents_run_creation_and_any_child(synthetic_generation):
    state = synthetic_generation
    Path(state["registration"]["public"]["path"]).unlink()
    with pytest.raises(E26Error):
        _generate_synthetic(state)
    assert state["launches"] == []
    assert not (state["root"] / "outputs/local/e26_screen").exists()


@pytest.mark.parametrize("fault,arm,events,stats", [
    ("csv_bounds", "public4_parity", 12, 4), ("baseline_failure", "baseline", 1, 0),
    ("serializer_skipped", "public4_parity", 12, 4), ("invalid_node", "public4_parity", 1, 0),
])
def test_generation_failure_retains_observed_telemetry_before_csv_validation(
    synthetic_generation, fault, arm, events, stats,
):
    state = synthetic_generation
    state["fault"] = fault
    with pytest.raises(E26Error):
        _generate_synthetic(state)
    directory = state["root"] / "outputs/local/e26_screen/synthetic-generation/generation" / arm
    assert len(json.loads((directory / "events.json").read_text())) == events
    assert len(json.loads((directory / "raw_stats.json").read_text())) == stats
    assert (directory / "output_bounds.json").exists()
    assert not (directory / "ARM_RESULT.json").exists()
    assert not (directory.parents[1] / "GENERATION_SEAL.json").exists()


def test_v1_registration_is_not_migrated_to_bounded_v2(synthetic_generation):
    state = synthetic_generation
    public = json.loads(Path(state["registration"]["public"]["path"]).read_text())
    public["schema_version"] = "biohub.e26_screen.preregistration.v1"
    with pytest.raises(E26Error, match="registration identity"):
        e26_screen.validate_public_registration(public, run_id=public["run_id"])


def test_all_three_generation_arms_apply_and_seal_complete_bounds_audit(synthetic_generation):
    state = synthetic_generation
    state["fault"] = "corrected_nodes"
    seal_ref = _generate_synthetic(state)
    seal = _verify_synthetic_seal(state, seal_ref)["seal"]
    for arm in seal["arms"]:
        result = json.loads(Path(arm["result"]["path"]).read_text())
        bounds = json.loads(Path(result["artifacts"]["output_bounds"]["path"]).read_text())
        assert len(bounds["corrections"]) == (4 if arm["arm"] == ARM_ORDER[0] else 36)
        expected_delta = 0 if arm["arm"] == ARM_ORDER[0] else -1
        assert all(row["legacy_csv_delta"] == {"x": expected_delta, "y": 0, "z": 0}
                   for row in bounds["corrections"])
        assert all(row["corrected_nodes"] == row["node_count"] == 1 for row in bounds["per_dataset"])


@pytest.mark.parametrize("field,value", [("schema_version", "old"), ("arm", "dry_run"),
                                         ("datasets", []), ("gt_inventory", {}), ("limits", {}), ("environment", {})])
def test_child_controls_reject_unknown_fields_schemas_or_routes_before_loading(synthetic_generation, field, value):
    state = synthetic_generation
    public = json.loads(Path(state["registration"]["public"]["path"]).read_text())
    child = e26_screen.derive_generation_child_control(public, "baseline")
    child[field] = value
    with pytest.raises(E26Error):
        e26_screen.validate_generation_child_control(child)
    assert state["strict_loads"] == []


@pytest.mark.parametrize("field,value", [("device", "cuda:0"), ("dtype", "float16"), ("verified_epoch", True),
                                         ("open_count", 3), ("fallback_candidates", 1), ("schema_version", "old")])
def test_strict_receipt_cannot_claim_wrong_model_runtime(synthetic_generation, field, value):
    public = json.loads(Path(synthetic_generation["registration"]["public"]["path"]).read_text())
    inputs = public["generation_input_binding"]
    receipt = _synthetic_strict_receipt(inputs)
    receipt[field] = value
    with pytest.raises(E26Error, match="receipt mismatch"):
        e26_screen._validate_deepcenter_receipt(receipt, inputs)


@pytest.mark.parametrize("field", ["csv", "raw_statistics", "normalized_statistics", "events", "config", "inference",
                                  "output_bounds"])
def test_generation_seal_rechecks_all_saved_artifacts(synthetic_generation, field):
    state = synthetic_generation
    seal_ref = _generate_synthetic(state)
    seal = json.loads(Path(seal_ref["path"]).read_text())
    result = json.loads(Path(seal["arms"][1]["result"]["path"]).read_text())
    path = Path(result["artifacts"][field]["path"])
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(E26Error):
        _verify_synthetic_seal(state, seal_ref)


def test_generation_seal_rejects_old_or_incomplete_arm_list(synthetic_generation):
    state = synthetic_generation
    seal_ref = _generate_synthetic(state)
    path = Path(seal_ref["path"])
    original = json.loads(path.read_text())
    for field, value in (("schema_version", "biohub.kaggle_screen.seal.v1"), ("arms", original["arms"][:2]),
                         ("arms", original["arms"][::-1]), ("submission_authorized", True)):
        changed = {**original, field: value}
        path.write_bytes(e26_screen._json_bytes(changed))
        with pytest.raises(E26Error):
            _verify_synthetic_seal(state, e26_screen._artifact_reference(path))


def test_actual_subprocess_transport_streams_logs_and_reaps_timeout(tmp_path, monkeypatch):
    # Real subprocess transport, but this script is only a tiny synthetic log/sleep
    # producer. No model/core fixture route exists in the production CLI.
    monkeypatch.setattr(e26_screen, "_PROJECT_ROOT", tmp_path)
    script = tmp_path / "scripts/e26_screen.py"
    script.parent.mkdir()
    script.write_text("import sys\nprint('synthetic stdout', flush=True)\nprint('synthetic stderr', file=sys.stderr)\n")
    first = tmp_path / "first"
    first.mkdir()
    receipt = e26_screen._launch_generation_child(first / "CHILD_CONTROL.json", "a" * 64, 10.)
    assert receipt["returncode"] == 0 and receipt["timed_out"] is False
    assert receipt["pid"] != os.getpid()
    assert (first / "stdout.log").read_text() == "synthetic stdout\n"
    assert (first / "stderr.log").read_text() == "synthetic stderr\n"
    script.write_text("import time\nprint('before timeout', flush=True)\ntime.sleep(10)\n")
    second = tmp_path / "second"
    second.mkdir()
    receipt = e26_screen._launch_generation_child(second / "CHILD_CONTROL.json", "b" * 64, .1)
    assert receipt["timed_out"] is True and receipt["returncode"] < 0
    assert (second / "stdout.log").exists() and (second / "stderr.log").exists()
    with pytest.raises(ProcessLookupError):
        os.kill(receipt["pid"], 0)


@pytest.mark.parametrize("fault", ["half", "training", "wrong_device", "wrong_epoch", "tuple"])
def test_actual_model_bundle_is_checked_not_only_receipt(synthetic_generation, monkeypatch, fault):
    import torch

    from biohub.public_postproc import deepcenter

    state = synthetic_generation
    public = json.loads(Path(state["registration"]["public"]["path"]).read_text())
    control = e26_screen.derive_generation_child_control(public, "baseline")
    inputs = control["generation_input_binding"]
    model = torch.nn.Linear(1, 1).eval()
    bundle = {"model": model, "device": torch.device("cpu"), "torch": torch,
              "path": Path(inputs["checkpoint"]["selected_path"]), "checkpoint_epoch": 2}
    if fault == "half":
        model.half()
    elif fault == "training":
        model.train()
    elif fault == "wrong_device":
        bundle["device"] = "cuda:0"
    elif fault == "wrong_epoch":
        bundle["checkpoint_epoch"] = True
    result = (bundle, _synthetic_strict_receipt(inputs)) if fault != "tuple" else bundle
    monkeypatch.setattr(deepcenter, "load_deepcenter_veto_detector_strict", lambda *args: result)
    with pytest.raises(E26Error):
        e26_screen._load_child_model(e26_screen._child_config(control), inputs)


def test_started_child_cannot_resume_or_reload_model(synthetic_generation):
    state = synthetic_generation
    _generate_synthetic(state)
    directory = state["root"] / "outputs/local/e26_screen/synthetic-generation/generation/public4_parity"
    control_ref = e26_screen._artifact_reference(directory / "CHILD_CONTROL.json")
    with pytest.raises(E26Error, match="exclusive"):
        e26_screen.run_generation_child(Path(control_ref["path"]), control_ref["sha256"])
    assert state["strict_loads"] == list(ARM_ORDER)


def test_runtime_limits_stop_before_candidate_without_a_success_seal(synthetic_generation, monkeypatch):
    state = synthetic_generation
    monkeypatch.setattr(e26_screen, "self_peak_rss_bytes", lambda: (
        1001 if state.get("arm") == "baseline" and state["active"] else 42))
    with pytest.raises(E26Error):
        _generate_synthetic(state)
    assert state["launches"] == ["public4_parity", "baseline"]
    assert state["strict_loads"] == ["public4_parity"]
    run = state["root"] / "outputs/local/e26_screen/synthetic-generation"
    assert (run / "GENERATION_FAILURE.json").exists() and not (run / "GENERATION_SEAL.json").exists()


def test_nonfinite_or_contradictory_runtime_receipts_fail_closed():
    limits = {"wall_seconds": 10., "ram_limit_bytes": 100}
    valid = {"wall_seconds": 2., "core_wall_seconds": 1., "peak_rss_bytes": 99, "ram_scope": "self_process"}
    e26_screen._validate_timing(valid, limits, core=True)
    for key, value in (("wall_seconds", math.nan), ("wall_seconds", -1), ("peak_rss_bytes", True),
                       ("peak_rss_bytes", 101), ("core_wall_seconds", math.inf), ("core_wall_seconds", 3.),
                       ("ram_scope", "process_tree")):
        with pytest.raises(E26Error):
            e26_screen._validate_timing({**valid, key: value}, limits, core=True)


def test_changed_original_registration_after_generation_invalidates_seal(synthetic_generation):
    state = synthetic_generation
    seal = _generate_synthetic(state)
    private = Path(state["registration"]["private"]["path"])
    private.write_bytes(private.read_bytes() + b" ")
    with pytest.raises(E26Error, match="commitment"):
        _verify_synthetic_seal(state, seal)


def test_supervisor_does_not_seal_overlapping_claimed_process_intervals(synthetic_generation, monkeypatch):
    state = synthetic_generation
    launch = e26_screen._launch_generation_child
    first_start = []

    def overlapping(*args):
        receipt = launch(*args)
        if not first_start:
            first_start.append(receipt["started_monotonic"])
        else:
            receipt["started_monotonic"] = first_start[0]
            receipt["wall_seconds"] = receipt["finished_monotonic"] - receipt["started_monotonic"]
        return receipt

    monkeypatch.setattr(e26_screen, "_launch_generation_child", overlapping)
    with pytest.raises(E26Error, match="overlap"):
        _generate_synthetic(state)
    run = state["root"] / "outputs/local/e26_screen/synthetic-generation"
    assert not (run / "GENERATION_SEAL.json").exists()
    assert json.loads((run / "GENERATION_FAILURE.json").read_text())["operation"] == "final_integrity"


_TEST_SCORE_STAGES = {"eval12": EVAL12, "eval24": EVAL24, "eval36": EVAL36}


def _synthetic_metric_row(name, adj=.8, *, division=True):
    # Fake score API boundary, not physical graph evidence. Official summarise
    # remains real and supplies singleton/group scores throughout these tests.
    return {"dataset": name, "edge_tp": 80, "edge_fp": 0, "edge_fn": 20,
            "division_tp": int(division), "division_fp": 0, "division_fn": 0,
            "num_pred_nodes": 1, "node_recall": 1., "total_node_ratio": -.5,
            "edge_jaccard": .8, "adj_edge_jaccard": adj}


@pytest.fixture
def synthetic_scoring(synthetic_generation, monkeypatch):
    from biohub import evaluate, io

    state = synthetic_generation
    state["seal"] = _generate_synthetic(state)
    state.update(score_calls=[], gt_reads=[], score_fault=None, outcome="reject12", division=True)
    state["real_score_submission"] = evaluate.score_submission
    state["real_estimated_number_of_nodes"] = io.estimated_number_of_nodes
    monkeypatch.setattr(e26_screen, "_check_score_entry_runtime", lambda: None)

    def estimated(path):
        state["gt_reads"].append(path.stem)
        if state["outcome"] == "reject12":
            assert path.stem in EVAL12, "eval12 rejection read eval24 GT semantics"
        return 2.

    def score(path, gt_dir, max_distance, verbose):
        stage, arm = path.stem.split("_")
        assert max_distance == 7.0 and verbose is False and gt_dir == state["root"] / "data/train"
        state["score_calls"].append((stage, arm))
        baseline = .8
        delta = 0. if state["outcome"] == "reject12" or (state["outcome"] == "reject24" and stage == "eval24") else .01
        rows = [_synthetic_metric_row(name, baseline + (delta if arm == "candidate" else 0.),
                                      division=state["division"]) for name in sorted(_TEST_SCORE_STAGES[stage])]
        if state["outcome"] == "reject36":
            # Simpson's paradox: each stage improves, but arm-specific edge
            # weights shift toward the lower-scoring stage in the candidate.
            for row in rows:
                row["adj_edge_jaccard"] = (.9 if stage == "eval12" else .5) + (.01 if arm == "candidate" else 0.)
                weight = 10000 if ((stage == "eval12") == (arm == "baseline")) else 100
                row.update(edge_tp=weight * 8 // 10, edge_fn=weight * 2 // 10)
        fault = state["score_fault"]
        if fault == "missing_row":
            rows.pop()
        elif fault == "duplicate_row":
            rows[-1] = dict(rows[0])
        elif fault == "bad_pred_count":
            rows[0]["num_pred_nodes"] += 1
        elif fault == "nan_adjusted":
            rows[0]["adj_edge_jaccard"] = math.nan
        summary = evaluate.summarise(rows)
        if fault == "wrong_summary":
            summary["score"] += .1
        if fault == "late_source" and arm == "candidate":
            (state["root"] / e26_screen._SOURCE_PATHS[0]).write_text("drift at end of scoring")
        return summary, rows

    def launch(control_path, sha, timeout_seconds, *, command):
        assert command == "_score"
        start = time.monotonic()
        with monkeypatch.context() as context:
            context.setattr(os, "environ", generation_environment())
            try:
                e26_screen.run_score_child(control_path, sha)
                returncode, error = 0, ""
            except Exception as exc:
                returncode, error = 2, f"{type(exc).__name__}: {exc}"
        (control_path.parent / "stdout.log").write_text("synthetic score process stdout\n")
        (control_path.parent / "stderr.log").write_text(error)
        finish = time.monotonic()
        return {
            "schema_version": "biohub.e26_screen.child_process.v1", "pid": os.getpid(), "returncode": returncode,
            "timed_out": False, "wall_seconds": finish - start, "timeout_seconds": timeout_seconds,
            "started_monotonic": start, "finished_monotonic": finish,
            "argv": [sys.executable, str(state["root"] / "scripts/e26_screen.py"), "_score", "--control",
                     str(control_path), "--control-sha256", sha], "cwd": str(state["root"]),
            "environment": generation_environment(),
            **{key: e26_screen._artifact_reference(control_path.parent / f"{key}.log") for key in ("stdout", "stderr")},
        }

    monkeypatch.setattr(io, "estimated_number_of_nodes", estimated)
    monkeypatch.setattr(evaluate, "score_submission", score)
    monkeypatch.setattr(e26_screen, "_launch_control_process", launch)
    return state


def _score_synthetic(state):
    ref = state["seal"]
    return e26_screen.score_screen(Path(ref["path"]), expected_seal_sha256=ref["sha256"],
                                   expected_public_sha256=state["registration"]["public"]["sha256"],
                                   expected_private_sha256=state["registration"]["private"]["sha256"])


@pytest.mark.parametrize("outcome,stages,status", [
    ("reject12", ["eval12"], "SCREEN_REJECT_EVAL12"),
    ("reject24", ["eval12", "eval24"], "SCREEN_REJECT_EVAL24"),
    ("pass", ["eval12", "eval24", "eval36"], "SCREEN_PASS_REQUIRES_CONFIRMATION"),
    ("reject36", ["eval12", "eval24", "eval36"], "SCREEN_REJECT_EVAL36"),
])
def test_staged_score_official_aggregation_and_common_finalizer(synthetic_scoring, outcome, stages, status):
    state = synthetic_scoring
    state["outcome"] = outcome
    ref = _score_synthetic(state)
    final = json.loads(Path(ref["path"]).read_text())
    assert final["status"] == status and final["submission_authorized"] is False
    assert [gate["stage"] for gate in final["gates"]] == stages
    assert state["score_calls"] == [(stage, arm) for stage in stages if stage != "eval36"
                                    for arm in ("baseline", "candidate")]
    assert state["gt_reads"] == [name for stage in stages if stage != "eval36" for _ in range(2)
                                 for name in _TEST_SCORE_STAGES[stage]]
    assert state["launches"] == list(ARM_ORDER), "scoring generated fresh predictions"
    directory = Path(ref["path"]).parent
    assert not (directory / "SCORE_FAILURE.json").exists()
    result = json.loads((directory / "SCORE_RESULT.json").read_text())
    assert result["control"] == final["control"]
    for stage in stages:
        saved = json.loads((directory / f"{stage}.json").read_text())
        assert saved["paired"]["gate"]["submission_authorized"] is False
        for arm in ("baseline", "candidate"):
            assert [row["dataset"] for row in saved["arms"][arm]["rows"]] == list(_TEST_SCORE_STAGES[stage])
            group = saved["arms"][arm]["groups"][stage]
            assert group["summary"]["n"] == group["summary"]["n_adj"] == len(_TEST_SCORE_STAGES[stage])
            assert group["count_totals"]["edge_tp"] == sum(row["edge_tp"] for row in saved["arms"][arm]["rows"])
    if outcome in ("pass", "reject36"):
        assert saved["saved_row_sources"] == result["stages"][:2] and saved["subsets"] == {}
        assert saved["gt_preflight"] == {}
    with pytest.raises(E26Error, match="already exists"):
        _score_synthetic(state)


@pytest.mark.parametrize("fault", ["missing_row", "duplicate_row", "bad_pred_count", "nan_adjusted", "wrong_summary"])
def test_score_api_omissions_nonfinite_and_wrong_summaries_are_error(synthetic_scoring, fault):
    state = synthetic_scoring
    state["score_fault"] = fault
    with pytest.raises(E26Error, match="child process failed"):
        _score_synthetic(state)
    directory = Path(state["seal"]["path"]).parent / "scoring"
    assert not (directory / "SCREEN_RESULT.json").exists()
    assert not (directory / "SCORE_RESULT.json").exists()
    failure = json.loads((directory / "SCORE_FAILURE.json").read_text())
    assert failure["status"] == "ERROR" and failure["submission_authorized"] is False
    assert failure["present_unvalidated_artifacts"] and failure["missing_artifacts"]
    assert failure["original_control"]["generation_seal"] == state["seal"]
    assert state["score_calls"] == [("eval12", "baseline")]


@pytest.mark.parametrize("outcome,stage", [("reject12", "eval12"), ("reject24", "eval24")])
@pytest.mark.parametrize("target", ["source", "stage_record", "subset"])
def test_early_reject_cannot_bypass_final_integrity(synthetic_scoring, monkeypatch, outcome, stage, target):
    state = synthetic_scoring
    state["outcome"] = outcome
    writer = e26_screen.write_json_exclusive

    def corrupt_after_stage(path, value):
        ref = writer(path, value)
        if path.name == f"{stage}.json":
            selected = {"source": state["root"] / e26_screen._SOURCE_PATHS[0], "stage_record": path,
                        "subset": path.parent / f"{stage}_baseline.csv"}[target]
            selected.write_bytes(selected.read_bytes() + b"tampering after rejected stage")
        return ref

    monkeypatch.setattr(e26_screen, "write_json_exclusive", corrupt_after_stage)
    with pytest.raises(E26Error):
        _score_synthetic(state)
    directory = Path(state["seal"]["path"]).parent / "scoring"
    assert not (directory / "SCREEN_RESULT.json").exists()
    assert not (directory / "SCORE_RESULT.json").exists()
    assert json.loads((directory / "SCORE_FAILURE.json").read_text())["status"] == "ERROR"
    assert all(name in (EVAL12 if outcome == "reject12" else EVAL36) for name in state["gt_reads"])
    assert len(state["score_calls"]) == (2 if outcome == "reject12" else 4)


@pytest.mark.filterwarnings("ignore:No divisions present")
@pytest.mark.parametrize("outcome", ["reject12", "pass"])
def test_division_free_diagnostics_are_null_but_eval36_required_gate_is_error(synthetic_scoring, outcome):
    state = synthetic_scoring
    state.update(outcome=outcome, division=False)
    if outcome == "pass":
        with pytest.raises(E26Error):
            _score_synthetic(state)
        directory = Path(state["seal"]["path"]).parent / "scoring"
        assert not (directory / "SCORE_RESULT.json").exists()
        assert not (directory / "SCREEN_RESULT.json").exists()
        assert "division_jaccard" in (directory / "stderr.log").read_text()
    else:
        ref = _score_synthetic(state)
        directory = Path(ref["path"]).parent
    saved = json.loads((directory / "eval12.json").read_text())
    summary = saved["arms"]["baseline"]["groups"]["eval12"]["summary"]
    assert summary["division_jaccard"] is None and summary["division_jaccard_undefined_reason"]
    assert summary["score"] == summary["adj_edge_jaccard"]
    assert saved["paired"]["payload"]["aggregate_deltas"]["eval12"]["division_jaccard"] is None
    assert set(saved["paired"]["division_delta_undefined_reasons"]["eval12"]) == {"baseline", "candidate"}


@pytest.mark.parametrize("value", [math.nan, math.inf, 0., -1., True])
def test_invalid_estimated_count_prevents_official_graph_scoring(synthetic_scoring, monkeypatch, value):
    from biohub import io

    state = synthetic_scoring
    monkeypatch.setattr(io, "estimated_number_of_nodes", lambda path: value)
    with pytest.raises(E26Error):
        _score_synthetic(state)
    assert state["score_calls"] == []


@pytest.mark.parametrize("target", ["private", "gt", "scale", "prediction"])
def test_sealed_input_drift_prevents_any_gt_semantics(synthetic_scoring, target):
    state = synthetic_scoring
    run = Path(state["seal"]["path"]).parent
    path = {"private": Path(state["registration"]["private"]["path"]),
            "gt": state["root"] / "data/train" / f"{EVAL24[0]}.geff/private.bin",
            "scale": state["root"] / "data/train" / f"{EVAL12[0]}.zarr/zarr.json",
            "prediction": run / "generation/baseline/submission.csv"}[target]
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(E26Error):
        _score_synthetic(state)
    assert state["gt_reads"] == state["score_calls"] == []


def test_score_scale_reader_cannot_use_a_different_fallback(synthetic_scoring, monkeypatch):
    from biohub import io

    state = synthetic_scoring
    monkeypatch.setattr(io, "read_scale", lambda path: (1., 1., 1.))
    with pytest.raises(E26Error):
        _score_synthetic(state)
    assert state["score_calls"] == []


def test_score_runtime_requires_fresh_process_and_explicit_environment():
    script = """
from biohub.e26_screen import _check_score_entry_runtime
_check_score_entry_runtime()
import sys
assert 'biohub.evaluate' not in sys.modules and 'torch' not in sys.modules
import biohub.evaluate
assert 'torch' not in sys.modules
try:
    _check_score_entry_runtime()
except Exception as exc:
    assert 'fresh' in str(exc)
else:
    raise AssertionError('preloaded scorer accepted')
print('fresh scoring import boundary PASS')
"""
    result = subprocess.run([sys.executable, "-c", script], env=generation_environment(),
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "fresh scoring import boundary PASS"


@pytest.fixture
def tiny_official_registration(registration_inputs):
    """Real official two-node GT in test temp paths, registered BEFORE generation.

    All eval24 trees deliberately remain invalid opaque sentinels. Opening one
    semantically would fail, while its permitted integrity hashing still works.
    """
    import polars as pl
    from geff import GeffMetadata

    from biohub.evaluate import graph_from_rows

    root = registration_inputs
    for name in EVAL12:
        path = root / "data/train" / f"{name}.geff"
        (path / "private.bin").unlink()  # Only this fixture's just-created sentinel.
        path.rmdir()
        nodes = pl.DataFrame({"node_id": [0, 1], "t": [0, 1], "z": [0., 0.], "y": [0., 0.], "x": [0., 0.]})
        edges = pl.DataFrame({"source_id": [0], "target_id": [1]})
        graph_from_rows(nodes, edges).to_geff(path)
        metadata = GeffMetadata.read(path)
        metadata.extra["estimated_number_of_nodes"] = 2
        metadata.write(path)
    return root


@pytest.mark.filterwarnings("ignore:No divisions present")
def test_real_official_scoring_path_rejects12_without_reading_later_gt(
    tiny_official_registration, synthetic_scoring, monkeypatch,
):
    # The fixture above runs before synthetic_generation preregisters its trees.
    # Restore only the real scientific API; generation and subprocess boundaries
    # stay synthetic. Do not mistake this for a competition SCREEN result.
    from biohub import evaluate, io

    state = synthetic_scoring
    monkeypatch.setattr(io, "estimated_number_of_nodes", state["real_estimated_number_of_nodes"])
    assert state["root"] == tiny_official_registration
    gt_reader = evaluate.load_geff_graph
    real_score = state["real_score_submission"]
    calls, graph_reads = [], []

    def tracked_graph(path):
        graph_reads.append(path.stem)
        assert path.stem in EVAL12, "later-stage GT graph opened after eval12 rejection"
        return gt_reader(path)

    def tracked_score(*args, **kwargs):
        calls.append(Path(args[0]).stem)
        return real_score(*args, **kwargs)

    monkeypatch.setattr(evaluate, "load_geff_graph", tracked_graph)
    monkeypatch.setattr(evaluate, "score_submission", tracked_score)
    ref = _score_synthetic(state)
    assert json.loads(Path(ref["path"]).read_text())["status"] == "SCREEN_REJECT_EVAL12"
    assert calls == ["eval12_baseline", "eval12_candidate"]
    assert graph_reads == list(EVAL12) * 2
    stage = json.loads((Path(ref["path"]).parent / "eval12.json").read_text())
    for arm in ("baseline", "candidate"):
        group = stage["arms"][arm]["groups"]["eval12"]
        assert group["count_totals"]["edge_tp"] == 0
        assert group["count_totals"]["edge_fn"] == 12
        assert group["summary"]["n"] == group["summary"]["n_adj"] == 12
        assert group["summary"]["score"] == 0. and group["summary"]["division_jaccard"] is None


def test_subset_preserves_graph_and_binds_mechanical_global_id_mapping(tmp_path):
    full, subset = tmp_path / "full.csv", tmp_path / "subset.csv"
    rows = []
    for name in ("before", "selected", "after"):
        for values in ([name, "node", 11, 0, 0, 0, 0, -1, -1],
                       [name, "node", 20, 1, 0, 0, 0, -1, -1],
                       [name, "edge", -1, -1, -1, -1, -1, 11, 20]):
            rows.append(dict(zip(_CSV_COLUMNS, [len(rows), *values], strict=True)))
    _write_csv_fixture(full, rows)
    full_ref = e26_screen._artifact_reference(full)
    args = full_ref, subset, ("selected",), {"selected": (2, 1, 1, 1)}
    provenance = e26_screen._stage_subset(*args, create=True)
    assert provenance == e26_screen._stage_subset(*args, create=False)
    assert provenance["row_id_mapping"]["sha256"] == hashlib.sha256(b"0,3\n1,4\n2,5\n").hexdigest()
    assert provenance["predictions_changed"] is False
    assert provenance["validation"]["total_edges"] == 1
    subset.write_text(subset.read_text().replace(",11,20", ",20,11"))
    with pytest.raises(E26Error, match="subset predictions"):
        e26_screen._stage_subset(*args, create=False)


def test_official_aggregate_is_not_average_of_singleton_scores():
    rows = [_synthetic_metric_row(EVAL12[0], .2), _synthetic_metric_row(EVAL12[1], .8)]
    rows[1].update(edge_tp=8, edge_fn=2)
    group = e26_screen._official_group(rows)
    mean = sum(e26_screen._official_group([row])["summary"]["score"] for row in rows) / 2
    assert group["summary"]["score"] == pytest.approx((100 * .2 + 10 * .8) / 110 + .1)
    assert group["summary"]["score"] != pytest.approx(mean)


@pytest.mark.parametrize("field,value", [("edge_tp", True), ("edge_fp", -1), ("edge_fn", 1.5),
                                         ("num_pred_nodes", 0), ("total_node_ratio", math.inf),
                                         ("node_recall", math.nan), ("edge_jaccard", math.nan)])
def test_official_row_validation_does_not_filter_bad_metrics(field, value):
    name = EVAL12[0]
    row = _synthetic_metric_row(name)
    row[field] = value
    with pytest.raises(E26Error):
        e26_screen._validated_score_rows([row], (name,), {name: {"nodes": 1}})


@pytest.mark.parametrize("stage", ["eval12", "eval24"])
def test_stage_wall_budget_error_prevents_later_scoring(synthetic_scoring, monkeypatch, stage):
    state = synthetic_scoring
    state["outcome"] = "pass"
    check = e26_screen.check_runtime_budget

    def expired(*args, **kwargs):
        if state["score_calls"] and state["score_calls"][-1] == (stage, "baseline"):
            raise E26Error("synthetic stage wall budget exceeded")
        return check(*args, **kwargs)

    monkeypatch.setattr(e26_screen, "check_runtime_budget", expired)
    with pytest.raises(E26Error):
        _score_synthetic(state)
    assert state["score_calls"][-1] == (stage, "baseline")
    directory = Path(state["seal"]["path"]).parent / "scoring"
    assert (directory / "SCORE_FAILURE.json").exists() and not (directory / "SCREEN_RESULT.json").exists()


def test_missing_gt_is_not_silently_omitted(synthetic_scoring):
    state = synthetic_scoring
    (state["root"] / "data/train" / f"{EVAL12[0]}.geff/private.bin").unlink()
    with pytest.raises(E26Error):
        _score_synthetic(state)
    assert state["gt_reads"] == state["score_calls"] == []


def test_score_parent_rejects_child_result_mutation_before_publication(synthetic_scoring, monkeypatch):
    state = synthetic_scoring
    launch = e26_screen._launch_control_process

    def altered(*args, **kwargs):
        receipt = launch(*args, **kwargs)
        directory = Path(args[0]).parent
        path = directory / "SCORE_RESULT.json"
        result = json.loads(path.read_text())
        result["status"] = "SCREEN_PASS_REQUIRES_CONFIRMATION"
        path.write_bytes(e26_screen._json_bytes(result))
        return receipt

    monkeypatch.setattr(e26_screen, "_launch_control_process", altered)
    with pytest.raises(E26Error, match="verdict disagrees"):
        _score_synthetic(state)
    directory = Path(state["seal"]["path"]).parent / "scoring"
    assert json.loads((directory / "SCORE_FAILURE.json").read_text())["operation"] == "score_final_integrity"
    assert not (directory / "SCREEN_RESULT.json").exists()


def test_completed_baseline_score_is_preserved_when_candidate_api_fails(synthetic_scoring, monkeypatch):
    from biohub import evaluate

    state = synthetic_scoring
    scorer = evaluate.score_submission

    def fail_candidate(path, *args, **kwargs):
        if path.stem == "eval12_candidate":
            raise RuntimeError("synthetic candidate graph scoring failed")
        return scorer(path, *args, **kwargs)

    monkeypatch.setattr(evaluate, "score_submission", fail_candidate)
    with pytest.raises(E26Error):
        _score_synthetic(state)
    directory = Path(state["seal"]["path"]).parent / "scoring"
    baseline = json.loads((directory / "eval12_baseline.json").read_text())
    assert baseline["arm"] == "baseline" and len(baseline["official"]["rows"]) == 12
    failure = json.loads((directory / "SCORE_FAILURE.json").read_text())
    ref = next(row for row in failure["present_unvalidated_artifacts"]
               if Path(row["path"]).name == "eval12_baseline.json")
    assert ref["json_reparsed"] is True and ref["scientifically_validated"] is False
    assert not (directory / "eval12.json").exists() and not (directory / "SCREEN_RESULT.json").exists()
