#!/bin/bash
# Codex adapter for the Codify harness contract.

CODIFY_CODEX_TRANSLATOR="${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/adapters/codex_events.py"

codify_codex_bin() {
    # Prefer the profile-mounted codex package, then an explicit env override.
    if [ -x "/opt/codify-codex/bin/codex" ]; then
        echo "/opt/codify-codex/bin/codex"
        return 0
    fi
    echo "${CODIFY_CODEX_BIN:-/usr/local/bin/codex}"
}

codex_adapter_metadata() {
    # Codex emits the V1 or V2 envelope/result per the runtime contract the
    # backend freezes into the attempt. The manifest top-level stays V1 until
    # the Phase 5 hard switch; this operator honours an explicit override.
    local contract="${CODIFY_RUNTIME_CONTRACT_VERSION:-codify.worker.harness/v1}"
    local event_schema="${CODIFY_EVENT_SCHEMA:-codify.worker.event/v1}"
    if [ "${contract}" = "codify.worker.harness/v2" ]; then
        event_schema="${CODIFY_EVENT_SCHEMA:-codify.worker.event/v2}"
    fi
    # Frozen manifest is the single source of truth for adapter version/digest.
    jq -c \
        --arg key codex \
        --arg contract "${contract}" \
        --arg event_schema "${event_schema}" \
        '{ key: $key,
           adapter_version: (.adapters.codex.version // ""),
           adapter_digest: (.adapters.codex.digest // ""),
           contract_version: $contract,
           event_schema: $event_schema }' \
        "${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/manifest.json"
}

codex_adapter_verify_runtime() {
    local bin
    bin="$(codify_codex_bin)"
    if [ ! -x "${bin}" ]; then
        echo "Codex CLI is unavailable: ${bin}" >&2
        return 1
    fi
    local version_output
    version_output="$("${bin}" --version 2>/dev/null | head -n 1)"
    if [ -z "${version_output}" ]; then
        echo "Could not read Codex CLI version" >&2
        return 1
    fi
    CODIFY_CLI_VERSION="${version_output}"
    export CODIFY_CLI_VERSION
    # cli_version_range in the manifest is an advisory fast-startup hint, not an
    # enforced gate: an out-of-range CLI logs a warning and is allowed to run.
    local cli_range version_range_py manifest_path
    version_range_py="${CODIFY_ORCHESTRATION_DIR:-}/worker-entrypoint/harness/version_range.py"
    manifest_path="${CODIFY_ORCHESTRATION_DIR:-}/manifest.json"
    [ -r "${manifest_path}" ] || manifest_path="${ENTRYPOINT_LIB_DIR:-}/harness/manifest.json"
    cli_range="$(jq -r '.adapters.codex.cli_version_range // empty' "${manifest_path}" 2>/dev/null || true)"
    if [ -n "${cli_range}" ] && [ -f "${version_range_py}" ] \
        && ! python3 "${version_range_py}" \
            --version "${CODIFY_CLI_VERSION}" --range "${cli_range}" >/dev/null 2>&1; then
        echo "WARNING: codex CLI ${CODIFY_CLI_VERSION} is outside the declared range ${cli_range} (advisory, not enforced)" >&2
    fi
    if [ -n "${CODIFY_CLI_BINARY_DIGEST:-}" ]; then
        local actual_digest
        actual_digest="$(sha256sum "${bin}" 2>/dev/null | awk '{print $1}')"
        if [ -z "${actual_digest}" ] || [ "${actual_digest}" != "${CODIFY_CLI_BINARY_DIGEST}" ]; then
            echo "Codex CLI binary digest mismatch: expected ${CODIFY_CLI_BINARY_DIGEST}, got ${actual_digest:-unreadable}" >&2
            return 1
        fi
    fi
    return 0
}

codex_adapter_detect_capabilities() {
    jq -c '.adapters.codex.capabilities // {}' \
        "${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/manifest.json"
}

codex_adapter_prepare_config() {
    # Persist CODEX_HOME (config.toml + session transcripts) on the issue-shared
    # volume so a later continue task can resume the same codex session across
    # containers. config.toml is rewritten per task from the frozen endpoint, so
    # the persisted home never leaks stale provider settings. Fall back to the
    # per-task runtime dir when the shared volume is absent.
    if [ -d "/opt/codify-issue-shared" ] && [ -w "/opt/codify-issue-shared" ]; then
        export CODEX_HOME="/opt/codify-issue-shared/codex-home"
    else
        export CODEX_HOME="${CODIFY_RUNTIME_DIR}/codex-home"
    fi
    mkdir -p "${CODEX_HOME}"
    chown -R "${CODIFY_RUN_UID:-1000}:${CODIFY_RUN_GID:-1000}" "${CODEX_HOME}" 2>/dev/null || true
    # Export the codex transport/model identity so events.py forms the
    # correct V2 harness envelope (cli_jsonl / codex-jsonl / openai_responses).
    # Harmless under V1 (events.py ignores them). No-op when already injected.
    export CODIFY_HARNESS_CONTROL_TRANSPORT_KIND="${CODIFY_HARNESS_CONTROL_TRANSPORT_KIND:-cli_jsonl}"
    export CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL="${CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL:-codex-jsonl}"
    export CODIFY_HARNESS_MODEL_PROTOCOLS="${CODIFY_HARNESS_MODEL_PROTOCOLS:-openai_responses}"
    # Point codex at the frozen Snapshot endpoint/model (codex does not honour
    # OPENAI_BASE_URL for the Responses API, so write an explicit config).
    local base_url="${OPENAI_BASE_URL:-}"
    local model="${OPENAI_MODEL:-}"
    if [ -n "${base_url}" ] && [ -n "${model}" ]; then
        # Sandbox: the worker container IS the isolation boundary (container-
        # boundary mode, matching the Claude harness). Codex's own bwrap sandbox
        # cannot create userns inside the worker container (workspace-write/read-only
        # would fail every command), so the container boundary runs in
        # danger-full-access. To keep Codex write-files-only — like Claude — an
        # execution policy forbids git write operations, so Codex cannot commit/
        # push and the shared Codify delivery does. approval_policy "never" keeps
        # unattended runs prompt-free (CI mode).
        #   container-boundary (Codify default) -> danger-full-access + execpolicy
        #   sandboxed (profile-tightened)       -> read-only
        # CODIFY_CODEX_SANDBOX may still force an explicit codex-level override.
        local sandbox_mode="${CODIFY_CODEX_SANDBOX:-}"
        if [ -z "${sandbox_mode}" ]; then
            case "${CODIFY_HARNESS_SANDBOX_MODE:-container-boundary}" in
                sandboxed) sandbox_mode="read-only" ;;
                *) sandbox_mode="danger-full-access" ;;
            esac
        fi
        if [ "${sandbox_mode}" = "danger-full-access" ]; then
            cat > "${CODEX_HOME}/execpolicy.rules" <<'RULES'
