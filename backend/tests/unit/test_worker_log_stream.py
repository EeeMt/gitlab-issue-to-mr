from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

from app.core.worker_log_parser import WorkerStdoutMarkerParser
from app.core.worker_log_stream import WorkerLogStreamer
from app.models import TaskLog


class TestWorkerLogStreamer(IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db.add = MagicMock()
        self.db.commit = AsyncMock()
        self.db.flush = AsyncMock()
        self.db.get = AsyncMock(return_value=None)
        self.parser = WorkerStdoutMarkerParser()
        self.streamer = WorkerLogStreamer(
            scrub_sensitive_data=lambda text: text.replace('glpat-secret', '[GITLAB_TOKEN]'),
            stdout_marker_parser=self.parser,
        )

    async def test_flush_log_chunk_skips_blank_content(self):
        await self.streamer.flush_log_chunk(1, ['   \n', '  \n'], 0)
        self.db.add.assert_not_called()

    async def test_flush_log_chunk_no_longer_writes_to_db(self):
        long_text = 'glpat-secret' + ('x' * 9000)
        await self.streamer.flush_log_chunk(1, [long_text], 0)
        self.db.add.assert_not_called()
        self.db.commit.assert_not_awaited()

    async def test_stream_logs_to_db_returns_exit_code_and_logs(self):
        container = MagicMock()
        container.logs.return_value = iter([b'hello\nworld\n'])
        container.wait.return_value = {'StatusCode': 0}

        exit_code, logs, chunks, timed_out = await self.streamer.stream_logs_to_db(
            container=container,
            task_id=1,
            db=self.db,
            timeout=5,
        )

        self.assertEqual(exit_code, 0)
        self.assertIn('hello', logs)
        self.assertIn('world', logs)
        self.assertGreaterEqual(chunks, 1)
        self.assertFalse(timed_out)

    async def test_stream_logs_to_db_parses_markers(self):
        entries = []
        original_add = self.db.add

        def capture_add(obj):
            if isinstance(obj, TaskLog):
                obj.id = len(entries) + 1
                entries.append(obj)
            return original_add(obj)

        self.db.add = capture_add

        async def mock_get(model_class, log_id):
            for entry in entries:
                if entry.id == log_id:
                    return entry
            return None

        self.db.get = mock_get
        container = MagicMock()
        container.logs.return_value = iter([
            b'CODIFY_TOOL_USE_START:{"id":"t1","name":"Read","input":{"file_path":"a.py"}}\n',
            b'CODIFY_TOOL_RESULT:{"id":"t1","output":"ok","error":false}\n',
            b'CODIFY_THINKING:{"text":"hmm"}\n',
        ])
        container.wait.return_value = {'StatusCode': 0}

        await self.streamer.stream_logs_to_db(container=container, task_id=1, db=self.db, timeout=5)

        tool_logs = [entry for entry in entries if entry.log_type == 'tool_call']
        thinking_logs = [entry for entry in entries if entry.log_type == 'thinking']
        self.assertEqual(len(tool_logs), 1)
        self.assertEqual(len(thinking_logs), 1)
        self.assertIn('ok', tool_logs[0].log_metadata)

    async def test_stream_logs_to_db_times_out(self):
        container = MagicMock()

        def slow_log_gen():
            yield b'first line\n'
            import time
            time.sleep(0.1)

        container.logs.return_value = slow_log_gen()
        container.wait.return_value = {'StatusCode': 0}

        exit_code, logs, chunks, timed_out = await self.streamer.stream_logs_to_db(
            container=container,
            task_id=1,
            db=self.db,
            timeout=0,
        )

        self.assertEqual(exit_code, -1)
        self.assertTrue(timed_out)
