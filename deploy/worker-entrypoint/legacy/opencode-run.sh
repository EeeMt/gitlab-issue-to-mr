#!/bin/bash
set -u

# OpenCode runner: start a Task-scoped ``opencode serve``, wait for readiness,
# drive one attempt (session / prompt / SSE drain + canonical normalization)
# through the Python bridge, then terminate the Server with no-daemon
# convergence.
#
# Unlike the stdio Pi runner, OpenCode is a standalone HTTP Server: the adapter
# probes a free loopback port and passes it via $OPENCODE_PORT, sets a Task
# private OPENCODE_SERVER_PASSWORD, and this runner starts/readiness/terminates
# the Server. The command plane is ``disabled`` for first release, so there is
# nothing to drain for steering — the bridge's ``dispatch`` rejects.
#
# Privilege model mirrors pi-run.sh: the Server subprocess is left in the
# current (orchestration) context; the translator and audit stream stay in the
# root orchestration context.

CODIFY_OPENCODE_BIN="${CODIFY_OPENCODE_BIN:-/usr/local/bin/opencode}"
CODIFY_OPENCODE_RAW_EVENT_JSONL="${CODIFY_OPENCODE_RAW_EVENT_JSONL:-${CODIFY_RUNTIME_DIR}/harness-events/opencode.jsonl}"
CODIFY_OPENCODE_EVENT_TRANSLATOR="${CODIFY_OPENCODE_EVENT_TRANSLATOR:-${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/adapters/opencode_events.py}"
CODIFY_OPENCODE_BRIDGE="${CODIFY_OPENCODE_BRIDGE:-${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/adapters/opencode_bridge.py}"
PROMPT_FILE="${PROMPT_FILE:-${CODIFY_HARNESS_PROMPT_FILE:-}}"
OPENCODE_PORT="${OPENCODE_PORT:?OPENCODE_PORT is required}"
OPENCODE_SERVER_PASSWORD="${OPENCODE_SERVER_PASSWORD:-}"
# Frozen Snapshot credential referenced by opencode.json via {env:...}; passed
# only to the Server process, never logged / archived.
OPENCODE_SNAPSHOT_KEY="${OPENCODE_SNAPSHOT_KEY:-}"
OPENCODE_CONFIG_DIR="${OPENCODE_CONFIG_DIR:-${CODIFY_RUNTIME_DIR}/opencode}"

mkdir -p "$(dirname "${CODIFY_OPENCODE_RAW_EVENT_JSONL}")"

if [ -z "${PROMPT_FILE}" ] || [ ! -s "${PROMPT_FILE}" ]; then
    echo "OpenCode prompt file is missing: ${PROMPT_FILE}" >&2
    exit 1
fi

RUN_DIR=$(mktemp -d)
SERVER_PID_FILE="${RUN_DIR}/opencode-server.pid"
trap 'cleanup' EXIT

cleanup() {
    rm -rf "${RUN_DIR}"
}

opencode_server_pid() {
    cat "${SERVER_PID_FILE}" 2>/dev/null || true
}

stop_server() {
    local pid
    pid="$(opencode_server_pid)"
    [ -n "${pid}" ] || return 0
    # TERM the process group so any child (SDK/plugin process) converges too.
    if kill -0 "${pid}" 2>/dev/null; then
        kill -TERM "-${pid}" 2>/dev/null || kill -TERM "${pid}" 2>/dev/null || true
    fi
    # Poll for disappearance (no-daemon guarantee), then KILL after grace.
    local deadline=$(( $(date +%s) + 10 ))
    while [ "$(date +%s)" -lt "${deadline}" ] && kill -0 "${pid}" 2>/dev/null; do
        sleep 0.5
    done
    if kill -0 "${pid}" 2>/dev/null; then
        kill -KILL "-${pid}" 2>/dev/null || kill -KILL "${pid}" 2>/dev/null || true
    fi
}

stop_server_force() {
    local pid
    pid="$(opencode_server_pid)"
    [ -n "${pid}" ] || return 0
    kill -KILL "${pid}" 2>/dev/null || true
}

start_server() {
    # The Server interpolates opencode.json's {env:OPENCODE_SNAPSHOT_KEY} and is
    # protected by OPENCODE_SERVER_PASSWORD; both are passed only into the Server
    # process env, and OPENCODE_CONFIG_DIR points at the Task-scoped config dir.
    OPENCODE_SERVER_PASSWORD="${OPENCODE_SERVER_PASSWORD}" \
    OPENCODE_SNAPSHOT_KEY="${OPENCODE_SNAPSHOT_KEY}" \
    OPENCODE_CONFIG_DIR="${OPENCODE_CONFIG_DIR}" \
    "${CODIFY_OPENCODE_BIN}" serve \
        --hostname 127.0.0.1 \
        --port "${OPENCODE_PORT}" \
        > "${RUN_DIR}/server.log" 2>&1 &
    echo $! > "${SERVER_PID_FILE}"
}

# 1. Start the Task-scoped Server.
start_server
SERVER_PID="$(opencode_server_pid)"
if [ -z "${SERVER_PID}" ] || ! kill -0 "${SERVER_PID}" 2>/dev/null; then
    echo "OpenCode Server failed to start" >&2
    cat "${RUN_DIR}/server.log" >&2 || true
    exit 1
fi

# 2. Readiness: poll /session until the Server responds (Basic auth 401/200) or
#    the readiness deadline passes. connection_refused is retried (Server not
#    yet listening, NOT port-in-use); any 200/401 means it is ready.
READY=0
DEADLINE=$(( $(date +%s) + ${OPENCODE_READINESS_TIMEOUT:-30} ))
while [ "$(date +%s)" -lt "${DEADLINE}" ]; do
    CODE="$(curl -s -o /dev/null -w '%{http_code}' \
        -u "opencode:${OPENCODE_SERVER_PASSWORD}" \
        --max-time 2 "http://127.0.0.1:${OPENCODE_PORT}/session" 2>/dev/null || true)"
    case "${CODE}" in
        200|401)
            READY=1
            break
            ;;
    esac
    sleep 0.5
done
if [ "${READY}" -ne 1 ]; then
    echo "OpenCode Server did not become ready within readiness timeout" >&2
    cat "${RUN_DIR}/server.log" >&2 || true
    stop_server_force
    exit 1
fi

# 3. Drive one attempt through the bridge (session -> SSE -> prompt -> drain).
set +e
OPENCODE_SERVER_PASSWORD="${OPENCODE_SERVER_PASSWORD}" \
OPENCODE_PORT="${OPENCODE_PORT}" \
OPENCODE_PROVIDER="${OPENCODE_PROVIDER:-}" \
OPENCODE_MODEL="${OPENCODE_MODEL:-${ANTHROPIC_MODEL:-${OPENAI_MODEL:-}}}" \
CODIFY_OPENCODE_EVENT_TRANSLATOR="${CODIFY_OPENCODE_EVENT_TRANSLATOR}" \
CODIFY_OPENCODE_RAW_EVENT_JSONL="${CODIFY_OPENCODE_RAW_EVENT_JSONL}" \
PROMPT_FILE="${PROMPT_FILE}" \
python3 "${CODIFY_OPENCODE_BRIDGE}" run
BRIDGE_RC=$?
set -e

# 4. Terminate the Server with no-daemon convergence (TERM to process group,
#    poll for disappearance, KILL after grace).
stop_server
exit "${BRIDGE_RC}"
