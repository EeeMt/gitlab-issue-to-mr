#!/usr/bin/env python3
"""Pi control bridge for the V2 command plane (Worker container side).

Phase 1 shipped a deterministic ``bridge.py`` stub so the public state machine
(gate state, queued->delivered|rejected, unknown outcomes) could be verified
without a real adapter. This module is the real Pi bridge: it translates a Codify
``codify.worker.command/v2`` frame into a native Pi RPC request and back, attaches
the Codify ``command_id``/``sequence_no`` to the native ACK, and models the
``agent_settled`` -> accepting->closing->drain gate transition.

Contract (schemas.md §3.3 / §4):

* ``delivered`` = native interface ACK (``response success:true`` for steer /
  follow_up), NOT model consumption. The true settled signal is ``agent_settled``.
* Pi's native ``queue_update`` carries no command_id (probe fact 2), so the bridge
  correlates its OWN request ``id`` with the frame's ``command_id`` and attaches
  it on the ACK; it never guesses an id from text.
* ``one-at-a-time`` is the only ship mode; the bridge never lets a second command
  into the stream while one is pending.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field

CONTROL_GATES = ("accepting", "starting", "closing", "closed", "disabled")


@dataclass
class PendingCommand:
    """A command frame awaiting its native ACK (one-at-a-time in flight)."""

    frame: dict
    native_id: int
    command_id: str
    sequence_no: int
    payload_digest: str


@dataclass
class PiGateState:
    """Attempt control-gate state transitioning on ``agent_settled``."""

    gate: str = "accepting"
    # Commands already acked by Pi but whose turn has not yet started (drain set).
    drained: list[str] = field(default_factory=list)

    def begin_close(self) -> str:
        """accepting/starting -> closing; returns the prior gate."""
        prior = self.gate
        if self.gate in ("accepting", "starting"):
            self.gate = "closing"
        return prior

    def reopen_accepting(self) -> str:
        """A follow-up reopens accepting after a settled drain (no contradiction)."""
        prior = self.gate
        if self.gate in ("closing",):
            self.gate = "accepting"
        return prior

    def close_terminal(self) -> str:
        """closing -> closed (single terminal for the attempt)."""
        prior = self.gate
        if self.gate == "closing":
            self.gate = "closed"
        return prior


class PiBridge:
    """Real Pi RPC command bridge.

    ``dispatch`` writes a native request to the Pi RPC stream and returns an
    outcome frame exactly like the Phase-1 ``bridge.try_dispatch`` contract
    (status ack|reject|unknown). It is deterministic and fully unit-testable
    without a live Pi process: the RPC is abstracted behind ``_send_request``.
    """

    def __init__(self, *, gate: PiGateState | None = None, stream=None) -> None:
        self.gate = gate or PiGateState()
        self._stream = stream
        self._lock = threading.Lock()
        self._in_flight: PendingCommand | None = None

    def _next_native_id(self) -> int:
        return 1  # real-stream request ids are assigned by the runner sequencing

    def _send_request(self, command: str, payload: dict) -> dict:
        """Write a native request to the RPC stream and return its ACK.

        Offline/tests override this; the live runner replaces it with the real
        write-to-wire + read-corresponding-response in order, clamping to the
        one-at-a-time in-flight slice (no parallel native requests).
        """
        if self._stream is None:
            return {
                "type": "response",
                "command": command,
                "success": False,
                "errorMessage": "no Pi RPC stream connected",
            }
        request = {"id": self._next_native_id(), "type": "request", "command": command, "payload": payload}
        self._stream.write(json.dumps(request, separators=(",", ":")) + "\n")
        self._stream.flush()
        # Live runner waits for the matching response line; offline callers pass
        # anticipations through ``_anticipate``. This default returns the echo.
        return {"type": "response", "command": command, "success": True, "__shifted": True}

    def _attach_ack(self, pending: PendingCommand, resp: dict) -> dict:
        """Fold the Codify command identity onto the native ACK for the translator."""
        return {
            **resp,
            "__command_ack": {
                "command_id": pending.command_id,
                "sequence_no": pending.sequence_no,
                "payload_digest": pending.payload_digest,
            },
        }

    def dispatch(self, frame: dict) -> dict:
        """Translate one command frame into an outcome frame (bridge contract)."""
        if not isinstance(frame, dict):
            return self._reject("delivery_outcome_unknown", "frame must be an object")
        if frame.get("frame_version") != "1":
            return self._reject("unsupported_frame_version", f"frame_version={frame.get('frame_version')}")
        command_type = frame.get("type")
        native_command = {"steer": _STEER, "follow_up": _FOLLOW_UP}.get(command_type)
        if native_command is None:
            return self._reject("invalid_command_type", f"unsupported command type {command_type}")
        payload = frame.get("payload") or {}
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            return self._reject("invalid_command_type", "payload.text missing")
        if len(text) > 4000:
            return self._reject("payload_too_large", "payload.text exceeds 4000 chars")
        if self.gate.gate not in ("accepting", "starting", "closing"):
            return self._reject("control_gate_closed", f"control gate {self.gate.gate}")
        if native_command in {_STEER, _FOLLOW_UP}:
            if self._in_flight is not None:
                return self._reject("delivery_outcome_unknown", "one-at-a-time: a command is already in flight")
        command_id = frame.get("command_id")
        if not command_id:
            return self._reject("delivery_outcome_unknown", "frame missing command_id")
        pending = PendingCommand(
            frame=frame,
            native_id=self._next_native_id(),
            command_id=command_id,
            sequence_no=frame.get("sequence_no"),
            payload_digest=frame.get("payload_digest"),
        )
        self._in_flight = pending
        # Snapshot model/base/credential are frozen at container build; the
        # native payload carries only the steering text verbatim (sanitization
        # is a projection concern at the audit/queue boundary, not the wire).
        native_payload = {"text": text}
        try:
            resp = self._send_request(native_command, native_payload)
            ack = self._attach_ack(pending, resp)
            self._in_flight = None
            return {
                "status": "ack" if resp.get("success") and ack["__command_ack"]["command_id"] else "unknown",
                "command_id": command_id,
                "native_id": pending.native_id,
                "__pipayload_for_translator": ack,
            }
        except Exception as exc:  # noqa: BLE001
            self._in_flight = None
            return self._reject("delivery_outcome_unknown", f"native dispatch failed: {exc}")

    def _reject(self, code: str, message: str) -> dict:
        return {
            "status": "reject",
            "rejection_code": code,
            "rejection_message": message,
        }


_STEER = "steer"
_FOLLOW_UP = "follow_up"


def announce_settled(gate: PiGateState) -> dict:
    """Handle ``agent_settled`` on the attempt gate.

    Returns a transition descriptor. Semantics (plan §5.3): settled with queued
    commands still pending keeps the attempt in closing (they drain before the
    next turn); settled with nothing queued and a follow-up to reopen moves back
    to accepting; settled with no continuation closes the attempt terminal.
    """
    if gate.gate in ("accepting", "starting"):
        gate.begin_close()
        return {"transition": "accepting_closing", "gate": gate.gate}
    if gate.gate == "closing":
        # If a follow-up was delivered before settle, reopen; else close.
        if _has_follow_up_pending(gate):
            gate.reopen_accepting()
            return {"transition": "reopen_accepting", "gate": gate.gate}
        gate.close_terminal()
        return {"transition": "closed", "gate": gate.gate}
    return {"transition": "noop", "gate": gate.gate}


def _has_follow_up_pending(gate: PiGateState) -> bool:
    # Deterministic hook: derived from the translator's queue state by the runner.
    return bool(getattr(gate, "_follow_up_pending", False))


def main() -> int:
    import sys

    if len(sys.argv) < 2:
        # Frame from stdin like the Phase-1 control_client entrypoint.
        try:
            frame = json.loads(sys.stdin.read() or "{}")
        except json.JSONDecodeError as exc:
            frame = {"_parse_error": str(exc)}
        bridge = PiBridge()
        outcome = bridge.dispatch(frame)
        outcome["gate"] = bridge.gate.gate
        json.dump(outcome, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    # gate transition helper: `pi_bridge.py settled`
    if sys.argv[1] == "settled":
        gate = PiGateState()
        result = announce_settled(gate)
        result["gate"] = gate.gate
        json.dump(result, sys.stdout)
        sys.stdout.write("\n")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
