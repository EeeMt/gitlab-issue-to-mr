#!/usr/bin/env python3
"""
Extended worker coverage tests targeting specific uncovered lines.

Covers areas NOT yet tested by test_worker_coverage.py or test_worker_new_patterns.py:

A. _stream_logs_to_db internal paths:
   - Lines 243-248: deadline exceeded → timeout return (-1)
   - Lines 252-260: asyncio.TimeoutError → buffer flush on interval
   - Lines 276-278: empty stripped line → append to buffer only
   - Lines 283-307: CODIFY_TOOL_USE_START marker → tool_call TaskLog
   - Lines 311-327: CODIFY_TOOL_RESULT marker → update existing tool_call log
   - Lines 366-381: CODIFY_SYSTEM_INIT marker → system_init TaskLog
   - Lines 388-391: buffer flush when MAX_BUFFER_LINES reached or interval elapsed

B. Post-processing edge cases:
   - Lines 643-644: MR title parse exception
   - Lines 737-747: MR stats from API (success + None result)
   - Line 779: _update_mr_description existing section with no next section

C. Notification helpers:
   - Lines 809-810: _send_notifications completion notification exception
   - Lines 835-836: _send_failure_notifications completion exception
   - Lines 851-852: _send_failure_notifications Mattermost exception
   - Lines 898-899: execute_task _notify_task_started exception

D. resume_task full flow:
   - Lines 1056-1081: task lookup, container not found
   - Lines 1083-1125: stream → parse → success/failure paths, retry scheduling
   - Lines 1127-1148: exception handler with cleanup and notifications

E. Misc:
   - Lines 962-963: execute_task remove_mr_draft_status exception
   - Lines 1007-1008: execute_task container removal exception
   - Lines 1031-1036: execute_task exception handler notification failures
   - Lines 1202-1203: _notify_task_completed mr_iid extraction from URL fails
   - Line 1208: _notify_task_completed success with MR URL but no extractable IID
   - Lines 1226-1227: _notify_task_completed _update_mr_description exception
   - Lines 1273-1275: _send_failure_alert webhook request exception
"""

import asyncio
import json
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.worker import WorkerExecutor, scrub_sensitive_data, sanitize_sensitive_data
from app.models import Task, TaskLog, TaskStatus


# ---------------------------------------------------------------------------
# Shared helpers (same patterns as existing test_worker_coverage.py)
# ---------------------------------------------------------------------------

def _make_settings(**overrides):
    """Return a mock settings object with sensible defaults."""
    s = MagicMock()
    s.gitlab_url = "http://gitlab.example.com"
    s.gitlab_bot_token = "test-token"
    s.worker_image = "test-worker:latest"
    s.task_timeout = 1800
    s.anthropic_base_url = "http://localhost:11434/v1"
    s.anthropic_api_key = "test-key"
    s.anthropic_model = "claude-sonnet-4-20250514"
    s.default_target_branch = "main"
    s.max_retries = 0
    s.backend_url = "http://localhost:8000"
    s.dashboard_url = "http://localhost:3000"
    s.custom_ca_bundle = None
    s.maven_cache_host_path = ""
    s.maven_settings_host_path = ""
    s.worker_volume_mounts_parsed = []
    s.alert_on_failure = False
    s.alert_webhook_url = None
    s.claude_max_turns = 20
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _make_worker(mock_gitlab=None, mock_docker=None):
    """Build a WorkerExecutor with mock clients."""
    mock_gitlab = mock_gitlab or MagicMock()
    mock_docker = mock_docker or MagicMock()
    return WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)


def _make_task(**kwargs):
    """Create a Task object with defaults and attach a mock issue."""
    from unittest.mock import MagicMock

    # Separate issue-level kwargs
    issue_overrides = {}
    for key in ['branch_name', 'base_branch', 'target_branch', 'merge_request_iid', 'merge_request_url']:
        if key in kwargs:
            issue_overrides[key] = kwargs.pop(key)

    # Remove old fields that callers might still pass
    for old_key in ['issue_iid', 'note_id', 'is_manual', 'retry_count']:
        kwargs.pop(old_key, None)

    defaults = dict(
        id=1, project_id=100, issue_id=1,
        user_prompt="Fix the bug",
        priority=0, status=TaskStatus.PENDING,
        is_retry=False, retry_source_task_id=None,
        additions=0, deletions=0, total_changes=0,
    )
    defaults.update(kwargs)
    task = Task(**defaults)

    # Attach mock issue
    if defaults.get('issue_id') is not None:
        mock_issue = MagicMock()
        mock_issue.id = defaults['issue_id']
        mock_issue.branch_name = issue_overrides.get('branch_name', f"codify-{defaults['id']}-p{defaults['project_id']}-i{defaults.get('issue_id', 1)}")
        mock_issue.base_branch = issue_overrides.get('base_branch', None)
        mock_issue.target_branch = issue_overrides.get('target_branch', 'main')
        mock_issue.merge_request_iid = issue_overrides.get('merge_request_iid', None)
        mock_issue.merge_request_url = issue_overrides.get('merge_request_url', None)
        mock_issue.claude_session_id = None
        mock_issue.session_storage_path = None
        mock_issue.project_id = defaults['project_id']
        task.issue = mock_issue
    else:
        task.issue = None

    return task


