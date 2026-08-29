"""Canonical worker event/archive projection helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tarfile
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.harness_attempts import ingest_canonical_event
from app.core.harness_protocol import (
    CONTROL_EVENT_TYPES,
    HarnessProtocolError,
    validate_event_by_schema,
)
from app.core.task_command_gate import (
    begin_control_drain,
    close_control_gate,
    reopen_control_after_native_turn_start,
)
from app.core.task_event_archive import (
    archive_bundle_name,
    decode_event_line,
    get_or_create_cursor,
    iter_complete_jsonl_records,
)
from app.core.task_log_payloads import append_raw_log_chunk, create_payload
from app.models import TaskLog

logger = logging.getLogger(__name__)

_ARCHIVE_STORE = "/opt/codify-archives"
_CONTAINER_RUNTIME_DIR = "/tmp/codify-runtime"
_CONTAINER_EVENT_JSONL = f"{_CONTAINER_RUNTIME_DIR}/event.jsonl"
_CONTAINER_CONSOLE_LOG = f"{_CONTAINER_RUNTIME_DIR}/console.log"
_PREVIEW_LIMIT = 120


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _preview(text: str, limit: int = _PREVIEW_LIMIT) -> tuple[str, bool]:
    normalized = " ".join(text.split())
    return normalized[:limit], len(normalized) > limit


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return _dumps(value)


class WorkerEventProjector:
    """Validate and project only ``codify.worker.event/v1`` records."""

    def __init__(self, sanitize_sensitive_data):
        self._sanitize_sensitive_data = sanitize_sensitive_data
        self.reset()

    def reset(self) -> None:
        self._message_parts: list[str] = []
        self._reasoning_parts: list[str] = []
        self._pending_tool_log_by_id: dict[str, tuple[int, datetime]] = {}

    async def load_resume_runtime_state(self, *, container: Any) -> None:
        """Compatibility no-op: attempts, not Claude init records, define replay state."""

    @staticmethod
    def _processed_record_bytes(chunk: str, remainder: str) -> int:
        return len(chunk.encode("utf-8")) - len(remainder.encode("utf-8"))

    async def _payload_log(
        self,
        *,
        db: AsyncSession,
        task_id: int,
        payload_kind: str,
        log_type: str,
        text: str,
    ) -> None:
        sanitized = self._sanitize_sensitive_data(text)
        if not sanitized:
            return
        payload = await create_payload(
            db,
            task_id=task_id,
            payload_kind=payload_kind,
            text=sanitized,
        )
        preview, truncated = _preview(sanitized)
        db.add(
            TaskLog(
                task_id=task_id,
                log_level="INFO",
                message="",
                log_type=log_type,
                log_metadata=_dumps(
                    {
                        "payload_id": payload.id,
                        "char_count": len(sanitized),
                        "preview": preview,
                        "truncated": truncated,
                    }
                ),
            )
        )

    async def _project_tool_started(
        self,
        *,
        task_id: int,
        payload: dict,
        db: AsyncSession,
    ) -> None:
        tool_id = str(payload.get("tool_id") or "")
        name = str(payload.get("name") or "")
        input_text = self._sanitize_sensitive_data(_text(payload.get("input") or {}))
        body = await create_payload(
            db,
            task_id=task_id,
            payload_kind="tool_input",
            text=input_text,
        )
        preview, truncated = _preview(input_text)
        log = TaskLog(
            task_id=task_id,
            log_level="INFO",
            message=f"Tool call: {name}",
            log_type="tool_call",
            log_metadata=_dumps(
                {
                    "tool_use_id": tool_id,
                    "name": name,
                    "input": payload.get("input") or {},
                    "input_payload_id": body.id,
                    "input_preview": preview,
                    "input_truncated": truncated,
                }
            ),
        )
        db.add(log)
        await db.flush()
        if tool_id and log.id:
            self._pending_tool_log_by_id[tool_id] = (log.id, datetime.now(UTC))

    async def _find_tool_log(self, db: AsyncSession, task_id: int, tool_id: str) -> TaskLog | None:
        pending = self._pending_tool_log_by_id.pop(tool_id, None)
        if pending is not None:
            return await db.get(TaskLog, pending[0])
        candidates = list(
            (
                await db.execute(
                    select(TaskLog)
                    .where(TaskLog.task_id == task_id, TaskLog.log_type == "tool_call")
                    .order_by(TaskLog.id.desc())
                    .limit(100)
                )
            ).scalars()
        )
        for candidate in candidates:
            try:
                metadata = json.loads(candidate.log_metadata or "{}")
            except json.JSONDecodeError:
                continue
            if metadata.get("tool_use_id") == tool_id:
                return candidate
        return None

    async def _project_tool_completed(
        self,
        *,
        task_id: int,
        payload: dict,
        db: AsyncSession,
    ) -> None:
        tool_id = str(payload.get("tool_id") or "")
        pending = await self._find_tool_log(db, task_id, tool_id)
        if pending is None:
            db.add(
                TaskLog(
                    task_id=task_id,
                    log_level="WARNING",
                    message="Canonical tool completion has no matching start",
                    log_type="diagnostic",
                    log_metadata=_dumps({"code": "tool_start_missing", "tool_id": tool_id}),
                )
            )
            return
        output = self._sanitize_sensitive_data(_text(payload.get("output")))
        output_payload = await create_payload(
            db,
            task_id=task_id,
            payload_kind="tool_output",
            text=output,
        )
        metadata = json.loads(pending.log_metadata or "{}")
        metadata.update(
            {
                "output_payload_id": output_payload.id,
                "output_truncated": len(output) > 500,
                "output_char_count": len(output),
                "error": bool(payload.get("error", False)),
            }
        )
        if payload.get("exit_code") is not None:
            metadata["exit_code"] = payload["exit_code"]
        if payload.get("error_message"):
            metadata["error_message"] = self._sanitize_sensitive_data(
                str(payload["error_message"])
            )
        pending.log_metadata = _dumps(metadata)

    async def ingest_event_record(
        self,
        *,
        task_id: int,
        record: dict,
        db: AsyncSession,
    ) -> bool:
        """Ingest one canonical record; return false for an exact duplicate."""
        normalized = validate_event_by_schema(record)
        if normalized["task_id"] != task_id:
            raise HarnessProtocolError("canonical event task_id does not match projector task")
        ingest = await ingest_canonical_event(db, normalized)
        if ingest.duplicate:
            return False
        event_type = normalized["type"]
        payload = normalized["payload"]

        if event_type == "agent_settled":
            await begin_control_drain(db, attempt=ingest.attempt)
        elif event_type in {"run.completed", "run.failed"}:
            await close_control_gate(
                db,
                attempt=ingest.attempt,
                reason="harness reached terminal event",
            )

        if event_type == "model.resolved":
            db.add(
                TaskLog(
                    task_id=task_id,
                    log_level="INFO",
                    message="",
                    log_type="system_init",
                    log_metadata=_dumps(
                        {"model": payload.get("model"), "session_id": payload.get("session_id")}
                    ),
                )
            )
        elif event_type == "message.delta":
            self._message_parts.append(_text(payload.get("text")))
        elif event_type == "message.completed":
            text = _text(payload.get("text")) or "".join(self._message_parts)
            self._message_parts.clear()
            await self._payload_log(
                db=db,
                task_id=task_id,
                payload_kind="assistant_text",
                log_type="assistant_text",
                text=text,
            )
        elif event_type == "reasoning_summary.delta":
            self._reasoning_parts.append(_text(payload.get("text")))
        elif event_type == "reasoning_summary.completed":
            text = _text(payload.get("text")) or "".join(self._reasoning_parts)
            self._reasoning_parts.clear()
            await self._payload_log(
                db=db,
                task_id=task_id,
                payload_kind="thinking",
                log_type="thinking",
                text=text,
            )
        elif event_type == "tool.started":
            await self._project_tool_started(task_id=task_id, payload=payload, db=db)
        elif event_type == "tool.completed":
            await self._project_tool_completed(task_id=task_id, payload=payload, db=db)
        elif event_type == "context.compacted":
            compact_metadata = {
                key: payload.get(key)
                for key in (
                    "session_id",
                    "reason",
                    "aborted",
                    "will_retry",
                    "tokens_before",
                    "estimated_tokens_after",
                    "auto",
                    "overflow",
                    "tail_start_id",
                    "summary",
                )
                if payload.get(key) is not None
            }
            db.add(
                TaskLog(
                    task_id=task_id,
                    log_level="INFO",
                    message="",
                    log_type="context_compact",
                    log_metadata=_dumps(compact_metadata),
                )
            )
        elif event_type in {"harness.completed", "harness.failed"}:
            db.add(
                TaskLog(
                    task_id=task_id,
                    log_level="INFO" if event_type.endswith("completed") else "ERROR",
                    message="",
                    log_type="harness_result",
                    log_metadata=_dumps({"type": event_type, **payload}),
                )
            )
        elif event_type == "usage.final":
            db.add(
                TaskLog(
                    task_id=task_id,
                    log_level="INFO",
                    message="",
                    log_type="usage_final",
                    log_metadata=_dumps(payload),
                )
            )
        elif event_type == "worker.finalization":
            db.add(
                TaskLog(
                    task_id=task_id,
                    log_level="INFO",
                    message="",
                    log_type="worker_finalization",
                    log_metadata=_dumps(payload),
                )
            )
        elif event_type in {"run.completed", "run.failed"}:
            db.add(
                TaskLog(
                    task_id=task_id,
                    log_level="INFO" if event_type == "run.completed" else "ERROR",
                    message="",
                    log_type="run_result",
                    log_metadata=_dumps({"type": event_type, **payload}),
                )
            )
        elif event_type in CONTROL_EVENT_TYPES:
            # V2 control-plane audit events. Projector only records them as a
            # product-visible diagnostic; it never writes back to
            # task_harness_commands rows (schemas.md §3.4 / §4.1). Command text
            # carried by queue.updated is projected only through the existing
            # sanitizer so tokens are never echoed verbatim (plan §5.3).
            sanitized_payload = dict(payload)
            if event_type == "control.queue.updated" and isinstance(payload.get("queue"), list):
                sanitized_queue = []
                for item in payload["queue"]:
                    entry = dict(item) if isinstance(item, dict) else {"text": item}
                    text = entry.get("text")
                    if isinstance(text, str):
                        entry["text"] = self._sanitize_sensitive_data(text)
                    sanitized_queue.append(entry)
                sanitized_payload["queue"] = sanitized_queue
            db.add(
                TaskLog(
                    task_id=task_id,
                    log_level="INFO",
                    message="",
                    log_type="control_event",
                    log_metadata=_dumps({"type": event_type, **sanitized_payload}),
                )
            )
        elif event_type == "agent_settled":
            db.add(
                TaskLog(
                    task_id=task_id,
                    log_level="INFO",
                    message="",
                    log_type="control_event",
                    log_metadata=_dumps({"type": event_type, **payload}),
                )
            )
        elif event_type == "diagnostic":
            if payload.get("code") == "pi_follow_up_turn_started":
                await reopen_control_after_native_turn_start(
                    db,
                    attempt=ingest.attempt,
                    command_id=payload.get("command_id"),
                    native_id=payload.get("native_id"),
                )
            db.add(
                TaskLog(
                    task_id=task_id,
                    log_level="WARNING",
                    message=str(payload.get("message") or payload.get("code") or "diagnostic"),
                    log_type="diagnostic",
                    log_metadata=_dumps(payload),
                )
            )
        return True

    async def ingest_event_records_from_chunk(
        self,
        *,
        task_id: int,
        chunk: str,
        cursor: Any,
        db: AsyncSession,
    ) -> None:
        records, remainder = iter_complete_jsonl_records(chunk)
        processed = 0
        for raw in records:
            record = decode_event_line(raw)
            normalized = validate_event_by_schema(record)
            if cursor.attempt_id is None and cursor.last_offset == 0:
                cursor.attempt_id = normalized["attempt_id"]
            elif cursor.attempt_id != normalized["attempt_id"]:
                raise HarnessProtocolError("event stream changed attempt without a new cursor")
            async with db.begin_nested():
                accepted = await self.ingest_event_record(
                    task_id=task_id,
                    record=normalized,
                    db=db,
                )
            if accepted:
                cursor.last_sequence_no = normalized["seq"]
            processed += len((raw + "\n").encode("utf-8"))
        cursor.last_offset += processed
        # Never consume the truncated tail. It will be retried after the writer appends EOF.
        if not remainder and processed != self._processed_record_bytes(chunk, remainder):
            raise HarnessProtocolError("event stream byte accounting mismatch")

    async def tail_event_jsonl(self, *, task_id: int, container: Any, db: AsyncSession) -> None:
        cursor = await get_or_create_cursor(db, task_id=task_id, stream_name="event_jsonl")
        offset = cursor.last_offset + 1
        try:
            result = await asyncio.to_thread(
                container.exec_run,
                f"tail -c +{offset} {_CONTAINER_EVENT_JSONL}",
                demux=False,
            )
            if result.exit_code != 0 or not result.output:
                return
            # errors="replace" keeps a torn final line (a crash mid-write that
            # split a multi-byte char) from crashing the whole ingest: the
            # partial line becomes the unconsumed remainder and is re-read from
            # the cursor offset after the writer finishes it.
            chunk = result.output.decode("utf-8", errors="replace")
            if chunk:
                await self.ingest_event_records_from_chunk(
                    task_id=task_id,
                    chunk=chunk,
                    cursor=cursor,
                    db=db,
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            logger.warning("[Task %s] canonical event tail failed: %s", task_id, exc)
            raise

    async def backfill_event_jsonl_from_archive(self, *, task_id: int, db: AsyncSession) -> None:
        archive_path = os.path.join(_ARCHIVE_STORE, archive_bundle_name(task_id=task_id))
        if not os.path.exists(archive_path):
            return
        try:
            with tarfile.open(archive_path, "r:gz") as archive:
                member = next((item for item in archive.getmembers() if item.name == "event.jsonl"), None)
                if member is None:
                    return
                extracted = archive.extractfile(member)
                if extracted is None:
                    return
                full_bytes = extracted.read()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Task %s] canonical archive read failed: %s", task_id, exc)
            return
        cursor = await get_or_create_cursor(db, task_id=task_id, stream_name="event_jsonl")
        if cursor.last_offset >= len(full_bytes):
            return
        new_data = full_bytes[cursor.last_offset :].decode("utf-8", errors="replace")
        await self.ingest_event_records_from_chunk(
            task_id=task_id,
            chunk=new_data,
            cursor=cursor,
            db=db,
        )
        await db.commit()

    async def backfill_console_log_from_archive(self, *, task_id: int, db: AsyncSession) -> None:
        archive_path = os.path.join(_ARCHIVE_STORE, archive_bundle_name(task_id=task_id))
        if not os.path.exists(archive_path):
            return
        try:
            with tarfile.open(archive_path, "r:gz") as archive:
                member = next((item for item in archive.getmembers() if item.name == "console.log"), None)
                if member is None:
                    return
                extracted = archive.extractfile(member)
                if extracted is None:
                    return
                full_bytes = extracted.read()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[Task %s] console archive read failed: %s", task_id, exc)
            return
        cursor = await get_or_create_cursor(db, task_id=task_id, stream_name="console_log")
        if cursor.last_offset >= len(full_bytes):
            return
        new_data = full_bytes[cursor.last_offset :].decode("utf-8", errors="replace")
        await append_raw_log_chunk(
            db,
            task_id=task_id,
            sequence_no=cursor.last_sequence_no + 1,
            text=new_data,
        )
        cursor.last_offset = len(full_bytes)
        cursor.last_sequence_no += 1
        await db.commit()

    async def tail_console_log(self, *, task_id: int, container: Any, db: AsyncSession) -> None:
        cursor = await get_or_create_cursor(db, task_id=task_id, stream_name="console_log")
        offset = cursor.last_offset + 1
        try:
            result = await asyncio.to_thread(
                container.exec_run,
                f"tail -c +{offset} {_CONTAINER_CONSOLE_LOG}",
                demux=False,
            )
            if result.exit_code != 0 or not result.output:
                return
            text = result.output.decode("utf-8", errors="replace")
            if not text:
                return
            await append_raw_log_chunk(
                db,
                task_id=task_id,
                sequence_no=cursor.last_sequence_no + 1,
                text=text,
            )
            cursor.last_sequence_no += 1
            cursor.last_offset += len(result.output)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            logger.debug("[Task %s] console tail failed: %s", task_id, exc)
