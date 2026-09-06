#!/usr/bin/env python3
"""Translate one Claude stream-json record to Canonical Event v1 records."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from result_builder import is_v2_contract, result_schema, v2_harness_block
from sanitize import redact_hidden_reasoning, sanitize

_REAL_SESSION_ID: str = ""


def _capture_real_session_id(raw_text: str) -> None:
    """Keep the unmasked session id before sanitization so resume stays possible.

    UUIDs are redacted to stable ``<UUID:...>`` placeholders in events and raw
    streams, but the harness result must carry the real session id so the backend
    persists ``output_session_id`` and ``--resume`` receives a valid value. The
    translator is one streaming process reading stdin to EOF, so the value lives
    in memory; the first real id seen wins.
    """
    global _REAL_SESSION_ID
    if _REAL_SESSION_ID:
        return
    try:
        record = json.loads(raw_text)
    except json.JSONDecodeError:
        return
    session_id = record.get("session_id")
    if isinstance(session_id, str) and session_id and "<" not in session_id:
        _REAL_SESSION_ID = session_id


def _session_id(record: dict) -> str | None:
    """Real session id when captured, else the (possibly masked) record value.

    The backend projects ``output_session_id`` from canonical events, so the
    resume capability requires the real value here; other UUIDs stay masked.
    """
    if _REAL_SESSION_ID:
        return _REAL_SESSION_ID
    value = record.get("session_id")
    return value if isinstance(value, str) and value else None


# Per-stream state for the partial-message thinking lifecycle
# (--include-partial-messages). The translator is one streaming process per
# attempt (stdin to EOF), so this state naturally resets between attempts.
# Partial stream events identify every thinking block by its native message id
# plus the content index; the full assistant records that follow must not
# re-map the same block (plan §4.1).
_PARTIAL_MESSAGE_ID: str = ""            # message id from the latest stream_event message_start
_PARTIAL_THINKING_STARTED: bool = False  # a thinking content_block_start was seen for this message
_OPEN_REASONING: dict = {}               # content index -> reasoning_id of open thinking blocks


def _interrupt_open_reasoning(reason: str, raw_line: int) -> None:
    """Interrupt every open thinking block that never received its own end.

    Only blocks whose started was observed are closed here; blocks that ended
    normally are already gone from the set (plan §4.1.5).
    """
    for reasoning_id in _OPEN_REASONING.values():
        _emit(
            "reasoning_summary.interrupted",
            {"reasoning_id": reasoning_id, "reason": reason},
            raw_line,
        )
    _OPEN_REASONING.clear()


def _handle_message_start(event: dict, raw_line: int) -> None:
    """Begin a new native message: reset the per-message partial state.

    Content indexes restart at 0 on message_start, and a new message means the
    previous one ended. Any thinking block the previous message left open
    (stream truncated mid-block) is interrupted here.
    """
    global _PARTIAL_MESSAGE_ID, _PARTIAL_THINKING_STARTED
    _interrupt_open_reasoning("message_ended", raw_line)
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    message_id = message.get("id")
    _PARTIAL_MESSAGE_ID = message_id if isinstance(message_id, str) else ""
    _PARTIAL_THINKING_STARTED = False


def _handle_content_block_start(event: dict, raw_line: int) -> None:
    """Open the reasoning placeholder for a thinking content block."""
    global _PARTIAL_THINKING_STARTED
    block = event.get("content_block") if isinstance(event.get("content_block"), dict) else {}
    if block.get("type") != "thinking":
        # tool_use/text blocks stay driven by the full assistant/user records;
        # their partial starts only feed console rendering, not canonical events.
        return
    index = event.get("index")
    if not isinstance(index, int) or not _PARTIAL_MESSAGE_ID:
        # Without a native message identity there is no stable reasoning_id;
        # leave the full assistant record to its legacy diagnostic handling.
        return
    _PARTIAL_THINKING_STARTED = True
    if index in _OPEN_REASONING:
        return  # duplicate start for one block: keep the first placeholder
    reasoning_id = f"claude-think-{_PARTIAL_MESSAGE_ID}-{index}"
    _OPEN_REASONING[index] = reasoning_id
    _emit("reasoning_summary.started", {"reasoning_id": reasoning_id}, raw_line)


def _handle_content_block_stop(event: dict, raw_line: int) -> None:
    """Close the reasoning placeholder for that block's content index.

    Thinking content is never projected (sanitize/redact boundaries), so the
    completion carries no text even when deltas were observed; an empty block
    still closes its placeholder (plan §4.1.3).
    """
    index = event.get("index")
    if not isinstance(index, int):
        return
    reasoning_id = _OPEN_REASONING.pop(index, None)
    if reasoning_id is None:
        return  # a stop for a text/tool_use block or an unknown index
    _emit(
        "reasoning_summary.completed",
        {"reasoning_id": reasoning_id, "client": "claude"},
        raw_line,
    )


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
            "harness-events/claude.jsonl",
            "--raw-line",
            str(raw_line),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def _usage(record: dict) -> dict:
    source = record.get("usage") if isinstance(record.get("usage"), dict) else {}
    return {
        "input_tokens": source.get("input_tokens"),
        "cached_input_tokens": source.get("cache_read_input_tokens"),
        "output_tokens": source.get("output_tokens"),
        "reasoning_tokens": None,
        "cost": record.get("total_cost_usd"),
        "currency": "USD" if record.get("total_cost_usd") is not None else None,
        "engine_fields": {
            key: value
            for key, value in source.items()
            if key not in {"input_tokens", "cache_read_input_tokens", "output_tokens"}
        },
    }


def _write_result(record: dict, *, success: bool, usage: dict) -> None:
    result_path = Path(os.environ["CODIFY_HARNESS_RESULT_FILE"])
    failure = None
    if not success:
        kind = _failure_kind(record)
        failure = {
            "kind": kind,
            "message": record.get("result") or record.get("subtype") or "AI execution failed",
        }
    result = {
        "schema": result_schema(),
        "status": (
            "completed"
            if success
            else "cancelled"
            if failure and failure["kind"] == "cancelled"
            else "protocol_error"
            if failure and failure["kind"] == "protocol_error"
            else "failed"
        ),
        "success": success,
        "result": record.get("result") or "",
        "session_id": _session_id(record),
        "model": os.environ.get("ANTHROPIC_MODEL") or None,
        "usage": usage,
        "failure": failure,
        "capability_warnings": [],
    }
    if is_v2_contract():
        # Nested harness block matching the event envelope so the archived
        # result passes validate_result_v2 (flat shape is rejected outright).
        result["harness"] = v2_harness_block()
    else:
        result.update(
            {
                "harness_key": "claude",
                "adapter_version": os.environ.get("CODIFY_ADAPTER_VERSION", "1.0.1"),
                "cli_version": os.environ.get("CODIFY_CLI_VERSION", "unknown"),
            }
        )
    temp_path = result_path.with_suffix(".json.tmp")
    temp_path.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.replace(temp_path, result_path)


def _failure_kind(record: dict) -> str:
    text = " ".join(
        str(record.get(key) or "") for key in ("subtype", "result", "error")
    ).lower()
    if any(marker in text for marker in ("authentication", "unauthorized", "invalid api key", "401")):
        return "authentication_error"
    if any(marker in text for marker in ("rate limit", "rate_limit", "too many requests", "429")):
        return "rate_limited"
    if any(marker in text for marker in ("sandbox", "permission denied", "approval required")):
        return "sandbox_error"
    if any(marker in text for marker in ("timed out", "timeout")):
        return "timeout"
    if any(marker in text for marker in ("cancelled", "canceled", "sigterm", "interrupted")):
        return "cancelled"
    if any(marker in text for marker in ("invalid session", "session not found", "no conversation found")):
        return "protocol_error"
    return "engine_error"


def _retry_failure_kind(record: dict) -> str:
    status = record.get("error_status")
    error = str(record.get("error") or "").lower()
    if status == 401 or "auth" in error:
        return "authentication_error"
    if status == 429 or "rate" in error:
        return "rate_limited"
    return "engine_error"


def translate(record: dict, raw_line: int) -> None:
    record_type = record.get("type")
    subtype = record.get("subtype")
    if record_type == "system" and subtype == "init":
        _emit(
            "model.resolved",
            {"model": record.get("model"), "session_id": _session_id(record)},
            raw_line,
        )
    elif record_type == "system" and subtype == "compact_boundary":
        _emit("context.compacted", {"session_id": _session_id(record)}, raw_line)
    elif record_type == "system" and subtype == "api_retry":
        _emit(
            "provider.retry",
            {
                "attempt": record.get("attempt"),
                "max_attempts": record.get("max_retries"),
                "failure_kind": _retry_failure_kind(record),
                "status_code": record.get("error_status"),
                "retry_delay_ms": record.get("retry_delay_ms"),
            },
            raw_line,
        )
    elif record_type == "stream_event":
        event = record.get("event") if isinstance(record.get("event"), dict) else {}
        event_type = event.get("type")
        if event_type == "message_start":
            _handle_message_start(event, raw_line)
        elif event_type == "content_block_start":
            _handle_content_block_start(event, raw_line)
        elif event_type == "content_block_delta":
            delta = event.get("delta") if isinstance(event.get("delta"), dict) else {}
            if delta.get("type") == "text_delta":
                _emit("message.delta", {"text": delta.get("text", "")}, raw_line)
            # thinking_delta/signature_delta are never projected as content and
            # must not drop the open block: the matching content_block_stop
            # still closes it.
        elif event_type == "content_block_stop":
            _handle_content_block_stop(event, raw_line)
        elif event_type in {"error", "abort"}:
            # A native error/abort ends the current message without per-block
            # end signals: interrupt only the blocks that are still open.
            reason = "stream_error"
            if event_type == "abort":
                reason = "aborted"
            else:
                error = event.get("error") if isinstance(event.get("error"), dict) else {}
                error_type = error.get("type")
                if isinstance(error_type, str) and error_type:
                    reason = error_type[:200]
            _interrupt_open_reasoning(reason, raw_line)
        # message_delta/message_stop/ping carry no canonical projection.
    elif record_type == "assistant":
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text" and block.get("text"):
                _emit(
                    "message.completed",
                    {"message_id": message.get("id"), "text": block.get("text")},
                    raw_line,
                )
            elif block_type == "tool_use":
                _emit(
                    "tool.started",
                    {
                        "tool_id": block.get("id"),
                        "name": block.get("name"),
                        "input": block.get("input") or {},
                    },
                    raw_line,
                )
            elif block_type == "thinking":
                # Partial-message mode already mapped this message's thinking
                # lifecycle from content_block_start/stop; the full record must
                # not create a second placeholder or completion (plan §4.1.4).
                # Without a partial lifecycle keep the legacy diagnostic-only
                # behavior.
                if not (
                    _PARTIAL_THINKING_STARTED
                    and message.get("id") == _PARTIAL_MESSAGE_ID
                ):
                    _emit(
                        "diagnostic",
                        {"code": "hidden_reasoning_omitted", "message": "AI thinking omitted"},
                        raw_line,
                    )
    elif record_type == "user":
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        for block in message.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                _emit(
                    "tool.completed",
                    {
                        "tool_id": block.get("tool_use_id"),
                        "output": block.get("content"),
                        "error": bool(block.get("is_error", False)),
                    },
                    raw_line,
                )
    elif record_type == "result":
        usage = _usage(record)
        _emit("usage.final", {"usage": usage}, raw_line)
        success = subtype == "success" and record.get("is_error") is not True
        payload = {
            "result": record.get("result") or "",
            "session_id": _session_id(record),
        }
        if success:
            _emit("harness.completed", payload, raw_line)
        else:
            # A failed turn never delivers the remaining block-end signals:
            # interrupt every block that is still open before the harness
            # terminal event.
            reason = (
                str(subtype)[:200]
                if isinstance(subtype, str) and subtype and subtype != "success"
                else "harness_failed"
            )
            _interrupt_open_reasoning(reason, raw_line)
            payload["failure"] = {
                "kind": _failure_kind(record),
                "message": record.get("result") or subtype or "AI execution failed",
            }
            _emit("harness.failed", payload, raw_line)
        _write_result(record, success=success, usage=usage)
    else:
        _emit(
            "diagnostic",
            {"code": "unknown_raw_event"},
            raw_line,
        )


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
            if record is None:
                _emit(
                    "diagnostic",
                    {"code": "non_json_raw_line", "text": raw_text[:500]},
                    line_no,
                )
                continue
            if not isinstance(record, dict):
                _emit("diagnostic", {"code": "non_object_raw_event"}, line_no)
                continue
            translate(record, line_no)
    # The native stream ended. When a turn dies mid-thinking no error/result
    # signal follows, so interrupt whatever blocks are still open before the
    # runner synthesizes the harness terminal (plan §4.1.5).
    _interrupt_open_reasoning("stream_error", line_no)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
