# Repository delivery, timing, and preparation artifact helpers.

repo_log() {
    printf '[repo] %s\n' "$*"
}

repo_has_unpublished_local_head() {
    local local_sha unpublished_sha
    local_sha=$(codify_run_shell 'cd /workspace && git rev-parse HEAD' 2>/dev/null || true)
    unpublished_sha=$(
        codify_run_shell 'cd /workspace && git config --get codify.unpublishedPushSha' \
            2>/dev/null || true
    )
    if [ -n "${local_sha}" ] && [ "${unpublished_sha}" = "${local_sha}" ]; then
        return 0
    fi

    case "${REPO_WORK_BRANCH_RELATION:-}" in
        local_ahead) return 0 ;;
        remote_missing)
            if [ -n "${local_sha}" ] \
                && [ "${local_sha}" != "${REPO_REMOTE_BASE_SHA:-}" ] \
                && codify_run_shell 'cd /workspace && git merge-base --is-ancestor "refs/remotes/origin/${BASE_BRANCH}" HEAD'; then
                return 0
            fi
            return 1
            ;;
        *) return 1 ;;
    esac
}

repo_push_work_branch_with_lease() {
    echo "Pushing to remote..."
    codify_run_shell 'cd /workspace && git remote set-url origin "${GIT_REPO_URL}"'
    codify_run_shell 'cd /workspace && git config --local http.extraHeader "PRIVATE-TOKEN: ${GITLAB_TOKEN}"'
    LOCAL_PUSH_SHA=$(codify_run_shell 'cd /workspace && git rev-parse HEAD')
    export LOCAL_PUSH_SHA

    if [ -n "${REPO_REMOTE_WORK_SHA}" ] \
        && ! codify_run_shell 'cd /workspace && git merge-base --is-ancestor "${REPO_REMOTE_WORK_SHA}" HEAD'; then
        repo_log "error push_blocked reason=local_history_rewritten prepared_remote=${REPO_REMOTE_WORK_SHA} local=${LOCAL_PUSH_SHA}"
        echo "ERROR: Local work-branch history no longer contains the remote tip observed at task start; refusing to push"
        return 1
    fi

    codify_run_shell 'cd /workspace && git config codify.unpublishedPushSha "${LOCAL_PUSH_SHA}"'
    set +e
    codify_run_shell 'cd /workspace && GIT_TERMINAL_PROMPT=0 git push -u --force-with-lease="refs/heads/${BRANCH_NAME}:${REPO_REMOTE_WORK_SHA}" origin "${BRANCH_NAME}"'
    local push_result=$?
    set -e
    if [ "${push_result}" -eq 0 ]; then
        codify_run_shell 'cd /workspace && git config --unset-all codify.unpublishedPushSha || true'
        REPO_REMOTE_WORK_SHA="${LOCAL_PUSH_SHA}"
        export REPO_REMOTE_WORK_SHA
        return 0
    fi

    set +e
    local current_remote_refs
    current_remote_refs=$(
        codify_run_shell 'cd /workspace && git ls-remote --heads origin "refs/heads/${BRANCH_NAME}"' 2>/dev/null
    )
    local remote_query_result=$?
    set -e
    local current_remote_work_sha=""
    if [ "${remote_query_result}" -eq 0 ]; then
        current_remote_work_sha=$(
            printf '%s\n' "${current_remote_refs}" \
                | awk -v ref="refs/heads/${BRANCH_NAME}" '$2 == ref {print $1; exit}'
        )
    fi

    if [ "${remote_query_result}" -ne 0 ]; then
        repo_log "error push_failed exit=${push_result} remote_query=failed local=${LOCAL_PUSH_SHA}"
    elif [ -n "${current_remote_work_sha}" ] \
        && [ "${current_remote_work_sha}" = "${LOCAL_PUSH_SHA}" ]; then
        repo_log "warning push_recovered result=remote_matches_local exit=${push_result} remote=${current_remote_work_sha} local=${LOCAL_PUSH_SHA}"
        echo "Push command returned ${push_result}, but the remote branch already matches the local commit; continuing"
        codify_run_shell 'cd /workspace && git config --unset-all codify.unpublishedPushSha || true'
        REPO_REMOTE_WORK_SHA="${LOCAL_PUSH_SHA}"
        export REPO_REMOTE_WORK_SHA
        return 0
    elif [ "${current_remote_work_sha:-missing}" != "${REPO_REMOTE_WORK_SHA:-missing}" ]; then
        repo_log "error push_rejected reason=remote_changed prepared_remote=${REPO_REMOTE_WORK_SHA:-missing} current_remote=${current_remote_work_sha:-missing} local=${LOCAL_PUSH_SHA:-unknown}"
        echo "ERROR: Remote work branch changed while this task was running; refusing to overwrite the remote branch"
    else
        repo_log "error push_failed exit=${push_result} remote=${current_remote_work_sha:-missing} local=${LOCAL_PUSH_SHA:-unknown}"
    fi
    return "${push_result}"
}

