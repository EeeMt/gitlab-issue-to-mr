"""Failure handling and notification helpers for worker task lifecycle."""

import asyncio
import logging
from typing import Any

from docker.errors import NotFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utcnow import utcnow
from app.core.worker_docker_targets import TaskContainerLookupError
from app.models import Issue, Task, TaskStatus

logger = logging.getLogger(__name__)

_QUIESCENT_CONTAINER_STATUSES = {"created", "exited", "dead", "removing"}


async def _quiesce_failed_container(container: Any, task_id: int) -> bool:
    """Ensure a failed task container cannot keep mutating its Issue workspace.

    Returns ``False`` when the daemon conclusively reports that the container no
    longer exists. An inconclusive Docker view is deliberately surfaced to the
    scheduler so it retains the Issue execution lock during deferred recovery.
    """
    try:
        await asyncio.to_thread(container.reload)
    except NotFound:
        return False
    except Exception as exc:  # noqa: BLE001
        raise TaskContainerLookupError(
            f"Could not inspect failed task {task_id} container"
        ) from exc

    if getattr(container, "status", None) in _QUIESCENT_CONTAINER_STATUSES:
        return True

    try:
        await asyncio.to_thread(container.stop, timeout=10)
    except NotFound:
        return False
    except Exception as stop_error:  # noqa: BLE001
        logger.warning(
            "Graceful stop failed for task %s after execution error: %s; forcing stop",
            task_id,
            stop_error,
        )
        try:
            await asyncio.to_thread(container.kill)
        except NotFound:
            return False
        except Exception as kill_error:  # noqa: BLE001
            raise TaskContainerLookupError(
                f"Could not stop failed task {task_id} container"
            ) from kill_error

    try:
        await asyncio.to_thread(container.reload)
    except NotFound:
        return False
    except Exception as exc:  # noqa: BLE001
        raise TaskContainerLookupError(
            f"Could not confirm failed task {task_id} container stopped"
        ) from exc
    if getattr(container, "status", None) not in _QUIESCENT_CONTAINER_STATUSES:
        raise TaskContainerLookupError(
            f"Failed task {task_id} container is not safely stopped "
            f"(status={getattr(container, 'status', None)})"
        )
    return True


async def fail_missing_parent_issue(db: AsyncSession, task: Task) -> bool:
    logger.error(f"[Task {task.id}] Parent issue {task.issue_id} not found; marking task FAILED")
    task.status = TaskStatus.FAILED
    task.error_message = f"Parent issue {task.issue_id} not found"
    task.completed_at = utcnow()
    task.raw_logs_finalized_at = getattr(task, "raw_logs_finalized_at", None) or utcnow()
    await db.commit()
    return False


async def fail_execute_task(
    worker,
    db: AsyncSession,
    task: Task,
    error: Exception,
    *,
    had_existing_mr: bool,
    issue: Issue | None = None,
    container: Any = None,
) -> bool:
    logger.error(f"[Task {task.id}] Task failed: {error}")
    container_exists = True
    if container is not None:
        # Do this before marking the task terminal. If Docker is unavailable or
        # the container cannot be stopped, the scheduler must keep the Issue lock
        # and hand ownership to deferred recovery instead of allowing overlapping
        # work against the same daemon-local repository.
        container_exists = await _quiesce_failed_container(container, task.id)

    had_completed_at = task.completed_at is not None
    task.status = TaskStatus.FAILED
    if task.completed_at is None:
        task.completed_at = utcnow()
    task.error_message = worker._sanitize_sensitive_data(str(error))[:1000]
    if container is None and getattr(task, "container_id", None) is None:
        task.raw_logs_finalized_at = getattr(task, "raw_logs_finalized_at", None) or utcnow()
    if had_completed_at:
        await worker._try_upsert_usage_ledger(db, task)
    await db.commit()

    if container is not None and not container_exists:
        task.raw_logs_finalized_at = getattr(task, "raw_logs_finalized_at", None) or utcnow()
        task.container_id = None
        await db.commit()
    elif container is not None and task.raw_logs_finalized_at is not None:
        try:
            worker.docker.remove_container(container, force=True)
        except Exception as cleanup_error:  # noqa: BLE001
            logger.warning(f"Failed to cleanup container: {cleanup_error}")
        else:
            task.container_id = None
            await db.commit()
    elif container is not None:
        logger.warning(
            "Retaining stopped container %s for failed task %s until raw logs are finalized",
            getattr(container, "id", "unknown"),
            task.id,
        )

    try:
        await worker._send_failure_notifications(
            task,
            success=False,
            had_existing_mr=had_existing_mr,
            issue=issue,
        )
    except Exception as notify_error:  # noqa: BLE001
        logger.warning(f"Failed to send failure notifications: {notify_error}")

    return False


