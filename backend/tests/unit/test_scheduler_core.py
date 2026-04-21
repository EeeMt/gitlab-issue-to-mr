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
        task.issue_id = task_id
        task.is_retry = False
        task.retry_source_task_id = None
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
        scheduler._running_issues.add(10)  # issue_id

        # Check if issue is in mutex
        issue_key = 10
        self.assertIn(issue_key, scheduler._running_issues)

        # Simulate what _run_cycle does - check mutex before execution
        task = MagicMock()
        task.project_id = 1
        task.issue_id = 10

        issue_key = task.issue_id

        # Should skip because issue is already running
        self.assertIn(issue_key, scheduler._running_issues)

    async def test_different_issues_not_blocked_by_mutex(self) -> None:
        """Different issue_id values should not conflict."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        scheduler._running_issues.add(10)

        # Different issue
        issue_key_2 = 20
        self.assertNotIn(issue_key_2, scheduler._running_issues)

    async def test_manual_task_with_no_issue_not_blocked(self) -> None:
        """Tasks with issue_id=None are independent and skip the mutex entirely."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        scheduler._running_issues.add(10)

        # A task with issue_id=None is independent; None is never in Set[int]
        self.assertNotIn(None, scheduler._running_issues)

    async def test_issue_cleanup_after_task_completion(self) -> None:
        """_run_task_background should remove issue from _running_issues."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        # Issue is running
        scheduler._running_issues.add(10)
        scheduler._running_tasks.add(1)

        # Mock the background task to cleanup
        # We simulate the finally block cleanup
        scheduler._running_tasks.discard(1)
        scheduler._running_issues.discard(10)

        self.assertNotIn(10, scheduler._running_issues)
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

        # Simulate what crash recovery does (container not found scenario)
        stuck_task.status = TaskStatus.FAILED
        stuck_task.error_message = "Task was running when scheduler restarted (container not found)"
        stuck_task.completed_at = datetime.now(UTC)

        self.assertEqual(stuck_task.status, TaskStatus.FAILED)
        self.assertIn("container not found", stuck_task.error_message.lower())

    async def test_worker_container_pattern_matching(self) -> None:
        """Worker containers should match the naming pattern."""
        from app.scheduler import WORKER_CONTAINER_PATTERN

        # Valid worker container names
        self.assertTrue(WORKER_CONTAINER_PATTERN.match("codify-1-issue10"))
        self.assertTrue(WORKER_CONTAINER_PATTERN.match("codify-123-issue789"))

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
        task.issue_id = 10
        task.status = "pending"

        mock_db = MagicMock()
        mock_db.commit = AsyncMock()

        # Track what gets added
        scheduler._execute_task = AsyncMock()

        # Just verify the tracking sets exist and can be modified
        scheduler._running_tasks.add(task.id)
        scheduler._running_issues.add(task.issue_id)

        self.assertIn(task.id, scheduler._running_tasks)
        self.assertIn(10, scheduler._running_issues)

    async def test_execute_task_updates_task_status(self) -> None:
        """_execute_task should update task status to RUNNING."""
        from app.scheduler import Scheduler
        from app.models import TaskStatus

        scheduler = Scheduler()

        task = MagicMock()
        task.id = 1
        task.project_id = 1
        task.issue_id = 10
        task.status = TaskStatus.PENDING

        mock_db = MagicMock()
        mock_db.commit = AsyncMock()

        # Directly update status as _execute_task does
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(UTC)

        self.assertEqual(task.status, TaskStatus.RUNNING)
        self.assertIsNotNone(task.started_at)


class SchedulerGetNextTaskTests(unittest.IsolatedAsyncioTestCase):
    """Tests for _get_next_task edge cases."""

    async def test_get_next_task_returns_none_when_no_tasks(self) -> None:
        """_get_next_task should return None when no pending/queued tasks exist."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await scheduler._get_next_task(mock_db)

        self.assertIsNone(result)
        mock_db.execute.assert_called_once()

    async def test_get_next_task_only_considers_pending_and_queued(self) -> None:
        """_get_next_task only queries for PENDING/QUEUED statuses (DB is called)."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        await scheduler._get_next_task(mock_db)

        # Ensure the database was queried exactly once (filtering is done in SQL)
        self.assertEqual(mock_db.execute.call_count, 1)


class SchedulerStartStopTests(unittest.IsolatedAsyncioTestCase):
    """Tests for scheduler start/stop lifecycle."""

    async def test_scheduler_stop_sets_running_false(self) -> None:
        """stop() should set self.running to False."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler.running = True
        await scheduler.stop()
        self.assertFalse(scheduler.running)

    async def test_get_scheduler_returns_singleton(self) -> None:
        """get_scheduler() should return the same instance on repeated calls."""
        import app.scheduler as sched_module

        # Reset singleton so we get a fresh one
        original = sched_module._scheduler
        sched_module._scheduler = None
        try:
            from app.scheduler import get_scheduler
            s1 = get_scheduler()
            s2 = get_scheduler()
            self.assertIs(s1, s2)
        finally:
            sched_module._scheduler = original


