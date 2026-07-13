#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$(cd "${ROOT_DIR}/.." && pwd)"
IMAGE_ARCHIVE="${ROOT_DIR}/images/codify-offline-images.tar.gz"
OUTPUT_ARCHIVE="${DEPLOY_DIR}/codify-offline-bundle.tar.gz"
TMP_ARCHIVE="${DEPLOY_DIR}/.codify-offline-bundle.tar.gz.tmp"

if [[ ! -f "${IMAGE_ARCHIVE}" ]]; then
  echo "Image archive not found: ${IMAGE_ARCHIVE}. Run ./scripts/export-images.sh first." >&2
  exit 1
fi
if ! compgen -G "${ROOT_DIR}/kits/codify-worker-kit-*.tar.gz" >/dev/null; then
    echo "Worker kit archive not found. Run deploy/worker-kit/export.sh first." >&2
    exit 1
fi
for kit_archive in "${ROOT_DIR}"/kits/codify-worker-kit-*.tar.gz; do
    if [[ ! -f "${kit_archive}.sha256" ]]; then
        echo "Worker kit checksum not found: ${kit_archive}.sha256" >&2
        exit 1
    fi
done

rm -f "${TMP_ARCHIVE}"

echo "Packaging offline bundle to ${OUTPUT_ARCHIVE}..."
tar -C "${DEPLOY_DIR}" -czf "${TMP_ARCHIVE}" offline-bundle
mv "${TMP_ARCHIVE}" "${OUTPUT_ARCHIVE}"

echo "Done."
