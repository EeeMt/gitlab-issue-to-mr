from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from app.core.harness_protocol import replay_events, validate_event, validate_result

REPO_ROOT = Path(__file__).resolve().parents[3]
HARNESS_DIR = REPO_ROOT / "deploy/worker-entrypoint/harness"
TRANSLATOR = HARNESS_DIR / "adapters/claude_events.py"
EVENT_WRITER = HARNESS_DIR / "events.py"
FIXTURE_ROOT = REPO_ROOT / "backend/tests/fixtures/harness_events/claude"
FORBIDDEN_CANONICAL_KEYS = {
    "subtype",
    "thread_id",
    "turn_id",
    "item_id",
    "raw_type",
    "raw_subtype",
    "thinking",
    "chain_of_thought",
    "hidden_reasoning",
}


def _environment(runtime_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        "CODIFY_RUNTIME_DIR": str(runtime_dir),
        "CODIFY_ATTEMPT_ID": "task-9-attempt-1",
        "TASK_ID": "9",
        "CODIFY_HARNESS_KEY": "claude",
        "CODIFY_ADAPTER_VERSION": "1.0.0",
        "CODIFY_CLI_VERSION": "2.1.152",
        "CODIFY_CANONICAL_EVENT_WRITER": str(EVENT_WRITER),
        "CODIFY_HARNESS_RESULT_FILE": str(runtime_dir / "harness-result.json"),
        "ANTHROPIC_MODEL": "claude-probe",
    }


def _emit(runtime_dir: Path, event_type: str, payload: dict | None = None) -> None:
    subprocess.run(
        [
            "python3",
            str(EVENT_WRITER),
            event_type,
            "--payload",
            json.dumps(payload or {}),
        ],
        check=True,
        env=_environment(runtime_dir),
        capture_output=True,
        text=True,
    )


def _translate(runtime_dir: Path, record: dict) -> None:
    raw_file = runtime_dir / "harness-events/claude.jsonl"
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


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def test_adapter_metadata_declares_contract_and_capabilities(tmp_path):
    command = f'''
set -e
CODIFY_RUNTIME_DIR={tmp_path!s}
ENTRYPOINT_LIB_DIR={REPO_ROOT / "deploy/worker-entrypoint"!s}
CODIFY_ORCHESTRATION_DIR={REPO_ROOT / "deploy"!s}
source "$ENTRYPOINT_LIB_DIR/harness/common.sh"
source "$ENTRYPOINT_LIB_DIR/harness/adapters/claude.sh"
claude_adapter_metadata
'''
    result = subprocess.run(["bash", "-c", command], check=True, capture_output=True, text=True)
    metadata = json.loads(result.stdout)
    assert metadata["key"] == "claude"
    assert metadata["contract_version"] == "codify.worker.harness/v1"
    assert metadata["event_schema"] == "codify.worker.event/v1"
    assert metadata["capabilities"]["resume"] is True
    assert metadata["capabilities"]["run_text"] is True
    assert metadata["capabilities"]["codegraph"] is True


def test_adapter_exposes_every_required_contract_operation(tmp_path):
    command = f'''
set -e
CODIFY_RUNTIME_DIR={tmp_path!s}
ENTRYPOINT_LIB_DIR={REPO_ROOT / "deploy/worker-entrypoint"!s}
CODIFY_ORCHESTRATION_DIR={REPO_ROOT / "deploy"!s}
source "$ENTRYPOINT_LIB_DIR/harness/common.sh"
source "$ENTRYPOINT_LIB_DIR/harness/adapters/claude.sh"
for operation in metadata verify_runtime detect_capabilities prepare_config build_command materialize_skills stream_events normalize_result terminate; do
    declare -F "adapter_${{operation}}" >/dev/null
done
adapter_detect_capabilities
'''
    result = subprocess.run(["bash", "-c", command], check=True, capture_output=True, text=True)
    capabilities = json.loads(result.stdout)
    assert capabilities["resume"] is True
    assert capabilities["run_text"] is True


