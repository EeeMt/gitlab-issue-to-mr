"""Issue-scoped system data cleanup helpers."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings
from app.core.docker_client import get_docker_client_async
from app.core.utcnow import utcnow
from app.core.worker_docker_targets import (
    TaskContainerNotFoundError,
    find_task_container,
    list_known_docker_targets,
)
from app.core.worker_workspace_remote import remove_issue_workspace_remote
from app.models import (
    Issue,
    IssueExecutionLock,
    MattermostNotificationDelivery,
    Task,
    TaskIngestCursor,
    TaskLog,
    TaskPayload,
    TaskRawLogChunk,
    TaskRunArchive,
    TaskStatus,
    TaskUsageLedger,
    WebhookEvent,
)

ACTIVE_TASK_STATUS_VALUES = {
    TaskStatus.PENDING.value,
    TaskStatus.QUEUED.value,
    TaskStatus.RUNNING.value,
}


@dataclass(slots=True)
class SystemDataCleanupResult:
    deleted_issues: int = 0
    deleted_tasks: int = 0
    skipped_active_issues: int = 0
    skipped_active_tasks: int = 0
    deleted_archives: int = 0
    missing_archives: int = 0
    deleted_workspaces: int = 0
    container_cleanup_errors: list[dict[str, Any]] = field(default_factory=list)
    file_cleanup_errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deleted_issues": self.deleted_issues,
            "deleted_tasks": self.deleted_tasks,
            "skipped_active_issues": self.skipped_active_issues,
            "skipped_active_tasks": self.skipped_active_tasks,
            "deleted_archives": self.deleted_archives,
            "missing_archives": self.missing_archives,
            "deleted_workspaces": self.deleted_workspaces,
            "container_cleanup_errors": self.container_cleanup_errors,
            "file_cleanup_errors": self.file_cleanup_errors,
        }


def _status_value(status: TaskStatus | str) -> str:
    return status.value if isinstance(status, TaskStatus) else str(status)


def _container_name(task: Task, settings: Any) -> str:
    prefix = settings.worker_container_prefix
    return f"{prefix}-{task.id}-issue{task.issue_id}"


async def _remove_task_containers(
    db: AsyncSession,
    tasks: list[Task],
    result: SystemDataCleanupResult,
    settings: Any,
) -> set[int]:
    container_tasks = [
        task
        for task in tasks
        if _status_value(task.status) == TaskStatus.RUNNING.value or bool(task.container_id)
    ]
    if not container_tasks:
        return set()

    failed_task_ids: set[int] = set()
    known_targets = await list_known_docker_targets(db, settings, include_retained=True)
    for task in container_tasks:
        container_name = _container_name(task, settings)
        container_reference = task.container_id or container_name
        try:
            try:
                _docker, container, _connection = await find_task_container(
                    db,
                    task,
                    settings,
                    container_reference,
                    known_targets=known_targets,
                    get_client=get_docker_client_async,
                )
            except TaskContainerNotFoundError:
                continue
            stop_error: Exception | None = None
            if _status_value(task.status) == TaskStatus.RUNNING.value:
                try:
                    await asyncio.to_thread(container.stop, timeout=5)
                except Exception as exc:  # noqa: BLE001
                    stop_error = exc
            try:
                await asyncio.to_thread(container.remove, force=True, v=True)
            except Exception as exc:  # noqa: BLE001
                if stop_error is not None:
                    raise RuntimeError(
                        f"container stop failed ({stop_error}); force removal failed ({exc})"
                    ) from exc
                raise
        except Exception as exc:
            failed_task_ids.add(task.id)
            result.container_cleanup_errors.append(
                {
                    "task_id": task.id,
                    "container_name": container_name,
                    "error": str(exc),
                }
            )
    return failed_task_ids


def _cleanup_archive_files(paths: list[str], result: SystemDataCleanupResult) -> None:
    for archive_path in paths:
        if not archive_path or not os.path.exists(archive_path):
            result.missing_archives += 1
            continue
        try:
            os.remove(archive_path)
            result.deleted_archives += 1
        except Exception as exc:  # noqa: BLE001
            result.file_cleanup_errors.append(
                {
                    "kind": "archive",
                    "path": archive_path,
                    "error": str(exc),
                }
            )


async def cleanup_system_data(
    db: AsyncSession,
    *,
    older_than_days: int | None,
    force: bool,
    workspace_root: str,
    settings: Any | None = None,
    now: datetime | None = None,
) -> SystemDataCleanupResult:
    settings = settings or get_effective_settings()
    result = SystemDataCleanupResult()
    cutoff = None
    if older_than_days is not None:
        cutoff = (now or utcnow()) - timedelta(days=older_than_days)

    issue_stmt = select(Issue.id)
    if cutoff is not None:
        issue_stmt = issue_stmt.where(Issue.created_at < cutoff)
    candidate_issue_ids = list((await db.execute(issue_stmt)).scalars().all())
    if not candidate_issue_ids:
        return result

    for issue_id in candidate_issue_ids:
        issue = (
            await db.execute(
                select(Issue)
                .where(Issue.id == issue_id)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if issue is None:
            # Even an unsuccessful SELECT starts a transaction. Release it before
            # proceeding to another issue so a skipped row cannot keep a stale
            # snapshot or lock alive.
            await db.rollback()
            continue

        issue_tasks = list(
            (await db.execute(select(Task).where(Task.issue_id == issue.id)))
            .scalars()
            .all()
        )
        active_tasks = [
            task
            for task in issue_tasks
            if _status_value(task.status) in ACTIVE_TASK_STATUS_VALUES
            or bool(task.container_id)
        ]
        if active_tasks and not force:
            result.skipped_active_issues += 1
            result.skipped_active_tasks += len(active_tasks)
            await db.rollback()
            continue

        if force:
            failed_task_ids = await _remove_task_containers(db, issue_tasks, result, settings)
            if failed_task_ids:
                await db.rollback()
                continue

        workspace_deleted = False
        if workspace_root and issue.workspace_deleted_at is None:
            try:
                removed = await remove_issue_workspace_remote(db, settings, issue)
                if removed:
                    workspace_deleted = True
            except Exception as exc:  # noqa: BLE001
                issue.workspace_delete_attempted_at = utcnow()
                issue.workspace_delete_error = str(exc)[:4000]
                result.file_cleanup_errors.append(
                    {
                        "kind": "workspace",
                        "path": os.path.join(
                            workspace_root,
                            f"project-{issue.project_id}",
                            f"issue-{issue.id}",
                        ),
                        "error": str(exc),
                    }
                )
                await db.commit()
                continue

        task_ids = [task.id for task in issue_tasks]
        archive_paths: list[str] = []
        if task_ids:
            archives = list(
                (
                    await db.execute(
                        select(TaskRunArchive).where(TaskRunArchive.task_id.in_(task_ids))
                    )
                )
                .scalars()
                .all()
            )
            archive_paths = [archive.archive_path for archive in archives]

        await db.execute(delete(IssueExecutionLock).where(IssueExecutionLock.issue_id == issue.id))
        await db.execute(
            update(WebhookEvent).where(WebhookEvent.issue_id == issue.id).values(issue_id=None)
        )

        if task_ids:
            for model in (
                TaskLog,
                TaskPayload,
                TaskRawLogChunk,
                TaskIngestCursor,
                TaskRunArchive,
                TaskUsageLedger,
                MattermostNotificationDelivery,
            ):
                await db.execute(delete(model).where(model.task_id.in_(task_ids)))
            await db.execute(delete(Task).where(Task.id.in_(task_ids)))

        await db.execute(delete(Issue).where(Issue.id == issue.id))
        await db.commit()

        result.deleted_issues += 1
        result.deleted_tasks += len(task_ids)
        if workspace_deleted:
            result.deleted_workspaces += 1
        _cleanup_archive_files(archive_paths, result)

    return result
