"""Issue CRUD API endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_effective_settings
from app.database import get_db
from app.dependencies.auth import require_authenticated_user
from app.models import Issue, IssueStatus, Task, TaskStatus, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/issues", tags=["issues"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class CreateIssueRequest(BaseModel):
    """Request body for creating an issue."""

    title: str
    description: Optional[str] = None
    project_id: int
    base_branch: Optional[str] = None
    target_branch: Optional[str] = None


class UpdateIssueRequest(BaseModel):
    """Request body for updating an issue."""

    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_issue(issue: Issue, task_count: Optional[int] = None) -> dict:
    """Serialize an Issue row for API responses."""
    data = {
        "id": issue.id,
        "title": issue.title,
        "description": issue.description,
        "project_id": issue.project_id,
        "status": issue.status,
        "branch_name": issue.branch_name,
        "base_branch": issue.base_branch,
        "target_branch": issue.target_branch,
        "merge_request_iid": issue.merge_request_iid,
        "merge_request_url": issue.merge_request_url,
        "claude_session_id": issue.claude_session_id,
        "session_storage_path": issue.session_storage_path,
        "initiator_user_id": issue.initiator_user_id,
        "initiator_username": issue.initiator_username,
        "created_at": issue.created_at.isoformat(),
        "updated_at": issue.updated_at.isoformat(),
    }
    if task_count is not None:
        data["task_count"] = task_count
    return data


def _serialize_issue_detail(issue: Issue) -> dict:
    """Serialize an Issue with its eagerly-loaded tasks."""
    data = _serialize_issue(issue)
    data["tasks"] = [
        {
            "id": t.id,
            "user_prompt": t.user_prompt,
            "status": t.status.value if isinstance(t.status, TaskStatus) else t.status,
            "is_retry": t.is_retry,
            "retry_source_task_id": t.retry_source_task_id,
            "container_id": t.container_id,
            "commit_sha": t.commit_sha,
            "error_message": t.error_message,
            "additions": t.additions,
            "deletions": t.deletions,
            "total_changes": t.total_changes,
            "input_tokens": t.input_tokens,
            "output_tokens": t.output_tokens,
            "model_name": t.model_name,
            "merge_request_title": t.merge_request_title,
            "created_at": t.created_at.isoformat(),
            "updated_at": t.updated_at.isoformat(),
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        }
        for t in (issue.tasks or [])
    ]
    return data


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("")
async def create_issue(
    body: CreateIssueRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
):
    """Create a new issue."""
    issue = Issue(
        title=body.title,
        description=body.description,
        project_id=body.project_id,
        status=IssueStatus.OPEN.value,
        base_branch=body.base_branch,
        target_branch=body.target_branch,
        initiator_user_id=current_user.id if current_user else None,
        initiator_username=current_user.username if current_user else None,
    )
    db.add(issue)
    await db.flush()

    # Set derived fields that depend on the auto-generated id
    settings = get_effective_settings()
    issue.branch_name = f"codify/issue-{issue.id}"
    issue.session_storage_path = f"{settings.session_storage_root}/{issue.id}/claude"

    await db.commit()
    await db.refresh(issue)

    return _serialize_issue(issue)


@router.get("")
async def list_issues(
    status: Optional[str] = None,
    project_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
):
    """List issues with optional filtering and pagination."""
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    offset = (page - 1) * page_size

    # Build a subquery for task_count
    task_count_subq = (
        select(Task.issue_id, func.count(Task.id).label("task_count"))
        .group_by(Task.issue_id)
        .subquery()
    )

    query = (
        select(Issue, task_count_subq.c.task_count)
        .outerjoin(task_count_subq, Issue.id == task_count_subq.c.issue_id)
        .order_by(Issue.created_at.desc())
    )

    if status:
        try:
            IssueStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST
                if hasattr(status, "HTTP_400_BAD_REQUEST")
                else 400,
                detail=f"Invalid status: {status}",
            )
        query = query.where(Issue.status == status)

    if project_id is not None:
        query = query.where(Issue.project_id == project_id)

    # Total count
    count_q = select(func.count()).select_from(
        query.with_only_columns(Issue.id).subquery()
    )
    total = (await db.execute(count_q)).scalar() or 0

    result = await db.execute(query.limit(page_size).offset(offset))
    rows = result.all()

    items = [
        _serialize_issue(row[0], task_count=row[1] or 0)
        for row in rows
    ]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{issue_id}")
async def get_issue(
    issue_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
):
    """Get issue detail with tasks."""
    result = await db.execute(
        select(Issue)
        .where(Issue.id == issue_id)
        .options(selectinload(Issue.tasks))
    )
    issue = result.scalar_one_or_none()
    if issue is None:
        raise HTTPException(
            status_code=404,
            detail=f"Issue {issue_id} not found",
        )
    return _serialize_issue_detail(issue)


@router.patch("/{issue_id}")
async def update_issue(
    issue_id: int,
    body: UpdateIssueRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
):
    """Update an issue (title, description, status)."""
    result = await db.execute(select(Issue).where(Issue.id == issue_id))
    issue = result.scalar_one_or_none()
    if issue is None:
        raise HTTPException(
            status_code=404,
            detail=f"Issue {issue_id} not found",
        )

    if body.title is not None:
        issue.title = body.title
    if body.description is not None:
        issue.description = body.description
    if body.status is not None:
        try:
            IssueStatus(body.status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {body.status}. Must be one of: {[s.value for s in IssueStatus]}",
            )
        issue.status = body.status

    await db.commit()
    await db.refresh(issue)
    return _serialize_issue(issue)


@router.post("/{issue_id}/close")
async def close_issue(
    issue_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
):
    """Close an issue."""
    result = await db.execute(select(Issue).where(Issue.id == issue_id))
    issue = result.scalar_one_or_none()
    if issue is None:
        raise HTTPException(
            status_code=404,
            detail=f"Issue {issue_id} not found",
        )

    issue.status = IssueStatus.CLOSED.value
    await db.commit()
    await db.refresh(issue)
    return _serialize_issue(issue)


@router.delete("/{issue_id}")
async def delete_issue(
    issue_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
):
    """Delete an issue.

    Returns 409 if the issue has active tasks (pending, queued, or running).
    """
    result = await db.execute(select(Issue).where(Issue.id == issue_id))
    issue = result.scalar_one_or_none()
    if issue is None:
        raise HTTPException(
            status_code=404,
            detail=f"Issue {issue_id} not found",
        )

    # Check for active tasks
    active_statuses = [TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING]
    active_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.issue_id == issue_id,
            Task.status.in_(active_statuses),
        )
    )
    active_count = active_result.scalar() or 0

    if active_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete issue {issue_id}: {active_count} active task(s) remain",
        )

    await db.delete(issue)
    await db.commit()
    return {"status": "deleted", "id": issue_id}
