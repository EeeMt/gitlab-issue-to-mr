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

For OpenCode first release the attempt has no live command plane (manifest
``steering=false``/``follow_up=false``, control state ``disabled``), so settled
converges a single harness terminal directly — there is no accepting->closing
->drain gate. ``agent_settled`` is still surfaced as an auditable diagnostic
marker so the projector's settled handling stays uniform across harnesses.

Transport is owned by the Bridge (see opencode_bridge.py): it establishes the
SSE subscription, creates the session, sends the frozen startup ``command`` or
``prompt_async``, and falls back to ``GET /session/status`` after a disconnect.
This module only normalizes records.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

from result_builder import v2_harness_block
from sanitize import clean_message, redact_hidden_reasoning, sanitize, sanitize_json_value

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
_INTERACTIVE_EVENT_TYPES = frozenset(
    {
        "permission.asked",
        "permission.v2.asked",
        "permission.replied",
        "permission.v2.replied",
        "question.asked",
        "question.v2.asked",
        "question.replied",
        "question.v2.replied",
        "question.rejected",
        "question.v2.rejected",
    }
)
_CANONICAL_CLOSED_TYPES = frozenset({"worker.finalization", "run.completed", "run.failed"})
_HARNESS_TERMINAL_TYPES = frozenset({"harness.completed", "harness.failed"})

