import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

from app.core.worker_log_parser import WorkerStdoutMarkerParser
from app.models import TaskLog


class TestWorkerStdoutMarkerParser(IsolatedAsyncioTestCase):
    def setUp(self):
        self.parser = WorkerStdoutMarkerParser()
        self.db = MagicMock()
        self.db.add = MagicMock()
        self.db.flush = AsyncMock()
        self.db.commit = AsyncMock()
        self.db.get = AsyncMock(return_value=None)

    async def test_tool_use_start_creates_tool_call_log(self):
        entries = []
        original_add = self.db.add

        def capture_add(obj):
            if isinstance(obj, TaskLog):
                obj.id = len(entries) + 1
                entries.append(obj)
            return original_add(obj)

        self.db.add = capture_add

        handled = await self.parser.handle_line(
            stripped='CODIFY_TOOL_USE_START:{"id":"tu1","name":"Read","input":{"file_path":"a.py"}}',
            task_id=1,
            db=self.db,
        )

        self.assertTrue(handled)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].log_type, 'tool_call')
        metadata = json.loads(entries[0].log_metadata)
        self.assertEqual(metadata['name'], 'Read')
        self.assertEqual(metadata['input'], {'file_path': 'a.py'})
        self.assertIsNone(metadata['output'])
        self.assertFalse(metadata['error'])

    async def test_tool_result_updates_existing_tool_call_log(self):
        log_entry = TaskLog(
            task_id=1,
            log_level='INFO',
            message='',
            log_type='tool_call',
            log_metadata=json.dumps({'name': 'Read', 'input': {'file_path': 'a.py'}, 'output': None, 'error': False}),
        )
        log_entry.id = 55
        self.parser._pending_tool_uses['tu1'] = 55
        self.db.get = AsyncMock(return_value=log_entry)

        handled = await self.parser.handle_line(
            stripped='CODIFY_TOOL_RESULT:{"id":"tu1","output":"done","error":true}',
            task_id=1,
            db=self.db,
        )

        self.assertTrue(handled)
        metadata = json.loads(log_entry.log_metadata)
        self.assertEqual(metadata['output'], 'done')
        self.assertTrue(metadata['error'])

    async def test_text_markers_create_logs(self):
        for marker, log_type in [
            ('CODIFY_THINKING:{"text":"hmm"}', 'thinking'),
            ('CODIFY_ASSISTANT_TEXT:{"text":"hello"}', 'assistant_text'),
            ('CODIFY_SYSTEM_INIT:{"model":"claude","cwd":"/workspace"}', 'system_init'),
        ]:
            self.db.add.reset_mock()
            handled = await self.parser.handle_line(stripped=marker, task_id=1, db=self.db)
            self.assertTrue(handled)
            added = self.db.add.call_args[0][0]
            self.assertEqual(added.log_type, log_type)
            self.assertEqual(added.message, '')

    async def test_invalid_marker_json_does_not_raise(self):
        for marker in [
            'CODIFY_TOOL_USE_START:{bad}',
            'CODIFY_TOOL_RESULT:{bad}',
            'CODIFY_THINKING:not-json',
            'CODIFY_ASSISTANT_TEXT:not-json',
            'CODIFY_SYSTEM_INIT:not-json',
        ]:
            handled = await self.parser.handle_line(stripped=marker, task_id=1, db=self.db)
            self.assertTrue(handled)

    async def test_non_marker_line_returns_false(self):
        handled = await self.parser.handle_line(stripped='plain log line', task_id=1, db=self.db)
        self.assertFalse(handled)
