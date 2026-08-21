#!/bin/bash

CODIFY_ORCHESTRATION_DIR="${CODIFY_ORCHESTRATION_DIR:-${ENTRYPOINT_LIB_DIR%/worker-entrypoint}}"
CODIFY_CANONICAL_EVENT_WRITER="${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/events.py"
CODIFY_HARNESS_RESULT_FILE="${CODIFY_RUNTIME_DIR}/harness-result.json"
CODIFY_HARNESS_RAW_DIR="${CODIFY_RUNTIME_DIR}/harness-events"
CODIFY_DELIVERY_STARTED=0
CODIFY_HARNESS_TERMINAL_SEEN=0
CODIFY_HARNESS_INITIALIZED=0
export CODIFY_ORCHESTRATION_DIR CODIFY_CANONICAL_EVENT_WRITER CODIFY_HARNESS_RESULT_FILE

codify_emit_event() {
    local event_type="$1"
    local payload="${2-}"
    if [ -z "${payload}" ]; then
        payload="{}"
    fi
    python3 "${CODIFY_CANONICAL_EVENT_WRITER}" "${event_type}" --payload "${payload}" >/dev/null
}

codify_event_type_exists() {
    local event_type="$1"
    [ -s "${CODIFY_RUNTIME_DIR}/event.jsonl" ] \
        && jq -e --arg type "${event_type}" 'select(.type == $type)' \
            "${CODIFY_RUNTIME_DIR}/event.jsonl" >/dev/null 2>&1
}

codify_harness_last_failure_message() {
    jq -r \
        'select(.type == "harness.failed") | .payload.failure.message // empty' \
        "${CODIFY_RUNTIME_DIR}/event.jsonl" 2>/dev/null | tail -n 1
}

codify_harness_mark_delivery_started() {
    if [ "${CODIFY_DELIVERY_STARTED}" -eq 0 ]; then
        codify_emit_event "delivery.started" '{"phase":"git"}'
        CODIFY_DELIVERY_STARTED=1
    fi
}

codify_harness_ensure_result() {
    local exit_code="${1:-1}"
    local result_schema="codify.worker.result/v1"
    if [ "${CODIFY_RUNTIME_CONTRACT_VERSION:-}" = "codify.worker.harness/v2" ]; then
        result_schema="codify.worker.result/v2"
    fi
    if [ -s "${CODIFY_HARNESS_RESULT_FILE}" ] \
        && jq -e --arg schema "${result_schema}" '.schema == $schema' \
            "${CODIFY_HARNESS_RESULT_FILE}" >/dev/null 2>&1; then
        return 0
    fi
    local failure_kind="protocol_error"
    local result_status="protocol_error"
    local failure_message=""
    failure_kind=$(jq -r \
        'select(.type == "harness.failed") | .payload.failure.kind // empty' \
        "${CODIFY_RUNTIME_DIR}/event.jsonl" 2>/dev/null | tail -n 1)
    failure_kind="${failure_kind:-protocol_error}"
    failure_message="$(codify_harness_last_failure_message)"
    case "${failure_kind}" in
        cancelled) result_status="cancelled" ;;
        protocol_error) result_status="protocol_error" ;;
        *) result_status="failed" ;;
    esac
    if [ "${exit_code}" -eq 0 ] && codify_event_type_exists "harness.completed"; then
        jq -nc \
            --arg schema "${result_schema}" \
            --arg harness_key "${CODIFY_HARNESS_KEY}" \
            --arg adapter_version "${CODIFY_ADAPTER_VERSION}" \
            --arg cli_version "${CODIFY_CLI_VERSION}" \
            '{schema:$schema,status:"completed",success:true,result:"",harness_key:$harness_key,adapter_version:$adapter_version,cli_version:$cli_version,session_id:null,model:null,usage:{input_tokens:null,cached_input_tokens:null,output_tokens:null,reasoning_tokens:null,cost:null,currency:null,engine_fields:{}},failure:null,capability_warnings:[]}' \
            > "${CODIFY_HARNESS_RESULT_FILE}.tmp"
    else
        jq -nc \
            --arg schema "${result_schema}" \
            --arg status "${result_status}" \
            --arg kind "${failure_kind}" \
            --argjson exit_code "${exit_code}" \
            --arg message "${failure_message}" \
            --arg harness_key "${CODIFY_HARNESS_KEY}" \
            --arg adapter_version "${CODIFY_ADAPTER_VERSION}" \
            --arg cli_version "${CODIFY_CLI_VERSION}" \
            '{schema:$schema,status:$status,success:false,result:"",harness_key:$harness_key,adapter_version:$adapter_version,cli_version:$cli_version,session_id:null,model:null,usage:{input_tokens:null,cached_input_tokens:null,output_tokens:null,reasoning_tokens:null,cost:null,currency:null,engine_fields:{}},failure:{kind:$kind,exit_code:$exit_code,message:$message},capability_warnings:[]} | del(.failure.message | select(. == ""))' \
            > "${CODIFY_HARNESS_RESULT_FILE}.tmp"
    fi
    mv "${CODIFY_HARNESS_RESULT_FILE}.tmp" "${CODIFY_HARNESS_RESULT_FILE}"
}

