"""Task workspace, runtime archive, and log payload helpers."""

import os
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, TaskPayload, TaskRunArchive


def build_task_workspace_status(
    task: Task,
    settings: Any,
    *,
    build_paths: Callable[..., Any],
    dir_exists: Callable[[str], bool] = os.path.isdir,
) -> dict[str, Any]:
    if not task.issue:
        return {"enabled": False, "reason": "task has no issue"}

    paths = build_paths(settings, task.issue, task)
    if paths is None:
        return {"enabled": False, "reason": "worker workspace host path is not configured"}

    return {
        "enabled": True,
        "issue_root": paths.issue_root,
        "repo_path": paths.repo_path,
        "runtime_path": paths.runtime_path,
        "repo_exists": dir_exists(paths.repo_path),
    }


def remove_task_workspace(
    task: Task,
    settings: Any,
    *,
    build_paths: Callable[..., Any],
    remove_workspace: Callable[[str], bool],
) -> dict[str, Any]:
    if not task.issue:
        raise HTTPException(
            status_code=404,
            detail="Workspace not available for task without issue",
        )

    paths = build_paths(settings, task.issue, task)
    if paths is None:
        raise HTTPException(
            status_code=404,
            detail="Worker workspace host path is not configured",
        )

    removed = remove_workspace(paths.issue_root)
    return {"removed": removed, "issue_root": paths.issue_root}


async def get_task_archive_metadata(
    db: AsyncSession,
    task_id: int,
    *,
    path_exists: Callable[[str], bool] = os.path.exists,
) -> dict[str, Any]:
    archive = (
        await db.execute(select(TaskRunArchive).where(TaskRunArchive.task_id == task_id))
    ).scalar_one_or_none()
    if not archive:
        raise HTTPException(status_code=404, detail="Archive not available")
    return {
        "archive_name": archive.archive_name,
        "archive_size_bytes": archive.archive_size_bytes,
        "created_at": archive.created_at.isoformat(),
        "file_exists": bool(archive.archive_path and path_exists(archive.archive_path)),
    }


async def get_task_archive_file(
    db: AsyncSession,
    task_id: int,
    *,
    path_exists: Callable[[str], bool] = os.path.exists,
) -> TaskRunArchive:
    archive = (
        await db.execute(select(TaskRunArchive).where(TaskRunArchive.task_id == task_id))
    ).scalar_one_or_none()
    if not archive:
        raise HTTPException(status_code=404, detail="Archive not available")
    if not archive.archive_path or not path_exists(archive.archive_path):
        raise HTTPException(status_code=404, detail="Archive file not found")
    return archive


async def get_task_payload_content(
    db: AsyncSession,
    task_id: int,
    payload_id: int,
) -> dict[str, Any]:
    payload = (
        await db.execute(
            select(TaskPayload).where(
                TaskPayload.task_id == task_id,
                TaskPayload.id == payload_id,
            )
        )
    ).scalar_one_or_none()
    if not payload:
        raise HTTPException(status_code=404, detail="Payload not found")
    return {
        "id": payload.id,
        "payload_kind": payload.payload_kind,
        "content": payload.content.decode("utf-8", errors="replace"),
        "encoding": payload.encoding,
        "char_count": payload.char_count,
        "byte_count": payload.byte_count,
    }
