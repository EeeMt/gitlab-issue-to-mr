"""Offline replay of the four Harness ``harness_events_v2/`` canonical fixtures.

Each JSONL fixture is a complete V2 attempt (run.started → ... → harness
terminal → worker.finalization → single task terminal). The projector selects
the V2 validator by the event schema; these fixtures assert that path without
needing any real Adapter, plus the control-plane audit semantics for Pi.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.harness_protocol import (
    CANONICAL_EVENT_SCHEMA_V2,
    CONTROL_EVENT_TYPES,
    CanonicalEventReplay,
    HarnessProtocolError,
    replay_events,
    validate_event_v2,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "backend" / "tests" / "fixtures" / "harness_events_v2"

MATRIX = {
    "pi": {
        "transport": "rpc_stdio",
        "protocols": {"anthropic_messages", "openai_responses", "openai_chat_completions"},
        "control": True,
    },
    "opencode": {
        "transport": "server_http",
        "protocols": {"anthropic_messages", "openai_responses", "openai_chat_completions"},
        "control": False,
    },
    "claude": {"transport": "cli_stream_json", "protocols": {"anthropic_messages"}, "control": False},
    "codex": {"transport": "cli_jsonl", "protocols": {"openai_responses"}, "control": False},
}


def _iter_fixtures():
    for path in sorted(FIXTURE_ROOT.rglob("*.jsonl")):
        yield path


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_all_four_harness_fixtures_exist():
    harness_dirs = {path.name for path in FIXTURE_ROOT.iterdir() if path.is_dir()}
    assert harness_dirs == set(MATRIX)


@pytest.mark.parametrize("path", _iter_fixtures(), ids=lambda p: str(p.relative_to(FIXTURE_ROOT)))
def test_v2_fixture_validates_and_replays_offline(path: Path):
    events = _jsonl(path)
    assert events, f"{path} is empty"
    harness = events[0]["harness"]["key"]
    expected = MATRIX[harness]
    for event in events:
        normalized = validate_event_v2(event)
        assert normalized["schema"] == CANONICAL_EVENT_SCHEMA_V2
        assert normalized["harness"]["control_transport"]["kind"] == expected["transport"]
        assert set(normalized["harness"]["model_protocols"]) == expected["protocols"]
    replay = replay_events(events)
    assert replay.harness_key == harness
    # A fixture may end in either task terminal (success vs harness failure);
    # the replay terminal must match the fixture's final event type.
    assert replay.terminal_type == events[-1]["type"]
    # Control events only appear for command-capable harnesses.
    control_types = {e["type"] for e in events if e["type"] in CONTROL_EVENT_TYPES}
    if expected["control"]:
        assert control_types
    else:
        assert not control_types


def test_pi_rejected_fixture_carries_control_rejected_event():
    events = _jsonl(FIXTURE_ROOT / "pi" / "rejected.v2.jsonl")
    rejected = next(e for e in events if e["type"] == "control.command.rejected")
    assert rejected["payload"]["rejection_code"] == "control_gate_closed"
    assert rejected["payload"]["command_id"]
    replay = replay_events(events)
    assert replay.terminal_type == "run.completed"


def test_projector_does_not_rewrite_command_state_from_control_events():
    # Behavioral contract: the projector (worker_event_projector) only audits
    # control events; it never writes back to task_harness_commands. We assert
    # the fixture set plus the validation path here — the no-write guarantee is
    # structural (audit-only TaskLog branch) and covered by integration.
    for path in _iter_fixtures():
        for event in _jsonl(path):
            if event["type"] in CONTROL_EVENT_TYPES:
                assert "command_id" in event["payload"] or event["type"] == "control.queue.updated"


def test_v2_event_rejects_schema_drift_mid_attempt():
    events = _jsonl(FIXTURE_ROOT / "claude" / "success.v2.jsonl")
    replay = CanonicalEventReplay()
    first = events[0]
    replay.ingest(first)
    drifted = json.loads(json.dumps(events[1]))
    drifted["harness"]["model_protocols"] = ["openai_responses"]
    with pytest.raises(HarnessProtocolError, match="model_protocols changed"):
        replay.ingest(drifted)


def test_v2_agent_settled_is_recognized_not_downgraded():
    # Pi's agent_settled is the true settled signal (probe fact 1); the V2
    # validator must recognize it as an auditable type rather than downgrading
    # it to a diagnostic unknown_event_type.
    events = _jsonl(FIXTURE_ROOT / "pi" / "success.v2.jsonl")
    settled = json.loads(json.dumps(events[1]))
    settled["event_id"] = "pi-fixture-agent-settled"
    settled["seq"] = 99
    settled["type"] = "agent_settled"
    settled["payload"] = {"aborted": False, "settled_line": 12}
    normalized = validate_event_v2(settled)
    assert normalized["type"] == "agent_settled"
    assert normalized["schema"] == CANONICAL_EVENT_SCHEMA_V2
