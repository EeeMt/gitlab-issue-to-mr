# Execute Claude, validate delivery, commit/push changes, and persist metadata.

# Freeze and validate the Adapter/capability view before any Harness-specific
# optional tooling is prepared. codify_harness_run reuses this initialization.
if ! codify_harness_initialize; then
    set +e
    codify_harness_run "${CODIFY_HARNESS_PROMPT_FILE}" "${CODIFY_HARNESS_OUTPUT_FILE}"
    HARNESS_INITIALIZATION_RESULT=$?
    set -e
    exit "${HARNESS_INITIALIZATION_RESULT}"
fi

write_existing_commit_delivery_metadata() {
    COMMIT_SHA=$(codify_run_shell 'cd /workspace && git rev-parse HEAD')
    FINAL_COMMIT_MESSAGE=$(codify_run_shell 'cd /workspace && git log -1 --pretty=%B')
    echo "Delivered existing local commit: ${COMMIT_SHA}"

    local summary_truncated task_metadata
    summary_truncated="${FINAL_SUMMARY_CONTENT:0:3000}"
    task_metadata=$(jq -nc \
        --argjson task_id "${TASK_ID:-0}" \
        --arg prompt "${USER_PROMPT:-}" \
        --arg commit_sha "${COMMIT_SHA}" \
        --arg commit_message "${FINAL_COMMIT_MESSAGE}" \
        --arg overall_summary "${FINAL_OVERALL_SUMMARY:-}" \
        --arg execution_summary "${summary_truncated}" \
        --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '{
            task_id: $task_id,
            prompt: $prompt,
            commit_sha: $commit_sha,
            commit_message: $commit_message,
            overall_summary: $overall_summary,
            execution_summary: $execution_summary,
            new_files: [],
            modified_files: [],
            deleted_files: [],
            additions: 0,
            deletions: 0,
            reused_local_commit: true,
            timestamp: $timestamp
        }')
    printf '%s\n' "${task_metadata}" > "${CODIFY_RUNTIME_DIR}/task-metadata.json"
    echo "Task metadata written to ${CODIFY_RUNTIME_DIR}/task-metadata.json for existing local commit"
}

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
        SUMMARY_CONTENT="${SUMMARY_CONTENT:0:45000}

...(内容已截断)"
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

# Now commit and push the changes
# Check if any changes were made (excluding result.md)
CHANGES=$(codify_run_shell 'cd /workspace && git status --porcelain' || true)
if [ -n "$CHANGES" ]; then
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
    done <<< "$CHANGES"
    echo "Changes detected, committing..."

    # Remove result.md if it exists from prior runs
    rm -f /workspace/result.md
    codify_run_shell 'cd /workspace && git rm -f result.md' 2>/dev/null || true

    # Add all changed files
    codify_run_shell 'cd /workspace && git add -A'

    # Calculate change statistics from staged changes before committing.
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
    # NOTE: files with commas in their names will be split incorrectly when
    # task-metadata.json is parsed on the backend (split(",")). This is an
    # inherent limitation of the comma-delimiter approach; such filenames are
    # extremely rare in practice.
    NEW_FILES="${NEW_FILES%,}"
    MODIFIED_FILES="${MODIFIED_FILES%,}"
    DELETED_FILES="${DELETED_FILES%,}"

    CHANGED_FILES_TEXT="新增: ${NEW_FILES:-无}
