#!/usr/bin/env bash
# fake ci-claude.sh — Replaces real ci-claude.sh for integration testing.
#
# Creates predictable file changes in /workspace and outputs JSON result
# in the same format as the real ci-claude.sh.
#
# Environment variables:
#   FAKE_CLAUDE_EXIT_CODE  — Exit code (default: 0)
#   FAKE_CLAUDE_FILES      — JSON array of {path, content} to create (optional)
#   FAKE_CLAUDE_RESULT     — Result text (default: "Created hello.py")
#   FAKE_CLAUDE_FAIL_MSG   — Error message when exit code != 0

# Intentionally omitting -e: we always want to reach the jq output at the
# bottom and exit with $EXIT_CODE, even if intermediate commands fail.
set -uo pipefail

PROMPT="${1:-}"
EXIT_CODE="${FAKE_CLAUDE_EXIT_CODE:-0}"
RESULT_TEXT="${FAKE_CLAUDE_RESULT:-Created hello.py with greeting function}"
FAIL_MSG="${FAKE_CLAUDE_FAIL_MSG:-Task failed}"
DELAY_SECONDS=0
ARTIFACT_DIR="${ARTIFACT_DIR:-${PWD}}"
mkdir -p "${ARTIFACT_DIR}"
EVENT_JSONL="${ARTIFACT_DIR}/event.jsonl"
RUNTIME_JSON="${ARTIFACT_DIR}/runtime.json"
CONSOLE_LOG="${ARTIFACT_DIR}/console.log"
touch "${EVENT_JSONL}" "${CONSOLE_LOG}"
jq -n \
    --arg model "fake-claude-1.0" \
    --arg cwd "${PWD}" \
    '{model: $model, cwd: $cwd, resume_session: ""}' > "${RUNTIME_JSON}"

append_event() {
    printf '%s\n' "$1" >> "${EVENT_JSONL}"
}

# Fetch dynamic config from mock server — GITLAB_URL points to mock-services in test env.
# This allows tests to change behavior at runtime via PATCH /mock/config.
if command -v curl &>/dev/null && [[ -n "${GITLAB_URL:-}" ]]; then
    MOCK_CONFIG=$(curl -sf "${GITLAB_URL}/mock/config" 2>/dev/null || echo "{}")
    _MC_EXIT=$(echo "$MOCK_CONFIG" | jq -r '.claude_exit_code // empty' 2>/dev/null || true)
    _MC_DELAY=$(echo "$MOCK_CONFIG" | jq -r '.claude_delay_seconds // empty' 2>/dev/null || true)
    _MC_SKIP=$(echo "$MOCK_CONFIG" | jq -r '.claude_skip_files // empty' 2>/dev/null || true)
    [[ -n "$_MC_EXIT" ]] && EXIT_CODE="$_MC_EXIT"
    [[ -n "$_MC_DELAY" ]] && DELAY_SECONDS="$_MC_DELAY"
fi

SKIP_FILES="${_MC_SKIP:-false}"

echo "[fake-claude] Prompt: ${PROMPT}" >&2
echo "[fake-claude] Exit code will be: ${EXIT_CODE}, skip_files: ${SKIP_FILES}" >&2

# Optional delay — lets cancel tests catch the task in RUNNING state
if [[ "$DELAY_SECONDS" -gt 0 ]] 2>/dev/null; then
    echo "[fake-claude] Sleeping for ${DELAY_SECONDS}s (configurable via mock config)" >&2
    sleep "$DELAY_SECONDS"
fi

# Create file changes in workspace (unless skip_files is set)
if [[ "$SKIP_FILES" == "true" ]]; then
    echo "[fake-claude] Skipping file creation (claude_skip_files=true)" >&2
elif [[ -n "${FAKE_CLAUDE_FILES:-}" ]]; then
    echo "[fake-claude] Creating files from FAKE_CLAUDE_FILES" >&2
    echo "${FAKE_CLAUDE_FILES}" | jq -c '.[]' 2>/dev/null | while read -r entry; do
        fpath=$(echo "$entry" | jq -r '.path')
        content=$(echo "$entry" | jq -r '.content')
        mkdir -p "$(dirname "$fpath")"
        printf '%s' "$content" > "$fpath"
        git add "$fpath" 2>/dev/null || true
        echo "[fake-claude] Created: $fpath" >&2
    done
else
    # Default: create a simple hello.py (include TASK_ID for uniqueness
    # so consecutive runs on the same branch still produce changes)
    cat > hello.py << PYEOF