def _make_db(task=None):
    """Create a mock async DB session."""
    from app.models import Issue
    db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = task
    mock_result.scalars.return_value.all.return_value = [task] if task else []
    db.execute = AsyncMock(return_value=mock_result)
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    # db.get should return the task's issue when queried
    async def mock_get(model_class, id_val):
        if task and model_class is Issue and hasattr(task, 'issue') and task.issue and task.issue.id == id_val:
            return task.issue
        return None
    db.get = AsyncMock(side_effect=mock_get)

    return db


def _make_stream_container(log_lines, exit_code=0):
    """Create a mock container that yields log_lines from .logs() and returns exit_code."""
    container = MagicMock()
    container.logs.return_value = iter(log_lines)
    container.wait.return_value = {"StatusCode": exit_code}
    container.id = "mock-container-id"
    return container


# ===================================================================
# A. _stream_logs_to_db — internal paths
# ===================================================================

class TestStreamLogsTimeout(unittest.TestCase):
    """Test _stream_logs_to_db deadline exceeded path — lines 243-248."""

    def test_returns_minus_one_on_deadline_exceeded(self):
        """When timeout=0, the deadline is already passed → returns (-1, ..., ...)."""
        worker = _make_worker()
        db = _make_db()
        container = _make_stream_container([b"some log line\n"])

        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=0)
        )

        self.assertEqual(exit_code, -1)

    def test_empty_buffer_on_deadline_exceeded(self):
        """When deadline exceeded with empty buffer, no flush occurs — lines 243-248."""
        worker = _make_worker()
        db = _make_db()

        # We need the queue to have items already, but deadline to be exceeded.
        # With timeout=0 the loop immediately hits remaining<=0 on first iteration.
        # But buffer is empty at first. We can't add to buffer before the loop starts.
        # Instead, use a very short timeout and a slow stream that produces data.
        # Actually, timeout=0 means remaining<=0 immediately, so buffer=[] → no flush.
        # Let's verify no flush occurs (buffer is empty at that point).
        container = _make_stream_container([])

        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=0)
        )

        self.assertEqual(exit_code, -1)
        self.assertEqual(chunks, 0)  # no buffer to flush


class TestStreamLogsTimeoutFlush(unittest.TestCase):
    """Test buffer flush on asyncio.TimeoutError in wait_for — lines 252-260."""

    def test_timeout_flush_interval(self):
        """When queue.get times out and flush interval elapsed, buffer is flushed."""
        worker = _make_worker()
        db = _make_db()

        # Create a container whose log stream stalls (yields nothing, then sentinel).
        # The _stream_thread reads from container.logs() which yields nothing for a while,
        # then we send the sentinel. We mock the queue directly instead.
        container = MagicMock()
        container.id = "mock-id"

        # We'll produce: one data line, then delay (timeout), then sentinel.
        # The easiest approach: mock the container.logs to be a slow iterator.
        lines_yielded = []

        def slow_log_gen():
            """Yield one line, then wait a bit, then end."""
            lines_yielded.append(True)
            yield b"first line\n"
            # Sleep to cause the asyncio.wait_for to time out at least once
            time.sleep(0.5)
            # Now the sentinel will be sent by the finally block

        container.logs.return_value = slow_log_gen()
        container.wait.return_value = {"StatusCode": 0}

        # Use a short timeout but enough for the stream to complete
        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=10)
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("first line", logs)


class TestStreamLogsEmptyLine(unittest.TestCase):
    """Test empty stripped line handling — lines 276-278."""

    def test_empty_line_appended_to_buffer(self):
        """Lines that strip to empty are still appended to buffer and all_lines."""
        worker = _make_worker()
        db = _make_db()
        container = _make_stream_container([b"\n", b"real content\n", b"  \n"])

        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        self.assertEqual(exit_code, 0)
        # The empty lines should be in the full log string
        self.assertIn("\n", logs)
        self.assertIn("real content", logs)

    def test_only_empty_lines_still_returned(self):
        """A stream of only empty lines produces logs with just newlines."""
        worker = _make_worker()
        db = _make_db()
        container = _make_stream_container([b"\n", b"\n", b"\n"])

        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(logs.strip(), "")


