"""Unit tests for the in-image command bridge/control-client stubs.

These are the fixed Worker-container-side entrypoints the command pump calls
(phase1-design §2.2). Phase 1 ships them as deterministic stubs that prove the
public state machine (capability negotiation, ack/reject/unknown outcomes)
without a real Pi/OpenCode adapter.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

HARNESS_DIR = (
    Path(__file__).resolve().parents[3]
    / "deploy"
    / "worker-entrypoint"
    / "harness"
)


def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(
        f"harness_{name}", HARNESS_DIR / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def control_client():
    return _load_module("control_client")


@pytest.fixture(scope="module")
def bridge():
    return _load_module("bridge")


def _frame(**overrides):
    frame = {
        "frame_version": "1",
        "command_id": "c-1",
        "task_id": 7,
        "attempt_id": "task-7-attempt-1",
        "sequence_no": 1,
        "type": "steer",
        "payload": {"text": "hello"},
        "control_gate": "accepting",
    }
    frame.update(overrides)
    return frame


def test_control_client_retries_when_owner_socket_is_absent(control_client, tmp_path, monkeypatch):
    monkeypatch.setenv("CODIFY_RUNTIME_DIR", str(tmp_path))
    outcome = control_client.handle(_frame())
    assert outcome["status"] == "retry"
    assert outcome["rejection_code"] == "control_owner_unreachable"


def test_get_state_probe_retries_when_owner_socket_is_absent(control_client, tmp_path, monkeypatch):
    monkeypatch.setenv("CODIFY_RUNTIME_DIR", str(tmp_path))
    outcome = control_client.handle(_frame(type="get_state", payload={}))
    assert outcome["status"] == "retry"
    assert outcome["rejection_code"] == "control_owner_unreachable"


def test_control_client_does_not_write_a_second_journal(control_client, tmp_path, monkeypatch):
    monkeypatch.setenv("CODIFY_RUNTIME_DIR", str(tmp_path))
    outcome = control_client.handle(_frame())
    assert outcome["status"] == "retry"
    assert not (tmp_path / "pi-control-requests.jsonl").exists()


def test_control_client_rejects_closed_gate(control_client):
    outcome = control_client.handle(_frame(control_gate="closed"))
    assert outcome["status"] == "reject"
    assert outcome["rejection_code"] == "control_gate_closed"


def test_control_client_forwards_only_closing_drain_marker(control_client, monkeypatch):
    forwarded = []

    def forward(frame):
        forwarded.append(frame)
        return {"status": "ack", "closed": True}

    monkeypatch.setattr(control_client, "_forward_to_bridge", forward)
    expected = _frame(type="close", control_gate="closing", payload={})
    outcome = control_client.handle(expected)
    assert outcome == {"status": "ack", "closed": True}
    assert forwarded == [expected]


def test_control_client_rejects_invalid_type(control_client):
    outcome = control_client.handle(_frame(type="explode"))
    assert outcome["status"] == "reject"
    assert outcome["rejection_code"] == "invalid_command_type"


def test_control_client_rejects_oversize_text(control_client):
    outcome = control_client.handle(_frame(payload={"text": "x" * 4001}))
    assert outcome["status"] == "reject"
    assert outcome["rejection_code"] == "payload_too_large"


def test_control_client_unknown_on_empty_frame(control_client):
    outcome = control_client.handle({})
    assert outcome["status"] == "unknown"
    assert outcome["rejection_code"] == "delivery_outcome_unknown"


def test_control_client_rejects_unsupported_frame_version(control_client):
    outcome = control_client.handle(_frame(frame_version="9"))
    assert outcome["status"] == "reject"
    assert outcome["rejection_code"] == "unsupported_frame_version"


def test_control_client_main_echoes_request_correlation(control_client, monkeypatch, capsys):
    frame = _frame(control_request_id="request-1")
    monkeypatch.setattr(control_client.sys, "stdin", io.StringIO(json.dumps(frame)))

    assert control_client.main() == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "status": "retry",
        "rejection_code": "control_owner_unreachable",
        "rejection_message": "Pi control owner is unavailable",
        "control_request_id": "request-1",
    }


def test_bridge_negotiates_pi_command_capability(bridge):
    caps = bridge.negotiate_capabilities("pi")
    assert caps["steering"] is True
    assert caps["follow_up"] is True


def test_bridge_negotiates_claude_without_command_capability(bridge):
    caps = bridge.negotiate_capabilities("claude")
    assert caps["steering"] is False
    assert caps["follow_up"] is False


def test_bridge_negotiation_is_fail_closed(bridge):
    # A harness cannot widen its capability claim beyond the stub upper bound.
    caps = bridge.negotiate_capabilities("claude", requested={"steering": True})
    assert caps["steering"] is False
