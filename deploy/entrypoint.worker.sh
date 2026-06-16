#!/bin/bash
set -e

# Worker entrypoint script
# Receives task parameters from environment variables

# Required environment variables
GITLAB_URL="${GITLAB_URL:?Missing GITLAB_URL}"
GITLAB_TOKEN="${GITLAB_TOKEN:?Missing GITLAB_TOKEN}"
PROJECT_ID="${PROJECT_ID:?Missing PROJECT_ID}"
BRANCH_NAME="${BRANCH_NAME:?Missing BRANCH_NAME}"
USER_PROMPT="${USER_PROMPT:?Missing USER_PROMPT}"

# Optional environment variables
# ISSUE_IID - required for webhook-triggered tasks, optional for manual tasks
ISSUE_IID="${ISSUE_IID:-}"
ISSUE_ID="${ISSUE_ID:-}"
ISSUE_TITLE="${ISSUE_TITLE:-}"
# BASE_BRANCH - base branch to create new branch from (defaults to TARGET_BRANCH if not set)
BASE_BRANCH="${BASE_BRANCH:-}"
TARGET_BRANCH="${TARGET_BRANCH:-}"

ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-http://localhost:11434/v1}"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-claude-sonnet-4-20250514}"
APPEND_SYSTEM_PROMPT="${APPEND_SYSTEM_PROMPT:-}"
CODIFY_RUNTIME_DIR="${CODIFY_RUNTIME_DIR:-/tmp/codify-runtime}"
export CODIFY_RUNTIME_DIR
mkdir -p "${CODIFY_RUNTIME_DIR}"
chown -R codify:codify "${CODIFY_RUNTIME_DIR}"
CONSOLE_LOG="${CODIFY_RUNTIME_DIR}/console.log"
DELIVERY_SUMMARY_FILE="${CODIFY_RUNTIME_DIR}/delivery-summary.md"
DELIVERY_SUMMARY_VALIDATION_FILE="${CODIFY_RUNTIME_DIR}/delivery-summary-validation.json"
MERMAID_SUMMARY_VALIDATE="${MERMAID_SUMMARY_VALIDATE:-true}"
MERMAID_SUMMARY_REPAIR_ATTEMPTS="${MERMAID_SUMMARY_REPAIR_ATTEMPTS:-2}"
MERMAID_SUMMARY_STRICT="${MERMAID_SUMMARY_STRICT:-false}"
touch "${CONSOLE_LOG}"
chown codify:codify "${CONSOLE_LOG}"

# Persist the same human-readable console stream that Docker exposes while the
# task is running. TaskRawLogChunk tails this file after completion.
CONSOLE_TEE_DIR=$(mktemp -d)
CONSOLE_TEE_PIPE="${CONSOLE_TEE_DIR}/console.pipe"
mkfifo "${CONSOLE_TEE_PIPE}"
tee -a "${CONSOLE_LOG}" < "${CONSOLE_TEE_PIPE}" &
exec > "${CONSOLE_TEE_PIPE}" 2>&1
rm -f "${CONSOLE_TEE_PIPE}"
rmdir "${CONSOLE_TEE_DIR}" 2>/dev/null || true

echo "========================================"
echo "Codify Worker"
echo "========================================"
echo "GitLab URL:   ${GITLAB_URL}"
echo "Project:      ${PROJECT_ID}"
echo "Issue:        ${ISSUE_IID:-N/A (manual task)}"
echo "MR IID:       ${MR_IID:-N/A}"
echo "Task ID:      ${TASK_ID:-N/A}"
echo "Branch:       ${BRANCH_NAME}"
echo "Base Branch:  ${BASE_BRANCH:-${TARGET_BRANCH}}"
echo "Target:       ${TARGET_BRANCH:-N/A (no-MR mode)}"
echo "----------------------------------------"
echo "Anthropic URL:  ${ANTHROPIC_BASE_URL}"
echo "Model:          ${ANTHROPIC_MODEL}"
echo "Max Turns:      ${CLAUDE_MAX_TURNS:-20}"
echo "API Key set:    $([ -n "$ANTHROPIC_API_KEY" ] && echo 'yes' || echo 'no')"
echo "System Prompt:  $([ -n "$APPEND_SYSTEM_PROMPT" ] && echo "set (${#APPEND_SYSTEM_PROMPT} chars)" || echo 'none')"
echo "GitLab Token:   $([ -n "$GITLAB_TOKEN" ] && echo 'set' || echo 'missing')"
echo "========================================"

# Extract scheme and hostname from GITLAB_URL for git operations
GITLAB_SCHEME="${GITLAB_URL%%://*}"
case "${GITLAB_SCHEME}" in http | https) ;; *) GITLAB_SCHEME="http" ;; esac
GITLAB_HOST=$(echo "${GITLAB_URL}" | sed 's|https://||' | sed 's|http://||')
CODIFY_GIT_CONFIG="/home/codify/.gitconfig"