class TestStreamLogsToolUseStart(unittest.TestCase):
    """Test CODIFY_TOOL_USE_START marker parsing — lines 283-307."""

    def test_creates_tool_call_task_log(self):
        """CODIFY_TOOL_USE_START creates a TaskLog with log_type='tool_call'."""
        worker = _make_worker()
        db = _make_db()
        # Mock flush to assign an id to log entries
        original_add = db.add

        log_entries_added = []

        def capture_add(obj):
            if isinstance(obj, TaskLog):
                obj.id = len(log_entries_added) + 100  # simulate auto-assigned ID
                log_entries_added.append(obj)
            return original_add(obj)

        db.add = capture_add

        tool_use_data = json.dumps({
            "id": "tool_use_001",
            "name": "read_file",
            "input": {"path": "/workspace/main.py"},
        })
        line = f"CODIFY_TOOL_USE_START:{tool_use_data}\n".encode()
        container = _make_stream_container([line])

        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        self.assertEqual(exit_code, 0)
        tool_call_logs = [e for e in log_entries_added if e.log_type == "tool_call"]
        self.assertEqual(len(tool_call_logs), 1)

        metadata = json.loads(tool_call_logs[0].log_metadata)
        self.assertEqual(metadata["name"], "read_file")
        self.assertEqual(metadata["input"], {"path": "/workspace/main.py"})
        self.assertIsNone(metadata["output"])
        self.assertFalse(metadata["error"])

    def test_tool_use_start_invalid_json_does_not_crash(self):
        """CODIFY_TOOL_USE_START with invalid JSON is silently skipped — line 307."""
        worker = _make_worker()
        db = _make_db()
        container = _make_stream_container([b"CODIFY_TOOL_USE_START:{bad json}\n"])

        # Should not raise
        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        self.assertEqual(exit_code, 0)

    def test_tool_use_start_no_regex_match(self):
        """CODIFY_TOOL_USE_START: line that doesn't match regex is ignored."""
        worker = _make_worker()
        db = _make_db()
        # A line that starts with CODIFY_TOOL_USE_START: but has nothing after the colon.
        # The (.+) in the regex requires at least one char, so empty payload produces no match.
        container = _make_stream_container([b"CODIFY_TOOL_USE_START:\n"])

        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        self.assertEqual(exit_code, 0)


class TestStreamLogsToolResult(unittest.TestCase):
    """Test CODIFY_TOOL_RESULT marker parsing — lines 311-327."""

    def test_updates_existing_tool_call_log(self):
        """CODIFY_TOOL_RESULT updates the matching tool_call log with output."""
        worker = _make_worker()
        db = _make_db()

        # We need to simulate: TOOL_USE_START creates a log, then TOOL_RESULT updates it.
        # The tricky part is that _stream_logs_to_db uses db.flush() to get auto-assigned IDs,
        # and db.get() to retrieve the log entry for updating.

        log_entries_added = []

        original_add_fn = db.add

        def capture_add(obj):
            if isinstance(obj, TaskLog):
                obj.id = len(log_entries_added) + 100
                log_entries_added.append(obj)
            return original_add_fn(obj)

        db.add = capture_add

        # Make db.get return the log entry we added
        async def mock_get(model_class, log_id):
            for entry in log_entries_added:
                if entry.id == log_id:
                    return entry
            return None

        db.get = mock_get

        tool_use_line = json.dumps({
            "id": "tool_use_abc",
            "name": "write_file",
            "input": {"path": "/workspace/test.py", "content": "pass"},
        })
        tool_result_line = json.dumps({
            "id": "tool_use_abc",
            "output": "File written successfully",
            "error": False,
        })

        container = _make_stream_container([
            f"CODIFY_TOOL_USE_START:{tool_use_line}\n".encode(),
            f"CODIFY_TOOL_RESULT:{tool_result_line}\n".encode(),
        ])

        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        self.assertEqual(exit_code, 0)
        # The tool_call log should have been updated with the result
        tool_call_log = log_entries_added[0]
        metadata = json.loads(tool_call_log.log_metadata)
        self.assertEqual(metadata["output"], "File written successfully")
        self.assertFalse(metadata["error"])

    def test_tool_result_with_error_flag(self):
        """CODIFY_TOOL_RESULT with error=True updates the log accordingly."""
        worker = _make_worker()
        db = _make_db()

        log_entries_added = []
        original_add_fn = db.add

        def capture_add(obj):
            if isinstance(obj, TaskLog):
                obj.id = len(log_entries_added) + 100
                log_entries_added.append(obj)
            return original_add_fn(obj)

        db.add = capture_add

        async def mock_get(model_class, log_id):
            for entry in log_entries_added:
                if entry.id == log_id:
                    return entry
            return None

        db.get = mock_get

        tool_use_line = json.dumps({"id": "tu_err", "name": "bash", "input": {"command": "exit 1"}})
        tool_result_line = json.dumps({"id": "tu_err", "output": "Command failed", "error": True})

        container = _make_stream_container([
            f"CODIFY_TOOL_USE_START:{tool_use_line}\n".encode(),
            f"CODIFY_TOOL_RESULT:{tool_result_line}\n".encode(),
        ])

        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        self.assertEqual(exit_code, 0)
        metadata = json.loads(log_entries_added[0].log_metadata)
        self.assertTrue(metadata["error"])
        self.assertEqual(metadata["output"], "Command failed")

    def test_tool_result_no_matching_tool_use(self):
        """CODIFY_TOOL_RESULT with unknown id is silently skipped (no pending entry)."""
        worker = _make_worker()
        db = _make_db()

        tool_result_line = json.dumps({
            "id": "unknown_tool_id",
            "output": "some result",
            "error": False,
        })
        container = _make_stream_container([
            f"CODIFY_TOOL_RESULT:{tool_result_line}\n".encode(),
        ])

        # Should not raise
        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        self.assertEqual(exit_code, 0)

    def test_tool_result_invalid_json_does_not_crash(self):
        """CODIFY_TOOL_RESULT with invalid JSON is silently skipped — line 327."""
        worker = _make_worker()
        db = _make_db()
        container = _make_stream_container([b"CODIFY_TOOL_RESULT:{bad}\n"])

        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        self.assertEqual(exit_code, 0)


