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
import signal
import subprocess
import time
from pathlib import Path

import pytest

from app.core.harness_protocol import CANONICAL_EVENT_SCHEMA_V2, replay_events, validate_event_v2

REPO_ROOT = Path(__file__).resolve().parents[3]
HARNESS_DIR = REPO_ROOT / "deploy/worker-entrypoint/harness"
TRANSLATOR = HARNESS_DIR / "adapters/opencode_events.py"
EVENT_WRITER = HARNESS_DIR / "events.py"
ADAPTER = HARNESS_DIR / "adapters/opencode.sh"
LEGACY_RUNNER = REPO_ROOT / "deploy/worker-entrypoint/legacy/opencode-run.sh"
PROBE_ROOT = REPO_ROOT / "docs/harness-probes/v2/opencode"

V2_ENV = {
    "CODIFY_RUNTIME_CONTRACT_VERSION": "codify.worker.harness/v2",
    "CODIFY_EVENT_SCHEMA": CANONICAL_EVENT_SCHEMA_V2,
    "CODIFY_HARNESS_CONTROL_TRANSPORT_KIND": "server_http",
    "CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL": "opencode-server",
    "CODIFY_HARNESS_MODEL_PROTOCOLS": "anthropic_messages",
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


def _durable_record(event_type: str, data: dict | None = None) -> dict:
    return {"id": "evt-durable-1", "type": event_type, "data": data or {}}


def _success_records() -> list[dict]:
    return [
        _record("server.connected"),
        _record("session.created", {"sessionID": "ses-oc-1", "info": {"id": "ses-oc-1", "version": "1.18.19"}}),
        _record("session.status", {"sessionID": "ses-oc-1", "status": {"type": "busy"}}),
        _record("message.part.delta", {"sessionID": "ses-oc-1", "messageID": "m1", "partID": "p1", "delta": "Hello "}),
        _record("message.part.delta", {"sessionID": "ses-oc-1", "messageID": "m1", "partID": "p1", "delta": "world"}),
        _record("message.part.updated", {"sessionID": "ses-oc-1", "part": {"type": "text", "text": "Hello world", "messageID": "m1"}}),
        _record("message.updated", {"sessionID": "ses-oc-1", "info": {"id": "m1", "role": "assistant"}}),
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
    assert result["result"] == "Hello world"


def test_opencode_usage_maps_native_fields_and_emits_usage_final(tmp_path):
    runtime_dir = tmp_path / "usage"
    runtime_dir.mkdir()
    records = _success_records()
    records[6] = _record(
        "message.updated",
        {
            "sessionID": "ses-oc-1",
            "info": {
                "id": "m1",
                "role": "assistant",
                "tokens": {
                    "input": 20,
                    "output": 4,
                    "reasoning": 7,
                    "total": 1560,
                    "cache": {"read": 1536, "write": 32},
                },
                "cost": 0.03,
            },
        },
    )
    _emit(runtime_dir, "run.started", {"runtime_bundle_digest": "d" * 64})
    _translate(runtime_dir, records)

    translated = _events(runtime_dir)
    for event in translated:
        assert validate_event_v2(event)["schema"] == CANONICAL_EVENT_SCHEMA_V2
    usage_events = [event for event in translated if event["type"] == "usage.final"]
    assert len(usage_events) == 1
    usage = usage_events[0]["payload"]["usage"]
    assert usage["input_tokens"] == 20
    assert usage["cached_input_tokens"] == 1536
    assert usage["output_tokens"] == 4
    assert usage["reasoning_tokens"] == 7
    assert usage["cost"] == 0.03
    assert usage["engine_fields"]["cache"]["write"] == 32
    assert usage["engine_fields"]["total"] == 1560

    result = json.loads((runtime_dir / "harness-result.json").read_text(encoding="utf-8"))
    assert result["usage"] == usage


def test_opencode_usage_keeps_flat_aliases_and_nested_cost_breakdown(tmp_path):
    runtime_dir = tmp_path / "usage-flat"
    runtime_dir.mkdir()
    records = _success_records()
    records[6] = _record(
        "message.updated",
        {
            "sessionID": "ses-oc-1",
            "info": {
                "id": "m1",
                "role": "assistant",
                "usage": {
                    "input": 20,
                    "output": 4,
                    "cacheRead": 1536,
                    "cacheWrite": 32,
                    "totalTokens": 1560,
                    "reasoningTokens": 7,
                    "cost": {
                        "input": 0.01,
                        "output": 0.02,
                        "cacheRead": 0.0,
                        "cacheWrite": 0.0,
                        "total": 0.03,
                    },
                },
            },
        },
    )
    _emit(runtime_dir, "run.started", {"runtime_bundle_digest": "d" * 64})
    _translate(runtime_dir, records)

    translated = _events(runtime_dir)
    for event in translated:
        assert validate_event_v2(event)["schema"] == CANONICAL_EVENT_SCHEMA_V2
    usage_events = [event for event in translated if event["type"] == "usage.final"]
    assert len(usage_events) == 1
    usage = usage_events[0]["payload"]["usage"]
    assert usage["input_tokens"] == 20
    assert usage["cached_input_tokens"] == 1536
    assert usage["output_tokens"] == 4
    assert usage["reasoning_tokens"] == 7
    assert usage["cost"] == 0.03
    assert usage["engine_fields"]["cacheWrite"] == 32
    assert usage["engine_fields"]["totalTokens"] == 1560
    assert usage["engine_fields"]["cost_breakdown"]["output"] == 0.02

    result = json.loads((runtime_dir / "harness-result.json").read_text(encoding="utf-8"))
    assert result["usage"] == usage


def test_opencode_stream_keeps_user_parts_out_of_assistant_result(tmp_path):
    runtime_dir = tmp_path / "role-aware"
    runtime_dir.mkdir()
    records = [
        _record("message.updated", {"sessionID": "ses-oc-roles", "info": {"id": "u1", "role": "user"}}),
        _record(
            "message.part.updated",
            {
                "sessionID": "ses-oc-roles",
                "part": {"type": "text", "text": "user prompt", "messageID": "u1", "id": "up1"},
            },
        ),
        _record(
            "message.part.updated",
            {
                "sessionID": "ses-oc-roles",
                "part": {
                    "type": "text",
                    "text": "assistant answer",
                    "messageID": "a1",
                    "id": "ap1",
                },
            },
        ),
        # A full part snapshot may precede a repeated delta on the wire. It
        # must not duplicate the assistant result.
        _record(
            "message.part.delta",
            {"sessionID": "ses-oc-roles", "messageID": "a1", "partID": "ap1", "delta": "assistant answer"},
        ),
        _record("message.updated", {"sessionID": "ses-oc-roles", "info": {"id": "a1", "role": "assistant"}}),
        _record("session.idle", {"sessionID": "ses-oc-roles"}),
    ]
    _emit(runtime_dir, "run.started", {"runtime_bundle_digest": "d" * 64})
    _translate(runtime_dir, records)

    result = json.loads((runtime_dir / "harness-result.json").read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    assert result["result"] == "assistant answer"
    assert all(event["payload"].get("content") != "user prompt" for event in _events(runtime_dir))


def _tool_part_record(
    *,
    call_id: str,
    tool: str,
    status: str,
    input_value: dict | None = None,
    output: str | None = None,
    error: str | None = None,
    exit_code: int | None = None,
) -> dict:
    state = {"status": status, "input": input_value or {}}
    if output is not None:
        state["output"] = output
    if error is not None:
        state["error"] = error
    if exit_code is not None:
        state["metadata"] = {"exit": exit_code}
    return _record(
        "message.part.updated",
        {
            "sessionID": "ses-oc-tools",
            "part": {
                "type": "tool",
                "id": f"part-{call_id}",
                "messageID": "m-tools",
                "callID": call_id,
                "tool": tool,
                "state": state,
            },
        },
    )


def test_opencode_tool_snapshots_map_to_one_canonical_lifecycle(tmp_path):
    runtime_dir = tmp_path / "tools"
    runtime_dir.mkdir()
    records = [
        _record("session.created", {"sessionID": "ses-oc-tools"}),
        _record("message.updated", {"sessionID": "ses-oc-tools", "info": {"id": "m-tools", "role": "assistant"}}),
        # The first pending snapshot has no useful input. It must not create an
        # empty tool row that can never be amended by a later snapshot.
        _tool_part_record(call_id="call-bash", tool="bash", status="pending"),
        _tool_part_record(
            call_id="call-bash",
            tool="bash",
            status="running",
            input_value={"command": "printf 'ok'"},
        ),
        _tool_part_record(
            call_id="call-bash",
            tool="bash",
            status="running",
            input_value={"command": "printf 'ok'"},
        ),
        _tool_part_record(
            call_id="call-bash",
            tool="bash",
            status="completed",
            input_value={"command": "printf 'ok'"},
            output="ok",
            exit_code=0,
        ),
        _tool_part_record(
            call_id="call-write",
            tool="write",
            status="running",
            input_value={"filePath": "/workspace/result.txt", "content": "done"},
        ),
        _tool_part_record(
            call_id="call-write",
            tool="write",
            status="error",
            input_value={"filePath": "/workspace/result.txt", "content": "done"},
            error="write failed",
        ),
        _record(
            "message.part.updated",
            {
                "sessionID": "ses-oc-tools",
                "part": {"type": "text", "text": "finished", "messageID": "m-tools", "id": "text-1"},
            },
        ),
        _record("session.idle", {"sessionID": "ses-oc-tools"}),
    ]
    _emit(runtime_dir, "run.started", {"runtime_bundle_digest": "d" * 64})
    _translate(runtime_dir, records)

    translated = _events(runtime_dir)
    for event in translated:
        assert validate_event_v2(event)["schema"] == CANONICAL_EVENT_SCHEMA_V2
    tool_started = [event for event in translated if event["type"] == "tool.started"]
    tool_completed = [event for event in translated if event["type"] == "tool.completed"]
    assert len(tool_started) == 2
    assert len(tool_completed) == 2
    assert tool_started[0]["payload"] == {
        "tool_id": "call-bash",
        "name": "Bash",
        "input": {"command": "printf 'ok'"},
    }
    assert tool_completed[0]["payload"] == {
        "tool_id": "call-bash",
        "name": "Bash",
        "output": "ok",
        "error": False,
        "exit_code": 0,
    }
    assert tool_started[1]["payload"]["name"] == "Write"
    assert tool_started[1]["payload"]["input"] == {
        "content": "done",
        "file_path": "/workspace/result.txt",
    }
    assert tool_completed[1]["payload"]["error"] is True
    assert [event["type"] for event in translated].count("harness.completed") == 1


def test_opencode_durable_events_map_text_tool_usage_and_compaction(tmp_path):
    runtime_dir = tmp_path / "durable"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started", {"runtime_bundle_digest": "d" * 64})
    _translate(
        runtime_dir,
        [
            _durable_record(
                "session.next.text.started",
                {"sessionID": "ses-next", "assistantMessageID": "msg-next", "textID": "txt-next"},
            ),
            _durable_record(
                "session.next.tool.input.started",
                {"sessionID": "ses-next", "assistantMessageID": "msg-next", "callID": "call-next", "name": "bash"},
            ),
            _durable_record(
                "session.next.tool.input.delta",
                {"sessionID": "ses-next", "assistantMessageID": "msg-next", "callID": "call-next", "delta": '{"command":"printf ok"}'},
            ),
            _durable_record(
                "session.next.tool.input.ended",
                {"sessionID": "ses-next", "assistantMessageID": "msg-next", "callID": "call-next", "text": '{"command":"printf ok"}'},
            ),
            _durable_record(
                "session.next.tool.called",
                {
                    "sessionID": "ses-next",
                    "assistantMessageID": "msg-next",
                    "callID": "call-next",
                    "tool": "bash",
                    "input": {"command": "printf ok"},
                },
            ),
            _durable_record(
                "session.next.tool.success",
                {
                    "sessionID": "ses-next",
                    "assistantMessageID": "msg-next",
                    "callID": "call-next",
                    "content": [{"type": "text", "text": "ok"}],
                    "result": "ok",
                },
            ),
            _durable_record(
                "session.next.text.delta",
                {"sessionID": "ses-next", "assistantMessageID": "msg-next", "textID": "txt-next", "delta": "done"},
            ),
            _durable_record(
                "session.next.text.ended",
                {"sessionID": "ses-next", "assistantMessageID": "msg-next", "textID": "txt-next", "text": "done"},
            ),
            _durable_record(
                "session.next.step.ended",
                {
                    "sessionID": "ses-next",
                    "assistantMessageID": "msg-next",
                    "finish": "stop",
                    "cost": 0.01,
                    "tokens": {"input": 10, "output": 2, "reasoning": 1, "cache": {"read": 3, "write": 0}},
                },
            ),
            _durable_record(
                "session.next.compaction.ended",
                {"sessionID": "ses-next", "reason": "threshold", "text": "summary"},
            ),
            _durable_record(
                "session.next.step.started",
                {"sessionID": "ses-next", "assistantMessageID": "msg-next", "agent": "build"},
            ),
            _record("session.idle", {"sessionID": "ses-next"}),
        ],
    )

    events = _events(runtime_dir)
    assert [event["type"] for event in events].count("tool.started") == 1
    assert [event["type"] for event in events].count("tool.completed") == 1
    tool_started = next(event for event in events if event["type"] == "tool.started")
    assert tool_started["payload"] == {
        "tool_id": "call-next",
        "name": "Bash",
        "input": {"command": "printf ok"},
    }
    tool_completed = next(event for event in events if event["type"] == "tool.completed")
    assert tool_completed["payload"] == {
        "tool_id": "call-next",
        "name": "Bash",
        "output": "ok",
        "error": False,
    }
    assert any(event["type"] == "message.delta" and event["payload"]["content"] == "done" for event in events)
    assert any(event["type"] == "usage.updated" for event in events)
    compacted = next(event for event in events if event["type"] == "context.compacted")
    assert compacted["payload"]["summary"] == "summary"
    assert any(
        event["type"] == "diagnostic"
        and event["payload"].get("code") == "opencode_durable_event"
        and event["payload"].get("type") == "session.next.step.started"
        for event in events
    )
    assert not any(
        event["type"] == "diagnostic" and event["payload"].get("code") == "unknown_raw_event"
        for event in events
    )
    raw = (runtime_dir / "harness-events/opencode.jsonl").read_text(encoding="utf-8")
    assert '"type":"session.next.tool.called"' in raw


@pytest.mark.parametrize(
    "event_type",
    [
        "permission.asked",
        "permission.v2.asked",
        "question.asked",
        "question.v2.asked",
    ],
)
def test_opencode_interactive_requests_fail_closed_with_typed_diagnostic(tmp_path, event_type):
    runtime_dir = tmp_path / event_type.replace(".", "-")
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    _translate(
        runtime_dir,
        [_record(event_type, {"sessionID": "ses-interactive", "id": "req-1"})],
    )
    events = _events(runtime_dir)
    diagnostic = next(event for event in events if event["type"] == "diagnostic")
    assert diagnostic["payload"]["code"] == "interactive_request_unsupported"
    result = json.loads((runtime_dir / "harness-result.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["failure"]["kind"] == ("sandbox_error" if "permission" in event_type else "engine_error")


def test_opencode_structured_session_error_uses_status_code_taxonomy(tmp_path):
    runtime_dir = tmp_path / "structured-error"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    _translate(
        runtime_dir,
        [
            _record(
                "session.error",
                {
                    "sessionID": "ses-error",
                    "error": {"name": "ProviderAuthError", "message": "credentials rejected", "statusCode": 401},
                },
            ),
        ],
    )
    result = json.loads((runtime_dir / "harness-result.json").read_text(encoding="utf-8"))
    assert result["failure"]["kind"] == "authentication_error"
    assert "credentials rejected" in result["failure"]["message"]


def test_opencode_known_server_events_are_archived_without_unknown_diagnostics(tmp_path):
    runtime_dir = tmp_path / "known-events"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    _translate(
        runtime_dir,
        [
            _record("catalog.updated", {"items": ["redacted"]}),
            _record("plugin.added", {"name": "example"}),
            _record("file.edited", {"file": "/workspace/a.txt"}),
            _record("message.updated", {"sessionID": "ses-known", "info": {"id": "m1", "role": "assistant"}}),
            _record("message.part.updated", {"part": {"type": "text", "text": "ok", "messageID": "m1", "id": "p1"}}),
            _record("session.idle", {"sessionID": "ses-known"}),
        ],
    )
    diagnostics = [event for event in _events(runtime_dir) if event["type"] == "diagnostic"]
    assert all(event["payload"].get("code") != "unknown_raw_event" for event in diagnostics)
    raw = (runtime_dir / "harness-events/opencode.jsonl").read_text(encoding="utf-8")
    assert '"type":"catalog.updated"' in raw


def test_opencode_idle_with_active_tool_is_protocol_failure(tmp_path):
    runtime_dir = tmp_path / "active-tool"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    _translate(
        runtime_dir,
        [
            _record("message.updated", {"sessionID": "ses-active", "info": {"id": "m1", "role": "assistant"}}),
            _tool_part_record(
                call_id="call-active",
                tool="bash",
                status="running",
                input_value={"command": "sleep 1"},
            ),
            _record("message.part.updated", {"part": {"type": "text", "text": "done", "messageID": "m1", "id": "p1"}}),
            _record("session.idle", {"sessionID": "ses-active"}),
        ],
    )
    result = json.loads((runtime_dir / "harness-result.json").read_text(encoding="utf-8"))
    assert result["status"] == "protocol_error"
    assert result["failure"]["kind"] == "protocol_error"


def test_opencode_session_idle_without_final_message_is_protocol_failure(tmp_path):
    runtime_dir = tmp_path / "idle"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    _translate(runtime_dir, [_record("session.idle", {"sessionID": "ses-oc-1"})])
    result = json.loads((runtime_dir / "harness-result.json").read_text(encoding="utf-8"))
    assert result["status"] == "protocol_error"
    assert result["success"] is False
    assert "harness.failed" in [e["type"] for e in _events(runtime_dir)]


@pytest.mark.parametrize(
    ("reason", "reason_location"),
    [
        ("account_rate_limit", "action"),
        ("quota_exceeded", "action"),
        ("usage-limit-exceeded", "status"),
    ],
)
def test_opencode_usage_limit_retry_maps_to_rate_limited_terminal(
    tmp_path, reason, reason_location
):
    runtime_dir = tmp_path / "rate-limit"
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    retry_status = {
        "type": "retry",
        "attempt": 1,
        "message": "provider rejected request",
    }
    if reason_location == "action":
        retry_status["action"] = {"reason": reason}
    else:
        retry_status["reason"] = reason
    _translate(
        runtime_dir,
        [
            _record(
                "session.status",
                {
                    "sessionID": "ses-oc-limit",
                    "status": retry_status,
                },
            ),
        ],
    )

    result = json.loads((runtime_dir / "harness-result.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["success"] is False
    assert result["failure"]["kind"] == "rate_limited"
    terminal = [event for event in _events(runtime_dir) if event["type"] == "harness.failed"]
    assert len(terminal) == 1
    assert terminal[0]["payload"]["failure"]["kind"] == "rate_limited"


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
            _record("message.part.delta", {"delta": "use API_KEY=sample1 please"}),
            _record("session.idle", {"sessionID": "ses-oc-1"}),
        ],
    )
    raw = (runtime_dir / "harness-events/opencode.jsonl").read_text(encoding="utf-8")
    assert "API_KEY=sample1" not in raw


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


def test_opencode_bridge_rejects_unknown_protocol_before_session_creation(tmp_path, monkeypatch):
    bridge = _load_bridge()
    created = False

    class _UnexpectedClient:
        def __init__(self, **_kwargs):
            nonlocal created
            created = True

    monkeypatch.setattr(bridge, "OpenCodeServerClient", _UnexpectedClient)
    for key, value in _run_attempt_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("CODIFY_MODEL_PROTOCOL", "vendor_proprietary")

    assert bridge._run_attempt() == 1
    assert created is False


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


def test_opencode_parse_sse_data_frames_from_11819(tmp_path):
    """1.18.19 /event emits single-line ``data: {json}`` frames (probe evidence).

    Each event is ``data: {\"id\",\"type\",\"properties\"}`` terminated by a blank
    line. parse_sse must surface server.connected so the bridge can subscribe
    before prompt (O2 regression).
    """
    bridge = _load_bridge()
    wire = (
        'data: {"id":"ev-1","type":"server.connected","properties":{}}\n'
        '\n'
        'data: {"id":"ev-2","type":"session.idle","properties":{"sessionID":"ses-1"}}\n'
        '\n'
    )
    events = list(bridge.parse_sse(wire))
    assert len(events) == 2
    assert events[0]["id"] == "ev-1"
    assert events[0]["type"] == "server.connected"
    assert events[0].get("properties", {}) == {}
    assert events[1]["type"] == "session.idle"
    assert events[1]["properties"] == {"sessionID": "ses-1"}


def test_opencode_parse_sse_unwraps_global_payload_and_keeps_durable_data(tmp_path):
    bridge = _load_bridge()
    wire = (
        'data: {"directory":"/workspace","payload":{"id":"evt-1","type":"session.next.text.delta","data":{"sessionID":"ses-1","assistantMessageID":"msg-1","textID":"txt-1","delta":"ok"}}}\n'
        '\n'
    )
    events = list(bridge.parse_sse(wire))
    assert events == [
        {
            "id": "evt-1",
            "type": "session.next.text.delta",
            "data": {
                "sessionID": "ses-1",
                "assistantMessageID": "msg-1",
                "textID": "txt-1",
                "delta": "ok",
            },
        }
    ]


def test_opencode_event_stream_preserves_durable_data(tmp_path, monkeypatch):
    bridge = _load_bridge()

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __init__(self):
            self.chunks = iter(
                [
                    (
                        'data: {"payload":{"id":"evt-1","type":"session.next.text.delta",'
                        '"data":{"sessionID":"ses-1","delta":"ok"}}}\n\n'
                    ).encode()
                ]
            )

        def read1(self, size=-1):
            return next(self.chunks, b"")

    monkeypatch.setattr(bridge.urllib.request, "urlopen", lambda *args, **kwargs: _Response())
    records = list(bridge.OpenCodeServerClient(port=8099).event_stream())
    assert records == [
        {
            "id": "evt-1",
            "type": "session.next.text.delta",
            "properties": {},
            "data": {"sessionID": "ses-1", "delta": "ok"},
        }
    ]


def test_opencode_parse_sse_data_frame_split_across_chunks(tmp_path):
    """A data: event split at a chunk boundary surfaces exactly once (no dup)."""
    bridge = _load_bridge()
    first_chunk = 'data: {"id":"ev-1","type":"server.connected","prop'
    second_chunk = 'erties":{}}\n\n'
    events = list(bridge.parse_sse(first_chunk))
    assert events == []
    events = list(bridge.parse_sse(first_chunk + second_chunk))
    assert len(events) == 1
    assert events[0]["type"] == "server.connected"


def test_opencode_sse_tail_handles_crlf_framing(tmp_path):
    bridge = _load_bridge()
    first_chunk = 'data: {"id":"ev-1","type":"server.connected","properties":{}}\r\n\r\n'
    second_chunk = 'data: {"id":"ev-2","type":"session.idle","properties":{"sessionID":"ses-1"}}\r\n\r\n'
    assert list(bridge.parse_sse(first_chunk)) == [
        {"id": "ev-1", "type": "server.connected", "properties": {}}
    ]
    assert bridge._sse_tail(first_chunk + second_chunk) == ""
    assert list(bridge.parse_sse(second_chunk)) == [
        {"id": "ev-2", "type": "session.idle", "properties": {"sessionID": "ses-1"}}
    ]


def test_opencode_parse_sse_from_captured_11819_wire(tmp_path):
    """The live-captured /event fixture (events.wire.sse) parses at churn.

    First frame is verbatim from a real 1.18.19 server.connected event; the
    bridge's subscription waits on exactly this record before prompting (O2).
    """
    bridge = _load_bridge()
    wire = (PROBE_ROOT / "events.wire.sse").read_text(encoding="utf-8")
    records = list(bridge.parse_sse(wire))
    assert records[0]["id"] == "evt_0243db697001U5L8xei9l1Hum4"
    assert records[0]["type"] == "server.connected"
    assert records[0].get("properties", {}) == {}
    assert any(r["type"] == "session.idle" for r in records)


def test_opencode_event_stream_reads_small_chunks_from_wire(tmp_path, monkeypatch):
    """GET /event must be consumed in small chunks (read1), not read(8192).

    The 1.18.19 wire fixture starts with an ~89B server.connected frame; a plain
    ``read(8192)`` stalls until the whole buffer fills, so the subscription never
    sees the connected signal. ``read1`` surfaces the small frame immediately.
    The fixture is delivered one blank-line-terminated event per chunk, and the
    first record is yielded from the first patch alone (chunked-SSE boundary).
    """
    bridge = _load_bridge()
    wire = (PROBE_ROOT / "events.wire.sse").read_text(encoding="utf-8")
    events = [e for e in wire.split("\n\n") if e.strip()]
    event_chunks = [(e + "\n\n").encode() for e in events]
    methods_used: list[str] = []

    class _ChunkedResponse:
        def __init__(self, chunks):
            self._chunks = iter(chunks)
            self._remainder = b""

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, size=-1):
            methods_used.append("read")
            return b""  # a streaming stub; read() blocks until the full size

        def read1(self, size=-1):
            methods_used.append("read1")
            if self._remainder:
                chunk, self._remainder = self._remainder, b""
                return chunk
            try:
                return next(self._chunks)
            except StopIteration:
                return b""

    def _urlopen(request, timeout=None, **_kw):
        return _ChunkedResponse(event_chunks)

    monkeypatch.setattr(bridge.urllib.request, "urlopen", _urlopen)
    client = bridge.OpenCodeServerClient(port=8099, password="pw")
    stream = client.event_stream()
    first = next(stream)  # server.connected is the first fixture event
    assert first["type"] == "server.connected"
    assert first["id"] == "evt_0243db697001U5L8xei9l1Hum4"
    assert "read1" in methods_used
    rest = list(stream)
    assert [r["type"] for r in rest] == [
        "session.status",
        "message.part.delta",
        "session.idle",
    ]


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
    raw_records = [
        json.loads(line)
        for line in (tmp_path / "harness-events/opencode.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["type"] for record in raw_records] == [
        "server.connected",
        "session.status",
        "message.part.delta",
        "session.idle",
    ]


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
    # Status-only idle is insufficient without an observed final assistant message.
    types = [e["type"] for e in _events(tmp_path)]
    assert "harness.completed" not in types
    assert types.count("harness.failed") == 1
    result = json.loads((tmp_path / "harness-result.json").read_text(encoding="utf-8"))
    assert result["status"] == "protocol_error"


def test_opencode_run_attempt_status_recovery_failure_is_typed_crash(tmp_path, monkeypatch):
    bridge = _load_bridge()

    def _disconnecting_stream():
        yield {"id": "e1", "type": "server.connected", "properties": {}}
        yield {"id": "e2", "type": "session.status", "properties": {"sessionID": "ses-oc-run", "status": {"type": "busy"}}}
        raise ConnectionError("connection refused")

    class _Fake:
        def create_session(self, *a, **k):
            return 200, {"info": {"id": "ses-oc-run"}}

        def event_stream(self):
            return _disconnecting_stream()

        def prompt_async(self, *a, **k):
            return 204, {}

        def status(self, *a, **k):
            raise ConnectionError("connection refused")

    monkeypatch.setattr(bridge, "OpenCodeServerClient", lambda **kw: _Fake())
    for key, value in _run_attempt_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    _emit(tmp_path, "run.started", {"runtime_bundle_digest": "d" * 64})

    assert bridge._run_attempt() == 0
    result = json.loads((tmp_path / "harness-result.json").read_text(encoding="utf-8"))
    assert result["failure"]["kind"] == "crash"


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
        bridge._forward(
            {"id": None, "type": "server.heartbeat", "properties": {}},
            _Pipe(stdin),
        )
        # No exception propagated. The translator, not the Bridge, owns the
        # sanitized raw archive.
    finally:
        try:
            stdin.close()
        except BrokenPipeError:
            pass


def test_opencode_run_attempt_resumes_existing_session_without_creating_one(tmp_path, monkeypatch):
    bridge = _load_bridge()
    calls: list[str] = []

    class _ResumeClient:
        def get_session(self, session_id: str):
            calls.append(f"get_session:{session_id}")
            return 200, {"id": session_id}

        def create_session(self, *args, **kwargs):
            calls.append("create_session")
            raise AssertionError("continuation must not create a new OpenCode session")

        def event_stream(self):
            calls.append("stream_established")
            yield {"id": "e1", "type": "server.connected", "properties": {}}
            yield {
                "id": "e2",
                "type": "message.part.updated",
                "properties": {
                    "sessionID": "ses-oc-resume",
                    "part": {"type": "text", "text": "continued", "messageID": "m1"},
                },
            }
            yield {
                "id": "e3",
                "type": "message.updated",
                "properties": {"sessionID": "ses-oc-resume", "info": {"id": "m1", "role": "assistant"}},
            }
            yield {"id": "e4", "type": "session.idle", "properties": {"sessionID": "ses-oc-resume"}}

        def prompt_async(self, session_id: str, text: str):
            calls.append(f"prompt_async:{session_id}")
            return 204, {}

    monkeypatch.setattr(bridge, "OpenCodeServerClient", lambda **kw: _ResumeClient())
    for key, value in _run_attempt_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("RESUME_SESSION", "ses-oc-resume")
    monkeypatch.delenv("CODIFY_RESUME_SESSION", raising=False)
    _emit(tmp_path, "run.started", {"runtime_bundle_digest": "d" * 64})

    assert bridge._run_attempt() == 0
    assert calls[:3] == ["get_session:ses-oc-resume", "stream_established", "prompt_async:ses-oc-resume"]
    assert "create_session" not in calls
    result = json.loads((tmp_path / "harness-result.json").read_text(encoding="utf-8"))
    assert result["session_id"] == "ses-oc-resume"


# ── opencode.sh adapter shell ───────────────────────────────────────────────

def _source_adapter(script: str, env: dict[str, str]):
    return subprocess.run(
        ["bash", "-c", f'source "{ADAPTER}" && {script}'],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
    )


def test_opencode_verify_runtime_enforces_pinned_version(tmp_path):
    cli = tmp_path / "bin" / "opencode"
    cli.parent.mkdir()
    cli.write_text("#!/bin/sh\necho opencode 1.18.19\n", encoding="utf-8")
    cli.chmod(0o755)
    env = {
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_OPENCODE_BIN": str(cli),
        "CODIFY_HARNESS_CLI_BIN": str(cli),
        "ENTRYPOINT_LIB_DIR": str(REPO_ROOT / "deploy/worker-entrypoint"),
        "CODIFY_RUNTIME_DIR": str(tmp_path),
        "CODIFY_RUN_UID": "1000",
        "CODIFY_RUN_GID": "1000",
    }
    ok = _source_adapter("opencode_adapter_verify_runtime", env)
    assert ok.returncode == 0, ok.stderr
    # Out-of-baseline version is advisory: a sanitized warning, execution
    # continues (§11.2 Compatibility policy).
    cli2 = tmp_path / "opencode-bad"
    cli2.write_text("#!/bin/sh\necho opencode 9.9.9\n", encoding="utf-8")
    cli2.chmod(0o755)
    env2 = {**env, "CODIFY_OPENCODE_BIN": str(cli2), "CODIFY_HARNESS_CLI_BIN": str(cli2)}
    bad = _source_adapter("opencode_adapter_verify_runtime", env2)
    assert bad.returncode == 0, bad.stderr
    assert "WARNING" in bad.stderr
    assert "advisory" in bad.stderr


def test_opencode_prepare_config_writes_snapshot_endpoint(tmp_path):
    env = {
        "CODIFY_RUNTIME_DIR": str(tmp_path),
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_RUN_UID": "1000",
        "CODIFY_RUN_GID": "1000",
        "ANTHROPIC_MODEL": "deepseek-v4-flash",
        "OPENCODE_PORT": "8099",
        "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
        "ANTHROPIC_API_KEY": "fake-key",
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
    # Snapshot base URL wins, normalized to the /v1 root so @ai-sdk/anthropic
    # (which appends /messages) hits /v1/messages; credential referenced by env
    # name, never inlined.
    assert provider["options"]["baseURL"] == "https://api.deepseek.com/anthropic/v1"
    assert provider["options"]["apiKey"] == "{env:OPENCODE_SNAPSHOT_KEY}"
    assert "fake-key" not in config.read_text(encoding="utf-8")
    # OpenCode 1.18.19 config schema: models.<id>.provider must be an object
    # {id: <provider-id>}, not a bare string (ConfigInvalidError otherwise).
    model = provider["models"]["deepseek-v4-flash"]
    assert model["id"] == "deepseek-v4-flash"
    assert model["provider"] == {"id": "codify"}
    # A free loopback port was probed and a Task password generated.
    assert result.stdout.strip().isdigit()


@pytest.mark.parametrize(
    ("protocol", "model", "endpoint_url", "api_key", "expected_npm"),
    [
        (
            "openai_responses",
            "responses-model",
            "https://responses.example/v1",
            "responses-key",
            "@ai-sdk/openai",
        ),
        (
            "openai_chat_completions",
            "chat-model",
            "https://chat.example/v1",
            "chat-key",
            "@ai-sdk/openai-compatible",
        ),
    ],
)
def test_opencode_prepare_config_maps_openai_protocols(
    tmp_path, protocol, model, endpoint_url, api_key, expected_npm
):
    env = {
        "CODIFY_RUNTIME_DIR": str(tmp_path),
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_RUN_UID": "1000",
        "CODIFY_RUN_GID": "1000",
        "CODIFY_MODEL_PROTOCOL": protocol,
        "ANTHROPIC_MODEL": "wrong-anthropic-model",
        "ANTHROPIC_BASE_URL": "https://wrong-anthropic.example",
        "ANTHROPIC_API_KEY": "wrong-anthropic-key",
        "OPENAI_MODEL": model,
        "OPENAI_BASE_URL": endpoint_url,
        "OPENAI_API_KEY": api_key,
    }
    result = _source_adapter("opencode_adapter_prepare_config", env)
    assert result.returncode == 0, result.stderr
    provider = json.loads(
        (tmp_path / "opencode/opencode.json").read_text(encoding="utf-8")
    )["provider"]["codify"]
    assert provider["npm"] == expected_npm
    assert provider["options"]["baseURL"] == endpoint_url
    assert provider["options"]["apiKey"] == "{env:OPENCODE_SNAPSHOT_KEY}"
    assert api_key not in (tmp_path / "opencode/opencode.json").read_text(encoding="utf-8")
    assert provider["models"][model]["id"] == model


def test_opencode_prepare_config_normalizes_relay_root_to_v1(tmp_path):
    env = {
        "CODIFY_RUNTIME_DIR": str(tmp_path),
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_RUN_UID": "1000",
        "CODIFY_RUN_GID": "1000",
        "ANTHROPIC_MODEL": "ox-alpha-free",
        "ANTHROPIC_BASE_URL": "http://192.168.50.45:15721",
        "ANTHROPIC_API_KEY": "fake-key",
    }
    result = _source_adapter("opencode_adapter_prepare_config", env)
    assert result.returncode == 0, result.stderr
    content = json.loads(
        (tmp_path / "opencode" / "opencode.json").read_text(encoding="utf-8")
    )
    provider = content["provider"]["codify"]
    # Relay root normalized to /v1 so @ai-sdk/anthropic hits /v1/messages (200)
    # instead of /messages (404).
    assert provider["options"]["baseURL"] == "http://192.168.50.45:15721/v1"
    assert provider["options"]["apiKey"] == "{env:OPENCODE_SNAPSHOT_KEY}"


def test_opencode_prepare_config_keeps_existing_v1_endpoint(tmp_path):
    # G1 (code-review P2-1): @ai-sdk/anthropic appends /messages to
    # options.baseURL, so a config base that already ends in /v1 must be left
    # untouched — normalizing it again would double-hang as /v1/v1 (a 200 root
    # becomes a 404 and the probe fails). Two arms: trailing slash and bare /v1.
    env = {
        "CODIFY_RUNTIME_DIR": str(tmp_path),
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_RUN_UID": "1000",
        "CODIFY_RUN_GID": "1000",
        "ANTHROPIC_MODEL": "ox-alpha-free",
        "ANTHROPIC_BASE_URL": "http://192.168.50.45:15721/v1",
        "ANTHROPIC_API_KEY": "fake-key",
    }
    result = _source_adapter("opencode_adapter_prepare_config", env)
    assert result.returncode == 0, result.stderr
    content = json.loads(
        (tmp_path / "opencode" / "opencode.json").read_text(encoding="utf-8")
    )
    provider = content["provider"]["codify"]
    assert provider["options"]["baseURL"] == "http://192.168.50.45:15721/v1"
    assert provider["options"]["apiKey"] == "{env:OPENCODE_SNAPSHOT_KEY}"


def test_opencode_prepare_config_normalizes_v1_trailing_slash(tmp_path):
    # G1 sibling arm: a config base ending in /v1/ is stripped to /v1 by the
    # %/ suffix removal — /v1/v1 is never produced for either spelling.
    env = {
        "CODIFY_RUNTIME_DIR": str(tmp_path),
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_RUN_UID": "1000",
        "CODIFY_RUN_GID": "1000",
        "ANTHROPIC_MODEL": "ox-alpha-free",
        "ANTHROPIC_BASE_URL": "http://192.168.50.45:15721/v1/",
        "ANTHROPIC_API_KEY": "fake-key",
    }
    result = _source_adapter("opencode_adapter_prepare_config", env)
    assert result.returncode == 0, result.stderr
    content = json.loads(
        (tmp_path / "opencode" / "opencode.json").read_text(encoding="utf-8")
    )
    provider = content["provider"]["codify"]
    assert provider["options"]["baseURL"] == "http://192.168.50.45:15721/v1"
    assert provider["options"]["apiKey"] == "{env:OPENCODE_SNAPSHOT_KEY}"


def test_opencode_prepare_config_exports_transport_env_defaults(tmp_path):
    # P2: prepare_config default-exports the OpenCode transport/model identity
    # (server_http / opencode-server / its supported protocol) when the runner did not
    # inject it, so result_builder.v2_harness_block forms the correct V2 envelope.
    env = {
        "CODIFY_RUNTIME_DIR": str(tmp_path),
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_RUN_UID": "1000",
        "CODIFY_RUN_GID": "1000",
    }
    result = _source_adapter(
        "unset CODIFY_HARNESS_CONTROL_TRANSPORT_KIND "
        "CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL CODIFY_HARNESS_MODEL_PROTOCOLS || true; "
        "opencode_adapter_prepare_config && printf '%s|%s|%s' "
        '"$CODIFY_HARNESS_CONTROL_TRANSPORT_KIND" '
        '"$CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL" '
        '"$CODIFY_HARNESS_MODEL_PROTOCOLS"',
        env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        "server_http|opencode-server|anthropic_messages,openai_responses,openai_chat_completions"
    )


def test_opencode_prepare_config_isolates_project_and_user_config(tmp_path):
    env = {
        "CODIFY_RUNTIME_DIR": str(tmp_path),
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "HOME": "/untrusted/user-home",
        "XDG_CONFIG_HOME": "/untrusted/config",
        "XDG_DATA_HOME": "/untrusted/data",
        "XDG_CACHE_HOME": "/untrusted/cache",
        "XDG_STATE_HOME": "/untrusted/state",
    }
    result = _source_adapter(
        "opencode_adapter_prepare_config && printf '%s|%s|%s|%s|%s|%s|%s' "
        '"$HOME" "${XDG_CONFIG_HOME}" "${XDG_DATA_HOME}" '
        '"${XDG_CACHE_HOME}" "${XDG_STATE_HOME}" "${OPENCODE_CONFIG_DIR}" '
        '"${OPENCODE_DISABLE_PROJECT_CONFIG}"',
        env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        f"{tmp_path}/opencode/home|{tmp_path}/opencode/xdg-config|"
        f"{tmp_path}/opencode/xdg-data|{tmp_path}/opencode/xdg-cache|"
        f"{tmp_path}/opencode/xdg-state|{tmp_path}/opencode|true"
    )


def test_opencode_materialize_skills_uses_task_private_discoverable_root(tmp_path):
    skills_dir = tmp_path / "skill-scope" / ".claude" / "skills" / "codify-marker"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        "---\nname: codify-marker\ndescription: isolated marker\n---\n# Marker\n",
        encoding="utf-8",
    )
    cli = tmp_path / "bin" / "opencode"
    cli.parent.mkdir()
    cli.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = debug ] && [ \"$2\" = skill ]; then\n"
        "  printf '[{\"name\":\"codify-marker\",\"location\":\"%s/skills/codify-marker/SKILL.md\"}]\\n' \"$OPENCODE_CONFIG_DIR\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    cli.chmod(0o755)
    result = _source_adapter(
        "opencode_adapter_materialize_skills",
        {
            "CODIFY_RUNTIME_DIR": str(tmp_path),
            "CODIFY_TASK_SKILLS_DIR": str(tmp_path / "skill-scope"),
            "CODIFY_OPENCODE_BIN": str(cli),
        },
    )

    assert result.returncode == 0, result.stderr
    assert (
        tmp_path / "opencode/skills/codify-marker/SKILL.md"
    ).read_text(encoding="utf-8").startswith("---\nname: codify-marker")
    assert not (tmp_path / "opencode/skills/.claude/skills").exists()


# ── legacy/opencode-run.sh: isolated server process group cleanup ───────────

def _write_runner_process_group_fixtures(tmp_path: Path) -> Path:
    """Create a fake setsid/server/curl/bridge without opening a TCP port."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fixtures = {
        "setsid": """#!/usr/bin/env python3
import os
import sys
os.setsid()
os.execvp(sys.argv[1], sys.argv[1:])
""",
        "curl": "#!/bin/sh\nprintf '200'\n",
        "ps": """#!/usr/bin/env python3
import os
import sys
pid = int(sys.argv[-1])
print(os.getpgid(pid))
""",
        "opencode": """#!/bin/bash
printf '%s\\n' "$@" > "${OPENCODE_TEST_ARGS}"
{
    printf 'HOME=%s\\n' "$HOME"
    printf 'XDG_CONFIG_HOME=%s\\n' "$XDG_CONFIG_HOME"
    printf 'XDG_DATA_HOME=%s\\n' "$XDG_DATA_HOME"
    printf 'XDG_CACHE_HOME=%s\\n' "$XDG_CACHE_HOME"
    printf 'XDG_STATE_HOME=%s\\n' "$XDG_STATE_HOME"
    printf 'OPENCODE_CONFIG_DIR=%s\\n' "$OPENCODE_CONFIG_DIR"
    printf 'OPENCODE_DISABLE_PROJECT_CONFIG=%s\\n' "$OPENCODE_DISABLE_PROJECT_CONFIG"
    printf 'OPENCODE_DISABLE_EXTERNAL_SKILLS=%s\\n' "$OPENCODE_DISABLE_EXTERNAL_SKILLS"
    printf 'OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=%s\\n' "$OPENCODE_DISABLE_CLAUDE_CODE_SKILLS"
} > "${OPENCODE_TEST_ENV}"
(
    trap '' TERM
    while :; do sleep 1; done
) &
child=$!
printf '%s %s\\n' "$$" "$child" > "${OPENCODE_TEST_PIDS}"
while :; do sleep 1; done
""",
        "bridge": """#!/usr/bin/env python3
import os
import sys
import time
time.sleep(float(os.environ.get("OPENCODE_TEST_BRIDGE_SLEEP", "0")))
sys.exit(int(os.environ.get("OPENCODE_TEST_BRIDGE_RC", "0")))
""",
    }
    for name, contents in fixtures.items():
        path = bin_dir / name
        path.write_text(contents, encoding="utf-8")
        path.chmod(0o755)
    return bin_dir


def _proc_start_time(pid: int) -> str | None:
    """Linux start-time token prevents a recycled PID being mistaken for a child."""
    stat = Path(f"/proc/{pid}/stat")
    if not stat.exists():
        return None
    return stat.read_text(encoding="utf-8").split()[21]


def _wait_for_file(path: Path, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            raise AssertionError(process.stderr.read())
        time.sleep(0.05)
    raise AssertionError("fake OpenCode server did not publish parent/child PIDs")


def _finish_runner(process: subprocess.Popen[str], expected_returncode: int) -> None:
    """Wait for the runner and close its text pipes on every terminal path."""
    _stdout, stderr = process.communicate(timeout=8)
    assert process.returncode == expected_returncode, stderr


def _assert_process_gone(pid: int, start_time: str | None) -> None:
    current = _proc_start_time(pid)
    if current is not None:
        assert current != start_time, f"process {pid} survived cleanup"


def _start_legacy_runner(tmp_path: Path, *, bridge_sleep: str = "0") -> tuple[subprocess.Popen[str], tuple[int, int], tuple[str | None, str | None]]:
    bin_dir = _write_runner_process_group_fixtures(tmp_path)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("test", encoding="utf-8")
    pid_file = tmp_path / "server-pids"
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CODIFY_OPENCODE_BIN": str(bin_dir / "opencode"),
        "CODIFY_OPENCODE_BRIDGE": str(bin_dir / "bridge"),
        "CODIFY_RUNTIME_DIR": str(tmp_path / "runtime"),
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_OPENCODE_RAW_EVENT_JSONL": str(tmp_path / "raw.jsonl"),
        "CODIFY_OPENCODE_EVENT_TRANSLATOR": str(TRANSLATOR),
        "OPENCODE_PORT": "12345",
        "OPENCODE_SERVER_PASSWORD": "pw",
        "OPENCODE_TEST_PIDS": str(pid_file),
        "OPENCODE_TEST_ARGS": str(tmp_path / "server-args"),
        "OPENCODE_TEST_ENV": str(tmp_path / "server-env"),
        "OPENCODE_TEST_BRIDGE_SLEEP": bridge_sleep,
        "OPENCODE_SERVER_STOP_GRACE_SECONDS": "1",
        "PROMPT_FILE": str(prompt),
    }
    process = subprocess.Popen(
        ["bash", str(LEGACY_RUNNER)],
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # The real container runner is not its own background job. Make the
        # same topology explicit so the test setsid shim is never a PG leader
        # before it calls os.setsid().
        start_new_session=True,
    )
    _wait_for_file(pid_file, process)
    parent, child = (int(value) for value in pid_file.read_text(encoding="utf-8").split())
    assert os.getpgid(parent) == parent  # setsid established an isolated group
    return process, (parent, child), (_proc_start_time(parent), _proc_start_time(child))


def test_opencode_legacy_runner_reaps_server_process_group_after_success(tmp_path):
    process, pids, starts = _start_legacy_runner(tmp_path)
    assert (tmp_path / "server-args").read_text(encoding="utf-8").splitlines() == [
        "serve",
        "--pure",
        "--hostname",
        "127.0.0.1",
        "--port",
        "12345",
    ]
    server_env = (tmp_path / "server-env").read_text(encoding="utf-8")
    assert f"HOME={tmp_path}/runtime/opencode/home" in server_env
    assert f"XDG_CONFIG_HOME={tmp_path}/runtime/opencode/xdg-config" in server_env
    assert f"XDG_DATA_HOME={tmp_path}/runtime/opencode/xdg-data" in server_env
    assert f"XDG_CACHE_HOME={tmp_path}/runtime/opencode/xdg-cache" in server_env
    assert f"XDG_STATE_HOME={tmp_path}/runtime/opencode/xdg-state" in server_env
    assert f"OPENCODE_CONFIG_DIR={tmp_path}/runtime/opencode" in server_env
    assert "OPENCODE_DISABLE_PROJECT_CONFIG=true" in server_env
    assert "OPENCODE_DISABLE_EXTERNAL_SKILLS=1" in server_env
    assert "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1" in server_env
    _finish_runner(process, 0)
    for pid, start in zip(pids, starts):
        _assert_process_gone(pid, start)


def test_opencode_legacy_runner_reaps_ignoring_child_after_cancel(tmp_path):
    process, pids, starts = _start_legacy_runner(tmp_path, bridge_sleep="30")
    process.send_signal(signal.SIGTERM)
    _finish_runner(process, 143)
    for pid, start in zip(pids, starts):
        _assert_process_gone(pid, start)


def test_opencode_legacy_runner_timeout_signal_reaps_ignoring_child(tmp_path):
    process, pids, starts = _start_legacy_runner(tmp_path, bridge_sleep="30")
    # GNU timeout delivers TERM to its child; deliver the same timeout signal
    # directly to keep the regression portable on macOS CI hosts.
    process.send_signal(signal.SIGTERM)
    _finish_runner(process, 143)
    for pid, start in zip(pids, starts):
        _assert_process_gone(pid, start)
