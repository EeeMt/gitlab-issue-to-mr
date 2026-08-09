"""SQL query builders for the admin system lifecycle statistics endpoints.

Implements the system lifecycle statistics design §8–9: two UNION ALL CTEs
(current rows + deletion archives) over which the Overview, Trends and
Breakdown endpoints are computed. The current-task branch normalizes the same
dimensions (provider, harness) with the same value priority as the deletion
archive service (§6.5) so a Task does not move to another grouping when it is
deleted.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    case,
    cast,
    extract,
    false,
    func,
    literal,
    or_,
    select,
)
from sqlalchemy.sql.selectable import CTE

from app.models import (
    AIProvider,
    DeletedIssueStatistics,
    DeletedTaskStatistics,
    Issue,
    Task,
    TaskStatus,
    TaskWorkerProfileSnapshot,
)

REPORTING_TIMEZONE = "Asia/Shanghai"
TERMINAL_TASK_STATUSES = ("completed", "failed", "cancelled")
ACTIVE_TASK_STATUSES = (
    TaskStatus.PENDING.value,
    TaskStatus.QUEUED.value,
    TaskStatus.RUNNING.value,
)
LONG_RUNNING_THRESHOLD_SECONDS = 3600
DEFAULT_BREAKDOWN_LIMIT = 10

_DATA_STATES = ("all", "retained", "deleted")


def _require_data_state(data_state: str) -> None:
    if data_state not in _DATA_STATES:
        raise ValueError(f"data_state must be one of {_DATA_STATES}, got {data_state!r}")


# ── normalization for the current-task branch (mirrors the archive service) ──


def _json_text(dialect: str, column, key: str) -> Any:
    """Extract a JSON object key as text, portably across PG and SQLite."""
    if dialect == "postgresql":
        return column.op("->>")(key)
    return func.json_extract(column, f"$.{key}")


def _normalized_current_dimensions(
    dialect: str, task, snapshot, provider
) -> tuple[Any, Any, Any, Any]:
    runtime = task.provider_runtime_snapshot
    snap_provider_id = _json_text(dialect, runtime, "provider_id").cast(Integer)
    snap_provider_name = _json_text(dialect, runtime, "provider_name")
    snap_provider_model = _json_text(dialect, runtime, "configured_model")
    provider_id = case(
        (snap_provider_id.is_not(None), snap_provider_id),
        else_=task.provider_id,
    )
    provider_name = case(
        (snap_provider_name.is_not(None), snap_provider_name),
        else_=provider.name,
    )
    provider_model = case(
        (task.model_name.is_not(None), task.model_name),
        (snap_provider_model.is_not(None), snap_provider_model),
        else_=provider.model,
    )
    harness_key = case(
        (snapshot.harness_key.is_not(None), snapshot.harness_key),
        else_=task.projected_harness_key,
    )
    return provider_id, provider_name, provider_model, harness_key


def _current_task_branch(
    *,
    dialect: str,
    project_id: int | None,
    provider_id: int | None,
    harness_key: str | None,
    data_state: str,
):
    task = Task
    snapshot = TaskWorkerProfileSnapshot
    provider = AIProvider
    norm_provider_id, norm_provider_name, norm_provider_model, norm_harness_key = (
        _normalized_current_dimensions(dialect, task, snapshot, provider)
    )

    stmt = (
        select(
            task.id.label("task_id"),
            task.issue_id.label("issue_id"),
            task.project_id.label("project_id"),
            norm_provider_id.label("provider_id"),
            norm_provider_name.label("provider_name"),
            norm_provider_model.label("provider_model"),
            norm_harness_key.label("harness_key"),
            task.task_mode.label("task_mode"),
            task.trigger_source.label("trigger_source"),
            task.is_retry.label("is_retry"),
            cast(task.status, String(32)).label("status"),
            literal(False).label("deleted_before_terminal"),
            task.is_manually_overridden.label("is_manually_overridden"),
            task.created_at.label("created_at"),
            task.scheduled_at.label("scheduled_at"),
            task.started_at.label("started_at"),
            task.completed_at.label("terminal_at"),
            task.input_tokens.label("input_tokens"),
            task.output_tokens.label("output_tokens"),
            task.additions.label("additions"),
            task.deletions.label("deletions"),
            task.total_changes.label("total_changes"),
            task.change_stats_recorded_at.is_not(None).label("change_data_available"),
            literal("retained").label("data_state"),
            literal(None, type_=DateTime).label("source_deleted_at"),
        )
        .select_from(task)
        .outerjoin(snapshot, snapshot.task_id == task.id)
        .outerjoin(provider, provider.id == task.provider_id)
    )

    if project_id is not None:
        stmt = stmt.where(task.project_id == project_id)
    if provider_id is not None:
        stmt = stmt.where(norm_provider_id == provider_id)
    if harness_key is not None:
        stmt = stmt.where(norm_harness_key == harness_key)
    if data_state == "deleted":
        stmt = stmt.where(false())
    return stmt


def _deleted_task_branch(
    *,
    project_id: int | None,
    provider_id: int | None,
    harness_key: str | None,
    data_state: str,
):
    dt = DeletedTaskStatistics
    stmt = select(
        dt.source_task_id.label("task_id"),
        dt.source_issue_id.label("issue_id"),
        dt.project_id.label("project_id"),
        dt.provider_id.label("provider_id"),
        dt.provider_name_snapshot.label("provider_name"),
        dt.provider_model_snapshot.label("provider_model"),
        dt.harness_key.label("harness_key"),
        dt.task_mode.label("task_mode"),
        dt.trigger_source.label("trigger_source"),
        dt.is_retry.label("is_retry"),
        dt.last_status.label("status"),
        dt.deleted_before_terminal.label("deleted_before_terminal"),
        dt.is_manually_overridden.label("is_manually_overridden"),
        dt.created_at.label("created_at"),
        dt.scheduled_at.label("scheduled_at"),
        dt.started_at.label("started_at"),
        dt.terminal_at.label("terminal_at"),
        dt.input_tokens.label("input_tokens"),
        dt.output_tokens.label("output_tokens"),
        dt.additions.label("additions"),
        dt.deletions.label("deletions"),
        dt.total_changes.label("total_changes"),
        dt.change_data_available.label("change_data_available"),
        literal("deleted").label("data_state"),
        dt.source_deleted_at.label("source_deleted_at"),
    )

    if project_id is not None:
        stmt = stmt.where(dt.project_id == project_id)
    if provider_id is not None:
        stmt = stmt.where(dt.provider_id == provider_id)
    if harness_key is not None:
        stmt = stmt.where(dt.harness_key == harness_key)
    if data_state == "retained":
        stmt = stmt.where(false())
    return stmt


def _current_issue_branch(*, project_id: int | None, data_state: str):
    issue = Issue
    stmt = select(
        issue.id.label("issue_id"),
        issue.project_id.label("project_id"),
        cast(issue.status, String(32)).label("status"),
        issue.created_at.label("created_at"),
        or_(
            issue.merge_request_iid.is_not(None),
            issue.merge_request_url.is_not(None),
        ).label("had_merge_request"),
        literal("retained").label("data_state"),
        literal(None, type_=DateTime).label("source_deleted_at"),
    )

    if project_id is not None:
        stmt = stmt.where(issue.project_id == project_id)
    if data_state == "deleted":
        stmt = stmt.where(false())
    return stmt


def _deleted_issue_branch(*, project_id: int | None, data_state: str):
    di = DeletedIssueStatistics
    stmt = select(
        di.source_issue_id.label("issue_id"),
        di.project_id.label("project_id"),
        di.last_status.label("status"),
        di.created_at.label("created_at"),
        di.had_merge_request.label("had_merge_request"),
        literal("deleted").label("data_state"),
        di.source_deleted_at.label("source_deleted_at"),
    )

    if project_id is not None:
        stmt = stmt.where(di.project_id == project_id)
    if data_state == "retained":
        stmt = stmt.where(false())
    return stmt


# ── CTE builders ──


def build_all_task_statistics_cte(
    *,
    dialect: str,
    project_id: int | None,
    provider_id: int | None,
    harness_key: str | None,
    data_state: str,
) -> CTE:
    _require_data_state(data_state)
    current = _current_task_branch(
        dialect=dialect,
        project_id=project_id,
        provider_id=provider_id,
        harness_key=harness_key,
        data_state=data_state,
    )
    deleted = _deleted_task_branch(
        project_id=project_id,
        provider_id=provider_id,
        harness_key=harness_key,
        data_state=data_state,
    )
    return current.union_all(deleted).cte("all_task_statistics")


def build_all_issue_statistics_cte(
    *,
    project_id: int | None,
    data_state: str,
) -> CTE:
    _require_data_state(data_state)
    current = _current_issue_branch(project_id=project_id, data_state=data_state)
    deleted = _deleted_issue_branch(project_id=project_id, data_state=data_state)
    return current.union_all(deleted).cte("all_issue_statistics")


# ── cross-dialect expressions ──


def duration_seconds(dialect: str, start_col, end_col) -> Any:
    """Seconds between two datetime columns (NULL-able expressions)."""
    if dialect == "postgresql":
        return extract("epoch", end_col - start_col)
    # SQLite: julianday() * 86400 to get a float second count.
    return (func.julianday(end_col) - func.julianday(start_col)) * 86400.0


def _token_complete(t: CTE) -> Any:
    return t.c.input_tokens.is_not(None) & t.c.output_tokens.is_not(None)


def _token_partial(t: CTE) -> Any:
    return or_(
        t.c.input_tokens.is_not(None) & t.c.output_tokens.is_(None),
        t.c.input_tokens.is_(None) & t.c.output_tokens.is_not(None),
    )


def _token_missing(t: CTE) -> Any:
    return t.c.input_tokens.is_(None) & t.c.output_tokens.is_(None)


def _change_available(t: CTE) -> Any:
    return t.c.change_data_available.is_(True)


def _token_eligible(t: CTE) -> Any:
    return (
        t.c.status.in_(TERMINAL_TASK_STATUSES)
        & t.c.started_at.is_not(None)
        & (~t.c.deleted_before_terminal)
    )


def _code_eligible(t: CTE) -> Any:
    return (
        (t.c.task_mode == "execute")
        & (t.c.status == "completed")
        & (~t.c.deleted_before_terminal)
    )


def task_execution_seconds(dialect: str, t: CTE) -> Any:
    return case(
        (
            t.c.started_at.is_not(None) & t.c.terminal_at.is_not(None),
            duration_seconds(dialect, t.c.started_at, t.c.terminal_at),
        ),
        else_=None,
    )


def task_queue_wait_seconds(dialect: str, t: CTE) -> Any:
    queue_base = case(
        (
            t.c.scheduled_at.is_not(None) & (t.c.scheduled_at > t.c.created_at),
            t.c.scheduled_at,
        ),
        else_=t.c.created_at,
    )
    return case(
        (
            t.c.started_at.is_not(None) & queue_base.is_not(None),
            duration_seconds(dialect, queue_base, t.c.started_at),
        ),
        else_=None,
    )


def bucket_expression(dialect: str, time_col, bucket: str) -> Any:
    if dialect == "postgresql":
        localized = (
            time_col.op("AT TIME ZONE")("UTC").op("AT TIME ZONE")(REPORTING_TIMEZONE)
        )
        if bucket == "day":
            return func.date_trunc("day", localized)
        if bucket == "week":
            return func.date_trunc("week", localized)
        return func.date_trunc("month", localized)
    # SQLite fallback: UTC calendar bucketing (no timezone conversion).
    if bucket == "week":
        return func.strftime("%Y-W%W", time_col)
    if bucket == "month":
        return func.strftime("%Y-%m", time_col)
    return func.date(time_col)


def build_earliest_lifecycle_query(all_tasks: CTE, all_issues: CTE) -> Any:
    """Return the earliest created_at across retained + deleted Tasks and Issues."""
    task_min = (
        select(func.min(all_tasks.c.created_at).label("m")).select_from(all_tasks).scalar_subquery()
    )
    issue_min = (
        select(func.min(all_issues.c.created_at).label("m"))
        .select_from(all_issues)
        .scalar_subquery()
    )
    # CASE instead of LEAST(): portable across PostgreSQL and SQLite.
    earliest = case(
        (
            task_min.is_not(None)
            & issue_min.is_not(None)
            & (task_min < issue_min),
            task_min,
        ),
        (issue_min.is_not(None), issue_min),
        else_=task_min,
    )
    return select(earliest.label("earliest_at"))


def pick_bucket_for_all(earliest_at: datetime | None, now: datetime) -> str:
    if earliest_at is None:
        return "week"
    span = now - earliest_at
    if span <= timedelta(days=90):
        return "day"
    if span <= timedelta(days=730):
        return "week"
    return "month"


# ── Overview ──


def build_current_state_task_query(
    *,
    dialect: str,
    project_id: int | None,
    provider_id: int | None,
    harness_key: str | None,
    now: datetime,
) -> Any:
    """Live-table snapshot of Pending/Queued/Running, long-running and queue wait."""
    task = Task
    snapshot = TaskWorkerProfileSnapshot
    provider = AIProvider
    norm_provider_id, _name, _model, norm_harness_key = _normalized_current_dimensions(
        dialect, task, snapshot, provider
    )
    queue_base = case(
        (
            task.scheduled_at.is_not(None) & (task.scheduled_at > task.created_at),
            task.scheduled_at,
        ),
        else_=task.created_at,
    )
    waiting = task.status.in_(ACTIVE_TASK_STATUSES[:-1])
    queue_wait = case(
        (waiting & queue_base.is_not(None), task_queue_wait_now(dialect, queue_base, now)),
        else_=None,
    )

    stmt = (
        select(
            func.coalesce(
                func.sum(case((task.status == TaskStatus.PENDING, 1), else_=0)), 0
            ).label("pending"),
            func.coalesce(
                func.sum(case((task.status == TaskStatus.QUEUED, 1), else_=0)), 0
            ).label("queued"),
            func.coalesce(
                func.sum(case((task.status == TaskStatus.RUNNING, 1), else_=0)), 0
            ).label("running"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (task.status == TaskStatus.RUNNING)
                            & task.started_at.is_not(None)
                            & (task.started_at < now - timedelta(seconds=LONG_RUNNING_THRESHOLD_SECONDS)),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("long_running"),
            func.avg(queue_wait).label("avg_queue_wait_seconds"),
            func.coalesce(
                func.sum(case((waiting & queue_base.is_not(None), 1), else_=0)), 0
            ).label("queue_wait_samples"),
        )
        .select_from(task)
        .outerjoin(snapshot, snapshot.task_id == task.id)
        .outerjoin(provider, provider.id == task.provider_id)
    )

    if project_id is not None:
        stmt = stmt.where(task.project_id == project_id)
    if provider_id is not None:
        stmt = stmt.where(norm_provider_id == provider_id)
    if harness_key is not None:
        stmt = stmt.where(norm_harness_key == harness_key)
    return stmt


def task_queue_wait_now(dialect: str, queue_base, now: datetime) -> Any:
    """Current (ongoing) queue wait for a still-waiting Task: now - queue_base."""
    if dialect == "postgresql":
        return extract("epoch", now - queue_base)
    return (func.julianday(now) - func.julianday(queue_base)) * 86400.0


def build_current_state_issue_query(*, project_id: int | None) -> Any:
    """Live active Issue count (status not closed), Project-filtered."""
    stmt = select(
        func.coalesce(func.sum(case((Issue.status != "closed", 1), else_=0)), 0).label(
            "active_issues"
        )
    )
    if project_id is not None:
        stmt = stmt.where(Issue.project_id == project_id)
    return stmt


def build_lifetime_task_query(dialect: str, all_tasks: CTE) -> Any:
    t = all_tasks
    return select(
        func.count(t.c.task_id).label("task_count"),
        func.count(case((t.c.data_state == "deleted", t.c.task_id))).label(
            "deleted_task_count"
        ),
        func.coalesce(
            func.sum(case((t.c.status == "completed", 1), else_=0)), 0
        ).label("completed"),
        func.coalesce(
            func.sum(case((t.c.status == "failed", 1), else_=0)), 0
        ).label("failed"),
        func.coalesce(
            func.sum(case((t.c.status == "cancelled", 1), else_=0)), 0
        ).label("cancelled"),
        func.coalesce(
            func.sum(case((t.c.deleted_before_terminal, 1), else_=0)), 0
        ).label("deleted_before_terminal"),
        func.coalesce(
            func.sum(task_execution_seconds(dialect, t)), 0
        ).label("known_execution_seconds"),
        func.coalesce(
            func.sum(case((_token_complete(t), t.c.input_tokens), else_=None)), 0
        ).label("known_input_tokens"),
        func.coalesce(
            func.sum(case((_token_complete(t), t.c.output_tokens), else_=None)), 0
        ).label("known_output_tokens"),
        func.coalesce(
            func.sum(case((_change_available(t), t.c.total_changes), else_=None)), 0
        ).label("known_total_changes"),
        func.coalesce(
            func.sum(case((_token_complete(t), 1), else_=0)), 0
        ).label("token_complete_samples"),
        func.coalesce(
            func.sum(case((_token_partial(t), 1), else_=0)), 0
        ).label("token_partial_samples"),
        func.coalesce(
            func.sum(case((_token_missing(t), 1), else_=0)), 0
        ).label("token_missing_samples"),
        func.coalesce(
            func.sum(case((_token_eligible(t), 1), else_=0)), 0
        ).label("token_eligible_samples"),
        func.coalesce(
            func.sum(case((_change_available(t), 1), else_=0)), 0
        ).label("change_available_samples"),
        func.coalesce(
            func.sum(case((_code_eligible(t), 1), else_=0)), 0
        ).label("code_eligible_samples"),
    )


def build_lifetime_issue_query(all_issues: CTE) -> Any:
    i = all_issues
    return select(
        func.count(i.c.issue_id).label("issue_count"),
        func.count(case((i.c.data_state == "deleted", i.c.issue_id))).label(
            "deleted_issue_count"
        ),
        func.coalesce(func.sum(case((i.c.had_merge_request, 1), else_=0)), 0).label(
            "issues_with_mr"
        ),
    )


# ── Trends ──


def build_task_created_trend(
    all_tasks: CTE, dialect: str, bucket: str, since: datetime | None
) -> Any:
    t = all_tasks
    bucket_expr = bucket_expression(dialect, t.c.created_at, bucket)
    stmt = select(
        bucket_expr.label("bucket"),
        func.count(t.c.task_id).label("task_count"),
    )
    if since is not None:
        stmt = stmt.where(t.c.created_at >= since)
    return stmt.group_by(bucket_expr).order_by(bucket_expr.asc())


def build_task_finished_trend(
    all_tasks: CTE, dialect: str, bucket: str, since: datetime | None
) -> Any:
    t = all_tasks
    bucket_expr = bucket_expression(dialect, t.c.terminal_at, bucket)
    stmt = select(
        bucket_expr.label("bucket"),
        func.count(t.c.task_id).label("task_count"),
        func.coalesce(
            func.sum(case((t.c.status == "completed", 1), else_=0)), 0
        ).label("completed"),
        func.coalesce(
            func.sum(case((t.c.status == "failed", 1), else_=0)), 0
        ).label("failed"),
        func.coalesce(
            func.sum(case((t.c.status == "cancelled", 1), else_=0)), 0
        ).label("cancelled"),
        func.coalesce(
            func.sum(case((_token_complete(t), t.c.input_tokens), else_=None)), 0
        ).label("known_input_tokens"),
        func.coalesce(
            func.sum(case((_token_complete(t), t.c.output_tokens), else_=None)), 0
        ).label("known_output_tokens"),
        func.coalesce(
            func.sum(case((_change_available(t), t.c.total_changes), else_=None)), 0
        ).label("known_total_changes"),
        func.coalesce(
            func.sum(task_execution_seconds(dialect, t)), 0
        ).label("known_execution_seconds"),
    ).where(t.c.terminal_at.is_not(None))
    if since is not None:
        stmt = stmt.where(t.c.terminal_at >= since)
    return stmt.group_by(bucket_expr).order_by(bucket_expr.asc())


def build_task_deleted_trend(
    all_tasks: CTE, dialect: str, bucket: str, since: datetime | None
) -> Any:
    t = all_tasks
    bucket_expr = bucket_expression(dialect, t.c.source_deleted_at, bucket)
    stmt = select(
        bucket_expr.label("bucket"),
        func.count(t.c.task_id).label("task_count"),
    ).where(t.c.source_deleted_at.is_not(None), t.c.data_state == "deleted")
    if since is not None:
        stmt = stmt.where(t.c.source_deleted_at >= since)
    return stmt.group_by(bucket_expr).order_by(bucket_expr.asc())


def build_issue_created_trend(
    all_issues: CTE, dialect: str, bucket: str, since: datetime | None
) -> Any:
    i = all_issues
    bucket_expr = bucket_expression(dialect, i.c.created_at, bucket)
    stmt = select(
        bucket_expr.label("bucket"),
        func.count(i.c.issue_id).label("issue_count"),
    )
    if since is not None:
        stmt = stmt.where(i.c.created_at >= since)
    return stmt.group_by(bucket_expr).order_by(bucket_expr.asc())


# ── Breakdowns ──


def _breakdown_select(t: CTE, key_expr) -> Any:
    return select(
        key_expr.label("key"),
        func.count(t.c.task_id).label("task_count"),
        func.coalesce(
            func.sum(case((t.c.status == "completed", 1), else_=0)), 0
        ).label("completed"),
        func.coalesce(
            func.sum(case((t.c.status == "failed", 1), else_=0)), 0
        ).label("failed"),
        func.coalesce(
            func.sum(case((t.c.status == "cancelled", 1), else_=0)), 0
        ).label("cancelled"),
        func.count(case((t.c.data_state == "deleted", t.c.task_id))).label(
            "deleted_count"
        ),
        func.coalesce(
            func.sum(case((_token_complete(t), t.c.input_tokens), else_=None)), 0
        ).label("known_input_tokens"),
        func.coalesce(
            func.sum(case((_token_complete(t), t.c.output_tokens), else_=None)), 0
        ).label("known_output_tokens"),
        func.coalesce(
            func.sum(case((_change_available(t), t.c.total_changes), else_=None)), 0
        ).label("known_total_changes"),
    )


def build_project_breakdown(dialect: str, all_tasks: CTE) -> Any:
    t = all_tasks
    key = t.c.project_id.label("key")
    return (
        _breakdown_select(t, key)
        .group_by(t.c.project_id)
        .order_by(func.count(t.c.task_id).desc(), t.c.project_id.asc())
    )


def build_provider_breakdown(dialect: str, all_tasks: CTE) -> Any:
    t = all_tasks
    return (
        select(
            t.c.provider_id.label("key"),
            t.c.provider_name.label("label"),
            t.c.provider_model.label("model"),
            func.count(t.c.task_id).label("task_count"),
            func.coalesce(
                func.sum(case((t.c.status == "completed", 1), else_=0)), 0
            ).label("completed"),
            func.coalesce(
                func.sum(case((t.c.status == "failed", 1), else_=0)), 0
            ).label("failed"),
            func.coalesce(
                func.sum(case((t.c.status == "cancelled", 1), else_=0)), 0
            ).label("cancelled"),
            func.count(case((t.c.data_state == "deleted", t.c.task_id))).label(
                "deleted_count"
            ),
            func.coalesce(
                func.sum(case((_token_complete(t), t.c.input_tokens), else_=None)), 0
            ).label("known_input_tokens"),
            func.coalesce(
                func.sum(case((_token_complete(t), t.c.output_tokens), else_=None)), 0
            ).label("known_output_tokens"),
            func.coalesce(
                func.sum(case((_change_available(t), t.c.total_changes), else_=None)), 0
            ).label("known_total_changes"),
        )
        .group_by(t.c.provider_id, t.c.provider_name, t.c.provider_model)
        .order_by(func.count(t.c.task_id).desc(), t.c.provider_id.asc())
    )


def build_harness_breakdown(dialect: str, all_tasks: CTE) -> Any:
    t = all_tasks
    key = t.c.harness_key.label("key")
    return (
        _breakdown_select(t, key)
        .group_by(t.c.harness_key)
        .order_by(func.count(t.c.task_id).desc(), t.c.harness_key.asc())
    )