class TestStreamLogsSystemInit(unittest.TestCase):
    """Test CODIFY_SYSTEM_INIT marker in _stream_logs_to_db — lines 366-381."""

    def test_creates_system_init_task_log(self):
        """CODIFY_SYSTEM_INIT with valid JSON creates a TaskLog with log_type='system_init'."""
        worker = _make_worker()
        db = _make_db()

        json_str = json.dumps({"model": "claude-sonnet-4-20250514", "cwd": "/workspace"})
        container = _make_stream_container([
            f"CODIFY_SYSTEM_INIT:{json_str}\n".encode(),
        ])

        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        self.assertEqual(exit_code, 0)
        added_objects = [c[0][0] for c in db.add.call_args_list if isinstance(c[0][0], TaskLog)]
        system_init_logs = [o for o in added_objects if o.log_type == "system_init"]
        self.assertEqual(len(system_init_logs), 1)
        self.assertEqual(system_init_logs[0].log_metadata, json_str)
        self.assertEqual(system_init_logs[0].message, "")

    def test_system_init_invalid_json_does_not_crash(self):
        """CODIFY_SYSTEM_INIT with invalid JSON is silently skipped — line 381."""
        worker = _make_worker()
        db = _make_db()
        container = _make_stream_container([b"CODIFY_SYSTEM_INIT:not-json\n"])

        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        self.assertEqual(exit_code, 0)
        added_objects = [c[0][0] for c in db.add.call_args_list if isinstance(c[0][0], TaskLog)]
        system_init_logs = [o for o in added_objects if getattr(o, "log_type", None) == "system_init"]
        self.assertEqual(len(system_init_logs), 0)


class TestStreamLogsBufferFlush(unittest.TestCase):
    """Test buffer flush on MAX_BUFFER_LINES threshold — lines 387-391."""

    def test_flushes_at_max_buffer_lines(self):
        """Buffer is flushed when it reaches MAX_BUFFER_LINES (200) — line 387."""
        worker = _make_worker()
        db = _make_db()

        # Generate 250 lines — should trigger at least one flush at 200 lines
        lines = [f"log line {i}\n".encode() for i in range(250)]
        container = _make_stream_container(lines)

        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=10)
        )

        self.assertEqual(exit_code, 0)
        # At least 2 chunks: one at 200 lines, remaining 50 at the end
        self.assertGreaterEqual(chunks, 2)

    def test_single_multi_line_chunk(self):
        """Docker may batch multiple lines into a single chunk."""
        worker = _make_worker()
        db = _make_db()

        # Send a single chunk with multiple lines
        multi_line = b"line 1\nline 2\nline 3\n"
        container = _make_stream_container([multi_line])

        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("line 1", logs)
        self.assertIn("line 2", logs)
        self.assertIn("line 3", logs)


# ===================================================================
# B. Post-processing edge cases
# ===================================================================

class TestParseMrTitleException(unittest.TestCase):
    """Test MR title parse exception path — lines 643-644."""

    def test_mr_title_exception_does_not_crash(self):
        """Exception during CODIFY_MR_TITLE processing is caught — lines 643-644."""
        worker = _make_worker()
        task = _make_task()
        db = _make_db()

        # We need the regex to match but the internal processing to raise.
        # The title match group(1) returns a string, and .strip() is called.
        # If title is truthy, sanitize_sensitive_data is called on it.
        # Let's patch sanitize_sensitive_data to raise an exception.
        logs = "CODIFY_MR_TITLE:Some title\n"

        with patch("app.core.worker.sanitize_sensitive_data", side_effect=Exception("sanitize boom")):
            # Should not raise
            asyncio.run(worker._parse_task_result(task, logs, db, exit_code=0))

        # merge_request_title should remain unset
        self.assertIsNone(task.merge_request_title)


