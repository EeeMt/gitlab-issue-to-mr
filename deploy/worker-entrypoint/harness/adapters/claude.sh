#!/bin/bash

CODIFY_CLAUDE_TRANSLATOR="${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/adapters/claude_events.py"

claude_adapter_metadata() {
    local manifest_path="${CODIFY_ORCHESTRATION_DIR}/manifest.json"
    if [ ! -r "${manifest_path}" ]; then
        manifest_path="${ENTRYPOINT_LIB_DIR}/harness/manifest.json"
    fi
    # Claude emits the V1 or V2 envelope/result per the runtime contract the
    # backend freezes into the attempt. The manifest top-level stays V1 until
    # the Phase 5 hard switch; this operator honours an explicit override.
    local contract="${CODIFY_RUNTIME_CONTRACT_VERSION:-codify.worker.harness/v1}"
    local event_schema="${CODIFY_EVENT_SCHEMA:-codify.worker.event/v1}"
    if [ "${contract}" = "codify.worker.harness/v2" ]; then
        event_schema="${CODIFY_EVENT_SCHEMA:-codify.worker.event/v2}"
    fi
    jq -ce \
        --arg contract "${contract}" \
        --arg event_schema "${event_schema}" \
        '
        . as $manifest
        | .adapters.claude
        | . + {
            key:"claude",
            adapter_version:.version,
            contract_version:$contract,
            event_schema:$event_schema
        }
    ' "${manifest_path}"
}

