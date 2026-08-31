"""Tests for the Pi V2 adapter: event translator, control bridge, adapter shell.

The Pi translator is driven by the Phase-0 probe framing (docs/harness-probes/v2/pi/)
and must map Pi's native RPC records to canonical V2 events with the correct
``delivered`` (= native ACK, not model consumption) and ``agent_settled`` (true
settled) semantics (schemas.md §3.3, probe facts).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from app.core.harness_protocol import CANONICAL_EVENT_SCHEMA_V2, replay_events, validate_event_v2

REPO_ROOT = Path(__file__).resolve().parents[3]
HARNESS_DIR = REPO_ROOT / "deploy/worker-entrypoint/harness"
TRANSLATOR = HARNESS_DIR / "adapters/pi_events.py"
EVENT_WRITER = HARNESS_DIR / "events.py"
ADAPTER = HARNESS_DIR / "adapters/pi.sh"
PROBE_ROOT = REPO_ROOT / "docs/harness-probes/v2/pi"

V2_ENV = {
    "CODIFY_RUNTIME_CONTRACT_VERSION": "codify.worker.harness/v2",
    "CODIFY_EVENT_SCHEMA": CANONICAL_EVENT_SCHEMA_V2,
    "CODIFY_HARNESS_CONTROL_TRANSPORT_KIND": "rpc_stdio",
    "CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL": "pi-rpc",
    "CODIFY_HARNESS_MODEL_PROTOCOLS": "anthropic_messages",
}


def _environment(runtime_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        **V2_ENV,
        "CODIFY_RUNTIME_DIR": str(runtime_dir),
        "CODIFY_ATTEMPT_ID": "task-pi-attempt-1",
        "TASK_ID": "9",
        "CODIFY_HARNESS_KEY": "pi",
        "CODIFY_ADAPTER_VERSION": "2.0.0",
        "CODIFY_CLI_VERSION": "0.84.2",
        "CODIFY_CANONICAL_EVENT_WRITER": str(EVENT_WRITER),
        "CODIFY_HARNESS_RESULT_FILE": str(runtime_dir / "harness-result.json"),
    }


def _emit(runtime_dir: Path, event_type: str, payload: dict | None = None) -> None:
    subprocess.run(
        ["python3", str(EVENT_WRITER), event_type, "--payload", json.dumps(payload or {})],
        check=True,
        env=_environment(runtime_dir),
        capture_output=True,
        text=True,
    )


def _events(runtime_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (runtime_dir / "event.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def _translate(runtime_dir: Path, records: list[dict]) -> None:
    raw_file = runtime_dir / "harness-events/pi.jsonl"
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.touch(exist_ok=True)
    payload = "".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        for record in records
    )
    subprocess.run(
        ["python3", str(TRANSLATOR), "--raw-file", str(raw_file)],
        input=payload,
        check=True,
        env=_environment(runtime_dir),
        capture_output=True,
        text=True,
    )


def _probe_records(name: str) -> list[dict]:
    path = PROBE_ROOT / f"{name}.raw.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _get_state_record(session_id: str = "pi-sess-1") -> dict:
    return {
        "id": 1,
        "type": "response",
        "command": "get_state",
        "success": True,
        "data": {
            "model": {"id": "deepseek-v4-flash", "api": "anthropic-messages"},
            "thinkingLevel": "medium",
            "isStreaming": False,
            "steeringMode": "one-at-a-time",
            "followUpMode": "one-at-a-time",
            "sessionId": session_id,
            "messageCount": 0,
            "pendingMessageCount": 0,
        },
    }


def test_pi_stream_maps_probe_to_v2_canonical_events(tmp_path):
    runtime_dir = tmp_path / "success"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started", {"runtime_bundle_digest": "d" * 64})
    _translate(runtime_dir, _probe_records("success"))
    # Pi does not run Git/MR; delivery + task terminal are emitted by the shared
    # runner/main.sh after the harness completes.
    _emit(runtime_dir, "worker.finalization", {"exit_code": 0})
    _emit(runtime_dir, "run.completed", {"status": "completed", "success": True})

    translated = _events(runtime_dir)
    for event in translated:
        normalized = validate_event_v2(event)
        assert normalized["schema"] == CANONICAL_EVENT_SCHEMA_V2
    by_type = [event["type"] for event in translated]
    assert "model.resolved" in by_type
    # message deltas -> message.delta, final text -> message.completed
    assert "message.delta" in by_type
    assert "message.completed" in by_type
    # agent_settled is the true settled signal and is auditable
    assert "agent_settled" in by_type
    assert "harness.completed" in by_type
    # writer emits a single harness terminal
    assert by_type.count("harness.completed") == 1

    replay = replay_events(translated)
    assert replay.harness_key == "pi"
    assert replay.terminal_type == "run.completed"


def test_owner_ack_correlation_is_canonical_but_not_raw_archive(tmp_path):
    runtime_dir = tmp_path / "correlated-ack"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    _translate(
        runtime_dir,
        [
            _get_state_record(),
            {
                "id": 22,
                "type": "response",
                "command": "steer",
                "success": True,
                "__command_ack": {
                    "command_id": "cmd-22", "sequence_no": 3, "payload_digest": "d" * 64,
                    "_delivered_at": "2026-08-24T00:00:00+00:00",
                },
            },
        ],
    )
    delivered = [e for e in _events(runtime_dir) if e["type"] == "control.command.delivered"]
    assert delivered[0]["payload"]["command_id"] == "cmd-22"
    assert delivered[0]["payload"]["delivered_at"] == "2026-08-24T00:00:00+00:00"
    raw = (runtime_dir / "harness-events/pi.jsonl").read_text(encoding="utf-8")
    assert "__command_ack" not in raw



def test_pi_message_end_does_not_duplicate_completed(tmp_path):
    """message_end(stop) must not re-emit message.completed after text_end.

    Task 646: the same final assistant text appeared as two consecutive
    message.completed events because both text_end and message_end emitted it.
    """
    runtime_dir = tmp_path / "dup"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    records = [
        _get_state_record(),
        {"id": 2, "type": "response", "command": "prompt", "success": True},
        {"type": "agent_start"},
        {"type": "turn_start"},
        {
            "type": "message_update",
            "assistantMessageEvent": {"type": "text_start", "index": 0},
        },
        {
            "type": "message_update",
            "assistantMessageEvent": {"type": "text_delta", "delta": "hello "},
        },
        {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "text_end",
                "content": "hello world",
                "index": 0,
            },
        },
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "hello world"}],
                "stopReason": "stop",
            },
        },
        {"type": "agent_end", "messages": []},
        {"type": "agent_settled"},
    ]
    _translate(runtime_dir, records)

    completed = [
        e for e in _events(runtime_dir) if e["type"] == "message.completed"
    ]
    assert len(completed) == 1, (
        f"expected exactly one message.completed, got {len(completed)}"
    )
    assert completed[0]["payload"]["text"] == "hello world"


def test_pi_provider_error_maps_to_rate_limited_terminal(tmp_path):
    """Pi exposes account limits on assistant message_end.errorMessage."""
    runtime_dir = tmp_path / "rate-limit"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    _translate(
        runtime_dir,
        [
            _get_state_record(),
            {"id": 2, "type": "response", "command": "prompt", "success": True},
            {"type": "agent_start"},
            {"type": "turn_start"},
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [],
                    "stopReason": "error",
                    "errorMessage": "429 Monthly usage limit reached. Resets in 6 days.",
                },
            },
            {"type": "agent_end", "messages": [], "willRetry": False},
            {"type": "agent_settled"},
        ],
    )

    terminal = next(event for event in _events(runtime_dir) if event["type"] == "harness.failed")
    assert terminal["payload"]["failure"]["kind"] == "rate_limited"
    result = json.loads((runtime_dir / "harness-result.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["failure"]["kind"] == "rate_limited"


def test_pi_provider_failure_message_is_bounded_and_html_does_not_fake_auth_error(tmp_path):
    """A large upstream error page must not bloat or misclassify the failure."""
    runtime_dir = tmp_path / "bounded-provider-error"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    html_error = "404 Not Found authentication javascript " + ("x" * 10000)
    _translate(
        runtime_dir,
        [
            _get_state_record(),
            {"id": 2, "type": "response", "command": "prompt", "success": True},
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [],
                    "stopReason": "error",
                    "errorMessage": html_error,
                },
            },
            {"type": "agent_end", "messages": [], "willRetry": False},
            {"type": "agent_settled"},
        ],
    )

    terminal = next(event for event in _events(runtime_dir) if event["type"] == "harness.failed")
    failure = terminal["payload"]["failure"]
    assert failure["kind"] == "engine_error"
    assert len(failure["message"]) == 2000
    result = json.loads((runtime_dir / "harness-result.json").read_text(encoding="utf-8"))
    assert result["failure"] == failure


def test_pi_delivered_is_native_ack_not_model_consumption(tmp_path):
    # A steer response with success:true followed by the turn completing emits
    # control.command.delivered; delivered == interface ACK, and the probe's
    # queue_update carries no command_id so the bridge attaches it (not guessed).
    runtime_dir = tmp_path / "steer"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    records = [
        _get_state_record(),
        {"id": 2, "type": "response", "command": "prompt", "success": True},
        {
            "type": "message_update",
            "assistantMessageEvent": {"type": "text_end", "content": "done"},
        },
        {"type": "queue_update", "steering": ["STEER: stop"], "followUp": []},
        {
            "id": 3,
            "type": "response",
            "command": "steer",
            "success": True,
            "__command_ack": {
                "command_id": "cmd-steer-1",
                "sequence_no": 1,
                "payload_digest": "dd",
            },
        },
        {"type": "agent_end", "messages": [], "willRetry": False},
        {"type": "agent_settled"},
    ]
    _translate(runtime_dir, records)

    types = [e["type"] for e in _events(runtime_dir)]
    delivered = [
        e["payload"] for e in _events(runtime_dir) if e["type"] == "control.command.delivered"
    ]
    assert delivered, "a steered command ACK must emit control.command.delivered"
    assert delivered[0]["command_id"] == "cmd-steer-1"
    assert delivered[0]["sequence_no"] == 1
    assert "harness.completed" in types
    assert "control.queue.updated" in types


def test_pi_rejects_incomplete_terminal_lifecycles_as_protocol_errors(tmp_path):
    """No subset of Pi's three terminal observations may complete a task."""
    cases = {
        "agent-end-only": [
            _get_state_record(),
            {"type": "agent_end", "messages": [], "willRetry": False},
        ],
        "settled-only": [_get_state_record(), {"type": "agent_settled"}],
        "eof-after-text": [
            _get_state_record(),
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "text_end", "content": "partial"},
            },
        ],
    }
    for name, records in cases.items():
        runtime_dir = tmp_path / name
        runtime_dir.mkdir()
        _emit(runtime_dir, "run.started")
        _translate(runtime_dir, records)
        events = _events(runtime_dir)
        assert "harness.completed" not in [event["type"] for event in events]
        terminal = next(event for event in events if event["type"] == "harness.failed")
        assert terminal["payload"]["failure"]["kind"] == "protocol_error"
        # Canonical audit references remain tied to the raw stream line.
        assert terminal["raw_ref"]["stream"] == "harness-events/pi.jsonl"
        result = json.loads((runtime_dir / "harness-result.json").read_text(encoding="utf-8"))
        assert result["status"] == "protocol_error"
        assert result["failure"]["kind"] == "protocol_error"


