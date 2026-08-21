#!/bin/bash
set -u

# Minimal Pi runner: drive ``pi --mode rpc`` (a persistent stdio process), drain
# its JSONL stream through the Pi event translator, and persist a V2 canonical
# result.
#
# Pi RPC is interactive and stateful, unlike the one-shot codex exec:
#   * the CLI reads one JSON request per line on stdin and writes responses /
#     stream events on stdout;
#   * the runner issues get_state (verify) then prompt (initial task prompt),
#     and relays bridge command requests (steer/follow_up/abort) into the stream;
#   * native ACKs carry no Codify command_id (probe fact 2), so the runner folds
#     the bridge's request id -> command mapping onto the ACK line before it
#     reaches the translator, where control.command.delivered is emitted.
#
# Privilege model mirrors codex-run.sh: the pi CLI subprocess runs as the worker
# runtime user while the translator and audit stream stay in the root
# orchestration context.

CODIFY_PI_BIN="${CODIFY_PI_BIN:-/usr/local/bin/pi}"
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

# The RPC stdin is served from a request pipe so the bridge can inject
# steer/follow_up during the run; stdout is drained through the translator FIFO.
RUN_DIR=$(mktemp -d)
REQ_FIFO="${RUN_DIR}/pi-request.fifo"
STREAM_FIFO="${RUN_DIR}/pi-stream.fifo"
mkfifo "${REQ_FIFO}" "${STREAM_FIFO}"
trap 'rm -rf "${RUN_DIR}"' EXIT

PI_COMMAND=("${CODIFY_PI_BIN}" --mode rpc)
if [ -n "${CODIFY_PI_RUN_AS:-}" ]; then
    if [[ "${CODIFY_PI_RUN_AS}" != /* || ! -x "${CODIFY_PI_RUN_AS}" ]]; then
        echo "CODIFY_PI_RUN_AS must be an executable absolute path: ${CODIFY_PI_RUN_AS}" >&2
        exit 1
    fi
    PI_COMMAND=(env HOME=/home/codify USER=codify LOGNAME=codify \
        "${CODIFY_PI_RUN_AS}" -- "${PI_COMMAND[@]}")
else
    # Keep the pi subprocess unprivileged only when a launcher is provided;
    # default to the current (orchestration) user like the other adapters.
    PI_COMMAND=(env USER="${USER:-root}" "${PI_COMMAND[@]}")
fi

set +e
# Open the request FIFO write end in a background cat so the pi subprocess
# reading stdin never sees EOF prematurely; the runner pushes requests into it.
( exec 3>"${REQ_FIFO}" ; while :; do sleep 5; done ) &
req_writer=$!
"${PI_COMMAND[@]}" < "${REQ_FIFO}" > "${STREAM_FIFO}" 2>&1 &
pi_pid=$!

# Issue the initial RPC handshake: new_session (opt. continuing a parent
# session), get_state (verify version/capability gate is enforced by the
# adapter before this runner is reached) then prompt with the frozen task text.
# Requests use Pi 0.84.2 framing -- ``type=<command>`` with the prompt body in a
# top-level ``message`` field (recovered handleCommand), NOT the enveloping
# ``{"type":"request","command":...,"payload":...}`` wrapper that pi rejects with
# ``Unknown command: request``. A continued run (CODIFY_RESUME_SESSION) sends
# ``new_session`` + ``parentSessionId`` (real 0.84.2 accepts it), while a first
# run sends bare ``new_session``; real 0.84.2 rejects the old ``type:resume``
# frame with ``Unknown command: resume``. Requests are written to the pipe held
# open by req_writer.
prompt_json="$(jq -Rs . < "${PROMPT_FILE}")"
first_frame='{"id":1,"type":"new_session"}'
if [ -n "${CODIFY_RESUME_SESSION}" ]; then
    first_frame="$(jq -nc --arg parent "${CODIFY_RESUME_SESSION}" '{id:1, type:"new_session", parentSessionId:$parent}')"
fi
printf '%s\n' "${first_frame}" > "${REQ_FIFO}"
printf '{"id":2,"type":"get_state"}\n' > "${REQ_FIFO}"
printf '{"id":3,"type":"prompt","message":%s}\n' \
    "${prompt_json}" > "${REQ_FIFO}"

# Root context drains stdout through the translator as ONE streaming process.
python3 "${CODIFY_PI_EVENT_TRANSLATOR}" --raw-file "${CODIFY_PI_RAW_EVENT_JSONL}" < "${STREAM_FIFO}"
python3 "${CODIFY_PI_BRIDGE}" >/dev/null 2>&1 <<< '{}'  # (no-op warm-up retained for parity)
wait "${pi_pid}"
exit_code=$?
set -e

CODIFY_HARNESS_RESULT_FILE="${CODIFY_HARNESS_RESULT_FILE:-${CODIFY_RUNTIME_DIR}/harness-result.json}"
result_status="$(jq -r '.status // empty' "${CODIFY_HARNESS_RESULT_FILE}" 2>/dev/null || true)"
if [ -n "${result_status}" ] && [ -s "${CODIFY_HARNESS_RESULT_FILE}" ]; then
    cat "${CODIFY_HARNESS_RESULT_FILE}"
fi
case "${result_status}" in
    completed)
        exit 0
        ;;
    failed)
        exit 1
        ;;
esac
exit "${exit_code}"
