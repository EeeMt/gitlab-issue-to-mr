
# Required configuration, console capture, TLS, repository clone, and branch checkout.
# Receives task parameters from environment variables

# Required environment variables
GITLAB_URL="${GITLAB_URL:?Missing GITLAB_URL}"
GITLAB_TOKEN="${GITLAB_TOKEN:?Missing GITLAB_TOKEN}"
PROJECT_ID="${PROJECT_ID:?Missing PROJECT_ID}"
BRANCH_NAME="${BRANCH_NAME:?Missing BRANCH_NAME}"
USER_PROMPT="${USER_PROMPT:?Missing USER_PROMPT}"
CODIFY_TASK_PROMPT_FILE="${CODIFY_TASK_PROMPT_FILE:?Missing CODIFY_TASK_PROMPT_FILE}"

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
CODIFY_WORKER_PRE_SCRIPT_FILE="${CODIFY_RUNTIME_DIR}/worker-pre-script.sh"
CODIFY_WORKER_POST_SCRIPT_FILE="${CODIFY_RUNTIME_DIR}/worker-post-script.sh"
export CODIFY_RUNTIME_DIR
mkdir -p "${CODIFY_RUNTIME_DIR}" /home/codify /root
codify_chown /home/codify "${CODIFY_RUNTIME_DIR}"
if [ -d /home/codify/.m2 ]; then
    codify_chown /home/codify/.m2 2>/dev/null || true
fi
if [ -d /home/codify/.m2/repository ]; then
    codify_chown /home/codify/.m2/repository 2>/dev/null || true
fi
prepare_worker_script_file() {
    local script_path="$1"
    if [ ! -f "${script_path}" ]; then
        return 0
    fi
    if codify_chown "${script_path}" 2>/dev/null; then
        chmod 700 "${script_path}" 2>/dev/null || true
    else
        chmod 755 "${script_path}" 2>/dev/null || true
    fi
}
prepare_worker_script_file "${CODIFY_WORKER_PRE_SCRIPT_FILE}"
prepare_worker_script_file "${CODIFY_WORKER_POST_SCRIPT_FILE}"
CONSOLE_LOG="${CODIFY_RUNTIME_DIR}/console.log"
DELIVERY_SUMMARY_FILE="${CODIFY_RUNTIME_DIR}/delivery-summary.md"
DELIVERY_SUMMARY_VALIDATION_FILE="${CODIFY_RUNTIME_DIR}/delivery-summary-validation.json"
MERMAID_SUMMARY_VALIDATE="${MERMAID_SUMMARY_VALIDATE:-true}"
MERMAID_SUMMARY_REPAIR_ATTEMPTS="${MERMAID_SUMMARY_REPAIR_ATTEMPTS:-2}"
MERMAID_SUMMARY_STRICT="${MERMAID_SUMMARY_STRICT:-false}"
touch "${CONSOLE_LOG}"
codify_chown "${CONSOLE_LOG}"

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
echo "Pre Script:     $([ -s "$CODIFY_WORKER_PRE_SCRIPT_FILE" ] && echo 'set' || echo 'none')"
echo "Post Script:    $([ -s "$CODIFY_WORKER_POST_SCRIPT_FILE" ] && echo 'set' || echo 'none')"
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
    if [ -z "${CODIFY_KIT_HOME}" ]; then
        cp "${CUSTOM_CA_BUNDLE}" /usr/local/share/ca-certificates/custom-ca.crt
        update-ca-certificates --fresh >/dev/null 2>&1 || true
    fi
    git config --global http.sslVerify true
    git config --global http.sslCAInfo "${CUSTOM_CA_BUNDLE}"
    git config --file "${CODIFY_GIT_CONFIG}" http.sslVerify true
    git config --file "${CODIFY_GIT_CONFIG}" http.sslCAInfo "${CUSTOM_CA_BUNDLE}"
    # Claude CLI (Node.js) picks up extra CA certs from this env var
    export NODE_EXTRA_CA_CERTS="${CUSTOM_CA_BUNDLE}"
    # Python requests / httpx pick this up automatically
    export REQUESTS_CA_BUNDLE="${CUSTOM_CA_BUNDLE}"
    export SSL_CERT_FILE="${CUSTOM_CA_BUNDLE}"
    # Preserve legacy baked-image behavior. Mounted runtime images own their JDK
    # truststore and can update it from a profile pre-script when required.
    if [ -z "${CODIFY_KIT_HOME}" ] && [ -n "${JAVA_HOME}" ] && [ -x "${JAVA_HOME}/bin/keytool" ]; then
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
codify_chown /home/codify/.git-credentials

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
codify_chown "${CODIFY_GIT_CONFIG}"

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
