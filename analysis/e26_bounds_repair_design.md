# E26 implementation repair: shape-aware output bounds

Designed by the parent on 2026-09-06 after the first target run, before any
E26 leaderboard submission. This repairs an execution/format defect within
the same motion-OFF hypothesis; it is not a newly successful scientific loop.

## Evidence and boundary

The private version1 completed, but its frozen CSV has exactly one out-of-bounds
node among120460 nodes: dataset44b6_0113de3b, node12069, frame49,
(z,y,x)=(44,256,191). The actual spatial shape is(64,256,256).
Independent review reproduced this; all other node coordinates are in bounds.
Source version1, CSV47eed35456bb3626e3903d582fc29f195bb0bb65c1d98db83f01ba908e36db17,
and full log remain untouched. No E26 submission was accepted.

The frozen notebook serializer rounds coordinates and clamps only below zero;
it does not enforce the upper bound. Centroid refinement uses an in-volume
weighted average, while the final line-fit step may extrapolate at a track end.
Independent cause review is complete: node12069 is an endpoint with the single
incident edge11797->12069. E23 instead follows11525->11793->12065 and omits
11797/12069. The entering pre/post-linefit floats and raw GEFF of this E26 run
were not retained. Thus the missing upper serializer bound is confirmed, but
linefit as the numerical origin of this particular violation is not proven.
Refinement can retain its input when a patch has no signal, so an already-invalid
raw coordinate cannot be excluded. A generic output bounds invariant is required
independently; unavailable historical checkpoints are not a circular prerequisite.

## Fixed repair scope

- Keep motion OFF, validator OFF, all model weights, detector thresholds,
  association settings, every graph edge, and all other scientific knobs fixed.
- Keep the existing Python rounding convention. For each finite coordinate,
  round then bound it to the corresponding actual dimension's[0,size-1].
  Read(T,Z,Y,X)from the dataset's existing Zarr metadata; require exact rank4,
  positive integral dimensions and matching multiscale axes T,Z,Y,X for path0.
  Do not infer order from rank alone or read full image arrays to get the shape.
- Reject NaN/Inf, missing/malformed metadata, invalid times and nonintegral IDs.
  Do not hide invalid upstream data with a default shape or clamp invalid time.
- Apply the same generic serializer behavior to either E23 or E26; no checks
  for this one node ID, dataset ID, frame, or hard-coded64/256 shape are allowed.
- Record complete affected-node/per-axis counts and maximum absolute integer
  correction. In deterministic traversal order, retain bounded examples with
  dataset, CSV row id, node id, t, axis, entering finite float, rounded integer,
  clipped integer, signed delta(clipped-rounded), and absolute integer delta.
  Distinguish complete aggregates from truncated samples. Zero-correction
  datasets remain visible. This is serializer telemetry, not an upstream trace.
- Preserve graph topology and row order/IDs. Do not remove nodes, edges or bad
  rows. Do not hand-edit the downloaded CSV and submit it under old code version1.
- Do not change the old negative safe-division diagnostic print or retention
  guard behavior in this repair. Distinguish known misleading telemetry from
  the independently validated model loading and graph invariants.

## Implementation and independent acceptance

Application code and focused tests must be authored by the requested Qwen Cloud
model via the existing subscription-only route. The latest user condition permits
qwen3.8-max when Flash fails acceptance; the parent confirmed the Flash HOLD and
explicitly selected Max for this bounds repair. The parent integrates,
rereads the complete delta, runs tests/lint, and obtains independent review.
No SOL substitution, PAYG or automatic worker launch is authorized by this design.
The current worker policy forbids launching from an unattended goal/heartbeat;
this handoff is preparation, not an instruction to bypass that boundary.

