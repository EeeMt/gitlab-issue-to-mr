#!/usr/bin/env python3
"""Translate a Pi RPC stdio stream to Canonical Event v2 records.

Pi 0.84.2 RPC framing is JSONL over stdio: requests are written by the Bridge as
``{"id": N, "type": "<command>", "message": "<text>"}`` (or ``{"type":"get_state"}``)
and responses / unsolicited stream events arrive on stdout as
``{"id": N, "type": "response", "command": <cmd>, "success": bool}``. This
translator reads the raw stream (one JSON object per line, LF-only framing per the
Phase-0 probe) and maps each record to a canonical event.

The ``delivered`` semantics follow open-harness-v2-schemas.md §3.3: a native
``response success:true`` to steer/follow_up is an interface ACK (the command was
queued), not proof the model consumed it. The true settled signal is
``agent_settled``. Because Pi's native ``queue_update`` carries no command_id
(probe fact 2), the Bridge attaches the Codify ``command_id``/``sequence_no`` on
delivery by correlating its own request id with the command frame; this module
never guesses an id from prompt text.

This is a single streaming process: it reads stdin to EOF, keeps per-stream
state, and emits the single harness terminal at stream end so the last
turn-terminal (agent_settled after the final turn) is authoritative.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from result_builder import v2_harness_block
from sanitize import clean_message, redact_hidden_reasoning, sanitize

SCHEMA = "codify.worker.event/v2"

# Native Pi command names that map to Codify control events.
_NATIVE_STEER = "steer"
_NATIVE_FOLLOW_UP = "follow_up"


def _lenient_loads(text: str) -> object | None:
    """Parse Pi 0.84.2 JSONL with string-aware repair.

    Probe fact: Pi sometimes emits unescaped quotes and raw control characters
    inside JSON string values (e.g. tool args containing ``"``), which strict
    ``json.loads`` rejects and would drop the whole record (including the
    authoritative ``agent_end``). Scan the text tracking in-string/escaped
    state: a quote that is not followed by a JSON structural character is an
    embedded literal quote (repair to ``\"``); raw control characters are
    escaped as ``\\uXXXX``. Return None when nothing was repaired or the
    repaired text still does not parse (caller keeps the strict skip path).
    """
    out: list[str] = []
    in_string = False
    escaped = False
    repaired = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if escaped:
            out.append(ch)
            escaped = False
            i += 1
            continue
        if in_string:
            if ch == "\\":
                out.append(ch)
                escaped = True
                i += 1
                continue
            if ch == '"':
                j = i + 1
                while j < n and text[j] in " \t":
                    j += 1
                if j < n and text[j] in ",}]:":
                    in_string = False
                    out.append(ch)
                else:
                    out.append('\\"')
                    repaired = True
                i += 1
                continue
            if ord(ch) < 0x20:
                out.append("\\u%04x" % ord(ch))
                repaired = True
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    if not repaired:
        return _lenient_agent_end(text)
    try:
        return json.loads("".join(out))
    except json.JSONDecodeError:
        return _lenient_agent_end(text)


_AGENT_END_WILL_RETRY_RE = re.compile(r'"willRetry"\s*:\s*(true|false)')
_AGENT_END_FAILURE_RE = re.compile(r'"failureMessage"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _lenient_agent_end(text: str) -> object | None:
    """Extract an authoritative ``agent_end`` record from an unparseable line.

    Pi 0.84.2 can emit deeply nested unescaped quotes inside tool-result
    payloads (e.g. GitLab URLs containing ``"``), which no character scan can
    repair reliably. The translator only needs ``willRetry``/``failureMessage``
    from ``agent_end`` to decide the terminal, so degrade to a targeted
    extraction instead of dropping the record (which would turn a successful
    run into ``successful_agent_end missing`` at EOF).
    """
    if '"type":"agent_end"' not in text and '"type": "agent_end"' not in text:
        return None
    will_retry_match = _AGENT_END_WILL_RETRY_RE.search(text)
    if will_retry_match is None:
        return None
    record: dict[str, object] = {
        "type": "agent_end",
        "willRetry": will_retry_match.group(1) == "true",
    }
    failure_match = _AGENT_END_FAILURE_RE.search(text)
    if failure_match is not None:
        record["failureMessage"] = failure_match.group(1)
    return record


# Per-stream in-memory state. The terminal is decided at EOF.
_STATE: dict = {
    "model_resolved": False,
    "session_negotiated": False,
    "pending_model_resolved_line": None,
    "model_id": None,
    "session_id": None,
    "thinking": [],
    # Pairing key for the current thinking block: set on thinking_start from
    # the raw stream line number, reused by the matching thinking_end so the
    # projector can complete the same placeholder row in place.
    "thinking_reasoning_id": None,
    "thinking_start_line": None,
    "text_parts": [],
    "tool_starts": {},
    "message_completed_emitted": False,
    "usage": {},
    "terminal": None,   # "completed" | "failed"
    "terminal_line": None,
    "terminal_failure": None,
    "aborted": False,
    # A Pi stream is successful only when it contains the complete, ordered
    # turn lifecycle below.  In particular, an EOF after text is not an
    # implicit success: a truncated RPC stream must be surfaced as a protocol
    # error rather than delivered as a completed task.
    "assistant_final_line": None,
    "agent_end_success_line": None,
    "agent_settled_line": None,
    "last_raw_line": 0,
}
_REAL_SESSION_ID: str = ""


def _capture_real_session_id(raw_text: str) -> None:
    """Keep the latest active Pi session id before sanitization.

    Pi emits an unsolicited startup ``get_state`` before the owner's
    ``new_session`` handshake.  That state points at a throwaway session file;
    the following ``get_state`` is the session actually used by the turn.  Do
    not keep only the first ID, or the next task cannot resolve its parent file.
    """
    global _REAL_SESSION_ID
    try:
        record = json.loads(raw_text)
    except json.JSONDecodeError:
        return
    if (
        not isinstance(record, dict)
        or record.get("type") != "response"
        or record.get("command") != "get_state"
        or not record.get("success")
    ):
        return
    data = record.get("data")
    session_id = (
        data.get("sessionId")
        if isinstance(data, dict)
        else None
    )
    if isinstance(session_id, str) and session_id and "<" not in session_id:
        _REAL_SESSION_ID = session_id


def _session_id(value: object = None) -> str | None:
    """Return the real session id when captured, else the sanitized fallback."""
    if _REAL_SESSION_ID:
        return _REAL_SESSION_ID
    fallback = value if value is not None else _STATE.get("session_id")
    return fallback if isinstance(fallback, str) and fallback else None


def _emit_model_resolved(raw_line: int) -> None:
    """Emit the model/session pair once the active Pi session is known."""
    if _STATE["model_resolved"]:
        return
    _STATE["model_resolved"] = True
    _STATE["pending_model_resolved_line"] = None
    _emit(
        "model.resolved",
        {"model": _STATE["model_id"], "session_id": _session_id()},
        raw_line,
    )


def _flush_pending_model_resolved() -> None:
    """Resolve a direct/legacy stream that has no explicit new_session ACK."""
    pending_line = _STATE.get("pending_model_resolved_line")
    if pending_line is not None and not _STATE["model_resolved"]:
        _emit_model_resolved(pending_line)


def _failure_kind(message: str) -> str:
    lowered = str(message).lower()
    if "abort" in lowered or "interrupt" in lowered:
        return "cancelled"
    # Do not match the bare word "authentication": an upstream HTML error
    # page can contain it in embedded JavaScript and is not thereby an auth
    # failure. Prefer explicit status/error phrases from the provider.
    if (
        "401" in lowered
        or "unauthorized" in lowered
        or "authentication failed" in lowered
        or "authentication error" in lowered
        or "invalid api key" in lowered
        or "invalid x-api-key" in lowered
    ):
        return "authentication_error"
    if "429" in lowered or "rate limit" in lowered or "too many requests" in lowered:
        return "rate_limited"
    if "sandbox" in lowered or "permission denied" in lowered:
        return "sandbox_error"
    return "engine_error"


def _failure_message(value: object, fallback: str) -> str:
    """Return a sanitized, bounded message for canonical failure payloads."""
    return clean_message(sanitize(str(value or fallback)))[:_FAILURE_MESSAGE_MAX_CHARS]


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
            "harness-events/pi.jsonl",
            "--raw-line",
            str(raw_line),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def _usage(record: dict) -> dict:
    source = record.get("usage") if isinstance(record.get("usage"), dict) else {}
    cost = source.get("cost")
    # Pi's cost is a nested object ({input,output,cacheRead,cacheWrite,total});
    # expose the aggregate total, preserving null when Pi reports none so the
    # canonical usage is explicitly unavailable rather than a fabricated value.
    cost_total = None
    if isinstance(cost, dict):
        total = cost.get("total")
        if isinstance(total, (int, float)) and not isinstance(total, bool):
            cost_total = total
    elif isinstance(cost, (int, float)) and not isinstance(cost, bool):
        cost_total = cost
    return {
        "input_tokens": source.get("input"),
        "cached_input_tokens": source.get("cacheRead"),
        "output_tokens": source.get("output"),
        "reasoning_tokens": None,
        "cost": cost_total,
        "currency": None,
        "engine_fields": {
            key: value
            for key, value in source.items()
            if key
            not in {
                "input",
                "output",
                "cacheRead",
                "cacheWrite",
                "cacheWrite1h",
                "totalTokens",
                "cost",
            }
        },
    }


_TOOL_OUTPUT_MAX_CHARS = 2000
_TOOL_COMMAND_MAX_CHARS = 1000
_TOOL_VALUE_MAX_CHARS = 4000
_FAILURE_MESSAGE_MAX_CHARS = _TOOL_OUTPUT_MAX_CHARS
_TOOL_NAME_ALIASES = {
    "bash": "Bash",
    "shell": "Bash",
    "write": "Write",
    "read": "Read",
    "edit": "Edit",
    "patch": "Edit",
    "multiedit": "MultiEdit",
    "multi_edit": "MultiEdit",
    "glob": "Glob",
    "grep": "Grep",
}


def _sanitize_value(value: object, *, depth: int = 0) -> object:
    """Keep arbitrary tool args/results bounded and safe for projection."""
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


def _display_tool_name(tool_name: object) -> str:
    raw_name = str(tool_name or "unknown").strip() or "unknown"
    return _TOOL_NAME_ALIASES.get(raw_name.lower(), raw_name)


def _set_usage(record: dict, raw_line: int, *, emit_update: bool = False) -> None:
    usage = record.get("usage")
    if not isinstance(usage, dict):
        return
    normalized = _usage(record)
    changed = normalized != _STATE.get("usage")
    _STATE["usage"] = normalized
    if emit_update and changed and any(
        normalized.get(key) is not None
        for key in ("input_tokens", "cached_input_tokens", "output_tokens", "cost")
    ):
        _emit("usage.updated", {"usage": normalized}, raw_line)


def _message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "".join(parts)


def _tool_call_arguments(value: object) -> dict:
    """Normalize Pi's toolCall.arguments, including JSON-string arguments."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"raw": sanitize(value)[:_TOOL_VALUE_MAX_CHARS]}
        if isinstance(parsed, dict):
            return parsed
        return {"value": _sanitize_value(parsed)}
    return {}


def _write_result(
    *,
    success: bool,
    result: str,
    usage: dict,
    failure_message: str | None = None,
    failure_kind: str | None = None,
) -> None:
    result_path = Path(os.environ["CODIFY_HARNESS_RESULT_FILE"])
    failure = None
    if not success:
        message = failure_message or result or "Pi execution failed"
        failure = {"kind": failure_kind or _failure_kind(message), "message": message}
    payload = {
        "schema": "codify.worker.result/v2",
        "status": (
            "completed"
            if success
            else "protocol_error"
            if failure and failure["kind"] == "protocol_error"
            else "failed"
        ),
        "success": success,
        "result": result,
        "harness": v2_harness_block(),
        "session_id": _session_id(),
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
        # Canonical usage.final feeds the projector's usage_final log
        # metadata, which worker_results uses to populate the ledger.
        _emit(
            "usage.final",
            {"usage": usage},
            _STATE["terminal_line"] or 0,
        )


def _close_open_thinking(reason: str, raw_line: int) -> None:
    """Explicitly interrupt the open thinking block when no end is observed.

    The projector no longer guesses that a new block ends an older one (plan
    §5.1): the adapter owns the native knowledge of where one block ends, so
    it emits reasoning_summary.interrupted for the open reasoning_id.
    """
    reasoning_id = _STATE.get("thinking_reasoning_id")
    if not reasoning_id:
        return
    _emit(
        "reasoning_summary.interrupted",
        {"reasoning_id": reasoning_id, "reason": reason},
        raw_line,
    )
    _STATE["thinking"] = []
    _STATE["thinking_reasoning_id"] = None
    _STATE["thinking_start_line"] = None


def _emit_terminal_at_eof() -> None:
    if _STATE["terminal"] is None:
        assistant_line = _STATE["assistant_final_line"]
        agent_end_line = _STATE["agent_end_success_line"]
        settled_line = _STATE["agent_settled_line"]
        active_tools = [
            tool_id
            for tool_id, lifecycle in _STATE.get("tool_starts", {}).items()
            if not lifecycle.get("completed")
        ]
        if _STATE["terminal_failure"] is not None:
            _STATE["terminal"] = "failed"
            _STATE["terminal_line"] = settled_line or _STATE["last_raw_line"] or 0
            failure = _STATE["terminal_failure"]
            _write_result(
                success=False,
                result="".join(_STATE["text_parts"]),
                usage=_STATE["usage"],
                failure_message=str(failure["message"]),
                failure_kind=str(failure.get("kind") or "engine_error"),
            )
        elif active_tools:
            message = "Pi protocol ended with active tool executions: " + ",".join(active_tools)
            _STATE["terminal"] = "failed"
            _STATE["terminal_line"] = settled_line or _STATE["last_raw_line"] or 0
            _STATE["terminal_failure"] = {"kind": "protocol_error", "message": message}
            _write_result(
                success=False,
                result="".join(_STATE["text_parts"]),
                usage=_STATE["usage"],
                failure_message=message,
                failure_kind="protocol_error",
            )
        elif (
            isinstance(assistant_line, int)
            and isinstance(agent_end_line, int)
            and isinstance(settled_line, int)
            and assistant_line < agent_end_line < settled_line
        ):
            _STATE["terminal"] = "completed"
            _STATE["terminal_line"] = settled_line
            _write_result(
                success=True,
                result="".join(_STATE["text_parts"]).strip(),
                usage=_STATE["usage"],
            )
        else:
            missing = []
            if not isinstance(assistant_line, int):
                missing.append("final_assistant_text")
            if not isinstance(agent_end_line, int):
                missing.append("successful_agent_end")
            if not isinstance(settled_line, int):
                missing.append("agent_settled")
            order_invalid = not missing and not (assistant_line < agent_end_line < settled_line)
            detail = "out_of_order_turn_terminal" if order_invalid else ",".join(missing)
            message = f"Pi protocol ended without complete terminal lifecycle: {detail}"
            _STATE["terminal"] = "failed"
            _STATE["terminal_line"] = _STATE["last_raw_line"] or 0
            _STATE["terminal_failure"] = {"kind": "protocol_error", "message": message}
            _write_result(
                success=False,
                result="".join(_STATE["text_parts"]),
                usage=_STATE["usage"],
                failure_message=message,
                failure_kind="protocol_error",
            )

    if _STATE["terminal"] == "completed":
        # Defensive: a block left open when the stream ends cleanly still
        # never had an end signal; close it rather than leave a spinner.
        _close_open_thinking("stream_ended_without_block_end", _STATE["terminal_line"] or 0)
        _emit(
            "harness.completed",
            {
                "result": "".join(_STATE["text_parts"]).strip(),
                "session_id": _session_id(),
            },
            _STATE["terminal_line"],
        )
    elif _STATE["terminal"] == "failed":
        _close_open_thinking("harness_failed", _STATE["terminal_line"] or 0)
        failure = _STATE["terminal_failure"] or {
            "kind": "engine_error",
            "message": "Pi turn failed",
        }
        _emit("harness.failed", {"failure": failure}, _STATE["terminal_line"])


def _handle_response(record: dict, raw_line: int) -> None:
    """Map a native ``response`` record (control command ACK/data)."""
    command = record.get("command")
    success = bool(record.get("success"))
    if command == "new_session" and success:
        # Pi may deliver an unsolicited startup get_state before this ACK.  Do
        # not resolve model.resolved from that throwaway session; the next
        # get_state after this handshake is the session used by the turn.
        _STATE["session_negotiated"] = True
        return
    if command == "get_state" and success:
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        model = data.get("model") if isinstance(data.get("model"), dict) else {}
        _STATE["model_id"] = model.get("id") or _STATE["model_id"]
        _STATE["session_id"] = _session_id(data.get("sessionId") or _STATE["session_id"])
        if not _STATE["model_resolved"]:
            if _STATE.get("session_negotiated"):
                _emit_model_resolved(raw_line)
            else:
                # Keep the first state pending.  If this is a direct fixture
                # or older stream without new_session, translate() flushes it
                # before the first turn event.  If new_session arrives next,
                # the pending state is replaced by the active get_state above.
                _STATE["pending_model_resolved_line"] = (
                    _STATE.get("pending_model_resolved_line") or raw_line
                )
        else:
            _emit(
                "diagnostic",
                {"code": "session_resumed", "session_id": _session_id()},
                raw_line,
            )
        return

    # steer / follow_up native ACK -> control.command.delivered. The Bridge
    # attached the Codify command_id/sequence_no on the request; the correlation
    # is authoritative (never a text guess). `delivered` == interface ACK.
    ack = record.get("__command_ack") if isinstance(record.get("__command_ack"), dict) else None
    if command in {_NATIVE_STEER, _NATIVE_FOLLOW_UP}:
        if success and ack and ack.get("command_id"):
            _emit(
                "control.command.delivered",
                {
                    "command_id": ack["command_id"],
                    "payload_digest": ack.get("payload_digest"),
                    "sequence_no": ack.get("sequence_no"),
                    "delivered_at": ack.get("_delivered_at"),
                },
                raw_line,
            )
        elif not success and ack and ack.get("command_id"):
            _emit(
                "control.command.rejected",
                {
                    "command_id": ack["command_id"],
                    "payload_digest": ack.get("payload_digest"),
                    "sequence_no": ack.get("sequence_no"),
                    "rejection_code": ack.get("rejection_code", "delivery_outcome_unknown"),
                    "rejection_message": ack.get("rejection_message"),
                },
                raw_line,
            )
        else:
            _emit(
                "diagnostic",
                {"code": "native_ack_without_command_id", "command": command},
                raw_line,
            )
        return

    if command == "abort":
        # Pi reports abort completion via agent_end(stopReason aborted), not a
        # distinct success here; a bare abort ACK is informational.
        _emit("diagnostic", {"code": "abort_ack", "success": success}, raw_line)
        return

    if not success:
        _emit(
            "diagnostic",
            {"code": "native_command_failed", "command": command},
            raw_line,
        )


def _handle_nested_toolcall(event: dict, raw_line: int) -> None:
    """Track Pi's model-side toolcall stream without mistaking it for execution.

    Pi emits ``toolcall_start/delta/end`` inside ``message_update`` and normally
    follows it with top-level ``tool_execution_*`` records. The nested stream
    is still archived and explicitly diagnosed, while the canonical lifecycle
    is emitted from the execution records; ``toolcall_end`` only provides a
    fallback start when an extension omits that top-level start.
    """
    event_type = event.get("type")
    content_index = event.get("contentIndex")
    content_key = f"content:{content_index}" if content_index is not None else "unknown"
    key = content_key
    pending = _STATE.setdefault("pending_tool_calls", {})
    tool_call = event.get("toolCall") if isinstance(event.get("toolCall"), dict) else {}
    tool_id = tool_call.get("id") or event.get("toolCallId")
    if tool_id:
        tool_id = str(tool_id).strip()
        id_key = f"id:{tool_id}"
    else:
        id_key = None
    entry = pending.get(content_key) or pending.get(id_key or "")
    if entry is None:
        # Keep the content index as the primary key whenever Pi supplies one:
        # toolcall_delta records are keyed by contentIndex and may not repeat
        # the id that was present on toolcall_start. Add the id as an alias so
        # the terminal record can still correlate by tool-call id.
        key = content_key if content_index is not None else id_key or content_key
        entry = pending.setdefault(
            key,
            {"tool_id": tool_id, "name": tool_call.get("name"), "arguments": ""},
        )
    if content_index is not None:
        pending[content_key] = entry
    if id_key:
        pending[id_key] = entry
    if tool_id:
        entry["tool_id"] = tool_id
    if tool_call.get("name"):
        entry["name"] = tool_call["name"]

    if event_type == "toolcall_delta":
        delta = event.get("delta")
        if isinstance(delta, str):
            entry["arguments"] += delta
        _emit(
            "diagnostic",
            {"code": "toolcall_delta", "content_index": content_index},
            raw_line,
        )
        return
    if event_type == "toolcall_start":
        _emit(
            "diagnostic",
            {"code": "toolcall_started", "content_index": content_index},
            raw_line,
        )
        return
    if event_type != "toolcall_end":
        _emit("diagnostic", {"code": "unknown_message_event", "type": event_type}, raw_line)
        return

    pending.pop(content_key, None)
    pending.pop(id_key or "", None)
    arguments = tool_call.get("arguments")
    if arguments is None:
        arguments = tool_call.get("input")
    if arguments is None:
        arguments = entry.get("arguments")
    tool_id = entry.get("tool_id") or tool_id
    if not tool_id:
        _emit(
            "diagnostic",
            {"code": "toolcall_missing_id", "content_index": content_index},
            raw_line,
        )
        return
    _handle_tool(
        {
            "type": "tool_execution_start",
            "toolCallId": tool_id,
            "toolName": tool_call.get("name") or entry.get("name"),
            "args": _tool_call_arguments(arguments),
        },
        raw_line,
    )


def _handle_message_update(record: dict, raw_line: int) -> None:
    _set_usage(record, raw_line, emit_update=True)
    event = record.get("assistantMessageEvent") if isinstance(record.get("assistantMessageEvent"), dict) else {}
    etype = event.get("type")
    if etype == "thinking_start":
        # A real start signal opens the page placeholder immediately. The id
        # derives from the stream-wide line number (contentIndex repeats per
        # message) and is reused by the matching thinking_end below. If the
        # previous block never ended, the adapter closes it explicitly by id —
        # the projector never infers this from the new start (plan §4.2/§5.1).
        _close_open_thinking("next_block_started_without_end", raw_line)
        _STATE["thinking"] = []
        reasoning_id = f"pi-thinking-{raw_line}"
        _STATE["thinking_reasoning_id"] = reasoning_id
        _STATE["thinking_start_line"] = raw_line
        _emit("reasoning_summary.started", {"reasoning_id": reasoning_id}, raw_line)
    elif etype == "thinking_delta":
        _STATE["thinking"].append(event.get("delta") or "")
    elif etype == "thinking_end":
        thinking = "".join(_STATE["thinking"])
        reasoning_id = _STATE.get("thinking_reasoning_id")
        payload: dict = {"client": "pi"}
        if reasoning_id:
            payload["reasoning_id"] = reasoning_id
        if thinking:
            payload["text"] = thinking
        # Completed fires even for an empty block so a started placeholder can
        # always close. When no start was observed the payload carries no
        # reasoning_id and the projector shows static content with no duration.
        _emit("reasoning_summary.completed", payload, raw_line)
        _STATE["thinking"] = []
        _STATE["thinking_reasoning_id"] = None
        _STATE["thinking_start_line"] = None
    elif etype == "text_start":
        _STATE["text_parts"] = []
        _STATE["message_completed_emitted"] = False
    elif etype == "text_delta":
        delta = event.get("delta") or ""
        _STATE["text_parts"].append(delta)
        _emit(
            "message.delta",
            {"content": delta, "role": "assistant"},
            raw_line,
        )
    elif etype == "text_end":
        content = event.get("content")
        if not isinstance(content, str) or not content:
            content = "".join(_STATE["text_parts"])
        _STATE["text_parts"] = [content] if content else _STATE["text_parts"]
        if content and not _STATE.get("message_completed_emitted"):
            _emit("message.completed", {"message_id": None, "text": content}, raw_line)
            _STATE["message_completed_emitted"] = True
        if isinstance(content, str) and content.strip():
            _STATE["assistant_final_line"] = raw_line
    elif etype in {"toolcall_start", "toolcall_delta", "toolcall_end"}:
        _handle_nested_toolcall(event, raw_line)
    elif etype:
        _emit("diagnostic", {"code": "unknown_message_event", "type": etype}, raw_line)


def _handle_message_end(record: dict, raw_line: int) -> None:
    message = record.get("message") if isinstance(record.get("message"), dict) else {}
    _set_usage(message, raw_line, emit_update=True)
    stop_reason = message.get("stopReason")
    error_message = message.get("errorMessage")
    if stop_reason == "error" or (
        stop_reason != "aborted"
        and isinstance(error_message, str)
        and error_message.strip()
    ):
        failure_message = _failure_message(error_message, "Pi message ended with an error")
        failure_kind = _failure_kind(failure_message)
        _STATE["terminal_failure"] = {
            "kind": failure_kind,
            "message": failure_message,
        }
        # The message/turn closed without the block's own end: close the open
        # block by id (plan §4.2).
        _close_open_thinking("message_error", raw_line)
        return
    if stop_reason == "aborted":
        _STATE["aborted"] = True
        failure = {
            "kind": "cancelled",
            "message": _failure_message(message.get("errorMessage"), "Pi run aborted"),
        }
        _STATE["terminal_failure"] = failure
        _close_open_thinking("message_aborted", raw_line)
        return
    if stop_reason in ("stop", "end_turn"):
        # message_end.message is authoritative. Most streams already emitted
        # message.completed from text_end; recover it here when a provider
        # omits the text_end snapshot.
        content = _message_text(message)
        if content and not _STATE.get("message_completed_emitted"):
            _STATE["text_parts"] = [content]
            _emit("message.completed", {"message_id": message.get("id"), "text": content}, raw_line)
            _STATE["message_completed_emitted"] = True
            _STATE["assistant_final_line"] = raw_line


def _handle_queue_update(record: dict, raw_line: int) -> None:
    steering = record.get("steering") if isinstance(record.get("steering"), list) else []
    follow_up = record.get("followUp") if isinstance(record.get("followUp"), list) else []
    queue = [
        {"id": f"steering[{i}]", "text": text}
        for i, text in enumerate(steering)
        if isinstance(text, str) and text
    ] + [
        {"id": f"followUp[{i}]", "text": text}
        for i, text in enumerate(follow_up)
        if isinstance(text, str) and text
    ]
    # Command text is projected only through the existing sanitizer (the Bridge
    # sanitizes before emitting queue content); the raw archive also holds the
    # sanitized line. Do not reprint full command bodies here.
    _emit("control.queue.updated", {"queue": queue}, raw_line)


def _tool_input(record: dict) -> dict:
    """Project a sanitized tool input: file paths stay verbatim (workspace
    paths only), shell commands are sanitized (URLs/tokens redacted)."""
    tool_name = str(record.get("toolName") or "unknown").lower()
    args = record.get("args") if isinstance(record.get("args"), dict) else {}
    sanitized = _sanitize_value(args)
    if not isinstance(sanitized, dict):
        return {}
    if tool_name in {"read", "write", "edit", "patch", "multiedit", "multi_edit"}:
        path = args.get("path") or args.get("filePath") or args.get("file_path")
        if isinstance(path, str) and path:
            sanitized.pop("path", None)
            sanitized.pop("filePath", None)
            sanitized["file_path"] = sanitize(path)[:_TOOL_VALUE_MAX_CHARS]
        return sanitized
    if tool_name in {"bash", "shell"}:
        command = args.get("command") or args.get("cmd") or args.get("script")
        if isinstance(command, str):
            return {"command": sanitize(command)[:_TOOL_COMMAND_MAX_CHARS]}
    return sanitized


def _tool_output(record: dict) -> str:
    result = record.get("result")
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            parts = [
                c.get("text")
                for c in content
                if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str)
            ]
            return sanitize("".join(parts))[:_TOOL_OUTPUT_MAX_CHARS]
        if isinstance(content, str):
            return sanitize(content)[:_TOOL_OUTPUT_MAX_CHARS]
    sanitized = _sanitize_value(result)
    if isinstance(sanitized, str):
        return sanitized[:_TOOL_OUTPUT_MAX_CHARS]
    if sanitized is None:
        return ""
    return json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))[:_TOOL_OUTPUT_MAX_CHARS]


def _handle_tool(record: dict, raw_line: int) -> None:
    """Map Pi tool_execution_* records to canonical tool.started/completed.

    Pi exposes tool calls as top-level stream records with toolName/args/result;
    read/write/edit surface their file path, bash its sanitized command, and
    completion carries the sanitized truncated output. tool_execution_update is
    a progress record with no additional terminal fact: explicit no-op (never
    unknown_raw_event).
    """
    record_type = record.get("type")
    tool_call_id = str(record.get("toolCallId") or "").strip()
    tool_name = _display_tool_name(record.get("toolName"))
    if not tool_call_id:
        _emit("diagnostic", {"code": "tool_missing_id", "name": tool_name}, raw_line)
        return
    tool_states = _STATE.setdefault("tool_starts", {})
    lifecycle = tool_states.setdefault(tool_call_id, {"started": False, "completed": False})
    if record_type == "tool_execution_start":
        if not lifecycle["started"]:
            _emit(
                "tool.started",
                {"tool_id": tool_call_id, "name": tool_name, "input": redact_hidden_reasoning(_tool_input(record))},
                raw_line,
            )
            lifecycle["started"] = True
    elif record_type == "tool_execution_update":
        # Progress is accumulated in Pi's result and has no corresponding
        # canonical type. It remains available in the sanitized raw archive;
        # do not manufacture one diagnostic per output chunk.
        lifecycle["partial_result_seen"] = True
    elif record_type == "tool_execution_end":
        if lifecycle["completed"]:
            return
        if not lifecycle["started"]:
            # A damaged/replayed stream can begin at the completion record.
            # Keep the canonical pair correlated instead of leaving the
            # projector with an orphaned tool.completed.
            _emit(
                "tool.started",
                {"tool_id": tool_call_id, "name": tool_name, "input": redact_hidden_reasoning(_tool_input(record))},
                raw_line,
            )
            lifecycle["started"] = True
        completion = {
            "tool_id": tool_call_id,
            "name": tool_name,
            "output": _tool_output(record),
            "error": bool(record.get("isError")),
        }
        error_message = record.get("errorMessage")
        if error_message is None and isinstance(record.get("result"), dict):
            result = record["result"]
            error_message = result.get("error") or result.get("message")
        if isinstance(error_message, str) and error_message.strip():
            completion["error_message"] = clean_message(sanitize(error_message))[:_TOOL_OUTPUT_MAX_CHARS]
        exit_code = record.get("exitCode")
        if exit_code is None and isinstance(record.get("result"), dict):
            exit_code = record["result"].get("exitCode") or record["result"].get("exit_code")
        if isinstance(exit_code, int) and not isinstance(exit_code, bool):
            completion["exit_code"] = exit_code
        _emit("tool.completed", completion, raw_line)
        lifecycle["completed"] = True


def _retry_payload(record: dict, *, source: str | None = None) -> dict:
    message = record.get("errorMessage") or record.get("finalError") or record.get("error")
    payload = {
        "attempt": record.get("attempt"),
        "max_attempts": record.get("maxAttempts"),
        "failure_kind": _failure_kind(_failure_message(message, "Pi provider retry")),
        "retry_delay_ms": record.get("delayMs"),
    }
    if source:
        payload["source"] = source
    return payload


def _handle_retry_start(record: dict, raw_line: int, *, source: str | None = None) -> None:
    # A preceding message_end may describe the transient error that caused the
    # retry. It is not terminal once the retry has actually started.
    _STATE["terminal_failure"] = None
    _emit("provider.retry", _retry_payload(record, source=source), raw_line)


def _handle_retry_end(record: dict, raw_line: int) -> None:
    payload = {
        "code": "provider_retry_finished",
        "attempt": record.get("attempt"),
        "success": bool(record.get("success")),
    }
    if not record.get("success"):
        message = _failure_message(record.get("finalError"), "Pi provider retry failed")
        _STATE["terminal_failure"] = {"kind": _failure_kind(message), "message": message}
        payload["failure_kind"] = _STATE["terminal_failure"]["kind"]
    _emit("diagnostic", payload, raw_line)


def _handle_compaction(record: dict, raw_line: int) -> None:
    record_type = record.get("type")
    if record_type == "compaction_start":
        _emit("diagnostic", {"code": "compaction_started", "reason": record.get("reason")}, raw_line)
        return
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    if isinstance(result.get("usage"), dict):
        _set_usage(result, raw_line, emit_update=True)
    payload = {
        "session_id": _session_id(),
        "reason": record.get("reason"),
        "aborted": bool(record.get("aborted")),
        "will_retry": bool(record.get("willRetry")),
    }
    for source_key, target_key in (
        ("tokensBefore", "tokens_before"),
        ("estimatedTokensAfter", "estimated_tokens_after"),
    ):
        value = result.get(source_key)
        if isinstance(value, int) and not isinstance(value, bool):
            payload[target_key] = value
    _emit("context.compacted", payload, raw_line)
    error_message = record.get("errorMessage")
    if error_message and not record.get("aborted") and not record.get("willRetry"):
        message = _failure_message(error_message, "Pi compaction failed")
        _STATE["terminal_failure"] = {"kind": _failure_kind(message), "message": message}


def _handle_agent_end(record: dict, raw_line: int) -> None:
    if _STATE["terminal"] is not None:
        return
    will_retry = bool(record.get("willRetry"))
    if _STATE["aborted"]:
        return
    failure_message = record.get("errorMessage") or record.get("terminationReason")
    if will_retry or failure_message:
        if failure_message:
            message = _failure_message(failure_message, "Pi agent ended with an error")
            _STATE["terminal_failure"] = {"kind": _failure_kind(message), "message": message}
    else:
        # ``agent_end`` alone is not a terminal.  Pi emits agent_settled after
        # the final turn, and losing that event at EOF is a protocol error.
        _STATE["agent_end_success_line"] = raw_line


def _handle_agent_settled(record: dict, raw_line: int) -> None:
    # agent_settled is the authoritative attempt-level settled signal. When it
    # follows a completed agent_end this is the clean terminal already recorded;
    # it is also surfaced as an audit event for the projector.
    _emit(
        "agent_settled",
        {"aborted": _STATE["aborted"], "settled_line": raw_line},
        raw_line,
    )
    _STATE["agent_settled_line"] = raw_line


def translate(record: dict, raw_line: int) -> None:
    _STATE["last_raw_line"] = raw_line
    record_type = record.get("type")
    is_response = record_type == "response"
    command = record.get("command") if is_response else None
    if command == "new_session" and record.get("success"):
        _STATE["session_negotiated"] = True
    elif not (is_response and command == "get_state"):
        _flush_pending_model_resolved()
    reopen = record.get("__pi_reopen_after")
    if isinstance(reopen, dict):
        _emit(
            "diagnostic",
            {"code": "pi_follow_up_turn_started", "command_id": reopen.get("command_id"), "native_id": reopen.get("native_id")},
            raw_line,
        )
    if record_type == "response":
        _handle_response(record, raw_line)
    elif record_type == "agent_start":
        return
    elif record_type == "turn_start":
        _STATE["message_completed_emitted"] = False
        return
    elif record_type == "message_start":
        return
    elif record_type == "message_update":
        _handle_message_update(record, raw_line)
    elif record_type == "message_end":
        _handle_message_end(record, raw_line)
    elif record_type == "queue_update":
        _handle_queue_update(record, raw_line)
    elif record_type == "turn_end":
        return
    elif record_type in (
        "tool_execution_start",
        "tool_execution_update",
        "tool_execution_end",
    ):
        _handle_tool(record, raw_line)
    elif record_type == "agent_end":
        _handle_agent_end(record, raw_line)
    elif record_type == "agent_settled":
        _handle_agent_settled(record, raw_line)
    elif record_type in {"compaction_start", "compaction_end"}:
        _handle_compaction(record, raw_line)
    elif record_type == "auto_retry_start":
        _handle_retry_start(record, raw_line)
    elif record_type == "auto_retry_end":
        _handle_retry_end(record, raw_line)
    elif record_type == "summarization_retry_scheduled":
        _handle_retry_start(record, raw_line, source="summarization")
    elif record_type == "summarization_retry_attempt_start":
        _emit(
            "diagnostic",
            {
                "code": "summarization_retry_started",
                "source": record.get("source"),
                "reason": record.get("reason"),
            },
            raw_line,
        )
    elif record_type == "summarization_retry_finished":
        _emit("diagnostic", {"code": "summarization_retry_finished"}, raw_line)
    elif record_type == "extension_error":
        error = record.get("error") or "Pi extension error"
        _emit(
            "diagnostic",
            {
                "code": "extension_error",
                "event": record.get("event"),
                "message": clean_message(sanitize(str(error)))[:_TOOL_OUTPUT_MAX_CHARS],
            },
            raw_line,
        )
    elif record_type == "bash_execution_update":
        delta = record.get("delta")
        payload = {"code": "bash_execution_update", "request_id": record.get("id")}
        if isinstance(delta, str):
            payload["output"] = sanitize(delta)[:_TOOL_OUTPUT_MAX_CHARS]
        _emit("diagnostic", payload, raw_line)
    else:
        _emit("diagnostic", {"code": "unknown_raw_event", "type": record_type}, raw_line)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-file", required=True, type=Path)
    parser.add_argument(
        "--no-archive-input",
        action="store_true",
        help="translate an already-durable raw capture without appending it again",
    )
    args = parser.parse_args()
    args.raw_file.parent.mkdir(parents=True, exist_ok=True)

    line_no = 0
    with args.raw_file.open("a", encoding="utf-8") as handle:
        for raw_input in sys.stdin:
            raw_input = raw_input.rstrip("\n")
            if not raw_input.strip():
                continue
            _capture_real_session_id(raw_input)
            input_text = sanitize(raw_input)
            if not input_text:
                continue
            try:
                record = json.loads(input_text)
            except json.JSONDecodeError:
                record = _lenient_loads(input_text)
                if record is None:
                    raw_text = input_text
                else:
                    if isinstance(record, dict):
                        archive_record = dict(record)
                        archive_record.pop("__command_ack", None)
                        archive_record.pop("__pi_reopen_after", None)
                    else:
                        archive_record = record
                    raw_text = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            else:
                # Owner-only correlation drives canonical ACK/reopen events;
                # it is not part of Pi's raw archive and must not be persisted
                # as if the CLI emitted it.
                if isinstance(record, dict):
                    archive_record = dict(record)
                    archive_record.pop("__command_ack", None)
                    archive_record.pop("__pi_reopen_after", None)
                else:
                    archive_record = record
                raw_text = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            if record is not None:
                record = redact_hidden_reasoning(record)
                if not args.no_archive_input:
                    archive_record = record
                    if isinstance(archive_record, dict):
                        archive_record = dict(archive_record)
                        archive_record.pop("__command_ack", None)
                        archive_record.pop("__pi_reopen_after", None)
                raw_text = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            if not args.no_archive_input:
                archive_text = (
                    json.dumps(archive_record, ensure_ascii=False, separators=(",", ":"))
                    if record is not None
                    else raw_text
                )
                handle.write(archive_text + "\n")
                handle.flush()
            line_no += 1
            if record is None:
                _emit("diagnostic", {"code": "non_json_raw_line", "text": raw_text[:500]}, line_no)
                continue
            if not isinstance(record, dict):
                _emit("diagnostic", {"code": "non_object_raw_event"}, line_no)
                continue
            translate(record, line_no)
    _emit_terminal_at_eof()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
