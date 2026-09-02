#!/bin/zsh

set -eu

readonly BIOHUB_PROJECT_DIR="/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking"
readonly BIOHUB_CODEX_BIN="/Users/taichi/.local/bin/codex"
readonly BIOHUB_MAINTENANCE_PROMPT="${BIOHUB_PROJECT_DIR}/analysis/periodic_maintenance_prompt.md"

if [[ ! -d "${BIOHUB_PROJECT_DIR}/.git" ]]; then
  print -u2 -- "maintenance HOLD: project checkout is unavailable"
  exit 3
fi

if [[ ! -x "${BIOHUB_CODEX_BIN}" ]]; then
  print -u2 -- "maintenance HOLD: Codex executable is unavailable"
  exit 3
fi

if [[ ! -f "${BIOHUB_MAINTENANCE_PROMPT}" || -L "${BIOHUB_MAINTENANCE_PROMPT}" ]]; then
  print -u2 -- "maintenance HOLD: prompt is unavailable or unsafe"
  exit 3
fi

print -- "maintenance started: $(/bin/date -u +%Y-%m-%dT%H:%M:%SZ)"

"${BIOHUB_CODEX_BIN}" exec \
  --ephemeral \
  --cd "${BIOHUB_PROJECT_DIR}" \
  --model gpt-5.6-sol \
  --sandbox workspace-write \
  --approve-for-me \
  --color never \
  --config 'model_reasoning_effort="medium"' \
  - < "${BIOHUB_MAINTENANCE_PROMPT}"

print -- "maintenance finished: $(/bin/date -u +%Y-%m-%dT%H:%M:%SZ)"