Focused tests must cover all three axes at lower/upper limits, rounding at and
near the upper edge, negative finite inputs, NaN/Inf, non-cubic shapes, size1,
invalid shape/time/ID, zero-change valid input, and truthful correction counts.
Include a small trajectory-shaped case exposing possible smoothing overshoot.
The integration check must prove only the declared serializer/shape/telemetry
code changed, and all priorE26 science/config/asset source is unchanged.

As a read-only acceptance analysis, applying the proposed integer-output mapping
to the pinned valid E23 reference must change zero rows. Applying it to the saved
invalid E26 CSV must report exactly the single y256→255 difference, with all
other columns and all edges unchanged. This analysis is not a new submission
file and is not a substitute for rerunning the corrected notebook.

Freeze the new code revision and source hashes before physical execution, obtain
its actual immutable Kaggle version, run it once serially, then perform fresh
source/config/weight/finite/CSV/graph checks and runtime/correction telemetry
review. The corrected public4 run has a hard predeclared gate: only node12069 in
44b6_0113de3b at t49 may change y256->255, integer magnitude1. Every other field,
row, node/edge, ID and ordering must match invalid version1. Additional corrected
rows/axes, larger corrections or other output differences mean NO SUBMIT until
independently explained and a revised contract fixed before another run. These
known-public4 identities are acceptance evidence, never hardcoded runtime logic.
The existing localSCREEN remains incomplete.
Only a valid target version can consume this loop's one accepted submission.
After acceptance follow its terminal LB result; numerical adoption gates and
the E23 incumbent remain unchanged until supported by proper evidence.

## Current status

MAX_BOUNDS_INTEGRATION_ACCEPTED / VERSION3_PHYSICAL_SHIP /
SUBMISSION56069885_ACCEPTED_PENDING_SCORE (2026-09-07 05:50 UTC).
Version2 isCOMPLETE and its CSV/graph/provenance pass, but the original report
expectation fails: seven recorded corrections include six unchanged legacy lower
clamps. Both independent audits confirmed the parent expectation-design defect.
Version2 remains NO SUBMIT. The reviewed forward-only contract is
e26_bounds_v3_contract.md: same science/helper/CSV, only a new Max-authored token,
explicit seven-event decomposition, fresh version3 run.703 tests/Ruff/SHIP;
actualversion3 completed and passed parent/both independent physical audits.
CSV/report byte-equalv2, seven fixed events/onev1 CSV delta, full provenance PASS.
One submission accepted05:48:26 UTC as56069885/scriptVersionId347872590.
Score/error empty on readback: pending, no newLB result. Existing2h maintenance
now follows only this acceptedID read-only. The following04:34 account is history.
The Qwen-authored generic helper and two test modules are now in canonical.
Parent verification:693 related tests PASS, focused156 PASS, Ruff PASS;
independent implementation review SHIP. Notebook integration subsequently passed
703 related tests/Ruff and independent166 tests/SHIP. The parent pushed once as
actualversion2; post-push all33cell source/config checks PASS and statusRUNNING.
No new output validation, submission or LB result yet; see e26_bounds_target_run.md.
Full read-only mapping of the pinned E23/E26 CSVs passes the zero/one-coordinate
contract; this does not replace the required fresh physical run.
The earlier units are closed. A fresh direct user request on2026-09-07 to use
qwen3.8-max and advance this project authorizes the current supervised r2 unit.
This does not authorize unattended/heartbeat/automation worker launches.

The historical Plus multi-deliverable task failed after a prohibited malformed
patch attempt and was stopped with no changes. A separately reviewed 300-second
helper-text-only unit then finished with tool0 but failed strict JSON delivery.
Neither output is accepted. Preserve both logs, do not decode/repair their code
into production, and do not launch another Plus narrowing/retry automatically.
The user subsequently approved a Cloud Flash task; that was a new model
selection, not permission for unattended runs or silent Max/SOL fallback.
Parent cannot substitute SOL-authored application implementation for Qwen.
At that historical point implementation was the dependency, not GPU completion.
The original version 1 remains terminal invalid; the separately fixed version 2
is now RUNNING as recorded in Current status above.

