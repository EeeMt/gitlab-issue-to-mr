"""Task and Issue helper utilities for API responses and authorization."""

import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings
from app.models import Issue, IssueStatus, Task, TaskStatus, User

logger = logging.getLogger(__name__)


def _serialize_task(
    task: Task,
    project_metadata: dict[str, Any] | None = None,
    settings: Any | None = None,
    *,
    include_prompt_details: bool = False,
) -> dict[str, Any]:
    """Serialize a task row for API responses.

    Pass ``settings`` from the caller when serializing multiple tasks in a loop
    to avoid recreating the Settings object for every task.
    """
    metadata = project_metadata or {}
    if settings is None:
        settings = get_effective_settings()
    project_path = metadata.get("project_path_with_namespace")
    project_url = f"{settings.gitlab_url.rstrip('/')}/{project_path}" if project_path else None
    session_mode = getattr(task, "session_mode", "continue")
    if session_mode not in {"continue", "fresh"}:
        session_mode = "continue"
    input_session_id = getattr(task, "input_session_id", None)
    if not isinstance(input_session_id, str):
        input_session_id = None
    output_session_id = getattr(task, "output_session_id", None)
    if not isinstance(output_session_id, str):
        output_session_id = None
    data = {
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
        "trigger_source": task.trigger_source,
        "ci_failure_run_id": task.ci_failure_run_id,
        "status": task.status.value,
        "priority": task.priority,
        "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
        "container_id": task.container_id,
        "container_name": (
            f"codify-{task.id}-issue{task.issue_id}"
            if task.container_id
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
        "commit_message": task.commit_message,
        "require_changes": task.require_changes,
        "task_mode": task.task_mode if task.task_mode else "execute",
        "session_mode": session_mode,
        "input_session_id": input_session_id,
        "output_session_id": output_session_id,
        "provider_id": task.provider_id,
        "provider_name": None,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "is_manually_overridden": task.is_manually_overridden,
        "override_reason": task.override_reason,
    }
    if include_prompt_details:
        data.update(
            {
                "run_instruction_template": task.run_instruction_template,
                "rendered_prompt": task.rendered_prompt,
                "rendered_prompt_at": (
                    task.rendered_prompt_at.isoformat() if task.rendered_prompt_at else None
                ),
            }
        )
    # Safely check if issue relationship is loaded (avoid lazy load / MissingGreenlet)
    issue = None
    try:
        insp = sa_inspect(task)
        if "issue" not in insp.unloaded:
            issue = task.issue
    except Exception:
        pass
    if issue is not None:
        data["issue"] = {
            "id": issue.id,
            "title": issue.title,
            "branch_name": issue.branch_name,
            "base_branch": issue.base_branch,
            "target_branch": issue.target_branch,
            "merge_request_iid": issue.merge_request_iid,
            "merge_request_url": issue.merge_request_url,
        }
    # Add provider name if loaded
    provider = None
    try:
        insp = sa_inspect(task)
        if "provider" not in insp.unloaded:
            provider = task.provider
    except Exception:
        pass
    if provider is not None:
        data["provider_name"] = provider.name
    return data


def _can_manage_task(task: Task, current_user: User | None) -> bool:
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


def _require_task_operator(task: Task, current_user: User | None) -> None:
    """Ensure the current user may operate on a task."""
    if _can_manage_task(task, current_user):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You may only operate on your own tasks unless you are an admin",
    )


def _can_manage_issue(issue: Issue, current_user: User | None) -> bool:
    """Return whether the current user may operate on an issue."""
    settings = get_effective_settings()
    if not settings.oidc_enabled:
        return True

    if current_user is None:
        return False

    if current_user.platform_role == "platform_admin":
        return True

    if issue.initiator_user_id is not None and issue.initiator_user_id == current_user.id:
        return True

    return False


def _require_issue_operator(issue: Issue, current_user: User | None) -> None:
    """Ensure the current user may operate on an issue."""
    if _can_manage_issue(issue, current_user):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You may only operate on your own issues unless you are an admin",
    )


async def maybe_update_issue_status(db: AsyncSession, issue_id: int) -> None:
    """Auto-transition issue status when no active tasks remain.

    - Has COMPLETED tasks → issue becomes COMPLETED
    - All tasks failed/cancelled → issue reverts to OPEN
    """
    try:
        active_count_result = await db.execute(
            select(func.count(Task.id)).where(
                Task.issue_id == issue_id,
                Task.status.in_([
                    TaskStatus.PENDING,
                    TaskStatus.QUEUED,
                    TaskStatus.RUNNING,
                ]),
            )
        )
        if active_count_result.scalar() > 0:
            return

        issue = await db.get(Issue, issue_id)
        if not issue or issue.status != IssueStatus.IN_PROGRESS.value:
            return

        completed_count_result = await db.execute(
            select(func.count(Task.id)).where(
                Task.issue_id == issue_id,
                Task.status == TaskStatus.COMPLETED,
                Task.task_mode != "plan",  # plan tasks do not constitute code delivery
            )
        )
        if completed_count_result.scalar() > 0:
            issue.status = IssueStatus.IN_REVIEW.value
            await db.commit()
            logger.info(f"Issue {issue_id} auto-transitioned to IN_REVIEW")
        else:
            issue.status = IssueStatus.OPEN.value
            await db.commit()
            logger.info(f"Issue {issue_id} auto-transitioned to OPEN (all tasks failed/cancelled)")
    except Exception as e:
        logger.warning(f"Failed to update issue {issue_id} status: {e}")
