"""Event/archive projection helpers for worker execution."""

import asyncio
import json as _json
import logging
import os as _os
import tarfile as _tarfile
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.task_event_archive import (
    archive_bundle_name,
    decode_event_line,
    get_or_create_cursor,
    iter_complete_jsonl_records,
)
from app.core.task_log_payloads import append_raw_log_chunk, create_payload
from app.models import TaskLog

_ARCHIVE_STORE = "/opt/codify-archives"

logger = logging.getLogger(__name__)
_CONTAINER_RUNTIME_DIR = "/tmp/codify-runtime"
_CONTAINER_EVENT_JSONL = f"{_CONTAINER_RUNTIME_DIR}/event.jsonl"
_CONTAINER_RUNTIME_JSON = f"{_CONTAINER_RUNTIME_DIR}/runtime.json"
_CONTAINER_CONSOLE_LOG = f"{_CONTAINER_RUNTIME_DIR}/console.log"

_THINKING_OPEN = '<think>'
_THINKING_CLOSE = '</think>'
_PREVIEW_LIMIT = 120


def _dumps(obj: Any) -> str:
    return _json.dumps(obj, ensure_ascii=False)


def _build_preview(text: str, limit: int = _PREVIEW_LIMIT) -> tuple[str, bool]:
    preview = text[:limit]
    return preview, len(text) > limit


def _serialize_tool_input(tool_input: Any) -> str:
    return _dumps(tool_input) if isinstance(tool_input, dict) else str(tool_input)


def _normalize_preview_text(text: str) -> str:
    return " ".join(text.split())


def _build_preview_from_serialized_tool_input(input_text: str) -> tuple[str, bool]:
    try:
        preview_source = _serialize_tool_input(_json.loads(input_text))
    except Exception:  # noqa: BLE001
        preview_source = input_text
    return _build_preview(_normalize_preview_text(preview_source))


def _build_text_preview(text: str) -> tuple[str, bool]:
    return _build_preview(_normalize_preview_text(text))


def _build_tool_output_preview(text: str) -> tuple[str, bool]:
    return _build_preview(text, limit=500)


