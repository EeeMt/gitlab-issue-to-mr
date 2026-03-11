"""Container management API endpoints."""

import asyncio
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Task
from app.core.docker_client import get_docker_client

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()

WORKER_CONTAINER_PATTERN = re.compile(r"^gimr-\d+-p\d+-i\d+$")


@router.get("/containers")
async def list_containers(db: AsyncSession = Depends(get_db)):
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
            filters={"name": "gimr-"},
        )

        for container in all_containers:
            # Only show worker containers
            if not WORKER_CONTAINER_PATTERN.match(container.name):
                continue

            # Try to extract task_id from container name (format: gimr-{task_id}-p{project_id}-i{issue_iid})
            task_id = None
            project_id = None
            issue_iid = None

            try:
                parts = container.name.split("-")
                if len(parts) >= 5 and parts[0] == "gimr":
                    task_id = int(parts[1])
                    project_id = int(parts[2].replace("p", ""))
                    issue_iid = int(parts[3].replace("i", ""))
            except (ValueError, IndexError):
                pass

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
async def get_container_logs(container_id: str):
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
                    yield f"data: {('Container not found: ' + container_id)}\n\n"
                    return

            # Stream logs
            logs = await asyncio.to_thread(
                container.logs,
                stdout=True,
                stderr=True,
                follow=True,
                tail=100,
                stream=True,
            )

            try:
                while True:
                    line = await asyncio.to_thread(next, logs, None)
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
async def get_task_container_logs(task_id: int, db: AsyncSession = Depends(get_db)):
    """Get container logs for a task (polling endpoint).

    Args:
        task_id: Task ID
        db: Database session

    Returns:
        Container logs
    """
    # Get task to find container_id
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )

    if not task.container_id:
        return {
            "container_id": None,
            "logs": "",
            "status": task.status,
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
        logger.error(f"Error getting container logs: {e}")
        return {
            "container_id": task.container_id,
            "logs": f"Error: {str(e)}",
            "status": task.status,
            "error": str(e),
        }