claude_adapter_verify_runtime() {
    case "${CODIFY_CLAUDE_BIN}" in
        /*) ;;
        *) echo "CODIFY_CLAUDE_BIN must be an absolute path" >&2; return 1 ;;
    esac
    [ -x "${CODIFY_CLAUDE_BIN}" ] || {
        echo "Claude CLI is unavailable: ${CODIFY_CLAUDE_BIN}" >&2
        return 1
    }
    [ -x "${CODIFY_CLAUDE_TRANSLATOR}" ] || {
        echo "Claude event translator is unavailable: ${CODIFY_CLAUDE_TRANSLATOR}" >&2
        return 1
    }
    local version_output
    version_output="$(codify_run_shell '"${CODIFY_CLAUDE_BIN}" --version')" || return 1
    [[ "${version_output}" =~ ([0-9]+)\.([0-9]+)\.([0-9]+) ]] || {
        echo "Could not parse Claude CLI version: ${version_output}" >&2
        return 1
    }
    if (( 10#${BASH_REMATCH[1]} < 2 \
        || (10#${BASH_REMATCH[1]} == 2 && 10#${BASH_REMATCH[2]} < 1) \
        || (10#${BASH_REMATCH[1]} == 2 && 10#${BASH_REMATCH[2]} == 1 \
            && 10#${BASH_REMATCH[3]} < 33) )); then
        echo "Claude CLI 2.1.33 or newer is required: ${version_output}" >&2
        return 1
    fi
    CODIFY_CLI_VERSION="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}.${BASH_REMATCH[3]}"
    export CODIFY_CLI_VERSION
    # cli_version_range in the manifest is an advisory fast-startup hint, not an
    # enforced gate: an out-of-range CLI logs a warning and is allowed to run.
    local cli_range version_range_py manifest_path
    version_range_py="${CODIFY_ORCHESTRATION_DIR:-}/worker-entrypoint/harness/version_range.py"
    manifest_path="${CODIFY_ORCHESTRATION_DIR:-}/manifest.json"
    [ -r "${manifest_path}" ] || manifest_path="${ENTRYPOINT_LIB_DIR:-}/harness/manifest.json"
    cli_range="$(jq -r '.adapters.claude.cli_version_range // empty' "${manifest_path}" 2>/dev/null || true)"
    if [ -n "${cli_range}" ] && [ -f "${version_range_py}" ] \
        && ! python3 "${version_range_py}" \
            --version "${CODIFY_CLI_VERSION}" --range "${cli_range}" >/dev/null 2>&1; then
        echo "WARNING: Claude CLI ${CODIFY_CLI_VERSION} is outside the declared range ${cli_range} (advisory, not enforced)" >&2
    fi
    if [ -n "${CODIFY_CLI_BINARY_DIGEST:-}" ]; then
        local actual_digest
        actual_digest="$(sha256sum "${CODIFY_CLAUDE_BIN}" 2>/dev/null | awk '{print $1}')"
        if [ -z "${actual_digest}" ] || [ "${actual_digest}" != "${CODIFY_CLI_BINARY_DIGEST}" ]; then
            echo "Claude CLI binary digest mismatch: expected ${CODIFY_CLI_BINARY_DIGEST}, got ${actual_digest:-unreadable}" >&2
            return 1
        fi
    fi
}

claude_adapter_detect_capabilities() {
    claude_adapter_metadata | jq -ce '.capabilities'
}

claude_adapter_prepare_config() {
    mkdir -p /home/codify/.claude "${CODIFY_HARNESS_RAW_DIR}"
    codify_chown -R /home/codify/.claude "${CODIFY_HARNESS_RAW_DIR}"
    chmod 700 /home/codify/.claude

    # Export the claude transport/model identity so events.py forms the
    # correct V2 harness envelope (cli_stream_json / claude-json /
    # anthropic_messages). Harmless under V1 (events.py ignores them). No-op
    # when the attempt already injects them.
    export CODIFY_HARNESS_CONTROL_TRANSPORT_KIND="${CODIFY_HARNESS_CONTROL_TRANSPORT_KIND:-cli_stream_json}"
    export CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL="${CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL:-claude-json}"
    export CODIFY_HARNESS_MODEL_PROTOCOLS="${CODIFY_HARNESS_MODEL_PROTOCOLS:-anthropic_messages}"

    local claude_system_prompt_file="/tmp/claude_system_prompt.txt"
    if [ -n "${APPEND_SYSTEM_PROMPT:-}" ]; then
        printf '%s' "${APPEND_SYSTEM_PROMPT}" > "${claude_system_prompt_file}"
        chmod 600 "${claude_system_prompt_file}"
        codify_chown "${claude_system_prompt_file}"
        APPEND_SYSTEM_PROMPT_FILE="${claude_system_prompt_file}"
        export APPEND_SYSTEM_PROMPT_FILE
        unset APPEND_SYSTEM_PROMPT
    fi

    # The mounted session volume persists Claude backups but older volumes may
    # not contain the top-level configuration file.
    if [ ! -f /home/codify/.claude.json ]; then
        local latest_backup=""
        latest_backup=$(ls -t /home/codify/.claude/backups/.claude.json.backup.* 2>/dev/null \
            | head -1 || true)
        if [ -n "${latest_backup}" ]; then
            echo "Restoring .claude.json from backup: ${latest_backup}"
            cp "${latest_backup}" /home/codify/.claude.json
        else
            echo "Creating minimal .claude.json"
            printf '{}\n' > /home/codify/.claude.json
        fi
        codify_chown /home/codify/.claude.json
    fi
}

claude_adapter_build_command() {
    printf '%s\n' "${CODIFY_ORCHESTRATION_DIR}/legacy/ci-claude.sh"
}

claude_adapter_materialize_skills() {
    if [ -n "${CODIFY_TASK_SKILLS_DIR:-}" ]; then
        [ -d "${CODIFY_TASK_SKILLS_DIR}/.claude/skills" ] || {
            echo "Task Skills snapshot does not contain .claude/skills" >&2
            return 1
        }
    fi
}

claude_adapter_run() {
    local prompt_file="$1"
    local result_file="$2"
    local raw_file="${CODIFY_HARNESS_RAW_DIR}/claude.jsonl"
    local legacy_runner
    legacy_runner="${CODIFY_HARNESS_COMMAND:-}"
    if [ -z "${legacy_runner}" ]; then
        legacy_runner="$(claude_adapter_build_command)" || return 1
    fi
    : > "${raw_file}"
    chown 0:0 "${raw_file}"
    chmod 644 "${raw_file}"
    CODIFY_CLAUDE_RAW_EVENT_JSONL="${raw_file}" \
    CODIFY_CLAUDE_EVENT_TRANSLATOR="${CODIFY_CLAUDE_TRANSLATOR}" \
    CODIFY_CANONICAL_EVENT_WRITER="${CODIFY_CANONICAL_EVENT_WRITER}" \
    CODIFY_CLAUDE_RUN_AS="${CODIFY_RUN_AS:-}" \
    ARTIFACT_DIR="${CODIFY_RUNTIME_DIR}" \
    CI_CLAUDE_DISABLE_CONSOLE_TEE=1 \
    PROMPT_FILE="${prompt_file}" \
    timeout "${TASK_TIMEOUT:-1800}" "${legacy_runner}" > "${result_file}"
}

claude_adapter_stream_events() {
    local raw_file="$1"
    python3 "${CODIFY_CLAUDE_TRANSLATOR}" --raw-file "${raw_file}"
}

claude_adapter_normalize_result() {
    # The streaming translator atomically writes the Canonical Result. Validate
    # its portable shape and frozen Adapter identity before public delivery.
    # Accept the result schema matching the active contract (v1 in production
    # today, v2 once the runtime contract flips).
    local schema="codify.worker.result/v1"
    if [ "${CODIFY_RUNTIME_CONTRACT_VERSION:-}" = "codify.worker.harness/v2" ]; then
        schema="codify.worker.result/v2"
    fi
    jq -e \
        --arg harness_key "${CODIFY_HARNESS_KEY}" \
        --arg adapter_version "${CODIFY_ADAPTER_VERSION}" \
        --arg cli_version "${CODIFY_CLI_VERSION}" \
        --arg schema "${schema}" \
        '.schema == $schema
         and .harness_key == $harness_key
         and .adapter_version == $adapter_version
         and .cli_version == $cli_version
         and (.status | IN("completed", "failed", "cancelled", "protocol_error"))
         and (.success | type == "boolean")
         and (.usage | type == "object")
         and (.capability_warnings | type == "array")' \
        "${CODIFY_HARNESS_RESULT_FILE}" >/dev/null
}

claude_adapter_run_text() {
    local prompt_file="$1"
    local timeout_seconds="${2:-60}"
    codify_run_shell \
        'cd /workspace && timeout '"${timeout_seconds}"' "${CODIFY_CLAUDE_BIN}" -p --bare --tools "" --permission-mode plan --no-session-persistence --output-format text --max-turns 3 --model "${ANTHROPIC_MODEL}" < '"${prompt_file}"
}

claude_adapter_terminate() {
    local pid="${1:-}"
    [ -n "${pid}" ] || return 0
    kill -TERM "${pid}" 2>/dev/null || true
}

# Public contract aliases. The common runner never calls a Harness-specific name.
adapter_metadata() { claude_adapter_metadata "$@"; }
adapter_verify_runtime() { claude_adapter_verify_runtime "$@"; }
adapter_detect_capabilities() { claude_adapter_detect_capabilities "$@"; }
adapter_prepare_config() { claude_adapter_prepare_config "$@"; }
adapter_build_command() { claude_adapter_build_command "$@"; }
adapter_materialize_skills() { claude_adapter_materialize_skills "$@"; }
adapter_stream_events() { claude_adapter_stream_events "$@"; }
adapter_normalize_result() { claude_adapter_normalize_result "$@"; }
adapter_run() { claude_adapter_run "$@"; }
adapter_run_text() { claude_adapter_run_text "$@"; }
adapter_terminate() { claude_adapter_terminate "$@"; }
