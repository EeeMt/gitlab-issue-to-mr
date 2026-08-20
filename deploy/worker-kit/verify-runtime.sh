#!/usr/bin/env bash
set -euo pipefail

KIT_PATH=""
IMAGE=""
SMOKE=""
HARNESS_KEY="claude"
HARNESS_HOST_PATH=""
HARNESS_CONTAINER_PATH=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --kit) KIT_PATH="${2:?missing --kit value}"; shift 2 ;;
        --image) IMAGE="${2:?missing --image value}"; shift 2 ;;
        --harness-key) HARNESS_KEY="${2:?missing --harness-key value}"; shift 2 ;;
        --harness-host-path) HARNESS_HOST_PATH="${2:?missing --harness-host-path value}"; shift 2 ;;
        --harness-container-path) HARNESS_CONTAINER_PATH="${2:?missing --harness-container-path value}"; shift 2 ;;
        --claude-host-path) HARNESS_KEY="claude"; HARNESS_HOST_PATH="${2:?missing --claude-host-path value}"; shift 2 ;;
        --claude-container-path) HARNESS_CONTAINER_PATH="${2:?missing --claude-container-path value}"; shift 2 ;;
        --smoke) SMOKE="${2:?missing --smoke value}"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

[ -n "${KIT_PATH}" ] || { echo "--kit is required" >&2; exit 2; }
[ -n "${IMAGE}" ] || { echo "--image is required" >&2; exit 2; }
[ -x "${KIT_PATH}/launcher" ] || { echo "Invalid worker kit: ${KIT_PATH}" >&2; exit 1; }
[ -d "${KIT_PATH}/nix/store" ] || { echo "Worker kit Nix store is missing" >&2; exit 1; }
case "${HARNESS_KEY}" in
    claude|codex) ;;
    *) echo "Unsupported --harness-key: ${HARNESS_KEY} (expected claude|codex)" >&2; exit 2 ;;
esac
if [ -n "${HARNESS_HOST_PATH}" ] && [ -z "${HARNESS_CONTAINER_PATH}" ]; then
    case "${HARNESS_KEY}" in
        claude) HARNESS_CONTAINER_PATH="/usr/local/bin/claude" ;;
        codex) HARNESS_CONTAINER_PATH="/usr/local/bin/codex" ;;
    esac
