"""Task cancellation and scheduling action routes."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.task_operations import (
    get_task_with_access_check,
    notify_task_cancelled,
    notify_task_execute_now,
    notify_task_rescheduled,
    validate_scheduled_datetime_in_future,
    validate_task_status_for_cancel,
    validate_task_status_for_execute,
    validate_task_status_for_reschedule,
)
from app.api.task_responses import (
    attach_task_worker_snapshot,
    loaded_task_relationship,
    refresh_task_response_state,
    serialize_task,
)
from app.api.task_schemas import RescheduleTaskRequest
from app.config import get_effective_settings
from app.core.docker_client import get_docker_client_async
from app.core.issue_execution_locks import release_issue_execution_lock
from app.core.projects import get_project_metadata
from app.core.task_helpers import maybe_update_issue_status
from app.core.task_log_payloads import persist_raw_log_snapshot
from app.core.utcnow import utcnow
from app.core.worker_docker_targets import (
    DockerConnectionsUnavailableError,
    TaskContainerLookupError,
    TaskContainerNotFoundError,
    find_task_container,
)
from app.database import get_db
from app.dependencies.auth import get_optional_current_user
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access_scope,
)
from app.models import TaskStatus, User

logger = logging.getLogger(__name__)
router = APIRouter()


class OverrideStatusRequest(BaseModel):
    status: str
    reason: str | None = None


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Cancel a task and finalize its authoritative raw log when possible."""
    task = await get_task_with_access_check(task_id, db, access_scope, current_user)
    validate_task_status_for_cancel(task)

    settings = get_effective_settings()
    container_name = f"{settings.worker_container_prefix}-{task_id}-issue{task.issue_id}"
    task_container_id = getattr(task, "container_id", None)
    if not isinstance(task_container_id, str) or not task_container_id.strip():
        task_container_id = None
    container_reference = task_container_id or container_name
    container = None
    raw_console_log: bytes | None = None
    container_absent = task.status != TaskStatus.RUNNING and task_container_id is None
    logger.info(
        "Cancellation requested for task %s (status=%s, container=%s)",
        task_id,
        task.status.value,
        container_reference,
    )
    if task.status == TaskStatus.RUNNING and task.cancel_requested_at is None:
        task.cancel_requested_at = utcnow()
        await db.commit()
        await db.refresh(task)
        logger.info(
            "Persisted cancellation intent for running task %s before stopping container %s",
            task_id,
            container_reference,
        )

    if not container_absent:
        try:
            docker, container, connection = await find_task_container(
                db,
                task,
                settings,
                container_reference,
                get_client=get_docker_client_async,
            )
            logger.info(
                "Located container %s for task %s on Docker daemon %s",
                container_reference,
                task_id,
                connection.host,
            )
        except TaskContainerNotFoundError:
            if task.status == TaskStatus.RUNNING and task_container_id is None:
                logger.warning(
                    "Cancellation for task %s remains pending because its worker "
                    "container has not published a stable ID yet",
                    task_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=(
                        "Cancellation was recorded while the worker container is still "
                        "starting; the task remains active until startup converges"
                    ),
                )
            container_absent = True
            logger.info(
                "Container %s for task %s is confirmed absent; completing cancellation",
                container_reference,
                task_id,
            )
        except (DockerConnectionsUnavailableError, TaskContainerLookupError) as exc:
            logger.warning(
                "Cancellation deferred for task %s because container %s could not be "
                "resolved: %s",
                task_id,
                container_reference,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Cancellation could not be confirmed because the worker Docker "
                    "daemon is unavailable; the task remains active"
                ),
            ) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Cancellation deferred for task %s after an unexpected container "
                "lookup failure",
                task_id,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Cancellation could not be confirmed because the worker container "
                    "state is unknown; the task remains active"
                ),
            ) from exc

    if container is not None:
        try:
            await asyncio.to_thread(container.stop, timeout=10)
            logger.info("Stopped container %s for cancelled task %s", container_reference, task_id)
        except Exception as stop_error:  # noqa: BLE001
            logger.warning(
                "Graceful stop failed for task %s container %s: %s; forcing stop",
                task_id,
                container_reference,
                stop_error,
            )
            try:
                await asyncio.to_thread(container.kill)
                logger.info(
                    "Force-stopped container %s for task %s",
                    container_reference,
                    task_id,
                )
            except Exception as kill_error:  # noqa: BLE001
                logger.error(
                    "Cancellation deferred for task %s because container %s could not "
                    "be stopped: graceful=%s; force=%s",
                    task_id,
                    container_reference,
                    stop_error,
                    kill_error,
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=(
                        "Cancellation could not stop the worker container; the task "
                        "remains active"
                    ),
                ) from kill_error

        try:
            raw_console_log = await asyncio.to_thread(
                docker.read_file_from_container,
                container,
                "/tmp/codify-runtime/console.log",
            )
        except Exception as log_error:  # noqa: BLE001
            logger.warning(
                "Stopped task %s container %s but could not read its final console log: %s",
                task_id,
                container_reference,
                log_error,
            )

    # Re-read the authoritative status: while this cancel was stopping the
    # container and draining logs, the scheduler finalizer may have already
    # converged a genuinely-completed run to COMPLETED. Never downgrade a
    # terminal outcome to CANCELLED.
    await db.refresh(task)
    if (
        task.status in (TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING)
        and (container_absent or task.status != TaskStatus.RUNNING)
    ):
        # No live execution to converge (PENDING/QUEUED, or RUNNING whose
        # container is already gone): finalize as cancelled directly. A RUNNING
        # task with a live container keeps RUNNING here — the scheduler finalizer
        # converges the authoritative canonical terminal (a run that already
        # completed stays COMPLETED; a TERM-interrupted run becomes CANCELLED).
        task.status = TaskStatus.CANCELLED
        task.completed_at = utcnow()
        task.error_message = "Cancelled by user"
    # Do not clobber raw_logs_finalized_at, which would force a retained-container
    # round trip.
    await db.commit()
    await db.refresh(task)
    logger.info(
        "Committed cancellation for task %s after worker container convergence",
        task_id,
    )

    raw_logs_finalized = container_absent
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
    if container_absent and raw_logs_finalized:
        task.container_id = None
    await db.commit()

    if container is not None:
        # Physical removal is owned by the scheduler's worker finalization, which
        # drains the log stream (capturing the cancelled terminal the container's
        # EXIT-trap finalizer emits) and then removes the container. Removing the
        # container here races that drain and can drop the canonical terminal for
        # a very early cancel, leaving the attempt without a run terminal. The
        # scheduler releases the issue execution lock once finalization completes.
        logger.info(
            "Cancelled task %s: deferring container removal to worker finalization",
            task_id,
        )

    if task.container_id is None:
        await release_issue_execution_lock(
            db,
            issue_id=task.issue_id,
            owner_task_id=task.id,
        )
        await db.commit()
        logger.info(
            "Released issue %s execution lock for cancelled task %s",
            task.issue_id,
            task_id,
        )
    else:
        logger.warning(
            "Keeping issue %s locked because cancelled task %s retains container %s",
            task.issue_id,
            task_id,
            task.container_id,
        )
    await notify_task_cancelled(task)
    logger.info(f"Task {task_id} cancelled via API")

    if task.issue_id is not None:
        await maybe_update_issue_status(db, task.issue_id)
    return {"status": "success", "message": f"Task {task_id} cancelled"}


