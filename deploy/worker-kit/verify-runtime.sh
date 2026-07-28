#!/usr/bin/env bash
set -euo pipefail

KIT_PATH=""
IMAGE=""
SMOKE=""
CLAUDE_HOST_PATH=""
CLAUDE_CONTAINER_PATH="/usr/local/bin/claude"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --kit) KIT_PATH="${2:?missing --kit value}"; shift 2 ;;
        --image) IMAGE="${2:?missing --image value}"; shift 2 ;;
        --claude-host-path) CLAUDE_HOST_PATH="${2:?missing --claude-host-path value}"; shift 2 ;;
        --claude-container-path) CLAUDE_CONTAINER_PATH="${2:?missing --claude-container-path value}"; shift 2 ;;
        --smoke) SMOKE="${2:?missing --smoke value}"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

[ -n "${KIT_PATH}" ] || { echo "--kit is required" >&2; exit 2; }
[ -n "${IMAGE}" ] || { echo "--image is required" >&2; exit 2; }
[ -x "${KIT_PATH}/launcher" ] || { echo "Invalid worker kit: ${KIT_PATH}" >&2; exit 1; }
[ -d "${KIT_PATH}/nix/store" ] || { echo "Worker kit Nix store is missing" >&2; exit 1; }
if [ -n "${CLAUDE_HOST_PATH}" ]; then
    [ -x "${CLAUDE_HOST_PATH}" ] || { echo "Claude executable is not executable: ${CLAUDE_HOST_PATH}" >&2; exit 1; }
    case "${CLAUDE_CONTAINER_PATH}" in
        /*) ;;
        *) echo "--claude-container-path must be absolute" >&2; exit 2 ;;
    esac
fi
docker image inspect "${IMAGE}" >/dev/null

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
if [ -n "${CLAUDE_HOST_PATH}" ]; then
    ARGS+=(--volume "${CLAUDE_HOST_PATH}:${CLAUDE_CONTAINER_PATH}:ro")
fi
ARGS+=(
    --entrypoint /opt/codify-kit/launcher
    --env "CODIFY_KIT_VERSION=${VERSION}"
    --env "CODIFY_RUNTIME_IMAGE=${IMAGE}"
)
if [ -n "${CLAUDE_HOST_PATH}" ]; then
    ARGS+=(--env "CODIFY_CLAUDE_BIN=${CLAUDE_CONTAINER_PATH}")
fi
ARGS+=("${IMAGE}" --verify)
if [ "${skill_capable_kit}" -eq 1 ]; then
    ARGS+=(--require-skill-support)
fi
if [ -n "${SMOKE}" ]; then
    ARGS+=(--smoke "${SMOKE}")
fi
docker run "${ARGS[@]}"
