"""Container management API endpoints."""

import asyncio
import json
import logging
import re
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.task_operations import get_task_with_access_check
from app.config import get_settings
from app.core.docker_client import get_docker_client
from app.database import AsyncSessionLocal, get_db
from app.dependencies.auth import (
    get_optional_current_user,
    require_authenticated_user,
    require_page_access,
)
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access,
    require_project_access_scope,
)
from app.models import Issue, Task, TaskLog, TaskRawLogChunk, TaskStatus, User

logger = logging.getLogger(__name__)
router = APIRouter()

_CA_REPLACEMENT_LINE_RE = re.compile(r"^Replacing debian:[^\r\n]+\.pem\r?$")


def _compact_raw_log_noise(logs: str) -> str:
    """Collapse noisy certificate replacement chatter while preserving other raw output."""
    if "Replacing debian:" not in logs:
        return logs

    output_lines: list[str] = []
    suppressed_count = 0

    def flush_suppressed() -> None:
        nonlocal suppressed_count
        if suppressed_count:
            output_lines.append(f"[suppressed {suppressed_count} CA certificate replacement lines]")
            suppressed_count = 0

    for line in logs.splitlines():
        if _CA_REPLACEMENT_LINE_RE.match(line):
            suppressed_count += 1
            continue
        flush_suppressed()
        output_lines.append(line)

    flush_suppressed()
    compacted = "\n".join(output_lines)
    if logs.endswith("\n"):
        compacted += "\n"
    return compacted


def _get_container_pattern() -> re.Pattern:
    """Build container name regex using configured prefix."""
    prefix = re.escape(get_settings().worker_container_prefix)
    return re.compile(rf"^{prefix}-(\d+)-issue(\d+)$")


@router.get("/containers")
async def list_containers(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_page_access("monitor")),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """List running worker containers.

    Args:
        db: Database session

    Returns:
        List of container info
    """
    containers_info = []

    try:
        docker = get_docker_client()
        settings = get_settings()
        prefix = settings.worker_container_prefix
        pattern = _get_container_pattern()
        all_containers = await asyncio.to_thread(
            docker.client.containers.list,
            all=True,
            filters={"name": f"{prefix}-"},
        )

        for container in all_containers:
            if not pattern.match(container.name):
                continue

            # Extract task_id and issue_id from: {prefix}-{task_id}-issue{issue_id}
            task_id = None
            issue_id = None

            m = pattern.match(container.name)
            if m:
                task_id = int(m.group(1))
                issue_id = int(m.group(2))

            # Look up project_id from task for access control
            project_id = None
            if task_id is not None:
                result = await db.execute(
                    select(Task.issue_id).where(Task.id == task_id)
                )
                tid = result.scalar_one_or_none()
                if tid:
                    result2 = await db.execute(
                        select(Issue.project_id).where(Issue.id == tid)
                    )
                    project_id = result2.scalar_one_or_none()

            if (
                project_id is not None
                and not access_scope.is_unrestricted
                and project_id not in access_scope.accessible_project_ids
            ):
                continue

            containers_info.append({
                "id": container.id,
                "name": container.name,
                "status": container.status,
                "task_id": task_id,
                "issue_id": issue_id,
                "project_id": project_id,
                "created_at": container.attrs.get("Created", ""),
            })

    except Exception as e:
        logger.error(f"Failed to list containers: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list containers: {str(e)}",
        )

    return containers_info


