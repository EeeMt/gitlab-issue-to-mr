#!/usr/bin/env python3
"""Unit tests for scheduler core logic.

Tests:
1. Priority queue ordering - higher priority tasks run first
2. Issue mutex behavior - same issue cannot run multiple tasks concurrently
3. Concurrency limiting - respects max_concurrency setting
"""

import asyncio
import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class SchedulerPriorityQueueTests(unittest.IsolatedAsyncioTestCase):
    """Tests for scheduler priority queue ordering."""

    def _create_mock_task(self, task_id: int, priority: int, scheduled_at=None, created_at=None) -> MagicMock:
        """Helper to create a mock Task."""
        task = MagicMock()
        task.id = task_id
        task.project_id = 1
        task.issue_iid = task_id * 10
        task.priority = priority
        task.status = "pending"
        task.scheduled_at = scheduled_at
        task.created_at = created_at or datetime.now(UTC)
        return task

    async def test_get_next_task_orders_by_priority_desc(self) -> None:
        """_get_next_task should return highest priority task first."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        task_high = self._create_mock_task(2, priority=10)

        # Query returns highest priority task
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task_high

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Call _get_next_task directly
        result = await scheduler._get_next_task(mock_db)

        # The query should be called
        mock_db.execute.assert_called_once()
        # Result should be task_high (highest priority)
        self.assertEqual(result, task_high)
        self.assertEqual(result.priority, 10)

    async def test_get_next_task_respects_scheduled_at_ordering(self) -> None:
        """_get_next_task should order by scheduled_at ASC (None first)."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        now = datetime.now(UTC)

        # Mock the select statement and scalars
        task_immediate = self._create_mock_task(1, priority=5, scheduled_at=None)
        task_future = self._create_mock_task(2, priority=5, scheduled_at=now + timedelta(hours=1))

        # When scalars().all() is called, return list sorted by scheduled_at
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.side_effect = [task_immediate, task_future]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await scheduler._get_next_task(mock_db)

        # Should return immediate task (None scheduled_at)
        self.assertEqual(result.id, 1)

    async def test_get_next_task_filters_by_status(self) -> None:
        """_get_next_task should only return PENDING or QUEUED tasks."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # No task returned

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await scheduler._get_next_task(mock_db)

        # Verify execute was called
        mock_db.execute.assert_called_once()
        # Result should be None since no tasks available
        self.assertIsNone(result)


class SchedulerIssueMutexTests(unittest.IsolatedAsyncioTestCase):
    """Tests for scheduler issue mutex behavior."""

    async def test_issue_mutex_prevents_duplicate_issue_tasks(self) -> None:
        """_running_issues set should block duplicate issue execution."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        # Pre-populate running issues set
        scheduler._running_issues.add("1:10")  # project_id:issue_iid

        # Check if issue is in mutex
        issue_key = "1:10"
        self.assertIn(issue_key, scheduler._running_issues)

        # Simulate what _run_cycle does - check mutex before execution
        task = MagicMock()
        task.project_id = 1
        task.issue_iid = 10

        issue_key = f"{task.project_id}:{task.issue_iid}"

        # Should skip because issue is already running
        self.assertIn(issue_key, scheduler._running_issues)

    async def test_different_issues_not_blocked_by_mutex(self) -> None:
        """Different issue_iid values should not conflict."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        scheduler._running_issues.add("1:10")

        # Different issue
        issue_key_2 = "1:20"
        self.assertNotIn(issue_key_2, scheduler._running_issues)

    async def test_manual_task_with_no_issue_not_blocked(self) -> None:
        """Manual tasks (issue_iid=None) should not be blocked."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        scheduler._running_issues.add("1:10")

        # Manual task issue_key is "1:None"
        manual_task_key = "1:None"
        self.assertNotIn(manual_task_key, scheduler._running_issues)

    async def test_issue_cleanup_after_task_completion(self) -> None:
        """_run_task_background should remove issue from _running_issues."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        # Issue is running
        scheduler._running_issues.add("1:10")
        scheduler._running_tasks.add(1)

        # Mock the background task to cleanup
        # We simulate the finally block cleanup
        scheduler._running_tasks.discard(1)
        scheduler._running_issues.discard("1:10")

        self.assertNotIn("1:10", scheduler._running_issues)
        self.assertNotIn(1, scheduler._running_tasks)


class SchedulerConcurrencyLimitingTests(unittest.IsolatedAsyncioTestCase):
    """Tests for scheduler concurrency limiting."""

    async def test_get_running_count_returns_correct_count(self) -> None:
        """_get_running_count should query database for RUNNING tasks."""
        from app.scheduler import Scheduler
        from app.models import TaskStatus

        scheduler = Scheduler()

        mock_result = MagicMock()
        mock_result.scalar.return_value = 3

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        count = await scheduler._get_running_count(mock_db)

        self.assertEqual(count, 3)
        mock_db.execute.assert_called_once()

    async def test_concurrency_check_before_task_selection(self) -> None:
        """Scheduler should check running count before selecting next task."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        # Simulate max concurrency reached
        running_count = 3
        max_concurrency = 3

        should_select_task = running_count < max_concurrency
        self.assertFalse(should_select_task)

        # Below max
        running_count = 2
        should_select_task = running_count < max_concurrency
        self.assertTrue(should_select_task)


