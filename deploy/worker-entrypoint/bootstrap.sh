
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
CODIFY_GIT_CLONE_DEPTH="${CODIFY_GIT_CLONE_DEPTH:-}"
CODIFY_GIT_CLONE_FILTER="${CODIFY_GIT_CLONE_FILTER:-}"

if [ -n "${CODIFY_GIT_CLONE_DEPTH}" ]; then
    case "${CODIFY_GIT_CLONE_DEPTH}" in
        *[!0-9]* | 0)
            echo "ERROR: CODIFY_GIT_CLONE_DEPTH must be an integer between 1 and 10000"
            exit 1
            ;;
    esac
    if [ "${CODIFY_GIT_CLONE_DEPTH}" -gt 10000 ]; then
        echo "ERROR: CODIFY_GIT_CLONE_DEPTH must be an integer between 1 and 10000"
        exit 1
    fi
fi

case "${CODIFY_GIT_CLONE_FILTER}" in
    "" | "blob:none") ;;
    *)
        echo "ERROR: CODIFY_GIT_CLONE_FILTER must be empty or blob:none"
        exit 1
        ;;
esac
export CODIFY_GIT_CLONE_DEPTH CODIFY_GIT_CLONE_FILTER

ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-http://localhost:11434/v1}"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-claude-sonnet-4-20250514}"
APPEND_SYSTEM_PROMPT="${APPEND_SYSTEM_PROMPT:-}"
CODIFY_RUNTIME_DIR="/tmp/codify-runtime"
CODIFY_ARTIFACT_DIR="${CODIFY_RUNTIME_DIR}/artifacts"
CODIFY_WORKER_PRE_SCRIPT_FILE="${CODIFY_RUNTIME_DIR}/worker-pre-script.sh"
CODIFY_WORKER_POST_SCRIPT_FILE="${CODIFY_RUNTIME_DIR}/worker-post-script.sh"
CODIFY_ARTIFACT_HELPER="${ENTRYPOINT_LIB_DIR}/artifacts.py"
export CODIFY_RUNTIME_DIR CODIFY_ARTIFACT_DIR
mkdir -p "${CODIFY_RUNTIME_DIR}" "${CODIFY_RUNTIME_DIR}/harness-events" \
    /workspace /home/codify /root
codify_chown /workspace /home/codify
if [ -r "${CODIFY_ARTIFACT_HELPER}" ] && command -v python3 >/dev/null 2>&1; then
    if ! python3 "${CODIFY_ARTIFACT_HELPER}" prepare \
        --uid "${CODIFY_RUN_UID}" --gid "${CODIFY_RUN_GID}"; then
        echo "WARNING: Could not prepare task artifact policy; using base archive behavior"
        rm -f "${CODIFY_RUNTIME_DIR}/artifact-policy.json"
    fi
else
    echo "WARNING: Task artifact helper is unavailable; using base archive behavior"
    rm -f "${CODIFY_RUNTIME_DIR}/artifact-policy.json"
fi
# The uploaded bundle may inherit a restrictive control-plane umask. It is
# task-local and bounded, so normalize it once before the unprivileged runtime
# reads CI inputs or custom scripts.
codify_chown -R "${CODIFY_RUNTIME_DIR}"
# Keep the fixed runtime path non-replaceable while allowing task-local files
# to be created. The EXIT helper removes write access before sealing.
chown 0:0 "${CODIFY_RUNTIME_DIR}"
# The runtime dir is shared by the root orchestrator and the model identity.
# A sticky world-writable dir makes the kernel's fs.protected_regular deny
# cross-uid appends (even for root), which breaks the legacy mixed-identity
# writer. The Harness keeps the sticky bit: there only root writes the runtime
# dir (the model identity never does), so the audit stream stays sealed.
if [ -n "${CODIFY_HARNESS_KEY:-}" ]; then
    chmod 1777 "${CODIFY_RUNTIME_DIR}"
else
    chmod 777 "${CODIFY_RUNTIME_DIR}"
fi
chmod 755 "${CODIFY_RUNTIME_DIR}/harness-events"
touch "${CODIFY_RUNTIME_DIR}/event.jsonl" \
    "${CODIFY_RUNTIME_DIR}/harness-events/claude.jsonl" \
    "${CODIFY_RUNTIME_DIR}/console.log"
