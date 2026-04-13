"""Task management API endpoints."""

import asyncio
import json as _json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select, false
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.docker_client import get_docker_client
from app.core.projects import build_project_lookup, get_project_metadata
from app.core.scheduling import resolve_scheduled_at
from app.core.task_helpers import _serialize_task
from app.core.utcnow import utcnow
from app.database import get_db
from app.dependencies.auth import get_optional_current_user, require_page_access
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access,
    require_project_access_scope,
)
from app.models import Task, TaskLog, TaskStatus, User

from app.api.task_schemas import CreateTaskRequest, RescheduleTaskRequest, RetryTaskRequest
from app.api.task_operations import (
    get_task_with_access_check,
    notify_task_cancelled,
    notify_task_execute_now,
    notify_task_rescheduled,
    notify_task_retried,
    validate_scheduled_datetime_in_future,
    validate_task_status_for_cancel,
    validate_task_status_for_execute,
    validate_task_status_for_retry,
    validate_task_status_for_reschedule,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/tasks")
async def list_tasks(
    status: Optional[str] = None,
    project_id: Optional[int] = None,
    issue_id: Optional[int] = None,
    initiator_username: Optional[str] = None,
    page: Optional[int] = None,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """List tasks with optional filtering and pagination.

    When ``page`` is provided, returns ``{items, total, page, page_size}``.
    Without ``page``, returns a plain ``Task[]`` array (legacy behaviour).
    """
    query = select(Task).options(selectinload(Task.issue)).order_by(Task.created_at.desc())

    if status:
        # Support comma-separated status values: ?status=running,pending,queued
        status_parts = [s.strip() for s in status.split(",") if s.strip()]
        valid_statuses = []
        for part in status_parts:
            try:
                valid_statuses.append(TaskStatus(part))
            except ValueError:
                pass
        if len(valid_statuses) == 1:
            query = query.where(Task.status == valid_statuses[0])
        elif valid_statuses:
            query = query.where(Task.status.in_(valid_statuses))

    if project_id:
        query = query.where(Task.project_id == project_id)
    elif not access_scope.is_unrestricted:
        allowed_project_ids = access_scope.accessible_project_ids
        if not allowed_project_ids:
            query = query.where(false())
        else:
            query = query.where(Task.project_id.in_(allowed_project_ids))

    if initiator_username:
        query = query.where(Task.initiator_username == initiator_username)

    if issue_id:
        query = query.where(Task.issue_id == issue_id)

    project_lookup = await build_project_lookup(
        accessible_projects=access_scope.accessible_projects,
        is_unrestricted=access_scope.is_unrestricted,
    )

    # Paginated mode: return { items, total, page, page_size }
    if page is not None:
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size

        count_result = await db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar() or 0

        result = await db.execute(query.limit(page_size).offset(offset))
        tasks = result.scalars().all()

        return {
            "items": [
                _serialize_task(task, project_lookup.get(task.project_id))
                for task in tasks
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # Legacy mode: return Task[] (max 100)
    result = await db.execute(query.limit(100))
    tasks = result.scalars().all()

    return [
        _serialize_task(task, project_lookup.get(task.project_id))
        for task in tasks
    ]


@router.get("/tasks/scheduled")
async def list_scheduled_tasks(
    project_id: Optional[int] = None,
    hour_start: Optional[str] = Query(None, description="ISO datetime; filter tasks in this 1-hour window"),
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_page_access("schedule_overview")),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """List active scheduled tasks for queue analytics views.

    When hour_start is provided, returns only tasks within that 1-hour window.
    """
    query = (
        select(Task)
        .options(selectinload(Task.issue))
        .where(
            Task.scheduled_at.is_not(None),
            Task.status.in_([
                TaskStatus.PENDING,
                TaskStatus.QUEUED,
                TaskStatus.RUNNING,
            ]),
        )
        .order_by(Task.scheduled_at.asc(), Task.priority.asc(), Task.created_at.asc())
    )

    if hour_start:
        try:
            window_start = datetime.fromisoformat(hour_start.replace("Z", "+00:00"))
            if window_start.tzinfo:
                window_start = window_start.replace(tzinfo=None)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid hour_start format")
        window_end = window_start + timedelta(hours=1)
        query = query.where(Task.scheduled_at >= window_start, Task.scheduled_at < window_end)

    if project_id:
        query = query.where(Task.project_id == project_id)
    elif not access_scope.is_unrestricted:
        allowed_project_ids = access_scope.accessible_project_ids
        if not allowed_project_ids:
            query = query.where(false())
        else:
            query = query.where(Task.project_id.in_(allowed_project_ids))

    result = await db.execute(query)
    tasks = result.scalars().all()
    project_lookup = await build_project_lookup(
        accessible_projects=access_scope.accessible_projects,
        is_unrestricted=access_scope.is_unrestricted,
    )

    return [
        _serialize_task(task, project_lookup.get(task.project_id))
        for task in tasks
    ]


@router.get("/tasks/slot-capacity")
async def get_slot_capacity(
    scheduled_at: datetime,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_optional_current_user),
):
    """Check slot capacity for a given scheduled time."""
    from app.core.slot_capacity import check_slot_capacity

    info = await check_slot_capacity(db, scheduled_at)
    return {
        "hour_start": info.hour_start.isoformat(),
        "hour_end": info.hour_end.isoformat(),
        "count": info.count,
        "max": info.max,
        "is_full": info.is_full,
        "enforce": info.enforce,
    }


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get task by ID.

    Args:
        task_id: Task ID
        db: Database session

    Returns:
        Task details
    """
    t0 = time.time()
    logger.info(f"[HANDLER START] get_task/{task_id} t={t0:.3f}")
    result = await db.execute(select(Task).options(selectinload(Task.issue)).where(Task.id == task_id))
    t1 = time.time()
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )

    t2 = time.time()
    metadata = await get_project_metadata(task.project_id)
    t3 = time.time()
    result_data = _serialize_task(task, metadata)
    t4 = time.time()

    total = t4 - t0
    if total > 1.0:
        logger.warning(
            f"[SLOW get_task/{task_id}] total={total:.3f}s "
            f"db={t1-t0:.3f}s project_meta={t3-t2:.3f}s serialize={t4-t3:.3f}s "
            f"access_scope_resolved_before_handler status={task.status}"
        )

    return result_data


@router.get("/tasks/{task_id}/logs")
async def get_task_logs(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get task logs."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )

    result = await db.execute(
        select(TaskLog)
        .where(TaskLog.task_id == task_id)
        .order_by(TaskLog.created_at.asc())
    )
    logs = result.scalars().all()

    return [
        {
            "id": log.id,
            "task_id": log.task_id,
            "log_level": log.log_level,
            "log_type": log.log_type,
            "metadata": log.log_metadata,
            "message": log.message,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]


@router.get("/tasks/{task_id}/log-stream")
async def stream_task_logs(
    task_id: int,
    since_id: int = 0,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Stream task log entries as Server-Sent Events.

    Polls the database for new TaskLog entries every 1.5 seconds and streams
    them to the client as SSE events. Stops automatically once the task reaches
    a terminal state (completed/failed/cancelled) and all pending logs are sent.

    Args:
        task_id: Task ID to stream logs for
        since_id: Only return log entries with id > since_id (for resuming)
        db: Database session
        access_scope: Project access scope for authorization

    Returns:
        StreamingResponse with text/event-stream media type
    """
    # Validate task exists and user has access before starting the stream
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    require_project_access(task.project_id, access_scope)

    _TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}

    async def generate_log_events():
        cursor = since_id
        try:
            while True:
                # Fetch next batch of log entries after cursor
                log_result = await db.execute(
                    select(TaskLog)
                    .where(TaskLog.task_id == task_id, TaskLog.id > cursor)
                    .order_by(TaskLog.id.asc())
                    .limit(100)
                )
                new_logs = log_result.scalars().all()

                for log in new_logs:
                    event_data = {
                        "id": log.id,
                        "log_type": log.log_type,
                        "metadata": log.log_metadata,
                        "message": log.message,
                        "created_at": log.created_at.isoformat(),
                    }
                    yield f"data: {_json.dumps(event_data)}\n\n"
                    cursor = log.id

                # Check current task status (re-query to get fresh state)
                task_result = await db.execute(
                    select(Task.status).where(Task.id == task_id)
                )
                current_status = task_result.scalar_one_or_none()

                if current_status in _TERMINAL_STATUSES and not new_logs:
                    # Task is done and no new logs — signal completion and stop
                    yield "event: done\ndata: {}\n\n"
                    break

                # Wait before polling again
                await asyncio.sleep(1.5)

        except asyncio.CancelledError:
            # Client disconnected
            pass
        except Exception as exc:
            logger.error(f"[Task {task_id}] log-stream error: {exc}")
            yield f"data: {_json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        generate_log_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/tasks/{task_id}/stats")
async def get_task_stats(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Get MR statistics for a task.

    Args:
        task_id: Task ID
        db: Database session

    Returns:
        MR change statistics (additions, deletions, total)
    """
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    require_project_access(task.project_id, access_scope)

    # Return database stats if available (non-zero)
    if task.additions > 0 or task.deletions > 0 or task.total_changes > 0:
        return {
            "additions": task.additions,
            "deletions": task.deletions,
            "total": task.total_changes,
        }

    # Fall back to GitLab API if no database stats
    if not task.merge_request_iid:
        return {"additions": 0, "deletions": 0, "total": 0}

    from app.core.gitlab_client import get_gitlab_client
    gitlab = get_gitlab_client()

    stats = await asyncio.to_thread(
        gitlab.get_merge_request_stats,
        task.project_id,
        task.merge_request_iid,
    )

    if not stats:
        return {"additions": 0, "deletions": 0, "total": 0}

    return stats


@router.patch("/tasks/{task_id}/stats")
async def update_task_stats(
    task_id: int,
    additions: int,
    deletions: int,
    total: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Update MR statistics for a task.

    Args:
        task_id: Task ID
        additions: Number of additions
        deletions: Number of deletions
        total: Total number of changes
        db: Database session

    Returns:
        Success message
    """
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    require_project_access(task.project_id, access_scope)

    task.additions = additions
    task.deletions = deletions
    task.total_changes = total
    await db.commit()

    logger.info(f"Task {task_id} stats updated: +{additions} -{deletions} ({total} total)")

    return {
        "status": "success",
        "message": f"Task {task_id} stats updated",
        "additions": additions,
        "deletions": deletions,
        "total": total,
    }


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Cancel a task."""
    task = await get_task_with_access_check(task_id, db, access_scope, current_user)
    validate_task_status_for_cancel(task)

    task.status = TaskStatus.CANCELLED
    task.completed_at = utcnow()
    task.error_message = "Cancelled by user"
    await db.commit()
    await db.refresh(task)

    # Kill the running container (if any) to free the thread pool slot immediately
    issue_suffix = f"i{task.issue_iid}" if task.issue_iid else "manual"
    container_name = f"codify-{task_id}-p{task.project_id}-{issue_suffix}"
    try:
        docker = get_docker_client()
        container = await asyncio.to_thread(docker.client.containers.get, container_name)
        await asyncio.to_thread(container.stop, timeout=5)
        logger.info(f"Stopped container {container_name} for cancelled task {task_id}")
    except Exception:
        pass  # Container may not exist or already stopped

    await notify_task_cancelled(task)
    logger.info(f"Task {task_id} cancelled via API")

    return {"status": "success", "message": f"Task {task_id} cancelled"}


@router.post("/tasks/{task_id}/retry")
async def retry_task(
    task_id: int,
    request: Optional[RetryTaskRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Retry a failed or cancelled task by creating a new task with the same prompt.

    The original task is preserved with its error state. A new task is created
    with is_retry=True and retry_source_task_id pointing to the original.
    """
    original_task = await get_task_with_access_check(task_id, db, access_scope, current_user)
    validate_task_status_for_retry(original_task)

    # Check for existing active retry
    existing_retry_query = select(Task).where(
        Task.retry_source_task_id == task_id,
        Task.status.in_(["pending", "queued", "running"]),
    )
    existing_retry_result = await db.execute(existing_retry_query)
    existing_retry = existing_retry_result.scalar_one_or_none()
    if existing_retry:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An active retry task (#{existing_retry.id}) already exists for task #{task_id}",
        )

    scheduled_at: Optional[datetime] = None
    if request and request.scheduled_datetime is not None:
        scheduled_at = validate_scheduled_datetime_in_future(request.scheduled_datetime)

    # Check slot capacity for scheduled retries
    if scheduled_at is not None:
        from app.core.slot_capacity import check_slot_capacity, slot_full_detail_dict
        slot_info = await check_slot_capacity(db, scheduled_at, exclude_task_id=task_id, acquire_lock=True)
        if slot_info.is_full and slot_info.enforce:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=slot_full_detail_dict(slot_info),
            )

    new_task = Task(
        issue_id=original_task.issue_id,
        project_id=original_task.project_id,
        user_prompt=original_task.user_prompt,
        priority=original_task.priority,
        scheduled_at=scheduled_at,
        is_retry=True,
        retry_source_task_id=original_task.id,
        initiator_user_id=current_user.id if current_user is not None else None,
        initiator_gitlab_user_id=current_user.gitlab_user_id if current_user is not None else None,
        initiator_username=current_user.username if current_user is not None else None,
    )
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)

    await notify_task_retried(new_task, None, scheduled_at)
    action = f"scheduled for retry at {scheduled_at}" if scheduled_at else "created as retry"
    logger.info(f"Task {new_task.id} {action} (retry of task {task_id})")

    return _serialize_task(new_task, await get_project_metadata(new_task.project_id))


