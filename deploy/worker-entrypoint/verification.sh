#!/bin/bash

codify_verify_v2_candidate_manifest() {
    [ -n "${CODIFY_RUNTIME_VERIFICATION_MANIFEST:-}" ] || return 0

    local manifest_path="${CODIFY_RUNTIME_VERIFICATION_MANIFEST}"
    local validator_path="${CODIFY_KIT_HOME:?CODIFY_KIT_HOME is required for V2 candidate verification}/validate-runtime-manifest.py"
    local harness_key="${CODIFY_HARNESS_KEY:?CODIFY_HARNESS_KEY is required for V2 candidate verification}"
    local adapter_path="${CODIFY_ORCHESTRATION_DIR:?CODIFY_ORCHESTRATION_DIR is required for V2 candidate verification}/worker-entrypoint/harness/adapters/${harness_key}.sh"

    [ -r "${manifest_path}" ] || {
        echo "V2 candidate Runtime Bundle manifest is unreadable: ${manifest_path}" >&2
        return 1
    }
    [ -r "${validator_path}" ] || {
        echo "V2 candidate validator is unavailable: ${validator_path}" >&2
        return 1
    }
    python3 "${validator_path}" "${manifest_path}" || return 1
    python3 - "${manifest_path}" "${CODIFY_ORCHESTRATION_DIR}" "${harness_key}" "${adapter_path}" <<'PY'
import hashlib
import json
import pathlib
import sys

manifest_path = pathlib.Path(sys.argv[1])
orchestration_dir = pathlib.Path(sys.argv[2])
key = sys.argv[3]
adapter_path = pathlib.Path(sys.argv[4])
if not key or key in {".", ".."} or "/" in key or "\\" in key:
    raise SystemExit("V2 candidate Harness key is unsafe")
root = orchestration_dir.resolve()
if manifest_path.resolve() != (root / "manifest.json").resolve():
    raise SystemExit("V2 candidate manifest is not the injected orchestration manifest")
candidate_adapter = adapter_path.resolve()
expected_adapter = (root / "worker-entrypoint" / "harness" / "adapters" / f"{key}.sh").resolve()
if candidate_adapter != expected_adapter or root not in candidate_adapter.parents:
    raise SystemExit("V2 candidate Adapter path is unsafe")
if not candidate_adapter.is_file() or candidate_adapter.is_symlink():
    raise SystemExit("V2 candidate Adapter is missing or unsafe")
manifest = json.loads(manifest_path.read_bytes())
evidence = manifest.get("harness_verification_evidence")
if not isinstance(evidence, dict) or evidence.get("harness_key") != key:
    raise SystemExit("V2 candidate evidence Harness key does not match CODIFY_HARNESS_KEY")
adapters = manifest.get("adapters")
selected = adapters.get(key) if isinstance(adapters, dict) else None
if not isinstance(selected, dict) or evidence.get("adapter") != selected.get("adapter"):
    raise SystemExit("V2 candidate evidence Adapter does not match selected Adapter")
relative = pathlib.PurePosixPath("worker-entrypoint") / "harness" / "adapters" / f"{key}.sh"
entry = next((item for item in manifest.get("files") or [] if item.get("path") == relative.as_posix()), None)
if not isinstance(entry, dict):
    raise SystemExit("V2 candidate selected Adapter is not manifested")
payload = candidate_adapter.read_bytes()
if len(payload) != entry.get("size") or hashlib.sha256(payload).hexdigest() != entry.get("sha256"):
    raise SystemExit("V2 candidate selected Adapter bytes do not match manifest")
PY
}

codify_verify_runtime() {
    local require_skill_support=0
    local smoke_command=""
    local command cli_version artifact_helper
    local cli_version_major cli_version_minor cli_version_patch

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

    CODIFY_HARNESS_CLI_BIN="${CODIFY_HARNESS_CLI_BIN:?Missing CODIFY_HARNESS_CLI_BIN}"
    export CODIFY_HARNESS_CLI_BIN

    echo "Codify worker kit ${CODIFY_KIT_VERSION:-unknown}"
    echo "Runtime image: ${CODIFY_RUNTIME_IMAGE:-unknown}"
    for command in bash git curl head jq python3 node codegraph ssh rg tar wc; do
        if ! command -v "${command}" >/dev/null 2>&1 \
            || ! codify_run_shell "command -v '${command}' >/dev/null 2>&1"; then
            echo "Required kit command is unavailable: ${command}" >&2
            return 1
        fi
    done
    case "${CODIFY_HARNESS_CLI_BIN}" in
        /*) ;;
        *)
            echo "CODIFY_HARNESS_CLI_BIN must be an absolute path: ${CODIFY_HARNESS_CLI_BIN}" >&2
            return 1
            ;;
    esac
    if [ ! -x "${CODIFY_HARNESS_CLI_BIN}" ]; then
        echo "Harness CLI is unavailable or not executable: ${CODIFY_HARNESS_CLI_BIN}" >&2
        return 1
    fi
    local adapter_path
    adapter_path="${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/adapters/${CODIFY_HARNESS_KEY:-claude}.sh"
    codify_verify_v2_candidate_manifest || return 1
    if [ -n "${CODIFY_RUNTIME_VERIFICATION_MANIFEST:-}" ] && [ ! -r "${adapter_path}" ]; then
        echo "V2 candidate selected Adapter is unavailable: ${adapter_path}" >&2
        return 1
    fi
    if [ -r "${adapter_path}" ]; then
        CODIFY_RUNTIME_DIR="${CODIFY_RUNTIME_DIR:-/tmp/codify-runtime}"
        mkdir -p "${CODIFY_RUNTIME_DIR}" "${CODIFY_RUNTIME_DIR}/harness-events"
        # shellcheck source=/dev/null
        source "${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/harness/common.sh"
        # shellcheck source=/dev/null
        source "${adapter_path}"
        adapter_verify_runtime || return 1
        cli_version="${CODIFY_CLI_VERSION}"
    else
        cli_version="$(codify_run_shell '"${CODIFY_HARNESS_CLI_BIN}" --version')"
    fi
    echo "${cli_version}"
    if [ "${require_skill_support}" -eq 1 ]; then
        if [[ ! "${cli_version}" =~ ([0-9]+)\.([0-9]+)\.([0-9]+) ]]; then
            echo "Could not parse Harness CLI version required for task skills: ${cli_version}" >&2
            return 1
        fi
        cli_version_major=$((10#${BASH_REMATCH[1]}))
        cli_version_minor=$((10#${BASH_REMATCH[2]}))
        cli_version_patch=$((10#${BASH_REMATCH[3]}))
        if (( cli_version_major < 2 \
            || (cli_version_major == 2 && cli_version_minor < 1) \
            || (cli_version_major == 2 && cli_version_minor == 1 \
                && cli_version_patch < 33) )); then
            echo "Task skills require a compatible Harness CLI; detected: ${cli_version}" >&2
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
