#!/usr/bin/env python3
"""Fixed in-image control-client entrypoint for V2 command dispatch.

This is the only executable the command pump calls inside a Worker container
(phase1-design §2.2): it reads a single control command frame as JSON from
stdin and writes one outcome frame to stdout.

Phase-1 scope: this is a stub that proves the public state machine
(queued -> delivered|rejected, capability negotiation and deterministic reject)
without any real Pi/OpenCode adapter. It is intentionally trivial and safe to
run standalone::

    echo '<frame json>' | python3 control_client.py

Outcome ``status`` is one of ``ack`` | ``reject`` | ``unknown``.
"""

from __future__ import annotations

import json
import socket
import sys

FRAME_VERSION = "1"
SUPPORTED_FRAME_TYPES = {"steer", "follow_up"}
# Liveness probe frame: proves the control endpoint is reachable without
# touching the harness conversation (pump promotes starting -> accepting).
PROBE_FRAME_TYPE = "get_state"


def _read_frame() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_parse_error": "invalid_json"}


def handle(frame: dict) -> dict:
    """Translate one command frame into an outcome frame."""
    if not frame:
        return {"status": "unknown", "rejection_code": "delivery_outcome_unknown",
                "rejection_message": "empty or unparsable frame"}
    if frame.get("frame_version") != FRAME_VERSION:
        return {"status": "reject", "rejection_code": "unsupported_frame_version",
                "rejection_message": f"frame_version={frame.get('frame_version')}"}
    if frame.get("type") == PROBE_FRAME_TYPE:
        return _forward_to_bridge(frame)
    if frame.get("type") == "close":
        if frame.get("control_gate") != "closing":
            return {"status": "reject", "rejection_code": "control_gate_closed"}
        return _forward_to_bridge(frame)
    if frame.get("type") not in SUPPORTED_FRAME_TYPES:
        return {"status": "reject", "rejection_code": "invalid_command_type",
                "rejection_message": f"unsupported command type {frame.get('type')}"}
    if frame.get("control_gate") not in ("accepting", "starting", "closing"):
        return {"status": "reject", "rejection_code": "control_gate_closed",
                "rejection_message": f"control gate {frame.get('control_gate')} not deliverable"}
    # Minimal payload validation: text must be present and within the 4000-char cap.
    payload = frame.get("payload") or {}
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return {"status": "reject", "rejection_code": "invalid_command_type",
                "rejection_message": "payload.text missing"}
    if len(text) > 4000:
        return {"status": "reject", "rejection_code": "payload_too_large",
                "rejection_message": "payload.text exceeds 4000 chars"}
    return _forward_to_bridge(frame)


def _forward_to_bridge(frame: dict) -> dict:
    """Synchronously proxy one frame to the sole Pi owner Unix socket."""
    task_id = frame.get("task_id")
    if not isinstance(task_id, int) or task_id <= 0:
        return {"status": "reject", "rejection_code": "invalid_command_type"}
    # A Docker exec starts with a fresh environment, so both runner and client
    # derive this path from the durable frame rather than a runner-only export.
    socket_path = f"/tmp/codify-pi-{task_id}.sock"
    connected = False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(16)
            client.connect(socket_path)
            connected = True
            client.sendall(json.dumps(frame, separators=(",", ":")).encode() + b"\n")
            data = b""
            while not data.endswith(b"\n"):
                chunk = client.recv(8192)
                if not chunk:
                    break
                data += chunk
        return json.loads(data.decode() or "{}")
    except Exception:
        if not connected:
            return {
                "status": "retry",
                "rejection_code": "control_owner_unreachable",
                "rejection_message": "Pi control owner is unavailable",
            }
        return {
            "status": "unknown",
            "rejection_code": "delivery_outcome_unknown",
            "rejection_message": "control socket outcome lost after connect",
        }


def main() -> int:
    frame = _read_frame()
    outcome = handle(frame)
    # The Docker-side pump reads a persisted outcome after a detached exec.
    # Echo only this opaque per-invocation token so an older outcome file can
    # never be accepted as the result of the current request.
    request_id = frame.get("control_request_id") if isinstance(frame, dict) else None
    if isinstance(request_id, str) and request_id:
        outcome = dict(outcome)
        outcome["control_request_id"] = request_id
    json.dump(outcome, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
