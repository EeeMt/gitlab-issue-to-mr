"""Helpers for persisting payload bodies and raw log chunks."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TaskPayload, TaskRawLogChunk


async def create_payload(
    db: AsyncSession,
    *,
    task_id: int,
    payload_kind: str,
    text: str,
    content_type: str = "text/plain",
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
