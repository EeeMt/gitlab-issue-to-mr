#!/bin/bash
set -e

# Keep the image entrypoint stable and load implementation modules in lifecycle order.
CODIFY_KIT_HOME="${CODIFY_KIT_HOME:-}"
if [ -n "${CODIFY_KIT_HOME}" ]; then
    ENTRYPOINT_LIB_DIR="${CODIFY_KIT_HOME}/worker-entrypoint"
    CODIFY_BASH="${CODIFY_BASH:?mounted worker kit did not provide CODIFY_BASH}"
     CODIFY_CI_CLAUDE="/usr/local/bin/ci-claude.sh"
    CODIFY_MERMAID_VALIDATOR="${CODIFY_KIT_BIN}/codify-validate-mermaid"
    CODIFY_RUN_AS="${CODIFY_KIT_HOME}/bin/codify-run-as"
else
    ENTRYPOINT_LIB_DIR="/opt/codify/worker-entrypoint"
    CODIFY_BASH="/bin/bash"
     CODIFY_CI_CLAUDE="${CODIFY_KIT_HOME}/ci-claude.sh"
    CODIFY_MERMAID_VALIDATOR="/opt/codify-mermaid/validate_mermaid_summary.mjs"
    CODIFY_RUN_AS=""
fi

codify_verify_runtime_snapshot() {
    local manifest_path="$1"
    python3 - "${manifest_path}" \
        "${CODIFY_RUNTIME_MANIFEST_DIGEST:?Missing CODIFY_RUNTIME_MANIFEST_DIGEST}" \
        "${CODIFY_RUNTIME_CONTRACT_VERSION:?Missing CODIFY_RUNTIME_CONTRACT_VERSION}" \
        "${CODIFY_HARNESS_KEY:?Missing CODIFY_HARNESS_KEY}" \
        "${CODIFY_ADAPTER_VERSION:?Missing CODIFY_ADAPTER_VERSION}" <<'PY'
import hashlib
import json
import pathlib
import sys

manifest_path = pathlib.Path(sys.argv[1]).resolve()
expected_digest, expected_contract, harness_key, adapter_version = sys.argv[2:]
manifest_bytes = manifest_path.read_bytes()
if hashlib.sha256(manifest_bytes).hexdigest() != expected_digest:
    raise SystemExit("Runtime Bundle manifest digest mismatch")
manifest = json.loads(manifest_bytes)
if manifest.get("contract_version") != expected_contract:
    raise SystemExit("Runtime Bundle contract does not match the Task binding")
adapter = (manifest.get("adapters") or {}).get(harness_key) or {}
if adapter.get("version") != adapter_version or not adapter.get("digest"):
    raise SystemExit("Runtime Bundle Adapter does not match the Task binding")
root = manifest_path.parent
expected_paths = set()
for entry in manifest.get("files") or []:
    relative = pathlib.PurePosixPath(str(entry.get("path") or ""))
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise SystemExit("Runtime Bundle manifest contains an unsafe path")
    path = (root / pathlib.Path(*relative.parts)).resolve()
    if root not in path.parents or not path.is_file() or path.is_symlink():
        raise SystemExit(f"Runtime Bundle file is unsafe or missing: {relative}")
    payload = path.read_bytes()
    if len(payload) != entry.get("size"):
        raise SystemExit(f"Runtime Bundle file size mismatch: {relative}")
    if hashlib.sha256(payload).hexdigest() != entry.get("sha256"):
        raise SystemExit(f"Runtime Bundle file digest mismatch: {relative}")
    expected_paths.add(relative.as_posix())
if "entrypoint.sh" not in expected_paths:
    raise SystemExit("Runtime Bundle entrypoint is not manifested")
PY
}

# Task execution always uses the immutable orchestration snapshot uploaded
# before the container starts. The Kit-local implementation is available only
# to `--verify`, which validates a newly installed Kit before profile rollout.
if [ -r "/tmp/codify-runtime/orchestration/manifest.json" ]; then
    CODIFY_ORCHESTRATION_DIR="/tmp/codify-runtime/orchestration"
    codify_verify_runtime_snapshot "${CODIFY_ORCHESTRATION_DIR}/manifest.json"
    ENTRYPOINT_LIB_DIR="${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint"
    CODIFY_CI_CLAUDE="${CODIFY_ORCHESTRATION_DIR}/legacy/ci-claude.sh"
else
    if [ "${1:-}" != "--verify" ]; then
        echo "Task Runtime Bundle manifest is required; legacy Kit fallback is disabled" >&2
        exit 1
    fi
    CODIFY_ORCHESTRATION_DIR="${ENTRYPOINT_LIB_DIR%/worker-entrypoint}"
fi
CODIFY_RUN_UID="${CODIFY_RUN_UID:-1000}"
CODIFY_RUN_GID="${CODIFY_RUN_GID:-1000}"
CODIFY_RUNTIME_PATH="${CODIFY_RUNTIME_PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"
export CODIFY_BASH CODIFY_CLAUDE_BIN CODIFY_CI_CLAUDE CODIFY_ORCHESTRATION_DIR
export CODIFY_HARNESS_CLI_BIN
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
    harness/common \
    harness/runner \
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
