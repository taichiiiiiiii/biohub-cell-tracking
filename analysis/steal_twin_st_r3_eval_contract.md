# ST-R3 binding contract: immutable official evaluation and feasibility harness

Updated: 2026-08-31 (Asia/Tokyo)

This document is the binding design for ST-R3. It is read with
[`steal_twin_design.md`](steal_twin_design.md),
[`steal_twin_st_r1_contract.md`](steal_twin_st_r1_contract.md), and
[`gold_loop_protocol.md`](gold_loop_protocol.md). The staged metric thresholds
and causal candidate remain those in `steal_twin_design.md`; this document
specifies how to produce, seal, score, and promote the artifacts without
silently changing those thresholds.

ST-R3 is post-processing-only. Reuse of the exact legacy E23 raw prediction
bundle and exact reviewed DeepCenter checkpoint has separate provenance and is
`NOT_APPLICABLE_POSTPROCESS_ONLY`; it is not a retrospective PASS under
[`training_loss_gate.md`](training_loss_gate.md). Any drift in a live model or
checkpoint invalidates `twin_only_v1` rather than being silently loss-gated as
the same candidate. A newly trained or warm-started model must first pass the
training-loss gate and then enter a separately named/preregistered candidate.

## Authority, scope, and non-goals

- `official/` is a read-only Git submodule. Never modify it.
- The only adoption metric is the direct official path used by
  `src/biohub/evaluate.py`: official `evaluate`, `per_sample_metrics`, and
  `summarise` with `max_distance=7.0` micrometres.
- ST-R3 may implement a local harness and tests. It does not change the twin
  motif, radii, veto, sort, caps, mutation, checkpoint, model, or E23 defaults.
- ST-R3 does not run or submit a Kaggle notebook, create a competition
  submission, choose final submissions, or use the public leaderboard.
- The four public-dummy videos are parity diagnostics only. Their stems,
  graphs, scores, or telemetry must never enter an ST-R3 adoption artifact.
- No notebook proxy score, handwritten micro-average, or rounded display value
  may decide a gate.

Current data status is **NOT_READY**. Active download progress does not change
that status. Only a new, completed, hash-pinned latest-verifier receipt covering
the final image-tree checks and the content-hash gate below may transition it
to READY; preregistration records that receipt's timestamp and SHA-256. ST-R4
prediction or scoring is forbidden while the latest receipt says NOT_READY or
is absent/stale.

The official submodule trust check is fail-closed: its checked-out `HEAD` must
equal the superproject gitlink, its working tree must be clean, and both values
must be recorded. At the time this contract was drafted both are
`075fc5f5a52d11077f9dc2b074644618f26939e2`; a different value requires an
explicit metric review and a new preregistration, not an automatic update.

## Dependency boundary: do not invent an R1b/R2 API

ST-R3 never calls the R1b planner directly. A thin production runner adapter
must bind to the reviewed, final ST-R2 public pipeline or CLI and expose the
following semantic contract:

```text
run_arm(arm_spec, fresh_output_dir, dataset_event_sink) -> arm_receipt
```

The spelling and Python type of that function are deliberately not binding.
They are selected only after the actual ST-R2 interface exists. The adapter
must have one explicit production binding; reflection, signature guessing,
multiple fallback call paths, and test-only monkeypatches in production are
forbidden. Unit tests use a fake adapter.

The semantic inputs and outputs below are provisional requirements, not a
claim that the R2 interface already supplies named artifacts. After R2 lands,
SOL must enumerate in a reviewed adapter appendix the exact entry point,
arguments, emitted filenames, schema versions, and every live field consumed
by ST-R3. That appendix and its code-commit hash become preregistration inputs.
Until it exists, status is `HOLD_INTERFACE_INCOMPLETE`.

The semantic inputs and outputs are binding:

- input: arm name, frozen profile/effective config, sorted 36-stem set, raw
  GEFF directory, image-only directory, the exact DeepCenter
  checkpoint/manifest paths, post-R2-appendix-enumerated non-model live
  artifacts, output paths, and a dataset start/finish event sink;
- output: process exit status, exact effective config, ordered dataset list,
  submission CSV, run-stats CSV, optional bounded debug JSONL, per-video timing
  events, and the final ST-R2 telemetry/conservation fields;
- the runner receives no GT path, GT graph, metric row, prior stage score, gate
  result, or callback capable of reading them;
- the authoritative arm is a fresh operating-system process. Importing the
  final pipeline into the long-lived scorer process is not an equivalent
  production binding.

If the final ST-R2 runner cannot emit unambiguous dataset start/finish events,
or cannot expose the exact effective config and telemetry, the runtime gate is
`HOLD_INTERFACE_INCOMPLETE`. Do not infer per-video timing from log prose and
do not invent planner internals in ST-R3 to work around it.

Before preregistration, the exact candidate code commit must also have two
hash-pinned prerequisite receipts:

- E23 public-four notebook-oracle parity: exact reference/input hashes, command,
  source commit/tree hash, node IDs, rounded coordinates, directed edges,
  forks, common telemetry, CSV bytes, and PASS;
- base1 non-regression: exact reference/input hashes, command, the same source
  commit/tree hash, byte-identical CSV/graph/common telemetry, and PASS.

These receipts are code-safety prerequisites only. The ST-R3 run stores only
their receipt SHA-256s and verdicts. It must not copy public-four CSVs, stems,
official rows/scores, or telemetry into generation, score, delta, gate, or
adoption artifacts. The scoring entry point rejects every public-four stem.

## Frozen datasets and disclosure

The ordered eval12 set is exactly:

