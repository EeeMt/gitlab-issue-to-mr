#!/bin/bash
set -u

# ``pi_owner.py`` is the sole owner of Pi stdin/stdout. This wrapper constructs
# the frozen command and feeds the owner's raw stream to the canonical adapter.
CODIFY_PI_BIN="${CODIFY_PI_BIN:?CODIFY_PI_BIN is required (resolved by the pi adapter from the Kit inventory or an authorized host_mount)}"
CODIFY_PI_RAW_EVENT_JSONL="${CODIFY_PI_RAW_EVENT_JSONL:-${CODIFY_RUNTIME_DIR}/harness-events/pi.jsonl}"
CODIFY_PI_EVENT_TRANSLATOR="${CODIFY_PI_EVENT_TRANSLATOR:-${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/adapters/pi_events.py}"
CODIFY_PI_BRIDGE="${CODIFY_PI_BRIDGE:-${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/adapters/pi_bridge.py}"
PROMPT_FILE="${PROMPT_FILE:-${CODIFY_HARNESS_PROMPT_FILE:-}}"
PI_SESSION_DIR="${PI_SESSION_DIR:-${CODIFY_RUNTIME_DIR}/pi-session}"
CODIFY_RESUME_SESSION="${CODIFY_RESUME_SESSION:-}"

mkdir -p "$(dirname "${CODIFY_PI_RAW_EVENT_JSONL}")" "${PI_SESSION_DIR}"
if [ -z "${PROMPT_FILE}" ] || [ ! -s "${PROMPT_FILE}" ]; then
    echo "Pi prompt file is missing: ${PROMPT_FILE}" >&2
    exit 1
fi

# Pi is an Anthropic-messages-only Runtime Bundle.  The adapter validates the
# frozen protocol before this wrapper starts; do not let a stale/custom OpenAI
# variable silently select a model on this command line.
PI_MODEL_RPC="${PI_MODEL:-${ANTHROPIC_MODEL:-}}"
PI_COMMAND=("${CODIFY_PI_BIN}" --mode rpc --provider codify)
if [ -n "${PI_MODEL_RPC}" ]; then
    PI_COMMAND+=(--model "${PI_MODEL_RPC}")
fi
if [ -n "${CODIFY_PI_RUN_AS:-}" ]; then
    if [[ "${CODIFY_PI_RUN_AS}" != /* || ! -x "${CODIFY_PI_RUN_AS}" ]]; then
        echo "CODIFY_PI_RUN_AS must be an executable absolute path: ${CODIFY_PI_RUN_AS}" >&2
        exit 1
    fi
    PI_COMMAND=(env HOME=/home/codify USER=codify LOGNAME=codify \
        "${CODIFY_PI_RUN_AS}" -- "${PI_COMMAND[@]}")
else
    PI_COMMAND=(env USER="${USER:-root}" "${PI_COMMAND[@]}")
fi

# Unix-domain socket paths are capped (macOS: 104 bytes). Keep the default
# outside the task runtime directory, whose generated path can exceed that.
# This path must be independently reconstructable by Docker exec's fresh
# environment; do not include the launcher PID. Task containers have one Pi
# owner, so the task id is sufficient and remains below AF_UNIX path limits.
if ! [[ "${TASK_ID:-}" =~ ^[1-9][0-9]*$ ]]; then
    echo "TASK_ID must be a positive integer for Pi control" >&2
    exit 1
fi
PI_OWNER_SOCKET="/tmp/codify-pi-${TASK_ID}.sock"
PI_OWNER_COMMAND="$(printf '%q ' "${PI_COMMAND[@]}")"
run_pi_owner() {
    python3 "${CODIFY_PI_BRIDGE%/*}/pi_owner.py" \
        --socket "${PI_OWNER_SOCKET}" \
        --task-id "${TASK_ID}" \
        --attempt-id "${CODIFY_ATTEMPT_ID:?CODIFY_ATTEMPT_ID is required for Pi control}" \
        --runtime-dir "${CODIFY_RUNTIME_DIR}" \
        --command "${PI_OWNER_COMMAND}" \
        --translator "${CODIFY_PI_EVENT_TRANSLATOR}" \
        --prompt-file "${PROMPT_FILE}" ${CODIFY_PI_OWNER_NO_SOCKET:+--no-socket} "$@"
}
if [ -n "${CODIFY_RESUME_SESSION}" ]; then
    run_pi_owner --parent-session "${CODIFY_RESUME_SESSION}"
else
    run_pi_owner
fi
owner_exit=$?
if [ "${owner_exit}" -ne 0 ]; then
    exit "${owner_exit}"
fi

result_file="${CODIFY_HARNESS_RESULT_FILE:-${CODIFY_RUNTIME_DIR}/harness-result.json}"
if [ -s "${result_file}" ]; then
    cat "${result_file}"
fi
exit "${owner_exit}"
