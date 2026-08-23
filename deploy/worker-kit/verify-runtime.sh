#!/usr/bin/env bash
set -euo pipefail

# A Kit manifest and a Runtime Bundle manifest are different contracts.  This
# verifier only accepts the latter through --runtime-manifest; it never treats
# the mounted Kit manifest as task orchestration truth.
KIT_PATH="" IMAGE="" SMOKE="" HARNESS_KEY="claude"
HARNESS_HOST_PATH="" HARNESS_CONTAINER_PATH="" RUNTIME_MANIFEST="" VERIFY_ALL=0
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --kit) KIT_PATH="${2:?missing --kit value}"; shift 2 ;;
        --image) IMAGE="${2:?missing --image value}"; shift 2 ;;
        --harness-key) HARNESS_KEY="${2:?missing --harness-key value}"; shift 2 ;;
        --harness-host-path) HARNESS_HOST_PATH="${2:?missing --harness-host-path value}"; shift 2 ;;
        --harness-container-path) HARNESS_CONTAINER_PATH="${2:?missing --harness-container-path value}"; shift 2 ;;
        --runtime-manifest) RUNTIME_MANIFEST="${2:?missing --runtime-manifest value}"; shift 2 ;;
        --all-harnesses) VERIFY_ALL=1; shift ;;
        --claude-host-path) HARNESS_KEY=claude; HARNESS_HOST_PATH="${2:?missing --claude-host-path value}"; shift 2 ;;
        --claude-container-path) HARNESS_CONTAINER_PATH="${2:?missing --claude-container-path value}"; shift 2 ;;
        --smoke) SMOKE="${2:?missing --smoke value}"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done
