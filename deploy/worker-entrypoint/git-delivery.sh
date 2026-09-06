# Git-delivery reconciliation (see git-delivery.py): pin, collect, publish.

GIT_DELIVERY_HELPER="${ENTRYPOINT_LIB_DIR}/git-delivery.py"
GIT_DELIVERY_START_FILE="${CODIFY_RUNTIME_DIR}/git-delivery-start.json"
GIT_DELIVERY_SNAPSHOT_FILE="${CODIFY_RUNTIME_DIR}/git-delivery.json"
GIT_DELIVERY_SNAPSHOT_WRITTEN=0
export GIT_DELIVERY_START_FILE GIT_DELIVERY_SNAPSHOT_FILE



repo_pin_delivery_start() {
    # Fix S (local task-branch HEAD), R0 (remote work-branch HEAD at prep) and
    # B0 (base HEAD) before any task code runs. REPO_REMOTE_WORK_SHA mutates on
    # push, so it must never double as the task start.
    if [ ! -d /workspace/.git ]; then
        repo_log "error delivery_pin reason=repo_missing"
        return 1
    fi
    local start_remote base_remote
    start_remote="${REPO_REMOTE_WORK_SHA:-}"
    base_remote="${REPO_REMOTE_BASE_SHA:-}"
    if ! repo_delivery_run_python \
        recover_start \
        --work-dir /workspace \
        --branch "${BRANCH_NAME}" \
        --attempt-id "${CODIFY_ATTEMPT_ID:?Missing CODIFY_ATTEMPT_ID}" \
        --out "${GIT_DELIVERY_START_FILE}" \
        --start-remote "${start_remote}" \
        --base-remote "${base_remote}" >/dev/null; then
        repo_log "error delivery_pin reason=collector_failed"
        return 1
    fi
    chmod 644 "${GIT_DELIVERY_START_FILE}" 2>/dev/null || true
    local pinned_sha
    pinned_sha=$(jq -r '.start_sha // empty' "${GIT_DELIVERY_START_FILE}" 2>/dev/null || true)
    repo_log "delivery pinned branch=${BRANCH_NAME} start=${pinned_sha:-unknown} remote=${start_remote:-missing}"
    return 0
}

repo_delivery_collect() {
    # Local facts (this-task commits, inherited pending commits, net diff)
    # into the snapshot with push.status=not_attempted. No network.
    if [ ! -f "${GIT_DELIVERY_START_FILE}" ]; then
        repo_log "error delivery_collect reason=start_file_missing"
        return 1
    fi
    local collect_output
    if ! collect_output=$(repo_delivery_run_python \
        collect \
        --work-dir /workspace \
        --start-file "${GIT_DELIVERY_START_FILE}" \
        --out "${GIT_DELIVERY_SNAPSHOT_FILE}" 2>&1); then
        repo_log "error delivery_collect reason=collector_failed detail=${collect_output}"
        return 1
    fi
    GIT_DELIVERY_SNAPSHOT_WRITTEN=1
    chmod 644 "${GIT_DELIVERY_SNAPSHOT_FILE}" 2>/dev/null || true
    codify_chown "${GIT_DELIVERY_SNAPSHOT_FILE}" 2>/dev/null || true
    return 0
}

repo_delivery_record() {
    # repo_delivery_record <status> [remote-sha] [error-code] [error-message]
    # Updates push facts in the snapshot and recomputes the canonical top-level
    # projections (commit_sha/commit_message/diff) from the same object.
    local status="$1"
    local remote_sha="${2:-}"
    local error_code="${3:-}"
    local error_message="${4:-}"
    if [ "${GIT_DELIVERY_SNAPSHOT_WRITTEN:-0}" -ne 1 ] \
        || [ ! -f "${GIT_DELIVERY_SNAPSHOT_FILE}" ]; then
        return 1
    fi
    local record_output
    if ! record_output=$(repo_delivery_run_python \
        record_push \
        --snapshot "${GIT_DELIVERY_SNAPSHOT_FILE}" \
        --status "${status}" \
        --remote-sha "${remote_sha}" \
        --error-code "${error_code}" \
        --error-message "${error_message}" 2>&1); then
        repo_log "error delivery_record status=${status} detail=${record_output}"
        return 1
    fi
    return 0
}

