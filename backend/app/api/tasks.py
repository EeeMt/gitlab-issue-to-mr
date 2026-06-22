"""Task management API endpoints."""

import asyncio
import json as _json
import logging
import os
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import false, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.task_operations import (
    get_task_with_access_check,
    notify_task_cancelled,
    notify_task_execute_now,
    notify_task_rescheduled,
    notify_task_retried,
    validate_scheduled_datetime_in_future,
    validate_task_status_for_cancel,
    validate_task_status_for_execute,
    validate_task_status_for_reschedule,
    validate_task_status_for_retry,
)
from app.api.task_schemas import (
    CreateTaskRequest,
    RescheduleTaskRequest,
    RetryTaskRequest,
    RunInstructionTemplatePreviewRequest,
    UpdateTaskRequest,
)
from app.config import get_effective_settings
from app.core.docker_client import get_docker_client
from app.core.issue_execution_locks import release_issue_execution_lock
from app.core.projects import build_project_lookup, get_project_metadata
from app.core.scheduling import resolve_scheduled_at
from app.core.task_helpers import _serialize_task, maybe_update_issue_status
from app.core.task_log_payloads import persist_raw_log_snapshot
from app.core.task_prompt import (
    NORMAL_PLACEHOLDER_NAMES,
    PLACEHOLDER_NAMES,
    TaskPromptValidationError,
    build_task_prompt_context,
    render_and_store_task_prompt,
    render_run_instruction_template,
    select_run_instruction_template,
)
from app.core.usage_limits import (
    UsageLimitExceeded,
    get_usage_quota_service,
    usage_limit_exceeded_detail,
)
from app.core.utcnow import utcnow
from app.core.worker_workspace import build_issue_workspace_paths, remove_issue_workspace
from app.database import AsyncSessionLocal, get_db
from app.dependencies.auth import get_optional_current_user, require_page_access
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access,
    require_project_access_scope,
)
from app.models import AIProvider, Issue, Task, TaskLog, TaskStatus, User

logger = logging.getLogger(__name__)
router = APIRouter()


TASKS_SORT_FIELDS = {"created_at", "status", "priority", "total_changes", "input_tokens", "output_tokens", "duration"}
SORT_ORDERS = {"asc", "desc"}