# Configure git SSL verification early, before any GitLab API requests.
# When a custom CA bundle is provided, install it into the system trust store,
# configure git to use it, and enable SSL verification.
# Without a custom CA, fall back to disabling SSL verification (legacy behaviour).
if [ -n "${CUSTOM_CA_BUNDLE}" ] && [ -f "${CUSTOM_CA_BUNDLE}" ]; then
    echo "Installing custom CA certificate from ${CUSTOM_CA_BUNDLE}"
    cp "${CUSTOM_CA_BUNDLE}" /usr/local/share/ca-certificates/custom-ca.crt
    update-ca-certificates --fresh >/dev/null 2>&1 || true
    git config --global http.sslVerify true
    git config --global http.sslCAInfo "${CUSTOM_CA_BUNDLE}"
    git config --file "${CODIFY_GIT_CONFIG}" http.sslVerify true
    git config --file "${CODIFY_GIT_CONFIG}" http.sslCAInfo "${CUSTOM_CA_BUNDLE}"
    # Claude CLI (Node.js) picks up extra CA certs from this env var
    export NODE_EXTRA_CA_CERTS="${CUSTOM_CA_BUNDLE}"
    # Python requests / httpx pick this up automatically
    export REQUESTS_CA_BUNDLE="${CUSTOM_CA_BUNDLE}"
    export SSL_CERT_FILE="${CUSTOM_CA_BUNDLE}"
    # Import into JDK truststore so Java tools (Maven, Gradle, etc.) verify the CA
    if [ -n "${JAVA_HOME}" ] && [ -x "${JAVA_HOME}/bin/keytool" ]; then
        "${JAVA_HOME}/bin/keytool" -importcert -noprompt -trustcacerts \
            -alias custom-ca \
            -file "${CUSTOM_CA_BUNDLE}" \
            -keystore "${JAVA_HOME}/lib/security/cacerts" \
            -storepass changeit 2>/dev/null || true
        echo "Custom CA imported into JDK truststore"
    fi
    echo "Custom CA installed; SSL verification enabled"
else
    # No custom CA — disable git SSL verification to allow self-signed GitLab certs
    git config --global http.sslVerify false
    git config --file "${CODIFY_GIT_CONFIG}" http.sslVerify false
fi

# Get correct git repo URL from GitLab API (handles external_url misconfiguration)
echo "Fetching repository URL from GitLab API..."
GITLAB_API_RESPONSE=$(curl -sS -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}")
GIT_REPO_URL=$(echo "${GITLAB_API_RESPONSE}" | grep -o '"http_url_to_repo":"[^"]*"' | cut -d'"' -f4)
PROJECT_PATH=$(echo "${GITLAB_API_RESPONSE}" | grep -o '"path_with_namespace":"[^"]*"' | cut -d'"' -f4)
DEFAULT_BRANCH=$(echo "${GITLAB_API_RESPONSE}" | grep -o '"default_branch":"[^"]*"' | cut -d'"' -f4)

# Set BASE_BRANCH: explicit > TARGET_BRANCH > project default branch (now that DEFAULT_BRANCH is known)
if [ -z "${BASE_BRANCH}" ]; then
    if [ -n "${TARGET_BRANCH}" ]; then
        BASE_BRANCH="${TARGET_BRANCH}"
    else
        BASE_BRANCH="${DEFAULT_BRANCH:-main}"
        echo "No TARGET_BRANCH set (no-MR mode); using default branch '${BASE_BRANCH}' as base"
    fi
fi

# Fallback to constructed URL if API fails
if [ -z "${PROJECT_PATH}" ] && [ -n "${GIT_REPO_URL}" ]; then
    PROJECT_PATH=$(echo "${GIT_REPO_URL}" | sed -E 's|https?://[^/]+/||; s|\.git$||')
fi

if [ -z "${PROJECT_PATH}" ]; then
    echo "Warning: Could not get URL from API, using constructed URL"
    PROJECT_PATH="projects/${PROJECT_ID}"
fi

# Build repo URL with the actual configured host and let credential helper provide auth.
GIT_REPO_URL="${GITLAB_SCHEME}://${GITLAB_HOST}/${PROJECT_PATH}.git"

# Log repository URL without exposing token
echo "Repository URL: ${GITLAB_SCHEME}://[TOKEN]@${GITLAB_HOST}/${PROJECT_PATH}.git"

# Set up credential helper - write credentials file for both root and codify.
# The entrypoint clones as root, but Claude runs as codify with HOME=/home/codify.
GIT_CREDENTIAL_LINE="${GITLAB_SCHEME}://oauth2:${GITLAB_TOKEN}@${GITLAB_HOST}"
rm -rf /root/.git-credentials /home/codify/.git-credentials
printf '%s\n' "${GIT_CREDENTIAL_LINE}" > /root/.git-credentials
chmod 600 /root/.git-credentials
printf '%s\n' "${GIT_CREDENTIAL_LINE}" > /home/codify/.git-credentials
chmod 600 /home/codify/.git-credentials
chown codify:codify /home/codify/.git-credentials

