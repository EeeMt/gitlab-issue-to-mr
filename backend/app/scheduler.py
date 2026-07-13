"""Task scheduler for queue management."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from docker.errors import NotFound
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings as get_settings
from app.core.docker_client import (
    DockerClientWrapper,
    DockerConnectionConfig,
    get_docker_client,
)
from app.core.issue_execution_locks import (
    acquire_issue_execution_lock,
    cleanup_inactive_issue_execution_locks,
    release_issue_execution_lock,
)
from app.core.session import cleanup_stale_sessions
from app.core.task_helpers import maybe_update_issue_status
from app.core.usage_limits import (
    UsageLimitExceeded,
    get_usage_quota_service,
    usage_limit_exceeded_detail,
)
from app.core.utcnow import utcnow
from app.core.worker_docker_targets import (
    DockerConnectionsUnavailableError,
    TaskContainerLookupError,
    TaskContainerNotFoundError,
    connection_for_task,
    docker_daemon_key,
    find_task_container,
    list_known_docker_targets,
)
from app.core.worker_workspace import cleanup_expired_workspaces
from app.database import AsyncSessionLocal
from app.models import Issue, IssueExecutionLock, IssueStatus, Task, TaskStatus
from app.runtime_config import load_runtime_config_from_db

logger = logging.getLogger(__name__)
_SESSION_CLEANUP_INTERVAL_SECONDS = 3600
_WORKSPACE_CLEANUP_INTERVAL_SECONDS = 21600
_LOCK_CLEANUP_INTERVAL_SECONDS = 300
_TERMINAL_WORKER_STUCK_SECONDS = 120
_RECOVERY_RETRY_OFFSETS_SECONDS = (0.0, 10.0, 20.0)
_RECOVERY_REQUEST_TIMEOUT_SECONDS = 5
_RECOVERY_PROBE_TIMEOUT_SECONDS = 11
_RECOVERY_UNAVAILABLE_RETRY_SECONDS = 30

# Thread pool for running worker tasks (to avoid blocking the event loop)
_worker_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="worker-")


def _get_container_pattern() -> re.Pattern:
    """Build container name regex using configured prefix."""
    prefix = re.escape(get_settings().worker_container_prefix)
    return re.compile(rf"^{prefix}-(\d+)-issue(\d+)$")


def _extract_task_id(container_name: str) -> int | None:
    """Extract task_id from a worker container name like codify-123-issue456."""
    m = _get_container_pattern().match(container_name)
    return int(m.group(1)) if m else None


def _get_recovery_docker_client(connection):
    """Create a bounded, non-cached client for startup recovery."""
    return DockerClientWrapper(
        connection,
        connect_timeout=_RECOVERY_REQUEST_TIMEOUT_SECONDS,
        operation_timeout=_RECOVERY_REQUEST_TIMEOUT_SECONDS,
    )


def _list_recovery_containers(connection, container_prefix: str):
    """Probe one daemon and close the transient client afterwards."""
    docker = _get_recovery_docker_client(connection)
    try:
        return docker.client.containers.list(
            all=True,
            filters={"name": f"{container_prefix}-"},
        )
    finally:
        docker.close()


def _inspect_recovery_container(connection, container_reference: str) -> tuple[str, str]:
    """Resolve one known container through a bounded transient recovery client."""
    docker = _get_recovery_docker_client(connection)
    try:
        container = docker.client.containers.get(container_reference)
        return container.name, container.status
    finally:
        docker.close()


async def _stop_recovered_cancelled_container(container, task_id: int) -> None:
    """Stop a recovered container so durable cancellation intent is actually enforced."""
    try:
        await asyncio.to_thread(container.stop, timeout=10)
    except Exception as stop_error:  # noqa: BLE001
        logger.warning(
            "Graceful stop failed for recovered cancelled task %s: %s; forcing stop",
            task_id,
            stop_error,
        )
        try:
            await asyncio.to_thread(container.kill)
        except Exception as kill_error:  # noqa: BLE001
            raise RuntimeError(
                f"could not stop recovered cancelled container: graceful={stop_error}; "
                f"force={kill_error}"
            ) from kill_error


class Scheduler:
    """Task scheduler with priority queue and concurrency control."""

    def __init__(self) -> None:
        self.running = False
        self._running_tasks: set[int] = set()  # task_ids currently running
        self._running_issues: set[int] = set()  # issue_ids with running tasks
        self._worker_tasks: dict[int, asyncio.Task] = {}  # scheduler task handles by task_id
        self._terminal_worker_seen_at: dict[int, float] = {}
        self._active_worker_threads: int = 0   # thread pool tasks in-flight (submitted but not done)
        self._last_session_cleanup_at = 0.0
        self._last_workspace_cleanup_at = 0.0
        self._last_lock_cleanup_at = 0.0

    async def start(self) -> None:
        """Start the scheduler loop."""
        logger.info("Starting scheduler...")
        self.running = True

        # Run recovery on startup
        try:
            await self._crash_recovery()
        except Exception as e:
            logger.warning(f"Skipping crash recovery on startup: {e}")

        while self.running:
            try:
                await self._run_cycle()
            except Exception:
                logger.exception("Scheduler cycle failed")
            settings = get_settings()
            await asyncio.sleep(settings.scheduler_interval)

        logger.info("Scheduler stopped")

    async def stop(self) -> None:
        """Stop the scheduler."""
        logger.info("Stopping scheduler...")
        self.running = False

    async def _run_cycle(self) -> None:
        """Run one scheduler cycle."""
        async with AsyncSessionLocal() as db:
            await load_runtime_config_from_db(db)
            await self._maybe_cleanup_sessions(db)
            await self._maybe_cleanup_workspaces(db)
            await self._maybe_cleanup_issue_locks(db)

            # Reconcile in-memory tracking sets against DB and local worker handles.
            # A task can be terminal in DB while its worker coroutine is still doing
            # post-run cleanup, so status alone is not enough to declare it stale.
            await self._reconcile_running_state(db)

            # Transition eligible PENDING tasks → QUEUED
            await self._mark_eligible_as_queued(db)

            settings = get_settings()
            # Count running tasks for concurrency control
            running_count = await self._get_running_count(db)

            if running_count >= settings.max_concurrency:
                logger.debug(f"Max concurrency reached ({running_count}/{settings.max_concurrency})")
                return

            # Get next task
            task = await self._get_next_task(db)
            if not task:
                logger.debug("No tasks available")
                return

            # Check issue mutex — prevents concurrent tasks on the same issue.
            # Tasks without issue_id are independent and skip the shared mutex.
            if task.issue_id in self._running_issues:
                logger.debug(f"Issue {task.issue_id} already running, skipping")
                return

            # Execute task
            await self._execute_task(db, task)

    async def _reconcile_running_state(self, db: AsyncSession) -> None:
        """Reconcile in-memory running-task sets against the database.

        When a worker thread blocks indefinitely (e.g., on a GitLab API call with no
        timeout), its finally block never executes, so _running_tasks and _running_issues
        are never cleared even after the DB task has moved out of RUNNING. This method
        keeps normal post-run cleanup active by checking the local asyncio task handle,
        and corrects real drift every cycle.
        """
        if not self._running_tasks and not self._running_issues:
            return

        if self._running_tasks:
            result = await db.execute(
                select(Task.id, Task.issue_id, Task.status).where(
                    Task.id.in_(list(self._running_tasks)),
                )
            )
            rows = result.fetchall()
            active_task_ids: set[int] = set()
            active_issue_ids: set[int] = set()
            for row in rows:
                task_id = row[0]
                issue_id = row[1]
                status = row[2] if len(row) > 2 else TaskStatus.RUNNING
                status_value = getattr(status, "value", status)
                if status_value == TaskStatus.RUNNING.value:
                    self._terminal_worker_seen_at.pop(task_id, None)
                    active_task_ids.add(task_id)
                    if issue_id is not None:
                        active_issue_ids.add(issue_id)
                    continue

                if self._worker_handle_is_active(task_id, status):
                    active_task_ids.add(task_id)
                    if issue_id is not None:
                        active_issue_ids.add(issue_id)

            stale_tasks = self._running_tasks - active_task_ids
            for task_id in stale_tasks:
                self._running_tasks.discard(task_id)
                self._forget_worker_handle_if_finished(task_id)
                logger.warning(
                    "Reconciled stale _running_tasks entry for task %s "
                    "(no longer RUNNING in DB and worker handle is inactive or stuck)",
                    task_id,
                )

            stale_issues = self._running_issues - active_issue_ids
            for issue_id in stale_issues:
                self._running_issues.discard(issue_id)
                logger.warning(
                    "Reconciled stale _running_issues entry for issue %s "
                    "(no RUNNING task or active worker handle within stuck threshold found)",
                    issue_id,
                )

        elif self._running_issues:
            # _running_tasks is empty but _running_issues has entries — possible when a
            # thread's finally block could not release the issue slot.  Query independently.
            result = await db.execute(
                select(Task.issue_id).distinct().where(
                    Task.issue_id.in_(list(self._running_issues)),
                    Task.status == TaskStatus.RUNNING,
                )
            )
            active_issue_ids = {row[0] for row in result.fetchall() if row[0] is not None}
            for issue_id in self._running_issues - active_issue_ids:
                self._running_issues.discard(issue_id)
                logger.warning(
                    "Reconciled stale _running_issues entry for issue %s "
                    "(no RUNNING task found in DB)",
                    issue_id,
                )

    def _worker_handle_is_active(self, task_id: int, status) -> bool:
        """Return True while the local worker coroutine is still doing cleanup."""
        status_value = getattr(status, "value", status)
        if status_value == TaskStatus.CANCELLED.value:
            return False

        worker_task = self._worker_tasks.get(task_id)
        if worker_task is None or worker_task.done():
            return False

        now = time.monotonic()
        first_seen = self._terminal_worker_seen_at.setdefault(task_id, now)
        elapsed = now - first_seen
        if elapsed < _TERMINAL_WORKER_STUCK_SECONDS:
            logger.debug(
                "Task %s is %s in DB but worker coroutine is still active "
                "(post-run cleanup, %.0fs)",
                task_id,
                status,
                elapsed,
            )
            return True

        logger.warning(
            "Task %s worker coroutine still active %.0fs after DB status became %s; "
            "reconciling as stale",
            task_id,
            elapsed,
            status,
        )
        return False

    def _forget_worker_handle_if_finished(self, task_id: int) -> None:
        """Drop completed handles, but keep active stuck handles observable."""
        worker_task = self._worker_tasks.get(task_id)
        if worker_task is not None and not worker_task.done():
            return
        self._worker_tasks.pop(task_id, None)
        self._terminal_worker_seen_at.pop(task_id, None)

    async def _maybe_cleanup_sessions(self, db: AsyncSession) -> None:
        """Periodically delete long-stale dashboard sessions."""
        now = time.time()
        if now - self._last_session_cleanup_at < _SESSION_CLEANUP_INTERVAL_SECONDS:
            return

        deleted_count = await cleanup_stale_sessions(db)
        if deleted_count:
            await db.commit()
            logger.info("Cleaned up %s stale dashboard sessions", deleted_count)
        self._last_session_cleanup_at = now

    async def _maybe_cleanup_workspaces(self, db: AsyncSession) -> None:
        """Periodically delete expired persistent worker workspaces."""
        now = time.time()
        if now - self._last_workspace_cleanup_at < _WORKSPACE_CLEANUP_INTERVAL_SECONDS:
            return

        settings = get_settings()
        raw_root = getattr(settings, "worker_workspace_host_path", "")
        root = raw_root.strip() if isinstance(raw_root, str) else ""
        if not root:
            self._last_workspace_cleanup_at = now
            return
        retention_days = getattr(settings, "worker_workspace_retention_days", 14)
        if not isinstance(retention_days, int):
            self._last_workspace_cleanup_at = now
            return

        removed = await asyncio.to_thread(
            cleanup_expired_workspaces,
            root,
            retention_days=retention_days,
        )
        if removed:
            logger.info("Cleaned up %s expired worker workspace(s)", removed)
        self._last_workspace_cleanup_at = now

    async def _maybe_cleanup_issue_locks(self, db: AsyncSession) -> None:
        """Periodically delete locks for completed/failed/cancelled tasks."""
        now = time.time()
        if now - self._last_lock_cleanup_at < _LOCK_CLEANUP_INTERVAL_SECONDS:
            return

        removed = await cleanup_inactive_issue_execution_locks(db)
        if removed:
            await db.commit()
            logger.warning("Cleaned up %s inactive issue execution lock(s)", removed)
        self._last_lock_cleanup_at = now

    async def _mark_eligible_as_queued(self, db: AsyncSession) -> None:
        """Mark eligible PENDING tasks as QUEUED.

        A PENDING task becomes QUEUED when:
        - scheduled_at is NULL (immediate) or scheduled_at <= now
        - Its issue is not already running (issue mutex)
        """
        now = utcnow()
        # Build list of issue_ids that are currently running (mutex-blocked)
        blocked_issue_ids = list(self._running_issues) if self._running_issues else []

        stmt = (
            update(Task)
            .where(
                Task.status == TaskStatus.PENDING,
                (Task.scheduled_at == None) | (Task.scheduled_at <= now),
            )
            .values(status=TaskStatus.QUEUED)
        )
        if blocked_issue_ids:
            stmt = stmt.where(
                (Task.issue_id == None) | (~Task.issue_id.in_(blocked_issue_ids))
            )
        result = await db.execute(stmt)
        if result.rowcount > 0:
            await db.commit()
            logger.debug(f"Marked {result.rowcount} eligible task(s) as QUEUED")
            # Transition issues to in_progress for all newly queued tasks
            queued_issue_result = await db.execute(
                select(Task.issue_id).where(
                    Task.status == TaskStatus.QUEUED,
                    Task.issue_id != None,
                ).distinct()
            )
            issue_ids = [row[0] for row in queued_issue_result]
            if issue_ids:
                await db.execute(
                    update(Issue)
                    .where(
                        Issue.id.in_(issue_ids),
                        Issue.status.in_([IssueStatus.OPEN.value, IssueStatus.IN_REVIEW.value]),
                    )
                    .values(status=IssueStatus.IN_PROGRESS.value)
                )
                await db.commit()
                logger.debug(f"Transitioned {len(issue_ids)} issue(s) to IN_PROGRESS for queued tasks")

    async def _get_running_count(self, db: AsyncSession) -> int:
        """Get count of currently running tasks."""
        result = await db.execute(
            select(func.count(Task.id)).where(Task.status == TaskStatus.RUNNING)
        )
        return result.scalar() or 0

    async def _get_next_task(self, db: AsyncSession) -> Task | None:
        """Get the next QUEUED task to execute based on priority.

        Only picks QUEUED tasks — eligible PENDING tasks are transitioned
        to QUEUED by _mark_eligible_as_queued() earlier in the cycle.

        Ordering:
        1. priority ASC — P0(0) runs before P1(1) before P2(2)
        2. scheduled tasks before immediate — users who booked a slot
           have a reasonable expectation their task runs on time
        3. scheduled_at ASC — earlier due times first
        4. created_at ASC — FIFO tiebreaker
        """
        result = await db.execute(
            select(Task)
            .where(Task.status == TaskStatus.QUEUED)
            .order_by(
                Task.priority.asc(),
                case((Task.scheduled_at.is_not(None), 0), else_=1),
                Task.scheduled_at.asc(),
                Task.created_at.asc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _execute_task(self, db: AsyncSession, task: Task) -> None:
        """Execute a task in a separate thread to avoid blocking the event loop."""
        task_id = task.id
        issue_id = task.issue_id
        logger.info("Executing task %s for issue %s", task_id, issue_id)

        lock_acquired = await acquire_issue_execution_lock(db, task)
        if not lock_acquired:
            logger.debug("Issue %s locked; task %s remains queued", issue_id, task_id)
            return

        try:
            initiator_user_id = getattr(task, "initiator_user_id", None)
            if isinstance(initiator_user_id, int):
                try:
                    await get_usage_quota_service().raise_if_over_limit(
                        db,
                        initiator_user_id,
                        scope="execute",
                    )
                except UsageLimitExceeded as exc:
                    logger.info(
                        "Task %s blocked by usage limits before execution",
                        task_id,
                    )
                    task.status = TaskStatus.FAILED
                    task.error_message = json.dumps(usage_limit_exceeded_detail(exc))
                    task.completed_at = utcnow()
                    await db.commit()
                    await release_issue_execution_lock(db, issue_id=issue_id)
                    await db.commit()
                    await maybe_update_issue_status(db, issue_id)
                    return

            # Update status to RUNNING
            task.status = TaskStatus.RUNNING
            task.started_at = utcnow()
            await db.commit()

            # Track in memory AFTER the DB commit so _reconcile_running_state
            # (which queries for RUNNING tasks) doesn't race with the update.
            self._running_tasks.add(task_id)
            self._running_issues.add(issue_id)

            # Any active task means the issue is currently in progress.
            await self._transition_issue_to_in_progress(db, issue_id)

            # Execute via worker in a thread pool WITHOUT waiting
            self._worker_tasks[task_id] = asyncio.create_task(self._run_task_background(task_id))
            logger.info("Task %s submitted to thread pool", task_id)

        except Exception as e:
            logger.exception("Task %s failed with exception", task_id)
            task.status = TaskStatus.FAILED
            task.error_message = str(e)[:500]
            task.completed_at = utcnow()
            await release_issue_execution_lock(db, issue_id=issue_id)
            try:
                await db.commit()
            except Exception:
                logger.exception("Failed to persist failure state for task %s", task_id)

            # Clean up tracking (may not have been added yet, discard is idempotent)
            self._running_tasks.discard(task_id)
            self._running_issues.discard(issue_id)

    async def _transition_issue_to_in_progress(self, db: AsyncSession, issue_id: int) -> None:
        """Auto-transition issue OPEN/COMPLETED → IN_PROGRESS when a task starts running."""
        try:
            issue = await db.get(Issue, issue_id)
            if issue and issue.status in (IssueStatus.OPEN.value, IssueStatus.IN_REVIEW.value):
                issue.status = IssueStatus.IN_PROGRESS.value
                await db.commit()
                logger.info(f"Issue {issue_id} auto-transitioned to IN_PROGRESS")
        except Exception as e:
            logger.warning(f"Failed to transition issue {issue_id}: {e}")

    async def _run_task_background(self, task_id: int) -> None:
        """Run task in background thread pool."""
        self._active_worker_threads += 1
        t_submit = time.time()
        logger.info(
            f"Task {task_id} submitted to thread pool "
            f"(active_threads={self._active_worker_threads}, "
            f"max_workers={_worker_executor._max_workers})"
        )
        try:
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                _worker_executor,
                _run_worker_task,
                task_id,
            )
            elapsed = time.time() - t_submit
            if success:
                logger.info(
                    f"Task {task_id} completed successfully (total={elapsed:.0f}s, "
                    f"active_threads={self._active_worker_threads})"
                )
            else:
                logger.error(
                    f"Task {task_id} failed (total={elapsed:.0f}s, "
                    f"active_threads={self._active_worker_threads})"
                )

        except Exception as exc:
            logger.exception(f"Task {task_id} failed with exception in background")
            await self._mark_worker_bootstrap_failed(task_id, exc)

        finally:
            self._active_worker_threads -= 1
            # Clean up tracking
            self._worker_tasks.pop(task_id, None)
            self._terminal_worker_seen_at.pop(task_id, None)
            self._running_tasks.discard(task_id)
            try:
                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(Task).where(Task.id == task_id)
                    )
                    task = result.scalar_one_or_none()
                    if task:
                        # Guard: only release the DB lock and in-memory slot if WE still hold it.
                        # If _reconcile_running_state already cleared us and a replacement task
                        # re-acquired the lock for this issue, releasing here would corrupt the
                        # new task's execution slot.
                        lock_result = await db.execute(
                            select(IssueExecutionLock).where(
                                IssueExecutionLock.issue_id == task.issue_id
                            )
                        )
                        lock = lock_result.scalar_one_or_none()
                        if lock is None or lock.task_id == task_id:
                            self._running_issues.discard(task.issue_id)
                            await release_issue_execution_lock(db, issue_id=task.issue_id)
                            await db.commit()
                            # Auto-transition issue to COMPLETED if all tasks done
                            await self._maybe_complete_issue(db, task.issue_id)
            except Exception:
                logger.exception("Failed to release lock for task %s", task_id)

    async def _mark_worker_bootstrap_failed(self, task_id: int, exc: Exception) -> None:
        """Persist failures that happen before WorkerExecutor can own task state."""
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Task).where(Task.id == task_id))
                task = result.scalar_one_or_none()
                if task is None or task.status != TaskStatus.RUNNING:
                    return

                from app.core.worker import sanitize_sensitive_data

                cancellation_requested = isinstance(
                    getattr(task, "cancel_requested_at", None),
                    datetime,
                )
                task.status = (
                    TaskStatus.CANCELLED if cancellation_requested else TaskStatus.FAILED
                )
                task.error_message = (
                    "Cancelled by user before worker startup completed"
                    if cancellation_requested
                    else sanitize_sensitive_data(f"Worker failed to start: {exc}")[:2000]
                )
                task.completed_at = utcnow()
                await release_issue_execution_lock(db, issue_id=task.issue_id)
                await db.commit()
                self._running_issues.discard(task.issue_id)
        except Exception:
            logger.exception("Failed to persist worker bootstrap failure for task %s", task_id)

    async def _maybe_complete_issue(self, db: AsyncSession, issue_id: int) -> None:
        """Delegate to shared helper."""
        await maybe_update_issue_status(db, issue_id)

    async def _crash_recovery(self) -> None:
        """Recover from crashes: clean up orphan containers, resume legitimate ones.

        Handles several scenarios:
        - Container running + task RUNNING → resume monitoring
        - Container exited + task RUNNING → resume (collects logs/results from exited container)
        - Container running/exited + no matching task → remove (true orphan)
        - Task RUNNING + no container → mark FAILED
        """
        logger.info("Running crash recovery...")

        async with AsyncSessionLocal() as db:
            removed_locks = await cleanup_inactive_issue_execution_locks(db)
            if removed_locks:
                logger.warning("Cleaned up %s inactive issue execution lock(s)", removed_locks)

            # Running tasks must be resumed; terminal tasks with unfinished raw-log
            # finalization still own their retained containers and must not be reaped.
            result = await db.execute(
                select(Task).where(
                    or_(
                        Task.status == TaskStatus.RUNNING,
                        and_(
                            Task.container_id.is_not(None),
                            Task.raw_logs_finalized_at.is_(None),
                        ),
                    )
                )
            )
            owned_tasks = result.scalars().all()
            stuck_tasks = [
                task
                for task in owned_tasks
                if getattr(task.status, "value", task.status) == TaskStatus.RUNNING.value
            ]
            retained_task_ids = {
                task.id
                for task in owned_tasks
                if getattr(task.status, "value", task.status) != TaskStatus.RUNNING.value
            }
            if stuck_tasks:
                logger.warning(f"Found {len(stuck_tasks)} tasks in RUNNING status")

            settings = get_settings()
            targets = await list_known_docker_targets(db, settings, include_retained=True)
            task_connections = {
                task.id: await connection_for_task(db, task, settings)
                for task in owned_tasks
            }
            task_daemon_keys = {
                task_id: docker_daemon_key(connection)
                for task_id, connection in task_connections.items()
            }

            async def enumerate_target(target):
                has_running_tasks = any(
                    task_id not in retained_task_ids and daemon_key == target.daemon_key
                    for task_id, daemon_key in task_daemon_keys.items()
                )
                retry_offsets = (
                    _RECOVERY_RETRY_OFFSETS_SECONDS
                    if has_running_tasks
                    else _RECOVERY_RETRY_OFFSETS_SECONDS[:1]
                )
                started_at = asyncio.get_running_loop().time()
                last_error = None
                for retry_offset in retry_offsets:
                    delay = started_at + retry_offset - asyncio.get_running_loop().time()
                    if delay > 0:
                        await asyncio.sleep(delay)
                    async def try_connections():
                        nonlocal last_error
                        for connection in target.connections:
                            try:
                                containers = await asyncio.to_thread(
                                    _list_recovery_containers,
                                    connection,
                                    settings.worker_container_prefix,
                                )
                                return containers, connection
                            except Exception as exc:  # noqa: BLE001
                                last_error = exc
                                logger.warning(
                                    "Failed to enumerate Docker target %s: %s",
                                    connection.host,
                                    exc,
                                )
                        if last_error is not None:
                            raise last_error
                        return [], None

                    try:
                        containers, successful_connection = await asyncio.wait_for(
                            try_connections(),
                            timeout=_RECOVERY_PROBE_TIMEOUT_SECONDS,
                        )
                        return target, containers, successful_connection, None
                    except Exception as exc:  # noqa: BLE001
                        last_error = exc
                return target, [], None, last_error

            target_results = await asyncio.gather(
                *(enumerate_target(target) for target in targets)
            )
            resumed_task_ids: set[int] = set()
            unavailable_task_ids: set[int] = set()
            successful_connections: dict[str, DockerConnectionConfig] = {}
            pattern = _get_container_pattern()
            for target, all_containers, successful_connection, target_error in target_results:
                target_owned_task_ids = {
                    task_id
                    for task_id, daemon_key in task_daemon_keys.items()
                    if daemon_key == target.daemon_key
                }
                target_running_task_ids = target_owned_task_ids - retained_task_ids
                target_retained_task_ids = target_owned_task_ids & retained_task_ids
                if target_error is not None:
                    unavailable_task_ids.update(target_running_task_ids)
                    logger.warning(
                        "Deferring recovery for tasks %s because Docker daemon %s "
                        "remains unreachable",
                        sorted(target_running_task_ids),
                        target.connection.host,
                    )
                    continue
                if successful_connection is not None:
                    successful_connections[target.daemon_key] = successful_connection
                for container in all_containers:
                    if not pattern.match(container.name):
                        continue

                    task_id = _extract_task_id(container.name)
                    c_status = container.status

                    if task_id is not None and task_id in target_running_task_ids:
                        if c_status in ("running", "exited"):
                            task = next(task for task in stuck_tasks if task.id == task_id)
                            cancellation_requested = isinstance(
                                getattr(task, "cancel_requested_at", None),
                                datetime,
                            )
                            if cancellation_requested and c_status == "running":
                                try:
                                    await _stop_recovered_cancelled_container(container, task_id)
                                except Exception as exc:  # noqa: BLE001
                                    unavailable_task_ids.add(task_id)
                                    logger.warning(
                                        "Deferring recovery for cancelled task %s because "
                                        "container %s could not be stopped: %s",
                                        task_id,
                                        container.name,
                                        exc,
                                    )
                                    continue
                            logger.info(
                                "Resuming task %s on %s (container %s, status=%s, issue_id=%s)",
                                task_id,
                                target.connection.host,
                                container.name,
                                c_status,
                                task.issue_id,
                            )
                            self._running_tasks.add(task_id)
                            self._running_issues.add(task.issue_id)
                            resumed_task_ids.add(task_id)
                            self._worker_tasks[task_id] = asyncio.create_task(
                                self._resume_task_background(
                                    task_id,
                                    container.name,
                                    successful_connection,
                                )
                            )
                        else:
                            logger.warning(
                                f"Removing {c_status} container for task {task_id}: {container.name}"
                            )
                            try:
                                container.remove(force=True)
                            except Exception as e:
                                logger.warning(f"Failed to remove container {container.name}: {e}")
                    elif task_id is not None and task_id in target_retained_task_ids:
                        logger.info(
                            "Retaining owned container %s for task %s until raw logs finalize",
                            container.name,
                            task_id,
                        )
                    else:
                        logger.warning(
                            f"Removing {c_status} orphan container: {container.name} "
                            f"(task_id={task_id}, target={target.connection.host})"
                        )
                        try:
                            container.remove(force=(c_status == "running"))
                        except Exception as e:
                            logger.warning(
                                f"Failed to remove container {container.name}: {e}"
                            )

            # Prefix-based enumeration is retained for orphan cleanup, but task recovery
            # uses the immutable container ID so a deployment-time prefix change cannot
            # make a live worker invisible.
            for task in stuck_tasks:
                container_id = getattr(task, "container_id", None)
                if (
                    task.id in resumed_task_ids
                    or task.id in unavailable_task_ids
                    or not isinstance(container_id, str)
                    or not container_id.strip()
                ):
                    continue
                daemon_key = task_daemon_keys[task.id]
                successful_connection = successful_connections.get(daemon_key)
                if successful_connection is None:
                    unavailable_task_ids.add(task.id)
                    continue
                try:
                    container_name, container_status = await asyncio.to_thread(
                        _inspect_recovery_container,
                        successful_connection,
                        container_id,
                    )
                except NotFound:
                    continue
                except Exception as exc:  # noqa: BLE001
                    unavailable_task_ids.add(task.id)
                    logger.warning(
                        "Deferring recovery for task %s because direct lookup of "
                        "container %s on %s was inconclusive: %s",
                        task.id,
                        container_id,
                        successful_connection.host,
                        exc,
                    )
                    continue

                if container_status in ("running", "exited"):
                    cancellation_requested = isinstance(
                        getattr(task, "cancel_requested_at", None),
                        datetime,
                    )
                    if cancellation_requested and container_status == "running":
                        try:
                            _docker, container, _connection = await find_task_container(
                                db,
                                task,
                                settings,
                                container_id,
                            )
                            await _stop_recovered_cancelled_container(container, task.id)
                        except Exception as exc:  # noqa: BLE001
                            unavailable_task_ids.add(task.id)
                            logger.warning(
                                "Deferring recovery for cancelled task %s because stable "
                                "container %s could not be stopped: %s",
                                task.id,
                                container_id,
                                exc,
                            )
                            continue
                    logger.info(
                        "Recovered task %s by stable container ID %s on %s "
                        "(name=%s, status=%s)",
                        task.id,
                        container_id,
                        successful_connection.host,
                        container_name,
                        container_status,
                    )
                    self._running_tasks.add(task.id)
                    self._running_issues.add(task.issue_id)
                    resumed_task_ids.add(task.id)
                    self._worker_tasks[task.id] = asyncio.create_task(
                        self._resume_task_background(
                            task.id,
                            container_name,
                            successful_connection,
                        )
                    )
                else:
                    unavailable_task_ids.add(task.id)
                    logger.warning(
                        "Deferring task %s recovery cleanup for container %s in status %s",
                        task.id,
                        container_id,
                        container_status,
                    )

            for task in stuck_tasks:
                if task.id in resumed_task_ids:
                    continue
                if task.id in unavailable_task_ids:
                    self._running_tasks.add(task.id)
                    self._running_issues.add(task.issue_id)
                    self._worker_tasks[task.id] = asyncio.create_task(
                        self._coordinate_unavailable_recovery(task.id)
                    )
                    logger.warning(
                        "Task %s remains RUNNING with issue %s locked while Docker "
                        "recovery is retried in the background",
                        task.id,
                        task.issue_id,
                    )
                    continue
                cancellation_requested = isinstance(
                    getattr(task, "cancel_requested_at", None),
                    datetime,
                )
                task.status = (
                    TaskStatus.CANCELLED if cancellation_requested else TaskStatus.FAILED
                )
                task.error_message = (
                    "Cancelled by user; worker container is confirmed absent"
                    if cancellation_requested
                    else "Task was running when scheduler restarted (container not found)"
                )
                task.completed_at = utcnow()
                await release_issue_execution_lock(db, issue_id=task.issue_id)
                logger.warning(
                    "Marked task %s as %s after reachable Docker daemon confirmed "
                    "that its container is absent",
                    task.id,
                    task.status.value,
                )

            await db.commit()

        failed_count = len(stuck_tasks) - len(resumed_task_ids) - len(unavailable_task_ids)
        logger.info(
            "Crash recovery complete: %s resumed, %s awaiting Docker, %s marked failed",
            len(resumed_task_ids),
            len(unavailable_task_ids),
            failed_count,
        )

    async def _coordinate_unavailable_recovery(self, task_id: int) -> None:
        """Keep an unknown remote worker owned until its daemon becomes reachable."""
        attempt = 0
        try:
            while self.running:
                resume_context: tuple[str, DockerConnectionConfig] | None = None
                should_retry = False
                async with AsyncSessionLocal() as db:
                    task = await db.get(Task, task_id)
                    if task is None:
                        logger.warning(
                            "Stopping deferred Docker recovery because task %s no longer exists",
                            task_id,
                        )
                        return
                    if task.status != TaskStatus.RUNNING:
                        logger.info(
                            "Stopping deferred Docker recovery for task %s because status is %s",
                            task_id,
                            getattr(task.status, "value", task.status),
                        )
                        self._running_tasks.discard(task_id)
                        self._running_issues.discard(task.issue_id)
                        return

                    settings = get_settings()
                    container_name = (
                        f"{settings.worker_container_prefix}-{task.id}-issue{task.issue_id}"
                    )
                    container_reference = task.container_id or container_name
                    attempt += 1
                    try:
                        _docker, container, connection = await find_task_container(
                            db,
                            task,
                            settings,
                            container_reference,
                        )
                        await asyncio.to_thread(container.reload)
                    except TaskContainerNotFoundError:
                        await db.refresh(task)
                        if task.status != TaskStatus.RUNNING:
                            continue
                        cancellation_requested = isinstance(
                            getattr(task, "cancel_requested_at", None),
                            datetime,
                        )
                        task.status = (
                            TaskStatus.CANCELLED
                            if cancellation_requested
                            else TaskStatus.FAILED
                        )
                        task.error_message = (
                            "Cancelled by user; worker container is confirmed absent"
                            if cancellation_requested
                            else (
                                "Task was running when scheduler restarted; Docker later "
                                "became reachable and confirmed that its container is absent"
                            )
                        )
                        task.completed_at = utcnow()
                        await release_issue_execution_lock(db, issue_id=task.issue_id)
                        await db.commit()
                        self._running_tasks.discard(task_id)
                        self._running_issues.discard(task.issue_id)
                        logger.error(
                            "Deferred recovery marked task %s %s after container %s "
                            "was confirmed absent",
                            task_id,
                            task.status.value,
                            container_reference,
                        )
                        return
                    except (DockerConnectionsUnavailableError, TaskContainerLookupError) as exc:
                        should_retry = True
                        if attempt == 1 or attempt % 10 == 0:
                            logger.warning(
                                "Deferred Docker recovery for task %s is still waiting "
                                "for container %s (attempt=%s): %s",
                                task_id,
                                container_reference,
                                attempt,
                                exc,
                            )
                    except Exception as exc:  # noqa: BLE001
                        should_retry = True
                        logger.warning(
                            "Deferred Docker recovery for task %s could not inspect "
                            "container %s (attempt=%s): %s",
                            task_id,
                            container_reference,
                            attempt,
                            exc,
                        )
                    else:
                        await db.refresh(task)
                        if task.status != TaskStatus.RUNNING:
                            continue
                        cancellation_requested = isinstance(
                            getattr(task, "cancel_requested_at", None),
                            datetime,
                        )
                        cancellation_stop_failed = False
                        if cancellation_requested and container.status == "running":
                            try:
                                await _stop_recovered_cancelled_container(container, task_id)
                            except Exception as exc:  # noqa: BLE001
                                should_retry = True
                                cancellation_stop_failed = True
                                logger.warning(
                                    "Deferred recovery found cancelled task %s but could "
                                    "not stop container %s: %s",
                                    task_id,
                                    container_reference,
                                    exc,
                                )
                        if cancellation_stop_failed:
                            pass
                        elif container.status not in ("running", "exited"):
                            try:
                                await asyncio.to_thread(container.remove, force=True)
                            except Exception as exc:  # noqa: BLE001
                                should_retry = True
                                logger.warning(
                                    "Deferred recovery found task %s container %s in "
                                    "status %s but could not remove it: %s",
                                    task_id,
                                    container_reference,
                                    container.status,
                                    exc,
                                )
                            else:
                                task.status = (
                                    TaskStatus.CANCELLED
                                    if cancellation_requested
                                    else TaskStatus.FAILED
                                )
                                task.error_message = (
                                    "Cancelled by user; recovered worker container was removed"
                                    if cancellation_requested
                                    else (
                                        "Task worker container was not runnable after scheduler "
                                        f"recovery (status={container.status})"
                                    )
                                )
                                task.completed_at = utcnow()
                                await release_issue_execution_lock(db, issue_id=task.issue_id)
                                await db.commit()
                                self._running_tasks.discard(task_id)
                                self._running_issues.discard(task.issue_id)
                                logger.error(
                                    "Deferred recovery removed non-runnable container %s "
                                    "and marked task %s failed",
                                    container_reference,
                                    task_id,
                                )
                                return
                        else:
                            resume_context = (container.name, connection)
                            logger.info(
                                "Docker daemon recovered for task %s after %s attempt(s); "
                                "resuming container %s on %s (status=%s)",
                                task_id,
                                attempt,
                                container.name,
                                connection.host,
                                container.status,
                            )

                if resume_context is not None:
                    await self._resume_task_background(task_id, *resume_context)
                    return
                if should_retry:
                    await asyncio.sleep(_RECOVERY_UNAVAILABLE_RETRY_SECONDS)
        finally:
            current = asyncio.current_task()
            if self._worker_tasks.get(task_id) is current:
                self._worker_tasks.pop(task_id, None)
            logger.info("Deferred Docker recovery coordinator stopped for task %s", task_id)

    async def _resume_task_background(
        self,
        task_id: int,
        container_name: str,
        recovery_connection: DockerConnectionConfig | None = None,
    ) -> None:
        """Resume monitoring a task in the background thread pool."""
        self._active_worker_threads += 1
        t_submit = time.time()
        logger.info(
            f"Task {task_id} resume submitted to thread pool "
            f"(active_threads={self._active_worker_threads}, "
            f"max_workers={_worker_executor._max_workers})"
        )
        try:
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                _worker_executor,
                _run_worker_resume_task,
                task_id,
                container_name,
                recovery_connection,
            )
            elapsed = time.time() - t_submit
            if success:
                logger.info(
                    f"Resumed task {task_id} completed successfully (total={elapsed:.0f}s)"
                )
            else:
                logger.error(
                    f"Resumed task {task_id} failed (total={elapsed:.0f}s)"
                )
        except Exception as e:
            logger.exception(f"Resumed task {task_id} failed with exception: {e}")
            await self._mark_worker_bootstrap_failed(task_id, e)
        finally:
            self._active_worker_threads -= 1
            self._worker_tasks.pop(task_id, None)
            self._terminal_worker_seen_at.pop(task_id, None)
            self._running_tasks.discard(task_id)
            try:
                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(Task).where(Task.id == task_id)
                    )
                    task = result.scalar_one_or_none()
                    if task:
                        lock_result = await db.execute(
                            select(IssueExecutionLock).where(
                                IssueExecutionLock.issue_id == task.issue_id
                            )
                        )
                        lock = lock_result.scalar_one_or_none()
                        if lock is None or lock.task_id == task_id:
                            self._running_issues.discard(task.issue_id)
                            await release_issue_execution_lock(db, issue_id=task.issue_id)
                            await db.commit()
                            await self._maybe_complete_issue(db, task.issue_id)
            except Exception:
                logger.exception("Failed to release lock for resumed task %s", task_id)


# Singleton scheduler instance
_scheduler: Scheduler | None = None


def get_scheduler() -> Scheduler:
    """Get singleton scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler


