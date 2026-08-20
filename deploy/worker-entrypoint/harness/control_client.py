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
import sys

FRAME_VERSION = "1"
SUPPORTED_FRAME_TYPES = {"steer", "follow_up"}


def _read_frame() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"_parse_error": str(exc)}


def handle(frame: dict) -> dict:
    """Translate one command frame into an outcome frame."""
    if not frame:
        return {"status": "unknown", "rejection_code": "delivery_outcome_unknown",
                "rejection_message": "empty or unparsable frame"}
    if frame.get("frame_version") != FRAME_VERSION:
        return {"status": "reject", "rejection_code": "unsupported_frame_version",
                "rejection_message": f"frame_version={frame.get('frame_version')}"}
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
    # Deterministic ack for a valid, supported command.
    return {"status": "ack", "command_id": frame.get("command_id")}


def main() -> int:
    outcome = handle(_read_frame())
    json.dump(outcome, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
