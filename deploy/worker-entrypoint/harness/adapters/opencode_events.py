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
from sanitize import clean_message, sanitize

SCHEMA = "codify.worker.event/v2"

# Per-stream in-memory state. The terminal is decided when settled is reached.
_STATE: dict = {
    "model_resolved": False,
    "model_id": None,
    "session_id": None,
    "text_parts": [],
    "messages": {},             # message_id -> part_id -> text state
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
        "429" in lowered
        or "rate limit" in lowered
        or "rate-limit" in lowered
        or "usage limit" in lowered
        or "account_rate_limit" in lowered
        or "too many requests" in lowered
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
    return {
        "input_tokens": source.get("input_tokens"),
        "cached_input_tokens": source.get("cached_input_tokens"),
        "output_tokens": source.get("output_tokens"),
        "reasoning_tokens": source.get("reasoning_tokens", source.get("reasoning")),
        "cost": source.get("cost"),
        "currency": None,
        "engine_fields": {
            key: value
            for key, value in source.items()
            if key
            not in {
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_tokens",
                "reasoning",
                "cost",
            }
        },
    }


def _write_result(*, success: bool, result: str, usage: dict, failure_message: str | None = None) -> None:
    result_path = Path(os.environ["CODIFY_HARNESS_RESULT_FILE"])
    failure = None
    if not success:
        message = failure_message or result or "OpenCode execution failed"
        failure = {"kind": _failure_kind(message), "message": message}
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
        _write_result(success=False, result="".join(_STATE["text_parts"]).strip(), usage=_STATE["usage"])
        _STATE["terminal_line"] = terminal_line
    elif _STATE["terminal_failure"] is not None:
        fail = _STATE["terminal_failure"]
        _STATE["terminal"] = "failed"
        _write_result(
            success=False, result="".join(_STATE["text_parts"]).strip(),
            usage=_STATE["usage"], failure_message=str(fail["message"]),
        )
        _STATE["terminal_line"] = terminal_line
    else:
        _STATE["terminal"] = "completed"
        _write_result(
            success=True,
            result="".join(_STATE["text_parts"]).strip(),
            usage=_STATE["usage"],
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
        reason = action.get("reason")
        lowered = str(message).lower()
        if reason == "account_rate_limit" or any(
            marker in lowered
            for marker in (
                "rate limit",
                "rate-limit",
                "usage limit",
                "too many requests",
                "429",
            )
        ):
            message = clean_message(str(message))
            _STATE["terminal_failure"] = {
                "kind": "rate_limited",
                "message": message,
            }
            _finalize_terminal()
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
    usage = info.get("usage") if isinstance(info.get("usage"), dict) else None
    if isinstance(usage, dict):
        _STATE["usage"] = _usage({"usage": usage})
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
    if part.get("type") == "text":
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
    usage = part.get("usage") if isinstance(part.get("usage"), dict) else None
    if isinstance(usage, dict):
        _STATE["usage"] = _usage({"usage": usage})


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
    elif record_type in ("permission", "question"):
        # A tool/permission block would leave the run non-idle; classify (probe 待测)
        # so the pipeline can diagnose rather than hang. Live runners detect the
        # resulting long non-idle session via the readiness/timeout policy.
        _emit("diagnostic", {"code": "permission_block", "type": record_type}, raw_line)
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
