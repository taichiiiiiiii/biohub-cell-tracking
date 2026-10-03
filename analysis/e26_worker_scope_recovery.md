# E26 implementation execution-scope recovery

2026-09-06. Operational design and isolated capability proof accepted after
independent SHIP reviews. Parent created the minimal per-repository configuration
delta, accepted after a separate exact-identity review. The local attempt budget
in e26_unit02a_patch_task.md is historical and closed, not a current launch
instruction. Current routing and terminal Cloud outcomes are recorded below.
Preserve recovery1 and its final log unchanged.

## Superseding direct-user Cloud request (2026-09-06)

The historical local-only recovery design below is retained as evidence, not
current routing authority. The user explicitly requested Qwen Cloud exact
`qwen3.7-plus` implementation, subscription-only. Parent cancelled local patch1
for that model change: exit130 at10:18:55.483628 UTC after852.59s, supervisor
timeout=false. No source/test files were created; worktree clean, client PIDs
91255/91311 gone and implementation lock absent. Final log15lines/2521B has
SHA256 `9b0bf9033dc8ee32edef111d506e523d89d2aa1aef4736c8bf98baf5f8497304`.
Backend active1/started42 at10:27 is separate unconfirmed upstream drain; do not
restart shared services or infer that client closure drained the local backend.

Logged-in QwenCloud usage refreshed19:22:41 JST: Individual Plan Pro Active,
remaining95.1%, total40000, no credit packs. Official QwenCloud Token Plan
overview lists qwen3.7-plus; quickstart gives the same dedicated Token Plan
endpoint checked by the existing shared queue. The UI supported-model panel
also contains 'No supported models', so UI alone does not prove model access.
An actual request must remain on the verified subscription endpoint and stop
on access/quota errors, without PAYG, purchases, resets or model fallback.
Sources: https://docs.qwencloud.com/token-plan/personal/token-plan-personal-overview
and https://docs.qwencloud.com/token-plan/personal/token-plan-personal-quickstart .

New separately identified `e26_unit02a_cloud_task.md` preserves the complete
scientific/reference/test suffix of the reviewed fullcontext draft. It permits
one direct-user, parent-supervised Cloud attempt capped at1200s, extensions0,
retries0. No unattended heartbeat/goal/automation Cloud execution. It requires
independent routing/task review and clean single-owner preflight before dispatch.
Its Cloud route does not need local inference capacity: client/worktree closure
is mandatory, backend drain remains separately recorded, never called resolved.

Cloud launcher and corrected handoff independent review: SHIP, no must-fix.
Final task SHA256 `f64264a5afce6437d7f06ac927b85ec998c5f47d9111e52e571e3b9ba4a1f0a3`.
The scientific/reference/test suffix matches the old draft apart from one final
blank line; no scientific content changed. Parent corrected the transport wording
to permit only launcher-managed Codex provider/auth flow, not model-generated
network or credential calls. Launcher SHA256
`b9c3a7733dbb0eb7635fe6c198a5c79801438be10ee6a09812c1ccc1552ecac8`, policy
`3e42a1ce182cebf3e1bc3ea4fe53e98398a2f9a26507817f5dbb7d73e65d0a59`, test
`8ff055a63c990e47653b3d8fe40cb1b21cebe1a9a1a32ecd4d108b99d333db84`.
Exact3file diff SHA256 `6fbdac10712c10d83b3e2657719be98c9beef57a887a72900d6a3c6ba6c442ea`.
Parent read the complete final diff;529 tests PASS15.89s plus Ruff/sh/diffcheck.
Configuration-only commit canonical7368cebe2d445e7eb6d0492133fdfb9aed9e51f7,
approved worktree sync a17eb0203ee791161f18774a1987e4f3dfd6c7fa. Its same529 tests
PASS16.40s plus Ruff/sh; clean worktree, no target files and no owner lock.
No AGENTS/unrelated WIP/shared queue edits or push. Old backend later reports
active0/waiting0/blockedtrue/started42; do not claim healthy/drained or repair it
as part of this Cloud task. Parent now authorizes the reviewed single1200s
direct-request Cloud handoff; log target unit02a_cloud1_WORKER.jsonl is unused.

