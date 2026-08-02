"""Executable Codify Harness and Canonical Event v1 contracts.

The worker owns event construction.  Adapters only normalize engine-specific
records into an event type and payload; callers use :func:`build_event` to add
the stable envelope and :class:`CanonicalEventReplay` to validate a complete
attempt before trusting its terminal state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Iterable, Mapping
from uuid import UUID, uuid4

CANONICAL_EVENT_SCHEMA = "codify.worker.event/v1"
HARNESS_CONTRACT_VERSION = "codify.worker.harness/v1"
CANONICAL_RESULT_SCHEMA = "codify.worker.result/v1"
FIRST_SEQUENCE = 1


class FailureKind(StrEnum):
    CONFIGURATION_ERROR = "configuration_error"
    AUTHENTICATION_ERROR = "authentication_error"
    RATE_LIMITED = "rate_limited"
    SANDBOX_ERROR = "sandbox_error"
    PROTOCOL_ERROR = "protocol_error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    ENGINE_ERROR = "engine_error"


KNOWN_EVENT_TYPES = frozenset(
    {
        "run.started",
        "model.resolved",
        "message.delta",
        "message.completed",
        "reasoning_summary.delta",
        "reasoning_summary.completed",
        "tool.started",
        "tool.completed",
        "context.compacted",
        "provider.retry",
        "usage.updated",
        "usage.final",
        "harness.completed",
        "harness.failed",
        "delivery.started",
        "delivery.completed",
        "delivery.failed",
        "worker.finalization",
        "run.completed",
        "run.failed",
        "diagnostic",
    }
)
TASK_TERMINAL_TYPES = frozenset({"run.completed", "run.failed"})
HARNESS_TERMINAL_TYPES = frozenset({"harness.completed", "harness.failed"})
NON_TERMINAL_TYPES = frozenset(
    event_type for event_type in KNOWN_EVENT_TYPES if event_type not in TASK_TERMINAL_TYPES
)
HIDDEN_REASONING_KEYS = frozenset(
    {"thinking", "chain_of_thought", "hidden_reasoning", "encrypted_content"}
)


class HarnessProtocolError(ValueError):
    """One canonical event or a complete attempt violates protocol v1."""

    def __init__(self, message: str, *, code: str = "protocol_error") -> None:
        super().__init__(message)
        self.code = code


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise HarnessProtocolError("occurred_at must be a non-empty RFC3339 timestamp")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HarnessProtocolError("occurred_at must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise HarnessProtocolError("occurred_at must include a timezone")
    return parsed


def _validate_raw_ref(raw_ref: Any) -> None:
    if raw_ref is None:
        return
    if not isinstance(raw_ref, Mapping):
        raise HarnessProtocolError("raw_ref must be an object or null")
    stream = raw_ref.get("stream")
    line = raw_ref.get("line")
    if not isinstance(stream, str) or not stream.startswith("harness-events/"):
        raise HarnessProtocolError("raw_ref.stream must reference harness-events/")
    if not isinstance(line, int) or isinstance(line, bool) or line < 1:
        raise HarnessProtocolError("raw_ref.line must be a positive integer")


def _contains_hidden_reasoning(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in HIDDEN_REASONING_KEYS:
                return True
            if _contains_hidden_reasoning(child):
                return True
    elif isinstance(value, list):
        return any(_contains_hidden_reasoning(child) for child in value)
    return False


def normalize_usage(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the portable usage object, preserving unavailable values as null."""
    source = value or {}
    normalized: dict[str, Any] = {
        "input_tokens": source.get("input_tokens"),
        "cached_input_tokens": source.get("cached_input_tokens"),
        "output_tokens": source.get("output_tokens"),
        "reasoning_tokens": source.get("reasoning_tokens"),
        "cost": source.get("cost"),
        "currency": source.get("currency"),
        "engine_fields": source.get("engine_fields") or {},
    }
    for key in (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
    ):
        token_count = normalized[key]
        if token_count is not None and (
            not isinstance(token_count, int) or isinstance(token_count, bool) or token_count < 0
        ):
            raise HarnessProtocolError(f"usage.{key} must be a non-negative integer or null")
    if normalized["cost"] is not None and (
        not isinstance(normalized["cost"], (int, float))
        or isinstance(normalized["cost"], bool)
        or normalized["cost"] < 0
    ):
        raise HarnessProtocolError("usage.cost must be a non-negative number or null")
    if normalized["currency"] is not None and not isinstance(normalized["currency"], str):
        raise HarnessProtocolError("usage.currency must be a string or null")
    if not isinstance(normalized["engine_fields"], Mapping):
        raise HarnessProtocolError("usage.engine_fields must be an object")
    return normalized