if [ ! -s "${CODIFY_RUNTIME_DIR}/harness-result.json" ]; then
    printf '{}\n' > "${CODIFY_RUNTIME_DIR}/harness-result.json"
fi
# Canonical, raw-Harness, result, and console evidence is owned by the root
# orchestration process. The model runs with the codify identity and must not
# be able to rewrite the audit stream directly.
chown 0:0 "${CODIFY_RUNTIME_DIR}/event.jsonl" \
    "${CODIFY_RUNTIME_DIR}/harness-events/claude.jsonl" \
    "${CODIFY_RUNTIME_DIR}/harness-result.json" \
    "${CODIFY_RUNTIME_DIR}/console.log"
chmod 644 "${CODIFY_RUNTIME_DIR}/event.jsonl" \
    "${CODIFY_RUNTIME_DIR}/harness-events/claude.jsonl" \
    "${CODIFY_RUNTIME_DIR}/harness-result.json" \
    "${CODIFY_RUNTIME_DIR}/console.log"
if [ -d /opt/codify-issue-meta ]; then
    printf '{"project_id":%s,"issue_id":%s,"worker_profile_id":%s}\n' \
        "${PROJECT_ID}" "${ISSUE_ID}" "${CODIFY_WORKER_PROFILE_ID:-null}" \
        > /opt/codify-issue-meta/workspace.json
    if [ -n "${ISSUE_ID}" ] && [ -n "${CODIFY_WORKER_PROFILE_ID:-}" ]; then
        printf '%s:%s:%s\n' "${PROJECT_ID}" "${ISSUE_ID}" "${CODIFY_WORKER_PROFILE_ID}" \
            > /opt/codify-issue-meta/owner
        codify_chown /opt/codify-issue-meta/owner
    fi
    # Workspaces created by older releases could contain root-owned Git metadata
    # because final add/commit/push operations ran as root. Normalize such a tree
    # once, then keep the marker so later tasks retain the cheap top-level chown.
    WORKSPACE_OWNERSHIP_MARKER="/opt/codify-issue-meta/ownership"
    EXPECTED_WORKSPACE_OWNER="${CODIFY_RUN_UID}:${CODIFY_RUN_GID}"
    CURRENT_WORKSPACE_OWNER=""
    if [ -f "${WORKSPACE_OWNERSHIP_MARKER}" ]; then
        CURRENT_WORKSPACE_OWNER=$(cat "${WORKSPACE_OWNERSHIP_MARKER}" 2>/dev/null || true)
    fi
    if [ "${CURRENT_WORKSPACE_OWNER}" != "${EXPECTED_WORKSPACE_OWNER}" ]; then
        echo "Normalizing persistent workspace ownership for ${EXPECTED_WORKSPACE_OWNER}..."
        for persistent_path in /workspace /home/codify/.claude /opt/codify-issue-shared; do
            if [ -d "${persistent_path}" ]; then
                codify_chown -R "${persistent_path}"
            fi
        done
    fi
    printf '%s\n' "${EXPECTED_WORKSPACE_OWNER}" > "${WORKSPACE_OWNERSHIP_MARKER}"
    codify_chown \
        /opt/codify-issue-meta \
        /opt/codify-issue-meta/workspace.json \
        "${WORKSPACE_OWNERSHIP_MARKER}"
fi
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
REPOSITORY_PREPARATION_FILE="${CODIFY_RUNTIME_DIR}/repository-preparation.json"
MERMAID_SUMMARY_VALIDATE="${MERMAID_SUMMARY_VALIDATE:-true}"
MERMAID_SUMMARY_REPAIR_ATTEMPTS="${MERMAID_SUMMARY_REPAIR_ATTEMPTS:-2}"
MERMAID_SUMMARY_STRICT="${MERMAID_SUMMARY_STRICT:-false}"
RUNTIME_ARCHIVE_CREATED=0