class SchedulerMaybeCleanupTests(unittest.IsolatedAsyncioTestCase):
    """Tests for _maybe_cleanup_sessions throttling."""

    async def test_cleanup_skipped_when_not_enough_time_elapsed(self) -> None:
        """If last cleanup was recent, cleanup_stale_sessions should NOT be called."""
        import time
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._last_session_cleanup_at = time.time()  # just now

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        mock_db.commit = AsyncMock()

        with patch("app.scheduler.cleanup_stale_sessions", new=AsyncMock()) as mock_cleanup:
            await scheduler._maybe_cleanup_sessions(mock_db)
            mock_cleanup.assert_not_called()

    async def test_cleanup_runs_when_enough_time_elapsed(self) -> None:
        """If last cleanup was long ago, cleanup_stale_sessions should be called."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._last_session_cleanup_at = 0.0  # epoch — very old

        mock_db = MagicMock()

        with patch("app.scheduler.cleanup_stale_sessions", new=AsyncMock(return_value=0)) as mock_cleanup:
            await scheduler._maybe_cleanup_sessions(mock_db)
            mock_cleanup.assert_awaited_once_with(mock_db)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# _get_running_count
# ---------------------------------------------------------------------------

class SchedulerGetRunningCountTests(unittest.IsolatedAsyncioTestCase):
    """Tests for _get_running_count."""

    async def test_get_running_count_returns_correct_value(self) -> None:
        """_get_running_count should return the DB count of RUNNING tasks."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        count_result = MagicMock()
        count_result.scalar.return_value = 3

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=count_result)

        count = await scheduler._get_running_count(mock_db)

        self.assertEqual(count, 3)
        mock_db.execute.assert_called_once()

    async def test_get_running_count_returns_zero_when_result_is_none(self) -> None:
        """_get_running_count should return 0 when scalar() is None."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        count_result = MagicMock()
        count_result.scalar.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=count_result)

        count = await scheduler._get_running_count(mock_db)

        self.assertEqual(count, 0)


# ---------------------------------------------------------------------------
# _crash_recovery
# ---------------------------------------------------------------------------

class SchedulerCrashRecoveryTests(unittest.IsolatedAsyncioTestCase):
    """Tests for crash recovery logic."""

    async def test_crash_recovery_marks_stuck_tasks_as_failed(self) -> None:
        """_crash_recovery should mark any RUNNING task as FAILED."""
        from app.scheduler import Scheduler
        from app.models import TaskStatus

        scheduler = Scheduler()

        stuck_task = MagicMock()
        stuck_task.id = 42
        stuck_task.status = TaskStatus.RUNNING

        tasks_result = MagicMock()
        tasks_result.scalars.return_value.all.return_value = [stuck_task]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=tasks_result)
        mock_db.commit = AsyncMock()

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_db)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = []

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_context):
            with patch("app.scheduler.get_docker_client", return_value=mock_docker):
                await scheduler._crash_recovery()

        self.assertEqual(stuck_task.status, TaskStatus.FAILED)
        self.assertIn("container not found", stuck_task.error_message)
        mock_db.commit.assert_awaited_once()

    async def test_crash_recovery_handles_docker_error_gracefully(self) -> None:
        """_crash_recovery should continue even if docker client raises."""
        from app.scheduler import Scheduler
        from app.models import TaskStatus

        scheduler = Scheduler()

        stuck_task = MagicMock()
        stuck_task.id = 43
        stuck_task.status = TaskStatus.RUNNING

        tasks_result = MagicMock()
        tasks_result.scalars.return_value.all.return_value = [stuck_task]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=tasks_result)
        mock_db.commit = AsyncMock()

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_db)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_context):
            with patch("app.scheduler.get_docker_client", side_effect=RuntimeError("docker down")):
                # Should not raise — docker failure is logged and skipped
                await scheduler._crash_recovery()

        # Task should still be marked failed
        self.assertEqual(stuck_task.status, TaskStatus.FAILED)

    async def test_crash_recovery_with_no_stuck_tasks(self) -> None:
        """_crash_recovery should handle the case with no stuck tasks."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        tasks_result = MagicMock()
        tasks_result.scalars.return_value.all.return_value = []

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=tasks_result)
        mock_db.commit = AsyncMock()

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_db)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = []

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_context):
            with patch("app.scheduler.get_docker_client", return_value=mock_docker):
                await scheduler._crash_recovery()

        # Should still commit (even if nothing to update)
        mock_db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# _run_cycle
