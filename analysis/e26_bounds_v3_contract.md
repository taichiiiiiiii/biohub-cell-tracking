# E26 v3 — serializer-report measurement correction and reproducibility

Current status at 2026-09-07 05:53 UTC: VERSION3_COMPLETE / PHYSICAL_SHIP /
SUBMISSION_ACCEPTED_PENDING_SCORE. Accepted E26 submission56069885,
scriptVersionId347872590, notebookversion3. E23 remains incumbent.

Preregistered 2026-09-07 before any v3 code update, GPU run or E26 submission.
This is the same E26 motion-OFF hypothesis, not a new scientific candidate.
Parent owns this design. Independent physical reviewers both classified v2 as
CSV/graph/provenance PASS but ORIGINAL_REPORT_GATE_FAIL / NO SUBMIT.

## Cause and immutable evidence

The v2 CSV is exactly the expected one-field repair of v1, SHA256
1a2975db15961ba4b92c67019b209ccbb1bd2e0a9c71011fd2595d82da6e3390.
Its telemetry truthfully records seven round-to-clip events. Six x lower-bound
events were already performed by the old max(0, round(x)) serializer and have
zero old/new CSV delta. An integer CSV cannot reveal those pre-clip negative
floats. The parent's exact-one-total-report assumption was wrong; helper behavior
is correct. Preserve that failed preregistration and v2 artifacts unchanged.
Do not reinterpret v2 as having passed. No E26 submission has been accepted.

## Only configuration change

Keep helper, every scientific setting, all weights, node/edge/CSV behavior,
notebook cells and metadata unchanged except the run-provenance token:
e26-bounds-a8d2b43e-d39549fb-20260907-v3.
Qwen Cloud exact qwen3.8-max through the existing subscription Token Plan/none
route authors the bounded token-only replacement. The parent mechanically
integrates it, reviews exact deltas and reruns tests/lint. No application logic
change, new provider/authentication settings, fallback, PAYG or new worktree.
The existing candidate directory remains the run source; retain v2 source/test
snapshots under ignored outputs before changing this identifier.

## Fixed physical gates (all required)

- New actual kernel version must be 3; verify returned push identity and complete
  before/after source/config/assets/Docker, private/T4/offline, no other push.
- CSV bytes must equal v2 exactly: SHA above, 12284897 bytes, 236052 rows,
  120460 nodes and115592 edges. Full schema/int64/row-ID/sentinel/order/graph/
  finite/bounds checks remain required; v1 difference stays id11613 y256->255 only.
- Report ordered dataset counts: 25467,19051,6069,69873 nodes, using actual Zarr
  metadata shapes. Complete samples, sample_limit20, not truncated. Totals:
  corrected_nodes7, axes z0/y1/x6, max correction1. Dataset2/3 have zero events.
- Upper event: 44b6_0113de3b, row11613/node12069/t49/y, round256->clip255,
  signed-1/absolute1. Lower events: 6bba_05db0fb1, x, round-1->clip0,
  signed+1/absolute1, exact row/node/t triples below. No additional identities,
  axes or corrections. Reapplying the old writer to every recorded original
  float must reproduce its v1 CSV field; the six lower events change no CSV field.
- Entering floats must be finite, JSON-safe and round to the fixed integers.
  Do not require equality of their last floating-point bits or a preregistered
  report byte hash; record differences if any. The complete new report's actual
  byte hash must nevertheless match its new provenance exactly.
- Preserve strict helper report validation, actual model/support pins, expected
  retention behavior and no unintended fallback. Record runtime without a hidden
  199-video or9.6-hour guarantee. Loss N/A; no new training.

| row_id | node_id | t |
|---|---|---|
|105657|7471|9|
|117286|19919|24|
|118505|21305|26|
|120631|23706|29|
|120993|24088|29|
|155985|61812|79|

## Execution and provenance

One new private physical run, platform timeout43200 seconds. Source/helper/test
hashes are fixed after token-only review and before push. No parallel heavy run.
At push+1000 seconds, recheck full source/config/version3 and RUNNING, then use
one bounded180-second live-token observation, closing on the new exact token.
If unavailable, one later read-only snapshot may be used while still RUNNING;
preserve every failed observation. No final-only substitution for live evidence,
no kernel restart to obtain a log. Observation failures alone are not GPU errors.

After COMPLETE, exact-version output request once; only known404 may use one
latest-output retrieval with pre/post version3/source/config checks, matching
new token in live/full logs and provenance, and actual CSV/report/helper hashes.
This remains operational provenance, not an exact-endpoint version guarantee.
The v3 token must exclude stale v2; same CSV bytes alone cannot bind the session.
Compare complete token values/complete log lines, not substrings: the new value
intentionally contains the old value as a prefix. Require one new assignment in
source, the new exact value in provenance, a new live marker and two new full-log
markers; reject the old exact assignment/value/marker or mixed records.