```text
44b6_12dfb391 44b6_267148e4 44b6_2a2eff9f 44b6_341df25f
44b6_587a1e22 44b6_5f15d135 6bba_062c8d37 6bba_07e24132
6bba_085bf656 6bba_09961292 6bba_0e7c0d07 6bba_12665c0e
```

The ordered eval24 set is exactly:

```text
44b6_706092f0 44b6_74d0c52e 44b6_7a302da0 44b6_996155de
44b6_9be80b04 44b6_a21120c2 44b6_aaf8b0ea 44b6_c50204e0
44b6_c8e2a523 44b6_d2f34f90 44b6_d5e7d891 44b6_d754aa59
6bba_1d0d8384 6bba_207c6aaf 6bba_20852818 6bba_2312ac41
6bba_268e1230 6bba_2819ca14 6bba_32db13fc 6bba_337b1b3a
6bba_3abfe10a 6bba_3c5691b6 6bba_3db54e20 6bba_3fda6b25
```

`eval36` is the ordered concatenation `eval12 + eval24`. Assert 36 unique
stems, an empty intersection, exactly 18 `44b6` and 18 `6bba` stems, and no
public-four stem. These sets have influenced prior analysis. Eval12 and eval24
are staged retrospective falsification sets, not holdouts; eval36 is their
roll-up, not a third independent validation set.

## Label-blind state machine

The harness is an append-only state machine. Each transition consumes and
hash-pins the preceding stage manifest.

```text
PREREGISTERED
  -> GENERATION_SEALED
  -> FEASIBILITY_PASS
  -> EVAL12_PASS
  -> EVAL24_PASS
  -> EVAL36_ADOPTION_CANDIDATE
```

Every failure has a terminal state. No command may skip a state or reopen a
terminal run directory.

1. **Preregister.** Freeze code, official scorer, candidate, configs, data,
   artifacts, commands, environment, target resource limits, gates, and
   output schema before generation or GT access.
2. **Generate and seal all 36 label-blind outputs.** Run one untimed safety
   dry-run, then the preregistered mirrored primary pairs `AB` and `BA`, where
   `A=baseline` and `B=candidate`. Validate all five arm executions and seal
   their bytes. No official metric module is imported and no GT path is
   accepted by an arm or generation entry point in this phase. A separate
   integrity scanner may have streamed opaque GT bytes to establish a
   preregistered content hash; it must not parse or score them.
3. **Feasibility.** Decide parity, conservation, runtime, RSS, and hidden-200
   gates from the sealed generation artifacts. A miss stops before scoring.
4. **Eval12.** Materialize only the 12 mechanically filtered arm rows and read
   only those 12 GT graphs. A miss is terminal.
5. **Eval24.** Only after a recorded eval12 pass, materialize and score the
   remaining 24 rows from the already sealed full-36 submissions. No arm is
   regenerated. A miss is terminal.
6. **Eval36 roll-up.** Combine the stored eval12 and eval24 official per-video
   rows and call official `summarise`; do not reread/re-evaluate all 36 and do
   not treat the roll-up as a new dataset.

The generation implementation and scoring implementation must be separate
entry points. The generation entry point must not import `biohub.evaluate` or
`tracking_cellmot.metrics`. The scoring entry point accepts only a sealed
generation-manifest hash and a stage name. After any score file exists, the
harness must refuse regeneration in that run directory. Equality of the two
baseline outputs and the two candidate outputs selects no favorable run: any
byte/canonical-graph/plan disagreement is a deterministic-replay failure.

## Preregistration manifest

`PREREGISTRATION.json` is written canonically and atomically before arm output
directories exist. It contains at least:

- schema version, candidate ID `twin_only_v1`, immutable run ID, creation UTC,
  operator phase, and `training_gate_status=NOT_APPLICABLE_POSTPROCESS_ONLY`;
- superproject commit, clean tracked-tree assertion, exact hashes of the
  harness, `src/biohub/evaluate.py`, relevant public-postproc source, tests,
  `pyproject.toml`, and `uv.lock`;
- the exact-commit E23 notebook-oracle parity receipt hash, base1
  non-regression receipt hash, and reviewed post-R2 adapter appendix hash;
- official gitlink, submodule `HEAD`, clean-submodule assertion, and hashes of
  the imported official metric source files;
- Python/platform/architecture, dependency versions, CPU model/core count,
  physical RAM, device/dtype, and the exact execution working directory;
- exact argv arrays (never shell strings) and an environment allowlist. Record
  names and non-secret values; reject unknown `BIOHUB_*` variables. Never
  serialize credentials, tokens, or the full ambient environment;
- `PYTHONHASHSEED=0`, locale/timezone, thread controls, and device visibility;
- the eval12/eval24/eval36 lists and their canonical SHA-256 digests;
- raw prediction, image, GT, the only live checkpoint/manifest (DeepCenter),
  and raw-bundle primary/secondary provenance receipts described below;
- immutable-snapshot/exclusive-lock protocol and the complete pre/post arm
  hash inventory/reverification schema for raw/image/source/runtime/live files;
- complete baseline, dry-run, and candidate effective-config maps and their
  canonical hashes;
- the fixed untimed-safety plus mirrored `AB`/`BA` execution protocol, block
  order, conservative runtime/RSS statistic, direct-exec/RSS method, GT
  sandbox specification, inherited-FD allowlist, and negative canaries;
- every metric and feasibility threshold printed in this contract, including
  comparison direction and inclusive/exclusive boundary;
- non-null target-job declared RAM bytes, declared wall-time seconds, and a
  hash-pinned source/snapshot supporting those values;
- either an exact target-execution-class equivalence receipt or a reviewed,
  preregistered conservative time-calibration receipt/factor, including the
  exact prehash/cache/gap state and charged integrity-I/O rule; local ratios do
  not substitute for this absolute-runtime evidence;