def hello():
    """Greeting function created by Codify."""
    return "Hello from Codify!"


# Task: ${TASK_ID:-unknown}, generated at $(date -u +%Y%m%d%H%M%S)
if __name__ == "__main__":
    print(hello())
PYEOF
    git add hello.py 2>/dev/null || true
    echo "[fake-claude] Created default: hello.py (task=${TASK_ID:-unknown})" >&2
fi

# Emit structured events to event.jsonl — mirrors what real Claude CLI produces.
# WorkerEventProjector tails this file and creates TaskLog entries.

# 1. System initialization
append_event '{"type":"system","subtype":"init","model":"fake-claude-1.0","cwd":"/workspace"}'

# 2. First thinking block
append_event '{"type":"stream_event","event":{"type":"content_block_start","content_block":{"type":"thinking"}}}'
append_event '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"Let me analyze the request. I need to create a Python file with a greeting function. I should make it well-structured with docstrings and a main guard."}}}'
append_event '{"type":"stream_event","event":{"type":"content_block_stop"}}'

# 3. First assistant text block
append_event '{"type":"stream_event","event":{"type":"content_block_start","content_block":{"type":"text"}}}'
append_event '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"I'\''ll create a hello.py file with a well-structured greeting function."}}}'
append_event '{"type":"stream_event","event":{"type":"content_block_stop"}}'

# 4. First tool call — Read existing files
append_event '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"tool_001","name":"Read","input":{"file_path":"README.md"}}]}}'
append_event '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"tool_001","content":"# Test Project\n\nThis is a test repository.","is_error":false}]}}'

# 5. Second thinking block
append_event '{"type":"stream_event","event":{"type":"content_block_start","content_block":{"type":"thinking"}}}'
append_event '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"The project has a README. I'\''ll create hello.py with proper structure and also add a utils.py for helper functions."}}}'
append_event '{"type":"stream_event","event":{"type":"content_block_stop"}}'

# 6. Second tool call — Write main file
append_event '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"tool_002","name":"Write","input":{"file_path":"hello.py","content":"def hello():\n    return \"Hello from Codify!\""}}]}}'
append_event '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"tool_002","content":"File created successfully","is_error":false}]}}'

# 7. Third tool call — Write second file
append_event '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"tool_003","name":"Write","input":{"file_path":"utils.py","content":"def greet(name):\n    return f\"Hello, {name}!\""}}]}}'
append_event '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"tool_003","content":"File created successfully","is_error":false}]}}'

# 8. Final assistant text
append_event '{"type":"stream_event","event":{"type":"content_block_start","content_block":{"type":"text"}}}'
append_event '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"I created two files:\n1. hello.py — main greeting function\n2. utils.py — helper greeting with name parameter"}}}'
append_event '{"type":"stream_event","event":{"type":"content_block_stop"}}'

# Build and output JSON result to stdout (entrypoint.sh captures this)
if [[ "$EXIT_CODE" == "0" ]]; then
    append_event '{"type":"result","subtype":"success","result":"Created hello.py with greeting function","session_id":"fake-session","usage":{"input_tokens":1500,"output_tokens":800,"cache_read_input_tokens":200,"cache_creation_input_tokens":100}}'
    jq -n \
        --argjson success true \
        --arg subtype "success" \
        --arg result "$RESULT_TEXT" \
        --arg session_id "fake-session-$(date +%s)" \
        '{
            success: $success,
            subtype: $subtype,
            result: $result,
            session_id: $session_id,
            usage: {input_tokens: 1500, output_tokens: 800, cache_read_input_tokens: 200, cache_creation_input_tokens: 100},
            tool_calls: [
                {name: "Read", input: {file_path: "README.md"}, output: "# Test Project", error: false},
                {name: "Write", input: {file_path: "hello.py", content: "..."}, output: "File created successfully", error: false},
                {name: "Write", input: {file_path: "utils.py", content: "..."}, output: "File created successfully", error: false}
            ]
        }'
else
    append_event '{"type":"result","subtype":"error","result":"Task failed","session_id":"","usage":{"input_tokens":500,"output_tokens":100}}'
    jq -n \
        --argjson success false \
        --arg subtype "error" \
        --arg result "$FAIL_MSG" \
        '{
            success: $success,
            subtype: $subtype,
            result: $result,
            session_id: "",
            usage: {input_tokens: 500, output_tokens: 100},
            tool_calls: []
        }'
fi

exit "$EXIT_CODE"
