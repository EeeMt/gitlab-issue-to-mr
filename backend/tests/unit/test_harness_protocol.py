from __future__ import annotations

from copy import deepcopy

import pytest

from app.core.harness_protocol import (
    CANONICAL_EVENT_SCHEMA,
    CANONICAL_EVENT_SCHEMA_V2,
    CANONICAL_RESULT_SCHEMA,
    COMMAND_SCHEMA_V2,
    MAX_COMMAND_TEXT_UTF16_CODE_UNITS,
    RUNTIME_MANIFEST_SCHEMA_V2,
    CanonicalEventReplay,
    HarnessProtocolError,
    build_event,
    command_payload_digest,
    command_text_utf16_code_units,
    deterministic_event_id,
    normalize_usage,
    replay_events,
    validate_command,
    validate_event,
    validate_event_by_schema,
    validate_event_v2,
    validate_manifest,
    validate_result,
    validate_result_v2,
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


# ── V2 superset (open-harness-v2-schemas.md) ─────────────────────────────────


def _v2_event(seq: int, event_type: str, payload: dict | None = None) -> dict:
    normalized_payload = payload or {}
    if event_type == "run.completed" and payload is None:
        normalized_payload = {"status": "completed", "success": True}
    return {
        "schema": CANONICAL_EVENT_SCHEMA_V2,
        "event_id": deterministic_event_id("v2-attempt-1", seq),
        "attempt_id": "v2-attempt-1",
        "seq": seq,
        "occurred_at": f"2026-08-01T00:00:{seq:02d}Z",
        "type": event_type,
        "task_id": 7,
        "harness": {
            "key": "pi",
            "adapter_version": "2.0.0",
            "cli_version": "0.84.2",
            "control_transport": {"kind": "rpc_stdio", "protocol": "pi-rpc"},
            "model_protocols": ["anthropic_messages"],
        },
        "payload": normalized_payload,
    }


def _v2_complete() -> list[dict]:
    return [
        _v2_event(1, "run.started"),
        _v2_event(2, "harness.completed", {"session_id": "s1"}),
        _v2_event(3, "worker.finalization", {"exit_code": 0}),
        _v2_event(4, "run.completed", {"status": "completed", "success": True}),
    ]


def test_v2_event_requires_v2_schema():
    event = _v2_event(1, "run.started")
    assert validate_event_v2(event)["schema"] == CANONICAL_EVENT_SCHEMA_V2
    event["schema"] = CANONICAL_EVENT_SCHEMA
    with pytest.raises(HarnessProtocolError, match="unsupported event schema"):
        validate_event_v2(event)


def test_v2_event_requires_control_transport_and_model_protocols():
    event = _v2_event(1, "run.started")
    del event["harness"]["control_transport"]
    with pytest.raises(HarnessProtocolError, match="control_transport"):
        validate_event_v2(event)
    event = _v2_event(1, "run.started")
    del event["harness"]["model_protocols"]
    with pytest.raises(HarnessProtocolError, match="model_protocols"):
        validate_event_v2(event)


def test_v2_rejects_unsupported_model_protocol():
    event = _v2_event(1, "run.started")
    event["harness"]["model_protocols"] = ["vendor_proprietary"]
    with pytest.raises(HarnessProtocolError, match="fail closed"):
        validate_event_v2(event)


def test_v1_validator_still_rejects_v2_fields_expectation():
    # V1 events must not silently accept a V2 schema.
    with pytest.raises(HarnessProtocolError, match="unsupported event schema"):
        validate_event(_v2_event(1, "run.started"))


def test_event_schema_dispatch_selects_v2_validator():
    event = _v2_event(1, "run.started")
    assert validate_event_by_schema(event)["schema"] == CANONICAL_EVENT_SCHEMA_V2
    v1 = build_event(
        attempt_id="x",
        seq=1,
        task_id=1,
        harness_key="claude",
        adapter_version="1",
        cli_version="1",
        event_type="run.started",
    )
    assert validate_event_by_schema(v1)["schema"] == CANONICAL_EVENT_SCHEMA


def test_control_command_delivered_requires_command_keys():
    event = _v2_event(2, "control.command.delivered")
    event["payload"] = {"command_id": "cmd-1"}
    with pytest.raises(HarnessProtocolError, match="requires"):
        validate_event_v2(event)


def test_control_command_rejected_requires_known_code():
    event = _v2_event(2, "control.command.rejected")
    event["payload"] = {
        "command_id": "cmd-1",
        "payload_digest": "d",
        "sequence_no": 1,
        "rejection_code": "mystery_code",
        "rejection_message": "no",
    }
    with pytest.raises(HarnessProtocolError, match="known rejection_code"):
        validate_event_v2(event)

    event["payload"]["rejection_code"] = "delivery_outcome_unknown"
    assert validate_event_v2(event)["type"] == "control.command.rejected"


def test_v2_replay_tracks_control_transport_identity():
    replay = CanonicalEventReplay()
    replay.ingest(_v2_event(1, "run.started"))
    changed = _v2_event(2, "harness.completed", {"session_id": "s"})
    changed["harness"]["control_transport"] = {"kind": "server_http", "protocol": "x"}
    with pytest.raises(HarnessProtocolError, match="control transport changed"):
        replay.ingest(changed)


def test_v2_complete_attempt_replays_to_single_terminal():
    replay = replay_events(_v2_complete())
    assert replay.terminal_type == "run.completed"


def test_v2_result_requires_harness_block_and_validates_usage():
    result = validate_result_v2(
        {
            "schema": "codify.worker.result/v2",
            "status": "completed",
            "success": True,
            "result": {"text": "ok"},
            "harness": {
                "key": "pi",
                "adapter_version": "2.0.0",
                "cli_version": "0.84.2",
                "control_transport": {"kind": "rpc_stdio", "protocol": "pi-rpc"},
                "model_protocols": ["anthropic_messages"],
            },
            "session_id": "s",
            "model": "m",
            "usage": {},
            "failure": None,
            "capability_warnings": [],
        }
    )
    assert result["usage"]["cost"] is None


def test_v2_result_pass_accepts_full_nested_harness_block():
    # Positive case: the frozen V2 result envelope (nested `harness` block with
    # control transport and model protocols) validates and is normalized.
    result = validate_result_v2(
        {
            "schema": "codify.worker.result/v2",
            "status": "completed",
            "success": True,
            "result": {"text": "ok"},
            "harness": {
                "key": "pi",
                "adapter_version": "2.0.0",
                "cli_version": "0.84.2",
                "control_transport": {"kind": "rpc_stdio", "protocol": "pi-rpc"},
                "model_protocols": ["anthropic_messages"],
            },
            "session_id": "s",
            "model": "m",
            "usage": {},
            "failure": None,
            "capability_warnings": [],
        }
    )
    assert result["schema"] == "codify.worker.result/v2"
    assert result["harness"]["key"] == "pi"


def test_command_payload_digest_is_canonical_and_stable():
    d1 = command_payload_digest(7, "v2-attempt-1", "steer", {"text": "go"})
    d2 = command_payload_digest(7, "v2-attempt-1", "steer", {"text": "go"})
    assert d1 == d2
    assert len(d1) == 64
    assert d1 != command_payload_digest(7, "v2-attempt-1", "steer", {"text": "go2"})


def test_command_payload_digest_preserves_valid_unicode_text_exactly():
    composed = "\u00e9😀"
    decomposed = "e\u0301😀"
    assert composed != decomposed
    assert command_payload_digest(7, "v2-attempt-1", "steer", {"text": composed}) != (
        command_payload_digest(7, "v2-attempt-1", "steer", {"text": decomposed})
    )


def _valid_command() -> dict:
    return {
        "schema": COMMAND_SCHEMA_V2,
        "command_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "task_id": 123,
        "attempt_id": "task-123-attempt-1",
        "sequence_no": 7,
        "type": "steer",
        "payload": {"text": "先修复并发问题"},
        "created_at": "2026-08-21T10:00:00Z",
    }


def test_validate_command_accepts_steer_followup():
    assert validate_command(_valid_command())["type"] == "steer"
    cmd = _valid_command()
    cmd["type"] = "follow_up"
    assert validate_command(cmd)["type"] == "follow_up"


def test_validate_command_rejects_invalid_type_and_oversized_text():
    cmd = _valid_command()
    cmd["type"] = "explode"
    with pytest.raises(HarnessProtocolError, match="steer or follow_up"):
        validate_command(cmd)
    cmd = _valid_command()
    cmd["payload"] = {"text": "x" * 4001}
    with pytest.raises(HarnessProtocolError, match="payload_too_large"):
        validate_command(cmd)


def test_validate_command_uses_frozen_ids_and_utf16_unicode_scalar_rules():
    assert MAX_COMMAND_TEXT_UTF16_CODE_UNITS == 4000
    cmd = _valid_command()
    cmd["command_id"] = "01Kxyz"
    with pytest.raises(HarnessProtocolError, match="ULID or UUID"):
        validate_command(cmd)

    cmd = _valid_command()
    cmd["command_id"] = "550E8400-E29B-41D4-A716-446655440000"
    assert validate_command(cmd)["command_id"] == "550e8400-e29b-41d4-a716-446655440000"

    cmd = _valid_command()
    cmd["command_id"] = "01arz3ndektsv4rrffq69g5fav"
    assert validate_command(cmd)["command_id"] == "01ARZ3NDEKTSV4RRFFQ69G5FAV"

    cmd = _valid_command()
    cmd["payload"] = {"text": "😀" * 2000}
    assert command_text_utf16_code_units(cmd["payload"]["text"]) == 4000
    assert validate_command(cmd)["payload"] == cmd["payload"]

    cmd = _valid_command()
    cmd["payload"] = {"text": "😀" * 2000 + "a"}
    with pytest.raises(HarnessProtocolError, match="payload_too_large"):
        validate_command(cmd)

    cmd = _valid_command()
    cmd["payload"] = {"text": "\ud800"}
    with pytest.raises(HarnessProtocolError, match="invalid Unicode scalar"):
        validate_command(cmd)


def _valid_manifest() -> dict:
    return {
        "schema": RUNTIME_MANIFEST_SCHEMA_V2,
        "maturity": "internal_preview",
        "contract_version": "codify.worker.harness/v2",
        "event_schema": CANONICAL_EVENT_SCHEMA_V2,
        "command_schema": COMMAND_SCHEMA_V2,
        "result_schema": "codify.worker.result/v2",
        "adapters": {
            "pi": {
                "support_tier": "default",
                "source": {
                    "repository": "https://github.com/earendil-works/pi",
                    "license": "MIT",
                    "artifact_version": "0.84.2",
                    "artifact_sha256": "906fbe78",
                },
                "adapter": {"version": "2.0.0", "digest": "abc"},
                "control_transport": {"kind": "rpc_stdio", "protocol": "pi-rpc"},
                "model_protocols": ["anthropic_messages"],
                "capabilities": {
                    "resume": True,
                    "task_skills": True,
                    "usage_tokens": True,
                    "steering": True,
                    "follow_up": True,
                },
                "options_schema": "pi/v1",
            }
        },
        "files": [{"path": "runner.py", "size": 123, "sha256": "deadbeef"}],
    }


def test_validate_manifest_accepts_approved_adapter():
    assert "pi" in validate_manifest(_valid_manifest())["adapters"]


def test_validate_manifest_fails_closed_on_unknown_adapter():
    manifest = _valid_manifest()
    manifest["adapters"]["custom"] = {
        "control_transport": {"kind": "rpc_stdio"},
        "model_protocols": ["anthropic_messages"],
        "capabilities": {"resume": True},
    }
    with pytest.raises(HarnessProtocolError, match="non-approved"):
        validate_manifest(manifest)
