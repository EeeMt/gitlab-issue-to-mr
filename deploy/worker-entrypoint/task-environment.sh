# Prepare prompt and user-owned state required by the Claude process.

TASK_MODE="${TASK_MODE:-execute}"

if [ ! -f "${CODIFY_TASK_PROMPT_FILE}" ]; then
    echo "Task prompt file does not exist: ${CODIFY_TASK_PROMPT_FILE}" >&2
    exit 1
fi
if [ ! -s "${CODIFY_TASK_PROMPT_FILE}" ]; then
    echo "Task prompt file is empty: ${CODIFY_TASK_PROMPT_FILE}" >&2
    exit 1
fi
cp "${CODIFY_TASK_PROMPT_FILE}" /tmp/claude_prompt.txt

CLAUDE_SYSTEM_PROMPT_FILE="/tmp/claude_system_prompt.txt"
if [ -n "${APPEND_SYSTEM_PROMPT}" ]; then
    printf '%s' "${APPEND_SYSTEM_PROMPT}" > "${CLAUDE_SYSTEM_PROMPT_FILE}"
    chmod 600 "${CLAUDE_SYSTEM_PROMPT_FILE}"
    codify_chown "${CLAUDE_SYSTEM_PROMPT_FILE}"
    export APPEND_SYSTEM_PROMPT_FILE="${CLAUDE_SYSTEM_PROMPT_FILE}"
    unset APPEND_SYSTEM_PROMPT
fi

chmod 644 /tmp/claude_prompt.txt
codify_chown -R /workspace /tmp/claude_prompt.txt
# Ensure issue-scoped shared storage is writable by the codify user
if [ -d /opt/codify-issue-shared ]; then
    codify_chown /opt/codify-issue-shared
fi
# Ensure session storage directory is writable by the codify user
if [ -d /home/codify/.claude ]; then
    codify_chown -R /home/codify/.claude
fi

# Restore .claude.json if missing (volume mount persists backups but not the config file)
if [ ! -f /home/codify/.claude.json ]; then
    LATEST_BACKUP=$(ls -t /home/codify/.claude/backups/.claude.json.backup.* 2>/dev/null | head -1)
    if [ -n "$LATEST_BACKUP" ]; then
        echo "Restoring .claude.json from backup: $LATEST_BACKUP"
        cp "$LATEST_BACKUP" /home/codify/.claude.json
    else
        echo "Creating minimal .claude.json"
        echo '{}' > /home/codify/.claude.json
    fi
    codify_chown /home/codify/.claude.json
fi