@router.post("/tasks/{task_id}/execute")
async def execute_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Trigger immediate execution of a pending task."""
    task = await get_task_with_access_check(task_id, db, access_scope, current_user)
    validate_task_status_for_execute(task)

    previous_scheduled_at = task.scheduled_at
    task.scheduled_at = None
    await db.commit()
    await db.refresh(task)

    await notify_task_execute_now(task, previous_scheduled_at)
    logger.info(f"Task {task_id} scheduled for immediate execution")

    return {"status": "success", "message": f"Task {task_id} scheduled for immediate execution"}


@router.patch("/tasks/{task_id}/schedule")
async def reschedule_task(
    task_id: int,
    request: RescheduleTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Update the scheduled execution time for an existing pending scheduled task."""
    task = await get_task_with_access_check(task_id, db, access_scope, current_user)
    validate_task_status_for_reschedule(task)

    normalized_scheduled = validate_scheduled_datetime_in_future(request.scheduled_datetime)

    # Check slot capacity for the new time slot
    from app.core.slot_capacity import check_slot_capacity, slot_full_detail_dict
    slot_info = await check_slot_capacity(db, normalized_scheduled, exclude_task_id=task_id, acquire_lock=True)
    if slot_info.is_full and slot_info.enforce:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=slot_full_detail_dict(slot_info),
        )

    previous_scheduled_at = task.scheduled_at
    task.scheduled_at = normalized_scheduled
    await db.commit()
    await db.refresh(task)

    await notify_task_rescheduled(task, previous_scheduled_at, normalized_scheduled)
    logger.info("Task %s rescheduled to %s via API", task_id, normalized_scheduled.isoformat())

    return _serialize_task(task, await get_project_metadata(task.project_id))


