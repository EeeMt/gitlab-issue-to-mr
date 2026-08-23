#!/usr/bin/env bash
# Full-chain acceptance benchmark. Each task uses the common driver; this script
# does not invoke a Harness CLI or initialize an adapter itself.
set -euo pipefail
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); harness=pi; output_dir=""; count=20
while (($#)); do
    case "$1" in
        --harness) harness=${2:?}; shift 2 ;;
        --output-dir) output_dir=${2:?}; shift 2 ;;
        --count) count=${2:?}; shift 2 ;;
        -h|--help) printf '%s\n' 'Usage: benchmark.sh [--harness KEY] --output-dir DIR [--count 20]'; exit 0 ;;
        *) exit 2 ;;
    esac
done
[[ -n "$output_dir" && "$count" =~ ^[1-9][0-9]*$ ]] || { printf '%s\n' 'output-dir and positive count are required' >&2; exit 2; }
mkdir -p "$output_dir"; summary="$output_dir/summary.tsv"; printf 'index\trc\n' > "$summary"; failures=0
for ((index=1; index<=count; index++)); do
    prompt="$output_dir/task-$index.prompt"
    printf 'Reply with exactly: V2_BENCHMARK_%s\n' "$index" > "$prompt"
    set +e
    "$script_dir/full-chain-driver.sh" --harness "$harness" --prompt "$prompt" --runtime-dir "$output_dir/run-$index" >/dev/null
    rc=$?
    set -e
    printf '%s\t%s\n' "$index" "$rc" >> "$summary"
    (( rc == 0 )) || ((failures+=1))
done
printf 'benchmark harness=%s total=%s failures=%s summary=%s\n' "$harness" "$count" "$failures" "$summary"
(( failures == 0 ))
