#!/usr/bin/env bash
set -euo pipefail

KIT_PATH=""
IMAGE=""
SMOKE=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --kit) KIT_PATH="${2:?missing --kit value}"; shift 2 ;;
        --image) IMAGE="${2:?missing --image value}"; shift 2 ;;
        --smoke) SMOKE="${2:?missing --smoke value}"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

[ -n "${KIT_PATH}" ] || { echo "--kit is required" >&2; exit 2; }
[ -n "${IMAGE}" ] || { echo "--image is required" >&2; exit 2; }
[ -x "${KIT_PATH}/launcher" ] || { echo "Invalid worker kit: ${KIT_PATH}" >&2; exit 1; }
[ -d "${KIT_PATH}/nix/store" ] || { echo "Worker kit Nix store is missing" >&2; exit 1; }
docker image inspect "${IMAGE}" >/dev/null

VERSION="$(sed -n 's/.*"kit_version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${KIT_PATH}/manifest.json")"
[ -n "${VERSION}" ] || { echo "Could not read kit version" >&2; exit 1; }

ARGS=(
    --rm
    --user 0:0
    --tmpfs /workspace:rw,exec,mode=1777
    --volume "${KIT_PATH}:/opt/codify-kit:ro"
    --volume "${KIT_PATH}/nix/store:/nix/store:ro"
    --entrypoint /opt/codify-kit/launcher
    --env "CODIFY_KIT_VERSION=${VERSION}"
    --env "CODIFY_RUNTIME_IMAGE=${IMAGE}"
    "${IMAGE}"
    --verify
)
if [ -n "${SMOKE}" ]; then
    ARGS+=(--smoke "${SMOKE}")
fi
docker run "${ARGS[@]}"