async def fail_resume_missing_container(
    db: AsyncSession,
    task: Task,
    error: Exception,
) -> bool:
    logger.error(
        f"[Task {task.id}] Container disappeared during resume; marking task FAILED: {error}"
    )
    task.status = TaskStatus.FAILED
    task.error_message = f"Container disappeared during resume: {error}"
    task.container_id = None
    task.completed_at = utcnow()
    task.raw_logs_finalized_at = getattr(task, "raw_logs_finalized_at", None) or utcnow()
    await db.commit()
    return False


async def fail_resume_task(
    worker,
    db: AsyncSession,
    task_id: int,
    task: Task,
    container: Any,
    error: Exception,
    *,
    had_existing_mr: bool,
    issue: Issue | None = None,
) -> bool:
    logger.exception(f"[Task {task_id}] Resume failed with exception: {error}")
    container_exists = await _quiesce_failed_container(container, task_id)
    had_completed_at = task.completed_at is not None
    task.status = TaskStatus.FAILED
    if task.completed_at is None:
        task.completed_at = utcnow()
    task.error_message = worker._sanitize_sensitive_data(str(error))[:1000]
    if had_completed_at:
        await worker._try_upsert_usage_ledger(db, task)
    await db.commit()

    if not container_exists:
        task.raw_logs_finalized_at = getattr(task, "raw_logs_finalized_at", None) or utcnow()
        task.container_id = None
        await db.commit()
    elif task.raw_logs_finalized_at is not None:
        try:
            worker.docker.remove_container(container, force=True)
        except Exception as cleanup_error:  # noqa: BLE001
            logger.warning(f"[Task {task_id}] Resume: failed to cleanup container: {cleanup_error}")
        else:
            task.container_id = None
            await db.commit()
    else:
        logger.warning(
            "Retaining stopped container %s for failed resumed task %s until raw logs "
            "are finalized",
            getattr(container, "id", "unknown"),
            task_id,
        )

    try:
        await worker._send_failure_alert(task, issue)
    except Exception as notify_error:  # noqa: BLE001
        logger.warning(f"[Task {task_id}] Resume: failed to send failure alert: {notify_error}")

    return False


async def send_failure_alert(
    worker,
    task: Task,
    issue: Issue | None = None,
    *,
    get_settings_fn,
    get_ssl_verify_fn,
    httpx_async_client_cls,
) -> None:
    settings = get_settings_fn()
    if not settings.alert_on_failure or not settings.alert_webhook_url:
        return

    error_msg = task.error_message[:500] if task.error_message else "Unknown error"
    error_msg = worker._sanitize_sensitive_data(error_msg)
    alert_data = {
        "text": "🚨 Task Failed",
        "attachments": [
            {
                "color": "danger",
                "fields": [
                    {"title": "Task ID", "value": str(task.id), "short": True},
                    {"title": "Project ID", "value": str(task.project_id), "short": True},
                    {"title": "Issue", "value": f"#{issue.id}" if issue else "N/A", "short": True},
                    {"title": "Error", "value": error_msg},
                ],
            }
        ],
    }

    try:
        async with httpx_async_client_cls(
            timeout=10.0,
            verify=get_ssl_verify_fn(settings),
        ) as client:
            response = await client.post(settings.alert_webhook_url, json=alert_data)
        if response.status_code < 400:
            logger.info(f"Sent failure alert for task {task.id}")
        else:
            logger.warning(f"Failed to send failure alert: {response.status_code}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to send failure alert: {exc}")


async def send_success_notifications(
    worker,
    task: Task,
    *,
    had_existing_mr: bool,
    issue: Issue | None = None,
    notify_task_event_fn=None,
    completion_event=None,
    session_factory=None,
) -> None:
    try:
        await notify_task_event_fn(
            task,
            completion_event,
            session_factory=session_factory,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to send Mattermost completion notification: {exc}")


async def send_failure_notifications(
    worker,
    task: Task,
    *,
    had_existing_mr: bool,
    issue: Issue | None = None,
    notify_task_event_fn=None,
    retry_scheduled_event=None,
    failed_event=None,
    session_factory=None,
) -> None:
    try:
        await worker._send_failure_alert(task, issue)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to send failure alert: {exc}")

    try:
        if task.status == TaskStatus.PENDING:
            await notify_task_event_fn(
                task,
                retry_scheduled_event,
                context={
                    "previous_scheduled_at": task.scheduled_at,
                    "scheduled_at": task.scheduled_at,
                },
                session_factory=session_factory,
            )
        else:
            await notify_task_event_fn(
                task,
                failed_event,
                session_factory=session_factory,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to send Mattermost failure notification: {exc}")