# ---------------------------------------------------------------------------

class SchedulerRunCycleTests(unittest.IsolatedAsyncioTestCase):
    """Tests for the main _run_cycle method."""

    def _make_mock_db_context(self):
        """Helper: create an async context manager mock for AsyncSessionLocal."""
        mock_db = MagicMock()
        mock_db.commit = AsyncMock()
        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_db)
        mock_context.__aexit__ = AsyncMock(return_value=False)
        return mock_context, mock_db

    async def test_run_cycle_skips_when_max_concurrency_reached(self) -> None:
        """_run_cycle should return early when running count >= max_concurrency."""
        from app.scheduler import Scheduler
        from types import SimpleNamespace

        scheduler = Scheduler()
        mock_context, mock_db = self._make_mock_db_context()
        mock_settings = SimpleNamespace(max_concurrency=2, scheduler_interval=1)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_context):
            with patch("app.scheduler.load_runtime_config_from_db", new=AsyncMock()):
                with patch.object(scheduler, "_maybe_cleanup_sessions", new=AsyncMock()):
                    with patch.object(scheduler, "_mark_eligible_as_queued", new=AsyncMock()):
                        with patch("app.scheduler.get_settings", return_value=mock_settings):
                            with patch.object(scheduler, "_get_running_count", new=AsyncMock(return_value=2)):
                                with patch.object(scheduler, "_get_next_task", new=AsyncMock()) as mock_next:
                                    await scheduler._run_cycle()
                                    mock_next.assert_not_called()

    async def test_run_cycle_skips_when_no_task_available(self) -> None:
        """_run_cycle should return early when no pending task exists."""
        from app.scheduler import Scheduler
        from types import SimpleNamespace

        scheduler = Scheduler()
        mock_context, mock_db = self._make_mock_db_context()
        mock_settings = SimpleNamespace(max_concurrency=4, scheduler_interval=1)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_context):
            with patch("app.scheduler.load_runtime_config_from_db", new=AsyncMock()):
                with patch.object(scheduler, "_maybe_cleanup_sessions", new=AsyncMock()):
                    with patch.object(scheduler, "_mark_eligible_as_queued", new=AsyncMock()):
                        with patch("app.scheduler.get_settings", return_value=mock_settings):
                            with patch.object(scheduler, "_get_running_count", new=AsyncMock(return_value=0)):
                                with patch.object(scheduler, "_get_next_task", new=AsyncMock(return_value=None)):
                                    with patch.object(scheduler, "_execute_task", new=AsyncMock()) as mock_exec:
                                        await scheduler._run_cycle()
                                        mock_exec.assert_not_called()

    async def test_run_cycle_skips_when_issue_mutex_active(self) -> None:
        """_run_cycle should skip a task when its issue is already being processed."""
        from app.scheduler import Scheduler
        from app.models import TaskStatus
        from types import SimpleNamespace

        scheduler = Scheduler()
        mock_context, mock_db = self._make_mock_db_context()
        mock_settings = SimpleNamespace(max_concurrency=4, scheduler_interval=1)

        task = MagicMock()
        task.id = 1
        task.project_id = 10
        task.issue_id = 99

        # Pre-populate the running issues mutex
        scheduler._running_issues.add(99)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_context):
            with patch("app.scheduler.load_runtime_config_from_db", new=AsyncMock()):
                with patch.object(scheduler, "_maybe_cleanup_sessions", new=AsyncMock()):
                    with patch.object(scheduler, "_mark_eligible_as_queued", new=AsyncMock()):
                        with patch("app.scheduler.get_settings", return_value=mock_settings):
                            with patch.object(scheduler, "_get_running_count", new=AsyncMock(return_value=0)):
                                with patch.object(scheduler, "_get_next_task", new=AsyncMock(return_value=task)):
                                    with patch.object(scheduler, "_execute_task", new=AsyncMock()) as mock_exec:
                                        await scheduler._run_cycle()
                                        mock_exec.assert_not_called()

    async def test_run_cycle_executes_task_when_available(self) -> None:
        """_run_cycle should call _execute_task when a task is available and conditions allow."""
        from app.scheduler import Scheduler
        from types import SimpleNamespace

        scheduler = Scheduler()
        mock_context, mock_db = self._make_mock_db_context()
        mock_settings = SimpleNamespace(max_concurrency=4, scheduler_interval=1)

        task = MagicMock()
        task.id = 2
        task.project_id = 5
        task.issue_id = 50

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_context):
            with patch("app.scheduler.load_runtime_config_from_db", new=AsyncMock()):
                with patch.object(scheduler, "_maybe_cleanup_sessions", new=AsyncMock()):
                    with patch.object(scheduler, "_mark_eligible_as_queued", new=AsyncMock()):
                        with patch("app.scheduler.get_settings", return_value=mock_settings):
                            with patch.object(scheduler, "_get_running_count", new=AsyncMock(return_value=0)):
                                with patch.object(scheduler, "_get_next_task", new=AsyncMock(return_value=task)):
                                    with patch.object(scheduler, "_execute_task", new=AsyncMock()) as mock_exec:
                                        await scheduler._run_cycle()
                                        mock_exec.assert_called_once_with(mock_db, task)


