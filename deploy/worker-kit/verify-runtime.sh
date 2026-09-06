#!/usr/bin/env bash
set -euo pipefail

# Host-side Kit/runtime verifier for the Kit-owned CLI model.
#
# Without --runtime-manifest the verifier validates the Kit manifest identity
# and harness inventory, then runs a functionality gate for every present
# Harness (integrity + launcher --verify) while recording absent keys with
# their reason code. A per-Harness gate failure marks only that Harness
# unavailable and does not abort the other keys.
#
# With --runtime-manifest the frozen Runtime Bundle (Task execution truth) is
# additionally validated against the Kit identity and the selected daemon
# image; adapter-declared baseline version/SHA differences are advisory
# sanitized warnings, never gates.
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
[ -f "${KIT_PATH}/verify-kit-content.py" ] || { echo "Worker Kit content verifier is missing" >&2; exit 1; }
[ -z "${RUNTIME_MANIFEST}" ] || [ -r "${RUNTIME_MANIFEST}" ] || { echo "Runtime Bundle manifest is unreadable" >&2; exit 1; }
[ "${VERIFY_ALL}" -eq 0 ] || [ -n "${RUNTIME_MANIFEST}" ] || { echo "--all-harnesses requires --runtime-manifest" >&2; exit 2; }
TRUSTED_CONTENT_VERIFIER="${CODIFY_TRUSTED_KIT_CONTENT_VERIFIER:-${PROJECT_ROOT}/deploy/worker-kit/verify-kit-content.py}"
[ -f "${TRUSTED_CONTENT_VERIFIER}" ] || {
    echo "Trusted Worker Kit content verifier is missing: ${TRUSTED_CONTENT_VERIFIER}" >&2
    exit 2
}
if [ -n "${HARNESS_HOST_PATH}" ]; then
    [ -x "${HARNESS_HOST_PATH}" ] || { echo "Harness executable is not executable" >&2; exit 1; }
    HARNESS_CONTAINER_PATH="${HARNESS_CONTAINER_PATH:-/usr/local/bin/${HARNESS_KEY}}"
    case "${HARNESS_CONTAINER_PATH}" in /*) ;; *) echo "--harness-container-path must be absolute" >&2; exit 2 ;; esac
fi
IMAGE_INSPECT="$(docker image inspect --format '{{json .}}' "${IMAGE}")"
export KIT_PATH RUNTIME_MANIFEST VERIFY_ALL IMAGE_INSPECT HARNESS_KEY PROJECT_ROOT

# Validate the Kit manifest identity + harness inventory host-side.
python3 - "${KIT_PATH}/manifest.json" <<'PY'
import json, pathlib, re, sys
def fail(message):
    print('verify-runtime: ' + message, file=sys.stderr); raise SystemExit(1)
try:
    kit = json.loads(pathlib.Path(sys.argv[1]).read_text())
except (OSError, ValueError) as exc: fail('invalid Kit manifest: ' + str(exc))
if kit.get('schema_version') != 2 or kit.get('manifest_kind') != 'codify.worker.kit-manifest/v1': fail('mounted manifest is not a Kit manifest')
platform = kit.get('platform')
if not isinstance(platform, str) or re.fullmatch(r'linux/[A-Za-z0-9][A-Za-z0-9_.-]*', platform) is None: fail('Kit platform is invalid')
inventory = kit.get('harness_inventory')
if not isinstance(inventory, dict) or set(inventory) != {'pi', 'opencode', 'claude', 'codex'}:
    fail('Kit manifest must record all four harness keys')
for key, entry in inventory.items():
    if not isinstance(entry, dict) or entry.get('availability') not in {'present', 'absent'}:
        fail('Kit inventory entry is invalid: ' + key)
    if entry['availability'] == 'present':
        path = entry.get('path')
        version = entry.get('version')
        digest = entry.get('sha256')
        size = entry.get('size')
        if not isinstance(path, str) or not path.startswith('/opt/codify-kit/'): fail('Kit inventory path is invalid: ' + key)
        if not isinstance(version, str) or not version: fail('Kit inventory version is missing: ' + key)
        if not isinstance(digest, str) or len(digest) != 64 or set(digest) - set('0123456789abcdef'): fail('Kit inventory SHA-256 is invalid: ' + key)
        if not isinstance(size, int) or size <= 0: fail('Kit inventory size is invalid: ' + key)
    else:
        if entry.get('reason_code') not in {'not_selected', 'missing_payload'}:
            fail('Kit inventory absent reason_code is invalid: ' + key)
PY
if ! python3 "${TRUSTED_CONTENT_VERIFIER}" --root "${KIT_PATH}" >/dev/null; then
    echo "verify-runtime: Worker Kit content inventory does not match installed bytes" >&2
    exit 1
fi
[ -n "${RUNTIME_MANIFEST}" ] && {
python3 - "${RUNTIME_MANIFEST}" "${KIT_PATH}/manifest.json" "${IMAGE_INSPECT}" <<'PY'
import hashlib, json, pathlib, re, sys
def fail(message):
    print('verify-runtime: ' + message, file=sys.stderr); raise SystemExit(1)
try:
    runtime = json.loads(pathlib.Path(sys.argv[1]).read_text())
    kit = json.loads(pathlib.Path(sys.argv[2]).read_text())
    image_inspect = json.loads(sys.argv[3])
except (OSError, ValueError) as exc: fail('invalid manifest input: ' + str(exc))
if runtime.get('schema') not in {'codify.worker.runtime-manifest/v2', 'codify.worker.runtime-bundle/v2'}:
    fail('--runtime-manifest must be a stamped runtime-manifest/v2 or runtime-bundle/v2 document')
runtime_platform = runtime.get('runtime_platform')
if not isinstance(runtime_platform, str) or runtime_platform != kit.get('platform'):
    fail('Runtime Bundle platform conflicts with Kit')
worker_image_identity = runtime.get('worker_image_identity')
if not isinstance(worker_image_identity, dict) or worker_image_identity.get('schema') != 'codify.worker-image-identity/v1':
    fail('Worker image identity schema is invalid')
required = ('daemon_key', 'image_reference', 'image_id', 'runtime_platform')
if any(not isinstance(worker_image_identity.get(key), str) or not worker_image_identity[key] for key in required):
    fail('Worker image identity is incomplete')
if worker_image_identity['runtime_platform'] != runtime_platform:
    fail('Worker image identity platform conflicts with runtime_platform')
if re.fullmatch(r'[^@\s]+@sha256:[0-9a-f]{64}', worker_image_identity['image_reference']) is None:
    fail('Worker image identity image_reference is invalid')
if re.fullmatch(r'sha256:[0-9a-f]{64}', worker_image_identity['image_id']) is None:
    fail('Worker image identity image_id is invalid')
repo_digests = image_inspect.get('RepoDigests')
if not isinstance(repo_digests, list) or worker_image_identity['image_reference'] not in repo_digests:
    fail('Worker image repository digest does not match frozen identity')
if image_inspect.get('Id') != worker_image_identity['image_id']:
    fail('Worker image ID does not match frozen identity')
if f"{image_inspect.get('Os')}/{image_inspect.get('Architecture')}" != worker_image_identity['runtime_platform']:
    fail('Worker image platform does not match frozen identity')
# Execution identity: image_identity + kit_identity + bundle_digest. The
# frozen Kit identity must equal the content digest of the mounted manifest.
manifest_sha256 = hashlib.sha256(pathlib.Path(sys.argv[2]).read_bytes()).hexdigest()
kit_identity = runtime.get('worker_kit_identity')
if not isinstance(kit_identity, dict) or kit_identity.get('schema') != 'codify.worker.kit-identity/v1':
    fail('Runtime Bundle Worker Kit identity is missing or invalid')
if kit_identity.get('manifest_sha256') != manifest_sha256:
    fail('Runtime Bundle Worker Kit identity does not match the mounted Kit manifest')
if kit_identity.get('platform') != runtime_platform:
    fail('Runtime Bundle Worker Kit platform conflicts with runtime_platform')
PY
PYTHON_VALIDATION="$(python3 "${KIT_PATH}/validate-runtime-manifest.py" "${RUNTIME_MANIFEST}" 2>&1)" || {
    echo "verify-runtime: ${PYTHON_VALIDATION}" >&2
    exit 1
}
}

kit_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kit_version"])' "${KIT_PATH}/manifest.json")"

# Host-side integrity: the installed payload bytes must match the manifest.
check_payload_integrity() {
    local key="$1" path="$2"
    local expected_sha expected_size observed_sha observed_size
    expected_sha="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["harness_inventory"][sys.argv[2]]["sha256"])' "${KIT_PATH}/manifest.json" "${key}")"
    expected_size="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["harness_inventory"][sys.argv[2]]["size"])' "${KIT_PATH}/manifest.json" "${key}")"
    observed="$(docker run --rm \
        --volume "${KIT_PATH}:/opt/codify-kit:ro" \
        --volume "${KIT_PATH}/nix/store:/nix/store:ro" \
        --entrypoint /bin/sh "${IMAGE}" \
        -c 'sha256sum "$1"; wc -c < "$1"' sh "${path}" 2>/dev/null || true)"
    observed_sha="$(printf '%s\n' "${observed}" | head -n1 | awk '{print $1}')"
    observed_size="$(printf '%s\n' "${observed}" | tail -n1 | tr -d ' ')"
    if [ "${observed_sha}" != "${expected_sha}" ] || [ "${observed_size}" != "${expected_size}" ]; then
        echo "verify-runtime: Kit payload integrity mismatch: ${key} (${path})" >&2
        return 1
    fi
}

run_one() {
    local key="$1" path="$2"
    case "${path}" in
        /*) ;;
        *) echo "verify-runtime: CLI path is not absolute: ${key}" >&2; return 1 ;;
    esac
    # Host-mount break-glass files are not part of the Kit inventory, so no
    # manifest digest applies; the operator authorizes their source. Only
    # Kit-owned inventory paths get the manifest integrity check.
    if [ -z "${HARNESS_HOST_PATH}" ] || [ "${key}" != "${HARNESS_KEY}" ]; then
        check_payload_integrity "${key}" "${path}" || return 1
    fi
    local args=(--rm --user 0:0 --tmpfs /workspace:rw,exec,mode=1777 --volume "${KIT_PATH}:/opt/codify-kit:ro" --volume "${KIT_PATH}/nix/store:/nix/store:ro")
    [ -x "${KIT_PATH}/bridge-selfcheck-${key}" ] || { echo "verify-runtime: self-check missing for ${key}" >&2; return 1; }
    docker run --rm --volume "${KIT_PATH}:/opt/codify-kit:ro" --volume "${KIT_PATH}/nix/store:/nix/store:ro" --entrypoint "/opt/codify-kit/bridge-selfcheck-${key}" "${IMAGE}" "${path}"
    local cli_env_value="CODIFY_HARNESS_CLI_BIN=${path}"
    if [ -n "${HARNESS_HOST_PATH}" ] && [ "${key}" = "${HARNESS_KEY}" ]; then
        args+=(--volume "${HARNESS_HOST_PATH}:${HARNESS_CONTAINER_PATH}:ro")
        cli_env_value="CODIFY_HARNESS_CLI_BIN=${HARNESS_CONTAINER_PATH}"
    fi
    args+=(--entrypoint /opt/codify-kit/launcher --env "CODIFY_KIT_VERSION=${kit_version}" --env "CODIFY_RUNTIME_IMAGE=${IMAGE}" --env "CODIFY_HARNESS_KEY=${key}")
    args+=(--env "${cli_env_value}")
    args+=("${IMAGE}" --verify)
    [ -n "${RUNTIME_MANIFEST}" ] || args+=(--require-skill-support)
    [ -z "${SMOKE}" ] || args+=(--smoke "${SMOKE}")
    docker run "${args[@]}"
}

# The Kit's Nix closure is self-contained: store binaries must never resolve
# libraries from the runtime image. Project images (compiler/toolchain) may set
# LD_LIBRARY_PATH for their own libraries; the launcher must neutralize it when
# it starts the orchestration process tree. This gate replays the polluting
# environment through the real launcher and requires the Kit's own curl to
# still start, proving the neutralization contract for this Kit+image pair.
check_library_path_isolation() {
    local curl_bin lib_dir kit_version
    kit_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kit_version"])' "${KIT_PATH}/manifest.json")"
    curl_bin="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["runtime_bin"]+"/curl")' "${KIT_PATH}/manifest.json")"
    # Locate the image's real system libc directory (the directory that would
    # hijack the closure if LD_LIBRARY_PATH pointed at it).
    lib_dir="$(docker run --rm \
        --volume "${KIT_PATH}:/opt/codify-kit:ro" \
        --volume "${KIT_PATH}/nix/store:/nix/store:ro" \
        --entrypoint /bin/sh "${IMAGE}" \
        -c 'd=""; for c in /lib/*/libc.so.6 /usr/lib/*/libc.so.6 /lib64/libc.so.6 /lib/libc.so.6 /usr/lib/libc.so.6; do [ -e "$c" ] && { d="$(dirname "$c")"; break; }; done; [ -n "$d" ] && printf "%s" "$d"' 2>/dev/null || true)"
    if [ -z "${lib_dir}" ]; then
        echo "verify-runtime: cannot locate the runtime image's libc directory; skipping LD_LIBRARY_PATH isolation gate" >&2
        return 0
    fi
    if docker run --rm \
        --env "LD_LIBRARY_PATH=${lib_dir}" \
        --env "CODIFY_KIT_VERSION=${kit_version}" \
        --volume "${KIT_PATH}:/opt/codify-kit:ro" \
        --volume "${KIT_PATH}/nix/store:/nix/store:ro" \
        --entrypoint /opt/codify-kit/launcher "${IMAGE}" \
        --maintenance-shell "${curl_bin} --version >/dev/null 2>&1" >/dev/null 2>&1; then
        echo "verify-runtime: library isolation OK (Kit launcher neutralizes LD_LIBRARY_PATH=${lib_dir})"
    else
        echo "verify-runtime: FAIL library isolation: the Kit launcher does not neutralize LD_LIBRARY_PATH=${lib_dir}; nix curl from the store cannot start in a polluted runtime image. Upgrade the Kit to a version whose launcher unsets LD_LIBRARY_PATH." >&2
        return 1
    fi
}

# Advisory baseline comparison (runtime-manifest path only): adapter-declared
# tested/baseline version/SHA differences produce sanitized warnings and never
# block execution.
advisory_baseline_warnings() {
    local key="$1"
    [ -n "${RUNTIME_MANIFEST}" ] || return 0
    python3 - "${RUNTIME_MANIFEST}" "${KIT_PATH}/manifest.json" "${key}" <<'PY'
import json, pathlib, sys
runtime = json.loads(pathlib.Path(sys.argv[1]).read_text())
kit = json.loads(pathlib.Path(sys.argv[2]).read_text())
key = sys.argv[3]
adapters = runtime.get('adapters') or {}
entry = kit.get('harness_inventory') or {}
observed = entry.get(key) or {}
baseline = ((adapters.get(key) or {}).get('source') or {})
if observed.get('availability') != 'present':
    print(f"verify-runtime: harness '{key}' is absent from the Kit ({observed.get('reason_code', 'unknown')})")
    raise SystemExit(0)
baseline_version = baseline.get('artifact_version')
baseline_sha = baseline.get('artifact_sha256')
if baseline_version is not None and baseline_version != observed.get('version'):
    print(f"verify-runtime: WARNING harness '{key}' observed version {observed.get('version')} differs from Adapter baseline {baseline_version} (advisory)")
if baseline_sha is not None and baseline_sha != observed.get('sha256'):
    print(f"verify-runtime: WARNING harness '{key}' observed SHA-256 differs from Adapter baseline (advisory)")
PY
}

# Resolve the verification set: explicit host_mount override, or the Kit
# inventory's present keys. Absent keys are recorded with their reason.
ADAPTER_KEYS=""
if [ -n "${HARNESS_HOST_PATH}" ]; then
    ADAPTER_KEYS="${HARNESS_KEY}"
elif [ -n "${RUNTIME_MANIFEST}" ] && [ "${VERIFY_ALL}" -eq 0 ]; then
    # Single-Harness runtime verification: the frozen evidence must name the
    # requested Harness so one key's evidence can never authorize another.
    evidence_key="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["harness_verification_evidence"]["harness_key"])' "${RUNTIME_MANIFEST}")"
    if [ "${evidence_key}" != "${HARNESS_KEY}" ]; then
        echo "verify-runtime: Harness verification evidence harness_key does not match requested Harness" >&2
        exit 1
    fi
    ADAPTER_KEYS="${HARNESS_KEY}"
else
    ADAPTER_KEYS="$(python3 - "${KIT_PATH}/manifest.json" <<'PY'
import json, pathlib, sys
kit = json.loads(pathlib.Path(sys.argv[1]).read_text())
for key, entry in (kit.get('harness_inventory') or {}).items():
    availability = entry.get('availability')
    if availability == 'present':
        print(key)
    else:
        print(f"verify-runtime: harness '{key}' absent ({entry.get('reason_code', 'unknown')})", file=sys.stderr)
PY
)"
fi

# Hard gate: the Kit store must be immune to the image's LD_LIBRARY_PATH
# before any Harness functionality check runs.
if ! check_library_path_isolation; then
    exit 1
fi

overall=0
while IFS= read -r adapter_key; do
    [ -z "${adapter_key}" ] && continue
    path=""
    if [ -n "${HARNESS_HOST_PATH}" ] && [ "${adapter_key}" = "${HARNESS_KEY}" ]; then
        path="${HARNESS_CONTAINER_PATH}"
    else
        path="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["harness_inventory"][sys.argv[2]]["path"])' "${KIT_PATH}/manifest.json" "${adapter_key}")"
    fi
    advisory_baseline_warnings "${adapter_key}" || true
    if ! run_one "${adapter_key}" "${path}"; then
        echo "verify-runtime: harness '${adapter_key}' unavailable (functionality gate failed)" >&2
        overall=1
    fi
done <<< "${ADAPTER_KEYS}"
exit "${overall}"
