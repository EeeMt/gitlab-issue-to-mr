#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_ARCHIVE="${ROOT_DIR}/images/gimr-offline-images.tar.gz"

if [[ ! -f "${IMAGE_ARCHIVE}" ]]; then
  echo "Image archive not found: ${IMAGE_ARCHIVE}" >&2
  exit 1
fi

echo "Loading Docker images from ${IMAGE_ARCHIVE}..."
gunzip -c "${IMAGE_ARCHIVE}" | docker load
echo "Done."
