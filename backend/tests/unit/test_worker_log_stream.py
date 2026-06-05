from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock

from app.core.worker_log_stream import WorkerLogStreamer


class TestWorkerLogStreamer(IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = MagicMock()
        self.streamer = WorkerLogStreamer()

    async def test_flush_log_chunk_is_noop(self):
        await self.streamer.flush_log_chunk(1, ['   \n', '  \n'], 0)

    async def test_flush_log_chunk_handles_long_text(self):
        long_text = 'glpat-secret' + ('x' * 9000)
        await self.streamer.flush_log_chunk(1, [long_text], 0)

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
