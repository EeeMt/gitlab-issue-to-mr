#!/usr/bin/env python3
"""Canonical event projection tests (TaskLog + TaskPayload)."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("CONFIG_ENCRYPTION_KEY", "unit-test-key")

from app.config import get_settings  # noqa: E402
from app.core.harness_attempts import create_task_attempt  # noqa: E402
from app.core.harness_protocol import HarnessProtocolError, build_event  # noqa: E402
from app.core.worker import WorkerExecutor  # noqa: E402
from app.models import Base, Task, TaskIngestCursor, TaskLog, TaskPayload  # noqa: E402


class EventProjectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        get_settings.cache_clear()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        get_settings.cache_clear()

    async def _setup_attempt(self, db):
        task = Task(id=1, issue_id=1, project_id=1, user_prompt="projection")
        db.add(task)
        await db.flush()
        return await create_task_attempt(
            db,
            task=task,
            harness_key="claude",
            adapter_version="1.0.0",
            cli_version="2.1.152",
            attempt_id="task-1-attempt-1",
        )

    def _event(self, seq: int, event_type: str, payload: dict | None = None):
        normalized_payload = payload or {}
        if event_type == "run.completed" and not payload:
            normalized_payload = {"status": "completed", "success": True}
        elif event_type == "run.failed" and not payload:
            normalized_payload = {
                "status": "failed",
                "success": False,
                "failure": {"kind": "engine_error"},
            }
        return build_event(
            attempt_id="task-1-attempt-1",
            seq=seq,
            task_id=1,
            harness_key="claude",
            adapter_version="1.0.0",
            cli_version="2.1.152",
            event_type=event_type,
            payload=normalized_payload,
            event_id=f"event-{seq}",
            occurred_at=f"2026-08-01T00:00:{seq:02d}Z",
        )

    async def _project(self, db, events):
        executor = WorkerExecutor(docker_client=MagicMock(), gitlab_client=MagicMock())
        for event in events:
            await executor._ingest_event_record(task_id=1, record=event, db=db)
        await db.flush()
        return executor

    async def test_projects_model_usage_harness_and_task_results(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            await self._project(
                db,
                [
                    self._event(1, "run.started"),
                    self._event(2, "model.resolved", {"model": "claude-sonnet", "session_id": "s"}),
                    self._event(
                        3,
                        "usage.final",
                        {"usage": {"input_tokens": 15, "output_tokens": 8}},
                    ),
                    self._event(4, "harness.completed", {"session_id": "s", "result": "done"}),
                    self._event(5, "worker.finalization", {"exit_code": 0}),
                    self._event(6, "run.completed", {"status": "completed", "success": True}),
                ],
            )
            logs = list((await db.execute(select(TaskLog).order_by(TaskLog.id))).scalars())
        assert [log.log_type for log in logs] == [
            "system_init",
            "usage_final",
            "harness_result",
            "worker_finalization",
            "run_result",
        ]
        usage = json.loads(logs[1].log_metadata)["usage"]
        assert usage["input_tokens"] == 15
        assert usage["cached_input_tokens"] is None

    async def test_message_deltas_are_bounded_until_completed_payload(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            await self._project(
                db,
                [
                    self._event(1, "run.started"),
                    self._event(2, "message.delta", {"text": "hello "}),
                    self._event(3, "message.delta", {"text": "world"}),
                    self._event(4, "message.completed", {}),
                ],
            )
            logs = list((await db.execute(select(TaskLog))).scalars())
            payloads = list((await db.execute(select(TaskPayload))).scalars())
        assert len(logs) == 1
        assert logs[0].log_type == "assistant_text"
        assert len(payloads) == 1
        assert payloads[0].content == b"hello world"

    async def test_reasoning_summary_is_projected_but_hidden_reasoning_is_rejected(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            await self._project(
                db,
                [
                    self._event(1, "run.started"),
                    self._event(2, "reasoning_summary.completed", {"text": "safe summary"}),
                ],
            )
            log = (await db.execute(select(TaskLog))).scalar_one()
            assert log.log_type == "thinking"
            with self.assertRaises(HarnessProtocolError):
                self._event(3, "message.completed", {"thinking": "secret"})

    async def test_tool_start_and_completion_share_payload_log(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            await self._project(
                db,
                [
                    self._event(1, "run.started"),
                    self._event(
                        2,
                        "tool.started",
                        {"tool_id": "t1", "name": "Bash", "input": {"command": "ls"}},
                    ),
                    self._event(
                        3,
                        "tool.completed",
                        {"tool_id": "t1", "output": "file.txt", "error": False},
                    ),
                ],
            )
            log = (await db.execute(select(TaskLog))).scalar_one()
            payloads = list((await db.execute(select(TaskPayload).order_by(TaskPayload.id))).scalars())
        metadata = json.loads(log.log_metadata)
        assert log.log_type == "tool_call"
        assert metadata["tool_use_id"] == "t1"
        assert metadata["output_payload_id"] == payloads[1].id
        assert payloads[1].content == b"file.txt"

    async def test_context_compaction_and_diagnostic_are_compatible_logs(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            await self._project(
                db,
                [
                    self._event(1, "run.started"),
                    self._event(2, "context.compacted", {"session_id": "s"}),
                    self._event(3, "diagnostic", {"code": "future_event"}),
                ],
            )
            logs = list((await db.execute(select(TaskLog).order_by(TaskLog.id))).scalars())
        assert [log.log_type for log in logs] == ["context_compact", "diagnostic"]

    async def test_exact_replay_does_not_duplicate_projection(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            events = [
                self._event(1, "run.started"),
                self._event(2, "message.completed", {"text": "once"}),
            ]
            executor = await self._project(db, events)
            for event in events:
                await executor._ingest_event_record(task_id=1, record=event, db=db)
            await db.flush()
            logs = list((await db.execute(select(TaskLog))).scalars())
        assert len(logs) == 1

    async def test_chunk_cursor_binds_attempt_and_keeps_partial_line(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            cursor = TaskIngestCursor(task_id=1, stream_name="event_jsonl")
            db.add(cursor)
            await db.flush()
            complete = json.dumps(self._event(1, "run.started"), separators=(",", ":")) + "\n"
            partial = json.dumps(self._event(2, "message.completed", {"text": "later"}))[:-2]
            executor = WorkerExecutor(docker_client=MagicMock(), gitlab_client=MagicMock())
            await executor._ingest_event_records_from_chunk(
                task_id=1,
                chunk=complete + partial,
                cursor=cursor,
                db=db,
            )
        assert cursor.attempt_id == "task-1-attempt-1"
        assert cursor.last_sequence_no == 1
        assert cursor.last_offset == len(complete.encode())

    async def test_raw_claude_record_is_rejected_by_backend(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            executor = WorkerExecutor(docker_client=MagicMock(), gitlab_client=MagicMock())
            with self.assertRaises(HarnessProtocolError):
                await executor._ingest_event_record(
                    task_id=1,
                    record={"type": "system", "subtype": "init", "model": "claude"},
                    db=db,
                )


if __name__ == "__main__":
    unittest.main()