git config --global credential.helper store
git config --file "${CODIFY_GIT_CONFIG}" credential.helper store

# Mark /workspace as safe before any git operations on reused workspaces
git config --global --add safe.directory /workspace

# Clone or reuse repository with authentication.
if [ -d /workspace/.git ]; then
    echo "Reusing existing workspace..."
    cd /workspace
    git remote set-url origin "${GIT_REPO_URL}"
    git fetch origin
else
    echo "Cloning repository..."
    git clone "${GIT_REPO_URL}" /workspace
    cd /workspace
fi

# Configure git
git config --global user.email "bot@codify.local"
git config --global user.name "Codify Bot"
git config --global --add safe.directory /workspace
git config --file "${CODIFY_GIT_CONFIG}" user.email "bot@codify.local"
git config --file "${CODIFY_GIT_CONFIG}" user.name "Codify Bot"
git config --file "${CODIFY_GIT_CONFIG}" --add safe.directory /workspace
chown codify:codify "${CODIFY_GIT_CONFIG}"

GIT_AUTHOR_NAME_VALUE="${GIT_AUTHOR_NAME:-${CODIFY_AUTHOR_NAME:-Codify User}}"
GIT_AUTHOR_EMAIL_VALUE="${GIT_AUTHOR_EMAIL:-${CODIFY_AUTHOR_EMAIL:-codify-task@codify.local}}"
CODIFY_COAUTHOR_NAME_VALUE="${CODIFY_COAUTHOR_NAME:-Codify}"
CODIFY_COAUTHOR_EMAIL_VALUE="${CODIFY_COAUTHOR_EMAIL:-codify@codify.local}"

# Checkout/create branch
WORKSPACE_CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
if [ -n "${WORKSPACE_CURRENT_BRANCH}" ] && [ "${WORKSPACE_CURRENT_BRANCH}" != "HEAD" ] && [ "${WORKSPACE_CURRENT_BRANCH}" != "${BRANCH_NAME}" ]; then
    WORKSPACE_DIRTY=$(git status --porcelain || true)
    if [ -n "${WORKSPACE_DIRTY}" ]; then
        echo "ERROR: Workspace has uncommitted changes on branch ${WORKSPACE_CURRENT_BRANCH}, cannot switch to ${BRANCH_NAME}"
        exit 1
    fi
fi

echo "Checking out branch: ${BRANCH_NAME}"
git fetch origin

# Verify BASE_BRANCH exists on remote; if not, fall back to the remote's actual default branch
if ! git rev-parse --verify "origin/${BASE_BRANCH}" > /dev/null 2>&1; then
    echo "Warning: origin/${BASE_BRANCH} not found. Detecting remote default branch..."
    DETECTED=$(git ls-remote --symref origin HEAD 2>/dev/null | grep '^ref:' | sed 's|ref: refs/heads/||;s|	HEAD||')
    if [ -n "${DETECTED}" ]; then
        echo "Detected remote default branch: ${DETECTED} (was: ${BASE_BRANCH})"
        BASE_BRANCH="${DETECTED}"
    else
        echo "ERROR: Cannot resolve base branch 'origin/${BASE_BRANCH}' and could not detect default branch"
        exit 1
    fi
fi

if git checkout "${BRANCH_NAME}" 2>/dev/null; then
    echo "Branch ${BRANCH_NAME} exists locally, checking for uncommitted changes..."
    BRANCH_DIRTY=$(git status --porcelain || true)
    if [ -n "${BRANCH_DIRTY}" ]; then
        echo "Warning: Workspace has uncommitted changes from a previous task, skipping pull to preserve work"
    elif git ls-remote --exit-code --heads origin "${BRANCH_NAME}" > /dev/null 2>&1; then
        echo "Remote branch found, pulling latest..."
        git pull origin "${BRANCH_NAME}"
    else
        echo "Branch exists locally but not on remote yet (prior task may not have pushed), continuing with local state"
    fi
else
    echo "Creating new branch from ${BASE_BRANCH}..."
    git checkout -b "${BRANCH_NAME}" "origin/${BASE_BRANCH}"
fi

# Run Claude Code CLI in direct execution mode
echo "Running Claude Code CLI in direct execution mode..."
echo "Prompt: ${USER_PROMPT}"
echo ""

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

*Claude Code CLI 正在直接实施变更...*
$(build_issue_reference_block)
EOF
}

build_issue_reference_block() {
    if [ -n "${ISSUE_IID}" ]; then
        printf '\n\nCloses #%s' "${ISSUE_IID}"
    fi
}

sanitize_summary_content() {
    local summary_text="$1"

    printf '%s\n' "${summary_text}" | awk '
        BEGIN { skip = 0 }
        /^## 执行摘要[[:space:]]*$/ { next }
        /^### 修改的文件[[:space:]]*$/ { skip = 1; next }
        /^### / {
            if (skip == 1) {
                skip = 0
            }
        }
        skip == 1 { next }
        /未跟踪/ { next }
        /可按需提交/ { next }
        { print }
    '
}

