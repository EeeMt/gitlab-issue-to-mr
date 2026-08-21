"""Tests for the OpenCode V2 adapter: event translator, control bridge, adapter shell.

The OpenCode translator is driven by the Phase-0 probe framing (docs/harness-probes/v2/opencode/)
and maps OpenCode's SSE ``{id, type, properties}`` records to canonical V2 events, using the
three-signal settled judgment (design §4): ``session.idle`` + final assistant message + no
error. First release has no command plane (steering=false/follow_up=false), so the bridge
deterministically rejects every command (schemas.md §3.3 / phase3 design §5).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from app.core.harness_protocol import CANONICAL_EVENT_SCHEMA_V2, replay_events, validate_event_v2

REPO_ROOT = Path(__file__).resolve().parents[3]
HARNESS_DIR = REPO_ROOT / "deploy/worker-entrypoint/harness"
TRANSLATOR = HARNESS_DIR / "adapters/opencode_events.py"
EVENT_WRITER = HARNESS_DIR / "events.py"
ADAPTER = HARNESS_DIR / "adapters/opencode.sh"
PROBE_ROOT = REPO_ROOT / "docs/harness-probes/v2/opencode"

V2_ENV = {
    "CODIFY_RUNTIME_CONTRACT_VERSION": "codify.worker.harness/v2",
    "CODIFY_EVENT_SCHEMA": CANONICAL_EVENT_SCHEMA_V2,
    "CODIFY_HARNESS_CONTROL_TRANSPORT_KIND": "server_http",
    "CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL": "opencode-server",
    "CODIFY_HARNESS_MODEL_PROTOCOLS": "anthropic_messages,openai_responses,openai_chat_completions",
}


def _environment(runtime_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        **V2_ENV,
        "CODIFY_RUNTIME_DIR": str(runtime_dir),
        "CODIFY_ATTEMPT_ID": "task-opencode-attempt-1",
        "TASK_ID": "9",
        "CODIFY_HARNESS_KEY": "opencode",
        "CODIFY_ADAPTER_VERSION": "2.0.0",
        "CODIFY_CLI_VERSION": "1.18.19",
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
    raw_file = runtime_dir / "harness-events/opencode.jsonl"
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


def _record(event_type: str, properties: dict | None = None) -> dict:
    return {"id": "ev-1", "type": event_type, "properties": properties or {}}


def _success_records() -> list[dict]:
    return [
        _record("server.connected"),
        _record("session.created", {"sessionID": "ses-oc-1", "info": {"id": "ses-oc-1", "version": "1.18.19"}}),
        _record("session.status", {"sessionID": "ses-oc-1", "status": {"type": "busy"}}),
        _record("message.part.delta", {"sessionID": "ses-oc-1", "messageID": "m1", "partID": "p1", "delta": "Hello "}),
        _record("message.part.delta", {"sessionID": "ses-oc-1", "messageID": "m1", "partID": "p1", "delta": "world"}),
        _record("message.part.updated", {"sessionID": "ses-oc-1", "part": {"type": "text", "text": "Hello world", "messageID": "m1"}}),
        _record("session.idle", {"sessionID": "ses-oc-1"}),
    ]


def test_opencode_stream_maps_sse_to_v2_canonical_events(tmp_path):
    runtime_dir = tmp_path / "success"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started", {"runtime_bundle_digest": "d" * 64})
    _translate(runtime_dir, _success_records())
    _emit(runtime_dir, "worker.finalization", {"exit_code": 0})
    _emit(runtime_dir, "run.completed", {"status": "completed", "success": True})

    translated = _events(runtime_dir)
    for event in translated:
        normalized = validate_event_v2(event)
        assert normalized["schema"] == CANONICAL_EVENT_SCHEMA_V2
    by_type = [event["type"] for event in translated]
    assert "message.delta" in by_type
    assert "message.completed" in by_type
    # agent_settled is surfaced for uniformity; single harness terminal.
    assert "agent_settled" in by_type
    assert by_type.count("harness.completed") == 1
    assert "harness.completed" in by_type

    replay = replay_events(translated)
    assert replay.harness_key == "opencode"
    assert replay.terminal_type == "run.completed"

    result = json.loads((runtime_dir / "harness-result.json").read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    assert result["success"] is True
    assert "Hello world" in result["result"]


def test_opencode_session_idle_converges_single_terminal(tmp_path):
    runtime_dir = tmp_path / "idle"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    _translate(runtime_dir, [_record("session.idle", {"sessionID": "ses-oc-1"})])
    _emit(runtime_dir, "worker.finalization", {"exit_code": 0})
    _emit(runtime_dir, "run.completed", {"status": "completed", "success": True})
    by_type = [e["type"] for e in _events(runtime_dir)]
    assert by_type.count("harness.completed") == 1


def test_opencode_abort_maps_to_cancelled_terminal(tmp_path):
    runtime_dir = tmp_path / "abort"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    _translate(
        runtime_dir,
        [
            _record("session.created", {"sessionID": "ses-oc-abort"}),
            _record("session.status", {"sessionID": "ses-oc-abort", "status": {"type": "busy"}}),
            _record("session.error", {"sessionID": "ses-oc-abort", "message": "The operation was aborted."}),
        ],
    )
    _emit(runtime_dir, "worker.finalization", {"exit_code": 0})
    _emit(runtime_dir, "run.failed", {"status": "failed", "success": False})
    types = [e["type"] for e in _events(runtime_dir)]
    assert "harness.failed" in types
    terminal = [e for e in _events(runtime_dir) if e["type"] == "harness.failed"][0]
    assert terminal["payload"]["failure"]["kind"] == "cancelled"
    result = json.loads((runtime_dir / "harness-result.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["success"] is False


def test_opencode_session_missing_classified_engine_error(tmp_path):
    runtime_dir = tmp_path / "session_missing"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    _translate(
        runtime_dir,
        [
            _record("session.error", {"sessionID": "missing", "message": "session_missing: session not found"}),
        ],
    )
    _emit(runtime_dir, "worker.finalization", {"exit_code": 1})
    _emit(runtime_dir, "run.failed", {"status": "failed", "success": False})
    terminal = [e for e in _events(runtime_dir) if e["type"] == "harness.failed"][0]
    assert terminal["payload"]["failure"]["kind"] == "engine_error"
    assert "session_missing" in terminal["payload"]["failure"]["message"]


def test_opencode_invalid_agent_command_classified_engine_error(tmp_path):
    runtime_dir = tmp_path / "invalid"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    _translate(
        runtime_dir,
        [
            _record("session.error", {"sessionID": "ses-oc", "message": "invalid_agent_command: agent 'x' not in allowlist"}),
        ],
    )
    _emit(runtime_dir, "worker.finalization", {"exit_code": 1})
    _emit(runtime_dir, "run.failed", {"status": "failed", "success": False})
    terminal = [e for e in _events(runtime_dir) if e["type"] == "harness.failed"][0]
    assert terminal["payload"]["failure"]["kind"] == "engine_error"
    assert "invalid_agent_command" in terminal["payload"]["failure"]["message"]


def test_opencode_translator_sanitizes_raw_archive(tmp_path):
    runtime_dir = tmp_path / "sanitize"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    # A secret in an SSE text delta must not reach the raw archive.
    _translate(
        runtime_dir,
        [
            _record("message.part.delta", {"delta": "use sk-ant-secret1234567890 please"}),
            _record("session.idle", {"sessionID": "ses-oc-1"}),
        ],
    )
    raw = (runtime_dir / "harness-events/opencode.jsonl").read_text(encoding="utf-8")
    assert "sk-ant-secret1234567890" not in raw


# ── opencode_bridge: deterministic reject + negotiation + SSE parse ─────────

def _load_bridge():
    import importlib
    import sys

    adapters_dir = str(HARNESS_DIR / "adapters")
    if adapters_dir not in sys.path:
        sys.path.insert(0, adapters_dir)
    return importlib.import_module("opencode_bridge")


def test_opencode_bridge_rejects_disabled_gate(tmp_path):
    bridge = _load_bridge()
    b = bridge.OpenCodeBridge()
    for command_type in ("steer", "follow_up"):
        outcome = b.dispatch(
            {
                "frame_version": "1",
                "command_id": "cmd-1",
                "sequence_no": 1,
                "type": command_type,
                "payload": {"text": "please continue"},
            }
        )
        assert outcome["status"] == "reject"
        assert outcome["rejection_code"] == "control_gate_closed"
        # Never a delivered path — OpenCode first release delivers nothing.
        assert "command_id" not in outcome or outcome.get("command_id") is None


def test_opencode_bridge_validates_frame_and_payload(tmp_path):
    bridge = _load_bridge()
    b = bridge.OpenCodeBridge()
    assert b.dispatch({"frame_version": "99", "type": "steer"})["rejection_code"] == "unsupported_frame_version"
    assert b.dispatch({"frame_version": "1", "type": "explode"})["rejection_code"] == "invalid_command_type"
    assert b.dispatch({"frame_version": "1", "type": "steer", "payload": {}})["rejection_code"] == "invalid_command_type"
    long = b.dispatch({"frame_version": "1", "type": "steer", "payload": {"text": "x" * 5000}})
    assert long["rejection_code"] == "payload_too_large"


def test_opencode_negotiate_capabilities_disabled(tmp_path):
    bridge = _load_bridge()
    caps = bridge.negotiate_capabilities("opencode")
    assert caps == {"steering": False, "follow_up": False}


def test_opencode_parse_sse_unwraps_wire_frame(tmp_path):
    bridge = _load_bridge()
    wire = (
        "id: ev-1\n"
        "type: server.connected\n"
        "properties: {}\n"
        "\n"
        "id: ev-2\n"
        "type: session.idle\n"
        "properties: {\"sessionID\":\"ses-1\"}\n"
        "\n"
    )
    events = list(bridge.parse_sse(wire))
    assert len(events) == 2
    assert events[0]["type"] == "server.connected"
    assert events[1]["type"] == "session.idle"
    assert events[1]["properties"] == {"sessionID": "ses-1"}


def test_opencode_client_sets_basic_auth(tmp_path):
    bridge = _load_bridge()
    client = bridge.OpenCodeServerClient(port=8099, password="pw", username="opencode")
    headers = client._headers()
    assert headers["Authorization"].startswith("Basic ")


# ── _run_attempt: subscribe-before-prompt (F1) + BrokenPipe tolerance (F2) ────

def _run_attempt_env(tmp_path: Path) -> dict[str, str]:
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("do the thing", encoding="utf-8")
    return {
        **_environment(tmp_path),
        **V2_ENV,
        "OPENCODE_PORT": "8099",
        "OPENCODE_SERVER_PASSWORD": "pw",
        "OPENCODE_SERVER_USERNAME": "opencode",
        "OPENCODE_MODEL": "deepseek-v4-flash",
        "CODIFY_OPENCODE_EVENT_TRANSLATOR": str(TRANSLATOR),
        "CODIFY_OPENCODE_RAW_EVENT_JSONL": str(tmp_path / "harness-events/opencode.jsonl"),
        "PROMPT_FILE": str(prompt_file),
    }


class _OrderedFakeClient:
    """Fake Server client that records the order of calls (F1 verification).

    ``event_stream`` models the real generator: the HTTP ``GET /event`` is sent
    lazily on first advancement (recorded as ``stream_established``), then
    ``server.connected`` arrives to confirm the subscription.
    """

    def __init__(self, calls: list[str], records: list[dict]):
        self.calls = calls
        self.records = records

    def create_session(self, model_id: str, provider_id: str):
        self.calls.append("create_session")
        return 200, {"info": {"id": "ses-oc-run"}}

    def event_stream(self):
        self.calls.append("stream_established")
        for record in self.records:
            yield record

    def prompt_async(self, session_id: str, text: str):
        self.calls.append("prompt_async")
        return 204, {}

    def status(self, session_id: str):
        self.calls.append("status")
        return 200, {"info": {"status": {"type": "idle"}}}


def test_opencode_run_attempt_subscribes_before_prompt(tmp_path, monkeypatch):
    bridge = _load_bridge()
    calls: list[str] = []
    fake = _OrderedFakeClient(
        calls,
        [
            {"id": "e1", "type": "server.connected", "properties": {}},
            {"id": "e2", "type": "session.status", "properties": {"sessionID": "ses-oc-run", "status": {"type": "busy"}}},
            {"id": "e3", "type": "message.part.delta", "properties": {"sessionID": "ses-oc-run", "delta": "ok"}},
            {"id": "e4", "type": "session.idle", "properties": {"sessionID": "ses-oc-run"}},
            {"id": "e5", "type": "server.heartbeat", "properties": {}},
        ],
    )
    monkeypatch.setattr(bridge, "OpenCodeServerClient", lambda **kw: fake)
    for key, value in _run_attempt_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    _emit(tmp_path, "run.started", {"runtime_bundle_digest": "d" * 64})

    rc = bridge._run_attempt()

    assert rc == 0
    # Subscription established (GET /event advanced, server.connected seen) BEFORE prompt.
    assert calls.index("stream_established") < calls.index("prompt_async")
    # No status fallback on a clean stream.
    assert "status" not in calls


def test_opencode_run_attempt_status_fallback_after_disconnect(tmp_path, monkeypatch):
    bridge = _load_bridge()

    def _disconnecting_stream():
        yield {"id": "e1", "type": "server.connected", "properties": {}}
        yield {"id": "e2", "type": "session.status", "properties": {"sessionID": "ses-oc-run", "status": {"type": "busy"}}}
        raise ConnectionError("stream dropped")

    calls: list[str] = []

    class _Fake:
        def create_session(self, *a, **k):
            return 200, {"info": {"id": "ses-oc-run"}}

        def event_stream(self):
            calls.append("stream_established")
            return _disconnecting_stream()

        def prompt_async(self, *a, **k):
            calls.append("prompt_async")
            return 204, {}

        def status(self, *a, **k):
            calls.append("status")
            return 200, {"info": {"status": {"type": "idle"}}}

    monkeypatch.setattr(bridge, "OpenCodeServerClient", lambda **kw: _Fake())
    for key, value in _run_attempt_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    _emit(tmp_path, "run.started", {"runtime_bundle_digest": "d" * 64})

    rc = bridge._run_attempt()

    assert rc == 0
    assert "status" in calls  # disconnect triggered the GET /session/status fallback
    # The status-reported idle recovered a settled turn: single completed terminal.
    types = [e["type"] for e in _events(tmp_path)]
    assert types.count("harness.completed") == 1


class _Pipe:
    """Minimal stand-in for a translator ``Popen`` exposing ``.stdin``."""

    def __init__(self, stdin):
        self.stdin = stdin


def test_opencode_forward_tolerates_closed_stdin(tmp_path):
    # F2: after the translator converges its terminal its stdin read end is
    # closed; a later write from the still-draining stream raises EPIPE, which
    # _forward must swallow rather than crash the Bridge.
    bridge = _load_bridge()
    read_fd, write_fd = os.pipe()
    os.close(read_fd)  # read end closed -> write raises BrokenPipeError (EPIPE)
    stdin = os.fdopen(write_fd, "w", encoding="utf-8")
    try:
        raw_path = tmp_path / "raw.jsonl"
        with raw_path.open("w", encoding="utf-8") as raw:
            bridge._forward(
                {"id": None, "type": "server.heartbeat", "properties": {}},
                raw,
                _Pipe(stdin),
            )
        # No exception propagated; the record still reached the raw archive.
        assert "server.heartbeat" in raw_path.read_text(encoding="utf-8")
    finally:
        try:
            stdin.close()
        except BrokenPipeError:
            pass


# ── opencode.sh adapter shell ───────────────────────────────────────────────

def _source_adapter(script: str, env: dict[str, str]):
    return subprocess.run(
        ["bash", "-c", f'source "{ADAPTER}" && {script}'],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
    )


def test_opencode_verify_runtime_enforces_pinned_version(tmp_path):
    cli = tmp_path / "opencode"
    cli.write_text("#!/bin/sh\necho opencode 1.18.19\n", encoding="utf-8")
    cli.chmod(0o755)
    env = {
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_OPENCODE_BIN": str(cli),
        "ENTRYPOINT_LIB_DIR": str(REPO_ROOT / "deploy/worker-entrypoint"),
        "CODIFY_RUNTIME_DIR": str(tmp_path),
        "CODIFY_RUN_UID": "1000",
        "CODIFY_RUN_GID": "1000",
    }
    ok = _source_adapter("opencode_adapter_verify_runtime", env)
    assert ok.returncode == 0, ok.stderr
    # Out-of-pin version must fail closed (manifest pins 1.18.19).
    cli2 = tmp_path / "opencode-bad"
    cli2.write_text("#!/bin/sh\necho opencode 9.9.9\n", encoding="utf-8")
    cli2.chmod(0o755)
    env2 = {**env, "CODIFY_OPENCODE_BIN": str(cli2)}
    bad = _source_adapter("opencode_adapter_verify_runtime", env2)
    assert bad.returncode != 0
    assert "version mismatch" in bad.stderr


def test_opencode_prepare_config_writes_snapshot_endpoint(tmp_path):
    env = {
        "CODIFY_RUNTIME_DIR": str(tmp_path),
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_RUN_UID": "1000",
        "CODIFY_RUN_GID": "1000",
        "OPENCODE_MODEL": "deepseek-v4-flash",
        "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
        "ANTHROPIC_API_KEY": "sk-snapshot-secret",
    }
    result = _source_adapter(
        "opencode_adapter_prepare_config && printf '%s' \"$OPENCODE_PORT\"",
        env,
    )
    assert result.returncode == 0, result.stderr
    config = tmp_path / "opencode" / "opencode.json"
    assert config.exists()
    content = json.loads(config.read_text(encoding="utf-8"))
    provider = content["provider"]["codify"]
    # Snapshot base URL wins; credential referenced by env name, never inlined.
    assert provider["options"]["baseURL"] == "https://api.deepseek.com/anthropic"
    assert provider["options"]["apiKey"] == "{env:OPENCODE_SNAPSHOT_KEY}"
    assert "sk-snapshot-secret" not in config.read_text(encoding="utf-8")
    # A free loopback port was probed and a Task password generated.
    assert result.stdout.strip().isdigit()
