#!/usr/bin/env bash
set -euo pipefail

ARCHIVE="${1:?usage: install.sh KIT_ARCHIVE [INSTALL_ROOT]}"
INSTALL_ROOT="${2:-/opt/codify/worker-kits}"
CHECKSUM_FILE="${ARCHIVE}.sha256"

if [ ! -f "${ARCHIVE}" ]; then
    echo "Worker kit archive not found: ${ARCHIVE}" >&2
    exit 1
fi
if [ ! -f "${CHECKSUM_FILE}" ]; then
    echo "Worker kit checksum not found: ${CHECKSUM_FILE}" >&2
    exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
    echo "Worker kit installation must run as root (root-owned immutable kit directory)" >&2
    exit 2
fi

check_install_root() {
    python3 - "${INSTALL_ROOT}" <<'PY'
import os
import stat
import sys

path = os.path.abspath(sys.argv[1])
while True:
    if os.path.lexists(path):
        info = os.lstat(path)
        if not stat.S_ISDIR(info.st_mode):
            raise SystemExit(f"Worker Kit install path is not a directory: {path}")
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise SystemExit(
                "Worker Kit install path and its existing parents must be root-owned "
                f"and not writable by group/others: {path}"
            )
    parent = os.path.dirname(path)
    if parent == path:
        break
    path = parent
PY
}

if command -v sha256sum >/dev/null 2>&1; then
    (cd "$(dirname "${ARCHIVE}")" && sha256sum -c "$(basename "${CHECKSUM_FILE}")")
else
    (cd "$(dirname "${ARCHIVE}")" && shasum -a 256 -c "$(basename "${CHECKSUM_FILE}")")
fi

check_install_root || {
    echo "Worker Kit install root is not a root-owned, non-writable directory" >&2
    exit 2
}
umask 022
mkdir -p "${INSTALL_ROOT}"
check_install_root || {
    echo "Worker Kit install root became unsafe while preparing the install" >&2
    exit 2
}
chown 0:0 "${INSTALL_ROOT}"
chmod 0755 "${INSTALL_ROOT}"
KIT_NAME="$(basename "${ARCHIVE}" .tar.gz)"
KIT_NAME="${KIT_NAME#codify-worker-kit-}"
KIT_DIR="${INSTALL_ROOT}/${KIT_NAME}"

# Content-addressed install: the archive name embeds the manifest SHA-256
# prefix. The manifest commits the complete content inventory, so any
# launcher/entrypoint/closure byte change produces a different identity.
# Refusing an existing directory guarantees two different Kit builds never
# share an install location and a build can never be overwritten.
if [ -e "${KIT_DIR}" ] || [ -L "${KIT_DIR}" ]; then
    echo "Worker kit identity is already installed: ${KIT_DIR}" >&2
    exit 1
fi
if [[ ! "${KIT_NAME}" =~ ^.+-(linux-[A-Za-z0-9_.-]+)-([0-9a-f]{12})$ ]]; then
    echo "Worker kit archive name is not content-addressed: ${KIT_NAME}" >&2
    exit 2
fi
ARCHIVE_PLATFORM="linux/${BASH_REMATCH[1]#linux-}"
EXPECTED_PREFIX="${BASH_REMATCH[2]}"

# Serialize publishers for one identity with a kernel lock. The lock file is
# intentionally retained: flock releases it on process death, so a crashed
# installer cannot strand a stale directory lock.
INSTALL_LOCK="${INSTALL_ROOT}/.worker-kit-install-${KIT_NAME}.lock"
STAGING=""
cleanup() {
    if [ -n "${STAGING}" ]; then
        rm -rf "${STAGING}"
    fi
}
trap cleanup EXIT
CONTENT_VERIFIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/verify-kit-content.py"
if [ ! -f "${CONTENT_VERIFIER}" ]; then
    echo "Trusted Worker Kit content verifier is missing: ${CONTENT_VERIFIER}" >&2
    exit 2
fi
if ! python3 "${CONTENT_VERIFIER}" --archive "${ARCHIVE}" --root-name "${KIT_NAME}" >/dev/null; then
    echo "Worker Kit archive content inventory does not match its bytes" >&2
    exit 2
fi

STAGING="$(mktemp -d "${INSTALL_ROOT}/.worker-kit-install.XXXXXX")"
ARCHIVE_VALIDATOR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../offline-bundle/scripts" && pwd)/validate-kit-archive.py"
if python3 "${ARCHIVE_VALIDATOR}" "${ARCHIVE}" "${KIT_NAME}" >/dev/null; then
    tar -C "${STAGING}" -xzf "${ARCHIVE}"
else
    echo "Worker kit archive contains an unsafe path or link" >&2
    exit 1
fi
STAGED_KIT="${STAGING}/${KIT_NAME}"
test -x "${STAGED_KIT}/launcher"
test -s "${STAGED_KIT}/manifest.json"
test -d "${STAGED_KIT}/nix/store"
test -f "${STAGED_KIT}/verify-kit-content.py"
if ! python3 "${CONTENT_VERIFIER}" --root "${STAGED_KIT}" >/dev/null; then
    echo "Worker Kit content inventory does not match the extracted Kit bytes" >&2
    exit 2
fi

MANIFEST_SHA256="$(sha256sum "${STAGED_KIT}/manifest.json" | awk '{print $1}')"
if [ "${MANIFEST_SHA256:0:${#EXPECTED_PREFIX}}" != "${EXPECTED_PREFIX}" ]; then
    echo "Worker kit manifest digest does not match the archive name: ${KIT_NAME}" >&2
    exit 2
fi