The historical Flash task is analysis/e26_flash_bounds_task.md: one supervised 600-second
authoring attempt, helper and tests as two literal Python blocks, no tools,
retry0/fallback0. No JSON-string encoding of source. Native SOL handles only
connection configuration, design, diagnostics, integration checks and reviews.
Final serializer ID/time rejection is a fail-closed format prerequisite; it does
not modify or validate the existing upstream raw int conversions. Scientific
settings, source preservation and the exact-one-public4-correction gate are fixed.

The first Flash model response completed normally in69.797seconds, tool0 and
strict two-literal-block delivery PASS. Its isolated61 tests produced53PASS and
8FAIL; parent and independent diagnostics rejected adoption. Confirmed defects
are correction telemetry erased by clipping before comparison, path0 ambiguity,
lossy Real ID conversion, malformed report samples, and incorrect test oracles.
The original source/log is preserved in outputs/local/e26_implementation.
One explicit evidence-driven feedback correction uses the same Flash/none/Token
Plan and stayed inside the first admission's total600-second supervision deadline,
2026-09-06 16:54:10 UTC. Independent review SHIP on this limited repair stage;
no transport retry, fallback or expanded scientific lever. The correction task
is analysis/e26_flash_bounds_correction_task.md. A second non-acceptable output
stops this unit; no parent-authored code substitution is allowed.

The one correction completed normally at16:52:32.692993 UTC in107.241seconds,
tool0/exit0/strict delivery PASS. Parent's isolated execution found97PASS/2FAIL
and Ruff I001 twice. This is not acceptance. The remaining failed test oracles
mistake no-op assignments for corruption (empty samples on a fresh report and
absolute_delta45 on an already45 sample). Independently of those false failures,
parent probes confirmed that a Fraction-valued original_float can be accepted
then make JSON serialization fail, and original_float/rounded_int mismatch,
missing non-truncated samples, and impossible axis totals are all accepted.
The valid generated clipping/telemetry path improved, but evidence integrity
checks remain incomplete. No canonical source/tests, new notebook, GPU run,
submission or LB update has been adopted. The bounded Flash unit is now closed;
no further worker/fallback is started in this unit.

The subsequent direct user instruction, "改善しなければ3.8MAXで", supplies a new
explicit model escalation decision. Flash's two failed acceptance results meet
that condition. At2026-09-06 17:10:45.844728 UTC the parent began one supervised
Max bounds task, exact qwen3.8-max/Token Plan/none/tool0/retry0, cap600seconds.
No API/route fallback, automation launch or parent-authored application code.
Operational42 tests and related553 tests PASS; independent operational and task
reviews SHIP. Separate Max catalog/policy preserve Plus/Flash defaults and locks.
Task: analysis/e26_max_bounds_task.md. The response completed normally at
17:13:29.870505 UTC,164.016seconds, exit0/tool0; strict literal delivery and both
AST parses PASS. The parent read both complete files and ran isolated tests:
112PASS/1FAIL, with Ruff F401 and I001. The failed assertion is an incorrect
no-op corruption test (absolute_delta45->45), not a clipping regression.
Independent review nevertheless found substantive acceptance defects: samples
can have an incorrect shape projection, out-of-range time/IDs, inconsistent
axis totals or false truncation; non-path0 metadata axes are unchecked; numeric
failures are not consistently normalized to OutputBoundsError. Review HOLD.
The first response/log remains isolated and unmodified; no canonical code/tests
were adopted. A new full correction cannot be safely completed and reviewed in
the remainder of the original600-second supervision window, so this bounded
unit closes without a correction launch, retry, fallback or deadline extension.
Max remains the explicitly selected model; transport success is not code
acceptance or tracking-accuracy improvement.
This is still the same scientific E26 bounds repair, not a fresh LB hypothesis.

