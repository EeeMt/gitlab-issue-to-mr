#!/bin/sh
# Verify selected Harness CLI payloads inside the Kit build and record the
# evidence that becomes the manifest harness_inventory.
#
# Runs in the nix closure builder (TARGETPLATFORM, glibc) so dynamically
# linked CLI payloads execute for real. Reads:
#   KIT_CLI_SELECTION   comma/plus-separated subset of pi,opencode,claude,codex
#   PI_CLI_VERSION OPENCODE_CLI_VERSION CLAUDE_CLI_VERSION CODEX_CLI_VERSION
#                       required expected versions; the payload's --version
#                       output must resolve to an exact match
#   GLIBC_LOADER        optional path to the nix closure's ld-linux loader;
#                       used when the payload cannot exec natively (the build
#                       stage is Alpine/musl and glibc binaries need /lib64)
#   /payloads/<key>/... staged payload directories (only selected keys)
#
# Writes /tmp/payload-evidence.json:
#   {"present": {<key>: {"path": <container-rel>, "version": <observed>,
#                        "sha256": ..., "size": ...}},
#    "missing": [<key>, ...]}
#
# Rules:
# - A selected key with no staged payload is recorded as "missing" so the
#   manifest can mark it absent with reason_code=missing_payload (degraded
#   Kit, warning) instead of failing the whole build.
# - A selected key whose payload is not executable, or whose --version does
#   not run, or whose --version contradicts a pinned version, FAILS the build:
#   a shipped-but-broken payload is a defect, not a degraded state.
set -eu
JQ="${JQ_BIN:-jq}"
SEMVER_SHAPE='^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$'
SEMVER_CORE_RE='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'

validate_semver() {
    version="$1"
    printf '%s\n' "${version}" | grep -Eq "${SEMVER_SHAPE}" || return 1

    core="${version}"
    case "${core}" in
        *+*)
            core="${core%%+*}"
            ;;
    esac
    prerelease=""
    case "${core}" in
        *-*)
            prerelease="${core#*-}"
            core="${core%%-*}"
            ;;
    esac
    printf '%s\n' "${core}" | grep -Eq "${SEMVER_CORE_RE}" || return 1

    if [ -n "${prerelease}" ]; then
        old_ifs="${IFS}"
        IFS=.
        set -- ${prerelease}
        IFS="${old_ifs}"
        for identifier in "$@"; do
            case "${identifier}" in
                *[!0-9]*) ;;
                0|[1-9]*) ;;
                *) return 1 ;;
            esac
        done
    fi
}

# Extract and validate the first version-looking token. Keeping the whole
# token before validation makes malformed values such as 1.2.3.4 or 1.2.3-01
# fail closed instead of being truncated to a valid-looking prefix.
extract_semver() {
    candidate=""
    for token in $(printf '%s\n' "$1" | grep -Eo '[0-9][0-9A-Za-z+.-]*' || true); do
        case "${token}" in
            *.*.*)
                candidate="${token}"
                validate_semver "${candidate}" || return 1
                printf '%s\n' "${candidate}"
                return 0
                ;;
        esac
    done
    return 1
}

# Run `--version` on a payload, falling back to the glibc loader when the
# native exec fails (musl build stage without /lib64). The loader's own lib
# dir is put on LD_LIBRARY_PATH so libc.so.6 etc. resolve. Runtime behaviour
# is unaffected: worker containers (glibc project-runtime images) exec the
# payload directly.
run_version() {
    payload="$1"
    payload_dir="$(dirname "${payload}")"
    payload_base="$(basename "${payload}")"
    # Run from the payload's own directory: some CLIs (pi) resolve their
    # version from argv[0]-relative sidecars (package.json), so the loader
    # fallback must keep argv[0] inside the payload dir.
    out="$(cd "${payload_dir}" && "./${payload_base}" --version 2>/dev/null | head -n 1 || true)"
    if [ -n "${out}" ]; then
        printf '%s\n' "${out}"
        return 0
    fi
    if [ -n "${GLIBC_LOADER:-}" ] && [ -x "${GLIBC_LOADER}" ]; then
        loader_dir="$(dirname "${GLIBC_LOADER}")"
        # pi resolves its version from an argv[0]-adjacent package.json; the
        # loader claims argv[0] for itself, so mirror the sidecar next to the
        # loader (build-stage-only, never shipped into the Kit).
        if [ -f "${payload_dir}/package.json" ]; then
            cp "${payload_dir}/package.json" "${loader_dir}/package.json"
        fi
        out="$(cd "${payload_dir}" && LD_LIBRARY_PATH="${loader_dir}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
            "${GLIBC_LOADER}" "${payload}" --version 2>/dev/null | head -n 1 || true)"
        if [ -n "${out}" ]; then
            printf '%s\n' "${out}"
            return 0
        fi
    fi
    return 1
}