PLATFORM="$(jq -r '.platform' "${STAGED_KIT}/manifest.json")"
if [[ ! "${PLATFORM}" =~ ^linux/[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
    echo "Worker kit manifest has an invalid platform: ${PLATFORM}" >&2
    exit 2
fi
if [ "${PLATFORM}" != "${ARCHIVE_PLATFORM}" ]; then
    echo "Worker kit platform mismatch: manifest ${PLATFORM}, archive ${KIT_NAME}" >&2
    exit 2
fi

# Integrity of the harness inventory: every present entry must exist inside
# the kit, be executable, and match its recorded size/SHA-256; an absent key
# must not ship a payload directory at all (fail closed).
HARNESS_ROOT="${STAGED_KIT}/harness"
if ! jq -e '.harness_inventory | keys | length == 4' "${STAGED_KIT}/manifest.json" >/dev/null; then
    echo "Worker kit manifest has no complete harness_inventory" >&2
    exit 2
fi
for key in pi opencode claude codex; do
    availability="$(jq -r --arg k "${key}" '.harness_inventory[$k].availability' "${STAGED_KIT}/manifest.json")"
    case "${availability}" in
        present)
            rel="$(jq -r --arg k "${key}" '.harness_inventory[$k].path | sub("^/opt/codify-kit/"; "")' "${STAGED_KIT}/manifest.json")"
            payload="${STAGED_KIT}/${rel}"
            if [ ! -f "${payload}" ]; then
                echo "Worker kit inventory marks ${key} present but its file is missing: ${rel}" >&2
                exit 2
            fi
            if [ ! -x "${payload}" ]; then
                echo "Worker kit inventory file for ${key} is not executable: ${rel}" >&2
                exit 2
            fi
            declared_size="$(jq -r --arg k "${key}" '.harness_inventory[$k].size' "${STAGED_KIT}/manifest.json")"
            actual_size="$(wc -c < "${payload}" | tr -d ' ')"
            if [ "${actual_size}" != "${declared_size}" ]; then
                echo "Worker kit size mismatch for ${key}: expected ${declared_size}, found ${actual_size}" >&2
                exit 2
            fi
            declared_sha="$(jq -r --arg k "${key}" '.harness_inventory[$k].sha256' "${STAGED_KIT}/manifest.json")"
            actual_sha="$(sha256sum "${payload}" | awk '{print $1}')"
            if [ "${actual_sha}" != "${declared_sha}" ]; then
                echo "Worker kit integrity check failed for ${key}: recorded SHA-256 does not match ${rel}" >&2
                exit 2
            fi
            ;;
        absent)
            reason="$(jq -r --arg k "${key}" '.harness_inventory[$k].reason_code' "${STAGED_KIT}/manifest.json")"
            case "${reason}" in
                not_selected|missing_payload) ;;
                *)
                    echo "Worker kit absent entry ${key} has an invalid reason_code: ${reason}" >&2
                    exit 2
                    ;;
            esac
            if [ -e "${HARNESS_ROOT}/${key}" ]; then
                echo "Worker kit marks ${key} absent but ships a payload directory: harness/${key}" >&2
                exit 2
            fi
            ;;
        *)
            echo "Worker kit inventory entry ${key} has invalid availability: ${availability}" >&2
            exit 2
            ;;
    esac
done

# Root-owned, non-writable-by-others install. Directory modes are applied
# after children so read-only nix/store entries keep working.
chown -R 0:0 "${STAGED_KIT}"
chmod -R u=rwX,go=rX "${STAGED_KIT}"

# Install receipt: the immutable record of archive/manifest/content digest
# and platform required by the release evidence contract.
ARCHIVE_SHA256="$(awk '{print $1}' "${CHECKSUM_FILE}")"
KIT_VERSION="$(jq -r '.kit_version' "${STAGED_KIT}/manifest.json")"
INSTALLED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
jq -n \
    --arg schema "codify.worker.kit-install-receipt/v1" \
    --arg archive "$(basename "${ARCHIVE}")" \
    --arg archive_sha256 "${ARCHIVE_SHA256}" \
    --arg manifest_sha256 "${MANIFEST_SHA256}" \
    --arg content_inventory_sha256 "$(jq -r '.content_inventory_sha256' "${STAGED_KIT}/manifest.json")" \
    --arg kit_version "${KIT_VERSION}" \
    --arg platform "${PLATFORM}" \
    --arg installed_at "${INSTALLED_AT}" \
    '{schema: $schema, archive: $archive, archive_sha256: $archive_sha256, manifest_sha256: $manifest_sha256, content_inventory_sha256: $content_inventory_sha256, kit_version: $kit_version, platform: $platform, installed_at: $installed_at}' \
    > "${STAGED_KIT}/.install-receipt.json"
chown 0:0 "${STAGED_KIT}/.install-receipt.json"
chmod 0644 "${STAGED_KIT}/.install-receipt.json"

if ! python3 - "${STAGED_KIT}" "${KIT_DIR}" "${INSTALL_LOCK}" <<'PY'
import fcntl
import os
import sys

source, destination, lock_path = sys.argv[1:]
flags = os.O_RDWR | os.O_CREAT
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
lock_fd = os.open(lock_path, flags, 0o600)
with os.fdopen(lock_fd, "r+") as lock_file:
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    if os.path.lexists(destination):
        raise SystemExit(3)
    os.rename(source, destination)
PY
then
    echo "Worker kit identity appeared before atomic publish: ${KIT_DIR}" >&2
    exit 1
fi
echo "Worker kit installed: ${KIT_DIR}"
echo "Kit identity manifest_sha256: ${MANIFEST_SHA256}"
