"""Task management API endpoints."""

import logging
import os
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.initiator_filters import list_initiator_filter_options
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
    get_task_archive_file,
    get_task_archive_metadata,
    get_task_payload_content,
)
from app.api.task_creation_service import (
    TaskCreationServices,
    create_task_record,
    retry_task_record,
)
from app.api.task_log_routes import (
    router as task_log_router,
)
from app.api.task_operations import (
    get_task_with_access_check,
    notify_task_retried,
    validate_scheduled_datetime_in_future,
    validate_task_status_for_reschedule,
    validate_task_status_for_retry,
)
from app.api.task_queries import TaskListFilters, build_task_list_query
from app.api.task_responses import (
    apply_queue_context,
    compute_task_queue_contexts,
)
from app.api.task_responses import (
    serialize_task as _serialize_task,
)
from app.api.task_runtime_summary_routes import (
    router as task_runtime_summary_router,
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
from app.api.task_update_service import TaskUpdateServices, update_task_record
from app.config import get_effective_settings
from app.core.docker_client import resolve_docker_connection
from app.core.harness_protocol import HARNESS_CONTRACT_VERSION_V2
from app.core.projects import build_project_lookup, get_project_metadata
from app.core.task_creation import prepare_task_runtime_snapshot
from app.core.task_failure_summary import load_task_failure_summary
from app.core.task_prompt import (
    FREEFORM_RUN_INSTRUCTION_TEMPLATE,
    NORMAL_PLACEHOLDER_NAMES,
    PLACEHOLDER_NAMES,
    TaskPromptValidationError,
    build_task_prompt_context,
    render_and_store_task_prompt,
    render_run_instruction_template,
    resolve_task_mode_template,
)
from app.core.usage_limits import (
    get_usage_quota_service,
)
from app.core.utcnow import utcnow
from app.core.worker_kit import MOUNTED_KIT_MODE
from app.core.worker_profiles import (
    clone_task_worker_snapshot,
    replace_task_worker_snapshot,
    resolve_provider_for_issue,
    resolve_worker_profile_for_issue,
    select_snapshot_run_instruction_template,
)
from app.core.worker_runtime_bundle import bind_runtime_bundle
from app.core.worker_runtime_readiness import (
    RuntimeProbeTransientError,
    fingerprint_from_snapshot,
    run_deterministic_kit_probe,
    serialize_runtime_readiness,
)
from app.core.worker_workspace import configured_workspace_root
from app.core.worker_workspace_remote import (
    inspect_issue_workspace,
    remove_issue_workspace_remote,
)
from app.database import get_db
from app.dependencies.auth import (
    get_optional_current_user,
    require_admin_user,
    require_page_access,
)
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access,
    require_project_access_scope,
)
from app.models import (
    AIProvider,
    Issue,
    Task,
    TaskHarnessAttempt,
    TaskStatus,
    TaskWorkerProfileSnapshot,
    User,
    WorkerProfile,
)

logger = logging.getLogger(__name__)
router = APIRouter()
router.include_router(task_action_router)
router.include_router(task_log_router)
router.include_router(task_stats_router)
router.include_router(task_runtime_summary_router)


def _task_creation_services() -> TaskCreationServices:
    """Capture patchable task-module dependencies at request time."""
    from app.core.task_helpers import _require_issue_operator

    return TaskCreationServices(
        require_issue_operator=_require_issue_operator,
        get_task_with_access_check=get_task_with_access_check,
        validate_task_status_for_retry=validate_task_status_for_retry,
        validate_scheduled_datetime_in_future=validate_scheduled_datetime_in_future,
        get_usage_quota_service=get_usage_quota_service,
        get_project_metadata=get_project_metadata,
        resolve_provider_for_issue=resolve_provider_for_issue,
        resolve_worker_profile_for_issue=resolve_worker_profile_for_issue,
        prepare_task_runtime_snapshot=prepare_task_runtime_snapshot,
        replace_task_worker_snapshot=replace_task_worker_snapshot,
        clone_task_worker_snapshot=clone_task_worker_snapshot,
        bind_runtime_bundle=bind_runtime_bundle,
        select_snapshot_run_instruction_template=select_snapshot_run_instruction_template,
        render_and_store_task_prompt=render_and_store_task_prompt,
        notify_task_retried=notify_task_retried,
    )


def _task_update_services() -> TaskUpdateServices:
    """Capture patchable update dependencies at request time."""
    return TaskUpdateServices(
        get_task_with_access_check=get_task_with_access_check,
        get_project_metadata=get_project_metadata,
        resolve_provider_for_issue=resolve_provider_for_issue,
        select_snapshot_run_instruction_template=select_snapshot_run_instruction_template,
        render_and_store_task_prompt=render_and_store_task_prompt,
    )