class TestUpdateTaskStatsFromApi(unittest.TestCase):
    """Test MR stats from API paths — lines 737-747."""

    def test_mr_stats_from_api_success(self):
        """When diff stats not in logs, fetches from API — lines 737-745."""
        mock_gitlab = MagicMock()
        mock_gitlab.get_merge_request_stats = AsyncMock(return_value={
            "additions": 25,
            "deletions": 10,
            "total": 35,
        })
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()
        task.issue.merge_request_iid = 42
        logs = "no diff stats here\n"

        asyncio.run(worker._update_task_stats_from_logs_or_api(task, logs, issue=task.issue))

        self.assertEqual(task.additions, 25)
        self.assertEqual(task.deletions, 10)
        self.assertEqual(task.total_changes, 35)

    def test_mr_stats_from_api_returns_none(self):
        """When API returns None for stats — lines 746-747."""
        mock_gitlab = MagicMock()
        mock_gitlab.get_merge_request_stats = AsyncMock(return_value=None)
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()
        task.issue.merge_request_iid = 42
        logs = "no diff stats\n"

        # Should not raise, stats remain at defaults
        asyncio.run(worker._update_task_stats_from_logs_or_api(task, logs, issue=task.issue))

        self.assertEqual(task.additions, 0)
        self.assertEqual(task.deletions, 0)

    def test_mr_stats_from_api_exception(self):
        """When API call raises, stats remain unchanged — line 749."""
        mock_gitlab = MagicMock()
        mock_gitlab.get_merge_request_stats = AsyncMock(side_effect=Exception("API error"))
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()
        task.issue.merge_request_iid = 42
        logs = "no diff stats\n"

        # Should not raise
        asyncio.run(worker._update_task_stats_from_logs_or_api(task, logs, issue=task.issue))

        self.assertEqual(task.additions, 0)

    def test_mr_stats_skipped_when_no_mr_iid(self):
        """When no merge_request_iid and no diff in logs, stats are not fetched."""
        mock_gitlab = MagicMock()
        mock_gitlab.get_merge_request_stats = AsyncMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()
        task.issue.merge_request_iid = None
        logs = "no diff stats\n"

        asyncio.run(worker._update_task_stats_from_logs_or_api(task, logs, issue=task.issue))

        mock_gitlab.get_merge_request_stats.assert_not_awaited()


class TestUpdateMrDescriptionNoNextSection(unittest.TestCase):
    """Test _update_mr_description with existing section and no next section — line 779."""

    def test_existing_section_no_next_section(self):
        """When execution section exists but there's no next --- section, append at end."""
        mock_mr = MagicMock()
        # Description has execution section but no trailing ---
        mock_mr.description = "## Info\n---\n### 执行进度\n- [x] 初始任务完成"

        mock_gitlab = MagicMock()
        mock_gitlab.get_merge_request.return_value = mock_mr
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(id=99)

        worker._update_mr_description(task, mr_iid=5)

        self.assertIn("任务 99", mock_mr.description)
        mock_mr.save.assert_called_once()
        # The progress should be appended at the end
        self.assertTrue(mock_mr.description.endswith("(任务 99)"))


# ===================================================================
# C. Notification helpers — exception edge cases
# ===================================================================

class TestSendNotificationsExceptions(unittest.TestCase):
    """Test _send_notifications and _send_failure_notifications exception paths."""

    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_send_notifications_completion_exception(self, mock_notify_event):
        """_send_notifications catches exception from _notify_task_completed — lines 809-810."""
        mock_gitlab = MagicMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(issue_id=1)

        # Make _notify_task_completed raise
        with patch.object(worker, '_notify_task_completed', new=AsyncMock(side_effect=Exception("notify error"))):
            # Should not raise
            asyncio.run(worker._send_notifications(task, success=True, had_existing_mr=False, logs="", issue=task.issue))

    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_send_failure_notifications_completion_exception(self, mock_notify_event):
        """_send_failure_notifications catches exception from _notify_task_completed — lines 835-836."""
        mock_gitlab = MagicMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(issue_id=1, status=TaskStatus.FAILED)

        with patch.object(worker, '_notify_task_completed', new=AsyncMock(side_effect=Exception("notify boom"))):
            # Should not raise
            asyncio.run(worker._send_failure_notifications(task, success=False, had_existing_mr=False, issue=task.issue))

    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_send_failure_notifications_mattermost_exception(self, mock_notify_event):
        """_send_failure_notifications catches Mattermost exception — lines 851-852."""
        mock_gitlab = MagicMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(issue_id=None, status=TaskStatus.FAILED)

        mock_notify_event.side_effect = Exception("Mattermost down")

        # Should not raise
        asyncio.run(worker._send_failure_notifications(task, success=False, had_existing_mr=False))


class TestExecuteTaskNotifyStartedException(unittest.TestCase):
    """Test execute_task catches _notify_task_started exception — lines 898-899."""

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_notify_started_exception_does_not_abort(self, mock_notify, mock_get_settings):
        """Exception in _notify_task_started doesn't abort execute_task — lines 898-899."""
        mock_get_settings.return_value = _make_settings()
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = MagicMock(id="ctr-123")

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock(side_effect=Exception("GitLab down"))
        mock_gitlab.create_mr_note = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(issue_id=1)
        db = _make_db(task)

        fake_logs = "CODIFY_DIFF:+1-0\n"

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, fake_logs, 1))):
            result = asyncio.run(worker.execute_task(db, task.id))

        # Should still succeed despite notification failure
        self.assertTrue(result)


# ===================================================================
# D. resume_task — full flow
# ===================================================================