All gates plus parent and independent physical audits precede this loop's one
accepted submission of actual version3/output filename submission.csv. Any new
contract/integrity failure means NO SUBMIT and no automatic rerun. LocalSCREEN
remainsINCOMPLETE; E23 stays incumbent absent the unchanged adoption evidence.

Independent scientific design review: SHIP, no must-fix (Heisenberg, Sep7).
Token-only handoff review: SHIP (Ampere). Max response completed at
05:06:31.068461 UTC in3.055 seconds, exact Max/Token Plan/none/tool0/exit0,
single180-second unit/no feedback/retry/fallback. Strict JSON delivery passed.
Worker log SHA7821a15c516765fede468fe4ca145e7d490c70cdd4e7ce4b6c59383be0777d81.
Parent applied the delivered suffix once in notebook and twice in test literals,
then verified exact byte equality to v2 except those replacements and no double
suffix. Immutable v2 snapshots: outputs/local/e26_implementation/v2_frozen_source/.
Parent703 tests PASS(1.78s), Ruff4 files PASS, git diff --check PASS.

Frozen v3 hashes before push:

- notebook:0976f955fec21352fe37e1afb37b8c40d992fbde61cdea2a43b189d4eae185f2 (276405bytes)
- notebook test:ce9669bd227564be55ab3a03026b37ecf7e13755d87f5ad69aa57ff6bc73eb23 (19511bytes)
- metadata:5aea96ed603325fd874c2b2c29d2e4015cfe19ced740faae44ef11d917e1ac68 (unchanged)
- helper:d39549fbaeefc9edbd6273e10c3cf96377b33b1ea6d080befec6bd12071e5df5 (unchanged)

Fresh GPU quota29.30/30 hours remaining,0.70 used. Final independent integration
review SHIP: exact one notebook/two test literal replacements, source assignment1,
helper embedded once, unchanged metadata/helper, focused10 PASS and Ruff PASS.
05:08:49.868028 UTC current remote version2/COMPLETE and all33 frozenv2 source/
config/assets checked. One push at05:10:25.605082 UTC was accepted at
05:10:28.321519 UTC as actualversion3/kernel133333893. Post-push05:12:28.454910
UTC confirmsRUNNING and all33 source/config/assets/Docker match. Receipt:
outputs/local/e26_implementation/e26_bounds_push_v3.json. No more GPU runs under
this contract. First live-token observation no earlier than05:27:09 UTC.
No v3 outputs or E26 submission yet. The existing two-hour maintenance remains
unchanged; a separate15-minute heartbeat was not created because the app permits
only one active heartbeat on this task. The parent continues this active run.

At05:30:19.903955 UTC full33cell source/config/assets/Docker/version3 guards
confirmedRUNNING. The first actual live stream observed the exact new token at
05:30:21.219286 UTC (runtime1038.495393004s), closed immediately, and repeated
the complete guards withRUNNING at05:30:22.706023 UTC. Observation2.802s,
304events, one exact marker, no stream error; no second connection used.
Evidence: outputs/local/e26_implementation/e26_v3_live_token_snapshot.jsonl,
SHA3fb5b9b839cadb19617b24b8b0770efb5f624e94cacb3a09c9156c1024fbab2e.
An earlier precheck stopped before any stream/file creation because the checker
compared local string booleans with API booleans and assumed machineShape=Gpu.
Read-only inspection confirmed actual private=true/GPU=true/internet=false and
NvidiaTeslaT4; fixing the checker normalization changed no notebook or run.
Fresh05:30:50 UTC limits: numTotal6/numAllowedNow5 (numToday omitted); all six
listed submissions are historical and no E26 submission has been accepted.

Pre-output submission message, fixed05:33 UTC:
`E26 motion relink OFF; bounds-safe serializer v3; exploratory; local SCREEN incomplete; E23 incumbent 0.924 unchanged`
Submit only version3's output filename submission.csv, not a local-file upload.
The05:32 web requests for official rules/code-requirements returned zero readable
lines and do not constitute a new content verification. Retain the actual logged-in
same-turn rules/code-requirements inspection recorded earlier; deadline/quota
checks are authenticated API observations, not substitutes for those rule texts.
Parent recheck at05:32:703 tests PASS(1.89s), four-file Ruff PASS,
git diff --check PASS. Frozen runtime sources remain unchanged.

## Complete output evidence (2026-09-07 05:40–05:43 UTC)

Download guards05:40:42.679024→05:40:48.809364 UTC: version3/kernel133333893,
all33cell source/config/assets/Docker unchanged, COMPLETE before and after.
One exactversion3 output request returned404; one preapproved latest retrieval
followed with173 unique inventory entries, no next page and only the five required
artifacts downloaded to fresh outputs/kaggle/e26_bounds_v3/. This is operational
provenance, not an exact-endpoint version guarantee. Full log has exactly two
new token lines and no old/mixed complete token values. Receipt:
outputs/local/e26_implementation/e26_bounds_v3_download_receipt.json.

