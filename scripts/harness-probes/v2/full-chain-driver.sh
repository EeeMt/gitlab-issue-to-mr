#!/usr/bin/env bash
# Run one V2 Harness through the frozen common runner. Credentials remain in
# caller environment; no credential files are read and no model output is printed.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: full-chain-driver.sh --harness claude|codex|pi|opencode --prompt FILE [options]
  --runtime-dir DIR       Archive directory (default: a new /tmp directory)
  --resume-session ID     Pass the native session identifier to the adapter
  --timeout SECONDS       Task timeout (default: 180)
  --dry-run               Validate arguments without executing
EOF
}
harness=""; prompt=""; runtime_dir=""; resume_session=""; timeout=180; dry_run=false
while (($#)); do
    case "$1" in
        --harness) harness=${2:?missing harness}; shift 2 ;;
        --prompt) prompt=${2:?missing prompt}; shift 2 ;;
        --runtime-dir) runtime_dir=${2:?missing runtime directory}; shift 2 ;;
        --resume-session) resume_session=${2:?missing session identifier}; shift 2 ;;
        --timeout) timeout=${2:?missing timeout}; shift 2 ;;
        --dry-run) dry_run=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
    esac
done
case "$harness" in claude|codex|pi|opencode) ;; *) printf '%s\n' '--harness is required' >&2; exit 2 ;; esac
[[ -n "$prompt" && -f "$prompt" ]] || { printf '%s\n' '--prompt must name a readable file' >&2; exit 2; }
[[ "$timeout" =~ ^[1-9][0-9]*$ ]] || { printf '%s\n' '--timeout must be a positive integer' >&2; exit 2; }
if "$dry_run"; then printf 'dry_run harness=%s\n' "$harness"; exit 0; fi
CODIFY_ORCHESTRATION_DIR=${CODIFY_ORCHESTRATION_DIR:-/opt/codify-kit}
[[ -r "$CODIFY_ORCHESTRATION_DIR/worker-entrypoint/harness/common.sh" ]] || { printf '%s\n' 'frozen orchestration directory is unavailable' >&2; exit 2; }
if [[ -z "$runtime_dir" ]]; then runtime_dir=$(mktemp -d "${TMPDIR:-/tmp}/codify-v2-${harness}.XXXXXX"); else mkdir -p "$runtime_dir"; fi
CODIFY_RUNTIME_DIR=$runtime_dir; CODIFY_HARNESS_KEY=$harness
CODIFY_ADAPTER_VERSION=${CODIFY_ADAPTER_VERSION:-2.0.0}
CODIFY_RUNTIME_CONTRACT_VERSION=${CODIFY_RUNTIME_CONTRACT_VERSION:-codify.worker.harness/v2}
CODIFY_ATTEMPT_ID=${CODIFY_ATTEMPT_ID:-"probe-$(date +%s)-$$"}; TASK_ID=${TASK_ID:-probe}; TASK_TIMEOUT=$timeout
export CODIFY_ORCHESTRATION_DIR CODIFY_RUNTIME_DIR CODIFY_HARNESS_KEY CODIFY_ADAPTER_VERSION CODIFY_RUNTIME_CONTRACT_VERSION CODIFY_ATTEMPT_ID TASK_ID TASK_TIMEOUT
[[ -z "$resume_session" ]] || { CODIFY_RESUME_SESSION=$resume_session; export CODIFY_RESUME_SESSION; }
# Initialization and adapter selection remain owned by production runner.sh.
source "$CODIFY_ORCHESTRATION_DIR/worker-entrypoint/harness/common.sh"
source "$CODIFY_ORCHESTRATION_DIR/worker-entrypoint/harness/runner.sh"
result_file="$CODIFY_RUNTIME_DIR/harness-result.json"
# The runner can emit raw model/provider diagnostics; this safety probe keeps
# those out of terminal logs. Its structured archive remains in runtime_dir.
set +e; codify_harness_run "$prompt" "$result_file" >/dev/null 2>&1; rc=$?; set -e
[[ -s "$result_file" ]] && result=present || result=missing
printf 'harness=%s rc=%s result=%s runtime_dir=%s\n' "$harness" "$rc" "$result" "$CODIFY_RUNTIME_DIR"
exit "$rc"
