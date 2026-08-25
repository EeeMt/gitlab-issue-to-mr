#!/usr/bin/env bash
# V2 release preflight for the Kit-owned model. The Project Runtime Image no
# longer carries or locks any Harness CLI: the four Harness CLIs live in the
# content-addressed Worker Kit archive, whose identity is the SHA-256 of its
# manifest bytes (the archive name embeds the 12-character manifest prefix).
#
# This script validates, on the Docker daemon selected by the local Docker
# CLI:
#   1. the Worker Kit archive and its .sha256 sidecar (sha256sum -c),
#   2. the archive's manifest.json (kind, kit_version, platform,
#      harness_inventory with exactly four well-formed entries),
#   3. the content-addressed archive name against the manifest SHA-256,
#   4. the Worker image identity (image ID, OS/architecture) against the
#      manifest platform.
#
# Daemon-visibility note: V2_RELEASE_WORKER_IMAGE must exist on the selected
# Docker daemon. With remote Docker, the Worker Kit archive is read on the
# control host by this script, but it must also be present on the daemon host
# for installation (see install-worker-kit.sh); a path only on the control
# host is not visible to the daemon host.
set -euo pipefail

fail() {
    echo "$1" >&2
    exit 2
}

kit_archive="${WORKER_KIT_ARCHIVE:-}"
if [[ -z "${kit_archive}" ]]; then
    fail "WORKER_KIT_ARCHIVE must name a Docker-daemon-visible Worker Kit archive (codify-worker-kit-<version>-linux-<arch>-<manifest-prefix>.tar.gz)"
fi

runtime_image="${V2_RELEASE_WORKER_IMAGE:-}"
if [[ -z "${runtime_image}" ]]; then
    fail "V2_RELEASE_WORKER_IMAGE must name the reviewed Worker image on the selected Docker daemon"
fi

[[ -f "${kit_archive}" ]] || fail "Worker Kit archive not found: ${kit_archive}"
checksum_file="${kit_archive}.sha256"
[[ -f "${checksum_file}" ]] || fail "Worker Kit archive checksum not found: ${checksum_file}"
if ! (cd "$(dirname "${kit_archive}")" && sha256sum -c "$(basename "${checksum_file}")") >/dev/null 2>&1; then
    fail "Worker Kit archive checksum verification failed: ${checksum_file}"
fi

# The Kit identity is the SHA-256 of the manifest bytes. Extract manifest.json
# from the archive and hash the raw bytes (not the shell-dequoted text) so the
# digest matches the content-addressed name.
manifest_path="$(tar -tzf "${kit_archive}" | awk '/\/manifest\.json$/{print; exit}')"
if [[ -z "${manifest_path}" ]]; then
    fail "Worker Kit archive contains no manifest.json"
fi
manifest="$(tar -xOzf "${kit_archive}" "${manifest_path}")"
manifest_sha256="$(tar -xOzf "${kit_archive}" "${manifest_path}" | sha256sum | awk '{print $1}')"

archive_name="$(basename "${kit_archive}")"
if [[ ! "${archive_name}" =~ ^codify-worker-kit-.+-linux-[A-Za-z0-9_-]+-[0-9a-f]{12}\.tar\.gz$ ]]; then
    fail "Worker Kit archive name is not content-addressed (expected codify-worker-kit-<version>-linux-<arch>-<12-hex>.tar.gz): ${archive_name}"
fi
if [[ "${archive_name}" != *-${manifest_sha256:0:12}.tar.gz ]]; then
    fail "Worker Kit archive name does not embed the manifest SHA-256 prefix (content-addressed identity): ${archive_name}"
fi

# Manifest shape checks.
jq -e '.manifest_kind == "codify.worker.kit-manifest/v1"' <<<"${manifest}" >/dev/null 2>&1 \
    || fail "Worker Kit manifest has an unsupported manifest_kind (expected codify.worker.kit-manifest/v1)"
jq -e '(.kit_version | type == "string" and length > 0)' <<<"${manifest}" >/dev/null 2>&1 \
    || fail "Worker Kit manifest has an empty kit_version"
jq -e '(.platform | type == "string" and test("^linux/[A-Za-z0-9][A-Za-z0-9_.-]*$"))' <<<"${manifest}" >/dev/null 2>&1 \
    || fail "Worker Kit manifest has an invalid platform"
jq -e '(.harness_inventory | type == "object" and (keys | sort) == ["claude", "codex", "opencode", "pi"])' <<<"${manifest}" >/dev/null 2>&1 \
    || fail "Worker Kit manifest harness_inventory must contain exactly the four keys claude/codex/opencode/pi"
jq -e '[.harness_inventory[] |
        ((.availability == "present") and
            ((.path | type == "string" and startswith("/opt/codify-kit/")) and
             (.version | type == "string" and length > 0) and
             (.sha256 | type == "string" and test("^[0-9a-f]{64}$")) and
             (.size | type == "number" and . > 0 and (. == floor)))) or
        ((.availability == "absent") and
            ((.reason_code == "not_selected") or (.reason_code == "missing_payload")))] | all' <<<"${manifest}" >/dev/null 2>&1 \
    || fail "Worker Kit manifest has an invalid harness_inventory entry (present needs path/version/sha256/size; absent needs reason_code not_selected|missing_payload)"

kit_version="$(jq -r '.kit_version' <<<"${manifest}")"
manifest_platform="$(jq -r '.platform' <<<"${manifest}")"

# Worker image identity on the selected daemon: image ID plus OS/architecture,
# and the platform must match the Kit manifest platform.
if ! image_identity="$(docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' "${runtime_image}" 2>/dev/null)"; then
    fail "selected Worker image is not present on the selected Docker daemon: ${runtime_image}"
fi
image_id="$(awk '{print $1}' <<<"${image_identity}")"
image_platform="$(awk '{print $2}' <<<"${image_identity}")"
if [[ ! "${image_id}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    fail "selected Worker image has no valid image ID: ${image_id}"
fi
if [[ ! "${image_platform}" =~ ^linux/[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
    fail "selected Worker image has an unsupported platform: ${image_platform}"
fi
# Normalize an architecture variant suffix (e.g. arm64/v8 -> arm64) so the
# daemon identity (linux/$ARCH[+/v$VARIANT]) compares with the manifest
# platform (linux/$TARGETARCH).
normalized_image_platform="${image_platform%/v[0-9]*}"
if [[ "${normalized_image_platform}" != "${manifest_platform}" ]]; then
    fail "Worker Kit platform (${manifest_platform}) does not match the selected Worker image platform (${image_platform})"
fi

echo "V2 release preflight OK: ${kit_version} ${manifest_platform} ${manifest_sha256}"