# These are OpenCode server/catalog/UI events. They are deliberately explicit
# no-ops: the sanitized raw SSE archive remains the source of truth, while
# catalog chatter must not become hundreds of misleading task diagnostics.
_IGNORED_KNOWN_EVENTS = frozenset(
    {
        "catalog.updated",
        "models-dev.refreshed",
        "integration.updated",
        "integration.connection.updated",
        "plugin.added",
        "reference.updated",
        "server.instance.disposed",
        "global.disposed",
        "installation.updated",
        "installation.update-available",
        "lsp.client.diagnostics",
        "lsp.updated",
        "file.edited",
        "file.watcher.updated",
        "vcs.branch.updated",
        "session.deleted",
        "project.directories.updated",
        "project.updated",
        "tui.prompt.append",
        "tui.command.execute",
        "tui.toast.show",
        "pty.created",
        "pty.updated",
        "pty.exited",
        "pty.deleted",
        "mcp.tools.changed",
        "server.heartbeat",
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
    # Open reasoning blocks keyed by canonical reasoning_id (plan §4.4). Only
    # blocks whose started was observed are ever completed/interrupted here;
    # closed blocks stay recorded so replays never emit a second lifecycle.
    "reasoning_blocks": {},                  # reasoning_id -> {message_id, family, status}
    # The first valid family to surface for one assistant message owns every
    # reasoning block in that message. This preserves the native part ids on
    # the frozen 1.18.19 path and avoids cross-family double projection.
    "reasoning_family_by_message": {},       # assistant message_id -> "part" | "durable"
    "interactive_block": None,
    "settled": False,
    "settled_line": None,
    "last_line": 1,
}
_REAL_SESSION_ID: str = ""


def _capture_real_session_id(raw_text: str) -> None:
    """Keep OpenCode's unmasked session id before sanitization so resume stays possible."""
    global _REAL_SESSION_ID
    if _REAL_SESSION_ID:
        return
    try:
        record = json.loads(raw_text)
    except json.JSONDecodeError:
        return
    properties = record.get("properties") if isinstance(record, dict) else None
    session_id = (
        properties.get("sessionID") or properties.get("sessionId")
        if isinstance(properties, dict)
        else None
    )
    if session_id is None and isinstance(record, dict):
        data = record.get("data")
        if isinstance(data, dict):
            session_id = data.get("sessionID") or data.get("sessionId")
    if isinstance(session_id, str) and session_id and "<" not in session_id:
        _REAL_SESSION_ID = session_id


def _session_id(value: object = None) -> str | None:
    """Return the real session id when captured, else the sanitized fallback."""
    if _REAL_SESSION_ID:
        return _REAL_SESSION_ID
    fallback = value if value is not None else _STATE.get("session_id")
    return fallback if isinstance(fallback, str) and fallback else None


def _failure_kind(message: str, *, status_code: object = None) -> str:
    if isinstance(status_code, (int, float)) and not isinstance(status_code, bool):
        if int(status_code) == 401:
            return "authentication_error"
        if int(status_code) == 429:
            return "rate_limited"
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


def _error_message(value: object, default: str) -> tuple[str, object]:
    """Extract a bounded message/status from OpenCode's structured errors."""
    status_code = None
    if isinstance(value, dict):
        status_code = value.get("statusCode")
        if status_code is None:
            status_code = value.get("status_code") or value.get("status")
        # OpenCode's APIError envelope keeps the provider response under
        # ``error.data``. Read that nested record before falling back to the
        # outer error name, otherwise a real HTTP 429/401 is reduced to the
        # unhelpful ``APIError``/engine_error pair.
        nested_data = value.get("data")
        if isinstance(nested_data, dict):
            nested_message, nested_status = _error_message(nested_data, default)
            status_code = status_code if status_code is not None else nested_status
            if nested_status is not None or nested_message != default:
                return nested_message, status_code
        message_value = (
            value.get("message")
            or value.get("error")
            or value.get("detail")
            or value.get("name")
            or value.get("code")
        )
        if isinstance(message_value, dict):
            message_value, nested_status = _error_message(message_value, default)
            status_code = status_code if status_code is not None else nested_status
            return message_value, status_code
        message = str(message_value or default)
    else:
        message = str(value or default)
    return clean_message(sanitize(message))[:_TOOL_OUTPUT_MAX_CHARS], status_code


def _remember_session(properties: dict) -> None:
    session_id = properties.get("sessionID") or properties.get("sessionId")
    if session_id:
        _STATE["session_id"] = _STATE["session_id"] or _session_id(session_id)


def _remember_assistant_message(message_id: object) -> str | None:
    if message_id is None or not str(message_id).strip():
        return None
    normalized = str(message_id).strip()
    if normalized not in _STATE["assistant_message_ids"]:
        _STATE["assistant_message_ids"].append(normalized)
    current = _STATE.get("message")
    if not isinstance(current, dict) or current.get("id") != normalized:
        _STATE["message"] = {"id": normalized, "role": "assistant"}
    else:
        current["role"] = "assistant"
    return normalized


def _is_rate_limit_reason(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized in _RATE_LIMIT_REASONS


def _emit(event_type: str, payload: dict, raw_line: int) -> None:
    writer = os.environ["CODIFY_CANONICAL_EVENT_WRITER"]
    try:
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
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        # A container cancellation can close the canonical Task stream while
        # OpenCode's already-buffered SSE records are still being translated.
        # Keep the writer strict; discard only this translator's late event
        # after the shared stream has reached its terminal boundary.
        if _canonical_stream_closed(event_type):
            return
        if exc.stderr:
            sys.stderr.write(exc.stderr)
        raise


def _canonical_stream_closed(event_type: str) -> bool:
    """Return whether the shared canonical stream is already non-appendable.

    The event writer serializes appends with the same lock. Taking a shared
    lock here prevents a partial final JSON line from turning a known terminal
    into an ordinary translator error while another finalizer is appending.
    """
    runtime_dir = os.environ.get("CODIFY_RUNTIME_DIR", "").strip()
    if not runtime_dir:
        return False
    event_path = Path(runtime_dir) / "event.jsonl"
    lock_path = Path(runtime_dir) / ".event.lock"
    try:
        lock_path.touch(exist_ok=True)
        with lock_path.open("r+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            try:
                last_type = None
                harness_terminal_seen = False
                for line in event_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        current_type = json.loads(line).get("type")
                        last_type = current_type
                        harness_terminal_seen = (
                            harness_terminal_seen or current_type in _HARNESS_TERMINAL_TYPES
                        )
                return last_type in _CANONICAL_CLOSED_TYPES or (
                    event_type in _HARNESS_TERMINAL_TYPES and harness_terminal_seen
                )
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    except (OSError, json.JSONDecodeError, TypeError):
        # An unreadable or malformed stream is not evidence of a settled Task;
        # preserve the original writer error for diagnosis.
        return False


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


def _display_tool_name(part: dict | object) -> str:
    raw_name = _raw_tool_name(part) if isinstance(part, dict) else str(part or "unknown")
    raw_name = raw_name.strip() or "unknown"
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


def _durable_tool_input(data: dict, lifecycle: dict | None = None) -> dict:
    value = data.get("input")
    if value is None and lifecycle is not None:
        value = lifecycle.get("input")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"raw": sanitize(value)[:_TOOL_VALUE_MAX_CHARS]}
        value = parsed
    sanitized = _sanitize_value(value)
    if isinstance(sanitized, dict):
        return sanitized
    if sanitized is None:
        return {}
    return {"value": sanitized}


def _durable_tool_output(data: dict) -> str:
    value = data.get("result")
    if value is None:
        value = data.get("content")
    if isinstance(value, dict) and "content" in value:
        value = value.get("content")
    sanitized = _sanitize_value(value)
    if isinstance(sanitized, list):
        text_parts = [
            item.get("text")
            for item in sanitized
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ]
        if text_parts:
            return "".join(text_parts)[:_TOOL_OUTPUT_MAX_CHARS]
    if isinstance(sanitized, str):
        return sanitized[:_TOOL_OUTPUT_MAX_CHARS]
    if sanitized is None:
        return ""
    return json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))[:_TOOL_OUTPUT_MAX_CHARS]


