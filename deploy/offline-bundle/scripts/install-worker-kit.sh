#!/usr/bin/env bash
set -euo pipefail

ARCHIVE="${1:?usage: install-worker-kit.sh KIT_ARCHIVE [INSTALL_ROOT]}"
INSTALL_ROOT="${2:-/opt/codify/worker-kits}"
CHECKSUM_FILE="${ARCHIVE}.sha256"

[ -f "${ARCHIVE}" ] || { echo "Worker kit archive not found: ${ARCHIVE}" >&2; exit 1; }
[ -f "${CHECKSUM_FILE}" ] || { echo "Checksum not found: ${CHECKSUM_FILE}" >&2; exit 1; }
if command -v sha256sum >/dev/null 2>&1; then
    (cd "$(dirname "${ARCHIVE}")" && sha256sum -c "$(basename "${CHECKSUM_FILE}")")
else
    (cd "$(dirname "${ARCHIVE}")" && shasum -a 256 -c "$(basename "${CHECKSUM_FILE}")")
fi
mkdir -p "${INSTALL_ROOT}"
KIT_NAME="$(basename "${ARCHIVE}" .tar.gz)"
KIT_NAME="${KIT_NAME#codify-worker-kit-}"
KIT_DIR="${INSTALL_ROOT}/${KIT_NAME}"
if [ -e "${KIT_DIR}" ]; then
    echo "Worker kit version is already installed: ${KIT_DIR}" >&2
    exit 1
fi
STAGING="$(mktemp -d "${INSTALL_ROOT}/.worker-kit-install.XXXXXX")"
cleanup() { rm -rf "${STAGING}"; }
trap cleanup EXIT
if tar -tzf "${ARCHIVE}" | awk -v root="${KIT_NAME}/" '
    index($0, root) != 1 || $0 ~ /(^|\/)\.\.($|\/)/ { invalid = 1 }
    END { exit invalid }
'; then
    tar -C "${STAGING}" -xzf "${ARCHIVE}"
else
    echo "Worker kit archive contains an unexpected path" >&2
    exit 1
fi
STAGED_KIT="${STAGING}/${KIT_NAME}"
test -x "${STAGED_KIT}/launcher"
test -s "${STAGED_KIT}/manifest.json"
test -d "${STAGED_KIT}/nix/store"
mv "${STAGED_KIT}" "${KIT_DIR}"
echo "Worker kit installed: ${KIT_DIR}"
