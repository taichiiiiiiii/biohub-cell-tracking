# E26 unit03 — GT-free generation contract

2026-09-06 / Parent design SHIP after independent SOL review (07:05 UTC).
Not a worker dispatch or physical-run authorization.
Prerequisite: unit02 accepted and integrated. Candidate, split and gates remain
exactly those in [E26 design](e26_motion_relink_off_design.md).
The parent owns this design; the user-designated Qwen implements; independent SOL
reviews code and tests. No Cloud on unattended goal continuations.

Accepted cross-process handoff: [runner interface](e26_runner_interface.md).
Unit04 writes private GT binding first and a GT-path-free public completion
receipt last, in a separate canonical preregistration artifact namespace. Unit03
checks the public receipt and opaque private-artifact bytes against both parent
dispatch digests, never deserializes the private GT inventory or opens GT trees.
Child controls remain generation-only. A failed child produces a failure receipt,
never a generation seal. Include the accepted interface in scientific source pins.

## Scope and verified reuse

Extend `src/biohub/e26_screen.py` and its tests; add `scripts/e26_screen.py`.
Keep existing post-processing, `official/`, E25/ST-R3, AGENTS and launchers unchanged.
No E25/ST-R3 runtime imports, private helper reuse, old seals or adoption labels.
No training, GT scoring, downloads, Kaggle calls, submission, or dependency installs.

Verified committed APIs:

- `run_postproc_core(geff_paths, out_csv, cfg, *, deepcenter_loader,
  dataset_start_hook, dataset_finish_hook, raw_stats_hook,
  write_run_stats_output=False, exclusive_output=True)` preserves explicit order.
  Start/finish hooks take `(sequence, dataset)`; raw-stats hook receives a mapping.
- `load_deepcenter_veto_detector_strict(cfg, checkpoint_path, manifest_path)`
  returns `(bundle, receipt)`. Load once, then inject a loader taking only `cfg`
  that checks identity and returns the bundle. Never pass the tuple to core.
  Existing strict receipt is supporting evidence, not an ST-R3 certificate.
- `open_volume(image_path)` reads shape/scale metadata without image decoding.
  `validate_submission(frame, explicit_shapes)` checks bounds and graph structure.
  Avoid `validate_csv(..., data/train)`: its shape discovery includes unrelated
  videos. Supply shapes only for the literal selected image paths.

## Three sequential fresh children

Order: `public4_parity` → `baseline` → `candidate`. No dry-run arm.
Public4 order: `44b6_0113de3b`, `44b6_0b24845f`, `6bba_05b6850b`, `6bba_05db0fb1`.
Other arms use unit02's literal EVAL12 + EVAL24 order. Do not discover/sort videos.
Build all configs with accepted unit02 API; assert full exact-E23 pair contract.
Both 36 arms use the same image-root string, weights and raw paths.

Reuse existing canonical inputs without copying datasets or making another worktree:

- raw4: `outputs/kaggle/e22_bidir030_public4_raw/tracking_repo/predictions/unknown/unet_transformer/split_0`
- raw36: `outputs/kaggle/e22_bidir030_eval36_raw/tracking_repo/predictions/unknown/unet_transformer_val/split_0`
- images: selected `.zarr` roots under `data/test` or `data/train`, respectively.
- weights: `outputs/kaggle/e23_artifacts/pilkwang/biohub-deepcenter-unet3d-center-prior-v1/weights/full_frame_center/best.pt`
- manifest: same artifact root's `ARTIFACT_MANIFEST.json`.
- parity reference: `outputs/kaggle/e23_reference/submission.csv`, pinned SHA
  `33c179b0449b9cdd186f06a653cddc8cf12359f008982f6713cdf30784a52e6a`.

Paths above locate evidence, not proof of its current contents. Before a physical
run, bind current bytes to the existing raw/image acquisition manifests and the
public4 pins in `e23_parity_runbook.md`. Strict loader retains its fixed weight/
manifest hashes and epoch2. No new artifact, relaxed hash or fallback discovery.
Public4 fresh CSV must equal pinned reference bytes before either 36 child starts.
Do not score public4 or interpret its parity as accuracy on unseen data.

