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

if command -v sha256sum >/dev/null 2>&1; then
    (cd "$(dirname "${ARCHIVE}")" && sha256sum -c "$(basename "${CHECKSUM_FILE}")")
else
    (cd "$(dirname "${ARCHIVE}")" && shasum -a 256 -c "$(basename "${CHECKSUM_FILE}")")
fi

mkdir -p "${INSTALL_ROOT}"
KIT_NAME="$(basename "${ARCHIVE}" .tar.gz)"
KIT_NAME="${KIT_NAME#codify-worker-kit-}"
KIT_DIR="${INSTALL_ROOT}/${KIT_NAME}"

# Content-addressed install: the archive name embeds the manifest SHA-256
# prefix. Refusing an existing directory guarantees two different Kit builds
# never share an install location and a build can never be overwritten.
if [ -e "${KIT_DIR}" ]; then
    echo "Worker kit identity is already installed: ${KIT_DIR}" >&2
    exit 1
fi
case "${KIT_NAME}" in
    *-linux-*-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f])
        ;;
    *)
        echo "Worker kit archive name is not content-addressed: ${KIT_NAME}" >&2
        exit 2
        ;;
esac

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

MANIFEST_SHA256="$(sha256sum "${STAGED_KIT}/manifest.json" | awk '{print $1}')"
EXPECTED_PREFIX="${KIT_NAME##*-}"
if [ "${MANIFEST_SHA256:0:${#EXPECTED_PREFIX}}" != "${EXPECTED_PREFIX}" ]; then
    echo "Worker kit manifest digest does not match the archive name: ${KIT_NAME}" >&2
    exit 2
fi

PLATFORM="$(jq -r '.platform' "${STAGED_KIT}/manifest.json")"
case "${PLATFORM}" in
    linux/*) ;;
    *)
        echo "Worker kit manifest has an invalid platform: ${PLATFORM}" >&2
        exit 2
        ;;
esac
case "${KIT_NAME}" in
    *-linux-${PLATFORM#linux/}-[0-9a-f]*)
        ;;
    *)
        echo "Worker kit platform mismatch: manifest ${PLATFORM}, archive ${KIT_NAME}" >&2
        exit 2
        ;;
esac

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
    --arg kit_version "${KIT_VERSION}" \
    --arg platform "${PLATFORM}" \
    --arg installed_at "${INSTALLED_AT}" \
    '{schema: $schema, archive: $archive, archive_sha256: $archive_sha256, manifest_sha256: $manifest_sha256, kit_version: $kit_version, platform: $platform, installed_at: $installed_at}' \
    > "${STAGED_KIT}/.install-receipt.json"
chown 0:0 "${STAGED_KIT}/.install-receipt.json"
chmod 0644 "${STAGED_KIT}/.install-receipt.json"

mv "${STAGED_KIT}" "${KIT_DIR}"
echo "Worker kit installed: ${KIT_DIR}"
echo "Kit identity manifest_sha256: ${MANIFEST_SHA256}"