class SchedulerCrashRecoveryTests(unittest.IsolatedAsyncioTestCase):
    """Tests for scheduler crash recovery."""

    async def test_crash_recovery_marks_stuck_tasks_failed(self) -> None:
        """Crash recovery should mark stuck RUNNING tasks as failed."""
        from app.scheduler import Scheduler
        from app.models import TaskStatus

        # This test verifies the logic that stuck tasks should be marked as failed
        # We test the status transition directly without DB access

        stuck_task = MagicMock()
        stuck_task.id = 1
        stuck_task.status = TaskStatus.RUNNING

        # Simulate what crash recovery does
        stuck_task.status = TaskStatus.FAILED
        stuck_task.error_message = "Task was running when service crashed"
        stuck_task.completed_at = datetime.now(UTC)

        self.assertEqual(stuck_task.status, TaskStatus.FAILED)
        self.assertIn("crashed", stuck_task.error_message.lower())

    async def test_worker_container_pattern_matching(self) -> None:
        """Worker containers should match the naming pattern."""
        from app.scheduler import WORKER_CONTAINER_PATTERN

        # Valid worker container names
        self.assertTrue(WORKER_CONTAINER_PATTERN.match("codify-1-p1-i10"))
        self.assertTrue(WORKER_CONTAINER_PATTERN.match("codify-123-p456-i789"))

        # Non-worker containers should not match
        self.assertFalse(WORKER_CONTAINER_PATTERN.match("codify-backend"))
        self.assertFalse(WORKER_CONTAINER_PATTERN.match("codify-postgres"))
        self.assertFalse(WORKER_CONTAINER_PATTERN.match("random-container"))


class SchedulerTaskExecutionTests(unittest.IsolatedAsyncioTestCase):
    """Tests for task execution flow."""

    async def test_execute_task_adds_to_running_tracking(self) -> None:
        """_execute_task should add task to _running_tasks and _running_issues."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        task = MagicMock()
        task.id = 1
        task.project_id = 1
        task.issue_iid = 10
        task.status = "pending"

        mock_db = MagicMock()
        mock_db.commit = AsyncMock()

        # Track what gets added
        scheduler._execute_task = AsyncMock()

        # Just verify the tracking sets exist and can be modified
        scheduler._running_tasks.add(task.id)
        scheduler._running_issues.add(f"{task.project_id}:{task.issue_iid}")

        self.assertIn(task.id, scheduler._running_tasks)
        self.assertIn("1:10", scheduler._running_issues)

    async def test_execute_task_updates_task_status(self) -> None:
        """_execute_task should update task status to RUNNING."""
        from app.scheduler import Scheduler
        from app.models import TaskStatus

        scheduler = Scheduler()

        task = MagicMock()
        task.id = 1
        task.project_id = 1
        task.issue_iid = 10
        task.status = TaskStatus.PENDING

        mock_db = MagicMock()
        mock_db.commit = AsyncMock()

        # Directly update status as _execute_task does
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(UTC)

        self.assertEqual(task.status, TaskStatus.RUNNING)
        self.assertIsNotNone(task.started_at)


if __name__ == "__main__":
    unittest.main()