normalize_delivery_summary_response() {
    local raw_summary="$1"

    printf '%s' "${raw_summary}" | python3 -c 'import re, sys; text = sys.stdin.read(); text = re.sub(r"\r$", "", text, flags=re.MULTILINE); text = re.sub(r"<think\b[^>]*>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL); text = re.sub(r"</?think\b[^>]*>", "", text, flags=re.IGNORECASE); text = re.sub(r"^```(?:markdown)?\s*", "", text.strip(), flags=re.IGNORECASE); text = re.sub(r"\s*```$", "", text).strip(); print(text, end="")'
}

annotate_delivery_summary_validation() {
    local attempts="$1"
    local repaired="$2"

    if [ ! -f "${DELIVERY_SUMMARY_VALIDATION_FILE}" ]; then
        return 0
    fi

    local tmp_file="${DELIVERY_SUMMARY_VALIDATION_FILE}.tmp"
    jq \
        --argjson attempts "${attempts}" \
        --argjson repaired "${repaired}" \
        '. + {repairAttempts: $attempts, repaired: $repaired}' \
        "${DELIVERY_SUMMARY_VALIDATION_FILE}" > "${tmp_file}" 2>/dev/null && mv "${tmp_file}" "${DELIVERY_SUMMARY_VALIDATION_FILE}" || rm -f "${tmp_file}"
}

run_mermaid_summary_validation() {
    local summary_file="$1"
    local output_file="$2"
    local validator="/opt/codify-mermaid/validate_mermaid_summary.mjs"

    if [ "${MERMAID_SUMMARY_VALIDATE}" != "true" ]; then
        jq -nc '{ok: true, diagramCount: 0, errors: [], skipped: true, reason: "disabled"}' > "${output_file}"
        return 0
    fi

    if [ ! -f "${validator}" ] || ! command -v node >/dev/null 2>&1; then
        jq -nc '{ok: false, diagramCount: 0, errors: [{index: null, message: "Mermaid validator unavailable", source: ""}], skipped: true, reason: "validator_unavailable"}' > "${output_file}"
        return 1
    fi

    local tmp_file="${output_file}.tmp"
    local err_file="${output_file}.stderr"
    set +e
    node "${validator}" "${summary_file}" > "${tmp_file}" 2> "${err_file}"
    local validation_status=$?
    set -e

    if [ ${validation_status} -ne 0 ]; then
        local validator_error
        validator_error="$(cat "${err_file}" 2>/dev/null || true)"
        jq -nc \
            --arg message "${validator_error:-Mermaid validator failed}" \
            '{ok: false, diagramCount: 0, errors: [{index: null, message: $message, source: ""}], validatorError: $message}' \
            > "${output_file}"
        rm -f "${tmp_file}" "${err_file}"
        return 1
    fi

    mv "${tmp_file}" "${output_file}"
    rm -f "${err_file}"
    jq -e '.ok == true' "${output_file}" >/dev/null 2>&1
}

build_mermaid_repair_prompt() {
    local summary_file="$1"
    local validation_file="$2"
    local prompt_file="$3"

    {
        printf '%s\n' '下面是一段 Codify 最终交付摘要，其中 Mermaid 图表无法渲染。'
        printf '%s\n' '请只修复 Markdown 中的 mermaid fenced code block，保留其它文字和业务结论。'
        printf '%s\n' '不要调用工具，不要修改文件，不要添加解释、标题或前后缀；只输出修复后的完整 Markdown 摘要。'
        printf '\n%s\n' 'Mermaid 校验错误 JSON：'
        cat "${validation_file}"
        printf '\n%s\n' '原始交付摘要：'
        cat "${summary_file}"
    } > "${prompt_file}"
}