def test_translator_builds_complete_canonical_attempt_and_result(tmp_path):
    _emit(tmp_path, "run.started", {"runtime_bundle_digest": "d" * 64})
    _translate(
        tmp_path,
        {"type": "system", "subtype": "init", "model": "claude-probe", "session_id": "s1"},
    )
    _translate(
        tmp_path,
        {
            "type": "assistant",
            "message": {
                "id": "m1",
                "content": [
                    {"type": "text", "text": "done"},
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {"path": "a"}},
                ],
            },
        },
    )
    _translate(
        tmp_path,
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "ok", "is_error": False}
                ]
            },
        },
    )
    _translate(
        tmp_path,
        {
            "type": "result",
            "subtype": "success",
            "result": "complete",
            "session_id": "s1",
            "total_cost_usd": 0.01,
            "usage": {"input_tokens": 10, "output_tokens": 4},
        },
    )
    _emit(tmp_path, "delivery.started")
    _emit(tmp_path, "delivery.completed")
    _emit(tmp_path, "worker.finalization", {"exit_code": 0})
    _emit(tmp_path, "run.completed", {"status": "completed", "success": True})

    events = _events(tmp_path)
    replay = replay_events(events)
    assert replay.terminal_type == "run.completed"
    assert [event["type"] for event in events] == [
        "run.started",
        "model.resolved",
        "message.completed",
        "tool.started",
        "tool.completed",
        "usage.final",
        "harness.completed",
        "delivery.started",
        "delivery.completed",
        "worker.finalization",
        "run.completed",
    ]
    result = validate_result(json.loads((tmp_path / "harness-result.json").read_text()))
    assert result["success"] is True
    assert result["session_id"] == "s1"
    assert result["usage"]["reasoning_tokens"] is None


def test_translator_omits_hidden_reasoning_and_sanitizes_raw_archive(tmp_path):
    _emit(tmp_path, "run.started")
    _translate(
        tmp_path,
        {
            "type": "assistant",
            "message": {
                "id": "019fbd0c-f440-7391-9a70-2a25b7e025ec",
                "content": [
                    {
                        "type": "thinking",
                        "thinking": "secret chain",
                        "signature": "private reasoning signature",
                    },
                    {
                        "id": "call_00_yS27ASV8amijQfGFk4Yl8246",
                        "type": "text",
                        "text": (
                            "Bearer abcdefghijklmnop /Users/alice/repo "
                            "Cookie=sessionsecret http://git.internal/repo "
                            "/private/tmp/codify-harness-workspace.0m5kUT"
                        ),
                    },
                ]
            },
        },
    )
    raw = (tmp_path / "harness-events/claude.jsonl").read_text()
    assert "secret chain" not in raw
    assert "private reasoning signature" not in raw
    assert "019fbd0c" not in raw
    assert "yS27ASV8" not in raw
    assert "0m5kUT" not in raw
    assert "<HIDDEN_REASONING_OMITTED>" in raw
    assert "<REDACTED_SIGNATURE>" in raw
    assert "Bearer abcdefghijklmnop" not in raw
    assert "/Users/alice" not in raw
    assert "sessionsecret" not in raw
    assert "git.internal" not in raw
    canonical = json.dumps(_events(tmp_path), ensure_ascii=False)
    assert "secret chain" not in canonical
    assert "hidden_reasoning_omitted" in canonical


def test_translator_maps_provider_retry_without_raw_subtype(tmp_path):
    _emit(tmp_path, "run.started")
    _translate(
        tmp_path,
        {
            "type": "system",
            "subtype": "api_retry",
            "attempt": 2,
            "max_retries": 10,
            "error": "authentication_failed",
            "error_status": 401,
            "retry_delay_ms": 1200,
        },
    )
    event = _events(tmp_path)[-1]
    assert event["type"] == "provider.retry"
    assert event["payload"] == {
        "attempt": 2,
        "max_attempts": 10,
        "failure_kind": "authentication_error",
        "status_code": 401,
        "retry_delay_ms": 1200,
    }
    assert "subtype" not in set(_walk_keys(event))


