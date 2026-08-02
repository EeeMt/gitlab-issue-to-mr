#!/usr/bin/env python3
"""Build the frozen Phase 0 Codex raw-event to Canonical Event candidate mapping."""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

# The sanitizer removes full credential assignments, but a masked-key tail such
# as the DeepSeek "Your api key: ****tial is invalid" error must never flow into
# the canonical stream either. Redact it here as well so the mapper is safe even
# against an un-sanitized raw record.
MASKED_KEY_TAIL = re.compile(r"\*\*\*\*[A-Za-z0-9_-]{2,}")


def _clean_message(text: str) -> str:
    return MASKED_KEY_TAIL.sub("<MASKED_KEY>", str(text))


FAILURE_KIND = {
    "tool_failure": "engine_error",
    "invalid_session": "protocol_error",
    "authentication_failure": "authentication_error",
    "rate_limited": "rate_limited",
    "network_interruption": "engine_error",
    "timeout": "timeout",
    "sigterm": "cancelled",
    "sigkill": "protocol_error",
    "cancelled": "cancelled",
}


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _failure_kind(scenario: str, message: str = "") -> str:
    lowered = message.lower()
    if "401" in lowered or "unauthorized" in lowered or "authentication" in lowered:
        return "authentication_error"
    if "429" in lowered or "rate limit" in lowered or "too many requests" in lowered:
        return "rate_limited"
    if "sandbox" in lowered or "permission denied" in lowered:
        return "sandbox_error"
    return FAILURE_KIND.get(scenario, "engine_error")


def _usage(raw: dict) -> dict:
    return {
        "input_tokens": raw.get("input_tokens"),
        "cached_input_tokens": raw.get("cached_input_tokens"),
        "output_tokens": raw.get("output_tokens"),
        "reasoning_tokens": raw.get("reasoning_output_tokens"),
        "cost": None,
        "currency": None,
        "engine_fields": {
            "cache_write_input_tokens": raw.get("cache_write_input_tokens"),
        },
    }


