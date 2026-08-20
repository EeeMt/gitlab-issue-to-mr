#!/usr/bin/env python3
"""Open-Harness V2 canonical-event replay generator (Phase 0, §3.4).

Reads the frozen V1 canonical fixtures (codify.worker.event/v1) for Claude and
Codex and re-derives the V2 canonical stream (codify.worker.event/v2) that the
V2 pipeline would emit for the SAME raw harness captures.

This is a *replay* of already-captured V1 evidence, not a re-run of the CLIs:
the raw event streams are unchanged; only the canonical envelope and the CLID
version pins change per the V2 architecture (docs/architecture/open-harness-v2.md).

V1 -> V2 deltas applied:
  - schema:     "codify.worker.event/v1"  -> "codify.worker.event/v2"
  - harness:    adapter_version "1.0.0(-candidate)" -> "2.0.0"
  - harness:    cli_version bumped to the V2 pinned version (codex "0.146.0",
                claude "2.1.152"), with control_transport/model_protocol added
                for first-class harnesses (pi/opencode).
  - event_id:   suffixed with "-v2" so V1 and V2 replay fixtures do not collide.
  - unchanged:  event type vocabulary (run.*, model.*, tool.*, message.*,
                harness.*, worker.*), (attempt_id, seq) idempotency, worker
                finalization before the single task terminal.

The V2 native boundary evidence (Pi steer/follow_up/abort, OpenCode
session/event/abort) is captured separately under docs/harness-probes/v2/pi and
/opencode; the three new V2 control events (control.command.delivered/rejected,
control.queue.updated) are *appended-only* audit events and are not synthesised
from V1 CLI captures.

Usage:
  python3 replay_v2.py <harness> <scenario_dir> [--write|--check|print]
  <harness> in {claude, codex}; reads <scenario_dir>/expected-canonical.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# V2 pinned CLI versions (see docs/harness-probes/v2/README.md §3.1)
CLI_VERSION = {
    "claude": "2.1.152",
    "codex": "0.146.0",
}
# control_transport / model_protocol reflect the V2 runtime manifest for first-class harnesses
CONTROL_TRANSPORT = {
    "claude": {"kind": "cli_stream_json", "protocol": "claude-json"},
    "codex": {"kind": "cli_jsonl", "protocol": "codex-jsonl"},
    "pi": {"kind": "rpc_stdio", "protocol": "pi-rpc"},
    "opencode": {"kind": "server_http", "protocol": "opencode-server"},
}
MODEL_PROTOCOLS = {
    "claude": ["anthropic_messages"],
    "codex": ["openai_responses"],
    "pi": ["anthropic_messages", "openai_responses", "openai_chat_completions"],
    "opencode": ["anthropic_messages", "openai_responses", "openai_chat_completions"],
}


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def replay(harness: str, scenario_dir: Path) -> list[dict]:
    v1 = _jsonl(scenario_dir / "expected-canonical.jsonl")
    out: list[dict] = []
    for ev in v1:
        e = dict(ev)
        e["schema"] = "codify.worker.event/v2"
        h = dict(ev.get("harness") or {})
        h["adapter_version"] = "2.0.0"
        h["cli_version"] = CLI_VERSION[harness]
        h["control_transport"] = CONTROL_TRANSPORT[harness]
        h["model_protocols"] = MODEL_PROTOCOLS[harness]
        e["harness"] = h
        e["event_id"] = ev.get("event_id", "") + "-v2"
        out.append(e)
    return out


def render(events: list[dict]) -> str:
    return "".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in events)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("harness", choices=sorted(CLI_VERSION))
    ap.add_argument("scenario_dir", type=Path)
    action = ap.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    action.add_argument("--write-to", type=Path)
    args = ap.parse_args()
    data = render(replay(args.harness, args.scenario_dir))
    if args.write_to:
        args.write_to.write_text(data)
        print(f"wrote {args.write_to}")
        return 0
    if args.write:
        (args.scenario_dir / "expected-canonical.v2.jsonl").write_text(data)
        print(f"wrote {args.scenario_dir / 'expected-canonical.v2.jsonl'}")
        return 0
    if args.check:
        got = (args.scenario_dir / "expected-canonical.v2.jsonl").read_text()
        return 0 if got == data else 1
    print(data, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