fi
if [ -n "${HARNESS_HOST_PATH}" ]; then
    [ -x "${HARNESS_HOST_PATH}" ] || { echo "Harness executable is not executable: ${HARNESS_HOST_PATH}" >&2; exit 1; }
    case "${HARNESS_CONTAINER_PATH}" in
        /*) ;;
        *) echo "--harness-container-path must be absolute" >&2; exit 2 ;;
    esac
fi
docker image inspect "${IMAGE}" >/dev/null

# ── Manifest-driven mode (V2) ───────────────────────────────────────────────
# When the kit's manifest.json is a codify.worker.runtime-manifest/v2, iterate
# its `.adapters` generically (support_tier / artifact_version / control kind /
# model_protocols / capabilities) instead of the hardcoded claude/codex case and
# run a per-adapter Bridge self-check hook. Otherwise fall back to the legacy
# claude/codex path below so V1 kits still verify exactly as before.
MANIFEST_DRIVEN=0
if command -v python3 >/dev/null 2>&1; then
    if python3 - "${KIT_PATH}/manifest.json" <<'PY2DETECT'
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    raise SystemExit(1)
adapters = data.get("adapters")
if data.get("schema") == "codify.worker.runtime-manifest/v2" \
        and isinstance(adapters, dict) and adapters \
        and all(isinstance(a, dict) for a in adapters.values()):
    raise SystemExit(0)
raise SystemExit(1)
PY2DETECT
    then
        MANIFEST_DRIVEN=1
    fi
fi

if [ "${MANIFEST_DRIVEN}" -eq 1 ]; then
    echo "verify-runtime: manifest-driven mode (runtime-manifest/v2)"
    python3 - "${KIT_PATH}/manifest.json" <<'PY2'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
for key in sorted(data.get("adapters") or {}):
    ad = data["adapters"][key]
    src = ad.get("source") or {}
    ct = ad.get("control_transport") or {}
    meta = ad.get("adapter") or {}
    caps = ad.get("capabilities") or {}
    print("\t".join([
        key,
        str(ad.get("support_tier") or ""),
        str(src.get("artifact_version") or ""),
        str(ct.get("kind") or ""),
        ",".join(ad.get("model_protocols") or []),
        str(meta.get("version") or ""),
        ",".join(sorted(k for k, v in caps.items() if v)),
    ]))
PY2
    python3 - "${KIT_PATH}/manifest.json" <<'PY2LOOP'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
for key in sorted(data.get("adapters") or {}):
    print(key)
PY2LOOP
    while IFS= read -r adapter_key; do
        echo "  bridge self-check hook: ${adapter_key}"
        if [ -x "${KIT_PATH}/bridge-selfcheck-${adapter_key}" ]; then
            "${KIT_PATH}/bridge-selfcheck-${adapter_key}" \
                || { echo "verify-runtime: ${adapter_key} bridge self-check failed" >&2; exit 1; }
        else
            echo "    (no bridge-selfcheck-${adapter_key} present; skipped)"
        fi
    done < <(python3 - "${KIT_PATH}/manifest.json" <<'PY2KEYS'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
for key in sorted(data.get("adapters") or {}):
    print(key)
PY2KEYS
)
    exit 0
fi

VERSION="$(sed -n 's/.*"kit_version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${KIT_PATH}/manifest.json")"
[ -n "${VERSION}" ] || { echo "Could not read kit version" >&2; exit 1; }

skill_capable_kit=0
if [[ "${VERSION}" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
    version_major=$((10#${BASH_REMATCH[1]}))
    version_minor=$((10#${BASH_REMATCH[2]}))
    version_patch=$((10#${BASH_REMATCH[3]}))
    if (( version_major > 0 \
        || version_minor > 3 \
        || (version_minor == 3 && version_patch >= 5) )); then
        skill_capable_kit=1
    fi
fi

ARGS=(
    --rm
    --user 0:0
    --tmpfs /workspace:rw,exec,mode=1777
    --volume "${KIT_PATH}:/opt/codify-kit:ro"
    --volume "${KIT_PATH}/nix/store:/nix/store:ro"
)
if [ -n "${HARNESS_HOST_PATH}" ]; then
    ARGS+=(--volume "${HARNESS_HOST_PATH}:${HARNESS_CONTAINER_PATH}:ro")
fi
ARGS+=(
    --entrypoint /opt/codify-kit/launcher
    --env "CODIFY_KIT_VERSION=${VERSION}"
    --env "CODIFY_RUNTIME_IMAGE=${IMAGE}"
    --env "CODIFY_HARNESS_KEY=${HARNESS_KEY}"
)
if [ -n "${HARNESS_HOST_PATH}" ]; then
    case "${HARNESS_KEY}" in
        claude) ARGS+=(--env "CODIFY_CLAUDE_BIN=${HARNESS_CONTAINER_PATH}") ;;
        codex)
            ARGS+=(
                --env "CODIFY_CODEX_BIN=${HARNESS_CONTAINER_PATH}"
                --env "CODIFY_HARNESS_CLI_BIN=${HARNESS_CONTAINER_PATH}"
            )
            ;;
    esac
fi
ARGS+=("${IMAGE}" --verify)
if [ "${skill_capable_kit}" -eq 1 ]; then
    ARGS+=(--require-skill-support)
fi
if [ -n "${SMOKE}" ]; then
    ARGS+=(--smoke "${SMOKE}")
fi
docker run "${ARGS[@]}"
