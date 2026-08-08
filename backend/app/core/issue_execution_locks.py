"""Database-backed issue execution locks."""

from __future__ import annotations

import inspect
import logging

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
    """Acquire the issue-level execution lock for a task.

    Uses ``INSERT ... ON CONFLICT DO NOTHING RETURNING`` (spec §6.6) so a unique
    conflict does NOT roll back an outer transaction that already holds the Issue
    row lock or has mutated ordering state.
    """
    stmt = (
        pg_insert(IssueExecutionLock)
        .values(
            issue_id=task.issue_id,
            task_id=task.id,
            acquired_at=utcnow(),
            heartbeat_at=None,
        )
        .on_conflict_do_nothing(index_elements=[IssueExecutionLock.issue_id])
        .returning(IssueExecutionLock.task_id)
    )
    result = await _maybe_await(db.execute(stmt))
    await _maybe_await(db.flush())
    return result.scalar_one_or_none() is not None


async def release_issue_execution_lock(
    db: AsyncSession,
    *,
    issue_id: int,
    owner_task_id: int,
) -> bool:
    """Release the issue-level execution lock only when the caller still owns it.

    The delete is scoped to ``(issue_id, owner_task_id)`` so a late finalizer can
    never delete a lock that a newer task re-acquired for the same Issue. Returns
    True when this call removed the lock, False when it was already gone or owned
    by another task.
    """
    result = await _maybe_await(
        db.execute(
            delete(IssueExecutionLock).where(
                IssueExecutionLock.issue_id == issue_id,
                IssueExecutionLock.task_id == owner_task_id,
            )
        )
    )
    return bool(result.rowcount)


async def cleanup_inactive_issue_execution_locks(db: AsyncSession) -> int:
    """Delete locks whose task is missing or fully terminal.

    A terminal task with a durable container reference still owns its Issue: the
    container may need to be stopped and its raw logs finalized before another
    task can safely mutate the same daemon-local workspace.
    """
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
        or (
            task.status in _TERMINAL_STATUSES
            and getattr(task, "container_id", None) is None
        )
    ]
    if not stale_issue_ids:
        return 0

    await db.execute(
        delete(IssueExecutionLock).where(IssueExecutionLock.issue_id.in_(stale_issue_ids))
    )
    return len(stale_issue_ids)
