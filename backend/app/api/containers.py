"""Container management API endpoints."""

import asyncio
import logging
import re
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies.auth import require_admin_user, require_authenticated_user, require_page_access
from app.dependencies.auth import get_optional_current_user
from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
from app.models import Task, TaskLog, User
from app.core.docker_client import get_docker_client
from app.api.task_operations import get_task_with_access_check

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()

WORKER_CONTAINER_PATTERN = re.compile(r"^codify-\d+-p\d+-(i\d+|manual)$")


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
        all_containers = await asyncio.to_thread(
            docker.client.containers.list,
            all=True,
            filters={"name": "codify-"},
        )

        for container in all_containers:
            # Only show worker containers
            if not WORKER_CONTAINER_PATTERN.match(container.name):
                continue

            # Try to extract task_id from container name
            # Formats: codify-{task_id}-p{project_id}-i{issue_iid}
            #          codify-{task_id}-p{project_id}-manual
            task_id = None
            project_id = None
            issue_iid = None

            try:
                parts = container.name.split("-")
                if len(parts) >= 4 and parts[0] == "codify":
                    task_id = int(parts[1])
                    project_id = int(parts[2].replace("p", ""))
                    if parts[3].startswith("i"):
                        issue_iid = int(parts[3][1:])
                    # 'manual' suffix: issue_iid stays None
            except (ValueError, IndexError):
                pass

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
                "project_id": project_id,
                "issue_iid": issue_iid,
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
    task = await get_task_with_access_check(task_id, db, access_scope, current_user)

    if not task.container_id:
        return {
            "container_id": None,
            "logs": "",
            "status": task.status,
        }

    async def _fetch_db_chunks() -> str:
        log_result = await db.execute(
            select(TaskLog)
            .where(TaskLog.task_id == task_id, TaskLog.log_type.is_(None))
            .order_by(TaskLog.id.asc())
        )
        chunks = log_result.scalars().all()
        return "".join(c.message or "" for c in chunks)

    if source == "db":
        logs = await _fetch_db_chunks()
        return {
            "container_id": task.container_id,
            "logs": logs,
            "status": task.status,
            "source": "db",
        }

    try:
        docker = get_docker_client()
        container = await asyncio.to_thread(docker.client.containers.get, task.container_id)
        raw_logs = await asyncio.to_thread(container.logs, stdout=True, stderr=True, tail=200)
        logs = raw_logs.decode("utf-8", errors="replace")
        return {
            "container_id": task.container_id,
            "container_status": container.status,
            "logs": logs,
            "status": task.status,
        }
    except Exception as e:
        # Container is gone (completed/removed) — fall back to DB-stored raw log chunks
        logs = await _fetch_db_chunks()
        if logs:
            return {
                "container_id": task.container_id,
                "logs": logs,
                "status": task.status,
                "source": "db",
            }
        logger.warning(f"Container gone and no DB chunks for task {task_id}: {e}")
        return {
            "container_id": task.container_id,
            "logs": "",
            "status": task.status,
        }