## Inputs, process boundary and artifacts

Parent creates a new run exclusively under canonical `outputs/local/e26_screen/`.
Reject invalid IDs, existing run/arm paths and output aliases to inputs; do not
resume, overwrite, clean up failed output, or recreate an interrupted arm.
Write JSON with `allow_nan=False`, exclusive creation, flush/fsync and byte hashes.
Record partial logs/errors separately; only complete successful children may be sealed.

Generation child receives a generation-only control file and its expected hash:
explicit ordered raw/image paths, config, fixed weight/manifest, output location,
source/dependency/input bindings and arm identity. No GT path/inventory, scoring
module/callback, whole experiment ledger or ambient credentials in child controls.
Images and GT currently share `data/train`; read selected `.zarr` paths only.
This is procedural separation, not OS-level invisibility or adversarial isolation.
Unit04 must prepare an opaque GT/scale binding before physical generation begins,
keep it outside child controls, and verify it again before staged scoring.

Use fresh Python children, explicit canonical script path/cwd and environment.
Pin `PYTHONHASHSEED=0`, empty `CUDA_VISIBLE_DEVICES`, locale C, timezone UTC and
OMP/OpenBLAS/MKL/NumExpr/VECLIB thread counts 1 before numerical imports.
Pin Python/NumPy/Torch seeds to 0 and Torch intra/inter-op counts to 1 in every
fresh child before model execution; record actual values, CPU receipt and dtype.
These are inference controls, not changes to the checkpoint's training seed.
No arbitrary BIOHUB overrides,
inherited auth/proxy settings, network calls or downloaded weights.
Separate child wall duration (including model load/validation) from core duration;
record self-process peak RSS in bytes with platform-specific conversion. Require
finite nonnegative durations/RSS and normal exit. Do not claim process-tree peak
RAM or approximately 200-video full-pipeline feasibility from these measurements.

Stream child stdout/stderr to exclusive files rather than buffering full output.
Wait for child termination and validate its receipt before the next starts; failures
or supervisor timeout stop the sequence and preserve evidence without retry.
Physical timeout/RAM budget is fixed separately before the first real run.

Historical sizing evidence, reread 2026-09-06 (not a new E26 measurement): E25 run
`outputs/local/kaggle_screen/e25_twin_screen_v2_20260905071008Z/generation/`
recorded public4 core 335.593199958 s / self peak RSS 4,395,270,144 B and baseline36
core 2,499.703610708 s / 4,467,179,520 B. Receipt SHA256s respectively:
`0ba4a02344ff02c2a24c903f405a795245ecb37a3e0216474bf1e819ca78df95` and
`4b360feaea2e7375a4f048e9b2756f9df4325dd6b466a04164de0873f5cdd005`.
Those old timers start after loading weights and exclude later CSV validation;
they are neither complete-child wall time nor a bound for the new candidate.
Use them only to size a reviewed physical budget with headroom, not as E26
runtime acceptance. E26's motion removal may also change downstream work.

## Validation and sealing

Reparse complete CSV: exact 10-column header, no duplicate columns/rows or missing
cells, global contiguous row IDs from zero, expected contiguous dataset blocks in
literal order, nodes before edges, integer numeric fields and correct -1 sentinels.
Integer fields are `id,node_id,t,z,y,x,source_id,target_id` (the existing writer
rounds coordinates to integers).
Require nonnegative unique node IDs per video; finite bounded t/ZYX; unique edge
pairs; same-video endpoints; t→t+1; in-degree ≤1 and out-degree ≤2. Allow a video
with nodes and zero edges. Invoke the existing structural validator with explicit
selected shapes after E26-specific checks. Never repair or silently drop bad rows.

