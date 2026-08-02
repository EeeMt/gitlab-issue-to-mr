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

append_runtime_event() {
    local event_json="$1"
    if [ -z "${event_json}" ] || [ ! -d "${CODIFY_RUNTIME_DIR}" ]; then
        return 0
    fi
    local event_file="${CODIFY_RUNTIME_DIR}/event.jsonl"
    # The first writer (root orchestrator or the model identity) creates the
    # shared canonical stream. Make it world-writable so every runtime identity
    # can append.
    if [ ! -e "${event_file}" ]; then
        : > "${event_file}" 2>/dev/null || return 0
        chmod 666 "${event_file}" 2>/dev/null || true
    fi
    # The kernel can deny the open even when mode bits allow it: a sticky
    # world-writable dir with fs.protected_regular refuses cross-uid appends,
    # and that check also applies to root. Never fail the caller or print the
    # shell's redirection error; on a denied append fall back to a per-uid
    # sidecar the runtime archive still collects.
    if ! ( printf '%s\n' "${event_json}" >> "${event_file}" ) 2>/dev/null; then
        printf '%s\n' "${event_json}" \
            >> "${CODIFY_RUNTIME_DIR}/event.$(id -u 2>/dev/null || printf unknown).jsonl" \
            2>/dev/null || true
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
