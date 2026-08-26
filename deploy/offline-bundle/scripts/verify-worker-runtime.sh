#!/usr/bin/env bash
set -euo pipefail

# The Worker Kit archive is the integrity boundary. The portable content
# verifier is kept outside the installed Kit and is passed explicitly to the
# Kit-local runtime verifier.
KIT_PATH=""
previous=""
for argument in "$@"; do
    if [ "${previous}" = "--kit" ]; then
        KIT_PATH="${argument}"
        break
    fi
    previous="${argument}"
done
[ -n "${KIT_PATH}" ] || { echo "--kit is required" >&2; exit 2; }
[ -x "${KIT_PATH}/verify-runtime.sh" ] || {
    echo "Installed Kit is missing its integrity-protected verifier" >&2
    exit 1
}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRUSTED_CONTENT_VERIFIER="${SCRIPT_DIR}/verify-kit-content.py"
if [ ! -f "${TRUSTED_CONTENT_VERIFIER}" ]; then
    TRUSTED_CONTENT_VERIFIER="${SCRIPT_DIR}/../../worker-kit/verify-kit-content.py"
fi
[ -f "${TRUSTED_CONTENT_VERIFIER}" ] || {
    echo "Trusted Worker Kit content verifier is missing" >&2
    exit 2
}
if ! python3 "${TRUSTED_CONTENT_VERIFIER}" --root "${KIT_PATH}" >/dev/null; then
    echo "Worker Kit content inventory does not match installed bytes" >&2
    exit 1
fi
export CODIFY_TRUSTED_KIT_CONTENT_VERIFIER="${TRUSTED_CONTENT_VERIFIER}"
exec "${KIT_PATH}/verify-runtime.sh" "$@"
