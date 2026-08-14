"""Business implementation for updating pending tasks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.task_responses import (
    attach_task_worker_snapshot,
    loaded_task_relationship,
    refresh_task_response_state,
    serialize_task,
)
from app.api.task_schemas import UpdateTaskRequest
from app.core.harness_registry import HarnessRegistryError
from app.core.model_endpoints import (
    ensure_harness_protocol_compatibility,
    normalize_endpoint,
)
from app.core.skills import (
    SkillValidationError,
    delete_unreferenced_skill_versions,
    load_enabled_skill_snapshots,
    replace_task_skill_references,
    validate_runtime_supports_skills,
)
from app.core.task_prompt import TaskPromptValidationError
from app.core.worker_profiles import WorkerProfileValidationError
from app.core.worker_shared_configuration import snapshot_effective_configuration_digest
from app.dependencies.project_access import ProjectAccessScope
from app.models import Issue, TaskStatus, TaskWorkerProfileSnapshot, User

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaskUpdateServices:
    get_task_with_access_check: Callable[..., Any]
    get_project_metadata: Callable[..., Any]
    resolve_provider_for_issue: Callable[..., Any]
    select_snapshot_run_instruction_template: Callable[..., Any]
    render_and_store_task_prompt: Callable[..., Any]


async def update_task_record(
    *,
    task_id: int,
    request: UpdateTaskRequest,
    db: AsyncSession,
    current_user: User | None,
    access_scope: ProjectAccessScope,
    services: TaskUpdateServices,
) -> dict:
    task = await services.get_task_with_access_check(
        task_id,
        db,
        access_scope,
        current_user,
        with_for_update=True,
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
    snapshot = loaded_task_relationship(task, "worker_profile_snapshot")
    if "provider_id" in updated_fields:
        issue = await db.get(Issue, task.issue_id)
        if issue is None:
            raise HTTPException(status_code=404, detail="Issue not found")

    if "provider_id" in updated_fields:
        if snapshot is None:
            snapshot = await db.get(TaskWorkerProfileSnapshot, task.id)
        if snapshot is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Task has no worker profile snapshot",
            )
        try:
            provider = await services.resolve_provider_for_issue(
                db,
                issue,
                request.provider_id,
            )
        except WorkerProfileValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        task.provider_id = provider.id
        task.provider_runtime_snapshot = None
        # Keep the frozen snapshot consistent with the provider that will actually
        # execute: re-freeze the secret-free endpoint and credential ref, and
        # reject a provider whose wire protocol cannot talk to the task's frozen
        # harness instead of failing at runtime.
        endpoint = normalize_endpoint(provider)
        harness_key = getattr(snapshot, "harness_key", None) or "claude"
        try:
            ensure_harness_protocol_compatibility(harness_key, endpoint)
        except (HarnessRegistryError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        snapshot.model_endpoint_snapshot = endpoint.as_snapshot()
        snapshot.credential_ref = endpoint.credential_ref

    if "require_changes" in updated_fields:
        task.require_changes = request.require_changes
    if "task_mode" in updated_fields:
        task.task_mode = request.task_mode
    if "run_instruction_template" in updated_fields:
        task.run_instruction_template = request.run_instruction_template

    if "skill_ids" in updated_fields:
        if snapshot is None:
            snapshot = await db.get(TaskWorkerProfileSnapshot, task.id)
        if snapshot is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Task has no worker profile snapshot",
            )
        requested_skill_ids = request.skill_ids
        if requested_skill_ids is None:
            profile = loaded_task_relationship(task, "worker_profile")
            if profile is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Task worker profile is no longer available",
                )
            requested_skill_ids = [
                skill.id
                for skill in (getattr(profile, "default_skills", None) or [])
                if bool(getattr(skill, "enabled", False))
            ]
            selection_source = "profile"
        else:
            selection_source = "task"
        try:
            selected_skills = await load_enabled_skill_snapshots(db, requested_skill_ids)
            validate_runtime_supports_skills(snapshot, selected_skills)
        except SkillValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        replace_task_skill_references(snapshot, selected_skills)
        snapshot.skill_selection_source = selection_source
        snapshot.effective_configuration_digest = snapshot_effective_configuration_digest(
            snapshot
        )

    if task.task_mode == "plan":
        task.require_changes = False

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
            template = services.select_snapshot_run_instruction_template(
                snapshot,
                task_mode=task.task_mode or "execute",
                trigger_source=task.trigger_source or "manual",
            )
        try:
            services.render_and_store_task_prompt(
                task,
                issue,
                await services.get_project_metadata(task.project_id),
                template,
            )
        except TaskPromptValidationError as exc:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    if "skill_ids" in updated_fields:
        await db.flush()
        await delete_unreferenced_skill_versions(db)
    await db.commit()
    await refresh_task_response_state(db, task, snapshot)
    attach_task_worker_snapshot(task, snapshot)
    logger.info("Task %s updated via PATCH: fields=%s", task_id, sorted(updated_fields))
    return serialize_task(
        task,
        await services.get_project_metadata(task.project_id),
        include_prompt_details=True,
    )
