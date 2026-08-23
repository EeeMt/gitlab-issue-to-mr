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
    _emit(runtime_dir, "run.started")
    _translate(
        runtime_dir,
        [
            _get_state_record(),
            {"type": "queue_update", "steering": ["use sk-ant-secret1234567890"], "followUp": []},
        ],
    )
    queue_events = [e for e in _events(runtime_dir) if e["type"] == "control.queue.updated"]
    assert queue_events
    text = json.dumps(queue_events[0]["payload"], ensure_ascii=False)
    assert "sk-ant-secret1234567890" not in text
    # raw archive is sanitized too (translator sanitizes each line)
    raw = (runtime_dir / "harness-events/pi.jsonl").read_text(encoding="utf-8")
    assert "sk-ant-secret1234567890" not in raw


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
        "PI_MODEL": "deepseek-v4-flash",
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


def test_pi_config_rejects_openai_chat_completions(tmp_path):
    env = {
        "CODIFY_RUNTIME_DIR": str(tmp_path),
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_RUN_UID": "1000",
        "CODIFY_RUN_GID": "1000",
        "HOME": str(tmp_path / "home"),
        "CODIFY_MODEL_PROTOCOL": "openai_chat_completions",
    }
    result = _source_adapter("pi_adapter_prepare_config", env)
    assert result.returncode != 0
    assert "does not support model protocol" in result.stderr


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
        "rpc_stdio|pi-rpc|anthropic_messages"
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
        "ENTRYPOINT_LIB_DIR": str(REPO_ROOT / "deploy/worker-entrypoint"),
    }
    ok = _source_adapter("pi_adapter_verify_runtime", env)
    assert ok.returncode == 0, ok.stderr
    # Out-of-pin version must fail closed (manifest pins 0.84.2).
    cli2 = tmp_path / "pi-bad"
    cli2.write_text("#!/bin/sh\necho pi 9.9.9\n", encoding="utf-8")
    cli2.chmod(0o755)
    env2 = {**env, "CODIFY_PI_BIN": str(cli2)}
    bad = _source_adapter("pi_adapter_verify_runtime", env2)
    assert bad.returncode != 0
    assert "version mismatch" in bad.stderr


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


def test_pi_runner_handshake_uses_new_session_not_resume():
    # Finding 1 regression guard: real pi 0.84.2 rejects the old handshake frame
    # ``{"type":"resume","sessionId":...}`` (``Unknown command: resume``); the pi
    # runner must request sessions via ``new_session`` (+ optional
    # ``parentSessionId`` for a continued task), then keep get_state -> prompt.
    runner = (REPO_ROOT / "deploy/worker-entrypoint/legacy/pi-run.sh").read_text(encoding="utf-8")
    assert '"type":"resume"' not in runner
    # Continuations reference the parent; first sessions use the bare frame.
    assert "parentSessionId" in runner
    assert '{id:1, type:"new_session", parentSessionId:$parent}' in runner
    assert '{"id":1,"type":"new_session"}' in runner
    # get_state / prompt frame sequence is preserved after the handshake.
    assert '{"id":2,"type":"get_state"}' in runner
    assert '{"id":3,"type":"prompt"' in runner
    assert runner.index('"type":"get_state"') < runner.index('"type":"prompt"')


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
    # The model resolves from the same adapter env chain as pi.sh prepare_config.
    assert 'PI_MODEL_RPC="${PI_MODEL:-${ANTHROPIC_MODEL:-${OPENAI_MODEL:-}}}"' in runner
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
    runner = (REPO_ROOT / "deploy/worker-entrypoint/legacy/pi-run.sh").read_text(encoding="utf-8")
    assert '.type == "agent_settled"' in runner
    assert 'kill "${req_writer}"' in runner
    assert runner.index('.type == "agent_settled"') < runner.index(
        'if [ "${ack_state}" -eq 1 ]'
    )


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
