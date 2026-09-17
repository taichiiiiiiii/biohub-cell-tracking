# Biohub Qwen Cloud Max evaluator

Evaluation only: qwen3.8-max through the existing QwenCloud Individual Token Plan
qwen_token_plan route, explicitly selected with --cloud-only --cloud-model qwen3.8-max.
This file retains its historical filename but does not authorize implementation.
The Flash implementation launcher remains Flash-only; do not bypass its guards.

## Parent entry and input contract

From the canonical feature-branch checkout run:
`.codex/bin/qwen-evaluate --parent-reviewed < evaluation.json`
No model/provider/effort override is accepted. The entry invokes the shared queue
once, which verifies the subscription provider/catalog and owns cloud/workspace
locks. Shared queue/auth configuration is unchanged. No automatic retry.

Input is one UTF-8 JSON object, at most 32768 bytes, with exactly these fields:
`reason`, `acceptance`, `changed_files`, `diff`, `test_results`, `context`.
`reason` is submission, private-score, cv-leakage-evaluation, reproducibility,
multi-module or flash-failed-twice; `changed_files` lists 1–12 unique safe relative paths;
`acceptance`, `diff`, `test_results` are nonempty strings; `context` is an optional-content
string (the key is required). Limits in bytes: acceptance/test_results/context 4096 each,
diff 16384. State missing test evidence honestly; do not fabricate a passing result.
Unknown keys, duplicate JSON keys, oversized content, sensitive filenames,
undeclared patch paths and recognized secret patterns are rejected before queue use.
No full-repo/history/log fields. Do not encode such data inside allowed fields.

The parent must inspect and minimize/redact the packet before using --parent-reviewed.
This flag is an explicit operator attestation, not caller-identity authentication.
No JSON confirmation booleans are accepted. --help exits 0 without calling the queue;
all other argument combinations are rejected before sending. Pattern
checks cannot prove absence of arbitrary/encoded secrets or disguised history.
The worker has no auto-loaded project docs, shell, agents, apps/plugins or web
search; read-only sandbox and the fixed policy prohibit edits and extra retrieval.
Provider authentication is supplied only by the existing queue, never by the worker.
Offline tests do not establish live provider availability or billing entitlement.

Parent may request one bounded evaluation only for a submission candidate, an
important private-score-sensitive proposal, CV/data-leakage/tracking-evaluation/
reproducibility changes, multi-module changes, or a change that failed Flash
acceptance twice. There is no numeric, percentage, Goal-wide or per-revision
evaluation cap. Parent records why a fresh read-only evaluation materially reduces
adoption risk or resolves a concrete uncertainty, the new evidence or changed risk,
and the final decision. A materially changed candidate is eligible again. An unchanged
candidate may be re-evaluated only when acceptance criteria, evidence or unresolved
risk materially changes. Never repeat an identical packet without a stated new reason,
pad review activity or replace the parent decision.

Receive only acceptance criteria, diff, changed-file list, relevant test/experiment
results and minimal surrounding code. No full repository, long conversation or
large logs. Return a short adoption recommendation with major defects, leakage/
evaluation risks, missing verification and evidence locations. Distinguish unknowns.
Do not reimplement, patch, produce replacement code or run additional experiments.
Final adoption, further experiments and submission decisions belong to parent Codex.

Direct user-requested, parent-supervised use only, never goals/heartbeats.
No tools, filesystem access, network, agents, credential/Keychain/token access,
authentication changes, Kaggle operations, training/inference, commit/push/PR,
publication, branches, deletion or edits to official/ or frozen inputs.
No PAYG, model/provider fallback, purchases/resets or request/stream retries.
Stop on quota, authentication, provider, routing or busy-slot errors; never steal locks.
Keep adapter effort none without claims about internal reasoning.
Flash's two acceptance failures do not authorize retrying provider/auth failures.
