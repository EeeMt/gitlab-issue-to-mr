"""Statistics API endpoints."""

import logging
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, false
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
from app.models import Task, TaskStatus

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Get task statistics.

    Returns:
        Statistics object
    """
    # Total count
    base_query = select(Task.id)
    if not access_scope.is_unrestricted:
        allowed_project_ids = access_scope.accessible_project_ids
        if not allowed_project_ids:
            base_query = base_query.where(false())
        else:
            base_query = base_query.where(Task.project_id.in_(allowed_project_ids))

    total_result = await db.execute(select(func.count()).select_from(base_query.subquery()))
    total = total_result.scalar() or 0

    # Count by status
    status_counts = {}
    for status_value in TaskStatus:
        result = await db.execute(
            select(func.count()).select_from(
                base_query.where(Task.status == status_value).subquery()
            )
        )
        status_counts[status_value.value] = result.scalar() or 0

    return {
        "total": total,
        "pending": status_counts.get("pending", 0),
        "queued": status_counts.get("queued", 0),
        "running": status_counts.get("running", 0),
        "completed": status_counts.get("completed", 0),
        "failed": status_counts.get("failed", 0),
        "cancelled": status_counts.get("cancelled", 0),
    }