SELECTION="${KIT_CLI_SELECTION:-}"
# "none" is the explicit empty-selection sentinel (the Docker CLI drops
# empty-valued build args); it behaves exactly like an empty selection.
if [ "${SELECTION}" = "none" ]; then
    SELECTION=""
fi
case "${SELECTION}" in
    "") KEYS="" ;;
    *) KEYS="$(printf '%s' "${SELECTION}" | tr ',+' '  ')" ;;
esac

for key in ${KEYS}; do
    case "${key}" in
        pi|opencode|claude|codex) ;;
        *)
            echo "KIT_CLI_SELECTION contains unknown harness key: ${key}" >&2
            exit 2
            ;;
    esac
done

PRESENT_JSON="{}"
MISSING=""
missing_count=0

for key in ${KEYS}; do
    case "${key}" in
        pi) rel="bin/pi" ;;
        opencode) rel="opencode" ;;
        claude) rel="claude" ;;
        codex) rel="bin/codex" ;;
    esac
    payload="/payloads/${key}/${rel}"
    if [ ! -f "${payload}" ]; then
        echo "WARNING: harness '${key}' selected but payload ${payload} is missing; manifest will record missing_payload" >&2
        if [ "${missing_count}" -eq 0 ]; then
            MISSING="${key}"
        else
            MISSING="${MISSING} ${key}"
        fi
        missing_count=$((missing_count + 1))
        continue
    fi
    if [ ! -x "${payload}" ]; then
        echo "ERROR: harness '${key}' payload is not executable: ${payload}" >&2
        exit 2
    fi
    if ! version_output="$(run_version "${payload}")"; then
        echo "ERROR: harness '${key}' --version produced no output: ${payload}" >&2
        exit 2
    fi
    if ! observed="$(extract_semver "${version_output}")"; then
        echo "ERROR: harness '${key}' --version is not a valid semantic version: ${version_output}" >&2
        exit 2
    fi
    pinned=""
    case "${key}" in
        pi) pinned="${PI_CLI_VERSION:-}" ;;
        opencode) pinned="${OPENCODE_CLI_VERSION:-}" ;;
        claude) pinned="${CLAUDE_CLI_VERSION:-}" ;;
        codex) pinned="${CODEX_CLI_VERSION:-}" ;;
    esac
    if [ -z "${pinned}" ]; then
        echo "ERROR: harness '${key}' has no pinned CLI version" >&2
        exit 2
    fi
    if ! validate_semver "${pinned}"; then
        echo "ERROR: harness '${key}' pinned version is not valid semantic version: ${pinned}" >&2
        exit 2
    fi
    if [ "${observed}" != "${pinned}" ]; then
        echo "ERROR: harness '${key}' observed version '${observed}' does not equal pinned version '${pinned}' (output: ${version_output})" >&2
        exit 2
    fi
    sha256="$(sha256sum "${payload}")"
    sha256="${sha256%% *}"
    size="$(wc -c < "${payload}" | tr -d ' ')"
    PRESENT_JSON="$(printf '%s' "${PRESENT_JSON}" | "${JQ}" --arg k "${key}" \
        --arg rel "${rel}" --arg v "${observed}" --arg s "${sha256}" --arg n "${size}" \
        '. + {($k): {path: ("/opt/codify-kit/harness/" + $k + "/" + $rel), version: $v, sha256: $s, size: ($n | tonumber)}}')"
    echo "Verified harness '${key}': ${payload} (${observed}, ${size} bytes)"
done

MISSING_JSON="[]"
if [ -n "${MISSING}" ]; then
    MISSING_JSON="$(printf '%s' "${MISSING}" | tr ' ' '\n' | "${JQ}" -R -s 'split("\n") | map(select(length > 0))')"
fi

"${JQ}" -n --argjson present "${PRESENT_JSON}" --argjson missing "${MISSING_JSON}" \
    '{present: $present, missing: $missing}' > /tmp/payload-evidence.json
echo "Payload evidence written to /tmp/payload-evidence.json"
