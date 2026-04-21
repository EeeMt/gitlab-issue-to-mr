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

# Emit CODIFY markers to stderr — simulates a realistic multi-step AI interaction.
# worker.py parses these in real-time and creates TaskLog entries.

# 1. System initialization
echo 'CODIFY_SYSTEM_INIT:{"model":"fake-claude-1.0","cwd":"/workspace"}' >&2

# 2. First thinking block — AI analyzes the prompt
echo 'CODIFY_THINKING:{"text":"Let me analyze the request. I need to create a Python file with a greeting function. I should make it well-structured with docstrings and a main guard."}' >&2

# 3. First assistant text — AI explains its plan
echo 'CODIFY_ASSISTANT_TEXT:{"text":"I'"'"'ll create a hello.py file with a well-structured greeting function."}' >&2

# 4. First tool call — Read existing files to understand context
echo 'CODIFY_TOOL_USE_START:{"id":"tool_001","name":"Read","input":{"file_path":"README.md"}}' >&2
echo 'CODIFY_TOOL_RESULT:{"id":"tool_001","output":"# Test Project\n\nThis is a test repository.","error":false}' >&2

# 5. Second thinking block — AI decides on implementation
echo 'CODIFY_THINKING:{"text":"The project has a README. I'"'"'ll create hello.py with proper structure and also add a utils.py for helper functions."}' >&2

# 6. Second tool call — Write the main file
echo 'CODIFY_TOOL_USE_START:{"id":"tool_002","name":"Write","input":{"file_path":"hello.py","content":"def hello():\n    return \"Hello from Codify!\""}}' >&2
echo 'CODIFY_TOOL_RESULT:{"id":"tool_002","output":"File created successfully","error":false}' >&2

# 7. Third tool call — Write a second file
echo 'CODIFY_TOOL_USE_START:{"id":"tool_003","name":"Write","input":{"file_path":"utils.py","content":"def greet(name):\n    return f\"Hello, {name}!\""}}' >&2
echo 'CODIFY_TOOL_RESULT:{"id":"tool_003","output":"File created successfully","error":false}' >&2

# 8. Final assistant text — AI summarizes what it did
echo 'CODIFY_ASSISTANT_TEXT:{"text":"I created two files:\n1. hello.py — main greeting function\n2. utils.py — helper greeting with name parameter"}' >&2

# Build and output JSON result to stdout (entrypoint.sh captures this)
if [[ "$EXIT_CODE" == "0" ]]; then
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