prepare_delivery_summary() {
    local raw_summary="$1"
    local current_summary
    current_summary="$(normalize_delivery_summary_response "${raw_summary}")"

    local summary_check_file="/tmp/delivery-summary-check.md"
    local repair_prompt_file="/tmp/delivery-summary-repair-prompt.md"
    local attempts=0
    local repaired=false

    printf '%s' "${current_summary}" > "${summary_check_file}"
    if run_mermaid_summary_validation "${summary_check_file}" "${DELIVERY_SUMMARY_VALIDATION_FILE}"; then
        echo "Delivery summary Mermaid validation passed" >&2
        annotate_delivery_summary_validation "${attempts}" "${repaired}"
        printf '%s' "${current_summary}"
        return 0
    fi

    local diagram_count error_count
    diagram_count="$(jq -r '.diagramCount // 0' "${DELIVERY_SUMMARY_VALIDATION_FILE}" 2>/dev/null || echo 0)"
    error_count="$(jq -r '(.errors // []) | length' "${DELIVERY_SUMMARY_VALIDATION_FILE}" 2>/dev/null || echo 0)"
    echo "Delivery summary Mermaid validation failed (diagrams=${diagram_count}, errors=${error_count})" >&2

    while [ "${attempts}" -lt "${MERMAID_SUMMARY_REPAIR_ATTEMPTS}" ]; do
        attempts=$((attempts + 1))
        echo "Repairing delivery summary Mermaid diagrams (attempt ${attempts}/${MERMAID_SUMMARY_REPAIR_ATTEMPTS})" >&2
        build_mermaid_repair_prompt "${summary_check_file}" "${DELIVERY_SUMMARY_VALIDATION_FILE}" "${repair_prompt_file}"

        set +e
        local repaired_summary
        repaired_summary=$(env HOME=/home/codify timeout 60 su -m -s /bin/bash codify -c 'cd /tmp && /usr/local/bin/claude -p --bare --tools "" --permission-mode plan --no-session-persistence --output-format text --max-turns 3 --model "${ANTHROPIC_MODEL}" < /tmp/delivery-summary-repair-prompt.md' 2>/dev/null)
        local repair_status=$?
        set -e

        if [ ${repair_status} -ne 0 ]; then
            echo "Delivery summary Mermaid repair failed with exit code ${repair_status}" >&2
            continue
        fi

        repaired_summary="$(normalize_delivery_summary_response "${repaired_summary}")"
        if [ -z "${repaired_summary}" ]; then
            echo "Delivery summary Mermaid repair returned empty output" >&2
            continue
        fi

        current_summary="${repaired_summary}"
        printf '%s' "${current_summary}" > "${summary_check_file}"
        if run_mermaid_summary_validation "${summary_check_file}" "${DELIVERY_SUMMARY_VALIDATION_FILE}"; then
            echo "Delivery summary Mermaid repair succeeded" >&2
            repaired=true
            annotate_delivery_summary_validation "${attempts}" "${repaired}"
            printf '%s' "${current_summary}"
            return 0
        fi
    done

    echo "Delivery summary Mermaid validation still failed after ${attempts} repair attempt(s)" >&2
    annotate_delivery_summary_validation "${attempts}" "${repaired}"
    if [ "${MERMAID_SUMMARY_STRICT}" = "true" ]; then
        return 1
    fi

    printf '%s' "${current_summary}"
}

write_delivery_summary_artifacts() {
    local summary_text="$1"

    printf '%s\n' "${summary_text}" > "${DELIVERY_SUMMARY_FILE}"
    chmod 644 "${DELIVERY_SUMMARY_FILE}" "${DELIVERY_SUMMARY_VALIDATION_FILE}" 2>/dev/null || true
    chown codify:codify "${DELIVERY_SUMMARY_FILE}" "${DELIVERY_SUMMARY_VALIDATION_FILE}" 2>/dev/null || true
    echo "Delivery summary written to ${DELIVERY_SUMMARY_FILE} (${#summary_text} chars)"
}

write_plan_task_metadata() {
    local summary_text="$1"
    local summary_truncated="${summary_text:0:3000}"
    local task_metadata

    task_metadata=$(jq -nc \
        --argjson task_id "${TASK_ID:-0}" \
        --arg prompt "${USER_PROMPT:-}" \
        --arg execution_summary "${summary_truncated}" \
        --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '{
            task_id: $task_id,
            prompt: $prompt,
            commit_sha: "",
            commit_message: "",
            overall_summary: "",
            execution_summary: $execution_summary,
            new_files: [],
            modified_files: [],
            deleted_files: [],
            additions: 0,
            deletions: 0,
            timestamp: $timestamp
        }')
    printf '%s\n' "${task_metadata}" > "${CODIFY_RUNTIME_DIR}/task-metadata.json"
    chmod 644 "${CODIFY_RUNTIME_DIR}/task-metadata.json" 2>/dev/null || true
    chown codify:codify "${CODIFY_RUNTIME_DIR}/task-metadata.json" 2>/dev/null || true
    echo "Plan task metadata written to ${CODIFY_RUNTIME_DIR}/task-metadata.json"
}

describe_file_path() {
    local filepath="$1"

    case "${filepath}" in
        .gitignore)
            printf '%s' "Git 忽略规则配置"
            ;;
        pom.xml)
            printf '%s' "Maven 项目配置"
            ;;
        src/main/java/*.java)
            printf '%s' "Java 示例或业务源码"
            ;;
        src/main/resources/*)
            printf '%s' "项目运行资源配置"
            ;;
        src/test/*)
            printf '%s' "测试代码"
            ;;
        *.md)
            printf '%s' "文档说明"
            ;;
        *)
            printf '%s' "本次改动涉及的文件"
            ;;
    esac
}

extract_file_description_from_summary() {
    local filepath="$1"
    local summary_text="$2"
    local line=""

    line=$(printf '%s\n' "${summary_text}" | grep -F "**${filepath}** -" | head -1 || true)
    if [ -n "${line}" ]; then
        printf '%s\n' "${line}" | sed -E 's/^[0-9]+[.)]?[[:space:]]*\*\*[^*]+\*\*[[:space:]]*-[[:space:]]*//'
        return 0
    fi

    describe_file_path "${filepath}"
}

