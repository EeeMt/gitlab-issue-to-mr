# Repository clone/fetch policy, workspace reuse, branch checkout, and preparation telemetry.

repo_clone() {
    local use_filter="$1"
    if [ -n "${CODIFY_GIT_CLONE_DEPTH}" ]; then
        if [ "${use_filter}" = "true" ]; then
            codify_run_shell 'git clone --depth "${CODIFY_GIT_CLONE_DEPTH}" --filter="${CODIFY_GIT_CLONE_FILTER}" --single-branch --branch "${BASE_BRANCH}" "${GIT_REPO_URL}" /workspace'
        else
            codify_run_shell 'git clone --depth "${CODIFY_GIT_CLONE_DEPTH}" --single-branch --branch "${BASE_BRANCH}" "${GIT_REPO_URL}" /workspace'
        fi
    elif [ "${use_filter}" = "true" ]; then
        codify_run_shell 'git clone --filter="${CODIFY_GIT_CLONE_FILTER}" "${GIT_REPO_URL}" /workspace'
    else
        codify_run_shell 'git clone "${GIT_REPO_URL}" /workspace'
    fi
}

repo_filter_was_ignored() {
    local clone_log="$1"
    grep -Eiq \
        'filtering not recognized by server|server does not support filter|filtering is not supported by.*server' \
        "${clone_log}"
}

repo_clear_ignored_filter_config() {
    # Git records promisor/filter configuration even when an older server returns success
    # after ignoring the requested filter. The clone is complete in that case, so remove the
    # misleading local markers and let later fetches use normal full-object semantics.
    codify_run_shell 'cd /workspace && git config --unset-all remote.origin.promisor || true'
    codify_run_shell 'cd /workspace && git config --unset-all remote.origin.partialclonefilter || true'
    codify_run_shell 'cd /workspace && git config --unset-all extensions.partialClone || true'
}

repo_fetch_work_branch() {
    if [ -n "${CODIFY_GIT_CLONE_DEPTH}" ]; then
        codify_run_shell 'cd /workspace && git fetch --depth "${CODIFY_GIT_CLONE_DEPTH}" origin "+refs/heads/${BRANCH_NAME}:refs/remotes/origin/${BRANCH_NAME}"'
    else
        codify_run_shell 'cd /workspace && git fetch origin "+refs/heads/${BRANCH_NAME}:refs/remotes/origin/${BRANCH_NAME}"'
    fi
}

repo_read_remote_refs() {
    local refs
    refs=$(codify_run_shell 'git ls-remote --symref "${GIT_REPO_URL}" HEAD "refs/heads/${BASE_BRANCH}" "refs/heads/${BRANCH_NAME}"')
    REPO_REMOTE_DEFAULT_BRANCH=$(
        printf '%s\n' "${refs}" \
            | awk '$1 == "ref:" && $3 == "HEAD" {
                sub(/^refs\/heads\//, "", $2)
                print $2
                exit
            }'
    )
    REPO_REMOTE_HEAD_SHA=$(
        printf '%s\n' "${refs}" | awk '$2 == "HEAD" {print $1; exit}'
    )
    REPO_REMOTE_BASE_SHA=$(
        printf '%s\n' "${refs}" \
            | awk -v ref="refs/heads/${BASE_BRANCH}" \
                '$1 != "ref:" && $2 == ref {print $1; exit}'
    )
    REPO_REMOTE_WORK_SHA=$(
        printf '%s\n' "${refs}" \
            | awk -v ref="refs/heads/${BRANCH_NAME}" \
                '$1 != "ref:" && $2 == ref {print $1; exit}'
    )
    if [ -n "${REPO_REMOTE_WORK_SHA}" ]; then
        REPO_REMOTE_WORK_BRANCH="true"
    fi
    repo_log "remote_refs base=${REPO_REMOTE_BASE_SHA:-missing} work=${REPO_REMOTE_WORK_SHA:-missing} default=${REPO_REMOTE_DEFAULT_BRANCH:-unknown}"
}