@router.get("/containers/{container_id}/logs")
async def get_container_logs(
    container_id: str,
    _current_user=Depends(require_authenticated_user),
):
    """Stream container logs via SSE.

    Args:
        container_id: Container ID

    Returns:
        SSE stream of logs
    """
    async def generate_logs():
        try:
            docker = get_docker_client()

            # Try to find container by ID or name
            t_get = time.time()
            try:
                container = await asyncio.to_thread(docker.client.containers.get, container_id)
            except Exception:
                # Try by partial ID
                containers = await asyncio.to_thread(docker.client.containers.list, all=True)
                container = None
                for c in containers:
                    if c.id.startswith(container_id):
                        container = c
                        break

                if not container:
                    return  # Container is gone; close stream silently

            t_got = time.time()
            if t_got - t_get > 2.0:
                logger.warning(f"[SLOW SSE] docker.containers.get took {t_got-t_get:.3f}s for {container_id}")

            # Stream logs
            t_stream = time.time()
            logs = await asyncio.to_thread(
                container.logs,
                stdout=True,
                stderr=True,
                follow=True,
                tail=100,
                stream=True,
            )
            t_streamed = time.time()
            if t_streamed - t_stream > 2.0:
                logger.warning(f"[SLOW SSE] container.logs() setup took {t_streamed-t_stream:.3f}s for {container_id}")

            try:
                while True:
                    t_next = time.time()
                    line = await asyncio.to_thread(next, logs, None)
                    wait = time.time() - t_next
                    if wait > 5.0:
                        logger.info(f"[SSE] log line wait={wait:.1f}s (container idle) for {container_id}")
                    if line is None:
                        break
                    yield f"data: {line.decode('utf-8', errors='replace')}\n\n"
            except Exception:
                # Generator closed
                pass

        except Exception as e:
            logger.error(f"Error streaming logs: {e}")
            yield f"data: Error: {str(e)}\n\n"

    return StreamingResponse(
        generate_logs(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/tasks/{task_id}/raw-log-stream")
async def stream_task_raw_logs(
    task_id: int,
    since_sequence_no: int = 0,
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Stream persisted raw console-log chunks in sequence order."""
    async with AsyncSessionLocal() as init_db:
        result = await init_db.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    require_project_access(task.project_id, access_scope)

    terminal_statuses = {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }

    async def generate_raw_log_events():
        cursor = max(since_sequence_no, 0)
        batch_size = 100
        idle_cycles = 0

        while True:
            async with AsyncSessionLocal() as poll_db:
                chunk_result = await poll_db.execute(
                    select(TaskRawLogChunk)
                    .where(
                        TaskRawLogChunk.task_id == task_id,
                        TaskRawLogChunk.sequence_no > cursor,
                    )
                    .order_by(TaskRawLogChunk.sequence_no.asc())
                    .limit(batch_size)
                )
                chunks = chunk_result.scalars().all()
                current_status = None
                raw_logs_finalized_at = None
                if len(chunks) < batch_size:
                    status_result = await poll_db.execute(
                        select(Task.status, Task.raw_logs_finalized_at).where(Task.id == task_id)
                    )
                    status_row = status_result.one_or_none()
                    if status_row is not None:
                        current_status, raw_logs_finalized_at = status_row

            if chunks:
                payload = []
                for chunk in chunks:
                    cursor = chunk.sequence_no
                    payload.append(
                        {
                            "sequence_no": chunk.sequence_no,
                            "content": chunk.content.decode("utf-8", errors="replace"),
                        }
                    )
                yield f"event: batch\ndata: {json.dumps(payload)}\n\n"
                idle_cycles = 0
                if len(chunks) == batch_size:
                    continue
            else:
                idle_cycles += 1

            terminal_logs_ready = (
                current_status in terminal_statuses
                and (
                    current_status != TaskStatus.CANCELLED
                    or raw_logs_finalized_at is not None
                )
            )
            if terminal_logs_ready:
                yield "event: done\ndata: {}\n\n"
                break

            if idle_cycles and idle_cycles % 10 == 0:
                yield ": keepalive\n\n"
            await asyncio.sleep(1.5)

    return StreamingResponse(
        generate_raw_log_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/tasks/{task_id}/container-logs")
async def get_task_container_logs(
    task_id: int,
    source: str = "auto",
    db: AsyncSession = Depends(get_db),
    current_user: Optional["User"] = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Get container logs for a task (polling endpoint).

    Args:
        task_id: Task ID
        source: 'auto' (try Docker, fall back to DB) or 'db' (always use DB chunks)
        db: Database session

    Returns:
        Container logs
    """
    task = await get_task_with_access_check(
        task_id,
        db,
        access_scope,
        current_user,
        require_operator=False,
    )

    raw_logs_finalized = task.raw_logs_finalized_at is not None

    if not task.container_id:
        return {
            "container_id": None,
            "logs": "",
            "status": task.status,
            "raw_logs_finalized": raw_logs_finalized,
        }

    async def _fetch_db_chunks() -> tuple[str, int]:
        # New format: TaskRawLogChunk (written by the event archive system)
        chunk_result = await db.execute(
            select(TaskRawLogChunk)
            .where(TaskRawLogChunk.task_id == task_id)
            .order_by(TaskRawLogChunk.sequence_no.asc())
        )
        new_chunks = chunk_result.scalars().all()
        if new_chunks:
            return (
                "".join(c.content.decode("utf-8", errors="replace") for c in new_chunks),
                new_chunks[-1].sequence_no,
            )

        # Legacy fallback: TaskLog with log_type IS NULL (old tasks without event archive)
        log_result = await db.execute(
            select(TaskLog)
            .where(TaskLog.task_id == task_id, TaskLog.log_type.is_(None))
            .order_by(TaskLog.id.asc())
        )
        chunks = log_result.scalars().all()
        return "".join(c.message or "" for c in chunks), 0

    if source == "db":
        logs, last_sequence_no = await _fetch_db_chunks()
        return {
            "container_id": task.container_id,
            "logs": _compact_raw_log_noise(logs),
            "status": task.status,
            "source": "db",
            "last_sequence_no": last_sequence_no,
            "raw_logs_finalized": raw_logs_finalized,
        }

    try:
        docker = get_docker_client()
        container = await asyncio.to_thread(docker.client.containers.get, task.container_id)
        raw_logs = await asyncio.to_thread(container.logs, stdout=True, stderr=True, tail=200)
        logs = raw_logs.decode("utf-8", errors="replace")
        return {
            "container_id": task.container_id,
            "container_status": container.status,
            "logs": _compact_raw_log_noise(logs),
            "status": task.status,
            "raw_logs_finalized": raw_logs_finalized,
        }
    except Exception as e:
        # Container is gone (completed/removed) — fall back to DB-stored raw log chunks
        logs, last_sequence_no = await _fetch_db_chunks()
        if logs:
            return {
                "container_id": task.container_id,
                "logs": _compact_raw_log_noise(logs),
                "status": task.status,
                "source": "db",
                "last_sequence_no": last_sequence_no,
                "raw_logs_finalized": raw_logs_finalized,
            }
        logger.warning(f"Container gone and no DB chunks for task {task_id}: {e}")
        return {
            "container_id": task.container_id,
            "logs": "",
            "status": task.status,
            "raw_logs_finalized": raw_logs_finalized,
        }
