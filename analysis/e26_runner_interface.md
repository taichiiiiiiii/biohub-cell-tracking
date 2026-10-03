# E26 unit03–04 handoff interface

2026-09-06. Parent design revision2; independent re-review SHIP. No dispatch or
physical-run authorization. The accepted generation and scoring contracts retain
all scientific requirements. This document fixes their artifact/process handoff,
not a new candidate, split, gate, implementation model or worktree.

## Decision and ownership

Preregistration must precede all fresh prediction generation without pre-creating
the generation run directory. Unit04 owns the opaque GT/scale preregistration;
unit03 owns generation and a generation-only child control. Unit04 then owns
staged official scoring in a separate process. Implement all three before any
real run, even though implementation/adoption proceeds unit02 → unit03 → unit04.
Unit03's synthetic acceptance must not be presented as physical-run readiness.

Use these two canonical output namespaces, not project copies or worktrees:

- `outputs/local/e26_screen_preregistrations/<run-id>/`: immutable preregistration.
- `outputs/local/e26_screen/<run-id>/`: fresh generation and later scoring results.

Creating the preregistration directory must fail if it already exists or if the
matching generation run exists. Later generation creates its own run directory
exclusively. Reject unsafe run IDs, path traversal, unexpected aliases, reused
IDs and existing artifacts. Failed outputs remain; do not delete, resume or
silently assign another ID. Generation and scoring retain their original
exclusive arm/result paths. This avoids weakening run-directory exclusivity to
accommodate an earlier GT registration.

## Process sequence

1. After all implementations and tests are accepted, parent fixes the numerical
   physical timeout/RAM budget. No numeric allowance is granted by this draft.
2. A separate preregistration entry checks generation output absence, pins exact
   scientific/source/dependency identities and generation inputs, inventories the
   selected 36 GT trees opaquely, and binds explicit image ZYX scale metadata.
   It must not parse GT graphs or estimated-node-count semantics. Exclusively
   write/reparse/hash private `GT_BINDING.json` first. Then write/reparse public
   `PREREGISTRATION.json` last as the completion marker. The latter contains no
   GT-tree paths or inventories; it binds the private artifact's SHA256, size and
   video count. Parent records both exact byte digests before dispatch.
3. Generation entry requires the public registration path and both expected
   digests, not an arbitrary caller-supplied GT digest or timestamp alone.
   Verify the complete public schema/run/candidate, literal orders, frozen budget
   and applicable identity bindings before
   creating the run and before the first generation child. Missing/incomplete
   preregistration is ERROR, never an opportunity to register after prediction.
   Unit03 may byte-hash the private registration artifact to check its binding,
   but must not deserialize it, inspect its GT paths/inventories or open GT trees.
   Complete private-schema/GT-inventory checks belong to unit04 preregistration
   and scoring. A half-created pair with no valid public marker is incomplete.
4. Build parent control, then derive each child control by an explicit generation
   field allowlist. Never serialize the whole public or private registration into child control,
   argv, environment or logs. No GT paths/inventories, score imports or score
   callbacks enter the generation child. The SHA commitment alone conveys no GT
   semantics. Original procedural-separation limits still apply.
5. Run fresh public4 → baseline36 → candidate36 children serially under unit03.
   Bind parent control and the original preregistration byte identity into the
   final generation seal, including both registration digests. Both immutable
   registration artifacts stay separate. A child failure emits only a failure
   receipt binding those original digests; no generation seal may exist then.
6. A separate scoring entry verifies the expected generation seal and its bound
   public/private registrations, all predictions/receipts and current identities before staged
   semantic GT reads. Follow unit04's eval12 → eval24 → saved-row eval36 sequence
   and common finalizer unchanged, including every early REJECT branch.

Both expected registration digests must be supplied at dispatch and recorded in
parent launch evidence. Accepting whichever preregistration file happens to exist
at score time is forbidden. Source changes between registration and scoring are
ERROR, not an invitation to update the registered source inventory.

## Minimum shared artifact header

Public `PREREGISTRATION.json` uses schema `biohub.e26_screen.preregistration.v1` and
includes run_id, exact candidate_id, created_utc, submission_authorized=false,
literal ARM_ORDER and EVAL36 order,
and the following mandatory binding objects:

- scientific_binding: exact relevant contract/task paths and byte identities,
  including the final unit03/unit04 handoff tasks and this interface.
- source_binding: generation plus scoring/official source closure, Git HEAD and
  honest dirty state. A hash of a status label is not a source inventory.
- dependency_binding: installed runtime identities required by unit03 and unit04.
- generation_input_binding: exact ordered raw/image/weight/reference identities,
  selected aliases/resolved content, explicit shapes/scales and E23 configs.
- gt_binding_commitment: artifact name `GT_BINDING.json`, algorithm `sha256`,
  expected byte digest, byte size and exact video count36 only. No GT-tree path
  or full GT inventory is allowed in the public registration.
- budget: fixed per-arm and whole-generation wall limits, score-process/stage
  limits and RAM measurement/enforcement policy with explicit scope/units and
  finite positive values. State self-process versus process-tree scope honestly.
  No default unlimited or inferred budget; limits do not relax scientific gates.

