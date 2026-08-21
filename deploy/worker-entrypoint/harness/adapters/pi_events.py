#!/usr/bin/env python3
"""Translate a Pi RPC stdio stream to Canonical Event v2 records.

Pi 0.84.2 RPC framing is JSONL over stdio: requests are written by the Bridge
as ``{"id": N, "type": "request", "command": ..., "payload": ...}`` and responses
/unsolicited stream events arrive on stdout. This translator reads the raw stream
(one JSON object per line, LF-only framing per the Phase-0 probe) and maps each
record to a canonical event.

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
import subprocess
import sys
from pathlib import Path

from sanitize import clean_message, sanitize

SCHEMA = "codify.worker.event/v2"

# Native Pi command names that map to Codify control events.
_NATIVE_STEER = "steer"
_NATIVE_FOLLOW_UP = "follow_up"

# Per-stream in-memory state. The terminal is decided at EOF.
_STATE: dict = {
    "model_resolved": False,
    "model_id": None,
    "session_id": None,
    "thinking": [],
    "text_parts": [],
    "tool_starts": {},
    "usage": {},
    "terminal": None,   # "completed" | "failed"
    "terminal_line": None,
    "terminal_failure": None,
    "aborted": False,
}


def _failure_kind(message: str) -> str:
    lowered = str(message).lower()
    if "401" in lowered or "unauthorized" in lowered or "authentication" in lowered:
        return "authentication_error"
    if "429" in lowered or "rate limit" in lowered or "too many requests" in lowered:
        return "rate_limited"
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


def _write_result(*, success: bool, result: str, usage: dict, failure_message: str | None = None) -> None:
    result_path = Path(os.environ["CODIFY_HARNESS_RESULT_FILE"])
    failure = None
    if not success:
        message = failure_message or result or "Pi execution failed"
        failure = {"kind": _failure_kind(message), "message": message}
    payload = {
        "schema": "codify.worker.result/v2",
        "status": "completed" if success else "failed",
        "success": success,
        "result": result,
        "harness_key": "pi",
        "adapter_version": os.environ.get("CODIFY_ADAPTER_VERSION", "2.0.0"),
        "cli_version": os.environ.get("CODIFY_CLI_VERSION", "unknown"),
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


def _emit_terminal_at_eof() -> None:
    if _STATE["terminal"] == "completed":
        _emit(
            "harness.completed",
            {
                "result": "".join(_STATE["text_parts"]).strip(),
                "session_id": _STATE["session_id"],
            },
            _STATE["terminal_line"],
        )
    elif _STATE["terminal"] == "failed":
        failure = _STATE["terminal_failure"] or {
            "kind": "engine_error",
            "message": "Pi turn failed",
        }
        _emit("harness.failed", {"failure": failure}, _STATE["terminal_line"])


def _handle_response(record: dict, raw_line: int) -> None:
    """Map a native ``response`` record (control command ACK/data)."""
    command = record.get("command")
    success = bool(record.get("success"))
    if command == "get_state" and success:
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        model = data.get("model") if isinstance(data.get("model"), dict) else {}
        _STATE["model_id"] = model.get("id") or _STATE["model_id"]
        _STATE["session_id"] = data.get("sessionId") or _STATE["session_id"]
        if not _STATE["model_resolved"]:
            _STATE["model_resolved"] = True
            _emit(
                "model.resolved",
                {"model": _STATE["model_id"], "session_id": _STATE["session_id"]},
                raw_line,
            )
        else:
            _emit(
                "diagnostic",
                {"code": "session_resumed", "session_id": _STATE["session_id"]},
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
                    "delivered_at": record.get("_delivered_at"),
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


def _handle_message_update(record: dict, raw_line: int) -> None:
    usage = record.get("usage")
    if isinstance(usage, dict):
        _STATE["usage"] = _usage(record)
    event = record.get("assistantMessageEvent") if isinstance(record.get("assistantMessageEvent"), dict) else {}
    etype = event.get("type")
    if etype == "thinking_start":
        _STATE["thinking"] = []
    elif etype == "thinking_delta":
        _STATE["thinking"].append(event.get("delta") or "")
    elif etype == "thinking_end":
        thinking = "".join(_STATE["thinking"])
        if thinking:
            _emit(
                "reasoning_summary.delta",
                {"text": thinking, "client": "pi"},
                raw_line,
            )
    elif etype == "text_start":
        _STATE["text_parts"] = []
    elif etype == "text_delta":
        delta = event.get("delta") or ""
        _STATE["text_parts"].append(delta)
        _emit(
            "message.delta",
            {"content": delta, "role": "assistant"},
            raw_line,
        )
    elif etype == "text_end":
        content = event.get("content") or ""
        _STATE["text_parts"] = [content] if content else _STATE["text_parts"]
        _emit("message.completed", {"message_id": None, "text": content}, raw_line)


def _handle_message_end(record: dict, raw_line: int) -> None:
    message = record.get("message") if isinstance(record.get("message"), dict) else {}
    if isinstance(message.get("usage"), dict):
        _STATE["usage"] = _usage(message)
    stop_reason = message.get("stopReason")
    if stop_reason == "aborted":
        _STATE["aborted"] = True
        failure = {
            "kind": "cancelled",
            "message": message.get("errorMessage") or "Pi run aborted",
        }
        _STATE["terminal"] = "failed"
        _STATE["terminal_line"] = raw_line
        _STATE["terminal_failure"] = failure
        _write_result(success=False, result="", usage=_STATE["usage"], failure_message=str(failure["message"]))
        return
    if stop_reason in ("stop", "end_turn"):
        text = "".join(_STATE["text_parts"])
        # message.completed is emitted from text_end for deltas; keep the final
        # aggregated assistant text for the harness result.
        if text:
            _emit("message.completed", {"message_id": None, "text": text}, raw_line)


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


def _handle_tool(record: dict, raw_line: int) -> None:
    # Pi tool calls surface as message content parts in this protocol version;
    # expose a lightweight diagnostic when a tool execution is observed.
    _emit(
        "diagnostic",
        {"code": "pi_tool_observed", "role": record.get("role", "assistant")},
        raw_line,
    )


def _handle_agent_end(record: dict, raw_line: int) -> None:
    will_retry = bool(record.get("willRetry"))
    if _STATE["aborted"]:
        return
    failure_message = record.get("errorMessage") or record.get("terminationReason")
    if will_retry or failure_message:
        if failure_message:
            message = clean_message(str(failure_message))
            _STATE["terminal"] = "failed"
            _STATE["terminal_line"] = raw_line
            _STATE["terminal_failure"] = {"kind": _failure_kind(message), "message": message}
            _write_result(success=False, result="".join(_STATE["text_parts"]), usage=_STATE["usage"], failure_message=message)
    else:
        # Final agent_end without retry -> the last completed turn is terminal.
        _STATE["terminal"] = "completed"
        _STATE["terminal_line"] = raw_line
        _write_result(
            success=True,
            result="".join(_STATE["text_parts"]).strip(),
            usage=_STATE["usage"],
        )


def _handle_agent_settled(record: dict, raw_line: int) -> None:
    # agent_settled is the authoritative attempt-level settled signal. When it
    # follows a completed agent_end this is the clean terminal already recorded;
    # it is also surfaced as an audit event for the projector.
    _emit(
        "agent_settled",
        {"aborted": _STATE["aborted"], "settled_line": raw_line},
        raw_line,
    )
    if _STATE["terminal"] is None:
        # Settled without a recorded turn terminal is a protocol anomaly; fall
        # back to a completed terminal so the attempt does not hang.
        _STATE["terminal"] = "completed"
        _STATE["terminal_line"] = raw_line
        _STATE["text_parts"] = _STATE["text_parts"] or ["[settled without assistant turn]"]
        _write_result(success=True, result="".join(_STATE["text_parts"]).strip(), usage=_STATE["usage"])


def translate(record: dict, raw_line: int) -> None:
    record_type = record.get("type")
    if record_type == "response":
        _handle_response(record, raw_line)
    elif record_type == "agent_start":
        return
    elif record_type == "turn_start":
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
    elif record_type == "tool_execution_start" or record_type == "tool_execution_end":
        _handle_tool(record, raw_line)
    elif record_type == "agent_end":
        _handle_agent_end(record, raw_line)
    elif record_type == "agent_settled":
        _handle_agent_settled(record, raw_line)
    elif record_type == "compaction_start" or record_type == "compaction_end":
        _emit("diagnostic", {"code": "compaction_observed"}, raw_line)
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