- target-class/equivalent whole-cgroup memory receipt or validated
  conservative RSS calibration, with supervisor/container/descendant and
  quota-charged page-cache scope;
- the expected artifact paths/schema and all allowed nullable metric fields.

The run ID may include a timestamp for readability, but immutability comes
from the preregistration SHA-256. A run directory must be newly created and
must not already exist. Source must be committed and clean for all tracked
files. Ignored outputs are permitted only outside the new run directory and
must be listed as inputs if read.

## Input integrity and leakage boundary

### Raw predictions

The eval36 raw bundle must be exactly 36 `*.geff` roots, 1,188 files, and
10,090,215 bytes at the path recorded in `gold_loop_protocol.md`. Its stem set
must equal eval36. Record a canonical per-file `(relative_path, bytes, sha256)`
inventory and its digest. Reject symlinks, missing/extra roots, duplicate
logical paths, unreadable files, and any tree/hash drift.

### Images

The image gate in `eval36_image_resume_runbook.md` must pass first: manifest
SHA-256
`6c1c59644daf7fe59458dc860f2e1783d1217be389a791ea54e1f611f5f848f4`,
36 roots, 3,672 exact manifest files, 15,932,872,938 bytes, 102 files per root,
no missing/extra/size mismatch/symlink/partial marker, valid metadata JSON, and
a successful real-data decode smoke for every root. While still label-blind,
stream and SHA-256 **every one of the 3,672 regular files**, including every
locally consumed image chunk, exactly once to create the sealed canonical
`IMAGE_CONTENT_INVENTORY.json`. Each record contains stem, relative path,
bytes, and SHA-256. Its canonical digest is the local-byte identity pin.

Create an immutable/content-addressed input snapshot for the image tree, raw
GEFF tree, exact source/runtime, and every post-R2-enumerated live artifact; or
hold a reviewed exclusive writer lock over the exact inode trees for the whole
arm window. A read-only mount alone is insufficient if another host writer can
mutate the backing tree. Record snapshot identity or lock owner/scope/acquire/
release evidence in every arm receipt.

Immediately before **and immediately after** every safety/AB/BA arm, re-hash
every image, raw-GEFF, source/runtime, and live-artifact file visible to that
arm and compare every path/size/SHA-256 to the sealed inventories. Reject
missing/extra/symlink/special files and any pre- or post-arm drift. Store both
reverify receipt hashes, durations, and byte counts with the arm; an after-drift
invalidates the entire execution even when output hashes look valid. Do not
use a prior path/size-only scan as a substitute.

This proves that the complete bytes made available to the arm were identical
and stable across the bracketed execution. It does not prove which files or
chunks the program actually read. The competition manifest exposes no upstream
chunk checksums, so it also does not prove upstream authenticity; availability
identity, execution-window stability, actual-open audit, and upstream
authenticity are four separately labelled claims.

Before arm execution, construct a fresh, mechanically verified image-only view
whose visible dataset entries are exactly the 36 expected `.zarr` roots and no
GT `.geff`. A procedural path convention is insufficient for the binding ship
path. Each arm runs in an OS-enforced container/mount namespace with read-only
mounts for only the reviewed source/runtime, raw bundle, sealed image view, and
enumerated live artifacts, plus one fresh writable arm output. The mixed
`data/train`, GT views/files, host repo root, prior score directories, and
public-four data are not mounted. Network is disabled.

Close every inherited file descriptor before direct exec except standard
input/output/error and explicitly declared event/output descriptors; none may
refer to host/GT/prior-result files. Inside the sandbox, assert mount inventory
and negative canaries: each known host/GT path is absent, a preregistered GT
sentinel cannot be opened, `/proc`/process metadata cannot reveal an inherited
GT FD, and argv/environment contain no GT path. Audit the exact generation
code/path imports for GT/metric reads. If the platform cannot enforce and prove
this nonvisibility, status is `HOLD_GT_VISIBLE`; a code/path audit plus
procedural restraint alone cannot ship.

### GT and scorer

A dedicated, separate preregistration integrity scanner may stream opaque GT
files only to compute their canonical content inventory; it must not import the metric,
parse a GT graph, inspect counts/labels, or publish the GT path to an arm.
Actual GT graphs are first parsed in the relevant score stage. Before that
stage, verify the preregistered exact stage stem set, one readable GT GEFF per
stem, one scale-bearing Zarr per stem, and the canonical inventory hash. Store
GT inventory hashes in preregistration, but do not expose paths or contents to
an arm spec. This separation is a scientific leakage control, not an
operating-system security sandbox; the generation sandbox above is the binding
nonvisibility control.

### Model artifacts

The primary/secondary checkpoints are **not live ST-R3 arm inputs**: their
outputs are already embodied in the sealed raw GEFF bundle. Record their known
hashes only as raw-bundle provenance and do not mount or claim to load them.
The exact set of live files/fields consumed by post-processing remains
incomplete until the post-R2 adapter appendix and a label-blind open-file audit
enumerate it. Every consumed live artifact must then be mounted explicitly and
hash-pinned; an undeclared open is a failure.

The only live model/checkpoint input is the exact DeepCenter artifact. It must
retain epoch 2 and checkpoint SHA-256
`8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0`.
Record checkpoint bytes, manifest hashes, and loader-verified epoch/config.
No arm may choose a path through an unpinned default or download an artifact.
All ST-R3 operations are network-disabled.

## Frozen arms and config equality

There are three semantic arms, executed five times over full eval36:

