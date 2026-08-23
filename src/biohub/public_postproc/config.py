"""Config for the ported public-notebook post-processing stack.

This mirrors two notebook cells almost verbatim:

* the "constants" cell, which reads ``os.environ.get(NAME, default)`` into
  typed Python constants -- captured here as :data:`CODE_DEFAULTS` (the
  string default for every ``BIOHUB_*`` variable) plus :func:`build_config`,
  which does the same ``os.environ.get`` parsing but against an in-memory
  env map instead of the real process environment;
* the "preset" cell, which unconditionally overwrites a subset of those
  env vars for one named experiment -- captured here as :data:`PRESET`.

``outputs/kaggle/base1_v1/submission.csv`` (score 0.8890) was produced by
the ``biohub_132_clean_short_track_rescue_lightcv_nohack`` preset, i.e.
``CODE_DEFAULTS`` overridden by ``PRESET`` with no further ``--set``.

Only the variables that ``filter_output_graph`` and the CSV/run_stats
writers actually read are modelled here. Variables that only affect the
GPU inference stage (``BIOHUB_DET_THRESHOLD``, ``BIOHUB_UNET_BATCH_SIZE``,
``BIOHUB_ILP_*``, ...) are intentionally out of scope for local
post-processing and are not part of this dataclass; presets that set them
are still accepted (the keys are simply ignored) so a real preset file can
be pasted into ``--set`` without editing it first.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

# ---------------------------------------------------------------------------
# "constants" cell: BIOHUB_<NAME> -> hardcoded string default.
# Verbatim from the notebook's config cell (values only; env var names kept
# so presets stay copy-paste compatible).
# ---------------------------------------------------------------------------
CODE_DEFAULTS: dict[str, str] = {
    "BIOHUB_OUTPUT_EDGE_MAX_UM": "14.0",
    "BIOHUB_OUTPUT_ENFORCE_NEXT_FRAME": "1",
    "BIOHUB_OUTPUT_SINGLE_PARENT_REPAIR": "1",
    "BIOHUB_OUTPUT_SINGLE_CHILD_REPAIR": "0",
    "BIOHUB_OUTPUT_PRUNE_ISOLATED": "1",
    "BIOHUB_OUTPUT_MOTION_RELINK": "1",
    "BIOHUB_MOTION_RELINK_TIGHT_UM": "6.0",
    "BIOHUB_MOTION_RELINK_RELAXED_UM": "10.0",
    "BIOHUB_MOTION_RELINK_VELOCITY_WEIGHT": "0.5",
    "BIOHUB_MOTION_RELINK_LEARNED_BONUS": "0.75",
    "BIOHUB_MOTION_RELINK_MAX_FRAME_NODES": "2600",
    "BIOHUB_OUTPUT_DIVISION_GEOMETRY_FILTER": "0",
    "BIOHUB_DIV_PARENT_MAX_UM": "10.5",
    "BIOHUB_DIV_SISTER_MAX_UM": "8.0",
    "BIOHUB_DIV_DROP_TO_SINGLE_IF_BAD": "1",
    "BIOHUB_OUTPUT_GAP_CLOSE": "1",
    "BIOHUB_GAP_CLOSE_MAX_GAP": "1",
    "BIOHUB_GAP_CLOSE_UM": "6.0",
    "BIOHUB_GAP_DENSITY_ADAPTIVE": "0",
    "BIOHUB_GAP_DENSITY_REFERENCE_UM": "6.5",
    "BIOHUB_GAP_DENSITY_GAIN": "0.040",
    "BIOHUB_GAP_DENSITY_MAX_STEP_DELTA_UM": "0.125",
    "BIOHUB_GAP_DENSITY_NEIGHBORS": "3",
    "BIOHUB_GAP_CLOSE_REUSE_EXISTING": "1",
    "BIOHUB_GAP_CLOSE_REUSE_UM": "3.2",
    "BIOHUB_GAP_CLOSE_MAX_ADDED_FRAC": "0.05",
    "BIOHUB_GAP_CLOSE_MAX_ADDED_ABS": "2000",
    "BIOHUB_GAP_REFINE_SYNTHETIC": "1",
    "BIOHUB_GAP_REFINE_WIN_Z": "1",
    "BIOHUB_GAP_REFINE_WIN_YX": "3",
    "BIOHUB_GAP_REFINE_MAX_SHIFT_UM": "3.2",
    "BIOHUB_OUTPUT_FILTER_SHORT_TRACKS": "1",
    "BIOHUB_OUTPUT_MIN_TRACK_LEN": "6",
    "BIOHUB_OUTPUT_KEEP_DIVISION_COMPONENTS": "1",
    "BIOHUB_ADAPTIVE_SHORT_TRACK_RESCUE": "0",
    "BIOHUB_SHORT_TRACK_RESCUE_TRIGGER_REMOVED_FRAC": "0.10",
    "BIOHUB_SHORT_TRACK_RESCUE_MIN_LEN": "4",
    "BIOHUB_SHORT_TRACK_RESCUE_MIN_MEAN_EDGE_PROB": "0.82",
    "BIOHUB_SHORT_TRACK_RESCUE_MAX_MEAN_EDGE_DIST_UM": "3.25",
    "BIOHUB_SHORT_TRACK_RESCUE_MAX_NODES_FRAC": "0.018",
    "BIOHUB_SHORT_TRACK_RESCUE_MAX_NODES_ABS": "180",
    "BIOHUB_OUTPUT_LINEFIT_SMOOTH": "1",
    "BIOHUB_OUTPUT_LINEFIT_WEIGHT": "0.8",
    "BIOHUB_OUTPUT_LINEFIT_WINDOW": "2",
    "BIOHUB_OUTPUT_GAP2_RECOVERY": "0",
    "BIOHUB_GAP2_MAX_TOTAL_UM": "10.2",
    "BIOHUB_GAP2_MAX_STEP_UM": "4.4",
    "BIOHUB_GAP2_MAX_LINKS_FRAC": "0.0045",
    "BIOHUB_GAP2_MAX_LINKS_ABS": "180",
    "BIOHUB_GAP2_REQUIRE_CONTEXT": "1",
    "BIOHUB_GAP2_FRAME_FRAC_CAP": "0.006",
    "BIOHUB_OUTPUT_SAFE_DIVISIONS": "1",
    "BIOHUB_SAFE_DIV_MAX_UM": "4.7",
    "BIOHUB_SAFE_DIV_SISTER_MAX_UM": "7.2",
    "BIOHUB_SAFE_DIV_EXISTING_CHILD_MAX_UM": "7.8",
    "BIOHUB_SAFE_DIV_FRAME_FRAC_CAP": "0.008",
    "BIOHUB_SAFE_DIV_GLOBAL_FRAC_CAP": "0.004",
    "BIOHUB_USE_DEEPCENTER_VETO": "1",
    "BIOHUB_REQUIRE_DEEPCENTER_VETO": "1",
    "BIOHUB_DEEPCENTER_GAP_VETO": "1",
    "BIOHUB_DEEPCENTER_SAFE_DIV_VETO": "1",
    "BIOHUB_DEEPCENTER_GAP_THRESHOLD": "0.10",
    "BIOHUB_DEEPCENTER_EXPECTED_EPOCH": "0",
    "BIOHUB_DEEPCENTER_GAP_CONFIRM_MIN_SPAN_UM": "0",
    "BIOHUB_DEEPCENTER_SAFE_DIV_THRESHOLD": "0.12",
    "BIOHUB_DEEPCENTER_SCORE_WIN_Z": "1",
    "BIOHUB_DEEPCENTER_SCORE_WIN_YX": "2",
    "BIOHUB_DEEPCENTER_SCORE_CACHE_MAX_FRAMES": "8",
    "BIOHUB_DEEPCENTER_RELATIVE": "weights/full_frame_center/checkpoint_last.pt",
    "BIOHUB_DEEPCENTER_CHECKPOINT": "",
    "BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT": (
        "/kaggle/input/biohub-deepcenter-unet3d-center-prior-v1/weights/full_frame_center/checkpoint_last.pt"
    ),
    "BIOHUB_DEEPCENTER_MANIFEST": "",
    "BIOHUB_DEEPCENTER_MANIFEST_DEFAULT": (
        "/kaggle/input/datasets/pilkwang/biohub-deepcenter-unet3d-center-prior-v1/ARTIFACT_MANIFEST.json"
    ),
    "BIOHUB_EXPERIMENT_TAG": "biohub_132_clean_short_track_rescue_lightcv_nohack",
}

# ---------------------------------------------------------------------------
# "preset" cell: biohub_132_clean_short_track_rescue_lightcv_nohack.
# Verbatim from the notebook preset -- values that are the same as
# CODE_DEFAULTS are kept too, so this dict alone documents the full preset.
# Only the keys relevant to post-processing are included (the source cell
# also sets BIOHUB_DET_THRESHOLD, BIOHUB_ILP_*, BIOHUB_RUN_VISUAL_EDA, ...,
# which affect the GPU/ILP stage or notebook display only).
# ---------------------------------------------------------------------------
PRESET: dict[str, str] = {
    "BIOHUB_OUTPUT_FILTER_SHORT_TRACKS": "1",
    "BIOHUB_MOTION_RELINK_LEARNED_BONUS": "1.0",
    "BIOHUB_MOTION_RELINK_TIGHT_UM": "6.0",
    "BIOHUB_MOTION_RELINK_RELAXED_UM": "9.5",
    "BIOHUB_GAP_CLOSE_MAX_GAP": "2",
    "BIOHUB_GAP_CLOSE_UM": "5.8",
    "BIOHUB_GAP_DENSITY_ADAPTIVE": "1",
    "BIOHUB_GAP_DENSITY_REFERENCE_UM": "6.5",
    "BIOHUB_GAP_DENSITY_GAIN": "0.040",
    "BIOHUB_GAP_DENSITY_MAX_STEP_DELTA_UM": "0.125",
    "BIOHUB_GAP_DENSITY_NEIGHBORS": "3",
    "BIOHUB_OUTPUT_MIN_TRACK_LEN": "6",
    "BIOHUB_OUTPUT_KEEP_DIVISION_COMPONENTS": "1",
    "BIOHUB_OUTPUT_GAP2_RECOVERY": "0",
    "BIOHUB_SAFE_DIV_MAX_UM": "4.66",
    "BIOHUB_SAFE_DIV_SISTER_MAX_UM": "8.5",
    "BIOHUB_SAFE_DIV_EXISTING_CHILD_MAX_UM": "7.65",
    "BIOHUB_SAFE_DIV_FRAME_FRAC_CAP": "0.0076",
    "BIOHUB_SAFE_DIV_GLOBAL_FRAC_CAP": "0.00375",
    "BIOHUB_ADAPTIVE_SHORT_TRACK_RESCUE": "1",
    "BIOHUB_SHORT_TRACK_RESCUE_TRIGGER_REMOVED_FRAC": "0.10",
    "BIOHUB_SHORT_TRACK_RESCUE_MIN_LEN": "5",
    "BIOHUB_SHORT_TRACK_RESCUE_MIN_MEAN_EDGE_PROB": "0.90",
    "BIOHUB_SHORT_TRACK_RESCUE_MAX_MEAN_EDGE_DIST_UM": "2.75",
    "BIOHUB_SHORT_TRACK_RESCUE_MAX_NODES_FRAC": "0.006",
    "BIOHUB_SHORT_TRACK_RESCUE_MAX_NODES_ABS": "60",
    "BIOHUB_USE_DEEPCENTER_VETO": "0",
    "BIOHUB_REQUIRE_DEEPCENTER_VETO": "0",
    "BIOHUB_DEEPCENTER_EXPECTED_EPOCH": "0",
    "BIOHUB_DEEPCENTER_GAP_CONFIRM_MIN_SPAN_UM": "8.0",
    "BIOHUB_DEEPCENTER_CHECKPOINT": "",
    "BIOHUB_DEEPCENTER_GAP_VETO": "0",
    "BIOHUB_DEEPCENTER_GAP_THRESHOLD": "0.20",
    "BIOHUB_DEEPCENTER_SAFE_DIV_VETO": "0",
    "BIOHUB_EXPERIMENT_TAG": "biohub_132_clean_short_track_rescue_lightcv_nohack",
}


def _get_bool(env: dict[str, str], name: str) -> bool:
    return env.get(name, CODE_DEFAULTS[name]) != "0"


def _get_float(env: dict[str, str], name: str) -> float:
    return float(env.get(name, CODE_DEFAULTS[name]))


def _get_int(env: dict[str, str], name: str) -> int:
    return int(env.get(name, CODE_DEFAULTS[name]))


def _get_str(env: dict[str, str], name: str) -> str:
    return env.get(name, CODE_DEFAULTS[name])


@dataclass(frozen=True)
class PostprocConfig:
    """Typed, parsed view of the ``BIOHUB_*`` post-processing knobs.

    Field names match the notebook's constant names (minus the ``BIOHUB_``
    prefix) so the port stays traceable line-for-line against the source
    cells.
    """

    TEST_DIR: Path

    OUTPUT_EDGE_MAX_UM: float
    OUTPUT_ENFORCE_NEXT_FRAME: bool
    OUTPUT_SINGLE_PARENT_REPAIR: bool
    OUTPUT_SINGLE_CHILD_REPAIR: bool
    OUTPUT_PRUNE_ISOLATED: bool
    OUTPUT_MOTION_RELINK: bool
    MOTION_RELINK_TIGHT_UM: float
    MOTION_RELINK_RELAXED_UM: float
    MOTION_RELINK_VELOCITY_WEIGHT: float
    MOTION_RELINK_LEARNED_BONUS: float
    MOTION_RELINK_MAX_FRAME_NODES: int

    OUTPUT_DIVISION_GEOMETRY_FILTER: bool
    DIV_PARENT_MAX_UM: float
    DIV_SISTER_MAX_UM: float
    DIV_DROP_TO_SINGLE_IF_BAD: bool

    OUTPUT_GAP_CLOSE: bool
    GAP_CLOSE_MAX_GAP: int
    GAP_CLOSE_UM: float
    GAP_DENSITY_ADAPTIVE: bool
    GAP_DENSITY_REFERENCE_UM: float
    GAP_DENSITY_GAIN: float
    GAP_DENSITY_MAX_STEP_DELTA_UM: float
    GAP_DENSITY_NEIGHBORS: int
    GAP_CLOSE_REUSE_EXISTING: bool
    GAP_CLOSE_REUSE_UM: float
    GAP_CLOSE_MAX_ADDED_FRAC: float
    GAP_CLOSE_MAX_ADDED_ABS: int
    GAP_REFINE_SYNTHETIC: bool
    GAP_REFINE_WIN_Z: int
    GAP_REFINE_WIN_YX: int
    GAP_REFINE_MAX_SHIFT_UM: float

    OUTPUT_FILTER_SHORT_TRACKS: bool
    OUTPUT_MIN_TRACK_LEN: int
    OUTPUT_KEEP_DIVISION_COMPONENTS: bool
    ADAPTIVE_SHORT_TRACK_RESCUE: bool
    SHORT_TRACK_RESCUE_TRIGGER_REMOVED_FRAC: float
    SHORT_TRACK_RESCUE_MIN_LEN: int
    SHORT_TRACK_RESCUE_MIN_MEAN_EDGE_PROB: float
    SHORT_TRACK_RESCUE_MAX_MEAN_EDGE_DIST_UM: float
    SHORT_TRACK_RESCUE_MAX_NODES_FRAC: float
    SHORT_TRACK_RESCUE_MAX_NODES_ABS: int

    OUTPUT_LINEFIT_SMOOTH: bool
    OUTPUT_LINEFIT_WEIGHT: float
    OUTPUT_LINEFIT_WINDOW: int

    OUTPUT_GAP2_RECOVERY: bool
    GAP2_MAX_TOTAL_UM: float
    GAP2_MAX_STEP_UM: float
    GAP2_MAX_LINKS_FRAC: float
    GAP2_MAX_LINKS_ABS: int
    GAP2_REQUIRE_CONTEXT: bool
    GAP2_FRAME_FRAC_CAP: float

    OUTPUT_SAFE_DIVISIONS: bool
    SAFE_DIV_MAX_UM: float
    SAFE_DIV_SISTER_MAX_UM: float
    SAFE_DIV_EXISTING_CHILD_MAX_UM: float
    SAFE_DIV_FRAME_FRAC_CAP: float
    SAFE_DIV_GLOBAL_FRAC_CAP: float

    USE_DEEPCENTER_VETO: bool
    REQUIRE_DEEPCENTER_VETO: bool
    DEEPCENTER_GAP_VETO: bool
    DEEPCENTER_SAFE_DIV_VETO: bool
    DEEPCENTER_GAP_THRESHOLD: float
    DEEPCENTER_EXPECTED_EPOCH: int
    DEEPCENTER_GAP_CONFIRM_MIN_SPAN_UM: float
    DEEPCENTER_SAFE_DIV_THRESHOLD: float
    DEEPCENTER_SCORE_WIN_Z: int
    DEEPCENTER_SCORE_WIN_YX: int
    DEEPCENTER_SCORE_CACHE_MAX_FRAMES: int
    DEEPCENTER_RELATIVE: str
    DEEPCENTER_CHECKPOINT: str
    DEEPCENTER_CHECKPOINT_DEFAULT: str
    DEEPCENTER_MANIFEST: str
    DEEPCENTER_MANIFEST_DEFAULT: str

    EXPERIMENT_TAG: str


def build_config(overrides: dict[str, str] | None = None, test_dir: Path | str = Path("data/test")) -> PostprocConfig:
    """Build a :class:`PostprocConfig` the same way the notebook builds its constants.

    Resolution order (last wins), mirroring "preset cell overwrites
    os.environ, constants cell reads os.environ.get(name, hardcoded)":
    ``CODE_DEFAULTS`` -> :data:`PRESET` -> ``overrides`` (``--set``).
    """
    env: dict[str, str] = dict(CODE_DEFAULTS)
    env.update(PRESET)
    if overrides:
        unknown = sorted(set(overrides) - set(CODE_DEFAULTS))
        if unknown:
            raise KeyError(f"unknown BIOHUB_* override key(s): {unknown}")
        env.update(overrides)

    return PostprocConfig(
        TEST_DIR=Path(test_dir),
        OUTPUT_EDGE_MAX_UM=_get_float(env, "BIOHUB_OUTPUT_EDGE_MAX_UM"),
        OUTPUT_ENFORCE_NEXT_FRAME=_get_bool(env, "BIOHUB_OUTPUT_ENFORCE_NEXT_FRAME"),
        OUTPUT_SINGLE_PARENT_REPAIR=_get_bool(env, "BIOHUB_OUTPUT_SINGLE_PARENT_REPAIR"),
        OUTPUT_SINGLE_CHILD_REPAIR=_get_bool(env, "BIOHUB_OUTPUT_SINGLE_CHILD_REPAIR"),
        OUTPUT_PRUNE_ISOLATED=_get_bool(env, "BIOHUB_OUTPUT_PRUNE_ISOLATED"),
        OUTPUT_MOTION_RELINK=_get_bool(env, "BIOHUB_OUTPUT_MOTION_RELINK"),
        MOTION_RELINK_TIGHT_UM=_get_float(env, "BIOHUB_MOTION_RELINK_TIGHT_UM"),
        MOTION_RELINK_RELAXED_UM=_get_float(env, "BIOHUB_MOTION_RELINK_RELAXED_UM"),
        MOTION_RELINK_VELOCITY_WEIGHT=_get_float(env, "BIOHUB_MOTION_RELINK_VELOCITY_WEIGHT"),
        MOTION_RELINK_LEARNED_BONUS=_get_float(env, "BIOHUB_MOTION_RELINK_LEARNED_BONUS"),
        MOTION_RELINK_MAX_FRAME_NODES=_get_int(env, "BIOHUB_MOTION_RELINK_MAX_FRAME_NODES"),
        OUTPUT_DIVISION_GEOMETRY_FILTER=_get_bool(env, "BIOHUB_OUTPUT_DIVISION_GEOMETRY_FILTER"),
        DIV_PARENT_MAX_UM=_get_float(env, "BIOHUB_DIV_PARENT_MAX_UM"),
        DIV_SISTER_MAX_UM=_get_float(env, "BIOHUB_DIV_SISTER_MAX_UM"),
        DIV_DROP_TO_SINGLE_IF_BAD=_get_bool(env, "BIOHUB_DIV_DROP_TO_SINGLE_IF_BAD"),
        OUTPUT_GAP_CLOSE=_get_bool(env, "BIOHUB_OUTPUT_GAP_CLOSE"),
        GAP_CLOSE_MAX_GAP=_get_int(env, "BIOHUB_GAP_CLOSE_MAX_GAP"),
        GAP_CLOSE_UM=_get_float(env, "BIOHUB_GAP_CLOSE_UM"),
        GAP_DENSITY_ADAPTIVE=_get_bool(env, "BIOHUB_GAP_DENSITY_ADAPTIVE"),
        GAP_DENSITY_REFERENCE_UM=_get_float(env, "BIOHUB_GAP_DENSITY_REFERENCE_UM"),
        GAP_DENSITY_GAIN=_get_float(env, "BIOHUB_GAP_DENSITY_GAIN"),
        GAP_DENSITY_MAX_STEP_DELTA_UM=_get_float(env, "BIOHUB_GAP_DENSITY_MAX_STEP_DELTA_UM"),
        GAP_DENSITY_NEIGHBORS=_get_int(env, "BIOHUB_GAP_DENSITY_NEIGHBORS"),
        GAP_CLOSE_REUSE_EXISTING=_get_bool(env, "BIOHUB_GAP_CLOSE_REUSE_EXISTING"),
        GAP_CLOSE_REUSE_UM=_get_float(env, "BIOHUB_GAP_CLOSE_REUSE_UM"),
        GAP_CLOSE_MAX_ADDED_FRAC=_get_float(env, "BIOHUB_GAP_CLOSE_MAX_ADDED_FRAC"),
        GAP_CLOSE_MAX_ADDED_ABS=_get_int(env, "BIOHUB_GAP_CLOSE_MAX_ADDED_ABS"),
        GAP_REFINE_SYNTHETIC=_get_bool(env, "BIOHUB_GAP_REFINE_SYNTHETIC"),
        GAP_REFINE_WIN_Z=_get_int(env, "BIOHUB_GAP_REFINE_WIN_Z"),
        GAP_REFINE_WIN_YX=_get_int(env, "BIOHUB_GAP_REFINE_WIN_YX"),
        GAP_REFINE_MAX_SHIFT_UM=_get_float(env, "BIOHUB_GAP_REFINE_MAX_SHIFT_UM"),
        OUTPUT_FILTER_SHORT_TRACKS=_get_bool(env, "BIOHUB_OUTPUT_FILTER_SHORT_TRACKS"),
        OUTPUT_MIN_TRACK_LEN=_get_int(env, "BIOHUB_OUTPUT_MIN_TRACK_LEN"),
        OUTPUT_KEEP_DIVISION_COMPONENTS=_get_bool(env, "BIOHUB_OUTPUT_KEEP_DIVISION_COMPONENTS"),
        ADAPTIVE_SHORT_TRACK_RESCUE=_get_bool(env, "BIOHUB_ADAPTIVE_SHORT_TRACK_RESCUE"),
        SHORT_TRACK_RESCUE_TRIGGER_REMOVED_FRAC=_get_float(env, "BIOHUB_SHORT_TRACK_RESCUE_TRIGGER_REMOVED_FRAC"),
        SHORT_TRACK_RESCUE_MIN_LEN=_get_int(env, "BIOHUB_SHORT_TRACK_RESCUE_MIN_LEN"),
        SHORT_TRACK_RESCUE_MIN_MEAN_EDGE_PROB=_get_float(env, "BIOHUB_SHORT_TRACK_RESCUE_MIN_MEAN_EDGE_PROB"),
        SHORT_TRACK_RESCUE_MAX_MEAN_EDGE_DIST_UM=_get_float(env, "BIOHUB_SHORT_TRACK_RESCUE_MAX_MEAN_EDGE_DIST_UM"),
        SHORT_TRACK_RESCUE_MAX_NODES_FRAC=_get_float(env, "BIOHUB_SHORT_TRACK_RESCUE_MAX_NODES_FRAC"),
        SHORT_TRACK_RESCUE_MAX_NODES_ABS=_get_int(env, "BIOHUB_SHORT_TRACK_RESCUE_MAX_NODES_ABS"),
        OUTPUT_LINEFIT_SMOOTH=_get_bool(env, "BIOHUB_OUTPUT_LINEFIT_SMOOTH"),
        OUTPUT_LINEFIT_WEIGHT=_get_float(env, "BIOHUB_OUTPUT_LINEFIT_WEIGHT"),
        OUTPUT_LINEFIT_WINDOW=_get_int(env, "BIOHUB_OUTPUT_LINEFIT_WINDOW"),
        OUTPUT_GAP2_RECOVERY=_get_bool(env, "BIOHUB_OUTPUT_GAP2_RECOVERY"),
        GAP2_MAX_TOTAL_UM=_get_float(env, "BIOHUB_GAP2_MAX_TOTAL_UM"),
        GAP2_MAX_STEP_UM=_get_float(env, "BIOHUB_GAP2_MAX_STEP_UM"),
        GAP2_MAX_LINKS_FRAC=_get_float(env, "BIOHUB_GAP2_MAX_LINKS_FRAC"),
        GAP2_MAX_LINKS_ABS=_get_int(env, "BIOHUB_GAP2_MAX_LINKS_ABS"),
        GAP2_REQUIRE_CONTEXT=_get_bool(env, "BIOHUB_GAP2_REQUIRE_CONTEXT"),
        GAP2_FRAME_FRAC_CAP=_get_float(env, "BIOHUB_GAP2_FRAME_FRAC_CAP"),
        OUTPUT_SAFE_DIVISIONS=_get_bool(env, "BIOHUB_OUTPUT_SAFE_DIVISIONS"),
        SAFE_DIV_MAX_UM=_get_float(env, "BIOHUB_SAFE_DIV_MAX_UM"),
        SAFE_DIV_SISTER_MAX_UM=_get_float(env, "BIOHUB_SAFE_DIV_SISTER_MAX_UM"),
        SAFE_DIV_EXISTING_CHILD_MAX_UM=_get_float(env, "BIOHUB_SAFE_DIV_EXISTING_CHILD_MAX_UM"),
        SAFE_DIV_FRAME_FRAC_CAP=_get_float(env, "BIOHUB_SAFE_DIV_FRAME_FRAC_CAP"),
        SAFE_DIV_GLOBAL_FRAC_CAP=_get_float(env, "BIOHUB_SAFE_DIV_GLOBAL_FRAC_CAP"),
        USE_DEEPCENTER_VETO=_get_bool(env, "BIOHUB_USE_DEEPCENTER_VETO"),
        REQUIRE_DEEPCENTER_VETO=_get_bool(env, "BIOHUB_REQUIRE_DEEPCENTER_VETO"),
        DEEPCENTER_GAP_VETO=_get_bool(env, "BIOHUB_DEEPCENTER_GAP_VETO"),
        DEEPCENTER_SAFE_DIV_VETO=_get_bool(env, "BIOHUB_DEEPCENTER_SAFE_DIV_VETO"),
        DEEPCENTER_GAP_THRESHOLD=_get_float(env, "BIOHUB_DEEPCENTER_GAP_THRESHOLD"),
        DEEPCENTER_EXPECTED_EPOCH=_get_int(env, "BIOHUB_DEEPCENTER_EXPECTED_EPOCH"),
        DEEPCENTER_GAP_CONFIRM_MIN_SPAN_UM=_get_float(env, "BIOHUB_DEEPCENTER_GAP_CONFIRM_MIN_SPAN_UM"),
        DEEPCENTER_SAFE_DIV_THRESHOLD=_get_float(env, "BIOHUB_DEEPCENTER_SAFE_DIV_THRESHOLD"),
        DEEPCENTER_SCORE_WIN_Z=_get_int(env, "BIOHUB_DEEPCENTER_SCORE_WIN_Z"),
        DEEPCENTER_SCORE_WIN_YX=_get_int(env, "BIOHUB_DEEPCENTER_SCORE_WIN_YX"),
        DEEPCENTER_SCORE_CACHE_MAX_FRAMES=_get_int(env, "BIOHUB_DEEPCENTER_SCORE_CACHE_MAX_FRAMES"),
        DEEPCENTER_RELATIVE=_get_str(env, "BIOHUB_DEEPCENTER_RELATIVE"),
        DEEPCENTER_CHECKPOINT=_get_str(env, "BIOHUB_DEEPCENTER_CHECKPOINT"),
        DEEPCENTER_CHECKPOINT_DEFAULT=_get_str(env, "BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT"),
        DEEPCENTER_MANIFEST=_get_str(env, "BIOHUB_DEEPCENTER_MANIFEST"),
        DEEPCENTER_MANIFEST_DEFAULT=_get_str(env, "BIOHUB_DEEPCENTER_MANIFEST_DEFAULT"),
        EXPERIMENT_TAG=_get_str(env, "BIOHUB_EXPERIMENT_TAG"),
    )


def config_field_names() -> list[str]:
    return [f.name for f in fields(PostprocConfig)]


def parse_set_overrides(pairs: list[str]) -> dict[str, str]:
    """Parse repeated ``--set NAME=VALUE`` CLI args into a ``BIOHUB_*`` override dict.

    ``NAME`` may omit the ``BIOHUB_`` prefix for brevity.
    """
    overrides: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--set expects NAME=VALUE, got: {pair!r}")
        name, value = pair.split("=", 1)
        name = name.strip()
        if not name.startswith("BIOHUB_"):
            name = f"BIOHUB_{name}"
        overrides[name] = value.strip()
    return overrides