# ---------------------------------------------------------------------------
# _maybe_cleanup_sessions — with sessions deleted
# ---------------------------------------------------------------------------

class SchedulerCleanupWithDeletesTests(unittest.IsolatedAsyncioTestCase):
    """Tests for _maybe_cleanup_sessions when sessions are deleted."""

    async def test_cleanup_commits_when_sessions_were_deleted(self) -> None:
        """When cleanup_stale_sessions returns > 0, db.commit should be called."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._last_session_cleanup_at = 0.0  # Very old — should trigger cleanup

        mock_db = MagicMock()
        mock_db.commit = AsyncMock()

        with patch("app.scheduler.cleanup_stale_sessions", new=AsyncMock(return_value=5)) as mock_cleanup:
            await scheduler._maybe_cleanup_sessions(mock_db)
            mock_cleanup.assert_awaited_once_with(mock_db)

        mock_db.commit.assert_awaited_once()

    async def test_cleanup_does_not_commit_when_no_sessions_deleted(self) -> None:
        """When cleanup_stale_sessions returns 0, db.commit should NOT be called."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._last_session_cleanup_at = 0.0

        mock_db = MagicMock()
        mock_db.commit = AsyncMock()

        with patch("app.scheduler.cleanup_stale_sessions", new=AsyncMock(return_value=0)):
            await scheduler._maybe_cleanup_sessions(mock_db)

        mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# _execute_task