def normalize_event_type(
    event_type: str,
    payload: Mapping[str, Any],
    *,
    raw_ref: Mapping[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    """Downgrade an unknown non-terminal type to an auditable diagnostic.

    Unknown types beginning with ``run.`` are rejected because their terminal
    meaning cannot be inferred safely.
    """
    if event_type in KNOWN_EVENT_TYPES:
        return event_type, dict(payload)
    if event_type.startswith("run."):
        raise HarnessProtocolError(
            f"unknown task terminal event type: {event_type}", code="unknown_terminal"
        )
    return (
        "diagnostic",
        {
            "code": "unknown_event_type",
            "original_type": event_type,
            "raw_ref": dict(raw_ref) if raw_ref else None,
        },
    )


def _validate_event_payload(event_type: str, payload: Mapping[str, Any]) -> None:
    if event_type == "run.completed":
        if payload.get("status") != "completed" or payload.get("success") is not True:
            raise HarnessProtocolError("run.completed requires completed/success payload")
    elif event_type == "run.failed":
        if payload.get("status") not in {"failed", "cancelled", "protocol_error"}:
            raise HarnessProtocolError("run.failed requires a known failure status")
        if payload.get("success") is not False:
            raise HarnessProtocolError("run.failed requires success=false")
        failure = payload.get("failure")
        if not isinstance(failure, Mapping) or failure.get("kind") not in set(FailureKind):
            raise HarnessProtocolError("run.failed requires a known failure.kind")
    elif event_type == "harness.failed":
        failure = payload.get("failure")
        if not isinstance(failure, Mapping) or failure.get("kind") not in set(FailureKind):
            raise HarnessProtocolError("harness.failed requires a known failure.kind")


def validate_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one canonical event envelope."""
    required = {
        "schema",
        "event_id",
        "attempt_id",
        "seq",
        "occurred_at",
        "type",
        "task_id",
        "harness",
        "payload",
    }
    missing = sorted(required - set(event))
    if missing:
        raise HarnessProtocolError(f"missing canonical event fields: {', '.join(missing)}")
    if event.get("schema") != CANONICAL_EVENT_SCHEMA:
        raise HarnessProtocolError(f"unsupported event schema: {event.get('schema')!r}")
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip():
        raise HarnessProtocolError("event_id must be a non-empty string")
    attempt_id = event.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise HarnessProtocolError("attempt_id must be a non-empty string")
    seq = event.get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < FIRST_SEQUENCE:
        raise HarnessProtocolError(f"seq must be an integer >= {FIRST_SEQUENCE}")
    _parse_timestamp(event.get("occurred_at"))
    task_id = event.get("task_id")
    if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id < 1:
        raise HarnessProtocolError("task_id must be a positive integer")
    harness = event.get("harness")
    if not isinstance(harness, Mapping):
        raise HarnessProtocolError("harness must be an object")
    for key in ("key", "adapter_version", "cli_version"):
        if not isinstance(harness.get(key), str) or not harness[key].strip():
            raise HarnessProtocolError(f"harness.{key} must be a non-empty string")
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        raise HarnessProtocolError("payload must be an object")
    if _contains_hidden_reasoning(payload):
        raise HarnessProtocolError("payload contains a forbidden hidden-reasoning field")
    _validate_raw_ref(event.get("raw_ref"))
    event_type, normalized_payload = normalize_event_type(
        str(event.get("type") or ""), payload, raw_ref=event.get("raw_ref")
    )
    if event_type in {"usage.updated", "usage.final"}:
        normalized_payload["usage"] = normalize_usage(normalized_payload.get("usage"))
    _validate_event_payload(event_type, normalized_payload)
    normalized = dict(event)
    normalized["type"] = event_type
    normalized["payload"] = normalized_payload
    return normalized


def build_event(
    *,
    attempt_id: str,
    seq: int,
    task_id: int,
    harness_key: str,
    adapter_version: str,
    cli_version: str,
    event_type: str,
    payload: Mapping[str, Any] | None = None,
    raw_ref: Mapping[str, Any] | None = None,
    event_id: str | None = None,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    event = {
        "schema": CANONICAL_EVENT_SCHEMA,
        "event_id": event_id or str(uuid4()),
        "attempt_id": attempt_id,
        "seq": seq,
        "occurred_at": occurred_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "type": event_type,
        "task_id": task_id,
        "harness": {
            "key": harness_key,
            "adapter_version": adapter_version,
            "cli_version": cli_version,
        },
        "payload": dict(payload or {}),
    }
    if raw_ref is not None:
        event["raw_ref"] = dict(raw_ref)
    return validate_event(event)


@dataclass(slots=True)
class CanonicalEventReplay:
    """Stateful invariant checker for one complete attempt."""

    attempt_id: str | None = None
    task_id: int | None = None
    harness_key: str | None = None
    adapter_version: str | None = None
    cli_version: str | None = None
    last_seq: int = 0
    seen_event_ids: set[str] = field(default_factory=set)
    started: bool = False
    harness_ended: bool = False
    finalization_seen: bool = False
    terminal_type: str | None = None

    def ingest(self, raw_event: Mapping[str, Any]) -> dict[str, Any]:
        event = validate_event(raw_event)
        event_id = event["event_id"]
        if event_id in self.seen_event_ids:
            raise HarnessProtocolError(f"duplicate event_id: {event_id}", code="duplicate_event")
        if self.terminal_type is not None:
            raise HarnessProtocolError("canonical event appears after task terminal", code="after_terminal")
        if self.attempt_id is None:
            self.attempt_id = event["attempt_id"]
            self.task_id = event["task_id"]
            self.harness_key = event["harness"]["key"]
            self.adapter_version = event["harness"]["adapter_version"]
            self.cli_version = event["harness"]["cli_version"]
        elif event["attempt_id"] != self.attempt_id:
            raise HarnessProtocolError("attempt_id changed inside one replay")
        elif event["task_id"] != self.task_id:
            raise HarnessProtocolError("task_id changed inside one replay")
        elif event["harness"]["key"] != self.harness_key:
            raise HarnessProtocolError("harness key changed inside one replay")
        elif event["harness"]["adapter_version"] != self.adapter_version:
            raise HarnessProtocolError("Adapter version changed inside one replay")
        elif event["harness"]["cli_version"] != self.cli_version:
            raise HarnessProtocolError("CLI version changed inside one replay")
        expected_seq = self.last_seq + 1
        if event["seq"] != expected_seq:
            raise HarnessProtocolError(
                f"sequence gap: expected {expected_seq}, received {event['seq']}",
                code="sequence_gap",
            )
        event_type = event["type"]
        if self.finalization_seen and event_type not in TASK_TERMINAL_TYPES:
            raise HarnessProtocolError(
                "only the Task terminal may follow worker.finalization",
                code="after_finalization",
            )
        if event_type == "run.started":
            if self.started:
                raise HarnessProtocolError("run.started appears more than once")
            if event["seq"] != FIRST_SEQUENCE:
                raise HarnessProtocolError("run.started must be the first canonical event")
            self.started = True
        elif not self.started:
            raise HarnessProtocolError("canonical attempt is missing run.started", code="missing_init")
        if event_type in HARNESS_TERMINAL_TYPES:
            if self.harness_ended:
                raise HarnessProtocolError("harness terminal appears more than once")
            self.harness_ended = True
        if event_type.startswith("delivery.") and not self.harness_ended:
            raise HarnessProtocolError("delivery event appears before harness terminal")
        if event_type == "worker.finalization":
            if not self.harness_ended:
                raise HarnessProtocolError("worker.finalization appears before harness terminal")
            if self.finalization_seen:
                raise HarnessProtocolError("worker.finalization appears more than once")
            self.finalization_seen = True
        if event_type in TASK_TERMINAL_TYPES:
            if not self.harness_ended:
                raise HarnessProtocolError("task terminal appears before harness terminal")
            if not self.finalization_seen:
                raise HarnessProtocolError("task terminal appears before worker.finalization")
            self.terminal_type = event_type
        self.last_seq = event["seq"]
        self.seen_event_ids.add(event_id)
        return event

    def finish(self) -> str:
        if not self.started:
            raise HarnessProtocolError("canonical attempt is missing run.started", code="missing_init")
        if not self.harness_ended:
            raise HarnessProtocolError(
                "canonical attempt is missing harness terminal", code="missing_harness_terminal"
            )
        if self.terminal_type is None:
            raise HarnessProtocolError(
                "canonical attempt is missing task terminal", code="missing_task_terminal"
            )
        return self.terminal_type


def replay_events(events: Iterable[Mapping[str, Any]]) -> CanonicalEventReplay:
    replay = CanonicalEventReplay()
    for event in events:
        replay.ingest(event)
    replay.finish()
    return replay


def validate_result(result: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema",
        "status",
        "success",
        "result",
        "harness_key",
        "adapter_version",
        "cli_version",
        "session_id",
        "model",
        "usage",
        "failure",
        "capability_warnings",
    }
    missing = sorted(required - set(result))
    if missing:
        raise HarnessProtocolError(f"missing canonical result fields: {', '.join(missing)}")
    if result.get("schema") != CANONICAL_RESULT_SCHEMA:
        raise HarnessProtocolError("unsupported canonical result schema")
    if result.get("status") not in {"completed", "failed", "cancelled", "protocol_error"}:
        raise HarnessProtocolError("invalid canonical result status")
    if not isinstance(result.get("success"), bool):
        raise HarnessProtocolError("canonical result success must be boolean")
    if result["success"] != (result["status"] == "completed"):
        raise HarnessProtocolError("canonical result success and status disagree")
    failure = result.get("failure")
    if result["success"] and failure is not None:
        raise HarnessProtocolError("successful canonical result cannot include failure")
    if not result["success"]:
        if not isinstance(failure, Mapping) or failure.get("kind") not in set(FailureKind):
            raise HarnessProtocolError("failed canonical result requires a known failure.kind")
    normalized = dict(result)
    normalized["usage"] = normalize_usage(result.get("usage"))
    warnings = result.get("capability_warnings")
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        raise HarnessProtocolError("capability_warnings must be an array of strings")
    return normalized


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def content_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def deterministic_event_id(attempt_id: str, seq: int) -> str:
    """Stable UUID-shaped ID for fixture replay and retry-safe projection."""
    digest = hashlib.sha256(f"{attempt_id}:{seq}".encode()).digest()[:16]
    return str(UUID(bytes=digest))