repo_delivery_ensure_pinned_remote() {
    # Re-bind origin to the task-frozen URL and refresh the credential header
    # before any network op: the Harness may have repointed origin.
    codify_run_shell 'cd /workspace && git remote set-url origin "${GIT_REPO_URL}"' || true
    codify_run_shell 'cd /workspace && git config --local http.extraHeader "PRIVATE-TOKEN: ${GITLAB_TOKEN}"' || true
}

repo_delivery_remote_tip() {
    # Work-branch tip of the FROZEN repository URL (never `origin`). Nonzero:
    # unconfirmed is never "absent".
    local refs tip
    set +e
    refs=$(codify_run_shell \
        'cd /workspace && GIT_TERMINAL_PROMPT=0 git ls-remote --heads "${GIT_REPO_URL}" "refs/heads/${BRANCH_NAME}"' \
        2>/dev/null)
    local query_result=$?
    set -e
    if [ "${query_result}" -ne 0 ]; then
        return 1
    fi
    tip=$(printf '%s\n' "${refs}" \
        | awk -v ref="refs/heads/${BRANCH_NAME}" '$2 == ref {print $1; exit}')
    if [ -n "${tip}" ]; then
        printf '%s\n' "${tip}"
    fi
    return 0
}

repo_delivery_fetch_branch() {
    # Fetch only the task work branch from the FROZEN URL into a private ref:
    # local origin tracking state is untrusted after the Harness ran. Depth
    # policy mirrors the configured clone strategy.
    if [ -n "${CODIFY_GIT_CLONE_DEPTH}" ]; then
        codify_run_shell \
            'cd /workspace && git fetch --depth "${CODIFY_GIT_CLONE_DEPTH}" "${GIT_REPO_URL}" "+refs/heads/${BRANCH_NAME}:refs/remotes/codify-delivery/${BRANCH_NAME}"' \
            2>/dev/null
    else
        codify_run_shell \
            'cd /workspace && git fetch "${GIT_REPO_URL}" "+refs/heads/${BRANCH_NAME}:refs/remotes/codify-delivery/${BRANCH_NAME}"' \
            2>/dev/null
    fi
}

repo_delivery_local_tip() {
    # Local copy of the frozen-remote observation written by fetch_branch.
    codify_run_shell 'cd /workspace && git rev-parse "refs/remotes/codify-delivery/${BRANCH_NAME}"' \
        2>/dev/null || true
}



repo_delivery_recheck_publish() {
    # One bounded recheck after a refused/uncertain push. Exports
    # REPO_DELIVERY_RECHECK_TIP (empty when unobservable) so the caller can
    # tell an unchanged rejection (push_failed) from an update (remote_changed).
    # Returns 0 only when the remote provably already contains the head.
    local head_sha="$1"
    local start_remote="$2"
    local tip
    tip=$(repo_delivery_remote_tip) || {
        REPO_DELIVERY_RECHECK_TIP=""
        export REPO_DELIVERY_RECHECK_TIP
        return 2
    }
    if [ -z "${tip}" ]; then
        REPO_DELIVERY_RECHECK_TIP=""
        export REPO_DELIVERY_RECHECK_TIP
        return 1
    fi
    if [ "${tip}" = "${head_sha}" ]; then
        REPO_DELIVERY_RECHECK_TIP="${tip}"
        export REPO_DELIVERY_RECHECK_TIP
        return 0
    fi
    if repo_delivery_fetch_branch; then
        local decision decision_type
        decision=$(repo_delivery_classify "${head_sha}" "${tip}" "${start_remote}") || return 2
        decision_type=$(printf '%s\n' "${decision}" | jq -r '.decision // "failed"')
        if [ "${decision_type}" = "already_present" ]; then
            REPO_DELIVERY_RECHECK_TIP="${tip}"
            export REPO_DELIVERY_RECHECK_TIP
            return 0
        fi
    fi
    REPO_DELIVERY_RECHECK_TIP="${tip}"
    export REPO_DELIVERY_RECHECK_TIP
    return 1
}

