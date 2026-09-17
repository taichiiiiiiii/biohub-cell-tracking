# E26 implementation transport recovery

2026-09-06. Parent recovery record. The single local recovery worker TERMINATED
at its09:32 UTC supervisor cap, exit130, with no saved implementation or tests.

Current phase: deployed transport repair remains ACCEPTED, but recovery1 did not
implement unit02a. Session54736 is terminal, not a live wait. Client processes
and worktree lock are gone; at09:42:37 UTC upstream active0 and the old client/
backend connections were gone, confirming inference-slot release. No implementation retry, Cloud, extension or shared mutation is
authorized. Scientific unit02–04 and physical evaluation remain incomplete.
Earlier dispatch/wait descriptions are history, not permission to resume them.

## Fixed problem and evidence

E26 config-only unit02a ended with SSE idle timeout and no code. Its frozen task
and failed log remain unchanged. Scientific candidate, split, gates and the
unit02→03→04 dependency order are unchanged.

Shared-owner diagnostic evidence is preserved without modification under
`outputs/local/e26_implementation/sse_diagnosis_20260906/` (11 original diagnostic
files; subsequent fix-attempt evidence is added under distinct names). Parent
verified byte equality with the completed owner's evidence and rechecked the
saved five-case results; no second fixture execution or model call was made.

- REPORT.md SHA256: `8a2efba90d963d882277f5bd36d0d72aadc6ac8fd85f0877642cd10985adbda2`
- diagnose.py SHA256: `f9d31065c9884959171a598556408ef05a6f36bdf7592519d643c96be6c4d2f4`
- results.json SHA256: `51590a109d74ed819cb153e42c5addadf95f3bce39c9290f5d8a07a91ef36b77`

The isolated Codex 0.153.4 fixture used a 2-second idle timeout and 6-second
synthetic completion. Silence and comment-only cases exited1 around 2 seconds;
periodic in_progress data events reached completion/exit0 at 6.2302 seconds.
The separate raw receiver received 23 comments and completed. Each case made
exactly one request. This supports a client/comment compatibility defect.
Write success is not a Codex receive acknowledgment. The failed production
worker's binary identity, packet timing, queue/active state and reason for
backend silence are not established by this shortened synthetic experiment.

Independent SOL reviewed the complete fixture, report, results and all synthetic
stdout/stderr: SHIP for this limited mechanism diagnosis, no must-fix. The
`codex_version` result field is a fixture constant, not automatic runtime version
capture; the report's path/hash observations are supporting evidence, not an
immutable binding to the original failed worker. Do not infer more than that.

## Parent decision and next bounded work

Do not simply raise Biohub's client timeout. The shared bridge has a separate
600-second upstream read timeout; changing the client alone is not a demonstrated
repair and cannot establish backend progress. Do not fabricate model text,
reasoning, tool calls or completion to keep the stream alive.
In addition, the shared queue validates the complete fixed provider definition,
including `stream_idle_timeout_ms=600000`; a Biohub-only override is rejected.
Independent SOL identified this and the parent reread the matching queue check.

Ask the existing shared owner for a minimal protocol-compatible liveness design
and isolated acceptance tests, not a whole-service rewrite. Its proposal must:

- Preserve event sequence/terminal ordering and report only a true active state.
- Cover queued and active upstream silence beyond a shortened client idle limit.
- Preserve single-inference ownership, disconnect draining and no duplicate
  requests; terminal/error stops liveness and unconfirmed upstream termination
  remains fail-closed.
- Keep the separate upstream timeout and a finite total worker supervision cap
  explicit. A functioning heartbeat is not evidence of useful model progress.
- Use only synthetic responses on isolated loopback for initial verification.

Source implementation, deployment, service interruption and unit02a retry are
separate decisions after independent review. No new service, worktree, model,
Cloud request, purchase or quota reset is authorized here. Subscription coverage
and available quota remain prerequisites for any otherwise eligible Cloud task;
unattended goal work remains local-only.

Once a reviewed repair is actually deployed and operationally verified, the
parent may explicitly decide a bounded attempt budget for the original config
scope. This document does not grant that budget. No scientific gate may be
removed to compensate for implementation infrastructure failure.

## Shared-owner candidate design received (not implemented)

