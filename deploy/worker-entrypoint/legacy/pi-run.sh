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

# Select the Snapshot model explicitly. pi 0.84.2 defaults to its built-in
# ``anthropic`` provider, which sends the relay key to api.anthropic.com and
# fails with ``401 invalid x-api-key``; the Snapshot model is registered under
# the ``codify`` provider in $HOME/.pi/agent/models.json, so pin both here so
# the key goes to the relay endpoint carved by the adapter.
PI_MODEL_RPC="${PI_MODEL:-${ANTHROPIC_MODEL:-${OPENAI_MODEL:-}}}"

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

# Drive the initial RPC handshake as a SEQUENTIAL state machine, not a burst:
# pi 0.84.2 processes requests asynchronously, so pushing new_session/get_state/
# prompt back-to-back let prompt run before new_session completed — the model
# call never initiated (0 sockets, permanent hang, reproduced on ox-alpha-free).
# The runner therefore reads the pi stdout stream line-by-line and issues the
# next request only after the previous step's ACK/response is observed:
#   new_session (id:1) -> ACK success -> get_state (id:2) -> response -> prompt (id:3)
# Requests use Pi 0.84.2 framing -- ``type=<command>`` with the prompt body in a
# top-level ``message`` field (recovered handleCommand), NOT the enveloping
# ``{"type":"request","command":...,"payload":...}`` wrapper that pi rejects with
# ``Unknown command: request``. A continued run (CODIFY_RESUME_SESSION) sends
# ``new_session`` + ``parentSessionId`` (real 0.84.2 accepts it), while a first
# run sends bare ``new_session``; real 0.84.2 rejects the old ``type:resume``
# frame with ``Unknown command: resume``. Requests are written to the pipe held
# open by req_writer. Every streamed line is buffered so the translator still
# sees the full ordered stream (handshake ACKs + the turn) at raw_line parity.
prompt_json="$(jq -Rs . < "${PROMPT_FILE}")"
first_frame='{"id":1,"type":"new_session"}'
if [ -n "${CODIFY_RESUME_SESSION}" ]; then
    first_frame="$(jq -nc --arg parent "${CODIFY_RESUME_SESSION}" \
        '{id:1, type:"new_session", parentSessionId:$parent}')"
fi
printf '%s\n' "${first_frame}" > "${REQ_FIFO}"
HANDSHAKE_BUF="${RUN_DIR}/pi-handshake.jsonl"
: > "${HANDSHAKE_BUF}"
ack_session=0
ack_state=0
while IFS= read -r line; do
    printf '%s\n' "${line}" >> "${HANDSHAKE_BUF}"
    # Terminal settle: pi 0.84.2 emits agent_settled when the turn completes.
    # Close the request FIFO write end (req_writer) so pi sees EOF on stdin and
    # exits; only then does STREAM_FIFO reach EOF and the translator persist the
    # V2 result — without this the runner hangs until TASK_TIMEOUT. Must run
    # before the ack_state continue so it also applies to the turn stream.
    if printf '%s' "${line}" | jq -e '.type == "agent_settled"' >/dev/null 2>&1; then
        kill "${req_writer}" 2>/dev/null || true
        kill "${BRIDGE_RELAY_PID:-0}" 2>/dev/null || true
    fi
    if [ "${ack_state}" -eq 1 ]; then
        continue  # handshake complete; the rest is the turn stream (drain as-is)
    fi
    cmd="$(printf '%s' "${line}" | jq -r '.command // empty' 2>/dev/null || true)"
    success="$(printf '%s' "${line}" | jq -r '.success // empty' 2>/dev/null || true)"
    case "${cmd}" in
        new_session)
            if [ "${ack_session}" -eq 0 ] && [ "${success}" = "true" ]; then
                ack_session=1
                printf '{"id":2,"type":"get_state"}\n' > "${REQ_FIFO}"
            fi
            ;;
        get_state)
            if [ "${ack_state}" -eq 0 ]; then
            ack_state=1
            printf '{"id":3,"type":"prompt","message":%s}\n' \
                "${prompt_json}" > "${REQ_FIFO}"
            # Bridge relay: tail the control-plane request journal and inject
            # native steer/follow_up frames into Pi's RPC stdin. Each outcome
            # is recorded so the in-image control client can report the real
            # native ACK to the command pump (plan §6.2).
            REQUESTS_JOURNAL="${CODIFY_RUNTIME_DIR}/pi-control-requests.jsonl"
            RESPONSES_JOURNAL="${CODIFY_RUNTIME_DIR}/pi-control-responses.jsonl"
            : > "${REQUESTS_JOURNAL}"
            (
                LAST_POS=0
                LAST_INODE=""
                while :; do
                    if [ -f "${REQUESTS_JOURNAL}" ]; then
                        INODE="$(stat -c %i "${REQUESTS_JOURNAL}" 2>/dev/null || echo "")"
                        if [ "${INODE}" != "${LAST_INODE}" ]; then
                            LAST_INODE="${INODE}"
                            LAST_POS=0
                        fi
                        SIZE="$(stat -c %s "${REQUESTS_JOURNAL}" 2>/dev/null || echo 0)"
                        if [ "${SIZE}" -gt "${LAST_POS}" ]; then
                            tail -c +"$((LAST_POS + 1))" "${REQUESTS_JOURNAL}" \
                                | while IFS= read -r req_line; do
                                    [ -n "${req_line}" ] || continue
                                    rtype="$(printf '%s' "${req_line}" | jq -r '.type // empty' 2>/dev/null)"
                                    cid="$(printf '%s' "${req_line}" | jq -r '.command_id // empty' 2>/dev/null)"
                                    case "${rtype}" in
                                        steer|follow_up)
                                            text="$(printf '%s' "${req_line}" | jq -r '.payload.text // ""')"
                                            REQ_ID="cmd-${cid}"
                                            printf '{"id":"%s","type":"%s","message":%s}\n' \
                                                "${REQ_ID}" "${rtype}" \
                                                "$(printf '%s' "${text}" | jq -Rs .)" > "${REQ_FIFO}"
                                            printf '%s\n' "{\"command_id\":\"${cid}\",\"status\":\"delivered\",\"req_id\":\"${REQ_ID}\"}" \
                                                >> "${RESPONSES_JOURNAL}"
                                            ;;
                                    esac
                                done
                            LAST_POS="${SIZE}"
                        fi
                    fi
                    sleep 1
                done
            ) &
            BRIDGE_RELAY_PID=$!
        fi
        ;;
    esac
done < "${STREAM_FIFO}"

# Root context hands the buffered ordered stream to the translator as ONE
# process, preserving raw-line ordering for the canonical events.
python3 "${CODIFY_PI_EVENT_TRANSLATOR}" --raw-file "${CODIFY_PI_RAW_EVENT_JSONL}" < "${HANDSHAKE_BUF}"
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
