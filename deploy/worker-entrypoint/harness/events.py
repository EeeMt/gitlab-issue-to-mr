#!/usr/bin/env python3
"""Standalone Canonical Event writer used inside Worker containers."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = "codify.worker.event/v1"
V2_CONTRACT = "codify.worker.harness/v2"
TASK_TERMINALS = {"run.completed", "run.failed"}
HARNESS_TERMINAL_TYPES = {"harness.completed", "harness.failed"}
KNOWN_TYPES = {
    "run.started",
    "model.resolved",
    "message.delta",
    "message.completed",
    "reasoning_summary.delta",
    "reasoning_summary.completed",
    "reasoning_summary.interrupted",
    "reasoning_summary.started",
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
    "control.command.delivered",
    "control.command.rejected",
    "control.queue.updated",
    "agent_settled",
    "diagnostic",
}


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for canonical event emission")
    return value


def _paths() -> tuple[Path, Path]:
    runtime_dir = Path(_required_env("CODIFY_RUNTIME_DIR"))
    return runtime_dir / "event.jsonl", runtime_dir / ".event.lock"


def _outer_timeout_requested(runtime_dir: Path) -> bool:
    """Return whether the backend requested a wall-clock timeout stop."""
    return (runtime_dir / ".codify-timeout").is_file()


def _normalize_payload(event_type: str, payload: dict) -> dict:
    if event_type in {"usage.updated", "usage.final"}:
        source = payload.get("usage") or {}
        payload["usage"] = {
            "input_tokens": source.get("input_tokens"),
            "cached_input_tokens": source.get("cached_input_tokens"),
            "output_tokens": source.get("output_tokens"),
            "reasoning_tokens": source.get("reasoning_tokens"),
            "cost": source.get("cost"),
            "currency": source.get("currency"),
            "engine_fields": source.get("engine_fields") or {},
        }
    return payload


def emit(event_type: str, payload: dict, raw_ref: dict | None) -> dict:
    if event_type not in KNOWN_TYPES:
        if event_type.startswith("run."):
            raise RuntimeError(f"unknown Task terminal event: {event_type}")
        payload = {
            "code": "unknown_event_type",
            "original_type": event_type,
            "raw_ref": raw_ref,
        }
        event_type = "diagnostic"
    event_path, lock_path = _paths()
    if event_type in HARNESS_TERMINAL_TYPES | TASK_TERMINALS and _outer_timeout_requested(
        event_path.parent
    ):
        # Docker uses SIGTERM/143 for both user cancellation and the backend's
        # wall-clock timeout. The marker is written immediately before the
        # backend calls Docker stop, so every terminal emitted after that point
        # carries the authoritative timeout taxonomy.
        payload = dict(payload)
        failure = payload.get("failure")
        failure = dict(failure) if isinstance(failure, dict) else {}
        failure["kind"] = "timeout"
        failure["message"] = "Task timed out"
        payload["failure"] = failure
        if event_type == "run.failed":
            payload["status"] = "failed"
            payload["success"] = False
    event_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)
    with lock_path.open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # seq is derived from the stream itself: the fsync'd event append is the
        # single source of truth. A crash between an append and any auxiliary
        # state can therefore never make a recovered container regenerate a
        # divergent seq for the same record.
        first_event = None
        last_type = None
        last_seq = 0
        harness_terminal_seen = False
        if event_path.exists():
            for line in event_path.read_text(encoding="utf-8", errors="strict").splitlines():
                if not line.strip():
                    continue
                parsed = json.loads(line)
                first_event = first_event or parsed
                last_type = parsed.get("type")
                last_seq += 1
                if last_type in HARNESS_TERMINAL_TYPES:
                    harness_terminal_seen = True
            if last_type in TASK_TERMINALS:
                raise RuntimeError("cannot append an event after the Task terminal")
        if last_seq == 0 and event_type != "run.started":
            raise RuntimeError(
                f"run.started must be the first canonical event; got {event_type}"
            )
        if event_type == "run.started" and last_seq > 0:
            raise RuntimeError("run.started appears more than once")
        if event_type in HARNESS_TERMINAL_TYPES and harness_terminal_seen:
            raise RuntimeError("harness terminal appears more than once")
        if event_type.startswith("delivery.") and not harness_terminal_seen:
            raise RuntimeError("delivery event appears before harness terminal")
        if event_type == "worker.finalization":
            if not harness_terminal_seen:
                raise RuntimeError("worker.finalization appears before harness terminal")
            if last_type == "worker.finalization":
                raise RuntimeError("worker.finalization appears more than once")
        if event_type in TASK_TERMINALS:
            if not harness_terminal_seen:
                raise RuntimeError("task terminal appears before harness terminal")
            if last_type != "worker.finalization":
                raise RuntimeError("Task terminal must immediately follow worker.finalization")
        if last_type == "worker.finalization" and event_type not in TASK_TERMINALS:
            raise RuntimeError("only the Task terminal may follow worker.finalization")
        harness = {
            "key": _required_env("CODIFY_HARNESS_KEY"),
            "adapter_version": _required_env("CODIFY_ADAPTER_VERSION"),
            "cli_version": _required_env("CODIFY_CLI_VERSION"),
        }
        # V2 attempts carry the control transport and the model protocols under
        # the harness envelope; the frozen manifest (or the adapter-exported
        # env) supplies them. Default to the V1 envelope when unset.
        contract = os.getenv("CODIFY_RUNTIME_CONTRACT_VERSION", "").strip()
        if contract == V2_CONTRACT:
            # Reuse the V2 schema when the adapter declares it.
            harness["control_transport"] = {
                "kind": os.getenv("CODIFY_HARNESS_CONTROL_TRANSPORT_KIND", "rpc_stdio"),
                "protocol": os.getenv("CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL"),
            }
            protocols = os.getenv("CODIFY_HARNESS_MODEL_PROTOCOLS", "")
            harness["model_protocols"] = [
                p for p in protocols.split(",") if p.strip()
            ] or [os.getenv("CODIFY_HARNESS_MODEL_PROTOCOL", "anthropic_messages")]
        schema = SCHEMA
        event_schema_env = os.getenv("CODIFY_EVENT_SCHEMA", "")
        if event_schema_env:
            schema = event_schema_env
        elif contract == V2_CONTRACT:
            schema = "codify.worker.event/v2"
        if first_event is not None and first_event.get("harness") != harness:
            raise RuntimeError("Harness identity changed inside one canonical attempt")
        seq = last_seq + 1
        event = {
            "schema": schema,
            "event_id": str(uuid.uuid4()),
            "attempt_id": _required_env("CODIFY_ATTEMPT_ID"),
            "seq": seq,
            "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "type": event_type,
            "task_id": int(_required_env("TASK_ID")),
            "harness": harness,
            "payload": _normalize_payload(event_type, payload),
        }
        if raw_ref is not None:
            event["raw_ref"] = dict(raw_ref)
        with event_path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            output.flush()
            os.fsync(output.fileno())
        return event


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("event_type")
    parser.add_argument("--payload", default="{}")
    parser.add_argument("--raw-stream")
    parser.add_argument("--raw-line", type=int)
    args = parser.parse_args()
    payload = json.loads(args.payload)
    if not isinstance(payload, dict):
        raise ValueError("canonical event payload must be an object")
    raw_ref = None
    if args.raw_stream is not None or args.raw_line is not None:
        if args.raw_stream is None or args.raw_line is None or args.raw_line < 1:
            raise ValueError("raw stream and positive raw line must be provided together")
        raw_ref = {"stream": args.raw_stream, "line": args.raw_line}
    emitted = emit(args.event_type, payload, raw_ref)
    print(json.dumps(emitted, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"canonical event emission failed: {exc}", file=sys.stderr)
        raise
