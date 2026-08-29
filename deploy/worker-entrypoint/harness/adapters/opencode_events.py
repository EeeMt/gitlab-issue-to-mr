#!/usr/bin/env python3
"""Translate OpenCode Server SSE events to Canonical Event v2 records.

OpenCode 1.18.19 drives a Task-scoped ``opencode serve`` (control transport
``server_http``). The Server pushes events over a single ``GET /event`` SSE
stream; each SSE record is the ``{id, type, properties}`` object observed in
the Phase-0 probe (docs/harness-probes/v2/opencode/events.observed.jsonl).
This translator reads those records one-per-line from stdin (the wire framing
is unwrapped into JSON by the Bridge) and maps each to a canonical event.

Settled judgment (open-harness-v2-phase3-opencode-design.md §4, frozen) is a
multi-signal combination, NOT a single busy/idle field:

1. ``session.idle`` (SSE) is authoritative; it implies the run is no longer
   busy and the turn reached terminal without more pending parts.
2. A final assistant message must have been received (text parts aggregated
   from ``message.part.updated``/``message.part.delta``).
3. The session is not in an error state.

For OpenCode first release the attempt has no command plane (manifest
``steering=false``/``follow_up=false``, control state ``disabled``), so settled
converges a single harness terminal directly — there is no accepting->closing
->drain gate. ``agent_settled`` is still surfaced as an auditable diagnostic
marker so the projector's settled handling stays uniform across harnesses.

Transport is owned by the Bridge (see opencode_bridge.py): it establishes the
SSE subscription, creates the session, sends ``prompt_async``, and falls back to
``GET /session/status`` after a disconnect. This module only normalizes records.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from result_builder import v2_harness_block
from sanitize import clean_message, redact_hidden_reasoning, sanitize

SCHEMA = "codify.worker.event/v2"
_RATE_LIMIT_REASONS = frozenset(
    {
        "account_rate_limit",
        "monthly_limit",
        "quota_exceeded",
        "rate_limit",
        "rate_limited",
        "usage_limit",
        "usage_limit_exceeded",
    }
)
_RATE_LIMIT_MARKERS = (
    "429",
    "rate limit",
    "rate-limit",
    "usage limit",
    "usage_limit",
    "quota exceeded",
    "quota_exceeded",
    "account_rate_limit",
    "too many requests",
    "monthly limit",
)
_TOOL_OUTPUT_MAX_CHARS = 2000
_TOOL_COMMAND_MAX_CHARS = 1000
_TOOL_VALUE_MAX_CHARS = 4000
_TOOL_NAME_ALIASES = {
    "bash": "Bash",
    "shell": "Bash",
    "write": "Write",
    "read": "Read",
    "edit": "Edit",
    "patch": "Edit",
    "apply_patch": "Edit",
    "multiedit": "MultiEdit",
    "multi_edit": "MultiEdit",
    "glob": "Glob",
    "grep": "Grep",
    "webfetch": "WebFetch",
    "web_fetch": "WebFetch",
    "task": "Task",
    "todowrite": "TodoWrite",
    "todo_write": "TodoWrite",
}
_TOOL_ACTIVE_STATUSES = frozenset({"pending", "running"})
_TOOL_TERMINAL_STATUSES = frozenset({"completed", "error", "failed"})

# These are OpenCode server/catalog/UI events. They are deliberately explicit
# no-ops: the sanitized raw SSE archive remains the source of truth, while
# catalog chatter must not become hundreds of misleading task diagnostics.
_IGNORED_KNOWN_EVENTS = frozenset(
    {
        "catalog.updated",
        "integration.updated",
        "plugin.added",
        "reference.updated",
        "server.instance.disposed",
        "installation.updated",
        "installation.update-available",
        "lsp.client.diagnostics",
        "lsp.updated",
        "file.edited",
        "file.watcher.updated",
        "vcs.branch.updated",
        "session.deleted",
        "tui.prompt.append",
        "tui.command.execute",
        "tui.toast.show",
        "pty.created",
        "pty.updated",
        "pty.exited",
        "pty.deleted",
    }
)

# Per-stream in-memory state. The terminal is decided when settled is reached.
_STATE: dict = {
    "model_resolved": False,
    "model_id": None,
    "session_id": None,
    "text_parts": [],
    "messages": {},             # message_id -> part_id -> text state
    "tools": {},                # tool_id -> lifecycle state
    "assistant_message_ids": [],
    "user_message_ids": set(),
    "message": {},        # most recent assistant message info
    "idle_seen": False,
    "busy": False,
    "usage": {},
    "terminal": None,     # "completed" | "failed"
    "terminal_failure": None,
    "aborted": False,
    "settled": False,
    "settled_line": None,
    "last_line": 1,
}


def _failure_kind(message: str) -> str:
    lowered = str(message).lower()
    if "abort" in lowered or "interrupt" in lowered or "operation was aborted" in lowered:
        return "cancelled"
    if "401" in lowered or "unauthorized" in lowered or "authentication" in lowered:
        return "authentication_error"
    if (
        any(marker in lowered for marker in _RATE_LIMIT_MARKERS)
    ):
        return "rate_limited"
    if "session_missing" in lowered or "session not found" in lowered:
        return "engine_error"
    if "invalid_agent_command" in lowered or "invalid command" in lowered:
        return "engine_error"
    if "crash" in lowered or "connection refused" in lowered or "connrefused" in lowered:
        return "crash"
    if "sandbox" in lowered or "permission denied" in lowered:
        return "sandbox_error"
    return "engine_error"


def _is_rate_limit_reason(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized in _RATE_LIMIT_REASONS


def _emit(event_type: str, payload: dict, raw_line: int) -> None:
    writer = os.environ["CODIFY_CANONICAL_EVENT_WRITER"]
    subprocess.run(
        [
            sys.executable,
            writer,
            event_type,
            "--payload",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            "--raw-stream",
            "harness-events/opencode.jsonl",
            "--raw-line",
            str(raw_line),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def _usage(properties: dict) -> dict:
    source = properties.get("usage") if isinstance(properties.get("usage"), dict) else {}
    if not source and isinstance(properties.get("tokens"), dict):
        source = properties["tokens"]
    def _first_value(*keys: str):
        for key in keys:
            value = source.get(key)
            if value is not None:
                return value
        return None

    cache = source.get("cache") if isinstance(source.get("cache"), dict) else {}
    cached_input_tokens = _first_value("cached_input_tokens", "cacheRead")
    if cached_input_tokens is None:
        cached_input_tokens = cache.get("read")

    cost_source = properties.get("cost")
    if cost_source is None:
        cost_source = source.get("cost")
    if isinstance(cost_source, dict):
        cost = cost_source.get("total")
    elif isinstance(cost_source, (int, float)) and not isinstance(cost_source, bool):
        cost = cost_source
    else:
        cost = None

    excluded = {
        "input_tokens",
        "input",
        "cached_input_tokens",
        "cacheRead",
        "output_tokens",
        "output",
        "reasoning_tokens",
        "reasoning",
        "reasoningTokens",
        "cost",
    }
    engine_fields = {
        key: value for key, value in source.items() if key not in excluded
    }
    if isinstance(cost_source, dict):
        engine_fields["cost_breakdown"] = cost_source
    return {
        "input_tokens": _first_value("input_tokens", "input"),
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": _first_value("output_tokens", "output"),
        "reasoning_tokens": _first_value("reasoning_tokens", "reasoning", "reasoningTokens"),
        "cost": cost,
        "currency": None,
        "engine_fields": engine_fields,
    }


def _sanitize_value(value: object, *, depth: int = 0) -> object:
    """Keep tool payloads bounded, JSON-safe, and free of sensitive strings."""
    if depth > 6:
        return "<DEPTH_LIMIT>"
    if isinstance(value, str):
        return sanitize(value)[:_TOOL_VALUE_MAX_CHARS]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _sanitize_value(child, depth=depth + 1)
            for key, child in list(value.items())[:64]
        }
    if isinstance(value, list):
        return [_sanitize_value(child, depth=depth + 1) for child in value[:64]]
    return sanitize(str(value))[:_TOOL_VALUE_MAX_CHARS]


def _raw_tool_name(part: dict) -> str:
    value = part.get("tool") or part.get("name")
    return str(value).strip() if value is not None and str(value).strip() else "unknown"


def _display_tool_name(part: dict) -> str:
    raw_name = _raw_tool_name(part)
    return _TOOL_NAME_ALIASES.get(raw_name.lower(), raw_name)


def _tool_id(properties: dict, part: dict) -> str | None:
    for source, keys in (
        (part, ("callID", "callId", "toolCallID", "toolCallId", "id")),
        (properties, ("callID", "callId", "toolCallID", "toolCallId", "partID", "partId")),
    ):
        for key in keys:
            value = source.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return None


def _tool_input(part: dict) -> dict:
    state = part.get("state") if isinstance(part.get("state"), dict) else {}
    source = state.get("input") if isinstance(state.get("input"), dict) else {}
    sanitized = _sanitize_value(source)
    if not isinstance(sanitized, dict):
        return {}
    raw_name = _raw_tool_name(part).lower()
    if raw_name in {"bash", "shell"}:
        command = source.get("command") or source.get("cmd") or source.get("script")
        if isinstance(command, str):
            return {"command": sanitize(command)[:_TOOL_COMMAND_MAX_CHARS]}
        return sanitized
    if raw_name in {"read", "write", "edit", "patch", "apply_patch", "multiedit", "multi_edit"}:
        path = (
            source.get("filePath")
            or source.get("file_path")
            or source.get("path")
            or source.get("filename")
        )
        if isinstance(path, str) and path:
            sanitized.pop("filePath", None)
            sanitized.pop("path", None)
            sanitized["file_path"] = sanitize(path)[:_TOOL_VALUE_MAX_CHARS]
        return sanitized
    return sanitized


def _tool_output(part: dict) -> str:
    state = part.get("state") if isinstance(part.get("state"), dict) else {}
    value = state.get("output")
    if value is None:
        value = state.get("error")
    if value is None and isinstance(state.get("metadata"), dict):
        value = state["metadata"].get("output") or state["metadata"].get("error")
    sanitized = _sanitize_value(value)
    if isinstance(sanitized, str):
        return sanitized[:_TOOL_OUTPUT_MAX_CHARS]
    if sanitized is None:
        return ""
    return json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))[:_TOOL_OUTPUT_MAX_CHARS]


def _handle_tool_part(properties: dict, raw_line: int) -> None:
    part = properties.get("part") if isinstance(properties.get("part"), dict) else {}
    state = part.get("state") if isinstance(part.get("state"), dict) else {}
    status = state.get("status")
    tool_id = _tool_id(properties, part)
    name = _display_tool_name(part)
    if status not in _TOOL_ACTIVE_STATUSES | _TOOL_TERMINAL_STATUSES:
        _emit("diagnostic", {"code": "unknown_tool_state", "name": name, "status": status}, raw_line)
        return
    if not tool_id:
        _emit("diagnostic", {"code": "tool_missing_id", "name": name}, raw_line)
        return

    lifecycle = _STATE["tools"].setdefault(
        tool_id,
        {"name": name, "input": {}, "started": False, "completed": False},
    )
    lifecycle["name"] = name
    input_value = _tool_input(part)
    if input_value:
        lifecycle["input"] = input_value

    # OpenCode's pending snapshot commonly has an empty input object. Wait for
    # the running snapshot so the canonical start carries the useful command or
    # file path; terminal-first streams still get a synthetic start below.
    if status in _TOOL_ACTIVE_STATUSES and not lifecycle["started"]:
        if status != "pending" or lifecycle["input"]:
            _emit(
                "tool.started",
                {
                    "tool_id": tool_id,
                    "name": name,
                    "input": redact_hidden_reasoning(lifecycle["input"]),
                },
                raw_line,
            )
            lifecycle["started"] = True

    if status in _TOOL_TERMINAL_STATUSES and not lifecycle["completed"]:
        if not lifecycle["started"]:
            _emit(
                "tool.started",
                {
                    "tool_id": tool_id,
                    "name": name,
                    "input": redact_hidden_reasoning(lifecycle["input"]),
                },
                raw_line,
            )
            lifecycle["started"] = True
        error_message = state.get("error")
        error = status != "completed" or bool(error_message)
        payload = {
            "tool_id": tool_id,
            "name": name,
            "output": _tool_output(part),
            "error": error,
        }
        if isinstance(error_message, str) and error_message.strip():
            payload["error_message"] = clean_message(sanitize(error_message))[:_TOOL_OUTPUT_MAX_CHARS]
        metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
        exit_code = metadata.get("exit")
        if isinstance(exit_code, int) and not isinstance(exit_code, bool):
            payload["exit_code"] = exit_code
        _emit("tool.completed", payload, raw_line)
        lifecycle["completed"] = True


def _write_result(
    *,
    success: bool,
    result: str,
    usage: dict,
    terminal_line: int,
    failure_message: str | None = None,
    failure_kind: str | None = None,
) -> None:
    result_path = Path(os.environ["CODIFY_HARNESS_RESULT_FILE"])
    failure = None
    if not success:
        message = failure_message or result or "OpenCode execution failed"
        failure = {"kind": failure_kind or _failure_kind(message), "message": message}
    payload = {
        "schema": "codify.worker.result/v2",
        "status": "completed" if success else (
            "protocol_error" if _STATE["terminal_failure"] and _STATE["terminal_failure"].get("kind") == "protocol_error" else "failed"
        ),
        "success": success,
        "result": result,
        "harness": v2_harness_block(),
        "session_id": _STATE["session_id"],
        "model": _STATE["model_id"],
        "usage": usage,
        "failure": failure,
        "capability_warnings": [],
    }
    temp_path = result_path.with_suffix(".json.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.replace(temp_path, result_path)
    if usage:
        _emit("usage.final", {"usage": usage}, terminal_line)


def _finalize_terminal() -> None:
    """Emit the single harness terminal once settled / error / abort is reached.

    Guarantees at most one harness terminal per attempt (the events.py writer
    rejects a second one), so it is idempotent via ``_STATE["terminal"]``.
    """
    if _STATE["terminal"] is not None:
        return
    terminal_line = int(_STATE["settled_line"] or _STATE["last_line"] or 1)
    if _STATE["aborted"]:
        _STATE["terminal"] = "failed"
        _STATE["terminal_failure"] = {"kind": "cancelled", "message": "OpenCode run aborted"}
        _write_result(
            success=False,
            result="".join(_STATE["text_parts"]).strip(),
            usage=_STATE["usage"],
            terminal_line=terminal_line,
        )
        _STATE["terminal_line"] = terminal_line
    elif _STATE["terminal_failure"] is not None:
        fail = _STATE["terminal_failure"]
        _STATE["terminal"] = "failed"
        _write_result(
            success=False, result="".join(_STATE["text_parts"]).strip(),
            usage=_STATE["usage"],
            terminal_line=terminal_line,
            failure_message=str(fail["message"]),
            failure_kind=str(fail.get("kind") or "") or None,
        )
        _STATE["terminal_line"] = terminal_line
    else:
        _STATE["terminal"] = "completed"
        _write_result(
            success=True,
            result="".join(_STATE["text_parts"]).strip(),
            usage=_STATE["usage"],
            terminal_line=terminal_line,
        )
        _STATE["terminal_line"] = terminal_line
    if _STATE["terminal"] == "completed":
        _emit(
            "harness.completed",
            {"result": "".join(_STATE["text_parts"]).strip(), "session_id": _STATE["session_id"]},
            terminal_line,
        )
    else:
        failure = _STATE["terminal_failure"] or {
            "kind": "engine_error",
            "message": "OpenCode turn failed",
        }
        _emit("harness.failed", {"failure": failure}, terminal_line)


def _handle_session_status(properties: dict, raw_line: int) -> None:
    status = properties.get("status") if isinstance(properties.get("status"), dict) else {}
    status_type = status.get("type")
    if status_type == "busy":
        _STATE["busy"] = True
        _emit("diagnostic", {"code": "session_busy"}, raw_line)
    elif status_type == "idle":
        _STATE["busy"] = False
        _STATE["idle_seen"] = True
    elif status_type == "retry":
        # OpenCode uses retry both for short transient retries and for terminal
        # account/provider limits. A retry with an account usage limit cannot
        # recover within this Task, so settle it as a typed failure instead of
        # leaving the SSE stream open until the next account reset.
        action = status.get("action") if isinstance(status.get("action"), dict) else {}
        message = (
            status.get("message")
            or action.get("message")
            or action.get("title")
            or "OpenCode provider retry"
        )
        reason = action.get("reason") or status.get("reason")
        lowered = str(message).lower()
        retry_payload = {
            "attempt": status.get("attempt"),
            "max_attempts": status.get("maxAttempts"),
            "failure_kind": _failure_kind(clean_message(str(message))),
            "retry_delay_ms": status.get("delayMs"),
        }
        next_retry = status.get("next")
        if isinstance(next_retry, (int, float)) and not isinstance(next_retry, bool):
            retry_payload["retry_at"] = next_retry
        _emit("provider.retry", retry_payload, raw_line)
        if _is_rate_limit_reason(reason) or any(
            marker in lowered for marker in _RATE_LIMIT_MARKERS
        ):
            message = clean_message(str(message))
            _STATE["terminal_failure"] = {
                "kind": "rate_limited",
                "message": message,
            }
            _finalize_terminal()
    elif status_type is not None:
        _emit("diagnostic", {"code": "unknown_session_status", "type": status_type}, raw_line)
    session_id = properties.get("sessionID")
    if session_id:
        _STATE["session_id"] = _STATE["session_id"] or session_id


def _handle_session_created(properties: dict, raw_line: int) -> None:
    session_id = properties.get("sessionID") or properties.get("sessionId")
    if session_id:
        _STATE["session_id"] = _STATE["session_id"] or session_id


def _handle_session_error(properties: dict, raw_line: int) -> None:
    message = properties.get("error") or properties.get("message") or "OpenCode session error"
    # session.error is an unhandled SSE path (probe 待测); classify deterministically
    # and converge to a failed terminal so the attempt does not hang.
    message = clean_message(str(message))
    kind = _failure_kind(message)
    if kind == "cancelled":
        _STATE["aborted"] = True
    _STATE["terminal_failure"] = {"kind": kind, "message": message}
    _finalize_terminal()


def _handle_message_updated(properties: dict, raw_line: int) -> None:
    info = properties.get("info") if isinstance(properties.get("info"), dict) else {}
    usage = info.get("usage") if isinstance(info.get("usage"), dict) else info.get("tokens")
    if isinstance(usage, dict):
        _STATE["usage"] = _usage({"usage": usage, "cost": info.get("cost")})
    role = info.get("role")
    message_id = info.get("id") or properties.get("messageID")
    if not message_id and role == "assistant":
        message_id = "__assistant__"
    if message_id and role == "user":
        _STATE["user_message_ids"].add(message_id)
        _STATE["messages"].pop(message_id, None)
    if role == "assistant":
        _STATE["message"] = info
        if message_id not in _STATE["assistant_message_ids"]:
            _STATE["assistant_message_ids"].append(message_id)
        _flush_pending_deltas(message_id)
        _refresh_text()
    session_id = properties.get("sessionID") or properties.get("sessionId")
    if session_id:
        _STATE["session_id"] = _STATE["session_id"] or session_id


def _message_id(properties: dict, part: dict | None = None) -> str:
    part = part or {}
    explicit = properties.get("messageID") or properties.get("messageId")
    explicit = explicit or part.get("messageID") or part.get("messageId")
    if explicit:
        return explicit
    if len(_STATE["assistant_message_ids"]) == 1:
        return _STATE["assistant_message_ids"][0]
    return "__unattributed__"


def _part_id(properties: dict, part: dict | None, message_id: str) -> str:
    part = part or {}
    explicit = properties.get("partID") or properties.get("partId") or part.get("id")
    if explicit:
        return explicit
    existing = _STATE["messages"].get(message_id, {})
    if len(existing) == 1:
        return next(iter(existing))
    return "__default__"


def _part_state(message_id: str, part_id: str) -> dict:
    messages = _STATE["messages"]
    message = messages.setdefault(message_id, {})
    return message.setdefault(
        part_id,
        {"text": "", "pending_deltas": []},
    )


def _refresh_text() -> None:
    text_parts: list[str] = []
    for message_id in _STATE["assistant_message_ids"]:
        for part in _STATE["messages"].get(message_id, {}).values():
            text = part.get("text")
            if isinstance(text, str):
                text_parts.append(text)
    _STATE["text_parts"] = text_parts


def _flush_pending_deltas(message_id: str) -> None:
    """Emit deltas buffered until OpenCode identifies their message role."""
    for part in _STATE["messages"].get(message_id, {}).values():
        pending = part.get("pending_deltas") or []
        for delta, raw_line in pending:
            _emit("message.delta", {"content": delta, "role": "assistant"}, raw_line)
        part["pending_deltas"] = []


def _handle_message_part_updated(properties: dict, raw_line: int) -> None:
    part = properties.get("part") if isinstance(properties.get("part"), dict) else {}
    part_type = part.get("type")
    if part_type == "tool":
        _handle_tool_part(properties, raw_line)
    elif part_type == "text":
        text = part.get("text")
        if isinstance(text, str):
            message_id = _message_id(properties, part)
            if message_id in _STATE["user_message_ids"]:
                return
            part_id = _part_id(properties, part, message_id)
            state = _part_state(message_id, part_id)
            # OpenCode emits full snapshots for a part. A snapshot can arrive
            # before or after deltas, so it replaces the accumulated text and
            # later deltas extend it only when they are not already included.
            state["text"] = text
            _refresh_text()
    elif part_type == "reasoning":
        # OpenCode reasoning parts are model-internal content. Preserve the
        # fact that the part was observed without projecting hidden reasoning.
        _emit(
            "diagnostic",
            {"code": "hidden_reasoning_omitted", "message": "OpenCode reasoning omitted"},
            raw_line,
        )
    elif part_type == "retry":
        message = part.get("error") or part.get("message") or "OpenCode provider retry"
        _emit(
            "provider.retry",
            {
                "attempt": part.get("attempt"),
                "max_attempts": part.get("maxAttempts"),
                "failure_kind": _failure_kind(clean_message(str(message))),
                "retry_delay_ms": part.get("delayMs"),
            },
            raw_line,
        )
    elif part_type == "compaction":
        _emit(
            "context.compacted",
            {
                "session_id": properties.get("sessionID"),
                "reason": part.get("reason"),
            },
            raw_line,
        )
    elif part_type not in {"step-start", "step-finish", "file", "patch", "snapshot", "agent", "subtask"}:
        _emit("diagnostic", {"code": "unknown_message_part", "type": part_type}, raw_line)
    usage = part.get("usage") if isinstance(part.get("usage"), dict) else part.get("tokens")
    if isinstance(usage, dict):
        _STATE["usage"] = _usage({"usage": usage, "cost": part.get("cost")})
        if part_type == "step-finish":
            _emit("usage.updated", {"usage": _STATE["usage"]}, raw_line)


def _handle_message_part_delta(properties: dict, raw_line: int) -> None:
    delta = properties.get("delta")
    if isinstance(delta, str) and delta:
        message_id = _message_id(properties)
        if message_id in _STATE["user_message_ids"]:
            return
        part_id = _part_id(properties, None, message_id)
        state = _part_state(message_id, part_id)
        current = state["text"]
        if not current.endswith(delta):
            state["text"] += delta
        _refresh_text()
        if message_id in _STATE["assistant_message_ids"]:
            _emit("message.delta", {"content": delta, "role": "assistant"}, raw_line)
        else:
            # The assistant message.updated event may trail its part stream.
            # Buffer the canonical delta until the role is known; this avoids
            # leaking the user prompt while preserving the event once identified.
            state["pending_deltas"].append((delta, raw_line))


def _handle_session_idle(properties: dict, raw_line: int) -> None:
    session_id = properties.get("sessionID")
    _STATE["session_id"] = _STATE["session_id"] or session_id
    _STATE["idle_seen"] = True
    _STATE["busy"] = False
    # Success requires all three observed signals: idle, a final assistant
    # message, and no error/abort. A delta is not a final message: it may be a
    # truncated SSE fragment. Never turn an idle-only status into fake success.
    if _STATE["terminal_failure"] is None and not _STATE["aborted"]:
        active_tools = [
            lifecycle["name"]
            for lifecycle in _STATE["tools"].values()
            if not lifecycle.get("completed")
        ]
        if active_tools:
            _STATE["terminal_failure"] = {
                "kind": "protocol_error",
                "message": "OpenCode protocol failure: session.idle with active tool parts",
            }
            _finalize_terminal()
            return
        final_text = "".join(_STATE["text_parts"])
        final_message = _STATE["message"]
        if (
            not isinstance(final_message, dict)
            or final_message.get("role") != "assistant"
            or not final_text
        ):
            _STATE["terminal_failure"] = {
                "kind": "protocol_error",
                "message": "OpenCode protocol failure: session.idle without a final assistant message",
            }
            _finalize_terminal()
            return
        _emit("message.completed", {"message_id": final_message.get("id"), "text": final_text}, raw_line)
        _emit(
            "agent_settled",
            {"aborted": False, "settled": "idle", "settled_line": raw_line},
            raw_line,
        )
        _STATE["settled"] = True
        _STATE["settled_line"] = raw_line
        _finalize_terminal()


def translate(record: dict, raw_line: int) -> None:
    record_type = record.get("type")
    properties = record.get("properties") if isinstance(record.get("properties"), dict) else {}
    if record_type in ("server.connected", "server.heartbeat"):
        return
    if record_type == "session.status":
        _handle_session_status(properties, raw_line)
    elif record_type in ("session.created", "session.updated"):
        _handle_session_created(properties, raw_line)
    elif record_type == "message.updated":
        _handle_message_updated(properties, raw_line)
    elif record_type == "message.part.updated":
        _handle_message_part_updated(properties, raw_line)
    elif record_type == "message.part.delta":
        _handle_message_part_delta(properties, raw_line)
    elif record_type == "session.diff":
        _emit("diagnostic", {"code": "session_diff", "diff_count": len(properties.get("diff") or [])}, raw_line)
    elif record_type == "session.idle":
        _handle_session_idle(properties, raw_line)
    elif record_type == "session.error":
        _handle_session_error(properties, raw_line)
    elif record_type == "session.compacted":
        _emit(
            "context.compacted",
            {"session_id": properties.get("sessionID") or properties.get("sessionId")},
            raw_line,
        )
    elif record_type in ("permission", "question", "permission.updated", "permission.replied", "question.updated", "question.replied"):
        # A tool/permission block would leave the run non-idle; classify (probe 待测)
        # so the pipeline can diagnose rather than hang. Live runners detect the
        # resulting long non-idle session via the readiness/timeout policy.
        _emit(
            "diagnostic",
            {
                "code": "permission_block" if not record_type.endswith("replied") else "permission_replied",
                "type": record_type,
                "permission_id": properties.get("permissionID") or properties.get("permissionId"),
            },
            raw_line,
        )
    elif record_type == "message.removed":
        message_id = properties.get("messageID") or properties.get("messageId")
        if message_id:
            _STATE["messages"].pop(message_id, None)
            if _STATE["message"].get("id") == message_id:
                _STATE["message"] = {}
            _refresh_text()
        _emit("diagnostic", {"code": "message_removed"}, raw_line)
    elif record_type == "message.part.removed":
        message_id = properties.get("messageID") or properties.get("messageId")
        part_id = properties.get("partID") or properties.get("partId")
        if message_id and part_id:
            _STATE["messages"].get(message_id, {}).pop(part_id, None)
            _refresh_text()
        _emit("diagnostic", {"code": "message_part_removed"}, raw_line)
    elif record_type in {"todo.updated", "command.executed"}:
        _emit("diagnostic", {"code": "opencode_event_observed", "type": record_type}, raw_line)
    elif record_type in _IGNORED_KNOWN_EVENTS:
        return
    else:
        _emit("diagnostic", {"code": "unknown_raw_event", "type": record_type}, raw_line)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-file", required=True, type=Path)
    args = parser.parse_args()
    args.raw_file.parent.mkdir(parents=True, exist_ok=True)

    line_no = 0
    with args.raw_file.open("a", encoding="utf-8") as handle:
        for raw_input in sys.stdin:
            raw_input = raw_input.rstrip("\n")
            if not raw_input.strip():
                continue
            input_text = sanitize(raw_input)
            if not input_text:
                continue
            try:
                record = json.loads(input_text)
            except json.JSONDecodeError:
                record = None
                raw_text = input_text
            else:
                record = redact_hidden_reasoning(record)
                raw_text = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            handle.write(raw_text + "\n")
            handle.flush()
            line_no += 1
            _STATE["last_line"] = line_no
            if record is None:
                _emit("diagnostic", {"code": "non_json_raw_line", "text": raw_text[:500]}, line_no)
                continue
            if not isinstance(record, dict):
                _emit("diagnostic", {"code": "non_object_raw_event"}, line_no)
                continue
            translate(record, line_no)
            if _STATE["terminal"] is not None:
                # Terminal is final; do not process further records.
                break
    # EOF without all settled signals is a protocol failure. In particular, a
    # status/SSE fragment cannot prove an assistant turn completed successfully.
    if _STATE["terminal"] is None and not _STATE["settled"]:
        _STATE["terminal_failure"] = {
            "kind": "protocol_error",
            "message": "OpenCode protocol failure: event stream ended before settled idle",
        }
    _finalize_terminal()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
