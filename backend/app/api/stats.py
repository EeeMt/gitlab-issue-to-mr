"""Statistics API endpoints."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, select, func, false, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.auth import get_optional_current_user, require_page_access
from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
from app.models import Task, TaskStatus, Issue, IssueStatus, User
from app.core.projects import build_project_lookup
from app.core.utcnow import utcnow

logger = logging.getLogger(__name__)
router = APIRouter()

FINISHED_TASK_STATUSES = (
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
)

ERROR_CATEGORY_PATTERNS = (
    ("Timeout", ("timeout", "timed out", "deadline exceeded")),
    ("Resource", ("out of memory", "oom", "no space left", "disk quota", "killed")),
    ("Docker", ("docker", "container", "image pull", "oci runtime")),
    ("Authentication", ("unauthorized", "forbidden", "authentication", "token", "permission denied")),
    ("Network", ("connection", "connect", "dns", "tls", "ssl", "socket", "proxy")),
    ("Git", ("merge conflict", "rebase", "checkout", "git ", "branch", "commit", "push failed")),
    (
        "Dependencies",
        ("module not found", "modulenotfounderror", "importerror", "pip ", "npm ", "package"),
    ),
    ("Tests", ("pytest", "test failed", "assertionerror", "failing test", "unit test", "integration test")),
    ("Code", ("syntaxerror", "indentationerror", "typeerror", "nameerror", "attributeerror", "traceback")),
)


@router.get("/stats")
async def get_stats(
    my: bool = Query(False, description="When true, scope to the current user's data only"),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Get task statistics.

    Returns:
        Statistics object
    """
    # Total count
    base_query = select(Task.id)
    if not access_scope.is_unrestricted:
        allowed_project_ids = access_scope.accessible_project_ids
        if not allowed_project_ids:
            base_query = base_query.where(false())
        else:
            base_query = base_query.where(Task.project_id.in_(allowed_project_ids))
    if my and current_user and current_user.username:
        base_query = base_query.where(Task.initiator_username == current_user.username)

    total_result = await db.execute(select(func.count()).select_from(base_query.subquery()))
    total = total_result.scalar() or 0

    # Count by status
    status_counts = {}
    for status_value in TaskStatus:
        result = await db.execute(
            select(func.count()).select_from(
                base_query.where(Task.status == status_value).subquery()
            )
        )
        status_counts[status_value.value] = result.scalar() or 0

    # Time-windowed counts for Monitor dashboard
    now = utcnow()
    cutoff_24h = now - timedelta(hours=24)

    completed_24h_result = await db.execute(
        select(func.count()).select_from(
            base_query.where(
                Task.status == TaskStatus.COMPLETED,
                Task.created_at >= cutoff_24h,
            ).subquery()
        )
    )
    completed_24h = completed_24h_result.scalar() or 0

    failed_cancelled_24h_result = await db.execute(
        select(func.count()).select_from(
            base_query.where(
                Task.status.in_([TaskStatus.FAILED, TaskStatus.CANCELLED]),
                Task.created_at >= cutoff_24h,
            ).subquery()
        )
    )
    failed_cancelled_24h = failed_cancelled_24h_result.scalar() or 0

    # Long-running: running tasks started more than 30 minutes ago
    cutoff_30min = now - timedelta(minutes=30)
    running_long_result = await db.execute(
        select(func.count()).select_from(
            base_query.where(
                Task.status == TaskStatus.RUNNING,
                Task.started_at.isnot(None),
                Task.started_at < cutoff_30min,
            ).subquery()
        )
    )
    running_long_30min = running_long_result.scalar() or 0

    # Issue statistics
    issue_base_query = select(Issue.id)
    if not access_scope.is_unrestricted:
        allowed_project_ids = access_scope.accessible_project_ids
        if not allowed_project_ids:
            issue_base_query = issue_base_query.where(false())
        else:
            issue_base_query = issue_base_query.where(Issue.project_id.in_(allowed_project_ids))
    if my and current_user:
        issue_base_query = issue_base_query.where(Issue.initiator_user_id == current_user.id)

    issue_total_result = await db.execute(
        select(func.count()).select_from(issue_base_query.subquery())
    )
    issue_total = issue_total_result.scalar() or 0

    issue_by_status = {}
    for status_val in IssueStatus:
        result = await db.execute(
            select(func.count()).select_from(
                issue_base_query.where(Issue.status == status_val).subquery()
            )
        )
        issue_by_status[status_val.value] = result.scalar() or 0

    return {
        "total": total,
        "pending": status_counts.get("pending", 0),
        "queued": status_counts.get("queued", 0),
        "running": status_counts.get("running", 0),
        "completed": status_counts.get("completed", 0),
        "failed": status_counts.get("failed", 0),
        "cancelled": status_counts.get("cancelled", 0),
        "completed_24h": completed_24h,
        "failed_cancelled_24h": failed_cancelled_24h,
        "running_long_30min": running_long_30min,
        "issues": {
            "total": issue_total,
            "by_status": issue_by_status,
        },
    }


