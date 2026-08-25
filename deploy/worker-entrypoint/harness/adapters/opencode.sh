#!/bin/bash
# OpenCode adapter for the Codify harness contract (V2, open-harness-v2 Phase 3).

CODIFY_OPENCODE_RUNNER="${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/legacy/opencode-run.sh"
CODIFY_OPENCODE_TRANSLATOR="${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/adapters/opencode_events.py"
CODIFY_OPENCODE_BRIDGE="${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/adapters/opencode_bridge.py"

codify_opencode_bin() {
    # Frozen single source: the backend-injected CODIFY_HARNESS_CLI_BIN (Kit
    # inventory path or authorized host_mount), else the Kit manifest's own
    # inventory path. The runtime image and PATH are never consulted.
    if [ -n "${CODIFY_HARNESS_CLI_BIN:-}" ]; then
        printf '%s\n' "${CODIFY_HARNESS_CLI_BIN}"
        return 0
    fi
    if [ -r "${CODIFY_KIT_HOME:-/opt/codify-kit}/manifest.json" ]; then
        local path
        path="$(jq -r --arg k opencode '.harness_inventory[$k].path // empty' \
            "${CODIFY_KIT_HOME:-/opt/codify-kit}/manifest.json" 2>/dev/null || true)"
        if [ -n "${path}" ]; then
            printf '%s\n' "${path}"
            return 0
        fi
    fi
    return 1
}

