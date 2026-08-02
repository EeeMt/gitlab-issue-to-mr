from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from app.core.harness_protocol import (
    CanonicalEventReplay,
    HarnessProtocolError,
    build_event,
    replay_events,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPO_ROOT / "backend" / "tests" / "fixtures" / "harness_events"
SANITIZER = REPO_ROOT / "scripts" / "harness-probes" / "sanitize_fixture.py"
PROBE = REPO_ROOT / "scripts" / "harness-probes" / "run-probe.sh"
CODEX_FIXTURE_MAPPER = REPO_ROOT / "scripts" / "harness-probes" / "codex_fixture_mapper.py"
EXPECTED_FILES = {
    "metadata.json",
    "stdout.jsonl",
    "stderr.log",
    "process.json",
    "expected-canonical.jsonl",
}
REQUIRED_REAL_SCENARIOS = {
    "success",
    "success_no_changes",
    "tool_success",
    "tool_failure",
    "new_session",
    "resume",
    "invalid_session",
    "authentication_failure",
    "rate_limited",
    "network_interruption",
    "timeout",
    "sigterm",
    "sigkill",
    "cancelled",
    "context_compaction",
    "usage_model",
}
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


def _scenario_directories() -> list[Path]:
    return sorted(
        path
        for harness in ("claude", "codex")
        for path in (FIXTURE_ROOT / harness).iterdir()
        if path.is_dir()
    )


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def test_required_real_probe_matrix_is_complete():
    for harness in ("claude", "codex"):
        actual = {path.name for path in (FIXTURE_ROOT / harness).iterdir() if path.is_dir()}
        assert actual == REQUIRED_REAL_SCENARIOS


@pytest.mark.parametrize("scenario_dir", _scenario_directories(), ids=lambda path: str(path.relative_to(FIXTURE_ROOT)))
def test_fixture_pair_is_sanitized_and_replays_offline(scenario_dir: Path, tmp_path: Path):
    assert {path.name for path in scenario_dir.iterdir() if path.is_file()} == EXPECTED_FILES
    metadata = json.loads((scenario_dir / "metadata.json").read_text())
    assert metadata["fixture_schema"] == "codify.harness.fixture/v1"
    assert metadata["harness"] == scenario_dir.parent.name
    assert metadata["scenario"] == scenario_dir.name
    assert metadata["collection_state"] in {
        "synthetic-offline-contract-sample",
        "sanitized-reviewed-real-probe",
    }
    assert len(metadata["binary_digest"]) == 64
    assert metadata["expected_harness_result"] in {"harness.completed", "harness.failed"}
    assert metadata["expected_task_result"] in {"run.completed", "run.failed"}
    assert metadata["sanitized_stdout_sha256"] == hashlib.sha256(
        (scenario_dir / "stdout.jsonl").read_bytes()
    ).hexdigest()

    if os.getenv("CODIFY_REQUIRE_REAL_HARNESS_FIXTURES") == "1":
        assert metadata["collection_state"] == "sanitized-reviewed-real-probe"

    for fixture_file in scenario_dir.iterdir():
        if fixture_file.is_file():
            result = subprocess.run(
                [str(SANITIZER), "--check", str(fixture_file)],
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, result.stderr

    sanitized = tmp_path / "stdout.jsonl"
    second = tmp_path / "stdout-again.jsonl"
    subprocess.run(
        [str(SANITIZER), str(scenario_dir / "stdout.jsonl"), str(sanitized)],
        check=True,
    )
    subprocess.run([str(SANITIZER), str(sanitized), str(second)], check=True)
    assert sanitized.read_bytes() == second.read_bytes()

    canonical = _jsonl(scenario_dir / "expected-canonical.jsonl")
    raw_line_count = len((scenario_dir / "stdout.jsonl").read_text().splitlines())
    raw_refs = [event["raw_ref"]["line"] for event in canonical if event.get("raw_ref")]
    assert raw_refs == sorted(raw_refs)
    assert all(1 <= line <= raw_line_count for line in raw_refs)
    replay = replay_events(canonical)
    assert replay.harness_key == metadata["harness"]
    assert replay.terminal_type == metadata["expected_task_result"]
    assert metadata["expected_harness_result"] in {event["type"] for event in canonical}
    assert not (FORBIDDEN_CANONICAL_KEYS & set(_walk_keys(canonical)))
    if metadata["harness"] == "codex":
        result = subprocess.run(
            [str(CODEX_FIXTURE_MAPPER), "--check", str(scenario_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_probe_runner_isolated_home_and_records_process_group(tmp_path: Path):
    output = tmp_path / "probe"
    result = subprocess.run(
        [
            str(PROBE),
            "--harness",
            "fake",
            "--scenario",
            "success",
            "--output-dir",
            str(output),
            "--version-command",
            'printf "fake 1.0\\n"',
            "--timeout",
            "5",
            "--",
            "bash",
            "-c",
            'printf \'{"type":"result","home":"%s"}\\n\' "$HOME"',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    process = json.loads((output / "process.json").read_text())
    raw = json.loads((output / "stdout.jsonl").read_text())
    assert process["pid"] == process["pgid"]
    assert process["timed_out"] is False
    assert "codify-harness-probe." in raw["home"]
    assert raw["home"] != str(Path.home())


def test_probe_runner_terminates_the_process_group_on_timeout(tmp_path: Path):
    output = tmp_path / "timeout"
    result = subprocess.run(
        [
            str(PROBE),
            "--harness",
            "fake",
            "--scenario",
            "timeout",
            "--output-dir",
            str(output),
            "--version-command",
            'printf "fake 1.0\\n"',
            "--timeout",
            "1",
            "--grace",
            "1",
            "--",
            "bash",
            "-c",
            'trap "" TERM; sleep 30 & wait',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    process = json.loads((output / "process.json").read_text())
    assert result.returncode == 137
    assert process["timed_out"] is True
    assert process["term_sent"] is True
    assert process["kill_sent"] is True


def test_sanitizer_removes_tokens_paths_private_urls_and_is_idempotent(tmp_path: Path):
    source = tmp_path / "raw.log"
    first = tmp_path / "first.log"
    second = tmp_path / "second.log"
    source.write_text(
        "glpat-abcdefghijk sk-ant-abcdefghijk sk-proj-abcdefghijklmnop "
        "Bearer abcdefghijk Cookie=sessionvalue /Users/operator/repo "
        "http://git.internal/private\n"
    )
    subprocess.run([str(SANITIZER), str(source), str(first)], check=True)
    subprocess.run([str(SANITIZER), str(first), str(second)], check=True)
    assert first.read_bytes() == second.read_bytes()
    assert "operator" not in first.read_text()
    assert "git.internal" not in first.read_text()
    assert subprocess.run([str(SANITIZER), "--check", str(first)], check=False).returncode == 0


def test_sanitizer_redacts_reasoning_and_stabilizes_probe_correlation(tmp_path: Path):
    source = tmp_path / "raw.jsonl"
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    source.write_text(
        json.dumps(
            {
                "session_id": "4e033cfd-68b6-4c8a-b509-d3ebfcd34d59",
                "thread_id": "019fbd0c-f440-7391-9a70-2a25b7e025ec",
                "cwd": "/private/tmp/codify-harness-workspace.0m5kUT",
                "memory_path": (
                    "/var/folders/aa/probe/codify-harness-probe.vbnfAt/.claude/projects/"
                    "-private-tmp-codify-harness-workspace-0m5kUT/memory"
                ),
                "content": [
                    {
                        "thinking": "private chain of thought",
                        "signature": "private-signature",
                        "tool_use_id": "call_00_yS27ASV8amijQfGFk4Yl8246",
                    }
                ],
            }
        )
        + "\n"
    )
    subprocess.run([str(SANITIZER), str(source), str(first)], check=True)
    subprocess.run([str(SANITIZER), str(first), str(second)], check=True)
    sanitized = first.read_text()
    assert first.read_bytes() == second.read_bytes()
    assert "private chain of thought" not in sanitized
    assert "private-signature" not in sanitized
    assert "4e033cfd" not in sanitized
    assert "019fbd0c" not in sanitized
    assert "0m5kUT" not in sanitized
    assert "codify-harness-workspace-" not in sanitized
    assert "yS27ASV8" not in sanitized
    assert "<REDACTED_REASONING>" in sanitized
    assert "<REDACTED_SIGNATURE>" in sanitized
    assert "<UUID:" in sanitized
    assert "<TOOL_ID:" in sanitized
    assert subprocess.run([str(SANITIZER), "--check", str(first)], check=False).returncode == 0


def _event(seq: int, event_type: str, payload: dict | None = None) -> dict:
    if payload is None and event_type == "run.completed":
        payload = {"status": "completed", "success": True}
    if payload is None and event_type == "run.failed":
        payload = {
            "status": "failed",
            "success": False,
            "failure": {"kind": "engine_error"},
        }
    return build_event(
        attempt_id="negative-attempt",
        seq=seq,
        task_id=9,
        harness_key="fake",
        adapter_version="1.0.0",
        cli_version="1.0.0",
        event_type=event_type,
        payload=payload or {},
        event_id=f"negative-event-{seq}",
        occurred_at=f"2026-08-01T00:00:{seq:02d}Z",
    )


@pytest.mark.parametrize(
    ("events", "message"),
    [
        ([_event(1, "run.started"), _event(2, "harness.completed")], "missing task terminal"),
        ([_event(1, "run.started"), _event(3, "harness.completed")], "sequence gap"),
        ([_event(1, "run.started"), _event(2, "worker.finalization")], "before harness terminal"),
    ],
)
def test_incomplete_fixture_replay_fails_closed(events: list[dict], message: str):
    with pytest.raises(HarnessProtocolError, match=message):
        replay_events(events)


def test_duplicate_and_after_terminal_records_fail_closed():
    replay = CanonicalEventReplay()
    sequence = [
        _event(1, "run.started"),
        _event(2, "harness.completed"),
        _event(3, "worker.finalization"),
        _event(4, "run.completed"),
    ]
    for event in sequence:
        replay.ingest(event)
    with pytest.raises(HarnessProtocolError, match="after task terminal"):
        replay.ingest(_event(5, "diagnostic"))