def _durable_tool_lifecycle(
    data: dict,
    raw_line: int,
    *,
    name: object = None,
    terminal: str | None = None,
    error_value: object = None,
    output_data: dict | None = None,
) -> None:
    tool_id = str(data.get("callID") or data.get("callId") or "").strip()
    if not tool_id:
        _emit("diagnostic", {"code": "tool_missing_id", "name": _display_tool_name(name)}, raw_line)
        return
    previous = _STATE.setdefault("tools", {}).get(tool_id)
    raw_name = (
        name
        if name is not None
        else data.get("tool")
        or data.get("name")
        or (previous or {}).get("name")
    )
    display_name = _display_tool_name(raw_name)
    lifecycle = _STATE.setdefault("tools", {}).setdefault(
        tool_id,
        {"name": display_name, "input": {}, "started": False, "completed": False},
    )
    lifecycle["name"] = display_name
    if isinstance(data.get("input"), (dict, list, str)):
        lifecycle["input"] = _durable_tool_input(data, lifecycle)
    elif lifecycle.get("input_text") and not lifecycle.get("input"):
        lifecycle["input"] = _durable_tool_input(
            {"input": lifecycle["input_text"]}, lifecycle
        )

    if not lifecycle["started"] and terminal != "progress":
        _emit(
            "tool.started",
            {
                "tool_id": tool_id,
                "name": display_name,
                "input": redact_hidden_reasoning(lifecycle.get("input") or {}),
            },
            raw_line,
        )
        lifecycle["started"] = True

    if terminal is None or terminal == "progress" or lifecycle["completed"]:
        return
    error_message = None
    if error_value is not None:
        error_message, _ = _error_message(error_value, "OpenCode tool failed")
    result_source = output_data if isinstance(output_data, dict) else data
    result = result_source.get("result")
    exit_code = None
    if isinstance(result, dict):
        exit_code = result.get("exitCode")
        if exit_code is None:
            exit_code = result.get("exit_code")
    failed = (
        terminal in {"failed", "error"}
        or error_value is not None
        or (isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0)
    )
    payload = {
        "tool_id": tool_id,
        "name": display_name,
        "output": _durable_tool_output(output_data or data),
        "error": failed,
    }
    if error_message:
        payload["error_message"] = error_message
    if isinstance(result, dict):
        if isinstance(exit_code, int) and not isinstance(exit_code, bool):
            payload["exit_code"] = exit_code
    _emit("tool.completed", payload, raw_line)
    lifecycle["completed"] = True


def _durable_data(record: dict, properties: dict) -> dict:
    data = record.get("data")
    return data if isinstance(data, dict) else properties


def _reasoning_message_id(value: object) -> str | None:
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def _durable_reasoning_id(data: dict) -> str | None:
    """Stable per-block identity for the durable ``session.next.reasoning.*``
    family: session + assistant message + reasoningID (plan §3.2). Both the
    started and the ended event carry these native fields, so the derived id
    pairs across the lifecycle and never reuses a bare per-message index.
    """
    message_id = _reasoning_message_id(data.get("assistantMessageID") or data.get("messageID"))
    reasoning_id = _reasoning_message_id(data.get("reasoningID") or data.get("reasoningId"))
    if not message_id or not reasoning_id:
        return None
    session_id = _reasoning_message_id(data.get("sessionID") or data.get("sessionId"))
    if session_id:
        return f"opencode-reason-{session_id}-{message_id}-{reasoning_id}"
    return f"opencode-reason-{message_id}-{reasoning_id}"


def _part_reasoning_id(session_id: object, message_id: str, part_id: str) -> str | None:
    """Stable identity for the ``message.part.updated`` fallback family.

    The snapshot is attributed by session + message + part id. Sentinel ids
    (``__unattributed__``/``__default__``) mean the block cannot be stably
    distinguished, so no lifecycle is projected for it.
    """
    if not message_id or not part_id or message_id.startswith("__") or part_id.startswith("__"):
        return None
    session_id = _reasoning_message_id(session_id)
    if session_id:
        return f"opencode-reason-part-{session_id}-{message_id}-{part_id}"
    return f"opencode-reason-part-{message_id}-{part_id}"