def _apply_project_column_scope(query, project_column, access_scope: ProjectAccessScope):
    """Apply project-based access control to a query using the specified project column."""
    if access_scope.is_unrestricted:
        return query

    allowed_project_ids = access_scope.accessible_project_ids
    if not allowed_project_ids:
        return query.where(false())
    return query.where(project_column.in_(allowed_project_ids))


def _apply_project_scope(query, access_scope: ProjectAccessScope):
    """Apply project-based access control to a Task query."""
    return _apply_project_column_scope(query, Task.project_id, access_scope)


def _apply_analytics_filters(
    query,
    access_scope: ProjectAccessScope,
    project_id: Optional[int] = None,
    initiator_username: Optional[str] = None,
):
    query = _apply_project_scope(query, access_scope)
    if project_id is not None:
        query = query.where(Task.project_id == project_id)
    if initiator_username:
        query = query.where(Task.initiator_username == initiator_username)
    return query


def _apply_issue_analytics_filters(
    query,
    access_scope: ProjectAccessScope,
    project_id: Optional[int] = None,
    initiator_username: Optional[str] = None,
):
    query = _apply_project_column_scope(query, Issue.project_id, access_scope)
    if project_id is not None:
        query = query.where(Issue.project_id == project_id)
    if initiator_username:
        query = query.where(Issue.initiator_username == initiator_username)
    return query


def _build_status_breakdown_rows(statuses, raw_rows: list) -> list[dict]:
    counts_by_status: dict[str, int] = {}
    for row in raw_rows:
        status_value = getattr(row.status, "value", row.status)
        counts_by_status[str(status_value)] = int(row.count or 0)

    total = sum(counts_by_status.get(getattr(status, "value", status), 0) for status in statuses)
    rows: list[dict] = []
    for status in statuses:
        status_value = str(getattr(status, "value", status))
        count = counts_by_status.get(status_value, 0)
        rows.append(
            {
                "status": status_value,
                "count": count,
                "share": (count / total) if total else 0,
            }
        )
    return rows


def _build_error_breakdown(error_rows: list[tuple[str, int]], failed_tasks: int) -> list[dict]:
    grouped: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "count": 0,
            "sample_message": None,
            "sample_count": 0,
        }
    )

    for error_message, count in error_rows:
        category = _categorize_error_message(error_message)
        bucket = grouped[category]
        bucket["count"] = int(bucket["count"]) + int(count)
        if bucket["sample_message"] is None or int(count) > int(bucket["sample_count"]):
            bucket["sample_message"] = _summarize_error_message(error_message)
            bucket["sample_count"] = int(count)

    rows = []
    for category, values in grouped.items():
        count = int(values["count"])
        rows.append(
            {
                "category": category,
                "count": count,
                "share_of_failed": (count / failed_tasks) if failed_tasks else 0,
                "sample_message": values["sample_message"],
            }
        )

    rows.sort(key=lambda row: (-row["count"], row["category"]))
    return rows