def test_pi_requires_ordered_text_agent_end_and_settled_for_completion(tmp_path):
    runtime_dir = tmp_path / "ordered-terminal"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    _translate(
        runtime_dir,
        [
            _get_state_record(),
            {"type": "agent_settled"},
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "text_end", "content": "late text"},
            },
            {"type": "agent_end", "messages": [], "willRetry": False},
        ],
    )
    terminal = next(event for event in _events(runtime_dir) if event["type"] == "harness.failed")
    assert terminal["payload"]["failure"]["kind"] == "protocol_error"


def test_pi_queue_update_text_is_sanitized_before_projection(tmp_path):
    # Command text in queue.updated must be projected only after the shared
    # sanitizer strips secrets (plan §5.3: "命令文本经既有日志清洗后再投影").
    runtime_dir = tmp_path / "sanitize"
    runtime_dir.mkdir()
    fake_provider_key = "sk-" + "ant-secret1234567890"
    _emit(runtime_dir, "run.started")
    _translate(
        runtime_dir,
        [
            _get_state_record(),
            {"type": "queue_update", "steering": [f"use {fake_provider_key}"], "followUp": []},
        ],
    )
    queue_events = [e for e in _events(runtime_dir) if e["type"] == "control.queue.updated"]
    assert queue_events
    text = json.dumps(queue_events[0]["payload"], ensure_ascii=False)
    assert fake_provider_key not in text
    # raw archive is sanitized too (translator sanitizes each line)
    raw = (runtime_dir / "harness-events/pi.jsonl").read_text(encoding="utf-8")
    assert fake_provider_key not in raw


