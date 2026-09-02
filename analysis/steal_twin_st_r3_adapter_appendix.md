# ST-R3 production-runner adapter appendix

Updated: 2026-09-02 (Asia/Tokyo)

Status: **`HOLD_INTERFACE_INCOMPLETE`**

This appendix binds the ST-R3 adapter review to candidate commit
`c540102a165e34c9b2a7869ed71bf5c44cf6676b` (`c540102`,
`feat: apply transactional twin-only rewires`). The official submodule gitlink
and checked-out `HEAD` are both
`075fc5f5a52d11077f9dc2b074644618f26939e2`; the submodule was clean when this
appendix was written. The reported integration checks at that commit were 580
repository tests and 102 official tests passing.

This document is subordinate to
[`steal_twin_st_r3_eval_contract.md`](steal_twin_st_r3_eval_contract.md). It
does not change that contract's semantic `run_arm` boundary, datasets, metric,
thresholds, state machine, freshness rules, or leakage boundary. It records
the actual ST-R2 interface at the pinned commit and specifies the minimum
production extension required before ST-R3 generation may leave
`HOLD_INTERFACE_INCOMPLETE`.

## Binding scope and current verdict

The final ST-R2 implementation is available, but it is not yet an admissible
ST-R3 production runner. In particular, it has no ordered-dataset allowlist,
arm name, effective-config artifact, strict single-artifact DeepCenter load,
dataset event sink, stable versioned stats schema, complete uncapped plan
artifact, or atomic success receipt. These omissions are interface omissions;
they must not be filled by reflection, log parsing, planner calls from ST-R3,
or inferred timing.

The current CLI can be launched in a fresh operating-system process and takes
no GT or scoring argument. That fact is necessary but not sufficient. Until
the normative extension below is implemented, tested, reviewed, and pinned to
a new candidate commit, all ST-R3 runtime, feasibility, and scoring transitions
remain forbidden.

## Actual ST-R2 production entry points

### Full post-processing path

The production Python entry point is:

```python
run_postproc(
    geff_dir: Path,
    out_csv: Path,
    cfg: PostprocConfig,
    run_stats_path: Path | None = None,
    predict_seconds: float = 0.0,
) -> dict[str, object]
```