@router.post("/tasks")
async def create_task(
    request: CreateTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Create a new task under an Issue.

    Args:
        request: Task creation request (requires issue_id)
        db: Database session

    Returns:
        Created task details
    """
    from app.models import Issue

    issue = await db.get(Issue, request.issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    if issue.status == "closed":
        raise HTTPException(status_code=400, detail="Cannot create tasks on a closed issue")

    from app.core.task_helpers import _require_issue_operator
    _require_issue_operator(issue, current_user)

    require_project_access(issue.project_id, access_scope)

    prompt = request.user_prompt or issue.description
    if not prompt:
        raise HTTPException(
            status_code=400,
            detail="No prompt provided and issue has no description",
        )

    scheduled_at = resolve_scheduled_at(
        request.scheduled_datetime,
        request.delay_seconds,
    )

    # Slot capacity only applies to scheduled tasks
    slot_warning = None
    if scheduled_at is not None:
        from app.core.slot_capacity import check_slot_capacity, slot_full_detail_dict
        slot_info = await check_slot_capacity(db, scheduled_at, acquire_lock=True)
        if slot_info.is_full:
            if slot_info.enforce:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=slot_full_detail_dict(slot_info),
                )
            slot_warning = slot_full_detail_dict(slot_info)

    task = Task(
        issue_id=issue.id,
        project_id=issue.project_id,
        user_prompt=prompt,
        initiator_user_id=current_user.id if current_user is not None else None,
        initiator_gitlab_user_id=current_user.gitlab_user_id if current_user is not None else None,
        initiator_username=current_user.username if current_user is not None else None,
        priority=request.priority,
        scheduled_at=scheduled_at,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    logger.info(
        f"Created task {task.id} for issue {issue.id} (project {issue.project_id}), "
        f"priority={request.priority}, delay={request.delay_seconds}"
    )

    response = _serialize_task(task, await get_project_metadata(issue.project_id))
    if slot_warning:
        response["slot_warning"] = slot_warning
    return response