At2026-09-07 03:44:22.801483 UTC the parent started validation r2 using the same
verified Max/none/Token Plan route. Admission probe found no worktree lock and a
free shared Cloud slot. The fixed authoring task is
analysis/e26_max_validation_r2_task.md: helper plus one corrected test oracle and
new regressions; preserve every other original test and the clipping/update path.
Independent design review SHIP. This new900-second supervision window ends at
03:59:22.801483 UTC and permits at most one evidence-driven feedback correction,
not transport retries or model fallback. Notebook integration is a separate unit
after acceptance. The old600-second task is not reopened. No code adoption yet.
Worker log: outputs/local/e26_implementation/max_validation_r2_WORKER.jsonl.

R2 returned normally at03:46:02.857988 UTC (100.056505seconds, tool0), but
130PASS/3FAIL plus independent validation gaps prevented adoption. The single
feedback was dispatched at03:52:55.405489 within the unchanged original deadline
and returned at03:55:02.623277 (127.217788seconds, tool0). Its156 tests passed,
but a non-vacuous parent counterexample and independent review proved the missing
distinct-visible-identity lower bound. The supplied identity test silently removed
the second sample and failed on maximum mismatch instead. R2 closed HOLD; no
second feedback or extension was used.

The parent redesigned the remaining work inside the same active direct-user
coding turn as a new single-function authoring unit, not an unattended restart:
analysis/e26_max_identity_guard_task.md. Independent design review SHIP. Only
_validate_report and one regression definition were reauthored, all other bytes
preserved. A single Max/none/Token Plan response started03:59:52.241666 UTC,
cap300seconds/no feedback/retry/fallback, and completed04:00:11.763603 UTC in
19.521937seconds, tool0. Strict two-def delivery/AST PASS. Parent full delta
review,156 tests, Ruff and independent review all PASS/SHIP. The new regression
was also run against the pre-guard helper and correctly failed with DID NOT RAISE,
proving it detects the intended defect. Import-only formatting was repeated at
canonical paths because Ruff classifies package imports differently there.
Accepted helper SHA256:d39549fbaeefc9edbd6273e10c3cf96377b33b1ea6d080befec6bd12071e5df5.
Full CSV mapping: E23 240126 rows/122207 nodes/zero changes; E26 236052 rows/
120460 nodes/exactly CSV id11613, dataset44b6_0113de3b,node12069,t49,y256->255.
Input CSV hashes remained unchanged. New kernel, physical run and LB result remain pending.

## Validation repair contract (implemented; history, not a restart instruction)

Preserve the original scientific invariant and frozen artifacts. Before another
physical run, a Qwen-authored correction must make report validation check its
own complete bounded history: JSON-safe builtin scalars; original float rounds
to rounded_int; clipped_int equals the generic shape projection; signed/absolute
delta agree; sample IDs/time/dataset are valid; per-axis and affected-node counts
are possible; non-truncated sample count equals total axis corrections; truncated
means exactly20 retained samples and more than20 total corrections. Complete
maxima/counts must not be inferred solely from truncated examples.
Keep ordinary node/coordinate work unchanged and reject malformed metadata
path/version types before using them. Tests must mutate a genuinely existing
valid sample or counter, not write the same value and demand rejection. Review
the oracle independently before implementation. Reuse the reviewed small bound
mapping idea, but do not silently adopt any unaccepted full module.

The next supervised Max repair should change only validation and its regression
tests, preserving the already-working clipping/update path. Supply concrete
counterexamples rather than another full-feature rewrite: x300 with internally
consistent clipped254/delta-46; sample t=T and ID2**63;21 identical corrections
with20 samples but truncated false; an x sample against z-only axis totals; and
nonfinite IDs. Require genuine fixture mutations, atomic rejection, exact
projection/ID/time checks, universal aggregate/truncation checks, every metadata
entry's axes, and normalized conversion errors. Keep repeated-ID calls valid.
Successful transport and a larger test count alone cannot accept the result.

