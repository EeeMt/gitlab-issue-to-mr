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

    def _event(
        self,
        seq: int,
        event_type: str,
        payload: dict | None = None,
        *,
        occurred_at: str | None = None,
        attempt_id: str = "task-1-attempt-1",
    ):
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
            attempt_id=attempt_id,
            seq=seq,
            task_id=1,
            harness_key="claude",
            adapter_version="1.0.0",
            cli_version="2.1.152",
            event_type=event_type,
            payload=normalized_payload,
            event_id=f"{attempt_id}-event-{seq}",
            occurred_at=occurred_at or f"2026-08-01T00:00:{seq:02d}Z",
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
                    self._event(
                        2,
                        "context.compacted",
                        {
                            "session_id": "s",
                            "reason": "threshold",
                            "auto": True,
                            "overflow": True,
                            "tail_start_id": "msg-7",
                            "summary": "safe summary",
                        },
                    ),
                    self._event(3, "diagnostic", {"code": "future_event"}),
                ],
            )
            logs = list((await db.execute(select(TaskLog).order_by(TaskLog.id))).scalars())
        assert [log.log_type for log in logs] == ["context_compact", "diagnostic"]
        metadata = json.loads(logs[0].log_metadata)
        assert metadata["auto"] is True
        assert metadata["overflow"] is True
        assert metadata["tail_start_id"] == "msg-7"
        assert metadata["summary"] == "safe summary"

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

    async def test_tail_survives_torn_final_line_with_split_multibyte_char(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            cursor = TaskIngestCursor(task_id=1, stream_name="event_jsonl")
            db.add(cursor)
            await db.flush()
            complete = (json.dumps(self._event(1, "run.started"), separators=(",", ":")) + "\n").encode()
            # "你" is 3 UTF-8 bytes; drop the final byte so the tail ends with a
            # split multi-byte character (a crash mid-write).
            torn = ('{"type":"message.delta","payload":{"text":"' + "你").encode()[:-1]
            container = MagicMock()
            container.exec_run.return_value = MagicMock(exit_code=0, output=complete + torn)
            executor = WorkerExecutor(docker_client=MagicMock(), gitlab_client=MagicMock())
            await executor._tail_event_jsonl(task_id=1, container=container, db=db)
        assert cursor.attempt_id == "task-1-attempt-1"
        assert cursor.last_sequence_no == 1
        assert cursor.last_offset == len(complete)

    # ── Thinking placeholder lifecycle (2026-09-04 plan, section B) ──────────

    def _started(
        self,
        seq: int,
        reasoning_id: str,
        occurred_at: str,
        *,
        attempt_id: str = "task-1-attempt-1",
    ):
        return self._event(
            seq,
            "reasoning_summary.started",
            {"reasoning_id": reasoning_id},
            occurred_at=occurred_at,
            attempt_id=attempt_id,
        )

    def _completed(
        self,
        seq: int,
        reasoning_id: str,
        text: str | None,
        occurred_at: str,
        *,
        attempt_id: str = "task-1-attempt-1",
    ):
        payload: dict = {"reasoning_id": reasoning_id, "client": "pi"}
        if text is not None:
            payload["text"] = text
        return self._event(
            seq,
            "reasoning_summary.completed",
            payload,
            occurred_at=occurred_at,
            attempt_id=attempt_id,
        )

    def _interrupted(
        self,
        seq: int,
        reasoning_id: str,
        occurred_at: str,
        *,
        reason: str | None = None,
        attempt_id: str = "task-1-attempt-1",
    ):
        payload: dict = {"reasoning_id": reasoning_id}
        if reason is not None:
            payload["reason"] = reason
        return self._event(
            seq,
            "reasoning_summary.interrupted",
            payload,
            occurred_at=occurred_at,
            attempt_id=attempt_id,
        )

    async def _thinking_rows(self, db):
        rows = {}
        for log in (await db.execute(select(TaskLog))).scalars():
            if log.log_type != "thinking":
                continue
            rows[json.loads(log.log_metadata)["reasoning_id"]] = log
        return rows

    async def test_thinking_start_creates_placeholder_without_payload(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            await self._project(
                db,
                [
                    self._event(1, "run.started"),
                    self._started(2, "pi-thinking-42", "2026-08-01T00:00:10Z"),
                ],
            )
            logs = list((await db.execute(select(TaskLog))).scalars())
            payloads = list((await db.execute(select(TaskPayload))).scalars())
        assert len(logs) == 1
        assert logs[0].log_type == "thinking"
        assert len(payloads) == 0
        assert json.loads(logs[0].log_metadata) == {
            "attempt_id": "task-1-attempt-1",
            "reasoning_id": "pi-thinking-42",
            "status": "in_progress",
            "started_at": "2026-08-01T00:00:10Z",
            "ended_at": None,
            "duration_ms": None,
            "payload_id": None,
            "preview": "",
            "char_count": 0,
            "truncated": False,
        }

    async def test_thinking_completion_finalizes_same_row_with_payload_and_duration(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            await self._project(
                db,
                [
                    self._event(1, "run.started"),
                    self._started(2, "pi-thinking-42", "2026-08-01T00:00:10Z"),
                    self._completed(3, "pi-thinking-42", "analysis text", "2026-08-01T00:00:48Z"),
                ],
            )
            logs = list((await db.execute(select(TaskLog))).scalars())
            payloads = list((await db.execute(select(TaskPayload))).scalars())
        assert len(logs) == 1
        assert len(payloads) == 1
        metadata = json.loads(logs[0].log_metadata)
        assert logs[0].log_type == "thinking"
        assert metadata["status"] == "completed"
        assert metadata["reasoning_id"] == "pi-thinking-42"
        assert metadata["started_at"] == "2026-08-01T00:00:10Z"
        assert metadata["ended_at"] == "2026-08-01T00:00:48Z"
        assert metadata["duration_ms"] == 38000
        assert metadata["payload_id"] == payloads[0].id
        assert metadata["preview"] == "analysis text"
        assert metadata["char_count"] == len("analysis text")
        assert metadata["truncated"] is False
        assert payloads[0].payload_kind == "thinking"
        assert payloads[0].content == b"analysis text"

    async def test_empty_thinking_completion_closes_placeholder_without_payload(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            await self._project(
                db,
                [
                    self._event(1, "run.started"),
                    self._started(2, "pi-thinking-42", "2026-08-01T00:00:10Z"),
                    self._completed(3, "pi-thinking-42", None, "2026-08-01T00:00:48Z"),
                ],
            )
            logs = list((await db.execute(select(TaskLog))).scalars())
            payloads = list((await db.execute(select(TaskPayload))).scalars())
        assert len(logs) == 1
        assert len(payloads) == 0
        metadata = json.loads(logs[0].log_metadata)
        assert metadata["status"] == "completed"
        assert metadata["duration_ms"] == 38000
        assert metadata["payload_id"] is None
        assert metadata["char_count"] == 0

    async def test_standalone_completed_without_start_stays_static_row(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            await self._project(
                db,
                [
                    self._event(1, "run.started"),
                    self._event(
                        2,
                        "reasoning_summary.completed",
                        {"text": "legacy static", "client": "pi"},
                    ),
                ],
            )
            logs = list((await db.execute(select(TaskLog))).scalars())
            payloads = list((await db.execute(select(TaskPayload))).scalars())
        assert len(logs) == 1
        assert logs[0].log_type == "thinking"
        assert len(payloads) == 1
        metadata = json.loads(logs[0].log_metadata)
        # No lifecycle fields: the frontend keeps its static display and never
        # guesses a start time or duration.
        assert "status" not in metadata
        assert "duration_ms" not in metadata
        assert metadata["payload_id"] == payloads[0].id

    async def test_harness_terminal_still_interrupts_leftover_open_rows(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            await self._project(
                db,
                [
                    self._event(1, "run.started"),
                    self._started(2, "pi-thinking-1", "2026-08-01T00:00:00Z"),
                    self._completed(3, "pi-thinking-1", "done early", "2026-08-01T00:00:20Z"),
                    self._started(4, "pi-thinking-2", "2026-08-01T00:00:30Z"),
                    self._event(
                        5,
                        "harness.failed",
                        {"failure": {"kind": "cancelled", "message": "user cancel"}},
                        occurred_at="2026-08-01T00:00:50Z",
                    ),
                ],
            )
            rows = await self._thinking_rows(db)
        first = json.loads(rows["pi-thinking-1"].log_metadata)
        assert first["status"] == "completed"
        assert first["duration_ms"] == 20000
        second = json.loads(rows["pi-thinking-2"].log_metadata)
        assert second["status"] == "interrupted"
        assert second["ended_at"] == "2026-08-01T00:00:50Z"
        assert second["duration_ms"] is None
        assert second["payload_id"] is None

    async def test_new_start_never_interrupts_another_open_block(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            await self._project(
                db,
                [
                    self._event(1, "run.started"),
                    self._started(2, "pi-thinking-1", "2026-08-01T00:00:00Z"),
                    self._started(3, "pi-thinking-2", "2026-08-01T00:00:30Z"),
                    self._completed(4, "pi-thinking-2", "second block", "2026-08-01T00:00:40Z"),
                ],
            )
            rows = await self._thinking_rows(db)
        assert len(rows) == 2
        first = json.loads(rows["pi-thinking-1"].log_metadata)
        second = json.loads(rows["pi-thinking-2"].log_metadata)
        # Starting block 2 never infers the end of block 1 (plan §5.1): the
        # orphan stays open until its own interrupted/completed event.
        assert first["status"] == "in_progress"
        assert first["ended_at"] is None
        assert second["status"] == "completed"
        assert second["duration_ms"] == 10000

    async def test_interrupted_event_closes_only_the_addressed_block(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            await self._project(
                db,
                [
                    self._event(1, "run.started"),
                    self._started(2, "pi-thinking-1", "2026-08-01T00:00:00Z"),
                    self._started(3, "pi-thinking-2", "2026-08-01T00:00:30Z"),
                    self._interrupted(
                        4,
                        "pi-thinking-1",
                        "2026-08-01T00:00:31Z",
                        reason="next_block_started_without_end",
                    ),
                    self._completed(5, "pi-thinking-2", "second block", "2026-08-01T00:00:40Z"),
                ],
            )
            rows = await self._thinking_rows(db)
        assert len(rows) == 2
        first = json.loads(rows["pi-thinking-1"].log_metadata)
        second = json.loads(rows["pi-thinking-2"].log_metadata)
        assert first["status"] == "interrupted"
        assert first["ended_at"] == "2026-08-01T00:00:31Z"
        assert first["duration_ms"] is None
        assert second["status"] == "completed"
        assert second["duration_ms"] == 10000

    async def test_interleave_blocks_pair_by_id(self):
        """A.start -> B.start -> A.complete -> B.complete keeps both rows
        distinct and finalizes each in place."""
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            await self._project(
                db,
                [
                    self._event(1, "run.started"),
                    self._started(2, "reasoning-A", "2026-08-01T00:00:00Z"),
                    self._started(3, "reasoning-B", "2026-08-01T00:00:10Z"),
                    self._completed(4, "reasoning-A", "A done", "2026-08-01T00:00:20Z"),
                    self._completed(5, "reasoning-B", "B done", "2026-08-01T00:00:30Z"),
                ],
            )
            rows = await self._thinking_rows(db)
            payloads = list(
                (await db.execute(select(TaskPayload).order_by(TaskPayload.id))).scalars()
            )
        assert len(rows) == 2
        assert [p.content for p in payloads] == [b"A done", b"B done"]
        a = json.loads(rows["reasoning-A"].log_metadata)
        b = json.loads(rows["reasoning-B"].log_metadata)
        assert a["status"] == "completed" and a["duration_ms"] == 20000
        assert b["status"] == "completed" and b["duration_ms"] == 20000

    async def test_repeated_start_and_completed_are_idempotent(self):
        """A re-delivered start keeps the original started_at; a repeated
        completed neither creates a second payload nor resets times."""
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            events = [
                self._event(1, "run.started"),
                self._started(2, "pi-thinking-42", "2026-08-01T00:00:10Z"),
                self._started(3, "pi-thinking-42", "2026-08-01T00:00:20Z"),
                self._completed(4, "pi-thinking-42", "final", "2026-08-01T00:00:48Z"),
                self._completed(5, "pi-thinking-42", "final", "2026-08-01T00:00:48Z"),
            ]
            executor = await self._project(db, events)
            for event in events:
                await executor._ingest_event_record(task_id=1, record=event, db=db)
            await db.flush()
            logs = list((await db.execute(select(TaskLog))).scalars())
            payloads = list((await db.execute(select(TaskPayload))).scalars())
        assert len(logs) == 1
        assert len(payloads) == 1
        metadata = json.loads(logs[0].log_metadata)
        assert metadata["started_at"] == "2026-08-01T00:00:10Z"
        assert metadata["ended_at"] == "2026-08-01T00:00:48Z"
        assert metadata["duration_ms"] == 38000
        assert metadata["payload_id"] == payloads[0].id

    async def test_interrupted_unknown_or_finalized_rows_are_ignored(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            await self._project(
                db,
                [
                    self._event(1, "run.started"),
                    self._started(2, "pi-thinking-1", "2026-08-01T00:00:00Z"),
                    self._completed(3, "pi-thinking-1", "done early", "2026-08-01T00:00:10Z"),
                    self._interrupted(4, "pi-thinking-1", "2026-08-01T00:00:20Z"),
                    self._interrupted(5, "never-started", "2026-08-01T00:00:21Z"),
                ],
            )
            logs = list((await db.execute(select(TaskLog))).scalars())
        assert len(logs) == 1
        metadata = json.loads(logs[0].log_metadata)
        assert metadata["status"] == "completed"
        assert metadata["ended_at"] == "2026-08-01T00:00:10Z"

    async def test_orphan_empty_completion_records_diagnostic_only(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            await self._project(
                db,
                [
                    self._event(1, "run.started"),
                    self._event(
                        2,
                        "reasoning_summary.completed",
                        {"reasoning_id": "orphan-empty", "client": "pi"},
                    ),
                ],
            )
            logs = list((await db.execute(select(TaskLog))).scalars())
            payloads = list((await db.execute(select(TaskPayload))).scalars())
        assert len(logs) == 1
        assert logs[0].log_type == "diagnostic"
        assert len(payloads) == 0

    async def test_multiple_blocks_pair_distinct_ids_without_content_crossing(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            await self._project(
                db,
                [
                    self._event(1, "run.started"),
                    self._started(2, "pi-thinking-1", "2026-08-01T00:00:00Z"),
                    self._completed(3, "pi-thinking-1", "first block", "2026-08-01T00:00:10Z"),
                    self._started(4, "pi-thinking-2", "2026-08-01T00:00:20Z"),
                    self._completed(5, "pi-thinking-2", "second block", "2026-08-01T00:00:30Z"),
                ],
            )
            logs = list(
                (await db.execute(select(TaskLog).order_by(TaskLog.id))).scalars()
            )
            payloads = list(
                (await db.execute(select(TaskPayload).order_by(TaskPayload.id))).scalars()
            )
        assert len(logs) == 2
        assert len(payloads) == 2
        assert [p.content for p in payloads] == [b"first block", b"second block"]
        assert [json.loads(log.log_metadata)["reasoning_id"] for log in logs] == [
            "pi-thinking-1",
            "pi-thinking-2",
        ]
        assert [json.loads(log.log_metadata)["status"] for log in logs] == [
            "completed",
            "completed",
        ]

    async def test_projector_rebuild_still_finalizes_the_original_row(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            executor = await self._project(
                db,
                [
                    self._event(1, "run.started"),
                    self._started(2, "pi-thinking-42", "2026-08-01T00:00:10Z"),
                ],
            )
            assert executor is not None
            await db.commit()
            created_id = (
                await db.execute(select(TaskLog.id).where(TaskLog.log_type == "thinking"))
            ).scalar_one()
            # Fresh projector instance: only persisted rows can pair the block.
            rebuilt = WorkerExecutor(docker_client=MagicMock(), gitlab_client=MagicMock())
            await rebuilt._ingest_event_record(
                task_id=1,
                record=self._completed(
                    3, "pi-thinking-42", "recovered", "2026-08-01T00:00:48Z"
                ),
                db=db,
            )
            logs = list((await db.execute(select(TaskLog))).scalars())
            payloads = list((await db.execute(select(TaskPayload))).scalars())
        assert len(logs) == 1
        assert logs[0].id == created_id
        assert len(payloads) == 1
        metadata = json.loads(logs[0].log_metadata)
        assert metadata["status"] == "completed"
        assert metadata["duration_ms"] == 38000
        assert metadata["payload_id"] == payloads[0].id

    async def test_thinking_events_replay_does_not_duplicate_rows_or_payloads(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            events = [
                self._event(1, "run.started"),
                self._started(2, "pi-thinking-42", "2026-08-01T00:00:10Z"),
                self._completed(3, "pi-thinking-42", "once", "2026-08-01T00:00:48Z"),
            ]
            executor = await self._project(db, events)
            for event in events:
                await executor._ingest_event_record(task_id=1, record=event, db=db)
            await db.flush()
            logs = list((await db.execute(select(TaskLog))).scalars())
            payloads = list((await db.execute(select(TaskPayload))).scalars())
        assert len(logs) == 1
        assert len(payloads) == 1
        assert json.loads(logs[0].log_metadata)["status"] == "completed"

    async def test_out_of_order_timestamps_leave_duration_blank(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            await self._project(
                db,
                [
                    self._event(1, "run.started"),
                    self._started(2, "pi-thinking-42", "2026-08-01T00:00:48Z"),
                    self._completed(3, "pi-thinking-42", "late", "2026-08-01T00:00:10Z"),
                ],
            )
            log = (await db.execute(select(TaskLog))).scalar_one()
        metadata = json.loads(log.log_metadata)
        assert metadata["status"] == "completed"
        assert metadata["duration_ms"] is None

    async def test_placeholder_receipt_rollback_leaves_nothing_and_retry_recovers(self):
        async with self.session_factory() as db:
            await self._setup_attempt(db)
            started = self._started(2, "pi-thinking-42", "2026-08-01T00:00:10Z")
            executor = WorkerExecutor(docker_client=MagicMock(), gitlab_client=MagicMock())
            await executor._ingest_event_record(
                task_id=1, record=self._event(1, "run.started"), db=db
            )
            nested = await db.begin_nested()
            await executor._ingest_event_record(task_id=1, record=started, db=db)
            await nested.rollback()
            before = list((await db.execute(select(TaskLog))).scalars())
            assert len(before) == 0
            await executor._ingest_event_record(task_id=1, record=started, db=db)
            await db.flush()
            after = list((await db.execute(select(TaskLog))).scalars())
        assert len(after) == 1
        assert json.loads(after[0].log_metadata)["status"] == "in_progress"

if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
