#!/usr/bin/env python3
"""Additional unit tests for scheduler.py to improve coverage.

Targets missed lines:
- 44-61: start() — full scheduler loop, crash recovery exception, cycle exception
- 95: _run_cycle task with issue_id=None (skips mutex)
- 182: _run_task_background worker failure path (success=False)
- 201: _run_task_background cleanup for task with issue_id=None
- 203-204: _run_task_background cleanup DB exception
- 232-240: _crash_recovery container cleanup (WORKER_CONTAINER_PATTERN, running/exited)
- 273-274: start_scheduler() module-level helper
- 279-280: stop_scheduler() module-level helper
"""

import asyncio
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from app.models import TaskStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_task(
    task_id: int = 1,
    project_id: int = 100,
    issue_id: int | None = 10,
    status: str = "pending",
) -> MagicMock:
    """Return a lightweight mock Task object."""
    task = MagicMock()
    task.id = task_id
    task.project_id = project_id
    task.issue_id = issue_id
    task.status = status
    task.started_at = None
    task.error_message = None
    task.completed_at = None
    task.is_retry = False
    task.retry_source_task_id = None
    return task


# ---------------------------------------------------------------------------
# start() — lines 44-61
# ---------------------------------------------------------------------------

class TestSchedulerStart(unittest.IsolatedAsyncioTestCase):
    """Tests for Scheduler.start() to cover crash recovery + main loop."""

    async def test_start_runs_crash_recovery_then_cycles(self) -> None:
        """start() should call _crash_recovery once, then _run_cycle each iteration."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        # Allow exactly two iterations before stopping.
        cycle_count = 0

        async def fake_run_cycle() -> None:
            nonlocal cycle_count
            cycle_count += 1
            if cycle_count >= 2:
                scheduler.running = False

        with patch.object(scheduler, "_crash_recovery", new_callable=AsyncMock) as mock_recovery, \
             patch.object(scheduler, "_run_cycle", side_effect=fake_run_cycle) as mock_cycle, \
             patch("app.scheduler.get_settings") as mock_settings, \
             patch("app.scheduler.asyncio.sleep", new_callable=AsyncMock):
            mock_settings.return_value = MagicMock(scheduler_interval=0)
            await scheduler.start()

        mock_recovery.assert_awaited_once()
        self.assertEqual(mock_cycle.await_count, 2)
        self.assertFalse(scheduler.running)  # loop exited

    async def test_start_continues_when_crash_recovery_raises(self) -> None:
        """start() should log + continue when _crash_recovery raises."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        async def stop_immediately() -> None:
            scheduler.running = False

        with patch.object(scheduler, "_crash_recovery", new_callable=AsyncMock,
                          side_effect=RuntimeError("docker down")) as mock_recovery, \
             patch.object(scheduler, "_run_cycle", side_effect=stop_immediately) as mock_cycle, \
             patch("app.scheduler.get_settings") as mock_settings, \
             patch("app.scheduler.asyncio.sleep", new_callable=AsyncMock):
            mock_settings.return_value = MagicMock(scheduler_interval=0)
            await scheduler.start()

        # Recovery raised but the loop still entered _run_cycle.
        mock_recovery.assert_awaited_once()
        mock_cycle.assert_awaited_once()

    async def test_start_logs_and_continues_when_run_cycle_raises(self) -> None:
        """start() should catch exceptions in _run_cycle and continue looping."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        call_count = 0

        async def failing_then_stop() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("DB connection lost")
            scheduler.running = False

        with patch.object(scheduler, "_crash_recovery", new_callable=AsyncMock), \
             patch.object(scheduler, "_run_cycle", side_effect=failing_then_stop), \
             patch("app.scheduler.get_settings") as mock_settings, \
             patch("app.scheduler.asyncio.sleep", new_callable=AsyncMock):
            mock_settings.return_value = MagicMock(scheduler_interval=0)
            await scheduler.start()

        # Loop ran twice: first raised, second stopped.
        self.assertEqual(call_count, 2)


# ---------------------------------------------------------------------------
# _run_cycle — line 95 (manual task branch)
# ---------------------------------------------------------------------------

class TestRunCycleManualTask(unittest.IsolatedAsyncioTestCase):
    """Tests for _run_cycle when the task has issue_id=None (skips mutex)."""

    async def test_run_cycle_skips_mutex_for_null_issue_id(self) -> None:
        """Task with issue_id=None should skip the issue mutex and call _execute_task."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        task = _make_mock_task(task_id=42, issue_id=None)

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db), \
             patch("app.scheduler.load_runtime_config_from_db", new_callable=AsyncMock), \
             patch.object(scheduler, "_maybe_cleanup_sessions", new_callable=AsyncMock), \
             patch("app.scheduler.get_settings") as mock_settings, \
             patch.object(scheduler, "_get_running_count", new_callable=AsyncMock, return_value=0), \
             patch.object(scheduler, "_get_next_task", new_callable=AsyncMock, return_value=task), \
             patch.object(scheduler, "_execute_task", new_callable=AsyncMock) as mock_exec:
            mock_settings.return_value = MagicMock(max_concurrency=5)
            await scheduler._run_cycle()

        # _execute_task should be called with (db, task) — no issue_key arg
        mock_exec.assert_awaited_once()
        args = mock_exec.await_args.args
        self.assertEqual(args[1], task)  # second arg is the task


