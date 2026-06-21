"""Issue-scoped system data cleanup helpers."""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.docker_client import get_docker_client
from app.core.utcnow import utcnow
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


def _issue_workspace_path(workspace_root: str, *, project_id: int, issue_id: int) -> str:
    return os.path.join(workspace_root, f"project-{project_id}", f"issue-{issue_id}")


def _container_name(task: Task) -> str:
    return f"codify-{task.id}-issue{task.issue_id}"


async def _stop_running_containers(
    tasks: list[Task],
    result: SystemDataCleanupResult,
) -> None:
    running_tasks = [
        task for task in tasks
        if _status_value(task.status) == TaskStatus.RUNNING.value
    ]
    if not running_tasks:
        return

    try:
        docker = get_docker_client()
    except Exception as exc:
        for task in running_tasks:
            result.container_cleanup_errors.append({
                "task_id": task.id,
                "container_name": _container_name(task),
                "error": str(exc),
            })
        return

    for task in running_tasks:
        container_name = _container_name(task)
        try:
            container = await asyncio.to_thread(docker.client.containers.get, container_name)
            await asyncio.to_thread(container.stop, timeout=5)
        except Exception as exc:
            result.container_cleanup_errors.append({
                "task_id": task.id,
                "container_name": container_name,
                "error": str(exc),
            })


def _cleanup_archive_files(paths: list[str], result: SystemDataCleanupResult) -> None:
    for archive_path in paths:
        if not archive_path or not os.path.exists(archive_path):
            result.missing_archives += 1
            continue
        try:
            os.remove(archive_path)
            result.deleted_archives += 1
        except Exception as exc:  # noqa: BLE001
            result.file_cleanup_errors.append({
                "kind": "archive",
                "path": archive_path,
                "error": str(exc),
            })


def _cleanup_workspaces(paths: list[str], result: SystemDataCleanupResult) -> None:
    for workspace_path in paths:
        if not workspace_path or not os.path.exists(workspace_path):
            continue
        try:
            shutil.rmtree(workspace_path)
            result.deleted_workspaces += 1
        except Exception as exc:  # noqa: BLE001
            result.file_cleanup_errors.append({
                "kind": "workspace",
                "path": workspace_path,
                "error": str(exc),
            })


async def cleanup_system_data(
    db: AsyncSession,
    *,
    older_than_days: int | None,
    force: bool,
    workspace_root: str,
    now: datetime | None = None,
) -> SystemDataCleanupResult:
    result = SystemDataCleanupResult()
    cutoff = None
    if older_than_days is not None:
        cutoff = (now or utcnow()) - timedelta(days=older_than_days)

    issue_stmt = select(Issue)
    if cutoff is not None:
        issue_stmt = issue_stmt.where(Issue.created_at < cutoff)
    issues = list((await db.execute(issue_stmt)).scalars().all())
    if not issues:
        return result

    issue_ids = [issue.id for issue in issues]
    task_result = await db.execute(select(Task).where(Task.issue_id.in_(issue_ids)))
    tasks = list(task_result.scalars().all())
    tasks_by_issue: dict[int, list[Task]] = {}
    for task in tasks:
        tasks_by_issue.setdefault(task.issue_id, []).append(task)

    selected_issues: list[Issue] = []
    for issue in issues:
        issue_tasks = tasks_by_issue.get(issue.id, [])
        active_tasks = [
            task
            for task in issue_tasks
            if _status_value(task.status) in ACTIVE_TASK_STATUS_VALUES
        ]
        if active_tasks and not force:
            result.skipped_active_issues += 1
            result.skipped_active_tasks += len(active_tasks)
            continue
        selected_issues.append(issue)

    if not selected_issues:
        return result

    selected_issue_ids = [issue.id for issue in selected_issues]
    selected_tasks = [
        task for task in tasks
        if task.issue_id in selected_issue_ids
    ]
    selected_task_ids = [task.id for task in selected_tasks]
    result.deleted_issues = len(selected_issue_ids)
    result.deleted_tasks = len(selected_task_ids)

    if force:
        await _stop_running_containers(selected_tasks, result)

    archive_paths: list[str] = []
    if selected_task_ids:
        archives = list((
            await db.execute(
                select(TaskRunArchive).where(TaskRunArchive.task_id.in_(selected_task_ids))
            )
        ).scalars().all())
        archive_paths = [archive.archive_path for archive in archives]

    workspace_paths: list[str] = []
    if workspace_root:
        workspace_paths = [
            _issue_workspace_path(
                workspace_root,
                project_id=issue.project_id,
                issue_id=issue.id,
            )
            for issue in selected_issues
        ]

    await db.execute(
        delete(IssueExecutionLock).where(IssueExecutionLock.issue_id.in_(selected_issue_ids))
    )
    await db.execute(
        update(WebhookEvent)
        .where(WebhookEvent.issue_id.in_(selected_issue_ids))
        .values(issue_id=None)
    )

    if selected_task_ids:
        for model in (
            TaskLog,
            TaskPayload,
            TaskRawLogChunk,
            TaskIngestCursor,
            TaskRunArchive,
            TaskUsageLedger,
            MattermostNotificationDelivery,
        ):
            await db.execute(delete(model).where(model.task_id.in_(selected_task_ids)))
        await db.execute(delete(Task).where(Task.id.in_(selected_task_ids)))

    await db.execute(delete(Issue).where(Issue.id.in_(selected_issue_ids)))
    await db.commit()

    _cleanup_archive_files(archive_paths, result)
    _cleanup_workspaces(workspace_paths, result)
    return result
