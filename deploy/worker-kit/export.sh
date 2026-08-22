#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${WORKER_KIT_VERSION:-0.3.14}"
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

# Snapshot the active Docker builder once; both the platform gate and the
# friendly message read from the same output.
builder_info() {
    docker buildx inspect 2>/dev/null || true
}

# Fail fast with a friendly message when the active builder cannot build the
# requested platform. Otherwise BuildKit fails mid-build with a cryptic
# "exec format error" that gives no hint about the real cause.
#
# The gate only applies when the current buildx builder is the docker driver,
# i.e. the same builder plain `docker build` uses. For other drivers (e.g. a
# docker-container builder selected via `docker buildx use`) `docker build`
# ignores the selection and uses the daemon instead, so we cannot predict its
# platforms here and fail open rather than risk a false abort.
check_platform_support() {
    local info driver platforms name supported="" p
    info="$(builder_info)"
    driver="$(awk -F': *' '/^Driver:/{print $2; exit}' <<<"${info}")"
    [[ "${driver}" == "docker" ]] || return 0
    platforms="$(awk '/Platforms:/{sub(/^[[:space:]]*Platforms:[[:space:]]*/,""); print}' <<<"${info}" | tr ',' '\n')"
    [[ -n "${platforms}" ]] || return 0
    while IFS= read -r p; do
        p="${p#"${p%%[![:space:]]*}"}"
        p="${p%"${p##*[![:space:]]}"}"
        # Match in either direction so a platform family and its sub-variants
        # (linux/arm64 vs linux/arm64/v8) satisfy each other.
        if [[ -n "${p}" && ( "${p}" == "${PLATFORM}" || "${p}" == "${PLATFORM}/"* || "${PLATFORM}" == "${p}/"* ) ]]; then
            supported=1
            break
        fi
    done <<< "${platforms}"
    [[ -n "${supported}" ]] && return 0
    name="$(awk -F': *' '/^Name:/{print $2; exit}' <<<"${info}")"
    available="$(sed -e 's/^[[:space:]]*//' -e '/^[[:space:]]*$/d' <<<"${platforms}" | paste -sd, - | sed 's/,/, /g')"
    cat >&2 <<EOF

Codify worker kit export cannot build for platform "${PLATFORM}" on the
active Docker builder.

    Active builder : ${name:-<unknown>}
    Supports       : ${available:-<unknown>}

The offline bundle ships both linux/amd64 and linux/arm64 kits, and each
kit must be built where the Docker builder can run that platform (natively
or via binfmt/QEMU emulation). BuildKit only reports a cryptic
"exec format error" when the platform is unavailable.

To produce the "${PLATFORM}" kit, either run on a machine whose builder
supports the platform (e.g. an Apple Silicon host):

    docker context use <dual-platform-context>
    make offline-bundle-export

or enable cross-arch emulation on the current host (binfmt/QEMU, e.g.
'docker run --privileged --rm tonistiigi/binfmt'), or point Docker at a
remote builder that already supports the platform, then re-run.

Aborting; no kit was produced for "${PLATFORM}".
EOF
    return 1
}

check_platform_support || exit 1

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