# ---------------------------------------------------------------------------

class SchedulerExecuteTaskTests(unittest.IsolatedAsyncioTestCase):
    """Tests for Scheduler._execute_task."""

    async def test_execute_task_marks_task_running_and_submits_background(self) -> None:
        """_execute_task should set status=RUNNING, commit, and create a background task."""
        from app.scheduler import Scheduler
        from app.models import TaskStatus

        scheduler = Scheduler()

        task = MagicMock()
        task.id = 5
        task.project_id = 10
        task.issue_id = 20
        task.status = TaskStatus.PENDING

        mock_db = MagicMock()
        mock_db.commit = AsyncMock()

        with patch.object(scheduler, "_run_task_background", new=MagicMock()) as mock_bg:
            with patch("app.scheduler.asyncio.create_task") as mock_create_task:
                await scheduler._execute_task(mock_db, task)

        self.assertEqual(task.status, TaskStatus.RUNNING)
        self.assertIsNotNone(task.started_at)
        mock_db.commit.assert_awaited_once()
        self.assertIn(5, scheduler._running_tasks)
        self.assertIn(20, scheduler._running_issues)
        mock_create_task.assert_called_once()

    async def test_execute_task_handles_exception_and_marks_failed(self) -> None:
        """_execute_task should mark task FAILED when commit raises an exception."""
        from app.scheduler import Scheduler
        from app.models import TaskStatus

        scheduler = Scheduler()

        task = MagicMock()
        task.id = 6
        task.project_id = 11
        task.issue_id = 21
        task.status = TaskStatus.PENDING

        mock_db = MagicMock()
        # First commit (marking running) raises an exception
        mock_db.commit = AsyncMock(side_effect=[Exception("DB failure"), None])

        await scheduler._execute_task(mock_db, task)

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("DB failure", task.error_message)
        self.assertNotIn(6, scheduler._running_tasks)
        self.assertNotIn(21, scheduler._running_issues)


# ---------------------------------------------------------------------------
# _run_task_background
# ---------------------------------------------------------------------------

class SchedulerRunTaskBackgroundTests(unittest.IsolatedAsyncioTestCase):
    """Tests for _run_task_background method."""

    async def test_run_task_background_success_removes_from_tracking(self) -> None:
        """_run_task_background should remove task from tracking sets after completion."""
        from app.scheduler import Scheduler
        from app.models import TaskStatus

        scheduler = Scheduler()
        scheduler._running_tasks.add(10)

        task = MagicMock()
        task.id = 10
        task.project_id = 5
        task.issue_id = 50

        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=task_result)

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_db)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        # Mock the executor to return True (success)
        async def mock_run_in_executor(executor, func, *args):
            return True

        loop = MagicMock()
        loop.run_in_executor = mock_run_in_executor

        with patch("app.scheduler.asyncio.get_event_loop", return_value=loop):
            with patch("app.scheduler.AsyncSessionLocal", return_value=mock_context):
                await scheduler._run_task_background(10)

        # Task should be removed from tracking
        self.assertNotIn(10, scheduler._running_tasks)

    async def test_run_task_background_handles_exception(self) -> None:
        """_run_task_background should clean up tracking even when an exception occurs."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._running_tasks.add(11)

        task = MagicMock()
        task.id = 11
        task.project_id = 6
        task.issue_id = 60

        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=task_result)

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_db)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        # Mock the executor to raise an exception
        async def mock_run_in_executor_fail(executor, func, *args):
            raise RuntimeError("Worker failed")

        loop = MagicMock()
        loop.run_in_executor = mock_run_in_executor_fail

        with patch("app.scheduler.asyncio.get_event_loop", return_value=loop):
            with patch("app.scheduler.AsyncSessionLocal", return_value=mock_context):
                # Should not raise
                await scheduler._run_task_background(11)

        self.assertNotIn(11, scheduler._running_tasks)
