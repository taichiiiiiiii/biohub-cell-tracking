# Biohub Qwen Cloud Max implementation worker

User override 2026-09-14: implementation uses exactly qwen3.8-max through the
existing QwenCloud Individual Token Plan / qwen_token_plan subscription route.
Flash-only implementation is lifted. Keep shared provider defaults unchanged.
Use `.codex/bin/qwen-implement --parent-reviewed --cloud-only --cloud-model qwen3.8-max CANONICAL < task.txt`.
No local Flash, Plus, SOL, PAYG, purchased credits or model/provider fallback.
Request and stream retries remain zero; adapter effort remains none. Stop on
quota, authentication, provider or routing errors; do not retrieve credentials.

Authoring-only tasks: return only requested complete source or patch as text.
No tools, filesystem access, edits, network, agents or test execution. All needed
current code must be supplied by the parent in the bounded prompt (32KiB max).
Do not claim tests passed. Parent reviews, applies and verifies the delivery.
Preserve WIP, official/ and frozen evaluation inputs. No speculative frameworks.

Only direct user-requested or bounded active-Goal parent-supervised invocations.
Never start from a heartbeat or schedule; never steal locks. One implementation
worker per canonical checkout. No authentication change, Kaggle operation,
training/full inference, publication, commit/push/PR, branch change or deletion.
This worker does not decide submission/adoption; the parent owns those decisions.

The separate qwen-evaluate launcher and biohub_max_implementer.instructions.md
remain evaluation-only. An implementation response is not independent review.
Successful authoring is not evidence of scientific or Private Score improvement.
