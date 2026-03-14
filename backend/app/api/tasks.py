"""Task management API endpoints."""

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, model_validator
from sqlalchemy import select, func, false
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.scheduling import resolve_scheduled_at
from app.database import get_db
from app.dependencies.auth import get_optional_current_user, require_page_access
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access,
    require_project_access_scope,
)
from app.models import Task, TaskLog, TaskStatus, User

logger = logging.getLogger(__name__)
router = APIRouter()


async def _build_project_lookup() -> dict[int, dict[str, str]]:
    """Build a project metadata lookup keyed by GitLab project ID."""
    from app.core.gitlab_client import get_gitlab_client

    try:
        gitlab = get_gitlab_client()
        projects = await asyncio.to_thread(gitlab.get_projects)
        return {
            project["id"]: {
                "project_name": project["name"],
                "project_path_with_namespace": project["path_with_namespace"],
            }
            for project in projects
        }
    except Exception as exc:
        logger.warning(f"Failed to load project metadata: {exc}")
        return {}


async def _get_project_metadata(project_id: int) -> dict[str, Optional[str]]:
    """Get project metadata for a single task response."""
    from app.core.gitlab_client import get_gitlab_client

    try:
        gitlab = get_gitlab_client()
        project = await asyncio.to_thread(gitlab.get_project, project_id)
        return {
            "project_name": getattr(project, "name", None),
            "project_path_with_namespace": getattr(project, "path_with_namespace", None),
        }
    except Exception as exc:
        logger.warning(f"Failed to load project {project_id} metadata: {exc}")
        return {
            "project_name": None,
            "project_path_with_namespace": None,
        }


