"""Task scheduler for queue management."""

import asyncio
import logging
import re
from datetime import datetime
from typing import Set

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.docker_client import get_docker_client
from app.core.worker import WorkerExecutor
from app.database import AsyncSessionLocal
from app.models import Task, TaskStatus

logger = logging.getLogger(__name__)
settings = get_settings()
WORKER_CONTAINER_PATTERN = re.compile(r"^gimr-\d+-p\d+-i\d+$")


class Scheduler:
    """Task scheduler with priority queue and concurrency control."""

    def __init__(self) -> None:
        self.running = False
        self._running_tasks: Set[int] = set()  # task_ids currently running
        self._running_issues: Set[str] = set()  # "project_id:issue_iid" pairs

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
            await asyncio.sleep(settings.scheduler_interval)

        logger.info("Scheduler stopped")

    async def stop(self) -> None:
        """Stop the scheduler."""
        logger.info("Stopping scheduler...")
        self.running = False

    async def _run_cycle(self) -> None:
        """Run one scheduler cycle."""
        async with AsyncSessionLocal() as db:
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

            # Check issue mutex
            issue_key = f"{task.project_id}:{task.issue_iid}"
            if issue_key in self._running_issues:
                logger.debug(f"Issue {issue_key} already running, skipping")
                return

            # Execute task
            await self._execute_task(db, task, issue_key)

    async def _get_running_count(self, db: AsyncSession) -> int:
        """Get count of currently running tasks."""
        result = await db.execute(
            select(func.count(Task.id)).where(Task.status == TaskStatus.RUNNING)
        )
        return result.scalar() or 0

    async def _get_next_task(self, db: AsyncSession) -> Task | None:
        """Get the next task to execute based on priority and scheduled time."""
        now = datetime.utcnow()

        # Query for next task:
        # - status in (PENDING, QUEUED)
        # - scheduled_at <= now (or null)
        # - order by priority DESC, scheduled_at ASC, created_at ASC
        result = await db.execute(
            select(Task)
            .where(
                Task.status.in_([TaskStatus.PENDING, TaskStatus.QUEUED]),
                (Task.scheduled_at == None) | (Task.scheduled_at <= now)
            )
            .order_by(Task.priority.desc(), Task.scheduled_at.asc(), Task.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _execute_task(self, db: AsyncSession, task: Task, issue_key: str) -> None:
        """Execute a task."""
        logger.info(f"Executing task {task.id} for issue {issue_key}")

        # Mark as running
        self._running_tasks.add(task.id)
        self._running_issues.add(issue_key)

        try:
            # Update status to RUNNING
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            await db.commit()

            # Execute via worker
            worker = WorkerExecutor()
            success = await worker.execute_task(db, task.id)

            if success:
                logger.info(f"Task {task.id} completed successfully")
            else:
                logger.error(f"Task {task.id} failed")

        except Exception as e:
            logger.exception(f"Task {task.id} failed with exception")
            task.status = TaskStatus.FAILED
            task.error_message = str(e)[:500]
            task.completed_at = datetime.utcnow()
            await db.commit()

        finally:
            # Clean up tracking
            self._running_tasks.discard(task.id)
            self._running_issues.discard(issue_key)

    async def _crash_recovery(self) -> None:
        """Recover from crashes: clean up stuck tasks and containers."""
        logger.info("Running crash recovery...")

        async with AsyncSessionLocal() as db:
            # Find stuck running tasks (started but not completed)
            result = await db.execute(
                select(Task).where(Task.status == TaskStatus.RUNNING)
            )
            stuck_tasks = result.scalars().all()

            if stuck_tasks:
                logger.warning(f"Found {len(stuck_tasks)} stuck running tasks")

            # Clean up containers
            try:
                docker = get_docker_client()
                all_containers = docker.client.containers.list(
                    all=True,
                    filters={"name": "gimr-"}
                )

                for container in all_containers:
                    # Only manage worker containers: gimr-{task_id}-p{project_id}-i{issue_iid}
                    # Avoid touching compose-managed service containers like gimr-backend/gimr-postgres.
                    if not WORKER_CONTAINER_PATTERN.match(container.name):
                        continue

                    # Skip containers that are supposed to be running
                    if container.status == "running":
                        logger.warning(f"Removing running container: {container.name}")
                        container.remove(force=True)
                    elif container.status == "exited":
                        container.remove()

                logger.info(f"Cleaned up {len(all_containers)} containers")

            except Exception as e:
                logger.warning(f"Failed to clean up containers: {e}")

            # Mark stuck tasks as failed
            for task in stuck_tasks:
                task.status = TaskStatus.FAILED
                task.error_message = "Task was running when service crashed"
                task.completed_at = datetime.utcnow()
                logger.warning(f"Marked task {task.id} as failed")

            await db.commit()

        logger.info("Crash recovery complete")


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