Use `response.in_progress` to report the same accepted response's known unfinished
state, not an assertion that a queued backend inference has begun. Preserve its
id/created_at/model/current public output snapshot; do not expose pending tools
or invent text, reasoning, usage or completion. The initial created/in_progress
events remain first. OpenAI's [streaming-event reference](https://developers.openai.com/api/reference/resources/responses/streaming-events)
defines this event and its response/sequence fields; periodic replay support for
every client is not guaranteed by that documentation. Local acceptance is required.

The proposed minimal change is a ResponseStream liveness method and an optional
ClientChannel callback, retaining comments for other callers. A single stream
RLock covers state mutation, snapshot, sequence assignment and send for start,
consume, finish, fail and liveness. Lock order is state then channel-write only;
close/join never runs with the state lock held. Locking emit alone is insufficient.
Terminal transition and send are atomic relative to liveness. Stop liveness on
disconnect/stopped or known protocol error awaiting drain; send only after normal
data inactivity (about 5 seconds). Keep scheduler, finite queue/upstream timeouts,
drain ownership and unconfirmed-completion blocking unchanged.

Required isolated acceptance for this candidate, before any deployment decision:

1. Keep old comment-only RED; use the actual bridge/scheduler with fake backend
   and actual isolated Codex to show queued and active 6-second silence survives
   a 2-second client idle limit. Exactly one upstream inference per admitted request.
2. Two-request FIFO/max-one-active tests, queued disconnect with no backend call,
   active disconnect retaining ownership through confirmed finish/EOF.
3. Barrier-controlled heartbeat versus finish/fail/incomplete/protocol-error races:
   created first, unique monotone sequences, at most one terminal, no data after
   terminal/DONE, no leaked pending tools or fabricated/duplicate output.
4. Write failure/close must not deadlock; shortened fake upstream timeout or
   unconfirmed EOF must still fail/mark blocked/refuse new work without retry.
   Confirmed normal EOF must not mark blocked.
5. Existing function/freeform/compaction/queue/interleaving regressions remain
   green; retain tested binary/source identities and synthetic-only evidence.

Deployment would require a bridge restart (not a backend restart). It may occur
only with coordination and the existing maintenance exclusion, active=0,
waiting=0, blocked=false and no unresolved drain. This design request does not
authorize stopping another task. Independent SOL design review: SHIP for offline
implementation/isolated testing only, not deployment or a new Biohub attempt.
Inactivity must mean time since a successful data/state event; ordinary comments
must not indefinitely suppress the new liveness callback.

## Parent dispatch after design review

The parent now requests the shared owner to implement the bounded candidate in
an isolated copy and run the above synthetic acceptance/regressions. This is an
explicit next phase after the earlier design-only request, not a silent retry.
Follow that owner's applicable implementation-author and spending constraints;
do not use paid/model fallback if those constraints prevent implementation.
Return source/diff, commands/results, executable hashes and independent review.
Do not edit loaded production sources/config/queues/launchers, contact production
ports, stop/restart services, invoke a real model/Cloud, or alter Biohub scientific
source/tests/frozen tasks. Deployment and unit02a retry remain unauthorized.

Shared owner acknowledged this same implementation request and is working under
`/private/tmp/flash-sse-fix-DETGu9`. It confirmed that its shared-infrastructure
task has no separate sole-author model seal; its parent writes the isolated
candidate without model calls and will obtain an independent review. This does
not change Biohub's Qwen-only scientific implementation rule. No second worker
or paid fallback was created, and the candidate is not yet accepted/deployed.

## First isolated verification: not accepted

The 2026-09-06 08:18:44 UTC candidate result recorded 59 tests, 1 failure, 0
errors (61.427 seconds). New active/queued/nonempty-snapshot Codex cases completed
after about 6 seconds; the old comment control still failed near 2 seconds.
The failure is `test_real_codex_compacts_and_continues_after_tools`: the expected
`probe_verify_5` tool result containing `VERIFIED` was absent from the inspected
`raw_requests[5]["input"]`. Do not waive this existing continuation requirement.
This is not yet evidence that the production failure is fixed.

Parent preserved the first failure, without rerunning the fixture:

