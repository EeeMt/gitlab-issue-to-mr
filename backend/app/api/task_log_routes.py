"""Structured task-log HTTP and SSE routes."""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.task_log_stream import generate_task_log_events
from app.database import AsyncSessionLocal, get_db
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access,
    require_project_access_scope,
)
from app.models import Task, TaskLog

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/tasks/{task_id}/logs")
async def get_task_logs(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Get structured task logs."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    require_project_access(task.project_id, access_scope)

    result = await db.execute(
        select(TaskLog).where(TaskLog.task_id == task_id).order_by(TaskLog.created_at.asc())
    )
    return [
        {
            "id": log.id,
            "task_id": log.task_id,
            "log_level": log.log_level,
            "log_type": log.log_type,
            "metadata": json.loads(log.log_metadata) if log.log_metadata else None,
            "message": log.message,
            "created_at": log.created_at.isoformat(),
        }
        for log in result.scalars().all()
    ]


@router.get("/tasks/{task_id}/log-stream")
async def stream_task_logs(
    task_id: int,
    since_id: int = 0,
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Stream task log entries as batched Server-Sent Events."""
    async with AsyncSessionLocal() as init_db:
        result = await init_db.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    require_project_access(task.project_id, access_scope)

    return StreamingResponse(
        generate_task_log_events(
            task_id,
            since_id,
            session_factory=AsyncSessionLocal,
            sleep=asyncio.sleep,
            monotonic=time.monotonic,
            logger=logger,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
