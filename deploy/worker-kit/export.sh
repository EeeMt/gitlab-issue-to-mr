#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${WORKER_KIT_VERSION:-0.1.0}"
PLATFORM="${WORKER_KIT_PLATFORM:-linux/amd64}"
ARCH="${PLATFORM#linux/}"
OUTPUT_DIR="${WORKER_KIT_OUTPUT_DIR:-${PROJECT_ROOT}/deploy/offline-bundle/kits}"
ARCHIVE="${OUTPUT_DIR}/codify-worker-kit-${VERSION}-linux-${ARCH}.tar.gz"
STAGING="$(mktemp -d)"

cleanup() {
    rm -rf "${STAGING}"
}
trap cleanup EXIT

mkdir -p "${OUTPUT_DIR}"
docker build \
    --platform "${PLATFORM}" \
    --build-arg WORKER_KIT_VERSION="${VERSION}" \
    -f "${PROJECT_ROOT}/deploy/Dockerfile.worker-kit" \
    --output "type=local,dest=${STAGING}/build" \
    "${PROJECT_ROOT}"

mkdir -p "${STAGING}/${VERSION}-linux-${ARCH}"
cp -a "${STAGING}/build/worker-kit/." "${STAGING}/${VERSION}-linux-${ARCH}/"
tar -C "${STAGING}" -czf "${ARCHIVE}" "${VERSION}-linux-${ARCH}"

if command -v sha256sum >/dev/null 2>&1; then
    (cd "${OUTPUT_DIR}" && sha256sum "$(basename "${ARCHIVE}")") > "${ARCHIVE}.sha256"
else
    (cd "${OUTPUT_DIR}" && shasum -a 256 "$(basename "${ARCHIVE}")") > "${ARCHIVE}.sha256"
fi
echo "Worker kit exported: ${ARCHIVE}"