prefix_rule(
    pattern = ["git", ["commit", "push", "add", "rm", "mv", "reset", "revert", "merge", "checkout", "branch", "stash", "init"]],
    decision = "forbidden",
    justification = "Codify delivery owns version control; Codex edits working-tree files only",
)
RULES
        fi
        cat > "${CODEX_HOME}/config.toml" <<EOF
model = "${model}"
model_provider = "codify"
sandbox_mode = "${sandbox_mode}"
approval_policy = "never"

[model_providers.codify]
name = "Codify endpoint"
base_url = "${base_url}"
wire_api = "responses"
env_key = "OPENAI_API_KEY"

[model_providers.codify.models."${model}"]
name = "${model}"
EOF
        chown "${CODIFY_RUN_UID:-1000}:${CODIFY_RUN_GID:-1000}" "${CODEX_HOME}/config.toml" 2>/dev/null || true
    fi
    return 0
}

codex_adapter_build_command() {
    # Model/Provider source is only the frozen Snapshot (via env). The runner
    # lives under worker-entrypoint/legacy (maps to the same path in the bundle).
    echo "${CODIFY_HARNESS_COMMAND:-${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/legacy/codex-run.sh}"
}

codex_adapter_materialize_skills() {
    # Codex discovers skills from the agentskills.io layout. Materialize the
    # sealed per-task Skill snapshot (packaged as .claude/skills) into the
    # per-task CODEX_HOME so the workspace/Git tree stays clean.
    if [ -z "${CODIFY_TASK_SKILLS_DIR:-}" ]; then
        return 0
    fi
    local src="${CODIFY_TASK_SKILLS_DIR}/.claude/skills"
    if [ ! -d "${src}" ]; then
        echo "Task Skills snapshot does not contain skills: ${src}" >&2
        return 1
    fi
    local dest="${CODEX_HOME:-${CODIFY_RUNTIME_DIR}/codex-home}/.agents/skills"
    mkdir -p "${dest}"
    if ! cp -a "${src}/." "${dest}/" 2>/dev/null; then
        echo "Could not materialize skills into ${dest}" >&2
        return 1
    fi
    chown -R "${CODIFY_RUN_UID:-1000}:${CODIFY_RUN_GID:-1000}" "${dest}" 2>/dev/null || true
    return 0
}