# ---------------------------------------------------------------------------
# _run_task_background — lines 182, 201, 203-204
# ---------------------------------------------------------------------------

class TestRunTaskBackground(unittest.IsolatedAsyncioTestCase):
    """Tests for _run_task_background covering failure and cleanup paths."""

    async def test_background_logs_error_when_worker_returns_false(self) -> None:
        """Line 182: if success is False, an error should be logged."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._running_tasks.add(7)
        scheduler._running_issues.add(10)

        # Build a mock Task with issue_id set
        mock_task = _make_mock_task(task_id=7, project_id=100, issue_id=10)

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_task

        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.scheduler._worker_executor") as mock_executor, \
             patch("app.scheduler.AsyncSessionLocal", return_value=mock_db), \
             patch("app.scheduler._run_worker_task", return_value=False):

            loop = asyncio.get_event_loop()
            with patch.object(loop, "run_in_executor", new_callable=AsyncMock, return_value=False):
                await scheduler._run_task_background(7)

        # Task and issue should be cleaned up
        self.assertNotIn(7, scheduler._running_tasks)
        self.assertNotIn(10, scheduler._running_issues)

    async def test_background_cleanup_for_null_issue_id(self) -> None:
        """Tasks with issue_id=None don't add to _running_issues, only _running_tasks."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._running_tasks.add(55)

        mock_task = _make_mock_task(task_id=55, project_id=100, issue_id=None)

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_task
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db):
            loop = asyncio.get_event_loop()
            with patch.object(loop, "run_in_executor", new_callable=AsyncMock, return_value=True):
                await scheduler._run_task_background(55)

        self.assertNotIn(55, scheduler._running_tasks)
        self.assertEqual(len(scheduler._running_issues), 0)

    async def test_background_cleanup_handles_db_exception(self) -> None:
        """Lines 203-204: DB exception during cleanup should be silently caught."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._running_tasks.add(99)

        # Make AsyncSessionLocal raise during __aenter__
        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(side_effect=RuntimeError("DB gone"))
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db):
            loop = asyncio.get_event_loop()
            with patch.object(loop, "run_in_executor", new_callable=AsyncMock, return_value=True):
                # Should NOT raise
                await scheduler._run_task_background(99)

        # Task cleaned up even though DB lookup failed
        self.assertNotIn(99, scheduler._running_tasks)

    async def test_background_handles_executor_exception(self) -> None:
        """_run_task_background should handle exceptions from run_in_executor."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._running_tasks.add(88)
        scheduler._running_issues.add(10)

        mock_task = _make_mock_task(task_id=88, project_id=100, issue_id=10)

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_task
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db):
            loop = asyncio.get_event_loop()
            with patch.object(loop, "run_in_executor", new_callable=AsyncMock,
                              side_effect=RuntimeError("thread pool boom")):
                await scheduler._run_task_background(88)

        self.assertNotIn(88, scheduler._running_tasks)
        self.assertNotIn(10, scheduler._running_issues)


# ---------------------------------------------------------------------------
# _crash_recovery — lines 232-240 (container pattern matching + cleanup)
# ---------------------------------------------------------------------------