repo_resolve_remote_base() {
    if [ -n "${REPO_REMOTE_BASE_SHA}" ]; then
        return 0
    fi
    if [ -z "${REPO_REMOTE_DEFAULT_BRANCH}" ] || [ -z "${REPO_REMOTE_HEAD_SHA}" ]; then
        echo "ERROR: Cannot resolve base branch '${BASE_BRANCH}' or the remote default branch"
        exit 1
    fi

    repo_log "warning base_branch=${BASE_BRANCH} unavailable; using remote default"
    repo_log "base_branch_fallback from=${BASE_BRANCH} to=${REPO_REMOTE_DEFAULT_BRANCH}"
    BASE_BRANCH="${REPO_REMOTE_DEFAULT_BRANCH}"
    REPO_REMOTE_BASE_SHA="${REPO_REMOTE_HEAD_SHA}"
    export BASE_BRANCH
}

repo_fetch_selected_refs() {
    if [ -n "${CODIFY_GIT_CLONE_DEPTH}" ]; then
        if [ -n "${REPO_REMOTE_WORK_SHA}" ] && [ "${BASE_BRANCH}" != "${BRANCH_NAME}" ]; then
            codify_run_shell 'cd /workspace && git fetch --depth "${CODIFY_GIT_CLONE_DEPTH}" origin "+refs/heads/${BASE_BRANCH}:refs/remotes/origin/${BASE_BRANCH}" "+refs/heads/${BRANCH_NAME}:refs/remotes/origin/${BRANCH_NAME}"'
        else
            codify_run_shell 'cd /workspace && git fetch --depth "${CODIFY_GIT_CLONE_DEPTH}" origin "+refs/heads/${BASE_BRANCH}:refs/remotes/origin/${BASE_BRANCH}"'
        fi
    else
        if [ -n "${REPO_REMOTE_WORK_SHA}" ] && [ "${BASE_BRANCH}" != "${BRANCH_NAME}" ]; then
            codify_run_shell 'cd /workspace && git fetch origin "+refs/heads/${BASE_BRANCH}:refs/remotes/origin/${BASE_BRANCH}" "+refs/heads/${BRANCH_NAME}:refs/remotes/origin/${BRANCH_NAME}"'
        else
            codify_run_shell 'cd /workspace && git fetch origin "+refs/heads/${BASE_BRANCH}:refs/remotes/origin/${BASE_BRANCH}"'
        fi
    fi

    REPO_REMOTE_BASE_SHA=$(codify_run_shell 'cd /workspace && git rev-parse "refs/remotes/origin/${BASE_BRANCH}"')
    if [ -n "${REPO_REMOTE_WORK_SHA}" ]; then
        REPO_REMOTE_WORK_SHA=$(codify_run_shell 'cd /workspace && git rev-parse "refs/remotes/origin/${BRANCH_NAME}"')
    fi
    repo_log "fetch refs=base${REPO_REMOTE_WORK_SHA:+,work} depth=${CODIFY_GIT_CLONE_DEPTH:-full}"
}