def test_pi_abort_maps_to_cancelled_terminal(tmp_path):
    runtime_dir = tmp_path / "abort"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    records = [
        _get_state_record(),
        {"id": 2, "type": "response", "command": "prompt", "success": True},
        {"type": "agent_start"},
        {"type": "turn_start"},
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [],
                "stopReason": "aborted",
                "errorMessage": "The operation was aborted.",
            },
        },
        {"type": "agent_settled"},
    ]
    _translate(runtime_dir, records)

    types = [e["type"] for e in _events(runtime_dir)]
    assert "harness.failed" in types
    terminal = [e for e in _events(runtime_dir) if e["type"] == "harness.failed"][0]
    assert terminal["payload"]["failure"]["kind"] == "cancelled"
    result = json.loads((runtime_dir / "harness-result.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["success"] is False


# ── pi_bridge: command dispatch + agent_settled gate transitions ─────────────

def _load_bridge():
    import importlib
    import sys

    adapters_dir = str(HARNESS_DIR / "adapters")
    if adapters_dir not in sys.path:
        sys.path.insert(0, adapters_dir)
    return importlib.import_module("pi_bridge")


def test_pi_bridge_maps_steer_frame_to_native_ack(tmp_path):
    bridge = _load_bridge()
    b = bridge.PiBridge()
    b._send_request = lambda _cmd, _p, **_kw: {  # type: ignore[method-assign]
        "type": "response",
        "command": "steer",
        "success": True,
    }
    outcome = b.dispatch(
        {
            "frame_version": "1",
            "command_id": "cmd-1",
            "sequence_no": 1,
            "type": "steer",
            "payload": {"text": "please continue"},
        }
    )
    assert outcome["status"] == "ack"
    assert outcome["command_id"] == "cmd-1"


def test_pi_bridge_writes_real_0842_request_frames(tmp_path):
    # Real pi 0.84.2 rejects the enveloping ``{"type":"request",...}`` wrapper
    # (``Unknown command: request``); the shipped bridge must write
    # ``{"type":<cmd>,"message":<text>}`` with a sequential id (probe fact).
    import io

    bridge = _load_bridge()
    stream = io.StringIO()
    b = bridge.PiBridge(stream=stream, native_id_start=4)  # after handshake ids 1..3
    outcome = b.dispatch(
        {
            "frame_version": "1",
            "command_id": "cmd-steer",
            "sequence_no": 5,
            "type": "follow_up",
            "payload": {"text": "keep going"},
        }
    )
    assert outcome["status"] == "ack"
    written = json.loads(stream.getvalue().strip())
    assert written == {"id": 4, "type": "follow_up", "message": "keep going"}
    # id sequence advances one-at-a-time
    b.dispatch(
        {
            "frame_version": "1",
            "command_id": "cmd-steer-2",
            "sequence_no": 6,
            "type": "steer",
            "payload": {"text": "stop now"},
        }
    )
    written2 = json.loads(stream.getvalue().strip().splitlines()[1])
    assert written2["id"] == 5


def test_pi_bridge_steer_frame_carries_message_not_envelope(tmp_path):
    import io

    bridge = _load_bridge()
    stream = io.StringIO()
    b = bridge.PiBridge(stream=stream, native_id_start=2)
    b.dispatch(
        {
            "frame_version": "1",
            "command_id": "cmd-x",
            "sequence_no": 1,
            "type": "steer",
            "payload": {"text": "go"},
        }
    )
    # steer maps to a message-carrying frame (no regression to the
    # ``{"type":"request",...,"payload":...}`` envelope wrapper pi rejects).
    written = json.loads(stream.getvalue().strip())
    assert written["type"] == "steer"
    assert written["message"] == "go"


def test_pi_bridge_rejects_closed_gate_and_wrong_type(tmp_path):
    bridge = _load_bridge()
    b = bridge.PiBridge()
    b.gate.gate = "closed"
    outcome = b.dispatch(
        {
            "frame_version": "1",
            "command_id": "cmd-1",
            "sequence_no": 2,
            "type": "steer",
            "payload": {"text": "go"},
        }
    )
    assert outcome["status"] == "reject"
    assert outcome["rejection_code"] == "control_gate_closed"

    b2 = bridge.PiBridge()
    bad = b2.dispatch(
        {
            "frame_version": "1",
            "command_id": "cmd-2",
            "sequence_no": 1,
            "type": "explode",
            "payload": {"text": "boom"},
        }
    )
    assert bad["status"] == "reject"
    assert bad["rejection_code"] == "invalid_command_type"


def test_pi_bridge_settled_transitions_gate(tmp_path):
    bridge = _load_bridge()
    # accepting -> closing on first settle
    gate = bridge.PiGateState()
    assert bridge.announce_settled(gate)["transition"] == "accepting_closing"
    assert gate.gate == "closing"
    # closing -> closed when no follow-up pending
    result = bridge.announce_settled(gate)
    assert result["transition"] == "closed"
    assert gate.gate == "closed"
    # reopen: closing + follow-up pending -> accepting
    gate2 = bridge.PiGateState()
    bridge.announce_settled(gate2)
    gate2._follow_up_pending = True
    assert bridge.announce_settled(gate2)["transition"] == "reopen_accepting"
    assert gate2.gate == "accepting"


# ── pi.sh adapter shell ───────────────────────────────────────────────────────

def _source_adapter(script: str, env: dict[str, str]):
    return subprocess.run(
        ["bash", "-c", f'source "{ADAPTER}" && {script}'],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
    )


def _pi_prepare_config(tmp_path: Path) -> Path:
    env = {
        "CODIFY_RUNTIME_DIR": str(tmp_path),
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_RUN_UID": "1000",
        "CODIFY_RUN_GID": "1000",
        "HOME": str(tmp_path / "home"),
        "ANTHROPIC_MODEL": "deepseek-v4-flash",
        "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
        "ANTHROPIC_API_KEY": "fake-key",
    }
    result = _source_adapter("pi_adapter_prepare_config", env)
    assert result.returncode == 0, result.stderr
    return tmp_path / "home"


def test_pi_config_maps_snapshot_endpoint_to_models_json(tmp_path):
    home = _pi_prepare_config(tmp_path)
    # pi 0.84.2 reads custom providers only from ~/.pi/agent/models.json (the
    # CLI subprocess HOME), not from PI_HOME.
    models_file = home / ".pi/agent/models.json"
    assert models_file.exists()
    content = json.loads(models_file.read_text(encoding="utf-8"))
    provider = content["providers"]["codify"]
    # Snapshot model/base/credential win; pi only parses the array form.
    assert provider["baseUrl"] == "https://api.deepseek.com/anthropic"
    assert provider["api"] == "anthropic-messages"
    assert provider["apiKey"] == "fake-key"
    assert provider["models"][0]["id"] == "deepseek-v4-flash"
    assert provider["models"][0]["name"] == "deepseek-v4-flash"
    assert provider["models"][0]["contextWindow"] == 128000


@pytest.mark.parametrize(
    ("endpoint_url", "expected_base_url"),
    [
        ("https://openrouter.ai/api/v1", "https://openrouter.ai/api"),
        ("https://openrouter.ai/api/v1/", "https://openrouter.ai/api"),
        ("https://api.deepseek.com/anthropic", "https://api.deepseek.com/anthropic"),
    ],
)
def test_pi_anthropic_config_normalizes_sdk_base_url(endpoint_url, expected_base_url, tmp_path):
    env = {
        "CODIFY_RUNTIME_DIR": str(tmp_path),
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_RUN_UID": "1000",
        "CODIFY_RUN_GID": "1000",
        "HOME": str(tmp_path / "home"),
        "ANTHROPIC_MODEL": "minimax/minimax-m3:free",
        "ANTHROPIC_BASE_URL": endpoint_url,
        "ANTHROPIC_API_KEY": "fake-key",
    }
    result = _source_adapter("pi_adapter_prepare_config", env)
    assert result.returncode == 0, result.stderr
    provider = json.loads(
        (tmp_path / "home/.pi/agent/models.json").read_text(encoding="utf-8")
    )["providers"]["codify"]
    assert provider["api"] == "anthropic-messages"
    assert provider["baseUrl"] == expected_base_url


@pytest.mark.parametrize(
    ("protocol", "model", "endpoint_url", "api_key", "expected_api"),
    [
        (
            "openai_responses",
            "responses-model",
            "https://openai.example/v1",
            "responses-key",
            "openai-responses",
        ),
        (
            "openai_chat_completions",
            "chat-model",
            "https://chat.example/v1",
            "chat-key",
            "openai-completions",
        ),
    ],
)
def test_pi_config_maps_openai_protocols_to_native_apis(
    tmp_path, protocol, model, endpoint_url, api_key, expected_api
):
    env = {
        "CODIFY_RUNTIME_DIR": str(tmp_path),
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_RUN_UID": "1000",
        "CODIFY_RUN_GID": "1000",
        "HOME": str(tmp_path / "home"),
        "CODIFY_MODEL_PROTOCOL": protocol,
        "ANTHROPIC_MODEL": "wrong-anthropic-model",
        "ANTHROPIC_BASE_URL": "https://wrong-anthropic.example",
        "ANTHROPIC_API_KEY": "wrong-anthropic-key",
        "OPENAI_MODEL": model,
        "OPENAI_BASE_URL": endpoint_url,
        "OPENAI_API_KEY": api_key,
    }
    result = _source_adapter("pi_adapter_prepare_config", env)
    assert result.returncode == 0, result.stderr
    provider = json.loads(
        (tmp_path / "home/.pi/agent/models.json").read_text(encoding="utf-8")
    )["providers"]["codify"]
    assert provider["api"] == expected_api
    assert provider["baseUrl"] == endpoint_url
    assert provider["apiKey"] == api_key
    assert provider["models"][0]["id"] == model


def test_pi_prepare_config_exports_transport_env_defaults(tmp_path):
    # P2: prepare_config default-exports the Pi transport/model identity
    # (rpc_stdio / pi-rpc / its supported protocol) when the runner did not inject it,
    # so result_builder.v2_harness_block forms the correct V2 envelope.
    env = {
        "CODIFY_RUNTIME_DIR": str(tmp_path),
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_RUN_UID": "1000",
        "CODIFY_RUN_GID": "1000",
    }
    result = _source_adapter(
        "unset CODIFY_HARNESS_CONTROL_TRANSPORT_KIND "
        "CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL CODIFY_HARNESS_MODEL_PROTOCOLS || true; "
        "pi_adapter_prepare_config && printf '%s|%s|%s' "
        '"$CODIFY_HARNESS_CONTROL_TRANSPORT_KIND" '
        '"$CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL" '
        '"$CODIFY_HARNESS_MODEL_PROTOCOLS"',
        env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        "rpc_stdio|pi-rpc|anthropic_messages,openai_responses,openai_chat_completions"
    )


def test_pi_materializes_skills_to_pi_native_dir_not_claude(tmp_path):
    skills_dir = tmp_path / "task-skills"
    (skills_dir / "deploy-app").mkdir(parents=True)
    (skills_dir / "deploy-app" / "SKILL.md").write_text(
        "---\nname: deploy-app\ndescription: deploy\n---\nbody\n", encoding="utf-8"
    )
    env = {
        "CODIFY_RUNTIME_DIR": str(tmp_path),
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_RUN_UID": "1000",
        "CODIFY_RUN_GID": "1000",
        "PI_HOME": str(tmp_path / "pi-home"),
        "CODIFY_TASK_SKILLS_DIR": str(skills_dir),
    }
    result = _source_adapter("pi_adapter_materialize_skills", env)
    assert result.returncode == 0, result.stderr
    # Materialized under Pi's native skills dir, NOT a .claude intermediate.
    assert (tmp_path / "pi-home/skills/deploy-app/SKILL.md").exists()
    assert not (tmp_path / "pi-home/.claude").exists()


def test_pi_verify_runtime_enforces_pinned_cli_version(tmp_path):
    cli = tmp_path / "pi"
    cli.write_text("#!/bin/sh\necho pi 0.84.2\n", encoding="utf-8")
    cli.chmod(0o755)
    env = {
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_PI_BIN": str(cli),
        "CODIFY_HARNESS_CLI_BIN": str(cli),
        "ENTRYPOINT_LIB_DIR": str(REPO_ROOT / "deploy/worker-entrypoint"),
    }
    ok = _source_adapter("pi_adapter_verify_runtime", env)
    assert ok.returncode == 0, ok.stderr
    # Out-of-baseline version is advisory: a sanitized warning, execution
    # continues (§11.2 Compatibility policy).
    cli2 = tmp_path / "pi-bad"
    cli2.write_text("#!/bin/sh\necho pi 9.9.9\n", encoding="utf-8")
    cli2.chmod(0o755)
    env2 = {**env, "CODIFY_PI_BIN": str(cli2), "CODIFY_HARNESS_CLI_BIN": str(cli2)}
    bad = _source_adapter("pi_adapter_verify_runtime", env2)
    assert bad.returncode == 0, bad.stderr
    assert "WARNING" in bad.stderr
    assert "advisory" in bad.stderr


def test_pi_continuation_raw_stream_maps_model_resolved(tmp_path):
    # Real pi 0.84.2 continuation wire (docs/harness-probes/v2/pi/continuation.raw.jsonl):
    # the runner sends ``new_session`` with ``parentSessionId`` to continue a task;
    # pi accepts it (success:true) and the following get_state returns the new child
    # session, from which the translator captures model + session_id. The new_session
    # ACK itself carries no canonical event and a handshake-only stream (no model
    # turn) emits no harness terminal at EOF.
    runtime_dir = tmp_path / "continuation"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started", {"runtime_bundle_digest": "d" * 64})
    _translate(runtime_dir, _probe_records("continuation"))
    events = [e for e in _events(runtime_dir) if e["type"] != "run.started"]
    for event in events:
        normalized = validate_event_v2(event)
        assert normalized["schema"] == CANONICAL_EVENT_SCHEMA_V2
    by_type = [e["type"] for e in events]
    assert "model.resolved" in by_type
    resolved = next(e for e in events if e["type"] == "model.resolved")
    assert resolved["payload"]["model"] == "deepseek-v4-flash"
    assert resolved["payload"]["session_id"] == "<SESSION_UUID>"
    assert "harness.completed" not in by_type


def test_pi_real_session_id_is_retained_for_result_after_sanitization(tmp_path):
    runtime_dir = tmp_path / "real-session"
    runtime_dir.mkdir()
    real_session_id = "123e4567-e89b-12d3-a456-426614174000"
    records = _probe_records("success")
    records[0]["data"]["sessionId"] = real_session_id
    records[0]["data"]["sessionFile"] = f"/root/.pi/sessions/session_{real_session_id}.jsonl"

    _emit(runtime_dir, "run.started")
    _translate(runtime_dir, records)

    result = json.loads((runtime_dir / "harness-result.json").read_text(encoding="utf-8"))
    assert result["session_id"] == real_session_id
    completed = next(event for event in _events(runtime_dir) if event["type"] == "harness.completed")
    assert completed["payload"]["session_id"] == real_session_id
    raw = (runtime_dir / "harness-events/pi.jsonl").read_text(encoding="utf-8")
    assert real_session_id not in raw


def test_pi_runner_handshake_uses_new_session_not_resume():
    # Finding 1 regression guard: real pi 0.84.2 rejects the old handshake frame
    # ``{"type":"resume","sessionId":...}`` (``Unknown command: resume``); the pi
    # runner must request sessions via ``new_session`` (+ optional
    # ``parentSessionId`` for a continued task), then keep get_state -> prompt.
    owner = (REPO_ROOT / "deploy/worker-entrypoint/harness/adapters/pi_owner.py").read_text(encoding="utf-8")
    assert '"type":"resume"' not in owner
    # Continuations reference the parent; first sessions use the bare frame.
    assert "parentSessionId" in owner
    assert '("new_session", None' in owner
    # get_state / prompt frame sequence is preserved by the single owner.
    assert '("get_state", None' in owner
    assert '("prompt", self.prompt' in owner
    assert owner.index('("get_state", None') < owner.index('("prompt", self.prompt')


def test_pi_runner_pins_codify_provider_and_snapshot_model():
    # Defect A guard (integration test 04:59): pi 0.84.2 launched as
    # ``pi --mode rpc`` without a provider/model defaults to its built-in
    # ``anthropic`` provider and sends the relay key to api.anthropic.com (401).
    # The runner must pin the adapter's ``codify`` provider and the Snapshot
    # model so the key goes to the relay endpoint carved into
    # $HOME/.pi/agent/models.json.
    runner = (REPO_ROOT / "deploy/worker-entrypoint/legacy/pi-run.sh").read_text(encoding="utf-8")
    assert "--mode rpc --provider codify" in runner
    assert "--model \"${PI_MODEL_RPC}\"" in runner
    # The model resolves from the protocol-specific Snapshot env selected by
    # pi.sh prepare_config; a stale harness-specific variable is ignored.
    assert 'PI_MODEL_RPC="${ANTHROPIC_MODEL:-}"' in runner
    assert 'openai_responses|openai_chat_completions' in runner
    assert 'PI_MODEL_RPC="${OPENAI_MODEL:-}"' in runner
    # Provider pin lives in the base command, before the CODIFY_PI_RUN_AS wrapper.
    base = runner[: runner.index('if [ -n "${CODIFY_PI_RUN_AS:-}" ]')]
    assert "--provider codify" in base
    assert "--mode rpc --provider codify" in base


def test_pi_runner_terminates_on_agent_settled_before_ack_continue():
    # Defect B guard: a successful turn ends with ``agent_settled``; the runner
    # must close the request FIFO write end (kill $req_writer) so pi sees stdin
    # EOF, exits, and STREAM_FIFO reaches EOF for the translator to persist the
    # V2 result. Without it the runner hangs until TASK_TIMEOUT. The kill must
    # be evaluated before the ``ack_state`` continue so it also fires on the
    # already-in-progress turn stream.
    owner = (REPO_ROOT / "deploy/worker-entrypoint/harness/adapters/pi_owner.py").read_text(encoding="utf-8")
    assert 'record.get("type") == "agent_settled"' in owner
    assert "self.process.stdin.close()" in owner


def test_pi_owner_accepts_large_jsonl_records(tmp_path):
    """Pi RPC records may exceed asyncio's default 64 KiB line limit."""
    import asyncio
    import importlib
    import sys

    adapters_dir = str(HARNESS_DIR / "adapters")
    if adapters_dir not in sys.path:
        sys.path.insert(0, adapters_dir)
    pi_owner = importlib.import_module("pi_owner")

    stub = tmp_path / "pi-large-record-stub.py"
    stub.write_text(
        "import json\n"
        "print(json.dumps({'type': 'oversized', 'payload': 'x' * 100000}), flush=True)\n"
        "print(json.dumps({'type': 'agent_settled'}), flush=True)\n",
        encoding="utf-8",
    )
    runtime_dir = tmp_path / "runtime"
    owner = pi_owner.PiOwner(
        [sys.executable, str(stub)], runtime_dir, tmp_path / "pi.sock"
    )

    async def run_owner():
        await owner.start()
        await asyncio.wait_for(owner.settled.wait(), timeout=5)
        assert owner.process is not None
        await asyncio.wait_for(owner.process.wait(), timeout=5)
        await asyncio.sleep(0)
        assert owner.failure is None
        await owner.finish()

    asyncio.run(run_owner())


STUB_PI_TMPL = r'''#!/usr/bin/env python3
import json, sys

TURN = {turn!r}

def emit(obj):
    print(json.dumps(obj, separators=(",", ":")), flush=True)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except ValueError:
        continue
    typ = req.get("type")
    rid = req.get("id", 1)
    if typ == "new_session":
        emit({{"id": rid, "type": "response", "command": "new_session", "success": True, "data": {{"cancelled": False}}}})
    elif typ == "get_state":
        emit({{"id": rid, "type": "response", "command": "get_state", "success": True, "data": {{"model": {{"id": "ox-alpha-free", "api": "anthropic-messages", "provider": "codify"}}, "thinkingLevel": "medium", "isStreaming": False, "steeringMode": "one-at-a-time", "followUpMode": "one-at-a-time", "sessionId": "pi-sess-test", "messageCount": 0, "pendingMessageCount": 0}}}})
    elif typ == "prompt":
        emit({{"id": rid, "type": "response", "command": "prompt", "success": True}})
        for event in TURN:
            emit(event)
'''


def test_pi_runner_terminates_and_persists_result_after_settled(tmp_path):
    # Defect B end-to-end: drive the real pi-run.sh against a stub ``pi --mode
    # rpc`` that answers the handshake and replays a completed turn ending in
    # agent_settled. On agent_settled the runner must close the request FIFO
    # write end, which gives the stub stdin EOF so it exits; STREAM_FIFO then
    # reaches EOF and the translator persists a completed V2 result. Without the
    # fix the runner hangs until the test timeout (was 0/22 -> TASK_TIMEOUT).
    runtime_dir = tmp_path / "run"
    runtime_dir.mkdir()
    prompt = runtime_dir / "prompt.txt"
    prompt.write_text("Reply with the single word PROBE_OK.\n", encoding="utf-8")
    turn = _probe_records("success")[2:]
    stub = tmp_path / "pi-stub"
    stub.write_text(STUB_PI_TMPL.format(turn=turn), encoding="utf-8")
    stub.chmod(0o755)
    # The harness runner (runner.sh) emits run.started before handing control to
    # the adapter runner; pi-run.sh only translates the stream, so seed the first
    # canonical event here to match the real execution order.
    _emit(runtime_dir, "run.started", {"runtime_bundle_digest": "d" * 64})
    env = {
        **_environment(runtime_dir),
        "CODIFY_PI_BIN": str(stub),
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "PROMPT_FILE": str(prompt),
            "ANTHROPIC_MODEL": "ox-alpha-free",
            "HOME": str(tmp_path),
            "CODIFY_PI_CONTROL_SOCKET": str(REPO_ROOT / f".pi-test-{os.getpid()}.sock"),
            "CODIFY_PI_OWNER_NO_SOCKET": "1",
    }
    proc = subprocess.run(
        ["bash", str(REPO_ROOT / "deploy/worker-entrypoint/legacy/pi-run.sh")],
        env=env,
        capture_output=True,
        text=True,
            timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result_file = runtime_dir / "harness-result.json"
    assert result_file.exists()
    result = json.loads(result_file.read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    assert result["success"] is True
    # The canonical audit trail surfaced the settled signal for the projector.
    by_type = [e["type"] for e in _events(runtime_dir)]
    assert "agent_settled" in by_type


# ── Full raw-type coverage: every Pi 0.84.2 stream record maps to a
# canonical event (or an explicit no-op), never to unknown_raw_event. ────────

class _FakeWriter:
    """Capture canonical events without a real writer subprocess."""

    def __init__(self):
        self.events = []

    def __call__(self, event_type, payload, raw_line):
        self.events.append((event_type, payload, raw_line))


def _reset_pi_state():
    import pi_events

    pi_events._STATE = {
        "model_resolved": False,
        "model_id": None,
        "session_id": None,
        "aborted": False,
        "usage": {},
        "terminal": None,
        "terminal_line": None,
        "terminal_failure": None,
        "assistant_final_line": None,
        "agent_end_success_line": None,
        "agent_settled_line": None,
        "last_raw_line": 0,
        "text_parts": [],
        "thinking": [],
        "message_completed_emitted": False,
    }


def test_pi_tool_start_maps_to_tool_started_with_sanitized_input():
    """tool_execution_start -> tool.started carrying tool_id/name/input; a
    bash command is sanitized (URLs/tokens redacted), read/write keep path."""
    import pi_events

    _reset_pi_state()
    writer = _FakeWriter()
    pi_events._emit = writer
    pi_events.translate(
        {
            "type": "tool_execution_start",
            "toolCallId": "<TOOL_ID:abc123>",
            "toolName": "write",
            "args": {"path": "/workspace/docs/pi.md", "content": "x"},
        },
        7,
    )
    started = [p for t, p, _ in writer.events if t == "tool.started"]
    assert len(started) == 1
    assert started[0]["tool_id"] == "<TOOL_ID:abc123>"
    assert started[0]["name"] == "Write"
    assert started[0]["input"] == {"content": "x", "file_path": "/workspace/docs/pi.md"}

    _reset_pi_state()
    writer = _FakeWriter()
    pi_events._emit = writer
    pi_events.translate(
        {
            "type": "tool_execution_start",
            "toolCallId": "<TOOL_ID:def456>",
            "toolName": "bash",
            "args": {
                "command": "curl -H 'PRIVATE-TOKEN: glpat-abcdef1234567890' http://192.168.50.129:8080/api/v4/x"
            },
        },
        8,
    )
    started = [p for t, p, _ in writer.events if t == "tool.started"]
    assert len(started) == 1
    assert "glpat-abcdef1234567890" not in json.dumps(started[0])
    assert "192.168.50.129" not in json.dumps(started[0])


def test_pi_tool_end_maps_to_tool_completed_with_truncated_output():
    """tool_execution_end -> tool.completed with sanitized output and error."""
    import pi_events

    _reset_pi_state()
    writer = _FakeWriter()
    pi_events._emit = writer
    pi_events.translate(
        {
            "type": "tool_execution_end",
            "toolCallId": "<TOOL_ID:abc123>",
            "toolName": "write",
            "result": {
                "content": [{"type": "text", "text": "Successfully wrote 52 bytes to /workspace/docs/pi.md http://192.168.50.129:8080/x"}]
            },
            "isError": False,
        },
        9,
    )
    completed = [p for t, p, _ in writer.events if t == "tool.completed"]
    assert len(completed) == 1
    assert "192.168.50.129" not in json.dumps(completed[0])
    assert completed[0]["error"] is False
    assert completed[0]["name"] == "Write"


def test_pi_tool_update_is_explicit_noop():
    """tool_execution_update emits nothing (progress only), never unknown."""
    import pi_events

    _reset_pi_state()
    writer = _FakeWriter()
    pi_events._emit = writer
    pi_events.translate(
        {"type": "tool_execution_update", "toolCallId": "<TOOL_ID:abc123>", "toolName": "bash"},
        10,
    )
    assert writer.events == []


def test_pi_nested_toolcall_fallback_is_deduplicated_by_execution_events():
    import pi_events

    _reset_pi_state()
    writer = _FakeWriter()
    pi_events._emit = writer
    pi_events.translate(
        {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "toolcall_end",
                "toolCall": {
                    "type": "toolCall",
                    "id": "call-nested",
                    "name": "bash",
                    "arguments": {"command": "pwd"},
                },
            },
        },
        10,
    )
    pi_events.translate(
        {
            "type": "tool_execution_start",
            "toolCallId": "call-nested",
            "toolName": "bash",
            "args": {"command": "pwd"},
        },
        11,
    )
    pi_events.translate(
        {
            "type": "tool_execution_end",
            "toolCallId": "call-nested",
            "toolName": "bash",
            "result": {"content": [{"type": "text", "text": "/workspace"}]},
            "isError": False,
        },
        12,
    )
    started = [p for t, p, _ in writer.events if t == "tool.started"]
    completed = [p for t, p, _ in writer.events if t == "tool.completed"]
    assert len(started) == 1
    assert len(completed) == 1
    assert started[0]["name"] == "Bash"
    assert started[0]["input"] == {"command": "pwd"}


def test_pi_nested_toolcall_deltas_are_buffered_and_explicitly_diagnosed():
    _load_bridge()
    import pi_events

    _reset_pi_state()
    writer = _FakeWriter()
    pi_events._emit = writer
    pi_events.translate(
        {
            "type": "message_update",
            "assistantMessageEvent": {"type": "toolcall_start", "contentIndex": 0},
        },
        10,
    )
    pi_events.translate(
        {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "toolcall_delta",
                "contentIndex": 0,
                "delta": '{"command":"pwd"}',
            },
        },
        11,
    )
    pi_events.translate(
        {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "toolcall_end",
                "contentIndex": 0,
                "toolCall": {"id": "call-buffered", "name": "bash"},
            },
        },
        12,
    )
    pi_events.translate(
        {
            "type": "tool_execution_end",
            "toolCallId": "call-buffered",
            "toolName": "bash",
            "result": {"content": [{"type": "text", "text": "ok"}]},
            "isError": False,
        },
        13,
    )

    started = [p for t, p, _ in writer.events if t == "tool.started"]
    completed = [p for t, p, _ in writer.events if t == "tool.completed"]
    assert started[0]["input"] == {"command": "pwd"}
    assert completed[0]["error"] is False
    codes = [p.get("code") for t, p, _ in writer.events if t == "diagnostic"]
    assert codes[:2] == ["toolcall_started", "toolcall_delta"]
    assert "unknown_raw_event" not in codes


def test_pi_nested_toolcall_start_id_does_not_break_content_index_deltas():
    _load_bridge()
    import pi_events

    _reset_pi_state()
    writer = _FakeWriter()
    pi_events._emit = writer
    pi_events.translate(
        {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "toolcall_start",
                "contentIndex": 0,
                "toolCall": {"id": "call-indexed", "name": "bash"},
            },
        },
        20,
    )
    pi_events.translate(
        {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "toolcall_delta",
                "contentIndex": 0,
                "delta": '{"command":"pwd"}',
            },
        },
        21,
    )
    pi_events.translate(
        {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "toolcall_end",
                "contentIndex": 0,
                "toolCall": {"id": "call-indexed", "name": "bash"},
            },
        },
        22,
    )

    started = [p for t, p, _ in writer.events if t == "tool.started"]
    assert started[0]["input"] == {"command": "pwd"}