- `baseline`: exact reviewed `e23`, twin master switch off;
- `dry_run`: exact `twin_only_v1` fields, master on, dry-run true;
- `candidate`: exact `e23_twin_only_v1`, master on, dry-run false.

All executions use the same code commit, raw/image/live-artifact bytes,
dataset order, hardware, device, thread controls, and dependency environment. Their effective
configs are serialized from the actual config objects, not reconstructed from
CLI prose. Baseline-to-candidate differences are restricted to the reviewed
twin whitelist, operational debug path, dry-run/master control, and experiment
tag. Every live artifact path and hash is identical.

The dry-run is an **untimed safety execution** and never supplies a primary
runtime/RSS value. The primary comparison is the preregistered mirrored pair:

```text
AB block: baseline, then candidate
BA block: candidate, then baseline
```

Preregister the block order itself; do not choose it after observation. Each
execution gets a new sandbox, direct-exec process, empty application caches,
fresh output, and full input-content reverification immediately before and
afterward. The pre-arm full read deliberately prewarms host page cache; do not
call the child cold. Pin the hashing executable/config, snapshot, bytes read,
prehash duration, completion-to-exec gap, cache/cgroup policy, and whether file
cache is charged to the job. Target-equivalence and calibration receipts must
reproduce this exact prewarm protocol or conservatively charge the difference.
Mirroring prevents one arm from always receiving the later position. The gate
deliberately uses the most conservative observed pair statistic:

```text
candidate_wall_gate = max(candidate_AB, candidate_BA)
baseline_wall_gate  = min(baseline_AB, baseline_BA)
candidate_rss_gate  = max(candidate_AB, candidate_BA)
baseline_rss_gate   = min(baseline_AB, baseline_BA)
candidate_integrity_wall_gate =
    max(candidate_AB_all_input_pre_plus_post_hash,
        candidate_BA_all_input_pre_plus_post_hash)
```

Both baseline output artifacts must be byte/canonical-graph identical, and so
must both candidate outputs. A disagreement fails deterministic replay; it is
not resolved by choosing one. Neither a minimum candidate run nor maximum
baseline run may replace the conservative statistic.

An arm directory is first built under a same-filesystem temporary name. On a
nonzero exit, signal, timeout, missing event, validation failure, or output
schema failure, retain a hash-pinned failure receipt but never publish it as a
successful arm. On success, validate all outputs and atomically rename the
directory once. Never append to or overwrite an existing successful arm.

## Runtime and RSS capture

Use a monotonic operating-system clock around each authoritative direct-exec
process. Record start/end UTC for audit and integer `monotonic_ns` duration for
the gate. The supervisor forks once, closes undeclared FDs, applies the
sandbox, then `exec`s the arm in that same PID; its `wait4` receipt therefore
covers the pre-exec wrapper footprint and the arm. Capture OS-reported peak
resident memory from that wait status, not Python allocator statistics:

- macOS `ru_maxrss` is bytes;
- Linux `ru_maxrss` is KiB and is normalized by multiplying by 1024;
- store raw value, raw unit, normalized bytes, platform, method, and child PID;
- store a process-creation audit proving that the exec'd process created no
  descendant. Static source review alone is insufficient;
- any descendant, unrelated child, unknown platform/unit, audit gap, detached
  work, or multiprocessing makes the direct-exec receipt invalid and the gate
  `HOLD_RSS_UNMEASURABLE` unless a separately reviewed process-tree/cgroup/job
  sampler accounts for the simultaneous aggregate RSS of the supervisor and
  **all** descendants at sufficient cadence and records its miss bound.

Thus an unmeasured descendant is never ignored. If a process-tree method is
used, its peak is aggregate concurrent resident bytes, not the maximum of
individual-process peaks.

Dataset timing events use monotonic nanoseconds, have exactly one start and one
finish per expected stem, are properly nested/non-overlapping for the
single-worker runner, and follow the frozen dataset order. Record per-video
wall seconds, maximum, p95 (with a preregistered nearest-rank definition), and
the slowest stem. Total child wall time, not the sum of stage timings, governs
the feasibility gate.

Also store, per video, frames, input/final nodes and edges, P/Q pool sizes,
examined frames, enumerated records, eligible/accepted records, and planner
time if available. Assert the final ST-R1/R2 conservation equations and
`enumerated <= p_pool`; the implementation/property tests must prove spatial
queries rather than all-P-by-all-Q materialization. Scaling readouts are
diagnostic and cannot be used to retune v1 after a metric is read.

The local relative gates, required before eval12, are:

```text
candidate_wall_gate <= 1.25 * baseline_wall_gate
candidate_rss_gate <= baseline_rss_gate + 1_073_741_824
```

The local `ru_maxrss` max-candidate/min-baseline result governs only the local
relative `+1 GiB` check. It must never be compared directly with target RAM.
The target `80%` memory gate requires exactly one of:

1. a measured target-class candidate receipt for the whole relevant process/
   cgroup/job;
2. a target-class-equivalent whole-process/cgroup receipt with identical quota
   accounting; or
3. a preregistered, validated conservative RSS calibration multiplier applied
   to a local measurement having the same whole-process/cgroup scope.

The resulting `target_candidate_aggregate_peak_gate` includes the arm,
supervisor, container/runtime, every descendant, and file/page cache whenever
the target quota charges it. The receipt records cgroup/job membership,
sampling/peak mechanism, `memory.current`/equivalent semantics, OOM/limit
settings, and all included PIDs/cache categories. A process-only `ru_maxrss`
receipt cannot be the calibration base. When snapshot/prehash/posthash execute
inside the target job or their cache is charged to it, the peak window begins
before those steps and ends after posthash. Excluding them requires the same
outside-quota proof allowed for the wall-time charge below. Then require:

