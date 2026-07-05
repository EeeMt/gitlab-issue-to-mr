"""SQL query builders for the analytics endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import case, false, func, select

from app.dependencies.project_access import ProjectAccessScope
from app.models import AIProvider, Issue, Task, TaskStatus

FINISHED_TASK_STATUSES = (
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
)


@dataclass(frozen=True)
class AnalyticsExpressions:
    finished_task: Any
    execution_seconds: Any
    queue_wait_seconds: Any
    token_total: Any
    output_tokens: Any
    token_tracked: Any
    throughput_eligible: Any


@dataclass(frozen=True)
class AnalyticsQueries:
    summary: Any
    projects: Any
    available_initiators: Any
    initiators: Any
    trends: Any
    priority_waits: Any
    issue_statuses: Any
    task_statuses: Any
    errors: Any
    providers: Any


def apply_project_column_scope(query, project_column, access_scope: ProjectAccessScope):
    if access_scope.is_unrestricted:
        return query
    allowed_project_ids = access_scope.accessible_project_ids
    if not allowed_project_ids:
        return query.where(false())
    return query.where(project_column.in_(allowed_project_ids))


def apply_project_scope(query, access_scope: ProjectAccessScope):
    return apply_project_column_scope(query, Task.project_id, access_scope)


def apply_analytics_filters(
    query,
    access_scope: ProjectAccessScope,
    project_id: int | None = None,
    initiator_username: str | None = None,
):
    query = apply_project_scope(query, access_scope)
    if project_id is not None:
        query = query.where(Task.project_id == project_id)
    if initiator_username:
        query = query.where(Task.initiator_username == initiator_username)
    return query


def apply_issue_analytics_filters(
    query,
    access_scope: ProjectAccessScope,
    project_id: int | None = None,
    initiator_username: str | None = None,
):
    query = apply_project_column_scope(query, Issue.project_id, access_scope)
    if project_id is not None:
        query = query.where(Issue.project_id == project_id)
    if initiator_username:
        query = query.where(Issue.initiator_username == initiator_username)
    return query


def build_analytics_expressions() -> AnalyticsExpressions:
    finished_task = case((Task.status.in_(FINISHED_TASK_STATUSES), 1), else_=0)
    execution_seconds = case(
        (
            Task.started_at.is_not(None) & Task.completed_at.is_not(None),
            func.extract("epoch", Task.completed_at - Task.started_at),
        ),
        else_=None,
    )
    queue_wait_seconds = case(
        (
            Task.started_at.is_not(None)
            & Task.scheduled_at.is_not(None)
            & (Task.scheduled_at > Task.created_at),
            func.extract("epoch", Task.started_at - Task.scheduled_at),
        ),
        (
            Task.started_at.is_not(None),
            func.extract("epoch", Task.started_at - Task.created_at),
        ),
        else_=None,
    )
    token_total = case(
        (
            Task.input_tokens.is_not(None) | Task.output_tokens.is_not(None),
            func.coalesce(Task.input_tokens, 0) + func.coalesce(Task.output_tokens, 0),
        ),
        else_=None,
    )
    output_tokens = case(
        (Task.output_tokens.is_not(None), Task.output_tokens),
        else_=None,
    )
    token_tracked = case(
        (Task.input_tokens.is_not(None) | Task.output_tokens.is_not(None), 1),
        else_=0,
    )
    throughput_eligible = (
        output_tokens.is_not(None)
        & execution_seconds.is_not(None)
        & (execution_seconds > 0)
    )
    return AnalyticsExpressions(
        finished_task=finished_task,
        execution_seconds=execution_seconds,
        queue_wait_seconds=queue_wait_seconds,
        token_total=token_total,
        output_tokens=output_tokens,
        token_tracked=token_tracked,
        throughput_eligible=throughput_eligible,
    )


def _build_summary_query(
    since: datetime,
    access_scope: ProjectAccessScope,
    project_id: int | None,
    initiator_username: str | None,
    expressions: AnalyticsExpressions,
):
    return apply_analytics_filters(
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
            func.coalesce(func.sum(expressions.finished_task), 0),
            func.coalesce(func.sum(case((Task.initiator_username.is_not(None), 1), else_=0)), 0),
            func.coalesce(func.sum(expressions.token_tracked), 0),
            func.min(case((Task.initiator_username.is_not(None), Task.created_at), else_=None)),
            func.coalesce(func.sum(expressions.execution_seconds), 0).label(
                "total_execution_seconds"
            ),
            func.avg(expressions.execution_seconds),
            func.max(expressions.execution_seconds),
            func.avg(expressions.queue_wait_seconds),
            func.max(expressions.queue_wait_seconds),
            func.avg(expressions.token_total),
            func.max(expressions.token_total),
        ).where(Task.created_at >= since),
        access_scope,
        project_id=project_id,
        initiator_username=initiator_username,
    )


def _common_breakdown_columns(expressions: AnalyticsExpressions) -> tuple[Any, ...]:
    return (
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
        func.coalesce(
            func.sum(func.coalesce(Task.input_tokens, 0) + func.coalesce(Task.output_tokens, 0)),
            0,
        ).label("total_tokens"),
        func.avg(expressions.execution_seconds).label("avg_execution_seconds"),
        func.coalesce(func.sum(expressions.execution_seconds), 0).label(
            "total_execution_seconds"
        ),
        func.avg(expressions.queue_wait_seconds).label("avg_queue_wait_seconds"),
        func.max(Task.created_at).label("last_task_at"),
    )


def _build_project_query(
    since: datetime,
    access_scope: ProjectAccessScope,
    project_id: int | None,
    initiator_username: str | None,
    expressions: AnalyticsExpressions,
):
    query = (
        select(Task.project_id, *_common_breakdown_columns(expressions))
        .where(Task.created_at >= since)
        .group_by(Task.project_id)
        .order_by(
            func.count(Task.id).desc(),
            func.coalesce(func.sum(Task.total_changes), 0).desc(),
            Task.project_id.asc(),
        )
    )
    return apply_analytics_filters(
        query,
        access_scope,
        project_id=project_id,
        initiator_username=initiator_username,
    )


def _build_available_initiators_query(
    since: datetime,
    access_scope: ProjectAccessScope,
    project_id: int | None,
):
    query = (
        select(
            Task.initiator_username,
            Task.initiator_gitlab_user_id,
            func.count(Task.id).label("task_count"),
        )
        .where(Task.created_at >= since, Task.initiator_username.is_not(None))
        .group_by(Task.initiator_username, Task.initiator_gitlab_user_id)
        .order_by(func.count(Task.id).desc(), Task.initiator_username.asc())
    )
    return apply_analytics_filters(query, access_scope, project_id=project_id)


def _build_initiator_query(
    since: datetime,
    access_scope: ProjectAccessScope,
    project_id: int | None,
    initiator_username: str | None,
    expressions: AnalyticsExpressions,
):
    query = (
        select(
            Task.initiator_username,
            Task.initiator_gitlab_user_id,
            *_common_breakdown_columns(expressions),
        )
        .where(Task.created_at >= since, Task.initiator_username.is_not(None))
        .group_by(Task.initiator_username, Task.initiator_gitlab_user_id)
        .order_by(
            func.count(Task.id).desc(),
            func.coalesce(func.sum(Task.total_changes), 0).desc(),
            Task.initiator_username.asc(),
        )
    )
    return apply_analytics_filters(
        query,
        access_scope,
        project_id=project_id,
        initiator_username=initiator_username,
    )


def _build_trend_query(
    since: datetime,
    access_scope: ProjectAccessScope,
    project_id: int | None,
    initiator_username: str | None,
    expressions: AnalyticsExpressions,
):
    query = (
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
            func.coalesce(
                func.sum(func.coalesce(Task.input_tokens, 0) + func.coalesce(Task.output_tokens, 0)),
                0,
            ).label("total_tokens"),
            func.avg(expressions.execution_seconds).label("avg_execution_seconds"),
        )
        .where(Task.created_at >= since)
        .group_by(func.date(Task.created_at))
        .order_by(func.date(Task.created_at).asc())
    )
    return apply_analytics_filters(
        query,
        access_scope,
        project_id=project_id,
        initiator_username=initiator_username,
    )


def _build_priority_wait_query(
    since: datetime,
    access_scope: ProjectAccessScope,
    project_id: int | None,
    initiator_username: str | None,
    expressions: AnalyticsExpressions,
):
    query = (
        select(
            Task.priority,
            func.count(Task.id).label("task_count"),
            func.avg(expressions.queue_wait_seconds).label("avg_queue_wait_seconds"),
            func.max(expressions.queue_wait_seconds).label("max_queue_wait_seconds"),
        )
        .where(Task.created_at >= since, Task.started_at.is_not(None))
        .group_by(Task.priority)
        .order_by(Task.priority.asc())
    )
    return apply_analytics_filters(
        query,
        access_scope,
        project_id=project_id,
        initiator_username=initiator_username,
    )


def _build_issue_status_query(
    since: datetime,
    access_scope: ProjectAccessScope,
    project_id: int | None,
    initiator_username: str | None,
):
    query = (
        select(Issue.status.label("status"), func.count(Issue.id).label("count"))
        .where(Issue.created_at >= since)
        .group_by(Issue.status)
        .order_by(Issue.status.asc())
    )
    return apply_issue_analytics_filters(
        query,
        access_scope,
        project_id=project_id,
        initiator_username=initiator_username,
    )


def _build_task_status_query(
    since: datetime,
    access_scope: ProjectAccessScope,
    project_id: int | None,
    initiator_username: str | None,
):
    query = (
        select(Task.status.label("status"), func.count(Task.id).label("count"))
        .where(Task.created_at >= since)
        .group_by(Task.status)
        .order_by(Task.status.asc())
    )
    return apply_analytics_filters(
        query,
        access_scope,
        project_id=project_id,
        initiator_username=initiator_username,
    )


def _build_error_query(
    since: datetime,
    access_scope: ProjectAccessScope,
    project_id: int | None,
    initiator_username: str | None,
):
    query = (
        select(Task.error_message, func.count(Task.id).label("count"))
        .where(
            Task.created_at >= since,
            Task.status == TaskStatus.FAILED,
            Task.error_message.is_not(None),
        )
        .group_by(Task.error_message)
        .order_by(func.count(Task.id).desc(), Task.error_message.asc())
    )
    return apply_analytics_filters(
        query,
        access_scope,
        project_id=project_id,
        initiator_username=initiator_username,
    )


def _build_provider_query(
    since: datetime,
    access_scope: ProjectAccessScope,
    project_id: int | None,
    initiator_username: str | None,
    expressions: AnalyticsExpressions,
):
    query = (
        select(
            Task.provider_id.label("provider_id"),
            AIProvider.name.label("provider_name"),
            AIProvider.model.label("provider_model"),
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
            func.coalesce(func.sum(expressions.finished_task), 0).label("finished_tasks"),
            func.coalesce(func.sum(Task.input_tokens), 0).label("total_input_tokens"),
            func.coalesce(func.sum(Task.output_tokens), 0).label("total_output_tokens"),
            func.coalesce(func.sum(expressions.token_total), 0).label("total_tokens"),
            func.avg(
                case(
                    (expressions.token_total.is_not(None), expressions.token_total),
                    else_=None,
                )
            ).label("avg_tokens_per_task"),
            (
                func.sum(
                    case(
                        (expressions.throughput_eligible, expressions.output_tokens),
                        else_=None,
                    )
                )
                / func.nullif(
                    func.sum(
                        case(
                            (expressions.throughput_eligible, expressions.execution_seconds),
                            else_=None,
                        )
                    ),
                    0,
                )
            ).label("avg_tokens_per_second"),
            func.avg(
                case(
                    (
                        (expressions.token_total.is_not(None))
                        & (Task.total_changes.is_not(None))
                        & (Task.total_changes > 0),
                        expressions.token_total / Task.total_changes,
                    ),
                    else_=None,
                )
            ).label("avg_tokens_per_changed_line"),
            func.avg(expressions.execution_seconds).label("avg_execution_seconds"),
            func.avg(
                case(
                    (
                        (expressions.execution_seconds.is_not(None))
                        & (Task.total_changes.is_not(None))
                        & (Task.total_changes > 0),
                        expressions.execution_seconds / Task.total_changes,
                    ),
                    else_=None,
                )
            ).label("avg_execution_seconds_per_changed_line"),
        )
        .select_from(Task)
        .join(AIProvider, AIProvider.id == Task.provider_id)
        .where(
            Task.created_at >= since,
            Task.status.in_(FINISHED_TASK_STATUSES),
        )
        .group_by(Task.provider_id, AIProvider.name, AIProvider.model)
        .order_by(
            func.count(Task.id).desc(),
            func.coalesce(func.sum(expressions.token_total), 0).desc(),
            AIProvider.name.asc(),
            AIProvider.model.asc(),
            Task.provider_id.asc(),
        )
    )
    return apply_analytics_filters(
        query,
        access_scope,
        project_id=project_id,
        initiator_username=initiator_username,
    )


def build_analytics_queries(
    *,
    since: datetime,
    access_scope: ProjectAccessScope,
    project_id: int | None,
    initiator_username: str | None,
) -> AnalyticsQueries:
    expressions = build_analytics_expressions()
    return AnalyticsQueries(
        summary=_build_summary_query(
            since, access_scope, project_id, initiator_username, expressions
        ),
        projects=_build_project_query(
            since, access_scope, project_id, initiator_username, expressions
        ),
        available_initiators=_build_available_initiators_query(
            since, access_scope, project_id
        ),
        initiators=_build_initiator_query(
            since, access_scope, project_id, initiator_username, expressions
        ),
        trends=_build_trend_query(
            since, access_scope, project_id, initiator_username, expressions
        ),
        priority_waits=_build_priority_wait_query(
            since, access_scope, project_id, initiator_username, expressions
        ),
        issue_statuses=_build_issue_status_query(
            since, access_scope, project_id, initiator_username
        ),
        task_statuses=_build_task_status_query(
            since, access_scope, project_id, initiator_username
        ),
        errors=_build_error_query(
            since, access_scope, project_id, initiator_username
        ),
        providers=_build_provider_query(
            since, access_scope, project_id, initiator_username, expressions
        ),
    )