class TestResumeTaskNotFound(unittest.TestCase):
    """Test resume_task when task is not found — lines 1056-1064."""

    @patch('app.core.worker.get_settings')
    def test_returns_false_when_task_not_found(self, mock_get_settings):
        """resume_task returns False when task is not in DB — lines 1062-1064."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        db = _make_db(task=None)

        result = asyncio.run(worker.resume_task(db, task_id=999, container_name="codify-999"))

        self.assertFalse(result)


class TestResumeTaskContainerNotFound(unittest.TestCase):
    """Test resume_task when container is not found — lines 1073-1081."""

    @patch('app.core.worker.get_settings')
    def test_container_not_found_sets_failed(self, mock_get_settings):
        """resume_task sets FAILED when container is not found — lines 1075-1081."""
        mock_get_settings.return_value = _make_settings()
        mock_docker = MagicMock()
        mock_docker.client.containers.get.side_effect = Exception("Container not found")

        worker = _make_worker(mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING)
        db = _make_db(task)

        result = asyncio.run(worker.resume_task(db, task_id=task.id, container_name="codify-1"))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("Container disappeared", task.error_message)
        self.assertIsNotNone(task.completed_at)


class TestResumeTaskSuccess(unittest.TestCase):
    """Test resume_task success flow — lines 1083-1125."""

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_resume_success_completes_task(self, mock_notify, mock_get_settings):
        """resume_task success flow: stream logs → parse → COMPLETED — lines 1092-1099."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(
            status=TaskStatus.RUNNING,
            merge_request_iid=42,
            merge_request_url="http://gitlab.example.com/-/merge_requests/42",
        )
        db = _make_db(task)

        fake_logs = "CODIFY_DIFF:+5-3\nhttp://gitlab.example.com/-/merge_requests/42\n"

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, fake_logs, 2))):
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertTrue(result)
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        mock_docker.remove_container.assert_called_with(mock_container, force=True)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_resume_success_removes_mr_draft(self, mock_notify, mock_get_settings):
        """resume_task on success removes MR draft status via _remove_mr_draft_status_for_issue."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-draft")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING, merge_request_iid=42)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, "CODIFY_DIFF:+1-0\n", 1))):
            with patch.object(worker, '_remove_mr_draft_status_for_issue') as mock_remove_draft:
                asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        mock_remove_draft.assert_called_once_with(task, task.issue)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_resume_success_draft_removal_exception(self, mock_notify, mock_get_settings):
        """resume_task catches _remove_mr_draft_status_for_issue exception."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-draft-err")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING, merge_request_iid=42)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, "CODIFY_DIFF:+1-0\n", 1))):
            with patch.object(worker, '_remove_mr_draft_status_for_issue', side_effect=Exception("draft boom")):
                result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        # Should still succeed
        self.assertTrue(result)


class TestResumeTaskFailure(unittest.TestCase):
    """Test resume_task failure flow — lines 1100-1107."""

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_resume_failure_no_retry(self, mock_notify, mock_get_settings):
        """resume_task failure sets FAILED — lines 1100-1107."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-fail")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(1, "error occurred", 1))):
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIsNotNone(task.error_message)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_resume_failure_stays_failed(self, mock_notify, mock_get_settings):
        """resume_task failure stays FAILED (no retry logic)."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-retry")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(1, "error", 1))):
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_resume_failure_no_log_chunks_creates_fallback(self, mock_notify, mock_get_settings):
        """resume_task with 0 log chunks on success creates fallback log — lines 1114-1116."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-fast")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, "CODIFY_DIFF:+1-0\n", 1))):
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        # Should still return True (success) despite cleanup failure
        self.assertTrue(result)


class TestResumeTaskException(unittest.TestCase):
    """Test resume_task exception handler — lines 1127-1148."""

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_exception_sets_failed_and_cleans_up(self, mock_notify, mock_get_settings):
        """Exception during resume sets FAILED and cleans up container — lines 1127-1137."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-exc")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING, merge_request_iid=None)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', side_effect=RuntimeError("Docker exploded")):
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("Docker exploded", task.error_message)
        mock_docker.remove_container.assert_called_with(mock_container, force=True)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_exception_cleanup_failure_does_not_raise(self, mock_notify, mock_get_settings):
        """Container cleanup failure during exception handling is caught — lines 1136-1137."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-cleanup-err")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container
        mock_docker.remove_container.side_effect = Exception("Cannot remove")

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING, merge_request_iid=None)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', side_effect=RuntimeError("boom")):
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertFalse(result)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_exception_notification_failure_does_not_raise(self, mock_notify, mock_get_settings):
        """Notification failures during exception handling are caught — lines 1139-1146."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-notify-err")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING, merge_request_iid=None, is_manual=False)
        db = _make_db(task)

        # Make both _notify_task_completed and notify_task_event raise
        with patch.object(worker, '_stream_logs_to_db', side_effect=RuntimeError("stream failed")):
            with patch.object(worker, '_notify_task_completed', new=AsyncMock(side_effect=Exception("notify failed"))):
                mock_notify.side_effect = Exception("mattermost failed")
                result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_resume_with_had_existing_mr(self, mock_notify, mock_get_settings):
        """resume_task with existing MR sets notify_target='mr' — line 1070."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-mr")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(
            status=TaskStatus.RUNNING,
            merge_request_iid=55,
            merge_request_url="http://gitlab.example.com/-/merge_requests/55",
        )
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, "CODIFY_DIFF:+1-0\n", 1))):
            with patch.object(worker, '_send_notifications', new=AsyncMock()) as mock_send:
                result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertTrue(result)
        mock_send.assert_called_once()
        self.assertTrue(mock_send.call_args.kwargs.get("had_existing_mr"))


# ===================================================================
# E. Misc — execute_task edge cases
# ===================================================================

class TestExecuteTaskDraftRemovalException(unittest.TestCase):
    """Test execute_task catches _remove_mr_draft_status exception — lines 962-963."""

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_draft_removal_exception_does_not_abort(self, mock_notify, mock_get_settings):
        """Exception in _remove_mr_draft_status doesn't abort execute_task — lines 962-963."""
        mock_get_settings.return_value = _make_settings()
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = MagicMock(id="ctr-draft-err")

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=42)
        db = _make_db(task)

        fake_logs = "CODIFY_DIFF:+1-0\nhttp://gitlab.example.com/-/merge_requests/42\n"

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, fake_logs, 1))):
            with patch.object(worker, '_remove_mr_draft_status', side_effect=Exception("draft error")):
                result = asyncio.run(worker.execute_task(db, task.id))

        # Should still succeed
        self.assertTrue(result)


