"""Task management API endpoints."""

import logging
import os
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.task_action_routes import (
    OverrideStatusRequest as OverrideStatusRequest,
)
from app.api.task_action_routes import (
    cancel_task as cancel_task,
)
from app.api.task_action_routes import (
    execute_task as execute_task,
)
from app.api.task_action_routes import (
    override_task_status as override_task_status,
)
from app.api.task_action_routes import (
    reschedule_task as reschedule_task,
)
from app.api.task_action_routes import (
    router as task_action_router,
)
from app.api.task_artifacts import (
    build_task_workspace_status,
    get_task_archive_file,
    get_task_archive_metadata,
    get_task_payload_content,
    remove_task_workspace,
)
from app.api.task_log_routes import (
    router as task_log_router,
)
from app.api.task_operations import (
    get_task_with_access_check,
    notify_task_retried,
    validate_scheduled_datetime_in_future,
    validate_task_status_for_retry,
)
from app.api.task_queries import TaskListFilters, build_task_list_query
from app.api.task_responses import (
    attach_task_worker_snapshot as _attach_task_worker_snapshot,
)
from app.api.task_responses import (
    loaded_task_relationship as _loaded_task_relationship,
)
from app.api.task_responses import (
    refresh_task_response_state as _refresh_task_response_state,
)
from app.api.task_responses import (
    serialize_task as _serialize_task,
)
from app.api.task_schemas import (
    CreateTaskRequest,
    RetryTaskRequest,
    RunInstructionTemplatePreviewRequest,
    UpdateTaskRequest,
)
from app.api.task_schemas import (
    RescheduleTaskRequest as RescheduleTaskRequest,
)
from app.api.task_stats_routes import (
    router as task_stats_router,
)
from app.config import get_effective_settings
from app.core.projects import build_project_lookup, get_project_metadata
from app.core.scheduling import resolve_scheduled_at
from app.core.task_creation import prepare_task_runtime_snapshot
from app.core.task_prompt import (
    NORMAL_PLACEHOLDER_NAMES,
    PLACEHOLDER_NAMES,
    TaskPromptValidationError,
    build_task_prompt_context,
    render_and_store_task_prompt,
    render_run_instruction_template,
)
from app.core.usage_limits import (
    UsageLimitExceeded,
    get_usage_quota_service,
    usage_limit_exceeded_detail,
)
from app.core.worker_profiles import (
    WorkerProfileValidationError,
    replace_task_worker_snapshot,
    resolve_provider_for_issue,
    resolve_worker_profile_for_issue,
    select_snapshot_run_instruction_template,
)
from app.core.worker_workspace import build_issue_workspace_paths, remove_issue_workspace
from app.database import get_db
from app.dependencies.auth import get_optional_current_user, require_page_access
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access,
    require_project_access_scope,
)
from app.models import (
    Issue,
    Task,
    TaskStatus,
    TaskWorkerProfileSnapshot,
    User,
)

logger = logging.getLogger(__name__)
router = APIRouter()
router.include_router(task_action_router)
router.include_router(task_log_router)
router.include_router(task_stats_router)


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
    query = build_task_list_query(
        TaskListFilters(
            status=status,
            project_id=project_id,
            issue_id=issue_id,
            initiator_username=initiator_username,
            priority=priority,
            has_mr=has_mr,
            search=search,
            created_after=created_after,
            created_before=created_before,
            scheduled_after=scheduled_after,
            scheduled_before=scheduled_before,
            sort_by=sort_by,
            sort_order=sort_order,
        ),
        access_scope,
    )

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

        count_result = await db.execute(select(func.count()).select_from(query.subquery()))
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

    return [_serialize_task(task, project_lookup.get(task.project_id), settings) for task in tasks]


