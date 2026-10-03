# E26 bounds-repaired target run — frozen before physical execution

Status at 2026-09-07 04:58 UTC: VERSION2_COMPLETE / CSV_PARITY_PASS /
REPORT_EXPECTATION_FAIL / SUBMISSION_HOLD.
This document is the preserved version2 preregistration and failed result.
The new forward-only version3 contract is e26_bounds_v3_contract.md. Canonical
candidate source now contains the v3 identifier; immutable v2 source/test/metadata
are retained at outputs/local/e26_implementation/v2_frozen_source/ with the v2
hashes listed below. v2 artifacts are unchanged and v2 remains NO SUBMIT.
All 236052 CSV rows match the preregistered one-field correction exactly, but
the report has seven round-to-clip corrections: one upper bound and six legacy
lower-bound corrections that leave the old CSV unchanged. The original report
expectation of exactly one is FAILED, not silently relabeled PASS. Independent
cause review and the next decision are pending. No E26 submission or LB result.
Push accepted 04:33:45.624396 UTC as actual version 2/kernel 133333893.
The user directly requested qwen3.8-max and project progress. The parent owns
design, integration and external actions; Qwen Cloud Max authored all application
and test logic through the existing subscription-only Token Plan/none route.
No unattended Cloud launch, model/provider fallback, PAYG, purchase or reset.

## Hypothesis and fixed scope

This is an execution repair inside E26 (E23 motion relink OFF), not a new
scientific loop. Keep motion OFF, validator OFF, weights, upstream casts,
graph topology, node/edge IDs and traversal order unchanged. The only output
behavior change is generic coordinate round-then-clip against actual Zarr3
TZYX metadata. Report corrections and fail on malformed metadata/numeric values.
Training is not performed: training Loss is not applicable to this repair.

The saved invalid v1 must not be edited or submitted. Canonical candidate:
`notebooks/e26_target_motion_off_bounds/e26_target_motion_off.ipynb`.
Original v1 source remains in `notebooks/e26_target_motion_off/` as an immutable
comparison fixture. These are subdirectories of the existing project, not new
repositories or worktrees.

## Frozen identities

| Artifact | SHA256 |
|---|---|
| Candidate notebook | e631fe0d68b9f862085bc14c7c39873f82b8d186ce7c15150381f9dd97798170 |
| Candidate kernel-metadata.json | 5aea96ed603325fd874c2b2c29d2e4015cfe19ced740faae44ef11d917e1ac68 |
| Accepted src/biohub/output_bounds.py | d39549fbaeefc9edbd6273e10c3cf96377b33b1ea6d080befec6bd12071e5df5 |
| tests/test_output_bounds.py | 1bbbe9ac6c19f3ec36ea8b4701eddd0565110c3d1ab32838d715bea5ac7087b9 |
| tests/test_output_bounds_regressions.py | 8f6e243a7b34e33e2ae5e1d493700f7ca81c92244cc07d117c2152a6552a887f |
| tests/test_e26_bounds_notebook.py | 88c9dda0aabce835fd0d8a97af4ce3e85654589e806754fa2d030f502f9ab3c6 |
| Original E26 v1 notebook | a8d2b43e743eea8a99a128e4a2672f1ede8531dc162ebbb10dd957fc5fa7a052 |
| Original E26 v1 CSV | 47eed35456bb3626e3903d582fc29f195bb0bb65c1d98db83f01ba908e36db17 |
| E23 reference CSV | 33c179b0449b9cdd186f06a653cddc8cf12359f008982f6713cdf30784a52e6a |

Parent validation:703 related tests PASS in2.31seconds; focused helper156 and
notebook10 included. Ruff PASS on the new module and three test modules.
Full33-cell object comparison changes only cell13 source; helper embedded once
verbatim. Kernel metadata changes only the old requested slug to the actual
slug. Independent final review SHIP: focused10 and combined166 tests PASS,
Ruff PASS; all four delivered oracle definitions match the reviewed final code.
No typecheck tool is configured in pyproject.toml; source AST and runtime tests pass.

Read-only integer-output mapping of actual saved CSVs: E23 240126 rows/122207
nodes changes zero fields; E26 236052 rows/120460 nodes changes only CSV id11613,
dataset44b6_0113de3b,node12069,t49,y256->255. Source CSV hashes remain unchanged.
This is not a submitted file or a substitute for fresh inference.

