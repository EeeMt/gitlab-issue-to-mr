"""Test artifact backfill from runtime archive after container exit."""

import json
import os
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("CONFIG_ENCRYPTION_KEY", "unit-test-key")

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool


def _create_archive(archive_dir: str, task_id: int, console_log_content: str) -> str:
    """Create a minimal runtime archive with console.log for testing."""
    archive_name = f"task-{task_id}-runtime-archive.tar.gz"
    archive_path = os.path.join(archive_dir, archive_name)

    console_path = os.path.join(archive_dir, "console.log")
    with open(console_path, "w") as f:
        f.write(console_log_content)

    with tarfile.open(archive_path, "w:gz") as tf:
        tf.add(console_path, arcname="console.log")

    os.unlink(console_path)
    return archive_path


def _create_archive_with_event_jsonl(
    archive_dir: str,
    task_id: int,
    event_lines: list[str],
    *,
    runtime_json: dict | None = None,
) -> str:
    """Create a minimal runtime archive with event.jsonl (and optionally runtime.json) for testing."""
    archive_name = f"task-{task_id}-runtime-archive.tar.gz"
    archive_path = os.path.join(archive_dir, archive_name)

    event_path = os.path.join(archive_dir, "event.jsonl")
    with open(event_path, "w") as f:
        f.write("".join(line + "\n" for line in event_lines))

    with tarfile.open(archive_path, "w:gz") as tf:
        tf.add(event_path, arcname="event.jsonl")
        if runtime_json is not None:
            runtime_path = os.path.join(archive_dir, "runtime.json")
            with open(runtime_path, "w") as rf:
                json.dump(runtime_json, rf)
            tf.add(runtime_path, arcname="runtime.json")
            os.unlink(runtime_path)

    os.unlink(event_path)
    return archive_path