- `fix_attempt1_verification.json` SHA256 `1d35ca01bf96bafc7d2b5862d4220b15c1a912fd8d98da16e55dcbb1b4563708`
- `fix_attempt1_tests.log` SHA256 `55bdb3e015955f6e51d135368f4be5c9ce60ba560f0471662a3ef39ed670d594`

These files are in the evidence directory above. Shared owner is diagnosing;
an additional read-only independent diagnosis may inspect fixture/index assumptions
versus a real continuation regression, but must not edit or rerun concurrently.
Production source hashes were unchanged in the verification receipt. Model/Cloud/
credential-helper calls were all zero. No deployment or Biohub retry is authorized.

Owner's follow-up diagnosis found tool-level exit71 (`sandbox_apply: Operation
not permitted`) under nested inner/outer sandboxes; it retained the tool-result
and file assertions and adjusted only the isolated fixture. The parent later
read the mutable `compaction-tool-results.json` after that adjustment and saw
successful patch/VERIFIED results, including request5. Do not use that overwritten
file as evidence of the earlier failure or infer full-suite success from it.
At that read, both candidate source hashes still matched the first verification
(`3cc7968d...` and `e068eca1...`). Full rerun and independent review remain pending.

Independent read-only diagnosis checked the owner's preserved
`attempts/failed-081844/`: request5 contains the correct probe_verify_5, but its
tool failed with sandbox exit71, as did earlier tool calls and file creation.
The assertion correctly detected failed tool execution, not unstable indexing.
No liveness regression is demonstrated by this failure. Keep all original
request/history/VERIFIED/file-content assertions.
Owner reports a fixture-only single-sandbox correction: outer network restriction,
fixture-only writes and home-read denial, with the inner redundant sandbox removed.
The unchanged candidate passed the compaction case alone, and a new negative test
checks actual rejected outside writes/home reads/nonfixture loopback access.
These owner-reported results still require full 60-test rerun and independent
implementation review before acceptance; production security settings are unchanged.

The 08:23:39 UTC full rerun recorded 60 tests/1 failure/0 errors (61.067 s),
not acceptance. Compaction now fails earlier at the CLI exit assertion with
`Error: Operation not permitted (os error 1)`, distinct from the earlier nested
tool exit71. The new isolation-boundary negative test passed. Candidate source
hashes are unchanged. Parent preserved `fix_attempt2_verification.json` and
`fix_attempt2_tests.log` beside the first attempt and informed the same owner.
Single-test success must not replace full-suite success; fixture startup/order
differences remain to be diagnosed. Production deployment/Biohub retry stay HOLD.

Parent read the complete 173-line candidate diff, terminal methods and the
independent review/report/test script. The reviewed source hashes match those
above; no new source blocker was found. Parent independently reran the four
in-memory review tests with before/after source-hash checks: PASS. This includes
40 paired producer/liveness runs with forced nonempty overlap, immutable
snapshots, ordered unique sequences/terminal, error suppression and success-only
clock updates. No server, socket, model or fixture-file write was involved.
This limited check does not substitute for the still-required full-suite rerun
or real-Codex/fake-backend integration evidence. No production acceptance yet.

Latest full rerun, 08:26:46 UTC: 60/60 PASS, 59.835 seconds, source/native hashes
unchanged. Parent read verification.json and the completed tests.log and retained
them as `fix_attempt3_verification.json`/`fix_attempt3_tests.log` without overwriting
the two failures. Active/queued/nonempty controls completed around 6.1 seconds;
the old-comment RED exited1 at 2.1015 seconds. Compaction now passes with the
fixture child cwd explicitly set to its workspace, retaining outside-write,
home-read and network restrictions plus all original continuation assertions.
The second failure's inherited home cwd conflicted with home-read denial; it is
separate from the first nested-sandbox failure. Owner's independent final review
of these full results is pending. Tests passing is not live deployment/recovery.

## Final acceptance and conditional deployment request

The final independent acceptance review is ACCEPT for the isolated candidate.
Parent read it and archived the complete 50-file bundle (264,941 bytes) under
`outputs/local/e26_implementation/sse_fix_20260906/`, checking every copied byte.
The two failed runs, final source/tests, reports and independent review are retained.
Inventory SHA256 over sorted path/bytes/SHA records encoded with JSON sorted keys
and compact separators is `a8a8d3cfda389f3c494d2b04d22c23b43f4211e48ed95b6644b5b0a3d5df4cd5`.
Final review SHA256: `6cf7d68e2ba09ce7c32a8a10057006e098c1cdb3c02ea9db4c04eea3fe5b9a91`.

Parent observed read-only health active0/waiting0/blockedfalse (started35). This
is a point-in-time observation, not permission to skip deployment-time checks.
Parent explicitly requests the shared owner to apply only the reviewed candidate
when maintenance exclusion, coordination/new-admission control and absence of
workers/requests/unresolved drain are confirmed immediately before transition.
Do not interrupt another task to create that opportunity. If those conditions
cannot be established, defer deployment and report why.

Retain old source/permissions/hashes and recovery instructions. Restart the bridge
only, keep backend/queue/config/catalog/authentication and repo code unchanged.
Preserve matching verification artifacts and document the correct regression
entry rather than leaving contradictory old/new test expectations unexplained.
Record exact installed bytes, new bridge PID/launch path, unchanged backend PID,
read-only health and maintenance exclusion release. No live-model/Cloud smoke or
Biohub unit02a retry is included. If rollout fails, stop and report safe restoration
options from the saved preimage; no unreviewed fixes or restart loop.

## Conditional implementation recovery draft

Parent prepared `analysis/e26_unit02a_recovery_task.md` (SHA256
`d699f849e8d95b807795800f1a342eca1b53754e58607c9e2fea0d032c603915`).
Its body from `## Authoritative context` onward is byte-identical to the frozen
failed task, confirmed by parent diff. Only the header proposes recovery after
deployment acceptance and fresh queue/worktree/identity preflight, with one local
attempt, a fixed 45-minute cap including queue time, no extension and zero retries.
Independent review returned conditional design SHIP: exact scientific body,
one-attempt budget, local-only routing and deployment/preflight separation are
preserved. This review alone is not launch authorization.

