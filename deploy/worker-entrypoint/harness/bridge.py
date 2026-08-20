#!/usr/bin/env python3
"""Bridge control endpoint for the V2 command plane (Worker container side).

Runs inside a Worker container next to the Harness Adapter. It exposes two
functions used by the command pump and by the offline test suite:

- ``negotiate_capabilities`` — the capability handshake the registry/control
  gate performs when an attempt opens (schemas.md §6).
- ``try_dispatch`` — round-trip one command frame through the fixed
  ``control_client.py`` entrypoint and return the resulting outcome.

Phase-1 scope: this is a deterministic stub that lets the whole public state
machine (gate state, queued->delivered|rejected, unknown outcomes) be verified
without a real Pi/OpenCode adapter. Real adapters replace the *body*, never the
frame contract.
"""

from __future__ import annotations

import json
import subprocess
import sys

CONTROL_CLIENT = "control_client.py"

# Capability upper bounds a harness can *request*; the system allowlist in the
# backend can only tighten these, never widen them (phase1-design §2.4).
DEFAULT_CAPABILITIES = {
    "resume": False,
    "task_skills": True,
    "usage_tokens": True,
    "steering": False,
    "follow_up": False,
}


def negotiate_capabilities(harness_key: str, requested: dict | None = None) -> dict:
    """Return the deterministic capability projection for a harness key.

    Only Pi claims command capability in the first release; all other harnesses
    report ``steering``/``follow_up`` False, which the control gate translates
    to ``control_gate=disabled`` (no commands accepted).
    """
    caps = dict(DEFAULT_CAPABILITIES)
    if harness_key == "pi":
        caps["steering"] = True
        caps["follow_up"] = True
    if isinstance(requested, dict):
        # A harness can never widen its own capability claim beyond the stub
        # upper bound; it may only shrink it (fail closed).
        for key, value in requested.items():
            if key in caps and not value:
                caps[key] = False
    return caps


def try_dispatch(frame: dict) -> dict:
    """Round-trip one frame through the fixed control_client entrypoint."""
    proc = subprocess.run(
        [sys.executable or "python3", CONTROL_CLIENT],
        input=json.dumps(frame, sort_keys=True),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return {
            "status": "unknown",
            "rejection_code": "delivery_outcome_unknown",
            "rejection_message": f"control_client exited {proc.returncode}: {proc.stderr[:2000]}",
        }
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {
            "status": "unknown",
            "rejection_code": "delivery_outcome_unknown",
            "rejection_message": f"malformed control_client output: {exc}",
        }


def main() -> int:
    harness_key = sys.argv[1] if len(sys.argv) > 1 else "claude"
    frame = json.loads(sys.stdin.read() or "{}")
    outcome = try_dispatch(frame)
    outcome["__capabilities"] = negotiate_capabilities(harness_key)
    json.dump(outcome, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