repo_classify_work_branch() {
    REPO_LOCAL_WORK_SHA=$(codify_run_shell 'cd /workspace && git rev-parse "refs/heads/${BRANCH_NAME}"')

    if [ -z "${REPO_REMOTE_WORK_SHA}" ]; then
        if [ -n "${REPO_PREVIOUS_REMOTE_WORK_SHA}" ]; then
            REPO_WORK_BRANCH_RELATION="remote_deleted"
        else
            REPO_WORK_BRANCH_RELATION="remote_missing"
        fi
    elif [ "${REPO_LOCAL_WORK_SHA}" = "${REPO_REMOTE_WORK_SHA}" ]; then
        REPO_WORK_BRANCH_RELATION="same"
    elif codify_run_shell 'cd /workspace && git merge-base --is-ancestor "refs/heads/${BRANCH_NAME}" "refs/remotes/origin/${BRANCH_NAME}"'; then
        REPO_WORK_BRANCH_RELATION="remote_ahead"
    elif codify_run_shell 'cd /workspace && git merge-base --is-ancestor "refs/remotes/origin/${BRANCH_NAME}" "refs/heads/${BRANCH_NAME}"'; then
        if [ -z "${REPO_PREVIOUS_REMOTE_WORK_SHA}" ] \
            || [ "${REPO_PREVIOUS_REMOTE_WORK_SHA}" = "${REPO_REMOTE_WORK_SHA}" ] \
            || codify_run_shell 'cd /workspace && git merge-base --is-ancestor "${REPO_PREVIOUS_REMOTE_WORK_SHA}" "${REPO_REMOTE_WORK_SHA}"'; then
            # The remote either stayed put or advanced into the local unpublished history.
            # In both cases the local branch remains a safe fast-forward of the remote tip.
            REPO_WORK_BRANCH_RELATION="local_ahead"
        elif codify_run_shell 'cd /workspace && git merge-base --is-ancestor "${REPO_REMOTE_WORK_SHA}" "${REPO_PREVIOUS_REMOTE_WORK_SHA}"'; then
            REPO_WORK_BRANCH_RELATION="remote_rewound"
        elif [ "$(codify_run_shell 'cd /workspace && git rev-parse --is-shallow-repository')" = "true" ]; then
            REPO_WORK_BRANCH_RELATION="unknown_shallow"
        else
            # The remote moved sideways to another commit already contained by the local
            # branch. Treat that non-fast-forward remote rewrite conservatively.
            REPO_WORK_BRANCH_RELATION="remote_rewound"
        fi
    elif codify_run_shell 'cd /workspace && git merge-base "refs/remotes/origin/${BRANCH_NAME}" "refs/heads/${BRANCH_NAME}"' > /dev/null; then
        REPO_WORK_BRANCH_RELATION="diverged"
    elif [ "$(codify_run_shell 'cd /workspace && git rev-parse --is-shallow-repository')" = "true" ]; then
        REPO_WORK_BRANCH_RELATION="unknown_shallow"
    else
        REPO_WORK_BRANCH_RELATION="diverged"
    fi
}

repo_sync_local_work_branch() {
    local dirty="$1"
    repo_classify_work_branch

    case "${REPO_WORK_BRANCH_RELATION}" in
        same)
            REPO_SYNC_ACTION="none"
            ;;
        remote_missing)
            REPO_SYNC_ACTION="preserve_local"
            repo_log "warning work_branch=${BRANCH_NAME} remote=missing; preserving local branch"
            ;;
        remote_deleted)
            repo_log "error work_branch=${BRANCH_NAME} relation=remote_deleted previous_remote=${REPO_PREVIOUS_REMOTE_WORK_SHA} local=${REPO_LOCAL_WORK_SHA}"
            echo "ERROR: Remote work branch was deleted after the workspace last observed it; refusing to recreate it automatically"
            exit 1
            ;;
        local_ahead)
            REPO_SYNC_ACTION="preserve_local"
            ;;
        remote_rewound)
            repo_log "error work_branch=${BRANCH_NAME} relation=remote_rewound previous_remote=${REPO_PREVIOUS_REMOTE_WORK_SHA} current_remote=${REPO_REMOTE_WORK_SHA} local=${REPO_LOCAL_WORK_SHA}"
            echo "ERROR: Remote work branch was rewound after the workspace last observed it; refusing to restore removed commits"
            exit 1
            ;;
        remote_ahead)
            if [ -n "${dirty}" ]; then
                repo_log "error work_branch=${BRANCH_NAME} relation=remote_ahead workspace=dirty local=${REPO_LOCAL_WORK_SHA} remote=${REPO_REMOTE_WORK_SHA}"
                echo "ERROR: Remote work branch advanced while the persistent workspace has uncommitted changes; refusing to overwrite local work"
                exit 1
            fi
            codify_run_shell 'cd /workspace && git merge --ff-only "refs/remotes/origin/${BRANCH_NAME}"'
            REPO_SYNC_ACTION="fast_forward"
            ;;
        unknown_shallow)
            repo_log "error work_branch=${BRANCH_NAME} relation=unknown_shallow local=${REPO_LOCAL_WORK_SHA} remote=${REPO_REMOTE_WORK_SHA}"
            echo "ERROR: Cannot prove the local and remote work-branch relationship within the configured shallow history"
            exit 1
            ;;
        diverged)
            repo_log "error work_branch=${BRANCH_NAME} relation=diverged local=${REPO_LOCAL_WORK_SHA} remote=${REPO_REMOTE_WORK_SHA}"
            echo "ERROR: Local and remote work branches have diverged; refusing to merge or overwrite remote changes"
            exit 1
            ;;
    esac

    repo_log "sync work_branch=${BRANCH_NAME} relation=${REPO_WORK_BRANCH_RELATION} action=${REPO_SYNC_ACTION} dirty=$([ -n "${dirty}" ] && printf true || printf false) local=${REPO_LOCAL_WORK_SHA} remote=${REPO_REMOTE_WORK_SHA:-missing}"
}