## Deployment receipt and parent verification — 2026-09-06 08:43 UTC

Shared owner completed conditional deployment. Evidence is retained at
`/Users/taichi/.local/share/qwen-flash/sse-deploy-20260906-pOEEz2/`:
`DEPLOYMENT.md`, `maintenance.json`, `deployed-verification.json`,
`deployed-tests.log`, `preimage/` and `ROLLBACK.md`.
Parent read the report and verification receipt and independently checked the
installed source hashes: bridge `3cc7968d75def38d171e258d994a3ce145e1140980291c9f0a2cc107e34779e5`,
scheduler `e068eca148203f6276448becde5ce4323f0640584787bd260a48f69595da9775`.
These are the accepted isolated candidate bytes. Live PID checks found bridge
33154 and unchanged backend 61759. Read-only health was ready, active0/waiting0,
blockedfalse, started0 (process-local counter reset by the bridge restart).

Owner's post-deployment suite imported the deployed sources and passed 33/33
tests in 10.046 seconds at 08:42:10 UTC, using a fake backend/random ports only.
This is not a repeated 60-test run or a live-model smoke. Nine protected files'
hashes/modes/owners were unchanged across the suite. The first maintenance
window expired before STOP without changes; the second restarted only bridge,
and all maintenance locks were released at 08:40:43 UTC. No model/Cloud request
or scientific retry occurred as part of deployment.

Parent separately confirmed the approved worktree is clean at branch
`feat/e26-motion-relink-off`, HEAD `3ecd535e44a90cce3bf43d6f31bdba5c525f2e9c`,
with no implementation lock. Launcher/shim/policy hashes remain respectively
`5705d3ab01770b1ce180ca7154d511843e38b81e7a5bc65828bed177a39a3d69`,
`436aabcdcace448d2cac703424b63dd10805aedea9c9076c257ea4ecbca6d9d7`,
`28fecd0381c4dd1fe9a829ca8c2055514386ed82f7a10fff506119664db1f87d`.
The unchanged provider definition is inline in that launcher: loopback11436,
local Flash, no auth, zero request/stream retries, 600000ms SSE idle limit.
Shared queue SHA is `9f526618e2ee466fb2a97d24c00b6f6d8f8ff8467fffc1fbbbe99b7e9f675e7e`;
local catalog SHA is `97007e1385c3774cfb69d78b13a7d8c39274bac9403e8e010e712ed384db0238`.
Native Codex SHA is `b973d440acac501fd2594a43e7ca9ce41e0a65b9dfb28d0d7a7837c99e1261e3`;
its JS launcher SHA is `61b0194f3bb6534439c8d26a3ed57d0805f84b884588b761795323eeb92fcf70`.
Independent deployment audit returned SHIP: it checked exact candidate/deployed
byte equality, matching modes/owners, live listener PIDs/start times, absent
maintenance guard and no holders on the three maintenance locks. Its fresh
checks did not query health; the parent performed the read-only health check.