append_changed_file_rows() {
    local change_type="$1"
    local csv_files="$2"
    local summary_text="$3"

    if [ -z "${csv_files}" ]; then
        return 0
    fi

    local old_ifs="${IFS}"
    IFS=','
    read -ra files <<< "${csv_files}"
    IFS="${old_ifs}"

    local filepath=""
    for filepath in "${files[@]}"; do
        [ -z "${filepath}" ] && continue
        printf '| %s | `%s` | %s |\n' \
            "${change_type}" \
            "${filepath}" \
            "$(extract_file_description_from_summary "${filepath}" "${summary_text}")"
    done
}

build_changed_files_table() {
    local new_files="$1"
    local modified_files="$2"
    local deleted_files="$3"
    local summary_text="$4"
    local rows=""

    rows+=$(append_changed_file_rows "新增" "${new_files}" "${summary_text}")
    rows+=$(append_changed_file_rows "修改" "${modified_files}" "${summary_text}")
    rows+=$(append_changed_file_rows "删除" "${deleted_files}" "${summary_text}")

    if [ -z "${rows}" ]; then
        rows='| 无 | 无 | 无 |'
    fi

    cat <<EOF
| 类型 | 文件 | 说明 |
| --- | --- | --- |
${rows}
EOF
}

build_completed_mr_description() {
    local summary_text="$1"
    local changed_files_text="$2"
    cat <<EOF
## ✅ AI 执行完成

### 需求
${USER_PROMPT}

### 涉及文件
${changed_files_text}

### 执行摘要
${summary_text}
$(build_issue_reference_block)
EOF
}

build_commit_message_prompt() {
    local changed_files_text="$1"
    local diff_stats_text="$2"
    local summary_text="$3"
    cat <<EOF
根据下面的信息，直接输出一条 Conventional Commits 规范的 git commit message。

重要：直接输出 commit message 本身，第一个字符必须是 type（如 feat:、fix: 等），不要有任何前言、解释或说明文字。

格式：
1. 使用中文。
2. 第一行格式：<type>: <description>
3. type 从 feat、fix、refactor、docs、test、build、chore、ci 中选择。
4. description 简洁明确，控制在 50 字符内。
5. 如需正文，subject 后空一行，用 1-3 行简短说明。
6. 最后添加 footer：AI-Generated: true
7. 不要使用 markdown、代码块、引号，不要包含 Co-authored-by。

用户需求：
${USER_PROMPT}

改动文件：
${changed_files_text}

Diff 统计：
${diff_stats_text}

执行摘要：
${summary_text}
EOF
}

normalize_model_commit_message() {
    local raw_message="$1"

    printf '%s' "${raw_message}" | python3 -c 'import re, sys; text = sys.stdin.read(); text = re.sub(r"\r$", "", text, flags=re.MULTILINE); text = re.sub(r"<think\b[^>]*>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL); text = re.sub(r"</?think\b[^>]*>", "", text, flags=re.IGNORECASE); print(text.strip(), end="")'
}

build_overall_summary_prompt() {
    local previous_summary_file="$1"
    local current_summary_text="$2"
    local commit_message_text="$3"
    local diff_stats_text="$4"
    local current_user_prompt="$5"
    local previous_summary_text="暂无前序任务摘要。"

    if [ -f "${previous_summary_file}" ]; then
        previous_summary_text="$(cat "${previous_summary_file}")"
    fi

    cat <<EOF
请基于同一个 GitLab MR 下的前序任务摘要和当前任务执行结果，生成一个真正的跨任务总体总结。

要求：
1. 使用中文。
2. 只总结整体目标、最终完成的核心结果、当前状态和验证情况。
3. 不要逐个复述每个 Task，不要输出文件清单，不要重复 MR Changes 页可看到的 diff 信息。
4. 控制在 3-6 条要点，使用 Markdown bullet list。
5. 不要添加标题、前言、结束语或代码块。

前序任务摘要：
${previous_summary_text}

当前任务需求：
${current_user_prompt}

当前任务提交说明：
${commit_message_text}

当前任务 Diff 统计：
${diff_stats_text}

当前任务执行摘要：
${current_summary_text}
EOF
}

normalize_model_overall_summary() {
    local raw_summary="$1"

    printf '%s' "${raw_summary}" | python3 -c 'import re, sys; text = sys.stdin.read(); text = re.sub(r"\r$", "", text, flags=re.MULTILINE); text = re.sub(r"<think\b[^>]*>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL); text = re.sub(r"</?think\b[^>]*>", "", text, flags=re.IGNORECASE); text = re.sub(r"^```(?:markdown)?\s*", "", text.strip(), flags=re.IGNORECASE); text = re.sub(r"\s*```$", "", text).strip(); text = text.replace("</details>", "&lt;/details&gt;"); print((text[:2000].rstrip() + "...") if len(text) > 2000 else text, end="")'
}

