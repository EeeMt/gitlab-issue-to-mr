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
# BASE_BRANCH - base branch to create new branch from (defaults to TARGET_BRANCH if not set)
BASE_BRANCH="${BASE_BRANCH:-}"
TARGET_BRANCH="${TARGET_BRANCH:-}"

ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-http://localhost:11434/v1}"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-claude-sonnet-4-20250514}"

echo "========================================"
echo "GitLab Issue to MR Worker"
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
echo "GitLab Token:   $([ -n "$GITLAB_TOKEN" ] && echo 'set' || echo 'missing')"
echo "========================================"

# Extract hostname from GITLAB_URL for git operations
GITLAB_HOST=$(echo "${GITLAB_URL}" | sed 's|https://||' | sed 's|http://||')

# Get correct git repo URL from GitLab API (handles external_url misconfiguration)
echo "Fetching repository URL from GitLab API..."
GITLAB_API_RESPONSE=$(curl -s -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
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
GIT_REPO_URL="http://${GITLAB_HOST}/${PROJECT_PATH}.git"

# Log repository URL without exposing token
echo "Repository URL: http://[TOKEN]@${GITLAB_HOST}/${PROJECT_PATH}.git"

# Configure git SSL verification
# When a custom CA bundle is provided, install it into the system trust store,
# configure git to use it, and enable SSL verification.
# Without a custom CA, fall back to disabling SSL verification (legacy behaviour).
if [ -n "${CUSTOM_CA_BUNDLE}" ] && [ -f "${CUSTOM_CA_BUNDLE}" ]; then
    echo "Installing custom CA certificate from ${CUSTOM_CA_BUNDLE}"
    cp "${CUSTOM_CA_BUNDLE}" /usr/local/share/ca-certificates/custom-ca.crt
    update-ca-certificates --fresh 2>/dev/null || true
    git config --global http.sslVerify true
    git config --global http.sslCAInfo "${CUSTOM_CA_BUNDLE}"
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
fi

# Set up credential helper - write credentials file
rm -rf ~/.git-credentials
touch ~/.git-credentials
chmod 600 ~/.git-credentials
# Write credentials in format: protocol://username:password@host
echo "http://oauth2:${GITLAB_TOKEN}@${GITLAB_HOST}" > ~/.git-credentials

git config --global credential.helper store

# Clone repository with authentication
echo "Cloning repository..."
git clone "${GIT_REPO_URL}" /workspace
cd /workspace

# Configure git
git config --global user.email "bot@codify.local"
git config --global user.name "Codify Bot"
git config --global --add safe.directory /workspace

# Checkout/create branch
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
    echo "Branch already exists, pulling latest..."
    git pull origin "${BRANCH_NAME}"
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
## 🚀 AI 正在执行

### 需求
${USER_PROMPT}

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

build_mr_title_prompt() {
    local changed_files_text="$1"
    cat <<EOF
请根据下面的需求和最终改动，生成一个简洁明确的 GitLab Merge Request 标题。

要求：
1. 只输出标题文本，不要引号、编号、前缀、解释或 markdown。
2. 中文优先，尽量控制在 30 个字以内。
3. 体现主要结果，不要写“实现功能”“更新代码”这类空泛表述。

需求：
${USER_PROMPT}

改动文件：
${changed_files_text}
EOF
}

build_commit_message_prompt() {
    local changed_files_text="$1"
    local diff_stats_text="$2"
    local summary_text="$3"
    cat <<EOF
请根据下面的信息，生成一条符合 Conventional Commits 规范的 git commit message。

要求：
1. 使用中文。
2. 第一行必须使用 Conventional Commits 格式：<type>: <description>。
3. type 从 feat、fix、refactor、docs、test、build、chore、ci 中选择最合适的一个；如果是新增可交付能力、初始化可运行项目、补充用户可见结果，优先使用 feat。
4. description 简洁明确，尽量控制在 50 个字符内，最多不超过 72 个字符。
5. 如果需要正文，subject 后空一行，再用 1-3 行简短说明“做了什么/为什么”。
6. 最后添加 footer：AI-Generated: true
7. 不要使用 markdown、代码块、引号，也不要包含 Co-authored-by trailer，我会自行追加。

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

cat > /tmp/claude_prompt.txt <<EOF
你在 /workspace 中工作，请直接完成下面的需求，不要先输出规划或步骤清单。

需求:
${USER_PROMPT}

上下文:
- GitLab project id: ${PROJECT_ID}
- Issue IID: ${ISSUE_IID:-N/A (manual task)}
- 当前工作分支: ${BRANCH_NAME}
- 目标分支: ${TARGET_BRANCH}

要求:
1. 直接检查代码库并实施修改。
2. 仅在当前仓库内工作，优先做精确修改，不要引入无关改动。
3. 完成后运行相关验证命令；如果仓库里没有对应命令，就明确说明。
4. 最终输出简短执行摘要，至少包含：
    - 修改了哪些文件
    - 做了什么
    - 运行了哪些验证
5. 不要描述“未跟踪文件”“待提交”“可按需提交”这类提交前状态，默认以已经完成并准备提交的口吻总结结果。
6. 不要要求人工确认，除非你真的被阻塞。
EOF

chmod 644 /tmp/claude_prompt.txt
chown -R codify:codify /workspace /tmp/claude_prompt.txt

export ANTHROPIC_BASE_URL
export ANTHROPIC_API_KEY
export ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN:-${ANTHROPIC_API_KEY}}"
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="${CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC:-1}"
export SANDBOX_MODE=1
export CLAUDE_MAX_TURNS="${CLAUDE_MAX_TURNS:-20}"
export CLAUDE_MODEL="${ANTHROPIC_MODEL}"
FINAL_SUMMARY_CONTENT=""
FINAL_CHANGED_FILES_TEXT=""
FINAL_MR_TITLE=""
FINAL_COMMIT_MESSAGE=""

echo "Claude CLI version: $(/usr/local/bin/claude --version)"
echo "Updating MR with execution status..."
update_mr_description "$(build_running_mr_description)" || true

echo "Starting Claude CLI (streaming mode)..."
set +e
env HOME=/home/codify timeout "${TASK_TIMEOUT:-1800}" su -m -s /bin/bash codify -c \
    'cd /workspace && export PATH="/usr/local/bin:/usr/bin:/bin:${JAVA_HOME}/bin" && /usr/local/bin/ci-claude.sh "$(cat /tmp/claude_prompt.txt)"' \
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

    # Emit machine-parseable usage stats for backend collection
    USAGE_JSON=$(jq -c '.usage // {}' /tmp/claude_result.json 2>/dev/null || echo '{}')
    echo "CODIFY_STATS:${USAGE_JSON}"

    # Emit structured tool calls for backend to store and frontend to render as timeline.
    # Each tool output is truncated to 2000 chars to keep the payload manageable.
    TOOL_CALLS_JSON=$(jq -c '[
      .tool_calls[]? |
      .output = ((.output // "") | if length > 2000 then .[:2000] + "…(truncated)" else . end)
    ]' /tmp/claude_result.json 2>/dev/null || echo '[]')
    echo "CODIFY_TOOL_CALLS:${TOOL_CALLS_JSON}"

    # Extract and emit session ID for backend to store on the Issue
    SESSION_ID=$(jq -r '.session_id // ""' /tmp/claude_result.json 2>/dev/null || echo '')
    if [ -n "${SESSION_ID}" ]; then
        echo "CODIFY_SESSION_ID:${SESSION_ID}"
    fi
fi

if [ $RESULT -ne 0 ]; then
    echo "Claude execution failed with exit code: ${RESULT}"
    exit $RESULT
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
    echo "CODIFY_DIFF:+${ADDITIONS}-${DELETIONS}"

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

    # Remove trailing commas
    NEW_FILES="${NEW_FILES%,}"
    MODIFIED_FILES="${MODIFIED_FILES%,}"
    DELETED_FILES="${DELETED_FILES%,}"

    CHANGED_FILES_TEXT="新增: ${NEW_FILES:-无}
修改: ${MODIFIED_FILES:-无}
删除: ${DELETED_FILES:-无}"
    FINAL_CHANGED_FILES_TEXT="$(build_changed_files_table "${NEW_FILES}" "${MODIFIED_FILES}" "${DELETED_FILES}" "${FINAL_SUMMARY_CONTENT}")"

    COMMIT_DIFF_STATS=$(git diff --cached --stat || echo "0 files changed")
    COMMIT_MESSAGE_PROMPT=$(build_commit_message_prompt "${CHANGED_FILES_TEXT}" "${COMMIT_DIFF_STATS}" "${FINAL_SUMMARY_CONTENT}")
    printf '%s\n' "${COMMIT_MESSAGE_PROMPT}" > /tmp/commit_message_prompt.txt
    chmod 644 /tmp/commit_message_prompt.txt
    chown codify:codify /tmp/commit_message_prompt.txt

    set +e
    GENERATED_COMMIT_MESSAGE=$(env HOME=/home/codify timeout 60 su -m -s /bin/bash codify -c '/usr/local/bin/claude -p --dangerously-skip-permissions --no-session-persistence --output-format text --max-turns 3 --model "${ANTHROPIC_MODEL}" "$(cat /tmp/commit_message_prompt.txt)"' 2>/dev/null)
    COMMIT_MESSAGE_RESULT=$?
    set -e

    if [ ${COMMIT_MESSAGE_RESULT} -eq 0 ]; then
        FINAL_COMMIT_MESSAGE=$(printf '%s\n' "${GENERATED_COMMIT_MESSAGE}" | sed 's/\r$//')
    fi

    if [ -z "${FINAL_COMMIT_MESSAGE}" ]; then
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
        printf '\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>\n'
    } > /tmp/commit_message.txt

    # Create commit
    git commit -F /tmp/commit_message.txt

    # Push to remote using git push
    echo "Pushing to remote..."
    git remote set-url origin "http://${GITLAB_HOST}/${PROJECT_PATH}.git"
    git config --local http.extraHeader "PRIVATE-TOKEN: ${GITLAB_TOKEN}"
    GIT_TERMINAL_PROMPT=0 git push -u origin "${BRANCH_NAME}"

    # Get commit SHA
    COMMIT_SHA=$(git rev-parse HEAD)
    echo "Committed: ${COMMIT_SHA}"
    echo "CODIFY_COMMIT_SHA:${COMMIT_SHA}"

    # MR was already created by backend before worker started.
    # In no-MR mode (TARGET_BRANCH is empty), skip all MR operations.
    MR_WEB_URL=""
    if [ -z "${TARGET_BRANCH:-}" ]; then
        echo "No-MR mode: skipping MR lookup and update"
    elif [ -n "${MR_IID}" ]; then
        echo "Using existing MR: !${MR_IID}"
        MR_WEB_URL=$(curl -s -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
            "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/merge_requests/${MR_IID}" | \
            grep -o '"web_url":"[^"]*"' | cut -d'"' -f4)
    else
        # Fallback: check if MR already exists for this branch
        echo "Checking for existing MR..."
        EXISTING_MR=$(curl -s -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
            "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/merge_requests?state=opened&source_branch=${BRANCH_NAME}" | \
            grep -o '"iid":[0-9]*' | head -1 | cut -d':' -f2)
        if [ -n "$EXISTING_MR" ]; then
            MR_IID="${EXISTING_MR}"
            MR_WEB_URL=$(curl -s -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
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
        TITLE_PROMPT=$(build_mr_title_prompt "${CHANGED_FILES_TEXT}")
        printf '%s\n' "${TITLE_PROMPT}" > /tmp/mr_title_prompt.txt
        chmod 644 /tmp/mr_title_prompt.txt
        chown codify:codify /tmp/mr_title_prompt.txt

        set +e
        GENERATED_MR_TITLE=$(env HOME=/home/codify timeout 60 su -m -s /bin/bash codify -c '/usr/local/bin/claude -p --dangerously-skip-permissions --no-session-persistence --output-format text --max-turns 3 --model "${ANTHROPIC_MODEL}" "$(cat /tmp/mr_title_prompt.txt)"' 2>/dev/null)
        TITLE_RESULT=$?
        set -e

        if [ ${TITLE_RESULT} -eq 0 ]; then
            FINAL_MR_TITLE=$(printf '%s' "${GENERATED_MR_TITLE}" | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g; s/^ *//; s/ *$//')
            FINAL_MR_TITLE="${FINAL_MR_TITLE:0:120}"
        fi

        if [ -z "${FINAL_MR_TITLE}" ]; then
            FINAL_MR_TITLE="AI: ${USER_PROMPT:0:60}"
        fi

        echo "CODIFY_MR_TITLE:${FINAL_MR_TITLE}"

        if [ -n "${FINAL_SUMMARY_CONTENT}" ]; then
            update_mr "${FINAL_MR_TITLE}" "$(build_completed_mr_description "${FINAL_SUMMARY_CONTENT}" "${FINAL_CHANGED_FILES_TEXT}")" || true
        else
            update_mr "${FINAL_MR_TITLE}" "" || true
        fi
    fi

    echo "========================================"
    echo "Task completed successfully!"
    echo "========================================"
else
    echo "No changes made by Claude CLI"
    if [ -z "${TARGET_BRANCH:-}" ]; then
        echo "No-MR mode: task completed without code changes"
        echo "========================================"
        echo "Task completed successfully!"
        echo "========================================"
        exit 0
    fi
    exit 1
fi
