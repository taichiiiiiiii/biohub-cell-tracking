# ST-R3 scoring appendix: sealed feasibility handoff and score artifacts

Updated: 2026-09-04 (Asia/Tokyo)

## Status

The scorer remains deliberately **HOLD_INTERFACE_INCOMPLETE**. The former
draft feasibility object is retained only as a synthetic-fixture boundary; it
is not a production schema and no combination of its self-reported booleans
can unlock GT. The production validator unconditionally returns the code-owned
HOLD; the draft validator is private and referenced only by synthetic tests.
Re-enablement therefore requires a reviewed source change after the generation
supervisor publishes its complete schemas. No
full five-arm generation/feasibility manifest exists yet, no GT-backed ST-R4
score was read, and no Kaggle/network action was taken. The subsequent
generation orchestrator must emit the exact handoff below; the scorer has no
legacy, reflection, or best-effort compatibility path.

Production re-enablement requires a new reviewed commit. That commit must
replace the draft handoff with exact schemas for all five distinct fixed arm
receipts and verify, rather than trust, arm identity/order, exact eval36 event
coverage, stats/plans/configs, pre/post inventories, sandbox mounts and closed
FDs, GT-negative canaries, DeepCenter identity, conservation, mirrored runtime
and RSS values, target-class calibration/equivalence, target limits, and every
derived feasibility gate. Each aggregate digest must be recomputed from its
listed artifacts. Until those schemas exist, the only production result is the
canonical `HOLD_INTERFACE_INCOMPLETE` CLI object, emitted before resolving the
run directory, manifest, inventory, or any GT path.

The CLI argument retains the contract spelling
`--generation-manifest-sha256`, but its value is deliberately the SHA-256 of
`feasibility/FEASIBILITY_PASS.json`. That file hash-pins the preceding
`generation/ARTIFACT_MANIFEST.json` and its preregistration chain. This gives
the scoring entry point only `(immutable run directory, exact sealed handoff
hash, stage)`.

## Draft feasibility handoff schema (test-only; cannot unlock production)

`feasibility/FEASIBILITY_PASS.json` is canonical UTF-8 JSON (sorted keys,
compact separators, one trailing newline, no NaN/Inf) with exactly these
top-level keys:

```text
schema_version state run_id preregistration generation_manifest datasets
executions canonical_submissions sealed_hashes official source_bindings
feasibility scoring_inputs artifacts
```

The exact values/children are:

```text
schema_version = "biohub.st_r3.feasibility_manifest.v1"
state          = "FEASIBILITY_PASS"
run_id         = nonempty immutable string, equal to PREREGISTRATION.json

preregistration = REF, path exactly "PREREGISTRATION.json"
generation_manifest = {
  ref: REF,  # path exactly "generation/ARTIFACT_MANIFEST.json"
  preregistration_sha256: SHA256
}

datasets = {
  eval12: exact frozen ordered 12-list,
  eval24: exact frozen ordered 24-list,
  eval36: exact concatenation eval12 + eval24,
  digests: {eval12: SHA256, eval24: SHA256, eval36: SHA256}
}

executions = {
  safety_dry_run: REF,
  baseline_ab: REF,
  candidate_ab: REF,
  candidate_ba: REF,
  baseline_ba: REF
}

canonical_submissions = {
  baseline: CANONICAL_SUBMISSION,
  candidate: CANONICAL_SUBMISSION
}

sealed_hashes = {
  full_arm_outputs_sha256: SHA256,
  stats_sha256: SHA256,
  plans_sha256: SHA256,
  configs_sha256: SHA256,
  source_inventory_sha256: SHA256,
  live_artifact_inventory_sha256: SHA256,
  image_content_inventory_sha256: SHA256,
  raw_inventory_sha256: SHA256
}

official = {
  gitlink: lowercase Git object ID,
  head: lowercase Git object ID exactly equal to gitlink,
  clean: true,
  source_hashes: {
    "tracking_cellmot/metrics.py": SHA256,
    "tracking_cellmot/division_metrics.py": SHA256
  }
}

source_bindings = {
  superproject_commit: lowercase Git object ID,
  tracked_tree_clean: true,
  evaluate_py_sha256: SHA256,
  st_r3_scoring_py_sha256: SHA256
}

feasibility = {
  ref: REF,
  prerequisites_passed: true,
  e23_parity: true,
  base1_non_regression: true,
  adapter_reviewed: true,
  training_gate_not_applicable: true,
  source_clean: true,
  official_clean: true,
  generation_sealed: true,
  gt_nonvisibility: true,
  deepcenter_bound: true,
  data_ready: true,
  image_ready: true,
  deterministic_replay: true,
  dry_run_identity: true,
  conservation: true,
  local_runtime: true,
  local_rss: true,
  target_runtime: true,
  target_memory: true,
  hidden_200: true
}

scoring_inputs = {
  gt_view: portable relative directory path,
  gt_inventory: REF,
  image_view: portable relative directory path,
  image_content_inventory: REF
}

artifacts = [REF, ...]  # strictly POSIX-path sorted, no duplicates/case collisions
```

