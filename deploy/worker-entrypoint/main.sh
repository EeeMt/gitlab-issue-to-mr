# Execute the selected harness, validate delivery, commit/push changes, and persist metadata.

# Freeze and validate the Adapter/capability view before any Harness-specific
# optional tooling is prepared. codify_harness_run reuses this initialization.
if ! codify_harness_initialize; then
    set +e
    codify_harness_run "${CODIFY_HARNESS_PROMPT_FILE}" "${CODIFY_HARNESS_OUTPUT_FILE}"
    HARNESS_INITIALIZATION_RESULT=$?
    set -e
    exit "${HARNESS_INITIALIZATION_RESULT}"
fi

# Fix the repository start point (S = local task-branch HEAD, R0 = confirmed
# remote work-branch HEAD at preparation, B0 = confirmed base HEAD) before any
# pre-script or harness code can move the workspace. Delivery attribution and
# safe publishing depend on these immutable pins.
if ! repo_pin_delivery_start; then
    echo "ERROR: Could not pin the repository start commit for delivery attribution"
    exit 1
fi

run_worker_script "pre" "${CODIFY_WORKER_PRE_SCRIPT_FILE}"

prepare_codegraph

echo "CodeGraph CLI version: $(codegraph --version 2>/dev/null || echo unavailable)"
echo "Harness: ${CODIFY_HARNESS_KEY:-claude}"
echo "Updating MR with execution status..."
update_mr_description "$(build_running_mr_description)" || true

echo "Starting Harness Adapter (streaming mode)..."
set +e
codify_harness_run "${CODIFY_HARNESS_PROMPT_FILE}" "${CODIFY_HARNESS_OUTPUT_FILE}"
SCRIPT_RESULT=$?
set -e
echo "Harness exited with code: ${SCRIPT_RESULT}"

RESULT=${SCRIPT_RESULT}