opencode_adapter_metadata() {
    jq -c \
        --arg key opencode \
        --arg contract "${CODIFY_RUNTIME_CONTRACT_VERSION:-codify.worker.harness/v2}" \
        --arg event_schema "codify.worker.event/v2" \
        '{ key: $key,
           adapter_version: (.adapters.opencode.version // .adapters.opencode.adapter.version // ""),
           adapter_digest: (.adapters.opencode.digest // ""),
           contract_version: $contract,
           event_schema: $event_schema }' \
        "${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/manifest.json"
}

opencode_adapter_verify_runtime() {
    local bin
    bin="$(codify_opencode_bin)" || {
        echo "OpenCode CLI is not available from the Worker Kit inventory" >&2
        return 1
    }
    if [ ! -x "${bin}" ]; then
        echo "OpenCode CLI is unavailable: ${bin}" >&2
        return 1
    fi
    CODIFY_OPENCODE_BIN="${bin}"
    export CODIFY_OPENCODE_BIN
    local version_output pinned normalized
    version_output="$("${bin}" --version 2>/dev/null | head -n 1)"
    if [ -z "${version_output}" ]; then
        echo "Could not read OpenCode CLI version" >&2
        return 1
    fi
    normalized="$(printf '%s\n' "${version_output}" | awk '{print $NF}')"
    CODIFY_CLI_VERSION="${normalized}"
    export CODIFY_CLI_VERSION
    # The Adapter-declared pinned version is the tested/baseline, not a hard
    # gate: an observed difference only logs a sanitized advisory warning and
    # execution continues (§11.2 Compatibility policy).
    local pinned
    pinned="$(jq -r '.adapters.opencode.cli_version // empty' \
        "${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/manifest.json" 2>/dev/null || true)"
    if [ -n "${pinned}" ] && [ "${normalized}" != "${pinned}" ]; then
        echo "WARNING: OpenCode CLI version ${normalized} differs from the Adapter baseline ${pinned} (advisory, not enforced)" >&2
    fi
    return 0
}

opencode_adapter_detect_capabilities() {
    jq -c '.adapters.opencode.capabilities // {}' \
        "${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/manifest.json"
}

# Probe a free loopback port (bind 127.0.0.1:0, read the kernel-assigned port,
# release it) and print it. The Server is then started with an explicit --port
# so the Bridge needs no race-prone discovery channel (design §1.1, frozen).
opencode_probe_port() {
    python3 - <<'PY'
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(("127.0.0.1", 0))
port = s.getsockname()[1]
s.close()
print(port)
PY
}

opencode_adapter_prepare_config() {
    # Task-scoped OpenCode config dir (ephemeral; never a shared user config).
    local config_dir="${CODIFY_RUNTIME_DIR}/opencode"
    mkdir -p "${config_dir}"
    chown -R "${CODIFY_RUN_UID:-1000}:${CODIFY_RUN_GID:-1000}" "${config_dir}" 2>/dev/null || true

    # Export the OpenCode transport/model identity so events.py forms the
    # correct V2 harness envelope. HTTP direct is the current production path;
    # only the fixed-version Anthropic-compatible mapping is advertised.
    export CODIFY_HARNESS_CONTROL_TRANSPORT_KIND="${CODIFY_HARNESS_CONTROL_TRANSPORT_KIND:-server_http}"
    export CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL="${CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL:-opencode-server}"
    export CODIFY_HARNESS_MODEL_PROTOCOLS="${CODIFY_HARNESS_MODEL_PROTOCOLS:-anthropic_messages}"

    # Port bridge: probe a free loopback port for the Server's explicit --port.
    # Tests and controlled launchers may preallocate a loopback port; otherwise
    # allocate one here. The Server remains bound only to loopback.
    OPENCODE_PORT="${OPENCODE_PORT:-$(opencode_probe_port)}"
    export OPENCODE_PORT

    # Task-private Server password (mandatory: an unset password leaves the
    # Server unprotected per probe fact). Never written to logs / raw archive.
    OPENCODE_SERVER_PASSWORD="${OPENCODE_SERVER_PASSWORD:-$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')}"
    export OPENCODE_SERVER_PASSWORD

    # Snapshot model / endpoint / credential are frozen by the backend and
    # injected as env. Translate into opencode.json so the Server uses EXACTLY
    # the Snapshot endpoint; OpenCode env-interpolates {env:VAR}, not $VAR.
    local model_protocol="${CODIFY_MODEL_PROTOCOL:-anthropic_messages}"
    if [ "${model_protocol}" != "anthropic_messages" ]; then
        echo "OpenCode does not support model protocol ${model_protocol} in this Runtime Bundle" >&2
        return 1
    fi
    local model="${OPENCODE_MODEL:-${ANTHROPIC_MODEL:-}}"
    local base_url="${OPENCODE_BASE_URL:-${ANTHROPIC_BASE_URL:-}}"
    local api_key="${OPENCODE_API_KEY:-${ANTHROPIC_API_KEY:-}}"
    local provider_npm="${OPENCODE_PROVIDER_NPM:-@ai-sdk/anthropic}"
    if [ -n "${model}" ] && [ -n "${base_url}" ] && [ -n "${api_key}" ]; then
        # The credential is referenced by a stable env name, not inlined, so it
        # never reaches opencode.json / the raw archive. The runner passes
        # OPENCODE_SNAPSHOT_KEY through to the Server, which interpolates it.
        export OPENCODE_SNAPSHOT_KEY="${api_key}"
        # @ai-sdk/anthropic appends /messages to options.baseURL, so the raw
        # relay root gives /messages (404). Normalize to the /v1 root so the SDK
        # hits /v1/messages, which the relay answers with 200. An endpoint that
        # already carries /v1 must be left untouched, or the SDK double-hangs as
        # /v1/v1.
        local api_base
        case "${base_url}" in
            */v1|*/v1/) api_base="${base_url%/}" ;;
            *) api_base="${base_url%/}/v1" ;;
        esac
        jq -nc \
            --arg model "${model}" \
            --arg api_base "${api_base}" \
            --arg npm "${provider_npm}" \
            '{provider:{codify:{npm:$npm,options:{baseURL:$api_base,apiKey:"{env:OPENCODE_SNAPSHOT_KEY}"},models:{($model):{id:$model,provider:{id:"codify"}}}}}}' \
            > "${config_dir}/opencode.json"
        chown "${CODIFY_RUN_UID:-1000}:${CODIFY_RUN_GID:-1000}" "${config_dir}/opencode.json" 2>/dev/null || true
    fi
    export OPENCODE_MODEL="${model}"
    return 0
}

opencode_adapter_build_command() {
    echo "${CODIFY_HARNESS_COMMAND:-${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/legacy/opencode-run.sh}"
}