This exact signature is defined in
[`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L1209). It discovers
and lexicographically sorts every direct `*.geff` child, rejecting only an
empty result ([`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L1222)).
It does not accept or validate an expected dataset list. Its return mapping has
exactly the live keys `datasets`, `total_nodes`, `total_edges`, `total_rows`,
and `run_stats`; `run_stats` is a pandas `DataFrame`, not a serialized receipt
([`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L1285)).

The only current full-run CLI is the repository script
`scripts/postproc_geffs.py`; there is no installed project console entry point.
Its arguments are:

| Argument | Current meaning |
|---|---|
| `--geff-dir PATH` | Required directory of direct `*.geff` inputs. |
| `--test-dir PATH` | Image-only Zarr root; defaults to repository `data/test`. |
| `--profile {base1,e23,e23_twin_only_v1}` | Named profile; defaults to `base1`. |
| `--out PATH` | Submission CSV path; required in normal mode. |
| `--run-stats PATH` | Stats CSV path; defaults to `run_stats.csv` beside `--out`. |
| `--save-prelinefit DIR` | Selects checkpoint mode instead of the full CSV path. |
| `--set NAME=VALUE` | Repeatable config override; `BIOHUB_` prefix may be omitted. |

The parser is defined at
[`postproc_geffs.py`](../scripts/postproc_geffs.py#L43), configuration is built
at lines 82--86, and the normal branch calls only `run_postproc` at
[`postproc_geffs.py`](../scripts/postproc_geffs.py#L102). The CLI writes only
human-readable stdout summaries after the run
([`postproc_geffs.py`](../scripts/postproc_geffs.py#L88)); stdout is not an arm
receipt or event protocol. The process exit status is the ordinary Python
interpreter status and is available only to its supervisor.

### Configuration actually consumed

`PostprocConfig` is a frozen typed dataclass. Its 101 fields, including
`TEST_DIR`, all post-processing knobs, the ST-R1/R2 knobs, all DeepCenter path
fields, and `EXPERIMENT_TAG`, are the binding current field set
([`config.py`](../src/biohub/public_postproc/config.py#L307)). Resolution order
is `CODE_DEFAULTS`, then the selected profile, then explicit overrides;
unknown overrides are rejected ([`config.py`](../src/biohub/public_postproc/config.py#L438)).
The three profiles and the frozen `e23_twin_only_v1` values are defined at
[`config.py`](../src/biohub/public_postproc/config.py#L261). The candidate's
frozen twin values are validated when the master switch is enabled
([`config.py`](../src/biohub/public_postproc/config.py#L473)).

The current float parser is a direct call to Python `float()`
([`config.py`](../src/biohub/public_postproc/config.py#L295)). It therefore
accepts textual `nan`, `inf`, and `-inf`, and it preserves signed zero as a
Python float. The present builder has no all-field exact-type/finiteness pass
and no expected effective-config hash check. This is an actual current
interface property, not permission for ST-R3 to accept those values.

The current code exposes only a field-name enumerator
([`config.py`](../src/biohub/public_postproc/config.py#L615)). It does not
serialize the fully resolved typed values. Printing the profile and raw
override dictionary is therefore not an exact effective-config artifact.

## Current emitted artifacts and schemas

### Submission CSV

Normal mode writes the caller-selected `--out` path. Its exact header is:

```text
id,dataset,row_type,node_id,t,z,y,x,source_id,target_id
```

The schema constant is defined in
[`csv_out.py`](../src/biohub/public_postproc/csv_out.py#L10). One global
contiguous `id` counter spans all datasets. Within each dataset, node rows are
sorted by `node_id`, followed by edge rows in filtered edge-list order. Node
coordinates are rounded to nonnegative integers; unused node/edge fields use
the `-1` sentinel ([`csv_out.py`](../src/biohub/public_postproc/csv_out.py#L14)).
Dataset blocks follow the lexicographically sorted GEFF path list
([`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L1247)). This CSV has
no embedded schema-version field; its ten-column schema is nevertheless
binding through the ST-R3 contract. This legacy sort is not the authoritative
ST-R3 order: the parent contract's binding erratum requires the literal
`eval12 + eval24` sequence.