# Always emit structured tool calls if the JSON file exists, even on failure.
# This lets the frontend show a timeline of what was attempted before the failure.
if [ -f "${CODIFY_HARNESS_OUTPUT_FILE}" ] && [ -s "${CODIFY_HARNESS_OUTPUT_FILE}" ]; then
    SUMMARY_CONTENT=$(jq -r '.result // ""' "${CODIFY_HARNESS_OUTPUT_FILE}" 2>/dev/null || true)
    if [ ${#SUMMARY_CONTENT} -gt 45000 ]; then
        SUMMARY_CONTENT="${SUMMARY_CONTENT:0:45000}"
    fi
    FINAL_SUMMARY_CONTENT="$(sanitize_summary_content "${SUMMARY_CONTENT}")"

fi

if [ $RESULT -ne 0 ]; then
    echo "Harness execution failed with exit code: ${RESULT}"
    exit $RESULT
fi

codify_harness_mark_delivery_started

run_worker_script "post" "${CODIFY_WORKER_POST_SCRIPT_FILE}"

FINAL_SUMMARY_CONTENT="$(prepare_delivery_summary "${FINAL_SUMMARY_CONTENT}")"
write_delivery_summary_artifacts "${FINAL_SUMMARY_CONTENT}"

# Plan mode: discard any accidental workspace changes and exit successfully
if [ "${TASK_MODE}" = "plan" ]; then
    echo "Plan mode: discarding any workspace changes..."
    codify_run_shell 'cd /workspace && git checkout -- .' 2>/dev/null || true
    codify_run_shell 'cd /workspace && git clean -fd' 2>/dev/null || true
    write_plan_task_metadata "${FINAL_SUMMARY_CONTENT}"
    echo "========================================"
    echo "Plan task completed successfully!"
    echo "========================================"
    exit 0
fi

# ---------------------------------------------------------------------------
# Unified Git delivery. Every successful task converges on the same sequence:
#   cleanup -> worker commit (only when a real staged diff exists) -> collect
#   local facts S..H + inherited pending commits -> publish H as a verified
#   fast-forward -> generate the MR summary -> persist metadata.
# Harness-made commits are never re-committed, squashed or amended.
# ---------------------------------------------------------------------------

repo_commit_remaining_workspace_changes() {
    # Stages and commits the leftover workspace changes with a model-generated
    # message. Returns 0 when nothing needed committing.
    if codify_run_shell 'cd /workspace && git diff --cached --quiet'; then
        echo "No staged changes; skipping the worker commit"
        return 0
    fi

    echo "Changes detected, committing..."

    # Calculate change statistics from staged changes for the commit message.
    echo "Calculating change statistics..."
    DIFF_STATS=$(codify_run_shell 'cd /workspace && git diff --cached --stat' || echo "0 files changed")
    echo "Diff stats: ${DIFF_STATS}"

    # Parse additions, deletions from git diff --stat output
    # Format: " X files changed, Y insertions(+), Z deletions(-)"
    # or: " X files changed, Y insertions(+), Z deletions(-), N files unresolved"
    ADDITIONS=0
    DELETIONS=0

    # Extract insertions (additions)
    INS_LINE=$(echo "${DIFF_STATS}" | grep -o '[0-9]\+ insertion' || echo "0 insertion")
    ADDITIONS=$(echo "${INS_LINE}" | grep -o '[0-9]\+' || echo "0")

    # Extract deletions
    DEL_LINE=$(echo "${DIFF_STATS}" | grep -o '[0-9]\+ deletion' || echo "0 deletion")
    DELETIONS=$(echo "${DEL_LINE}" | grep -o '[0-9]\+' || echo "0")

    # Calculate total changes
    TOTAL_CHANGES=$((ADDITIONS + DELETIONS))

    echo "Changes: +${ADDITIONS} -${DELETIONS} (${TOTAL_CHANGES} total)"

    # Collect changed file lists from the staged diff before committing.
    # These feed only the worker commit-message prompt; the authoritative task
    # statistics come from the net S..H diff collected afterwards.
    NEW_FILES=""
    MODIFIED_FILES=""
    DELETED_FILES=""
    STAGED_NAME_STATUS=$(codify_run_shell 'cd /workspace && git diff --cached --name-status --no-renames' || true)
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        status=$(printf '%s' "$line" | awk '{print $1}')
        filepath=$(printf '%s' "$line" | cut -f2-)
        case "$status" in
            A) NEW_FILES="${NEW_FILES}${filepath}," ;;
            M) MODIFIED_FILES="${MODIFIED_FILES}${filepath}," ;;
            D) DELETED_FILES="${DELETED_FILES}${filepath}," ;;
        esac
    done <<< "${STAGED_NAME_STATUS}"

    # Remove trailing commas.
    # NOTE: files with commas in their names will be split incorrectly here;
    # this only affects the model prompt text, never the task statistics.
    NEW_FILES="${NEW_FILES%,}"
    MODIFIED_FILES="${MODIFIED_FILES%,}"
    DELETED_FILES="${DELETED_FILES%,}"

    CHANGED_FILES_TEXT="新增: ${NEW_FILES:-无}
修改: ${MODIFIED_FILES:-无}
删除: ${DELETED_FILES:-无}"

    COMMIT_DIFF_STATS=$(codify_run_shell 'cd /workspace && git diff --cached --stat' || echo "0 files changed")
    echo "Generating commit message with the harness model..."
    COMMIT_MESSAGE_PROMPT=$(build_commit_message_prompt "${CHANGED_FILES_TEXT}" "${COMMIT_DIFF_STATS}" "${FINAL_SUMMARY_CONTENT}")
    printf '%s\n' "${COMMIT_MESSAGE_PROMPT}" > /tmp/commit_message_prompt.txt
    chmod 644 /tmp/commit_message_prompt.txt
    codify_chown /tmp/commit_message_prompt.txt
    echo "Commit message prompt written to /tmp/commit_message_prompt.txt"

    set +e
    GENERATED_COMMIT_MESSAGE=$(codify_harness_run_text /tmp/commit_message_prompt.txt 60 2>/dev/null)
    COMMIT_MESSAGE_RESULT=$?
    set -e

    if [ ${COMMIT_MESSAGE_RESULT} -eq 0 ]; then
        echo "Harness commit message generation succeeded"
        echo "Harness raw commit message response:"
        printf '%s\n' "${GENERATED_COMMIT_MESSAGE}" | sed 's/^/  /'
        FINAL_COMMIT_MESSAGE=$(normalize_model_commit_message "${GENERATED_COMMIT_MESSAGE}")
    else
        echo "Harness commit message generation failed with exit code ${COMMIT_MESSAGE_RESULT}; using fallback"
    fi

    if [ -z "${FINAL_COMMIT_MESSAGE}" ]; then
        echo "Generated commit message was empty after normalization; using fallback"
        FINAL_COMMIT_MESSAGE="chore: 更新 ${BRANCH_NAME} 分支实现

