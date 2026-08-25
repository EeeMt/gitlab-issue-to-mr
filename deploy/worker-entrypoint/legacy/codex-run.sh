#!/bin/bash
set -u

# Minimal Codex runner: run `codex exec --json`, stream each line through the
# Codex event translator, and persist a canonical harness result.
#
# Privilege model mirrors ci-claude.sh: the codex CLI subprocess runs as the
# worker runtime user (CODIFY_CODEX_RUN_AS, i.e. codify), while the translator
# and the audit stream stay in the root orchestration context. The FIFO write
# end is opened by this root parent via the `> fifo` redirection, so the
# dropped-privilege codex process merely inherits the fd and never needs
# write permission on the FIFO itself.

CODIFY_CODEX_BIN="${CODIFY_CODEX_BIN:?CODIFY_CODEX_BIN is required (resolved by the codex adapter from the Kit inventory or an authorized host_mount)}"
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

# Build the codex command. When a privilege-drop launcher is provided, only the
# codex CLI subprocess runs through it; this runner retains the audit stream.
CODEX_COMMAND=("${CODIFY_CODEX_BIN}")
if [ -n "${CODIFY_CODEX_RUN_AS:-}" ]; then
    if [[ "${CODIFY_CODEX_RUN_AS}" != /* || ! -x "${CODIFY_CODEX_RUN_AS}" ]]; then
        echo "CODIFY_CODEX_RUN_AS must be an executable absolute path: ${CODIFY_CODEX_RUN_AS}" >&2
        exit 1
    fi
    CODEX_COMMAND=(env HOME=/home/codify USER=codify LOGNAME=codify \
        "${CODIFY_CODEX_RUN_AS}" -- "${CODIFY_CODEX_BIN}")
fi

STREAM_DIR=$(mktemp -d)
STREAM_FIFO="${STREAM_DIR}/codex-stream.fifo"
mkfifo "${STREAM_FIFO}"
trap 'rm -rf "${STREAM_DIR}"' EXIT

set +e
# codex shares this runner's process group so the wrapping `timeout` (codex.sh)
# signals the whole CLI tree on TASK_TIMEOUT; the FIFO write fd is opened by
# this root shell and inherited by the dropped-privilege codex subprocess.
# Pin stdin to /dev/null so the non-interactive runner never reads a stray
# terminal/pipe stream; the prompt is always passed as an argument.
if [ -n "${CODIFY_RESUME_SESSION:-}" ]; then
    "${CODEX_COMMAND[@]}" exec resume --json --skip-git-repo-check \
        "${CODIFY_RESUME_SESSION}" "$(cat "${PROMPT_FILE}")" < /dev/null > "${STREAM_FIFO}" 2>&1 &
else
    "${CODEX_COMMAND[@]}" exec --json --skip-git-repo-check \
        "$(cat "${PROMPT_FILE}")" < /dev/null > "${STREAM_FIFO}" 2>&1 &
fi
codex_pid=$!

# Root context drains the FIFO through the translator as ONE streaming process
# so canonical events and the raw audit file stay root-owned (the model cannot
# rewrite them) and all cross-record state lives in translator memory. The
# translator emits the single harness terminal at stream end.
python3 "${CODIFY_CODEX_EVENT_TRANSLATOR}" --raw-file "${CODIFY_CODEX_RAW_EVENT_JSONL}" < "${STREAM_FIFO}"
wait "${codex_pid}"
exit_code=$?
set -e

# Stream the authoritative result on stdout (the same contract as the Claude
# runner) so main.sh can read `.result` for the delivery summary and commit
# prompts, then decide the exit code from the result status.
CODIFY_HARNESS_RESULT_FILE="${CODIFY_HARNESS_RESULT_FILE:-${CODIFY_RUNTIME_DIR}/harness-result.json}"
result_status="$(jq -r '.status // empty' "${CODIFY_HARNESS_RESULT_FILE}" 2>/dev/null || true)"
if [ -n "${result_status}" ] && [ -s "${CODIFY_HARNESS_RESULT_FILE}" ]; then
    cat "${CODIFY_HARNESS_RESULT_FILE}"
fi
case "${result_status}" in
    completed)
        # codex may still exit non-zero on benign per-item errors after a
        # completed turn; a completed turn is authoritative for delivery.
        exit 0
        ;;
    failed)
        # A failed turn means the agent did not finish its work: the attempt fails.
        exit 1
        ;;
esac

exit "${exit_code}"
