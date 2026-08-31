#!/bin/bash

codify_harness_initialize() {
    if [ "${CODIFY_HARNESS_INITIALIZED:-0}" -eq 1 ]; then
        return 0
    fi
    CODIFY_HARNESS_KEY="${CODIFY_HARNESS_KEY:-claude}"
    local adapter_path capabilities command_path frozen_adapter_version operation
    local resolved_adapter_version
    adapter_path="${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/adapters/${CODIFY_HARNESS_KEY}.sh"
    [ -r "${adapter_path}" ] || {
        echo "Unsupported frozen Harness Adapter: ${CODIFY_HARNESS_KEY}" >&2
        return 1
    }
    # shellcheck source=/dev/null
    source "${adapter_path}"
    for operation in \
        metadata \
        verify_runtime \
        detect_capabilities \
        prepare_config \
        build_command \
        materialize_skills \
        stream_events \
        normalize_result \
        terminate \
        run
    do
        declare -F "adapter_${operation}" >/dev/null 2>&1 || {
            echo "Harness Adapter is missing required operation: ${operation}" >&2
            return 1
        }
    done
    local metadata
    metadata="$(adapter_metadata)" || return 1
    resolved_adapter_version="$(printf '%s' "${metadata}" | jq -er '.adapter_version')" || return 1
    frozen_adapter_version="${CODIFY_ADAPTER_VERSION:-}"
    if [ -n "${frozen_adapter_version}" ] \
        && [ "${frozen_adapter_version}" != "${resolved_adapter_version}" ]; then
        echo "Frozen Adapter version does not match Runtime Bundle metadata" >&2
        return 1
    fi
    CODIFY_ADAPTER_VERSION="${resolved_adapter_version}"
    CODIFY_CLI_VERSION="${CODIFY_CLI_VERSION:-unknown}"
    export CODIFY_HARNESS_KEY CODIFY_ADAPTER_VERSION
    export CODIFY_CLI_VERSION
    adapter_verify_runtime || return 1
    capabilities="$(adapter_detect_capabilities)" || return 1
    printf '%s' "${capabilities}" | jq -e 'type == "object"' >/dev/null || {
        echo "Harness Adapter capabilities must be a JSON object" >&2
        return 1
    }
    CODIFY_HARNESS_CAPABILITIES="${capabilities}"
    export CODIFY_HARNESS_CAPABILITIES
    adapter_prepare_config || return 1
    adapter_materialize_skills || return 1
    command_path="$(adapter_build_command)" || return 1
    case "${command_path}" in
        /*) ;;
        *) echo "Harness Adapter command must be an absolute path" >&2; return 1 ;;
    esac
    [ -x "${command_path}" ] || {
        echo "Harness Adapter command is unavailable: ${command_path}" >&2
        return 1
    }
    CODIFY_HARNESS_COMMAND="${command_path}"
    export CODIFY_HARNESS_COMMAND
    local event_bytes
    event_bytes=$(wc -c < "${CODIFY_RUNTIME_DIR}/event.jsonl" 2>/dev/null || printf 'unreadable')
    echo "Canonical event stream before initialization: ${event_bytes} bytes"
    if [ ! -s "${CODIFY_RUNTIME_DIR}/event.jsonl" ]; then
        # A fresh container can inherit no canonical events. Reset only the
        # advisory writer lock in that case; a recovered live container keeps
        # its stream intact (seq is derived from the stream, not a side file).
        rm -f "${CODIFY_RUNTIME_DIR}/.event.lock"
        if [ -n "${CODIFY_HARNESS_SANDBOX_MODE:-}" ]; then
            codify_emit_event "run.started" \
                "$(jq -nc --arg runtime_bundle_digest "${CODIFY_RUNTIME_BUNDLE_DIGEST:-}" --arg sandbox_mode "${CODIFY_HARNESS_SANDBOX_MODE:-}" '{runtime_bundle_digest:$runtime_bundle_digest, sandbox_mode:$sandbox_mode}')" \
                || return 1
        else
            codify_emit_event "run.started" \
                "$(jq -nc --arg runtime_bundle_digest "${CODIFY_RUNTIME_BUNDLE_DIGEST:-}" '{runtime_bundle_digest:$runtime_bundle_digest}')" \
                || return 1
        fi
        echo "Canonical attempt initialized: ${CODIFY_ATTEMPT_ID}"
    fi
    CODIFY_HARNESS_INITIALIZED=1
}

codify_harness_capability_enabled() {
    local capability="$1"
    [ -n "${CODIFY_HARNESS_CAPABILITIES:-}" ] \
        && printf '%s' "${CODIFY_HARNESS_CAPABILITIES}" \
            | jq -e --arg capability "${capability}" '.[$capability] == true' >/dev/null
}

codify_harness_run() {
    local prompt_file="$1"
    local result_file="$2"
    local errexit_enabled=0
    case "$-" in
        *e*) errexit_enabled=1 ;;
    esac
    if ! codify_harness_initialize; then
        CODIFY_HARNESS_KEY="${CODIFY_HARNESS_KEY:-unknown}"
        CODIFY_ADAPTER_VERSION="${CODIFY_ADAPTER_VERSION:-unknown}"
        CODIFY_CLI_VERSION="${CODIFY_CLI_VERSION:-unknown}"
        export CODIFY_HARNESS_KEY CODIFY_ADAPTER_VERSION CODIFY_CLI_VERSION
        if ! codify_event_type_exists "run.started"; then
            if ! codify_emit_event "run.started" \
                "$(jq -nc --arg runtime_bundle_digest "${CODIFY_RUNTIME_BUNDLE_DIGEST:-}" '{runtime_bundle_digest:$runtime_bundle_digest}')"; then
                echo "Could not initialize canonical attempt" >&2
                CODIFY_HARNESS_TERMINAL_SEEN=1
                return 1
            fi
        fi
        if ! codify_event_type_exists "harness.completed" \
            && ! codify_event_type_exists "harness.failed"; then
            codify_emit_event "harness.failed" \
                '{"failure":{"kind":"configuration_error","message":"Harness Adapter initialization failed"}}'
        fi
        CODIFY_HARNESS_TERMINAL_SEEN=1
        return 1
    fi
    set +e
    # Run the adapter as a background job and wait on it so the SIGTERM trap
    # interrupts immediately. A foreground child would otherwise defer the trap
    # until the CLI exits, letting `docker stop` escalate to SIGKILL before the
    # finalizer can emit a cancelled terminal.
    adapter_run "${prompt_file}" "${result_file}" &
    CODIFY_HARNESS_ADAPTER_PID=$!
    export CODIFY_HARNESS_ADAPTER_PID
    local adapter_pid="${CODIFY_HARNESS_ADAPTER_PID}"
    wait "${adapter_pid}"
    local result=$?
    CODIFY_HARNESS_ADAPTER_PID=""
    export CODIFY_HARNESS_ADAPTER_PID
    adapter_normalize_result "${result_file}"
    local normalize_result=$?
    if [ "${errexit_enabled}" -eq 1 ]; then
        set -e
    else
        set +e
    fi
    if [ "${normalize_result}" -ne 0 ]; then
        if ! codify_event_type_exists "harness.completed" \
            && ! codify_event_type_exists "harness.failed"; then
            local normalization_failure_kind="protocol_error"
            case "${result}" in
                124) normalization_failure_kind="timeout" ;;
                130 | 137 | 143) normalization_failure_kind="cancelled" ;;
            esac
            # The Adapter's legacy result carries the CLI error text when it
            # aborted before producing a canonical result. Preserve it instead
            # of reporting a generic normalization failure.
            local adapter_failure_message
            adapter_failure_message=$(jq -r \
                'select(.success == false) | .result // empty' \
                "${result_file}" 2>/dev/null | tail -n 1)
            adapter_failure_message="${adapter_failure_message:0:2000}"
            codify_emit_event "harness.failed" \
                "$(jq -nc \
                    --arg kind "${normalization_failure_kind}" \
                    --arg message "${adapter_failure_message:-Harness result normalization failed}" \
                    '{failure:{kind:$kind,message:$message}}')"
        fi
        result=1
    fi
    if codify_event_type_exists "harness.completed" || codify_event_type_exists "harness.failed"; then
        CODIFY_HARNESS_TERMINAL_SEEN=1
    else
        codify_emit_event "harness.failed" \
            "$(jq -nc --argjson exit_code "${result}" '{failure:{kind:"protocol_error",message:"Harness stream ended without result",exit_code:$exit_code}}')"
        CODIFY_HARNESS_TERMINAL_SEEN=1
    fi
    # A Harness process can exit cleanly after reporting a provider or runtime
    # failure (Pi's owner deliberately uses a clean exit for a settled turn).
    # The canonical terminal event is authoritative for the worker boundary;
    # never let a zero process exit enter delivery after `harness.failed`.
    if [ "${result}" -eq 0 ] && codify_event_type_exists "harness.failed"; then
        result=1
    fi
    return "${result}"
}

codify_harness_run_text() {
    if ! codify_harness_capability_enabled "run_text" \
        || ! declare -F adapter_run_text >/dev/null 2>&1; then
        echo "Harness Adapter does not support run_text" >&2
        return 1
    fi
    adapter_run_text "$@"
}