def _open_reasoning_block(
    canonical_id: str, message_id: str | None, family: str, raw_line: int
) -> None:
    """Emit ``reasoning_summary.started`` for the first observation of a block.

    Duplicate started snapshots (reconnect replays) never open a second
    placeholder: an already-open block is kept, and a block whose end was
    already observed is never re-opened into a fresh active placeholder.
    """
    block = _STATE["reasoning_blocks"].get(canonical_id)
    if block is not None:
        return
    _STATE["reasoning_blocks"][canonical_id] = {
        "message_id": message_id,
        "family": family,
        "status": "open",
    }
    _emit("reasoning_summary.started", {"reasoning_id": canonical_id}, raw_line)


def _close_reasoning_block(canonical_id: str, raw_line: int) -> None:
    """Complete an open block in place, at most once per block.

    Reasoning text never enters canonical payloads (plan §3.1), so the
    completion is body-less; an empty completion still stops the placeholder
    timer in place. Repeated end snapshots for an already-closed block are
    silent replays.
    """
    block = _STATE["reasoning_blocks"].get(canonical_id)
    if block is None or block["status"] != "open":
        return
    block["status"] = "closed"
    _emit(
        "reasoning_summary.completed",
        {"reasoning_id": canonical_id, "client": "opencode"},
        raw_line,
    )


def _record_orphan_reasoning_end(canonical_id: str, message_id: str | None, family: str, raw_line: int) -> None:
    """Close the book on an end snapshot whose start was never observed.

    Reasoning was already finished when first seen, so no active placeholder
    may be fabricated (plan §3.2); the fact stays an auditable diagnostic and
    the id is recorded as closed so a later stale started replay cannot start
    it either.
    """
    if canonical_id not in _STATE["reasoning_blocks"]:
        _STATE["reasoning_blocks"][canonical_id] = {
            "message_id": message_id,
            "family": family,
            "status": "closed",
        }
    _emit(
        "diagnostic",
        {"code": "reasoning_completed_without_start", "reasoning_id": canonical_id},
        raw_line,
    )


def _interrupt_open_reasoning(
    reason: str, raw_line: int, message_id: str | None = None
) -> None:
    """Interrupt open reasoning blocks whose native end will never arrive.

    Blocks that already delivered their own end stay completed; this only
    closes blocks still open, so the caller may run it repeatedly (idle,
    EOF, failure finalization) without double events. ``message_id`` narrows
    the close to one assistant message (its message errored/aborted); whole
    run failures close every open block.
    """
    for canonical_id in list(_STATE["reasoning_blocks"]):
        block = _STATE["reasoning_blocks"][canonical_id]
        if block["status"] != "open":
            continue
        if message_id and block.get("message_id") and block["message_id"] != message_id:
            continue
        _emit(
            "reasoning_summary.interrupted",
            {"reasoning_id": canonical_id, "reason": reason},
            raw_line,
        )
        block["status"] = "closed"


