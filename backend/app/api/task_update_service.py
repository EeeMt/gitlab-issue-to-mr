"""Business implementation for updating pending tasks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.task_operations import require_task_execution_writer
from app.api.task_responses import (
    attach_task_worker_snapshot,
    loaded_task_relationship,
    refresh_task_response_state,
    serialize_task,
)
from app.api.task_schemas import UpdateTaskRequest
from app.config import get_effective_settings
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
from app.core.task_prompt import TaskPromptValidationError, resolve_task_mode_template
from app.core.worker_profiles import (
    WorkerProfileValidationError,
    replace_task_worker_snapshot,
)
from app.core.worker_runtime_readiness import (
    readiness_for_profile,
    runtime_unavailable_http_detail,
)
from app.core.worker_shared_configuration import (
    load_shared_configuration,
    snapshot_effective_configuration_digest,
)
from app.dependencies.project_access import ProjectAccessScope
from app.models import (
    Issue,
    TaskStatus,
    TaskWorkerProfileSnapshot,
    User,
    WorkerProfile,
)

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
    require_task_execution_writer(task, action="update")

    updated_fields = request.model_fields_set
    original_task_mode = task.task_mode or "execute"
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

    if "worker_profile_id" in updated_fields:
        # §12.3: an explicit worker switch on a not-yet-executed Task re-resolves
        # the current shared configuration, re-checks runtime readiness, and
        # replaces the frozen snapshot. Prompt-only edits never reach this path,
        # so they never refresh the snapshot.
        if issue is None:
            issue = await db.get(Issue, task.issue_id)
        if issue is None:
            raise HTTPException(status_code=404, detail="Issue not found")
        if snapshot is None:
            snapshot = await db.get(TaskWorkerProfileSnapshot, task.id)
        if snapshot is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Task has no worker profile snapshot",
            )
        # Every writer that needs both rows follows the same global order:
        # Shared configuration, then the selected Profile.  In particular,
        # get_task_with_access_check may already have put the Task's current
        # Profile in this session's identity map before a concurrent Profile
        # PATCH commits.  Lock Shared first, then force a locked re-read of the
        # target Profile so readiness and snapshotting cannot use that stale
        # identity-map value.
        shared = await load_shared_configuration(db, for_update=True)
        new_profile = await db.get(
            WorkerProfile,
            request.worker_profile_id,
            options=[
                selectinload(WorkerProfile.environment_variables),
                selectinload(WorkerProfile.default_skills),
            ],
            with_for_update=True,
            populate_existing=True,
        )
        if new_profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Worker profile not found",
            )
        # get_task_with_access_check loads task.worker_profile without its
        # environment_variables, so this profile may already sit in the session
        # identity map with that collection unloaded — and db.get() with loader
        # options does not re-apply them to an identity-mapped object. Force-load
        # the collections the switch touches below so a later lazy access cannot
        # raise MissingGreenlet (and silently bypass the readiness gate).
        await db.refresh(
            new_profile,
            attribute_names=["environment_variables", "default_skills"],
        )
        if not new_profile.enabled:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Worker profile '{new_profile.name}' is disabled",
            )
        # Hand the same locked Shared context to both the readiness gate and the
        # frozen snapshot so a concurrent shared PATCH cannot interleave between
        # the two reads (§11.2).
        readiness = await readiness_for_profile(
            db,
            new_profile,
            get_effective_settings(),
            shared=shared,
        )
        if readiness.is_unavailable:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=runtime_unavailable_http_detail(readiness),
            )
        old_skill_ids = [
            reference.skill_id
            for reference in (getattr(snapshot, "skill_references", None) or [])
            if isinstance(getattr(reference, "skill_id", None), int)
        ]
        old_selection_source = getattr(snapshot, "skill_selection_source", None)
        try:
            provider = await services.resolve_provider_for_issue(
                db, issue, task.provider_id
            )
        except WorkerProfileValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        harness_key = getattr(new_profile, "default_harness_key", None) or "claude"
        endpoint = normalize_endpoint(provider)
        try:
            ensure_harness_protocol_compatibility(harness_key, endpoint)
        except (HarnessRegistryError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        task.provider_id = provider.id
        task.provider_runtime_snapshot = None
        snapshot = await replace_task_worker_snapshot(
            db,
            task,
            new_profile,
            harness_key=harness_key,
            endpoint=endpoint,
            shared_configuration=shared,
        )
        # Preserve the task's skill selection across the switch: a task-sourced
        # selection carries its skill ids over (re-validated against the new
        # runtime), while a profile-sourced selection falls back to the new
        # Profile defaults.
        if old_selection_source == "task" and old_skill_ids:
            requested_skill_ids = old_skill_ids
            selection_source = "task"
        else:
            requested_skill_ids = [
                skill.id
                for skill in (getattr(new_profile, "default_skills", None) or [])
                if bool(getattr(skill, "enabled", False))
            ]
            selection_source = "profile"
        try:
            selected_skills = await load_enabled_skill_snapshots(
                db, requested_skill_ids
            )
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

    if task.task_mode in ("plan", "freeform"):
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
            "worker_profile_id",
        }
    )
    if render_context_changed:
        if issue is None:
            issue = await db.get(Issue, task.issue_id)
        if issue is None:
            raise HTTPException(status_code=404, detail="Issue not found")
        if snapshot is None:
            snapshot = await db.get(TaskWorkerProfileSnapshot, task.id)
        target_mode = task.task_mode or "execute"
        submitted_template = (
            request.run_instruction_template
            if "run_instruction_template" in updated_fields
            else None
        )
        mode_changed = original_task_mode != target_mode
        try:
            if target_mode == "freeform":
                # freeform always resolves to the canonical template and rejects
                # any other explicit template; require_changes was forced false above.
                template = resolve_task_mode_template(
                    task_mode="freeform",
                    submitted_template=submitted_template,
                    default_template=None,
                )
            elif submitted_template is not None:
                template = resolve_task_mode_template(
                    task_mode=target_mode,
                    submitted_template=submitted_template,
                    default_template=None,
                )
            elif mode_changed:
                # Switching to execute/plan without an explicit template uses the
                # frozen snapshot's target-mode default — never the previous
                # freeform {{user_prompt}} template.
                if snapshot is None:
                    raise TaskPromptValidationError("Task has no worker profile snapshot")
                default_template = services.select_snapshot_run_instruction_template(
                    snapshot,
                    task_mode=target_mode,
                    trigger_source=task.trigger_source or "manual",
                )
                template = resolve_task_mode_template(
                    task_mode=target_mode,
                    submitted_template=None,
                    default_template=default_template,
                )
            else:
                # Mode unchanged without an explicit template: keep the existing
                # task snapshot template, backfilled from the frozen snapshot when
                # the task predates prompt persistence.
                default_template = task.run_instruction_template
                if default_template is None:
                    if snapshot is None:
                        raise TaskPromptValidationError("Task has no worker profile snapshot")
                    default_template = services.select_snapshot_run_instruction_template(
                        snapshot,
                        task_mode=target_mode,
                        trigger_source=task.trigger_source or "manual",
                    )
                template = resolve_task_mode_template(
                    task_mode=target_mode,
                    submitted_template=None,
                    default_template=default_template,
                )
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