At10:37:44.310469 UTC the single Cloud attempt started: session5682,
thread01a0764b-a76f-7ad3-8561-225b32f306cd, launcher70288/supervisor70278,
deadline10:57:44.310469 UTC. Queue admitted0.00s with
mode=subscription-cloud-only, route=cloud, model=qwen3.7-plus, automatic_retry=0.
This proves selected runtime routing, not yet useful code, accepted tests or an
accuracy result. Preserve this session; no second attempt or deadline extension.

That patch-authoring attempt is now terminal: parent stopped it after three
identical patch parser rejections at10:38:04,10:38:42,10:39:21 UTC. Exit130 at
10:39:59.715020 UTC,135.4s, supervisor_timeout=false. The final model message
recognized that added lines need '+' prefixes, but no corrected patch was
accepted before closure. Full rejected patch inputs are not retained; do not
claim a provider/Unicode/root-cause diagnosis. No files created, worktree clean,
lock released. Final log14lines/2188B SHA256
`b269513bad3d31fcc9d411a2325f6d243cc70a9fa4e11ff2f7ee1d8a903cf6ca`.

Parent is redesigning delivery within the user's current directly supervised
implementation request, not restarting the frozen patch task or an unattended
goal loop. New `e26_unit02a_cloud_delivery_task.md` asks Qwen to author exactly
two full Python file bodies in its final response, with no tool calls. Parent
will parse the two strict labels/fences, verify byte-preserving extraction and
mechanically apply only to the two absent approved paths after reading all code.
No parent-authored scientific fixes or filled-in placeholders. Scientific body,
full config reference, parent tests and independent adoption review remain.
The different delivery task requires separate independent review and one newly
recorded600s cap; no extensions/transport retries/model fallback/PAYG. Provider
use remains an interactive response to this direct user request, not scheduled
automation. A failed or incomplete delivery stops without repeated relaunches.

Independent delivery handoff review: SHIP after adding mandatory pre-apply
tool-event/error0, complete-log, still-absent-target and same-clean-state checks.
Accepted task SHA256 `858f93d758a9cd1cf0f5fd3a20b8ad938140f5a5b15410f0c083599efe7b7267`.
Parent read the revised header; all scientific requirements/reference/verification
remain unchanged. Before dispatch worktree HEADa17eb0203ee791161f18774a1987e4f3dfd6c7fa
is clean, old process/lock absent, two targets absent and new log unused. Parent
allocates the reviewed single600s delivery cap within this direct user request.

Delivery1: session14344, thread01a07651-db76-7740-894d-d3df37a4802a,
10:44:30.878302 to10:46:12.838484 UTC, exit0,101.96s, timeoutfalse.
Runtime admission again exact subscription-cloud-only/qwen3.7-plus/retries0.
Complete log has one agent-message containing exactly two requested Python
blocks, no tool events/errors, and normal turn/supervisor completion. Before
mechanical apply, targets remained absent and worktree at the same clean HEAD.
Parent read both full bodies, applied them unchanged only to approved targets
and compared the complete contents to the extracted Qwen blocks: byte-identical.
Source SHA256 `0e06ac2ef5bede82366f75f3ee34607e6d4ffbe6e69b8c154603ae931465b8d7`,
tests `5e0e7660c0fc006b211e16c5f62d6e1ccf55ab3db7906e1172db246f540ef362`.

Delivery succeeded, scientific acceptance HOLD: public4 incorrectly uses base1
instead of required e23, and its test incorrectly endorses that preset. Parent
original pytest:4failed535passed2.09s; all four failures concern specialized
motion/twin error regexes preempted by the generic field validator. Ruff fails
17 violations (two unused imports, import organization,14 overlong lines).
No accuracy/scoring/submission or scientific commit. Parent does not edit the
Qwen-authored code. Independent review will bound a correction task preserving
the full science and tests. `e26_unit02a_cloud_revision_task.md` is a separately
identified reviewed-defect delivery draft; do not dispatch before independent
review and archiving only these two newly generated files to restore clean state.

