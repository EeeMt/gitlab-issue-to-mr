"""Task scheduler for queue management."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Set

from sqlalchemy import case, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings as get_settings
from app.core.docker_client import get_docker_client
from app.core.session import cleanup_stale_sessions
from app.core.utcnow import utcnow
from app.core.worker import WorkerExecutor
from app.database import AsyncSessionLocal
from app.models import Task, TaskStatus, Issue, IssueStatus
from app.runtime_config import load_runtime_config_from_db

logger = logging.getLogger(__name__)
_SESSION_CLEANUP_INTERVAL_SECONDS = 3600

# Thread pool for running worker tasks (to avoid blocking the event loop)
_worker_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="worker-")


WORKER_CONTAINER_PATTERN = re.compile(r"^codify-(\d+)-issue(\d+)$")


def _extract_task_id(container_name: str) -> int | None:
    """Extract task_id from a worker container name like codify-123-issue456."""
    m = WORKER_CONTAINER_PATTERN.match(container_name)
    return int(m.group(1)) if m else None


class Scheduler:
    """Task scheduler with priority queue and concurrency control."""

    def __init__(self) -> None:
        self.running = False
        self._running_tasks: Set[int] = set()  # task_ids currently running
        self._running_issues: Set[int] = set()  # issue_ids with running tasks
        self._last_session_cleanup_at = 0.0

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
            except Exception as e:
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
            if task.issue_id is not None:
                if task.issue_id in self._running_issues:
                    logger.debug(f"Issue {task.issue_id} already running, skipping")
                    return

            # Execute task
            await self._execute_task(db, task)

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

    async def _get_running_count(self, db: AsyncSession) -> int:
        """Get count of currently running tasks."""
        result = await db.execute(
            select(func.count(Task.id)).where(Task.status == TaskStatus.RUNNING)
        )
        return result.scalar() or 0

    async def _get_next_task(self, db: AsyncSession) -> Task | None:
        """Get the next task to execute based on priority and scheduled time.

        Ordering:
        1. priority ASC — P0(0) runs before P1(1) before P2(2)
        2. scheduled tasks before immediate — users who booked a slot
           have a reasonable expectation their task runs on time
        3. scheduled_at ASC — earlier due times first
        4. created_at ASC — FIFO tiebreaker
        """
        now = utcnow()

        result = await db.execute(
            select(Task)
            .where(
                Task.status.in_([TaskStatus.PENDING, TaskStatus.QUEUED]),
                (Task.scheduled_at == None) | (Task.scheduled_at <= now)
            )
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
        logger.info(f"Executing task {task.id} for issue {task.issue_id}")

        # Mark as running
        self._running_tasks.add(task.id)
        if task.issue_id is not None:
            self._running_issues.add(task.issue_id)

        try:
            # Update status to RUNNING
            task.status = TaskStatus.RUNNING
            task.started_at = utcnow()
            await db.commit()

            # Auto-transition issue to IN_PROGRESS
            if task.issue_id is not None:
                await self._transition_issue_to_in_progress(db, task.issue_id)

            # Execute via worker in a thread pool WITHOUT waiting
            asyncio.create_task(self._run_task_background(task.id))
            logger.info(f"Task {task.id} submitted to thread pool")

        except Exception as e:
            logger.exception(f"Task {task.id} failed with exception")
            task.status = TaskStatus.FAILED
            task.error_message = str(e)[:500]
            task.completed_at = utcnow()
            await db.commit()

            # Clean up tracking
            self._running_tasks.discard(task.id)
            if task.issue_id is not None:
                self._running_issues.discard(task.issue_id)

    async def _transition_issue_to_in_progress(self, db: AsyncSession, issue_id: int) -> None:
        """Auto-transition issue OPEN/COMPLETED → IN_PROGRESS when a task starts running."""
        try:
            issue = await db.get(Issue, issue_id)
            if issue and issue.status in (IssueStatus.OPEN.value, IssueStatus.COMPLETED.value):
                issue.status = IssueStatus.IN_PROGRESS.value
                await db.commit()
                logger.info(f"Issue {issue_id} auto-transitioned to IN_PROGRESS")
        except Exception as e:
            logger.warning(f"Failed to transition issue {issue_id}: {e}")

    async def _run_task_background(self, task_id: int) -> None:
        """Run task in background thread pool."""
        issue_key = None
        try:
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                _worker_executor,
                _run_worker_task,
                task_id,
            )

            if success:
                logger.info(f"Task {task_id} completed successfully")
            else:
                logger.error(f"Task {task_id} failed")

        except Exception as e:
            logger.exception(f"Task {task_id} failed with exception in background")

        finally:
            # Clean up tracking
            self._running_tasks.discard(task_id)
            try:
                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(Task).where(Task.id == task_id)
                    )
                    task = result.scalar_one_or_none()
                    if task and task.issue_id is not None:
                        self._running_issues.discard(task.issue_id)
                        # Auto-transition issue to COMPLETED if all tasks done
                        await self._maybe_complete_issue(db, task.issue_id)
            except Exception:
                pass

    async def _maybe_complete_issue(self, db: AsyncSession, issue_id: int) -> None:
        """Auto-transition issue IN_PROGRESS → COMPLETED when last active task completes."""
        try:
            active_count = await db.execute(
                select(func.count(Task.id)).where(
                    Task.issue_id == issue_id,
                    Task.status.in_([
                        TaskStatus.PENDING,
                        TaskStatus.QUEUED,
                        TaskStatus.RUNNING,
                    ]),
                )
            )
            if active_count.scalar() == 0:
                # Check if there's at least one completed task
                completed_count = await db.execute(
                    select(func.count(Task.id)).where(
                        Task.issue_id == issue_id,
                        Task.status == TaskStatus.COMPLETED,
                    )
                )
                if completed_count.scalar() > 0:
                    issue = await db.get(Issue, issue_id)
                    if issue and issue.status == IssueStatus.IN_PROGRESS.value:
                        issue.status = IssueStatus.COMPLETED.value
                        await db.commit()
                        logger.info(f"Issue {issue_id} auto-transitioned to COMPLETED")
        except Exception as e:
            logger.warning(f"Failed to check issue {issue_id} completion: {e}")

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
            # Find all tasks that are still marked RUNNING in the DB
            result = await db.execute(
                select(Task).where(Task.status == TaskStatus.RUNNING)
            )
            stuck_tasks = result.scalars().all()
            running_task_map = {t.id: t for t in stuck_tasks}

            if stuck_tasks:
                logger.warning(f"Found {len(stuck_tasks)} tasks in RUNNING status")

            # Discover worker containers and cross-reference with DB
            resumed_task_ids: set[int] = set()
            try:
                docker = get_docker_client()
                all_containers = docker.client.containers.list(
                    all=True,
                    filters={"name": "codify-"}
                )

                for container in all_containers:
                    if not WORKER_CONTAINER_PATTERN.match(container.name):
                        continue

                    task_id = _extract_task_id(container.name)
                    c_status = container.status

                    if task_id is not None and task_id in running_task_map:
                        if c_status in ("running", "exited"):
                            # Legitimate worker (running or just finished) — resume monitoring.
                            task = running_task_map[task_id]
                            logger.info(
                                f"Resuming task {task_id} (container {container.name}, "
                                f"status={c_status}, issue_id={task.issue_id})"
                            )
                            self._running_tasks.add(task_id)
                            if task.issue_id is not None:
                                self._running_issues.add(task.issue_id)
                            resumed_task_ids.add(task_id)
                            asyncio.create_task(
                                self._resume_task_background(task_id, container.name)
                            )
                        else:
                            # Container in weird state (created, dead, etc.) — remove and let task fail
                            logger.warning(
                                f"Removing {c_status} container for task {task_id}: {container.name}"
                            )
                            try:
                                container.remove(force=True)
                            except Exception as e:
                                logger.warning(f"Failed to remove container {container.name}: {e}")
                    else:
                        # No matching RUNNING task — true orphan
                        logger.warning(
                            f"Removing {c_status} orphan container: {container.name} "
                            f"(task_id={task_id}, in_db={task_id in running_task_map if task_id else 'N/A'})"
                        )
                        try:
                            container.remove(force=(c_status == "running"))
                        except Exception as e:
                            logger.warning(
                                f"Failed to remove container {container.name}: {e}"
                            )

            except Exception as e:
                logger.warning(f"Failed to enumerate containers: {e}")

            # Mark truly stuck tasks as failed (RUNNING in DB but no container)
            for task in stuck_tasks:
                if task.id in resumed_task_ids:
                    continue
                task.status = TaskStatus.FAILED
                task.error_message = "Task was running when scheduler restarted (container not found)"
                task.completed_at = utcnow()
                logger.warning(f"Marked task {task.id} as failed (no running container)")

            await db.commit()

        logger.info(
            f"Crash recovery complete: {len(resumed_task_ids)} resumed, "
            f"{len(stuck_tasks) - len(resumed_task_ids)} marked failed"
        )

    async def _resume_task_background(self, task_id: int, container_name: str) -> None:
        """Resume monitoring a task in the background thread pool."""
        try:
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                _worker_executor,
                _run_worker_resume_task,
                task_id,
                container_name,
            )
            if success:
                logger.info(f"Resumed task {task_id} completed successfully")
            else:
                logger.error(f"Resumed task {task_id} failed")
        except Exception as e:
            logger.exception(f"Resumed task {task_id} failed with exception: {e}")
        finally:
            self._running_tasks.discard(task_id)
            try:
                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(Task).where(Task.id == task_id)
                    )
                    task = result.scalar_one_or_none()
                    if task and task.issue_id is not None:
                        self._running_issues.discard(task.issue_id)
                        await self._maybe_complete_issue(db, task.issue_id)
            except Exception:
                pass


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
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    # Get database URL from settings
    from app.config import get_settings
    settings = get_settings()
    from app.database import _database_url

    # Create a new engine for this thread (not shared with main event loop)
    engine = create_async_engine(
        _database_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
    )

    # Create session maker for this engine
    ThreadSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Import worker
    from app.core.worker import WorkerExecutor

    async def run_task():
        async with ThreadSessionLocal() as db:
            worker = WorkerExecutor()
            return await worker.execute_task(db, task_id)

    # Create new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        return loop.run_until_complete(run_task())
    finally:
        try:
            loop.run_until_complete(engine.dispose())
        finally:
            asyncio.set_event_loop(None)
            loop.close()


def _run_worker_resume_task(task_id: int, container_name: str) -> bool:
    """Resume monitoring a worker task in a separate thread with its own event loop.

    Similar to _run_worker_task but calls WorkerExecutor.resume_task()
    which attaches to an existing container instead of creating a new one.
    """
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    from app.database import _database_url

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
            worker = WorkerExecutor()
            return await worker.resume_task(db, task_id, container_name)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        return loop.run_until_complete(run_task())
    finally:
        try:
            loop.run_until_complete(engine.dispose())
        finally:
            asyncio.set_event_loop(None)
            loop.close()
