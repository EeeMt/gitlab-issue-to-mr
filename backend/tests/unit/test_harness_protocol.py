from __future__ import annotations

from copy import deepcopy

import pytest

from app.core.harness_protocol import (
    CANONICAL_EVENT_SCHEMA,
    CANONICAL_RESULT_SCHEMA,
    CanonicalEventReplay,
    HarnessProtocolError,
    build_event,
    deterministic_event_id,
    normalize_usage,
    replay_events,
    validate_event,
    validate_result,
)


def _event(seq: int, event_type: str, payload: dict | None = None) -> dict:
    normalized_payload = payload or {}
    if event_type == "run.completed" and payload is None:
        normalized_payload = {"status": "completed", "success": True}
    elif event_type == "run.failed" and payload is None:
        normalized_payload = {
            "status": "failed",
            "success": False,
            "failure": {"kind": "engine_error"},
        }
    return build_event(
        attempt_id="task-7-attempt-1",
        seq=seq,
        task_id=7,
        harness_key="claude",
        adapter_version="1.0.0",
        cli_version="2.1.152",
        event_type=event_type,
        payload=normalized_payload,
        event_id=deterministic_event_id("task-7-attempt-1", seq),
        occurred_at=f"2026-08-01T00:00:{seq:02d}Z",
    )


def _complete_attempt() -> list[dict]:
    return [
        _event(1, "run.started"),
        _event(2, "model.resolved", {"model": "claude-test"}),
        _event(3, "harness.completed", {"session_id": "session-1"}),
        _event(4, "delivery.completed", {"commit_sha": "a" * 40}),
        _event(5, "worker.finalization", {"exit_code": 0}),
        _event(6, "run.completed", {"status": "completed", "success": True}),
    ]


@pytest.mark.parametrize(
    "field",
    [
        "schema",
        "event_id",
        "attempt_id",
        "seq",
        "occurred_at",
        "type",
        "task_id",
        "harness",
        "payload",
    ],
)
def test_event_requires_stable_envelope_fields(field: str):
    event = _event(1, "run.started")
    event.pop(field)
    with pytest.raises(HarnessProtocolError, match="missing canonical event fields"):
        validate_event(event)


def test_event_schema_is_exact():
    event = _event(1, "run.started")
    assert event["schema"] == CANONICAL_EVENT_SCHEMA
    event["schema"] = "codify.worker.event/v2"
    with pytest.raises(HarnessProtocolError, match="unsupported event schema"):
        validate_event(event)


def test_unknown_non_terminal_becomes_diagnostic_with_raw_reference():
    event = _event(1, "run.started")
    event["type"] = "claude.private_event"
    event["raw_ref"] = {"stream": "harness-events/claude.jsonl", "line": 3}
    normalized = validate_event(event)
    assert normalized["type"] == "diagnostic"
    assert normalized["payload"] == {
        "code": "unknown_event_type",
        "original_type": "claude.private_event",
        "raw_ref": {"stream": "harness-events/claude.jsonl", "line": 3},
    }


def test_unknown_task_terminal_is_rejected():
    event = _event(1, "run.started")
    event["type"] = "run.maybe_completed"
    with pytest.raises(HarnessProtocolError, match="unknown task terminal"):
        validate_event(event)


def test_run_failed_requires_failure_taxonomy():
    with pytest.raises(HarnessProtocolError, match="failure.kind"):
        _event(
            1,
            "run.failed",
            {"status": "failed", "success": False, "failure": {"kind": "mystery"}},
        )


@pytest.mark.parametrize("hidden_key", ["thinking", "chain_of_thought", "hidden_reasoning"])
def test_hidden_reasoning_fields_are_rejected_recursively(hidden_key: str):
    event = _event(1, "run.started")
    event["payload"] = {"nested": [{hidden_key: "not allowed"}]}
    with pytest.raises(HarnessProtocolError, match="hidden-reasoning"):
        validate_event(event)


def test_reasoning_summary_is_allowed():
    event = _event(1, "reasoning_summary.completed", {"text": "safe summary"})
    assert validate_event(event)["payload"]["text"] == "safe summary"


def test_usage_keeps_unknown_values_null_instead_of_zero():
    assert normalize_usage({}) == {
        "input_tokens": None,
        "cached_input_tokens": None,
        "output_tokens": None,
        "reasoning_tokens": None,
        "cost": None,
        "currency": None,
        "engine_fields": {},
    }


def test_usage_preserves_provider_fields():
    normalized = normalize_usage(
        {"input_tokens": 4, "cost": 0.2, "engine_fields": {"cache_creation": 2}}
    )
    assert normalized["input_tokens"] == 4
    assert normalized["output_tokens"] is None
    assert normalized["engine_fields"] == {"cache_creation": 2}