@router.get("/tasks")
async def list_tasks(
    status: str | None = None,
    project_id: str | None = None,
    issue_id: int | None = None,
    initiator_username: str | None = None,
    priority: str | None = None,
    has_mr: bool | None = None,
    search: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    scheduled_after: str | None = None,
    scheduled_before: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    page: int | None = None,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """List tasks with optional filtering, sorting, and pagination.

    When ``page`` is provided, returns ``{items, total, page, page_size}``.
    Without ``page``, returns a plain ``Task[]`` array (legacy behaviour).
    """
    # Validate sort params
    effective_sort_by = "created_at"
    effective_sort_order = "desc"
    if sort_by:
        if sort_by not in TASKS_SORT_FIELDS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid sort_by: {sort_by}. Allowed: {', '.join(sorted(TASKS_SORT_FIELDS))}",
            )
        effective_sort_by = sort_by
    if sort_order:
        if sort_order not in SORT_ORDERS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid sort_order: {sort_order}. Allowed: asc, desc",
            )
        effective_sort_order = sort_order

    if effective_sort_by == "duration":
        # Duration = completed_at - started_at (or now - started_at for running tasks)
        duration_expr = func.coalesce(
            func.extract("epoch", Task.completed_at - Task.started_at),
            func.extract("epoch", func.now() - Task.started_at),
        )
        if effective_sort_order == "asc":
            order_clause = duration_expr.asc().nullslast()
        else:
            order_clause = duration_expr.desc().nullslast()
    else:
        sort_column = getattr(Task, effective_sort_by)
        if effective_sort_order == "asc":
            order_clause = sort_column.asc().nullslast()
        else:
            order_clause = sort_column.desc().nullslast()

    query = select(Task).options(selectinload(Task.issue), selectinload(Task.provider)).order_by(order_clause)

    # Multi-status filter (comma-separated, raise 400 for invalid values)
    if status:
        status_parts = [s.strip() for s in status.split(",") if s.strip()]
        valid_statuses = []
        invalid_parts = []
        for part in status_parts:
            try:
                valid_statuses.append(TaskStatus(part))
            except ValueError:
                invalid_parts.append(part)
        if invalid_parts:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status value(s): {', '.join(invalid_parts)}. "
                       f"Allowed: {', '.join(s.value for s in TaskStatus)}",
            )
        if len(valid_statuses) == 1:
            query = query.where(Task.status == valid_statuses[0])
        elif valid_statuses:
            query = query.where(Task.status.in_(valid_statuses))

    # Project filter (comma-separated integers for multi-select)
    if project_id:
        project_ids = []
        for p in project_id.split(","):
            p = p.strip()
            if p:
                try:
                    project_ids.append(int(p))
                except ValueError:
                    pass
        if project_ids:
            if not access_scope.is_unrestricted:
                project_ids = [pid for pid in project_ids if pid in access_scope.accessible_project_ids]
            if len(project_ids) == 1:
                query = query.where(Task.project_id == project_ids[0])
            elif project_ids:
                query = query.where(Task.project_id.in_(project_ids))
            else:
                query = query.where(false())
        elif not access_scope.is_unrestricted:
            allowed_project_ids = access_scope.accessible_project_ids
            if not allowed_project_ids:
                query = query.where(false())
            else:
                query = query.where(Task.project_id.in_(allowed_project_ids))
    elif not access_scope.is_unrestricted:
        allowed_project_ids = access_scope.accessible_project_ids
        if not allowed_project_ids:
            query = query.where(false())
        else:
            query = query.where(Task.project_id.in_(allowed_project_ids))

    # Initiator filter (comma-separated usernames for multi-select)
    if initiator_username:
        usernames = [u.strip() for u in initiator_username.split(",") if u.strip()]
        if len(usernames) == 1:
            query = query.where(Task.initiator_username == usernames[0])
        elif usernames:
            query = query.where(Task.initiator_username.in_(usernames))

    if issue_id:
        query = query.where(Task.issue_id == issue_id)

    # Priority filter (comma-separated integers, silently skip non-integers)
    if priority:
        priority_values = []
        for p in priority.split(","):
            p = p.strip()
            if p:
                try:
                    priority_values.append(int(p))
                except ValueError:
                    pass
        if len(priority_values) == 1:
            query = query.where(Task.priority == priority_values[0])
        elif priority_values:
            query = query.where(Task.priority.in_(priority_values))

    # Has MR filter (checks if the task's issue has a merge_request_iid)
    if has_mr is not None:
        if has_mr:
            query = query.where(Task.issue.has(Issue.merge_request_iid.is_not(None)))
        else:
            query = query.where(
                Task.issue.has(Issue.merge_request_iid.is_(None))
            )

    # Text search on user_prompt (min 2, max 200 chars)
    if search:
        if len(search) > 200:
            raise HTTPException(status_code=400, detail="search too long (max 200 characters)")
        if len(search) >= 2:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.where(Task.user_prompt.ilike(f"%{escaped}%", escape="\\"))

    # Date range filters (DB stores naive UTC datetimes, so strip tzinfo)
    if created_after:
        try:
            dt = datetime.fromisoformat(created_after.replace("Z", "+00:00")).replace(tzinfo=None)
            query = query.where(Task.created_at >= dt)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid created_after: {created_after}")
    if created_before:
        try:
            dt = datetime.fromisoformat(created_before.replace("Z", "+00:00")).replace(tzinfo=None)
            query = query.where(Task.created_at <= dt)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid created_before: {created_before}")

    # Scheduled date range filters
    if scheduled_after:
        try:
            dt = datetime.fromisoformat(scheduled_after.replace("Z", "+00:00")).replace(tzinfo=None)
            query = query.where(Task.scheduled_at >= dt)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid scheduled_after: {scheduled_after}")
    if scheduled_before:
        try:
            dt = datetime.fromisoformat(scheduled_before.replace("Z", "+00:00")).replace(tzinfo=None)
            query = query.where(Task.scheduled_at <= dt)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid scheduled_before: {scheduled_before}")

    project_lookup = await build_project_lookup(
        accessible_projects=access_scope.accessible_projects,
        is_unrestricted=access_scope.is_unrestricted,
    )

    # Compute settings once — _serialize_task uses it per-task, so pass it in
    # to avoid recreating the Settings object for every row in the result set.
    settings = get_effective_settings()

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
                _serialize_task(task, project_lookup.get(task.project_id), settings)
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
        _serialize_task(task, project_lookup.get(task.project_id), settings)
        for task in tasks
    ]


