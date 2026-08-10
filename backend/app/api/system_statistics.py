"""Admin-only system lifecycle statistics endpoints.

Three endpoints (overview / trends / breakdowns) implement the system lifecycle
statistics design §10. All routes are registered behind ``require_admin_user``
in ``app.main``; they must never reuse the normal-user Analytics permission.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.system_statistics_queries import (
    DEFAULT_BREAKDOWN_LIMIT,
    REPORTING_TIMEZONE,
    build_all_issue_statistics_cte,
    build_all_task_statistics_cte,
    build_current_state_issue_query,
    build_current_state_task_query,
    build_earliest_lifecycle_query,
    build_harness_breakdown,
    build_issue_created_trend,
    build_lifetime_issue_query,
    build_lifetime_task_query,
    build_project_breakdown,
    build_provider_breakdown,
    build_task_created_trend,
    build_task_deleted_trend,
    build_task_finished_trend,
    pick_bucket_for_all,
)
from app.core.utcnow import utcnow
from app.database import get_db
from app.models import SystemStatisticsMetadata

router = APIRouter()

_REFERENCE_STATEMENT = (
    "参考统计：仅覆盖当前仍保留的数据，以及从 {capture_started_at} 起通过标准删除入口保留的删除数据。"
)


def _int(value) -> int:
    return int(value or 0)


def _optional_float(value) -> float | None:
    return float(value) if value is not None else None


def _optional_int(value) -> int | None:
    return int(value) if value is not None else None


def _ratio(numerator, denominator) -> float | None:
    if denominator in (None, 0) or numerator is None:
        return None
    return float(numerator) / float(denominator)


def _bucket_to_iso(value) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _resolve_range(range_value: str, now: datetime) -> tuple[datetime | None, str]:
    if range_value == "90d":
        return now - timedelta(days=90), "day"
    if range_value == "1y":
        return now - timedelta(days=365), "week"
    return None, "month"


async def _coverage_from_metadata(db: AsyncSession, now: datetime) -> dict[str, Any]:
    meta = await db.get(SystemStatisticsMetadata, 1)
    capture_started_at = meta.capture_started_at if meta else None
    return {
        "capture_started_at": (
            capture_started_at.isoformat() if capture_started_at else None
        ),
        "capture_enabled": capture_started_at is not None,
        "statement": _REFERENCE_STATEMENT.format(
            capture_started_at=(
                capture_started_at.isoformat() if capture_started_at else "（尚未启用）"
            )
        ),
    }


@router.get("/admin/system-statistics/overview")
async def get_system_statistics_overview(
    project_id: int | None = Query(default=None),
    provider_id: int | None = Query(default=None),
    harness_key: str | None = Query(default=None),
    data_state: str = Query(default="all", pattern="^(all|retained|deleted)$"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    dialect = db.bind.dialect.name
    now = utcnow()

    all_tasks = build_all_task_statistics_cte(
        dialect=dialect,
        project_id=project_id,
        provider_id=provider_id,
        harness_key=harness_key,
        data_state=data_state,
    )
    all_issues = build_all_issue_statistics_cte(
        project_id=project_id,
        data_state=data_state,
    )

    current_state_row = (
        await db.execute(
            build_current_state_task_query(
                dialect=dialect,
                project_id=project_id,
                provider_id=provider_id,
                harness_key=harness_key,
                now=now,
            )
        )
    ).one()
    active_issues_row = (
        await db.execute(build_current_state_issue_query(project_id=project_id))
    ).one()
    lifetime_task_row = (
        await db.execute(build_lifetime_task_query(dialect, all_tasks))
    ).one()
    lifetime_issue_row = (
        await db.execute(build_lifetime_issue_query(all_issues))
    ).one()
    coverage = await _coverage_from_metadata(db, now)

    finished = (
        _int(lifetime_task_row.completed)
        + _int(lifetime_task_row.failed)
        + _int(lifetime_task_row.cancelled)
    )
    # NULL when no complete-token / no code-change sample exists: an unknown
    # aggregate must stay Unknown (§5.7), not read as an exact 0.
    known_total_tokens = (
        _int(lifetime_task_row.known_input_tokens)
        + _int(lifetime_task_row.known_output_tokens)
        if lifetime_task_row.known_input_tokens is not None
        or lifetime_task_row.known_output_tokens is not None
        else None
    )
    token_eligible = _int(lifetime_task_row.token_eligible_samples)
    code_eligible = _int(lifetime_task_row.code_eligible_samples)
    token_complete = _int(lifetime_task_row.token_complete_samples)
    code_available = _int(lifetime_task_row.change_available_samples)

    return {
        "as_of": now.isoformat(),
        "reporting_timezone": REPORTING_TIMEZONE,
        "current_state": {
            "pending": _int(current_state_row.pending),
            "queued": _int(current_state_row.queued),
            "running": _int(current_state_row.running),
            "long_running": _int(current_state_row.long_running),
            "active_issues": _int(active_issues_row.active_issues),
            "avg_queue_wait_seconds": _optional_float(
                current_state_row.avg_queue_wait_seconds
            ),
            "queue_wait_samples": _int(current_state_row.queue_wait_samples),
        },
        "lifetime": {
            "issue_count": _int(lifetime_issue_row.issue_count),
            "task_count": _int(lifetime_task_row.task_count),
            "completed": _int(lifetime_task_row.completed),
            "failed": _int(lifetime_task_row.failed),
            "cancelled": _int(lifetime_task_row.cancelled),
            "finished": finished,
            "success_rate": _ratio(_int(lifetime_task_row.completed), finished),
            "failure_rate": _ratio(_int(lifetime_task_row.failed), finished),
            "issues_with_mr": _int(lifetime_issue_row.issues_with_mr),
            "known_total_tokens": known_total_tokens,
            "known_total_changes": _optional_int(lifetime_task_row.known_total_changes),
            "known_total_execution_seconds": _optional_float(
                lifetime_task_row.known_execution_seconds
            ),
        },
        "deletion": {
            "deleted_task_count": _int(lifetime_task_row.deleted_task_count),
            "deleted_issue_count": _int(lifetime_issue_row.deleted_issue_count),
            "deleted_before_terminal": _int(lifetime_task_row.deleted_before_terminal),
        },
        "coverage": {
            **coverage,
            "token": {
                "eligible_samples": token_eligible,
                "complete_samples": token_complete,
                "partial_samples": _int(lifetime_task_row.token_partial_samples),
                "missing_samples": _int(lifetime_task_row.token_missing_samples),
                "coverage_rate": _ratio(token_complete, token_eligible),
            },
            "code": {
                "eligible_samples": code_eligible,
                "available_samples": code_available,
                "coverage_rate": _ratio(code_available, code_eligible),
            },
        },
    }


@router.get("/admin/system-statistics/trends")
async def get_system_statistics_trends(
    project_id: int | None = Query(default=None),
    provider_id: int | None = Query(default=None),
    harness_key: str | None = Query(default=None),
    data_state: str = Query(default="all", pattern="^(all|retained|deleted)$"),
    range: str = Query(default="all", pattern="^(90d|1y|all)$"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    dialect = db.bind.dialect.name
    now = utcnow()

    all_tasks = build_all_task_statistics_cte(
        dialect=dialect,
        project_id=project_id,
        provider_id=provider_id,
        harness_key=harness_key,
        data_state=data_state,
    )
    all_issues = build_all_issue_statistics_cte(
        project_id=project_id,
        data_state=data_state,
    )

    since, bucket = _resolve_range(range, now)
    if range == "all":
        earliest_at = (
            await db.execute(build_earliest_lifecycle_query(all_tasks, all_issues))
        ).scalar_one_or_none()
        bucket = pick_bucket_for_all(earliest_at, now)

    created_rows = list(
        (
            await db.execute(
                build_task_created_trend(all_tasks, dialect, bucket, since)
            )
        ).all()
    )
    finished_rows = list(
        (
            await db.execute(
                build_task_finished_trend(all_tasks, dialect, bucket, since)
            )
        ).all()
    )
    deleted_rows = list(
        (
            await db.execute(
                build_task_deleted_trend(all_tasks, dialect, bucket, since)
            )
        ).all()
    )
    issue_rows = list(
        (
            await db.execute(
                build_issue_created_trend(all_issues, dialect, bucket, since)
            )
        ).all()
    )

    return {
        "as_of": now.isoformat(),
        "reporting_timezone": REPORTING_TIMEZONE,
        "range": range,
        "bucket": bucket,
        "series": [
            {
                "time_basis": "created_at",
                "values": [
                    {"bucket": _bucket_to_iso(row.bucket), "task_count": _int(row.task_count)}
                    for row in created_rows
                ],
            },
            {
                "time_basis": "terminal_at",
                "values": [
                    {
                        "bucket": _bucket_to_iso(row.bucket),
                        "task_count": _int(row.task_count),
                        "completed": _int(row.completed),
                        "failed": _int(row.failed),
                        "cancelled": _int(row.cancelled),
                        "known_total_tokens": _int(row.known_input_tokens)
                        + _int(row.known_output_tokens),
                        "known_total_changes": _int(row.known_total_changes),
                        "known_execution_seconds": _optional_float(
                            row.known_execution_seconds
                        ),
                    }
                    for row in finished_rows
                ],
            },
            {
                "time_basis": "source_deleted_at",
                "values": [
                    {"bucket": _bucket_to_iso(row.bucket), "task_count": _int(row.task_count)}
                    for row in deleted_rows
                ],
            },
            {
                "time_basis": "issue_created_at",
                "values": [
                    {"bucket": _bucket_to_iso(row.bucket), "issue_count": _int(row.issue_count)}
                    for row in issue_rows
                ],
            },
        ],
    }


def _top_n_with_unknown(rows: list[dict], *, limit: int) -> list[dict]:
    """Take the Top N rows by task_count, keeping the Unknown group visible."""
    ranked = sorted(
        rows, key=lambda item: (-item["task_count"], str(item.get("label") or ""))
    )
    top = [item for item in ranked if item.get("key") is not None][:limit]
    unknown = next((item for item in ranked if item.get("key") is None), None)
    if unknown is not None and unknown not in top:
        top.append(unknown)
    return top


def _serialize_breakdown_row(row, *, key: str | None, label: str | None) -> dict:
    completed = _int(row.completed)
    finished = completed + _int(row.failed) + _int(row.cancelled)
    return {
        "key": key,
        "label": label if label is not None else "Unknown",
        "task_count": _int(row.task_count),
        "completed": completed,
        "failed": _int(row.failed),
        "cancelled": _int(row.cancelled),
        "success_rate": _ratio(completed, finished),
        "deleted_count": _int(row.deleted_count),
        "known_total_tokens": _int(row.known_input_tokens) + _int(
            row.known_output_tokens
        ),
        "known_total_changes": _int(row.known_total_changes),
    }


@router.get("/admin/system-statistics/breakdowns")
async def get_system_statistics_breakdowns(
    project_id: int | None = Query(default=None),
    provider_id: int | None = Query(default=None),
    harness_key: str | None = Query(default=None),
    data_state: str = Query(default="all", pattern="^(all|retained|deleted)$"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    dialect = db.bind.dialect.name
    now = utcnow()

    all_tasks = build_all_task_statistics_cte(
        dialect=dialect,
        project_id=project_id,
        provider_id=provider_id,
        harness_key=harness_key,
        data_state=data_state,
    )

    project_rows = list((await db.execute(build_project_breakdown(dialect, all_tasks))).all())
    provider_rows = list((await db.execute(build_provider_breakdown(dialect, all_tasks))).all())
    harness_rows = list((await db.execute(build_harness_breakdown(dialect, all_tasks))).all())

    projects = [
        {
            **_serialize_breakdown_row(
                row,
                key=str(row.key) if row.key is not None else None,
                label=f"Project {row.key}" if row.key is not None else None,
            ),
            "project_id": int(row.key) if row.key is not None else None,
        }
        for row in project_rows
    ]
    providers = [
        {
            **_serialize_breakdown_row(
                row,
                key=str(row.key) if row.key is not None else None,
                label=row.label,
            ),
            "provider_id": int(row.key) if row.key is not None else None,
        }
        for row in provider_rows
    ]
    harnesses = [
        _serialize_breakdown_row(
            row, key=str(row.key) if row.key is not None else None, label=row.key
        )
        for row in harness_rows
    ]

    return {
        "as_of": now.isoformat(),
        "reporting_timezone": REPORTING_TIMEZONE,
        "projects": _top_n_with_unknown(projects, limit=DEFAULT_BREAKDOWN_LIMIT),
        "providers": _top_n_with_unknown(providers, limit=DEFAULT_BREAKDOWN_LIMIT),
        "harnesses": _top_n_with_unknown(harnesses, limit=DEFAULT_BREAKDOWN_LIMIT),
    }
