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
    export CODIFY_OPENCODE_HTTP_AUDIT_FILE="${CODIFY_RUNTIME_DIR}/opencode-http-audit.jsonl"
    local task_home="${config_dir}/home"
    local xdg_config_home="${config_dir}/xdg-config"
    local xdg_data_home="${config_dir}/xdg-data"
    local xdg_cache_home="${config_dir}/xdg-cache"
    local xdg_state_home="${config_dir}/xdg-state"
    # OpenCode stores its session database below XDG_DATA_HOME. Keep that one
    # harness-specific directory on the issue-shared volume so a later task can
    # GET and continue the same session; config/cache/state remain ephemeral so
    # provider credentials and user settings never cross task boundaries.
    local issue_shared="/opt/codify-issue-shared"
    if [ -d "${issue_shared}" ] && mkdir -p "${issue_shared}/opencode-data" \
        && chown "${CODIFY_RUN_UID:-1000}:${CODIFY_RUN_GID:-1000}" "${issue_shared}/opencode-data" 2>/dev/null; then
        xdg_data_home="${issue_shared}/opencode-data"
    fi
    mkdir -p "${config_dir}" "${task_home}" "${xdg_config_home}" \
        "${xdg_data_home}" "${xdg_cache_home}" "${xdg_state_home}"
    chown -R "${CODIFY_RUN_UID:-1000}:${CODIFY_RUN_GID:-1000}" "${config_dir}" 2>/dev/null || true

    # OpenCode normally merges global/user state and project files into the
    # task config.  Both are outside the frozen Snapshot boundary: isolate all
    # HOME/XDG roots, force the task config directory, and disable implicit
    # project discovery.  The fixed 1.18.19 CLI supports this flag; the
    # runner's --pure additionally disables external plugins.
    export HOME="${task_home}"
    export XDG_CONFIG_HOME="${xdg_config_home}"
    export XDG_DATA_HOME="${xdg_data_home}"
    export XDG_CACHE_HOME="${xdg_cache_home}"
    export XDG_STATE_HOME="${xdg_state_home}"
    export OPENCODE_CONFIG_DIR="${config_dir}"
    export CODIFY_OPENCODE_DATA_HOME="${xdg_data_home}"
    export OPENCODE_DISABLE_PROJECT_CONFIG="true"
    # The frozen Snapshot already declares the exact Provider and Model.  The
    # public models.dev catalog is non-essential and is not reachable from all
    # authorized Hosts; prevent its startup refresh from aborting a Task.
    export OPENCODE_DISABLE_MODELS_FETCH="1"
    # Do not scan the repository or any external Claude-compatible skills.
    # Managed Skills are installed below OPENCODE_CONFIG_DIR/skills instead.
    export OPENCODE_DISABLE_EXTERNAL_SKILLS="1"
    export OPENCODE_DISABLE_CLAUDE_CODE_SKILLS="1"
    unset OPENCODE_CONFIG OPENCODE_CONFIG_CONTENT

    # Only the small, validated OpenCode options schema crosses the Snapshot
    # boundary.  Do not accept arbitrary config or command names from the
    # repository/environment: the backend has already validated the payload,
    # and this worker-side check keeps a malformed/hand-built container
    # fail-closed as well.
    local options_json="${CODIFY_HARNESS_OPTIONS_JSON:-}"
    if [ -z "${options_json}" ]; then
        options_json='{}'
    fi
    if ! printf '%s' "${options_json}" | jq -e 'type == "object"' >/dev/null 2>&1; then
        echo "OpenCode harness options are not a JSON object" >&2
        return 1
    fi
    local option_agent option_command option_variant
    option_agent="$(printf '%s' "${options_json}" | jq -r '.agent // "build"')"
    option_command="$(printf '%s' "${options_json}" | jq -r '.command // empty')"
    option_variant="$(printf '%s' "${options_json}" | jq -r '.model_variant // empty')"
    if ! printf '%s' "${options_json}" | jq -e \
        '(((keys - ["agent", "command", "model_variant"]) | length) == 0)
         and ((.agent // "build") | IN("build", "plan", "general", "explore"))
         and ((.command == null) or .command == "codify")
         and ((.model_variant == null)
              or (.model_variant | type == "string" and test("^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")))' \
        >/dev/null 2>&1; then
        echo "OpenCode harness options contain an invalid agent, command, or model variant" >&2
        return 1
    fi
    export CODIFY_OPENCODE_AGENT="${option_agent}"
    if [ -n "${option_command}" ]; then
        export CODIFY_OPENCODE_COMMAND="${option_command}"
    else
        unset CODIFY_OPENCODE_COMMAND
    fi
    if [ -n "${option_variant}" ]; then
        export CODIFY_OPENCODE_VARIANT="${option_variant}"
    else
        unset CODIFY_OPENCODE_VARIANT
    fi

    # Export the OpenCode transport/model identity so events.py forms the
    # correct V2 harness envelope. HTTP direct is the current production path;
    # the capability list is read from the frozen Runtime Bundle manifest.
    export CODIFY_HARNESS_CONTROL_TRANSPORT_KIND="${CODIFY_HARNESS_CONTROL_TRANSPORT_KIND:-server_http}"
    export CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL="${CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL:-opencode-server}"

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
    local manifest_path="${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/manifest.json"
    local declared_model_protocols
    declared_model_protocols="$(jq -er \
        '.adapters.opencode.model_protocols | select(type == "array" and length > 0) | join(",")' \
        "${manifest_path}" 2>/dev/null)" || {
        echo "OpenCode Runtime Bundle manifest has no model protocol declaration" >&2
        return 1
    }
    if ! jq -e --arg protocol "${model_protocol}" \
        '.adapters.opencode.model_protocols | index($protocol) != null' \
        "${manifest_path}" >/dev/null 2>&1; then
        echo "OpenCode Runtime Bundle does not declare model protocol ${model_protocol}" >&2
        return 1
    fi
    export CODIFY_HARNESS_MODEL_PROTOCOLS="${declared_model_protocols}"
    export OPENCODE_PROVIDER="codify"

    local model base_url api_key provider_npm
    case "${model_protocol}" in
        anthropic_messages)
            model="${ANTHROPIC_MODEL:-}"
            base_url="${ANTHROPIC_BASE_URL:-}"
            api_key="${ANTHROPIC_API_KEY:-}"
            provider_npm="@ai-sdk/anthropic"
            ;;
        openai_responses)
            model="${OPENAI_MODEL:-}"
            base_url="${OPENAI_BASE_URL:-}"
            api_key="${OPENAI_API_KEY:-}"
            provider_npm="@ai-sdk/openai"
            ;;
        openai_chat_completions)
            model="${OPENAI_MODEL:-}"
            base_url="${OPENAI_BASE_URL:-}"
            api_key="${OPENAI_API_KEY:-}"
            provider_npm="@ai-sdk/openai-compatible"
            ;;
        *)
            echo "OpenCode does not support model protocol ${model_protocol} in this Runtime Bundle" >&2
            return 1
            ;;
    esac
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
        local config_json
        config_json="$(jq -nc \
            --arg model "${model}" \
            --arg api_base "${api_base}" \
            --arg npm "${provider_npm}" \
            '{permission:{external_directory:{"*":"ask","/tmp/**":"allow"}},
              provider:{codify:{npm:$npm,options:{baseURL:$api_base,apiKey:"{env:OPENCODE_SNAPSHOT_KEY}"},models:{($model):{id:$model,provider:{id:"codify"}}}}}}')"
        if [ -n "${option_command}" ]; then
            config_json="$(printf '%s' "${config_json}" | jq \
                --arg command "${option_command}" \
                '. + {command:{($command):{description:"Codify task command",template:"$ARGUMENTS"}}}')"
        fi
        printf '%s\n' "${config_json}" > "${config_dir}/opencode.json"
        chown "${CODIFY_RUN_UID:-1000}:${CODIFY_RUN_GID:-1000}" "${config_dir}/opencode.json" 2>/dev/null || true
    fi
    export OPENCODE_MODEL="${model}"
    return 0
}

opencode_adapter_build_command() {
    echo "${CODIFY_HARNESS_COMMAND:-${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/legacy/opencode-run.sh}"
}

opencode_adapter_materialize_skills() {
    # Managed Skills are materialized into the Task-scoped OpenCode config
    # directory. OpenCode 1.18.19 discovers ``OPENCODE_CONFIG_DIR/skills``;
    # copying the shared ``.claude/skills`` wrapper itself would produce the
    # wrong ``skills/.claude/skills`` nesting and silently hide every Skill.
    if [ -z "${CODIFY_TASK_SKILLS_DIR:-}" ]; then
        return 0
    fi
    if [ ! -d "${CODIFY_TASK_SKILLS_DIR}" ]; then
        echo "Task Skills snapshot is missing: ${CODIFY_TASK_SKILLS_DIR}" >&2
        return 1
    fi
    local config_dir="${CODIFY_RUNTIME_DIR}/opencode"
    local task_home="${config_dir}/home"
    local src="${CODIFY_TASK_SKILLS_DIR}/.claude/skills"
    if [ ! -d "${src}" ]; then
        echo "Task Skills snapshot does not contain .claude/skills: ${src}" >&2
        return 1
    fi
    local dest="${config_dir}/skills"
    # Keep a direct invocation of this operation hermetic too; the normal
    # runner already exported the same values during prepare_config.
    export HOME="${task_home}"
    export XDG_CONFIG_HOME="${config_dir}/xdg-config"
    export XDG_DATA_HOME="${CODIFY_OPENCODE_DATA_HOME:-${config_dir}/xdg-data}"
    export XDG_CACHE_HOME="${config_dir}/xdg-cache"
    export XDG_STATE_HOME="${config_dir}/xdg-state"
    export OPENCODE_CONFIG_DIR="${config_dir}"
    export CODIFY_OPENCODE_DATA_HOME="${XDG_DATA_HOME}"
    export OPENCODE_DISABLE_PROJECT_CONFIG="true"
    export OPENCODE_DISABLE_MODELS_FETCH="1"
    export OPENCODE_DISABLE_EXTERNAL_SKILLS="1"
    export OPENCODE_DISABLE_CLAUDE_CODE_SKILLS="1"
    unset OPENCODE_CONFIG OPENCODE_CONFIG_CONTENT
    mkdir -p "${dest}"
    if ! cp -a "${src}/." "${dest}/" 2>/dev/null; then
        echo "Could not materialize skills into ${dest}" >&2
        return 1
    fi
    chown -R "${CODIFY_RUN_UID:-1000}:${CODIFY_RUN_GID:-1000}" "${dest}" 2>/dev/null || true

    # ``task_skills=true`` is an executable capability, not just a copy
    # operation. Ask the pinned CLI to enumerate the materialized Skills and
    # require every selected Skill to resolve from this Task-private root.
    local cli="${CODIFY_OPENCODE_BIN:-}"
    if [ -z "${cli}" ]; then
        cli="$(codify_opencode_bin)" || {
            echo "OpenCode CLI is unavailable for Task Skills verification" >&2
            return 1
        }
    fi
    local discovered
    discovered="$("${cli}" debug skill --pure 2>/dev/null)" || {
        echo "OpenCode could not enumerate materialized Task Skills" >&2
        return 1
    }
    local skill_file skill_name
    for skill_file in "${src}"/*/SKILL.md; do
        [ -f "${skill_file}" ] || continue
        skill_name="$(basename "$(dirname "${skill_file}")")"
        if ! printf '%s' "${discovered}" | jq -e \
            --arg name "${skill_name}" \
            --arg root "${dest}/" \
            'any(.[]?; .name == $name and (.location | (type == "string" and startswith($root))))' \
            >/dev/null 2>&1; then
            echo "OpenCode did not discover Task Skill ${skill_name} from ${dest}" >&2
            return 1
        fi
    done
    return 0
}