The referenced generation JSON must report `state="GENERATION_SEALED"` and
the same `preregistration_sha256`; its remaining schema is owned by the
generation supervisor.

`REF` has exactly `{path,bytes,sha256}`. `path` is a nonempty portable POSIX
relative path without `.`/`..`, backslashes, absolute roots, symlinks, or
special-file traversal. `bytes` is a nonnegative JSON integer. `sha256` is 64
lowercase hexadecimal characters. Every referenced regular file is rehashed.

`CANONICAL_SUBMISSION` has exactly:

```text
{
  ref: REF,
  typed_graph_sha256: SHA256,
  partitions: {
    <each exact eval36 stem>: {sha256: SHA256, bytes: integer, row_count: integer}
  }
}
```

Its ref path is fixed to
`generation/canonical/{baseline,candidate}/submission.csv`. The typed graph
digest is SHA-256 of canonical JSON with schema
`biohub.st_r3.typed_submission_graph.v1` and the ordered dataset records
`{dataset,nodes,edges}`; node tuples are `[node_id,t,z,y,x]`, edge tuples are
`[source_id,target_id]`. Each partition hash/byte count is over the exact
physical data-row bytes for that dataset, excluding the header. It is checked
back against the full CSV before any stage subset is created.

Each future execution receipt must itself be canonical JSON at a distinct,
arm-specific fixed path. Any GT capability/path value, argv/environment/mount
entry, inherited FD, or public-four value is rejected unless an exact reviewed
schema explicitly allows a non-sensitive field. The generation supervisor must
define and verify its complete receipt schema. Merely supplying five keys,
opaque hashes, or `true` booleans is not evidence and cannot unlock scoring.

## GT inventory and preflight

The GT inventory has exactly:

```text
{
  "schema_version": "biohub.st_r3.gt_inventory.v1",
  "stems": [exact ordered eval36],
  "records": [REF, ...]
}
```

Records are sorted by path and exactly cover regular files below the relative
GT view. The GT view has exactly one `<stem>.geff` and one `<stem>.zarr`
directory for every eval36 stem, no other root, symlink, or special file. At an
eval12/eval24 transition, all files under only the unlocked roots are matched
to inventory byte counts and SHA-256s before parsing/scoring.

For every unlocked stem the scorer requires one unambiguous OME-NGFF scale
transform for scored array path `0`, resulting in exactly finite positive
`(z,y,x)` micrometre values. The strict values must equal `read_scale`
exactly; the repository default-scale fallback cannot pass. The root GEFF
metadata must explicitly contain numeric, finite, positive
`estimated_number_of_nodes`, and it must equal the helper result exactly.
The image root has exactly one metadata representation: Zarr v3 `zarr.json`
or Zarr v2 `.zattrs`; coexistence is ambiguous and rejected. Axis names are
explicitly either uppercase `T/Z/Y/X` (the real pinned Zarr v3 bytes) or the
lowercase NGFF spelling `t/z/y/x`. Mixed case, reordering, missing spatial
`type=space`, or missing `unit=micrometer` is rejected rather than inferred.
The four-axis time component is mandatory; a three-axis `Z/Y/X` shorthand is
not accepted. The current repository `read_scale` consumes only the v3 root
`zarr.json`, so a structurally valid v2 `.zattrs` remains fail-closed at the
helper-agreement check rather than allowing an equal-to-`DEFAULT_SCALE`
fallback to masquerade as an explicit metadata read. Supporting v2 scoring
requires a separately reviewed `read_scale` change and source-hash binding.

## CSV and official readout

Both sealed full CSVs require the exact ten-column header. All cells are
unquoted, nonempty, canonical base-10 integers where numeric, with a final and
consistent newline. Full IDs are physical-order contiguous `0..N-1`; dataset
blocks use frozen eval36 order; nodes precede edges; node IDs strictly
increase. Sentinel, TZYX-bound, endpoint, t-to-t+1, uniqueness, indegree,
outdegree, and nonempty-dataset constraints are checked.

Eval12/eval24/singleton CSVs are byte-exact row subsequences. Their original
IDs, text, newline, and relative order are preserved; renumbering,
reformatting, reordering, missing rows, or extra rows cannot hash back to the
sealed partition and fail.

