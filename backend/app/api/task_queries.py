"""Query construction for task list endpoints."""

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import false, func, select
from sqlalchemy.orm import selectinload

from app.api.initiator_filters import apply_initiator_filter
from app.api.list_filter_values import (
    normalize_search_term,
    parse_csv_integers,
    parse_datetime_filter,
    validate_datetime_range,
)
from app.dependencies.project_access import ProjectAccessScope
from app.models import Issue, Task, TaskStatus

TASKS_SORT_FIELDS = {
    "created_at",
    "status",
    "priority",
    "total_changes",
    "input_tokens",
    "output_tokens",
    "duration",
}
SORT_ORDERS = {"asc", "desc"}


@dataclass(frozen=True)
class TaskListFilters:
    status: str | None = None
    project_id: str | None = None
    issue_id: int | None = None
    initiator: str | None = None
    initiator_username: str | None = None
    priority: str | None = None
    has_mr: bool | None = None
    search: str | None = None
    created_after: str | None = None
    created_before: str | None = None
    scheduled_after: str | None = None
    scheduled_before: str | None = None
    sort_by: str | None = None
    sort_order: str | None = None


def _restrict_to_accessible_projects(query, access_scope: ProjectAccessScope):
    project_ids = access_scope.accessible_project_ids
    if not project_ids:
        return query.where(false())
    return query.where(Task.project_id.in_(project_ids))


def build_task_list_query(
    filters: TaskListFilters,
    access_scope: ProjectAccessScope,
):
    sort_by = filters.sort_by or "created_at"
    sort_order = filters.sort_order or "desc"
    if sort_by not in TASKS_SORT_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort_by: {sort_by}. Allowed: {', '.join(sorted(TASKS_SORT_FIELDS))}",
        )
    if sort_order not in SORT_ORDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort_order: {sort_order}. Allowed: asc, desc",
        )

    if sort_by == "duration":
        duration = func.coalesce(
            func.extract("epoch", Task.completed_at - Task.started_at),
            func.extract("epoch", func.now() - Task.started_at),
        )
        order_clause = (
            duration.asc().nullslast()
            if sort_order == "asc"
            else duration.desc().nullslast()
        )
    else:
        sort_column = getattr(Task, sort_by)
        order_clause = (
            sort_column.asc().nullslast()
            if sort_order == "asc"
            else sort_column.desc().nullslast()
        )

    tie_breaker = Task.id.asc() if sort_order == "asc" else Task.id.desc()
    query = (
        select(Task)
        .options(
            selectinload(Task.issue),
            selectinload(Task.provider),
            selectinload(Task.worker_profile),
            selectinload(Task.worker_profile_snapshot),
        )
        .order_by(order_clause, tie_breaker)
    )

    if filters.status:
        parts = [value.strip() for value in filters.status.split(",") if value.strip()]
        valid: list[TaskStatus] = []
        invalid: list[str] = []
        for value in parts:
            try:
                valid.append(TaskStatus(value))
            except ValueError:
                invalid.append(value)
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid status value(s): {', '.join(invalid)}. "
                    f"Allowed: {', '.join(status.value for status in TaskStatus)}"
                ),
            )
        if len(valid) == 1:
            query = query.where(Task.status == valid[0])
        elif valid:
            query = query.where(Task.status.in_(valid))

    if filters.project_id:
        project_ids = parse_csv_integers(filters.project_id, "project_id", minimum=1)
        if project_ids:
            if not access_scope.is_unrestricted:
                project_ids = [
                    project_id
                    for project_id in project_ids
                    if project_id in access_scope.accessible_project_ids
                ]
            if len(project_ids) == 1:
                query = query.where(Task.project_id == project_ids[0])
            elif project_ids:
                query = query.where(Task.project_id.in_(project_ids))
            else:
                query = query.where(false())
    elif not access_scope.is_unrestricted:
        query = _restrict_to_accessible_projects(query, access_scope)

    if filters.initiator:
        query = apply_initiator_filter(query, Task, filters.initiator)
    elif filters.initiator_username:
        usernames = [
            value.strip()
            for value in filters.initiator_username.split(",")
            if value.strip()
        ]
        if len(usernames) == 1:
            query = query.where(Task.initiator_username == usernames[0])
        elif usernames:
            query = query.where(Task.initiator_username.in_(usernames))

    if filters.issue_id:
        query = query.where(Task.issue_id == filters.issue_id)

    if filters.priority:
        priorities = parse_csv_integers(filters.priority, "priority", allowed={0, 1, 2})
        if len(priorities) == 1:
            query = query.where(Task.priority == priorities[0])
        elif priorities:
            query = query.where(Task.priority.in_(priorities))

    if filters.has_mr is not None:
        condition = (
            Issue.merge_request_iid.is_not(None)
            if filters.has_mr
            else Issue.merge_request_iid.is_(None)
        )
        query = query.where(Task.issue.has(condition))

    if filters.search:
        search_term = normalize_search_term(filters.search)
        if search_term:
            escaped = (
                search_term
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            query = query.where(Task.user_prompt.ilike(f"%{escaped}%", escape="\\"))

    date_filters = (
        ("created_after", Task.created_at, True),
        ("created_before", Task.created_at, False),
        ("scheduled_after", Task.scheduled_at, True),
        ("scheduled_before", Task.scheduled_at, False),
    )
    parsed_dates: dict[str, tuple[Any, Any, bool]] = {}
    for field, column, is_lower_bound in date_filters:
        value = getattr(filters, field)
        if value:
            parsed = parse_datetime_filter(value, field)
            parsed_dates[field] = (parsed, column, is_lower_bound)

    validate_datetime_range(
        parsed_dates.get("created_after", (None, None, False))[0],
        parsed_dates.get("created_before", (None, None, False))[0],
        "created_after",
        "created_before",
    )
    validate_datetime_range(
        parsed_dates.get("scheduled_after", (None, None, False))[0],
        parsed_dates.get("scheduled_before", (None, None, False))[0],
        "scheduled_after",
        "scheduled_before",
    )
    for parsed, column, is_lower_bound in parsed_dates.values():
        query = query.where(column >= parsed if is_lower_bound else column <= parsed)

    return query