@pytest.mark.parametrize(
    "scenario_dir",
    sorted(path for path in FIXTURE_ROOT.iterdir() if path.is_dir()),
    ids=lambda path: path.name,
)
def test_real_claude_fixture_stream_translates_to_safe_canonical_events(
    tmp_path,
    scenario_dir,
):
    runtime_dir = tmp_path / scenario_dir.name
    runtime_dir.mkdir()
    _emit(runtime_dir, "run.started")
    raw_records = [
        json.loads(line)
        for line in (scenario_dir / "stdout.jsonl").read_text().splitlines()
        if line.strip()
    ]
    for record in raw_records:
        _translate(runtime_dir, record)

    translated = _events(runtime_dir)
    for event in translated:
        validate_event(event)
    assert not (FORBIDDEN_CANONICAL_KEYS & set(_walk_keys(translated)))

    archived = (runtime_dir / "harness-events/claude.jsonl").read_text()
    assert len(archived.splitlines()) == len(raw_records)
    assert "<REDACTED_REASONING>" not in archived
    assert '"signature":"<REDACTED_SIGNATURE>"' in archived or not any(
        "signature" in json.dumps(record) for record in raw_records
    )

    retry_count = sum(record.get("subtype") == "api_retry" for record in raw_records)
    assert sum(event["type"] == "provider.retry" for event in translated) == retry_count

    expected = [
        json.loads(line)
        for line in (scenario_dir / "expected-canonical.jsonl").read_text().splitlines()
    ]

    def semantic(event):
        return {
            "type": event["type"],
            "payload": event["payload"],
            "raw_ref": event.get("raw_ref"),
        }

    assert [semantic(event) for event in translated] == [
        semantic(event) for event in expected[: len(translated)]
    ]

    result_records = [record for record in raw_records if record.get("type") == "result"]
    if result_records:
        expected_terminal = (
            "harness.completed"
            if result_records[-1].get("subtype") == "success"
            and result_records[-1].get("is_error") is not True
            else "harness.failed"
        )
        assert translated[-1]["type"] == expected_terminal
        validate_result(json.loads((runtime_dir / "harness-result.json").read_text()))


def test_unknown_raw_event_is_non_terminal_diagnostic(tmp_path):
    _emit(tmp_path, "run.started")
    _translate(tmp_path, {"type": "future_claude_event", "payload": {"x": 1}})
    event = _events(tmp_path)[-1]
    assert event["type"] == "diagnostic"
    assert event["payload"]["code"] == "unknown_raw_event"
    assert "raw_type" not in event["payload"]


def test_translator_records_plain_text_cli_error_with_text(tmp_path):
    _emit(tmp_path, "run.started")
    raw_file = tmp_path / "harness-events/claude.jsonl"
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["python3", str(TRANSLATOR), "--raw-file", str(raw_file)],
        input=(
            "--dangerously-skip-permissions cannot be used "
            "with root/sudo privileges for security reasons"
        ),
        check=True,
        env=_environment(tmp_path),
        capture_output=True,
        text=True,
    )
    event = _events(tmp_path)[-1]
    assert event["type"] == "diagnostic"
    assert event["payload"]["code"] == "non_json_raw_line"
    assert event["payload"]["text"] == (
        "--dangerously-skip-permissions cannot be used "
        "with root/sudo privileges for security reasons"
    )


def test_translator_classifies_authentication_failure(tmp_path):
    _emit(tmp_path, "run.started")
    _translate(
        tmp_path,
        {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "result": "Authentication failed with 401",
            "usage": {},
        },
    )
    result = validate_result(json.loads((tmp_path / "harness-result.json").read_text()))
    assert result["status"] == "failed"
    assert result["failure"]["kind"] == "authentication_error"
    assert _events(tmp_path)[-1]["payload"]["failure"]["kind"] == "authentication_error"


