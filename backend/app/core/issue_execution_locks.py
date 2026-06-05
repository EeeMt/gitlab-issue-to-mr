"""Database-backed issue execution locks."""

from __future__ import annotations

import inspect
import logging

from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utcnow import utcnow
from app.models import IssueExecutionLock, Task, TaskStatus

logger = logging.getLogger(__name__)
_TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def acquire_issue_execution_lock(db: AsyncSession, task: Task) -> bool:
    """Acquire the issue-level execution lock for a task."""
    if task.issue_id is None:
        return True

    issue_id = task.issue_id
    task_id = task.id
    try:
        await _maybe_await(db.execute(
            insert(IssueExecutionLock).values(
                issue_id=issue_id,
                task_id=task_id,
                acquired_at=utcnow(),
                heartbeat_at=None,
            )
        ))
        await _maybe_await(db.flush())
        return True
    except IntegrityError:
        await _maybe_await(db.rollback())
        logger.info(
            "Issue %s is already locked; task %s will wait",
            issue_id,
            task_id,
        )
        return False


async def release_issue_execution_lock(
    db: AsyncSession,
    *,
    issue_id: int | None,
) -> None:
    """Release the issue-level execution lock if the task has an issue."""
    if issue_id is None:
        return

    await _maybe_await(
        db.execute(delete(IssueExecutionLock).where(IssueExecutionLock.issue_id == issue_id))
    )


async def cleanup_inactive_issue_execution_locks(db: AsyncSession) -> int:
    """Delete locks whose task is missing or terminal."""
    result = await db.execute(select(IssueExecutionLock))
    locks = list(result.scalars().all())
    if not locks:
        return 0

    task_ids = [lock.task_id for lock in locks]
    task_result = await db.execute(select(Task).where(Task.id.in_(task_ids)))
    tasks_by_id = {task.id: task for task in task_result.scalars().all()}

    stale_issue_ids = [
        lock.issue_id
        for lock in locks
        if (task := tasks_by_id.get(lock.task_id)) is None
        or task.status in _TERMINAL_STATUSES
    ]
    if not stale_issue_ids:
        return 0

    await db.execute(
        delete(IssueExecutionLock).where(IssueExecutionLock.issue_id.in_(stale_issue_ids))
    )
    return len(stale_issue_ids)