@router.get("/tasks")
async def list_tasks(
    status: str | None = None,
    project_id: str | None = None,
    issue_id: int | None = None,
    initiator: str | None = None,
    initiator_username: str | None = None,
    priority: str | None = None,
    has_mr: bool | None = None,
    search: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    scheduled_after: str | None = None,
    scheduled_before: str | None = None,
    harness: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    page: int | None = None,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
    _current_user: User | None = Depends(get_optional_current_user),
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
            initiator=initiator,
            initiator_username=initiator_username,
            priority=priority,
            has_mr=has_mr,
            search=search,
            created_after=created_after,
            created_before=created_before,
            scheduled_after=scheduled_after,
            scheduled_before=scheduled_before,
            harness=harness,
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

        count_result = await db.execute(
            select(func.count()).select_from(query.order_by(None).subquery())
        )
        total = count_result.scalar() or 0

        result = await db.execute(query.limit(page_size).offset(offset))
        tasks = result.scalars().all()

        items = [
            _serialize_task(task, project_lookup.get(task.project_id), settings)
            for task in tasks
        ]
        queue_contexts = await compute_task_queue_contexts(db, list(tasks))
        for task, item in zip(tasks, items):
            apply_queue_context(item, task.id, queue_contexts, current_user=_current_user)

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # Legacy mode: return Task[] (max 100)
    result = await db.execute(query.limit(100))
    tasks = result.scalars().all()

    items = [_serialize_task(task, project_lookup.get(task.project_id), settings) for task in tasks]
    queue_contexts = await compute_task_queue_contexts(db, list(tasks))
    for task, item in zip(tasks, items):
        apply_queue_context(item, task.id, queue_contexts, current_user=_current_user)

    return items


@router.get("/tasks/filter-options")
async def get_task_filter_options(
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Return complete task-list filter options within the caller's access scope."""
    result = await list_initiator_filter_options(db, Task, access_scope)

    harness_query = select(
        TaskHarnessAttempt.harness_key,
        func.count(func.distinct(TaskHarnessAttempt.task_id)).label("task_count"),
    ).join(Task, Task.id == TaskHarnessAttempt.task_id)

    if not access_scope.is_unrestricted:
        if not access_scope.accessible_project_ids:
            harness_query = harness_query.where(false())
        else:
            harness_query = harness_query.where(
                Task.project_id.in_(access_scope.accessible_project_ids)
            )

    harness_query = harness_query.group_by(TaskHarnessAttempt.harness_key).order_by(
        TaskHarnessAttempt.harness_key
    )
    harness_result = await db.execute(harness_query)

    result["harnesses"] = [
        {"value": key, "label": key, "count": count}
        for key, count in harness_result.all()
    ]

    return result


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

    serialized = [
        _serialize_task(task, project_lookup.get(task.project_id), settings)
        for task in tasks
    ]
    if tasks:
        # Attach batch per-Issue queue context so Schedule/Heatmap views can show
        # non-head tasks that wait behind a predecessor (§7).
        queue_contexts = await compute_task_queue_contexts(db, tasks)
        for task, data in zip(tasks, serialized):
            apply_queue_context(data, task.id, queue_contexts, current_user=_current_user)
    return serialized


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
        "freeform": {
            "content": FREEFORM_RUN_INSTRUCTION_TEMPLATE,
            "available_placeholders": ["user_prompt"],
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
        require_changes=(
            False if request.task_mode in ("plan", "freeform") else request.require_changes
        ),
        trigger_source="manual",
    )
    try:
        template = resolve_task_mode_template(
            task_mode=request.task_mode,
            submitted_template=request.run_instruction_template,
            default_template=None,
        )
        result = render_run_instruction_template(
            template,
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


@router.get("/tasks/schedule-constraints")
async def get_schedule_constraints(
    issue_id: int | None = Query(default=None),
    task_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Return the valid ``scheduled_at`` window for an append or a reschedule.

    ``issue_id`` returns the tail-create floor (no ceiling) for new Tasks on an
    Issue; ``task_id`` returns the bidirectional window for rescheduling that
    Task. Exactly one of the two is required. The window returned here is a
    convenience projection — the submitting transaction re-validates under the
    Issue row lock and remains the source of truth.

    Registered before ``/tasks/{task_id}`` so the static path is never captured
    as a Task ID.
    """
    from app.core.issue_task_order import IssueOrderIntegrityError, compute_schedule_window

    if task_id is not None and issue_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide exactly one of issue_id or task_id, not both",
        )
    if task_id is not None:
        task = await get_task_with_access_check(task_id, db, access_scope, current_user)
        validate_task_status_for_reschedule(task)
        try:
            return await compute_schedule_window(
                db,
                issue_id=task.issue_id,
                exclude_task_id=task.id,
            )
        except IssueOrderIntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=exc.detail,
            ) from exc
    if issue_id is not None:
        issue = await db.get(Issue, issue_id)
        if issue is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Issue not found",
            )
        require_project_access(issue.project_id, access_scope)
        try:
            return await compute_schedule_window(db, issue_id=issue.id)
        except IssueOrderIntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=exc.detail,
            ) from exc
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Either issue_id or task_id is required",
    )


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
    _current_user: User | None = Depends(get_optional_current_user),
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
            selectinload(Task.provider).load_only(AIProvider.id, AIProvider.name),
            selectinload(Task.worker_profile).load_only(
                WorkerProfile.id,
                WorkerProfile.name,
            ),
            selectinload(Task.worker_profile_snapshot).load_only(
                TaskWorkerProfileSnapshot.worker_profile_id,
                TaskWorkerProfileSnapshot.profile_name,
                TaskWorkerProfileSnapshot.image,
                TaskWorkerProfileSnapshot.runtime_mode,
                TaskWorkerProfileSnapshot.worker_kit_version,
                TaskWorkerProfileSnapshot.skill_selection_source,
                TaskWorkerProfileSnapshot.created_at,
                TaskWorkerProfileSnapshot.harness_key,
                TaskWorkerProfileSnapshot.harness_adapter_version,
                TaskWorkerProfileSnapshot.harness_adapter_digest,
                TaskWorkerProfileSnapshot.harness_config_snapshot,
                TaskWorkerProfileSnapshot.model_endpoint_snapshot,
                TaskWorkerProfileSnapshot.credential_ref,
                TaskWorkerProfileSnapshot.cli_source,
                TaskWorkerProfileSnapshot.cli_executable_path,
                TaskWorkerProfileSnapshot.cli_version,
                TaskWorkerProfileSnapshot.cli_binary_digest,
                TaskWorkerProfileSnapshot.image_digest,
                TaskWorkerProfileSnapshot.runtime_contract_version,
                TaskWorkerProfileSnapshot.orchestration_version,
                TaskWorkerProfileSnapshot.runtime_bundle_digest,
            ),
            selectinload(Task.worker_profile_snapshot).selectinload(
                TaskWorkerProfileSnapshot.skill_references
            ),
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
    queue_contexts = await compute_task_queue_contexts(db, [task])
    apply_queue_context(result_data, task.id, queue_contexts, current_user=_current_user)
    if task.status in (TaskStatus.PENDING, TaskStatus.QUEUED):
        from app.core.issue_task_order import (
            IssueOrderIntegrityError,
            compute_schedule_window,
        )

        try:
            result_data["schedule_constraints"] = await compute_schedule_window(
                db,
                issue_id=task.issue_id,
                exclude_task_id=task.id,
            )
        except IssueOrderIntegrityError as exc:
            # An active Task with a NULL issue_sequence (e.g. the scheduler
            # crash-recovery window) fails the Issue closed; surface the same
            # structured 409 as the schedule-window and reschedule endpoints.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=exc.detail,
            ) from exc
    # Steering/follow-up UI state: the current attempt's control gate and
    # command capability drive whether TaskView shows the live-command input
    # (plan §10: only when control_state == accepting).
    attempt_row = (
        await db.execute(
            select(
                TaskHarnessAttempt.control_state,
                TaskHarnessAttempt.harness_key,
            )
            .where(TaskHarnessAttempt.task_id == task.id)
            .order_by(TaskHarnessAttempt.attempt_no.desc())
            .limit(1)
        )
    ).first()
    if attempt_row is not None:
        result_data["control_state"] = attempt_row.control_state
        result_data["attempt_harness_key"] = attempt_row.harness_key

    failure_summary = await load_task_failure_summary(db, task.id)
    result_data.update(failure_summary)
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
    return await update_task_record(
        task_id=task_id,
        request=request,
        db=db,
        current_user=current_user,
        access_scope=access_scope,
        services=_task_update_services(),
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
    return await retry_task_record(
        task_id=task_id,
        request=request,
        db=db,
        current_user=current_user,
        access_scope=access_scope,
        services=_task_creation_services(),
    )


@router.post("/tasks/{task_id}/verify-worker-runtime")
async def verify_task_worker_runtime(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    """Verify a frozen task snapshot's Worker Kit through the readiness service (§15.2).

    Runs the strict, side-effect-free Kit probe against the snapshot's frozen
    Docker target and returns the post-check readiness. Does not touch the
    task's lifecycle state; a later retry/schedule re-reads the readiness
    record.
    """
    task = await db.get(
        Task,
        task_id,
        options=[selectinload(Task.worker_profile_snapshot)],
    )
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    snapshot = task.worker_profile_snapshot
    if snapshot is None or snapshot.runtime_mode != MOUNTED_KIT_MODE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Task worker runtime verification requires mounted_kit mode",
        )
    settings = get_effective_settings()
    connection = resolve_docker_connection(
        settings,
        docker_host=snapshot.docker_host,
        docker_tls_ca=snapshot.docker_tls_ca,
        docker_tls_cert=snapshot.docker_tls_cert,
        docker_tls_key=snapshot.docker_tls_key,
    )
    fingerprint = fingerprint_from_snapshot(snapshot, settings)
    try:
        outcome = await run_deterministic_kit_probe(
            db,
            connection=connection,
            image=snapshot.image,
            runtime_mode=snapshot.runtime_mode,
            worker_kit_version=snapshot.worker_kit_version or "",
            worker_kit_path=snapshot.worker_kit_path or "",
            ttl_seconds=settings.worker_runtime_readiness_ttl_seconds,
            require_content_inventory=(
                getattr(snapshot, "runtime_contract_version", None)
                == HARNESS_CONTRACT_VERSION_V2
            ),
        )
    except RuntimeProbeTransientError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "worker_runtime_verification_transient_failure",
                "message": f"Worker Kit probe could not reach a conclusion: {exc}",
            },
        ) from exc
    return {
        "ok": True,
        "task_id": task_id,
        "runtime_locator_fingerprint": fingerprint,
        "runtime_mode": snapshot.runtime_mode,
        "worker_kit_version": snapshot.worker_kit_version,
        "docker_host": connection.host,
        "runtime_readiness": serialize_runtime_readiness(outcome.readiness),
    }


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
    return await create_task_record(
        request=request,
        db=db,
        current_user=current_user,
        access_scope=access_scope,
        services=_task_creation_services(),
    )


@router.get("/tasks/{task_id}/workspace")
async def get_task_workspace_status(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    task = await get_task_with_access_check(task_id, db, access_scope, current_user)
    issue = await db.get(Issue, task.issue_id)
    if issue is None:
        return {"enabled": False, "reason": "task has no issue"}
    settings = get_effective_settings()
    if configured_workspace_root(settings) is None:
        return {"enabled": False, "reason": "worker workspace host path is not configured"}
    try:
        workspace = await inspect_issue_workspace(db, settings, issue)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to inspect workspace for issue %s on worker %s: %s",
            issue.id,
            issue.worker_profile_id,
            exc,
        )
        raise HTTPException(
            status_code=502, detail=f"Worker workspace is unavailable: {exc}"
        ) from exc
    return {
        "enabled": True,
        "issue_root": workspace.issue_root,
        "repo_path": workspace.repo_path,
        "issue_exists": workspace.issue_exists,
        "repo_exists": workspace.repo_exists,
        "worker_profile_id": issue.worker_profile_id,
    }


@router.delete("/tasks/{task_id}/workspace")
async def delete_task_workspace(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    task = await get_task_with_access_check(task_id, db, access_scope, current_user)
    issue = (
        await db.execute(select(Issue).where(Issue.id == task.issue_id).with_for_update())
    ).scalar_one_or_none()
    if issue is None:
        raise HTTPException(status_code=404, detail="Workspace not available without issue")
    active_count = (
        await db.execute(
            select(func.count(Task.id)).where(
                Task.issue_id == issue.id,
                or_(
                    Task.status.in_(
                        (TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING)
                    ),
                    Task.container_id.is_not(None),
                ),
            )
        )
    ).scalar_one()
    if active_count:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete workspace while the issue has an active or retained task",
        )

    settings = get_effective_settings()
    if configured_workspace_root(settings) is None:
        raise HTTPException(status_code=404, detail="Worker workspace host path is not configured")
    try:
        removed = await remove_issue_workspace_remote(db, settings, issue)
    except Exception as exc:  # noqa: BLE001
        issue.workspace_delete_attempted_at = utcnow()
        issue.workspace_delete_error = str(exc)[:4000]
        await db.commit()
        raise HTTPException(
            status_code=502, detail=f"Worker workspace deletion failed: {exc}"
        ) from exc

    deleted_at = utcnow()
    issue.workspace_delete_attempted_at = deleted_at
    issue.workspace_deleted_at = deleted_at
    issue.workspace_delete_error = None
    await db.commit()
    return {
        "removed": removed,
        "issue_root": os.path.join(
            configured_workspace_root(settings) or "",
            f"project-{issue.project_id}",
            f"issue-{issue.id}",
        ),
        "worker_profile_id": issue.worker_profile_id,
    }


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