The output file is opened directly with mode `"w"` before the dataset loop.
An exception can therefore leave a header or partial dataset rows at the final
path ([`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L1247)).

### Run-stats CSV

Normal mode writes the caller-selected `--run-stats`, or `run_stats.csv` next
to the submission ([`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L1227)).
Rows are sorted by `dataset` before pandas writes them
([`csv_out.py`](../src/biohub/public_postproc/csv_out.py#L69)). Each row begins
with these derived fields:

```text
dataset
raw_nodes
nodes
raw_edges
edges
division_like_sources
edge_to_node_ratio
gap_added_nodes_frac
```

The construction is exact at
[`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L1167). It then
expands the stats mapping and appends `predict_minutes_total` and
`experiment_tag` ([`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L1190)).
The CLI never supplies `predict_seconds`, so its current
`predict_minutes_total` is zero. This is not arm or per-video runtime.

The current ordinary stats keys are:

```text
raw_edges
dropped_nonconsecutive_edges
dropped_long_edges
dropped_multi_parent_edges
dropped_multi_child_edges
dropped_division_edges
gap_candidates
gap_pairs_selected
gap_reused_existing
gap_inserted_synthetic
gap_added_nodes
gap_added_edges
gap_skipped_node_cap
gap_density_nodes_scored
gap_density_candidates_expanded
gap_density_candidates_restricted
gap_density_selected_outside_base
gap_density_step_delta_milli_sum
gap_refined_synthetic
gap_refine_failed
gap_refine_rejected_shift
centroid_refine_examined
centroid_refine_moved
centroid_refine_no_signal
centroid_refine_rejected_shift
pruned_isolated_nodes
motion_relink_edges
motion_relink_tight_edges
motion_relink_relaxed_edges
motion_relink_frames
motion_relink_replaced_raw_edges
motion_relink_fallback_raw
motion_relink_skipped_large_frame
gap2_candidates
gap2_pairs_selected
gap2_added_nodes
gap2_added_edges
gap2_skipped_cap
safe_division_candidates
safe_division_geometric_candidates
safe_divisions_added
safe_division_skipped_cap
safe_division_mutual_nn_rejected
safe_division_divergence_rejected
deepcenter_gap_checked
deepcenter_gap_bypassed_strong_motion
deepcenter_gap_bypassed_observed_node
deepcenter_gap_accepted
deepcenter_gap_rejected
deepcenter_gap_missing
deepcenter_safe_div_checked
deepcenter_safe_div_accepted
deepcenter_safe_div_rejected
deepcenter_safe_div_missing
short_track_components_removed
short_track_nodes_removed
short_track_edges_removed
short_track_filter_skipped_all
short_track_rescue_triggered
short_track_rescue_components
short_track_rescue_nodes
short_track_rescue_budget
linefit_smoothed_nodes
linefit_skipped_nodes
```

They are seeded at
[`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L82). The additional
`gap_close_effective_max_gap` field is currently conditional and absent from
`new_stats`; this is explicitly documented at lines 85--87. Consequently the
current run-stats header is neither fixed nor versioned.

All 48 current ST-R1 fields are present as integer columns:

```text
steal_twin_examined_frames
steal_twin_p_pool
steal_twin_q_pool
steal_twin_enumerated
steal_twin_rejected_distance_twin
steal_twin_rejected_ambiguous_p_nn
steal_twin_rejected_ambiguous_q_nn
steal_twin_rejected_not_mutual_parent_nn
steal_twin_rejected_distance_existing_child
steal_twin_rejected_distance_parent
steal_twin_rejected_distance_sister_low
steal_twin_rejected_distance_sister_high
steal_twin_rejected_time
steal_twin_rejected_missing_successor
steal_twin_rejected_shared_successor
steal_twin_rejected_divergence
steal_twin_rejected_synthetic
steal_twin_rejected_deepcenter_bundle
steal_twin_rejected_deepcenter_dataset
steal_twin_rejected_deepcenter_frame
steal_twin_rejected_deepcenter_heatmap
steal_twin_rejected_deepcenter_nonfinite
steal_twin_rejected_deepcenter_threshold
steal_twin_eligible
steal_twin_rejected_conflict
steal_twin_rejected_frame_cap
steal_twin_rejected_video_cap
steal_twin_accepted
steal_twin_planned_edges_removed
steal_twin_planned_edges_added
steal_twin_edges_removed
steal_twin_edges_added
steal_twin_isolated_donors
steal_twin_validation_failed
steal_twin_validation_missing_node_field
steal_twin_validation_invalid_node_id
steal_twin_validation_duplicate_node_id
steal_twin_validation_invalid_node_time
steal_twin_validation_nonfinite_node_coordinate
steal_twin_validation_invalid_edge_endpoint
steal_twin_validation_dangling_edge
steal_twin_validation_duplicate_edge
steal_twin_validation_nonconsecutive_edge
steal_twin_validation_indegree
steal_twin_validation_outdegree
steal_twin_validation_nonfinite_edge_distance
steal_twin_debug_records_written
steal_twin_debug_records_dropped
```

Their binding order and spelling are defined in
[`divisions.py`](../src/biohub/public_postproc/divisions.py#L243). Planner
conservation is checked internally before mutation
([`divisions.py`](../src/biohub/public_postproc/divisions.py#L1269)).

The 14 ST-R2 fields are:

```text
steal_twin_mutations_applied
steal_twin_pure_nodes
steal_twin_pure_edges
steal_twin_pure_fork_sources
steal_twin_pure_edge_symmetric_difference
steal_twin_geometry_edges_removed_observed
steal_twin_prune_nodes_removed_observed
steal_twin_prune_edges_removed_observed
steal_twin_short_nodes_removed_observed
steal_twin_short_edges_removed_observed
steal_twin_final_nodes
steal_twin_final_edges
steal_twin_final_fork_sources
steal_twin_linefit_coordinate_changed_nodes_observed
```

Their exact schema is defined at
[`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L64). Applied
remove/add/symmetric-difference conservation is enforced at
[`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L1017), downstream
removal/final topology is recorded at
[`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L1071), and linefit's
topology-preservation guard records coordinate changes at
[`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L720).

ST-R3 consumes the eight base graph/count fields, all 48 ST-R1 fields, and all
14 ST-R2 fields for per-video telemetry and conservation. Other ordinary
fields remain replay/parity telemetry and must remain stable between mirrored
executions. `frames` and planner time are not currently emitted. `frames` must
come from the sealed image metadata in the extension; planner time remains
nullable because the parent contract says "if available".

### Bounded debug JSONL

When `STEAL_TWIN_DEBUG_JSONL` is nonempty, the current runner writes that
arbitrary path. Each eligible candidate produces a resolution record after
sort and cap/conflict resolution
([`divisions.py`](../src/biohub/public_postproc/divisions.py#L885)). The JSON
record fields are:

```text
dataset, decision, reason,
p, q, a, b, a2, b2, sort_key,
d_pq, d_pa, d_pb, d_ab, d_a2b2, divergence_growth,
raw_deepcenter_score, deepcenter_threshold,
deepcenter_decision.{accepted,raw_score,reason},
removed_edge.{source_id,target_id,metadata},
planned_edge.{source_id,target_id,distance_um,edge_prob}
```

Serialization is compact canonical JSON per line, but allocation is capped
once across the whole run and excess records are counted as dropped
([`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L503)). The file is
atomically replaced only after the full run succeeds
([`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L553),
[`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L1282)). It has no
schema version. It is diagnostic only and cannot serve as the complete
pre-mutation plan artifact required by ST-R3.

