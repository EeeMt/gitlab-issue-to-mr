#!/usr/bin/env bash
# Capture one isolated Harness command. Raw output must stay outside Git until sanitized.
set -euo pipefail

usage() {
    cat >&2 <<'EOF'
Usage: run-probe.sh --harness KEY --scenario NAME --output-dir DIR \
  --version-command COMMAND [--timeout SECONDS] [--grace SECONDS] -- COMMAND [ARG ...]
EOF
}

HARNESS=""
SCENARIO=""
OUTPUT_DIR=""
VERSION_COMMAND=""
TIMEOUT_SECONDS=120
GRACE_SECONDS=5

while [ "$#" -gt 0 ]; do
    case "$1" in
        --harness) HARNESS="${2:-}"; shift 2 ;;
        --scenario) SCENARIO="${2:-}"; shift 2 ;;
        --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
        --version-command) VERSION_COMMAND="${2:-}"; shift 2 ;;
        --timeout) TIMEOUT_SECONDS="${2:-}"; shift 2 ;;
        --grace) GRACE_SECONDS="${2:-}"; shift 2 ;;
        --) shift; break ;;
        *) usage; exit 2 ;;
    esac
done

[ -n "${HARNESS}" ] && [ -n "${SCENARIO}" ] && [ -n "${OUTPUT_DIR}" ] \
    && [ -n "${VERSION_COMMAND}" ] && [ "$#" -gt 0 ] || { usage; exit 2; }
[[ "${HARNESS}" =~ ^[a-z0-9_-]+$ ]] || { echo "Invalid harness key" >&2; exit 2; }
[[ "${SCENARIO}" =~ ^[a-z0-9_-]+$ ]] || { echo "Invalid scenario name" >&2; exit 2; }
[[ "${TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]] || { echo "Invalid timeout" >&2; exit 2; }
[[ "${GRACE_SECONDS}" =~ ^[1-9][0-9]*$ ]] || { echo "Invalid grace" >&2; exit 2; }

umask 077
mkdir -p "${OUTPUT_DIR}"
OUTPUT_DIR=$(cd "${OUTPUT_DIR}" && pwd -P)
PROBE_HOME=$(mktemp -d "${TMPDIR:-/tmp}/codify-harness-probe.XXXXXX")
cleanup() {
    rm -rf "${PROBE_HOME}"
}
trap cleanup EXIT

STDOUT_FILE="${OUTPUT_DIR}/stdout.jsonl"
STDERR_FILE="${OUTPUT_DIR}/stderr.log"
PROCESS_FILE="${OUTPUT_DIR}/process.json"
METADATA_FILE="${OUTPUT_DIR}/metadata.json"
COMMAND_FILE="${OUTPUT_DIR}/command.txt"
: > "${STDOUT_FILE}"
: > "${STDERR_FILE}"

STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
CLI_VERSION=$(env -i PATH="${PATH}" HOME="${PROBE_HOME}" TMPDIR="${PROBE_HOME}" \
    bash -lc "${VERSION_COMMAND}" 2>&1 || true)

# Record the argv shape without environment values. Prompt/config files should be passed by path.
printf '%q ' "$@" > "${COMMAND_FILE}"
printf '\n' >> "${COMMAND_FILE}"
ENV_KEYS=$(env | cut -d= -f1 | LC_ALL=C sort | tr '\n' ',' | sed 's/,$//')

set +e
python3 - "${STDOUT_FILE}" "${STDERR_FILE}" "${PROCESS_FILE}" \
    "${PROBE_HOME}" "${TIMEOUT_SECONDS}" "${GRACE_SECONDS}" "$@" <<'PY'
import datetime
import json
import os
import signal
import subprocess
import sys

stdout_path, stderr_path, process_path, probe_home, timeout, grace, *command = sys.argv[1:]
environment = os.environ.copy()
environment.update({
    "HOME": probe_home,
    "XDG_CONFIG_HOME": os.path.join(probe_home, ".config"),
    "XDG_DATA_HOME": os.path.join(probe_home, ".local", "share"),
    "XDG_CACHE_HOME": os.path.join(probe_home, ".cache"),
    "CODEX_HOME": os.path.join(probe_home, ".codex"),
})
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "CODEX_HOME"):
    os.makedirs(environment[name], mode=0o700, exist_ok=True)

started = datetime.datetime.now(datetime.UTC)
timed_out = False
term_sent = False
kill_sent = False
received_signal = None
with open(stdout_path, "wb") as stdout, open(stderr_path, "wb") as stderr:
    process = subprocess.Popen(
        command,
        stdout=stdout,
        stderr=stderr,
        env=environment,
        start_new_session=True,
    )

    def relay(signum, _frame):
        nonlocal_received[0] = signal.Signals(signum).name
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass

    nonlocal_received = [None]
    signal.signal(signal.SIGTERM, relay)
    signal.signal(signal.SIGINT, relay)
    try:
        exit_code = process.wait(timeout=int(timeout))
    except subprocess.TimeoutExpired:
        timed_out = True
        term_sent = True
        os.killpg(process.pid, signal.SIGTERM)
        try:
            exit_code = process.wait(timeout=int(grace))
        except subprocess.TimeoutExpired:
            kill_sent = True
            os.killpg(process.pid, signal.SIGKILL)
            exit_code = process.wait()
    received_signal = nonlocal_received[0]
ended = datetime.datetime.now(datetime.UTC)
with open(process_path, "w", encoding="utf-8") as handle:
    json.dump({
        "pid": process.pid,
        "pgid": process.pid,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "term_sent": term_sent,
        "kill_sent": kill_sent,
        "received_signal": received_signal,
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "ended_at": ended.isoformat().replace("+00:00", "Z"),
    }, handle, indent=2, sort_keys=True)
    handle.write("\n")
raise SystemExit(exit_code if exit_code >= 0 else 128 + abs(exit_code))
PY
EXIT_CODE=$?
set -e
ENDED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

python3 - "${METADATA_FILE}" "${HARNESS}" "${SCENARIO}" "${CLI_VERSION}" \
    "${STARTED_AT}" "${ENDED_AT}" "${ENV_KEYS}" <<'PY'
import json, platform, sys
path, harness, scenario, version, started, ended, env_keys = sys.argv[1:]
with open(path, "w", encoding="utf-8") as handle:
    json.dump({
        "fixture_schema": "codify.harness.fixture/v1",
        "harness": harness, "scenario": scenario, "cli_version": version.strip(),
        "adapter_candidate_version": "1.0.0", "image_digest": None,
        "provider_kind": "probe", "wire_protocol": "probe",
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "command_file": "command.txt", "environment_keys": env_keys.split(",") if env_keys else [],
        "environment_sources": {key: "operator_environment" for key in env_keys.split(",") if key},
        "started_at": started, "ended_at": ended, "expected_result": None,
        "collection_state": "raw-restricted-do-not-commit",
    }, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

exit "${EXIT_CODE}"