class TestCrashRecoveryContainers(unittest.IsolatedAsyncioTestCase):
    """Tests for _crash_recovery container cleanup logic."""

    def _make_container(self, name: str, status: str = "exited") -> MagicMock:
        c = MagicMock()
        c.name = name
        c.status = status
        c.remove = MagicMock()
        return c

    async def test_crash_recovery_removes_running_worker_containers(self) -> None:
        """Line 237-238: running worker containers should be force-removed."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        running_worker = self._make_container("codify-1-issue10", status="running")
        exited_worker = self._make_container("codify-2-issue20", status="exited")

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [running_worker, exited_worker]

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()

        # No stuck tasks
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db), \
             patch("app.scheduler.get_docker_client", return_value=mock_docker):
            await scheduler._crash_recovery()

        running_worker.remove.assert_called_once_with(force=True)
        exited_worker.remove.assert_called_once_with(force=False)

    async def test_crash_recovery_skips_non_worker_containers(self) -> None:
        """Line 232-233: containers that don't match WORKER_CONTAINER_PATTERN are skipped."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        # Service containers should be ignored
        backend = self._make_container("codify-backend", status="running")
        postgres = self._make_container("codify-postgres", status="running")
        # Valid worker container
        worker = self._make_container("codify-5-issue300", status="exited")

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [backend, postgres, worker]

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db), \
             patch("app.scheduler.get_docker_client", return_value=mock_docker):
            await scheduler._crash_recovery()

        backend.remove.assert_not_called()
        postgres.remove.assert_not_called()
        worker.remove.assert_called_once_with(force=False)  # exited → normal remove

    async def test_crash_recovery_marks_stuck_tasks_as_failed(self) -> None:
        """Stuck RUNNING tasks should be marked FAILED with an error message."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        stuck_task = _make_mock_task(task_id=10, status="running")

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stuck_task]
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = []

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db), \
             patch("app.scheduler.get_docker_client", return_value=mock_docker):
            await scheduler._crash_recovery()

        self.assertEqual(stuck_task.status, TaskStatus.FAILED)
        self.assertIn("container not found", stuck_task.error_message)
        self.assertIsNotNone(stuck_task.completed_at)
        mock_db.commit.assert_awaited_once()

    async def test_crash_recovery_continues_when_docker_fails(self) -> None:
        """Container cleanup failure should not prevent stuck-task recovery."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        stuck_task = _make_mock_task(task_id=11, status="running")

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stuck_task]
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db), \
             patch("app.scheduler.get_docker_client", side_effect=RuntimeError("no docker")):
            await scheduler._crash_recovery()

        # Stuck tasks should still be marked as failed
        self.assertEqual(stuck_task.status, TaskStatus.FAILED)
        mock_db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# _crash_recovery — smart recovery (resume / orphan cleanup / _extract_task_id)
# ---------------------------------------------------------------------------

