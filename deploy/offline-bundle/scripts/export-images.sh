#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCHIVE="${ROOT_DIR}/images/gimr-offline-images.tar.gz"

IMAGES=(
  "deploy-backend:latest"
  "deploy-nginx:latest"
  "gitlab-issues-to-mr-worker:latest"
  "postgres:16-alpine"
)

echo "Exporting images to ${ARCHIVE}..."
docker save "${IMAGES[@]}" | gzip -1 > "${ARCHIVE}"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "${ARCHIVE}" > "${ROOT_DIR}/images/SHA256SUMS"
else
  shasum -a 256 "${ARCHIVE}" > "${ROOT_DIR}/images/SHA256SUMS"
fi
echo "Done."
