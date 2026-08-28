#!/usr/bin/env bash
# V2 Harness lifecycle benchmark. Each run uses the common driver; delivery and
# Git/MR acceptance evidence must be collected from real Codify Tasks separately.
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
mkdir -p "$output_dir"; summary="$output_dir/summary.tsv"
printf 'index\trc\tduration_seconds\tstatus\tsuccess\tfailure_kind\tinput_tokens\tcached_input_tokens\toutput_tokens\treasoning_tokens\ttool_calls\tdelivery_status\thuman_acceptance\n' > "$summary"
failures=0
for ((index=1; index<=count; index++)); do
    prompt="$output_dir/task-$index.prompt"
    printf 'Reply with exactly: V2_BENCHMARK_%s\n' "$index" > "$prompt"
    run_dir="$output_dir/run-$index"
    started_at=$SECONDS
    set +e
    "$script_dir/full-chain-driver.sh" --harness "$harness" --prompt "$prompt" --runtime-dir "$run_dir" >/dev/null
    rc=$?
    set -e
    duration_seconds=$((SECONDS - started_at))
    python3 "$script_dir/summarize-run.py" \
        --index "$index" \
        --return-code "$rc" \
        --duration-seconds "$duration_seconds" \
        --result-file "$run_dir/harness-result.json" \
        --event-file "$run_dir/event.jsonl" >> "$summary"
    (( rc == 0 )) || ((failures+=1))
done
printf 'benchmark harness=%s total=%s failures=%s summary=%s\n' "$harness" "$count" "$failures" "$summary"
(( failures == 0 ))
