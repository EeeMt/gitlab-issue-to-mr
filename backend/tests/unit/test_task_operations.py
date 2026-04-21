"""Tests for task operation helpers — notification error handling paths.

Covers uncovered lines in app/api/task_operations.py:
- notify_task_cancelled exception handling (lines 171-172)
- notify_task_retried exception handling (lines 192-193)
- notify_task_execute_now exception handling (lines 212-213)
- notify_task_rescheduled exception handling (lines 233-234)
"""

import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.models import TaskStatus


def _make_task(task_id=1, status=TaskStatus.PENDING, scheduled_at=None):
    """Build a mock Task object."""
    task = MagicMock()
    task.id = task_id
    task.status = status
    task.project_id = 10
    task.issue_id = 1
    task.user_prompt = "Test prompt"
    task.scheduled_at = scheduled_at
    task.initiator_username = "testuser"
    return task


# ---------------------------------------------------------------------------
# Notification error handling (exception is logged, not raised)
# ---------------------------------------------------------------------------


class TestNotifyTaskCancelled(unittest.IsolatedAsyncioTestCase):
    """Test notify_task_cancelled swallows exceptions."""

    @patch("app.api.task_operations.notify_task_event", new_callable=AsyncMock)
    async def test_success(self, mock_notify):
        """Should call notify_task_event without error."""
        from app.api.task_operations import notify_task_cancelled

        task = _make_task(status=TaskStatus.CANCELLED)
        await notify_task_cancelled(task)
        mock_notify.assert_awaited_once()

    @patch("app.api.task_operations.notify_task_event", new_callable=AsyncMock)
    async def test_exception_swallowed(self, mock_notify):
        """Should log warning and not raise when notification fails."""
        from app.api.task_operations import notify_task_cancelled

        mock_notify.side_effect = Exception("Mattermost down")
        task = _make_task(task_id=42, status=TaskStatus.CANCELLED)

        # Should NOT raise
        await notify_task_cancelled(task)
        mock_notify.assert_awaited_once()


class TestNotifyTaskRetried(unittest.IsolatedAsyncioTestCase):
    """Test notify_task_retried swallows exceptions."""

    @patch("app.api.task_operations.notify_task_event", new_callable=AsyncMock)
    async def test_success(self, mock_notify):
        """Should call notify_task_event with context."""
        from app.api.task_operations import notify_task_retried

        task = _make_task(status=TaskStatus.PENDING)
        prev_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        new_dt = datetime(2025, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
        await notify_task_retried(task, previous_scheduled_at=prev_dt, scheduled_at=new_dt)
        mock_notify.assert_awaited_once()

    @patch("app.api.task_operations.notify_task_event", new_callable=AsyncMock)
    async def test_exception_swallowed(self, mock_notify):
        """Should log warning and not raise when notification fails."""
        from app.api.task_operations import notify_task_retried

        mock_notify.side_effect = RuntimeError("Connection refused")
        task = _make_task(task_id=55, status=TaskStatus.PENDING)

        # Should NOT raise
        await notify_task_retried(task, previous_scheduled_at=None, scheduled_at=None)
        mock_notify.assert_awaited_once()


class TestNotifyTaskExecuteNow(unittest.IsolatedAsyncioTestCase):
    """Test notify_task_execute_now swallows exceptions."""

    @patch("app.api.task_operations.notify_task_event", new_callable=AsyncMock)
    async def test_success(self, mock_notify):
        """Should call notify_task_event with context."""
        from app.api.task_operations import notify_task_execute_now

        task = _make_task(status=TaskStatus.QUEUED)
        prev_dt = datetime(2025, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
        await notify_task_execute_now(task, previous_scheduled_at=prev_dt)
        mock_notify.assert_awaited_once()

    @patch("app.api.task_operations.notify_task_event", new_callable=AsyncMock)
    async def test_exception_swallowed(self, mock_notify):
        """Should log warning and not raise when notification fails."""
        from app.api.task_operations import notify_task_execute_now

        mock_notify.side_effect = TimeoutError("Mattermost timeout")
        task = _make_task(task_id=77, status=TaskStatus.QUEUED)

        # Should NOT raise
        await notify_task_execute_now(task, previous_scheduled_at=None)
        mock_notify.assert_awaited_once()


class TestNotifyTaskRescheduled(unittest.IsolatedAsyncioTestCase):
    """Test notify_task_rescheduled swallows exceptions."""

    @patch("app.api.task_operations.notify_task_event", new_callable=AsyncMock)
    async def test_success(self, mock_notify):
        """Should call notify_task_event with context."""
        from app.api.task_operations import notify_task_rescheduled

        task = _make_task(status=TaskStatus.PENDING)
        prev_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        new_dt = datetime(2025, 1, 3, 14, 0, 0, tzinfo=timezone.utc)
        await notify_task_rescheduled(task, previous_scheduled_at=prev_dt, scheduled_at=new_dt)
        mock_notify.assert_awaited_once()

    @patch("app.api.task_operations.notify_task_event", new_callable=AsyncMock)
    async def test_exception_swallowed(self, mock_notify):
        """Should log warning and not raise when notification fails."""
        from app.api.task_operations import notify_task_rescheduled

        mock_notify.side_effect = ConnectionError("Network failure")
        task = _make_task(task_id=88, status=TaskStatus.PENDING)
        new_dt = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)

        # Should NOT raise
        await notify_task_rescheduled(task, previous_scheduled_at=None, scheduled_at=new_dt)
        mock_notify.assert_awaited_once()