- 完成用户请求对应的代码修改
- 同步更新相关文件与验证结果

AI-Generated: true"
    fi

    if ! printf '%s\n' "${FINAL_COMMIT_MESSAGE}" | grep -q '^AI-Generated: true$'; then
        FINAL_COMMIT_MESSAGE="${FINAL_COMMIT_MESSAGE}

AI-Generated: true"
    fi

    {
        printf '%s\n' "${FINAL_COMMIT_MESSAGE}"
        printf '\nCo-authored-by: %s <%s>\n' "${CODIFY_COAUTHOR_NAME_VALUE}" "${CODIFY_COAUTHOR_EMAIL_VALUE}"
    } > /tmp/commit_message.txt
    echo "Commit message written to /tmp/commit_message.txt"
    echo "Final commit message:"
    sed 's/^/  /' /tmp/commit_message.txt

    # Create commit
    GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME_VALUE}" \
    GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL_VALUE}" \
    codify_run_shell 'cd /workspace && git commit -F /tmp/commit_message.txt'

    echo "Worker commit created: $(codify_run_shell 'cd /workspace && git rev-parse HEAD')"
    return 0
}

repo_delivery_generate_overall_summary() {
    # Task/MR summary generation covers the whole task result (full commit list
    # and the net S..H diff), not just the worker's last commit message.
    echo "Generating overall MR summary with the harness model..."
    PREVIOUS_SUMMARY_FILE="${CODIFY_RUNTIME_DIR}/previous-task-summaries.md"
    if [ -f "${PREVIOUS_SUMMARY_FILE}" ]; then
        PREVIOUS_SUMMARY_BYTES=$(wc -c < "${PREVIOUS_SUMMARY_FILE}" | tr -d ' ')
        echo "Previous task summaries found: ${PREVIOUS_SUMMARY_FILE} (${PREVIOUS_SUMMARY_BYTES} bytes)"
    else
        echo "Previous task summaries not found at ${PREVIOUS_SUMMARY_FILE}; using empty history"
    fi

    local commit_list_text diff_stats_text head_subject
    commit_list_text=$(jq -r \
        '.git_delivery.commits[]? | "- `" + .sha[0:8] + "` " + .subject' \
        "${GIT_DELIVERY_SNAPSHOT_FILE}" 2>/dev/null || true)
    diff_stats_text=$(jq -r \
        '"+" + ((.git_delivery.diff // {}).additions // 0 | tostring) + " -" + ((.git_delivery.diff // {}).deletions // 0 | tostring)' \
        "${GIT_DELIVERY_SNAPSHOT_FILE}" 2>/dev/null || true)
    head_subject=$(codify_run_shell 'cd /workspace && git log -1 --format=%s' 2>/dev/null || true)

    OVERALL_SUMMARY_PROMPT=$(build_overall_summary_prompt \
        "${PREVIOUS_SUMMARY_FILE}" \
        "${FINAL_SUMMARY_CONTENT}" \
        "${FINAL_COMMIT_MESSAGE:-${head_subject:-}}" \
        "${commit_list_text:-无}" \
        "${diff_stats_text:-无}" \
        "${USER_PROMPT}")
    printf '%s\n' "${OVERALL_SUMMARY_PROMPT}" > /tmp/overall_summary_prompt.txt
    chmod 644 /tmp/overall_summary_prompt.txt
    codify_chown /tmp/overall_summary_prompt.txt
    echo "Overall summary prompt written to /tmp/overall_summary_prompt.txt (${#OVERALL_SUMMARY_PROMPT} chars)"

    set +e
    GENERATED_OVERALL_SUMMARY=$(codify_harness_run_text /tmp/overall_summary_prompt.txt 60 2>/dev/null)
    OVERALL_SUMMARY_RESULT=$?
    set -e

    if [ ${OVERALL_SUMMARY_RESULT} -eq 0 ]; then
        echo "Harness overall summary generation succeeded"
        FINAL_OVERALL_SUMMARY=$(normalize_model_overall_summary "${GENERATED_OVERALL_SUMMARY}")
        if [ -n "${FINAL_OVERALL_SUMMARY}" ]; then
            echo "Overall MR summary generated (${#FINAL_OVERALL_SUMMARY} chars)"
        else
            echo "Harness overall summary normalized to empty; keeping previous MR summary"
        fi
    else
        echo "Harness overall summary generation failed with exit code ${OVERALL_SUMMARY_RESULT}; keeping previous MR summary"
    fi
    return 0
}