- submission.csv:12284897bytes, SHA1a2975db15961ba4b92c67019b209ccbb1bd2e0a9c71011fd2595d82da6e3390
- output_bounds_report.json:3426bytes, SHA7d514ce8a82f50085938c3681d18552a59e7171ae67b07f39f3e2cc27b022cf2
- output_bounds_provenance.json:363bytes, SHA3b8ab2cace636864a7b431d49792e8b655a8f2b865a974b032815d1a65a1c39f
- run_stats.csv:2988bytes, SHAb85c4ab6e187465c7014dccffaccba2a696a1b3cfbd5255f3da156b7c0e19624
- run.log:76831bytes, SHA6dfc772f2dc10c7afdb83cb346954596911e54e9d08e92ff721a073fc02e3e88

Parent canonical validator VALID, every canary fired;236052 rows/120460 nodes.
Parent strict report validation against actual4 Zarr metadata shapes, counts,
seven identities/round/clip/oldwriter decomposition PASS. Full CSV byte-equalv2,
all-field zipped comparison againstv1 gives only row11613 y256→255. Report also
byte-equalv2 including all entering floats, which is observed, not a new gate.
Provenance exact five fields/newtoken/helper/actual CSV+report hashes PASS.
run_stats differs fromv2 only in allfour predict_minutes_total values
(9.051425683498383→8.951369599501293). Official subtree remains clean.
05:43:10 UTC current limits6total/5allowed, six historical submissions/noE26.
Fresh top30 leaderboard still has16th0.951; planning target0.953 unchanged.
No scientific score, SCREEN completion or incumbent adoption is inferred.

Both independent physical reviewers returnedSHIP with no new discrepancy:
Ampere full strictCSV/report and Heisenberg source/live/full-log/assets/runtime.
Parent accepts all v3 gates before the one exactversion3 submission. Full log
472events ends1771.773182817s (29.53min); v2 ended1285.712530171s (21.43min).
Prediction8.95137 vs9.05143min, while token→Foundgraphs614.85667 vs294.38902s
includes loader discovery/setup and is not a pure checkpoint-load measurement.
T4×2, expected4 asset pins, epoch2 DeepCenter loaded, motionOFF/validatorOFF,
allow_artifact_fallback=false and existing retention fallback60 all match.
No Traceback/OOM/unintended fallback; only nonfatal notebook-export warnings.
Legacy summary source_notebook_sha256 is not used as actual-source evidence;
binding relies on API all33 cells, live/full exact token and actual hash provenance.
Hidden199/12h/9.6h feasibility remains unproven, not extrapolated from this total.
LocalSCREEN remainsINCOMPLETE and E23public0.924 remains incumbent.

## Accepted submission and follow-up

One SDK code-submission call (the same explicit kernel/version/output fields as
the preregistered CLI command), request05:48:24.917302 UTC,
accepted response05:48:26.887224 UTC: ref56069885. No retry or second submission.
Immediate pre-submit full33 source/config/assets/Docker/version3/COMPLETE and
fresh no-E26 history/quota checks passed. Request and response:
outputs/local/e26_implementation/e26_v3_submission_attempt.jsonl.

Readback05:48:45.295395 UTC: seven submissions, exactE26 slug,
scriptVersionId347872590, outputsubmission.csv, correct frozen description.
Kaggle timestamp05:48:25.793 UTC; score/error_description empty, status omitted,
totalBytes0: accepted/pending, not an observed execution error or scored result.
Limits now numToday1/numTotal7/numAllowedNow4. Readback:
outputs/local/e26_implementation/e26_v3_submission_readback.json.
Public4 CSV SHA above binds the validated target output, not the as-yet-unknown
CSV regenerated during hidden scoring. Do not claim a hidden output hash.

Existing heartbeat id2 was updated successfully at05:49 UTC for read-only
follow-up of this exact acceptedID/slug/scriptVersionId. Name, same task, ACTIVE,
two-hour cadence and failed_runs_only notification policy were preserved and
read back from automation.toml. No separate automation/new task was created.
The prior blanket Kaggle API ban now has only this accepted-submission-read
exception; no new push/run/download/submission/final-selection changes or
unattended Qwen Cloud calls. On finite score or explicit error, record the result
and stop repeated checks of thisID, retaining normal maintenance. Empty status/
score is not silently turned into failure. Parent must not claim completion of
the gold goal, SCREEN, hidden feasibility or model adoption from acceptance.

Final direct-turn check05:53:35.397687 UTC: same submission56069885 and exact
slug/scriptVersionId347872590, SDK status attributeSubmissionStatus.PENDING,
public_score/error_description empty and total_bytes0. No terminal result yet.
Approved work/e26-flash is still clean; no new worker, commit or Git push.
