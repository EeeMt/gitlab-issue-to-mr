#!/usr/bin/env bash
# Minimal Pi RPC fact probe. It serializes native requests and reports only
# event names/counts, never raw stdout or configured credentials.
set -euo pipefail
prompt='Reply with exactly: PI_RPC_PROBE_OK'; pi_bin=${PI_BIN:-pi}; timeout=60; dry_run=false
while (($#)); do
    case "$1" in
        --prompt) prompt=${2:?missing prompt}; shift 2 ;;
        --pi-bin) pi_bin=${2:?missing Pi binary}; shift 2 ;;
        --timeout) timeout=${2:?missing timeout}; shift 2 ;;
        --dry-run) dry_run=true; shift ;;
        -h|--help) printf '%s\n' 'Usage: pi-rpc-sequence.sh [--pi-bin PATH] [--prompt TEXT] [--timeout SECONDS]'; exit 0 ;;
        *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
    esac
done
[[ "$timeout" =~ ^[1-9][0-9]*$ ]] || { printf '%s\n' 'timeout must be positive' >&2; exit 2; }
if "$dry_run"; then printf 'dry_run pi_bin=%s\n' "$pi_bin"; exit 0; fi
command -v "$pi_bin" >/dev/null 2>&1 || { printf '%s\n' 'Pi binary unavailable' >&2; exit 2; }
PI_PROBE_BIN=$pi_bin PI_PROBE_PROMPT=$prompt PI_PROBE_TIMEOUT=$timeout python3 - <<'PY'
import json, os, subprocess, time

proc = subprocess.Popen([os.environ["PI_PROBE_BIN"], "--mode", "rpc"], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
seen, session_id = {}, None
def receive(command, deadline):
    global session_id
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line: return False
        try: event = json.loads(line)
        except json.JSONDecodeError: continue
        kind = event.get("type", "unknown"); seen[kind] = seen.get(kind, 0) + 1
        if event.get("type") == "response" and event.get("command") == command:
            session_id = (event.get("data") or {}).get("sessionId") or session_id
            return bool(event.get("success", True))
    return False
def send(identifier, kind, **payload):
    proc.stdin.write(json.dumps({"id": identifier, "type": kind, **payload}) + "\n"); proc.stdin.flush()
deadline = time.monotonic() + int(os.environ["PI_PROBE_TIMEOUT"])
try:
    send(1, "new_session"); fresh_ack = receive("new_session", deadline)
    send(2, "get_state"); state_ack = receive("get_state", deadline)
    send(3, "prompt", message=os.environ["PI_PROBE_PROMPT"]); settled = False
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line: break
        try: event = json.loads(line)
        except json.JSONDecodeError: continue
        kind = event.get("type", "unknown"); seen[kind] = seen.get(kind, 0) + 1
        if kind == "agent_settled": settled = True; break
    resume_ack = False
    if session_id:
        send(4, "new_session", parentSessionId=session_id); resume_ack = receive("new_session", deadline)
    print(json.dumps({"fresh_ack": fresh_ack, "state_ack": state_ack, "settled": settled,
                      "continuation_ack": resume_ack, "event_counts": seen}, sort_keys=True))
    raise SystemExit(0 if all((fresh_ack, state_ack, settled)) else 1)
finally:
    proc.kill(); proc.wait()
PY