async def start_scheduler() -> None:
    """Start the scheduler in background."""
    scheduler = get_scheduler()
    await scheduler.start()


async def stop_scheduler() -> None:
    """Stop the scheduler."""
    if _scheduler:
        await _scheduler.stop()


def _run_worker_task(task_id: int) -> bool:
    """Run worker task in a separate thread with its own event loop.

    This function creates a new asyncio event loop and database connection for the thread.

    Args:
        task_id: Task ID to execute

    Returns:
        True if successful, False otherwise
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database import _database_url

    # Create new event loop for this thread BEFORE creating the engine,
    # so asyncpg binds to this thread's loop rather than the scheduler's main loop.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    engine = create_async_engine(
        _database_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
    )

    ThreadSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    from app.core.worker import WorkerExecutor

    async def run_task():
        async with ThreadSessionLocal() as db:
            worker = WorkerExecutor(session_factory=ThreadSessionLocal)
            return await worker.execute_task(db, task_id)

    try:
        return loop.run_until_complete(run_task())
    finally:
        try:
            loop.run_until_complete(engine.dispose())
        finally:
            asyncio.set_event_loop(None)
            loop.close()


def _run_worker_resume_task(
    task_id: int,
    container_name: str,
    recovery_connection: DockerConnectionConfig | None = None,
) -> bool:
    """Resume monitoring a worker task in a separate thread with its own event loop.

    Similar to _run_worker_task but calls WorkerExecutor.resume_task()
    which attaches to an existing container instead of creating a new one.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database import _database_url

    # Create new event loop for this thread BEFORE creating the engine,
    # so asyncpg binds to this thread's loop rather than the scheduler's main loop.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    engine = create_async_engine(
        _database_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
    )

    ThreadSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    from app.core.worker import WorkerExecutor

    async def run_task():
        async with ThreadSessionLocal() as db:
            if recovery_connection is None:
                worker = WorkerExecutor(session_factory=ThreadSessionLocal)
            else:
                worker = WorkerExecutor(
                    docker_client=get_docker_client(recovery_connection),
                    session_factory=ThreadSessionLocal,
                )
            return await worker.resume_task(db, task_id, container_name)

    try:
        return loop.run_until_complete(run_task())
    finally:
        try:
            loop.run_until_complete(engine.dispose())
        finally:
            asyncio.set_event_loop(None)
            loop.close()
