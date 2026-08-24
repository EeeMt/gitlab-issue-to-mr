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
IMAGE_INSPECT="$(docker image inspect --format '{{json .}}' "${IMAGE}")"

IMAGE_ARTIFACT_MANIFEST=""
if [ -n "${RUNTIME_MANIFEST}" ]; then
    IMAGE_ARTIFACT_MANIFEST="$(docker run --rm --entrypoint cat "${IMAGE}" /etc/codify-worker-cli-artifacts.json)"
    IMAGE_ARTIFACT_LOCK_SHA256="$(docker run --rm --entrypoint /bin/sh "${IMAGE}" -c 'sha256sum "$1" | awk '\''{print $1}'\''' sh /etc/codify-worker-cli-artifacts.json)"
fi
export KIT_PATH RUNTIME_MANIFEST VERIFY_ALL IMAGE_ARTIFACT_MANIFEST IMAGE_ARTIFACT_LOCK_SHA256 IMAGE_INSPECT HARNESS_KEY PROJECT_ROOT
if [ -z "${RUNTIME_MANIFEST}" ]; then
    ADAPTER_KEYS="${HARNESS_KEY}"
else
ADAPTER_KEYS="$(python3 - <<'PY'
import hashlib, json, os, pathlib, re, sys
from datetime import datetime
def fail(message):
    print('verify-runtime: ' + message, file=sys.stderr); raise SystemExit(1)
try:
    kit = json.loads((pathlib.Path(os.environ['KIT_PATH']) / 'manifest.json').read_text())
    image = json.loads(os.environ['IMAGE_ARTIFACT_MANIFEST'])
    image_inspect = json.loads(os.environ['IMAGE_INSPECT'])
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
    # A persisted frozen Bundle keeps the build-time nested Adapter identity.
    # The launcher projection is a separate, container-internal shape and is
    # deliberately not accepted as release verification input.
    for key, adapter in (runtime.get('adapters') or {}).items():
        if not isinstance(adapter, dict) or not isinstance(adapter.get('adapter'), dict):
            fail('runtime-bundle/v2 Adapter identity must be nested under adapter: ' + key)
runtime_platform = runtime.get('runtime_platform')
worker_image_identity = runtime.get('worker_image_identity')
if not isinstance(worker_image_identity, dict) or worker_image_identity.get('schema') != 'codify.worker-image-identity/v1':
    fail('Worker image identity schema is invalid')
required_identity = ('daemon_key', 'image_reference', 'image_id', 'runtime_platform', 'cli_artifact_lock_sha256')
if any(not isinstance(worker_image_identity.get(key), str) or not worker_image_identity[key] for key in required_identity):
    fail('Worker image identity is incomplete')
if any(char.isspace() for char in worker_image_identity['daemon_key']):
    fail('Worker image identity daemon_key is invalid')
if re.fullmatch(r'[^@\s]+@sha256:[0-9a-f]{64}', worker_image_identity['image_reference']) is None:
    fail('Worker image identity image_reference is invalid')
if re.fullmatch(r'sha256:[0-9a-f]{64}', worker_image_identity['image_id']) is None:
    fail('Worker image identity image_id is invalid')
if re.fullmatch(r'linux/[A-Za-z0-9][A-Za-z0-9_.-]*', worker_image_identity['runtime_platform']) is None:
    fail('Worker image identity runtime_platform is invalid')
if worker_image_identity['runtime_platform'] != runtime_platform:
    fail('Worker image identity platform conflicts with runtime_platform')
if re.fullmatch(r'[0-9a-f]{64}', worker_image_identity['cli_artifact_lock_sha256']) is None:
    fail('Worker image identity CLI lock digest is invalid')
repo_digests = image_inspect.get('RepoDigests')
if not isinstance(repo_digests, list) or worker_image_identity['image_reference'] not in repo_digests:
    fail('Worker image repository digest does not match frozen identity')
if image_inspect.get('Id') != worker_image_identity['image_id']:
    fail('Worker image ID does not match frozen identity')
if f"{image_inspect.get('Os')}/{image_inspect.get('Architecture')}" != worker_image_identity['runtime_platform']:
    fail('Worker image platform does not match frozen identity')
if os.environ.get('IMAGE_ARTIFACT_LOCK_SHA256') != worker_image_identity['cli_artifact_lock_sha256']:
    fail('Worker image CLI artifact lock bytes do not match frozen identity')