@router.post("/tasks/{task_id}/override-status")
async def override_task_status(
    task_id: int,
    request: OverrideStatusRequest,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
    current_user: User | None = Depends(get_optional_current_user),
) -> dict:
    """Manually override a terminal task's status."""
    task = await get_task_with_access_check(task_id, db, access_scope, current_user)
    if request.status not in ("completed", "failed"):
        raise HTTPException(
            status_code=400,
            detail="status must be 'completed' or 'failed'",
        )

    new_status = TaskStatus(request.status)
    if task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
        raise HTTPException(
            status_code=400,
            detail=f"Can only override completed or failed tasks, current: {task.status.value}",
        )
    if task.status == new_status:
        raise HTTPException(
            status_code=400,
            detail=f"Task is already {task.status.value}",
        )

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
    return {
        "status": "success",
        "message": f"Task {task_id} status overridden to {new_status.value}",
    }


@router.post("/tasks/{task_id}/execute")
async def execute_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Trigger immediate execution of a pending task.

    Execute-now only clears the Task's own ``scheduled_at``. A non-head Task
    still waits for its active predecessors; the response reports that blocking
    fact instead of claiming the Task bypassed the Issue queue (§7.2).
    """
    from app.api.task_responses import compute_task_queue_contexts

    task = await get_task_with_access_check(task_id, db, access_scope, current_user)
    validate_task_status_for_execute(task)

    previous_scheduled_at = task.scheduled_at
    task.scheduled_at = None
    await db.commit()
    await db.refresh(task)

    queue_contexts = await compute_task_queue_contexts(db, [task])
    ctx = queue_contexts.get(task.id) or {}
    queue_position = ctx.get("queue_position")

    if queue_position is not None and queue_position > 1:
        await notify_task_execute_now(task, previous_scheduled_at)
        logger.info(
            "Task %s cleared scheduled_at; still waits for predecessors",
            task_id,
        )
        return {
            "status": "success",
            "message": "Task will run after its predecessors complete",
            "queue_position": queue_position,
            "blocked_by_task_id": ctx.get("blocked_by_task_id"),
        }

    await notify_task_execute_now(task, previous_scheduled_at)
    logger.info(f"Task {task_id} scheduled for immediate execution")
    return {
        "status": "success",
        "message": f"Task {task_id} scheduled for immediate execution",
        "queue_position": queue_position,
    }


@router.patch("/tasks/{task_id}/schedule")
async def reschedule_task(
    task_id: int,
    request: RescheduleTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Update the execution time for a pending scheduled task.

    The new time must stay inside the Issue queue window: not before the latest
    scheduled time of any earlier active Task and not after the earliest
    scheduled time of any later active Task (§4.2). The window is re-validated
    under the Issue row lock (before the Slot advisory lock, §6.3) so a
    concurrent append or reschedule cannot submit a monotonic-order violation.
    """
    from sqlalchemy import select

    from app.api.task_responses import (
        apply_queue_context,
        compute_task_queue_contexts,
    )
    from app.core.issue_task_order import (
        ScheduleWindowConflict,
        compute_schedule_window,
        count_active_successors,
        validate_schedule_time_locked,
    )
    from app.models import Issue

    task = await get_task_with_access_check(task_id, db, access_scope, current_user)
    validate_task_status_for_reschedule(task)
    normalized_scheduled = validate_scheduled_datetime_in_future(request.scheduled_datetime)

    issue = (
        await db.execute(select(Issue).where(Issue.id == task.issue_id).with_for_update())
    ).scalar_one_or_none()
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    try:
        await validate_schedule_time_locked(
            db,
            issue_id=issue.id,
            scheduled_at=normalized_scheduled,
            exclude_task_id=task.id,
        )
    except ScheduleWindowConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.detail,
        ) from exc

    from app.core.slot_capacity import check_slot_capacity, slot_full_detail_dict

    slot_info = await check_slot_capacity(
        db,
        normalized_scheduled,
        exclude_task_id=task_id,
        acquire_lock=True,
    )
    if slot_info.is_full and slot_info.enforce:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=slot_full_detail_dict(slot_info),
        )

    # An active head that moves to a future time re-enters PENDING and keeps
    # every active successor blocked behind it; report the blast radius (§7.3).
    blocked_successor_count = 0
    is_head = task.status == TaskStatus.QUEUED
    if not is_head:
        pre_contexts = await compute_task_queue_contexts(db, [task])
        is_head = (pre_contexts.get(task.id) or {}).get("queue_position") == 1
    if is_head:
        blocked_successor_count = await count_active_successors(
            db,
            issue_id=issue.id,
            task_id=task.id,
        )

    previous_scheduled_at = task.scheduled_at
    snapshot = loaded_task_relationship(task, "worker_profile_snapshot")
    task.scheduled_at = normalized_scheduled
    if task.status == TaskStatus.QUEUED:
        task.status = TaskStatus.PENDING
    await db.commit()
    await refresh_task_response_state(db, task, snapshot)
    attach_task_worker_snapshot(task, snapshot)

    await notify_task_rescheduled(
        task,
        previous_scheduled_at,
        normalized_scheduled,
    )
    logger.info(
        "Task %s rescheduled to %s via API",
        task_id,
        normalized_scheduled.isoformat(),
    )
    response = serialize_task(
        task,
        await get_project_metadata(task.project_id),
        include_prompt_details=True,
    )
    queue_contexts = await compute_task_queue_contexts(db, [task])
    apply_queue_context(response, task.id, queue_contexts)
    response["blocked_successor_count"] = blocked_successor_count
    response["schedule_constraints"] = await compute_schedule_window(
        db,
        issue_id=issue.id,
        exclude_task_id=task.id,
    )
    return response