## Version and output binding

Actual kernel:`taichiiiii/biohub-e26-motion-off-exploratory`, kernel ID133333893.
The pre-push check found version 1/COMPLETE; the single push was accepted as
actual version 2 at 04:33:45.624396 UTC with a 43200-second platform timeout.
Post-push source/config checks at 04:34 and 04:40 UTC found version 2/RUNNING,
all 33 normalized cell sources equal, and private/T4/GPU/internet-off unchanged.
Receipts are in outputs/local/e26_implementation/e26_bounds_*v2*.json.
Any subsequent version or source change means HOLD. Do not push again while
binding these outputs.

Version-specific SDK requests are preferred, but historically returned404.
Latest output/status responses contain no version or session field. Therefore
this run adds a non-scientific provenance token before runtime and after output:
`e26-bounds-a8d2b43e-d39549fb-20260907`.
`output_bounds_provenance.json` records schema_version1, this token, helper SHA,
actual written CSV SHA and actual bounds-report SHA. Priorv1 source/log/inventory
contain neither this token nor bounds/provenance artifacts.

Require push identity, latest source/config equal to normalized frozen candidate,
RUNNING/live-log token, COMPLETE, exact-version output request once, and another
full source/config check after output retrieval. Only a known404 may use one
bounded latest-output retrieval with independent-reviewed operational provenance:
same current version before/after, no intervening push, matching token in source/
live and downloaded logs/provenance, and matching actual CSV/report hashes.
This is not an exact-endpoint version guarantee. Stale/mixed/ambiguous output,
missing token, source/config/version mismatch or failed validation meansNO SUBMIT.

Observation incident: the first live-log stream started at 04:35:48 UTC and
ended with ChunkedEncodingError before the token was observed. Its 128 events
remain in e26_v2_live_events.jsonl. This is a transport observation failure,
not evidence of a failed or restarted kernel. Independent operational review
approved one bounded read-only reconnect to the same still-RUNNING version.
At 04:42:13.533187 UTC the parent rechecked kernel ID, version 2, every cell,
all configuration/assets and RUNNING, then opened a 900-second observation cap
in e26_v2_live_reconnect.jsonl. No second push or execution restart. All original
token/source/hash gates still apply; reconnection success is not artifact proof.

The second observer also ended with ChunkedEncodingError at 04:45:19.225750 UTC,
after 185.69 seconds/297 events, last runtime 538.65 seconds, token count zero.
Independent SDK/log diagnosis showed that a connection replays history from
runtime 6 seconds, so continuous SSE coverage is unnecessary for the original
live-token gate. Parent fixes one final delayed read-only observation: no earlier
than 04:52:06 UTC (accepted push +1100 seconds), fresh full version/source/config/
RUNNING checks, 180-second cap, close immediately on the exact token. No more
connections if it times out/errors or misses the token; HOLD, not final-only
substitution. This changes only the parent's observation allocation, not the
run/candidate/Cloud retry budget or required provenance. If already COMPLETE,
do not manufacture live evidence. Preserve both earlier observation failures.

Final live observation succeeded: 04:52:56.221228 UTC fresh version 2/full source/
config/assets/Docker/RUNNING guards, exact token observed at 04:52:57.430588 UTC
with kernel runtime 871.661756943 seconds, immediate stream close, and status
still RUNNING at 04:52:58.144385 UTC. Elapsed 1.923 seconds, 304 replayed events,
exit 0. Evidence: e26_v2_live_token_snapshot.jsonl. Prediction completed at
runtime 871.174 seconds, reported 9.05 minutes. No further stream connections.
The live-token requirement is met; COMPLETE/fresh outputs/full integrity gates
remain pending and cannot be inferred from this observation.

## Physical acceptance and one exploratory submission

All10 CSV fields must validate: schema, finite integral int64 values, global
consecutive row IDs, node/edge sentinels, dataset blocks, node-before-edge,
unique nodes/edges, no dangling endpoints, t-to-t+1 edges and coordinate bounds.
Validate actual model/support hashes, configuration, GPU/runtime and no fallback.
Correction reports must contain the4 expected datasets, zero records retained
for unchanged datasets, and exactly the known public4 y256->255 correction with
magnitude1. Compare fresh CSV row-by-row against saved v1: every other field,
row, node, edge and ordering must be exactly unchanged. Additional differences
meanHOLD pending independent explanation and a new pre-run contract.