def _categorize_error_message(error_message: str | None) -> str:
    if not error_message:
        return "Other"

    normalized = error_message.lower()
    for category, patterns in ERROR_CATEGORY_PATTERNS:
        if any(pattern in normalized for pattern in patterns):
            return category
    return "Other"


def _summarize_error_message(error_message: str | None) -> str | None:
    if not error_message:
        return None

    first_line = next((line.strip() for line in error_message.splitlines() if line.strip()), "")
    if not first_line:
        return None
    return first_line[:160]


@router.get("/stats/analytics")
async def get_analytics(
    days: int = Query(default=30, ge=7, le=90),
    project_id: Optional[int] = Query(default=None),
    initiator_username: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_page_access("analytics")),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Get analytics for recent tasks by project, initiator, and day."""
    if days not in {7, 30, 90}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="days must be one of: 7, 30, 90",
        )

    selected_initiator_username = initiator_username.strip() if initiator_username else None
    if selected_initiator_username == "":
        selected_initiator_username = None

    if project_id is not None and not access_scope.is_unrestricted:
        allowed_project_ids = set(access_scope.accessible_project_ids)
        if project_id not in allowed_project_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} is not available for analytics.",
            )

    now = utcnow()
    since = now - timedelta(days=days - 1)

    finished_task_expr = case((Task.status.in_(FINISHED_TASK_STATUSES), 1), else_=0)
    execution_seconds_expr = case(
        (
            Task.started_at.is_not(None) & Task.completed_at.is_not(None),
            func.extract("epoch", Task.completed_at - Task.started_at),
        ),
        else_=None,
    )
    queue_wait_seconds_expr = case(
        (
            Task.started_at.is_not(None),
            func.extract("epoch", Task.started_at - Task.created_at),
        ),
        else_=None,
    )
    token_total_expr = case(
        (
            Task.input_tokens.is_not(None) | Task.output_tokens.is_not(None),
            func.coalesce(Task.input_tokens, 0) + func.coalesce(Task.output_tokens, 0),
        ),
        else_=None,
    )
    token_tracked_expr = case(
        (Task.input_tokens.is_not(None) | Task.output_tokens.is_not(None), 1),
        else_=0,
    )

    summary_query = _apply_analytics_filters(
        select(
            func.count(Task.id),
            func.coalesce(func.sum(Task.additions), 0),
            func.coalesce(func.sum(Task.deletions), 0),
            func.coalesce(func.sum(Task.total_changes), 0),
            func.coalesce(func.sum(Task.input_tokens), 0),
            func.coalesce(func.sum(Task.output_tokens), 0),
            func.coalesce(func.sum(case((Task.status == TaskStatus.COMPLETED, 1), else_=0)), 0),
            func.coalesce(func.sum(case((Task.status == TaskStatus.FAILED, 1), else_=0)), 0),
            func.coalesce(func.sum(case((Task.status == TaskStatus.CANCELLED, 1), else_=0)), 0),
            func.coalesce(func.sum(finished_task_expr), 0),
            func.coalesce(func.sum(case((Task.initiator_username.is_not(None), 1), else_=0)), 0),
            func.coalesce(func.sum(token_tracked_expr), 0),
            func.min(case((Task.initiator_username.is_not(None), Task.created_at), else_=None)),
            func.avg(execution_seconds_expr),
            func.max(execution_seconds_expr),
            func.avg(queue_wait_seconds_expr),
            func.max(queue_wait_seconds_expr),
            func.avg(token_total_expr),
            func.max(token_total_expr),
        ).where(Task.created_at >= since),
        access_scope,
        project_id=project_id,
        initiator_username=selected_initiator_username,
    )
    summary_result = await db.execute(summary_query)
    (
        total_tasks,
        total_additions,
        total_deletions,
        total_changes,
        total_input_tokens,
        total_output_tokens,
        completed_tasks,
        failed_tasks,
        cancelled_tasks,
        finished_tasks,
        tracked_initiator_tasks,
        token_tracked_tasks,
        initiator_tracking_started_at,
        avg_execution_seconds,
        max_execution_seconds,
        avg_queue_wait_seconds,
        max_queue_wait_seconds,
        avg_total_tokens_per_tracked_task,
        max_total_tokens_per_tracked_task,
    ) = summary_result.one()

    project_query = (
        select(
            Task.project_id,
            func.count(Task.id).label("task_count"),
            func.coalesce(func.sum(case((Task.status == TaskStatus.COMPLETED, 1), else_=0)), 0).label(
                "completed_tasks"
            ),
            func.coalesce(func.sum(case((Task.status == TaskStatus.FAILED, 1), else_=0)), 0).label(
                "failed_tasks"
            ),
            func.coalesce(func.sum(case((Task.status == TaskStatus.CANCELLED, 1), else_=0)), 0).label(
                "cancelled_tasks"
            ),
            func.coalesce(func.sum(Task.additions), 0).label("additions"),
            func.coalesce(func.sum(Task.deletions), 0).label("deletions"),
            func.coalesce(func.sum(Task.total_changes), 0).label("total_changes"),
            func.coalesce(func.sum(Task.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(Task.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(func.coalesce(Task.input_tokens, 0) + func.coalesce(Task.output_tokens, 0)), 0).label(
                "total_tokens"
            ),
            func.avg(execution_seconds_expr).label("avg_execution_seconds"),
            func.avg(queue_wait_seconds_expr).label("avg_queue_wait_seconds"),
            func.max(Task.created_at).label("last_task_at"),
        )
        .where(Task.created_at >= since)
        .group_by(Task.project_id)
        .order_by(
            func.count(Task.id).desc(),
            func.coalesce(func.sum(Task.total_changes), 0).desc(),
            Task.project_id.asc(),
        )
    )
    project_query = _apply_analytics_filters(
        project_query,
        access_scope,
        project_id=project_id,
        initiator_username=selected_initiator_username,
    )
    project_rows = (await db.execute(project_query)).all()
    project_lookup = await build_project_lookup(
        accessible_projects=access_scope.accessible_projects,
        is_unrestricted=access_scope.is_unrestricted,
    )

    available_initiators_query = (
        select(
            Task.initiator_username,
            Task.initiator_gitlab_user_id,
            func.count(Task.id).label("task_count"),
        )
        .where(Task.created_at >= since, Task.initiator_username.is_not(None))
        .group_by(Task.initiator_username, Task.initiator_gitlab_user_id)
        .order_by(func.count(Task.id).desc(), Task.initiator_username.asc())
    )
    available_initiators_query = _apply_analytics_filters(
        available_initiators_query,
        access_scope,
        project_id=project_id,
    )
    available_initiator_rows = (await db.execute(available_initiators_query)).all()

    initiator_query = (
        select(
            Task.initiator_username,
            Task.initiator_gitlab_user_id,
            func.count(Task.id).label("task_count"),
            func.coalesce(func.sum(case((Task.status == TaskStatus.COMPLETED, 1), else_=0)), 0).label(
                "completed_tasks"
            ),
            func.coalesce(func.sum(case((Task.status == TaskStatus.FAILED, 1), else_=0)), 0).label(
                "failed_tasks"
            ),
            func.coalesce(func.sum(case((Task.status == TaskStatus.CANCELLED, 1), else_=0)), 0).label(
                "cancelled_tasks"
            ),
            func.coalesce(func.sum(Task.additions), 0).label("additions"),
            func.coalesce(func.sum(Task.deletions), 0).label("deletions"),
            func.coalesce(func.sum(Task.total_changes), 0).label("total_changes"),
            func.coalesce(func.sum(Task.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(Task.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(func.coalesce(Task.input_tokens, 0) + func.coalesce(Task.output_tokens, 0)), 0).label(
                "total_tokens"
            ),
            func.avg(execution_seconds_expr).label("avg_execution_seconds"),
            func.avg(queue_wait_seconds_expr).label("avg_queue_wait_seconds"),
            func.max(Task.created_at).label("last_task_at"),
        )
        .where(Task.created_at >= since, Task.initiator_username.is_not(None))
        .group_by(Task.initiator_username, Task.initiator_gitlab_user_id)
        .order_by(func.count(Task.id).desc(), func.coalesce(func.sum(Task.total_changes), 0).desc(), Task.initiator_username.asc())
    )
    initiator_query = _apply_analytics_filters(
        initiator_query,
        access_scope,
        project_id=project_id,
        initiator_username=selected_initiator_username,
    )
    initiator_rows = (await db.execute(initiator_query)).all()

    trend_query = (
        select(
            func.date(Task.created_at).label("day"),
            func.count(Task.id).label("task_count"),
            func.coalesce(func.sum(case((Task.status == TaskStatus.COMPLETED, 1), else_=0)), 0).label(
                "completed_tasks"
            ),
            func.coalesce(func.sum(case((Task.status == TaskStatus.FAILED, 1), else_=0)), 0).label(
                "failed_tasks"
            ),
            func.coalesce(func.sum(case((Task.status == TaskStatus.CANCELLED, 1), else_=0)), 0).label(
                "cancelled_tasks"
            ),
            func.coalesce(func.sum(Task.additions), 0).label("additions"),
            func.coalesce(func.sum(Task.deletions), 0).label("deletions"),
            func.coalesce(func.sum(Task.total_changes), 0).label("total_changes"),
            func.coalesce(func.sum(Task.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(Task.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(func.coalesce(Task.input_tokens, 0) + func.coalesce(Task.output_tokens, 0)), 0).label(
                "total_tokens"
            ),
            func.avg(execution_seconds_expr).label("avg_execution_seconds"),
        )
        .where(Task.created_at >= since)
        .group_by(func.date(Task.created_at))
        .order_by(func.date(Task.created_at).asc())
    )
    trend_query = _apply_analytics_filters(
        trend_query,
        access_scope,
        project_id=project_id,
        initiator_username=selected_initiator_username,
    )
    trend_rows = (await db.execute(trend_query)).all()
    trend_map = {str(row.day): row for row in trend_rows}

    priority_wait_query = (
        select(
            Task.priority,
            func.count(Task.id).label("task_count"),
            func.avg(queue_wait_seconds_expr).label("avg_queue_wait_seconds"),
            func.max(queue_wait_seconds_expr).label("max_queue_wait_seconds"),
        )
        .where(Task.created_at >= since, Task.started_at.is_not(None))
        .group_by(Task.priority)
        .order_by(Task.priority.asc())
    )
    priority_wait_query = _apply_analytics_filters(
        priority_wait_query,
        access_scope,
        project_id=project_id,
        initiator_username=selected_initiator_username,
    )
    priority_wait_rows = (await db.execute(priority_wait_query)).all()

    issue_status_query = (
        select(Issue.status.label("status"), func.count(Issue.id).label("count"))
        .where(Issue.created_at >= since)
        .group_by(Issue.status)
        .order_by(Issue.status.asc())
    )
    issue_status_query = _apply_issue_analytics_filters(
        issue_status_query,
        access_scope,
        project_id=project_id,
        initiator_username=selected_initiator_username,
    )
    issue_status_breakdown = _build_status_breakdown_rows(
        IssueStatus,
        (await db.execute(issue_status_query)).all(),
    )

    task_status_query = (
        select(Task.status.label("status"), func.count(Task.id).label("count"))
        .where(Task.created_at >= since)
        .group_by(Task.status)
        .order_by(Task.status.asc())
    )
    task_status_query = _apply_analytics_filters(
        task_status_query,
        access_scope,
        project_id=project_id,
        initiator_username=selected_initiator_username,
    )
    task_status_breakdown = _build_status_breakdown_rows(
        TaskStatus,
        (await db.execute(task_status_query)).all(),
    )

    error_query = (
        select(Task.error_message, func.count(Task.id).label("count"))
        .where(
            Task.created_at >= since,
            Task.status == TaskStatus.FAILED,
            Task.error_message.is_not(None),
        )
        .group_by(Task.error_message)
        .order_by(func.count(Task.id).desc(), Task.error_message.asc())
    )
    error_query = _apply_analytics_filters(
        error_query,
        access_scope,
        project_id=project_id,
        initiator_username=selected_initiator_username,
    )
    error_rows = [
        (str(row.error_message), int(row.count or 0))
        for row in (await db.execute(error_query)).all()
        if row.error_message
    ]
    error_breakdown = _build_error_breakdown(error_rows, int(failed_tasks or 0))

    trends: list[dict] = []
    for offset in range(days):
        day = since.date() + timedelta(days=offset)
        row = trend_map.get(day.isoformat())
        trends.append(
            {
                "date": day.isoformat(),
                "task_count": int(row.task_count) if row else 0,
                "completed_tasks": int(row.completed_tasks) if row else 0,
                "failed_tasks": int(row.failed_tasks) if row else 0,
                "cancelled_tasks": int(row.cancelled_tasks) if row else 0,
                "additions": int(row.additions) if row else 0,
                "deletions": int(row.deletions) if row else 0,
                "total_changes": int(row.total_changes) if row else 0,
                "input_tokens": int(row.input_tokens) if row else 0,
                "output_tokens": int(row.output_tokens) if row else 0,
                "total_tokens": int(row.total_tokens) if row else 0,
                "avg_execution_seconds": float(row.avg_execution_seconds) if row and row.avg_execution_seconds is not None else None,
            }
        )

    success_rate = (int(completed_tasks or 0) / int(finished_tasks or 0)) if finished_tasks else None
    failure_rate = (int(failed_tasks or 0) / int(finished_tasks or 0)) if finished_tasks else None

    return {
        "window_days": days,
        "generated_at": now.isoformat(),
        "summary": {
            "total_tasks": int(total_tasks or 0),
            "total_additions": int(total_additions or 0),
            "total_deletions": int(total_deletions or 0),
            "total_changes": int(total_changes or 0),
            "total_input_tokens": int(total_input_tokens or 0),
            "total_output_tokens": int(total_output_tokens or 0),
            "total_tokens": int(total_input_tokens or 0) + int(total_output_tokens or 0),
            "completed_tasks": int(completed_tasks or 0),
            "failed_tasks": int(failed_tasks or 0),
            "cancelled_tasks": int(cancelled_tasks or 0),
            "finished_tasks": int(finished_tasks or 0),
            "success_rate": success_rate,
            "failure_rate": failure_rate,
            "tracked_initiator_tasks": int(tracked_initiator_tasks or 0),
            "token_tracked_tasks": int(token_tracked_tasks or 0),
            "initiator_tracking_started_at": (
                initiator_tracking_started_at.isoformat() if initiator_tracking_started_at else None
            ),
            "avg_execution_seconds": float(avg_execution_seconds) if avg_execution_seconds is not None else None,
            "max_execution_seconds": float(max_execution_seconds) if max_execution_seconds is not None else None,
            "avg_queue_wait_seconds": float(avg_queue_wait_seconds) if avg_queue_wait_seconds is not None else None,
            "max_queue_wait_seconds": float(max_queue_wait_seconds) if max_queue_wait_seconds is not None else None,
            "avg_total_tokens_per_tracked_task": (
                float(avg_total_tokens_per_tracked_task)
                if avg_total_tokens_per_tracked_task is not None
                else None
            ),
            "max_total_tokens_per_tracked_task": (
                float(max_total_tokens_per_tracked_task)
                if max_total_tokens_per_tracked_task is not None
                else None
            ),
        },
        "available_initiators": [
            {
                "initiator_username": row.initiator_username,
                "initiator_gitlab_user_id": int(row.initiator_gitlab_user_id)
                if row.initiator_gitlab_user_id is not None
                else None,
                "task_count": int(row.task_count or 0),
            }
            for row in available_initiator_rows
        ],
        "projects": [
            {
                "project_id": int(row.project_id),
                "project_name": (project_lookup.get(int(row.project_id)) or {}).get("project_name")
                or f"Project {row.project_id}",
                "project_path_with_namespace": (project_lookup.get(int(row.project_id)) or {}).get(
                    "project_path_with_namespace"
                ),
                "task_count": int(row.task_count or 0),
                "completed_tasks": int(row.completed_tasks or 0),
                "failed_tasks": int(row.failed_tasks or 0),
                "cancelled_tasks": int(row.cancelled_tasks or 0),
                "success_rate": (
                    int(row.completed_tasks or 0)
                    / max(int(row.completed_tasks or 0) + int(row.failed_tasks or 0) + int(row.cancelled_tasks or 0), 1)
                )
                if (int(row.completed_tasks or 0) + int(row.failed_tasks or 0) + int(row.cancelled_tasks or 0)) > 0
                else None,
                "additions": int(row.additions or 0),
                "deletions": int(row.deletions or 0),
                "total_changes": int(row.total_changes or 0),
                "input_tokens": int(row.input_tokens or 0),
                "output_tokens": int(row.output_tokens or 0),
                "total_tokens": int(row.total_tokens or 0),
                "avg_execution_seconds": (
                    float(row.avg_execution_seconds) if row.avg_execution_seconds is not None else None
                ),
                "avg_queue_wait_seconds": (
                    float(row.avg_queue_wait_seconds) if row.avg_queue_wait_seconds is not None else None
                ),
                "last_task_at": row.last_task_at.isoformat() if row.last_task_at else None,
            }
            for row in project_rows
        ],
        "initiators": [
            {
                "initiator_username": row.initiator_username,
                "initiator_gitlab_user_id": int(row.initiator_gitlab_user_id)
                if row.initiator_gitlab_user_id is not None
                else None,
                "task_count": int(row.task_count or 0),
                "completed_tasks": int(row.completed_tasks or 0),
                "failed_tasks": int(row.failed_tasks or 0),
                "cancelled_tasks": int(row.cancelled_tasks or 0),
                "success_rate": (
                    int(row.completed_tasks or 0)
                    / max(int(row.completed_tasks or 0) + int(row.failed_tasks or 0) + int(row.cancelled_tasks or 0), 1)
                )
                if (int(row.completed_tasks or 0) + int(row.failed_tasks or 0) + int(row.cancelled_tasks or 0)) > 0
                else None,
                "additions": int(row.additions or 0),
                "deletions": int(row.deletions or 0),
                "total_changes": int(row.total_changes or 0),
                "input_tokens": int(row.input_tokens or 0),
                "output_tokens": int(row.output_tokens or 0),
                "total_tokens": int(row.total_tokens or 0),
                "avg_execution_seconds": (
                    float(row.avg_execution_seconds) if row.avg_execution_seconds is not None else None
                ),
                "avg_queue_wait_seconds": (
                    float(row.avg_queue_wait_seconds) if row.avg_queue_wait_seconds is not None else None
                ),
                "last_task_at": row.last_task_at.isoformat() if row.last_task_at else None,
            }
            for row in initiator_rows
        ],
        "trends": trends,
        "priority_waits": [
            {
                "priority": int(row.priority),
                "task_count": int(row.task_count or 0),
                "avg_queue_wait_seconds": (
                    float(row.avg_queue_wait_seconds) if row.avg_queue_wait_seconds is not None else None
                ),
                "max_queue_wait_seconds": (
                    float(row.max_queue_wait_seconds) if row.max_queue_wait_seconds is not None else None
                ),
            }
            for row in priority_wait_rows
        ],
        "issue_status_breakdown": issue_status_breakdown,
        "task_status_breakdown": task_status_breakdown,
        "error_breakdown": error_breakdown,
    }


@router.get("/stats/activity-heatmap")
async def get_activity_heatmap(
    days: int = Query(default=365, ge=1, le=730),
    my: bool = Query(False, description="When true, scope to the current user's data only"),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Return daily completed-task counts for the heatmap."""
    now = utcnow()
    since = now - timedelta(days=days)

    query = (
        select(
            func.date(Task.completed_at).label("date"),
            func.count().label("count"),
        )
        .where(Task.status == TaskStatus.COMPLETED)
        .where(Task.completed_at >= since)
        .group_by(func.date(Task.completed_at))
        .order_by(func.date(Task.completed_at))
    )

    if not access_scope.is_unrestricted:
        allowed_project_ids = access_scope.accessible_project_ids
        if not allowed_project_ids:
            return []
        query = query.where(Task.project_id.in_(allowed_project_ids))

    if my and current_user and current_user.username:
        query = query.where(Task.initiator_username == current_user.username)

    result = await db.execute(query)
    rows = result.all()

    return [{"date": str(row.date), "count": row.count} for row in rows]


