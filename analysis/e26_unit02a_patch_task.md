# E26 unit02a — patch-authoring handoff

2026-09-06. Scientific handoff and role division independently reviewed SHIP at
draft SHA6b359d34e937a390b7ef0704942fdf255cc274dffe88b8627cdf46bb6edfd938.
Parent allocates one conditional local-only attempt below; dispatch still requires
exact launcher acceptance and preflight. This is a new operational handoff, not a
restart of recovery1. Preserve all earlier tasks and logs.

## Execution responsibility

Qwen authors both complete files using apply_patch. Shell execution is disabled:
do not call shell, exec_command, write_stdin, another agent/model or request an
alternative executor. Do not explore the repository or use view_image to read
unrelated material. Use the complete specification and inline reference below.
The parent verified the clean approved worktree; obey its automatically supplied
AGENTS and the launcher's fixed routing/safety policy. Historical routing in
AGENTS does not override the current fixed local-only launch policy.

Unlike the frozen recovery task, the worker does NOT execute pytest or Ruff.
Author all required tests, then report changed files, tests NOT RUN, remaining
uncertainties and rollback (the two newly created files only; do not delete).
Never claim tests passed. Parent reads complete source/tests BEFORE running the
unchanged full test commands below; independent SOL acceptance is also required.
This changes test-execution responsibility only, not scientific authorship,
scope, acceptance criteria, source ownership or test coverage.

No Cloud, --interactive, --cloud-only, PAYG, purchases, resets, fallback or
automatic retry. Parent budget: one local-only attempt,1200 seconds from launcher
start including queue time, no extension. This bounded attempt tests whether the
accepted removal of shell exploration enables actual code/test authorship; it
does not extend or resume recovery1. Before dispatch, parent must record accepted
task/configuration hashes and verify service/queue suitability and the clean,
unlocked approved worktree identity. If exact launcher review or any preflight is
unresolved, do not launch. Timeout sends SIGINT to the owned launcher; preserve
partial files/log and verify worker closure before releasing any retained lock.
No second attempt or route change is authorized by this handoff.

## Files and API

Only create `src/biohub/e26_screen.py` and `tests/test_e26_screen.py` in the
one approved worktree. No edits to existing source/tests, official/, AGENTS,
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

## Inline source reference (do not reimplement)

Import PostprocConfig and build_config from biohub.public_postproc.config.
PostprocConfig is the existing dataclass; inspect all fields via dataclasses.fields
at runtime without reading files. Do not copy the preset or invent field values.
The excerpt below is a partial read-only reference to the existing function,
not a complete replacement function to paste into the new module.

Source: src/biohub/public_postproc/config.py lines438–470.
Complete source file SHA-256:
415a586ad4d8a81b96314025fa0cf05ce6c797df7ef8eb75e53f48efe192d882
Canonical and approved worktree bytes matched before handoff creation.

```python
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