def _handle_durable_event(record_type: str, data: dict, raw_line: int) -> None:
    """Map OpenCode's ``session.next.*`` durable event family.

    OpenCode 1.18.19 exposes this second event shape alongside the older
    ``properties`` events. The durable payload puts execution facts under
    ``data``; the canonical contract stays unchanged, so only facts with a
    safe existing canonical equivalent are promoted and the rest are retained
    as explicit diagnostics/raw evidence.
    """
    _remember_session(data)

    if record_type == "session.next.text.started":
        message_id = _remember_assistant_message(data.get("assistantMessageID"))
        if message_id:
            _part_state(message_id, str(data.get("textID") or "__default__"))
        return

    if record_type == "session.next.text.delta":
        delta = data.get("delta")
        message_id = _remember_assistant_message(data.get("assistantMessageID"))
        if not isinstance(delta, str) or not message_id:
            _emit(
                "diagnostic",
                {"code": "invalid_durable_text_delta", "type": record_type},
                raw_line,
            )
            return
        part_id = str(data.get("textID") or "__default__")
        state = _part_state(message_id, part_id)
        if delta and not state["text"].endswith(delta):
            state["text"] += delta
            _emit("message.delta", {"content": delta, "role": "assistant"}, raw_line)
        _refresh_text()
        return

    if record_type == "session.next.text.ended":
        message_id = _remember_assistant_message(data.get("assistantMessageID"))
        text = data.get("text")
        if not message_id or not isinstance(text, str):
            _emit(
                "diagnostic",
                {"code": "invalid_durable_text_end", "type": record_type},
                raw_line,
            )
            return
        _part_state(message_id, str(data.get("textID") or "__default__"))["text"] = text
        _refresh_text()
        return

    if record_type == "session.next.reasoning.started":
        message_id = _remember_assistant_message(data.get("assistantMessageID"))
        reasoning_id = _durable_reasoning_id(data)
        if not reasoning_id:
            _emit(
                "diagnostic",
                {"code": "reasoning_missing_id", "type": record_type},
                raw_line,
            )
            return
        if message_id:
            family = _STATE["reasoning_family_by_message"].get(message_id)
            if family == "part":
                # Frozen native part snapshots own this message. Durable is
                # an optional compatibility family, so it is ignored rather
                # than folded onto a non-unique part block.
                return
            _STATE["reasoning_family_by_message"].setdefault(message_id, "durable")
        if _STATE["reasoning_family_by_message"].get(message_id) == "part":
            return
        _open_reasoning_block(reasoning_id, message_id, "durable", raw_line)
        return

    if record_type == "session.next.reasoning.ended":
        message_id = _remember_assistant_message(data.get("assistantMessageID"))
        reasoning_id = _durable_reasoning_id(data)
        if not reasoning_id:
            _emit(
                "diagnostic",
                {"code": "reasoning_missing_id", "type": record_type},
                raw_line,
            )
            return
        if message_id:
            family = _STATE["reasoning_family_by_message"].get(message_id)
            if family == "part":
                return
            _STATE["reasoning_family_by_message"].setdefault(message_id, "durable")
        if reasoning_id in _STATE["reasoning_blocks"]:
            _close_reasoning_block(reasoning_id, raw_line)
            return
        # Ended without any observed started: an already-finished block, never
        # a fresh active placeholder (plan §3.2).
        _record_orphan_reasoning_end(reasoning_id, message_id, "durable", raw_line)
        return

    # Reasoning deltas and any other reasoning.* subtype carry only streaming
    # text that must never enter a canonical payload. They add no lifecycle
    # fact and must not extend an open placeholder (plan §4.4); the sanitized
    # raw archive remains the audit trail, so nothing further is emitted.
    if record_type.startswith("session.next.reasoning."):
        return

    if record_type == "session.next.tool.input.started":
        _durable_tool_lifecycle(
            data,
            raw_line,
            name=data.get("name"),
            terminal="progress",
        )
        return

    if record_type == "session.next.tool.input.delta":
        tool_id = str(data.get("callID") or data.get("callId") or "").strip()
        if tool_id:
            lifecycle = _STATE.setdefault("tools", {}).setdefault(
                tool_id,
                {"name": "unknown", "input": {}, "started": False, "completed": False},
            )
            delta = data.get("delta")
            if isinstance(delta, str):
                lifecycle["input_text"] = lifecycle.get("input_text", "") + delta
        _emit(
            "diagnostic",
            {"code": "tool_input_delta", "tool_id": tool_id or None},
            raw_line,
        )
        return

    if record_type == "session.next.tool.input.ended":
        tool_id = str(data.get("callID") or data.get("callId") or "").strip()
        if tool_id:
            lifecycle = _STATE.setdefault("tools", {}).setdefault(
                tool_id,
                {"name": "unknown", "input": {}, "started": False, "completed": False},
            )
            text = data.get("text")
            if isinstance(text, str):
                lifecycle["input_text"] = text
                lifecycle["input"] = _durable_tool_input({"input": text}, lifecycle)
        _emit(
            "diagnostic",
            {"code": "tool_input_ended", "tool_id": tool_id or None},
            raw_line,
        )
        return

    if record_type == "session.next.tool.called":
        _durable_tool_lifecycle(data, raw_line, name=data.get("tool"))
        return

    if record_type == "session.next.tool.progress":
        _durable_tool_lifecycle(data, raw_line, name=data.get("tool"), terminal="progress")
        _emit(
            "diagnostic",
            {
                "code": "tool_progress",
                "tool_id": data.get("callID") or data.get("callId"),
            },
            raw_line,
        )
        return

    if record_type in {"session.next.tool.success", "session.next.tool.failed"}:
        error_value = data.get("error") if record_type.endswith("failed") else None
        _durable_tool_lifecycle(
            data,
            raw_line,
            name=data.get("tool"),
            terminal="failed" if record_type.endswith("failed") else "completed",
            error_value=error_value,
        )
        return

    if record_type == "session.next.shell.started":
        _durable_tool_lifecycle(
            {
                **data,
                "tool": "bash",
                "input": {"command": data.get("command") or ""},
            },
            raw_line,
            name="bash",
        )
        return

    if record_type == "session.next.shell.ended":
        _durable_tool_lifecycle(
            {**data, "tool": "bash"},
            raw_line,
            name="bash",
            terminal="completed",
            output_data={"result": data.get("output")},
        )
        return

    if record_type == "session.next.step.ended":
        tokens = data.get("tokens")
        if isinstance(tokens, dict):
            _STATE["usage"] = _usage({"tokens": tokens, "cost": data.get("cost")})
            _emit("usage.updated", {"usage": _STATE["usage"]}, raw_line)
        _emit(
            "diagnostic",
            {
                "code": "step_ended",
                "finish": data.get("finish"),
                "file_count": len(data.get("files") or []) if isinstance(data.get("files"), list) else None,
            },
            raw_line,
        )
        return

    if record_type == "session.next.step.failed":
        message, status_code = _error_message(data.get("error"), "OpenCode step failed")
        _STATE["terminal_failure"] = {
            "kind": _failure_kind(message, status_code=status_code),
            "message": message,
        }
        # The failed step will never deliver its open reasoning block ends;
        # interrupt them now so no placeholder keeps spinning (plan §4.4).
        _interrupt_open_reasoning("step_failed", raw_line)
        _emit(
            "diagnostic",
            {
                "code": "step_failed",
                "message": message,
                "failure_kind": _STATE["terminal_failure"]["kind"],
            },
            raw_line,
        )
        return

    if record_type == "session.next.retried":
        message, status_code = _error_message(data.get("error"), "OpenCode provider retry")
        retryable = data.get("error", {}).get("isRetryable") if isinstance(data.get("error"), dict) else None
        _emit(
            "provider.retry",
            {
                "attempt": data.get("attempt"),
                "failure_kind": _failure_kind(message, status_code=status_code),
            },
            raw_line,
        )
        if retryable is False:
            _STATE["terminal_failure"] = {
                "kind": _failure_kind(message, status_code=status_code),
                "message": message,
            }
        else:
            _STATE["terminal_failure"] = None
        return

    if record_type == "session.next.compaction.started":
        _emit(
            "diagnostic",
            {"code": "compaction_started", "reason": data.get("reason")},
            raw_line,
        )
        return

    if record_type == "session.next.compaction.delta":
        _emit("diagnostic", {"code": "compaction_delta"}, raw_line)
        return

    if record_type == "session.next.compaction.ended":
        payload = {
            "session_id": _session_id(data.get("sessionID") or data.get("sessionId")),
            "reason": data.get("reason"),
        }
        summary = data.get("text")
        if isinstance(summary, str) and summary:
            payload["summary"] = sanitize(summary)[:_TOOL_OUTPUT_MAX_CHARS]
        _emit("context.compacted", payload, raw_line)
        return

    # Prompt, model, step-start, revert, context and agent-switch events are
    # meaningful protocol observations but have no safe existing canonical
    # equivalent. Keep them explicit instead of allowing a silent drop or an
    # unexplained unknown event.
    payload = {"code": "opencode_durable_event", "type": record_type}
    for key in ("sessionID", "messageID", "assistantMessageID", "callID", "agent"):
        if data.get(key) is not None:
            payload[key] = data[key]
    _emit("diagnostic", payload, raw_line)


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
        error_value = state.get("error")
        error_message = None
        if error_value:
            error_message, _ = _error_message(error_value, "OpenCode tool failed")
        metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
        exit_code = metadata.get("exit")
        if exit_code is None:
            exit_code = metadata.get("exit_code")
        error = (
            status != "completed"
            or error_value is not None
            or (isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0)
        )
        payload = {
            "tool_id": tool_id,
            "name": name,
            "output": _tool_output(part),
            "error": error,
        }
        if error_message:
            payload["error_message"] = error_message
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
    if _STATE["aborted"] or _STATE["terminal_failure"] is not None:
        # Safety net for every failing terminal: reasoning blocks still open
        # when the run fails (rate limits, protocol errors, EOF, interactive
        # blocks, ...) must be interrupted, never left spinning. The source
        # failure events already interrupt with specific reasons, so this is
        # a no-op once they ran.
        _interrupt_open_reasoning(
            "aborted"
            if _STATE["aborted"]
            else str((_STATE["terminal_failure"] or {}).get("kind") or "run_failed"),
            terminal_line,
        )
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
    _remember_session(properties)