Save full effective config, strict weight receipt, ordered raw statistics, start/
finish events, CSV counts/hash and timings per arm. Cross-check all dataset orders
and counts. Candidate's seven `motion_relink_*` counters must be zero; baseline
records enabled-stage behavior including replacement/fallback/large-frame skips.
Do not assume baseline replaced edges in every video, or require equal output graph
sizes. No E25 twin-only edge-preservation or division-TP gate applies here.
Core statistics contain integer counters and two finite ratios. The conditional
`gap_close_effective_max_gap` key may be absent: preserve this as explicit null
with an absence reason, not NaN or a fabricated zero. Require all seven motion
counters to be present nonnegative integers; a missing motion counter is ERROR.
Do not use pandas run-stats to normalize these records, since absent keys can
become NaN and its writer is nonexclusive.
Freeze the exact raw key set from the pinned core `new_stats()` keys plus
`dataset,raw_nodes,nodes,raw_edges,edges,division_like_sources,edge_to_node_ratio,
gap_added_nodes_frac`, with only `gap_close_effective_max_gap` optional on raw
input. Reject missing/extra keys, wrong types and wrong dataset order. Validate
raw values before adding the explicit optional-absence diagnostic. Count fields
are nonnegative integers excluding bool; `gap_density_step_delta_milli_sum` is a
signed integer accumulation and must not be subjected to the count lower bound.
Both ratios are finite nonnegative
numbers excluding bool. Cross-check nodes/edges/forks against reparsed CSV counts.
Require `motion_relink_tight_edges + motion_relink_relaxed_edges ==
motion_relink_edges`. With motion enabled, zero motion edges requires fallback=1,
positive motion edges requires fallback=0; fallback and skipped-large are 0/1.
Skipped-large requires zero motion edges and fallback=1. Fallback requires zero
replaced-raw edges; replacement count cannot exceed raw-edge count. These are
stage-specific consistency checks, not a requirement that all videos replace edges.

Inventory exact relevant source bytes including package initializers, new module/
CLI, io, validate, config/csv_out/deepcenter/divisions/frames/geometry/graph_ops/
pipeline, pyproject, lockfile and this scientific contract, together with pre/post
hashes of `analysis/e26_motion_relink_off_design.md`,
accepted `analysis/e26_unit02_task.md`, `analysis/kaggle_loop_protocol_v2.md` and
the final unit03 worker task. These documents must stay fixed during physical runs.
Record Git HEAD/dirty state honestly; preserve unrelated WIP. Pin Python/platform and installed numerical/
GEFF/graph/Torch dependency versions. Rehash selected complete input trees, source,
dependencies and weight/reference files before/after execution; reject drift.
Resolve legitimate existing input aliases explicitly and bind both selected names
and resolved content; reject broken links, cycles or unexpected file kinds.
Hash resolved regular files through stable pre/post file-stat checks. The direct
generation dependencies are NumPy, pandas, SciPy, blosc2, tracksdata, geff, Torch
and (for structural validation) Polars; also record installed transitive runtime
distribution versions. Do not import a scoring module just to reuse its hash helper.

Only after parity plus both complete validated 36 outputs and unchanged bindings,
emit an E26 generation seal binding control and all arm artifacts. It means
generation complete, not scored, accepted or submission-authorized. Unit04 verifies
all bindings again before any GT scoring; it never trusts seal presence alone.

## Synthetic acceptance and review outcome

Use tiny fixtures and fake children/loaders only during implementation. Test exact
order and no-overlap, parity mismatch preventing baseline, baseline failure
preventing candidate, config/input/source drift, strict-loader tuple/CPU handling,
CSV corruption cases above, unchanged valid zero-edge videos, wrong telemetry,
nonfinite timings, failure retention, existing-output rejection and incomplete/
old-schema seals. Test production entry cannot activate fixture hooks.

Independent SOL path diagnosis confirmed the source closure and existing APIs,
and identified the optional-statistics issue above. Independent design review
accepted the corrected scientific-document closure and exact statistics schema/
consistency checks: SHIP. Preserve these requirements in the bounded worker task.
Do not launch unit03 until unit02 is accepted.