@router.get("/tasks/scheduled")
async def list_scheduled_tasks(
    project_id: int | None = None,
    hour_start: str | None = Query(
        None, description="ISO datetime; filter tasks in this 1-hour window"
    ),
    my: bool = Query(
        False, description="When true, restrict to tasks initiated by the current user"
    ),
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
        .options(
            selectinload(Task.issue),
            selectinload(Task.provider),
            selectinload(Task.worker_profile),
            selectinload(Task.worker_profile_snapshot),
        )
        .where(
            Task.scheduled_at.is_not(None),
            Task.status.in_(
                [
                    TaskStatus.PENDING,
                    TaskStatus.QUEUED,
                    TaskStatus.RUNNING,
                ]
            ),
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

    return [_serialize_task(task, project_lookup.get(task.project_id), settings) for task in tasks]


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
        select(Task)
        .options(
            selectinload(Task.issue),
            selectinload(Task.provider),
            selectinload(Task.worker_profile),
            selectinload(Task.worker_profile_snapshot),
        )
        .where(Task.id == task_id)
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
            f"db={t1 - t0:.3f}s project_meta={t3 - t2:.3f}s serialize={t4 - t3:.3f}s "
            f"access_scope_resolved_before_handler status={task.status}"
        )

    return result_data


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

    issue = None
    snapshot = _loaded_task_relationship(task, "worker_profile_snapshot")
    if updated_fields & {"worker_profile_id", "provider_id"}:
        issue = await db.get(Issue, task.issue_id)
        if issue is None:
            raise HTTPException(status_code=404, detail="Issue not found")

    if "worker_profile_id" in updated_fields:
        try:
            worker_profile = await resolve_worker_profile_for_issue(
                db,
                issue,
                request.worker_profile_id,
            )
        except WorkerProfileValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        task.worker_profile_id = worker_profile.id
        snapshot = await replace_task_worker_snapshot(db, task, worker_profile)
        task.worker_profile_snapshot = snapshot

    if "provider_id" in updated_fields:
        try:
            provider = await resolve_provider_for_issue(db, issue, request.provider_id)
        except WorkerProfileValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        task.provider_id = provider.id

    if "require_changes" in updated_fields:
        task.require_changes = request.require_changes  # type: ignore[assignment]  # null rejected by schema

    if "task_mode" in updated_fields:
        task.task_mode = request.task_mode  # type: ignore[assignment]  # null rejected by schema

    if "run_instruction_template" in updated_fields:
        task.run_instruction_template = request.run_instruction_template
    elif "worker_profile_id" in updated_fields:
        task.run_instruction_template = None

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
        & {
            "user_prompt",
            "run_instruction_template",
            "task_mode",
            "require_changes",
            "worker_profile_id",
            "provider_id",
        }
    )
    if render_context_changed:
        if issue is None:
            issue = await db.get(Issue, task.issue_id)
        if issue is None:
            raise HTTPException(status_code=404, detail="Issue not found")
        if snapshot is None:
            snapshot = await db.get(TaskWorkerProfileSnapshot, task.id)
        template = task.run_instruction_template
        if template is None:
            if snapshot is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Task has no worker profile snapshot",
                )
            template = select_snapshot_run_instruction_template(
                snapshot,
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
    await _refresh_task_response_state(db, task, snapshot)
    _attach_task_worker_snapshot(task, snapshot)

    logger.info("Task %s updated via PATCH: fields=%s", task_id, sorted(updated_fields))

    return _serialize_task(
        task,
        await get_project_metadata(task.project_id),
        include_prompt_details=True,
    )


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

        slot_info = await check_slot_capacity(
            db, scheduled_at, exclude_task_id=task_id, acquire_lock=True
        )
        if slot_info.is_full and slot_info.enforce:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=slot_full_detail_dict(slot_info),
            )

    issue = (
        await db.execute(select(Issue).where(Issue.id == original_task.issue_id))
    ).scalar_one_or_none()
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")

    try:
        provider = await resolve_provider_for_issue(
            db,
            issue,
            original_task.provider_id,
        )
        worker_profile = await resolve_worker_profile_for_issue(
            db,
            issue,
            original_task.worker_profile_id,
        )
    except WorkerProfileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

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
        provider_id=provider.id,
        worker_profile_id=worker_profile.id,
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
    try:
        snapshot = await prepare_task_runtime_snapshot(
            db,
            new_task,
            issue,
            worker_profile,
            await get_project_metadata(new_task.project_id),
            run_instruction_template=original_task.run_instruction_template,
            template_trigger_source=original_task.trigger_source or "manual",
            replace_snapshot=replace_task_worker_snapshot,
            select_template=select_snapshot_run_instruction_template,
            render_prompt=render_and_store_task_prompt,
        )
    except TaskPromptValidationError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    await db.commit()
    await _refresh_task_response_state(db, new_task, snapshot)
    _attach_task_worker_snapshot(new_task, snapshot)
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

    try:
        worker_profile = await resolve_worker_profile_for_issue(
            db,
            issue,
            request.worker_profile_id,
        )
        provider = await resolve_provider_for_issue(
            db,
            issue,
            request.provider_id,
        )
    except WorkerProfileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

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
        provider_id=provider.id,
        worker_profile_id=worker_profile.id,
        task_mode=request.task_mode,
        require_changes=request.effective_require_changes,
    )
    db.add(task)
    await db.flush()
    try:
        snapshot = await prepare_task_runtime_snapshot(
            db,
            task,
            issue,
            worker_profile,
            await get_project_metadata(issue.project_id),
            run_instruction_template=request.run_instruction_template,
            replace_snapshot=replace_task_worker_snapshot,
            select_template=select_snapshot_run_instruction_template,
            render_prompt=render_and_store_task_prompt,
        )
    except TaskPromptValidationError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    await db.commit()
    await _refresh_task_response_state(db, task, snapshot)
    _attach_task_worker_snapshot(task, snapshot)
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

    return build_task_workspace_status(
        task,
        get_effective_settings(),
        build_paths=build_issue_workspace_paths,
        dir_exists=os.path.isdir,
    )


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
    return remove_task_workspace(
        task,
        get_effective_settings(),
        build_paths=build_issue_workspace_paths,
        remove_workspace=remove_issue_workspace,
    )


@router.get("/tasks/{task_id}/archive")
async def get_task_archive(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Get runtime archive metadata for a completed task."""
    await get_task_with_access_check(
        task_id,
        db,
        access_scope,
        require_operator=False,
    )
    return await get_task_archive_metadata(db, task_id, path_exists=os.path.exists)


@router.get("/tasks/{task_id}/archive/download")
async def download_task_archive(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Download the compressed runtime archive for a completed task."""
    await get_task_with_access_check(
        task_id,
        db,
        access_scope,
        require_operator=False,
    )
    archive = await get_task_archive_file(db, task_id, path_exists=os.path.exists)
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
    await get_task_with_access_check(
        task_id,
        db,
        access_scope,
        require_operator=False,
    )
    return await get_task_payload_content(db, task_id, payload_id)