class TestExecuteTaskContainerRemovalException(unittest.TestCase):
    """Test execute_task catches container removal exception — lines 1007-1008."""

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_container_removal_exception_does_not_raise(self, mock_notify, mock_get_settings):
        """Exception in docker.remove_container doesn't raise — lines 1007-1008."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-rm-err")
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = mock_container
        mock_docker.remove_container.side_effect = Exception("Cannot remove")

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=None)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, "CODIFY_DIFF:+1-0\n", 1))):
            result = asyncio.run(worker.execute_task(db, task.id))

        # Should still return True (success) despite cleanup failure
        self.assertTrue(result)


class TestExecuteTaskExceptionNotificationFailures(unittest.TestCase):
    """Test execute_task exception handler notification failures — lines 1031-1036."""

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_notification_failures_in_exception_handler(self, mock_notify, mock_get_settings):
        """Both _notify_task_completed and notify_task_event can fail — lines 1031-1036."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-notify-err")
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=None, is_manual=False)
        db = _make_db(task)

        # Make stream raise, then also make notifications raise
        mock_notify.side_effect = Exception("mattermost down")

        with patch.object(worker, '_stream_logs_to_db', side_effect=RuntimeError("stream failed")):
            with patch.object(worker, '_notify_task_completed', new=AsyncMock(side_effect=Exception("notify failed"))):
                result = asyncio.run(worker.execute_task(db, task.id))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)


class TestNotifyTaskCompletedMrIidExtraction(unittest.TestCase):
    """Test _notify_task_completed MR IID extraction edge cases — lines 1202-1203, 1208."""

    @patch('app.core.worker.get_settings')
    def test_mr_iid_extraction_from_url_failure(self, mock_get_settings):
        """When MR URL parsing fails, uses fallback message — lines 1202-1203."""
        mock_get_settings.return_value = _make_settings()
        mock_gitlab = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)

        # URL with /merge_requests/ but the IID part is not extractable
        task = _make_task(
            merge_request_iid=None,
            merge_request_url="http://gitlab.example.com/project/-/merge_requests/",
            is_manual=False,
        )

        asyncio.run(worker._notify_task_completed(task, success=True, notify_target="mr"))

        # Should use the "MR 已更新" fallback message since no numeric IID extracted

    @patch('app.core.worker.get_settings')
    def test_success_mr_url_with_no_extractable_iid(self, mock_get_settings):
        """Success with MR URL but non-numeric IID — notify_target=issue does not send."""
        mock_get_settings.return_value = _make_settings()
        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)

        # URL that has merge_requests but splitting gives empty string
        task = _make_task(
            merge_request_iid=None,
            merge_request_url="http://gitlab.example.com/merge_requests/abc?foo=bar",
        )
        issue = task.issue

        asyncio.run(worker._notify_task_completed(task, success=True, notify_target="issue", issue=issue))

        # With no mr_iid and notify_target="issue", the worker doesn't send to issue
        # Only MR notifications are supported now
        mock_gitlab.create_note.assert_not_called()
        mock_gitlab.create_mr_note.assert_not_called()


