"""Top-level task execution and resume orchestration."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.worker_task_lifecycle import (
    create_execute_container,
    prepare_execute_task_context,
    prepare_resume_task_context,
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
    context = await prepare_resume_task_context(
        worker,
        db,
        task_id,
        container_name,
        settings=settings,
    )
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