class TestSmartCrashRecovery(unittest.IsolatedAsyncioTestCase):
    """Tests for the smart crash recovery behaviour (resume vs kill)."""

    def _make_container(self, name: str, status: str = "exited") -> MagicMock:
        c = MagicMock()
        c.name = name
        c.status = status
        c.remove = MagicMock()
        return c

    async def test_crash_recovery_resumes_legitimate_running_tasks(self) -> None:
        """A RUNNING task whose container is still running should be resumed, not failed."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        # RUNNING task id=42 in DB
        stuck_task = _make_mock_task(task_id=42, project_id=100, issue_id=10, status="running")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stuck_task]

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Running container whose name maps to task 42
        running_container = self._make_container("codify-42-issue10", status="running")

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [running_container]

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db), \
             patch("app.scheduler.get_docker_client", return_value=mock_docker), \
             patch.object(scheduler, "_resume_task_background", new=MagicMock()) as mock_resume, \
             patch("app.scheduler.asyncio.create_task") as mock_create_task:
            await scheduler._crash_recovery()

        # Task should NOT be marked failed
        self.assertNotEqual(stuck_task.status, TaskStatus.FAILED)
        # Container should NOT be removed
        running_container.remove.assert_not_called()
        # _resume_task_background should have been called with the task/container
        mock_resume.assert_called_once_with(42, "codify-42-issue10")
        # asyncio.create_task should have been called to schedule the resume
        mock_create_task.assert_called_once()
        # Task should be tracked as running
        self.assertIn(42, scheduler._running_tasks)
        self.assertIn(10, scheduler._running_issues)

    async def test_crash_recovery_resumes_task_with_issue_id(self) -> None:
        """A RUNNING task with issue_id should be resumed and tracked in _running_issues."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        stuck_task = _make_mock_task(task_id=7, project_id=200, issue_id=200, status="running")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stuck_task]

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        container = self._make_container("codify-7-issue200", status="running")

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [container]

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db), \
             patch("app.scheduler.get_docker_client", return_value=mock_docker), \
             patch.object(scheduler, "_resume_task_background", new=MagicMock()), \
             patch("app.scheduler.asyncio.create_task"):
            await scheduler._crash_recovery()

        self.assertNotEqual(stuck_task.status, TaskStatus.FAILED)
        container.remove.assert_not_called()
        self.assertIn(7, scheduler._running_tasks)
        self.assertIn(200, scheduler._running_issues)

    async def test_crash_recovery_kills_orphan_running_containers(self) -> None:
        """A running container with no matching RUNNING task should be force-removed."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        # No stuck tasks in DB
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Orphan running container (task_id=99 not in DB)
        orphan = self._make_container("codify-99-issue10", status="running")

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [orphan]

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db), \
             patch("app.scheduler.get_docker_client", return_value=mock_docker):
            await scheduler._crash_recovery()

        orphan.remove.assert_called_once_with(force=True)

    async def test_crash_recovery_mixed_resume_and_fail(self) -> None:
        """Tasks with containers are resumed; tasks without containers are failed."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        task_with_container = _make_mock_task(task_id=10, project_id=100, issue_id=5, status="running")
        task_without_container = _make_mock_task(task_id=20, project_id=200, issue_id=15, status="running")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [task_with_container, task_without_container]

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Only task 10 has a running container
        container_10 = self._make_container("codify-10-issue5", status="running")

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [container_10]

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db), \
             patch("app.scheduler.get_docker_client", return_value=mock_docker), \
             patch.object(scheduler, "_resume_task_background", new=MagicMock()), \
             patch("app.scheduler.asyncio.create_task"):
            await scheduler._crash_recovery()

        # Task 10 should be resumed, not failed
        self.assertNotEqual(task_with_container.status, TaskStatus.FAILED)
        container_10.remove.assert_not_called()
        self.assertIn(10, scheduler._running_tasks)

        # Task 20 should be failed (no container)
        self.assertEqual(task_without_container.status, TaskStatus.FAILED)
        self.assertIn("container not found", task_without_container.error_message)
        self.assertIsNotNone(task_without_container.completed_at)

    async def test_crash_recovery_exited_container_with_running_task(self) -> None:
        """An exited container for a RUNNING task should be RESUMED (not removed).

        The worker's resume_task handles exited containers by collecting logs
        and processing results, so crash recovery should resume them just like
        running containers.
        """
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        stuck_task = _make_mock_task(task_id=50, project_id=300, issue_id=1, status="running")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stuck_task]

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Container for task 50 exists but is exited
        exited_container = self._make_container("codify-50-issue1", status="exited")

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [exited_container]

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db), \
             patch("app.scheduler.get_docker_client", return_value=mock_docker), \
             patch.object(scheduler, "_resume_task_background", new=MagicMock()), \
             patch("app.scheduler.asyncio.create_task") as mock_create_task:
            await scheduler._crash_recovery()

        # Container should NOT be removed — it's being resumed
        exited_container.remove.assert_not_called()
        # Task should be tracked for resume, NOT marked failed
        self.assertIn(50, scheduler._running_tasks)
        self.assertIn(1, scheduler._running_issues)
        # asyncio.create_task should have been called to resume
        mock_create_task.assert_called_once()

    async def test_crash_recovery_dead_container_with_running_task(self) -> None:
        """A 'dead' container for a RUNNING task should be removed and task marked failed."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        stuck_task = _make_mock_task(task_id=60, project_id=400, issue_id=2, status="running")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stuck_task]

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        dead_container = self._make_container("codify-60-issue2", status="dead")

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [dead_container]

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db), \
             patch("app.scheduler.get_docker_client", return_value=mock_docker):
            await scheduler._crash_recovery()

        # Dead container should be force-removed
        dead_container.remove.assert_called_once_with(force=True)
        # Task should be marked failed (no resume for dead containers)
        self.assertEqual(stuck_task.status, TaskStatus.FAILED)
        self.assertIn("container not found", stuck_task.error_message)


class TestExtractTaskId(unittest.TestCase):
    """Tests for the _extract_task_id() helper function."""

    def test_standard_issue_container(self) -> None:
        """codify-123-issue789 → 123."""
        from app.scheduler import _extract_task_id
        self.assertEqual(_extract_task_id("codify-123-issue789"), 123)

    def test_another_issue_container(self) -> None:
        """codify-1-issue2 → 1."""
        from app.scheduler import _extract_task_id
        self.assertEqual(_extract_task_id("codify-1-issue2"), 1)

    def test_service_container_returns_none(self) -> None:
        """codify-backend → None (not a worker container)."""
        from app.scheduler import _extract_task_id
        self.assertIsNone(_extract_task_id("codify-backend"))

    def test_invalid_name_returns_none(self) -> None:
        """Completely unrelated name → None."""
        from app.scheduler import _extract_task_id
        self.assertIsNone(_extract_task_id("invalid"))

    def test_partial_match_returns_none(self) -> None:
        """codify-1-p100-other → None (invalid suffix)."""
        from app.scheduler import _extract_task_id
        self.assertIsNone(_extract_task_id("codify-1-p100-other"))

    def test_large_ids(self) -> None:
        """Large numeric IDs should be extracted correctly."""
        from app.scheduler import _extract_task_id
        self.assertEqual(_extract_task_id("codify-99999-issue77777"), 99999)


# ---------------------------------------------------------------------------
# Module-level helpers — lines 273-274, 279-280
# ---------------------------------------------------------------------------

class TestModuleLevelHelpers(unittest.IsolatedAsyncioTestCase):
    """Tests for start_scheduler() and stop_scheduler() module functions."""

    async def test_start_scheduler_delegates_to_singleton(self) -> None:
        """start_scheduler() should call get_scheduler().start()."""
        from app import scheduler as scheduler_module

        mock_scheduler = MagicMock()
        mock_scheduler.start = AsyncMock()

        with patch.object(scheduler_module, "get_scheduler", return_value=mock_scheduler):
            await scheduler_module.start_scheduler()

        mock_scheduler.start.assert_awaited_once()

    async def test_stop_scheduler_delegates_when_instance_exists(self) -> None:
        """stop_scheduler() should call _scheduler.stop() when it exists."""
        from app import scheduler as scheduler_module

        mock_scheduler = MagicMock()
        mock_scheduler.stop = AsyncMock()

        original = scheduler_module._scheduler
        try:
            scheduler_module._scheduler = mock_scheduler
            await scheduler_module.stop_scheduler()
            mock_scheduler.stop.assert_awaited_once()
        finally:
            scheduler_module._scheduler = original

    async def test_stop_scheduler_noop_when_no_instance(self) -> None:
        """stop_scheduler() should do nothing when _scheduler is None."""
        from app import scheduler as scheduler_module

        original = scheduler_module._scheduler
        try:
            scheduler_module._scheduler = None
            # Should not raise
            await scheduler_module.stop_scheduler()
        finally:
            scheduler_module._scheduler = original


# ---------------------------------------------------------------------------
# WORKER_CONTAINER_PATTERN regex — line 30
# ---------------------------------------------------------------------------

class TestWorkerContainerPattern(unittest.TestCase):
    """Tests for the WORKER_CONTAINER_PATTERN regex."""

    def test_matches_issue_container(self) -> None:
        from app.scheduler import WORKER_CONTAINER_PATTERN
        self.assertIsNotNone(WORKER_CONTAINER_PATTERN.match("codify-1-issue10"))

    def test_matches_another_issue_container(self) -> None:
        from app.scheduler import WORKER_CONTAINER_PATTERN
        self.assertIsNotNone(WORKER_CONTAINER_PATTERN.match("codify-42-issue200"))

    def test_rejects_service_container(self) -> None:
        from app.scheduler import WORKER_CONTAINER_PATTERN
        self.assertIsNone(WORKER_CONTAINER_PATTERN.match("codify-backend"))
        self.assertIsNone(WORKER_CONTAINER_PATTERN.match("codify-postgres"))

    def test_rejects_partial_match(self) -> None:
        from app.scheduler import WORKER_CONTAINER_PATTERN
        self.assertIsNone(WORKER_CONTAINER_PATTERN.match("codify-1-p100-other"))


# ---------------------------------------------------------------------------
# _execute_task — exception path
# ---------------------------------------------------------------------------

class TestExecuteTask(unittest.IsolatedAsyncioTestCase):
    """Tests for _execute_task exception handling."""

    async def test_execute_task_marks_failed_on_commit_error(self) -> None:
        """If db.commit() raises during status update, task should be marked FAILED."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        task = _make_mock_task(task_id=77, issue_id=10)

        mock_db = MagicMock()
        mock_db.commit = AsyncMock(side_effect=[RuntimeError("DB error"), AsyncMock()])

        await scheduler._execute_task(mock_db, task)

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIsNotNone(task.error_message)
        self.assertNotIn(77, scheduler._running_tasks)
        self.assertNotIn(10, scheduler._running_issues)


