#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${WORKER_KIT_VERSION:-0.4.0}"
PLATFORM="${WORKER_KIT_PLATFORM:-linux/amd64}"
ARCH="${PLATFORM#linux/}"
SELECTION="${WORKER_KIT_CLI_SELECTION:-pi,opencode}"
OUTPUT_DIR="${WORKER_KIT_OUTPUT_DIR:-${PROJECT_ROOT}/deploy/offline-bundle/kits}"
STAGING=""
cid=""

# Per-key staged payload layout: <source path under deploy/worker-cli/> ->
# <relative executable path inside the Kit harness/<key>/ directory>.
cli_source_for() {
    case "$1" in
        pi) echo "pi" ;;
        opencode) echo "opencode/opencode" ;;
        claude) echo "claude" ;;
        codex) echo "codex" ;;
        *) return 1 ;;
    esac
}
cli_rel_for() {
    case "$1" in
        pi) echo "bin/pi" ;;
        opencode) echo "opencode" ;;
        claude) echo "claude" ;;
        codex) echo "bin/codex" ;;
    esac
}

cleanup() {
    if [[ -n "${cid}" ]]; then
        docker rm "${cid}" >/dev/null 2>&1 || true
    fi
    if [[ -n "${STAGING}" ]]; then
        chmod -R u+w "${STAGING}" 2>/dev/null || true
        rm -rf "${STAGING}"
    fi
    rm -rf "${PROJECT_ROOT}/deploy/worker-cli/kit-staging"
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

# Validate the selection set and stage only the selected payloads into the
# build context (deploy/worker-cli/kit-staging). Unselected payloads never
# enter the Kit, so manifest absent entries can never conflict with shipped
# files. A selected key whose payload is missing is left absent: the manifest
# records it as missing_payload (degraded Kit) instead of failing the build.
stage_selected_payloads() {
    local keys="" key src rel staged
    # Always create the build-context staging directory: the Dockerfile COPYs
    # it unconditionally, even for an empty selection (0 CLI payloads).
    mkdir -p "${PROJECT_ROOT}/deploy/worker-cli/kit-staging"
    # BuildKit does not ship empty directories in the build context; the
    # placeholder keeps the COPY source present for 0-payload selections.
    : > "${PROJECT_ROOT}/deploy/worker-cli/kit-staging/.keep"
    [[ -n "${SELECTION}" ]] || return 0
    keys="$(printf '%s' "${SELECTION}" | tr ',+' '  ')"
    for key in ${keys}; do
        case "${key}" in
            pi|opencode|claude|codex) ;;
            *)
                echo "WORKER_KIT_CLI_SELECTION contains unknown harness key: ${key}" >&2
                exit 2
                ;;
        esac
        src="$(cli_source_for "${key}")"
        rel="$(cli_rel_for "${key}")"
        staged="${PROJECT_ROOT}/deploy/worker-cli/kit-staging/${key}"
        if [ ! -e "${PROJECT_ROOT}/deploy/worker-cli/${src}" ]; then
            echo "WARNING: harness '${key}' selected but payload deploy/worker-cli/${src} is missing; manifest will record missing_payload" >&2
            continue
        fi
        if [ -d "${PROJECT_ROOT}/deploy/worker-cli/${src}" ]; then
            # Directory payload: copy its contents under the staged rel dir so
            # sidecar files (e.g. package.json for pi's version lookup) ship
            # next to the executable. The rel basename must exist inside.
            rel_dir="$(dirname "${rel}")"
            mkdir -p "${staged}/${rel_dir}"
            cp -a "${PROJECT_ROOT}/deploy/worker-cli/${src}/." "${staged}/${rel_dir}/"
            echo "Staged harness '${key}' payload dir -> worker-cli/kit-staging/${key}/${rel_dir}/"
        else
            mkdir -p "$(dirname "${staged}/${rel}")"
            cp -a "${PROJECT_ROOT}/deploy/worker-cli/${src}" "${staged}/${rel}"
            echo "Staged harness '${key}' payload -> worker-cli/kit-staging/${key}/${rel}"
        fi
    done
}

check_platform_support || exit 1

mkdir -p "${OUTPUT_DIR}"
stage_selected_payloads

# The Docker CLI drops empty-valued build args, so an explicit empty
# selection is passed as the "none" sentinel (interpreted as no payloads by
# the verifier and manifest generator).
SELECTION_ARG="${SELECTION:-none}"
BUILD_ARGS=(
    --build-arg "WORKER_KIT_VERSION=${VERSION}"
    --build-arg "KIT_CLI_SELECTION=${SELECTION_ARG}"
)
for key in pi opencode claude codex; do
    env_name="WORKER_KIT_$(printf '%s' "${key}" | tr '[:lower:]' '[:upper:]')_CLI_VERSION"
    arg_name="$(printf '%s' "${key}" | tr '[:lower:]' '[:upper:]')_CLI_VERSION"
    if [ -n "${!env_name:-}" ]; then
        BUILD_ARGS+=(--build-arg "${arg_name}=${!env_name}")
    fi
done

STAGING="$(mktemp -d "${OUTPUT_DIR}/.build-staging.XXXXXX")"

IMAGE_TAG="codify-worker-kit-export:${VERSION}-${ARCH}"
docker build \
    --platform "${PLATFORM}" \
    "${BUILD_ARGS[@]}" \
    -f "${PROJECT_ROOT}/deploy/Dockerfile.worker-kit" \
    -t "${IMAGE_TAG}" \
    "${PROJECT_ROOT}"

cid="$(docker create --platform "${PLATFORM}" "${IMAGE_TAG}" true)"
# The manifest bytes are the content-addressed Kit identity: the archive name
# embeds their SHA-256 prefix so installers refuse to overwrite an existing
# identity directory and two different builds never share a name.
MANIFEST_DIGEST="$(docker run --rm --entrypoint cat "${IMAGE_TAG}" /worker-kit/manifest.json | sha256sum | awk '{print $1}')"
KIT_NAME="${VERSION}-linux-${ARCH}-${MANIFEST_DIGEST:0:12}"
ARCHIVE="${OUTPUT_DIR}/codify-worker-kit-${KIT_NAME}.tar.gz"
if [ -e "${ARCHIVE}" ]; then
    echo "Worker kit archive already exists (immutable, content-addressed): ${ARCHIVE}" >&2
    exit 2
fi

mkdir -p "${STAGING}/build/worker-kit"
# Stream through tar so read-only Nix store directory modes are applied after children exist.
docker cp "${cid}:/worker-kit/." - | tar -C "${STAGING}/build/worker-kit/" -xf -
docker rm "${cid}"
cid=""

mkdir -p "${STAGING}/${KIT_NAME}"
cp -a "${STAGING}/build/worker-kit/." "${STAGING}/${KIT_NAME}/"
# Do not encode macOS extended attributes as AppleDouble files in Linux kits.
COPYFILE_DISABLE=1 tar -C "${STAGING}" -czf "${ARCHIVE}" "${KIT_NAME}"

if command -v sha256sum >/dev/null 2>&1; then
    (cd "${OUTPUT_DIR}" && sha256sum "$(basename "${ARCHIVE}")") > "${ARCHIVE}.sha256"
else
    (cd "${OUTPUT_DIR}" && shasum -a 256 "$(basename "${ARCHIVE}")") > "${ARCHIVE}.sha256"
fi
echo "Worker kit exported: ${ARCHIVE}"
echo "Kit identity manifest_sha256: ${MANIFEST_DIGEST}"
