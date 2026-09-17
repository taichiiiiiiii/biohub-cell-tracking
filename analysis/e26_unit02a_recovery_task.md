# E26 unit02a — transport-recovery config implementation

Parent recovery design, 2026-09-06 08:46 UTC. Independent task and deployment
reviews are SHIP; parent accepts the recorded deployment/preflight checks.
One local recovery dispatch is authorized under the limits below. This document
does not authorize another attempt after that dispatch ends.

The prior unit02a failed with SSE idle timeout and no saved code. Its task and
log are preserved. This proposed attempt retains the exact config APIs, allowed
files, pure behavior and acceptance tests from that task; the body below is
unchanged. No scientific hypothesis, split, gate or submission authority changes.

Parent prerequisites before dispatch: verify the accepted liveness repair is
deployed, bridge/backend state and implementation queue are suitable, exact
approved worktree is clean/unlocked on its expected branch/HEAD, and task,
launcher, provider, queue, native client and deployed repair bytes are recorded.
If any prerequisite is absent, do not launch or switch models.

After the parent explicitly accepts those checks, allow one bounded local-Flash
attempt through the unchanged default launcher. No --interactive, --cloud-only,
Cloud, other model/provider, purchase or reset. Request/stream retries stay zero.
The total supervisor cap is 45 minutes from launch, including queue time, with
no extension. Failure or timeout preserves partial evidence and ends this attempt;
do not restart automatically. The repair does not prove useful model progress.

## Authoritative context and bounded reads

The stdin task is the complete E26 specification for this small unit. It is not
stored inside the clean implementation worktree: do not search for it there.
Read worktree `AGENTS.md` and obey the launcher's fixed routing/safety policy.
The only other necessary source read is
`src/biohub/public_postproc/config.py` lines 438–470 for the existing public API.
Do not print the whole config, list directories, search analysis/docs, or search
the repository for E26. Parent/launcher already verified target/branch/clean state.
Proceed to apply_patch and focused tests; report a concrete missing contract
instead of exploring unrelated history. Do not repeatedly rewrite passing work.

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

Use existing absolute canonical interpreter and Ruff, not an environment install:
`/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking/.venv/bin/python`
and the adjacent `.venv/bin/ruff`.
Run PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider on
`tests/test_e26_screen.py`, `tests/test_e26_motion_relink_contract.py` and
`tests/test_public_postproc.py` together. Run Ruff check --no-cache on the two new
files. Report exact results and changed files, then stop. Parent and independent
SOL review the complete diff and rerun checks before any integration.
