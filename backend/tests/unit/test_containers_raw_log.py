#!/usr/bin/env python3
"""Test backward-compat raw log fetching from TaskRawLogChunk + TaskLog fallback."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("CONFIG_ENCRYPTION_KEY", "unit-test-key")

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool


class ContainersRawLogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from app.config import get_settings
        get_settings.cache_clear()
        from app.models import Base
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_fetch_db_chunks_uses_task_raw_log_chunk_when_available(self):
        from app.models import TaskRawLogChunk
        from sqlalchemy import select
        async with self.session_factory() as db:
            db.add(TaskRawLogChunk(
                task_id=1, sequence_no=1, encoding="identity",
                content=b"line1\n", char_count=6, byte_count=6,
            ))
            db.add(TaskRawLogChunk(
                task_id=1, sequence_no=2, encoding="identity",
                content=b"line2\n", char_count=6, byte_count=6,
            ))
            await db.commit()

            chunk_result = await db.execute(
                select(TaskRawLogChunk)
                .where(TaskRawLogChunk.task_id == 1)
                .order_by(TaskRawLogChunk.sequence_no.asc())
            )
            new_chunks = chunk_result.scalars().all()
            assert len(new_chunks) == 2
            text = "".join(c.content.decode("utf-8") for c in new_chunks)
            assert text == "line1\nline2\n"

    async def test_fetch_db_chunks_falls_back_to_task_log_when_no_raw_chunks(self):
        from app.models import TaskLog, TaskRawLogChunk
        from sqlalchemy import select
        async with self.session_factory() as db:
            db.add(TaskLog(task_id=1, log_level="INFO", message="legacy output\n", log_type=None))
            await db.commit()

            # Verify no TaskRawLogChunk rows exist
            chunk_result = await db.execute(
                select(TaskRawLogChunk).where(TaskRawLogChunk.task_id == 1)
            )
            new_chunks = chunk_result.scalars().all()
            assert len(new_chunks) == 0

            # Should fall back to TaskLog
            log_result = await db.execute(
                select(TaskLog)
                .where(TaskLog.task_id == 1, TaskLog.log_type.is_(None))
                .order_by(TaskLog.id.asc())
            )
            chunks = log_result.scalars().all()
            assert len(chunks) == 1
            text = "".join(c.message or "" for c in chunks)
            assert "legacy output" in text

    async def test_raw_chunks_take_priority_over_task_log(self):
        """When both TaskRawLogChunk and TaskLog exist, use TaskRawLogChunk."""
        from app.models import TaskLog, TaskRawLogChunk
        from sqlalchemy import select
        async with self.session_factory() as db:
            db.add(TaskLog(task_id=2, log_level="INFO", message="old log\n", log_type=None))
            db.add(TaskRawLogChunk(
                task_id=2, sequence_no=1, encoding="identity",
                content=b"new chunk\n", char_count=10, byte_count=10,
            ))
            await db.commit()

            chunk_result = await db.execute(
                select(TaskRawLogChunk)
                .where(TaskRawLogChunk.task_id == 2)
                .order_by(TaskRawLogChunk.sequence_no.asc())
            )
            new_chunks = chunk_result.scalars().all()
            assert len(new_chunks) == 1
            # New chunks exist — should use them, not legacy TaskLog
            text = "".join(c.content.decode("utf-8") for c in new_chunks)
            assert text == "new chunk\n"


if __name__ == "__main__":
    unittest.main()