def build_expected(scenario_dir: Path) -> list[dict]:
    metadata = json.loads((scenario_dir / "metadata.json").read_text())
    process = json.loads((scenario_dir / "process.json").read_text())
    records = _jsonl(scenario_dir / "stdout.jsonl")
    scenario = metadata["scenario"]
    attempt_id = f"codex-{scenario}-real-probe"
    adapter_version = metadata["adapter_candidate_version"]
    cli_version = metadata["cli_version"]
    model = metadata["provider_model"]
    events: list[dict] = []
    session_id = None
    final_message = ""
    harness_terminal = False
    retry_attempt = 0
    last_turn_completed = max(
        (index for index, record in enumerate(records, start=1) if record.get("type") == "turn.completed"),
        default=None,
    )

    def add(event_type: str, payload: dict | None = None, raw_line: int | None = None) -> None:
        sequence = len(events) + 1
        event = {
            "schema": "codify.worker.event/v1",
            "event_id": f"codex-{scenario}-event-{sequence}",
            "attempt_id": attempt_id,
            "seq": sequence,
            "occurred_at": (
                datetime(2026, 8, 1, tzinfo=UTC) + timedelta(seconds=sequence)
            ).isoformat().replace("+00:00", "Z"),
            "type": event_type,
            "task_id": 2,
            "harness": {
                "key": "codex",
                "adapter_version": adapter_version,
                "cli_version": cli_version,
            },
            "payload": payload or {},
        }
        if raw_line is not None:
            event["raw_ref"] = {
                "stream": "harness-events/codex.jsonl",
                "line": raw_line,
            }
        events.append(event)

    add("run.started")
    for line_number, record in enumerate(records, start=1):
        record_type = record.get("type")
        item = record.get("item") if isinstance(record.get("item"), dict) else {}
        item_type = item.get("type")
        if record_type == "thread.started":
            if session_id is None:
                session_id = record.get("thread_id")
                add(
                    "model.resolved",
                    {"model": model, "session_id": session_id},
                    line_number,
                )
            else:
                add(
                    "diagnostic",
                    {"code": "session_resumed", "session_id": session_id},
                    line_number,
                )
        elif record_type == "turn.started":
            continue
        elif record_type == "error":
            retry_attempt += 1
            message = str(record.get("message") or "")
            add(
                "provider.retry",
                {
                    "attempt": retry_attempt,
                    "failure_kind": _failure_kind(scenario, message),
                },
                line_number,
            )
        elif record_type == "item.started" and item_type == "command_execution":
            add(
                "tool.started",
                {
                    "tool_id": item.get("id"),
                    "name": "shell",
                    "input": {"command": item.get("command")},
                },
                line_number,
            )
        elif record_type == "item.completed" and item_type == "command_execution":
            exit_code = item.get("exit_code")
            add(
                "tool.completed",
                {
                    "tool_id": item.get("id"),
                    "output": item.get("aggregated_output") or "",
                    "error": exit_code not in {0, None},
                    "exit_code": exit_code,
                },
                line_number,
            )
        elif record_type == "item.completed" and item_type == "agent_message":
            final_message = str(item.get("text") or "")
            add(
                "message.completed",
                {"message_id": item.get("id"), "text": final_message},
                line_number,
            )
        elif record_type == "item.completed" and item_type == "error":
            message = str(item.get("message") or "")
            if "multiple compactions" in message.lower():
                add(
                    "context.compacted",
                    {"evidence": "cli_compaction_advisory"},
                    line_number,
                )
            else:
                add(
                    "diagnostic",
                    {"code": "capability_warning", "message": _clean_message(message)},
                    line_number,
                )
        elif record_type == "turn.completed":
            add("usage.final", {"usage": _usage(record.get("usage") or {})}, line_number)
            if line_number == last_turn_completed:
                add(
                    "harness.completed",
                    {"session_id": session_id, "result": final_message},
                    line_number,
                )
                harness_terminal = True
        elif record_type == "turn.failed":
            error = record.get("error") if isinstance(record.get("error"), dict) else {}
            message = _clean_message(str(error.get("message") or "Codex turn failed"))
            kind = _failure_kind(scenario, message)
            add(
                "harness.failed",
                {"failure": {"kind": kind, "message": message}},
                line_number,
            )
            harness_terminal = True
        else:
            add("diagnostic", {"code": "unknown_raw_event"}, line_number)

    if not harness_terminal:
        kind = FAILURE_KIND.get(scenario, "protocol_error")
        add(
            "harness.failed",
            {
                "failure": {
                    "kind": kind,
                    "message": "Harness ended without a raw terminal; synthesized from process evidence",
                }
            },
        )

    add(
        "worker.finalization",
        {
            "exit_code": process["exit_code"],
            "timed_out": process["timed_out"],
            "term_sent": process["term_sent"],
            "kill_sent": process["kill_sent"],
        },
    )
    if metadata["expected_task_result"] == "run.completed":
        add("run.completed", {"status": "completed", "success": True})
    else:
        kind = FAILURE_KIND[scenario]
        status = (
            "cancelled"
            if kind == "cancelled"
            else "protocol_error"
            if kind == "protocol_error"
            else "failed"
        )
        add(
            "run.failed",
            {
                "status": status,
                "success": False,
                "failure": {"kind": kind},
            },
        )
    return events


def render(events: list[dict]) -> str:
    return "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario_dir", type=Path)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    args = parser.parse_args()
    expected = render(build_expected(args.scenario_dir))
    destination = args.scenario_dir / "expected-canonical.jsonl"
    if args.check:
        if destination.read_text() != expected:
            print(f"Codex fixture mapping drift: {args.scenario_dir}")
            return 1
        return 0
    if args.write:
        destination.write_text(expected)
        return 0
    print(expected, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
