#!/bin/sh
# Verify selected Harness CLI payloads inside the Kit build and record the
# evidence that becomes the manifest harness_inventory.
#
# Runs in the nix closure builder (TARGETPLATFORM, glibc) so dynamically
# linked CLI payloads execute for real. Reads:
#   KIT_CLI_SELECTION   comma/plus-separated subset of pi,opencode,claude,codex
#   PI_CLI_VERSION OPENCODE_CLI_VERSION CLAUDE_CLI_VERSION CODEX_CLI_VERSION
#                       optional pinned versions; when set, the payload's
#                       --version output must contain the pinned value
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
    version_output="$("${payload}" --version 2>/dev/null | head -n 1 || true)"
    if [ -z "${version_output}" ]; then
        echo "ERROR: harness '${key}' --version produced no output: ${payload}" >&2
        exit 2
    fi
    pinned=""
    case "${key}" in
        pi) pinned="${PI_CLI_VERSION:-}" ;;
        opencode) pinned="${OPENCODE_CLI_VERSION:-}" ;;
        claude) pinned="${CLAUDE_CLI_VERSION:-}" ;;
        codex) pinned="${CODEX_CLI_VERSION:-}" ;;
    esac
    if [ -n "${pinned}" ] && ! printf '%s\n' "${version_output}" | grep -Fq "${pinned}"; then
        echo "ERROR: harness '${key}' --version '${version_output}' does not contain pinned version '${pinned}'" >&2
        exit 2
    fi
    observed="$(printf '%s\n' "${version_output}" | awk '{print $NF}')"
    sha256="$(sha256sum "${payload}" | awk '{print $1}')"
    size="$(wc -c < "${payload}" | tr -d ' ')"
    PRESENT_JSON="$(printf '%s' "${PRESENT_JSON}" | "${JQ}" --arg k "${key}" \
        --arg rel "${rel}" --arg v "${observed}" --arg s "${sha256}" --arg n "${size}" \
        '. + {($k): {path: ("/opt/codify-kit/harness/" + $rel), version: $v, sha256: $s, size: ($n | tonumber)}}')"
    echo "Verified harness '${key}': ${payload} (${observed}, ${size} bytes)"
done

if [ "${missing_count}" -eq 0 ]; then
    MISSING_JSON="[]"
else
    MISSING_JSON="$(printf '%s' "${MISSING}" | tr ' ' '\n' | "${JQ}" -R -s 'split("\n") | map(select(length > 0))')"
fi

"${JQ}" -n --argjson present "${PRESENT_JSON}" --argjson missing "${MISSING_JSON}" \
    '{present: $present, missing: $missing}' > /tmp/payload-evidence.json
echo "Payload evidence written to /tmp/payload-evidence.json"
