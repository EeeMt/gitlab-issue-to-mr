#!/usr/bin/env bash
# Validate the non-secret, immutable Worker-image CLI identity lock through a
# real bind mount on the Docker daemon selected by Docker Compose.  A remote
# daemon resolves bind sources on *its* filesystem, not the control host's.
set -euo pipefail

lock_path="${CODIFY_WORKER_CLI_ARTIFACT_MANIFEST_HOST_PATH:-}"
if [[ -z "${lock_path}" ]]; then
    echo "CODIFY_WORKER_CLI_ARTIFACT_MANIFEST_HOST_PATH must name a Docker-daemon-visible regular file" >&2
    exit 2
fi

runtime_image="${CODIFY_V2_RELEASE_WORKER_IMAGE:-}"
if [[ -z "${runtime_image}" ]]; then
    echo "CODIFY_V2_RELEASE_WORKER_IMAGE must name the reviewed Worker image on the selected Docker daemon" >&2
    exit 2
fi

runtime_platform="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "${runtime_image}")"
if [[ ! "${runtime_platform}" =~ ^linux/[A-Za-z0-9_-]+$ ]]; then
    echo "selected Worker image has an unsupported platform: ${runtime_platform}" >&2
    exit 2
fi

# The daemon-visible bind must contain the exact immutable document embedded in
# the selected Worker image.  Platform equality alone would permit a reviewed
# amd64 lock from a different Worker release to be mounted accidentally.
image_lock_sha256="$(
    docker run --rm --entrypoint sha256sum "${runtime_image}" \
        /etc/codify-worker-cli-artifacts.json | awk 'NR == 1 { print $1 }'
)"
if [[ ! "${image_lock_sha256}" =~ ^[0-9a-f]{64}$ ]]; then
    echo "selected Worker image has no readable CLI artifact lock checksum" >&2
    exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compose=(
    docker compose
    -f "${repo_root}/deploy/docker-compose.yml"
    -f "${repo_root}/deploy/docker-compose.v2-release.yml"
)

# `compose config` checks interpolation only.  These one-shots never start the
# application, but each makes its exact readonly bind on the selected daemon
# and validates the mounted bytes inside the respective service image.
for service in backend scheduler; do
    if ! "${compose[@]}" run --rm --no-deps --entrypoint python3 "${service}" \
        /usr/local/lib/codify/validate-worker-cli-artifact-lock.py \
        --require-readonly \
        --expected-platform "${runtime_platform}" \
        --expected-sha256 "${image_lock_sha256}" \
        /run/codify/worker-cli-artifacts.json; then
        echo "V2 release lock is not readable and valid through the selected Docker daemon (${service})" >&2
        exit 2
    fi
done