At 08:46 UTC the parent explicitly accepts these checks and the conditional
design review, and authorizes exactly one default local Flash recovery dispatch.
The task's header is changed from DRAFT to accepted; its scientific body remains
byte-identical to the failed task. This is a new bounded operational decision
based on a reviewed, deployed repair, not an automatic retry of the old process.
The queue-inclusive cap is 2700 seconds from launch with zero extensions;
an outer supervisor sends INT to the owned launcher at that deadline so the
existing signal forwarding can cancel/reap its child. Any retained lock or child
requires inspection, never lock theft or a replacement launch. Cloud remains off.

### Recovery1 dispatch

Accepted task SHA256: `a9815c7019e2a1d650d9136bcc3a928b094b417210cfd9cd5de5b16c54f42416`.
Parent confirmed the unchanged scientific body again and ready/idle/unblocked
health immediately before launch. Start `2026-09-06T08:47:00.109047+00:00`,
deadline `2026-09-06T09:32:00.109047+00:00`; launcher PID66751, session54736,
thread `01a075e6-453f-7aa2-8d54-087695d85948`. Queue admission0.00s, route=flash,
model=qwen38-flash-next, automatic_retry=0. The outer supervisor enforces the
2700-second queue-inclusive deadline; no new repository source was authored for
supervision. Log: `outputs/local/e26_implementation/unit02a_flash_recovery1_WORKER.jsonl`.
Poll this same live handle; do not infer termination from quiet output or start
a replacement. Parent/independent code review and tests remain prerequisites
to accepting any Qwen result. Unit02b–04 and physical scoring are still pending.

### In-flight bounded-read diagnosis — 2026-09-06 09:20 UTC

This is an intermediate observation of the same live session54736, not a
terminal verdict or a new launch. Independent log audit examined the first
52 lines/80,958 bytes of the append-only worker log. Parent confirmed that exact
prefix length and SHA256 `56b89a4f6c60eb9f007e5cba06fad87785044e2e03a9e67634ee78418b0fbbcb`.
The snapshot contains 22 command starts, 20 exit0 and two exit1, with 63,076 bytes
of saved command output. No patch/file-change/pytest/Ruff result is present.
Parent's current read-only worktree check is still clean with no new files.

The task allowed AGENTS and config.py438–470 reads, but the worker listed
directories, read most of config, pyproject and unrelated adapter/ST-R3 code,
and searched the repository. An explicit AGENTS read is not visible in this log;
that does not prove it was absent from the client's injected instructions.
Item19 is an item-level compaction accuracy warning, not turn failure: subsequent
items20–24 continued with messages and more read commands in the same session.
Re-exploration is observed; its causal relation to compaction, actual token count
and number of compactions are not established by the warning or byte counts.

Parent corrected one detail in the audit's failure classification against the
actual command output: item10 reports `zsh:1: == not found` from its compound
command (which contains `echo ===`), not evidence that missing-file/grep no-match
caused that exit. Item14 reports a mistyped-directory cd failure. Neither is an
implementation test failure. The accepted diagnosis is bounded-read noncompliance
with no observed implementation yet, not a terminal transport/quota failure.
Continue only this already-authorized handle under the unchanged09:32 UTC cap;
no extension, Cloud, replacement task or scope substitute follows from the audit.

### Offline next-action capability check (not adopted or deployed)