@router.get("/tasks/scheduled")
async def list_scheduled_tasks(
    project_id: int | None = None,
    hour_start: str | None = Query(None, description="ISO datetime; filter tasks in this 1-hour window"),
    my: bool = Query(False, description="When true, restrict to tasks initiated by the current user"),
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_page_access("schedule_overview")),
):
    """List active scheduled tasks for queue analytics views.

    Returns all scheduled tasks regardless of project membership — the schedule
    overview is a global queue view where all authenticated users with page access
    can see the full pipeline. Project-level access is only enforced for write
    operations (reschedule, cancel, etc.).

    When my=True, restricts results to the current user's tasks.
    When hour_start is provided, returns only tasks within that 1-hour window.
    """
    query = (
        select(Task)
        .options(selectinload(Task.issue), selectinload(Task.provider))
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

    if my and _current_user and getattr(_current_user, "username", None):
        query = query.where(Task.initiator_username == _current_user.username)

    result = await db.execute(query)
    tasks = result.scalars().all()
    project_lookup = await build_project_lookup(is_unrestricted=True)
    settings = get_effective_settings()

    return [
        _serialize_task(task, project_lookup.get(task.project_id), settings)
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


@router.get("/tasks/run-instruction-template-defaults")
async def get_run_instruction_template_defaults(
    _access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Return effective execute and plan templates for task operators."""
    settings = get_effective_settings()
    placeholders = list(NORMAL_PLACEHOLDER_NAMES)
    return {
        "execute": {
            "content": settings.default_execute_run_instruction_template,
            "available_placeholders": placeholders,
            "known_placeholders": list(PLACEHOLDER_NAMES),
        },
        "plan": {
            "content": settings.default_plan_run_instruction_template,
            "available_placeholders": placeholders,
            "known_placeholders": list(PLACEHOLDER_NAMES),
        },
    }


@router.post("/tasks/render-run-instruction-template-preview")
async def preview_run_instruction_template(
    request: RunInstructionTemplatePreviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Render unsaved task editor content without mutating the database."""
    issue = await db.get(Issue, request.issue_id)
    if not issue:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
    require_project_access(issue.project_id, access_scope)
    from app.core.task_helpers import _require_issue_operator

    _require_issue_operator(issue, current_user)
    prospective_task = Task(
        issue_id=issue.id,
        project_id=issue.project_id,
        user_prompt=request.user_prompt,
        task_mode=request.task_mode,
        require_changes=False if request.task_mode == "plan" else request.require_changes,
        trigger_source="manual",
    )
    try:
        result = render_run_instruction_template(
            request.run_instruction_template,
            build_task_prompt_context(
                prospective_task,
                issue,
                await get_project_metadata(issue.project_id),
            ),
            available_placeholders=NORMAL_PLACEHOLDER_NAMES,
        )
    except TaskPromptValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return {
        "rendered_prompt": result.rendered_prompt,
        "used_placeholders": list(result.used_placeholders),
        "unused_known_placeholders": list(result.unused_known_placeholders),
    }


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
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
    result = await db.execute(
        select(Task).options(selectinload(Task.issue), selectinload(Task.provider)).where(Task.id == task_id)
    )
    t1 = time.time()
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )

    require_project_access(task.project_id, access_scope)

    t2 = time.time()
    metadata = await get_project_metadata(task.project_id)
    t3 = time.time()
    result_data = _serialize_task(task, metadata, include_prompt_details=True)
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
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Get task logs."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )

    require_project_access(task.project_id, access_scope)

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
            "metadata": _json.loads(log.log_metadata) if log.log_metadata else None,
            "message": log.message,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]


@router.get("/tasks/{task_id}/log-stream")
async def stream_task_logs(
    task_id: int,
    since_id: int = 0,
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Stream task log entries as Server-Sent Events.

    Polls the database for new TaskLog entries every 1.5 seconds and streams
    them to the client as SSE events. Stops automatically once the task reaches
    a terminal state (completed/failed/cancelled) and all pending logs are sent.

    Args:
        task_id: Task ID to stream logs for
        since_id: Only return log entries with id > since_id (for resuming)
        access_scope: Project access scope for authorization

    Returns:
        StreamingResponse with text/event-stream media type
    """
    # Validate task exists and user has access before starting the stream.
    # Use a short-lived session that closes immediately — this endpoint must not
    # hold a DB connection for the full stream duration (up to 30 min).
    async with AsyncSessionLocal() as init_db:
        result = await init_db.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    require_project_access(task.project_id, access_scope)

    _TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}

    def _log_to_event_data(log: TaskLog) -> dict:
        return {
            "id": log.id,
            "log_type": log.log_type,
            "metadata": _json.loads(log.log_metadata) if log.log_metadata else None,
            "message": log.message,
            "created_at": log.created_at.isoformat(),
        }

    async def generate_log_events():
        cursor = since_id
        # Track tool_call log IDs that were emitted without output_payload_id.
        # These logs are updated in-place (not appended) by the worker, so they
        # are never re-emitted by the id > cursor query.  We re-query them each
        # cycle and push an "update" SSE event the moment output_payload_id
        # appears, eliminating the need for a client-side fetchLogs() poll.
        pending_tool_calls: set[int] = set()
        _BATCH_SIZE = 500
        _SLOW_QUERY_THRESHOLD_S = 0.5
        stream_start = time.monotonic()
        total_events_sent = 0
        poll_cycle = 0
        first_batch_sent = False   # tracks whether the first "batch" event was yielded
        ff_streak = 0              # consecutive fast-forward cycles currently running
        ff_streak_logs = 0         # total log entries delivered across the streak
        logger.info(
            f"[Task {task_id}] log-stream opened since_id={since_id} "
            f"resume={'yes' if since_id > 0 else 'no'}"
        )
        try:
            while True:
                poll_cycle += 1
                cycle_start = time.monotonic()

                # Collect all SSE payloads while the session is open, then close
                # the session and yield outside it.  This ensures the DB connection
                # is returned to the pool before we block on network I/O to the
                # client (a slow or stalled client must not hold a DB connection).
                #
                # Regular log entries are batched into a single "batch" SSE event
                # (a JSON array) so the browser processes them in ONE macrotask.
                # Without batching, each individual SSE message fires a separate
                # macrotask; queueMicrotask() cannot coalesce across macrotasks, so
                # 100 events produce 100 Vue reactive updates and O(n²) total work.
                cycle_log_data: list[dict] = []    # payload for the "batch" event
                cycle_update_events: list[str] = []  # "update" events stay individual
                fast_forward = False
                current_status = None
                new_log_count = 0

                async with AsyncSessionLocal() as poll_db:
                    # Fetch new log entries since last cursor
                    t0 = time.monotonic()
                    log_result = await poll_db.execute(
                        select(TaskLog)
                        .where(TaskLog.task_id == task_id, TaskLog.id > cursor)
                        .order_by(TaskLog.id.asc())
                        .limit(_BATCH_SIZE)
                    )
                    new_logs = log_result.scalars().all()
                    new_log_count = len(new_logs)
                    log_query_ms = (time.monotonic() - t0) * 1000

                    if log_query_ms > _SLOW_QUERY_THRESHOLD_S * 1000:
                        logger.warning(
                            f"[Task {task_id}] log-stream slow log query cycle={poll_cycle} "
                            f"cursor={cursor} fetched={new_log_count} query_ms={log_query_ms:.1f}"
                        )
                    elif new_logs:
                        logger.debug(
                            f"[Task {task_id}] log-stream cycle={poll_cycle} "
                            f"fetched={new_log_count} cursor={cursor} query_ms={log_query_ms:.1f}"
                        )

                    for log in new_logs:
                        event_data = _log_to_event_data(log)
                        cursor = log.id
                        total_events_sent += 1
                        # Queue tool_call logs that don't yet have output_payload_id
                        if log.log_type == "tool_call":
                            meta = event_data["metadata"] or {}
                            if not meta.get("output_payload_id"):
                                pending_tool_calls.add(log.id)
                        cycle_log_data.append(event_data)

                    if new_log_count == _BATCH_SIZE:
                        # Batch was full — more logs likely waiting; skip sleep
                        fast_forward = True
                    else:
                        # Re-check pending tool_call logs for in-place updates.
                        # Fresh session means no stale identity map; no need for
                        # populate_existing.
                        if pending_tool_calls:
                            t0 = time.monotonic()
                            updated_result = await poll_db.execute(
                                select(TaskLog)
                                .where(TaskLog.id.in_(pending_tool_calls))
                            )
                            update_query_ms = (time.monotonic() - t0) * 1000
                            if update_query_ms > _SLOW_QUERY_THRESHOLD_S * 1000:
                                logger.warning(
                                    f"[Task {task_id}] log-stream slow tool_call update query "
                                    f"cycle={poll_cycle} pending={len(pending_tool_calls)} "
                                    f"query_ms={update_query_ms:.1f}"
                                )
                            for log in updated_result.scalars().all():
                                meta = _json.loads(log.log_metadata) if log.log_metadata else {}
                                if meta.get("output_payload_id"):
                                    cycle_update_events.append(
                                        f"event: update\ndata: {_json.dumps(_log_to_event_data(log))}\n\n"
                                    )
                                    pending_tool_calls.discard(log.id)
                                    total_events_sent += 1

                        # Check current task status
                        t0 = time.monotonic()
                        task_result = await poll_db.execute(
                            select(Task.status).where(Task.id == task_id)
                        )
                        current_status = task_result.scalar_one_or_none()
                        status_query_ms = (time.monotonic() - t0) * 1000
                        if status_query_ms > _SLOW_QUERY_THRESHOLD_S * 1000:
                            logger.warning(
                                f"[Task {task_id}] log-stream slow status query cycle={poll_cycle} "
                                f"status={current_status} query_ms={status_query_ms:.1f}"
                            )
                # Session closed here — DB connection returned to pool.

                cycle_ms = (time.monotonic() - cycle_start) * 1000
                if cycle_ms > 1000:
                    logger.warning(
                        f"[Task {task_id}] log-stream slow cycle cycle={poll_cycle} "
                        f"cycle_ms={cycle_ms:.1f} total_sent={total_events_sent}"
                    )

                # Yield events with DB connection already released.
                # All log entries are batched into a single SSE event so the
                # browser processes the entire cycle in one macrotask.
                if cycle_log_data:
                    _batch_payload = f"event: batch\ndata: {_json.dumps(cycle_log_data)}\n\n"
                    _yield_t0 = time.monotonic()
                    yield _batch_payload
                    # NOTE: measures time for the ASGI send() call to return, i.e. the
                    # time to copy the payload into the kernel TCP send buffer.  Spikes
                    # (> 500 ms) indicate client-side TCP backpressure, not network RTT.
                    _yield_ms = (time.monotonic() - _yield_t0) * 1000
                    if not first_batch_sent:
                        first_batch_sent = True
                        logger.info(
                            f"[Task {task_id}] log-stream first-batch "
                            f"cycle={poll_cycle} count={len(cycle_log_data)} "
                            f"time_to_first_ms={((_yield_t0 - stream_start) * 1000):.1f} "
                            f"idle_cycles_before={poll_cycle - 1} "
                            f"yield_ms={_yield_ms:.1f}"
                        )
                    elif _yield_ms > 500:
                        logger.warning(
                            f"[Task {task_id}] log-stream slow-yield "
                            f"cycle={poll_cycle} count={len(cycle_log_data)} "
                            f"yield_ms={_yield_ms:.1f}"
                        )
                for ev in cycle_update_events:
                    yield ev

                if len(pending_tool_calls) > 20:
                    # Rate-limited: log on first detection and every 10th cycle
                    # thereafter to avoid spamming when the condition persists.
                    if poll_cycle % 10 == 1:
                        logger.warning(
                            f"[Task {task_id}] log-stream large-pending-tool-calls "
                            f"size={len(pending_tool_calls)} cycle={poll_cycle}"
                        )

                if fast_forward:
                    ff_streak += 1
                    ff_streak_logs += len(cycle_log_data)
                    # Per-cycle detail suppressed; streak summary fires when burst ends.
                    continue

                if ff_streak > 0:
                    # Streak just ended — summarise how much catch-up was done
                    logger.info(
                        f"[Task {task_id}] log-stream fast-forward-done "
                        f"cycles={ff_streak} logs={ff_streak_logs} cursor={cursor}"
                    )
                    ff_streak = 0
                    ff_streak_logs = 0

                if current_status not in _TERMINAL_STATUSES and not new_log_count:
                    # Periodic heartbeat so we can confirm the stream is alive in logs
                    if poll_cycle % 20 == 0:
                        logger.debug(
                            f"[Task {task_id}] log-stream alive "
                            f"cycle={poll_cycle} cursor={cursor} status={current_status} "
                            f"pending={len(pending_tool_calls)} "
                            f"elapsed_s={time.monotonic() - stream_start:.0f}"
                        )

                if current_status in _TERMINAL_STATUSES and new_log_count == 0:
                    # new_log_count == 0 means cycle_log_data was also empty —
                    # no "batch" event was yielded this cycle, so no pending
                    # microtask flush exists on the client when "done" arrives.
                    yield "event: done\ndata: {}\n\n"
                    elapsed_s = time.monotonic() - stream_start
                    logger.info(
                        f"[Task {task_id}] log-stream closed reason=done "
                        f"total_events={total_events_sent} cycles={poll_cycle} "
                        f"elapsed_s={elapsed_s:.1f}"
                    )
                    break

                # Wait before polling again
                await asyncio.sleep(1.5)

        except asyncio.CancelledError:
            elapsed_s = time.monotonic() - stream_start
            logger.info(
                f"[Task {task_id}] log-stream closed reason=client_disconnected "
                f"total_events={total_events_sent} cycles={poll_cycle} "
                f"elapsed_s={elapsed_s:.1f}"
                + (
                    f" ff_streak_aborted={ff_streak} ff_streak_logs={ff_streak_logs}"
                    if ff_streak > 0 else ""
                )
            )
        except Exception as exc:
            elapsed_s = time.monotonic() - stream_start
            logger.error(
                f"[Task {task_id}] log-stream error after {elapsed_s:.1f}s "
                f"cycle={poll_cycle} total_events={total_events_sent}"
                + (f" ff_streak={ff_streak}" if ff_streak > 0 else "")
                + f": {exc}"
            )
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
    merge_request_iid = None
    issue_result = await db.execute(select(Issue).where(Issue.id == task.issue_id))
    issue = issue_result.scalar_one_or_none()
    if issue:
        merge_request_iid = issue.merge_request_iid

    if not merge_request_iid:
        return {"additions": 0, "deletions": 0, "total": 0}

    from app.core.gitlab_client import get_gitlab_client
    gitlab = get_gitlab_client()

    stats = await asyncio.to_thread(
        gitlab.get_merge_request_stats,
        task.project_id,
        merge_request_iid,
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


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: int,
    request: UpdateTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Update editable fields of a task that has not yet started.

    Only fields present in the request body are applied.  The task must be in
    PENDING or QUEUED status; any other status results in a 409 response.
    """
    task = await get_task_with_access_check(
        task_id, db, access_scope, current_user, with_for_update=True
    )

    if task.status not in (TaskStatus.PENDING, TaskStatus.QUEUED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Task {task_id} cannot be edited because its status is "
                f"'{task.status.value}'. Only PENDING or QUEUED tasks can be updated."
            ),
        )

    updated_fields = request.model_fields_set

    if "user_prompt" in updated_fields:
        if not request.user_prompt or not request.user_prompt.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="user_prompt must be a non-empty string",
            )
        task.user_prompt = request.user_prompt.strip()

    if "priority" in updated_fields:
        if request.priority not in (0, 1, 2):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="priority must be 0 (low), 1 (normal), or 2 (high)",
            )
        task.priority = request.priority

    if "provider_id" in updated_fields:
        # None means "clear to system default"; an integer must reference an existing provider
        if request.provider_id is not None:
            provider = await db.get(AIProvider, request.provider_id)
            if not provider:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Provider not found",
                )
            if provider.is_disabled is True:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Provider is disabled",
                )
        task.provider_id = request.provider_id

    if "require_changes" in updated_fields:
        task.require_changes = request.require_changes  # type: ignore[assignment]  # null rejected by schema

    if "task_mode" in updated_fields:
        task.task_mode = request.task_mode  # type: ignore[assignment]  # null rejected by schema

    if "run_instruction_template" in updated_fields:
        task.run_instruction_template = request.run_instruction_template

    # Enforce invariant: plan tasks must never have require_changes=True,
    # regardless of whether task_mode or require_changes was the field being updated.
    if task.task_mode == "plan":
        task.require_changes = False

    # Re-read the row inside the same transaction before committing.
    # Under READ COMMITTED, this sees any status changes that were committed by a
    # concurrent worker *before* this transaction acquired its FOR UPDATE lock.
    # This prevents a successful PATCH on a task whose status was already advanced
    # to RUNNING (or beyond) by the time we are ready to write.
    await db.refresh(task, attribute_names=["status"])
    if task.status not in (TaskStatus.PENDING, TaskStatus.QUEUED):
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Task {task_id} can no longer be edited: "
                f"status changed to '{task.status.value}' while processing the request."
            ),
        )

    render_context_changed = bool(
        updated_fields
        & {"user_prompt", "run_instruction_template", "task_mode", "require_changes"}
    )
    if render_context_changed:
        issue = await db.get(Issue, task.issue_id)
        template = task.run_instruction_template
        if template is None:
            template = select_run_instruction_template(
                get_effective_settings(),
                task_mode=task.task_mode or "execute",
                trigger_source=task.trigger_source or "manual",
            )
        try:
            render_and_store_task_prompt(
                task,
                issue,
                await get_project_metadata(task.project_id),
                template,
            )
        except TaskPromptValidationError as exc:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    await db.commit()
    await db.refresh(task)

    logger.info(
        "Task %s updated via PATCH: fields=%s", task_id, sorted(updated_fields)
    )

    return _serialize_task(
        task,
        await get_project_metadata(task.project_id),
        include_prompt_details=True,
    )


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Cancel a task."""
    task = await get_task_with_access_check(task_id, db, access_scope, current_user)
    validate_task_status_for_cancel(task)

    task.status = TaskStatus.CANCELLED
    task.completed_at = utcnow()
    task.error_message = "Cancelled by user"
    task.raw_logs_finalized_at = None
    await db.commit()
    await db.refresh(task)

    # Stop the container before reading console.log so the snapshot cannot grow
    # after its cursor is persisted. Keep the container filesystem available
    # until the final snapshot has been stored.
    settings = get_effective_settings()
    container_name = f"{settings.worker_container_prefix}-{task_id}-issue{task.issue_id}"
    container = None
    raw_console_log: bytes | None = None
    try:
        docker = get_docker_client()
        container = await asyncio.to_thread(docker.client.containers.get, container_name)
        try:
            await asyncio.to_thread(container.stop, timeout=10)
        except Exception as stop_error:
            logger.warning(
                "Graceful stop failed for cancelled task %s: %s; forcing container stop",
                task_id,
                stop_error,
            )
            await asyncio.to_thread(container.kill)
        raw_console_log = await asyncio.to_thread(
            docker.read_file_from_container,
            container,
            "/tmp/codify-runtime/console.log",
        )
    except Exception as container_error:
        logger.warning(
            "Could not finalize container logs for cancelled task %s: %s",
            task_id,
            container_error,
        )

    raw_logs_finalized = container is None and task.container_id is None
    if raw_console_log is not None:
        await persist_raw_log_snapshot(
            db,
            task_id=task_id,
            content=raw_console_log,
        )
        raw_logs_finalized = True

    if not raw_logs_finalized:
        await db.refresh(task, attribute_names=["raw_logs_finalized_at"])
        raw_logs_finalized = task.raw_logs_finalized_at is not None
    if raw_logs_finalized and task.raw_logs_finalized_at is None:
        task.raw_logs_finalized_at = utcnow()
    await db.commit()

    if container is not None and raw_logs_finalized:
        try:
            await asyncio.to_thread(container.remove, force=True)
            logger.info(f"Removed container {container_name} for cancelled task {task_id}")
        except Exception as remove_error:
            logger.warning(
                "Could not remove container for cancelled task %s: %s",
                task_id,
                remove_error,
            )
    elif container is not None:
        logger.error(
            "Retaining container %s for cancelled task %s because raw logs were not finalized",
            container_name,
            task_id,
        )

    await release_issue_execution_lock(db, issue_id=task.issue_id)
    await db.commit()

    await notify_task_cancelled(task)
    logger.info(f"Task {task_id} cancelled via API")

    # Auto-update issue status if no active tasks remain
    if task.issue_id is not None:
        await maybe_update_issue_status(db, task.issue_id)

    return {"status": "success", "message": f"Task {task_id} cancelled"}


class OverrideStatusRequest(BaseModel):
    status: str  # "completed" or "failed"
    reason: str | None = None


@router.post("/tasks/{task_id}/override-status")
async def override_task_status(
    task_id: int,
    request: OverrideStatusRequest,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
    current_user: User | None = Depends(get_optional_current_user),
) -> dict:
    """Manually override a terminal task's status (completed <-> failed)."""
    task = await get_task_with_access_check(task_id, db, access_scope, current_user)

    if request.status not in ("completed", "failed"):
        raise HTTPException(status_code=400, detail="status must be 'completed' or 'failed'")

    new_status = TaskStatus(request.status)
    if task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
        raise HTTPException(
            status_code=400,
            detail=f"Can only override completed or failed tasks, current: {task.status.value}",
        )
    if task.status == new_status:
        raise HTTPException(status_code=400, detail=f"Task is already {task.status.value}")

    task.status = new_status
    task.is_manually_overridden = True
    task.override_reason = request.reason or None
    task.overridden_by_user_id = current_user.id if current_user else None
    task.overridden_at = utcnow()
    await db.commit()
    await db.refresh(task)

    if task.issue_id is not None:
        await maybe_update_issue_status(db, task.issue_id)

    logger.info(f"Task {task_id} status manually overridden to {new_status.value}")
    return {"status": "success", "message": f"Task {task_id} status overridden to {new_status.value}"}