Private `GT_BINDING.json` uses schema `biohub.e26_screen.gt_binding.v1`, run_id,
candidate_id, submission_authorized=false, literal EVAL36 order and the exact
ordered 36 GT-tree opaque content inventories with explicit ZYX metadata
bindings. No precomputed metric or interpreted graph is stored. Only unit04
parses this private JSON; unit03 treats its entire contents as opaque bytes.

Nested inventories must retain full records and deterministic hashes, not merely
counts or hashes of absent files. All JSON is exclusive, allow_nan=False,
flush/fsync, and reparsed. Unknown/old/incomplete schemas fail closed. The final
implementation schema and tests must validate nested keys/types and exact selected
orders; this header list does not replace the underlying contracts' checks.

Parent `CONTROL.json` binds both registration artifact paths, sizes and expected digests
alongside generation controls; it is not the control passed to an arm child.
Each arm's generation-only control has its own hash. `GENERATION_SEAL.json`
binds parent control, both original registration identities and all complete arm
artifacts. Scoring binds those same bytes rather than creating replacement seals.
None of these artifacts authorizes submission or certifies generalization.

## Interface acceptance tests

Use synthetic trees/fake children only. In addition to the complete unit03/04
acceptance suites, prove:

- preregistration precedes generation; existing run prevents registration;
- missing/changed/old/wrong-run public registration or missing/mismatched private
  artifact bytes prevent the first child; missing public completion marker does
  not permit a half-created registration pair;
- an expected-SHA mismatch cannot be bypassed by replacing the file or by a
  plausible created_utc value;
- all three child controls/argv/env/logs exclude GT paths/inventories and scoring
  state while binding the expected generation identity;
- instrument generation JSON loaders/GT readers to prove unit03 never parses the
  private artifact or opens its GT trees, while opaque artifact hashing works;
- successful parent seal refers to both original immutable registrations; after
  child failures only a failure receipt retains their digests and
  `GENERATION_SEAL.json` is absent;
- score entry rejects registration substitution and post-registration source or
  budget changes before semantic GT access;
- early eval12 rejection still never opens eval24 GT semantically, while opaque
  integrity rechecks remain permitted and clearly identified.

No production fixture hook, generated toy GT, post-hoc registration, omitted
scientific check or alternate metric is an acceptable shortcut to a green test.

## Bounded implementation reference map

Single-agent handoff, 2026-09-08: the user's no-subagent override changes routing
only. The parent directly implements and self-reviews this interface. The existing
`e26_generation_contract.md` and `e26_scoring_contract.md` are also the final
unit03/unit04 implementation briefs; no separate worker-task files or dispatch are
needed. Pin both, this interface, the E26 design, unit02 and unit02b tasks, v2
screening protocol and E23 parity runbook in the scientific closure. All scientific
requirements, frozen numerical gates and pre-execution acceptance remain unchanged.

Independent read-only API diagnosis, with parent checks of the core loop,
strict receipt, raw-stat builder and CSV writer, found the following boundary.
These are existing committed APIs, not a reason to copy or import an old runner.

- `public_postproc/pipeline.py:1325–1443`: call `run_postproc_core` once per arm
  with the exact supplied GEFF sequence, `write_run_stats_output=False` and
  `exclusive_output=True`. Its return keys are datasets, total_nodes,
  total_edges, total_rows and run_stats (None with the required flag).
  Start/finish hooks receive `(sequence, dataset)`; finish follows CSV fsync.
- `public_postproc/deepcenter.py:288–303`: call the public strict loader once;
  it returns `(bundle, receipt)`. The core's injected one-argument loader checks
  `actual_cfg is cfg` and returns only bundle. Check actual CPU/float32 receipt
  and epoch2; its legacy schema label does not grant an ST-R3 certificate.
- `public_postproc/pipeline.py:88–171,1283–1303`: obtain the pinned `new_stats()`
  key set and capture each raw hook mapping as a plain dict in event order.
  Preserve the signed density accumulator and optional gap key semantics from
  the generation contract. Validate before adding absence diagnostics.
- `public_postproc/csv_out.py:14–76`: the core owns the writer (global IDs,
  sorted nodes, existing edge order). Do not instantiate a second writer or use
  the sorted/nonexclusive pandas run-stats path.
- `biohub.io.open_volume` and `biohub.validate.validate_submission` provide
  metadata shapes and structural checks using only explicit selected images.
  The latter takes a Polars frame and a dataset→(T,Z,Y,X) map; the extra E26 CSV
  checks in the generation contract still run before calling it.

Graph reading, all-centroid refinement, filtering and final linefit stay inside
the existing core; do not reimplement the scientific path or call private graph
conversion helpers from the runner. Defer numerical/scientific imports until
the child's explicit environment controls are established. This source map is
implementation guidance, not a substitute for any input/CSV/telemetry/seal test.

## Review record

Initial draft `dd09d7070bc358fe0ffab8d9e73632b25bfa65cc0c0fec0400b75e12fc0f6a3a`
was HOLD on two defects: passing full private GT registration into generation
schema parsing, and ambiguous failure-path seal wording. Revision2 separates
private binding from the public completion marker and explicitly forbids a
generation seal on child failure. Independent review accepted revision2
`e2664fb91001ddfb06e15adc7eef5b6d13a9a6fdff63e7f8462481eab298fa98`
with no remaining blocking issue. Parent adopts that interface; this status and
review record are the only subsequent changes. No implementation or physical
evaluation is certified by this design acceptance.
