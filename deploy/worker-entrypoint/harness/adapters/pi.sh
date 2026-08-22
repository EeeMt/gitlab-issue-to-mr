#!/bin/bash
# Pi adapter for the Codify harness contract (V2, open-harness-v2 Phase 2).

CODIFY_PI_TRANSLATOR="${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/adapters/pi_events.py"
CODIFY_PI_BRIDGE="${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/adapters/pi_bridge.py"

codify_pi_bin() {
    if [ -x "/opt/codify-pi/bin/pi" ]; then
        echo "/opt/codify-pi/bin/pi"
        return 0
    fi
    echo "${CODIFY_PI_BIN:-/usr/local/bin/pi}"
}

pi_adapter_metadata() {
    jq -c \
        --arg key pi \
        --arg contract "${CODIFY_RUNTIME_CONTRACT_VERSION:-codify.worker.harness/v2}" \
        --arg event_schema "codify.worker.event/v2" \
        '{ key: $key,
           adapter_version: (.adapters.pi.version // .adapters.pi.adapter.version // ""),
           adapter_digest: (.adapters.pi.digest // ""),
           contract_version: $contract,
           event_schema: $event_schema }' \
        "${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/manifest.json"
}

pi_adapter_verify_runtime() {
    local bin
    bin="$(codify_pi_bin)"
    if [ ! -x "${bin}" ]; then
        echo "Pi CLI is unavailable: ${bin}" >&2
        return 1
    fi
    local version_output pinned normalized
    version_output="$("${bin}" --version 2>/dev/null | head -n 1)"
    if [ -z "${version_output}" ]; then
        echo "Could not read Pi CLI version" >&2
        return 1
    fi
    # pi --version may print "pi 0.84.2" or bare "0.84.2"; normalize to the
    # trailing token before comparing against the manifest pin.
    normalized="$(printf '%s\n' "${version_output}" | awk '{print $NF}')"
    CODIFY_CLI_VERSION="${normalized}"
    export CODIFY_CLI_VERSION
    # Pi 0.84.2 is the frozen version (probe §3.1); refuse to run an unverified
    # binary so manifest pinning is enforced at the container boundary.
    local pinned
    pinned="$(jq -r '.adapters.pi.cli_version // empty' \
        "${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/manifest.json" 2>/dev/null || true)"
    if [ -n "${pinned}" ] && [ "${normalized}" != "${pinned}" ]; then
        echo "Pi CLI version mismatch: expected ${pinned}, got ${normalized}" >&2
        return 1
    fi
    return 0
}

pi_adapter_detect_capabilities() {
    jq -c '.adapters.pi.capabilities // {}' \
        "${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/manifest.json"
}

pi_adapter_prepare_config() {
    # Persist the Pi session on the issue-shared volume so a later continue task
    # can resume the same conversation across containers. Fall back to the
    # per-task runtime dir when the shared volume is absent.
    if [ -d "/opt/codify-issue-shared" ] && [ -w "/opt/codify-issue-shared" ]; then
        export PI_HOME="/opt/codify-issue-shared/pi-home"
    else
        export PI_HOME="${CODIFY_RUNTIME_DIR}/pi-home"
    fi
    mkdir -p "${PI_HOME}"
    chown -R "${CODIFY_RUN_UID:-1000}:${CODIFY_RUN_GID:-1000}" "${PI_HOME}" 2>/dev/null || true

    # Export the Pi transport/model identity so events.py forms the correct V2
    # harness envelope (rpc_stdio / pi-rpc / three model protocols per the
    # manifest). Harmless under V1; no-op when already injected by the runner.
    export CODIFY_HARNESS_CONTROL_TRANSPORT_KIND="${CODIFY_HARNESS_CONTROL_TRANSPORT_KIND:-rpc_stdio}"
    export CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL="${CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL:-pi-rpc}"
    export CODIFY_HARNESS_MODEL_PROTOCOLS="${CODIFY_HARNESS_MODEL_PROTOCOLS:-anthropic_messages,openai_responses,openai_chat_completions}"

    # Model endpoint mapping. The Snapshot's model / base URL / credential are
    # frozen by the backend and injected as env (ANTHROPIC_MODEL / base / key or
    # OPENAI_*). Pi reads custom providers from ~/.pi/agent/models.json; we
    # translate the frozen snapshot into that file so the CLI uses EXACTLY the
    # Snapshot endpoint. Pi's own native config must never override the Snapshot,
    # so we do not read any pre-existing user models.json (PI_HOME is ephemeral).
    local model="${PI_MODEL:-${ANTHROPIC_MODEL:-${OPENAI_MODEL:-}}}"
    local base_url="${PI_BASE_URL:-${ANTHROPIC_BASE_URL:-${OPENAI_BASE_URL:-}}}"
    local api_key="${PI_API_KEY:-${ANTHROPIC_API_KEY:-${OPENAI_API_KEY:-}}}"
    if [ -n "${model}" ] && [ -n "${base_url}" ] && [ -n "${api_key}" ]; then
        # pi 0.84.2 reads custom providers only from ~/.pi/agent/models.json
        # (the CLI subprocess HOME); it ignores the PI_HOME env var. PI_HOME
        # above is kept ONLY for the issue-shared session/skills persistence.
        # The CLI parses only the array form of providers.<name>.models, so the
        # frozen Snapshot must be written in that shape or --list-models is
        # empty and every prompt fails with "Model not found".
        local models_file="${HOME:-/root}/.pi/agent/models.json"
        local api="anthropic-messages"
        if [ -z "${ANTHROPIC_BASE_URL:-}" ] && [ -n "${OPENAI_BASE_URL:-}" ]; then
            api="openai-chat-completions"
        fi
        mkdir -p "$(dirname "${models_file}")"
        # The provider id/name are namespaced to Codify so Pi never shares state
        # with another harness; baseUrl is the frozen Snapshot endpoint.
        jq -nc \
            --arg model "${model}" \
            --arg base_url "${base_url}" \
            --arg api_key "${api_key}" \
            --arg api "${api}" \
            '{providers:{codify:{baseUrl:$base_url,api:$api,apiKey:$api_key,models:[{id:$model,name:$model,reasoning:false,input:["text"],contextWindow:128000,maxTokens:8192}]}}}' \
            > "${models_file}"
        chown "${CODIFY_RUN_UID:-1000}:${CODIFY_RUN_GID:-1000}" "${models_file}" 2>/dev/null || true
        chmod 600 "${models_file}" 2>/dev/null || true
    fi
    return 0
}

pi_adapter_build_command() {
    echo "${CODIFY_HARNESS_COMMAND:-${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/legacy/pi-run.sh}"
}

pi_adapter_materialize_skills() {
    # Managed Skills are materialized to a Task-private Pi directory and loaded
    # through Pi's native mechanism; .claude/skills is NOT the shared
    # intermediate format for Pi (plan §5.4).
    if [ -z "${CODIFY_TASK_SKILLS_DIR:-}" ]; then
        return 0
    fi
    if [ ! -d "${CODIFY_TASK_SKILLS_DIR}" ]; then
        echo "Task Skills snapshot is missing: ${CODIFY_TASK_SKILLS_DIR}" >&2
        return 1
    fi
    local dest="${PI_HOME:-${CODIFY_RUNTIME_DIR}/pi-home}/skills"
    mkdir -p "${dest}"
    if ! cp -a "${CODIFY_TASK_SKILLS_DIR}/." "${dest}/" 2>/dev/null; then
        echo "Could not materialize skills into ${dest}" >&2
        return 1
    fi
    chown -R "${CODIFY_RUN_UID:-1000}:${CODIFY_RUN_GID:-1000}" "${dest}" 2>/dev/null || true
    return 0
}

pi_adapter_run() {
    local prompt_file="$1"
    local result_file="$2"
    local raw_file="${CODIFY_HARNESS_RAW_DIR}/pi.jsonl"
    : > "${raw_file}"
    chown 0:0 "${raw_file}"
    chmod 644 "${raw_file}"
    CODIFY_PI_RUN_AS="${CODIFY_PI_RUN_AS:-}" \
    CODIFY_PI_BIN="$(codify_pi_bin)" \
    CODIFY_PI_RAW_EVENT_JSONL="${raw_file}" \
    CODIFY_PI_EVENT_TRANSLATOR="${CODIFY_PI_TRANSLATOR}" \
    CODIFY_PI_BRIDGE="${CODIFY_PI_BRIDGE}" \
    CODIFY_CANONICAL_EVENT_WRITER="${CODIFY_CANONICAL_EVENT_WRITER}" \
    ARTIFACT_DIR="${CODIFY_RUNTIME_DIR}" \
    CI_CLAUDE_DISABLE_CONSOLE_TEE=1 \
    PROMPT_FILE="${prompt_file}" \
    PI_SESSION_DIR="${CODIFY_RUNTIME_DIR}/pi-session" \
    timeout "${TASK_TIMEOUT:-1800}" "${CODIFY_HARNESS_COMMAND}" > "${result_file}"
}

pi_adapter_stream_events() {
    local raw_file="$1"
    python3 "${CODIFY_PI_TRANSLATOR}" --raw-file "${raw_file}"
}

pi_adapter_normalize_result() {
    local result_file="$1"
    local authoritative="${CODIFY_HARNESS_RESULT_FILE:-${result_file}}"
    [ -s "${authoritative}" ] || return 1
    # Pi is a V2-only adapter: the harness identity is nested under `harness`.
    jq -e \
        --arg harness_key pi \
        --arg adapter_version "${CODIFY_ADAPTER_VERSION}" \
        --arg cli_version "${CODIFY_CLI_VERSION}" \
        '.schema == "codify.worker.result/v2"
         and .harness.key == $harness_key
         and .harness.adapter_version == $adapter_version
         and .harness.cli_version == $cli_version
         and .harness.control_transport.kind != null
         and (.harness.model_protocols | type == "array")
         and (.harness.model_protocols | length > 0)
         and (.status | IN("completed", "failed", "cancelled", "protocol_error"))
         and (.success | type == "boolean")
         and (.usage | type == "object")
         and (.capability_warnings | type == "array")' \
        "${authoritative}" >/dev/null || return 1
    return 0
}

pi_adapter_terminate() {
    # SIGTERM: prefer a native abort/close over the shared Runner grace -> KILL.
    # The running pi RPC only sees an abort via the request pipe; when this runs
    # under the container signal path the pipe fd may already be gone, so fall
    # back to a TERM to the process group (the shared Runner grace then KILLs).
    local pid="${1:-${PI_PID:-}}"
    if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
        kill -TERM "${pid}" 2>/dev/null || true
    fi
    return 0
}

adapter_metadata() { pi_adapter_metadata "$@"; }
adapter_verify_runtime() { pi_adapter_verify_runtime "$@"; }
adapter_detect_capabilities() { pi_adapter_detect_capabilities "$@"; }
adapter_prepare_config() { pi_adapter_prepare_config "$@"; }
adapter_build_command() { pi_adapter_build_command "$@"; }
adapter_materialize_skills() { pi_adapter_materialize_skills "$@"; }
adapter_stream_events() { pi_adapter_stream_events "$@"; }
adapter_normalize_result() { pi_adapter_normalize_result "$@"; }
adapter_run() { pi_adapter_run "$@"; }
adapter_terminate() { pi_adapter_terminate "$@"; }
