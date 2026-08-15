# GitLab merge-request helpers.

update_mr() {
    local title="${1:-}"
    local description="${2:-}"
    if [ -z "${MR_IID:-}" ]; then
        echo "No MR_IID, skipping MR update"
        return 0
    fi

    local response_code
    local curl_args=(
        -sS
        -o /tmp/mr_update_response.txt
        -w "%{http_code}"
        -X PUT
        -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}"
    )

    if [ -n "${title}" ]; then
        curl_args+=(--data-urlencode "title=${title}")
    fi

    if [ -n "${description}" ]; then
        curl_args+=(--data-urlencode "description=${description}")
    fi

    response_code=$(curl "${curl_args[@]}" \
        "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/merge_requests/${MR_IID}") || {
        echo "Error updating MR description"
        cat /tmp/mr_update_response.txt 2>/dev/null || true
        return 1
    }

    if [ "${response_code}" -ge 400 ] 2>/dev/null; then
        echo "Failed to update MR: ${response_code}"
        cat /tmp/mr_update_response.txt 2>/dev/null || true
        return 1
    fi

    echo "MR description updated successfully"
}

update_mr_description() {
    update_mr "" "$1"
}

build_running_mr_description() {
    cat <<EOF
## ${ISSUE_TITLE:-AI 正在执行}

### 🔄 任务 #${TASK_ID} 正在执行

**提示:** ${USER_PROMPT}

---

*AI 正在直接实施变更...*
$(build_issue_reference_block)
EOF
}

build_issue_reference_block() {
    if [ -n "${ISSUE_IID}" ]; then
        printf '\n\nCloses #%s' "${ISSUE_IID}"
    fi
}
