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
# The Server is deliberately placed in its own session/process group. OpenCode
# may fork SDK/plugin helpers; cleanup must converge that entire group without
# ever signalling the runner's own process group.

CODIFY_OPENCODE_BIN="${CODIFY_OPENCODE_BIN:?CODIFY_OPENCODE_BIN is required (resolved by the opencode adapter from the Kit inventory or an authorized host_mount)}"
CODIFY_OPENCODE_RAW_EVENT_JSONL="${CODIFY_OPENCODE_RAW_EVENT_JSONL:-${CODIFY_RUNTIME_DIR}/harness-events/opencode.jsonl}"
CODIFY_OPENCODE_EVENT_TRANSLATOR="${CODIFY_OPENCODE_EVENT_TRANSLATOR:-${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/adapters/opencode_events.py}"
CODIFY_OPENCODE_BRIDGE="${CODIFY_OPENCODE_BRIDGE:-${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/adapters/opencode_bridge.py}"
PROMPT_FILE="${PROMPT_FILE:-${CODIFY_HARNESS_PROMPT_FILE:-}}"
OPENCODE_PORT="${OPENCODE_PORT:?OPENCODE_PORT is required}"
OPENCODE_SERVER_PASSWORD="${OPENCODE_SERVER_PASSWORD:-}"
CODIFY_RESUME_SESSION="${CODIFY_RESUME_SESSION:-${RESUME_SESSION:-}}"
# Frozen Snapshot credential referenced by opencode.json via {env:...}; passed
# only to the Server process, never logged / archived.
OPENCODE_SNAPSHOT_KEY="${OPENCODE_SNAPSHOT_KEY:-}"
OPENCODE_CONFIG_DIR="${CODIFY_RUNTIME_DIR}/opencode"
# The adapter sets these roots before invoking the runner. Keep defensive
# defaults here too because this script is also directly exercised by recovery
# and shell-level tests; no inherited user/project config may enter a Task.
OPENCODE_HOME="${OPENCODE_CONFIG_DIR}/home"
HOME="${OPENCODE_HOME}"
XDG_CONFIG_HOME="${OPENCODE_CONFIG_DIR}/xdg-config"
CODIFY_OPENCODE_DATA_HOME="${CODIFY_OPENCODE_DATA_HOME:-${OPENCODE_CONFIG_DIR}/xdg-data}"
XDG_DATA_HOME="${CODIFY_OPENCODE_DATA_HOME}"
XDG_CACHE_HOME="${OPENCODE_CONFIG_DIR}/xdg-cache"
XDG_STATE_HOME="${OPENCODE_CONFIG_DIR}/xdg-state"
OPENCODE_DISABLE_PROJECT_CONFIG="true"
OPENCODE_DISABLE_EXTERNAL_SKILLS="1"
OPENCODE_DISABLE_CLAUDE_CODE_SKILLS="1"
unset OPENCODE_CONFIG OPENCODE_CONFIG_CONTENT
export HOME XDG_CONFIG_HOME XDG_DATA_HOME XDG_CACHE_HOME XDG_STATE_HOME \
    CODIFY_OPENCODE_DATA_HOME CODIFY_RESUME_SESSION \
    OPENCODE_DISABLE_PROJECT_CONFIG OPENCODE_DISABLE_EXTERNAL_SKILLS \
    OPENCODE_DISABLE_CLAUDE_CODE_SKILLS

mkdir -p "$(dirname "${CODIFY_OPENCODE_RAW_EVENT_JSONL}")"

if [ -z "${PROMPT_FILE}" ] || [ ! -s "${PROMPT_FILE}" ]; then
    echo "OpenCode prompt file is missing: ${PROMPT_FILE}" >&2
    exit 1
fi

RUN_DIR=$(mktemp -d)
SERVER_PID_FILE="${RUN_DIR}/opencode-server.pid"
trap 'cleanup' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

cleanup() {
    stop_server || true
    rm -rf "${RUN_DIR}"
}

opencode_server_pid() {
    cat "${SERVER_PID_FILE}" 2>/dev/null || true
}

