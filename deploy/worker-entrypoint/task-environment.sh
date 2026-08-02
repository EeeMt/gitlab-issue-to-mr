# Prepare the Harness-neutral prompt and issue-scoped shared state.

TASK_MODE="${TASK_MODE:-execute}"

if [ ! -f "${CODIFY_TASK_PROMPT_FILE}" ]; then
    echo "Task prompt file does not exist: ${CODIFY_TASK_PROMPT_FILE}" >&2
    exit 1
fi
if [ ! -s "${CODIFY_TASK_PROMPT_FILE}" ]; then
    echo "Task prompt file is empty: ${CODIFY_TASK_PROMPT_FILE}" >&2
    exit 1
fi
CODIFY_HARNESS_PROMPT_FILE="/tmp/codify-harness-prompt.txt"
CODIFY_HARNESS_OUTPUT_FILE="/tmp/codify-harness-output.json"
cp "${CODIFY_TASK_PROMPT_FILE}" "${CODIFY_HARNESS_PROMPT_FILE}"
chmod 644 "${CODIFY_HARNESS_PROMPT_FILE}"
codify_chown /workspace "${CODIFY_HARNESS_PROMPT_FILE}"
export CODIFY_HARNESS_PROMPT_FILE CODIFY_HARNESS_OUTPUT_FILE
# Ensure issue-scoped shared storage is writable by the codify user
if [ -d /opt/codify-issue-shared ]; then
    codify_chown /opt/codify-issue-shared
fi
