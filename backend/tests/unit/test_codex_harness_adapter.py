"""Tests for the Codex event translator."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from app.core.harness_protocol import replay_events, validate_event, validate_result

REPO_ROOT = Path(__file__).resolve().parents[3]
HARNESS_DIR = REPO_ROOT / "deploy/worker-entrypoint/harness"
TRANSLATOR = HARNESS_DIR / "adapters/codex_events.py"
EVENT_WRITER = HARNESS_DIR / "events.py"


def _environment(runtime_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        "CODIFY_RUNTIME_DIR": str(runtime_dir),
        "CODIFY_ATTEMPT_ID": "task-9-attempt-1",
        "TASK_ID": "9",
        "CODIFY_HARNESS_KEY": "codex",
        "CODIFY_ADAPTER_VERSION": "1.0.0",
        "CODIFY_CLI_VERSION": "0.146.0-alpha.3.1",
        "CODIFY_CANONICAL_EVENT_WRITER": str(EVENT_WRITER),
        "CODIFY_HARNESS_RESULT_FILE": str(runtime_dir / "harness-result.json"),
        "ANTHROPIC_MODEL": "deepseek-v4-flash",
    }


def _emit(runtime_dir: Path, event_type: str, payload: dict | None = None) -> None:
    subprocess.run(
        ["python3", str(EVENT_WRITER), event_type, "--payload", json.dumps(payload or {})],
        check=True,
        env=_environment(runtime_dir),
        capture_output=True,
        text=True,
    )


def _translate(runtime_dir: Path, record: dict) -> None:
    raw_file = runtime_dir / "harness-events/codex.jsonl"
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["python3", str(TRANSLATOR), "--raw-file", str(raw_file)],
        input=json.dumps(record),
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


def test_codex_stream_maps_to_canonical_events(tmp_path):
    _emit(tmp_path, "run.started", {"runtime_bundle_digest": "d" * 64})
    _translate(
        tmp_path,
        {"thread_id": "6ad6e4f5-6205-8e2a-9b3c-1a2b3c4d5e6f", "type": "thread.started"},
    )
    _translate(
        tmp_path,
        {"type": "item.started", "item": {
            "id": "item_0", "type": "command_execution", "command": "printf OK"}},
    )
    _translate(
        tmp_path,
        {"type": "item.completed", "item": {
            "id": "item_0", "type": "command_execution",
            "aggregated_output": "OK", "exit_code": 0}},
    )
    _translate(
        tmp_path,
        {"type": "item.completed", "item": {"id": "item_1", "type": "agent_message", "text": "done"}},
    )
    _translate(
        tmp_path,
        {"type": "turn.completed", "usage": {
            "input_tokens": 10, "output_tokens": 4, "reasoning_output_tokens": 2}},
    )
    _emit(tmp_path, "delivery.started")
    _emit(tmp_path, "delivery.completed")
    _emit(tmp_path, "worker.finalization", {"exit_code": 0})
    _emit(tmp_path, "run.completed", {"status": "completed", "success": True})

    events = _events(tmp_path)
    by_type = [event["type"] for event in events]
    assert by_type == [
        "run.started",
        "model.resolved",
        "tool.started",
        "tool.completed",
        "message.completed",
        "usage.final",
        "harness.completed",
        "delivery.started",
        "delivery.completed",
        "worker.finalization",
        "run.completed",
    ]
    model_resolved = events[1]
    assert model_resolved["payload"]["session_id"] == "6ad6e4f5-6205-8e2a-9b3c-1a2b3c4d5e6f"
    tool_completed = events[3]["payload"]
    assert tool_completed["exit_code"] == 0
    usage = events[5]["payload"]["usage"]
    assert usage["reasoning_tokens"] == 2
    replay = replay_events(events)
    assert replay.terminal_type == "run.completed"


def test_codex_raw_stream_is_sanitized_and_persisted(tmp_path):
    _emit(tmp_path, "run.started", {"runtime_bundle_digest": "d" * 64})
    _translate(
        tmp_path,
        {"type": "item.completed", "item": {
            "id": "item_0", "type": "command_execution",
            "command": "echo sk-ant-secret1234567890", "exit_code": 0}},
    )
    raw = (tmp_path / "harness-events/codex.jsonl").read_text(encoding="utf-8")
    assert "sk-ant-secret1234567890" not in raw
    assert "ANTHROPIC_API_KEY" in raw or "<OPENAI_API_KEY>" in raw
