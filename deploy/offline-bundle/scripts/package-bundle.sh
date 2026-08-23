#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$(cd "${ROOT_DIR}/.." && pwd)"
IMAGE_ARCHIVE="${ROOT_DIR}/images/codify-offline-images.tar.gz"
OUTPUT_ARCHIVE="${DEPLOY_DIR}/codify-offline-bundle.tar.gz"
TMP_ARCHIVE="${DEPLOY_DIR}/.codify-offline-bundle.tar.gz.tmp"
STAGING_DIR=""

cleanup() {
    if [[ -n "${STAGING_DIR}" ]]; then
        rm -rf "${STAGING_DIR}"
    fi
}
trap cleanup EXIT

if [[ ! -f "${IMAGE_ARCHIVE}" ]]; then
  echo "Image archive not found: ${IMAGE_ARCHIVE}. Run ./scripts/export-images.sh first." >&2
  exit 1
fi
if [[ ! -x "${DEPLOY_DIR}/worker-kit/verify-runtime.sh" || ! -f "${DEPLOY_DIR}/worker-kit/validate-runtime-manifest.py" ]]; then
  echo "Worker Kit portable verifier/validator is missing; refusing to package" >&2
  exit 1
fi
KIT_CHECK_DIR="$(mktemp -d "${DEPLOY_DIR}/.worker-kit-package-check.XXXXXX")"
trap 'rm -rf "${KIT_CHECK_DIR}"; cleanup' EXIT
if ! compgen -G "${ROOT_DIR}/kits/codify-worker-kit-*.tar.gz" >/dev/null; then
    echo "Worker kit archive not found. Run deploy/worker-kit/export.sh first." >&2
    exit 1
fi
for kit_archive in "${ROOT_DIR}"/kits/codify-worker-kit-*.tar.gz; do
    if [[ ! -f "${kit_archive}.sha256" ]]; then
        echo "Worker kit checksum not found: ${kit_archive}.sha256" >&2
        exit 1
    fi
    if command -v sha256sum >/dev/null 2>&1; then
        (cd "$(dirname "${kit_archive}")" && sha256sum -c "$(basename "${kit_archive}").sha256")
    else
        (cd "$(dirname "${kit_archive}")" && shasum -a 256 -c "$(basename "${kit_archive}").sha256")
    fi
    kit_name="$(basename "${kit_archive}" .tar.gz)"
    kit_extract="${KIT_CHECK_DIR}/${kit_name}"
    mkdir -p "${kit_extract}"
    python3 "${ROOT_DIR}/scripts/validate-kit-archive.py" "${kit_archive}" "${kit_name#codify-worker-kit-}"
    tar -C "${kit_extract}" -xzf "${kit_archive}"
    kit_root="${kit_extract}/${kit_name#codify-worker-kit-}"
    [[ -x "${kit_root}/launcher" && -s "${kit_root}/manifest.json" && -d "${kit_root}/nix/store" ]] || {
        echo "Worker Kit archive has an invalid launcher/manifest/store contract: ${kit_archive}" >&2
        exit 1
    }
    [[ -x "${kit_root}/verify-runtime.sh" ]] || {
        echo "Worker Kit archive is missing executable verify-runtime.sh: ${kit_archive}" >&2
        exit 1
    }
    [[ -f "${kit_root}/validate-runtime-manifest.py" ]] || {
        echo "Worker Kit archive is missing validate-runtime-manifest.py: ${kit_archive}" >&2
        exit 1
    }
done

rm -f "${TMP_ARCHIVE}"

STAGING_DIR="$(mktemp -d "${DEPLOY_DIR}/.codify-offline-bundle-staging.XXXXXX")"
cp -R "${ROOT_DIR}" "${STAGING_DIR}/offline-bundle"

echo "Packaging offline bundle to ${OUTPUT_ARCHIVE}..."
tar -C "${STAGING_DIR}" -czf "${TMP_ARCHIVE}" offline-bundle
mv "${TMP_ARCHIVE}" "${OUTPUT_ARCHIVE}"
if command -v sha256sum >/dev/null 2>&1; then
    (cd "$(dirname "${OUTPUT_ARCHIVE}")" && sha256sum "$(basename "${OUTPUT_ARCHIVE}")") > "${OUTPUT_ARCHIVE}.sha256"
else
    (cd "$(dirname "${OUTPUT_ARCHIVE}")" && shasum -a 256 "$(basename "${OUTPUT_ARCHIVE}")") > "${OUTPUT_ARCHIVE}.sha256"
fi

echo "Done. Before extracting or executing the bundle, verify it with one platform command:"
echo "  Linux:  sha256sum -c ${OUTPUT_ARCHIVE}.sha256"
echo "  macOS:  shasum -a 256 -c ${OUTPUT_ARCHIVE}.sha256"
