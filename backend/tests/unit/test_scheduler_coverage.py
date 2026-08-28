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
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from app.models import TaskStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_task(
    task_id: int = 1,
    project_id: int = 100,
    issue_id: int | None = 10,
    status: str = "pending",
    task_mode: str = "execute",
) -> MagicMock:
    """Return a lightweight mock Task object."""
    task = MagicMock()
    task.id = task_id
    task.project_id = project_id
    task.issue_id = issue_id
    task.status = status
    task.task_mode = task_mode
    task.started_at = None
    task.error_message = None
    task.completed_at = None
    task.is_retry = False
    task.retry_source_task_id = None
    task.runtime_bundle = MagicMock(
        contract_version="codify.worker.harness/v1",
        digest="a" * 64,
        manifest={"adapters": {"claude": {}}},
    )
    task.worker_profile_snapshot = MagicMock(
        runtime_contract_version="codify.worker.harness/v1",
        runtime_bundle_digest="a" * 64,
        harness_key="claude",
    )
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

        with (
            patch.object(scheduler, "_crash_recovery", new_callable=AsyncMock) as mock_recovery,
            patch.object(scheduler, "_run_cycle", side_effect=fake_run_cycle) as mock_cycle,
            patch("app.scheduler.get_settings") as mock_settings,
            patch("app.scheduler.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.return_value = MagicMock(scheduler_interval=0)
            await scheduler.start()

        mock_recovery.assert_awaited_once()
        self.assertEqual(mock_cycle.await_count, 2)
        self.assertFalse(scheduler.running)  # loop exited

    async def test_start_retries_before_dispatch_when_crash_recovery_raises(self) -> None:
        """start() must not dispatch until the startup ownership audit succeeds."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        async def stop_immediately() -> None:
            scheduler.running = False

        with (
            patch.object(
                scheduler,
                "_crash_recovery",
                new_callable=AsyncMock,
                side_effect=[RuntimeError("docker down"), None],
            ) as mock_recovery,
            patch.object(scheduler, "_run_cycle", side_effect=stop_immediately) as mock_cycle,
            patch("app.scheduler.get_settings") as mock_settings,
            patch("app.scheduler.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.return_value = MagicMock(scheduler_interval=0)
            await scheduler.start()

        self.assertEqual(mock_recovery.await_count, 2)
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

        with (
            patch.object(scheduler, "_crash_recovery", new_callable=AsyncMock),
            patch.object(scheduler, "_run_cycle", side_effect=failing_then_stop),
            patch("app.scheduler.get_settings") as mock_settings,
            patch("app.scheduler.asyncio.sleep", new_callable=AsyncMock),
        ):
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
        with (
            patch("app.scheduler.AsyncSessionLocal", return_value=mock_db),
            patch("app.scheduler.refresh_runtime_config_if_stale", new_callable=AsyncMock),
            patch.object(scheduler, "_maybe_cleanup_sessions", new_callable=AsyncMock),
            patch.object(scheduler, "_maybe_cleanup_workspaces", new_callable=AsyncMock),
            patch.object(scheduler, "_maybe_cleanup_retained_containers", new_callable=AsyncMock),
            patch.object(scheduler, "_maybe_cleanup_issue_locks", new_callable=AsyncMock),
            patch.object(scheduler, "_reconcile_running_state", new_callable=AsyncMock),
            patch.object(scheduler, "_mark_eligible_as_queued", new_callable=AsyncMock),
            patch("app.scheduler.get_settings") as mock_settings,
            patch.object(scheduler, "_get_running_count", new_callable=AsyncMock, return_value=0),
            patch.object(scheduler, "_get_next_task", new_callable=AsyncMock, return_value=task),
            patch.object(scheduler, "_execute_task", new_callable=AsyncMock) as mock_exec,
        ):
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
        mock_db.commit = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.side_effect = [mock_task, None]

        mock_db.execute = AsyncMock(return_value=mock_result)

        with (
            patch("app.scheduler._worker_executor"),
            patch("app.scheduler.AsyncSessionLocal", return_value=mock_db),
            patch("app.scheduler._run_worker_task", return_value=False),
        ):
            loop = asyncio.get_event_loop()
            with patch.object(loop, "run_in_executor", new_callable=AsyncMock, return_value=False):
                await scheduler._run_task_background(7)

        # Task and issue should be cleaned up
        self.assertNotIn(7, scheduler._running_tasks)
        self.assertNotIn(10, scheduler._running_issues)

    async def test_background_keeps_issue_locked_for_retained_container(self) -> None:
        """A terminal worker cannot release its Issue before container reconciliation."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._running_tasks.add(8)
        scheduler._running_issues.add(11)
        task = _make_mock_task(
            task_id=8,
            project_id=100,
            issue_id=11,
            status=TaskStatus.FAILED,
        )
        task.container_id = "container-8"
        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task
        lock_result = MagicMock()
        lock_result.scalar_one_or_none.return_value = MagicMock(task_id=8)
        db = MagicMock()
        db.__aenter__ = AsyncMock(return_value=db)
        db.__aexit__ = AsyncMock(return_value=False)
        db.execute = AsyncMock(side_effect=[task_result, lock_result])
        db.commit = AsyncMock()

        with (
            patch("app.scheduler.AsyncSessionLocal", return_value=db),
            patch(
                "app.scheduler.release_issue_execution_lock",
                new=AsyncMock(),
            ) as release_lock,
            patch.object(
                asyncio.get_event_loop(),
                "run_in_executor",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            await scheduler._run_task_background(8)

        self.assertNotIn(8, scheduler._running_tasks)
        self.assertIn(11, scheduler._running_issues)
        self.assertIn(11, scheduler._retained_container_blocked_issues)
        release_lock.assert_not_awaited()

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

        mock_task = _make_mock_task(
            task_id=88,
            project_id=100,
            issue_id=10,
            status=TaskStatus.RUNNING,
        )

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.side_effect = [mock_task, None]
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db):
            loop = asyncio.get_event_loop()
            with patch.object(
                loop,
                "run_in_executor",
                new_callable=AsyncMock,
                side_effect=RuntimeError("thread pool boom"),
            ):
                await scheduler._run_task_background(88)

        self.assertNotIn(88, scheduler._running_tasks)
        self.assertNotIn(10, scheduler._running_issues)

    async def test_background_lookup_error_starts_deferred_recovery(self) -> None:
        """An ambiguous startup keeps ownership until Docker recovery can inspect it."""
        from app.core.worker_docker_targets import TaskContainerLookupError
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._running_tasks.add(89)
        scheduler._running_issues.add(11)
        current = asyncio.current_task()
        assert current is not None
        scheduler._worker_tasks[89] = current
        replacement = MagicMock()
        scheduled_coroutines = []

        def capture_task(coroutine):
            scheduled_coroutines.append(coroutine)
            coroutine.close()
            return replacement

        with (
            patch.object(
                asyncio.get_event_loop(),
                "run_in_executor",
                new_callable=AsyncMock,
                side_effect=TaskContainerLookupError("start outcome unknown"),
            ),
            patch.object(
                scheduler,
                "_mark_worker_bootstrap_failed",
                new_callable=AsyncMock,
            ) as mark_failed,
            patch("app.scheduler.asyncio.create_task", side_effect=capture_task),
        ):
            await scheduler._run_task_background(89)

        self.assertEqual(len(scheduled_coroutines), 1)
        self.assertIs(scheduler._worker_tasks[89], replacement)
        self.assertIn(89, scheduler._running_tasks)
        self.assertIn(11, scheduler._running_issues)
        mark_failed.assert_not_awaited()


# ---------------------------------------------------------------------------
# Retained terminal-container cleanup
# ---------------------------------------------------------------------------


class TestRetainedContainerCleanup(unittest.IsolatedAsyncioTestCase):
    async def test_reconcile_discovers_terminal_container_from_database(self) -> None:
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        retained_result = MagicMock()
        retained_result.fetchall.return_value = [(12,)]
        db = MagicMock()
        db.execute = AsyncMock(return_value=retained_result)

        await scheduler._reconcile_retained_issue_blocks(db)

        self.assertIn(12, scheduler._retained_container_blocked_issues)
        self.assertIn(12, scheduler._running_issues)

    async def test_retained_issue_block_is_released_only_after_reference_clears(self) -> None:
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._retained_container_blocked_issues.add(12)
        scheduler._running_issues.add(12)
        retained_result = MagicMock()
        retained_result.fetchall.return_value = [(12,)]
        cleared_result = MagicMock()
        cleared_result.fetchall.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[retained_result, cleared_result])

        await scheduler._reconcile_retained_issue_blocks(db)
        self.assertIn(12, scheduler._retained_container_blocked_issues)
        self.assertIn(12, scheduler._running_issues)

        await scheduler._reconcile_retained_issue_blocks(db)
        self.assertNotIn(12, scheduler._retained_container_blocked_issues)

    async def test_clear_reference_keeps_block_when_another_container_prevents_release(
        self,
    ) -> None:
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._retained_container_blocked_issues.add(12)
        scheduler._running_issues.add(12)
        task = _make_mock_task(
            task_id=92,
            project_id=100,
            issue_id=12,
            status=TaskStatus.FAILED,
        )
        task.container_id = "container-92"
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(rowcount=0))
        db.commit = AsyncMock()

        await scheduler._clear_retained_container_reference(db, task)

        self.assertIsNone(task.container_id)
        self.assertIn(12, scheduler._retained_container_blocked_issues)
        self.assertIn(12, scheduler._running_issues)

    async def test_cleanup_finalizes_fallback_logs_then_removes_container(self) -> None:
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        task = _make_mock_task(
            task_id=90,
            project_id=100,
            issue_id=12,
            status=TaskStatus.FAILED,
        )
        task.container_id = "container-90"
        task.raw_logs_finalized_at = None

        candidate_result = MagicMock()
        candidate_result.scalars.return_value.all.return_value = [90]
        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task
        release_result = MagicMock(rowcount=1)
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[candidate_result, task_result, release_result])
        db.commit = AsyncMock()
        db.rollback = AsyncMock()

        docker = MagicMock()
        docker.read_file_from_container.return_value = None
        docker.get_container_logs.return_value = b"launcher failed\n"
        container = MagicMock()
        container.status = "running"
        scheduler._retained_container_blocked_issues.add(12)
        scheduler._running_issues.add(12)

        with (
            patch(
                "app.scheduler.find_task_container",
                new=AsyncMock(return_value=(docker, container, MagicMock())),
            ),
            patch(
                "app.scheduler.persist_raw_log_snapshot",
                new=AsyncMock(),
            ) as persist_snapshot,
        ):
            await scheduler._cleanup_retained_container_batch(db, MagicMock())

        persist_snapshot.assert_awaited_once_with(
            db,
            task_id=90,
            content=b"launcher failed\n",
        )
        self.assertIsNotNone(task.raw_logs_finalized_at)
        self.assertIsNone(task.container_id)
        container.stop.assert_called_once_with(timeout=10)
        container.remove.assert_called_once_with(force=True, v=True)
        self.assertEqual(db.commit.await_count, 2)
        self.assertNotIn(12, scheduler._retained_container_blocked_issues)
        self.assertNotIn(12, scheduler._running_issues)

    async def test_cleanup_clears_reference_when_container_is_confirmed_absent(self) -> None:
        from app.core.worker_docker_targets import TaskContainerNotFoundError
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        task = _make_mock_task(
            task_id=91,
            project_id=100,
            issue_id=12,
            status=TaskStatus.CANCELLED,
        )
        task.container_id = "container-91"
        task.raw_logs_finalized_at = None

        candidate_result = MagicMock()
        candidate_result.scalars.return_value.all.return_value = [91]
        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task
        release_result = MagicMock(rowcount=1)
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[candidate_result, task_result, release_result])
        db.commit = AsyncMock()
        db.rollback = AsyncMock()

        with patch(
            "app.scheduler.find_task_container",
            new=AsyncMock(side_effect=TaskContainerNotFoundError("gone")),
        ):
            await scheduler._cleanup_retained_container_batch(db, MagicMock())

        self.assertIsNone(task.container_id)
        self.assertIsNotNone(task.raw_logs_finalized_at)
        db.commit.assert_awaited_once()


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

        with (
            patch("app.scheduler.AsyncSessionLocal", return_value=mock_db),
            patch("app.scheduler._get_recovery_docker_client", return_value=mock_docker),
        ):
            await scheduler._crash_recovery()

        running_worker.remove.assert_called_once_with(force=True, v=True)
        exited_worker.remove.assert_called_once_with(force=False, v=True)

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

        with (
            patch("app.scheduler.AsyncSessionLocal", return_value=mock_db),
            patch("app.scheduler._get_recovery_docker_client", return_value=mock_docker),
        ):
            await scheduler._crash_recovery()

        backend.remove.assert_not_called()
        postgres.remove.assert_not_called()
        worker.remove.assert_called_once_with(force=False, v=True)  # exited → normal remove

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

        with (
            patch("app.scheduler.AsyncSessionLocal", return_value=mock_db),
            patch("app.scheduler._get_recovery_docker_client", return_value=mock_docker),
        ):
            await scheduler._crash_recovery()

        self.assertEqual(stuck_task.status, TaskStatus.FAILED)
        self.assertIn("container not found", stuck_task.error_message)
        self.assertIsNone(stuck_task.container_id)
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

        with (
            patch("app.scheduler.AsyncSessionLocal", return_value=mock_db),
            patch("app.scheduler._RECOVERY_RETRY_OFFSETS_SECONDS", (0, 0, 0)),
            patch(
                "app.scheduler._get_recovery_docker_client", side_effect=RuntimeError("no docker")
            ),
            patch.object(
                scheduler,
                "_coordinate_unavailable_recovery",
                new=MagicMock(return_value=object()),
            ),
            patch("app.scheduler.asyncio.create_task", return_value=MagicMock()),
            patch("app.scheduler.release_issue_execution_lock", new=AsyncMock()) as release_lock,
        ):
            await scheduler._crash_recovery()

        self.assertEqual(stuck_task.status, "running")
        self.assertIn(stuck_task.id, scheduler._running_tasks)
        release_lock.assert_not_awaited()
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

        with (
            patch("app.scheduler.AsyncSessionLocal", return_value=mock_db),
            patch("app.scheduler._get_recovery_docker_client", return_value=mock_docker),
            patch.object(scheduler, "_resume_task_background", new=MagicMock()) as mock_resume,
            patch("app.scheduler.asyncio.create_task") as mock_create_task,
        ):
            await scheduler._crash_recovery()

        # Task should NOT be marked failed
        self.assertNotEqual(stuck_task.status, TaskStatus.FAILED)
        # Container should NOT be removed
        running_container.remove.assert_not_called()
        # _resume_task_background should have been called with the task/container
        mock_resume.assert_called_once_with(42, "codify-42-issue10", ANY)
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

        with (
            patch("app.scheduler.AsyncSessionLocal", return_value=mock_db),
            patch("app.scheduler._get_recovery_docker_client", return_value=mock_docker),
            patch.object(scheduler, "_resume_task_background", new=MagicMock()),
            patch("app.scheduler.asyncio.create_task"),
        ):
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

        with (
            patch("app.scheduler.AsyncSessionLocal", return_value=mock_db),
            patch("app.scheduler._get_recovery_docker_client", return_value=mock_docker),
        ):
            await scheduler._crash_recovery()

        orphan.remove.assert_called_once_with(force=True, v=True)

    async def test_crash_recovery_mixed_resume_and_fail(self) -> None:
        """Tasks with containers are resumed; tasks without containers are failed."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        task_with_container = _make_mock_task(
            task_id=10, project_id=100, issue_id=5, status="running"
        )
        task_without_container = _make_mock_task(
            task_id=20, project_id=200, issue_id=15, status="running"
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            task_with_container,
            task_without_container,
        ]

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Only task 10 has a running container
        container_10 = self._make_container("codify-10-issue5", status="running")

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [container_10]

        with (
            patch("app.scheduler.AsyncSessionLocal", return_value=mock_db),
            patch("app.scheduler._get_recovery_docker_client", return_value=mock_docker),
            patch.object(scheduler, "_resume_task_background", new=MagicMock()),
            patch("app.scheduler.asyncio.create_task"),
        ):
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

        with (
            patch("app.scheduler.AsyncSessionLocal", return_value=mock_db),
            patch("app.scheduler._get_recovery_docker_client", return_value=mock_docker),
            patch.object(scheduler, "_resume_task_background", new=MagicMock()),
            patch("app.scheduler.asyncio.create_task") as mock_create_task,
        ):
            await scheduler._crash_recovery()

        # Container should NOT be removed — it's being resumed
        exited_container.remove.assert_not_called()
        # Task should be tracked for resume, NOT marked failed
        self.assertIn(50, scheduler._running_tasks)
        self.assertIn(1, scheduler._running_issues)
        # asyncio.create_task should have been called to resume
        mock_create_task.assert_called_once()

    async def test_crash_recovery_dead_container_with_running_task(self) -> None:
        """A dead worker remains owned until deferred recovery finalizes its logs."""
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

        with (
            patch("app.scheduler.AsyncSessionLocal", return_value=mock_db),
            patch("app.scheduler._get_recovery_docker_client", return_value=mock_docker),
            patch.object(
                scheduler,
                "_coordinate_unavailable_recovery",
                new=MagicMock(return_value=object()),
            ) as coordinate_recovery,
            patch("app.scheduler.asyncio.create_task", return_value=MagicMock()) as create_task,
        ):
            await scheduler._crash_recovery()

        dead_container.remove.assert_not_called()
        self.assertEqual(stuck_task.status, "running")
        self.assertIn(60, scheduler._running_tasks)
        self.assertIn(2, scheduler._running_issues)
        coordinate_recovery.assert_called_once_with(60)
        create_task.assert_called_once()


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
    """Tests for the _get_container_pattern() regex."""

    @patch("app.scheduler.get_settings")
    def test_matches_issue_container(self, mock_settings: MagicMock) -> None:
        from app.scheduler import _get_container_pattern

        mock_settings.return_value.worker_container_prefix = "codify"
        pattern = _get_container_pattern()
        self.assertIsNotNone(pattern.match("codify-1-issue10"))

    @patch("app.scheduler.get_settings")
    def test_matches_another_issue_container(self, mock_settings: MagicMock) -> None:
        from app.scheduler import _get_container_pattern

        mock_settings.return_value.worker_container_prefix = "codify"
        pattern = _get_container_pattern()
        self.assertIsNotNone(pattern.match("codify-42-issue200"))

    @patch("app.scheduler.get_settings")
    def test_rejects_service_container(self, mock_settings: MagicMock) -> None:
        from app.scheduler import _get_container_pattern

        mock_settings.return_value.worker_container_prefix = "codify"
        pattern = _get_container_pattern()
        self.assertIsNone(pattern.match("codify-backend"))
        self.assertIsNone(pattern.match("codify-postgres"))

    @patch("app.scheduler.get_settings")
    def test_rejects_partial_match(self, mock_settings: MagicMock) -> None:
        from app.scheduler import _get_container_pattern

        mock_settings.return_value.worker_container_prefix = "codify"
        pattern = _get_container_pattern()
        self.assertIsNone(pattern.match("codify-1-p100-other"))


# ---------------------------------------------------------------------------
# _execute_task — exception path
# ---------------------------------------------------------------------------


class TestExecuteTask(unittest.IsolatedAsyncioTestCase):
    """Tests for _execute_task atomic claim and exception handling."""

    def _claimable_task(self, task_id=77, issue_id=10, task_mode="execute"):
        task = _make_mock_task(task_id=task_id, issue_id=issue_id, task_mode=task_mode)
        task.status = TaskStatus.QUEUED
        task.issue_sequence = 1
        task.scheduled_at = None
        return task

    def _claim_execute(self, task):
        """Ordered db.execute results for _execute_task's atomic claim."""
        snapshot_result = MagicMock()
        snapshot_result.scalar_one_or_none.return_value = None
        issue_lock = MagicMock()
        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task
        pred_result = MagicMock()
        pred_result.first.return_value = None
        return [snapshot_result, issue_lock, task_result, pred_result]

    async def test_execute_task_marks_failed_on_commit_error(self) -> None:
        """If the atomic claim commit raises, task is rolled back and no worker starts."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        task = self._claimable_task(task_id=77, issue_id=10)

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=self._claim_execute(task))
        mock_db.commit = AsyncMock(side_effect=RuntimeError("DB error"))
        mock_db.rollback = AsyncMock()

        with (
            patch(
                "app.scheduler.ensure_issue_order_integrity_locked",
                new=AsyncMock(return_value={"repaired_sequences": 0, "repaired_projections": 0}),
            ),
            patch("app.scheduler.acquire_issue_execution_lock", new=AsyncMock(return_value=True)),
            patch("app.scheduler.asyncio.create_task") as mock_create_task,
        ):
            await scheduler._execute_task(mock_db, task)

        mock_db.rollback.assert_awaited()
        mock_create_task.assert_not_called()
        self.assertNotIn(77, scheduler._running_tasks)
        self.assertNotIn(10, scheduler._running_issues)

    async def test_plan_task_transitions_issue_to_in_progress(self) -> None:
        """Plan tasks still mark their linked issue as IN_PROGRESS while active."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        task = self._claimable_task(task_id=99, issue_id=5, task_mode="plan")

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=self._claim_execute(task))
        mock_db.commit = AsyncMock()

        with (
            patch(
                "app.scheduler.ensure_issue_order_integrity_locked",
                new=AsyncMock(return_value={"repaired_sequences": 0, "repaired_projections": 0}),
            ),
            patch("app.scheduler.acquire_issue_execution_lock", new=AsyncMock(return_value=True)),
            patch.object(
                scheduler, "_transition_issue_to_in_progress", new_callable=AsyncMock
            ) as mock_transition,
            patch.object(scheduler, "_run_task_background", new_callable=AsyncMock),
        ):
            await scheduler._execute_task(mock_db, task)

        mock_transition.assert_called_once_with(mock_db, 5)

    async def test_execute_task_does_transition_issue_for_execute_mode(self) -> None:
        """Execute-mode tasks still call _transition_issue_to_in_progress normally."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        task = self._claimable_task(task_id=100, issue_id=7, task_mode="execute")

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=self._claim_execute(task))
        mock_db.commit = AsyncMock()

        with (
            patch(
                "app.scheduler.ensure_issue_order_integrity_locked",
                new=AsyncMock(return_value={"repaired_sequences": 0, "repaired_projections": 0}),
            ),
            patch("app.scheduler.acquire_issue_execution_lock", new=AsyncMock(return_value=True)),
            patch.object(
                scheduler, "_transition_issue_to_in_progress", new_callable=AsyncMock
            ) as mock_transition,
            patch.object(scheduler, "_run_task_background", new_callable=AsyncMock),
        ):
            await scheduler._execute_task(mock_db, task)

        mock_transition.assert_called_once_with(mock_db, 7)


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
        """A deferred remove failure keeps task ownership and its finalized logs."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler.running = True

        stuck_task = _make_mock_task(
            task_id=60,
            project_id=400,
            issue_id=2,
            status=TaskStatus.RUNNING,
        )
        stuck_task.container_id = "container-60"
        stuck_task.raw_logs_finalized_at = None
        stuck_task.cancel_requested_at = None

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.get = AsyncMock(return_value=stuck_task)
        mock_db.refresh = AsyncMock()
        mock_db.commit = AsyncMock()

        dead_container = self._make_container("codify-60-issue2", status="dead")
        dead_container.remove.side_effect = RuntimeError("Cannot remove dead container")

        mock_docker = MagicMock()
        mock_docker.read_file_from_container.return_value = b"worker failed\n"
        connection = MagicMock()

        async def stop_after_retry(_delay: float) -> None:
            scheduler.running = False

        with (
            patch("app.scheduler.AsyncSessionLocal", return_value=mock_db),
            patch(
                "app.scheduler.find_task_container",
                new=AsyncMock(return_value=(mock_docker, dead_container, connection)),
            ),
            patch(
                "app.scheduler.persist_raw_log_snapshot",
                new=AsyncMock(),
            ) as persist_snapshot,
            patch(
                "app.scheduler.release_issue_execution_lock",
                new=AsyncMock(),
            ) as release_lock,
            patch("app.scheduler.asyncio.sleep", side_effect=stop_after_retry),
        ):
            await scheduler._coordinate_unavailable_recovery(60)

        dead_container.remove.assert_called_once_with(force=True, v=True)
        persist_snapshot.assert_awaited_once_with(
            mock_db,
            task_id=60,
            content=b"worker failed\n",
        )
        self.assertIsNotNone(stuck_task.raw_logs_finalized_at)
        self.assertEqual(stuck_task.status, TaskStatus.RUNNING)
        self.assertEqual(stuck_task.container_id, "container-60")
        release_lock.assert_not_awaited()

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

        with (
            patch("app.scheduler.AsyncSessionLocal", return_value=mock_db),
            patch("app.scheduler._get_recovery_docker_client", return_value=mock_docker),
        ):
            # Should NOT raise
            await scheduler._crash_recovery()

        orphan.remove.assert_called_once_with(force=True, v=True)

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

        with (
            patch("app.scheduler.AsyncSessionLocal", return_value=mock_db),
            patch("app.scheduler._get_recovery_docker_client", return_value=mock_docker),
        ):
            await scheduler._crash_recovery()

        # Exited orphan: force=False (c_status != "running")
        orphan.remove.assert_called_once_with(force=False, v=True)


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
        mock_db.commit = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.side_effect = [mock_task, None]
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
        mock_db.commit = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.side_effect = [mock_task, None]
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

        mock_task = _make_mock_task(
            task_id=44,
            project_id=300,
            issue_id=30,
            status=TaskStatus.RUNNING,
        )

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.side_effect = [mock_task, None]
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_db):
            loop = asyncio.get_event_loop()
            with patch.object(
                loop,
                "run_in_executor",
                new_callable=AsyncMock,
                side_effect=RuntimeError("thread pool crashed"),
            ):
                await scheduler._resume_task_background(44, "codify-44-issue30")

        self.assertNotIn(44, scheduler._running_tasks)
        self.assertNotIn(30, scheduler._running_issues)

    async def test_resume_missing_attempt_bootstrap_failure_converges(self) -> None:
        """Recovery policy rejection is handed to terminal bootstrap handling."""
        from app.core.harness_execution_policy import ExecutionPolicyError
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._running_tasks.add(46)
        scheduler._running_issues.add(32)
        rejection = ExecutionPolicyError(
            "missing durable execution attempt",
            code="missing_execution_attempt",
        )
        with patch.object(
            asyncio.get_event_loop(),
            "run_in_executor",
            new_callable=AsyncMock,
            side_effect=rejection,
        ), patch.object(
            scheduler,
            "_mark_worker_bootstrap_failed",
            new_callable=AsyncMock,
        ) as mark_failed:
            await scheduler._resume_task_background(46, "codify-46-issue32")

        mark_failed.assert_awaited_once()
        self.assertIs(mark_failed.await_args.args[1], rejection)
        self.assertNotIn(46, scheduler._running_tasks)

    async def test_resume_lookup_error_restarts_deferred_recovery(self) -> None:
        """An inconclusive Docker lookup keeps ownership and restarts recovery."""
        from app.core.worker_docker_targets import TaskContainerLookupError
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        scheduler._running_tasks.add(45)
        scheduler._running_issues.add(31)
        current = asyncio.current_task()
        assert current is not None
        scheduler._worker_tasks[45] = current
        replacement = MagicMock()
        scheduled_coroutines = []

        def capture_task(coroutine):
            scheduled_coroutines.append(coroutine)
            coroutine.close()
            return replacement

        with (
            patch.object(
                asyncio.get_event_loop(),
                "run_in_executor",
                new_callable=AsyncMock,
                side_effect=TaskContainerLookupError("Docker timed out"),
            ),
            patch.object(
                scheduler,
                "_mark_worker_bootstrap_failed",
                new_callable=AsyncMock,
            ) as mark_failed,
            patch("app.scheduler.asyncio.create_task", side_effect=capture_task),
        ):
            await scheduler._resume_task_background(45, "codify-45-issue31")

        self.assertEqual(len(scheduled_coroutines), 1)
        self.assertIs(scheduler._worker_tasks[45], replacement)
        self.assertIn(45, scheduler._running_tasks)
        self.assertIn(31, scheduler._running_issues)
        mark_failed.assert_not_awaited()

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
        mock_result.scalar_one_or_none.side_effect = [mock_task, None]
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

    def _run_with_mocks(
        self,
        resume_return_value=True,
        *,
        snapshot_digest="d" * 64,
        attempt_present=True,
    ):
        """Helper: run _run_worker_resume_task with all imports mocked."""
        from app.scheduler import _run_worker_resume_task

        mock_worker = MagicMock()
        mock_worker.resume_task = AsyncMock(return_value=resume_return_value)

        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        bundle = SimpleNamespace(
            contract_version="codify.worker.harness/v2",
            digest="d" * 64,
            manifest={"adapters": {"pi": {}}},
        )
        task = SimpleNamespace(
            id=42,
            runtime_bundle=bundle,
            worker_profile_snapshot=SimpleNamespace(
                runtime_contract_version="codify.worker.harness/v2",
                runtime_bundle_digest=snapshot_digest,
                harness_key="pi",
            ),
        )
        attempt = (
            SimpleNamespace(
                attempt_id="attempt-42",
                event_schema="codify.worker.event/v2",
                harness_key="pi",
            )
            if attempt_present
            else None
        )
        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task
        attempt_result = MagicMock()
        attempt_result.scalar_one_or_none.return_value = attempt
        mock_db.execute = AsyncMock(side_effect=[task_result, attempt_result])

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        pump = AsyncMock()
        self.last_pump = pump
        self.last_worker = mock_worker
        mock_docker = MagicMock()
        mock_container = mock_docker.client.containers.get.return_value
        mock_container.reload = MagicMock()
        with (
            patch("app.database._database_url", "sqlite+aiosqlite:///:memory:"),
            patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine),
            patch("sqlalchemy.ext.asyncio.async_sessionmaker") as mock_sm,
            patch("app.core.worker.WorkerExecutor", return_value=mock_worker),
            patch("app.core.worker_command_pump.run_pump_until_task_ends", new=pump),
            patch("app.scheduler.get_docker_client", return_value=mock_docker),
            patch("app.scheduler.validate_resume_container_identity"),
        ):
            mock_sm.return_value = MagicMock(return_value=mock_db)
            result = _run_worker_resume_task(42, "codify-42-issue10")

        return result, mock_worker, mock_engine, pump

    def test_run_worker_resume_task_success(self) -> None:
        """Lines 441-476: successful resume returns True."""
        result, mock_worker, _, _ = self._run_with_mocks(resume_return_value=True)
        self.assertTrue(result)
        mock_worker.resume_task.assert_awaited_once()

    def test_run_worker_resume_task_failure(self) -> None:
        """_run_worker_resume_task returns False when worker returns False."""
        result, _, _, _ = self._run_with_mocks(resume_return_value=False)
        self.assertFalse(result)

    def test_run_worker_resume_task_disposes_engine(self) -> None:
        """Engine should be disposed in the finally block even on success."""
        _, _, mock_engine, _ = self._run_with_mocks(resume_return_value=True)
        mock_engine.dispose.assert_called_once()

    def test_invalid_recovery_contract_never_starts_command_pump(self) -> None:
        """A mismatched frozen snapshot fails before transport can dispatch."""
        from app.core.harness_execution_policy import ExecutionPolicyError

        with self.assertRaises(ExecutionPolicyError):
            self._run_with_mocks(snapshot_digest="x" * 64)
        self.last_pump.assert_not_awaited()
        self.last_worker.resume_task.assert_not_awaited()

    def test_v2_recovery_without_attempt_never_starts_command_pump(self) -> None:
        """A V2 container without a durable attempt is not resumed."""
        from app.core.harness_execution_policy import (
            MISSING_EXECUTION_ATTEMPT,
            ExecutionPolicyError,
        )

        with self.assertRaises(ExecutionPolicyError) as exc:
            self._run_with_mocks(attempt_present=False)
        self.assertEqual(exc.exception.code, MISSING_EXECUTION_ATTEMPT)
        self.last_pump.assert_not_awaited()
        self.last_worker.resume_task.assert_not_awaited()