# ---------------------------------------------------------------------------
# _crash_recovery — lines 287-288 (dead container remove() raises)
# ---------------------------------------------------------------------------

class TestCrashRecoveryContainerRemoveFailures(unittest.IsolatedAsyncioTestCase):
    """Tests for container.remove() failure paths during crash recovery."""

    def _make_container(self, name: str, status: str = "exited") -> MagicMock:
        c = MagicMock()
        c.name = name
        c.status = status
        c.remove = MagicMock()
        return c

    async def test_dead_container_remove_failure_is_caught(self) -> None:
        """Lines 287-288: when removing a dead container raises, recovery should continue."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        # Task 60 in RUNNING state in DB
        stuck_task = _make_mock_task(task_id=60, project_id=400, issue_id=2, status="running")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stuck_task]

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Container in "dead" state — remove() will raise
        dead_container = self._make_container("codify-60-issue2", status="dead")
        dead_container.remove.side_effect = RuntimeError("Cannot remove dead container")

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [dead_container]

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db), \
             patch("app.scheduler.get_docker_client", return_value=mock_docker):
            # Should NOT raise — exception is caught and logged
            await scheduler._crash_recovery()

        dead_container.remove.assert_called_once_with(force=True)
        # Task should still be marked failed (no container resumed it)
        self.assertEqual(stuck_task.status, TaskStatus.FAILED)

    async def test_orphan_container_remove_failure_is_caught(self) -> None:
        """Lines 297-298: when removing an orphan container raises, recovery should continue."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        # No stuck tasks in DB
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Orphan container whose remove() raises
        orphan = self._make_container("codify-99-issue10", status="running")
        orphan.remove.side_effect = RuntimeError("Container in use by another process")

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [orphan]

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db), \
             patch("app.scheduler.get_docker_client", return_value=mock_docker):
            # Should NOT raise
            await scheduler._crash_recovery()

        orphan.remove.assert_called_once_with(force=True)

    async def test_orphan_exited_container_remove_failure_is_caught(self) -> None:
        """Lines 297-298: orphan exited container remove failure is safely caught."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        orphan = self._make_container("codify-77-issue200", status="exited")
        orphan.remove.side_effect = RuntimeError("Filesystem busy")

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [orphan]

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db), \
             patch("app.scheduler.get_docker_client", return_value=mock_docker):
            await scheduler._crash_recovery()

        # Exited orphan: force=False (c_status != "running")
        orphan.remove.assert_called_once_with(force=False)


# ---------------------------------------------------------------------------
# _resume_task_background — lines 323-352
# ---------------------------------------------------------------------------

class TestResumeTaskBackground(unittest.IsolatedAsyncioTestCase):
    """Tests for _resume_task_background covering all paths."""

    async def test_resume_success_cleans_up_tracking(self) -> None:
        """Lines 323-332: successful resume returns True, tracking cleaned up."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._running_tasks.add(42)
        scheduler._running_issues.add(10)

        mock_task = _make_mock_task(task_id=42, project_id=100, issue_id=10)

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_task
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db):
            loop = asyncio.get_event_loop()
            with patch.object(loop, "run_in_executor", new_callable=AsyncMock, return_value=True):
                await scheduler._resume_task_background(42, "codify-42-issue10")

        self.assertNotIn(42, scheduler._running_tasks)
        self.assertNotIn(10, scheduler._running_issues)

    async def test_resume_failure_returns_false(self) -> None:
        """Lines 333-334: when resume returns False, error is logged and tracking cleaned."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._running_tasks.add(43)
        scheduler._running_issues.add(20)

        mock_task = _make_mock_task(task_id=43, project_id=200, issue_id=20)

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_task
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db):
            loop = asyncio.get_event_loop()
            with patch.object(loop, "run_in_executor", new_callable=AsyncMock, return_value=False):
                await scheduler._resume_task_background(43, "codify-43-issue20")

        self.assertNotIn(43, scheduler._running_tasks)
        self.assertNotIn(20, scheduler._running_issues)

    async def test_resume_exception_cleans_up_tracking(self) -> None:
        """Lines 335-336: executor exception during resume is caught, tracking cleaned."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._running_tasks.add(44)
        scheduler._running_issues.add(30)

        mock_task = _make_mock_task(task_id=44, project_id=300, issue_id=30)

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_task
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db):
            loop = asyncio.get_event_loop()
            with patch.object(loop, "run_in_executor", new_callable=AsyncMock,
                              side_effect=RuntimeError("thread pool crashed")):
                await scheduler._resume_task_background(44, "codify-44-issue30")

        self.assertNotIn(44, scheduler._running_tasks)
        self.assertNotIn(30, scheduler._running_issues)

    async def test_resume_task_with_issue_id_cleans_up(self) -> None:
        """Task with issue_id cleans up _running_issues with the int issue_id."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._running_tasks.add(55)
        scheduler._running_issues.add(100)

        mock_task = _make_mock_task(task_id=55, project_id=100, issue_id=100)

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_task
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db):
            loop = asyncio.get_event_loop()
            with patch.object(loop, "run_in_executor", new_callable=AsyncMock, return_value=True):
                await scheduler._resume_task_background(55, "codify-55-issue100")

        self.assertNotIn(55, scheduler._running_tasks)
        self.assertNotIn(100, scheduler._running_issues)

    async def test_resume_db_cleanup_failure_is_caught(self) -> None:
        """Lines 351-352: DB exception during cleanup in finally block is silently caught."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._running_tasks.add(66)

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(side_effect=RuntimeError("DB connection lost"))
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db):
            loop = asyncio.get_event_loop()
            with patch.object(loop, "run_in_executor", new_callable=AsyncMock, return_value=True):
                # Should NOT raise
                await scheduler._resume_task_background(66, "codify-66-issue5")

        # Task cleaned up even though DB lookup failed
        self.assertNotIn(66, scheduler._running_tasks)

    async def test_resume_task_not_found_in_db(self) -> None:
        """Lines 345-350: task not found in DB during cleanup — no issue_key to discard."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._running_tasks.add(77)

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # task not found
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db):
            loop = asyncio.get_event_loop()
            with patch.object(loop, "run_in_executor", new_callable=AsyncMock, return_value=True):
                await scheduler._resume_task_background(77, "codify-77-issue5")

        self.assertNotIn(77, scheduler._running_tasks)


# ---------------------------------------------------------------------------
# _run_worker_resume_task — lines 441-476
# ---------------------------------------------------------------------------

class TestRunWorkerResumeTask(unittest.TestCase):
    """Tests for the module-level _run_worker_resume_task() function.

    The function uses local imports so we patch at the *source* modules:
    - app.database._database_url
    - sqlalchemy.ext.asyncio.create_async_engine
    - sqlalchemy.ext.asyncio.async_sessionmaker
    - app.core.worker.WorkerExecutor
    """

    def _run_with_mocks(self, resume_return_value=True):
        """Helper: run _run_worker_resume_task with all imports mocked."""
        from app.scheduler import _run_worker_resume_task

        mock_worker = MagicMock()
        mock_worker.resume_task = AsyncMock(return_value=resume_return_value)

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        with patch("app.database._database_url", "sqlite+aiosqlite:///:memory:"), \
             patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine), \
             patch("sqlalchemy.ext.asyncio.async_sessionmaker") as mock_sm, \
             patch("app.core.worker.WorkerExecutor", return_value=mock_worker):
            mock_sm.return_value = MagicMock(return_value=mock_db)
            result = _run_worker_resume_task(42, "codify-42-issue10")

        return result, mock_worker, mock_engine

    def test_run_worker_resume_task_success(self) -> None:
        """Lines 441-476: successful resume returns True."""
        result, mock_worker, _ = self._run_with_mocks(resume_return_value=True)
        self.assertTrue(result)
        mock_worker.resume_task.assert_awaited_once()

    def test_run_worker_resume_task_failure(self) -> None:
        """_run_worker_resume_task returns False when worker returns False."""
        result, _, _ = self._run_with_mocks(resume_return_value=False)
        self.assertFalse(result)

    def test_run_worker_resume_task_disposes_engine(self) -> None:
        """Engine should be disposed in the finally block even on success."""
        _, _, mock_engine = self._run_with_mocks(resume_return_value=True)
        mock_engine.dispose.assert_called_once()


if __name__ == "__main__":
    unittest.main()
