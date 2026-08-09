"""Task merge-request statistics routes."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.change_stats import validate_change_statistics
from app.core.utcnow import utcnow
from app.database import get_db
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access,
    require_project_access_scope,
)
from app.models import Issue, Task

logger = logging.getLogger(__name__)
router = APIRouter()

_EMPTY_STATS = {"additions": 0, "deletions": 0, "total": 0}


@router.get("/tasks/{task_id}/stats")
async def get_task_stats(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Get MR statistics, falling back to GitLab when no values are persisted.

    Persisted values (including real zeros) are returned whenever
    ``change_stats_recorded_at`` is set; only then does the response reflect a
    known result instead of a GitLab re-query (design §6.4).
    """
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    require_project_access(task.project_id, access_scope)

    if task.change_stats_recorded_at is not None:
        return {
            "additions": task.additions,
            "deletions": task.deletions,
            "total": task.total_changes,
        }

    if task.additions > 0 or task.deletions > 0 or task.total_changes > 0:
        return {
            "additions": task.additions,
            "deletions": task.deletions,
            "total": task.total_changes,
        }

    issue_result = await db.execute(select(Issue).where(Issue.id == task.issue_id))
    issue = issue_result.scalar_one_or_none()
    merge_request_iid = issue.merge_request_iid if issue else None
    if not merge_request_iid:
        return _EMPTY_STATS.copy()

    from app.core.gitlab_client import get_gitlab_client

    stats = await asyncio.to_thread(
        get_gitlab_client().get_merge_request_stats,
        task.project_id,
        merge_request_iid,
    )
    return stats or _EMPTY_STATS.copy()


@router.patch("/tasks/{task_id}/stats")
async def update_task_stats(
    task_id: int,
    additions: int,
    deletions: int,
    total: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Persist MR statistics for a task.

    Rejects negative or inconsistent triples (400) and takes a Task row lock so
    writes serialize with deletion archiving (design §6.4, §7).
    """
    result = await db.execute(
        select(Task).where(Task.id == task_id).with_for_update()
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    require_project_access(task.project_id, access_scope)

    error = validate_change_statistics(additions, deletions, total)
    if error is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error,
        )

    task.additions = additions
    task.deletions = deletions
    task.total_changes = total
    task.change_stats_recorded_at = utcnow()
    await db.commit()

    logger.info(f"Task {task_id} stats updated: +{additions} -{deletions} ({total} total)")
    return {
        "status": "success",
        "message": f"Task {task_id} stats updated",
        "additions": additions,
        "deletions": deletions,
        "total": total,
    }
