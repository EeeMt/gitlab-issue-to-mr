#!/usr/bin/env python3
"""Focused tests for the task-log SSE generator (task_log_stream.py).

Covers the thinking-placeholder lifecycle over the wire: a started row arrives
in ``batch``, its final status arrives later as an in-place ``update`` (even for
empty content), final updates precede ``done``, completed rows created inside
one poll window are batched once in their final state, rows of other tasks
never enter the tracked set, and a reconnect that rewinds ``since_id``
re-reads a row that completed while disconnected.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import MagicMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("CONFIG_ENCRYPTION_KEY", "unit-test-key")

from app.api.task_log_stream import generate_task_log_events  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.models import Base, Task, TaskLog, TaskStatus  # noqa: E402


def _no_sleep(_: float):
    return asyncio.sleep(0)


def _parse_frames(frames: list[str]):
    events = []
    for frame in frames:
        event_name = None
        data = None
        for line in frame.splitlines():
            if line.startswith("event: "):
                event_name = line[len("event: "):].strip()
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        events.append((event_name, data))
    return events


class TaskLogStreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        get_settings.cache_clear()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        get_settings.cache_clear()

    def _metadata(self, **overrides):
        base = {
            "attempt_id": "task-1-attempt-1",
            "reasoning_id": "pi-thinking-1",
            "status": "in_progress",
            "started_at": "2026-08-01T00:00:10Z",
            "ended_at": None,
            "duration_ms": None,
            "payload_id": None,
            "preview": "",
            "char_count": 0,
            "truncated": False,
        }
        base.update(overrides)
        return json.dumps(base, ensure_ascii=False)

    async def _seed(self, status: TaskStatus | None = None, *, task_id: int = 1):
        async with self.session_factory() as db:
            task = Task(
                id=task_id,
                issue_id=1,
                project_id=1,
                user_prompt="stream",
                status=status or TaskStatus.RUNNING,
            )
            db.add(task)
            await db.commit()

    async def _add_log(self, *, task_id: int = 1, log_type: str, metadata: str | None):
        async with self.session_factory() as db:
            db.add(
                TaskLog(
                    task_id=task_id,
                    log_level="INFO",
                    message="",
                    log_type=log_type,
                    log_metadata=metadata,
                )
            )
            await db.commit()

    async def _set_task_status(self, status: TaskStatus, task_id: int = 1):
        async with self.session_factory() as db:
            task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one()
            task.status = status
            await db.commit()

    async def _finish_thinking(self, *, row_id: int, status: str):
        async with self.session_factory() as db:
            log = (await db.execute(select(TaskLog).where(TaskLog.id == row_id))).scalar_one()
            metadata = json.loads(log.log_metadata)
            metadata.update({"status": status, "ended_at": "2026-08-01T00:00:48Z"})
            log.log_metadata = json.dumps(metadata, ensure_ascii=False)
            await db.commit()

    async def _stream(self, task_id: int = 1, since_id: int = 0):
        frames: list[str] = []
        async for frame in generate_task_log_events(
            task_id,
            since_id,
            session_factory=self.session_factory,
            sleep=_no_sleep,
            logger=MagicMock(),
        ):
            frames.append(frame)
        return frames

    async def test_start_batch_then_completed_update_before_done(self):
        """A started row arrives via batch; its completion is pushed as an
        in-place update and the final update precedes the done event."""
        await self._seed()
        await self._add_log(task_id=1, log_type="thinking", metadata=self._metadata())

        collected: dict[str, list] = {"frames": []}

        async def drive():
            frames_seen = 0
            async for frame in generate_task_log_events(
                1,
                0,
                session_factory=self.session_factory,
                sleep=_no_sleep,
                logger=MagicMock(),
            ):
                frames_seen += 1
                if frames_seen == 1:
                    # First cycle delivered the batch: finalize the row and
                    # terminate the task before the generator's next poll.
                    await self._finish_thinking(row_id=1, status="completed")
                    await self._set_task_status(TaskStatus.COMPLETED)
                collected["frames"].append(frame)

        await drive()
        events = _parse_frames(collected["frames"])
        names = [name for name, _ in events]
        assert names == ["batch", "update", "done"], names
        batch_data = events[0][1]
        assert batch_data[0]["id"] == 1
        assert batch_data[0]["metadata"]["status"] == "in_progress"
        assert batch_data[0]["log_type"] == "thinking"
        update_data = events[1][1]
        assert update_data["id"] == 1
        assert update_data["metadata"]["status"] == "completed"
        assert update_data["metadata"]["duration_ms"] is None
        assert update_data["metadata"]["payload_id"] is None
        # The completed snapshot must be the one the page merges over the row
        # it already holds from the batch.
        assert events[1][1]["metadata"]["reasoning_id"] == "pi-thinking-1"

    async def test_empty_content_completion_still_sends_update(self):
        """Completion without content still closes the placeholder via update
        (the end is judged by status, never by payload_id)."""
        await self._seed()
        await self._add_log(task_id=1, log_type="thinking", metadata=self._metadata())

        collected: dict[str, list] = {"frames": []}

        async def drive():
            frames_seen = 0
            async for frame in generate_task_log_events(
                1,
                0,
                session_factory=self.session_factory,
                sleep=_no_sleep,
                logger=MagicMock(),
            ):
                frames_seen += 1
                if frames_seen == 1:
                    await self._finish_thinking(row_id=1, status="completed")
                    await self._set_task_status(TaskStatus.COMPLETED)
                collected["frames"].append(frame)

        await drive()
        events = _parse_frames(collected["frames"])
        names = [name for name, _ in events]
        assert names == ["batch", "update", "done"], names
        update_metadata = events[1][1]["metadata"]
        assert update_metadata["status"] == "completed"
        assert update_metadata["payload_id"] is None

    async def test_fast_completion_within_one_window_batches_final_row_once(self):
        """A row that starts and completes inside one poll window is batched
        once in its final state — no update event, no placeholder flicker."""
        await self._seed()
        await self._add_log(
            task_id=1,
            log_type="thinking",
            metadata=self._metadata(status="completed", ended_at="2026-08-01T00:00:48Z"),
        )
        await self._set_task_status(TaskStatus.COMPLETED)
        frames = await self._stream()
        events = _parse_frames(frames)
        names = [name for name, _ in events]
        assert names == ["batch", "done"], names
        assert len(events[0][1]) == 1
        assert events[0][1][0]["metadata"]["status"] == "completed"

    async def test_interrupted_row_is_pushed_as_update(self):
        await self._seed()
        await self._add_log(task_id=1, log_type="thinking", metadata=self._metadata())

        collected: dict[str, list] = {"frames": []}

        async def drive():
            frames_seen = 0
            async for frame in generate_task_log_events(
                1,
                0,
                session_factory=self.session_factory,
                sleep=_no_sleep,
                logger=MagicMock(),
            ):
                frames_seen += 1
                if frames_seen == 1:
                    await self._finish_thinking(row_id=1, status="interrupted")
                    await self._set_task_status(TaskStatus.CANCELLED)
                collected["frames"].append(frame)

        await drive()
        events = _parse_frames(collected["frames"])
        names = [name for name, _ in events]
        assert names == ["batch", "update", "done"], names
        assert events[1][1]["metadata"]["status"] == "interrupted"
        assert events[1][1]["metadata"]["duration_ms"] is None

    async def test_other_task_rows_never_enter_tracking(self):
        """In-progress rows of another task neither batch into this stream nor
        produce update events for it."""
        await self._seed()
        await self._seed(task_id=2)
        await self._add_log(task_id=1, log_type="thinking", metadata=self._metadata())
        await self._add_log(task_id=2, log_type="thinking", metadata=self._metadata())

        async def drive():
            frames_seen = 0
            async for frame in generate_task_log_events(
                1,
                0,
                session_factory=self.session_factory,
                sleep=_no_sleep,
                logger=MagicMock(),
            ):
                frames_seen += 1
                if frames_seen == 1:
                    # The other task's row completes; task 1's row stays open.
                    await self._finish_thinking(row_id=2, status="completed")
                    await self._set_task_status(TaskStatus.RUNNING, task_id=2)
                    # Give the generator another cycle, then close task 1 with
                    # its row still in_progress so the stream ends.
                    await self._set_task_status(TaskStatus.CANCELLED, task_id=1)
                collected["frames"].append(frame)

        collected: dict[str, list] = {"frames": []}
        await drive()
        events = _parse_frames(collected["frames"])
        names = [name for name, _ in events]
        assert names == ["batch", "done"], names
        assert [row["id"] for row in events[0][1]] == [1]

    async def test_reconnect_rewind_rereads_row_completed_while_disconnected(self):
        """A since_id rewound below an in-progress row re-reads its current
        (already completed) snapshot in the first batch."""
        await self._seed()
        await self._add_log(
            task_id=1,
            log_type="thinking",
            metadata=self._metadata(status="completed", ended_at="2026-08-01T00:00:48Z"),
        )
        await self._add_log(task_id=1, log_type="assistant_text", metadata=None)
        await self._set_task_status(TaskStatus.COMPLETED)
        # Client rewinds since_id = min(pending) - 1 = 0 because it still
        # holds an in_progress snapshot of row 1.
        frames = await self._stream(since_id=0)
        events = _parse_frames(frames)
        names = [name for name, _ in events]
        assert names == ["batch", "done"], names
        assert [row["id"] for row in events[0][1]] == [1, 2]
        assert events[0][1][0]["metadata"]["status"] == "completed"

    async def test_no_new_logs_and_terminal_ends_stream_with_done_only(self):
        await self._seed()
        await self._set_task_status(TaskStatus.COMPLETED)
        frames = await self._stream()
        events = _parse_frames(frames)
        assert [(name, data) for name, data in events if name == "batch"] == []
        assert events[-1] == ("done", {})


if __name__ == "__main__":
    unittest.main()