REPO_PREPARE_STARTED_MS=$(repo_now_ms)
REPO_PREPARATION_ACTIVE=1
REPO_PREPARATION_ARTIFACT_WRITTEN=0
REPO_PREPARATION_PHASE="initialize"
REPO_WORKSPACE_STATE="new"
REPO_ACTION="clone"
REPO_FALLBACK=""
REPO_REMOTE_WORK_BRANCH="false"
REPO_REMOTE_DEFAULT_BRANCH=""
REPO_REMOTE_HEAD_SHA=""
REPO_REMOTE_BASE_SHA=""
REPO_REMOTE_WORK_SHA=""
REPO_PREVIOUS_REMOTE_WORK_SHA=""
REPO_LOCAL_WORK_SHA=""
REPO_WORK_BRANCH_RELATION=""
REPO_SYNC_ACTION=""
REPO_REQUESTED_STRATEGY="full"
export REPO_REMOTE_WORK_SHA REPO_PREVIOUS_REMOTE_WORK_SHA
[ -n "${CODIFY_GIT_CLONE_DEPTH}" ] && REPO_REQUESTED_STRATEGY="shallow"
REPO_REQUESTED_FILTER="${CODIFY_GIT_CLONE_FILTER:-none}"

# Clone or reuse repository with authentication.
if [ -d /workspace/.git ]; then
    REPO_PREPARATION_PHASE="fetch"
    REPO_WORKSPACE_STATE="reused"
    REPO_ACTION="fetch"
    repo_log "prepare workspace=reused strategy=${REPO_REQUESTED_STRATEGY} depth=${CODIFY_GIT_CLONE_DEPTH:-full} filter=${REPO_REQUESTED_FILTER}"
    codify_run_shell 'cd /workspace && git remote set-url origin "${GIT_REPO_URL}"'
    # Unlike rev-parse, show-ref does not print an unresolved ref before returning failure.
    # Keeping stdout empty is essential here: a non-empty value means this workspace really
    # observed the remote work branch during an earlier run.
    REPO_PREVIOUS_REMOTE_WORK_SHA=$(
        codify_run_shell 'cd /workspace && git show-ref --verify --hash "refs/remotes/origin/${BRANCH_NAME}"' \
            2>/dev/null || true
    )
    repo_read_remote_refs
    repo_resolve_remote_base
    repo_fetch_selected_refs