# ---------------------------------------------------------------------------
# _mark_eligible_as_queued — issue in_review → in_progress transition
# ---------------------------------------------------------------------------


class TestMarkEligibleAsQueuedIssueTransition(unittest.IsolatedAsyncioTestCase):
    """Tests that _mark_eligible_as_queued also transitions linked issues to in_progress.

    Regression: an issue could stay in 'in_review' if all prior tasks completed but a
    new task was still in QUEUED state. The scheduler must update issue status when
    tasks are marked QUEUED.
    """

    def _mark_queued_execute(self, *, promote_rowcount, queued_issues, normalize_rowcount=0):
        """Build the ordered db.execute side_effect for the three-step promote.

        New _mark_eligible_as_queued runs: (1) a NULL-sequence scan, (2) an illegal
        QUEUED normalization update, (3) a head-only promote update, then when a
        promote succeeded, (4) an issue-ID query and (5) an issue status update.
        """
        null_scan = MagicMock()
        null_scan.fetchall.return_value = []
        normalize = MagicMock()
        normalize.rowcount = normalize_rowcount
        promote = MagicMock()
        promote.rowcount = promote_rowcount
        effects = [null_scan, normalize, promote]
        if promote_rowcount > 0:
            effects.append(list(queued_issues))
            effects.append(MagicMock())
        return effects

    async def test_in_review_issue_transitions_to_in_progress_when_task_queued(self) -> None:
        """Issue in 'in_review' → 'in_progress' after tasks are marked QUEUED."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        mock_db = AsyncMock()

        mock_db.execute = AsyncMock(
            side_effect=self._mark_queued_execute(
                promote_rowcount=2,
                queued_issues=[(5,)],
            )
        )

        with patch("app.scheduler.utcnow"):
            await scheduler._mark_eligible_as_queued(mock_db)

        # execute: null scan, normalize update, promote update, issue query, issue update
        self.assertEqual(mock_db.execute.await_count, 5)
        # commit twice: once after promote update, once after issue update
        self.assertEqual(mock_db.commit.await_count, 2)

    async def test_no_issue_transition_when_no_tasks_marked_queued(self) -> None:
        """When rowcount == 0 no issue query or update is performed."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        mock_db = AsyncMock()

        mock_db.execute = AsyncMock(
            side_effect=self._mark_queued_execute(
                promote_rowcount=0,
                queued_issues=[],
            )
        )

        with patch("app.scheduler.utcnow"):
            await scheduler._mark_eligible_as_queued(mock_db)

        # Only the three step executes, no commit
        self.assertEqual(mock_db.execute.await_count, 3)
        mock_db.commit.assert_not_called()

    async def test_no_issue_update_when_queued_tasks_have_no_issue(self) -> None:
        """When all newly queued tasks have issue_id=None, no issue update is executed."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        mock_db = AsyncMock()

        mock_db.execute = AsyncMock(
            side_effect=self._mark_queued_execute(
                promote_rowcount=1,
                queued_issues=[],
            )
        )

        with patch("app.scheduler.utcnow"):
            await scheduler._mark_eligible_as_queued(mock_db)

        # execute: null scan, normalize, promote, issue query (empty) — no issue update
        self.assertEqual(mock_db.execute.await_count, 4)
        # commit once (only for promote update)
        self.assertEqual(mock_db.commit.await_count, 1)

    async def test_multiple_issues_all_transitioned(self) -> None:
        """Multiple issues linked to queued tasks all get transitioned."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        mock_db = AsyncMock()

        mock_db.execute = AsyncMock(
            side_effect=self._mark_queued_execute(
                promote_rowcount=3,
                queued_issues=[(1,), (7,), (42,)],
            )
        )

        with patch("app.scheduler.utcnow"):
            await scheduler._mark_eligible_as_queued(mock_db)

        self.assertEqual(mock_db.execute.await_count, 5)
        self.assertEqual(mock_db.commit.await_count, 2)

    async def test_plan_tasks_included_in_issue_in_progress_transition(self) -> None:
        """Queued plan tasks mark their linked issue as IN_PROGRESS while active."""

        from app.scheduler import Scheduler

        scheduler = Scheduler()
        mock_db = AsyncMock()

        mock_db.execute = AsyncMock(
            side_effect=self._mark_queued_execute(
                promote_rowcount=1,
                queued_issues=[(5,)],
            )
        )

        with patch("app.scheduler.utcnow"):
            await scheduler._mark_eligible_as_queued(mock_db)

        self.assertEqual(mock_db.execute.await_count, 5)
        self.assertEqual(mock_db.commit.await_count, 2)

    async def test_issue_query_does_not_filter_task_mode(self) -> None:
        """The issue transition query treats any queued task mode as active work."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        mock_db = AsyncMock()

        captured_stmts = []

        async def capture_execute(stmt, *args, **kwargs):
            captured_stmts.append(stmt)
            if len(captured_stmts) == 1:
                null_scan = MagicMock()
                null_scan.fetchall.return_value = []
                return null_scan
            if len(captured_stmts) == 2:
                normalize = MagicMock()
                normalize.rowcount = 0
                return normalize
            if len(captured_stmts) == 3:
                promote = MagicMock()
                promote.rowcount = 1
                return promote
            return []  # issue query returns empty -> no third update execute

        mock_db.execute = capture_execute

        with patch("app.scheduler.utcnow"):
            await scheduler._mark_eligible_as_queued(mock_db)

        # The fourth statement is the issue-ID SELECT; compile and inspect it.
        self.assertGreaterEqual(len(captured_stmts), 4)
        from sqlalchemy.dialects import postgresql

        compiled = captured_stmts[3].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
        sql_text = str(compiled).lower()
        self.assertNotIn("task_mode", sql_text, "Issue-ID query must include all task modes")
        self.assertNotIn("plan", sql_text, "Issue-ID query must include plan mode tasks")


if __name__ == "__main__":
    unittest.main()
