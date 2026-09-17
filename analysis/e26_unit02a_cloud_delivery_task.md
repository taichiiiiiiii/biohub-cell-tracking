# E26 unit02a — supervised Cloud source-delivery handoff

> 履歴・非運用・現行起動に使用禁止。この旧タスクは保存用です。
> 現行方針は [AGENTS.md](../AGENTS.md)、MAX評価入口は
> [評価手順](../.codex/runners/biohub_max_implementer.instructions.md) を参照。
> 以下のモデル指定・命令・実行例は当時の履歴であり、現在のworkerへ渡してはいけません。

2026-09-06. This is a redesigned delivery step within the current direct user
request to implement via exact Qwen Cloud qwen3.7-plus using the existing
qwen_token_plan subscription. It is not an unattended goal/heartbeat job.
The previous Cloud patch-authoring attempt was stopped after three repeated
patch-format rejections, exit130 at10:39:59.715020 UTC after135.4s, no files.
Its final message identified missing '+' prefixes, but no corrected patch was
accepted. The rejected full patch inputs are unavailable; do not guess a cause
beyond the observed parser errors. Do not retry that frozen patch task.

## Delivery design and responsibility

Qwen must author both complete files. Do not call ANY tools, including apply_patch,
shell, exec_command, write_stdin, view_image, another agent or request_user_input.
Do not discover files or search for context; the complete source reference below
is enough. Do not create patches, diff hunks or placeholder files. Return only the
two complete file contents in the final message with this exact structure:

### src/biohub/e26_screen.py
```python
<complete source, no placeholder>
```

### tests/test_e26_screen.py
```python
<complete tests, no placeholder>
```

The two headings above are output labels, not commands. Do not include any other
code fences, prose, diagnostic text or markdown inside the Python blocks.
The parent will parse exactly these two blocks, preserve their bytes, inspect
all code/tests, and mechanically apply them only to the two previously absent
approved-worktree paths. Parent must not add or rewrite scientific code. If the
output is incomplete, malformed, or requires changes, do not silently fill gaps.
Before parsing or applying, the parent must inspect the complete worker log for
zero tool-call/file-change events or tool errors, recheck that both targets are
still absent and verify the worktree has the identical clean preflight state.
Any tool activity, unexplained log gap, file mutation or failed check invalidates
this delivery: preserve evidence and stop without applying its final blocks.
Tests are NOT RUN by Qwen. Parent will execute the unchanged commands below only
after full code review and obtain independent SOL review before acceptance.
A single newly designed supervised delivery has a600s wall cap, extensions0,
request/stream retries0, no model/provider fallback. This is not authority for
repeated relaunches, unattended runs, PAYG, purchases, resets or new worktrees.
Only launcher/queue-managed Codex provider transport may use the existing
subscription endpoint/auth helper. No model-generated tools or network calls.
The fixed current Cloud routing overrides historical local names in AGENTS.

## Files and API

Only author the complete contents of `src/biohub/e26_screen.py` and
`tests/test_e26_screen.py` for the one approved worktree. Do not write files
or call tools in this delivery-only task; the parent mechanically saves your output. No edits to existing source/tests, official/, AGENTS,
launchers or data. No Git mutations, network, credentials, dependencies, agents,
model loading, filesystem I/O in the new module, real data or scoring.

Implement only:

- `E26Error`, a RuntimeError subclass.
- `CANDIDATE_ID = "e23_motion_relink_off_v1"`.
- `ARM_ORDER = ("public4_parity", "baseline", "candidate")`.
- `build_arm_config(arm: str, image_root: Path, checkpoint: Path,
  manifest: Path) -> PostprocConfig`.
- `validate_config_pair(baseline: PostprocConfig, candidate: PostprocConfig,
  *, image_root: Path, checkpoint: Path, manifest: Path) -> None`.

Use existing `build_config(overrides, test_dir, profile="e23")`, not hand-copied
preset values. Image root/checkpoint/manifest arguments must be Path instances.
Unknown/non-string arms or malformed inputs raise E26Error. Do not resolve/read
paths: nonexistent fixture paths are valid pure inputs.
All arms apply identical explicit string path overrides for
`BIOHUB_DEEPCENTER_CHECKPOINT`, `BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT`,
`BIOHUB_DEEPCENTER_MANIFEST`, `BIOHUB_DEEPCENTER_MANIFEST_DEFAULT`.
Only candidate adds `BIOHUB_OUTPUT_MOTION_RELINK="0"`. No arbitrary caller
overrides and no process-environment reads. Public4 may use a different image root;
it is not part of the 36-video pair comparison.