create_runtime_archive() {
    if [ "${RUNTIME_ARCHIVE_CREATED}" -eq 1 ]; then
        return 0
    fi

    local archive_name="task-${TASK_ID:-0}-runtime-archive.tar.gz"
    local archive_path="${CODIFY_RUNTIME_DIR}/${archive_name}"
    local archive_part_path="${archive_path}.part"
    local archive_max_bytes=$((640 * 1024 * 1024))
    if [ -r "${CODIFY_ARTIFACT_HELPER}" ] && command -v python3 >/dev/null 2>&1; then
        if python3 "${CODIFY_ARTIFACT_HELPER}" archive --task-id "${TASK_ID:-0}"; then
            echo "Archive created: ${archive_path}"
            RUNTIME_ARCHIVE_CREATED=1
            return 0
        fi
        echo "WARNING: Artifact-aware archive creation failed; creating base runtime archive"
    fi

    local archive_files=()
    local candidate
    for candidate in \
        event.jsonl \
        harness-events \
        harness-result.json \
        runtime.json \
        console.log \
        delivery-summary.md \
        delivery-summary-validation.json \
        repository-preparation.json \
        artifacts-validation.json
    do
        [ -e "${CODIFY_RUNTIME_DIR}/${candidate}" ] && archive_files+=("${candidate}")
    done
    if [ "${#archive_files[@]}" -eq 0 ]; then
        return 0
    fi

    rm -f "${archive_part_path}" 2>/dev/null || true
    local -a archive_pipeline_status=()
    if tar -czf - -C "${CODIFY_RUNTIME_DIR}" "${archive_files[@]}" 2>/dev/null \
        | head -c "$((archive_max_bytes + 1))" > "${archive_part_path}"; then
        archive_pipeline_status=("${PIPESTATUS[@]}")
    else
        archive_pipeline_status=("${PIPESTATUS[@]}")
    fi
    local archive_status="${archive_pipeline_status[0]:-1}"
    local limiter_status="${archive_pipeline_status[1]:-1}"
    local archive_size=0
    if [ -f "${archive_part_path}" ]; then
        archive_size=$(wc -c < "${archive_part_path}")
    fi
    if [ "${archive_status}" -eq 0 ] \
        && [ "${limiter_status}" -eq 0 ] \
        && [ "${archive_size}" -le "${archive_max_bytes}" ]; then
        if python3 -c 'import os,sys; os.replace(sys.argv[1], sys.argv[2])' \
            "${archive_part_path}" "${archive_path}" 2>/dev/null; then
            echo "Archive created: ${archive_path}"
            RUNTIME_ARCHIVE_CREATED=1
            return 0
        fi
    fi
    rm -f "${archive_part_path}" "${archive_path}" 2>/dev/null || true
    if [ "${archive_size}" -gt "${archive_max_bytes}" ]; then
        echo "WARNING: Base runtime archive exceeds the 640 MiB hard limit; archive omitted"
    else
        echo "WARNING: Base runtime archive creation failed; archive omitted"
    fi
    RUNTIME_ARCHIVE_CREATED=1
    return 0
}

codify_finalize_on_exit() {
    local exit_code="${1:-0}"
    if declare -F repo_finalize_preparation_on_exit >/dev/null 2>&1; then
        repo_finalize_preparation_on_exit "${exit_code}" || true
    fi
    if declare -F codify_harness_finalize_attempt >/dev/null 2>&1 \
        && [ -n "${CODIFY_ATTEMPT_ID:-}" ]; then
        codify_harness_finalize_attempt "${exit_code}" || true
    fi
    # Detach the shell from the console FIFO and wait for tee to persist every
    # buffered line before the archive snapshots console.log.
    exec >/dev/null 2>&1
    if [ -n "${CONSOLE_TEE_PID:-}" ]; then
        wait "${CONSOLE_TEE_PID}" 2>/dev/null || true
    fi
    create_runtime_archive || true
}

trap 'codify_finalize_on_exit "$?"' EXIT
touch "${CONSOLE_LOG}"
chown 0:0 "${CONSOLE_LOG}"
chmod 644 "${CONSOLE_LOG}"

# Persist the same human-readable console stream that Docker exposes while the
# task is running. TaskRawLogChunk tails this file after completion.
CONSOLE_TEE_DIR=$(mktemp -d)
CONSOLE_TEE_PIPE="${CONSOLE_TEE_DIR}/console.pipe"
mkfifo "${CONSOLE_TEE_PIPE}"
tee -a "${CONSOLE_LOG}" < "${CONSOLE_TEE_PIPE}" &
CONSOLE_TEE_PID=$!
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
export BASE_BRANCH BRANCH_NAME

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
export GIT_REPO_URL

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