else
    REPO_PREPARATION_PHASE="clone"
    repo_log "prepare workspace=new strategy=${REPO_REQUESTED_STRATEGY} depth=${CODIFY_GIT_CLONE_DEPTH:-full} filter=${REPO_REQUESTED_FILTER}"

    # A missing .git directory does not prove that a persistent workspace is disposable.
    # Preserve any interrupted or manually recovered files and require explicit cleanup.
    if [ -d /workspace ] \
        && find /workspace -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
        repo_log "error workspace=nonempty git_metadata=missing; refusing clone"
        echo "ERROR: /workspace contains files but is not a Git repository; refusing to overwrite it"
        exit 1
    fi

    # ``--depth`` implies single-branch. Read HEAD, base and work refs in one request so the
    # clone can resolve a deleted base and recover an existing Issue branch without duplicate
    # remote probes.
    if [ -n "${CODIFY_GIT_CLONE_DEPTH}" ]; then
        repo_read_remote_refs
        repo_resolve_remote_base
    fi

    if [ -n "${CODIFY_GIT_CLONE_FILTER}" ]; then
        REPO_CLONE_LOG_DIR="${CODIFY_RUNTIME_DIR:-/tmp/codify-runtime}"
        mkdir -p "${REPO_CLONE_LOG_DIR}"
        CLONE_ATTEMPT_LOG=$(mktemp "${REPO_CLONE_LOG_DIR}/repository-clone.XXXXXX")
        set +e
        repo_clone true 2>&1 | tee "${CLONE_ATTEMPT_LOG}"
        CLONE_RESULT="${PIPESTATUS[0]}"
        set -e
        if [ "${CLONE_RESULT}" -ne 0 ]; then
            repo_log "warning filter=${CODIFY_GIT_CLONE_FILTER} clone_failed exit=${CLONE_RESULT}"
            repo_log "fallback retrying clone without object filter"
            REPO_FALLBACK="filter_disabled"
            # The workspace was known-empty before clone. Remove only files left by that
            # failed attempt so the same bounded target can be retried safely.
            find /workspace -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
            rm -f "${CLONE_ATTEMPT_LOG}"
            CLONE_ATTEMPT_LOG=""
            repo_clone false
        elif repo_filter_was_ignored "${CLONE_ATTEMPT_LOG}"; then
            REPO_FALLBACK="filter_ignored"
            repo_log "warning filter=${CODIFY_GIT_CLONE_FILTER} ignored_by_server; continuing with full objects"
            repo_clear_ignored_filter_config
        fi
        [ -z "${CLONE_ATTEMPT_LOG}" ] || rm -f "${CLONE_ATTEMPT_LOG}"
    else
        repo_clone false
    fi

    if [ -z "${CODIFY_GIT_CLONE_DEPTH}" ] \
        && codify_run_shell 'cd /workspace && git show-ref --verify --quiet "refs/remotes/origin/${BRANCH_NAME}"'; then
        REPO_REMOTE_WORK_BRANCH="true"
        REPO_REMOTE_WORK_SHA=$(codify_run_shell 'cd /workspace && git rev-parse "refs/remotes/origin/${BRANCH_NAME}"')
    fi
fi

# A cleaned/expired workspace may still have a remote Issue branch. The same is true when
# reusing a shallow single-branch clone left between clone and checkout by an interrupted task.
# Fetch it explicitly or checkout would incorrectly recreate it from base.
if [ "${REPO_WORKSPACE_STATE}" = "new" ] \
    && [ -n "${CODIFY_GIT_CLONE_DEPTH}" ] \
    && [ -n "${REPO_REMOTE_WORK_SHA}" ]; then
    repo_log "fetching existing work branch=${BRANCH_NAME} depth=${CODIFY_GIT_CLONE_DEPTH} requested_filter=${REPO_REQUESTED_FILTER}"
    repo_fetch_work_branch
fi
cd /workspace

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
REPO_PREPARATION_PHASE="checkout"
WORKSPACE_CURRENT_BRANCH=$(codify_run_shell 'cd /workspace && git rev-parse --abbrev-ref HEAD' 2>/dev/null || echo "")
if [ -n "${WORKSPACE_CURRENT_BRANCH}" ] && [ "${WORKSPACE_CURRENT_BRANCH}" != "HEAD" ] && [ "${WORKSPACE_CURRENT_BRANCH}" != "${BRANCH_NAME}" ]; then
    WORKSPACE_DIRTY=$(codify_run_shell 'cd /workspace && git status --porcelain' || true)
    if [ -n "${WORKSPACE_DIRTY}" ]; then
        echo "ERROR: Workspace has uncommitted changes on branch ${WORKSPACE_CURRENT_BRANCH}, cannot switch to ${BRANCH_NAME}"
        exit 1
    fi
fi

echo "Checking out branch: ${BRANCH_NAME}"

# Verify BASE_BRANCH exists on remote; if not, fall back to the remote's actual default branch
if ! codify_run_shell 'cd /workspace && git rev-parse --verify "origin/${BASE_BRANCH}"' > /dev/null 2>&1; then
    echo "Warning: origin/${BASE_BRANCH} not found. Detecting remote default branch..."
    DETECTED=$(codify_run_shell 'cd /workspace && git ls-remote --symref origin HEAD' 2>/dev/null | grep '^ref:' | sed 's|ref: refs/heads/||;s|	HEAD||')
    if [ -n "${DETECTED}" ]; then
        echo "Detected remote default branch: ${DETECTED} (was: ${BASE_BRANCH})"
        BASE_BRANCH="${DETECTED}"
    else
        echo "ERROR: Cannot resolve base branch 'origin/${BASE_BRANCH}' and could not detect default branch"
        exit 1
    fi