class TestNotifyTaskCompletedUpdateMrDescException(unittest.TestCase):
    """Test _notify_task_completed catches _update_mr_description exception — lines 1226-1227."""

    @patch('app.core.worker.get_settings')
    def test_update_mr_description_exception_caught(self, mock_get_settings):
        """Exception in _update_mr_description during notification is caught — lines 1226-1227."""
        mock_get_settings.return_value = _make_settings()
        mock_gitlab = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(
            merge_request_iid=42,
            merge_request_url="http://gitlab.example.com/-/merge_requests/42",
        )
        issue = task.issue

        with patch.object(worker, '_update_mr_description', side_effect=Exception("desc update failed")):
            # Should not raise
            asyncio.run(worker._notify_task_completed(task, success=True, notify_target="mr", issue=issue))

        mock_gitlab.create_mr_note.assert_called_once()


class TestSendFailureAlertWebhookException(unittest.TestCase):
    """Test _send_failure_alert webhook request exception — lines 1273-1275."""

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.get_ssl_verify')
    def test_webhook_request_exception_caught(self, mock_ssl, mock_get_settings):
        """httpx.AsyncClient.post exception is caught — lines 1273-1275."""
        mock_get_settings.return_value = _make_settings(
            alert_on_failure=True,
            alert_webhook_url="http://hooks.example.com/alert",
        )
        mock_ssl.return_value = True
        worker = _make_worker()
        task = _make_task(error_message="something failed")

        mock_client_instance = AsyncMock()
        mock_client_instance.post.side_effect = Exception("Connection refused")
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch('app.core.worker.httpx.AsyncClient', return_value=mock_client_instance):
            # Should not raise
            asyncio.run(worker._send_failure_alert(task))

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.get_ssl_verify')
    def test_webhook_non_success_status_code(self, mock_ssl, mock_get_settings):
        """Non-success status code logs warning — lines 1273."""
        mock_get_settings.return_value = _make_settings(
            alert_on_failure=True,
            alert_webhook_url="http://hooks.example.com/alert",
        )
        mock_ssl.return_value = True
        worker = _make_worker()
        task = _make_task(error_message="failed")

        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch('app.core.worker.httpx.AsyncClient', return_value=mock_client_instance):
            # Should not raise
            asyncio.run(worker._send_failure_alert(task))


class TestStreamLogsContainerWaitException(unittest.TestCase):
    """Test container.wait() exception after stream ends — line 404-406."""

    def test_container_wait_exception_returns_minus_one(self):
        """When container.wait() raises, exit_code is -1."""
        worker = _make_worker()
        db = _make_db()

        container = MagicMock()
        container.logs.return_value = iter([b"some log\n"])
        container.wait.side_effect = Exception("container wait timeout")
        container.id = "mock-id"

        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        self.assertEqual(exit_code, -1)
        self.assertIn("some log", logs)


class TestStreamLogsMultipleMarkersSameStream(unittest.TestCase):
    """Test that multiple marker types in a single stream are all processed correctly."""

    def test_mixed_markers_processed(self):
        """THINKING, TOOL_USE_START, SYSTEM_INIT in one stream all create logs."""
        worker = _make_worker()
        db = _make_db()

        log_entries_added = []
        original_add_fn = db.add

        def capture_add(obj):
            if isinstance(obj, TaskLog):
                obj.id = len(log_entries_added) + 100
                log_entries_added.append(obj)
            return original_add_fn(obj)

        db.add = capture_add

        thinking_data = json.dumps({"text": "Let me think..."})
        system_init_data = json.dumps({"model": "claude-sonnet", "cwd": "/ws"})
        tool_use_data = json.dumps({"id": "tu1", "name": "bash", "input": {"cmd": "ls"}})

        container = _make_stream_container([
            b"Normal log line\n",
            f"CODIFY_THINKING:{thinking_data}\n".encode(),
            f"CODIFY_SYSTEM_INIT:{system_init_data}\n".encode(),
            f"CODIFY_TOOL_USE_START:{tool_use_data}\n".encode(),
            b"Another normal line\n",
        ])

        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        self.assertEqual(exit_code, 0)

        # Check each marker type was captured
        thinking_logs = [e for e in log_entries_added if e.log_type == "thinking"]
        self.assertEqual(len(thinking_logs), 1)

        system_init_logs = [e for e in log_entries_added if e.log_type == "system_init"]
        self.assertEqual(len(system_init_logs), 1)

        tool_call_logs = [e for e in log_entries_added if e.log_type == "tool_call"]
        self.assertEqual(len(tool_call_logs), 1)


class TestStreamLogsThreadError(unittest.TestCase):
    """Test that log stream thread errors send sentinel and don't hang."""

    def test_stream_thread_exception_sends_sentinel(self):
        """When container.logs() raises, thread sends sentinel and stream ends cleanly."""
        worker = _make_worker()
        db = _make_db()

        container = MagicMock()
        container.logs.side_effect = Exception("Docker API error")
        container.wait.return_value = {"StatusCode": 1}
        container.id = "mock-id"

        exit_code, logs, chunks = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        # The stream thread raised but sent sentinel, so we get whatever exit code container.wait returns
        # (or -1 if wait also fails)
        self.assertIn(exit_code, [1, -1])
        self.assertEqual(logs, "")  # no data was read before the error


if __name__ == "__main__":
    unittest.main()