## Reviewed notebook integration boundary (accepted; authoring history below)

The independent writer-tail audit found one definitions/runtime boundary in
frozen E26 cell13: after the final filter function return at source line1617,
before DeepCenter runtime initialization at source line1620. Embed only an
accepted helper there, verbatim and without future imports. No helper function
or constant name in the first delivery collides with existing notebook globals;
repeat that check against the actually accepted revision, including added names.

Initialize ordered report storage beside stats_rows at source line1629. For
each sorted GEFF, load the matching actual Zarr shape and create the dataset
report immediately after obtaining dataset from its stem at line1640. Replace
only the node CSV dictionary writer at lines1673-1684, preserving sorted node
iteration, upstream casts, row_id increment and the complete edge loop. Append
the dataset report once after the node loop. Write the ordered JSON report next
to submission.csv after run_stats.csv at line1738, using strict finite JSON.
Those are source-cell line numbers, not physical JSON notebook lines.

Root metadata validation is an explicit new fail-closed precondition. Failure
can leave a partial CSV from earlier datasets; such a run is invalid and must
never be submitted. Preserve final dataset/header/row-count checks and all other
cells/config/assets. No rejected Flash or Max helper is eligible for embedding.

Integration task analysis/e26_max_notebook_integration_task.md started04:07:57.394095
UTC,600seconds/originaldeadline04:17:57.394095. Initialresponse44.438288seconds,
strict6replacementanchors/AST/helperliteral PASS. Independent source-only SHIP:
onlycell13's6declared regions and separate kernel metadata id changed. Oldv1dir
is immutable; candidate lives in notebooks/e26_target_motion_off_bounds. Tests
were5PASS/5FAIL due fixture/schema/placeholder/test-import/exception-class errors;
candidate is provisional, not eligible for physical execution or submission.

Before physical execution, independent SDK audit found output/status responses
contain no immutable version/session field. Exact-version endpoints previously404.
The parent therefore preregistered a non-scientific provenance addition before its
implementation: token e26-bounds-a8d2b43e-d39549fb-20260907 in source and start/end
logs, plus output_bounds_provenance.json with schema_version1/run_token/helper_sha256/
actual submission_sha256/actual output_bounds_report_sha256. Priorv1source/log and
inventory contain neither token nor bounds artifacts. No scientific branch uses it.
One feedback at04:12:22.809886 UTC keeps the originaldeadline and corrects tests
plus only the first/sixth replacement telemetry. Task:
analysis/e26_max_notebook_integration_feedback_task.md. No further feedback/fallback.

Version binding for the eventual run: prefer exact actualversion output once.
Only a known404 may trigger one bounded latest-output diagnostic retrieval after
independent review; require pre/post currentversion and complete source/config
equality, COMPLETE, no interveningpush, unique token in source/live+downloadedlog/
provenance, and provenance hashes matching CSV/report bytes. Token plus hashes
must exclude stalev1/mixed artifacts. Label this operational provenance, not an
exact-endpoint version guarantee. Missingtoken/artifact, differentversion/source,
non-COMPLETE, asset/hash/output inconsistency or ambiguous inventory meansHOLD.

Closure on 2026-09-07 at 04:34 UTC: the integration feedback delivered valid
application/provenance code, but three test oracles still failed. A separately
bounded four-definition test-only handoff corrected notebook-vs-kernel metadata,
literal helper newline, same-runtime exception identity and CSV row ID 0.
A final four-literal-only handoff changed mislabeled expected node IDs to ints.
Parent application semantics were unchanged; all logic remained Qwen-authored.
Final notebook tests 10 PASS, combined related tests 703 PASS, Ruff PASS;
independent combined 166 PASS and SHIP. Frozen candidate and hashes are in
e26_bounds_target_run.md. This supersedes the provisional integration status
above without erasing the failed authoring results. Actual version 2 was pushed
once and source/config checked RUNNING; physical integrity remains pending.