def _serialize_task(task: Task, project_metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Serialize a task row for API responses."""
    metadata = project_metadata or {}
    settings = get_settings()
    project_path = metadata.get("project_path_with_namespace")
    project_url = f"{settings.gitlab_url.rstrip('/')}/{project_path}" if project_path else None
    issue_url = (
        f"{project_url}/-/issues/{task.issue_iid}"
        if project_url and task.issue_iid
        else None
    )
    branch_url = (
        f"{project_url}/-/tree/{quote(task.branch_name, safe='')}"
        if project_url and task.branch_name
        else None
    )
    target_branch_url = (
        f"{project_url}/-/tree/{quote(task.target_branch, safe='')}"
        if project_url and task.target_branch
        else None
    )
    return {
        "id": task.id,
        "project_id": task.project_id,
        "project_name": metadata.get("project_name"),
        "project_path_with_namespace": metadata.get("project_path_with_namespace"),
        "project_url": project_url,
        "issue_iid": task.issue_iid,
        "issue_url": issue_url,
        "issue_id": task.issue_id,
        "note_id": task.note_id,
        "user_prompt": task.user_prompt,
        "branch_name": task.branch_name,
        "branch_url": branch_url,
        "merge_request_iid": task.merge_request_iid,
        "merge_request_url": task.merge_request_url,
        "status": task.status.value,
        "priority": task.priority,
        "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
        "container_id": task.container_id,
        "target_branch": task.target_branch,
        "target_branch_url": target_branch_url,
        "commit_sha": task.commit_sha,
        "error_message": task.error_message,
        "additions": task.additions,
        "deletions": task.deletions,
        "total_changes": task.total_changes,
        "is_manual": task.is_manual,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


@router.get("/tasks")
async def list_tasks(
    status: Optional[str] = None,
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """List tasks with optional filtering.

    Args:
        status: Filter by task status
        project_id: Filter by project ID
        db: Database session

    Returns:
        List of tasks
    """
    query = select(Task).order_by(Task.created_at.desc())

    if status:
        try:
            task_status = TaskStatus(status)
            query = query.where(Task.status == task_status)
        except ValueError:
            pass

    if project_id:
        require_project_access(project_id, access_scope)
        query = query.where(Task.project_id == project_id)
    elif not access_scope.is_unrestricted:
        allowed_project_ids = access_scope.accessible_project_ids
        if not allowed_project_ids:
            query = query.where(false())
        else:
            query = query.where(Task.project_id.in_(allowed_project_ids))

    result = await db.execute(query.limit(100))
    tasks = result.scalars().all()
    project_lookup = await _build_project_lookup()

    return [
        _serialize_task(task, project_lookup.get(task.project_id))
        for task in tasks
    ]


@router.get("/tasks/scheduled")
async def list_scheduled_tasks(
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_page_access("schedule_overview")),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """List active scheduled tasks for queue analytics views."""
    query = (
        select(Task)
        .where(
            Task.scheduled_at.is_not(None),
            Task.status.in_([
                TaskStatus.PENDING,
                TaskStatus.QUEUED,
                TaskStatus.RUNNING,
            ]),
        )
        .order_by(Task.scheduled_at.asc(), Task.priority.desc(), Task.created_at.asc())
    )

    if project_id:
        require_project_access(project_id, access_scope)
        query = query.where(Task.project_id == project_id)
    elif not access_scope.is_unrestricted:
        allowed_project_ids = access_scope.accessible_project_ids
        if not allowed_project_ids:
            query = query.where(false())
        else:
            query = query.where(Task.project_id.in_(allowed_project_ids))

    result = await db.execute(query)
    tasks = result.scalars().all()
    project_lookup = await _build_project_lookup()

    return [
        _serialize_task(task, project_lookup.get(task.project_id))
        for task in tasks
    ]


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Get task by ID.

    Args:
        task_id: Task ID
        db: Database session

    Returns:
        Task details
    """
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    require_project_access(task.project_id, access_scope)

    return _serialize_task(task, await _get_project_metadata(task.project_id))


@router.get("/tasks/{task_id}/logs")
async def get_task_logs(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Get task logs.

    Args:
        task_id: Task ID
        db: Database session

    Returns:
        List of task log entries
    """
    # Check if task exists
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    require_project_access(task.project_id, access_scope)

    # Get logs
    result = await db.execute(
        select(TaskLog)
        .where(TaskLog.task_id == task_id)
        .order_by(TaskLog.created_at.asc())
    )
    logs = result.scalars().all()

    return [
        {
            "id": log.id,
            "task_id": log.task_id,
            "log_level": log.log_level,
            "message": log.message,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]


@router.get("/tasks/{task_id}/stats")
async def get_task_stats(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Get MR statistics for a task.

    Args:
        task_id: Task ID
        db: Database session

    Returns:
        MR change statistics (additions, deletions, total)
    """
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    require_project_access(task.project_id, access_scope)

    # Return database stats if available (non-zero)
    if task.additions > 0 or task.deletions > 0 or task.total_changes > 0:
        return {
            "additions": task.additions,
            "deletions": task.deletions,
            "total": task.total_changes,
        }

    # Fall back to GitLab API if no database stats
    if not task.merge_request_iid:
        return {"additions": 0, "deletions": 0, "total": 0}

    from app.core.gitlab_client import get_gitlab_client
    gitlab = get_gitlab_client()

    stats = await asyncio.to_thread(
        gitlab.get_merge_request_stats,
        task.project_id,
        task.merge_request_iid,
    )

    if not stats:
        return {"additions": 0, "deletions": 0, "total": 0}

    return stats


@router.patch("/tasks/{task_id}/stats")
async def update_task_stats(
    task_id: int,
    additions: int,
    deletions: int,
    total: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Update MR statistics for a task.

    Args:
        task_id: Task ID
        additions: Number of additions
        deletions: Number of deletions
        total: Total number of changes
        db: Database session

    Returns:
        Success message
    """
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    require_project_access(task.project_id, access_scope)

    task.additions = additions
    task.deletions = deletions
    task.total_changes = total
    await db.commit()

    logger.info(f"Task {task_id} stats updated: +{additions} -{deletions} ({total} total)")

    return {
        "status": "success",
        "message": f"Task {task_id} stats updated",
        "additions": additions,
        "deletions": deletions,
        "total": total,
    }


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Cancel a task.

    Args:
        task_id: Task ID
        db: Database session

    Returns:
        Success message
    """
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    require_project_access(task.project_id, access_scope)

    if task.status not in [TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel task with status {task.status.value}",
        )

    task.status = TaskStatus.CANCELLED
    task.completed_at = datetime.utcnow()
    task.error_message = "Cancelled by user"
    await db.commit()

    logger.info(f"Task {task_id} cancelled via API")

    return {"status": "success", "message": f"Task {task_id} cancelled"}


@router.post("/tasks/{task_id}/retry")
async def retry_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Retry a failed or cancelled task.

    Args:
        task_id: Task ID
        db: Database session

    Returns:
        Success message
    """
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    require_project_access(task.project_id, access_scope)

    if task.status not in [TaskStatus.FAILED, TaskStatus.CANCELLED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot retry task with status {task.status.value}",
        )

    task.status = TaskStatus.PENDING
    task.error_message = None
    task.completed_at = None
    task.started_at = None
    task.container_id = None
    task.commit_sha = None
    task.additions = 0
    task.deletions = 0
    task.total_changes = 0
    await db.commit()

    logger.info(f"Task {task_id} reset for retry")

    return {"status": "success", "message": f"Task {task_id} reset for retry"}


@router.post("/tasks/{task_id}/execute")
async def execute_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Trigger immediate execution of a pending task.

    Args:
        task_id: Task ID
        db: Database session

    Returns:
        Success message
    """
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    require_project_access(task.project_id, access_scope)

    if task.status != TaskStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task must be in PENDING status to execute immediately, current: {task.status.value}",
        )

    # Remove scheduled_at to execute immediately
    task.scheduled_at = None
    await db.commit()

    logger.info(f"Task {task_id} scheduled for immediate execution")

    return {"status": "success", "message": f"Task {task_id} scheduled for immediate execution"}


# Pydantic models for manual task creation
class CreateTaskRequest(BaseModel):
    """Request model for creating a manual task."""
    project_id: int
    branch_name: str
    target_branch: str = "main"
    user_prompt: str
    priority: int = 0
    delay_seconds: Optional[int] = None
    scheduled_datetime: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_distinct_branches(self) -> "CreateTaskRequest":
        """Manual tasks must use distinct source and target branches."""
        if self.branch_name == self.target_branch:
            raise ValueError("Source branch and target branch must be different for manual tasks")
        return self


@router.get("/projects")
async def list_projects(
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """List accessible GitLab projects.

    Returns:
        List of projects with id, name, and path
    """
    from app.core.gitlab_client import get_gitlab_client
    if not access_scope.is_unrestricted:
        return access_scope.accessible_projects
    gitlab = get_gitlab_client()
    projects = await asyncio.to_thread(gitlab.get_projects)
    return projects


@router.get("/projects/{project_id}/branches")
async def list_branches(
    project_id: int,
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """List branches for a GitLab project.

    Args:
        project_id: GitLab project ID

    Returns:
        List of branch names
    """
    from app.core.gitlab_client import get_gitlab_client
    require_project_access(project_id, access_scope)
    gitlab = get_gitlab_client()
    branches = await asyncio.to_thread(gitlab.get_branches, project_id)
    return branches


@router.post("/tasks")
async def create_task(
    request: CreateTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Create a new manual task.

    Args:
        request: Task creation request
        db: Database session

    Returns:
        Created task details
    """
    scheduled_at = resolve_scheduled_at(
        request.scheduled_datetime,
        request.delay_seconds,
    )
    require_project_access(request.project_id, access_scope)

    # Create task
    task = Task(
        project_id=request.project_id,
        user_prompt=request.user_prompt,
        initiator_user_id=current_user.id if current_user is not None else None,
        initiator_gitlab_user_id=current_user.gitlab_user_id if current_user is not None else None,
        initiator_username=current_user.username if current_user is not None else None,
        branch_name=request.branch_name,
        target_branch=request.target_branch,
        priority=request.priority,
        scheduled_at=scheduled_at,
        is_manual=True,
        # These are nullable for manual tasks
        issue_iid=None,
        issue_id=None,
        note_id=None,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    logger.info(
        f"Created manual task {task.id} for project {request.project_id}, "
        f"branch={request.branch_name}, target={request.target_branch}, "
        f"priority={request.priority}, delay={request.delay_seconds}"
    )

    return {
        "id": task.id,
        "project_id": task.project_id,
        "user_prompt": task.user_prompt,
        "branch_name": task.branch_name,
        "target_branch": task.target_branch,
        "status": task.status.value,
        "priority": task.priority,
        "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
        "is_manual": task.is_manual,
        "created_at": task.created_at.isoformat(),
    }