Independent source/test review HOLD confirms the public4 science error, four
unreachable literal checks,17 Ruff issues and missing explicit pair/public4/
coordinated-path-drift/None coverage. Parent retained all requirements and chose
the review's source check-order correction, not weaker regexes. Revised task
SHA256 `eb21bb67fe53b75c75ff2d4acee0407e6b1aa583c3e278bbc6665965e195a5ce`:
independent handoff review SHIP. It includes previous full Qwen output, original
science/reference/tests, no-tool/complete-log/byte-apply guards and600s cap.
Parent moved only the two generated untracked files into ignored evidence
`outputs/local/e26_implementation/unit02a_delivery1_source.py` and
`unit02a_delivery1_tests.py`; hashes unchanged, recoverable, no deletion of user
work. Worktree restored to the same clean HEAD, owner lock absent, new revision
log unused. A single supervised correction delivery is allocated for those
reviewed defects within the current direct user implementation request; no
unattended loop, repeated transport attempt or scientific commit is authorized.

Revision admission stopped before model execution at10:51:17.862559 UTC:
shared queue reported `cloud-only subscription slot is busy; no wait or fallback`.
Supervisor exit2 at10:51:18.095014 UTC,0.23s, timeoutfalse, no thread/model request
started by this attempt. Log `unit02a_cloud_revision1_WORKER.jsonl` SHA256
`c5a25d50785eebdf507406e331d5830474dc20a45e0071496312fa18b40c31d1`.
Worktree clean and owner lock absent. Read-only lsof gave no identifiable holder;
that does not prove release. A separate nonblocking diagnostic flock also failed
with EAGAIN/Errno35, confirming the subscription slot was busy at that observation.
Current availability has not been rechecked; do not infer that it is still busy.
No owner was identified, interrupted, unlocked or displaced; no polling relaunch,
PAYG, other model, new worktree or asynchronous Cloud retry was scheduled.
Current status: exact Cloud model configured and useful Qwen code received, but
unit02a remains unaccepted; reviewed correction handoff is ready and has not run.
The single-admission failure is not a provider timeout, quota exhaustion proof,
or an accuracy result. All old outputs remain recoverable evidence.

## Fixed evidence and hypothesis

Recovery1 ran for2700.19 seconds, exited130 at the supervisor cap and produced
no patch or test execution. Its final log contains34 shell command starts and
99,697 bytes of command output, predominantly repeated source exploration despite
the bounded task's explicit read limit. An intermediate compaction warning was
nonterminal; the log does not establish its exact count or causal contribution.
Transport repair did not establish useful implementation progress.

Hypothesis: removing shell execution from the implementation worker, while
supplying its complete reference context, eliminates the observed exploration
mechanism and permits it to author the required code/tests. This hypothesis is
about task execution, not scientific accuracy or a new tracking candidate.
Do not reduce the APIs, test coverage, original unit02b gates or unit03–04 scope.

## Proposed division of work

- Qwen remains author of the two unit02a implementation/test files. No SOL
  substitution for scientific application code, no alternate provider, Cloud,
  PAYG, purchase, quota reset or automatic retry.
- Parent supplies the complete bounded task and byte-pinned relevant source
  excerpts inline, including the existing config public API. The worker does
  not need repository discovery to obtain its specification. Original policy
  and worktree scientific instructions remain applicable.
- Proposed configuration delta is only disabling shell_tool and unified_exec
  for the worker while retaining a working apply_patch tool. Keep fixed local
  model/provider, common queue, registered clean worktree/branch lock, retries0,
  sandbox/network restrictions, current native client and catalog unchanged.
  This is a proposal for per-repository launch configuration, not a change to
  shared services or a scientific-code implementation by the parent.
- The worker creates the complete required module and tests with apply_patch,
  reports changed files and explicitly reports that it did not run commands.
  Do not let it claim tests passed or request another tool/model to run them.
- Parent first reviews the entire generated source and tests, then runs the
  exact original pytest suite and Ruff checks. A separate SOL reviewer checks
  contract completeness and implementation defects. Failed or incomplete work
  is not adopted. All original validation commands still must actually pass;
  only their execution moves from the shell-disabled worker to the parent.
  This operational role change requires independent acceptance before dispatch.

Do not silently count this as the old task's worker-side tests having run.
Keep the old task frozen; if the proposal is accepted, create a separately
identified handoff retaining all scientific obligations and recording this
test-execution responsibility change. Unit02a remains incomplete until the full
parent/independent acceptance, and unit02 as a whole still requires unit02b.

