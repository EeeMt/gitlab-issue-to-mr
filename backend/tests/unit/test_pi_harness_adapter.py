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
    "CODIFY_HARNESS_MODEL_PROTOCOLS": "anthropic_messages,openai_responses,openai_chat_completions",
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
    b._send_request = lambda _cmd, _p: {  # type: ignore[method-assign]
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
        "PI_HOME": str(tmp_path / "pi-home"),
        "PI_MODEL": "deepseek-v4-flash",
        "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
        "ANTHROPIC_API_KEY": "sk-snapshot-secret",
    }
    result = _source_adapter("pi_adapter_prepare_config", env)
    assert result.returncode == 0, result.stderr
    return tmp_path / "pi-home"


def test_pi_config_maps_snapshot_endpoint_to_models_json(tmp_path):
    pi_home = _pi_prepare_config(tmp_path)
    models_file = pi_home / "agent/models.json"
    assert models_file.exists()
    content = json.loads(models_file.read_text(encoding="utf-8"))
    # Snapshot model/base/credential win; Pi native config cannot override.
    assert content["models"]["deepseek-v4-flash"]["baseUrl"] == "https://api.deepseek.com/anthropic"
    assert content["providers"]["codify"]["apiKey"] == "sk-snapshot-secret"


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