codify_harness_finalize_attempt() {
    local exit_code="${1:-1}"
    local delivery_payload finalization_payload terminal_payload
    if ! codify_event_type_exists "run.started"; then
        echo "Canonical attempt has no run.started event; refusing terminal synthesis" >&2
        codify_harness_ensure_result "${exit_code}"
        return 1
    fi
    if [ "${CODIFY_HARNESS_TERMINAL_SEEN}" -eq 0 ]; then
        if codify_event_type_exists "harness.completed" || codify_event_type_exists "harness.failed"; then
            CODIFY_HARNESS_TERMINAL_SEEN=1
        elif [ "${CODIFY_CANCELLED:-0}" -eq 1 ]; then
            codify_emit_event "harness.failed" \
                '{"failure":{"kind":"cancelled","message":"Cancelled by user"}}'
            CODIFY_HARNESS_TERMINAL_SEEN=1
        else
            codify_emit_event "harness.failed" \
                '{"failure":{"kind":"protocol_error","message":"Harness exited without a terminal event"}}'
            CODIFY_HARNESS_TERMINAL_SEEN=1
        fi
    fi
    codify_harness_ensure_result "${exit_code}"

    if [ "${CODIFY_DELIVERY_STARTED}" -eq 1 ]; then
        delivery_payload=$(jq -nc \
            --argjson exit_code "${exit_code}" \
            --arg commit_sha "${COMMIT_SHA:-}" \
            '{exit_code:$exit_code,commit_sha:(if $commit_sha == "" then null else $commit_sha end)}')
        if [ "${exit_code}" -eq 0 ]; then
            codify_emit_event "delivery.completed" "${delivery_payload}"
        else
            codify_emit_event "delivery.failed" "${delivery_payload}"
        fi
    fi

    finalization_payload=$(jq -nc \
        --argjson exit_code "${exit_code}" \
        --arg commit_sha "${COMMIT_SHA:-}" \
        --arg commit_message "${FINAL_COMMIT_MESSAGE:-}" \
        --argjson additions "${ADDITIONS:-0}" \
        --argjson deletions "${DELETIONS:-0}" \
        --argjson total "${TOTAL_CHANGES:-0}" \
        '{exit_code:$exit_code,commit_sha:(if $commit_sha == "" then null else $commit_sha end),commit_message:$commit_message,diff:{additions:$additions,deletions:$deletions,total:$total}}')
    codify_emit_event "worker.finalization" "${finalization_payload}"

    if [ "${exit_code}" -eq 0 ] \
        && [ "${CODIFY_CANCELLED:-0}" -ne 1 ] \
        && codify_event_type_exists "harness.completed"; then
        terminal_payload=$(jq -nc --arg status completed '{status:$status,success:true}')
        codify_emit_event "run.completed" "${terminal_payload}"
    else
        local failure_kind=""
        local task_status=""
        local failure_message=""
        # Preserve the Adapter's normalized failure taxonomy. Process-level
        # timeout/cancellation remains authoritative because the Harness may
        # have been terminated before it could emit a trustworthy result.
        failure_kind=$(jq -r \
            'select(.type == "harness.failed") | .payload.failure.kind // empty' \
            "${CODIFY_RUNTIME_DIR}/event.jsonl" 2>/dev/null | tail -n 1)
        case "${exit_code}" in
            124) failure_kind="timeout" ;;
            130 | 137 | 143) failure_kind="cancelled" ;;
        esac
        if [ "${CODIFY_CANCELLED:-0}" -eq 1 ]; then
            failure_kind="cancelled"
        fi
        failure_kind="${failure_kind:-engine_error}"
        case "${failure_kind}" in
            cancelled) task_status="cancelled" ;;
            protocol_error) task_status="protocol_error" ;;
            *) task_status="failed" ;;
        esac
        failure_message="$(codify_harness_last_failure_message)"
        terminal_payload=$(jq -nc \
            --argjson exit_code "${exit_code}" \
            --arg kind "${failure_kind}" \
            --arg status "${task_status}" \
            --arg message "${failure_message}" \
            '{status:$status,success:false,failure:{kind:$kind,exit_code:$exit_code,message:$message}} | del(.failure.message | select(. == ""))')
        codify_emit_event "run.failed" "${terminal_payload}"
    fi
}
