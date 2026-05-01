#!/usr/bin/env python3
"""Unit tests for worker event-archive ingestion (TaskLog + TaskPayload projection)."""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("CONFIG_ENCRYPTION_KEY", "unit-test-key")

from app.config import get_settings  # noqa: E402
from app.models import Base, TaskLog, TaskPayload, TaskIngestCursor  # noqa: E402
from app.core.worker import WorkerExecutor  # noqa: E402


class EventProjectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-key"
        get_settings.cache_clear()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        get_settings.cache_clear()

    async def _ingest_lines(self, task_id: int, lines: list, db):
        executor = WorkerExecutor(docker_client=MagicMock(), gitlab_client=MagicMock())
        for raw in lines:
            await executor._ingest_event_record(task_id=task_id, record=json.loads(raw), db=db)

    async def test_event_tailer_projects_tool_use_to_tasklog_and_payload(self):
        event_lines = [
            '{"type":"stream_event","event":{"type":"content_block_start","content_block":{"type":"tool_use","id":"tool_1","name":"Write"}}}',
            '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"file_path\\":\\"a.py\\",\\"content\\":\\"print(1)\\"}"}}}',
            '{"type":"stream_event","event":{"type":"content_block_stop"}}',
        ]
        async with self.session_factory() as db:
            await self._ingest_lines(task_id=1, lines=event_lines, db=db)
            await db.flush()
            logs = (await db.execute(select(TaskLog))).scalars().all()
            payloads = (await db.execute(select(TaskPayload))).scalars().all()

        assert len(logs) == 1
        assert len(payloads) == 1
        assert json.loads(logs[0].log_metadata)["input_payload_id"] == payloads[0].id
        assert payloads[0].payload_kind == "tool_input"

    async def test_event_tailer_projects_assistant_text_to_tasklog_and_payload(self):
        event_lines = [
            '{"type":"stream_event","event":{"type":"content_block_start","content_block":{"type":"text"}}}',
            '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"hello from assistant"}}}',
            '{"type":"stream_event","event":{"type":"content_block_stop"}}',
        ]
        async with self.session_factory() as db:
            await self._ingest_lines(task_id=1, lines=event_lines, db=db)
            await db.flush()
            logs = (await db.execute(select(TaskLog).where(TaskLog.log_type == "assistant_text"))).scalars().all()
            payloads = (await db.execute(select(TaskPayload).where(TaskPayload.payload_kind == "assistant_text"))).scalars().all()

        assert len(logs) == 1
        assert len(payloads) == 1
        assert json.loads(logs[0].log_metadata)["payload_id"] == payloads[0].id
        assert payloads[0].char_count == len("hello from assistant")