## Capability proof before any adoption

Official [configuration documentation](https://learn.chatgpt.com/docs/config-file/config-reference)
describes shell_tool and unified_exec. It does not prove that disabling both in
this installed custom-provider client retains apply_patch or blocks every shell
dispatch. Do not infer that guarantee from a feature-list value.

Use an isolated fresh fixture, actual pinned native client and fake Responses
backend on a random loopback port, not a real model or the production ports.
Keep an empty isolated Codex home and an outer OS boundary denying user-home
reads, network other than that fixture port and writes outside the fixture.
No credentials or account calls. One case has a30-second supervisor cap, the
whole probe120 seconds, retries0; retain any failure and its diagnostic outcome.

Minimum evidence:

1. Capture the actual advertised tool set in the current default control.
2. Capture the set with both proposed flags false; establish shell/exec_command/
   write_stdin are absent and whether apply_patch remains available.
3. If patch remains available, send one fake toy patch and confirm only its
   expected fixture file/content is written, then verify the resulting tool
   response. No Biohub source is generated by this diagnostic.
4. Send a forbidden shell call and prove its sentinel side effect is absent;
   preserve the rejection response. Tool-advertisement absence alone is weaker
   evidence than actual dispatch rejection.
5. Save exact argv, client/catalog/source hashes, calls/results and isolation
   details. No retry against a real provider to compensate for a failed probe.

This is a narrowly tested operational guard, not general adversarial filesystem
isolation, a model-quality benchmark or proof that the next Qwen task will finish.
In particular, apply_patch can modify files and test code must be reviewed before
execution. Never describe missing shell tools as proof that all other reads or
all unwanted actions are technically impossible.

## Adoption and stop conditions

Only after a successful probe and independent design review may the parent
consider the minimal launch-configuration change, rerun all launcher regression
checks and obtain independent review of that exact delta. Keep model routing and
scientific authorship fixed. Do not bypass the shared queue or create another
worktree. No hook engine is needed for this proposal.

Before any later live dispatch, separately confirm the cancelled upstream request
has released its inference slot, deployed services are suitable, and the approved
worktree is clean/unlocked at the expected identity. Record the new task and
launcher bytes plus an explicit single-attempt time cap. This proposal allocates
no live attempt, deadline extension or retry budget. A failed capability check
means HOLD, not shell re-enablement, Cloud fallback or a weaker scientific task.

## Accepted evidence and current implementation status

- Independent operational design review: SHIP. Separate patch-authoring handoff
  `e26_unit02a_patch_task.md` reviewed at SHA-256
  `6b359d34e937a390b7ef0704942fdf255cc274dffe88b8627cdf46bb6edfd938`:
  SHIP, original scientific body and parent-only full test execution preserved.
- Isolated probe: PASS; independent artifact/source review: SHIP. Archived under
  `outputs/local/e26_implementation/tool_gating_20260906/`; REPORT.json SHA-256
  `a0cd2d431aa0c4b1b8f9c1a3bd0534200dd835200da2fd34bba83ec04e405d5b`.
  Default advertised exec_command/write_stdin/request_user_input/apply_patch/
  view_image. With both flags false, all three requests advertised only
  request_user_input/apply_patch/view_image. A toy apply_patch succeeded; an
  unadvertised exec_command returned unsupported call without its sentinel file.
  Both cases exited0 (0.126399s and0.097750s), no timeout or real model/Cloud/auth
  helper/production-port use. Client0.153.4 native hash remains
  `b973d440acac501fd2594a43e7ca9ce41e0a65b9dfb28d0d7a7837c99e1261e3`.
- Probe scope limitation: advertised tools are normalized in REPORT from in-memory
  requests, not separately archived raw HTTP request bodies. Full probe source and
  stdout/stderr are retained. This proves that client combination's local dispatch,
  not general OS isolation, Qwen behavior, target-file enforcement or model quality.
  Fixture and production catalogs both select unified_exec/freeform apply_patch;
  the probe intentionally uses a synthetic model and isolated provider.
- Parent configuration delta: two false feature overrides in qwen-implement and
  two required-value assertions in its regression test. No AGENTS, fixed policy,
  shim, queue, catalog, model, provider, retries or sandbox change. No scientific
  application implementation by SOL. Separate exact-delta/identity review SHIP.
- Parent baseline launcher tests:16 PASS in12.52s. After the delta, all527 tests
  across launcher, unit01 motion contract and public_postproc PASS in14.58s;
  Ruff, shell syntax and git diff --check PASS. These are offline/local tests,
  not unit02a implementation tests or an accuracy result.
- Cancelled recovery1 inference slot release was confirmed at09:42:37 UTC.
  Recheck current services/worktree before a separately budgeted actual launch.
- Parent allocated a conditional single1200s local-only attempt (queue included,
  extensions0) in the new handoff, now SHA-256
  `9b558c5469543b54d21aba143e45cb72df65756419b3d7d87bb6ed95740ff2f7`.
  Only execution-status/budget paragraphs changed after the reviewed draft; the
  scientific body, inline source and full parent test commands are unchanged.
- Exact-delta review evidence discrepancy: the first reviewer described the correct
  four-line delta but reported file/diff hashes different from parent raw output;
  its attempted correction did not provide usable exact values. Parent stopped
  that review turn and requested a separate read-only exact-delta/identity audit.
  Do not count that inconsistent identity report as acceptance or launch evidence.
  Parent actual launcher SHA is
  `23b4c861c5f4f7908047e3d0e76e0cc92ef616bb680b8190f060e2e2ad0a2b1a`,
  test SHA `c43826f4d8f002227a76868edad0bf1ca1c3d6f7dc50179c0a50bff2b166ccac`,
  exact two-file git diff SHA
  `87d404bc8cda6e47ded474e4a7a0b04063cebdf85985d27636664d56ba053b13`.
  No source divergence was observed in parent checks. Nothing was committed,
  synchronized to the worktree or dispatched while that audit was pending.
- Separate artifact reviewer confirmed all three actual hashes from raw tool
  output and the exact four-line delta: SHIP. Parent accepts that independently
  verified identity report, not the earlier inconsistent report. Configuration
  unit committed as canonical28cd5086a163a987417e50827dab70efec6f9ec1 and
  synchronized only to approved worktree345dc386aa92c2f5ffd317b6192fbb7e190e0944.
  No unrelated WIP/AGENTS was staged and nothing was pushed. Worktree files match
  the accepted launcher/test hashes. Parent reran the same527 tests there:
  PASS16.45s, plus Ruff/shell syntax. Model/task/scientific scope fixed.
- At10:04:42.892400 UTC parent dispatched the single patch1 local attempt,
  session80539, thread01a0762d-6c53-7831-8233-5a998699a3b5. Launcher PID91311,
  supervisor PID91255; deadline10:24:42.892400 UTC including queue time.
  Admission0.00s, route=flash/model=qwen38-flash-next, automatic_retry0.
  Initial health active1/waiting0/blockedfalse/started37 confirms a live request.
  Log: `outputs/local/e26_implementation/unit02a_patch1_WORKER.jsonl`.
  Keep the same session handle; no restart on observation timeout. Preserve all
  partial files/log on failure. Parent review/full tests/independent acceptance
  still precede integration; no accuracy evaluation or submission has occurred.
- Live diagnostic snapshot at10:11:22 UTC:9 log lines/1287B, no target files and
  clean worktree; session80539 remains live. At10:07:07 router rejected a patch
  as outside the project; at10:07:33 another patch failed empty Update hunk
  validation. These are distinct nonterminal tool errors, not provider-failure
  proof. The rejected complete patch inputs are not in this log; do not attribute
  the first error to a particular path or Unicode normalization without evidence.
  The model then explicitly requested actual PostprocConfig/build_config context.
- Independent read-only diagnosis identifies missing inline context: current task
  supplies only438–470, not the full dataclass307–437 or full factory438–613.
  If a later handoff is needed, supplying those exact hash-pinned existing source
  ranges as read-only references can address that stated context need without
  changing the scientific specification or reimplementing the factory. This does
  not prove either patch error's cause or guarantee successful authorship. Do not
  mutate the live task, start a second worker or treat this diagnostic as a retry
  allocation; the existing deadline and same-handle supervision remain binding.