@pytest.mark.parametrize("bad_value", [-1, 1.5, True, "2"])
def test_usage_rejects_invalid_token_counts(bad_value):
    with pytest.raises(HarnessProtocolError, match="input_tokens"):
        normalize_usage({"input_tokens": bad_value})


def test_complete_attempt_replays_to_single_task_terminal():
    replay = replay_events(_complete_attempt())
    assert replay.terminal_type == "run.completed"
    assert replay.last_seq == 6


def test_same_event_cannot_be_ingested_twice():
    replay = CanonicalEventReplay()
    event = _event(1, "run.started")
    replay.ingest(event)
    with pytest.raises(HarnessProtocolError, match="duplicate event_id"):
        replay.ingest(event)


def test_sequence_gap_is_protocol_error():
    replay = CanonicalEventReplay()
    replay.ingest(_event(1, "run.started"))
    with pytest.raises(HarnessProtocolError, match="sequence gap") as exc:
        replay.ingest(_event(3, "harness.completed"))
    assert exc.value.code == "sequence_gap"


def test_harness_terminal_is_not_a_task_terminal():
    replay = CanonicalEventReplay()
    replay.ingest(_event(1, "run.started"))
    replay.ingest(_event(2, "harness.completed"))
    with pytest.raises(HarnessProtocolError, match="missing task terminal"):
        replay.finish()


def test_task_terminal_requires_worker_finalization():
    replay = CanonicalEventReplay()
    replay.ingest(_event(1, "run.started"))
    replay.ingest(_event(2, "harness.completed"))
    with pytest.raises(HarnessProtocolError, match="before worker.finalization"):
        replay.ingest(_event(3, "run.completed"))


def test_terminal_must_be_last_event():
    replay = replay_events(_complete_attempt())
    with pytest.raises(HarnessProtocolError, match="after task terminal"):
        replay.ingest(_event(7, "diagnostic"))


def test_only_task_terminal_may_follow_worker_finalization():
    replay = CanonicalEventReplay()
    replay.ingest(_event(1, "run.started"))
    replay.ingest(_event(2, "harness.completed"))
    replay.ingest(_event(3, "worker.finalization"))
    with pytest.raises(HarnessProtocolError, match="only the Task terminal"):
        replay.ingest(_event(4, "diagnostic"))


def test_cli_version_cannot_change_inside_attempt():
    replay = CanonicalEventReplay()
    replay.ingest(_event(1, "run.started"))
    changed = _event(2, "harness.completed")
    changed["harness"]["cli_version"] = "2.2.0"
    with pytest.raises(HarnessProtocolError, match="CLI version changed"):
        replay.ingest(changed)


def test_attempt_identity_cannot_change():
    replay = CanonicalEventReplay()
    replay.ingest(_event(1, "run.started"))
    changed = _event(2, "harness.completed")
    changed["attempt_id"] = "other-attempt"
    with pytest.raises(HarnessProtocolError, match="attempt_id changed"):
        replay.ingest(changed)


def test_dual_task_terminal_is_rejected_as_event_after_terminal():
    events = _complete_attempt()
    replay = replay_events(events)
    second = deepcopy(events[-1])
    second["seq"] = 7
    second["event_id"] = deterministic_event_id("task-7-attempt-1", 7)
    second["type"] = "run.failed"
    second["payload"] = {
        "status": "failed",
        "success": False,
        "failure": {"kind": "engine_error"},
    }
    with pytest.raises(HarnessProtocolError, match="after task terminal"):
        replay.ingest(second)


def test_canonical_result_requires_failure_taxonomy_and_normalized_usage():
    result = validate_result(
        {
            "schema": CANONICAL_RESULT_SCHEMA,
            "status": "failed",
            "success": False,
            "result": "",
            "harness_key": "claude",
            "adapter_version": "1.0.0",
            "cli_version": "2.1.152",
            "session_id": None,
            "model": None,
            "usage": {},
            "failure": {"kind": "engine_error", "message": "boom"},
            "capability_warnings": [],
        }
    )
    assert result["usage"]["cost"] is None


def test_successful_result_cannot_carry_failure():
    with pytest.raises(HarnessProtocolError, match="cannot include failure"):
        validate_result(
            {
                "schema": CANONICAL_RESULT_SCHEMA,
                "status": "completed",
                "success": True,
                "result": "ok",
                "harness_key": "claude",
                "adapter_version": "1.0.0",
                "cli_version": "2.1.152",
                "session_id": "s",
                "model": "m",
                "usage": {},
                "failure": {"kind": "engine_error"},
                "capability_warnings": [],
            }
        )