def _handle_session_created(properties: dict, raw_line: int) -> None:
    _remember_session(properties)


def _interactive_request_id(properties: dict) -> object:
    for key in ("id", "permissionID", "permissionId", "questionID", "questionId"):
        if properties.get(key) is not None:
            return properties[key]
    return None


def _handle_interactive_event(record_type: str, properties: dict, raw_line: int) -> None:
    """Fail closed for permission/question prompts the first release cannot answer."""
    _remember_session(properties)
    request_id = _interactive_request_id(properties)
    asked = record_type.endswith(".asked") or record_type in {
        "permission",
        "question",
        "permission.updated",
        "question.updated",
    }
    rejected = record_type.endswith(".rejected")
    is_permission = "permission" in record_type
    if asked:
        kind = "sandbox_error" if is_permission else "engine_error"
        message = (
            f"OpenCode {record_type} requires an interactive response; "
            "the Codify first-release control plane cannot answer it"
        )
        _STATE["interactive_block"] = request_id or record_type
        _STATE["terminal_failure"] = {"kind": kind, "message": message}
        _emit(
            "diagnostic",
            {
                "code": "interactive_request_unsupported",
                "type": record_type,
                "request_id": request_id,
                "failure_kind": kind,
            },
            raw_line,
        )
        _finalize_terminal()
        return

    code = "interactive_request_rejected" if rejected else "interactive_request_replied"
    _emit(
        "diagnostic",
        {"code": code, "type": record_type, "request_id": request_id},
        raw_line,
    )


