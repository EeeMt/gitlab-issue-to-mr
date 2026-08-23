#!/usr/bin/env bash
# Protocol-level resume probe built exclusively on full-chain-driver.sh.
set -euo pipefail
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); harness=pi; output_dir=""
while (($#)); do
    case "$1" in --harness) harness=${2:?}; shift 2;; --output-dir) output_dir=${2:?}; shift 2;; -h|--help) printf '%s\n' 'Usage: resume.sh [--harness KEY] --output-dir DIR'; exit 0;; *) exit 2;; esac
done
[[ -n "$output_dir" ]] || { printf '%s\n' '--output-dir is required' >&2; exit 2; }
mkdir -p "$output_dir"
printf '%s\n' 'Reply with exactly: RESUME_TURN_ONE.' > "$output_dir/turn-1.prompt"
printf '%s\n' 'Reply with exactly: RESUME_TURN_TWO.' > "$output_dir/turn-2.prompt"
"$script_dir/full-chain-driver.sh" --harness "$harness" --prompt "$output_dir/turn-1.prompt" --runtime-dir "$output_dir/turn-1"
session_id=$(python3 - "$output_dir/turn-1/harness-result.json" <<'PY'
import json, sys
try: print(json.load(open(sys.argv[1])).get("session_id", ""))
except (OSError, ValueError): pass
PY
)
[[ -n "$session_id" ]] || { printf '%s\n' 'resume_session=missing' >&2; exit 1; }
"$script_dir/full-chain-driver.sh" --harness "$harness" --prompt "$output_dir/turn-2.prompt" --runtime-dir "$output_dir/turn-2" --resume-session "$session_id"
printf '%s\n' 'resume_protocol=completed'