repo_delivery_push_pinned() {
    # repo_delivery_push_pinned <head_sha> <lease_sha_or_empty>
    # Push exactly <head_sha>:refs/heads/<branch> to the FROZEN URL with a
    # lease that only confirms a verified fast-forward.
    local head_sha="$1"
    local lease_sha="$2"
    echo "Pushing ${head_sha} to refs/heads/${BRANCH_NAME} (lease ${lease_sha:-must-not-exist})..."
    repo_delivery_ensure_pinned_remote
    REPO_DELIVERY_LEASE="${lease_sha}"
    REPO_DELIVERY_PUBLISH_HEAD="${head_sha}"
    export REPO_DELIVERY_LEASE REPO_DELIVERY_PUBLISH_HEAD
    codify_run_shell "cd /workspace && git config codify.unpublishedPushSha '${head_sha}'" || true
    set +e
    codify_run_shell \
        'cd /workspace && GIT_TERMINAL_PROMPT=0 git push --force-with-lease="refs/heads/${BRANCH_NAME}:${REPO_DELIVERY_LEASE}" "${GIT_REPO_URL}" "${REPO_DELIVERY_PUBLISH_HEAD}:refs/heads/${BRANCH_NAME}"'
    local push_result=$?
    set -e
    return "${push_result}"
}

repo_delivery_record_confirmed() {
    # Persist the confirmed outcome; the marker clears only after the write
    # succeeds, so a failed record fails the run and keeps recovery state.
    local status="$1"
    local remote_sha="$2"
    if ! repo_delivery_record "${status}" "${remote_sha}"; then
        repo_log "error delivery_record status=${status} failed; keeping recovery marker"
        echo "ERROR: Could not persist the confirmed delivery outcome"
        return 1
    fi
    repo_delivery_clear_marker
    return 0
}