## DeepCenter selection actually performed

The effective config contains explicit and default checkpoint paths, explicit
and default manifest paths, and a relative checkpoint name
([`config.py`](../src/biohub/public_postproc/config.py#L418)). The loader does
not bind to one path. It constructs an ordered candidate list from the
explicit-or-default checkpoint, every path discoverable through the manifest,
and a relative/default combination
([`deepcenter.py`](../src/biohub/public_postproc/deepcenter.py#L50),
[`deepcenter.py`](../src/biohub/public_postproc/deepcenter.py#L87)).

The loader skips missing paths and catches incompatible checkpoints before
trying later candidates. On success it returns an in-memory mapping containing
the chosen `path` and verified `checkpoint_epoch`, but the runner does not
serialize either value ([`deepcenter.py`](../src/biohub/public_postproc/deepcenter.py#L163)).
Thus even with `REQUIRE_DEEPCENTER_VETO=1`, the present interface cannot prove
that exactly the preregistered artifact, and no fallback, was loaded.
The parent contract binds that sole live checkpoint to epoch 2 and SHA-256
`8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0`;
the corresponding E23 `ARTIFACT_MANIFEST.json` is pinned to SHA-256
`1eedc1af72b10c464c6995013075310510b6f6e634450ff2bc170c67b89ce911`.
This appendix neither changes nor relaxes that identity.

## Pre-linefit checkpoint and relinefit are excluded

`save_prelinefit_checkpoint` is not an ST-R3 arm binding. It writes one
`<dataset>.pkl` containing `dataset`, `raw_node_count`, `nodes_by_id`, `edges`,
and `stats`, plus `manifest.json` containing only `geff_dir` and ordered
`datasets` ([`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L1299)).
The directory may already exist; payloads and the manifest have no schema
version, effective config, input hashes, or atomic run-level publication.

`run_relinefit` trusts that manifest and unpickles those payloads before
running only linefit and rewriting CSV/stats
([`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L1365)). Its CLI
accepts `--prelinefit`, `--test-dir`, `--out`, `--run-stats`, and repeatable
`--set`, but no named profile; it rebuilds the default config
([`relinefit.py`](../scripts/relinefit.py#L34)). Topology, planner telemetry,
and earlier image/checkpoint effects are already baked into the pickle.
Therefore neither checkpoint mode nor relinefit may be selected, mounted, or
used as a fallback by the authoritative ST-R3 adapter.

## Dataset event capability

There is none. `run_postproc` has no event-sink argument and the CLI has no
event file descriptor or event path. The loop loads, filters, writes CSV rows,
and appends stats without emitting a machine-readable boundary
([`pipeline.py`](../src/biohub/public_postproc/pipeline.py#L1250)). No
monotonic clock is used. The final stdout dataset list appears only after
completion and cannot be parsed into per-video timing. This missing capability
alone requires `HOLD_INTERFACE_INCOMPLETE` under the parent contract.

## Normative minimum production-extension contract

The following requirements are cumulative. `MUST`, `MUST NOT`, `SHOULD`, and
`MAY` are normative.

1. **One typed production runner and one fresh-process CLI.** The implementation
   MUST add `src/biohub/public_postproc/production_adapter.py`, containing a
   typed immutable `ArmSpec`, typed immutable `ChildResult`, and the only public
   ST-R3 production runner,
   `run_production_arm(spec: ArmSpec) -> ChildResult`. It MUST add exactly one
   authoritative CLI, `scripts/st_r3_postproc_arm.py`,
   which parses fixed arguments into `ArmSpec` and calls that runner. The ST-R3
   supervisor MUST execute this CLI as a fresh OS process with a preregistered
   argv array and allowlisted environment. Baseline, dry-run, and candidate
   MUST use this same path. Reflection, signature probing, alternate runners,
   planner imports or direct planner calls from the adapter, copied dataset
   loops, checkpoint/relinefit, evaluator imports, GT inputs, and fallback CLIs
   are forbidden.

2. **One pipeline loop and authoritative order.** `pipeline.py` MUST expose a
   minimally refactored core that accepts an explicit GEFF path sequence and
   executes it without sorting. Both the typed production runner and legacy
   `run_postproc` MUST delegate to that one core; the adapter MUST NOT copy the
   loop. `ArmSpec` MUST carry `arm_name`, profile/effective-config inputs, raw
   GEFF root, image-only root, exact DeepCenter paths, the literal ordered
   dataset sequence, expected effective-config SHA-256, supervisor staging
   directory, and inherited event FD. The provided sequence MUST equal the
   parent contract's literal `eval12 + eval24` concatenation exactly. Direct
   GEFF membership MUST equal the same 36 stems as a set. Membership may be
   compared as sets, but execution, CSV blocks, stats, plans, and events MUST
   follow the provided sequence with no sort. Missing, extra, duplicate,
   reordered, symlinked, or invalid arm/profile inputs MUST fail before detector
   load or child artifact creation. Arm-to-config mapping is exact and contains
   no caller-selected profile or free-form override: `baseline` maps to `e23`,
   `dry_run` maps to `e23_twin_only_v1` with `STEAL_TWIN_DRY_RUN=True`, and
   `candidate` maps to `e23_twin_only_v1` with `STEAL_TWIN_DRY_RUN=False`.
   The authoritative CLI MUST NOT expose `--set` or a freely selectable
   `--profile`; any other arm name or effective mapping fails closed.

3. **Canonical, hash-checked effective config.** After building
   `PostprocConfig`, but before output or detector load, the production adapter
   MUST inspect every one of the 101 dataclass fields. Each actual value MUST
   have exactly the runtime type required by the versioned schema: `bool`,
   `int`, `float`, and `str` fields require that exact built-in type with no
   subclass equivalence, while `TEST_DIR` requires the declared Path category
   and an explicit tagged canonical representation rather than an untyped
   string. Every float MUST be finite. JSON MUST be UTF-8, key-sorted,
   compact (`separators=(",", ":")`), `allow_nan=False`, and terminate with
   one newline. Schema version MUST be
   `biohub.st_r3.effective_config.v1`. Serialization and parsing MUST preserve
   every typed value exactly, including the IEEE-754 bytes/sign bit of `-0.0`.
   The adapter MUST hash the canonical bytes and compare them to the
   preregistered `expected_effective_config_sha256` in `ArmSpec` before any
   output or detector operation. A mismatch MUST fail closed. This validation
   belongs in `production_adapter.py`; changing the legacy `float()` config
   parser is neither required nor sufficient.

4. **Strict, single-open DeepCenter binding.** A new strict load path MUST leave
   the legacy fallback loader unchanged. For each registered manifest and
   checkpoint, it MUST open with `O_NOFOLLOW`, require a regular file, retain
   the same file descriptor, hash from that descriptor, seek the same
   descriptor back, and parse/load from it. The checkpoint MUST be passed to
   `torch.load` through that same open file, not reopened by path. Pre- and
   post-read `fstat` identity, size, and modification metadata MUST match. The
   loader MUST require epoch 2, checkpoint SHA-256
   `8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0`, the
   exact manifest SHA-256
   `1eedc1af72b10c464c6995013075310510b6f6e634450ff2bc170c67b89ce911`,
   and frozen loader config. It MUST perform zero fallback
   enumeration and zero alternate opens; missing, replaced, nonregular,
   mismatched, or incompatible input fails immediately. The staged
   `deepcenter_receipt.json` MUST use schema
   `biohub.st_r3.deepcenter_receipt.v1` and record registered identities,
   hashes, pre/post file identity, chosen artifact, verified epoch/config,
   device/dtype, open count, and `fallback_candidates=0`, without secret path
   leakage.

5. **Inherited atomic event channel.** The CLI MUST require
   `--event-fd INTEGER`; an output event path is forbidden. The descriptor MUST
   be an allowlisted inherited blocking pipe owned and drained by the
   supervisor. Each canonical UTF-8 JSON-line event MUST use schema
   `biohub.st_r3.dataset_event.v1`, contain exactly registered fields including
   `schema_version`, child `pid`, zero-based `sequence`, `arm_name`, `dataset`,
   `kind`, and integer `monotonic_ns`, and have total encoded length strictly
   below that FD's `PIPE_BUF`. The child MUST emit each complete record with one
   blocking `os.write` call; `EINTR`, any partial count, record splitting, or
   retry as multiple writes is a fatal interface error. `START` is emitted
   immediately before the first read/load for that dataset. `FINISH` is emitted
   only after its CSV contribution and raw stats are staged and its complete
   per-dataset plan file is atomically finalized in child staging. The child
   MUST NOT write an events artifact. The parent validates exact
   `START`/`FINISH` alternation, sequence, stem order, PID, kinds, strict monotonic
   increase, and one pair per expected dataset, then seals the received bytes
   as the canonical events artifact.

6. **Complete plan hook before debug and mutation.** The pipeline MUST expose a
   production plan hook immediately after `_run_steal_twin_r1_dry_run` returns
   a validated `TwinPlan`, and before debug allocation or mutation. Any required
   refactor MUST move debug allocation after this hook without changing planner
   semantics. For dry-run and candidate, one atomically finalized file per
   dataset under `twin_plans/<sequence>.<dataset>.json` MUST serialize every
   `TwinPlan` top-level field:
   `validation_reason`, `nodes`, `edges`, `candidates`, `accepted_candidates`,
   `decisions`, `counters`, and `debug_records`, including all nested metadata,
   exact sort keys, DeepCenter decisions, and validation/conservation data.
   Schema version is `biohub.st_r3.twin_plan.v1`; files are uncapped and may not
   omit or truncate any record even beyond 200. Baseline MUST finalize one
   `planner_active=false` envelope per dataset. Dry-run and candidate canonical
   pre-mutation files MUST be byte-identical. The existing bounded debug stream
   remains separate and diagnostic; it is allocated only after the full plan
   file is durable and is never an ST-R3 plan input.

7. **Stable raw-stats hook and schema.** Before pandas construction or sorting,
   the shared pipeline core MUST pass each completed raw stats mapping to an
   adapter hook in frozen execution order. The adapter MUST validate the
   predeclared fixed header and exact field types both before and after canonical
   encoding, assert all ST-R1/R2 conservation, and reject mutation, missing,
   extra, reordered, blank, NaN, or Inf values. The fixed schema MUST include
   every current base, ordinary, ST-R1, and ST-R2 field enumerated above;
   `gap_close_effective_max_gap` MUST have a defined value/null rule in every
   row. It MUST additionally include
   `stats_schema_version=biohub.st_r3.run_stats.v1`, the ordered dataset,
   image-derived `frames`, and fixed-type nullable `planner_seconds`. The
   adapter MUST write `run_stats.csv` without pandas type inference. Sorting may
   not repair or conceal order. The frozen raw row and canonical row MUST be
   conservation-validated before dataset `finish`.

8. **Supervisor-owned staging and publication.** The supervisor MUST create a
   never-before-used staging directory and final arm path on the same filesystem
   and pass only the staging directory to the child. The child MUST write only
   explicitly partial/staged artifacts there: submission, stats, canonical
   config, strict DeepCenter receipt, per-dataset plan files/manifest, optional
   bounded debug, and logs allowed by the parent contract. The fixed child
   staged names MUST be `submission.csv.partial`, `run_stats.csv.partial`,
   `effective_config.json.partial`, `deepcenter_receipt.json.partial`,
   `twin_plans/`, `twin_plan_manifest.json.partial`, optional
   `twin_debug.jsonl.partial`, and `child_result.json`; no child-created events
   file is allowed. It MUST flush, fsync,
   close, validate, and hash each file. The child MUST write
   `child_result.json` last, with schema `biohub.st_r3.child_result.v1`, as a
   statement that its own staging work completed; it MUST NOT write
   `arm_receipt.json`, rename the whole arm directory, seal events, or make an
   authoritative runtime/RSS claim. After `wait4`/equivalent process completion
   and event, schema, conservation, byte, and hash validation, the supervisor
   promotes validated `.partial` artifact names inside staging, writes
   `arm_receipt.json` and `dataset_events.jsonl` from the exact pipe bytes into
   staging, fsyncs them and the directory, and atomically renames the whole staging directory
   to the fresh final arm path. That whole-directory rename, with the supervisor
   receipt present, is the sole success publication.

9. **Failure and partial-publication semantics.** Any child exception, event
   write error, timeout, signal, dataset/config/checkpoint mismatch, schema or
   conservation error, hash failure, output collision, or supervisor validation
   failure MUST leave no final arm directory and no success receipt. The
   supervisor preserves the staging directory under its unambiguous failed
   identity and records exit code/signal plus its partial inventory; no staged
   byte is a generation input. The child MUST NOT promote partial work after an
   error. A rerun uses a different never-before-used staging and final path and
   MUST NOT resume, overwrite, clean, or rename the failed staging directory.

10. **Out-of-interface holds remain binding.** The production adapter MUST NOT
    accept GT paths, mounts, or FDs and cannot establish the supervisor's GT
    nonvisibility sandbox. The supervisor's GT mount/FD closure audit and its
    `wait4`, process-tree, cgroup/job, target-runtime, and target-memory evidence
    are outside this production interface. Therefore an interface implementation
    may reach `SHIP` in its own focused review while the overall ST-R3 run still
    remains `HOLD_GT_VISIBLE`, `HOLD_TARGET_RUNTIME_UNCALIBRATED`, and/or
    `HOLD_TARGET_MEMORY_UNCALIBRATED`. No child receipt may clear those holds.

11. **Tests required before interface review.** Focused tests MUST invoke the
    real CLI as a subprocess on a tiny on-disk GEFF/image/DeepCenter fixture.
    They MUST cover all three arms; literal frozen concatenation versus
    lexicographic order; exact set membership; missing, extra, duplicate,
    reordered, and symlinked GEFF rejection before output; `nan`, `inf`,
    `-inf`, and exact `-0.0` config handling; all-field exact types; tagged Path
    round trip; `allow_nan=False`; expected-config hash mismatch; short atomic
    event records; oversize/split/partial-write and injected `EINTR` failures;
    event alternation/PID/order/time validation; plan files beyond 200 records
    with all `TwinPlan` fields; hook-before-debug-before-mutation ordering;
    dry-run/candidate plan-byte equality and baseline inactive envelopes;
    single-open checkpoint hashing/load, same-FD TOCTOU/fstat detection, and
    zero fallback; fixed raw/canonical stats schemas and order/conservation;
    child partial/result-last behavior; parent-only whole-directory publication;
    failed staging preservation; nonzero exit/signal behavior; and absence of
    GT/evaluator/checkpoint-relinefit paths. Legacy `run_postproc` equivalence
    and all existing ST-R1/R2 property, mutation, parity, non-regression,
    repository, and official tests MUST continue to pass.

12. **Allowed implementation file set.** The minimum extension review permits
    changes only to:

    ```text
    scripts/st_r3_postproc_arm.py
    src/biohub/public_postproc/production_adapter.py
    src/biohub/public_postproc/deepcenter.py
    src/biohub/public_postproc/pipeline.py
    tests/test_public_postproc.py
    tests/test_st_r3_postproc_arm.py
    analysis/steal_twin_st_r3_adapter_appendix.md
    ```

    The CLI, production adapter, and focused test MAY be new. The strict loader
    addition in `deepcenter.py` MUST leave the legacy loader behavior intact;
    the pipeline change is limited to explicit-sequence delegation and the raw
    stats/plan hooks. Existing `config.py`, `csv_out.py`, and CLIs SHOULD NOT be
    changed and require a reviewed allowed-set amendment before any change.
    Changes to `divisions.py`, planner semantics, motif/radii/veto/sort/caps/
    mutation behavior, official code, evaluation code, datasets, checkpoints,
    profiles, thresholds, or the R3 semantic contract are forbidden. If another
    file proves indispensable, work stops until this set is separately amended.

13. **Rebinding gate.** Completion of code is not completion of this appendix.
    A reviewer MUST pin the new clean candidate commit, enumerate the final CLI
    and typed runner signatures and exact schemas/filenames actually implemented,
    hash this appendix, run the focused subprocess tests plus the full repository
    and official suites, and verify the production adapter against the real CLI.
    Only then may a reviewed appendix revision change the interface verdict
    from `HOLD_INTERFACE_INCOMPLETE`. No fake adapter establishes this binding.

## Fields deliberately not supplied to the runner

The extension MUST NOT accept a GT path, GT graph, metric row, prior score,
stage verdict, adoption gate, public-four artifact, or callback capable of
reading any of them. It receives only the arm/config/dataset/input/live-artifact
and output/event information allowed by the parent contract. The supervisor
may measure child wall time and aggregate RSS and may validate/hash sealed
outputs; it must not import the production pipeline into the long-lived scorer.

## Present conclusion

Commit `c540102a165e34c9b2a7869ed71bf5c44cf6676b` supplies the reviewed ST-R2
mutation and conservation implementation, but its public runner surface does
not meet the ST-R3 semantic boundary. The only honest current decision is
`HOLD_INTERFACE_INCOMPLETE`. The normative extension above is an interface and
artifact-publication layer; it does not authorize any change to the candidate,
metric, thresholds, or evaluation protocol.