```text
target_candidate_aggregate_peak_gate
    <= 0.80 * target_declared_ram_bytes
```

Missing scope, uncharged supervisor/container memory, an uncovered descendant,
or unknown target page-cache accounting is `HOLD_TARGET_MEMORY_UNCALIBRATED`.

The absolute hidden-200 gate is allowed only if the timed environment has a
hash-pinned `TARGET_CLASS_EQUIVALENT` receipt covering execution image,
OS/kernel/architecture, CPU model and quota, accelerator visibility, RAM,
thread controls, filesystem/storage class, dependency lock, and sandbox, or a
preregistered conservative calibration has been validated on both local and
target execution classes. The calibration stores benchmark bytes/commands,
repeats, raw values, derivation, expiry, and a reviewed multiplier
`target_seconds_per_local_second >= 1`.

Equivalence/calibration must also bind the exact integrity-hash prewarm/cache
protocol, completion-to-exec gap, input byte volume, filesystem cache state,
and target quota treatment of page cache. Define
`target_integrity_charge_eval36_seconds` as the conservative target-class time
for snapshot preparation plus pre- and post-arm full hashing. It may be zero
only with a hash-pinned target receipt proving the identical immutable snapshot
was prewarmed/verified outside the charged target wall and that required
post-verification is likewise outside that quota. Otherwise derive it from a
direct target measurement or a separately validated conservative integrity-I/O
multiplier; do not hide it outside the child timer. Then and only then evaluate:

```text
target_eval36_charged_seconds =
    candidate_wall_gate * target_seconds_per_local_second
    + target_integrity_charge_eval36_seconds
hidden_200_seconds = target_eval36_charged_seconds * 200 / 36
hidden_200_seconds <= 0.80 * target_declared_wall_seconds
```

Exact target-class equivalence uses multiplier `1`. Without equivalence or a
valid conservative calibration, the local ratio remains reportable but the
absolute gate is `HOLD_TARGET_RUNTIME_UNCALIBRATED`; no metric may be read.

All time/RSS/limit/multiplier quantities must be finite and strictly positive,
except `target_integrity_charge_eval36_seconds` may be exactly zero only under
its explicit outside-quota receipt. Target limits must be non-null. Comparisons
use full stored precision with no tolerance or display rounding.
A runtime/RSS miss is terminal even if a later diagnostic score would win;
exact E23 remains the fallback. No metric is read after such a miss.

The mirrored pair is the complete primary receipt. Optional diagnostic repeats
use a different diagnostic run ID and cannot replace either primary block or
select a favorable value. Two positions reduce order bias but do not establish
a precise runtime variance estimate.

## Generation integrity gates

Every one of the five full-generation submission CSVs must match the exact
ten-column writer contract in
`src/biohub/public_postproc/csv_out.py`, including header order:

```text
id,dataset,row_type,node_id,t,z,y,x,source_id,target_id
```

No missing or extra columns, empty cells, quoted numeric alternatives, booleans,
NaN/Inf, or non-canonical sentinel is accepted. Parse integers strictly in
base-10 and require:

- `id` is globally unique and exactly contiguous `0..N-1` in physical row
  order; dataset blocks follow the frozen stem order;
- node rows precede edge rows within a dataset and node rows are strictly
  increasing by unique `node_id`;
- a node row has `row_type=node`, nonnegative integer `node_id`, integer
  `t,z,y,x`, finite values,
  `source_id=target_id=-1`, `0<=t<T`, and coordinates within the explicit Zarr
  `(Z,Y,X)` bounds;
- an edge row has `row_type=edge`,
  `node_id=t=z=y=x=-1`, and nonnegative integer `source_id,target_id`;
- every dataset has at least one node; every edge endpoint exists in that
  dataset; `(source_id,target_id)` pairs are unique; target time is exactly
  source time plus one; indegree is at most 1 and outdegree at most 2;
- no self-edge, cross-dataset endpoint, duplicate node, duplicate edge,
  unexpected dataset, or trailing/hidden row is accepted.

For a mechanically derived eval12/eval24 or singleton scoring CSV, all schema,
strict-type, sentinel, finiteness, per-dataset node/edge order, bounds,
referential-integrity, uniqueness, time, and degree rules above still apply.
The sole ID exception is intentional: its data rows must be an exact physical
row subsequence of the sealed full-generation CSV, with original text, original
`id`, and relative order unchanged. Therefore a staged subset may start at a
nonzero ID and contain gaps; it must not renumber IDs or be rejected for lack
of subset contiguity. Its dataset set must equal exactly the requested unlocked
stage/singleton, while the five full-generation CSVs still require global
contiguous `0..N-1` and all 36 frozen blocks.

CSV text bytes are authoritative for byte replay, while a separately encoded
canonical typed graph is authoritative for semantic replay. Both hashes are
stored. A permissive Polars cast or `read_submission` check alone is not the
complete ST-R3 validator.

Before sealing generation:

- each of the five executions reports exactly the 36 ordered unique stems and
  one stats row per stem; no silent skip, subset, duplicate, or extra dataset
  is permitted;
- each has a valid immutable-snapshot/exclusive-lock receipt and matching
  pre/post full SHA inventories for image, raw, source/runtime, and every live
  artifact; any execution-window drift invalidates the arm;
- both baseline CSV/typed-graph artifacts are mutually identical; both
  candidate artifacts are mutually identical; baseline and dry-run submission
  CSVs are byte-identical and their normalized node IDs, exact typed integer
  coordinates, directed edges, forks, and output row order are identical;
