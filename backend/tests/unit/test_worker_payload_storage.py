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

    async def _ingest_record(self, task_id: int, record: dict, db):
        executor = WorkerExecutor(docker_client=MagicMock(), gitlab_client=MagicMock())
        executor._timeline_gate_open = True
        await executor._ingest_event_record(task_id=task_id, record=record, db=db)

    async def test_event_tailer_projects_result_event_to_run_result_log(self):
        event_lines = [
            '{"type":"result","subtype":"success","result":"done","session_id":"session-123","usage":{"input_tokens":1500,"output_tokens":800}}',
        ]
        async with self.session_factory() as db:
            await self._ingest_lines(task_id=1, lines=event_lines, db=db)
            await db.flush()
            logs = (await db.execute(select(TaskLog).where(TaskLog.log_type == "run_result"))).scalars().all()

        assert len(logs) == 1
        meta = json.loads(logs[0].log_metadata)
        assert meta == {
            "subtype": "success",
            "session_id": "session-123",
            "usage": {"input_tokens": 1500, "output_tokens": 800},
        }

    async def test_event_tailer_projects_worker_finalization_event(self):
        event_lines = [
            (
                '{"type":"codify_worker","subtype":"finalization",'
                '"commit_sha":"0123456789abcdef0123456789abcdef01234567",'
                '"diff":{"additions":12,"deletions":3,"total":15},'
                '"merge_request_title":"Fix worker result parsing"}'
            ),
        ]
        async with self.session_factory() as db:
            await self._ingest_lines(task_id=1, lines=event_lines, db=db)
            await db.flush()
            logs = (await db.execute(select(TaskLog).where(TaskLog.log_type == "worker_finalization"))).scalars().all()

        assert len(logs) == 1
        meta = json.loads(logs[0].log_metadata)
        assert meta == {
            "commit_sha": "0123456789abcdef0123456789abcdef01234567",
            "diff": {"additions": 12, "deletions": 3, "total": 15},
            "merge_request_title": "Fix worker result parsing",
        }

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
        meta = json.loads(logs[0].log_metadata)
        assert meta["input_payload_id"] == payloads[0].id
        assert meta["input_preview"] == '{"file_path": "a.py", "content": "print(1)"}'
        assert meta["input_truncated"] is False
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
        meta = json.loads(logs[0].log_metadata)
        assert meta["payload_id"] == payloads[0].id
        assert meta["preview"] == "hello from assistant"
        assert meta["truncated"] is False
        assert payloads[0].char_count == len("hello from assistant")

    async def test_event_tailer_correlates_tool_result_to_tool_call(self):
        event_lines = [
            '{"type":"stream_event","event":{"type":"content_block_start","content_block":{"type":"tool_use","id":"tool_1","name":"Bash"}}}',
            '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"command\\":\\"ls\\"}"}}}',
            '{"type":"stream_event","event":{"type":"content_block_stop"}}',
            '{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tool_1","content":[{"type":"text","text":"file1.txt\\nfile2.txt"}],"is_error":false}]}}',
        ]
        async with self.session_factory() as db:
            await self._ingest_lines(task_id=1, lines=event_lines, db=db)
            await db.flush()
            logs = (await db.execute(select(TaskLog).where(TaskLog.log_type == "tool_call"))).scalars().all()
            payloads = (await db.execute(select(TaskPayload))).scalars().all()

        assert len(logs) == 1
        assert len(payloads) == 2
        meta = json.loads(logs[0].log_metadata)
        assert meta["input_payload_id"] is not None
        assert meta["input_preview"] == '{"command": "ls"}'
        assert meta["output_payload_id"] is not None
        assert meta["output_payload_id"] != meta["input_payload_id"]
        assert meta["output_preview"] == "file1.txt\nfile2.txt"
        assert meta["error"] is False
        output_payload = next(p for p in payloads if p.payload_kind == "tool_output")
        assert meta["output_payload_id"] == output_payload.id

    async def test_event_tailer_handles_tool_result_plain_string_content(self):
        event_lines = [
            '{"type":"stream_event","event":{"type":"content_block_start","content_block":{"type":"tool_use","id":"tool_2","name":"Bash"}}}',
            '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"command\\":\\"ls\\"}"}}}',
            '{"type":"stream_event","event":{"type":"content_block_stop"}}',
            '{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tool_2","content":"plain string output","is_error":false}]}}',
        ]
        async with self.session_factory() as db:
            await self._ingest_lines(task_id=1, lines=event_lines, db=db)
            await db.flush()
            logs = (await db.execute(select(TaskLog).where(TaskLog.log_type == "tool_call"))).scalars().all()
            payloads = (await db.execute(select(TaskPayload).where(TaskPayload.payload_kind == "tool_output"))).scalars().all()

        assert len(logs) == 1
        assert len(payloads) == 1
        assert json.loads(logs[0].log_metadata)["output_preview"] == "plain string output"
        assert payloads[0].char_count == len("plain string output")

    async def test_resumed_run_ignores_history_until_current_system_init(self):
        executor = WorkerExecutor(docker_client=MagicMock(), gitlab_client=MagicMock())
        executor._run_is_resumed = True
        executor._timeline_gate_open = False
        event_lines = [
            '{"type":"stream_event","event":{"type":"content_block_start","content_block":{"type":"tool_use","id":"old_tool","name":"Bash"}}}',
            '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"command\\":\\"old\\"}"}}}',
            '{"type":"stream_event","event":{"type":"content_block_stop"}}',
            '{"type":"system","subtype":"init","model":"claude-sonnet","cwd":"/workspace"}',
            '{"type":"stream_event","event":{"type":"content_block_start","content_block":{"type":"tool_use","id":"new_tool","name":"Bash"}}}',
            '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"command\\":\\"new\\"}"}}}',
            '{"type":"stream_event","event":{"type":"content_block_stop"}}',
        ]
        async with self.session_factory() as db:
            for raw in event_lines:
                await executor._ingest_event_record(task_id=1, record=json.loads(raw), db=db)
            await db.flush()
            logs = (await db.execute(select(TaskLog).order_by(TaskLog.id))).scalars().all()
            payloads = (await db.execute(select(TaskPayload).order_by(TaskPayload.id))).scalars().all()

        assert [log.log_type for log in logs] == ['system_init', 'tool_call']
        assert len(payloads) == 1
        assert payloads[0].payload_kind == 'tool_input'
        assert b'new' in payloads[0].content

    async def test_non_resumed_run_keeps_ingesting_from_first_record(self):
        executor = WorkerExecutor(docker_client=MagicMock(), gitlab_client=MagicMock())
        executor._run_is_resumed = False
        executor._timeline_gate_open = True
        event_lines = [
            '{"type":"stream_event","event":{"type":"content_block_start","content_block":{"type":"tool_use","id":"tool_3","name":"Bash"}}}',
            '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"command\\":\\"ls\\"}"}}}',
            '{"type":"stream_event","event":{"type":"content_block_stop"}}',
        ]
        async with self.session_factory() as db:
            for raw in event_lines:
                await executor._ingest_event_record(task_id=1, record=json.loads(raw), db=db)
            await db.flush()
            logs = (await db.execute(select(TaskLog).where(TaskLog.log_type == "tool_call"))).scalars().all()

        assert len(logs) == 1

    async def test_resumed_run_stores_current_system_init(self):
        executor = WorkerExecutor(docker_client=MagicMock(), gitlab_client=MagicMock())
        executor._run_is_resumed = True
        executor._timeline_gate_open = False
        async with self.session_factory() as db:
            await executor._ingest_event_record(
                task_id=1,
                record=json.loads('{"type":"system","subtype":"init","model":"claude-sonnet","cwd":"/workspace"}'),
                db=db,
            )
            await db.flush()
            logs = (await db.execute(select(TaskLog).where(TaskLog.log_type == "system_init"))).scalars().all()

        assert len(logs) == 1
        assert executor._timeline_gate_open is True
        assert json.loads(logs[0].log_metadata)["model"] == "claude-sonnet"

    async def test_resumed_run_initial_chunk_keeps_only_latest_system_init_segment(self):
        executor = WorkerExecutor(docker_client=MagicMock(), gitlab_client=MagicMock())
        executor._run_is_resumed = True
        executor._timeline_gate_open = False
        async with self.session_factory() as db:
            cursor = TaskIngestCursor(task_id=1, stream_name="event_jsonl", last_offset=0, last_sequence_no=0)
            db.add(cursor)
            await db.flush()

            chunk = "\n".join([
                '{"type":"system","subtype":"init","model":"claude-sonnet","cwd":"/workspace"}',
                '{"type":"stream_event","event":{"type":"content_block_start","content_block":{"type":"tool_use","id":"old_tool","name":"Bash"}}}',
                '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"command\\":\\"old\\"}"}}}',
                '{"type":"stream_event","event":{"type":"content_block_stop"}}',
                '{"type":"result","subtype":"success"}',
                '{"type":"system","subtype":"init","model":"claude-sonnet","cwd":"/workspace"}',
                '{"type":"stream_event","event":{"type":"content_block_start","content_block":{"type":"tool_use","id":"new_tool","name":"Bash"}}}',
                '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"command\\":\\"new\\"}"}}}',
                '{"type":"stream_event","event":{"type":"content_block_stop"}}',
                '',
            ])

            await executor._ingest_event_records_from_chunk(task_id=1, chunk=chunk, cursor=cursor, db=db)
            await db.flush()
            logs = (await db.execute(select(TaskLog).order_by(TaskLog.id))).scalars().all()
            payloads = (await db.execute(select(TaskPayload).order_by(TaskPayload.id))).scalars().all()

        assert [log.log_type for log in logs] == ['system_init', 'tool_call']
        assert len(payloads) == 1
        assert payloads[0].payload_kind == 'tool_input'
        assert b'new' in payloads[0].content
        assert b'old' not in payloads[0].content
        assert cursor.last_offset == len(chunk.encode('utf-8'))
        assert cursor.last_sequence_no == 4

    async def test_resumed_run_subsequent_chunk_does_not_retrim(self):
        executor = WorkerExecutor(docker_client=MagicMock(), gitlab_client=MagicMock())
        executor._run_is_resumed = True
        executor._timeline_gate_open = True
        async with self.session_factory() as db:
            cursor = TaskIngestCursor(task_id=1, stream_name="event_jsonl", last_offset=100, last_sequence_no=2)
            db.add(cursor)
            await db.flush()

            chunk = "\n".join([
                '{"type":"stream_event","event":{"type":"content_block_start","content_block":{"type":"tool_use","id":"next_tool","name":"Bash"}}}',
                '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"command\\":\\"next\\"}"}}}',
                '{"type":"stream_event","event":{"type":"content_block_stop"}}',
                '',
            ])

            await executor._ingest_event_records_from_chunk(task_id=1, chunk=chunk, cursor=cursor, db=db)
            await db.flush()
            logs = (await db.execute(select(TaskLog).where(TaskLog.log_type == "tool_call"))).scalars().all()

        assert len(logs) == 1
        assert cursor.last_sequence_no == 5
        assert cursor.last_offset == 100 + len(chunk.encode('utf-8'))
        assert json.loads(logs[0].log_metadata)["tool_use_id"] == "next_tool"

    async def test_assistant_message_projects_tool_use_and_text(self):
        event_lines = [
            '{"type":"system","subtype":"init","model":"MiniMax-M2.5","cwd":"/workspace"}',
            '{"type":"assistant","message":{"content":[{"text":"Let me check the environment.","type":"text"}]}}',
            '{"type":"assistant","message":{"content":[{"id":"call_abc123","input":{"command":"git status"},"name":"Bash","type":"tool_use"}]}}',
            '{"type":"user","message":{"role":"user","content":[{"tool_use_id":"call_abc123","type":"tool_result","content":"On branch main","is_error":false}]}}',
            '{"type":"assistant","message":{"content":[{"text":"Done.","type":"text"}]}}',
        ]
        async with self.session_factory() as db:
            await self._ingest_lines(task_id=1, lines=event_lines, db=db)
            await db.flush()
            logs = (await db.execute(select(TaskLog).order_by(TaskLog.id))).scalars().all()
            payloads = (await db.execute(select(TaskPayload).order_by(TaskPayload.id))).scalars().all()

        log_types = [log.log_type for log in logs]
        assert log_types == ['system_init', 'assistant_text', 'tool_call', 'assistant_text']
        assert len(payloads) == 4
        assistant_meta = json.loads(next(l for l in logs if l.log_type == 'assistant_text').log_metadata)
        assert assistant_meta['preview'] == 'Let me check the environment.'
        tool_log = next(l for l in logs if l.log_type == 'tool_call')
        meta = json.loads(tool_log.log_metadata)
        assert meta["input_payload_id"] is not None
        assert meta["input_preview"] == '{"command": "git status"}'
        assert meta["output_payload_id"] is not None
        assert meta["output_preview"] == 'On branch main'
        assert meta["name"] == "Bash"
        assert meta["error"] is False

    async def test_assistant_message_projects_thinking(self):
        event_lines = [
            '{"type":"system","subtype":"init","model":"claude-sonnet","cwd":"/workspace"}',
            '{"type":"assistant","message":{"content":[{"thinking":"I need to analyze this...","type":"thinking"}]}}',
        ]
        async with self.session_factory() as db:
            await self._ingest_lines(task_id=1, lines=event_lines, db=db)
            await db.flush()
            logs = (await db.execute(select(TaskLog).where(TaskLog.log_type == "thinking"))).scalars().all()
            payloads = (await db.execute(select(TaskPayload).where(TaskPayload.payload_kind == "thinking"))).scalars().all()

        assert len(logs) == 1
        assert len(payloads) == 1
        meta = json.loads(logs[0].log_metadata)
        assert meta['preview'] == 'I need to analyze this...'
        assert payloads[0].char_count == len("I need to analyze this...")

    async def test_assistant_message_splits_thinking_from_response_in_text_block(self):
        mixed_text = "<think>Let me check.</think>\n\n## Result\n\nHere is the info."
        record = {
            "type": "assistant",
            "message": {"content": [{"text": mixed_text, "type": "text"}]},
        }
        async with self.session_factory() as db:
            await self._ingest_record(task_id=1, record=record, db=db)
            await db.flush()
            thinking_logs = (await db.execute(select(TaskLog).where(TaskLog.log_type == "thinking"))).scalars().all()
            text_logs = (await db.execute(select(TaskLog).where(TaskLog.log_type == "assistant_text"))).scalars().all()
            thinking_payloads = (await db.execute(select(TaskPayload).where(TaskPayload.payload_kind == "thinking"))).scalars().all()
            text_payloads = (await db.execute(select(TaskPayload).where(TaskPayload.payload_kind == "assistant_text"))).scalars().all()

        assert len(thinking_logs) == 1
        assert len(text_logs) == 1
        assert len(thinking_payloads) == 1
        assert len(text_payloads) == 1
        assert json.loads(thinking_logs[0].log_metadata)['preview'] == 'Let me check.'
        assert json.loads(text_logs[0].log_metadata)['preview'] == '## Result Here is the info.'
        assert b"## Result" not in thinking_payloads[0].content
        assert b"## Result" in text_payloads[0].content

    async def test_assistant_message_pure_thinking_text_block(self):
        pure_thinking = "<think>Just thinking, no response yet.</think>"
        record = {
            "type": "assistant",
            "message": {"content": [{"text": pure_thinking, "type": "text"}]},
        }
        async with self.session_factory() as db:
            await self._ingest_record(task_id=1, record=record, db=db)
            await db.flush()
            thinking_logs = (await db.execute(select(TaskLog).where(TaskLog.log_type == "thinking"))).scalars().all()
            text_logs = (await db.execute(select(TaskLog).where(TaskLog.log_type == "assistant_text"))).scalars().all()

        assert len(thinking_logs) == 1
        assert json.loads(thinking_logs[0].log_metadata)['preview'] == 'Just thinking, no response yet.'
        assert len(text_logs) == 0

    async def test_assistant_message_multiple_thinking_tags_in_text_block(self):
        multi_text = "<think>First thought.</think>Response one.<think>Second thought.</think>Response two."
        record = {
            "type": "assistant",
            "message": {"content": [{"text": multi_text, "type": "text"}]},
        }
        async with self.session_factory() as db:
            await self._ingest_record(task_id=1, record=record, db=db)
            await db.flush()
            thinking_logs = (await db.execute(select(TaskLog).where(TaskLog.log_type == "thinking"))).scalars().all()
            text_logs = (await db.execute(select(TaskLog).where(TaskLog.log_type == "assistant_text"))).scalars().all()
            thinking_payloads = (await db.execute(select(TaskPayload).where(TaskPayload.payload_kind == "thinking"))).scalars().all()
            text_payloads = (await db.execute(select(TaskPayload).where(TaskPayload.payload_kind == "assistant_text"))).scalars().all()

        assert len(thinking_logs) == 2
        assert len(text_logs) == 2
        assert len(thinking_payloads) == 2
        assert len(text_payloads) == 2
        assert json.loads(thinking_logs[0].log_metadata)['preview'] == 'First thought.'
        assert json.loads(thinking_logs[1].log_metadata)['preview'] == 'Second thought.'
        assert json.loads(text_logs[0].log_metadata)['preview'] == 'Response one.'
        assert json.loads(text_logs[1].log_metadata)['preview'] == 'Response two.'
        assert b"First thought" in thinking_payloads[0].content
        assert b"Second thought" in thinking_payloads[1].content
        assert b"Response one" in text_payloads[0].content
        assert b"Response two" in text_payloads[1].content