Each unlocked stem/arm is passed singleton-by-singleton to
`biohub.evaluate.score_submission(..., max_distance=7.0, verbose=False)`.
Missing-GT skip is an error. The scorer calls the imported official
`summarise` again for each singleton, then separately for baseline/candidate
stage and lineage groups. The exact official summary key set is enforced.
Official counts remain integers and floats retain Python round-trip precision.
Only a zero division denominator becomes JSON `null` plus
`NO_DIVISION_DENOMINATOR`; all other nonfinite values fail.

Eval36 loads the already published eval12 and eval24 `PER_VIDEO.json` rows in
their exact concatenated order. It performs zero GT/evaluator calls, then runs
official `summarise` on the stored per-sample rows for eval36 and its two
lineage partitions.

## State, artifacts, and commands

The production CLI uses one authoritative `--stage all` invocation. Once the
future sealed feasibility handoff is accepted it runs eval12, its gate, eval24,
its gate, and the eval36 stored-row roll-up without returning control to a
human. Internal eval24/eval36 transitions additionally require the exact prior
manifest SHA held in memory by that invocation; recomputing a self-consistent
manifest after score-read modification cannot advance the state. A skip, error, metric
reject, or completed eval36 creates the first no-clobber
`final/VERDICT.json`; later continuation is refused. Partial score files are
atomically retained under `scores/failed_<stage>/` and inventoried. Successful
stage directories are built under same-filesystem temporary names and renamed
once; existing targets, symlinks, and special files are refused.
If the directory fsync after a no-replace rename fails, a file publication is
retracted only when the pathname still names the exact installed inode. A
stage publication is moved away from its success name into a unique
`failed_<stage>-publish-*` quarantine. It is never reported as a successful
stage.

Each published stage contains canonical `INPUT_RECEIPT.json`,
`PER_VIDEO.json`, `AGGREGATES.json`, `DELTAS.json`, `GATE.json`, and
`ARTIFACT_MANIFEST.json`; eval12/eval24 also retain exact stage and singleton
CSV subsequences. The manifest has exactly:

```text
schema_version = "biohub.st_r3.score_stage_manifest.v1"
state run_id stage preceding_manifest feasibility_manifest_sha256 artifacts
```

Every artifact record has exactly `{path,bytes,sha256,media_type,schema_type,role}`.
The manifest excludes itself and chains to feasibility, eval12, or eval24 as
appropriate. Published stage directories must contain exactly the manifest
and its listed regular files.

Commands, after the future upstream handoff exists:

```bash
PYTHONPATH="src:official/src" python scripts/st_r3_score_stage.py \
  --run-dir outputs/local/steal_twin/<immutable_run_id> \
  --generation-manifest-sha256 <FEASIBILITY_PASS.json SHA256> \
  --stage all
```

The CLI writes one canonical result object. `HOLD_INTERFACE_INCOMPLETE` is
`status="HOLD"` with exit code 3; ERROR has exit code 2 and REJECT is nonzero.
EVAL12_PASS, EVAL24_PASS, and EVAL36_ADOPTION_CANDIDATE are zero. The adoption
label authorizes no Kaggle operation.

## Remaining holds

- Full generation supervisor and this exact feasibility handoff do not yet
  exist: `HOLD_INTERFACE_INCOMPLETE`.
- The authoritative latest image-verifier receipt became READY on 2026-09-04
  (`READY.json` SHA-256
  `8a0a36d393ecc11a0532bc12011257a4c012cb7361d4346941b4d1211c58c73e`).
  This closes only image completeness; production ST-R4 remains held by the
  incomplete generation/feasibility handoff and the gates below.
- No target-class runtime calibration/equivalence or whole-cgroup memory
  receipt was supplied here. Those remain generation/feasibility holds and
  cannot be inferred from local scoring tests.
- No generation sandbox/nonvisibility receipt, five-arm deterministic replay,
  DeepCenter binding, E23 parity receipt, or base1 receipt was produced here.
  The handoff requires their aggregate/ref gates to be true; fixture values
  demonstrate schema behavior only.
- Synthetic official fixtures validate metric direction/counts but are not
  real eval12/eval24 results and must not be reported as candidate evidence.
- Same-UID mutation is checked at the independent consumer boundary: every
  accepted ref and unlocked GT file is opened with no-follow semantics, has
  one link, and retains device/inode/mode/UID/link/size/mtime/ctime identity
  while hashing. GT receipts bind those identities and content hashes both
  before and after scoring. This complements but does not clear the upstream
  supervisor's `HOLD_PROCESS_TREE_UNPROVEN` for its own process tree.