# Python-based validation commonly leaves untracked bytecode beside the source
# files. It is a runtime artifact, not task delivery; remove only untracked
# cache files before calculating and staging the workspace diff.
codify_run_shell 'cd /workspace && git clean -fd -- "**/__pycache__" "**/*.pyc" "**/*.pyo"' || true

# Remove result.md if it exists from prior runs
rm -f /workspace/result.md
codify_run_shell 'cd /workspace && git rm -f result.md' 2>/dev/null || true

# Stage all remaining workspace changes; the worker commit below is skipped
# when the stage stays empty so a clean tree never produces an empty commit.
codify_run_shell 'cd /workspace && git add -A'

WORKSPACE_STATUS=$(codify_run_shell 'cd /workspace && git status --porcelain' || true)
if [ -n "$WORKSPACE_STATUS" ]; then
    echo "Changes detected:"
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        status=$(printf '%s' "$line" | cut -c1-2)
        filepath=$(printf '%s' "$line" | cut -c4-)
        case "$status" in
            "??") echo "  [new] ${filepath}" ;;
            " M"|"M "|"MM") echo "  [modified] ${filepath}" ;;
            " D"|"D ") echo "  [deleted] ${filepath}" ;;
            "A "|" A") echo "  [added] ${filepath}" ;;
            "R "|" R") echo "  [renamed] ${filepath}" ;;
            *) echo "  [${status}] ${filepath}" ;;
        esac
    done <<< "${WORKSPACE_STATUS}"
fi

if ! repo_commit_remaining_workspace_changes; then
    echo "ERROR: Could not commit the remaining workspace changes"
    exit 1
fi

# Collect local facts into the delivery snapshot: this task's commits S..H,
# inherited pending commits and the net diff. The snapshot is written once and
# only ever updated by record_push, so metadata and canonical events agree.
if ! repo_delivery_collect; then
    echo "ERROR: Could not collect Git delivery facts; refusing to declare a delivery result"
    exit 1
fi

DELIVERY_COLLECT_ERROR=$(jq -r '.error.code // empty' "${GIT_DELIVERY_SNAPSHOT_FILE}" 2>/dev/null || true)
if [ -n "${DELIVERY_COLLECT_ERROR}" ]; then
    DELIVERY_COLLECT_MESSAGE=$(jq -r '.error.message // "Delivery facts could not be collected"' "${GIT_DELIVERY_SNAPSHOT_FILE}")
    echo "ERROR: ${DELIVERY_COLLECT_MESSAGE}"
    repo_delivery_record "failed" "" "${DELIVERY_COLLECT_ERROR}" "${DELIVERY_COLLECT_MESSAGE}" || true
    repo_delivery_write_metadata || true
    exit 1
fi

if repo_delivery_has_content; then
    if repo_delivery_publish; then
        # The model-generated MR summary runs only for genuinely new commits;
        # recovered-only deliveries keep the previous overall summary.
        if repo_delivery_commits_present; then
            repo_delivery_generate_overall_summary || true
        fi
        repo_delivery_write_metadata || true
        echo "========================================"
        echo "Task completed successfully!"
        echo "========================================"
        exit 0
    fi
    repo_delivery_write_metadata || true
    echo "ERROR: Code delivery was not confirmed; the task ends failed with the local commits preserved"
    exit 1
fi

echo "No changes made by Harness"
# No delivery content: no remote query, no publish.
repo_delivery_record "not_needed" || true
if [ "${REQUIRE_CHANGES:-true}" = "false" ]; then
    echo "require_changes disabled: task completed without code changes"
    repo_delivery_write_metadata || true
    echo "========================================"
    echo "Task completed successfully!"
    echo "========================================"
    exit 0
fi
repo_delivery_write_metadata || true
echo "ERROR: No changes were delivered and require_changes is enabled"
exit 1