- the untimed dry-run and both primary candidate executions emit identical
  canonical **pre-mutation** plan, resolution-decision, sort-order, and planner
  counter artifacts for every dataset. Exclude only fields caused by applying
  the mutation (`actual edges removed/added`, post-mutation graph and downstream
  deltas). The exact consumed filenames/field names are bound in the post-R2
  adapter appendix; absent artifacts or unequal hashes are a deterministic
  replay failure;
- baseline is the exact E23/off behavior and candidate changes only through
  the reviewed ST-R2 mutation path;
- all five CSVs pass the exact schema/type/sentinel/order/graph contract above;
- all ST-R1 counters are present as integers, validation failures are zero,
  conservation holds per video, and ST-R2 actual removal/addition/invariant
  fields pass;
- no DeepCenter missing/incompatible/fail-open warning appears in logs;
- output/log/debug/event files contain no NaN/Inf, credentials, absolute secret
  paths, or unregistered dataset;
- debug JSONL is diagnostic only, canonically ordered/capped, and never read by
  the scorer or gate calculator;
- every output file receives bytes and SHA-256 in the generation manifest.

After replay equality, the one identical baseline hash and one identical
candidate hash become the sealed canonical full-36 graph inputs accepted by
every later score stage. Eval12/eval24 subset CSVs are mechanical,
order-preserving filters of those files. Their rows must hash back to the
corresponding full-arm dataset partitions; IDs are not renumbered and values
are not reformatted.

## Exact official scoring contract

Before scoring any unlocked stem, parse and record its scale and adjustment
denominator without fallback:

- the hashed root Zarr metadata must contain an explicit, unambiguous OME-NGFF
  scale transform for the scored array; after removing the time axis, extract
  exactly the three-vector `(z,y,x)` in micrometres;
- all three scale values are finite and strictly positive, and a strict call to
  the current `read_scale` returns exactly that vector. Missing/malformed scale
  metadata must fail; `DEFAULT_SCALE` is forbidden as a fallback;
- GEFF metadata must contain explicit `estimated_number_of_nodes`; parse it as
  `n_total`, require finite and strictly positive, and require
  `estimated_number_of_nodes(geff)` to return that exact recorded value.

Store the metadata paths/hashes, raw source values, parsed scale vector, and
`n_total` in the stage input receipt. Any failure stops before official
`per_sample_metrics`, preventing a NaN adjustment from being silently skipped.

For each currently unlocked dataset and each arm independently:

1. filter the sealed submission to exactly one dataset without changing row
   bytes/values;
2. call `src/biohub/evaluate.py::score_submission` through its official imports
   with `max_distance=7.0` and the stage GT view;
3. assert the returned dataset set is exactly the requested singleton. The
   current wrapper can skip missing GT, so ST-R3 must turn any skip into a hard
   failure;
4. keep the official per-sample row and call official `summarise` on a
   one-element list after removing only the added `dataset` label;
5. construct no handwritten edge, division, adjustment, or combined-score
   formula.

For each unlocked group (`eval12`, later `eval24`, later `eval36`, and the
`44b6`/`6bba` partitions within it), call official `summarise` separately on
the baseline rows and candidate rows. Subtract the two returned summaries only
after both calls. Never summarise row deltas and never use the arithmetic mean
of per-video scores as the official aggregate.

Persist for each video and arm:

- every official count: edge TP/FP/FN, division TP/FP/FN, and integer
  `num_pred_nodes`;
- node recall, total-node ratio, edge Jaccard, adjusted-edge Jaccard;
- the one-row official division Jaccard and combined score;
- exact source arm/subset/GT/scorer hashes.

The exact official `summarise` return-key set is:

```text
n
edge_jaccard
division_jaccard
division_tp
division_fp
division_fn
node_recall
adj_edge_jaccard
n_adj
score
```

Require exactly this set, no missing/extra key, and persist it without calling
diagnostic values official. `summarise` does **not** return aggregate edge
TP/FP/FN or aggregate `num_pred_nodes`. If useful, sums of those per-video
official counts are stored under an explicitly separate `diagnostic_sums`
object, excluded from gate input except that no such substitute may replace an
official key. The division-TP gate uses the official summary's `division_tp`.
Floats are stored as JSON numbers using Python's lossless round-trip
representation and are never rounded before subtraction or comparison.
Counts remain integers.

Canonical JSON uses UTF-8, sorted keys, compact separators, `allow_nan=False`,
and one trailing newline. A per-video/aggregate division Jaccard with zero
division denominator is represented as JSON `null` plus
`division_jaccard_status="NO_DIVISION_DENOMINATOR"`; that is the only allowed
official non-finite sentinel. Any non-finite adjusted-edge Jaccard, combined
score, paired delta, gate input, or unexpected metric is a hard failure.

Per-video paired combined-score deltas are candidate minus baseline, joined by
exact dataset key. Compute their mean with `math.fsum(values)/n`, their median
from the sorted full-precision values (arithmetic mean of the two middle
values for even `n`), and their worst as `min(values)`. Direct IEEE-754
comparisons decide gates; do not add epsilon. Unit tests use exact boundaries
and adjacent `math.nextafter` values.

Running the scoring stage twice against the same sealed manifest in fresh
temporary score directories must produce byte-identical canonical metric and
gate JSON. This proves deterministic scoring/readout replay; it is not a claim
that the two mirrored timing positions characterize runtime variance.

## Mechanical staged gates

All comparisons are inclusive exactly as printed.

### Eval12

```text
paired mean combined-score delta >= +0.005
paired median delta              >=  0.000
paired worst delta               >= -0.002
official aggregate adjusted-edge delta >= -0.002
44b6 official aggregate combined-score delta >= 0
6bba official aggregate combined-score delta >= 0
```