repo_now_ms() {
    local now
    now=$(date +%s%3N 2>/dev/null || true)
    case "${now}" in
        *[!0-9]* | "") printf '%s000\n' "$(date +%s)" ;;
        *) printf '%s\n' "${now}" ;;
    esac
}

repo_write_preparation_artifact() {
    local elapsed_ms="$1"
    local actual_shallow="$2"
    local effective_filter="$3"
    local commit_sha="$4"
    local pack_size="$5"
    local status="$6"
    local phase="$7"
    local exit_code="$8"

    jq -n \
        --arg status "${status}" \
        --arg phase "${phase}" \
        --arg action "${REPO_ACTION}" \
        --arg workspace "${REPO_WORKSPACE_STATE}" \
        --arg configured_depth "${CODIFY_GIT_CLONE_DEPTH}" \
        --arg configured_filter "${CODIFY_GIT_CLONE_FILTER}" \
        --arg actual_shallow "${actual_shallow}" \
        --arg effective_filter "${effective_filter}" \
        --arg fallback "${REPO_FALLBACK}" \
        --arg remote_work_branch "${REPO_REMOTE_WORK_BRANCH}" \
        --arg previous_remote_work_sha "${REPO_PREVIOUS_REMOTE_WORK_SHA}" \
        --arg remote_work_sha "${REPO_REMOTE_WORK_SHA}" \
        --arg work_branch_relation "${REPO_WORK_BRANCH_RELATION}" \
        --arg sync_action "${REPO_SYNC_ACTION}" \
        --arg base_branch "${BASE_BRANCH}" \
        --arg work_branch "${BRANCH_NAME}" \
        --arg commit_sha "${commit_sha}" \
        --arg pack_size "${pack_size}" \
        --argjson elapsed_ms "${elapsed_ms}" \
        --argjson exit_code "${exit_code}" \
        '{
            status: $status,
            phase: $phase,
            exit_code: $exit_code,
            action: $action,
            workspace_reused: ($workspace == "reused"),
            configured_depth: (
                if $configured_depth == "" then null else ($configured_depth | tonumber) end
            ),
            configured_filter: (
                if $configured_filter == "" then null else $configured_filter end
            ),
            actual_shallow: (
                if $actual_shallow == "true" then true
                elif $actual_shallow == "false" then false
                else null end
            ),
            effective_filter: (
                if $effective_filter == "" then null else $effective_filter end
            ),
            fallback: (if $fallback == "" then null else $fallback end),
            remote_work_branch: ($remote_work_branch == "true"),
            previous_remote_work_sha: (
                if $previous_remote_work_sha == "" then null else $previous_remote_work_sha end
            ),
            remote_work_sha: (
                if $remote_work_sha == "" then null else $remote_work_sha end
            ),
            work_branch_relation: (
                if $work_branch_relation == "" then null else $work_branch_relation end
            ),
            sync_action: (if $sync_action == "" then null else $sync_action end),
            base_branch: $base_branch,
            work_branch: $work_branch,
            commit_sha: $commit_sha,
            pack_size: (if $pack_size == "" then null else $pack_size end),
            elapsed_ms: $elapsed_ms
        }' > "${REPOSITORY_PREPARATION_FILE}"
    chmod 644 "${REPOSITORY_PREPARATION_FILE}" 2>/dev/null || true
    codify_chown "${REPOSITORY_PREPARATION_FILE}" 2>/dev/null || true
    REPO_PREPARATION_ARTIFACT_WRITTEN=1
}

repo_finalize_preparation_on_exit() {
    local exit_code="${1:-1}"
    if [ "${REPO_PREPARATION_ACTIVE:-0}" -ne 1 ] \
        || [ "${REPO_PREPARATION_ARTIFACT_WRITTEN:-0}" -eq 1 ]; then
        return 0
    fi

    local finished_ms elapsed_ms actual_shallow effective_filter commit_sha pack_size
    finished_ms=$(repo_now_ms)
    elapsed_ms=$((finished_ms - REPO_PREPARE_STARTED_MS))
    actual_shallow="unknown"
    effective_filter=""
    commit_sha="unknown"
    pack_size=""
    if [ -d /workspace/.git ]; then
        actual_shallow=$(codify_run_shell 'cd /workspace && git rev-parse --is-shallow-repository' 2>/dev/null || echo "unknown")
        effective_filter=$(codify_run_shell 'cd /workspace && git config --get remote.origin.partialclonefilter' 2>/dev/null || true)
        commit_sha=$(codify_run_shell 'cd /workspace && git rev-parse --short HEAD' 2>/dev/null || echo "unknown")
        pack_size=$(codify_run_shell 'cd /workspace && git count-objects -vH' 2>/dev/null | awk -F': ' '$1 == "size-pack" {print $2}' || true)
    fi
    repo_log "failed action=${REPO_ACTION} phase=${REPO_PREPARATION_PHASE} exit=${exit_code} elapsed_ms=${elapsed_ms}"
    repo_write_preparation_artifact \
        "${elapsed_ms}" \
        "${actual_shallow}" \
        "${effective_filter}" \
        "${commit_sha}" \
        "${pack_size}" \
        "failed" \
        "${REPO_PREPARATION_PHASE}" \
        "${exit_code}"
}