stop_server() {
    local pid
    pid="$(opencode_server_pid)"
    [ -n "${pid}" ] || return 0
    # ``start_server`` verifies pid == PGID before publishing this file. Never
    # fall back to the runner's group: an unexpected PID/PGID is unsafe.
    local pgid
    pgid="$(ps -o pgid= -p "${pid}" 2>/dev/null | tr -d '[:space:]')"
    if [ -n "${pgid}" ] && [ "${pgid}" != "${pid}" ]; then
        echo "OpenCode Server PID/PGID mismatch; refusing group signal" >&2
        kill -TERM "${pid}" 2>/dev/null || true
        wait "${pid}" 2>/dev/null || true
        rm -f "${SERVER_PID_FILE}"
        return 1
    fi
    # TERM the independently verified process group so SDK/plugin children
    # converge with the server parent.
    if kill -0 "${pid}" 2>/dev/null; then
        kill -TERM "-${pid}" 2>/dev/null || true
    fi
    # Poll for disappearance (no-daemon guarantee), then KILL after grace.
    local deadline=$(( $(date +%s) + ${OPENCODE_SERVER_STOP_GRACE_SECONDS:-10} ))
    # The server leader may exit promptly while a plugin child ignores TERM;
    # test the group, not only its leader, before deciding convergence.
    while [ "$(date +%s)" -lt "${deadline}" ] && kill -0 "-${pid}" 2>/dev/null; do
        sleep 0.5
    done
    if kill -0 "-${pid}" 2>/dev/null; then
        kill -KILL "-${pid}" 2>/dev/null || true
    fi
    # Reap the server leader before deleting identity state. This keeps the
    # cleanup idempotent and avoids a stale PID being reused by a later task.
    wait "${pid}" 2>/dev/null || true
    rm -f "${SERVER_PID_FILE}"
}

stop_server_force() {
    stop_server
}

start_server() {
    # The Server interpolates opencode.json's {env:OPENCODE_SNAPSHOT_KEY} and is
    # protected by OPENCODE_SERVER_PASSWORD; both are passed only into the Server
    # process env, and OPENCODE_CONFIG_DIR points at the Task-scoped config dir.
    if ! command -v setsid >/dev/null 2>&1; then
        echo "OpenCode Server requires setsid for safe process-group cleanup" >&2
        return 1
    fi
    OPENCODE_SERVER_PASSWORD="${OPENCODE_SERVER_PASSWORD}" \
    OPENCODE_SNAPSHOT_KEY="${OPENCODE_SNAPSHOT_KEY}" \
    OPENCODE_CONFIG_DIR="${OPENCODE_CONFIG_DIR}" \
    HOME="${HOME}" \
    XDG_CONFIG_HOME="${XDG_CONFIG_HOME}" \
    XDG_DATA_HOME="${XDG_DATA_HOME}" \
    XDG_CACHE_HOME="${XDG_CACHE_HOME}" \
    XDG_STATE_HOME="${XDG_STATE_HOME}" \
    OPENCODE_DISABLE_PROJECT_CONFIG="${OPENCODE_DISABLE_PROJECT_CONFIG}" \
    OPENCODE_DISABLE_EXTERNAL_SKILLS="${OPENCODE_DISABLE_EXTERNAL_SKILLS}" \
    OPENCODE_DISABLE_CLAUDE_CODE_SKILLS="${OPENCODE_DISABLE_CLAUDE_CODE_SKILLS}" \
    CODIFY_OPENCODE_DATA_HOME="${CODIFY_OPENCODE_DATA_HOME}" \
    setsid "${CODIFY_OPENCODE_BIN}" serve \
        --pure \
        --hostname 127.0.0.1 \
        --port "${OPENCODE_PORT}" \
        > "${RUN_DIR}/server.log" 2>&1 &
    local pid=$!
    if ! kill -0 "${pid}" 2>/dev/null; then
        echo "OpenCode Server exited before process-group verification" >&2
        return 1
    fi
    local pgid deadline
    deadline=$(( $(date +%s) + ${OPENCODE_SERVER_PROCESS_GROUP_TIMEOUT:-5} ))
    while kill -0 "${pid}" 2>/dev/null; do
        pgid="$(ps -o pgid= -p "${pid}" 2>/dev/null | tr -d '[:space:]')"
        [ "${pgid}" = "${pid}" ] && break
        [ "$(date +%s)" -lt "${deadline}" ] || break
        sleep 0.05
    done
    if [ "${pgid:-}" != "${pid}" ]; then
        echo "OpenCode Server did not become its own process-group leader" >&2
        kill -TERM "${pid}" 2>/dev/null || true
        wait "${pid}" 2>/dev/null || true
        return 1
    fi
    echo "${pid}" > "${SERVER_PID_FILE}"
}

# 1. Start the Task-scoped Server.
if ! start_server; then
    exit 1
fi
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
OPENCODE_PROVIDER="${OPENCODE_PROVIDER:-codify}" \
OPENCODE_MODEL="${OPENCODE_MODEL:-}" \
CODIFY_RESUME_SESSION="${CODIFY_RESUME_SESSION}" \
RESUME_SESSION="${RESUME_SESSION:-}" \
CODIFY_MODEL_PROTOCOL="${CODIFY_MODEL_PROTOCOL:-anthropic_messages}" \
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