Pair validation must reject coordinated drift: rebuild expected baseline and
candidate from the explicit path arguments and exact E23 profile. Validate actual
PostprocConfig objects across every dataclass field, including value types, not
just Python equality (bool must not pass as int or vice versa). The only pair
difference must be OUTPUT_MOTION_RELINK, literal True→False; both
OUTPUT_STEAL_TWIN_REWIRE values must be literal False. TEST_DIR, EXPERIMENT_TAG,
all other flags/thresholds/paths remain exactly expected. Reject wrong object
types, a changed shared threshold/tag/weight path or image root, additional pair
differences and equalized motion flags. Return None only on a valid pair.

Example usage: build baseline and candidate with the same three Path arguments,
then pass the pair and those same paths to validate_config_pair. No gate payload
is involved in this unit. Do not invent a partial screening verdict or return
any success/adoption/submission status.

## Acceptance and the unchanged remaining scope

Focused tests must cover all three arms, all four explicit weight path overrides,
the full exact pair, public4's separate root, invalid arms/path/object types,
shared and one-sided drift, literal boolean/type violations and environment
independence. Use synthetic Path values and dataclasses.replace; no real files.

The accepted unit01 motion-branch tests are unchanged. Unit02b still must add the
original literal EVAL12/EVAL24/EVAL36, pure paired statistics, exact stage gates,
schema/payload validation and every boundary/error/no-submit test. None of those
requirements is waived, replaced by config tests or considered complete here.
Unit03/04/physical generation/scoring remain blocked on all of unit02 acceptance.

## Complete read-only source reference

Existing src/biohub/public_postproc/config.py, all633 lines,31182 bytes.
SHA-256:415a586ad4d8a81b96314025fa0cf05ce6c797df7ef8eb75e53f48efe192d882.
Import PostprocConfig and build_config from biohub.public_postproc.config.
Do not reimplement, edit or copy this module/presets into the new module. Its full
text is context for the existing field types, mappings and factory behavior,
not additional work or a new scientific candidate. Historical comments about
scores are not fresh leaderboard or validation evidence.