def test_pi_tool_end_with_error_flags_error():
    import pi_events

    _reset_pi_state()
    writer = _FakeWriter()
    pi_events._emit = writer
    pi_events.translate(
        {
            "type": "tool_execution_end",
            "toolCallId": "<TOOL_ID:e1>",
            "toolName": "bash",
            "result": {"content": [{"type": "text", "text": "permission denied"}]},
            "isError": True,
            "errorMessage": "permission denied",
            "exitCode": 126,
        },
        11,
    )
    completed = [p for t, p, _ in writer.events if t == "tool.completed"]
    assert completed[0]["error"] is True
    assert completed[0]["error_message"] == "permission denied"
    assert completed[0]["exit_code"] == 126


def test_pi_compaction_start_is_explicit_diagnostic():
    import pi_events

    _reset_pi_state()
    writer = _FakeWriter()
    pi_events._emit = writer
    pi_events.translate({"type": "compaction_start", "reason": "threshold"}, 9)
    codes = [p.get("code") for t, p, _ in writer.events if t == "diagnostic"]
    assert codes == ["compaction_started"], codes


def test_pi_compaction_end_maps_to_context_compacted():
    import pi_events

    _reset_pi_state()
    writer = _FakeWriter()
    pi_events._emit = writer
    pi_events.translate(
        {
            "type": "compaction_end",
            "reason": "threshold",
            "result": {
                "tokensBefore": 150000,
                "estimatedTokensAfter": 32000,
                "usage": {"input": 32000, "output": 1200, "totalTokens": 33200},
            },
            "aborted": False,
            "willRetry": False,
        },
        10,
    )
    compacted = [p for t, p, _ in writer.events if t == "context.compacted"]
    assert compacted == [
        {
            "session_id": None,
            "reason": "threshold",
            "aborted": False,
            "will_retry": False,
            "tokens_before": 150000,
            "estimated_tokens_after": 32000,
        }
    ]