If all integrity gates pass, submit once under the actual verified kernel version
and filename`submission.csv`, not a manually patched local CSV. Bind the accepted
submission ID to version/token/output hashes. An uncertain response requires
reading submissions before any retry to avoid duplicates. Follow terminal score.
Local SCREEN remainsINCOMPLETE; this is user-authorized exploratory submission,
not SCREEN/PREFLIGHT success or generalization evidence. E23 publicLB0.924 and
the existing numerical adoption gates remain unchanged until new valid evidence.

Fresh read-only preflight on Sep7: official rules alreadyaccepted,5 submissions/day,
Notebook-only, CPU/GPU12h,offline,submission.csv; three existing Kaggle assets
reportCC0-1.0. GPU quota29.66h remaining of30h at04:06UTC. Refresh before push.
No additional assets are introduced. Publicv1 runtime was about20.3minutes;
hidden-test runtime and the project's9.6h buffer are not guaranteed by this.

Fresh pre-submission context at 04:44–04:45 UTC: competition API rank 920/3195,
deadline September 29 23:59 UTC, notebook-only and daily maximum 5 unchanged.
Leaderboard API's 16th and 17th rows both display 0.951. The recorded medal
formula gives a top-16 proxy (formula not newly reverified); planning target is
now 0.953 with the prior 0.002 buffer, not a change to any E26 scientific gate.
Submission limits return numTotal=6 and numAllowedNow=5; numToday is omitted,
not a measured zero. Current accepted list contains no E26 and E23 remains0.924.
Browser refresh could not run because the Mac was locked; these fresh values
come from the authenticated API, and the earlier same-turn rules read remains
the explicit rules evidence.

## Implementation failure lessons

Physical result (04:56 UTC): COMPLETE, before/after all 33 source/config/assets/
Docker/version checks match. Exact-version output returned 404 once; the single
reviewed latest retrieval had 173 unique files/no remaining page, two token
prints and matching provenance hashes. Only CSV, run_stats, bounds report,
provenance and full log were downloaded. Receipt:
outputs/local/e26_implementation/e26_bounds_v2_download_receipt.json.
CSV SHA is the preregistered expected 1a2975db15961ba4b92c67019b209ccbb1bd2e0a9c71011fd2595d82da6e3390.
Parent validator including canaries is VALID; every old/new CSV field agrees
except id11613 y256->255. Row count236052; node120460; edge115592.

The report's new evidence is six x lower-bound corrections in 6bba_05db0fb1,
node IDs7471,19919,21305,23706,24088,61812, each rounded-1->clipped0. The old
serializer already used max(0, int(round(float(...)))); the prior saved integer
CSV had therefore erased these entering negative values. The new report records
all round-to-clip changes, not only changes relative to the old CSV. This is a
parent expectation-design defect under investigation, not seven CSV mutations.
The earlier exact-one-total-report preregistration remains preserved above with
its FAIL result; it cannot be retrospectively represented as having passed.

Observed runtime markers: inference starts328.089s, completes871.174s (9.05min),
token871.662s, graph count1166.051s, CSV/provenance1273.686s, final export1285.713s
(about21.43min overall). Between token and graph count are DeepCenter loading
and enumeration; no claim this is pure loading time. No hidden-runtime guarantee.
No new training/Loss, E26 localSCREEN stillINCOMPLETE, E23 incumbent still0.924.

Full helper/test reauthoring repeatedly omitted stated validation rules or used
tests that failed for unrelated reasons. Single-function identity correction
closed that defect; running its test against pre-guard code proved sensitivity.
Integration oracles then confused separate kernel metadata with notebook metadata,
helper trailing newline, same-namespace exception classes, and CSV row ID0.
Four-def test-only correction fixed those; a compact prose label`node_id1` was
misread as a string, so four literal expectations were separately typed as ints.
All logic changes remain Qwen-authored. Parent formatting changed only import
grouping and literal line layout with AST-value equivalence, never test semantics.
Future handoffs should use explicit field=value/type notation and the smallest
changed definitions; pass schema/fixtures exactly and preserve accepted code.
