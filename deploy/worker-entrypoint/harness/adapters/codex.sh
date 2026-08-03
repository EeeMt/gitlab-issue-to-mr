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
    # Frozen manifest is the single source of truth for adapter version/digest.
    jq -c \
        --arg key codex \
        --arg contract "${CODIFY_RUNTIME_CONTRACT_VERSION:-codify.worker.harness/v1}" \
        --arg event_schema "codify.worker.event/v1" \
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
    return 0
}

codex_adapter_detect_capabilities() {
    jq -c '.adapters.codex.capabilities // {}' \
        "${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/manifest.json"
}

codex_adapter_prepare_config() {
    # Hermetic per-task CODEX_HOME; never inherit host or image global config.
    export CODEX_HOME="${CODIFY_RUNTIME_DIR}/codex-home"
    mkdir -p "${CODEX_HOME}"
    chown -R "${CODIFY_RUN_UID:-1000}:${CODIFY_RUN_GID:-1000}" "${CODEX_HOME}" 2>/dev/null || true
    # Point codex at the frozen Snapshot endpoint/model (codex does not honour
    # OPENAI_BASE_URL for the Responses API, so write an explicit config).
    local base_url="${OPENAI_BASE_URL:-}"
    local model="${OPENAI_MODEL:-}"
    if [ -n "${base_url}" ] && [ -n "${model}" ]; then
        # Sandbox: the container IS the boundary (container-boundary mode).
        # bwrap cannot create userns inside the worker container; running with
        # full access within the hardened container is an explicit, documented
        # dev risk-acceptance, not a silent relaxation (CODIFY_CODEX_SANDBOX
        # can force "read-only" when the host supports bwrap/userns).
        sandbox_mode="${CODIFY_CODEX_SANDBOX:-danger-full-access}"
        cat > "${CODEX_HOME}/config.toml" <<EOF
model = "${model}"
model_provider = "codify"
sandbox_mode = "${sandbox_mode}"

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
    # Codex skills live under CODEX_HOME/AGENTS.md conventions; neutral Skill
    # snapshots are materialized by the runner only when declared available.
    if [ -n "${CODIFY_TASK_SKILLS_DIR:-}" ] && [ -d "${CODIFY_TASK_SKILLS_DIR}" ]; then
        return 0
    fi
    return 0
}

codex_adapter_run() {
    local prompt_file="$1"
    local result_file="$2"
    local raw_file="${CODIFY_HARNESS_RAW_DIR}/codex.jsonl"
    : > "${raw_file}"
    chown 0:0 "${raw_file}"
    chmod 644 "${raw_file}"
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
    [ -s "${result_file}" ] || return 1
    jq -e \
        --arg harness_key codex \
        --arg adapter_version "${CODIFY_ADAPTER_VERSION}" \
        --arg cli_version "${CODIFY_CLI_VERSION}" \
        '{schema:"codify.worker.result/v1",status:"completed",success:true,result:"",
          harness_key:$harness_key,adapter_version:$adapter_version,cli_version:$cli_version,
          session_id:null,model:null,
          usage:{input_tokens:null,cached_input_tokens:null,output_tokens:null,reasoning_tokens:null,cost:null,currency:null,engine_fields:{}},
          failure:null,capability_warnings:[]}' \
        "${result_file}" >/dev/null 2>&1 || return 1
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
