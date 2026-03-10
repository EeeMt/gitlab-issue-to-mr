"""Statistics API endpoints."""

import logging
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Task, TaskStatus

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Get task statistics.

    Returns:
        Statistics object
    """
    # Total count
    total_result = await db.execute(select(func.count(Task.id)))
    total = total_result.scalar() or 0

    # Count by status
    status_counts = {}
    for status_value in TaskStatus:
        result = await db.execute(
            select(func.count(Task.id)).where(Task.status == status_value)
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