def _handle_session_error(properties: dict, raw_line: int) -> None:
    _remember_session(properties)
    error = properties.get("error") or properties.get("message")
    message, status_code = _error_message(error, "OpenCode session error")
    kind = _failure_kind(message, status_code=status_code)
    if kind == "cancelled":
        _STATE["aborted"] = True
    # The errored/aborted session never completes its open reasoning blocks;
    # close them with the native cause instead of leaving them spinning.
    _interrupt_open_reasoning("aborted" if _STATE["aborted"] else "session_error", raw_line)
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
        _remember_assistant_message(message_id)
        _flush_pending_deltas(message_id)
        _refresh_text()
        # An errored/aborted assistant message (native error fact, e.g. the
        # post-abort message carries error:true) means its reasoning blocks
        # will never deliver their own end; interrupt exactly those blocks.
        if info.get("error") or properties.get("error"):
            target = (
                message_id
                if isinstance(message_id, str) and message_id and message_id != "__assistant__"
                else None
            )
            _interrupt_open_reasoning("message_error", raw_line, message_id=target)
    _remember_session(properties)


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


def _handle_reasoning_part(properties: dict, part: dict, raw_line: int) -> None:
    """Map OpenCode 1.18.19 ``ReasoningPart`` snapshots.

    ``message.part.updated`` is the frozen, primary reasoning family. Its
    actual schema uses ``time.start`` to prove the block began and the
    presence of ``time.end`` to prove it ended; ``state.status`` belongs to a
    ToolPart and must never be used for reasoning. The optional
    ``session.next.reasoning.*`` compatibility mapping remains below for
    non-frozen servers, but the native part snapshot is the path exercised by
    1.18.19.
    """
    timing = part.get("time") if isinstance(part.get("time"), dict) else {}
    started_at = timing.get("start")
    ended_at = timing.get("end")
    valid_started_at = isinstance(started_at, (int, float)) and not isinstance(started_at, bool)
    ended = isinstance(ended_at, (int, float)) and not isinstance(ended_at, bool)
    if not valid_started_at:
        # No native lifecycle evidence in this snapshot. Keep hidden reasoning
        # out of canonical payloads and never invent a placeholder from text.
        _emit(
            "diagnostic",
            {"code": "hidden_reasoning_omitted", "message": "OpenCode reasoning omitted"},
            raw_line,
        )
        return
    message_id = _message_id(properties, part)
    if message_id in _STATE["user_message_ids"]:
        return
    part_id = _part_id(properties, part, message_id)
    session_id = properties.get("sessionID") or properties.get("sessionId") or part.get("sessionID")
    reasoning_id = _part_reasoning_id(session_id, message_id, part_id)
    if not reasoning_id:
        _emit(
            "diagnostic",
            {"code": "reasoning_missing_id", "type": "message.part.updated"},
            raw_line,
        )
        return
    family = _STATE["reasoning_family_by_message"].get(message_id)
    if family == "durable":
        # Durable appeared first for this message; keep its compatibility
        # lifecycle stable and suppress all native snapshots for it.
        return
    _STATE["reasoning_family_by_message"].setdefault(message_id, "part")
    if not ended:
        _open_reasoning_block(reasoning_id, message_id, "part", raw_line)
        return
    # ``time.end`` is an authoritative end even when reasoning text is empty.
    if reasoning_id in _STATE["reasoning_blocks"]:
        _close_reasoning_block(reasoning_id, raw_line)
        return
    # Already-finished first snapshot: no start may be fabricated.
    _record_orphan_reasoning_end(reasoning_id, message_id, "part", raw_line)


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
        _handle_reasoning_part(properties, part, raw_line)
    elif part_type == "retry":
        message = part.get("error") or part.get("message") or "OpenCode provider retry"
        error_message, status_code = _error_message(message, "OpenCode provider retry")
        _emit(
            "provider.retry",
            {
                "attempt": part.get("attempt"),
                "max_attempts": part.get("maxAttempts"),
                "failure_kind": _failure_kind(error_message, status_code=status_code),
                "retry_delay_ms": part.get("delayMs"),
            },
            raw_line,
        )
    elif part_type == "compaction":
        payload = {
            "session_id": _session_id(properties.get("sessionID") or properties.get("sessionId")),
            "reason": part.get("reason"),
            "auto": part.get("auto"),
            "overflow": part.get("overflow"),
            "tail_start_id": part.get("tail_start_id"),
        }
        _emit("context.compacted", {key: value for key, value in payload.items() if value is not None}, raw_line)
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
    _remember_session(properties)
    _STATE["idle_seen"] = True
    _STATE["busy"] = False
    if _STATE["terminal_failure"] is not None or _STATE["aborted"]:
        # A failed step/compaction or an abort may be followed by the normal
        # idle marker. It must still converge; otherwise the bridge waits for
        # the server's heartbeat forever after the failure was already known.
        _finalize_terminal()
        return
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
        # session.idle closes the turn. Reasoning blocks that never delivered
        # their own end must not be completed retroactively (session.idle is
        # not a block-end signal, plan §4.4): interrupt them so no placeholder
        # keeps spinning after the run settled cleanly.
        _interrupt_open_reasoning("idle_without_block_end", raw_line)
        _emit("message.completed", {"message_id": final_message.get("id"), "text": final_text}, raw_line)
        _emit(
            "agent_settled",
            {"aborted": False, "settled": "idle", "settled_line": raw_line},
            raw_line,
        )
        _STATE["settled"] = True
        _STATE["settled_line"] = raw_line
        _finalize_terminal()


