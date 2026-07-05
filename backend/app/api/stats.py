"""Statistics API endpoints."""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, false, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics_queries import (
    apply_analytics_filters as _apply_analytics_filters,
)
from app.api.analytics_queries import (
    apply_issue_analytics_filters as _apply_issue_analytics_filters,
)
from app.api.analytics_queries import (
    apply_project_column_scope as _apply_project_column_scope,
)
from app.api.analytics_queries import apply_project_scope as _apply_project_scope
from app.api.analytics_queries import build_analytics_queries
from app.api.analytics_responses import AnalyticsSummary, build_analytics_response
from app.api.analytics_responses import (
    build_error_breakdown as _build_error_breakdown,
)
from app.api.analytics_responses import (
    build_provider_chart_series as _build_provider_chart_series,
)
from app.api.analytics_responses import (
    build_status_breakdown_rows as _build_status_breakdown_rows,
)
from app.api.analytics_responses import (
    categorize_error_message as _categorize_error_message,
)
from app.api.analytics_responses import safe_ratio as _safe_ratio
from app.api.analytics_responses import (
    summarize_error_message as _summarize_error_message,
)
from app.config import get_effective_settings
from app.core.projects import build_project_lookup
from app.core.utcnow import utcnow
from app.database import get_db
from app.dependencies.auth import get_optional_current_user, require_page_access
from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
from app.models import Issue, IssueStatus, Task, TaskStatus, User

logger = logging.getLogger(__name__)
router = APIRouter()

__all__ = [
    "_apply_analytics_filters",
    "_apply_issue_analytics_filters",
    "_apply_project_column_scope",
    "_apply_project_scope",
    "_build_error_breakdown",
    "_build_provider_chart_series",
    "_build_status_breakdown_rows",
    "_categorize_error_message",
    "_safe_ratio",
    "_summarize_error_message",
]

@router.get("/stats")
async def get_stats(
    my: bool = Query(False, description="When true, scope to the current user's data only"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
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


@router.get("/stats/analytics")
async def get_analytics(
    days: int = Query(default=30, ge=7, le=90),
    project_id: int | None = Query(default=None),
    initiator_username: str | None = Query(default=None),
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

    queries = build_analytics_queries(
        since=since,
        access_scope=access_scope,
        project_id=project_id,
        initiator_username=selected_initiator_username,
    )
    summary = AnalyticsSummary.from_row((await db.execute(queries.summary)).one())

    project_rows = (await db.execute(queries.projects)).all()
    project_lookup = await build_project_lookup(
        accessible_projects=access_scope.accessible_projects,
        is_unrestricted=access_scope.is_unrestricted,
    )

    available_initiator_rows = (await db.execute(queries.available_initiators)).all()
    initiator_rows = (await db.execute(queries.initiators)).all()

    trend_rows = (await db.execute(queries.trends)).all()
    priority_wait_rows = (await db.execute(queries.priority_waits)).all()
    issue_status_rows = (await db.execute(queries.issue_statuses)).all()
    task_status_rows = (await db.execute(queries.task_statuses)).all()
    error_rows = (await db.execute(queries.errors)).all()
    provider_rows = (await db.execute(queries.providers)).all()

    return build_analytics_response(
        days=days,
        now=now,
        since=since,
        summary=summary,
        project_rows=project_rows,
        project_lookup=project_lookup,
        available_initiator_rows=available_initiator_rows,
        initiator_rows=initiator_rows,
        trend_rows=trend_rows,
        priority_wait_rows=priority_wait_rows,
        issue_status_rows=issue_status_rows,
        task_status_rows=task_status_rows,
        error_rows=error_rows,
        provider_rows=provider_rows,
    )


@router.get("/stats/activity-heatmap")
async def get_activity_heatmap(
    days: int = Query(default=365, ge=1, le=730),
    my: bool = Query(False, description="When true, scope to the current user's data only"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
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
    project_id: int | None = None,
    my: bool = Query(False, description="When true, restrict to tasks initiated by the current user"),
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_page_access("schedule_overview")),
):
    """Get aggregated statistics for scheduled tasks.

    Returns summary counts and 24-hour hourly distribution without
    fetching individual task objects — designed for ScheduleOverview polling.
    All authenticated users with schedule_overview access see the global queue.
    When my=True, restricts results to the current user's tasks.
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
    if project_id is not None:
        base_conditions.append(Task.project_id == project_id)
    if my and _current_user and getattr(_current_user, "username", None):
        base_conditions.append(Task.initiator_username == _current_user.username)

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

    settings = get_effective_settings()

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
        "slot_max_tasks": settings.slot_max_tasks,
        "slot_max_tasks_enforce": settings.slot_max_tasks_enforce,
    }