@router.post("/tasks/{task_id}/retry")
async def retry_task(
    task_id: int,
    request: RetryTaskRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
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

    scheduled_at: datetime | None = None
    if request and request.scheduled_datetime is not None:
        scheduled_at = validate_scheduled_datetime_in_future(request.scheduled_datetime)

    if current_user is not None and current_user.id is not None:
        try:
            await get_usage_quota_service().raise_if_over_limit(
                db,
                current_user.id,
                scope="create",
            )
        except UsageLimitExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=usage_limit_exceeded_detail(exc),
            ) from exc

    # Check slot capacity for scheduled retries
    if scheduled_at is not None:
        from app.core.slot_capacity import check_slot_capacity, slot_full_detail_dict
        slot_info = await check_slot_capacity(db, scheduled_at, exclude_task_id=task_id, acquire_lock=True)
        if slot_info.is_full and slot_info.enforce:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=slot_full_detail_dict(slot_info),
            )

    provider_id = original_task.provider_id
    if provider_id is None:
        default_result = await db.execute(
            select(AIProvider).where(AIProvider.is_default == True)
        )
        provider = default_result.scalar_one_or_none()
        if not provider:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No default provider configured. Please set a default AI provider.",
            )
        provider_id = provider.id
    else:
        provider = await db.get(AIProvider, provider_id)

    if provider and provider.is_disabled is True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Provider is disabled",
        )

    new_task = Task(
        issue_id=original_task.issue_id,
        project_id=original_task.project_id,
        user_prompt=original_task.user_prompt,
        priority=original_task.priority,
        scheduled_at=scheduled_at,
        is_retry=True,
        retry_source_task_id=original_task.id,
        trigger_source="retry",
        ci_failure_run_id=original_task.ci_failure_run_id,
        provider_id=provider_id,
        initiator_user_id=current_user.id if current_user is not None else None,
        initiator_gitlab_user_id=current_user.gitlab_user_id if current_user is not None else None,
        initiator_username=current_user.username if current_user is not None else None,
        initiator_display_name=current_user.display_name if current_user is not None else None,
        initiator_email=current_user.email if current_user is not None else None,
        task_mode=original_task.task_mode if original_task.task_mode else "execute",
        require_changes=original_task.require_changes,
    )
    db.add(new_task)
    await db.flush()
    issue = (
        await db.execute(select(Issue).where(Issue.id == new_task.issue_id))
    ).scalar_one_or_none()
    retry_template = select_run_instruction_template(
        get_effective_settings(),
        task_mode=new_task.task_mode,
        trigger_source=original_task.trigger_source or "manual",
        retry_snapshot=original_task.run_instruction_template,
    )
    try:
        render_and_store_task_prompt(
            new_task,
            issue,
            await get_project_metadata(new_task.project_id),
            retry_template,
        )
    except TaskPromptValidationError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    await db.commit()
    await db.refresh(new_task)
    # Eagerly set the issue relationship for serialization
    new_task.issue = issue

    await notify_task_retried(new_task, None, scheduled_at)
    action = f"scheduled for retry at {scheduled_at}" if scheduled_at else "created as retry"
    logger.info(f"Task {new_task.id} {action} (retry of task {task_id})")

    return _serialize_task(
        new_task,
        await get_project_metadata(new_task.project_id),
        include_prompt_details=True,
    )