```python
"""Config for the ported public-notebook post-processing stack.

This mirrors two notebook cells almost verbatim:

* the "constants" cell, which reads ``os.environ.get(NAME, default)`` into
  typed Python constants -- captured here as :data:`CODE_DEFAULTS` (the
  string default for every ``BIOHUB_*`` variable) plus :func:`build_config`,
  which does the same ``os.environ.get`` parsing but against an in-memory
  env map instead of the real process environment;
* the "preset" cell, which unconditionally overwrites a subset of those
  env vars for one named experiment -- captured here as :data:`PRESET`.

:data:`PRESET` is also exported as :data:`BASE1_PRESET`. Named profiles
(see :data:`PROFILES`) select which preset is layered on top of
``CODE_DEFAULTS`` by :func:`build_config`:

* ``base1`` -- ``CODE_DEFAULTS`` + ``PRESET``; the exact config that
  produced ``outputs/kaggle/base1_v1/submission.csv`` (score 0.8890) via
  the ``biohub_132_clean_short_track_rescue_lightcv_nohack`` preset with
  no further ``--set``. This is the default and stays byte-for-byte
  identical to the previous behavior.
* ``e23`` -- ``CODE_DEFAULTS`` + :data:`E23_PRESET`; the submitted E23
  notebook's effective post-processing settings (public LB 0.924), per the
  E23 parity contract in ``analysis/gold_loop_protocol.md``. It is built
  directly on ``CODE_DEFAULTS`` and never inherits the base1 preset.
* ``e23_twin_only_v1`` -- ``CODE_DEFAULTS`` + :data:`TWIN_ONLY_V1_PRESET`;
  the frozen twin-only experiment configuration layered on E23.

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
    # Phase-1 (E23 parity) additions: not part of the original notebook's
    # constants cell. Defaults keep base1 behavior: refinement off, legacy
    # safe-division mode, structural gates off.
    "BIOHUB_REFINE_ALL_CENTROIDS": "0",
    "BIOHUB_REFINE_CENTROIDS_WIN_Z": "1",
    "BIOHUB_REFINE_CENTROIDS_WIN_YX": "3",
    "BIOHUB_REFINE_CENTROIDS_BASELINE_PERCENTILE": "20.0",
    "BIOHUB_REFINE_CENTROIDS_MAX_SHIFT_UM": "2.8",
    "BIOHUB_SAFE_DIV_MODE": "legacy",
    "BIOHUB_SAFE_DIV_REQUIRE_MID_TRACK_PARENT": "0",
    "BIOHUB_SAFE_DIV_REQUIRE_MUTUAL_NN": "0",
    "BIOHUB_SAFE_DIV_REQUIRE_DIVERGENCE": "0",
    "BIOHUB_SAFE_DIV_DIVERGE_UM": "2.25",
    "BIOHUB_OUTPUT_STEAL_TWIN_REWIRE": "0",
    "BIOHUB_STEAL_TWIN_MODE": "twin_only_v1",
    "BIOHUB_STEAL_TWIN_DRY_RUN": "0",
    "BIOHUB_STEAL_TWIN_PARENT_MAX_UM": "8.0",
    "BIOHUB_STEAL_TWIN_EXISTING_CHILD_MAX_UM": "10.0",
    "BIOHUB_STEAL_TWIN_SISTER_MIN_UM": "5.5",
    "BIOHUB_STEAL_TWIN_SISTER_MAX_UM": "11.0",
    "BIOHUB_STEAL_TWIN_DIVERGE_UM": "2.25",
    "BIOHUB_STEAL_TWIN_TWIN_MAX_UM": "5.0",
    "BIOHUB_STEAL_TWIN_REQUIRE_TWO_SUCCESSORS": "1",
    "BIOHUB_STEAL_TWIN_REJECT_SYNTHETIC": "1",
    "BIOHUB_STEAL_TWIN_DEEPCENTER_VETO": "1",
    "BIOHUB_STEAL_TWIN_FRAME_CAP_ABS": "1",
    "BIOHUB_STEAL_TWIN_VIDEO_CAP_ABS": "2",
    "BIOHUB_STEAL_TWIN_DEBUG_JSONL": "",
    "BIOHUB_STEAL_TWIN_DEBUG_MAX_RECORDS": "200",
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

# Alias so the base1 profile reads explicitly next to the other profiles.
BASE1_PRESET: dict[str, str] = PRESET

# ---------------------------------------------------------------------------
# E23 preset: the submitted E23 notebook's effective post-processing
# settings (public LB 0.924), per the E23 parity contract in
# analysis/gold_loop_protocol.md. Layered on CODE_DEFAULTS only -- never on
# the base1 preset -- so anything unset here falls back to the notebook's
# "constants" cell values, not to base1's overrides. Values that equal
# CODE_DEFAULTS are kept explicit so this dict alone documents the profile.
# ---------------------------------------------------------------------------
E23_PRESET: dict[str, str] = {
    "BIOHUB_MOTION_RELINK_LEARNED_BONUS": "1.0",
    "BIOHUB_GAP_CLOSE_MAX_GAP": "2",
    "BIOHUB_GAP_CLOSE_UM": "5.8",
    "BIOHUB_GAP_DENSITY_ADAPTIVE": "1",
    "BIOHUB_GAP_DENSITY_REFERENCE_UM": "6.5",
    "BIOHUB_GAP_DENSITY_GAIN": "0.040",
    "BIOHUB_GAP_DENSITY_MAX_STEP_DELTA_UM": "0.125",
    "BIOHUB_GAP_DENSITY_NEIGHBORS": "3",
    "BIOHUB_OUTPUT_FILTER_SHORT_TRACKS": "1",
    "BIOHUB_OUTPUT_MIN_TRACK_LEN": "6",
    "BIOHUB_OUTPUT_KEEP_DIVISION_COMPONENTS": "1",
    "BIOHUB_OUTPUT_GAP2_RECOVERY": "0",
    "BIOHUB_ADAPTIVE_SHORT_TRACK_RESCUE": "0",
    "BIOHUB_SAFE_DIV_MAX_UM": "8.0",
    "BIOHUB_SAFE_DIV_SISTER_MAX_UM": "11.0",
    "BIOHUB_SAFE_DIV_EXISTING_CHILD_MAX_UM": "10.0",
    "BIOHUB_SAFE_DIV_FRAME_FRAC_CAP": "0.0076",
    "BIOHUB_SAFE_DIV_GLOBAL_FRAC_CAP": "0.00375",
    "BIOHUB_SAFE_DIV_MODE": "e23",
    "BIOHUB_SAFE_DIV_REQUIRE_MID_TRACK_PARENT": "1",
    "BIOHUB_SAFE_DIV_REQUIRE_MUTUAL_NN": "1",
    "BIOHUB_SAFE_DIV_REQUIRE_DIVERGENCE": "1",
    "BIOHUB_SAFE_DIV_DIVERGE_UM": "2.25",
    "BIOHUB_REFINE_ALL_CENTROIDS": "1",
    "BIOHUB_REFINE_CENTROIDS_WIN_Z": "1",
    "BIOHUB_REFINE_CENTROIDS_WIN_YX": "3",
    "BIOHUB_REFINE_CENTROIDS_BASELINE_PERCENTILE": "20.0",
    "BIOHUB_REFINE_CENTROIDS_MAX_SHIFT_UM": "2.8",
    "BIOHUB_USE_DEEPCENTER_VETO": "1",
    "BIOHUB_REQUIRE_DEEPCENTER_VETO": "1",
    "BIOHUB_DEEPCENTER_EXPECTED_EPOCH": "2",
    "BIOHUB_DEEPCENTER_GAP_VETO": "1",
    "BIOHUB_DEEPCENTER_GAP_THRESHOLD": "0.25",
    "BIOHUB_DEEPCENTER_GAP_CONFIRM_MIN_SPAN_UM": "8.5",
    "BIOHUB_DEEPCENTER_SAFE_DIV_VETO": "1",
    "BIOHUB_DEEPCENTER_SAFE_DIV_THRESHOLD": "0.12",
    "BIOHUB_DEEPCENTER_RELATIVE": "weights/full_frame_center/best.pt",
    "BIOHUB_DEEPCENTER_CHECKPOINT": (
        "/kaggle/input/biohub-deepcenter-unet3d-center-prior-v1/weights/full_frame_center/best.pt"
    ),
    "BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT": (
        "/kaggle/input/biohub-deepcenter-unet3d-center-prior-v1/weights/full_frame_center/best.pt"
    ),
    "BIOHUB_EXPERIMENT_TAG": "e23_pub923_parity",
}

TWIN_ONLY_V1_PRESET: dict[str, str] = {
    **E23_PRESET,
    "BIOHUB_OUTPUT_STEAL_TWIN_REWIRE": "1",
    "BIOHUB_STEAL_TWIN_MODE": "twin_only_v1",
    "BIOHUB_STEAL_TWIN_DRY_RUN": "0",
    "BIOHUB_STEAL_TWIN_PARENT_MAX_UM": "8.0",
    "BIOHUB_STEAL_TWIN_EXISTING_CHILD_MAX_UM": "10.0",
    "BIOHUB_STEAL_TWIN_SISTER_MIN_UM": "5.5",
    "BIOHUB_STEAL_TWIN_SISTER_MAX_UM": "11.0",
    "BIOHUB_STEAL_TWIN_DIVERGE_UM": "2.25",
    "BIOHUB_STEAL_TWIN_TWIN_MAX_UM": "5.0",
    "BIOHUB_STEAL_TWIN_REQUIRE_TWO_SUCCESSORS": "1",
    "BIOHUB_STEAL_TWIN_REJECT_SYNTHETIC": "1",
    "BIOHUB_STEAL_TWIN_DEEPCENTER_VETO": "1",
    "BIOHUB_STEAL_TWIN_FRAME_CAP_ABS": "1",
    "BIOHUB_STEAL_TWIN_VIDEO_CAP_ABS": "2",
    "BIOHUB_STEAL_TWIN_DEBUG_JSONL": "",
    "BIOHUB_STEAL_TWIN_DEBUG_MAX_RECORDS": "200",
    "BIOHUB_EXPERIMENT_TAG": "e23_twin_only_v1",
}

# Named post-processing profiles: profile name -> preset layered on top of
# CODE_DEFAULTS by build_config. Adding a profile never changes base1.
PROFILES: dict[str, dict[str, str]] = {
    "base1": BASE1_PRESET,
    "e23": E23_PRESET,
    "e23_twin_only_v1": TWIN_ONLY_V1_PRESET,
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

    # All-node intensity-centroid refinement (E23 parity; inert in base1).
    REFINE_ALL_CENTROIDS: bool
    REFINE_CENTROIDS_WIN_Z: int
    REFINE_CENTROIDS_WIN_YX: int
    REFINE_CENTROIDS_BASELINE_PERCENTILE: float
    REFINE_CENTROIDS_MAX_SHIFT_UM: float

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
    # Structural safe-division gates (E23 parity; inert in base1).
    # SAFE_DIV_MODE selects the candidate-generation semantics: "legacy"
    # (current port) or "e23" (notebook structural gates).
    # REQUIRE_MUTUAL_NN / REQUIRE_DIVERGENCE mirror the notebook env vars
    # BIOHUB_SAFE_DIV_REQUIRE_MUTUAL_NN / BIOHUB_SAFE_DIV_REQUIRE_DIVERGENCE
    # exactly; the submitted notebook hardwires both gates, so the e23
    # preset enables them (and REQUIRE_MID_TRACK_PARENT, its C1 gate).
    SAFE_DIV_MODE: str
    SAFE_DIV_REQUIRE_MID_TRACK_PARENT: bool
    SAFE_DIV_REQUIRE_MUTUAL_NN: bool
    SAFE_DIV_REQUIRE_DIVERGENCE: bool
    SAFE_DIV_DIVERGE_UM: float

    OUTPUT_STEAL_TWIN_REWIRE: bool
    STEAL_TWIN_MODE: str
    STEAL_TWIN_DRY_RUN: bool
    STEAL_TWIN_PARENT_MAX_UM: float
    STEAL_TWIN_EXISTING_CHILD_MAX_UM: float
    STEAL_TWIN_SISTER_MIN_UM: float
    STEAL_TWIN_SISTER_MAX_UM: float
    STEAL_TWIN_DIVERGE_UM: float
    STEAL_TWIN_TWIN_MAX_UM: float
    STEAL_TWIN_REQUIRE_TWO_SUCCESSORS: bool
    STEAL_TWIN_REJECT_SYNTHETIC: bool
    STEAL_TWIN_DEEPCENTER_VETO: bool
    STEAL_TWIN_FRAME_CAP_ABS: int
    STEAL_TWIN_VIDEO_CAP_ABS: int
    STEAL_TWIN_DEBUG_JSONL: str
    STEAL_TWIN_DEBUG_MAX_RECORDS: int

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


def build_config(
    overrides: dict[str, str] | None = None,
    test_dir: Path | str = Path("data/test"),
    profile: str = "base1",
) -> PostprocConfig:
    """Build a :class:`PostprocConfig` the same way the notebook builds its constants.

    Resolution order (last wins), mirroring "preset cell overwrites
    os.environ, constants cell reads os.environ.get(name, hardcoded)":
    ``CODE_DEFAULTS`` -> the named profile's preset (:data:`PROFILES`;
    ``base1`` is :data:`PRESET`, ``e23`` is :data:`E23_PRESET`) ->
    ``overrides`` (``--set``). Positional arguments are unchanged, so
    existing callers keep building the byte-for-byte ``base1`` config.

    Raises :class:`ValueError` for an unknown ``profile`` or an invalid
    ``BIOHUB_SAFE_DIV_MODE`` override, and :class:`KeyError` for unknown
    override keys.
    """
    try:
        preset = PROFILES[profile]
    except KeyError:
        raise ValueError(f"unknown profile {profile!r}; expected one of {sorted(PROFILES)}") from None

    env: dict[str, str] = dict(CODE_DEFAULTS)
    env.update(preset)
    if overrides:
        unknown = sorted(set(overrides) - set(CODE_DEFAULTS))
        if unknown:
            raise KeyError(f"unknown BIOHUB_* override key(s): {unknown}")
        env.update(overrides)

    safe_div_mode = _get_str(env, "BIOHUB_SAFE_DIV_MODE")
    if safe_div_mode not in ("legacy", "e23"):
        raise ValueError(f"BIOHUB_SAFE_DIV_MODE must be 'legacy' or 'e23', got {safe_div_mode!r}")

    output_steal_twin_rewire = _get_bool(env, "BIOHUB_OUTPUT_STEAL_TWIN_REWIRE")
    steal_twin_values: dict[str, object] = {
        "STEAL_TWIN_MODE": _get_str(env, "BIOHUB_STEAL_TWIN_MODE"),
        "STEAL_TWIN_PARENT_MAX_UM": _get_float(env, "BIOHUB_STEAL_TWIN_PARENT_MAX_UM"),
        "STEAL_TWIN_EXISTING_CHILD_MAX_UM": _get_float(env, "BIOHUB_STEAL_TWIN_EXISTING_CHILD_MAX_UM"),
        "STEAL_TWIN_SISTER_MIN_UM": _get_float(env, "BIOHUB_STEAL_TWIN_SISTER_MIN_UM"),
        "STEAL_TWIN_SISTER_MAX_UM": _get_float(env, "BIOHUB_STEAL_TWIN_SISTER_MAX_UM"),
        "STEAL_TWIN_DIVERGE_UM": _get_float(env, "BIOHUB_STEAL_TWIN_DIVERGE_UM"),
        "STEAL_TWIN_TWIN_MAX_UM": _get_float(env, "BIOHUB_STEAL_TWIN_TWIN_MAX_UM"),
        "STEAL_TWIN_REQUIRE_TWO_SUCCESSORS": _get_bool(env, "BIOHUB_STEAL_TWIN_REQUIRE_TWO_SUCCESSORS"),
        "STEAL_TWIN_REJECT_SYNTHETIC": _get_bool(env, "BIOHUB_STEAL_TWIN_REJECT_SYNTHETIC"),
        "STEAL_TWIN_DEEPCENTER_VETO": _get_bool(env, "BIOHUB_STEAL_TWIN_DEEPCENTER_VETO"),
        "STEAL_TWIN_FRAME_CAP_ABS": _get_int(env, "BIOHUB_STEAL_TWIN_FRAME_CAP_ABS"),
        "STEAL_TWIN_VIDEO_CAP_ABS": _get_int(env, "BIOHUB_STEAL_TWIN_VIDEO_CAP_ABS"),
        "STEAL_TWIN_DEBUG_MAX_RECORDS": _get_int(env, "BIOHUB_STEAL_TWIN_DEBUG_MAX_RECORDS"),
    }
    frozen_steal_twin_values: dict[str, object] = {
        "STEAL_TWIN_MODE": "twin_only_v1",
        "STEAL_TWIN_PARENT_MAX_UM": 8.0,
        "STEAL_TWIN_EXISTING_CHILD_MAX_UM": 10.0,
        "STEAL_TWIN_SISTER_MIN_UM": 5.5,
        "STEAL_TWIN_SISTER_MAX_UM": 11.0,
        "STEAL_TWIN_DIVERGE_UM": 2.25,
        "STEAL_TWIN_TWIN_MAX_UM": 5.0,
        "STEAL_TWIN_REQUIRE_TWO_SUCCESSORS": True,
        "STEAL_TWIN_REJECT_SYNTHETIC": True,
        "STEAL_TWIN_DEEPCENTER_VETO": True,
        "STEAL_TWIN_FRAME_CAP_ABS": 1,
        "STEAL_TWIN_VIDEO_CAP_ABS": 2,
        "STEAL_TWIN_DEBUG_MAX_RECORDS": 200,
    }
    if output_steal_twin_rewire:
        for name, expected in frozen_steal_twin_values.items():
            actual = steal_twin_values[name]
            if actual != expected:
                raise ValueError(f"BIOHUB_{name} must equal frozen twin_only_v1 value {expected!r}, got {actual!r}")

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
        REFINE_ALL_CENTROIDS=_get_bool(env, "BIOHUB_REFINE_ALL_CENTROIDS"),
        REFINE_CENTROIDS_WIN_Z=_get_int(env, "BIOHUB_REFINE_CENTROIDS_WIN_Z"),
        REFINE_CENTROIDS_WIN_YX=_get_int(env, "BIOHUB_REFINE_CENTROIDS_WIN_YX"),
        REFINE_CENTROIDS_BASELINE_PERCENTILE=_get_float(env, "BIOHUB_REFINE_CENTROIDS_BASELINE_PERCENTILE"),
        REFINE_CENTROIDS_MAX_SHIFT_UM=_get_float(env, "BIOHUB_REFINE_CENTROIDS_MAX_SHIFT_UM"),
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
        SAFE_DIV_MODE=safe_div_mode,
        SAFE_DIV_REQUIRE_MID_TRACK_PARENT=_get_bool(env, "BIOHUB_SAFE_DIV_REQUIRE_MID_TRACK_PARENT"),
        SAFE_DIV_REQUIRE_MUTUAL_NN=_get_bool(env, "BIOHUB_SAFE_DIV_REQUIRE_MUTUAL_NN"),
        SAFE_DIV_REQUIRE_DIVERGENCE=_get_bool(env, "BIOHUB_SAFE_DIV_REQUIRE_DIVERGENCE"),
        SAFE_DIV_DIVERGE_UM=_get_float(env, "BIOHUB_SAFE_DIV_DIVERGE_UM"),
        OUTPUT_STEAL_TWIN_REWIRE=output_steal_twin_rewire,
        STEAL_TWIN_MODE=str(steal_twin_values["STEAL_TWIN_MODE"]),
        STEAL_TWIN_DRY_RUN=_get_bool(env, "BIOHUB_STEAL_TWIN_DRY_RUN"),
        STEAL_TWIN_PARENT_MAX_UM=float(steal_twin_values["STEAL_TWIN_PARENT_MAX_UM"]),
        STEAL_TWIN_EXISTING_CHILD_MAX_UM=float(steal_twin_values["STEAL_TWIN_EXISTING_CHILD_MAX_UM"]),
        STEAL_TWIN_SISTER_MIN_UM=float(steal_twin_values["STEAL_TWIN_SISTER_MIN_UM"]),
        STEAL_TWIN_SISTER_MAX_UM=float(steal_twin_values["STEAL_TWIN_SISTER_MAX_UM"]),
        STEAL_TWIN_DIVERGE_UM=float(steal_twin_values["STEAL_TWIN_DIVERGE_UM"]),
        STEAL_TWIN_TWIN_MAX_UM=float(steal_twin_values["STEAL_TWIN_TWIN_MAX_UM"]),
        STEAL_TWIN_REQUIRE_TWO_SUCCESSORS=bool(steal_twin_values["STEAL_TWIN_REQUIRE_TWO_SUCCESSORS"]),
        STEAL_TWIN_REJECT_SYNTHETIC=bool(steal_twin_values["STEAL_TWIN_REJECT_SYNTHETIC"]),
        STEAL_TWIN_DEEPCENTER_VETO=bool(steal_twin_values["STEAL_TWIN_DEEPCENTER_VETO"]),
        STEAL_TWIN_FRAME_CAP_ABS=int(steal_twin_values["STEAL_TWIN_FRAME_CAP_ABS"]),
        STEAL_TWIN_VIDEO_CAP_ABS=int(steal_twin_values["STEAL_TWIN_VIDEO_CAP_ABS"]),
        STEAL_TWIN_DEBUG_JSONL=_get_str(env, "BIOHUB_STEAL_TWIN_DEBUG_JSONL"),
        STEAL_TWIN_DEBUG_MAX_RECORDS=int(steal_twin_values["STEAL_TWIN_DEBUG_MAX_RECORDS"]),
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
```

## Parent-only verification after complete code review

From the approved worktree, using existing canonical tools (no install):

```sh
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 /Users/taichi/コンペティション/Kaggle/biohub-cell-tracking/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_e26_screen.py tests/test_e26_motion_relink_contract.py tests/test_public_postproc.py
/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking/.venv/bin/ruff check --no-cache src/biohub/e26_screen.py tests/test_e26_screen.py
```

Parent and independent SOL review every change for full contract coverage before
integration. A passing config-only suite is not unit02b completion, an E26
accuracy result, permission to read GT, or permission to submit.