@router.get("/stats/scheduled")
async def get_scheduled_stats(
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_page_access("schedule_overview")),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Get aggregated statistics for scheduled tasks.

    Returns summary counts and 24-hour hourly distribution without
    fetching individual task objects — designed for ScheduleOverview polling.
    """
    now = utcnow()
    now_hour = now.replace(minute=0, second=0, microsecond=0)
    next_24h = now + timedelta(hours=24)
    end_24h_bucket = now_hour + timedelta(hours=24)

    # Build shared WHERE conditions (avoiding subquery to preserve column refs)
    base_conditions = [
        Task.scheduled_at.isnot(None),
        Task.status.in_([TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING]),
    ]
    if not access_scope.is_unrestricted:
        allowed_project_ids = access_scope.accessible_project_ids
        if not allowed_project_ids:
            base_conditions.append(false())
        else:
            base_conditions.append(Task.project_id.in_(allowed_project_ids))
    if project_id is not None:
        base_conditions.append(Task.project_id == project_id)

    # Summary counts in a single query using conditional aggregation
    summary_q = select(
        func.count().label("total"),
        func.count(case((Task.scheduled_at <= now, 1))).label("ready_now"),
        func.count(
            case(((Task.scheduled_at > now) & (Task.scheduled_at <= next_24h), 1))
        ).label("next_24h"),
        func.count(case((Task.scheduled_at > next_24h, 1))).label("later"),
        func.count(case((Task.status == TaskStatus.QUEUED, 1))).label("queued_count"),
        func.count(case((Task.status == TaskStatus.RUNNING, 1))).label("running_count"),
    ).where(*base_conditions)

    summary_result = await db.execute(summary_q)
    s = summary_result.one()

    # Hourly distribution: count tasks bucketed by hour for next 24 hours
    # Use literal_column to embed 'hour' directly in SQL, avoiding separate
    # bind parameters that PostgreSQL can't match across SELECT/GROUP BY/ORDER BY
    hour_trunc = func.date_trunc(literal_column("'hour'"), Task.scheduled_at)
    hourly_q = (
        select(
            hour_trunc.label("hour_start"),
            func.count().label("count"),
        )
        .where(
            *base_conditions,
            Task.scheduled_at >= now_hour,
            Task.scheduled_at < end_24h_bucket,
        )
        .group_by(hour_trunc)
        .order_by(hour_trunc)
    )
    hourly_result = await db.execute(hourly_q)
    hourly_rows = hourly_result.all()

    # Build 24 buckets, filling in zeros for empty hours
    hourly_map = {row.hour_start: row.count for row in hourly_rows}
    hourly_distribution = []
    max_count = 0
    for i in range(24):
        bucket_start = now_hour + timedelta(hours=i)
        count = hourly_map.get(bucket_start, 0)
        if count > max_count:
            max_count = count
        hourly_distribution.append({
            "hour_start": bucket_start.isoformat(),
            "count": count,
        })

    # Find busiest hour
    busiest = max(hourly_distribution, key=lambda b: b["count"])

    return {
        "summary": {
            "total": s.total,
            "ready_now": s.ready_now,
            "next_24h": s.next_24h,
            "later": s.later,
            "queued_count": s.queued_count,
            "running_count": s.running_count,
            "busiest_hour_count": busiest["count"],
            "busiest_hour_label": busiest["hour_start"],
        },
        "hourly_distribution": hourly_distribution,
        "max_count": max_count,
    }
