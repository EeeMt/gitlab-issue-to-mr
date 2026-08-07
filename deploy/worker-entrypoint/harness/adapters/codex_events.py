#!/usr/bin/env python3
"""Translate a Codex ``exec --json`` stream to Canonical Event v1 records.

Single streaming process: reads stdin to EOF, keeps all cross-record state in
memory, and emits the single harness terminal at stream end so the LAST
turn-terminal record (turn.completed vs turn.failed) is authoritative.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from sanitize import clean_message, sanitize

# Per-stream in-memory state. The terminal is decided at EOF, so a later
# turn.failed can override an earlier completed turn without colliding with
# the single-terminal canonical invariant.
_STATE: dict = {
    "thread_id": "",
    "retry_count": 0,
    "model_resolved": False,
    "last_assistant_text": "",
    "terminal_type": None,      # "completed" | "failed"
    "terminal_line": None,
    "terminal_failure": None,   # {"kind": ..., "message": ...}
}


def _capture_real_thread_id(raw_text: str) -> None:
    """Persist the unmasked thread id from the raw (pre-sanitize) line.

    Sanitization turns a real UUID into ``<UUID:...>``; the harness result must
    carry the real value so resume works. Only the first real value wins; a
    masked fixture value is kept as a fallback by thread.started.
    """
    try:
        record = json.loads(raw_text)
    except json.JSONDecodeError:
        return
    thread_id = record.get("thread_id")
    if isinstance(thread_id, str) and thread_id and "<" not in thread_id:
        _STATE["thread_id"] = thread_id


def _thread_id(record: dict) -> str | None:
    if _STATE["thread_id"]:
        return _STATE["thread_id"]
    value = record.get("thread_id")
    return value if isinstance(value, str) and value else None


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
            "harness-events/codex.jsonl",
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
        "cached_input_tokens": source.get("cached_input_tokens"),
        "output_tokens": source.get("output_tokens"),
        "reasoning_tokens": source.get("reasoning_output_tokens"),
        "cost": source.get("cost"),
        "currency": source.get("currency"),
        "engine_fields": {
            key: value
            for key, value in source.items()
            if key
            not in {
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
                "cost",
                "currency",
            }
        },
    }


def _write_result(
    *,
    success: bool,
    result: str,
    usage: dict,
    failure_message: str | None = None,
) -> None:
    result_path = Path(os.environ["CODIFY_HARNESS_RESULT_FILE"])
    failure = None
    if not success:
        message = failure_message or result or "Codex execution failed"
        failure = {"kind": _failure_kind(message), "message": message}
    payload = {
        "schema": "codify.worker.result/v1",
        "status": "completed" if success else "failed",
        "success": success,
        "result": result,
        "harness_key": "codex",
        "adapter_version": os.environ.get("CODIFY_ADAPTER_VERSION", "1.0.0"),
        "cli_version": os.environ.get("CODIFY_CLI_VERSION", "unknown"),
        "session_id": _STATE["thread_id"] or None,
        "model": os.environ.get("ANTHROPIC_MODEL") or None,
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
    """Emit the single harness terminal decided from the last turn-terminal."""
    if _STATE["terminal_type"] == "completed":
        _emit(
            "harness.completed",
            {"result": _STATE["last_assistant_text"], "session_id": _STATE["thread_id"] or None},
            _STATE["terminal_line"],
        )
    elif _STATE["terminal_type"] == "failed":
        failure = _STATE["terminal_failure"] or {
            "kind": "engine_error",
            "message": "Codex turn failed",
        }
        _emit("harness.failed", {"failure": failure}, _STATE["terminal_line"])


def translate(record: dict, raw_line: int) -> None:
    record_type = record.get("type")
    if record_type == "thread.started":
        thread_id = record.get("thread_id")
        if isinstance(thread_id, str) and thread_id and not _STATE["thread_id"]:
            # Masked fixture value kept as a fallback for the session id.
            _STATE["thread_id"] = thread_id
        if not _STATE["model_resolved"]:
            _STATE["model_resolved"] = True
            _emit(
                "model.resolved",
                {"model": os.environ.get("ANTHROPIC_MODEL") or None, "session_id": _thread_id(record)},
                raw_line,
            )
        else:
            _emit(
                "diagnostic",
                {"code": "session_resumed", "session_id": _thread_id(record)},
                raw_line,
            )
    elif record_type == "turn.started":
        return
    elif record_type == "error":
        _STATE["retry_count"] += 1
        _emit(
            "provider.retry",
            {
                "attempt": _STATE["retry_count"],
                "failure_kind": _failure_kind(record.get("message") or ""),
            },
            raw_line,
        )
    elif record_type == "turn.failed":
        error = record.get("error") if isinstance(record.get("error"), dict) else {}
        message = clean_message(str(error.get("message") or "Codex turn failed"))
        _STATE["terminal_type"] = "failed"
        _STATE["terminal_line"] = raw_line
        _STATE["terminal_failure"] = {"kind": _failure_kind(message), "message": message}
        _write_result(success=False, result=message, usage=_usage(record), failure_message=message)
    elif record_type == "item.started":
        item = record.get("item") if isinstance(record.get("item"), dict) else {}
        if item.get("type") == "command_execution":
            _emit(
                "tool.started",
                {
                    "tool_id": item.get("id"),
                    "name": "shell",
                    "input": {"command": item.get("command") or ""},
                },
                raw_line,
            )
    elif record_type == "item.completed":
        item = record.get("item") if isinstance(record.get("item"), dict) else {}
        item_type = item.get("type")
        if item_type == "command_execution":
            _emit(
                "tool.completed",
                {
                    "tool_id": item.get("id"),
                    "output": item.get("aggregated_output") or "",
                    "error": bool(item.get("exit_code") not in (None, 0)),
                    "exit_code": item.get("exit_code"),
                },
                raw_line,
            )
        elif item_type == "agent_message":
            text = item.get("text") or ""
            _STATE["last_assistant_text"] = text
            _emit(
                "message.completed",
                {"message_id": item.get("id"), "text": text},
                raw_line,
            )
        elif item_type == "error":
            message = clean_message(str(item.get("message") or ""))
            if "compaction" in message.lower():
                _emit(
                    "context.compacted",
                    {"evidence": "cli_compaction_advisory"},
                    raw_line,
                )
            else:
                _emit(
                    "diagnostic",
                    {"code": "capability_warning", "message": message},
                    raw_line,
                )
    elif record_type == "turn.completed":
        usage = _usage(record)
        _emit("usage.final", {"usage": usage}, raw_line)
        _STATE["terminal_type"] = "completed"
        _STATE["terminal_line"] = raw_line
        _write_result(success=True, result=_STATE["last_assistant_text"], usage=usage)
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
            _capture_real_thread_id(raw_input)
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