def _handle_observed_failure_event(record_type: str, properties: dict, raw_line: int) -> None:
    _remember_session(properties)
    error = properties.get("error") or properties.get("message") or record_type
    message, status_code = _error_message(error, f"OpenCode event {record_type}")
    _emit(
        "diagnostic",
        {
            "code": "opencode_event_failure",
            "type": record_type,
            "message": message,
            "failure_kind": _failure_kind(message, status_code=status_code),
        },
        raw_line,
    )


def translate(record: dict, raw_line: int) -> None:
    record_type = record.get("type")
    properties = record.get("properties") if isinstance(record.get("properties"), dict) else {}
    if isinstance(record_type, str) and record_type.startswith("session.next."):
        _handle_durable_event(record_type, _durable_data(record, properties), raw_line)
        return
    elif record_type in ("server.connected", "server.heartbeat"):
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
            {"session_id": _session_id(properties.get("sessionID") or properties.get("sessionId"))},
            raw_line,
        )
    elif record_type in _INTERACTIVE_EVENT_TYPES or record_type in {
        "permission",
        "question",
        "permission.updated",
        "question.updated",
    }:
        _handle_interactive_event(record_type, properties, raw_line)
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
    elif record_type in {"mcp.browser.open.failed", "workspace.failed", "worktree.failed"}:
        _handle_observed_failure_event(record_type, properties, raw_line)
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
            _capture_real_session_id(raw_input)
            try:
                record = json.loads(raw_input)
            except json.JSONDecodeError:
                input_text = sanitize(raw_input)
                if not input_text:
                    continue
                record = None
                raw_text = input_text
            else:
                record = redact_hidden_reasoning(sanitize_json_value(record))
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