Any miss records `REJECT_EVAL12` and permanently locks eval24/eval36 for that
run. Do not soften the bar or regenerate either arm.

### Eval24

```text
paired mean combined-score delta >= +0.003
paired median delta              >=  0.000
paired worst delta               >= -0.002
official aggregate adjusted-edge delta >= -0.002
44b6 official aggregate combined-score delta >= 0
6bba official aggregate combined-score delta >= 0
```

Any miss records `REJECT_EVAL24` and locks eval36.

### Eval36 roll-up/adoption

Using only the already stored eval12/eval24 rows:

```text
official aggregate division_tp delta       >= +4
official aggregate adjusted-edge delta     >= -0.002
official aggregate combined-score delta    >=  0.000
official aggregate division_jaccard delta  >=  0.000
paired median combined-score delta          >=  0.000
paired worst combined-score delta           >= -0.002
44b6 official aggregate combined-score delta >= 0
6bba official aggregate combined-score delta >= 0
```

Only a run that also retains all prerequisite and feasibility passes may be
labelled `EVAL36_ADOPTION_CANDIDATE`. Candidate counts, geometry, DeepCenter
scores, and debug overlap remain diagnostic and cannot override a failed gate.
Public-four behavior exists only in the external prerequisite receipt and is
not an ST-R3 diagnostic or adoption input/artifact. This label does not
authorize a Kaggle operation.

## Artifact layout and hashing

Use a new ignored directory such as:

```text
outputs/local/steal_twin/<immutable_run_id>/
  PREREGISTRATION.json
  prerequisites/{PARITY_RECEIPT_REF,BASE1_RECEIPT_REF}.json
  inputs/{INPUT_INVENTORY,IMAGE_CONTENT_INVENTORY}.json
  generation/safety_dry_run/...
  generation/primary/AB/{baseline,candidate}/...
  generation/primary/BA/{candidate,baseline}/...
  generation/ARTIFACT_MANIFEST.json
  scores/eval12/...
  scores/eval24/...
  scores/eval36_rollup/...
  final/VERDICT.json
```

Each stage manifest contains the preceding manifest SHA-256 plus, for every
new regular file, relative path, bytes, SHA-256, media/schema type, and role.
It excludes itself to avoid a circular digest. Output directories contain no
symlinks. Inputs may use a separately documented view, but inventories record
both logical view path and resolved source identity without exposing secrets.

Canonical inventory/tree digests are SHA-256 over canonical JSON records
sorted by POSIX relative path, not locale-dependent `find` output. Reject path
traversal, absolute paths inside portable manifests, duplicate paths, special
files, and case-colliding logical paths. Stage artifacts are written to a
same-filesystem temporary file/directory, fsynced where supported, and
atomically renamed. Published stage bytes are never edited in place.

The final verdict includes every individual boolean gate, the first failure,
terminal status, all governing manifest hashes, exact commands, runtime/RSS,
per-video and aggregate score artifact hashes, and the allowed next action. A
human-readable report may round for display but must link to the full-precision
canonical artifacts and must never be consumed by gate code.

After a completed or failed ST-R4 readout, append the immutable code/artifact
references, input hashes, commands, runtime/RSS, per-video paired results,
official aggregates, gate verdict, and next hypothesis to
`analysis/experiment_ledger.md`. The harness never edits the ledger itself.

## Failure semantics and no-retuning rule

- Missing/extra data, hash drift, dirty source/official tree, malformed config,
  runner exception, timeout, signal, partial output, validation/conservation
  miss, nondeterminism, non-finite gate input, missing target limit, or
  unmeasurable RSS is fail-closed before metrics.
- A score-stage exception records `ERROR_AFTER_GT_READ` with the exact sealed
  generation hash and partial score inventory. Do not silently drop the video
  or resume into a different candidate/config.
- A harness defect may be fixed only in a new code commit and new run ID. The
  original sealed arm artifacts may be reused only if the new preregistration
  names their generation-manifest hash, the defect cannot affect generation,
  and no candidate/config/artifact/data byte changed. Otherwise regenerate
  the safety run and both complete mirrored blocks before reading further scores.
- Once eval12 is read, changing code that can affect generation, config,
  checkpoint, threshold, dataset, output, or gate creates a different
  candidate and is forbidden under `twin_only_v1`. Do not probe eval24/eval36
  with a patched v1.
- Failed and partial artifacts are retained as evidence. Do not overwrite,
  delete, rename into success, or select a favorable retry.
- Exact E23 is always the fallback on an integrity, metric, or feasibility
  miss. `disposable_steal` remains blocked.

## Required adversarial tests before ST-R4

Tests must cover at least:

1. official positive fixture where the exact twin rewire improves the correct
   parent/division, and a valid-donor-cut fixture where it harms edge/division
   metrics; both go through `score_submission`, not a proxy;
2. exact official single-video and group `summarise` behavior, proving the
   group aggregate is not a mean of per-video scores and baseline/candidate are
   summarised separately;
3. missing GT skip, extra/missing/duplicate dataset, eval12/eval24 overlap,
   public-four contamination, reordered stems, malformed CSV, duplicate node,
   dangling/duplicate/nonconsecutive edge, and non-finite metric rejection;
   exact ten-column header/order, strict integer syntax, row sentinels,
   full-generation contiguous IDs, dataset/node/edge order, coordinate bounds,
   duplicate edge, degree rules, empty/trailing rows, and unexpected columns;
   staged exact-subsequence IDs may be nonzero/gapped, while renumbering or
   reordered/reformatted subset rows fail;
4. preservation of integer/full-precision `num_pred_nodes` and floats; the one
   allowed zero-division null sentinel; canonical JSON rejects all NaN/Inf;
   exact official `summarise` key set and separation of non-gating diagnostic
   edge/node sums;
