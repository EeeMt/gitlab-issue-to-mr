#!/usr/bin/env bash
set -euo pipefail

# The Worker Kit archive is the integrity boundary. The installed Kit carries
# both this release verifier and its portable manifest validator; this wrapper
# never falls back to a checkout copy.
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
exec "${KIT_PATH}/verify-runtime.sh" "$@"
