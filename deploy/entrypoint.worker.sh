#!/bin/bash
set -e

# Keep the image entrypoint stable and load implementation modules in lifecycle order.
CODIFY_KIT_HOME="${CODIFY_KIT_HOME:-}"
if [ -n "${CODIFY_KIT_HOME}" ]; then
    ENTRYPOINT_LIB_DIR="${CODIFY_KIT_HOME}/worker-entrypoint"
    CODIFY_BASH="${CODIFY_BASH:?mounted worker kit did not provide CODIFY_BASH}"
    CODIFY_CLAUDE_BIN="${CODIFY_CLAUDE_BIN:-/usr/local/bin/claude}"
    CODIFY_CI_CLAUDE="${CODIFY_KIT_HOME}/ci-claude.sh"
    CODIFY_MERMAID_VALIDATOR="${CODIFY_KIT_BIN}/codify-validate-mermaid"
    CODIFY_RUN_AS="${CODIFY_KIT_HOME}/bin/codify-run-as"
else
    ENTRYPOINT_LIB_DIR="/opt/codify/worker-entrypoint"
    CODIFY_BASH="/bin/bash"
    CODIFY_CLAUDE_BIN="${CODIFY_CLAUDE_BIN:-/usr/local/bin/claude}"
    CODIFY_CI_CLAUDE="/usr/local/bin/ci-claude.sh"
    CODIFY_MERMAID_VALIDATOR="/opt/codify-mermaid/validate_mermaid_summary.mjs"
    CODIFY_RUN_AS=""
fi
CODIFY_RUN_UID="${CODIFY_RUN_UID:-1000}"
CODIFY_RUN_GID="${CODIFY_RUN_GID:-1000}"
CODIFY_RUNTIME_PATH="${CODIFY_RUNTIME_PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"
export CODIFY_BASH CODIFY_CLAUDE_BIN CODIFY_CI_CLAUDE
export CODIFY_MERMAID_VALIDATOR
export CODIFY_RUN_UID CODIFY_RUN_GID CODIFY_RUNTIME_PATH

codify_chown() {
    chown "${CODIFY_RUN_UID}:${CODIFY_RUN_GID}" "$@"
}

codify_run_shell() {
    local command="$1"
    # Login shells may replace PATH from the runtime image's /etc/profile. Restore
    # the composed project-runtime + mounted-kit PATH after profile loading so kit
    # tools remain available when the project image does not provide them.
    command='export PATH="${CODIFY_RUNTIME_PATH}"; '"${command}"
    if [ -n "${CODIFY_RUN_AS}" ]; then
        env HOME=/home/codify USER=codify LOGNAME=codify \
            "${CODIFY_RUN_AS}" -- "${CODIFY_BASH}" -lc "${command}"
    else
        env HOME=/home/codify su -m -s "${CODIFY_BASH}" codify -c "${command}"
    fi
}

if [ "${1:-}" = "--verify" ]; then
    shift
    # shellcheck source=deploy/worker-entrypoint/verification.sh
    source "${ENTRYPOINT_LIB_DIR}/verification.sh"
    codify_verify_runtime "$@"
    exit 0
fi

for module in \
    bootstrap \
    repository-helpers \
    repository \
    gitlab \
    delivery \
    task-environment \
    codegraph \
    runtime \
    main
do
    module_path="${ENTRYPOINT_LIB_DIR}/${module}.sh"
    if [ ! -r "${module_path}" ]; then
        echo "Worker entrypoint module is missing or unreadable: ${module_path}" >&2
        exit 1
    fi
    # shellcheck source=/dev/null
    source "${module_path}"
done
