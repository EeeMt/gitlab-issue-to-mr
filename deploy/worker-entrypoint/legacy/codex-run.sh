#!/bin/bash
set -u

# Minimal Codex runner: run `codex exec --json`, stream each line through the
# Codex event translator, and persist a canonical harness result.

CODIFY_CODEX_BIN="${CODIFY_CODEX_BIN:-/usr/local/bin/codex}"
CODIFY_CODEX_RAW_EVENT_JSONL="${CODIFY_CODEX_RAW_EVENT_JSONL:-${CODIFY_RUNTIME_DIR}/harness-events/codex.jsonl}"
CODIFY_CODEX_EVENT_TRANSLATOR="${CODIFY_CODEX_EVENT_TRANSLATOR:-${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/adapters/codex_events.py}"
PROMPT_FILE="${PROMPT_FILE:-${CODIFY_HARNESS_PROMPT_FILE:-}}"

mkdir -p "$(dirname "${CODIFY_CODEX_RAW_EVENT_JSONL}")"

if [ -z "${PROMPT_FILE}" ] || [ ! -s "${PROMPT_FILE}" ]; then
    echo "Codex prompt file is missing: ${PROMPT_FILE}" >&2
    exit 1
fi

export CODEX_HOME="${CODEX_HOME:-${CODIFY_RUNTIME_DIR}/codex-home}"
mkdir -p "${CODEX_HOME}"

set +e
if [ -n "${CODIFY_RESUME_SESSION:-}" ]; then
    "${CODIFY_CODEX_BIN}" exec resume --json --skip-git-repo-check \
        "${CODIFY_RESUME_SESSION}" "$(cat "${PROMPT_FILE}")" 2>&1 \
        | while IFS= read -r line; do
            printf '%s\n' "${line}" \
                | python3 "${CODIFY_CODEX_EVENT_TRANSLATOR}" --raw-file "${CODIFY_CODEX_RAW_EVENT_JSONL}"
        done
else
    "${CODIFY_CODEX_BIN}" exec --json --skip-git-repo-check "$(cat "${PROMPT_FILE}")" 2>&1 \
        | while IFS= read -r line; do
            printf '%s\n' "${line}" \
                | python3 "${CODIFY_CODEX_EVENT_TRANSLATOR}" --raw-file "${CODIFY_CODEX_RAW_EVENT_JSONL}"
        done
fi
exit_code=${PIPESTATUS[0]}
set -e

# The canonical result is authoritative: when a turn completed, the translator
# already persisted a successful harness result. codex may exit non-zero due to
# benign per-item errors (e.g. fallback model metadata) even after a completed
# turn; returning 0 lets the shared delivery commit the agent's changes.
if grep -q '"turn.completed"' "${CODIFY_CODEX_RAW_EVENT_JSONL}" 2>/dev/null; then
    exit 0
fi

exit "${exit_code}"