class WorkerEventProjector:
    """Projects worker runtime artifacts into TaskLog/TaskPayload rows."""

    def __init__(self, sanitize_sensitive_data):
        self._sanitize_sensitive_data = sanitize_sensitive_data
        self.reset()

    def reset(self) -> None:
        self._active_tool_use: dict | None = None
        self._active_text_block: dict | None = None
        self._active_thinking_block: dict | None = None
        self._pending_tool_log_by_id: dict[str, tuple[int, datetime]] = {}
        self._latest_result_record: dict | None = None
        self._run_is_resumed: bool | None = None
        self._timeline_gate_open = True

    async def load_resume_runtime_state(self, *, container: Any) -> None:
        if self._run_is_resumed is not None:
            return
        try:
            result = await asyncio.to_thread(
                container.exec_run,
                f"python3 -c \"import json, pathlib; print(json.loads(pathlib.Path('{_CONTAINER_RUNTIME_JSON}').read_text()).get('resume_session', ''))\"",
                demux=False,
            )
            if result.exit_code != 0:
                self._run_is_resumed = False
                self._timeline_gate_open = True
                return
            resume_session = result.output.decode("utf-8", errors="replace").strip()
            self._run_is_resumed = bool(resume_session)
            self._timeline_gate_open = not self._run_is_resumed
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Failed to load runtime resume state: {exc}")
            self._run_is_resumed = False
            self._timeline_gate_open = True

    @staticmethod
    def _initial_event_cursor_is_pristine(cursor: Any) -> bool:
        return cursor.last_offset == 0 and cursor.last_sequence_no == 0

    @staticmethod
    def _latest_init_index_from_raw_records(records: list[str]) -> int:
        latest_init_index = -1
        for index, raw in enumerate(records):
            try:
                record = decode_event_line(raw)
            except Exception:  # noqa: BLE001
                continue
            if record.get("type") == "system" and record.get("subtype") == "init":
                latest_init_index = index
        return latest_init_index

    def _trim_initial_resumed_records_for_latest_run(
        self, *, cursor: Any, records: list[str]
    ) -> tuple[list[str], int]:
        if not self._run_is_resumed or not self._initial_event_cursor_is_pristine(cursor):
            return records, 0

        latest_init_index = self._latest_init_index_from_raw_records(records)
        if latest_init_index <= 0:
            return records, 0

        self._timeline_gate_open = True
        return records[latest_init_index:], latest_init_index

    @staticmethod
    def _processed_record_bytes(chunk: str, remainder: str) -> int:
        return len(chunk.encode("utf-8")) - len(remainder.encode("utf-8"))

    async def ingest_event_records_from_chunk(
        self, *, task_id: int, chunk: str, cursor: Any, db: AsyncSession
    ) -> None:
        records, remainder = iter_complete_jsonl_records(chunk)
        records_to_process, skipped_count = self._trim_initial_resumed_records_for_latest_run(
            cursor=cursor,
            records=records,
        )
        for raw in records_to_process:
            try:
                record = decode_event_line(raw)
                await self.ingest_event_record(task_id=task_id, record=record, db=db)
                cursor.last_sequence_no += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"[Task {task_id}] Failed to ingest event record: {exc}")
        if skipped_count > 0:
            logger.info(
                f"[Task {task_id}] Skipped {skipped_count} resumed event records before latest system/init"
            )
        cursor.last_offset += self._processed_record_bytes(chunk, remainder)

        if records_to_process and self._run_is_resumed:
            self._timeline_gate_open = True

    async def ingest_event_record(self, *, task_id: int, record: dict, db: AsyncSession) -> None:
        """Project one raw event.jsonl record into TaskLog/TaskPayload rows."""
        record_type = record.get("type")
        if record_type == "system" and record.get("subtype") == "init":
            if self._run_is_resumed:
                self._timeline_gate_open = True
            db.add(TaskLog(
                task_id=task_id,
                log_level="INFO",
                message="",
                log_type="system_init",
                log_metadata=_dumps({"model": record.get("model"), "cwd": record.get("cwd")}),
            ))
        elif record_type == "system" and record.get("subtype") == "compact_boundary":
            db.add(TaskLog(
                task_id=task_id,
                log_level="INFO",
                message="",
                log_type="context_compact",
                log_metadata=_dumps({"session_id": record.get("session_id")}),
            ))
        elif record_type == "system" and record.get("subtype") == "status":
            # compacting / compact_result status events are informational; no log row needed
            pass
        elif record_type == "codify_worker" and record.get("subtype") == "finalization":
            db.add(TaskLog(
                task_id=task_id,
                log_level="INFO",
                message="",
                log_type="worker_finalization",
                log_metadata=_dumps({
                    "commit_sha": record.get("commit_sha") or "",
                    "diff": record.get("diff") or {},
                    "commit_message": record.get("commit_message") or "",
                }),
            ))
        elif not self._timeline_gate_open:
            return
        elif record_type == "stream_event":
            event = record.get("event", {})
            await self._project_stream_event(task_id=task_id, event=event, db=db)
        elif record_type == "assistant":
            await self._project_assistant_message(task_id=task_id, record=record, db=db)
        elif record_type == "user":
            await self._handle_user_event(task_id=task_id, record=record, db=db)
        elif record_type == "result":
            self._latest_result_record = record
            db.add(TaskLog(
                task_id=task_id,
                log_level="INFO",
                message="",
                log_type="run_result",
                log_metadata=_dumps({
                    "subtype": record.get("subtype"),
                    "session_id": record.get("session_id"),
                    "usage": record.get("usage") or {},
                }),
            ))

    async def _create_sanitized_text_payload(
        self,
        *,
        db: AsyncSession,
        task_id: int,
        payload_kind: str,
        text: str,
    ) -> Any:
        sanitized_text = self._sanitize_sensitive_data(text)
        return await create_payload(
            db,
            task_id=task_id,
            payload_kind=payload_kind,
            text=sanitized_text,
        )

    async def _add_text_log_with_payload(
        self,
        *,
        db: AsyncSession,
        task_id: int,
        payload_kind: str,
        log_type: str,
        text: str,
    ) -> None:
        sanitized_text = self._sanitize_sensitive_data(text)
        if not sanitized_text:
            return
        payload = await self._create_sanitized_text_payload(
            db=db,
            task_id=task_id,
            payload_kind=payload_kind,
            text=sanitized_text,
        )
        preview, truncated = _build_text_preview(sanitized_text)
        db.add(TaskLog(
            task_id=task_id,
            log_level="INFO",
            message="",
            log_type=log_type,
            log_metadata=_dumps({
                "payload_id": payload.id,
                "char_count": len(sanitized_text),
                "preview": preview,
                "truncated": truncated,
            }),
        ))

    async def _handle_user_event(self, *, task_id: int, record: dict, db: AsyncSession) -> None:
        """Handle user-turn events — primarily tool_result correlation."""
        message = record.get("message", {})
        for item in (message.get("content") or []):
            if item.get("type") != "tool_result":
                continue
            tool_use_id = item.get("tool_use_id")
            is_error = item.get("is_error", False)
            raw_content = item.get("content", "")

            if isinstance(raw_content, str):
                output_text = raw_content
            elif isinstance(raw_content, list):
                parts: list[str] = []
                for block in raw_content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                output_text = "".join(parts)
            else:
                output_text = ""

            pending = self._pending_tool_log_by_id.pop(tool_use_id, None)
            if pending is None:
                continue
            log_id, start_time = pending
            pending_log = await db.get(TaskLog, log_id)
            if pending_log is None:
                continue
            payload = await self._create_sanitized_text_payload(
                db=db,
                task_id=task_id,
                payload_kind="tool_output",
                text=output_text,
            )
            sanitized_output_text = self._sanitize_sensitive_data(output_text)
            _, output_truncated = _build_tool_output_preview(sanitized_output_text)
            meta = _json.loads(pending_log.log_metadata or "{}")
            meta["output_payload_id"] = payload.id
            meta["output_truncated"] = output_truncated
            meta["output_char_count"] = len(sanitized_output_text)
            meta["error"] = is_error
            meta["duration_ms"] = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            pending_log.log_metadata = _dumps(meta)

    async def _project_assistant_message(self, *, task_id: int, record: dict, db: AsyncSession) -> None:
        """Project a complete assistant message (non-streaming format)."""
        message = record.get("message", {})
        content_blocks = message.get("content") or []

        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")

            if block_type == "tool_use":
                tool_use_id = block.get("id", "")
                tool_name = block.get("name", "")
                tool_input = block.get("input", {})
                input_text = _serialize_tool_input(tool_input)
                sanitized_input_text = self._sanitize_sensitive_data(input_text)
                input_preview, input_truncated = _build_preview_from_serialized_tool_input(sanitized_input_text)
                start_time = datetime.now(UTC)
                payload = await self._create_sanitized_text_payload(
                    db=db,
                    task_id=task_id,
                    payload_kind="tool_input",
                    text=input_text,
                )
                log = TaskLog(
                    task_id=task_id,
                    log_level="INFO",
                    message=f"Tool call: {tool_name}",
                    log_type="tool_call",
                    log_metadata=_dumps({
                        "tool_use_id": tool_use_id,
                        "name": tool_name,
                        "input": tool_input,
                        "input_payload_id": payload.id,
                        "input_preview": input_preview,
                        "input_truncated": input_truncated,
                    }),
                )
                db.add(log)
                await db.flush()
                if tool_use_id and log.id:
                    self._pending_tool_log_by_id[tool_use_id] = (log.id, start_time)

            elif block_type == "text":
                text = block.get("text", "")
                if not text:
                    continue
                remaining = text
                while remaining:
                    open_idx = remaining.find(_THINKING_OPEN)
                    if open_idx < 0:
                        await self._add_text_log_with_payload(
                            db=db,
                            task_id=task_id,
                            payload_kind="assistant_text",
                            log_type="assistant_text",
                            text=remaining,
                        )
                        break

                    if open_idx > 0:
                        await self._add_text_log_with_payload(
                            db=db,
                            task_id=task_id,
                            payload_kind="assistant_text",
                            log_type="assistant_text",
                            text=remaining[:open_idx],
                        )

                    close_idx = remaining.find(_THINKING_CLOSE, open_idx + len(_THINKING_OPEN))
                    if close_idx < 0:
                        await self._add_text_log_with_payload(
                            db=db,
                            task_id=task_id,
                            payload_kind="thinking",
                            log_type="thinking",
                            text=remaining[open_idx + len(_THINKING_OPEN):],
                        )
                        break

                    await self._add_text_log_with_payload(
                        db=db,
                        task_id=task_id,
                        payload_kind="thinking",
                        log_type="thinking",
                        text=remaining[open_idx + len(_THINKING_OPEN):close_idx],
                    )
                    remaining = remaining[close_idx + len(_THINKING_CLOSE):].lstrip("\n")

            elif block_type == "thinking":
                await self._add_text_log_with_payload(
                    db=db,
                    task_id=task_id,
                    payload_kind="thinking",
                    log_type="thinking",
                    text=block.get("thinking", ""),
                )

    async def _flush_tool_use_projection(self, *, task_id: int, db: AsyncSession) -> None:
        """Flush accumulated tool_use block into TaskLog + TaskPayload."""
        tool_use = self._active_tool_use
        if tool_use is None:
            return
        start_time = datetime.now(UTC)
        input_text = "".join(tool_use["input_parts"])
        try:
            tool_input = _json.loads(input_text)
        except Exception:
            tool_input = {}
        sanitized_input_text = self._sanitize_sensitive_data(input_text)
        payload = await self._create_sanitized_text_payload(
            db=db,
            task_id=task_id,
            payload_kind="tool_input",
            text=input_text,
        )
        input_preview, input_truncated = _build_preview_from_serialized_tool_input(sanitized_input_text)
        log = TaskLog(
            task_id=task_id,
            log_level="INFO",
            message=f"Tool call: {tool_use['name']}",
            log_type="tool_call",
            log_metadata=_dumps({
                "tool_use_id": tool_use["id"],
                "name": tool_use["name"],
                "input": tool_input,
                "input_payload_id": payload.id,
                "input_preview": input_preview,
                "input_truncated": input_truncated,
            }),
        )
        db.add(log)
        await db.flush()
        if tool_use["id"] and log.id:
            self._pending_tool_log_by_id[tool_use["id"]] = (log.id, start_time)
        self._active_tool_use = None

    async def _project_stream_event(self, *, task_id: int, event: dict, db: AsyncSession) -> None:
        """Map one stream_event payload to TaskLog/TaskPayload mutations."""
        event_type = event.get("type")
        content_block = event.get("content_block", {})
        block_type = content_block.get("type")

        if event_type == "content_block_start":
            if block_type == "tool_use":
                self._active_tool_use = {
                    "id": content_block["id"],
                    "name": content_block["name"],
                    "input_parts": [],
                }
                self._active_text_block = None
                self._active_thinking_block = None
            elif block_type == "text":
                self._active_text_block = {"parts": []}
                self._active_tool_use = None
                self._active_thinking_block = None
            elif block_type == "thinking":
                self._active_thinking_block = {"parts": []}
                self._active_text_block = None
                self._active_tool_use = None

        elif event_type == "content_block_delta":
            delta = event.get("delta", {})
            delta_type = delta.get("type")
            if delta_type == "input_json_delta" and self._active_tool_use is not None:
                self._active_tool_use["input_parts"].append(delta.get("partial_json", ""))
            elif delta_type == "text_delta" and self._active_text_block is not None:
                self._active_text_block["parts"].append(delta.get("text", ""))
            elif delta_type == "thinking_delta" and self._active_thinking_block is not None:
                self._active_thinking_block["parts"].append(delta.get("thinking", ""))

        elif event_type == "content_block_stop":
            if self._active_tool_use is not None:
                await self._flush_tool_use_projection(task_id=task_id, db=db)
            elif self._active_thinking_block is not None:
                text = "".join(self._active_thinking_block["parts"])
                await self._add_text_log_with_payload(
                    db=db,
                    task_id=task_id,
                    payload_kind="thinking",
                    log_type="thinking",
                    text=text,
                )
                self._active_thinking_block = None
            elif self._active_text_block is not None:
                text = "".join(self._active_text_block["parts"])
                await self._add_text_log_with_payload(
                    db=db,
                    task_id=task_id,
                    payload_kind="assistant_text",
                    log_type="assistant_text",
                    text=text,
                )
                self._active_text_block = None

    async def tail_event_jsonl(self, *, task_id: int, container: Any, db: AsyncSession) -> None:
        """Read newly appended event records from container's event.jsonl and project them."""
        await self.load_resume_runtime_state(container=container)
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
            chunk = result.output.decode("utf-8", errors="replace")
            if not chunk:
                return
            await self.ingest_event_records_from_chunk(task_id=task_id, chunk=chunk, cursor=cursor, db=db)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[Task {task_id}] _tail_event_jsonl error: {exc}")
        await db.commit()

    async def backfill_event_jsonl_from_archive(
        self, *, task_id: int, db: AsyncSession
    ) -> None:
        """Read event.jsonl from the saved archive and project missing event records."""
        archive_path = _os.path.join(_ARCHIVE_STORE, archive_bundle_name(task_id=task_id))
        if not _os.path.exists(archive_path):
            return
        try:
            with _tarfile.open(archive_path, "r:gz") as tf:
                event_member = next(
                    (m for m in tf.getmembers() if m.name == "event.jsonl"), None
                )
                if event_member is None:
                    return
                extracted = tf.extractfile(event_member)
                if extracted is None:
                    return
                full_text = extracted.read().decode("utf-8", errors="replace")

                runtime_member = next(
                    (m for m in tf.getmembers() if m.name == "runtime.json"), None
                )
                if runtime_member is not None:
                    runtime_extracted = tf.extractfile(runtime_member)
                    if runtime_extracted is not None:
                        runtime_data = _json.loads(runtime_extracted.read())
                        resume_session = runtime_data.get("resume_session", "")
                        self._run_is_resumed = bool(resume_session)
                        self._timeline_gate_open = not self._run_is_resumed
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[Task {task_id}] Could not backfill event.jsonl from archive: {exc}")
            return

        cursor = await get_or_create_cursor(db, task_id=task_id, stream_name="event_jsonl")
        full_bytes = full_text.encode("utf-8")
        if cursor.last_offset >= len(full_bytes):
            return

        # If the system/init record was already ingested (non-zero cursor), the
        # timeline gate should already be open regardless of resume state.
        if cursor.last_sequence_no > 0:
            self._timeline_gate_open = True

        new_data_bytes = full_bytes[cursor.last_offset:]
        new_data = new_data_bytes.decode("utf-8", errors="replace")
        if not new_data:
            return
        await self.ingest_event_records_from_chunk(
            task_id=task_id, chunk=new_data, cursor=cursor, db=db
        )
        await db.commit()

    async def backfill_console_log_from_archive(
        self, *, task_id: int, db: AsyncSession
    ) -> None:
        """Read console.log from the saved runtime archive and fill missing raw log chunks."""
        archive_path = _os.path.join(_ARCHIVE_STORE, archive_bundle_name(task_id=task_id))
        if not _os.path.exists(archive_path):
            return
        try:
            with _tarfile.open(archive_path, "r:gz") as tf:
                member = next((m for m in tf.getmembers() if m.name == "console.log"), None)
                if member is None:
                    return
                extracted = tf.extractfile(member)
                if extracted is None:
                    return
                full_text = extracted.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[Task {task_id}] Could not backfill console.log from archive: {exc}")
            return

        cursor = await get_or_create_cursor(db, task_id=task_id, stream_name="console_log")
        if cursor.last_offset >= len(full_text.encode("utf-8")):
            return

        new_data = full_text.encode("utf-8")[cursor.last_offset:].decode("utf-8", errors="replace")
        if not new_data:
            return
        await append_raw_log_chunk(
            db,
            task_id=task_id,
            sequence_no=cursor.last_sequence_no + 1,
            text=new_data,
        )
        cursor.last_offset = len(full_text.encode("utf-8"))
        cursor.last_sequence_no += 1

    async def tail_console_log(self, *, task_id: int, container: Any, db: AsyncSession) -> None:
        """Read newly appended bytes from console.log and persist as raw log chunks."""
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
            await append_raw_log_chunk(db, task_id=task_id, sequence_no=cursor.last_sequence_no + 1, text=text)
            cursor.last_sequence_no += 1
            cursor.last_offset += len(result.output)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[Task {task_id}] _tail_console_log error: {exc}")
        await db.commit()
