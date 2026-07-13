# Runtime exports, custom hooks, events, and archive lifecycle.

export ANTHROPIC_BASE_URL
export ANTHROPIC_API_KEY
export ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN:-${ANTHROPIC_API_KEY}}"
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="${CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC:-1}"
export SANDBOX_MODE=1
export CLAUDE_MAX_TURNS="${CLAUDE_MAX_TURNS:-20}"
export CLAUDE_MODEL="${ANTHROPIC_MODEL}"
export APPEND_SYSTEM_PROMPT
FINAL_SUMMARY_CONTENT=""
FINAL_CHANGED_FILES_TEXT=""
FINAL_COMMIT_MESSAGE=""
FINAL_OVERALL_SUMMARY=""
RUNTIME_ARCHIVE_CREATED=0

create_runtime_archive() {
    if [ "${RUNTIME_ARCHIVE_CREATED}" -eq 1 ]; then
        return 0
    fi

    local archive_name="task-${TASK_ID:-0}-runtime-archive.tar.gz"
    local archive_path="${CODIFY_RUNTIME_DIR}/${archive_name}"

    if [ -f "${CODIFY_RUNTIME_DIR}/event.jsonl" ] && [ -f "${CODIFY_RUNTIME_DIR}/runtime.json" ]; then
        local archive_files=(event.jsonl runtime.json console.log)
        [ -f "${DELIVERY_SUMMARY_FILE}" ] && archive_files+=(delivery-summary.md)
        [ -f "${DELIVERY_SUMMARY_VALIDATION_FILE}" ] && archive_files+=(delivery-summary-validation.json)
        tar -czf "${archive_path}" -C "${CODIFY_RUNTIME_DIR}" "${archive_files[@]}" 2>/dev/null || true
        echo "Archive created: ${archive_path}"
        RUNTIME_ARCHIVE_CREATED=1
    fi
}

append_runtime_event() {
    local event_json="$1"
    if [ -n "${event_json}" ] && [ -d "${CODIFY_RUNTIME_DIR}" ]; then
        printf '%s\n' "${event_json}" >> "${CODIFY_RUNTIME_DIR}/event.jsonl"
    fi
}

run_worker_script() {
    local phase="$1"
    local script_path="$2"

    if [ ! -s "${script_path}" ]; then
        return 0
    fi

    echo "Running custom ${phase} script..."

    set +e
    codify_run_shell "cd /workspace && export PATH=\"${CODIFY_RUNTIME_PATH}\" && \"${CODIFY_BASH}\" \"${script_path}\""
    local script_result=$?
    set -e

    if [ ${script_result} -ne 0 ]; then
        echo "Custom ${phase} script failed with exit code: ${script_result}"
        return ${script_result}
    fi

    echo "Custom ${phase} script completed successfully"
    return 0
}
