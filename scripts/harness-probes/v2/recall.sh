#!/usr/bin/env bash
# Semantic context-recall probe; uses the shared full-chain runner twice.
set -euo pipefail
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); harness=pi; output_dir=""
while (($#)); do
    case "$1" in --harness) harness=${2:?}; shift 2;; --output-dir) output_dir=${2:?}; shift 2;; -h|--help) printf '%s\n' 'Usage: recall.sh [--harness KEY] --output-dir DIR'; exit 0;; *) exit 2;; esac
done
[[ -n "$output_dir" ]] || { printf '%s\n' '--output-dir is required' >&2; exit 2; }
mkdir -p "$output_dir"; token="recall-$RANDOM-$RANDOM"
printf 'Remember this test marker for the next turn: %s. Reply only ACK.\n' "$token" > "$output_dir/turn-1.prompt"
"$script_dir/full-chain-driver.sh" --harness "$harness" --prompt "$output_dir/turn-1.prompt" --runtime-dir "$output_dir/turn-1"
session_id=$(python3 - "$output_dir/turn-1/harness-result.json" <<'PY'
import json, sys
try: print(json.load(open(sys.argv[1])).get("session_id", ""))
except (OSError, ValueError): pass
PY
)
[[ -n "$session_id" ]] || { printf '%s\n' 'recall_session=missing' >&2; exit 1; }
printf '%s\n' 'Repeat the test marker from the preceding turn exactly, with no other text.' > "$output_dir/turn-2.prompt"
"$script_dir/full-chain-driver.sh" --harness "$harness" --prompt "$output_dir/turn-2.prompt" --runtime-dir "$output_dir/turn-2" --resume-session "$session_id"
python3 - "$output_dir/turn-2/harness-result.json" "$token" <<'PY'
import json, sys
try: text = json.load(open(sys.argv[1])).get("result", "")
except (OSError, ValueError): text = ""
print("recall=" + ("passed" if text.strip() == sys.argv[2] else "failed"))
raise SystemExit(0 if text.strip() == sys.argv[2] else 1)
PY