codex_adapter_run() {
    local prompt_file="$1"
    local result_file="$2"
    local raw_file="${CODIFY_HARNESS_RAW_DIR}/codex.jsonl"
    : > "${raw_file}"
    chown 0:0 "${raw_file}"
    chmod 644 "${raw_file}"
    CODIFY_CODEX_RUN_AS="${CODIFY_RUN_AS:-}" \
    CODIFY_CODEX_BIN="$(codify_codex_bin)" \
    CODIFY_CODEX_RAW_EVENT_JSONL="${raw_file}" \
    CODIFY_CODEX_EVENT_TRANSLATOR="${CODIFY_CODEX_TRANSLATOR}" \
    CODIFY_CANONICAL_EVENT_WRITER="${CODIFY_CANONICAL_EVENT_WRITER}" \
    ARTIFACT_DIR="${CODIFY_RUNTIME_DIR}" \
    CI_CLAUDE_DISABLE_CONSOLE_TEE=1 \
    PROMPT_FILE="${prompt_file}" \
    timeout "${TASK_TIMEOUT:-1800}" "${CODIFY_HARNESS_COMMAND}" > "${result_file}"
}

codex_adapter_stream_events() {
    local raw_file="$1"
    python3 "${CODIFY_CODEX_TRANSLATOR}" --raw-file "${raw_file}"
}

codex_adapter_normalize_result() {
    local result_file="$1"
    # The authoritative result is written by the event translator under
    # CODIFY_HARNESS_RESULT_FILE; the runner's result_file receives only the
    # legacy CLI stdout and must not be used for canonical normalization.
    local authoritative="${CODIFY_HARNESS_RESULT_FILE:-${result_file}}"
    [ -s "${authoritative}" ] || return 1
    # Accept the result schema matching the active contract (v1 in production
    # today, v2 once the runtime contract flips). The V2 envelope nests the
    # harness identity under a `harness` block; the V1 envelope keeps it flat.
    local schema="codify.worker.result/v1"
    if [ "${CODIFY_RUNTIME_CONTRACT_VERSION:-}" = "codify.worker.harness/v2" ]; then
        schema="codify.worker.result/v2"
        jq -e \
            --arg harness_key codex \
            --arg adapter_version "${CODIFY_ADAPTER_VERSION}" \
            --arg cli_version "${CODIFY_CLI_VERSION}" \
            --arg schema "${schema}" \
            '.schema == $schema
             and .harness.key == $harness_key
             and .harness.adapter_version == $adapter_version
             and .harness.cli_version == $cli_version
             and .harness.control_transport.kind != null
             and (.harness.model_protocols | type == "array")
             and (.harness.model_protocols | length > 0)
             and (.status | IN("completed", "failed", "cancelled", "protocol_error"))
             and (.success | type == "boolean")
             and (.usage | type == "object")
             and (.capability_warnings | type == "array")' \
            "${authoritative}" >/dev/null || return 1
        return 0
    fi
    jq -e \
        --arg harness_key codex \
        --arg adapter_version "${CODIFY_ADAPTER_VERSION}" \
        --arg cli_version "${CODIFY_CLI_VERSION}" \
        --arg schema "${schema}" \
        '.schema == $schema
         and .harness_key == $harness_key
         and .adapter_version == $adapter_version
         and .cli_version == $cli_version
         and (.status | IN("completed", "failed", "cancelled", "protocol_error"))
         and (.success | type == "boolean")
         and (.usage | type == "object")
         and (.capability_warnings | type == "array")' \
        "${authoritative}" >/dev/null || return 1
    return 0
}

codex_adapter_run_text() {
    # Codex does not expose a run_text helper; the runner falls back to a
    # deterministic commit message / original summary.
    echo "Codex run_text is unsupported" >&2
    return 1
}

codex_adapter_terminate() {
    return 0
}

adapter_metadata() { codex_adapter_metadata "$@"; }
adapter_verify_runtime() { codex_adapter_verify_runtime "$@"; }
adapter_detect_capabilities() { codex_adapter_detect_capabilities "$@"; }
adapter_prepare_config() { codex_adapter_prepare_config "$@"; }
adapter_build_command() { codex_adapter_build_command "$@"; }
adapter_materialize_skills() { codex_adapter_materialize_skills "$@"; }
adapter_stream_events() { codex_adapter_stream_events "$@"; }
adapter_normalize_result() { codex_adapter_normalize_result "$@"; }
adapter_run() { codex_adapter_run "$@"; }
adapter_run_text() { codex_adapter_run_text "$@"; }
adapter_terminate() { codex_adapter_terminate "$@"; }
