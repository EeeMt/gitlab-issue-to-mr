"""Task operation helpers for the Task API."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from fastapi import HTTPException, status

from app.core.mattermost_notifications import (
    MATTERMOST_EVENT_TASK_CANCELLED,
    MATTERMOST_EVENT_TASK_EXECUTE_NOW,
    MATTERMOST_EVENT_TASK_RESCHEDULED,
    MATTERMOST_EVENT_TASK_RETRY_SCHEDULED,
    notify_task_event,
)
from app.core.scheduling import normalize_scheduled_datetime
from app.core.utcnow import utcnow
from app.dependencies.project_access import ProjectAccessScope, require_project_access
from app.models import Task, TaskStatus

import logging

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import User

logger = logging.getLogger(__name__)


async def get_task_with_access_check(
    task_id: int,
    db: "AsyncSession",
    access_scope: ProjectAccessScope,
    current_user: Optional["User"] = None,
    require_operator: bool = True,
) -> Task:
    """Get a task by ID with access control checks.

    Args:
        task_id: Task ID to look up
        db: Database session
        access_scope: Project access scope for authorization
        current_user: Current authenticated user (optional)
        require_operator: Whether to require task operator permission

    Returns:
        Task model instance

    Raises:
        HTTPException: If task not found or access denied
    """
    from sqlalchemy import select

    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    require_project_access(task.project_id, access_scope)

    if require_operator:
        from app.core.task_helpers import _require_task_operator

        _require_task_operator(task, current_user)

    return task


def validate_task_status_for_cancel(task: Task) -> None:
    """Validate that task can be cancelled.

    Args:
        task: Task to validate

    Raises:
        HTTPException: If task cannot be cancelled
    """
    if task.status not in [TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel task with status {task.status.value}",
        )


def validate_task_status_for_retry(task: Task) -> None:
    """Validate that task can be retried.

    Args:
        task: Task to validate

    Raises:
        HTTPException: If task cannot be retried
    """
    if task.status not in [TaskStatus.FAILED, TaskStatus.CANCELLED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot retry task with status {task.status.value}",
        )


def validate_task_status_for_execute(task: Task) -> None:
    """Validate that task can be executed immediately.

    Args:
        task: Task to validate

    Raises:
        HTTPException: If task cannot be executed
    """
    if task.status not in (TaskStatus.PENDING, TaskStatus.QUEUED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task must be in PENDING or QUEUED status to execute immediately, current: {task.status.value}",
        )


def validate_task_status_for_reschedule(task: Task) -> None:
    """Validate that task can be rescheduled.

    Args:
        task: Task to validate

    Raises:
        HTTPException: If task cannot be rescheduled
    """
    if task.status not in (TaskStatus.PENDING, TaskStatus.QUEUED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task must be in PENDING or QUEUED status to reschedule, current: {task.status.value}",
        )

    if task.status == TaskStatus.PENDING and task.scheduled_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only scheduled or queued tasks can update their scheduled time",
        )


def validate_scheduled_datetime_in_future(scheduled_datetime: datetime) -> datetime:
    """Validate that a scheduled datetime is in the future.

    Args:
        scheduled_datetime: Datetime to validate

    Returns:
        Normalized datetime

    Raises:
        HTTPException: If datetime is not in the future
    """
    normalized = normalize_scheduled_datetime(scheduled_datetime)
    if normalized is None or normalized <= utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Scheduled datetime must be in the future for manual tasks",
        )
    return normalized


async def notify_task_cancelled(task: Task) -> None:
    """Send notification for cancelled task.

    Args:
        task: Cancelled task
    """
    try:
        await notify_task_event(task, MATTERMOST_EVENT_TASK_CANCELLED)
    except Exception as exc:
        logger.warning("Failed to send Mattermost cancel notification for task %s: %s", task.id, exc)


async def notify_task_retried(task: Task, previous_scheduled_at: Optional[datetime], scheduled_at: Optional[datetime]) -> None:
    """Send notification for retried task.

    Args:
        task: Retried task
        previous_scheduled_at: Previous scheduled time
        scheduled_at: New scheduled time
    """
    try:
        await notify_task_event(
            task,
            MATTERMOST_EVENT_TASK_RETRY_SCHEDULED,
            context={
                "previous_scheduled_at": previous_scheduled_at,
                "scheduled_at": scheduled_at,
            },
        )
    except Exception as exc:
        logger.warning("Failed to send Mattermost retry notification for task %s: %s", task.id, exc)


async def notify_task_execute_now(task: Task, previous_scheduled_at: Optional[datetime]) -> None:
    """Send notification for immediate execution.

    Args:
        task: Task being executed
        previous_scheduled_at: Previous scheduled time
    """
    try:
        await notify_task_event(
            task,
            MATTERMOST_EVENT_TASK_EXECUTE_NOW,
            context={
                "previous_scheduled_at": previous_scheduled_at,
                "scheduled_at": None,
            },
        )
    except Exception as exc:
        logger.warning("Failed to send Mattermost execute-now notification for task %s: %s", task.id, exc)


async def notify_task_rescheduled(task: Task, previous_scheduled_at: Optional[datetime], scheduled_at: datetime) -> None:
    """Send notification for rescheduled task.

    Args:
        task: Rescheduled task
        previous_scheduled_at: Previous scheduled time
        scheduled_at: New scheduled time
    """
    try:
        await notify_task_event(
            task,
            MATTERMOST_EVENT_TASK_RESCHEDULED,
            context={
                "previous_scheduled_at": previous_scheduled_at,
                "scheduled_at": scheduled_at,
            },
        )
    except Exception as exc:
        logger.warning("Failed to send Mattermost reschedule notification for task %s: %s", task.id, exc)