class TestConsoleLogBackfill(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from app.config import get_settings
        get_settings.cache_clear()
        from app.models import Base
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:", poolclass=StaticPool
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.temp_dir = tempfile.mkdtemp()

    async def asyncTearDown(self):
        await self.engine.dispose()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_backfill_adds_missing_chunks_when_cursor_behind(self):
        from app.core.worker_event_projector import WorkerEventProjector
        from app.core.task_log_payloads import append_raw_log_chunk
        from app.models import TaskIngestCursor, TaskRawLogChunk
        from sqlalchemy import select

        task_id = 42
        console_content = (
            "line 1: starting up\n"
            "line 2: claude starting\n"
            "line 3: model output\n"
            "line 4: no changes made\n"
            "line 5: task completed\n"
        )

        archive_path = _create_archive(self.temp_dir, task_id, console_content)

        projector = WorkerEventProjector(sanitize_sensitive_data=lambda x: x)

        async with self.session_factory() as db:
            # Simulate: cursor ingested first 3 lines (45 bytes), missing last 2 lines
            already_ingested = "line 1: starting up\nline 2: claude starting\nline 3: model output\n"
            await append_raw_log_chunk(
                db, task_id=task_id, sequence_no=1, text=already_ingested
            )
            cursor = TaskIngestCursor(
                task_id=task_id,
                stream_name="console_log",
                last_offset=len(already_ingested.encode("utf-8")),
                last_sequence_no=1,
            )
            db.add(cursor)
            await db.commit()

        # Patch archive path
        original_finalize_path = None
        with unittest.mock.patch(
            "app.core.worker_event_projector._ARCHIVE_STORE", self.temp_dir
        ):
            async with self.session_factory() as db:
                await projector.backfill_console_log_from_archive(
                    task_id=task_id, db=db
                )
                await db.commit()

        async with self.session_factory() as db:
            result = await db.execute(
                select(TaskRawLogChunk)
                .where(TaskRawLogChunk.task_id == task_id)
                .order_by(TaskRawLogChunk.sequence_no.asc())
            )
            chunks = result.scalars().all()
            text = "".join(c.content.decode("utf-8") for c in chunks)
            assert len(chunks) == 2
            assert text == console_content

    async def test_backfill_skips_when_cursor_already_caught_up(self):
        from app.core.worker_event_projector import WorkerEventProjector
        from app.core.task_log_payloads import append_raw_log_chunk
        from app.models import TaskIngestCursor, TaskRawLogChunk
        from sqlalchemy import select

        task_id = 43
        console_content = "complete log\n"

        archive_path = _create_archive(self.temp_dir, task_id, console_content)

        projector = WorkerEventProjector(sanitize_sensitive_data=lambda x: x)

        async with self.session_factory() as db:
            await append_raw_log_chunk(
                db, task_id=task_id, sequence_no=1, text=console_content
            )
            cursor = TaskIngestCursor(
                task_id=task_id,
                stream_name="console_log",
                last_offset=len(console_content.encode("utf-8")),
                last_sequence_no=1,
            )
            db.add(cursor)
            await db.commit()

        with unittest.mock.patch(
            "app.core.worker_event_projector._ARCHIVE_STORE", self.temp_dir
        ):
            async with self.session_factory() as db:
                await projector.backfill_console_log_from_archive(
                    task_id=task_id, db=db
                )
                await db.commit()

        async with self.session_factory() as db:
            result = await db.execute(
                select(TaskRawLogChunk)
                .where(TaskRawLogChunk.task_id == task_id)
                .order_by(TaskRawLogChunk.sequence_no.asc())
            )
            chunks = result.scalars().all()
            assert len(chunks) == 1  # no new chunks added

    async def test_backfill_noop_when_archive_missing(self):
        from app.core.worker_event_projector import WorkerEventProjector
        from app.models import TaskIngestCursor, TaskRawLogChunk
        from sqlalchemy import select

        task_id = 44
        projector = WorkerEventProjector(sanitize_sensitive_data=lambda x: x)

        async with self.session_factory() as db:
            cursor = TaskIngestCursor(
                task_id=task_id,
                stream_name="console_log",
                last_offset=0,
                last_sequence_no=0,
            )
            db.add(cursor)
            await db.commit()

        with unittest.mock.patch(
            "app.core.worker_event_projector._ARCHIVE_STORE", self.temp_dir
        ):
            async with self.session_factory() as db:
                await projector.backfill_console_log_from_archive(
                    task_id=task_id, db=db
                )
                await db.commit()

        async with self.session_factory() as db:
            result = await db.execute(
                select(TaskRawLogChunk)
                .where(TaskRawLogChunk.task_id == task_id)
            )
            chunks = result.scalars().all()
            assert len(chunks) == 0  # no archive, no chunks


class TestEventJsonlBackfill(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from app.config import get_settings
        get_settings.cache_clear()
        from app.models import Base
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:", poolclass=StaticPool
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.temp_dir = tempfile.mkdtemp()

    async def asyncTearDown(self):
        await self.engine.dispose()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_backfill_projects_missing_event_records(self):
        from app.core.worker_event_projector import WorkerEventProjector
        from app.models import TaskIngestCursor, TaskLog
        from sqlalchemy import select

        task_id = 50
        event_lines = [
            json.dumps({"type": "system", "subtype": "init", "model": "test-model", "cwd": "/workspace"}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "changes applied"}]}}),
            json.dumps({"type": "result", "subtype": "success", "is_error": False}),
        ]
        full_text = "".join(line + "\n" for line in event_lines)
        first_line = event_lines[0] + "\n"

        _create_archive_with_event_jsonl(self.temp_dir, task_id, event_lines)

        projector = WorkerEventProjector(sanitize_sensitive_data=lambda x: x)

        async with self.session_factory() as db:
            cursor = TaskIngestCursor(
                task_id=task_id,
                stream_name="event_jsonl",
                last_offset=len(first_line.encode("utf-8")),
                last_sequence_no=1,
            )
            db.add(cursor)
            await db.commit()

        with unittest.mock.patch(
            "app.core.worker_event_projector._ARCHIVE_STORE", self.temp_dir
        ):
            async with self.session_factory() as db:
                await projector.backfill_event_jsonl_from_archive(
                    task_id=task_id, db=db
                )
                await db.commit()

        async with self.session_factory() as db:
            result = await db.execute(
                select(TaskLog)
                .where(TaskLog.task_id == task_id, TaskLog.log_type == "assistant_text")
            )
            text_logs = result.scalars().all()
            assert len(text_logs) == 1
            metadata = json.loads(text_logs[0].log_metadata)
            assert metadata["payload_id"] is not None

    async def test_backfill_event_jsonl_noop_when_cursor_caught_up(self):
        from app.core.worker_event_projector import WorkerEventProjector
        from app.models import TaskIngestCursor, TaskLog
        from sqlalchemy import select

        task_id = 51
        event_lines = [
            json.dumps({"type": "system", "subtype": "init", "model": "test-model", "cwd": "/workspace"}),
        ]
        full_text = "".join(line + "\n" for line in event_lines)

        _create_archive_with_event_jsonl(self.temp_dir, task_id, event_lines)

        projector = WorkerEventProjector(sanitize_sensitive_data=lambda x: x)

        async with self.session_factory() as db:
            cursor = TaskIngestCursor(
                task_id=task_id,
                stream_name="event_jsonl",
                last_offset=len(full_text.encode("utf-8")),
                last_sequence_no=1,
            )
            db.add(cursor)
            await db.commit()

        with unittest.mock.patch(
            "app.core.worker_event_projector._ARCHIVE_STORE", self.temp_dir
        ):
            async with self.session_factory() as db:
                await projector.backfill_event_jsonl_from_archive(
                    task_id=task_id, db=db
                )
                await db.commit()

        async with self.session_factory() as db:
            result = await db.execute(
                select(TaskLog).where(
                    TaskLog.task_id == task_id,
                    TaskLog.log_type.isnot(None),
                )
            )
            logs = result.scalars().all()
            assert len(logs) == 0  # cursor was already past end, nothing new

    async def test_backfill_projects_resumed_session_events_past_cursor(self):
        """When system/init was already ingested, resumed-session events still get projected."""
        from app.core.worker_event_projector import WorkerEventProjector
        from app.models import TaskIngestCursor, TaskLog
        from sqlalchemy import select

        task_id = 53
        event_lines = [
            json.dumps({"type": "system", "subtype": "init", "model": "test-model", "cwd": "/workspace"}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "work done"}]}}),
            json.dumps({"type": "result", "subtype": "success", "is_error": False}),
        ]
        first_line = event_lines[0] + "\n"

        _create_archive_with_event_jsonl(
            self.temp_dir,
            task_id,
            event_lines,
            runtime_json={"resume_session": "session-abc"},
        )

        projector = WorkerEventProjector(sanitize_sensitive_data=lambda x: x)

        async with self.session_factory() as db:
            cursor = TaskIngestCursor(
                task_id=task_id,
                stream_name="event_jsonl",
                last_offset=len(first_line.encode("utf-8")),
                last_sequence_no=1,
            )
            db.add(cursor)
            await db.commit()

        with unittest.mock.patch(
            "app.core.worker_event_projector._ARCHIVE_STORE", self.temp_dir
        ):
            async with self.session_factory() as db:
                await projector.backfill_event_jsonl_from_archive(
                    task_id=task_id, db=db
                )
                await db.commit()

        async with self.session_factory() as db:
            result = await db.execute(
                select(TaskLog).where(
                    TaskLog.task_id == task_id,
                    TaskLog.log_type == "assistant_text",
                )
            )
            text_logs = result.scalars().all()
            assert len(text_logs) == 1

    async def test_backfill_event_jsonl_noop_when_archive_missing(self):
        from app.core.worker_event_projector import WorkerEventProjector
        from app.models import TaskIngestCursor, TaskLog
        from sqlalchemy import select

        task_id = 52
        projector = WorkerEventProjector(sanitize_sensitive_data=lambda x: x)

        async with self.session_factory() as db:
            cursor = TaskIngestCursor(
                task_id=task_id,
                stream_name="event_jsonl",
                last_offset=0,
                last_sequence_no=0,
            )
            db.add(cursor)
            await db.commit()

        with unittest.mock.patch(
            "app.core.worker_event_projector._ARCHIVE_STORE", self.temp_dir
        ):
            async with self.session_factory() as db:
                await projector.backfill_event_jsonl_from_archive(
                    task_id=task_id, db=db
                )
                await db.commit()

        async with self.session_factory() as db:
            result = await db.execute(
                select(TaskLog).where(TaskLog.task_id == task_id)
            )
            logs = result.scalars().all()
            assert len(logs) == 0
