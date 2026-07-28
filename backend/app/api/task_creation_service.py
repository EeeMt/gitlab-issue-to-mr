"""Business implementations for creating and retrying tasks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.task_responses import (
    attach_task_worker_snapshot,
    refresh_task_response_state,
    serialize_task,
)
from app.api.task_schemas import CreateTaskRequest, RetryTaskRequest
from app.core.scheduling import resolve_scheduled_at
from app.core.skills import SkillValidationError, skill_snapshots_from_task_snapshot
from app.core.task_prompt import TaskPromptValidationError
from app.core.usage_limits import UsageLimitExceeded, usage_limit_exceeded_detail
from app.core.utcnow import utcnow
from app.core.worker_profiles import WorkerProfileValidationError
from app.dependencies.project_access import ProjectAccessScope, require_project_access
from app.models import Issue, Task, User

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaskCreationServices:
    require_issue_operator: Callable[..., Any]
    get_task_with_access_check: Callable[..., Any]
    validate_task_status_for_retry: Callable[..., Any]
    validate_scheduled_datetime_in_future: Callable[..., Any]
    get_usage_quota_service: Callable[..., Any]
    get_project_metadata: Callable[..., Any]
    resolve_provider_for_issue: Callable[..., Any]
    resolve_worker_profile_for_issue: Callable[..., Any]
    prepare_task_runtime_snapshot: Callable[..., Any]
    replace_task_worker_snapshot: Callable[..., Any]
    select_snapshot_run_instruction_template: Callable[..., Any]
    render_and_store_task_prompt: Callable[..., Any]
    notify_task_retried: Callable[..., Any]


async def _raise_if_usage_limited(
    db: AsyncSession,
    current_user: User | None,
    services: TaskCreationServices,
) -> None:
    if current_user is None or current_user.id is None:
        return
    try:
        await services.get_usage_quota_service().raise_if_over_limit(
            db,
            current_user.id,
            scope="create",
        )
    except UsageLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=usage_limit_exceeded_detail(exc),
        ) from exc


async def retry_task_record(
    *,
    task_id: int,
    request: RetryTaskRequest | None,
    db: AsyncSession,
    current_user: User | None,
    access_scope: ProjectAccessScope,
    services: TaskCreationServices,
) -> dict:
    original_task = await services.get_task_with_access_check(
        task_id,
        db,
        access_scope,
        current_user,
    )
    services.validate_task_status_for_retry(original_task)

    existing_retry = (
        await db.execute(
            select(Task).where(
                Task.retry_source_task_id == task_id,
                Task.status.in_(["pending", "queued", "running"]),
            )
        )
    ).scalar_one_or_none()
    if existing_retry:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An active retry task (#{existing_retry.id}) already exists for task #{task_id}",
        )

    scheduled_at: datetime | None = None
    if request and request.scheduled_datetime is not None:
        scheduled_at = services.validate_scheduled_datetime_in_future(request.scheduled_datetime)

    await _raise_if_usage_limited(db, current_user, services)
    if scheduled_at is not None:
        from app.core.slot_capacity import check_slot_capacity, slot_full_detail_dict

        slot_info = await check_slot_capacity(
            db,
            scheduled_at,
            exclude_task_id=task_id,
            acquire_lock=True,
        )
        if slot_info.is_full and slot_info.enforce:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=slot_full_detail_dict(slot_info),
            )

    issue = (
        await db.execute(
            select(Issue).where(Issue.id == original_task.issue_id).with_for_update()
        )
    ).scalar_one_or_none()
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.status == "closed":
        raise HTTPException(status_code=400, detail="Cannot retry tasks on a closed issue")

    try:
        provider = await services.resolve_provider_for_issue(
            db,
            issue,
            original_task.provider_id,
        )
        worker_profile = await services.resolve_worker_profile_for_issue(
            db,
            issue,
        )
    except WorkerProfileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    original_session_mode = getattr(original_task, "session_mode", "continue")
    original_output_session_id = getattr(original_task, "output_session_id", None)
    retry_session_mode = (
        "fresh"
        if original_session_mode == "fresh"
        and not (isinstance(original_output_session_id, str) and original_output_session_id.strip())
        else "continue"
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
        provider_id=provider.id,
        worker_profile_id=worker_profile.id,
        initiator_user_id=current_user.id if current_user is not None else None,
        initiator_gitlab_user_id=(
            current_user.gitlab_user_id if current_user is not None else None
        ),
        initiator_username=current_user.username if current_user is not None else None,
        initiator_display_name=(current_user.display_name if current_user is not None else None),
        initiator_email=current_user.email if current_user is not None else None,
        task_mode=original_task.task_mode if original_task.task_mode else "execute",
        require_changes=original_task.require_changes,
        # Continue a session established by the source run. If a fresh run failed before it
        # produced a session, preserve fresh mode so the retry cannot fall back to the old one.
        session_mode=retry_session_mode,
    )
    issue.workspace_last_used_at = utcnow()
    issue.workspace_delete_attempted_at = None
    issue.workspace_deleted_at = None
    issue.workspace_delete_error = None
    db.add(new_task)
    await db.flush()
    try:
        snapshot = await services.prepare_task_runtime_snapshot(
            db,
            new_task,
            issue,
            worker_profile,
            await services.get_project_metadata(new_task.project_id),
            run_instruction_template=original_task.run_instruction_template,
            template_trigger_source=original_task.trigger_source or "manual",
            replace_snapshot=services.replace_task_worker_snapshot,
            select_template=services.select_snapshot_run_instruction_template,
            render_prompt=services.render_and_store_task_prompt,
            skill_snapshots=(
                skill_snapshots_from_task_snapshot(original_task.worker_profile_snapshot)
                if original_task.worker_profile_snapshot is not None
                else []
            ),
            skill_selection_source=getattr(
                getattr(original_task, "worker_profile_snapshot", None),
                "skill_selection_source",
                "profile",
            ),
        )
    except (TaskPromptValidationError, SkillValidationError) as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    await db.commit()
    await refresh_task_response_state(db, new_task, snapshot)
    attach_task_worker_snapshot(new_task, snapshot)
    new_task.issue = issue
    await services.notify_task_retried(new_task, None, scheduled_at)
    action = f"scheduled for retry at {scheduled_at}" if scheduled_at else "created as retry"
    logger.info("Task %s %s (retry of task %s)", new_task.id, action, task_id)
    return serialize_task(
        new_task,
        await services.get_project_metadata(new_task.project_id),
        include_prompt_details=True,
    )


async def create_task_record(
    *,
    request: CreateTaskRequest,
    db: AsyncSession,
    current_user: User | None,
    access_scope: ProjectAccessScope,
    services: TaskCreationServices,
) -> dict:
    issue = await db.get(Issue, request.issue_id, with_for_update=True)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.status == "closed":
        raise HTTPException(status_code=400, detail="Cannot create tasks on a closed issue")

    services.require_issue_operator(issue, current_user)
    require_project_access(issue.project_id, access_scope)
    prompt = request.user_prompt or issue.description
    if not prompt:
        raise HTTPException(
            status_code=400,
            detail="No prompt provided and issue has no description",
        )

    try:
        worker_profile = await services.resolve_worker_profile_for_issue(
            db,
            issue,
        )
        provider = await services.resolve_provider_for_issue(
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
    await _raise_if_usage_limited(db, current_user, services)

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
        initiator_gitlab_user_id=(
            current_user.gitlab_user_id if current_user is not None else None
        ),
        initiator_username=current_user.username if current_user is not None else None,
        initiator_display_name=(current_user.display_name if current_user is not None else None),
        initiator_email=current_user.email if current_user is not None else None,
        priority=request.priority,
        scheduled_at=scheduled_at,
        provider_id=provider.id,
        worker_profile_id=worker_profile.id,
        task_mode=request.task_mode,
        require_changes=request.effective_require_changes,
        session_mode=request.session_mode,
    )
    issue.workspace_last_used_at = utcnow()
    issue.workspace_delete_attempted_at = None
    issue.workspace_deleted_at = None
    issue.workspace_delete_error = None
    db.add(task)
    await db.flush()
    try:
        snapshot = await services.prepare_task_runtime_snapshot(
            db,
            task,
            issue,
            worker_profile,
            await services.get_project_metadata(issue.project_id),
            run_instruction_template=request.run_instruction_template,
            replace_snapshot=services.replace_task_worker_snapshot,
            select_template=services.select_snapshot_run_instruction_template,
            render_prompt=services.render_and_store_task_prompt,
            skill_ids=request.skill_ids,
            skill_ids_provided=(
                "skill_ids" in request.model_fields_set and request.skill_ids is not None
            ),
        )
    except (TaskPromptValidationError, SkillValidationError) as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    await db.commit()
    await refresh_task_response_state(db, task, snapshot)
    attach_task_worker_snapshot(task, snapshot)
    task.issue = issue
    logger.info(
        "Created task %s for issue %s (project %s), priority=%s, delay=%s",
        task.id,
        issue.id,
        issue.project_id,
        request.priority,
        request.delay_seconds,
    )

    response = serialize_task(
        task,
        await services.get_project_metadata(issue.project_id),
        include_prompt_details=True,
    )
    if slot_warning:
        response["slot_warning"] = slot_warning
    return response
