#!/usr/bin/env python3
"""Translate one Codex ``exec --json`` record to Canonical Event v1 records."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

_REAL_THREAD_ID: str = ""
_REAL_THREAD_ID_FILE_NAME = ".real-thread-id"


def _real_thread_id_file() -> Path:
    return Path(os.environ["CODIFY_RUNTIME_DIR"]) / _REAL_THREAD_ID_FILE_NAME


def _persist_real_thread_id(thread_id: str) -> None:
    try:
        _real_thread_id_file().write_text(thread_id, encoding="utf-8")
    except OSError:
        pass


def _capture_real_thread_id(raw_text: str) -> None:
    global _REAL_THREAD_ID
    if _REAL_THREAD_ID:
        return
    try:
        record = json.loads(raw_text)
    except json.JSONDecodeError:
        return
    thread_id = record.get("thread_id")
    if isinstance(thread_id, str) and thread_id and "<" not in thread_id:
        _REAL_THREAD_ID = thread_id
        _persist_real_thread_id(thread_id)


def _thread_id(record: dict) -> str | None:
    if _REAL_THREAD_ID:
        return _REAL_THREAD_ID
    try:
        persisted = _real_thread_id_file().read_text(encoding="utf-8").strip()
    except OSError:
        persisted = ""
    if persisted and "<" not in persisted:
        return persisted
    return record.get("thread_id")


def _stable_placeholder(kind: str, value: str) -> str:
    if value.startswith(f"<{kind}:"):
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"<{kind}:{digest}>"


TOKEN_PATTERNS = (
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{8,}\b"), "<GITLAB_TOKEN>"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{8,}\b"), "<ANTHROPIC_API_KEY>"),
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b"), "<OPENAI_API_KEY>"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}"), "Bearer <REDACTED>"),
    (
        re.compile(r"(?i)\b([A-Z0-9_]*(?:API_KEY|AUTH_TOKEN|ACCESS_TOKEN|PASSWORD|SECRET)"
                   r"\s*[:=]\s*[\"']?)[^\s,;\"']{6,}"),
        lambda match: f"{match.group(1)}<REDACTED>",
    ),
    (
        re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                   r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"),
        lambda match: _stable_placeholder("UUID", match.group(0).lower()),
    ),
)
PRIVATE_HOST = re.compile(
    r"(?i)(?:localhost|127(?:\.\d{1,3}){3}|10(?:\.\d{1,3}){3}|"
    r"192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|"
    r"[^./\s]+\.(?:local|internal|corp))"
)
URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")


def _sanitize_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return "<PRIVATE_URL>"
    if parsed.username or parsed.password or PRIVATE_HOST.fullmatch(parsed.hostname or ""):
        return "<PRIVATE_URL>"
    return raw


def sanitize(text: str) -> str:
    text = URL_PATTERN.sub(_sanitize_url, text)
    for pattern, replacement in TOKEN_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


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


def _write_result(record: dict, *, success: bool, result: str, usage: dict) -> None:
    result_path = Path(os.environ["CODIFY_HARNESS_RESULT_FILE"])
    failure = None
    if not success:
        failure = {"kind": "engine_error", "message": result or "Codex execution failed"}
    payload = {
        "schema": "codify.worker.result/v1",
        "status": "completed" if success else "failed",
        "success": success,
        "result": result,
        "harness_key": "codex",
        "adapter_version": os.environ.get("CODIFY_ADAPTER_VERSION", "1.0.0"),
        "cli_version": os.environ.get("CODIFY_CLI_VERSION", "unknown"),
        "session_id": _thread_id(record),
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


def translate(record: dict, raw_line: int) -> None:
    record_type = record.get("type")
    if record_type == "thread.started":
        thread_id = record.get("thread_id")
        if isinstance(thread_id, str) and thread_id and "<" not in thread_id:
            global _REAL_THREAD_ID
            _REAL_THREAD_ID = thread_id
            _persist_real_thread_id(thread_id)
        _emit(
            "model.resolved",
            {"model": os.environ.get("ANTHROPIC_MODEL") or None, "session_id": _thread_id(record)},
            raw_line,
        )
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
            _emit(
                "message.completed",
                {"message_id": item.get("id"), "text": text},
                raw_line,
            )
    elif record_type == "turn.completed":
        usage = _usage(record)
        _emit("usage.final", {"usage": usage}, raw_line)
        thread_id = _thread_id(record)
        _emit(
            "harness.completed",
            {"result": "", "session_id": thread_id},
            raw_line,
        )
        _write_result(record, success=True, result="", usage=usage)
    else:
        _emit("diagnostic", {"code": "unknown_raw_event", "type": record_type}, raw_line)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-file", required=True, type=Path)
    args = parser.parse_args()
    raw_input = sys.stdin.read().rstrip("\n")
    _capture_real_thread_id(raw_input)
    input_text = sanitize(raw_input)
    if not input_text:
        return 0
    try:
        record = json.loads(input_text)
    except json.JSONDecodeError:
        record = None
        raw_text = input_text
    else:
        raw_text = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    args.raw_file.parent.mkdir(parents=True, exist_ok=True)
    with args.raw_file.open("a", encoding="utf-8") as handle:
        handle.write(raw_text + "\n")
    raw_line = sum(1 for _ in args.raw_file.open(encoding="utf-8"))
    if record is None:
        _emit("diagnostic", {"code": "non_json_raw_line", "text": raw_text[:500]}, raw_line)
        return 0
    if not isinstance(record, dict):
        _emit("diagnostic", {"code": "non_object_raw_event"}, raw_line)
        return 0
    translate(record, raw_line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