opencode_adapter_run() {
    local prompt_file="$1"
    local result_file="$2"
    local raw_file="${CODIFY_HARNESS_RAW_DIR}/opencode.jsonl"
    local audit_file="${CODIFY_OPENCODE_HTTP_AUDIT_FILE:-${CODIFY_RUNTIME_DIR}/opencode-http-audit.jsonl}"
    : > "${raw_file}"
    : > "${audit_file}"
    chown 0:0 "${raw_file}"
    chown 0:0 "${audit_file}"
    chmod 644 "${raw_file}"
    chmod 644 "${audit_file}"
    # The root adapter owns the canonical event stream; the OpenCode Server
    # and its repository tools must run as codify so Harness-created files and
    # Git metadata remain writable by the outer Worker delivery path.
    CODIFY_OPENCODE_BIN="$(codify_opencode_bin)" \
    CODIFY_OPENCODE_RAW_EVENT_JSONL="${raw_file}" \
    CODIFY_OPENCODE_HTTP_AUDIT_FILE="${audit_file}" \
    CODIFY_OPENCODE_EVENT_TRANSLATOR="${CODIFY_OPENCODE_TRANSLATOR}" \
    CODIFY_OPENCODE_BRIDGE="${CODIFY_OPENCODE_BRIDGE}" \
    CODIFY_OPENCODE_RUN_AS="${CODIFY_OPENCODE_RUN_AS:-${CODIFY_RUN_AS:-}}" \
    CODIFY_OPENCODE_SESSION_FILE="${CODIFY_OPENCODE_SESSION_FILE:-${CODIFY_RUNTIME_DIR}/opencode-session.id}" \
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
    # SIGTERM: request the native session abort before stopping the adapter.
    # The marker is Task-local and is removed by the runner after cleanup.
    local session_file="${CODIFY_OPENCODE_SESSION_FILE:-${CODIFY_RUNTIME_DIR}/opencode-session.id}"
    local session_id
    session_id="$(cat "${session_file}" 2>/dev/null || true)"
    if [ -n "${session_id}" ]; then
        local audit_file="${CODIFY_OPENCODE_HTTP_AUDIT_FILE:-${CODIFY_RUNTIME_DIR}/opencode-http-audit.jsonl}"
        OPENCODE_SERVER_PASSWORD="${OPENCODE_SERVER_PASSWORD:-}" \
        OPENCODE_SERVER_USERNAME="${OPENCODE_SERVER_USERNAME:-opencode}" \
        OPENCODE_PORT="${OPENCODE_PORT:-}" \
        CODIFY_OPENCODE_HTTP_AUDIT_FILE="${audit_file}" \
        CODIFY_OPENCODE_SESSION_FILE="${session_file}" \
        python3 "${CODIFY_OPENCODE_BRIDGE}" abort "${session_id}" || true
    fi
    local pid="${1:-}"
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