def test_event_writer_rejects_non_terminal_after_worker_finalization(tmp_path):
    _emit(tmp_path, "run.started")
    _emit(tmp_path, "harness.completed")
    _emit(tmp_path, "worker.finalization", {"exit_code": 0})
    result = subprocess.run(
        ["python3", str(EVENT_WRITER), "diagnostic", "--payload", '{}'],
        check=False,
        env=_environment(tmp_path),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "only the Task terminal" in result.stderr


def test_runner_initialization_failure_still_emits_complete_failed_attempt(tmp_path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "event.jsonl").touch()
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("probe")
    environment = {
        **_environment(runtime_dir),
        "ENTRYPOINT_LIB_DIR": str(REPO_ROOT / "deploy/worker-entrypoint"),
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_HARNESS_KEY": "missing-adapter",
        "CODIFY_ADAPTER_VERSION": "1.0.0",
        "CODIFY_CLI_VERSION": "unknown",
    }
    command = f'''
set -e
source "$ENTRYPOINT_LIB_DIR/harness/common.sh"
source "$ENTRYPOINT_LIB_DIR/harness/runner.sh"
set +e
codify_harness_run {prompt!s} {tmp_path / "result.json"!s}
exit_code=$?
set -e
codify_harness_finalize_attempt "$exit_code"
'''
    subprocess.run(["bash", "-c", command], env=environment, check=True)
    events = _events(runtime_dir)
    replay = replay_events(events)
    assert replay.terminal_type == "run.failed"
    assert events[1]["payload"]["failure"]["kind"] == "configuration_error"
    result = validate_result(json.loads((runtime_dir / "harness-result.json").read_text()))
    assert result["failure"]["kind"] == "configuration_error"


def test_runner_propagates_run_started_write_failure(tmp_path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "event.jsonl").touch()
    orchestration_dir = tmp_path / "orchestration"
    adapter_dir = orchestration_dir / "worker-entrypoint/harness/adapters"
    adapter_dir.mkdir(parents=True)
    command_path = orchestration_dir / "fake-harness"
    command_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    command_path.chmod(0o755)
    (adapter_dir / "test.sh").write_text(
        """
adapter_metadata() { printf '%s\\n' '{"adapter_version":"1.0.0"}'; }
adapter_verify_runtime() { return 0; }
adapter_detect_capabilities() { printf '%s\\n' '{}'; }
adapter_prepare_config() { return 0; }
adapter_build_command() { printf '%s\\n' "${CODIFY_ORCHESTRATION_DIR}/fake-harness"; }
adapter_materialize_skills() { return 0; }
adapter_stream_events() { return 0; }
adapter_normalize_result() { return 0; }
adapter_terminate() { return 0; }
adapter_run() { return 0; }
""",
        encoding="utf-8",
    )
    environment = {
        **_environment(runtime_dir),
        "ENTRYPOINT_LIB_DIR": str(REPO_ROOT / "deploy/worker-entrypoint"),
        "CODIFY_ORCHESTRATION_DIR": str(orchestration_dir),
        "CODIFY_HARNESS_KEY": "test",
        "CODIFY_ADAPTER_VERSION": "1.0.0",
    }
    command = """
source "$ENTRYPOINT_LIB_DIR/harness/runner.sh"
codify_emit_event() { return 73; }
codify_harness_initialize
"""
    result = subprocess.run(
        ["bash", "-c", command],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "Canonical attempt initialized" not in result.stdout


@pytest.mark.parametrize(
    ("failure_kind", "exit_code", "expected_kind", "expected_status"),
    [
        ("authentication_error", 1, "authentication_error", "failed"),
        ("rate_limited", 1, "rate_limited", "failed"),
        ("sandbox_error", 1, "sandbox_error", "failed"),
        ("protocol_error", 1, "protocol_error", "protocol_error"),
        ("engine_error", 143, "cancelled", "cancelled"),
        ("engine_error", 124, "timeout", "failed"),
    ],
)
def test_finalizer_preserves_adapter_failure_taxonomy(
    tmp_path,
    failure_kind,
    exit_code,
    expected_kind,
    expected_status,
):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "event.jsonl").touch()
    _emit(runtime_dir, "run.started")
    _emit(
        runtime_dir,
        "harness.failed",
        {"failure": {"kind": failure_kind, "message": "normalized failure"}},
    )
    environment = {
        **_environment(runtime_dir),
        "ENTRYPOINT_LIB_DIR": str(REPO_ROOT / "deploy/worker-entrypoint"),
        "CODIFY_HARNESS_TERMINAL_SEEN": "1",
    }
    command = f"""
source "$ENTRYPOINT_LIB_DIR/harness/common.sh"
CODIFY_HARNESS_TERMINAL_SEEN=1
codify_harness_finalize_attempt {exit_code}
"""
    subprocess.run(["bash", "-c", command], env=environment, check=True)
    events = _events(runtime_dir)
    replay = replay_events(events)
    assert replay.terminal_type == "run.failed"
    terminal = events[-1]
    assert terminal["payload"]["failure"]["kind"] == expected_kind
    assert terminal["payload"]["status"] == expected_status
    assert terminal["payload"]["failure"]["message"] == "normalized failure"