修改: ${MODIFIED_FILES:-无}
删除: ${DELETED_FILES:-无}"
    FINAL_CHANGED_FILES_TEXT="$(build_changed_files_table "${NEW_FILES}" "${MODIFIED_FILES}" "${DELETED_FILES}" "${FINAL_SUMMARY_CONTENT}")"

    COMMIT_DIFF_STATS=$(codify_run_shell 'cd /workspace && git diff --cached --stat' || echo "0 files changed")
    echo "Generating commit message with Claude..."
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
        echo "Claude commit message generation succeeded"
        echo "Claude raw commit message response:"
        printf '%s\n' "${GENERATED_COMMIT_MESSAGE}" | sed 's/^/  /'
        FINAL_COMMIT_MESSAGE=$(normalize_model_commit_message "${GENERATED_COMMIT_MESSAGE}")
    else
        echo "Claude commit message generation failed with exit code ${COMMIT_MESSAGE_RESULT}; using fallback"
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

    echo "Generating overall MR summary with Claude..."
    PREVIOUS_SUMMARY_FILE="${CODIFY_RUNTIME_DIR}/previous-task-summaries.md"
    if [ -f "${PREVIOUS_SUMMARY_FILE}" ]; then
        PREVIOUS_SUMMARY_BYTES=$(wc -c < "${PREVIOUS_SUMMARY_FILE}" | tr -d ' ')
        echo "Previous task summaries found: ${PREVIOUS_SUMMARY_FILE} (${PREVIOUS_SUMMARY_BYTES} bytes)"
    else
        echo "Previous task summaries not found at ${PREVIOUS_SUMMARY_FILE}; using empty history"
    fi
    OVERALL_SUMMARY_PROMPT=$(build_overall_summary_prompt "${PREVIOUS_SUMMARY_FILE}" "${FINAL_SUMMARY_CONTENT}" "${FINAL_COMMIT_MESSAGE}" "${COMMIT_DIFF_STATS}" "${USER_PROMPT}")
    printf '%s\n' "${OVERALL_SUMMARY_PROMPT}" > /tmp/overall_summary_prompt.txt
    chmod 644 /tmp/overall_summary_prompt.txt
    codify_chown /tmp/overall_summary_prompt.txt
    echo "Overall summary prompt written to /tmp/overall_summary_prompt.txt (${#OVERALL_SUMMARY_PROMPT} chars)"

    set +e
    GENERATED_OVERALL_SUMMARY=$(codify_harness_run_text /tmp/overall_summary_prompt.txt 60 2>/dev/null)
    OVERALL_SUMMARY_RESULT=$?
    set -e

    if [ ${OVERALL_SUMMARY_RESULT} -eq 0 ]; then
        echo "Claude overall summary generation succeeded"
        FINAL_OVERALL_SUMMARY=$(normalize_model_overall_summary "${GENERATED_OVERALL_SUMMARY}")
        if [ -n "${FINAL_OVERALL_SUMMARY}" ]; then
            echo "Overall MR summary generated (${#FINAL_OVERALL_SUMMARY} chars)"
        else
            echo "Claude overall summary normalized to empty; keeping previous MR summary"
        fi
    else
        echo "Claude overall summary generation failed with exit code ${OVERALL_SUMMARY_RESULT}; keeping previous MR summary"
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

    # Push to remote using the exact branch tip observed during repository preparation.
    repo_push_work_branch_with_lease

    # Get commit SHA
    COMMIT_SHA=$(codify_run_shell 'cd /workspace && git rev-parse HEAD')
    echo "Committed: ${COMMIT_SHA}"

    # MR was already created by backend before worker started.
    # In no-MR mode (TARGET_BRANCH is empty), skip all MR operations.
    MR_WEB_URL=""
    if [ -z "${TARGET_BRANCH:-}" ]; then
        echo "No-MR mode: skipping MR lookup and update"
    elif [ -n "${MR_IID}" ]; then
        echo "Using existing MR: !${MR_IID}"
        MR_WEB_URL=$(curl -sS -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
            "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/merge_requests/${MR_IID}" | \
            grep -o '"web_url":"[^"]*"' | cut -d'"' -f4)
    else
        # Fallback: check if MR already exists for this branch
        echo "Checking for existing MR..."
        EXISTING_MR=$(curl -sS -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
            "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/merge_requests?state=opened&source_branch=${BRANCH_NAME}" | \
            grep -o '"iid":[0-9]*' | head -1 | cut -d':' -f2)
        if [ -n "$EXISTING_MR" ]; then
            MR_IID="${EXISTING_MR}"
            MR_WEB_URL=$(curl -sS -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
                "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/merge_requests/${EXISTING_MR}" | \
                grep -o '"web_url":"[^"]*"' | cut -d'"' -f4)
        fi
    fi

    if [ -z "${TARGET_BRANCH:-}" ]; then
        echo "No-MR mode: branch pushed, no MR created"
    else
        if [ -z "$MR_WEB_URL" ]; then
            MR_WEB_URL=$(cat /workspace/mr_response.json 2>/dev/null | grep -o '"web_url":"[^"]*"' | cut -d'"' -f4)
        fi
        echo "MR: ${MR_WEB_URL:-none}"
    fi

    if [ -n "${MR_IID}" ]; then
        echo "MR IID: ${MR_IID}"
    fi

    # Write per-task metadata for MR description aggregation across tasks.
    # FINAL_SUMMARY_CONTENT is Claude's execution narrative (truncated to 3000 chars).
    SUMMARY_TRUNCATED="${FINAL_SUMMARY_CONTENT:0:3000}"
    TASK_METADATA=$(jq -nc \
        --argjson task_id "${TASK_ID:-0}" \
        --arg prompt "${USER_PROMPT:-}" \
        --arg commit_sha "${COMMIT_SHA:-}" \
        --arg commit_message "${FINAL_COMMIT_MESSAGE:-}" \
        --arg overall_summary "${FINAL_OVERALL_SUMMARY:-}" \
        --arg execution_summary "${SUMMARY_TRUNCATED}" \
        --arg new_files "${NEW_FILES:-}" \
        --arg modified_files "${MODIFIED_FILES:-}" \
        --arg deleted_files "${DELETED_FILES:-}" \
        --argjson additions "${ADDITIONS:-0}" \
        --argjson deletions "${DELETIONS:-0}" \
        --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '{
            task_id: $task_id,
            prompt: $prompt,
            commit_sha: $commit_sha,
            commit_message: $commit_message,
            overall_summary: $overall_summary,
            execution_summary: $execution_summary,
            new_files: (if $new_files == "" then [] else ($new_files | split(",")) end),
            modified_files: (if $modified_files == "" then [] else ($modified_files | split(",")) end),
            deleted_files: (if $deleted_files == "" then [] else ($deleted_files | split(",")) end),
            additions: $additions,
            deletions: $deletions,
            timestamp: $timestamp
        }')
    printf '%s\n' "${TASK_METADATA}" > "${CODIFY_RUNTIME_DIR}/task-metadata.json"
    echo "Task metadata written to ${CODIFY_RUNTIME_DIR}/task-metadata.json (overall_summary_chars=${#FINAL_OVERALL_SUMMARY})"

    echo "========================================"
    echo "Task completed successfully!"
    echo "========================================"
elif repo_has_unpublished_local_head; then
    echo "No new workspace changes; publishing the preserved local commit"
    repo_log "delivery work_branch=${BRANCH_NAME} relation=${REPO_WORK_BRANCH_RELATION} action=push_existing_head"
    repo_push_work_branch_with_lease
    write_existing_commit_delivery_metadata
    echo "========================================"
    echo "Task completed successfully!"
    echo "========================================"
else
    echo "No changes made by Harness"
    if [ "${REQUIRE_CHANGES:-true}" = "false" ]; then
        echo "require_changes disabled: task completed without code changes"
        echo "========================================"
        echo "Task completed successfully!"
        echo "========================================"
        exit 0
    fi
    exit 1
fi