def test_pi_retry_events_preserve_the_stream_until_the_final_settled_turn(tmp_path):
    runtime_dir = tmp_path / "retry"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    _translate(
        runtime_dir,
        [
            _get_state_record(),
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [],
                    "stopReason": "error",
                    "errorMessage": "503 temporary overload",
                },
            },
            {
                "type": "agent_end",
                "messages": [],
                "willRetry": True,
                "errorMessage": "503 temporary overload",
            },
            {
                "type": "auto_retry_start",
                "attempt": 1,
                "maxAttempts": 3,
                "delayMs": 2000,
                "errorMessage": "503 temporary overload",
            },
            {"type": "auto_retry_end", "success": True, "attempt": 2},
            {"type": "message_update", "assistantMessageEvent": {"type": "text_start"}},
            {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "recovered"}},
            {"type": "message_update", "assistantMessageEvent": {"type": "text_end", "content": "recovered"}},
            {"type": "message_end", "message": {"role": "assistant", "stopReason": "stop", "content": [{"type": "text", "text": "recovered"}]}},
            {"type": "agent_end", "messages": [], "willRetry": False},
            {"type": "agent_settled"},
        ],
    )
    events = _events(runtime_dir)
    types = [event["type"] for event in events]
    assert types.count("provider.retry") == 1
    assert any(
        event["type"] == "diagnostic" and event["payload"].get("code") == "provider_retry_finished"
        for event in events
    )
    assert "harness.completed" in types
    assert "harness.failed" not in types
    raw = (runtime_dir / "harness-events/pi.jsonl").read_text(encoding="utf-8")
    assert '"type":"auto_retry_start"' in raw


