"""Task helper utilities for API responses and authorization."""

from typing import Any, Optional

from fastapi import HTTPException, status

from app.config import get_effective_settings
from app.models import Task, User


def _serialize_task(task: Task, project_metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Serialize a task row for API responses."""
    metadata = project_metadata or {}
    settings = get_effective_settings()
    project_path = metadata.get("project_path_with_namespace")
    project_url = f"{settings.gitlab_url.rstrip('/')}/{project_path}" if project_path else None
    return {
        "id": task.id,
        "issue_id": task.issue_id,
        "project_id": task.project_id,
        "project_name": metadata.get("project_name"),
        "project_path_with_namespace": metadata.get("project_path_with_namespace"),
        "project_url": project_url,
        "user_prompt": task.user_prompt,
        "initiator_user_id": task.initiator_user_id,
        "initiator_gitlab_user_id": task.initiator_gitlab_user_id,
        "initiator_username": task.initiator_username,
        "is_retry": task.is_retry,
        "retry_source_task_id": task.retry_source_task_id,
        "status": task.status.value,
        "priority": task.priority,
        "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
        "container_id": task.container_id,
        "container_name": (
            f"codify-{task.id}-issue{task.issue_id}"
            if task.container_id and task.issue_id
            else None
        ),
        "commit_sha": task.commit_sha,
        "error_message": task.error_message,
        "additions": task.additions,
        "deletions": task.deletions,
        "total_changes": task.total_changes,
        "input_tokens": task.input_tokens,
        "output_tokens": task.output_tokens,
        "model_name": task.model_name,
        "merge_request_title": task.merge_request_title,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


def _can_manage_task(task: Task, current_user: Optional[User]) -> bool:
    """Return whether the current user may operate on a task."""
    settings = get_effective_settings()
    if not settings.oidc_enabled:
        return True

    if current_user is None:
        return False

    if current_user.platform_role == "platform_admin":
        return True

    if task.initiator_user_id is not None and task.initiator_user_id == current_user.id:
        return True

    if (
        task.initiator_gitlab_user_id is not None
        and task.initiator_gitlab_user_id == current_user.gitlab_user_id
    ):
        return True

    return False


def _require_task_operator(task: Task, current_user: Optional[User]) -> None:
    """Ensure the current user may operate on a task."""
    if _can_manage_task(task, current_user):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You may only operate on your own tasks unless you are an admin",
    )