@router.post("/tasks/{task_id}/execute")
async def execute_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
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
    current_user: User | None = Depends(get_optional_current_user),
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
    # Rescheduling to a future time resets QUEUED → PENDING
    if task.status == TaskStatus.QUEUED:
        task.status = TaskStatus.PENDING
    await db.commit()
    await db.refresh(task)

    await notify_task_rescheduled(task, previous_scheduled_at, normalized_scheduled)
    logger.info("Task %s rescheduled to %s via API", task_id, normalized_scheduled.isoformat())

    return _serialize_task(
        task,
        await get_project_metadata(task.project_id),
        include_prompt_details=True,
    )


@router.post("/tasks")
async def create_task(
    request: CreateTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
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

    # Validate provider_id is required
    from app.models import AIProvider
    provider = await db.get(AIProvider, request.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    if provider.is_disabled is True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Provider is disabled",
        )

    scheduled_at = resolve_scheduled_at(
        request.scheduled_datetime,
        request.delay_seconds,
    )

    if current_user is not None and current_user.id is not None:
        try:
            await get_usage_quota_service().raise_if_over_limit(
                db,
                current_user.id,
                scope="create",
            )
        except UsageLimitExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=usage_limit_exceeded_detail(exc),
            ) from exc

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
        initiator_display_name=current_user.display_name if current_user is not None else None,
        initiator_email=current_user.email if current_user is not None else None,
        priority=request.priority,
        scheduled_at=scheduled_at,
        provider_id=request.provider_id,
        task_mode=request.task_mode,
        require_changes=request.effective_require_changes,
    )
    db.add(task)
    await db.flush()
    template = request.run_instruction_template
    if template is None:
        template = select_run_instruction_template(
            get_effective_settings(),
            task_mode=task.task_mode,
            trigger_source=task.trigger_source or "manual",
        )
    try:
        render_and_store_task_prompt(
            task,
            issue,
            await get_project_metadata(issue.project_id),
            template,
        )
    except TaskPromptValidationError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    await db.commit()
    await db.refresh(task)
    task.issue = issue  # ensure nested issue is included in serialization

    logger.info(
        f"Created task {task.id} for issue {issue.id} (project {issue.project_id}), "
        f"priority={request.priority}, delay={request.delay_seconds}"
    )

    response = _serialize_task(
        task,
        await get_project_metadata(issue.project_id),
        include_prompt_details=True,
    )
    if slot_warning:
        response["slot_warning"] = slot_warning
    return response