5. every gate exactly at, immediately below, and immediately above each
   threshold, including lineage, division-TP, adjusted-edge, combined,
   division-Jaccard, runtime, RSS, and hidden-200 boundaries;
6. state-machine refusal of scoring before generation/feasibility, eval24
   before eval12 pass, eval36 before eval24 pass, regeneration after any score,
   and continuation after a terminal failure;
7. eval36 is exactly the stored eval12/eval24 union and causes no new GT
   evaluation call; both preregistered candidate replays receive no stage
   score/GT argument and are byte/canonical-graph identical;
8. dry-run/baseline byte identity; dry-run/candidate pre-mutation
   plan/decision/sort/counter identity excluding enumerated mutation fields;
   two-baseline/two-candidate replay identity; allowed effective-config diff,
   live-artifact/input hash equality, all ST-R1/R2 conservation, and deliberate
   counter/schema corruption;
9. every local image file/chunk is initially SHA-sealed; image/raw/source/
   runtime/live artifacts are fully re-hashed before and after every arm;
   missing/extra/content drift during the execution fails even at equal size;
   immutable-snapshot/exclusive-lock absence fails, available-byte stability is
   not labelled actual consumption or upstream authenticity; GT/artifact/code/
   official hash drift, symlink/special/path traversal/case collision, dirty
   submodule, atomic-write interruption, existing-output refusal, and secret
   redaction;
10. fresh-child nonzero exit/signal/timeout, incomplete dataset events,
    overlapping/reordered events, macOS/Linux RSS normalization, unknown RSS
    units, any uncovered descendant, aggregate process-tree RSS when enabled,
    closed inherited FDs, GT mount/sentinel negative canaries, missing target
    resource declarations, mirrored AB/BA order, conservative max-candidate /
    min-baseline statistic, and refusal to select a favorable repeat; local
    process RSS is forbidden for target-RAM comparison; target whole-cgroup
    measurement/equivalence/conservative-multiplier branches include
    supervisor/container/descendants and quota-charged page cache;
11. same sealed score input evaluated twice yields byte-identical canonical
    per-video, aggregate, delta, and gate artifacts; strict explicit finite
    positive three-vector scale and `n_total`, with missing/malformed/default
    scale and absent/nonpositive/nonfinite estimated-node metadata rejected;
12. fake runner adapter tests do not establish production-interface
    compatibility; one integration test must exercise the actual reviewed
    ST-R2 CLI/entry point on an in-memory/tiny on-disk fixture; adapter appendix
    names and schemas must match the live artifacts exactly;
13. exact-commit E23 notebook-oracle parity and base1 non-regression receipt
    hashes are mandatory, while public-four rows/stems/scores are absent from
    all adoption inputs/artifacts;
14. hidden-200 is HOLD without exact target-class equivalence or a valid
    conservative calibration, and both equivalence and calibrated multiplier
    branches hit exact/adjacent boundary tests; exact prehash/cache/gap state is
    bound, and pre/post integrity time is charged unless a valid outside-quota
    receipt proves otherwise;
15. an absent/stale/failing latest image verifier receipt remains NOT_READY;
    primary/secondary
    checkpoints are rejected from live mounts while their hashes remain raw
    provenance; DeepCenter is the only live checkpoint, and any checkpoint
    drift rejects `twin_only_v1` instead of relabelling it loss-gate PASS;
16. a newly trained/warm-started checkpoint cannot enter this candidate even
    with a loss-gate PASS; it requires a distinct candidate/preregistration.

The official-positive/adversarial fixtures must assert the raw official counts
as well as the final score direction. A test that only checks that two float
scores differ is insufficient.

## Verification and handoff evidence

The future Qwen handoff must define its exact allowed file set after ST-R2
lands, then run at least:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="src:official/src" \
  .venv/bin/python -m pytest tests -q -p no:cacheprovider
.venv/bin/ruff check src scripts tests
git diff --check
git status --short
```

Before any GT-backed ST-R4 command, SOL must reread the complete Qwen diff,
verify the production adapter against the actual ST-R2 interface, rerun the
focused and full suites, and inspect a label-blind tiny-run artifact manually.
Open interface names are not permission to weaken any semantic requirement in
this contract.

## Current open risks

- The actual ST-R2 production interface and its per-dataset timing event hook
  do not yet exist. This contract intentionally freezes an adapter boundary,
  not a guessed planner signature.
- Immutable snapshots/locks plus pre/post SHA-256 prove that identical local
  bytes were available and stable across each arm; they do not prove every
  byte was actually read or upstream-authentic because Kaggle exposes no chunk
  checksums in the pinned manifest.
- Fresh processes do not flush the host OS page cache. Mirrored AB/BA order and
  max-candidate/min-baseline gating are conservative, but two positions do not
  estimate the full runtime distribution.
- Absolute hidden-200 feasibility remains HOLD until the timed environment is
  proved target-class equivalent or a reviewed conservative calibration is
  available, with the hash-prewarm/cache protocol and charged integrity time.
- The target-RAM gate remains HOLD until whole relevant process/cgroup memory,
  including quota-charged page cache and supervisor/container scope, is
  measured in target class or conservatively calibrated; local `ru_maxrss`
  cannot establish it.
- Binding GT nonvisibility requires an enforceable sandbox/mount namespace and
  closed inherited FDs; a platform that only offers procedural separation
  cannot run the adoption path.
- Eval12/eval24 have prior exposure and eval36 is only their roll-up. Passing
  this contract supports bounded retrospective falsification, not an unbiased
  generalization estimate or a guaranteed leaderboard gain.
