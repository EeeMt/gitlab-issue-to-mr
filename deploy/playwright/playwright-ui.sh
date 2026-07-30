#!/usr/bin/env bash
set -Eeuo pipefail

ui_host="${PLAYWRIGHT_UI_HOST:-0.0.0.0}"
ui_port="${PLAYWRIGHT_UI_PORT:-9323}"

if [[ ! "${ui_port}" =~ ^[0-9]+$ ]] || ((ui_port < 1 || ui_port > 65535)); then
    echo "PLAYWRIGHT_UI_PORT must be an integer between 1 and 65535" >&2
    exit 2
fi

exec playwright test \
    --ui \
    --ui-host="${ui_host}" \
    --ui-port="${ui_port}" \
    "$@"