fi

if codify_run_shell 'cd /workspace && git show-ref --verify --quiet "refs/heads/${BRANCH_NAME}"'; then
    codify_run_shell 'cd /workspace && git checkout "${BRANCH_NAME}"'
    echo "Branch ${BRANCH_NAME} exists locally, checking for uncommitted changes..."
    BRANCH_DIRTY=$(codify_run_shell 'cd /workspace && git status --porcelain' || true)
    repo_sync_local_work_branch "${BRANCH_DIRTY}"
elif [ -n "${REPO_REMOTE_WORK_SHA}" ] \
    && codify_run_shell 'cd /workspace && git show-ref --verify --quiet "refs/remotes/origin/${BRANCH_NAME}"'; then
    REPO_REMOTE_WORK_BRANCH="true"
    REPO_WORK_BRANCH_RELATION="remote_only"
    REPO_SYNC_ACTION="checkout_remote"
    repo_log "checking out existing remote work branch=${BRANCH_NAME}"
    # The single-branch clone refspec only names BASE_BRANCH, so Git does not classify the
    # explicitly fetched ref as tracking-eligible. Start from the exact remote commit and keep
    # using explicit fetch/push refs instead of silently falling back to the current base.
    codify_run_shell 'cd /workspace && git checkout --no-track -b "${BRANCH_NAME}" "origin/${BRANCH_NAME}"'
else
    REPO_WORK_BRANCH_RELATION="new"
    REPO_SYNC_ACTION="create_from_base"
    echo "Creating new branch from ${BASE_BRANCH}..."
    codify_run_shell 'cd /workspace && git checkout -b "${BRANCH_NAME}" "origin/${BASE_BRANCH}"'
fi

REPO_ACTUAL_SHALLOW=$(codify_run_shell 'cd /workspace && git rev-parse --is-shallow-repository' 2>/dev/null || echo "unknown")
REPO_EFFECTIVE_FILTER=$(codify_run_shell 'cd /workspace && git config --get remote.origin.partialclonefilter' 2>/dev/null || true)
REPO_COMMIT_SHA=$(codify_run_shell 'cd /workspace && git rev-parse --short HEAD' 2>/dev/null || echo "unknown")
REPO_PACK_SIZE=$(codify_run_shell 'cd /workspace && git count-objects -vH' 2>/dev/null | awk -F': ' '$1 == "size-pack" {print $2}' || true)
REPO_PREPARE_FINISHED_MS=$(repo_now_ms)
REPO_PREPARE_ELAPSED_MS=$((REPO_PREPARE_FINISHED_MS - REPO_PREPARE_STARTED_MS))
REPO_PREPARATION_PHASE="ready"
repo_log "actual_state shallow=${REPO_ACTUAL_SHALLOW} effective_filter=${REPO_EFFECTIVE_FILTER:-none}"
repo_log "ready action=${REPO_ACTION} elapsed_ms=${REPO_PREPARE_ELAPSED_MS} branch=${BRANCH_NAME} commit=${REPO_COMMIT_SHA} pack_size=${REPO_PACK_SIZE:-unknown} fallback=${REPO_FALLBACK:-none}"
# Persistent workspaces may carry .git objects owned by a different uid from an
# earlier harness run (e.g. Codex exec as root). The shared delivery commits as
# the worker runtime user, so normalize ownership so it can write .git.
chown -R "${CODIFY_RUN_UID}:${CODIFY_RUN_GID}" /workspace/.git 2>/dev/null || true
repo_write_preparation_artifact \
    "${REPO_PREPARE_ELAPSED_MS}" \
    "${REPO_ACTUAL_SHALLOW}" \
    "${REPO_EFFECTIVE_FILTER}" \
    "${REPO_COMMIT_SHA}" \
    "${REPO_PACK_SIZE}" \
    "ready" \
    "${REPO_PREPARATION_PHASE}" \
    "0"

# Run Claude Code CLI in direct execution mode
echo "Running Claude Code CLI in direct execution mode..."
echo "Prompt: ${USER_PROMPT}"
echo ""