repo_delivery_publish() {
    # Reconcile local facts with the FROZEN remote and publish H only as a
    # verified fast-forward; returns 0 only for pushed / already_present.
    local head_sha start_remote status
    head_sha=$(repo_delivery_snapshot_value '.git_delivery.head_sha')
    if [ -z "${head_sha}" ] || [ ! -f "${GIT_DELIVERY_SNAPSHOT_FILE}" ]; then
        repo_log "error delivery_publish reason=snapshot_missing"
        return 1
    fi
    start_remote=$(repo_delivery_snapshot_value '.git_delivery.start_remote_sha')

    # Pinned head must still be the branch head with no stray changes.
    if ! codify_run_shell \
        "cd /workspace && [ \"\$(git rev-parse --abbrev-ref HEAD)\" = '${BRANCH_NAME}' ] && [ \"\$(git rev-parse HEAD)\" = '${head_sha}' ] && [ -z \"\$(git status --porcelain)\" ]" \
        2>/dev/null; then
        repo_log "error delivery_publish reason=branch_changed head=${head_sha}"
        echo "ERROR: The task branch moved or gained uncommitted changes during finalization; delivery was not published"
        repo_delivery_record "failed" "" "branch_changed" \
            "The task branch moved or gained uncommitted changes during finalization; the pinned head was not published" \
            || true
        return 1
    fi

    repo_delivery_ensure_pinned_remote
    local remote_tip
    remote_tip=$(repo_delivery_remote_tip)
    local observe_result=$?
    if [ "${observe_result}" -ne 0 ]; then
        echo "ERROR: Could not observe the remote task branch; delivery is unconfirmed"
        repo_log "error delivery_publish reason=remote_unobservable head=${head_sha}"
        repo_delivery_record "failed" "" "remote_unconfirmed" \
            "The remote task branch could not be observed (network or credentials); the delivery is not confirmed" \
            || true
        return 1
    fi

    if [ -z "${remote_tip}" ]; then
        if [ -n "${start_remote}" ]; then
            echo "ERROR: The remote task branch was deleted while this task was running; refusing to recreate it"
            repo_log "error delivery_publish reason=remote_deleted start_remote=${start_remote} head=${head_sha}"
            repo_delivery_record "failed" "" "remote_deleted" \
                "The remote task branch was deleted after this task started; refusing to recreate it automatically" \
                || true
            return 1
        fi
        # Branch never existed: create it with "must not exist" as the lease.
        repo_log "delivery publish action=create_branch head=${head_sha}"
        if repo_delivery_push_pinned "${head_sha}" ""; then
            if repo_delivery_record_confirmed "pushed" "${head_sha}"; then
                repo_log "delivery published action=created head=${head_sha}"
                return 0
            fi
            return 1
        fi
        # Bounded single recheck: a concurrent creator may already contain H.
        if repo_delivery_recheck_publish "${head_sha}" "${start_remote}"; then
            echo "Remote already contains the delivered head; confirming delivery"
            if repo_delivery_record_confirmed "already_present" "${head_sha}"; then
                repo_log "delivery confirmed action=already_present head=${head_sha}"
                return 0
            fi
            return 1
        fi
        echo "ERROR: Could not create the remote task branch; delivery was not published"
        repo_delivery_record "failed" "" "push_failed" \
            "The remote task branch could not be created; the pinned head was not published" \
            || true
        return 1
    fi

    repo_log "delivery observe remote=${remote_tip} head=${head_sha} start_remote=${start_remote:-missing}"
    if ! repo_delivery_fetch_branch; then
        echo "ERROR: Could not fetch the remote task branch; delivery is unconfirmed"
        repo_delivery_record "failed" "${remote_tip}" "remote_unconfirmed" \
            "The remote task branch could not be fetched (network or credentials); the delivery is not confirmed" \
            || true
        return 1
    fi
    local fetched_tip
    fetched_tip=$(repo_delivery_local_tip)
    local decision decision_type
    decision=$(repo_delivery_classify "${head_sha}" "${fetched_tip}" "${start_remote}") || {
        echo "ERROR: Remote delivery reconciliation failed"
        repo_delivery_record "failed" "${fetched_tip}" "remote_unconfirmed" \
            "Remote delivery reconciliation could not be completed" || true
        return 1
    }
    decision_type=$(printf '%s\n' "${decision}" | jq -r '.decision // "failed"')
    if [ "${decision_type}" = "already_present" ]; then
        echo "Remote already contains the delivered commits; confirming delivery"
        if repo_delivery_record_confirmed "already_present" "${fetched_tip}"; then
            repo_log "delivery confirmed action=already_present remote=${fetched_tip} head=${head_sha}"
            return 0
        fi
        return 1
    fi
    if [ "${decision_type}" != "push" ]; then
        local error_code error_message
        error_code=$(printf '%s\n' "${decision}" | jq -r '.error_code // "remote_diverged"')
        error_message=$(printf '%s\n' "${decision}" | jq -r '.error_message // "Remote reconciliation failed"')
        echo "ERROR: ${error_message}"
        repo_delivery_record "failed" "${fetched_tip}" "${error_code}" "${error_message}" || true
        return 1
    fi

    # Fast-forward proven locally (R <= H and R0 <= R when R0 existed); the
    # observed tip is the exact lease, never a force without that proof.
    if repo_delivery_push_pinned "${head_sha}" "${fetched_tip}"; then
        if repo_delivery_record_confirmed "pushed" "${head_sha}"; then
            repo_log "delivery published action=fast_forward remote=${fetched_tip} head=${head_sha}"
            return 0
        fi
        return 1
    fi

    # One bounded recheck after a refused/uncertain push: prove H landed.
    echo "Push returned non-zero; rechecking whether the remote already contains ${head_sha}"
    local recheck_result
    repo_delivery_recheck_publish "${head_sha}" "${start_remote}"
    recheck_result=$?
    if [ "${recheck_result}" -eq 0 ]; then
        echo "Remote already contains the delivered head; confirming delivery"
        if repo_delivery_record_confirmed "already_present" "${head_sha}"; then
            repo_log "delivery confirmed action=push_recovered head=${head_sha}"
            return 0
        fi
        return 1
    fi
    if [ "${recheck_result}" -eq 2 ] || [ -z "${REPO_DELIVERY_RECHECK_TIP:-}" ]; then
        echo "ERROR: Delivery is unconfirmed after the push attempt (network or credentials)"
        repo_log "error delivery_publish reason=remote_unconfirmed head=${head_sha}"
        repo_delivery_record "failed" "" "remote_unconfirmed" \
            "The push result could not be confirmed (network or credentials); the delivery is not confirmed" \
            || true
    elif [ "${REPO_DELIVERY_RECHECK_TIP}" = "${fetched_tip}" ]; then
        echo "ERROR: The remote rejected the push; delivery was not confirmed"
        repo_log "error delivery_publish reason=push_failed head=${head_sha}"
        repo_delivery_record "failed" "${fetched_tip}" "push_failed" \
            "The remote rejected the push of the pinned head; the delivery is not confirmed" \
            || true
    else
        echo "ERROR: The remote task branch changed during publishing; the pinned head was not pushed"
        repo_log "error delivery_publish reason=remote_changed head=${head_sha}"
        repo_delivery_record "failed" "${fetched_tip}" "remote_changed" \
            "The remote task branch changed between verification and push; the pinned head was not published" \
            || true
    fi
    return 1
}

