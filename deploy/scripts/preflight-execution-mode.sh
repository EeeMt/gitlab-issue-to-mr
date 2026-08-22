#!/usr/bin/env bash
# Deployment preflight (open-harness-v2 plan §4.8): compare the
# HARNESS_EXECUTION_MODE reported by the Backend and Scheduler /health
# endpoints. A mismatch (or a missing value) aborts the deployment.
#
# Usage:
#   preflight-execution-mode.sh [BACKEND_HEALTH_URL] [SCHEDULER_HEALTH_URL]
#
# Defaults target the dev compose stack:
#   http://localhost:8000/health  and  http://localhost:8001/health
#
# Exit codes: 0 = both present and equal, 1 = mismatch/missing/unreachable.
set -euo pipefail

# Defaults target the dev compose stack: Backend on 8000, Scheduler health
# endpoint (scheduler_health_port) published on 8001.
BACKEND_URL="${1:-http://localhost:8000/health}"
SCHEDULER_URL="${2:-http://localhost:8001/health}"

fetch_mode() {
    local url="$1" name="$2" body mode
    if ! body="$(curl -fsS --max-time 10 "$url" 2>/dev/null)"; then
        echo "PREFLIGHT FAIL: cannot reach ${name} health at ${url}" >&2
        return 2
    fi
    # Extract without requiring jq on the host: sed over the JSON field.
    mode="$(printf '%s' "$body" \
        | sed -n 's/.*"harness_execution_mode"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
    if [ -z "$mode" ]; then
        echo "PREFLIGHT FAIL: ${name} health payload has no harness_execution_mode" >&2
        return 2
    fi
    printf '%s' "$mode"
}

backend_mode="$(fetch_mode "$BACKEND_URL" "Backend")" || backend_fetch=$?
scheduler_mode="$(fetch_mode "$SCHEDULER_URL" "Scheduler")" || scheduler_fetch=$?

if [ "${backend_fetch:-0}" -ne 0 ] || [ "${scheduler_fetch:-0}" -ne 0 ]; then
    exit 1
fi

echo "Backend   harness_execution_mode = ${backend_mode}"
echo "Scheduler harness_execution_mode = ${scheduler_mode}"

if [ "$backend_mode" != "$scheduler_mode" ]; then
    echo "PREFLIGHT FAIL: Backend/Scheduler HARNESS_EXECUTION_MODE mismatch "
    echo "(${backend_mode} != ${scheduler_mode}); refusing deployment." >&2
    exit 1
fi

case "$backend_mode" in
    dual_canary|v2_only) ;;
    *)
        echo "PREFLIGHT FAIL: unknown mode '${backend_mode}'" >&2
        exit 1
        ;;
esac

echo "PREFLIGHT OK: execution modes agree on '${backend_mode}'"