TASK_MODE="${TASK_MODE:-execute}"

if [ "${TASK_MODE}" = "plan" ]; then
cat > /tmp/claude_prompt.txt <<EOF
请分析下面的需求，给出详细的实施方案。不要修改任何文件，不要执行任何写操作（包括 git commit、git push、创建 MR）。

需求:
${USER_PROMPT}

上下文:
- 仓库路径: ${PROJECT_PATH}

要求:
1. 检查代码库，理解现有结构和约束。
2. 给出清晰、可操作的实施方案，包含：
    - 需要新增或修改哪些文件，以及具体的改动思路
    - 为什么这么设计
    - 潜在风险或需要注意的地方
3. 不要修改任何文件，不要执行任何写操作。
4. 如果方案需要表达流程、架构、时序、状态转换等图表，必须使用 Markdown 的 mermaid fenced code block（语言标记为 mermaid），不要使用 ASCII 图、图片链接或其它图表格式。
5. 不要要求人工确认。
EOF
else
cat > /tmp/claude_prompt.txt <<EOF
请直接完成下面的需求，不要先输出规划或步骤清单。

需求:
${USER_PROMPT}

上下文:
- 仓库路径: ${PROJECT_PATH}

要求:
1. 直接检查代码库并实施修改。
2. 仅在当前仓库内工作，优先做精确修改，不要引入无关改动。
3. 完成后运行相关验证命令；如果仓库里没有对应命令，就明确说明。
4. 最终输出简短执行摘要，至少包含：
    - 做了什么，为什么这么做
    - 运行了哪些验证
5. 如果执行摘要需要表达流程、架构、时序、状态转换等图表，必须使用 Markdown 的 mermaid fenced code block（语言标记为 mermaid），不要使用 ASCII 图、图片链接或其它图表格式。
6. 不要描述"未跟踪文件""待提交""可按需提交"这类提交前状态，默认以已经完成并准备提交的口吻总结结果。
7. 不要要求人工确认，除非你真的被阻塞。
EOF
fi

CLAUDE_SYSTEM_PROMPT_FILE="/tmp/claude_system_prompt.txt"
if [ -n "${APPEND_SYSTEM_PROMPT}" ]; then
    printf '%s' "${APPEND_SYSTEM_PROMPT}" > "${CLAUDE_SYSTEM_PROMPT_FILE}"
    chmod 600 "${CLAUDE_SYSTEM_PROMPT_FILE}"
    chown codify:codify "${CLAUDE_SYSTEM_PROMPT_FILE}"
    export APPEND_SYSTEM_PROMPT_FILE="${CLAUDE_SYSTEM_PROMPT_FILE}"
    unset APPEND_SYSTEM_PROMPT
fi

chmod 644 /tmp/claude_prompt.txt
chown -R codify:codify /workspace /tmp/claude_prompt.txt
# Ensure issue-scoped shared storage is writable by the codify user
if [ -d /opt/codify-issue-shared ]; then
    chown codify:codify /opt/codify-issue-shared
fi
# Ensure session storage directory is writable by the codify user
if [ -d /home/codify/.claude ]; then
    chown -R codify:codify /home/codify/.claude
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
    chown codify:codify /home/codify/.claude.json
fi

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

trap create_runtime_archive EXIT

echo "Claude CLI version: $(/usr/local/bin/claude --version)"
echo "Updating MR with execution status..."
update_mr_description "$(build_running_mr_description)" || true

echo "Starting Claude CLI (streaming mode)..."
set +e
env HOME=/home/codify timeout "${TASK_TIMEOUT:-1800}" su -m -s /bin/bash codify -c \
    'cd /workspace && export PATH="/usr/local/bin:/usr/bin:/bin:${JAVA_HOME}/bin" && ARTIFACT_DIR="${CODIFY_RUNTIME_DIR}" CI_CLAUDE_DISABLE_CONSOLE_TEE=1 PROMPT_FILE=/tmp/claude_prompt.txt /usr/local/bin/ci-claude.sh' \
    > /tmp/claude_result.json
SCRIPT_RESULT=$?
set -e
echo "Claude CLI exited with code: ${SCRIPT_RESULT}"

RESULT=${SCRIPT_RESULT}