repo_delivery_has_content() {
    # 0 when commits or recovered_commits are non-empty (delivery content).
    [ -f "${GIT_DELIVERY_SNAPSHOT_FILE}" ] || return 1
    local count
    count=$(jq -r \
        '((.git_delivery.commits // []) | length) + ((.git_delivery.recovered_commits // []) | length)' \
        "${GIT_DELIVERY_SNAPSHOT_FILE}" 2>/dev/null || echo 0)
    [ -n "${count}" ] && [ "${count}" -gt 0 ] 2>/dev/null
}

repo_delivery_commits_present() {
    # 0 when this task produced commits of its own (worker or harness).
    [ -f "${GIT_DELIVERY_SNAPSHOT_FILE}" ] || return 1
    local count
    count=$(jq -r '((.git_delivery.commits // []) | length)' \
        "${GIT_DELIVERY_SNAPSHOT_FILE}" 2>/dev/null || echo 0)
    [ -n "${count}" ] && [ "${count}" -gt 0 ] 2>/dev/null
}

repo_delivery_collect_facts_on_exit() {
    # Best-effort, network-free preservation of local commit facts for failed
    # exits; collection never replaces the original failure reason.
    if [ "${TASK_MODE:-execute}" = "plan" ]; then
        return 0
    fi
    if [ "${GIT_DELIVERY_SNAPSHOT_WRITTEN:-0}" -eq 1 ]; then
        return 0
    fi
    if [ ! -d /workspace/.git ] || [ ! -f "${GIT_DELIVERY_START_FILE:-}" ]; then
        return 0
    fi
    if ! repo_delivery_collect; then
        repo_log "warning delivery_facts_preservation failed"
        return 0
    fi
    repo_delivery_write_metadata || true
    repo_log "delivery facts preserved after exit"
    return 0
}

repo_delivery_write_metadata() {
    # Persist per-task metadata for MR aggregation and Task worker_metadata.
    # All commit/stat projection comes from the same delivery snapshot used by
    # the canonical finalizer; git_delivery is the authoritative contract.
    if [ ! -f "${GIT_DELIVERY_SNAPSHOT_FILE}" ]; then
        repo_log "warning delivery_metadata skipped reason=snapshot_missing"
        return 1
    fi
    local summary_truncated task_metadata
    summary_truncated="${FINAL_SUMMARY_CONTENT:-}"
    summary_truncated="${summary_truncated:0:3000}"
    task_metadata=$(jq -nc \
        --argjson task_id "${TASK_ID:-0}" \
        --arg prompt "${USER_PROMPT:-}" \
        --arg overall_summary "${FINAL_OVERALL_SUMMARY:-}" \
        --arg execution_summary "${summary_truncated}" \
        --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --slurpfile snap "${GIT_DELIVERY_SNAPSHOT_FILE}" \
        '{
            task_id: $task_id,
            prompt: $prompt,
            commit_sha: $snap[0].commit_sha,
            commit_message: $snap[0].commit_message,
            overall_summary: $overall_summary,
            execution_summary: $execution_summary,
            new_files: (($snap[0].git_delivery.diff // {}) .new_files // []),
            modified_files: (($snap[0].git_delivery.diff // {}) .modified_files // []),
            deleted_files: (($snap[0].git_delivery.diff // {}) .deleted_files // []),
            additions: (($snap[0].git_delivery.diff // {}) .additions),
            deletions: (($snap[0].git_delivery.diff // {}) .deletions),
            reused_local_commit: (
                (((($snap[0].git_delivery.commits // []) | length) == 0))
                and (((($snap[0].git_delivery.recovered_commits // []) | length) > 0))
            ),
            git_delivery: $snap[0].git_delivery,
            timestamp: $timestamp
        }')
    printf '%s\n' "${task_metadata}" > "${CODIFY_RUNTIME_DIR}/task-metadata.json"
    chmod 644 "${CODIFY_RUNTIME_DIR}/task-metadata.json" 2>/dev/null || true
    codify_chown "${CODIFY_RUNTIME_DIR}/task-metadata.json" 2>/dev/null || true
    echo "Task metadata written to ${CODIFY_RUNTIME_DIR}/task-metadata.json (overall_summary_chars=${#FINAL_OVERALL_SUMMARY})"
    return 0
}