harness_verification_evidence = runtime.get('harness_verification_evidence')
if not isinstance(harness_verification_evidence, dict) or harness_verification_evidence.get('schema') != 'codify.worker-harness-verification/v1':
    fail('Harness verification evidence schema is invalid')
if harness_verification_evidence.get('contract_version') != 'codify.worker.harness/v2':
    fail('Harness verification evidence contract_version is invalid')
if re.fullmatch(r'[0-9a-f]{64}', harness_verification_evidence.get('verification_input_digest', '')) is None:
    fail('Harness verification evidence verification_input_digest is invalid')
generation = harness_verification_evidence.get('generation')
if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
    fail('Harness verification evidence generation is invalid')
verified_at = harness_verification_evidence.get('verified_at')
if not isinstance(verified_at, str) or not verified_at:
    fail('Harness verification evidence verified_at is invalid')
try:
    parsed_verified_at = datetime.fromisoformat(verified_at.replace('Z', '+00:00'))
except ValueError:
    fail('Harness verification evidence verified_at is invalid')
if parsed_verified_at.tzinfo is None:
    fail('Harness verification evidence verified_at is invalid')
if harness_verification_evidence.get('image_identity') != worker_image_identity:
    fail('Harness verification evidence image_identity conflicts with Worker image identity')
def bundle_digest(files, worker_image_identity, harness_verification_evidence):
    file_digest = hashlib.sha256(json.dumps([
        {'path': entry['path'], 'size': entry['size'], 'sha256': entry['sha256']}
        for entry in sorted(files, key=lambda item: item['path'])
    ], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if worker_image_identity is None:
        fail('Worker image identity is required')
    if harness_verification_evidence is None:
        fail('Harness verification evidence is required')
    return hashlib.sha256(json.dumps(
        {
            'files_digest': file_digest,
            'worker_image_identity': worker_image_identity,
            'harness_verification_evidence': harness_verification_evidence,
        },
        ensure_ascii=False, sort_keys=True, separators=(',', ':')
    ).encode()).hexdigest()
validator = pathlib.Path(os.environ['KIT_PATH']) / 'validate-runtime-manifest.py'
if not validator.is_file():
    fail('Kit is missing the authoritative Runtime Bundle validator')
if runtime.get('contract_version') not in (compat.get('harness_contracts') or ()) or runtime.get('event_schema') not in (compat.get('event_schemas') or ()): fail('Runtime Bundle contract/event conflicts with Kit')
runtime_platform = runtime.get('runtime_platform')
if not isinstance(runtime_platform, str) or len(runtime_platform) <= len('linux/') or not runtime_platform.startswith('linux/'):
    fail('Runtime Bundle platform is missing or invalid')
if runtime_platform != platform:
    fail('Runtime Bundle platform conflicts with Kit/runtime image')
adapters = runtime.get('adapters')
if not isinstance(adapters, dict) or not adapters: fail('Runtime Bundle adapters are missing')
evidence_harness_key = harness_verification_evidence.get('harness_key')
if not isinstance(evidence_harness_key, str) or evidence_harness_key not in adapters:
    fail('Harness verification evidence harness_key is invalid or absent from Runtime Bundle')
evidence_adapter = harness_verification_evidence.get('adapter')
if (
    not isinstance(evidence_adapter, dict)
    or not isinstance(evidence_adapter.get('version'), str)
    or not evidence_adapter['version']
    or re.fullmatch(r'[0-9a-f]{64}', evidence_adapter.get('digest', '')) is None
):
    fail('Harness verification evidence adapter is invalid')
selected_runtime_adapter = adapters[evidence_harness_key].get('adapter') if isinstance(adapters[evidence_harness_key], dict) else None
if evidence_adapter != selected_runtime_adapter:
    fail('Harness verification evidence adapter conflicts with selected Runtime Bundle adapter')
if os.environ['VERIFY_ALL'] != '1' and evidence_harness_key != os.environ['HARNESS_KEY']:
    fail('Harness verification evidence harness_key does not match requested Harness')
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
if not isinstance(runtime.get('bundle_digest'), str) or re.fullmatch(r'[0-9a-f]{64}', runtime['bundle_digest']) is None:
    fail('Runtime Bundle bundle_digest is missing or invalid')
if bundle_digest(files, worker_image_identity, harness_verification_evidence) != runtime['bundle_digest']:
    fail('Runtime Bundle bundle_digest does not match its frozen files')
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
