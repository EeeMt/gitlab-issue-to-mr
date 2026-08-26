#!/usr/bin/env bash
set -euo pipefail

ARCHIVE="${1:?usage: install-worker-kit.sh KIT_ARCHIVE [INSTALL_ROOT]}"
INSTALL_ROOT="${2:-/opt/codify/worker-kits}"
CHECKSUM_FILE="${ARCHIVE}.sha256"

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

[ -f "${ARCHIVE}" ] || { echo "Worker kit archive not found: ${ARCHIVE}" >&2; exit 1; }
[ -f "${CHECKSUM_FILE}" ] || { echo "Checksum not found: ${CHECKSUM_FILE}" >&2; exit 1; }
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
if [ -e "${KIT_DIR}" ] || [ -L "${KIT_DIR}" ]; then
    echo "Worker kit identity is already installed: ${KIT_DIR}" >&2
    exit 1
fi
if [[ ! "${KIT_NAME}" =~ ^.+-(linux-[A-Za-z0-9_.-]+)-([0-9a-f]{12})$ ]]; then
    echo "Worker kit archive name is not content-addressed: ${KIT_NAME}" >&2
    exit 2
fi
ARCHIVE_PLATFORM="linux/${BASH_REMATCH[1]#linux-}"
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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTENT_VERIFIER="${SCRIPT_DIR}/verify-kit-content.py"
if [ ! -f "${CONTENT_VERIFIER}" ]; then
    CONTENT_VERIFIER="${SCRIPT_DIR}/../../worker-kit/verify-kit-content.py"
fi
if [ ! -f "${CONTENT_VERIFIER}" ]; then
    echo "Trusted Worker Kit content verifier is missing" >&2
    exit 2
fi
if ! python3 "${CONTENT_VERIFIER}" --archive "${ARCHIVE}" --root-name "${KIT_NAME}" >/dev/null; then
    echo "Worker Kit archive content inventory does not match its bytes" >&2
    exit 2
fi
STAGING="$(mktemp -d "${INSTALL_ROOT}/.worker-kit-install.XXXXXX")"
if python3 "$(dirname "${BASH_SOURCE[0]}")/validate-kit-archive.py" "${ARCHIVE}" "${KIT_NAME}"; then
    tar -C "${STAGING}" -xzf "${ARCHIVE}"
else
    echo "Worker kit archive contains an unexpected path" >&2
    exit 1
fi
STAGED_KIT="${STAGING}/${KIT_NAME}"
test -x "${STAGED_KIT}/launcher"
test -s "${STAGED_KIT}/manifest.json"
test -d "${STAGED_KIT}/nix/store"
test -f "${STAGED_KIT}/verify-kit-content.py"
python3 "${CONTENT_VERIFIER}" --root "${STAGED_KIT}" >/dev/null || {
    echo "Worker Kit content inventory does not match the extracted Kit bytes" >&2
    exit 2
}
if command -v sha256sum >/dev/null 2>&1; then
    MANIFEST_SHA256="$(sha256sum "${STAGED_KIT}/manifest.json" | awk '{print $1}')"
else
    MANIFEST_SHA256="$(shasum -a 256 "${STAGED_KIT}/manifest.json" | awk '{print $1}')"
fi
EXPECTED_PREFIX="${KIT_NAME##*-}"
if [ "${MANIFEST_SHA256:0:12}" != "${EXPECTED_PREFIX}" ]; then
    echo "Worker kit manifest digest does not match the archive name: ${KIT_NAME}" >&2
    exit 2
fi
MANIFEST_PLATFORM="$(python3 - "${STAGED_KIT}/manifest.json" <<'PY'
import json
import sys

manifest = json.loads(open(sys.argv[1], encoding="utf-8").read())
platform = manifest.get("platform")
if not isinstance(platform, str) or not platform.startswith("linux/"):
    raise SystemExit(1)
print(platform)
PY
)" || {
    echo "Worker kit manifest has an invalid platform" >&2
    exit 2
}
if [ "${MANIFEST_PLATFORM}" != "${ARCHIVE_PLATFORM}" ]; then
    echo "Worker kit platform mismatch: manifest ${MANIFEST_PLATFORM}, archive ${ARCHIVE_PLATFORM}" >&2
    exit 2
fi
chown -R 0:0 "${STAGED_KIT}"
chmod -R u=rwX,go=rX "${STAGED_KIT}"
ARCHIVE_SHA256="$(awk '{print $1}' "${CHECKSUM_FILE}")"
python3 - "${STAGED_KIT}/manifest.json" "${STAGED_KIT}/.install-receipt.json" \
    "$(basename "${ARCHIVE}")" "${ARCHIVE_SHA256}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" <<'PY'
import hashlib
import json
import pathlib
import sys

manifest_path = pathlib.Path(sys.argv[1])
receipt_path = pathlib.Path(sys.argv[2])
manifest = json.loads(manifest_path.read_bytes())
receipt = {
    "schema": "codify.worker.kit-install-receipt/v1",
    "archive": sys.argv[3],
    "archive_sha256": sys.argv[4],
    "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    "content_inventory_sha256": manifest["content_inventory_sha256"],
    "kit_version": manifest["kit_version"],
    "platform": manifest["platform"],
    "installed_at": sys.argv[5],
}
receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
PY
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