def test_pi_documented_special_events_do_not_become_unknown_raw_events():
    import pi_events

    _reset_pi_state()
    writer = _FakeWriter()
    pi_events._emit = writer
    records = [
        {"type": "auto_retry_start", "attempt": 1, "maxAttempts": 3, "delayMs": 100, "errorMessage": "429 retry"},
        {"type": "auto_retry_end", "success": True, "attempt": 2},
        {"type": "summarization_retry_scheduled", "attempt": 1, "maxAttempts": 3, "delayMs": 100, "errorMessage": "temporary"},
        {"type": "summarization_retry_attempt_start", "source": "compaction", "reason": "threshold"},
        {"type": "summarization_retry_finished"},
        {"type": "extension_error", "event": "tool_call", "error": "extension failed"},
        {"type": "bash_execution_update", "id": "req-1", "delta": "partial output"},
    ]
    for line, record in enumerate(records, start=1):
        pi_events.translate(record, line)
    unknown = [
        payload for event_type, payload, _ in writer.events
        if event_type == "diagnostic" and payload.get("code") == "unknown_raw_event"
    ]
    assert unknown == []
    assert [event_type for event_type, _, _ in writer.events].count("provider.retry") == 2


def test_pi_thinking_end_is_a_completed_reasoning_summary():
    import pi_events

    _reset_pi_state()
    writer = _FakeWriter()
    pi_events._emit = writer
    pi_events.translate(
        {"type": "message_update", "assistantMessageEvent": {"type": "thinking_start"}},
        1,
    )
    pi_events.translate(
        {"type": "message_update", "assistantMessageEvent": {"type": "thinking_delta", "delta": "plan"}},
        2,
    )
    pi_events.translate(
        {"type": "message_update", "assistantMessageEvent": {"type": "thinking_end"}},
        3,
    )
    summaries = [p for t, p, _ in writer.events if t == "reasoning_summary.completed"]
    assert summaries == [{"text": "plan", "client": "pi"}]


