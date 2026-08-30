"""Top-level task execution and resume orchestration."""

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.harness_execution_policy import (
    ExecutionPolicyError,
    execution_rejection_detail,
)
from app.core.task_command_gate import close_task_control_gates
from app.core.utcnow import utcnow
from app.core.worker_docker_targets import (
    DockerConnectionsUnavailableError,
    TaskContainerLookupError,
)
from app.core.worker_task_lifecycle import (
    create_execute_container,
    prepare_execute_task_context,
    prepare_resume_task_context,
    stop_container_for_persisted_cancellation,
)
from app.models import Task, TaskStatus

logger = logging.getLogger(__name__)


async def run_execute_task(
    worker,
    db: AsyncSession,
    task_id: int,
    *,
    settings: Any,
) -> bool:
    context = await prepare_execute_task_context(worker, db, task_id, settings=settings)
    if not context:
        return False
    if context["handled"]:
        return context["result"]

    settings = context["settings"]
    task = context["task"]
    issue = context["issue"]
    had_existing_mr = context["had_existing_mr"]
    sudo_gl = context["sudo_gl"]
    container = None

    try:
        try:
            container = await create_execute_container(
                worker,
                db,
                settings=settings,
                task=task,
                issue=issue,
                sudo_gl=sudo_gl,
            )
            if container is None:
                return False
            await db.refresh(task)
            if task.status == TaskStatus.CANCELLED or isinstance(
                getattr(task, "cancel_requested_at", None),
                datetime,
            ):
                await stop_container_for_persisted_cancellation(container, task_id)
        except ValueError as error:
            logger.error(
                "[Task %s] Failed while building worker environment: %s",
                task_id,
                error,
            )
            return await worker._handle_execute_task_failure(
                db,
                task,
                error,
                had_existing_mr=had_existing_mr,
                issue=issue,
            )

        return await worker._monitor_container_run(
            db=db,
            task=task,
            issue=issue,
            container=container,
            settings=settings,
            had_existing_mr=had_existing_mr,
            sudo_gl=sudo_gl,
        )
    except (DockerConnectionsUnavailableError, TaskContainerLookupError):
        raise
    except Exception as error:  # noqa: BLE001
        logger.exception("Task %s failed with exception: %s", task_id, error)
        return await worker._handle_execute_task_failure(
            db,
            task,
            error,
            had_existing_mr=had_existing_mr,
            issue=issue,
            container=container,
        )


async def run_resume_task(
    worker,
    db: AsyncSession,
    task_id: int,
    container_name: str,
    *,
    settings: Any,
) -> bool:
    try:
        context = await prepare_resume_task_context(
            worker,
            db,
            task_id,
            container_name,
            settings=settings,
        )
    except ExecutionPolicyError as error:
        # Resume/recovery is a terminal boundary: a V2 task without its
        # durable attempt must never remain RUNNING after direct invocation.
        # Do not attach to the container or start the command pump; recovery
        # will reconcile any retained container from the terminal task row.
        result = await db.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if task is not None:
            task.status = TaskStatus.FAILED
            task.completed_at = task.completed_at or utcnow()
            task.error_message = json.dumps(
                execution_rejection_detail(error, action="resume", subject=task_id),
                ensure_ascii=False,
                sort_keys=True,
            )[:1000]
            await close_task_control_gates(
                db,
                task_id=task_id,
                reason=f"resume rejected: {error.code}",
            )
            await db.commit()
        return False
    if not context:
        return False
    if context["handled"]:
        return context["result"]

    try:
        return await worker._monitor_container_run(
            db=db,
            task=context["task"],
            issue=context["issue"],
            container=context["container"],
            settings=context["settings"],
            had_existing_mr=context["had_existing_mr"],
            sudo_gl=context["sudo_gl"],
            resume_prefix=" (resume)",
        )
    except (DockerConnectionsUnavailableError, TaskContainerLookupError):
        raise
    except Exception as error:  # noqa: BLE001
        return await worker._handle_resume_task_failure(
            db,
            task_id,
            context["task"],
            context["container"],
            error,
            had_existing_mr=context["had_existing_mr"],
            issue=context["issue"],
        )


async def process_pending_tasks(worker, db: AsyncSession) -> int:
    result = await db.execute(
        select(Task).where(Task.status == TaskStatus.PENDING).order_by(Task.created_at)
    )
    tasks = result.scalars().all()

    processed = 0
    for task in tasks:
        if await worker.execute_task(db, task.id):
            processed += 1
    return processed
