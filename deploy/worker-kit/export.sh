#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${WORKER_KIT_VERSION:-0.3.2}"
PLATFORM="${WORKER_KIT_PLATFORM:-linux/amd64}"
ARCH="${PLATFORM#linux/}"
OUTPUT_DIR="${WORKER_KIT_OUTPUT_DIR:-${PROJECT_ROOT}/deploy/offline-bundle/kits}"
ARCHIVE="${OUTPUT_DIR}/codify-worker-kit-${VERSION}-linux-${ARCH}.tar.gz"
STAGING=""
cid=""

cleanup() {
    if [[ -n "${cid}" ]]; then
        docker rm "${cid}" >/dev/null 2>&1 || true
    fi
    if [[ -n "${STAGING}" ]]; then
        chmod -R u+w "${STAGING}" 2>/dev/null || true
        rm -rf "${STAGING}"
    fi
}
trap cleanup EXIT

mkdir -p "${OUTPUT_DIR}"
STAGING="$(mktemp -d "${OUTPUT_DIR}/.build-staging.XXXXXX")"

IMAGE_TAG="codify-worker-kit-export:${VERSION}-${ARCH}"
docker build \
    --platform "${PLATFORM}" \
    --build-arg WORKER_KIT_VERSION="${VERSION}" \
    -f "${PROJECT_ROOT}/deploy/Dockerfile.worker-kit" \
    -t "${IMAGE_TAG}" \
    "${PROJECT_ROOT}"

cid="$(docker create --platform "${PLATFORM}" "${IMAGE_TAG}" true)"
mkdir -p "${STAGING}/build/worker-kit"
# Stream through tar so read-only Nix store directory modes are applied after children exist.
docker cp "${cid}:/worker-kit/." - | tar -C "${STAGING}/build/worker-kit/" -xf -
docker rm "${cid}"
cid=""

mkdir -p "${STAGING}/${VERSION}-linux-${ARCH}"
cp -a "${STAGING}/build/worker-kit/." "${STAGING}/${VERSION}-linux-${ARCH}/"
# Do not encode macOS extended attributes as AppleDouble files in Linux kits.
COPYFILE_DISABLE=1 tar -C "${STAGING}" -czf "${ARCHIVE}" "${VERSION}-linux-${ARCH}"

if command -v sha256sum >/dev/null 2>&1; then
    (cd "${OUTPUT_DIR}" && sha256sum "$(basename "${ARCHIVE}")") > "${ARCHIVE}.sha256"
else
    (cd "${OUTPUT_DIR}" && shasum -a 256 "$(basename "${ARCHIVE}")") > "${ARCHIVE}.sha256"
fi
echo "Worker kit exported: ${ARCHIVE}"