Parent used OpenAI Docs to check whether the observed read-scope drift can be
guarded without changing the scientific task. The fetched official
[hooks reference](https://learn.chatgpt.com/docs/hooks) documents PreToolUse
denial for Bash/unified exec and apply_patch, but explicitly describes tool hooks
as guardrails rather than a complete security boundary. Unsupported outputs and
specialized bypass paths mean an assumed fail-closed policy is not established
by that page alone. The [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
also documents shell_tool and unified_exec flags; disabling commands outright
would remove the worker's required test capability and was not selected.

Read-only installed `codex features list` reports hooks/shell_tool/unified_exec
stable and true. The first diagnostic form with global --ignore-user-config was
rejected by CLI parsing and launched no model. No configuration, source, hook,
worker or shared service was changed by these checks. Shared queue validation
pins model/provider/catalog but its source inspection alone does not establish
that any future hook configuration will be accepted or enforce the desired calls.

If the current attempt ends without usable work, a possible separate harness
proposal is a narrow pre-tool command allowlist retaining the exact allowed
reference reads, named-file patches and mandatory pytest/Ruff commands. Before
adoption it would require independent review and isolated fake-backend tests of
actual installed-client coverage, invalid/timeout cases and explicit denials.
No new retry, hook implementation, scientific gate reduction or model switch is
authorized here. In later live output item28 the worker did explicitly read
AGENTS; the earlier snapshot's read-not-observed statement remains historical.

## Recovery1 terminal outcome — 2026-09-06 09:32 UTC

The outer supervisor reached its fixed2700-second cap and sent SIGINT to its
owned launcher66751. Session54736 returned exit130; supervisor recorded
elapsed2700.19s. A native warning at09:32:00.207979 UTC says the task did not
complete gracefully within100ms, followed by the supervisor's finished record.
This is supervisor cancellation, not an SSE idle or provider error.

Final immutable log:79 lines/129,702 bytes, SHA256
`d21ef2fbe5b82d80429b52f66dbe21523236630afc74d3783c312c2e81771f42`.
Independent final audit found34 command starts,32 exit0,2 exit1 and99,697 bytes
of command output: read/search/version checks only. Patch/file-change/new source,
pytest runs and Ruff checks were all absent. Earlier shell/path failures are
diagnostic-command exits, not implementation test failures. No stream disconnect,
SSE idle timeout, provider error or turn.failed was present. Their absence does
not certify model usefulness or general transport reliability.

Parent checked at09:32:18 and09:35 UTC: approved worktree clean at
`3ecd535e44a90cce3bf43d6f31bdba5c525f2e9c`, both target files absent, implementation
lock absent. Supervisor66738/launcher66751/queue66893/node66916/native67005 were
all absent in the post-exit PID check. No lock was stolen or manually removed.
AGENTS and both unrelated raw-provenance WIP file hashes remain unchanged.

Shared owner independently observed the client-side bridge connection CLOSED
but its backend connection ESTABLISHED, same bridge33154/backend61759, with
health active1/waiting0/blockedfalse/started36. This is consistent with cancelled
request drain still holding an inference slot, not proof of forward progress or
drain completion. The600-second socket timeout is not a total drain deadline.
Parent's09:35 health recheck still had the same values. No backend/service restart,
new model request, Cloud call or interruption of another task was performed.

Outcome: implementation attempt exhausted, no code to adopt/commit/test/submit.
Keep all evidence and the full scientific goal. A next operational design may
address repeated unauthorized read exploration, but the capability note above
does not authorize a hook change, model switch or another worker. First confirm
upstream release and separately review any proposed execution-policy change.

### Upstream release confirmed — 09:42:37 UTC

Parent read-only health now reports active0/waiting0/blockedfalse/started36.
`lsof` for the same bridge33154 shows only11436 LISTEN; the known closed client
connection and established backend connection56163→11435 are both absent.
This resolves the earlier unconfirmed-drain state. It does not provide the exact
completion time or certify useful model output. No restart or new request was
used to obtain the idle state. Shared owner was informed; no added work requested.

The separate [execution-scope proposal](e26_worker_scope_recovery.md) is a draft:
shell-disabled Qwen code/test authorship, full parent-run original tests and
independent acceptance. Its native-client/fake-backend capability probe and
design review are in progress. No launch configuration or scientific source
has changed, and no live attempt is authorized by the draft.