@router.get("/tasks/{task_id}/workspace")
async def get_task_workspace_status(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    task = await get_task_with_access_check(task_id, db, access_scope, current_user)
    if task.issue is None:
        task.issue = await db.get(Issue, task.issue_id)

    settings = get_effective_settings()
    if not task.issue:
        return {"enabled": False, "reason": "task has no issue"}

    paths = build_issue_workspace_paths(settings, task.issue, task)
    if paths is None:
        return {"enabled": False, "reason": "worker workspace host path is not configured"}

    repo_exists = os.path.isdir(paths.repo_path)
    return {
        "enabled": True,
        "issue_root": paths.issue_root,
        "repo_path": paths.repo_path,
        "runtime_path": paths.runtime_path,
        "repo_exists": repo_exists,
    }


@router.delete("/tasks/{task_id}/workspace")
async def delete_task_workspace(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    task = await get_task_with_access_check(task_id, db, access_scope, current_user)
    if task.status == TaskStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Cannot delete workspace while task is running")
    if task.issue is None:
        task.issue = await db.get(Issue, task.issue_id)
    if not task.issue:
        raise HTTPException(status_code=404, detail="Workspace not available for task without issue")

    settings = get_effective_settings()
    paths = build_issue_workspace_paths(settings, task.issue, task)
    if paths is None:
        raise HTTPException(status_code=404, detail="Worker workspace host path is not configured")

    removed = remove_issue_workspace(paths.issue_root)
    return {"removed": removed, "issue_root": paths.issue_root}


@router.get("/tasks/{task_id}/archive")
async def get_task_archive(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Get runtime archive metadata for a completed task."""
    from app.models import TaskRunArchive
    archive = (
        await db.execute(
            select(TaskRunArchive).where(TaskRunArchive.task_id == task_id)
        )
    ).scalar_one_or_none()
    if not archive:
        raise HTTPException(status_code=404, detail="Archive not available")
    return {
        "archive_name": archive.archive_name,
        "archive_size_bytes": archive.archive_size_bytes,
        "created_at": archive.created_at.isoformat(),
        "file_exists": bool(archive.archive_path and os.path.exists(archive.archive_path)),
    }


@router.get("/tasks/{task_id}/archive/download")
async def download_task_archive(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Download the compressed runtime archive for a completed task."""
    from app.models import TaskRunArchive
    archive = (
        await db.execute(
            select(TaskRunArchive).where(TaskRunArchive.task_id == task_id)
        )
    ).scalar_one_or_none()
    if not archive:
        raise HTTPException(status_code=404, detail="Archive not available")
    if not archive.archive_path or not os.path.exists(archive.archive_path):
        raise HTTPException(status_code=404, detail="Archive file not found")
    return FileResponse(
        archive.archive_path,
        media_type="application/gzip",
        filename=archive.archive_name,
    )


@router.get("/tasks/{task_id}/payloads/{payload_id}")
async def get_task_payload(
    task_id: int,
    payload_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Get payload content for a task log entry."""
    from app.models import TaskPayload
    payload = (
        await db.execute(
            select(TaskPayload).where(
                TaskPayload.task_id == task_id, TaskPayload.id == payload_id
            )
        )
    ).scalar_one_or_none()
    if not payload:
        raise HTTPException(status_code=404, detail="Payload not found")
    content = payload.content.decode("utf-8", errors="replace")
    return {
        "id": payload.id,
        "payload_kind": payload.payload_kind,
        "content": content,
        "encoding": payload.encoding,
        "char_count": payload.char_count,
        "byte_count": payload.byte_count,
    }
