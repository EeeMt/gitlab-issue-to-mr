"""Helpers for persisting payload bodies and raw log chunks."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.task_event_archive import get_or_create_cursor
from app.models import TaskPayload, TaskRawLogChunk


async def create_payload(
    db: AsyncSession,
    *,
    task_id: int,
    payload_kind: str,
    text: str,
) -> TaskPayload:
    """Insert a TaskPayload row and return it (flushed, id assigned)."""
    content = text.encode("utf-8")
    payload = TaskPayload(
        task_id=task_id,
        payload_kind=payload_kind,
        encoding="identity",
        content=content,
        char_count=len(text),
        byte_count=len(content),
    )
    db.add(payload)
    await db.flush()
    return payload


async def append_raw_log_chunk(
    db: AsyncSession,
    *,
    task_id: int,
    sequence_no: int,
    text: str,
) -> TaskRawLogChunk:
    """Append a raw log chunk row (flushed, id assigned)."""
    content = text.encode("utf-8")
    chunk = TaskRawLogChunk(
        task_id=task_id,
        sequence_no=sequence_no,
        encoding="identity",
        content=content,
        char_count=len(text),
        byte_count=len(content),
    )
    db.add(chunk)
    await db.flush()
    return chunk


async def persist_raw_log_snapshot(
    db: AsyncSession,
    *,
    task_id: int,
    content: bytes,
) -> None:
    """Persist bytes missing from a stable, full console.log snapshot."""
    if not content:
        return
    cursor = await get_or_create_cursor(db, task_id=task_id, stream_name="console_log")
    if cursor.last_offset >= len(content):
        return

    new_bytes = content[cursor.last_offset:]
    text = new_bytes.decode("utf-8", errors="replace")
    if not text:
        return

    await append_raw_log_chunk(
        db,
        task_id=task_id,
        sequence_no=cursor.last_sequence_no + 1,
        text=text,
    )
    cursor.last_offset = len(content)
    cursor.last_sequence_no += 1