opencode_adapter_materialize_skills() {
    # Managed Skills are materialized into the Task-scoped OpenCode config dir
    # and loaded through OpenCode's official skills path (task_skills=true).
    if [ -z "${CODIFY_TASK_SKILLS_DIR:-}" ]; then
        return 0
    fi
    if [ ! -d "${CODIFY_TASK_SKILLS_DIR}" ]; then
        echo "Task Skills snapshot is missing: ${CODIFY_TASK_SKILLS_DIR}" >&2
        return 1
    fi
    local dest="${CODIFY_RUNTIME_DIR}/opencode/skills"
    mkdir -p "${dest}"
    if ! cp -a "${CODIFY_TASK_SKILLS_DIR}/." "${dest}/" 2>/dev/null; then
        echo "Could not materialize skills into ${dest}" >&2
        return 1
    fi
    chown -R "${CODIFY_RUN_UID:-1000}:${CODIFY_RUN_GID:-1000}" "${dest}" 2>/dev/null || true
    return 0
}

opencode_adapter_run() {
    local prompt_file="$1"
    local result_file="$2"
    local raw_file="${CODIFY_HARNESS_RAW_DIR}/opencode.jsonl"
    : > "${raw_file}"
    chown 0:0 "${raw_file}"
    chmod 644 "${raw_file}"
    CODIFY_OPENCODE_BIN="$(codify_opencode_bin)" \
    CODIFY_OPENCODE_RAW_EVENT_JSONL="${raw_file}" \
    CODIFY_OPENCODE_EVENT_TRANSLATOR="${CODIFY_OPENCODE_TRANSLATOR}" \
    CODIFY_OPENCODE_BRIDGE="${CODIFY_OPENCODE_BRIDGE}" \
    CODIFY_CANONICAL_EVENT_WRITER="${CODIFY_CANONICAL_EVENT_WRITER}" \
    OPENCODE_PORT="${OPENCODE_PORT}" \
    OPENCODE_SERVER_PASSWORD="${OPENCODE_SERVER_PASSWORD}" \
    PROMPT_FILE="${prompt_file}" \
    timeout "${TASK_TIMEOUT:-1800}" "${CODIFY_HARNESS_COMMAND}" > "${result_file}"
}

opencode_adapter_stream_events() {
    local raw_file="$1"
    python3 "${CODIFY_OPENCODE_TRANSLATOR}" --raw-file "${raw_file}"
}

opencode_adapter_normalize_result() {
    local result_file="$1"
    local authoritative="${CODIFY_HARNESS_RESULT_FILE:-${result_file}}"
    [ -s "${authoritative}" ] || return 1
    # OpenCode is a V2-only adapter: the harness identity is nested under `harness`.
    jq -e \
        --arg harness_key opencode \
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

opencode_adapter_terminate() {
    # SIGTERM: stop the Task-scoped OpenCode Server with no-daemon convergence.
    # The Server process was started by the runner; on the container signal path
    # the runner may already be gone, so fall back to the shared Runner's grace
    # -> KILL. Prefer an in-flight abort before TERM when a Bridge is attached.
    local pid="${1:-${OPENCODE_SERVER_PID:-}}"
    if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
        kill -TERM "${pid}" 2>/dev/null || true
    fi
    return 0
}

adapter_metadata() { opencode_adapter_metadata "$@"; }
adapter_verify_runtime() { opencode_adapter_verify_runtime "$@"; }
adapter_detect_capabilities() { opencode_adapter_detect_capabilities "$@"; }
adapter_prepare_config() { opencode_adapter_prepare_config "$@"; }
adapter_build_command() { opencode_adapter_build_command "$@"; }
adapter_materialize_skills() { opencode_adapter_materialize_skills "$@"; }
adapter_stream_events() { opencode_adapter_stream_events "$@"; }
adapter_normalize_result() { opencode_adapter_normalize_result "$@"; }
adapter_run() { opencode_adapter_run "$@"; }
adapter_terminate() { opencode_adapter_terminate "$@"; }
