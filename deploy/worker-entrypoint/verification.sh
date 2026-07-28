#!/bin/bash

codify_verify_runtime() {
    local require_skill_support=0
    local smoke_command=""
    local command claude_version artifact_helper
    local claude_version_major claude_version_minor claude_version_patch

    while [ "$#" -gt 0 ]; do
        case "$1" in
            --require-skill-support)
                require_skill_support=1
                shift
                ;;
            --smoke)
                [ "$#" -eq 2 ] || {
                    echo "--smoke requires exactly one shell command" >&2
                    return 2
                }
                smoke_command="$2"
                shift 2
                ;;
            *)
                echo "Unknown worker-kit verify arguments: $*" >&2
                return 2
                ;;
        esac
    done

    echo "Codify worker kit ${CODIFY_KIT_VERSION:-unknown}"
    echo "Runtime image: ${CODIFY_RUNTIME_IMAGE:-unknown}"
    for command in bash git curl head jq python3 node codegraph ssh rg tar wc; do
        if ! command -v "${command}" >/dev/null 2>&1 \
            || ! codify_run_shell "command -v '${command}' >/dev/null 2>&1"; then
            echo "Required kit command is unavailable: ${command}" >&2
            return 1
        fi
    done
    case "${CODIFY_CLAUDE_BIN}" in
        /*) ;;
        *)
            echo "CODIFY_CLAUDE_BIN must be an absolute path: ${CODIFY_CLAUDE_BIN}" >&2
            return 1
            ;;
    esac
    if [ ! -x "${CODIFY_CLAUDE_BIN}" ]; then
        echo "Claude CLI is unavailable or not executable: ${CODIFY_CLAUDE_BIN}" >&2
        return 1
    fi
    claude_version="$(codify_run_shell '"${CODIFY_CLAUDE_BIN}" --version')"
    echo "${claude_version}"
    if [ "${require_skill_support}" -eq 1 ]; then
        if [[ ! "${claude_version}" =~ ([0-9]+)\.([0-9]+)\.([0-9]+) ]]; then
            echo "Could not parse Claude Code version required for task skills: ${claude_version}" >&2
            return 1
        fi
        claude_version_major=$((10#${BASH_REMATCH[1]}))
        claude_version_minor=$((10#${BASH_REMATCH[2]}))
        claude_version_patch=$((10#${BASH_REMATCH[3]}))
        if (( claude_version_major < 2 \
            || (claude_version_major == 2 && claude_version_minor < 1) \
            || (claude_version_major == 2 && claude_version_minor == 1 \
                && claude_version_patch < 33) )); then
            echo "Task skills require Claude Code 2.1.33 or newer; detected: ${claude_version}" >&2
            return 1
        fi
    fi
    node --version
    python3 --version
    artifact_helper="${ENTRYPOINT_LIB_DIR}/artifacts.py"
    [ -r "${artifact_helper}" ] || {
        echo "Task artifact helper is missing: ${artifact_helper}" >&2
        return 1
    }
    python3 -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); compile(p.read_text(), str(p), "exec")' \
        "${artifact_helper}"
    git --version
    codegraph --version
    printf '# worker-kit smoke\n' > /tmp/codify-worker-kit-summary.md
    "${CODIFY_MERMAID_VALIDATOR}" /tmp/codify-worker-kit-summary.md \
        >/tmp/codify-worker-kit-mermaid.json
    jq -e '.ok == true' /tmp/codify-worker-kit-mermaid.json >/dev/null
    test "$(codify_run_shell 'id -u')" = "${CODIFY_RUN_UID}"
    codify_run_shell \
        'touch /workspace/.codify-worker-kit-write-test && rm -f /workspace/.codify-worker-kit-write-test'
    if [ -n "${smoke_command}" ]; then
        codify_run_shell \
            "export PATH=\"${CODIFY_RUNTIME_PATH}\"; cd /workspace; ${smoke_command}"
    fi
    echo "Worker kit verification passed"
}