def test_pi_unknown_raw_type_emits_unknown_raw_event():
    import pi_events

    _reset_pi_state()
    writer = _FakeWriter()
    pi_events._emit = writer
    pi_events.translate({"type": "futuristic_new_event"}, 11)
    codes = [p.get("code") for t, p, _ in writer.events if t == "diagnostic"]
    assert codes == ["unknown_raw_event"], codes


def test_pi_rejected_native_ack_maps_control_command_rejected():
    import pi_events

    _reset_pi_state()
    writer = _FakeWriter()
    pi_events._emit = writer
    pi_events.translate(
        {
            "type": "response",
            "command": "follow_up",
            "success": False,
            "__command_ack": {
                "command_id": "cmd-rejected-1",
                "payload_digest": "d1",
                "sequence_no": 3,
                "rejection_code": "delivery_outcome_unknown",
            },
        },
        13,
    )
    delivered = [p for t, p, _ in writer.events if t == "control.command.rejected"]
    assert len(delivered) == 1
    assert delivered[0]["command_id"] == "cmd-rejected-1"
    assert delivered[0]["sequence_no"] == 3


def test_pi_native_ack_without_command_id_is_diagnostic_not_delivered():
    import pi_events

    _reset_pi_state()
    writer = _FakeWriter()
    pi_events._emit = writer
    pi_events.translate(
        {"type": "response", "command": "steer", "success": True},
        15,
    )
    types = [t for t, _, _ in writer.events]
    assert "control.command.delivered" not in types
    assert any(
        t == "diagnostic" and p.get("code") == "native_ack_without_command_id"
        for t, p, _ in writer.events
    )


def test_pi_reopen_marker_emits_follow_up_turn_started():
    import pi_events

    _reset_pi_state()
    writer = _FakeWriter()
    pi_events._emit = writer
    pi_events.translate(
        {
            "type": "turn_start",
            "__pi_reopen_after": {"command_id": "cmd-9", "native_id": "n9"},
        },
        17,
    )
    codes = [p.get("code") for t, p, _ in writer.events if t == "diagnostic"]
    assert codes == ["pi_follow_up_turn_started"], codes


def test_pi_incomplete_terminal_emits_harness_failed(tmp_path):
    import pi_events

    os.environ["CODIFY_HARNESS_RESULT_FILE"] = str(tmp_path / "harness-result.json")
    _reset_pi_state()
    writer = _FakeWriter()
    pi_events._emit = writer
    # Stream ends with only text, no agent_end/agent_settled.
    pi_events.translate(
        {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "hi"}},
        1,
    )
    pi_events._emit_terminal_at_eof()
    types = [t for t, _, _ in writer.events]
    assert "harness.failed" in types
    assert pi_events._STATE["terminal"] == "failed"
    del os.environ["CODIFY_HARNESS_RESULT_FILE"]