[ -n "${KIT_PATH}" ] || { echo "--kit is required" >&2; exit 2; }
[ -n "${IMAGE}" ] || { echo "--image is required" >&2; exit 2; }
[ -x "${KIT_PATH}/launcher" ] || { echo "Invalid worker kit: ${KIT_PATH}" >&2; exit 1; }
[ -d "${KIT_PATH}/nix/store" ] || { echo "Worker kit Nix store is missing" >&2; exit 1; }
[ -r "${KIT_PATH}/manifest.json" ] || { echo "Worker Kit manifest is missing" >&2; exit 1; }
[ -z "${RUNTIME_MANIFEST}" ] || [ -r "${RUNTIME_MANIFEST}" ] || { echo "Runtime Bundle manifest is unreadable" >&2; exit 1; }
[ "${VERIFY_ALL}" -eq 0 ] || [ -n "${RUNTIME_MANIFEST}" ] || { echo "--all-harnesses requires --runtime-manifest" >&2; exit 2; }
if [ -n "${HARNESS_HOST_PATH}" ]; then
    [ -x "${HARNESS_HOST_PATH}" ] || { echo "Harness executable is not executable" >&2; exit 1; }
    HARNESS_CONTAINER_PATH="${HARNESS_CONTAINER_PATH:-/usr/local/bin/${HARNESS_KEY}}"
    case "${HARNESS_CONTAINER_PATH}" in /*) ;; *) echo "--harness-container-path must be absolute" >&2; exit 2 ;; esac
fi
docker image inspect "${IMAGE}" >/dev/null

IMAGE_ARTIFACT_MANIFEST=""
if [ -n "${RUNTIME_MANIFEST}" ]; then
    IMAGE_ARTIFACT_MANIFEST="$(docker run --rm --entrypoint cat "${IMAGE}" /etc/codify-worker-cli-artifacts.json)"
fi
export KIT_PATH RUNTIME_MANIFEST VERIFY_ALL IMAGE_ARTIFACT_MANIFEST HARNESS_KEY PROJECT_ROOT
if [ -z "${RUNTIME_MANIFEST}" ]; then
    ADAPTER_KEYS="${HARNESS_KEY}"
else
ADAPTER_KEYS="$(python3 - <<'PY'
import hashlib, json, os, pathlib, sys
def fail(message):
    print('verify-runtime: ' + message, file=sys.stderr); raise SystemExit(1)
try:
    kit = json.loads((pathlib.Path(os.environ['KIT_PATH']) / 'manifest.json').read_text())
    image = json.loads(os.environ['IMAGE_ARTIFACT_MANIFEST'])
except (OSError, ValueError) as exc: fail('invalid manifest input: ' + str(exc))
if kit.get('schema_version') != 2 or kit.get('manifest_kind') != 'codify.worker.kit-manifest/v1': fail('mounted manifest is not a Kit manifest')
platform = kit.get('platform')
compat, requirements = kit.get('runtime_compatibility') or {}, kit.get('cli_requirements') or {}
if not isinstance(platform, str) or not platform.startswith('linux/'): fail('Kit platform is invalid')
if image.get('schema') != 'codify.worker.cli-artifacts/v1' or image.get('platform') != platform: fail('runtime image artifact platform conflicts with Kit')
artifacts = image.get('artifacts') or {}
if set(requirements) != {'claude', 'codex', 'pi', 'opencode'}: fail('Kit must declare all four CLI requirements')
for key, expected in requirements.items():
    actual = artifacts.get(key) or {}; digest = actual.get('sha256')
    if actual.get('path') != expected.get('path') or actual.get('version') != expected.get('version'): fail('runtime image CLI mismatch: ' + key)
    if not isinstance(digest, str) or len(digest) != 64 or set(digest) - set('0123456789abcdef'): fail('runtime image CLI SHA-256 is invalid: ' + key)
runtime_path = os.environ['RUNTIME_MANIFEST']
if not runtime_path:
    print(os.environ['HARNESS_KEY']); raise SystemExit(0)
try: runtime = json.loads(pathlib.Path(runtime_path).read_text())
except (OSError, ValueError) as exc: fail('invalid Runtime Bundle manifest: ' + str(exc))
runtime_schema = runtime.get('schema')
if runtime_schema not in {
    'codify.worker.runtime-manifest/v2',
    'codify.worker.runtime-bundle/v2',
}:
    fail('--runtime-manifest must be a stamped runtime-manifest/v2 or runtime-bundle/v2 document, not a Kit manifest')
files = runtime.get('files')
if not isinstance(files, list) or not files:
    fail('Runtime Bundle must contain a non-empty frozen files list')
seen_paths = set()
for entry in files:
    if not isinstance(entry, dict):
        fail('Runtime Bundle file entries must be objects')
    path = entry.get('path')
    if (
        not isinstance(path, str)
        or path in {'', '.'}
        or '\\' in path
        or pathlib.PurePosixPath(path).is_absolute()
        or '..' in pathlib.PurePosixPath(path).parts
    ):
        fail('Runtime Bundle contains an unsafe file path')
    if path in seen_paths:
        fail('Runtime Bundle contains duplicate file paths: ' + path)
    seen_paths.add(path)
    size, digest = entry.get('size'), entry.get('sha256')
    if not isinstance(size, int) or size < 0:
        fail('Runtime Bundle file size is invalid: ' + path)
    if not isinstance(digest, str) or len(digest) != 64 or set(digest) - set('0123456789abcdef'):
        fail('Runtime Bundle file SHA-256 is invalid: ' + path)
if runtime_schema == 'codify.worker.runtime-bundle/v2':
    if not isinstance(runtime.get('bundle_digest'), str) or len(runtime['bundle_digest']) != 64 or set(runtime['bundle_digest']) - set('0123456789abcdef'):
        fail('Runtime Bundle bundle_digest is missing or invalid')
    canonical = [
        {'path': entry['path'], 'size': entry['size'], 'sha256': entry['sha256']}
        for entry in sorted(files, key=lambda item: item['path'])
    ]
    calculated = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()
    if calculated != runtime['bundle_digest']:
        fail('Runtime Bundle bundle_digest does not match its frozen files')
if runtime_schema == 'codify.worker.runtime-bundle/v2':
    # A persisted frozen Bundle keeps the build-time nested Adapter identity.
    # The launcher projection is a separate, container-internal shape and is
    # deliberately not accepted as release verification input.
    for key, adapter in (runtime.get('adapters') or {}).items():
        if not isinstance(adapter, dict) or not isinstance(adapter.get('adapter'), dict):
            fail('runtime-bundle/v2 Adapter identity must be nested under adapter: ' + key)
validator = pathlib.Path(os.environ['KIT_PATH']) / 'validate-runtime-manifest.py'
if not validator.is_file():
    fail('Kit is missing the authoritative Runtime Bundle validator')
if runtime.get('contract_version') not in (compat.get('harness_contracts') or ()) or runtime.get('event_schema') not in (compat.get('event_schemas') or ()): fail('Runtime Bundle contract/event conflicts with Kit')
adapters = runtime.get('adapters')
if not isinstance(adapters, dict) or not adapters: fail('Runtime Bundle adapters are missing')
if os.environ['VERIFY_ALL'] == '1' and set(adapters) != set(requirements):
    fail('VERIFY_ALL requires exactly the four Kit Harness adapters')
for key, adapter in adapters.items():
    if key not in requirements: fail('Runtime Bundle adapter is not supplied by Kit: ' + key)
    source, artifact = adapter.get('source') or {}, artifacts[key]
    if source.get('artifact_version') != artifact['version'] or source.get('artifact_sha256') != artifact['sha256']: fail('Runtime Bundle artifact identity conflicts with image: ' + key)
    identity = adapter.get('adapter')
    if not isinstance(identity, dict) or not isinstance(identity.get('version'), str) or not identity['version']:
        fail('Runtime Bundle adapter version is missing: ' + key)
    digest = identity.get('digest')
    if not isinstance(digest, str) or len(digest) != 64 or set(digest) - set('0123456789abcdef'):
        fail('Runtime Bundle adapter digest is missing or invalid: ' + key)
    if adapter.get('support_tier') in {'default', 'first-class'} and not (pathlib.Path(os.environ['KIT_PATH']) / ('bridge-selfcheck-' + key)).is_file(): fail('first-class adapter lacks self-check: ' + key)
keys = sorted(adapters) if os.environ['VERIFY_ALL'] == '1' else [os.environ['HARNESS_KEY']]
if any(key not in adapters for key in keys): fail('requested harness is absent from Runtime Bundle')
print('\n'.join(keys))
PY
)"
fi

if [ -n "${RUNTIME_MANIFEST}" ]; then
PYTHON_VALIDATION="$(python3 "${KIT_PATH}/validate-runtime-manifest.py" "${RUNTIME_MANIFEST}" 2>&1)" || {
    echo "verify-runtime: ${PYTHON_VALIDATION}" >&2
    exit 1
}
fi

kit_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kit_version"])' "${KIT_PATH}/manifest.json")"
run_one() {
    local key="$1" path
    if [ -n "${RUNTIME_MANIFEST}" ]; then
        path="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["cli_requirements"][sys.argv[2]]["path"])' "${KIT_PATH}/manifest.json" "${key}")"
    else
        path="${HARNESS_CONTAINER_PATH:-/usr/local/bin/${key}}"
    fi
    case "${path}" in
        /*) ;;
        *) echo "verify-runtime: CLI path is not absolute: ${key}" >&2; return 1 ;;
    esac
    if [ -n "${RUNTIME_MANIFEST}" ]; then
        local expected_cli_sha actual_cli_sha
        expected_cli_sha="$(python3 -c 'import json,os,sys; print(json.loads(os.environ["IMAGE_ARTIFACT_MANIFEST"])["artifacts"][sys.argv[1]]["sha256"])' "${key}")"
        case "${expected_cli_sha}" in
            [0-9a-f][0-9a-f]*) ;;
            *) echo "verify-runtime: image CLI SHA-256 is invalid: ${key}" >&2; return 1 ;;
        esac
        if [ "${#expected_cli_sha}" -ne 64 ]; then
            echo "verify-runtime: image CLI SHA-256 is invalid: ${key}" >&2
            return 1
        fi
        actual_cli_sha="$(docker run --rm --entrypoint /bin/sh "${IMAGE}" -c 'test -f "$1" && test -x "$1" && sha256sum "$1" | awk '\''{print $1}'\''' sh "${path}")"
        if [ "${actual_cli_sha}" != "${expected_cli_sha}" ]; then
            echo "verify-runtime: runtime image CLI SHA-256 mismatch: ${key}" >&2
            return 1
        fi
    fi
    local args=(--rm --user 0:0 --tmpfs /workspace:rw,exec,mode=1777 --volume "${KIT_PATH}:/opt/codify-kit:ro" --volume "${KIT_PATH}/nix/store:/nix/store:ro")
    if [ -n "${RUNTIME_MANIFEST}" ]; then
        [ -x "${KIT_PATH}/bridge-selfcheck-${key}" ] || { echo "verify-runtime: self-check missing for ${key}" >&2; return 1; }
        docker run --rm --volume "${KIT_PATH}:/opt/codify-kit:ro" --volume "${KIT_PATH}/nix/store:/nix/store:ro" --entrypoint "/opt/codify-kit/bridge-selfcheck-${key}" "${IMAGE}" "${path}"
        local cli_env_value="CODIFY_HARNESS_CLI_BIN=${path}"
    else
        legacy_env="CODIFY_$(printf '%s' "${key}" | tr '[:lower:]' '[:upper:]')_BIN"
        local cli_env_value="${legacy_env}=${path}"
    fi
    if [ -n "${HARNESS_HOST_PATH}" ] && [ "${key}" = "${HARNESS_KEY}" ]; then
        local cli_env="CODIFY_$(printf '%s' "${key}" | tr '[:lower:]' '[:upper:]')_BIN"
        args+=(--volume "${HARNESS_HOST_PATH}:${HARNESS_CONTAINER_PATH}:ro")
        cli_env_value="${cli_env}=${HARNESS_CONTAINER_PATH}"
    fi
    args+=(--entrypoint /opt/codify-kit/launcher --env "CODIFY_KIT_VERSION=${kit_version}" --env "CODIFY_RUNTIME_IMAGE=${IMAGE}" --env "CODIFY_HARNESS_KEY=${key}")
    args+=(--env "${cli_env_value}")
    args+=("${IMAGE}" --verify)
    [ -n "${RUNTIME_MANIFEST}" ] || args+=(--require-skill-support)
    [ -z "${SMOKE}" ] || args+=(--smoke "${SMOKE}")
    docker run "${args[@]}"
}
while IFS= read -r adapter_key; do [ -z "${adapter_key}" ] || run_one "${adapter_key}"; done <<< "${ADAPTER_KEYS}"
