"""Response serialization for task analytics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.models import IssueStatus, TaskStatus

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
    (
        "Tests",
        ("pytest", "test failed", "assertionerror", "failing test", "unit test", "integration test"),
    ),
    (
        "Code",
        (
            "syntaxerror",
            "indentationerror",
            "typeerror",
            "nameerror",
            "attributeerror",
            "traceback",
        ),
    ),
)


@dataclass(frozen=True)
class AnalyticsSummary:
    total_tasks: Any
    total_additions: Any
    total_deletions: Any
    total_changes: Any
    total_input_tokens: Any
    total_output_tokens: Any
    completed_tasks: Any
    failed_tasks: Any
    cancelled_tasks: Any
    finished_tasks: Any
    tracked_initiator_tasks: Any
    token_tracked_tasks: Any
    initiator_tracking_started_at: Any
    total_execution_seconds: Any
    avg_execution_seconds: Any
    max_execution_seconds: Any
    avg_queue_wait_seconds: Any
    max_queue_wait_seconds: Any
    avg_total_tokens_per_tracked_task: Any
    max_total_tokens_per_tracked_task: Any

    @classmethod
    def from_row(cls, row) -> AnalyticsSummary:
        return cls(*row)

    def serialize(self) -> dict:
        success_rate = safe_ratio(self.completed_tasks, self.finished_tasks)
        failure_rate = safe_ratio(self.failed_tasks, self.finished_tasks)
        return {
            "total_tasks": int(self.total_tasks or 0),
            "total_additions": int(self.total_additions or 0),
            "total_deletions": int(self.total_deletions or 0),
            "total_changes": int(self.total_changes or 0),
            "total_input_tokens": int(self.total_input_tokens or 0),
            "total_output_tokens": int(self.total_output_tokens or 0),
            "total_tokens": int(self.total_input_tokens or 0) + int(self.total_output_tokens or 0),
            "completed_tasks": int(self.completed_tasks or 0),
            "failed_tasks": int(self.failed_tasks or 0),
            "cancelled_tasks": int(self.cancelled_tasks or 0),
            "finished_tasks": int(self.finished_tasks or 0),
            "success_rate": success_rate,
            "failure_rate": failure_rate,
            "tracked_initiator_tasks": int(self.tracked_initiator_tasks or 0),
            "token_tracked_tasks": int(self.token_tracked_tasks or 0),
            "initiator_tracking_started_at": (
                self.initiator_tracking_started_at.isoformat()
                if self.initiator_tracking_started_at
                else None
            ),
            "total_execution_seconds": (
                float(self.total_execution_seconds)
                if self.total_execution_seconds is not None
                else 0.0
            ),
            "avg_execution_seconds": _optional_float(self.avg_execution_seconds),
            "max_execution_seconds": _optional_float(self.max_execution_seconds),
            "avg_queue_wait_seconds": _optional_float(self.avg_queue_wait_seconds),
            "max_queue_wait_seconds": _optional_float(self.max_queue_wait_seconds),
            "avg_total_tokens_per_tracked_task": _optional_float(
                self.avg_total_tokens_per_tracked_task
            ),
            "max_total_tokens_per_tracked_task": _optional_float(
                self.max_total_tokens_per_tracked_task
            ),
        }


def _optional_float(value) -> float | None:
    return float(value) if value is not None else None


def safe_ratio(numerator: int | float | None, denominator: int | float | None) -> float | None:
    if denominator in (None, 0) or numerator is None:
        return None
    return float(numerator) / float(denominator)


def categorize_error_message(error_message: str | None) -> str:
    if not error_message:
        return "Other"
    normalized = error_message.lower()
    for category, patterns in ERROR_CATEGORY_PATTERNS:
        if any(pattern in normalized for pattern in patterns):
            return category
    return "Other"


def summarize_error_message(error_message: str | None) -> str | None:
    if not error_message:
        return None
    first_line = next((line.strip() for line in error_message.splitlines() if line.strip()), "")
    return first_line[:160] if first_line else None


def build_status_breakdown_rows(statuses, raw_rows: list) -> list[dict]:
    counts_by_status: dict[str, int] = {}
    for row in raw_rows:
        status_value = getattr(row.status, "value", row.status)
        counts_by_status[str(status_value)] = int(row.count or 0)

    total = sum(counts_by_status.get(getattr(status, "value", status), 0) for status in statuses)
    return [
        {
            "status": str(getattr(status, "value", status)),
            "count": counts_by_status.get(str(getattr(status, "value", status)), 0),
            "share": (
                counts_by_status.get(str(getattr(status, "value", status)), 0) / total
                if total
                else 0
            ),
        }
        for status in statuses
    ]


def build_error_breakdown(error_rows: list[tuple[str, int]], failed_tasks: int) -> list[dict]:
    grouped: dict[str, dict[str, object]] = defaultdict(
        lambda: {"count": 0, "sample_message": None, "sample_count": 0}
    )
    for error_message, count in error_rows:
        category = categorize_error_message(error_message)
        bucket = grouped[category]
        bucket["count"] = int(bucket["count"]) + int(count)
        if bucket["sample_message"] is None or int(count) > int(bucket["sample_count"]):
            bucket["sample_message"] = summarize_error_message(error_message)
            bucket["sample_count"] = int(count)

    rows = [
        {
            "category": category,
            "count": int(values["count"]),
            "share_of_failed": (
                int(values["count"]) / failed_tasks if failed_tasks else 0
            ),
            "sample_message": values["sample_message"],
        }
        for category, values in grouped.items()
    ]
    rows.sort(key=lambda row: (-row["count"], row["category"]))
    return rows


def _provider_display_label(provider_name: str | None, provider_model: str | None) -> str:
    if not provider_name:
        return "Unknown / Legacy"
    return f"{provider_name} / {provider_model}" if provider_model else provider_name


def build_provider_chart_series(rows: list[dict]) -> dict[str, list[dict]]:
    def build(metric_key: str) -> list[dict]:
        return [
            {
                "provider_id": row["provider_id"],
                "label": _provider_display_label(row["provider_name"], row["provider_model"]),
                "value": row[metric_key],
            }
            for row in rows
            if row[metric_key] is not None
        ]

    return {
        "success_rate": build("success_rate"),
        "avg_tokens_per_second": build("avg_tokens_per_second"),
        "avg_tokens_per_changed_line": build("avg_tokens_per_changed_line"),
        "avg_execution_seconds_per_changed_line": build(
            "avg_execution_seconds_per_changed_line"
        ),
    }


def _serialize_provider_rows(rows: list) -> list[dict]:
    items: list[dict] = []
    for row in rows:
        finished_count = int(row.finished_tasks or 0)
        completed_count = int(row.completed_tasks or 0)
        items.append(
            {
                "provider_id": int(row.provider_id) if row.provider_id is not None else None,
                "provider_name": row.provider_name or "Unknown / Legacy",
                "provider_model": row.provider_model,
                "task_count": int(row.task_count or 0),
                "finished_task_count": finished_count,
                "completed_task_count": completed_count,
                "failed_task_count": int(row.failed_tasks or 0),
                "cancelled_task_count": int(row.cancelled_tasks or 0),
                "success_rate": safe_ratio(completed_count, finished_count),
                "total_input_tokens": int(row.total_input_tokens or 0),
                "total_output_tokens": int(row.total_output_tokens or 0),
                "total_tokens": int(row.total_tokens or 0),
                "avg_tokens_per_task": _optional_float(row.avg_tokens_per_task),
                "avg_tokens_per_second": _optional_float(row.avg_tokens_per_second),
                "avg_tokens_per_changed_line": _optional_float(
                    row.avg_tokens_per_changed_line
                ),
                "avg_execution_seconds": _optional_float(row.avg_execution_seconds),
                "avg_execution_seconds_per_changed_line": _optional_float(
                    row.avg_execution_seconds_per_changed_line
                ),
            }
        )
    return items


def _serialize_harness_rows(rows: list) -> list[dict]:
    items: list[dict] = []
    for row in rows:
        finished_count = int(row.finished_tasks or 0)
        completed_count = int(row.completed_tasks or 0)
        items.append(
            {
                "harness_key": row.harness_key or "claude",
                "adapter_version": row.adapter_version,
                "task_count": int(row.task_count or 0),
                "finished_task_count": finished_count,
                "completed_task_count": completed_count,
                "failed_task_count": int(row.failed_tasks or 0),
                "cancelled_task_count": int(row.cancelled_tasks or 0),
                "success_rate": safe_ratio(completed_count, finished_count),
                "avg_execution_seconds": _optional_float(row.avg_execution_seconds),
            }
        )
    return items


def _serialize_common_breakdown(row) -> dict:
    completed = int(row.completed_tasks or 0)
    failed = int(row.failed_tasks or 0)
    cancelled = int(row.cancelled_tasks or 0)
    return {
        "task_count": int(row.task_count or 0),
        "completed_tasks": completed,
        "failed_tasks": failed,
        "cancelled_tasks": cancelled,
        "success_rate": safe_ratio(completed, completed + failed + cancelled),
        "additions": int(row.additions or 0),
        "deletions": int(row.deletions or 0),
        "total_changes": int(row.total_changes or 0),
        "input_tokens": int(row.input_tokens or 0),
        "output_tokens": int(row.output_tokens or 0),
        "total_tokens": int(row.total_tokens or 0),
        "avg_execution_seconds": _optional_float(row.avg_execution_seconds),
        "total_execution_seconds": float(row.total_execution_seconds or 0),
        "avg_queue_wait_seconds": _optional_float(row.avg_queue_wait_seconds),
        "last_task_at": row.last_task_at.isoformat() if row.last_task_at else None,
    }


def _serialize_projects(rows: list, project_lookup: dict[int, dict]) -> list[dict]:
    items = []
    for row in rows:
        project_id = int(row.project_id)
        metadata = project_lookup.get(project_id) or {}
        items.append(
            {
                "project_id": project_id,
                "project_name": metadata.get("project_name") or f"Project {row.project_id}",
                "project_path_with_namespace": metadata.get("project_path_with_namespace"),
                **_serialize_common_breakdown(row),
            }
        )
    return items


def _serialize_initiators(rows: list) -> list[dict]:
    return [
        {
            "initiator_username": row.initiator_username,
            "initiator_gitlab_user_id": (
                int(row.initiator_gitlab_user_id)
                if row.initiator_gitlab_user_id is not None
                else None
            ),
            **_serialize_common_breakdown(row),
        }
        for row in rows
    ]


def _serialize_trends(rows: list, *, since: datetime, days: int) -> list[dict]:
    trend_map = {str(row.day): row for row in rows}
    trends = []
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
                "avg_execution_seconds": (
                    float(row.avg_execution_seconds)
                    if row and row.avg_execution_seconds is not None
                    else None
                ),
            }
        )
    return trends


def build_analytics_response(
    *,
    days: int,
    now: datetime,
    since: datetime,
    summary: AnalyticsSummary,
    project_rows: list,
    project_lookup: dict[int, dict],
    available_initiator_rows: list,
    initiator_rows: list,
    trend_rows: list,
    priority_wait_rows: list,
    issue_status_rows: list,
    task_status_rows: list,
    error_rows: list,
    provider_rows: list,
    harness_rows: list,
) -> dict:
    provider_items = _serialize_provider_rows(provider_rows)
    harness_items = _serialize_harness_rows(harness_rows)
    return {
        "window_days": days,
        "generated_at": now.isoformat(),
        "summary": summary.serialize(),
        "available_initiators": [
            {
                "initiator_username": row.initiator_username,
                "initiator_gitlab_user_id": (
                    int(row.initiator_gitlab_user_id)
                    if row.initiator_gitlab_user_id is not None
                    else None
                ),
                "task_count": int(row.task_count or 0),
            }
            for row in available_initiator_rows
        ],
        "projects": _serialize_projects(project_rows, project_lookup),
        "initiators": _serialize_initiators(initiator_rows),
        "provider_summary": {
            "active_provider_count": len(provider_items),
            "provider_covered_task_count": sum(item["task_count"] for item in provider_items),
            "provider_covered_total_tokens": sum(
                item["total_tokens"] for item in provider_items
            ),
            "provider_success_rate": safe_ratio(
                sum(item["completed_task_count"] for item in provider_items),
                sum(item["finished_task_count"] for item in provider_items),
            ),
        },
        "providers": provider_items,
        "provider_chart_series": build_provider_chart_series(provider_items),
        "harnesses": harness_items,
        "trends": _serialize_trends(trend_rows, since=since, days=days),
        "priority_waits": [
            {
                "priority": int(row.priority),
                "task_count": int(row.task_count or 0),
                "avg_queue_wait_seconds": _optional_float(row.avg_queue_wait_seconds),
                "max_queue_wait_seconds": _optional_float(row.max_queue_wait_seconds),
            }
            for row in priority_wait_rows
        ],
        "issue_status_breakdown": build_status_breakdown_rows(
            IssueStatus, issue_status_rows
        ),
        "task_status_breakdown": build_status_breakdown_rows(TaskStatus, task_status_rows),
        "error_breakdown": build_error_breakdown(
            [
                (str(row.error_message), int(row.count or 0))
                for row in error_rows
                if row.error_message
            ],
            int(summary.failed_tasks or 0),
        ),
    }