# Always emit structured tool calls if the JSON file exists, even on failure.
# This lets the frontend show a timeline of what was attempted before the failure.
if [ -f /tmp/claude_result.json ] && [ -s /tmp/claude_result.json ]; then
    SUMMARY_CONTENT=$(jq -r '.result // ""' /tmp/claude_result.json 2>/dev/null || true)
    if [ ${#SUMMARY_CONTENT} -gt 45000 ]; then
        SUMMARY_CONTENT="${SUMMARY_CONTENT:0:45000}

...(内容已截断)"
    fi
    FINAL_SUMMARY_CONTENT="$(sanitize_summary_content "${SUMMARY_CONTENT}")"

fi

if [ $RESULT -ne 0 ]; then
    echo "Claude execution failed with exit code: ${RESULT}"
    create_runtime_archive
    exit $RESULT
fi

FINAL_SUMMARY_CONTENT="$(prepare_delivery_summary "${FINAL_SUMMARY_CONTENT}")"
write_delivery_summary_artifacts "${FINAL_SUMMARY_CONTENT}"

# Plan mode: discard any accidental workspace changes and exit successfully
if [ "${TASK_MODE}" = "plan" ]; then
    echo "Plan mode: discarding any workspace changes..."
    git checkout -- . 2>/dev/null || true
    git clean -fd 2>/dev/null || true
    write_plan_task_metadata "${FINAL_SUMMARY_CONTENT}"
    create_runtime_archive
    echo "========================================"
    echo "Plan task completed successfully!"
    echo "========================================"
    exit 0
fi

# Now commit and push the changes
# Check if any changes were made (excluding result.md)
CHANGES=$(git status --porcelain || true)
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
    git rm -f result.md 2>/dev/null || true

    # Add all changed files
    git add -A

    # Calculate change statistics from staged changes before committing.
    echo "Calculating change statistics..."
    DIFF_STATS=$(git diff --cached --stat || echo "0 files changed")
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
    STAGED_NAME_STATUS=$(git diff --cached --name-status --no-renames || true)
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

    COMMIT_DIFF_STATS=$(git diff --cached --stat || echo "0 files changed")
    echo "Generating commit message with Claude..."
    COMMIT_MESSAGE_PROMPT=$(build_commit_message_prompt "${CHANGED_FILES_TEXT}" "${COMMIT_DIFF_STATS}" "${FINAL_SUMMARY_CONTENT}")
    printf '%s\n' "${COMMIT_MESSAGE_PROMPT}" > /tmp/commit_message_prompt.txt
    chmod 644 /tmp/commit_message_prompt.txt
    chown codify:codify /tmp/commit_message_prompt.txt
    echo "Commit message prompt written to /tmp/commit_message_prompt.txt"

    set +e
    GENERATED_COMMIT_MESSAGE=$(env HOME=/home/codify timeout 60 su -m -s /bin/bash codify -c 'cd /workspace && /usr/local/bin/claude -p --dangerously-skip-permissions --no-session-persistence --output-format text --max-turns 3 --model "${ANTHROPIC_MODEL}" < /tmp/commit_message_prompt.txt' 2>/dev/null)
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
    chown codify:codify /tmp/overall_summary_prompt.txt
    echo "Overall summary prompt written to /tmp/overall_summary_prompt.txt (${#OVERALL_SUMMARY_PROMPT} chars)"

    set +e
    GENERATED_OVERALL_SUMMARY=$(env HOME=/home/codify timeout 60 su -m -s /bin/bash codify -c 'cd /workspace && /usr/local/bin/claude -p --dangerously-skip-permissions --no-session-persistence --output-format text --max-turns 3 --model "${ANTHROPIC_MODEL}" < /tmp/overall_summary_prompt.txt' 2>/dev/null)
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
    git commit -F /tmp/commit_message.txt

    # Push to remote using git push
    echo "Pushing to remote..."
    git remote set-url origin "${GITLAB_SCHEME}://${GITLAB_HOST}/${PROJECT_PATH}.git"
    git config --local http.extraHeader "PRIVATE-TOKEN: ${GITLAB_TOKEN}"
    GIT_TERMINAL_PROMPT=0 git push -u origin "${BRANCH_NAME}"

    # Get commit SHA
    COMMIT_SHA=$(git rev-parse HEAD)
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

    FINALIZATION_EVENT=$(jq -nc \
        --arg commit_sha "${COMMIT_SHA:-}" \
        --argjson additions "${ADDITIONS:-0}" \
        --argjson deletions "${DELETIONS:-0}" \
        --argjson total "${TOTAL_CHANGES:-0}" \
        --arg commit_message "${FINAL_COMMIT_MESSAGE:-}" \
        '{
            type:"codify_worker",
            subtype:"finalization",
            commit_sha:$commit_sha,
            diff:{additions:$additions,deletions:$deletions,total:$total},
            commit_message:$commit_message
        }')
    append_runtime_event "${FINALIZATION_EVENT}"

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

    create_runtime_archive

    echo "========================================"
    echo "Task completed successfully!"
    echo "========================================"
else
    echo "No changes made by Claude CLI"
    if [ "${REQUIRE_CHANGES:-true}" = "false" ]; then
        echo "require_changes disabled: task completed without code changes"
        create_runtime_archive
        echo "========================================"
        echo "Task completed successfully!"
        echo "========================================"
        exit 0
    fi
    create_runtime_archive
    exit 1
fi
