"""Issue CRUD API endpoints."""

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import false, func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_effective_settings
from app.core.gitlab_client import get_gitlab_client
from app.core.task_helpers import _require_issue_operator
from app.core.utcnow import utcnow
from app.core.worker_profiles import get_default_provider, get_default_worker_profile
from app.core.worker_workspace import build_issue_workspace_paths
from app.database import get_db
from app.dependencies.auth import require_authenticated_user
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access,
    require_project_access_scope,
)
from app.models import AIProvider, Issue, IssueStatus, Task, TaskStatus, User, WorkerProfile

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/issues", tags=["issues"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class CreateIssueRequest(BaseModel):
    """Request body for creating an issue."""

    title: str
    description: str | None = None
    project_id: int
    base_branch: str | None = None
    target_branch: str | None = None
    delete_branch_on_close: bool = True
    ci_auto_repair_enabled: bool = False
    default_worker_profile_id: int | None = None
    default_provider_id: int | None = None


class UpdateIssueRequest(BaseModel):
    """Request body for updating an issue."""

    title: str | None = None
    description: str | None = None
    status: str | None = None
    ci_auto_repair_enabled: bool | None = None
    default_worker_profile_id: int | None = None
    default_provider_id: int | None = None


class CloseIssueRequest(BaseModel):
    """Request body for manually closing an issue."""

    branch_action: Literal["keep", "delete"] | None = None
    delete_branch: bool = False

    @property
    def should_delete_branch(self) -> bool:
        """Return whether a manual close explicitly requested branch deletion."""
        if self.branch_action is not None:
            return self.branch_action == "delete"
        return self.delete_branch is True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_issue(issue: Issue, task_count: int | None = None) -> dict:
    """Serialize an Issue row for API responses."""
    default_worker_profile = _loaded_issue_relationship(issue, "default_worker_profile")
    default_provider = _loaded_issue_relationship(issue, "default_provider")
    data = {
        "id": issue.id,
        "title": issue.title,
        "description": issue.description,
        "project_id": issue.project_id,
        "status": issue.status,
        "closed_via": issue.closed_via,
        "branch_name": issue.branch_name,
        "base_branch": issue.base_branch,
        "target_branch": issue.target_branch,
        "merge_request_iid": issue.merge_request_iid,
        "merge_request_url": issue.merge_request_url,
        "delete_branch_on_close": issue.delete_branch_on_close,
        "branch_deleted": issue.branch_deleted,
        "ci_auto_repair_enabled": issue.ci_auto_repair_enabled,
        "default_worker_profile_id": issue.default_worker_profile_id,
        "default_provider_id": issue.default_provider_id,
        "default_worker_profile_name": (
            default_worker_profile.name if default_worker_profile is not None else None
        ),
        "default_provider_name": default_provider.name if default_provider is not None else None,
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


def _loaded_issue_relationship(issue: Issue, name: str):
    try:
        insp = sa_inspect(issue)
        if name in insp.unloaded:
            return None
    except Exception:
        pass
    value = getattr(issue, name, None)
    if value.__class__.__module__.startswith("unittest.mock"):
        return None
    return value


async def _resolve_issue_default_worker_id(
    db: AsyncSession,
    explicit_id: int | None,
) -> int | None:
    if explicit_id is not None:
        profile = await db.get(WorkerProfile, explicit_id)
        if profile is None or not profile.enabled:
            raise HTTPException(status_code=422, detail="Default worker profile is not available")
        return profile.id
    profile = await get_default_worker_profile(db)
    return profile.id if profile else None


async def _resolve_issue_default_provider_id(
    db: AsyncSession,
    explicit_id: int | None,
) -> int | None:
    if explicit_id is not None:
        provider = await db.get(AIProvider, explicit_id)
        if provider is None or provider.is_disabled:
            raise HTTPException(status_code=422, detail="Default AI provider is not available")
        return provider.id
    provider = await get_default_provider(db)
    return provider.id if provider else None


def _task_duration_seconds(task: Task, now: datetime | None = None) -> float:
    """Return runtime seconds for one task, including currently running tasks."""
    if not task.started_at:
        return 0.0
    ended_at = task.completed_at or now or utcnow()
    if ended_at < task.started_at:
        return 0.0
    return (ended_at - task.started_at).total_seconds()


def _serialize_issue_detail(issue: Issue) -> dict:
    """Serialize an Issue with its eagerly-loaded tasks."""
    data = _serialize_issue(issue)
    tasks = issue.tasks or []
    data["tasks"] = [
        {
            "id": t.id,
            "user_prompt": t.user_prompt,
            "initiator_user_id": t.initiator_user_id,
            "initiator_gitlab_user_id": t.initiator_gitlab_user_id,
            "initiator_username": t.initiator_username,
            "status": t.status.value if isinstance(t.status, TaskStatus) else t.status,
            "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
            "is_retry": t.is_retry,
            "retry_source_task_id": t.retry_source_task_id,
            "trigger_source": t.trigger_source,
            "ci_failure_run_id": t.ci_failure_run_id,
            "container_id": t.container_id,
            "commit_sha": t.commit_sha,
            "error_message": t.error_message,
            "additions": t.additions,
            "deletions": t.deletions,
            "total_changes": t.total_changes,
            "input_tokens": t.input_tokens,
            "output_tokens": t.output_tokens,
            "model_name": t.model_name,
            "commit_message": t.commit_message,
            "created_at": t.created_at.isoformat(),
            "updated_at": t.updated_at.isoformat(),
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        }
        for t in tasks
    ]
    now = utcnow()
    data["totals"] = {
        "additions": sum(t.additions or 0 for t in tasks),
        "deletions": sum(t.deletions or 0 for t in tasks),
        "total_changes": sum(t.total_changes or 0 for t in tasks),
        "input_tokens": sum(t.input_tokens or 0 for t in tasks),
        "output_tokens": sum(t.output_tokens or 0 for t in tasks),
        "duration_seconds": sum(_task_duration_seconds(t, now) for t in tasks),
    }
    return data


async def _try_delete_issue_branch(
    issue: Issue,
    db: AsyncSession,
    *,
    ignore_close_policy: bool = False,
) -> None:
    """Attempt to delete the issue's GitLab branch. Silently handles all failures."""
    if not issue.branch_name:
        return
    if not ignore_close_policy and not issue.delete_branch_on_close:
        return
    try:
        client = get_gitlab_client()
        success = client.delete_branch(issue.project_id, issue.branch_name)
        if success:
            issue.branch_deleted = True
            await db.flush()
        else:
            logger.warning(
                f"Branch deletion failed for issue {issue.id} "
                f"(branch: {issue.branch_name}) — leaving branch_deleted=False"
            )
    except Exception as e:
        logger.warning(f"Unexpected error in _try_delete_issue_branch for issue {issue.id}: {e}")


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
    default_worker_profile_id = await _resolve_issue_default_worker_id(
        db,
        body.default_worker_profile_id,
    )
    default_provider_id = await _resolve_issue_default_provider_id(
        db,
        body.default_provider_id,
    )
    issue = Issue(
        title=body.title,
        description=body.description,
        project_id=body.project_id,
        status=IssueStatus.OPEN.value,
        base_branch=body.base_branch,
        target_branch=body.target_branch,
        delete_branch_on_close=body.delete_branch_on_close,
        ci_auto_repair_enabled=body.ci_auto_repair_enabled,
        default_worker_profile_id=default_worker_profile_id,
        default_provider_id=default_provider_id,
        initiator_user_id=current_user.id if current_user else None,
        initiator_username=current_user.username if current_user else None,
    )
    db.add(issue)
    await db.flush()

    # Set derived fields that depend on the auto-generated id
    settings = get_effective_settings()
    issue.branch_name = f"codify/issue-{issue.id}"
    workspace_paths = build_issue_workspace_paths(
        settings,
        issue,
        type("TaskPathSeed", (), {"id": 0})(),
    )
    issue.session_storage_path = (
        workspace_paths.claude_path
        if workspace_paths is not None
        else f"{settings.session_storage_root}/{issue.id}/claude"
    )

    await db.commit()
    await db.refresh(issue)

    return _serialize_issue(issue)


ISSUES_SORT_FIELDS = {
    "created_at",
    "status",
    "total_changes",
    "total_input_tokens",
    "total_output_tokens",
    "duration",
}
SORT_ORDERS = {"asc", "desc"}


@router.get("")
async def list_issues(
    status: str | None = None,
    project_id: str | None = None,
    initiator_user_id: int | None = None,
    initiator_username: str | None = None,
    has_mr: bool | None = None,
    search: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """List issues with optional filtering, sorting, and pagination."""
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    offset = (page - 1) * page_size

    # Validate sort params
    effective_sort_by = "created_at"
    effective_sort_order = "desc"
    if sort_by:
        if sort_by not in ISSUES_SORT_FIELDS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid sort_by: {sort_by}. Allowed: {', '.join(sorted(ISSUES_SORT_FIELDS))}",
            )
        effective_sort_by = sort_by
    if sort_order:
        if sort_order not in SORT_ORDERS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid sort_order: {sort_order}. Allowed: asc, desc",
            )
        effective_sort_order = sort_order

    duration_seconds_expr = func.coalesce(
        func.extract("epoch", Task.completed_at - Task.started_at),
        func.extract("epoch", func.now() - Task.started_at),
    )

    # Build a subquery for task_count and totals
    task_agg_subq = (
        select(
            Task.issue_id,
            func.count(Task.id).label("task_count"),
            func.coalesce(func.sum(Task.additions), 0).label("total_additions"),
            func.coalesce(func.sum(Task.deletions), 0).label("total_deletions"),
            func.coalesce(func.sum(Task.total_changes), 0).label("total_changes"),
            func.coalesce(func.sum(Task.input_tokens), 0).label("total_input_tokens"),
            func.coalesce(func.sum(Task.output_tokens), 0).label("total_output_tokens"),
            func.coalesce(func.sum(duration_seconds_expr), 0).label("duration_seconds"),
        )
        .group_by(Task.issue_id)
        .subquery()
    )

    # Determine sort column and direction
    agg_sort_columns = {
        "total_changes": task_agg_subq.c.total_changes,
        "total_input_tokens": task_agg_subq.c.total_input_tokens,
        "total_output_tokens": task_agg_subq.c.total_output_tokens,
        "duration": task_agg_subq.c.duration_seconds,
    }
    if effective_sort_by in agg_sort_columns:
        sort_column = func.coalesce(agg_sort_columns[effective_sort_by], 0)
    else:
        sort_column = getattr(Issue, effective_sort_by)
    order_clause = sort_column.asc() if effective_sort_order == "asc" else sort_column.desc()

    query = (
        select(
            Issue,
            task_agg_subq.c.task_count,
            task_agg_subq.c.total_additions,
            task_agg_subq.c.total_deletions,
            task_agg_subq.c.total_changes,
            task_agg_subq.c.total_input_tokens,
            task_agg_subq.c.total_output_tokens,
            task_agg_subq.c.duration_seconds,
        )
        .options(
            selectinload(Issue.default_worker_profile),
            selectinload(Issue.default_provider),
        )
        .outerjoin(task_agg_subq, Issue.id == task_agg_subq.c.issue_id)
        .order_by(order_clause)
    )

    # Multi-status filter (comma-separated)
    if status:
        status_parts = [s.strip() for s in status.split(",") if s.strip()]
        valid_statuses = []
        invalid_parts = []
        for part in status_parts:
            try:
                valid_statuses.append(IssueStatus(part))
            except ValueError:
                invalid_parts.append(part)
        if invalid_parts:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status value(s): {', '.join(invalid_parts)}. "
                       f"Allowed: {', '.join(s.value for s in IssueStatus)}",
            )
        if len(valid_statuses) == 1:
            query = query.where(Issue.status == valid_statuses[0])
        elif valid_statuses:
            query = query.where(Issue.status.in_(valid_statuses))

    # Project filter (comma-separated integers for multi-select)
    if project_id:
        project_ids = []
        for p in project_id.split(","):
            p = p.strip()
            if p:
                try:
                    project_ids.append(int(p))
                except ValueError:
                    pass
        if project_ids:
            if not access_scope.is_unrestricted:
                project_ids = [pid for pid in project_ids if pid in access_scope.accessible_project_ids]
            if len(project_ids) == 1:
                query = query.where(Issue.project_id == project_ids[0])
            elif project_ids:
                query = query.where(Issue.project_id.in_(project_ids))
            else:
                query = query.where(false())
        elif not access_scope.is_unrestricted:
            allowed_project_ids = access_scope.accessible_project_ids
            if not allowed_project_ids:
                query = query.where(false())
            else:
                query = query.where(Issue.project_id.in_(allowed_project_ids))
    elif not access_scope.is_unrestricted:
        allowed_project_ids = access_scope.accessible_project_ids
        if not allowed_project_ids:
            query = query.where(false())
        else:
            query = query.where(Issue.project_id.in_(allowed_project_ids))

    if initiator_user_id is not None:
        query = query.where(Issue.initiator_user_id == initiator_user_id)

    if initiator_username:
        usernames = [u.strip() for u in initiator_username.split(",") if u.strip()]
        if len(usernames) == 1:
            query = query.where(Issue.initiator_username == usernames[0])
        elif len(usernames) > 1:
            query = query.where(Issue.initiator_username.in_(usernames))

    # Has MR filter
    if has_mr is not None:
        if has_mr:
            query = query.where(Issue.merge_request_iid.is_not(None))
        else:
            query = query.where(Issue.merge_request_iid.is_(None))

    # Text search on title (min 2, max 200 chars)
    if search:
        if len(search) > 200:
            raise HTTPException(status_code=400, detail="search too long (max 200 characters)")
        if len(search) >= 2:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.where(Issue.title.ilike(f"%{escaped}%", escape="\\"))

    # Date range filters
    if created_after:
        try:
            dt = datetime.fromisoformat(created_after.replace("Z", "+00:00")).replace(tzinfo=None)
            query = query.where(Issue.created_at >= dt)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid created_after: {created_after}")
    if created_before:
        try:
            dt = datetime.fromisoformat(created_before.replace("Z", "+00:00")).replace(tzinfo=None)
            query = query.where(Issue.created_at <= dt)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid created_before: {created_before}")

    # Total count
    count_q = select(func.count()).select_from(
        query.with_only_columns(Issue.id).subquery()
    )
    total = (await db.execute(count_q)).scalar() or 0

    result = await db.execute(query.limit(page_size).offset(offset))
    rows = result.all()

    items = [
        {
            **_serialize_issue(row[0], task_count=row[1] or 0),
            "totals": {
                "additions": row[2] or 0,
                "deletions": row[3] or 0,
                "total_changes": row[4] or 0,
                "input_tokens": row[5] or 0,
                "output_tokens": row[6] or 0,
                "duration_seconds": float(row[7] or 0),
            },
        }
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
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Get issue detail with tasks."""
    result = await db.execute(
        select(Issue)
        .where(Issue.id == issue_id)
        .options(
            selectinload(Issue.tasks),
            selectinload(Issue.default_worker_profile),
            selectinload(Issue.default_provider),
        )
    )
    issue = result.scalar_one_or_none()
    if issue is None:
        raise HTTPException(
            status_code=404,
            detail=f"Issue {issue_id} not found",
        )
    require_project_access(issue.project_id, access_scope)
    return _serialize_issue_detail(issue)


@router.patch("/{issue_id}")
async def update_issue(
    issue_id: int,
    body: UpdateIssueRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
):
    """Update an issue (title, description, status)."""
    result = await db.execute(
        select(Issue)
        .where(Issue.id == issue_id)
        .options(
            selectinload(Issue.tasks),
            selectinload(Issue.default_worker_profile),
            selectinload(Issue.default_provider),
        )
    )
    issue = result.scalar_one_or_none()
    if issue is None:
        raise HTTPException(
            status_code=404,
            detail=f"Issue {issue_id} not found",
        )
    _require_issue_operator(issue, current_user)

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
    if body.ci_auto_repair_enabled is not None:
        issue.ci_auto_repair_enabled = body.ci_auto_repair_enabled
    if "default_worker_profile_id" in body.model_fields_set:
        issue.default_worker_profile_id = await _resolve_issue_default_worker_id(
            db,
            body.default_worker_profile_id,
        )
    if "default_provider_id" in body.model_fields_set:
        issue.default_provider_id = await _resolve_issue_default_provider_id(
            db,
            body.default_provider_id,
        )

    await db.commit()
    await db.refresh(issue, attribute_names=["tasks", "default_worker_profile", "default_provider"])
    return _serialize_issue_detail(issue)


@router.post("/{issue_id}/close")
async def close_issue(
    issue_id: int,
    body: CloseIssueRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
):
    """Close an issue."""
    result = await db.execute(
        select(Issue)
        .where(Issue.id == issue_id)
        .options(
            selectinload(Issue.tasks),
            selectinload(Issue.default_worker_profile),
            selectinload(Issue.default_provider),
        )
    )
    issue = result.scalar_one_or_none()
    if issue is None:
        raise HTTPException(
            status_code=404,
            detail=f"Issue {issue_id} not found",
        )
    _require_issue_operator(issue, current_user)

    issue.status = IssueStatus.CLOSED.value
    issue.closed_via = "manual"
    if body and body.should_delete_branch:
        await _try_delete_issue_branch(issue, db, ignore_close_policy=True)
    await db.commit()
    await db.refresh(issue, attribute_names=["tasks", "default_worker_profile", "default_provider"])
    return _serialize_issue_detail(issue)


@router.post("/{issue_id}/delete-branch")
async def delete_issue_branch(
    issue_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
):
    """Manually delete the GitLab branch associated with a closed issue."""
    result = await db.execute(
        select(Issue)
        .where(Issue.id == issue_id)
        .options(
            selectinload(Issue.tasks),
            selectinload(Issue.default_worker_profile),
            selectinload(Issue.default_provider),
        )
    )
    issue = result.scalar_one_or_none()
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    _require_issue_operator(issue, current_user)

    if issue.status != IssueStatus.CLOSED.value:
        raise HTTPException(
            status_code=400,
            detail="Issue must be closed before its branch can be deleted",
        )
    if not issue.branch_name:
        raise HTTPException(status_code=400, detail="Issue has no branch to delete")

    if issue.branch_deleted:
        # Already deleted: return the full serialized issue detail to match frontend expectations
        return _serialize_issue_detail(issue)

    try:
        client = get_gitlab_client()
        success = client.delete_branch(issue.project_id, issue.branch_name)
    except Exception as e:
        logger.warning(f"GitLab error deleting branch for issue {issue_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete branch in GitLab")

    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete branch in GitLab")

    issue.branch_deleted = True
    await db.commit()
    # Refresh tasks relationship (match pattern used by close_issue)
    await db.refresh(issue, attribute_names=["tasks", "default_worker_profile", "default_provider"])
    return _serialize_issue_detail(issue)


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
    _require_issue_operator(issue, current_user)

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
